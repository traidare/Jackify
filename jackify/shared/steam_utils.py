"""
Steam Utilities Module

Centralized Steam installation type detection to avoid redundant subprocess calls.
"""

import logging
import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

NATIVE_STEAM_ROOTS = [
    Path.home() / ".steam" / "steam",
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "root",
]

FLATPAK_STEAM_ROOTS = [
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "home" / ".local" / "share" / "Steam",
]

STEAM_PREFERENCE_AUTO = "auto"
STEAM_PREFERENCE_NATIVE = "native"
STEAM_PREFERENCE_FLATPAK = "flatpak"

# Common Jackify-supported game AppIDs used to infer which Steam install is actually in use.
_STEAM_USAGE_APPIDS = {
    "489830",   # Skyrim Special Edition
    "377160",   # Fallout 4
    "22380",    # Fallout New Vegas
    "22330",    # Oblivion
    "22370",    # Fallout 3
    "1716740",  # Starfield
}


def detect_steam_installation_types() -> Tuple[bool, bool]:
    """
    Detect Steam installation types at startup.

    Performs detection ONCE and returns results to be cached in SystemInfo.

    Returns:
        Tuple[bool, bool]: (is_flatpak_steam, is_native_steam)
    """
    raw_flatpak = _detect_flatpak_steam()
    raw_native = _detect_native_steam()

    is_flatpak = raw_flatpak
    is_native = raw_native
    preferred_type, preferred_root = resolve_preferred_steam_installation()

    # Deterministic dual-install behavior: expose one active Steam type.
    if raw_flatpak and raw_native:
        if preferred_type == STEAM_PREFERENCE_FLATPAK:
            is_flatpak, is_native = True, False
        else:
            is_flatpak, is_native = False, True

    logger.info(
        "Steam installation detection: Flatpak=%s, Native=%s, Preferred=%s (%s), RawFlatpak=%s, RawNative=%s",
        is_flatpak,
        is_native,
        preferred_type or "none",
        preferred_root or "n/a",
        raw_flatpak,
        raw_native,
    )

    return is_flatpak, is_native


def get_steam_install_roots(install_type: Optional[str] = None) -> List[Path]:
    """Return known Steam roots for a specific install type or both."""
    if install_type == STEAM_PREFERENCE_FLATPAK:
        return list(FLATPAK_STEAM_ROOTS)
    if install_type == STEAM_PREFERENCE_NATIVE:
        return list(NATIVE_STEAM_ROOTS)
    return list(NATIVE_STEAM_ROOTS) + list(FLATPAK_STEAM_ROOTS)


def is_flatpak_steam_root(path: Path) -> bool:
    """Return True if a Steam root path belongs to Flatpak Steam."""
    path_str = str(path)
    return ".var/app/com.valvesoftware.Steam" in path_str


def get_available_steam_roots() -> Dict[str, List[Path]]:
    """Return discovered Steam roots grouped by install type."""
    roots = {
        STEAM_PREFERENCE_NATIVE: [],
        STEAM_PREFERENCE_FLATPAK: [],
    }
    for root in NATIVE_STEAM_ROOTS:
        if root.exists():
            roots[STEAM_PREFERENCE_NATIVE].append(root)
    for root in FLATPAK_STEAM_ROOTS:
        if root.exists():
            roots[STEAM_PREFERENCE_FLATPAK].append(root)
    return roots


def get_ordered_steam_roots(preference: str = STEAM_PREFERENCE_AUTO) -> List[Path]:
    """
    Return Steam roots in deterministic priority order.

    If both native and flatpak are installed, preference controls order.
    AUTO uses the most recently active install (loginusers.vdf timestamp/mtime).
    """
    available = get_available_steam_roots()
    native_roots = available[STEAM_PREFERENCE_NATIVE]
    flatpak_roots = available[STEAM_PREFERENCE_FLATPAK]

    if preference not in {
        STEAM_PREFERENCE_AUTO,
        STEAM_PREFERENCE_NATIVE,
        STEAM_PREFERENCE_FLATPAK,
    }:
        preference = STEAM_PREFERENCE_AUTO

    if preference == STEAM_PREFERENCE_NATIVE:
        return native_roots + flatpak_roots
    if preference == STEAM_PREFERENCE_FLATPAK:
        return flatpak_roots + native_roots

    preferred_type, _ = resolve_preferred_steam_installation(STEAM_PREFERENCE_AUTO)
    if preferred_type == STEAM_PREFERENCE_FLATPAK:
        return flatpak_roots + native_roots
    return native_roots + flatpak_roots


def resolve_preferred_steam_installation(
    preference: str = STEAM_PREFERENCE_AUTO,
) -> Tuple[Optional[str], Optional[Path]]:
    """
    Resolve the preferred Steam install type/root deterministically.

    Priority:
    1) Explicit preference (`native` or `flatpak`) if installed
    2) AUTO mode: whichever install has more relevant installed-game manifests
    3) AUTO tie-break: newest loginusers activity marker
    4) Deterministic fallback: native first, then flatpak
    """
    available = get_available_steam_roots()
    native_roots = available[STEAM_PREFERENCE_NATIVE]
    flatpak_roots = available[STEAM_PREFERENCE_FLATPAK]

    if preference == STEAM_PREFERENCE_NATIVE and native_roots:
        return STEAM_PREFERENCE_NATIVE, native_roots[0]
    if preference == STEAM_PREFERENCE_FLATPAK and flatpak_roots:
        return STEAM_PREFERENCE_FLATPAK, flatpak_roots[0]

    if native_roots and flatpak_roots:
        native_game_score = _steam_root_game_presence_score(native_roots[0])
        flatpak_game_score = _steam_root_game_presence_score(flatpak_roots[0])
        if flatpak_game_score > native_game_score:
            return STEAM_PREFERENCE_FLATPAK, flatpak_roots[0]
        if native_game_score > flatpak_game_score:
            return STEAM_PREFERENCE_NATIVE, native_roots[0]

        native_score = _steam_root_activity_score(native_roots[0])
        flatpak_score = _steam_root_activity_score(flatpak_roots[0])
        if flatpak_score > native_score:
            return STEAM_PREFERENCE_FLATPAK, flatpak_roots[0]
        return STEAM_PREFERENCE_NATIVE, native_roots[0]

    if native_roots:
        return STEAM_PREFERENCE_NATIVE, native_roots[0]
    if flatpak_roots:
        return STEAM_PREFERENCE_FLATPAK, flatpak_roots[0]
    return None, None


def _steam_root_activity_score(steam_root: Path) -> float:
    """
    Return a comparable activity score for Steam root.
    Uses loginusers.vdf mtime as a robust cross-layout signal.
    """
    try:
        loginusers = steam_root / "config" / "loginusers.vdf"
        if loginusers.exists():
            return os.path.getmtime(loginusers)
    except Exception as exc:
        logger.debug("Could not read Steam activity marker for %s: %s", steam_root, exc)
    return 0.0


def _steam_root_game_presence_score(steam_root: Path) -> int:
    """
    Score a Steam root by presence of relevant installed game appmanifests.
    Higher score means that Steam install is more likely the one user is actively using.
    """
    score = 0
    for library_root in _get_library_roots_for_steam_root(steam_root):
        steamapps = library_root / "steamapps"
        if not steamapps.is_dir():
            continue
        for app_id in _STEAM_USAGE_APPIDS:
            manifest = steamapps / f"appmanifest_{app_id}.acf"
            if manifest.is_file():
                score += 1
    return score


def _get_library_roots_for_steam_root(steam_root: Path) -> List[Path]:
    """
    Return Steam library roots for a given Steam root using libraryfolders.vdf.
    Includes the primary Steam root as a fallback.
    """
    roots: List[Path] = [steam_root]
    vdf_path = steam_root / "config" / "libraryfolders.vdf"
    if not vdf_path.is_file():
        return roots

    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r'"path"\s*"([^"]+)"', text):
            raw_path = match.group(1).replace("\\\\", "\\")
            lib_root = Path(raw_path).expanduser()
            if lib_root not in roots:
                roots.append(lib_root)
    except Exception as exc:
        logger.debug("Failed reading %s: %s", vdf_path, exc)
    return roots


def _detect_flatpak_steam() -> bool:
    """Detect if Steam is installed as a Flatpak."""
    try:
        # First check if flatpak command exists
        if not shutil.which('flatpak'):
            return False

        # Verify the app is actually installed (not just directory exists)
        result = subprocess.run(
            ['flatpak', 'list', '--app'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress stderr
            text=True,
            timeout=5
        )

        if result.returncode == 0 and 'com.valvesoftware.Steam' in result.stdout:
            logger.debug("Flatpak Steam detected")
            return True

    except Exception as e:
        logger.debug(f"Error detecting Flatpak Steam: {e}")

    return False


def _detect_native_steam() -> bool:
    """Detect if native Steam installation exists."""
    try:
        for path in NATIVE_STEAM_ROOTS:
            if path.exists():
                logger.debug(f"Native Steam detected at: {path}")
                return True

    except Exception as e:
        logger.debug(f"Error detecting native Steam: {e}")

    return False
