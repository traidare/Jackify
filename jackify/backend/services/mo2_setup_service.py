"""
MO2 Setup Service

Downloads and configures a standalone Mod Organizer 2 instance:
  - Fetches latest release from GitHub
  - Extracts with 7z
  - Creates a Steam shortcut and Proton prefix via AutomatedPrefixService
"""

import re
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def _is_dangerous_path(path: Path) -> bool:
    home = Path.home().resolve()
    dangerous = [Path('/'), Path('/home'), Path('/root'), home]
    return any(path.resolve() == d for d in dangerous)


class MO2SetupService:
    """Download, extract, and configure a standalone MO2 instance."""

    GITHUB_API = "https://api.github.com/repos/ModOrganizer2/modorganizer/releases/latest"
    ASSET_PATTERN = re.compile(r"Mod\.Organizer-\d+\.\d+(\.\d+)?\.7z$")

    def setup_mo2(
        self,
        install_dir: Path,
        shortcut_name: str = "Mod Organizer 2",
        progress_callback: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Download, extract, and configure MO2.

        Returns (success, app_id, error_message).
        """

        def _progress(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)
        
        def _cancel_requested() -> bool:
            try:
                return bool(should_cancel and should_cancel())
            except Exception:
                return False

        if not shutil.which('7z'):
            return False, None, "7z not found. Install p7zip-full (or equivalent) first."

        if _is_dangerous_path(install_dir):
            return False, None, f"Refusing to install to dangerous path: {install_dir}"

        # Create directory
        try:
            install_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, None, f"Could not create directory: {e}"

        # Fetch release info
        _progress("Fetching latest MO2 release info...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            resp = requests.get(self.GITHUB_API, timeout=15, verify=True)
            resp.raise_for_status()
            release = resp.json()
        except Exception as e:
            return False, None, f"Failed to fetch MO2 release info: {e}"

        # Find asset
        asset = None
        for a in release.get('assets', []):
            if self.ASSET_PATTERN.match(a['name']):
                asset = a
                break
        if not asset:
            return False, None, "Could not find main MO2 .7z asset in latest release."

        # Download
        archive_path = install_dir / asset['name']
        _progress(f"Downloading {asset['name']}...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            with requests.get(asset['browser_download_url'], stream=True, timeout=120, verify=True) as r:
                r.raise_for_status()
                with open(archive_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if _cancel_requested():
                            return False, None, "MO2 setup cancelled."
                        f.write(chunk)
        except Exception as e:
            return False, None, f"Failed to download MO2 archive: {e}"

        # Extract
        _progress(f"Extracting to {install_dir}...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            result = subprocess.run(
                ['7z', 'x', str(archive_path), f'-o{install_dir}'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1200,
            )
            if result.returncode != 0:
                err = result.stderr.decode(errors='ignore')
                return False, None, f"Extraction failed: {err}"
        except Exception as e:
            return False, None, f"Extraction failed: {e}"

        # Validate
        mo2_exe = install_dir / "ModOrganizer.exe"
        if not mo2_exe.exists():
            # MO2 release archives usually extract into a single top-level folder.
            # Limit search depth to direct children to avoid expensive recursive scans.
            mo2_exe = None
            for child in install_dir.iterdir():
                candidate = child / "ModOrganizer.exe"
                if candidate.exists():
                    mo2_exe = candidate
                    break
        if not mo2_exe:
            return False, None, "ModOrganizer.exe not found after extraction."

        # Cleanup archive
        try:
            archive_path.unlink()
        except Exception:
            pass

        _progress(f"MO2 installed at: {mo2_exe.parent}")

        # Set up Steam shortcut and Proton prefix
        _progress("Creating Steam shortcut and Proton prefix...")
        if _cancel_requested():
            return False, None, "MO2 setup cancelled."
        try:
            from .automated_prefix_service import AutomatedPrefixService
            svc = AutomatedPrefixService()
            success, prefix_path, app_id, _last_ts = svc.run_working_workflow(
                shortcut_name=shortcut_name,
                modlist_install_dir=str(install_dir),
                final_exe_path=str(mo2_exe),
                progress_callback=_progress,
            )
        except Exception as e:
            logger.error(f"AutomatedPrefixService failed: {e}")
            return False, None, f"Prefix setup failed: {e}"

        if not success:
            return False, None, "Failed to create Steam shortcut or Proton prefix."

        _progress("MO2 setup complete.")
        return True, app_id, None
