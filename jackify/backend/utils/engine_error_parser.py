import json
from typing import Optional
from jackify.shared.errors import (
    JackifyError, InstallError, OAuthError,
    oauth_expired, wabbajack_install_failed, format_technical_context,
)


def _ctx_detail(ctx: dict) -> Optional[str]:
    if not ctx:
        return None
    return format_technical_context(context=ctx)


_TYPE_MAP = {
    "auth_failed": lambda msg, ctx: oauth_expired(),
    "premium_required": lambda msg, ctx: InstallError(
        "Nexus Premium Required",
        msg,
        suggestion="Jackify requires a Nexus Premium account for automated installs.",
        solutions=[
            "Log in to Nexus Mods with a Premium account.",
            "Non-premium support is planned for a future release.",
        ],
    ),
    "network_error": lambda msg, ctx: InstallError(
        "Network or Download Failure",
        msg,
        suggestion="Check your internet connection and retry.",
        solutions=[
            "Verify your internet connection.",
            "Re-run the install — Wabbajack resumes from where it stopped.",
            "Check if Nexus Mods is reachable at nexusmods.com.",
            "Disable VPN or proxy if active.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "disk_full": lambda msg, ctx: InstallError(
        "Disk Full",
        msg,
        suggestion="Free space on the target drive and retry.",
        solutions=[
            "Run: df -h to see available space.",
            "Delete old modlist downloads or backups.",
            "Move the install to a larger drive.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "permission_denied": lambda msg, ctx: InstallError(
        "Permission Denied",
        msg,
        suggestion="Check write permissions on the target path.",
        solutions=[
            "Ensure Jackify and Steam are run as the same user.",
            "Avoid install paths under /usr, /var, or /opt.",
            f"Check permissions: ls -la {ctx.get('path', '<path>')}",
        ],
        technical=_ctx_detail(ctx),
    ),
    "archive_corrupt": lambda msg, ctx: InstallError(
        "Corrupted Archive",
        msg,
        suggestion="Re-run the install — Wabbajack will re-download and re-verify the file.",
        solutions=[
            "Re-run the install.",
            "Check available disk space (partial downloads appear corrupt).",
            "Check Modlist_Install_workflow.log for the specific filename.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "file_not_found": lambda msg, ctx: InstallError(
        "File Not Found",
        msg,
        suggestion="Check the modlist URL and your game installation paths.",
        solutions=[
            "Verify the modlist name is correct.",
            "Ensure the target game is installed.",
            "Re-run — the modlist index may have been temporarily unavailable.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "validation_failed": lambda msg, ctx: InstallError(
        "Validation Failed",
        msg,
        suggestion="Re-run the install to re-download any failed files.",
        solutions=[
            "Re-run the install — Wabbajack resumes and re-validates.",
            "Check available disk space.",
            "Check Modlist_Install_workflow.log for specific failures.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "download_stalled": lambda msg, ctx: InstallError(
        "Downloads Stalled",
        msg,
        suggestion="Check your connection and OAuth status, then retry.",
        solutions=[
            "Check your internet connection.",
            "In Settings, confirm Nexus OAuth is active.",
            "Re-run the install.",
        ],
    ),
}

_EXIT_CODE_MAP = {
    2: lambda d, c: _TYPE_MAP["auth_failed"](d, c or {}),
    3: lambda d, c: _TYPE_MAP["network_error"](d, c or {}),
    4: lambda d, c: _TYPE_MAP["disk_full"](d, c or {}),
    5: lambda d, c: _TYPE_MAP["validation_failed"](d, c or {}),
    6: lambda d, c: wabbajack_install_failed(format_technical_context(detail=d, context=c) or d),
}


def parse_engine_error_line(line: str) -> Optional[JackifyError]:
    """Parse one stderr line. Returns JackifyError or None."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if obj.get("je") != "1":
        return None
    if obj.get("level") == "warning":
        return None
    error_type = obj.get("type", "engine_error")
    message = obj.get("message", "An unknown engine error occurred.")
    context = obj.get("context") or {}
    factory = _TYPE_MAP.get(error_type)
    if factory:
        return factory(message, context)
    return wabbajack_install_failed(f"[{error_type}] {message}")


def error_from_exit_code(exit_code: int, detail: str = "", context: Optional[dict] = None) -> Optional[JackifyError]:
    """Return a JackifyError based on exit code alone (fallback when no stderr line received)."""
    factory = _EXIT_CODE_MAP.get(exit_code)
    if factory:
        detail_message = detail or f"Engine exited with code {exit_code}."
        return factory(detail_message, context or {})
    return None
