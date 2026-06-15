# la2_bot/utils/target_utils.py
"""Утилиты для отправки команд выбора цели."""

from la2_bot.core.comm import send_command
from la2_bot.ui.bot_menu import get_target_count_mode, is_flag_enabled
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match
from la2_bot.utils import coordinate_utils
from la2_bot.config import config

def send_target_command(ser):
    """
    Отправляет команду выбора цели в зависимости от настроек в меню.
    """
    if not is_flag_enabled('next_target'):
        print("[target] Выбор цели отключен в меню.")
        return

    count_mode = get_target_count_mode()
    if count_mode == 1:
        send_command(ser, 'NEXT_TARGET')
        print("[target] Отправлена команда NEXT_TARGET (режим 1 цели)")
    elif count_mode == 2:
        send_command(ser, 'NEXT_TARGET')
        print("[target] Отправлена команда NEXT_TARGET (1/2)")
        send_command(ser, 'NEXT_TARGET_2')
        print("[target] Отправлена команда NEXT_TARGET_2 (2/2)")
    else:
        print(f"[target] Неизвестный режим выбора количества целей: {count_mode}. Команда не отправлена.")


def is_target_selected():
    """Проверяет, что таргет действительно выбран по контрольному пикселю.

    Если координата/цвет не определены в конфиге, возвращает True (для совместимости).
    """
    if not is_flag_enabled('target_mob'):
        return True

    point1 = getattr(coordinate_utils, 'TARGET_SELECTED_POINT', None)
    color_expected1 = getattr(config, 'TARGET_MOB_COLOR', None)
    if not color_expected1:
        color_expected1 = getattr(config, 'TARGET_SELECTED_COLOR', None)

    point2 = getattr(coordinate_utils, 'TARGET_MOB_POINT2', None)
    color_expected2 = getattr(config, 'TARGET_MOB_COLOR2', None)

    checks = []
    if point1 and color_expected1:
        checks.append((point1, color_expected1))
    if point2 and color_expected2:
        checks.append((point2, color_expected2))
    if not checks:
        return True
    try:
        for point, color_expected in checks:
            current = get_pixel_color(point[0], point[1])
            if isinstance(color_expected, list):
                if any(is_color_match(current, c, getattr(config, 'COLOR_THRESHOLD', 10)) for c in color_expected):
                    return True
            else:
                if is_color_match(current, color_expected, getattr(config, 'COLOR_THRESHOLD', 10)):
                    return True
        return False
    except Exception:
        return False


def is_target_hp_damaged():
    """Проверяет, что пиксель "HP цели (Поврежден)" соответствует ожидаемому цвету.

    Возвращает False, если координата/цвет не определены.
    """
    point = getattr(coordinate_utils, 'TARGET_HP_DAMAGED_POINT', None)
    color_expected = getattr(config, 'TARGET_HP_DAMAGED_COLOR', None)
    if not point or not color_expected:
        return False
    try:
        current = get_pixel_color(point[0], point[1])
        return is_color_match(current, color_expected, getattr(config, 'COLOR_THRESHOLD', 10))
    except Exception:
        return False
