# la2_bot/ui/config_panel.py
"""
Окно редактирования активного config_lu4.py / config_mw.py.

Особенности:
- автоматически читает все UPPER_CASE переменные из активного конфига;
- дополнительно находит опциональные config-параметры, используемые через
  getattr(config, ...) и _cfg_*('NAME', default) в исходниках проекта;
- безопасно парсит ввод через ast.literal_eval (без eval/exec);
- сохраняет только реально изменённые значения;
- перед записью делает timestamp-backup исходного конфига;
- применяет сохранённые значения к активному модулю в памяти;
- при изменении *_REL/координат очищает coordinate cache;
- подсказка по каждому параметру появляется при наведении на его название.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, Iterable, List, Optional, Tuple

from la2_bot.config.config_manager import get_config, get_client_name


# ---------------------------------------------------------------------------
# Описания самых важных параметров. Для остальных tooltip дополняется
# автоматически: комментариями из config_*.py, названием секции и типом.
# ---------------------------------------------------------------------------
DESCRIPTIONS: Dict[str, str] = {
    "CHECK_INTERVAL": "Основной интервал главного цикла бота в секундах. Меньше — быстрее реакция, но выше нагрузка CPU.",
    "GAME_EXE_NAME": "Имя процесса игрового клиента, для которого используется этот конфиг.",
    "COLOR_THRESHOLD": "Допуск сравнения цветов пикселей. Чем больше значение, тем мягче проверка цвета.",
    "TARGET_SWITCH_DELAY": "Обычная задержка перед поиском следующей цели.",
    "NEXT_TARGET_MIN": "Минимальная задержка между обычными командами поиска следующей цели.",
    "NEXT_TARGET_MAX": "Максимальная задержка между обычными командами поиска следующей цели.",
    "STUCK_TARGET_TIMEOUT": "Сколько секунд цель может не меняться, прежде чем бот посчитает её застрявшей.",
    "LOOT_MIN": "Минимальная пауза между командами подбора лута.",
    "LOOT_MAX": "Максимальная пауза между командами подбора лута.",
    "SWEEP_TO_LOOT_MIN": "Минимальная пауза между Sweep и последующим подбором лута.",
    "SWEEP_TO_LOOT_MAX": "Максимальная пауза между Sweep и последующим подбором лута.",
    "LOOT_REPEAT_COUNT": "Сколько раз нажимать кнопку подбора лута после убийства.",
    "POTION_INTERVAL": "Минимальный интервал между использованием HP банки.",
    "MP_SKILL_INTERVAL": "Интервал использования MP-скилла.",
    "ATTACK_INTERVAL_MIN": "Минимальный интервал резервного/повторного нажатия Attack.",
    "ATTACK_INTERVAL_MAX": "Максимальный интервал резервного/повторного нажатия Attack.",
    "SPOIL_ATTEMPT_INTERVAL_MIN": "Минимальный интервал между обычными повторными попытками Spoil.",
    "SPOIL_ATTEMPT_INTERVAL_MAX": "Максимальный интервал между обычными повторными попытками Spoil.",
    "THREAT_WATCH_DURATION": "Базовая длительность post-death окна наблюдения anti-aggro.",
    "THREAT_WATCH_CHECK_INTERVAL": "Как часто anti-aggro проверяет HP персонажа во время watcher.",
    "THREAT_HP_DROP_THRESHOLD_ABS": "Минимальное подтверждённое падение числового HP персонажа для детекта входящего урона.",
    "THREAT_HP_DROP_THRESHOLD": "Порог падения HP для процентного режима определения HP.",
    "THREAT_HP_CONFIRM_SAMPLES": "Сколько последовательных измерений должны подтвердить урон.",
    "THREAT_HP_CONFIRM_TOLERANCE_ABS": "Допуск между подтверждающими числовыми измерениями HP.",
    "THREAT_SCENARIO_KILL_ENABLED": "Сценарий «Антиагр кил»: после смерти текущей цели / при отсутствии валидного таргета бот отслеживает входящий урон и может взять агрессора. Можно включать независимо от FULL HP сценария.",
    "THREAT_SCENARIO_FULL_HP_ENABLED": "Сценарий «Антиагр фул хп»: когда текущая цель есть и всё ещё FULL HP, но персонаж получает урон, бот через anti-aggro проверку может сменить цель. Можно включать независимо от post-death сценария.",
    "THREAT_NO_TARGET_DECISION_DELAY": "Задержка anti-aggro, когда валидного таргета нет. Сейчас рекомендуемое значение — 1.0 сек.",
    "THREAT_LIVE_FULL_TARGET_DECISION_DELAY": "Задержка anti-aggro, когда текущая цель есть, но всё ещё FULL HP. Сейчас рекомендуемое значение — 1.0 сек.",
    "THREAT_ENGAGED_FULL_RECHECK_DECISION_DELAY": "Задержка повторной проверки уже выбранной anti-aggro цели, если она остаётся FULL HP.",
    "THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE": "Минимальная уверенность OCR HP персонажа для live anti-aggro. Ниже этого значения измерение не используется для переключения.",
    "THREAT_TARGET_ACQUIRE_ATTEMPTS": "Сколько попыток anti-aggro делает для захвата новой цели.",
    "THREAT_TARGET_ACQUIRE_TIMEOUT": "Сколько секунд ждать появления валидной цели после команды поиска.",
    "THREAT_TARGET_STABLE_SAMPLES": "Сколько подряд проверок должны подтвердить найденную цель до Attack.",
    "THREAT_TARGET_POLL_INTERVAL": "Интервал проверки появления/стабильности anti-aggro цели.",
    "THREAT_POST_KILL_SWEEP_GATE_TIMEOUT": "Максимальное время ожидания завершения обязательного Sweep перед anti-aggro переключением.",
    "THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES": "Сколько раз подтвердить, что новая текущая цель уже повреждена, прежде чем отменить старый post-death watcher.",
    "THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL": "Интервал между проверками повреждённой цели перед отменой post-death watcher.",
    "THREAT_BASELINE_HINT_MAX_AGE": "Максимальный возраст последнего замера HP до смерти цели, который можно использовать как baseline anti-aggro.",
    "THREAT_HP_SUSPICIOUS_UP_JUMP_ABS": "Абсолютный порог подозрительного резкого скачка OCR HP вверх; используется для защиты от ошибки распознавания.",
    "THREAT_HP_SUSPICIOUS_UP_JUMP_RATIO": "Относительный порог подозрительного скачка OCR HP вверх.",
    "THREAT_ENGAGED_MAX_DURATION": "Сколько максимум хранить anti-aggro цель в состоянии ENGAGED без сброса состояния.",
    "THREAT_ENGAGED_FULL_RECHECK_MIN_AGE": "Минимальный возраст ENGAGED-цели до разрешения повторной проверки full-HP цели.",
    "THREAT_ENGAGED_FULL_RECHECK_MAX_SAMPLE_GAP": "Максимальный разрыв между live HP замерами персонажа для повторной anti-aggro проверки.",
    "OVERLAY_ALPHA": "Прозрачность главного оверлея: 0.0 — невидимый, 1.0 — полностью непрозрачный.",
    "OVERLAY_POSITION_X": "Стартовая X-позиция главного оверлея.",
    "OVERLAY_POSITION_Y": "Стартовая Y-позиция главного оверлея.",
    "HUD_POSITION_X": "Стартовая X-позиция HUD.",
    "HUD_POSITION_Y": "Стартовая Y-позиция HUD.",
    "HUD_ELEMENT_ALPHA": "Прозрачность элементов HUD.",
    "MOB_NAMES": "Список имён мобов, которые используются функцией поиска/подсветки мобов.",
    "MOB_HIGHLIGHT_INTERVAL": "Интервал обновления подсветки/поиска имён мобов.",
    "BUFF_SEQUENCE": "Последовательность F-клавиш, которые нажимаются в цикле бафов.",
    "BUFF_KEY_PRESS_MS": "Длительность удержания клавиши бафа в миллисекундах.",
    "BUFF_CYCLE_INTERVAL": "Интервал между полными циклами бафов в секундах.",
    "CMD": "Словарь команд Arduino. Меняйте только если точно знаете раскладку клавиш/команд прошивки.",
    "BAUD_RATE": "Скорость COM-порта Arduino.",
    "VID": "USB Vendor ID Arduino.",
    "PID": "USB Product ID Arduino.",
}


# Дополнительные настройки anti-aggro, которые могут использоваться кодом через
# defaults и поэтому ещё отсутствовать в config_lu4.py/config_mw.py.
EXTRA_DEFAULTS: Dict[str, Any] = {
    "THREAT_SCENARIO_KILL_ENABLED": True,
    "THREAT_SCENARIO_FULL_HP_ENABLED": True,
    "THREAT_POST_KILL_SWEEP_GATE_TIMEOUT": 5.0,
    "THREAT_NO_TARGET_DECISION_DELAY": 1.0,
    "THREAT_LIVE_FULL_TARGET_DECISION_DELAY": 1.0,
    "THREAT_RETARGET_DECISION_POLL_INTERVAL": 0.05,
    "THREAT_ENGAGED_MAX_DURATION": 60.0,
    "THREAT_LIVE_FULL_TARGET_CLEAR_ATTEMPTS": 2,
    "THREAT_LIVE_FULL_TARGET_CLEAR_TIMEOUT": 0.35,
    "THREAT_TARGET_POLL_INTERVAL": 0.05,
    "THREAT_TARGET_ACQUIRE_ATTEMPTS": 2,
    "THREAT_TARGET_ACQUIRE_TIMEOUT": 0.8,
    "THREAT_TARGET_STABLE_SAMPLES": 2,
    "THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_SAMPLES": 2,
    "THREAT_POST_DEATH_DAMAGED_TARGET_CONFIRM_INTERVAL": 0.05,
    "THREAT_HP_DROP_THRESHOLD_ABS": 4.0,
    "THREAT_HP_DROP_THRESHOLD": 1.0,
    "THREAT_LIVE_FULL_TARGET_MIN_OCR_CONFIDENCE": 70.0,
    "THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD_ABS": 4.0,
    "THREAT_LIVE_FULL_TARGET_DROP_THRESHOLD": 1.0,
    "THREAT_LIVE_FULL_TARGET_DECISION_POLL_INTERVAL": 0.10,
    "THREAT_LIVE_FULL_TARGET_DAMAGED_CONFIRM_SAMPLES": 2,
    "THREAT_LIVE_FULL_TARGET_FINAL_FULL_CONFIRM_SAMPLES": 3,
    "THREAT_ENGAGED_FULL_RECHECK_DROP_THRESHOLD_ABS": 4.0,
    "THREAT_ENGAGED_FULL_RECHECK_MIN_OCR_CONFIDENCE": 70.0,
    "THREAT_ENGAGED_FULL_RECHECK_DROP_THRESHOLD": 1.0,
    "THREAT_ENGAGED_FULL_RECHECK_MAX_SAMPLE_GAP": 1.5,
    "THREAT_ENGAGED_FULL_RECHECK_MIN_AGE": 3.0,
    "THREAT_ENGAGED_FULL_RECHECK_DECISION_DELAY": 1.0,
    "THREAT_ENGAGED_FULL_RECHECK_POLL_INTERVAL": 0.10,
    "THREAT_ENGAGED_FULL_RECHECK_DAMAGED_CONFIRM_SAMPLES": 2,
    "THREAT_ENGAGED_FULL_RECHECK_FINAL_FULL_SAMPLES": 3,
    "THREAT_ENGAGED_FULL_RECHECK_CYCLE_SETTLE": 0.18,
    "THREAT_NO_TARGET_DROP_THRESHOLD_ABS": 4.0,
    "THREAT_NO_TARGET_MIN_OCR_CONFIDENCE": 70.0,
    "THREAT_NO_TARGET_CONFIRM_TOLERANCE_ABS": 2.0,
    "THREAT_NO_TARGET_DROP_THRESHOLD": 1.0,
    "THREAT_NO_TARGET_CONFIRM_SAMPLES": 2,
    "THREAT_NO_TARGET_CONFIRM_INTERVAL": 0.12,
    "THREAT_NO_TARGET_CONFIRM_TIMEOUT": 0.65,
    "THREAT_NO_TARGET_BASELINE_MAX_AGE": 1.5,
    "THREAT_WATCH_EFFECTIVE_MIN_DURATION": 3.0,
    "THREAT_HP_CONFIRM_SAMPLES": 2,
    "THREAT_HP_CONFIRM_TOLERANCE": 1.0,
    "THREAT_BASELINE_HINT_MAX_AGE": 1.25,
    "THREAT_HP_CONFIRM_TOLERANCE_ABS": 2.0,
    "THREAT_HP_SUSPICIOUS_UP_JUMP_ABS": 60.0,
    "THREAT_HP_SUSPICIOUS_UP_JUMP_RATIO": 0.50,
}


@dataclass
class SettingItem:
    name: str
    value: Any
    display_value: str
    configured: bool
    source_comment: str = ""
    section: str = ""
    category: str = "Прочее"
    value_type: str = ""


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 18
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_attributes("-topmost", True)
            tip.configure(bg="#111111")
            label = tk.Label(
                tip,
                text=self.text,
                justify="left",
                bg="#111111",
                fg="#f0f0f0",
                relief="solid",
                borderwidth=1,
                font=("Arial", 9),
                wraplength=520,
                padx=8,
                pady=6,
            )
            label.pack()
            tip.geometry(f"+{x}+{y}")
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def _project_root_from_config(config_module) -> Path:
    config_file = Path(config_module.__file__).resolve()
    # .../KiraSOP/la2_bot/config/config_lu4.py -> .../KiraSOP
    return config_file.parents[2]


def _is_upper_setting_name(name: str) -> bool:
    return bool(name) and name.upper() == name and not name.startswith("_") and re.match(r"^[A-Z][A-Z0-9_]*$", name) is not None


def _value_type_name(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, bytes):
        return "bytes"
    return type(value).__name__


def _display_repr(value: Any) -> str:
    """Однострочное Python-представление для Entry."""
    try:
        text = repr(value)
    except Exception:
        text = str(value)
    return " ".join(text.splitlines())


def _classify_setting(name: str) -> str:
    # Координаты и цвета выше функциональных категорий, чтобы все калибровочные
    # параметры были собраны вместе.
    if name.endswith("_REL") or name.endswith("_POINT") or name.endswith("_RECT") or name.endswith("_AREA") or "COLOR" in name or name.startswith("CANVAS_"):
        return "Координаты и цвета"
    if name == "CMD" or name in {"BAUD_RATE", "VID", "PID"}:
        return "Arduino / команды"
    if name.startswith("THREAT_"):
        return "Антиагр"
    if name.startswith(("SPOIL_", "SKILL_RESET_", "GREEN_PIXEL_")):
        return "Спойл"
    if name.startswith(("LOOT_", "SWEEP_")):
        return "Sweep / лут"
    if name.startswith(("BUFF_", "FLAG_BUFF_")):
        return "Бафы"
    if name.startswith(("OVERLAY_", "HUD_")):
        return "Интерфейс"
    if name.startswith(("DOUBLE_CLICK_", "LCLICK_")):
        return "Клики"
    if name.startswith(("MOB_", "NAME_SEARCH_")):
        return "Поиск мобов"
    if name.startswith("FLAG_"):
        return "Флаги / кнопки"
    if name.startswith(("TARGET_", "NEXT_TARGET_", "RETURN_TO_TARGET_", "STUCK_TARGET_", "HP1_MONSTER_")):
        return "Цели"
    if name.startswith(("POTION_", "MP_SKILL_", "ATTACK_", "CHAR_HP_", "CHAR_MP_", "HP_", "MP_")):
        return "Бой / HP / MP"
    return "Основные / прочее"


def _section_for_line(lines: List[str], lineno: int) -> str:
    """Ищет ближайший предыдущий комментарий вида '# ----- ... -----'."""
    for idx in range(max(0, lineno - 2), -1, -1):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            clean = stripped.lstrip("#").strip().strip("-").strip()
            if clean and ("настрой" in clean.lower() or "конфиг" in clean.lower() or "координ" in clean.lower() or "интервал" in clean.lower() or "поиск" in clean.lower() or "цвет" in clean.lower() or "команд" in clean.lower() or "hud" in clean.lower() or "баф" in clean.lower() or "оверле" in clean.lower()):
                return clean
            continue
        break
    return ""


def _inline_comment_for_node(lines: List[str], node: ast.AST) -> str:
    try:
        end_line = getattr(node, "end_lineno", getattr(node, "lineno", 1))
        line = lines[end_line - 1]
        end_col = getattr(node, "end_col_offset", len(line))
        tail = line[end_col:]
        if "#" in tail:
            return tail.split("#", 1)[1].strip()
    except Exception:
        pass
    return ""


def _extract_configured_items(config_module) -> Tuple[List[SettingItem], str, ast.Module]:
    path = Path(config_module.__file__).resolve()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    items: List[SettingItem] = []

    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id

        if not name or not _is_upper_setting_name(name):
            continue

        try:
            value = getattr(config_module, name)
        except Exception:
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue

        section = _section_for_line(lines, getattr(node, "lineno", 1))
        comment = _inline_comment_for_node(lines, node)
        items.append(
            SettingItem(
                name=name,
                value=value,
                display_value=_display_repr(value),
                configured=True,
                source_comment=comment,
                section=section,
                category=_classify_setting(name),
                value_type=_value_type_name(value),
            )
        )

    return items, source, tree


def _literal_default(node: ast.AST) -> Tuple[bool, Any]:
    try:
        return True, ast.literal_eval(node)
    except Exception:
        return False, None


def _discover_optional_settings(project_root: Path) -> Dict[str, Any]:
    """Ищет параметры, которые код читает через default, но которых может не быть в config."""
    result: Dict[str, Any] = dict(EXTRA_DEFAULTS)
    source_root = project_root / "la2_bot"
    if not source_root.exists():
        return result

    for py_path in source_root.rglob("*.py"):
        # __pycache__ и сгенерированные/временные файлы неинтересны.
        if "__pycache__" in py_path.parts:
            continue
        try:
            text = py_path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(py_path))
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # getattr(config, 'NAME', default)
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 3:
                obj, key_node, default_node = node.args[:3]
                if isinstance(obj, ast.Name) and obj.id == "config" and isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    name = key_node.value
                    if _is_upper_setting_name(name):
                        ok, value = _literal_default(default_node)
                        if ok:
                            result.setdefault(name, value)

            # _cfg_float('NAME', default), _cfg_int(...), _cfg_bool(...), etc.
            func_name = node.func.id if isinstance(node.func, ast.Name) else ""
            if func_name.startswith("_cfg_") and len(node.args) >= 2:
                key_node, default_node = node.args[:2]
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    name = key_node.value
                    if _is_upper_setting_name(name):
                        ok, value = _literal_default(default_node)
                        if ok:
                            result.setdefault(name, value)

    return result


def _tooltip_text(item: SettingItem) -> str:
    parts: List[str] = []
    if item.name in DESCRIPTIONS:
        parts.append(DESCRIPTIONS[item.name])
    elif item.source_comment:
        parts.append(item.source_comment)
    elif item.section:
        parts.append(f"Параметр раздела «{item.section}».")
    else:
        parts.append(f"Настраиваемый параметр {item.name} активного клиента.")

    if item.source_comment and item.name in DESCRIPTIONS and item.source_comment.lower() not in DESCRIPTIONS[item.name].lower():
        parts.append(f"Комментарий конфига: {item.source_comment}")
    if item.section:
        parts.append(f"Раздел: {item.section}.")
    parts.append(f"Тип значения: {item.value_type}.")
    if not item.configured:
        parts.append("Сейчас параметр не записан в config-файл: используется значение по умолчанию из кода. Если изменить его и нажать «Сохранить», он будет добавлен в активный config_*.py.")
    return "\n".join(parts)


def _parse_user_value(text: str, old_value: Any) -> Any:
    raw = text.strip()
    if not raw:
        raise ValueError("пустое значение")

    # Основной путь — только безопасные Python literals.
    try:
        value = ast.literal_eval(raw)
    except Exception:
        # Для строк разрешаем ввод без кавычек, чтобы GAME_EXE_NAME и подписи
        # было удобно редактировать. Для остальных типов это считается ошибкой.
        if isinstance(old_value, str):
            value = raw
        else:
            raise ValueError("используйте Python-формат: 1.0, True, (1, 2), ['F1'], {'KEY': b'5\\n'}")

    # Мягкая проверка типа: int -> float разрешаем и наоборот, когда безопасно.
    if old_value is not None:
        if isinstance(old_value, bool) and not isinstance(value, bool):
            raise ValueError("ожидается True или False")
        if isinstance(old_value, int) and not isinstance(old_value, bool):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            elif not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("ожидается целое число")
        elif isinstance(old_value, float):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value)
            else:
                raise ValueError("ожидается число")
        elif isinstance(old_value, tuple) and not isinstance(value, tuple):
            raise ValueError("ожидается tuple, например (100, 200)")
        elif isinstance(old_value, list) and not isinstance(value, list):
            raise ValueError("ожидается list, например ['F1', 'F2']")
        elif isinstance(old_value, dict) and not isinstance(value, dict):
            raise ValueError("ожидается словарь {...}")
        elif isinstance(old_value, bytes) and not isinstance(value, bytes):
            raise ValueError("ожидается bytes, например b'5\\n'")
    return value


def _repr_for_source(value: Any) -> str:
    # pprint здесь не используем: однострочный repr проще и безопаснее для
    # автоматической замены выражения в существующем source.
    return repr(value)


def _node_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _source_offsets(source: str) -> List[int]:
    offsets = [0]
    for match in re.finditer(r"\n", source):
        offsets.append(match.end())
    return offsets


def _replace_config_values(source: str, changes: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Заменяет только выражения существующих top-level assignments; новые добавляет в конец."""
    tree = ast.parse(source)
    offsets = _source_offsets(source)
    existing_nodes: Dict[str, ast.AST] = {}
    for node in tree.body:
        name = _node_name(node)
        if name and _is_upper_setting_name(name):
            existing_nodes[name] = node

    replacements: List[Tuple[int, int, str]] = []
    appended: List[str] = []

    for name, value in changes.items():
        node = existing_nodes.get(name)
        new_expr = _repr_for_source(value)
        if node is None:
            appended.append(f"{name} = {new_expr}")
            continue

        value_node = getattr(node, "value", None)
        if value_node is None:
            continue
        start = offsets[value_node.lineno - 1] + value_node.col_offset
        end = offsets[value_node.end_lineno - 1] + value_node.end_col_offset
        replacements.append((start, end, new_expr))

    result = source
    for start, end, text in sorted(replacements, key=lambda x: x[0], reverse=True):
        result = result[:start] + text + result[end:]

    if appended:
        if not result.endswith("\n"):
            result += "\n"
        result += "\n# ----- Настройки, добавленные через панель «Конфиг» -----\n"
        result += "\n".join(appended) + "\n"

    return result, [line.split("=", 1)[0].strip() for line in appended]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


def _backup_config(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.backup_{stamp}")
    shutil.copy2(path, backup)
    return backup


def _apply_runtime(config_module, changes: Dict[str, Any]) -> None:
    coordinate_related = False
    for name, value in changes.items():
        try:
            setattr(config_module, name, value)
        except Exception:
            continue
        if name.endswith("_REL") or "POINT" in name or "RECT" in name or "AREA" in name or name.startswith("CANVAS_"):
            coordinate_related = True

    if coordinate_related:
        try:
            from la2_bot.utils import coordinate_utils
            coordinate_utils.clear_coordinate_cache()
        except Exception:
            pass


def save_config_values(changes: Dict[str, Any], *, create_backup: bool = True):
    """Сохраняет несколько значений в активный config_*.py и применяет их runtime.

    Используется не только окном «Конфиг», но и быстрыми переключателями
    на оверлее. Новые UPPER_CASE переменные автоматически добавляются в конец
    активного config_lu4.py/config_mw.py.
    """
    if not changes:
        return None

    config_module = get_config()
    config_path = Path(config_module.__file__).resolve()
    source = config_path.read_text(encoding="utf-8")
    new_source, _appended = _replace_config_values(source, changes)
    ast.parse(new_source, filename=str(config_path))

    backup = _backup_config(config_path) if create_backup else None
    _atomic_write(config_path, new_source)
    _apply_runtime(config_module, changes)
    return backup


class ConfigPanel:
    BG = "#171717"
    PANEL_BG = "#202020"
    ROW_BG = "#262626"
    ROW_CHANGED_BG = "#463c16"
    FG = "#f0f0f0"
    MUTED = "#a8a8a8"
    ACCENT = "#6b8e23"

    def __init__(self, parent: tk.Misc, client_name: Optional[str] = None):
        self.parent = parent
        self.client_name = client_name or get_client_name()
        self.config_module = get_config()
        self.config_path = Path(self.config_module.__file__).resolve()
        self.project_root = _project_root_from_config(self.config_module)

        self.root = tk.Toplevel(parent)
        self.root.title(f"Настройка конфига — {self.client_name}")
        self.root.geometry("980x720")
        self.root.minsize(780, 520)
        self.root.configure(bg=self.BG)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        self.items: List[SettingItem] = []
        self.item_by_name: Dict[str, SettingItem] = {}
        self.vars: Dict[str, tk.StringVar] = {}
        self.original_text: Dict[str, str] = {}
        self.row_frames: Dict[str, tk.Frame] = {}
        self.row_widgets: Dict[str, Tuple[tk.Label, tk.Entry, tk.Label]] = {}
        self._tooltips: List[ToolTip] = []

        self.search_var = tk.StringVar()
        self.category_var = tk.StringVar(value="Все")
        self.status_var = tk.StringVar(value="")

        self._build_ui()
        self.reload()

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(
            header,
            text="Настройка конфига",
            font=("Arial", 15, "bold"),
            bg=self.BG,
            fg=self.FG,
        ).pack(side="left")

        self.client_label = tk.Label(
            header,
            text=f"Клиент: {self.client_name}",
            font=("Arial", 9),
            bg=self.BG,
            fg="#9fd3ff",
        )
        self.client_label.pack(side="left", padx=(12, 0))

        controls = tk.Frame(self.root, bg=self.PANEL_BG)
        controls.pack(fill="x", padx=10, pady=(0, 6))

        tk.Label(controls, text="Поиск:", bg=self.PANEL_BG, fg=self.FG).pack(side="left", padx=(8, 4), pady=7)
        search_entry = tk.Entry(controls, textvariable=self.search_var, width=28, bg="#111111", fg=self.FG, insertbackground="white")
        search_entry.pack(side="left", pady=7)
        self.search_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(controls, text="Раздел:", bg=self.PANEL_BG, fg=self.FG).pack(side="left", padx=(14, 4))
        self.category_combo = ttk.Combobox(controls, textvariable=self.category_var, state="readonly", width=24)
        self.category_combo.pack(side="left")
        self.category_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())

        tk.Label(
            controls,
            text="Наведи курсор на название параметра — появится подсказка",
            bg=self.PANEL_BG,
            fg=self.MUTED,
            font=("Arial", 8),
        ).pack(side="right", padx=8)

        table_header = tk.Frame(self.root, bg="#101010")
        table_header.pack(fill="x", padx=10)
        tk.Label(table_header, text="Параметр", width=38, anchor="w", bg="#101010", fg="#cccccc", font=("Arial", 9, "bold")).pack(side="left", padx=(6, 0), pady=5)
        tk.Label(table_header, text="Значение", anchor="w", bg="#101010", fg="#cccccc", font=("Arial", 9, "bold")).pack(side="left", fill="x", expand=True, padx=(4, 0))
        tk.Label(table_header, text="Тип", width=10, anchor="w", bg="#101010", fg="#cccccc", font=("Arial", 9, "bold")).pack(side="right", padx=(0, 6))

        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.canvas = tk.Canvas(body, bg=self.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=self.BG)
        self.inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        footer = tk.Frame(self.root, bg=self.PANEL_BG)
        footer.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(
            footer,
            text="Сохранить",
            width=14,
            bg="#315a31",
            fg="white",
            font=("Arial", 9, "bold"),
            command=self.save,
        ).pack(side="left", padx=(8, 4), pady=8)

        tk.Button(
            footer,
            text="Перечитать",
            width=14,
            bg="#444444",
            fg="white",
            command=self.reload,
        ).pack(side="left", padx=4)

        tk.Button(
            footer,
            text="Закрыть",
            width=12,
            bg="#5a3131",
            fg="white",
            command=self.stop,
        ).pack(side="right", padx=8)

        tk.Label(
            footer,
            textvariable=self.status_var,
            anchor="w",
            bg=self.PANEL_BG,
            fg="#d8d8d8",
            font=("Arial", 8),
        ).pack(side="left", fill="x", expand=True, padx=10)

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_window, width=event.width)

    def _on_mousewheel(self, event):
        try:
            if self.root.winfo_exists() and self.root.focus_displayof() is not None:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _clear_rows(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.vars.clear()
        self.original_text.clear()
        self.row_frames.clear()
        self.row_widgets.clear()
        self._tooltips.clear()

    def _load_items(self) -> List[SettingItem]:
        configured_items, _source, _tree = _extract_configured_items(self.config_module)
        configured_names = {item.name for item in configured_items}

        optional = _discover_optional_settings(self.project_root)
        extra_items: List[SettingItem] = []
        for name, default in optional.items():
            if name in configured_names or not _is_upper_setting_name(name):
                continue
            try:
                runtime_value = getattr(self.config_module, name)
                value = runtime_value
            except Exception:
                value = default
            extra_items.append(
                SettingItem(
                    name=name,
                    value=value,
                    display_value=_display_repr(value),
                    configured=False,
                    source_comment="",
                    section="Опциональные параметры, найденные в коде",
                    category=_classify_setting(name),
                    value_type=_value_type_name(value),
                )
            )

        items = configured_items + extra_items
        category_order = {
            "Основные / прочее": 0,
            "Бой / HP / MP": 1,
            "Цели": 2,
            "Антиагр": 3,
            "Спойл": 4,
            "Sweep / лут": 5,
            "Бафы": 6,
            "Поиск мобов": 7,
            "Клики": 8,
            "Флаги / кнопки": 9,
            "Интерфейс": 10,
            "Координаты и цвета": 11,
            "Arduino / команды": 12,
        }
        items.sort(key=lambda x: (category_order.get(x.category, 99), x.name))
        return items

    def reload(self):
        try:
            # get_config() может смениться, если ConfigManager переключил клиент.
            self.client_name = get_client_name()
            self.config_module = get_config()
            self.config_path = Path(self.config_module.__file__).resolve()
            self.project_root = _project_root_from_config(self.config_module)
            self.client_label.config(text=f"Клиент: {self.client_name}")

            self.items = self._load_items()
            self.item_by_name = {item.name: item for item in self.items}
            self._clear_rows()

            categories = ["Все"] + sorted({item.category for item in self.items})
            self.category_combo["values"] = categories
            if self.category_var.get() not in categories:
                self.category_var.set("Все")

            last_category = None
            for item in self.items:
                if item.category != last_category:
                    section_frame = tk.Frame(self.inner, bg="#111111")
                    section_frame.pack(fill="x", pady=(7 if last_category is not None else 0, 2))
                    tk.Label(
                        section_frame,
                        text=item.category,
                        anchor="w",
                        bg="#111111",
                        fg="#9fd3ff",
                        font=("Arial", 10, "bold"),
                        padx=7,
                        pady=4,
                    ).pack(fill="x")
                    section_frame._config_category = item.category  # type: ignore[attr-defined]
                    last_category = item.category

                row = tk.Frame(self.inner, bg=self.ROW_BG)
                row.pack(fill="x", pady=1)
                row._config_category = item.category  # type: ignore[attr-defined]
                self.row_frames[item.name] = row

                name_text = item.name + ("  •" if not item.configured else "")
                name_label = tk.Label(
                    row,
                    text=name_text,
                    width=38,
                    anchor="w",
                    bg=self.ROW_BG,
                    fg="#ffe7a3" if not item.configured else self.FG,
                    font=("Consolas", 9),
                    cursor="question_arrow",
                    padx=6,
                )
                name_label.pack(side="left", pady=4)

                value_var = tk.StringVar(value=item.display_value)
                self.vars[item.name] = value_var
                self.original_text[item.name] = item.display_value

                type_label = tk.Label(
                    row,
                    text=item.value_type,
                    width=10,
                    anchor="w",
                    bg=self.ROW_BG,
                    fg=self.MUTED,
                    font=("Arial", 8),
                    padx=4,
                )
                type_label.pack(side="right", pady=4)

                entry = tk.Entry(
                    row,
                    textvariable=value_var,
                    bg="#111111",
                    fg="white",
                    insertbackground="white",
                    relief="flat",
                    font=("Consolas", 9),
                )
                entry.pack(side="left", fill="x", expand=True, padx=(4, 2), pady=4)

                self.row_widgets[item.name] = (name_label, entry, type_label)
                self._tooltips.append(ToolTip(name_label, _tooltip_text(item)))
                value_var.trace_add("write", lambda *_args, n=item.name: self._mark_changed(n))

            self.status_var.set(
                f"{self.config_path.name}: {len(self.items)} параметров.  • = параметр пока использует default из кода."
            )
            self._apply_filter()
        except Exception as exc:
            self.status_var.set(f"Ошибка чтения конфига: {exc}")
            messagebox.showerror("Конфиг", f"Не удалось прочитать активный конфиг:\n{exc}", parent=self.root)

    def _mark_changed(self, name: str):
        row = self.row_frames.get(name)
        widgets = self.row_widgets.get(name)
        var = self.vars.get(name)
        if row is None or widgets is None or var is None:
            return
        changed = var.get().strip() != self.original_text.get(name, "").strip()
        bg = self.ROW_CHANGED_BG if changed else self.ROW_BG
        try:
            row.configure(bg=bg)
            widgets[0].configure(bg=bg)
            widgets[2].configure(bg=bg)
        except Exception:
            pass

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        category = self.category_var.get()

        # Сначала строки.
        visible_categories = set()
        for item in self.items:
            row = self.row_frames.get(item.name)
            if row is None:
                continue
            haystack = f"{item.name} {item.category} {_tooltip_text(item)}".lower()
            show = (not query or query in haystack) and (category == "Все" or item.category == category)
            if show:
                row.pack(fill="x", pady=1)
                visible_categories.add(item.category)
            else:
                row.pack_forget()

        # Заголовки категорий — это остальные дети inner с _config_category.
        for child in self.inner.winfo_children():
            cat = getattr(child, "_config_category", None)
            if cat and child not in self.row_frames.values():
                if cat in visible_categories:
                    first_row = self._first_visible_row_for_category(cat)
                    if first_row is not None:
                        child.pack(fill="x", pady=(7, 2), before=first_row)
                    else:
                        child.pack(fill="x", pady=(7, 2))
                else:
                    child.pack_forget()

    def _first_visible_row_for_category(self, category: str):
        for item in self.items:
            if item.category == category:
                row = self.row_frames.get(item.name)
                if row is not None and row.winfo_manager():
                    return row
        return None

    def _collect_changes(self) -> Tuple[Dict[str, Any], List[str]]:
        changes: Dict[str, Any] = {}
        errors: List[str] = []
        for item in self.items:
            var = self.vars.get(item.name)
            if var is None:
                continue
            current_text = var.get().strip()
            original_text = self.original_text.get(item.name, "").strip()
            if current_text == original_text:
                continue
            try:
                changes[item.name] = _parse_user_value(current_text, item.value)
            except Exception as exc:
                errors.append(f"{item.name}: {exc}")
        return changes, errors

    def save(self):
        changes, errors = self._collect_changes()
        if errors:
            messagebox.showerror(
                "Ошибка значения",
                "Исправь значения:\n\n" + "\n".join(errors[:12]),
                parent=self.root,
            )
            return
        if not changes:
            self.status_var.set("Изменений нет.")
            return

        try:
            source_before = self.config_path.read_text(encoding="utf-8")
            _new_source, appended = _replace_config_values(source_before, changes)
            backup = save_config_values(changes, create_backup=True)

            names = ", ".join(changes.keys())
            extra = f"; добавлено новых: {len(appended)}" if appended else ""
            backup_name = backup.name if backup is not None else "нет"
            self.status_var.set(
                f"Сохранено {len(changes)} параметров{extra}. Backup: {backup_name}. Часть настроек интерфейса требует перезапуска."
            )
            print(f"[ConfigPanel] Сохранены настройки: {names}. Backup: {backup}")

            # Перечитываем, чтобы новые optional-параметры стали обычными configured.
            self.reload()
        except Exception as exc:
            self.status_var.set(f"Ошибка сохранения: {exc}")
            messagebox.showerror(
                "Конфиг",
                f"Не удалось сохранить конфиг. Исходный файл не должен быть повреждён.\n\n{exc}",
                parent=self.root,
            )

    def focus(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def stop(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def create_config_panel(parent: tk.Misc, client_name: Optional[str] = None) -> ConfigPanel:
    return ConfigPanel(parent, client_name=client_name)
