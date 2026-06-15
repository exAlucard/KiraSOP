# la2_bot/actions/consumables.py
"""Модуль с логикой использования расходников (HP/MP)."""
import time
from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.utils.target_utils import is_target_selected, is_target_hp_damaged

def use_hp_potion_if_needed(ser, last_potion_time):
    if not coordinate_utils.CHAR_HP_POINT:
        return last_potion_time
    
    color = get_pixel_color(*coordinate_utils.CHAR_HP_POINT)

    if not is_color_match(color, config.CHAR_HP_COLOR) and time.time() - last_potion_time >= config.POTION_INTERVAL:
        send_command(ser, 'HP_POTION')
        print(f"Пью банку ХП..")
        return time.time()
    return last_potion_time

def use_mp_skill_if_needed(ser, last_mp_skill_time):
    from la2_bot.detection.spoil_manager import is_first_spoil_success

    # Проверяем, что все необходимые координаты инициализированы
    if not all([coordinate_utils.CHAR_MP_POINT, 
                coordinate_utils.TARGET_HP_1_POINT, 
                coordinate_utils.TARGET_HP_DAMAGED_POINT]):
        return last_mp_skill_time

    mp_color = get_pixel_color(*coordinate_utils.CHAR_MP_POINT)
    has_enough_mp = is_color_match(mp_color, config.CHAR_MP_COLOR)

    first_spoil_condition = is_first_spoil_success()
    interval_condition = time.time() - last_mp_skill_time >= config.MP_SKILL_INTERVAL

    target_is_alive = is_target_color(
        get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT)
    )
    target_hp_is_damaged = is_target_hp_damaged()
    target_hp_condition = target_is_alive and target_hp_is_damaged

    if target_hp_condition and not is_target_selected():
        target_hp_condition = False

    if has_enough_mp and first_spoil_condition and interval_condition and target_hp_condition:
        send_command(ser, 'MP_SKILL')
        print("[mp_skill] Скилл использован.")
        return time.time()
    return last_mp_skill_time
