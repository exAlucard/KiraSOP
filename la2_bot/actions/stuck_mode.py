# la2_bot/actions/stuck_mode.py
"""Новый независимый режим "Stuck" (не трогаем существующий код).
Логика:
- Проверяет пиксель полного HP: TARGET_HP_FULL_POINT.
- Если он красный непрерывно дольше STUCK_TARGET_TIMEOUT:
  - Логирует, жмёт ESC (сброс цели), ждёт 0.5s, жмёт 0 (RETURN_TO_TARGET).
  - Сбрасывает внутренний таймер и флаги.
"""
import time
from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config

# Внутреннее состояние режима
_full_hp_since_ts = None


def reset_state():
    global _full_hp_since_ts
    _full_hp_since_ts = None


def stuck_mode_tick(ser):
    """Выполняет один цикл проверки режима Stuck. Не блокирует надолго.
    ser: открытый serial для Arduino команд.
    """
    global _full_hp_since_ts

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
            print(f"[StuckMode] Цель полное HP > {config.STUCK_TARGET_TIMEOUT}s. Сбрасываю и возвращаюсь к таргету...")
            send_command(ser, 'RETURN_TO_TARGET')
            _full_hp_since_ts = None
    else:
        # Атака идёт — сбрасываем таймер
        _full_hp_since_ts = None
