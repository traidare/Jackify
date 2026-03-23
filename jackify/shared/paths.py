"""
Path utilities for Jackify.

This module provides standardized path resolution for Jackify directories,
supporting configurable data directory while keeping config in a fixed location.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def get_jackify_data_dir() -> Path:
    """
    Get the configurable Jackify data directory.
    
    This directory contains:
    - downloaded_mod_lists/
    - logs/ 
    - temporary proton prefixes during installation
    
    Returns:
        Path: The Jackify data directory (always set in config)
    """
    try:
        # Import here to avoid circular imports
        from jackify.backend.handlers.config_handler import ConfigHandler
        
        config_handler = ConfigHandler()
        jackify_data_dir = config_handler.get('jackify_data_dir')
        
        # Config handler now always ensures this is set, but fallback just in case
        if jackify_data_dir:
            return Path(jackify_data_dir).expanduser()
        else:
            return Path.home() / "Jackify"
            
    except Exception:
        # Emergency fallback if config system fails
        return Path.home() / "Jackify"


def get_jackify_logs_dir() -> Path:
    """Get the logs directory within the Jackify data directory."""
    return get_jackify_data_dir() / "logs"


def get_jackify_downloads_dir() -> Path:
    """Get the downloaded modlists directory within the Jackify data directory."""
    return get_jackify_data_dir() / "downloaded_mod_lists"


def get_jackify_config_dir() -> Path:
    """
    Get the Jackify configuration directory (always ~/.config/jackify).
    
    This directory contains:
    - config.json (settings)
    - API keys and credentials
    - Resource settings
    
    Returns:
        Path: Always ~/.config/jackify
    """
    return Path.home() / ".config" / "jackify"


def cleanup_stale_tmp() -> None:
    """Remove stale engine temp directories from the Jackify tmp dir.

    The engine writes TTW working files (xd3 patches, patch manifests) into
    UUID-named subdirectories under <data_dir>/.tmp/ during TTW installation.
    These are never cleaned up on failure or interruption and can accumulate
    several GB per run. Any such directory present at startup is always stale —
    no TTW install can be in flight before the application has started.

    Only removes directories matching known engine temp prefixes. The
    jackify-proton-extraction prefix is intentionally reused by the engine
    across runs and is left in place.
    """
    tmp_dir = get_jackify_data_dir() / ".tmp"
    if not tmp_dir.is_dir():
        return

    stale_prefixes = ("ttw_mpi_", "ttw_ogg_")
    removed = 0
    freed = 0

    for entry in tmp_dir.iterdir():
        if not any(entry.name.startswith(p) for p in stale_prefixes):
            continue
        try:
            if entry.is_dir():
                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry)
            else:
                size = entry.stat().st_size
                entry.unlink()
            freed += size
            removed += 1
            logger.debug(f"Removed stale engine tmp: {entry.name}")
        except Exception as e:
            logger.warning(f"Could not remove stale engine tmp {entry.name}: {e}")

    if removed:
        freed_mb = freed / (1024 * 1024)
        logger.info(f"Cleaned {removed} stale engine tmp entries ({freed_mb:.0f} MB freed)")