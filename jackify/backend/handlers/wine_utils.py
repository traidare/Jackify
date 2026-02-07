#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wine Utilities Module
Handles wine-related operations and utilities.
Proton and config logic live in mixins (wine_utils_proton, wine_utils_config).
"""

import os
import re
import subprocess
import logging
from pathlib import Path
from typing import Optional

from .subprocess_utils import get_clean_subprocess_env
from .wine_utils_proton import WineUtilsProtonMixin, VALVE_PROTON_APPID_MAP
from .wine_utils_config import WineUtilsConfigMixin

logger = logging.getLogger(__name__)

# Re-export for any code that imports from wine_utils
__all__ = ['WineUtils', 'VALVE_PROTON_APPID_MAP']


class WineUtils(WineUtilsProtonMixin, WineUtilsConfigMixin):
    """Utilities for wine-related operations. Proton and config logic in mixins."""

    @staticmethod
    def cleanup_wine_processes() -> bool:
        """Clean up wine processes. Returns True on success, False on failure."""
        try:
            processes = subprocess.run(
                "pgrep -f 'win7|win10|ShowDotFiles|protontricks'",
                shell=True,
                capture_output=True,
                text=True,
                env=get_clean_subprocess_env()
            ).stdout.strip()
            if processes:
                for pid in processes.split("\n"):
                    try:
                        subprocess.run(
                            f"kill -9 {pid}", shell=True, check=True,
                            env=get_clean_subprocess_env()
                        )
                    except subprocess.CalledProcessError:
                        logger.warning(f"Failed to kill process {pid}")
                logger.debug("Processes killed successfully")
            else:
                logger.debug("No matching processes found")
            subprocess.run("pkill -9 winetricks", shell=True, env=get_clean_subprocess_env())
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup wine processes: {e}")
            return False

    @staticmethod
    def _get_sd_card_mounts() -> list:
        """Detect SD card mount points using df. Returns list of mount paths from /run/media."""
        result = subprocess.run(['df', '-h'], capture_output=True, text=True, timeout=5)
        sd_mounts = []
        for line in result.stdout.split('\n'):
            if '/run/media' in line:
                parts = line.split()
                if len(parts) >= 6:
                    mount_point = parts[-1]
                    if mount_point.startswith('/run/media/'):
                        sd_mounts.append(mount_point)
        sd_mounts.sort(key=len, reverse=True)
        logger.debug(f"Detected SD card mounts from df: {sd_mounts}")
        return sd_mounts

    @staticmethod
    def _strip_sdcard_path(path: str) -> str:
        """Strip SD card mount prefix from path. Handles /run/media/deck/UUID and mmcblk0p1 patterns."""
        deck_pattern = r'^/run/media/deck/[^/]+(/.*)?$'
        match = re.match(deck_pattern, path)
        if match:
            stripped = match.group(1) if match.group(1) else "/"
            logger.debug(f"Stripped SD card path (deck pattern): {path} -> {stripped}")
            return stripped
        if path.startswith('/run/media/mmcblk0p1/'):
            stripped = path.replace('/run/media/mmcblk0p1', '', 1)
            logger.debug(f"Stripped SD card path (mmcblk pattern): {path} -> {stripped}")
            return stripped
        return path

    @staticmethod
    def edit_binary_working_paths(modlist_ini: str, modlist_dir: str, modlist_sdcard: bool,
                                  steam_library: str, basegame_sdcard: bool) -> bool:
        """Edit binary and working directory paths in ModOrganizer.ini. Returns True on success."""
        if not os.path.isfile(modlist_ini):
            logger.error(f"ModOrganizer.ini not found at {modlist_ini}")
            return False
        try:
            with open(modlist_ini, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
            modified_content = []
            found_skse = False
            skse_lines = []
            for i, line in enumerate(content):
                if re.search(r'skse64_loader\.exe|f4se_loader\.exe', line):
                    skse_lines.append((i, line))
                    found_skse = True
            if not found_skse:
                logger.debug("No SKSE/F4SE launcher entries found")
                return False
            for line_num, orig_line in skse_lines:
                if '=' not in orig_line:
                    continue
                binary_num, skse_loc = orig_line.split('=', 1)
                drive_letter = " = D:" if modlist_sdcard else " = Z:"
                just_num = binary_num.split('\\')[0]
                bin_path_start = binary_num.strip().replace('\\', '\\\\')
                path_start = f"{just_num}\\\\workingDirectory".replace('\\', '\\\\')
                if "mods" in orig_line:
                    path_middle = WineUtils._strip_sdcard_path(modlist_dir) if modlist_sdcard else modlist_dir
                    path_end = re.sub(r'.*/mods', '/mods', skse_loc.split('/')[0])
                    bin_path_end = re.sub(r'.*/mods', '/mods', skse_loc)
                elif any(term in orig_line for term in ["Stock Game", "Game Root", "STOCK GAME", "Stock Game Folder", "Stock Folder", "Skyrim Stock", "root/Skyrim Special Edition"]):
                    path_middle = WineUtils._strip_sdcard_path(modlist_dir) if modlist_sdcard else modlist_dir
                    if "Stock Game" in orig_line:
                        path_end = re.sub(r'.*/Stock Game', '/Stock Game', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Stock Game', '/Stock Game', skse_loc)
                    elif "Game Root" in orig_line:
                        path_end = re.sub(r'.*/Game Root', '/Game Root', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Game Root', '/Game Root', skse_loc)
                    elif "STOCK GAME" in orig_line:
                        path_end = re.sub(r'.*/STOCK GAME', '/STOCK GAME', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/STOCK GAME', '/STOCK GAME', skse_loc)
                    elif "Stock Folder" in orig_line:
                        path_end = re.sub(r'.*/Stock Folder', '/Stock Folder', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Stock Folder', '/Stock Folder', skse_loc)
                    elif "Skyrim Stock" in orig_line:
                        path_end = re.sub(r'.*/Skyrim Stock', '/Skyrim Stock', os.path.dirname(skse_loc))
                        bin_path_end = re.sub(r'.*/Skyrim Stock', '/Skyrim Stock', skse_loc)
                    elif "Stock Game Folder" in orig_line:
                        path_end = re.sub(r'.*/Stock Game Folder', '/Stock Game Folder', skse_loc)
                        bin_path_end = path_end
                    elif "root/Skyrim Special Edition" in orig_line:
                        path_end = '/' + skse_loc.lstrip()
                        bin_path_end = path_end
                    else:
                        logger.error(f"Unknown stock game type in line: {orig_line}")
                        continue
                elif "steamapps" in orig_line:
                    if basegame_sdcard:
                        path_middle = WineUtils._strip_sdcard_path(steam_library)
                        drive_letter = " = D:"
                    else:
                        path_middle = steam_library.split('steamapps')[0]
                    path_end = re.sub(r'.*/steamapps', '/steamapps', os.path.dirname(skse_loc))
                    bin_path_end = re.sub(r'.*/steamapps', '/steamapps', skse_loc)
                else:
                    logger.warning(f"No matching pattern found in the path: {orig_line}")
                    continue
                full_bin_path = f"{bin_path_start}{drive_letter}{path_middle}{bin_path_end}"
                full_path = f"{path_start}{drive_letter}{path_middle}{path_end}"
                new_path = full_path.replace('/', '\\\\')
                for i, line in enumerate(content):
                    if line.startswith(bin_path_start):
                        content[i] = f"{full_bin_path}\n"
                    elif line.startswith(path_start):
                        content[i] = f"{new_path}\n"
            with open(modlist_ini, 'w', encoding='utf-8') as f:
                f.writelines(content)
            logger.debug("Updated binary and working directory paths successfully")
            return True
        except Exception as e:
            logger.error(f"Error editing binary working paths: {e}")
            return False

    @staticmethod
    def all_owned_by_user(path: str) -> bool:
        """Return True if all files and directories under path are owned by the current user."""
        uid = os.getuid()
        gid = os.getgid()
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full_path = os.path.join(root, name)
                try:
                    stat = os.stat(full_path)
                    if stat.st_uid != uid or stat.st_gid != gid:
                        return False
                except Exception:
                    return False
        return True

    @staticmethod
    def chown_chmod_modlist_dir(modlist_dir: str) -> bool:
        """
        DEPRECATED: Use FileSystemHandler.verify_ownership_and_permissions() instead.
        Verify and fix ownership/permissions for modlist directory.
        """
        if not WineUtils.all_owned_by_user(modlist_dir):
            logger.error(f"Ownership issue detected: Some files in {modlist_dir} are not owned by the current user")
            try:
                user = subprocess.run("whoami", shell=True, capture_output=True, text=True).stdout.strip()
                group = subprocess.run("id -gn", shell=True, capture_output=True, text=True).stdout.strip()
                logger.error("To fix ownership issues, open a terminal and run:")
                logger.error(f"  sudo chown -R {user}:{group} \"{modlist_dir}\"")
                logger.error(f"  sudo chmod -R 755 \"{modlist_dir}\"")
                logger.error("After running these commands, retry the operation.")
                return False
            except Exception as e:
                logger.error(f"Error checking ownership: {e}")
                return False
        logger.info(f"Files in {modlist_dir} are owned by current user, verifying permissions...")
        try:
            result = subprocess.run(
                ['chmod', '-R', '755', modlist_dir],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                logger.info(f"Permissions set successfully for {modlist_dir}")
            else:
                logger.warning(f"chmod returned non-zero but continuing: {result.stderr}")
            return True
        except Exception as e:
            logger.warning(f"Error running chmod: {e}, continuing anyway")
            return True

    @staticmethod
    def update_executables(modlist_ini: str, modlist_dir: str, modlist_sdcard: bool,
                           steam_library: str, basegame_sdcard: bool) -> bool:
        """Update executable paths in ModOrganizer.ini."""
        logger.info("Updating executable paths in ModOrganizer.ini...")
        try:
            with open(modlist_ini, 'r') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if "skse64_loader.exe" in line or "f4se_loader.exe" in line:
                    binary_path = line.strip().split('=', 1)[1] if '=' in line else ""
                    drive_letter = "D:" if modlist_sdcard else "Z:"
                    binary_num = line.strip().split('=', 1)[0] if '=' in line else ""
                    justnum = binary_num.split('\\')[0] if '\\' in binary_num else binary_num
                    bin_path_start = binary_num.replace('\\', '\\\\')
                    path_start = f"{justnum}\\workingDirectory".replace('\\', '\\\\')
                    if "mods" in binary_path:
                        path_middle = WineUtils._strip_sdcard_path(modlist_dir) if modlist_sdcard else modlist_dir
                        path_end = '/' + '/'.join(binary_path.split('/mods/', 1)[1].split('/')[:-1]) if '/mods/' in binary_path else ""
                        bin_path_end = '/' + '/'.join(binary_path.split('/mods/', 1)[1].split('/')) if '/mods/' in binary_path else ""
                    elif any(x in binary_path for x in ["Stock Game", "Game Root", "STOCK GAME", "Stock Game Folder", "Stock Folder", "Skyrim Stock", "root/Skyrim Special Edition"]):
                        path_middle = WineUtils._strip_sdcard_path(modlist_dir) if modlist_sdcard else modlist_dir
                        if "Stock Game" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/Stock Game/', 1)[1].split('/')[:-1]) if '/Stock Game/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Stock Game/', 1)[1].split('/')) if '/Stock Game/' in binary_path else ""
                        elif "Game Root" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/Game Root/', 1)[1].split('/')[:-1]) if '/Game Root/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Game Root/', 1)[1].split('/')) if '/Game Root/' in binary_path else ""
                        elif "STOCK GAME" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/STOCK GAME/', 1)[1].split('/')[:-1]) if '/STOCK GAME/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/STOCK GAME/', 1)[1].split('/')) if '/STOCK GAME/' in binary_path else ""
                        elif "Stock Folder" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/Stock Folder/', 1)[1].split('/')[:-1]) if '/Stock Folder/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Stock Folder/', 1)[1].split('/')) if '/Stock Folder/' in binary_path else ""
                        elif "Skyrim Stock" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/Skyrim Stock/', 1)[1].split('/')[:-1]) if '/Skyrim Stock/' in binary_path else ""
                            bin_path_end = '/' + '/'.join(binary_path.split('/Skyrim Stock/', 1)[1].split('/')) if '/Skyrim Stock/' in binary_path else ""
                        elif "Stock Game Folder" in binary_path:
                            path_end = '/' + '/'.join(binary_path.split('/Stock Game Folder/', 1)[1].split('/')) if '/Stock Game Folder/' in binary_path else ""
                            bin_path_end = path_end
                        elif "root/Skyrim Special Edition" in binary_path:
                            path_end = '/' + binary_path.split('root/Skyrim Special Edition', 1)[1] if 'root/Skyrim Special Edition' in binary_path else ""
                            bin_path_end = '/' + binary_path.split('root/Skyrim Special Edition', 1)[1] if 'root/Skyrim Special Edition' in binary_path else ""
                        else:
                            continue
                    elif "steamapps" in binary_path:
                        if basegame_sdcard:
                            path_middle = WineUtils._strip_sdcard_path(steam_library)
                            drive_letter = "D:"
                        else:
                            path_middle = steam_library.split('steamapps', 1)[0] if 'steamapps' in steam_library else steam_library
                        path_end = '/' + '/'.join(binary_path.split('/steamapps/', 1)[1].split('/')[:-1]) if '/steamapps/' in binary_path else ""
                        bin_path_end = '/' + '/'.join(binary_path.split('/steamapps/', 1)[1].split('/')) if '/steamapps/' in binary_path else ""
                    else:
                        logger.warning(f"No matching pattern found in the path: {binary_path}")
                        continue
                    full_bin_path = f"{bin_path_start}={drive_letter}{path_middle}{bin_path_end}"
                    full_path = f"{path_start}={drive_letter}{path_middle}{path_end}"
                    new_path = full_path.replace('/', '\\\\')
                    lines[i] = f"{full_bin_path}\n"
                    for j, working_line in enumerate(lines):
                        if working_line.startswith(path_start):
                            lines[j] = f"{new_path}\n"
                            break
            with open(modlist_ini, 'w') as f:
                f.writelines(lines)
            logger.info("Executable paths updated successfully")
            return True
        except Exception as e:
            logger.error(f"Error updating executable paths: {e}")
            return False
