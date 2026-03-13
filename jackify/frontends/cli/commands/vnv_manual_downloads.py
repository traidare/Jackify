"""CLI helpers for VNV manual-download handling."""

from pathlib import Path
from typing import Callable, Optional

from jackify.backend.services.nexus_premium_service import NexusPremiumService
from jackify.backend.services.vnv_post_install_service import VNVPostInstallService
from jackify.frontends.cli.commands.manual_download_flow import run_cli_manual_download_phase
from jackify.frontends.cli.ui.indeterminate_status import CliIndeterminateStatus


def _is_explicitly_non_premium(service: VNVPostInstallService) -> bool:
    auth_token = service.auth_service.get_auth_token()
    auth_method = service.auth_service.get_auth_method()
    if not auth_token or not auth_method:
        return False
    is_premium, username = NexusPremiumService().check_premium_status(
        auth_token,
        is_oauth=auth_method == "oauth",
    )
    return username is not None and not is_premium


def _missing_manual_items(service: VNVPostInstallService) -> list[dict]:
    completed = service.check_already_completed()
    include_bsa = not completed["bsa_decompressed"] and not (
        service._find_cached_bsa_mpi() or service._find_cached_bsa_package()
    )
    include_4gb = not completed["4gb_patch"] and not service._find_cached_4gb_patcher()
    if not include_4gb and not include_bsa:
        return []
    items = service.get_manual_download_items(include_bsa=include_bsa)
    if include_4gb:
        return items
    return [item for item in items if int(item.get("mod_id", 0)) != service.LINUX_4GB_PATCHER_MOD_ID]


def ensure_vnv_cli_manual_downloads(
    service: VNVPostInstallService,
    output_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    if not _is_explicitly_non_premium(service):
        return True
    items = _missing_manual_items(service)
    if not items:
        return True
    output = output_callback or print
    output("")
    output("VNV requires manual Nexus downloads for this account. Opening Jackify CLI Download Manager...")
    return run_cli_manual_download_phase(
        events=items,
        loop_iteration=1,
        download_dir=service.cache_dir,
        stdin_write=lambda _payload: True,
        output_callback=output,
        concurrent_limit=2,
    )


def build_vnv_cli_manual_file_callback(
    service: VNVPostInstallService,
    output_callback: Optional[Callable[[str], None]] = None,
):
    output = output_callback or print
    manual_items = service.get_manual_download_items(include_bsa=True)

    def _cached_file_for_title(title: str) -> Optional[Path]:
        if "4GB" in title:
            return service._find_cached_4gb_patcher()
        return service._find_cached_bsa_mpi() or service._find_cached_bsa_package()

    def _manual_file_callback(title: str, instructions: str) -> Optional[Path]:
        cached = _cached_file_for_title(title)
        if cached:
            return cached
        mod_id = (
            service.LINUX_4GB_PATCHER_MOD_ID
            if "4GB" in title
            else service.FNV_BSA_DECOMPRESSOR_MOD_ID
        )
        item = next((entry for entry in manual_items if int(entry.get("mod_id", 0)) == mod_id), None)
        if not item:
            output("")
            output(instructions)
            return None
        output("")
        output(f"{title} - opening Jackify CLI Download Manager...")
        success = run_cli_manual_download_phase(
            events=[item],
            loop_iteration=1,
            download_dir=service.cache_dir,
            stdin_write=lambda _payload: True,
            output_callback=output,
            concurrent_limit=1,
        )
        if not success:
            return None
        return _cached_file_for_title(title)

    return _manual_file_callback


def create_vnv_cli_progress_callback(
    output_callback: Optional[Callable[[str], None]] = None,
) -> tuple[Callable[[str], None], Callable[[], None]]:
    """Create a CLI progress callback with a pulser for indeterminate VNV stages."""
    output = output_callback or print
    pulser = CliIndeterminateStatus()

    def _should_pulse(message: str) -> bool:
        lowered = message.lower()
        if "%" in lowered:
            return False
        if "assets processed:" in lowered:
            return False
        if "decompressing bsa files:" in lowered:
            return False
        pulse_markers = (
            "running vnv post-install automation",
            "running bsa decompressor",
            "running 4gb patcher",
            "preparing bsa decompressor package",
            "extracting bsa package",
            "ensuring ttw_linux_installer is available",
            "checking for post-install automation",
            "finalizing post-install configuration",
        )
        return any(marker in lowered for marker in pulse_markers)

    def _progress(message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if _should_pulse(text):
            pulser.set(text)
            return
        pulser.stop()
        output(text)

    return _progress, pulser.close
