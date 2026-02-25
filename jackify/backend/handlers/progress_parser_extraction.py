"""Progress/speed extraction methods for ProgressParser (Mixin)."""

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ProgressParserExtractionMixin:
    """Mixin providing progress and speed extraction methods."""

    def _extract_overall_progress(self, line: str) -> Optional[float]:
        """Extract overall progress percentage."""
        match = re.search(r'(?:Progress|Overall):\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            return float(match.group(1))

        match = re.search(r'^(\d+(?:\.\d+)?)%\s*(?:complete|done|progress)', line, re.IGNORECASE)
        if match:
            return float(match.group(1))

        return None

    def _extract_step_info(self, line: str) -> Optional[Tuple[int, int]]:
        """Extract step information like [12/14]."""
        line_lower = line.lower()
        # Texture conversion counters are tracked separately; don't let generic
        # step parsing overwrite the primary install counter.
        if 'converting textures' in line_lower and 'installing files' not in line_lower:
            return None

        match = self.wabbajack_status_pattern.search(line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            return (current, total)

        match = re.search(r'\[(\d+)/(\d+)\]', line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            return (current, total)
        return None

    def _extract_data_info(self, line: str) -> Optional[Tuple[int, int]]:
        """Extract data size information like 1.1GB/56.3GB."""
        match = re.search(r'\(?(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\)?', line, re.IGNORECASE)
        if match:
            current_val = float(match.group(1))
            current_unit = match.group(2).upper()
            total_val = float(match.group(3))
            total_unit = match.group(4).upper()

            current_bytes = self._convert_to_bytes(current_val, current_unit)
            total_bytes = self._convert_to_bytes(total_val, total_unit)

            return (current_bytes, total_bytes)

        return None

    def _parse_data_string(self, data_str: str) -> Optional[Tuple[int, int]]:
        """Parse data string like '1.1GB/56.3GB' or '1234/5678'."""
        match = re.search(r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', data_str, re.IGNORECASE)
        if match:
            current_val = float(match.group(1))
            current_unit = match.group(2).upper()
            total_val = float(match.group(3))
            total_unit = match.group(4).upper()

            current_bytes = self._convert_to_bytes(current_val, current_unit)
            total_bytes = self._convert_to_bytes(total_val, total_unit)

            return (current_bytes, total_bytes)

        match = re.search(r'(\d+)\s*/\s*(\d+)', data_str)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            return (current, total)

        return None

    def _extract_speed_info(self, line: str) -> Optional[Tuple[str, float]]:
        """Extract speed information."""
        match = re.search(r'-\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            speed_val = float(match.group(1))
            speed_unit = match.group(2).upper()
            speed_bytes = self._convert_to_bytes(speed_val, speed_unit)

            operation = "unknown"
            line_lower = line.lower()
            if 'download' in line_lower:
                operation = "download"
            elif 'extract' in line_lower:
                operation = "extract"
            elif 'validat' in line_lower or 'hash' in line_lower:
                operation = "validate"

            return (operation, speed_bytes)

        match = re.search(r'(?:at|speed:?)\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            speed_val = float(match.group(1))
            speed_unit = match.group(2).upper()
            speed_bytes = self._convert_to_bytes(speed_val, speed_unit)

            operation = "unknown"
            line_lower = line.lower()
            if 'download' in line_lower:
                operation = "download"
            elif 'extract' in line_lower:
                operation = "extract"
            elif 'validat' in line_lower:
                operation = "validate"

            return (operation, speed_bytes)

        return None

    def _parse_speed(self, speed_str: str) -> float:
        """Parse speed string to bytes per second."""
        match = re.search(r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', speed_str, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).upper()
            return self._convert_to_bytes(value, unit)
        return 0.0

    def _parse_speed_from_string(self, speed_str: str) -> float:
        """Parse speed string like '6.8MB/s' to bytes per second."""
        match = re.search(r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s(?:ec)?', speed_str, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).upper()
            return self._convert_to_bytes(value, unit)
        return 0.0

    def _convert_to_bytes(self, value: float, unit: str) -> int:
        """Convert value with unit to bytes."""
        multipliers = {
            'B': 1,
            'KB': 1024,
            'MB': 1024 * 1024,
            'GB': 1024 * 1024 * 1024,
            'TB': 1024 * 1024 * 1024 * 1024
        }
        return int(value * multipliers.get(unit, 1))
