"""Prefix creation methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional
import logging
import os
import time
import subprocess

logger = logging.getLogger(__name__)


def debug_print(message):
    """Log debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        logger.debug(message)


class PrefixCreationMixin:
    """Mixin providing prefix creation methods for AutomatedPrefixService."""

    def detect_actual_prefix_appid(self, initial_appid: int, shortcut_name: str) -> Optional[int]:
        """
        After Steam restart, detect the actual prefix AppID that was created.
        Uses direct VDF file reading to find the actual AppID.

        Args:
            initial_appid: The initial (negative) AppID from shortcuts.vdf
            shortcut_name: Name of the shortcut for logging

        Returns:
            The actual (positive) AppID of the created prefix, or None if not found
        """
        try:
            logger.info(f"Using VDF to detect actual AppID for shortcut: {shortcut_name}")

            # Wait up to 30 seconds for Steam to process the shortcut
            for i in range(30):
                try:
                    from ..handlers.shortcut_handler import ShortcutHandler
                    from ..handlers.path_handler import PathHandler

                    path_handler = PathHandler()
                    shortcuts_path = path_handler._find_shortcuts_vdf()

                    if shortcuts_path:
                        from ..handlers.vdf_handler import VDFHandler
                        shortcuts_data = VDFHandler.load(shortcuts_path, binary=True)

                        if shortcuts_data and 'shortcuts' in shortcuts_data:
                            for idx, shortcut in shortcuts_data['shortcuts'].items():
                                app_name = shortcut.get('AppName', shortcut.get('appname', '')).strip()

                                if app_name.lower() == shortcut_name.lower():
                                    appid = shortcut.get('appid')
                                    if appid:
                                        actual_appid = int(appid) & 0xFFFFFFFF
                                        logger.info(f"Found shortcut '{app_name}' in shortcuts.vdf")
                                        logger.info(f"  Initial AppID (signed): {initial_appid}")
                                        logger.info(f"  Actual AppID (unsigned): {actual_appid}")
                                        return actual_appid

                    logger.debug(f"Shortcut '{shortcut_name}' not found in VDF yet (attempt {i+1}/30)")
                    time.sleep(1)

                except Exception as e:
                    logger.warning(f"Error reading shortcuts.vdf on attempt {i+1}: {e}")
                    time.sleep(1)

            logger.error(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf after 30 seconds")
            return None

        except Exception as e:
            logger.error(f"Error detecting actual prefix AppID: {e}")
            return None

    def launch_shortcut_to_trigger_prefix(self, initial_appid: int) -> bool:
        """
        Launch the shortcut using rungameid to trigger prefix creation.
        This follows the same pattern as the working test script.
        
        Args:
            initial_appid: The initial (negative) AppID from shortcuts.vdf
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert signed AppID to unsigned AppID (same as STL's generateSteamShortID)
            unsigned_appid = self.generate_steam_short_id(initial_appid)
            
            # Calculate rungameid using the unsigned AppID
            rungameid = (unsigned_appid << 32) | 0x02000000
            
            logger.info(f"Launching shortcut with rungameid: {rungameid}")
            debug_print(f"[DEBUG] Launching shortcut with rungameid: {rungameid}")
            debug_print(f"[DEBUG] Initial signed AppID: {initial_appid}")
            debug_print(f"[DEBUG] Unsigned AppID: {unsigned_appid}")
            
            # Launch using rungameid
            cmd = ['steam', f'steam://rungameid/{rungameid}']
            debug_print(f"[DEBUG] About to run launch command: {' '.join(cmd)}")
            
            # Use subprocess.Popen to launch asynchronously (steam command returns immediately)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Wait a moment for the process to start
            time.sleep(1)
            
            # Check if the process is still running (steam command should exit quickly)
            try:
                return_code = process.poll()
                if return_code is None:
                    # Process is still running, wait a bit more
                    time.sleep(2)
                    return_code = process.poll()
                
                debug_print(f"[DEBUG] Steam launch process return code: {return_code}")
                
                # Get any output
                stdout, stderr = process.communicate(timeout=1)
                if stdout:
                    debug_print(f"[DEBUG] Steam launch stdout: {stdout}")
                if stderr:
                    debug_print(f"[DEBUG] Steam launch stderr: {stderr}")
                    
            except subprocess.TimeoutExpired:
                debug_print("[DEBUG] Steam launch process timed out, but that's OK")
                process.kill()
            
            logger.info(f"Launch command executed: {' '.join(cmd)}")
            
            # Give it a moment for the shortcut to actually start
            time.sleep(5)
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Launch command timed out")
            debug_print("[DEBUG] Launch command timed out")
            return False
        except Exception as e:
            logger.error(f"Error launching shortcut: {e}")
            debug_print(f"[DEBUG] Error launching shortcut: {e}")
            return False

    def create_prefix_directly(self, appid: int, batch_file_path: str) -> Optional[Path]:
        """
        Create prefix directly using Proton wrapper.
        
        Args:
            appid: The AppID from the shortcut
            batch_file_path: Path to the temporary batch file
            
        Returns:
            Path to the created prefix, or None if failed
        """
        proton_path = self.find_proton_experimental()
        if not proton_path:
            return None
        
        # Steam uses negative AppIDs for non-Steam shortcuts, but we need the positive value for the prefix path
        positive_appid = abs(appid)
        logger.info(f"Using positive AppID {positive_appid} for prefix creation (original: {appid})")
        
        # Create the prefix directory structure
        prefix_path = self._get_compatdata_path_for_appid(positive_appid)
        if not prefix_path:
            logger.error(f"Could not determine compatdata path for AppID {positive_appid}")
            return None
        
        # Create the prefix directory structure
        prefix_path.mkdir(parents=True, exist_ok=True)
        pfx_dir = prefix_path / "pfx"
        pfx_dir.mkdir(exist_ok=True)
        
        # Set up environment
        env = os.environ.copy()
        env['STEAM_COMPAT_DATA_PATH'] = str(prefix_path)
        env['STEAM_COMPAT_APP_ID'] = str(positive_appid)  # Use positive AppID for environment
        
        # Determine correct Steam root based on installation type
        from ..handlers.path_handler import PathHandler
        path_handler = PathHandler()
        steam_library = path_handler.find_steam_library()
        if steam_library and steam_library.name == "common":
            # Extract Steam root from library path: .../Steam/steamapps/common -> .../Steam
            steam_root = steam_library.parent.parent
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(steam_root)
        else:
            # Fallback to legacy path if detection fails
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(Path.home() / ".local/share/Steam")
        
        # Build the command
        cmd = [
            str(proton_path / "proton"),
            "run",
            batch_file_path
        ]
        
        logger.info(f"Creating prefix with command: {' '.join(cmd)}")
        logger.info(f"Prefix path: {prefix_path}")
        logger.info(f"Using AppID: {positive_appid} (original: {appid})")
        
        try:
            # Run the command with a timeout
            result = subprocess.run(
                cmd, 
                env=env, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            # Check if prefix was created
            time.sleep(2)  # Give it a moment to settle
            
            prefix_created = prefix_path.exists()
            pfx_exists = (prefix_path / "pfx").exists()
            
            logger.info(f"Return code: {result.returncode}")
            logger.info(f"Prefix created: {prefix_created}")
            logger.info(f"pfx directory exists: {pfx_exists}")
            
            if result.stderr:
                logger.debug(f"stderr: {result.stderr.strip()}")
            
            success = prefix_created and pfx_exists
            
            if success:
                logger.info(f"Prefix created successfully at: {prefix_path}")
                return prefix_path
            else:
                logger.error("Failed to create prefix")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out, but this might be normal")
            # Check if prefix was created despite timeout
            prefix_created = prefix_path.exists()
            pfx_exists = (prefix_path / "pfx").exists()
            
            if prefix_created and pfx_exists:
                logger.info(f"Prefix created successfully despite timeout at: {prefix_path}")
                return prefix_path
            else:
                logger.error("No prefix created")
                return None
                
        except Exception as e:
            logger.error(f"Error creating prefix: {e}")
            return None

    def _get_compatdata_path_for_appid(self, appid: int) -> Optional[Path]:
        """
        Get the compatdata path for a given AppID.
        
        First tries to find existing compatdata, then constructs path from libraryfolders.vdf
        for creating new prefixes.
        
        Args:
            appid: The AppID to get the path for
            
        Returns:
            Path to the compatdata directory, or None if not found
        """
        from ..handlers.path_handler import PathHandler
        
        # First, try to find existing compatdata
        compatdata_path = PathHandler.find_compat_data(str(appid))
        if compatdata_path:
            return compatdata_path
        
        # Prefix doesn't exist yet - determine where to create it from libraryfolders.vdf
        library_paths = PathHandler.get_all_steam_library_paths()
        if library_paths:
            # Use the first library (typically the default library)
            # Construct compatdata path: library_path/steamapps/compatdata/appid
            first_library = library_paths[0]
            compatdata_base = first_library / "steamapps" / "compatdata"
            return compatdata_base / str(appid)
        
        # Only fallback if VDF parsing completely fails
        logger.warning("Could not get library paths from libraryfolders.vdf, using fallback locations")
        fallback_bases = [
            Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
        ]
        
        for base_path in fallback_bases:
            if base_path.is_dir():
                return base_path / str(appid)
        
        return None

    def verify_prefix_creation(self, prefix_path: Path) -> bool:
        """
        Verify that the prefix was created successfully.
        
        Args:
            prefix_path: Path to the prefix directory
            
        Returns:
            True if prefix is valid, False otherwise
        """
        try:
            logger.info(f"Verifying prefix: {prefix_path}")
            
            # Check if prefix exists and has proper structure
            if not prefix_path.exists():
                logger.error("Prefix directory does not exist")
                return False
            
            pfx_dir = prefix_path / "pfx"
            if not pfx_dir.exists():
                logger.error("Prefix exists but no pfx subdirectory")
                return False
            
            # Check for key Wine files
            system_reg = pfx_dir / "system.reg"
            user_reg = pfx_dir / "user.reg"
            drive_c = pfx_dir / "drive_c"
            
            if not system_reg.exists():
                logger.error("No system.reg found in prefix")
                return False
            
            if not user_reg.exists():
                logger.error("No user.reg found in prefix")
                return False
            
            if not drive_c.exists():
                logger.error("No drive_c directory found in prefix")
                return False
            
            logger.info("Prefix structure verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying prefix: {e}")
            return False

    def wait_for_prefix_completion(self, prefix_id: str, timeout: int = 60) -> bool:
        """
        Wait for system.reg to stop growing (indicates prefix creation is complete).
        
        Args:
            prefix_id: The Steam prefix ID to monitor
            timeout: Maximum seconds to wait
            
        Returns:
            True if prefix creation completed, False if timeout
        """
        try:
            prefix_path = Path.home() / f".local/share/Steam/steamapps/compatdata/{prefix_id}"
            system_reg = prefix_path / "pfx/system.reg"
            
            logger.info(f"Monitoring prefix completion: {system_reg}")
            
            last_size = 0
            stable_count = 0
            
            for i in range(timeout):
                if system_reg.exists():
                    current_size = system_reg.stat().st_size
                    logger.debug(f"system.reg size: {current_size} bytes")
                    
                    if current_size == last_size:
                        stable_count += 1
                        if stable_count >= 3:  # Stable for 3 seconds
                            logger.info(" system.reg size stable - prefix creation complete")
                            return True
                    else:
                        stable_count = 0
                        last_size = current_size
                
                time.sleep(1)
            
            logger.warning(f"Timeout waiting for prefix completion after {timeout} seconds")
            return False
            
        except Exception as e:
            logger.error(f"Error monitoring prefix completion: {e}")
            return False

    def create_prefix_with_proton_wrapper(self, appid: int) -> bool:
        """
        Create a Proton prefix directly using Proton's wrapper and STEAM_COMPAT_DATA_PATH.
        
        Args:
            appid: The AppID to create the prefix for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Determine Steam locations based on installation type
            from ..handlers.path_handler import PathHandler
            path_handler = PathHandler()
            all_libraries = path_handler.get_all_steam_library_paths()
            
            # Check if we have Flatpak Steam by looking for .var/app/com.valvesoftware.Steam in library paths
            is_flatpak_steam = any('.var/app/com.valvesoftware.Steam' in str(lib) for lib in all_libraries)
            
            if is_flatpak_steam and all_libraries:
                # Flatpak Steam: Use the actual library root from libraryfolders.vdf
                # Compatdata should be in the library root, not the client root
                flatpak_library_root = all_libraries[0]  # Use first library (typically the default)
                flatpak_client_root = flatpak_library_root.parent.parent / ".steam/steam"
                
                if not flatpak_library_root.is_dir():
                    logger.error(
                        f"Flatpak Steam library root does not exist: {flatpak_library_root}"
                    )
                    return False
                
                steam_root = flatpak_client_root if flatpak_client_root.is_dir() else flatpak_library_root
                # CRITICAL: compatdata must be in the library root, not client root
                compatdata_dir = flatpak_library_root / "steamapps/compatdata"
                proton_common_dir = flatpak_library_root / "steamapps/common"
            else:
                # Native Steam (or unknown): fall back to legacy ~/.steam/steam layout
                steam_root = Path.home() / ".steam/steam"
                compatdata_dir = steam_root / "steamapps/compatdata"
                proton_common_dir = steam_root / "steamapps/common"
            
            # Ensure compatdata root exists and is a directory we actually want to use
            if not compatdata_dir.is_dir():
                logger.error(f"Compatdata root does not exist: {compatdata_dir}. Aborting prefix creation.")
                return False
            
            # Find a Proton wrapper to use
            proton_path = self._find_proton_binary(proton_common_dir)
            if not proton_path:
                logger.error("No Proton wrapper found")
                return False
            
            # Set up environment variables
            env = os.environ.copy()
            env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = str(steam_root)
            env['STEAM_COMPAT_DATA_PATH'] = str(compatdata_dir / str(abs(appid)))
            # Suppress GUI windows using jackify-engine's proven approach
            env['DISPLAY'] = ''
            env['WAYLAND_DISPLAY'] = ''
            env['WINEDEBUG'] = '-all'
            env['WINEDLLOVERRIDES'] = 'msdia80.dll=n;conhost.exe=d;cmd.exe=d'
            
            # Create the compatdata directory for this AppID (but never the whole tree)
            compat_dir = compatdata_dir / str(abs(appid))
            compat_dir.mkdir(exist_ok=True)
            
            logger.info(f"Creating Proton prefix for AppID {appid}")
            logger.info(f"STEAM_COMPAT_CLIENT_INSTALL_PATH={env['STEAM_COMPAT_CLIENT_INSTALL_PATH']}")
            logger.info(f"STEAM_COMPAT_DATA_PATH={env['STEAM_COMPAT_DATA_PATH']}")
            
            # Run proton run wineboot -u to initialize the prefix
            cmd = [str(proton_path), 'run', 'wineboot', '-u']
            logger.info(f"Running: {' '.join(cmd)}")

            # Adjust timeout for SD card installations on Steam Deck (slower I/O)
            from ..services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            is_steamdeck_sdcard = (platform_service.is_steamdeck and
                                 str(proton_path).startswith('/run/media/'))
            timeout = 180 if is_steamdeck_sdcard else 60
            if is_steamdeck_sdcard:
                logger.info(f"Using extended timeout ({timeout}s) for Steam Deck SD card Proton installation")

            # Use jackify-engine's approach: UseShellExecute=false, CreateNoWindow=true equivalent
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout,
                                  shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            logger.info(f"Proton exit code: {result.returncode}")
            
            if result.stdout:
                logger.info(f"stdout: {result.stdout.strip()[:500]}")
            if result.stderr:
                logger.info(f"stderr: {result.stderr.strip()[:500]}")
            
            # Give a moment for files to land
            time.sleep(3)
            
            # Check if prefix was created
            pfx = compat_dir / 'pfx'
            if pfx.exists():
                logger.info(f" Proton prefix created at: {pfx}")
                return True
            else:
                logger.warning(f"Proton prefix not found at: {pfx}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("Proton timed out; prefix may still be initializing")
            return False
        except Exception as e:
            logger.error(f"Error creating prefix: {e}")
            return False

