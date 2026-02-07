"""WebView installation methods for InstallWabbajackHandler (Mixin)."""
import logging
import shutil
import subprocess
from pathlib import Path

from .status_utils import show_status

logger = logging.getLogger(__name__)


class WabbajackWebViewMixin:
    """Mixin providing WebView installation methods."""

    def _install_webview(self) -> bool:
        """Installs the WebView2 runtime using protontricks-launch."""
        if not self.final_appid or not self.install_path:
            self.logger.error("Cannot install WebView: final_appid or install_path not set.")
            return False

        installer_name = "MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        installer_path = self.install_path / installer_name

        if not installer_path.is_file():
            self.logger.error(f"WebView installer not found at {installer_path}. Cannot install.")
            self.logger.error("WebView installer file missing. Please ensure step 12 completed.")
            return False

        self.logger.info(f"Starting WebView installation for AppID {self.final_appid}...")

        cmd_prefix = []
        if self.protontricks_handler.which_protontricks == 'flatpak':
            cmd_prefix = ["flatpak", "run", "--command=protontricks-launch", "com.github.Matoking.protontricks"]
        else:
            launch_path = shutil.which("protontricks-launch")
            if not launch_path:
                self.logger.error("protontricks-launch command not found in PATH.")
                self.logger.error("protontricks-launch command not found.")
                return False
            cmd_prefix = [launch_path]

        args = ["--appid", self.final_appid, str(installer_path), "/silent", "/install"]
        full_cmd = cmd_prefix + args

        self.logger.debug(f"Executing WebView install command: {' '.join(full_cmd)}")

        try:
            result = subprocess.run(full_cmd, check=True, capture_output=True, text=True, timeout=600)
            self.logger.info("WebView installation command completed successfully.")
            return True
        except FileNotFoundError:
            self.logger.error(f"Command not found: {cmd_prefix[0]}")
            self.logger.error(f"Could not execute {cmd_prefix[0]}. Is it installed correctly?")
            return False
        except subprocess.TimeoutExpired:
            self.logger.error("WebView installation timed out after 10 minutes.")
            self.logger.error("WebView installation took too long and timed out.")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"WebView installation failed with return code {e.returncode}")
            self.logger.error(f"STDERR (truncated):\n{e.stderr[:500] if e.stderr else ''}")
            self.logger.error(f"WebView installation failed (Return Code: {e.returncode}). Check logs for details.")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during WebView installation: {e}", exc_info=True)
            self.logger.error(f"An unexpected error occurred during WebView installation: {e}")
            return False

    def _download_webview_installer(self) -> bool:
        """
        Downloads the specific WebView2 installer needed by Wabbajack.
        Checks existence first.

        Returns:
            bool: True on success or if file already exists correctly, False otherwise.
        """
        if not self.install_path:
            self.logger.error("Cannot download WebView installer: install_path is not set.")
            return False

        url = "https://node10.sokloud.com/filebrowser/api/public/dl/yqVTbUT8/rwatch/WebView/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        file_name = "MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
        destination = self.install_path / file_name

        self.logger.info(f"Checking WebView installer: {destination}")

        if destination.is_file():
            self.logger.info(f"WebView installer {destination.name} already exists. Skipping download.")
            return True

        self.logger.info(f"WebView installer not found locally. Downloading {file_name}...")
        show_status("Downloading WebView Installer")

        if self._download_file(url, destination):
            return True
        else:
            self.logger.error(f"Failed to download WebView installer from {url}.")
            return False

    def _set_prefix_renderer(self, renderer: str = 'vulkan') -> bool:
        """Sets the prefix renderer using protontricks."""
        if not self.final_appid:
            self.logger.error("Cannot set renderer: final_appid not set.")
            return False

        self.logger.info(f"Setting prefix renderer to {renderer} for AppID {self.final_appid}...")
        try:
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                self.logger.critical("ProtontricksHandler not initialized in InstallWabbajackHandler!")
                self.logger.error("Internal Error: Protontricks handler not available.")
                return False

            result = self.protontricks_handler.run_protontricks(
                self.final_appid,
                'settings',
                f'renderer={renderer}'
            )
            if result and result.returncode == 0:
                self.logger.info(f"Successfully set renderer to {renderer}.")
                return True
            else:
                err_msg = result.stderr if result else "Command execution failed"
                self.logger.error(f"Failed to set renderer to {renderer}. Error: {err_msg}")
                self.logger.error(f"Failed to set prefix renderer to {renderer}.")
                return False
        except Exception as e:
            self.logger.error(f"Exception setting renderer: {e}", exc_info=True)
            self.logger.error(f"Error setting prefix renderer: {e}.")
            return False

    def _download_and_replace_reg_file(self, url: str, target_reg_path: Path) -> bool:
        """Downloads a .reg file and replaces the target file. Always downloads and overwrites."""
        self.logger.info(f"Downloading registry file from {url} to replace {target_reg_path}")

        if self._download_file(url, target_reg_path):
            self.logger.info(f"Successfully downloaded and replaced {target_reg_path}")
            return True
        else:
            self.logger.error(f"Failed to download/replace {target_reg_path} from {url}")
            return False
