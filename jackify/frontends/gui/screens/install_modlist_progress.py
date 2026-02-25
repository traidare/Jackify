"""Progress and installation event handlers for InstallModlistScreen (Mixin)."""
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QTextCursor
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.errors import wabbajack_install_failed
from jackify.shared.progress_models import InstallationPhase, OperationType, InstallationProgress, FileProgress
from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
import time
import logging

logger = logging.getLogger(__name__)
class ProgressHandlersMixin:
    """Mixin providing progress tracking and installation event handlers for InstallModlistScreen."""

    def on_installation_progress(self, progress_message):
        """
        Handle progress messages from installation thread.

        NOTE: This is called for MOST engine output, not just progress lines!
        The name is misleading - it's actually the main output path.
        """
        # Always write output to console buffer (same as on_installation_output)
        self._safe_append_text(progress_message)

    def on_premium_required_detected(self, engine_line: str):
        """Handle detection of Nexus Premium requirement."""
        if self._premium_notice_shown:
            return

        self._premium_notice_shown = True
        self._premium_failure_active = True

        user_message = (
            "Nexus Mods rejected the automated download because this account is not Premium. "
            "Jackify currently requires a Nexus Premium membership for automated installs, "
            "and non-premium support is still planned."
        )

        if engine_line:
            logger.warning(f"Nexus Premium required, engine message: {engine_line}")
            self._safe_append_text(f"[Jackify] Engine message: {engine_line}")
        logger.warning("Nexus Premium required for this modlist install")
        self._safe_append_text("[Jackify] Jackify detected that Nexus Premium is required for this modlist install.")

        MessageService.critical(
            self,
            "Nexus Premium Required",
            f"{user_message}\n\nDetected engine output:\n{engine_line or 'Buy Nexus Premium to automate this process.'}",
            safety_level="medium"
        )

        if hasattr(self, 'install_thread') and self.install_thread:
            self.install_thread.cancel()

    def on_progress_updated(self, progress_state):
        """R&D: Handle structured progress updates from parser"""
        # Calculate proper overall progress during BSA building
        # During BSA building, file installation is at 100% but BSAs are still being built
        # Override overall_percent to show BSA building progress instead
        if progress_state.bsa_building_total > 0 and progress_state.bsa_building_current > 0:
            bsa_percent = (progress_state.bsa_building_current / progress_state.bsa_building_total) * 100.0
            progress_state.overall_percent = min(99.0, bsa_percent)  # Cap at 99% until fully complete

        # CRITICAL: Detect stalled downloads (0.0MB/s for extended period)
        # Catch silent token refresh failures or network issues
        # IMPORTANT: Only check during DOWNLOAD phase, not during VALIDATE phase
        # Validation checks existing files and shows 0.0MB/s, which is expected behavior
        if progress_state.phase == InstallationPhase.DOWNLOAD:
            speed_display = progress_state.get_overall_speed_display()
            # Check if speed is 0 or very low (< 0.1MB/s) for more than 2 minutes
            # Only trigger if we're actually in download phase (not validation)
            is_stalled = not speed_display or speed_display == "0.0B/s" or \
                        (speed_display and any(x in speed_display.lower() for x in ['0.0mb/s', '0.0kb/s', '0b/s']))
            
            # Additional check: Only consider it stalled if we have active download files
            # If no files are being downloaded, it might just be between downloads
            has_active_downloads = any(
                f.operation == OperationType.DOWNLOAD and not f.is_complete 
                for f in progress_state.active_files
            )
            
            if is_stalled and has_active_downloads:
                if self._stalled_download_start_time is None:
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                elif progress_state.data_processed > self._stalled_data_snapshot:
                    # Bytes are advancing despite 0 speed readout — engine reporting lag, not a real stall
                    self._stalled_download_start_time = time.time()
                    self._stalled_data_snapshot = progress_state.data_processed
                else:
                    stalled_duration = time.time() - self._stalled_download_start_time
                    # Warn after 2 minutes of stalled downloads
                    if stalled_duration > 120 and not self._stalled_download_notified:
                        self._stalled_download_notified = True
                        logger.warning("Downloads stalled (0.0MB/s for 2+ minutes)")
                        MessageService.warning(
                            self,
                            "Download Stalled",
                            (
                                "Downloads have been stalled (0.0MB/s) for over 2 minutes.\n\n"
                                "Possible causes:\n"
                                "• OAuth token expired and refresh failed\n"
                                "• Network connectivity issues\n"
                                "• Nexus Mods server issues\n\n"
                                "Please check the console output (Show Details) for error messages.\n"
                                "If authentication failed, you may need to re-authorize in Settings."
                            ),
                            safety_level="low"
                        )
                        # Force console to be visible
                        if not self.show_details_checkbox.isChecked():
                            self.show_details_checkbox.setChecked(True)
                        # Add warning to console
                        self._safe_append_text(
                            "\n[Jackify] WARNING: Downloads have stalled (0.0MB/s for 2+ minutes)\n"
                            "[Jackify] This may indicate an authentication or network issue.\n"
                            "[Jackify] Check the console above for error messages.\n"
                        )
            else:
                # Downloads are active - reset stall timer
                self._stalled_download_start_time = None
                self._stalled_download_notified = False
                self._stalled_data_snapshot = 0

        # Update progress indicator widget
        self.progress_indicator.update_progress(progress_state)
        
        # Only show file progress list if console is not visible (mutually exclusive)
        console_visible = self.show_details_checkbox.isChecked()
        
        # Determine phase display name up front (short/stable label)
        phase_label = progress_state.get_phase_label()
        
        # During installation or extraction phase, show summary counter instead of individual files
        # Avoid cluttering UI with completed files
        is_installation_phase = (
            progress_state.phase == InstallationPhase.INSTALL or
            (progress_state.phase_name and 'install' in progress_state.phase_name.lower())
        )
        is_extraction_phase = (
            progress_state.phase == InstallationPhase.EXTRACT or
            (progress_state.phase_name and 'extract' in progress_state.phase_name.lower())
        )
        
        # Detect BSA building phase - check multiple indicators
        is_bsa_building = False
        
        # Check phase name for BSA indicators
        if progress_state.phase_name:
            phase_lower = progress_state.phase_name.lower()
            if 'bsa' in phase_lower or ('building' in phase_lower and progress_state.phase == InstallationPhase.INSTALL):
                is_bsa_building = True
        
        # Check message/status text for BSA building indicators
        if not is_bsa_building and progress_state.message:
            msg_lower = progress_state.message.lower()
            if ('building' in msg_lower or 'writing' in msg_lower or 'verifying' in msg_lower) and '.bsa' in msg_lower:
                is_bsa_building = True
        
        # Check if we have BSA files being processed (even if they're at 100%, they indicate BSA phase)
        if not is_bsa_building and progress_state.active_files:
            bsa_files = [f for f in progress_state.active_files if f.filename.lower().endswith('.bsa')]
            if len(bsa_files) > 0:
                # If we have any BSA files and we're in INSTALL phase, likely BSA building
                if progress_state.phase == InstallationPhase.INSTALL:
                    is_bsa_building = True
        
        # Also check display text for BSA mentions (fallback)
        if not is_bsa_building:
            display_lower = progress_state.display_text.lower()
            if 'bsa' in display_lower and progress_state.phase == InstallationPhase.INSTALL:
                is_bsa_building = True
        
        now_mono = time.monotonic()
        if is_bsa_building:
            self._bsa_hold_deadline = now_mono + 1.5
        elif now_mono < self._bsa_hold_deadline:
            is_bsa_building = True
        else:
            self._bsa_hold_deadline = now_mono

        if is_installation_phase:
            # During installation, we may have BSA building AND file installation happening
            # Show both: install summary + any active BSA files
            # Render loop handles smooth updates - just set target state
            
            current_step = progress_state.phase_step

            display_items = []

            # Line 1: Always show "Installing Files: X/Y" at the top (no progress bar, no size)
            if current_step > 0 or progress_state.phase_max_steps > 0:
                install_line = FileProgress(
                    filename=f"Installing Files: {current_step}/{progress_state.phase_max_steps}",
                    operation=OperationType.INSTALL,
                    percent=0.0,
                    speed=-1.0
                )
                install_line._no_progress_bar = True  # Flag to hide progress bar
                display_items.append(install_line)

            # Lines 2+: Show converting textures and BSA files
            # Extract and categorize active files
            for f in progress_state.active_files:
                if f.operation == OperationType.INSTALL:
                    if f.filename.lower().endswith('.bsa') or f.filename.lower().endswith('.ba2'):
                        # BSA: filename.bsa (42/89) - Use state-level BSA counter
                        if progress_state.bsa_building_total > 0:
                            display_filename = f"BSA: {f.filename} ({progress_state.bsa_building_current}/{progress_state.bsa_building_total})"
                        else:
                            display_filename = f"BSA: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break
                    elif f.filename.lower().endswith(('.dds', '.png', '.tga', '.bmp')):
                        # Converting Texture: filename.dds (234/1078)
                        # Use state-level texture counter (more reliable than file-level)
                        if progress_state.texture_conversion_total > 0:
                            display_filename = f"Converting Texture: {f.filename} ({progress_state.texture_conversion_current}/{progress_state.texture_conversion_total})"
                        else:
                            # No texture counter available, just show filename
                            display_filename = f"Converting Texture: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break

            # Update target state (render loop handles smooth display)
            # Explicitly pass None for summary_info to clear any stale summary data
            if display_items:
                self.file_progress_list.update_files(display_items, current_phase="Installing", summary_info=None)
            return
        elif is_extraction_phase:
            # Show summary info for Extracting phase (step count)
            # Render loop handles smooth updates - just set target state
            # Explicitly pass empty list for file_progresses to clear any stale file list
            current_step = progress_state.phase_step
            summary_info = {
                'current_step': current_step,
                'max_steps': progress_state.phase_max_steps,
            }
            phase_display_name = phase_label or "Extracting"
            self.file_progress_list.update_files([], current_phase=phase_display_name, summary_info=summary_info)
            return
        elif progress_state.active_files:
            if self.debug:
                logger.debug(f"DEBUG: Updating file progress list with {len(progress_state.active_files)} files")
                for fp in progress_state.active_files:
                    logger.debug(f"DEBUG:   - {fp.filename}: {fp.percent:.1f}% ({fp.operation.value})")
            # Pass phase label to update header (e.g., "[Activity - Downloading]")
            # Explicitly clear summary_info when showing file list
            try:
                self.file_progress_list.update_files(progress_state.active_files, current_phase=phase_label, summary_info=None)
            except RuntimeError as e:
                # Widget was deleted - ignore to prevent coredump
                if "already deleted" in str(e):
                    if self.debug:
                        logger.debug(f"DEBUG: Ignoring widget deletion error: {e}")
                    return
                raise
            except Exception as e:
                # Catch any other exceptions to prevent coredump
                if self.debug:
                    logger.debug(f"DEBUG: Error updating file progress list: {e}")
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
        else:
            # Show empty state so widget stays visible even when no files are active
            try:
                self.file_progress_list.update_files([], current_phase=phase_label)
            except RuntimeError as e:
                # Widget was deleted - ignore to prevent coredump
                if "already deleted" in str(e):
                    return
                raise
            except Exception as e:
                # Catch any other exceptions to prevent coredump
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)

    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        logger.debug(f"DEBUG: on_installation_finished called with success={success}, message={message}")
        # R&D: Clear all progress displays when installation completes
        self.progress_state_manager.reset()
        # Clear file list but keep CPU tracking running for configuration phase
        self.file_progress_list.list_widget.clear()
        self.file_progress_list._file_items.clear()
        self.file_progress_list._summary_widget = None
        self.file_progress_list._transition_label = None
        self.file_progress_list._last_phase = None
        
        if success:
            # Update progress indicator with completion
            final_state = InstallationProgress(
                phase=InstallationPhase.FINALIZE,
                phase_name="Installation Complete",
                overall_percent=100.0
            )
            self.progress_indicator.update_progress(final_state)

            try:
                from jackify.backend.utils.modlist_meta import write_modlist_meta
                thread = getattr(self, 'install_thread', None)
                if thread and getattr(thread, 'install_dir', None) and getattr(thread, 'modlist_name', None):
                    write_modlist_meta(
                        thread.install_dir,
                        thread.modlist_name,
                        getattr(self, '_current_game_type', None),
                        install_mode=getattr(thread, 'install_mode', 'online'),
                    )
            except Exception as _meta_err:
                logger.debug(f"Modlist meta write skipped: {_meta_err}")

            logger.info(f"Installation succeeded: {message}")
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)  # Simulate successful completion
        else:
            # Reset to initial state on failure
            self.progress_indicator.reset()

            if self._premium_failure_active:
                message = "Installation stopped because Nexus Premium is required for automated downloads."

            if not self._premium_failure_active:
                engine_error = getattr(self.install_thread, 'last_error', None)
                if engine_error:
                    self._engine_error = engine_error
                self._failure_message = message

            logger.error(f"Installation failed: {message}")
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit)  # Simulate error

    def process_finished(self, exit_code, exit_status):
        logger.debug(f"DEBUG: process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        logger.debug("DEBUG: Button states reset in process_finished")
        

        if exit_code == 0:
            # Check if this was an unsupported game
            game_type = getattr(self, '_current_game_type', None)
            game_name = getattr(self, '_current_game_name', None)
            
            if game_type and not self.wabbajack_parser.is_supported_game(game_type):
                # Show success message for unsupported games without post-install configuration
                MessageService.information(
                    self, "Modlist Install Complete!",
                    f"Modlist installation completed successfully!\n\n"
                    f"Note: Post-install configuration was skipped for unsupported game type: {game_name or game_type}\n\n"
                    f"You will need to manually configure Steam shortcuts and other post-install steps."
                )
                logger.warning(f"Post-install configuration skipped for unsupported game: {game_name or game_type}")
                self._safe_append_text(f"\nModlist installation completed successfully.")
                self._safe_append_text(f"\nWarning: Post-install configuration skipped for unsupported game: {game_name or game_type}")
            else:
                # Check if auto-restart is enabled
                auto_restart_enabled = hasattr(self, 'auto_restart_checkbox') and self.auto_restart_checkbox.isChecked()
                
                if auto_restart_enabled:
                    # Auto-accept Steam restart - proceed without dialog
                    logger.info("Auto-accepting Steam restart (unattended mode enabled)")
                    reply = QMessageBox.Yes  # Simulate user clicking Yes
                else:
                    # Show the normal install complete dialog for supported games
                    reply = MessageService.question(
                        self, "Modlist Install Complete!",
                        "Modlist install complete!\n\nWould you like to add this modlist to Steam and configure it now? Steam will restart, closing any game you have open!",
                        critical=False,  # Non-critical, won't steal focus
                        safety_level="medium",
                    )
                
                if reply == QMessageBox.Yes:
                    # --- Create Steam shortcut BEFORE restarting Steam ---
                    # Proceed directly to automated prefix creation
                    self.start_automated_prefix_workflow()
                else:
                    # User selected "No" - show completion message and keep GUI open
                    self._safe_append_text("\nModlist installation completed successfully!")
                    self._safe_append_text("Note: You can manually configure Steam integration later if needed.")
                    MessageService.information(
                        self, "Installation Complete", 
                        "Modlist installation completed successfully!\n\n"
                        "The modlist has been installed but Steam integration was skipped.\n"
                        "You can manually add the modlist to Steam later if desired.",
                        safety_level="medium"
                    )
                    # Re-enable controls since operation is complete
                    self._enable_controls_after_operation()
        else:
            # Check for user cancellation first - check message parameter first, then console
            if self._premium_failure_active:
                MessageService.warning(
                    self,
                    "Nexus Premium Required",
                    "Jackify stopped the installation because Nexus Mods reported that this account is not Premium.\n\n"
                    "Automatic installs currently require Nexus Premium. Non-premium support is planned.",
                    safety_level="medium"
                )
                logger.warning("Install stopped: Nexus Premium required")
                self._safe_append_text("\nInstall stopped: Nexus Premium required.")
                self._premium_failure_active = False
            elif hasattr(self, '_cancellation_requested') and self._cancellation_requested:
                # User explicitly cancelled via cancel button
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                self._cancellation_requested = False
            else:
                # Check console as fallback
                last_output = self.console.toPlainText()
                if "cancelled by user" in last_output.lower():
                    MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                else:
                    logger.error(f"Install failed (exit code {exit_code})")
                    engine_error = getattr(self, '_engine_error', None)
                    if engine_error:
                        self._engine_error = None
                        MessageService.show_error(self, engine_error)
                    else:
                        failure_msg = getattr(self, '_failure_message', None) or f"Exit code {exit_code}."
                        self._failure_message = None
                        MessageService.show_error(self, wabbajack_install_failed(failure_msg))
                    self._safe_append_text(f"\nInstall failed (exit code {exit_code}).")
        self.console.moveCursor(QTextCursor.End)
