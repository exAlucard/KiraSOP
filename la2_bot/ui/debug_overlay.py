# la2_bot/ui/debug_overlay.py
import tkinter as tk
import threading
import time
import win32con
import win32gui
from la2_bot.config import config
from la2_bot.utils import coordinate_utils
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils.pixel_utils import is_color_match
from la2_bot.detection.green_pixel_utils import is_green_pixel_detected
from la2_bot.core.debug_state import get_threat_watcher_hp # Импортируем новую функцию
import la2_bot.config.hud_settings

DEBUG_POINTS = [
    ("CHAR_HP_POINT", config.CHAR_HP_COLOR, "HP Персонажа"),
    ("CHAR_MP_POINT", config.CHAR_MP_COLOR, "MP Персонажа"),
    ("SKILL_RESET_POINT", config.SKILL_RESET_COLOR, "Откат Скилла"),
    ("TARGET_SELECTED_POINT", getattr(config, 'TARGET_MOB_COLOR', getattr(config, 'TARGET_SELECTED_COLOR', (158, 158, 124))), "Таргет - моб"),
    ("TARGET_MOB_POINT2", getattr(config, 'TARGET_MOB_COLOR2', None), "Таргет - моб (2)"),
    ("TARGET_HP_1_POINT", config.TARGET_COLOR, "1 HP Цели (BTN8)"),
    ("TARGET_HP_DAMAGED_POINT", getattr(config, 'TARGET_HP_DAMAGED_COLOR', config.TARGET_COLOR), "HP Цели (Поврежден)"),
    ("TARGET_HP_FULL_POINT", config.TARGET_COLOR, "HP Цели (Полный)"),
    ("FLAGSTOP_POINT", (103, 0, 83), "Пиксель Flagstop"),
]

class DebugOverlay:
    def __init__(self, root, client_name):
        self.root = tk.Toplevel(root)
        self.client_name = client_name
        self.settings = la2_bot.config.hud_settings.load_hud_settings(self.client_name)

        self.root.title("Debug Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-alpha", 0.9)

        pos_x = self.settings.get("debug_overlay_pos_x", 100)
        pos_y = self.settings.get("debug_overlay_pos_y", 100)
        self.root.geometry(f"+{pos_x}+{pos_y}")

        self.stop_event = threading.Event()
        self.thread = None

        self.labels = {}
        self._create_widgets()

        hwnd = self.root.winfo_id()
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

        self.root.bind("<ButtonPress-1>", self.on_mouse_down)
        self.root.bind("<B1-Motion>", self.on_mouse_move)
        self.root.bind("<ButtonRelease-1>", self.on_mouse_up)

    def _create_widgets(self):
        main_frame = tk.Frame(self.root, bg="#1E1E1E")
        main_frame.pack(padx=5, pady=5)
        tk.Button(main_frame, text="X", command=self.stop, bg="red", fg="white", width=2).pack(side=tk.RIGHT, anchor='ne')

        # --- Секция пикселей ---
        pixel_frame = tk.LabelFrame(main_frame, text="DEBUG: KEY PIXELS", font=('Arial', 10, 'bold'), bg="#333333", fg="white", padx=5, pady=5)
        pixel_frame.pack(fill='x', expand=True)

        headers = ["Параметр", "Координата", "Ожидаемый Цвет", "Текущий Цвет"]
        for i, header in enumerate(headers):
            tk.Label(pixel_frame, text=header, font=('Arial', 8, 'bold'), bg="#222222", fg="yellow", width=15 if i < 3 else 16).grid(row=0, column=i, padx=2, pady=2, sticky="w")

        for i, (name, expected_color, label) in enumerate(DEBUG_POINTS):
            row = i + 1
            tk.Label(pixel_frame, text=label, font=('Arial', 8), bg="#333333", fg="white", width=15, anchor="w").grid(row=row, column=0, padx=2, pady=1, sticky="w")
            self.labels[name + "_COORD"] = tk.Label(pixel_frame, text="N/A", font=('Arial', 8), bg="#333333", fg="lightblue", width=15, anchor="w")
            self.labels[name + "_COORD"].grid(row=row, column=1, padx=2, pady=1, sticky="w")
            tk.Label(pixel_frame, text=str(expected_color), font=('Arial', 8), bg="#333333", fg="lightgreen", width=15, anchor="w").grid(row=row, column=2, padx=2, pady=1, sticky="w")
            self.labels[name + "_CURRENT"] = tk.Label(pixel_frame, text="N/A", font=('Arial', 8), bg="#333333", fg="red", width=16, anchor="w")
            self.labels[name + "_CURRENT"].grid(row=row, column=3, padx=2, pady=1, sticky="w")

        row = len(DEBUG_POINTS) + 1
        tk.Label(pixel_frame, text="Зеленый пиксель", font=('Arial', 8), bg="#333333", fg="white", width=15, anchor="w").grid(row=row, column=0, padx=2, pady=1, sticky="w")
        self.labels["GREEN_PIXEL_COORD"] = tk.Label(pixel_frame, text="N/A", font=('Arial', 8), bg="#333333", fg="lightblue", width=15, anchor="w")
        self.labels["GREEN_PIXEL_COORD"].grid(row=row, column=1, padx=2, pady=1, sticky="w")
        tk.Label(pixel_frame, text=str(getattr(config, 'GREEN_PIXEL_COLOR', None)), font=('Arial', 8), bg="#333333", fg="lightgreen", width=15, anchor="w").grid(row=row, column=2, padx=2, pady=1, sticky="w")
        self.labels["GREEN_PIXEL_CURRENT"] = tk.Label(pixel_frame, text="N/A", font=('Arial', 8), bg="#333333", fg="red", width=16, anchor="w")
        self.labels["GREEN_PIXEL_CURRENT"].grid(row=row, column=3, padx=2, pady=1, sticky="w")

        row = len(DEBUG_POINTS) + 2
        tk.Label(pixel_frame, text="Статус", font=('Arial', 8), bg="#333333", fg="white", width=15, anchor="w").grid(row=row, column=0, padx=2, pady=1, sticky="w")
        self.labels["GREEN_PIXEL_STATUS"] = tk.Label(pixel_frame, text="N/A", font=('Arial', 8), bg="#333333", fg="white", width=15, anchor="w")
        self.labels["GREEN_PIXEL_STATUS"].grid(row=row, column=1, columnspan=3, padx=2, pady=1, sticky="w")
        
        # --- Секция Анти-агра ---
        threat_frame = tk.LabelFrame(main_frame, text="АНТИ-АГР СТАТУС", font=('Arial', 10, 'bold'), bg="#333333", fg="white", padx=5, pady=5)
        threat_frame.pack(fill='x', expand=True, pady=(10,0))
        
        self.labels['TW_PREVIOUS_HP'] = tk.Label(threat_frame, text="Пред. HP: N/A", font=('Arial', 8), bg="#333333", fg="white", anchor="w")
        self.labels['TW_PREVIOUS_HP'].pack(fill='x')
        self.labels['TW_CURRENT_HP'] = tk.Label(threat_frame, text="Тек. HP: N/A", font=('Arial', 8), bg="#333333", fg="white", anchor="w")
        self.labels['TW_CURRENT_HP'].pack(fill='x')
        self.labels['TW_STATUS'] = tk.Label(threat_frame, text="Статус: OK", font=('Arial', 10, 'bold'), bg="#333333", fg="lightgreen", anchor="center")
        self.labels['TW_STATUS'].pack(fill='x', pady=5)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._update_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.root.destroy()

    def _update_loop(self):
        while not self.stop_event.is_set():
            try:
                # Обновление пикселей
                for name, expected_color, _ in DEBUG_POINTS:
                    coord = coordinate_utils.get_absolute_coord(name)
                    if coord:
                        self.labels[name + "_COORD"].config(text=f"({coord[0]}, {coord[1]})")
                        current_color = get_pixel_color(coord[0], coord[1])
                        color_text = f"({current_color[0]}, {current_color[1]}, {current_color[2]})"
                        is_match = False
                        if name == 'TARGET_HP_DAMAGED_POINT':
                           is_match = current_color == expected_color
                        elif name == 'TARGET_SELECTED_POINT':
                           if isinstance(expected_color, list):
                               is_match = any(is_color_match(current_color, c, getattr(config, 'COLOR_THRESHOLD', 10)) for c in expected_color)
                           else:
                               is_match = is_color_match(current_color, expected_color, getattr(config, 'COLOR_THRESHOLD', 10))
                        elif name == 'TARGET_MOB_POINT2':
                           if expected_color is None:
                               is_match = False
                           else:
                               is_match = is_color_match(current_color, expected_color, getattr(config, 'COLOR_THRESHOLD', 10))
                        elif name.startswith('TARGET'):
                           is_match = is_target_color(current_color)
                        else:
                           is_match = current_color == expected_color

                        self.labels[name + "_CURRENT"].config(text=color_text, bg="#004400" if is_match else "#440000")
                    else:
                        self.labels[name + "_COORD"].config(text="Неактивно")
                        self.labels[name + "_CURRENT"].config(text="N/A", bg="#333333")
                
                self.labels["GREEN_PIXEL_STATUS"].config(text="Найден" if is_green_pixel_detected() else "Не найден", 
                                                          bg="#004400" if is_green_pixel_detected() else "#440000")

                try:
                    gp_coord = getattr(coordinate_utils, 'GREEN_PIXEL_POINT', None)
                    gp_expected = getattr(config, 'GREEN_PIXEL_COLOR', None)
                    if gp_coord and gp_expected:
                        self.labels["GREEN_PIXEL_COORD"].config(text=f"({gp_coord[0]}, {gp_coord[1]})")
                        gp_current = get_pixel_color(gp_coord[0], gp_coord[1])
                        gp_text = f"({gp_current[0]}, {gp_current[1]}, {gp_current[2]})"
                        gp_match = is_color_match(gp_current, gp_expected, getattr(config, 'COLOR_THRESHOLD', 10))
                        self.labels["GREEN_PIXEL_CURRENT"].config(text=gp_text, bg="#004400" if gp_match else "#440000")
                    else:
                        self.labels["GREEN_PIXEL_COORD"].config(text="Неактивно")
                        self.labels["GREEN_PIXEL_CURRENT"].config(text="N/A", bg="#333333")
                except Exception:
                    pass

                # Обновление данных анти-агра
                hp_data = get_threat_watcher_hp()
                prev_hp = hp_data.get('previous_hp')
                curr_hp = hp_data.get('current_hp')
                is_falling = hp_data.get('hp_falling', False)

                prev_hp_text = f"{prev_hp:.1f}%" if isinstance(prev_hp, float) else "N/A"
                curr_hp_text = f"{curr_hp:.1f}%" if isinstance(curr_hp, float) else "N/A"

                self.labels['TW_PREVIOUS_HP'].config(text=f"Пред. HP: {prev_hp_text}")
                self.labels['TW_CURRENT_HP'].config(text=f"Тек. HP: {curr_hp_text}")

                if is_falling:
                    self.labels['TW_STATUS'].config(text="АНТИ-АГР!", fg="red")
                else:
                    self.labels['TW_STATUS'].config(text="Статус: OK", fg="lightgreen")

            except Exception as e:
                print(f"[Debug Overlay] Ошибка в цикле обновления: {e}")

            time.sleep(0.5)

    def on_mouse_down(self, event):
        self.root._offsetx = event.x_root - self.root.winfo_x()
        self.root._offsety = event.y_root - self.root.winfo_y()
        self.root._dragged = False

    def on_mouse_move(self, event):
        x = event.x_root - self.root._offsetx
        y = event.y_root - self.root._offsety
        self.root.geometry(f'+{x}+{y}')
        self.root._dragged = True

    def on_mouse_up(self, event):
        if self.root._dragged:
            current_settings = la2_bot.config.hud_settings.load_hud_settings(self.client_name)
            current_settings["debug_overlay_pos_x"] = self.root.winfo_x()
            current_settings["debug_overlay_pos_y"] = self.root.winfo_y()
            la2_bot.config.hud_settings.save_hud_settings(current_settings, self.client_name)

def create_debug_overlay(root, client_name):
    """Создает и запускает отладочный оверлей."""
    overlay = DebugOverlay(root, client_name)
    overlay.start()
    return overlay
