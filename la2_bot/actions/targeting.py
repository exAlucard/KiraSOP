"""Модуль с логикой управления целями, лутом и свипом."""

import time
import random
import threading

from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.core.comm import send_command
from la2_bot.core.state import pause_event
from la2_bot.detection.hp_bar_detection import get_hp_measurement
from la2_bot.ui.bot_menu import is_flag_enabled, get_target_count_mode
from la2_bot.utils.threat_watcher import (
    schedule_threat_watch,
    schedule_live_full_target_antiaggro,
    schedule_engaged_full_target_recheck,
    schedule_no_target_antiaggro,
    is_threat_watcher_active,
    is_threat_watcher_acquiring,
    is_live_full_target_pending,
    is_engaged_full_target_recheck_pending,
    is_anti_aggro_target_active,
    is_anti_aggro_priority_active,
    get_anti_aggro_target_age,
    clear_anti_aggro_target,
    get_threat_watcher_phase,
    get_current_watch_id,
    get_target_probe,
    begin_post_kill_sweep_gate,
    end_post_kill_sweep_gate,
)
from la2_bot.core.debug_state import is_next_target_on_cooldown, set_next_target_cooldown
from la2_bot.utils.target_utils import is_target_selected, is_target_hp_damaged
from la2_bot.utils.antiaggro_diagnostics import log_event, log_event_throttled, save_debug_snapshot


_rapid_search_lock = threading.Lock()
_rapid_search_thread = None


def _raw_target_present():
    """Быстрая проверка появления HP-полоски цели без дополнительных фильтров."""
    point = getattr(coordinate_utils, 'TARGET_HP_1_POINT', None)
    if not point:
        return False
    try:
        return is_target_color(get_pixel_color(*point))
    except Exception:
        return False


def _rapid_target_search_worker(ser, state):
    """Отдельный worker нормального поиска цели с темпом около 10 команд/сек.

    Worker нужен вместо простого уменьшения cooldown: основной bot_loop иногда
    занят OCR/скиллами, поэтому один только cooldown не гарантирует 10 Гц.
    Поиск прекращается сразу при появлении HP-полоски цели, выключении кнопки,
    паузе бота или захвате приоритета anti-aggro.
    """
    global _rapid_search_thread
    stop_reason = 'unknown'
    command_count = 0

    log_event(
        'RAPID_TARGET_SEARCH_START',
        level='info',
        rate_hz=10.0,
        target_count_mode=get_target_count_mode(),
        target_before=get_target_probe(),
    )

    try:
        while True:
            if not pause_event.is_set():
                stop_reason = 'bot_paused'
                break

            if not is_flag_enabled('next_target'):
                stop_reason = 'next_target_disabled'
                break

            if not is_flag_enabled('rapid_target_search'):
                stop_reason = 'rapid_search_disabled'
                break

            watcher_active = is_threat_watcher_active()
            anti_target = is_anti_aggro_target_active()
            priority_active = is_anti_aggro_priority_active()
            if watcher_active or anti_target or priority_active:
                stop_reason = 'antiaggro_priority'
                break

            # Как только игра показала HP цели, больше 5/6 не жмём.
            # Основной цикл отдельно проверит selected/full/damaged.
            if _raw_target_present():
                stop_reason = 'target_appeared'
                break

            # Уважаем cooldown других подсистем (AltHeal, AltDS, anti-aggro и т.д.).
            if is_next_target_on_cooldown():
                time.sleep(0.02)
                continue

            target_count_mode = get_target_count_mode()
            command = 'NEXT_TARGET'
            if target_count_mode == 2:
                if state.get('last_target_index', 0) == 0:
                    command = 'NEXT_TARGET'
                    state['last_target_index'] = 1
                else:
                    command = 'NEXT_TARGET_2'
                    state['last_target_index'] = 0

            log_event(
                'RAPID_TARGET_SEARCH_COMMAND',
                level='debug',
                command=command,
                target_count_mode=target_count_mode,
                command_index=command_count + 1,
                interval=0.10,
                target_before=get_target_probe(),
            )
            send_command(ser, command)
            command_count += 1

            try:
                state['last_target_switch_ts'] = time.time()
            except Exception:
                pass

            # Не даём другим вызовам обычного поиска вклиниться между импульсами.
            set_next_target_cooldown(0.10)
            time.sleep(0.10)

    except Exception as exc:
        stop_reason = 'worker_exception'
        log_event(
            'RAPID_TARGET_SEARCH_ERROR',
            level='error',
            error=repr(exc),
            commands=command_count,
        )
    finally:
        log_event(
            'RAPID_TARGET_SEARCH_STOP',
            level='info',
            reason=stop_reason,
            commands=command_count,
            target_after=get_target_probe(),
        )
        with _rapid_search_lock:
            if _rapid_search_thread is threading.current_thread():
                _rapid_search_thread = None


def _ensure_rapid_target_search(ser, state):
    global _rapid_search_thread
    with _rapid_search_lock:
        if _rapid_search_thread is not None and _rapid_search_thread.is_alive():
            return False
        thread = threading.Thread(
            target=_rapid_target_search_worker,
            args=(ser, state),
            name='rapid_target_search',
            daemon=True,
        )
        _rapid_search_thread = thread
        thread.start()
        return True


def find_new_target(ser, state):
    """Централизованный поиск новой цели с учетом cooldown и anti-aggro.

    v8: флаг ``rapid_target_search`` запускает отдельный worker, который
    отправляет обычные команды поиска примерно 10 раз/сек до появления цели.
    В режиме двух целей чередуются NEXT_TARGET / NEXT_TARGET_2 (5 / 6).
    Anti-aggro NEAREST_TARGET этим режимом не затрагивается.
    """
    watcher_active = is_threat_watcher_active()
    anti_target = is_anti_aggro_target_active()
    priority_active = is_anti_aggro_priority_active()

    if watcher_active or anti_target or priority_active:
        log_event_throttled(
            "find_target_blocked_antiaggro",
            1.0,
            "FIND_TARGET_BLOCKED",
            level="debug",
            reason="watcher_or_antiaggro_target",
            watcher_active=watcher_active,
            antiaggro_target=anti_target,
            priority_active=priority_active,
            phase=get_threat_watcher_phase(),
            watch_id=get_current_watch_id(),
        )
        return

    if not is_flag_enabled('next_target'):
        log_event_throttled(
            "find_target_disabled",
            3.0,
            "FIND_TARGET_BLOCKED",
            level="debug",
            reason="next_target_disabled",
        )
        return

    # x10 работает своим worker'ом и сам учитывает текущий cooldown.
    if is_flag_enabled('rapid_target_search'):
        _ensure_rapid_target_search(ser, state)
        return

    if is_next_target_on_cooldown():
        log_event_throttled(
            "find_target_blocked_cooldown",
            1.0,
            "FIND_TARGET_BLOCKED",
            level="debug",
            reason="cooldown",
        )
        return

    target_count_mode = get_target_count_mode()
    command = 'NEXT_TARGET'

    if target_count_mode == 2:
        if state.get('last_target_index', 0) == 0:
            command = 'NEXT_TARGET'
            state['last_target_index'] = 1
        else:
            command = 'NEXT_TARGET_2'
            state['last_target_index'] = 0

    log_event(
        "NORMAL_TARGET_COMMAND",
        level="debug",
        command=command,
        target_count_mode=target_count_mode,
        rapid_search=False,
        search_interval=float(config.TARGET_SWITCH_DELAY),
        target_before=get_target_probe(),
    )
    send_command(ser, command)

    set_next_target_cooldown(config.TARGET_SWITCH_DELAY)
    try:
        state['last_target_switch_ts'] = time.time()
    except Exception:
        pass


def has_valid_current_target():
    if not coordinate_utils.TARGET_HP_1_POINT:
        return False

    target_alive = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))
    if not target_alive:
        return False

    if not is_target_selected():
        return False

    # Anti-aggro цель может быть уже повреждена — ее нужно добивать, а не выкидывать.
    if is_flag_enabled('skip_damaged_target') and not is_anti_aggro_target_active():
        is_target_full_hp = False
        if getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None):
            is_target_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))
        if not is_target_full_hp and is_target_hp_damaged():
            return False

    return True


def _sleep_interruptible_by_anti_aggro(duration, step=0.03):
    end_time = time.time() + max(0.0, float(duration))
    while time.time() < end_time:
        if is_anti_aggro_priority_active():
            return False
        remaining = end_time - time.time()
        time.sleep(min(step, max(0.0, remaining)))
    return True


def _loot_command(ser, command, delay_after=None):
    if is_anti_aggro_priority_active():
        return False

    log_event(
        "LOOT_COMMAND",
        level="debug",
        command=command,
        phase=get_threat_watcher_phase(),
        watch_id=get_current_watch_id(),
    )
    send_command(ser, command)

    if delay_after is not None:
        return _sleep_interruptible_by_anti_aggro(delay_after)
    return True


def _probe_target_is_full_hp(probe):
    """Возвращает True, если контрольная точка полного HP цели красная."""
    if not probe:
        return False
    rgb = probe.get("full_rgb")
    return isinstance(rgb, tuple) and is_target_color(rgb)


def _live_full_target_drop_threshold(measurement):
    """Порог для перехвата агра, пока выбранная цель ещё имеет full HP."""
    if measurement and measurement.get("method") == "ocr_numeric":
        try:
            return max(1.0, float(getattr(
                config,
                "THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD_ABS",
                getattr(config, "THREAT_HP_DROP_THRESHOLD_ABS", 4.0),
            )))
        except (TypeError, ValueError):
            return 4.0
    try:
        return max(0.1, float(getattr(
            config,
            "THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD",
            getattr(config, "THREAT_HP_DROP_THRESHOLD", 1.0),
        )))
    except (TypeError, ValueError):
        return 1.0



def _no_target_drop_threshold(measurement):
    """Порог входящего урона, когда у бота вообще нет выбранной цели."""
    if measurement and measurement.get("method") == "ocr_numeric":
        try:
            return max(1.0, float(getattr(
                config,
                "THREAT_NO_TARGET_DROP_THRESHOLD_ABS",
                getattr(config, "THREAT_HP_DROP_THRESHOLD_ABS", 4.0),
            )))
        except (TypeError, ValueError):
            return 4.0
    try:
        return max(0.1, float(getattr(
            config,
            "THREAT_NO_TARGET_DROP_THRESHOLD",
            getattr(config, "THREAT_HP_DROP_THRESHOLD", 1.0),
        )))
    except (TypeError, ValueError):
        return 1.0

def _ocr_confidence_ok(current_measurement, previous_confidence):
    """Отсекает одиночные OCR-провалы до запуска live anti-aggro."""
    if not current_measurement or current_measurement.get("method") != "ocr_numeric":
        return True
    try:
        min_conf = float(getattr(config, "THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE", 70.0))
    except (TypeError, ValueError):
        min_conf = 70.0
    current_conf = current_measurement.get("ocr_confidence")
    try:
        current_ok = current_conf is not None and float(current_conf) >= min_conf
    except (TypeError, ValueError):
        current_ok = False
    if previous_confidence is None:
        return current_ok
    try:
        return current_ok and float(previous_confidence) >= min_conf
    except (TypeError, ValueError):
        return False


def _log_target_state(ser, state, *, raw_alive, selected_ok, damaged, accepted, anti_target):
    """Логирует таргет и постоянно контролирует HP персонажа для anti-aggro.

    v7: HP персонажа читается не только при живой цели, но и когда таргета
    вообще нет. Именно этот постоянный IDLE-monitor закрывает окно после
    завершения post-death watcher: если бота продолжают бить, anti-aggro
    запускается от нового подтверждённого падения HP.
    """
    phase = get_threat_watcher_phase()
    watcher_active = is_threat_watcher_active()

    signature = (
        bool(raw_alive),
        bool(selected_ok),
        bool(damaged),
        bool(accepted),
        bool(anti_target),
        bool(watcher_active),
        phase,
    )
    old_signature = state.get('_antiaggro_diag_target_signature')
    now_mono = time.monotonic()
    probe = None
    live_intercept_started = False
    no_target_intercept_started = False

    base_fields = {
        "raw_alive": raw_alive,
        "selected_ok": selected_ok,
        "damaged": damaged,
        "accepted": accepted,
        "antiaggro_target": anti_target,
        "watcher_active": watcher_active,
        "phase": phase,
        "watch_id": get_current_watch_id(),
        "was_hp1_red": state.get('was_hp1_red'),
    }

    if signature != old_signature:
        state['_antiaggro_diag_target_signature'] = signature
        probe = get_target_probe()
        log_event("TARGET_STATE_CHANGED", probe=probe, **base_fields)
    else:
        last_heartbeat = state.get('_antiaggro_diag_heartbeat_ts', 0.0)
        if now_mono - last_heartbeat >= 2.0:
            state['_antiaggro_diag_heartbeat_ts'] = now_mono
            probe = get_target_probe()
            log_event("TARGET_STATE_HEARTBEAT", level="debug", probe=probe, **base_fields)

    # v7: character-HP monitor работает постоянно, пока включён anti_agr.
    # Для живой цели сохраняется live-full логика v6. При отсутствии цели тот
    # же поток измерений может напрямую запустить NO_TARGET anti-aggro.
    if is_flag_enabled('anti_agr') and not watcher_active:
        sample_interval = 0.50 if raw_alive else 0.35
        last_live_hp_ts = state.get('_antiaggro_diag_live_hp_mono', 0.0)

        if now_mono - last_live_hp_ts >= sample_interval:
            state['_antiaggro_diag_live_hp_mono'] = now_mono
            measurement = get_hp_measurement(include_image=False)
            hp_value = measurement.get('percentage')

            previous_live_hp = state.get('_antiaggro_diag_last_char_hp')
            previous_live_hp_ts = state.get('_antiaggro_diag_last_char_hp_wall_ts')
            previous_live_confidence = state.get('_antiaggro_diag_last_char_hp_confidence')
            now_wall = time.time()
            sample_gap = (
                now_wall - previous_live_hp_ts
                if previous_live_hp_ts is not None else None
            )

            if hp_value is not None and previous_live_hp is not None:
                try:
                    hp_drop = float(previous_live_hp) - float(hp_value)
                except (TypeError, ValueError):
                    hp_drop = 0.0

                if hp_drop > 0:
                    target_probe = probe if probe is not None else get_target_probe()
                    confidence_ok = _ocr_confidence_ok(
                        measurement, previous_live_confidence
                    )

                    if raw_alive:
                        full_scenario_enabled = is_flag_enabled('anti_agr_full_hp')
                        # FULL-target path:
                        # - обычная цель: v6 даёт ей 2 секунды начать терять HP;
                        # - уже выбранная anti-aggro цель: v12 больше не считается
                        #   автоматически правильной навсегда. Если она долго
                        #   остаётся FULL HP, а персонаж продолжает получать урон,
                        #   запускается отдельная проверка и принудительный cycle.
                        target_full_hp = _probe_target_is_full_hp(target_probe)
                        live_threshold = _live_full_target_drop_threshold(measurement)
                        live_pending = is_live_full_target_pending()
                        engaged_recheck_pending = is_engaged_full_target_recheck_pending()
                        anti_target_age = get_anti_aggro_target_age() if anti_target else None
                        try:
                            engaged_min_age = max(
                                1.0,
                                float(getattr(
                                    config,
                                    "THREAT_ENGAGED_FULL_RECHECK_MIN_AGE",
                                    3.0,
                                )),
                            )
                        except (TypeError, ValueError):
                            engaged_min_age = 3.0

                        recent_sample = sample_gap is not None and sample_gap <= 1.5
                        should_intercept = bool(
                            full_scenario_enabled
                            and target_full_hp
                            and hp_drop >= live_threshold
                            and confidence_ok
                            and not anti_target
                            and not watcher_active
                            and not live_pending
                            and phase == 'IDLE'
                        )
                        should_recheck_engaged = bool(
                            full_scenario_enabled
                            and target_full_hp
                            and hp_drop >= live_threshold
                            and confidence_ok
                            and anti_target
                            and phase == 'ENGAGED'
                            and not watcher_active
                            and not engaged_recheck_pending
                            and recent_sample
                            and anti_target_age is not None
                            and anti_target_age >= engaged_min_age
                        )

                        action = "diagnostic_only_no_retarget"
                        reason = "current target is already damaged or anti-aggro is busy"
                        if not full_scenario_enabled:
                            reason = "THREAT_SCENARIO_FULL_HP_ENABLED=False"
                        elif live_pending:
                            reason = "2s live full-target decision window is already running"
                        elif engaged_recheck_pending:
                            reason = "engaged anti-aggro target recheck is already running"
                        elif target_full_hp and not confidence_ok:
                            reason = "full target, but OCR confidence is too low for forced retarget"
                        elif target_full_hp and hp_drop < live_threshold:
                            reason = "full target, but HP drop is below live anti-aggro threshold"
                        elif should_recheck_engaged:
                            action = "schedule_engaged_full_target_recheck"
                            reason = (
                                "anti-aggro target stayed full HP long enough while "
                                "character keeps taking damage"
                            )
                        elif (
                            anti_target
                            and target_full_hp
                            and phase == 'ENGAGED'
                            and anti_target_age is not None
                            and anti_target_age < engaged_min_age
                        ):
                            reason = "engaged anti-aggro target is still inside initial combat/spoil grace"
                        elif anti_target and target_full_hp and not recent_sample:
                            reason = "engaged anti-aggro HP sample gap is too large for a safe recheck"
                        elif should_intercept:
                            action = "schedule_live_full_target_antiaggro"
                            reason = "target is full HP and character HP dropped before engagement"

                        log_event(
                            "LIVE_TARGET_HP_DROP_WHILE_TARGET_ALIVE",
                            level="warning" if hp_drop >= live_threshold else "debug",
                            previous_hp=previous_live_hp,
                            current_hp=hp_value,
                            drop=hp_drop,
                            threshold=live_threshold,
                            sample_gap=sample_gap,
                            current_ocr_confidence=measurement.get('ocr_confidence'),
                            previous_ocr_confidence=previous_live_confidence,
                            confidence_ok=confidence_ok,
                            full_hp_scenario_enabled=full_scenario_enabled,
                            target_full_hp=target_full_hp,
                            antiaggro_target=anti_target,
                            antiaggro_target_age=anti_target_age,
                            engaged_recheck_min_age=engaged_min_age,
                            engaged_recheck_pending=engaged_recheck_pending,
                            watcher_active=watcher_active,
                            phase=phase,
                            target=target_probe,
                            action=action,
                            reason=reason,
                        )

                        if should_recheck_engaged:
                            recheck_started = schedule_engaged_full_target_recheck(
                                ser,
                                baseline_hp=previous_live_hp,
                                observed_hp=hp_value,
                                baseline_age=sample_gap,
                                target_probe=target_probe,
                                observed_measurement=measurement,
                            )
                            log_event(
                                "ENGAGED_FULL_TARGET_RECHECK_SCHEDULE_RESULT",
                                level="warning" if recheck_started else "error",
                                scheduled=recheck_started,
                                previous_hp=previous_live_hp,
                                current_hp=hp_value,
                                drop=hp_drop,
                                antiaggro_target_age=anti_target_age,
                                target=target_probe,
                                phase=get_threat_watcher_phase(),
                                watch_id=get_current_watch_id(),
                            )
                            if recheck_started:
                                phase = get_threat_watcher_phase()

                        elif should_intercept:
                            live_intercept_started = schedule_live_full_target_antiaggro(
                                ser,
                                baseline_hp=previous_live_hp,
                                observed_hp=hp_value,
                                baseline_age=sample_gap,
                                target_probe=target_probe,
                                observed_measurement=measurement,
                            )
                            log_event(
                                "LIVE_FULL_TARGET_INTERCEPT_SCHEDULE_RESULT",
                                level="warning" if live_intercept_started else "error",
                                scheduled=live_intercept_started,
                                previous_hp=previous_live_hp,
                                current_hp=hp_value,
                                drop=hp_drop,
                                target=target_probe,
                                phase=get_threat_watcher_phase(),
                                watch_id=get_current_watch_id(),
                            )
                            if live_intercept_started:
                                # PENDING не блокирует обычный бой; значение
                                # watcher_active здесь нужно только для логов.
                                phase = get_threat_watcher_phase()

                    else:
                        kill_scenario_enabled = is_flag_enabled('anti_agr_kill')
                        # v7: НЕТ ЦЕЛИ. Здесь уже нет неоднозначности "может
                        # текущий моб сам меня бьёт": если HP падает, а valid
                        # target отсутствует, это прямой повод искать агрессора.
                        no_target_threshold = _no_target_drop_threshold(measurement)
                        max_gap = 1.5
                        recent_enough = sample_gap is not None and sample_gap <= max_gap
                        should_intercept = bool(
                            kill_scenario_enabled
                            and hp_drop >= no_target_threshold
                            and confidence_ok
                            and recent_enough
                            and not anti_target
                            and not watcher_active
                            and not is_live_full_target_pending()
                            and phase == 'IDLE'
                        )

                        action = (
                            "schedule_no_target_antiaggro"
                            if should_intercept
                            else "diagnostic_only"
                        )
                        if not kill_scenario_enabled:
                            reason = "THREAT_SCENARIO_KILL_ENABLED=False"
                        elif watcher_active:
                            reason = "post-death/other watcher is already active"
                        elif is_live_full_target_pending():
                            reason = "live full-target pending is active"
                        elif not recent_enough:
                            reason = "previous HP sample is too old"
                        elif not confidence_ok:
                            reason = "OCR confidence is too low"
                        elif hp_drop < no_target_threshold:
                            reason = "HP drop is below no-target threshold"
                        elif phase != 'IDLE' or anti_target:
                            reason = "anti-aggro is already busy"
                        else:
                            reason = "character HP dropped while no valid target exists"

                        log_event(
                            "NO_TARGET_HP_DROP_DETECTED",
                            level="warning" if hp_drop >= no_target_threshold else "debug",
                            previous_hp=previous_live_hp,
                            current_hp=hp_value,
                            drop=hp_drop,
                            threshold=no_target_threshold,
                            sample_gap=sample_gap,
                            recent_enough=recent_enough,
                            current_ocr_confidence=measurement.get('ocr_confidence'),
                            previous_ocr_confidence=previous_live_confidence,
                            confidence_ok=confidence_ok,
                            kill_scenario_enabled=kill_scenario_enabled,
                            antiaggro_target=anti_target,
                            watcher_active=watcher_active,
                            live_full_pending=is_live_full_target_pending(),
                            phase=phase,
                            target=target_probe,
                            action=action,
                            reason=reason,
                        )

                        if should_intercept:
                            no_target_intercept_started = schedule_no_target_antiaggro(
                                ser,
                                baseline_hp=previous_live_hp,
                                observed_hp=hp_value,
                                baseline_age=sample_gap,
                                observed_measurement=measurement,
                                target_probe=target_probe,
                            )
                            log_event(
                                "NO_TARGET_INTERCEPT_SCHEDULE_RESULT",
                                level=(
                                    "warning"
                                    if no_target_intercept_started
                                    else "error"
                                ),
                                scheduled=no_target_intercept_started,
                                previous_hp=previous_live_hp,
                                current_hp=hp_value,
                                drop=hp_drop,
                                target=target_probe,
                                phase=get_threat_watcher_phase(),
                                watch_id=get_current_watch_id(),
                            )
                            if no_target_intercept_started:
                                watcher_active = True
                                phase = get_threat_watcher_phase()

            # Храним последний ВАЛИДНЫЙ sample. При OCR=None не стираем
            # baseline: иначе один нечитаемый кадр создаёт слепое окно.
            if hp_value is not None:
                state['_antiaggro_diag_last_char_hp'] = hp_value
                state['_antiaggro_diag_last_char_hp_wall_ts'] = now_wall
                state['_antiaggro_diag_last_char_hp_confidence'] = measurement.get(
                    'ocr_confidence'
                )

            log_event(
                "LIVE_TARGET_HP_SAMPLE" if raw_alive else "NO_TARGET_HP_SAMPLE",
                level="debug" if hp_value is not None else "warning",
                hp=hp_value,
                measurement={
                    "bbox": measurement.get('bbox'),
                    "size": measurement.get('size'),
                    "method": measurement.get('method'),
                    "ocr_text": measurement.get('ocr_text'),
                    "ocr_confidence": measurement.get('ocr_confidence'),
                    "ocr_pass": measurement.get('ocr_pass'),
                    "row_spread": measurement.get('row_spread'),
                    "rows": measurement.get('rows'),
                    "error": measurement.get('error'),
                },
                target_alive=raw_alive,
                watcher_active=watcher_active,
                phase=phase,
            )

            if not raw_alive:
                last_idle_notice = state.get('_antiaggro_no_target_monitor_notice_mono', 0.0)
                if now_mono - last_idle_notice >= 3.0:
                    state['_antiaggro_no_target_monitor_notice_mono'] = now_mono
                    log_event(
                        "NO_TARGET_MONITOR_HEARTBEAT",
                        level="info",
                        hp=hp_value,
                        phase=phase,
                        watcher_active=watcher_active,
                        target=(probe if probe is not None else get_target_probe()),
                        hint=(
                            "v7 IDLE-monitor активен: при подтвержденном падении HP "
                            "без валидной цели будет запущен NO_TARGET anti-aggro."
                        ),
                    )

            if hp_value is None:
                last_bad_snapshot = state.get(
                    '_antiaggro_diag_bad_hp_snapshot_mono', 0.0
                )
                if now_mono - last_bad_snapshot >= 5.0:
                    state['_antiaggro_diag_bad_hp_snapshot_mono'] = now_mono
                    save_debug_snapshot(
                        (
                            "live_target_hp_unreadable"
                            if raw_alive else "no_target_hp_unreadable"
                        ),
                        metadata={"measurement": measurement},
                    )

    if (
        raw_alive
        and is_flag_enabled('anti_agr_full_hp')
        and not watcher_active
        and not anti_target
        and not live_intercept_started
        and not is_live_full_target_pending()
    ):
        last_notice = state.get('_antiaggro_diag_live_notice_ts', 0.0)
        if now_mono - last_notice >= 3.0:
            state['_antiaggro_diag_live_notice_ts'] = now_mono
            if probe is None:
                probe = get_target_probe()
            log_event(
                "ANTIAGGRO_LIVE_TARGET_MONITOR_ACTIVE",
                level="debug",
                phase=phase,
                watch_id=get_current_watch_id(),
                hint=(
                    "При FULL HP цели входящий урон запускает 2s PENDING; "
                    "при поврежденной цели blind-retarget не выполняется."
                ),
                probe=probe,
            )

    return live_intercept_started or no_target_intercept_started


def main_target_loot_and_sweep(ser, state):
    """Основной цикл работы с целью, loot/sweep и anti-aggro."""
    if not coordinate_utils.TARGET_HP_1_POINT:
        log_event_throttled(
            "target_hp1_missing",
            3.0,
            "TARGET_HP1_POINT_MISSING",
            level="error",
        )
        return state

    now = time.time()
    anti_aggro_target = is_anti_aggro_target_active()
    hp1_rgb = get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT)
    is_target_alive_raw = is_target_color(hp1_rgb)

    last_switch_ts = state.get('last_target_switch_ts')
    in_switch_grace = (
        last_switch_ts is not None
        and (now - last_switch_ts) < max(0.4, min(1.0, config.TARGET_SWITCH_DELAY))
    )

    is_selected_ok = (not is_target_alive_raw) or is_target_selected()

    is_target_damaged = False
    if is_flag_enabled('skip_damaged_target') and not anti_aggro_target:
        if is_target_alive_raw:
            is_target_full_hp = False
            if getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None):
                is_target_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))
            if not is_target_full_hp:
                is_target_damaged = is_target_hp_damaged()

    is_target_alive = is_target_alive_raw and is_selected_ok and (not is_target_damaged)

    live_intercept_started = _log_target_state(
        ser,
        state,
        raw_alive=is_target_alive_raw,
        selected_ok=is_selected_ok,
        damaged=is_target_damaged,
        accepted=is_target_alive,
        anti_target=anti_aggro_target,
    )

    # v6: сам факт schedule live full-target теперь означает только PENDING.
    # В эти 2 секунды НЕ выходим из main-loop: spoil/обычная атака должны
    # продолжиться, чтобы текущий моб успел потерять HP. Выходим только когда
    # pending уже повысился до реальной фазы ACQUIRING перед ESC/retarget.
    if is_threat_watcher_acquiring():
        state['was_hp1_red'] = is_target_alive_raw
        return state

    if anti_aggro_target and is_target_alive_raw and not is_selected_ok:
        invalid_since = state.get('invalid_target_since')
        if invalid_since is None:
            state['invalid_target_since'] = now
            invalid_since = now
            log_event(
                "ANTIAGGRO_TARGET_SELECTION_LOST",
                level="warning",
                grace=0.75,
                target=get_target_probe(),
            )

        if now - invalid_since >= 0.75:
            log_event(
                "ANTIAGGRO_TARGET_RELEASE_SELECTION_LOST",
                level="error",
                target=get_target_probe(),
            )
            save_debug_snapshot(
                "antiaggro_target_selection_lost",
                metadata={"target": get_target_probe()},
            )
            clear_anti_aggro_target('таргет перестал подтверждаться')
            state['invalid_target_since'] = None
            find_new_target(ser, state)

        state['was_hp1_red'] = is_target_alive_raw
        return state

    if is_target_alive_raw and not is_target_alive:
        invalid_since = state.get('invalid_target_since')
        if invalid_since is None:
            state['invalid_target_since'] = now
            invalid_since = now
            log_event(
                "TARGET_REJECTED",
                level="warning",
                reason=("not_selected" if not is_selected_ok else "damaged_target"),
                in_switch_grace=in_switch_grace,
                target=get_target_probe(),
            )

        if (not in_switch_grace) and (now - invalid_since >= 0.1):
            log_event(
                "TARGET_REJECTED_SWITCHING",
                reason=("not_selected" if not is_selected_ok else "damaged_target"),
                invalid_for=now - invalid_since,
            )
            find_new_target(ser, state)
            state['invalid_target_since'] = None

        state['was_hp1_red'] = is_target_alive_raw
        return state

    state['invalid_target_since'] = None

    # Проверка на застрявшую цель.
    if is_target_alive and is_flag_enabled('stuck_target'):
        full_point = getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None)
        is_target_full_hp = bool(full_point and is_target_color(get_pixel_color(*full_point)))

        if is_target_full_hp:
            if state.get('target_full_hp_since') is None:
                state['target_full_hp_since'] = now

            if now - state['target_full_hp_since'] > config.STUCK_TARGET_TIMEOUT:
                log_event(
                    "TARGET_STUCK",
                    level="warning",
                    timeout=config.STUCK_TARGET_TIMEOUT,
                    antiaggro_target=anti_aggro_target,
                    target=get_target_probe(),
                )
                if anti_aggro_target:
                    clear_anti_aggro_target('цель признана застрявшей')
                send_command(ser, 'ESC')
                time.sleep(0.5)
                find_new_target(ser, state)
                state['target_full_hp_since'] = None
                state['was_hp1_red'] = False
                return state
        else:
            state['target_full_hp_since'] = None
    else:
        state['target_full_hp_since'] = None

    # Главный переход: цель была жива, теперь контрольный HP-пиксель не красный.
    if state.get('was_hp1_red') and not is_target_alive_raw:
        log_event(
            "TARGET_DEATH_TRANSITION",
            level="warning",
            hp1_rgb=hp1_rgb,
            antiaggro_enabled=is_flag_enabled('anti_agr'),
            antiaggro_kill_enabled=is_flag_enabled('anti_agr_kill'),
            antiaggro_full_hp_enabled=is_flag_enabled('anti_agr_full_hp'),
            antiaggro_target_was_active=anti_aggro_target,
            target_probe=get_target_probe(),
            predeath_char_hp=state.get('_antiaggro_diag_last_char_hp'),
            predeath_char_hp_age=(
                time.time() - state.get('_antiaggro_diag_last_char_hp_wall_ts')
                if state.get('_antiaggro_diag_last_char_hp_wall_ts') else None
            ),
        )
        state['was_hp1_red'] = False

        if anti_aggro_target:
            clear_anti_aggro_target('цель умерла')

        # v9: свип имеет абсолютный приоритет перед сменой цели anti-aggro.
        # Watcher запускаем сразу, чтобы он не пропустил входящий удар, но
        # закрываем sweep-gate: даже если угроза подтвердится мгновенно, поток
        # останется в WATCHING и НЕ отправит NEAREST_TARGET/ATTACK до четырех SWEEP.
        sweep_gate_open = False
        if is_flag_enabled('anti_agr_kill'):
            begin_post_kill_sweep_gate()
            sweep_gate_open = True

            predeath_hp = state.get('_antiaggro_diag_last_char_hp')
            predeath_ts = state.get('_antiaggro_diag_last_char_hp_wall_ts')
            predeath_age = (time.time() - predeath_ts) if predeath_ts else None
            scheduled = schedule_threat_watch(
                ser,
                source="target_death",
                baseline_hint=predeath_hp,
                baseline_hint_age=predeath_age,
            )
            log_event(
                "WATCH_SCHEDULE_RESULT",
                scheduled=scheduled,
                phase=get_threat_watcher_phase(),
                watch_id=get_current_watch_id(),
                sweep_gate=True,
            )
        else:
            log_event(
                "WATCH_NOT_SCHEDULED",
                level="warning",
                reason="THREAT_SCENARIO_KILL_ENABLED=False",
            )

        required_sweeps = 4
        sweeps_sent = 0
        try:
            # До обязательной серии SWEEP anti-aggro не может стать ACQUIRING,
            # поэтому эти ожидания не прерываются сменой цели.
            initial_delay = random.uniform(config.LOOT_MIN, config.LOOT_MAX)
            if not _sleep_interruptible_by_anti_aggro(initial_delay):
                # Аварийный fallback: даже если внешняя подсистема неожиданно
                # получила priority, SWEEP всё равно должен быть отправлен.
                log_event(
                    "SWEEP_PRIORITY_OVERRIDES_ANTIAGGRO",
                    level="warning",
                    step="initial_delay",
                )

            # FIX: после смерти моба отправляем SWEEP ровно 4 раза.
            # Между нажатиями сохраняем исходный небольшой случайный интервал.
            for sweep_index in range(1, required_sweeps + 1):
                log_event(
                    "POST_KILL_SWEEP_COMMAND",
                    level="info",
                    index=sweep_index,
                    total=required_sweeps,
                    command="SWEEP",
                    antiaggro_phase=get_threat_watcher_phase(),
                    watch_id=get_current_watch_id(),
                )
                send_command(ser, 'SWEEP')
                sweeps_sent += 1

                if sweep_index < required_sweeps:
                    delay = random.uniform(
                        config.SWEEP_TO_LOOT_MIN,
                        config.SWEEP_TO_LOOT_MAX,
                    )
                    time.sleep(max(0.0, delay))

        finally:
            if sweep_gate_open:
                end_post_kill_sweep_gate(
                    reason=(
                        "four_sweeps_sent"
                        if sweeps_sent == required_sweeps
                        else "sweep_sequence_aborted_fail_open"
                    )
                )

        # После четвертого SWEEP anti-aggro уже может переключить цель. Остальной
        # LOOT намеренно остаётся прерываемым: приоритет теперь у угрозы.
        post_sweep_delay = random.uniform(
            config.SWEEP_TO_LOOT_MIN, config.SWEEP_TO_LOOT_MAX
        )
        if not _sleep_interruptible_by_anti_aggro(post_sweep_delay):
            log_event("LOOT_INTERRUPTED_BY_ANTIAGGRO", step="after_required_sweep")
            return state

        for index in range(config.LOOT_REPEAT_COUNT):
            delay = random.uniform(config.LOOT_MIN, config.LOOT_MAX)
            if not _loot_command(ser, 'LOOT', delay):
                log_event("LOOT_INTERRUPTED_BY_ANTIAGGRO", step=f"loot_{index + 1}")
                return state

        # Сохраняем существующие дополнительные 10 LOOT из исходного проекта.
        for index in range(10):
            delay = random.uniform(config.LOOT_MIN, config.LOOT_MAX)
            if not _loot_command(ser, 'LOOT', delay):
                log_event("LOOT_INTERRUPTED_BY_ANTIAGGRO", step=f"extra_loot_{index + 1}")
                return state

        if is_threat_watcher_active():
            log_event(
                "NORMAL_TARGET_DEFERRED",
                reason="watcher_still_active_after_loot",
                phase=get_threat_watcher_phase(),
                watch_id=get_current_watch_id(),
            )
            return state

        if is_anti_aggro_target_active():
            valid = has_valid_current_target()
            log_event(
                "ANTIAGGRO_TARGET_AFTER_LOOT",
                valid=valid,
                target=get_target_probe(),
            )
            if valid:
                state['was_hp1_red'] = True
            return state

        if has_valid_current_target():
            log_event(
                "TARGET_ALREADY_PRESENT_AFTER_LOOT",
                target=get_target_probe(),
            )
            state['was_hp1_red'] = True
            return state
        else:
            log_event("NORMAL_TARGET_SEARCH_AFTER_LOOT", target=get_target_probe())
            find_new_target(ser, state)

    elif not is_target_alive_raw and not state.get('was_hp1_red'):
        find_new_target(ser, state)

    state['was_hp1_red'] = is_target_alive_raw
    return state
