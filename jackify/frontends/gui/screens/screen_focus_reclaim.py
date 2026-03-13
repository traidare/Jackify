"""Shared mixin for reclaiming window focus after Steam restart."""
import logging
from PySide6.QtCore import QTimer, Qt

logger = logging.getLogger(__name__)

STEAM_RESTART_SENTINEL = "[Jackify] Steam restart complete"


class FocusReclaimMixin:
    """Mixin providing post-Steam-restart focus reclaim for any screen.

    Usage: inherit this mixin and call _start_focus_reclaim_retries() when
    Steam restart is detected. Detection is typically done by checking
    progress messages for STEAM_RESTART_SENTINEL.
    """

    def _start_focus_reclaim_retries(self):
        try:
            if hasattr(self, "_focus_reclaim_timer") and self._focus_reclaim_timer:
                self._focus_reclaim_timer.stop()
                self._focus_reclaim_timer.deleteLater()
        except Exception:
            pass

        self._focus_reclaim_attempt = 0
        self._focus_reclaim_max_attempts = 12  # ~24 seconds total
        self._focus_reclaim_timer = QTimer(self)
        self._focus_reclaim_timer.setInterval(2000)
        self._focus_reclaim_timer.timeout.connect(self._focus_reclaim_tick)
        self._focus_reclaim_timer.start()
        self._focus_reclaim_tick()

    def _focus_reclaim_tick(self):
        try:
            win = self.window()
            if win is None:
                return

            self._focus_reclaim_attempt += 1
            win.raise_()
            win.activateWindow()
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)

            if win.isActiveWindow():
                logger.info("Foreground focus reclaimed after Steam restart")
                self._focus_reclaim_timer.stop()
                return

            if self._focus_reclaim_attempt >= self._focus_reclaim_max_attempts:
                logger.warning("Foreground focus reclaim timed out after Steam restart")
                self._focus_reclaim_timer.stop()
        except Exception as e:
            logger.debug(f"Focus reclaim tick failed: {e}")
            try:
                self._focus_reclaim_timer.stop()
            except Exception:
                pass
