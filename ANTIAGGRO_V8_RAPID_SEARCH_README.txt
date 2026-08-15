KiraSOP anti-aggro v8 + Rapid Target Search
============================================

Основа: targeting/threat_watcher из v7.

НОВОЕ
-----
В основном оверлее добавляется кнопка:
    Поиск цели x10 OFF / ON

OFF:
    Старое поведение. После NEXT_TARGET/NEXT_TARGET_2 используется обычный
    config.TARGET_SWITCH_DELAY.

ON:
    Пока нет цели, запускается отдельный worker поиска. Он отправляет команду
    примерно раз в 0.10 секунды (~10 команд/сек), поэтому частота меньше зависит
    от загрузки основного bot_loop.

    Целей: 1 (5):
        NEXT_TARGET, NEXT_TARGET, NEXT_TARGET ...

    Целей: 2 (5,6):
        NEXT_TARGET, NEXT_TARGET_2, NEXT_TARGET, NEXT_TARGET_2 ...
        то есть 5 -> 6 -> 5 -> 6 примерно с общим темпом 10 команд/сек.

Как только TARGET_HP_1_POINT показывает валидную цель, обычный поиск больше
не вызывается, поэтому спам прекращается автоматически.

Anti-aggro NEAREST_TARGET НЕ ускоряется и работает по алгоритму v7.

УСТАНОВКА
---------
1. Распаковать архив в корень KiraSOP с заменой targeting.py/threat_watcher.py.
2. Запустить INSTALL_V8.bat один раз.
   Или: python apply_v8_overlay_patch.py
3. Перезапустить бот.

Патчер изменяет только la2_bot/ui/bot_menu.py и перед первым изменением делает:
    la2_bot/ui/bot_menu.py.v8_backup

Состояние кнопки хранится через существующий hud_settings, как остальные флаги.

ЛОГ
---
В x10 режиме появляются события:
    RAPID_TARGET_SEARCH_START
    RAPID_TARGET_SEARCH_COMMAND
    RAPID_TARGET_SEARCH_STOP

Обычный режим по-прежнему пишет NORMAL_TARGET_COMMAND.
