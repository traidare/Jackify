"""
Shared back/cancel behavior for screens with Show Details.

All screens that have a Cancel/Back button and optional Show Details checkbox
should use this mixin so the main window consistently collapses when leaving.
"""

from PySide6.QtCore import QSize, Qt
from ..utils import set_responsive_minimum


class ScreenBackMixin:
    """
    Mixin providing shared go_back() and collapse_show_details_before_leave().

    Requires on self: resize_request (Signal(str)), stacked_widget, main_menu_index.
    Optional: show_details_checkbox, _toggle_console_visibility (for collapse).
    """

    def go_back(self):
        """Navigate back to main menu and request main window collapse."""
        self.resize_request.emit("collapse")
        try:
            main_window = self.window()
            if main_window:
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception:
            pass
        if getattr(self, "stacked_widget", None) is not None:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

    def collapse_show_details_before_leave(self):
        """
        If Show Details is expanded, collapse it so the main window shrinks
        before we leave. Call this from cancel_and_cleanup (or any exit path)
        before go_back().
        """
        main_window = self.window()
        is_steamdeck = bool(
            getattr(main_window, "system_info", None)
            and getattr(main_window.system_info, "is_steamdeck", False)
        )
        if not hasattr(self, "show_details_checkbox") or not self.show_details_checkbox.isChecked():
            return
        self.show_details_checkbox.blockSignals(True)
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.blockSignals(False)
        if not is_steamdeck and hasattr(self, "_toggle_console_visibility"):
            self._toggle_console_visibility(Qt.Unchecked)
