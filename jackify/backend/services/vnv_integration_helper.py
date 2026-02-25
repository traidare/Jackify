"""
VNV Integration Helper

Helper functions to integrate VNV post-install automation into modlist workflows.
Handles detection, confirmation, and execution for:
- Install Modlist
- Configure New Modlist
- Configure Existing Modlist
"""

import logging
import configparser
import re
from pathlib import Path
from typing import Optional, Callable, Tuple

from .vnv_post_install_service import VNVPostInstallService

logger = logging.getLogger(__name__)


def _parse_bytearray_value(value: str) -> str:
    """
    Parse Qt @ByteArray format to extract the actual string value.
    
    Format: @ByteArray(Viva New Vegas Extended)
    Returns: Viva New Vegas Extended
    """
    match = re.match(r'@ByteArray\((.*)\)', value)
    if match:
        return match.group(1)
    return value


def _check_modorganizer_ini_profile(modlist_install_location: Path) -> bool:
    """
    Check ModOrganizer.ini for VNV profile names.
    
    Args:
        modlist_install_location: Path to modlist installation directory
        
    Returns:
        True if selected_profile is "Viva New Vegas" or "Viva New Vegas Extended"
    """
    try:
        mo_ini_path = modlist_install_location / "ModOrganizer.ini"
        if not mo_ini_path.exists():
            logger.debug(f"ModOrganizer.ini not found at {mo_ini_path}")
            return False

        config = configparser.ConfigParser()
        # Read with UTF-8-sig to handle BOM
        config.read(mo_ini_path, encoding='utf-8-sig')
        
        if 'General' not in config:
            logger.debug("No [General] section in ModOrganizer.ini")
            return False
        
        selected_profile_raw = config.get('General', 'selected_profile', fallback='')
        if not selected_profile_raw:
            logger.debug("No selected_profile in ModOrganizer.ini")
            return False
        
        # Parse @ByteArray format
        selected_profile = _parse_bytearray_value(selected_profile_raw)
        logger.debug(f"Found selected_profile: {selected_profile}")
        
        # Check if it's one of the VNV profiles
        vnv_profiles = ["Viva New Vegas", "Viva New Vegas Extended"]
        return selected_profile in vnv_profiles
        
    except Exception as e:
        logger.debug(f"Error checking ModOrganizer.ini for VNV profile: {e}")
        return False


def should_offer_vnv_automation(modlist_name: str, modlist_install_location: Optional[Path] = None) -> bool:
    """
    Check if VNV automation should be offered for this modlist.
    
    Detection methods (in order of reliability):
    1. Check ModOrganizer.ini selected_profile (most reliable)
    2. Check modlist name for VNV patterns
    
    Args:
        modlist_name: Name of the modlist
        modlist_install_location: Optional path to modlist installation directory
        
    Returns:
        True if VNV automation should be offered
    """
    # Method 1: Check ModOrganizer.ini profile (most reliable)
    if modlist_install_location:
        if _check_modorganizer_ini_profile(modlist_install_location):
            logger.info(f"VNV detected via ModOrganizer.ini profile in {modlist_install_location}")
            return True
    
    # Method 2: Check modlist name patterns
    modlist_name_lower = modlist_name.lower()
    vnv_patterns = [
        "viva new vegas",
        "vnv",  # Common abbreviation
        "viva new vegas extended"
    ]
    
    for pattern in vnv_patterns:
        if pattern in modlist_name_lower:
            logger.info(f"VNV detected via name pattern '{pattern}' in '{modlist_name}'")
            return True
    
    return False


def run_vnv_automation_if_applicable(
    modlist_name: str,
    modlist_install_location: Path,
    game_root: Optional[Path],
    ttw_installer_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    manual_file_callback: Optional[Callable[[str, str], Optional[Path]]] = None,
    confirmation_callback: Optional[Callable[[str], bool]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if VNV automation should run, get user confirmation, and execute if confirmed.

    Args:
        modlist_name: Name of the installed modlist
        modlist_install_location: Path to modlist installation
        game_root: Path to game root directory
        ttw_installer_path: Optional path to TTW_Linux_Installer (for BSA decompression)
        progress_callback: Optional callback for progress updates
        manual_file_callback: Optional callback for manual file selection (non-Premium)
        confirmation_callback: Optional callback for user confirmation
                              Takes description string, returns True if user confirms

    Returns:
        Tuple of (automation_was_run: bool, error_message: Optional[str])
    """
    try:
        # Check if this is VNV (pass install location for ModOrganizer.ini check)
        if not should_offer_vnv_automation(modlist_name, modlist_install_location):
            logger.debug(f"Modlist '{modlist_name}' does not require VNV automation")
            return False, None

        logger.info(f"VNV detected: {modlist_name}")

        # Resolve game root for Fallout New Vegas if caller didn't provide one.
        # CLI flows may pass None and rely on auto-detection.
        resolved_game_root = game_root
        if resolved_game_root is None:
            try:
                from jackify.backend.handlers.path_handler import PathHandler
                game_paths = PathHandler().find_vanilla_game_paths()
                resolved_game_root = game_paths.get('Fallout New Vegas')
            except Exception as detect_err:
                logger.debug(f"VNV game root auto-detection failed: {detect_err}")

        if resolved_game_root is None:
            logger.warning("VNV detected but Fallout New Vegas game root could not be resolved")
            if progress_callback:
                progress_callback("VNV automation skipped: Fallout New Vegas path not found")
            return False, None

        # Initialize service
        vnv_service = VNVPostInstallService(
            modlist_install_location=modlist_install_location,
            game_root=resolved_game_root,
            ttw_installer_path=ttw_installer_path
        )

        # Check what's already done
        completed = vnv_service.check_already_completed()
        # Only skip if ALL three steps are completed
        if completed['root_mods'] and completed['4gb_patch'] and completed['bsa_decompressed']:
            logger.info("VNV automation steps already completed")
            if progress_callback:
                progress_callback("VNV post-install steps already completed")
            return False, None

        # Get confirmation from user (required)
        if not confirmation_callback:
            logger.error("VNV automation requires confirmation_callback")
            return False, "VNV automation requires user confirmation"
        
        if confirmation_callback:
            description = vnv_service.get_automation_description()
            if not confirmation_callback(description):
                logger.info("User declined VNV automation")
                if progress_callback:
                    progress_callback("VNV automation skipped by user")
                return False, None

        # Run automation
        logger.info("Starting VNV post-install automation")
        if progress_callback:
            progress_callback("Running VNV post-install automation...")

        success, message = vnv_service.run_all_steps(
            progress_callback=progress_callback,
            manual_file_callback=manual_file_callback
        )

        if success:
            logger.info(f"VNV automation completed: {message}")
            if progress_callback:
                progress_callback(f"VNV automation: {message}")
            return True, None
        else:
            logger.error(f"VNV automation failed: {message}")
            return True, message

    except Exception as e:
        error_msg = f"VNV automation error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return True, error_msg
