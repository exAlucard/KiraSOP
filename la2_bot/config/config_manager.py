# la2_bot/config/config_manager.py

import importlib
from la2_bot.utils.window_utils import get_game_window_geometry

_current_client_name = None
_current_config_module = None
_supported_clients = {"lu4", "mw"}
_process_to_client = {
    "lu4.bin": "lu4",
    "mw.bin": "mw",
    "l2.bin": "mw",
    "ScrydeGame.bin": "mw"
}

def _load_config_module(client_name):
    """Загружает модуль конфигурации для указанного клиента."""
    if client_name not in _supported_clients:
        raise ValueError(f"Неподдерживаемый клиент: {client_name}")

    module_name = f"la2_bot.config.config_{client_name}"
    print(f"[ConfigManager] Загрузка конфига: {module_name}")
    try:
        config_module = importlib.import_module(module_name)
        config_module = importlib.reload(config_module)
        return config_module
    except ImportError as e:
        print(f"[ConfigManager] Ошибка импорта конфига {module_name}: {e}")
        raise

def initialize_config(default_client="lu4"):
    """Инициализирует конфиг при запуске программы, используя активный клиент или клиент по умолчанию."""
    global _current_client_name, _current_config_module

    found_client = None
    found_process = None
    for process_name in _process_to_client.keys():
        if get_game_window_geometry(process_name):
            found_process = process_name
            found_client = _process_to_client[process_name]
            break

    if found_client:
        _current_client_name = found_client
        _current_config_module = _load_config_module(_current_client_name)
        print(f"[ConfigManager] Активный клиент найден. Установлен клиент: {_current_client_name} (процесс {found_process})")
    else:
        _current_client_name = default_client
        _current_config_module = _load_config_module(_current_client_name)
        print(f"[ConfigManager] Активный клиент не найден. Установлен клиент по умолчанию: {_current_client_name}")

    if _current_config_module is None:
        raise RuntimeError(f"Не удалось загрузить конфигурацию для клиента {_current_client_name}")

def update_config_if_needed():

    global _current_client_name, _current_config_module

    new_client_name = None
    new_process_name = None
    for process_name in _process_to_client.keys():
        if get_game_window_geometry(process_name):
            new_process_name = process_name
            new_client_name = _process_to_client[process_name]
            break

    if new_client_name and new_client_name != _current_client_name:
        print(f"[ConfigManager] Обнаружена смена активного клиента: {_current_client_name} -> {new_client_name} (процесс {new_process_name})")
        _current_client_name = new_client_name
        _current_config_module = _load_config_module(new_client_name)
        print(f"[ConfigManager] Конфиг обновлён для клиента: {_current_client_name}")

        from la2_bot.utils import coordinate_utils
        coordinate_utils.clear_coordinate_cache()
        return True
    
    return False

def get_config():
    """Возвращает текущий активный модуль конфигурации."""
    if _current_config_module is None:
        raise RuntimeError("Менеджер конфигураций не инициализирован.")
    return _current_config_module

def get_client_name():
    """Возвращает имя текущего активного клиента."""
    if _current_client_name is None:
        raise RuntimeError("Менеджер конфигураций не инициализирован.")
    return _current_client_name