# la2_bot/detection/hp_bar_detection.py
"""Чтение HP персонажа для anti-aggro.

ВАЖНО ДЛЯ LU4:
по диагностическим снимкам область ``HP_BAR_RECT`` фактически содержит не
горизонтальную полоску, а числовое значение HP (например 189, 184, 127).
Старый алгоритм искал "последний красный пиксель" и поэтому воспринимал форму
цифр как процент HP. Здесь область читается как число через Tesseract OCR.

Имя ``get_hp_percentage`` сохранено ради совместимости со старым кодом, но
возвращаемое значение для OCR-режима — текущее абсолютное HP, а не процент.
Для определения входящего урона это даже полезнее: watcher сравнивает два
последовательных значения и реагирует на уменьшение.
"""

import os
import re
import threading
from pathlib import Path

from PIL import Image, ImageGrab, ImageOps

from la2_bot.config import config
from la2_bot.utils import coordinate_utils
from la2_bot.utils.antiaggro_diagnostics import log_event, log_event_throttled

try:
    import pytesseract
    from pytesseract import TesseractNotFoundError
except Exception:  # pragma: no cover - обрабатывается как отсутствие OCR
    pytesseract = None

    class TesseractNotFoundError(RuntimeError):
        pass


_ocr_lock = threading.Lock()
_tesseract_checked = False
_tesseract_available = False
_tesseract_path = None


def _candidate_tesseract_paths():
    configured = getattr(config, "TESSERACT_CMD", None)
    env_value = os.environ.get("TESSERACT_CMD")

    candidates = [configured, env_value]
    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ])

    result = []
    for value in candidates:
        if not value:
            continue
        value = os.path.expandvars(os.path.expanduser(str(value)))
        if value not in result:
            result.append(value)
    return result


def _ensure_tesseract():
    """Проверяет Tesseract один раз и кэширует результат."""
    global _tesseract_checked, _tesseract_available, _tesseract_path

    if _tesseract_checked:
        return _tesseract_available

    with _ocr_lock:
        if _tesseract_checked:
            return _tesseract_available

        _tesseract_checked = True

        if pytesseract is None:
            log_event_throttled(
                "hp_ocr_wrapper_missing",
                30.0,
                "HP_OCR_UNAVAILABLE",
                level="error",
                reason="pytesseract_import_failed",
                hint="Установи пакет pytesseract из requirements.txt.",
            )
            return False

        # Сначала пробуем tesseract из PATH / уже заданный pytesseract.tesseract_cmd.
        try:
            version = str(pytesseract.get_tesseract_version())
            _tesseract_available = True
            _tesseract_path = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract"))
            log_event(
                "HP_OCR_READY",
                level="info",
                engine="tesseract",
                version=version.splitlines()[0] if version else None,
                executable=_tesseract_path,
            )
            return True
        except Exception:
            pass

        # На Windows Tesseract часто установлен, но каталог не добавлен в PATH.
        for candidate in _candidate_tesseract_paths():
            try:
                if not Path(candidate).is_file():
                    continue
                pytesseract.pytesseract.tesseract_cmd = candidate
                version = str(pytesseract.get_tesseract_version())
                _tesseract_available = True
                _tesseract_path = candidate
                log_event(
                    "HP_OCR_READY",
                    level="info",
                    engine="tesseract",
                    version=version.splitlines()[0] if version else None,
                    executable=candidate,
                )
                return True
            except Exception:
                continue

        log_event_throttled(
            "hp_ocr_engine_missing",
            30.0,
            "HP_OCR_UNAVAILABLE",
            level="error",
            reason="tesseract_executable_not_found",
            candidates=_candidate_tesseract_paths(),
            hint=(
                "pytesseract установлен, но не найден tesseract.exe. Добавь Tesseract-OCR в PATH "
                "или задай config.TESSERACT_CMD."
            ),
        )
        return False


def _extract_digits(text):
    if text is None:
        return None, None
    compact = "".join(re.findall(r"\d+", str(text)))
    if not compact:
        return None, None
    # Защита от случайного огромного мусора OCR.
    if len(compact) > 8:
        return None, compact
    try:
        value = int(compact)
    except (TypeError, ValueError):
        return None, compact
    if value < 0:
        return None, compact
    return value, compact


def _ocr_once(image):
    config_string = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    data = pytesseract.image_to_data(
        image,
        config=config_string,
        output_type=pytesseract.Output.DICT,
    )

    candidates = []
    for text, confidence in zip(data.get("text", []), data.get("conf", [])):
        value, digits = _extract_digits(text)
        if value is None:
            continue
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = -1.0
        candidates.append((conf, value, digits, str(text).strip()))

    if not candidates:
        raw = " ".join(str(x).strip() for x in data.get("text", []) if str(x).strip())
        return None, None, raw, None

    candidates.sort(key=lambda item: item[0], reverse=True)
    conf, value, digits, raw = candidates[0]
    return value, digits, raw, conf


def analyze_hp_image(image):
    """Распознаёт числовое HP на уже полученном PIL Image.

    Функция вынесена отдельно, чтобы диагностические PNG можно было проверять
    без ImageGrab. На нормальном кадре выполняется один OCR-pass; второй pass
    нужен только если исходный маленький crop не распознался.
    """
    if image is None:
        return {
            "value": None,
            "ocr_text": None,
            "ocr_raw": None,
            "ocr_confidence": None,
            "ocr_pass": None,
            "error": "image_missing",
        }

    if not _ensure_tesseract():
        return {
            "value": None,
            "ocr_text": None,
            "ocr_raw": None,
            "ocr_confidence": None,
            "ocr_pass": None,
            "error": "tesseract_unavailable",
        }

    try:
        # pytesseract вызывает внешний процесс. Lock не дает live diagnostic и
        # watcher одновременно плодить OCR-процессы на одном маленьком регионе.
        with _ocr_lock:
            value, digits, raw, confidence = _ocr_once(image.convert("RGB"))
            min_confidence = float(getattr(config, "THREAT_HP_OCR_MIN_CONFIDENCE", 45.0))
            if value is not None and (confidence is None or confidence >= min_confidence):
                return {
                    "value": float(value),
                    "ocr_text": digits,
                    "ocr_raw": raw,
                    "ocr_confidence": confidence,
                    "ocr_pass": "rgb_original",
                    "error": None,
                }

            # Fallback: увеличиваем серое изображение. На скейле игры это обычно
            # восстанавливает цифры, которые Tesseract пропустил на 20-30 px crop.
            gray = ImageOps.grayscale(image)
            scale = 4
            enlarged = gray.resize(
                (max(1, gray.width * scale), max(1, gray.height * scale)),
                Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else 1,
            )
            value2, digits2, raw2, confidence2 = _ocr_once(enlarged)
            if value2 is not None and (confidence2 is None or confidence2 >= min_confidence):
                return {
                    "value": float(value2),
                    "ocr_text": digits2,
                    "ocr_raw": raw2,
                    "ocr_confidence": confidence2,
                    "ocr_pass": "gray_upscaled",
                    "error": None,
                }

            return {
                "value": None,
                "ocr_text": digits2 or digits,
                "ocr_raw": raw2 or raw,
                "ocr_confidence": confidence2 if confidence2 is not None else confidence,
                "ocr_pass": "failed_both",
                "error": "digits_not_recognized_or_low_confidence",
            }

    except TesseractNotFoundError as exc:
        log_event_throttled(
            "hp_ocr_engine_lost",
            10.0,
            "HP_OCR_UNAVAILABLE",
            level="error",
            error=repr(exc),
        )
        return {
            "value": None,
            "ocr_text": None,
            "ocr_raw": None,
            "ocr_confidence": None,
            "ocr_pass": None,
            "error": "tesseract_not_found",
        }
    except Exception as exc:
        log_event_throttled(
            "hp_ocr_exception",
            2.0,
            "HP_OCR_ERROR",
            level="error",
            error=repr(exc),
        )
        return {
            "value": None,
            "ocr_text": None,
            "ocr_raw": None,
            "ocr_confidence": None,
            "ocr_pass": None,
            "error": repr(exc),
        }



def _is_hp_red(pixel):
    r, g, b = pixel[:3]
    return r > g + b and r > 50


def _analyze_bar_image(image):
    """Fallback для клиентов, где HP_BAR_RECT действительно является полосой."""
    if image is None:
        return {"value": None, "rows": [], "row_spread": None, "error": "image_missing"}

    width, height = image.size
    if width <= 0 or height <= 0:
        return {"value": None, "rows": [], "row_spread": None, "error": "empty_image"}

    center_y = height // 2
    row_ids = sorted({
        max(0, min(height - 1, center_y - 1)),
        max(0, min(height - 1, center_y)),
        max(0, min(height - 1, center_y + 1)),
    })

    rows = []
    values = []
    for y in row_ids:
        last_hp_x = -1
        red_count = 0
        transitions = 0
        previous_red = None
        for x in range(width):
            red = _is_hp_red(image.getpixel((x, y)))
            if red:
                red_count += 1
                last_hp_x = x
            if previous_red is not None and previous_red != red:
                transitions += 1
            previous_red = red

        percentage = 0.0 if last_hp_x < 0 else ((last_hp_x + 1) / width) * 100.0
        rows.append({
            "y": int(y),
            "percentage": float(percentage),
            "last_red_x": int(last_hp_x),
            "red_count": int(red_count),
            "red_ratio": float(red_count / width),
            "transitions": int(transitions),
        })
        values.append(float(percentage))

    values_sorted = sorted(values)
    value = values_sorted[len(values_sorted) // 2] if values_sorted else None
    spread = (max(values) - min(values)) if values else None
    return {"value": value, "rows": rows, "row_spread": spread, "error": None}


def _detection_mode():
    mode = str(getattr(config, "THREAT_HP_DETECT_MODE", "auto") or "auto").strip().lower()
    if mode in {"ocr", "numeric", "ocr_numeric"}:
        return "ocr_numeric"
    if mode in {"bar", "percentage", "bar_percentage"}:
        return "bar_percentage"

    client = str(getattr(config, "GAME_EXE_NAME", "") or "").lower()
    if "lu4" in client:
        return "ocr_numeric"
    if "mw" in client:
        return "bar_percentage"
    return "auto"

def _grab_hp_region():
    # Для обратной совместимости сначала используем исправленный пользователем
    # HP_BAR_RECT, затем исходный OCR-прямоугольник HP_RECT.
    rect = getattr(coordinate_utils, "HP_BAR_RECT", None)
    if not rect:
        rect = getattr(coordinate_utils, "HP_RECT", None)

    if not rect:
        log_event_throttled(
            "hp_rect_missing",
            2.0,
            "HP_RECT_MISSING",
            level="error",
            hint="Не найден ни HP_BAR_RECT, ни HP_RECT.",
        )
        return None, rect

    try:
        return ImageGrab.grab(bbox=rect), rect
    except Exception as exc:
        log_event_throttled(
            "hp_grab_error",
            1.0,
            "HP_GRAB_ERROR",
            level="error",
            hp_rect=rect,
            error=repr(exc),
        )
        return None, rect


def get_hp_measurement(include_image=False):
    """Возвращает HP и диагностические поля.

    LU4: числовое абсолютное HP через OCR.
    MW/настоящая полоска: процент заполнения старым bar-детектором.
    ``THREAT_HP_DETECT_MODE = 'ocr'|'bar'`` может принудительно выбрать режим.
    """
    hp_image, rect = _grab_hp_region()
    if hp_image is None:
        return {
            "percentage": None,
            "value": None,
            "bbox": rect,
            "size": None,
            "method": None,
            "ocr_text": None,
            "ocr_raw": None,
            "ocr_confidence": None,
            "ocr_pass": None,
            "rows": [],
            "row_spread": None,
            "image": None,
            "error": "grab_failed_or_rect_missing",
        }

    width, height = hp_image.size
    mode = _detection_mode()

    if mode in {"ocr_numeric", "auto"}:
        ocr_result = analyze_hp_image(hp_image)
        value = ocr_result.get("value")
        if value is not None:
            return {
                "percentage": value,
                "value": value,
                "bbox": rect,
                "size": [width, height],
                "method": "ocr_numeric",
                "ocr_text": ocr_result.get("ocr_text"),
                "ocr_raw": ocr_result.get("ocr_raw"),
                "ocr_confidence": ocr_result.get("ocr_confidence"),
                "ocr_pass": ocr_result.get("ocr_pass"),
                "rows": [],
                "row_spread": None,
                "image": hp_image.copy() if include_image else None,
                "error": None,
            }

        # Для LU4 НЕ используем старый red-pixel fallback: на присланных кадрах
        # он измеряет геометрию цифр "189/184/127" и создаёт ложный процент.
        if mode == "ocr_numeric":
            log_event_throttled(
                "hp_ocr_unreadable",
                0.75,
                "HP_OCR_UNREADABLE",
                level="warning",
                bbox=rect,
                size=[width, height],
                ocr_text=ocr_result.get("ocr_text"),
                ocr_raw=ocr_result.get("ocr_raw"),
                ocr_confidence=ocr_result.get("ocr_confidence"),
                ocr_pass=ocr_result.get("ocr_pass"),
                error=ocr_result.get("error"),
            )
            return {
                "percentage": None,
                "value": None,
                "bbox": rect,
                "size": [width, height],
                "method": "ocr_numeric",
                "ocr_text": ocr_result.get("ocr_text"),
                "ocr_raw": ocr_result.get("ocr_raw"),
                "ocr_confidence": ocr_result.get("ocr_confidence"),
                "ocr_pass": ocr_result.get("ocr_pass"),
                "rows": [],
                "row_spread": None,
                "image": hp_image.copy() if include_image else None,
                "error": ocr_result.get("error"),
            }

    bar_result = _analyze_bar_image(hp_image)
    value = bar_result.get("value")
    spread = bar_result.get("row_spread")
    rows = bar_result.get("rows") or []

    if spread is not None and spread >= 5.0:
        log_event_throttled(
            "hp_row_spread",
            0.5,
            "HP_ROWS_INCONSISTENT",
            level="warning",
            hp=value,
            spread=spread,
            rows=rows,
            bbox=rect,
            size=[width, height],
        )

    return {
        "percentage": value,
        "value": value,
        "bbox": rect,
        "size": [width, height],
        "method": "bar_percentage",
        "ocr_text": None,
        "ocr_raw": None,
        "ocr_confidence": None,
        "ocr_pass": None,
        "rows": rows,
        "row_spread": spread,
        "image": hp_image.copy() if include_image else None,
        "error": bar_result.get("error"),
    }

def get_hp_percentage():
    """Совместимый API: текущее абсолютное HP или None."""
    return get_hp_measurement(include_image=False)["percentage"]
