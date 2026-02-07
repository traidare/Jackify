"""Configuration workflow methods for InstallTTWScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog
import logging
import os
import threading
import traceback
# Runtime imports to avoid circular dependencies
from jackify.frontends.gui.services.message_service import MessageService  # Runtime import

logger = logging.getLogger(__name__)


def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class TTWConfigMixin:
    """Mixin providing configuration workflow methods for InstallTTWScreen."""

    def _detect_game_type_from_mo2_ini(self, install_dir: str) -> str:
        """Detect game type by checking ModOrganizer.ini for loader executables."""
        from pathlib import Path
        import logging
        logger = logging.getLogger(__name__)
        
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

    def restart_steam_and_configure(self):
        """Restart Steam using backend service directly - DECOUPLED FROM CLI"""
        debug_print("DEBUG: restart_steam_and_configure called - using direct backend service")
        progress = QProgressDialog("Restarting Steam...", None, 0, 0, self)
        progress.setWindowTitle("Restarting Steam")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        
        def do_restart():
            debug_print("DEBUG: do_restart thread started - using direct backend service")
            try:
                from jackify.backend.handlers.shortcut_handler import ShortcutHandler
                
                # Use backend service directly instead of CLI subprocess
                # Get system_info from parent screen
                system_info = getattr(self, 'system_info', None)
                is_steamdeck = system_info.is_steamdeck if system_info else False
                shortcut_handler = ShortcutHandler(steamdeck=is_steamdeck)
                
                debug_print("DEBUG: About to call secure_steam_restart()")
                success = shortcut_handler.secure_steam_restart()
                debug_print(f"DEBUG: secure_steam_restart() returned: {success}")
                
                out = "Steam restart completed successfully." if success else "Steam restart failed."
                
            except Exception as e:
                debug_print(f"DEBUG: Exception in do_restart: {e}")
                success = False
                out = str(e)
                
            self.steam_restart_finished.emit(success, out)
            
        threading.Thread(target=do_restart, daemon=True).start()
        self._steam_restart_progress = progress  # Store to close later

    def _on_steam_restart_finished(self, success, out):
        debug_print("DEBUG: _on_steam_restart_finished called")
        # Safely cleanup progress dialog on main thread
        if hasattr(self, '_steam_restart_progress') and self._steam_restart_progress:
            try:
                self._steam_restart_progress.close()
                self._steam_restart_progress.deleteLater()  # Use deleteLater() for safer cleanup
            except Exception as e:
                debug_print(f"DEBUG: Error closing progress dialog: {e}")
            finally:
                self._steam_restart_progress = None
        
        # Controls are managed by the proper control management system
        if success:
            self._safe_append_text("Steam restarted successfully.")
            
            # Save context for later use in configuration
            self._manual_steps_retry_count = 0
            self._current_modlist_name = "TTW Installation"  # Fixed name for TTW
            self._current_resolution = None  # TTW doesn't need resolution changes
            
            # Use automated prefix creation instead of manual steps
            debug_print("DEBUG: Starting automated prefix creation workflow")
            self._safe_append_text("Starting automated prefix creation workflow...")
            self.start_automated_prefix_workflow()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.")

    def start_automated_prefix_workflow(self):
        # Ensure _current_resolution is always set before starting workflow
        if not hasattr(self, '_current_resolution') or self._current_resolution is None:
            resolution = None  # TTW doesn't need resolution changes
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution and resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None
        """Start the automated prefix creation workflow"""
        try:
            # Disable controls during installation
            self._disable_controls_during_operation()
            modlist_name = "TTW Installation"
            install_dir = self.install_dir_edit.text().strip()
            final_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
            
            if not os.path.exists(final_exe_path):
                # Check if this is Somnium specifically (uses files/ subdirectory)
                modlist_name_lower = modlist_name.lower()
                if "somnium" in modlist_name_lower:
                    somnium_exe_path = os.path.join(install_dir, "files", "ModOrganizer.exe")
                    if os.path.exists(somnium_exe_path):
                        final_exe_path = somnium_exe_path
                        self._safe_append_text(f"Detected Somnium modlist - will proceed with automated setup")
                        # Show Somnium guidance popup after automated workflow completes
                        self._show_somnium_guidance = True
                        self._somnium_install_dir = install_dir
                    else:
                        self._safe_append_text(f"ERROR: Somnium ModOrganizer.exe not found at {somnium_exe_path}")
                        MessageService.critical(self, "Somnium ModOrganizer.exe Not Found", 
                            f"Expected Somnium ModOrganizer.exe not found at:\n{somnium_exe_path}\n\nCannot proceed with automated setup.")
                        return
                else:
                    self._safe_append_text(f"ERROR: ModOrganizer.exe not found at {final_exe_path}")
                    MessageService.critical(self, "ModOrganizer.exe Not Found", 
                        f"ModOrganizer.exe not found at:\n{final_exe_path}\n\nCannot proceed with automated setup.")
                    return
            
            # Run automated prefix creation in separate thread
            from PySide6.QtCore import QThread, Signal
            
            class AutomatedPrefixThread(QThread):
                finished = Signal(bool, str, str, str)  # success, prefix_path, appid (as string), last_timestamp
                progress = Signal(str)  # progress messages
                error = Signal(str)  # error messages
                show_progress_dialog = Signal(str)  # show progress dialog with message
                hide_progress_dialog = Signal()  # hide progress dialog
                conflict_detected = Signal(list)  # conflicts list
                
                def __init__(self, modlist_name, install_dir, final_exe_path):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.final_exe_path = final_exe_path
                
                def run(self):
                    try:
                        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                        
                        def progress_callback(message):
                            self.progress.emit(message)
                            # Show progress dialog during Steam restart
                            if "Steam restarted successfully" in message:
                                self.hide_progress_dialog.emit()
                            elif "Restarting Steam..." in message:
                                self.show_progress_dialog.emit("Restarting Steam...")
                        
                        prefix_service = AutomatedPrefixService()
                        # Determine Steam Deck once and pass through the workflow
                        try:
                            import os
                            _is_steamdeck = False
                            if os.path.exists('/etc/os-release'):
                                with open('/etc/os-release') as f:
                                    if 'steamdeck' in f.read().lower():
                                        _is_steamdeck = True
                        except Exception:
                            _is_steamdeck = False
                        result = prefix_service.run_working_workflow(
                            self.modlist_name, self.install_dir, self.final_exe_path, progress_callback, steamdeck=_is_steamdeck
                        )
                        
                        # Handle the result - check for conflicts
                        if isinstance(result, tuple) and len(result) == 4:
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result with timestamp
                                success, prefix_path, new_appid, last_timestamp = result
                        elif isinstance(result, tuple) and len(result) == 3:
                            # Fallback for old format (backward compatibility)
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result (old format)
                                success, prefix_path, new_appid = result
                                last_timestamp = None
                        else:
                            # Handle non-tuple result
                            success = result
                            prefix_path = ""
                            new_appid = "0"
                            last_timestamp = None
                        
                        # Ensure progress dialog is hidden when workflow completes
                        self.hide_progress_dialog.emit()
                        self.finished.emit(success, prefix_path or "", str(new_appid) if new_appid else "0", last_timestamp)
                        
                    except Exception as e:
                        # Ensure progress dialog is hidden on error
                        self.hide_progress_dialog.emit()
                        self.error.emit(str(e))
            
            # Create and start thread
            self.prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, final_exe_path)
            self.prefix_thread.finished.connect(self.on_automated_prefix_finished)
            self.prefix_thread.error.connect(self.on_automated_prefix_error)
            self.prefix_thread.progress.connect(self.on_automated_prefix_progress)
            self.prefix_thread.show_progress_dialog.connect(self.show_steam_restart_progress)
            self.prefix_thread.hide_progress_dialog.connect(self.hide_steam_restart_progress)
            self.prefix_thread.conflict_detected.connect(self.show_shortcut_conflict_dialog)
            self.prefix_thread.start()
            
        except Exception as e:
            debug_print(f"DEBUG: Exception in start_automated_prefix_workflow: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            self._safe_append_text(f"ERROR: Failed to start automated workflow: {e}")
            # Re-enable controls on exception
            self._enable_controls_after_operation()
    
    def on_automated_prefix_finished(self, success, prefix_path, new_appid_str, last_timestamp=None):
        """Handle completion of automated prefix creation"""
        try:
            if success:
                debug_print(f"SUCCESS: Automated prefix creation completed!")
                debug_print(f"Prefix created at: {prefix_path}")
                if new_appid_str and new_appid_str != "0":
                    debug_print(f"AppID: {new_appid_str}")
                
                # Convert string AppID back to integer for configuration
                new_appid = int(new_appid_str) if new_appid_str and new_appid_str != "0" else None
                
                # Continue with configuration using the new AppID and timestamp
                modlist_name = "TTW Installation"
                install_dir = self.install_dir_edit.text().strip()
                self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
            else:
                self._safe_append_text(f"ERROR: Automated prefix creation failed")
                self._safe_append_text("Please check the logs for details")
                MessageService.critical(self, "Automated Setup Failed", 
                    "Automated prefix creation failed. Please check the console output for details.")
                # Re-enable controls on failure
                self._enable_controls_after_operation()
        finally:
            # Always ensure controls are re-enabled when workflow truly completes
            pass
    
    def on_automated_prefix_error(self, error_msg):
        """Handle error in automated prefix creation"""
        self._safe_append_text(f"ERROR: Error during automated prefix creation: {error_msg}")
        MessageService.critical(self, "Automated Setup Error", 
            f"Error during automated prefix creation: {error_msg}")
        # Re-enable controls on error
        self._enable_controls_after_operation()
    
    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
    
    def on_configuration_progress(self, progress_msg):
        """Handle progress updates from modlist configuration"""
        self._safe_append_text(progress_msg)
    
    def show_steam_restart_progress(self, message):
        """Show Steam restart progress dialog"""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt
        
        self.steam_restart_progress = QProgressDialog(message, None, 0, 0, self)
        self.steam_restart_progress.setWindowTitle("Restarting Steam")
        self.steam_restart_progress.setWindowModality(Qt.WindowModal)
        self.steam_restart_progress.setMinimumDuration(0)
        self.steam_restart_progress.setValue(0)
        self.steam_restart_progress.show()
    
    def hide_steam_restart_progress(self):
        """Hide Steam restart progress dialog"""
        if hasattr(self, 'steam_restart_progress') and self.steam_restart_progress:
            try:
                self.steam_restart_progress.close()
                self.steam_restart_progress.deleteLater()
            except Exception:
                pass
            finally:
                self.steam_restart_progress = None
        # Controls are managed by the proper control management system

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion on main thread"""
        try:
            # Re-enable controls now that installation/configuration is complete
            self._enable_controls_after_operation()
            
            if success:
                # Check if we need to show Somnium guidance
                if self._show_somnium_guidance:
                    self._show_somnium_post_install_guidance()
                
                # Show celebration SuccessDialog after the entire workflow
                from ..dialogs import SuccessDialog
                import time
                if not hasattr(self, '_install_workflow_start_time'):
                    self._install_workflow_start_time = time.time()
                time_taken = int(time.time() - self._install_workflow_start_time)
                mins, secs = divmod(time_taken, 60)
                time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"
                display_names = {
                    'skyrim': 'Skyrim',
                    'fallout4': 'Fallout 4',
                    'falloutnv': 'Fallout New Vegas',
                    'oblivion': 'Oblivion',
                    'starfield': 'Starfield',
                    'oblivion_remastered': 'Oblivion Remastered',
                    'enderal': 'Enderal'
                }
                game_name = display_names.get(self._current_game_type, self._current_game_name)
                success_dialog = SuccessDialog(
                    modlist_name=modlist_name,
                    workflow_type="install",
                    time_taken=time_str,
                    game_name=game_name,
                    parent=self
                )
                success_dialog.show()
                
                # TTW workflow does NOT need ENB detection/dialog
            elif hasattr(self, '_manual_steps_retry_count') and self._manual_steps_retry_count >= 3:
                # Max retries reached - show failure message
                MessageService.critical(self, "Manual Steps Failed", 
                                   "Manual steps validation failed after multiple attempts.")
            else:
                # Configuration failed for other reasons
                MessageService.critical(self, "Configuration Failed", 
                                   "Post-install configuration failed. Please check the console output.")
        except Exception as e:
            # Ensure controls are re-enabled even on unexpected errors
            self._enable_controls_after_operation()
            raise
        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None

    def on_configuration_error(self, error_message):
        """Handle configuration error on main thread"""
        self._safe_append_text(f"Configuration failed with error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}")

        # Re-enable all controls on error
        self._enable_controls_after_operation()

        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None

    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Update the context with the new AppID (same format as manual steps)
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': self.context.get('game_name', 'Skyrim Special Edition') if hasattr(self, 'context') else 'Skyrim Special Edition'
            }
            self.context = updated_context  # Ensure context is always set
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Get Steam Deck detection once and pass to ConfigThread
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            is_steamdeck = platform_service.is_steamdeck

            # Create new config thread with updated context
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str)
                error_occurred = Signal(str)

                def __init__(self, context, is_steamdeck):
                    super().__init__()
                    self.context = context
                    self.is_steamdeck = is_steamdeck
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service with passed Steam Deck detection
                        system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
                        modlist_service = ModlistService(system_info)
                        
                        # Detect game type from ModOrganizer.ini
                        detected_game_type = self._detect_game_type_from_mo2_ini(self.context['path'])
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type=detected_game_type,
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution'),
                            skip_confirmation=True,
                            engine_installed=True  # Skip path manipulation for engine workflows
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
            self.config_thread = ConfigThread(updated_context, is_steamdeck)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
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
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid  # Use the NEW AppID from Steam
            }
            
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Clean up old thread if exists and wait for it to finish
            if hasattr(self, 'config_thread') and self.config_thread is not None:
                # Disconnect all signals to prevent "Internal C++ object already deleted" errors
                try:
                    self.config_thread.progress_update.disconnect()
                    self.config_thread.configuration_complete.disconnect()
                    self.config_thread.error_occurred.disconnect()
                except:
                    pass  # Ignore errors if already disconnected
                if self.config_thread.isRunning():
                    self.config_thread.quit()
                    self.config_thread.wait(5000)  # Wait up to 5 seconds
                self.config_thread.deleteLater()
                self.config_thread = None
            
            # Start new config thread
            self.config_thread = self._create_config_thread(updated_context)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            self.on_configuration_error(str(e))

    def _create_config_thread(self, context):
        """Create a new ConfigThread with proper lifecycle management"""
        from PySide6.QtCore import QThread, Signal

        # Get Steam Deck detection once
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        is_steamdeck = platform_service.is_steamdeck

        class ConfigThread(QThread):
            progress_update = Signal(str)
            configuration_complete = Signal(bool, str, str)
            error_occurred = Signal(str)

            def __init__(self, context, is_steamdeck, parent=None):
                super().__init__(parent)
                self.context = context
                self.is_steamdeck = is_steamdeck
                
            def run(self):
                try:
                    from jackify.backend.models.configuration import SystemInfo
                    from jackify.backend.services.modlist_service import ModlistService
                    from jackify.backend.models.modlist import ModlistContext
                    from pathlib import Path
                    
                    # Initialize backend service with passed Steam Deck detection
                    system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
                    modlist_service = ModlistService(system_info)
                    
                    # Detect game type from ModOrganizer.ini
                    detected_game_type = self._detect_game_type_from_mo2_ini(self.context['path'])
                    
                    # Convert context to ModlistContext for service
                    modlist_context = ModlistContext(
                        name=self.context['name'],
                        install_dir=Path(self.context['path']),
                        download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                        game_type=detected_game_type,
                        nexus_api_key='',  # Not needed for configuration
                        modlist_value=self.context.get('modlist_value', ''),
                        modlist_source=self.context.get('modlist_source', 'identifier'),
                        resolution=self.context.get('resolution'),  # Pass resolution from GUI
                        skip_confirmation=True,
                        engine_installed=True  # Skip path manipulation for engine workflows
                    )
                    
                    # Add app_id to context
                    if 'appid' in self.context:
                        modlist_context.app_id = self.context['appid']
                    
                    # Define callbacks
                    def progress_callback(message):
                        self.progress_update.emit(message)
                        
                    def completion_callback(success, message, modlist_name):
                        self.configuration_complete.emit(success, message, modlist_name)
                        
                    def manual_steps_callback(modlist_name, retry_count):
                        # Should not reach here -- manual steps already complete
                        self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                    
                    # Call the new service method for post-Steam configuration
                    result = modlist_service.configure_modlist_post_steam(
                        context=modlist_context,
                        progress_callback=progress_callback,
                        manual_steps_callback=manual_steps_callback,
                        completion_callback=completion_callback
                    )
                    
                    if not result:
                        self.progress_update.emit("WARNING: configure_modlist_post_steam returned False")
                    
                except Exception as e:
                    import traceback
                    error_details = f"Error in configuration: {e}\nTraceback: {traceback.format_exc()}"
                    self.progress_update.emit(f"DEBUG: {error_details}")
                    self.error_occurred.emit(str(e))
        
        return ConfigThread(context, is_steamdeck, parent=self)

