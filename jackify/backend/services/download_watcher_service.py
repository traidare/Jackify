"""
Watches a directory for newly downloaded files and matches them against a
list of pending manual download items by lax filename comparison.
"""

import os
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread, Event
from typing import Callable, Optional

logger = logging.getLogger(__name__)

@dataclass
class WatcherConfig:
    watch_directory: Path
    watch_recursive: bool = False
    debounce_seconds: float = 2.0
    additional_dirs: list = field(default_factory=list)


class DownloadWatcherService:
    """
    Monitors a directory for files that match pending download items.

    Caller sets pending_items (list of dicts with at least 'file_name') and
    registers an on_candidate callback that receives (Path, dict) when a
    potential match is detected (after debounce, before hash validation).
    """

    def __init__(self, config: WatcherConfig, on_candidate: Callable[[Path, dict], None]):
        self._config = config
        self._on_candidate = on_candidate
        self._pending_items: list[dict] = []
        self._pending_exact: list[tuple[str, dict]] = []
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        # Track known files so we only react to new/changed ones
        self._known: dict[Path, float] = {}

    def set_pending_items(self, items: list[dict]) -> None:
        """Replace the pending items list. Thread-safe for simple list swap."""
        self._pending_items = list(items)
        self._pending_exact = [
            (str(item.get('file_name', '')).lower(), item)
            for item in self._pending_items
            if item.get('file_name')
        ]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._watch_loop, daemon=True, name='DownloadWatcher')
        self._thread.start()
        logger.debug(f"Download watcher started on: {self._config.watch_directory}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("Download watcher stopped")

    def _all_watch_dirs(self) -> list[Path]:
        dirs = [self._config.watch_directory]
        dirs.extend(self._config.additional_dirs)
        return [d for d in dirs if d.is_dir()]

    def _scan(self) -> None:
        for watch_dir in self._all_watch_dirs():
            try:
                entries = list(watch_dir.iterdir()) if not self._config.watch_recursive else \
                    [p for p in watch_dir.rglob('*') if p.is_file()]
                for path in entries:
                    if not path.is_file():
                        continue
                    # Skip browser temp files
                    if path.suffix in ('.part', '.crdownload', '.tmp'):
                        continue
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    prev_mtime = self._known.get(path)
                    if prev_mtime == mtime:
                        continue
                    self._known[path] = mtime
                    self._check_candidate(path)
            except OSError as e:
                logger.debug(f"Watcher scan error on {watch_dir}: {e}")

    def _check_candidate(self, path: Path) -> None:
        candidate_name = path.name.lower()
        # Exact filename match (case-insensitive).
        for expected_name, item in self._pending_exact:
            if expected_name == candidate_name:
                logger.debug(f"Candidate exact match: {path.name}")
                self._debounce_and_emit(path, item)
                return
        # Some modlist metadata stores filenames with a leading dot that browsers
        # strip when saving the download. Match against the stripped expected name.
        for expected_name, item in self._pending_exact:
            if expected_name.lstrip('.') == candidate_name:
                logger.debug(f"Candidate dot-normalized match: {path.name} -> {expected_name}")
                self._debounce_and_emit(path, item)
                return

    def _debounce_and_emit(self, path: Path, item: dict) -> None:
        def _wait_and_emit():
            prev_size = -1
            stable_count = 0
            needed = max(1, int(self._config.debounce_seconds / 0.5))
            for _ in range(needed * 4):  # max ~2× debounce time
                if self._stop_event.is_set():
                    return
                time.sleep(0.5)
                try:
                    size = path.stat().st_size
                except OSError:
                    return
                if size == prev_size:
                    stable_count += 1
                    if stable_count >= needed:
                        break
                else:
                    stable_count = 0
                prev_size = size
            if path.exists():
                self._on_candidate(path, item)

        Thread(target=_wait_and_emit, daemon=True, name=f'Debounce-{path.name[:20]}').start()

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._scan()
            self._stop_event.wait(timeout=1.0)
