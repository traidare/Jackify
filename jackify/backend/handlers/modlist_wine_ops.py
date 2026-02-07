"""Wine/Proton operation methods for ModlistHandler (Mixin)."""
from pathlib import Path
from typing import Tuple, Optional, List
import os
import logging
import subprocess
import shutil
import time
import vdf
import json
import configparser

logger = logging.getLogger(__name__)


class ModlistWineOpsMixin:
    """Mixin providing Wine and Proton operation methods for ModlistHandler."""

    def verify_proton_setup(self, appid_to_check: str) -> Tuple[bool, str]:
        """Verifies that Proton is correctly set up for a given AppID.

        Checks config.vdf for Proton Experimental and existence of compatdata/pfx dir.

        Args:
            appid_to_check: The AppID string to verify.

        Returns:
            tuple: (bool success, str status_code)
                   Status codes: 'ok', 'invalid_appid', 'config_vdf_missing', 
                                 'config_vdf_error', 'proton_check_failed', 
                                 'wrong_proton_version', 'compatdata_missing',
                                 'prefix_missing'
        """
        self.logger.info(f"Verifying Proton setup for AppID: {appid_to_check}")
        
        if not appid_to_check or not appid_to_check.isdigit():
            self.logger.error("Invalid AppID provided for verification.")
            return False, 'invalid_appid'

        proton_tool_name = None
        compatdata_path_found = None
        prefix_exists = False

        # 1. Find and Parse config.vdf
        config_vdf_path = None
        possible_steam_paths = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/root"
        ]
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                config_vdf_path = potential_path
                self.logger.debug(f"Found config.vdf at: {config_vdf_path}")
                break
        
        if not config_vdf_path:
            self.logger.error("Could not locate Steam's config.vdf file.")
            return False, 'config_vdf_missing'

        # Add a short delay to allow Steam to potentially finish writing changes
        self.logger.debug("Waiting 2 seconds before reading config.vdf...")
        time.sleep(2)

        try:
            self.logger.debug(f"Attempting to load VDF file: {config_vdf_path}")
            # CORRECTION: Use the vdf library directly here, not VDFHandler
            with open(str(config_vdf_path), 'r') as f:
                 config_data = vdf.load(f, mapper=vdf.VDFDict)

            # --- Write full config.vdf to a debug file ---
            debug_dump_path = os.path.expanduser("~/dev/Jackify/configvdf_dump.txt")
            with open(debug_dump_path, "w") as dump_f:
                json.dump(config_data, dump_f, indent=2)
            self.logger.info(f"Full config.vdf dumped to {debug_dump_path}")

            # --- Log only the relevant section for this AppID ---
            steam_config_section = config_data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {})
            compat_mapping = steam_config_section.get('CompatToolMapping', {})
            app_mapping = compat_mapping.get(appid_to_check, {})
            self.logger.debug("───────────────────────────────────────────────────────────────────")
            self.logger.debug(f"Config.vdf entry for AppID {appid_to_check} (CompatToolMapping):")
            self.logger.debug(json.dumps({appid_to_check: app_mapping}, indent=2))
            self.logger.debug("───────────────────────────────────────────────────────────────────")
            self.logger.debug(f"Steam config section from VDF: {json.dumps(steam_config_section, indent=2)}")
            # --- End Debugging ---
            
            # Navigate the structure: Software -> Valve -> Steam -> CompatToolMapping -> appid_to_check -> Name
            compat_mapping = steam_config_section.get('CompatToolMapping', {})
            app_mapping = compat_mapping.get(appid_to_check, {})
            proton_tool_name = app_mapping.get('name') # CORRECTED: Use lowercase 'name'
            self.proton_ver = proton_tool_name # Store detected version
            
            if proton_tool_name:
                self.logger.info(f"Proton tool name from config.vdf: {proton_tool_name}")
            else:
                 self.logger.warning(f"CompatToolMapping entry not found for AppID {appid_to_check} in config.vdf.")
                 # Add more debug info here about what *was* found
                 self.logger.debug(f"CompatToolMapping contents: {json.dumps(compat_mapping.get(appid_to_check, 'Key not found'), indent=2)}")
                 return False, 'proton_check_failed' # Compatibility not explicitly set

        except FileNotFoundError:
            self.logger.error(f"Config.vdf file not found during load attempt: {config_vdf_path}")
            return False, 'config_vdf_missing'
        except Exception as e:
            self.logger.error(f"Error parsing config.vdf: {e}", exc_info=True)
            return False, 'config_vdf_error'

        # 2. Check if the correct Proton version is set (allowing variations)
        # Target: Proton Experimental
        if not proton_tool_name or 'experimental' not in proton_tool_name.lower():
            self.logger.warning(f"Incorrect Proton version detected: '{proton_tool_name}'. Expected 'Proton Experimental'.")
            return False, 'wrong_proton_version'
        
        self.logger.info("Proton version check passed ('Proton Experimental' set).")

        # 3. Check for compatdata / prefix directory existence
        possible_compat_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
             # Add SD card paths if necessary / detectable
             # Path("/run/media/mmcblk0p1/steamapps/compatdata") # Example
        ]
        
        compat_dir_found = False
        for base_path in possible_compat_bases:
            potential_compat_path = base_path / appid_to_check
            if potential_compat_path.is_dir():
                self.logger.debug(f"Found compatdata directory: {potential_compat_path}")
                compat_dir_found = True
                # Check for prefix *within* the found compatdata dir
                prefix_path = potential_compat_path / "pfx"
                if prefix_path.is_dir():
                     self.logger.info(f"Wine prefix directory verified: {prefix_path}")
                     prefix_exists = True
                     break # Found both compatdata and prefix, exit loop
                else:
                     self.logger.warning(f"Compatdata directory found, but prefix missing: {prefix_path}")
                     # Keep searching other base paths in case prefix exists elsewhere
            
        if not compat_dir_found:
             self.logger.error(f"Compatdata directory not found for AppID {appid_to_check} in standard locations.")
             return False, 'compatdata_missing'
             
        if not prefix_exists:
             # Found compatdata but no pfx inside any of them
             self.logger.error(f"Wine prefix directory (pfx) not found within any located compatdata directory for AppID {appid_to_check}.")
             return False, 'prefix_missing'

        # All checks passed
        self.logger.info(f"Proton setup verification successful for AppID {appid_to_check}.")
        return True, 'ok'

    def set_steam_grid_images(self, appid: str, modlist_dir: str):
        """
        Copies hero, logo, and poster images from the modlist's SteamIcons directory
        to the grid directory of all non-zero Steam user directories, named after the new AppID.
        """
        steam_icons_dir = Path(modlist_dir) / "SteamIcons"
        if not steam_icons_dir.is_dir():
            self.logger.info(f"No SteamIcons directory found at {steam_icons_dir}, skipping grid image copy.")
            return

        # Find all non-zero Steam user directories
        userdata_base = Path.home() / ".steam/steam/userdata"
        if not userdata_base.is_dir():
            self.logger.error(f"Steam userdata directory not found at {userdata_base}")
            return

        for user_dir in userdata_base.iterdir():
            if not user_dir.is_dir() or user_dir.name == "0":
                continue
            grid_dir = user_dir / "config/grid"
            grid_dir.mkdir(parents=True, exist_ok=True)

            images = [
                ("grid-hero.png", f"{appid}_hero.png"),
                ("grid-logo.png", f"{appid}_logo.png"),
                ("grid-tall.png", f"{appid}.png"),
                ("grid-tall.png", f"{appid}p.png"),
            ]

            for src_name, dest_name in images:
                src_path = steam_icons_dir / src_name
                dest_path = grid_dir / dest_name
                if src_path.exists():
                    try:
                        shutil.copyfile(src_path, dest_path)
                        self.logger.info(f"Copied {src_path} to {dest_path}")
                    except Exception as e:
                        self.logger.error(f"Failed to copy {src_path} to {dest_path}: {e}")
                else:
                    self.logger.warning(f"Image {src_path} not found; skipping.")

    def get_modlist_wine_components(self, modlist_name, game_var_full=None):
        """
        Returns the full list of Wine components to install for a given modlist/game.
        - Always includes the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022)
        - Adds game-specific extras (from bash script logic)
        - Adds any modlist-specific extras (from MODLIST_WINE_COMPONENTS)
        """
        default_components = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
        extras = []
        # Determine game type
        game = (game_var_full or modlist_name or "").lower().replace(" ", "")
        # Add game-specific extras
        if "skyrim" in game or "fallout4" in game or "starfield" in game or "oblivion_remastered" in game or "enderal" in game:
            extras += ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7"]
        elif "falloutnewvegas" in game or "fnv" in game or "oblivion" in game:
            extras += ["d3dx9_43", "d3dx9"]
        # Add modlist-specific extras
        modlist_lower = modlist_name.lower().replace(" ", "") if modlist_name else ""
        for key, components in self.MODLIST_WINE_COMPONENTS.items():
            if key in modlist_lower:
                extras += components
        # Remove duplicates while preserving order
        seen = set()
        full_list = [x for x in default_components + extras if not (x in seen or seen.add(x))]
        return full_list

    def _re_enforce_windows_10_mode(self):
        """
        Re-enforce Windows 10 mode after modlist-specific configurations.
        This matches the legacy script behavior (line 1333) where Windows 10 mode
        is re-applied after modlist-specific steps to ensure consistency.
        """
        try:
            if not hasattr(self, 'appid') or not self.appid:
                self.logger.warning("Cannot re-enforce Windows 10 mode - no AppID available")
                return

            from ..handlers.winetricks_handler import WinetricksHandler
            from ..handlers.path_handler import PathHandler

            # Get prefix path for the AppID
            prefix_path = PathHandler.find_compat_data(str(self.appid))
            if not prefix_path:
                self.logger.warning("Cannot re-enforce Windows 10 mode - prefix path not found")
                return

            # Use winetricks handler to set Windows 10 mode
            winetricks_handler = WinetricksHandler()
            wine_binary = winetricks_handler._get_wine_binary_for_prefix(str(prefix_path))
            if not wine_binary:
                self.logger.warning("Cannot re-enforce Windows 10 mode - wine binary not found")
                return

            winetricks_handler._set_windows_10_mode(str(prefix_path), wine_binary)

            self.logger.info("Windows 10 mode re-enforced after modlist-specific configurations")

        except Exception as e:
            self.logger.warning(f"Error re-enforcing Windows 10 mode: {e}")

    def _handle_symlinked_downloads(self) -> bool:
        """
        Check if downloads_directory in ModOrganizer.ini points to a symlink.
        If it does, comment out the line to force MO2 to use default behavior.

        Returns:
            bool: True on success or no action needed, False on error
        """
        try:
            if not self.modlist_ini or not os.path.exists(self.modlist_ini):
                self.logger.warning("ModOrganizer.ini not found for symlink check")
                return True  # Non-critical

            # Read the INI file
            # Allow duplicate sections/keys since some ModOrganizer.ini variants repeat [General]
            # Latest occurrence wins, which matches how we only need the final downloads_directory value.
            config = configparser.ConfigParser(allow_no_value=True, delimiters=['='], strict=False)
            config.optionxform = str  # Preserve case sensitivity

            try:
                # Read file manually to handle BOM
                with open(self.modlist_ini, 'r', encoding='utf-8-sig') as f:
                    config.read_file(f)
            except UnicodeDecodeError:
                with open(self.modlist_ini, 'r', encoding='latin-1') as f:
                    config.read_file(f)

            # Check if downloads_directory or download_directory exists and is a symlink
            downloads_key = None
            downloads_path = None

            if 'General' in config:
                # Check for both possible key names
                if 'downloads_directory' in config['General']:
                    downloads_key = 'downloads_directory'
                    downloads_path = config['General']['downloads_directory']
                elif 'download_directory' in config['General']:
                    downloads_key = 'download_directory'
                    downloads_path = config['General']['download_directory']

            if downloads_path:

                if downloads_path and os.path.exists(downloads_path):
                    # Check if the path or any parent directory contains symlinks
                    def has_symlink_in_path(path):
                        """Check if path or any parent directory is a symlink"""
                        current_path = Path(path).resolve()
                        check_path = Path(path)

                        # Walk up the path checking each component
                        for parent in [check_path] + list(check_path.parents):
                            if parent.is_symlink():
                                return True, str(parent)
                        return False, None

                    has_symlink, symlink_path = has_symlink_in_path(downloads_path)
                    if has_symlink:
                        self.logger.info(f"Detected symlink in downloads directory path: {symlink_path} -> {downloads_path}")
                        self.logger.info("Commenting out downloads_directory to avoid Wine symlink issues")

                        # Read the file manually to preserve comments and formatting
                        with open(self.modlist_ini, 'r', encoding='utf-8') as f:
                            lines = f.readlines()

                        # Find and comment out the downloads directory line
                        modified = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith(f'{downloads_key}='):
                                lines[i] = '#' + line  # Comment out the line
                                modified = True
                                break

                        if modified:
                            # Write the modified file back
                            with open(self.modlist_ini, 'w', encoding='utf-8') as f:
                                f.writelines(lines)
                            self.logger.info(f"{downloads_key} line commented out successfully")
                        else:
                            self.logger.warning("downloads_directory line not found in file")
                    else:
                        self.logger.debug(f"downloads_directory is not a symlink: {downloads_path}")
                else:
                    self.logger.debug("downloads_directory path does not exist or is empty")
            else:
                self.logger.debug("No downloads_directory found in ModOrganizer.ini")

            return True

        except Exception as e:
            self.logger.error(f"Error handling symlinked downloads: {e}", exc_info=True)
            return False

    def _apply_universal_dotnet_fixes(self):
        """
        Apply universal dotnet4.x compatibility registry fixes to ALL modlists.
        Now called AFTER wine component installation to prevent overwrites.
        Includes wineserver shutdown/flush to ensure persistence.
        """
        try:
            prefix_path = os.path.join(str(self.compat_data_path), "pfx")
            if not os.path.exists(prefix_path):
                self.logger.warning(f"Prefix path not found: {prefix_path}")
                return False

            self.logger.info("Applying universal dotnet4.x compatibility registry fixes (post-component installation)...")

            # Find the appropriate Wine binary to use for registry operations
            wine_binary = self._find_wine_binary_for_registry()
            if not wine_binary:
                self.logger.error("Could not find Wine binary for registry operations")
                return False

            # Find wineserver binary for flushing registry changes
            wine_dir = os.path.dirname(wine_binary)
            wineserver_binary = os.path.join(wine_dir, 'wineserver')
            if not os.path.exists(wineserver_binary):
                self.logger.warning(f"wineserver not found at {wineserver_binary}, registry flush may not work")
                wineserver_binary = None

            # Set environment for Wine registry operations
            env = os.environ.copy()
            env['WINEPREFIX'] = prefix_path
            env['WINEDEBUG'] = '-all'  # Suppress Wine debug output

            # Shutdown any running wineserver processes to ensure clean slate
            if wineserver_binary:
                self.logger.debug("Shutting down wineserver before applying registry fixes...")
                try:
                    subprocess.run([wineserver_binary, '-w'], env=env, timeout=30, capture_output=True)
                    self.logger.debug("Wineserver shutdown complete")
                except Exception as e:
                    self.logger.warning(f"Wineserver shutdown failed (non-critical): {e}")

            # Registry fix 1: Set *mscoree=native DLL override (asterisk for full override)
            # Use native .NET runtime instead of Wine's
            self.logger.debug("Setting *mscoree=native DLL override...")
            cmd1 = [
                wine_binary, 'reg', 'add',
                'HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides',
                '/v', '*mscoree', '/t', 'REG_SZ', '/d', 'native', '/f'
            ]

            result1 = subprocess.run(cmd1, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            self.logger.info(f"*mscoree registry command result: returncode={result1.returncode}, stdout={result1.stdout[:200]}, stderr={result1.stderr[:200]}")
            if result1.returncode == 0:
                self.logger.info("Successfully applied *mscoree=native DLL override")
            else:
                self.logger.error(f"Failed to set *mscoree DLL override: returncode={result1.returncode}, stderr={result1.stderr}")

            # Registry fix 2: Set OnlyUseLatestCLR=1
            # Use latest CLR to avoid .NET version conflicts
            self.logger.debug("Setting OnlyUseLatestCLR=1 registry entry...")
            cmd2 = [
                wine_binary, 'reg', 'add',
                'HKEY_LOCAL_MACHINE\\Software\\Microsoft\\.NETFramework',
                '/v', 'OnlyUseLatestCLR', '/t', 'REG_DWORD', '/d', '1', '/f'
            ]

            result2 = subprocess.run(cmd2, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            self.logger.info(f"OnlyUseLatestCLR registry command result: returncode={result2.returncode}, stdout={result2.stdout[:200]}, stderr={result2.stderr[:200]}")
            if result2.returncode == 0:
                self.logger.info("Successfully applied OnlyUseLatestCLR=1 registry entry")
            else:
                self.logger.error(f"Failed to set OnlyUseLatestCLR: returncode={result2.returncode}, stderr={result2.stderr}")

            # Force wineserver to flush registry changes to disk
            if wineserver_binary:
                self.logger.debug("Flushing registry changes to disk via wineserver shutdown...")
                try:
                    subprocess.run([wineserver_binary, '-w'], env=env, timeout=30, capture_output=True)
                    self.logger.debug("Registry changes flushed to disk")
                except Exception as e:
                    self.logger.warning(f"Registry flush failed (non-critical): {e}")

            # VERIFICATION: Confirm the registry entries persisted
            self.logger.info("Verifying registry entries were applied and persisted...")
            verification_passed = True

            # Verify *mscoree=native
            verify_cmd1 = [
                wine_binary, 'reg', 'query',
                'HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides',
                '/v', '*mscoree'
            ]
            verify_result1 = subprocess.run(verify_cmd1, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            if verify_result1.returncode == 0 and 'native' in verify_result1.stdout:
                self.logger.info("VERIFIED: *mscoree=native is set correctly")
            else:
                self.logger.error(f"VERIFICATION FAILED: *mscoree=native not found in registry. Query output: {verify_result1.stdout}")
                verification_passed = False

            # Verify OnlyUseLatestCLR=1
            verify_cmd2 = [
                wine_binary, 'reg', 'query',
                'HKEY_LOCAL_MACHINE\\Software\\Microsoft\\.NETFramework',
                '/v', 'OnlyUseLatestCLR'
            ]
            verify_result2 = subprocess.run(verify_cmd2, env=env, capture_output=True, text=True, errors='replace', timeout=30)
            if verify_result2.returncode == 0 and ('0x1' in verify_result2.stdout or 'REG_DWORD' in verify_result2.stdout):
                self.logger.info("VERIFIED: OnlyUseLatestCLR=1 is set correctly")
            else:
                self.logger.error(f"VERIFICATION FAILED: OnlyUseLatestCLR=1 not found in registry. Query output: {verify_result2.stdout}")
                verification_passed = False

            # Both fixes applied and verified
            if result1.returncode == 0 and result2.returncode == 0 and verification_passed:
                self.logger.info("Universal dotnet4.x compatibility fixes applied, flushed, and verified successfully")
                return True
            else:
                self.logger.error("Registry fixes failed verification - fixes may not persist across prefix restarts")
                return False

        except Exception as e:
            self.logger.error(f"Failed to apply universal dotnet4.x fixes: {e}")
            return False

    def _find_wine_binary_for_registry(self) -> Optional[str]:
        """Find wine binary from Install Proton path"""
        try:
            # Use Install Proton from config (used by jackify-engine)
            from ..handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            proton_path = config_handler.get_proton_path()

            if proton_path:
                proton_path = Path(proton_path).expanduser()

                # Check both GE-Proton and Valve Proton structures
                wine_candidates = [
                    proton_path / "files" / "bin" / "wine",  # GE-Proton
                    proton_path / "dist" / "bin" / "wine"    # Valve Proton
                ]

                for wine_bin in wine_candidates:
                    if wine_bin.exists() and wine_bin.is_file():
                        return str(wine_bin)

            # Fallback: use best detected Proton
            from ..handlers.wine_utils import WineUtils
            best_proton = WineUtils.select_best_proton()
            if best_proton:
                wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                if wine_binary:
                    return wine_binary

            return None
        except Exception as e:
            self.logger.error(f"Error finding Wine binary: {e}")
            return None

    def _search_wine_in_proton_directory(self, proton_path: Path) -> Optional[str]:
        """
        Recursively search for wine binary within a Proton directory.
        This handles cases where the directory structure might differ between Proton versions.
        
        Args:
            proton_path: Path to the Proton directory to search
            
        Returns:
            Path to wine binary if found, None otherwise
        """
        try:
            if not proton_path.exists() or not proton_path.is_dir():
                return None

            # Search for 'wine' executable (not 'wine64' or 'wine-preloader')
            # Limit search depth to avoid scanning entire filesystem
            max_depth = 5
            for root, dirs, files in os.walk(proton_path, followlinks=False):
                # Calculate depth relative to proton_path
                depth = len(Path(root).relative_to(proton_path).parts)
                if depth > max_depth:
                    dirs.clear()  # Don't descend further
                    continue
                
                # Check if 'wine' is in this directory
                if 'wine' in files:
                    wine_path = Path(root) / 'wine'
                    # Verify it's actually an executable file
                    if wine_path.is_file() and os.access(wine_path, os.X_OK):
                        self.logger.debug(f"Found wine binary at: {wine_path}")
                        return str(wine_path)

            return None
        except Exception as e:
            self.logger.debug(f"Error during recursive wine search in {proton_path}: {e}")
            return None

