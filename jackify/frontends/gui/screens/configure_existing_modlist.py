# Copy of ConfigureNewModlistScreen, adapted for existing modlists
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
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
from jackify.frontends.gui.services.message_service import MessageService
from .configure_existing_modlist_ui import ConfigureExistingModlistUIMixin
from .configure_existing_modlist_workflow import ConfigureExistingModlistWorkflowMixin
from .configure_existing_modlist_shortcuts import ConfigureExistingModlistShortcutsMixin
from .configure_existing_modlist_console import ConfigureExistingModlistConsoleMixin
from .screen_back_mixin import ScreenBackMixin

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ConfigureExistingModlistScreen(
    ScreenBackMixin,
    ConfigureExistingModlistUIMixin,
    ConfigureExistingModlistWorkflowMixin,
    ConfigureExistingModlistShortcutsMixin,
    ConfigureExistingModlistConsoleMixin,
    QWidget,
):
    steam_restart_finished = Signal(bool, str)
    resize_request = Signal(str)

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        # Stop CPU tracking if active
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

        # Clean up configuration thread if running
        if hasattr(self, 'config_thread') and self.config_thread.isRunning():
            self.config_thread.terminate()
            self.config_thread.wait(1000)

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Ensure initial collapsed layout first so UI is stable before async load
        try:
            from PySide6.QtCore import Qt as _Qt
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            self._toggle_console_visibility(False)
            
            # Only set minimum size - DO NOT RESIZE
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception as e:
            print(f"Warning: Failed to set initial collapsed state: {e}")

        # Load shortcuts after layout is done so we don't block or re-enter during showEvent
        if not self._shortcuts_loaded:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(150, self._load_shortcuts_async)
            self._shortcuts_loaded = True

    def hideEvent(self, event):
        """Clean up thread when screen is hidden (terminate without blocking main thread)"""
        super().hideEvent(event)
        if self._shortcut_loader is not None:
            if self._shortcut_loader.isRunning():
                try:
                    self._shortcut_loader.finished_signal.disconnect()
                except Exception:
                    pass
                self._shortcut_loader.terminate()
            self._shortcut_loader = None

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()

        if success:
            # Check for VNV post-install automation after configuration
            install_dir = getattr(self, '_current_install_dir', None)
            if install_dir:
                self._check_and_run_vnv_automation(modlist_name, install_dir)

            # Calculate time taken
            time_taken = self._calculate_time_taken()

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show success dialog with celebration
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="configure_existing",
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
                    enb_dialog.exec()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to show ENB dialog: %s", e)
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
        # Clear the shortcut selection
        self.shortcut_combo.clear()
        self.shortcut_map.clear()
        # Auto-refresh modlist list when screen is entered
        self.refresh_modlist_list()

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
        debug_print("DEBUG: cleanup called - cleaning up ConfigurationThread")
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            debug_print("DEBUG: Terminating ConfigurationThread")
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass
            self.config_thread.terminate()
            self.config_thread.wait(2000)  # Wait up to 2 seconds 