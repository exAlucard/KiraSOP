# la2_bot/utils/threat_watcher.py
"""Наблюдение за входящим уроном после смерти/лута цели (anti-aggro).

Версия с подробной диагностикой:
- полный DEBUG-трейс каждого измерения HP и каждого poll таргета;
- структурированные причины, почему anti-aggro не сработал;
- диагностические PNG/JSON при ошибках/подозрительном поведении;
- обычный targeting не перебивает фазу ACQUIRING/ENGAGED;
- v6 ждёт 2 секунды перед live-retarget и проверяет, не начал ли текущий моб терять HP;
- v7 постоянно контролирует HP и без таргета: входящий урон после истечения post-death watcher
  немедленно запускает подтверждение и захват ближайшего агрессора;
- v11: если новая текущая цель уже получила урон, post-death watcher отменяется и
  больше не имеет права переключать этот начавшийся бой через NEAREST_TARGET;
- v12: уже выбранная anti-aggro цель больше не считается правильной навсегда:
  если она несколько секунд остаётся FULL HP, а персонаж продолжает получать урон,
  бот после дополнительной 2-секундной проверки циклически меняет её через NEXT_TARGET.
- v14: задержка anti-aggro унифицирована до 1 секунды.
- v16: два независимых сценария из конфига: THREAT_SCENARIO_KILL_ENABLED и
  THREAT_SCENARIO_FULL_HP_ENABLED; отключённый сценарий не может завершить pending retarget.
"""

import itertools
import threading
import time
from statistics import median

from la2_bot.detection.hp_bar_detection import get_hp_measurement
from la2_bot.core.comm import send_command
from la2_bot.config import config
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.core.debug_state import set_threat_watcher_hp, set_next_target_cooldown
from la2_bot.utils.target_utils import is_target_selected
from la2_bot.utils.antiaggro_diagnostics import (
    collect_coordinate_diagnostics,
    get_log_path,
    log_event,
    save_debug_snapshot,
)


PHASE_IDLE = 'IDLE'
PHASE_WATCHING = 'WATCHING'
PHASE_ACQUIRING = 'ACQUIRING'
PHASE_ENGAGED = 'ENGAGED'

threat_watcher_thread = None
_state_lock = threading.RLock()
_phase = PHASE_IDLE
_anti_aggro_target_active = False
_anti_aggro_target_since = 0.0
_watch_counter = itertools.count(1)
_current_watch_id = None
_live_full_pending_thread = None
_live_full_pending_id = None
_engaged_full_recheck_thread = None
_engaged_full_recheck_id = None

# v9: после смерти цели anti-aggro может ДЕТЕКТИРОВАТЬ урон сразу,
# но не имеет права менять таргет до завершения обязательного SWEEP.
# Event установлен = переключение разрешено; clear = ждём свип.
_post_kill_sweep_done = threading.Event()
_post_kill_sweep_done.set()
_post_kill_sweep_started_mono = 0.0
_last_target_lost_mono = 0.0


def begin_post_kill_sweep_gate():
    """Закрывает барьер смены цели до выполнения обязательного SWEEP."""
    global _post_kill_sweep_started_mono, _last_target_lost_mono
    now_mono = time.monotonic()
    _post_kill_sweep_started_mono = now_mono
    # v13: сохраняем момент смерти/исчезновения таргета отдельно от sweep-gate.
    # Сам gate после SWEEP обнуляется, а 1-секундная задержка должна считаться
    # именно от момента смерти, а не добавляться ещё одной секундой после SWEEP.
    _last_target_lost_mono = now_mono
    _post_kill_sweep_done.clear()
    log_event(
        "POST_KILL_SWEEP_GATE_CLOSED",
        level="info",
        watch_id=get_current_watch_id(),
        reason="target_death_before_sweep",
    )


def end_post_kill_sweep_gate(reason="sweep_complete"):
    """Открывает барьер: anti-aggro теперь может выполнять retarget/ATTACK."""
    global _post_kill_sweep_started_mono
    was_pending = not _post_kill_sweep_done.is_set()
    age = (
        time.monotonic() - _post_kill_sweep_started_mono
        if _post_kill_sweep_started_mono else None
    )
    _post_kill_sweep_done.set()
    _post_kill_sweep_started_mono = 0.0
    if was_pending:
        log_event(
            "POST_KILL_SWEEP_GATE_OPENED",
            level="info",
            watch_id=get_current_watch_id(),
            reason=reason,
            blocked_for=age,
        )


def is_post_kill_sweep_pending():
    return not _post_kill_sweep_done.is_set()


def _wait_for_post_kill_sweep_before_acquire(watch_id, trigger_source):
    """Ждёт обязательный свип перед любой сменой цели post-death watcher'ом.

    Урон уже подтверждён, поэтому мы не теряем событие. Просто удерживаем фазу
    WATCHING, чтобы targeting успел отправить SWEEP. После открытия gate поток
    немедленно повышается до ACQUIRING. Есть аварийный timeout, чтобы ошибка
    основного потока не могла навсегда заморозить anti-aggro.
    """
    if _post_kill_sweep_done.is_set():
        return True

    timeout = _cfg_float('THREAT_POST_KILL_SWEEP_GATE_TIMEOUT', 5.0, minimum=1.0)
    wait_started = time.monotonic()
    log_event(
        "THREAT_DEFERRED_UNTIL_SWEEP",
        level="warning",
        watch_id=watch_id,
        trigger_source=trigger_source,
        timeout=timeout,
        action="remember_threat_but_do_not_retarget_yet",
    )

    released = _post_kill_sweep_done.wait(timeout=timeout)
    waited = time.monotonic() - wait_started
    if released:
        if not is_kill_scenario_enabled():
            log_event(
                "THREAT_SWEEP_BARRIER_RELEASED_BUT_SCENARIO_DISABLED",
                level="info",
                watch_id=watch_id,
                trigger_source=trigger_source,
                waited=waited,
                action="cancel_post_death_retarget",
            )
            return False
        log_event(
            "THREAT_SWEEP_BARRIER_RELEASED",
            level="info",
            watch_id=watch_id,
            trigger_source=trigger_source,
            waited=waited,
            action="antiaggro_acquire_now_allowed",
        )
        return True

    log_event(
        "THREAT_SWEEP_BARRIER_TIMEOUT",
        level="error",
        watch_id=watch_id,
        trigger_source=trigger_source,
        waited=waited,
        timeout=timeout,
        action="fail_open_to_avoid_permanent_antiaggro_lock",
    )
    return False


def _cfg_float(name, default, minimum=None):
    try:
        value = float(getattr(config, name, default))
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    return value


def _cfg_int(name, default, minimum=None):
    try:
        value = int(getattr(config, name, default))
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    return value


def _cfg_bool(name, default=True):
    try:
        value = getattr(config, name, default)
    except Exception:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'off', 'no', 'нет'}
    return bool(value)


def is_kill_scenario_enabled():
    """Post-death / no-target anti-aggro scenario."""
    return _cfg_bool('THREAT_SCENARIO_KILL_ENABLED', True)


def is_full_hp_scenario_enabled():
    """Live FULL-HP target anti-aggro scenario, including ENGAGED recheck."""
    return _cfg_bool('THREAT_SCENARIO_FULL_HP_ENABLED', True)


def _wait_state_based_retarget_delay(
    watch_id,
    trigger_source,
    *,
    no_target_anchor_mono=None,
):
    """v13: задержка перед retarget зависит от текущего состояния таргета.

    Правила v14:
    - таргета НЕТ (TARGET_HP_1_POINT не красный) -> 1.0 сек;
    - таргет ЕСТЬ и он FULL HP -> 1.0 сек;
    - таргет стал damaged во время ожидания -> retarget отменяется.

    Если состояние меняется прямо во время окна (например, был no-target и
    появился FULL HP моб), таймер переключается на соответствующее правило.
    Для post-death no-target первая секунда считается от момента смерти цели,
    поэтому SWEEP не добавляет лишнюю секунду сверху.
    """
    no_target_delay = _cfg_float(
        'THREAT_NO_TARGET_DECISION_DELAY', 1.0, minimum=0.10
    )
    full_target_delay = _cfg_float(
        'THREAT_LIVE_FULL_TARGET_DECISION_DELAY', 1.0, minimum=0.25
    )
    poll_interval = _cfg_float(
        'THREAT_RETARGET_DECISION_POLL_INTERVAL', 0.05, minimum=0.02
    )

    now = time.monotonic()
    probe = get_target_probe()

    if _probe_is_damaged(probe):
        log_event(
            "RETARGET_DELAY_CANCELLED_TARGET_DAMAGED",
            level="warning",
            watch_id=watch_id,
            trigger_source=trigger_source,
            target=probe,
            decision="keep_current_target",
        )
        return False

    if _probe_is_ready(probe):
        mode = "full_target"
        delay = full_target_delay
        anchor = now
    else:
        mode = "no_target"
        delay = no_target_delay
        try:
            supplied_anchor = float(no_target_anchor_mono) if no_target_anchor_mono else 0.0
        except (TypeError, ValueError):
            supplied_anchor = 0.0
        anchor = supplied_anchor if supplied_anchor > 0.0 else now

    deadline = anchor + delay
    remaining = max(0.0, deadline - now)

    log_event(
        "RETARGET_DECISION_DELAY_START",
        level="warning",
        watch_id=watch_id,
        trigger_source=trigger_source,
        mode=mode,
        delay=delay,
        remaining=remaining,
        no_target_delay=no_target_delay,
        full_target_delay=full_target_delay,
        target=probe,
    )

    # Если нужное время уже прошло (типичный post-death случай, когда SWEEP
    # занял почти всю 1 секунду), ничего дополнительно не тормозим.
    if remaining <= 0.0:
        log_event(
            "RETARGET_DECISION_DELAY_COMPLETE",
            level="info",
            watch_id=watch_id,
            trigger_source=trigger_source,
            mode=mode,
            elapsed_from_anchor=max(0.0, now - anchor),
            target=get_target_probe(),
            reason="delay_already_satisfied",
        )
        return True

    while True:
        now = time.monotonic()
        if now >= deadline:
            final_probe = get_target_probe()
            if _probe_is_damaged(final_probe):
                log_event(
                    "RETARGET_DELAY_CANCELLED_TARGET_DAMAGED",
                    level="warning",
                    watch_id=watch_id,
                    trigger_source=trigger_source,
                    mode=mode,
                    target=final_probe,
                    decision="keep_current_target",
                    reason="target_damaged_at_delay_end",
                )
                return False

            log_event(
                "RETARGET_DECISION_DELAY_COMPLETE",
                level="info",
                watch_id=watch_id,
                trigger_source=trigger_source,
                mode=mode,
                delay=delay,
                target=final_probe,
            )
            return True

        time.sleep(min(poll_interval, max(0.0, deadline - now)))
        current_probe = get_target_probe()

        if _probe_is_damaged(current_probe):
            log_event(
                "RETARGET_DELAY_CANCELLED_TARGET_DAMAGED",
                level="warning",
                watch_id=watch_id,
                trigger_source=trigger_source,
                mode=mode,
                target=current_probe,
                decision="keep_current_target",
                reason="target_became_damaged_during_delay",
            )
            return False

        current_mode = "full_target" if _probe_is_ready(current_probe) else "no_target"
        if current_mode != mode:
            old_mode = mode
            mode = current_mode
            now = time.monotonic()
            if mode == "full_target":
                delay = full_target_delay
                anchor = now
            else:
                delay = no_target_delay
                anchor = now
            deadline = anchor + delay

            log_event(
                "RETARGET_DECISION_DELAY_MODE_CHANGED",
                level="warning",
                watch_id=watch_id,
                trigger_source=trigger_source,
                old_mode=old_mode,
                new_mode=mode,
                delay=delay,
                target=current_probe,
            )


def _set_phase(phase, watch_id=None, reason=None):
    global _phase
    with _state_lock:
        old = _phase
        _phase = phase
    if old != phase:
        log_event(
            "WATCH_PHASE",
            watch_id=watch_id or _current_watch_id,
            old=old,
            new=phase,
            reason=reason,
        )


def get_threat_watcher_phase():
    with _state_lock:
        return _phase


def get_current_watch_id():
    with _state_lock:
        return _current_watch_id


def is_threat_watcher_active():
    with _state_lock:
        thread = threat_watcher_thread
        return thread is not None and thread.is_alive()


def is_threat_watcher_acquiring():
    with _state_lock:
        return _phase == PHASE_ACQUIRING


def is_live_full_target_pending():
    """True только во время 2-секундного окна проверки FULL-HP цели.

    PENDING намеренно НЕ считается anti-aggro priority: spoil/обычная атака должны
    продолжаться, чтобы текущий моб успел получить урон и тем самым доказать,
    что бой уже начался именно с ним.
    """
    with _state_lock:
        thread = _live_full_pending_thread
        return thread is not None and thread.is_alive()


def get_live_full_pending_id():
    with _state_lock:
        return _live_full_pending_id


def is_engaged_full_target_recheck_pending():
    """True, пока v12 перепроверяет уже захваченную anti-aggro FULL-HP цель."""
    with _state_lock:
        thread = _engaged_full_recheck_thread
        return thread is not None and thread.is_alive()


def get_anti_aggro_target_age():
    """Возраст текущего anti-aggro target в секундах или None."""
    if not is_anti_aggro_target_active():
        return None
    with _state_lock:
        since = _anti_aggro_target_since
    if not since:
        return None
    return max(0.0, time.time() - since)


def _anti_aggro_target_expired_locked():
    if not _anti_aggro_target_active:
        return False

    max_duration = _cfg_float('THREAT_ENGAGED_MAX_DURATION', 60.0, minimum=5.0)
    return (time.time() - _anti_aggro_target_since) > max_duration


def is_anti_aggro_target_active():
    global _anti_aggro_target_active, _anti_aggro_target_since, _phase

    with _state_lock:
        if _anti_aggro_target_expired_locked():
            age = time.time() - _anti_aggro_target_since
            log_event(
                "ANTIAGGRO_TARGET_EXPIRED",
                level="warning",
                watch_id=_current_watch_id,
                age=age,
            )
            _anti_aggro_target_active = False
            _anti_aggro_target_since = 0.0
            if _phase == PHASE_ENGAGED:
                _phase = PHASE_IDLE
        return _anti_aggro_target_active


def is_anti_aggro_priority_active():
    with _state_lock:
        acquiring = _phase == PHASE_ACQUIRING
    return acquiring or is_anti_aggro_target_active()


def _mark_anti_aggro_target_active(watch_id=None):
    global _anti_aggro_target_active, _anti_aggro_target_since, _phase
    with _state_lock:
        _anti_aggro_target_active = True
        _anti_aggro_target_since = time.time()
        old = _phase
        _phase = PHASE_ENGAGED
    log_event(
        "ANTIAGGRO_TARGET_LOCKED",
        watch_id=watch_id or _current_watch_id,
        old_phase=old,
        new_phase=PHASE_ENGAGED,
    )


def clear_anti_aggro_target(reason=None):
    global _anti_aggro_target_active, _anti_aggro_target_since, _phase

    with _state_lock:
        was_active = _anti_aggro_target_active
        age = time.time() - _anti_aggro_target_since if _anti_aggro_target_since else None
        _anti_aggro_target_active = False
        _anti_aggro_target_since = 0.0
        if _phase == PHASE_ENGAGED:
            _phase = PHASE_IDLE

    if was_active:
        log_event(
            "ANTIAGGRO_TARGET_CLEARED",
            watch_id=_current_watch_id,
            reason=reason,
            age=age,
        )


def _measurement_summary(measurement):
    if not measurement:
        return None
    return {
        # Поле hp исторически называлось percentage. В v3 для LU4 это
        # абсолютное числовое HP, распознанное OCR.
        "hp": measurement.get("percentage"),
        "method": measurement.get("method"),
        "ocr_text": measurement.get("ocr_text"),
        "ocr_confidence": measurement.get("ocr_confidence"),
        "ocr_pass": measurement.get("ocr_pass"),
        "bbox": measurement.get("bbox"),
        "size": measurement.get("size"),
        "row_spread": measurement.get("row_spread"),
        "rows": measurement.get("rows"),
        "error": measurement.get("error"),
    }


def _save_snapshot_async(reason, metadata=None, hp_image=None):
    """Сохраняет диагностику вне критического пути anti-aggro.

    На тестовом логе запись PNG/JSON занимала сотни миллисекунд. Нельзя держать
    фазу WATCHING или задерживать ATTACK ради диагностического файла.
    """
    def worker():
        try:
            save_debug_snapshot(reason, metadata=metadata, hp_image=hp_image)
        except Exception as exc:
            log_event(
                "SNAPSHOT_ASYNC_ERROR",
                level="error",
                reason=reason,
                error=repr(exc),
            )

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name=f"antiaggro_snapshot:{reason}",
    )
    thread.start()


def _read_stable_hp(sample_count=3, sample_delay=0.025, watch_id=None):
    """Снимает несколько показаний HP и возвращает медиану + сырые измерения."""
    values = []
    measurements = []
    for index in range(max(1, int(sample_count))):
        measurement = get_hp_measurement(include_image=(index == 0))
        measurements.append(measurement)
        hp = measurement.get("percentage")
        if hp is not None:
            values.append(float(hp))
        log_event(
            "HP_BASELINE_SAMPLE",
            level="debug",
            watch_id=watch_id,
            sample=index + 1,
            measurement=_measurement_summary(measurement),
        )
        if index + 1 < sample_count:
            time.sleep(max(0.0, sample_delay))

    if not values:
        return None, measurements
    return float(median(values)), measurements


def _safe_pixel(point):
    if not point:
        return None
    try:
        return get_pixel_color(*point)
    except Exception as exc:
        return {"error": repr(exc)}


def get_target_probe():
    """Диагностическое состояние таргета, используемое и watcher, и targeting."""
    point = getattr(coordinate_utils, 'TARGET_HP_1_POINT', None)
    hp1_rgb = _safe_pixel(point)

    target_alive = False
    if isinstance(hp1_rgb, tuple):
        try:
            target_alive = bool(is_target_color(hp1_rgb))
        except Exception:
            target_alive = False

    try:
        selected = bool(is_target_selected())
        selected_error = None
    except Exception as exc:
        selected = False
        selected_error = repr(exc)

    return {
        "hp1_point": point,
        "hp1_rgb": hp1_rgb,
        "alive_by_hp1": target_alive,
        "selected": selected,
        "selected_error": selected_error,
        "full_point": getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None),
        "full_rgb": _safe_pixel(getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None)),
        "damaged_point": getattr(coordinate_utils, 'TARGET_HP_DAMAGED_POINT', None),
        "damaged_rgb": _safe_pixel(getattr(coordinate_utils, 'TARGET_HP_DAMAGED_POINT', None)),
        "selected_point": getattr(coordinate_utils, 'TARGET_SELECTED_POINT', None),
        "selected_rgb": _safe_pixel(getattr(coordinate_utils, 'TARGET_SELECTED_POINT', None)),
        "mob2_point": getattr(coordinate_utils, 'TARGET_MOB_POINT2', None),
        "mob2_rgb": _safe_pixel(getattr(coordinate_utils, 'TARGET_MOB_POINT2', None)),
    }


def _probe_is_ready(probe):
    return bool(probe.get("alive_by_hp1") and probe.get("selected"))


def _probe_is_full_hp(probe):
    """True, если выбранная живая цель всё ещё имеет полный HP."""
    if not probe:
        return False
    rgb = probe.get("full_rgb")
    return isinstance(rgb, tuple) and bool(is_target_color(rgb))


def _probe_is_damaged(probe):
    """True только для ЖИВОЙ выбранной цели, у которой HP уже не full.

    На LU4 точка TARGET_HP_DAMAGED_POINT красная и при full HP, поэтому одного
    damaged_rgb недостаточно. Надёжный признак начавшегося боя:
    - TARGET_HP_1_POINT показывает живую цель;
    - damaged point красный;
    - full point уже НЕ красный.
    """
    if not _probe_is_ready(probe):
        return False
    damaged_rgb = probe.get("damaged_rgb")
    damaged_marker = (
        isinstance(damaged_rgb, tuple)
        and bool(is_target_color(damaged_rgb))
    )
    return bool(damaged_marker and not _probe_is_full_hp(probe))


def _confirm_existing_target_damaged(
    watch_id,
    *,
    source,
    required=2,
    interval=0.05,
):
    """Подтверждает, что текущий живой target уже получил урон.

    Нужен как race-guard прямо перед ACQUIRING/NEAREST_TARGET: если обычный бой
    уже стартовал, post-death anti-aggro не имеет права менять эту цель.
    """
    required = max(1, int(required))
    consecutive = 0
    last_probe = get_target_probe()

    for check in range(1, required + 1):
        last_probe = get_target_probe()
        damaged = _probe_is_damaged(last_probe)
        consecutive = consecutive + 1 if damaged else 0
        log_event(
            "POST_DEATH_DAMAGED_TARGET_GUARD_POLL",
            level="debug",
            watch_id=watch_id,
            source=source,
            check=check,
            required=required,
            damaged=damaged,
            consecutive=consecutive,
            target=last_probe,
        )
        if not damaged:
            return False, last_probe
        if consecutive >= required:
            return True, last_probe
        time.sleep(max(0.02, float(interval)))

    return False, last_probe


def _clear_current_target_for_live_intercept(ser, watch_id):
    """Снимает исходную FULL-HP цель перед поиском агрессора.

    Для post-death watcher существующая цель иногда уже является агрессором, и
    её нельзя трогать. Для live FULL-HP сценария всё наоборот: эта цель была
    выбрана ДО входящего удара, поэтому сначала гарантированно убираем её из
    таргета и только затем выполняем NEAREST_TARGET.
    """
    clear_attempts = _cfg_int('THREAT_LIVE_FULL_TARGET_CLEAR_ATTEMPTS', 2, minimum=1)
    clear_timeout = _cfg_float('THREAT_LIVE_FULL_TARGET_CLEAR_TIMEOUT', 0.35, minimum=0.10)
    poll_interval = _cfg_float('THREAT_TARGET_POLL_INTERVAL', 0.05, minimum=0.02)
    last_probe = get_target_probe()

    if not _probe_is_ready(last_probe):
        log_event(
            "LIVE_FULL_TARGET_ALREADY_CLEAR",
            level="debug",
            watch_id=watch_id,
            target=last_probe,
        )
        return True, last_probe

    for attempt in range(1, clear_attempts + 1):
        log_event(
            "LIVE_FULL_TARGET_CLEAR_COMMAND",
            level="warning",
            watch_id=watch_id,
            attempt=attempt,
            command="ESC",
            target_before=last_probe,
        )
        send_command(ser, 'ESC')
        deadline = time.monotonic() + clear_timeout

        while time.monotonic() < deadline:
            time.sleep(min(0.05, poll_interval))
            last_probe = get_target_probe()
            if not _probe_is_ready(last_probe):
                log_event(
                    "LIVE_FULL_TARGET_CURRENT_TARGET_CLEARED",
                    watch_id=watch_id,
                    attempt=attempt,
                    target_after=last_probe,
                )
                return True, last_probe

        log_event(
            "LIVE_FULL_TARGET_CLEAR_ATTEMPT_TIMEOUT",
            level="warning",
            watch_id=watch_id,
            attempt=attempt,
            target=last_probe,
        )

    log_event(
        "LIVE_FULL_TARGET_CLEAR_FAILED",
        level="error",
        watch_id=watch_id,
        target=last_probe,
        hint="ESC не снял исходную FULL-HP цель; NEAREST_TARGET не отправляется, чтобы не зафиксировать старый таргет как агрессора.",
    )
    return False, last_probe


def _poll_target_stable(
    watch_id,
    *,
    source,
    attempt=None,
    timeout=0.25,
    poll_interval=0.05,
    required=2,
):
    """Требует несколько подряд валидных кадров таргета.

    Один красный pixel-poll может быть промежуточным кадром интерфейса. Два
    подтверждения подряд почти не добавляют задержки, зато убирают ложный lock.
    """
    deadline = time.monotonic() + max(0.05, float(timeout))
    required = max(1, int(required))
    consecutive = 0
    poll_no = 0
    last_probe = get_target_probe()

    while time.monotonic() < deadline:
        poll_no += 1
        last_probe = get_target_probe()
        ready = _probe_is_ready(last_probe)
        consecutive = consecutive + 1 if ready else 0
        log_event(
            "TARGET_ACQUIRE_POLL",
            level="debug",
            watch_id=watch_id,
            source=source,
            attempt=attempt,
            poll=poll_no,
            ready=ready,
            stable_count=consecutive,
            stable_required=required,
            probe=last_probe,
        )
        if consecutive >= required:
            return True, last_probe, poll_no
        time.sleep(max(0.02, float(poll_interval)))

    return False, last_probe, poll_no


def _lock_and_attack(ser, watch_id, target_probe, *, source, attempt=None, trigger_metadata=None):
    """Фиксирует anti-aggro цель и немедленно отправляет ATTACK."""
    _mark_anti_aggro_target_active(watch_id=watch_id)
    set_next_target_cooldown(2.0)

    # Критично: ATTACK идёт ДО PNG/JSON snapshot. В v2 snapshot задерживал
    # фактическую атаку примерно на 0.3-0.4 сек.
    send_command(ser, 'ATTACK')
    log_event(
        "ANTIAGGRO_ATTACK_COMMAND",
        watch_id=watch_id,
        source=source,
        attempt=attempt,
        command="ATTACK",
        target=target_probe,
    )

    _save_snapshot_async(
        "antiaggro_acquire_success",
        metadata={
            "watch_id": watch_id,
            "source": source,
            "attempt": attempt,
            "target": target_probe,
            "trigger": trigger_metadata,
        },
    )
    return True


def _try_claim_existing_target(
    ser,
    watch_id,
    *,
    source,
    stable_required,
    poll_interval,
    trigger_metadata=None,
    attempt=None,
    initial_probe=None,
    abort_if_damaged=False,
):
    """Если игра уже сама выбрала живую цель — не нажимаем NEAREST_TARGET.

    Проверка выполняется не только в начале ACQUIRE, но и прямо перед каждой
    командой NEAREST_TARGET. Это закрывает race, найденный в v3: между
    ACQUIRE_START и фактической командой интерфейс успевал показать правильную
    цель, а watcher всё равно переключал её NEAREST_TARGET.
    """
    probe = initial_probe if initial_probe is not None else get_target_probe()
    if not _probe_is_ready(probe):
        return False, probe

    log_event(
        "TARGET_PRESENT_BEFORE_NEAREST_TARGET",
        level="warning",
        watch_id=watch_id,
        source=source,
        attempt=attempt,
        target=probe,
        action="verify_and_claim_without_nearest_target",
    )

    stable, verified_probe, polls = _poll_target_stable(
        watch_id,
        source=source,
        attempt=attempt,
        timeout=max(0.18, poll_interval * (stable_required + 2)),
        poll_interval=poll_interval,
        required=stable_required,
    )
    if not stable:
        log_event(
            "EXISTING_TARGET_UNSTABLE",
            level="warning",
            watch_id=watch_id,
            source=source,
            attempt=attempt,
            polls=polls,
            target=verified_probe,
        )
        return False, verified_probe

    if abort_if_damaged and _probe_is_damaged(verified_probe):
        log_event(
            "EXISTING_TARGET_ALREADY_DAMAGED_KEEP_CURRENT",
            level="warning",
            watch_id=watch_id,
            source=source,
            attempt=attempt,
            polls=polls,
            target=verified_probe,
            decision="keep_current_target_and_abort_post_death_retarget",
        )
        return False, verified_probe

    log_event(
        "EXISTING_TARGET_CLAIMED",
        watch_id=watch_id,
        source=source,
        attempt=attempt,
        polls=polls,
        target=verified_probe,
        command="ATTACK",
    )
    _lock_and_attack(
        ser,
        watch_id,
        verified_probe,
        source=source,
        attempt=attempt,
        trigger_metadata=trigger_metadata,
    )
    return True, verified_probe


def _acquire_aggressor(
    ser,
    watch_id,
    trigger_metadata=None,
    *,
    allow_existing_target=True,
    clear_current_target=False,
    acquire_source="post_death",
    abort_if_existing_damaged=False,
):
    attempts = _cfg_int('THREAT_TARGET_ACQUIRE_ATTEMPTS', 2, minimum=1)
    poll_interval = _cfg_float('THREAT_TARGET_POLL_INTERVAL', 0.05, minimum=0.02)
    acquire_timeout = _cfg_float('THREAT_TARGET_ACQUIRE_TIMEOUT', 0.8, minimum=0.2)
    stable_required = _cfg_int('THREAT_TARGET_STABLE_SAMPLES', 2, minimum=1)

    set_next_target_cooldown(attempts * acquire_timeout + 1.0)
    before_probe = get_target_probe()
    log_event(
        "ACQUIRE_START",
        watch_id=watch_id,
        attempts=attempts,
        poll_interval=poll_interval,
        acquire_timeout=acquire_timeout,
        stable_required=stable_required,
        allow_existing_target=allow_existing_target,
        clear_current_target=clear_current_target,
        acquire_source=acquire_source,
        abort_if_existing_damaged=abort_if_existing_damaged,
        target_before=before_probe,
        trigger=trigger_metadata,
    )

    if abort_if_existing_damaged:
        damaged_now, damaged_probe = _confirm_existing_target_damaged(
            watch_id,
            source="acquire_start_guard",
            required=_cfg_int(
                'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES', 2, minimum=1
            ),
            interval=_cfg_float(
                'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL', 0.05, minimum=0.02
            ),
        )
        if damaged_now:
            log_event(
                "ACQUIRE_ABORT_CURRENT_TARGET_ALREADY_DAMAGED",
                level="warning",
                watch_id=watch_id,
                acquire_source=acquire_source,
                target=damaged_probe,
                decision="keep_current_target",
                reason="normal_combat_already_started_before_antiaggro_acquire",
            )
            return False

    # Обычный post-death режим может принять уже появившуюся цель без
    # NEAREST_TARGET. Live FULL-HP режим обязан сначала избавиться от исходного
    # таргета, иначе мы просто снова атакуем моба, к которому бежали.
    if clear_current_target:
        cleared, before_probe = _clear_current_target_for_live_intercept(
            ser, watch_id
        )
        if not cleared:
            _save_snapshot_async(
                "live_full_target_clear_failed",
                metadata={
                    "watch_id": watch_id,
                    "target": before_probe,
                    "trigger": trigger_metadata,
                },
            )
            return False

    if allow_existing_target:
        claimed, last_probe = _try_claim_existing_target(
            ser,
            watch_id,
            source="existing_target_at_acquire_start",
            stable_required=stable_required,
            poll_interval=poll_interval,
            trigger_metadata=trigger_metadata,
            initial_probe=before_probe,
            abort_if_damaged=abort_if_existing_damaged,
        )
        if claimed:
            return True
    else:
        last_probe = before_probe

    for attempt in range(1, attempts + 1):
        if allow_existing_target:
            claimed, pre_command = _try_claim_existing_target(
                ser,
                watch_id,
                source="existing_target_before_nearest",
                stable_required=stable_required,
                poll_interval=poll_interval,
                trigger_metadata=trigger_metadata,
                attempt=attempt,
                abort_if_damaged=abort_if_existing_damaged,
            )
            if claimed:
                return True
            if abort_if_existing_damaged:
                damaged_now, damaged_probe = _confirm_existing_target_damaged(
                    watch_id,
                    source=f"before_nearest_attempt_{attempt}",
                    required=_cfg_int(
                        'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES', 2, minimum=1
                    ),
                    interval=_cfg_float(
                        'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL', 0.05, minimum=0.02
                    ),
                )
                if damaged_now:
                    log_event(
                        "ACQUIRE_ABORT_CURRENT_TARGET_ALREADY_DAMAGED",
                        level="warning",
                        watch_id=watch_id,
                        acquire_source=acquire_source,
                        attempt=attempt,
                        target=damaged_probe,
                        decision="keep_current_target",
                        reason="target_became_damaged_before_nearest_target",
                    )
                    return False
        else:
            # После успешного ESC любая цель, появившаяся сама ДО команды, уже
            # не является исходной FULL-HP целью. Это может быть auto-target
            # агрессора самой игрой — её безопасно принять без лишнего switch.
            auto_probe = get_target_probe()
            if _probe_is_ready(auto_probe):
                claimed, pre_command = _try_claim_existing_target(
                    ser,
                    watch_id,
                    source="auto_target_after_live_clear",
                    stable_required=stable_required,
                    poll_interval=poll_interval,
                    trigger_metadata=trigger_metadata,
                    attempt=attempt,
                    initial_probe=auto_probe,
                )
                if claimed:
                    return True
            else:
                pre_command = auto_probe

        log_event(
            "ACQUIRE_COMMAND",
            watch_id=watch_id,
            attempt=attempt,
            command="NEAREST_TARGET",
            acquire_source=acquire_source,
            target_before=pre_command,
        )
        send_command(ser, 'NEAREST_TARGET')
        command_mono = time.monotonic()

        stable, last_probe, polls = _poll_target_stable(
            watch_id,
            source="after_nearest_target",
            attempt=attempt,
            timeout=acquire_timeout,
            poll_interval=poll_interval,
            required=stable_required,
        )
        if stable:
            log_event(
                "ACQUIRE_SUCCESS",
                watch_id=watch_id,
                attempt=attempt,
                polls=polls,
                command_to_ready_ms=(time.monotonic() - command_mono) * 1000.0,
                acquire_source=acquire_source,
                target=last_probe,
                command="ATTACK",
            )
            return _lock_and_attack(
                ser,
                watch_id,
                last_probe,
                source=(
                    "live_full_target_nearest"
                    if clear_current_target else "nearest_target"
                ),
                attempt=attempt,
                trigger_metadata=trigger_metadata,
            )

        log_event(
            "ACQUIRE_ATTEMPT_TIMEOUT",
            level="warning",
            watch_id=watch_id,
            attempt=attempt,
            polls=polls,
            acquire_source=acquire_source,
            last_target=last_probe,
        )

        if attempt < attempts:
            time.sleep(min(0.12, poll_interval * 2.0))

    log_event(
        "ACQUIRE_FAILED",
        level="error",
        watch_id=watch_id,
        acquire_source=acquire_source,
        last_target=last_probe,
        hint=(
            "HP-урон подтвержден, но после NEAREST_TARGET TARGET_HP_1_POINT не стал красным. "
            "Проверь команду/бинд NEAREST_TARGET и возможность выбрать агрессора в этот момент."
        ),
    )
    _save_snapshot_async(
        "antiaggro_acquire_failed",
        metadata={
            "watch_id": watch_id,
            "acquire_source": acquire_source,
            "last_target": last_probe,
            "trigger": trigger_metadata,
        },
    )
    return False


def schedule_live_full_target_antiaggro(
    ser,
    *,
    baseline_hp,
    observed_hp,
    baseline_age=None,
    target_probe=None,
    observed_measurement=None,
):
    """Проверяет внешний агр при живой FULL-HP цели с 2-секундной задержкой.

    v6: первый удар по персонажу больше НЕ вызывает мгновенный ESC/retarget.
    Создаётся отдельное PENDING-окно, которое не блокирует spoil/ATTACK. Пока
    бот продолжает обычное начало боя, мы наблюдаем HP выбранного моба:

    * если за окно цель хотя бы стабильно перестала быть FULL HP — бой уже
      начался с текущим мобом, live anti-aggro отменяется;
    * только если спустя всё окно цель по-прежнему жива, выбрана и FULL HP,
      PENDING атомарно повышается до ACQUIRING и выполняется ESC ->
      NEAREST_TARGET -> ATTACK.
    """
    global threat_watcher_thread, _phase, _current_watch_id
    global _live_full_pending_thread, _live_full_pending_id

    if not is_full_hp_scenario_enabled():
        log_event(
            "LIVE_FULL_TARGET_TRIGGER_REJECTED",
            level="info",
            reason="THREAT_SCENARIO_FULL_HP_ENABLED=False",
        )
        return False

    try:
        baseline_value = float(baseline_hp)
        observed_value = float(observed_hp)
    except (TypeError, ValueError):
        log_event(
            "LIVE_FULL_TARGET_TRIGGER_REJECTED",
            level="error",
            reason="invalid_hp_values",
            baseline_hp=baseline_hp,
            observed_hp=observed_hp,
        )
        return False

    method = (observed_measurement or {}).get("method")
    if method == "ocr_numeric":
        threshold = _cfg_float(
            'THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD_ABS',
            getattr(config, 'THREAT_HP_DROP_THRESHOLD_ABS', 4.0),
            minimum=1.0,
        )
        min_confidence = _cfg_float(
            'THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE', 70.0, minimum=0.0
        )
    else:
        threshold = _cfg_float(
            'THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD',
            getattr(config, 'THREAT_HP_DROP_THRESHOLD', 1.0),
            minimum=0.1,
        )
        min_confidence = 0.0

    initial_drop = baseline_value - observed_value
    if initial_drop < threshold:
        log_event(
            "LIVE_FULL_TARGET_TRIGGER_REJECTED",
            level="debug",
            reason="drop_below_threshold",
            baseline_hp=baseline_value,
            observed_hp=observed_value,
            drop=initial_drop,
            threshold=threshold,
        )
        return False

    if method == "ocr_numeric":
        confidence = (observed_measurement or {}).get("ocr_confidence")
        try:
            confidence_ok = confidence is not None and float(confidence) >= min_confidence
        except (TypeError, ValueError):
            confidence_ok = False
        if not confidence_ok:
            log_event(
                "LIVE_FULL_TARGET_TRIGGER_REJECTED",
                level="warning",
                reason="low_ocr_confidence",
                ocr_confidence=confidence,
                min_confidence=min_confidence,
                baseline_hp=baseline_value,
                observed_hp=observed_value,
            )
            return False

    initial_probe = target_probe or get_target_probe()
    if not (_probe_is_ready(initial_probe) and _probe_is_full_hp(initial_probe)):
        log_event(
            "LIVE_FULL_TARGET_TRIGGER_REJECTED",
            level="debug",
            reason="target_not_full_or_not_selected",
            target=initial_probe,
        )
        return False

    pending_id = f"live-{int(time.time() * 1000)}-{next(_watch_counter)}"
    with _state_lock:
        pending_thread = _live_full_pending_thread
        if pending_thread is not None and pending_thread.is_alive():
            log_event(
                "LIVE_FULL_TARGET_TRIGGER_REJECTED",
                level="debug",
                pending_id=pending_id,
                reason="live_full_pending_already_running",
                current_pending_id=_live_full_pending_id,
            )
            return False
        if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
            log_event(
                "LIVE_FULL_TARGET_TRIGGER_REJECTED",
                level="warning",
                pending_id=pending_id,
                reason="watcher_already_running",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False
        if _anti_aggro_target_active:
            log_event(
                "LIVE_FULL_TARGET_TRIGGER_REJECTED",
                level="warning",
                pending_id=pending_id,
                reason="antiaggro_target_already_active",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False

    decision_delay = _cfg_float(
        'THREAT_LIVE_FULL_TARGET_DECISION_DELAY', 1.0, minimum=0.25
    )
    target_poll = _cfg_float(
        'THREAT_LIVE_FULL_TARGET_DECISION_POLL_INTERVAL', 0.10, minimum=0.03
    )
    damaged_confirm_required = _cfg_int(
        'THREAT_LIVE_FULL_TARGET_DAMAGED_CONFIRM_SAMPLES', 2, minimum=1
    )
    final_full_required = _cfg_int(
        'THREAT_LIVE_FULL_TARGET_FINAL_FULL_CONFIRM_SAMPLES', 3, minimum=1
    )

    log_event(
        "LIVE_FULL_TARGET_PENDING_SCHEDULED",
        level="warning",
        pending_id=pending_id,
        decision_delay=decision_delay,
        poll_interval=target_poll,
        damaged_confirm_required=damaged_confirm_required,
        final_full_required=final_full_required,
        baseline_hp=baseline_value,
        observed_hp=observed_value,
        hp_drop=initial_drop,
        threshold=threshold,
        baseline_age=baseline_age,
        target=initial_probe,
        measurement=_measurement_summary(observed_measurement),
        action="wait_before_retarget_while_normal_combat_continues",
    )

    def live_full_pending_logic():
        global threat_watcher_thread, _phase, _current_watch_id
        global _live_full_pending_thread, _live_full_pending_id

        start_mono = time.monotonic()
        promoted = False
        retarget_attempted = False
        last_probe = initial_probe
        damaged_streak = 0
        full_samples = 0
        not_full_samples = 0

        try:
            deadline = start_mono + decision_delay
            log_event(
                "LIVE_FULL_TARGET_DECISION_DELAY_START",
                level="warning",
                pending_id=pending_id,
                duration=decision_delay,
                target=initial_probe,
                note="spoil/обычная атака НЕ блокируются в это окно",
            )

            # Главное 1-секундное окно: только наблюдаем текущую цель.
            while time.monotonic() < deadline:
                time.sleep(min(target_poll, max(0.0, deadline - time.monotonic())))

                if not is_full_hp_scenario_enabled():
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason="THREAT_SCENARIO_FULL_HP_ENABLED switched OFF",
                    )
                    return

                # Если за это время запустился post-death watcher или появился
                # уже зафиксированный anti-aggro target, pending больше не нужен.
                with _state_lock:
                    active_thread = threat_watcher_thread
                    busy_with_other_watcher = (
                        active_thread is not None
                        and active_thread is not threading.current_thread()
                        and active_thread.is_alive()
                    )
                    anti_target_active = _anti_aggro_target_active

                if busy_with_other_watcher or anti_target_active:
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason=(
                            "another_watcher_started"
                            if busy_with_other_watcher
                            else "antiaggro_target_became_active"
                        ),
                        phase=get_threat_watcher_phase(),
                        watch_id=get_current_watch_id(),
                    )
                    return

                last_probe = get_target_probe()
                if not _probe_is_ready(last_probe):
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason="current_target_lost_or_died_during_delay",
                        elapsed=time.monotonic() - start_mono,
                        target=last_probe,
                    )
                    return

                target_full = _probe_is_full_hp(last_probe)
                if target_full:
                    full_samples += 1
                    damaged_streak = 0
                else:
                    not_full_samples += 1
                    damaged_streak += 1

                log_event(
                    "LIVE_FULL_TARGET_DECISION_POLL",
                    level="debug",
                    pending_id=pending_id,
                    elapsed=time.monotonic() - start_mono,
                    remaining=max(0.0, deadline - time.monotonic()),
                    target_full=target_full,
                    damaged_streak=damaged_streak,
                    damaged_confirm_required=damaged_confirm_required,
                    target=last_probe,
                )

                # Не отменяемся от одного серого пикселя: нужно несколько
                # последовательных подтверждений, что full-HP точка исчезла.
                if damaged_streak >= damaged_confirm_required:
                    log_event(
                        "LIVE_FULL_TARGET_RETARGET_CANCELLED_TARGET_DAMAGED",
                        level="warning",
                        pending_id=pending_id,
                        elapsed=time.monotonic() - start_mono,
                        damaged_streak=damaged_streak,
                        full_samples=full_samples,
                        not_full_samples=not_full_samples,
                        target=last_probe,
                        decision="keep_current_target",
                        reason="current mob lost HP during 2s grace period; combat with it has started",
                    )
                    return

            # По истечении ровно окна ещё раз убеждаемся несколькими быстрыми
            # poll'ами, что цель действительно всё ещё FULL HP.
            final_full_count = 0
            for check in range(1, final_full_required + 1):
                last_probe = get_target_probe()
                ready = _probe_is_ready(last_probe)
                target_full = ready and _probe_is_full_hp(last_probe)
                if target_full:
                    final_full_count += 1
                else:
                    final_full_count = 0

                log_event(
                    "LIVE_FULL_TARGET_FINAL_FULL_CHECK",
                    level="debug" if target_full else "warning",
                    pending_id=pending_id,
                    check=check,
                    required=final_full_required,
                    ready=ready,
                    target_full=target_full,
                    consecutive_full=final_full_count,
                    target=last_probe,
                )

                if not ready:
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason="target_lost_at_final_check",
                        target=last_probe,
                    )
                    return
                if not target_full:
                    log_event(
                        "LIVE_FULL_TARGET_RETARGET_CANCELLED_TARGET_DAMAGED",
                        level="warning",
                        pending_id=pending_id,
                        reason="target_not_full_at_final_check",
                        target=last_probe,
                        decision="keep_current_target",
                    )
                    return
                if check < final_full_required:
                    time.sleep(min(0.06, target_poll))

            if not is_full_hp_scenario_enabled():
                log_event(
                    "LIVE_FULL_TARGET_PENDING_ABORTED",
                    level="info",
                    pending_id=pending_id,
                    reason="THREAT_SCENARIO_FULL_HP_ENABLED switched OFF before promotion",
                )
                return

            # Только теперь становимся настоящим anti-aggro watcher. До этой
            # точки spoil/ATTACK работали как обычно.
            with _state_lock:
                if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason="watcher_started_during_promotion",
                        current_watch_id=_current_watch_id,
                        phase=_phase,
                    )
                    return
                if _anti_aggro_target_active:
                    log_event(
                        "LIVE_FULL_TARGET_PENDING_ABORTED",
                        level="info",
                        pending_id=pending_id,
                        reason="antiaggro_target_active_during_promotion",
                    )
                    return

                old_phase = _phase
                _current_watch_id = pending_id
                _phase = PHASE_ACQUIRING
                threat_watcher_thread = threading.current_thread()
                promoted = True

            set_next_target_cooldown(2.5)
            log_event(
                "LIVE_FULL_TARGET_DECISION_RETARGET",
                level="warning",
                watch_id=pending_id,
                old_phase=old_phase,
                new_phase=PHASE_ACQUIRING,
                waited=time.monotonic() - start_mono,
                full_samples=full_samples,
                not_full_samples=not_full_samples,
                final_full_count=final_full_count,
                target=last_probe,
                decision="retarget",
                reason="target stayed full HP for entire decision delay",
            )

            # Последняя защита от гонки между promotion и ESC.
            last_probe = get_target_probe()
            if not (_probe_is_ready(last_probe) and _probe_is_full_hp(last_probe)):
                log_event(
                    "LIVE_FULL_TARGET_RETARGET_CANCELLED_TARGET_DAMAGED",
                    level="warning",
                    watch_id=pending_id,
                    reason="target_changed_between_promotion_and_clear",
                    target=last_probe,
                    decision="keep_current_target",
                )
                return

            trigger_metadata = {
                "trigger_source": "live_full_target_hp_drop_after_1s_grace",
                "baseline_hp": baseline_value,
                "initial_observed_hp": observed_value,
                "initial_hp_drop": initial_drop,
                "threshold": threshold,
                "baseline_age": baseline_age,
                "decision_delay": decision_delay,
                "target_before_clear": last_probe,
                "measurement": _measurement_summary(observed_measurement),
            }
            retarget_attempted = True
            _save_snapshot_async(
                "live_full_target_retarget_after_delay",
                metadata={"watch_id": pending_id, **trigger_metadata},
            )

            _acquire_aggressor(
                ser,
                watch_id=pending_id,
                trigger_metadata=trigger_metadata,
                allow_existing_target=False,
                clear_current_target=True,
                acquire_source="live_full_target_after_1s",
            )

        except Exception as exc:
            log_event(
                "LIVE_FULL_TARGET_PENDING_EXCEPTION",
                level="error",
                pending_id=pending_id,
                error=repr(exc),
            )
            _save_snapshot_async(
                "live_full_target_pending_exception",
                metadata={"pending_id": pending_id, "error": repr(exc)},
            )
        finally:
            if promoted:
                set_threat_watcher_hp(None, None, False)
            with _state_lock:
                if threat_watcher_thread is threading.current_thread():
                    threat_watcher_thread = None
                if promoted and not _anti_aggro_target_active and _phase == PHASE_ACQUIRING:
                    _phase = PHASE_IDLE
                final_phase = _phase
                if promoted and _current_watch_id == pending_id and not _anti_aggro_target_active:
                    _current_watch_id = None
                if _live_full_pending_thread is threading.current_thread():
                    _live_full_pending_thread = None
                    _live_full_pending_id = None

            log_event(
                "LIVE_FULL_TARGET_PENDING_END",
                pending_id=pending_id,
                elapsed=time.monotonic() - start_mono,
                promoted_to_acquiring=promoted,
                retarget_attempted=retarget_attempted,
                final_phase=final_phase,
                antiaggro_target_active=is_anti_aggro_target_active(),
            )

    thread = threading.Thread(
        target=live_full_pending_logic,
        daemon=True,
        name=f'live_full_target_pending:{pending_id}',
    )
    with _state_lock:
        _live_full_pending_thread = thread
        _live_full_pending_id = pending_id
    thread.start()
    return True



def schedule_engaged_full_target_recheck(
    ser,
    *,
    baseline_hp,
    observed_hp,
    baseline_age=None,
    target_probe=None,
    observed_measurement=None,
):
    """v12: перепроверяет уже захваченную anti-aggro цель, которая остаётся FULL HP.

    Проблема, которую закрывает этот режим: NO_TARGET/post-death anti-aggro может
    выбрать ближайшего, но не того моба. Раньше после `_mark_anti_aggro_target_active`
    любой дальнейший входящий урон становился только диагностикой и target мог
    оставаться неправильным до минуты.

    Чтобы не ломать нормальное начало боя/спойл:
    1) target должен быть ENGAGED уже несколько секунд;
    2) новый входящий урон должен быть свежим и уверенно прочитанным;
    3) ещё 2 секунды бот продолжает spoil/ATTACK и наблюдает HP моба;
    4) если моб начал терять HP — остаёмся на нём;
    5) если всё это время он FULL HP — временно становимся ACQUIRING и нажимаем
       NEXT_TARGET, то есть именно ЦИКЛИМ цель, а не снова выбираем тот же
       NEAREST_TARGET.
    """
    global threat_watcher_thread, _phase, _current_watch_id
    global _engaged_full_recheck_thread, _engaged_full_recheck_id
    global _anti_aggro_target_active, _anti_aggro_target_since

    if not is_full_hp_scenario_enabled():
        log_event(
            "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
            level="info",
            reason="THREAT_SCENARIO_FULL_HP_ENABLED=False",
        )
        return False

    try:
        baseline_value = float(baseline_hp)
        observed_value = float(observed_hp)
    except (TypeError, ValueError):
        log_event(
            "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
            level="error",
            reason="invalid_hp_values",
            baseline_hp=baseline_hp,
            observed_hp=observed_hp,
        )
        return False

    method = (observed_measurement or {}).get("method")
    if method == "ocr_numeric":
        threshold = _cfg_float(
            'THREAT_ENGAGED_FULL_RECHECK_DROP_THRESHOLD_ABS',
            getattr(
                config,
                'THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD_ABS',
                getattr(config, 'THREAT_HP_DROP_THRESHOLD_ABS', 4.0),
            ),
            minimum=1.0,
        )
        min_confidence = _cfg_float(
            'THREAT_ENGAGED_FULL_RECHECK_MIN_OCR_CONFIDENCE',
            getattr(config, 'THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE', 70.0),
            minimum=0.0,
        )
    else:
        threshold = _cfg_float(
            'THREAT_ENGAGED_FULL_RECHECK_DROP_THRESHOLD',
            getattr(
                config,
                'THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD',
                getattr(config, 'THREAT_HP_DROP_THRESHOLD', 1.0),
            ),
            minimum=0.1,
        )
        min_confidence = 0.0

    hp_drop = baseline_value - observed_value
    if hp_drop < threshold:
        log_event(
            "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
            level="debug",
            reason="drop_below_threshold",
            baseline_hp=baseline_value,
            observed_hp=observed_value,
            hp_drop=hp_drop,
            threshold=threshold,
        )
        return False

    max_sample_gap = _cfg_float(
        'THREAT_ENGAGED_FULL_RECHECK_MAX_SAMPLE_GAP', 1.5, minimum=0.2
    )
    if baseline_age is None or float(baseline_age) > max_sample_gap:
        log_event(
            "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
            level="debug",
            reason="hp_sample_gap_too_large",
            baseline_age=baseline_age,
            max_sample_gap=max_sample_gap,
        )
        return False

    if method == "ocr_numeric":
        confidence = (observed_measurement or {}).get("ocr_confidence")
        try:
            confidence_ok = confidence is not None and float(confidence) >= min_confidence
        except (TypeError, ValueError):
            confidence_ok = False
        if not confidence_ok:
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
                level="warning",
                reason="low_ocr_confidence",
                ocr_confidence=confidence,
                min_confidence=min_confidence,
            )
            return False

    initial_probe = target_probe or get_target_probe()
    if not (_probe_is_ready(initial_probe) and _probe_is_full_hp(initial_probe)):
        log_event(
            "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
            level="debug",
            reason="target_not_ready_or_not_full",
            target=initial_probe,
        )
        return False

    min_engaged_age = _cfg_float(
        'THREAT_ENGAGED_FULL_RECHECK_MIN_AGE', 3.0, minimum=1.0
    )
    decision_delay = _cfg_float(
        'THREAT_ENGAGED_FULL_RECHECK_DECISION_DELAY', 1.0, minimum=0.5
    )
    poll_interval = _cfg_float(
        'THREAT_ENGAGED_FULL_RECHECK_POLL_INTERVAL', 0.10, minimum=0.03
    )
    damaged_required = _cfg_int(
        'THREAT_ENGAGED_FULL_RECHECK_DAMAGED_CONFIRM_SAMPLES', 2, minimum=1
    )
    final_full_required = _cfg_int(
        'THREAT_ENGAGED_FULL_RECHECK_FINAL_FULL_SAMPLES', 3, minimum=1
    )
    settle_after_cycle = _cfg_float(
        'THREAT_ENGAGED_FULL_RECHECK_CYCLE_SETTLE', 0.18, minimum=0.05
    )

    recheck_id = f"engaged-recheck-{int(time.time() * 1000)}-{next(_watch_counter)}"

    with _state_lock:
        active_thread = _engaged_full_recheck_thread
        if active_thread is not None and active_thread.is_alive():
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
                level="debug",
                recheck_id=recheck_id,
                reason="recheck_already_running",
                active_recheck_id=_engaged_full_recheck_id,
            )
            return False

        if not _anti_aggro_target_active or _phase != PHASE_ENGAGED:
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
                level="debug",
                recheck_id=recheck_id,
                reason="antiaggro_target_not_engaged",
                phase=_phase,
                antiaggro_target_active=_anti_aggro_target_active,
            )
            return False

        target_age = (
            time.time() - _anti_aggro_target_since
            if _anti_aggro_target_since else 0.0
        )
        if target_age < min_engaged_age:
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
                level="debug",
                recheck_id=recheck_id,
                reason="engaged_target_too_young",
                target_age=target_age,
                min_engaged_age=min_engaged_age,
            )
            return False

        if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_REJECTED",
                level="debug",
                recheck_id=recheck_id,
                reason="another_watcher_running",
                watch_id=_current_watch_id,
            )
            return False

        source_watch_id = _current_watch_id

    log_event(
        "ENGAGED_FULL_TARGET_RECHECK_SCHEDULED",
        level="warning",
        recheck_id=recheck_id,
        source_watch_id=source_watch_id,
        target_age=target_age,
        min_engaged_age=min_engaged_age,
        decision_delay=decision_delay,
        baseline_hp=baseline_value,
        observed_hp=observed_value,
        hp_drop=hp_drop,
        threshold=threshold,
        baseline_age=baseline_age,
        target=initial_probe,
        measurement=_measurement_summary(observed_measurement),
        action="keep_fighting_for_1s_then_cycle_if_target_still_full",
    )

    def engaged_recheck_logic():
        global threat_watcher_thread, _phase, _current_watch_id
        global _engaged_full_recheck_thread, _engaged_full_recheck_id
        global _anti_aggro_target_active, _anti_aggro_target_since

        start_mono = time.monotonic()
        promoted = False
        cycle_sent = False
        success = False
        last_probe = initial_probe
        old_watch_id = source_watch_id

        try:
            deadline = start_mono + decision_delay
            damaged_streak = 0

            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_DELAY_START",
                level="warning",
                recheck_id=recheck_id,
                duration=decision_delay,
                target=initial_probe,
                note="ENGAGED остаётся активным; spoil и обычная атака продолжаются",
            )

            while time.monotonic() < deadline:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

                if not is_full_hp_scenario_enabled():
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                        level="info",
                        recheck_id=recheck_id,
                        reason="THREAT_SCENARIO_FULL_HP_ENABLED switched OFF",
                    )
                    return

                with _state_lock:
                    if (
                        not _anti_aggro_target_active
                        or _phase != PHASE_ENGAGED
                        or _current_watch_id != source_watch_id
                    ):
                        log_event(
                            "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                            level="info",
                            recheck_id=recheck_id,
                            reason="antiaggro_state_changed_during_delay",
                            phase=_phase,
                            current_watch_id=_current_watch_id,
                            source_watch_id=source_watch_id,
                        )
                        return

                last_probe = get_target_probe()
                if not _probe_is_ready(last_probe):
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                        level="info",
                        recheck_id=recheck_id,
                        reason="target_lost_or_died_during_delay",
                        target=last_probe,
                    )
                    return

                damaged = _probe_is_damaged(last_probe)
                target_full = _probe_is_full_hp(last_probe)
                damaged_streak = damaged_streak + 1 if damaged else 0

                log_event(
                    "ENGAGED_FULL_TARGET_RECHECK_POLL",
                    level="debug",
                    recheck_id=recheck_id,
                    elapsed=time.monotonic() - start_mono,
                    target_full=target_full,
                    damaged=damaged,
                    damaged_streak=damaged_streak,
                    damaged_required=damaged_required,
                    target=last_probe,
                )

                if damaged_streak >= damaged_required:
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_CANCELLED_TARGET_DAMAGED",
                        level="warning",
                        recheck_id=recheck_id,
                        elapsed=time.monotonic() - start_mono,
                        target=last_probe,
                        decision="keep_current_antiaggro_target",
                        reason="current antiaggro mob started losing HP during grace",
                    )
                    return

            final_full_count = 0
            for check in range(1, final_full_required + 1):
                last_probe = get_target_probe()
                ready = _probe_is_ready(last_probe)
                target_full = ready and _probe_is_full_hp(last_probe)
                damaged = ready and _probe_is_damaged(last_probe)

                if target_full and not damaged:
                    final_full_count += 1
                else:
                    final_full_count = 0

                log_event(
                    "ENGAGED_FULL_TARGET_RECHECK_FINAL_FULL_CHECK",
                    level="debug" if target_full else "warning",
                    recheck_id=recheck_id,
                    check=check,
                    required=final_full_required,
                    ready=ready,
                    target_full=target_full,
                    damaged=damaged,
                    consecutive_full=final_full_count,
                    target=last_probe,
                )

                if not ready:
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                        level="info",
                        recheck_id=recheck_id,
                        reason="target_lost_at_final_check",
                        target=last_probe,
                    )
                    return
                if damaged or not target_full:
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_CANCELLED_TARGET_DAMAGED",
                        level="warning",
                        recheck_id=recheck_id,
                        reason="target_no_longer_full_at_final_check",
                        target=last_probe,
                        decision="keep_current_antiaggro_target",
                    )
                    return
                if check < final_full_required:
                    time.sleep(min(0.06, poll_interval))

            if not is_full_hp_scenario_enabled():
                log_event(
                    "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                    level="info",
                    recheck_id=recheck_id,
                    reason="THREAT_SCENARIO_FULL_HP_ENABLED switched OFF before cycle",
                )
                return

            # Promotion happens only after all grace/final checks. From here the
            # normal search/spoil paths must yield to anti-aggro re-acquisition.
            with _state_lock:
                if (
                    not _anti_aggro_target_active
                    or _phase != PHASE_ENGAGED
                    or _current_watch_id != source_watch_id
                ):
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                        level="info",
                        recheck_id=recheck_id,
                        reason="antiaggro_state_changed_before_cycle",
                        phase=_phase,
                        current_watch_id=_current_watch_id,
                    )
                    return
                if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
                    log_event(
                        "ENGAGED_FULL_TARGET_RECHECK_ABORTED",
                        level="info",
                        recheck_id=recheck_id,
                        reason="watcher_started_before_cycle",
                        current_watch_id=_current_watch_id,
                    )
                    return

                old_phase = _phase
                old_watch_id = _current_watch_id
                _phase = PHASE_ACQUIRING
                _current_watch_id = recheck_id
                threat_watcher_thread = threading.current_thread()
                promoted = True

            set_next_target_cooldown(2.5)
            log_event(
                "ENGAGED_FULL_TARGET_RESELECT_START",
                level="warning",
                recheck_id=recheck_id,
                previous_watch_id=old_watch_id,
                old_phase=old_phase,
                new_phase=PHASE_ACQUIRING,
                waited=time.monotonic() - start_mono,
                target_before=last_probe,
                reason="antiaggro target stayed FULL HP while player kept taking damage",
            )

            # Не используем ESC -> NEAREST_TARGET: это часто выбирает того же
            # самого ближайшего моба. Здесь цель уже признана подозрительной,
            # поэтому NEXT_TARGET должен именно прокрутить выбор дальше.
            log_event(
                "ENGAGED_FULL_TARGET_RESELECT_COMMAND",
                level="warning",
                recheck_id=recheck_id,
                command="NEXT_TARGET",
                target_before=get_target_probe(),
            )
            send_command(ser, 'NEXT_TARGET')
            cycle_sent = True
            time.sleep(settle_after_cycle)

            stable_required = _cfg_int(
                'THREAT_TARGET_STABLE_SAMPLES', 2, minimum=1
            )
            poll_target_interval = _cfg_float(
                'THREAT_TARGET_POLL_INTERVAL', 0.05, minimum=0.02
            )
            acquire_timeout = _cfg_float(
                'THREAT_TARGET_ACQUIRE_TIMEOUT', 0.8, minimum=0.2
            )
            stable, last_probe, polls = _poll_target_stable(
                recheck_id,
                source="after_engaged_next_target",
                attempt=1,
                timeout=acquire_timeout,
                poll_interval=poll_target_interval,
                required=stable_required,
            )

            if not stable:
                # Если NEXT_TARGET оставил нас вообще без цели, один fallback
                # NEAREST_TARGET лучше, чем застрять в ACQUIRING.
                log_event(
                    "ENGAGED_FULL_TARGET_RESELECT_FALLBACK",
                    level="warning",
                    recheck_id=recheck_id,
                    command="NEAREST_TARGET",
                    last_target=last_probe,
                )
                send_command(ser, 'NEAREST_TARGET')
                time.sleep(min(0.12, settle_after_cycle))
                stable, last_probe, polls = _poll_target_stable(
                    recheck_id,
                    source="after_engaged_nearest_fallback",
                    attempt=2,
                    timeout=acquire_timeout,
                    poll_interval=poll_target_interval,
                    required=stable_required,
                )

            if stable:
                log_event(
                    "ENGAGED_FULL_TARGET_RESELECT_SUCCESS",
                    level="warning",
                    recheck_id=recheck_id,
                    polls=polls,
                    target=last_probe,
                    command="ATTACK",
                )
                success = bool(_lock_and_attack(
                    ser,
                    recheck_id,
                    last_probe,
                    source="engaged_full_target_reselect",
                    attempt=1,
                    trigger_metadata={
                        "trigger_source": "engaged_full_target_recheck",
                        "baseline_hp": baseline_value,
                        "observed_hp": observed_value,
                        "hp_drop": hp_drop,
                        "target_age": target_age,
                        "decision_delay": decision_delay,
                        "previous_watch_id": old_watch_id,
                    },
                ))
                return

            log_event(
                "ENGAGED_FULL_TARGET_RESELECT_FAILED",
                level="error",
                recheck_id=recheck_id,
                target=last_probe,
                cycle_sent=cycle_sent,
                hint="NEXT_TARGET/NEAREST_TARGET не дали стабильную цель.",
            )
            _save_snapshot_async(
                "engaged_full_target_reselect_failed",
                metadata={
                    "recheck_id": recheck_id,
                    "previous_watch_id": old_watch_id,
                    "target": last_probe,
                },
            )

        except Exception as exc:
            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_EXCEPTION",
                level="error",
                recheck_id=recheck_id,
                error=repr(exc),
            )
            _save_snapshot_async(
                "engaged_full_target_recheck_exception",
                metadata={"recheck_id": recheck_id, "error": repr(exc)},
            )
        finally:
            with _state_lock:
                if threat_watcher_thread is threading.current_thread():
                    threat_watcher_thread = None

                if promoted and not success:
                    # Если после cycle всё ещё есть живая цель, возвращаем
                    # ENGAGED и позволяем будущему урону перепроверить её снова.
                    current_probe = get_target_probe()
                    if _probe_is_ready(current_probe):
                        _phase = PHASE_ENGAGED
                        _current_watch_id = old_watch_id
                    else:
                        _anti_aggro_target_active = False
                        _anti_aggro_target_since = 0.0
                        _phase = PHASE_IDLE
                        _current_watch_id = None

                if _engaged_full_recheck_thread is threading.current_thread():
                    _engaged_full_recheck_thread = None
                    _engaged_full_recheck_id = None

                final_phase = _phase
                final_watch_id = _current_watch_id

            log_event(
                "ENGAGED_FULL_TARGET_RECHECK_END",
                recheck_id=recheck_id,
                elapsed=time.monotonic() - start_mono,
                promoted=promoted,
                cycle_sent=cycle_sent,
                success=success,
                final_phase=final_phase,
                final_watch_id=final_watch_id,
                antiaggro_target_active=is_anti_aggro_target_active(),
            )

    thread = threading.Thread(
        target=engaged_recheck_logic,
        daemon=True,
        name=f'engaged_full_recheck:{recheck_id}',
    )
    with _state_lock:
        _engaged_full_recheck_thread = thread
        _engaged_full_recheck_id = recheck_id
    thread.start()
    return True

def schedule_no_target_antiaggro(
    ser,
    *,
    baseline_hp,
    observed_hp,
    baseline_age=None,
    observed_measurement=None,
    target_probe=None,
):
    """Запускает anti-aggro, если персонажа ударили при полном отсутствии цели.

    В отличие от короткого post-death watcher этот путь может запускаться в
    любой момент IDLE. Это закрывает ситуацию: watcher уже закончился, бот
    перебирает NEXT_TARGET, подходящей цели нет, но окружающие мобы продолжают
    бить персонажа.

    Первый drop, замеченный основным targeting-loop, считается кандидатом.
    Отдельный поток подтверждает HP и выдерживает 1-секундное no-target окно
    перед NEAREST_TARGET -> ATTACK. Если в окне появляется FULL-HP цель,
    применяется 2-секундное правило. Во время ожидания фаза уже ACQUIRING,
    поэтому обычный NEXT_TARGET не может выиграть race.
    """
    global threat_watcher_thread, _phase, _current_watch_id

    if not is_kill_scenario_enabled():
        log_event(
            "NO_TARGET_THREAT_TRIGGER_REJECTED",
            level="info",
            reason="THREAT_SCENARIO_KILL_ENABLED=False",
        )
        return False

    try:
        baseline_value = float(baseline_hp)
        observed_value = float(observed_hp)
    except (TypeError, ValueError):
        log_event(
            "NO_TARGET_THREAT_TRIGGER_REJECTED",
            level="error",
            reason="invalid_hp_values",
            baseline_hp=baseline_hp,
            observed_hp=observed_hp,
        )
        return False

    measurement = observed_measurement or {}
    method = measurement.get("method")
    if method == "ocr_numeric":
        threshold = _cfg_float(
            'THREAT_NO_TARGET_DROP_THRESHOLD_ABS',
            getattr(config, 'THREAT_HP_DROP_THRESHOLD_ABS', 4.0),
            minimum=1.0,
        )
        min_confidence = _cfg_float(
            'THREAT_NO_TARGET_MIN_OCR_CONFIDENCE',
            getattr(config, 'THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE', 70.0),
            minimum=0.0,
        )
        confirm_tolerance = _cfg_float(
            'THREAT_NO_TARGET_CONFIRM_TOLERANCE_ABS', 2.0, minimum=0.0
        )
    else:
        threshold = _cfg_float(
            'THREAT_NO_TARGET_DROP_THRESHOLD',
            getattr(config, 'THREAT_HP_DROP_THRESHOLD', 1.0),
            minimum=0.1,
        )
        min_confidence = 0.0
        confirm_tolerance = _cfg_float(
            'THREAT_NO_TARGET_CONFIRM_TOLERANCE',
            max(1.0, threshold),
            minimum=0.0,
        )

    initial_drop = baseline_value - observed_value
    if initial_drop < threshold:
        log_event(
            "NO_TARGET_THREAT_TRIGGER_REJECTED",
            level="debug",
            reason="drop_below_threshold",
            baseline_hp=baseline_value,
            observed_hp=observed_value,
            drop=initial_drop,
            threshold=threshold,
        )
        return False

    max_baseline_age = _cfg_float(
        'THREAT_NO_TARGET_BASELINE_MAX_AGE', 1.5, minimum=0.2
    )
    if baseline_age is not None:
        try:
            age_value = float(baseline_age)
        except (TypeError, ValueError):
            age_value = None
        if age_value is not None and age_value > max_baseline_age:
            log_event(
                "NO_TARGET_THREAT_TRIGGER_REJECTED",
                level="warning",
                reason="baseline_too_old",
                baseline_age=age_value,
                max_baseline_age=max_baseline_age,
                baseline_hp=baseline_value,
                observed_hp=observed_value,
            )
            return False

    if method == "ocr_numeric":
        confidence = measurement.get("ocr_confidence")
        try:
            confidence_ok = confidence is not None and float(confidence) >= min_confidence
        except (TypeError, ValueError):
            confidence_ok = False
        if not confidence_ok:
            log_event(
                "NO_TARGET_THREAT_TRIGGER_REJECTED",
                level="warning",
                reason="low_ocr_confidence",
                ocr_confidence=confidence,
                min_confidence=min_confidence,
                baseline_hp=baseline_value,
                observed_hp=observed_value,
            )
            return False

    initial_probe = target_probe or get_target_probe()
    if _probe_is_ready(initial_probe):
        log_event(
            "NO_TARGET_THREAT_TRIGGER_REJECTED",
            level="debug",
            reason="target_already_present",
            target=initial_probe,
        )
        return False

    watch_id = f"idle-{int(time.time() * 1000)}-{next(_watch_counter)}"
    confirm_samples = _cfg_int('THREAT_NO_TARGET_CONFIRM_SAMPLES', 2, minimum=1)
    confirm_interval = _cfg_float(
        'THREAT_NO_TARGET_CONFIRM_INTERVAL', 0.12, minimum=0.04
    )
    confirm_timeout = _cfg_float(
        'THREAT_NO_TARGET_CONFIRM_TIMEOUT', 0.65, minimum=0.15
    )
    decision_delay = _cfg_float(
        'THREAT_NO_TARGET_DECISION_DELAY', 1.0, minimum=0.10
    )

    with _state_lock:
        if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
            log_event(
                "NO_TARGET_THREAT_TRIGGER_REJECTED",
                level="debug",
                watch_id=watch_id,
                reason="watcher_already_running",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False
        if _anti_aggro_target_active:
            log_event(
                "NO_TARGET_THREAT_TRIGGER_REJECTED",
                level="debug",
                watch_id=watch_id,
                reason="antiaggro_target_already_active",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False
        pending = _live_full_pending_thread
        if pending is not None and pending.is_alive():
            log_event(
                "NO_TARGET_THREAT_TRIGGER_REJECTED",
                level="debug",
                watch_id=watch_id,
                reason="live_full_pending_active",
                pending_id=_live_full_pending_id,
            )
            return False

        _current_watch_id = watch_id
        old_phase = _phase
        _phase = PHASE_ACQUIRING

    trigger_base = {
        "baseline_hp": baseline_value,
        "observed_hp": observed_value,
        "hp_drop": initial_drop,
        "threshold": threshold,
        "baseline_age": baseline_age,
        "measurement": _measurement_summary(measurement),
        "target_at_trigger": initial_probe,
    }

    log_event(
        "NO_TARGET_THREAT_SCHEDULED",
        level="warning",
        watch_id=watch_id,
        old_phase=old_phase,
        confirm_samples=confirm_samples,
        confirm_interval=confirm_interval,
        confirm_timeout=confirm_timeout,
        decision_delay=decision_delay,
        **trigger_base,
    )

    def no_target_threat_logic():
        global threat_watcher_thread, _phase, _current_watch_id

        start_mono = time.monotonic()
        confirmations = 1
        last_hp = observed_value
        last_measurement = measurement
        acquired = False

        try:
            if not is_kill_scenario_enabled():
                log_event(
                    "NO_TARGET_THREAT_NOT_CONFIRMED",
                    level="info",
                    watch_id=watch_id,
                    reason="THREAT_SCENARIO_KILL_ENABLED switched OFF",
                )
                return

            # Если пользователь выставил confirm_samples=1, первый качественный
            # main-loop sample уже достаточен.
            deadline = time.monotonic() + confirm_timeout

            while confirmations < confirm_samples and time.monotonic() < deadline:
                time.sleep(confirm_interval)

                if not is_kill_scenario_enabled():
                    log_event(
                        "NO_TARGET_THREAT_NOT_CONFIRMED",
                        level="info",
                        watch_id=watch_id,
                        reason="THREAT_SCENARIO_KILL_ENABLED switched OFF",
                    )
                    return

                current_measurement = get_hp_measurement(include_image=False)
                last_measurement = current_measurement
                current_hp = current_measurement.get("percentage")

                if current_hp is None:
                    log_event(
                        "NO_TARGET_THREAT_CONFIRM_SAMPLE",
                        level="warning",
                        watch_id=watch_id,
                        valid=False,
                        confirmations=confirmations,
                        confirm_required=confirm_samples,
                        measurement=_measurement_summary(current_measurement),
                    )
                    continue

                current_hp = float(current_hp)
                hp_drop = baseline_value - current_hp

                confidence_ok = True
                if current_measurement.get("method") == "ocr_numeric":
                    conf = current_measurement.get("ocr_confidence")
                    try:
                        confidence_ok = (
                            conf is not None and float(conf) >= min_confidence
                        )
                    except (TypeError, ValueError):
                        confidence_ok = False

                # Допускаем дальнейшее падение HP без ограничения. Если HP
                # слегка отскочил вверх из-за regen/OCR, candidate всё ещё
                # считается подтверждённым, пока общий drop от baseline остаётся
                # выше порога и значение не ушло значительно выше first sample.
                candidate_ok = (
                    confidence_ok
                    and hp_drop >= threshold
                    and current_hp <= observed_value + confirm_tolerance
                )

                confirmations = confirmations + 1 if candidate_ok else 0
                last_hp = current_hp

                log_event(
                    "NO_TARGET_THREAT_CONFIRM_SAMPLE",
                    level="warning" if candidate_ok else "debug",
                    watch_id=watch_id,
                    valid=candidate_ok,
                    hp=current_hp,
                    baseline=baseline_value,
                    drop=hp_drop,
                    threshold=threshold,
                    confirmations=confirmations,
                    confirm_required=confirm_samples,
                    confidence_ok=confidence_ok,
                    measurement=_measurement_summary(current_measurement),
                    target=get_target_probe(),
                )

                if not candidate_ok:
                    # Если кандидат полностью исчез — выходим сразу. Новый
                    # реальный удар будет замечен постоянным IDLE-монитором.
                    break

            if confirmations < confirm_samples:
                log_event(
                    "NO_TARGET_THREAT_NOT_CONFIRMED",
                    level="warning",
                    watch_id=watch_id,
                    baseline_hp=baseline_value,
                    observed_hp=observed_value,
                    last_hp=last_hp,
                    confirmations=confirmations,
                    confirm_required=confirm_samples,
                    last_measurement=_measurement_summary(last_measurement),
                    target=get_target_probe(),
                )
                return

            if not is_kill_scenario_enabled():
                log_event(
                    "NO_TARGET_THREAT_NOT_CONFIRMED",
                    level="info",
                    watch_id=watch_id,
                    reason="THREAT_SCENARIO_KILL_ENABLED switched OFF before retarget delay",
                )
                return

            # v13/v14: при полном отсутствии таргета не переключаемся мгновенно.
            # Ждём суммарно 1 секунду от первого подтверждённого drop. Если
            # за это время внезапно появилась FULL-HP цель, автоматически
            # переключаемся на 2-секундное правило; damaged цель отменяет retarget.
            if not _wait_state_based_retarget_delay(
                watch_id,
                trigger_source="no_target_damage",
                no_target_anchor_mono=start_mono,
            ):
                return

            if not is_kill_scenario_enabled():
                log_event(
                    "NO_TARGET_THREAT_NOT_CONFIRMED",
                    level="info",
                    watch_id=watch_id,
                    reason="THREAT_SCENARIO_KILL_ENABLED switched OFF before acquire",
                )
                return

            trigger_metadata = {
                **trigger_base,
                "confirmed_hp": last_hp,
                "confirmations": confirmations,
                "confirm_required": confirm_samples,
                "confirmation_measurement": _measurement_summary(last_measurement),
            }
            log_event(
                "NO_TARGET_THREAT_CONFIRMED",
                level="warning",
                watch_id=watch_id,
                **trigger_metadata,
            )
            _save_snapshot_async(
                "no_target_threat_confirmed",
                metadata={"watch_id": watch_id, **trigger_metadata},
            )

            acquired = _acquire_aggressor(
                ser,
                watch_id=watch_id,
                trigger_metadata=trigger_metadata,
                allow_existing_target=True,
                clear_current_target=False,
                acquire_source="no_target_damage",
            )

        except Exception as exc:
            log_event(
                "NO_TARGET_THREAT_EXCEPTION",
                level="error",
                watch_id=watch_id,
                error=repr(exc),
            )
            _save_snapshot_async(
                "no_target_threat_exception",
                metadata={"watch_id": watch_id, "error": repr(exc)},
            )
        finally:
            set_threat_watcher_hp(None, None, False)
            with _state_lock:
                if threat_watcher_thread is threading.current_thread():
                    threat_watcher_thread = None
                if not _anti_aggro_target_active and _phase == PHASE_ACQUIRING:
                    _phase = PHASE_IDLE
                final_phase = _phase
                if _current_watch_id == watch_id and not _anti_aggro_target_active:
                    _current_watch_id = None

            log_event(
                "NO_TARGET_THREAT_END",
                watch_id=watch_id,
                elapsed=time.monotonic() - start_mono,
                acquired=acquired,
                final_phase=final_phase,
                antiaggro_target_active=is_anti_aggro_target_active(),
            )

    thread = threading.Thread(
        target=no_target_threat_logic,
        daemon=True,
        name=f'no_target_threat:{watch_id}',
    )
    with _state_lock:
        threat_watcher_thread = thread
    thread.start()
    return True

def schedule_threat_watch(ser, source="target_death", baseline_hint=None, baseline_hint_age=None):
    """Запускает post-death watcher, если включён сценарий «Антиагр кил»."""
    global threat_watcher_thread, _phase, _current_watch_id

    watch_id = f"{int(time.time() * 1000)}-{next(_watch_counter)}"
    if not is_kill_scenario_enabled():
        log_event(
            "WATCH_START_REJECTED",
            level="info",
            watch_id=watch_id,
            source=source,
            reason="THREAT_SCENARIO_KILL_ENABLED=False",
        )
        return False

    with _state_lock:
        if threat_watcher_thread is not None and threat_watcher_thread.is_alive():
            log_event(
                "WATCH_START_REJECTED",
                level="warning",
                watch_id=watch_id,
                reason="watcher_already_running",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False

        if _anti_aggro_target_active:
            log_event(
                "WATCH_START_REJECTED",
                level="warning",
                watch_id=watch_id,
                reason="antiaggro_target_already_active",
                current_watch_id=_current_watch_id,
                phase=_phase,
            )
            return False

        _current_watch_id = watch_id
        old_phase = _phase
        _phase = PHASE_WATCHING

    log_event(
        "WATCH_SCHEDULED",
        watch_id=watch_id,
        source=source,
        old_phase=old_phase,
        baseline_hint=baseline_hint,
        baseline_hint_age=baseline_hint_age,
        coordinates=collect_coordinate_diagnostics(),
        log_path=str(get_log_path()),
    )

    def threat_watcher_logic():
        global threat_watcher_thread, _phase, _current_watch_id

        last_measurement = None
        snapshot_on_read_error_done = False
        start_mono = time.monotonic()

        try:
            if not is_kill_scenario_enabled():
                log_event(
                    "WATCH_ABORT_SCENARIO_DISABLED",
                    level="info",
                    watch_id=watch_id,
                    source=source,
                    reason="THREAT_SCENARIO_KILL_ENABLED switched OFF",
                )
                return

            configured_duration = _cfg_float('THREAT_WATCH_DURATION', 2.0, minimum=0.2)
            min_effective_duration = _cfg_float(
                'THREAT_WATCH_EFFECTIVE_MIN_DURATION', 3.0, minimum=0.5
            )
            duration = max(configured_duration, min_effective_duration)
            check_interval = _cfg_float('THREAT_WATCH_CHECK_INTERVAL', 0.1, minimum=0.03)
            configured_drop_threshold = _cfg_float(
                'THREAT_HP_DROP_THRESHOLD', 1.0, minimum=0.1
            )
            confirm_samples = _cfg_int('THREAT_HP_CONFIRM_SAMPLES', 2, minimum=1)
            configured_confirm_tolerance = _cfg_float(
                'THREAT_HP_CONFIRM_TOLERANCE',
                max(1.0, configured_drop_threshold),
                minimum=0.0,
            )
            baseline_hint_max_age = _cfg_float(
                'THREAT_BASELINE_HINT_MAX_AGE', 1.25, minimum=0.1
            )

            log_event(
                "WATCH_START",
                watch_id=watch_id,
                source=source,
                configured_duration=configured_duration,
                duration=duration,
                min_effective_duration=min_effective_duration,
                check_interval=check_interval,
                drop_threshold=configured_drop_threshold,
                numeric_drop_threshold=getattr(config, 'THREAT_HP_DROP_THRESHOLD_ABS', 4.0),
                confirm_samples=confirm_samples,
                confirm_tolerance=configured_confirm_tolerance,
                baseline_hint_max_age=baseline_hint_max_age,
                baseline_hint=baseline_hint,
                baseline_hint_age=baseline_hint_age,
                target_at_start=get_target_probe(),
                coordinates=collect_coordinate_diagnostics(),
            )

            baseline_hp, baseline_measurements = _read_stable_hp(
                sample_count=3,
                sample_delay=min(0.03, check_interval / 2.0),
                watch_id=watch_id,
            )
            if baseline_hp is None:
                log_event(
                    "WATCH_ABORT_NO_BASELINE_HP",
                    level="error",
                    watch_id=watch_id,
                    measurements=[_measurement_summary(m) for m in baseline_measurements],
                    hint="HP_BAR_RECT не читается или красная полоска не попадает в область.",
                )
                first_image = None
                if baseline_measurements:
                    first_image = baseline_measurements[0].get("image")
                save_debug_snapshot(
                    "no_baseline_hp",
                    metadata={
                        "watch_id": watch_id,
                        "measurements": [_measurement_summary(m) for m in baseline_measurements],
                    },
                    hp_image=first_image,
                )
                set_threat_watcher_hp(None, None, False)
                return

            raw_baseline_hp = float(baseline_hp)
            baseline_method = next(
                (
                    m.get("method")
                    for m in baseline_measurements
                    if m and m.get("percentage") is not None and m.get("method")
                ),
                None,
            )

            # В bar-режиме старый порог остаётся процентным. Для LU4 OCR число
            # абсолютное, поэтому 1.0 означает всего 1 HP и слишком чувствительно.
            if baseline_method == "ocr_numeric":
                drop_threshold = _cfg_float(
                    'THREAT_HP_DROP_THRESHOLD_ABS', 4.0, minimum=1.0
                )
                confirm_tolerance = _cfg_float(
                    'THREAT_HP_CONFIRM_TOLERANCE_ABS',
                    max(1.0, min(2.0, drop_threshold / 2.0)),
                    minimum=0.0,
                )
            else:
                drop_threshold = configured_drop_threshold
                confirm_tolerance = configured_confirm_tolerance

            hint_value = None
            hint_age_value = None
            hint_fresh = False
            if baseline_hint is not None:
                try:
                    hint_value = float(baseline_hint)
                except (TypeError, ValueError):
                    hint_value = None
            if baseline_hint_age is not None:
                try:
                    hint_age_value = float(baseline_hint_age)
                except (TypeError, ValueError):
                    hint_age_value = None
            if hint_value is not None and hint_age_value is not None:
                hint_fresh = 0.0 <= hint_age_value <= baseline_hint_max_age

            baseline_values = []
            for measurement in baseline_measurements:
                try:
                    value = measurement.get("percentage")
                    if value is not None:
                        baseline_values.append(float(value))
                except Exception:
                    pass

            baseline_hint_drop = (
                hint_value - raw_baseline_hp if hint_value is not None else None
            )
            prebaseline_drop_confirmations = 0
            if hint_fresh:
                prebaseline_drop_confirmations = sum(
                    1 for value in baseline_values
                    if (hint_value - value) >= drop_threshold
                )

            # Если свежий live-sample был, например, 122 HP, а сразу после смерти
            # три OCR-прохода дают 419, это слишком большой скачок вверх для
            # доверенного baseline. В присланном логе именно такой кадр затем
            # создал фиктивный drop 419 -> 108 = 311 HP.
            #
            # Мы не отбрасываем OCR совсем: просто используем свежий pre-death
            # sample как консервативный baseline до конца короткого watcher.
            baseline_rebased_to_hint = False
            if (
                baseline_method == "ocr_numeric"
                and hint_fresh
                and raw_baseline_hp > hint_value
            ):
                suspicious_up_abs = _cfg_float(
                    'THREAT_HP_SUSPICIOUS_UP_JUMP_ABS', 60.0, minimum=10.0
                )
                suspicious_up_ratio = _cfg_float(
                    'THREAT_HP_SUSPICIOUS_UP_JUMP_RATIO', 0.50, minimum=0.10
                )
                suspicious_up_limit = max(
                    suspicious_up_abs,
                    abs(hint_value) * suspicious_up_ratio,
                )
                upward_jump = raw_baseline_hp - hint_value
                if upward_jump >= suspicious_up_limit:
                    baseline_hp = hint_value
                    baseline_rebased_to_hint = True
                    log_event(
                        "HP_BASELINE_REBASED_TO_RECENT_HINT",
                        level="warning",
                        watch_id=watch_id,
                        raw_baseline_hp=raw_baseline_hp,
                        effective_baseline_hp=baseline_hp,
                        baseline_hint=hint_value,
                        baseline_hint_age=hint_age_value,
                        upward_jump=upward_jump,
                        suspicious_limit=suspicious_up_limit,
                        method=baseline_method,
                        hint=(
                            "Слишком большой скачок HP вверх сразу после смерти цели. "
                            "Для защиты от OCR-ошибки watcher временно использует свежий pre-death HP."
                        ),
                    )

            baseline_hp = float(baseline_hp)
            previous_hp = baseline_hp
            min_hp = min(raw_baseline_hp, baseline_hp)
            max_hp = max(raw_baseline_hp, baseline_hp)
            max_drop = 0.0
            consecutive_drop_samples = 0
            candidate_hp = None
            sample_no = 0
            none_samples = 0
            suspicious_samples = 0
            last_heartbeat_mono = 0.0
            damaged_target_streak = 0
            damaged_target_confirm_required = _cfg_int(
                'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES', 2, minimum=1
            )
            end_time = time.monotonic() + duration
            set_threat_watcher_hp(previous_hp, previous_hp, False)

            log_event(
                "HP_BASELINE_READY",
                watch_id=watch_id,
                baseline_hp=baseline_hp,
                raw_baseline_hp=raw_baseline_hp,
                baseline_rebased_to_hint=baseline_rebased_to_hint,
                baseline_method=baseline_method,
                drop_threshold=drop_threshold,
                confirm_tolerance=confirm_tolerance,
                baseline_hint=hint_value,
                baseline_hint_age=hint_age_value,
                baseline_hint_fresh=hint_fresh,
                baseline_hint_drop=baseline_hint_drop,
                prebaseline_drop_confirmations=prebaseline_drop_confirmations,
                measurements=[_measurement_summary(m) for m in baseline_measurements],
            )

            # v3 только диагностировал это окно и ждал ЕЩЁ одного удара. По
            # присланному логу терялись реальные падения 187->165 и 244->230.
            # Теперь свежий pre-death sample + несколько baseline OCR-замеров
            # являются полноценным подтверждением входящего урона.
            if (
                hint_fresh
                and baseline_hint_drop is not None
                and baseline_hint_drop >= drop_threshold
                and prebaseline_drop_confirmations >= min(2, len(baseline_values))
            ):
                trigger_measurement = (
                    baseline_measurements[-1] if baseline_measurements else None
                )
                trigger_metadata = {
                    "baseline_hp": hint_value,
                    "raw_watcher_baseline_hp": raw_baseline_hp,
                    "effective_baseline_hp": baseline_hp,
                    "current_hp": raw_baseline_hp,
                    "hp_drop": baseline_hint_drop,
                    "sample": "prebaseline",
                    "confirmations": prebaseline_drop_confirmations,
                    "measurement": _measurement_summary(trigger_measurement),
                    "trigger_source": "predeath_to_watcher_baseline",
                }
                log_event(
                    "HP_DROP_BEFORE_WATCHER_BASELINE",
                    level="warning",
                    watch_id=watch_id,
                    predeath_hp=hint_value,
                    predeath_age=hint_age_value,
                    watcher_baseline_hp=raw_baseline_hp,
                    drop=baseline_hint_drop,
                    threshold=drop_threshold,
                    confirmations=prebaseline_drop_confirmations,
                    action="trigger_antiaggro_immediately",
                )
                if not _wait_for_post_kill_sweep_before_acquire(
                    watch_id,
                    trigger_source="prebaseline_hp_drop_confirmed",
                ):
                    return
                if not _wait_state_based_retarget_delay(
                    watch_id,
                    trigger_source="prebaseline_hp_drop_confirmed",
                    no_target_anchor_mono=_last_target_lost_mono,
                ):
                    return
                damaged_now, damaged_probe = _confirm_existing_target_damaged(
                    watch_id,
                    source="prebaseline_before_acquiring",
                    required=_cfg_int(
                        'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES', 2, minimum=1
                    ),
                    interval=_cfg_float(
                        'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL', 0.05, minimum=0.02
                    ),
                )
                if damaged_now:
                    log_event(
                        "WATCH_CANCELLED_COMBAT_ALREADY_STARTED",
                        level="warning",
                        watch_id=watch_id,
                        target=damaged_probe,
                        decision="keep_current_target",
                        reason="target_is_damaged_before_prebaseline_antiaggro_acquire",
                    )
                    return
                _set_phase(
                    PHASE_ACQUIRING,
                    watch_id=watch_id,
                    reason="prebaseline_hp_drop_confirmed_after_sweep",
                )
                log_event(
                    "THREAT_CONFIRMED_PREBASELINE",
                    level="warning",
                    watch_id=watch_id,
                    **trigger_metadata,
                )
                _save_snapshot_async(
                    "threat_confirmed_prebaseline",
                    metadata={"watch_id": watch_id, **trigger_metadata},
                )
                _acquire_aggressor(
                    ser,
                    watch_id=watch_id,
                    trigger_metadata=trigger_metadata,
                    abort_if_existing_damaged=True,
                )
                return

            if baseline_hint is not None and not hint_fresh:
                log_event(
                    "BASELINE_HINT_IGNORED_STALE",
                    level="debug",
                    watch_id=watch_id,
                    baseline_hint=baseline_hint,
                    baseline_hint_age=baseline_hint_age,
                    max_age=baseline_hint_max_age,
                )

            while time.monotonic() < end_time:
                if not is_kill_scenario_enabled():
                    log_event(
                        "WATCH_ABORT_SCENARIO_DISABLED",
                        level="info",
                        watch_id=watch_id,
                        reason="THREAT_SCENARIO_KILL_ENABLED switched OFF during watch",
                    )
                    return

                # Если после смерти предыдущего моба бот уже успел начать бой с
                # новой целью и её HP реально уменьшилось, post-death watcher
                # больше не должен реагировать на входящий урон и менять target.
                # Два подряд кадра защищают от единичного серого пикселя UI.
                combat_probe = get_target_probe()
                if _probe_is_damaged(combat_probe):
                    damaged_target_streak += 1
                else:
                    damaged_target_streak = 0

                if damaged_target_streak:
                    log_event(
                        "POST_DEATH_DAMAGED_TARGET_OBSERVED",
                        level="debug",
                        watch_id=watch_id,
                        streak=damaged_target_streak,
                        required=damaged_target_confirm_required,
                        target=combat_probe,
                    )

                if damaged_target_streak >= damaged_target_confirm_required:
                    log_event(
                        "WATCH_CANCELLED_COMBAT_ALREADY_STARTED",
                        level="warning",
                        watch_id=watch_id,
                        target=combat_probe,
                        damaged_streak=damaged_target_streak,
                        decision="keep_current_target",
                        reason=(
                            "current living target lost HP while post-death watcher was active; "
                            "normal combat has already started"
                        ),
                    )
                    return

                sample_no += 1
                measurement = get_hp_measurement(include_image=False)
                last_measurement = measurement
                current_hp = measurement.get("percentage")

                if current_hp is None:
                    none_samples += 1
                    set_threat_watcher_hp(previous_hp, None, False)
                    log_event(
                        "HP_SAMPLE_INVALID",
                        level="warning",
                        watch_id=watch_id,
                        sample=sample_no,
                        previous_hp=previous_hp,
                        measurement=_measurement_summary(measurement),
                    )
                    if not snapshot_on_read_error_done:
                        snapshot_on_read_error_done = True
                        _save_snapshot_async(
                            "hp_read_failed_during_watch",
                            metadata={
                                "watch_id": watch_id,
                                "sample": sample_no,
                                "measurement": _measurement_summary(measurement),
                            },
                        )
                    time.sleep(check_interval)
                    continue

                current_hp = float(current_hp)
                min_hp = min(min_hp, current_hp)
                max_hp = max(max_hp, current_hp)

                # Baseline в коротком post-death окне НЕ поднимаем по одному
                # OCR-сэмплу. Ошибка 189 -> 789 -> 189 иначе создала бы ложный
                # гигантский drop на следующем кадре. Хил выше baseline просто
                # даёт отрицательный drop и не является угрозой.
                hp_drop = baseline_hp - current_hp
                max_drop = max(max_drop, hp_drop)
                is_falling = hp_drop >= drop_threshold

                if is_falling:
                    if candidate_hp is None or abs(current_hp - candidate_hp) <= confirm_tolerance:
                        consecutive_drop_samples += 1
                    else:
                        log_event(
                            "HP_DROP_CANDIDATE_CHANGED",
                            level="warning",
                            watch_id=watch_id,
                            sample=sample_no,
                            old_candidate=candidate_hp,
                            new_candidate=current_hp,
                            tolerance=confirm_tolerance,
                        )
                        consecutive_drop_samples = 1
                    candidate_hp = current_hp
                else:
                    if hp_drop > 0.0:
                        suspicious_samples += 1
                    consecutive_drop_samples = 0
                    candidate_hp = None

                set_threat_watcher_hp(previous_hp, current_hp, is_falling)

                log_event(
                    "HP_SAMPLE",
                    level="debug",
                    watch_id=watch_id,
                    sample=sample_no,
                    hp=current_hp,
                    previous_hp=previous_hp,
                    baseline=baseline_hp,
                    drop=hp_drop,
                    threshold=drop_threshold,
                    falling=is_falling,
                    confirmations=consecutive_drop_samples,
                    confirm_required=confirm_samples,
                    method=measurement.get("method"),
                    ocr_text=measurement.get("ocr_text"),
                    ocr_confidence=measurement.get("ocr_confidence"),
                    ocr_pass=measurement.get("ocr_pass"),
                    row_spread=measurement.get("row_spread"),
                    rows=measurement.get("rows"),
                )

                # В консоли даем heartbeat раз в ~0.5 сек. Детальный probe читаем
                # только в момент реального логирования, а не на каждом sample.
                now_mono = time.monotonic()
                if now_mono - last_heartbeat_mono >= 0.5:
                    last_heartbeat_mono = now_mono
                    log_event(
                        "WATCH_HEARTBEAT",
                        watch_id=watch_id,
                        sample=sample_no,
                        hp=current_hp,
                        baseline=baseline_hp,
                        drop=hp_drop,
                        confirmations=consecutive_drop_samples,
                        target=get_target_probe(),
                    )

                if consecutive_drop_samples >= confirm_samples:
                    trigger_metadata = {
                        "baseline_hp": baseline_hp,
                        "current_hp": current_hp,
                        "hp_drop": hp_drop,
                        "sample": sample_no,
                        "confirmations": consecutive_drop_samples,
                        "measurement": _measurement_summary(measurement),
                    }
                    # Приоритет anti-aggro выставляем ПЕРЕД любым snapshot/log I/O.
                    # Это закрывает race из присланного лога, где spoil успел
                    # отправить SKILL1_SPOIL между THREAT_CONFIRMED и ACQUIRING.
                    if not _wait_for_post_kill_sweep_before_acquire(
                        watch_id,
                        trigger_source="hp_drop_confirmed",
                    ):
                        return
                    if not _wait_state_based_retarget_delay(
                        watch_id,
                        trigger_source="hp_drop_confirmed",
                        no_target_anchor_mono=_last_target_lost_mono,
                    ):
                        return
                    damaged_now, damaged_probe = _confirm_existing_target_damaged(
                        watch_id,
                        source="hp_drop_before_acquiring",
                        required=_cfg_int(
                            'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES', 2, minimum=1
                        ),
                        interval=_cfg_float(
                            'THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL', 0.05, minimum=0.02
                        ),
                    )
                    if damaged_now:
                        log_event(
                            "WATCH_CANCELLED_COMBAT_ALREADY_STARTED",
                            level="warning",
                            watch_id=watch_id,
                            target=damaged_probe,
                            decision="keep_current_target",
                            reason="target_became_damaged_before_post_death_antiaggro_acquire",
                            hp_drop=hp_drop,
                            current_hp=current_hp,
                        )
                        return
                    _set_phase(
                        PHASE_ACQUIRING,
                        watch_id=watch_id,
                        reason="hp_drop_confirmed_after_sweep",
                    )
                    log_event(
                        "THREAT_CONFIRMED",
                        level="warning",
                        watch_id=watch_id,
                        **trigger_metadata,
                    )
                    _save_snapshot_async(
                        "threat_confirmed",
                        metadata={"watch_id": watch_id, **trigger_metadata},
                    )
                    _acquire_aggressor(
                        ser,
                        watch_id=watch_id,
                        trigger_metadata=trigger_metadata,
                        abort_if_existing_damaged=True,
                    )
                    return

                previous_hp = current_hp
                time.sleep(check_interval)

            elapsed = time.monotonic() - start_mono
            timeout_target = get_target_probe()
            level = "warning" if max_drop > 0 or none_samples else "info"
            log_event(
                "WATCH_TIMEOUT_NO_THREAT",
                level=level,
                watch_id=watch_id,
                elapsed=elapsed,
                samples=sample_no,
                invalid_samples=none_samples,
                baseline=baseline_hp,
                min_hp=min_hp,
                max_hp=max_hp,
                max_drop=max_drop,
                drop_threshold=drop_threshold,
                suspicious_samples=suspicious_samples,
                last_measurement=_measurement_summary(last_measurement),
                target_at_timeout=timeout_target,
                hint=(
                    "Если персонажа реально били, сравни max_drop с drop_threshold и открой HP_SAMPLE. "
                    "Если max_drop=0 — вероятнее всего неверно читается HP_BAR_RECT или удар произошел вне окна watcher."
                ),
            )

            # Если HP хоть немного двигался, чтение пропадало или в момент timeout уже есть
            # живая цель — сохраняем снимок для разбора, даже если порог не подтвердился.
            if max_drop > 0 or none_samples or timeout_target.get("alive_by_hp1"):
                save_debug_snapshot(
                    "watch_timeout_no_threat",
                    metadata={
                        "watch_id": watch_id,
                        "samples": sample_no,
                        "invalid_samples": none_samples,
                        "baseline": baseline_hp,
                        "min_hp": min_hp,
                        "max_hp": max_hp,
                        "max_drop": max_drop,
                        "drop_threshold": drop_threshold,
                        "target": timeout_target,
                        "last_measurement": _measurement_summary(last_measurement),
                    },
                )

        except Exception as exc:
            log_event(
                "WATCH_EXCEPTION",
                level="error",
                watch_id=watch_id,
                error=repr(exc),
            )
            save_debug_snapshot(
                "watch_exception",
                metadata={"watch_id": watch_id, "error": repr(exc)},
            )

        finally:
            set_threat_watcher_hp(None, None, False)
            with _state_lock:
                threat_watcher_thread = None
                if not _anti_aggro_target_active:
                    _phase = PHASE_IDLE
                final_phase = _phase
                if _current_watch_id == watch_id and not _anti_aggro_target_active:
                    _current_watch_id = None
            log_event(
                "WATCH_END",
                watch_id=watch_id,
                elapsed=time.monotonic() - start_mono,
                final_phase=final_phase,
                antiaggro_target_active=is_anti_aggro_target_active(),
            )

    thread = threading.Thread(target=threat_watcher_logic, daemon=True, name=f'threat_watcher:{watch_id}')
    with _state_lock:
        threat_watcher_thread = thread
    thread.start()
    return True
