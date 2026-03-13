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
from jackify.shared.errors import configuration_failed
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
import logging
logger = logging.getLogger(__name__)
from .configure_existing_modlist_ui import ConfigureExistingModlistUIMixin
from .configure_existing_modlist_workflow import ConfigureExistingModlistWorkflowMixin
from .configure_existing_modlist_shortcuts import ConfigureExistingModlistShortcutsMixin
from .configure_existing_modlist_console import ConfigureExistingModlistConsoleMixin
from .screen_back_mixin import ScreenBackMixin
from .install_modlist_ttw import TTWIntegrationMixin
from .install_modlist_postinstall import PostInstallFeedbackMixin

class ConfigureExistingModlistScreen(
    ScreenBackMixin,
    TTWIntegrationMixin,
    ConfigureExistingModlistUIMixin,
    ConfigureExistingModlistWorkflowMixin,
    ConfigureExistingModlistShortcutsMixin,
    ConfigureExistingModlistConsoleMixin,
    PostInstallFeedbackMixin,
    QWidget,
):
    resize_request = Signal(str)

    def _park_thread(self, thread, signal_names=None):
        """Disconnect a running thread from this screen and keep it alive until it finishes."""
        if thread is None:
            return None
        signal_names = signal_names or []
        for signal_name in signal_names:
            try:
                getattr(thread, signal_name).disconnect()
            except Exception:
                pass
        if not hasattr(self, "_parked_threads"):
            self._parked_threads = []
        self._parked_threads.append(thread)
        self._parked_threads = [t for t in self._parked_threads if getattr(t, "isRunning", lambda: False)()]
        return None

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

        from PySide6.QtCore import QThread
        for attr_name, value in list(vars(self).items()):
            try:
                if isinstance(value, QThread) and value.isRunning():
                    signal_names = []
                    for candidate in ("finished_signal", "progress_update", "configuration_complete", "error_occurred"):
                        if hasattr(value, candidate):
                            signal_names.append(candidate)
                    setattr(self, attr_name, self._park_thread(value, signal_names))
            except Exception:
                pass

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        if getattr(self, '_vnv_controller', None) is not None:
            self._vnv_controller.cleanup()
            self._vnv_controller = None
        self.cleanup_processes()
        self.collapse_show_details_before_leave()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        try:
            self.force_collapsed_details_state()
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception as e:
            print(f"Warning: Failed to set initial collapsed state: {e}")

        # Shortcut loading is handled by reset_screen_to_defaults() → refresh_modlist_list()
        # which fires via _debug_screen_change on every navigation to this screen.

    def hideEvent(self, event):
        """Clean up thread when screen is hidden."""
        super().hideEvent(event)
        if self._shortcut_loader is not None:
            if self._shortcut_loader.isRunning():
                self._shortcut_loader = self._park_thread(self._shortcut_loader, ["finished_signal", "error_signal"])
            else:
                self._shortcut_loader = None

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()

        if success:
            install_dir = getattr(self, '_current_install_dir', None)

            if install_dir:
                game_type = self._detect_game_type_from_mo2_ini(install_dir)
                if game_type in ('falloutnv', 'fallout_new_vegas'):
                    from jackify.backend.utils.modlist_meta import get_modlist_name
                    identified_name = get_modlist_name(install_dir)
                    if identified_name and self._check_ttw_eligibility(identified_name, game_type, install_dir):
                        self._cleanup_config_thread()
                        self._initiate_ttw_workflow(identified_name, install_dir)
                        return

            # Check for VNV post-install automation after configuration
            if install_dir and self._check_and_run_vnv_automation(modlist_name, install_dir):
                self._pending_success_dialog_params = {
                    'modlist_name': modlist_name,
                    'workflow_type': 'configure_existing',
                    'time_taken': self._calculate_time_taken(),
                    'game_name': getattr(self, '_current_game_name', None),
                    'enb_detected': enb_detected,
                }
                return

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
            MessageService.show_error(self, configuration_failed(str(message)))
        self._cleanup_config_thread()
    
    def on_configuration_error(self, error_message):
        """Handle configuration error"""
        # Re-enable all controls on error
        self._enable_controls_after_operation()

        self._safe_append_text(f"Configuration error: {error_message}")
        MessageService.show_error(self, configuration_failed(str(error_message)))
        self._cleanup_config_thread()

    def _cleanup_config_thread(self):
        """Safely stop and release configuration thread."""
        if not hasattr(self, 'config_thread') or self.config_thread is None:
            return

        try:
            self.config_thread.progress_update.disconnect()
            self.config_thread.configuration_complete.disconnect()
            self.config_thread.error_occurred.disconnect()
        except (RuntimeError, TypeError):
            pass

        if self.config_thread.isRunning():
            self.config_thread.quit()
            self.config_thread.wait(5000)

        self.config_thread.deleteLater()
        self.config_thread = None

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
        self.force_collapsed_details_state()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        logger.debug("DEBUG: cleanup called - cleaning up ConfigurationThread")

        if getattr(self, '_vnv_controller', None) is not None:
            self._vnv_controller.cleanup()
            self._vnv_controller = None
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            logger.debug("DEBUG: Parking ConfigurationThread")
            self.config_thread = self._park_thread(
                self.config_thread,
                ["progress_update", "configuration_complete", "error_occurred"],
            )
