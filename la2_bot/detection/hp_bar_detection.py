# la2_bot/detection/hp_bar_detection.py
from PIL import ImageGrab
from la2_bot.utils import coordinate_utils

def get_hp_percentage():
    """
    Анализирует область полоски HP и возвращает процент заполнения.

    Сканирует горизонтальную линию пикселей внутри `HP_BAR_RECT_REL`,
    находит последний пиксель, который является "красным" (R > G + B),
    и вычисляет процент HP на основе его положения.

    Возвращает:
        float: Процент HP (от 0.0 до 100.0) или None, если область не задана.
    """
    if not coordinate_utils.HP_BAR_RECT:
        return None

    try:
        # Захватываем только область полоски HP
        hp_bar_img = ImageGrab.grab(bbox=coordinate_utils.HP_BAR_RECT)
        width, height = hp_bar_img.size

        # Сканируем пиксели по центру высоты полоски
        y = height // 2

        last_hp_x = -1
        # Идем справа налево, чтобы найти границу между "пустой" и "полной" полоской
        for x in range(width - 1, -1, -1):
            r, g, b = hp_bar_img.getpixel((x, y))
            # Ищем "красный" пиксель, характерный для полоски HP.
            # Условие: красный компонент значительно больше суммы зеленого и синего.
            # Это условие хорошо работает для большинства оттенков красного,
            # игнорируя серые, черные или другие цвета "пустой" части.
            if r > g + b and r > 50:  # Добавим порог для красного, чтобы избежать темных/черных пикселей
                last_hp_x = x
                break  # Нашли самый правый пиксель HP, выходим
        
        if last_hp_x == -1:
            # Если красных пикселей не найдено, скорее всего, HP = 0
            return 0.0

        # Рассчитываем процент
        percentage = ((last_hp_x + 1) / width) * 100.0
        return percentage

    except Exception as e:
        print(f"[HP Detector] Ошибка при анализе полоски HP: {e}")
        return None
