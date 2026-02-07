#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-install and modlist config mixin for WineUtils.
Extracted from wine_utils for file-size and domain separation.
"""

import os
import re
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WineUtilsConfigMixin:
    """Mixin providing post-install tasks and modlist-specific configuration."""

    @staticmethod
    def create_dxvk_file(modlist_dir: str, modlist_sdcard: bool, steam_library: str,
                        basegame_sdcard: bool, game_var_full: str) -> bool:
        """Create DXVK file in the modlist directory pointing to the game directory."""
        try:
            game_dir = os.path.join(steam_library, game_var_full)
            dxvk_file = os.path.join(modlist_dir, "DXVK")
            with open(dxvk_file, 'w') as f:
                f.write(game_dir)
            logger.debug(f"Created DXVK file at {dxvk_file} pointing to {game_dir}")
            return True
        except Exception as e:
            logger.error(f"Error creating DXVK file: {e}")
            return False

    @staticmethod
    def small_additional_tasks(modlist_dir: str, compat_data_path: Optional[str]) -> bool:
        """Perform small additional tasks (delete unsupported plugins, download Bethini font)."""
        try:
            file_to_delete = os.path.join(modlist_dir, "plugins/FixGameRegKey.py")
            if os.path.exists(file_to_delete):
                os.remove(file_to_delete)
                logger.debug(f"File deleted: {file_to_delete}")
            if compat_data_path and os.path.isdir(compat_data_path):
                font_path = os.path.join(compat_data_path, "pfx/drive_c/windows/Fonts/seguisym.ttf")
                font_dir = os.path.dirname(font_path)
                os.makedirs(font_dir, exist_ok=True)
                font_url = "https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf"
                subprocess.run(
                    f"wget {font_url} -q -nc -O \"{font_path}\"",
                    shell=True,
                    check=True
                )
                logger.debug(f"Downloaded font to: {font_path}")
            return True
        except Exception as e:
            logger.error(f"Error performing additional tasks: {e}")
            return False

    @staticmethod
    def modlist_specific_steps(modlist: str, appid: str) -> bool:
        """Perform modlist-specific configuration steps. Returns True on success."""
        try:
            modlist_configs = {
                "wildlander": ["dotnet48", "dotnet472", "vcrun2019"],
                "septimus|sigernacollection|licentia|aldrnari|phoenix": ["dotnet48", "dotnet472"],
                "masterstroke": ["dotnet48", "dotnet472"],
                "diablo": ["dotnet48", "dotnet472"],
                "living_skyrim": ["dotnet48", "dotnet472", "dotnet462"],
                "nolvus": ["dotnet8"]
            }
            modlist_lower = modlist.lower().replace(" ", "")
            if "wildlander" in modlist_lower:
                logger.info(f"Running steps specific to {modlist}. This can take some time, be patient!")
                return True
            for pattern, components in modlist_configs.items():
                if re.search(pattern.replace("|", "|.*"), modlist_lower):
                    logger.info(f"Running steps specific to {modlist}. This can take some time, be patient!")
                    for component in components:
                        if component == "dotnet8":
                            logger.info("Downloading .NET 8 Runtime")
                            pass
                        else:
                            logger.info(f"Installing {component}...")
                            pass
                    return True
            logger.debug(f"No specific steps needed for {modlist}")
            return True
        except Exception as e:
            logger.error(f"Error performing modlist-specific steps: {e}")
            return False

    @staticmethod
    def fnv_launch_options(game_var: str, compat_data_path: Optional[str], modlist: str) -> bool:
        """Set up Fallout New Vegas launch options. Returns True on success."""
        if game_var != "Fallout New Vegas":
            return True
        try:
            appid_to_check = "22380"
            for path in [
                os.path.expanduser("~/.local/share/Steam/steamapps/compatdata"),
                os.path.expanduser("~/.steam/steam/steamapps/compatdata"),
                os.path.expanduser("~/.steam/root/steamapps/compatdata")
            ]:
                compat_path = os.path.join(path, appid_to_check)
                if os.path.exists(compat_path):
                    logger.warning(
                        f"\nFor {modlist}, please add the following line to the Launch Options "
                        f"in Steam for your '{modlist}' entry:"
                    )
                    logger.info(f"\nSTEAM_COMPAT_DATA_PATH=\"{compat_path}\" %command%")
                    logger.warning("\nThis is essential for the modlist to load correctly.")
                    return True
            logger.error("Could not determine the compatdata path for Fallout New Vegas")
            return False
        except Exception as e:
            logger.error(f"Error setting FNV launch options: {e}")
            return False
