# la2_bot/actions/vkatak.py
"""Отдельная логика режима "ВКатак":
- Проверяем цвет пикселя CHAR_MP_POINT.
- Если цвет соответствует CHAR_MP_COLOR (с порогом COLOR_THRESHOLD), жмём 8 (MP_SKILL), иначе 1 (SKILL1_SPOIL).
- Вызывается тиком из основного цикла с внешним интервалом.
"""
import time
from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match
from la2_bot.utils import coordinate_utils
from la2_bot.utils.target_utils import is_target_selected
from la2_bot.config import config


def vkatak_tick(ser):
    """Один тик режима ВКатак. Не хранит внутреннее состояние.
    Возвращает True, если было отправлено какое-либо действие (1 или 8).
    """
    if not coordinate_utils.CHAR_MP_POINT:
        return False

    if not is_target_selected():
        print("[vkatak] TARGET_SELECTED пиксель не совпал. Действие пропущено.")
        return False

    mp_color = get_pixel_color(*coordinate_utils.CHAR_MP_POINT)
    has_enough_mp = is_color_match(mp_color, config.CHAR_MP_COLOR, getattr(config, 'COLOR_THRESHOLD', 10))

    if has_enough_mp:
        send_command(ser, 'MP_SKILL')  # 8
    else:
        send_command(ser, 'ATTACK')  # 7
    return True
