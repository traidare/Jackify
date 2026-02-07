"""
File progress item widget for a single file's progress display.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QProgressBar, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from jackify.shared.progress_models import FileProgress, OperationType
from ..shared_theme import JACKIFY_COLOR_BLUE


class FileProgressItem(QWidget):
    """Widget representing a single file's progress."""

    def __init__(self, file_progress: FileProgress, parent=None):
        super().__init__(parent)
        self.file_progress = file_progress
        self._target_percent = file_progress.percent
        self._current_display_percent = file_progress.percent
        self._spinner_position = 0
        self._is_indeterminate = False
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_progress)
        self._animation_timer.setInterval(16)
        self._setup_ui()
        self._update_display()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        operation_label = QLabel(self._get_operation_symbol())
        operation_label.setFixedWidth(20)
        operation_label.setAlignment(Qt.AlignCenter)
        operation_label.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-weight: bold;")
        layout.addWidget(operation_label)

        filename_label = QLabel(self._truncate_filename(self.file_progress.filename))
        filename_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filename_label.setToolTip(self.file_progress.filename)
        filename_label.setStyleSheet("color: #ccc; font-size: 11px;")
        layout.addWidget(filename_label, 1)
        self.filename_label = filename_label

        percent_label = QLabel()
        percent_label.setFixedWidth(40)
        percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        percent_label.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(percent_label)
        self.percent_label = percent_label

        progress_bar = QProgressBar()
        progress_bar.setFixedHeight(12)
        progress_bar.setFixedWidth(80)
        progress_bar.setTextVisible(False)
        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 2px;
                background-color: #1a1a1a;
            }}
            QProgressBar::chunk {{
                background-color: {JACKIFY_COLOR_BLUE};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(progress_bar)
        self.progress_bar = progress_bar

    def _get_operation_symbol(self) -> str:
        symbols = {
            OperationType.DOWNLOAD: "↓",
            OperationType.EXTRACT: "↻",
            OperationType.VALIDATE: "✓",
            OperationType.INSTALL: "→",
        }
        return symbols.get(self.file_progress.operation, "•")

    def _truncate_filename(self, filename: str, max_length: int = 40) -> str:
        if len(filename) <= max_length:
            return filename
        return filename[:max_length-3] + "..."

    def _update_display(self):
        is_summary = hasattr(self.file_progress, '_is_summary') and self.file_progress._is_summary
        no_progress_bar = hasattr(self.file_progress, '_no_progress_bar') and self.file_progress._no_progress_bar

        if 'Installing Files' in self.file_progress.filename or 'Converting Texture' in self.file_progress.filename or 'BSA:' in self.file_progress.filename:
            name_display = self.file_progress.filename
        elif self.file_progress.filename.startswith('Wine component:'):
            rest = self.file_progress.filename.split(':', 1)[1].strip()
            comp_id = rest.split('|')[0].strip() if '|' in rest else rest
            name_display = f"Installing {comp_id}..."
        else:
            name_display = self._truncate_filename(self.file_progress.filename)

        if not is_summary and not no_progress_bar:
            size_display = self.file_progress.size_display
            if size_display:
                name_display = f"{name_display} ({size_display})"

        self.filename_label.setText(name_display)
        self.filename_label.setToolTip(self.file_progress.filename)

        if no_progress_bar:
            self._animation_timer.stop()
            self.percent_label.setText("")
            self.progress_bar.setVisible(False)
            return

        self.progress_bar.setVisible(True)

        if is_summary:
            summary_step = getattr(self.file_progress, '_summary_step', 0)
            summary_max = getattr(self.file_progress, '_summary_max', 0)

            if summary_max > 0:
                percent = (summary_step / summary_max) * 100.0
                self._target_percent = max(0, min(100, percent))
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
                self.progress_bar.setRange(0, 100)
            else:
                self._is_indeterminate = True
                self.percent_label.setText("")
                self.progress_bar.setRange(0, 100)
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
            return

        is_queued = (
            self.file_progress.total_size > 0 and
            self.file_progress.percent == 0 and
            self.file_progress.current_size == 0 and
            self.file_progress.speed <= 0
        )

        if is_queued:
            self._is_indeterminate = False
            self._animation_timer.stop()
            self.percent_label.setText("Queued")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            return

        has_meaningful_progress = (
            self.file_progress.percent > 0 or
            (self.file_progress.total_size > 0 and self.file_progress.current_size > 0) or
            (self.file_progress.speed > 0 and self.file_progress.percent >= 0)
        )

        if has_meaningful_progress:
            self._is_indeterminate = False
            self._target_percent = max(0, self.file_progress.percent)
            if not self._animation_timer.isActive():
                self._animation_timer.start()
            self.progress_bar.setRange(0, 100)
        else:
            self._is_indeterminate = True
            self.percent_label.setText("")
            self.progress_bar.setRange(0, 100)
            if not self._animation_timer.isActive():
                self._animation_timer.start()

    def _animate_progress(self):
        if self._is_indeterminate:
            self._spinner_position = (self._spinner_position + 4) % 200
            if self._spinner_position < 100:
                display_value = self._spinner_position
            else:
                display_value = 200 - self._spinner_position
            self.progress_bar.setValue(display_value)
        else:
            diff = self._target_percent - self._current_display_percent
            if abs(diff) >= 0.1:
                self._current_display_percent += diff * 0.2
            self._current_display_percent = max(0, min(100, self._current_display_percent))

            display_percent = self._current_display_percent
            self.progress_bar.setValue(int(display_percent))
            if self.file_progress.percent > 0:
                self.percent_label.setText(f"{display_percent:.0f}%")
            else:
                self.percent_label.setText("")

    def update_progress(self, file_progress: FileProgress):
        self.file_progress = file_progress
        self._update_display()

    def cleanup(self):
        if self._animation_timer.isActive():
            self._animation_timer.stop()
