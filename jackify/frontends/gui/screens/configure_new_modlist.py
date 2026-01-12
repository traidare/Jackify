"""
ConfigureNewModlistScreen for Jackify GUI
"""
import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QCheckBox, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject
from PySide6.QtGui import QPixmap, QTextCursor
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
# Progress reporting components
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.shared.progress_models import InstallationPhase, InstallationProgress
import os
import subprocess
import sys
import threading
import time
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
import traceback
import signal
from jackify.backend.core.modlist_operations import get_jackify_engine_path
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.services.api_key_service import APIKeyService
from jackify.backend.services.resolution_service import ResolutionService
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from PySide6.QtWidgets import QApplication
from jackify.frontends.gui.services.message_service import MessageService
from jackify.shared.resolution_utils import get_resolution_fallback

logger = logging.getLogger(__name__)

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, cli_path, game_type, project_root, log_path, mode='list-modlists', modlist_name=None, install_dir=None, download_dir=None):
        super().__init__()
        self.cli_path = cli_path
        self.game_type = game_type
        self.project_root = project_root
        self.log_path = log_path
        self.mode = mode
        self.modlist_name = modlist_name
        self.install_dir = install_dir
        self.download_dir = download_dir
    def run(self):
        # CRITICAL: Use safe Python executable to prevent AppImage recursive spawning
        from jackify.backend.handlers.subprocess_utils import get_safe_python_executable
        python_exe = get_safe_python_executable()
        
        if self.mode == 'list-modlists':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--list-modlists', '--game-type', self.game_type]
        elif self.mode == 'install':
            cmd = [python_exe, self.cli_path, '--install-modlist', '--install', '--modlist-name', self.modlist_name, '--install-dir', self.install_dir, '--download-dir', self.download_dir, '--game-type', self.game_type]
        else:
            self.result.emit([], '[ModlistFetchThread] Unknown mode')
            return
        try:
            with open(self.log_path, 'a') as logf:
                logf.write(f"\n[Modlist Fetch CMD] {cmd}\n")
                # Use clean subprocess environment to prevent AppImage variable inheritance
                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                env = get_clean_subprocess_env()
                proc = subprocess.Popen(cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                stdout, stderr = proc.communicate()
                logf.write(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n")
                if proc.returncode == 0:
                    modlist_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
                    self.result.emit(modlist_ids, '')
                else:
                    self.result.emit([], stderr)
        except Exception as e:
            self.result.emit([], str(e))

class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for item in items:
            QListWidgetItem(item, self.list_widget)
        layout.addWidget(self.list_widget)
        self.selected_item = None
        self.list_widget.itemClicked.connect(self.on_item_clicked)
    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()

class ConfigureNewModlistScreen(QWidget):
    resize_request = Signal(str)
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        debug_print("DEBUG: ConfigureNewModlistScreen __init__ called")
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}
        
        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()

        # Path for workflow log
        self.refresh_paths()

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True

        # Time tracking for workflow completion
        self._workflow_start_time = None

        # Initialize progress reporting components
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.progress_indicator.set_status("Ready to configure", 0)
        self.file_progress_list = FileProgressList()

        # Create "Show Details" checkbox
        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)  # Start collapsed
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        # Title (no logo)
        title = QLabel("<b>Configure New Modlist</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to configure a newly installed modlist in Jackify. "
            "Set up your Steam shortcut, restart Steam, and complete post-install configuration."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px; line-height: 1.2;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)  # Force compact height for description
        header_layout.addWidget(desc)
        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)  # Match other screens
        if self.debug:
            header_widget.setStyleSheet("border: 2px solid pink;")
            header_widget.setToolTip("HEADER_SECTION")
        main_overall_vbox.addWidget(header_widget)

        # --- Upper section: user-configurables (left) + process monitor (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)
        # Left: user-configurables (form and controls)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        # --- [Options] header (moved here for alignment) ---
        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;")
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        user_config_vbox.addWidget(options_header)
        # --- Install/Downloads Dir/API Key (reuse Tuxborn style) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Reduced from 8 to 6 for better readability
        form_grid.setContentsMargins(0, 0, 0, 0)
        # Modlist Name (NEW FIELD)
        modlist_name_label = QLabel("Modlist Name:")
        self.modlist_name_edit = QLineEdit()
        self.modlist_name_edit.setMaximumHeight(25)  # Force compact height
        form_grid.addWidget(modlist_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.modlist_name_edit, 0, 1)
        # Install Dir
        install_dir_label = QLabel("ModOrganizer.exe Path:")
        self.install_dir_edit = QLineEdit("/path/to/Modlist/ModOrganizer.exe")
        self.install_dir_edit.setMaximumHeight(25)  # Force compact height
        browse_install_btn = QPushButton("Browse")
        browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)
        # --- Resolution Dropdown ---
        resolution_label = QLabel("Resolution:")
        self.resolution_combo = QComboBox()
        self.resolution_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.resolution_combo.addItem("Leave unchanged")
        self.resolution_combo.addItems([
            "1280x720",
            "1280x800 (Steam Deck)",
            "1366x768",
            "1440x900",
            "1600x900",
            "1600x1200",
            "1680x1050",
            "1920x1080",
            "1920x1200",
            "2048x1152",
            "2560x1080",
            "2560x1440",
            "2560x1600",
            "3440x1440",
            "3840x1600",
            "3840x2160",
            "3840x2400",
            "5120x1440",
            "5120x2160",
            "7680x4320"
        ])
        form_grid.addWidget(resolution_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        
        # Load saved resolution if available
        saved_resolution = self.resolution_service.get_saved_resolution()
        is_steam_deck = False
        try:
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    if 'steamdeck' in f.read().lower():
                        is_steam_deck = True
        except Exception:
            pass
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
            debug_print(f"DEBUG: Loaded saved resolution: {saved_resolution} (index: {resolution_index})")
        elif is_steam_deck:
            # Set default to 1280x800 (Steam Deck)
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            if "1280x800 (Steam Deck)" in combo_items:
                self.resolution_combo.setCurrentIndex(combo_items.index("1280x800 (Steam Deck)"))
            else:
                self.resolution_combo.setCurrentIndex(0)
        # Otherwise, default is 'Leave unchanged' (index 0)
        
        # Horizontal layout for resolution dropdown and auto-restart checkbox
        resolution_and_restart_layout = QHBoxLayout()
        resolution_and_restart_layout.setSpacing(12)
        
        # Resolution dropdown (made smaller)
        self.resolution_combo.setMaximumWidth(280)  # Constrain width but keep aesthetically pleasing
        resolution_and_restart_layout.addWidget(self.resolution_combo)
        
        # Add stretch to push checkbox to the right
        resolution_and_restart_layout.addStretch()
        
        # Auto-accept Steam restart checkbox (right-aligned)
        self.auto_restart_checkbox = QCheckBox("Auto-accept Steam restart")
        self.auto_restart_checkbox.setChecked(False)  # Always default to unchecked per session
        self.auto_restart_checkbox.setToolTip("When checked, Steam restart dialog will be automatically accepted, allowing unattended configuration")
        resolution_and_restart_layout.addWidget(self.auto_restart_checkbox)
        
        # Update the form grid to use the combined layout
        form_grid.addLayout(resolution_and_restart_layout, 2, 1)
        
        form_section_widget = QWidget()
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form_section_widget.setLayout(form_grid)
        form_section_widget.setMinimumHeight(120)  # Reduced to match compact form
        form_section_widget.setMaximumHeight(240)  # Increased to show resolution dropdown
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Configuration")
        btn_row.addWidget(self.start_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_and_cleanup)
        btn_row.addWidget(cancel_btn)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")
        # Right: Tabbed interface with Activity and Process Monitor
        # Both tabs are always available, user can switch between them
        self.process_monitor = QTextEdit()
        self.process_monitor.setReadOnly(True)
        self.process_monitor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.process_monitor.setMinimumSize(QSize(300, 20))
        self.process_monitor.setStyleSheet(f"background: #222; color: {JACKIFY_COLOR_BLUE}; font-family: monospace; font-size: 11px; border: 1px solid #444;")
        self.process_monitor_heading = QLabel("<b>[Process Monitor]</b>")
        self.process_monitor_heading.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; margin-bottom: 2px;")
        self.process_monitor_heading.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        process_vbox = QVBoxLayout()
        process_vbox.setContentsMargins(0, 0, 0, 0)
        process_vbox.setSpacing(2)
        process_vbox.addWidget(self.process_monitor_heading)
        process_vbox.addWidget(self.process_monitor)
        process_monitor_widget = QWidget()
        process_monitor_widget.setLayout(process_vbox)
        process_monitor_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.debug:
            process_monitor_widget.setStyleSheet("border: 2px solid purple;")
            process_monitor_widget.setToolTip("PROCESS_MONITOR")
        self.process_monitor_widget = process_monitor_widget

        # Set up File Progress List (Activity tab)
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create tab widget to hold both Activity and Process Monitor
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.activity_tabs.setContentsMargins(0, 0, 0, 0)
        self.activity_tabs.setDocumentMode(False)
        self.activity_tabs.setTabPosition(QTabWidget.North)
        if self.debug:
            self.activity_tabs.setStyleSheet("border: 2px solid cyan;")
            self.activity_tabs.setToolTip("ACTIVITY_TABS")

        # Add both widgets as tabs
        self.activity_tabs.addTab(self.file_progress_list, "Activity")
        self.activity_tabs.addTab(process_monitor_widget, "Process Monitor")

        upper_hbox.addWidget(user_config_widget, stretch=11)
        upper_hbox.addWidget(self.activity_tabs, stretch=9)
        upper_hbox.setAlignment(Qt.AlignTop)
        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy for consistent height
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_section_widget.setMaximumHeight(280)  # Increased to show resolution dropdown
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)

        # Status banner with progress indicator and "Show details" toggle
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)  # Compact height
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)

        # Console output area (shown when "Show details" is checked)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(50)
        self.console.setMaximumHeight(1000)
        self.console.setFontFamily('monospace')
        self.console.setVisible(False)  # Hidden by default (compact mode)
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")

        # Create a container that holds console + button row with proper spacing
        console_and_buttons_widget = QWidget()
        console_and_buttons_layout = QVBoxLayout()
        console_and_buttons_layout.setContentsMargins(0, 0, 0, 0)
        console_and_buttons_layout.setSpacing(8)

        console_and_buttons_layout.addWidget(self.console, stretch=1)
        console_and_buttons_layout.addWidget(btn_row_widget)

        console_and_buttons_widget.setLayout(console_and_buttons_layout)
        console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        console_and_buttons_widget.setFixedHeight(50)  # Lock to button row height when console is hidden
        if self.debug:
            console_and_buttons_widget.setStyleSheet("border: 2px solid lightblue;")
            console_and_buttons_widget.setToolTip("CONSOLE_AND_BUTTONS_CONTAINER")
        # Add without stretch to prevent squashing upper section
        main_overall_vbox.addWidget(console_and_buttons_widget)

        # Store references for toggle functionality
        self.console_and_buttons_widget = console_and_buttons_widget
        self.console_and_buttons_layout = console_and_buttons_layout
        self.main_overall_vbox = main_overall_vbox

        self.setLayout(main_overall_vbox)

        # --- Process Monitor (right) ---
        self.process = None
        self.log_timer = None
        self.last_log_pos = 0
        # --- Process Monitor Timer ---
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.update_top_panel)
        self.top_timer.start(2000)
        # --- Start Configuration button ---
        self.start_btn.clicked.connect(self.validate_and_start_configure)
        
        # Initialize empty controls list - will be populated after UI is built
        self._actionable_controls = []
        
        # Now collect all actionable controls after UI is fully built
        self._collect_actionable_controls()

    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # Form fields
            self.modlist_name_edit,
            self.install_dir_edit,
            # Resolution controls
            self.resolution_combo,
            # Checkboxes  
            self.auto_restart_checkbox,
        ]

    def _disable_controls_during_operation(self):
        """Disable all actionable controls during configure operations (except Cancel)"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(False)

    def _enable_controls_after_operation(self):
        """Re-enable all actionable controls after configure operations complete"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(True)

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'Configure_New_Modlist_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def resizeEvent(self, event):
        """Handle window resize to prioritize form over console"""
        super().resizeEvent(event)
        self._adjust_console_for_form_priority()

    def _adjust_console_for_form_priority(self):
        """Console now dynamically fills available space with stretch=1, no manual calculation needed"""
        # The console automatically fills remaining space due to stretch=1 in the layout
        # Remove any fixed height constraints to allow natural stretching
        self.console.setMaximumHeight(16777215)  # Reset to default maximum
        self.console.setMinimumHeight(50)  # Keep minimum height for usability

    def _setup_scroll_tracking(self):
        """Set up scroll tracking for professional auto-scroll behavior"""
        scrollbar = self.console.verticalScrollBar()
        scrollbar.sliderPressed.connect(self._on_scrollbar_pressed)
        scrollbar.sliderReleased.connect(self._on_scrollbar_released)
        scrollbar.valueChanged.connect(self._on_scrollbar_value_changed)

    def _on_scrollbar_pressed(self):
        """User started manually scrolling"""
        self._user_manually_scrolled = True

    def _on_scrollbar_released(self):
        """User finished manually scrolling"""
        self._user_manually_scrolled = False

    def _on_scrollbar_value_changed(self):
        """Track if user is at bottom of scroll area"""
        scrollbar = self.console.verticalScrollBar()
        # Use tolerance to account for rounding and rapid updates
        self._was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1
        
        # If user manually scrolls to bottom, reset manual scroll flag
        if self._was_at_bottom and self._user_manually_scrolled:
            # Small delay to allow user to scroll away if they want
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._reset_manual_scroll_if_at_bottom)
    
    def _reset_manual_scroll_if_at_bottom(self):
        """Reset manual scroll flag if user is still at bottom after delay"""
        scrollbar = self.console.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 1:
            self._user_manually_scrolled = False

    def _on_show_details_toggled(self, checked):
        """Handle Show Details checkbox toggle"""
        self._toggle_console_visibility(checked)

    def _toggle_console_visibility(self, is_checked):
        """Toggle console visibility and window size"""
        main_window = None
        try:
            parent = self.parent()
            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            if parent and isinstance(parent, QMainWindow):
                main_window = parent
        except Exception:
            pass

        if is_checked:
            # Show console
            self.console.setVisible(True)
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            # Allow expansion when console is visible
            if hasattr(self, 'console_and_buttons_widget'):
                self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.console_and_buttons_widget.setMinimumHeight(0)
                self.console_and_buttons_widget.setMaximumHeight(16777215)
                self.console_and_buttons_widget.updateGeometry()

            # Stop CPU tracking when showing console
            self.file_progress_list.stop_cpu_tracking()

            # Expand window
            if main_window:
                try:
                    from PySide6.QtCore import QSize
                    # On Steam Deck, keep fullscreen; on other systems, set normal window state
                    if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                        main_window.showNormal()
                    main_window.setMaximumHeight(16777215)
                    main_window.setMinimumHeight(0)
                    expanded_min = 900
                    current_size = main_window.size()
                    target_height = max(expanded_min, 900)
                    main_window.setMinimumHeight(expanded_min)
                    main_window.resize(current_size.width(), target_height)
                    self.main_overall_vbox.invalidate()
                    self.updateGeometry()
                except Exception:
                    pass
        else:
            # Hide console
            self.console.setVisible(False)
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

            # Lock height when console is hidden
            if hasattr(self, 'console_and_buttons_widget'):
                self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.console_and_buttons_widget.setFixedHeight(50)
                self.console_and_buttons_widget.updateGeometry()

            # CPU tracking will start when user clicks "Start Configuration", not here
            # (Removed to avoid blocking showEvent)

            # Collapse window
            if main_window:
                try:
                    from PySide6.QtCore import QSize
                    # Only set minimum size - DO NOT RESIZE
                    # On Steam Deck, keep fullscreen; on other systems, set normal window state
                    if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                        main_window.showNormal()
                    main_window.setMaximumSize(QSize(16777215, 16777215))
                    set_responsive_minimum(main_window, min_width=960, min_height=420)
                    # DO NOT resize - let window stay at current size
                except Exception:
                    pass

    def _handle_progress_update(self, text):
        """Handle progress updates - update console, activity window, and progress indicator"""
        # Always append to console
        self._safe_append_text(text)

        # Parse the message to update UI widgets
        message_lower = text.lower()

        # Update progress indicator based on key status messages
        if "creating steam shortcut" in message_lower:
            self.progress_indicator.set_status("Creating Steam shortcut...", 10)
        elif "restarting steam" in message_lower or "restart steam" in message_lower:
            self.progress_indicator.set_status("Restarting Steam...", 20)
        elif "steam restart" in message_lower and "success" in message_lower:
            self.progress_indicator.set_status("Steam restarted successfully", 30)
        elif "creating proton prefix" in message_lower or "prefix creation" in message_lower:
            self.progress_indicator.set_status("Creating Proton prefix...", 50)
        elif "prefix created" in message_lower or "prefix creation" in message_lower and "success" in message_lower:
            self.progress_indicator.set_status("Proton prefix created", 70)
        elif "applying curated registry" in message_lower or "registry" in message_lower:
            self.progress_indicator.set_status("Applying registry files...", 75)
        elif "installing wine components" in message_lower or "wine component" in message_lower:
            self.progress_indicator.set_status("Installing wine components...", 80)
        elif "dotnet" in message_lower and "fix" in message_lower:
            self.progress_indicator.set_status("Applying dotnet fixes...", 85)
        elif "setting ownership" in message_lower or "ownership and permissions" in message_lower:
            self.progress_indicator.set_status("Setting permissions...", 90)
        elif "verifying" in message_lower:
            self.progress_indicator.set_status("Verifying setup...", 95)
        elif "steam integration complete" in message_lower or "configuration complete" in message_lower:
            self.progress_indicator.set_status("Configuration complete", 100)

        # Update activity window with generic configuration status
        # Only update if message contains meaningful progress (not blank lines or separators)
        if text.strip() and not text.strip().startswith('='):
            # Show generic "Configuring modlist..." in activity window
            self.file_progress_list.update_files(
                [],
                current_phase="Configuring",
                summary_info={"current": 1, "total": 1, "label": "Setting up modlist"}
            )

    def _safe_append_text(self, text):
        """Append text with professional auto-scroll behavior"""
        # Write all messages to log file
        self._write_to_log_file(text)

        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance

        # Add the text
        self.console.append(text)

        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _write_to_log_file(self, message):
        """Write message to workflow log file with timestamp"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.modlist_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Logging should never break the workflow
            pass

    def browse_install_dir(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select ModOrganizer.exe", os.path.expanduser("~"), "ModOrganizer.exe (ModOrganizer.exe)")
        if file:
            self.install_dir_edit.setText(file)

    def go_back(self):
        """Navigate back to main menu and restore window size"""
        # Emit collapse signal to restore compact mode
        self.resize_request.emit('collapse')

        # Restore window size before navigating away
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                from ..utils import apply_window_size_and_position

                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass

        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        # Stop CPU tracking if active
        if hasattr(self, 'file_progress_list'):
            self.file_progress_list.stop_cpu_tracking()

        # Clean up automated prefix thread if running
        if hasattr(self, 'automated_prefix_thread') and self.automated_prefix_thread.isRunning():
            self.automated_prefix_thread.terminate()
            self.automated_prefix_thread.wait(1000)

        # Clean up configuration thread if running
        if hasattr(self, 'config_thread') and self.config_thread.isRunning():
            self.config_thread.terminate()
            self.config_thread.wait(1000)

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        self.go_back()

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Ensure initial collapsed layout each time this screen is opened
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            # Force collapsed state
            self._toggle_console_visibility(False)
        except Exception as e:
            # If initial collapse fails, log but don't crash
            print(f"Warning: Failed to set initial collapsed state: {e}")

    def update_top_panel(self):
        try:
            result = subprocess.run([
                "ps", "-eo", "pcpu,pmem,comm,args"
            ], stdout=subprocess.PIPE, text=True, timeout=2)
            lines = result.stdout.splitlines()
            header = "CPU%\tMEM%\tCOMMAND"
            filtered = [header]
            process_rows = []
            for line in lines[1:]:
                line_lower = line.lower()
                # Include jackify-engine and related heavy processes
                heavy_processes = (
                    "jackify-engine" in line_lower or "7zz" in line_lower or 
                    "texconv" in line_lower or "wine" in line_lower or 
                    "wine64" in line_lower or "protontricks" in line_lower
                )
                # Include Python processes running configure-modlist command
                configure_processes = (
                    "python" in line_lower and "configure-modlist" in line_lower
                )
                # Include QProcess processes that might be configuration-related
                qprocess_config = (
                    hasattr(self, 'config_process') and 
                    self.config_process and 
                    self.config_process.state() == QProcess.Running and
                    ("python" in line_lower or "jackify" in line_lower)
                )
                
                if (heavy_processes or configure_processes or qprocess_config) and "jackify-gui.py" not in line_lower:
                    cols = line.strip().split(None, 3)
                    if len(cols) >= 3:
                        process_rows.append(cols)
            process_rows.sort(key=lambda x: float(x[0]), reverse=True)
            for cols in process_rows:
                filtered.append('\t'.join(cols))
            if len(filtered) == 1:
                filtered.append("[No Jackify-related processes found]")
            self.process_monitor.setPlainText('\n'.join(filtered))
        except Exception as e:
            self.process_monitor.setPlainText(f"[process info unavailable: {e}]")

    def _check_protontricks(self):
        """Check if protontricks is available before critical operations"""
        try:
            if self.protontricks_service.is_bundled_mode():
                return True

            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            
            if not is_installed:
                # Show protontricks error dialog
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                
                if result == QDialog.Rejected:
                    return False
                
                # Re-check after dialog
                is_installed, _, _ = self.protontricks_service.detect_protontricks(use_cache=False)
                return is_installed
            
            return True
            
        except Exception as e:
            print(f"Error checking protontricks: {e}")
            from jackify.frontends.gui.services.message_service import MessageService
            MessageService.warning(self, "Protontricks Check Failed", 
                                 f"Unable to verify protontricks installation: {e}\n\n"
                                 "Continuing anyway, but some features may not work correctly.")
            return True  # Continue anyway

    def validate_and_start_configure(self):
        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Validate ModOrganizer.exe path
        mo2_path = self.install_dir_edit.text().strip()
        from jackify.frontends.gui.services.message_service import MessageService
        if not mo2_path:
            MessageService.warning(self, "Missing Path", "Please specify the path to ModOrganizer.exe", safety_level="low")
            return
        if not os.path.isfile(mo2_path):
            MessageService.warning(self, "Invalid Path", "The specified path does not point to a valid file", safety_level="low")
            return
        if not mo2_path.endswith('ModOrganizer.exe'):
            MessageService.warning(self, "Invalid File", "The specified file is not ModOrganizer.exe", safety_level="low")
            return
        
        # Start time tracking
        self._workflow_start_time = time.time()

        # Initialize progress indicator
        self.progress_indicator.set_status("Preparing to configure...", 0)

        # Start CPU tracking
        self.file_progress_list.start_cpu_tracking()

        # Disable controls during configuration (after validation passes)
        self._disable_controls_during_operation()
        
        # Validate modlist name
        modlist_name = self.modlist_name_edit.text().strip()
        if not modlist_name:
            MessageService.warning(self, "Missing Name", "Please specify a name for your modlist", safety_level="low")
            self._enable_controls_after_operation()
            return
        
        # Handle resolution saving
        resolution = self.resolution_combo.currentText()
        if resolution and resolution != "Leave unchanged":
            success = self.resolution_service.save_resolution(resolution)
            if success:
                debug_print(f"DEBUG: Resolution saved successfully: {resolution}")
            else:
                debug_print("DEBUG: Failed to save resolution")
        else:
            # Clear saved resolution if "Leave unchanged" is selected
            if self.resolution_service.has_saved_resolution():
                self.resolution_service.clear_saved_resolution()
                debug_print("DEBUG: Saved resolution cleared")
        
        # Start configuration - automated workflow handles Steam restart internally
        self.configure_modlist()

    def configure_modlist(self):
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # This ensures Proton version and winetricks settings are current
        self.config_handler._load_config()

        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()
        modlist_name = self.modlist_name_edit.text().strip()
        mo2_exe_path = self.install_dir_edit.text().strip()
        resolution = self.resolution_combo.currentText()
        if not install_dir or not modlist_name:
            MessageService.warning(self, "Missing Info", "Install directory or modlist name is missing.", safety_level="low")
            return

        # Use automated prefix service instead of manual steps
        self._safe_append_text("")
        self._safe_append_text("=== Steam Integration Phase ===")
        self._safe_append_text("Starting automated Steam setup workflow...")

        # Start automated prefix workflow
        self._start_automated_prefix_workflow(modlist_name, install_dir, mo2_exe_path, resolution)

    def _start_automated_prefix_workflow(self, modlist_name, install_dir, mo2_exe_path, resolution):
        """Start the automated prefix workflow using AutomatedPrefixService in a background thread"""
        from jackify import __version__ as jackify_version
        self._safe_append_text(f"Jackify v{jackify_version}")
        self._safe_append_text(f"Initializing automated Steam setup for '{modlist_name}'...")
        self._safe_append_text("Starting automated Steam shortcut creation and configuration...")
        
        # Disable the start button to prevent multiple workflows
        self.start_btn.setEnabled(False)
        
        # Create and start the automated prefix thread
        class AutomatedPrefixThread(QThread):
            progress_update = Signal(str)
            workflow_complete = Signal(object)  # Will emit the result tuple
            error_occurred = Signal(str)
            
            def __init__(self, modlist_name, install_dir, mo2_exe_path, steamdeck):
                super().__init__()
                self.modlist_name = modlist_name
                self.install_dir = install_dir
                self.mo2_exe_path = mo2_exe_path
                self.steamdeck = steamdeck
                
            def run(self):
                try:
                    from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                    
                    # Initialize the automated prefix service
                    prefix_service = AutomatedPrefixService()
                    
                    # Define progress callback for GUI updates
                    def progress_callback(message):
                        self.progress_update.emit(message)
                    
                    # Run the automated workflow (this contains the blocking operations)
                    result = prefix_service.run_working_workflow(
                        self.modlist_name, self.install_dir, self.mo2_exe_path, 
                        progress_callback, steamdeck=self.steamdeck
                    )
                    
                    # Emit the result
                    self.workflow_complete.emit(result)
                    
                except Exception as e:
                    self.error_occurred.emit(str(e))
        
        # Detect Steam Deck once using centralized service
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        _is_steamdeck = platform_service.is_steamdeck
        
        # Create and start the thread
        self.automated_prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, mo2_exe_path, _is_steamdeck)
        self.automated_prefix_thread.progress_update.connect(self._handle_progress_update)
        self.automated_prefix_thread.workflow_complete.connect(self._on_automated_prefix_complete)
        self.automated_prefix_thread.error_occurred.connect(self._on_automated_prefix_error)
        self.automated_prefix_thread.start()
    
    def _on_automated_prefix_complete(self, result):
        """Handle completion of the automated prefix workflow"""
        try:
            # Handle the result - check for conflicts
            if isinstance(result, tuple) and len(result) == 4:
                if result[0] == "CONFLICT":
                    # Conflict detected - show conflict resolution dialog
                    conflicts = result[1]
                    self.show_shortcut_conflict_dialog(conflicts)
                    return
                else:
                    # Normal result
                    success, prefix_path, new_appid, last_timestamp = result
                    if success:
                        self._safe_append_text(f"Automated Steam setup completed successfully!")
                        self._safe_append_text(f"New AppID assigned: {new_appid}")
                        
                        # Continue with post-Steam configuration, passing the last timestamp
                        self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                         os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), 
                                                                         last_timestamp)
                    else:
                        self._safe_append_text(f"Automated Steam setup failed")
                        self._safe_append_text("Please check the logs for details.")
                        self.start_btn.setEnabled(True)
            elif isinstance(result, tuple) and len(result) == 3:
                # Fallback for old format (backward compatibility)
                success, prefix_path, new_appid = result
                if success:
                    self._safe_append_text(f"Automated Steam setup completed successfully!")
                    self._safe_append_text(f"New AppID assigned: {new_appid}")
                    
                    # Continue with post-Steam configuration
                    self.continue_configuration_after_automated_prefix(new_appid, self.modlist_name_edit.text().strip(), 
                                                                     os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip())
                else:
                    self._safe_append_text(f"Automated Steam setup failed")
                    self._safe_append_text("Please check the logs for details.")
                    self.start_btn.setEnabled(True)
            else:
                # Handle unexpected result format
                self._safe_append_text(f"Automated Steam setup failed - unexpected result format")
                self._safe_append_text("Please check the logs for details.")
                self.start_btn.setEnabled(True)
                
        except Exception as e:
            self._safe_append_text(f"Error handling automated prefix result: {str(e)}")
            self.start_btn.setEnabled(True)
    
    def _on_automated_prefix_error(self, error_message):
        """Handle error from the automated prefix workflow"""
        self._safe_append_text(f"Error during automated Steam setup: {error_message}")
        self._safe_append_text("Please check the logs for details.")
        
        # Show critical error dialog to user (don't silently fail)
        from jackify.backend.services.message_service import MessageService
        MessageService.critical(
            self,
            "Steam Setup Error",
            f"Error during automated Steam setup:\n\n{error_message}\n\nPlease check the console output for details.",
            safety_level="medium"
        )
        
        self._enable_controls_after_operation()

    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve shortcut name conflicts"""
        conflict_names = [c['name'] for c in conflicts]
        conflict_info = f"Found existing Steam shortcut: '{conflict_names[0]}'"
        
        modlist_name = self.modlist_name_edit.text().strip()
        
        # Create dialog with Jackify styling
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        from PySide6.QtCore import Qt
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Steam Shortcut Conflict")
        dialog.setModal(True)
        dialog.resize(450, 180)
        
        # Apply Jackify dark theme styling
        dialog.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                padding: 10px 0px;
            }
            QLineEdit {
                background-color: #404040;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
                selection-background-color: #3fd0ea;
            }
            QLineEdit:focus {
                border-color: #3fd0ea;
            }
            QPushButton {
                background-color: #404040;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #505050;
                border-color: #3fd0ea;
            }
            QPushButton:pressed {
                background-color: #303030;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Conflict message
        conflict_label = QLabel(f"{conflict_info}\n\nPlease choose a different name for your shortcut:")
        layout.addWidget(conflict_label)
        
        # Text input for new name
        name_input = QLineEdit(modlist_name)
        name_input.selectAll()
        layout.addWidget(name_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        create_button = QPushButton("Create with New Name")
        cancel_button = QPushButton("Cancel")
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(create_button)
        layout.addLayout(button_layout)
        
        # Connect signals
        def on_create():
            new_name = name_input.text().strip()
            if new_name and new_name != modlist_name:
                dialog.accept()
                # Retry workflow with new name
                self.retry_automated_workflow_with_new_name(new_name)
            elif new_name == modlist_name:
                # Same name - show warning
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                # Empty name
                from jackify.backend.services.message_service import MessageService
                MessageService.warning(self, "Invalid Name", "Please enter a valid shortcut name.")
        
        def on_cancel():
            dialog.reject()
            self._safe_append_text("Shortcut creation cancelled by user")
        
        create_button.clicked.connect(on_create)
        cancel_button.clicked.connect(on_cancel)
        
        # Make Enter key work
        name_input.returnPressed.connect(on_create)
        
        dialog.exec()
    
    def retry_automated_workflow_with_new_name(self, new_name):
        """Retry the automated workflow with a new shortcut name"""
        # Update the modlist name field temporarily
        original_name = self.modlist_name_edit.text()
        self.modlist_name_edit.setText(new_name)
        
        # Restart the automated workflow
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self._start_automated_prefix_workflow(new_name, os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip(), self.install_dir_edit.text().strip(), self.resolution_combo.currentText())

    # Old CLI-based handlers removed - now using backend service directly

    # Manual steps methods removed - now using automated prefix service
        """Validate that manual steps were actually completed and handle retry logic"""
        modlist_name = self.modlist_name_edit.text().strip()
        install_dir = os.path.dirname(self.install_dir_edit.text().strip()) if self.install_dir_edit.text().strip().endswith('ModOrganizer.exe') else self.install_dir_edit.text().strip()
        mo2_exe_path = self.install_dir_edit.text().strip()
        
        # CRITICAL: Re-detect the AppID after Steam restart and manual steps
        # Steam assigns a NEW AppID during restart, different from the one we initially created
        self._safe_append_text(f"Re-detecting AppID for shortcut '{modlist_name}' after Steam restart...")
        from jackify.backend.handlers.shortcut_handler import ShortcutHandler
        from jackify.backend.services.platform_detection_service import PlatformDetectionService

        platform_service = PlatformDetectionService.get_instance()
        shortcut_handler = ShortcutHandler(steamdeck=platform_service.is_steamdeck)
        current_appid = shortcut_handler.get_appid_for_shortcut(modlist_name, mo2_exe_path)
        
        if not current_appid or not current_appid.isdigit():
            self._safe_append_text(f"Error: Could not find Steam-assigned AppID for shortcut '{modlist_name}'")
            self._safe_append_text("Error: This usually means the shortcut was not launched from Steam")
            self.handle_validation_failure("Could not find Steam shortcut")
            return
        
        self._safe_append_text(f"Found Steam-assigned AppID: {current_appid}")
        self._safe_append_text(f"Validating manual steps completion for AppID: {current_appid}")
        
        # Check manual steps completion (same validation as Tuxborn)
        validation_passed = True
        missing_details = []
        
        # Check 1: Proton version
        proton_ok = False
        try:
            from jackify.backend.handlers.modlist_handler import ModlistHandler
            from jackify.backend.handlers.path_handler import PathHandler
            
            # Initialize ModlistHandler with correct parameters
            path_handler = PathHandler()

            # Use centralized Steam Deck detection
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()

            modlist_handler = ModlistHandler(steamdeck=platform_service.is_steamdeck, verbose=False)
            
            # Set required properties manually after initialization
            modlist_handler.modlist_dir = install_dir
            modlist_handler.appid = current_appid  # Use the re-detected AppID
            modlist_handler.game_var = "skyrimspecialedition"  # Default for now
            
            # Set compat_data_path for Proton detection using the re-detected AppID
            compat_data_path_str = path_handler.find_compat_data(current_appid)
            if compat_data_path_str:
                from pathlib import Path
                modlist_handler.compat_data_path = Path(compat_data_path_str)
            
            # Check Proton version using the re-detected AppID
            self._safe_append_text(f"Attempting to detect Proton version for AppID {current_appid}...")
            if modlist_handler._detect_proton_version():
                self._safe_append_text(f"Raw detected Proton version: '{modlist_handler.proton_ver}'")
                
                if modlist_handler.proton_ver and 'experimental' in modlist_handler.proton_ver.lower():
                    self._safe_append_text(f"Proton version validated: {modlist_handler.proton_ver}")
                    proton_ok = True
                else:
                    self._safe_append_text(f"Error: Wrong Proton version detected: '{modlist_handler.proton_ver}' (expected 'experimental' in name)")
            else:
                self._safe_append_text("Error: Could not detect Proton version from any source")
                
        except Exception as e:
            self._safe_append_text(f"Error checking Proton version: {e}")
        
        if not proton_ok:
            validation_passed = False
            missing_details.append("Error: Proton version not set to 'Proton - Experimental'")
        
        # Check 2: Compatdata directory exists
        compatdata_ok = False
        try:
            from jackify.backend.handlers.path_handler import PathHandler
            path_handler = PathHandler()
            self._safe_append_text(f"Searching for compatdata directory for AppID {current_appid}...")
            prefix_path_str = path_handler.find_compat_data(current_appid)
            self._safe_append_text(f"Compatdata search result: '{prefix_path_str}'")
            
            if prefix_path_str:
                from pathlib import Path
                prefix_path = Path(prefix_path_str)
                if prefix_path.exists() and prefix_path.is_dir():
                    self._safe_append_text(f"Compatdata directory found: {prefix_path_str}")
                    compatdata_ok = True
                elif prefix_path.exists():
                    self._safe_append_text(f"Error: Path exists but is not a directory: {prefix_path_str}")
                else:
                    self._safe_append_text(f"Error: No compatdata directory found for AppID {current_appid}")
            else:
                self._safe_append_text(f"ERROR: No compatdata directory found for AppID {current_appid}")
        except Exception as e:
            self._safe_append_text(f"Error checking compatdata: {e}")
        
        if not compatdata_ok:
            validation_passed = False
            missing_details.append("Error: Modlist was not launched from Steam (no compatdata directory)")
        
        if validation_passed:
            self._safe_append_text("Manual steps validation passed!")
            self._safe_append_text("Continuing configuration with updated AppID...")
            
            # Continue with configuration (same as Tuxborn)
            self.continue_configuration_after_manual_steps(current_appid, modlist_name, install_dir)
        else:
            missing_text = "\n".join(missing_details)
            self._safe_append_text(f"Manual steps validation failed:\n{missing_text}")
            self.handle_validation_failure(missing_text)
    
    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Get resolution from UI
            resolution = self.resolution_combo.currentText()
            resolution_value = resolution.split()[0] if resolution != "Leave unchanged" else None
            
            # Update the context with the new AppID (same format as manual steps)
            mo2_exe_path = self.install_dir_edit.text().strip()
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'modlist_value': None,
                'modlist_source': None,
                'resolution': resolution_value,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            self.context = updated_context  # Ensure context is always set
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context):
                    super().__init__()
                    self.context = context
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        system_info = SystemInfo(is_steamdeck=False)
                        modlist_service = ModlistService(system_info)
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type='skyrim',  # Default for now
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value=self.context.get('modlist_value'),
                            modlist_source=self.context.get('modlist_source', 'identifier'),
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # This shouldn't happen since automated prefix creation is complete
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the service method for post-Steam configuration
                        self.progress_update.emit("")
                        self.progress_update.emit("=== Configuration Phase ===")
                        self.progress_update.emit("")
                        self.progress_update.emit("Starting modlist configuration...")
                        result = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not result:
                            self.progress_update.emit("Configuration failed to start")
                            self.error_occurred.emit("Configuration failed to start")
                            
                    except Exception as e:
                        self.error_occurred.emit(str(e))
            
            # Start configuration thread
            self.config_thread = ConfigThread(updated_context)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            import traceback
            self._safe_append_text(f"Full traceback: {traceback.format_exc()}")
            self.on_configuration_error(str(e))

    def continue_configuration_after_manual_steps(self, new_appid, modlist_name, install_dir):
        """Continue the configuration process with the corrected AppID after manual steps validation"""
        try:
            # Update the context with the new AppID
            mo2_exe_path = self.install_dir_edit.text().strip()
            resolution = self.resolution_combo.currentText()
            
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': mo2_exe_path,
                'resolution': resolution.split()[0] if resolution != "Leave unchanged" else None,
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid,  # Use the NEW AppID from Steam
                'game_name': 'Skyrim Special Edition'  # Default for new modlist
            }
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Create new config thread with updated context (same as Tuxborn)
            from PySide6.QtCore import QThread, Signal
            
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str, bool)
                error_occurred = Signal(str)
                
                def __init__(self, context):
                    super().__init__()
                    self.context = context
                    
                def run(self):
                    try:
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service
                        system_info = SystemInfo(is_steamdeck=False)
                        modlist_service = ModlistService(system_info)
                        
                        # Convert context to ModlistContext for service
                        modlist_context = ModlistContext(
                            name=self.context['name'],
                            install_dir=Path(self.context['path']),
                            download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                            game_type='skyrim',  # Default for configure new
                            nexus_api_key='',  # Not needed for configuration
                            modlist_value='',  # Not needed for existing modlist
                            modlist_source='existing',
                            resolution=self.context.get('resolution') or get_resolution_fallback(None),
                            skip_confirmation=True
                        )
                        
                        # Add app_id to context
                        if 'appid' in self.context:
                            modlist_context.app_id = self.context['appid']
                        
                        # Define callbacks
                        def progress_callback(message):
                            self.progress_update.emit(message)
                            
                        def completion_callback(success, message, modlist_name, enb_detected=False):
                            self.configuration_complete.emit(success, message, modlist_name, enb_detected)
                            
                        def manual_steps_callback(modlist_name, retry_count):
                            # This shouldn't happen since manual steps should be done
                            self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                        
                        # Call the working configuration service method
                        self.progress_update.emit("Starting configuration with backend service...")
                        
                        success = modlist_service.configure_modlist_post_steam(
                            context=modlist_context,
                            progress_callback=progress_callback,
                            manual_steps_callback=manual_steps_callback,
                            completion_callback=completion_callback
                        )
                        
                        if not success:
                            self.error_occurred.emit("Configuration failed - check logs for details")
                            
                    except Exception as e:
                        import traceback
                        error_msg = f"Configuration error: {e}\n{traceback.format_exc()}"
                        self.error_occurred.emit(error_msg)
            
            # Create and start the configuration thread
            self.config_thread = ConfigThread(updated_context)
            self.config_thread.progress_update.connect(self._handle_progress_update)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            MessageService.critical(self, "Configuration Error", f"Failed to continue configuration: {e}", safety_level="medium")

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion (same as Tuxborn)"""
        # Re-enable all controls when workflow completes
        self._enable_controls_after_operation()
        
        if success:
            # Calculate time taken
            time_taken = self._calculate_time_taken()

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show success dialog with celebration
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="configure_new",
                time_taken=time_taken,
                game_name=getattr(self, '_current_game_name', None),
                parent=self
            )
            success_dialog.show()
            
            # Show ENB Proton dialog if ENB was detected (use stored detection result, no re-detection)
            if enb_detected:
                try:
                    from ..dialogs.enb_proton_dialog import ENBProtonDialog
                    enb_dialog = ENBProtonDialog(modlist_name=modlist_name, parent=self)
                    enb_dialog.exec()  # Modal dialog - blocks until user clicks OK
                except Exception as e:
                    # Non-blocking: if dialog fails, just log and continue
                    logger.warning(f"Failed to show ENB dialog: {e}")
        else:
            self._safe_append_text(f"Configuration failed: {message}")
            MessageService.critical(self, "Configuration Failed", 
                               f"Configuration failed: {message}", safety_level="medium")
    
    def on_configuration_error(self, error_message):
        """Handle configuration error"""
        # Re-enable all controls on error
        self._enable_controls_after_operation()
        
        self._safe_append_text(f"Configuration error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}", safety_level="medium")

    def handle_validation_failure(self, missing_text):
        """Handle manual steps validation failure with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               "Please complete the manual steps and try again.", safety_level="medium")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.", safety_level="medium")
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self.modlist_name_edit.text().strip())

    # Old CLI-based process finished handler removed - now using backend service callbacks

    def _calculate_time_taken(self) -> str:
        """Calculate and format the time taken for the workflow"""
        if self._workflow_start_time is None:
            return "unknown time"
        
        elapsed_seconds = time.time() - self._workflow_start_time
        elapsed_minutes = int(elapsed_seconds // 60)
        elapsed_seconds_remainder = int(elapsed_seconds % 60)
        
        if elapsed_minutes > 0:
            if elapsed_minutes == 1:
                return f"{elapsed_minutes} minute {elapsed_seconds_remainder} seconds"
            else:
                return f"{elapsed_minutes} minutes {elapsed_seconds_remainder} seconds"
        else:
            return f"{elapsed_seconds_remainder} seconds"

    def show_next_steps_dialog(self, message):
        dlg = QDialog(self)
        dlg.setWindowTitle("Next Steps")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        btn_row = QHBoxLayout()
        btn_return = QPushButton("Return")
        btn_exit = QPushButton("Exit")
        btn_row.addWidget(btn_return)
        btn_row.addWidget(btn_exit)
        layout.addLayout(btn_row)
        def on_return():
            dlg.accept()
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(0)
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.install_dir_edit.setText("/path/to/Modlist/ModOrganizer.exe")

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Reset resolution combo to saved config preference
        saved_resolution = self.resolution_service.get_saved_resolution()
        if saved_resolution:
            combo_items = [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())]
            resolution_index = self.resolution_service.get_resolution_index(saved_resolution, combo_items)
            self.resolution_combo.setCurrentIndex(resolution_index)
        elif self.resolution_combo.count() > 0:
            self.resolution_combo.setCurrentIndex(0)  # Fallback to "Leave unchanged"

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

    def cleanup(self):
        """Clean up any running threads when the screen is closed"""
        debug_print("DEBUG: cleanup called - cleaning up threads")
        
        # Clean up automated prefix thread if running
        if hasattr(self, 'automated_prefix_thread') and self.automated_prefix_thread and self.automated_prefix_thread.isRunning():
            debug_print("DEBUG: Terminating AutomatedPrefixThread")
            try:
                self.automated_prefix_thread.progress_update.disconnect()
                self.automated_prefix_thread.workflow_complete.disconnect()
                self.automated_prefix_thread.error_occurred.disconnect()
            except:
                pass
            self.automated_prefix_thread.terminate()
            self.automated_prefix_thread.wait(2000)  # Wait up to 2 seconds
        
        # Clean up config thread if running
        if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
            debug_print("DEBUG: Terminating ConfigThread")
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass
            self.config_thread.terminate()
            self.config_thread.wait(2000)  # Wait up to 2 seconds 