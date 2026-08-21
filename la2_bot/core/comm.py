# la2_bot/core/comm.py
import time
import threading
import serial
from serial.tools import list_ports
from la2_bot.config import config
from la2_bot.core.state import pause_event


def find_arduino_port(vid, pid):
    for port in list_ports.comports():
        if (port.vid, port.pid) == (vid, pid) or 'Arduino' in (port.description or ''):
            return port.device
    raise IOError("Arduino не найден")


class ResilientSerial:
    """Обёртка над serial.Serial с полной пересоздачей соединения при ошибках."""

    def __init__(self, vid, pid, baud_rate, timeout=1):
        self._vid = vid
        self._pid = pid
        self._baud_rate = baud_rate
        self._timeout = timeout
        self._lock = threading.Lock()
        self._ser = None
        self._port = None
        self._connect_initial()

    def _connect_initial(self):
        port = find_arduino_port(self._vid, self._pid)
        ser = serial.Serial(port, self._baud_rate, timeout=self._timeout)
        time.sleep(2)
        self._ser = ser
        self._port = port
        print(f"Connected to Arduino on {port}")

    def _reconnect(self):
        """Полностью пересоздать соединение с поиском Arduino по VID/PID."""
        try:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        except Exception:
            pass

        port = find_arduino_port(self._vid, self._pid)
        ser = serial.Serial(port, self._baud_rate, timeout=self._timeout)
        time.sleep(2)
        self._ser = ser
        self._port = port
        print(f"Reconnected to Arduino on {port}")

    def send(self, cmd_key, max_retries=3, delay=2):
        """Отправка команды с автоматическими попытками переподключения."""
        data = config.CMD[cmd_key]
        retries = 0
        while retries < max_retries:
            try:
                with self._lock:
                    if self._ser is None or not self._ser.is_open:
                        self._reconnect()
                    self._ser.write(data)
                print(f"Sent: {cmd_key}")
                return True
            except serial.SerialException as e:
                print(f"Ошибка записи: {e}. Переподключение ({retries + 1}/{max_retries})...")
                time.sleep(delay)
                try:
                    with self._lock:
                        self._reconnect()
                except Exception as e2:
                    print(f"Не удалось пересоздать порт: {e2}")
                retries += 1
            except Exception as e:
                print(f"Неожиданная ошибка при отправке команды {cmd_key}: {e}")
                return False
        print("Не удалось отправить команду после нескольких попыток.")
        return False


def init_serial():
    """Инициализирует устойчивое соединение с Arduino и возвращает обёртку ResilientSerial."""
    return ResilientSerial(config.VID, config.PID, config.BAUD_RATE, timeout=1)


def send_command(ser, cmd_key, max_retries=3, delay=2):
    # Глобальное уважение паузы: если бот на паузе, команды не отправляем
    try:
        if not pause_event.is_set():
            # Для отладки можно раскомментировать:
            # print(f"[comm] Команда {cmd_key} не отправлена: бот на паузе")
            return False
    except Exception:
        # Если что-то пошло не так с pause_event, не блокируем работу полностью
        pass

    # Новый путь: если ser — это ResilientSerial (или совместимый объект), используем его send()
    try:
        if hasattr(ser, "send"):
            return ser.send(cmd_key, max_retries=max_retries, delay=delay)
    except Exception:
        pass

    # Fallback для обычного serial.Serial (на случай старых вызовов)
    retries = 0
    while retries < max_retries:
        try:
            ser.write(config.CMD[cmd_key])
            print(f"Sent: {cmd_key}")
            return True
        except serial.SerialException as e:
            print(f"Ошибка записи: {e}. Переподключение ({retries + 1}/{max_retries})...")
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(delay)
            try:
                ser.open()
                print("Переподключение прошло успешно")
            except Exception as e2:
                print(f"Не удалось открыть порт: {e2}")
            retries += 1
    print("Не удалось отправить команду после нескольких попыток.")
    return False

_NEXT_TARGET_COMMANDS = frozenset(("NEXT_TARGET", "NEXT_TARGET_2"))


def _is_assist_pkm_enabled():
    """Читает runtime-флаг оверлея без жёсткого циклического импорта UI -> comm."""
    try:
        # bot_menu импортирует модули, которые сами используют comm.py, поэтому
        # импорт намеренно локальный и выполняется только в момент команды.
        from la2_bot.ui.bot_menu import is_flag_enabled
        return bool(is_flag_enabled('assist_pkm'))
    except Exception as exc:
        # Ошибка UI не должна ломать сам выбор цели.
        print(f"[comm] Не удалось прочитать флаг assist_pkm: {exc}")
        return False


def send_next_target_with_assist(ser, cmd_key, max_retries=3, delay=2):
    """Отправляет NEXT_TARGET/NEXT_TARGET_2 и, при АссистПКМ, сразу RCLICK.

    Arduino сама удерживает цифровую клавишу PRESS_DELAY_MS, поэтому отдельная
    задержка между 5/6 и RCLICK на стороне Python не нужна: команды в Serial
    приходят по порядку, а ПКМ обрабатывается уже после отпускания клавиши.
    """
    if cmd_key not in _NEXT_TARGET_COMMANDS:
        raise ValueError(
            f"send_next_target_with_assist поддерживает только "
            f"NEXT_TARGET/NEXT_TARGET_2, получено: {cmd_key!r}"
        )

    sent = send_command(
        ser,
        cmd_key,
        max_retries=max_retries,
        delay=delay,
    )
    if not sent:
        return False

    if not _is_assist_pkm_enabled():
        return True

    rclick_sent = send_command(
        ser,
        'RCLICK',
        max_retries=max_retries,
        delay=delay,
    )
    if not rclick_sent:
        print(f"[comm] {cmd_key} отправлен, но RCLICK для АссистПКМ не отправился")

    # Основная команда выбора цели уже успешно ушла, поэтому сохраняем True.
    return True

