# la2_bot/actions/return_to_target.py
"""Модуль управления возвратом к цели."""
import time
import random
import threading
from la2_bot.core.comm import send_command
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
from la2_bot.ui.bot_menu import is_flag_enabled
from la2_bot.utils.target_utils import is_target_selected

return_to_target_process_thread = None
return_to_target_stop_event = threading.Event()

def manage_return_to_target_process(ser, pause_event):
    global return_to_target_process_thread, return_to_target_stop_event
    if return_to_target_process_thread is not None and return_to_target_process_thread.is_alive():
        return

    return_to_target_stop_event.clear()

    def return_to_target_logic():
        print("[return_to_target] Поток возврата к цели запущен.")
        hp1_point = coordinate_utils.TARGET_HP_1_POINT
        target_color = config.TARGET_COLOR
        check_interval = config.HP1_MONSTER_CHECK_INTERVAL
        wait_start_time = None
        wait_time = 0.0

        try:
            while not return_to_target_stop_event.is_set() and pause_event.is_set():
                if not is_flag_enabled('return_to_target'):
                    return_to_target_stop_event.wait(timeout=check_interval)
                    continue

                hp1_color = get_pixel_color(*hp1_point)
                is_hp1_red = is_color_match(hp1_color, target_color)

                if is_hp1_red and not is_target_selected():
                    is_hp1_red = False

                if is_hp1_red:
                    if wait_start_time is not None:
                        print("[return_to_target] Пиксель 1 ХП снова красный. Сброс таймера.")
                    wait_start_time = None
                    if return_to_target_stop_event.wait(timeout=check_interval):
                        break
                    continue

                if wait_start_time is None:
                    wait_time = random.uniform(config.HP1_MONSTER_WAIT_TIME_MIN, config.HP1_MONSTER_WAIT_TIME_MAX)
                    wait_start_time = time.time()
                    print(f"[return_to_target] Пиксель 1 ХП не красный. Начало ожидания {wait_time:.2f} секунд.")

                elapsed_time = time.time() - wait_start_time
                if elapsed_time >= wait_time:
                    print("[return_to_target] Время ожидания истекло. Выполняю возврат к цели (RETURN_TO_TARGET).")
                    send_command(ser, 'RETURN_TO_TARGET')
                    pause_time = random.uniform(config.RETURN_TO_TARGET_PAUSE_MIN, config.RETURN_TO_TARGET_PAUSE_MAX)
                    if return_to_target_stop_event.wait(timeout=pause_time):
                        break
                    if not pause_event.is_set():
                        continue
                    if is_target_selected():
                        send_command(ser, 'ATTACK')
                    wait_start_time = None
                    print("[return_to_target] Действия выполнены. Жду появления красного пикселя.")
                else:
                    remaining_time = wait_time - elapsed_time
                    sleep_time = min(remaining_time, check_interval)
                    if return_to_target_stop_event.wait(timeout=sleep_time):
                        break

            if return_to_target_stop_event.is_set():
                print("[return_to_target] Получен сигнал остановки.")
            elif not pause_event.is_set():
                print("[return_to_target] Пауза активна.")
        except Exception as e:
            print(f"[return_to_target] Ошибка в потоке возврата к цели: {e}")

    return_to_target_process_thread = threading.Thread(target=return_to_target_logic, daemon=True)
    return_to_target_process_thread.start()

def stop_return_to_target_process():
    global return_to_target_stop_event

    if return_to_target_stop_event and not return_to_target_stop_event.is_set():
        return_to_target_stop_event.set()