#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks Handler Module
Handles detection and operation of Protontricks
"""

import os
import re
import subprocess
from pathlib import Path
import shutil
import logging
from typing import Dict, Optional, List
import sys

# Initialize logger
logger = logging.getLogger(__name__)


class ProtontricksHandler:
    """
    Handles operations related to Protontricks detection and usage

    This handler now supports native Steam operations as a fallback/replacement
    for protontricks functionality.
    """

    def __init__(self, steamdeck: bool, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.which_protontricks = None  # 'flatpak', 'native', or 'bundled'
        self.flatpak_install_type = None  # 'user' or 'system' (for flatpak installations)
        self.protontricks_version = None
        self.protontricks_path = None
        self.steamdeck = steamdeck # Store steamdeck status
        self._native_steam_service = None
        self.use_native_operations = True  # Enable native Steam operations by default

    def _get_steam_dir_from_libraryfolders(self) -> Optional[Path]:
        """
        Determine the Steam installation directory from libraryfolders.vdf location.
        This is the source of truth - we read libraryfolders.vdf to find where Steam is actually installed.
        
        Returns:
            Path to Steam installation directory (the one with config/, steamapps/, etc.) or None
        """
        from ..handlers.path_handler import PathHandler
        
        # Check all possible libraryfolders.vdf locations
        vdf_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".steam/root/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf",  # Flatpak
            Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/config/libraryfolders.vdf",  # Flatpak alternative
        ]
        
        for vdf_path in vdf_paths:
            if vdf_path.is_file():
                # The Steam installation directory is the parent of the config directory
                steam_dir = vdf_path.parent.parent
                # Verify it has steamapps directory (required by protontricks)
                if (steam_dir / "steamapps").exists():
                    logger.debug(f"Determined STEAM_DIR from libraryfolders.vdf: {steam_dir}")
                    return steam_dir
        
        # Fallback: try to get from library paths
        library_paths = PathHandler.get_all_steam_library_paths()
        if library_paths:
            # For Flatpak Steam, library path is .local/share/Steam, but Steam installation might be data/Steam
            first_lib = library_paths[0]
            if '.var/app/com.valvesoftware.Steam' in str(first_lib):
                # Check if data/Steam exists (main Flatpak Steam installation)
                data_steam = Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam"
                if (data_steam / "steamapps").exists():
                    logger.debug(f"Determined STEAM_DIR from Flatpak data path: {data_steam}")
                    return data_steam
                # Otherwise use the library path itself
                if (first_lib / "steamapps").exists():
                    logger.debug(f"Determined STEAM_DIR from Flatpak library path: {first_lib}")
                    return first_lib
            else:
                # Native Steam - library path should be the Steam installation
                if (first_lib / "steamapps").exists():
                    logger.debug(f"Determined STEAM_DIR from native library path: {first_lib}")
                    return first_lib
        
        logger.warning("Could not determine STEAM_DIR from libraryfolders.vdf")
        return None
    
    def _get_bundled_winetricks_path(self) -> Optional[Path]:
        """
        Get the path to the bundled winetricks script following AppImage best practices.
        Same logic as WinetricksHandler._get_bundled_winetricks_path()
        """
        possible_paths = []

        # AppImage environment - use APPDIR (standard AppImage best practice)
        if os.environ.get('APPDIR'):
            appdir_path = Path(os.environ['APPDIR']) / 'opt' / 'jackify' / 'tools' / 'winetricks'
            possible_paths.append(appdir_path)

        # Development environment - relative to module location
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / 'winetricks'
        possible_paths.append(dev_path)

        # Try each path until we find one that works
        for path in possible_paths:
            if path.exists() and os.access(path, os.X_OK):
                logger.debug(f"Found bundled winetricks at: {path}")
                return path

        logger.warning(f"Bundled winetricks not found. Tried paths: {possible_paths}")
        return None
    
    def _get_bundled_cabextract_path(self) -> Optional[Path]:
        """
        Get the path to the bundled cabextract binary following AppImage best practices.
        Same logic as WinetricksHandler._get_bundled_cabextract()
        """
        possible_paths = []

        # AppImage environment - use APPDIR (standard AppImage best practice)
        if os.environ.get('APPDIR'):
            appdir_path = Path(os.environ['APPDIR']) / 'opt' / 'jackify' / 'tools' / 'cabextract'
            possible_paths.append(appdir_path)

        # Development environment - relative to module location
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / 'cabextract'
        possible_paths.append(dev_path)

        # Try each path until we find one that works
        for path in possible_paths:
            if path.exists() and os.access(path, os.X_OK):
                logger.debug(f"Found bundled cabextract at: {path}")
                return path

        logger.warning(f"Bundled cabextract not found. Tried paths: {possible_paths}")
        return None

    def _get_clean_subprocess_env(self):
        """
        Create a clean environment for subprocess calls by removing bundle-specific
        environment variables that can interfere with external program execution.
        
        Uses the centralized get_clean_subprocess_env() to ensure AppImage variables
        are removed to prevent subprocess spawning issues.

        Returns:
            dict: Cleaned environment dictionary
        """
        # Use centralized function that removes AppImage variables
        from .subprocess_utils import get_clean_subprocess_env
        env = get_clean_subprocess_env()

        # Clean library path variables that frozen bundles modify (Linux/Unix)
        if 'LD_LIBRARY_PATH_ORIG' in env:
            # Restore original LD_LIBRARY_PATH if it was backed up by the bundler
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            # Remove bundle-modified LD_LIBRARY_PATH
            env.pop('LD_LIBRARY_PATH', None)
        
        # Clean macOS library path (if present)
        if 'DYLD_LIBRARY_PATH' in env and hasattr(sys, '_MEIPASS'):
            dyld_entries = env['DYLD_LIBRARY_PATH'].split(os.pathsep)
            cleaned_dyld = [p for p in dyld_entries if not p.startswith(sys._MEIPASS)]
            if cleaned_dyld:
                env['DYLD_LIBRARY_PATH'] = os.pathsep.join(cleaned_dyld)
            else:
                env.pop('DYLD_LIBRARY_PATH', None)
        
        return env

    def _get_native_steam_service(self):
        """Get native Steam operations service instance"""
        if self._native_steam_service is None:
            from ..services.native_steam_operations_service import NativeSteamOperationsService
            self._native_steam_service = NativeSteamOperationsService(steamdeck=self.steamdeck)
        return self._native_steam_service

    def detect_protontricks(self):
        """
        Detect if protontricks is installed (silent detection for GUI/automated use).

        Returns True if protontricks is found, False otherwise.
        Does NOT prompt user or attempt installation - that's handled by the GUI.
        """
        logger.debug("Detecting if protontricks is installed...")

        # Check if protontricks exists as a command
        protontricks_path_which = shutil.which("protontricks")
        self.flatpak_path = shutil.which("flatpak")

        if protontricks_path_which:
            # Check if it's a flatpak wrapper
            try:
                with open(protontricks_path_which, 'r') as f:
                    content = f.read()
                    if "flatpak run" in content:
                        logger.debug(f"Detected Protontricks is a Flatpak wrapper at {protontricks_path_which}")
                        self.which_protontricks = 'flatpak'
                    else:
                        logger.info(f"Native Protontricks found at {protontricks_path_which}")
                        self.which_protontricks = 'native'
                        self.protontricks_path = protontricks_path_which
                        return True
            except Exception as e:
                logger.error(f"Error reading protontricks executable: {e}")

        # Check if flatpak protontricks is installed (check both user and system)
        try:
            env = self._get_clean_subprocess_env()

            # Check user installation first
            result_user = subprocess.run(
                ["flatpak", "list", "--user"],
                capture_output=True,
                text=True,
                env=env
            )
            if result_user.returncode == 0 and "com.github.Matoking.protontricks" in result_user.stdout:
                logger.info("Flatpak Protontricks is installed (user-level)")
                self.which_protontricks = 'flatpak'
                self.flatpak_install_type = 'user'
                return True

            # Check system installation
            result_system = subprocess.run(
                ["flatpak", "list", "--system"],
                capture_output=True,
                text=True,
                env=env
            )
            if result_system.returncode == 0 and "com.github.Matoking.protontricks" in result_system.stdout:
                logger.info("Flatpak Protontricks is installed (system-level)")
                self.which_protontricks = 'flatpak'
                self.flatpak_install_type = 'system'
                return True

        except FileNotFoundError:
            logger.warning("'flatpak' command not found. Cannot check for Flatpak Protontricks.")
        except Exception as e:
            logger.error(f"Unexpected error checking flatpak: {e}")

        # Not found
        logger.warning("Protontricks not found (native or flatpak).")
        return False

    def _get_flatpak_run_args(self) -> List[str]:
        """
        Get the correct flatpak run arguments based on installation type.
        Returns list starting with ['flatpak', 'run', '--user'|'--system', ...]
        """
        base_args = ["flatpak", "run"]

        if self.flatpak_install_type == 'user':
            base_args.append("--user")
        elif self.flatpak_install_type == 'system':
            base_args.append("--system")
        # If flatpak_install_type is None, don't add flag (shouldn't happen in normal flow)

        return base_args

    def _get_flatpak_alias_string(self, command=None) -> str:
        """
        Get the correct flatpak alias string based on installation type.
        Args:
            command: Optional command override (e.g., 'protontricks-launch').
                     If None, returns base protontricks alias.
        Returns:
            String like 'flatpak run --user com.github.Matoking.protontricks'
        """
        flag = f"--{self.flatpak_install_type}" if self.flatpak_install_type else ""

        if command:
            # For commands like protontricks-launch
            if flag:
                return f"flatpak run {flag} --command={command} com.github.Matoking.protontricks"
            else:
                return f"flatpak run --command={command} com.github.Matoking.protontricks"
        else:
            # Base protontricks command
            if flag:
                return f"flatpak run {flag} com.github.Matoking.protontricks"
            else:
                return f"flatpak run com.github.Matoking.protontricks"

    def check_protontricks_version(self):
        """
        Check if the protontricks version is sufficient
        Returns True if version is sufficient, False otherwise
        """
        try:
            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "-V"]
            else:
                cmd = ["protontricks", "-V"]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            version_str = result.stdout.split(' ')[1].strip('()')
            
            # Clean version string
            cleaned_version = re.sub(r'[^0-9.]', '', version_str)
            self.protontricks_version = cleaned_version
            
            # Parse version components
            version_parts = cleaned_version.split('.')
            if len(version_parts) >= 2:
                major, minor = int(version_parts[0]), int(version_parts[1])
                if major < 1 or (major == 1 and minor < 12):
                    logger.error(f"Protontricks version {cleaned_version} is too old. Version 1.12.0 or newer is required.")
                    return False
                return True
            else:
                logger.error(f"Could not parse protontricks version: {cleaned_version}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking protontricks version: {e}")
            return False
    
    def run_protontricks(self, *args, **kwargs):
        """
        Run protontricks with the given arguments and keyword arguments.
        kwargs are passed directly to subprocess.run (e.g., stderr=subprocess.DEVNULL).
        Use stdout=subprocess.PIPE, stderr=subprocess.PIPE/DEVNULL instead of capture_output=True.
        Returns subprocess.CompletedProcess object
        """
        # Ensure protontricks is detected first
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                logger.error("Could not detect protontricks installation")
                return None

        # Build command based on detected protontricks type
        if self.which_protontricks == 'bundled':
            # CRITICAL: Use safe Python executable to prevent AppImage recursive spawning
            from .subprocess_utils import get_safe_python_executable
            python_exe = get_safe_python_executable()
            
            # Use bundled wrapper script for reliable invocation
            # The wrapper script imports cli and calls it with sys.argv
            wrapper_script = self._get_bundled_protontricks_wrapper_path()
            if wrapper_script and Path(wrapper_script).exists():
                cmd = [python_exe, str(wrapper_script)]
                cmd.extend([str(a) for a in args])
            else:
                # Fallback: use python -m to run protontricks CLI directly
                # This avoids importing protontricks.__init__ which imports gui.py which needs Pillow
                cmd = [python_exe, "-m", "protontricks.cli.main"]
                cmd.extend([str(a) for a in args])
        elif self.which_protontricks == 'flatpak':
            cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks"]
            cmd.extend(args)
        else:  # native
            cmd = ["protontricks"]
            cmd.extend(args)

        # Default to capturing stdout/stderr unless specified otherwise in kwargs
        run_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'text': True,
            **kwargs # Allow overriding defaults (like stderr=DEVNULL)
        }
        
        # Log full command for advanced users to reproduce manually (debug mode only)
        cmd_str = ' '.join(map(str, cmd))
        logger.debug("=" * 80)
        logger.debug("PROTONTRICKS COMMAND (for manual reproduction):")
        logger.debug(f"  {cmd_str}")
        logger.debug("=" * 80)

        # Handle environment: if env was passed in kwargs, merge it with our clean env
        # Otherwise create a clean env from scratch
        if 'env' in kwargs and kwargs['env']:
            # Merge passed env with our clean env (our values take precedence)
            env = self._get_clean_subprocess_env()
            env.update(kwargs['env'])  # Merge passed env, but our clean env is base
            # Re-apply our critical settings after merge to ensure they're set
        else:
            # Bundled-runtime fix: Use cleaned environment for all protontricks calls
            env = self._get_clean_subprocess_env()
        
        # Suppress Wine debug output
        env['WINEDEBUG'] = '-all'
        
        # CRITICAL: Set STEAM_DIR based on libraryfolders.vdf to prevent user prompts
        steam_dir = self._get_steam_dir_from_libraryfolders()
        if steam_dir:
            env['STEAM_DIR'] = str(steam_dir)
            logger.debug(f"Set STEAM_DIR for protontricks: {steam_dir}")
        else:
            logger.warning("Could not determine STEAM_DIR from libraryfolders.vdf - protontricks may prompt user")

        # CRITICAL: Only set bundled winetricks for NATIVE protontricks
        # Flatpak protontricks runs in a sandbox and CANNOT access AppImage FUSE mounts (/tmp/.mount_*)
        # Flatpak protontricks has its own winetricks bundled inside the flatpak
        if self.which_protontricks == 'native':
            winetricks_path = self._get_bundled_winetricks_path()
            if winetricks_path:
                env['WINETRICKS'] = str(winetricks_path)
                logger.debug(f"Set WINETRICKS for native protontricks: {winetricks_path}")
            else:
                logger.warning("Bundled winetricks not found - native protontricks will use system winetricks")

            cabextract_path = self._get_bundled_cabextract_path()
            if cabextract_path:
                cabextract_dir = str(cabextract_path.parent)
                current_path = env.get('PATH', '')
                env['PATH'] = f"{cabextract_dir}{os.pathsep}{current_path}" if current_path else cabextract_dir
                logger.debug(f"Added bundled cabextract to PATH for native protontricks: {cabextract_dir}")
            else:
                logger.warning("Bundled cabextract not found - native protontricks will use system cabextract")
        else:
            # Flatpak protontricks - DO NOT set bundled paths
            logger.debug(f"Using {self.which_protontricks} protontricks - it has its own winetricks (cannot access AppImage mounts)")
        
        # CRITICAL: Suppress winetricks verbose output when not in debug mode
        # WINETRICKS_SUPER_QUIET suppresses "Executing..." messages from winetricks
        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        debug_mode = config_handler.get('debug_mode', False)
        if not debug_mode:
            env['WINETRICKS_SUPER_QUIET'] = '1'
            logger.debug("Set WINETRICKS_SUPER_QUIET=1 to suppress winetricks verbose output")
        else:
            logger.debug("Debug mode enabled - winetricks verbose output will be shown")
        
        # Note: No need to modify LD_LIBRARY_PATH for Wine/Proton as it's a system dependency
        # Wine/Proton finds its own libraries through the system's library search paths

        run_kwargs['env'] = env
        try:
            return subprocess.run(cmd, **run_kwargs)
        except Exception as e:
            logger.error(f"Error running protontricks: {e}")
            return None

    def set_protontricks_permissions(self, modlist_dir, steamdeck=False):
        """
        Set permissions for Steam operations to access the modlist directory.

        Uses native operations when enabled, falls back to protontricks permissions.
        Returns True on success, False on failure
        """
        # Use native operations if enabled
        if self.use_native_operations:
            logger.debug("Using native Steam operations, permissions handled natively")
            try:
                return self._get_native_steam_service().set_steam_permissions(modlist_dir, steamdeck)
            except Exception as e:
                logger.warning(f"Native permissions failed, falling back to protontricks: {e}")

        if self.which_protontricks != 'flatpak':
            logger.debug("Using Native protontricks, skip setting permissions")
            return True
        
        logger.info("Setting Protontricks permissions...")
        # Bundled-runtime fix: Use cleaned environment
        env = self._get_clean_subprocess_env()
        
        permissions_set = []
        permissions_failed = []
        
        try:
            # 1. Set permission for modlist directory (required for wine component installation)
            logger.debug(f"Setting permission for modlist directory: {modlist_dir}")
            try:
                subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks", 
                               f"--filesystem={modlist_dir}"], check=True, env=env, capture_output=True)
                permissions_set.append(f"modlist directory: {modlist_dir}")
            except subprocess.CalledProcessError as e:
                permissions_failed.append(f"modlist directory: {modlist_dir} ({e})")
                logger.warning(f"Failed to set permission for modlist directory: {e}")
            
            # 2. Set permission for main Steam directory (required for accessing compatdata, config, etc.)
            steam_dir = self._get_steam_dir_from_libraryfolders()
            if steam_dir and steam_dir.exists():
                logger.info(f"Setting permission for Steam directory: {steam_dir}")
                logger.debug("This allows protontricks to access Steam compatdata, config, and steamapps directories")
                try:
                    subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks", 
                                   f"--filesystem={steam_dir}"], check=True, env=env, capture_output=True)
                    permissions_set.append(f"Steam directory: {steam_dir}")
                except subprocess.CalledProcessError as e:
                    permissions_failed.append(f"Steam directory: {steam_dir} ({e})")
                    logger.warning(f"Failed to set permission for Steam directory: {e}")
            else:
                logger.warning("Could not determine Steam directory - protontricks may not have access to Steam directories")
            
            # 3. Set permissions for all additional Steam library folders (compatdata can be in any library)
            from ..handlers.path_handler import PathHandler
            all_library_paths = PathHandler.get_all_steam_library_paths()
            for lib_path in all_library_paths:
                # Skip if this is the main Steam directory (already set above)
                if steam_dir and lib_path.resolve() == steam_dir.resolve():
                    continue
                if lib_path.exists():
                    logger.debug(f"Setting permission for Steam library folder: {lib_path}")
                    try:
                        subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks", 
                                       f"--filesystem={lib_path}"], check=True, env=env, capture_output=True)
                        permissions_set.append(f"Steam library: {lib_path}")
                    except subprocess.CalledProcessError as e:
                        permissions_failed.append(f"Steam library: {lib_path} ({e})")
                        logger.warning(f"Failed to set permission for Steam library folder {lib_path}: {e}")
            
            # 4. Set SD card permissions (Steam Deck only)
            if steamdeck:
                logger.warn("Checking for SDCard and setting permissions appropriately...")
                # Find sdcard path
                result = subprocess.run(["df", "-h"], capture_output=True, text=True, env=env)
                for line in result.stdout.splitlines():
                    if "/run/media" in line:
                        sdcard_path = line.split()[-1]
                        logger.debug(f"SDCard path: {sdcard_path}")
                        try:
                            subprocess.run(["flatpak", "override", "--user", f"--filesystem={sdcard_path}", 
                                          "com.github.Matoking.protontricks"], check=True, env=env, capture_output=True)
                            permissions_set.append(f"SD card: {sdcard_path}")
                        except subprocess.CalledProcessError as e:
                            permissions_failed.append(f"SD card: {sdcard_path} ({e})")
                            logger.warning(f"Failed to set permission for SD card {sdcard_path}: {e}")
                # Add standard Steam Deck SD card path as fallback
                try:
                    subprocess.run(["flatpak", "override", "--user", "--filesystem=/run/media/mmcblk0p1", 
                                  "com.github.Matoking.protontricks"], check=True, env=env, capture_output=True)
                    permissions_set.append("SD card: /run/media/mmcblk0p1")
                except subprocess.CalledProcessError as e:
                    # This is expected to fail if the path doesn't exist, so only log at debug level
                    logger.debug(f"Could not set permission for fallback SD card path (may not exist): {e}")
            
            # Report results
            if permissions_set:
                logger.info(f"Successfully set {len(permissions_set)} permission(s) for protontricks")
                logger.debug(f"Permissions set: {', '.join(permissions_set)}")
            if permissions_failed:
                logger.warning(f"Failed to set {len(permissions_failed)} permission(s)")
                logger.debug(f"Failed permissions: {', '.join(permissions_failed)}")
            
            # Return True if at least modlist directory permission was set (critical)
            if any("modlist directory" in p for p in permissions_set):
                logger.info("Protontricks permissions configured (at least modlist directory access granted)")
                return True
            else:
                logger.error("Failed to set critical modlist directory permission")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error while setting Protontricks permissions: {e}")
            return False
    
    def create_protontricks_alias(self):
        """
        Create aliases for protontricks in ~/.bashrc if using flatpak
        Returns True if created or already exists, False on failure
        """
        if self.which_protontricks != 'flatpak':
            logger.debug("Not using flatpak, skipping alias creation")
            return True
        
        try:
            bashrc_path = os.path.expanduser("~/.bashrc")
            
            # Check if file exists and read content
            if os.path.exists(bashrc_path):
                with open(bashrc_path, 'r') as f:
                    content = f.read()
                
                # Check if aliases already exist
                protontricks_alias_exists = "alias protontricks=" in content
                launch_alias_exists = "alias protontricks-launch" in content
                
                # Add missing aliases with correct flag based on installation type
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        logger.info("Adding protontricks alias to ~/.bashrc")
                        alias_cmd = self._get_flatpak_alias_string()
                        f.write(f"\nalias protontricks='{alias_cmd}'\n")

                    if not launch_alias_exists:
                        logger.info("Adding protontricks-launch alias to ~/.bashrc")
                        launch_alias_cmd = self._get_flatpak_alias_string(command='protontricks-launch')
                        f.write(f"\nalias protontricks-launch='{launch_alias_cmd}'\n")
                
                return True
            else:
                logger.error("~/.bashrc not found, skipping alias creation")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create protontricks aliases: {e}")
            return False
    
    # def get_modlists(self): # Keep commented out or remove old method
    #     """
    #     Get a list of Skyrim, Fallout, Oblivion modlists from Steam via protontricks
    #     Returns a list of modlist names
    #     """
        # ... (old implementation with filtering) ...
    
    # Renamed from list_non_steam_games for clarity and purpose
    def list_non_steam_shortcuts(self) -> Dict[str, str]:
        """List ALL non-Steam shortcuts.

        Uses native VDF parsing when enabled, falls back to protontricks -l parsing.

        Returns:
            A dictionary mapping the shortcut name (AppName) to its AppID.
            Returns an empty dictionary if none are found or an error occurs.
        """
        # Use native operations if enabled
        if self.use_native_operations:
            logger.info("Listing non-Steam shortcuts via native VDF parsing...")
            try:
                return self._get_native_steam_service().list_non_steam_shortcuts()
            except Exception as e:
                logger.warning(f"Native shortcut listing failed, falling back to protontricks: {e}")

        logger.info("Listing ALL non-Steam shortcuts via protontricks...")
        non_steam_shortcuts = {}
        # --- Ensure protontricks is detected before proceeding ---
        if not self.which_protontricks:
            self.logger.info("Protontricks type/path not yet determined. Running detection...")
            if not self.detect_protontricks():
                self.logger.error("Protontricks detection failed. Cannot list shortcuts.")
                return {}
            self.logger.info(f"Protontricks detection successful: {self.which_protontricks}")
        # --- End detection check ---
        try:
            cmd = [] # Initialize cmd list
            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "-l"]
            elif self.protontricks_path:
                cmd = [self.protontricks_path, "-l"]
            else:
                logger.error("Protontricks path not determined, cannot list shortcuts.")
                return {}
            self.logger.debug(f"Running command: {' '.join(cmd)}")
            # Bundled-runtime fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore', env=env)
            # Regex to capture name and AppID
            pattern = re.compile(r"Non-Steam shortcut:\s+(.+)\s+\((\d+)\)")
            for line in result.stdout.splitlines():
                line = line.strip()
                match = pattern.match(line)
                if match:
                    app_name = match.group(1).strip() # Get the name
                    app_id = match.group(2).strip()   # Get the AppID
                    non_steam_shortcuts[app_name] = app_id
                    logger.debug(f"Found non-Steam shortcut: '{app_name}' with AppID {app_id}")
            if not non_steam_shortcuts:
                logger.warning("No non-Steam shortcuts found in protontricks output.")
        except FileNotFoundError:
             logger.error(f"Protontricks command not found. Path: {cmd[0] if cmd else 'N/A'}")
             return {}
        except subprocess.CalledProcessError as e:
            # Log error but don't necessarily stop; might have partial output
            logger.error(f"Error running protontricks -l (Exit code: {e.returncode}): {e}")
            logger.error(f"Stderr (truncated): {e.stderr[:500] if e.stderr else ''}")
            # Return what we have, might be useful
        except Exception as e:
            logger.error(f"Unexpected error listing non-Steam shortcuts: {e}", exc_info=True)
            return {}
        return non_steam_shortcuts
    
    def enable_dotfiles(self, appid):
        """
        Enable visibility of (.)dot files in the Wine prefix
        Returns True on success, False on failure
        
        Args:
            appid (str): The app ID to use
        
        Returns:
            bool: True on success, False on failure
        """
        logger.debug(f"APPID={appid}")
        logger.info("Enabling visibility of (.)dot files...")
        
        try:
            # Check current setting
            result = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles", 
                appid,
                stderr=subprocess.DEVNULL # Suppress stderr for this query
            )
            
            # Check if the initial query command ran successfully and contained expected output
            if result and result.returncode == 0 and "ShowDotFiles" in result.stdout and "Y" in result.stdout:
                logger.info("DotFiles already enabled via registry... skipping")
                return True
            elif result and result.returncode != 0:
                # Log as info/debug since non-zero exit is expected if key doesn't exist
                logger.info(f"Initial query for ShowDotFiles likely failed because the key doesn't exist yet (Exit Code: {result.returncode}). Proceeding to set it. Stderr: {result.stderr}") 
            elif not result:
                 logger.error("Failed to execute initial dotfile query command.")
                 # Proceed cautiously

            # --- Try to set the value --- 
            dotfiles_set_success = False

            # Method 1: Set registry key (Primary Method)
            logger.debug("Attempting to set ShowDotFiles registry key...")
            result_add = self.run_protontricks(
                "-c", "WINEDEBUG=-all wine reg add \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles /d Y /f", 
                appid,
                # Keep stderr for this one to log potential errors from reg add
                # stderr=subprocess.DEVNULL 
            )
            if result_add and result_add.returncode == 0:
                 logger.info("'wine reg add' command executed successfully.")
                 dotfiles_set_success = True # Tentative success
            elif result_add:
                 logger.warning(f"'wine reg add' command failed (Exit Code: {result_add.returncode}). Stderr: {result_add.stderr}")
            else:
                 logger.error("Failed to execute 'wine reg add' command.")

            # Method 2: Create user.reg entry (Backup Method)
            # This is useful if registry commands fail but direct file access works
            logger.debug("Ensuring user.reg has correct entry...")
            prefix_path = self.get_wine_prefix_path(appid) 
            if prefix_path:
                user_reg_path = Path(prefix_path) / "user.reg" 
                try:
                    if user_reg_path.exists():
                        content = user_reg_path.read_text(encoding='utf-8', errors='ignore')
                        # Check for CORRECT format with proper backslash escaping
                        has_correct_format = '[Software\\\\Wine]' in content and '"ShowDotFiles"="Y"' in content
                        has_broken_format = '[SoftwareWine]' in content and '"ShowDotFiles"="Y"' in content

                        if has_broken_format and not has_correct_format:
                            # Fix the broken format by replacing the section header
                            logger.debug(f"Found broken ShowDotFiles format in {user_reg_path}, fixing...")
                            content = content.replace('[SoftwareWine]', '[Software\\\\Wine]')
                            user_reg_path.write_text(content, encoding='utf-8')
                            dotfiles_set_success = True
                        elif not has_correct_format:
                            logger.debug(f"Adding ShowDotFiles entry to {user_reg_path}")
                            with open(user_reg_path, 'a', encoding='utf-8') as f:
                                f.write('\n[Software\\\\Wine] 1603891765\n')
                                f.write('"ShowDotFiles"="Y"\n')
                            dotfiles_set_success = True # Count file write as success too
                        else:
                             logger.debug("ShowDotFiles already present in correct format in user.reg")
                             dotfiles_set_success = True # Already there counts as success
                    else:
                        logger.warning(f"user.reg not found at {user_reg_path}, creating it.")
                        with open(user_reg_path, 'w', encoding='utf-8') as f:
                             f.write('[Software\\\\Wine] 1603891765\n')
                             f.write('"ShowDotFiles"="Y"\n')
                        dotfiles_set_success = True # Creating file counts as success
                except Exception as e:
                    logger.warning(f"Error reading/writing user.reg: {e}")
            else:
                logger.warning("Could not get WINEPREFIX path, skipping user.reg modification.")
            
            # --- Verification Step --- 
            logger.debug("Verifying dotfile setting after attempts...")
            verify_result = self.run_protontricks( 
                "-c", "WINEDEBUG=-all wine reg query \"HKEY_CURRENT_USER\\Software\\Wine\" /v ShowDotFiles", 
                appid,
                stderr=subprocess.DEVNULL # Suppress stderr for verification query
            )
            
            query_verified = False
            if verify_result and verify_result.returncode == 0 and "ShowDotFiles" in verify_result.stdout and "Y" in verify_result.stdout:
                 logger.debug("Verification query successful and key is set.")
                 query_verified = True
            elif verify_result:
                 # Change Warning to Info - verification failing right after setting is common
                 logger.info(f"Verification query failed or key not found (Exit Code: {verify_result.returncode}). Stderr: {verify_result.stderr}") 
            else:
                 logger.error("Failed to execute verification query command.")

            # --- Final Decision --- 
            if dotfiles_set_success:
                 # If the add command or file write succeeded, we report overall success,
                 # even if the verification query failed, but log the query status.
                 if query_verified:
                      logger.info("Dotfiles enabled and verified successfully!")
                 else:
                      # Change Warning to Info - verification failing right after setting is common
                      logger.info("Dotfiles potentially enabled (reg add/user.reg succeeded), but verification query failed.") 
                 return True # Report success based on the setting action
            else:
                 # If both the reg add and user.reg steps failed
                 logger.error("Failed to enable dotfiles using registry and user.reg methods.")
                 return False
                
        except Exception as e:
            logger.error(f"Unexpected error enabling dotfiles: {e}", exc_info=True) 
            return False
    
    def set_win10_prefix(self, appid):
        """
        Set Windows 10 version in the proton prefix
        Returns True on success, False on failure
        """
        try:
            # Bundled-runtime fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            env["WINEDEBUG"] = "-all"

            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "--no-bwrap", appid, "win10"]
            else:
                cmd = ["protontricks", "--no-bwrap", appid, "win10"]
            
            subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logger.error(f"Error setting Windows 10 prefix: {e}")
            return False
    
    def protontricks_alias(self):
        """
        Create protontricks alias in ~/.bashrc
        """
        logger.info("Creating protontricks alias in ~/.bashrc...")
        
        try:
            if self.which_protontricks == 'flatpak':
                # Check if aliases already exist
                bashrc_path = os.path.expanduser("~/.bashrc")
                protontricks_alias_exists = False
                launch_alias_exists = False
                
                if os.path.exists(bashrc_path):
                    with open(bashrc_path, 'r') as f:
                        content = f.read()
                        protontricks_alias_exists = "alias protontricks=" in content
                        launch_alias_exists = "alias protontricks-launch=" in content

                # Add aliases if they don't exist with correct flag based on installation type
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        f.write("\n# Jackify: Protontricks alias\n")
                        alias_cmd = self._get_flatpak_alias_string()
                        f.write(f"alias protontricks='{alias_cmd}'\n")
                        logger.debug("Added protontricks alias to ~/.bashrc")

                    if not launch_alias_exists:
                        f.write("\n# Jackify: Protontricks-launch alias\n")
                        launch_alias_cmd = self._get_flatpak_alias_string(command='protontricks-launch')
                        f.write(f"alias protontricks-launch='{launch_alias_cmd}'\n")
                        logger.debug("Added protontricks-launch alias to ~/.bashrc")
                
                logger.info("Protontricks aliases created successfully")
                return True
            else:
                logger.info("Protontricks is not installed via flatpak, skipping alias creation")
                return True
        except Exception as e:
            logger.error(f"Error creating protontricks alias: {e}")
            return False
    
    def get_wine_prefix_path(self, appid) -> Optional[str]:
        """Gets the WINEPREFIX path for a given AppID.

        Uses native path discovery when enabled, falls back to protontricks detection.

        Args:
            appid (str): The Steam AppID.

        Returns:
            The WINEPREFIX path as a string, or None if detection fails.
        """
        # Use native operations if enabled
        if self.use_native_operations:
            logger.debug(f"Getting WINEPREFIX for AppID {appid} via native path discovery")
            try:
                return self._get_native_steam_service().get_wine_prefix_path(appid)
            except Exception as e:
                logger.warning(f"Native WINEPREFIX detection failed, falling back to protontricks: {e}")

        logger.debug(f"Getting WINEPREFIX for AppID {appid}")
        result = self.run_protontricks("-c", "echo $WINEPREFIX", appid)
        if result and result.returncode == 0 and result.stdout.strip():
            prefix_path = result.stdout.strip()
            logger.debug(f"Detected WINEPREFIX: {prefix_path}")
            return prefix_path
        else:
            logger.error(f"Failed to get WINEPREFIX for AppID {appid}. Stderr: {result.stderr if result else 'N/A'}")
            return None
    
    def run_protontricks_launch(self, appid, installer_path, *extra_args):
        """
        Run protontricks-launch (for WebView or similar installers) using the correct method for bundled, flatpak, or native.
        Returns subprocess.CompletedProcess object.
        """
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                self.logger.error("Could not detect protontricks installation")
                return None
        if self.which_protontricks == 'bundled':
            # CRITICAL: Use safe Python executable to prevent AppImage recursive spawning
            from .subprocess_utils import get_safe_python_executable
            python_exe = get_safe_python_executable()
            # Use bundled Python module
            cmd = [python_exe, "-m", "protontricks.cli.launch", "--appid", appid, str(installer_path)]
        elif self.which_protontricks == 'flatpak':
            cmd = self._get_flatpak_run_args() + ["--command=protontricks-launch", "com.github.Matoking.protontricks", "--appid", appid, str(installer_path)]
        else:  # native
            launch_path = shutil.which("protontricks-launch")
            if not launch_path:
                self.logger.error("protontricks-launch command not found in PATH.")
                return None
            cmd = [launch_path, "--appid", appid, str(installer_path)]
        if extra_args:
            cmd.extend(extra_args)
        self.logger.debug(f"Running protontricks-launch: {' '.join(map(str, cmd))}")
        try:
            # Bundled-runtime fix: Use cleaned environment
            env = self._get_clean_subprocess_env()
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        except Exception as e:
            self.logger.error(f"Error running protontricks-launch: {e}")
            return None
    
    def _ensure_flatpak_cache_access(self, cache_path: Path) -> bool:
        """
        Ensure flatpak protontricks has filesystem access to the winetricks cache.

        Args:
            cache_path: Path to winetricks cache directory

        Returns:
            True if access granted or already exists, False on failure
        """
        if self.which_protontricks != 'flatpak':
            return True  # Not flatpak, no action needed

        try:
            # Check if flatpak already has access to this path
            result = subprocess.run(
                ['flatpak', 'override', '--user', '--show', 'com.github.Matoking.protontricks'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # Check if cache path is already in filesystem overrides
                cache_str = str(cache_path.resolve())
                if f'filesystems=' in result.stdout and cache_str in result.stdout:
                    self.logger.debug(f"Flatpak protontricks already has access to cache: {cache_str}")
                    return True

            # Grant access to cache directory
            self.logger.info(f"Granting flatpak protontricks access to winetricks cache: {cache_path}")
            result = subprocess.run(
                ['flatpak', 'override', '--user', 'com.github.Matoking.protontricks',
                 f'--filesystem={cache_path.resolve()}'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                self.logger.info("Successfully granted flatpak protontricks cache access")
                return True
            else:
                self.logger.warning(f"Failed to grant flatpak cache access: {result.stderr}")
                return False

        except Exception as e:
            self.logger.warning(f"Could not configure flatpak cache access: {e}")
            return False

    def install_wine_components(self, appid, game_var, specific_components: Optional[List[str]] = None):
        """
        Install the specified Wine components into the given prefix using protontricks.
        If specific_components is None, use the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).
        """
        self.logger.info("=" * 80)
        self.logger.info("USING PROTONTRICKS")
        self.logger.info("=" * 80)
        env = self._get_clean_subprocess_env()
        env["WINEDEBUG"] = "-all"

        # CRITICAL: Only set bundled winetricks for NATIVE protontricks
        # Flatpak protontricks runs in a sandbox and CANNOT access AppImage FUSE mounts (/tmp/.mount_*)
        # Flatpak protontricks has its own winetricks bundled inside the flatpak
        if self.which_protontricks == 'native':
            winetricks_path = self._get_bundled_winetricks_path()
            if winetricks_path:
                env['WINETRICKS'] = str(winetricks_path)
                self.logger.debug(f"Set WINETRICKS for native protontricks: {winetricks_path}")
            else:
                self.logger.warning("Bundled winetricks not found - native protontricks will use system winetricks")

            cabextract_path = self._get_bundled_cabextract_path()
            if cabextract_path:
                cabextract_dir = str(cabextract_path.parent)
                current_path = env.get('PATH', '')
                env['PATH'] = f"{cabextract_dir}{os.pathsep}{current_path}" if current_path else cabextract_dir
                self.logger.debug(f"Added bundled cabextract to PATH for native protontricks: {cabextract_dir}")
            else:
                self.logger.warning("Bundled cabextract not found - native protontricks will use system cabextract")
        else:
            # Flatpak protontricks - DO NOT set bundled paths
            self.logger.info(f"Using {self.which_protontricks} protontricks - it has its own winetricks (cannot access AppImage mounts)")

        # CRITICAL: Suppress winetricks verbose output when not in debug mode
        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        debug_mode = config_handler.get('debug_mode', False)
        if not debug_mode:
            env['WINETRICKS_SUPER_QUIET'] = '1'
            self.logger.debug("Set WINETRICKS_SUPER_QUIET=1 in install_wine_components to suppress winetricks verbose output")

        # Set up winetricks cache (shared with winetricks_handler for efficiency)
        from jackify.shared.paths import get_jackify_data_dir
        jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
        jackify_cache_dir.mkdir(parents=True, exist_ok=True)

        # Ensure flatpak protontricks has access to cache (no-op for native)
        self._ensure_flatpak_cache_access(jackify_cache_dir)

        env['WINETRICKS_CACHE'] = str(jackify_cache_dir)
        self.logger.info(f"Using winetricks cache: {jackify_cache_dir}")
        if specific_components is not None:
            components_to_install = specific_components
            self.logger.info(f"Installing specific components: {components_to_install}")
        else:
            components_to_install = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {components_to_install}")
        if not components_to_install:
            self.logger.info("No Wine components to install.")
            return True
        self.logger.info(f"AppID: {appid}, Game: {game_var}, Components: {components_to_install}")
        # print(f"\n[Jackify] Installing Wine components for AppID {appid} ({game_var}):\n  {', '.join(components_to_install)}\n")  # Suppressed per user request
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()
            try:
                result = self.run_protontricks("--no-bwrap", appid, "-q", *components_to_install, env=env, timeout=600)
                self.logger.debug(f"Protontricks output: {result.stdout if result else ''}")
                if result and result.returncode == 0:
                    self.logger.info("Wine Component installation command completed.")

                    # Verify components were actually installed
                    if self._verify_components_installed(appid, components_to_install):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        return True
                    else:
                        self.logger.error(f"Component verification failed (Attempt {attempt}/{max_attempts})")
                        # Continue to retry
                else:
                    self.logger.error(f"Protontricks command failed (Attempt {attempt}/{max_attempts}). Return Code: {result.returncode if result else 'N/A'}")
                    # Only show stdout/stderr in debug mode to avoid verbose output
                    from ..handlers.config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    debug_mode = config_handler.get('debug_mode', False)
                    if debug_mode:
                        self.logger.error(f"Stdout: {result.stdout.strip() if result else ''}")
                        self.logger.error(f"Stderr: {result.stderr.strip() if result else ''}")
                    else:
                        # In non-debug mode, only show stderr if it contains actual errors (not verbose winetricks output)
                        if result and result.stderr:
                            stderr_lower = result.stderr.lower()
                            # Filter out verbose winetricks messages
                            if any(keyword in stderr_lower for keyword in ['error', 'failed', 'cannot', 'warning: cannot find']):
                                # Only show actual errors, not "Executing..." messages
                                error_lines = [line for line in result.stderr.strip().split('\n') 
                                             if any(keyword in line.lower() for keyword in ['error', 'failed', 'cannot', 'warning: cannot find'])
                                             and 'executing' not in line.lower()]
                                if error_lines:
                                    self.logger.error(f"Stderr (errors only): {' '.join(error_lines)}")
            except Exception as e:
                self.logger.error(f"Error during protontricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)
        self.logger.error(f"Failed to install Wine components after {max_attempts} attempts.")
        return False
    
    def _verify_components_installed(self, appid: str, components: List[str]) -> bool:
        """
        Verify that Wine components were actually installed by querying protontricks.

        Args:
            appid: Steam AppID
            components: List of components that should be installed

        Returns:
            bool: True if all critical components are verified, False otherwise
        """
        try:
            self.logger.info("Verifying installed components...")

            # Run protontricks list-installed to get actual installed components
            result = self.run_protontricks("--no-bwrap", appid, "list-installed", timeout=30)

            if not result or result.returncode != 0:
                self.logger.error("Failed to query installed components")
                self.logger.debug(f"list-installed stderr: {result.stderr if result else 'N/A'}")
                return False

            installed_output = result.stdout.lower()
            self.logger.debug(f"Installed components output: {installed_output}")

            # Define critical components that MUST be installed
            # These are the core components that determine success
            critical_components = ["vcrun2022", "xact"]

            # Check for critical components
            missing_critical = []
            for component in critical_components:
                if component.lower() not in installed_output:
                    missing_critical.append(component)

            if missing_critical:
                self.logger.error(f"CRITICAL: Missing essential components: {missing_critical}")
                self.logger.error("Installation reported success but components are NOT installed")
                return False

            # Check for requested components (warn but don't fail)
            missing_requested = []
            for component in components:
                # Handle settings like fontsmooth=rgb (just check the base component name)
                base_component = component.split('=')[0].lower()
                if base_component not in installed_output and component.lower() not in installed_output:
                    missing_requested.append(component)

            if missing_requested:
                self.logger.warning(f"Some requested components may not be installed: {missing_requested}")
                self.logger.warning("This may cause issues, but critical components are present")

            self.logger.info(f"Verification passed - critical components confirmed: {critical_components}")
            return True

        except Exception as e:
            self.logger.error(f"Error verifying components: {e}", exc_info=True)
            return False

    def _cleanup_wine_processes(self):
        """
        Internal method to clean up wine processes during component installation
        """
        try:
            subprocess.run("pgrep -f 'win7|win10|ShowDotFiles|protontricks' | xargs -r kill -9",
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run("pkill -9 winetricks",
                          shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error cleaning up wine processes: {e}") 
    
    def check_and_setup_protontricks(self) -> bool:
        """
        Runs all necessary checks and setup steps for Protontricks.
        - Detects (and prompts for install if missing)
        - Checks version
        - Creates aliases if using Flatpak

        Returns:
            bool: True if Protontricks is ready to use, False otherwise.
        """
        logger.info("Checking and setting up Protontricks...")

        logger.info("Checking Protontricks installation...")
        if not self.detect_protontricks():
            # Error message already printed by detect_protontricks if install fails/skipped
            return False
        logger.info(f"Protontricks detected: {self.which_protontricks}")

        logger.info("Checking Protontricks version...")
        if not self.check_protontricks_version():
            # Error message already printed by check_protontricks_version
            print(f"Error: Protontricks version {self.protontricks_version} is too old or could not be checked.")
            return False
        logger.info(f"Protontricks version {self.protontricks_version} is sufficient.")

        # Aliases are non-critical, log warning if creation fails
        if self.which_protontricks == 'flatpak':
            logger.info("Ensuring Flatpak aliases exist in ~/.bashrc...")
            if not self.protontricks_alias():
                # Logged by protontricks_alias, maybe add print?
                print("Warning: Failed to create/verify protontricks aliases in ~/.bashrc")
                # Don't necessarily fail the whole setup for this

        logger.info("Protontricks check and setup completed successfully.")
        return True 