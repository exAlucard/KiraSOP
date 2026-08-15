# la2_bot/core/debug_state.py
"""Модуль для хранения и управления состоянием отладочной информации и глобальных флагов."""

import threading
import time

from la2_bot.utils.antiaggro_diagnostics import log_event

# Словарь для хранения отладочной информации и блокировка для потокобезопасного доступа
_debug_data = {
    'threat_watcher': {
        'previous_hp': None,
        'current_hp': None,
        'hp_falling': False
    },
    'next_target_cooldown_until': 0,  # Время, до которого поиск новой цели заблокирован
}
_lock = threading.Lock()


def set_threat_watcher_hp(previous_hp, current_hp, is_falling):
    """Потокобезопасно обновляет информацию о HP для threat_watcher."""
    with _lock:
        _debug_data['threat_watcher']['previous_hp'] = previous_hp
        _debug_data['threat_watcher']['current_hp'] = current_hp
        _debug_data['threat_watcher']['hp_falling'] = is_falling


def get_threat_watcher_hp():
    """Потокобезопасно получает информацию о HP для threat_watcher."""
    with _lock:
        return _debug_data['threat_watcher'].copy()


def set_next_target_cooldown(duration_seconds):
    """
    Продлевает кулдаун на поиск следующей цели.

    Важно: более короткий новый кулдаун больше НЕ может случайно сократить
    уже установленный длинный кулдаун из другого потока.
    """
    try:
        duration_seconds = max(0.0, float(duration_seconds))
    except (TypeError, ValueError):
        return

    new_until = time.time() + duration_seconds
    with _lock:
        old_until = _debug_data['next_target_cooldown_until']
        if new_until > old_until:
            _debug_data['next_target_cooldown_until'] = new_until
            log_event(
                "NEXT_TARGET_COOLDOWN_EXTENDED",
                level="debug",
                duration=duration_seconds,
                old_until=old_until,
                new_until=new_until,
            )


def is_next_target_on_cooldown():
    """Проверяет, активен ли кулдаун на поиск следующей цели."""
    with _lock:
        return time.time() < _debug_data['next_target_cooldown_until']
