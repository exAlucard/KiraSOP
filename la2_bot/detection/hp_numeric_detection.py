# la2_bot/detection/hp_numeric_detection.py
"""
Чтение фактического HP персонажа из текста интерфейса игры.

Пример:
    287 / 287

Используется ТОЛЬКО для отладки/оверлея.
Логика анти-агра продолжает работать по HP BAR и не зависит от OCR.
"""

import re
import threading
import time

from PIL import ImageGrab, ImageOps, ImageEnhance

from la2_bot.utils import coordinate_utils


_CACHE_LOCK = threading.Lock()
_CACHE = {
    "timestamp": 0.0,
    "current": None,
    "max": None,
    "raw": "",
    "source": "",
}

_EASYOCR_READER = None
_EASYOCR_FAILED = False


def get_hp_numeric_rect():
    """
    Возвращает область, в которой написано HP вида CURRENT / MAX.

    Приоритет:
      1. HP_TEXT_RECT_REL -> coordinate_utils.HP_TEXT_RECT
      2. старый HP_RECT_REL -> coordinate_utils.HP_RECT
         (в LU4 он уже обозначен как OCR-прямоугольник)
      3. автоматическая область вокруг центра HP_BAR_RECT

    Для максимально стабильной работы лучше явно добавить в config_*.py:
        HP_TEXT_RECT_REL = (left, top, right, bottom)
    """
    explicit_rect = getattr(
        coordinate_utils,
        "HP_TEXT_RECT",
        None,
    )

    if explicit_rect:
        return explicit_rect

    legacy_ocr_rect = getattr(
        coordinate_utils,
        "HP_RECT",
        None,
    )

    if legacy_ocr_rect:
        return legacy_ocr_rect

    hp_bar_rect = getattr(
        coordinate_utils,
        "HP_BAR_RECT",
        None,
    )

    if not hp_bar_rect:
        return None

    x1, y1, x2, y2 = hp_bar_rect
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)

    # Цифры HP обычно находятся примерно по центру самой полоски.
    left = int(x1 + width * 0.28)
    right = int(x1 + width * 0.72)

    # HP_BAR_RECT нередко задается только по внутренней красной линии.
    # Поэтому расширяем область вверх и вниз, чтобы захватить цифры целиком.
    top = int(y1 - max(6, height * 1.0))
    bottom = int(y2 + max(10, height * 1.5))

    return (
        left,
        max(0, top),
        right,
        bottom,
    )


def _parse_hp_text(text):
    if not text:
        return None

    cleaned = text.replace("\\", "/")
    cleaned = cleaned.replace("|", "/")
    cleaned = re.sub(r"\s+", "", cleaned)

    match = re.search(
        r"(\d{1,7})/(\d{1,7})",
        cleaned,
    )

    if not match:
        return None

    try:
        current = int(match.group(1))
        maximum = int(match.group(2))
    except ValueError:
        return None

    if maximum <= 0:
        return None

    if current < 0 or current > maximum:
        return None

    return current, maximum


def _get_easyocr_reader():
    global _EASYOCR_READER
    global _EASYOCR_FAILED

    if _EASYOCR_READER is not None:
        return _EASYOCR_READER

    if _EASYOCR_FAILED:
        return None

    try:
        import easyocr

        # Инициализируется лениво: только когда открыт Debug Overlay
        # и впервые понадобилось числовое HP.
        _EASYOCR_READER = easyocr.Reader(
            ["en"],
            gpu=False,
            verbose=False,
        )

        return _EASYOCR_READER

    except Exception as exc:
        _EASYOCR_FAILED = True

        print(
            "[HP Numeric OCR] EasyOCR недоступен: "
            f"{exc}"
        )

        return None


def _read_with_easyocr(image):
    reader = _get_easyocr_reader()

    if reader is None:
        return None, ""

    try:
        import numpy as np

        # Увеличение особенно важно для маленьких цифр интерфейса L2.
        scale = 5
        enlarged = image.resize(
            (
                image.width * scale,
                image.height * scale,
            )
        )

        results = reader.readtext(
            np.array(enlarged),
            detail=0,
            paragraph=False,
            allowlist="0123456789/",
        )

        raw = " ".join(
            str(item)
            for item in results
        )

        parsed = _parse_hp_text(raw)

        return parsed, raw

    except Exception as exc:
        print(
            "[HP Numeric OCR] Ошибка EasyOCR: "
            f"{exc}"
        )
        return None, ""


def _read_with_tesseract(image):
    """
    Резервный OCR через pytesseract.

    Пробуем несколько вариантов обработки, потому что цифры в L2
    маленькие и имеют тёмную обводку.
    """
    try:
        import pytesseract
    except Exception as exc:
        print(
            "[HP Numeric OCR] pytesseract недоступен: "
            f"{exc}"
        )
        return None, ""

    candidates = []

    try:
        for scale in (5, 7):
            enlarged = image.resize(
                (
                    image.width * scale,
                    image.height * scale,
                )
            )

            gray = ImageOps.grayscale(enlarged)
            gray = ImageEnhance.Contrast(
                gray
            ).enhance(1.6)

            variants = [
                gray,
                ImageOps.autocontrast(gray),
            ]

            for threshold in (140, 165, 190):
                variants.append(
                    gray.point(
                        lambda value, t=threshold:
                            255 if value > t else 0
                    )
                )

            for variant in variants:
                for psm in (6, 7):
                    raw = pytesseract.image_to_string(
                        variant,
                        config=(
                            f"--psm {psm} --oem 1 "
                            "-c "
                            "tessedit_char_whitelist="
                            "0123456789/"
                        ),
                    )

                    parsed = _parse_hp_text(raw)

                    if parsed:
                        candidates.append(
                            (
                                parsed,
                                raw.strip(),
                            )
                        )

        if not candidates:
            return None, ""

        # Если несколько вариантов дали одинаковый результат,
        # считаем такой вариант наиболее надежным.
        counts = {}

        for parsed, raw in candidates:
            counts[parsed] = (
                counts.get(parsed, 0) + 1
            )

        best = max(
            counts,
            key=counts.get,
        )

        best_raw = ""

        for parsed, raw in candidates:
            if parsed == best:
                best_raw = raw
                break

        return best, best_raw

    except Exception as exc:
        print(
            "[HP Numeric OCR] Ошибка Tesseract: "
            f"{exc}"
        )

        return None, ""


def get_hp_numeric_values(force=False):
    """
    Возвращает:
        {
            "current": 287,
            "max": 287,
            "raw": "287 / 287",
            "source": "EasyOCR",
        }

    Значение кэшируется, чтобы OCR не выполнялся каждые 0.5 сек.
    """
    now = time.time()

    cache_interval = 1.0

    with _CACHE_LOCK:
        if (
            not force
            and now - _CACHE["timestamp"]
            < cache_interval
        ):
            return dict(_CACHE)

    rect = get_hp_numeric_rect()

    if not rect:
        result = {
            "timestamp": now,
            "current": None,
            "max": None,
            "raw": "",
            "source": "",
        }

        with _CACHE_LOCK:
            _CACHE.update(result)

        return dict(result)

    try:
        image = ImageGrab.grab(
            bbox=rect
        )
    except Exception as exc:
        print(
            "[HP Numeric OCR] Не удалось захватить "
            f"область HP: {exc}"
        )

        result = {
            "timestamp": now,
            "current": None,
            "max": None,
            "raw": "",
            "source": "",
        }

        with _CACHE_LOCK:
            _CACHE.update(result)

        return dict(result)

    # EasyOCR обычно устойчивее на маленьком игровом шрифте.
    parsed, raw = _read_with_easyocr(
        image
    )

    source = "EasyOCR"

    if not parsed:
        parsed, raw = _read_with_tesseract(
            image
        )
        source = "Tesseract"

    if parsed:
        current, maximum = parsed

        result = {
            "timestamp": now,
            "current": current,
            "max": maximum,
            "raw": raw,
            "source": source,
        }
    else:
        result = {
            "timestamp": now,
            "current": None,
            "max": None,
            "raw": raw,
            "source": "",
        }

    with _CACHE_LOCK:
        _CACHE.update(result)

    return dict(result)
