"""
Steam path discovery for FileSystemHandler: find_steam_library, find_compat_data, find_steam_config_vdf.
"""

import logging
from pathlib import Path
from typing import Optional

import vdf

logger = logging.getLogger(__name__)


class FilesystemSteamMixin:
    """Mixin providing Steam library and compatdata path discovery for FileSystemHandler."""

    @staticmethod
    def find_steam_library() -> Optional[Path]:
        """
        Find the Steam library containing game installations, prioritizing vdf.

        Returns:
            Optional[Path]: Path object to the Steam library's steamapps/common dir, or None if not found
        """
        logger.info("Detecting Steam library location...")

        possible_vdf_paths = [
            Path.home() / ".steam/steam/config/libraryfolders.vdf",
            Path.home() / ".local/share/Steam/config/libraryfolders.vdf",
            Path.home() / ".steam/root/config/libraryfolders.vdf",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/config/libraryfolders.vdf"
        ]

        libraryfolders_vdf_path: Optional[Path] = None
        for path_obj in possible_vdf_paths:
            current_path = Path(path_obj)
            if current_path.is_file():
                libraryfolders_vdf_path = current_path
                logger.debug(f"Found libraryfolders.vdf at: {libraryfolders_vdf_path}")
                break

        if not libraryfolders_vdf_path:
            logger.warning("libraryfolders.vdf not found...")
        else:
            try:
                with open(libraryfolders_vdf_path, 'r') as f:
                    data = vdf.load(f)

                libraries = data.get('libraryfolders', {})
                for key in libraries:
                    if isinstance(libraries[key], dict) and 'path' in libraries[key]:
                        lib_path_str = libraries[key]['path']
                        if lib_path_str:
                            potential_lib_path = Path(lib_path_str) / "steamapps/common"
                            if potential_lib_path.is_dir():
                                logger.info(f"Using Steam library path from vdf: {potential_lib_path}")
                                return potential_lib_path

                logger.warning("No valid library paths found within libraryfolders.vdf.")
            except ImportError:
                logger.error("Python 'vdf' library not found. Cannot parse libraryfolders.vdf.")
            except Exception as e:
                logger.error(f"Error parsing libraryfolders.vdf: {e}")

        default_path = Path.home() / ".steam/steam/steamapps/common"
        if default_path.is_dir():
            logger.warning(f"Using default Steam library path: {default_path}")
            return default_path

        logger.error("No valid Steam library found via vdf or at default location.")
        return None

    @staticmethod
    def find_compat_data(appid: str) -> Optional[Path]:
        """Find the compatdata directory for a given AppID."""
        if not appid or not appid.isdigit():
            logger.error(f"Invalid AppID provided for compatdata search: {appid}")
            return None

        logger.debug(f"Searching for compatdata directory for AppID: {appid}")

        possible_bases = [
            Path.home() / ".steam/steam/steamapps/compatdata",
            Path.home() / ".local/share/Steam/steamapps/compatdata",
        ]

        steam_lib_common_path: Optional[Path] = FilesystemSteamMixin.find_steam_library()
        if steam_lib_common_path:
            library_root = steam_lib_common_path.parent.parent
            vdf_compat_path = library_root / "steamapps/compatdata"
            if vdf_compat_path.is_dir() and vdf_compat_path not in possible_bases:
                possible_bases.insert(0, vdf_compat_path)

        for base_path in possible_bases:
            if not base_path.is_dir():
                logger.debug(f"Compatdata base path does not exist or is not a directory: {base_path}")
                continue

            potential_path = base_path / appid
            if potential_path.is_dir():
                logger.info(f"Found compatdata directory: {potential_path}")
                return potential_path
            logger.debug(f"Compatdata for {appid} not found in {base_path}")

        logger.warning(f"Compatdata directory for AppID {appid} not found in standard or detected library locations.")
        return None

    @staticmethod
    def find_steam_config_vdf() -> Optional[Path]:
        """Finds the active Steam config.vdf file."""
        logger.debug("Searching for Steam config.vdf...")
        possible_steam_paths = [
            Path.home() / ".steam/steam",
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/root"
        ]
        for steam_path in possible_steam_paths:
            potential_path = steam_path / "config/config.vdf"
            if potential_path.is_file():
                logger.info(f"Found config.vdf at: {potential_path}")
                return potential_path

        logger.warning("Could not locate Steam's config.vdf file in standard locations.")
        return None
