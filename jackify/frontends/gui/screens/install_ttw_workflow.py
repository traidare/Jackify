"""TTW installation workflow methods for InstallTTWScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QThread, Signal, QProcess
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtGui import QTextCursor
import logging
import os
import re
import time
import traceback
import shutil
import tempfile
# Runtime imports to avoid circular dependencies
from jackify.frontends.gui.services.message_service import MessageService  # Runtime import
from jackify.backend.handlers.validation_handler import ValidationHandler  # Runtime import
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog  # Runtime import
from ..shared_theme import JACKIFY_COLOR_BLUE  # Runtime import
from ..utils import strip_ansi_control_codes  # Runtime import

logger = logging.getLogger(__name__)


def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class TTWWorkflowMixin:
    """Mixin providing installation workflow methods for InstallTTWScreen."""

    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()
        debug_print('DEBUG: validate_and_start_install called')

        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()
        debug_print('DEBUG: Reloaded config from disk')

        # Check TTW requirements first
        if not self._check_ttw_requirements():
            return
        
        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Disable all controls during installation (except Cancel)
        self._disable_controls_during_operation()
        
        try:
            # TTW only needs .mpi file
            mpi_path = self.file_edit.text().strip()
            if not mpi_path or not os.path.isfile(mpi_path) or not mpi_path.endswith('.mpi'):
                MessageService.warning(self, "Invalid TTW File", "Please select a valid TTW .mpi file.")
                self._enable_controls_after_operation()
                return
            install_dir = self.install_dir_edit.text().strip()
            
            # Validate required fields
            missing_fields = []
            if not install_dir:
                missing_fields.append("Install Directory")
            if missing_fields:
                MessageService.warning(self, "Missing Required Fields", f"Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields))
                self._enable_controls_after_operation()
                return
            
            # Validate install directory
            validation_handler = ValidationHandler()
            from pathlib import Path
            install_dir_path = Path(install_dir)
            
            # Check for dangerous directories first (system roots, etc.)
            if validation_handler.is_dangerous_directory(install_dir_path):
                dlg = WarningDialog(
                    f"The directory '{install_dir}' is a system or user root and cannot be used for TTW installation.",
                    parent=self
                )
                if not dlg.exec() or not dlg.confirmed:
                    self._enable_controls_after_operation()
                    return
            
            # Check if directory exists and is not empty - TTW_Linux_Installer will overwrite existing files
            if install_dir_path.exists() and install_dir_path.is_dir():
                # Check if directory contains any files
                try:
                    has_files = any(install_dir_path.iterdir())
                    if has_files:
                        # Directory exists and is not empty - warn user about deletion
                        dlg = WarningDialog(
                            f"The TTW output directory already exists and contains files:\n{install_dir}\n\n"
                            f"All files in this directory will be deleted before installation.\n\n"
                            f"This action cannot be undone.",
                            parent=self
                        )
                        if not dlg.exec() or not dlg.confirmed:
                            self._enable_controls_after_operation()
                            return
                        
                        # User confirmed - delete all contents of the directory
                        import shutil
                        try:
                            for item in install_dir_path.iterdir():
                                if item.is_dir():
                                    shutil.rmtree(item)
                                else:
                                    item.unlink()
                            debug_print(f"DEBUG: Deleted all contents of {install_dir}")
                        except Exception as e:
                            MessageService.critical(self, "Error", f"Failed to delete directory contents:\n{e}")
                            self._enable_controls_after_operation()
                            return
                except Exception as e:
                    debug_print(f"DEBUG: Error checking directory contents: {e}")
                    # If we can't check, proceed
            
            if not os.path.isdir(install_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create install directory:\n{e}")
                        self._enable_controls_after_operation()
                        return
                else:
                    self._enable_controls_after_operation()
                    return
            
            # Start TTW installation
            self.console.clear()
            self.process_monitor.clear()
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)
            
            debug_print(f'DEBUG: Calling run_ttw_installer with mpi_path={mpi_path}, install_dir={install_dir}')
            self.run_ttw_installer(mpi_path, install_dir)
        except Exception as e:
            debug_print(f"DEBUG: Exception in validate_and_start_install: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            # Re-enable all controls after exception
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            debug_print(f"DEBUG: Controls re-enabled in exception handler")

    def run_ttw_installer(self, mpi_path, install_dir):
        debug_print('DEBUG: run_ttw_installer called - USING THREADED BACKEND WRAPPER')

        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # Refresh Proton version and winetricks settings
        self.config_handler._load_config()

        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Clear console for fresh installation output
        self.console.clear()
        self._safe_append_text("Starting TTW installation...")

        # Initialize Activity window with immediate feedback
        self.file_progress_list.clear()
        self._update_ttw_phase("Initializing TTW installation", 0, 0, 0)
        # Force UI update immediately
        QApplication.processEvents()

        # Show status banner and show details checkbox
        self.status_banner.setVisible(True)
        self.status_banner.setText("Initializing TTW installation...")
        self.show_details_checkbox.setVisible(True)

        # Reset banner to default blue color for new installation
        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)

        self.ttw_start_time = time.time()

        # Start a timer to update elapsed time
        self.ttw_elapsed_timer = QTimer()
        self.ttw_elapsed_timer.timeout.connect(self._update_ttw_elapsed_time)
        self.ttw_elapsed_timer.start(1000)  # Update every second

        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        # Create installation thread
        from PySide6.QtCore import QThread, Signal
        
        class TTWInstallationThread(QThread):
            output_batch_received = Signal(list)  # Batched output lines
            progress_received = Signal(str)
            installation_finished = Signal(bool, str)

            def __init__(self, mpi_path, install_dir):
                super().__init__()
                self.mpi_path = mpi_path
                self.install_dir = install_dir
                self.cancelled = False
                self.proc = None
                self.output_buffer = []  # Buffer for batching output
                self.last_emit_time = 0  # Track when we last emitted

            def cancel(self):
                self.cancelled = True
                try:
                    if self.proc and self.proc.poll() is None:
                        self.proc.terminate()
                except Exception:
                    pass

            def process_and_buffer_line(self, raw_line):
                """Process line in worker thread and add to buffer"""
                # Strip ANSI codes
                cleaned = strip_ansi_control_codes(raw_line).strip()

                # Strip emojis (do this in worker thread, not UI thread)
                filtered_chars = []
                for char in cleaned:
                    code = ord(char)
                    is_emoji = (
                        (0x1F300 <= code <= 0x1F9FF) or
                        (0x1F600 <= code <= 0x1F64F) or
                        (0x2600 <= code <= 0x26FF) or
                        (0x2700 <= code <= 0x27BF)
                    )
                    if not is_emoji:
                        filtered_chars.append(char)
                cleaned = ''.join(filtered_chars).strip()

                # Only buffer non-empty lines
                if cleaned:
                    self.output_buffer.append(cleaned)

            def flush_output_buffer(self):
                """Emit buffered lines as a batch"""
                if self.output_buffer:
                    self.output_batch_received.emit(self.output_buffer[:])
                    self.output_buffer.clear()
                    self.last_emit_time = time.time()
            
            def run(self):
                try:
                    from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
                    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    from pathlib import Path
                    import tempfile

                    # Emit startup message
                    self.process_and_buffer_line("Initializing TTW installation...")
                    self.flush_output_buffer()

                    # Create backend handler
                    filesystem_handler = FileSystemHandler()
                    config_handler = ConfigHandler()
                    ttw_handler = TTWInstallerHandler(
                        steamdeck=False,
                        verbose=False,
                        filesystem_handler=filesystem_handler,
                        config_handler=config_handler
                    )

                    # Create temporary output file
                    output_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.ttw_output', encoding='utf-8')
                    output_file_path = Path(output_file.name)
                    output_file.close()

                    # Start installation via backend (non-blocking)
                    self.process_and_buffer_line("Starting TTW installation...")
                    self.flush_output_buffer()

                    self.proc, error_msg = ttw_handler.start_ttw_installation(
                        Path(self.mpi_path),
                        Path(self.install_dir),
                        output_file_path
                    )

                    if not self.proc:
                        self.installation_finished.emit(False, error_msg or "Failed to start TTW installation")
                        return

                    self.process_and_buffer_line("TTW_Linux_Installer process started, monitoring output...")
                    self.flush_output_buffer()

                    # Poll output file with batching for UI responsiveness
                    last_position = 0
                    BATCH_INTERVAL = 0.3  # Emit batches every 300ms

                    while self.proc.poll() is None:
                        if self.cancelled:
                            break

                        try:
                            # Read new content from file
                            with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                                f.seek(last_position)
                                new_lines = f.readlines()
                                last_position = f.tell()

                                # Process lines in worker thread (heavy work done here, not UI thread)
                                for line in new_lines:
                                    if self.cancelled:
                                        break
                                    self.process_and_buffer_line(line.rstrip())

                                # Emit batch if enough time has passed
                                current_time = time.time()
                                if current_time - self.last_emit_time >= BATCH_INTERVAL:
                                    self.flush_output_buffer()

                        except Exception:
                            pass

                        # Sleep longer since we're batching
                        time.sleep(0.1)

                    # Read any remaining output
                    try:
                        with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_position)
                            remaining_lines = f.readlines()
                            for line in remaining_lines:
                                self.process_and_buffer_line(line.rstrip())
                        self.flush_output_buffer()
                    except Exception:
                        pass

                    # Clean up
                    try:
                        output_file_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                    ttw_handler.cleanup_ttw_process(self.proc)

                    # Check result
                    returncode = self.proc.returncode if self.proc else -1
                    if self.cancelled:
                        self.installation_finished.emit(False, "Installation cancelled by user")
                    elif returncode == 0:
                        self.installation_finished.emit(True, "TTW installation completed successfully!")
                    else:
                        self.installation_finished.emit(False, f"TTW installation failed with exit code {returncode}")

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    self.installation_finished.emit(False, f"Installation error: {str(e)}")

        # Start the installation thread
        self.install_thread = TTWInstallationThread(mpi_path, install_dir)
        # Use QueuedConnection to ensure signals are processed asynchronously and don't block UI
        self.install_thread.output_batch_received.connect(self.on_installation_output_batch, Qt.QueuedConnection)
        self.install_thread.progress_received.connect(self.on_installation_progress, Qt.QueuedConnection)
        self.install_thread.installation_finished.connect(self.on_installation_finished, Qt.QueuedConnection)

        # Start thread and immediately process events to show initial UI state
        self.install_thread.start()
        QApplication.processEvents()  # Process any pending events to update UI immediately

    def on_installation_output_batch(self, messages):
        """Handle batched output from TTW_Linux_Installer (already processed in worker thread)"""
        # Lines are already cleaned (ANSI codes stripped, emojis removed) in worker thread
        # CRITICAL: Accumulate all console updates and do ONE widget update per batch

        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_current_phase = None
            self._ttw_last_progress = 0
            self._ttw_last_activity_update = 0
            self.ttw_start_time = time.time()

        # Accumulate lines to display (do ONE console update at end)
        lines_to_display = []
        html_fragments = []
        show_details_due_to_error = False
        latest_progress = None  # Track latest progress to update activity ONCE per batch

        for cleaned in messages:
            if not cleaned:
                continue

            lower_cleaned = cleaned.lower()

            # Extract progress (but don't update UI yet - wait until end of batch)
            try:
                progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
                if progress_match:
                    current = int(progress_match.group(1))
                    total = int(progress_match.group(2))
                    percent = int((current / total) * 100) if total > 0 else 0
                    latest_progress = (current, total, percent)

                if 'loading manifest:' in lower_cleaned:
                    manifest_match = re.search(r'loading manifest:\s*(\d+)/(\d+)', lower_cleaned)
                    if manifest_match:
                        current = int(manifest_match.group(1))
                        total = int(manifest_match.group(2))
                        self._ttw_current_phase = "Loading manifest"
            except Exception:
                pass

            # Determine if we should show this line
            is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
            is_warning = 'warning:' in lower_cleaned
            is_milestone = any(kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid'])
            is_file_op = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
            
            # Filter out meaningless standalone messages (just "OK", etc.)
            is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']
            
            should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)

            if should_show:
                if is_error or is_warning:
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_fragments.append(f'<span style="color: {color};">{escaped}</span>')
                    show_details_due_to_error = True
                else:
                    lines_to_display.append(cleaned)

        # Update activity widget ONCE per batch (if progress changed significantly)
        if latest_progress:
            current, total, percent = latest_progress
            current_time = time.time()
            percent_changed = abs(percent - self._ttw_last_progress) >= 1
            time_passed = (current_time - self._ttw_last_activity_update) >= 0.5  # 500ms throttle

            if percent_changed or time_passed:
                self._update_ttw_activity(current, total, percent)
                self._ttw_last_progress = percent
                self._ttw_last_activity_update = current_time

        # Now do ONE console update for entire batch
        if html_fragments or lines_to_display:
            try:
                # Update console with all accumulated output in one operation
                if html_fragments:
                    combined_html = '<br>'.join(html_fragments)
                    self.console.insertHtml(combined_html + '<br>')

                if lines_to_display:
                    combined_text = '\n'.join(lines_to_display)
                    self.console.append(combined_text)

                if show_details_due_to_error and not self.show_details_checkbox.isChecked():
                    self.show_details_checkbox.setChecked(True)
            except Exception:
                pass

    def on_installation_output(self, message):
        """Handle regular output from TTW_Linux_Installer with comprehensive filtering and smart parsing"""
        # Initialize tracking structures
        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_last_extraction_progress = 0
            self._ttw_last_file_operation_time = 0
            self._ttw_file_operation_count = 0
            self._ttw_current_phase = None
            self._ttw_last_progress_line = None
            self._ttw_progress_line_text = None
        
        # Filter out internal status messages from user console
        if message.strip().startswith('[Jackify]'):
            # Log internal messages to file but don't show in console
            self._write_to_log_file(message)
            return

        # Strip ANSI terminal control codes
        cleaned = strip_ansi_control_codes(message).strip()

        # Strip emojis from output (TTW_Linux_Installer includes emojis)
        # Use character-by-character filtering to avoid regex recursion issues
        # Safer than regex for emoji removal
        filtered_chars = []
        for char in cleaned:
            code = ord(char)
            # Check if character is in emoji ranges - skip emojis
            is_emoji = (
                (0x1F300 <= code <= 0x1F9FF) or  # Miscellaneous Symbols and Pictographs
                (0x1F600 <= code <= 0x1F64F) or  # Emoticons
                (0x2600 <= code <= 0x26FF) or    # Miscellaneous Symbols
                (0x2700 <= code <= 0x27BF)       # Dingbats
            )
            if not is_emoji:
                filtered_chars.append(char)
        cleaned = ''.join(filtered_chars).strip()

        # Filter out empty lines
        if not cleaned:
            return

        # Initialize start time if not set
        if not hasattr(self, 'ttw_start_time'):
            self.ttw_start_time = time.time()

        lower_cleaned = cleaned.lower()

        # === MINIMAL PROCESSING: Match standalone behavior as closely as possible ===
        # When running standalone: output goes directly to terminal, no processing
        # Here: We must process each line, but do it as efficiently as possible
        
        # Always log to file (simple, no recursion risk)
        try:
            self._write_to_log_file(cleaned)
        except Exception:
            pass
        
        # Extract progress for Activity window (minimal regex, wrapped in try/except)
        try:
            # Try [X/Y] pattern
            progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
            if progress_match:
                current = int(progress_match.group(1))
                total = int(progress_match.group(2))
                percent = int((current / total) * 100) if total > 0 else 0
                phase = self._ttw_current_phase or "Processing"
                self._update_ttw_activity(current, total, percent)
            
            # Try "Loading manifest: X/Y"
            if 'loading manifest:' in lower_cleaned:
                manifest_match = re.search(r'loading manifest:\s*(\d+)/(\d+)', lower_cleaned)
                if manifest_match:
                    current = int(manifest_match.group(1))
                    total = int(manifest_match.group(2))
                    percent = int((current / total) * 100) if total > 0 else 0
                    self._ttw_current_phase = "Loading manifest"
                    self._update_ttw_activity(current, total, percent)
        except Exception:
            pass  # Skip if regex fails
        
        # Determine if we should show this line
        # By default: only show errors, warnings, milestones
        # Everything else: only in details mode
        is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
        is_warning = 'warning:' in lower_cleaned
        is_milestone = any(kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid'])
        is_file_op = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
        
        # Filter out meaningless standalone messages (just "OK", etc.)
        is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']
        
        should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)
        
        if should_show:
            # Direct console append - no recursion, no complex processing
            try:
                if is_error or is_warning:
                    # Color code errors/warnings
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html = f'<span style="color: {color};">{escaped}</span><br>'
                    self.console.insertHtml(html)
                    if not self.show_details_checkbox.isChecked():
                        self.show_details_checkbox.setChecked(True)
                else:
                    self.console.append(cleaned)
            except Exception:
                pass  # Don't break on console errors
        
        return

    def on_installation_progress(self, progress_message):
        """Replace the last line in the console for progress updates"""
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.movePosition(QTextCursor.StartOfLine, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(progress_message)
        # Don't force scroll for progress updates - let user control

    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        debug_print(f"DEBUG: on_installation_finished called with success={success}, message={message}")

        # Stop elapsed timer
        if hasattr(self, 'ttw_elapsed_timer'):
            self.ttw_elapsed_timer.stop()

        # Update status banner
        if success:
            elapsed = int(time.time() - self.ttw_start_time) if hasattr(self, 'ttw_start_time') else 0
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.status_banner.setText(f"Installation completed successfully! Total time: {minutes}m {seconds}s")
            self.status_banner.setStyleSheet(f"""
                background-color: #1a4d1a;
                color: #4CAF50;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)
        else:
            self.status_banner.setText(f"Installation failed: {message}")
            self.status_banner.setStyleSheet(f"""
                background-color: #4d1a1a;
                color: #f44336;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit)

    def process_finished(self, exit_code, exit_status):
        debug_print(f"DEBUG: process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        debug_print("DEBUG: Button states reset in process_finished")
        

        if exit_code == 0:
            # TTW installation complete
            self._safe_append_text("\nTTW installation completed successfully!")
            self._safe_append_text("The merged TTW files have been created in the output directory.")

            # Check if we're in modlist integration mode
            if self._integration_mode:
                self._safe_append_text("\nIntegrating TTW into modlist...")
                self._perform_modlist_integration()
            else:
                # Standard mode - ask user if they want to create a mod archive for MO2
                reply = MessageService.question(
                    self, "TTW Installation Complete!",
                    "Tale of Two Wastelands installation completed successfully!\n\n"
                    f"Output location: {self.install_dir_edit.text()}\n\n"
                    "Would you like to create a zipped mod archive for MO2?\n"
                    "This will package the TTW files for easy installation into Mod Organizer 2.",
                    critical=False
                )

                if reply == QMessageBox.Yes:
                    self._create_ttw_mod_archive()
                else:
                    MessageService.information(
                        self, "Installation Complete",
                        "TTW installation complete!\n\n"
                        "You can manually use the TTW files from the output directory.",
                        safety_level="medium"
                    )
        else:
            # Check for user cancellation first
            last_output = self.console.toPlainText()
            if "cancelled by user" in last_output.lower():
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
            else:
                MessageService.critical(self, "Install Failed", "The modlist install failed. Please check the console output for details.")
                self._safe_append_text(f"\nInstall failed (exit code {exit_code}).")
        self.console.moveCursor(QTextCursor.End)

