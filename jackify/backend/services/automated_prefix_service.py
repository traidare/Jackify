#!/usr/bin/env python3
"""
Automated Prefix Creation Service

This service implements the automated Proton prefix creation workflow
that eliminates the need for manual steps in Jackify.
"""
import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, Union, List, Dict
import vdf

logger = logging.getLogger(__name__)

def debug_print(message):
    """Log debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        logger.debug(message)

from .automated_prefix_shortcuts import ShortcutOperationsMixin
from .automated_prefix_proton import ProtonOperationsMixin
from .automated_prefix_creation import PrefixCreationMixin
from .automated_prefix_stl import STLAlgorithmMixin
from .automated_prefix_workflow import WorkflowMixin
from .automated_prefix_registry import RegistryOperationsMixin
from .automated_prefix_game_utils import GameUtilsMixin

class AutomatedPrefixService(ShortcutOperationsMixin, ProtonOperationsMixin, PrefixCreationMixin, STLAlgorithmMixin, WorkflowMixin, RegistryOperationsMixin, GameUtilsMixin):
    """
    Service for automated Proton prefix creation using temporary batch files
    and direct Proton wrapper integration.
    """
    
    def __init__(self, system_info=None):
        from jackify.shared.paths import get_jackify_data_dir
        self.scripts_dir = get_jackify_data_dir() / "scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.system_info = system_info
        # Use shared timing for consistency across services
    
    def _get_progress_timestamp(self):
        """Get consistent progress timestamp"""
        from jackify.shared.timing import get_timestamp
        return get_timestamp()

    def _get_shortcuts_path(self) -> Optional[Path]:
        """Get the path to shortcuts.vdf using proper Steam path detection."""
        try:
            from ..handlers.path_handler import PathHandler
            
            # Use find_steam_config_vdf to get the Steam config path, then derive the Steam root
            config_vdf_path = PathHandler.find_steam_config_vdf()
            if not config_vdf_path:
                logger.error("Could not find Steam config.vdf")
                return None
            
            # Get Steam root directory (config.vdf is in steam/config/config.vdf)
            steam_path = config_vdf_path.parent.parent  # steam/config/config.vdf -> steam
            logger.debug(f"Detected Steam path: {steam_path}")
            
            # Find the userdata directory
            userdata_dir = steam_path / "userdata"
            if not userdata_dir.exists():
                logger.error(f"Steam userdata directory not found: {userdata_dir}")
                return None
            
            # Use NativeSteamService for proper user detection
            from ..services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()

            if not steam_service.find_steam_user():
                logger.error("Could not detect Steam user for shortcuts")
                return None

            shortcuts_path = steam_service.get_shortcuts_vdf_path()
            if not shortcuts_path:
                logger.error("Could not get shortcuts.vdf path from Steam service")
                return None
            
            logger.debug(f"Looking for shortcuts.vdf at: {shortcuts_path}")
            if not shortcuts_path.exists():
                logger.error(f"shortcuts.vdf not found: {shortcuts_path}")
                return None
                
            logger.info(f"Found shortcuts.vdf at: {shortcuts_path}")
            return shortcuts_path
            
        except Exception as e:
            logger.error(f"Error getting shortcuts path: {e}")
            import traceback
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return None
        
    def create_temp_batch_file(self, shortcut_name: str) -> Optional[str]:
        """
        Create a temporary batch file for silent prefix creation.
        
        Args:
            shortcut_name: Name of the shortcut (used for unique filename)
            
        Returns:
            Path to the created batch file, or None if failed
        """
        try:
            # Create a unique batch file name
            timestamp = int(time.time())
            batch_filename = f"prefix_creation_{shortcut_name}_{timestamp}.bat"
            batch_path = self.scripts_dir / batch_filename
            
            # Create the batch file content
            batch_content = f"""@echo off
echo Creating prefix for {shortcut_name}
REM This will trigger Proton to create a prefix
echo Prefix creation in progress...
REM Wait a bit for Proton to initialize
timeout /t 5 /nobreak >nul
REM Try to run a simple command to ensure prefix is created
echo Prefix creation completed
exit"""
            
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            # Make it executable
            os.chmod(str(batch_path), 0o755)
            
            logger.info(f"Created temporary batch file: {batch_path}")
            return str(batch_path)
            
        except Exception as e:
            logger.error(f"Failed to create batch file: {e}")
            return None

    def restart_steam(self) -> bool:
        """
        Restart Steam using the robust service method.

        Returns:
            True if successful, False otherwise
        """
        try:
            from .steam_restart_service import robust_steam_restart
            # Use system_info if available (backward compatibility)
            system_info = getattr(self, 'system_info', None)
            return robust_steam_restart(progress_callback=None, timeout=60, system_info=system_info)
        except Exception as e:
            logger.error(f"Error restarting Steam: {e}")
            return False

    def _get_config_path(self) -> Optional[Path]:
        """Get the path to config.vdf"""
        try:
            from ..handlers.path_handler import PathHandler
            
            # Use find_steam_config_vdf to get the Steam config path
            config_vdf_path = PathHandler.find_steam_config_vdf()
            if not config_vdf_path:
                logger.error("Could not find Steam config.vdf")
                return None
            
            return config_vdf_path
            
        except Exception as e:
            logger.error(f"Error getting config path: {e}")
            return None


    def kill_running_processes(self) -> bool:
        """
        Kill any running processes that might interfere with prefix creation.
        This follows the same pattern as the working test script.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            import psutil
            
            logger.info("Looking for processes to kill...")
            
            # Look for ModOrganizer.exe process or any wine processes
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    proc_info = proc.info
                    name = proc_info.get('name', '')
                    cmdline = proc_info.get('cmdline', [])
                    
                    # Check for ModOrganizer.exe or wine processes
                    if ('ModOrganizer.exe' in name or 
                        'wine' in name.lower() or
                        any('ModOrganizer.exe' in str(arg) for arg in (cmdline or [])) or
                        any('wine' in str(arg).lower() for arg in (cmdline or []))):
                        
                        logger.info(f"Found process to kill: {name} (PID {proc_info['pid']})")
                        proc.terminate()
                        proc.wait(timeout=5)
                        logger.info(f" Process killed successfully")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
            
            logger.info("No more processes to kill")
            return True
            
        except Exception as e:
            logger.error(f"Error killing processes: {e}")
            return False

    def kill_mo_processes(self) -> int:
        """
        Kill all ModOrganizer.exe processes.
        
        Returns:
            Number of processes killed
        """
        try:
            import psutil
            killed_count = 0
            
            logger.info("Searching for ModOrganizer processes...")
            
            for proc in psutil.process_iter():
                try:
                    proc_info = proc.as_dict(attrs=['pid', 'name', 'cmdline'])
                    name = proc_info.get('name', '').lower()
                    cmdline = proc_info.get('cmdline') or []
                    
                    # Check process name and command line
                    is_mo_process = (
                        'modorganizer' in name or
                        'mo2' in name or
                        any('modorganizer' in str(arg).lower() for arg in cmdline) or
                        any('ModOrganizer.exe' in str(arg) for arg in cmdline)
                    )
                    
                    if is_mo_process:
                        pid = proc_info['pid']
                        logger.info(f"Found ModOrganizer process: PID {pid}, name='{name}', cmdline={cmdline}")
                        
                        # Force kill with SIGTERM first, then SIGKILL if needed
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                            logger.info(f" Process {pid} terminated gracefully")
                        except psutil.TimeoutExpired:
                            logger.info(f"Process {pid} didn't terminate, force killing...")
                            proc.kill()
                            proc.wait(timeout=2)
                            logger.info(f" Process {pid} force killed")
                        
                        killed_count += 1
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as e:
                    logger.debug(f"Error checking process: {e}")
                    continue
            
            if killed_count > 0:
                logger.info(f" Killed {killed_count} ModOrganizer processes")
            else:
                logger.warning("No ModOrganizer processes found to kill")
                
            return killed_count
            
        except Exception as e:
            logger.error(f"Error killing ModOrganizer processes: {e}")
            return 0

    @staticmethod
    def get_ttw_installer_path() -> Optional[Path]:
        """Get path to TTW_Linux_Installer if available"""
        try:
            from jackify.shared.paths import get_jackify_data_dir
            ttw_path = get_jackify_data_dir() / "TTW_Linux_Installer" / "ttw_linux_gui"
            if ttw_path.exists():
                return ttw_path
        except Exception:
            pass
        return None

    def modify_shortcut_to_batch_file(self, shortcut_name: str, new_exe_path: str, new_start_dir: str) -> bool:
        """
        Modify an existing shortcut's target and start directory.
        
        This is used in the workflow to:
        1. Change the shortcut target to a batch file (to create prefix)
        2. Change it back to ModOrganizer.exe (after prefix creation)
        
        Args:
            shortcut_name: The name of the shortcut to modify
            new_exe_path: The new executable path
            new_start_dir: The new start directory
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                logger.error("No shortcuts.vdf path found")
                return False
            
            # Read the current shortcuts.vdf
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            if 'shortcuts' not in shortcuts_data:
                logger.error("No shortcuts found in shortcuts.vdf")
                return False
            
            shortcuts = shortcuts_data['shortcuts']
            shortcut_found = False
            
            # Find the shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                if shortcut.get('AppName', '') == shortcut_name:
                    # Update the shortcut
                    shortcut['Exe'] = new_exe_path
                    shortcut['StartDir'] = new_start_dir
                    shortcut_found = True
                    logger.info(f"Modified shortcut '{shortcut_name}' to target: {new_exe_path}")
                    break
            
            if not shortcut_found:
                logger.error(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
                return False
            
            # Write the updated shortcuts.vdf back
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Successfully modified shortcut '{shortcut_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error modifying shortcut: {e}")
            return False

    def _get_localconfig_path(self) -> str:
        """
        Get the path to localconfig.vdf file.
        
        Returns:
            Path to localconfig.vdf or None if not found
        """
        # Use NativeSteamService for proper user detection
        try:
            from ..services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()

            if steam_service.find_steam_user():
                localconfig_path = steam_service.user_config_path / "localconfig.vdf"
                if localconfig_path.exists():
                    return str(localconfig_path)
        except Exception as e:
            logger.error(f"Error using Steam service for localconfig.vdf detection: {e}")

        # Fallback to manual detection
        steam_userdata_path = Path.home() / ".steam" / "steam" / "userdata"
        if steam_userdata_path.exists():
            user_dirs = [d for d in steam_userdata_path.iterdir() if d.is_dir() and d.name.isdigit() and d.name != "0"]
            if user_dirs:
                # Use most recently modified directory as fallback
                try:
                    most_recent = max(user_dirs, key=lambda d: d.stat().st_mtime)
                    localconfig_path = most_recent / "config" / "localconfig.vdf"
                    if localconfig_path.exists():
                        return str(localconfig_path)
                except Exception:
                    pass
        
        logger.error("Could not find localconfig.vdf")
        return None

    def get_prefix_path(self, appid: int) -> Optional[Path]:
        """
        Get the path to the Proton prefix for the given AppID.
        Uses same Flatpak detection as create_prefix_with_proton_wrapper.

        Args:
            appid: The AppID (unsigned, positive number)

        Returns:
            Path to the prefix directory, or None if not found
        """
        from ..handlers.path_handler import PathHandler
        path_handler = PathHandler()
        all_libraries = path_handler.get_all_steam_library_paths()

        # Check if Flatpak Steam
        is_flatpak_steam = any('.var/app/com.valvesoftware.Steam' in str(lib) for lib in all_libraries)

        if is_flatpak_steam and all_libraries:
            # Flatpak Steam: use first library root
            library_root = all_libraries[0]
            compatdata_dir = library_root / "steamapps/compatdata"
        else:
            # Native Steam
            compatdata_dir = Path.home() / ".steam/steam/steamapps/compatdata"

        # Ensure we use the absolute value (unsigned AppID)
        prefix_dir = compatdata_dir / str(abs(appid))

        if prefix_dir.exists():
            return prefix_dir
        else:
            return None

