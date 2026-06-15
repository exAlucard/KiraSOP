"""Always Assist feature: press key '5' via Arduino every 1 second."""
import threading
import time
from la2_bot.core.comm import send_command

_assist_thread = None
_stop_event = threading.Event()
_ser = None

INTERVAL_SECONDS = 2.0


def _worker():
    try:
        while not _stop_event.is_set():
            try:
                if _ser is not None:
                    send_command(_ser, 'NEXT_TARGET')  # Arduino mapped to key '5'
                    time.sleep(0.05)
                    send_command(_ser, 'ATTACK')
            except Exception:
                pass
            if _stop_event.wait(timeout=INTERVAL_SECONDS):
                break
    except Exception:
        pass


def set_serial(ser):
    global _ser
    _ser = ser


def start():
    global _assist_thread
    if _assist_thread and _assist_thread.is_alive():
        return
    _stop_event.clear()
    _assist_thread = threading.Thread(target=_worker, daemon=True)
    _assist_thread.start()


def stop():
    global _assist_thread
    if _assist_thread and _assist_thread.is_alive():
        _stop_event.set()
        _assist_thread.join(timeout=1.0)
        _assist_thread = None
