# la2_bot/actions/stuck_mode.py
"""Независимый режим Stuck.

Логика:
- Проверяет пиксель полного HP: TARGET_HP_FULL_POINT.
- Если он красный непрерывно дольше STUCK_TARGET_TIMEOUT:
  - выполняет RETURN_TO_TARGET;
  - сбрасывает внутренний таймер.

Во время anti-aggro режим временно не вмешивается в выбор цели.
"""

import time

from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.utils.threat_watcher import (
    is_threat_watcher_active,
    is_anti_aggro_priority_active,
    get_threat_watcher_phase,
    get_current_watch_id,
)
from la2_bot.utils.antiaggro_diagnostics import log_event_throttled


# Внутреннее состояние режима
_full_hp_since_ts = None


def reset_state():
    global _full_hp_since_ts
    _full_hp_since_ts = None


def stuck_mode_tick(ser):
    """Выполняет один цикл проверки режима Stuck. Не блокирует надолго."""
    global _full_hp_since_ts

    # Stuck/RETURN_TO_TARGET не должен перебивать anti-aggro.
    if is_threat_watcher_active() or is_anti_aggro_priority_active():
        log_event_throttled(
            "stuck_paused_antiaggro", 1.0,
            "STUCK_PAUSED_BY_ANTIAGGRO", level="debug",
            phase=get_threat_watcher_phase(), watch_id=get_current_watch_id(),
        )
        _full_hp_since_ts = None
        return

    # Нужны координаты цели и пикселя полного HP
    if not all([coordinate_utils.TARGET_HP_1_POINT, coordinate_utils.TARGET_HP_FULL_POINT]):
        _full_hp_since_ts = None
        return

    now = time.time()

    # Есть ли цель в таргете
    target_alive = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))
    if not target_alive:
        _full_hp_since_ts = None
        return

    # Полный HP цели?
    is_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))
    if is_full_hp:
        if _full_hp_since_ts is None:
            _full_hp_since_ts = now

        # Превысили таймаут — выполняем последовательность
        if now - _full_hp_since_ts > config.STUCK_TARGET_TIMEOUT:
            print(
                f"[StuckMode] Цель полное HP > {config.STUCK_TARGET_TIMEOUT}s. "
                "Возвращаюсь к сохраненному таргету..."
            )
            send_command(ser, 'RETURN_TO_TARGET')
            _full_hp_since_ts = None
    else:
        # Атака идёт — сбрасываем таймер
        _full_hp_since_ts = None
