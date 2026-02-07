"""
Main window startup and background tasks mixin.
Gallery cache preload, protontricks check, update check.
"""

import sys

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QDialog


def _debug_print(message):
    from jackify.backend.handlers.config_handler import ConfigHandler
    ch = ConfigHandler()
    if ch.get('debug_mode', False):
        print(message)


class MainWindowStartupMixin:
    """Mixin for startup and background tasks."""

    def _start_gallery_cache_preload(self):
        from PySide6.QtCore import QThread, Signal

        class GalleryCachePreloadThread(QThread):
            finished_signal = Signal(bool, str)

            def run(self):
                try:
                    from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
                    service = ModlistGalleryService()
                    metadata = service.fetch_modlist_metadata(
                        include_validation=False,
                        include_search_index=True,
                        sort_by="title",
                        force_refresh=False
                    )
                    if metadata:
                        modlists_with_mods = sum(1 for m in metadata.modlists if hasattr(m, 'mods') and m.mods)
                        if modlists_with_mods > 0:
                            _debug_print(f"Gallery cache ready ({modlists_with_mods} modlists with mods)")
                        else:
                            _debug_print("Gallery cache updated")
                    else:
                        _debug_print("Failed to load gallery cache")
                except Exception as e:
                    _debug_print(f"Gallery cache preload error: {str(e)}")

        self._gallery_cache_preload_thread = GalleryCachePreloadThread()
        self._gallery_cache_preload_thread.start()
        _debug_print("Started background gallery cache preload")

    def _check_protontricks_on_startup(self):
        try:
            method = self.config_handler.get('component_installation_method', 'winetricks')
            if method != 'system_protontricks':
                _debug_print(f"Skipping protontricks check (current method: {method}).")
                return
            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            if not is_installed:
                print(f"Protontricks not found: {details}")
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                if result == QDialog.Rejected:
                    print("User chose to exit due to missing protontricks")
                    sys.exit(1)
            else:
                _debug_print(f"Protontricks detected: {details}")
        except Exception as e:
            print(f"Error checking protontricks: {e}")

    def _check_for_updates_on_startup(self):
        try:
            _debug_print("Checking for updates on startup...")

            class UpdateCheckThread(QThread):
                update_available = Signal(object)

                def __init__(self, update_service):
                    super().__init__()
                    self.update_service = update_service

                def run(self):
                    update_info = self.update_service.check_for_updates()
                    if update_info:
                        self.update_available.emit(update_info)

            def on_update_available(update_info):
                _debug_print(f"Update available: v{update_info.version}")

                def show_update_dialog():
                    from jackify.frontends.gui.dialogs.update_dialog import UpdateDialog
                    dialog = UpdateDialog(update_info, self.update_service, self)
                    dialog.exec()
                QTimer.singleShot(1000, show_update_dialog)

            self._update_thread = UpdateCheckThread(self.update_service)
            self._update_thread.update_available.connect(on_update_available)
            self._update_thread.start()
        except Exception as e:
            _debug_print(f"Error setting up update check: {e}")
