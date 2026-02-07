"""
Config handler directory paths: install/download parent and modlist base dirs.
"""

import os
import logging

logger = logging.getLogger(__name__)


class ConfigDirectoriesMixin:
    """Mixin providing directory path getters/setters for ConfigHandler."""

    def set_default_install_parent_dir(self, path):
        """Save the parent directory for modlist installations."""
        try:
            if path and os.path.exists(path):
                self.settings["default_install_parent_dir"] = path
                logger.debug("Default install parent directory saved: %s", path)
                return self.save_config()
            logger.warning("Invalid or non-existent path for install parent directory: %s", path)
            return False
        except Exception as e:
            logger.error("Error saving install parent directory: %s", e)
            return False

    def get_default_install_parent_dir(self):
        """Retrieve the saved parent directory for modlist installations."""
        try:
            path = self.settings.get("default_install_parent_dir")
            if path and os.path.exists(path):
                logger.debug("Retrieved default install parent directory: %s", path)
                return path
            logger.debug("No valid default install parent directory found")
            return None
        except Exception as e:
            logger.error("Error retrieving install parent directory: %s", e)
            return None

    def set_default_download_parent_dir(self, path):
        """Save the parent directory for downloads."""
        try:
            if path and os.path.exists(path):
                self.settings["default_download_parent_dir"] = path
                logger.debug("Default download parent directory saved: %s", path)
                return self.save_config()
            logger.warning("Invalid or non-existent path for download parent directory: %s", path)
            return False
        except Exception as e:
            logger.error("Error saving download parent directory: %s", e)
            return False

    def get_default_download_parent_dir(self):
        """Retrieve the saved parent directory for downloads."""
        try:
            path = self.settings.get("default_download_parent_dir")
            if path and os.path.exists(path):
                logger.debug("Retrieved default download parent directory: %s", path)
                return path
            logger.debug("No valid default download parent directory found")
            return None
        except Exception as e:
            logger.error("Error retrieving download parent directory: %s", e)
            return None

    def has_saved_install_parent_dir(self):
        """Check if a default install parent directory is saved and valid."""
        path = self.settings.get("default_install_parent_dir")
        return path is not None and os.path.exists(path)

    def has_saved_download_parent_dir(self):
        """Check if a default download parent directory is saved and valid."""
        path = self.settings.get("default_download_parent_dir")
        return path is not None and os.path.exists(path)

    def get_modlist_install_base_dir(self):
        """Get the configurable base directory for modlist installations."""
        return self.settings.get("modlist_install_base_dir", os.path.expanduser("~/Games"))

    def set_modlist_install_base_dir(self, path):
        """Set the configurable base directory for modlist installations."""
        try:
            if path:
                self.settings["modlist_install_base_dir"] = path
                logger.debug("Modlist install base directory saved: %s", path)
                return self.save_config()
            logger.warning("Invalid path for modlist install base directory")
            return False
        except Exception as e:
            logger.error("Error saving modlist install base directory: %s", e)
            return False

    def get_modlist_downloads_base_dir(self):
        """Get the configurable base directory for modlist downloads."""
        return self.settings.get("modlist_downloads_base_dir", os.path.expanduser("~/Games/Modlist_Downloads"))

    def set_modlist_downloads_base_dir(self, path):
        """Set the configurable base directory for modlist downloads."""
        try:
            if path:
                self.settings["modlist_downloads_base_dir"] = path
                logger.debug("Modlist downloads base directory saved: %s", path)
                return self.save_config()
            logger.warning("Invalid path for modlist downloads base directory")
            return False
        except Exception as e:
            logger.error("Error saving modlist downloads base directory: %s", e)
            return False
