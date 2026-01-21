"""
Jackify GUI Frontend Main Application

Main entry point for the Jackify GUI application using PySide6.
This replaces the legacy jackify_gui implementation with a refactored architecture.
"""

import sys
import os
import logging
from pathlib import Path

# Suppress xkbcommon locale errors (harmless but annoying)
os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false;*.warning=false'
os.environ['QT_ENABLE_GLYPH_CACHE_WORKAROUND'] = '1'

# Hidden diagnostic flag for debugging AppImage/bundled environment issues - must be first
if '--env-diagnostic' in sys.argv:
    import json
    from datetime import datetime
    
    print("Bundled Environment Diagnostic")
    print("=" * 50)
    
    # Check if we're running as AppImage
    is_appimage = 'APPIMAGE' in os.environ or 'APPDIR' in os.environ
    appdir = os.environ.get('APPDIR')
    
    print(f"AppImage: {is_appimage}")
    print(f"APPDIR: {appdir}")
    
    # Capture environment data
    env_data = {
        'timestamp': datetime.now().isoformat(),
        'context': 'appimage_runtime',
        'appimage': is_appimage,
        'appdir': appdir,
        'python_executable': sys.executable,
        'working_directory': os.getcwd(),
        'sys_path': sys.path,
    }
    
    # Bundle-specific environment variables
    bundle_vars = {}
    for key, value in os.environ.items():
        if any(term in key.lower() for term in ['mei', 'appimage', 'tmp']):
            bundle_vars[key] = value
    
    env_data['bundle_vars'] = bundle_vars
    
    # Check LD_LIBRARY_PATH
    ld_path = os.environ.get('LD_LIBRARY_PATH', '')
    if ld_path:
        suspicious = [p for p in ld_path.split(':') if 'mei' in p.lower() or 'tmp' in p.lower()]
        env_data['ld_library_path'] = ld_path
        env_data['ld_library_path_suspicious'] = suspicious
    
    # Try to find jackify-engine from bundled context
    engine_paths = []
    if meipass:
        meipass_path = Path(meipass)
        potential_engine = meipass_path / "jackify" / "engine" / "jackify-engine"
        if potential_engine.exists():
            engine_paths.append(str(potential_engine))
    
    env_data['engine_paths_found'] = engine_paths
    
    # Output the results
    print("\nEnvironment Data:")
    print(json.dumps(env_data, indent=2))
    
    # Save to file
    try:
        output_file = Path.cwd() / "bundle_env_capture.json"
        with open(output_file, 'w') as f:
            json.dump(env_data, f, indent=2)
        print(f"\nData saved to: {output_file}")
    except Exception as e:
        print(f"\nCould not save data: {e}")
    
    sys.exit(0)

from jackify import __version__ as jackify_version

# Initialize logger
logger = logging.getLogger(__name__)

if '--help' in sys.argv or '-h' in sys.argv:
    print("""Jackify - Native Linux Modlist Manager\n\nUsage:\n  jackify [--cli] [--debug] [--version] [--help]\n\nOptions:\n  --cli         Launch CLI frontend\n  --debug       Enable debug logging\n  --version     Show version and exit\n  --help, -h    Show this help message and exit\n\nIf no options are given, the GUI will launch by default.\n""")
    sys.exit(0)

if '-v' in sys.argv or '--version' in sys.argv or '-V' in sys.argv:
    print(f"Jackify version {jackify_version}")
    sys.exit(0)


from jackify import __version__

# Add src directory to Python path
src_dir = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(src_dir))

from PySide6.QtWidgets import (
    QSizePolicy, QScrollArea,
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QPushButton,
    QStackedWidget, QHBoxLayout, QDialog, QFormLayout, QLineEdit, QCheckBox, QSpinBox, QMessageBox, QGroupBox, QGridLayout, QFileDialog, QToolButton, QStyle, QComboBox, QTabWidget, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, QEvent, QTimer, QThread, Signal
from PySide6.QtGui import QIcon
import json

# Import backend services and models
from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.modlist_service import ModlistService
from jackify.frontends.gui.services.message_service import MessageService
from jackify.frontends.gui.shared_theme import DEBUG_BORDERS
from jackify.frontends.gui.utils import get_screen_geometry, set_responsive_minimum

ENABLE_WINDOW_HEIGHT_ANIMATION = False

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

# Constants for styling and disclaimer
DISCLAIMER_TEXT = (
    "Disclaimer: Jackify is currently in an alpha state. This software is provided as-is, "
    "without any warranty or guarantee of stability. By using Jackify, you acknowledge that you do so at your own risk. "
    "The developers are not responsible for any data loss, system issues, or other problems that may arise from its use. "
    "Please back up your data and use caution."
)

MENU_ITEMS = [
    ("Modlist Tasks", "modlist_tasks"),
    ("Hoolamike Tasks", "hoolamike_tasks"),
    ("Additional Tasks", "additional_tasks"),
    ("Exit Jackify", "exit_jackify"),
]


class FeaturePlaceholder(QWidget):
    """Placeholder widget for features not yet implemented"""
    
    def __init__(self, stacked_widget=None):
        super().__init__()
        layout = QVBoxLayout()
        
        label = QLabel("[Feature screen placeholder]")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        back_btn = QPushButton("Back to Main Menu")
        if stacked_widget:
            back_btn.clicked.connect(lambda: stacked_widget.setCurrentIndex(0))
        layout.addWidget(back_btn)
        
        self.setLayout(layout)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        try:
            super().__init__(parent)
            from jackify.backend.handlers.config_handler import ConfigHandler
            import logging
            self.logger = logging.getLogger(__name__)
            self.config_handler = ConfigHandler()
            self._original_debug_mode = self.config_handler.get('debug_mode', False)
            self.setWindowTitle("Settings")
            self.setModal(True)
            self.setMinimumWidth(650)
            self.setMaximumWidth(800)
            self.setStyleSheet("QDialog { background-color: #232323; color: #eee; } QPushButton:hover { background-color: #333; }")

            main_layout = QVBoxLayout()
            self.setLayout(main_layout)

            # Create tab widget
            self.tab_widget = QTabWidget()
            self.tab_widget.setStyleSheet("""
                QTabWidget::pane { border: 1px solid #555; background: #232323; }
                QTabBar::tab { background: #333; color: #eee; padding: 8px 16px; margin: 2px; }
                QTabBar::tab:selected { background: #555; }
                QTabBar::tab:hover { background: #444; }
            """)
            main_layout.addWidget(self.tab_widget)

            # Create tabs
            self._create_general_tab()
            self._create_advanced_tab()

            # --- Save/Close/Help Buttons ---
            btn_layout = QHBoxLayout()
            self.help_btn = QPushButton("Help")
            self.help_btn.setToolTip("Help/documentation coming soon!")
            self.help_btn.clicked.connect(self._show_help)
            btn_layout.addWidget(self.help_btn)
            btn_layout.addStretch(1)
            save_btn = QPushButton("Save")
            close_btn = QPushButton("Close")
            save_btn.clicked.connect(self._save)
            close_btn.clicked.connect(self.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(close_btn)

            # Add error label for validation messages
            self.error_label = QLabel("")
            self.error_label.setStyleSheet("QLabel { color: #ff6b6b; }")
            main_layout.addWidget(self.error_label)

            main_layout.addSpacing(10)
            main_layout.addLayout(btn_layout)

        except Exception as e:
            print(f"[ERROR] Exception in SettingsDialog.__init__: {e}")
            import traceback
            traceback.print_exc()

    def _create_general_tab(self):
        """Create the General settings tab"""
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)

        # --- Directory Paths Section (moved to top as most essential) ---
        dir_group = QGroupBox("Directory Paths")
        dir_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        dir_layout = QFormLayout()
        dir_group.setLayout(dir_layout)
        self.install_dir_edit = QLineEdit(self.config_handler.get("modlist_install_base_dir", ""))
        self.install_dir_edit.setToolTip("Default directory for modlist installations.")
        self.install_dir_btn = QPushButton()
        self.install_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.install_dir_btn.setToolTip("Browse for directory")
        self.install_dir_btn.setFixedWidth(32)
        self.install_dir_btn.clicked.connect(lambda: self._pick_directory(self.install_dir_edit))
        install_dir_row = QHBoxLayout()
        install_dir_row.addWidget(self.install_dir_edit)
        install_dir_row.addWidget(self.install_dir_btn)
        dir_layout.addRow(QLabel("Install Base Dir:"), install_dir_row)
        self.download_dir_edit = QLineEdit(self.config_handler.get("modlist_downloads_base_dir", ""))
        self.download_dir_edit.setToolTip("Default directory for modlist downloads.")
        self.download_dir_btn = QPushButton()
        self.download_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.download_dir_btn.setToolTip("Browse for directory")
        self.download_dir_btn.setFixedWidth(32)
        self.download_dir_btn.clicked.connect(lambda: self._pick_directory(self.download_dir_edit))
        download_dir_row = QHBoxLayout()
        download_dir_row.addWidget(self.download_dir_edit)
        download_dir_row.addWidget(self.download_dir_btn)
        dir_layout.addRow(QLabel("Downloads Base Dir:"), download_dir_row)

        # Jackify Data Directory
        from jackify.shared.paths import get_jackify_data_dir
        current_jackify_dir = str(get_jackify_data_dir())
        self.jackify_data_dir_edit = QLineEdit(current_jackify_dir)
        self.jackify_data_dir_edit.setToolTip("Directory for Jackify data (logs, downloads, temp files). Default: ~/Jackify")
        self.jackify_data_dir_btn = QPushButton()
        self.jackify_data_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.jackify_data_dir_btn.setToolTip("Browse for directory")
        self.jackify_data_dir_btn.setFixedWidth(32)
        self.jackify_data_dir_btn.clicked.connect(lambda: self._pick_directory(self.jackify_data_dir_edit))
        jackify_data_dir_row = QHBoxLayout()
        jackify_data_dir_row.addWidget(self.jackify_data_dir_edit)
        jackify_data_dir_row.addWidget(self.jackify_data_dir_btn)

        # Reset to default button
        reset_jackify_dir_btn = QPushButton("Reset")
        reset_jackify_dir_btn.setToolTip("Reset to default (~/ Jackify)")
        reset_jackify_dir_btn.setFixedWidth(50)
        reset_jackify_dir_btn.clicked.connect(lambda: self.jackify_data_dir_edit.setText(str(Path.home() / "Jackify")))
        jackify_data_dir_row.addWidget(reset_jackify_dir_btn)

        dir_layout.addRow(QLabel("Jackify Data Dir:"), jackify_data_dir_row)
        general_layout.addWidget(dir_group)
        general_layout.addSpacing(12)

        # --- Proton Version Settings Section ---
        proton_group = QGroupBox("Proton Version Settings")
        proton_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        proton_layout = QVBoxLayout()
        proton_group.setLayout(proton_layout)

        # Install Proton Version (for jackify-engine texture processing)
        install_proton_layout = QHBoxLayout()
        self.install_proton_dropdown = QComboBox()
        self.install_proton_dropdown.setToolTip("Proton version for modlist installation and texture processing (requires fast Proton)")
        self.install_proton_dropdown.setMinimumWidth(200)

        install_refresh_btn = QPushButton("↻")
        install_refresh_btn.setFixedSize(30, 30)
        install_refresh_btn.setToolTip("Refresh install Proton version list")
        install_refresh_btn.clicked.connect(self._refresh_install_proton_dropdown)

        install_proton_layout.addWidget(QLabel("Install Proton:"))
        install_proton_layout.addWidget(self.install_proton_dropdown)
        install_proton_layout.addWidget(install_refresh_btn)
        install_proton_layout.addStretch()

        # Game Proton Version (for game shortcuts)
        game_proton_layout = QHBoxLayout()
        self.game_proton_dropdown = QComboBox()
        self.game_proton_dropdown.setToolTip("Proton version for game shortcuts (can be any Proton 9+)")
        self.game_proton_dropdown.setMinimumWidth(200)

        game_refresh_btn = QPushButton("↻")
        game_refresh_btn.setFixedSize(30, 30)
        game_refresh_btn.setToolTip("Refresh game Proton version list")
        game_refresh_btn.clicked.connect(self._refresh_game_proton_dropdown)

        game_proton_layout.addWidget(QLabel("Game Proton:"))
        game_proton_layout.addWidget(self.game_proton_dropdown)
        game_proton_layout.addWidget(game_refresh_btn)
        game_proton_layout.addStretch()

        proton_layout.addLayout(install_proton_layout)
        proton_layout.addLayout(game_proton_layout)

        # Populate both Proton dropdowns
        self._populate_install_proton_dropdown()
        self._populate_game_proton_dropdown()

        general_layout.addWidget(proton_group)
        general_layout.addSpacing(12)

        # --- Nexus OAuth Section ---
        oauth_group = QGroupBox("Nexus Authentication")
        oauth_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        oauth_layout = QVBoxLayout()
        oauth_group.setLayout(oauth_layout)

        # OAuth status and button
        oauth_status_layout = QHBoxLayout()
        self.oauth_status_label = QLabel("Checking...")
        self.oauth_status_label.setStyleSheet("color: #ccc;")

        self.oauth_btn = QPushButton("Authorise")
        self.oauth_btn.setMaximumWidth(100)
        self.oauth_btn.clicked.connect(self._handle_oauth_click)

        oauth_status_layout.addWidget(QLabel("Status:"))
        oauth_status_layout.addWidget(self.oauth_status_label)
        oauth_status_layout.addWidget(self.oauth_btn)
        oauth_status_layout.addStretch()

        oauth_layout.addLayout(oauth_status_layout)

        # Update OAuth status on init
        self._update_oauth_status()

        general_layout.addWidget(oauth_group)
        general_layout.addSpacing(12)

        # --- Enable Debug Section (moved to bottom as advanced option) ---
        debug_group = QGroupBox("Enable Debug")
        debug_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        debug_layout = QVBoxLayout()
        debug_group.setLayout(debug_layout)
        self.debug_checkbox = QCheckBox("Enable debug mode (requires restart)")
        # Load debug_mode from config
        self.debug_checkbox.setChecked(self.config_handler.get('debug_mode', False))
        self.debug_checkbox.setToolTip("Enable verbose debug logging. Requires Jackify restart to take effect.")
        self.debug_checkbox.setStyleSheet("color: #fff;")
        debug_layout.addWidget(self.debug_checkbox)
        general_layout.addWidget(debug_group)
        general_layout.addStretch()  # Add stretch to push content to top

        self.tab_widget.addTab(general_tab, "General")

    def _create_advanced_tab(self):
        """Create the Advanced settings tab"""
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)

        # --- Nexus Authentication Section ---
        auth_group = QGroupBox("Nexus Authentication")
        auth_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        auth_layout = QVBoxLayout()
        auth_group.setLayout(auth_layout)

        # OAuth temporarily disabled for v0.1.8 - API key is primary auth method
        # API Key Fallback Checkbox (hidden until OAuth re-enabled)
        # self.api_key_fallback_checkbox = QCheckBox("Enable API Key Fallback (Legacy)")
        # self.api_key_fallback_checkbox.setChecked(self.config_handler.get("api_key_fallback_enabled", False))
        # self.api_key_fallback_checkbox.setToolTip("Allow using API key if OAuth fails or is unavailable (not recommended)")
        # auth_layout.addWidget(self.api_key_fallback_checkbox)

        # API Key Section
        api_layout = QHBoxLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        api_key = self.config_handler.get_api_key()
        if api_key:
            self.api_key_edit.setText(api_key)
        else:
            self.api_key_edit.setText("")
        self.api_key_edit.setToolTip("Your Nexus API Key (legacy authentication method)")
        self.api_key_edit.textChanged.connect(self._on_api_key_changed)

        self.api_show_btn = QToolButton()
        self.api_show_btn.setCheckable(True)
        self.api_show_btn.setIcon(QIcon.fromTheme("view-visible"))
        self.api_show_btn.setToolTip("Show or hide your API key")
        self.api_show_btn.toggled.connect(self._toggle_api_key_visibility)

        clear_api_btn = QPushButton("Clear")
        clear_api_btn.clicked.connect(self._clear_api_key)
        clear_api_btn.setMaximumWidth(60)

        api_layout.addWidget(QLabel("API Key:"))
        api_layout.addWidget(self.api_key_edit)
        api_layout.addWidget(self.api_show_btn)
        api_layout.addWidget(clear_api_btn)
        auth_layout.addLayout(api_layout)

        advanced_layout.addWidget(auth_group)
        advanced_layout.addSpacing(12)

        resource_group = QGroupBox("Resource Limits")
        resource_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        resource_outer_layout = QVBoxLayout()
        resource_group.setLayout(resource_outer_layout)

        self.resource_settings_path = os.path.expanduser("~/.config/jackify/resource_settings.json")
        self.resource_settings = self._load_json(self.resource_settings_path)
        self.resource_edits = {}

        # If no resources exist, show helpful message
        if not self.resource_settings:
            info_label = QLabel("Resource Limit settings will be generated once a modlist install action is performed")
            info_label.setStyleSheet("color: #aaa; font-style: italic; padding: 20px; font-size: 11pt;")
            info_label.setWordWrap(True)
            info_label.setAlignment(Qt.AlignCenter)
            info_label.setMinimumHeight(60)
            resource_outer_layout.addWidget(info_label)
        else:
            # Two-column layout for better space usage
            # Use a single grid with proper column spacing
            resource_grid = QGridLayout()
            resource_grid.setVerticalSpacing(4)
            resource_grid.setHorizontalSpacing(8)
            resource_grid.setColumnMinimumWidth(2, 40)  # Spacing between columns

            # Headers for left column (columns 0-1)
            resource_grid.addWidget(self._bold_label("Resource"), 0, 0, 1, 1, Qt.AlignLeft)
            resource_grid.addWidget(self._bold_label("Max Tasks"), 0, 1, 1, 1, Qt.AlignLeft)

            # Headers for right column (columns 3-4, skip column 2 for spacing)
            resource_grid.addWidget(self._bold_label("Resource"), 0, 3, 1, 1, Qt.AlignLeft)
            resource_grid.addWidget(self._bold_label("Max Tasks"), 0, 4, 1, 1, Qt.AlignLeft)

            # Split resources between left and right columns (4 + 4)
            resource_items = list(self.resource_settings.items())

            # Find Bandwidth info from Downloads resource if it exists
            bandwidth_kb = 0
            if "Downloads" in self.resource_settings:
                downloads_throughput_bytes = self.resource_settings["Downloads"].get("MaxThroughput", 0)
                bandwidth_kb = downloads_throughput_bytes // 1024 if downloads_throughput_bytes > 0 else 0

            # Left column gets first 4 resources (columns 0-1)
            left_row = 1
            for k, v in resource_items[:4]:
                try:
                    resource_grid.addWidget(QLabel(f"{k}:", parent=self), left_row, 0, 1, 1, Qt.AlignLeft)

                    max_tasks_spin = QSpinBox()
                    max_tasks_spin.setMinimum(1)
                    max_tasks_spin.setMaximum(128)
                    max_tasks_spin.setValue(v.get('MaxTasks', 16))
                    max_tasks_spin.setToolTip("Maximum number of concurrent tasks for this resource.")
                    max_tasks_spin.setFixedWidth(100)
                    resource_grid.addWidget(max_tasks_spin, left_row, 1)

                    self.resource_edits[k] = (None, max_tasks_spin)
                    left_row += 1
                except Exception as e:
                    print(f"[ERROR] Failed to create widgets for resource '{k}': {e}")
                    continue

            # Right column gets next 4 resources (columns 3-4, skip column 2 for spacing)
            right_row = 1
            for k, v in resource_items[4:]:
                try:
                    resource_grid.addWidget(QLabel(f"{k}:", parent=self), right_row, 3, 1, 1, Qt.AlignLeft)

                    max_tasks_spin = QSpinBox()
                    max_tasks_spin.setMinimum(1)
                    max_tasks_spin.setMaximum(128)
                    max_tasks_spin.setValue(v.get('MaxTasks', 16))
                    max_tasks_spin.setToolTip("Maximum number of concurrent tasks for this resource.")
                    max_tasks_spin.setFixedWidth(100)
                    resource_grid.addWidget(max_tasks_spin, right_row, 4)

                    self.resource_edits[k] = (None, max_tasks_spin)
                    right_row += 1
                except Exception as e:
                    print(f"[ERROR] Failed to create widgets for resource '{k}': {e}")
                    continue

            # Add Bandwidth Limit at the bottom of right column
            if "Downloads" in self.resource_settings:
                resource_grid.addWidget(QLabel("Bandwidth Limit:", parent=self), right_row, 3, 1, 1, Qt.AlignLeft)

                self.bandwidth_spin = QSpinBox()
                self.bandwidth_spin.setMinimum(0)
                self.bandwidth_spin.setMaximum(1000000)
                self.bandwidth_spin.setValue(bandwidth_kb)
                self.bandwidth_spin.setSuffix(" KB/s")
                self.bandwidth_spin.setFixedWidth(100)
                self.bandwidth_spin.setToolTip("Set the maximum download speed for modlist downloads. 0 = unlimited.")

                # Create a layout for the spinbox and note
                bandwidth_widget_layout = QHBoxLayout()
                bandwidth_widget_layout.setContentsMargins(0, 0, 0, 0)
                bandwidth_widget_layout.addWidget(self.bandwidth_spin)

                bandwidth_note = QLabel("(0 = unlimited)")
                bandwidth_note.setStyleSheet("color: #aaa; font-size: 9pt;")
                bandwidth_widget_layout.addWidget(bandwidth_note)
                bandwidth_widget_layout.addStretch()

                # Create container widget for the layout
                bandwidth_container = QWidget()
                bandwidth_container.setLayout(bandwidth_widget_layout)
                resource_grid.addWidget(bandwidth_container, right_row, 4, 1, 1, Qt.AlignLeft)
            else:
                self.bandwidth_spin = None

            # Add stretch column at the end to push content left
            resource_grid.setColumnStretch(5, 1)

            resource_outer_layout.addLayout(resource_grid)

        advanced_layout.addWidget(resource_group)

        # Advanced Tool Options Section
        component_group = QGroupBox("Advanced Tool Options")
        component_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        component_layout = QVBoxLayout()
        component_group.setLayout(component_layout)

        # Label for the radio buttons
        method_label = QLabel("Wine Components Installation:")
        component_layout.addWidget(method_label)

        # Radio button group for component installation method
        self.component_method_group = QButtonGroup()
        component_method_layout = QVBoxLayout()
        
        # Get current setting
        current_method = self.config_handler.get('component_installation_method', 'system_protontricks')
        # Migrate old bundled_protontricks users to system_protontricks
        if current_method == 'bundled_protontricks':
            current_method = 'system_protontricks'

        # Protontricks (default)
        self.protontricks_radio = QRadioButton("Protontricks (Default)")
        self.protontricks_radio.setChecked(current_method == 'system_protontricks')
        self.protontricks_radio.setToolTip(
            "Use system-installed protontricks (flatpak or native). Required for component installation."
        )
        self.component_method_group.addButton(self.protontricks_radio, 0)
        component_method_layout.addWidget(self.protontricks_radio)

        # Winetricks (alternative)
        self.winetricks_radio = QRadioButton("Winetricks (Alternative)")
        self.winetricks_radio.setChecked(current_method == 'winetricks')
        self.winetricks_radio.setToolTip(
            "Use bundled winetricks instead. May work when protontricks unavailable."
        )
        self.component_method_group.addButton(self.winetricks_radio, 1)
        component_method_layout.addWidget(self.winetricks_radio)
        
        component_layout.addLayout(component_method_layout)

        advanced_layout.addWidget(component_group)
        advanced_layout.addStretch()  # Add stretch to push content to top

        self.tab_widget.addTab(advanced_tab, "Advanced")

    def _toggle_api_key_visibility(self, checked):
        # Always use the same eyeball icon, only change color when toggled
        eye_icon = QIcon.fromTheme("view-visible")
        if not eye_icon.isNull():
            self.api_show_btn.setIcon(eye_icon)
            self.api_show_btn.setText("")
        else:
            self.api_show_btn.setIcon(QIcon())
            self.api_show_btn.setText("\U0001F441")  # 👁
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
            self.api_show_btn.setStyleSheet("QToolButton { color: #4fc3f7; }")  # Jackify blue
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
            self.api_show_btn.setStyleSheet("")

    def _pick_directory(self, line_edit):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text() or os.path.expanduser("~"))
        if dir_path:
            line_edit.setText(dir_path)

    def _show_help(self):
        from jackify.frontends.gui.services.message_service import MessageService
        MessageService.information(self, "Help", "Help/documentation coming soon!", safety_level="low")

    def _load_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_json(self, path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            MessageService.warning(self, "Error", f"Failed to save {path}: {e}", safety_level="medium")

    def _clear_api_key(self):
        self.api_key_edit.setText("")
        self.config_handler.clear_api_key()
        MessageService.information(self, "API Key Cleared", "Nexus API Key has been cleared.", safety_level="low")

    def _on_api_key_changed(self, text):
        """Handle immediate API key saving when text changes"""
        api_key = text.strip()
        self.config_handler.save_api_key(api_key)

    def _update_oauth_status(self):
        """Update OAuth status label and button"""
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        auth_service = NexusAuthService()
        authenticated, method, username = auth_service.get_auth_status()

        if authenticated and method == 'oauth':
            self.oauth_status_label.setText(f"Authorised as {username}" if username else "Authorised")
            self.oauth_status_label.setStyleSheet("color: #3fd0ea;")
            self.oauth_btn.setText("Revoke")
        elif method == 'oauth_expired':
            self.oauth_status_label.setText("OAuth token expired")
            self.oauth_status_label.setStyleSheet("color: #FFA726;")
            self.oauth_btn.setText("Re-authorise")
        else:
            self.oauth_status_label.setText("Not authorised")
            self.oauth_status_label.setStyleSheet("color: #f44336;")
            self.oauth_btn.setText("Authorise")

    def _handle_oauth_click(self):
        """Handle OAuth button click (Authorise or Revoke)"""
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        from jackify.frontends.gui.services.message_service import MessageService
        from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication
        from PySide6.QtCore import Qt

        auth_service = NexusAuthService()
        authenticated, method, _ = auth_service.get_auth_status()

        if authenticated and method == 'oauth':
            # Revoke OAuth
            reply = MessageService.question(self, "Revoke", "Revoke OAuth authorisation?", safety_level="low")
            if reply == QMessageBox.Yes:
                auth_service.revoke_oauth()
                self._update_oauth_status()
                MessageService.information(self, "Revoked", "OAuth authorisation has been revoked.", safety_level="low")
        else:
            # Authorise with OAuth
            reply = MessageService.question(self, "Authorise with Nexus",
                "Your browser will open for Nexus authorisation.\n\n"
                "Note: Your browser may ask permission to open 'xdg-open'\n"
                "or Jackify's protocol handler - please click 'Open' or 'Allow'.\n\n"
                "Please log in and authorise Jackify when prompted.\n\n"
                "Continue?", safety_level="low")

            if reply != QMessageBox.Yes:
                return

            progress = QProgressDialog(
                "Waiting for authorisation...\n\nPlease check your browser.",
                "Cancel",
                0, 0,
                self
            )
            progress.setWindowTitle("Nexus OAuth")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(400)
            progress.show()
            QApplication.processEvents()

            def show_message(msg):
                progress.setLabelText(f"Waiting for authorisation...\n\n{msg}")
                QApplication.processEvents()

            success = auth_service.authorize_oauth(show_browser_message_callback=show_message)
            progress.close()
            QApplication.processEvents()

            self._update_oauth_status()

            if success:
                _, _, username = auth_service.get_auth_status()
                msg = "OAuth authorisation successful!"
                if username:
                    msg += f"\n\nAuthorised as: {username}"
                MessageService.information(self, "Success", msg, safety_level="low")
            else:
                MessageService.warning(self, "Failed", "OAuth authorisation failed or was cancelled.", safety_level="low")

    def _get_proton_10_path(self):
        """Get Proton 10 path if available, fallback to auto"""
        try:
            from jackify.backend.handlers.wine_utils import WineUtils
            available_protons = WineUtils.scan_valve_proton_versions()

            # Look for Proton 10.x
            for proton in available_protons:
                if proton['version'].startswith('10.'):
                    return proton['path']

            # Fallback to auto if no Proton 10 found
            return 'auto'
        except:
            return 'auto'

    def _populate_install_proton_dropdown(self):
        """Populate Install Proton dropdown (Experimental/GE-Proton 10+ only for fast texture processing)"""
        try:
            from jackify.backend.handlers.wine_utils import WineUtils

            # Get all available Proton versions
            available_protons = WineUtils.scan_all_proton_versions()

            # Check if any Proton versions were found
            has_proton = len(available_protons) > 0

            # Add "Auto" or "No Proton" option first based on detection
            if has_proton:
                self.install_proton_dropdown.addItem("Auto (Recommended)", "auto")
            else:
                self.install_proton_dropdown.addItem("No Proton Versions Detected", "none")

            # Filter for fast Proton versions only
            fast_protons = []
            slow_protons = []

            for proton in available_protons:
                proton_name = proton.get('name', 'Unknown Proton')
                proton_type = proton.get('type', 'Unknown')

                is_fast_proton = False

                # Fast Protons: Experimental, GE-Proton 10+
                if proton_name == "Proton - Experimental":
                    is_fast_proton = True
                elif proton_type == 'GE-Proton':
                    # For GE-Proton, check major_version field
                    major_version = proton.get('major_version', 0)
                    if major_version >= 10:
                        is_fast_proton = True

                if is_fast_proton:
                    if proton_type == 'GE-Proton':
                        display_name = f"{proton_name} (GE)"
                    else:
                        display_name = proton_name
                    fast_protons.append((display_name, str(proton['path'])))
                else:
                    # Slow Protons: Valve 9, 10 beta, older GE-Proton, etc.
                    if proton_type == 'GE-Proton':
                        display_name = f"{proton_name} (GE) (Slow texture processing)"
                    else:
                        display_name = f"{proton_name} (Slow texture processing)"
                    slow_protons.append((display_name, str(proton['path'])))

            # Add fast Protons first
            for display_name, path in fast_protons:
                self.install_proton_dropdown.addItem(display_name, path)

            # Add separator and slow Protons with warnings
            if slow_protons:
                self.install_proton_dropdown.insertSeparator(self.install_proton_dropdown.count())
                for display_name, path in slow_protons:
                    self.install_proton_dropdown.addItem(display_name, path)

            # Load saved preference
            saved_proton = self.config_handler.get('proton_path', self._get_proton_10_path())
            self._set_dropdown_selection(self.install_proton_dropdown, saved_proton)

        except Exception as e:
            logger.error(f"Failed to populate install Proton dropdown: {e}")
            self.install_proton_dropdown.addItem("Auto (Recommended)", "auto")

    def _populate_game_proton_dropdown(self):
        """Populate Game Proton dropdown (any Proton 9+ for game compatibility)"""
        try:
            from jackify.backend.handlers.wine_utils import WineUtils

            # Get all available Proton versions
            available_protons = WineUtils.scan_all_proton_versions()

            # Add "Same as Install" option first
            self.game_proton_dropdown.addItem("Same as Install Proton", "same_as_install")

            # Add all Proton 9+ versions
            for proton in available_protons:
                proton_name = proton.get('name', 'Unknown Proton')
                proton_type = proton.get('type', 'Unknown')

                # Add type indicator for clarity
                if proton_type == 'GE-Proton':
                    display_name = f"{proton_name} (GE)"
                else:
                    display_name = proton_name

                self.game_proton_dropdown.addItem(display_name, str(proton['path']))

            # Load saved preference
            saved_game_proton = self.config_handler.get('game_proton_path', 'same_as_install')
            self._set_dropdown_selection(self.game_proton_dropdown, saved_game_proton)

        except Exception as e:
            logger.error(f"Failed to populate game Proton dropdown: {e}")
            self.game_proton_dropdown.addItem("Same as Install Proton", "same_as_install")

    def _set_dropdown_selection(self, dropdown, saved_value):
        """Helper to set dropdown selection based on saved value"""
        found_match = False
        for i in range(dropdown.count()):
            if dropdown.itemData(i) == saved_value:
                dropdown.setCurrentIndex(i)
                found_match = True
                break

        # If no exact match and not auto/same_as_install, select first option
        if not found_match and saved_value not in ["auto", "same_as_install"]:
            dropdown.setCurrentIndex(0)

    def _refresh_install_proton_dropdown(self):
        """Refresh Install Proton dropdown"""
        current_selection = self.install_proton_dropdown.currentData()
        self.install_proton_dropdown.clear()
        self._populate_install_proton_dropdown()
        self._set_dropdown_selection(self.install_proton_dropdown, current_selection)

    def _refresh_game_proton_dropdown(self):
        """Refresh Game Proton dropdown"""
        current_selection = self.game_proton_dropdown.currentData()
        self.game_proton_dropdown.clear()
        self._populate_game_proton_dropdown()
        self._set_dropdown_selection(self.game_proton_dropdown, current_selection)

    def _save(self):
        try:
            # Validate values (only if resource_edits exist)
            for k, (multithreading_checkbox, max_tasks_spin) in self.resource_edits.items():
                if max_tasks_spin.value() > 128:
                    self.error_label.setText(f"Invalid value for {k}: Max Tasks must be <= 128.")
                    return
            if self.bandwidth_spin and self.bandwidth_spin.value() > 1000000:
                self.error_label.setText("Bandwidth limit must be <= 1,000,000 KB/s.")
                return
            self.error_label.setText("")

            # Save resource settings
            for k, (multithreading_checkbox, max_tasks_spin) in self.resource_edits.items():
                resource_data = self.resource_settings.get(k, {})
                resource_data['MaxTasks'] = max_tasks_spin.value()
                self.resource_settings[k] = resource_data

            # Save bandwidth limit to Downloads resource MaxThroughput (only if bandwidth UI exists)
            if self.bandwidth_spin:
                if "Downloads" not in self.resource_settings:
                    self.resource_settings["Downloads"] = {"MaxTasks": 16}  # Provide default MaxTasks
                # Convert KB/s to bytes/s for storage (resource_settings.json expects bytes)
                bandwidth_kb = self.bandwidth_spin.value()
                bandwidth_bytes = bandwidth_kb * 1024
                self.resource_settings["Downloads"]["MaxThroughput"] = bandwidth_bytes

            # Save all resource settings (including bandwidth) in one operation
            self._save_json(self.resource_settings_path, self.resource_settings)

            # Save debug mode to config
            self.config_handler.set('debug_mode', self.debug_checkbox.isChecked())
            # OAuth disabled for v0.1.8 - no fallback setting needed
            # Save API key
            api_key = self.api_key_edit.text().strip()
            self.config_handler.save_api_key(api_key)
            # Save modlist base dirs
            self.config_handler.set("modlist_install_base_dir", self.install_dir_edit.text().strip())
            self.config_handler.set("modlist_downloads_base_dir", self.download_dir_edit.text().strip())
            # Save jackify data directory (always store actual path, never None)
            jackify_data_dir = self.jackify_data_dir_edit.text().strip()
            self.config_handler.set("jackify_data_dir", jackify_data_dir)

            # Initialize with existing config values as fallback (prevents UnboundLocalError if auto-detection fails)
            resolved_install_path = self.config_handler.get("proton_path", "")
            resolved_install_version = self.config_handler.get("proton_version", "")

            # Save Install Proton selection - resolve "auto" to actual path
            selected_install_proton_path = self.install_proton_dropdown.currentData()
            if selected_install_proton_path == "none":
                # No Proton detected - warn user but allow saving other settings
                MessageService.warning(
                    self,
                    "No Compatible Proton Installed",
                    "Jackify requires Proton 9.0+, Proton Experimental, or GE-Proton 10+ to install modlists.\n\n"
                    "To install Proton:\n"
                    "1. Install any Windows game in Steam (Proton downloads automatically), OR\n"
                    "2. Install GE-Proton using ProtonPlus or ProtonUp-Qt, OR\n"
                    "3. Download GE-Proton manually from:\n"
                    "   https://github.com/GloriousEggroll/proton-ge-custom/releases\n\n"
                    "Your other settings will be saved, but modlist installation may not work without Proton.",
                    safety_level="medium"
                )
                logger.warning("No Proton detected - user warned, allowing save to proceed for other settings")
                # Don't modify Proton config, but continue to save other settings
            elif selected_install_proton_path == "auto":
                # Resolve "auto" to actual best Proton path using unified detection
                try:
                    from jackify.backend.handlers.wine_utils import WineUtils
                    best_proton = WineUtils.select_best_proton()

                    if best_proton:
                        resolved_install_path = str(best_proton['path'])
                        resolved_install_version = best_proton['name']
                        self.config_handler.set("proton_path", resolved_install_path)
                        self.config_handler.set("proton_version", resolved_install_version)
                    else:
                        # No Proton found - don't write anything, let engine auto-detect
                        logger.warning("Auto Proton selection failed: No Proton versions found")
                        # Don't modify existing config values
                except Exception as e:
                    # Exception during detection - log it and don't write anything
                    logger.error(f"Auto Proton selection failed with exception: {e}", exc_info=True)
                    # Don't modify existing config values
            else:
                # User selected specific Proton version
                resolved_install_path = selected_install_proton_path
                resolved_install_version = self.install_proton_dropdown.currentText()
                self.config_handler.set("proton_path", resolved_install_path)
                self.config_handler.set("proton_version", resolved_install_version)

            # Save Game Proton selection
            selected_game_proton_path = self.game_proton_dropdown.currentData()
            if selected_game_proton_path == "same_as_install":
                # Use same as install proton
                resolved_game_path = resolved_install_path
                resolved_game_version = resolved_install_version
            else:
                # User selected specific game Proton version
                resolved_game_path = selected_game_proton_path
                resolved_game_version = self.game_proton_dropdown.currentText()

            self.config_handler.set("game_proton_path", resolved_game_path)
            self.config_handler.set("game_proton_version", resolved_game_version)

            # Save component installation method preference
            if self.winetricks_radio.isChecked():
                method = 'winetricks'
            else:  # protontricks_radio (default)
                method = 'system_protontricks'

            old_method = self.config_handler.get('component_installation_method', 'winetricks')
            method_changed = (old_method != method)

            self.config_handler.set("component_installation_method", method)
            self.config_handler.set("use_winetricks_for_components", method == 'winetricks')

            # Force immediate save and verify
            save_result = self.config_handler.save_config()
            if not save_result:
                self.logger.error("Failed to save Proton configuration")
            else:
                self.logger.info(f"Saved Proton config: install_path={resolved_install_path}, game_path={resolved_game_path}")
                # Verify the save worked by reading it back
                saved_path = self.config_handler.get("proton_path")
                if saved_path != resolved_install_path:
                    self.logger.error(f"Config save verification failed: expected {resolved_install_path}, got {saved_path}")
                else:
                    self.logger.debug("Config save verified successfully")

            # Refresh cached paths in GUI screens if Jackify directory changed
            self._refresh_gui_paths()

            # Check if debug mode changed and prompt for restart
            new_debug_mode = self.debug_checkbox.isChecked()
            if new_debug_mode != self._original_debug_mode:
                reply = MessageService.question(self, "Restart Required", "Debug mode change requires a restart. Restart Jackify now?", safety_level="low")
                if reply == QMessageBox.Yes:
                    import os, sys
                    # User requested restart - do it regardless of execution environment
                    self.accept()

                    # Check if running from AppImage
                    if os.environ.get('APPIMAGE'):
                        # AppImage: restart the AppImage
                        os.execv(os.environ['APPIMAGE'], [os.environ['APPIMAGE']] + sys.argv[1:])
                    else:
                        # Dev mode: restart the Python module
                        os.execv(sys.executable, [sys.executable, '-m', 'jackify.frontends.gui'] + sys.argv[1:])
                    return

            # If we get here, no restart was needed
            # Check protontricks if user just switched to it
            if method_changed and method == 'system_protontricks':
                main_window = self.parent()
                if main_window and hasattr(main_window, 'protontricks_service'):
                    is_installed, installation_type, details = main_window.protontricks_service.detect_protontricks(use_cache=False)
                    if not is_installed:
                        from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                        dialog = ProtontricksErrorDialog(main_window.protontricks_service, main_window)
                        dialog.exec()

            MessageService.information(self, "Settings Saved", "Settings have been saved successfully.", safety_level="low")
            self.accept()

        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
            MessageService.warning(self, "Save Error", f"Failed to save settings: {e}", safety_level="medium")

    def _refresh_gui_paths(self):
        """Refresh cached paths in all GUI screens."""
        try:
            # Get the main window through parent relationship
            main_window = self.parent()
            if not main_window or not hasattr(main_window, 'stacked_widget'):
                return
            
            # Refresh paths in all screens that have the method
            screens_to_refresh = [
                getattr(main_window, 'install_modlist_screen', None),
                getattr(main_window, 'configure_new_modlist_screen', None),
                getattr(main_window, 'configure_existing_modlist_screen', None),
            ]
            
            for screen in screens_to_refresh:
                if screen and hasattr(screen, 'refresh_paths'):
                    screen.refresh_paths()
                    
        except Exception as e:
            print(f"Warning: Could not refresh GUI paths: {e}")

    def _bold_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; color: #fff;")
        return label


class JackifyMainWindow(QMainWindow):
    """Main window for Jackify GUI application"""
    
    def __init__(self, dev_mode=False):
        super().__init__()
        self.setWindowTitle("Jackify")
        self._window_margin = 32
        self._base_min_width = 900
        self._base_min_height = 520
        self._compact_height = 640
        self._details_extra_height = 360
        self._initial_show_adjusted = False
        
        # Track open dialogs to prevent duplicates
        self._settings_dialog = None
        self._about_dialog = None
        
        # Ensure GNOME/Ubuntu exposes full set of window controls (avoid hidden buttons)
        self._apply_standard_window_flags()
        try:
            self.setSizeGripEnabled(True)
        except AttributeError:
            pass
        
        # Set default responsive minimum constraints before restoring geometry
        self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
        
        # Restore window geometry from QSettings (standard Qt approach)
        self._restore_geometry()
        self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
        
        # Initialize backend services
        self._initialize_backend()

        # Set up UI
        self._setup_ui(dev_mode=dev_mode)

        # Start background preload of gallery cache for instant gallery opening
        self._start_gallery_cache_preload()

        # DISABLED: Window geometry saving causes issues with expanded state being memorized
        # QApplication.instance().aboutToQuit.connect(self._save_geometry_on_quit)
        # self.resizeEvent = self._on_resize_event_geometry
    
    def _apply_standard_window_flags(self):
        window_flags = self.windowFlags()
        window_flags |= (
            Qt.Window |
            Qt.WindowTitleHint |
            Qt.WindowSystemMenuHint |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )
        window_flags &= ~Qt.CustomizeWindowHint
        self.setWindowFlags(window_flags)
    
    def _restore_geometry(self):
        """Restore window geometry from QSettings (standard Qt approach)"""
        # DISABLED: Don't restore saved geometry to avoid expanded state issues
        # Always start with fresh calculated size
        width, height = self._calculate_initial_window_size()
        # Ensure we use compact height, not expanded
        height = min(height, self._compact_height)
        self.resize(width, height)
        self._center_on_screen(width, height)
    
    def _save_geometry_on_quit(self):
        """Save window geometry on application quit (only if in compact mode)"""
        # Only save if window is in compact mode (not expanded with "Show Details")
        # Also ensure we don't save expanded geometry - always start collapsed
        if self._is_compact_mode():
            self._save_geometry()
        else:
            # If Show Details is enabled, clear saved geometry so we start collapsed next time
            from PySide6.QtCore import QSettings
            settings = QSettings("Jackify", "Jackify")
            settings.remove("windowGeometry")
    
    def _is_compact_mode(self) -> bool:
        """Check if window is in compact mode (not expanded with Show Details)"""
        # Check if any child screen has "Show Details" checked
        try:
            if hasattr(self, 'install_modlist_screen'):
                if hasattr(self.install_modlist_screen, 'show_details_checkbox'):
                    if self.install_modlist_screen.show_details_checkbox.isChecked():
                        return False
            if hasattr(self, 'install_ttw_screen'):
                if hasattr(self.install_ttw_screen, 'show_details_checkbox'):
                    if self.install_ttw_screen.show_details_checkbox.isChecked():
                        return False
            if hasattr(self, 'configure_new_modlist_screen'):
                if hasattr(self.configure_new_modlist_screen, 'show_details_checkbox'):
                    if self.configure_new_modlist_screen.show_details_checkbox.isChecked():
                        return False
            if hasattr(self, 'configure_existing_modlist_screen'):
                if hasattr(self.configure_existing_modlist_screen, 'show_details_checkbox'):
                    if self.configure_existing_modlist_screen.show_details_checkbox.isChecked():
                        return False
        except Exception:
            pass
        return True
    
    def _save_geometry(self):
        """Save window geometry to QSettings"""
        from PySide6.QtCore import QSettings
        settings = QSettings("Jackify", "Jackify")
        settings.setValue("windowGeometry", self.saveGeometry())

    def apply_responsive_minimum(self, min_width: int = 1100, min_height: int = 600):
        """Apply minimum size that respects current screen bounds."""
        set_responsive_minimum(self, min_width=min_width, min_height=min_height, margin=self._window_margin)

    def _calculate_initial_window_size(self):
        """Determine initial window size that fits within available screen space."""
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return (self._base_min_width, self._base_min_height)
        
        width = min(
            max(self._base_min_width, int(screen_width * 0.85)),
            screen_width - self._window_margin
        )
        height = min(
            max(self._base_min_height, int(screen_height * 0.75)),
            screen_height - self._window_margin
        )
        return (width, height)

    def _center_on_screen(self, width: int, height: int):
        """Center window on the current screen."""
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.move(x, y)

    def _ensure_within_available_geometry(self):
        """Ensure restored geometry fits on the visible screen."""
        from PySide6.QtCore import QRect
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return
        current_geometry: QRect = self.geometry()
        new_width = min(current_geometry.width(), screen_width - self._window_margin)
        new_height = min(current_geometry.height(), screen_height - self._window_margin)
        new_width = max(new_width, self.minimumWidth())
        new_height = max(new_height, self.minimumHeight())
        new_x = min(max(current_geometry.x(), 0), screen_width - new_width)
        new_y = min(max(current_geometry.y(), 0), screen_height - new_height)
        self.setGeometry(new_x, new_y, new_width, new_height)
    
    def _on_resize_event_geometry(self, event):
        """Handle window resize - save geometry if in compact mode"""
        super().resizeEvent(event)
        # Save geometry with a delay to avoid excessive writes
        # Only save if in compact mode
        if self._is_compact_mode():
            from PySide6.QtCore import QTimer
            if not hasattr(self, '_geometry_save_timer'):
                self._geometry_save_timer = QTimer()
                self._geometry_save_timer.setSingleShot(True)
                self._geometry_save_timer.timeout.connect(self._save_geometry)
            self._geometry_save_timer.stop()
            self._geometry_save_timer.start(500)  # Save after 500ms of no resizing
    
    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_show_adjusted:
            self._initial_show_adjusted = True
            # On Steam Deck, keep maximized state; on other systems, set normal window state
            if not (hasattr(self, 'system_info') and self.system_info.is_steamdeck):
                self.setWindowState(Qt.WindowNoState)
                self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
                self._ensure_within_available_geometry()
    
    def _initialize_backend(self):
        """Initialize backend services for direct use (no subprocess)"""
        # Detect Steam installation types once at startup
        from ...shared.steam_utils import detect_steam_installation_types
        is_flatpak, is_native = detect_steam_installation_types()

        # Determine system info with Steam detection
        self.system_info = SystemInfo(
            is_steamdeck=self._is_steamdeck(),
            is_flatpak_steam=is_flatpak,
            is_native_steam=is_native
        )

        # Apply resource limits for optimal operation
        self._apply_resource_limits()

        # Initialize config handler
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.config_handler = ConfigHandler()

        # Initialize backend services
        self.backend_services = {
            'modlist_service': ModlistService(self.system_info)
        }

        # Initialize GUI services
        self.gui_services = {}

        # Initialize protontricks detection service
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        self.protontricks_service = ProtontricksDetectionService(steamdeck=self.system_info.is_steamdeck)

        # Initialize update service
        from jackify.backend.services.update_service import UpdateService
        self.update_service = UpdateService(__version__)
        
        debug_print(f"GUI Backend initialized - Steam Deck: {self.system_info.is_steamdeck}")
    
    def _is_steamdeck(self):
        """Check if running on Steam Deck"""
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                    if "steamdeck" in content:
                        return True
            return False
        except Exception:
            return False
    
    def _apply_resource_limits(self):
        """Apply recommended resource limits for optimal Jackify operation"""
        try:
            from jackify.backend.services.resource_manager import ResourceManager
            
            resource_manager = ResourceManager()
            success = resource_manager.apply_recommended_limits()
            
            if success:
                status = resource_manager.get_limit_status()
                if status['target_achieved']:
                    debug_print(f"Resource limits optimized: file descriptors set to {status['current_soft']}")
                else:
                    print(f"Resource limits improved: file descriptors increased to {status['current_soft']} (target: {status['target_limit']})")
            else:
                # Log the issue but don't block startup
                status = resource_manager.get_limit_status()
                print(f"Warning: Could not optimize resource limits: current file descriptors={status['current_soft']}, target={status['target_limit']}")
                
                # Check if debug mode is enabled for additional info
                from jackify.backend.handlers.config_handler import ConfigHandler
                config_handler = ConfigHandler()
                if config_handler.get('debug_mode', False):
                    instructions = resource_manager.get_manual_increase_instructions()
                    print(f"Manual increase instructions available for {instructions['distribution']}")
                    
        except Exception as e:
            # Don't block startup on resource management errors
            print(f"Warning: Error applying resource limits: {e}")
    
    def _setup_ui(self, dev_mode=False):
        """Set up the user interface"""
        # Create stacked widget for screen navigation
        self.stacked_widget = QStackedWidget()
        
        # Create screens using refactored codebase
        from jackify.frontends.gui.screens import (
            MainMenu, ModlistTasksScreen, AdditionalTasksScreen,
            InstallModlistScreen, ConfigureNewModlistScreen, ConfigureExistingModlistScreen
        )
        from jackify.frontends.gui.screens.install_ttw import InstallTTWScreen
        from jackify.frontends.gui.screens.wabbajack_installer import WabbajackInstallerScreen

        self.main_menu = MainMenu(stacked_widget=self.stacked_widget, dev_mode=dev_mode)
        self.feature_placeholder = FeaturePlaceholder(stacked_widget=self.stacked_widget)
        
        self.modlist_tasks_screen = ModlistTasksScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0,
            dev_mode=dev_mode
        )
        self.additional_tasks_screen = AdditionalTasksScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0,
            system_info=self.system_info
        )
        self.install_modlist_screen = InstallModlistScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0
        )
        self.configure_new_modlist_screen = ConfigureNewModlistScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0
        )
        self.configure_existing_modlist_screen = ConfigureExistingModlistScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0
        )
        self.install_ttw_screen = InstallTTWScreen(
            stacked_widget=self.stacked_widget,
            main_menu_index=0,
            system_info=self.system_info
        )
        self.wabbajack_installer_screen = WabbajackInstallerScreen(
            stacked_widget=self.stacked_widget,
            additional_tasks_index=3,
            system_info=self.system_info
        )

        # Let TTW screen request window resize for expand/collapse
        try:
            self.install_ttw_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        # Let Install Modlist screen request window resize for expand/collapse
        try:
            self.install_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        # Let Configure screens request window resize for expand/collapse
        try:
            self.configure_new_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        try:
            self.configure_existing_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        # Let Wabbajack Installer screen request window resize for expand/collapse
        try:
            self.wabbajack_installer_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        
        # Add screens to stacked widget
        self.stacked_widget.addWidget(self.main_menu)           # Index 0: Main Menu
        self.stacked_widget.addWidget(self.feature_placeholder) # Index 1: Placeholder
        self.stacked_widget.addWidget(self.modlist_tasks_screen)  # Index 2: Modlist Tasks
        self.stacked_widget.addWidget(self.additional_tasks_screen)  # Index 3: Additional Tasks
        self.stacked_widget.addWidget(self.install_modlist_screen)        # Index 4: Install Modlist
        self.stacked_widget.addWidget(self.install_ttw_screen)            # Index 5: Install TTW
        self.stacked_widget.addWidget(self.configure_new_modlist_screen)  # Index 6: Configure New
        self.stacked_widget.addWidget(self.wabbajack_installer_screen)    # Index 7: Wabbajack Installer
        self.stacked_widget.addWidget(self.configure_existing_modlist_screen)  # Index 8: Configure Existing

        # Add debug tracking for screen changes
        self.stacked_widget.currentChanged.connect(self._debug_screen_change)
        # Ensure fullscreen is maintained on Steam Deck when switching screens
        self.stacked_widget.currentChanged.connect(self._maintain_fullscreen_on_deck)
        
        # --- Persistent Bottom Bar ---
        bottom_bar = QWidget()
        bottom_bar_layout = QHBoxLayout()
        bottom_bar_layout.setContentsMargins(10, 2, 10, 2)
        bottom_bar_layout.setSpacing(0)
        bottom_bar.setLayout(bottom_bar_layout)
        bottom_bar.setFixedHeight(32)
        bottom_bar_style = "background-color: #181818; border-top: 1px solid #222;"
        if DEBUG_BORDERS:
            bottom_bar_style += " border: 2px solid lime;"
        bottom_bar.setStyleSheet(bottom_bar_style)

        # Version label (left)
        version_label = QLabel(f"Jackify v{__version__}")
        version_label.setStyleSheet("color: #bbb; font-size: 13px;")
        bottom_bar_layout.addWidget(version_label, alignment=Qt.AlignLeft)

        # Spacer
        bottom_bar_layout.addStretch(1)

        # Ko-Fi support link (center)
        kofi_link = QLabel('<a href="#" style="color:#72A5F2; text-decoration:none;">♥ Support on Ko-fi</a>')
        kofi_link.setStyleSheet("color: #72A5F2; font-size: 13px;")
        kofi_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_link.setOpenExternalLinks(False)
        kofi_link.linkActivated.connect(lambda: self._open_url("https://ko-fi.com/omni1"))
        kofi_link.setToolTip("Support Jackify development")
        bottom_bar_layout.addWidget(kofi_link, alignment=Qt.AlignCenter)

        # Spacer
        bottom_bar_layout.addStretch(1)

        # Settings button (right side)
        settings_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">Settings</a>')
        settings_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        settings_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        settings_btn.setOpenExternalLinks(False)
        settings_btn.linkActivated.connect(self.open_settings_dialog)
        bottom_bar_layout.addWidget(settings_btn, alignment=Qt.AlignRight)

        # About button (right side)
        about_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">About</a>')
        about_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        about_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_btn.setOpenExternalLinks(False)
        about_btn.linkActivated.connect(self.open_about_dialog)
        bottom_bar_layout.addWidget(about_btn, alignment=Qt.AlignRight)

        # --- Main Layout ---
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        # Don't use stretch - let screens size to their content
        main_layout.addWidget(self.stacked_widget)  # Screen sizes to content
        main_layout.addWidget(bottom_bar)  # Bottom bar stays at bottom
        # Set stacked widget to not expand unnecessarily
        self.stacked_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Start with main menu
        self.stacked_widget.setCurrentIndex(0)
        
        # Check for protontricks after UI is set up
        self._check_protontricks_on_startup()

    def _maintain_fullscreen_on_deck(self, index):
        """Maintain maximized state on Steam Deck when switching screens."""
        if hasattr(self, 'system_info') and self.system_info.is_steamdeck:
            # Ensure window stays maximized on Steam Deck
            if not self.isMaximized():
                self.showMaximized()
    
    def _debug_screen_change(self, index):
        """Handle screen changes - debug logging and state reset"""
        # Reset screen state when switching to workflow screens
        widget = self.stacked_widget.widget(index)
        if widget and hasattr(widget, 'reset_screen_to_defaults'):
            widget.reset_screen_to_defaults()

        # Only show debug info if debug mode is enabled
        from jackify.backend.handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        if not config_handler.get('debug_mode', False):
            return
            
        screen_names = {
            0: "Main Menu",
            1: "Feature Placeholder",
            2: "Modlist Tasks Menu",
            3: "Additional Tasks Menu",
            4: "Install Modlist Screen",
            5: "Install TTW Screen",
            6: "Configure New Modlist",
            7: "Wabbajack Installer",
            8: "Configure Existing Modlist",
        }
        screen_name = screen_names.get(index, f"Unknown Screen (Index {index})")
        widget = self.stacked_widget.widget(index)
        widget_class = widget.__class__.__name__ if widget else "None"
        # Only print screen change debug to stderr to avoid workflow log pollution
        import sys
        print(f"[DEBUG] Screen changed to Index {index}: {screen_name} (Widget: {widget_class})", file=sys.stderr)
        
        # Additional debug for the install modlist screen
        if index == 4:
            print(f"   Install Modlist Screen details:", file=sys.stderr)
            print(f"      - Widget type: {type(widget)}", file=sys.stderr)
            print(f"      - Widget file: {widget.__class__.__module__}", file=sys.stderr)
            if hasattr(widget, 'windowTitle'):
                print(f"      - Window title: {widget.windowTitle()}", file=sys.stderr)
            if hasattr(widget, 'layout'):
                layout = widget.layout()
                if layout:
                    print(f"      - Layout type: {type(layout)}", file=sys.stderr)
                    print(f"      - Layout children count: {layout.count()}", file=sys.stderr)
        
    def _start_gallery_cache_preload(self):
        """Start background preloading of modlist metadata for instant gallery opening"""
        from PySide6.QtCore import QThread, Signal

        # Create background thread to preload gallery cache
        class GalleryCachePreloadThread(QThread):
            finished_signal = Signal(bool, str)

            def run(self):
                try:
                    from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
                    service = ModlistGalleryService()

                    # Fetch with search index to build cache (invisible background operation)
                    metadata = service.fetch_modlist_metadata(
                        include_validation=False,  # Skip validation for speed
                        include_search_index=True,  # Include mods for search
                        sort_by="title",
                        force_refresh=False  # Use cache if valid
                    )

                    if metadata:
                        modlists_with_mods = sum(1 for m in metadata.modlists if hasattr(m, 'mods') and m.mods)
                        if modlists_with_mods > 0:
                            debug_print(f"Gallery cache ready ({modlists_with_mods} modlists with mods)")
                        else:
                            debug_print("Gallery cache updated")
                    else:
                        debug_print("Failed to load gallery cache")

                except Exception as e:
                    debug_print(f"Gallery cache preload error: {str(e)}")

        # Start thread (non-blocking, runs in background)
        self._gallery_cache_preload_thread = GalleryCachePreloadThread()
        self._gallery_cache_preload_thread.start()

        debug_print("Started background gallery cache preload")

    def _check_protontricks_on_startup(self):
        """Check for protontricks installation on startup"""
        try:
            # Only check for protontricks if user has selected it in settings
            method = self.config_handler.get('component_installation_method', 'winetricks')
            if method != 'system_protontricks':
                debug_print(f"Skipping protontricks check (current method: {method}).")
                return

            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            
            if not is_installed:
                print(f"Protontricks not found: {details}")
                # Show error dialog
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                
                if result == QDialog.Rejected:
                    # User chose to exit
                    print("User chose to exit due to missing protontricks")
                    sys.exit(1)
            else:
                debug_print(f"Protontricks detected: {details}")
                
        except Exception as e:
            print(f"Error checking protontricks: {e}")
            # Continue anyway - don't block startup on detection errors
    
    def _check_for_updates_on_startup(self):
        """Check for updates on startup - non-blocking background check"""
        try:
            debug_print("Checking for updates on startup...")
            
            # Run update check in background thread to avoid blocking GUI startup
            class UpdateCheckThread(QThread):
                update_available = Signal(object)  # Signal to pass update_info to main thread
                
                def __init__(self, update_service):
                    super().__init__()
                    self.update_service = update_service
                
                def run(self):
                    update_info = self.update_service.check_for_updates()
                    if update_info:
                        self.update_available.emit(update_info)
            
            def on_update_available(update_info):
                """Handle update check result in main thread"""
                debug_print(f"Update available: v{update_info.version}")
                
                # Show update dialog after a short delay to ensure GUI is fully loaded
                def show_update_dialog():
                    from .dialogs.update_dialog import UpdateDialog
                    dialog = UpdateDialog(update_info, self.update_service, self)
                    dialog.exec()
                
                QTimer.singleShot(1000, show_update_dialog)
            
            # Start background thread
            self._update_thread = UpdateCheckThread(self.update_service)
            self._update_thread.update_available.connect(on_update_available)
            self._update_thread.start()
            
        except Exception as e:
            debug_print(f"Error setting up update check: {e}")
            # Continue anyway - don't block startup on update check errors
    
    def cleanup_processes(self):
        """Clean up any running processes before closing"""
        try:
            # Clean up background threads first
            if hasattr(self, '_update_thread') and self._update_thread is not None:
                if self._update_thread.isRunning():
                    self._update_thread.quit()
                    self._update_thread.wait(2000)
                self._update_thread = None

            if hasattr(self, '_gallery_cache_preload_thread') and self._gallery_cache_preload_thread is not None:
                if self._gallery_cache_preload_thread.isRunning():
                    self._gallery_cache_preload_thread.quit()
                    self._gallery_cache_preload_thread.wait(2000)
                self._gallery_cache_preload_thread = None

            # Clean up GUI services
            for service in self.gui_services.values():
                if hasattr(service, 'cleanup'):
                    service.cleanup()

            # Clean up screen processes
            screens = [
                self.modlist_tasks_screen, self.install_modlist_screen,
                self.configure_new_modlist_screen, self.configure_existing_modlist_screen
            ]
            for screen in screens:
                if hasattr(screen, 'cleanup_processes'):
                    screen.cleanup_processes()
                elif hasattr(screen, 'cleanup'):
                    screen.cleanup()
            
            # Final safety net: kill any remaining jackify-engine processes
            try:
                import subprocess
                subprocess.run(['pkill', '-f', 'jackify-engine'], timeout=5, capture_output=True)
            except Exception:
                pass  # pkill might fail if no processes found, which is fine
                    
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def closeEvent(self, event):
        """Handle window close event"""
        self.cleanup_processes()
        event.accept()

    def open_settings_dialog(self):
        """Open settings dialog, preventing duplicate instances"""
        try:
            # Check if dialog already exists and is visible
            if self._settings_dialog is not None:
                try:
                    if self._settings_dialog.isVisible():
                        # Dialog is already open - raise it to front
                        self._settings_dialog.raise_()
                        self._settings_dialog.activateWindow()
                        return
                    else:
                        # Dialog exists but is closed - clean up reference
                        self._settings_dialog = None
                except RuntimeError:
                    # Dialog was deleted - clean up reference
                    self._settings_dialog = None
            
            # Create new dialog
            dlg = SettingsDialog(self)
            self._settings_dialog = dlg
            
            # Clean up reference when dialog is closed
            def on_dialog_finished():
                self._settings_dialog = None
            
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_settings_dialog: {e}")
            import traceback
            traceback.print_exc()
            self._settings_dialog = None

    def open_about_dialog(self):
        """Open about dialog, preventing duplicate instances"""
        try:
            from jackify.frontends.gui.dialogs.about_dialog import AboutDialog
            
            # Check if dialog already exists and is visible
            if self._about_dialog is not None:
                try:
                    if self._about_dialog.isVisible():
                        # Dialog is already open - raise it to front
                        self._about_dialog.raise_()
                        self._about_dialog.activateWindow()
                        return
                    else:
                        # Dialog exists but is closed - clean up reference
                        self._about_dialog = None
                except RuntimeError:
                    # Dialog was deleted - clean up reference
                    self._about_dialog = None
            
            # Create new dialog
            dlg = AboutDialog(self.system_info, self)
            self._about_dialog = dlg
            
            # Clean up reference when dialog is closed
            def on_dialog_finished():
                self._about_dialog = None
            
            dlg.finished.connect(on_dialog_finished)
            dlg.exec()
        except Exception as e:
            print(f"[ERROR] Exception in open_about_dialog: {e}")
            import traceback
            traceback.print_exc()
            self._about_dialog = None

    def _open_url(self, url: str):
        """Open URL with clean environment to avoid AppImage library conflicts."""
        import subprocess
        import os

        env = os.environ.copy()

        # Remove AppImage-specific environment variables
        appimage_vars = [
            'LD_LIBRARY_PATH',
            'PYTHONPATH',
            'PYTHONHOME',
            'QT_PLUGIN_PATH',
            'QML2_IMPORT_PATH',
        ]

        if 'APPIMAGE' in env or 'APPDIR' in env:
            for var in appimage_vars:
                if var in env:
                    del env[var]

        subprocess.Popen(
            ['xdg-open', url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def _on_child_resize_request(self, mode: str):
        """
        Handle child screen resize requests (expand/collapse console).
        Allow window expansion/collapse for Show Details toggle, but keep fixed sizing for navigation.
        """
        debug_print(f"DEBUG: _on_child_resize_request called with mode='{mode}', current_size={self.size()}")
        # On Steam Deck we keep the stable, full-size layout and ignore child resize
        try:
            if self.system_info and self.system_info.is_steamdeck:
                debug_print("DEBUG: Steam Deck detected, ignoring resize request")
                # Hide the checkbox if present (Deck uses full layout)
                try:
                    if hasattr(self, 'install_ttw_screen') and self.install_ttw_screen.show_details_checkbox:
                        self.install_ttw_screen.show_details_checkbox.setVisible(False)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # Allow expansion/collapse for Show Details toggle
        # This is different from navigation resizing - we want this to work
        if mode == "expand":
            # Expand window to accommodate console
            current_size = self.size()
            current_pos = self.pos()
            # Calculate target height and clamp to available space
            target_height = self._compact_height + self._details_extra_height
            self._resize_height(target_height)
        elif mode == "collapse":
            # Collapse window back to compact size
            self._resize_height(self._compact_height)
        else:
            # Unknown mode - just ensure minimums
            self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
            
    def _resize_height(self, requested_height: int):
        """Resize the window to a given height while keeping it on-screen."""
        target_height = self._clamp_height_to_screen(requested_height)
        self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
        if ENABLE_WINDOW_HEIGHT_ANIMATION:
            self._animate_height(target_height)
            return
        
        geom = self.geometry()
        new_y = geom.y()
        _, _, _, screen_height = get_screen_geometry(self)
        max_bottom = max(self._base_min_height, screen_height - self._window_margin)
        if new_y + target_height > max_bottom:
            new_y = max(0, max_bottom - target_height)
        self._programmatic_resize = True
        self.setGeometry(geom.x(), new_y, geom.width(), target_height)
        QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))

    def _clamp_height_to_screen(self, requested_height: int) -> int:
        """Clamp requested height to available screen space."""
        _, _, _, screen_height = get_screen_geometry(self)
        available = max(self._base_min_height, screen_height - self._window_margin)
        return max(self._base_min_height, min(requested_height, available))
    
    def _animate_height(self, target_height: int, duration_ms: int = 180):
        """Smoothly animate the window height to target_height.

        Kept local imports to minimize global impact and avoid touching module headers.
        """
        try:
            from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect
        except Exception:
            # Fallback to immediate resize if animation types are unavailable
            before = self.size()
            self._programmatic_resize = True
            self.resize(self.size().width(), target_height)
            debug_print(f"DEBUG: Animated fallback resize from {before} to {self.size()}")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))
            return

        # Build end rect with same x/y/width and target height
        start_rect = self.geometry()
        end_rect = QRect(start_rect.x(), start_rect.y(), start_rect.width(), self._clamp_height_to_screen(target_height))
        
        # Check if expanded window would go off-screen and adjust position if needed
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            # Calculate where bottom would be with target_height
            would_be_bottom = start_rect.y() + target_height
            if would_be_bottom > screen_geometry.bottom():
                # Window would go off bottom - move it up
                new_y = screen_geometry.bottom() - target_height
                if new_y < screen_geometry.top():
                    new_y = screen_geometry.top()
                end_rect.moveTop(new_y)

        # Hold reference to avoid GC stopping the animation
        self._resize_anim = QPropertyAnimation(self, b"geometry")
        self._resize_anim.setDuration(duration_ms)
        self._resize_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._resize_anim.setStartValue(start_rect)
        self._resize_anim.setEndValue(end_rect)
        # Mark as programmatic during animation
        self._programmatic_resize = True
        self._resize_anim.finished.connect(lambda: setattr(self, '_programmatic_resize', False))
        self._resize_anim.start()



def resource_path(relative_path):
    """Get path to resource file, handling both AppImage and dev modes."""
    # AppImage mode - use APPDIR if available
    appdir = os.environ.get('APPDIR')
    if appdir:
        # In AppImage, resources are in opt/jackify/ relative to APPDIR
        # __file__ is at opt/jackify/frontends/gui/main.py, so go up to opt/jackify/
        appimage_path = os.path.join(appdir, 'opt', 'jackify', relative_path)
        if os.path.exists(appimage_path):
            return appimage_path
    
    # Dev mode or fallback - go up from frontends/gui to jackify, then to assets
    # __file__ is at src/jackify/frontends/gui/main.py, so go up to src/jackify/
    current_dir = os.path.abspath(os.path.dirname(__file__))
    # Go up from frontends/gui to jackify
    jackify_dir = os.path.dirname(os.path.dirname(current_dir))
    return os.path.join(jackify_dir, relative_path)


def main():
    """Main entry point for the GUI application"""
    # CRITICAL: Enable faulthandler for segfault debugging
    # This will print Python stack traces on segfault
    import faulthandler
    import signal
    # Enable faulthandler to both stderr and file
    try:
        log_dir = Path.home() / '.local' / 'share' / 'jackify' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        trace_file = open(log_dir / 'segfault_trace.txt', 'w')
        faulthandler.enable(file=trace_file, all_threads=True)
    except Exception:
        # Fallback to stderr only if file can't be opened
        faulthandler.enable(all_threads=True)
    
    # Check for CLI mode argument
    if len(sys.argv) > 1 and '--cli' in sys.argv:
        # Launch CLI frontend instead of GUI
        try:
            from jackify.frontends.cli.__main__ import main as cli_main
            print("CLI mode detected - switching to CLI frontend")
            return cli_main()
        except ImportError as e:
            print(f"Error importing CLI frontend: {e}")
            print("CLI mode not available. Falling back to GUI mode.")
    
    # Load config and set debug mode if needed
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    debug_mode = config_handler.get('debug_mode', False)
    # Command-line --debug always takes precedence
    if '--debug' in sys.argv or '-d' in sys.argv:
        debug_mode = True
        # Temporarily save CLI debug flag to config so engine can see it
        config_handler.set('debug_mode', True)
    import logging

    # Initialize file logging on root logger so all modules inherit it
    from jackify.shared.logging import LoggingHandler
    logging_handler = LoggingHandler()
    # Only rotate log file when debug mode is enabled
    if debug_mode:
        logging_handler.rotate_log_for_logger('jackify_gui', 'jackify-gui.log')
    root_logger = logging_handler.setup_logger('', 'jackify-gui.log', is_general=True, debug_mode=debug_mode)  # Empty name = root logger
    
    # CRITICAL: Set root logger level BEFORE any child loggers are used
    # This ensures DEBUG messages from child loggers propagate correctly
    if debug_mode:
        root_logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)  # Also set on root via getLogger() for compatibility
        root_logger.debug("CLI --debug flag detected, saved debug_mode=True to config")
        root_logger.info("Debug mode enabled (from config or CLI)")
    else:
        root_logger.setLevel(logging.WARNING)
        logging.getLogger().setLevel(logging.WARNING)
    
    # Root logger should not propagate (it's the top level)
    # Child loggers will propagate to root logger by default (unless they explicitly set propagate=False)
    root_logger.propagate = False

    dev_mode = '--dev' in sys.argv

    # Launch GUI application
    app = QApplication(sys.argv)
    # CRITICAL: Set application name before desktop file name to ensure proper window title/icon on PopOS/Ubuntu
    app.setApplicationName("Jackify")
    app.setApplicationDisplayName("Jackify")
    app.setDesktopFileName("jackify.desktop")

    # Global cleanup function for signal handling
    def emergency_cleanup():
        debug_print("Cleanup: terminating jackify-engine processes")
        try:
            import subprocess
            subprocess.run(['pkill', '-f', 'jackify-engine'], timeout=5, capture_output=True)
        except Exception:
            pass
    
    # Set up signal handlers for graceful shutdown
    import signal
    def signal_handler(sig, frame):
        print(f"Received signal {sig}, cleaning up...")
        emergency_cleanup()
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # System shutdown
    
    # Set the application icon
    # Try multiple locations - AppImage build script places icon in standard locations
    icon_path = None
    icon = QIcon()
    
    # Priority 1: Try resource_path (works in dev mode and if assets are in AppImage)
    try_path = resource_path('assets/JackifyLogo_256.png')
    if os.path.exists(try_path):
        icon_path = try_path
        icon = QIcon(try_path)
    
    # Priority 2: Try standard AppImage icon locations (where build script actually places it)
    if icon.isNull():
        appdir = os.environ.get('APPDIR')
        if appdir:
            appimage_icon_paths = [
                os.path.join(appdir, 'com.jackify.app.png'),  # Root of AppDir
                os.path.join(appdir, 'usr', 'share', 'icons', 'hicolor', '256x256', 'apps', 'com.jackify.app.png'),  # Standard location
                os.path.join(appdir, 'opt', 'jackify', 'assets', 'JackifyLogo_256.png'),  # If assets are copied
            ]
            for path in appimage_icon_paths:
                if os.path.exists(path):
                    icon_path = path
                    icon = QIcon(path)
                    if not icon.isNull():
                        if debug_mode:
                            logging.getLogger().debug(f"Using AppImage icon: {path}")
                        break
    
    # Priority 3: Fallback to any PNG in assets directory
    if icon.isNull():
        try_path = resource_path('assets/JackifyLogo_256.png')
        if os.path.exists(try_path):
            icon_path = try_path
            icon = QIcon(try_path)
    
    if debug_mode:
        logging.getLogger().debug(f"Final icon path: {icon_path}")
        logging.getLogger().debug(f"Icon is null: {icon.isNull()}")
    
    app.setWindowIcon(icon)
    window = JackifyMainWindow(dev_mode=dev_mode)
    window.setWindowIcon(icon)
    window.show()
    
    # On Steam Deck, set window to maximized to prevent button overlap with Show Details console
    if hasattr(window, 'system_info') and window.system_info.is_steamdeck:
        window.showMaximized()
    else:
        # Position window after showing (so size is finalized)
        # Center horizontally, position near top (10% from top) to leave room for expansion
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            window_size = window.size()
            x = (screen_geometry.width() - window_size.width()) // 2
            y = int(screen_geometry.top() + (screen_geometry.height() * 0.1))  # 10% from top
            window.move(x, y)
    
    # Start background update check after window is shown
    window._check_for_updates_on_startup()
    
    # Ensure cleanup on exit
    import atexit
    atexit.register(emergency_cleanup)
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main()) 