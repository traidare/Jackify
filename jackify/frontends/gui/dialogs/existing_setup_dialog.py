"""Shared dialog for existing install/shortcut detection decisions."""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def prompt_existing_setup_dialog(
    parent: QWidget,
    *,
    window_title: str,
    heading: str,
    body: str,
    existing_name: str,
    requested_name: str,
    install_dir: Optional[str] = None,
    field_label: str = "New shortcut name",
    reuse_label: str = "Use Existing Setup",
    new_label: str = "Create New Shortcut",
    cancel_label: str = "Cancel",
) -> Tuple[str, Optional[str]]:
    """
    Show the shared existing-setup dialog.

    Returns:
        ("reuse"|"new"|"cancel", new_name_or_none)
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(window_title)
    dialog.setModal(True)
    dialog.setMinimumWidth(760)
    dialog.setMinimumHeight(320)

    dialog.setStyleSheet(
        """
        QDialog {
            background: #181818;
            color: #ffffff;
            border-radius: 12px;
        }
        QFrame#dialogCard {
            background: #23272e;
            border: 1px solid #353a40;
            border-radius: 12px;
        }
        QFrame#infoCard {
            background: #2a2f36;
            border: 1px solid #3b4148;
            border-radius: 8px;
        }
        QLabel {
            color: #ffffff;
            font-size: 14px;
            padding: 0px;
        }
        QLabel#dialogTitle {
            font-size: 22px;
            font-weight: 600;
            color: #3fb7d6;
        }
        QLabel#dialogBody {
            color: #e0e0e0;
            line-height: 1.35;
        }
        QLabel#infoLabel {
            color: #c7d0d8;
            font-size: 13px;
            line-height: 1.3;
        }
        QLabel#fieldLabel {
            color: #b0b0b0;
            font-size: 12px;
        }
        QLineEdit {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #555555;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px;
            selection-background-color: #3fd0ea;
        }
        QLineEdit:focus {
            border-color: #3fd0ea;
        }
        QPushButton {
            background-color: #404040;
            color: #ffffff;
            border: 2px solid #555555;
            border-radius: 4px;
            padding: 8px 16px;
            font-size: 14px;
            min-width: 120px;
        }
        QPushButton:hover {
            background-color: #505050;
            border-color: #3fd0ea;
        }
        QPushButton:pressed {
            background-color: #303030;
        }
        """
    )

    outer_layout = QVBoxLayout(dialog)
    outer_layout.setContentsMargins(24, 20, 24, 20)
    outer_layout.setSpacing(0)

    card = QFrame(dialog)
    card.setObjectName("dialogCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(22, 22, 22, 22)
    card_layout.setSpacing(14)

    title_label = QLabel(heading)
    title_label.setObjectName("dialogTitle")
    title_label.setAlignment(Qt.AlignCenter)
    title_label.setWordWrap(True)
    card_layout.addWidget(title_label)

    body_label = QLabel(body)
    body_label.setObjectName("dialogBody")
    body_label.setAlignment(Qt.AlignCenter)
    body_label.setWordWrap(True)
    card_layout.addWidget(body_label)

    info_card = QFrame(card)
    info_card.setObjectName("infoCard")
    info_layout = QVBoxLayout(info_card)
    info_layout.setContentsMargins(14, 12, 14, 12)
    info_layout.setSpacing(6)

    info_lines = [
        f"<b>Existing shortcut:</b> {existing_name}",
        f"<b>Requested name:</b> {requested_name or existing_name}",
    ]
    if install_dir:
        info_lines.append(f"<b>Install directory:</b> {install_dir}")
    info_label = QLabel("<br>".join(info_lines))
    info_label.setObjectName("infoLabel")
    info_label.setTextFormat(Qt.RichText)
    info_label.setWordWrap(True)
    info_layout.addWidget(info_label)
    card_layout.addWidget(info_card)

    field_title = QLabel(field_label)
    field_title.setObjectName("fieldLabel")
    card_layout.addWidget(field_title)

    name_input = QLineEdit(requested_name or existing_name)
    name_input.selectAll()
    card_layout.addWidget(name_input)

    button_layout = QHBoxLayout()
    button_layout.setSpacing(10)

    reuse_button = QPushButton(reuse_label)
    cancel_button = QPushButton(cancel_label)
    new_button = QPushButton(new_label)
    for button in (reuse_button, cancel_button, new_button):
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    button_layout.addWidget(reuse_button)
    button_layout.addWidget(cancel_button)
    button_layout.addWidget(new_button)
    card_layout.addLayout(button_layout)
    outer_layout.addWidget(card)

    result = {"action": "cancel", "new_name": None}

    def on_reuse():
        result["action"] = "reuse"
        dialog.accept()

    def on_new():
        result["action"] = "new"
        result["new_name"] = name_input.text().strip()
        dialog.accept()

    def on_cancel():
        result["action"] = "cancel"
        dialog.reject()

    reuse_button.clicked.connect(on_reuse)
    new_button.clicked.connect(on_new)
    cancel_button.clicked.connect(on_cancel)
    name_input.returnPressed.connect(on_new)

    dialog.adjustSize()
    dialog.exec()
    return result["action"], result["new_name"]
