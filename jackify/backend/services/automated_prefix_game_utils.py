#!/usr/bin/env python3
"""
Game utilities mixin for AutomatedPrefixService.

Handles game-specific operations:
- Launch options generation
- Game detection
- User directory creation
- Proton version preferences
"""
import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class GameUtilsMixin:
    """Mixin for game-related utility operations"""

    def _generate_special_game_launch_options(self, special_game_type: str, modlist_install_dir: str) -> Optional[str]:
        """
        Generate launch options for FNV/Enderal games that require vanilla compatdata.
        
        Args:
            special_game_type: "fnv" or "enderal"
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            Complete launch options string with STEAM_COMPAT_DATA_PATH, or None if failed
        """
        if not special_game_type or special_game_type not in ["fnv", "enderal"]:
            return None
            
        logger.info(f"Generating {special_game_type.upper()} launch options")
        
        # Map game types to AppIDs
        appid_map = {"fnv": "22380", "enderal": "976620"}
        appid = appid_map[special_game_type]
        
        # Find vanilla game compatdata
        from ..handlers.path_handler import PathHandler
        compatdata_path = PathHandler.find_compat_data(appid)
        if not compatdata_path:
            logger.error(f"Could not find vanilla {special_game_type.upper()} compatdata directory (AppID {appid})")
            return None
            
        # Create STEAM_COMPAT_DATA_PATH string
        compat_data_str = f'STEAM_COMPAT_DATA_PATH="{compatdata_path}"'
        
        # Generate STEAM_COMPAT_MOUNTS if multiple libraries exist
        compat_mounts_str = ""
        try:
            all_libs = PathHandler.get_all_steam_library_paths()
            main_steam_lib_path_obj = PathHandler.find_steam_library()
            if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
                main_steam_lib_path = main_steam_lib_path_obj.parent.parent
            else:
                main_steam_lib_path = main_steam_lib_path_obj
                
            mount_paths = []
            if main_steam_lib_path:
                main_resolved = main_steam_lib_path.resolve()
                for lib_path in all_libs:
                    if lib_path.resolve() != main_resolved:
                        mount_paths.append(str(lib_path.resolve()))
                        
            if mount_paths:
                mount_paths_str = ':'.join(mount_paths)
                compat_mounts_str = f'STEAM_COMPAT_MOUNTS="{mount_paths_str}"'
                logger.info(f"Added STEAM_COMPAT_MOUNTS for {special_game_type.upper()}")
        except Exception as e:
            logger.warning(f"Error generating STEAM_COMPAT_MOUNTS for {special_game_type}: {e}")
            
        # Combine all launch options
        launch_options = f"{compat_mounts_str} {compat_data_str} %command%".strip()
        launch_options = ' '.join(launch_options.split())  # Clean up spacing
        
        logger.info(f"Generated {special_game_type.upper()} launch options: {launch_options}")
        return launch_options

    def _find_steam_game(self, app_id: str, common_names: list) -> Optional[str]:
        """Find a Steam game installation path by AppID and common names"""
        import os
        from pathlib import Path

        # Get Steam libraries from libraryfolders.vdf - check multiple possible locations
        possible_config_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf"  # Flatpak
        ]

        steam_config_path = None
        for path in possible_config_paths:
            if path.exists():
                steam_config_path = path
                break

        if not steam_config_path:
            return None
            
        steam_libraries = []
        try:
            with open(steam_config_path, 'r') as f:
                content = f.read()
                # Parse library paths from VDF
                import re
                library_matches = re.findall(r'"path"\s+"([^"]+)"', content)
                steam_libraries = [Path(path) / "steamapps" / "common" for path in library_matches]
        except Exception as e:
            logger.warning(f"Failed to parse Steam library folders: {e}")
            return None
        
        # Search for game in each library
        for library_path in steam_libraries:
            if not library_path.exists():
                continue
                
            # Check manifest file first (more reliable)
            manifest_path = library_path.parent / "appmanifest_{}.acf".format(app_id)
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r') as f:
                        content = f.read()
                        install_dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                        if install_dir_match:
                            game_path = library_path / install_dir_match.group(1)
                            if game_path.exists():
                                return str(game_path)
                except Exception:
                    pass
            
            # Fallback: check common folder names
            for name in common_names:
                game_path = library_path / name
                if game_path.exists():
                    return str(game_path)
                    
        return None

    def _create_game_user_directories(self, modlist_compatdata_path: str, special_game_type: str):
        """
        Pre-create game-specific user directories to prevent first-launch issues.

        Creates both My Documents/My Games and AppData/Local directories for the game.
        This prevents issues where games fail to create these on first launch under Proton.
        """
        # Map game types to their directory names
        game_dir_names = {
            "skyrim": "Skyrim Special Edition",
            "fnv": "FalloutNV",
            "fo3": "Fallout3",
            "fo4": "Fallout4",
            "oblivion": "Oblivion",
            "oblivion_remastered": "Oblivion Remastered",
            "enderal": "Enderal Special Edition",
            "starfield": "Starfield"
        }

        # Get the directory name for this game type
        game_dir_name = game_dir_names.get(special_game_type)
        if not game_dir_name:
            logger.debug(f"No user directory mapping for game type: {special_game_type}")
            return

        base_path = os.path.join(modlist_compatdata_path, "pfx", "drive_c", "users", "steamuser")

        directories_to_create = [
            os.path.join(base_path, "Documents", "My Games", game_dir_name),
            os.path.join(base_path, "AppData", "Local", game_dir_name)
        ]

        created_count = 0
        for directory in directories_to_create:
            try:
                os.makedirs(directory, exist_ok=True)
                logger.info(f"Created user directory: {directory}")
                created_count += 1
            except Exception as e:
                logger.warning(f"Failed to create directory {directory}: {e}")

        if created_count > 0:
            logger.info(f"Created {created_count} user directories for {game_dir_name}")

    def _get_lorerim_preferred_proton(self):
        """Get Lorerim's preferred Proton 9 version with specific priority order"""
        try:
            from jackify.backend.handlers.wine_utils import WineUtils

            # Get all available Proton versions
            available_versions = WineUtils.scan_all_proton_versions()

            if not available_versions:
                logger.warning("No Proton versions found for Lorerim override")
                return None

            # Priority order for Lorerim:
            # 1. GEProton9-27 (specific version)
            # 2. Other GEProton-9 versions (latest first)
            # 3. Valve Proton 9 (any version)

            preferred_candidates = []

            for version in available_versions:
                version_name = version['name']

                # Priority 1: GEProton9-27 specifically
                if version_name == 'GE-Proton9-27':
                    logger.info(f"Lorerim: Found preferred GE-Proton9-27")
                    return version_name

                # Priority 2: Other GE-Proton 9 versions
                elif version_name.startswith('GE-Proton9-'):
                    preferred_candidates.append(('ge_proton_9', version_name, version))

                # Priority 3: Valve Proton 9
                elif 'Proton 9' in version_name:
                    preferred_candidates.append(('valve_proton_9', version_name, version))

            # Return best candidate if any found
            if preferred_candidates:
                # Sort by priority (GE-Proton first, then by name for latest)
                preferred_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
                best_candidate = preferred_candidates[0]
                logger.info(f"Lorerim: Selected {best_candidate[1]} as best Proton 9 option")
                return best_candidate[1]

            logger.warning("Lorerim: No suitable Proton 9 versions found, will use user settings")
            return None

        except Exception as e:
            logger.error(f"Error detecting Lorerim Proton preference: {e}")
            return None

    def _store_proton_override_notification(self, modlist_name: str, proton_version: str):
        """Store Proton override information for end-of-install notification"""
        try:
            # Store override info for later display
            if not hasattr(self, '_proton_overrides'):
                self._proton_overrides = []

            self._proton_overrides.append({
                'modlist': modlist_name,
                'proton_version': proton_version,
                'reason': f'{modlist_name} requires Proton 9 for optimal compatibility'
            })

            logger.debug(f"Stored Proton override notification: {modlist_name} → {proton_version}")

        except Exception as e:
            logger.error(f"Failed to store Proton override notification: {e}")

    def _show_proton_override_notification(self, progress_callback=None):
        """Display any Proton override notifications to the user"""
        try:
            if hasattr(self, '_proton_overrides') and self._proton_overrides:
                for override in self._proton_overrides:
                    notification_msg = f"PROTON OVERRIDE: {override['modlist']} configured to use {override['proton_version']} for optimal compatibility"

                    if progress_callback:
                        progress_callback("")
                        progress_callback(f"{self._get_progress_timestamp()} {notification_msg}")

                    logger.info(notification_msg)

                # Clear notifications after display
                self._proton_overrides = []

        except Exception as e:
            logger.error(f"Failed to show Proton override notification: {e}")

