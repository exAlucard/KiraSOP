# la2_bot/actions/mob_interaction.py
import time
import random
import pyautogui
from la2_bot.utils import coordinate_utils
from la2_bot.config import config
import threading
from la2_bot.core.state import mob_highlight_thread, mob_highlight_stop_event
from la2_bot.utils.mob_name_highlighter import find_and_highlight_mobs

pyautogui.FAILSAFE = False

def perform_double_click(ser):

    click_point = coordinate_utils.DOUBLE_CLICK_POINT
    if not click_point or len(click_point) != 2:
        print(f"[double_click] Ошибка: Неверный формат координат DOUBLE_CLICK_POINT: {click_point}")
        return

    x, y = click_point
    duration = random.uniform(
        config.DOUBLE_CLICK_MOVE_DURATION_MIN,
        config.DOUBLE_CLICK_MOVE_DURATION_MAX
    )
    pause_between_clicks = random.uniform(
        config.DOUBLE_CLICK_PAUSE_MIN,
        config.DOUBLE_CLICK_PAUSE_MAX
    )

    print(f"[double_click] Перемещаю мышь в точку ({x}, {y}) за {duration:.2f} секунд.")
    try:
        pyautogui.moveTo(x, y, duration=duration)
        print(f"[double_click] Мышь перемещена в точку ({x}, {y}).")
    except Exception as e:
        print(f"[double_click] Ошибка при перемещении мыши: {e}")
        return

    time.sleep(0.1)

    try:
        pyautogui.click()
        print("[double_click] Первый клик выполнен.")
    except Exception as e:
        print(f"[double_click] Ошибка при первом клике: {e}")
        return

    if pause_between_clicks > 0:
        print(f"[double_click] Пауза на {pause_between_clicks:.2f} секунд.")
        time.sleep(pause_between_clicks)

    try:
        pyautogui.click()
        print("[double_click] Второй клик выполнен.")
    except Exception as e:
        print(f"[double_click] Ошибка при втором клике: {e}")

def start_mob_highlight_worker():
    global mob_highlight_thread
    if not mob_highlight_thread or not mob_highlight_thread.is_alive():
        mob_highlight_stop_event.clear()
        mob_highlight_thread = threading.Thread(
            target=mob_highlight_worker,
            args=(mob_highlight_stop_event,),
            daemon=True
        )
        mob_highlight_thread.start()
        print("[main] Поток подсветки мобов запущен.")


def stop_mob_highlight_worker():
    global mob_highlight_thread
    if mob_highlight_thread and mob_highlight_thread.is_alive():
        mob_highlight_stop_event.set()


def mob_highlight_worker(stop_event):
    print("[mob_highlight] Рабочий поток подсветки запущен.")
    while not stop_event.is_set():
        mob_highlight_loop_iteration()
        if stop_event.wait(timeout=1.0):
            break
    print("[mob_highlight] Рабочий поток подсветки остановлен.")


def mob_highlight_loop_iteration():
    find_and_highlight_mobs()