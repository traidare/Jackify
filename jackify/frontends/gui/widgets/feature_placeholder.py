"""
Placeholder widget for unimplemented feature screens.
"""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt


class FeaturePlaceholder(QWidget):
    """Placeholder widget for features not yet implemented."""

    def __init__(self, stacked_widget=None):
        super().__init__()
        layout = QVBoxLayout()
        label = QLabel("[Feature screen placeholder]")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        back_btn = QPushButton("Back to Main Menu")
        if stacked_widget:
            back_btn.clicked.connect(lambda: stacked_widget.setCurrentIndex(0))
        layout.addWidget(back_btn)
        self.setLayout(layout)
