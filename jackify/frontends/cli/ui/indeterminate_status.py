"""Single-line CLI pulser for indeterminate background stages."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Optional


class CliIndeterminateStatus:
    """Render one in-place pulsing status line for long-running CLI steps."""

    def __init__(self, output=None, interval: float = 0.12):
        self._output = output or sys.stdout
        self._interval = interval
        self._interactive = bool(getattr(self._output, "isatty", lambda: False)())
        self._message: Optional[str] = None
        self._printed_message: Optional[str] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def set(self, message: str) -> None:
        """Start or update the active pulsing message."""
        cleaned = (message or "").strip()
        if not cleaned:
            self.stop()
            return
        if not self._interactive:
            if cleaned != self._printed_message:
                print(cleaned, file=self._output, flush=True)
                self._printed_message = cleaned
            return
        with self._lock:
            self._message = cleaned
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the pulser and clear its terminal line."""
        if not self._interactive:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None
        with self._lock:
            self._message = None
        self._output.write("\r\033[2K")
        self._output.flush()

    def close(self) -> None:
        self.stop()

    def _run(self) -> None:
        for frame in itertools.cycle("|/-\\"):
            if self._stop_event.wait(self._interval):
                return
            with self._lock:
                message = self._message
            if not message:
                continue
            self._output.write(f"\r\033[2K{message} {frame}")
            self._output.flush()

