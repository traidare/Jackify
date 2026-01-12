"""
File Progress List Widget

Displays a list of files currently being processed (downloaded, extracted, etc.)
with individual progress indicators.
R&D NOTE: This is experimental code for investigation purposes.
"""

from typing import Optional
import shiboken6
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, 
    QProgressBar, QHBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont

from jackify.shared.progress_models import FileProgress, OperationType
from ..shared_theme import JACKIFY_COLOR_BLUE

def _debug_log(message):
    """Log message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)


class SummaryProgressWidget(QWidget):
    """Widget showing summary progress for phases like Installing."""
    
    def __init__(self, phase_name: str, current_step: int, max_steps: int, parent=None):
        super().__init__(parent)
        self.phase_name = phase_name
        self.current_step = current_step
        self.max_steps = max_steps
        # Smooth interpolation for counter updates
        self._target_step = current_step
        self._target_max = max_steps
        self._display_step = current_step
        self._display_max = max_steps
        self._interpolation_timer = QTimer(self)
        self._interpolation_timer.timeout.connect(self._interpolate_counter)
        self._interpolation_timer.setInterval(16)  # ~60fps
        self._interpolation_timer.start()
        self._setup_ui()
        self._update_display()
    
    def _setup_ui(self):
        """Set up the UI for summary display."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Text label showing phase and count (no progress bar for cleaner display)
        self.text_label = QLabel()
        self.text_label.setStyleSheet("color: #ccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(self.text_label)
    
    def _interpolate_counter(self):
        """Smoothly interpolate counter display toward target values."""
        # Interpolate step
        step_diff = self._target_step - self._display_step
        if abs(step_diff) < 0.5:
            self._display_step = self._target_step
        else:
            # Smooth interpolation (20% per frame)
            self._display_step += step_diff * 0.2
        
        # Interpolate max (usually doesn't change, but handle it)
        max_diff = self._target_max - self._display_max
        if abs(max_diff) < 0.5:
            self._display_max = self._target_max
        else:
            self._display_max += max_diff * 0.2
        
        # Update display with interpolated values
        self._update_display()
    
    def _update_display(self):
        """Update the display with current progress."""
        # Use interpolated display values for smooth counter updates
        display_step = int(round(self._display_step))
        display_max = int(round(self._display_max))
        
        if display_max > 0:
            new_text = f"{self.phase_name} ({display_step}/{display_max})"
        else:
            new_text = f"{self.phase_name}"

        # Only update text if it changed (reduces repaints)
        if self.text_label.text() != new_text:
            self.text_label.setText(new_text)

    def update_progress(self, current_step: int, max_steps: int):
        """Update target values (display will smoothly interpolate)."""
        # Update targets (render loop will smoothly interpolate)
        self._target_step = current_step
        self._target_max = max_steps
        # Also update actual values for reference
        self.current_step = current_step
        self.max_steps = max_steps


class FileProgressItem(QWidget):
    """Widget representing a single file's progress."""
    
    def __init__(self, file_progress: FileProgress, parent=None):
        super().__init__(parent)
        self.file_progress = file_progress
        self._target_percent = file_progress.percent  # Target value for smooth animation
        self._current_display_percent = file_progress.percent  # Currently displayed value
        self._spinner_position = 0  # For custom indeterminate spinner animation (0-200 range for smooth wraparound)
        self._is_indeterminate = False  # Track if we're in indeterminate mode
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_progress)
        self._animation_timer.setInterval(16)  # ~60fps for smooth animation
        self._setup_ui()
        self._update_display()
    
    def _setup_ui(self):
        """Set up the UI for this file item."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        
        # Operation icon/indicator (simple text for now)
        operation_label = QLabel(self._get_operation_symbol())
        operation_label.setFixedWidth(20)
        operation_label.setAlignment(Qt.AlignCenter)
        operation_label.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-weight: bold;")
        layout.addWidget(operation_label)
        
        # Filename (truncated if too long)
        filename_label = QLabel(self._truncate_filename(self.file_progress.filename))
        filename_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filename_label.setToolTip(self.file_progress.filename)  # Full name in tooltip
        filename_label.setStyleSheet("color: #ccc; font-size: 11px;")
        layout.addWidget(filename_label, 1)
        self.filename_label = filename_label
        
        # Progress percentage (only show if we have valid progress data)
        percent_label = QLabel()
        percent_label.setFixedWidth(40)
        percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        percent_label.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(percent_label)
        self.percent_label = percent_label
        
        # Progress indicator: either progress bar (with %) or animated spinner (no %)
        progress_bar = QProgressBar()
        progress_bar.setFixedHeight(12)
        progress_bar.setFixedWidth(80)
        progress_bar.setTextVisible(False)  # Hide text, we have percent label

        # Apply stylesheet ONCE here instead of on every update
        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 2px;
                background-color: #1a1a1a;
            }}
            QProgressBar::chunk {{
                background-color: {JACKIFY_COLOR_BLUE};
                border-radius: 1px;
            }}
        """)

        layout.addWidget(progress_bar)
        self.progress_bar = progress_bar
    
    def _get_operation_symbol(self) -> str:
        """Get symbol for operation type."""
        symbols = {
            OperationType.DOWNLOAD: "↓",
            OperationType.EXTRACT: "↻",
            OperationType.VALIDATE: "✓",
            OperationType.INSTALL: "→",
        }
        return symbols.get(self.file_progress.operation, "•")
    
    def _truncate_filename(self, filename: str, max_length: int = 40) -> str:
        """Truncate filename if too long."""
        if len(filename) <= max_length:
            return filename
        return filename[:max_length-3] + "..."
    
    def _update_display(self):
        """Update the display with current progress."""
        # Check if this is a summary item (e.g., "Installing files (1234/5678)")
        is_summary = hasattr(self.file_progress, '_is_summary') and self.file_progress._is_summary

        # Check if progress bar should be hidden (e.g., "Installing Files: 234/35346")
        no_progress_bar = hasattr(self.file_progress, '_no_progress_bar') and self.file_progress._no_progress_bar

        # Update filename - DON'T truncate for install phase items
        # Only truncate for download phase to keep consistency there
        if 'Installing Files' in self.file_progress.filename or 'Converting Texture' in self.file_progress.filename or 'BSA:' in self.file_progress.filename:
            name_display = self.file_progress.filename  # Don't truncate
        else:
            name_display = self._truncate_filename(self.file_progress.filename)

        if not is_summary and not no_progress_bar:
            size_display = self.file_progress.size_display
            if size_display:
                name_display = f"{name_display} ({size_display})"

        self.filename_label.setText(name_display)
        self.filename_label.setToolTip(self.file_progress.filename)

        # For items with _no_progress_bar flag (e.g., "Installing Files: 234/35346")
        # Hide the progress bar and percentage - just show the text
        if no_progress_bar:
            self._animation_timer.stop()  # Stop animation for items without progress bars
            self.percent_label.setText("")  # No percentage
            self.progress_bar.setVisible(False)  # Hide progress bar
            return

        # Ensure progress bar is visible for other items
        self.progress_bar.setVisible(True)

        # For summary items, calculate progress from step/max
        if is_summary:
            summary_step = getattr(self.file_progress, '_summary_step', 0)
            summary_max = getattr(self.file_progress, '_summary_max', 0)

            if summary_max > 0:
                percent = (summary_step / summary_max) * 100.0
                # Update target for smooth animation
                self._target_percent = max(0, min(100, percent))
                
                # Start animation timer if not already running
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
                
                self.progress_bar.setRange(0, 100)
                # Progress bar value will be updated by animation timer
            else:
                # No max for summary - use custom animated spinner
                self._is_indeterminate = True
                self.percent_label.setText("")
                self.progress_bar.setRange(0, 100)  # Use determinate range for custom animation
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
            return

        # Check if this is a queued item (not yet started)
        # Queued items have total_size > 0 but percent == 0, current_size == 0, speed <= 0
        is_queued = (
            self.file_progress.total_size > 0 and
            self.file_progress.percent == 0 and
            self.file_progress.current_size == 0 and
            self.file_progress.speed <= 0
        )

        if is_queued:
            # Queued download - show "Queued" text with empty progress bar
            self._is_indeterminate = False
            self._animation_timer.stop()
            self.percent_label.setText("Queued")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            return

        # Check if we have meaningful progress data
        # For operations like BSA building, we may not have percent or size data
        has_meaningful_progress = (
            self.file_progress.percent > 0 or
            (self.file_progress.total_size > 0 and self.file_progress.current_size > 0) or
            (self.file_progress.speed > 0 and self.file_progress.percent >= 0)
        )

        # Use determinate mode if we have actual progress data, otherwise use custom animated spinner
        if has_meaningful_progress:
            # Normal progress mode
            self._is_indeterminate = False
            # Update target for smooth animation
            self._target_percent = max(0, self.file_progress.percent)

            # Start animation timer if not already running
            if not self._animation_timer.isActive():
                self._animation_timer.start()

            self.progress_bar.setRange(0, 100)
            # Progress bar value will be updated by animation timer
        else:
            # No progress data (e.g., texture conversions, BSA building) - use custom animated spinner
            self._is_indeterminate = True
            self.percent_label.setText("")  # Clear percent label
            self.progress_bar.setRange(0, 100)  # Use determinate range for custom animation
            # Start animation timer for custom spinner
            if not self._animation_timer.isActive():
                self._animation_timer.start()

    def _animate_progress(self):
        """Smoothly animate progress bar from current to target value, or animate spinner."""
        if self._is_indeterminate:
            # Custom indeterminate spinner animation
            # Use a bouncing/pulsing effect: position moves 0-100-0 smoothly
            # Increment by 4 units per frame for fast animation (full cycle in ~0.8s at 60fps)
            self._spinner_position = (self._spinner_position + 4) % 200

            # Create bouncing effect: 0->100->0
            if self._spinner_position < 100:
                display_value = self._spinner_position
            else:
                display_value = 200 - self._spinner_position

            self.progress_bar.setValue(display_value)
        else:
            # Normal progress animation
            # Calculate difference
            diff = self._target_percent - self._current_display_percent

            # If very close, snap to target and stop animation
            if abs(diff) < 0.1:
                self._current_display_percent = self._target_percent
                self._animation_timer.stop()
            else:
                # Smooth interpolation (ease-out for natural feel)
                # Move 20% of remaining distance per frame (~60fps = smooth)
                self._current_display_percent += diff * 0.2

            # Update display
            display_percent = max(0, min(100, self._current_display_percent))
            self.progress_bar.setValue(int(display_percent))

            # Update percentage label
            if self.file_progress.percent > 0:
                self.percent_label.setText(f"{display_percent:.0f}%")
            else:
                self.percent_label.setText("")
    
    def update_progress(self, file_progress: FileProgress):
        """Update with new progress data."""
        self.file_progress = file_progress
        self._update_display()
    
    def cleanup(self):
        """Clean up resources when widget is no longer needed."""
        if self._animation_timer.isActive():
            self._animation_timer.stop()


class FileProgressList(QWidget):
    """
    Widget displaying a list of files currently being processed.
    Shows individual progress for each file.
    """
    
    def __init__(self, parent=None):
        """
        Initialize file progress list.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._file_items: dict[str, FileProgressItem] = {}
        self._summary_widget: Optional[SummaryProgressWidget] = None
        self._last_phase: Optional[str] = None  # Track phase changes for transition messages
        self._transition_label: Optional[QLabel] = None  # Label for "Preparing..." message
        self._last_summary_time: float = 0.0  # Track when summary widget was last shown
        self._summary_hold_duration: float = 0.5  # Hold summary for minimum 0.5s to prevent flicker
        self._last_summary_update: float = 0.0  # Track last summary update for throttling
        self._summary_update_interval: float = 0.1  # Update summary every 100ms (simple throttling)
        
        self._setup_ui()
        # Set size policy to match Process Monitor - expand to fill available space
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
    def _setup_ui(self):
        """Set up the UI - match Process Monitor layout structure exactly."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)  # Match Process Monitor spacing (was 4, now 2)

        # Header row with CPU usage only (tab label replaces "[Activity]" header)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # CPU usage indicator (right-aligned)
        self.cpu_label = QLabel("")
        self.cpu_label.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 2px;")
        self.cpu_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addStretch()  # Push CPU label to the right
        header_layout.addWidget(self.cpu_label, 0)

        layout.addLayout(header_layout)
        
        # List widget for file items - match Process Monitor size constraints
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #222;
                border: 1px solid #444;
                border-radius: 4px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2a2a2a;
                padding: 2px;
            }
            QListWidget::item:selected {
                background-color: #2a2a2a;
            }
        """)
        # Match Process Monitor minimum size: QSize(300, 20)
        self.list_widget.setMinimumSize(QSize(300, 20))
        # Match Process Monitor - no maximum height constraint, expand to fill available space
        # The list will scroll if there are more items than can fit
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Match Process Monitor size policy - expand to fill available space
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.list_widget, stretch=1)  # Match Process Monitor stretch
        
        # Throttle timer for updates when there are many files
        import time
        self._last_update_time = 0.0

        # CPU usage tracking
        self._cpu_timer = QTimer(self)
        self._cpu_timer.timeout.connect(self._update_cpu_usage)
        self._cpu_timer.setInterval(2000)  # Update every 2 seconds
        self._last_cpu_percent = 0.0
        self._cpu_process_cache = None  # Cache the process object for better performance
        self._child_process_cache = {}  # Cache child Process objects by PID for persistent CPU tracking
    
    def update_files(self, file_progresses: list[FileProgress], current_phase: str = None, summary_info: dict = None):
        """
        Update the list with current file progresses.
        
        Args:
            file_progresses: List of FileProgress objects for active files
            current_phase: Optional phase name to display in header (e.g., "Downloading", "Extracting")
            summary_info: Optional dict with 'current_step' and 'max_steps' for summary display (e.g., Installing phase)
        """
        # Throttle updates to prevent UI freezing with many files
        # If we have many files (>50), throttle updates to every 100ms
        import time
        current_time = time.time()
        if len(file_progresses) > 50:
            if current_time - self._last_update_time < 0.1:  # 100ms throttle
                return  # Skip this update
            self._last_update_time = current_time
        
        # If we have summary info (e.g., Installing phase), show summary widget instead of file list
        if summary_info and not file_progresses:
            current_time = time.time()

            # Get new values
            current_step = summary_info.get('current_step', 0)
            max_steps = summary_info.get('max_steps', 0)
            phase_name = current_phase or "Installing files"

            # Check if summary widget already exists and is valid
            summary_widget_valid = self._summary_widget and shiboken6.isValid(self._summary_widget)
            if not summary_widget_valid:
                self._summary_widget = None

            # If widget exists, check if we should throttle the update
            if self._summary_widget:
                # Throttle updates to prevent flickering with rapidly changing counters
                if current_time - self._last_summary_update < self._summary_update_interval:
                    return  # Skip update, too soon

                # Update existing summary widget (no clearing needed)
                self._summary_widget.update_progress(current_step, max_steps)
                # Update phase name if it changed
                if self._summary_widget.phase_name != phase_name:
                    self._summary_widget.phase_name = phase_name
                    self._summary_widget._update_display()
                self._last_summary_update = current_time
                return

            # Widget doesn't exist - create it (only clear when creating new widget)
            # CRITICAL FIX: Remove all item widgets before clear() to prevent orphaned widgets
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item:
                    widget = self.list_widget.itemWidget(item)
                    if widget:
                        self.list_widget.removeItemWidget(item)
            self.list_widget.clear()
            self._file_items.clear()

            # Create new summary widget
            self._summary_widget = SummaryProgressWidget(phase_name, current_step, max_steps)
            summary_item = QListWidgetItem()
            summary_item.setSizeHint(self._summary_widget.sizeHint())
            summary_item.setData(Qt.UserRole, "__summary__")
            self.list_widget.addItem(summary_item)
            self.list_widget.setItemWidget(summary_item, self._summary_widget)
            self._last_summary_time = current_time
            self._last_summary_update = current_time

            return
        
        # Clear summary widget and transition label when showing file list
        # But only if enough time has passed to prevent flickering
        current_time = time.time()

        if self._summary_widget:
            # Hold summary widget for minimum duration to prevent rapid flickering
            if current_time - self._last_summary_time >= self._summary_hold_duration:
                # Remove summary widget from list
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item and item.data(Qt.UserRole) == "__summary__":
                        # CRITICAL FIX: Call removeItemWidget() before takeItem() to prevent orphaned widgets
                        widget = self.list_widget.itemWidget(item)
                        if widget:
                            self.list_widget.removeItemWidget(item)
                        self.list_widget.takeItem(i)
                        break
                self._summary_widget = None
            else:
                # Too soon to clear summary, keep it visible
                return

        # Clear transition label if it exists
        if self._transition_label:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item and item.data(Qt.UserRole) == "__transition__":
                    # CRITICAL FIX: Call removeItemWidget() before takeItem() to prevent orphaned widgets
                    widget = self.list_widget.itemWidget(item)
                    if widget:
                        self.list_widget.removeItemWidget(item)
                    self.list_widget.takeItem(i)
                    break
            self._transition_label = None
        
        if not file_progresses:
            # No files - check if this is a phase transition
            if current_phase and self._last_phase and current_phase != self._last_phase:
                # Phase changed - show transition message briefly
                self._show_transition_message(current_phase)
            else:
                # Show empty state but keep header stable
                # CRITICAL FIX: Remove all item widgets before clear() to prevent orphaned widgets
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item:
                        widget = self.list_widget.itemWidget(item)
                        if widget:
                            self.list_widget.removeItemWidget(item)
                self.list_widget.clear()
                self._file_items.clear()

            # Update last phase tracker
            if current_phase:
                self._last_phase = current_phase
            return
        
        # Determine phase from file operations if not provided
        if not current_phase and file_progresses:
            # Get the most common operation type
            operations = [fp.operation for fp in file_progresses if fp.operation != OperationType.UNKNOWN]
            if operations:
                operation_counts = {}
                for op in operations:
                    operation_counts[op] = operation_counts.get(op, 0) + 1
                most_common = max(operation_counts.items(), key=lambda x: x[1])[0]
                phase_map = {
                    OperationType.DOWNLOAD: "Downloading",
                    OperationType.EXTRACT: "Extracting",
                    OperationType.VALIDATE: "Validating",
                    OperationType.INSTALL: "Installing",
                }
                current_phase = phase_map.get(most_common, "")
        
        # Remove completed files
        # Build set of current item keys (using stable keys for counters)
        current_keys = set()
        for fp in file_progresses:
            if 'Installing Files:' in fp.filename:
                current_keys.add("__installing_files__")
            elif 'Converting Texture:' in fp.filename:
                base_name = fp.filename.split('(')[0].strip()
                current_keys.add(f"__texture_{base_name}__")
            elif fp.filename.startswith('BSA:'):
                bsa_name = fp.filename.split('(')[0].strip()
                current_keys.add(f"__bsa_{bsa_name}__")
            else:
                current_keys.add(fp.filename)
        
        for item_key in list(self._file_items.keys()):
            if item_key not in current_keys:
                # Find and remove the item
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item and item.data(Qt.UserRole) == item_key:
                        # CRITICAL FIX: Call removeItemWidget() before takeItem() to prevent orphaned widgets
                        widget = self.list_widget.itemWidget(item)
                        if widget:
                            self.list_widget.removeItemWidget(item)
                        self.list_widget.takeItem(i)
                        break
                del self._file_items[item_key]
        
        # Update or add files - maintain specific ordering
        # Use stable identifiers for special items (like "Installing Files: X/Y")
        for idx, file_progress in enumerate(file_progresses):
            # For items with changing counters in filename, use a stable key
            if 'Installing Files:' in file_progress.filename:
                item_key = "__installing_files__"
            elif 'Converting Texture:' in file_progress.filename:
                # Extract base filename for stable key
                base_name = file_progress.filename.split('(')[0].strip()
                item_key = f"__texture_{base_name}__"
            elif file_progress.filename.startswith('BSA:'):
                # Extract BSA filename for stable key
                bsa_name = file_progress.filename.split('(')[0].strip()
                item_key = f"__bsa_{bsa_name}__"
            else:
                # Use filename as key for regular files
                item_key = file_progress.filename
            
            if item_key in self._file_items:
                # Update existing widget - DO NOT reorder items (causes segfaults)
                # Reordering with takeItem/insertItem can delete widgets and cause crashes
                # Order is less important than stability - just update the widget in place
                item_widget = self._file_items[item_key]
                # CRITICAL: Check widget is still valid before updating
                if shiboken6.isValid(item_widget):
                    try:
                        item_widget.update_progress(file_progress)
                    except RuntimeError:
                        # Widget was deleted - remove from dict and create new one below
                        del self._file_items[item_key]
                        # Fall through to create new widget
                    else:
                        # Update successful - skip creating new widget
                        continue
                else:
                    # Widget invalid - remove from dict and create new one
                    del self._file_items[item_key]
                    # Fall through to create new widget
            # Create new widget (either because it didn't exist or was invalid)
            # CRITICAL: Use addItem instead of insertItem to avoid position conflicts
            # Order is less important than stability - addItem is safer than insertItem
            item_widget = FileProgressItem(file_progress)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, item_key)  # Use stable key
            self.list_widget.addItem(list_item)  # Use addItem for safety (avoids segfaults)
            self.list_widget.setItemWidget(list_item, item_widget)
            self._file_items[item_key] = item_widget

        # Update last phase tracker
        if current_phase:
            self._last_phase = current_phase

    def _show_transition_message(self, new_phase: str):
        """Show a brief 'Preparing...' message during phase transitions."""
        # CRITICAL FIX: Remove all item widgets before clear() to prevent orphaned widgets
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                widget = self.list_widget.itemWidget(item)
                if widget:
                    self.list_widget.removeItemWidget(item)
        self.list_widget.clear()
        self._file_items.clear()

        # Header removed - tab label provides context

        # Create or update transition label
        if self._transition_label is None or not shiboken6.isValid(self._transition_label):
            self._transition_label = QLabel()
            self._transition_label.setAlignment(Qt.AlignCenter)
            self._transition_label.setStyleSheet("color: #888; font-style: italic; padding: 20px;")

        self._transition_label.setText(f"Preparing {new_phase.lower()}...")

        # Add to list widget
        transition_item = QListWidgetItem()
        transition_item.setSizeHint(self._transition_label.sizeHint())
        transition_item.setData(Qt.UserRole, "__transition__")
        self.list_widget.addItem(transition_item)
        self.list_widget.setItemWidget(transition_item, self._transition_label)

        # Remove transition message after brief delay (will be replaced by actual content)
        # The next update_files call with actual content will clear this automatically

    def clear(self):
        """Clear all file items."""
        # CRITICAL FIX: Remove all item widgets before clear() to prevent orphaned widgets
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                widget = self.list_widget.itemWidget(item)
                if widget:
                    self.list_widget.removeItemWidget(item)
        self.list_widget.clear()
        self._file_items.clear()
        self._summary_widget = None
        self._transition_label = None
        self._last_phase = None
        # Header removed - tab label provides context
        # Stop CPU timer and clear CPU label
        self.stop_cpu_tracking()
        self.cpu_label.setText("")

    def start_cpu_tracking(self):
        """Start tracking CPU usage."""
        if not self._cpu_timer.isActive():
            # Initialize process and take first measurement to establish baseline
            try:
                import psutil
                import os
                self._cpu_process_cache = psutil.Process(os.getpid())
                # First call with interval to establish baseline
                self._cpu_process_cache.cpu_percent(interval=0.1)
                # Cache child processes
                self._child_process_cache = {}
                for child in self._cpu_process_cache.children(recursive=True):
                    try:
                        child.cpu_percent(interval=0.1)
                        self._child_process_cache[child.pid] = child
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception:
                pass

            self._cpu_timer.start()
            self._update_cpu_usage()  # Update immediately after baseline

    def stop_cpu_tracking(self):
        """Stop tracking CPU usage."""
        if self._cpu_timer.isActive():
            self._cpu_timer.stop()

    def update_or_add_item(self, item_id: str, label: str, progress: float = 0.0):
        """
        Add or update a single status item in the Activity window.
        Useful for simple status messages like "Downloading...", "Extracting...", etc.
        
        Args:
            item_id: Unique identifier for this item
            label: Display label for the item
            progress: Progress percentage (0-100), or 0 for indeterminate
        """
        from jackify.shared.progress_models import FileProgress, OperationType
        
        # Create a FileProgress object for this status item
        file_progress = FileProgress(
            filename=label,
            operation=OperationType.DOWNLOAD if progress > 0 else OperationType.UNKNOWN,
            percent=progress,
            current_size=0,
            total_size=0
        )
        
        # Use update_files with a single-item list
        self.update_files([file_progress], current_phase=None)

    def _update_cpu_usage(self):
        """
        Update CPU usage display with Jackify-related processes.

        Shows total CPU usage across all cores as a percentage of system capacity.
        E.g., on an 8-core system:
        - 100% = using all 8 cores fully
        - 50% = using 4 cores fully (or 8 cores at half capacity)
        - 12.5% = using 1 core fully
        """
        try:
            import psutil
            import os
            import sys

            # Get or create process cache
            if self._cpu_process_cache is None:
                self._cpu_process_cache = psutil.Process(os.getpid())

            # Get current process CPU (Jackify GUI)
            # cpu_percent() returns percentage relative to one core
            # We need to divide by num_cpus to get system-wide percentage
            num_cpus = psutil.cpu_count()

            main_cpu_raw = self._cpu_process_cache.cpu_percent(interval=None)
            main_cpu = main_cpu_raw / num_cpus
            total_cpu = main_cpu

            # Add CPU usage from ALL child processes recursively
            # This includes jackify-engine, texconv.exe, wine processes, etc.
            child_count = 0
            child_cpu_sum = 0.0
            try:
                children = self._cpu_process_cache.children(recursive=True)
                current_child_pids = set()

                for child in children:
                    try:
                        current_child_pids.add(child.pid)

                        # Check if this is a new process we haven't cached
                        if child.pid not in self._child_process_cache:
                            # Cache new process and establish baseline
                            child.cpu_percent(interval=0.1)
                            self._child_process_cache[child.pid] = child
                            # Skip this iteration since baseline was just set
                            continue

                        # Use cached process object for consistent cpu_percent tracking
                        cached_child = self._child_process_cache[child.pid]
                        child_cpu_raw = cached_child.cpu_percent(interval=None)
                        child_cpu = child_cpu_raw / num_cpus
                        total_cpu += child_cpu
                        child_count += 1
                        child_cpu_sum += child_cpu_raw
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # Clean up cache for processes that no longer exist
                dead_pids = set(self._child_process_cache.keys()) - current_child_pids
                for pid in dead_pids:
                    del self._child_process_cache[pid]

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Also search for ALL Jackify-related processes by name/cmdline
            # This catches processes that may not be direct children (shell launches, Proton/wine wrappers, etc.)
            # NOTE: Since children() is recursive, this typically only finds Proton spawn cases.
            tracked_pids = {self._cpu_process_cache.pid}  # Avoid double-counting
            tracked_pids.update(current_child_pids)

            extra_count = 0
            extra_cpu_sum = 0.0
            try:
                for proc in psutil.process_iter(['name', 'pid', 'cmdline']):
                    try:
                        if proc.pid in tracked_pids:
                            continue

                        proc_name = proc.info.get('name', '').lower()
                        cmdline = proc.info.get('cmdline', [])
                        cmdline_str = ' '.join(cmdline).lower() if cmdline else ''

                        # Match Jackify-related process names (include Proton/wine wrappers)
                        # Include all tools that jackify-engine uses during installation
                        jackify_names = [
                            'jackify-engine',        # Main engine
                            'texconv',               # Texture conversion
                            'texdiag',               # Texture diagnostics
                            'directxtex',            # DirectXTex helper binaries
                            'texconv_jackify',       # Bundled texconv build
                            'texdiag_jackify',       # Bundled texdiag build
                            'directxtex_jackify',    # Bundled DirectXTex build
                            '7z',                    # Archive extraction (7z)
                            '7zz',                   # Archive extraction (7zz)
                            'bsarch',                # BSA archive tool
                            'wine',                  # Proton/wine launcher
                            'wine64',                # Proton/wine 64-bit launcher
                            'wine64-preloader',      # Proton/wine preloader
                            'steam-run',             # Steam runtime wrapper
                            'proton',                # Proton launcher scripts
                        ]

                        # Check process name
                        is_jackify = any(name in proc_name for name in jackify_names)

                        # Check command line (e.g., wine running jackify tools, or paths containing jackify)
                        if not is_jackify and cmdline_str:
                            # Check for jackify tool names in command line (catches wine running texconv.exe, etc.)
                            # This includes: texconv, texconv.exe, texdiag, 7z, 7zz, bsarch, jackify-engine
                            is_jackify = any(name in cmdline_str for name in jackify_names)
                            
                            # Also check for .exe variants (wine runs .exe files)
                            if not is_jackify:
                                exe_names = [f'{name}.exe' for name in jackify_names]
                                is_jackify = any(exe_name in cmdline_str for exe_name in exe_names)
                            
                            # Also check if command line contains jackify paths
                            if not is_jackify:
                                is_jackify = 'jackify' in cmdline_str and any(
                                    tool in cmdline_str for tool in ['engine', 'tools', 'binaries']
                                )

                        if is_jackify:
                            # Check if this is a new process we haven't cached
                            if proc.pid not in self._child_process_cache:
                                # Establish baseline for new process and cache it
                                proc.cpu_percent(interval=0.1)
                                self._child_process_cache[proc.pid] = proc
                                # Skip this iteration since baseline was just set
                                continue

                            # Use cached process object
                            cached_proc = self._child_process_cache[proc.pid]
                            proc_cpu_raw = cached_proc.cpu_percent(interval=None)
                            proc_cpu = proc_cpu_raw / num_cpus
                            total_cpu += proc_cpu
                            tracked_pids.add(proc.pid)
                            extra_count += 1
                            extra_cpu_sum += proc_cpu_raw

                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, TypeError):
                        pass
            except Exception:
                pass

            # Smooth the value slightly to reduce jitter (less aggressive than before)
            if self._last_cpu_percent > 0:
                total_cpu = (self._last_cpu_percent * 0.3) + (total_cpu * 0.7)
            self._last_cpu_percent = total_cpu

            # Always show CPU percentage when tracking is active
            # Cap at 100% for display (shouldn't exceed but just in case)
            display_percent = min(100.0, total_cpu)

            if display_percent >= 0.1:
                self.cpu_label.setText(f"CPU: {display_percent:.0f}%")
            else:
                # Show 0% instead of hiding to indicate tracking is active
                self.cpu_label.setText("CPU: 0%")

        except Exception as e:
            # Show error indicator if tracking fails
            import sys
            print(f"CPU tracking error: {e}", file=sys.stderr)
            self.cpu_label.setText("")


