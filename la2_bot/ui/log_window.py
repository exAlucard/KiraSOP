import tkinter as tk

from la2_bot.core import log_buffer
import la2_bot.config.hud_settings


class LogWindow:
    UPDATE_INTERVAL_MS = 100

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

        self.text = tk.Text(
            self.root,
            bg="#0F0F0F",
            fg="#E6E6E6",
            insertbackground="#E6E6E6",
            wrap="none",
        )
        self.text.pack(fill="both", expand=True)

        self.scroll_y = tk.Scrollbar(
            self.root,
            orient="vertical",
            command=self.text.yview,
        )
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=self.scroll_y.set)

        self.scroll_x = tk.Scrollbar(
            self.root,
            orient="horizontal",
            command=self.text.xview,
        )
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.configure(xscrollcommand=self.scroll_x.set)

        self.text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        # Храним сам последний снимок логов, а не только его длину.
        # Это важно, потому что log_buffer использует deque(maxlen=2000):
        # после заполнения длина всегда равна 2000, хотя содержимое меняется.
        self._last_lines = None

        self._autoscroll = True
        self._after_id = None
        self._stopped = False

        self.text.bind("<Button-1>", self._on_user_scroll)
        self.text.bind("<MouseWheel>", self._on_user_scroll)
        self.text.bind("<Key>", self._on_user_scroll)

    def _on_user_scroll(self, _event=None):
        try:
            last_visible = float(self.text.yview()[1])
            self._autoscroll = last_visible >= 0.999
        except Exception:
            pass

    def start(self):
        if self._stopped:
            return

        # Обновляем через Tk.after(), чтобы все операции с Tkinter
        # выполнялись только в GUI-потоке.
        self._poll_logs()

    def stop(self):
        if self._stopped:
            return

        self._stopped = True

        try:
            current_settings = la2_bot.config.hud_settings.load_hud_settings(
                self.client_name
            )
            current_settings["log_window_pos_x"] = self.root.winfo_x()
            current_settings["log_window_pos_y"] = self.root.winfo_y()
            current_settings["log_window_width"] = self.root.winfo_width()
            current_settings["log_window_height"] = self.root.winfo_height()
            la2_bot.config.hud_settings.save_hud_settings(
                current_settings,
                self.client_name,
            )
        except Exception:
            pass

        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

        try:
            self.root.destroy()
        except Exception:
            pass

    def _set_text(self, lines):
        if self._stopped:
            return

        try:
            # Запоминаем, был ли пользователь у самого низа ДО перерисовки.
            # Если он читает старые строки, не прыгаем автоматически вниз.
            if self._autoscroll:
                should_scroll = True
            else:
                should_scroll = float(self.text.yview()[1]) >= 0.999

            self.text.configure(state="normal")
            self.text.delete("1.0", "end")

            if lines:
                self.text.insert("end", "\n".join(lines) + "\n")

            if should_scroll:
                self.text.see("end")
                self._autoscroll = True

            self.text.configure(state="disabled")
        except tk.TclError:
            # Окно уже могло быть закрыто между callback'ами.
            pass

    def _poll_logs(self):
        if self._stopped:
            return

        try:
            lines = log_buffer.get_lines()

            # Сравниваем содержимое, а не len(lines).
            # Благодаря этому окно обновляется и после заполнения
            # deque(maxlen=2000).
            if self._last_lines is None or lines != self._last_lines:
                self._last_lines = list(lines)
                self._set_text(lines)

        except Exception:
            # Окно логов не должно ронять основной бот из-за UI-ошибки.
            pass

        if not self._stopped:
            try:
                self._after_id = self.root.after(
                    self.UPDATE_INTERVAL_MS,
                    self._poll_logs,
                )
            except tk.TclError:
                self._after_id = None


def create_log_window(root, client_name):
    win = LogWindow(root, client_name)
    win.start()
    return win
