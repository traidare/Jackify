#!/usr/bin/env python3
"""
Platform Detection Service

Centralizes platform detection logic (Steam Deck, etc.) to be performed once at application startup
and shared across all components.
"""

import os
import logging

logger = logging.getLogger(__name__)


class PlatformDetectionService:
    """
    Service for detecting platform-specific information once at startup
    """

    _instance = None
    _is_steamdeck = None

    def __new__(cls):
        """Singleton pattern to ensure only one instance"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize platform detection if not already done"""
        if self._is_steamdeck is None:
            self._detect_platform()

    def _detect_platform(self):
        """Perform platform detection once"""
        logger.debug("Performing platform detection...")

        # Steam Deck detection
        self._is_steamdeck = False
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    content = f.read().lower()
                    if 'steamdeck' in content or 'steamos' in content:
                        self._is_steamdeck = True
                        logger.info("Steam Deck/SteamOS platform detected")
                    else:
                        logger.debug("Non-Steam Deck Linux platform detected")
            else:
                logger.debug("No /etc/os-release found - assuming non-Steam Deck platform")
        except Exception as e:
            logger.warning(f"Error detecting Steam Deck platform: {e}")
            self._is_steamdeck = False

        logger.debug(f"Platform detection complete: is_steamdeck={self._is_steamdeck}")

    @property
    def is_steamdeck(self) -> bool:
        """Get Steam Deck detection result"""
        if self._is_steamdeck is None:
            self._detect_platform()
        return self._is_steamdeck

    @classmethod
    def get_instance(cls):
        """Get the singleton instance"""
        return cls()