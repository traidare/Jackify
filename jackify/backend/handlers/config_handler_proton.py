"""
Config handler Proton path and version getters and auto-detect.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ConfigProtonMixin:
    """Mixin providing Proton path/version and auto-detect for ConfigHandler."""

    @staticmethod
    def _is_usable_proton_path(proton_path: Optional[str]) -> bool:
        """Return True when path looks like a valid Proton install directory."""
        if not proton_path:
            return False
        try:
            p = Path(str(proton_path)).expanduser()
            if not p.is_dir():
                return False
            # Valve Proton structure
            if (p / "dist" / "bin" / "wine").exists():
                return True
            # GE-Proton structure
            if (p / "files" / "bin" / "wine").exists():
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def _best_proton_entry() -> Optional[Dict[str, Any]]:
        """Get best detected Proton entry or None."""
        try:
            from .wine_utils import WineUtils
            return WineUtils.select_best_proton()
        except Exception:
            return None

    def normalize_proton_paths_on_boot(self) -> bool:
        """
        Ensure stored Proton paths are valid at startup, repairing stale selections.

        Rules:
        - If install proton path is missing/invalid, auto-detect next best and persist it.
        - If no compatible Proton exists, persist install path/version as null.
        - If game proton path is set and invalid, reset it to install proton (or null).

        Returns:
            True if config values were changed and saved, False otherwise.
        """
        changed = False

        install_path = self.settings.get("proton_path")
        if install_path == "auto":
            install_path = None

        install_valid = self._is_usable_proton_path(install_path)
        if not install_valid:
            best = self._best_proton_entry()
            if best:
                best_path = str(best["path"])
                best_name = str(best.get("name") or Path(best_path).name)
                if self.settings.get("proton_path") != best_path:
                    self.settings["proton_path"] = best_path
                    changed = True
                if self.settings.get("proton_version") != best_name:
                    self.settings["proton_version"] = best_name
                    changed = True
                logger.warning(
                    "Install Proton path was missing/invalid; auto-selected %s (%s)",
                    best_name,
                    best_path,
                )
            else:
                if self.settings.get("proton_path") is not None:
                    self.settings["proton_path"] = None
                    changed = True
                if self.settings.get("proton_version") is not None:
                    self.settings["proton_version"] = None
                    changed = True
                logger.warning(
                    "Install Proton path was missing/invalid and no compatible Proton was found"
                )
        else:
            # Keep proton_version in sync with existing valid path when missing/legacy.
            if not self.settings.get("proton_version"):
                self.settings["proton_version"] = Path(str(install_path)).name
                changed = True

        effective_install = self.settings.get("proton_path")
        game_path = self.settings.get("game_proton_path")

        # Legacy/placeholder values should not persist for runtime resolution.
        if game_path in ("same_as_install", "auto"):
            target = effective_install
            if self.settings.get("game_proton_path") != target:
                self.settings["game_proton_path"] = target
                changed = True
        elif game_path and not self._is_usable_proton_path(game_path):
            self.settings["game_proton_path"] = effective_install
            changed = True
            logger.warning(
                "Game Proton path was missing/invalid; reset to install Proton path"
            )

        if changed:
            self.save_config()
        return changed

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
