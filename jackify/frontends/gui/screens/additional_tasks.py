"""
Additional Tasks & Tools Screen

Simple screen for TTW automation only.
Follows the same pattern as ModlistTasksScreen.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from jackify.backend.models.configuration import SystemInfo
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import set_responsive_minimum

logger = logging.getLogger(__name__)


class AdditionalTasksScreen(QWidget):
    """Simple Additional Tasks screen for TTW only"""

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info: Optional[SystemInfo] = None):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        
        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface following ModlistTasksScreen pattern"""
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)  # Reduced from 40
        layout.setSpacing(12)  # Match main menu spacing
        
        # Header section
        self._setup_header(layout)
        
        # Menu buttons section
        self._setup_menu_buttons(layout)
        
        # Bottom spacer
        layout.addStretch()
        self.setLayout(layout)

    def _setup_header(self, layout):
        """Set up the header section"""
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        # Title
        title = QLabel("<b>Additional Tasks & Tools</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        # Description area with fixed height
        desc = QLabel("TTW automation, Wabbajack installer, and additional tools.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)  # Fixed height for description zone
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)

        # Separator
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setFixedWidth(400)  # Match button width
        sep.setStyleSheet("background: #fff;")
        header_layout.addWidget(sep, alignment=Qt.AlignHCenter)

        header_layout.addSpacing(10)

        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)  # Fixed total header height
        layout.addWidget(header_widget)
    
    def _setup_menu_buttons(self, layout):
        """Set up the menu buttons section"""
        # Menu options
        MENU_ITEMS = [
            ("Install TTW", "ttw_install", "Install Tale of Two Wastelands using TTW_Linux_Installer"),
            ("Install Wabbajack", "wabbajack_install", "Install Wabbajack.exe via Proton (automated setup)"),
            ("Return to Main Menu", "return_main_menu", "Go back to the main menu"),
        ]
        
        # Create grid layout for buttons (mirror ModlistTasksScreen pattern)
        button_grid = QGridLayout()
        button_grid.setSpacing(12)  # Reduced from 16
        button_grid.setAlignment(Qt.AlignHCenter)

        button_width = 400
        button_height = 40  # Reduced from 50

        for i, (label, action_id, description) in enumerate(MENU_ITEMS):
            # Create button
            btn = QPushButton(label)
            btn.setFixedSize(button_width, button_height)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4a5568;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background-color: #5a6578;
                }}
                QPushButton:pressed {{
                    background-color: {JACKIFY_COLOR_BLUE};
                }}
            """)
            btn.clicked.connect(lambda checked, a=action_id: self._handle_button_click(a))

            # Description label
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignHCenter)
            desc_label.setStyleSheet("color: #999; font-size: 11px;")  # Reduced from 12px
            desc_label.setWordWrap(True)
            desc_label.setFixedWidth(button_width)

            # Add to grid (button row, then description row)
            button_grid.addWidget(btn, i * 2, 0, Qt.AlignHCenter)
            button_grid.addWidget(desc_label, i * 2 + 1, 0, Qt.AlignHCenter)

        layout.addLayout(button_grid)

    # Removed _create_menu_button; using same pattern as ModlistTasksScreen

    def _handle_button_click(self, action_id):
        """Handle button clicks"""
        if action_id == "ttw_install":
            self._show_ttw_info()
        elif action_id == "wabbajack_install":
            self._show_wabbajack_installer()
        elif action_id == "coming_soon":
            self._show_coming_soon_info()
        elif action_id == "return_main_menu":
            self._return_to_main_menu()

    def _show_ttw_info(self):
        """Navigate to TTW installation screen"""
        if self.stacked_widget:
            # Navigate to TTW installation screen (index 5)
            self.stacked_widget.setCurrentIndex(5)

    def _show_wabbajack_installer(self):
        """Navigate to Wabbajack installer screen"""
        if self.stacked_widget:
            # Navigate to Wabbajack installer screen (index 7)
            self.stacked_widget.setCurrentIndex(7)

    def _show_coming_soon_info(self):
        """Show coming soon info"""
        from ..services.message_service import MessageService
        MessageService.information(
            self,
            "Coming Soon",
            "Additional tools and features will be added in future updates.\n\n"
            "Check back later for more functionality!"
        )

    def _return_to_main_menu(self):
        """Return to main menu"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

    def showEvent(self, event):
        """Called when the widget becomes visible - resize to compact size"""
        super().showEvent(event)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass