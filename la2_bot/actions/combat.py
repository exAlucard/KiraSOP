"""Модуль с боевыми действиями.

v10: обычная периодическая атака не перебивает стартовый приоритет спойла.
"""

import time
import random

from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.core.comm import send_command
from la2_bot.ui.bot_menu import is_flag_enabled
from la2_bot.utils.target_utils import is_target_selected
from la2_bot.detection.spoil_manager import is_spoil_priority_pending


def periodic_attack_if_needed(ser, last_attack_time):
    hp1_red = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))

    poke_enabled = is_flag_enabled('poke')
    # При включенном режиме "Подпинывание" игнорируем проверку полного ХП цели.
    full_hp_red = False if poke_enabled else is_target_color(
        get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT)
    )

    if not poke_enabled and hp1_red and not is_target_selected():
        hp1_red = False

    # Новая цель сначала должна получить spoil. Это закрывает ситуацию, когда
    # цель уже начала терять HP от других источников и periodic ATTACK успевает
    # включить обычную атаку раньше подтвержденного спойла.
    if hp1_red and is_spoil_priority_pending():
        return last_attack_time

    current_interval = random.uniform(config.ATTACK_INTERVAL_MIN, config.ATTACK_INTERVAL_MAX)

    if (poke_enabled or hp1_red) and not full_hp_red and time.time() - last_attack_time >= current_interval:
        time.sleep(random.uniform(config.LOOT_MIN, config.LOOT_MAX))
        print(f"Сработала Атака раз в {round(current_interval, 2)} сек на всякий случай..")
        send_command(ser, 'ATTACK')
        return time.time()

    return last_attack_time
