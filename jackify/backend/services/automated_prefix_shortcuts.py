"""Shortcut operation methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import logging
import os
import time
import vdf
import subprocess

from .automated_prefix_shortcuts_cleanup import AutomatedPrefixShortcutsCleanupMixin

logger = logging.getLogger(__name__)


def debug_print(message):
    """Log debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        logger.debug(message)


class ShortcutOperationsMixin(AutomatedPrefixShortcutsCleanupMixin):
    """Mixin providing shortcut operation methods for AutomatedPrefixService."""

    def create_shortcut_with_native_service(self, shortcut_name: str, exe_path: str, 
                                           modlist_install_dir: str, custom_launch_options: str = None,
                                           download_dir=None) -> Tuple[bool, Optional[int]]:
        """
        Create a Steam shortcut using the native Steam service (no STL).
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the executable  
            modlist_install_dir: Directory where the modlist is installed
            custom_launch_options: Pre-generated launch options (overrides default generation)
            download_dir: Optional download path; its mountpoint is added to STEAM_COMPAT_MOUNTS
            
        Returns:
            (success, unsigned_app_id)
        """
        logger.info(f"Creating shortcut with native service: {shortcut_name}")
        
        try:
            from ..services.native_steam_service import NativeSteamService
            
            # Initialize native Steam service
            steam_service = NativeSteamService()
            
            # Use custom launch options if provided, otherwise generate default
            if custom_launch_options:
                launch_options = custom_launch_options
                logger.info(f"Using pre-generated launch options: {launch_options}")
            else:
                # Generate STEAM_COMPAT_MOUNTS including install and download mountpoints
                launch_options = "%command%"
                try:
                    from ..handlers.path_handler import PathHandler
                    path_handler = PathHandler()
                    mount_paths = path_handler.get_steam_compat_mount_paths(
                        install_dir=modlist_install_dir, download_dir=download_dir
                    )
                    if mount_paths:
                        launch_options = f'STEAM_COMPAT_MOUNTS="{":".join(mount_paths)}" %command%'
                        logger.info(f"Generated launch options with mounts: {launch_options}")
                except Exception as e:
                    logger.warning(f"Could not generate STEAM_COMPAT_MOUNTS, using default: {e}")
                    launch_options = "%command%"
            
            # Get user's preferred Proton version (with Lorerim-specific override)
            proton_version = self._get_user_proton_version(shortcut_name)

            # Create shortcut with Proton using native service
            success, app_id = steam_service.create_shortcut_with_proton(
                app_name=shortcut_name,
                exe_path=exe_path,
                start_dir=modlist_install_dir,
                launch_options=launch_options,
                tags=["Jackify"],
                proton_version=proton_version
            )
            
            if success and app_id:
                logger.info(f" Native Steam service created shortcut successfully with AppID: {app_id}")
                return True, app_id
            else:
                logger.error("Native Steam service failed to create shortcut")
                return False, None
                
        except Exception as e:
            logger.error(f"Error creating shortcut with native service: {e}")
            return False, None

    def verify_shortcut_created(self, shortcut_name: str) -> Optional[int]:
        """
        Verify the shortcut was created and get its AppID.
        
        Args:
            shortcut_name: Name of the shortcut to look for
            
        Returns:
            AppID if found, None otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return None
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Look for our shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name in name:
                    appid = shortcut.get('appid')
                    exe_path = shortcut.get('Exe', '').strip('"')
                    
                    logger.info(f"Found shortcut: {name}")
                    logger.info(f"  AppID: {appid}")
                    logger.info(f"  Exe: {exe_path}")
                    logger.info(f"  CompatTool: {shortcut.get('CompatTool', 'NOT_SET')}")
                    
                    return appid
            
            logger.error(f"Shortcut '{shortcut_name}' not found")
            return None
            
        except Exception as e:
            logger.error(f"Error reading shortcuts: {e}")
            return None

    def create_shortcut_directly(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> bool:
        """
        Create a Steam shortcut directly by modifying shortcuts.vdf.
        This is a fallback when STL fails.
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] create_shortcut_directly called for '{shortcut_name}' - this is the fallback method")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the next available index
            next_index = str(len(shortcuts))
            
            # Calculate AppID for the new shortcut (negative for non-Steam shortcuts)
            import hashlib
            app_name_bytes = shortcut_name.encode('utf-8')
            exe_bytes = exe_path.encode('utf-8')
            combined = app_name_bytes + exe_bytes
            hash_value = int(hashlib.md5(combined).hexdigest()[:8], 16)
            appid = -(hash_value & 0x7FFFFFFF)  # Make it negative and within 32-bit range
            
            # Create new shortcut entry
            new_shortcut = {
                'AppName': shortcut_name,
                'Exe': f'"{exe_path}"',
                'StartDir': f'"{modlist_install_dir}"',
                'appid': appid,
                'icon': '',
                'ShortcutPath': '',
                'LaunchOptions': '',
                'IsHidden': 0,
                'AllowDesktopConfig': 1,
                'AllowOverlay': 1,
                'openvr': 0,
                'Devkit': 0,
                'DevkitGameID': '',
                'LastPlayTime': 0,
                'FlatpakAppID': '',
                'tags': {},
                'CompatTool': 'proton_experimental',  # Set Proton Experimental
                'IsInstalled': 1  # Make it appear in "Locally Installed" filter
            }
            
            # Add the new shortcut
            shortcuts[next_index] = new_shortcut
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created shortcut directly: {shortcut_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating shortcut directly: {e}")
            return False

    def create_shortcut_directly_with_proton(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> bool:
        """
        Create a Steam shortcut with temporary batch file for invisible prefix creation.
        This uses the CRC32-based AppID calculation for predictable results.
        
        Args:
            shortcut_name: Name for the shortcut
            exe_path: Path to the final ModOrganizer.exe executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] create_shortcut_directly_with_proton called for '{shortcut_name}' - using temporary batch file approach")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Calculate predictable AppID using CRC32 (based on FINAL exe_path)
            from zlib import crc32
            combined_string = exe_path + shortcut_name
            crc = crc32(combined_string.encode('utf-8'))
            appid = -(crc & 0x7FFFFFFF)  # Make it negative and within 32-bit range (like other shortcuts)
            
            debug_print(f"[DEBUG] Calculated AppID: {appid} from '{combined_string}'")
            
            # Create temporary batch file for invisible prefix creation
            batch_content = """@echo off
echo Creating Proton prefix...
timeout /t 3 /nobreak >nul
echo Prefix creation complete.
"""
            from jackify.shared.paths import get_jackify_data_dir
            batch_path = get_jackify_data_dir() / "temp_prefix_creation.bat"
            batch_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            debug_print(f"[DEBUG] Created temporary batch file: {batch_path}")
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Check if shortcut already exists (idempotent)
            found = False
            new_shortcuts_list = []
            shortcuts_list = list(shortcuts.values())
            
            for shortcut in shortcuts_list:
                if shortcut.get('AppName') == shortcut_name:
                    debug_print(f"[DEBUG] Updating existing shortcut for '{shortcut_name}'")
                    # Update existing shortcut with temporary batch file
                    shortcut.update({
                        'Exe': f'"{batch_path}"',  # Point to temporary batch file
                        'StartDir': f'"{batch_path.parent}"',  # Batch file directory
                        'appid': appid,
                        'LaunchOptions': '',  # Empty like working shortcuts
                        'tags': {},  # Empty tags like working shortcuts
                        'CompatTool': 'proton_experimental'  # Set Proton version directly in shortcut
                    })
                    new_shortcuts_list.append(shortcut)
                    found = True
                else:
                    new_shortcuts_list.append(shortcut)
            
            if not found:
                debug_print(f"[DEBUG] Creating new shortcut for '{shortcut_name}'")
                # Create new shortcut entry pointing to temporary batch file
                new_shortcut = {
                    'AppName': shortcut_name,
                    'Exe': f'"{batch_path}"',  # Point to temporary batch file
                    'StartDir': f'"{batch_path.parent}"',  # Batch file directory
                    'appid': appid,
                    'icon': '',
                    'ShortcutPath': '',
                    'LaunchOptions': '',  # Empty like working shortcuts
                    'IsHidden': 0,
                    'AllowDesktopConfig': 1,
                    'AllowOverlay': 1,
                    'OpenVR': 0,
                    'Devkit': 0,
                    'DevkitGameID': '',
                    'LastPlayTime': 0,
                    'FlatpakAppID': '',
                    'tags': {},  # Empty tags like working shortcuts
                    'sortas': '',
                    'CompatTool': 'proton_experimental'  # Set Proton version directly in shortcut
                }
                new_shortcuts_list.append(new_shortcut)
            
            # Rebuild shortcuts dict with new order
            shortcuts_data['shortcuts'] = {str(i): s for i, s in enumerate(new_shortcuts_list)}
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created/updated shortcut with temporary batch file: {shortcut_name} with AppID {appid}")
            debug_print(f"[DEBUG] Shortcut created/updated with temporary batch file, AppID {appid}")
            
            # Set Proton version in config.vdf BEFORE creating shortcut
            if self.set_proton_version_for_shortcut(appid, 'proton_experimental'):
                logger.info(f"Set Proton Experimental for shortcut {shortcut_name}")
                return True
            else:
                logger.warning(f"Failed to set Proton version for shortcut {shortcut_name}")
                return False
            
        except Exception as e:
            logger.error(f"Error creating shortcut with temporary batch file: {e}")
            return False

    def replace_shortcut_with_final_exe(self, shortcut_name: str, final_exe_path: str, modlist_install_dir: str) -> bool:
        """
        Replace the temporary batch file shortcut with the final ModOrganizer.exe.
        This should be called after the prefix has been created.
        
        Args:
            shortcut_name: Name of the shortcut to update
            final_exe_path: Path to the final ModOrganizer.exe executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            debug_print(f"[DEBUG] replace_shortcut_with_final_exe called for '{shortcut_name}'")
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                debug_print("[DEBUG] No shortcuts path found")
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find and update the shortcut
            found = False
            new_shortcuts_list = []
            shortcuts_list = list(shortcuts.values())
            
            for shortcut in shortcuts_list:
                if shortcut.get('AppName') == shortcut_name:
                    debug_print(f"[DEBUG] Replacing temporary batch file with final exe for '{shortcut_name}'")
                    # Update shortcut to point to final ModOrganizer.exe
                    shortcut.update({
                        'Exe': f'"{final_exe_path}"',  # Point to final ModOrganizer.exe
                        'StartDir': modlist_install_dir,  # ModOrganizer directory
                        'LaunchOptions': '',  # Empty like working shortcuts
                        'tags': {},  # Empty tags like working shortcuts
                        # Keep existing appid and CompatibilityTool
                    })
                    new_shortcuts_list.append(shortcut)
                    found = True
                else:
                    new_shortcuts_list.append(shortcut)
            
            if not found:
                logger.error(f"Shortcut '{shortcut_name}' not found for replacement")
                return False
            
            # Rebuild shortcuts dict with new order
            shortcuts_data['shortcuts'] = {str(i): s for i, s in enumerate(new_shortcuts_list)}
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Replaced shortcut with final exe: {shortcut_name}")
            debug_print(f"[DEBUG] Shortcut replaced with final ModOrganizer.exe")
            
            return True
            
        except Exception as e:
            logger.error(f"Error replacing shortcut with final exe: {e}")
            return False

    def modify_shortcut_to_final_exe(self, shortcut_name: str, final_exe_path: str, 
                                   final_start_dir: str) -> bool:
        """
        Update the existing batch file shortcut to point to the final executable.
        This preserves the AppID and prefix association while changing the target.
        
        Args:
            shortcut_name: Name of the shortcut to modify
            final_exe_path: Path to the final executable (e.g., ModOrganizer.exe)
            final_start_dir: Start directory for the executable
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            # Read current shortcuts
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find the batch file shortcut that created the prefix
            logger.info(f"Looking for batch file shortcut '{shortcut_name}' among {len(shortcuts)} shortcuts...")
            target_shortcut = None
            target_index = None
            
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                exe = shortcut.get('Exe', '')
                
                # Find the specific shortcut that points to our batch file (handle quoted paths)
                if (name == shortcut_name and 
                    exe and 'prefix_creation_' in exe and (exe.endswith('.bat') or exe.endswith('.bat"'))):
                    target_shortcut = shortcut
                    target_index = str(i)
                    logger.info(f"Found batch file shortcut '{shortcut_name}' at index {i}")
                    logger.info(f"  Current Exe: {exe}")
                    logger.info(f"  Current StartDir: {shortcut.get('StartDir', '')}")
                    logger.info(f"  Current CompatTool: {shortcut.get('CompatTool', 'NOT_SET')}")
                    logger.info(f"  AppID: {shortcut.get('appid', 'NOT_SET')}")
                    break
            
            if target_shortcut is None:
                logger.error(f"No batch file shortcut found with name '{shortcut_name}'")
                # Debug: show all available shortcuts
                logger.debug("Available shortcuts:")
                for i in range(len(shortcuts)):
                    shortcut = shortcuts[str(i)]
                    name = shortcut.get('AppName', '')
                    exe = shortcut.get('Exe', '')
                    logger.debug(f"  [{i}] {name} -> {exe}")
                return False
            
            # Update the existing shortcut IN-PLACE (preserves AppID and all other fields)
            logger.info(f"Updating shortcut at index {target_index} IN-PLACE...")
            
            # Only change Exe and StartDir - preserve everything else including AppID
            old_exe = target_shortcut.get('Exe', '')
            old_start_dir = target_shortcut.get('StartDir', '')
            
            target_shortcut['Exe'] = f'"{final_exe_path}"'
            target_shortcut['StartDir'] = f'"{final_start_dir}"'
            
            # Ensure CompatTool is set (STL should have set this, but make sure)
            if not target_shortcut.get('CompatTool', '').strip():
                target_shortcut['CompatTool'] = 'proton_experimental'
                logger.info("Set CompatTool to proton_experimental (was not set)")
            
            logger.info(f" Updated shortcut '{shortcut_name}' at index {target_index}:")
            logger.info(f"  Exe: {old_exe} → {target_shortcut['Exe']}")
            logger.info(f"  StartDir: {old_start_dir} → {target_shortcut['StartDir']}")
            logger.info(f"  AppID: {target_shortcut.get('appid', 'NOT_SET')} (preserved)")
            logger.info(f"  CompatTool: {target_shortcut.get('CompatTool', 'NOT_SET')} (preserved)")
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(" Shortcut updated successfully - no duplicates created")
            return True
            
        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False

    def verify_final_shortcut(self, shortcut_name: str, expected_exe_path: str) -> bool:
        """
        Verify the shortcut now points to the final executable.
        
        Args:
            shortcut_name: Name of the shortcut to verify
            expected_exe_path: Expected executable path
            
        Returns:
            True if shortcut is correct, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return False
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Find our shortcut
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name in name:
                    exe_path = shortcut.get('Exe', '')
                    start_dir = shortcut.get('StartDir', '')
                    
                    logger.info(f"Final shortcut configuration:")
                    logger.info(f"  Name: {name}")
                    logger.info(f"  Exe: {exe_path}")
                    logger.info(f"  StartDir: {start_dir}")
                    
                    # Verify it points to the final executable
                    if expected_exe_path in exe_path:
                        logger.info("Shortcut correctly points to final executable")
                        return True
                    else:
                        logger.error("Shortcut does not point to final executable")
                        return False
            
            logger.error(f"Shortcut '{shortcut_name}' not found")
            return False
            
        except Exception as e:
            logger.error(f"Error reading shortcuts: {e}")
            return False

