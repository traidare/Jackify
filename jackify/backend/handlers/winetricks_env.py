"""
Winetricks environment and dependency setup for install_wine_components.
Builds env dict, checks downloaders/deps, resolves components list.
"""

import os
import sys
import subprocess
import logging
from typing import Optional, List, Callable, Tuple

logger = logging.getLogger(__name__)


def _get_clean_winetricks_base_env() -> dict:
    """
    Base environment for winetricks subprocess with no AppImage/bundle vars.
    Wine and wineserver must not see _MEIPASS, bundle PATH/LD_LIBRARY_PATH or
    connection reset / regsvr32 failures can occur when running from AppImage.
    """
    preserve = [
        "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LANGUAGE",
        "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY",
        "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS",
        "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "QT_QPA_PLATFORM", "GDK_BACKEND",
    ]
    env = {}
    for var in preserve:
        if var in os.environ:
            env[var] = os.environ[var]
    if "HOME" not in env and "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    path = os.environ.get("PATH", "")
    if getattr(sys, "_MEIPASS", None):
        path = os.pathsep.join(p for p in path.split(os.pathsep) if not p.startswith(sys._MEIPASS))
    env["PATH"] = path or "/usr/bin:/bin"
    return env


class WinetricksEnvMixin:
    """Mixin providing env build and dependency check for WinetricksHandler.install_wine_components."""

    def _build_winetricks_env(
        self,
        wineprefix: str,
        status_callback: Optional[Callable[[str], None]],
        specific_components: Optional[List[str]],
    ) -> Tuple[Optional[dict], Optional[List[str]]]:
        """
        Build environment and resolve components for winetricks. Returns (env, components_to_install) or (None, None).
        Uses a clean base env (no AppImage/bundle vars) so wine/wineserver see only Proton and system.
        """
        env = _get_clean_winetricks_base_env()
        env['WINEDEBUG'] = '-all'
        env['WINEPREFIX'] = wineprefix
        env['WINETRICKS_GUI'] = 'none'
        if 'DISPLAY' in env:
            env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
        else:
            env['DISPLAY'] = env.get('DISPLAY', '')

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
                        self.logger.info(f"Using user-selected Proton: {user_proton_path}")
                    elif os.path.exists(ge_proton_wine):
                        wine_binary = ge_proton_wine
                        self.logger.info(f"Using user-selected GE-Proton: {user_proton_path}")
                    else:
                        self.logger.warning(f"User-selected Proton path invalid: {user_proton_path}")
                else:
                    self.logger.warning(f"User-selected Proton no longer exists: {user_proton_path}")

            if not wine_binary:
                if not user_proton_path or user_proton_path == 'auto':
                    self.logger.info("Auto-detecting Proton (user selected 'auto')")
                    best_proton = WineUtils.select_best_proton()
                    if best_proton:
                        wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                        self.logger.info(f"Auto-selected Proton: {best_proton['name']} at {best_proton['path']}")
                    else:
                        self.logger.error("Auto-detection failed - no Proton versions found")
                        available_versions = WineUtils.scan_all_proton_versions()
                        if available_versions:
                            self.logger.error(f"Available Proton versions: {[v['name'] for v in available_versions]}")
                        else:
                            self.logger.error("No Proton versions detected in standard Steam locations")
                else:
                    self.logger.error(f"Cannot use configured Proton: {user_proton_path}")
                    self.logger.error("Please check Settings and ensure the Proton version still exists")
                    return (None, None)

            if not wine_binary:
                self.logger.error("Cannot run winetricks: No compatible Proton version found")
                self.logger.error("Please ensure you have Proton 9+ or GE-Proton installed through Steam")
                return (None, None)

            if not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                self.logger.error(f"Cannot run winetricks: Wine binary not found or not executable: {wine_binary}")
                return (None, None)

            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))
            self.logger.debug(f"Proton dist path: {proton_dist_path}")
            wineserver_bin = os.path.join(proton_dist_path, 'bin', 'wineserver')

            # Create wine wrapper scripts (like protontricks does) to ensure proper
            # LD_LIBRARY_PATH setup when winetricks spawns wine subprocesses
            from .wine_wrapper import WineWrapperManager
            wrapper_manager = WineWrapperManager()
            wrapper_dir = wrapper_manager.create_wrappers(proton_dist_path)

            if wrapper_dir:
                wine_wrapper = wrapper_dir / "wine"
                wineserver_wrapper = wrapper_dir / "wineserver"
                env['WINE'] = str(wine_wrapper)
                env['WINELOADER'] = str(wine_wrapper)
                env['WINESERVER'] = str(wineserver_wrapper)
                env['WINE_BIN'] = str(wine_binary)
                env['WINE_BINDIR'] = f"{proton_dist_path}/bin"
                if os.path.exists(wineserver_bin) and os.access(wineserver_bin, os.X_OK):
                    env['WINESERVER_BIN'] = wineserver_bin
                # Put wrapper dir first in PATH so winetricks finds our wrappers
                env['PATH'] = f"{wrapper_dir}:{proton_dist_path}/bin:{env.get('PATH', '')}"
                self.logger.info(f"Using wine wrappers for winetricks: {wrapper_dir}")
                self.logger.debug(f"WINE={wine_wrapper}, WINESERVER={wineserver_wrapper}")
            else:
                # Fallback to direct binary paths if wrapper creation fails
                self.logger.warning("Wine wrapper creation failed, using direct binary paths")
                env['WINE'] = str(wine_binary)
                env['WINELOADER'] = str(wine_binary)
                env['WINE_BIN'] = str(wine_binary)
                env['WINE_BINDIR'] = f"{proton_dist_path}/bin"
                if os.path.exists(wineserver_bin) and os.access(wineserver_bin, os.X_OK):
                    env['WINESERVER'] = wineserver_bin
                    env['WINESERVER_BIN'] = wineserver_bin
                env['PATH'] = f"{proton_dist_path}/bin:{env.get('PATH', '')}"

            env['WINEDLLPATH'] = f"{proton_dist_path}/lib64/wine:{proton_dist_path}/lib/wine"
            # LD_LIBRARY_PATH is now set by wrapper scripts, but set it here too for completeness
            ld_prepend = f"{proton_dist_path}/lib64:{proton_dist_path}/lib"
            env['LD_LIBRARY_PATH'] = f"{ld_prepend}:{env.get('LD_LIBRARY_PATH', '')}" if env.get('LD_LIBRARY_PATH') else ld_prepend
            self.logger.debug(f"Set LD_LIBRARY_PATH for Proton (prepend): {ld_prepend[:80]}...")

            dll_overrides = {
                "beclient": "b,n", "beclient_x64": "b,n", "dxgi": "n", "d3d9": "n",
                "d3d10core": "n", "d3d11": "n", "d3d12": "n", "d3d12core": "n",
                "nvapi": "n", "nvapi64": "n", "nvofapi64": "n", "nvcuda": "b"
            }
            existing_overrides = env.get('WINEDLLOVERRIDES', '')
            if existing_overrides:
                for override in existing_overrides.split(';'):
                    if '=' in override:
                        name, value = override.split('=', 1)
                        dll_overrides[name] = value
            env['WINEDLLOVERRIDES'] = ';'.join(f"{name}={setting}" for name, setting in dll_overrides.items())
            env['WINE_LARGE_ADDRESS_AWARE'] = '1'
            env['DXVK_ENABLE_NVAPI'] = '1'
            self.logger.debug(f"Set protontricks environment: WINEDLLPATH={env['WINEDLLPATH']}")

        except Exception as e:
            self.logger.error(f"Cannot run winetricks: Failed to get Proton wine binary: {e}")
            return (None, None)

        has_downloader = False
        for tool in ['aria2c', 'curl', 'wget']:
            try:
                result = subprocess.run(['which', tool], capture_output=True, timeout=2, env=os.environ.copy())
                if result.returncode == 0:
                    has_downloader = True
                    self.logger.info(f"System has {tool} available - winetricks will auto-select best option")
                    break
            except Exception:
                pass

        if not has_downloader:
            self._handle_missing_downloader_error()
            return (None, None)

        tools_dir = None
        bundled_tools = []
        for tool_name in ['cabextract', 'unzip', '7z', 'xz', 'sha256sum']:
            bundled_tool = self._get_bundled_tool(tool_name, fallback_to_system=False)
            if bundled_tool:
                bundled_tools.append(tool_name)
                if tools_dir is None:
                    tools_dir = os.path.dirname(bundled_tool)
        if tools_dir:
            env['PATH'] = f"{env.get('PATH', '')}:{tools_dir}"
            bundling_msg = f"Using bundled tools directory (after system PATH): {tools_dir}"
            self.logger.info(bundling_msg)
            if status_callback:
                status_callback(bundling_msg)
            tools_msg = f"Bundled tools available: {', '.join(bundled_tools)}"
            self.logger.info(tools_msg)
            if status_callback:
                status_callback(tools_msg)
        else:
            self.logger.debug("No bundled tools found, relying on system PATH")

        deps_check_msg = "=== Checking winetricks dependencies ==="
        self.logger.info(deps_check_msg)
        if status_callback:
            status_callback(deps_check_msg)
        missing_deps = []
        bundled_tools_list = ['aria2c', 'wget', 'unzip', '7z', 'xz', 'sha256sum', 'cabextract']
        dependency_checks = {
            'wget': 'wget', 'curl': 'curl', 'aria2c': 'aria2c', 'unzip': 'unzip',
            '7z': ['7z', '7za', '7zr'], 'xz': 'xz',
            'sha256sum': ['sha256sum', 'sha256', 'shasum'], 'perl': 'perl'
        }
        for dep_name, commands in dependency_checks.items():
            found = False
            if isinstance(commands, str):
                commands = [commands]
            if dep_name in bundled_tools_list:
                for cmd in commands:
                    bundled_tool = self._get_bundled_tool(cmd, fallback_to_system=False)
                    if bundled_tool:
                        dep_msg = f"  {dep_name}: {bundled_tool} (bundled)"
                        self.logger.info(dep_msg)
                        if status_callback:
                            status_callback(dep_msg)
                        found = True
                        break
            if not found:
                for cmd in commands:
                    try:
                        result = subprocess.run(['which', cmd], capture_output=True, timeout=2)
                        if result.returncode == 0:
                            cmd_path = result.stdout.decode().strip()
                            dep_msg = f"  {dep_name}: {cmd_path} (system)"
                            self.logger.info(dep_msg)
                            if status_callback:
                                status_callback(dep_msg)
                            found = True
                            break
                    except Exception:
                        pass
            if not found:
                missing_deps.append(dep_name)
                if dep_name in bundled_tools_list:
                    self.logger.warning(f"  {dep_name}: NOT FOUND (neither bundled nor system)")
                else:
                    self.logger.warning(f"  {dep_name}: NOT FOUND (system only - not bundled)")

        if missing_deps:
            download_deps = [d for d in missing_deps if d in ['wget', 'curl', 'aria2c']]
            verbose = getattr(self, 'verbose', False)
            if verbose:
                critical_deps = [d for d in missing_deps if d not in ['aria2c']]
                if critical_deps:
                    self.logger.warning(f"Missing critical winetricks dependencies: {', '.join(critical_deps)}")
                    self.logger.warning("Winetricks may fail if these are required for component installation")
                optional_deps = [d for d in missing_deps if d in ['aria2c']]
                if optional_deps:
                    self.logger.info(f"Optional dependencies not found (will use alternatives): {', '.join(optional_deps)}")
            all_downloaders = {'wget', 'curl', 'aria2c'}
            if set(download_deps) == all_downloaders:
                self.logger.error("=" * 80)
                self.logger.error("CRITICAL: No download tools found (wget, curl, or aria2c)")
                self.logger.error("Winetricks requires at least ONE download tool to install components")
                self.logger.error("")
                self.logger.error("SOLUTION: Install one of the following:")
                self.logger.error("  - aria2c (preferred): sudo apt install aria2  # or equivalent for your distro")
                self.logger.error("  - curl: sudo apt install curl  # or equivalent for your distro")
                self.logger.error("  - wget: sudo apt install wget  # or equivalent for your distro")
                self.logger.error("=" * 80)
            elif getattr(self, 'verbose', False):
                self.logger.warning("Critical dependencies: wget/curl (download), unzip/7z (extract)")
        elif getattr(self, 'verbose', False):
            self.logger.info("All winetricks dependencies found")
        if getattr(self, 'verbose', False):
            self.logger.info("========================================")

        from jackify.shared.paths import get_jackify_data_dir
        jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
        jackify_cache_dir.mkdir(parents=True, exist_ok=True)
        env['WINETRICKS_CACHE'] = str(jackify_cache_dir)
        # Current winetricks uses W_CACHE rather than WINETRICKS_CACHE.
        # Keep both for compatibility so downloads land in a path steam-run can access.
        env['W_CACHE'] = str(jackify_cache_dir)

        if specific_components is not None:
            all_components = specific_components
            self.logger.info(f"Installing specific components: {all_components}")
        else:
            all_components = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
            self.logger.info(f"Installing default components: {all_components}")

        if not all_components:
            self.logger.info("No Wine components to install.")
            if status_callback:
                status_callback("No Wine components to install")
            return (env, [])

        components_to_install = self._reorder_components_for_installation(all_components)
        self.logger.info(f"WINEPREFIX: {wineprefix}, Ordered Components: {components_to_install}")
        if status_callback:
            status_callback(f"Installing Wine components: {', '.join(components_to_install)}")
        return (env, components_to_install)
