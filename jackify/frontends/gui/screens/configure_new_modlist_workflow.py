"""Workflow management for ConfigureNewModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal
import os
import time
import logging
from jackify.shared.resolution_utils import get_resolution_fallback

logger = logging.getLogger(__name__)

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class ConfigureNewModlistWorkflowMixin:
    """Mixin providing workflow management for ConfigureNewModlistScreen."""

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

        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Validate ModOrganizer.exe path
        mo2_path = self.install_dir_edit.text().strip()
        from jackify.frontends.gui.services.message_service import MessageService
        if not mo2_path:
            MessageService.warning(self, "Missing Path", "Please specify the path to ModOrganizer.exe", safety_level="low")
            return
        if not os.path.isfile(mo2_path):
            MessageService.warning(self, "Invalid Path", "The specified path does not point to a valid file", safety_level="low")
            return
        if not mo2_path.endswith('ModOrganizer.exe'):
            MessageService.warning(self, "Invalid File", "The specified file is not ModOrganizer.exe", safety_level="low")
            return
        
        # Start time tracking
        self._workflow_start_time = time.time()

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration (after validation passes)
        self._disable_controls_during_operation()
        
        # Validate modlist name
        modlist_name = self.modlist_name_edit.text().strip()
        if not modlist_name:
            MessageService.warning(self, "Missing Name", "Please specify a name for your modlist", safety_level="low")
            self._enable_controls_after_operation()
            return
        
        # Handle resolution saving
        resolution = self.resolution_combo.currentText()
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
        
        # Start configuration - automated workflow handles Steam restart internally
        self.configure_modlist()


    def configure_modlist(self):
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()
        modlist_name = self.modlist_name_edit.text().strip()
        mo2_exe_path = self.install_dir_edit.text().strip()
        resolution = self.resolution_combo.currentText()
        if not install_dir or not modlist_name:
            MessageService.warning(self, "Missing Info", "Install directory or modlist name is missing.", safety_level="low")
            return

        # Use automated prefix service instead of manual steps
        self._safe_append_text("")
        self._safe_append_text("=== Steam Integration Phase ===")
        self._safe_append_text("Starting automated Steam setup workflow...")

        # Start automated prefix workflow
        self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path, resolution)


    def _start_automated_prefix_workflow(self, modlist_name, install_dir, mo2_exe_path, resolution):
        """Start the automated prefix workflow using AutomatedPrefixService in a background thread"""
        from jackify import __version__ as jackify_version
        self._safe_append_text(f"Jackify v{jackify_version}")
        self._safe_append_text(f"Initializing automated Steam setup for '{modlist_name}'...")
        self._safe_append_text("Starting automated Steam shortcut creation and configuration...")
        
        # Disable the start button to prevent multiple workflows
        self.start_btn.setEnabled(False)
        
        # Create and start the automated prefix thread
        class AutomatedPrefixThread(QThread):
            progress_update = Signal(str)
            workflow_complete = Signal(object)  # Will emit the result tuple
            error_occurred = Signal(str)
            
            def __init__(self, modlist_name, install_dir, mo2_exe_path, steamdeck, auto_restart):
                super().__init__()
                self.modlist_name = modlist_name
                self.install_dir = install_dir
                self.mo2_exe_path = mo2_exe_path
                self.steamdeck = steamdeck
                self.auto_restart = auto_restart
                
            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    
                    # Initialize the automated prefix service
                    prefix_service = AutomatedPrefixService()
                    
                    # Define progress callback for GUI updates
                    def progress_callback(message):
                        self.progress_update.emit(message)
                    
                    # Run the automated workflow (this contains the blocking operations)
                    result = prefix_service.run_working_workflow(
                        self.modlist_name, self.install_dir, self.mo2_exe_path, 
                        progress_callback, steamdeck=self.steamdeck, auto_restart=self.auto_restart
                    )
                    
                    # Emit the result
                    self.workflow_complete.emit(result)
                    
                except Exception as e:
                    self.error_occurred.emit(str(e))
        
        # Detect Steam Deck once using centralized service
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        _is_steamdeck = platform_service.is_steamdeck

        # Decide whether to restart Steam: checkbox checked = yes; unchecked = ask (only skip if user clicks No)
        from PySide6.QtWidgets import QMessageBox
        from jackify.frontends.gui.services.message_service import MessageService

        auto_restart = self.auto_restart_checkbox.isChecked()
        if not auto_restart:
            reply = MessageService.question(
                self,
                "Restart Steam?",
                "Steam will need to restart to detect the new shortcut. Do you want Jackify to restart Steam when the time comes?",
                safety_level="medium"
            )
            # Only skip restart when user explicitly clicks No; treat Yes or dialog close as restart
            auto_restart = reply != QMessageBox.No

        logger.info("Configure New Modlist: starting automated prefix workflow with auto_restart=%s", auto_restart)

        # Create and start the thread
        self.automated_prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, mo2_exe_path, _is_steamdeck, auto_restart)
        self.automated_prefix_thread.progress_update.connect(self._handle_progress_update)
        self.automated_prefix_thread.workflow_complete.connect(self._on_automated_prefix_complete)
        self.automated_prefix_thread.error_occurred.connect(self._on_automated_prefix_error)
        self.automated_prefix_thread.start()


    def _on_automated_prefix_complete(self, result):
        """Handle completion of the automated prefix workflow"""
        try:
            # Handle the result - check for conflicts
            if isinstance(result, tuple) and len(result) == 4:
                if result[0] == "CONFLICT":
                    # Conflict detected - show conflict resolution dialog
                    conflicts = result[1]
                    self.show_shortcut_conflict_dialog(conflicts)
                    return
                else:
                    # Normal result
                    success, prefix_path, new_appid, last_timestamp = result
                    if success:
                        self._safe_append_text(f"Automated Steam setup completed successfully!")
                        self._safe_append_text(f"New AppID assigned: {new_appid}")
                        
                        # Continue with post-Steam configuration, passing the last timestamp
                        self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                         os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), 
                                                                         last_timestamp)
                    else:
                        self._safe_append_text(f"Automated Steam setup failed")
                        self._safe_append_text("Please check the logs for details.")
                        self.start_btn.setEnabled(True)
            elif isinstance(result, tuple) and len(result) == 3:
                # Fallback for old format (backward compatibility)
                success, prefix_path, new_appid = result
                if success:
                    self._safe_append_text(f"Automated Steam setup completed successfully!")
                    self._safe_append_text(f"New AppID assigned: {new_appid}")
                    
                    # Continue with post-Steam configuration
                    self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                     os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip())
                else:
                    self._safe_append_text(f"Automated Steam setup failed")
                    self._safe_append_text("Please check the logs for details.")
                    self.start_btn.setEnabled(True)
            else:
                # Handle unexpected result format
                self._safe_append_text(f"Automated Steam setup failed - unexpected result format")
                self._safe_append_text("Please check the logs for details.")
                self.start_btn.setEnabled(True)
                
        except Exception as e:
            self._safe_append_text(f"Error handling automated prefix result: {str(e)}")
            self.start_btn.setEnabled(True)


    def _on_automated_prefix_error(self, error_message):
        """Handle error from the automated prefix workflow"""
        self._safe_append_text(f"Error during automated Steam setup: {error_message}")
        self._safe_append_text("Please check the logs for details.")
        
        # Show critical error dialog to user (don't silently fail)
        from jackify.backend.services.message_service import MessageService
        MessageService.critical(
            self,
            "Steam Setup Error",
            f"Error during automated Steam setup:\n\n{error_message}\n\nPlease check the console output for details.",
            safety_level="medium"
        )
        
        self._enable_controls_after_operation()


    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Get resolution from UI
            resolution = self.resolution_combo.currentText()
            resolution_value = resolution.split()[0] if resolution != "Leave unchanged" else None
            
            # Update the context with the new AppID (same format as manual steps)
            mo2_exe_path = self.install_dir_edit.text().strip()
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'modlist_value': None,
                'modlist_source': None,
                'resolution': resolution_value,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            self.context = updated_context  # Ensure context is always set
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context
            from PySide6.QtCore import QThread, Signal
            
            # Capture parent's method and system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            parent_system_info = self.system_info
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context, system_info, detect_func):
                    super().__init__()
                    self.context = context
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.context['path'])
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # This shouldn't happen since automated prefix creation is complete
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the service method for post-Steam configuration
                        self.progress_update.emit("")
                        self.progress_update.emit("=== Configuration Phase ===")
                        self.progress_update.emit("")
                        self.progress_update.emit("Starting modlist configuration...")
                        result = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not result:
                            self.progress_update.emit("Configuration failed to start")
                            self.error_occurred.emit("Configuration failed to start")
                            
                    except Exception as e:
                        self.error_occurred.emit(str(e))
            
            # Start configuration thread
            self.config_thread = ConfigThread(updated_context, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            import traceback
            self._safe_append_text(f"Full traceback: {traceback.format_exc()}")
            self.on_configuration_error(str(e))


    def continue_configuration_after_manual_steps(self, new_appid, modlist_name, install_dir):
        """Continue the configuration process with the corrected AppID after manual steps validation"""
        try:
            # Update the context with the new AppID
            mo2_exe_path = self.install_dir_edit.text().strip()
            resolution = self.resolution_combo.currentText()
            
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'resolution': resolution.split()[0] if resolution != "Leave unchanged" else None,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid,  # Use the NEW AppID from Steam
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context (same as Tuxborn)
            from PySide6.QtCore import QThread, Signal
            
            # Capture parent's method and system_info
            detect_game_type_func = self._detect_game_type_from_mo2_ini
            parent_system_info = self.system_info
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context, system_info, detect_func):
                    super().__init__()
                    self.context = context
                    self.system_info = system_info
                    self.detect_game_type = detect_func
                    
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        modlist_service = ModlistService(self.system_info)
                        
                        # Detect game type from ModOrganizer.ini using captured function
                        detected_game_type = self.detect_game_type(self.context['path'])
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        if 'appid' in self.context:
                            modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # Should not reach here -- manual steps already complete
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the working configuration service method
                        self.progress_update.emit("Starting configuration with backend service...")
                        
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
            self.config_thread = ConfigThread(updated_context, parent_system_info, detect_game_type_func)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            MessageService.critical(self, "Configuration Error", f"Failed to continue configuration: {e}", safety_level="medium")


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


