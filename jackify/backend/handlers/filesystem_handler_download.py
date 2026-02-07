"""
Filesystem download operations: download_file.
"""

import logging
from pathlib import Path

import requests


logger = logging.getLogger(__name__)


class FilesystemDownloadMixin:
    """Mixin providing download_file for FileSystemHandler."""

    def download_file(self, url: str, destination_path: Path, overwrite: bool = False, quiet: bool = False) -> bool:
        """Download a file from a URL to a destination path."""
        self.logger.info("Downloading %s to %s...", url, destination_path)

        if not overwrite and destination_path.exists():
            self.logger.info("File already exists, skipping download: %s", destination_path)
            if not quiet:
                self.logger.info("File %s already exists, skipping download.", destination_path.name)
            return True

        try:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(url, stream=True, timeout=300, verify=True) as r:
                r.raise_for_status()
                with open(destination_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            self.logger.info("Download complete.")
            if not quiet:
                self.logger.info("Download complete.")
            return True
        except requests.exceptions.RequestException as e:
            self.logger.error("Download failed: %s", e)
            self.logger.error("Download failed for %s. Check network connection and URL.", url)
            if destination_path.exists():
                try:
                    destination_path.unlink()
                except OSError:
                    pass
            return False
        except Exception as e:
            self.logger.error("Error during download or file writing: %s", e, exc_info=True)
            self.logger.error("An unexpected error occurred during download.")
            if destination_path.exists():
                try:
                    destination_path.unlink()
                except OSError:
                    pass
            return False
