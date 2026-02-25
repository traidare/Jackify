"""TTW installer requirements and validation for InstallTTWScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox
from jackify.frontends.gui.services.message_service import MessageService
from pathlib import Path
import os
import requests
import traceback
import logging

logger = logging.getLogger(__name__)
class TTWRequirementsMixin:
    """Mixin providing TTW installer requirement checking and validation for InstallTTWScreen."""

    def check_requirements(self):
        """Check and display requirements status"""
        from jackify.backend.handlers.path_handler import PathHandler
        from jackify.backend.handlers.filesystem_handler import FileSystemHandler
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.backend.models.configuration import SystemInfo
        
        path_handler = PathHandler()
        
        # Check game detection
        detected_games = path_handler.find_vanilla_game_paths()
        
        # Fallout 3
        if 'Fallout 3' in detected_games:
            self.fallout3_status.setText("Fallout 3: Detected")
            self.fallout3_status.setStyleSheet("color: #3fd0ea;")
        else:
            self.fallout3_status.setText("Fallout 3: Not Found - Install from Steam")
            self.fallout3_status.setStyleSheet("color: #f44336;")
        
        # Fallout New Vegas
        if 'Fallout New Vegas' in detected_games:
            self.fnv_status.setText("Fallout New Vegas: Detected")
            self.fnv_status.setStyleSheet("color: #3fd0ea;")
        else:
            self.fnv_status.setText("Fallout New Vegas: Not Found - Install from Steam")
            self.fnv_status.setStyleSheet("color: #f44336;")
        
        # Update Start button state after checking requirements
        self._update_start_button_state()
    
    def _check_ttw_installer_status(self):
        """Check TTW_Linux_Installer installation status and update UI"""
        try:
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.handlers.config_handler import ConfigHandler
            from jackify.backend.models.configuration import SystemInfo
            
            # Create handler instances
            filesystem_handler = FileSystemHandler()
            config_handler = ConfigHandler()
            system_info = SystemInfo(is_steamdeck=False)
            ttw_installer_handler = TTWInstallerHandler(
                steamdeck=False,
                verbose=False,
                filesystem_handler=filesystem_handler,
                config_handler=config_handler
            )
            
            # Check if TTW_Linux_Installer is installed
            ttw_installer_handler._check_installation()

            if ttw_installer_handler.ttw_installer_installed:
                # Check version against pinned/latest
                update_available, installed_v, target_v = ttw_installer_handler.is_ttw_installer_update_available()
                if update_available:
                    # Determine if this is a downgrade or upgrade
                    from jackify.backend.handlers.ttw_installer_handler import TTW_INSTALLER_PINNED_VERSION
                    if TTW_INSTALLER_PINNED_VERSION and installed_v and target_v:
                        # If we have a pinned version and installed is newer, it's a downgrade
                        try:
                            # Simple version comparison - if installed version string is longer/more complex, likely newer
                            # For now, just check if they're different and show appropriate message
                            if installed_v != target_v:
                                version_text = f"Update to v{target_v} (currently v{installed_v})"
                            else:
                                version_text = f"Update available (v{installed_v} → v{target_v})"
                        except Exception:
                            version_text = f"Update to v{target_v}" if target_v else "Update available"
                    else:
                        # Normal update (newer version available)
                        version_text = f"Update available (v{installed_v} → v{target_v})" if installed_v and target_v else "Update available"
                    self.ttw_installer_status.setText(version_text)
                    self.ttw_installer_status.setStyleSheet("color: #f44336;")
                    self.ttw_installer_btn.setText("Update now")
                    self.ttw_installer_btn.setEnabled(True)
                    self.ttw_installer_btn.setVisible(True)
                else:
                    version_text = f"Ready (v{installed_v})" if installed_v else "Ready"
                    self.ttw_installer_status.setText(version_text)
                    self.ttw_installer_status.setStyleSheet("color: #3fd0ea;")
                    self.ttw_installer_btn.setText("Update now")
                    self.ttw_installer_btn.setEnabled(False)  # Greyed out when ready
                    self.ttw_installer_btn.setVisible(True)
            else:
                self.ttw_installer_status.setText("Not Found")
                self.ttw_installer_status.setStyleSheet("color: #f44336;")
                self.ttw_installer_btn.setText("Install now")
                self.ttw_installer_btn.setEnabled(True)
                self.ttw_installer_btn.setVisible(True)
                
        except Exception as e:
            self.ttw_installer_status.setText("Check Failed")
            self.ttw_installer_status.setStyleSheet("color: #f44336;")
            self.ttw_installer_btn.setText("Install now")
            self.ttw_installer_btn.setEnabled(True)
            self.ttw_installer_btn.setVisible(True)
            logger.debug(f"DEBUG: TTW_Linux_Installer status check failed: {e}")

    def install_ttw_installer(self):
        """Install or update TTW_Linux_Installer"""
        # If not detected, show info dialog
        try:
            current_status = self.ttw_installer_status.text().strip()
        except Exception:
            current_status = ""
        if current_status == "Not Found":
            MessageService.information(
                self,
                "TTW_Linux_Installer Installation",
                (
                    "TTW_Linux_Installer is a native Linux installer for TTW and other MPI packages.<br><br>"
                    "Project: <a href=\"https://github.com/SulfurNitride/TTW_Linux_Installer\">github.com/SulfurNitride/TTW_Linux_Installer</a><br>"
                    "Please star the repository and thank the developer.<br><br>"
                    "Jackify will now download and install the latest Linux build of TTW_Linux_Installer."
                ),
                safety_level="low",
            )

        # Update button to show installation in progress
        self.ttw_installer_btn.setText("Installing...")
        self.ttw_installer_btn.setEnabled(False)

        self.console.append("Installing/updating TTW_Linux_Installer...")

        # Create background thread for installation
        from PySide6.QtCore import QThread, Signal

        class InstallerDownloadThread(QThread):
            finished = Signal(bool, str)  # success, message
            progress = Signal(str)  # progress message

            def run(self):
                try:
                    from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
                    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    from jackify.backend.models.configuration import SystemInfo

                    # Create handler instances
                    filesystem_handler = FileSystemHandler()
                    config_handler = ConfigHandler()
                    system_info = SystemInfo(is_steamdeck=False)
                    ttw_installer_handler = TTWInstallerHandler(
                        steamdeck=False,
                        verbose=False,
                        filesystem_handler=filesystem_handler,
                        config_handler=config_handler
                    )

                    # Install TTW_Linux_Installer (this will download and extract)
                    self.progress.emit("Downloading TTW_Linux_Installer...")
                    success, message = ttw_installer_handler.install_ttw_installer()

                    if success:
                        install_path = ttw_installer_handler.ttw_installer_dir
                        self.progress.emit(f"Installation complete: {install_path}")
                    else:
                        self.progress.emit(f"Installation failed: {message}")

                    self.finished.emit(success, message)

                except Exception as e:
                    error_msg = f"Error installing TTW_Linux_Installer: {str(e)}"
                    self.progress.emit(error_msg)
                    logger.debug(f"DEBUG: TTW_Linux_Installer installation error: {e}")
                    self.finished.emit(False, error_msg)

        # Create and start thread
        self.installer_download_thread = InstallerDownloadThread()
        self.installer_download_thread.progress.connect(self._on_installer_download_progress)
        self.installer_download_thread.finished.connect(self._on_installer_download_finished)
        self.installer_download_thread.start()
        
        # Update Activity window to show download in progress
        self.file_progress_list.clear()
        self.file_progress_list.update_or_add_item(
            item_id="ttw_installer_download",
            label="Downloading TTW_Linux_Installer...",
            progress=0
        )

    def _on_installer_download_progress(self, message):
        """Handle installer download progress updates"""
        self.console.append(message)
        # Update Activity window based on progress message
        if "Downloading" in message:
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="Downloading TTW_Linux_Installer...",
                progress=0  # Indeterminate progress
            )
        elif "Extracting" in message or "extracting" in message.lower():
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="Extracting TTW_Linux_Installer...",
                progress=50
            )
        elif "complete" in message.lower() or "successfully" in message.lower():
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="TTW_Linux_Installer ready",
                progress=100
            )

    def _on_installer_download_finished(self, success, message):
        """Handle installer download completion"""
        if success:
            self.console.append("TTW_Linux_Installer installed successfully")
            # Clear Activity window after successful installation
            self.file_progress_list.clear()
            # Re-check status after installation (this will update button state correctly)
            self._check_ttw_installer_status()
            self._update_start_button_state()
        else:
            self.console.append(f"Installation failed: {message}")
            # Clear Activity window on failure
            self.file_progress_list.clear()
            # Re-enable button on failure so user can retry
            self.ttw_installer_btn.setText("Install now")
            self.ttw_installer_btn.setEnabled(True)
    
    def _check_ttw_requirements(self):
        """Check TTW requirements before installation"""
        from jackify.backend.handlers.path_handler import PathHandler
        
        path_handler = PathHandler()
        
        # Check game detection
        detected_games = path_handler.find_vanilla_game_paths()
        missing_games = []
        
        if 'Fallout 3' not in detected_games:
            missing_games.append("Fallout 3")
        if 'Fallout New Vegas' not in detected_games:
            missing_games.append("Fallout New Vegas")
        
        if missing_games:
            MessageService.warning(
                self, 
                "Missing Required Games", 
                f"TTW requires both Fallout 3 and Fallout New Vegas to be installed.\n\nMissing: {', '.join(missing_games)}"
            )
            return False
        
        # Check TTW_Linux_Installer using the status we already checked
        status_text = self.ttw_installer_status.text()
        if status_text in ("Not Found", "Check Failed"):
            MessageService.warning(
                self,
                "TTW_Linux_Installer Required",
                "TTW_Linux_Installer is required for TTW installation but is not installed.\n\nPlease install TTW_Linux_Installer using the 'Install now' button."
            )
            return False
        
        return True
    
    def _update_start_button_state(self):
        """Enable/disable Start button based on requirements and file selection"""
        # Check if all requirements are met
        requirements_met = self._check_ttw_requirements()
        
        # Check if .mpi file is selected
        mpi_file_selected = bool(self.file_edit.text().strip())
        
        # Enable Start button only if both requirements are met and file is selected
        self.start_btn.setEnabled(requirements_met and mpi_file_selected)
        
        # Update button text to indicate what's missing
        if not requirements_met:
            self.start_btn.setText("Requirements Not Met")
        elif not mpi_file_selected:
            self.start_btn.setText("Select TTW .mpi File")
        else:
            self.start_btn.setText("Start Installation")

