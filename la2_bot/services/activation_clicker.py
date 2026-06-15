#la2_bot/services/activation_clicker.py

import time, random, pyautogui
from la2_bot.core.comm import send_command
from la2_bot.utils.window_utils import is_game_active, get_game_window_geometry
from la2_bot.utils.coordinate_utils import get_screen_coord_from_client_rel
from la2_bot.config import config


def perform_activation_click(ser):
    if is_game_active(config.GAME_EXE_NAME):
        print("[activation_click] Окно уже в фокусе — активация не требуется.")
        return

    window_geometry = get_game_window_geometry(config.GAME_EXE_NAME)
    if not window_geometry:
        print(f"[activation_click] Ошибка: не удалось найти окно {config.GAME_EXE_NAME}")
        return

    rel_x, rel_y = getattr(config, 'DOUBLE_CLICK_POINT_REL', (0.5, 0.5))
    x, y = get_screen_coord_from_client_rel(rel_x, rel_y, window_geometry)

    move_duration = random.uniform(
        getattr(config, 'DOUBLE_CLICK_MOVE_DURATION_MIN', 0.4),
        getattr(config, 'DOUBLE_CLICK_MOVE_DURATION_MAX', 0.9)
    )
    pyautogui.moveTo(x, y, duration=move_duration)
    time.sleep(0.08)
    send_command(ser, 'RCLICK')
    print("[activation_click] ПКМ выполнен для активации окна.")
