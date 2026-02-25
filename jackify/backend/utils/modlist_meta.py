import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JACKIFY_META_FILE = "jackify_meta.json"

_BYTEARRAY_RE = re.compile(r"@ByteArray\((.+)\)", re.DOTALL)


def write_modlist_meta(
    install_dir: str,
    modlist_name: str,
    game_type: Optional[str],
    install_mode: str = "online",
    modlist_version: Optional[str] = None,
) -> bool:
    """Write jackify_meta.json into install_dir. Returns True on success."""
    from jackify import __version__ as jackify_version
    import datetime

    try:
        meta = {
            "modlist_name": modlist_name,
            "game_type": game_type or "",
            "install_mode": install_mode,
            "install_date": datetime.datetime.now().isoformat(timespec="seconds"),
            "jackify_version": jackify_version,
        }
        if modlist_version:
            meta["modlist_version"] = modlist_version

        out = Path(install_dir) / JACKIFY_META_FILE
        out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        logger.debug(f"Wrote modlist meta to {out}")
        return True
    except Exception as e:
        logger.debug(f"Failed to write modlist meta: {e}")
        return False


def read_modlist_meta(install_dir: str) -> Optional[dict]:
    """Read jackify_meta.json from install_dir. Returns dict or None."""
    try:
        meta_path = Path(install_dir) / JACKIFY_META_FILE
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Failed to read modlist meta from {install_dir}: {e}")
        return None


def _read_selected_profile(install_dir: str) -> Optional[str]:
    """Read selected_profile from ModOrganizer.ini, stripping @ByteArray() wrapper."""
    try:
        mo2_ini = Path(install_dir) / "ModOrganizer.ini"
        if not mo2_ini.exists():
            return None
        for line in mo2_ini.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith("selected_profile"):
                continue
            _, _, value = line.partition("=")
            value = value.strip()
            m = _BYTEARRAY_RE.match(value)
            if m:
                return m.group(1).strip()
            return value or None
    except Exception as e:
        logger.debug(f"Failed to read selected_profile from {install_dir}: {e}")
    return None


def get_modlist_name(install_dir: str) -> Optional[str]:
    """Return the best available modlist name for install_dir.

    Priority:
    1. jackify_meta.json (written by Jackify at install time)
    2. selected_profile from ModOrganizer.ini (set by modlist author)
    """
    meta = read_modlist_meta(install_dir)
    if meta and meta.get("modlist_name"):
        return meta["modlist_name"]
    return _read_selected_profile(install_dir)
