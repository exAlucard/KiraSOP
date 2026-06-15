# la2_bot/utils/mob_name_highlighter.py

import time
import os
import re
import numpy as np
from PIL import ImageGrab, ImageDraw
import easyocr
from la2_bot.config import config
from la2_bot.utils import coordinate_utils

DEBUG_DIR = "../../debug"
MAX_DEBUG_FILES = 5
reader = easyocr.Reader(['en'], gpu=True)

def mob_highlight_loop():
    """
    Выполняет одну итерацию поиска и подсветки мобов.
    (Основной цикл теперь управляется из main.py)
    """
    find_and_highlight_mobs()

def clean_text(text):
    """Удаляем лишнее, нормализуем текст для сравнения."""
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9 ]+', '', text)
    return text


def find_and_highlight_mobs():
    """
    Захватывает область экрана, ищет имена мобов с помощью EasyOCR
    и подсвечивает их, если находит.
    """
    bbox = coordinate_utils.NAME_SEARCH_AREA
    try:
        raw_img = ImageGrab.grab(bbox=bbox).convert("RGB")
    except Exception as e:
        print(f"[EasyOCR] Ошибка захвата экрана: {e}")
        return

    try:
        results = reader.readtext(np.array(raw_img), detail=1, paragraph=False)

    except Exception as e:
        print(f"[EasyOCR] Ошибка при распознавании: {e}")
        return

    draw = ImageDraw.Draw(raw_img)
    found = False

    for (bbox_coords, text_raw, confidence) in results:
        if not isinstance(text_raw, str) or not text_raw.strip():
            continue

        text_clean = clean_text(text_raw)
        if not text_clean:
            continue

        for mob in config.MOB_NAMES:
            mob_clean = clean_text(mob)
            if not mob_clean:
                continue

            if text_clean in mob_clean or mob_clean in text_clean or text_clean == mob_clean:
                xs = [point[0] for point in bbox_coords]
                ys = [point[1] for point in bbox_coords]
                x_min, x_max = int(min(xs)), int(max(xs))
                y_min, y_max = int(min(ys)), int(max(ys))

                outline_color = "blue"
                for offset in range(2):
                    draw.rectangle(
                        [(x_min + offset, y_min + offset), (x_max - offset, y_max - offset)],
                        outline=outline_color
                    )
                print(
                    f"[EasyOCR] Found mob '{mob}' (raw: '{text_raw}', clean: '{text_clean}', conf: {confidence:.2f}) at bbox ({x_min}, {y_min}, {x_max}, {y_max})")
                found = True

    if found:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        timestamp = int(time.time())
        raw_img.save(os.path.join(DEBUG_DIR, f"mob_highlight_{timestamp}_easyocr.png"))
        cleanup_old_debug_screens(DEBUG_DIR, MAX_DEBUG_FILES)


def cleanup_old_debug_screens(directory, max_files):
    """Удаляет старые отладочные файлы, оставляя только последние `max_files`."""
    try:
        files = [os.path.join(directory, f) for f in os.listdir(directory)
                 if f.startswith("mob_") and f.endswith("_easyocr.png")]
        files.sort(key=os.path.getmtime, reverse=True)

        for file in files[max_files:]:
            try:
                os.remove(file)
            except Exception as e:
                print(f"[EasyOCR] Error deleting {file}: {e}")
    except Exception as e:
        print(f"[EasyOCR] Error during cleanup: {e}")




