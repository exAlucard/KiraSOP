# main.py
# Прямая замена для exAlucard/KiraSOP.
# Добавляет кнопку «ПВПмод» в основной оверлей.
# В ПВП-режиме периодическая ATTACK отправляется без проверки HP цели,
# TARGET_SELECTED_POINT / TARGET_MOB_POINT2 и без блокировки приоритетом спойла.

import random
import threading
import time
import tkinter as tk

from la2_bot.config import initialize_config
from la2_bot.core.log_buffer import install_stdout_capture


install_stdout_capture()

print("[main] Инициализация конфигурации...")
initialize_config()
print("[main] Конфигурация инициализирована.")

from la2_bot.config import config
from la2_bot.config.config_manager import get_client_name
import la2_bot.config.hud_settings as hud_settings
from la2_bot.core.state import pause_event
import la2_bot.ui.bot_menu as bot_menu


# ---------------------------------------------------------------------------
# PVP MODE: общий флаг интерфейса
# ---------------------------------------------------------------------------
# Ключ добавляется ДО create_pause_overlay(), поэтому штатная загрузка
# сохранённых состояний кнопок сама подхватит pvp_mode из hud_settings.
bot_menu.bot_flags.setdefault("pvp_mode", False)


# Сохраняем штатную функцию, чтобы при выключенном ПВП-режиме поведение проекта
# оставалось полностью прежним.
_original_is_flag_enabled = bot_menu.is_flag_enabled


def _pvp_aware_is_flag_enabled(flag_name):
    """Флаги, которые в ПВП-режиме должны игнорировать mob-проверки."""
    pvp_enabled = bool(bot_menu.bot_flags.get("pvp_mode", False))

    if pvp_enabled:
        # is_target_selected() при выключенном target_mob возвращает True,
        # поэтому TARGET_SELECTED_POINT / TARGET_MOB_POINT2 не блокируют игрока.
        if flag_name == "target_mob":
            return False

        # В ПВП не отбрасываем уже повреждённую цель как «неподходящую».
        if flag_name == "skip_damaged_target":
            return False

    return _original_is_flag_enabled(flag_name)


# Подменяем функцию до импорта combat/engine/targeting, чтобы все модули,
# импортирующие is_flag_enabled, получили PVP-aware вариант.
bot_menu.is_flag_enabled = _pvp_aware_is_flag_enabled

# target_utils иногда может оказаться уже загружен косвенным импортом UI-модулей.
# Явно обновляем его ссылку, чтобы is_target_selected() точно видел ПВП-режим.
import la2_bot.utils.target_utils as target_utils
target_utils.is_flag_enabled = _pvp_aware_is_flag_enabled


# ---------------------------------------------------------------------------
# PVP MODE: отдельная логика периодической атаки
# ---------------------------------------------------------------------------
import la2_bot.actions.combat as combat

_original_periodic_attack_if_needed = combat.periodic_attack_if_needed


def _periodic_attack_if_needed_with_pvp(ser, last_attack_time):
    """
    Обычный режим: вызывается оригинальная функция проекта без изменений.

    ПВПмод ON: ATTACK отправляется по штатному ATTACK_INTERVAL_MIN/MAX,
    но БЕЗ любых проверок:
      - TARGET_HP_1_POINT;
      - TARGET_HP_FULL_POINT;
      - TARGET_SELECTED_POINT / TARGET_MOB_POINT2;
      - is_spoil_priority_pending().
    """
    if not bot_menu.bot_flags.get("pvp_mode", False):
        return _original_periodic_attack_if_needed(ser, last_attack_time)

    now = time.time()

    try:
        interval_min = float(getattr(config, "ATTACK_INTERVAL_MIN", 6.0))
        interval_max = float(getattr(config, "ATTACK_INTERVAL_MAX", 8.0))
    except (TypeError, ValueError):
        interval_min, interval_max = 6.0, 8.0

    if interval_min > interval_max:
        interval_min, interval_max = interval_max, interval_min

    interval_min = max(0.05, interval_min)
    interval_max = max(interval_min, interval_max)
    current_interval = random.uniform(interval_min, interval_max)

    if now - last_attack_time < current_interval:
        return last_attack_time

    print(
        f"[ПВПмод] ATTACK без проверки пикселя "
        f"(интервал {current_interval:.2f} сек)."
    )
    combat.send_command(ser, "ATTACK")
    return time.time()


combat.periodic_attack_if_needed = _periodic_attack_if_needed_with_pvp


# Импортируем engine только после патчей выше: так его локальная ссылка
# periodic_attack_if_needed уже указывает на PVP-aware функцию.
import la2_bot.core.engine as engine


# В штатном engine периодическая атака вызывается только когда next_target ON.
# Для ПВП-режима делаем исключение ТОЛЬКО внутри engine, чтобы кнопка «ПВПмод»
# сама включала боевой тик даже при /target OFF. При этом targeting.py продолжает
# уважать реальное состояние /target и не начинает самовольно спамить 5/6.
_engine_original_is_flag_enabled = engine.is_flag_enabled


def _engine_pvp_is_flag_enabled(flag_name):
    if flag_name == "next_target" and bot_menu.bot_flags.get("pvp_mode", False):
        return True
    return _pvp_aware_is_flag_enabled(flag_name)


engine.is_flag_enabled = _engine_pvp_is_flag_enabled

# На случай, если targeting был закеширован раньше, также обновляем его
# модульную ссылку на PVP-aware проверку флагов.
try:
    import la2_bot.actions.targeting as targeting
    targeting.is_flag_enabled = _pvp_aware_is_flag_enabled
except Exception:
    pass


# ---------------------------------------------------------------------------
# PVP MODE: кнопка на основном оверлее
# ---------------------------------------------------------------------------
def _find_main_flags_frame(root):
    """Находит штатный flags_frame; при неудаче кнопка добавится прямо в root."""
    for child in root.winfo_children():
        if isinstance(child, tk.Frame):
            try:
                if child.cget("bg") == "#222222":
                    return child
            except Exception:
                pass
    return root


def _add_pvp_button(root):
    parent = _find_main_flags_frame(root)

    button = tk.Button(
        parent,
        font=("Arial", 9, "bold"),
        width=25,
    )

    def refresh_style():
        enabled = bool(bot_menu.bot_flags.get("pvp_mode", False))
        if enabled:
            button.config(
                text="ПВПмод ON",
                bg="#004400",
                fg="white",
                relief="raised",
            )
        else:
            button.config(
                text="ПВПмод OFF",
                bg="#440000",
                fg="lightgray",
                relief="ridge",
            )

    def toggle_pvp_mode():
        new_value = not bool(bot_menu.bot_flags.get("pvp_mode", False))
        bot_menu.bot_flags["pvp_mode"] = new_value

        try:
            hud_settings.save_button_state(
                "pvp_mode",
                new_value,
                get_client_name(),
            )
        except Exception as exc:
            print(f"[ПВПмод] Не удалось сохранить состояние кнопки: {exc}")

        refresh_style()

        if new_value:
            print(
                "[ПВПмод] ON: ATTACK теперь не требует подтверждения "
                "TARGET_SELECTED_POINT/TARGET_MOB_POINT2 и HP-пикселей."
            )
        else:
            print("[ПВПмод] OFF: восстановлена штатная логика атаки.")

    button.config(command=toggle_pvp_mode)
    button.pack(side=tk.TOP, anchor="w", pady=(0, 2))
    refresh_style()
    return button


def main():
    root = tk.Tk()

    # Сначала создаём оверлей: он загрузит сохранённое pvp_mode, потому что ключ
    # уже добавлен в bot_menu.bot_flags выше.
    bot_menu.create_pause_overlay(root, pause_event, hud_settings)
    _add_pvp_button(root)

    threading.Thread(
        target=engine.bot_loop,
        args=(pause_event,),
        daemon=True,
        name="bot-loop",
    ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
