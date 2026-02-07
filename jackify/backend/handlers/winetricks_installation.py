#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks installation mixin: environment, run winetricks, protontricks fallback.
Extracted from winetricks_handler for file-size and domain separation.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)


class WinetricksInstallationMixin:
    """Mixin providing winetricks environment setup and component installation strategies."""

    def _reorder_components_for_installation(self, components: list) -> list:
        """Reorder components for proper installation sequence. Currently returns original order."""
        return components

    def _prepare_winetricks_environment(self, wineprefix: str) -> Optional[dict]:
        """Prepare environment for winetricks (Proton detection, DLL overrides, cache). Returns env dict or None."""
        try:
            env = os.environ.copy()
            env['WINEDEBUG'] = '-all'
            env['WINEPREFIX'] = wineprefix
            env['WINETRICKS_GUI'] = 'none'
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils
            config = ConfigHandler()
            user_proton_path = config.get_proton_path()
            wine_binary = None
            if user_proton_path and user_proton_path != 'auto':
                if os.path.exists(user_proton_path):
                    resolved_proton_path = os.path.realpath(user_proton_path)
                    valve_proton_wine = os.path.join(resolved_proton_path, 'dist', 'bin', 'wine')
                    ge_proton_wine = os.path.join(resolved_proton_path, 'files', 'bin', 'wine')
                    if os.path.exists(valve_proton_wine):
                        wine_binary = valve_proton_wine
                    elif os.path.exists(ge_proton_wine):
                        wine_binary = ge_proton_wine
            if not wine_binary:
                if not user_proton_path or user_proton_path == 'auto':
                    self.logger.info("Auto-detecting Proton (user selected 'auto' or path not set)")
                    best_proton = WineUtils.select_best_proton()
                    if best_proton:
                        wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                else:
                    self.logger.error(f"Cannot prepare winetricks environment: configured Proton not found: {user_proton_path}")
                    return None
            if not wine_binary or not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                self.logger.error("Cannot prepare winetricks environment: No compatible Proton found")
                return None
            env['WINE'] = str(wine_binary)
            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))
            env['WINEDLLPATH'] = f"{proton_dist_path}/lib64/wine:{proton_dist_path}/lib/wine"
            env['PATH'] = f"{proton_dist_path}/bin:{env.get('PATH', '')}"
            dll_overrides = {
                "beclient": "b,n", "beclient_x64": "b,n", "dxgi": "n", "d3d9": "n",
                "d3d10core": "n", "d3d11": "n", "d3d12": "n", "d3d12core": "n",
                "nvapi": "n", "nvapi64": "n", "nvofapi64": "n", "nvcuda": "b"
            }
            env['WINEDLLOVERRIDES'] = ';'.join(f"{name}={setting}" for name, setting in dll_overrides.items())
            env['WINE_LARGE_ADDRESS_AWARE'] = '1'
            env['DXVK_ENABLE_NVAPI'] = '1'
            from jackify.shared.paths import get_jackify_data_dir
            jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
            jackify_cache_dir.mkdir(parents=True, exist_ok=True)
            env['WINETRICKS_CACHE'] = str(jackify_cache_dir)
            return env
        except Exception as e:
            self.logger.error(f"Failed to prepare winetricks environment: {e}")
            return None

    def _install_components_with_winetricks(self, components: list, wineprefix: str, env: dict) -> bool:
        """Install components using winetricks with the prepared environment."""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying winetricks installation (attempt {attempt}/{max_attempts})")
                self._cleanup_wine_processes()
            try:
                cmd = [self.winetricks_path, '--unattended'] + components
                self.logger.debug(f"Running winetricks: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=600
                )
                if result.returncode == 0:
                    self.logger.info("Winetricks components installation command completed.")
                    if self._verify_components_installed(wineprefix, components, env):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        wine_binary = env.get('WINE', '')
                        self._set_windows_10_mode(env.get('WINEPREFIX', ''), wine_binary)
                        return True
                    self.logger.error(f"Component verification failed (attempt {attempt})")
                else:
                    self.logger.error(f"Winetricks failed (attempt {attempt}): {result.stderr.strip()}")
            except Exception as e:
                self.logger.error(f"Error during winetricks run (attempt {attempt}): {e}")
        self.logger.error(f"Failed to install components with winetricks after {max_attempts} attempts")
        return False

    def _set_windows_10_mode(self, wineprefix: str, wine_binary: str) -> None:
        """Set Windows 10 mode for the prefix after component installation."""
        try:
            env = os.environ.copy()
            env['WINEPREFIX'] = wineprefix
            env['WINE'] = wine_binary
            self.logger.info("Setting Windows 10 mode after component installation (matching legacy script)")
            result = subprocess.run(
                [self.winetricks_path, '-q', 'win10'],
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                self.logger.info("Windows 10 mode set successfully")
            else:
                self.logger.warning(f"Could not set Windows 10 mode: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Error setting Windows 10 mode: {e}")

    def _set_windows_10_mode_after_install(self, wineprefix: str, install_env: dict) -> None:
        """Set Windows 10 mode for the prefix after component installation."""
        try:
            self._set_windows_10_mode(wineprefix, install_env.get('WINE', ''))
        except Exception as e:
            self.logger.warning(f"Error setting Windows 10 mode: {e}")

    def _install_components_separately(self, components: list, wineprefix: str, wine_binary: str, base_env: dict) -> bool:
        """Install components one at a time for maximum compatibility."""
        self.logger.info(f"Installing {len(components)} components separately")
        for i, component in enumerate(components, 1):
            self.logger.info(f"Installing component {i}/{len(components)}: {component}")
            env = base_env.copy()
            env['WINEPREFIX'] = wineprefix
            env['WINE'] = wine_binary
            max_attempts = 3
            component_success = False
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    self.logger.warning(f"Retrying {component} installation (attempt {attempt}/{max_attempts})")
                    self._cleanup_wine_processes()
                try:
                    cmd = [self.winetricks_path, '--unattended', component]
                    self.logger.debug(f"Running: {' '.join(cmd)}")
                    result = subprocess.run(
                        cmd,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )
                    if result.returncode == 0:
                        self.logger.info(f"{component} installed successfully")
                        component_success = True
                        break
                    self.logger.error(f"{component} failed (attempt {attempt}): {result.stderr.strip()}")
                    self.logger.debug(f"Full stdout for {component}: {result.stdout.strip()}")
                except Exception as e:
                    self.logger.error(f"Error installing {component} (attempt {attempt}): {e}")
            if not component_success:
                self.logger.error(f"Failed to install {component} after {max_attempts} attempts")
                return False
        self.logger.info("All components installed successfully using separate sessions")
        self._set_windows_10_mode(wineprefix, env.get('WINE', ''))
        return True

    def _is_flatpak_steam_prefix(self, wineprefix: str) -> bool:
        """True if wineprefix is under Flatpak Steam (.var/app/com.valvesoftware.Steam)."""
        if not wineprefix:
            return False
        path_str = os.fspath(wineprefix)
        return ".var" in path_str and "app" in path_str and "com.valvesoftware.Steam" in path_str

    def _extract_appid_from_wineprefix(self, wineprefix: str) -> Optional[str]:
        """Extract AppID from wineprefix path (compatdata/AppID)."""
        try:
            if 'compatdata' in wineprefix:
                path_parts = Path(wineprefix).parts
                for i, part in enumerate(path_parts):
                    if part == 'compatdata' and i + 1 < len(path_parts):
                        potential_appid = path_parts[i + 1]
                        if potential_appid.isdigit():
                            return potential_appid
            self.logger.error(f"Could not extract AppID from wineprefix path: {wineprefix}")
            return None
        except Exception as e:
            self.logger.error(f"Error extracting AppID from wineprefix: {e}")
            return None

    def _get_wine_binary_for_prefix(self, wineprefix: str) -> str:
        """Get the wine binary path for a given prefix (user Proton or auto-detect)."""
        try:
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils
            config = ConfigHandler()
            user_proton_path = config.get_proton_path()
            wine_binary = None
            if user_proton_path and user_proton_path != 'auto':
                if os.path.exists(user_proton_path):
                    resolved_proton_path = os.path.realpath(user_proton_path)
                    valve_proton_wine = os.path.join(resolved_proton_path, 'dist', 'bin', 'wine')
                    ge_proton_wine = os.path.join(resolved_proton_path, 'files', 'bin', 'wine')
                    if os.path.exists(valve_proton_wine):
                        wine_binary = valve_proton_wine
                    elif os.path.exists(ge_proton_wine):
                        wine_binary = ge_proton_wine
            if not wine_binary:
                if not user_proton_path or user_proton_path == 'auto':
                    self.logger.info("Auto-detecting Proton (user selected 'auto' or path not set)")
                    best_proton = WineUtils.select_best_proton()
                    if best_proton:
                        wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                else:
                    self.logger.error(f"Configured Proton not found: {user_proton_path}")
                    return ""
            return wine_binary if wine_binary else ""
        except Exception as e:
            self.logger.error(f"Error getting wine binary for prefix: {e}")
            return ""

    def _install_components_protontricks_only(self, components: list, wineprefix: str, game_var: str,
                                             status_callback: Optional[Callable[[str], None]] = None,
                                             appid: Optional[str] = None) -> bool:
        """Install all components using system protontricks only. appid can be passed in or extracted from wineprefix."""
        try:
            self.logger.info(f"Installing all components with system protontricks: {components}")
            from ..handlers.protontricks_handler import ProtontricksHandler
            steamdeck = os.path.exists('/home/deck')
            protontricks_handler = ProtontricksHandler(steamdeck, logger=self.logger)
            resolved_appid = appid or self._extract_appid_from_wineprefix(wineprefix)
            if not resolved_appid:
                self.logger.error("Could not extract AppID from wineprefix for protontricks installation")
                return False
            self.logger.info(f"Using AppID {resolved_appid} for protontricks installation")
            if not protontricks_handler.detect_protontricks():
                self.logger.error("Protontricks not available for component installation")
                return False
            components_list = ', '.join(components)
            if status_callback:
                status_callback(f"Installing Wine components via protontricks: {components_list}")
            success = protontricks_handler.install_wine_components(resolved_appid, game_var, components)
            if success:
                self.logger.info("All components installed successfully with protontricks")
                wine_binary = self._get_wine_binary_for_prefix(wineprefix)
                self._set_windows_10_mode(wineprefix, wine_binary)
                return True
            self.logger.error("Component installation failed with protontricks")
            return False
        except Exception as e:
            self.logger.error(f"Error installing components with protontricks: {e}", exc_info=True)
            return False
