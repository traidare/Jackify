"""Image loading and caching manager for ModlistGalleryDialog."""

from collections import deque
from functools import partial
import logging
from typing import Dict, Optional

import shiboken6
from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from jackify.backend.models.modlist_metadata import ModlistMetadata
from jackify.backend.services.modlist_gallery_service import ModlistGalleryService


logger = logging.getLogger(__name__)


class ImageManager(QObject):
    """Centralized image loading and caching manager"""

    def __init__(self, gallery_service: ModlistGalleryService, parent=None):
        super().__init__(parent)
        self.gallery_service = gallery_service
        self.pixmap_cache: Dict[str, QPixmap] = {}
        self.network_manager = QNetworkAccessManager(self)
        self.download_queue = deque()
        self.downloading: set[str] = set()
        self.max_concurrent = 2  # Start with 2 concurrent downloads to reduce UI lag
        self.save_queue = deque()  # Queue for deferred disk saves
        self._pending_callbacks: dict[str, list] = {}
        self._active_replies: dict[QNetworkReply, str] = {}
        self._shutting_down = False
        self._save_timer = None
        self._queue_timer = QTimer(self)
        self._queue_timer.setSingleShot(True)
        self._queue_timer.timeout.connect(self._process_queue)

    def get_image(self, metadata: ModlistMetadata, callback, size: str = "small") -> Optional[QPixmap]:
        """
        Get image for modlist - returns cached pixmap or None if needs download

        Args:
            metadata: Modlist metadata
            callback: Callback function when image is loaded
            size: Image size to use ("small" for cards, "large" for detail view)
        """
        if self._shutting_down:
            return None

        cache_key = f"{metadata.machineURL}_{size}"

        # Check memory cache first (should be preloaded)
        if cache_key in self.pixmap_cache:
            return self.pixmap_cache[cache_key]

        # Only check disk cache if not in memory (fallback for images that weren't preloaded)
        # Rarely happens if preload worked
        cached_path = self.gallery_service.get_cached_image_path(metadata, size)
        if cached_path and cached_path.exists():
            try:
                pixmap = QPixmap(str(cached_path))
                if not pixmap.isNull():
                    self.pixmap_cache[cache_key] = pixmap
                    return pixmap
            except Exception:
                pass

        # Queue for download if not cached
        if callback:
            self._pending_callbacks.setdefault(cache_key, []).append(callback)

        if cache_key not in self.downloading:
            self.download_queue.append((metadata, size))
            self._process_queue()

        return None

    def cleanup(self):
        """Abort in-flight replies and stop timers before the gallery dialog goes away."""
        if self._shutting_down:
            return

        self._shutting_down = True
        logger.debug(
            "Cleaning up gallery image manager | queued=%d active_replies=%d",
            len(self.download_queue),
            len(self._active_replies),
        )

        self.download_queue.clear()
        self.downloading.clear()
        self.save_queue.clear()
        self._pending_callbacks.clear()

        if self._queue_timer is not None and shiboken6.isValid(self._queue_timer):
            self._queue_timer.stop()

        if self._save_timer is not None and shiboken6.isValid(self._save_timer):
            self._save_timer.stop()
            self._save_timer.deleteLater()
            self._save_timer = None

        for reply in list(self._active_replies.keys()):
            if not shiboken6.isValid(reply):
                continue
            try:
                reply.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()
        self._active_replies.clear()

    def _process_queue(self):
        """Process download queue up to max_concurrent"""
        if self._shutting_down:
            return

        # Process one at a time with small delays to keep UI responsive
        if len(self.downloading) < self.max_concurrent and self.download_queue:
            metadata, size = self.download_queue.popleft()
            cache_key = f"{metadata.machineURL}_{size}"

            if cache_key not in self.downloading:
                self.downloading.add(cache_key)
                self._download_image(metadata, size)

                # Schedule next download with small delay to yield to UI
                if self.download_queue:
                    self._schedule_queue_processing(100)

    def _schedule_queue_processing(self, delay_ms: int):
        """Schedule queue processing without leaving orphaned single-shot callbacks behind."""
        if self._shutting_down or not shiboken6.isValid(self._queue_timer):
            return
        self._queue_timer.start(delay_ms)

    def _download_image(self, metadata: ModlistMetadata, size: str = "small"):
        """Download image from network"""
        image_url = self.gallery_service.get_image_url(metadata, size)
        if not image_url:
            cache_key = f"{metadata.machineURL}_{size}"
            self.downloading.discard(cache_key)
            self._pending_callbacks.pop(cache_key, None)
            self._schedule_queue_processing(0)
            return

        url = QUrl(image_url)
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"Jackify/0.1.8")

        reply = self.network_manager.get(request)
        cache_key = f"{metadata.machineURL}_{size}"
        self._active_replies[reply] = cache_key
        reply.finished.connect(partial(self._on_download_finished, reply, metadata, size))

    def _on_download_finished(self, reply: QNetworkReply, metadata: ModlistMetadata, size: str = "small"):
        """Handle download completion"""
        cache_key = f"{metadata.machineURL}_{size}"
        callbacks = self._pending_callbacks.pop(cache_key, [])
        self._active_replies.pop(reply, None)
        self.downloading.discard(cache_key)

        try:
            if self._shutting_down or not shiboken6.isValid(reply):
                return

            if reply.error() != QNetworkReply.NoError:
                logger.debug(
                    "Gallery image download failed | url=%s error=%s",
                    reply.url().toString(),
                    reply.errorString(),
                )
                return

            image_data = reply.readAll()
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_data) or pixmap.isNull():
                logger.debug(
                    "Gallery image decode failed | cache_key=%s bytes=%d",
                    cache_key,
                    len(image_data),
                )
                return

            # Store in memory cache immediately.
            self.pixmap_cache[cache_key] = pixmap

            # Defer disk save to avoid blocking UI - queue it for later.
            cached_path = self.gallery_service.get_image_cache_path(metadata, size)
            self.save_queue.append((pixmap, cached_path))
            self._start_save_timer()

            for callback in callbacks:
                self._invoke_callback(callback, pixmap, cache_key)
        finally:
            if shiboken6.isValid(reply):
                reply.deleteLater()

            # Process next in queue with a short delay to yield to the UI thread.
            if not self._shutting_down:
                self._schedule_queue_processing(50)

    def _invoke_callback(self, callback, pixmap: QPixmap, cache_key: str):
        """Call a widget-bound callback only while its QObject still exists."""
        if callback is None:
            return

        callback_owner = getattr(callback, "__self__", None)
        if callback_owner is not None:
            try:
                if not shiboken6.isValid(callback_owner):
                    logger.debug("Skipping stale gallery image callback | cache_key=%s", cache_key)
                    return
            except TypeError:
                pass

        try:
            callback(pixmap)
        except RuntimeError as exc:
            logger.debug("Gallery image callback failed | cache_key=%s error=%s", cache_key, exc)

    def _start_save_timer(self):
        """Start timer for deferred disk saves if not already running"""
        if self._save_timer is None:
            self._save_timer = QTimer(self)
            self._save_timer.timeout.connect(self._save_next_image)
            self._save_timer.setSingleShot(False)
            self._save_timer.start(200)  # Save one image every 200ms

    def _save_next_image(self):
        """Save next image from queue to disk (non-blocking)"""
        if self._shutting_down:
            return

        if self.save_queue:
            pixmap, cached_path = self.save_queue.popleft()
            try:
                cached_path.parent.mkdir(parents=True, exist_ok=True)
                pixmap.save(str(cached_path), "WEBP")
            except Exception:
                pass  # Save failed - not critical, image is in memory cache

        # Stop timer if queue is empty
        if not self.save_queue and self._save_timer:
            self._save_timer.stop()
            self._save_timer.deleteLater()
            self._save_timer = None
