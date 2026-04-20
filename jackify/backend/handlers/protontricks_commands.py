#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks run/launch commands mixin.
Extracted from protontricks_handler for file-size and domain separation.
"""

import os
import subprocess
from pathlib import Path
import shutil
from typing import Optional

import logging

logger = logging.getLogger(__name__)


class ProtontricksCommandsMixin:
    """Mixin providing run_protontricks and run_protontricks_launch."""

    def _add_jackify_proton_wrapper_env(self, env: dict) -> dict:
        """
        Override protontricks' cached proxy wrappers with Jackify's wrappers.
        This keeps Proton inside steam-run on NixOS while preserving stdout for
        winetricks' early cmd.exe/winepath probes.
        """
        try:
            from .config_handler import ConfigHandler
            from .wine_utils import WineUtils
            from .wine_wrapper import WineWrapperManager

            config = ConfigHandler()
            user_proton_path = config.get_proton_path()
            wine_binary = None

            if user_proton_path and user_proton_path != 'auto' and os.path.exists(user_proton_path):
                resolved_proton_path = os.path.realpath(user_proton_path)
                for candidate in (
                    os.path.join(resolved_proton_path, 'dist', 'bin', 'wine'),
                    os.path.join(resolved_proton_path, 'files', 'bin', 'wine'),
                ):
                    if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                        wine_binary = candidate
                        break

            if not wine_binary:
                best_proton = WineUtils.select_best_proton()
                if best_proton:
                    wine_binary = WineUtils.find_proton_binary(best_proton['name'])

            if not wine_binary or not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                return env

            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))
            wineserver_bin = os.path.join(proton_dist_path, 'bin', 'wineserver')
            wrapper_dir = WineWrapperManager().create_wrappers(proton_dist_path)
            if not wrapper_dir:
                return env

            wine_wrapper = wrapper_dir / "wine"
            wineserver_wrapper = wrapper_dir / "wineserver"
            env['WINE'] = str(wine_wrapper)
            env['WINELOADER'] = str(wine_wrapper)
            env['WINESERVER'] = str(wineserver_wrapper)
            env['WINE_BIN'] = str(wine_binary)
            env['WINE_BINDIR'] = f"{proton_dist_path}/bin"
            if os.path.exists(wineserver_bin) and os.access(wineserver_bin, os.X_OK):
                env['WINESERVER_BIN'] = wineserver_bin
            env['PATH'] = f"{wrapper_dir}{os.pathsep}{proton_dist_path}/bin{os.pathsep}{env.get('PATH', '')}"
            self.logger.debug(f"Using Jackify Proton wrappers for protontricks: {wrapper_dir}")
        except Exception as e:
            self.logger.warning(f"Could not prepare Jackify Proton wrappers for protontricks: {e}")

        return env

    def run_protontricks(self, *args, **kwargs):
        """
        Run protontricks with the given arguments and keyword arguments.
        kwargs are passed to subprocess.run (e.g., stderr=subprocess.DEVNULL).
        Returns subprocess.CompletedProcess or None.
        """
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                self.logger.error("Could not detect protontricks installation")
                return None

        if self.which_protontricks == 'bundled':
            from .subprocess_utils import get_safe_python_executable
            python_exe = get_safe_python_executable()
            wrapper_script = self._get_bundled_protontricks_wrapper_path()
            if wrapper_script and Path(wrapper_script).exists():
                cmd = [python_exe, str(wrapper_script)]
                cmd.extend([str(a) for a in args])
            else:
                cmd = [python_exe, "-m", "protontricks.cli.main"]
                cmd.extend([str(a) for a in args])
        elif self.which_protontricks == 'flatpak':
            cmd = list(self._get_flatpak_run_args())
            if kwargs.get('env') and kwargs['env'].get('WINETRICKS_CACHE'):
                try:
                    cache_val = str(Path(kwargs['env']['WINETRICKS_CACHE']).resolve())
                    cmd.append(f'--env=WINETRICKS_CACHE={cache_val}')
                except Exception:
                    pass
            if kwargs.get('env') and kwargs['env'].get('W_CACHE'):
                try:
                    cache_val = str(Path(kwargs['env']['W_CACHE']).resolve())
                    cmd.append(f'--env=W_CACHE={cache_val}')
                except Exception:
                    pass
            cmd.append("com.github.Matoking.protontricks")
            cmd.extend(args)
        else:
            cmd = ["protontricks"]
            cmd.extend(args)

        run_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'text': True,
            **kwargs
        }

        cmd_str = ' '.join(map(str, cmd))
        self.logger.debug("=" * 80)
        self.logger.debug("PROTONTRICKS COMMAND (for manual reproduction):")
        self.logger.debug(f"  {cmd_str}")
        self.logger.debug("=" * 80)

        if 'env' in kwargs and kwargs['env']:
            env = self._get_clean_subprocess_env()
            env.update(kwargs['env'])
        else:
            env = self._get_clean_subprocess_env()

        env['WINEDEBUG'] = '-all'
        steam_dir = self._get_steam_dir_from_libraryfolders()
        if steam_dir:
            env['STEAM_DIR'] = str(steam_dir)
            self.logger.debug(f"Set STEAM_DIR for protontricks: {steam_dir}")
        else:
            self.logger.warning("Could not determine STEAM_DIR from libraryfolders.vdf - protontricks may prompt user")

        if self.which_protontricks == 'native':
            winetricks_path = self._get_bundled_winetricks_path()
            if winetricks_path:
                env['WINETRICKS'] = str(winetricks_path)
                self.logger.debug(f"Set WINETRICKS for native protontricks: {winetricks_path}")
            else:
                self.logger.warning("Bundled winetricks not found - native protontricks will use system winetricks")
            cabextract_path = self._get_bundled_cabextract_path()
            if cabextract_path:
                cabextract_dir = str(cabextract_path.parent)
                current_path = env.get('PATH', '')
                env['PATH'] = f"{cabextract_dir}{os.pathsep}{current_path}" if current_path else cabextract_dir
                self.logger.debug(f"Added bundled cabextract to PATH for native protontricks: {cabextract_dir}")
            else:
                self.logger.warning("Bundled cabextract not found - native protontricks will use system cabextract")
            env = self._add_jackify_proton_wrapper_env(env)
        else:
            self.logger.debug(f"Using {self.which_protontricks} protontricks - it has its own winetricks (cannot access AppImage mounts)")

        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        debug_mode = config_handler.get('debug_mode', False)
        if not debug_mode:
            env['WINETRICKS_SUPER_QUIET'] = '1'
            self.logger.debug("Set WINETRICKS_SUPER_QUIET=1 to suppress winetricks verbose output")
        else:
            self.logger.debug("Debug mode enabled - winetricks verbose output will be shown")

        run_kwargs['env'] = env
        try:
            return subprocess.run(cmd, **run_kwargs)
        except Exception as e:
            self.logger.error(f"Error running protontricks: {e}")
            return None

    def run_protontricks_launch(self, appid, installer_path, *extra_args):
        """
        Run protontricks-launch (for WebView or similar installers).
        Returns subprocess.CompletedProcess or None.
        """
        if self.which_protontricks is None:
            if not self.detect_protontricks():
                self.logger.error("Could not detect protontricks installation")
                return None
        if self.which_protontricks == 'bundled':
            from .subprocess_utils import get_safe_python_executable
            python_exe = get_safe_python_executable()
            cmd = [python_exe, "-m", "protontricks.cli.launch", "--appid", appid, str(installer_path)]
        elif self.which_protontricks == 'flatpak':
            cmd = self._get_flatpak_run_args() + ["--command=protontricks-launch", "com.github.Matoking.protontricks", "--appid", appid, str(installer_path)]
        else:
            launch_path = shutil.which("protontricks-launch")
            if not launch_path:
                self.logger.error("protontricks-launch command not found in PATH.")
                return None
            cmd = [launch_path, "--appid", appid, str(installer_path)]
        if extra_args:
            cmd.extend(extra_args)
        self.logger.debug(f"Running protontricks-launch: {' '.join(map(str, cmd))}")
        try:
            env = self._get_clean_subprocess_env()
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        except Exception as e:
            self.logger.error(f"Error running protontricks-launch: {e}")
            return None
