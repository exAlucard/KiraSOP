# la2_bot/actions/vkatak.py
"""Отдельная логика режима "ВКатак".

FIX:
- MP_SKILL работает как раньше.
- ATTACK запрещён, пока spoil_manager держит стартовый приоритет SPOIL.
- Дополнительно есть короткая защита сразу после NEXT_TARGET/NEXT_TARGET_2,
  закрывающая гонку потоков до того, как spoil_worker успеет увидеть новую цель.
"""

import time

from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match
from la2_bot.utils import coordinate_utils
from la2_bot.utils.target_utils import is_target_selected
from la2_bot.config import config
from la2_bot.detection.spoil_manager import is_spoil_priority_pending


def _target_switch_guard_active(last_target_switch_ts):
    """Короткий guard после NEXT_TARGET для закрытия межпоточной гонки."""
    try:
        switch_ts = float(last_target_switch_ts or 0.0)
    except (TypeError, ValueError):
        return False

    if switch_ts <= 0.0:
        return False

    try:
        guard_seconds = float(
            getattr(config, "VKATAK_TARGET_SWITCH_ATTACK_GUARD", 0.35)
        )
    except (TypeError, ValueError):
        guard_seconds = 0.35

    guard_seconds = max(0.0, guard_seconds)
    return (time.time() - switch_ts) < guard_seconds


def vkatak_tick(ser, last_target_switch_ts=0.0):
    """Один тик режима ВКатак.

    Возвращает True, только если реально была отправлена команда.

    Важно:
    - MP_SKILL не меняем.
    - ATTACK не отправляем во время spoil-priority.
    - ATTACK не отправляем сразу после переключения цели.
    """
    if not coordinate_utils.CHAR_MP_POINT:
        return False

    if not is_target_selected():
        print("[vkatak] TARGET_SELECTED пиксель не совпал. Действие пропущено.")
        return False

    mp_color = get_pixel_color(*coordinate_utils.CHAR_MP_POINT)
    has_enough_mp = is_color_match(
        mp_color,
        config.CHAR_MP_COLOR,
        getattr(config, "COLOR_THRESHOLD", 10),
    )

    if has_enough_mp:
        send_command(ser, "MP_SKILL")  # 8
        return True

    # Главный FIX: новая цель сначала проходит стартовый SPOIL.
    if is_spoil_priority_pending():
        print("[vkatak] ATTACK пропущен: новая цель ожидает первичный SPOIL.")
        return False

    # Страховка от узкой гонки между NEXT_TARGET и первым тиком spoil_worker.
    if _target_switch_guard_active(last_target_switch_ts):
        print("[vkatak] ATTACK пропущен: только что выполнен NEXT_TARGET.")
        return False

    send_command(ser, "ATTACK")  # 7
    return True
