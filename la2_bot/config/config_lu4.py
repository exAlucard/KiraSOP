# la2_bot/config/config_lu4.py
# ----- Настройки COM‑порта и основной интервал -----
BAUD_RATE      = 9600
VID            = 0x2341
PID            = 0x8036
CHECK_INTERVAL = 0.05

GAME_EXE_NAME = "lu4.bin"

# ----- Относительные координаты и разрешение -----
CANVAS_BASE_WIDTH  = 1920
CANVAS_BASE_HEIGHT = 1080

# ----- Координаты пикселей -----
TARGET_HP_1_POINT_REL         = (758, 8)  # 1 HP основной цели (для возврата к таргету)
TARGET_HP_DAMAGED_POINT_REL   = (1045, 8 )  # Пиксель поврежденной цели
TARGET_HP_FULL_POINT_REL      = (1160, 9)  # Признак полного HP цели (для спойла)
CHAR_HP_POINT_REL             = (205, 67)  # Пиксель HP персонажа
CHAR_MP_POINT_REL             = (60, 87)  # Пиксель MP персонажа

# ----- Цвета и порог -----
TARGET_COLOR      = (255, 0, 0)
CHAR_HP_COLOR     = (228, 123, 106)
CHAR_MP_COLOR     = (102, 153, 215)
COLOR_THRESHOLD   = 10

# ----- Поиск удачного спойла -----
GREEN_PIXEL_SEARCH_AREA_REL  = (1207, 952, 1224, 1086)
GREEN_PIXEL_POINT_REL        = None
GREEN_PIXEL_COLOR       = (191, 255, 177)

# ----- Поиск отката скила -----
SKILL_RESET_POINT_REL  = (501, 955)
SKILL_RESET_COLOR = (70, 30, 1)

# ----- Прямоугольники для OCR -----
HP_RECT_REL  = (120, 63, 170, 80)
MP_RECT_REL  = (120, 83, 150, 100)

# ----- Команды на Arduino -----
CMD = {
    'NEXT_TARGET':      b'5\n',     # Следующая цель 1
    'NEXT_TARGET_2':    b'6\n',     # Следующая цель 2
    'RETURN_TO_TARGET': b'0\n',     # Возврат к сохраненному таргету
    'SKILL1_SPOIL':     b'1\n',
    'SWEEP':            b'3\n',
    'LOOT':             b'4\n',
    'HP_POTION':        b'9\n',
    'HEAL_KEY':         b'-\n',
    'MP_SKILL':         b'8\n',
    'ATTACK':           b'7\n',
    'ESC':              b'ESC\n',
    'NEAREST_TARGET':   b'2\n',     # Ближайшая цель (для угрозы)
    
    'RMOUSE_PRESS':     b'RMOUSE_PRESS\n',
    'RMOUSE_RELEASE':   b'RMOUSE_RELEASE\n',
    'LCLICK':           b'LCLICK\n',
    'RCLICK':           b'RCLICK\n',
    
    'W_PRESS':          b'WPRESS\n',
    'W_RELEASE':        b'WREL\n',
    'ALT_TAB':          b'ALT_TAB\n',
    # --- Функциональные клавиши для Arduino ---
    'F1':               b'F1\n',
    'F2':               b'F2\n',
    'F3':               b'F3\n',
    'F4':               b'F4\n',
    'F5':               b'F5\n',
    'F6':               b'F6\n',
    'F7':               b'F7\n',
    'F8':               b'F8\n',
    'F9':               b'F9\n',
    'F10':              b'F10\n',
    'F11':              b'F11\n',
    'F12':              b'F12\n',
}

# ----- Интервалы и задержки -----
STUCK_TARGET_TIMEOUT = 7.0 # Время в секундах, чтобы считать цель "застрявшей"
TARGET_SWITCH_DELAY = 0.5 # Задержка перед поиском новой цели
NEXT_TARGET_MIN    = 0.2
NEXT_TARGET_MAX    = 0.5
LOOT_MIN           = 0.05
LOOT_MAX           = 0.15
SWEEP_TO_LOOT_MIN  = 0.3
SWEEP_TO_LOOT_MAX  = 0.6
LOOT_REPEAT_COUNT  = 3

POTION_INTERVAL    = 15.0
MP_SKILL_INTERVAL  = 3.0
ATTACK_INTERVAL_MIN = 6.0
ATTACK_INTERVAL_MAX = 8.0

SPOIL_ATTEMPT_INTERVAL_MIN = 0.85
SPOIL_ATTEMPT_INTERVAL_MAX = 1.4

# --- Наблюдение за угрозой ---
THREAT_WATCH_DURATION = 2.0  # Новая настройка
THREAT_WATCH_BASE_DURATION = 1.0
THREAT_WATCH_BASE_DURATION_DELTA = 0.2
THREAT_WATCH_EXTRA_DURATION_AFTER_NEXT = 1.5
THREAT_WATCH_EXTRA_DURATION_AFTER_NEXT_DELTA = 0.5
THREAT_WATCH_CHECK_INTERVAL = 0.1
THREAT_POST_NEXT_DELAY_RANGE = (2.0, 3.0)

# ----- Конфиг оверлея паузы -----
OVERLAY_ALPHA = 0.5
OVERLAY_POSITION_X  = 25
OVERLAY_POSITION_Y  = 442

# ----- Подсветка мобов -----
NAME_SEARCH_AREA_REL  = (0,127,1916,875)
MOB_NAMES = ["Hunter Bear", "Goblin Brigand Leader"]
MOB_HIGHLIGHT_INTERVAL = 0.5

# ----- Настройки дабл кликера по области (ЛКМ) -----
LCLICK_PAUSE_MIN = 0.15
LCLICK_PAUSE_MAX = 0.25
DOUBLE_CLICK_INTERVAL = 2.0

# ----- Настройки флагов опций бота (начальное состояние при запуске) -----
FLAG_POTION_ENABLED             = True
FLAG_MP_SKILL_ENABLED           = True
FLAG_NEXT_TARGET_ENABLED        = True
FLAG_MOB_SEARCH_ENABLED         = False
FLAG_DOUBLE_CLICK_ENABLED       = True
FLAG_RETURN_TO_TARGET_ENABLED   = False # Использовать возврат к таргету
FLAG_STUCK_TARGET_ENABLED       = True  # Включить/выключить сброс застрявшей цели

# ----- Настройки двойного клика -----
DOUBLE_CLICK_POINT_REL  = (155, 250)
DOUBLE_CLICK_MOVE_DURATION_MIN = 0.4
DOUBLE_CLICK_MOVE_DURATION_MAX = 0.8
DOUBLE_CLICK_PAUSE_MIN = 1.0
DOUBLE_CLICK_PAUSE_MAX = 1.6

# ----- Пиксель Flagstop (для HUD и отладки) -----
FLAGSTOP_POINT_REL = (952, 502)

# ----- Настройки экшена Возврат к таргету -----
HP1_MONSTER_WAIT_TIME_MIN = 3.0
HP1_MONSTER_WAIT_TIME_MAX = 4.0
RETURN_TO_TARGET_PAUSE_MIN = 0.5
RETURN_TO_TARGET_PAUSE_MAX = 1.0
HP1_MONSTER_CHECK_INTERVAL = 0.2

# ----- Настройки текста кнопок в оверлее -----
FLAG_BUTTON_TEXT_POTION             = "HP Банка"
FLAG_BUTTON_TEXT_MP_SKILL           = "MP Скилл"
FLAG_BUTTON_TEXT_NEXT_TARGET        = "/target"
FLAG_BUTTON_TEXT_MOB_SEARCH         = "Поиск Моба"
FLAG_BUTTON_TEXT_DOUBLE_CLICK       = "Дабл Клик"
FLAG_BUTTON_TEXT_RETURN_TO_TARGET   = "Возврат к таргету"
FLAG_BUTTON_TEXT_TARGET_MODE        = "Цель"
FLAG_BUTTON_TEXT_STUCK_TARGET       = "Анти-стук"

FLAG_TARGET_MODE_INITIAL_STATE = 0

# ----- Конфигурация модуля green_pixel_utils -----
GREEN_PIXEL_RESTART_INTERVAL = 7200

# ----- Настройки клика при снятии с паузы и потере фокуса -----
DOUBLE_CLICK_ON_PLAY_DELAY = 1.0
DOUBLE_CLICK_ON_FOCUS_LOST_DELAY = 5.0

# ----- Настройки HUD -----
HUD_POSITION_X = 0
HUD_POSITION_Y = 0

HUD_LABELS = {
    "TARGET_HP_1_POINT": "Пиксель 1 HP цели",
    "TARGET_HP_DAMAGED_POINT": "Пиксель поврежденной цели",
    "TARGET_HP_FULL_POINT": "Пиксель полного HP цели",
    "CHAR_HP_POINT": "Пиксель HP персонажа",
    "CHAR_MP_POINT": "Пиксель MP персонажа",
    "SKILL_RESET_POINT": "Пиксель сброса скилла",
    "DOUBLE_CLICK_POINT": "Точка двойного клика",
    "FLAGSTOP_POINT": "Пиксель Flagstop",
    "HP_RECT": "Область OCR HP персонажа",
    "MP_RECT": "Область OCR MP персонажа",
    "GREEN_PIXEL_SEARCH_AREA": "Зона поиска зелёного пикселя",
    "NAME_SEARCH_AREA": "Зона поиска имени моба",
    "POTION_INTERVAL": "Интервал HP Банки",
    "MP_SKILL_INTERVAL": "Интервал MP Скилла",
    "NEXT_TARGET_MIN": "Мин. интервал NEXT TARGET",
    "NEXT_TARGET_MAX": "Макс. интервал NEXT TARGET",
    "LOOT_REPEAT_COUNT": "Кол-во лута",
    "STUCK_TARGET_TIMEOUT": "Таймаут застрявшей цели"
}

HUD_ELEMENT_ALPHA = 0.5

# ----- Настройки бафов (F1..F10) -----
# Включено ли выполнение цикла бафов
FLAG_BUFF_ENABLED = False
# Последовательность клавиш для нажатия в одном цикле
# Возможные значения: 'F1'..'F10'
BUFF_SEQUENCE = ['F1']
# Задержка удержания клавиши (мс)
BUFF_KEY_PRESS_MS = 50.0
# Интервал между нажатиями внутри цикла (сек)
BUFF_BETWEEN_KEYS_MIN = 0.2
BUFF_BETWEEN_KEYS_MAX = 0.3
# Общий интервал между циклами (сек)
BUFF_CYCLE_INTERVAL = 60.0

# Текст кнопки в оверлее для бафов
FLAG_BUTTON_TEXT_BUFF = "Бафы (F1-F10)"
