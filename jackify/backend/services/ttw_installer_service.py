"""Shared backend helpers for locating and installing TTW_Linux_Installer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from jackify.backend.handlers.config_handler import ConfigHandler
from jackify.backend.handlers.filesystem_handler import FileSystemHandler
from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler

logger = logging.getLogger(__name__)


def _build_handler() -> TTWInstallerHandler:
    return TTWInstallerHandler(
        steamdeck=False,
        verbose=False,
        filesystem_handler=FileSystemHandler(),
        config_handler=ConfigHandler(),
    )


def get_ttw_installer_path() -> Optional[Path]:
    """Return the resolved TTW_Linux_Installer executable path, if available."""
    handler = _build_handler()
    path = handler.ttw_installer_executable_path
    if path and path.exists():
        return path
    return None


def ensure_ttw_installer_available(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[Optional[Path], str]:
    """
    Ensure TTW_Linux_Installer is installed and return its executable path.

    Returns:
        (path, message)
    """
    existing = get_ttw_installer_path()
    if existing:
        return existing, "TTW_Linux_Installer ready"

    if progress_callback:
        progress_callback("TTW_Linux_Installer not found, installing...")

    handler = _build_handler()
    success, message = handler.install_ttw_installer()
    if not success:
        logger.error("Failed to install TTW_Linux_Installer: %s", message)
        return None, message

    path = handler.ttw_installer_executable_path
    if path and path.exists():
        if progress_callback:
            progress_callback("TTW_Linux_Installer installed successfully")
        return path, message

    return None, "TTW_Linux_Installer install completed but executable was not found"
