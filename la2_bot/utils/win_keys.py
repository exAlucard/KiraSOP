import time
import win32con
import win32api


def tap_vk(vk: int):
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def alt_tab_once():
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    tap_vk(win32con.VK_TAB)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


def alt_tab_then_tap(vk: int, pre_delay: float = 0.5, post_delay: float = 0.0):
    alt_tab_once()
    if pre_delay > 0:
        time.sleep(pre_delay)
    tap_vk(vk)
    if post_delay > 0:
        time.sleep(post_delay)
    alt_tab_once()
