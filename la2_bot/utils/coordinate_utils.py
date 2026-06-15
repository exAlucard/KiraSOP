# la2_bot/utils/coordinate_utils.py
"""
Модуль для преобразования относительных координат из config.py
в абсолютные координаты для текущего окна игры.
"""

from la2_bot.config import config

_absolute_coords = {}

def get_screen_coord_from_client_rel(rel_x, rel_y, window_geometry):
    if not window_geometry:
        return None
    try:
        if isinstance(window_geometry, dict):
            win_x = window_geometry['x']
            win_y = window_geometry['y']
            win_w = window_geometry['width']
            win_h = window_geometry['height']
        else:
            win_x, win_y, win_w, win_h = window_geometry

        screen_x = int(win_x + rel_x * win_w)
        screen_y = int(win_y + rel_y * win_h)
        return (screen_x, screen_y)
    except Exception as e:
        return None

def _convert_to_relative(abs_coords, canvas_width, canvas_height):
    if len(abs_coords) == 2:
        return (abs_coords[0] / canvas_width, abs_coords[1] / canvas_height)
    elif len(abs_coords) == 4:
        return (abs_coords[0] / canvas_width, abs_coords[1] / canvas_height,
                abs_coords[2] / canvas_width, abs_coords[3] / canvas_height)
    return abs_coords

def _convert_to_absolute(rel_coords, win_x, win_y, win_w, win_h):
    if len(rel_coords) == 2:
        return (int(win_x + rel_coords[0] * win_w), int(win_y + rel_coords[1] * win_h))
    elif len(rel_coords) == 4:
        return (int(win_x + rel_coords[0] * win_w), int(win_y + rel_coords[1] * win_h),
                int(win_x + rel_coords[2] * win_w), int(win_y + rel_coords[3] * win_h))
    return rel_coords

def initialize_coordinates(window_geometry):
    """Инициализирует абсолютные координаты на основе геометрии текущего окна игры."""
    global _absolute_coords
    _absolute_coords.clear()
    if not window_geometry:
        return

    if isinstance(window_geometry, dict):
        win_x = window_geometry['x']
        win_y = window_geometry['y']
        win_w = window_geometry['width']
        win_h = window_geometry['height']
    else:
        win_x, win_y, win_w, win_h = window_geometry

    canvas_width = config.CANVAS_BASE_WIDTH
    canvas_height = config.CANVAS_BASE_HEIGHT

    from la2_bot.config.config_manager import get_config
    current_config_module = get_config()

    import inspect
    config_vars = {k: v for k, v in inspect.getmembers(current_config_module) if not k.startswith('_') and not inspect.ismodule(v) and not inspect.isfunction(v) and not inspect.isbuiltin(v)}

    rel_vars = {k: v for k, v in config_vars.items() if k.endswith('_REL')}

    for rel_name, abs_value_from_config in rel_vars.items():
        try:
            rel_coords = _convert_to_relative(abs_value_from_config, canvas_width, canvas_height)
            abs_coords = _convert_to_absolute(rel_coords, win_x, win_y, win_w, win_h)
            abs_name = rel_name[:-4]
            _absolute_coords[abs_name] = abs_coords
        except Exception as e:
            continue

    if 'DOUBLE_CLICK_POINT' not in _absolute_coords and 'DOUBLE_CLICK_POINT_REL' in rel_vars:
        try:
            rel_coords = _convert_to_relative(rel_vars['DOUBLE_CLICK_POINT_REL'], canvas_width, canvas_height)
            abs_coords = _convert_to_absolute(rel_coords, win_x, win_y, win_w, win_h)
            _absolute_coords['DOUBLE_CLICK_POINT'] = abs_coords
        except Exception as e:
            _absolute_coords['DOUBLE_CLICK_POINT'] = None

def get_absolute_coord(coord_name):
    result = _absolute_coords.get(coord_name, None)
    return result

def __getattr__(name):
    return get_absolute_coord(name)

def clear_coordinate_cache():
    global _absolute_coords
    _absolute_coords.clear()
