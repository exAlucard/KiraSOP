# la2_bot/utils/window_utils.py

import pygetwindow as gw
import win32process
import win32gui
import win32api
import win32con
import os

def is_game_active(exe_name):
    """
    Проверяет, является ли активное окно окном игры, заданной по имени исполняемого файла.
    """
    try:
        active_window = gw.getActiveWindow()
        if active_window is not None:
            hwnd = active_window._hWnd
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid
                )
                process_path = win32process.GetModuleFileNameEx(process_handle, 0)
                win32api.CloseHandle(process_handle)
                process_exe_name = os.path.basename(process_path)
                if process_exe_name == exe_name:
                    return True

            except Exception as e:
                pass
        return False
    except Exception as e:
        return False

def get_game_window_geometry(exe_name):
    """
    Получает геометрию клиентской области окна игры.
    Ищет окно по имени исполняемого файла.
    """
    try:
        active_window = gw.getActiveWindow()
        if active_window is not None:
            hwnd = active_window._hWnd
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid
                )
                process_path = win32process.GetModuleFileNameEx(process_handle, 0)
                win32api.CloseHandle(process_handle)
                process_exe_name = os.path.basename(process_path)
                if process_exe_name == exe_name:
                    client_rect = win32gui.GetClientRect(hwnd)
                    client_area_top_left_screen = win32gui.ClientToScreen(hwnd, (0, 0))
                    client_width = client_rect[2] - client_rect[0]
                    client_height = client_rect[3] - client_rect[1]

                    return {
                        'x': client_area_top_left_screen[0],
                        'y': client_area_top_left_screen[1],
                        'width': client_width,
                        'height': client_height
                    }
            except Exception as e:
                pass

        all_windows = gw.getWindowsWithTitle('')
        for window in all_windows:
            hwnd = window._hWnd
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid
                )
                process_path = win32process.GetModuleFileNameEx(process_handle, 0)
                win32api.CloseHandle(process_handle)
                process_exe_name = os.path.basename(process_path)

                if process_exe_name == exe_name:
                    client_rect = win32gui.GetClientRect(hwnd)
                    client_area_top_left_screen = win32gui.ClientToScreen(hwnd, (0, 0))
                    client_width = client_rect[2] - client_rect[0]
                    client_height = client_rect[3] - client_rect[1]

                    return {
                        'x': client_area_top_left_screen[0],
                        'y': client_area_top_left_screen[1],
                        'width': client_width,
                        'height': client_height
                    }
            except Exception as e:
                continue
        return None

    except Exception as e:
        return None