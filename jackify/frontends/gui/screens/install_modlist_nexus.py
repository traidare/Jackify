"""Nexus authentication methods for InstallModlistScreen (Mixin)."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QProgressDialog, QApplication
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
import logging
import webbrowser

logger = logging.getLogger(__name__)


class NexusAuthMixin:
    """Mixin providing Nexus authentication methods for InstallModlistScreen."""

    def _update_nexus_status(self):
        """Update the Nexus login status display"""
        authenticated, method, username = self.auth_service.get_auth_status()

        if authenticated and method == 'oauth':
            # OAuth authorised
            status_text = "Authorised"
            if username:
                status_text += f" ({username})"
            self.nexus_status.setText(status_text)
            self.nexus_status.setStyleSheet("color: #3fd0ea;")
            self.nexus_login_btn.setText("Revoke")
            self.nexus_login_btn.setVisible(True)
        elif authenticated and method == 'api_key':
            # API Key in use (fallback - configured in Settings)
            self.nexus_status.setText("API Key")
            self.nexus_status.setStyleSheet("color: #FFA726;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)
        else:
            # Not authorised
            self.nexus_status.setText("Not Authorised")
            self.nexus_status.setStyleSheet("color: #f44336;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)

    def _show_copyable_url_dialog(self, url: str):
        """Show a dialog with a copyable URL"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual Browser Open Required")
        dialog.setModal(True)
        dialog.setMinimumWidth(600)

        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Explanation label
        info_label = QLabel(
            "Could not open browser automatically.\n\n"
            "Please copy the URL below and paste it into your browser:"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #ccc; font-size: 12px;")
        layout.addWidget(info_label)

        # URL input (read-only but selectable)
        url_input = QLineEdit()
        url_input.setText(url)
        url_input.setReadOnly(True)
        url_input.selectAll()  # Pre-select text for easy copying
        url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #3fd0ea;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(url_input)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Copy button
        copy_btn = QPushButton("Copy URL")
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3fd0ea;
                color: #000;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5fdfff;
            }
        """)
        def copy_to_clipboard():
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            copy_btn.setText("Copied!")
            copy_btn.setEnabled(False)
        copy_btn.clicked.connect(copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.setLayout(layout)
        dialog.exec()

    def _handle_nexus_login_click(self):
        """Handle Nexus login button click"""
        from jackify.frontends.gui.services.message_service import MessageService

        authenticated, method, _ = self.auth_service.get_auth_status()
        if authenticated and method == 'oauth':
            # OAuth is active - offer to revoke
            reply = MessageService.question(self, "Revoke", "Revoke OAuth authorisation?", safety_level="low")
            if reply == QMessageBox.Yes:
                self.auth_service.revoke_oauth()
                self._update_nexus_status()
        else:
            # Not authorised or using API key - offer to authorise with OAuth
            reply = MessageService.question(self, "Authorise with Nexus",
                "Your browser will open for Nexus authorisation.\n\n"
                "Note: Your browser may ask permission to open 'xdg-open'\n"
                "or Jackify's protocol handler - please click 'Open' or 'Allow'.\n\n"
                "Please log in and authorise Jackify when prompted.\n\n"
                "Continue?", safety_level="low")

            if reply != QMessageBox.Yes:
                return

            # Create progress dialog
            progress = QProgressDialog(
                "Waiting for authorisation...\n\nPlease check your browser.",
                "Cancel",
                0, 0,
                self
            )
            progress.setWindowTitle("Nexus OAuth")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(400)

            # Track cancellation
            oauth_cancelled = [False]

            def on_cancel():
                oauth_cancelled[0] = True

            progress.canceled.connect(on_cancel)
            progress.show()
            QApplication.processEvents()

            # Create OAuth thread to prevent GUI freeze
            class OAuthThread(QThread):
                finished_signal = Signal(bool)
                message_signal = Signal(str)
                manual_url_signal = Signal(str)  # Signal when browser fails to open

                def __init__(self, auth_service, parent=None):
                    super().__init__(parent)
                    self.auth_service = auth_service

                def run(self):
                    def show_message(msg):
                        # Check if this is a "browser failed" message with URL
                        if "Could not open browser" in msg and "Please open this URL manually:" in msg:
                            # Extract URL from message
                            url_start = msg.find("Please open this URL manually:") + len("Please open this URL manually:")
                            url = msg[url_start:].strip()
                            self.manual_url_signal.emit(url)
                        else:
                            self.message_signal.emit(msg)

                    success = self.auth_service.authorize_oauth(show_browser_message_callback=show_message)
                    self.finished_signal.emit(success)

            oauth_thread = OAuthThread(self.auth_service, self)

            # Connect message signal to update progress dialog
            def update_progress_message(msg):
                if not oauth_cancelled[0]:
                    progress.setLabelText(f"Waiting for authorisation...\n\n{msg}")
                    QApplication.processEvents()

            # Connect manual URL signal to show copyable dialog
            def show_manual_url_dialog(url):
                if not oauth_cancelled[0]:
                    progress.hide()  # Hide progress dialog temporarily
                    self._show_copyable_url_dialog(url)
                    progress.show()

            oauth_thread.message_signal.connect(update_progress_message)
            oauth_thread.manual_url_signal.connect(show_manual_url_dialog)

            # Wait for thread completion
            oauth_success = [False]
            def on_oauth_finished(success):
                oauth_success[0] = success

            oauth_thread.finished_signal.connect(on_oauth_finished)
            oauth_thread.start()

            # Wait for thread to finish (non-blocking event loop)
            while oauth_thread.isRunning():
                QApplication.processEvents()
                oauth_thread.wait(100)  # Check every 100ms
                if oauth_cancelled[0]:
                    # User cancelled - thread will still complete but we ignore result
                    oauth_thread.wait(2000)
                    if oauth_thread.isRunning():
                        oauth_thread.terminate()
                    break

            progress.close()
            QApplication.processEvents()

            self._update_nexus_status()
            self._enable_controls_after_operation()

            # Check success first - if OAuth succeeded, ignore cancellation flag
            # (progress dialog close can trigger cancel handler even on success)
            if oauth_success[0]:
                _, _, username = self.auth_service.get_auth_status()
                if username:
                    msg = f"OAuth authorisation successful!<br><br>Authorised as: {username}"
                else:
                    msg = "OAuth authorisation successful!"
                MessageService.information(self, "Success", msg, safety_level="low")
            elif oauth_cancelled[0]:
                MessageService.information(self, "Cancelled", "OAuth authorisation cancelled.", safety_level="low")
            else:
                MessageService.warning(
                    self,
                    "Authorisation Failed",
                    "OAuth authorisation failed.\n\n"
                    "If your browser showed a blank page (e.g. Firefox on Steam Deck),\n"
                    "try again and use 'Paste callback URL' to paste the URL from the address bar.\n\n"
                    "If you see 'redirect URI mismatch', the OAuth redirect URI must be configured by Nexus.\n\n"
                    "You can configure an API key in Settings as a fallback.",
                    safety_level="medium"
                )

