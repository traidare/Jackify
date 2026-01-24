"""
TTW_Linux_Installer Handler

Handles downloading, installation, and execution of TTW_Linux_Installer for TTW installations.
Replaces hoolamike for TTW-specific functionality.
"""

import logging
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple
import requests

from .path_handler import PathHandler
from .filesystem_handler import FileSystemHandler
from .config_handler import ConfigHandler
from .logging_handler import LoggingHandler
from .subprocess_utils import get_clean_subprocess_env

logger = logging.getLogger(__name__)

# Define default TTW_Linux_Installer paths
from jackify.shared.paths import get_jackify_data_dir
JACKIFY_BASE_DIR = get_jackify_data_dir()
DEFAULT_TTW_INSTALLER_DIR = JACKIFY_BASE_DIR / "TTW_Linux_Installer"
TTW_INSTALLER_EXECUTABLE_NAME = "ttw_linux_gui"  # Same executable, runs in CLI mode with args

# GitHub release info
TTW_INSTALLER_REPO = "SulfurNitride/TTW_Linux_Installer"
TTW_INSTALLER_RELEASE_URL = f"https://api.github.com/repos/{TTW_INSTALLER_REPO}/releases/latest"
# Pin to 0.0.7 - last version with old format (ttw_linux_gui, universal-mpi-installer)
# Set to None to use latest release
TTW_INSTALLER_PINNED_VERSION = "0.0.7"


class TTWInstallerHandler:
    """Handles TTW installation using TTW_Linux_Installer (replaces hoolamike for TTW)."""

    def __init__(self, steamdeck: bool, verbose: bool, filesystem_handler: FileSystemHandler, 
                 config_handler: ConfigHandler, menu_handler=None):
        """Initialize the handler."""
        self.steamdeck = steamdeck
        self.verbose = verbose
        self.path_handler = PathHandler()
        self.filesystem_handler = filesystem_handler
        self.config_handler = config_handler
        self.menu_handler = menu_handler
        
        # Set up logging
        logging_handler = LoggingHandler()
        logging_handler.rotate_log_for_logger('ttw-install', 'TTW_Install_workflow.log')
        self.logger = logging_handler.setup_logger('ttw-install', 'TTW_Install_workflow.log')
        
        # Installation paths
        self.ttw_installer_dir: Path = DEFAULT_TTW_INSTALLER_DIR
        self.ttw_installer_executable_path: Optional[Path] = None
        self.ttw_installer_installed: bool = False
        
        # Load saved install path from config
        saved_path_str = self.config_handler.get('ttw_installer_install_path')
        if saved_path_str and Path(saved_path_str).is_dir():
            self.ttw_installer_dir = Path(saved_path_str)
            self.logger.info(f"Loaded TTW_Linux_Installer path from config: {self.ttw_installer_dir}")
        
        # Check if already installed
        self._check_installation()

    def _ensure_dirs_exist(self):
        """Ensure base directories exist."""
        self.ttw_installer_dir.mkdir(parents=True, exist_ok=True)

    def _check_installation(self):
        """Check if TTW_Linux_Installer is installed at expected location.
        
        Checks for both old format (ttw_linux_gui) and new format (mpi_installer) executables.
        """
        self._ensure_dirs_exist()
        
        # Check for both old (ttw_linux_gui) and new (mpi_installer) executable names
        exe_names = [TTW_INSTALLER_EXECUTABLE_NAME, "mpi_installer"]
        for exe_name in exe_names:
            potential_exe_path = self.ttw_installer_dir / exe_name
            if potential_exe_path.is_file() and os.access(potential_exe_path, os.X_OK):
                self.ttw_installer_executable_path = potential_exe_path
                self.ttw_installer_installed = True
                self.logger.info(f"Found TTW_Linux_Installer at: {self.ttw_installer_executable_path}")
                return
        
        # Not found
        self.ttw_installer_installed = False
        self.ttw_installer_executable_path = None
        self.logger.info(f"TTW_Linux_Installer not found (searched for: {', '.join(exe_names)})")

    def install_ttw_installer(self, install_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """Download and install TTW_Linux_Installer from GitHub releases.
        
        Args:
            install_dir: Optional directory to install to (defaults to ~/Jackify/TTW_Linux_Installer)
            
        Returns:
            (success: bool, message: str)
        """
        try:
            self._ensure_dirs_exist()
            target_dir = Path(install_dir) if install_dir else self.ttw_installer_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            # Fetch release info (pinned version or latest)
            if TTW_INSTALLER_PINNED_VERSION:
                release_url = f"https://api.github.com/repos/{TTW_INSTALLER_REPO}/releases/tags/{TTW_INSTALLER_PINNED_VERSION}"
                self.logger.info(f"Fetching pinned TTW_Linux_Installer version {TTW_INSTALLER_PINNED_VERSION} from {release_url}")
            else:
                release_url = TTW_INSTALLER_RELEASE_URL
                self.logger.info(f"Fetching latest TTW_Linux_Installer release from {release_url}")
            
            resp = requests.get(release_url, timeout=15, verify=True)
            resp.raise_for_status()
            data = resp.json()
            release_tag = data.get("tag_name") or data.get("name")

            # Find Linux asset - universal-mpi-installer pattern (can be .zip or .tar.gz)
            linux_asset = None
            asset_names = [asset.get("name", "") for asset in data.get("assets", [])]
            self.logger.info(f"Available release assets: {asset_names}")
            
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                # Look for universal-mpi-installer pattern
                if "universal-mpi-installer" in name and name.endswith((".zip", ".tar.gz")):
                    linux_asset = asset
                    self.logger.info(f"Found Linux asset: {asset.get('name')}")
                    break

            if not linux_asset:
                # Log all available assets for debugging
                all_assets = [asset.get("name", "") for asset in data.get("assets", [])]
                self.logger.error(f"No suitable Linux asset found. Available assets: {all_assets}")
                return False, f"No suitable Linux TTW_Linux_Installer asset found in latest release. Available assets: {', '.join(all_assets)}"

            download_url = linux_asset.get("browser_download_url")
            asset_name = linux_asset.get("name")
            if not download_url or not asset_name:
                return False, "Latest release is missing required asset metadata"

            # Download to target directory
            temp_path = target_dir / asset_name
            self.logger.info(f"Downloading {asset_name} from {download_url}")
            if not self.filesystem_handler.download_file(download_url, temp_path, overwrite=True, quiet=True):
                return False, "Failed to download TTW_Linux_Installer asset"

            # Extract archive (zip or tar.gz)
            try:
                self.logger.info(f"Extracting {asset_name} to {target_dir}")
                if asset_name.lower().endswith('.tar.gz'):
                    with tarfile.open(temp_path, "r:gz") as tf:
                        tf.extractall(path=target_dir)
                elif asset_name.lower().endswith('.zip'):
                    with zipfile.ZipFile(temp_path, "r") as zf:
                        zf.extractall(path=target_dir)
                else:
                    return False, f"Unsupported archive format: {asset_name}"
            finally:
                try:
                    temp_path.unlink(missing_ok=True)  # cleanup
                except Exception:
                    pass

            # Find executable - support both old (ttw_linux_gui) and new (mpi_installer) names
            # Try old name first (since we're pinning to 0.0.7)
            exe_names = [TTW_INSTALLER_EXECUTABLE_NAME, "mpi_installer"]
            exe_path = None
            
            for exe_name in exe_names:
                potential_path = target_dir / exe_name
                if potential_path.is_file():
                    exe_path = potential_path
                    self.logger.info(f"Found executable: {exe_name}")
                    break
                # Search recursively
                for p in target_dir.rglob(exe_name):
                    if p.is_file():
                        exe_path = p
                        self.logger.info(f"Found executable: {exe_name} at {p}")
                        break
                if exe_path:
                    break

            if not exe_path or not exe_path.is_file():
                return False, f"TTW_Linux_Installer executable not found after extraction (searched for: {', '.join(exe_names)})"
            
            # Remove any other executable versions to avoid confusion
            for exe_name in exe_names:
                if exe_name != exe_path.name:
                    other_exe = target_dir / exe_name
                    if other_exe.is_file():
                        self.logger.info(f"Removing other version executable: {other_exe}")
                        try:
                            other_exe.unlink()
                        except Exception as e:
                            self.logger.warning(f"Failed to remove {other_exe}: {e}")

            # Set executable permissions
            try:
                os.chmod(exe_path, 0o755)
            except Exception as e:
                self.logger.warning(f"Failed to chmod +x on {exe_path}: {e}")

            # Update state
            self.ttw_installer_dir = target_dir
            self.ttw_installer_executable_path = exe_path
            self.ttw_installer_installed = True
            self.config_handler.set('ttw_installer_install_path', str(target_dir))
            if release_tag:
                self.config_handler.set('ttw_installer_version', release_tag)

            self.logger.info(f"TTW_Linux_Installer installed successfully at {exe_path}")
            return True, f"TTW_Linux_Installer installed at {target_dir}"

        except Exception as e:
            self.logger.error(f"Error installing TTW_Linux_Installer: {e}", exc_info=True)
            return False, f"Error installing TTW_Linux_Installer: {e}"

    def get_installed_ttw_installer_version(self) -> Optional[str]:
        """Return the installed TTW_Linux_Installer version stored in Jackify config, if any."""
        try:
            v = self.config_handler.get('ttw_installer_version')
            return str(v) if v else None
        except Exception:
            return None

    def is_ttw_installer_update_available(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if TTW_Linux_Installer update is available.
        If a version is pinned, compares against pinned version instead of latest.
        Returns (update_available, installed_version, target_version).
        """
        installed = self.get_installed_ttw_installer_version()
        
        # If we have a pinned version, compare against that instead of latest
        if TTW_INSTALLER_PINNED_VERSION:
            if not installed:
                # No version recorded - check if executable exists to infer version
                if self.ttw_installer_installed and self.ttw_installer_executable_path:
                    exe_name = self.ttw_installer_executable_path.name
                    # If pinned to 0.0.7 but found mpi_installer, it's wrong version
                    if TTW_INSTALLER_PINNED_VERSION == "0.0.7" and exe_name == "mpi_installer":
                        return (True, None, TTW_INSTALLER_PINNED_VERSION)
                    # If pinned to 0.0.7 and found ttw_linux_gui, assume correct
                    elif TTW_INSTALLER_PINNED_VERSION == "0.0.7" and exe_name == "ttw_linux_gui":
                        return (False, None, TTW_INSTALLER_PINNED_VERSION)
                # Not installed - don't show as update available
                return (False, None, TTW_INSTALLER_PINNED_VERSION)
            
            # Compare against pinned version
            if installed != TTW_INSTALLER_PINNED_VERSION:
                # Installed version doesn't match pinned - show as out of date (allows downgrade)
                return (True, installed, TTW_INSTALLER_PINNED_VERSION)
            else:
                return (False, installed, TTW_INSTALLER_PINNED_VERSION)
        
        # No pinned version - check against latest release (original behavior)
        # If executable exists but no version is recorded, don't show as "out of date"
        if not installed and self.ttw_installer_installed:
            self.logger.info("TTW_Linux_Installer executable found but no version recorded in config")
            # Don't treat as update available - just show as "Ready" (unknown version)
            return (False, None, None)
        
        try:
            resp = requests.get(TTW_INSTALLER_RELEASE_URL, timeout=10, verify=True)
            resp.raise_for_status()
            latest = resp.json().get('tag_name') or resp.json().get('name')
            if not latest:
                return (False, installed, None)
            if not installed:
                # No version recorded and executable doesn't exist; treat as not installed
                return (False, None, str(latest))
            return (installed != str(latest), installed, str(latest))
        except Exception as e:
            self.logger.warning(f"Error checking for TTW_Linux_Installer updates: {e}")
            return (False, installed, None)

    def install_ttw_backend(self, ttw_mpi_path: Path, ttw_output_path: Path) -> Tuple[bool, str]:
        """Install TTW using TTW_Linux_Installer.
        
        Args:
            ttw_mpi_path: Path to TTW .mpi file
            ttw_output_path: Target installation directory
            
        Returns:
            (success: bool, message: str)
        """
        self.logger.info("Starting Tale of Two Wastelands installation via TTW_Linux_Installer")

        # Validate parameters
        if not ttw_mpi_path or not ttw_output_path:
            return False, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"

        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)

        # Validate paths
        if not ttw_mpi_path.exists():
            return False, f"TTW .mpi file not found: {ttw_mpi_path}"

        if not ttw_mpi_path.is_file():
            return False, f"TTW .mpi path is not a file: {ttw_mpi_path}"

        if ttw_mpi_path.suffix.lower() != '.mpi':
            return False, f"TTW path does not have .mpi extension: {ttw_mpi_path}"

        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Failed to create output directory: {e}"

        # Check installation
        if not self.ttw_installer_installed:
            # Try to install automatically
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return False, f"TTW_Linux_Installer not installed and auto-install failed: {message}"

        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return False, "TTW_Linux_Installer executable not found"

        # Detect game paths
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return False, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."

        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')

        if not fallout3_path or not falloutnv_path:
            return False, "Could not detect Fallout 3 or Fallout New Vegas installation paths"

        # Construct command - run in CLI mode with arguments
        cmd = [
            str(self.ttw_installer_executable_path),
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--output", str(ttw_output_path),
            "--start"
        ]

        self.logger.info(f"Executing TTW_Linux_Installer: {' '.join(cmd)}")

        try:
            env = get_clean_subprocess_env()
            # CRITICAL: cwd must be the directory containing the executable, not the extraction root
            # This is because AppContext.BaseDirectory (used by TTW installer to find BundledBinaries)
            # is the directory containing the executable, not the working directory
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd,
                cwd=exe_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Stream output to logger
            if process.stdout:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        self.logger.info(f"TTW_Linux_Installer: {line}")

            process.wait()
            ret = process.returncode

            if ret == 0:
                self.logger.info("TTW installation completed successfully.")
                return True, "TTW installation completed successfully!"
            else:
                self.logger.error(f"TTW installation process returned non-zero exit code: {ret}")
                return False, f"TTW installation failed with exit code {ret}"

        except Exception as e:
            self.logger.error(f"Error executing TTW_Linux_Installer: {e}", exc_info=True)
            return False, f"Error executing TTW_Linux_Installer: {e}"

    def start_ttw_installation(self, ttw_mpi_path: Path, ttw_output_path: Path, output_file: Path):
        """Start TTW installation process (non-blocking).

        Starts the TTW_Linux_Installer subprocess with output redirected to a file.
        Returns immediately with process handle. Caller should poll process and read output file.

        Args:
            ttw_mpi_path: Path to TTW .mpi file
            ttw_output_path: Target installation directory
            output_file: Path to file where stdout/stderr will be written

        Returns:
            (process: subprocess.Popen, error_message: str) - process is None if failed
        """
        self.logger.info("Starting TTW installation (non-blocking mode)")

        # Validate parameters
        if not ttw_mpi_path or not ttw_output_path:
            return None, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"

        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)

        # Validate paths
        if not ttw_mpi_path.exists():
            return None, f"TTW .mpi file not found: {ttw_mpi_path}"

        if not ttw_mpi_path.is_file():
            return None, f"TTW .mpi path is not a file: {ttw_mpi_path}"

        if ttw_mpi_path.suffix.lower() != '.mpi':
            return None, f"TTW path does not have .mpi extension: {ttw_mpi_path}"

        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return None, f"Failed to create output directory: {e}"

        # Check installation
        if not self.ttw_installer_installed:
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return None, f"TTW_Linux_Installer not installed and auto-install failed: {message}"

        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return None, "TTW_Linux_Installer executable not found"

        # Detect game paths
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return None, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."

        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')

        if not fallout3_path or not falloutnv_path:
            return None, "Could not detect Fallout 3 or Fallout New Vegas installation paths"

        # Construct command
        cmd = [
            str(self.ttw_installer_executable_path),
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--output", str(ttw_output_path),
            "--start"
        ]

        self.logger.info(f"Executing TTW_Linux_Installer: {' '.join(cmd)}")

        try:
            env = get_clean_subprocess_env()
            # Note: TTW_Linux_Installer bundles its own lz4 and will find it via AppContext.BaseDirectory
            # We set cwd to the executable's directory so AppContext.BaseDirectory matches the working directory

            # Open output file for writing
            output_fh = open(output_file, 'w', encoding='utf-8', buffering=1)

            # Start process with output redirected to file
            # CRITICAL: cwd must be the directory containing the executable, not the extraction root
            # This is because AppContext.BaseDirectory (used by TTW installer to find BundledBinaries)
            # is the directory containing the executable, not the working directory
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd,
                cwd=exe_dir,
                env=env,
                stdout=output_fh,
                stderr=subprocess.STDOUT,
                bufsize=1
            )

            self.logger.info(f"TTW_Linux_Installer process started (PID: {process.pid}), output to {output_file}")

            # Store file handle so it can be closed later
            process._output_fh = output_fh

            return process, None

        except Exception as e:
            self.logger.error(f"Error starting TTW_Linux_Installer: {e}", exc_info=True)
            return None, f"Error starting TTW_Linux_Installer: {e}"

    @staticmethod
    def cleanup_ttw_process(process):
        """Clean up after TTW installation process.

        Closes file handles and ensures process is terminated properly.

        Args:
            process: subprocess.Popen object from start_ttw_installation()
        """
        if process:
            # Close output file handle if attached
            if hasattr(process, '_output_fh'):
                try:
                    process._output_fh.close()
                except Exception:
                    pass

            # Terminate if still running
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

    def install_ttw_backend_with_output_stream(self, ttw_mpi_path: Path, ttw_output_path: Path, output_callback=None):
        """Install TTW with streaming output for GUI (DEPRECATED - use start_ttw_installation instead).

        Args:
            ttw_mpi_path: Path to TTW .mpi file
            ttw_output_path: Target installation directory
            output_callback: Optional callback function(line: str) for real-time output

        Returns:
            (success: bool, message: str)
        """
        self.logger.info("Starting Tale of Two Wastelands installation via TTW_Linux_Installer (with output stream)")

        # Validate parameters (same as install_ttw_backend)
        if not ttw_mpi_path or not ttw_output_path:
            return False, "Missing required parameters: ttw_mpi_path and ttw_output_path are required"

        ttw_mpi_path = Path(ttw_mpi_path)
        ttw_output_path = Path(ttw_output_path)

        # Validate paths
        if not ttw_mpi_path.exists():
            return False, f"TTW .mpi file not found: {ttw_mpi_path}"

        if not ttw_mpi_path.is_file():
            return False, f"TTW .mpi path is not a file: {ttw_mpi_path}"

        if ttw_mpi_path.suffix.lower() != '.mpi':
            return False, f"TTW path does not have .mpi extension: {ttw_mpi_path}"

        if not ttw_output_path.exists():
            try:
                ttw_output_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Failed to create output directory: {e}"

        # Check installation
        if not self.ttw_installer_installed:
            if output_callback:
                output_callback("TTW_Linux_Installer not found, installing...")
            self.logger.info("TTW_Linux_Installer not found, attempting to install...")
            success, message = self.install_ttw_installer()
            if not success:
                return False, f"TTW_Linux_Installer not installed and auto-install failed: {message}"

        if not self.ttw_installer_executable_path or not self.ttw_installer_executable_path.is_file():
            return False, "TTW_Linux_Installer executable not found"

        # Detect game paths
        required_games = ['Fallout 3', 'Fallout New Vegas']
        detected_games = self.path_handler.find_vanilla_game_paths()
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            return False, f"Missing required games: {', '.join(missing_games)}. TTW requires both Fallout 3 and Fallout New Vegas."

        fallout3_path = detected_games.get('Fallout 3')
        falloutnv_path = detected_games.get('Fallout New Vegas')

        if not fallout3_path or not falloutnv_path:
            return False, "Could not detect Fallout 3 or Fallout New Vegas installation paths"

        # Construct command
        cmd = [
            str(self.ttw_installer_executable_path),
            "--fo3", str(fallout3_path),
            "--fnv", str(falloutnv_path),
            "--mpi", str(ttw_mpi_path),
            "--output", str(ttw_output_path),
            "--start"
        ]

        self.logger.info(f"Executing TTW_Linux_Installer: {' '.join(cmd)}")

        try:
            env = get_clean_subprocess_env()
            # CRITICAL: cwd must be the directory containing the executable, not the extraction root
            # This is because AppContext.BaseDirectory (used by TTW installer to find BundledBinaries)
            # is the directory containing the executable, not the working directory
            exe_dir = str(self.ttw_installer_executable_path.parent)
            process = subprocess.Popen(
                cmd,
                cwd=exe_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Stream output to both logger and callback
            if process.stdout:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        self.logger.info(f"TTW_Linux_Installer: {line}")
                        if output_callback:
                            output_callback(line)

            process.wait()
            ret = process.returncode

            if ret == 0:
                self.logger.info("TTW installation completed successfully.")
                return True, "TTW installation completed successfully!"
            else:
                self.logger.error(f"TTW installation process returned non-zero exit code: {ret}")
                return False, f"TTW installation failed with exit code {ret}"

        except Exception as e:
            self.logger.error(f"Error executing TTW_Linux_Installer: {e}", exc_info=True)
            return False, f"Error executing TTW_Linux_Installer: {e}"

    @staticmethod
    def integrate_ttw_into_modlist(ttw_output_path: Path, modlist_install_dir: Path, ttw_version: str) -> bool:
        """Integrate TTW output into a modlist's MO2 structure

        This method:
        1. Copies TTW output to the modlist's mods folder
        2. Updates modlist.txt for all profiles
        3. Updates plugins.txt with TTW ESMs in correct order

        Args:
            ttw_output_path: Path to TTW output directory
            modlist_install_dir: Path to modlist installation directory
            ttw_version: TTW version string (e.g., "3.4")

        Returns:
            bool: True if integration successful, False otherwise
        """
        logging_handler = LoggingHandler()
        logging_handler.rotate_log_for_logger('ttw-install', 'TTW_Install_workflow.log')
        logger = logging_handler.setup_logger('ttw-install', 'TTW_Install_workflow.log')

        try:
            import shutil

            # Validate paths
            if not ttw_output_path.exists():
                logger.error(f"TTW output path does not exist: {ttw_output_path}")
                return False

            mods_dir = modlist_install_dir / "mods"
            profiles_dir = modlist_install_dir / "profiles"

            if not mods_dir.exists() or not profiles_dir.exists():
                logger.error(f"Invalid modlist directory structure: {modlist_install_dir}")
                return False

            # Create mod folder name with version
            mod_folder_name = f"[NoDelete] Tale of Two Wastelands {ttw_version}" if ttw_version else "[NoDelete] Tale of Two Wastelands"
            target_mod_dir = mods_dir / mod_folder_name

            # Copy TTW output to mods directory
            logger.info(f"Copying TTW output to {target_mod_dir}")
            if target_mod_dir.exists():
                logger.info(f"Removing existing TTW mod at {target_mod_dir}")
                shutil.rmtree(target_mod_dir)

            shutil.copytree(ttw_output_path, target_mod_dir)
            logger.info("TTW output copied successfully")

            # TTW ESMs in correct load order
            ttw_esms = [
                "Fallout3.esm",
                "Anchorage.esm",
                "ThePitt.esm",
                "BrokenSteel.esm",
                "PointLookout.esm",
                "Zeta.esm",
                "TaleOfTwoWastelands.esm",
                "YUPTTW.esm"
            ]

            # Process each profile
            for profile_dir in profiles_dir.iterdir():
                if not profile_dir.is_dir():
                    continue

                profile_name = profile_dir.name
                logger.info(f"Processing profile: {profile_name}")

                # Update modlist.txt
                modlist_file = profile_dir / "modlist.txt"
                if modlist_file.exists():
                    # Read existing modlist
                    with open(modlist_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    # Find the TTW placeholder separator and insert BEFORE it
                    separator_found = False
                    ttw_mod_line = f"+{mod_folder_name}\n"
                    new_lines = []

                    for line in lines:
                        # Skip existing TTW mod entries (but keep separators and other TTW-related mods)
                        # Match patterns: "+[NoDelete] Tale of Two Wastelands", "+[NoDelete] TTW", etc.
                        stripped = line.strip()
                        if stripped.startswith('+') and '[nodelete]' in stripped.lower():
                            # Check if it's the main TTW mod (not other TTW-related mods like "TTW Quick Start")
                            if ('tale of two wastelands' in stripped.lower() and 'quick start' not in stripped.lower() and
                                'loading wheel' not in stripped.lower()) or stripped.lower().startswith('+[nodelete] ttw '):
                                logger.info(f"Removing existing TTW mod entry: {stripped}")
                                continue

                        # Insert TTW mod BEFORE the placeholder separator (MO2 order is bottom-up)
                        # Check BEFORE appending so TTW mod appears before separator in file
                        if "put tale of two wastelands mod here" in line.lower() and "_separator" in line.lower():
                            new_lines.append(ttw_mod_line)
                            separator_found = True
                            logger.info(f"Inserted TTW mod before separator: {line.strip()}")

                        new_lines.append(line)

                    # If no separator found, append at the end
                    if not separator_found:
                        new_lines.append(ttw_mod_line)
                        logger.warning(f"No TTW separator found in {profile_name}, appended to end")

                    # Write back
                    with open(modlist_file, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)

                    logger.info(f"Updated modlist.txt for {profile_name}")
                else:
                    logger.warning(f"modlist.txt not found for profile {profile_name}")

                # Update plugins.txt
                plugins_file = profile_dir / "plugins.txt"
                if plugins_file.exists():
                    # Read existing plugins
                    with open(plugins_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    # Remove any existing TTW ESMs
                    ttw_esm_set = set(esm.lower() for esm in ttw_esms)
                    lines = [line for line in lines if line.strip().lower() not in ttw_esm_set]

                    # Find CaravanPack.esm and insert TTW ESMs after it
                    insert_index = None
                    for i, line in enumerate(lines):
                        if line.strip().lower() == "caravanpack.esm":
                            insert_index = i + 1
                            break

                    if insert_index is not None:
                        # Insert TTW ESMs in correct order
                        for esm in reversed(ttw_esms):
                            lines.insert(insert_index, f"{esm}\n")
                    else:
                        logger.warning(f"CaravanPack.esm not found in {profile_name}, appending TTW ESMs to end")
                        for esm in ttw_esms:
                            lines.append(f"{esm}\n")

                    # Write back
                    with open(plugins_file, 'w', encoding='utf-8') as f:
                        f.writelines(lines)

                    logger.info(f"Updated plugins.txt for {profile_name}")
                else:
                    logger.warning(f"plugins.txt not found for profile {profile_name}")

            logger.info("TTW integration completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error integrating TTW into modlist: {e}", exc_info=True)
            return False
