"""Installation workflow methods for InstallModlistScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
import logging
import os
import re
import time

from .install_modlist_installer_thread import InstallerThread
from .install_modlist_output_mixin import InstallModlistOutputMixin
from jackify.backend.services.steam_restart_service import ensure_flatpak_steam_filesystem_access
from jackify.shared.errors import install_dir_create_failed

logger = logging.getLogger(__name__)


class InstallWorkflowMixin(InstallModlistOutputMixin):
    """Mixin providing installation workflow methods for InstallModlistScreen."""

    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()
        logger.debug('DEBUG: validate_and_start_install called')

        # Immediately show "Initialising" status to provide feedback
        self.progress_indicator.set_status("Initialising...", 0)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()  # Force UI update

        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Check protontricks before proceeding
        if not self._check_protontricks():
            self.progress_indicator.reset()
            return

        # Disable all controls during installation (except Cancel)
        self._disable_controls_during_operation()
        
        try:
            tab_index = self.source_tabs.currentIndex()
            install_mode = 'online'
            if tab_index == 1:  # .wabbajack File tab
                modlist = self.file_edit.text().strip()
                if not modlist or not os.path.isfile(modlist) or not modlist.endswith('.wabbajack'):
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Please select a valid .wabbajack file."
                    )
                    return
                install_mode = 'file'
            else:
                # For online modlists, ALWAYS use machine_url from selected_modlist_info
                # Button text is now the display name (title), NOT the machine URL
                if not hasattr(self, 'selected_modlist_info') or not self.selected_modlist_info:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
                
                machine_url = self.selected_modlist_info.get('machine_url')
                if not machine_url:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is incomplete. Please select the modlist again from the gallery."
                    )
                    return
                
                # CRITICAL: Use machine_url, NOT button text
                modlist = machine_url
            install_dir = self.install_dir_edit.text().strip()
            downloads_dir = self.downloads_dir_edit.text().strip()

            # Get authentication token (OAuth or API key) with automatic refresh
            api_key, oauth_info = self.auth_service.get_auth_for_engine()
            if not api_key:
                self._abort_with_message(
                    "warning",
                    "Authorisation Required",
                    "Please authorise with Nexus Mods before installing modlists.\n\n"
                    "Click the 'Authorise' button above to log in with OAuth,\n"
                    "or configure an API key in Settings.",
                    safety_level="medium"
                )
                return

            # Log authentication status at install start (Issue #111 diagnostics)
            auth_method = self.auth_service.get_auth_method()
            logger.info("=" * 60)
            logger.info("Authentication Status at Install Start")
            logger.info(f"Method: {auth_method or 'UNKNOWN'}")
            logger.info(f"Token length: {len(api_key)} chars")
            if len(api_key) >= 8:
                logger.info(f"Token (partial): {api_key[:4]}...{api_key[-4:]}")

            if auth_method == 'oauth':
                token_handler = self.auth_service.token_handler
                token_info = token_handler.get_token_info()
                if 'expires_in_minutes' in token_info:
                    logger.info(f"OAuth expires in: {token_info['expires_in_minutes']:.1f} minutes")
                if token_info.get('refresh_token_likely_expired'):
                    logger.warning(f"OAuth refresh token age: {token_info['refresh_token_age_days']:.1f} days (may need re-auth)")
            logger.info("=" * 60)

            modlist_name = self.modlist_name_edit.text().strip()
            missing_fields = []
            if not modlist_name:
                missing_fields.append("Modlist Name")
            if not install_dir:
                missing_fields.append("Install Directory")
            if not downloads_dir:
                missing_fields.append("Downloads Directory")
            if missing_fields:
                self._abort_with_message(
                    "warning",
                    "Missing Required Fields",
                    "Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields)
                )
                return
            from jackify.backend.handlers.validation_handler import ValidationHandler
            validation_handler = ValidationHandler()
            is_safe, reason = validation_handler.is_safe_install_directory(Path(install_dir))
            if not is_safe:
                from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
                dlg = WarningDialog(reason, parent=self)
                result = dlg.exec()
                if not result or not dlg.confirmed:
                    self._abort_install_validation()
                    return
            if not os.path.isdir(install_dir):
                from ..services.message_service import MessageService
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.show_error(self, install_dir_create_failed(install_dir, str(e)))
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
                    return
            if not os.path.isdir(downloads_dir):
                from ..services.message_service import MessageService
                create = MessageService.question(self, "Create Directory?",
                    f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.show_error(self, install_dir_create_failed(downloads_dir, str(e)))
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
                    return

            # Handle resolution saving
            resolution = self.resolution_combo.currentText()
            if resolution and resolution != "Leave unchanged":
                success = self.resolution_service.save_resolution(resolution)
                if success:
                    logger.debug(f"DEBUG: Resolution saved successfully: {resolution}")
                else:
                    logger.debug("DEBUG: Failed to save resolution")
            else:
                # Clear saved resolution if "Leave unchanged" is selected
                if self.resolution_service.has_saved_resolution():
                    self.resolution_service.clear_saved_resolution()
                    logger.debug("DEBUG: Saved resolution cleared")
            
            ensure_flatpak_steam_filesystem_access(Path(install_dir))

            # Handle parent directory saving
            self._save_parent_directories(install_dir, downloads_dir)
            
            # Detect game type and check support
            game_type = None
            game_name = None
            
            if install_mode == 'file':
                # Parse .wabbajack file to get game type
                wabbajack_path = Path(modlist)
                result = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_path)
                if result:
                    if isinstance(result, tuple):
                        game_type, raw_game_type = result
                        # Get display name for the game
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        if game_type == 'unknown' and raw_game_type:
                            game_name = raw_game_type
                        else:
                            game_name = display_names.get(game_type, game_type)
                    else:
                        game_type = result
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        game_name = display_names.get(game_type, game_type)
            else:
                # For online modlists, try to get game type from selected modlist
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    game_name = self.selected_modlist_info.get('game', '')
                    logger.debug(f"DEBUG: Detected game_name from selected_modlist_info: '{game_name}'")
                    
                    # Map game name to game type
                    game_mapping = {
                        'skyrim special edition': 'skyrim',
                        'skyrim': 'skyrim',
                        'fallout 4': 'fallout4',
                        'fallout new vegas': 'falloutnv',
                        'oblivion': 'oblivion',
                        'starfield': 'starfield',
                        'oblivion_remastered': 'oblivion_remastered',
                        'enderal': 'enderal',
                        'enderal special edition': 'enderal'
                    }
                    game_type = game_mapping.get(game_name.lower())
                    logger.debug(f"DEBUG: Mapped game_name '{game_name}' to game_type: '{game_type}'")
                    if not game_type:
                        game_type = 'unknown'
                        logger.debug(f"DEBUG: Game type not found in mapping, setting to 'unknown'")
                else:
                    logger.debug(f"DEBUG: No selected_modlist_info found")
                    game_type = 'unknown'
            
            # Store game type and name for later use
            self._current_game_type = game_type
            self._current_game_name = game_name
            
            # Check if game is supported
            logger.debug(f"DEBUG: Checking if game_type '{game_type}' is supported")
            logger.debug(f"DEBUG: game_type='{game_type}', game_name='{game_name}'")
            is_supported = self.wabbajack_parser.is_supported_game(game_type) if game_type else False
            logger.debug(f"DEBUG: is_supported_game('{game_type}') returned: {is_supported}")
            
            if game_type and not is_supported:
                logger.debug(f"DEBUG: Game '{game_type}' is not supported, showing dialog")
                # Show unsupported game dialog
                from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
                dialog = UnsupportedGameDialog(self, game_name)
                if not dialog.show_dialog(self, game_name):
                    self._abort_install_validation()
                    return
            
            self.console.clear()
            self.process_monitor.clear()
            
            # R&D: Reset progress indicator for new installation
            self.progress_indicator.reset()
            self.progress_state_manager.reset()
            self.file_progress_list.clear()
            self.file_progress_list.start_cpu_tracking()  # Start tracking CPU during installation
            self._premium_notice_shown = False
            self._stalled_download_start_time = None
            self._stalled_download_notified = False
            self._stalled_data_snapshot = 0
            self._token_error_notified = False  # Reset token error notification
            self._premium_failure_active = False
            self._post_install_active = False
            self._post_install_current_step = 0
            # Activity tab is always visible (tabs handle visibility automatically)
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)
            
            # CRITICAL: Final safety check - ensure online modlists use machine_url
            if install_mode == 'online':
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    expected_machine_url = self.selected_modlist_info.get('machine_url')
                    if expected_machine_url:
                        modlist = expected_machine_url  # Force use machine_url
                    else:
                        self._abort_with_message(
                            "critical",
                            "Installation Error",
                            "Cannot determine modlist machine URL. Please select the modlist again."
                        )
                        return
                else:
                    self._abort_with_message(
                        "critical",
                        "Installation Error",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
            
            logger.debug(f'DEBUG: Calling run_modlist_installer with modlist={modlist}, install_dir={install_dir}, downloads_dir={downloads_dir}, install_mode={install_mode}')
            self.run_modlist_installer(modlist, install_dir, downloads_dir, api_key, install_mode, oauth_info)
        except Exception as e:
            logger.debug(f"DEBUG: Exception in validate_and_start_install: {e}")
            import traceback
            logger.debug(f"DEBUG: Traceback: {traceback.format_exc()}")
            # Re-enable all controls after exception
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            logger.debug(f"DEBUG: Controls re-enabled in exception handler")

    def run_modlist_installer(self, modlist, install_dir, downloads_dir, api_key, install_mode='online', oauth_info=None):
        logger.debug('DEBUG: run_modlist_installer called - USING THREADED BACKEND WRAPPER')
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Clear console for fresh installation output
        self.console.clear()
        from jackify import __version__ as jackify_version
        self._safe_append_text(f"Jackify v{jackify_version}")
        self._safe_append_text("Starting modlist installation with custom progress handling...")
        
        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        self.install_thread = InstallerThread(
            modlist, install_dir, downloads_dir, api_key, self.modlist_name_edit.text().strip(), install_mode,
            progress_state_manager=self.progress_state_manager,  # R&D: Pass progress state manager
            auth_service=self.auth_service,  # Fix Issue #127: Pass auth_service for Premium detection diagnostics
            oauth_info=oauth_info  # Pass OAuth state for auto-refresh
        )
        self.install_thread.output_received.connect(self.on_installation_output)
        self.install_thread.progress_received.connect(self.on_installation_progress)
        self.install_thread.progress_updated.connect(self.on_progress_updated)  # R&D: Connect progress update
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        self.install_thread.premium_required_detected.connect(self.on_premium_required_detected)
        # R&D: Pass progress state manager to thread
        self.install_thread.progress_state_manager = self.progress_state_manager
        self.install_thread.start()
