"""Модуль управления спойлом цели.

v10: приоритет спойла в самом начале боя.

Основные правила:
- как только появилась новая валидная цель, первая попытка SKILL1_SPOIL идет сразу;
- первые несколько секунд до успешного спойла повторные попытки идут часто;
- ATTACK от spoil_manager не отправляется раньше первой попытки SPOIL;
- во время anti-aggro WATCHING/ACQUIRING спойл уступает управление;
- после anti-aggro ENGAGED новая цель немедленно перевооружает spoil-manager.
"""

import threading
import time
import random

from la2_bot.core.comm import send_command
from la2_bot.config import config
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match, is_target_color
from la2_bot.detection import green_pixel_utils
from la2_bot.utils import coordinate_utils
from la2_bot.utils.target_utils import is_target_selected
from la2_bot.utils.threat_watcher import (
    is_anti_aggro_target_active,
    is_threat_watcher_active,
    get_threat_watcher_phase,
    get_current_watch_id,
)
from la2_bot.utils.antiaggro_diagnostics import log_event, log_event_throttled


spoil_process_thread = None
spoil_stop_event = threading.Event()

spoiled_event = threading.Event()
spoiled_event.clear()
first_spoil_success_event = threading.Event()
first_spoil_success_event.clear()

# Пока Event установлен, другие боевые подсистемы не должны начинать обычную
# атаку: цель сначала надо попытаться успешно заспойлить.
_spoil_priority_pending_event = threading.Event()
_spoil_priority_pending_event.clear()


def _cfg_float(name, default, minimum=None):
    try:
        value = float(getattr(config, name, default))
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    return value


def _antiaggro_blocks_spoil():
    """Блокировать spoil только пока anti-aggro еще выбирает цель.

    ENGAGED не блокирует spoil: после успешного anti-aggro найденного моба
    надо спойлить так же, как обычную боевую цель.
    """
    phase = get_threat_watcher_phase()

    if phase == 'ACQUIRING':
        return True

    if phase == 'WATCHING' and is_threat_watcher_active():
        return True

    return False


def _target_is_alive_and_selected():
    point = getattr(coordinate_utils, 'TARGET_HP_1_POINT', None)
    if not point:
        return False, None

    try:
        hp1_color = get_pixel_color(*point)
        alive = is_target_color(hp1_color)
        if alive and not is_target_selected():
            alive = False
        return alive, hp1_color
    except Exception:
        return False, None


def _target_is_full_hp():
    point = getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None)
    if not point:
        return False
    try:
        return is_target_color(get_pixel_color(*point))
    except Exception:
        return False


def manage_spoil_process(ser, pause_event):
    global spoil_process_thread
    if spoil_process_thread and spoil_process_thread.is_alive():
        return

    spoil_stop_event.clear()

    def spoil_worker_logic():
        current_target_id = None
        target_started_at = None
        first_spoil_successful = False
        first_spoil_command_sent = False
        next_spoil_attempt_at = 0.0
        pending_attack_at = None
        rearm_after_antiaggro = False
        last_full_hp = False

        # Новые параметры необязательны: если их нет в config, работают defaults.
        priority_window = _cfg_float('SPOIL_PRIORITY_WINDOW_SECONDS', 3.0, 0.5)
        priority_retry = _cfg_float('SPOIL_PRIORITY_RETRY_INTERVAL', 0.25, 0.08)
        # Обычная атака разрешается сразу после подтвержденного спойла.
        # Если green detector не подтвердил его совсем, fallback не дает боту
        # зависнуть на цели навсегда.
        post_success_attack_delay = _cfg_float('SPOIL_POST_SUCCESS_ATTACK_DELAY', 0.08, 0.0)
        attack_fallback_timeout = _cfg_float('SPOIL_ATTACK_FALLBACK_TIMEOUT', 2.5, 0.5)
        loop_interval = _cfg_float('SPOIL_FAST_LOOP_INTERVAL', 0.03, 0.01)

        def reset_target_state(reason=None):
            nonlocal current_target_id
            nonlocal target_started_at
            nonlocal first_spoil_successful
            nonlocal first_spoil_command_sent
            nonlocal next_spoil_attempt_at
            nonlocal pending_attack_at
            nonlocal last_full_hp

            if reason and current_target_id is not None:
                log_event(
                    'SPOIL_TARGET_STATE_RESET',
                    level='debug',
                    reason=reason,
                    target_id=current_target_id,
                )

            current_target_id = None
            target_started_at = None
            first_spoil_successful = False
            first_spoil_command_sent = False
            next_spoil_attempt_at = 0.0
            pending_attack_at = None
            last_full_hp = False

            spoiled_event.clear()
            first_spoil_success_event.clear()
            _spoil_priority_pending_event.clear()
            green_pixel_utils.clear_green_pixel_detected()

        def arm_new_target(hp1_color, reason='target_appeared'):
            nonlocal current_target_id
            nonlocal target_started_at
            nonlocal first_spoil_successful
            nonlocal first_spoil_command_sent
            nonlocal next_spoil_attempt_at
            nonlocal pending_attack_at
            nonlocal last_full_hp

            now = time.monotonic()
            current_target_id = time.time()
            target_started_at = now
            first_spoil_successful = False
            first_spoil_command_sent = False
            next_spoil_attempt_at = now  # ВАЖНО: первая попытка без задержки.
            pending_attack_at = None
            last_full_hp = _target_is_full_hp()

            spoiled_event.clear()
            first_spoil_success_event.clear()
            _spoil_priority_pending_event.set()
            green_pixel_utils.clear_green_pixel_detected()

            log_event(
                'SPOIL_NEW_TARGET',
                level='info',
                target_id=current_target_id,
                reason=reason,
                hp1_rgb=hp1_color,
                target_full_hp=last_full_hp,
                first_attempt='immediate',
                priority_window=priority_window,
                priority_retry=priority_retry,
            )

        while not spoil_stop_event.is_set():
            if not pause_event.is_set():
                time.sleep(0.10)
                continue

            if _antiaggro_blocks_spoil():
                # После выхода из WATCHING/ACQUIRING обязательно считаем
                # anti-aggro цель новой, даже если HP-полоска между целями
                # визуально не исчезала.
                rearm_after_antiaggro = True
                pending_attack_at = None

                log_event_throttled(
                    'spoil_paused_antiaggro',
                    1.0,
                    'SPOIL_PAUSED_BY_ANTIAGGRO',
                    level='info',
                    phase=get_threat_watcher_phase(),
                    watch_id=get_current_watch_id(),
                )
                time.sleep(loop_interval)
                continue

            if rearm_after_antiaggro:
                reset_target_state('antiaggro_rearm')
                rearm_after_antiaggro = False
                log_event(
                    'SPOIL_REARM_AFTER_ANTIAGGRO',
                    level='info',
                    phase=get_threat_watcher_phase(),
                    watch_id=get_current_watch_id(),
                    antiaggro_target_active=is_anti_aggro_target_active(),
                )

            if not all([
                getattr(coordinate_utils, 'TARGET_HP_1_POINT', None),
                getattr(coordinate_utils, 'SKILL_RESET_POINT', None),
            ]):
                log_event_throttled(
                    'spoil_wait_coords',
                    2.0,
                    'SPOIL_WAIT_COORDINATES',
                    level='debug',
                )
                time.sleep(0.5)
                continue

            hp1_red, hp1_color = _target_is_alive_and_selected()

            if not hp1_red:
                if current_target_id is not None:
                    reset_target_state('target_disappeared_or_died')
                time.sleep(0.05)
                continue

            current_full_hp = _target_is_full_hp()

            if current_target_id is None:
                arm_new_target(hp1_color, reason='target_appeared')

            # Дополнительная страховка для прямого переключения с поврежденного
            # моба на новую full-HP цель, когда HP-полоска вообще не успела
            # исчезнуть между двумя таргетами.
            elif current_full_hp and not last_full_hp and first_spoil_successful:
                reset_target_state('damaged_to_full_target_transition')
                arm_new_target(hp1_color, reason='damaged_to_full_target_transition')

            last_full_hp = current_full_hp
            now = time.monotonic()
            target_age = now - target_started_at if target_started_at is not None else 0.0

            # Green detector работает отдельно. Как только он подтвердил spoil,
            # мгновенно закрываем все дальнейшие попытки для этой цели.
            if green_pixel_utils.is_green_pixel_detected():
                green_pixel_utils.clear_green_pixel_detected()
                spoiled_event.set()

                if not first_spoil_successful:
                    first_spoil_successful = True
                    first_spoil_success_event.set()
                    _spoil_priority_pending_event.clear()
                    # После подтвержденного spoil можно сразу переходить к атаке.
                    if first_spoil_command_sent:
                        pending_attack_at = now + post_success_attack_delay
                    log_event(
                        'SPOIL_SUCCESS',
                        level='info',
                        target_id=current_target_id,
                        target_age=target_age,
                        first_command_sent=first_spoil_command_sent,
                    )

            # ATTACK, который принадлежит spoil_manager, никогда не может пройти
            # раньше первой команды SPOIL. Он отложен, но worker в это время НЕ
            # спит: продолжает видеть green pixel и готовность скилла.
            if pending_attack_at is not None and now >= pending_attack_at:
                if first_spoil_command_sent and not _antiaggro_blocks_spoil():
                    alive_now, _ = _target_is_alive_and_selected()
                    if alive_now:
                        if not first_spoil_successful:
                            # Hard fallback: spoil не подтвержден, но полностью
                            # стопорить бой дольше нельзя.
                            _spoil_priority_pending_event.clear()
                            log_event(
                                'SPOIL_PRIORITY_TIMEOUT_ATTACK_FALLBACK',
                                level='warning',
                                target_id=current_target_id,
                                target_age=target_age,
                                timeout=attack_fallback_timeout,
                            )
                        else:
                            log_event(
                                'SPOIL_POST_SUCCESS_ATTACK',
                                level='info',
                                target_id=current_target_id,
                                target_age=target_age,
                            )
                        send_command(ser, 'ATTACK')
                pending_attack_at = None

            if not first_spoil_successful and now >= next_spoil_attempt_at:
                skill_reset_color = get_pixel_color(*coordinate_utils.SKILL_RESET_POINT)
                skill_ready = not is_color_match(skill_reset_color, config.SKILL_RESET_COLOR)

                if skill_ready:
                    if _antiaggro_blocks_spoil():
                        time.sleep(loop_interval)
                        continue

                    # Первая команда — сразу после обнаружения цели.
                    # Если бот еще далеко и команда не сработала, в первые
                    # priority_window секунд повторяем быстро.
                    if not first_spoil_command_sent:
                        attempt_type = 'immediate_first'
                    elif target_age <= priority_window:
                        attempt_type = 'priority_retry'
                    else:
                        attempt_type = 'normal_retry'

                    log_event(
                        'SPOIL_COMMAND',
                        level='info' if attempt_type == 'immediate_first' else 'debug',
                        command='SKILL1_SPOIL',
                        target_id=current_target_id,
                        target_age=target_age,
                        attempt_type=attempt_type,
                        target_full_hp=current_full_hp,
                    )
                    send_command(ser, 'SKILL1_SPOIL')

                    if not first_spoil_command_sent:
                        first_spoil_command_sent = True
                        # Не блокируем поток sleep(1). ATTACK просто ставится
                        # в очередь на чуть позже, а spoil-check продолжает жить.
                        pending_attack_at = now + attack_fallback_timeout

                    if target_age <= priority_window:
                        next_spoil_attempt_at = now + priority_retry
                    else:
                        next_spoil_attempt_at = now + random.uniform(
                            config.SPOIL_ATTEMPT_INTERVAL_MIN,
                            config.SPOIL_ATTEMPT_INTERVAL_MAX,
                        )
                else:
                    # Главное отличие от старого алгоритма: если скилл сейчас
                    # не готов, НЕ засыпаем на 0.85-1.4 сек. Проверяем часто и
                    # жмем SPOIL сразу, как только он станет доступен.
                    log_event_throttled(
                        f'spoil_skill_wait_{current_target_id}',
                        0.5,
                        'SPOIL_WAIT_SKILL_READY',
                        level='debug',
                        target_id=current_target_id,
                        target_age=target_age,
                    )
                    next_spoil_attempt_at = now + loop_interval

            time.sleep(loop_interval)

    spoil_process_thread = threading.Thread(
        target=spoil_worker_logic,
        daemon=True,
        name='spoil_worker',
    )
    spoil_process_thread.start()
    print('[spoil_process] Поток спойла запущен.')


def stop_spoil_process():
    global spoil_process_thread
    if spoil_process_thread and spoil_process_thread.is_alive():
        print('[spoil_process] Получен сигнал остановки.')
        spoil_stop_event.set()
        spoil_process_thread.join(timeout=1.0)
        spoil_process_thread = None


def is_any_spoil_success():
    return spoiled_event.is_set()


def clear_any_spoil_success():
    spoiled_event.clear()


def is_first_spoil_success():
    return first_spoil_success_event.is_set()


def clear_first_spoil_success():
    first_spoil_success_event.clear()



def is_spoil_priority_pending():
    """True, пока новая цель должна получить spoil раньше обычной атаки."""
    return _spoil_priority_pending_event.is_set()


is_spoil_success = is_any_spoil_success
clear_spoil_success = clear_any_spoil_success
