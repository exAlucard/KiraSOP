# la2_bot/detection/spoil_manager.py
"""Модуль для управления процессом спойла цели."""
import threading
import time
import random
from la2_bot.core.comm import send_command
from la2_bot.config import config
from la2_bot.utils.pixel_utils import get_pixel_color, is_color_match, is_target_color
from la2_bot.detection import green_pixel_utils
from la2_bot.utils import coordinate_utils
from la2_bot.utils.target_utils import send_target_command
from la2_bot.utils.target_utils import is_target_selected

spoil_process_thread = None
spoil_stop_event = threading.Event()

spoiled_event = threading.Event()
spoiled_event.clear()
first_spoil_success_event = threading.Event()
first_spoil_success_event.clear()


def manage_spoil_process(ser, pause_event):
    global spoil_process_thread
    if spoil_process_thread and spoil_process_thread.is_alive():
        return

    spoil_stop_event.clear()

    def spoil_worker_logic():
        current_target_id = None
        first_spoil_successful = False

        while not spoil_stop_event.is_set():
            if not pause_event.is_set():
                time.sleep(0.5)
                continue

            # Проверка, инициализированы ли координаты
            if not all([coordinate_utils.TARGET_HP_1_POINT, coordinate_utils.SKILL_RESET_POINT]):
                print("[spoil_process] Ожидание инициализации координат...")
                time.sleep(1)
                continue

            hp1_color = get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT)
            hp1_red = is_target_color(hp1_color)

            if hp1_red and not is_target_selected():
                hp1_red = False

            if not hp1_red:
                if current_target_id is not None:
                    # print("[spoil_process] Цель мертва, сброс состояния спойла.")
                    green_pixel_utils.clear_green_pixel_detected()
                    current_target_id = None
                    first_spoil_successful = False
                    spoiled_event.clear()
                    first_spoil_success_event.clear()
                time.sleep(0.1)
                continue

            if current_target_id is None:
                current_target_id = time.time()
                first_spoil_successful = False
                spoiled_event.clear()
                first_spoil_success_event.clear()
                green_pixel_utils.clear_green_pixel_detected()
                # print(f"[spoil_process] Новая цель обнаружена, ID: {current_target_id:.2f}")

            green_found = green_pixel_utils.is_green_pixel_detected()
            if green_found:
                # print("[spoil_process] Спойл успешен (найден зеленый пиксель).")
                green_pixel_utils.clear_green_pixel_detected()
                spoiled_event.set()
                if not first_spoil_successful:
                    first_spoil_successful = True
                    first_spoil_success_event.set()
                    # print("[spoil_process] Первый спойл ЗАЧТЕН как успешный.")

            if not first_spoil_successful:
                skill_reset_color = get_pixel_color(*coordinate_utils.SKILL_RESET_POINT)
                skill_ready = not is_color_match(skill_reset_color, config.SKILL_RESET_COLOR)
                if skill_ready:
                    send_command(ser, 'SKILL1_SPOIL')
                    time.sleep(1.0)
                    send_command(ser, 'ATTACK')
            
            time.sleep(random.uniform(config.SPOIL_ATTEMPT_INTERVAL_MIN, config.SPOIL_ATTEMPT_INTERVAL_MAX))

    spoil_process_thread = threading.Thread(target=spoil_worker_logic, daemon=True)
    spoil_process_thread.start()
    print("[spoil_process] Поток спойла запущен.")

def stop_spoil_process():
    global spoil_process_thread
    if spoil_process_thread and spoil_process_thread.is_alive():
        print("[spoil_process] Получен сигнал остановки.")
        spoil_stop_event.set()
        spoil_process_thread.join(timeout=1.0) # Ожидаем завершения потока
        spoil_process_thread = None

def is_any_spoil_success():
    return spoiled_event.is_set()

def clear_any_spoil_success():
    spoiled_event.clear()

def is_first_spoil_success():
    return first_spoil_success_event.is_set()

def clear_first_spoil_success():
    first_spoil_success_event.clear()

is_spoil_success = is_any_spoil_success
clear_spoil_success = clear_any_spoil_success
