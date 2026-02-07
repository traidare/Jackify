"""Dialog management for ConfigureNewModlistScreen (Mixin)."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QApplication, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor
from pathlib import Path
from typing import Optional
import subprocess
from jackify.frontends.gui.services.message_service import MessageService

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, cli_path, game_type, project_root, log_path, mode='list-modlists', modlist_name=None, install_dir=None, download_dir=None):
        super().__init__()
        self.cli_path = cli_path
        self.game_type = game_type
        self.project_root = project_root
        self.log_path = log_path
        self.mode = mode
        self.modlist_name = modlist_name
        self.install_dir = install_dir
        self.download_dir = download_dir
    def run(self):
        # CRITICAL: Use safe Python executable to prevent AppImage recursive spawning
        from jackify.backend.handlers.subprocess_utils import get_safe_python_executable
        python_exe = get_safe_python_executable()
        
        if self.mode == 'list-modlists':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--list-modlists', '--game-type', self.game_type]
        elif self.mode == 'install':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--install', '--modlist-name', self.modlist_name, '--install-dir', self.install_dir, '--download-dir', self.download_dir, '--game-type', self.game_type]
        else:
            self.result.emit([], '[ModlistFetchThread] Unknown mode')
            return
        try:
            with open(self.log_path, 'a') as logf:
                logf.write(f"\n[Modlist Fetch CMD] {cmd}\n")
                # Use clean subprocess environment to prevent AppImage variable inheritance
                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                env = get_clean_subprocess_env()
                proc = subprocess.Popen(cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                stdout, stderr = proc.communicate()
                logf.write(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n")
                if proc.returncode == 0:
                    modlist_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
                    self.result.emit(modlist_ids, '')
                else:
                    self.result.emit([], stderr)
        except Exception as e:
            self.result.emit([], str(e))


class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from PySide6.QtWidgets import QSizePolicy
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for item in items:
            QListWidgetItem(item, self.list_widget)
        layout.addWidget(self.list_widget)
        self.selected_item = None
        self.list_widget.itemClicked.connect(self.on_item_clicked)
    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()


class ConfigureNewModlistDialogsMixin:
    """Mixin providing dialog management for ConfigureNewModlistScreen."""

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        # Stop CPU tracking if active
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

        # Clean up automated prefix thread if running
        if hasattr(self, 'automated_prefix_thread') and self.automated_prefix_thread.isRunning():
            self.automated_prefix_thread.terminate()
            self.automated_prefix_thread.wait(1000)

        # Clean up configuration thread if running
        if hasattr(self, 'config_thread') and self.config_thread.isRunning():
            self.config_thread.terminate()
            self.config_thread.wait(1000)


    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve shortcut name conflicts"""
        conflict_names = [c['name'] for c in conflicts]
        conflict_info = f"Found existing Steam shortcut: '{conflict_names[0]}'"
        
        modlist_name = self.modlist_name_edit.text().strip()
        
        # Create dialog with Jackify styling
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        from PySide6.QtCore import Qt
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Steam Shortcut Conflict")
        dialog.setModal(True)
        dialog.resize(450, 180)
        
        # Apply Jackify dark theme styling
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
        
        # Conflict message
        conflict_label = QLabel(f"{conflict_info}\n\nPlease choose a different name for your shortcut:")
        layout.addWidget(conflict_label)
        
        # Text input for new name
        name_input = QLineEdit(modlist_name)
        name_input.selectAll()
        layout.addWidget(name_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        create_button = QPushButton("Create with New Name")
        cancel_button = QPushButton("Cancel")
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(create_button)
        layout.addLayout(button_layout)
        
        # Connect signals
        def on_create():
            new_name = name_input.text().strip()
            if new_name and new_name != modlist_name:
                dialog.accept()
                # Retry workflow with new name
                self.retry_automated_workflow_with_new_name(new_name)
            elif new_name == modlist_name:
                # Same name - show warning
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                # Empty name
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
        
        def on_cancel():
            dialog.reject()
            self._safe_append_text("Shortcut creation cancelled by user")
        
        create_button.clicked.connect(on_create)
        cancel_button.clicked.connect(on_cancel)
        
        # Make Enter key work
        name_input.returnPressed.connect(on_create)
        
        dialog.exec()


    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name"""
        # Update the modlist name field temporarily
        original_name = self.modlist_name_edit.text()
        self.modlist_name_edit.setText(new_name)
        
        # Restart the automated workflow
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self._start_automated_prefix_workflow(new_name, os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), self.install_dir_edit.text().strip(), self.resolution_combo.currentText())


    def handle_validation_failure(self, missing_text):
        """Handle manual steps validation failure with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               "Please complete the manual steps and try again.", safety_level="medium")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.", safety_level="medium")
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self.modlist_name_edit.text().strip())


    def _check_and_run_vnv_automation(self, modlist_name: str, install_dir: str):
        """Check if VNV automation should run and execute if applicable

        Args:
            modlist_name: Name of the installed modlist
            install_dir: Installation directory path
        """
        try:
            from pathlib import Path
            from jackify.backend.services.vnv_integration_helper import run_vnv_automation_if_applicable, should_offer_vnv_automation
            from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
            from jackify.backend.handlers.path_handler import PathHandler

            # Get paths first (needed for VNV detection)
            install_path = Path(install_dir)
            
            # Quick check before importing more (pass install location for ModOrganizer.ini check)
            if not should_offer_vnv_automation(modlist_name, install_path):
                return
            game_paths = PathHandler().find_vanilla_game_paths()
            game_root = game_paths.get('Fallout New Vegas')

            if not game_root:
                debug_print("DEBUG: VNV automation skipped - FNV game root not found")
                return

            # Confirmation callback - show dialog to user
            def confirmation_callback(description: str) -> bool:
                from ..services.message_service import MessageService
                reply = MessageService.question(
                    self,
                    "VNV Post-Install Automation",
                    description,
                    critical=False,
                    safety_level="medium"
                )
                return reply == QMessageBox.Yes

            # Manual file callback for non-Premium users
            def manual_file_callback(title: str, instructions: str) -> Optional[Path]:
                from PySide6.QtWidgets import QFileDialog
                from ..services.message_service import MessageService

                # Show instructions
                MessageService.information(self, title, instructions)

                # Open file picker
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    title,
                    str(Path.home() / "Downloads"),
                    "All Files (*.*)"
                )

                if file_path:
                    return Path(file_path)
                return None

            # Run automation
            automation_ran, error = run_vnv_automation_if_applicable(
                modlist_name=modlist_name,
                modlist_install_location=install_path,
                game_root=game_root,
                ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                progress_callback=None,  # GUI doesn't need progress updates for post-install
                manual_file_callback=manual_file_callback,
                confirmation_callback=confirmation_callback
            )

            if error:
                from ..services.message_service import MessageService
                MessageService.warning(
                    self,
                    "VNV Automation Failed",
                    f"VNV post-install automation encountered an error:\n\n{error}\n\n"
                    "You can complete these steps manually by following the guide at:\n"
                    "https://vivanewvegas.moddinglinked.com/wabbajack.html"
                )

        except Exception as e:
            debug_print(f"ERROR: Failed to run VNV automation: {e}")
            import traceback
            debug_print(f"Traceback: {traceback.format_exc()}")


    def show_next_steps_dialog(self, message):
        dlg = QDialog(self)
        dlg.setWindowTitle("Next Steps")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        btn_row = QHBoxLayout()
        btn_return = QPushButton("Return")
        btn_exit = QPushButton("Exit")
        btn_row.addWidget(btn_return)
        btn_row.addWidget(btn_exit)
        layout.addLayout(btn_row)
        def on_return():
            dlg.accept()
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(0)
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()


