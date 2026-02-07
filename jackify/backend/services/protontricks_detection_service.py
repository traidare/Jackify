#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protontricks Detection Service Module
Centralized service for detecting and managing protontricks installation across CLI and GUI frontends
"""

import logging
import os
import shutil
import subprocess
import sys
import importlib.util
from typing import Optional, Tuple
from ..handlers.protontricks_handler import ProtontricksHandler
from ..handlers.config_handler import ConfigHandler

# Initialize logger
logger = logging.getLogger(__name__)


class ProtontricksDetectionService:
    """
    Centralized service for detecting and managing protontricks installation
    Handles detection, validation, and installation guidance for both CLI and GUI
    """
    
    def __init__(self, steamdeck: bool = False):
        """
        Initialize the protontricks detection service
        
        Args:
            steamdeck (bool): Whether running on Steam Deck
        """
        self.steamdeck = steamdeck
        self.config_handler = ConfigHandler()
        self._protontricks_handler = None
        self._last_detection_result = None
        self._cached_detection_valid = False
        logger.debug(f"ProtontricksDetectionService initialized (steamdeck={steamdeck})")
    
    def _get_protontricks_handler(self) -> ProtontricksHandler:
        """Get or create ProtontricksHandler instance"""
        if self._protontricks_handler is None:
            self._protontricks_handler = ProtontricksHandler(self.steamdeck)
        return self._protontricks_handler
    
    def detect_protontricks(self, use_cache: bool = True) -> Tuple[bool, str, str]:
        """
        Detect if system protontricks is installed and get installation details

        Args:
            use_cache (bool): Whether to use cached detection result

        Returns:
            Tuple[bool, str, str]: (is_installed, installation_type, details_message)
            - is_installed: True if protontricks is available
            - installation_type: 'native', 'flatpak', or 'none'
            - details_message: Human-readable status message
        """
        if use_cache and self._cached_detection_valid and self._last_detection_result:
            logger.debug("Using cached protontricks detection result")
            return self._last_detection_result
        
        logger.info("Detecting protontricks installation...")
        
        handler = self._get_protontricks_handler()
        
        # Reset handler state for fresh detection
        handler.which_protontricks = None
        handler.protontricks_path = None
        handler.protontricks_version = None
        
        # Perform detection without user prompts
        is_installed = self._detect_without_prompts(handler)
        
        # Determine installation type and create message
        if is_installed:
            installation_type = handler.which_protontricks or 'unknown'
            if installation_type == 'native':
                details_message = f"Native protontricks found at {handler.protontricks_path}"
            elif installation_type == 'flatpak':
                details_message = "Flatpak protontricks is installed"
            else:
                details_message = "Protontricks is installed (unknown type)"
        else:
            installation_type = 'none'
            details_message = "Protontricks not found - install via flatpak or package manager"
        
        # Cache the result
        self._last_detection_result = (is_installed, installation_type, details_message)
        self._cached_detection_valid = True
        
        logger.info(f"Protontricks detection complete: {details_message}")
        return self._last_detection_result
    
    def _detect_without_prompts(self, handler: ProtontricksHandler) -> bool:
        """
        Detect system protontricks (flatpak or native) without user prompts.

        Args:
            handler (ProtontricksHandler): Handler instance to use

        Returns:
            bool: True if system protontricks is found
        """
        # Use the handler's silent detection method
        return handler.detect_protontricks()

    def is_bundled_mode(self) -> bool:
        """
        DEPRECATED: Bundled protontricks no longer supported.
        Always returns False for backwards compatibility.
        """
        return False
    
    def install_flatpak_protontricks(self) -> Tuple[bool, str]:
        """
        Install protontricks via Flatpak
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info("Attempting to install Flatpak Protontricks...")
        
        try:
            handler = self._get_protontricks_handler()
            
            # Check if flatpak is available
            if not shutil.which("flatpak"):
                error_msg = "Flatpak not found. Please install Flatpak first."
                logger.error(error_msg)
                return False, error_msg
            
            # Install command - use --user flag for user-level installation (works on Steam Deck)
            # Avoids system-wide installation permissions
            install_cmd = ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "com.github.Matoking.protontricks"]
            
            # Use clean environment
            env = handler._get_clean_subprocess_env()
            
            # Log the command for debugging
            logger.debug(f"Running flatpak install command: {' '.join(install_cmd)}")
            
            # Run installation with timeout (5 minutes should be plenty)
            process = subprocess.run(
                install_cmd, 
                check=True, 
                text=True, 
                env=env, 
                capture_output=True,
                timeout=300  # 5 minute timeout
            )
            
            # Log stdout/stderr for debugging (even on success, might contain useful info)
            if process.stdout:
                logger.debug(f"Flatpak install stdout: {process.stdout}")
            if process.stderr:
                logger.debug(f"Flatpak install stderr: {process.stderr}")
            
            # Clear cache to force re-detection
            self._cached_detection_valid = False
            
            success_msg = "Flatpak Protontricks installed successfully."
            logger.info(success_msg)
            return True, success_msg
            
        except FileNotFoundError:
            error_msg = "Flatpak command not found. Please install Flatpak first."
            logger.error(error_msg)
            return False, error_msg
        except subprocess.TimeoutExpired:
            error_msg = "Flatpak installation timed out after 5 minutes. Please check your network connection and try again."
            logger.error(error_msg)
            return False, error_msg
        except subprocess.CalledProcessError as e:
            # Include stderr in error message for better debugging
            stderr_msg = e.stderr.strip() if e.stderr else "No error details available"
            stdout_msg = e.stdout.strip() if e.stdout else ""
            
            # Try to extract meaningful error from stderr
            if stderr_msg:
                # Common errors: permission denied, network issues, etc.
                if "permission" in stderr_msg.lower() or "denied" in stderr_msg.lower():
                    error_msg = f"Permission denied. Try running: flatpak install --user flathub com.github.Matoking.protontricks\n\nDetails: {stderr_msg}"
                elif "network" in stderr_msg.lower() or "connection" in stderr_msg.lower():
                    error_msg = f"Network error during installation. Check your internet connection.\n\nDetails: {stderr_msg}"
                elif "already installed" in stderr_msg.lower():
                    # Might be success -- clear cache and re-detect
                    logger.info("Protontricks appears to already be installed (according to flatpak output)")
                    self._cached_detection_valid = False
                    return True, "Protontricks is already installed."
                else:
                    error_msg = f"Flatpak installation failed:\n\n{stderr_msg}"
                    if stdout_msg:
                        error_msg += f"\n\nOutput: {stdout_msg}"
            else:
                error_msg = f"Flatpak installation failed with return code {e.returncode}."
                if stdout_msg:
                    error_msg += f"\n\nOutput: {stdout_msg}"
            
            logger.error(f"Flatpak installation error: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error during Flatpak installation: {e}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def get_installation_guidance(self) -> str:
        """
        Get guidance message for installing protontricks natively
        
        Returns:
            str: Installation guidance message
        """
        return """To install protontricks natively, use your distribution's package manager:

• Arch Linux: sudo pacman -S protontricks
• Ubuntu/Debian: sudo apt install protontricks
• Fedora: sudo dnf install protontricks
• OpenSUSE: sudo zypper install protontricks
• Gentoo: sudo emerge protontricks

Alternatively, you can install via Flatpak:
flatpak install flathub com.github.Matoking.protontricks

After installation, click "Re-detect" to continue."""
    
    def clear_cache(self):
        """Clear cached detection results to force re-detection"""
        self._cached_detection_valid = False
        self._last_detection_result = None
        logger.debug("Protontricks detection cache cleared")