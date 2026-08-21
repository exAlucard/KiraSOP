# la2_bot/ui/bot_menu.py

import tkinter as tk

import win32con
import win32gui

from la2_bot.config import config
from la2_bot.ui.hud import create_hud
from la2_bot.ui.debug_overlay import create_debug_overlay
from la2_bot.ui.log_window import create_log_window
from la2_bot.ui.config_panel import create_config_panel, save_config_values
import la2_bot.config.hud_settings
from la2_bot.config.config_manager import get_client_name, get_config
from la2_bot.features import always_assist
from la2_bot.detection import flagstop_mode


OVERLAY_ALPHA = config.OVERLAY_ALPHA
OVERLAY_POSITION_X = config.OVERLAY_POSITION_X
OVERLAY_POSITION_Y = config.OVERLAY_POSITION_Y


bot_flags = {
    'potion': config.FLAG_POTION_ENABLED,
    'mp_skill': config.FLAG_MP_SKILL_ENABLED,
    'next_target': config.FLAG_NEXT_TARGET_ENABLED,
    'mob_search': config.FLAG_MOB_SEARCH_ENABLED,
    'double_click': config.FLAG_DOUBLE_CLICK_ENABLED,
    'target_mob': True,
    'return_to_target': config.FLAG_RETURN_TO_TARGET_ENABLED,
    'stuck_target': config.FLAG_STUCK_TARGET_ENABLED,
    'skip_damaged_target': True,

    # Внутренний master-флаг. Реальное состояние вычисляется как OR двух сценариев ниже.
    'anti_agr': True,
    'anti_agr_kill': bool(getattr(config, 'THREAT_SCENARIO_KILL_ENABLED', True)),
    'anti_agr_full_hp': bool(getattr(config, 'THREAT_SCENARIO_FULL_HP_ENABLED', True)),
    'anti_coin': False,
    'target_count_mode': 1,

    # Быстрый обычный поиск цели кнопками 5 / 6.
    'rapid_target_search': False,

    'altheal': False,
    'buffs': False,
    'heal': False,
    'altds': False,
    'flip': False,
    'vkatak': False,
    'stuck': False,
    'anti_no_target': False,
    'poke': False,
    'always_assist': False,
}


def create_pause_overlay(root, pause_event, hud_settings_module):
    global bot_flags

    current_client_name = get_client_name()

    loaded_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
    loaded_button_states = la2_bot.config.hud_settings.load_button_states(current_client_name)

    heal_interval_seconds = loaded_settings.get("heal_interval_seconds", 15.0)
    loot_repeat_count = loaded_settings.get(
        "loot_repeat_count",
        getattr(config, 'LOOT_REPEAT_COUNT', 3),
    )
    buff_cycle_interval = loaded_settings.get(
        "buff_cycle_interval",
        getattr(config, 'BUFF_CYCLE_INTERVAL', 60.0),
    )

    for key, value in loaded_button_states.items():
        if key in bot_flags:
            bot_flags[key] = value

    # Два независимых сценария anti-aggro живут в активном config_*.py.
    scenario_defaults = {
        'THREAT_SCENARIO_KILL_ENABLED': True,
        'THREAT_SCENARIO_FULL_HP_ENABLED': True,
    }
    missing_scenarios = {
        name: default
        for name, default in scenario_defaults.items()
        if not hasattr(config, name)
    }
    if missing_scenarios:
        try:
            save_config_values(missing_scenarios, create_backup=False)
        except Exception as exc:
            print(f"[Overlay] Не удалось добавить anti-aggro scenario defaults в конфиг: {exc}")

    bot_flags['anti_agr_kill'] = bool(
        getattr(config, 'THREAT_SCENARIO_KILL_ENABLED', True)
    )
    bot_flags['anti_agr_full_hp'] = bool(
        getattr(config, 'THREAT_SCENARIO_FULL_HP_ENABLED', True)
    )
    bot_flags['anti_agr'] = bool(
        bot_flags['anti_agr_kill'] or bot_flags['anti_agr_full_hp']
    )

    flagstop_saved_enabled = loaded_button_states.get('flagstop_mode', False)

    if bot_flags.get('always_assist') and pause_event.is_set():
        always_assist.start()

    hud_instance = None
    debug_instance = None
    logs_instance = None
    config_instance = None
    old_buttons_window = None
    flagstop_button = None

    button_width = 25

    def toggle_hud():
        nonlocal hud_instance
        if hud_instance is None or not tk.Toplevel.winfo_exists(hud_instance.root):
            hud_instance = create_hud(
                root,
                pause_event,
                hud_settings_module,
                current_client_name,
            )
            hud_instance.start()
            hud_instance.toggle_visibility()
        else:
            hud_instance.toggle_visibility()

    def toggle_pause():
        state = pause_button.cget('text')
        if state in ("Start", "Pause"):
            pause_event.set()
            pause_button.config(text="Playing", bg="green", fg="white")

            if bot_flags.get('always_assist'):
                always_assist.start()
        else:
            pause_event.clear()
            pause_button.config(text="Pause", bg="red", fg="white")
            always_assist.stop()

    def toggle_flag(flag_key, button_widget):
        bot_flags[flag_key] = not bot_flags[flag_key]
        la2_bot.config.hud_settings.save_button_state(
            flag_key,
            bot_flags[flag_key],
            current_client_name,
        )
        update_flag_button_style(flag_key, button_widget)

        if flag_key == 'always_assist':
            if bot_flags[flag_key]:
                if pause_event.is_set():
                    always_assist.start()
            else:
                always_assist.stop()

    def update_flag_button_style(flag_key, button_widget):
        flag_text_map = {
            'potion': f"{config.FLAG_BUTTON_TEXT_POTION} (9)",
            'mp_skill': f"{config.FLAG_BUTTON_TEXT_MP_SKILL} (8)",
            'next_target': f"{config.FLAG_BUTTON_TEXT_NEXT_TARGET} (5)",
            'mob_search': config.FLAG_BUTTON_TEXT_MOB_SEARCH,
            'double_click': config.FLAG_BUTTON_TEXT_DOUBLE_CLICK,
            'target_mob': "Таргет - моб",
            'return_to_target': f"{config.FLAG_BUTTON_TEXT_RETURN_TO_TARGET} (0)",
            'stuck_target': config.FLAG_BUTTON_TEXT_STUCK_TARGET,
            'skip_damaged_target': "Пропускать раненных",
            'anti_coin': "Антимонетка (W)",
            'anti_agr': "Антиагр",
            'anti_agr_kill': "Антиагр кил",
            'anti_agr_full_hp': "Антиагр фул хп",
            'rapid_target_search': "Поиск цели x10",
            'altheal': "Альтхил",
            'buffs': getattr(config, 'FLAG_BUTTON_TEXT_BUFF', 'Бафы'),
            'heal': "Хил",
            'altds': "АльтДС",
            'flip': "Флип",
            'vkatak': "ВКатак",
            'stuck': "Stuck",
            'anti_no_target': "АнтиНоТаргет (-)",
            'poke': "Подпинывание",
            'always_assist': "ВсегдаАсист",
        }

        is_enabled = bot_flags[flag_key]
        base_text = flag_text_map.get(flag_key, flag_key.capitalize())

        if is_enabled:
            button_widget.config(
                bg="#004400",
                fg="white",
                relief="raised",
                text=f"{base_text} ON",
            )
        else:
            button_widget.config(
                bg="#440000",
                fg="lightgray",
                relief="ridge",
                text=f"{base_text} OFF",
            )

    def make_flag_button(parent, flag_key, *, bold=False):
        btn = tk.Button(
            parent,
            font=("Arial", 9, "bold") if bold else ("Arial", 9),
            width=button_width,
        )
        btn.config(command=lambda b=btn, k=flag_key: toggle_flag(k, b))
        btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
        update_flag_button_style(flag_key, btn)
        return btn

    def _sync_antiaggro_scenario_flags():
        kill_enabled = bool(
            getattr(config, 'THREAT_SCENARIO_KILL_ENABLED', True)
        )
        full_enabled = bool(
            getattr(config, 'THREAT_SCENARIO_FULL_HP_ENABLED', True)
        )
        bot_flags['anti_agr_kill'] = kill_enabled
        bot_flags['anti_agr_full_hp'] = full_enabled
        bot_flags['anti_agr'] = bool(kill_enabled or full_enabled)
        return kill_enabled, full_enabled

    def toggle_antiaggro_scenario(flag_key, config_name, button_widget):
        current = bool(
            bot_flags.get(flag_key, getattr(config, config_name, True))
        )
        new_value = not current

        bot_flags[flag_key] = new_value
        bot_flags['anti_agr'] = bool(
            bot_flags.get('anti_agr_kill', True)
            or bot_flags.get('anti_agr_full_hp', True)
        )

        try:
            active_config = get_config()
            setattr(active_config, config_name, new_value)
        except Exception as exc:
            print(f"[Overlay] Ошибка runtime-переключения {config_name}: {exc}")

        update_flag_button_style(flag_key, button_widget)

        try:
            la2_bot.config.hud_settings.save_button_state(
                flag_key,
                new_value,
                current_client_name,
            )
        except Exception as exc:
            print(f"[Overlay] Не удалось сохранить UI-state {flag_key}: {exc}")

        try:
            save_config_values(
                {config_name: new_value},
                create_backup=False,
            )
        except Exception as exc:
            print(f"[Overlay] Ошибка сохранения {config_name} в config-файл: {exc}")

        _sync_antiaggro_scenario_flags()
        update_flag_button_style(flag_key, button_widget)

        try:
            if (
                config_instance is not None
                and tk.Toplevel.winfo_exists(config_instance.root)
            ):
                config_instance.reload()
        except Exception:
            pass

    def toggle_target_count_mode(button_widget):
        current_mode = bot_flags.get('target_count_mode', 1)
        new_mode = 2 if current_mode == 1 else 1
        bot_flags['target_count_mode'] = new_mode
        la2_bot.config.hud_settings.save_button_state(
            'target_count_mode',
            new_mode,
            current_client_name,
        )
        update_target_count_mode_button_style(button_widget)

    def update_target_count_mode_button_style(button_widget):
        mode = bot_flags.get('target_count_mode', 1)
        if mode == 1:
            button_widget.config(
                text="Целей: 1 (5)",
                bg="#004400",
                fg="white",
            )
        else:
            button_widget.config(
                text="Целей: 2 (5,6)",
                bg="#444400",
                fg="white",
            )

    def on_mouse_down(event):
        root._offsetx = event.x_root - root.winfo_x()
        root._offsety = event.y_root - root.winfo_y()
        root._dragged = False

    def on_mouse_move(event):
        x = event.x_root - root._offsetx
        y = event.y_root - root._offsety
        root.geometry(f'+{x}+{y}')
        root._dragged = True

    def on_mouse_up(event):
        if root._dragged:
            current_settings = la2_bot.config.hud_settings.load_hud_settings(
                current_client_name
            )
            current_settings["pause_overlay_pos_x"] = root.winfo_x()
            current_settings["pause_overlay_pos_y"] = root.winfo_y()
            la2_bot.config.hud_settings.save_hud_settings(
                current_settings,
                current_client_name,
            )

    def on_close():
        nonlocal old_buttons_window

        la2_bot.config.hud_settings.save_all_button_states(
            bot_flags,
            current_client_name,
        )

        current_settings = la2_bot.config.hud_settings.load_hud_settings(
            current_client_name
        )
        current_settings["pause_overlay_pos_x"] = root.winfo_x()
        current_settings["pause_overlay_pos_y"] = root.winfo_y()
        la2_bot.config.hud_settings.save_hud_settings(
            current_settings,
            current_client_name,
        )

        try:
            if old_buttons_window is not None and old_buttons_window.winfo_exists():
                old_buttons_window.destroy()
        except Exception:
            pass

        root.quit()
        root.destroy()

        import sys
        sys.exit(0)

    def toggle_flagstop():
        nonlocal flagstop_button

        if flagstop_mode.is_flagstop_enabled():
            flagstop_mode.stop_flagstop()

            if flagstop_button is not None:
                flagstop_button.config(
                    text="Флагстоп OFF",
                    bg="#440000",
                    fg="lightgray",
                )

            la2_bot.config.hud_settings.save_button_state(
                'flagstop_mode',
                False,
                current_client_name,
            )
        else:
            flagstop_mode.start_flagstop(pause_event)

            if flagstop_button is not None:
                flagstop_button.config(
                    text="Флагстоп ON",
                    bg="#004400",
                    fg="white",
                )

            la2_bot.config.hud_settings.save_button_state(
                'flagstop_mode',
                True,
                current_client_name,
            )

    # ------------------------------------------------------------------
    # Основное окно
    # ------------------------------------------------------------------
    root.title("Bot Control Overlay")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.wm_attributes("-alpha", config.OVERLAY_ALPHA)

    pos_x = loaded_settings.get(
        "pause_overlay_pos_x",
        config.OVERLAY_POSITION_X,
    )
    pos_y = loaded_settings.get(
        "pause_overlay_pos_y",
        config.OVERLAY_POSITION_Y,
    )
    root.geometry(f"+{pos_x}+{pos_y}")
    root.protocol("WM_DELETE_WINDOW", on_close)

    pause_button = tk.Button(
        root,
        text="Start",
        font=("Arial", 12, "bold"),
        width=25,
        bg="lightyellow",
        fg="black",
        bd=3,
        relief="solid",
        highlightthickness=2,
        highlightbackground="gold",
        activebackground="khaki",
        activeforeground="black",
        command=toggle_pause,
    )
    pause_button.pack(pady=(5, 2))
    pause_button.bind("<ButtonPress-1>", on_mouse_down)
    pause_button.bind("<B1-Motion>", on_mouse_move)
    pause_button.bind("<ButtonRelease-1>", on_mouse_up)

    def _sync_pause_button_from_event():
        try:
            is_running = pause_event.is_set()
            text = pause_button.cget('text')

            if is_running and text != "Playing":
                pause_button.config(
                    text="Playing",
                    bg="green",
                    fg="white",
                )
            elif not is_running and text == "Playing":
                pause_button.config(
                    text="Pause",
                    bg="red",
                    fg="white",
                )
        except Exception:
            pass
        finally:
            root.after(300, _sync_pause_button_from_event)

    root.after(300, _sync_pause_button_from_event)

    flags_frame = tk.Frame(root, bg="#222222")
    flags_frame.pack(pady=(0, 5))

    # ------------------------------------------------------------------
    # Основная панель.
    #
    # В «СтарыеКнопки» перенесены:
    #   mob_search, double_click, return_to_target, stuck_target,
    #   anti_coin, anti_no_target, poke.
    # ------------------------------------------------------------------
    potion_btn = make_flag_button(flags_frame, "potion")
    mp_skill_btn = make_flag_button(flags_frame, "mp_skill")
    next_target_btn = make_flag_button(flags_frame, "next_target")

    target_mob_btn = make_flag_button(flags_frame, "target_mob")

    skip_damaged_target_btn = make_flag_button(
        flags_frame,
        "skip_damaged_target",
    )

    anti_agr_kill_btn = tk.Button(
        flags_frame,
        font=("Arial", 9),
        width=button_width,
    )
    anti_agr_kill_btn.config(
        command=lambda: toggle_antiaggro_scenario(
            "anti_agr_kill",
            "THREAT_SCENARIO_KILL_ENABLED",
            anti_agr_kill_btn,
        )
    )
    anti_agr_kill_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("anti_agr_kill", anti_agr_kill_btn)

    anti_agr_full_hp_btn = tk.Button(
        flags_frame,
        font=("Arial", 9),
        width=button_width,
    )
    anti_agr_full_hp_btn.config(
        command=lambda: toggle_antiaggro_scenario(
            "anti_agr_full_hp",
            "THREAT_SCENARIO_FULL_HP_ENABLED",
            anti_agr_full_hp_btn,
        )
    )
    anti_agr_full_hp_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("anti_agr_full_hp", anti_agr_full_hp_btn)

    def refresh_antiaggro_scenario_buttons():
        try:
            _sync_antiaggro_scenario_flags()
            update_flag_button_style(
                "anti_agr_kill",
                anti_agr_kill_btn,
            )
            update_flag_button_style(
                "anti_agr_full_hp",
                anti_agr_full_hp_btn,
            )
            root.after(500, refresh_antiaggro_scenario_buttons)
        except Exception:
            pass

    root.after(500, refresh_antiaggro_scenario_buttons)

    target_count_mode_btn = tk.Button(
        flags_frame,
        font=("Arial", 9),
        width=button_width,
    )
    target_count_mode_btn.config(
        command=lambda: toggle_target_count_mode(target_count_mode_btn)
    )
    target_count_mode_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))

    initial_target_count_mode = loaded_button_states.get(
        "target_count_mode",
        1,
    )
    bot_flags["target_count_mode"] = initial_target_count_mode
    update_target_count_mode_button_style(target_count_mode_btn)

    rapid_target_search_btn = make_flag_button(
        flags_frame,
        "rapid_target_search",
    )

    altheal_btn = make_flag_button(flags_frame, "altheal")
    buffs_btn = make_flag_button(flags_frame, "buffs")
    heal_btn = make_flag_button(flags_frame, "heal")

    heal_interval_frame = tk.Frame(flags_frame, bg="#222222")
    heal_interval_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))

    tk.Label(
        heal_interval_frame,
        text="Интервал хила (сек):",
        font=("Arial", 8),
        bg="#222222",
        fg="white",
    ).pack(side=tk.LEFT)

    heal_interval_var = tk.StringVar(
        value=str(heal_interval_seconds)
    )
    heal_interval_entry = tk.Entry(
        heal_interval_frame,
        textvariable=heal_interval_var,
        width=6,
    )
    heal_interval_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_heal_interval():
        try:
            val = float(
                heal_interval_var.get().replace(',', '.')
            )
            if val <= 0:
                return

            current_settings = (
                la2_bot.config.hud_settings.load_hud_settings(
                    current_client_name
                )
            )
            current_settings["heal_interval_seconds"] = val
            la2_bot.config.hud_settings.save_hud_settings(
                current_settings,
                current_client_name,
            )
        except Exception:
            return

    tk.Button(
        heal_interval_frame,
        text="OK",
        font=("Arial", 8),
        width=3,
        command=apply_heal_interval,
    ).pack(side=tk.LEFT)

    loot_count_frame = tk.Frame(flags_frame, bg="#222222")
    loot_count_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))

    tk.Label(
        loot_count_frame,
        text="Кол-во пикапов:",
        font=("Arial", 8),
        bg="#222222",
        fg="white",
    ).pack(side=tk.LEFT)

    loot_count_var = tk.StringVar(
        value=str(loot_repeat_count)
    )
    loot_count_entry = tk.Entry(
        loot_count_frame,
        textvariable=loot_count_var,
        width=6,
    )
    loot_count_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_loot_count():
        try:
            val = int(
                float(loot_count_var.get().replace(',', '.'))
            )
            if val < 0:
                return

            current_settings = (
                la2_bot.config.hud_settings.load_hud_settings(
                    current_client_name
                )
            )
            current_settings["loot_repeat_count"] = val
            la2_bot.config.hud_settings.save_hud_settings(
                current_settings,
                current_client_name,
            )
            config.LOOT_REPEAT_COUNT = val
        except Exception:
            return

    tk.Button(
        loot_count_frame,
        text="OK",
        font=("Arial", 8),
        width=3,
        command=apply_loot_count,
    ).pack(side=tk.LEFT)

    buff_interval_frame = tk.Frame(flags_frame, bg="#222222")
    buff_interval_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))

    tk.Label(
        buff_interval_frame,
        text="Интервал бафа (сек):",
        font=("Arial", 8),
        bg="#222222",
        fg="white",
    ).pack(side=tk.LEFT)

    buff_interval_var = tk.StringVar(
        value=str(buff_cycle_interval)
    )
    buff_interval_entry = tk.Entry(
        buff_interval_frame,
        textvariable=buff_interval_var,
        width=6,
    )
    buff_interval_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_buff_interval():
        try:
            val = float(
                buff_interval_var.get().replace(',', '.')
            )
            if val <= 0:
                return

            current_settings = (
                la2_bot.config.hud_settings.load_hud_settings(
                    current_client_name
                )
            )
            current_settings["buff_cycle_interval"] = val
            la2_bot.config.hud_settings.save_hud_settings(
                current_settings,
                current_client_name,
            )
            config.BUFF_CYCLE_INTERVAL = val
        except Exception:
            return

    tk.Button(
        buff_interval_frame,
        text="OK",
        font=("Arial", 8),
        width=3,
        command=apply_buff_interval,
    ).pack(side=tk.LEFT)

    altds_btn = make_flag_button(flags_frame, "altds")
    flip_btn = make_flag_button(flags_frame, "flip")
    vkatak_btn = make_flag_button(flags_frame, "vkatak")

    # Это отдельный флаг "Stuck". Его не переносим:
    # пользователь просил перенести именно "Анти-стук" (stuck_target).
    stuck_btn = make_flag_button(flags_frame, "stuck")

    always_assist_btn = make_flag_button(
        flags_frame,
        "always_assist",
    )

    flagstop_button = tk.Button(
        flags_frame,
        text="Флагстоп OFF",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#440000",
        fg="lightgray",
        command=toggle_flagstop,
    )
    flagstop_button.pack(side=tk.TOP, anchor='w', pady=(0, 2))

    if flagstop_saved_enabled:
        flagstop_mode.start_flagstop(pause_event)
        flagstop_button.config(
            text="Флагстоп ON",
            bg="#004400",
            fg="white",
        )

    # ------------------------------------------------------------------
    # Панель «СтарыеКнопки»
    # ------------------------------------------------------------------
    def close_old_buttons_panel():
        nonlocal old_buttons_window

        try:
            if old_buttons_window is not None and old_buttons_window.winfo_exists():
                old_buttons_window.destroy()
        except Exception:
            pass

        old_buttons_window = None

    def toggle_old_buttons_panel():
        nonlocal old_buttons_window

        try:
            exists = (
                old_buttons_window is not None
                and old_buttons_window.winfo_exists()
            )
        except Exception:
            exists = False

        if exists:
            close_old_buttons_panel()
            return

        panel = tk.Toplevel(root)
        old_buttons_window = panel

        panel.title("СтарыеКнопки")
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.configure(bg="#222222")
        panel.wm_attributes("-alpha", config.OVERLAY_ALPHA)

        root.update_idletasks()
        panel_x = root.winfo_x() + root.winfo_width() + 6
        panel_y = root.winfo_y()
        panel.geometry(f"+{panel_x}+{panel_y}")

        header = tk.Frame(panel, bg="#333333")
        header.pack(fill=tk.X, padx=2, pady=(2, 4))

        tk.Label(
            header,
            text="СтарыеКнопки",
            font=("Arial", 9, "bold"),
            bg="#333333",
            fg="white",
        ).pack(side=tk.LEFT, padx=(6, 4), pady=3)

        tk.Button(
            header,
            text="×",
            font=("Arial", 9, "bold"),
            width=3,
            bg="#440000",
            fg="white",
            command=close_old_buttons_panel,
        ).pack(side=tk.RIGHT, padx=2, pady=2)

        old_flags_frame = tk.Frame(panel, bg="#222222")
        old_flags_frame.pack(padx=4, pady=(0, 4))

        # Перенесённые кнопки. Логика и ключи флагов не меняются.
        make_flag_button(old_flags_frame, "anti_no_target")
        make_flag_button(old_flags_frame, "poke")
        make_flag_button(old_flags_frame, "mob_search")
        make_flag_button(old_flags_frame, "double_click")
        make_flag_button(old_flags_frame, "return_to_target")
        make_flag_button(old_flags_frame, "anti_coin")
        make_flag_button(old_flags_frame, "stuck_target")

        def old_panel_mouse_down(event):
            panel._offsetx = event.x_root - panel.winfo_x()
            panel._offsety = event.y_root - panel.winfo_y()

        def old_panel_mouse_move(event):
            x = event.x_root - panel._offsetx
            y = event.y_root - panel._offsety
            panel.geometry(f"+{x}+{y}")

        header.bind("<ButtonPress-1>", old_panel_mouse_down)
        header.bind("<B1-Motion>", old_panel_mouse_move)

    hud_toggle_btn = tk.Button(
        root,
        text="HUD",
        font=("Arial", 9),
        width=button_width,
        bg="#444444",
        fg="white",
        command=toggle_hud,
    )
    hud_toggle_btn.pack(pady=(2, 2))

    old_buttons_btn = tk.Button(
        root,
        text="СтарыеКнопки",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#4a3b22",
        fg="white",
        command=toggle_old_buttons_panel,
    )
    old_buttons_btn.pack(pady=(2, 2))

    def toggle_config_panel():
        nonlocal config_instance

        try:
            exists = (
                config_instance is not None
                and tk.Toplevel.winfo_exists(config_instance.root)
            )
        except Exception:
            exists = False

        if not exists:
            config_instance = create_config_panel(
                root,
                current_client_name,
            )
        else:
            config_instance.focus()

    def toggle_debug_overlay():
        nonlocal debug_instance

        if (
            debug_instance is None
            or not tk.Toplevel.winfo_exists(debug_instance.root)
        ):
            debug_instance = create_debug_overlay(
                root,
                current_client_name,
            )
        else:
            debug_instance.stop()
            debug_instance = None

    def toggle_logs_window():
        nonlocal logs_instance

        if (
            logs_instance is None
            or not tk.Toplevel.winfo_exists(logs_instance.root)
        ):
            logs_instance = create_log_window(
                root,
                current_client_name,
            )
        else:
            logs_instance.stop()
            logs_instance = None

    config_button = tk.Button(
        root,
        text="Конфиг",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#334d19",
        fg="white",
        command=toggle_config_panel,
    )
    config_button.pack(pady=(2, 2))

    debug_button = tk.Button(
        root,
        text="Отладка",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#000044",
        fg="white",
        command=toggle_debug_overlay,
    )
    debug_button.pack(pady=(2, 2))

    logs_button = tk.Button(
        root,
        text="Логи",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#003333",
        fg="white",
        command=toggle_logs_window,
    )
    logs_button.pack(pady=(2, 2))

    def reset_hud():
        nonlocal hud_instance

        client_name = get_client_name()
        hud_settings_module.reset_hud_settings_to_default(
            client_name
        )

        if hud_instance:
            hud_instance.stop()
            hud_instance.root.destroy()
            hud_instance = None

        print(
            f"[HUD] Настройки HUD для {client_name} сброшены до дефолтных. "
            "Нажмите 'Показать HUD', чтобы обновить отображение."
        )

    reset_button = tk.Button(
        root,
        text="Сброс HUD",
        font=("Arial", 9, "bold"),
        width=button_width,
        bg="#440000",
        fg="white",
        command=reset_hud,
    )
    reset_button.pack(pady=(2, 5))

    hwnd = root.winfo_id()
    ex_style = win32gui.GetWindowLong(
        hwnd,
        win32con.GWL_EXSTYLE,
    )
    ex_style |= (
        win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_TOPMOST
    )
    win32gui.SetWindowLong(
        hwnd,
        win32con.GWL_EXSTYLE,
        ex_style,
    )
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        0,
        0,
        0,
        0,
        (
            win32con.SWP_NOMOVE
            | win32con.SWP_NOSIZE
            | win32con.SWP_NOACTIVATE
        ),
    )


def is_flag_enabled(flag_name):
    # Anti-aggro сценарии читаются из активного config_*.py,
    # поэтому изменения через панель «Конфиг» начинают действовать сразу.
    if flag_name == 'anti_agr_kill':
        return bool(
            getattr(
                config,
                'THREAT_SCENARIO_KILL_ENABLED',
                True,
            )
        )

    if flag_name == 'anti_agr_full_hp':
        return bool(
            getattr(
                config,
                'THREAT_SCENARIO_FULL_HP_ENABLED',
                True,
            )
        )

    if flag_name == 'anti_agr':
        return bool(
            getattr(
                config,
                'THREAT_SCENARIO_KILL_ENABLED',
                True,
            )
            or getattr(
                config,
                'THREAT_SCENARIO_FULL_HP_ENABLED',
                True,
            )
        )

    return bot_flags.get(flag_name, False)


def get_target_count_mode():
    return bot_flags.get('target_count_mode', 1)
