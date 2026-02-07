#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks verification mixin: component install verification.
Extracted from winetricks_handler for file-size and domain separation.
"""

import os
import logging
from typing import List


class WinetricksVerificationMixin:
    """Mixin providing verification of installed Wine components."""

    def _verify_components_installed(self, wineprefix: str, components: List[str], env: dict) -> bool:
        """Verify that every requested component was installed (winetricks.log)."""
        try:
            self.logger.info("Verifying installed components...")
            winetricks_log = os.path.join(wineprefix, 'winetricks.log')
            log_content = ""
            if os.path.exists(winetricks_log):
                try:
                    with open(winetricks_log, 'r', encoding='utf-8', errors='ignore') as f:
                        log_content = f.read().lower()
                except Exception as e:
                    self.logger.error(f"Failed to read winetricks.log: {e}")
                    return False
            self.logger.debug(f"winetricks.log length: {len(log_content)} bytes")
            missing = []
            for component in components:
                base_component = component.split('=')[0].lower()
                if base_component in log_content or component.lower() in log_content:
                    continue
                missing.append(component)
            if missing:
                self.logger.error(f"Components not verified installed: {missing}")
                return False
            self.logger.info("Verification passed - all components confirmed")
            return True
        except Exception as e:
            self.logger.error(f"Error verifying components: {e}", exc_info=True)
            return False
