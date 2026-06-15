"""Модуль с логикой управления целями, лутом и свипом."""
import time
import random
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.core.comm import send_command
from la2_bot.ui.bot_menu import is_flag_enabled, get_target_count_mode
from la2_bot.utils.threat_watcher import schedule_threat_watch
from la2_bot.core.debug_state import is_next_target_on_cooldown, set_next_target_cooldown
from la2_bot.utils.target_utils import is_target_selected, is_target_hp_damaged

def find_new_target(ser, state):
    """Централизованная функция для поиска новой цели с учетом кулдауна."""
    if is_next_target_on_cooldown():
        return

    if is_flag_enabled('next_target'):
        target_count_mode = get_target_count_mode()
        
        if target_count_mode == 2:
            if state.get('last_target_index', 0) == 0:
                send_command(ser, 'NEXT_TARGET')
                state['last_target_index'] = 1
            else:
                send_command(ser, 'NEXT_TARGET_2')
                state['last_target_index'] = 0
        else:
            send_command(ser, 'NEXT_TARGET')
        
        # Устанавливаем кулдаун, чтобы избежать повторных вызовов
        set_next_target_cooldown(config.TARGET_SWITCH_DELAY)
        try:
            state['last_target_switch_ts'] = time.time()
        except Exception:
            pass

def has_valid_current_target():
    if not coordinate_utils.TARGET_HP_1_POINT:
        return False

    target_alive = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))
    if not target_alive:
        return False

    if not is_target_selected():
        return False

    if is_flag_enabled('skip_damaged_target'):
        is_target_full_hp = False
        if getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None):
            is_target_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))
        if not is_target_full_hp and is_target_hp_damaged():
            return False

    return True

def main_target_loot_and_sweep(ser, state):
    """
    Обрабатывает весь цикл работы с целью: от выбора до лута.
    """
    if not coordinate_utils.TARGET_HP_1_POINT:
        return state

    now = time.time()
    is_target_alive_raw = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT))

    # После переключения цели даём интерфейсу/пикселям немного времени обновиться,
    # чтобы не перескакивать через подходящую цель из-за "переходного" состояния.
    last_switch_ts = state.get('last_target_switch_ts')
    in_switch_grace = last_switch_ts is not None and (now - last_switch_ts) < max(0.4, min(1.0, config.TARGET_SWITCH_DELAY))

    # Дополнительное подтверждение, что таргет реально выбран (например, по UI-индикатору)
    is_selected_ok = (not is_target_alive_raw) or is_target_selected()

    # Условие: начинать действовать только если цель НЕ повреждена
    is_target_damaged = False
    if is_flag_enabled('skip_damaged_target'):
        if is_target_alive_raw:
            # Если цель полное HP — считаем, что она не повреждена
            is_target_full_hp = False
            if getattr(coordinate_utils, 'TARGET_HP_FULL_POINT', None):
                is_target_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))

            if not is_target_full_hp:
                is_target_damaged = is_target_hp_damaged()

    is_target_alive = is_target_alive_raw and is_selected_ok and (not is_target_damaged)

    # Если цель есть, но она не подходит под условия старта (не выбран таргет/цель уже повреждена) — ищем другую
    if is_target_alive_raw and not is_target_alive:
        invalid_since = state.get('invalid_target_since')
        if invalid_since is None:
            state['invalid_target_since'] = now
            invalid_since = now

        # Переключаем цель только если она остаётся неподходящей достаточно долго,
        # иначе можно перескочить через подходящую цель из-за задержек UI.
        if (not in_switch_grace) and (now - invalid_since >= 0.1):
            find_new_target(ser, state)
            state['invalid_target_since'] = None
        state['was_hp1_red'] = is_target_alive_raw
        return state

    # Цель подходит — сбрасываем таймер "неподходящей цели"
    state['invalid_target_since'] = None

    # Проверка на застрявшую цель
    if is_target_alive and is_flag_enabled('stuck_target'):
        is_target_full_hp = is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_FULL_POINT))
        
        if is_target_full_hp:
            if state.get('target_full_hp_since') is None:
                state['target_full_hp_since'] = now
            
            if now - state['target_full_hp_since'] > config.STUCK_TARGET_TIMEOUT:
                print(f"[Targeting] Цель застряла на {config.STUCK_TARGET_TIMEOUT} сек. Сбрасываю и ищу новую...")
                send_command(ser, 'ESC') # Сброс цели
                time.sleep(0.5) # Пауза после сброса
                find_new_target(ser, state) # Ищем новую
                state['target_full_hp_since'] = None
                state['was_hp1_red'] = False # Сбрасываем флаг, так как цели уже нет
                return state
        else:
            state['target_full_hp_since'] = None # Атака идет, сбрасываем таймер
    else:
        state['target_full_hp_since'] = None # Цели нет или опция выключена, сбрасываем

    # Условие смерти цели
    if state.get('was_hp1_red') and not is_target_alive_raw:
        print("[Targeting] Цель умерла. Запускаю цикл лута и свипа.")
        state['was_hp1_red'] = False

        time.sleep(random.uniform(config.LOOT_MIN, config.LOOT_MAX))
        send_command(ser, 'SWEEP')
        time.sleep(random.uniform(config.SWEEP_TO_LOOT_MIN, config.SWEEP_TO_LOOT_MAX))
        send_command(ser, 'SWEEP')
        time.sleep(random.uniform(config.SWEEP_TO_LOOT_MIN, config.SWEEP_TO_LOOT_MAX))
        
        for _ in range(config.LOOT_REPEAT_COUNT):
            send_command(ser, 'LOOT')
            time.sleep(random.uniform(config.LOOT_MIN, config.LOOT_MAX))
        for _ in range(10):
            send_command(ser, 'LOOT')
            time.sleep(random.uniform(config.LOOT_MIN, config.LOOT_MAX))

        if is_flag_enabled('anti_agr'):
            schedule_threat_watch(ser)
        
        if has_valid_current_target():
            print("[Targeting] После смерти уже есть подходящий таргет. Новую цель не ищу.")
            state['was_hp1_red'] = True
            return state
        else:
            find_new_target(ser, state)

    # Если цели нет и не было, ищем новую
    elif not is_target_alive_raw and not state.get('was_hp1_red'):
        find_new_target(ser, state)

    state['was_hp1_red'] = is_target_alive_raw
    return state
