"""STL algorithm methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional
import logging
import vdf
import binascii

logger = logging.getLogger(__name__)


class STLAlgorithmMixin:
    """Mixin providing Steam Tools Library algorithm methods for AutomatedPrefixService."""

    def generate_steam_short_id(self, signed_appid: int) -> int:
        """
        Convert signed 32-bit integer to unsigned 32-bit integer (same as STL's generateSteamShortID).
        
        Args:
            signed_appid: Signed 32-bit integer AppID
            
        Returns:
            Unsigned 32-bit integer AppID
        """
        return signed_appid & 0xFFFFFFFF

    def find_appid_in_shortcuts_vdf(self, shortcut_name: str) -> Optional[str]:
        """
        Find the AppID for a shortcut by name directly in shortcuts.vdf.
        This is a fallback method when protontricks detection fails.
        
        Args:
            shortcut_name: Name of the shortcut to find
            
        Returns:
            AppID as string, or None if not found
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return None
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            
            # Look for shortcut by name
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                
                if shortcut_name == name:
                    appid = shortcut.get('appid')
                    if appid:
                        logger.info(f"Found AppID {appid} for shortcut '{shortcut_name}' in shortcuts.vdf")
                        return str(appid)
            
            logger.warning(f"Shortcut '{shortcut_name}' not found in shortcuts.vdf")
            return None
            
        except Exception as e:
            logger.error(f"Error finding AppID in shortcuts.vdf: {e}")
            return None

    def predict_appid_using_stl_algorithm(self, shortcut_name: str, exe_path: str) -> Optional[int]:
        """
        Predict the AppID using SteamTinkerLaunch's exact algorithm.
        
        This implements the same logic as STL's generateShortcutVDFAppId and generateSteamShortID functions:
        1. Combine AppName + ExePath
        2. Generate MD5 hash, take first 8 characters
        3. Convert to decimal, make negative, ensure < 1 billion
        4. Convert to unsigned 32-bit integer
        
        Args:
            shortcut_name: Name of the shortcut
            exe_path: Path to the executable
            
        Returns:
            Predicted AppID as integer, or None if failed
        """
        try:
            import hashlib
            
            # Step 1: Combine AppName + ExePath (exactly like STL)
            combined_string = f"{shortcut_name}{exe_path}"
            logger.debug(f"Combined string for AppID prediction: '{combined_string}'")
            
            # Step 2: Generate MD5 hash and take first 8 characters
            md5_hash = hashlib.md5(combined_string.encode()).hexdigest()
            seed_hex = md5_hash[:8]
            logger.debug(f"MD5 hash: {md5_hash}, seed hex: {seed_hex}")
            
            # Step 3: Convert to decimal, make negative, ensure < 1 billion
            seed_decimal = int(seed_hex, 16)
            signed_appid = -(seed_decimal % 1000000000)
            logger.debug(f"Seed decimal: {seed_decimal}, signed AppID: {signed_appid}")
            
            # Step 4: Convert to unsigned 32-bit integer (STL's generateSteamShortID)
            unsigned_appid = signed_appid & 0xFFFFFFFF
            logger.debug(f"Unsigned AppID: {unsigned_appid}")
            
            logger.info(f"Predicted AppID using STL algorithm: {unsigned_appid} (signed: {signed_appid})")
            return unsigned_appid
            
        except Exception as e:
            logger.error(f"Error predicting AppID using STL algorithm: {e}")
            return None

    def create_shortcut_with_stl_algorithm(self, shortcut_name: str, exe_path: str, start_dir: str, compatibility_tool: str = None) -> bool:
        """
        Create a shortcut using STL's exact algorithm for consistent AppID calculation.
        
        Args:
            shortcut_name: Name of the shortcut
            exe_path: Path to the executable
            start_dir: Start directory
            compatibility_tool: Optional compatibility tool to set immediately (like STL does)
            
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
            
            # Find the next available index
            next_index = str(len(shortcuts))
            
            # Calculate AppID using STL's algorithm
            predicted_appid = self.predict_appid_using_stl_algorithm(shortcut_name, exe_path)
            if not predicted_appid:
                logger.error("Failed to predict AppID for shortcut creation")
                return False
            
            # Convert to signed AppID (STL stores the signed version in shortcuts.vdf)
            signed_appid = predicted_appid
            if predicted_appid > 0x7FFFFFFF:  # If it's a large positive number, make it negative
                signed_appid = predicted_appid - 0x100000000
            
            # Create new shortcut entry
            new_shortcut = {
                'AppName': shortcut_name,
                'Exe': f'"{exe_path}"',
                'StartDir': f'"{start_dir}"',
                'appid': signed_appid,  # Use the signed AppID
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
                'IsInstalled': 1  # Make it appear in "Locally Installed" filter
            }
            
            # Add the new shortcut
            shortcuts[next_index] = new_shortcut
            
            # Write back to file
            with open(shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts_data, f)
            
            logger.info(f"Created shortcut with STL algorithm: {shortcut_name} with AppID {signed_appid} (unsigned: {predicted_appid})")
            
            # Set compatibility tool immediately if provided (like STL does)
            if compatibility_tool:
                logger.info(f"Setting compatibility tool immediately: {compatibility_tool}")
                success = self.set_compatibility_tool_complete_stl_style(predicted_appid, compatibility_tool)
                if not success:
                    logger.warning("Failed to set compatibility tool immediately")
            
            return True
            
        except Exception as e:
            logger.error(f"Error creating shortcut with STL algorithm: {e}")
            return False

