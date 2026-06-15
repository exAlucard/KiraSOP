# la2_bot/detection/green_pixel_utils.py
"""
Модуль для непрерывного отслеживания зеленого пикселя спойла в отдельном потоке.
(Переделан с использованием mss и механизмом перезапуска)
"""
import threading
import time
import numpy as np
import mss
from la2_bot.config import config
from la2_bot.utils import coordinate_utils

# --- Глобальные переменные ---
green_pixel_thread = None
green_pixel_detected_event = threading.Event()
green_pixel_detected_event.clear()
_green_pixel_stop_event = threading.Event()
_detection_counter = 0
_sct = None
_last_reset_time = 0


def _reset_mss():
    """
    Сбрасывает глобальный объект mss, создавая новый экземпляр.
    Вызывается при ошибках или по таймеру.
    """
    global _sct, _last_reset_time
    if _sct is not None:
        try:
            _sct.close()
        except:
            pass
    _sct = mss.mss()
    _last_reset_time = time.time()
    print(f"[green_pixel] Модуль mss перезапущен. Время: {time.strftime('%H:%M:%S')}")


def _green_pixel_worker_logic(
        target_color=config.GREEN_PIXEL_COLOR,
        threshold=config.COLOR_THRESHOLD,
        check_duration=0.1,
        check_interval=0.1,
        base_check_interval=0.15
):
    """
    Основная логика работы потока по поиску зеленого пикселя.
    """
    global _detection_counter, _sct, _last_reset_time
    _reset_mss()

    try:
        while not _green_pixel_stop_event.is_set():
            if time.time() - _last_reset_time > config.GREEN_PIXEL_RESTART_INTERVAL:
                _reset_mss()

            point = getattr(coordinate_utils, 'GREEN_PIXEL_POINT', None)
            series_found = False
            
            # Сначала проверяем точку (если задана)
            if point and isinstance(point, (tuple, list)) and len(point) == 2:
                x, y = int(point[0]), int(point[1])
                checks_needed = max(1, int(check_duration / check_interval))

                for i in range(checks_needed):
                    if _green_pixel_stop_event.is_set():
                        break
                    try:
                        monitor = {
                            "top": y,
                            "left": x,
                            "width": 1,
                            "height": 1,
                        }
                        screenshot = _sct.grab(monitor)
                        arr = np.array(screenshot)
                        b, g, r, _ = arr[0, 0]
                        color = (int(r), int(g), int(b))
                        if isinstance(target_color, list):
                            if any(all(abs(color[j] - tc[j]) <= threshold for j in range(3)) for tc in target_color):
                                series_found = True
                                break
                        elif all(abs(color[j] - target_color[j]) <= threshold for j in range(3)):
                            series_found = True
                            break

                        if i < checks_needed - 1:
                            if _green_pixel_stop_event.wait(timeout=check_interval):
                                break
                    except Exception as e:
                        print(f"[green_pixel] Ошибка захвата/обработки пикселя (mss): {e}")
                        _reset_mss()
                        if _green_pixel_stop_event.wait(timeout=check_interval * 2):
                            break

                if series_found:
                    _detection_counter += 1
                    green_pixel_detected_event.set()
                    if _green_pixel_stop_event.wait(timeout=base_check_interval):
                        break
                    continue

            search_area = coordinate_utils.GREEN_PIXEL_SEARCH_AREA

            if not search_area or len(search_area) != 4:
                print(f"[green_pixel] Ошибка: Неверная область захвата GREEN_PIXEL_SEARCH_AREA: {search_area}")
                if _green_pixel_stop_event.wait(timeout=base_check_interval):
                    break
                continue

            try:
                monitor = {
                    "top": search_area[1],
                    "left": search_area[0],
                    "width": search_area[2] - search_area[0],
                    "height": search_area[3] - search_area[1]
                }
                if monitor["width"] <= 0 or monitor["height"] <= 0:
                    print(
                        f"[green_pixel] Ошибка: Неверные размеры области захвата: ширина={monitor['width']}, высота={monitor['height']}")
                    if _green_pixel_stop_event.wait(timeout=base_check_interval):
                        break
                    continue
            except (IndexError, TypeError) as e:
                print(f"[green_pixel] Ошибка при преобразовании области захвата: {e}")
                if _green_pixel_stop_event.wait(timeout=base_check_interval):
                    break
                continue

            checks_needed = max(1, int(check_duration / check_interval))
            series_found = False

            for i in range(checks_needed):
                if _green_pixel_stop_event.is_set():
                    break

                try:
                    screenshot = _sct.grab(monitor)
                    img_array = np.array(screenshot)
                    img_array_rgb = img_array[:, :, [2, 1, 0]]

                    if isinstance(target_color, list):
                        for tc in target_color:
                            target_np = np.array(tc)
                            target_np = target_np[np.newaxis, np.newaxis, :]
                            diff = np.abs(img_array_rgb.astype(np.int16) - target_np.astype(np.int16))
                            mask = np.all(diff <= threshold, axis=-1)
                            if np.any(mask):
                                series_found = True
                                break
                        if series_found:
                            break
                    else:
                        target_np = np.array(target_color)
                        target_np = target_np[np.newaxis, np.newaxis, :]
                        diff = np.abs(img_array_rgb.astype(np.int16) - target_np.astype(np.int16))
                        mask = np.all(diff <= threshold, axis=-1)
                        if np.any(mask):
                            series_found = True
                            break

                    if i < checks_needed - 1:
                        if _green_pixel_stop_event.wait(timeout=check_interval):
                            break

                except Exception as e:
                    print(f"[green_pixel] Ошибка захвата/обработки изображения (mss): {e}")
                    _reset_mss()

                    if _green_pixel_stop_event.wait(timeout=check_interval * 2):
                        break
                    continue

            if series_found:
                _detection_counter += 1
                green_pixel_detected_event.set()

            if _green_pixel_stop_event.wait(timeout=base_check_interval):
                break

    except Exception as e:
        print(f"[green_pixel] Критическая ошибка в потоке поиска зеленого пикселя: {e}")


def start_green_pixel_monitoring():
    """
    Запускает поток непрерывного мониторинга зеленого пикселя.
    """
    global green_pixel_thread, _green_pixel_stop_event
    stop_green_pixel_monitoring()
    _green_pixel_stop_event.clear()
    green_pixel_detected_event.clear()
    global _detection_counter
    _detection_counter = 0
    green_pixel_thread = threading.Thread(target=_green_pixel_worker_logic, daemon=True)
    green_pixel_thread.start()


def stop_green_pixel_monitoring():
    """
    Отправляет сигнал для остановки потока мониторинга зеленого пикселя.
    """
    global _green_pixel_stop_event, green_pixel_thread
    if _green_pixel_stop_event:
        _green_pixel_stop_event.set()

def is_green_pixel_detected():
    """
    Проверяет, было ли обнаружено событие зеленого пикселя.
    Возвращает True, если событие установлено, иначе False.
    """
    return green_pixel_detected_event.is_set()

def clear_green_pixel_detected():
    """
    Сбрасывает событие обнаружения зеленого пикселя.
    """
    green_pixel_detected_event.clear()


__all__ = [
    'start_green_pixel_monitoring',
    'stop_green_pixel_monitoring',
    'is_green_pixel_detected',
    'clear_green_pixel_detected',
]