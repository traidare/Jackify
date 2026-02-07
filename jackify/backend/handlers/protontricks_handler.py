#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks Handler Module
Handles detection and operation of Protontricks.
Delegates to mixins: detection, commands, steam (permissions/aliases/shortcuts), prefix (dotfiles/win10/components).
"""

import logging

from .protontricks_detection import ProtontricksDetectionMixin
from .protontricks_commands import ProtontricksCommandsMixin
from .protontricks_steam import ProtontricksSteamMixin
from .protontricks_prefix import ProtontricksPrefixMixin

logger = logging.getLogger(__name__)


class ProtontricksHandler(
    ProtontricksDetectionMixin,
    ProtontricksCommandsMixin,
    ProtontricksSteamMixin,
    ProtontricksPrefixMixin,
):
    """
    Handles operations related to Protontricks detection and usage.
    Supports native Steam operations as fallback/replacement for protontricks.
    """

    def __init__(self, steamdeck: bool, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.which_protontricks = None
        self.flatpak_install_type = None
        self.protontricks_version = None
        self.protontricks_path = None
        self.steamdeck = steamdeck
        self._native_steam_service = None
        self.use_native_operations = True

    def check_and_setup_protontricks(self) -> bool:
        """
        Run detection, version check, and alias setup for Protontricks.
        Returns True if Protontricks is ready to use, False otherwise.
        """
        self.logger.info("Checking and setting up Protontricks...")
        self.logger.info("Checking Protontricks installation...")
        if not self.detect_protontricks():
            return False
        self.logger.info(f"Protontricks detected: {self.which_protontricks}")

        self.logger.info("Checking Protontricks version...")
        if not self.check_protontricks_version():
            self.logger.error(f"Protontricks version {self.protontricks_version} is too old or could not be checked.")
            return False
        self.logger.info(f"Protontricks version {self.protontricks_version} is sufficient.")

        if self.which_protontricks == 'flatpak':
            self.logger.info("Ensuring Flatpak aliases exist in ~/.bashrc...")
            if not self.protontricks_alias():
                self.logger.warning("Failed to create/verify protontricks aliases in ~/.bashrc")

        self.logger.info("Protontricks check and setup completed successfully.")
        return True
