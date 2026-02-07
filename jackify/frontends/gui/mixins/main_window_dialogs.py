"""
Main window dialogs and cleanup mixin.
Settings, About, open URL, cleanup_processes, closeEvent.
"""

import os
import subprocess

from jackify.frontends.gui.dialogs.settings_dialog import SettingsDialog


class MainWindowDialogsMixin:
    """Mixin for settings/about dialogs, open URL, and cleanup."""

    def open_settings_dialog(self):
        try:
            if self._settings_dialog is not None:
                try:
                    if self._settings_dialog.isVisible():
                        self._settings_dialog.raise_()
                        self._settings_dialog.activateWindow()
                        return
                    else:
                        self._settings_dialog = None
                except RuntimeError:
                    self._settings_dialog = None
            dlg = SettingsDialog(self)
            self._settings_dialog = dlg

            def on_dialog_finished():
                self._settings_dialog = None
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_settings_dialog: {e}")
            import traceback
            traceback.print_exc()
            self._settings_dialog = None

    def open_about_dialog(self):
        try:
            from jackify.frontends.gui.dialogs.about_dialog import AboutDialog
            if self._about_dialog is not None:
                try:
                    if self._about_dialog.isVisible():
                        self._about_dialog.raise_()
                        self._about_dialog.activateWindow()
                        return
                    else:
                        self._about_dialog = None
                except RuntimeError:
                    self._about_dialog = None
            dlg = AboutDialog(self.system_info, self)
            self._about_dialog = dlg

            def on_dialog_finished():
                self._about_dialog = None
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_about_dialog: {e}")
            import traceback
            traceback.print_exc()
            self._about_dialog = None

    def _open_url(self, url: str):
        env = os.environ.copy()
        appimage_vars = [
            'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME',
            'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH',
        ]
        if 'APPIMAGE' in env or 'APPDIR' in env:
            for var in appimage_vars:
                env.pop(var, None)
        subprocess.Popen(
            ['xdg-open', url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def cleanup_processes(self):
        try:
            if hasattr(self, '_update_thread') and self._update_thread is not None:
                if self._update_thread.isRunning():
                    self._update_thread.quit()
                    self._update_thread.wait(2000)
                self._update_thread = None
            if hasattr(self, '_gallery_cache_preload_thread') and self._gallery_cache_preload_thread is not None:
                if self._gallery_cache_preload_thread.isRunning():
                    self._gallery_cache_preload_thread.quit()
                    self._gallery_cache_preload_thread.wait(2000)
                self._gallery_cache_preload_thread = None
            for service in self.gui_services.values():
                if hasattr(service, 'cleanup'):
                    service.cleanup()
            screens = [
                self.modlist_tasks_screen, self.install_modlist_screen,
                self.configure_new_modlist_screen, self.configure_existing_modlist_screen,
            ]
            for screen in screens:
                if hasattr(screen, 'cleanup_processes'):
                    screen.cleanup_processes()
                elif hasattr(screen, 'cleanup'):
                    screen.cleanup()
            try:
                subprocess.run(['pkill', '-f', 'jackify-engine'], timeout=5, capture_output=True)
            except Exception:
                pass
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def closeEvent(self, event):
        self._save_geometry_on_quit()
        self.cleanup_processes()
        event.accept()
