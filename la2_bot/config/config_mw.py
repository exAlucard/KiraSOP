# la2_bot/config/config_mw.py
# ----- Настройки COM‑порта и основной интервал -----
BAUD_RATE      = 9600
VID            = 0x2341
PID            = 0x8036
CHECK_INTERVAL = 0.05   # Основной интервал проверки в цикле bot_loop (секунды)

GAME_EXE_NAME = "l2.bin" # Имя процесса для второго клиента

# ----- Относительные координаты и разрешение -----
# Эталонное разрешение, на котором определялись все координаты пикселей
CANVAS_BASE_WIDTH  = 1920 # Замените на ваше реальное базовое разрешение
CANVAS_BASE_HEIGHT = 1080 # Замените на ваше реальное базовое разрешение

# ----- Координаты пикселей (Примерные координаты для mw.bin, замените на свои) -----
TARGET_HP_1_POINT_REL         = (791, 28)  # 1 HP основной цели (для возврата к таргету)
TARGET_HP_DAMAGED_POINT_REL   = (1112, 28) # Пиксель поврежденной цели
TARGET_HP_FULL_POINT_REL      = (1142, 28) # Признак полного HP цели (для спойла)
TARGET_SELECTED_POINT_REL     = (876, 60)  # Подтверждение выбранного таргета
TARGET_MOB_POINT2_REL         = (875, 60)  # Вторая точка подтверждения таргета моба
CHAR_HP_POINT_REL             = (305, 46)  # Пиксель HP персонажа (для HP_POTION)
CHAR_MP_POINT_REL             = (305, 59)   # Пиксель MP персонажа (для MP_SKILL)

# ----- Цвета и порог (Примерные цвета для mw.bin, замените на свои) -----
TARGET_COLOR      = [(54, 35, 29), (117, 26, 33), (111, 23, 19)]    # Основные цвета HP цели
CHAR_HP_COLOR     = (137, 32, 21)  # Цвет полоски HP персонажа (ЯРКО-КРАСНЫЙ)
CHAR_MP_COLOR     = (5, 57, 134)   # Цвет полоски MP персонажа
TARGET_HP_DAMAGED_COLOR = (59, 44, 39)  # Цвет пикселя "HP цели (Поврежден)"
TARGET_MOB_COLOR = [(171, 150, 117), (170, 150, 117)]  # Цвет таргета моба
TARGET_MOB_COLOR2 = (159, 153, 119)  # Цвет таргета моба (2-я точка)
COLOR_THRESHOLD   = 2               # Порог для is_color_match

# ----- Поиск удачного спойла (Примерные координаты/цвет для mw.bin, замените на свои) -----
GREEN_PIXEL_SEARCH_AREA_REL  = (4, 749, 348, 870 ) # Область поиска зелёного пикселя верх лево и право низ 21, 829, 133, 843
GREEN_PIXEL_POINT_REL        = (89, 834)            # Точка проверки удачного спойла (предпочтительнее области)
GREEN_PIXEL_COLOR       = (150, 249, 1)      # Цвет целевого зелёного пикселя

# ----- Поиск отката скила (Примерные координаты/цвет для mw.bin, замените на свои) -----
SKILL_RESET_POINT_REL  = (729, 971)  # Координаты иконки скилла для проверки отката
SKILL_RESET_COLOR = (55, 26, 2) # Цвет иконки отката скила (когда не готов)

# ----- Прямоугольники для анализа полосок (HP, MP и т.д.) -----
# Область для анализа полоски HP. Должна охватывать ВСЮ длину полоски.
# Мы будем сканировать эту область и считать процент ярко-красных пикселей.
HP_BAR_RECT_REL = (20, 41, 493, 50)  # (лево, верх, право, низ)
MP_RECT_REL  = (125, 85, 155, 102) # Область OCR для MP персонажа

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
# --- Управление целями ---
STUCK_TARGET_TIMEOUT = 13.0 # Время в секундах, чтобы считать цель "застрявшей"
TARGET_SWITCH_DELAY = 1.5 # Задержка перед поиском новой цели (УВЕЛИЧЕНО ДЛЯ СТАБИЛЬНОСТИ)
NEXT_TARGET_MIN    = 0.2
NEXT_TARGET_MAX    = 0.5
LOOT_MIN           = 0.05
LOOT_MAX           = 0.15
SWEEP_TO_LOOT_MIN  = 0.3
SWEEP_TO_LOOT_MAX  = 0.6
LOOT_REPEAT_COUNT  = 3

# --- Использование расходников и скиллов ---
POTION_INTERVAL    = 15.0
MP_SKILL_INTERVAL  = 1.0
ATTACK_INTERVAL_MIN = 6.0
ATTACK_INTERVAL_MAX = 8.0

# --- Логика спойла ---
SPOIL_ATTEMPT_INTERVAL_MIN = 0.85
SPOIL_ATTEMPT_INTERVAL_MAX = 1.4

# --- Наблюдение за угрозой ---
THREAT_WATCH_DURATION = 2.0
THREAT_WATCH_BASE_DURATION                      = 0.1
THREAT_WATCH_BASE_DURATION_DELTA                = 0.2
THREAT_WATCH_EXTRA_DURATION_AFTER_NEXT          = 1.5
THREAT_WATCH_EXTRA_DURATION_AFTER_NEXT_DELTA    = 0.5
THREAT_WATCH_CHECK_INTERVAL                     = 0.1
THREAT_POST_NEXT_DELAY_RANGE                    = (2.0, 3.0)

# ----- Конфиг оверлея паузы -----
OVERLAY_ALPHA = 0.5
OVERLAY_POSITION_X  = 25
OVERLAY_POSITION_Y  = 442

# ----- Подсветка мобов -----
NAME_SEARCH_AREA_REL  = (0,127,1916,875)
MOB_NAMES = [
    "Hunter Bear",
    "Goblin Brigand Leader",
]
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
FLAG_RETURN_TO_TARGET_ENABLED   = False # Использовать возврат к таргету для монстров с 1 ХП
FLAG_STUCK_TARGET_ENABLED       = True  # Новая опция: включить/выключить сброс застрявшей цели
FLAG_FLAGSTOP_ENABLED           = True

# ----- Настройки двойного клика (perform_double_click) -----
DOUBLE_CLICK_POINT_REL  = (160, 255)
DOUBLE_CLICK_MOVE_DURATION_MIN = 0.4
DOUBLE_CLICK_MOVE_DURATION_MAX = 0.8
DOUBLE_CLICK_PAUSE_MIN = 1.0
DOUBLE_CLICK_PAUSE_MAX = 1.6

# ----- Пиксель Flagstop (для HUD и отладки) -----
FLAGSTOP_POINT_REL = (952, 503)

# ----- Настройки экшена Возврат к таргету (для монстров с 1 ХП) -----
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
FLAG_BUTTON_TEXT_STUCK_TARGET       = "Анти-стук" # Новый текст для кнопки

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
    # --- Координаты пикселей ---
    "TARGET_HP_1_POINT": "Пиксель 1 HP цели (MW)",
    "TARGET_HP_DAMAGED_POINT": "Пиксель поврежденной цели (MW)",
    "TARGET_HP_FULL_POINT": "Пиксель полного HP цели (MW)",
    "CHAR_HP_POINT": "Пиксель HP персонажа (MW)",
    "CHAR_MP_POINT": "Пиксель MP персонажа (MW)",
    "SKILL_RESET_POINT": "Пиксель сброса скилла (MW)",
    "DOUBLE_CLICK_POINT": "Точка двойного клика (MW)",
    "FLAGSTOP_POINT": "Пиксель Flagstop (MW)",

    # --- Прямоугольники для OCR ---
    "HP_BAR_RECT": "Область полоски HP персонажа (MW)",
    "MP_RECT": "Область OCR MP персонажа (MW)",

    # --- Области поиска ---
    "GREEN_PIXEL_SEARCH_AREA": "Зона поиска зелёного пикселя (MW)",
    "NAME_SEARCH_AREA": "Зона поиска имени моба (MW)",

    # --- Настройки интервалов ---
    "POTION_INTERVAL": "Интервал HP Банки",
    "MP_SKILL_INTERVAL": "Интервал MP Скилла",
    "NEXT_TARGET_MIN": "Мин. интервал NEXT TARGET",
    "NEXT_TARGET_MAX": "Макс. интервал NEXT TARGET",
    "LOOT_REPEAT_COUNT": "Кол-во лута",
    "STUCK_TARGET_TIMEOUT": "Таймаут застрявшей цели"
}

# Прозрачность элементов HUD
HUD_ELEMENT_ALPHA = 0.5

# ----- Настройки бафов (F1..F12) -----
# Включено ли выполнение цикла бафов
FLAG_BUFF_ENABLED = False
# Последовательность клавиш для нажатия в одном цикле
# Возможные значения: 'F1'..'F12'
BUFF_SEQUENCE = ['F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12']
# Задержка удержания клавиши (мс)
BUFF_KEY_PRESS_MS = 50.0
# Сколько раз нажимать каждую клавишу в цикле
BUFF_PER_KEY_PRESS_COUNT = 5
# Пауза между повторами одной и той же клавиши (сек)
BUFF_INTRA_PRESS_DELAY = 0.2
# Пауза между разными клавишами (сек)
BUFF_BETWEEN_KEYS_DELAY = 6.0
# Общий интервал между циклами (сек) — 17 минут
BUFF_CYCLE_INTERVAL = 17 * 60.0

# Текст кнопки в оверлее для бафов
FLAG_BUTTON_TEXT_BUFF = "Бафы (F1-F12)"
