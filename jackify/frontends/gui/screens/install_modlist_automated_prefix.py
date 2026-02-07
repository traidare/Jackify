"""Automated prefix workflow handlers for InstallModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QMainWindow
from jackify.frontends.gui.services.message_service import MessageService
from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
from pathlib import Path
import traceback
import threading
import subprocess
import time
import os


def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class AutomatedPrefixHandlersMixin:
    """Mixin providing automated prefix workflow event handlers for InstallModlistScreen."""

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

            # Force Steam GUI to start after restart
            # Ensure Steam GUI is visible after restart
            # start_steam() now uses -foreground, but we'll also try to bring GUI to front
            debug_print("DEBUG: Ensuring Steam GUI is visible after restart")
            try:
                # Wait a moment for Steam processes to stabilize
                time.sleep(3)
                # Try multiple methods to ensure GUI opens
                # Method 1: steam:// protocol (works if Steam is running)
                try:
                    subprocess.Popen(['xdg-open', 'steam://open/main'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    debug_print("DEBUG: Issued steam://open/main command")
                    time.sleep(1)
                except Exception as e:
                    debug_print(f"DEBUG: steam://open/main failed: {e}")
                
                # Method 2: Direct steam -foreground command (redundant but ensures GUI)
                try:
                    subprocess.Popen(['steam', '-foreground'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    debug_print("DEBUG: Issued steam -foreground command")
                except Exception as e2:
                    debug_print(f"DEBUG: steam -foreground failed: {e2}")
            except Exception as e:
                debug_print(f"DEBUG: Error ensuring Steam GUI visibility: {e}")
            
            # CRITICAL: Bring Jackify window back to focus after Steam restart
            # Let user continue with installation
            debug_print("DEBUG: Bringing Jackify window back to focus")
            try:
                from PySide6.QtWidgets import QApplication
                # Get the main window - use window() to get top-level widget, then find QMainWindow
                top_level = self.window()
                main_window = None
                
                # Try to find QMainWindow in the widget hierarchy
                if isinstance(top_level, QMainWindow):
                    main_window = top_level
                else:
                    # Walk up the parent chain
                    current = self
                    while current:
                        if isinstance(current, QMainWindow):
                            main_window = current
                            break
                        current = current.parent()
                    
                    # Last resort: use top-level widget
                    if not main_window and top_level:
                        main_window = top_level
                
                if main_window:
                    # Restore window if minimized
                    if hasattr(main_window, 'isMinimized') and main_window.isMinimized():
                        main_window.showNormal()
                    
                    # Bring to front and activate - use multiple methods for reliability
                    main_window.raise_()
                    main_window.activateWindow()
                    main_window.show()
                    
                    # Aggressive focus restoration with multiple attempts
                    # Steam may steal focus, so we retry multiple times over several seconds
                    def restore_focus():
                        if main_window:
                            try:
                                main_window.raise_()
                                main_window.activateWindow()
                                app = QApplication.instance()
                                if app and app.activeWindow() != main_window:
                                    debug_print("DEBUG: Window not active, retrying focus restoration")
                            except Exception:
                                pass
                    
                    # Immediate attempts
                    QTimer.singleShot(50, restore_focus)
                    QTimer.singleShot(200, restore_focus)
                    QTimer.singleShot(500, restore_focus)
                    # Delayed attempts in case Steam steals focus after initial restoration
                    QTimer.singleShot(1000, restore_focus)
                    QTimer.singleShot(2000, restore_focus)
                    QTimer.singleShot(3000, restore_focus)
                    
                    debug_print(f"DEBUG: Jackify window focus restoration scheduled (type: {type(main_window).__name__})")
                else:
                    debug_print("DEBUG: Could not find main window to bring to focus")
            except Exception as e:
                debug_print(f"DEBUG: Error bringing Jackify to focus: {e}")

            # Save context for later use in configuration
            self._manual_steps_retry_count = 0
            self._current_modlist_name = self.modlist_name_edit.text().strip()

            # Save resolution for later use in configuration
            resolution = self.resolution_combo.currentText()
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None

            # Use automated prefix creation instead of manual steps
            debug_print("DEBUG: Starting automated prefix creation workflow")
            self._safe_append_text("Starting automated prefix creation workflow...")
            self.start_automated_prefix_workflow()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.")

    def start_automated_prefix_workflow(self):
        """Start the automated prefix creation workflow"""
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        # Ensure _current_resolution is always set before starting workflow
        if not hasattr(self, '_current_resolution') or self._current_resolution is None:
            resolution = self.resolution_combo.currentText() if hasattr(self, 'resolution_combo') else None
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution and resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None

        try:
            # Disable controls during installation
            self._disable_controls_during_operation()
            modlist_name = self.modlist_name_edit.text().strip()
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
            
            self._begin_post_install_feedback()

            # Run automated prefix creation in separate thread
            class AutomatedPrefixThread(QThread):
                finished = Signal(bool, str, str, str)  # success, prefix_path, appid (as string), last_timestamp
                progress = Signal(str)  # progress messages
                error = Signal(str)  # error messages
                show_progress_dialog = Signal(str)  # show progress dialog with message
                hide_progress_dialog = Signal()  # hide progress dialog
                conflict_detected = Signal(list)  # conflicts list
                
                def __init__(self, modlist_name, install_dir, final_exe_path, downloads_dir=None):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.final_exe_path = final_exe_path
                    self.downloads_dir = downloads_dir

                def run(self):
                    try:
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
                            _is_steamdeck = False
                            if os.path.exists('/etc/os-release'):
                                with open('/etc/os-release') as f:
                                    if 'steamdeck' in f.read().lower():
                                        _is_steamdeck = True
                        except Exception:
                            _is_steamdeck = False
                        result = prefix_service.run_working_workflow(
                            self.modlist_name, self.install_dir, self.final_exe_path, progress_callback,
                            steamdeck=_is_steamdeck, download_dir=self.downloads_dir
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
            
            # Create and start thread (pass downloads_dir for STEAM_COMPAT_MOUNTS)
            downloads_dir = self.downloads_dir_edit.text().strip() if getattr(self, 'downloads_dir_edit', None) else None
            self.prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, final_exe_path, downloads_dir)
            self.prefix_thread.finished.connect(self.on_automated_prefix_finished)
            self.prefix_thread.error.connect(self.on_automated_prefix_error)
            self.prefix_thread.progress.connect(self.on_automated_prefix_progress)
            self.prefix_thread.show_progress_dialog.connect(self.show_steam_restart_progress)
            self.prefix_thread.hide_progress_dialog.connect(self.hide_steam_restart_progress)
            self.prefix_thread.conflict_detected.connect(self.show_shortcut_conflict_dialog)
            self.prefix_thread.start()
            
        except Exception as e:
            debug_print(f"DEBUG: Exception in start_automated_prefix_workflow: {e}")
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
                modlist_name = self.modlist_name_edit.text().strip()
                install_dir = self.install_dir_edit.text().strip()
                self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
            else:
                self._safe_append_text(f"ERROR: Automated prefix creation failed")
                self._safe_append_text("Please check the logs for details")
                MessageService.critical(self, "Automated Setup Failed", 
                    "Automated prefix creation failed. Please check the console output for details.")
                # Re-enable controls on failure
                self._enable_controls_after_operation()
                self._end_post_install_feedback(success=False)
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
        self._end_post_install_feedback(success=False)

    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
        self._handle_post_install_progress(progress_msg)

