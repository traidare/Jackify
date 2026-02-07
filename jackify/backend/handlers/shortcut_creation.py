"""Shortcut creation methods for ShortcutHandler (Mixin)."""
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ShortcutCreationMixin:
    """Mixin providing shortcut creation methods."""

    def create_shortcut(self, executable_path=None, shortcut_name=None, launch_options="", icon_path="",
                        install_dir=None, download_dir=None):
        """
        Create a new Steam shortcut entry.

        Args:
            executable_path (str): Path to the main executable (e.g., Hoolamike.exe)
            shortcut_name (str): Name for the Steam shortcut
            launch_options (str): Launch options string (optional)
            icon_path (str): Path to the icon for the shortcut (optional)
            install_dir: Optional modlist install path; its mountpoint is added to STEAM_COMPAT_MOUNTS
            download_dir: Optional download path; its mountpoint is added to STEAM_COMPAT_MOUNTS

        Returns:
            tuple: (bool success, Optional[str] app_id) - Success status and the generated AppID, or None if failed.
        """
        self.logger.info(f"Attempting to create shortcut for: {shortcut_name}")
        self.logger.debug(f"[DEBUG] create_shortcut called with executable_path={executable_path}, shortcut_name={shortcut_name}, icon_path={icon_path}")
        self._last_shortcuts_backup = None
        self._safe_shortcuts_backup = None
        self._shortcuts_file = None

        if executable_path:
            exe_dir = os.path.dirname(executable_path)
            steam_icons_path = Path(exe_dir) / "Steam Icons"
            steamicons_path = Path(exe_dir) / "SteamIcons"
            if steam_icons_path.is_dir() and not steamicons_path.is_dir():
                try:
                    steam_icons_path.rename(steamicons_path)
                    self.logger.info(f"Renamed 'Steam Icons' to 'SteamIcons' in {exe_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to rename 'Steam Icons' to 'SteamIcons': {e}")

        if not executable_path or not os.path.exists(executable_path):
            self.logger.error(f"Invalid or non-existent executable path provided: {executable_path}")
            return False, None
        else:
            start_dir = os.path.dirname(executable_path)

        if not shortcut_name:
            self.logger.error("Shortcut name not provided.")
            return False, None

        try:
            shortcuts_file = self.shortcuts_path
            self._shortcuts_file = shortcuts_file

            if not shortcuts_file or not os.path.isfile(shortcuts_file):
                self.logger.error("shortcuts.vdf path not found or is invalid.")
                self.logger.error("Could not find the Steam shortcuts file (shortcuts.vdf).")
                config_dir = os.path.dirname(shortcuts_file) if shortcuts_file else None
                if config_dir and os.path.isdir(config_dir):
                    self.logger.warning(f"Attempting to create blank shortcuts.vdf at {shortcuts_file}")
                    with open(shortcuts_file, 'wb') as f:
                        f.write(b'\x00shortcuts\x00\x08\x08')
                    self.logger.info("Created blank shortcuts.vdf.")
                else:
                    self.logger.error("Cannot create shortcuts.vdf as parent directory doesn't exist.")
                    return False, None
            else:
                config_dir = os.path.dirname(shortcuts_file)
                if not os.path.isdir(config_dir):
                    self.logger.error(f"Config directory not found: {config_dir}")
                    self.logger.error(f"Steam config directory not found: {config_dir}")
                    return False, None

                backup_dir = os.path.join(config_dir, "backups")
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join(backup_dir, f"shortcuts_{timestamp}.bak")

                if os.path.exists(shortcuts_file):
                    import shutil
                    shutil.copy2(shortcuts_file, backup_path)
                    self._last_shortcuts_backup = backup_path
                    self.logger.info(f"Created backup at {backup_path}")
                else:
                    self.logger.warning(f"shortcuts.vdf does not exist at {shortcuts_file}, cannot create backup. Proceeding with potentially new file.")

            compat_mounts_str = ""
            try:
                self.logger.info("Determining necessary STEAM_COMPAT_MOUNTS...")
                mount_paths = self.path_handler.get_steam_compat_mount_paths(
                    install_dir=install_dir, download_dir=download_dir
                )
                if mount_paths:
                    compat_mounts_str = f'STEAM_COMPAT_MOUNTS="{":".join(mount_paths)}"'
                    self.logger.info(f"Generated STEAM_COMPAT_MOUNTS string: {compat_mounts_str}")
                else:
                    self.logger.info("No additional libraries or mountpoints needed for STEAM_COMPAT_MOUNTS.")

            except Exception as e:
                self.logger.error(f"Error determining STEAM_COMPAT_MOUNTS: {e}", exc_info=True)

            final_launch_options = launch_options
            if compat_mounts_str:
                 if final_launch_options:
                     final_launch_options = f"{compat_mounts_str} {final_launch_options}"
                 else:
                     final_launch_options = compat_mounts_str

            if not final_launch_options.strip().endswith("%command%"):
                if final_launch_options:
                    final_launch_options = f"{final_launch_options} %command%"
                else:
                    final_launch_options = "%command%"

            self.logger.debug(f"Final launch options string: {final_launch_options}")

            success, app_id = self._add_steam_shortcut_safely(
                shortcuts_file,
                shortcut_name,
                executable_path,
                start_dir,
                icon_path=icon_path,
                launch_options=final_launch_options,
                tags=["Jackify", "Tool"]
            )

            if not success:
                self.logger.error("Failed to add shortcut entry safely.")
                return False, None

            self.logger.info(f"Shortcut created successfully for {shortcut_name} with AppID {app_id}")
            return True, app_id

        except Exception as e:
            self.logger.error(f"Error creating shortcut: {e}", exc_info=True)
            print(f"An error occurred while creating the shortcut: {e}")
            return False, None

    def _is_steam_deck(self):
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        return True
            import subprocess
            user_services = subprocess.run(['systemctl', '--user', 'list-units', '--type=service', '--no-pager'], capture_output=True, text=True)
            if 'app-steam@autostart.service' in user_services.stdout:
                return True
        except Exception as e:
            self.logger.warning(f"Error detecting Steam Deck: {e}")
        return False
