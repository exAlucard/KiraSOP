import sys
import threading
from collections import deque


_lock = threading.Lock()
_buffer = deque(maxlen=2000)


def append_line(line: str):
    if not line:
        return
    with _lock:
        _buffer.append(line)


def get_lines():
    with _lock:
        return list(_buffer)


class _StreamRedirector:
    def __init__(self, original_stream, prefix: str = ""):
        self._original_stream = original_stream
        self._prefix = prefix
        self._partial = ""

    def write(self, s):
        try:
            if self._original_stream is not None:
                self._original_stream.write(s)
        except Exception:
            pass

        if not s:
            return

        text = self._partial + str(s)
        lines = text.splitlines(True)

        self._partial = ""
        for part in lines:
            if part.endswith("\n") or part.endswith("\r"):
                clean = part.rstrip("\r\n")
                append_line(f"{self._prefix}{clean}")
            else:
                self._partial += part

    def flush(self):
        try:
            if self._original_stream is not None:
                self._original_stream.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return bool(self._original_stream and self._original_stream.isatty())
        except Exception:
            return False


_installed = False


def install_stdout_capture():
    global _installed
    if _installed:
        return
    _installed = True

    sys.stdout = _StreamRedirector(sys.stdout, prefix="")
    sys.stderr = _StreamRedirector(sys.stderr, prefix="[stderr] ")
