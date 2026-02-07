"""Workflow management for ConfigureExistingModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal
import os
import time
import logging
from pathlib import Path
from typing import Optional
from jackify.shared.resolution_utils import get_resolution_fallback

logger = logging.getLogger(__name__)

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class ConfigureExistingModlistWorkflowMixin:
    """Mixin providing workflow management for ConfigureExistingModlistScreen."""

    def _detect_game_type_from_mo2_ini(self, install_dir: str) -> str:
        """Detect game type by checking ModOrganizer.ini for loader executables."""
        from pathlib import Path
        
        mo2_ini = Path(install_dir) / "ModOrganizer.ini"
        if not mo2_ini.exists():
            return 'skyrim'  # Fallback to most common
        
        try:
            content = mo2_ini.read_text(encoding='utf-8', errors='ignore').lower()
            
            if 'skse64_loader.exe' in content or 'skyrim special edition' in content:
                return 'skyrim'
            elif 'f4se_loader.exe' in content or 'fallout 4' in content:
                return 'fallout4'
            elif 'nvse_loader.exe' in content or 'fallout new vegas' in content:
                return 'falloutnv'
            elif 'obse_loader.exe' in content or 'oblivion' in content:
                return 'oblivion'
            elif 'starfield' in content:
                return 'starfield'
            elif 'enderal' in content:
                return 'enderal'
            else:
                return 'skyrim'
        except Exception as e:
            logger.warning(f"Error detecting game type from ModOrganizer.ini: {e}")
            return 'skyrim'


    def validate_and_start_configure(self):
        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration
        self._disable_controls_during_operation()
        
        # Get selected shortcut
        idx = self.shortcut_combo.currentIndex() - 1  # Account for 'Please Select...'
        from jackify.frontends.gui.services.message_service import MessageService
        if idx < 0 or idx >= len(self.shortcut_map):
            MessageService.critical(self, "No Shortcut Selected", "Please select a ModOrganizer.exe Steam shortcut to configure.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        shortcut = self.shortcut_map[idx]
        modlist_name = shortcut.get('AppName', shortcut.get('appname', ''))
        install_dir = shortcut.get('StartDir', shortcut.get('startdir', ''))
        if not modlist_name or not install_dir:
            MessageService.critical(self, "Invalid Shortcut", "The selected shortcut is missing required information.", safety_level="medium")
            self._enable_controls_after_operation()
            return
        resolution = self.resolution_combo.currentText()
        # Handle resolution saving
        if resolution and resolution != "Leave unchanged":
            success = self.resolution_service.save_resolution(resolution)
            if success:
                debug_print(f"DEBUG: Resolution saved successfully: {resolution}")
            else:
                debug_print("DEBUG: Failed to save resolution")
        else:
            # Clear saved resolution if "Leave unchanged" is selected
            if self.resolution_service.has_saved_resolution():
                self.resolution_service.clear_saved_resolution()
                debug_print("DEBUG: Saved resolution cleared")
        # Start the workflow (no shortcut creation needed)
        self.start_workflow(modlist_name, install_dir, resolution)


    def start_workflow(self, modlist_name, install_dir, resolution):
        """Start the configuration workflow using backend service directly"""
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        # Store install_dir for later use in on_configuration_complete
        self._current_install_dir = install_dir

        try:
            # Start time tracking
            self._workflow_start_time = time.time()

            from jackify import __version__ as jackify_version
            self._safe_append_text(f"Jackify v{jackify_version}")
            self._safe_append_text("[Jackify] Starting post-install configuration...")
            
            # Create configuration thread using backend service
            from PySide6.QtCore import QThread, Signal
            from jackify.backend.models.configuration import SystemInfo
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            
            # Capture parent's method and create system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            platform_service = PlatformDetectionService.get_instance()
            parent_system_info = SystemInfo(is_steamdeck=platform_service.is_steamdeck)
            
            class ConfigurationThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, modlist_name, install_dir, resolution, system_info, detect_func):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.resolution = resolution
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                    
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        import os
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.install_dir)
                        
                        # Create modlist context for existing modlist configuration
                        mo2_exe_path = os.path.join(self.install_dir, "ModOrganizer.exe")
                        modlist_context = ModlistContext(
                            name=self.modlist_name,
                            install_dir=Path(self.install_dir),
                            download_dir=Path(self.install_dir).parent / 'Downloads',  # Default
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration-only
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            skip_confirmation=True
                        )
                        
                        # For existing modlists, add resolution if specified
                        if self.resolution != "Leave unchanged":
                            modlist_context.resolution = self.resolution.split()[0]
                        # If "Leave unchanged" selected, resolution stays None
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # Existing modlists shouldn't need manual steps, but handle gracefully
                            self.progress_update.emit(f"Note: Manual steps callback triggered for {modlist_name} (retry {retry_count})")
                        
                        # Call the working configuration service method
                        self.progress_update.emit("Starting existing modlist configuration...")
                        
                        # For existing modlists, call configure_modlist_post_steam directly
                        # since Steam setup and manual steps should already be done
                        success = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not success:
                            self.error_occurred.emit("Configuration failed - check logs for details")
                            
                    except Exception as e:
                        import traceback
                        error_msg = f"Configuration error: {e}\n{traceback.format_exc()}"
                        self.error_occurred.emit(error_msg)
            
            # Create and start the configuration thread
            self.config_thread = ConfigurationThread(modlist_name, install_dir, resolution, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"[ERROR] Failed to start configuration: {e}")
            MessageService.critical(self, "Configuration Error", f"Failed to start configuration: {e}", safety_level="medium")


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


    def show_manual_steps_dialog(self, extra_warning=""):
        modlist_name = self.shortcut_combo.currentText().split('(')[0].strip() or "your modlist"
        msg = (
            f"<b>Manual Proton Setup Required for <span style='color:#3fd0ea'>{modlist_name}</span></b><br>"
            "After Steam restarts, complete the following steps in Steam:<br>"
            f"1. Locate the '<b>{modlist_name}</b>' entry in your Steam Library<br>"
            "2. Right-click and select 'Properties'<br>"
            "3. Switch to the 'Compatibility' tab<br>"
            "4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'<br>"
            "5. Select 'Proton - Experimental' from the dropdown menu<br>"
            "6. Close the Properties window<br>"
            f"7. Launch '<b>{modlist_name}</b>' from your Steam Library<br>"
            "8. Wait for Wabbajack to download its files and fully load<br>"
            "9. Once Wabbajack has fully loaded, CLOSE IT completely and return here<br>"
            "<br>Once you have completed ALL the steps above, click OK to continue."
            f"{extra_warning}"
        )
        reply = MessageService.question(self, "Manual Steps Required", msg, safety_level="medium")
        if reply == QMessageBox.Yes:
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.write(b'\n')
                self.config_process.waitForBytesWritten(1000)
            self._config_prompt_state = None
            self._manual_steps_buffer = []
        else:
            # User clicked Cancel or closed the dialog - cancel the workflow
            self._safe_append_text("\nManual steps cancelled by user. Workflow stopped.")
            # Terminate the configuration process
            if self.config_process and self.config_process.state() == QProcess.Running:
                self.config_process.terminate()
                self.config_process.waitForFinished(2000)
            # Re-enable all controls
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)


    def show_next_steps_dialog(self, message):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
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


    def _on_steam_restart_finished(self, success, message):
        pass 


    def refresh_modlist_list(self):
        """Refresh the modlist dropdown by re-detecting ModOrganizer.exe shortcuts (async)"""
        # Use async loading to avoid blocking UI
        self._shortcuts_loaded = False  # Allow reload
        self._load_shortcuts_async() 


    def _calculate_time_taken(self) -> str:
        """Calculate and format the time taken for the workflow"""
        if self._workflow_start_time is None:
            return "unknown time"
        
        elapsed_seconds = time.time() - self._workflow_start_time
        elapsed_minutes = int(elapsed_seconds // 60)
        elapsed_seconds_remainder = int(elapsed_seconds % 60)
        
        if elapsed_minutes > 0:
            if elapsed_minutes == 1:
                return f"{elapsed_minutes} minute {elapsed_seconds_remainder} seconds"
            else:
                return f"{elapsed_minutes} minutes {elapsed_seconds_remainder} seconds"
        else:
            return f"{elapsed_seconds_remainder} seconds"


