"""
Progress Parser

Parses jackify-engine text output to extract structured progress information.
This is an R&D implementation - experimental and subject to change.
"""

import os
import re
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass

from jackify.shared.progress_models import (
    InstallationProgress,
    InstallationPhase,
    FileProgress,
    OperationType
)


@dataclass
class ParsedLine:
    """Result of parsing a single line of output."""
    has_progress: bool = False
    phase: Optional[InstallationPhase] = None
    phase_name: Optional[str] = None
    file_progress: Optional[FileProgress] = None
    completed_filename: Optional[str] = None  # Filename that just completed
    overall_percent: Optional[float] = None
    step_info: Optional[Tuple[int, int]] = None  # (current, total)
    data_info: Optional[Tuple[int, int]] = None  # (current_bytes, total_bytes)
    speed_info: Optional[Tuple[str, float]] = None  # (operation, speed_bytes_per_sec)
    file_counter: Optional[Tuple[int, int]] = None  # (current_file, total_files) for Extracting phase
    message: str = ""


class ProgressParser:
    """
    Parses jackify-engine output to extract progress information.
    
    This parser uses pattern matching to extract:
    - Installation phases
    - File-level progress
    - Overall progress percentages
    - Step counts
    - Data sizes
    - Operation speeds
    """
    
    def __init__(self):
        """Initialize parser with pattern definitions."""
        # Phase detection patterns
        self.phase_patterns = [
            (r'===?\s*(.+?)\s*===?', self._extract_phase_from_section),
            (r'\[.*?\]\s*(?:Installing|Downloading|Extracting|Validating|Processing)', self._extract_phase_from_action),
            (r'(?:Starting|Beginning)\s+(.+?)(?:\s+phase|\.|$)', re.IGNORECASE),
        ]
        
        # File progress patterns
        self.file_patterns = [
            # Pattern: "Installing: filename.7z (42%)"
            (r'(?:Installing|Downloading|Extracting|Validating):\s*(.+?)\s*\((\d+(?:\.\d+)?)%\)', self._parse_file_with_percent),
            # Pattern: "filename.7z: 42%"
            (r'(.+?\.(?:7z|zip|rar|bsa|dds)):\s*(\d+(?:\.\d+)?)%', self._parse_file_with_percent),
            # Pattern: "filename.7z [45.2MB/s]"
            (r'(.+?\.(?:7z|zip|rar|bsa|dds))\s*\[([^\]]+)\]', self._parse_file_with_speed),
        ]
        
        # Overall progress patterns (stored as regex patterns, not tuples with callbacks)
        # Wabbajack format: "[12/14] Installing files (1.1GB/56.3GB)"
        self.overall_patterns = [
            # Pattern: "Progress: 85%" or "85%"
            (r'(?:Progress|Overall):\s*(\d+(?:\.\d+)?)%', re.IGNORECASE),
            (r'^(\d+(?:\.\d+)?)%\s*(?:complete|done|progress)', re.IGNORECASE),
        ]
        
        # Wabbajack status update format: "[12/14] StatusText (current/total)"
        # This is the primary format we should match
        self.wabbajack_status_pattern = re.compile(
            r'\[(\d+)/(\d+)\]\s+(.+?)\s+\(([^)]+)\)',
            re.IGNORECASE
        )
        
        # Alternative format: "[timestamp] StatusText (current/total) - speed"
        # Example: "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s"
        self.timestamp_status_pattern = re.compile(
            r'\[[^\]]+\]\s+(.+?)\s+\((\d+)/(\d+)\)\s*-\s*([^\s]+)',
            re.IGNORECASE
        )
        
        # Data size patterns
        self.data_patterns = [
            # Pattern: "1.1GB/56.3GB" or "(1.1GB/56.3GB)"
            (r'\(?(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\)?', re.IGNORECASE),
            # Pattern: "Processing 1.1GB of 56.3GB"
            (r'Processing\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s+of\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', re.IGNORECASE),
        ]
        
        # Speed patterns
        self.speed_patterns = [
            # Pattern: "267.3MB/s" or "45.2 MB/s"
            (r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', re.IGNORECASE),
            # Pattern: "at 267.3MB/s" or "speed: 45.2 MB/s"
            (r'(?:at|speed:?)\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', re.IGNORECASE),
        ]
        
        # File filter - only display meaningful artifacts in the UI
        self.allowed_extensions = {
            '.7z', '.zip', '.rar', '.bsa', '.ba2', '.dds', '.wabbajack',
            '.exe', '.esp', '.esm', '.esl', '.bin', '.dll', '.pak',
            '.tar', '.gz', '.xz', '.bz2', '.z01', '.z02', '.cab', '.msi'
        }
    
    def should_display_file(self, filename: str) -> bool:
        """Public helper so other components can reuse the filter."""
        return self._should_display_file(filename)
    
    def _should_display_file(self, filename: str) -> bool:
        """Determine whether a filename is worth showing in the UI."""
        if not filename:
            return False
        base = os.path.basename(filename.strip())
        if not base:
            return False
        # Special case: allow ".wabbajack" and "Downloading .wabbajack file"
        if base == ".wabbajack" or base == "Downloading .wabbajack file":
            return True
        # Skip temporary/generated files (e.g., #zcbe$123.txt)
        if base.startswith('#'):
            return False
        name, ext = os.path.splitext(base)
        if not ext:
            return False
        if ext.lower() not in self.allowed_extensions:
            return False
        # Also skip generic filenames that are clearly tooling artifacts
        if name.lower() in {'empty', 'script', 'one', 'two', 'three'}:
            return False
        return True
    
    def parse_line(self, line: str) -> ParsedLine:
        """
        Parse a single line of output and extract progress information.
        
        Args:
            line: Raw line from jackify-engine output
            
        Returns:
            ParsedLine with extracted information
        """
        result = ParsedLine(message=line.strip())
        
        if not line.strip():
            return result
        
        # Try to extract phase information
        phase_info = self._extract_phase(line)
        if phase_info:
            result.phase, result.phase_name = phase_info
            result.has_progress = True
        
        # Try to extract file progress
        file_prog = self._extract_file_progress(line)
        if file_prog:
            result.file_progress = file_prog
            result.has_progress = True
            # Check if file counter was attached (for extraction or install phases)
            if hasattr(file_prog, '_file_counter'):
                result.file_counter = file_prog._file_counter
                delattr(file_prog, '_file_counter')  # Clean up temp attribute
        
        # Try to extract overall progress
        overall = self._extract_overall_progress(line)
        if overall is not None:
            result.overall_percent = overall
            result.has_progress = True
        
        # Try to extract Wabbajack status format first: "[12/14] StatusText (1.1GB/56.3GB)"
        # BUT skip if this is a .wabbajack download line (handled by specific pattern below)
        wabbajack_match = self.wabbajack_status_pattern.search(line)
        if wabbajack_match:
            status_text = wabbajack_match.group(3).strip().lower()
            # Skip if this is a .wabbajack download - let the specific pattern handle it
            if '.wabbajack' in status_text or 'downloading .wabbajack' in status_text:
                # Don't process this as generic status - let .wabbajack pattern handle it
                pass
            else:
                # Extract step info
                current_step = int(wabbajack_match.group(1))
                max_steps = int(wabbajack_match.group(2))
                result.step_info = (current_step, max_steps)
                
                # Extract status text (phase name)
                phase_info = self._extract_phase_from_text(status_text)
                if phase_info:
                    result.phase, result.phase_name = phase_info
                
                # Extract data info from parentheses
                data_str = wabbajack_match.group(4).strip()
                data_info = self._parse_data_string(data_str)
                if data_info:
                    result.data_info = data_info
                
                result.has_progress = True
        
        # Try alternative format: "[timestamp] StatusText (current/total) - speed"
        # Example: "[00:00:10] Downloading Mod Archives (17/214) - 6.8MB/s"
        timestamp_match = self.timestamp_status_pattern.search(line)
        if timestamp_match:
            # Extract status text (phase name)
            status_text = timestamp_match.group(1).strip()
            phase_info = self._extract_phase_from_text(status_text)
            if phase_info:
                result.phase, result.phase_name = phase_info
            
            # Extract step info (current/total in parentheses)
            current_step = int(timestamp_match.group(2))
            max_steps = int(timestamp_match.group(3))
            result.step_info = (current_step, max_steps)
            
            # Extract speed
            speed_str = timestamp_match.group(4).strip()
            speed_info = self._parse_speed_from_string(speed_str)
            if speed_info:
                operation = self._detect_operation_from_line(status_text)
                result.speed_info = (operation.value, speed_info)
            
            # Calculate overall percentage from step progress
            if max_steps > 0:
                result.overall_percent = (current_step / max_steps) * 100.0
            
            result.has_progress = True
        
        # Try .wabbajack download format: "[timestamp] Downloading .wabbajack (size/size) - speed"
        # Example: "[00:02:08] Downloading .wabbajack (739.2/1947.2MB) - 6.0MB/s"
        # Also handles: "[00:02:08] Downloading modlist.wabbajack (739.2/1947.2MB) - 6.0MB/s"
        wabbajack_download_pattern = re.compile(
            r'\[[^\]]+\]\s+Downloading\s+([^\s]+\.wabbajack|\.wabbajack)\s+\(([^)]+)\)\s*-\s*([^\s]+)',
            re.IGNORECASE
        )
        wabbajack_match = wabbajack_download_pattern.search(line)
        if wabbajack_match:
            # Extract filename (group 1)
            filename = wabbajack_match.group(1).strip()
            if filename == ".wabbajack":
                # Try to extract actual filename from message if available
                filename_match = re.search(r'([A-Za-z0-9_\-\.]+\.wabbajack)', line, re.IGNORECASE)
                if filename_match:
                    filename = filename_match.group(1)
                else:
                    # Use display message as filename
                    filename = "Downloading .wabbajack file"
            
            # Extract data info from parentheses (e.g., "49.7/1947.2MB" or "739.2MB/1947.2MB")
            # Format can be: "current/totalUnit" or "currentUnit/totalUnit"
            data_str = wabbajack_match.group(2).strip()
            data_info = None
            
            # Try standard format first (both have units)
            data_info = self._extract_data_info(f"({data_str})")
            
            # If that fails, try format where only second number has unit: "49.7/1947.2MB"
            if not data_info:
                pattern = r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)'
                match = re.search(pattern, data_str, re.IGNORECASE)
                if match:
                    current_val = float(match.group(1))
                    current_unit = match.group(2) if match.group(2) else match.group(4)  # Use second unit if first missing
                    total_val = float(match.group(3))
                    total_unit = match.group(4)
                    
                    current_bytes = self._convert_to_bytes(current_val, current_unit)
                    total_bytes = self._convert_to_bytes(total_val, total_unit)
                    data_info = (current_bytes, total_bytes)
            
            if data_info:
                result.data_info = data_info
                # Calculate percent from data
                current_bytes, total_bytes = data_info
                if total_bytes > 0:
                    result.overall_percent = (current_bytes / total_bytes) * 100.0
            
            # Extract speed (group 3)
            speed_str = wabbajack_match.group(3).strip()
            speed_info = self._parse_speed_from_string(speed_str)
            if speed_info:
                result.speed_info = ("download", speed_info)
            
            # Set phase
            result.phase = InstallationPhase.DOWNLOAD
            result.phase_name = f"Downloading {filename}"
            
            # Create FileProgress entry for .wabbajack file
            if data_info:
                current_bytes, total_bytes = data_info
                percent = (current_bytes / total_bytes) * 100.0 if total_bytes > 0 else 0.0
                from jackify.shared.progress_models import FileProgress, OperationType
                file_progress = FileProgress(
                    filename=filename,
                    operation=OperationType.DOWNLOAD,
                    percent=percent,
                    current_size=current_bytes,
                    total_size=total_bytes,
                    speed=speed_info if speed_info else -1.0
                )
                result.file_progress = file_progress
            
            result.has_progress = True
        
        # Try to extract step information (fallback)
        if not result.step_info:
            step_info = self._extract_step_info(line)
            if step_info:
                result.step_info = step_info
                result.has_progress = True
        
        # Try to extract data size information (fallback)
        if not result.data_info:
            data_info = self._extract_data_info(line)
            if data_info:
                result.data_info = data_info
                result.has_progress = True
        
        # Try to extract speed information
        speed_info = self._extract_speed_info(line)
        if speed_info:
            result.speed_info = speed_info
            result.has_progress = True
        
        # Try to detect file completion
        completed_file = self._extract_completed_file(line)
        if completed_file:
            result.completed_filename = completed_file
            result.has_progress = True
        
        return result
    
    def _extract_phase(self, line: str) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase information from line."""
        # Check for section headers like "=== Installing files ==="
        section_match = re.search(r'===?\s*(.+?)\s*===?', line)
        if section_match:
            section_name = section_match.group(1).strip().lower()
            phase = self._map_section_to_phase(section_name)
            return (phase, section_match.group(1).strip())
        
        # Check for action-based phase indicators
        action_match = re.search(r'\[.*?\]\s*(Installing|Downloading|Extracting|Validating|Processing|Checking existing)', line, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).lower()
            phase = self._map_action_to_phase(action)
            return (phase, action_match.group(1))
        
        return None
    
    def _extract_phase_from_section(self, match: re.Match) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from section header match."""
        section_name = match.group(1).strip().lower()
        phase = self._map_section_to_phase(section_name)
        return (phase, match.group(1).strip())
    
    def _extract_phase_from_action(self, match: re.Match) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from action match."""
        action = match.group(1).lower()
        phase = self._map_action_to_phase(action)
        return (phase, match.group(1))
    
    def _map_section_to_phase(self, section_name: str) -> InstallationPhase:
        """Map section name to InstallationPhase enum."""
        section_lower = section_name.lower()
        if 'download' in section_lower:
            return InstallationPhase.DOWNLOAD
        elif 'extract' in section_lower:
            return InstallationPhase.EXTRACT
        elif 'validate' in section_lower or 'verif' in section_lower:
            return InstallationPhase.VALIDATE
        elif 'install' in section_lower:
            return InstallationPhase.INSTALL
        elif 'finaliz' in section_lower or 'complet' in section_lower:
            return InstallationPhase.FINALIZE
        elif 'configur' in section_lower or 'initializ' in section_lower:
            return InstallationPhase.INITIALIZATION
        else:
            return InstallationPhase.UNKNOWN
    
    def _map_action_to_phase(self, action: str) -> InstallationPhase:
        """Map action word to InstallationPhase enum."""
        action_lower = action.lower()
        if 'download' in action_lower:
            return InstallationPhase.DOWNLOAD
        elif 'extract' in action_lower:
            return InstallationPhase.EXTRACT
        elif 'validat' in action_lower or 'checking' in action_lower:
            return InstallationPhase.VALIDATE
        elif 'install' in action_lower:
            return InstallationPhase.INSTALL
        else:
            return InstallationPhase.UNKNOWN
    
    def _extract_file_progress(self, line: str) -> Optional[FileProgress]:
        """Extract file-level progress information."""
        # CRITICAL: Defensive checks to prevent segfault in regex engine
        # Segfaults happen in C code before Python exceptions, so we must validate input first
        if not line or not isinstance(line, str):
            return None
        # Limit line length to prevent stack overflow in regex (10KB should be more than enough)
        if len(line) > 10000:
            return None
        # Check for null bytes or other problematic characters that could corrupt regex
        if '\x00' in line:
            # Replace null bytes to prevent corruption
            line = line.replace('\x00', '')
        
        # PRIORITY: Check for [FILE_PROGRESS] prefix first (new engine format)
        # Format: [FILE_PROGRESS] Downloading: filename.zip (20.0%) [3.7MB/s]
        # Updated format: [FILE_PROGRESS] (Downloading|Extracting|Installing|Converting|Completed|etc): filename.zip (20.0%) [3.7MB/s] (current/total)
        # Speed bracket is optional to handle cases where speed may not be present
        # Counter (current/total) is optional and used for Extracting and Installing phases
        file_progress_match = re.search(
            r'\[FILE_PROGRESS\]\s+(Downloading|Extracting|Validating|Installing|Converting|Building|Writing|Verifying|Completed|Checking existing):\s+(.+?)\s+\((\d+(?:\.\d+)?)%\)\s*(?:\[(.+?)\])?\s*(?:\((\d+)/(\d+)\))?',
            line,
            re.IGNORECASE
        )
        if file_progress_match:
            operation_str = file_progress_match.group(1).strip()
            filename = file_progress_match.group(2).strip()
            percent = float(file_progress_match.group(3))
            speed_str = file_progress_match.group(4).strip() if file_progress_match.group(4) else None
            # Extract counter if present (group 5 and 6)
            counter_current = int(file_progress_match.group(5)) if file_progress_match.group(5) else None
            counter_total = int(file_progress_match.group(6)) if file_progress_match.group(6) else None

            # Map operation string first (needed for hidden progress items)
            operation_map = {
                'downloading': OperationType.DOWNLOAD,
                'extracting': OperationType.EXTRACT,
                'validating': OperationType.VALIDATE,
                'installing': OperationType.INSTALL,
                'building': OperationType.INSTALL,  # BSA building
                'writing': OperationType.INSTALL,   # BSA writing
                'verifying': OperationType.VALIDATE,  # BSA verification
                'checking existing': OperationType.VALIDATE,  # Resume verification
                'converting': OperationType.INSTALL,
                'compiling': OperationType.INSTALL,
                'hashing': OperationType.VALIDATE,
                'completed': OperationType.UNKNOWN,
            }
            operation = operation_map.get(operation_str.lower(), OperationType.UNKNOWN)

            # If we have counter info but file shouldn't be displayed, create a minimal FileProgress
            # just to carry the counter information (for extraction/install summary display)
            if counter_current and counter_total and not self._should_display_file(filename):
                # Create minimal file progress that won't be shown in activity window
                # but will carry counter info for summary widget
                file_progress = FileProgress(
                    filename="__phase_progress__",  # Dummy name
                    operation=operation,  # Use detected operation
                    percent=percent,
                    speed=-1.0  # No speed for summary
                )
                file_progress._file_counter = (counter_current, counter_total)
                file_progress._hidden = True  # Mark as hidden so it doesn't show in activity window
                return file_progress

            if not self._should_display_file(filename):
                return None

            # Operation already mapped above (line 352)
            # If operation is "Completed", ensure percent is 100%
            if operation_str.lower() == 'completed':
                percent = 100.0
            
            # Parse speed if available
            # Use -1 as sentinel to indicate "no speed provided by engine"
            speed = -1.0
            if speed_str:
                speed = self._parse_speed_from_string(speed_str)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent,
                speed=speed
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info

            # Store counter in a temporary attribute we can access later
            # Distinguish between texture conversion, BSA building, and install counters
            if counter_current is not None and counter_total is not None:
                if operation_str.lower() == 'converting':
                    # This is a texture conversion counter
                    file_progress._texture_counter = (counter_current, counter_total)
                elif operation_str.lower() == 'building':
                    # This is a BSA building counter
                    file_progress._bsa_counter = (counter_current, counter_total)
                else:
                    # This is an install/extract counter
                    file_progress._file_counter = (counter_current, counter_total)

            return file_progress
        
        # Skip lines that are clearly status messages, not file progress
        if re.search(r'\[.*?\]\s*(?:Downloading|Installing|Extracting)\s+(?:Mod|Files|Archives)', line, re.IGNORECASE):
            return None
        
        # Pattern 1: "Installing: filename.7z (42%)" or "Downloading: filename.7z (42%)"
        match = re.search(r'(?:Installing|Downloading|Extracting|Validating):\s*(.+?)\s*\((\d+(?:\.\d+)?)%\)', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress
        
        # Pattern 2: "filename.7z: 42%" or "filename.7z - 42%" or "filename.wabbajack: 42%"
        match = re.search(r'(.+?\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[:-]\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress
        
        # Pattern 3: "filename.7z [45.2MB/s]" or "filename.7z @ 45.2MB/s" or "filename.wabbajack [45.2MB/s]"
        match = re.search(r'(.+?\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[\[@]\s*([^\]]+)\]?', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            speed_str = match.group(2).strip().rstrip(']')
            speed = self._parse_speed(speed_str)
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                speed=speed
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress
        
        # Pattern 4: Lines that look like filenames with progress info
        # Match lines that contain a filename-like pattern followed by percentage
        # This catches formats like "Enderal Remastered Armory - Standard-490-1-2-0-1669565635.7z at 42%"
        # or "modlist.wabbajack at 42%"
        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s+(?:at|@|:|-)?\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )
        
        # Pattern 5: Filename with size info that might indicate progress
        # "filename.7z (1.2MB/5.4MB)" or "filename.7z 1.2MB of 5.4MB" or "filename.wabbajack (1.2MB/5.4MB)"
        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[\(]?\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/?\s*of\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            current_val = float(match.group(2))
            current_unit = match.group(3).upper()
            total_val = float(match.group(4))
            total_unit = match.group(5).upper()
            current_bytes = self._convert_to_bytes(current_val, current_unit)
            total_bytes = self._convert_to_bytes(total_val, total_unit)
            percent = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                percent=percent,
                current_size=current_bytes,
                total_size=total_bytes
            )
        
        # Pattern 6: Filename with speed info
        # "filename.7z downloading at 45.2MB/s" or "filename.wabbajack downloading at 45.2MB/s"
        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s+(?:downloading|extracting|validating|installing)\s+at\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            speed_val = float(match.group(2))
            speed_unit = match.group(3).upper()
            speed = self._convert_to_bytes(speed_val, speed_unit)
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                speed=speed
            )
        
        return None
    
    def _parse_file_with_percent(self, match: re.Match) -> Optional[FileProgress]:
        """Parse file progress from percentage match."""
        filename = match.group(1).strip()
        percent = float(match.group(2))
        operation = OperationType.UNKNOWN
        # Try to detect operation from context
        return FileProgress(
            filename=filename,
            operation=operation,
            percent=percent
        )
    
    def _parse_file_with_speed(self, match: re.Match) -> Optional[FileProgress]:
        """Parse file progress from speed match."""
        filename = match.group(1).strip()
        speed_str = match.group(2).strip()
        speed = self._parse_speed(speed_str)
        operation = OperationType.UNKNOWN
        return FileProgress(
            filename=filename,
            operation=operation,
            speed=speed
        )
    
    def _detect_operation_from_line(self, line: str) -> OperationType:
        """Detect operation type from line content."""
        line_lower = line.lower()
        if 'download' in line_lower:
            return OperationType.DOWNLOAD
        elif 'extract' in line_lower:
            return OperationType.EXTRACT
        elif 'validat' in line_lower:
            return OperationType.VALIDATE
        elif 'install' in line_lower or 'build' in line_lower or 'convert' in line_lower:
            return OperationType.INSTALL
        else:
            return OperationType.UNKNOWN
    
    def _extract_overall_progress(self, line: str) -> Optional[float]:
        """Extract overall progress percentage."""
        # Pattern: "Progress: 85%" or "85%"
        match = re.search(r'(?:Progress|Overall):\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            return float(match.group(1))
        
        # Pattern: "85% complete"
        match = re.search(r'^(\d+(?:\.\d+)?)%\s*(?:complete|done|progress)', line, re.IGNORECASE)
        if match:
            return float(match.group(1))
        
        return None
    
    def _extract_step_info(self, line: str) -> Optional[Tuple[int, int]]:
        """Extract step information like [12/14]."""
        # Try Wabbajack status format first: "[12/14] StatusText (data)"
        match = self.wabbajack_status_pattern.search(line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            return (current, total)
        
        # Fallback to simple [12/14] pattern
        match = re.search(r'\[(\d+)/(\d+)\]', line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            return (current, total)
        return None
    
    def _extract_data_info(self, line: str) -> Optional[Tuple[int, int]]:
        """Extract data size information like 1.1GB/56.3GB."""
        # Pattern: "1.1GB/56.3GB" or "(1.1GB/56.3GB)"
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
        # Try size format first: "1.1GB/56.3GB"
        match = re.search(r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', data_str, re.IGNORECASE)
        if match:
            current_val = float(match.group(1))
            current_unit = match.group(2).upper()
            total_val = float(match.group(3))
            total_unit = match.group(4).upper()
            
            current_bytes = self._convert_to_bytes(current_val, current_unit)
            total_bytes = self._convert_to_bytes(total_val, total_unit)
            
            return (current_bytes, total_bytes)
        
        # Try numeric format: "1234/5678" (might be file counts or bytes)
        match = re.search(r'(\d+)\s*/\s*(\d+)', data_str)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            # Assume bytes if values are large, otherwise might be file counts
            # For now, return as-is and let caller decide
            return (current, total)
        
        return None
    
    def _extract_phase_from_text(self, text: str) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from status text like 'Installing files'."""
        text_lower = text.lower()
        
        # Map common Wabbajack status texts to phases
        if 'download' in text_lower:
            return (InstallationPhase.DOWNLOAD, text)
        elif 'extract' in text_lower:
            return (InstallationPhase.EXTRACT, text)
        elif 'validat' in text_lower or 'hash' in text_lower:
            return (InstallationPhase.VALIDATE, text)
        elif 'install' in text_lower:
            return (InstallationPhase.INSTALL, text)
        elif 'prepar' in text_lower or 'configur' in text_lower:
            return (InstallationPhase.INITIALIZATION, text)
        elif 'finish' in text_lower or 'complet' in text_lower:
            return (InstallationPhase.FINALIZE, text)
        else:
            return (InstallationPhase.UNKNOWN, text)
    
    def _extract_speed_info(self, line: str) -> Optional[Tuple[str, float]]:
        """Extract speed information."""
        # Pattern: "267.3MB/s" or "at 45.2 MB/s" or "- 6.8MB/s"
        # Try pattern with dash separator first (common in status lines)
        match = re.search(r'-\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            speed_val = float(match.group(1))
            speed_unit = match.group(2).upper()
            speed_bytes = self._convert_to_bytes(speed_val, speed_unit)
            
            # Try to detect operation type from context
            operation = "unknown"
            line_lower = line.lower()
            if 'download' in line_lower:
                operation = "download"
            elif 'extract' in line_lower:
                operation = "extract"
            elif 'validat' in line_lower or 'hash' in line_lower:
                operation = "validate"
            
            return (operation, speed_bytes)
        
        # Pattern: "at 267.3MB/s" or "speed: 45.2 MB/s"
        match = re.search(r'(?:at|speed:?)\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            speed_val = float(match.group(1))
            speed_unit = match.group(2).upper()
            speed_bytes = self._convert_to_bytes(speed_val, speed_unit)
            
            # Try to detect operation type from context
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
        # Handle format: "6.8MB/s" or "6.8 MB/s" or "6.8MB/sec"
        match = re.search(r'(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s(?:ec)?', speed_str, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).upper()
            return self._convert_to_bytes(value, unit)
        return 0.0
    
    def _extract_completed_file(self, line: str) -> Optional[str]:
        """Extract filename from completion messages like 'Finished downloading filename.7z'."""
        # Pattern: "Finished downloading filename.7z. Hash: ..."
        # or "Finished downloading filename.7z"
        match = re.search(
            r'Finished\s+(?:downloading|extracting|validating|installing)\s+(.+?)(?:\.\s|\.$|\s+Hash:)',
            line,
            re.IGNORECASE
        )
        if match:
            filename = match.group(1).strip()
            # Remove any trailing dots or whitespace
            filename = filename.rstrip('. ')
            return filename
        return None
    
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


class ProgressStateManager:
    """
    Manages installation progress state by accumulating parsed information.
    
    This class maintains the current state of installation progress and
    updates it as new lines are parsed.
    """
    
    def __init__(self):
        """Initialize state manager."""
        self.state = InstallationProgress()
        self.parser = ProgressParser()
        self._file_history = {}
        self._wabbajack_entry_name = None
        self._synthetic_flag = "_synthetic_wabbajack"
        self._previous_phase = None  # Track phase changes to reset stale data
    
    def process_line(self, line: str) -> bool:
        """
        Process a line of output and update state.
        
        Args:
            line: Raw line from jackify-engine output
            
        Returns:
            True if state was updated, False otherwise
        """
        parsed = self.parser.parse_line(line)
        
        if not parsed.has_progress:
            return False
        
        updated = False
        
        # Update phase - detect phase changes to reset stale data
        phase_changed = False
        if parsed.phase and parsed.phase != self.state.phase:
            # Phase is changing - selectively reset stale data from previous phase
            previous_phase = self.state.phase
            
            # Only reset data sizes when transitioning FROM VALIDATE phase
            # Validation phase data sizes are from .wabbajack file and shouldn't persist
            if previous_phase == InstallationPhase.VALIDATE and not parsed.data_info:
                # Clear old validation data sizes (e.g., 339.0MB/339.1MB from .wabbajack)
                if self.state.data_total > 0:
                    self.state.data_processed = 0
                    self.state.data_total = 0
                    updated = True
            
            # Clear "Validating" phase name immediately when transitioning away from VALIDATE
            # This ensures stale phase name doesn't persist into download phase
            if previous_phase == InstallationPhase.VALIDATE:
                # Transitioning away from VALIDATE - always clear old phase_name
                # The new phase will either provide a new phase_name or get_phase_label() will derive it
                if self.state.phase_name and 'validat' in self.state.phase_name.lower():
                    self.state.phase_name = ""
                    updated = True
            
            phase_changed = True
            self._previous_phase = self.state.phase
            self.state.phase = parsed.phase
            updated = True
        elif parsed.phase:
            self.state.phase = parsed.phase
            updated = True
        
        # Update phase name - clear old phase name if phase changed but no new phase_name provided
        if parsed.phase_name:
            self.state.phase_name = parsed.phase_name
            updated = True
        elif phase_changed:
            # Phase changed but no new phase_name - clear old phase_name to prevent stale display
            # This ensures "Validating" doesn't stick when we transition to DOWNLOAD
            if self.state.phase_name and self.state.phase != InstallationPhase.VALIDATE:
                # Only clear if we're not in VALIDATE phase anymore
                self.state.phase_name = ""
                updated = True
        
        # CRITICAL: Always clear "Validating" phase_name if we're in DOWNLOAD phase
        # This catches cases where phase didn't change but we're downloading, or phase_name got set again
        if self.state.phase == InstallationPhase.DOWNLOAD:
            if self.state.phase_name and 'validat' in self.state.phase_name.lower():
                self.state.phase_name = ""
                updated = True
        
        # Update overall progress
        if parsed.overall_percent is not None:
            self.state.overall_percent = parsed.overall_percent
            updated = True
        
        # Update step information
        if parsed.step_info:
            self.state.phase_step, self.state.phase_max_steps = parsed.step_info
            updated = True
        
        # Update data information
        if parsed.data_info:
            self.state.data_processed, self.state.data_total = parsed.data_info
            # Calculate overall percent from data if not already set
            if self.state.data_total > 0 and self.state.overall_percent == 0.0:
                self.state.overall_percent = (self.state.data_processed / self.state.data_total) * 100.0
            updated = True

        # Update file counter (for Extracting phase)
        if parsed.file_counter:
            self.state.phase_step, self.state.phase_max_steps = parsed.file_counter
            updated = True
        
        # Update file progress
        if parsed.file_progress:
            # Skip hidden files (used only for carrying counter info)
            if hasattr(parsed.file_progress, '_hidden') and parsed.file_progress._hidden:
                # Counter already extracted above, don't add to active files
                return updated

            # Update texture conversion counter at state level if this is a texture conversion
            if hasattr(parsed.file_progress, '_texture_counter'):
                tex_current, tex_total = parsed.file_progress._texture_counter
                self.state.texture_conversion_current = tex_current
                self.state.texture_conversion_total = tex_total
                updated = True

            # Update BSA building counter at state level if this is a BSA building operation
            if hasattr(parsed.file_progress, '_bsa_counter'):
                bsa_current, bsa_total = parsed.file_progress._bsa_counter
                self.state.bsa_building_current = bsa_current
                self.state.bsa_building_total = bsa_total
                updated = True

            if parsed.file_progress.filename.lower().endswith('.wabbajack'):
                self._wabbajack_entry_name = parsed.file_progress.filename
                self._remove_synthetic_wabbajack()
                # Mark that we have a real .wabbajack entry to prevent synthetic ones
                self._has_real_wabbajack = True
            else:
                # CRITICAL: If we get a real archive file (not .wabbajack), remove all .wabbajack entries
                # This ensures .wabbajack entries disappear as soon as archive downloads start
                from jackify.shared.progress_models import OperationType
                if parsed.file_progress.operation == OperationType.DOWNLOAD:
                    self._remove_all_wabbajack_entries()
                    self._has_real_wabbajack = True  # Prevent re-adding
            self._augment_file_metrics(parsed.file_progress)
            # Don't add files that are already at 100% unless they're being updated
            # This prevents re-adding completed files
            existing_file = None
            for f in self.state.active_files:
                if f.filename == parsed.file_progress.filename:
                    existing_file = f
                    break
            
            # Don't add files that are already at 100% when first detected (downloads that already exist)
            # This prevents showing 1600 files instantly at 100% in the activity window
            if parsed.file_progress.percent >= 100.0 and not existing_file:
                # File completed before we ever saw it (already existed on disk)
                # Don't clutter the UI by showing it
                # Just update the phase step counts if applicable
                updated = True
            elif parsed.file_progress.percent >= 100.0:
                # File reached 100% that we were already tracking - show completion briefly
                parsed.file_progress.percent = 100.0
                parsed.file_progress.last_update = time.time()  # Set timestamp to NOW for minimum display
                self.state.add_file(parsed.file_progress)
                updated = True
            else:
                # File still in progress, add/update it normally
                self.state.add_file(parsed.file_progress)
                updated = True
        elif parsed.data_info:
            # CRITICAL: Remove .wabbajack entries as soon as archive download phase starts
            # Check if we're in "Downloading Mod Archives" phase or have real archive files downloading
            phase_name_lower = (parsed.phase_name or "").lower()
            message_lower = (parsed.message or "").lower()
            is_archive_phase = (
                'mod archives' in phase_name_lower or
                'downloading mod archives' in message_lower or
                (parsed.phase == InstallationPhase.DOWNLOAD and self._has_real_download_activity())
            )
            
            if is_archive_phase:
                # Archive download phase has started - remove all .wabbajack entries immediately
                self._remove_all_wabbajack_entries()
                self._has_real_wabbajack = True  # Prevent re-adding
            
            # Only create synthetic .wabbajack entry if we don't already have a real one
            if not getattr(self, '_has_real_wabbajack', False):
                if self._maybe_add_wabbajack_progress(parsed):
                    updated = True
        
        # Handle file completion messages
        if parsed.completed_filename:
            if not self.parser.should_display_file(parsed.completed_filename):
                parsed.completed_filename = None

        if parsed.completed_filename:
            # Try to find existing file in the list
            found_existing = False
            for file_prog in self.state.active_files:
                # Match by exact filename or by filename without path
                filename_match = (
                    file_prog.filename == parsed.completed_filename or
                    file_prog.filename.endswith(parsed.completed_filename) or
                    parsed.completed_filename in file_prog.filename
                )
                if filename_match:
                    file_prog.percent = 100.0
                    file_prog.last_update = time.time()  # Update timestamp for staleness check
                    updated = True
                    found_existing = True
                    break
            
            # If file wasn't in the list (completed too fast to get a progress line),
            # create a FileProgress entry so it appears briefly
            if not found_existing:
                from jackify.shared.progress_models import FileProgress, OperationType
                # Try to infer operation from context or default to DOWNLOAD
                operation = OperationType.DOWNLOAD
                if parsed.file_progress:
                    operation = parsed.file_progress.operation
                
                # Create a completed file entry so it appears for 0.5 seconds
                completed_file = FileProgress(
                    filename=parsed.completed_filename,
                    operation=operation,
                    percent=100.0,
                    current_size=0,
                    total_size=0
                    # speed defaults to -1.0 (not provided)
                )
                completed_file.last_update = time.time()
                self.state.add_file(completed_file)
                updated = True
        
        # Update speed information
        if parsed.speed_info:
            operation, speed = parsed.speed_info
            self.state.update_speed(operation, speed)
            updated = True
        
        # Update message
        if parsed.message:
            self.state.message = parsed.message
        
        # Update timestamp
        if updated:
            self.state.timestamp = time.time()
        
        # Always clean up completed files (not just when > 10)
        # This ensures completed files are removed promptly
        if updated:
            self.state.remove_completed_files()
        
        return updated
    
    def get_state(self) -> InstallationProgress:
        """Get current progress state."""
        return self.state
    
    def reset(self):
        """Reset progress state."""
        self.state = InstallationProgress()
        self._file_history = {}
        self._wabbajack_entry_name = None
        self._synthetic_flag = "_synthetic_wabbajack"
        self._has_real_wabbajack = False

    def _augment_file_metrics(self, file_progress: FileProgress):
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
        
        # Only compute speed if engine didn't provide one (sentinel value -1)
        # Prefer engine-reported speeds (including 0B/s) as they are more accurate
        computed_speed = 0.0  # Initialize default
        if file_progress.speed < 0:  # -1 means engine didn't provide speed
            computed_speed = 0.0
            if history and current_size:
                prev_bytes = history.get('bytes', 0)
                prev_time = history.get('time', now)
                delta_bytes = current_size - prev_bytes
                delta_time = now - prev_time

                # Require at least 1 second between updates for speed calculation
                # This prevents wildly inaccurate speeds from rapid progress bursts
                if delta_bytes >= 0 and delta_time >= 1.0:
                    computed_speed = delta_bytes / delta_time
                elif history.get('computed_speed'):
                    # Keep previous speed if time delta too small
                    computed_speed = history.get('computed_speed', 0.0)

            file_progress.speed = computed_speed  # Set to 0 or computed value
        else:
            # Engine provided speed, use it for history
            computed_speed = file_progress.speed
        
        if current_size or total_size:
            self._file_history[file_progress.filename] = {
                'bytes': current_size,
                'time': now,
                'total': total_size or (history.get('total') if history else None),
                'computed_speed': computed_speed,
            }
        elif history:
            # Preserve existing history even if new data missing
            self._file_history[file_progress.filename] = history

    def _maybe_add_wabbajack_progress(self, parsed: ParsedLine) -> bool:
        """Create a synthetic file entry for .wabbajack archive download."""
        if not parsed.data_info:
            return False
        if not parsed.data_info:
            return False
        
        current_bytes, total_bytes = parsed.data_info
        if total_bytes <= 0:
            return False
        
        # Check if we already have ANY .wabbajack entry (real or synthetic) - don't create duplicates
        for fp in self.state.active_files:
            if fp.filename.lower().endswith('.wabbajack'):
                # Update existing entry instead of creating new one
                synthetic_entry = fp
                if getattr(fp, self._synthetic_flag, False):
                    # It's synthetic - update it
                    percent = (current_bytes / total_bytes) * 100.0
                    synthetic_entry.percent = percent
                    synthetic_entry.current_size = current_bytes
                    synthetic_entry.total_size = total_bytes
                    synthetic_entry.last_update = time.time()
                    self._augment_file_metrics(synthetic_entry)
                    return True
                else:
                    # It's real - don't create synthetic
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
        # Use a consistent name - don't create multiple entries with different names
        if not self._wabbajack_entry_name:
            # Use display message as filename
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

    def _remove_synthetic_wabbajack(self):
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
    
    def _remove_all_wabbajack_entries(self):
        """Remove ALL .wabbajack entries (synthetic and real) when archive download phase starts."""
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
            # Also clear the wabbajack entry name to prevent re-adding
            self._wabbajack_entry_name = None

