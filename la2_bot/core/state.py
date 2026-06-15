# la2_bot/core/state.py

import threading

# --- Глобальные переменные ---
pause_event = threading.Event()
mob_highlight_thread = None
mob_highlight_stop_event = threading.Event()

last_focus_state = None
_last_focus_check = 0


def set_last_focus_state(value):
    global last_focus_state
    last_focus_state = value

def get_last_focus_state():
    return last_focus_state

def set_last_focus_check(value):
    global _last_focus_check
    _last_focus_check = value

def get_last_focus_check():
    return _last_focus_check