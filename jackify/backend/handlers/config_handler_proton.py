"""
Config handler Proton path and version getters and auto-detect.
"""

import logging

logger = logging.getLogger(__name__)


class ConfigProtonMixin:
    """Mixin providing Proton path/version and auto-detect for ConfigHandler."""

    def get_proton_path(self):
        """Retrieve the saved Install Proton path. Always reads fresh from disk."""
        try:
            config = self._read_config_from_disk()
            proton_path = config.get("proton_path")
            if not proton_path:
                logger.debug("proton_path not set in config - will use auto-detection")
                return None
            logger.debug("Retrieved fresh install proton_path from config: %s", proton_path)
            return proton_path
        except Exception as e:
            logger.error("Error retrieving install proton_path: %s", e)
            return None

    def get_game_proton_path(self):
        """Retrieve the saved Game Proton path. Falls back to install Proton. Always reads fresh from disk."""
        try:
            config = self._read_config_from_disk()
            game_proton_path = config.get("game_proton_path")
            if not game_proton_path or game_proton_path == "same_as_install":
                game_proton_path = config.get("proton_path")
            if not game_proton_path:
                logger.debug("game_proton_path not set in config - will use auto-detection")
                return None
            logger.debug("Retrieved fresh game proton_path from config: %s", game_proton_path)
            return game_proton_path
        except Exception as e:
            logger.error("Error retrieving game proton_path: %s", e)
            return "auto"

    def get_proton_version(self):
        """Retrieve the saved Proton version. Always reads fresh from disk."""
        try:
            config = self._read_config_from_disk()
            proton_version = config.get("proton_version", "auto")
            logger.debug("Retrieved fresh proton_version from config: %s", proton_version)
            return proton_version
        except Exception as e:
            logger.error("Error retrieving proton_version: %s", e)
            return "auto"

    def _auto_detect_proton(self):
        """Auto-detect and set best Proton version (GE-Proton and Valve Proton)."""
        try:
            from .wine_utils import WineUtils
            best_proton = WineUtils.select_best_proton()
            if best_proton:
                self.settings["proton_path"] = str(best_proton['path'])
                self.settings["proton_version"] = best_proton['name']
                proton_type = best_proton.get('type', 'Unknown')
                logger.info("Auto-detected Proton: %s (%s)", best_proton['name'], proton_type)
                self.save_config()
            else:
                self.settings["proton_path"] = None
                self.settings["proton_version"] = None
                logger.warning("No compatible Proton versions found - proton_path set to null in config.json")
                logger.info("Jackify will auto-detect Proton on each run until a valid version is found")
                self.save_config()
        except Exception as e:
            logger.error("Failed to auto-detect Proton: %s", e)
            self.settings["proton_path"] = None
            self.settings["proton_version"] = None
            logger.warning("proton_path set to null in config.json due to auto-detection failure")
            self.save_config()
