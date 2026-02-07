"""
ConfigureNewModlistScreen for Jackify GUI
"""
import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QCheckBox, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject
from PySide6.QtGui import QPixmap, QTextCursor
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
# Progress reporting components
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.shared.progress_models import InstallationPhase, InstallationProgress
import os
import subprocess
import sys
import threading
import time
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
import traceback
import signal
from jackify.backend.core.modlist_operations import get_jackify_engine_path
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.services.api_key_service import APIKeyService
from jackify.backend.services.resolution_service import ResolutionService
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from PySide6.QtWidgets import QApplication
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.resolution_utils import get_resolution_fallback
from .configure_new_modlist_ui_setup import ConfigureNewModlistUISetupMixin
from .configure_new_modlist_console import ConfigureNewModlistConsoleMixin
from .configure_new_modlist_workflow import ConfigureNewModlistWorkflowMixin
from .configure_new_modlist_dialogs import ConfigureNewModlistDialogsMixin, ModlistFetchThread, SelectionDialog
from .screen_back_mixin import ScreenBackMixin

logger = logging.getLogger(__name__)

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ConfigureNewModlistScreen(ScreenBackMixin, ConfigureNewModlistUISetupMixin, ConfigureNewModlistConsoleMixin, ConfigureNewModlistWorkflowMixin, ConfigureNewModlistDialogsMixin, QWidget):
    resize_request = Signal(str)

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Ensure initial collapsed layout each time this screen is opened
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            # Force collapsed state
            # Set console to hidden state without emitting signals
            self.console.setVisible(False)
            self.resize_request.emit("compact")
        except Exception as e:
            # If initial collapse fails, log but don't crash
            print(f"Warning: Failed to set initial collapsed state: {e}")

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion (same as Tuxborn)"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()

        if success:
            # Check for VNV post-install automation after configuration
            install_dir = self.install_dir_edit.text().strip()
            if install_dir:
                self._check_and_run_vnv_automation(modlist_name, install_dir)

            # Calculate time taken
            time_taken = self._calculate_time_taken()

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show success dialog with celebration
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="configure_new",
                time_taken=time_taken,
                game_name=getattr(self, '_current_game_name', None),
                parent=self
            )
            success_dialog.show()
            
            # Show ENB Proton dialog if ENB was detected (use stored detection result, no re-detection)
            if enb_detected:
                try:
                    from ..dialogs.enb_proton_dialog import ENBProtonDialog
                    enb_dialog = ENBProtonDialog(modlist_name=modlist_name, parent=self)
                    enb_dialog.exec()  # Modal dialog - blocks until user clicks OK
                except Exception as e:
                    # Non-blocking: if dialog fails, just log and continue
                    logger.warning(f"Failed to show ENB dialog: {e}")
        else:
            self._safe_append_text(f"Configuration failed: {message}")
            MessageService.critical(self, "Configuration Failed", 
                               f"Configuration failed: {message}", safety_level="medium")
    
    def on_configuration_error(self, error_message):
        """Handle configuration error"""
        # Re-enable all controls on error
        self._enable_controls_after_operation()
        
        self._safe_append_text(f"Configuration error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}", safety_level="medium")





    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.install_dir_edit.setText("/path/to/Modlist/ModOrganizer.exe")

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Reset resolution combo to saved config preference
        saved_resolution = self.resolution_service.get_saved_resolution()
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
        elif self.resolution_combo.count() > 0:
            self.resolution_combo.setCurrentIndex(0)  # Fallback to "Leave unchanged"

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        debug_print("DEBUG: cleanup called - cleaning up threads")
        
        # Clean up automated prefix thread if running
        if hasattr(self, 'automated_prefix_thread') and self.automated_prefix_thread and self.automated_prefix_thread.isRunning():
            debug_print("DEBUG: Terminating AutomatedPrefixThread")
            try:
                self.automated_prefix_thread.progress_update.disconnect()
                self.automated_prefix_thread.workflow_complete.disconnect()
                self.automated_prefix_thread.error_occurred.disconnect()
            except:
                pass
            self.automated_prefix_thread.terminate()
            self.automated_prefix_thread.wait(2000)  # Wait up to 2 seconds
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            debug_print("DEBUG: Terminating ConfigThread")
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass
            self.config_thread.terminate()
            self.config_thread.wait(2000)  # Wait up to 2 seconds 