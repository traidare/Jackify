"""VNV automation methods for InstallModlistScreen (Mixin).

Delegates to VNVAutomationController for the actual workflow.
"""

import logging

logger = logging.getLogger(__name__)


class VNVAutomationMixin:
    """Mixin providing VNV automation methods for InstallModlistScreen."""

    def _check_and_run_vnv_automation(self, modlist_name: str, install_dir: str) -> bool:
        """Check if VNV automation should run and start it if applicable.

        Returns:
            True if VNV automation is starting (success dialog should be deferred)
            False if no VNV automation needed (show success dialog immediately)
        """
        from ..services.vnv_automation_controller import VNVAutomationController

        self._vnv_controller = VNVAutomationController()
        return self._vnv_controller.attempt(
            parent=self,
            modlist_name=modlist_name,
            install_dir=install_dir,
            on_progress=self._safe_append_text,
            on_complete=self._on_vnv_complete,
            begin_feedback=self._begin_post_install_feedback,
            handle_feedback=self._handle_post_install_progress,
        )

    def _on_vnv_complete(self, success: bool, error: str):
        """Handle VNV automation completion and show deferred success dialog."""
        self._end_post_install_feedback(not bool(error))

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

        if hasattr(self, '_pending_success_dialog_params'):
            params = self._pending_success_dialog_params
            del self._pending_success_dialog_params

            self.file_progress_list.clear()

            from ..dialogs import SuccessDialog
            success_dialog = SuccessDialog(
                modlist_name=params['modlist_name'],
                workflow_type="install",
                time_taken=params['time_taken'],
                game_name=params['game_name'],
                parent=self,
            )
            success_dialog.show()

            if params.get('enb_detected'):
                try:
                    from ..dialogs.enb_proton_dialog import ENBProtonDialog
                    enb_dialog = ENBProtonDialog(modlist_name=params['modlist_name'], parent=self)
                    enb_dialog.exec()
                except Exception as e:
                    logger.warning("Failed to show ENB dialog: %s", e)
