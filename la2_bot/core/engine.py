# la2_bot/core/engine.py
import time
from la2_bot.core.state import (
    pause_event,
    mob_highlight_thread,
    mob_highlight_stop_event,
    last_focus_state,
    set_last_focus_state,
    set_last_focus_check,
    get_last_focus_check
)
from la2_bot.core.comm import init_serial
from la2_bot.actions.consumables import use_hp_potion_if_needed, use_mp_skill_if_needed
from la2_bot.actions.targeting import main_target_loot_and_sweep
from la2_bot.actions.combat import periodic_attack_if_needed
from la2_bot.actions.return_to_target import manage_return_to_target_process, stop_return_to_target_process
from la2_bot.detection.spoil_manager import manage_spoil_process, stop_spoil_process
from la2_bot.ui.bot_menu import is_flag_enabled
from la2_bot.utils.window_utils import is_game_active, get_game_window_geometry
from la2_bot.config import config
from la2_bot.utils.coordinate_utils import initialize_coordinates
from la2_bot.detection import green_pixel_utils
from la2_bot.utils.threat_watcher import is_threat_watcher_active
from la2_bot.core.comm import send_command
from la2_bot.core.debug_state import set_next_target_cooldown
from la2_bot.actions.buff_manager import manage_buff_process, stop_buff_process
from la2_bot.actions.vkatak import vkatak_tick
from la2_bot.actions.stuck_mode import stuck_mode_tick, reset_state as stuck_mode_reset
from la2_bot.actions.anti_no_target import anti_no_target_tick, reset_state as anti_no_target_reset
from la2_bot.features import always_assist
import la2_bot.config.hud_settings


def bot_loop(pause_event):
    ser = init_serial()
    try:
        always_assist.set_serial(ser)
    except Exception:
        pass
    processes_started = False
    state = {
        'was_hp1_red': True,
        'next_next_target': time.time(),
        'last_target_index': 0,
    }
    last_potion = last_mp_skill = last_attack = 0
    set_last_focus_check(0)
    next_altheal_time = 0.0
    next_heal_time = 0.0
    next_altds_time = 0.0
    next_flip_time = 0.0
    next_vkatak_time = 0.0
    next_stuck_time = 0.0
    next_anti_no_target_time = 0.0
    next_settings_refresh_time = 0.0
    heal_interval_seconds = 15.0

    try:
        while True:
            if not pause_event.is_set():
                if processes_started:
                    print("[main] Бот на паузе. Останавливаю фоновые процессы...")
                    stop_spoil_process()
                    stop_return_to_target_process()
                    green_pixel_utils.stop_green_pixel_monitoring()
                    processes_started = False
                time.sleep(0.5)
                continue

            current_client_name = config.GAME_EXE_NAME
            if not is_game_active(current_client_name):
                time.sleep(0.5)
                continue

            window_geometry = get_game_window_geometry(current_client_name)
            if window_geometry:
                initialize_coordinates(window_geometry)
                if not processes_started:
                    print("[main] Инициализация координат завершена, запускаю фоновые процессы.")
                    manage_spoil_process(ser, pause_event)
                    manage_return_to_target_process(ser, pause_event)
                    green_pixel_utils.start_green_pixel_monitoring()
                    processes_started = True
                    print(f"[main] Фоновые процессы запущены для клиента {current_client_name}")
            else:
                if processes_started:
                    stop_spoil_process()
                    stop_return_to_target_process()
                    green_pixel_utils.stop_green_pixel_monitoring()
                    processes_started = False
                time.sleep(1)
                continue

            # --- Основная логика бота ---
            now = time.time()

            if now >= next_settings_refresh_time:
                try:
                    from la2_bot.config.config_manager import get_client_name
                    settings = la2_bot.config.hud_settings.load_hud_settings(get_client_name())
                    val = settings.get("heal_interval_seconds", 15.0)
                    val = float(val)
                    if val > 0:
                        heal_interval_seconds = val
                    loot_count = settings.get("loot_repeat_count", getattr(config, 'LOOT_REPEAT_COUNT', 3))
                    loot_count = int(float(loot_count))
                    if loot_count >= 0:
                        config.LOOT_REPEAT_COUNT = loot_count
                    buff_interval = settings.get("buff_cycle_interval", getattr(config, 'BUFF_CYCLE_INTERVAL', 60.0))
                    buff_interval = float(buff_interval)
                    if buff_interval > 0:
                        config.BUFF_CYCLE_INTERVAL = buff_interval
                except Exception:
                    pass
                next_settings_refresh_time = now + 2.0

            if is_flag_enabled('potion'):
                last_potion = use_hp_potion_if_needed(ser, last_potion)
            if is_flag_enabled('mp_skill'):
                last_mp_skill = use_mp_skill_if_needed(ser, last_mp_skill)

            # Основная логика выполняется независимо от анти-агра
            state = main_target_loot_and_sweep(ser, state)
            
            if is_flag_enabled('next_target'):
                last_attack = periodic_attack_if_needed(ser, last_attack)

            # Arduino-based Altheal: Alt+Tab -> 9 -> Alt+Tab, every ~15s when enabled
            if is_flag_enabled('altheal'):
                now = time.time()
                if now >= next_altheal_time:
                    set_next_target_cooldown(1.5)
                    send_command(ser, 'ALT_TAB')
                    time.sleep(0.5)
                    send_command(ser, 'HP_POTION')  # key '9'
                    time.sleep(0.1)
                    send_command(ser, 'ALT_TAB')
                    next_altheal_time = now + 15.0

            # Flip mode: every 300s press F8
            if is_flag_enabled('flip'):
                now = time.time()
                if now >= next_flip_time:
                    send_command(ser, 'F8')
                    next_flip_time = now + 300.0

            # Arduino-based Heal: every 15s press key '9' five times with 0.2s interval
            if is_flag_enabled('heal'):
                if now >= next_heal_time:
                    heal_cmd_key = 'HEAL_KEY' if isinstance(getattr(config, 'CMD', None), dict) and 'HEAL_KEY' in config.CMD else 'HP_POTION'
                    for _ in range(5):
                        send_command(ser, heal_cmd_key)
                        time.sleep(0.2)
                    next_heal_time = now + heal_interval_seconds

            # VKatak: independent module, periodic tick. Presses 8 if MP color matches else 1.
            if is_flag_enabled('vkatak'):
                now = time.time()
                if now >= next_vkatak_time:
                    vkatak_tick(ser)
                    next_vkatak_time = now + getattr(config, 'SPOIL_ATTEMPT_INTERVAL_MIN', 1.0)

            # Stuck mode: independent module. When enabled, checks full HP timeout and triggers ESC + RETURN_TO_TARGET.
            if is_flag_enabled('stuck'):
                now = time.time()
                if now >= next_stuck_time:
                    stuck_mode_tick(ser)
                    next_stuck_time = now + 0.2
            else:
                stuck_mode_reset()

            # Anti-no-target mode: если нет таргета дольше 13с — нажимает "-".
            if is_flag_enabled('anti_no_target'):
                now = time.time()
                if now >= next_anti_no_target_time:
                    anti_no_target_tick(ser)
                    next_anti_no_target_time = now + 0.2
            else:
                anti_no_target_reset()

            # Arduino-based AltDS: every 310s Alt+Tab -> wait 0.5s -> ATTACK(7) -> Alt+Tab, block next target for 1.5s
            if is_flag_enabled('altds'):
                now = time.time()
                if now >= next_altds_time:
                    set_next_target_cooldown(1.5)
                    send_command(ser, 'ALT_TAB')
                    time.sleep(0.5)
                    send_command(ser, 'ATTACK')  # key '7'
                    time.sleep(0.1)
                    send_command(ser, 'ALT_TAB')
                    next_altds_time = now + 310.0

            # Buff manager (F1..F10 sequence)
            if is_flag_enabled('buffs'):
                # Expose current desire to the worker via config
                try:
                    config.FLAG_BUFF_ENABLED = True
                except Exception:
                    pass
                manage_buff_process(pause_event, ser)
            else:
                try:
                    config.FLAG_BUFF_ENABLED = False
                except Exception:
                    pass
                stop_buff_process()

            time.sleep(config.CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("Прервано пользователем")
    finally:
        print("[main] Завершение работы, останавливаю все процессы...")
        stop_spoil_process()
        stop_return_to_target_process()
        green_pixel_utils.stop_green_pixel_monitoring()
        print("[main] Основной цикл завершен.")
