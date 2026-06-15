# la2_bot/actions/buff_manager.py
import threading
import time
from typing import List

from la2_bot.config import config
from la2_bot.core.state import pause_event as global_pause_event
from la2_bot.core.comm import send_command


_buff_thread = None
_buff_stop_event = threading.Event()


_ARDUINO_KEYS = {'F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12'}


def _tap_key_arduino(ser, key: str, press_ms: float):
    # В прошивке длительность нажатия фиксирована; press_ms используется как пауза после отправки
    send_command(ser, key)
    if press_ms > 0:
        time.sleep(press_ms / 1000.0)


def _get_sequence() -> List[str]:
    try:
        seq = list(getattr(config, 'BUFF_SEQUENCE', []))
        # фильтруем неизвестные
        return [k for k in seq if k in _ARDUINO_KEYS]
    except Exception:
        return []


def manage_buff_process(pause_event=None, ser=None):
    global _buff_thread
    if _buff_thread and _buff_thread.is_alive():
        return

    _buff_stop_event.clear()

    def _worker():
        last_cycle_ts = 0.0
        while not _buff_stop_event.is_set():
            # ожидание play
            if not (pause_event or global_pause_event).is_set():
                time.sleep(0.2)
                continue

            # проверка флага
            if not getattr(config, 'FLAG_BUFF_ENABLED', False):
                time.sleep(0.5)
                continue

            # общий интервал между циклами
            now = time.time()
            cycle_interval = float(getattr(config, 'BUFF_CYCLE_INTERVAL', 60.0))
            if now - last_cycle_ts < cycle_interval:
                time.sleep(0.2)
                continue

            seq = _get_sequence()
            if not seq:
                time.sleep(0.5)
                continue

            # Параметры нажатий согласно спецификации пользователя
            press_ms = float(getattr(config, 'BUFF_KEY_PRESS_MS', 50.0))  # пауза после отправки, фактический "hold" фиксирован прошивкой
            per_key_press_count = int(getattr(config, 'BUFF_PER_KEY_PRESS_COUNT', 5))
            intra_press_delay = float(getattr(config, 'BUFF_INTRA_PRESS_DELAY', 0.2))  # между повторами одной клавиши
            between_keys_delay = float(getattr(config, 'BUFF_BETWEEN_KEYS_DELAY', 6.0))  # между разными клавишами

            import random
            try:
                for key in seq:
                    if _buff_stop_event.is_set():
                        break
                    if not (pause_event or global_pause_event).is_set():
                        break
                    if ser is None:
                        raise RuntimeError("Arduino Serial не инициализирован для buff_manager")
                    # Нажимаем одну и ту же клавишу per_key_press_count раз с задержкой intra_press_delay
                    repeats = per_key_press_count if per_key_press_count > 0 else 1
                    for _ in range(repeats):
                        if _buff_stop_event.is_set() or not (pause_event or global_pause_event).is_set():
                            break
                        _tap_key_arduino(ser, key, press_ms)
                        if intra_press_delay > 0:
                            time.sleep(intra_press_delay)
                    # Пауза между разными клавишами
                    if between_keys_delay > 0:
                        time.sleep(between_keys_delay)
                last_cycle_ts = time.time()
            except Exception as e:
                print(f"[buff] Ошибка в цикле бафов: {e}")
                time.sleep(1.0)

    _buff_thread = threading.Thread(target=_worker, daemon=True)
    _buff_thread.start()
    print("[buff] Поток бафов запущен.")


def stop_buff_process():
    global _buff_thread
    if _buff_thread and _buff_thread.is_alive():
        _buff_stop_event.set()
        _buff_thread.join(timeout=1.0)
        _buff_thread = None
        print("[buff] Поток бафов остановлен.")
