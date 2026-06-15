# la2_bot/config/__init__.py

from .config_manager import get_config, get_client_name, initialize_config, update_config_if_needed

# --- Импортируем функции управления ---
from .config_manager import get_config as get_active_config
from .config_manager import get_client_name as get_active_client_name
from .config_manager import update_config_if_needed as check_and_update_config

# --- Создаем псевдоним 'config', который будет указывать на активный конфиг ---
# Это позволяет делать 'from la2_bot.config import config'
# и затем использовать config.GAME_EXE_NAME и т.д.
class _ConfigProxy:
    """
    Прокси-класс, который делегирует доступ к атрибутам
    текущему активному модулю конфигурации.
    """
    def __getattr__(self, name):
        """
        Динамически возвращает переменную из текущего активного конфига.
        Пример: config.GAME_EXE_NAME -> вернёт значение из config_lu4.py или config_mw.py
        """
        active_config = get_active_config()
        if hasattr(active_config, name):
            return getattr(active_config, name)
        raise AttributeError(f"'{active_config.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        """
        (Опционально) Позволяет изменять переменные в активном конфиге, если это необходимо.
        """
        active_config = get_active_config()
        if hasattr(active_config, name):
            setattr(active_config, name, value)
        else:
            raise AttributeError(f"'{active_config.__name__}' object has no attribute '{name}'")

# Создаем глобальный экземпляр прокси
config = _ConfigProxy()

# Также можно экспортировать другие функции/переменные, если нужно
__all__ = [
    "config", "get_active_config", "get_active_client_name", "check_and_update_config",
    "initialize_config" # Добавляем, чтобы можно было вызвать из main.py
]