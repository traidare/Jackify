"""Image loading and caching manager for ModlistGalleryDialog."""
from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtGui import QPixmap
from typing import Optional, Dict
from collections import deque
from jackify.backend.models.modlist_metadata import ModlistMetadata
from jackify.backend.services.modlist_gallery_service import ModlistGalleryService

class ImageManager(QObject):
    """Centralized image loading and caching manager"""
    
    def __init__(self, gallery_service: ModlistGalleryService):
        super().__init__()
        self.gallery_service = gallery_service
        self.pixmap_cache: Dict[str, QPixmap] = {}
        self.network_manager = QNetworkAccessManager()
        self.download_queue = deque()
        self.downloading: set = set()
        self.max_concurrent = 2  # Start with 2 concurrent downloads to reduce UI lag
        self.save_queue = deque()  # Queue for deferred disk saves
        self._save_timer = None
        
    def get_image(self, metadata: ModlistMetadata, callback, size: str = "small") -> Optional[QPixmap]:
        """
        Get image for modlist - returns cached pixmap or None if needs download
        
        Args:
            metadata: Modlist metadata
            callback: Callback function when image is loaded
            size: Image size to use ("small" for cards, "large" for detail view)
        """
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
        if cache_key not in self.downloading:
            self.download_queue.append((metadata, callback, size))
            self._process_queue()
        
        return None
    
    def _process_queue(self):
        """Process download queue up to max_concurrent"""
        # Process one at a time with small delays to keep UI responsive
        if len(self.downloading) < self.max_concurrent and self.download_queue:
            metadata, callback, size = self.download_queue.popleft()
            cache_key = f"{metadata.machineURL}_{size}"
            
            if cache_key not in self.downloading:
                self.downloading.add(cache_key)
                self._download_image(metadata, callback, size)
                
                # Schedule next download with small delay to yield to UI
                if self.download_queue:
                    QTimer.singleShot(100, self._process_queue)
    
    def _download_image(self, metadata: ModlistMetadata, callback, size: str = "small"):
        """Download image from network"""
        image_url = self.gallery_service.get_image_url(metadata, size)
        if not image_url:
            cache_key = f"{metadata.machineURL}_{size}"
            self.downloading.discard(cache_key)
            self._process_queue()
            return
        
        url = QUrl(image_url)
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"Jackify/0.1.8")
        
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self._on_download_finished(reply, metadata, callback, size))
    
    def _on_download_finished(self, reply: QNetworkReply, metadata: ModlistMetadata, callback, size: str = "small"):
        """Handle download completion"""
        from PySide6.QtWidgets import QApplication
        
        cache_key = f"{metadata.machineURL}_{size}"
        self.downloading.discard(cache_key)
        
        if reply.error() == QNetworkReply.NoError:
            image_data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data) and not pixmap.isNull():
                # Store in memory cache immediately
                self.pixmap_cache[cache_key] = pixmap
                
                # Defer disk save to avoid blocking UI - queue it for later
                cached_path = self.gallery_service.get_image_cache_path(metadata, size)
                self.save_queue.append((pixmap, cached_path))
                self._start_save_timer()
                
                # Call callback with pixmap (update UI immediately)
                if callback:
                    callback(pixmap)
                
                # Process events to keep UI responsive
                QApplication.processEvents()
        
        reply.deleteLater()
        
        # Process next in queue (with small delay to yield to UI)
        QTimer.singleShot(50, self._process_queue)
    
    def _start_save_timer(self):
        """Start timer for deferred disk saves if not already running"""
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.timeout.connect(self._save_next_image)
            self._save_timer.setSingleShot(False)
            self._save_timer.start(200)  # Save one image every 200ms
    
    def _save_next_image(self):
        """Save next image from queue to disk (non-blocking)"""
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
            self._save_timer = None
