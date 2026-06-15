# la2_bot/utils/pixel_utils.py

import ctypes
from la2_bot.config import config
def get_pixel_color(x, y):
    """Считывает пиксель (R, G, B)."""
    hdc   = ctypes.windll.user32.GetDC(0)
    memdc = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
    bmp   = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc, 1, 1)
    ctypes.windll.gdi32.SelectObject(memdc, bmp)
    ctypes.windll.gdi32.BitBlt(memdc, 0, 0, 1, 1, hdc, x, y, 0x00CC0020)
    buf = ctypes.create_string_buffer(4)
    ctypes.windll.gdi32.GetBitmapBits(bmp, 4, buf)
    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(memdc)
    ctypes.windll.user32.ReleaseDC(0, hdc)
    raw = buf.raw
    return (raw[2], raw[1], raw[0])


def is_color_match(color, target, thresh=config.COLOR_THRESHOLD):
    return all(abs(color[i] - target[i]) <= thresh for i in range(3))

def is_target_color(color):
    """Проверяет, соответствует ли цвет одному из цветов цели."""
    if isinstance(config.TARGET_COLOR, list):
        return any(is_color_match(color, c) for c in config.TARGET_COLOR)
    return is_color_match(color, config.TARGET_COLOR)