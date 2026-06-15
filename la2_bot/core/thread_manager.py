# la2_bot/core/thread_manager.py

import threading

"""Глобальные переменные для потока возврата к маяку"""
beacon_return_process_thread = None
beacon_return_stop_event = threading.Event()

def reset_beacon_thread():
    global beacon_return_process_thread
    beacon_return_process_thread = None

def reset_beacon_stop_event():
    global beacon_return_stop_event
    beacon_return_stop_event.clear()