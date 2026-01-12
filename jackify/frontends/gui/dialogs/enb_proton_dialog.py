"""
ENB Proton Compatibility Dialog

Shown when ENB is detected in a modlist installation to warn users
about Proton version requirements for ENB compatibility.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, 
    QSpacerItem, QSizePolicy, QFrame, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont

logger = logging.getLogger(__name__)


class ENBProtonDialog(QDialog):
    """
    Dialog shown when ENB is detected, warning users about Proton version requirements.
    
    Features:
    - Clear warning about ENB compatibility
    - Ordered list of recommended Proton versions
    - Prominent display to ensure users see it
    """
    
    def __init__(self, modlist_name: str, parent=None):
        super().__init__(parent)
        self.modlist_name = modlist_name
        self.setWindowTitle("ENB Detected - Proton Version Required")
        self.setWindowModality(Qt.ApplicationModal)  # Modal to ensure user sees it
        self.setFixedSize(600, 550)  # Increased height to show full Proton version list and button spacing
        self.setStyleSheet("QDialog { background: #181818; color: #fff; border-radius: 12px; }")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(30, 30, 30, 30)

        # --- Card background for content ---
        card = QFrame(self)
        card.setObjectName("enbCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setFixedWidth(540)
        card.setMinimumHeight(400)  # Increased to accommodate full Proton version list
        card.setMaximumHeight(16777215)  # Remove max height constraint to allow expansion
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card.setStyleSheet(
            "QFrame#enbCard { "
            "  background: #23272e; "
            "  border-radius: 12px; "
            "  border: 2px solid #e67e22; "  # Orange border for warning
            "}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        # Warning title (orange/warning color)
        title_label = QLabel("ENB Detected")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "QLabel { "
            "  font-size: 24px; "
            "  font-weight: 700; "
            "  color: #e67e22; "  # Orange warning color
            "  margin-bottom: 4px; "
            "}"
        )
        card_layout.addWidget(title_label)

        # Main warning message
        warning_text = (
            f"If you plan on using ENB as part of <span style='color:#3fb7d6; font-weight:600;'>{self.modlist_name}</span>, "
            f"you will need to use one of the following Proton versions, otherwise you will have issues running the modlist:"
        )
        warning_label = QLabel(warning_text)
        warning_label.setAlignment(Qt.AlignCenter)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(
            "QLabel { "
            "  font-size: 14px; "
            "  color: #e0e0e0; "
            "  line-height: 1.5; "
            "  margin-bottom: 12px; "
            "  padding: 8px; "
            "}"
        )
        warning_label.setTextFormat(Qt.RichText)
        card_layout.addWidget(warning_label)

        # Proton version list (in order of recommendation)
        versions_text = (
            "<div style='text-align: left; padding: 12px; background: #1a1d23; border-radius: 8px; margin: 8px 0;'>"
            "<div style='font-size: 13px; color: #b0b0b0; margin-bottom: 8px;'><b style='color: #fff;'>(In order of recommendation)</b></div>"
            "<div style='font-size: 14px; color: #fff; line-height: 1.8;'>"
            "• <b style='color: #2ecc71;'>Proton-CachyOS</b><br/>"
            "• <b style='color: #3498db;'>GE-Proton 10-14</b> or <b style='color: #3498db;'>lower</b><br/>"
            "• <b style='color: #f39c12;'>Proton 9</b> from Valve"
            "</div>"
            "</div>"
        )
        versions_label = QLabel(versions_text)
        versions_label.setAlignment(Qt.AlignLeft)
        versions_label.setWordWrap(True)
        versions_label.setStyleSheet(
            "QLabel { "
            "  font-size: 14px; "
            "  color: #e0e0e0; "
            "  line-height: 1.6; "
            "  margin: 8px 0; "
            "}"
        )
        versions_label.setTextFormat(Qt.RichText)
        card_layout.addWidget(versions_label)

        # Additional note
        note_text = (
            "<div style='font-size: 12px; color: #95a5a6; font-style: italic; margin-top: 8px;'>"
            "Note: Valve's Proton 10 has known ENB compatibility issues."
            "</div>"
        )
        note_label = QLabel(note_text)
        note_label.setAlignment(Qt.AlignCenter)
        note_label.setWordWrap(True)
        note_label.setStyleSheet(
            "QLabel { "
            "  font-size: 12px; "
            "  color: #95a5a6; "
            "  font-style: italic; "
            "  margin-top: 8px; "
            "}"
        )
        note_label.setTextFormat(Qt.RichText)
        card_layout.addWidget(note_label)

        layout.addStretch()
        layout.addWidget(card, alignment=Qt.AlignCenter)
        layout.addSpacing(20)  # Add spacing between card and button

        # OK button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.ok_btn = QPushButton("I Understand")
        self.ok_btn.setStyleSheet(
            "QPushButton { "
            "  background: #3fb7d6; "
            "  color: #fff; "
            "  border: none; "
            "  border-radius: 6px; "
            "  padding: 10px 24px; "
            "  font-size: 14px; "
            "  font-weight: 600; "
            "}"
            "QPushButton:hover { "
            "  background: #35a5c2; "
            "}"
            "QPushButton:pressed { "
            "  background: #2d8fa8; "
            "}"
        )
        self.ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.ok_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Set the Wabbajack icon if available
        self._set_dialog_icon()
        
        logger.info(f"ENBProtonDialog created for modlist: {modlist_name}")
    
    def _set_dialog_icon(self):
        """Set the dialog icon to Wabbajack icon if available"""
        try:
            icon_path = Path(__file__).parent.parent.parent.parent.parent / "Files" / "wabbajack-icon.png"
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self.setWindowIcon(icon)
        except Exception as e:
            logger.debug(f"Could not set dialog icon: {e}")

