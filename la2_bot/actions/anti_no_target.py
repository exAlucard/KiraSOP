# la2_bot/actions/anti_no_target.py
"""Режим "Anti No Target".
Логика:
- Проверяет пиксель HP цели: TARGET_HP_1_POINT.
- Если пиксель не виден (нет таргета/HP моба) непрерывно дольше NO_TARGET_TIMEOUT секунд:
  - Нажимает клавишу "-" (HEAL_KEY) через Arduino.
  - Перезапускает таймер, чтобы следующее нажатие было не раньше чем через 13с.
"""
import time
from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils

NO_TARGET_TIMEOUT = 13.0  # секунд без таргета перед нажатием "-"

# Внутреннее состояние
_no_target_since_ts = None


def reset_state():
    global _no_target_since_ts
    _no_target_since_ts = None


def anti_no_target_tick(ser):
    """Выполняет один цикл проверки. Не блокирует надолго."""
    global _no_target_since_ts

    if not coordinate_utils.TARGET_HP_1_POINT:
        _no_target_since_ts = None
        return

    now = time.time()

    has_target = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))

    if has_target:
        # Цель есть — сбрасываем таймер
        _no_target_since_ts = None
        return

    # Цели нет — считаем время
    if _no_target_since_ts is None:
        _no_target_since_ts = now

    if now - _no_target_since_ts > NO_TARGET_TIMEOUT:
        print(f"[AntiNoTarget] Нет таргета > {NO_TARGET_TIMEOUT}s. Нажимаю '-'...")
        send_command(ser, 'HEAL_KEY')
        # Перезапускаем отсчёт
        _no_target_since_ts = now
