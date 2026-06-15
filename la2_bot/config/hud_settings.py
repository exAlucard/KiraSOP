# la2_bot/config/hud_settings.py
import json
import os
import importlib
from la2_bot.config.config_manager import get_client_name

def get_hud_settings_filename(client_name):
    return f"hud_settings_{client_name}.json"

def load_hud_settings(client_name=None):
    if client_name is None:
        client_name = get_client_name()
    filename = get_hud_settings_filename(client_name)
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                if os.path.getsize(filename) > 0:
                    return json.load(f)
                else:
                    return {}
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_hud_settings(settings, client_name=None):
    if client_name is None:
        client_name = get_client_name()
    filename = get_hud_settings_filename(client_name)
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

def load_button_states(client_name=None):
    if client_name is None:
        client_name = get_client_name()
    settings = load_hud_settings(client_name)
    return settings.get("button_states", {})

def save_button_state(flag_key, state, client_name=None):
    if client_name is None:
        client_name = get_client_name()
    settings = load_hud_settings(client_name)
    if "button_states" not in settings:
        settings["button_states"] = {}
    settings["button_states"][flag_key] = state
    save_hud_settings(settings, client_name)

def save_all_button_states(all_states, client_name=None):
    if client_name is None:
        client_name = get_client_name()
    settings = load_hud_settings(client_name)
    settings["button_states"] = all_states
    save_hud_settings(settings, client_name)

def reset_hud_settings_to_default(client_name=None):
    """Сбрасывает настройки HUD до значений из статического конфига."""
    if client_name is None:
        client_name = get_client_name()

    try:
        config_module = importlib.import_module(f"la2_bot.config.config_{client_name}")
    except ImportError:
        print(f"[HUD Settings] Не удалось найти статический конфиг для клиента {client_name}")
        return

    settings = load_hud_settings(client_name)
    for key in (
        "pos_x",
        "pos_y",
        "is_visible",
        "elements_positions",
        "element_visibility_states",
    ):
        if key in settings:
            del settings[key]

    save_hud_settings(settings, client_name)
    print(f"[HUD Settings] Настройки HUD для клиента {client_name} сброшены до дефолтных.")
