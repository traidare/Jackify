"""Metrics and synthetic entry methods for ProgressStateManager (Mixin)."""

import logging
import re
import time
from typing import TYPE_CHECKING

from jackify.shared.progress_models import FileProgress, OperationType, InstallationPhase

if TYPE_CHECKING:
    from jackify.backend.handlers.progress_parser import ParsedLine

logger = logging.getLogger(__name__)


class ProgressStateMetricsMixin:
    """Mixin providing metrics augmentation methods."""

    def _augment_file_metrics(self, file_progress: FileProgress) -> None:
        """Populate size/speed info to improve UI accuracy."""
        now = time.time()
        history = self._file_history.get(file_progress.filename)

        total_size = file_progress.total_size or (history.get('total') if history else None)
        if total_size and file_progress.percent and not file_progress.current_size:
            file_progress.current_size = int((file_progress.percent / 100.0) * total_size)
        elif file_progress.current_size and not total_size and file_progress.total_size:
            total_size = file_progress.total_size

        if total_size and not file_progress.total_size:
            file_progress.total_size = total_size

        current_size = file_progress.current_size or 0

        computed_speed = 0.0
        if file_progress.speed < 0:
            computed_speed = 0.0
            if history and current_size:
                prev_bytes = history.get('bytes', 0)
                prev_time = history.get('time', now)
                delta_bytes = current_size - prev_bytes
                delta_time = now - prev_time

                if delta_bytes >= 0 and delta_time >= 1.0:
                    computed_speed = delta_bytes / delta_time
                elif history.get('computed_speed'):
                    computed_speed = history.get('computed_speed', 0.0)

            file_progress.speed = computed_speed
        else:
            computed_speed = file_progress.speed

        if current_size or total_size:
            self._file_history[file_progress.filename] = {
                'bytes': current_size,
                'time': now,
                'total': total_size or (history.get('total') if history else None),
                'computed_speed': computed_speed,
            }
        elif history:
            self._file_history[file_progress.filename] = history

    def _maybe_add_wabbajack_progress(self, parsed: "ParsedLine") -> bool:
        """Create a synthetic file entry for .wabbajack archive download."""
        if not parsed.data_info:
            return False
        if not parsed.data_info:
            return False

        current_bytes, total_bytes = parsed.data_info
        if total_bytes <= 0:
            return False

        for fp in self.state.active_files:
            if fp.filename.lower().endswith('.wabbajack'):
                synthetic_entry = fp
                if getattr(fp, self._synthetic_flag, False):
                    percent = (current_bytes / total_bytes) * 100.0
                    synthetic_entry.percent = percent
                    synthetic_entry.current_size = current_bytes
                    synthetic_entry.total_size = total_bytes
                    synthetic_entry.last_update = time.time()
                    self._augment_file_metrics(synthetic_entry)
                    return True
                else:
                    return False

        synthetic_entry = None
        for fp in self.state.active_files:
            if getattr(fp, self._synthetic_flag, False):
                synthetic_entry = fp
                break

        message = (parsed.message or "")
        phase_name = (parsed.phase_name or "").lower()
        should_force = 'wabbajack' in message.lower() or 'wabbajack' in phase_name

        if not synthetic_entry:
            if self._has_real_download_activity() and not should_force:
                return False
            if self.state.phase not in (InstallationPhase.INITIALIZATION, InstallationPhase.DOWNLOAD) and not should_force:
                return False

        percent = (current_bytes / total_bytes) * 100.0
        if not self._wabbajack_entry_name:
            filename_match = re.search(r'([A-Za-z0-9_\-\.]+\.wabbajack)', message, re.IGNORECASE)
            if filename_match:
                self._wabbajack_entry_name = filename_match.group(1)
        if not self._wabbajack_entry_name:
            self._wabbajack_entry_name = "Downloading .wabbajack file"
        entry_name = self._wabbajack_entry_name

        if synthetic_entry:
            synthetic_entry.percent = percent
            synthetic_entry.current_size = current_bytes
            synthetic_entry.total_size = total_bytes
            synthetic_entry.last_update = time.time()
            self._augment_file_metrics(synthetic_entry)
        else:
            special_file = FileProgress(
                filename=entry_name,
                operation=OperationType.DOWNLOAD,
                percent=percent,
                current_size=current_bytes,
                total_size=total_bytes
            )
            special_file.last_update = time.time()
            setattr(special_file, self._synthetic_flag, True)
            self._augment_file_metrics(special_file)
            self.state.add_file(special_file)
        return True

    def _has_real_download_activity(self) -> bool:
        """Check if there are real download entries already visible."""
        for fp in self.state.active_files:
            if getattr(fp, self._synthetic_flag, False):
                continue
            if fp.operation == OperationType.DOWNLOAD:
                return True
        return False

    def _remove_synthetic_wabbajack(self) -> None:
        """Remove any synthetic .wabbajack entries once real files appear."""
        remaining = []
        removed = False
        for fp in self.state.active_files:
            if getattr(fp, self._synthetic_flag, False):
                removed = True
                self._file_history.pop(fp.filename, None)
                continue
            remaining.append(fp)
        if removed:
            self.state.active_files = remaining

    def _remove_all_wabbajack_entries(self) -> None:
        """Remove ALL .wabbajack entries when archive download phase starts."""
        remaining = []
        removed = False
        for fp in self.state.active_files:
            if fp.filename.lower().endswith('.wabbajack') or 'wabbajack' in fp.filename.lower():
                removed = True
                self._file_history.pop(fp.filename, None)
                continue
            remaining.append(fp)
        if removed:
            self.state.active_files = remaining
            self._wabbajack_entry_name = None
