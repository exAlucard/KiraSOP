import threading
import time

import mss
import numpy as np

from la2_bot.utils import coordinate_utils

# Вторая точка для сравнения (для Betoner)
BETONER_X = 956
BETONER_Y = 504
BETONER_COLOR_HEX = "ff00ff"  # для Betoner

# Третья точка для сравнения (для DrKvas)
DRKVAS_X = 955
DRKVAS_Y = 507
DRKVAS_COLOR_HEX = "f700f6"  # для DrKvas

# Четвёртая точка для сравнения (для Wascer)
WASCER_X = 958
WASCER_Y = 500
WASCER_COLOR_HEX = "f700f6"  # для Wascer


def _hex_to_rgb(hex_str: str):
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        raise ValueError("HEX color must be 6 characters long")
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return r, g, b


_pause_event = None
_enabled = False
_thread = None
_stop_event = threading.Event()
_target_rgb = _hex_to_rgb("ef00ed")
_betoner_target_rgb = _hex_to_rgb(BETONER_COLOR_HEX)
_drkvas_target_rgb = _hex_to_rgb(DRKVAS_COLOR_HEX)
_wascer_target_rgb = _hex_to_rgb(WASCER_COLOR_HEX)
_last_log_time = 0.0
_last_error_log_time = 0.0


def _pixel_matches(rgb, tolerance=5):
    """Проверка совпадения для основного пикселя."""
    tr, tg, tb = _target_rgb
    r, g, b = rgb
    return (
        abs(tr - r) <= tolerance
        and abs(tg - g) <= tolerance
        and abs(tb - b) <= tolerance
    )


def _square_matches(center_x, center_y, target_rgb, tolerance=5, size=5):
    """Проверка совпадения цвета в квадрате size x size вокруг точки.

    В центре квадрата находится исходная точка (center_x, center_y).
    Если в пределах допуска найден хотя бы один пиксель нужного цвета, возвращает True.
    """
    half = size // 2
    top = center_y - half
    left = center_x - half

    if size <= 0:
        return False

    with mss.mss() as sct:
        monitor = {
            "top": top,
            "left": left,
            "width": size,
            "height": size,
        }

        img = sct.grab(monitor)
        arr = np.array(img)

        # mss возвращает BGRA, конвертируем в RGB
        bgr = arr[:, :, :3]
        rgb_arr = bgr[:, :, ::-1]

        target = np.array(target_rgb, dtype=np.int16)
        target = target[np.newaxis, np.newaxis, :]

        diff = np.abs(rgb_arr.astype(np.int16) - target)
        mask = np.all(diff <= tolerance, axis=-1)
        return bool(np.any(mask))


def _pixel_matches_betoner(rgb, tolerance=5):
    """Проверка совпадения для Betoner-пикселя."""
    tr, tg, tb = _betoner_target_rgb
    r, g, b = rgb
    return (
        abs(tr - r) <= tolerance
        and abs(tg - g) <= tolerance
        and abs(tb - b) <= tolerance
    )


def _pixel_matches_drkvas(rgb, tolerance=5):
    """Проверка совпадения для DrKvas-пикселя."""
    tr, tg, tb = _drkvas_target_rgb
    r, g, b = rgb
    return (
        abs(tr - r) <= tolerance
        and abs(tg - g) <= tolerance
        and abs(tb - b) <= tolerance
    )


def _pixel_matches_wascer(rgb, tolerance=5):
    """Проверка совпадения для Wascer-пикселя."""
    tr, tg, tb = _wascer_target_rgb
    r, g, b = rgb
    return (
        abs(tr - r) <= tolerance
        and abs(tg - g) <= tolerance
        and abs(tb - b) <= tolerance
    )


def _get_pixel_rgb():
    coord = coordinate_utils.get_absolute_coord("FLAGSTOP_POINT")
    if not coord or len(coord) < 2:
        raise RuntimeError("FLAGSTOP_POINT is not initialized; check coordinate initialization")

    x, y = coord[0], coord[1]

    with mss.mss() as sct:
        monitor = {
            "top": y,
            "left": x,
            "width": 1,
            "height": 1,
        }
        img = sct.grab(monitor)
        arr = np.array(img)
        b, g, r, _ = arr[0, 0]
        return (int(r), int(g), int(b)), (x, y)


def _get_wascer_pixel_rgb():
    """Получить цвет и координату Wascer-пикселя.

    Использует жёстко заданные координаты, не зависящие от FLAGSTOP_POINT.
    """
    x, y = WASCER_X, WASCER_Y
    with mss.mss() as sct:
        monitor = {
            "top": y,
            "left": x,
            "width": 1,
            "height": 1,
        }
        img = sct.grab(monitor)
        arr = np.array(img)
        b, g, r, _ = arr[0, 0]
        return (int(r), int(g), int(b)), (x, y)


def _get_drkvas_pixel_rgb():
    """Получить цвет и координату DrKvas-пикселя.

    Использует жёстко заданные координаты, не зависящие от FLAGSTOP_POINT.
    """
    x, y = DRKVAS_X, DRKVAS_Y
    with mss.mss() as sct:
        monitor = {
            "top": y,
            "left": x,
            "width": 1,
            "height": 1,
        }
        img = sct.grab(monitor)
        arr = np.array(img)
        b, g, r, _ = arr[0, 0]
        return (int(r), int(g), int(b)), (x, y)


def _get_betoner_pixel_rgb():
    """Получить цвет и координату Betoner-пикселя.

    Использует жёстко заданные координаты, не зависящие от FLAGSTOP_POINT.
    """
    x, y = BETONER_X, BETONER_Y
    with mss.mss() as sct:
        monitor = {
            "top": y,
            "left": x,
            "width": 1,
            "height": 1,
        }
        img = sct.grab(monitor)
        arr = np.array(img)
        b, g, r, _ = arr[0, 0]
        return (int(r), int(g), int(b)), (x, y)


def _worker():
    global _enabled, _last_log_time, _last_error_log_time
    while not _stop_event.is_set():
        if not _enabled or _pause_event is None:
            time.sleep(0.2)
            continue
        try:
            coord_main = coordinate_utils.get_absolute_coord("FLAGSTOP_POINT")
            if not coord_main or len(coord_main) < 2:
                try:
                    from la2_bot.config import config
                    from la2_bot.utils.window_utils import get_game_window_geometry
                    window_geometry = get_game_window_geometry(getattr(config, 'GAME_EXE_NAME', None))
                    if window_geometry:
                        coordinate_utils.initialize_coordinates(window_geometry)
                except Exception:
                    pass

                coord_main = coordinate_utils.get_absolute_coord("FLAGSTOP_POINT")
                if not coord_main or len(coord_main) < 2:
                    time.sleep(0.5)
                    continue

            x_main, y_main = coord_main[0], coord_main[1]

            matched_main = _square_matches(x_main, y_main, _target_rgb)
            matched_betoner = _square_matches(BETONER_X, BETONER_Y, _betoner_target_rgb)
            matched_drkvas = _square_matches(DRKVAS_X, DRKVAS_Y, _drkvas_target_rgb)
            matched_wascer = _square_matches(WASCER_X, WASCER_Y, _wascer_target_rgb)
            matched = matched_main or matched_betoner or matched_drkvas or matched_wascer

            # Логирование раз в секунду (отключено вывод в консоль)
            now = time.time()
            if now - _last_log_time >= 1.0:
                pause_state = _pause_event.is_set() if _pause_event is not None else None
                action = "NONE"
                if matched and pause_state:
                    action = "PAUSE_REQUESTED"
                elif matched and not pause_state:
                    action = "ALREADY_PAUSED"
                # Здесь ранее был подробный print(...) состояния флагстопа
                _last_log_time = now

            if matched:
                if _pause_event is not None and _pause_event.is_set():
                    print("[flagstop] Совпадение пикселя, ставлю бота на паузу")
                    _pause_event.clear()
            time.sleep(0.2)
        except Exception as e:
            now = time.time()
            if now - _last_error_log_time >= 5.0:
                print(f"[flagstop] Ошибка в воркере: {e}")
                _last_error_log_time = now
            time.sleep(0.5)


def get_flagstop_pixel_state():
    """Возвращает текущее состояние пикселя флагстопа.

    :return: (matched: bool, rgb: tuple|None)
    """
    try:
        rgb, _ = _get_pixel_rgb()
        return _pixel_matches(rgb), rgb
    except Exception:
        return False, None


def start_flagstop(pause_event):
    global _pause_event, _enabled, _thread
    _pause_event = pause_event
    _enabled = True
    if _thread is None or not _thread.is_alive():
        _stop_event.clear()
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()


def stop_flagstop():
    global _enabled
    _enabled = False


def is_flagstop_enabled():
    return _enabled
