# main.py
import threading
import tkinter as tk

from la2_bot.config import initialize_config
from la2_bot.core.log_buffer import install_stdout_capture

install_stdout_capture()

print("[main] Инициализация конфигурации...")
initialize_config()
print("[main] Конфигурация инициализирована.")

from la2_bot.ui.bot_menu import create_pause_overlay
import la2_bot.config.hud_settings
from la2_bot.core.engine import bot_loop
from la2_bot.core.state import pause_event

def main():
    root = tk.Tk()
    threading.Thread(target=bot_loop, args=(pause_event,), daemon=True).start()
    create_pause_overlay(root, pause_event, la2_bot.config.hud_settings)
    root.mainloop()

if __name__ == "__main__":
    main()