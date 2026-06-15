# la2_bot/ui/bot_menu.py
import tkinter as tk
import win32con
import win32gui
import win32api
import time
import threading
from la2_bot.config import config
from la2_bot.ui.hud import create_hud
from la2_bot.ui.debug_overlay import create_debug_overlay
from la2_bot.ui.log_window import create_log_window
import la2_bot.config.hud_settings
from la2_bot.config.config_manager import get_client_name
from la2_bot.core.debug_state import set_next_target_cooldown
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
    'anti_agr': False, # Renamed from target_mode
    'anti_coin': False,
    'target_count_mode': 1,
    'altheal': False,
    'buffs': False,
    'heal': False,
    'altds': False,
    'flip': False,
    'vkatak': False,
    'stuck': False,
    'poke': False,
    'always_assist': False,
}

def create_pause_overlay(root, pause_event, hud_settings_module):
    global bot_flags
    current_client_name = get_client_name()
    loaded_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
    loaded_button_states = la2_bot.config.hud_settings.load_button_states(current_client_name)
    heal_interval_seconds = loaded_settings.get("heal_interval_seconds", 15.0)
    loot_repeat_count = loaded_settings.get("loot_repeat_count", getattr(config, 'LOOT_REPEAT_COUNT', 3))
    buff_cycle_interval = loaded_settings.get("buff_cycle_interval", getattr(config, 'BUFF_CYCLE_INTERVAL', 60.0))
    for key, value in loaded_button_states.items():
        if key in bot_flags:
            bot_flags[key] = value

    # Восстановление сохранённого состояния Flagstop
    flagstop_saved_enabled = loaded_button_states.get('flagstop_mode', False)

    # Auto-start background worker if saved ON and bot is running
    if bot_flags.get('always_assist') and pause_event.is_set():
        always_assist.start()

    hud_instance = None
    altheal_thread = None
    flagstop_button = None

    def toggle_hud():
        nonlocal hud_instance
        if hud_instance is None or not tk.Toplevel.winfo_exists(hud_instance.root):
            hud_instance = create_hud(root, pause_event, hud_settings_module, current_client_name)
            hud_instance.start()
            hud_instance.toggle_visibility()
        else:
            hud_instance.toggle_visibility()

    def toggle_pause():
        state = pause_button.cget('text')
        if state in ("Start", "Pause"):
            pause_event.set()
            pause_button.config(text="Playing", bg="green", fg="white")
            # Start AlwaysAssist only when bot is running and flag is ON
            if bot_flags.get('always_assist'):
                always_assist.start()
        else:
            pause_event.clear()
            pause_button.config(text="Pause", bg="red", fg="white")
            # Stop AlwaysAssist when bot is paused
            always_assist.stop()

    def toggle_flag(flag_key, button_widget):
        bot_flags[flag_key] = not bot_flags[flag_key]
        la2_bot.config.hud_settings.save_button_state(flag_key, bot_flags[flag_key], current_client_name)
        update_flag_button_style(flag_key, button_widget)
        # 'altheal' and 'heal' are handled in engine loop via Arduino
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
            'altheal': "Альтхил",
            'buffs': getattr(config, 'FLAG_BUTTON_TEXT_BUFF', 'Бафы'),
            'heal': "Хил",
            'altds': "АльтДС",
            'flip': "Флип",
            'vkatak': "ВКатак",
            'stuck': "Stuck",
            'poke': "Подпинывание",
            'always_assist': "ВсегдаАсист",
        }
        is_enabled = bot_flags[flag_key]
        base_text = flag_text_map.get(flag_key, flag_key.capitalize())
        if is_enabled:
            button_widget.config(bg="#004400", fg="white", relief="raised", text=f"{base_text} ON")
        else:
            button_widget.config(bg="#440000", fg="lightgray", relief="ridge", text=f"{base_text} OFF")

    

    def toggle_target_count_mode(button_widget):
        current_mode = bot_flags.get('target_count_mode', 1)
        new_mode = 2 if current_mode == 1 else 1
        bot_flags['target_count_mode'] = new_mode
        la2_bot.config.hud_settings.save_button_state('target_count_mode', new_mode, current_client_name)
        update_target_count_mode_button_style(button_widget)

    def update_target_count_mode_button_style(button_widget):
        mode = bot_flags.get('target_count_mode', 1)
        if mode == 1:
            button_widget.config(text="Целей: 1 (5)", bg="#004400", fg="white")
        else:
            button_widget.config(text="Целей: 2 (5,6)", bg="#444400", fg="white")

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
            current_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
            current_settings["pause_overlay_pos_x"] = root.winfo_x()
            current_settings["pause_overlay_pos_y"] = root.winfo_y()
            la2_bot.config.hud_settings.save_hud_settings(current_settings, current_client_name)

    def on_close():
        la2_bot.config.hud_settings.save_all_button_states(bot_flags, current_client_name)
        current_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
        current_settings["pause_overlay_pos_x"] = root.winfo_x()
        current_settings["pause_overlay_pos_y"] = root.winfo_y()
        la2_bot.config.hud_settings.save_hud_settings(current_settings, current_client_name)
        root.quit()
        root.destroy()
        import sys
        sys.exit(0)

    def toggle_flagstop():
        nonlocal flagstop_button
        if flagstop_mode.is_flagstop_enabled():
            flagstop_mode.stop_flagstop()
            if flagstop_button is not None:
                flagstop_button.config(text="Флагстоп OFF", bg="#440000", fg="lightgray")
            # сохраняем состояние "выкл"
            la2_bot.config.hud_settings.save_button_state('flagstop_mode', False, current_client_name)
        else:
            flagstop_mode.start_flagstop(pause_event)
            if flagstop_button is not None:
                flagstop_button.config(text="Флагстоп ON", bg="#004400", fg="white")
            # сохраняем состояние "вкл"
            la2_bot.config.hud_settings.save_button_state('flagstop_mode', True, current_client_name)

    root.title("Bot Control Overlay")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.wm_attributes("-alpha", config.OVERLAY_ALPHA)
    pos_x = loaded_settings.get("pause_overlay_pos_x", config.OVERLAY_POSITION_X)
    pos_y = loaded_settings.get("pause_overlay_pos_y", config.OVERLAY_POSITION_Y)
    root.geometry(f"+{pos_x}+{pos_y}")
    root.protocol("WM_DELETE_WINDOW", on_close)

    pause_button = tk.Button(
        root, text="Start", font=("Arial", 12, "bold"), width=25, bg="lightyellow", fg="black", bd=3,
        relief="solid", highlightthickness=2, highlightbackground="gold", activebackground="khaki",
        activeforeground="black", command=toggle_pause
    )
    pause_button.pack(pady=(5, 2))
    pause_button.bind("<ButtonPress-1>", on_mouse_down)
    pause_button.bind("<B1-Motion>", on_mouse_move)
    pause_button.bind("<ButtonRelease-1>", on_mouse_up)

    # Синхронизация текста кнопки с реальным состоянием pause_event
    def _sync_pause_button_from_event():
        try:
            is_running = pause_event.is_set()
            text = pause_button.cget('text')
            if is_running and text != "Playing":
                pause_button.config(text="Playing", bg="green", fg="white")
            elif not is_running and text == "Playing":
                pause_button.config(text="Pause", bg="red", fg="white")
        except Exception:
            pass
        finally:
            # Проверяем состояние каждые 300 мс
            root.after(300, _sync_pause_button_from_event)

    root.after(300, _sync_pause_button_from_event)

    flags_frame = tk.Frame(root, bg="#222222")
    flags_frame.pack(pady=(0, 5))

    button_width = 25
    potion_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("potion", potion_btn))
    potion_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("potion", potion_btn)

    mp_skill_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("mp_skill", mp_skill_btn))
    mp_skill_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("mp_skill", mp_skill_btn)

    next_target_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("next_target", next_target_btn))
    next_target_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("next_target", next_target_btn)

    mob_search_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("mob_search", mob_search_btn))
    mob_search_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("mob_search", mob_search_btn)

    double_click_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("double_click", double_click_btn))
    double_click_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("double_click", double_click_btn)

    target_mob_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("target_mob", target_mob_btn))
    target_mob_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("target_mob", target_mob_btn)

    return_to_target_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("return_to_target", return_to_target_btn))
    return_to_target_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("return_to_target", return_to_target_btn)
    
    stuck_target_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("stuck_target", stuck_target_btn))
    stuck_target_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("stuck_target", stuck_target_btn)

    skip_damaged_target_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("skip_damaged_target", skip_damaged_target_btn))
    skip_damaged_target_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("skip_damaged_target", skip_damaged_target_btn)

    anti_coin_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("anti_coin", anti_coin_btn))
    anti_coin_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("anti_coin", anti_coin_btn)

    # Renamed from target_mode_btn to anti_agr_btn
    anti_agr_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("anti_agr", anti_agr_btn))
    anti_agr_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("anti_agr", anti_agr_btn)
    
    target_count_mode_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_target_count_mode(target_count_mode_btn))
    target_count_mode_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    initial_target_count_mode = loaded_button_states.get("target_count_mode", 1)
    bot_flags["target_count_mode"] = initial_target_count_mode
    update_target_count_mode_button_style(target_count_mode_btn)

    hud_toggle_btn = tk.Button(root, text="HUD", font=("Arial", 9), width=button_width, bg="#444444", fg="white", command=toggle_hud)
    hud_toggle_btn.pack(pady=(2, 2))

    debug_instance = None
    logs_instance = None
    
    def toggle_debug_overlay():
        nonlocal debug_instance
        if debug_instance is None or not tk.Toplevel.winfo_exists(debug_instance.root):
            debug_instance = create_debug_overlay(root, current_client_name)
        else:
            debug_instance.stop()
            debug_instance = None

    def toggle_logs_window():
        nonlocal logs_instance
        if logs_instance is None or not tk.Toplevel.winfo_exists(logs_instance.root):
            logs_instance = create_log_window(root, current_client_name)
        else:
            logs_instance.stop()
            logs_instance = None

    debug_button = tk.Button(root, text="Отладка", font=("Arial", 9, "bold"), width=button_width, bg="#000044", fg="white", command=toggle_debug_overlay)
    debug_button.pack(pady=(2, 2))

    logs_button = tk.Button(root, text="Логи", font=("Arial", 9, "bold"), width=button_width, bg="#003333", fg="white", command=toggle_logs_window)
    logs_button.pack(pady=(2, 2))

    # Local Altheal worker removed; handled in engine via Arduino

    altheal_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("altheal", altheal_btn))
    altheal_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("altheal", altheal_btn)
    # No local background worker for altheal; engine reads the flag

    buffs_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("buffs", buffs_btn))
    buffs_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("buffs", buffs_btn)

    heal_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("heal", heal_btn))
    heal_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("heal", heal_btn)

    heal_interval_frame = tk.Frame(flags_frame, bg="#222222")
    heal_interval_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))
    tk.Label(heal_interval_frame, text="Интервал хила (сек):", font=("Arial", 8), bg="#222222", fg="white").pack(side=tk.LEFT)
    heal_interval_var = tk.StringVar(value=str(heal_interval_seconds))
    heal_interval_entry = tk.Entry(heal_interval_frame, textvariable=heal_interval_var, width=6)
    heal_interval_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_heal_interval():
        try:
            val = float(heal_interval_var.get().replace(',', '.'))
            if val <= 0:
                return
            current_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
            current_settings["heal_interval_seconds"] = val
            la2_bot.config.hud_settings.save_hud_settings(current_settings, current_client_name)
        except Exception:
            return

    tk.Button(heal_interval_frame, text="OK", font=("Arial", 8), width=3, command=apply_heal_interval).pack(side=tk.LEFT)

    loot_count_frame = tk.Frame(flags_frame, bg="#222222")
    loot_count_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))
    tk.Label(loot_count_frame, text="Кол-во пикапов:", font=("Arial", 8), bg="#222222", fg="white").pack(side=tk.LEFT)
    loot_count_var = tk.StringVar(value=str(loot_repeat_count))
    loot_count_entry = tk.Entry(loot_count_frame, textvariable=loot_count_var, width=6)
    loot_count_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_loot_count():
        try:
            val = int(float(loot_count_var.get().replace(',', '.')))
            if val < 0:
                return
            current_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
            current_settings["loot_repeat_count"] = val
            la2_bot.config.hud_settings.save_hud_settings(current_settings, current_client_name)
            config.LOOT_REPEAT_COUNT = val
        except Exception:
            return

    tk.Button(loot_count_frame, text="OK", font=("Arial", 8), width=3, command=apply_loot_count).pack(side=tk.LEFT)

    buff_interval_frame = tk.Frame(flags_frame, bg="#222222")
    buff_interval_frame.pack(side=tk.TOP, anchor='w', pady=(0, 6))
    tk.Label(buff_interval_frame, text="Интервал бафа (сек):", font=("Arial", 8), bg="#222222", fg="white").pack(side=tk.LEFT)
    buff_interval_var = tk.StringVar(value=str(buff_cycle_interval))
    buff_interval_entry = tk.Entry(buff_interval_frame, textvariable=buff_interval_var, width=6)
    buff_interval_entry.pack(side=tk.LEFT, padx=(5, 5))

    def apply_buff_interval():
        try:
            val = float(buff_interval_var.get().replace(',', '.'))
            if val <= 0:
                return
            current_settings = la2_bot.config.hud_settings.load_hud_settings(current_client_name)
            current_settings["buff_cycle_interval"] = val
            la2_bot.config.hud_settings.save_hud_settings(current_settings, current_client_name)
            config.BUFF_CYCLE_INTERVAL = val
        except Exception:
            return

    tk.Button(buff_interval_frame, text="OK", font=("Arial", 8), width=3, command=apply_buff_interval).pack(side=tk.LEFT)

    altds_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("altds", altds_btn))
    altds_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("altds", altds_btn)

    flip_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("flip", flip_btn))
    flip_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("flip", flip_btn)

    vkatak_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("vkatak", vkatak_btn))
    vkatak_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("vkatak", vkatak_btn)

    stuck_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("stuck", stuck_btn))
    stuck_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("stuck", stuck_btn)

    poke_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("poke", poke_btn))
    poke_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("poke", poke_btn)

    always_assist_btn = tk.Button(flags_frame, font=("Arial", 9), width=button_width, command=lambda: toggle_flag("always_assist", always_assist_btn))
    always_assist_btn.pack(side=tk.TOP, anchor='w', pady=(0, 2))
    update_flag_button_style("always_assist", always_assist_btn)

    flagstop_button = tk.Button(flags_frame, text="Флагстоп OFF", font=("Arial", 9, "bold"), width=button_width, bg="#440000", fg="lightgray", command=toggle_flagstop)
    flagstop_button.pack(side=tk.TOP, anchor='w', pady=(0, 2))

    # Применяем сохранённое состояние Flagstop при старте (после создания кнопки)
    if flagstop_saved_enabled:
        flagstop_mode.start_flagstop(pause_event)
        flagstop_button.config(text="Флагстоп ON", bg="#004400", fg="white")

    def reset_hud():
        client_name = get_client_name()
        hud_settings_module.reset_hud_settings_to_default(client_name)
        nonlocal hud_instance
        if hud_instance:
            hud_instance.stop()
            hud_instance.root.destroy()
            hud_instance = None
        print(f"[HUD] Настройки HUD для {client_name} сброшены до дефолтных. Нажмите 'Показать HUD', чтобы обновить отображение.")

    reset_button = tk.Button(root, text="Сброс HUD", font=("Arial", 9, "bold"), width=button_width, bg="#440000", fg="white", command=reset_hud)
    reset_button.pack(pady=(2, 5))

    hwnd = root.winfo_id()
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

def is_flag_enabled(flag_name):
    return bot_flags.get(flag_name, False)

def get_target_count_mode():
    return bot_flags.get('target_count_mode', 1)
''