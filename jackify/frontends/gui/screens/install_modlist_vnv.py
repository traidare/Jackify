"""VNV automation methods for InstallModlistScreen (Mixin)."""
from pathlib import Path
from PySide6.QtCore import QTimer
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class VNVAutomationMixin:
    """Mixin providing VNV automation methods for InstallModlistScreen."""

    def _check_and_run_vnv_automation(self, modlist_name: str, install_dir: str) -> bool:
        """Check if VNV automation should run and execute if applicable in background thread

        Args:
            modlist_name: Name of the installed modlist
            install_dir: Installation directory path

        Returns:
            True if VNV automation is starting (success dialog should be deferred)
            False if no VNV automation needed (show success dialog immediately)
        """
        try:
            from jackify.backend.services.vnv_integration_helper import should_offer_vnv_automation
            from jackify.backend.handlers.path_handler import PathHandler
            from jackify.backend.services.vnv_post_install_service import VNVPostInstallService
            from jackify.backend.services.automated_prefix_service import AutomatedPrefixService

            # Get paths first (needed for VNV detection)
            install_path = Path(install_dir)

            # Quick check before importing more (pass install location for ModOrganizer.ini check)
            if not should_offer_vnv_automation(modlist_name, install_path):
                return False

            game_paths = PathHandler().find_vanilla_game_paths()
            game_root = game_paths.get('Fallout New Vegas')

            if not game_root:
                logger.debug("DEBUG: VNV automation skipped - FNV game root not found")
                return False

            # Initialize service to check completion status
            vnv_service = VNVPostInstallService(
                modlist_install_location=install_path,
                game_root=game_root,
                ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path()
            )

            # Check what's already done
            completed = vnv_service.check_already_completed()
            # Only skip if ALL three steps are completed
            if completed['root_mods'] and completed['4gb_patch'] and completed['bsa_decompressed']:
                logger.info("VNV automation steps already completed")
                return False

            # Get automation description for confirmation
            description = vnv_service.get_automation_description()

            # Show confirmation dialog ON MAIN THREAD (not in worker thread!)
            from ..services.message_service import MessageService
            from PySide6.QtWidgets import QMessageBox
            reply = MessageService.question(
                self,
                "VNV Post-Install Automation",
                description,
                critical=False,
                safety_level="medium"
            )

            if reply != QMessageBox.Yes:
                logger.info("User declined VNV automation")
                return False

            # Enable post-install progress tracking for VNV automation
            self._begin_post_install_feedback()

            # User confirmed - start automation in background thread
            # Note: manual_file_callback is not passed because Qt GUI operations
            # cannot be called from a background thread. If downloads fail,
            # the service will return instructions for manual download instead.
            self._run_vnv_automation_threaded(
                modlist_name,
                install_path,
                game_root
            )

            return True  # VNV automation is running, defer success dialog

        except Exception as e:
            logger.debug(f"ERROR: Failed to start VNV automation: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return False  # Error - show success dialog anyway

    def _run_vnv_automation_threaded(self, modlist_name, install_path, game_root):
        """Run VNV automation in a background thread with progress updates

        Note: User confirmation should already be obtained before calling this method.
        Manual file selection is not supported from background threads - if downloads
        fail, the service will return instructions for manual download.
        """
        from PySide6.QtCore import QThread, Signal
        from jackify.backend.services.vnv_integration_helper import run_vnv_automation_if_applicable
        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService

        class VNVAutomationWorker(QThread):
            progress_update = Signal(str)
            completed = Signal(bool, str)  # (success, error_message)

            def __init__(self, modlist_name, install_path, game_root, ttw_installer_path):
                super().__init__()
                self.modlist_name = modlist_name
                self.install_path = install_path
                self.game_root = game_root
                self.ttw_installer_path = ttw_installer_path

            def run(self):
                try:
                    # User already confirmed, pass lambda that always returns True
                    # manual_file_callback is None - downloads that fail will return
                    # instructions for manual download instead of showing Qt dialogs
                    automation_ran, error = run_vnv_automation_if_applicable(
                        modlist_name=self.modlist_name,
                        modlist_install_location=self.install_path,
                        game_root=self.game_root,
                        ttw_installer_path=self.ttw_installer_path,
                        progress_callback=self.progress_update.emit,
                        manual_file_callback=None,
                        confirmation_callback=lambda desc: True  # Already confirmed on main thread
                    )
                    self.completed.emit(error is None, error or "")
                except Exception as e:
                    import traceback
                    self.completed.emit(False, f"Exception: {str(e)}\n{traceback.format_exc()}")

        # Create and start worker
        self.vnv_worker = VNVAutomationWorker(
            modlist_name,
            install_path,
            game_root,
            AutomatedPrefixService.get_ttw_installer_path()
        )

        # Connect signals
        self.vnv_worker.progress_update.connect(self._on_vnv_progress)
        self.vnv_worker.completed.connect(self._on_vnv_complete)
        self.vnv_worker.finished.connect(self.vnv_worker.deleteLater)

        # Start worker
        self.vnv_worker.start()

    def _on_vnv_progress(self, message: str):
        """Handle VNV automation progress updates"""
        self._safe_append_text(message)
        # Also update progress indicator, Activity window, and Details window
        self._handle_post_install_progress(message)

    def _on_vnv_complete(self, success: bool, error: str):
        """Handle VNV automation completion and show deferred success dialog"""
        # End post-install feedback now that VNV automation is complete
        self._end_post_install_feedback(True)

        if not success and error:
            from ..services.message_service import MessageService
            MessageService.warning(
                self,
                "VNV Automation Failed",
                f"VNV post-install automation encountered an error:\n\n{error}\n\n"
                "You can complete these steps manually by following the guide at:\n"
                "https://vivanewvegas.moddinglinked.com/wabbajack.html"
            )
        elif success:
            self._safe_append_text("VNV post-install automation completed successfully")

        # Show the deferred success dialog now that VNV automation is complete
        if hasattr(self, '_pending_success_dialog_params'):
            params = self._pending_success_dialog_params
            del self._pending_success_dialog_params  # Clean up

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show success dialog
            from ..dialogs import SuccessDialog
            success_dialog = SuccessDialog(
                modlist_name=params['modlist_name'],
                workflow_type="install",
                time_taken=params['time_taken'],
                game_name=params['game_name'],
                parent=self
            )
            success_dialog.show()

            # Show ENB Proton dialog if ENB was detected
            if params.get('enb_detected'):
                try:
                    from ..dialogs.enb_proton_dialog import ENBProtonDialog
                    enb_dialog = ENBProtonDialog(modlist_name=params['modlist_name'], parent=self)
                    enb_dialog.exec()  # Modal dialog - blocks until user clicks OK
                except Exception as e:
                    # Non-blocking: if dialog fails, just log and continue
                    logger.warning(f"Failed to show ENB dialog: {e}")

