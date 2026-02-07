"""Registry operations mixin for AutomatedPrefixService."""
import os
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RegistryOperationsMixin:
    """Mixin providing Wine/Proton registry operations."""

    def _update_registry_path(self, system_reg_path: str, section_name: str, path_key: str, new_path: str) -> bool:
        """Update a specific path value in Wine registry, preserving other entries"""
        if not os.path.exists(system_reg_path):
            return False
            
        try:
            # Read existing content
            with open(system_reg_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            in_target_section = False
            path_updated = False
            
            # Determine Wine drive letter based on SD card detection
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.handlers.path_handler import PathHandler
            
            linux_path = Path(new_path)
            
            if FileSystemHandler.is_sd_card(linux_path):
                # SD card paths use D: drive
                # Strip SD card prefix using the same method as other handlers
                relative_sd_path_str = PathHandler._strip_sdcard_path_prefix(linux_path)
                wine_path = relative_sd_path_str.replace('/', '\\\\')
                wine_drive = "D:"
                logger.debug(f"SD card path detected: {new_path} -> D:\\{wine_path}")
            else:
                # Regular paths use Z: drive with full path
                wine_path = new_path.strip('/').replace('/', '\\\\')
                wine_drive = "Z:"
                logger.debug(f"Regular path: {new_path} -> Z:\\{wine_path}")
            
            # Update existing path if found
            for i, line in enumerate(lines):
                stripped_line = line.strip()
                # Case-insensitive comparison for section name (Wine registry is case-insensitive)
                if stripped_line.split(']')[0].lower() + ']' == section_name.lower() if ']' in stripped_line else stripped_line.lower() == section_name.lower():
                    in_target_section = True
                elif stripped_line.startswith('[') and in_target_section:
                    in_target_section = False
                elif in_target_section and f'"{path_key}"' in line:
                    lines[i] = f'"{path_key}"="{wine_drive}\\\\{wine_path}\\\\"\n'  # Add trailing backslashes
                    path_updated = True
                    break
            
            # Add new section if path wasn't updated
            if not path_updated:
                lines.append(f'\n{section_name}\n')
                lines.append(f'"{path_key}"="{wine_drive}\\\\{wine_path}\\\\"\n')  # Add trailing backslashes
            
            # Write updated content
            with open(system_reg_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to update registry path: {e}")
            return False

    def _apply_universal_dotnet_fixes(self, modlist_compatdata_path: str):
        """Apply universal dotnet4.x compatibility registry fixes to ALL modlists"""
        try:
            prefix_path = os.path.join(modlist_compatdata_path, "pfx")
            if not os.path.exists(prefix_path):
                logger.warning(f"Prefix path not found: {prefix_path}")
                return False

            logger.info("Applying universal dotnet4.x compatibility registry fixes...")

            # Find the appropriate Wine binary to use for registry operations
            wine_binary = self._find_wine_binary_for_registry(modlist_compatdata_path)
            if not wine_binary:
                logger.error("Could not find Wine binary for registry operations")
                return False

            # Set environment for Wine registry operations
            env = os.environ.copy()
            env['WINEPREFIX'] = prefix_path
            env['WINEDEBUG'] = '-all'  # Suppress Wine debug output

            # Registry fix 1: Set *mscoree=native DLL override (asterisk for full override)
            # Use native .NET runtime instead of Wine's
            logger.debug("Setting *mscoree=native DLL override...")
            cmd1 = [
                wine_binary, 'reg', 'add',
                'HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides',
                '/v', '*mscoree', '/t', 'REG_SZ', '/d', 'native', '/f'
            ]

            result1 = subprocess.run(cmd1, env=env, capture_output=True, text=True, errors='replace')
            if result1.returncode == 0:
                logger.info("Successfully applied *mscoree=native DLL override")
            else:
                logger.warning(f"Failed to set *mscoree DLL override: {result1.stderr}")

            # Registry fix 2: Set OnlyUseLatestCLR=1
            # Use latest CLR to avoid .NET version conflicts
            logger.debug("Setting OnlyUseLatestCLR=1 registry entry...")
            cmd2 = [
                wine_binary, 'reg', 'add',
                'HKEY_LOCAL_MACHINE\\Software\\Microsoft\\.NETFramework',
                '/v', 'OnlyUseLatestCLR', '/t', 'REG_DWORD', '/d', '1', '/f'
            ]

            result2 = subprocess.run(cmd2, env=env, capture_output=True, text=True, errors='replace')
            if result2.returncode == 0:
                logger.info("Successfully applied OnlyUseLatestCLR=1 registry entry")
            else:
                logger.warning(f"Failed to set OnlyUseLatestCLR: {result2.stderr}")

            # Both fixes applied - this should eliminate dotnet4.x installation requirements
            if result1.returncode == 0 and result2.returncode == 0:
                logger.info("Universal dotnet4.x compatibility fixes applied successfully")
                return True
            else:
                logger.warning("Some dotnet4.x registry fixes failed, but continuing...")
                return False

        except Exception as e:
            logger.error(f"Failed to apply universal dotnet4.x fixes: {e}")
            return False

    def _find_wine_binary_for_registry(self, modlist_compatdata_path: str) -> Optional[str]:
        """Find the appropriate Wine binary for registry operations"""
        try:
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils
            
            # Method 1: Use the user's configured Proton version from settings
            config_handler = ConfigHandler()
            user_proton_path = config_handler.get_game_proton_path()

            if user_proton_path and user_proton_path != 'auto':
                # User has selected a specific Proton version
                proton_path = Path(user_proton_path).expanduser()

                # Check for wine binary in both GE-Proton and Valve Proton structures
                wine_candidates = [
                    proton_path / "files" / "bin" / "wine",  # GE-Proton structure
                    proton_path / "dist" / "bin" / "wine"    # Valve Proton structure
                ]

                for wine_path in wine_candidates:
                    if wine_path.exists() and wine_path.is_file():
                        logger.info(f"Using Wine binary from user's configured Proton: {wine_path}")
                        return str(wine_path)

                # Wine binary not found at expected paths - search recursively in Proton directory
                logger.debug(f"Wine binary not found at expected paths in {proton_path}, searching recursively...")
                wine_binary = self._search_wine_in_proton_directory(proton_path)
                if wine_binary:
                    logger.info(f"Found Wine binary via recursive search in Proton directory: {wine_binary}")
                    return wine_binary

                logger.warning(f"User's configured Proton path has no wine binary: {user_proton_path}")

            # Method 2: Fallback to auto-detection using WineUtils
            best_proton = WineUtils.select_best_proton()
            if best_proton:
                wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                if wine_binary:
                    logger.info(f"Using Wine binary from detected Proton: {wine_binary}")
                    return wine_binary

            # NEVER fall back to system wine - it will break Proton prefixes with architecture mismatches
            logger.error("No suitable Proton Wine binary found for registry operations")
            return None

        except Exception as e:
            logger.error(f"Error finding Wine binary: {e}")
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
                try:
                    depth = len(Path(root).relative_to(proton_path).parts)
                except ValueError:
                    # Path is not relative to proton_path (shouldn't happen, but be safe)
                    continue
                    
                if depth > max_depth:
                    dirs.clear()  # Don't descend further
                    continue
                
                # Check if 'wine' is in this directory
                if 'wine' in files:
                    wine_path = Path(root) / 'wine'
                    # Verify it's actually an executable file
                    if wine_path.is_file() and os.access(wine_path, os.X_OK):
                        logger.debug(f"Found wine binary at: {wine_path}")
                        return str(wine_path)

            return None
        except Exception as e:
            logger.debug(f"Error during recursive wine search in {proton_path}: {e}")
            return None

    def _inject_game_registry_entries(self, modlist_compatdata_path: str, special_game_type: str):
        """Detect and inject FNV/Enderal game paths and apply universal dotnet4.x compatibility fixes"""
        system_reg_path = os.path.join(modlist_compatdata_path, "pfx", "system.reg")
        if not os.path.exists(system_reg_path):
            logger.warning("system.reg not found, skipping game path injection")
            return

        logger.info("Detecting game registry entries...")

        # Universal dotnet4.x registry fixes applied in modlist_handler.py after .reg downloads
        
        # Game configurations
        games_config = {
            "22380": {  # Fallout New Vegas AppID
                "name": "Fallout New Vegas",
                "common_names": ["Fallout New Vegas", "FalloutNV"],
                "registry_section": "[Software\\\\Wow6432Node\\\\bethesda softworks\\\\falloutnv]",
                "path_key": "Installed Path"
            },
            "976620": {  # Enderal Special Edition AppID
                "name": "Enderal",
                "common_names": ["Enderal: Forgotten Stories (Special Edition)", "Enderal Special Edition", "Enderal"],
                "registry_section": "[Software\\\\Wow6432Node\\\\SureAI\\\\Enderal SE]", 
                "path_key": "installed path"
            }
        }
        
        # Detect and inject each game
        for app_id, config in games_config.items():
            game_path = self._find_steam_game(app_id, config["common_names"])
            if game_path:
                logger.info(f"Detected {config['name']} at: {game_path}")
                success = self._update_registry_path(
                    system_reg_path,
                    config["registry_section"], 
                    config["path_key"],
                    game_path
                )
                if success:
                    logger.info(f"Updated registry entry for {config['name']}")
                else:
                    logger.warning(f"Failed to update registry entry for {config['name']}")
            else:
                logger.debug(f"{config['name']} not found in Steam libraries")
                
        logger.info("Game registry injection completed")

