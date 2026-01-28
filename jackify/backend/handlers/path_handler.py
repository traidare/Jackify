#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path Handler Module
Handles path-related operations for ModOrganizer.ini and other configuration files
"""

import os
import re
import logging
import shutil
from pathlib import Path
from typing import Optional, Union, Dict, Any, List, Tuple
from datetime import datetime
import vdf

# Initialize logger
logger = logging.getLogger(__name__)

# --- Configuration (Adapted from Proposal) ---
# Define known script extender executables (lowercase for comparisons)
TARGET_EXECUTABLES_LOWER = ["skse64_loader.exe", "f4se_loader.exe", "nvse_loader.exe", "obse_loader.exe", "sfse_loader.exe", "obse64_loader.exe", "falloutnv.exe"]
# Define known stock game folder names (case-sensitive, as they appear on disk)
STOCK_GAME_FOLDERS = ["Stock Game", "Game Root", "Stock Folder", "Skyrim Stock"]
# Define the SD card path prefix on Steam Deck/Linux
SDCARD_PREFIX = '/run/media/mmcblk0p1/'

class PathHandler:
    """
    Handles path-related operations for ModOrganizer.ini and other configuration files
    """
    
    @staticmethod
    def _strip_sdcard_path_prefix(path_obj: Path) -> str:
        """
        Removes any detected SD card mount prefix dynamically.
        Handles both /run/media/mmcblk0p1 and /run/media/deck/UUID patterns.
        Returns the path as a POSIX-style string (using /).
        """
        from .wine_utils import WineUtils

        path_str = path_obj.as_posix()  # Work with consistent forward slashes

        # Use dynamic SD card detection from WineUtils
        stripped_path = WineUtils._strip_sdcard_path(path_str)

        if stripped_path != path_str:
            # Path was stripped, remove leading slash for relative path
            return stripped_path.lstrip('/') if stripped_path != '/' else '.'

        return path_str

    @staticmethod
    def update_mo2_ini_paths(
        modlist_ini_path: Path,
        modlist_dir_path: Path,
        modlist_sdcard: bool,
        steam_library_common_path: Optional[Path] = None,
        basegame_dir_name: Optional[str] = None,
        basegame_sdcard: bool = False # Default to False if not provided
    ) -> bool:
        logger.info(f"[DEBUG] update_mo2_ini_paths called with: modlist_ini_path={modlist_ini_path}, modlist_dir_path={modlist_dir_path}, modlist_sdcard={modlist_sdcard}, steam_library_common_path={steam_library_common_path}, basegame_dir_name={basegame_dir_name}, basegame_sdcard={basegame_sdcard}")
        if not modlist_ini_path.is_file():
            logger.error(f"ModOrganizer.ini not found at specified path: {modlist_ini_path}")
            # Attempt to create a minimal INI
            try:
                logger.warning("Creating minimal ModOrganizer.ini with [General] section.")
                with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                    f.write('[General]\n')
                # Continue as if file existed
            except Exception as e:
                logger.critical(f"Failed to create minimal ModOrganizer.ini: {e}")
                return False
        if not modlist_dir_path.is_dir():
            logger.error(f"Modlist directory not found or not a directory: {modlist_dir_path}")
            # Warn but continue
        
        # --- Bulletproof game directory detection ---
        # 1. Get all Steam libraries and log them
        all_steam_libraries = PathHandler.get_all_steam_library_paths()
        logger.info(f"[DEBUG] Detected Steam libraries: {all_steam_libraries}")
        import sys
        if hasattr(sys, 'argv') and any(arg in ('--debug', '-d') for arg in sys.argv):
            self.logger.debug(f"Detected Steam libraries: {all_steam_libraries}")

        # 2. For each library, check for the canonical vanilla game directory
        GAME_DIR_NAMES = {
            "Skyrim Special Edition": "Skyrim Special Edition",
            "Fallout 4": "Fallout 4",
            "Fallout New Vegas": "Fallout New Vegas",
            "Oblivion": "Oblivion"
        }
        canonical_name = None
        if basegame_dir_name and basegame_dir_name in GAME_DIR_NAMES:
            canonical_name = GAME_DIR_NAMES[basegame_dir_name]
        elif basegame_dir_name:
            canonical_name = basegame_dir_name # fallback, but should match above
        gamepath_target_dir = None
        gamepath_target_is_sdcard = modlist_sdcard
        checked_candidates = []
        if canonical_name:
            for lib in all_steam_libraries:
                candidate = lib / "steamapps" / "common" / canonical_name
                checked_candidates.append(str(candidate))
                logger.info(f"[DEBUG] Checking for vanilla game directory: {candidate}")
                if candidate.is_dir():
                    gamepath_target_dir = candidate
                    logger.info(f"Found vanilla game directory: {candidate}")
                    break
        if not gamepath_target_dir:
            logger.error(f"Could not find vanilla game directory '{canonical_name}' in any Steam library. Checked: {checked_candidates}")
            # 4. Prompt the user for the path
            print("\nCould not automatically detect a Stock Game or vanilla game directory.")
            print("Please enter the full path to your vanilla game directory (e.g., /path/to/Skyrim Special Edition):")
            while True:
                user_input = input("Game directory path: ").strip()
                user_path = Path(user_input)
                logger.info(f"[DEBUG] User entered: {user_input}")
                if user_path.is_dir():
                    exe_candidates = list(user_path.glob('*.exe'))
                    logger.info(f"[DEBUG] .exe files in user path: {exe_candidates}")
                    if exe_candidates:
                        gamepath_target_dir = user_path
                        logger.info(f"User provided valid vanilla game directory: {gamepath_target_dir}")
                        break
                    else:
                        print("Directory exists but does not appear to contain the game executable. Please check and try again.")
                        logger.warning("User path exists but no .exe files found.")
                else:
                    print("Directory not found. Please enter a valid path.")
                    logger.warning("User path does not exist.")
        if not gamepath_target_dir:
            logger.critical("[FATAL] Could not determine a valid target directory for gamePath. Check configuration and paths. Aborting update.")
            return False

        # 3. Update gamePath, binary, and workingDirectory entries in the INI
        logger.debug(f"Determined gamePath target directory: {gamepath_target_dir}")
        logger.debug(f"gamePath target is on SD card: {gamepath_target_is_sdcard}")
        try:
            logger.debug(f"Reading original INI file: {modlist_ini_path}")
            with open(modlist_ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_lines = f.readlines()

            # --- Find and robustly update gamePath line ---
            gamepath_line_num = -1
            general_section_line = -1
            for i, line in enumerate(original_lines):
                if re.match(r'^\s*\[General\]\s*$', line, re.IGNORECASE):
                    general_section_line = i
                if re.match(r'^\s*gamepath\s*=\s*', line, re.IGNORECASE):
                    gamepath_line_num = i
                    break
            processed_str = PathHandler._strip_sdcard_path_prefix(gamepath_target_dir)
            windows_style_single = processed_str.replace('/', '\\')
            gamepath_drive_letter = "D:" if gamepath_target_is_sdcard else "Z:"
            # Use robust formatter
            formatted_gamepath = PathHandler._format_gamepath_for_mo2(f'{gamepath_drive_letter}{windows_style_single}')
            new_gamepath_line = f'gamePath = @ByteArray({formatted_gamepath})\n'
            if gamepath_line_num != -1:
                logger.info(f"Updating existing gamePath line: {original_lines[gamepath_line_num].strip()} -> {new_gamepath_line.strip()}")
                original_lines[gamepath_line_num] = new_gamepath_line
            else:
                insert_at = general_section_line + 1 if general_section_line != -1 else 0
                logger.info(f"Adding missing gamePath line at line {insert_at+1}: {new_gamepath_line.strip()}")
                original_lines.insert(insert_at, new_gamepath_line)

            # --- Update customExecutables binaries and workingDirectories ---
            TARGET_EXECUTABLES_LOWER = [
                "skse64_loader.exe", "f4se_loader.exe", "nvse_loader.exe", "obse_loader.exe", "falloutnv.exe"
            ]
            in_custom_exec = False
            for i, line in enumerate(original_lines):
                if re.match(r'^\s*\[customExecutables\]\s*$', line, re.IGNORECASE):
                    in_custom_exec = True
                    continue
                if in_custom_exec and re.match(r'^\s*\[.*\]\s*$', line):
                    in_custom_exec = False
                if in_custom_exec:
                    m = re.match(r'^(\d+)\\binary\s*=\s*(.*)$', line.strip(), re.IGNORECASE)
                    if m:
                        idx, old_path = m.group(1), m.group(2)
                        exe_name = os.path.basename(old_path).lower()
                        if exe_name in TARGET_EXECUTABLES_LOWER:
                            new_path = f'{gamepath_drive_letter}/{PathHandler._strip_sdcard_path_prefix(gamepath_target_dir)}/{exe_name}'
                            # Use robust formatter
                            new_path = PathHandler._format_binary_for_mo2(new_path)
                            logger.info(f"Updating binary for entry {idx}: {old_path} -> {new_path}")
                            original_lines[i] = f'{idx}\\binary = {new_path}\n'
                    m_wd = re.match(r'^(\d+)\\workingDirectory\s*=\s*(.*)$', line.strip(), re.IGNORECASE)
                    if m_wd:
                        idx, old_wd = m_wd.group(1), m_wd.group(2)
                        new_wd = f'{gamepath_drive_letter}{windows_style_single}'
                        # Use robust formatter
                        new_wd = PathHandler._format_workingdir_for_mo2(new_wd)
                        logger.info(f"Updating workingDirectory for entry {idx}: {old_wd} -> {new_wd}")
                        original_lines[i] = f'{idx}\\workingDirectory = {new_wd}\n'

            # --- Backup and Write New INI ---
            backup_path = modlist_ini_path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
            try:
                shutil.copy2(modlist_ini_path, backup_path)
                logger.info(f"Backed up original INI to: {backup_path}")
            except Exception as bak_err:
                logger.error(f"Failed to backup original INI file: {bak_err}")
                return False
            try:
                with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                    f.writelines(original_lines)
                logger.info(f"Successfully wrote updated paths to {modlist_ini_path}")
                return True
            except Exception as write_err:
                logger.error(f"Failed to write updated INI file {modlist_ini_path}: {write_err}", exc_info=True)
                logger.error("Attempting to restore from backup...")
                try:
                    shutil.move(backup_path, modlist_ini_path)
                    logger.info("Successfully restored original INI from backup.")
                except Exception as restore_err:
                    logger.critical(f"CRITICAL FAILURE: Could not write new INI and failed to restore backup {backup_path}. Manual intervention required at {modlist_ini_path}! Error: {restore_err}")
                return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during INI path update: {e}", exc_info=True)
            return False
    
    @staticmethod
    def edit_resolution(modlist_ini, resolution):
        """
        Edit resolution settings in ModOrganizer.ini
        
        Args:
            modlist_ini (str): Path to ModOrganizer.ini
            resolution (str): Resolution in the format "1920x1080"
            
        Returns:
            bool: True on success, False on failure
        """
        try:
            logger.info(f"Editing resolution settings to {resolution}...")
            
            # Parse resolution
            width, height = resolution.split('x')
            
            # Read the current ModOrganizer.ini
            with open(modlist_ini, 'r') as f:
                content = f.read()
            
            # Replace width and height settings
            content = re.sub(r'^width\s*=\s*\d+$', f'width = {width}', content, flags=re.MULTILINE)
            content = re.sub(r'^height\s*=\s*\d+$', f'height = {height}', content, flags=re.MULTILINE)
            
            # Write the updated content back to the file
            with open(modlist_ini, 'w') as f:
                f.write(content)
            
            logger.info("Resolution settings edited successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error editing resolution settings: {e}")
            return False
    
    @staticmethod
    def create_dxvk_conf(modlist_dir, modlist_sdcard, steam_library, basegame_sdcard, game_var_full, vanilla_game_dir=None, stock_game_path=None):
        """
        Create dxvk.conf file in the appropriate location
        
        Args:
            modlist_dir (str): Path to the modlist directory
            modlist_sdcard (bool): Whether the modlist is on an SD card
            steam_library (str): Path to the Steam library
            basegame_sdcard (bool): Whether the base game is on an SD card
            game_var_full (str): Full name of the game (e.g., "Skyrim Special Edition")
            vanilla_game_dir (str): Optional path to vanilla game directory for fallback
            stock_game_path (str): Direct path to detected stock game directory (if available)
            
        Returns:
            bool: True on success, False on failure
        """
        try:
            logger.info("Creating dxvk.conf file...")
            
            candidate_dirs = PathHandler._build_dxvk_candidate_dirs(
                modlist_dir=modlist_dir,
                stock_game_path=stock_game_path,
                steam_library=steam_library,
                game_var_full=game_var_full,
                vanilla_game_dir=vanilla_game_dir
            )
            
            if not candidate_dirs:
                logger.error("Could not determine location for dxvk.conf (no candidate directories found)")
                return False
            
            target_dir = None
            for directory in candidate_dirs:
                if directory.is_dir():
                    target_dir = directory
                    break
            
            if target_dir is None:
                fallback_dir = Path(modlist_dir) if modlist_dir and Path(modlist_dir).is_dir() else None
                if fallback_dir:
                    logger.warning(f"No stock/vanilla directories found; falling back to modlist directory: {fallback_dir}")
                    target_dir = fallback_dir
                else:
                    logger.error("All candidate directories for dxvk.conf are missing.")
                    return False
            
            dxvk_conf_path = target_dir / "dxvk.conf"
            
            # The required line that Jackify needs
            required_line = "dxvk.enableGraphicsPipelineLibrary = False"
            
            # Check if dxvk.conf already exists
            if dxvk_conf_path.exists():
                logger.info(f"Found existing dxvk.conf at {dxvk_conf_path}")
                
                # Read existing content
                try:
                    with open(dxvk_conf_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read().strip()
                    
                    # Check if our required line is already present
                    existing_lines = existing_content.split('\n') if existing_content else []
                    has_required_line = any(line.strip() == required_line for line in existing_lines)
                    
                    if has_required_line:
                        logger.info("Required DXVK setting already present in existing file")
                        return True
                    else:
                        # Append our required line to existing content
                        if existing_content:
                            # File has content, append our line
                            updated_content = existing_content + '\n' + required_line + '\n'
                            logger.info("Appending required DXVK setting to existing file")
                        else:
                            # File is empty, just add our line
                            updated_content = required_line + '\n'
                            logger.info("Adding required DXVK setting to empty file")
                        
                        with open(dxvk_conf_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        
                        logger.info(f"dxvk.conf updated successfully at {dxvk_conf_path}")
                        return True
                        
                except Exception as e:
                    logger.error(f"Error reading/updating existing dxvk.conf: {e}")
                    # Fall back to creating new file
                    logger.info("Falling back to creating new dxvk.conf file")
            
            # Create new dxvk.conf file (original behavior)
            dxvk_conf_content = required_line + '\n'
            
            dxvk_conf_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dxvk_conf_path, 'w', encoding='utf-8') as f:
                f.write(dxvk_conf_content)
            
            logger.info(f"dxvk.conf created successfully at {dxvk_conf_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating dxvk.conf: {e}")
            return False

    @staticmethod
    def verify_dxvk_conf_exists(modlist_dir, steam_library, game_var_full, vanilla_game_dir=None, stock_game_path=None) -> bool:
        """
        Verify that dxvk.conf exists in at least one of the candidate directories and contains the required setting.
        """
        required_line = "dxvk.enableGraphicsPipelineLibrary = False"
        candidate_dirs = PathHandler._build_dxvk_candidate_dirs(
            modlist_dir=modlist_dir,
            stock_game_path=stock_game_path,
            steam_library=steam_library,
            game_var_full=game_var_full,
            vanilla_game_dir=vanilla_game_dir
        )
        
        for directory in candidate_dirs:
            conf_path = directory / "dxvk.conf"
            if conf_path.is_file():
                try:
                    with open(conf_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if required_line not in content:
                        logger.warning(f"dxvk.conf found at {conf_path} but missing required setting. Appending now.")
                        with open(conf_path, 'a', encoding='utf-8') as f:
                            if not content.endswith('\n'):
                                f.write('\n')
                            f.write(required_line + '\n')
                    logger.info(f"Verified dxvk.conf at {conf_path}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to verify dxvk.conf at {conf_path}: {e}")
        
        logger.warning("dxvk.conf verification failed - file not found in any candidate directory.")
        return False

    @staticmethod
    def _normalize_common_library_path(steam_library: Optional[str]) -> Optional[Path]:
        if not steam_library:
            return None
        path = Path(steam_library)
        parts_lower = [part.lower() for part in path.parts]
        if len(parts_lower) >= 2 and parts_lower[-2:] == ['steamapps', 'common']:
            return path
        if parts_lower and parts_lower[-1] == 'common':
            return path
        if 'steamapps' in parts_lower:
            idx = parts_lower.index('steamapps')
            truncated = Path(*path.parts[:idx + 1])
            return truncated / 'common'
        return path / 'steamapps' / 'common'

    @staticmethod
    def _build_dxvk_candidate_dirs(modlist_dir, stock_game_path, steam_library, game_var_full, vanilla_game_dir) -> List[Path]:
        candidates: List[Path] = []
        seen = set()

        def add_candidate(path_obj: Optional[Path]):
            if not path_obj:
                return
            key = path_obj.resolve() if path_obj.exists() else path_obj
            if key in seen:
                return
            seen.add(key)
            candidates.append(path_obj)

        if stock_game_path:
            add_candidate(Path(stock_game_path))

        if modlist_dir:
            base_path = Path(modlist_dir)
            common_names = [
                "Stock Game",
                "Game Root",
                "STOCK GAME",
                "Stock Game Folder",
                "Stock Folder",
                "Skyrim Stock",
                os.path.join("root", "Skyrim Special Edition")
            ]
            for name in common_names:
                add_candidate(base_path / name)

        steam_common = PathHandler._normalize_common_library_path(steam_library)
        if steam_common and game_var_full:
            add_candidate(steam_common / game_var_full)

        if vanilla_game_dir:
            add_candidate(Path(vanilla_game_dir))

        if modlist_dir:
            add_candidate(Path(modlist_dir))

        return candidates
    
    @staticmethod
    def find_steam_config_vdf() -> Optional[Path]:
        """Finds the active Steam config.vdf file."""
        logger.debug("Searching for Steam config.vdf...")
        possible_steam_paths = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/root"
        ]
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                logger.info(f"Found config.vdf at: {potential_path}")
                return potential_path # Return Path object

        logger.warning("Could not locate Steam's config.vdf file in standard locations.")
        return None
    
    @staticmethod
    def find_steam_library() -> Optional[Path]:
        """Find the primary Steam library common directory containing games."""
        logger.debug("Attempting to find Steam library...")
        
        # Potential locations for libraryfolders.vdf
        libraryfolders_vdf_paths = [
            os.path.expanduser("~/.steam/steam/config/libraryfolders.vdf"),
            os.path.expanduser("~/.local/share/Steam/config/libraryfolders.vdf"),
            os.path.expanduser("~/.var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf"),  # Flatpak
        ]
        
        # Simple backup mechanism (optional but good practice)
        for path in libraryfolders_vdf_paths:
            if os.path.exists(path):
                backup_dir = os.path.join(os.path.dirname(path), "backups")
                if not os.path.exists(backup_dir):
                    try:
                        os.makedirs(backup_dir)
                    except OSError as e:
                        logger.warning(f"Could not create backup directory {backup_dir}: {e}")
                
                # Create timestamped backup if it doesn't exist for today
                timestamp = datetime.now().strftime("%Y%m%d")
                backup_filename = f"libraryfolders_{timestamp}.vdf.bak"
                backup_path = os.path.join(backup_dir, backup_filename)
                
                if not os.path.exists(backup_path):
                    try:
                        import shutil
                        shutil.copy2(path, backup_path)
                        logger.debug(f"Created backup of libraryfolders.vdf at {backup_path}")
                    except Exception as e:
                        logger.error(f"Failed to create backup of libraryfolders.vdf: {e}")
                        # Continue anyway, as we're only reading the file
                        pass
        
        libraryfolders_vdf_path_obj = None  # Will hold the Path object
        found_path_str = None
        for path_str in libraryfolders_vdf_paths:
            if os.path.exists(path_str):
                found_path_str = path_str # Keep the string path for logging/opening
                libraryfolders_vdf_path_obj = Path(path_str) # Convert to Path object here
                logger.debug(f"Found libraryfolders.vdf at: {path_str}")
                break
        
        # Check using the Path object's is_file() method
        if not libraryfolders_vdf_path_obj or not libraryfolders_vdf_path_obj.is_file():
             logger.warning("libraryfolders.vdf not found or is not a file. Cannot automatically detect Steam Library.")
             return None
        
        # Parse the VDF file to extract library paths
        library_paths = []
        try:
            # Open using the original string path is fine, or use the Path object
            with open(found_path_str, 'r') as f: # Or use libraryfolders_vdf_path_obj
                content = f.read()
                
                # Use regex to find all path entries
                path_matches = re.finditer(r'"path"\s*"([^"]+)"', content)
                for match in path_matches:
                    library_path_str = match.group(1).replace('\\\\', '\\') # Fix potential double escapes
                    common_path = os.path.join(library_path_str, "steamapps", "common")
                    if os.path.isdir(common_path): # Verify the common path exists
                        library_paths.append(Path(common_path))
                        logger.debug(f"Found potential common path: {common_path}")
                    else:
                        logger.debug(f"Skipping non-existent common path derived from VDF: {common_path}")
            
            logger.debug(f"Found {len(library_paths)} valid library common paths from VDF.")
            
            # Return the first valid path found
            if library_paths:
                logger.info(f"Using Steam library common path: {library_paths[0]}")
                return library_paths[0]
            
            # If no valid paths found in VDF, try the default structure
            logger.debug("No valid common paths found in VDF, checking default location...")
            default_common_path = Path.home() / ".steam/steam/steamapps/common"
            if default_common_path.is_dir():
                logger.info(f"Using default Steam library common path: {default_common_path}")
                return default_common_path
            
            default_common_path_local = Path.home() / ".local/share/Steam/steamapps/common"
            if default_common_path_local.is_dir():
                 logger.info(f"Using default local Steam library common path: {default_common_path_local}")
                 return default_common_path_local
            
            logger.error("No valid Steam library common path found in VDF or default locations.")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing libraryfolders.vdf or finding Steam library: {e}", exc_info=True)
            return None
    
    @staticmethod
    def find_compat_data(appid: str) -> Optional[Path]:
        """Find the compatdata directory for a given AppID."""
        if not appid:
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None
        
        # Handle negative AppIDs (remove minus sign for validation)
        appid_clean = appid.lstrip('-')
        if not appid_clean.isdigit():
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None

        logger.debug(f"Searching for compatdata directory for AppID: {appid}")
        
        # Use libraryfolders.vdf to find all Steam library paths, when available
        library_paths = PathHandler.get_all_steam_library_paths()
        if library_paths:
            logger.debug(f"Checking compatdata in {len(library_paths)} Steam libraries")
            
            # Check each Steam library's compatdata directory
            for library_path in library_paths:
                compatdata_base = library_path / "steamapps" / "compatdata"
                if not compatdata_base.is_dir():
                    logger.debug(f"Compatdata directory does not exist: {compatdata_base}")
                    continue
                    
                potential_path = compatdata_base / appid
                if potential_path.is_dir():
                    logger.info(f"Found compatdata directory: {potential_path}")
                    return potential_path
                else:
                    logger.debug(f"Compatdata for AppID {appid} not found in {compatdata_base}")
        
        # Check fallback locations only if we didn't find valid libraries
        # If we have valid libraries from libraryfolders.vdf, we should NOT fall back to wrong locations
        is_flatpak_steam = any('.var/app/com.valvesoftware.Steam' in str(lib) for lib in library_paths) if library_paths else False
        
        if not library_paths or is_flatpak_steam:
            # Only check Flatpak-specific fallbacks if we have Flatpak Steam
            logger.debug("Checking fallback compatdata locations...")
            if is_flatpak_steam:
                # For Flatpak Steam, only check Flatpak-specific locations
                fallback_locations = [
                    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
                    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata",
                ]
            else:
                # For native Steam or unknown, check standard locations
                fallback_locations = [
                    Path.home() / ".local/share/Steam/steamapps/compatdata",
                    Path.home() / ".steam/steam/steamapps/compatdata",
                ]
            
            for compatdata_base in fallback_locations:
                if compatdata_base.is_dir():
                    potential_path = compatdata_base / appid
                    if potential_path.is_dir():
                        logger.warning(f"Found compatdata directory in fallback location (may be from old incorrect creation): {potential_path}")
                        return potential_path
        
        logger.warning(f"Compatdata directory for AppID {appid} not found in any Steam library or fallback location.")
        return None
    
    @staticmethod
    def detect_stock_game_path(game_type: str, steam_library: Path) -> Optional[Path]:
        """
        Detect the stock game path for a given game type and Steam library
        Returns the path if found, None otherwise
        """
        try:
            # Map of game types to their Steam App IDs
            game_app_ids = {
                'skyrim': '489830',  # Skyrim Special Edition
                'fallout4': '377160',  # Fallout 4
                'fnv': '22380',  # Fallout: New Vegas
                'oblivion': '22330'  # The Elder Scrolls IV: Oblivion
            }
            
            if game_type not in game_app_ids:
                return None
            
            app_id = game_app_ids[game_type]
            game_path = steam_library / 'steamapps' / 'common'
            
            # List of possible game directory names
            possible_names = {
                'skyrim': ['Skyrim Special Edition', 'Skyrim'],
                'fallout4': ['Fallout 4'],
                'fnv': ['Fallout New Vegas', 'FalloutNV'],
                'oblivion': ['Oblivion']
            }
            
            if game_type not in possible_names:
                return None
            
            # Check each possible directory name
            for name in possible_names[game_type]:
                potential_path = game_path / name
                if potential_path.exists():
                    return potential_path
            
            return None
            
        except Exception as e:
            logging.error(f"Error detecting stock game path: {e}")
            return None
    
    @staticmethod
    def get_steam_library_path(steam_path: str) -> Optional[str]:
        """Get the Steam library path from libraryfolders.vdf."""
        try:
            libraryfolders_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
            if not os.path.exists(libraryfolders_path):
                return None

            with open(libraryfolders_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse the VDF content
            libraries = {}
            current_library = None
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('"path"'):
                    current_library = line.split('"')[3].replace('\\\\', '\\')
                elif line.startswith('"apps"') and current_library:
                    libraries[current_library] = True

            # Return the first library path that exists
            for library_path in libraries:
                if os.path.exists(library_path):
                    return library_path

            return None
        except Exception as e:
            logger.error(f"Error getting Steam library path: {str(e)}")
            return None
    
    @staticmethod
    def get_all_steam_library_paths() -> List[Path]:
        """Finds all Steam library paths listed in all known libraryfolders.vdf files (including Flatpak)."""
        logger.info("[DEBUG] Searching for all Steam libraryfolders.vdf files...")
        vdf_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".steam/root/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf",  # Flatpak
        ]
        library_paths = set()
        for vdf_path in vdf_paths:
            if vdf_path.is_file():
                logger.info(f"[DEBUG] Parsing libraryfolders.vdf: {vdf_path}")
                try:
                    with open(vdf_path, 'r', encoding='utf-8') as f:
                        data = vdf.load(f)
                        # libraryfolders.vdf structure: libraryfolders -> "0", "1", etc. -> "path"
                        libraryfolders = data.get('libraryfolders', {})
                        for key, lib_data in libraryfolders.items():
                            if isinstance(lib_data, dict) and 'path' in lib_data:
                                lib_path = Path(lib_data['path'])
                                # Resolve symlinks for consistency (mmcblk0p1 -> deck/UUID)
                                try:
                                    resolved_path = lib_path.resolve()
                                    library_paths.add(resolved_path)
                                    logger.debug(f"[DEBUG] Found library path: {resolved_path}")
                                except (OSError, RuntimeError) as resolve_err:
                                    # If resolve fails, use original path
                                    logger.warning(f"[DEBUG] Could not resolve {lib_path}, using as-is: {resolve_err}")
                                    library_paths.add(lib_path)
                except Exception as e:
                    logger.error(f"[DEBUG] Failed to parse {vdf_path}: {e}")
        logger.info(f"[DEBUG] All detected Steam libraries: {library_paths}")
        return list(library_paths)

    # Moved _find_shortcuts_vdf here from ShortcutHandler
    def _find_shortcuts_vdf(self) -> Optional[str]:
        """Helper to find the active shortcuts.vdf file for the current Steam user.

        Uses proper multi-user detection to find the correct Steam user instead
        of just taking the first found user directory.

        Returns:
            Optional[str]: The full path to the shortcuts.vdf file, or None if not found.
        """
        try:
            # Use native Steam service for proper multi-user detection
            from jackify.backend.services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            shortcuts_path = steam_service.get_shortcuts_vdf_path()

            if shortcuts_path:
                logger.info(f"Found shortcuts.vdf using multi-user detection: {shortcuts_path}")
                return str(shortcuts_path)
            else:
                logger.error("Could not determine shortcuts.vdf path using multi-user detection")
                return None

        except Exception as e:
            logger.error(f"Error using multi-user detection for shortcuts.vdf: {e}")
            return None

    @staticmethod
    def find_game_install_paths(target_appids: Dict[str, str]) -> Dict[str, Path]:
        """
        Find installation paths for multiple specified games using Steam app IDs.
        
        Args:
            target_appids: Dictionary mapping game names to app IDs
            
        Returns:
            Dictionary mapping game names to their installation paths
        """
        # Get all Steam library paths
        library_paths = PathHandler.get_all_steam_library_paths()
        if not library_paths:
            logger.warning("Failed to find any Steam library paths")
            return {}
        
        results = {}
        
        # For each library path, look for each target game
        for library_path in library_paths:
            # Check if the common directory exists (games are in steamapps/common)
            common_dir = library_path / "steamapps" / "common"
            if not common_dir.is_dir():
                logger.debug(f"No 'steamapps/common' directory in library: {library_path}")
                continue
            
            # Get subdirectories in common dir
            try:
                game_dirs = [d for d in common_dir.iterdir() if d.is_dir()]
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot access directory {common_dir}: {e}")
                continue
            
            # For each app ID, check if we find its directory
            for game_name, app_id in target_appids.items():
                if game_name in results:
                    continue  # Already found this game
                
                # Try to find by appmanifest (manifests are in steamapps subdirectory)
                appmanifest_path = library_path / "steamapps" / f"appmanifest_{app_id}.acf"
                if appmanifest_path.is_file():
                    # Find the installdir value
                    try:
                        with open(appmanifest_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            match = re.search(r'"installdir"\s+"([^"]+)"', content)
                            if match:
                                install_dir_name = match.group(1)
                                install_path = common_dir / install_dir_name
                                if install_path.is_dir():
                                    results[game_name] = install_path
                                    logger.info(f"Found {game_name} at {install_path}")
                                    continue
                    except Exception as e:
                        logger.warning(f"Error reading appmanifest for {game_name}: {e}")
        
        return results

    def replace_gamepath(self, modlist_ini_path: Path, new_game_path: Path, modlist_sdcard: bool = False) -> bool:
        """
        Updates the gamePath value in ModOrganizer.ini to the specified path.
        Strictly matches the bash script: only replaces an existing gamePath line.
        If the file or line does not exist, logs error and aborts.
        """
        logger.info(f"Replacing gamePath in {modlist_ini_path} with {new_game_path}")
        if not modlist_ini_path.is_file():
            logger.error(f"ModOrganizer.ini not found at: {modlist_ini_path}")
            return False
        try:
            with open(modlist_ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            drive_letter = "D:\\\\" if modlist_sdcard else "Z:\\\\"
            processed_path = self._strip_sdcard_path_prefix(new_game_path)
            windows_style = processed_path.replace('/', '\\')
            windows_style_double = windows_style.replace('\\', '\\\\')
            new_gamepath_line = f'gamePath=@ByteArray({drive_letter}{windows_style_double})\n'
            gamepath_found = False
            for i, line in enumerate(lines):
                # Make the check case-insensitive and robust to whitespace
                if re.match(r'^\s*gamepath\s*=.*$', line, re.IGNORECASE):
                    lines[i] = new_gamepath_line
                    gamepath_found = True
                    break
            if not gamepath_found:
                logger.error("No gamePath line found in ModOrganizer.ini")
                return False
            with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Successfully updated gamePath to {new_game_path}")
            return True
        except Exception as e:
            logger.error(f"Error replacing gamePath: {e}", exc_info=True)
            return False

    # =====================================================================================
    # CRITICAL: DO NOT CHANGE THIS FUNCTION WITHOUT UPDATING TESTS AND CONSULTING PROJECT LEAD
    # This function implements the exact path rewriting logic required for ModOrganizer.ini
    # to match the original, robust bash script. Any change here risks breaking modlist
    # configuration for users. If you must change this, update all relevant tests and
    # consult the Project Lead for Jackify. See also omni-guides.sh for reference logic.
    # =====================================================================================
    def edit_binary_working_paths(self, modlist_ini_path: Path, modlist_dir_path: Path, modlist_sdcard: bool, steam_libraries: Optional[List[Path]] = None) -> bool:
        """
        Update all binary paths and working directories in a ModOrganizer.ini file.
        Handles various ModOrganizer.ini formats (single or double backslashes in keys).
        When updating gamePath, binary, and workingDirectory, retain the original stock folder (Stock Game, Game Root, etc) if present in the current value.
        steam_libraries: Optional[List[Path]] - already-discovered Steam library paths to use for vanilla detection.

        # DO NOT CHANGE THIS LOGIC WITHOUT UPDATING TESTS AND CONSULTING THE PROJECT LEAD
        # This is a critical, regression-prone area. See omni-guides.sh for reference.
        """
        try:
            logger.debug(f"Updating binary paths and working directories in {modlist_ini_path} to use root: {modlist_dir_path}")
            if not modlist_ini_path.is_file():
                logger.error(f"INI file {modlist_ini_path} does not exist")
                return False
            with open(modlist_ini_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Extract existing gamePath to use as source of truth for vanilla game location
            existing_game_path = None
            gamepath_drive_letter = None
            gamepath_line_index = -1
            for i, line in enumerate(lines):
                if re.match(r'^\s*gamepath\s*=.*@ByteArray\(([^)]+)\)', line, re.IGNORECASE):
                    match = re.search(r'@ByteArray\(([^)]+)\)', line)
                    if match:
                        raw_path = match.group(1)
                        gamepath_line_index = i
                        # Extract drive letter from gamePath (Z: or D:)
                        if raw_path.startswith('Z:'):
                            gamepath_drive_letter = 'Z:'
                        elif raw_path.startswith('D:'):
                            gamepath_drive_letter = 'D:'
                        # Convert Windows path back to Linux path
                        if raw_path.startswith(('Z:', 'D:')):
                            linux_path = raw_path[2:].replace('\\\\', '/').replace('\\', '/')
                            existing_game_path = linux_path
                            logger.debug(f"Extracted existing gamePath: {existing_game_path}, drive letter: {gamepath_drive_letter}")
                            break

            # Special handling for gamePath in three-true scenario (engine_installed + steamdeck + sdcard)
            if modlist_sdcard and existing_game_path and existing_game_path.startswith('/run/media') and gamepath_line_index != -1:
                # Simple manual stripping of /run/media/deck/UUID pattern for SD card paths
                # Match /run/media/deck/[UUID]/Games/... and extract just /Games/...
                sdcard_pattern = r'^/run/media/deck/[^/]+(/Games/.*)$'
                match = re.match(sdcard_pattern, existing_game_path)
                if match:
                    stripped_path = match.group(1)  # Just the /Games/... part
                    windows_path = stripped_path.replace('/', '\\\\')
                    new_gamepath_value = f"D:\\\\{windows_path}"
                    new_gamepath_line = f"gamePath = @ByteArray({new_gamepath_value})\n"

                    logger.info(f"Updating gamePath for SD card: {lines[gamepath_line_index].strip()} -> {new_gamepath_line.strip()}")
                    lines[gamepath_line_index] = new_gamepath_line
                else:
                    logger.warning(f"SD card path doesn't match expected pattern: {existing_game_path}")
            
            game_path_updated = False
            binary_paths_updated = 0
            working_dirs_updated = 0
            binary_lines = []
            working_dir_lines = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                binary_match = re.match(r'^(\d+)(\\+)\s*binary\s*=.*$', stripped, re.IGNORECASE)
                if binary_match:
                    index = binary_match.group(1)
                    backslash_style = binary_match.group(2)
                    binary_lines.append((i, stripped, index, backslash_style))
                wd_match = re.match(r'^(\d+)(\\+)\s*workingDirectory\s*=.*$', stripped, re.IGNORECASE)
                if wd_match:
                    index = wd_match.group(1)
                    backslash_style = wd_match.group(2)
                    working_dir_lines.append((i, stripped, index, backslash_style))
            binary_paths_by_index = {}
            # Use existing gamePath to determine correct Steam library, fallback to detection
            if existing_game_path and '/steamapps/common/' in existing_game_path:
                # Extract the Steam library root from the existing gamePath
                steamapps_index = existing_game_path.find('/steamapps/common/')
                steam_lib_root = existing_game_path[:steamapps_index]
                steam_libraries = [Path(steam_lib_root)]
                logger.info(f"Using Steam library from existing gamePath: {steam_lib_root}")
            elif steam_libraries is None or not steam_libraries:
                steam_libraries = PathHandler.get_all_steam_library_paths()
                logger.debug(f"Fallback to detected Steam libraries: {steam_libraries}")
            for i, line, index, backslash_style in binary_lines:
                parts = line.split('=', 1)
                if len(parts) != 2:
                    logger.error(f"Malformed binary line: {line}")
                    continue
                key_part, value_part = parts
                
                # Clean up malformed paths (quotes in wrong places, etc.)
                cleaned_value = PathHandler._clean_malformed_binary_path(value_part)
                exe_name = os.path.basename(cleaned_value).lower()
                
                # SELECTIVE FILTERING: Only process target executables (script extenders, etc.)
                if exe_name not in TARGET_EXECUTABLES_LOWER:
                    logger.debug(f"Skipping non-target executable: {exe_name}")
                    continue
                    
                rel_path = None
                # --- BEGIN: FULL PARITY LOGIC ---
                if 'steamapps' in cleaned_value:
                    # Vanilla game path detected - always rebuild to ensure correct format
                    if not gamepath_drive_letter:
                        logger.warning(f"Vanilla game path detected but gamePath drive letter not found. Skipping binary path update for: {exe_name}")
                        logger.warning("This may indicate jackify-engine already configured paths correctly, or gamePath is malformed.")
                        continue
                    
                    # Check if path is malformed (has quotes or wrong structure)
                    is_malformed = '"' in cleaned_value or cleaned_value != value_part.strip().strip('"')
                    
                    # Extract subpath from cleaned value (includes exe name)
                    idx = cleaned_value.index('steamapps')
                    subpath = cleaned_value[idx:].lstrip('/')
                    
                    # Find correct Steam library
                    correct_steam_lib = None
                    for lib in steam_libraries:
                        # Check if the actual game folder exists in this library
                        if len(subpath.split('/')) > 3 and (lib / subpath.split('/')[2] / subpath.split('/')[3]).exists():
                            correct_steam_lib = lib
                            break
                    if not correct_steam_lib and steam_libraries:
                        correct_steam_lib = steam_libraries[0]
                    if correct_steam_lib:
                        # Always rebuild path using gamePath drive letter to ensure correct format
                        drive_prefix = gamepath_drive_letter
                        if is_malformed:
                            logger.info(f"Fixing malformed binary path for {exe_name}: {value_part.strip()}")
                        logger.debug(f"Vanilla game path detected: Using drive letter from gamePath: {drive_prefix}")
                        new_binary_path = f"{drive_prefix}/{correct_steam_lib}/{subpath}".replace('\\', '/').replace('//', '/')
                    else:
                        logger.error("Could not determine correct Steam library for vanilla game path.")
                        continue
                else:
                    # For modlist-relative paths (Stock Game, mods, etc.), use modlist location
                    drive_prefix = "D:" if modlist_sdcard else "Z:"
                    found_stock = None
                    for folder in STOCK_GAME_FOLDERS:
                        folder_pattern = f"/{folder}"
                        if folder_pattern in cleaned_value:
                            idx = cleaned_value.index(folder_pattern)
                            rel_path = cleaned_value[idx:].lstrip('/')
                            found_stock = folder
                            break
                    if not rel_path:
                        mods_pattern = "/mods/"
                        if mods_pattern in cleaned_value:
                            idx = cleaned_value.index(mods_pattern)
                            rel_path = cleaned_value[idx:].lstrip('/')
                        else:
                            rel_path = exe_name
                    processed_modlist_path = PathHandler._strip_sdcard_path_prefix(modlist_dir_path) if modlist_sdcard else str(modlist_dir_path)
                    new_binary_path = f"{drive_prefix}/{processed_modlist_path}/{rel_path}".replace('\\', '/').replace('//', '/')
                formatted_binary_path = PathHandler._format_binary_for_mo2(new_binary_path)
                # Ensure no quotes in formatted path (binary paths should never have quotes)
                if '"' in formatted_binary_path:
                    logger.warning(f"Formatted binary path still contains quotes, removing: {formatted_binary_path}")
                    formatted_binary_path = formatted_binary_path.replace('"', '')
                new_binary_line = f"{index}{backslash_style}binary = {formatted_binary_path}"
                logger.info(f"Updating binary path: {line.strip()} -> {new_binary_line}")
                # Preserve original line ending - lines from readlines() should have newline, but ensure it
                original_line = lines[i]
                if original_line.endswith('\n'):
                    lines[i] = new_binary_line + '\n'
                else:
                    lines[i] = new_binary_line + '\n'
                binary_paths_updated += 1
                binary_paths_by_index[index] = formatted_binary_path
            for j, wd_line, index, backslash_style in working_dir_lines:
                if index in binary_paths_by_index:
                    binary_path = binary_paths_by_index[index]
                    wd_path = os.path.dirname(binary_path)
                    # Derive drive letter from binary path, not modlist location
                    if binary_path.startswith("D:"):
                        drive_prefix = "D:"
                    elif binary_path.startswith("Z:"):
                        drive_prefix = "Z:"
                    else:
                        # Fallback: use modlist location if binary path doesn't have drive letter
                        drive_prefix = "D:" if modlist_sdcard else "Z:"
                    if wd_path.startswith("D:") or wd_path.startswith("Z:"):
                        wd_path = wd_path[2:]
                    wd_path = drive_prefix + wd_path
                    formatted_wd_path = PathHandler._format_workingdir_for_mo2(wd_path)
                    key_part = f"{index}{backslash_style}workingDirectory"
                    new_wd_line = f"{key_part} = {formatted_wd_path}"
                    logger.debug(f"Updating working directory: {wd_line.strip()} -> {new_wd_line}")
                    # Preserve original line ending - ensure newline is present
                    original_wd_line = lines[j]
                    if original_wd_line.endswith('\n'):
                        lines[j] = new_wd_line + '\n'
                    else:
                        lines[j] = new_wd_line + '\n'
                    working_dirs_updated += 1
            with open(modlist_ini_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"edit_binary_working_paths completed: Game path updated: {game_path_updated}, Binary paths updated: {binary_paths_updated}, Working directories updated: {working_dirs_updated}")
            return True
        except Exception as e:
            logger.error(f"Error updating binary paths in {modlist_ini_path}: {str(e)}")
            return False

    def _format_path_for_mo2(self, path: str) -> str:
        """Format a path for MO2's ModOrganizer.ini file (working directories)."""
        # Replace forward slashes with double backslashes
        formatted = path.replace('/', '\\')
        # Ensure we have a Windows drive letter format
        if not re.match(r'^[A-Za-z]:', formatted):
            formatted = 'D:' + formatted
        # Double the backslashes for the INI file format
        formatted = formatted.replace('\\', '\\\\')
        return formatted

    def _format_binary_path_for_mo2(self, path_str):
        """Format a binary path for MO2 config file.
        
        Binary paths need forward slashes (/) in the path portion.
        """
        # Replace backslashes with forward slashes
        return path_str.replace('\\', '/')
        
    def _format_working_dir_for_mo2(self, path_str):
        """
        Format a working directory path for MO2 config file.
        Ensures double backslashes throughout, as required by ModOrganizer.ini.
        """
        import re
        path = path_str.replace('/', '\\')
        path = path.replace('\\', '\\\\')  # Double all backslashes
        # Ensure only one double backslash after drive letter
        path = re.sub(r'^([A-Z]:)\\\\+', r'\1\\\\', path)
        return path

    @staticmethod
    def find_vanilla_game_paths(game_names=None) -> Dict[str, Path]:
        """
        For each known game, iterate all Steam libraries and look for the canonical game directory name in steamapps/common.
        Returns a dict of found games and their paths.
        Args:
            game_names: Optional list of game names to check. If None, uses default supported games.
        Returns:
            Dict[str, Path]: Mapping of game name to found install Path.
        """
        # Canonical game directory names (allow list for Fallout 3)
        GAME_DIR_NAMES = {
            "Skyrim Special Edition": ["Skyrim Special Edition"],
            "Fallout 4": ["Fallout 4"],
            "Fallout New Vegas": ["Fallout New Vegas"],
            "Oblivion": ["Oblivion"],
            "Fallout 3": ["Fallout 3", "Fallout 3 goty"]
        }
        if game_names is None:
            game_names = list(GAME_DIR_NAMES.keys())
        all_steam_libraries = PathHandler.get_all_steam_library_paths()
        logger.info(f"[DEBUG] Detected Steam libraries: {all_steam_libraries}")
        found_games = {}
        for game in game_names:
            possible_names = GAME_DIR_NAMES.get(game, [game])
            for lib in all_steam_libraries:
                for name in possible_names:
                    candidate = lib / "steamapps" / "common" / name
                    logger.info(f"[DEBUG] Checking for vanilla game directory: {candidate}")
                    if candidate.is_dir():
                        found_games[game] = candidate
                        logger.info(f"Found vanilla game directory for {game}: {candidate}")
                        break  # Stop after first found location
                if game in found_games:
                    break
        return found_games

    def _detect_stock_game_path(self):
        """Detects common 'Stock Game' or 'Game Root' directories within the modlist path."""
        self.logger.info("Step 7a: Detecting Stock Game/Game Root directory...")
        if not self.modlist_dir:
            self.logger.error("Modlist directory not set, cannot detect stock game path.")
            return False

        modlist_path = Path(self.modlist_dir)
        # Always prefer 'Stock Game' if it exists, then fallback to others
        preferred_order = [
            "Stock Game",
            "STOCK GAME",
            "Skyrim Stock",
            "Stock Game Folder",
            "Stock Folder",
            Path("root/Skyrim Special Edition"),
            "Game Root"  # 'Game Root' is now last
        ]

        found_path = None
        for name in preferred_order:
            potential_path = modlist_path / name
            if potential_path.is_dir():
                found_path = str(potential_path)
                self.logger.info(f"Found potential stock game directory: {found_path}")
                break # Found the first match
        if found_path:
            self.stock_game_path = found_path
            return True
        else:
            self.stock_game_path = None
            self.logger.info("No common Stock Game/Game Root directory found. Will assume vanilla game path is needed for some operations.")
            return True

    # --- Add robust path formatters for INI fields ---
    @staticmethod
    def _format_gamepath_for_mo2(path: str) -> str:
        import re
        path = path.replace('/', '\\')
        path = re.sub(r'\\+', r'\\', path)  # Collapse multiple backslashes
        # Ensure only one double backslash after drive letter
        path = re.sub(r'^([A-Z]:)\\+', r'\1\\', path)
        return path

    @staticmethod
    def _clean_malformed_binary_path(value_part: str) -> str:
        """
        Clean up malformed binary paths from engine (e.g., quotes in wrong places).
        Example: "Z:/path/to/game"/exe.exe -> Z:/path/to/game/exe.exe
        """
        cleaned = value_part.strip()
        # Remove quotes if they wrap only part of the path (malformed)
        if cleaned.startswith('"') and '"' in cleaned[1:]:
            # Find the closing quote
            quote_end = cleaned.find('"', 1)
            if quote_end > 0:
                # Check if there's content after the quote (malformed)
                after_quote = cleaned[quote_end + 1:].strip()
                if after_quote.startswith('/') or after_quote:
                    # Malformed: quotes wrap only part of path
                    # Remove quotes and join
                    path_part = cleaned[1:quote_end]
                    remaining = after_quote.lstrip('/')
                    cleaned = f"{path_part}/{remaining}" if remaining else path_part
                    logger.info(f"Cleaned malformed binary path: {value_part} -> {cleaned}")
        # Remove any remaining quotes (handles fully quoted paths too)
        cleaned = cleaned.strip('"')
        # Normalize slashes
        cleaned = cleaned.replace('\\', '/')
        return cleaned

    @staticmethod
    def _format_binary_for_mo2(path: str) -> str:
        import re
        path = path.replace('\\', '/')
        # Collapse multiple forward slashes after drive letter
        path = re.sub(r'^([A-Z]:)//+', r'\1/', path)
        return path

    @staticmethod
    def _format_workingdir_for_mo2(path: str) -> str:
        import re
        path = path.replace('/', '\\')
        path = path.replace('\\', '\\\\')  # Double all backslashes
        # Ensure only one double backslash after drive letter
        path = re.sub(r'^([A-Z]:)\\\\+', r'\1\\\\', path)
        return path

# --- End of PathHandler --- 