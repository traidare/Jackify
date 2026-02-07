"""
Summary progress widget for phase display (e.g. Installing 123/456).
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import QTimer


class SummaryProgressWidget(QWidget):
    """Widget showing summary progress for phases like Installing."""

    def __init__(self, phase_name: str, current_step: int, max_steps: int, parent=None):
        super().__init__(parent)
        self.phase_name = phase_name
        self.current_step = current_step
        self.max_steps = max_steps
        self._target_step = current_step
        self._target_max = max_steps
        self._display_step = current_step
        self._display_max = max_steps
        self._interpolation_timer = QTimer(self)
        self._interpolation_timer.timeout.connect(self._interpolate_counter)
        self._interpolation_timer.setInterval(16)
        self._interpolation_timer.start()
        self._setup_ui()
        self._update_display()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.text_label = QLabel()
        self.text_label.setStyleSheet("color: #ccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(self.text_label)

    def _interpolate_counter(self):
        step_diff = self._target_step - self._display_step
        if abs(step_diff) < 0.5:
            self._display_step = self._target_step
        else:
            self._display_step += step_diff * 0.2

        max_diff = self._target_max - self._display_max
        if abs(max_diff) < 0.5:
            self._display_max = self._target_max
        else:
            self._display_max += max_diff * 0.2

        self._update_display()

    def _update_display(self):
        display_step = int(round(self._display_step))
        display_max = int(round(self._display_max))

        if display_max > 0:
            new_text = f"{self.phase_name} ({display_step}/{display_max})"
        else:
            new_text = f"{self.phase_name}"

        if self.text_label.text() != new_text:
            self.text_label.setText(new_text)

    def update_progress(self, current_step: int, max_steps: int):
        self._target_step = current_step
        self._target_max = max_steps
        self.current_step = current_step
        self.max_steps = max_steps
