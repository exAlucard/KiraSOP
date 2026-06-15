# la2_bot/utils/threat_watcher.py
"""Модуль для наблюдения за угрозой после лута цели."""

import threading
import time
import random
from la2_bot.detection.hp_bar_detection import get_hp_percentage 
from la2_bot.core.comm import send_command
from la2_bot.config import config
from la2_bot.utils.pixel_utils import get_pixel_color, is_target_color
from la2_bot.utils import coordinate_utils
from la2_bot.core.debug_state import set_threat_watcher_hp, set_next_target_cooldown
from la2_bot.utils.target_utils import is_target_selected

threat_watcher_thread = None

def is_threat_watcher_active():
    """Проверяет, активен ли поток наблюдения за угрозой."""
    global threat_watcher_thread
    return threat_watcher_thread is not None and threat_watcher_thread.is_alive()

def schedule_threat_watch(ser):
    """Планирует и запускает поток для наблюдения за угрозой (анти-агр)."""
    global threat_watcher_thread

    if is_threat_watcher_active():
        print("[threat_watcher] Поток наблюдения уже запущен, новый не создается.")
        return

    def threat_watcher_logic():
        """
        Основная логика наблюдения за угрозой.
        Активируется, если HP персонажа падает при отсутствии цели.
        """
        global threat_watcher_thread
        try:
            duration = config.THREAT_WATCH_DURATION
            end_time = time.time() + duration

            print(f"[threat_watcher] Наблюдение за угрозой активно на {duration:.2f} сек.")

            previous_hp = get_hp_percentage()
            if previous_hp is None:
                print("[threat_watcher] Не удалось считать начальное % HP, отмена наблюдения.")
                set_threat_watcher_hp(None, None, False)
                return
            
            set_threat_watcher_hp(previous_hp, previous_hp, False)

            while time.time() < end_time:
                current_hp = get_hp_percentage()
                is_falling = False
                if current_hp is not None and previous_hp is not None:
                    if current_hp < previous_hp:
                        is_falling = True
                        set_threat_watcher_hp(previous_hp, current_hp, is_falling)
                        print(f"[threat_watcher] HP % уменьшилось: {previous_hp:.1f}% -> {current_hp:.1f}%. Активирую анти-агр!")
                        
                        # Активируем кулдаун, чтобы главный цикл не мешал
                        set_next_target_cooldown(2.0) 

                        send_command(ser, 'NEAREST_TARGET')
                        print("[threat_watcher] Нажата кнопка 'NEAREST_TARGET', ожидание 1 сек.")
                        time.sleep(1)
                        
                        if is_target_color(get_pixel_color(*coordinate_utils.TARGET_HP_1_POINT)):
                            if is_target_selected():
                                print("[threat_watcher] Анти-агр успешен! Цель найдена, атакую.")
                                send_command(ser, 'ATTACK')
                            else:
                                print("[threat_watcher] Цель найдена, но таргет не подтвержден. Атаку не выполняю.")
                        else:
                            print("[threat_watcher] Анти-агр не нашел цель. Возврат к основному циклу.")
                        return
                
                set_threat_watcher_hp(previous_hp, current_hp, is_falling)
                previous_hp = current_hp
                time.sleep(config.THREAT_WATCH_CHECK_INTERVAL)
            
            print("[threat_watcher] Период наблюдения истек, угрозы не обнаружено.")

        finally:
            set_threat_watcher_hp(None, None, False)
            threat_watcher_thread = None
            print("[threat_watcher] Поток наблюдения завершен.")

    threat_watcher_thread = threading.Thread(target=threat_watcher_logic, daemon=True)
    threat_watcher_thread.start()
    print("[threat_watcher] Поток наблюдения запущен.")
