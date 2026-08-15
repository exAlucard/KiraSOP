# la2_bot/utils/antiaggro_diagnostics.py
"""Диагностика anti-aggro без внешних зависимостей.

Пишет подробный rotating-log в ``logs/antiaggro/antiaggro.log`` и по запросу
сохраняет небольшие PNG-кропы HP-бара/контрольных точек таргета.

Модуль сделан ленивым: если каталог проекта недоступен для записи, логирование
продолжит работать в консоль и не сломает основной бот.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import time
from datetime import datetime

from PIL import ImageGrab

from la2_bot.config import config
from la2_bot.utils import coordinate_utils


_LOGGER_NAME = "kirasop.antiaggro"
_LOGGER = None
_INIT_LOCK = threading.Lock()
_THROTTLE_LOCK = threading.Lock()
_LAST_THROTTLED = {}
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_COUNTER = 0
_SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


def _project_root():
    # .../la2_bot/utils/antiaggro_diagnostics.py -> корень репозитория
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd()


def _log_dir():
    return _project_root() / "logs" / "antiaggro"


def get_log_path():
    return _log_dir() / "antiaggro.log"


def get_snapshot_dir():
    return _log_dir() / "snapshots"


def _build_logger():
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | %(levelname)-5s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # В файл идет DEBUG: там виден каждый HP sample и каждый poll таргета.
    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "antiaggro.log",
            maxBytes=3 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        # Файл диагностический; ошибка записи не должна останавливать бота.
        pass

    # В консоль не выводим каждый sample, только INFO+.
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


def get_logger():
    global _LOGGER
    if _LOGGER is None:
        with _INIT_LOCK:
            if _LOGGER is None:
                _LOGGER = _build_logger()
                _LOGGER.info(
                    "event=DIAG_SESSION_START session=%s client=%r log=%r",
                    _SESSION_ID,
                    getattr(config, "GAME_EXE_NAME", None),
                    str(get_log_path()),
                )
    return _LOGGER


def _safe_value(value):
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, (tuple, list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return repr(value)
    return repr(value)


def log_event(event, level="info", **fields):
    """Пишет структурированную строку ``event=... key=value``."""
    logger = get_logger()
    parts = [f"event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={_safe_value(value)}")
    message = " ".join(parts)

    fn = getattr(logger, str(level).lower(), logger.info)
    fn(message)


def log_event_throttled(key, interval, event, level="info", **fields):
    """То же, что log_event, но не чаще interval секунд для одного key."""
    now = time.monotonic()
    with _THROTTLE_LOCK:
        previous = _LAST_THROTTLED.get(key, 0.0)
        if now - previous < max(0.0, float(interval)):
            return False
        _LAST_THROTTLED[key] = now
    log_event(event, level=level, **fields)
    return True


def _point_box(point, padding=18):
    if not point:
        return None
    try:
        x, y = int(point[0]), int(point[1])
        p = max(2, int(padding))
        return (max(0, x - p), max(0, y - p), x + p + 1, y + p + 1)
    except Exception:
        return None


def _union_boxes(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _collect_probe_pixels():
    """Читает RGB только диагностических контрольных точек."""
    result = {}
    try:
        from la2_bot.utils.pixel_utils import get_pixel_color
    except Exception as exc:
        return {"pixel_read_error": repr(exc)}

    names = (
        "TARGET_HP_1_POINT",
        "TARGET_HP_FULL_POINT",
        "TARGET_HP_DAMAGED_POINT",
        "TARGET_SELECTED_POINT",
        "TARGET_MOB_POINT2",
        "CHAR_HP_POINT",
    )
    for name in names:
        point = getattr(coordinate_utils, name, None)
        if not point:
            result[name] = None
            continue
        try:
            result[name] = {
                "point": [int(point[0]), int(point[1])],
                "rgb": list(get_pixel_color(int(point[0]), int(point[1]))),
            }
        except Exception as exc:
            result[name] = {"point": list(point), "error": repr(exc)}
    return result


def collect_coordinate_diagnostics():
    return {
        "HP_BAR_RECT": getattr(coordinate_utils, "HP_BAR_RECT", None),
        "TARGET_HP_1_POINT": getattr(coordinate_utils, "TARGET_HP_1_POINT", None),
        "TARGET_HP_FULL_POINT": getattr(coordinate_utils, "TARGET_HP_FULL_POINT", None),
        "TARGET_HP_DAMAGED_POINT": getattr(coordinate_utils, "TARGET_HP_DAMAGED_POINT", None),
        "TARGET_SELECTED_POINT": getattr(coordinate_utils, "TARGET_SELECTED_POINT", None),
        "TARGET_MOB_POINT2": getattr(coordinate_utils, "TARGET_MOB_POINT2", None),
    }


def save_debug_snapshot(reason, metadata=None, hp_image=None):
    """Сохраняет небольшие диагностические PNG + JSON.

    Снимки делаются только по явному вызову из watcher/детектора, поэтому не
    создают постоянную нагрузку. Ошибка создания снимка никогда не пробрасывается.
    """
    global _SNAPSHOT_COUNTER

    # Можно отключить без изменения кода.
    if not bool(getattr(config, "THREAT_DEBUG_SNAPSHOTS", True)):
        return None

    with _SNAPSHOT_LOCK:
        _SNAPSHOT_COUNTER += 1
        counter = _SNAPSHOT_COUNTER

    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(reason))[:50]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    stem = f"{stamp}_{counter:04d}_{safe_reason}"

    try:
        out_dir = get_snapshot_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_event("SNAPSHOT_DIR_ERROR", level="warning", reason=reason, error=repr(exc))
        return None

    saved = {}
    errors = []

    # HP bar: если detector уже имеет свежий crop, не делаем второй grab.
    try:
        if hp_image is not None:
            img = hp_image.copy()
        else:
            hp_rect = getattr(coordinate_utils, "HP_BAR_RECT", None)
            img = ImageGrab.grab(bbox=hp_rect) if hp_rect else None
        if img is not None:
            path = out_dir / f"{stem}_hp.png"
            img.save(path)
            saved["hp"] = str(path)
    except Exception as exc:
        errors.append(f"hp:{exc!r}")

    # Маленькие отдельные crop-ы вокруг контрольных точек таргета. Так даже если
    # точки находятся далеко друг от друга, snapshot не превращается в почти полный экран.
    try:
        point_specs = (
            ("target_hp1", getattr(coordinate_utils, "TARGET_HP_1_POINT", None)),
            ("target_full", getattr(coordinate_utils, "TARGET_HP_FULL_POINT", None)),
            ("target_damaged", getattr(coordinate_utils, "TARGET_HP_DAMAGED_POINT", None)),
            ("target_selected", getattr(coordinate_utils, "TARGET_SELECTED_POINT", None)),
            ("target_mob2", getattr(coordinate_utils, "TARGET_MOB_POINT2", None)),
        )
        for label, point in point_specs:
            bbox = _point_box(point, padding=24)
            if not bbox:
                continue
            img = ImageGrab.grab(bbox=bbox)
            path = out_dir / f"{stem}_{label}.png"
            img.save(path)
            saved[label] = {"path": str(path), "bbox": list(bbox)}
    except Exception as exc:
        errors.append(f"target:{exc!r}")

    payload = {
        "session": _SESSION_ID,
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "reason": reason,
        "client": getattr(config, "GAME_EXE_NAME", None),
        "coordinates": collect_coordinate_diagnostics(),
        "probe_pixels": _collect_probe_pixels(),
        "metadata": metadata or {},
        "saved": saved,
        "errors": errors,
    }

    try:
        json_path = out_dir / f"{stem}.json"
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        saved["json"] = str(json_path)
    except Exception as exc:
        errors.append(f"json:{exc!r}")

    log_event(
        "SNAPSHOT_SAVED",
        reason=reason,
        files=saved,
        errors=errors,
    )
    return saved
