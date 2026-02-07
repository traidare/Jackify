"""Cleanup and replacement logic for shortcut operations (Mixin)."""
from pathlib import Path
from typing import Optional, Tuple
import logging
import os
import vdf
import subprocess

logger = logging.getLogger(__name__)


class AutomatedPrefixShortcutsCleanupMixin:
    """Mixin providing cleanup_old_batch_shortcuts, modify_shortcut_target, replace_existing_shortcut."""

    def cleanup_old_batch_shortcuts(self, shortcut_name: str) -> bool:
        """Remove old batch file shortcuts for this modlist to prevent duplicates."""
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False

            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)

            shortcuts = shortcuts_data.get('shortcuts', {})
            indices_to_remove = []

            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                exe = shortcut.get('Exe', '')

                if (name == shortcut_name and
                        'prefix_creation_' in exe and
                        exe.endswith('.bat')):
                    indices_to_remove.append(str(i))
                    logger.info(f"Marking old batch shortcut for removal: {name} -> {exe}")

            if not indices_to_remove:
                logger.debug(f"No old batch shortcuts found for '{shortcut_name}'")
                return True

            new_shortcuts = {}
            new_index = 0

            for i in range(len(shortcuts)):
                if str(i) not in indices_to_remove:
                    new_shortcuts[str(new_index)] = shortcuts[str(i)]
                    new_index += 1

            shortcuts_data['shortcuts'] = new_shortcuts

            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)

            logger.info(f"Cleaned up {len(indices_to_remove)} old batch shortcuts for '{shortcut_name}'")
            return True

        except Exception as e:
            logger.error(f"Error cleaning up old shortcuts: {e}")
            return False

    def modify_shortcut_target(self, shortcut_name: str, new_exe_path: str, new_start_dir: str) -> bool:
        """Modify an existing shortcut's target and start directory. Preserves launch options."""
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                logger.error("No shortcuts.vdf path found")
                return False

            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)

            if 'shortcuts' not in shortcuts_data:
                logger.error("No shortcuts found in shortcuts.vdf")
                return False

            shortcuts = shortcuts_data['shortcuts']
            shortcut_found = False

            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                if shortcut.get('AppName', '') == shortcut_name:
                    existing_launch_options = shortcut.get('LaunchOptions', '')
                    shortcut['Exe'] = new_exe_path
                    shortcut['StartDir'] = new_start_dir
                    shortcut['LaunchOptions'] = existing_launch_options
                    shortcut_found = True
                    logger.info(f"Modified shortcut '{shortcut_name}' to target: {new_exe_path}")
                    logger.info(f"Preserved launch options: {existing_launch_options}")
                    break

            if not shortcut_found:
                logger.error(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
                return False

            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)

            logger.info(f"Successfully modified shortcut '{shortcut_name}'")
            return True

        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False

    def replace_existing_shortcut(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> Tuple[bool, Optional[int]]:
        """Replace an existing shortcut with a new one using STL, then create via native service."""
        try:
            logger.info(f"Replacing existing shortcut: {shortcut_name}")

            appdir = os.environ.get('APPDIR')
            if appdir:
                stl_path = Path(appdir) / "opt" / "jackify" / "steamtinkerlaunch"
            else:
                project_root = Path(__file__).parent.parent.parent.parent.parent
                stl_path = project_root / "external_repos/steamtinkerlaunch/steamtinkerlaunch"

            if not stl_path.exists():
                logger.error(f"STL not found at: {stl_path}")
                return False, None

            remove_cmd = [str(stl_path), "rnsg", f"--appname={shortcut_name}"]
            env = os.environ.copy()
            env['STL_QUIET'] = '1'

            logger.info(f"Removing existing shortcut: {' '.join(remove_cmd)}")
            result = subprocess.run(remove_cmd, capture_output=True, text=True, timeout=30, env=env)

            if result.returncode != 0:
                logger.warning(f"Failed to remove existing shortcut: {result.stderr}")

            success, app_id = self.create_shortcut_with_native_service(shortcut_name, exe_path, modlist_install_dir)
            return success, app_id

        except Exception as e:
            logger.error(f"Error replacing shortcut: {e}")
            return False, None
