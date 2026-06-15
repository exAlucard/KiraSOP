# la2_bot/ui/hud.py

import tkinter as tk
from la2_bot.config import config
from la2_bot.utils import coordinate_utils
from la2_bot.utils.window_utils import get_game_window_geometry

class HUDOverlay:
    def __init__(self, parent_root, pause_event, hud_settings_module, client_name):
        self.root = tk.Toplevel(parent_root)
        self.parent_root = parent_root
        self.pause_event = pause_event
        self.hud_settings_module = hud_settings_module
        self.client_name = client_name
        self.settings = self.hud_settings_module.load_hud_settings(self.client_name)
        self.elements = {}
        self.visibility_buttons = {}
        self.element_visibility_states = self.settings.get("element_visibility_states", {})
        for key in self._get_display_keys():
            if key not in self.element_visibility_states:
                self.element_visibility_states[key] = True

        self.root.overrideredirect(False)
        self.root.protocol("WM_DELETE_WINDOW", self._close_hud)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", 0.7)

        pos_x = self.settings.get("pos_x", 100)
        pos_y = self.settings.get("pos_y", 100)
        self.root.geometry(f"+{pos_x}+{pos_y}")

        self.is_visible = self.settings.get("is_visible", False)
        if self.is_visible:
            self.root.deiconify()
        else:
            self.root.withdraw()

        self.root.bind("<ButtonPress-1>", self._start_move_root_window)
        self.root.bind("<ButtonRelease-1>", self._stop_move_root_window)
        self.root.bind("<B1-Motion>", self._on_move_root_window)

        self.toggles_frame = tk.Frame(self.root, bg="#333333")
        self.toggles_frame.pack(side="bottom", fill="x", pady=2)
        self._create_visibility_toggles()

        self.update_interval = 500
        self.active_element_key = None
        self.elements_initialized = False

    def start(self):
        self.parent_root.after(self.update_interval, self._update_loop)

    def _create_visibility_toggles(self):
        for key in self._get_display_keys():
            btn_cmd = lambda k=key: self._toggle_element_visibility(k)
            btn = tk.Button(
                self.toggles_frame,
                text=f"{config.HUD_LABELS.get(self._get_coord_name_for_key(key), key)}: {'ON' if self.element_visibility_states.get(key, True) else 'OFF'}",
                font=("Arial", 7),
                width=25,
                command=btn_cmd
            )
            btn.pack(side="top", fill="x", pady=1, padx=2)
            self.visibility_buttons[key] = btn
        self.toggles_frame.pack_forget()

    def _update_loop(self):
        if self.is_visible:
            game_geom_dict = get_game_window_geometry(config.GAME_EXE_NAME)
            if game_geom_dict:
                game_geom = (
                    game_geom_dict['x'],
                    game_geom_dict['y'],
                    game_geom_dict['width'],
                    game_geom_dict['height']
                )

                if not self.elements_initialized:
                    for item in self.elements.values():
                        item["window"].destroy()
                    self.elements = {}
                    coordinate_utils.initialize_coordinates(game_geom_dict)
                    self._initialize_elements(game_geom)
                    self.elements_initialized = True
                else:
                    self._update_elements_positions(game_geom)
        self.parent_root.after(self.update_interval, self._update_loop)

    def _initialize_elements(self, game_geom):
        for key in self._get_display_keys():
            if key not in self.elements:
                self._create_hud_element(key, game_geom)
            self._update_element_visibility(key)

    def _update_elements_positions(self, game_geom):
        for key, element in self.elements.items():
            element_settings = self.settings.get("elements_positions", {}).get(key)
            if not element_settings:
                coord_name = self._get_coord_name_for_key(key)
                abs_coord = coordinate_utils.get_absolute_coord(coord_name)
                if abs_coord:
                    self._position_element_based_on_coord(key, abs_coord, game_geom)

    def _position_element_based_on_coord(self, key, abs_coord, game_geom):
        element = self.elements[key]
        window = element["window"]

        if element["is_point"]:
            x, y = abs_coord
            screen_x, screen_y = x, y
            window.update_idletasks()
            win_width = window.winfo_width()
            marker_size = 11
            new_x = screen_x - win_width // 2
            new_y = screen_y - marker_size // 2
            window.geometry(f"+{new_x}+{new_y}")
        else:
            x1, y1, x2, y2 = abs_coord
            screen_x1, screen_y1 = x1, y1
            
            label_frame = element["label_frame"]
            window.update_idletasks()
            label_height = label_frame.winfo_height()
            
            adjusted_y = screen_y1 - label_height
            window.geometry(f"+{screen_x1}+{adjusted_y}")


    def _create_hud_element(self, key, game_geom):
        coord_name = self._get_coord_name_for_key(key)
        abs_coord = coordinate_utils.get_absolute_coord(coord_name)
        if not abs_coord: return

        is_point = len(abs_coord) == 2
        window = tk.Toplevel(self.parent_root)
        window.overrideredirect(True)
        window.wm_attributes("-topmost", True)
        window.config(bg='grey')
        window.wm_attributes("-transparentcolor", "grey")

        text_label_str = config.HUD_LABELS.get(coord_name, key)
        
        label_frame = None

        if is_point:
            marker_size = 11
            canvas = tk.Canvas(window, width=marker_size, height=marker_size, bg='grey', highlightthickness=0)
            canvas.create_line(marker_size//2, 0, marker_size//2, marker_size, fill='red', width=1)
            canvas.create_line(0, marker_size//2, marker_size, marker_size//2, fill='red', width=1)
            canvas.pack()
            
            label_frame = tk.Frame(window, bg="black")
            label = tk.Label(label_frame, text=text_label_str, bg="black", fg="white", font=("Arial", 8))
            label.pack(padx=5, pady=2)
            label_frame.pack()
        else:
            width, height = abs_coord[2] - abs_coord[0], abs_coord[3] - abs_coord[1]

            label_frame = tk.Frame(window, bg="black")
            label = tk.Label(label_frame, text=text_label_str, bg="black", fg="white", font=("Arial", 8))
            label.pack(padx=5, pady=2)
            label_frame.pack(side="top", fill="x")

            canvas = tk.Canvas(window, width=width, height=height, bg='grey', highlightthickness=0)
            canvas.pack(side="top")
            canvas.create_rectangle(1, 1, width-1, height-1, outline='cyan', width=2)
            
        self.elements[key] = {"window": window, "is_point": is_point, "label_frame": label_frame}

        element_settings = self.settings.get("elements_positions", {}).get(key)
        if element_settings:
            window.geometry(f"+{element_settings['x']}+{element_settings['y']}")
        else:
            self._position_element_based_on_coord(key, abs_coord, game_geom)

        window.bind("<ButtonPress-1>", lambda e, k=key: self._start_move_element(e, k))
        window.bind("<ButtonRelease-1>", lambda e, k=key: self._stop_move_element(e, k))
        window.bind("<B1-Motion>", lambda e, k=key: self._on_move_element(e, k))

    def _get_display_keys(self):
        from la2_bot.config.config_manager import get_config
        current_config_module = get_config()
        import inspect
        config_vars = {k: v for k, v in inspect.getmembers(current_config_module) if not k.startswith('_') and not inspect.ismodule(v) and not inspect.isfunction(v) and not inspect.isbuiltin(v)}
        return [k for k in config_vars.keys() if k.endswith('_REL')]

    def _get_coord_name_for_key(self, key):
        return key[:-4]

    def _toggle_element_visibility(self, key):
        self.element_visibility_states[key] = not self.element_visibility_states.get(key, True)
        self.settings["element_visibility_states"] = self.element_visibility_states
        self.hud_settings_module.save_hud_settings(self.settings, self.client_name)
        self._update_element_visibility(key)
        self._update_visibility_button_text(key)

    def _update_element_visibility(self, key):
        if key in self.elements:
            is_visible = self.element_visibility_states.get(key, True) and self.is_visible
            if is_visible:
                self.elements[key]["window"].deiconify()
            else:
                self.elements[key]["window"].withdraw()

    def _update_visibility_button_text(self, key):
        btn = self.visibility_buttons[key]
        is_on = self.element_visibility_states.get(key, True)
        coord_name = self._get_coord_name_for_key(key)
        btn.config(text=f"{config.HUD_LABELS.get(coord_name, key)}: {'ON' if is_on else 'OFF'}")

    def toggle_visibility(self):
        self.is_visible = not self.is_visible
        self.settings["is_visible"] = self.is_visible
        self.hud_settings_module.save_hud_settings(self.settings, self.client_name)

        if self.is_visible:
            self.root.deiconify()
            self.toggles_frame.pack(side="bottom", fill="x", pady=2)
            self.elements_initialized = False
            self._update_loop()
        else:
            self.root.withdraw()
            self.toggles_frame.pack_forget()
            for item in self.elements.values():
                item["window"].withdraw()

    def _start_move_root_window(self, event):
        self.root_start_x = event.x_root - self.root.winfo_x()
        self.root_start_y = event.y_root - self.root.winfo_y()

    def _stop_move_root_window(self, event):
        self.settings["pos_x"] = self.root.winfo_x()
        self.settings["pos_y"] = self.root.winfo_y()
        self.hud_settings_module.save_hud_settings(self.settings, self.client_name)

    def _on_move_root_window(self, event):
        x = event.x_root - self.root_start_x
        y = event.y_root - self.root_start_y
        self.root.geometry(f"+{x}+{y}")

    def _start_move_element(self, event, key):
        self.active_element_key = key
        rect = self.elements[key]["window"]
        self.element_start_x = event.x_root - rect.winfo_x()
        self.element_start_y = event.y_root - rect.winfo_y()

    def _stop_move_element(self, event, key):
        if self.active_element_key == key:
            self.active_element_key = None
            rect = self.elements[key]["window"]
            if "elements_positions" not in self.settings:
                self.settings["elements_positions"] = {}
            self.settings["elements_positions"][key] = {"x": rect.winfo_x(), "y": rect.winfo_y()}
            self.hud_settings_module.save_hud_settings(self.settings, self.client_name)

    def _on_move_element(self, event, key):
        if self.active_element_key == key:
            rect = self.elements[key]["window"]
            new_x = event.x_root - self.element_start_x
            new_y = event.y_root - self.element_start_y
            rect.geometry(f"+{new_x}+{new_y}")

    def _close_hud(self):
        self.is_visible = False
        self.settings["is_visible"] = self.is_visible
        self.hud_settings_module.save_hud_settings(self.settings, self.client_name)
        self.root.destroy()
        for item in self.elements.values():
            if item and item.get("window") and item.get("window").winfo_exists():
                item["window"].destroy()
        self.elements = {}

def create_hud(parent_root, pause_event, hud_settings_module, client_name):
    return HUDOverlay(parent_root, pause_event, hud_settings_module, client_name)
