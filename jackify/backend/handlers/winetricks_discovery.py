#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winetricks discovery mixin: bundled path and tool availability.
Extracted from winetricks_handler for file-size and domain separation.
"""

import os
import subprocess
import logging
import shutil
from pathlib import Path
from typing import Optional


class WinetricksDiscoveryMixin:
    """Mixin providing winetricks path discovery and availability checks."""

    def _get_bundled_winetricks_path(self) -> Optional[str]:
        """Get the bundled winetricks script, or fall back to PATH-provided winetricks."""
        possible_paths = []
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', 'winetricks')
            possible_paths.append(appdir_path)
        module_dir = Path(__file__).parent.parent.parent
        dev_path = module_dir / 'tools' / 'winetricks'
        possible_paths.append(str(dev_path))
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled winetricks at: {path}")
                return str(path)
        system_winetricks = shutil.which('winetricks')
        if system_winetricks:
            self.logger.debug(f"Using system winetricks from PATH: {system_winetricks}")
            return system_winetricks
        self.logger.error(f"Winetricks not found. Tried bundled paths: {possible_paths}")
        return None

    def _get_bundled_tool(self, tool_name: str, fallback_to_system: bool = True) -> Optional[str]:
        """Get path to a bundled tool (e.g. cabextract, wget). Fall back to system PATH if requested."""
        possible_paths = []
        if os.environ.get('APPDIR'):
            appdir_path = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', tool_name)
            possible_paths.append(appdir_path)
        module_dir = Path(__file__).parent.parent.parent
        dev_path = module_dir / 'tools' / tool_name
        possible_paths.append(str(dev_path))
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self.logger.debug(f"Found bundled {tool_name} at: {path}")
                return str(path)
        if fallback_to_system:
            try:
                import shutil
                system_tool = shutil.which(tool_name)
                if system_tool:
                    self.logger.debug(f"Using system {tool_name}: {system_tool}")
                    return system_tool
            except Exception:
                pass
        self.logger.debug(f"Bundled {tool_name} not found in tools directory")
        return None

    def _get_bundled_cabextract(self) -> Optional[str]:
        """Get the path to the bundled cabextract binary. Backward compatibility."""
        return self._get_bundled_tool('cabextract', fallback_to_system=True)

    def is_available(self) -> bool:
        """Check if winetricks is available and ready to use."""
        if not self.winetricks_path:
            self.logger.error("Winetricks executable not found")
            return False
        try:
            env = os.environ.copy()
            result = subprocess.run(
                [self.winetricks_path, '--version'],
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )
            if result.returncode == 0:
                self.logger.debug(f"Winetricks version: {result.stdout.strip()}")
                return True
            self.logger.error(f"Winetricks --version failed: {result.stderr}")
            return False
        except Exception as e:
            self.logger.error(f"Error testing winetricks: {e}")
            return False
