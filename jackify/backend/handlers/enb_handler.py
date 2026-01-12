#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENB Handler Module
Handles ENB detection and Linux compatibility configuration for modlists.
"""

import logging
import configparser
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class ENBHandler:
    """
    Handles ENB detection and configuration for Linux compatibility.
    
    Detects ENB components in modlist installations and ensures enblocal.ini
    has the required LinuxVersion=true setting in the [GLOBAL] section.
    """
    
    def __init__(self):
        """Initialize ENB handler."""
        self.logger = logger
    
    def detect_enb_in_modlist(self, modlist_path: Path) -> Dict[str, Any]:
        """
        Detect ENB components in modlist installation.
        
        Searches for ENB configuration files:
        - enbseries.ini, enblocal.ini (ENB configuration files)
        
        Note: Does NOT check for DLL files (d3d9.dll, d3d11.dll, dxgi.dll) as these
        are used by many other mods (ReShade, other graphics mods) and are not
        reliable indicators of ENB presence.
        
        Args:
            modlist_path: Path to modlist installation directory
            
        Returns:
            Dict with detection results:
            - has_enb: bool - True if ENB config files found
            - enblocal_ini: str or None - Path to enblocal.ini if found
            - enbseries_ini: str or None - Path to enbseries.ini if found
            - d3d9_dll: str or None - Always None (not checked)
            - d3d11_dll: str or None - Always None (not checked)
            - dxgi_dll: str or None - Always None (not checked)
        """
        enb_info = {
            'has_enb': False,
            'enblocal_ini': None,
            'enbseries_ini': None,
            'd3d9_dll': None,
            'd3d11_dll': None,
            'dxgi_dll': None
        }
        
        if not modlist_path.exists():
            self.logger.warning(f"Modlist path does not exist: {modlist_path}")
            return enb_info
        
        # Search for ENB indicator files
        # IMPORTANT: Only check for ENB config files (enbseries.ini, enblocal.ini)
        # Do NOT check for DLL files (d3d9.dll, d3d11.dll, dxgi.dll) as these are used
        # by many other mods (ReShade, other graphics mods) and are not reliable ENB indicators
        
        enb_config_patterns = [
            ('**/enbseries.ini', 'enbseries_ini'),
            ('**/enblocal.ini', 'enblocal_ini')
        ]
        
        for pattern, key in enb_config_patterns:
            for file_path in modlist_path.glob(pattern):
                # Skip backups and plugin data directories
                if "Backup" in str(file_path) or "plugins/data" in str(file_path):
                    continue
                
                enb_info['has_enb'] = True
                if not enb_info[key]:  # Store first match
                    enb_info[key] = str(file_path)
        
        # If we detected ENB config but didn't find enblocal.ini via glob,
        # use the priority-based finder
        if enb_info['has_enb'] and not enb_info['enblocal_ini']:
            found_ini = self.find_enblocal_ini(modlist_path)
            if found_ini:
                enb_info['enblocal_ini'] = str(found_ini)
        
        return enb_info
    
    def find_enblocal_ini(self, modlist_path: Path) -> Optional[Path]:
        """
        Find enblocal.ini in modlist installation using priority-based search.
        
        Search order (highest priority first):
        1. Stock Game/Game Root directories (active locations)
        2. Mods folder with Root/root subfolder (most common pattern)
        3. Direct in mods/fixes folders
        4. Fallback recursive search (excluding backups)
        
        Args:
            modlist_path: Path to modlist installation directory
            
        Returns:
            Path to enblocal.ini if found, None otherwise
        """
        if not modlist_path.exists():
            return None
        
        # Priority 1: Stock Game/Game Root (active locations)
        stock_game_names = [
            "Stock Game",
            "Game Root",
            "STOCK GAME",
            "Stock Game Folder",
            "Stock Folder",
            "Skyrim Stock"
        ]
        
        for name in stock_game_names:
            candidate = modlist_path / name / "enblocal.ini"
            if candidate.exists():
                self.logger.debug(f"Found enblocal.ini in Stock Game location: {candidate}")
                return candidate
        
        # Priority 2: Mods folder with Root/root subfolder
        mods_dir = modlist_path / "mods"
        if mods_dir.exists():
            # Search for Root/root subfolders
            for root_dir in mods_dir.rglob("Root"):
                candidate = root_dir / "enblocal.ini"
                if candidate.exists():
                    self.logger.debug(f"Found enblocal.ini in mods/Root: {candidate}")
                    return candidate
            
            for root_dir in mods_dir.rglob("root"):
                candidate = root_dir / "enblocal.ini"
                if candidate.exists():
                    self.logger.debug(f"Found enblocal.ini in mods/root: {candidate}")
                    return candidate
        
        # Priority 3: Direct in mods/fixes folders
        for search_dir in [modlist_path / "mods", modlist_path / "fixes"]:
            if search_dir.exists():
                for enb_file in search_dir.rglob("enblocal.ini"):
                    # Skip backups and plugin data
                    if "Backup" not in str(enb_file) and "plugins/data" not in str(enb_file):
                        self.logger.debug(f"Found enblocal.ini in {search_dir.name}: {enb_file}")
                        return enb_file
        
        # Priority 4: Fallback recursive search (exclude backups)
        for enb_file in modlist_path.rglob("enblocal.ini"):
            if "Backup" not in str(enb_file) and "plugins/data" not in str(enb_file):
                self.logger.debug(f"Found enblocal.ini via recursive search: {enb_file}")
                return enb_file
        
        return None
    
    def ensure_linux_version_setting(self, enblocal_ini_path: Path) -> bool:
        """
        Safely ensure [GLOBAL] section exists with LinuxVersion=true in enblocal.ini.
        
        Safety features:
        - Verifies file exists before attempting modification
        - Checks if [GLOBAL] section exists before adding (prevents duplicates)
        - Creates backup before any write operation
        - Only writes if changes are actually needed
        - Handles encoding issues gracefully
        - Preserves existing file structure and comments
        
        Args:
            enblocal_ini_path: Path to enblocal.ini file
            
        Returns:
            bool: True if successful or no changes needed, False on error
        """
        try:
            # Safety check: file must exist
            if not enblocal_ini_path.exists():
                self.logger.warning(f"enblocal.ini not found at: {enblocal_ini_path}")
                return False
            
            # Read existing INI with same settings as modlist_handler.py
            config = configparser.ConfigParser(
                allow_no_value=True,
                delimiters=['=']
            )
            config.optionxform = str  # Preserve case sensitivity
            
            # Read with encoding handling (same pattern as modlist_handler.py)
            try:
                with open(enblocal_ini_path, 'r', encoding='utf-8-sig') as f:
                    config.read_file(f)
            except UnicodeDecodeError:
                with open(enblocal_ini_path, 'r', encoding='latin-1') as f:
                    config.read_file(f)
            except configparser.DuplicateSectionError as e:
                # If file has duplicate [GLOBAL] sections, log warning and skip
                self.logger.warning(f"enblocal.ini has duplicate sections: {e}. Skipping modification.")
                return False
            
            # Check if [GLOBAL] section exists (case-insensitive check)
            global_section_exists = False
            global_section_name = None
            
            # Find existing [GLOBAL] section (case-insensitive)
            for section_name in config.sections():
                if section_name.upper() == 'GLOBAL':
                    global_section_exists = True
                    global_section_name = section_name  # Use actual case
                    break
            
            # Check current LinuxVersion value
            needs_update = False
            if global_section_exists:
                # Section exists - check if LinuxVersion needs updating
                current_value = config.get(global_section_name, 'LinuxVersion', fallback=None)
                if current_value is None or current_value.lower() != 'true':
                    needs_update = True
            else:
                # Section doesn't exist - we need to add it
                needs_update = True
            
            # If no changes needed, return success
            if not needs_update:
                self.logger.debug(f"enblocal.ini already has LinuxVersion=true in [GLOBAL] section")
                return True
            
            # Changes needed - create backup first
            backup_path = enblocal_ini_path.with_suffix('.ini.jackify_backup')
            try:
                if not backup_path.exists():
                    shutil.copy2(enblocal_ini_path, backup_path)
                    self.logger.debug(f"Created backup: {backup_path}")
            except Exception as e:
                self.logger.warning(f"Failed to create backup: {e}. Proceeding anyway.")
            
            # Make changes
            if not global_section_exists:
                # Add [GLOBAL] section (configparser will use exact case 'GLOBAL')
                config.add_section('GLOBAL')
                global_section_name = 'GLOBAL'
                self.logger.debug("Added [GLOBAL] section to enblocal.ini")
            
            # Set LinuxVersion=true
            config.set(global_section_name, 'LinuxVersion', 'true')
            self.logger.debug(f"Set LinuxVersion=true in [GLOBAL] section")
            
            # Write back to file
            with open(enblocal_ini_path, 'w', encoding='utf-8') as f:
                config.write(f, space_around_delimiters=False)
            
            self.logger.info(f"Successfully configured enblocal.ini: {enblocal_ini_path}")
            return True
            
        except configparser.DuplicateSectionError as e:
            # Handle duplicate sections gracefully
            self.logger.error(f"enblocal.ini has duplicate [GLOBAL] sections: {e}")
            return False
        except configparser.Error as e:
            # Handle other configparser errors
            self.logger.error(f"ConfigParser error reading enblocal.ini: {e}")
            return False
        except Exception as e:
            # Handle any other errors
            self.logger.error(f"Unexpected error configuring enblocal.ini: {e}", exc_info=True)
            return False
    
    def configure_enb_for_linux(self, modlist_path: Path) -> Tuple[bool, Optional[str], bool]:
        """
        Main entry point: detect ENB and configure enblocal.ini.
        
        Safe for modlists without ENB - returns success with no message.
        
        Args:
            modlist_path: Path to modlist installation directory
            
        Returns:
            Tuple[bool, Optional[str], bool]: (success, message, enb_detected)
            - success: True if successful or no ENB detected, False on error
            - message: Human-readable message (None if no action taken)
            - enb_detected: True if ENB was detected, False otherwise
        """
        try:
            # Step 1: Detect ENB (safe - just searches for files)
            enb_info = self.detect_enb_in_modlist(modlist_path)
            enb_detected = enb_info.get('has_enb', False)
            
            # Step 2: If no ENB detected, return success (no action needed)
            if not enb_detected:
                return (True, None, False)  # Safe: no ENB, nothing to do
            
            # Step 3: Find enblocal.ini
            enblocal_path = enb_info.get('enblocal_ini')
            if not enblocal_path:
                # ENB detected but no enblocal.ini found - this is unusual but not an error
                self.logger.warning("ENB detected but enblocal.ini not found - may be configured elsewhere")
                return (True, None, True)  # ENB detected but no config file
            
            # Step 4: Configure enblocal.ini (safe method with all checks)
            enblocal_path_obj = Path(enblocal_path)
            success = self.ensure_linux_version_setting(enblocal_path_obj)
            
            if success:
                return (True, "ENB configured for Linux compatibility", True)
            else:
                # Non-blocking: log error but don't fail workflow
                return (False, "Failed to configure ENB (see logs for details)", True)
                
        except Exception as e:
            # Catch-all error handling - never break the workflow
            self.logger.error(f"Error in ENB configuration: {e}", exc_info=True)
            return (False, "ENB configuration error (see logs)", False)

