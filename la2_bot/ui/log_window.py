import tkinter as tk
import threading
import time

from la2_bot.core import log_buffer
import la2_bot.config.hud_settings


class LogWindow:
    def __init__(self, root, client_name):
        self.root = tk.Toplevel(root)
        self.client_name = client_name
        self.settings = la2_bot.config.hud_settings.load_hud_settings(self.client_name)

        self.root.title("Bot Logs")
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-alpha", 0.9)

        pos_x = self.settings.get("log_window_pos_x", 200)
        pos_y = self.settings.get("log_window_pos_y", 200)
        width = self.settings.get("log_window_width", 700)
        height = self.settings.get("log_window_height", 350)
        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

        self.stop_event = threading.Event()
        self.thread = None

        self.text = tk.Text(self.root, bg="#0F0F0F", fg="#E6E6E6", insertbackground="#E6E6E6", wrap="none")
        self.text.pack(fill="both", expand=True)

        self.scroll_y = tk.Scrollbar(self.root, orient="vertical", command=self.text.yview)
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=self.scroll_y.set)

        self.scroll_x = tk.Scrollbar(self.root, orient="horizontal", command=self.text.xview)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.configure(xscrollcommand=self.scroll_x.set)

        self.text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        self._last_len = 0
        self._autoscroll = True

        self.text.bind("<Button-1>", self._on_user_scroll)
        self.text.bind("<MouseWheel>", self._on_user_scroll)
        self.text.bind("<Key>", self._on_user_scroll)

    def _on_user_scroll(self, _event=None):
        # If user navigates away from the end, disable autoscroll
        try:
            last_visible = float(self.text.yview()[1])
            self._autoscroll = last_visible >= 0.999
        except Exception:
            pass

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._update_loop, daemon=True)
            self.thread.start()

    def stop(self):
        try:
            current_settings = la2_bot.config.hud_settings.load_hud_settings(self.client_name)
            current_settings["log_window_pos_x"] = self.root.winfo_x()
            current_settings["log_window_pos_y"] = self.root.winfo_y()
            current_settings["log_window_width"] = self.root.winfo_width()
            current_settings["log_window_height"] = self.root.winfo_height()
            la2_bot.config.hud_settings.save_hud_settings(current_settings, self.client_name)
        except Exception:
            pass

        self.stop_event.set()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _set_text(self, lines):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(lines) + ("\n" if lines else ""))
        if self._autoscroll:
            self.text.see("end")
        self.text.configure(state="disabled")

    def _update_loop(self):
        # Initial fill
        try:
            lines = log_buffer.get_lines()
            self._last_len = len(lines)
            self.root.after(0, lambda: self._set_text(lines))
        except Exception:
            pass

        while not self.stop_event.is_set():
            try:
                lines = log_buffer.get_lines()
                if len(lines) != self._last_len:
                    self._last_len = len(lines)
                    self.root.after(0, lambda l=lines: self._set_text(l))
            except Exception:
                pass

            time.sleep(0.25)


def create_log_window(root, client_name):
    win = LogWindow(root, client_name)
    win.start()
    return win
