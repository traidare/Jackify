#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks Steam/permissions/shortcuts/alias mixin.
Extracted from protontricks_handler for file-size and domain separation.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict

import logging

logger = logging.getLogger(__name__)


class ProtontricksSteamMixin:
    """Mixin for Steam permissions, aliases, and non-Steam shortcut listing."""

    def set_protontricks_permissions(self, modlist_dir, steamdeck=False):
        """
        Set permissions for Steam operations to access the modlist directory.
        Uses native operations when enabled, else protontricks flatpak overrides.
        Returns True on success, False on failure.
        """
        if self.use_native_operations:
            self.logger.debug("Using native Steam operations, permissions handled natively")
            try:
                return self._get_native_steam_service().set_steam_permissions(modlist_dir, steamdeck)
            except Exception as e:
                self.logger.warning(f"Native permissions failed, falling back to protontricks: {e}")

        if self.which_protontricks != 'flatpak':
            self.logger.debug("Using Native protontricks, skip setting permissions")
            return True

        self.logger.info("Setting Protontricks permissions...")
        env = self._get_clean_subprocess_env()
        permissions_set = []
        permissions_failed = []

        try:
            self.logger.debug(f"Setting permission for modlist directory: {modlist_dir}")
            try:
                subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks",
                               f"--filesystem={modlist_dir}"], check=True, env=env, capture_output=True)
                permissions_set.append(f"modlist directory: {modlist_dir}")
            except subprocess.CalledProcessError as e:
                permissions_failed.append(f"modlist directory: {modlist_dir} ({e})")
                self.logger.warning(f"Failed to set permission for modlist directory: {e}")

            steam_dir = self._get_steam_dir_from_libraryfolders()
            if steam_dir and steam_dir.exists():
                self.logger.info(f"Setting permission for Steam directory: {steam_dir}")
                self.logger.debug("Allows protontricks to access Steam compatdata, config, steamapps")
                try:
                    subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks",
                                   f"--filesystem={steam_dir}"], check=True, env=env, capture_output=True)
                    permissions_set.append(f"Steam directory: {steam_dir}")
                except subprocess.CalledProcessError as e:
                    permissions_failed.append(f"Steam directory: {steam_dir} ({e})")
                    self.logger.warning(f"Failed to set permission for Steam directory: {e}")
            else:
                self.logger.warning("Could not determine Steam directory - protontricks may not have access to Steam directories")

            from ..handlers.path_handler import PathHandler
            all_library_paths = PathHandler.get_all_steam_library_paths()
            for lib_path in all_library_paths:
                if steam_dir and lib_path.resolve() == steam_dir.resolve():
                    continue
                if lib_path.exists():
                    self.logger.debug(f"Setting permission for Steam library folder: {lib_path}")
                    try:
                        subprocess.run(["flatpak", "override", "--user", "com.github.Matoking.protontricks",
                                       f"--filesystem={lib_path}"], check=True, env=env, capture_output=True)
                        permissions_set.append(f"Steam library: {lib_path}")
                    except subprocess.CalledProcessError as e:
                        permissions_failed.append(f"Steam library: {lib_path} ({e})")
                        self.logger.warning(f"Failed to set permission for Steam library folder {lib_path}: {e}")

            if steamdeck:
                self.logger.warning("Checking for SDCard and setting permissions appropriately...")
                result = subprocess.run(["df", "-h"], capture_output=True, text=True, env=env)
                for line in result.stdout.splitlines():
                    if "/run/media" in line:
                        sdcard_path = line.split()[-1]
                        self.logger.debug(f"SDCard path: {sdcard_path}")
                        try:
                            subprocess.run(["flatpak", "override", "--user", f"--filesystem={sdcard_path}",
                                          "com.github.Matoking.protontricks"], check=True, env=env, capture_output=True)
                            permissions_set.append(f"SD card: {sdcard_path}")
                        except subprocess.CalledProcessError as e:
                            permissions_failed.append(f"SD card: {sdcard_path} ({e})")
                            self.logger.warning(f"Failed to set permission for SD card {sdcard_path}: {e}")
                try:
                    subprocess.run(["flatpak", "override", "--user", "--filesystem=/run/media/mmcblk0p1",
                                  "com.github.Matoking.protontricks"], check=True, env=env, capture_output=True)
                    permissions_set.append("SD card: /run/media/mmcblk0p1")
                except subprocess.CalledProcessError as e:
                    self.logger.debug(f"Could not set permission for fallback SD card path (may not exist): {e}")

            if permissions_set:
                self.logger.info(f"Successfully set {len(permissions_set)} permission(s) for protontricks")
                self.logger.debug(f"Permissions set: {', '.join(permissions_set)}")
            if permissions_failed:
                self.logger.warning(f"Failed to set {len(permissions_failed)} permission(s)")
                self.logger.debug(f"Failed permissions: {', '.join(permissions_failed)}")

            if any("modlist directory" in p for p in permissions_set):
                self.logger.info("Protontricks permissions configured (at least modlist directory access granted)")
                return True
            self.logger.error("Failed to set critical modlist directory permission")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error while setting Protontricks permissions: {e}")
            return False

    def create_protontricks_alias(self):
        """Create aliases for protontricks in ~/.bashrc if using flatpak. Returns True if created or already exists."""
        if self.which_protontricks != 'flatpak':
            self.logger.debug("Not using flatpak, skipping alias creation")
            return True
        try:
            bashrc_path = os.path.expanduser("~/.bashrc")
            if os.path.exists(bashrc_path):
                with open(bashrc_path, 'r') as f:
                    content = f.read()
                protontricks_alias_exists = "alias protontricks=" in content
                launch_alias_exists = "alias protontricks-launch" in content
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        self.logger.info("Adding protontricks alias to ~/.bashrc")
                        alias_cmd = self._get_flatpak_alias_string()
                        f.write(f"\nalias protontricks='{alias_cmd}'\n")
                    if not launch_alias_exists:
                        self.logger.info("Adding protontricks-launch alias to ~/.bashrc")
                        launch_alias_cmd = self._get_flatpak_alias_string(command='protontricks-launch')
                        f.write(f"\nalias protontricks-launch='{launch_alias_cmd}'\n")
                return True
            self.logger.error("~/.bashrc not found, skipping alias creation")
            return False
        except Exception as e:
            self.logger.error(f"Failed to create protontricks aliases: {e}")
            return False

    def list_non_steam_shortcuts(self) -> Dict[str, str]:
        """
        List ALL non-Steam shortcuts.
        Uses native VDF parsing when enabled, else protontricks -l.
        Returns dict mapping shortcut name to AppID.
        """
        if self.use_native_operations:
            self.logger.info("Listing non-Steam shortcuts via native VDF parsing...")
            try:
                return self._get_native_steam_service().list_non_steam_shortcuts()
            except Exception as e:
                self.logger.warning(f"Native shortcut listing failed, falling back to protontricks: {e}")

        self.logger.info("Listing ALL non-Steam shortcuts via protontricks...")
        non_steam_shortcuts = {}
        if not self.which_protontricks:
            self.logger.info("Protontricks type/path not yet determined. Running detection...")
            if not self.detect_protontricks():
                self.logger.error("Protontricks detection failed. Cannot list shortcuts.")
                return {}
            self.logger.info(f"Protontricks detection successful: {self.which_protontricks}")
        try:
            cmd = []
            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "-l"]
            elif self.protontricks_path:
                cmd = [self.protontricks_path, "-l"]
            else:
                self.logger.error("Protontricks path not determined, cannot list shortcuts.")
                return {}
            self.logger.debug(f"Running command: {' '.join(cmd)}")
            env = self._get_clean_subprocess_env()
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore', env=env)
            pattern = re.compile(r"Non-Steam shortcut:\s+(.+)\s+\((\d+)\)")
            for line in result.stdout.splitlines():
                line = line.strip()
                match = pattern.match(line)
                if match:
                    app_name = match.group(1).strip()
                    app_id = match.group(2).strip()
                    non_steam_shortcuts[app_name] = app_id
                    self.logger.debug(f"Found non-Steam shortcut: '{app_name}' with AppID {app_id}")
            if not non_steam_shortcuts:
                self.logger.warning("No non-Steam shortcuts found in protontricks output.")
        except FileNotFoundError:
            self.logger.error(f"Protontricks command not found. Path: {cmd[0] if cmd else 'N/A'}")
            return {}
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error running protontricks -l (Exit code: {e.returncode}): {e}")
            self.logger.error(f"Stderr (truncated): {e.stderr[:500] if e.stderr else ''}")
        except Exception as e:
            self.logger.error(f"Unexpected error listing non-Steam shortcuts: {e}", exc_info=True)
            return {}
        return non_steam_shortcuts

    def protontricks_alias(self):
        """Create protontricks alias in ~/.bashrc (flatpak only). Returns True on success."""
        self.logger.info("Creating protontricks alias in ~/.bashrc...")
        try:
            if self.which_protontricks == 'flatpak':
                bashrc_path = os.path.expanduser("~/.bashrc")
                protontricks_alias_exists = False
                launch_alias_exists = False
                if os.path.exists(bashrc_path):
                    with open(bashrc_path, 'r') as f:
                        content = f.read()
                        protontricks_alias_exists = "alias protontricks=" in content
                        launch_alias_exists = "alias protontricks-launch=" in content
                with open(bashrc_path, 'a') as f:
                    if not protontricks_alias_exists:
                        f.write("\n# Jackify: Protontricks alias\n")
                        alias_cmd = self._get_flatpak_alias_string()
                        f.write(f"alias protontricks='{alias_cmd}'\n")
                        self.logger.debug("Added protontricks alias to ~/.bashrc")
                    if not launch_alias_exists:
                        f.write("\n# Jackify: Protontricks-launch alias\n")
                        launch_alias_cmd = self._get_flatpak_alias_string(command='protontricks-launch')
                        f.write(f"alias protontricks-launch='{launch_alias_cmd}'\n")
                        self.logger.debug("Added protontricks-launch alias to ~/.bashrc")
                self.logger.info("Protontricks aliases created successfully")
                return True
            self.logger.info("Protontricks is not installed via flatpak, skipping alias creation")
            return True
        except Exception as e:
            self.logger.error(f"Error creating protontricks alias: {e}")
            return False

    def _ensure_flatpak_cache_access(self, cache_path: Path) -> bool:
        """Ensure flatpak protontricks has filesystem access to the winetricks cache dir.
        WINETRICKS_CACHE is passed at run time via flatpak run --env= (see run_protontricks)."""
        if self.which_protontricks != 'flatpak':
            return True
        try:
            cache_str = str(cache_path.resolve())
            result = subprocess.run(
                ['flatpak', 'override', '--user', '--show', 'com.github.Matoking.protontricks'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and f'filesystems=' in result.stdout and cache_str in result.stdout:
                self.logger.debug(f"Flatpak protontricks already has cache filesystem access: {cache_str}")
                return True
            self.logger.info(f"Granting flatpak protontricks filesystem access to winetricks cache: {cache_path}")
            result = subprocess.run(
                ['flatpak', 'override', '--user', 'com.github.Matoking.protontricks',
                 f'--filesystem={cache_str}'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self.logger.info("Successfully granted flatpak protontricks cache filesystem access")
                return True
            self.logger.warning(f"Failed to grant flatpak cache access: {result.stderr}")
            return False
        except Exception as e:
            self.logger.warning(f"Could not configure flatpak cache access: {e}")
            return False
