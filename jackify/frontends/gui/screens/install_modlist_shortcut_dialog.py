"""Steam shortcut conflict dialog and retry workflow for InstallModlistScreen (Mixin)."""
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
)
from jackify.frontends.gui.services.message_service import MessageService


class InstallModlistShortcutDialogMixin:
    """Mixin providing shortcut conflict dialog and retry-with-new-name for InstallModlistScreen."""

    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve shortcut name conflicts."""
        conflict_names = [c['name'] for c in conflicts]
        conflict_info = f"Found existing Steam shortcut: '{conflict_names[0]}'"

        modlist_name = self.modlist_name_edit.text().strip()

        dialog = QDialog(self)
        dialog.setWindowTitle("Steam Shortcut Conflict")
        dialog.setModal(True)
        dialog.resize(450, 180)

        dialog.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px 0px;
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
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        conflict_label = QLabel(f"{conflict_info}\n\nPlease choose a different name for your shortcut:")
        layout.addWidget(conflict_label)

        name_input = QLineEdit(modlist_name)
        name_input.selectAll()
        layout.addWidget(name_input)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        create_button = QPushButton("Create with New Name")
        cancel_button = QPushButton("Cancel")

        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(create_button)
        layout.addLayout(button_layout)

        def on_create():
            new_name = name_input.text().strip()
            if new_name and new_name != modlist_name:
                dialog.accept()
                self.retry_automated_workflow_with_new_name(new_name)
            elif new_name == modlist_name:
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")

        def on_cancel():
            dialog.reject()
            self._safe_append_text("Shortcut creation cancelled by user")

        create_button.clicked.connect(on_create)
        cancel_button.clicked.connect(on_cancel)
        name_input.returnPressed.connect(on_create)

        dialog.exec()

    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name."""
        self.modlist_name_edit.setText(new_name)
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self.start_automated_prefix_workflow()
