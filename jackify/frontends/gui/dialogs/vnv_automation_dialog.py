"""
VNV Automation Confirmation Dialog

Custom dialog for VNV automation confirmation with optional BSA decompression checkbox.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QCheckBox, QFrame, QTextEdit, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class VNVAutomationDialog(QDialog):
    """Dialog for confirming VNV automation with optional BSA decompression."""
    
    def __init__(self, parent=None, description: str = ""):
        super().__init__(parent)
        self.setWindowTitle("VNV Post-Install Automation")
        self.setModal(True)
        self.setFixedSize(600, 450)
        self.setStyleSheet("QDialog { background: #181818; color: #fff; }")
        
        # Result: (confirmed: bool, include_bsa: bool)
        self.result_data = (False, True)
        
        self.setup_ui(description)
    
    def setup_ui(self, description: str):
        """Set up the dialog UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Card background for content
        card = QFrame(self)
        card.setObjectName("vnvCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setStyleSheet(
            "QFrame#vnvCard { "
            "  background: #2d2d2d; "
            "  border-radius: 12px; "
            "  border: 1px solid #555; "
            "}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)
        card_layout.setContentsMargins(28, 28, 28, 28)
        
        # Description text - use QTextEdit for scrollable long text
        description_text = QTextEdit()
        description_text.setPlainText(description)
        description_text.setReadOnly(True)
        description_text.setMaximumHeight(200)
        description_text.setStyleSheet(
            "QTextEdit { "
            "  background: #1a1a1a; "
            "  color: #fff; "
            "  border: 1px solid #555; "
            "  border-radius: 4px; "
            "  padding: 8px; "
            "}"
        )
        card_layout.addWidget(description_text)
        
        # BSA Decompression checkbox
        self.bsa_checkbox = QCheckBox("Include BSA Decompression")
        self.bsa_checkbox.setChecked(True)  # Default to checked
        self.bsa_checkbox.setStyleSheet("color: #fff; padding: 5px;")
        card_layout.addWidget(self.bsa_checkbox)
        
        card_layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.yes_button = QPushButton("Yes")
        self.yes_button.setDefault(True)
        self.yes_button.setMinimumWidth(100)
        self.yes_button.clicked.connect(self.accept_dialog)
        button_layout.addWidget(self.yes_button)
        
        self.no_button = QPushButton("No")
        self.no_button.setMinimumWidth(100)
        self.no_button.clicked.connect(self.reject_dialog)
        button_layout.addWidget(self.no_button)
        
        card_layout.addLayout(button_layout)
        main_layout.addWidget(card)
    
    def accept_dialog(self):
        """Handle Yes button click."""
        self.result_data = (True, self.bsa_checkbox.isChecked())
        self.accept()
    
    def reject_dialog(self):
        """Handle No button click."""
        self.result_data = (False, False)
        self.reject()
    
    def get_result(self) -> tuple[bool, bool]:
        """
        Get the dialog result.
        
        Returns:
            Tuple of (confirmed: bool, include_bsa_decompression: bool)
        """
        return self.result_data

