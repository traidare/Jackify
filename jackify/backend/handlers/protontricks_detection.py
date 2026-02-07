#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks detection and version mixin.
Extracted from protontricks_handler for file-size and domain separation.
"""

import os
import re
import subprocess
from pathlib import Path
import shutil
import logging
from typing import Optional, List
import sys

from .subprocess_utils import get_clean_subprocess_env


class ProtontricksDetectionMixin:
    """Mixin providing protontricks detection, Steam dir, bundled paths, and version checks."""

    def _get_steam_dir_from_libraryfolders(self) -> Optional[Path]:
        """Determine Steam installation directory from libraryfolders.vdf."""
        from ..handlers.path_handler import PathHandler
        vdf_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".steam/root/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam/config/libraryfolders.vdf",
        ]
        for vdf_path in vdf_paths:
            if vdf_path.is_file():
                steam_dir = vdf_path.parent.parent
                if (steam_dir / "steamapps").exists():
                    self.logger.debug(f"Determined STEAM_DIR from libraryfolders.vdf: {steam_dir}")
                    return steam_dir
        library_paths = PathHandler.get_all_steam_library_paths()
        if library_paths:
            first_lib = library_paths[0]
            if '.var/app/com.valvesoftware.Steam' in str(first_lib):
                data_steam = Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam"
                if (data_steam / "steamapps").exists():
                    self.logger.debug(f"Determined STEAM_DIR from Flatpak data path: {data_steam}")
                    return data_steam
                if (first_lib / "steamapps").exists():
                    self.logger.debug(f"Determined STEAM_DIR from Flatpak library path: {first_lib}")
                    return first_lib
            elif (first_lib / "steamapps").exists():
                self.logger.debug(f"Determined STEAM_DIR from native library path: {first_lib}")
                return first_lib
        self.logger.warning("Could not determine STEAM_DIR from libraryfolders.vdf")
        return None

    def _get_bundled_winetricks_path(self) -> Optional[Path]:
        """Get path to bundled winetricks (AppImage and dev)."""
        possible_paths = []
        if os.environ.get('APPDIR'):
            possible_paths.append(Path(os.environ['APPDIR']) / 'opt' / 'jackify' / 'tools' / 'winetricks')
        module_dir = Path(__file__).parent.parent.parent
        possible_paths.append(module_dir / 'tools' / 'winetricks')
        for path in possible_paths:
            if path.exists() and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled winetricks at: {path}")
                return path
        self.logger.warning(f"Bundled winetricks not found. Tried paths: {possible_paths}")
        return None

    def _get_bundled_cabextract_path(self) -> Optional[Path]:
        """Get path to bundled cabextract (AppImage and dev)."""
        possible_paths = []
        if os.environ.get('APPDIR'):
            possible_paths.append(Path(os.environ['APPDIR']) / 'opt' / 'jackify' / 'tools' / 'cabextract')
        module_dir = Path(__file__).parent.parent.parent
        possible_paths.append(module_dir / 'tools' / 'cabextract')
        for path in possible_paths:
            if path.exists() and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled cabextract at: {path}")
                return path
        self.logger.warning(f"Bundled cabextract not found. Tried paths: {possible_paths}")
        return None

    def _get_bundled_protontricks_wrapper_path(self) -> Optional[str]:
        """Return path to bundled protontricks wrapper script if any. Returns None to use python -m fallback."""
        return None

    def _get_clean_subprocess_env(self):
        """Create clean environment for subprocess (remove AppImage/bundle vars)."""
        env = get_clean_subprocess_env()
        if 'LD_LIBRARY_PATH_ORIG' in env:
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            env.pop('LD_LIBRARY_PATH', None)
        if 'DYLD_LIBRARY_PATH' in env and hasattr(sys, '_MEIPASS'):
            dyld_entries = env['DYLD_LIBRARY_PATH'].split(os.pathsep)
            cleaned_dyld = [p for p in dyld_entries if not p.startswith(sys._MEIPASS)]
            if cleaned_dyld:
                env['DYLD_LIBRARY_PATH'] = os.pathsep.join(cleaned_dyld)
            else:
                env.pop('DYLD_LIBRARY_PATH', None)
        return env

    def _get_native_steam_service(self):
        """Get native Steam operations service instance."""
        if self._native_steam_service is None:
            from ..services.native_steam_operations_service import NativeSteamOperationsService
            self._native_steam_service = NativeSteamOperationsService(steamdeck=self.steamdeck)
        return self._native_steam_service

    def detect_protontricks(self):
        """Detect if protontricks is installed (native or flatpak). Returns True if found."""
        self.logger.debug("Detecting if protontricks is installed...")
        protontricks_path_which = shutil.which("protontricks")
        self.flatpak_path = shutil.which("flatpak")
        if protontricks_path_which:
            try:
                with open(protontricks_path_which, 'r') as f:
                    content = f.read()
                    if "flatpak run" in content:
                        self.logger.debug(f"Detected Protontricks is a Flatpak wrapper at {protontricks_path_which}")
                        self.which_protontricks = 'flatpak'
                    else:
                        self.logger.info(f"Native Protontricks found at {protontricks_path_which}")
                        self.which_protontricks = 'native'
                        self.protontricks_path = protontricks_path_which
                        return True
            except Exception as e:
                self.logger.error(f"Error reading protontricks executable: {e}")
        try:
            env = self._get_clean_subprocess_env()
            result_user = subprocess.run(
                ["flatpak", "list", "--user"],
                capture_output=True, text=True, env=env
            )
            if result_user.returncode == 0 and "com.github.Matoking.protontricks" in result_user.stdout:
                self.logger.info("Flatpak Protontricks is installed (user-level)")
                self.which_protontricks = 'flatpak'
                self.flatpak_install_type = 'user'
                return True
            result_system = subprocess.run(
                ["flatpak", "list", "--system"],
                capture_output=True, text=True, env=env
            )
            if result_system.returncode == 0 and "com.github.Matoking.protontricks" in result_system.stdout:
                self.logger.info("Flatpak Protontricks is installed (system-level)")
                self.which_protontricks = 'flatpak'
                self.flatpak_install_type = 'system'
                return True
        except FileNotFoundError:
            self.logger.warning("'flatpak' command not found. Cannot check for Flatpak Protontricks.")
        except Exception as e:
            self.logger.error(f"Unexpected error checking flatpak: {e}")
        self.logger.warning("Protontricks not found (native or flatpak).")
        return False

    def _get_flatpak_run_args(self) -> List[str]:
        """Get flatpak run arguments (--user or --system)."""
        base_args = ["flatpak", "run"]
        if self.flatpak_install_type == 'user':
            base_args.append("--user")
        elif self.flatpak_install_type == 'system':
            base_args.append("--system")
        return base_args

    def _get_flatpak_alias_string(self, command=None) -> str:
        """Get flatpak alias string for bashrc."""
        flag = f"--{self.flatpak_install_type}" if self.flatpak_install_type else ""
        if command:
            return f"flatpak run {flag} --command={command} com.github.Matoking.protontricks" if flag else f"flatpak run --command={command} com.github.Matoking.protontricks"
        return f"flatpak run {flag} com.github.Matoking.protontricks" if flag else "flatpak run com.github.Matoking.protontricks"

    def check_protontricks_version(self):
        """Check if protontricks version is sufficient (>= 1.12). Returns True if OK."""
        try:
            if self.which_protontricks == 'flatpak':
                cmd = self._get_flatpak_run_args() + ["com.github.Matoking.protontricks", "-V"]
            else:
                cmd = ["protontricks", "-V"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            version_str = result.stdout.split(' ')[1].strip('()')
            cleaned_version = re.sub(r'[^0-9.]', '', version_str)
            self.protontricks_version = cleaned_version
            version_parts = cleaned_version.split('.')
            if len(version_parts) >= 2:
                major, minor = int(version_parts[0]), int(version_parts[1])
                if major < 1 or (major == 1 and minor < 12):
                    self.logger.error(f"Protontricks version {cleaned_version} is too old. Version 1.12.0 or newer is required.")
                    return False
                return True
            self.logger.error(f"Could not parse protontricks version: {cleaned_version}")
            return False
        except Exception as e:
            self.logger.error(f"Error checking protontricks version: {e}")
            return False
