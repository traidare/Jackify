#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks Handler Module
Handles wine component installation using bundled winetricks
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)


class WinetricksHandler:
    """
    Handles wine component installation using bundled winetricks
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.winetricks_path = self._get_bundled_winetricks_path()

    def _get_bundled_winetricks_path(self) -> Optional[str]:
        """
        Get the path to the bundled winetricks script following AppImage best practices
        """
        possible_paths = []

        # AppImage environment - use APPDIR (standard AppImage best practice)
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', 'winetricks')
            possible_paths.append(appdir_path)

        # Development environment - relative to module location
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / 'winetricks'
        possible_paths.append(str(dev_path))

        # Try each path until we find one that works
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled winetricks at: {path}")
                return str(path)

        self.logger.error(f"Bundled winetricks not found. Tried paths: {possible_paths}")
        return None

    def _get_bundled_tool(self, tool_name: str, fallback_to_system: bool = True) -> Optional[str]:
        """
        Get the path to a bundled tool binary, checking same locations as winetricks.
        
        Args:
            tool_name: Name of the tool (e.g., 'cabextract', 'wget', 'unzip')
            fallback_to_system: If True, fall back to system PATH if bundled version not found
            
        Returns:
            Path to the tool, or None if not found
        """
        possible_paths = []

        # AppImage environment - same pattern as winetricks detection
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', tool_name)
            possible_paths.append(appdir_path)

        # Development environment - relative to module location, same as winetricks
        module_dir = Path(__file__).parent.parent.parent  # Go from handlers/ up to jackify/
        dev_path = module_dir / 'tools' / tool_name
        possible_paths.append(str(dev_path))

        # Try each path until we find one that works
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled {tool_name} at: {path}")
                return str(path)

        # Fallback to system PATH if requested
        if fallback_to_system:
            try:
                import shutil
                system_tool = shutil.which(tool_name)
                if system_tool:
                    self.logger.debug(f"Using system {tool_name}: {system_tool}")
                    return system_tool
            except Exception:
                pass

        self.logger.debug(f"Bundled {tool_name} not found in tools directory")
        return None

    def _get_bundled_cabextract(self) -> Optional[str]:
        """
        Get the path to the bundled cabextract binary.
        Maintains backward compatibility with existing code.
        """
        return self._get_bundled_tool('cabextract', fallback_to_system=True)

    def is_available(self) -> bool:
        """
        Check if winetricks is available and ready to use
        """
        if not self.winetricks_path:
            self.logger.error("Bundled winetricks not found")
            return False

        try:
            env = os.environ.copy()
            result = subprocess.run(
                [self.winetricks_path, '--version'],
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )
            if result.returncode == 0:
                self.logger.debug(f"Winetricks version: {result.stdout.strip()}")
                return True
            else:
                self.logger.error(f"Winetricks --version failed: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Error testing winetricks: {e}")
            return False

    def install_wine_components(self, wineprefix: str, game_var: str, specific_components: Optional[List[str]] = None, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Install the specified Wine components into the given prefix using winetricks.
        If specific_components is None, use the default set (fontsmooth=rgb, xact, xact_x64, vcrun2022).
        
        Args:
            wineprefix: Path to Wine prefix
            game_var: Game name for logging
            specific_components: Optional list of specific components to install
            status_callback: Optional callback function(status_message: str) for progress updates
        """
        if not self.is_available():
            self.logger.error("Winetricks is not available")
            return False

        env = os.environ.copy()
        env['WINEDEBUG'] = '-all'  # Suppress Wine debug output
        env['WINEPREFIX'] = wineprefix
        env['WINETRICKS_GUI'] = 'none'  # Suppress GUI popups
        # Less aggressive popup suppression - don't completely disable display
        if 'DISPLAY' in env:
            # Keep DISPLAY but add window manager hints to prevent focus stealing
            env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'  # Disable Wine menu integration
        else:
            # No display available anyway
            env['DISPLAY'] = ''

        # Force winetricks to use Proton wine binary - NEVER fall back to system wine
        try:
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils

            config = ConfigHandler()
            # Use Install Proton for component installation/texture processing
            # get_proton_path() returns the Install Proton path
            user_proton_path = config.get_proton_path()

            # If user selected a specific Proton, try that first
            wine_binary = None
            if user_proton_path and user_proton_path != 'auto':
                # Check if user-selected Proton still exists
                if os.path.exists(user_proton_path):
                    # Resolve symlinks to handle ~/.steam/steam -> ~/.local/share/Steam
                    resolved_proton_path = os.path.realpath(user_proton_path)

                    # Check for wine binary in different Proton structures
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

            # Only auto-detect if user explicitly chose 'auto'
            if not wine_binary:
                if user_proton_path == 'auto':
                    self.logger.info("Auto-detecting Proton (user selected 'auto')")
                    best_proton = WineUtils.select_best_proton()
                    if best_proton:
                        wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                        self.logger.info(f"Auto-selected Proton: {best_proton['name']} at {best_proton['path']}")
                    else:
                        # Enhanced debugging for Proton detection failure
                        self.logger.error("Auto-detection failed - no Proton versions found")
                        available_versions = WineUtils.scan_all_proton_versions()
                        if available_versions:
                            self.logger.error(f"Available Proton versions: {[v['name'] for v in available_versions]}")
                        else:
                            self.logger.error("No Proton versions detected in standard Steam locations")
                else:
                    # User selected a specific Proton but validation failed - this is an ERROR
                    self.logger.error(f"Cannot use configured Proton: {user_proton_path}")
                    self.logger.error("Please check Settings and ensure the Proton version still exists")
                    return False

            if not wine_binary:
                self.logger.error("Cannot run winetricks: No compatible Proton version found")
                self.logger.error("Please ensure you have Proton 9+ or GE-Proton installed through Steam")
                return False

            if not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                self.logger.error(f"Cannot run winetricks: Wine binary not found or not executable: {wine_binary}")
                return False

            env['WINE'] = str(wine_binary)
            self.logger.info(f"Using Proton wine binary for winetricks: {wine_binary}")

            # CRITICAL: Set up protontricks-compatible environment
            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))  # e.g., /path/to/proton/dist/bin/wine -> /path/to/proton/dist
            self.logger.debug(f"Proton dist path: {proton_dist_path}")

            # Set WINEDLLPATH like protontricks does
            env['WINEDLLPATH'] = f"{proton_dist_path}/lib64/wine:{proton_dist_path}/lib/wine"

            # Ensure Proton bin directory is first in PATH
            env['PATH'] = f"{proton_dist_path}/bin:{env.get('PATH', '')}"

            # Set DLL overrides exactly like protontricks
            dll_overrides = {
                "beclient": "b,n",
                "beclient_x64": "b,n",
                "dxgi": "n",
                "d3d9": "n",
                "d3d10core": "n",
                "d3d11": "n",
                "d3d12": "n",
                "d3d12core": "n",
                "nvapi": "n",
                "nvapi64": "n",
                "nvofapi64": "n",
                "nvcuda": "b"
            }

            # Merge with existing overrides
            existing_overrides = env.get('WINEDLLOVERRIDES', '')
            if existing_overrides:
                # Parse existing overrides
                for override in existing_overrides.split(';'):
                    if '=' in override:
                        name, value = override.split('=', 1)
                        dll_overrides[name] = value

            env['WINEDLLOVERRIDES'] = ';'.join(f"{name}={setting}" for name, setting in dll_overrides.items())

            # Set Wine defaults from protontricks
            env['WINE_LARGE_ADDRESS_AWARE'] = '1'
            env['DXVK_ENABLE_NVAPI'] = '1'

            self.logger.debug(f"Set protontricks environment: WINEDLLPATH={env['WINEDLLPATH']}")

        except Exception as e:
            self.logger.error(f"Cannot run winetricks: Failed to get Proton wine binary: {e}")
            return False

        # Set up bundled tools directory for winetricks
        # Get tools directory from any bundled tool (winetricks, cabextract, etc.)
        tools_dir = None
        bundled_tools = []
        
        # Check for bundled tools and collect their directory
        tool_names = ['cabextract', 'wget', 'unzip', '7z', 'xz', 'sha256sum']
        for tool_name in tool_names:
            bundled_tool = self._get_bundled_tool(tool_name, fallback_to_system=False)
            if bundled_tool:
                bundled_tools.append(tool_name)
                if tools_dir is None:
                    tools_dir = os.path.dirname(bundled_tool)
        
        # Prepend tools directory to PATH if we have any bundled tools
        if tools_dir:
            env['PATH'] = f"{tools_dir}:{env.get('PATH', '')}"
            self.logger.info(f"Using bundled tools directory: {tools_dir}")
            self.logger.info(f"Bundled tools available: {', '.join(bundled_tools)}")
        else:
            self.logger.debug("No bundled tools found, relying on system PATH")

        # CRITICAL: Check for winetricks dependencies BEFORE attempting installation
        # This helps diagnose failures on systems where dependencies are missing
        self.logger.info("=== Checking winetricks dependencies ===")
        missing_deps = []
        dependency_checks = {
            'wget': 'wget',
            'curl': 'curl',
            'aria2c': 'aria2c',
            'unzip': 'unzip',
            '7z': ['7z', '7za', '7zr'],
            'xz': 'xz',
            'sha256sum': ['sha256sum', 'sha256', 'shasum'],
            'perl': 'perl'
        }
        
        for dep_name, commands in dependency_checks.items():
            found = False
            if isinstance(commands, str):
                commands = [commands]
            
            # First check for bundled version
            bundled_tool = None
            for cmd in commands:
                bundled_tool = self._get_bundled_tool(cmd, fallback_to_system=False)
                if bundled_tool:
                    self.logger.info(f"  ✓ {dep_name}: {bundled_tool} (bundled)")
                    found = True
                    break
            
            # If not bundled, check system PATH
            if not found:
                for cmd in commands:
                    try:
                        result = subprocess.run(['which', cmd], capture_output=True, timeout=2)
                        if result.returncode == 0:
                            cmd_path = result.stdout.decode().strip()
                            self.logger.info(f"  ✓ {dep_name}: {cmd_path} (system)")
                            found = True
                            break
                    except Exception:
                        pass
            
            if not found:
                missing_deps.append(dep_name)
                self.logger.warning(f"  ✗ {dep_name}: NOT FOUND (neither bundled nor system)")
        
        if missing_deps:
            self.logger.warning(f"Missing winetricks dependencies: {', '.join(missing_deps)}")
            self.logger.warning("Winetricks may fail if these are required for component installation")
            self.logger.warning("Critical dependencies: wget/curl/aria2c (download), unzip/7z (extract)")
        else:
            self.logger.info("All winetricks dependencies found")
        self.logger.info("========================================")

        # Set winetricks cache to jackify_data_dir for self-containment
        from jackify.shared.paths import get_jackify_data_dir
        jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
        jackify_cache_dir.mkdir(parents=True, exist_ok=True)
        env['WINETRICKS_CACHE'] = str(jackify_cache_dir)

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
            return True

        # Reorder components for proper installation sequence
        components_to_install = self._reorder_components_for_installation(all_components)
        self.logger.info(f"WINEPREFIX: {wineprefix}, Game: {game_var}, Ordered Components: {components_to_install}")
        
        # Show status with component list
        if status_callback:
            components_list = ', '.join(components_to_install)
            status_callback(f"Installing Wine components: {components_list}")

        # Check user preference for component installation method
        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        
        # Get component installation method with migration
        method = config_handler.get('component_installation_method', 'winetricks')

        # Migrate bundled_protontricks to system_protontricks (no longer supported)
        if method == 'bundled_protontricks':
            self.logger.warning("Bundled protontricks no longer supported, migrating to system_protontricks")
            method = 'system_protontricks'
            config_handler.set('component_installation_method', 'system_protontricks')

        # Choose installation method based on user preference
        if method == 'system_protontricks':
            self.logger.info("Using system protontricks for all components")
            return self._install_components_protontricks_only(components_to_install, wineprefix, game_var, status_callback)
        # else: method == 'winetricks' (default behavior continues below)

        # Install all components together with winetricks (faster)
        max_attempts = 3
        winetricks_failed = False
        last_error_details = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(f"Retrying component installation (attempt {attempt}/{max_attempts})...")
                self._cleanup_wine_processes()

            try:
                # Build winetricks command - using --unattended for silent installation
                cmd = [self.winetricks_path, '--unattended'] + components_to_install

                self.logger.debug(f"Running: {' '.join(cmd)}")

                # Enhanced diagnostics for bundled winetricks
                self.logger.debug("=== Winetricks Environment Diagnostics ===")
                self.logger.debug(f"Bundled winetricks path: {self.winetricks_path}")
                self.logger.debug(f"Winetricks exists: {os.path.exists(self.winetricks_path)}")
                self.logger.debug(f"Winetricks executable: {os.access(self.winetricks_path, os.X_OK)}")
                if os.path.exists(self.winetricks_path):
                    try:
                        winetricks_stat = os.stat(self.winetricks_path)
                        self.logger.debug(f"Winetricks permissions: {oct(winetricks_stat.st_mode)}")
                        self.logger.debug(f"Winetricks size: {winetricks_stat.st_size} bytes")
                    except Exception as stat_err:
                        self.logger.debug(f"Could not stat winetricks: {stat_err}")

                self.logger.debug(f"WINE binary: {env.get('WINE', 'NOT SET')}")
                wine_binary = env.get('WINE', '')
                if wine_binary and os.path.exists(wine_binary):
                    self.logger.debug(f"WINE binary exists: True")
                else:
                    self.logger.debug(f"WINE binary exists: False")

                self.logger.debug(f"WINEPREFIX: {env.get('WINEPREFIX', 'NOT SET')}")
                wineprefix = env.get('WINEPREFIX', '')
                if wineprefix and os.path.exists(wineprefix):
                    self.logger.debug(f"WINEPREFIX exists: True")
                    self.logger.debug(f"WINEPREFIX/pfx exists: {os.path.exists(os.path.join(wineprefix, 'pfx'))}")
                else:
                    self.logger.debug(f"WINEPREFIX exists: False")

                self.logger.debug(f"DISPLAY: {env.get('DISPLAY', 'NOT SET')}")
                self.logger.debug(f"WINETRICKS_CACHE: {env.get('WINETRICKS_CACHE', 'NOT SET')}")
                self.logger.debug(f"Components to install: {components_to_install}")
                self.logger.debug("==========================================")

                result = subprocess.run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=600
                )

                self.logger.debug(f"Winetricks output: {result.stdout}")
                if result.returncode == 0:
                    self.logger.info("Wine Component installation command completed.")

                    # Verify components were actually installed
                    if self._verify_components_installed(wineprefix, components_to_install, env):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        components_list = ', '.join(components_to_install)
                        if status_callback:
                            status_callback(f"Wine components installed and verified: {components_list}")
                        # Set Windows 10 mode after component installation (matches legacy script timing)
                        self._set_windows_10_mode(wineprefix, env.get('WINE', ''))
                        return True
                    else:
                        self.logger.error(f"Component verification failed (Attempt {attempt}/{max_attempts})")
                        # Continue to retry
                else:
                    # Store detailed error information for fallback diagnostics
                    last_error_details = {
                        'returncode': result.returncode,
                        'stdout': result.stdout.strip(),
                        'stderr': result.stderr.strip(),
                        'attempt': attempt
                    }

                    # CRITICAL: Always log full error details (not just in debug mode)
                    # This helps diagnose failures on systems we can't replicate
                    self.logger.error("=" * 80)
                    self.logger.error(f"WINETRICKS FAILED (Attempt {attempt}/{max_attempts})")
                    self.logger.error(f"Return Code: {result.returncode}")
                    self.logger.error("")
                    self.logger.error("STDOUT:")
                    if result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            self.logger.error(f"  {line}")
                    else:
                        self.logger.error("  (empty)")
                    self.logger.error("")
                    self.logger.error("STDERR:")
                    if result.stderr.strip():
                        for line in result.stderr.strip().split('\n'):
                            self.logger.error(f"  {line}")
                    else:
                        self.logger.error("  (empty)")
                    self.logger.error("=" * 80)

                    # Enhanced error diagnostics with actionable information
                    stderr_lower = result.stderr.lower()
                    stdout_lower = result.stdout.lower()
                    
                    # Log which diagnostic category matches
                    diagnostic_found = False

                    if "command not found" in stderr_lower or "no such file" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Winetricks or dependency binary not found")
                        self.logger.error("  - Bundled winetricks may be missing dependencies")
                        self.logger.error("  - Check dependency check output above for missing tools")
                        self.logger.error("  - Will attempt protontricks fallback if all attempts fail")
                        diagnostic_found = True
                    elif "permission denied" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Permission issue detected")
                        self.logger.error(f"  - Check permissions on: {self.winetricks_path}")
                        self.logger.error(f"  - Check permissions on WINEPREFIX: {env.get('WINEPREFIX', 'N/A')}")
                        diagnostic_found = True
                    elif "timeout" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Timeout issue detected during component download/install")
                        self.logger.error("  - Network may be slow or unstable")
                        self.logger.error("  - Component download may be taking too long")
                        diagnostic_found = True
                    elif "sha256sum mismatch" in stderr_lower or "sha256sum" in stdout_lower:
                        self.logger.error("DIAGNOSTIC: Checksum verification failed")
                        self.logger.error("  - Component download may be corrupted")
                        self.logger.error("  - Network issue or upstream file change")
                        diagnostic_found = True
                    elif "curl" in stderr_lower or "wget" in stderr_lower or "aria2c" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Download tool (curl/wget/aria2c) issue")
                        self.logger.error("  - Network connectivity problem or missing download tool")
                        self.logger.error("  - Check dependency check output above")
                        diagnostic_found = True
                    elif "cabextract" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: cabextract missing or failed")
                        self.logger.error("  - Required for extracting Windows cabinet files")
                        self.logger.error("  - Bundled cabextract should be available, check PATH")
                        diagnostic_found = True
                    elif "unzip" in stderr_lower or "7z" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Archive extraction tool (unzip/7z) missing or failed")
                        self.logger.error("  - Required for extracting zip/7z archives")
                        self.logger.error("  - Check dependency check output above")
                        diagnostic_found = True
                    elif "please install" in stderr_lower:
                        self.logger.error("DIAGNOSTIC: Winetricks explicitly requesting dependency installation")
                        self.logger.error("  - Winetricks detected missing required tool")
                        self.logger.error("  - Check dependency check output above")
                        diagnostic_found = True
                    
                    if not diagnostic_found:
                        self.logger.error("DIAGNOSTIC: Unknown winetricks failure pattern")
                        self.logger.error("  - Error details logged above (STDOUT/STDERR)")
                        self.logger.error("  - Check dependency check output above for missing tools")
                        self.logger.error("  - Will attempt protontricks fallback if all attempts fail")

                    winetricks_failed = True

            except subprocess.TimeoutExpired as e:
                self.logger.error(f"Winetricks timed out (Attempt {attempt}/{max_attempts}): {e}")
                last_error_details = {'error': 'timeout', 'attempt': attempt}
                winetricks_failed = True
            except Exception as e:
                self.logger.error(f"Error during winetricks run (Attempt {attempt}/{max_attempts}): {e}", exc_info=True)
                last_error_details = {'error': str(e), 'attempt': attempt}
                winetricks_failed = True

        # All winetricks attempts failed - try automatic fallback to protontricks
        if winetricks_failed:
            self.logger.error("=" * 80)
            self.logger.error(f"WINETRICKS FAILED AFTER {max_attempts} ATTEMPTS")
            self.logger.error("")
            if last_error_details:
                self.logger.error("Last error details:")
                if 'returncode' in last_error_details:
                    self.logger.error(f"  Return code: {last_error_details['returncode']}")
                if 'stderr' in last_error_details and last_error_details['stderr']:
                    self.logger.error(f"  Last stderr (first 500 chars): {last_error_details['stderr'][:500]}")
                if 'stdout' in last_error_details and last_error_details['stdout']:
                    self.logger.error(f"  Last stdout (first 500 chars): {last_error_details['stdout'][:500]}")
            self.logger.error("")
            self.logger.error("Attempting automatic fallback to protontricks...")
            self.logger.error("=" * 80)

            # Network diagnostics before fallback (non-fatal)
            self.logger.warning("=" * 80)
            self.logger.warning("NETWORK DIAGNOSTICS: Testing connectivity to component download sources...")
            try:
                # Check if curl is available
                curl_check = subprocess.run(['which', 'curl'], capture_output=True, timeout=5)
                if curl_check.returncode == 0:
                    # Test Microsoft download servers (used by winetricks for .NET, VC runtimes, DirectX)
                    test_result = subprocess.run(['curl', '-I', '--max-time', '10', 'https://download.microsoft.com'],
                                                capture_output=True, text=True, timeout=15)
                    if test_result.returncode == 0:
                        self.logger.warning("Can reach download.microsoft.com")
                    else:
                        self.logger.error("Cannot reach download.microsoft.com - network/DNS issue likely")
                        self.logger.error(f"  Curl exit code: {test_result.returncode}")
                        if test_result.stderr:
                            self.logger.error(f"  Curl error: {test_result.stderr.strip()}")
                else:
                    self.logger.warning("curl not available, skipping network diagnostic test")
            except Exception as e:
                self.logger.warning(f"Network diagnostic test skipped: {e}")
            self.logger.warning("=" * 80)

            # Check if protontricks is available for fallback using centralized handler
            try:
                from .protontricks_handler import ProtontricksHandler
                steamdeck = os.path.exists('/home/deck')
                protontricks_handler = ProtontricksHandler(steamdeck)
                protontricks_available = protontricks_handler.detect_protontricks()

                if protontricks_available:
                    self.logger.warning("=" * 80)
                    self.logger.warning("AUTOMATIC FALLBACK: Winetricks failed, attempting protontricks fallback...")
                    self.logger.warning(f"Last winetricks error: {last_error_details}")
                    self.logger.warning("=" * 80)

                    # Attempt fallback to protontricks
                    fallback_success = self._install_components_protontricks_only(components_to_install, wineprefix, game_var, status_callback)

                    if fallback_success:
                        self.logger.info("SUCCESS: Protontricks fallback succeeded where winetricks failed")
                        return True
                    else:
                        self.logger.error("FAILURE: Both winetricks and protontricks fallback failed")
                        return False
                else:
                    self.logger.error("Protontricks not available for fallback")
                    self.logger.error(f"Final winetricks error details: {last_error_details}")
                    return False
            except Exception as e:
                self.logger.error(f"Could not check for protontricks fallback: {e}")
                return False

        return False

    def _reorder_components_for_installation(self, components: list) -> list:
        """
        Reorder components for proper installation sequence if needed.
        Currently returns components in original order.
        """
        return components

    def _install_components_separately(self, components: list, wineprefix: str, wine_binary: str, base_env: dict) -> bool:
        """
        Install components separately for maximum compatibility.
        """
        self.logger.info(f"Installing {len(components)} components separately")

        for i, component in enumerate(components, 1):
            self.logger.info(f"Installing component {i}/{len(components)}: {component}")

            # Prepare environment for this component
            env = base_env.copy()
            env['WINEPREFIX'] = wineprefix
            env['WINE'] = wine_binary

            # Install this component
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
                    else:
                        self.logger.error(f"{component} failed (attempt {attempt}): {result.stderr.strip()}")
                        self.logger.debug(f"Full stdout for {component}: {result.stdout.strip()}")

                except Exception as e:
                    self.logger.error(f"Error installing {component} (attempt {attempt}): {e}")

            if not component_success:
                self.logger.error(f"Failed to install {component} after {max_attempts} attempts")
                return False

        self.logger.info("All components installed successfully using separate sessions")
        # Set Windows 10 mode after all component installation
        self._set_windows_10_mode(wineprefix, env.get('WINE', ''))
        return True

    def _prepare_winetricks_environment(self, wineprefix: str) -> Optional[dict]:
        """
        Prepare the environment for winetricks installation.
        This reuses the existing environment setup logic.

        Args:
            wineprefix: Wine prefix path

        Returns:
            dict: Environment variables for winetricks, or None if failed
        """
        try:
            env = os.environ.copy()
            env['WINEDEBUG'] = '-all'
            env['WINEPREFIX'] = wineprefix
            env['WINETRICKS_GUI'] = 'none'

            # Existing Proton detection logic
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
                    # User selected a specific Proton but validation failed
                    self.logger.error(f"Cannot prepare winetricks environment: configured Proton not found: {user_proton_path}")
                    return None

            if not wine_binary or not (os.path.exists(wine_binary) and os.access(wine_binary, os.X_OK)):
                self.logger.error(f"Cannot prepare winetricks environment: No compatible Proton found")
                return None

            env['WINE'] = str(wine_binary)

            # Set up protontricks-compatible environment (existing logic)
            proton_dist_path = os.path.dirname(os.path.dirname(wine_binary))
            env['WINEDLLPATH'] = f"{proton_dist_path}/lib64/wine:{proton_dist_path}/lib/wine"
            env['PATH'] = f"{proton_dist_path}/bin:{env.get('PATH', '')}"

            # Existing DLL overrides
            dll_overrides = {
                "beclient": "b,n", "beclient_x64": "b,n", "dxgi": "n", "d3d9": "n",
                "d3d10core": "n", "d3d11": "n", "d3d12": "n", "d3d12core": "n",
                "nvapi": "n", "nvapi64": "n", "nvofapi64": "n", "nvcuda": "b"
            }

            env['WINEDLLOVERRIDES'] = ';'.join(f"{name}={setting}" for name, setting in dll_overrides.items())
            env['WINE_LARGE_ADDRESS_AWARE'] = '1'
            env['DXVK_ENABLE_NVAPI'] = '1'

            # Set up winetricks cache
            from jackify.shared.paths import get_jackify_data_dir
            jackify_cache_dir = get_jackify_data_dir() / 'winetricks_cache'
            jackify_cache_dir.mkdir(parents=True, exist_ok=True)
            env['WINETRICKS_CACHE'] = str(jackify_cache_dir)

            return env

        except Exception as e:
            self.logger.error(f"Failed to prepare winetricks environment: {e}")
            return None

    def _install_components_with_winetricks(self, components: list, wineprefix: str, env: dict) -> bool:
        """
        Install components using winetricks with the prepared environment.

        Args:
            components: List of components to install
            wineprefix: Wine prefix path
            env: Prepared environment variables

        Returns:
            bool: True if installation succeeded, False otherwise
        """
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
                    self.logger.info(f"Winetricks components installation command completed.")

                    # Verify components were actually installed
                    if self._verify_components_installed(wineprefix, components, env):
                        self.logger.info("Component verification successful - all components installed correctly.")
                        # Set Windows 10 mode after component installation (matches legacy script timing)
                        wine_binary = env.get('WINE', '')
                        self._set_windows_10_mode(env.get('WINEPREFIX', ''), wine_binary)
                        return True
                    else:
                        self.logger.error(f"Component verification failed (attempt {attempt})")
                        # Continue to retry
                else:
                    self.logger.error(f"Winetricks failed (attempt {attempt}): {result.stderr.strip()}")

            except Exception as e:
                self.logger.error(f"Error during winetricks run (attempt {attempt}): {e}")

        self.logger.error(f"Failed to install components with winetricks after {max_attempts} attempts")
        return False

    def _set_windows_10_mode(self, wineprefix: str, wine_binary: str):
        """
        Set Windows 10 mode for the prefix after component installation (matches legacy script timing).
        This should be called AFTER all Wine components are installed, not before.
        """
        try:
            env = os.environ.copy()
            env['WINEPREFIX'] = wineprefix
            env['WINE'] = wine_binary

            self.logger.info("Setting Windows 10 mode after component installation (matching legacy script)")
            result = subprocess.run([
                self.winetricks_path, '-q', 'win10'
            ], env=env, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                self.logger.info("Windows 10 mode set successfully")
            else:
                self.logger.warning(f"Could not set Windows 10 mode: {result.stderr}")

        except Exception as e:
            self.logger.warning(f"Error setting Windows 10 mode: {e}")

    def _install_components_protontricks_only(self, components: list, wineprefix: str, game_var: str, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Install all components using protontricks only.
        This matches the behavior of the original bash script.

        Args:
            components: List of components to install
            wineprefix: Path to wine prefix
            game_var: Game variable name
        """
        try:
            self.logger.info(f"Installing all components with system protontricks: {components}")

            # Import protontricks handler
            from ..handlers.protontricks_handler import ProtontricksHandler

            # Determine if we're on Steam Deck (for protontricks handler)
            steamdeck = os.path.exists('/home/deck')
            protontricks_handler = ProtontricksHandler(steamdeck, logger=self.logger)

            # Get AppID from wineprefix
            appid = self._extract_appid_from_wineprefix(wineprefix)
            if not appid:
                self.logger.error("Could not extract AppID from wineprefix for protontricks installation")
                return False

            self.logger.info(f"Using AppID {appid} for protontricks installation")

            # Detect protontricks availability
            if not protontricks_handler.detect_protontricks():
                self.logger.error("Protontricks not available for component installation")
                return False

            # Install all components using protontricks
            components_list = ', '.join(components)
            if status_callback:
                status_callback(f"Installing Wine components via protontricks: {components_list}")
            success = protontricks_handler.install_wine_components(appid, game_var, components)

            if success:
                self.logger.info("All components installed successfully with protontricks")
                # Set Windows 10 mode after component installation
                wine_binary = self._get_wine_binary_for_prefix(wineprefix)
                self._set_windows_10_mode(wineprefix, wine_binary)
                return True
            else:
                self.logger.error("Component installation failed with protontricks")
                return False

        except Exception as e:
            self.logger.error(f"Error installing components with protontricks: {e}", exc_info=True)
            return False

    def _extract_appid_from_wineprefix(self, wineprefix: str) -> Optional[str]:
        """
        Extract AppID from wineprefix path.

        Args:
            wineprefix: Wine prefix path

        Returns:
            AppID as string, or None if extraction fails
        """
        try:
            if 'compatdata' in wineprefix:
                # Standard Steam compatdata structure
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
        """
        Get the wine binary path for a given prefix.

        Args:
            wineprefix: Wine prefix path

        Returns:
            Wine binary path as string
        """
        try:
            from ..handlers.config_handler import ConfigHandler
            from ..handlers.wine_utils import WineUtils

            config = ConfigHandler()
            user_proton_path = config.get_proton_path()

            # If user selected a specific Proton, try that first
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

            # Only auto-detect if user explicitly chose 'auto' or path is not set
            if not wine_binary:
                if not user_proton_path or user_proton_path == 'auto':
                    self.logger.info("Auto-detecting Proton (user selected 'auto' or path not set)")
                    best_proton = WineUtils.select_best_proton()
                    if best_proton:
                        wine_binary = WineUtils.find_proton_binary(best_proton['name'])
                else:
                    # User selected a specific Proton but validation failed
                    self.logger.error(f"Configured Proton not found: {user_proton_path}")
                    return ""

            return wine_binary if wine_binary else ""
        except Exception as e:
            self.logger.error(f"Error getting wine binary for prefix: {e}")
            return ""

    def _verify_components_installed(self, wineprefix: str, components: List[str], env: dict) -> bool:
        """
        Verify that Wine components were actually installed by checking winetricks.log.

        Args:
            wineprefix: Wine prefix path
            components: List of components that should be installed
            env: Environment variables (includes WINE path)

        Returns:
            bool: True if all critical components are verified, False otherwise
        """
        try:
            self.logger.info("Verifying installed components...")

            # Check winetricks.log file for installed components
            winetricks_log = os.path.join(wineprefix, 'winetricks.log')

            if not os.path.exists(winetricks_log):
                self.logger.error(f"winetricks.log not found at {winetricks_log}")
                return False

            try:
                with open(winetricks_log, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read().lower()
            except Exception as e:
                self.logger.error(f"Failed to read winetricks.log: {e}")
                return False

            self.logger.debug(f"winetricks.log length: {len(log_content)} bytes")

            # Define critical components that MUST be installed
            critical_components = ["vcrun2022", "xact"]

            # Check for critical components
            missing_critical = []
            for component in critical_components:
                if component.lower() not in log_content:
                    missing_critical.append(component)

            if missing_critical:
                self.logger.error(f"CRITICAL: Missing essential components: {missing_critical}")
                self.logger.error("Installation reported success but components are NOT in winetricks.log")
                return False

            # Check for requested components (warn but don't fail)
            missing_requested = []
            for component in components:
                # Handle settings like fontsmooth=rgb (just check the base component name)
                base_component = component.split('=')[0].lower()
                if base_component not in log_content and component.lower() not in log_content:
                    missing_requested.append(component)

            if missing_requested:
                self.logger.warning(f"Some requested components may not be installed: {missing_requested}")
                self.logger.warning("This may cause issues, but critical components are present")

            self.logger.info(f"Verification passed - critical components confirmed: {critical_components}")
            return True

        except Exception as e:
            self.logger.error(f"Error verifying components: {e}", exc_info=True)
            return False

    def _cleanup_wine_processes(self):
        """
        Internal method to clean up wine processes during component installation
        Only cleanup winetricks processes - NEVER kill all wine processes
        """
        try:
            # Only cleanup winetricks processes - do NOT kill other wine apps
            subprocess.run("pkill -f winetricks", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.logger.debug("Cleaned up winetricks processes only")
        except Exception as e:
            self.logger.error(f"Error cleaning up winetricks processes: {e}")