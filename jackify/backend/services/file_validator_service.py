"""
Hash validation and file move for manually downloaded archives.
Uses xxhash64 to match the engine's hash format exactly.
"""

import struct
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# xxhash produces 16-char lowercase hex with no prefix - matches engine Hash.ToHex()
# C extension is ABI-locked to the Python version it was compiled against, so
# AppImage builds need a pure-Python fallback for cross-version compatibility.
try:
    import xxhash
    _XXHASH_IMPL = 'native'
except ImportError:
    xxhash = None
    _XXHASH_IMPL = 'fallback'
    logger.info("xxhash C extension not available, using pure-Python fallback")


class _XXH64Fallback:
    """Pure-Python xxhash64 implementation for when the C extension can't load.
    Reference: https://github.com/Cyan4973/xxHash/blob/dev/doc/xxhash_spec.md"""

    _P1 = 11400714785074694791
    _P2 = 14029467366897019727
    _P3 = 1609587929392839161
    _P4 = 9650029242287828579
    _P5 = 2870177450012600261
    _M64 = 0xFFFFFFFFFFFFFFFF

    def __init__(self, seed: int = 0):
        self._seed = seed & self._M64
        self._total_len = 0
        self._buf = b""
        self._v1 = (seed + self._P1 + self._P2) & self._M64
        self._v2 = (seed + self._P2) & self._M64
        self._v3 = seed & self._M64
        self._v4 = (seed - self._P1) & self._M64

    @staticmethod
    def _rotl64(x: int, r: int) -> int:
        return ((x << r) | (x >> (64 - r))) & 0xFFFFFFFFFFFFFFFF

    def _round(self, acc: int, inp: int) -> int:
        acc = (acc + inp * self._P2) & self._M64
        acc = self._rotl64(acc, 31)
        acc = (acc * self._P1) & self._M64
        return acc

    def _merge_round(self, acc: int, val: int) -> int:
        val = self._round(0, val)
        acc ^= val
        acc = (acc * self._P1 + self._P4) & self._M64
        return acc

    def update(self, data: bytes) -> None:
        self._buf += data
        self._total_len += len(data)

        if len(self._buf) < 32:
            return

        p = 0
        end = len(self._buf) - 31  # process 32-byte blocks

        while p < end:
            self._v1 = self._round(self._v1, struct.unpack_from('<Q', self._buf, p)[0])
            self._v2 = self._round(self._v2, struct.unpack_from('<Q', self._buf, p + 8)[0])
            self._v3 = self._round(self._v3, struct.unpack_from('<Q', self._buf, p + 16)[0])
            self._v4 = self._round(self._v4, struct.unpack_from('<Q', self._buf, p + 24)[0])
            p += 32

        self._buf = self._buf[p:]

    def hexdigest(self) -> str:
        return format(self._digest(), '016x')

    def _digest(self) -> int:
        M = self._M64
        if self._total_len >= 32:
            h = self._rotl64(self._v1, 1)
            h = (h + self._rotl64(self._v2, 7)) & M
            h = (h + self._rotl64(self._v3, 12)) & M
            h = (h + self._rotl64(self._v4, 18)) & M
            h = self._merge_round(h, self._v1)
            h = self._merge_round(h, self._v2)
            h = self._merge_round(h, self._v3)
            h = self._merge_round(h, self._v4)
        else:
            h = (self._seed + self._P5) & M

        h = (h + self._total_len) & M

        buf = self._buf
        p = 0
        remaining = len(buf)

        while remaining >= 8:
            k1 = struct.unpack_from('<Q', buf, p)[0]
            k1 = self._round(0, k1)
            h ^= k1
            h = (self._rotl64(h, 27) * self._P1 + self._P4) & M
            p += 8
            remaining -= 8

        while remaining >= 4:
            k1 = struct.unpack_from('<I', buf, p)[0]
            h ^= (k1 * self._P1) & M
            h = (self._rotl64(h, 23) * self._P2 + self._P3) & M
            p += 4
            remaining -= 4

        while remaining > 0:
            h ^= (buf[p] * self._P5) & M
            h = (self._rotl64(h, 11) * self._P1) & M
            p += 1
            remaining -= 1

        # Avalanche
        h ^= h >> 33
        h = (h * self._P2) & M
        h ^= h >> 29
        h = (h * self._P3) & M
        h ^= h >> 32
        return h

_CHUNK = 1024 * 1024  # 1 MB


def _reverse_hex_byte_order(hex_value: str) -> str:
    """Reverse byte order of a hex string (e.g. aabbccdd -> ddccbbaa)."""
    value = (hex_value or "").strip().lower()
    if len(value) % 2 != 0:
        return value
    return "".join(reversed([value[i:i + 2] for i in range(0, len(value), 2)]))


def _hash_matches_expected(computed_hash: str, expected_hash: str) -> bool:
    """Accept either canonical or byte-reversed xxhash64 representations."""
    computed = (computed_hash or "").strip().lower()
    expected = (expected_hash or "").strip().lower()
    if not computed or not expected:
        return False
    return computed == expected or _reverse_hex_byte_order(computed) == expected


@dataclass
class ValidationResult:
    matches: bool
    computed_hash: Optional[str]
    file_path: Path
    error: Optional[str] = None


class FileValidatorService:
    """
    Validates downloaded files against expected xxhash64 and moves them to
    the modlist downloads directory on success.
    """

    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='FileValidator')

    def validate_async(
        self,
        file_path: Path,
        expected_hash: str,
        modlist_download_dir: Path,
        on_result: Callable[[ValidationResult, Optional[Path]], None],
        dest_name: Optional[str] = None,
    ) -> None:
        """
        Validate file_path against expected_hash in a thread pool worker.
        on_result(result, dest_path) is called on the worker thread when done.
        dest_path is the moved file location if validation succeeded, else None.
        dest_name overrides the destination filename (used when the engine's
        canonical name differs from the downloaded file's name, e.g. leading dot).
        """
        self._executor.submit(
            self._validate_and_move,
            file_path, expected_hash, modlist_download_dir, on_result, dest_name
        )

    def _validate_and_move(
        self,
        file_path: Path,
        expected_hash: str,
        modlist_download_dir: Path,
        on_result: Callable,
        dest_name: Optional[str] = None,
    ) -> None:
        result = self._validate(file_path, expected_hash)
        dest: Optional[Path] = None
        if result.matches:
            try:
                dest = self._move_file(file_path, modlist_download_dir, dest_name=dest_name)
                logger.info(
                    "[MDL-1026] Archive move complete | "
                    f"source_path={file_path} destination_path={dest} hash={result.computed_hash or 'missing'}"
                )
            except OSError as e:
                logger.warning(
                    "[MDL-9020] Archive move failed after hash validation | "
                    f"source_path={file_path} destination_dir={modlist_download_dir} reason={e}"
                )
                result = ValidationResult(
                    matches=False,
                    computed_hash=result.computed_hash,
                    file_path=file_path,
                    error=f"Move failed: {e}",
                )
        on_result(result, dest)

    def _validate(self, file_path: Path, expected_hash: str) -> ValidationResult:
        try:
            # No expected hash — accept by filename match alone, just move the file.
            if not (expected_hash or "").strip():
                return ValidationResult(matches=True, computed_hash=None, file_path=file_path)
            h = xxhash.xxh64() if xxhash else _XXH64Fallback()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
            computed = h.hexdigest().lower()  # 16-char lowercase hex, no prefix
            matches = _hash_matches_expected(computed, expected_hash)
            return ValidationResult(
                matches=matches,
                computed_hash=computed,
                file_path=file_path,
            )
        except OSError as e:
            return ValidationResult(matches=False, computed_hash=None, file_path=file_path,
                                    error=str(e))

    def _move_file(self, source: Path, dest_dir: Path, dest_name: Optional[str] = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (dest_name if dest_name else source.name)
        # If the watched file is already in the modlist downloads directory,
        # treat it as in-place and avoid a same-path move error.
        try:
            if source.resolve() == dest.resolve():
                logger.debug(f"Validated file already in modlist downloads directory: {source}")
                return dest
        except OSError:
            pass
        shutil.move(str(source), str(dest))
        logger.debug(f"Moved validated file: {source.name} -> {dest}")
        return dest

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
