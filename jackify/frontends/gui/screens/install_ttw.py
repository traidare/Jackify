
"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QFrame
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, strip_ansi_control_codes, set_responsive_minimum
from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
import os
import subprocess
import sys
import threading
from jackify.backend.handlers.shortcut_handler import ShortcutHandler
from jackify.backend.handlers.wabbajack_parser import WabbajackParser
import traceback
from jackify.backend.core.modlist_operations import get_jackify_engine_path
import signal
import re
import time
from jackify.backend.handlers.subprocess_utils import ProcessManager
from jackify.backend.handlers.config_handler import ConfigHandler
from ..dialogs import SuccessDialog
from jackify.backend.handlers.validation_handler import ValidationHandler
from jackify.frontends.gui.dialogs.warning_dialog import WarningDialog
from jackify.frontends.gui.services.message_service import MessageService

def debug_print(message):
    """Print debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        print(message)

class ModlistFetchThread(QThread):
    result = Signal(list, str)
    def __init__(self, game_type, log_path, mode='list-modlists'):
        super().__init__()
        self.game_type = game_type
        self.log_path = log_path
        self.mode = mode
    
    def run(self):
        try:
            # Use proper backend service - NOT the misnamed CLI class
            from jackify.backend.services.modlist_service import ModlistService
            from jackify.backend.models.configuration import SystemInfo
            
            # Initialize backend service
            # Detect if we're on Steam Deck
            is_steamdeck = False
            try:
                if os.path.exists('/etc/os-release'):
                    with open('/etc/os-release') as f:
                        if 'steamdeck' in f.read().lower():
                            is_steamdeck = True
            except Exception:
                pass
            
            system_info = SystemInfo(is_steamdeck=is_steamdeck)
            modlist_service = ModlistService(system_info)
            
            # Get modlists using proper backend service
            modlist_infos = modlist_service.list_modlists(game_type=self.game_type)
            
            # Return full modlist objects instead of just IDs to preserve enhanced metadata
            self.result.emit(modlist_infos, '')
            
        except Exception as e:
            error_msg = f"Backend service error: {str(e)}"
            # Don't write to log file before workflow starts - just return error
            self.result.emit([], error_msg)


class InstallTTWScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    resize_request = Signal(str)
    integration_complete = Signal(bool, str)  # Signal for modlist integration completion (success, ttw_version)

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info=None):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.system_info = system_info
        self.debug = DEBUG_BORDERS
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Initialize log path (can be refreshed via refresh_paths method)
        self.refresh_paths()

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()

        # Modlist integration mode tracking
        self._integration_mode = False
        self._integration_modlist_name = None
        self._integration_install_dir = None

        # Somnium guidance tracking
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        # Remember original main window geometry/min-size to restore on expand
        self._saved_geometry = None
        self._saved_min_size = None

        main_overall_vbox = QVBoxLayout(self)
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        # Match other workflow screens
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)
        main_overall_vbox.setSpacing(12)
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        # Title
        title = QLabel("<b>Install Tale of Two Wastelands (TTW)</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        # Description area with fixed height
        desc = QLabel(
            "This screen allows you to install Tale of Two Wastelands (TTW) using TTW_Linux_Installer. "
            "Configure your options and start the installation."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)  # Fixed height for description zone
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)

        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)  # Fixed total header height to match other screens
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
        user_config_vbox.setSpacing(4)  # Reduce spacing between major form sections
        
        # --- Instructions ---
        instruction_text = QLabel(
            "Tale of Two Wastelands installation requires a .mpi file you can get from: "
            '<a href="https://mod.pub/ttw/133/files">https://mod.pub/ttw/133/files</a> '
            "(requires a user account for ModPub)"
        )
        instruction_text.setWordWrap(True)
        instruction_text.setStyleSheet("color: #ccc; font-size: 12px; margin: 0px; padding: 0px; line-height: 1.2;")
        instruction_text.setOpenExternalLinks(True)
        user_config_vbox.addWidget(instruction_text)
        
        # --- Compact Form Grid for inputs (align with other screens) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)
        form_grid.setContentsMargins(0, 0, 0, 0)

        # Row 0: TTW .mpi File location
        file_label = QLabel("TTW .mpi File location:")
        self.file_edit = QLineEdit()
        self.file_edit.setMaximumHeight(25)
        self.file_edit.textChanged.connect(self._update_start_button_state)
        self.file_btn = QPushButton("Browse")
        self.file_btn.clicked.connect(self.browse_wabbajack_file)
        file_hbox = QHBoxLayout()
        file_hbox.addWidget(self.file_edit)
        file_hbox.addWidget(self.file_btn)
        form_grid.addWidget(file_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(file_hbox, 0, 1)

        # Row 1: Output Directory
        install_dir_label = QLabel("Output Directory:")
        self.install_dir_edit = QLineEdit(self.config_handler.get_modlist_install_base_dir())
        self.install_dir_edit.setMaximumHeight(25)
        self.browse_install_btn = QPushButton("Browse")
        self.browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(self.browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)

        # --- TTW_Linux_Installer Status aligned in form grid (row 2) ---
        ttw_installer_label = QLabel("TTW_Linux_Installer Status:")
        self.ttw_installer_status = QLabel("Checking...")
        self.ttw_installer_btn = QPushButton("Install now")
        self.ttw_installer_btn.setStyleSheet("""
            QPushButton:hover { opacity: 0.95; }
            QPushButton:disabled { opacity: 0.6; }
        """)
        self.ttw_installer_btn.setVisible(False)
        self.ttw_installer_btn.clicked.connect(self.install_ttw_installer)
        ttw_installer_hbox = QHBoxLayout()
        ttw_installer_hbox.setContentsMargins(0, 0, 0, 0)
        ttw_installer_hbox.setSpacing(8)
        ttw_installer_hbox.addWidget(self.ttw_installer_status)
        ttw_installer_hbox.addWidget(self.ttw_installer_btn)
        ttw_installer_hbox.addStretch()
        form_grid.addWidget(ttw_installer_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(ttw_installer_hbox, 2, 1)

        # --- Game Requirements aligned in form grid (row 3) ---
        game_req_label = QLabel("Game Requirements:")
        self.fallout3_status = QLabel("Fallout 3: Checking...")
        self.fallout3_status.setStyleSheet("color: #ccc;")
        self.fnv_status = QLabel("Fallout New Vegas: Checking...")
        self.fnv_status.setStyleSheet("color: #ccc;")
        game_req_hbox = QHBoxLayout()
        game_req_hbox.setContentsMargins(0, 0, 0, 0)
        game_req_hbox.setSpacing(16)
        game_req_hbox.addWidget(self.fallout3_status)
        game_req_hbox.addWidget(self.fnv_status)
        game_req_hbox.addStretch()
        form_grid.addWidget(game_req_label, 3, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(game_req_hbox, 3, 1)

        form_group = QWidget()
        form_group.setLayout(form_grid)
        user_config_vbox.addWidget(form_group)
        
        # (TTW_Linux_Installer and Game Requirements now aligned in form_grid above)
        
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Installation")
        self.start_btn.setEnabled(False)  # Disabled until requirements are met
        btn_row.addWidget(self.start_btn)
        

        
        # Cancel button (goes back to menu)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_and_cleanup)
        btn_row.addWidget(self.cancel_btn)
        
        # Cancel Installation button (appears during installation)
        self.cancel_install_btn = QPushButton("Cancel Installation")
        self.cancel_install_btn.clicked.connect(self.cancel_installation)
        self.cancel_install_btn.setVisible(False)  # Hidden by default
        btn_row.addWidget(self.cancel_install_btn)

        # Add stretches to center buttons row
        btn_row.insertStretch(0, 1)
        btn_row.addStretch(1)

        # Show Details Checkbox (collapsible console)
        self.show_details_checkbox = QCheckBox("Show details")
        # Start collapsed by default (console hidden until user opts in)
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        # Use toggled(bool) for reliable signal and map to our handler
        try:
            self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)
        except Exception:
            # Fallback to stateChanged if toggled is unavailable
            self.show_details_checkbox.stateChanged.connect(self._toggle_console_visibility)
        # Note: Checkbox will be placed in the status banner row (right-aligned)

        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)  # Limit height to make it more compact
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        # Keep a reference for dynamic sizing when collapsing/expanding
        self.btn_row_widget = btn_row_widget
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        if self.debug:
            user_config_widget.setStyleSheet("border: 2px solid orange;")
            user_config_widget.setToolTip("USER_CONFIG_WIDGET")

        # Right: Tabbed interface with Activity and Process Monitor
        # Both tabs are always available, user can switch between them
        self.file_progress_list = FileProgressList()
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
        self.upper_section_widget = QWidget()
        self.upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy for consistent height
        self.upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.upper_section_widget.setMaximumHeight(280)  # Fixed height to match other workflow screens
        if self.debug:
            self.upper_section_widget.setStyleSheet("border: 2px solid green;")
            self.upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(self.upper_section_widget)

        # --- Status Banner (shows high-level progress) ---
        self.status_banner = QLabel("Ready to install")
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 6px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)
        # Prevent banner from expanding vertically
        self.status_banner.setMaximumHeight(34)
        self.status_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Show the banner by default so users see status even when collapsed
        self.status_banner.setVisible(True)
        # Create a compact banner row with the checkbox right-aligned
        banner_row = QHBoxLayout()
        # Minimal padding to avoid visible gaps
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.status_banner, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)  # Compact height
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)

        # Remove spacing - console should expand to fill available space
        # --- Console output area (full width, placeholder for now) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        # Console starts hidden; toggled via Show details
        self.console.setMinimumHeight(0)
        self.console.setMaximumHeight(0)
        self.console.setFontFamily('monospace')
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        # Add console directly so we can hide/show without affecting buttons
        main_overall_vbox.addWidget(self.console, stretch=1)
        # Place the button row after the console so it's always visible and centered
        main_overall_vbox.addWidget(btn_row_widget, alignment=Qt.AlignHCenter)

        # Store reference to main layout
        self.main_overall_vbox = main_overall_vbox
        self.setLayout(main_overall_vbox)

        self.current_modlists = []

        # --- Process Monitor (right) ---
        self.process = None
        self.log_timer = None
        self.last_log_pos = 0
        # --- Process Monitor Timer ---
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.update_top_panel)
        self.top_timer.start(2000)
        # --- Start Installation button ---
        self.start_btn.clicked.connect(self.validate_and_start_install)
        self.steam_restart_finished.connect(self._on_steam_restart_finished)

        # Initialize process tracking
        self.process = None
        
        # Initialize empty controls list - will be populated after UI is built
        self._actionable_controls = []
    
    def check_requirements(self):
        """Check and display requirements status"""
        from jackify.backend.handlers.path_handler import PathHandler
        from jackify.backend.handlers.filesystem_handler import FileSystemHandler
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.backend.models.configuration import SystemInfo
        
        path_handler = PathHandler()
        
        # Check game detection
        detected_games = path_handler.find_vanilla_game_paths()
        
        # Fallout 3
        if 'Fallout 3' in detected_games:
            self.fallout3_status.setText("Fallout 3: Detected")
            self.fallout3_status.setStyleSheet("color: #3fd0ea;")
        else:
            self.fallout3_status.setText("Fallout 3: Not Found - Install from Steam")
            self.fallout3_status.setStyleSheet("color: #f44336;")
        
        # Fallout New Vegas
        if 'Fallout New Vegas' in detected_games:
            self.fnv_status.setText("Fallout New Vegas: Detected")
            self.fnv_status.setStyleSheet("color: #3fd0ea;")
        else:
            self.fnv_status.setText("Fallout New Vegas: Not Found - Install from Steam")
            self.fnv_status.setStyleSheet("color: #f44336;")
        
        # Update Start button state after checking requirements
        self._update_start_button_state()
    
    def _check_ttw_installer_status(self):
        """Check TTW_Linux_Installer installation status and update UI"""
        try:
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.handlers.filesystem_handler import FileSystemHandler
            from jackify.backend.handlers.config_handler import ConfigHandler
            from jackify.backend.models.configuration import SystemInfo
            
            # Create handler instances
            filesystem_handler = FileSystemHandler()
            config_handler = ConfigHandler()
            system_info = SystemInfo(is_steamdeck=False)
            ttw_installer_handler = TTWInstallerHandler(
                steamdeck=False,
                verbose=False,
                filesystem_handler=filesystem_handler,
                config_handler=config_handler
            )
            
            # Check if TTW_Linux_Installer is installed
            ttw_installer_handler._check_installation()

            if ttw_installer_handler.ttw_installer_installed:
                # Check version against latest
                update_available, installed_v, latest_v = ttw_installer_handler.is_ttw_installer_update_available()
                if update_available:
                    version_text = f"Out of date (v{installed_v} → v{latest_v})" if installed_v and latest_v else "Out of date"
                    self.ttw_installer_status.setText(version_text)
                    self.ttw_installer_status.setStyleSheet("color: #f44336;")
                    self.ttw_installer_btn.setText("Update now")
                    self.ttw_installer_btn.setEnabled(True)
                    self.ttw_installer_btn.setVisible(True)
                else:
                    version_text = f"Ready (v{installed_v})" if installed_v else "Ready"
                    self.ttw_installer_status.setText(version_text)
                    self.ttw_installer_status.setStyleSheet("color: #3fd0ea;")
                    self.ttw_installer_btn.setText("Update now")
                    self.ttw_installer_btn.setEnabled(False)  # Greyed out when ready
                    self.ttw_installer_btn.setVisible(True)
            else:
                self.ttw_installer_status.setText("Not Found")
                self.ttw_installer_status.setStyleSheet("color: #f44336;")
                self.ttw_installer_btn.setText("Install now")
                self.ttw_installer_btn.setEnabled(True)
                self.ttw_installer_btn.setVisible(True)
                
        except Exception as e:
            self.ttw_installer_status.setText("Check Failed")
            self.ttw_installer_status.setStyleSheet("color: #f44336;")
            self.ttw_installer_btn.setText("Install now")
            self.ttw_installer_btn.setEnabled(True)
            self.ttw_installer_btn.setVisible(True)
            debug_print(f"DEBUG: TTW_Linux_Installer status check failed: {e}")

    def install_ttw_installer(self):
        """Install or update TTW_Linux_Installer"""
        # If not detected, show info dialog
        try:
            current_status = self.ttw_installer_status.text().strip()
        except Exception:
            current_status = ""
        if current_status == "Not Found":
            MessageService.information(
                self,
                "TTW_Linux_Installer Installation",
                (
                    "TTW_Linux_Installer is a native Linux installer for TTW and other MPI packages.<br><br>"
                    "Project: <a href=\"https://github.com/SulfurNitride/TTW_Linux_Installer\">github.com/SulfurNitride/TTW_Linux_Installer</a><br>"
                    "Please star the repository and thank the developer.<br><br>"
                    "Jackify will now download and install the latest Linux build of TTW_Linux_Installer."
                ),
                safety_level="low",
            )

        # Update button to show installation in progress
        self.ttw_installer_btn.setText("Installing...")
        self.ttw_installer_btn.setEnabled(False)

        self.console.append("Installing/updating TTW_Linux_Installer...")

        # Create background thread for installation
        from PySide6.QtCore import QThread, Signal

        class InstallerDownloadThread(QThread):
            finished = Signal(bool, str)  # success, message
            progress = Signal(str)  # progress message

            def run(self):
                try:
                    from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
                    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    from jackify.backend.models.configuration import SystemInfo

                    # Create handler instances
                    filesystem_handler = FileSystemHandler()
                    config_handler = ConfigHandler()
                    system_info = SystemInfo(is_steamdeck=False)
                    ttw_installer_handler = TTWInstallerHandler(
                        steamdeck=False,
                        verbose=False,
                        filesystem_handler=filesystem_handler,
                        config_handler=config_handler
                    )

                    # Install TTW_Linux_Installer (this will download and extract)
                    self.progress.emit("Downloading TTW_Linux_Installer...")
                    success, message = ttw_installer_handler.install_ttw_installer()

                    if success:
                        install_path = ttw_installer_handler.ttw_installer_dir
                        self.progress.emit(f"Installation complete: {install_path}")
                    else:
                        self.progress.emit(f"Installation failed: {message}")

                    self.finished.emit(success, message)

                except Exception as e:
                    error_msg = f"Error installing TTW_Linux_Installer: {str(e)}"
                    self.progress.emit(error_msg)
                    debug_print(f"DEBUG: TTW_Linux_Installer installation error: {e}")
                    self.finished.emit(False, error_msg)

        # Create and start thread
        self.installer_download_thread = InstallerDownloadThread()
        self.installer_download_thread.progress.connect(self._on_installer_download_progress)
        self.installer_download_thread.finished.connect(self._on_installer_download_finished)
        self.installer_download_thread.start()
        
        # Update Activity window to show download in progress
        self.file_progress_list.clear()
        self.file_progress_list.update_or_add_item(
            item_id="ttw_installer_download",
            label="Downloading TTW_Linux_Installer...",
            progress=0
        )

    def _on_installer_download_progress(self, message):
        """Handle installer download progress updates"""
        self.console.append(message)
        # Update Activity window based on progress message
        if "Downloading" in message:
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="Downloading TTW_Linux_Installer...",
                progress=0  # Indeterminate progress
            )
        elif "Extracting" in message or "extracting" in message.lower():
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="Extracting TTW_Linux_Installer...",
                progress=50
            )
        elif "complete" in message.lower() or "successfully" in message.lower():
            self.file_progress_list.update_or_add_item(
                item_id="ttw_installer_download",
                label="TTW_Linux_Installer ready",
                progress=100
            )

    def _on_installer_download_finished(self, success, message):
        """Handle installer download completion"""
        if success:
            self.console.append("TTW_Linux_Installer installed successfully")
            # Clear Activity window after successful installation
            self.file_progress_list.clear()
            # Re-check status after installation (this will update button state correctly)
            self._check_ttw_installer_status()
            self._update_start_button_state()
        else:
            self.console.append(f"Installation failed: {message}")
            # Clear Activity window on failure
            self.file_progress_list.clear()
            # Re-enable button on failure so user can retry
            self.ttw_installer_btn.setText("Install now")
            self.ttw_installer_btn.setEnabled(True)
    
    def _check_ttw_requirements(self):
        """Check TTW requirements before installation"""
        from jackify.backend.handlers.path_handler import PathHandler
        
        path_handler = PathHandler()
        
        # Check game detection
        detected_games = path_handler.find_vanilla_game_paths()
        missing_games = []
        
        if 'Fallout 3' not in detected_games:
            missing_games.append("Fallout 3")
        if 'Fallout New Vegas' not in detected_games:
            missing_games.append("Fallout New Vegas")
        
        if missing_games:
            MessageService.warning(
                self, 
                "Missing Required Games", 
                f"TTW requires both Fallout 3 and Fallout New Vegas to be installed.\n\nMissing: {', '.join(missing_games)}"
            )
            return False
        
        # Check TTW_Linux_Installer using the status we already checked
        status_text = self.ttw_installer_status.text()
        if status_text in ("Not Found", "Check Failed"):
            MessageService.warning(
                self,
                "TTW_Linux_Installer Required",
                "TTW_Linux_Installer is required for TTW installation but is not installed.\n\nPlease install TTW_Linux_Installer using the 'Install now' button."
            )
            return False
        
        return True
        
        # Now collect all actionable controls after UI is fully built
        self._collect_actionable_controls()
        
        # Check if all requirements are met and enable/disable Start button
        self._update_start_button_state()
    
    def _update_start_button_state(self):
        """Enable/disable Start button based on requirements and file selection"""
        # Check if all requirements are met
        requirements_met = self._check_ttw_requirements()
        
        # Check if .mpi file is selected
        mpi_file_selected = bool(self.file_edit.text().strip())
        
        # Enable Start button only if both requirements are met and file is selected
        self.start_btn.setEnabled(requirements_met and mpi_file_selected)
        
        # Update button text to indicate what's missing
        if not requirements_met:
            self.start_btn.setText("Requirements Not Met")
        elif not mpi_file_selected:
            self.start_btn.setText("Select TTW .mpi File")
        else:
            self.start_btn.setText("Start Installation")
    
    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # File selection
            self.file_edit,
            self.file_btn,
            # Install directory
            self.install_dir_edit,
            self.browse_install_btn,
        ]

    def _disable_controls_during_operation(self):
        """Disable all actionable controls during install/configure operations (except Cancel)"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(False)

    def _enable_controls_after_operation(self):
        """Re-enable all actionable controls after install/configure operations complete"""
        for control in self._actionable_controls:
            if control:
                control.setEnabled(True)

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'TTW_Install_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def set_modlist_integration_mode(self, modlist_name: str, install_dir: str):
        """Set the screen to modlist integration mode

        This mode is activated when TTW needs to be installed and integrated
        into an existing modlist. In this mode, after TTW installation completes,
        the TTW output will be automatically integrated into the modlist.

        Args:
            modlist_name: Name of the modlist to integrate TTW into
            install_dir: Installation directory of the modlist
        """
        self._integration_mode = True
        self._integration_modlist_name = modlist_name
        self._integration_install_dir = install_dir

        # Reset saved geometry so showEvent can properly collapse from current window size
        self._saved_geometry = None
        self._saved_min_size = None

        # Update UI to show integration mode
        debug_print(f"TTW screen set to integration mode for modlist: {modlist_name}")
        debug_print(f"Installation directory: {install_dir}")

    def _open_url_safe(self, url):
        """Safely open URL via subprocess to avoid Qt library clashes inside the AppImage runtime"""
        import subprocess
        try:
            subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Warning: Could not open URL {url}: {e}")

    def force_collapsed_state(self):
        """Force the screen into its collapsed state regardless of prior layout.

        This is used to resolve timing/race conditions when navigating here from
        the end of the Install Modlist workflow, ensuring the UI opens collapsed
        just like when launched from Additional Tasks.
        """
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting user-facing signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            # Apply collapsed layout explicitly
            self._toggle_console_visibility(_Qt.Unchecked)
            # Inform parent window to collapse height
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass
        except Exception:
            pass

    def resizeEvent(self, event):
        """Handle window resize to prioritize form over console"""
        super().resizeEvent(event)
        self._adjust_console_for_form_priority()

    def _adjust_console_for_form_priority(self):
        """Console now dynamically fills available space with stretch=1, no manual calculation needed"""
        # The console automatically fills remaining space due to stretch=1 in the layout
        # Remove any fixed height constraints to allow natural stretching
        self.console.setMaximumHeight(16777215)  # Reset to default maximum
        # Only enforce a small minimum when details are shown; keep 0 when collapsed
        if self.console.isVisible():
            self.console.setMinimumHeight(50)
        else:
            self.console.setMinimumHeight(0)

    def showEvent(self, event):
        """Called when the widget becomes visible"""
        super().showEvent(event)
        debug_print(f"DEBUG: TTW showEvent - integration_mode={self._integration_mode}")
        
        # Check TTW_Linux_Installer status asynchronously (non-blocking) after screen opens
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._check_ttw_installer_status)

        # Ensure initial collapsed layout each time this screen is opened
        try:
            from PySide6.QtCore import Qt as _Qt
            # On Steam Deck: keep expanded layout and hide the details toggle
            try:
                is_steamdeck = False
                # Check our own system_info first
                if self.system_info and getattr(self.system_info, 'is_steamdeck', False):
                    is_steamdeck = True
                # Fallback to checking parent window's system_info
                elif not self.system_info:
                    parent = self.window()
                    if parent and hasattr(parent, 'system_info') and getattr(parent.system_info, 'is_steamdeck', False):
                        is_steamdeck = True

                if is_steamdeck:
                    debug_print("DEBUG: Steam Deck detected, keeping expanded")
                    # Force expanded state and hide checkbox
                    if self.show_details_checkbox.isVisible():
                        self.show_details_checkbox.setVisible(False)
                    # Show console with proper sizing for Steam Deck
                    self.console.setVisible(True)
                    self.console.show()
                    self.console.setMinimumHeight(200)
                    self.console.setMaximumHeight(16777215)  # Remove height limit
                    return
            except Exception as e:
                debug_print(f"DEBUG: Steam Deck check exception: {e}")
                pass
            debug_print(f"DEBUG: Checkbox checked={self.show_details_checkbox.isChecked()}")
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            debug_print("DEBUG: Calling _toggle_console_visibility(Unchecked)")
            self._toggle_console_visibility(_Qt.Unchecked)
            # Force the window to compact height to eliminate bottom whitespace
            main_window = self.window()
            debug_print(f"DEBUG: main_window={main_window}, size={main_window.size() if main_window else None}")
            if main_window:
                # Save original geometry once
                if self._saved_geometry is None:
                    self._saved_geometry = main_window.geometry()
                    debug_print(f"DEBUG: Saved geometry: {self._saved_geometry}")
                if self._saved_min_size is None:
                    self._saved_min_size = main_window.minimumSize()
                    debug_print(f"DEBUG: Saved min size: {self._saved_min_size}")

                # Fixed compact size - same as menu screens
                from PySide6.QtCore import QSize
                # On Steam Deck, keep fullscreen; on other systems, set normal window state
                if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                    main_window.showNormal()
                # First, completely unlock the window
                main_window.setMinimumSize(QSize(0, 0))
                main_window.setMaximumSize(QSize(16777215, 16777215))
                # Only set minimum size - DO NOT RESIZE
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
                # Notify parent to ensure compact
                try:
                    self.resize_request.emit('collapse')
                    debug_print("DEBUG: Emitted resize_request collapse signal")
                except Exception as e:
                    debug_print(f"DEBUG: Exception emitting signal: {e}")
                    pass
        except Exception as e:
            debug_print(f"DEBUG: showEvent exception: {e}")
            import traceback
            debug_print(f"DEBUG: {traceback.format_exc()}")
            pass

    def hideEvent(self, event):
        """Called when the widget becomes hidden - restore window size constraints"""
        super().hideEvent(event)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                # Clear any size constraints that might have been set to prevent affecting other screens
                # This is especially important when the console is expanded
                main_window.setMaximumSize(QSize(16777215, 16777215))
                main_window.setMinimumSize(QSize(0, 0))
                debug_print("DEBUG: Install TTW hideEvent - cleared window size constraints")
        except Exception as e:
            debug_print(f"DEBUG: hideEvent exception: {e}")
            pass

    def _load_saved_parent_directories(self):
        """No-op: do not pre-populate install/download directories from saved values."""
        pass

    def _update_directory_suggestions(self, modlist_name):
        """Update directory suggestions based on modlist name"""
        try:
            if not modlist_name:
                return
                
            # Update install directory suggestion with modlist name
            saved_install_parent = self.config_handler.get_default_install_parent_dir()
            if saved_install_parent:
                suggested_install_dir = os.path.join(saved_install_parent, modlist_name)
                self.install_dir_edit.setText(suggested_install_dir)
                debug_print(f"DEBUG: Updated install directory suggestion: {suggested_install_dir}")
            
            # Update download directory suggestion
            saved_download_parent = self.config_handler.get_default_download_parent_dir()
            if saved_download_parent:
                suggested_download_dir = os.path.join(saved_download_parent, "Downloads")
                debug_print(f"DEBUG: Updated download directory suggestion: {suggested_download_dir}")
                
        except Exception as e:
            debug_print(f"DEBUG: Error updating directory suggestions: {e}")
    
    def _save_parent_directories(self, install_dir, downloads_dir):
        """Removed automatic saving - user should set defaults in settings"""
        pass






    def browse_wabbajack_file(self):
        # Use QFileDialog instance to ensure consistent dialog style
        start_path = self.file_edit.text() if self.file_edit.text() else os.path.expanduser("~")
        dialog = QFileDialog(self, "Select TTW .mpi File")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("MPI Files (*.mpi);;All Files (*)")
        dialog.setDirectory(start_path)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)  # Force Qt dialog for consistency
        if dialog.exec() == QDialog.Accepted:
            files = dialog.selectedFiles()
            if files:
                self.file_edit.setText(files[0])

    def browse_install_dir(self):
        # Use QFileDialog instance to match file browser style exactly
        dialog = QFileDialog(self, "Select Install Directory")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)  # Force Qt dialog to match file browser
        if self.install_dir_edit.text():
            dialog.setDirectory(self.install_dir_edit.text())
        if dialog.exec() == QDialog.Accepted:
            dirs = dialog.selectedFiles()
            if dirs:
                self.install_dir_edit.setText(dirs[0])


    def go_back(self):
        """Navigate back to main menu and restore window size"""
        # Restore window size before navigating away
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                
                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass
        
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index) 

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
                if (
                    ("jackify-engine" in line_lower or "7zz" in line_lower or "texconv" in line_lower or
                     "wine" in line_lower or "wine64" in line_lower or "protontricks" in line_lower or
                     "ttw_linux" in line_lower)
                    and "jackify-gui.py" not in line_lower
                ):
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
            MessageService.warning(self, "Protontricks Check Failed", 
                                 f"Unable to verify protontricks installation: {e}\n\n"
                                 "Continuing anyway, but some features may not work correctly.")
            return True  # Continue anyway

    

    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()
        debug_print('DEBUG: validate_and_start_install called')

        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()
        debug_print('DEBUG: Reloaded config from disk')

        # Check TTW requirements first
        if not self._check_ttw_requirements():
            return
        
        # Check protontricks before proceeding
        if not self._check_protontricks():
            return
        
        # Disable all controls during installation (except Cancel)
        self._disable_controls_during_operation()
        
        try:
            # TTW only needs .mpi file
            mpi_path = self.file_edit.text().strip()
            if not mpi_path or not os.path.isfile(mpi_path) or not mpi_path.endswith('.mpi'):
                MessageService.warning(self, "Invalid TTW File", "Please select a valid TTW .mpi file.")
                self._enable_controls_after_operation()
                return
            install_dir = self.install_dir_edit.text().strip()
            
            # Validate required fields
            missing_fields = []
            if not install_dir:
                missing_fields.append("Install Directory")
            if missing_fields:
                MessageService.warning(self, "Missing Required Fields", f"Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields))
                self._enable_controls_after_operation()
                return
            
            # Validate install directory
            validation_handler = ValidationHandler()
            from pathlib import Path
            install_dir_path = Path(install_dir)
            
            # Check for dangerous directories first (system roots, etc.)
            if validation_handler.is_dangerous_directory(install_dir_path):
                dlg = WarningDialog(
                    f"The directory '{install_dir}' is a system or user root and cannot be used for TTW installation.",
                    parent=self
                )
                if not dlg.exec() or not dlg.confirmed:
                    self._enable_controls_after_operation()
                    return
            
            # Check if directory exists and is not empty - TTW_Linux_Installer will overwrite existing files
            if install_dir_path.exists() and install_dir_path.is_dir():
                # Check if directory contains any files
                try:
                    has_files = any(install_dir_path.iterdir())
                    if has_files:
                        # Directory exists and is not empty - warn user about deletion
                        dlg = WarningDialog(
                            f"The TTW output directory already exists and contains files:\n{install_dir}\n\n"
                            f"All files in this directory will be deleted before installation.\n\n"
                            f"This action cannot be undone.",
                            parent=self
                        )
                        if not dlg.exec() or not dlg.confirmed:
                            self._enable_controls_after_operation()
                            return
                        
                        # User confirmed - delete all contents of the directory
                        import shutil
                        try:
                            for item in install_dir_path.iterdir():
                                if item.is_dir():
                                    shutil.rmtree(item)
                                else:
                                    item.unlink()
                            debug_print(f"DEBUG: Deleted all contents of {install_dir}")
                        except Exception as e:
                            MessageService.critical(self, "Error", f"Failed to delete directory contents:\n{e}")
                            self._enable_controls_after_operation()
                            return
                except Exception as e:
                    debug_print(f"DEBUG: Error checking directory contents: {e}")
                    # If we can't check, proceed
            
            if not os.path.isdir(install_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The install directory does not exist:\n{install_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create install directory:\n{e}")
                        self._enable_controls_after_operation()
                        return
                else:
                    self._enable_controls_after_operation()
                    return
            
            # Start TTW installation
            self.console.clear()
            self.process_monitor.clear()
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)
            
            debug_print(f'DEBUG: Calling run_ttw_installer with mpi_path={mpi_path}, install_dir={install_dir}')
            self.run_ttw_installer(mpi_path, install_dir)
        except Exception as e:
            debug_print(f"DEBUG: Exception in validate_and_start_install: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            # Re-enable all controls after exception
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            debug_print(f"DEBUG: Controls re-enabled in exception handler")

    def run_ttw_installer(self, mpi_path, install_dir):
        debug_print('DEBUG: run_ttw_installer called - USING THREADED BACKEND WRAPPER')

        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # This ensures Proton version and winetricks settings are current
        self.config_handler._load_config()

        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)

        # Clear console for fresh installation output
        self.console.clear()
        self._safe_append_text("Starting TTW installation...")

        # Initialize Activity window with immediate feedback
        self.file_progress_list.clear()
        self._update_ttw_phase("Initializing TTW installation", 0, 0, 0)
        # Force UI update immediately
        QApplication.processEvents()

        # Show status banner and show details checkbox
        self.status_banner.setVisible(True)
        self.status_banner.setText("Initializing TTW installation...")
        self.show_details_checkbox.setVisible(True)

        # Reset banner to default blue color for new installation
        self.status_banner.setStyleSheet(f"""
            background-color: #2a2a2a;
            color: {JACKIFY_COLOR_BLUE};
            padding: 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        """)

        self.ttw_start_time = time.time()

        # Start a timer to update elapsed time
        self.ttw_elapsed_timer = QTimer()
        self.ttw_elapsed_timer.timeout.connect(self._update_ttw_elapsed_time)
        self.ttw_elapsed_timer.start(1000)  # Update every second

        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        # Create installation thread
        from PySide6.QtCore import QThread, Signal
        
        class TTWInstallationThread(QThread):
            output_batch_received = Signal(list)  # Batched output lines
            progress_received = Signal(str)
            installation_finished = Signal(bool, str)

            def __init__(self, mpi_path, install_dir):
                super().__init__()
                self.mpi_path = mpi_path
                self.install_dir = install_dir
                self.cancelled = False
                self.proc = None
                self.output_buffer = []  # Buffer for batching output
                self.last_emit_time = 0  # Track when we last emitted

            def cancel(self):
                self.cancelled = True
                try:
                    if self.proc and self.proc.poll() is None:
                        self.proc.terminate()
                except Exception:
                    pass

            def process_and_buffer_line(self, raw_line):
                """Process line in worker thread and add to buffer"""
                # Strip ANSI codes
                cleaned = strip_ansi_control_codes(raw_line).strip()

                # Strip emojis (do this in worker thread, not UI thread)
                filtered_chars = []
                for char in cleaned:
                    code = ord(char)
                    is_emoji = (
                        (0x1F300 <= code <= 0x1F9FF) or
                        (0x1F600 <= code <= 0x1F64F) or
                        (0x2600 <= code <= 0x26FF) or
                        (0x2700 <= code <= 0x27BF)
                    )
                    if not is_emoji:
                        filtered_chars.append(char)
                cleaned = ''.join(filtered_chars).strip()

                # Only buffer non-empty lines
                if cleaned:
                    self.output_buffer.append(cleaned)

            def flush_output_buffer(self):
                """Emit buffered lines as a batch"""
                if self.output_buffer:
                    self.output_batch_received.emit(self.output_buffer[:])
                    self.output_buffer.clear()
                    self.last_emit_time = time.time()
            
            def run(self):
                try:
                    from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
                    from jackify.backend.handlers.filesystem_handler import FileSystemHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    from pathlib import Path
                    import tempfile

                    # Emit startup message
                    self.process_and_buffer_line("Initializing TTW installation...")
                    self.flush_output_buffer()

                    # Create backend handler
                    filesystem_handler = FileSystemHandler()
                    config_handler = ConfigHandler()
                    ttw_handler = TTWInstallerHandler(
                        steamdeck=False,
                        verbose=False,
                        filesystem_handler=filesystem_handler,
                        config_handler=config_handler
                    )

                    # Create temporary output file
                    output_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.ttw_output', encoding='utf-8')
                    output_file_path = Path(output_file.name)
                    output_file.close()

                    # Start installation via backend (non-blocking)
                    self.process_and_buffer_line("Starting TTW installation...")
                    self.flush_output_buffer()

                    self.proc, error_msg = ttw_handler.start_ttw_installation(
                        Path(self.mpi_path),
                        Path(self.install_dir),
                        output_file_path
                    )

                    if not self.proc:
                        self.installation_finished.emit(False, error_msg or "Failed to start TTW installation")
                        return

                    self.process_and_buffer_line("TTW_Linux_Installer process started, monitoring output...")
                    self.flush_output_buffer()

                    # Poll output file with batching for UI responsiveness
                    last_position = 0
                    BATCH_INTERVAL = 0.3  # Emit batches every 300ms

                    while self.proc.poll() is None:
                        if self.cancelled:
                            break

                        try:
                            # Read new content from file
                            with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                                f.seek(last_position)
                                new_lines = f.readlines()
                                last_position = f.tell()

                                # Process lines in worker thread (heavy work done here, not UI thread)
                                for line in new_lines:
                                    if self.cancelled:
                                        break
                                    self.process_and_buffer_line(line.rstrip())

                                # Emit batch if enough time has passed
                                current_time = time.time()
                                if current_time - self.last_emit_time >= BATCH_INTERVAL:
                                    self.flush_output_buffer()

                        except Exception:
                            pass

                        # Sleep longer since we're batching
                        time.sleep(0.1)

                    # Read any remaining output
                    try:
                        with open(output_file_path, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_position)
                            remaining_lines = f.readlines()
                            for line in remaining_lines:
                                self.process_and_buffer_line(line.rstrip())
                        self.flush_output_buffer()
                    except Exception:
                        pass

                    # Clean up
                    try:
                        output_file_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                    ttw_handler.cleanup_ttw_process(self.proc)

                    # Check result
                    returncode = self.proc.returncode if self.proc else -1
                    if self.cancelled:
                        self.installation_finished.emit(False, "Installation cancelled by user")
                    elif returncode == 0:
                        self.installation_finished.emit(True, "TTW installation completed successfully!")
                    else:
                        self.installation_finished.emit(False, f"TTW installation failed with exit code {returncode}")

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    self.installation_finished.emit(False, f"Installation error: {str(e)}")

        # Start the installation thread
        self.install_thread = TTWInstallationThread(mpi_path, install_dir)
        # Use QueuedConnection to ensure signals are processed asynchronously and don't block UI
        self.install_thread.output_batch_received.connect(self.on_installation_output_batch, Qt.QueuedConnection)
        self.install_thread.progress_received.connect(self.on_installation_progress, Qt.QueuedConnection)
        self.install_thread.installation_finished.connect(self.on_installation_finished, Qt.QueuedConnection)

        # Start thread and immediately process events to show initial UI state
        self.install_thread.start()
        QApplication.processEvents()  # Process any pending events to update UI immediately

    def on_installation_output_batch(self, messages):
        """Handle batched output from TTW_Linux_Installer (already processed in worker thread)"""
        # Lines are already cleaned (ANSI codes stripped, emojis removed) in worker thread
        # CRITICAL: Accumulate all console updates and do ONE widget update per batch

        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_current_phase = None
            self._ttw_last_progress = 0
            self._ttw_last_activity_update = 0
            self.ttw_start_time = time.time()

        # Accumulate lines to display (do ONE console update at end)
        lines_to_display = []
        html_fragments = []
        show_details_due_to_error = False
        latest_progress = None  # Track latest progress to update activity ONCE per batch

        for cleaned in messages:
            if not cleaned:
                continue

            lower_cleaned = cleaned.lower()

            # Extract progress (but don't update UI yet - wait until end of batch)
            try:
                progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
                if progress_match:
                    current = int(progress_match.group(1))
                    total = int(progress_match.group(2))
                    percent = int((current / total) * 100) if total > 0 else 0
                    latest_progress = (current, total, percent)

                if 'loading manifest:' in lower_cleaned:
                    manifest_match = re.search(r'loading manifest:\s*(\d+)/(\d+)', lower_cleaned)
                    if manifest_match:
                        current = int(manifest_match.group(1))
                        total = int(manifest_match.group(2))
                        self._ttw_current_phase = "Loading manifest"
            except Exception:
                pass

            # Determine if we should show this line
            is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
            is_warning = 'warning:' in lower_cleaned
            is_milestone = any(kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid'])
            is_file_op = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
            
            # Filter out meaningless standalone messages (just "OK", etc.)
            is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']
            
            should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)

            if should_show:
                if is_error or is_warning:
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_fragments.append(f'<span style="color: {color};">{escaped}</span>')
                    show_details_due_to_error = True
                else:
                    lines_to_display.append(cleaned)

        # Update activity widget ONCE per batch (if progress changed significantly)
        if latest_progress:
            current, total, percent = latest_progress
            current_time = time.time()
            percent_changed = abs(percent - self._ttw_last_progress) >= 1
            time_passed = (current_time - self._ttw_last_activity_update) >= 0.5  # 500ms throttle

            if percent_changed or time_passed:
                self._update_ttw_activity(current, total, percent)
                self._ttw_last_progress = percent
                self._ttw_last_activity_update = current_time

        # Now do ONE console update for entire batch
        if html_fragments or lines_to_display:
            try:
                # Update console with all accumulated output in one operation
                if html_fragments:
                    combined_html = '<br>'.join(html_fragments)
                    self.console.insertHtml(combined_html + '<br>')

                if lines_to_display:
                    combined_text = '\n'.join(lines_to_display)
                    self.console.append(combined_text)

                if show_details_due_to_error and not self.show_details_checkbox.isChecked():
                    self.show_details_checkbox.setChecked(True)
            except Exception:
                pass

    def on_installation_output(self, message):
        """Handle regular output from TTW_Linux_Installer with comprehensive filtering and smart parsing"""
        # Initialize tracking structures
        if not hasattr(self, '_ttw_seen_lines'):
            self._ttw_seen_lines = set()
            self._ttw_last_extraction_progress = 0
            self._ttw_last_file_operation_time = 0
            self._ttw_file_operation_count = 0
            self._ttw_current_phase = None
            self._ttw_last_progress_line = None
            self._ttw_progress_line_text = None
        
        # Filter out internal status messages from user console
        if message.strip().startswith('[Jackify]'):
            # Log internal messages to file but don't show in console
            self._write_to_log_file(message)
            return

        # Strip ANSI terminal control codes
        cleaned = strip_ansi_control_codes(message).strip()

        # Strip emojis from output (TTW_Linux_Installer includes emojis)
        # Common emojis: ✅ ❌ ⚠️ 🔍 💾 📁 🚀 🛑
        # Use character-by-character filtering to avoid regex recursion issues
        # This is safer than regex for emoji removal
        filtered_chars = []
        for char in cleaned:
            code = ord(char)
            # Check if character is in emoji ranges - skip emojis
            is_emoji = (
                (0x1F300 <= code <= 0x1F9FF) or  # Miscellaneous Symbols and Pictographs
                (0x1F600 <= code <= 0x1F64F) or  # Emoticons
                (0x2600 <= code <= 0x26FF) or    # Miscellaneous Symbols
                (0x2700 <= code <= 0x27BF)       # Dingbats
            )
            if not is_emoji:
                filtered_chars.append(char)
        cleaned = ''.join(filtered_chars).strip()

        # Filter out empty lines
        if not cleaned:
            return

        # Initialize start time if not set
        if not hasattr(self, 'ttw_start_time'):
            self.ttw_start_time = time.time()

        lower_cleaned = cleaned.lower()

        # === MINIMAL PROCESSING: Match standalone behavior as closely as possible ===
        # When running standalone: output goes directly to terminal, no processing
        # Here: We must process each line, but do it as efficiently as possible
        
        # Always log to file (simple, no recursion risk)
        try:
            self._write_to_log_file(cleaned)
        except Exception:
            pass
        
        # Extract progress for Activity window (minimal regex, wrapped in try/except)
        try:
            # Try [X/Y] pattern
            progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
            if progress_match:
                current = int(progress_match.group(1))
                total = int(progress_match.group(2))
                percent = int((current / total) * 100) if total > 0 else 0
                phase = self._ttw_current_phase or "Processing"
                self._update_ttw_activity(current, total, percent)
            
            # Try "Loading manifest: X/Y"
            if 'loading manifest:' in lower_cleaned:
                manifest_match = re.search(r'loading manifest:\s*(\d+)/(\d+)', lower_cleaned)
                if manifest_match:
                    current = int(manifest_match.group(1))
                    total = int(manifest_match.group(2))
                    percent = int((current / total) * 100) if total > 0 else 0
                    self._ttw_current_phase = "Loading manifest"
                    self._update_ttw_activity(current, total, percent)
        except Exception:
            pass  # Skip if regex fails
        
        # Determine if we should show this line
        # By default: only show errors, warnings, milestones
        # Everything else: only in details mode
        is_error = 'error:' in lower_cleaned and 'succeeded' not in lower_cleaned and '0 failed' not in lower_cleaned
        is_warning = 'warning:' in lower_cleaned
        is_milestone = any(kw in lower_cleaned for kw in ['===', 'complete', 'finished', 'validation', 'configuration valid'])
        is_file_op = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
        
        # Filter out meaningless standalone messages (just "OK", etc.)
        is_noise = cleaned.strip().upper() in ['OK', 'OK.', 'OK!', 'DONE', 'DONE.', 'SUCCESS', 'SUCCESS.']
        
        should_show = (is_error or is_warning or is_milestone) or (self.show_details_checkbox.isChecked() and not is_file_op and not is_noise)
        
        if should_show:
            # Direct console append - no recursion, no complex processing
            try:
                if is_error or is_warning:
                    # Color code errors/warnings
                    color = '#f44336' if is_error else '#ff9800'
                    prefix = "WARNING: " if is_warning else "ERROR: "
                    escaped = (prefix + cleaned).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html = f'<span style="color: {color};">{escaped}</span><br>'
                    self.console.insertHtml(html)
                    if not self.show_details_checkbox.isChecked():
                        self.show_details_checkbox.setChecked(True)
                else:
                    self.console.append(cleaned)
            except Exception:
                pass  # Don't break on console errors
        
        return
        # Simplified: Only extract progress, don't filter file operations (show in details mode)
        # Extract progress from lines like: [44908/58889] or [X/Y]
        progress_match = None
        try:
            progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
        except (RecursionError, re.error):
            pass
        
        if progress_match:
            current = int(progress_match.group(1))
            total = int(progress_match.group(2))
            percent = int((current / total) * 100) if total > 0 else 0
            
            # Check if this looks like a file operation line (has file extension)
            is_file_operation = any(ext in lower_cleaned for ext in ['.ogg', '.mp3', '.bsa', '.dds', '.nif', '.kf', '.hkx'])
            
            if is_file_operation:
                # File operation - only show in details mode, but still extract progress for Activity window
                self._ttw_file_operation_count += 1
                phase_name = self._ttw_current_phase or "Processing files"
                
                # Update Activity Window with phase and counters
                self._update_ttw_activity(current, total, percent)
                
                # Only show in details mode
                if self.show_details_checkbox.isChecked():
                    elapsed = int(time.time() - self.ttw_start_time)
                    elapsed_min = elapsed // 60
                    elapsed_sec = elapsed % 60
                    progress_text = f"{phase_name}: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
                    self._update_progress_line(progress_text)
                return

        # === COLLAPSE REPETITIVE EXTRACTION PROGRESS ===
        # Pattern: "Extracted 100/27290 files..." - simplified with error handling
        extraction_progress_match = None
        try:
            extraction_progress_match = re.search(r'Extracted\s+(\d+)/(\d+)\s+files', cleaned, re.IGNORECASE)
        except (RecursionError, re.error):
            pass
        
        if extraction_progress_match:
            current = int(extraction_progress_match.group(1))
            total = int(extraction_progress_match.group(2))
            percent = int((current / total) * 100) if total > 0 else 0
            
            # Update phase with counters (always update Activity window)
            phase_name = "Extracting MPI package"
            self._ttw_current_phase = phase_name
            self._update_ttw_phase(phase_name, current, total, percent)
            
            # Only show progress line in details mode
            if self.show_details_checkbox.isChecked():
                elapsed = int(time.time() - self.ttw_start_time)
                elapsed_min = elapsed // 60
                elapsed_sec = elapsed % 60
                progress_text = f"{phase_name}: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
                self._update_progress_line(progress_text)
            
            # Update last progress tracking
            self._ttw_last_extraction_progress = current
            return

        # === IMPORTANT MILESTONES AND SUMMARIES ===
        # Simplified: Use simple string checks instead of regex
        milestone_keywords = ['===', 'complete', 'finished', 'installation summary', 'assets processed',
                             'validation complete', 'bsa creation', 'post-commands', 'operation summary',
                             'package:', 'variables:', 'locations:', 'assets:', 'loaded', 'successfully parsed']
        is_milestone = any(keyword in lower_cleaned for keyword in milestone_keywords)
        
        if is_milestone:
            self._safe_append_text(cleaned)
            return

        # === PROGRESS PATTERNS ===
        # Pattern 1: "Progress: 50% (1234/5678)" - simplified regex with error handling
        progress_pct_match = None
        try:
            progress_pct_match = re.search(r'(\d+)%\s*\((\d+)/(\d+)\)', cleaned)
        except (RecursionError, re.error):
            pass
        
        if progress_pct_match:
            percent = int(progress_pct_match.group(1))
            current = int(progress_pct_match.group(2))
            total = int(progress_pct_match.group(3))
            
            if not hasattr(self, 'ttw_total_assets'):
                self.ttw_total_assets = total
            
            elapsed = int(time.time() - self.ttw_start_time)
            elapsed_min = elapsed // 60
            elapsed_sec = elapsed % 60
            
            self.status_banner.setText(
                f"Installing TTW: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
            )
            
            # Update Activity Window with phase and counters
            phase_name = self._ttw_current_phase or "Processing"
            self._update_ttw_activity(current, total, percent)
            
            # Only show progress line in details mode
            if self.show_details_checkbox.isChecked():
                progress_text = f"{phase_name}: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
                self._update_progress_line(progress_text)
            return

        # Pattern 2: "[X/Y]" with context OR "Loading manifest: X/Y" pattern - simplified with error handling
        progress_match = None
        loading_manifest_match = None
        try:
            progress_match = re.search(r'\[(\d+)/(\d+)\]', cleaned)
            loading_manifest_match = re.search(r'loading manifest:\s*(\d+)/(\d+)', lower_cleaned)
        except (RecursionError, re.error):
            pass
        
        if loading_manifest_match:
            # Special handling for "Loading manifest: X/Y" - always show this progress
            current = int(loading_manifest_match.group(1))
            total = int(loading_manifest_match.group(2))
            percent = int((current / total) * 100) if total > 0 else 0
            
            # Extract elapsed time if present - simplified with error handling
            elapsed_match = None
            try:
                elapsed_match = re.search(r'elapsed:\s*(\d+)m\s*(\d+)s', lower_cleaned)
            except (RecursionError, re.error):
                pass
            
            if elapsed_match:
                elapsed_min = int(elapsed_match.group(1))
                elapsed_sec = int(elapsed_match.group(2))
            else:
                elapsed = int(time.time() - self.ttw_start_time)
                elapsed_min = elapsed // 60
                elapsed_sec = elapsed % 60
            
            phase_name = "Loading manifest"
            self._ttw_current_phase = phase_name
            
            # Remove duplicate percentage - status banner already shows it
            self.status_banner.setText(
                f"Loading manifest: {current:,}/{total:,} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
            )
            
            # Update single progress line (but show periodic updates to indicate activity)
            progress_text = f"{phase_name}: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
            
            # Show periodic updates (every 2% or every 5 seconds) to indicate process is alive
            # More frequent updates to prevent appearance of hanging
            if not hasattr(self, '_ttw_last_manifest_percent'):
                self._ttw_last_manifest_percent = 0
                self._ttw_last_manifest_time = time.time()
            
            percent_diff = percent - self._ttw_last_manifest_percent
            time_diff = time.time() - self._ttw_last_manifest_time
            
            # Update progress line, but also show new line if significant progress or time elapsed
            # More frequent updates (every 2% or 5 seconds) to show activity
            if percent_diff >= 2 or time_diff >= 5:
                # Significant progress or time elapsed - show as new line to indicate activity
                self._safe_append_text(progress_text)
                self._ttw_progress_line_text = progress_text
                self._ttw_last_manifest_percent = percent
                self._ttw_last_manifest_time = time.time()
            else:
                # Small progress - just update the line
                self._update_progress_line(progress_text)
            
            # Update Activity Window with phase and counters
            self._update_ttw_activity(current, total, percent)
            
            # Process events to keep UI responsive during long operations
            QApplication.processEvents()
            return
        
        if progress_match:
            current = int(progress_match.group(1))
            total = int(progress_match.group(2))
            
            # Check if this is a meaningful progress line (not a file operation we already handled)
            if any(keyword in lower_cleaned for keyword in ['writing', 'creating', 'processing', 'installing', 'extracting', 'loading']):
                if not hasattr(self, 'ttw_total_assets'):
                    self.ttw_total_assets = total
                
                # Detect specific phases from context (simple string checks)
                phase_name = self._ttw_current_phase
                if 'bsa' in lower_cleaned or 'writing' in lower_cleaned:
                    phase_name = "Writing BSA archives"
                    self._ttw_current_phase = phase_name
                elif 'loading' in lower_cleaned:
                    phase_name = "Loading manifest"
                    self._ttw_current_phase = phase_name
                elif not phase_name:
                    phase_name = "Processing"
                
                percent = int((current / total) * 100) if total > 0 else 0
                elapsed = int(time.time() - self.ttw_start_time)
                elapsed_min = elapsed // 60
                elapsed_sec = elapsed % 60
                
                self.status_banner.setText(
                    f"Installing TTW: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
                )
                
                # Update Activity Window with phase and counters (always)
                self._update_ttw_activity(current, total, percent)
                
                # Only show progress line in details mode
                if self.show_details_checkbox.isChecked():
                    progress_text = f"{phase_name}: {current}/{total} ({percent}%) | Elapsed: {elapsed_min}m {elapsed_sec}s"
                    self._update_progress_line(progress_text)
            return

        # === PHASE DETECTION ===
        phase_keywords = {
            'extracting': 'Extracting MPI package',
            'downloading': 'Downloading files',
            'loading manifest': 'Loading manifest',
            'parsing assets': 'Parsing assets',
            'validation': 'Running validation',
            'installing': 'Installing TTW',
            'writing bsa': 'Writing BSA archives',
            'post-installation': 'Running post-installation commands',
            'cleaning up': 'Cleaning up'
        }
        
        for keyword, phase_name in phase_keywords.items():
            if keyword in lower_cleaned:
                if self._ttw_current_phase != phase_name:
                    # Start new phase - just update Activity window and show phase message
                    self._ttw_current_phase = phase_name
                    self._update_ttw_phase(phase_name)  # Start phase without counters initially
                    if self.show_details_checkbox.isChecked():
                        self._safe_append_text(f"{phase_name}...")
                    self._ttw_progress_line_text = None  # Reset progress line
                return

        # === CONFIGURATION AND VALIDATION MESSAGES ===
        # Simplified: Use simple string checks
        config_keywords = ['fallout 3:', 'fallout nv:', 'output:', 'mpi package:', 'configuration valid',
                          'validating configuration', 'verifying', 'file correctly absent', 'disk space check']
        is_config = any(keyword in lower_cleaned for keyword in config_keywords)
        
        if is_config:
            self._safe_append_text(cleaned)
            return

        # === EXECUTION COMMANDS (filter most, show important ones) ===
        if 'executing:' in lower_cleaned or 'cmd.exe' in lower_cleaned:
            # Only show rename operations and failures, not every delete/rename
            if 'renamed:' in lower_cleaned or 'ren:' in lower_cleaned:
                if self.show_details_checkbox.isChecked():
                    self._safe_append_text(cleaned)
            return

        # === PATCH/LZ4 DECOMPRESSION MESSAGES ===
        # Show these to indicate activity during manifest loading
        if 'patch' in lower_cleaned and ('lz4' in lower_cleaned or 'decompressing' in lower_cleaned):
            # Show patch decompression messages (but not errors - those are handled above)
            if 'error' not in lower_cleaned and 'failed' not in lower_cleaned:
                # Just a status message - show it briefly or in details mode
                if self.show_details_checkbox.isChecked():
                    self._safe_append_text(cleaned)
                # Don't return - let it fall through to default handling
            else:
                # Error message - already handled by error detection above
                return

        # === DEFAULT: Only show in details mode ===
        if self.show_details_checkbox.isChecked():
            self._safe_append_text(cleaned)
    
    def on_installation_progress(self, progress_message):
        """Replace the last line in the console for progress updates"""
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.movePosition(QTextCursor.StartOfLine, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(progress_message)
        # Don't force scroll for progress updates - let user control
    
    def _update_progress_line(self, text):
        """Update progress - just append, don't try to replace (simpler and safer)"""
        # Simplified: Just append progress lines instead of trying to replace
        # This avoids Qt cursor manipulation issues that cause SystemError
        # Only show in details mode to avoid spam
        if self.show_details_checkbox.isChecked():
            self._safe_append_text(text)
        # Always track for Activity window updates (handled separately)
        self._ttw_progress_line_text = text
    
    def _update_ttw_elapsed_time(self):
        """Update status banner with elapsed time"""
        if hasattr(self, 'ttw_start_time'):
            elapsed = int(time.time() - self.ttw_start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.status_banner.setText(f"Processing Tale of Two Wastelands installation... Elapsed: {minutes}m {seconds}s")

    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        debug_print(f"DEBUG: on_installation_finished called with success={success}, message={message}")

        # Stop elapsed timer
        if hasattr(self, 'ttw_elapsed_timer'):
            self.ttw_elapsed_timer.stop()

        # Update status banner
        if success:
            elapsed = int(time.time() - self.ttw_start_time) if hasattr(self, 'ttw_start_time') else 0
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.status_banner.setText(f"Installation completed successfully! Total time: {minutes}m {seconds}s")
            self.status_banner.setStyleSheet(f"""
                background-color: #1a4d1a;
                color: #4CAF50;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)
        else:
            self.status_banner.setText(f"Installation failed: {message}")
            self.status_banner.setStyleSheet(f"""
                background-color: #4d1a1a;
                color: #f44336;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            """)
            self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit)

    def process_finished(self, exit_code, exit_status):
        debug_print(f"DEBUG: process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        debug_print("DEBUG: Button states reset in process_finished")
        

        if exit_code == 0:
            # TTW installation complete
            self._safe_append_text("\nTTW installation completed successfully!")
            self._safe_append_text("The merged TTW files have been created in the output directory.")

            # Check if we're in modlist integration mode
            if self._integration_mode:
                self._safe_append_text("\nIntegrating TTW into modlist...")
                self._perform_modlist_integration()
            else:
                # Standard mode - ask user if they want to create a mod archive for MO2
                reply = MessageService.question(
                    self, "TTW Installation Complete!",
                    "Tale of Two Wastelands installation completed successfully!\n\n"
                    f"Output location: {self.install_dir_edit.text()}\n\n"
                    "Would you like to create a zipped mod archive for MO2?\n"
                    "This will package the TTW files for easy installation into Mod Organizer 2.",
                    critical=False
                )

                if reply == QMessageBox.Yes:
                    self._create_ttw_mod_archive()
                else:
                    MessageService.information(
                        self, "Installation Complete",
                        "TTW installation complete!\n\n"
                        "You can manually use the TTW files from the output directory.",
                        safety_level="medium"
                    )
        else:
            # Check for user cancellation first
            last_output = self.console.toPlainText()
            if "cancelled by user" in last_output.lower():
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
            else:
                MessageService.critical(self, "Install Failed", "The modlist install failed. Please check the console output for details.")
                self._safe_append_text(f"\nInstall failed (exit code {exit_code}).")
        self.console.moveCursor(QTextCursor.End)

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

    def _on_show_details_toggled(self, checked: bool):
        from PySide6.QtCore import Qt as _Qt
        self._toggle_console_visibility(_Qt.Checked if checked else _Qt.Unchecked)

    def _toggle_console_visibility(self, state):
        """Toggle console visibility and resize main window"""
        is_checked = (state == Qt.Checked)
        main_window = self.window()

        if not main_window:
            return

        # Check if we're on Steam Deck
        is_steamdeck = False
        if self.system_info and getattr(self.system_info, 'is_steamdeck', False):
            is_steamdeck = True
        elif not self.system_info and main_window and hasattr(main_window, 'system_info'):
            is_steamdeck = getattr(main_window.system_info, 'is_steamdeck', False)

        # Console height when expanded
        console_height = 300

        if is_checked:
            # Show console
            self.console.setVisible(True)
            self.console.show()
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            try:
                self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            except Exception:
                pass
            try:
                self.main_overall_vbox.setStretchFactor(self.console, 1)
            except Exception:
                pass

            # On Steam Deck, skip window resizing - keep default Steam Deck window size
            if is_steamdeck:
                debug_print("DEBUG: Steam Deck detected, skipping window resize in _toggle_console_visibility")
                return

            # Restore main window to normal size (clear any compact constraints)
            # On Steam Deck, keep fullscreen; on other systems, set normal window state
            if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                main_window.showNormal()
            main_window.setMaximumHeight(16777215)
            main_window.setMinimumHeight(0)
            # Restore original minimum size so the window can expand normally
            try:
                if self._saved_min_size is not None:
                    main_window.setMinimumSize(self._saved_min_size)
            except Exception:
                pass
            # Prefer exact original geometry if known
            if self._saved_geometry is not None:
                main_window.setGeometry(self._saved_geometry)
            else:
                expanded_min = 900
                current_size = main_window.size()
                target_height = max(expanded_min, 900)
                main_window.setMinimumHeight(expanded_min)
                main_window.resize(current_size.width(), target_height)
            try:
                # Encourage layouts to recompute sizes
                self.main_overall_vbox.invalidate()
                self.updateGeometry()
            except Exception:
                pass
            # Notify parent to expand
            try:
                self.resize_request.emit('expand')
            except Exception:
                pass
        else:
            # Hide console fully (removes it from layout sizing)
            self.console.setVisible(False)
            self.console.hide()
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            try:
                # Make the hidden console contribute no expand pressure
                self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            except Exception:
                pass
            try:
                self.main_overall_vbox.setStretchFactor(self.console, 0)
            except Exception:
                pass

            # On Steam Deck, skip window resizing to keep maximized state
            if is_steamdeck:
                debug_print("DEBUG: Steam Deck detected, skipping window resize in collapse branch")
                return

            # Use fixed compact height for consistency across all workflow screens
            compact_height = 620
            # On Steam Deck, keep fullscreen; on other systems, set normal window state
            if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                main_window.showNormal()
            # Set minimum height but no maximum to allow user resizing
            try:
                from PySide6.QtCore import QSize
                set_responsive_minimum(main_window, min_width=960, min_height=compact_height)
                main_window.setMaximumSize(QSize(16777215, 16777215))  # No maximum
            except Exception:
                pass

            # Resize to compact height to avoid leftover space
            current_size = main_window.size()
            main_window.resize(current_size.width(), compact_height)
            # Notify parent to collapse
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass

    def _update_ttw_activity(self, current, total, percent):
        """Update Activity window with TTW installation progress"""
        try:
            # Determine current phase based on progress
            if not hasattr(self, '_ttw_current_phase'):
                self._ttw_current_phase = None

            # Use current phase name or default
            phase_name = self._ttw_current_phase or "Processing"
            
            # Update or add activity item showing current progress with phase name and counters
            # Don't include percentage in label - progress bar shows it
            label = f"{phase_name}: {current:,}/{total:,}"
            self.file_progress_list.update_or_add_item(
                item_id="ttw_progress",
                label=label,
                progress=percent
            )
        except Exception:
            pass

    def _update_ttw_phase(self, phase_name, current=None, total=None, percent=0):
        """Update Activity window with current TTW installation phase and optional progress"""
        try:
            self._ttw_current_phase = phase_name
            
            # Build label with phase name and counters if provided
            # Don't include percentage in label - progress bar shows it
            if current is not None and total is not None:
                label = f"{phase_name}: {current:,}/{total:,}"
            else:
                label = phase_name
            
            # Update or add activity item
            self.file_progress_list.update_or_add_item(
                item_id="ttw_phase",
                label=label,
                progress=percent
            )
        except Exception:
            pass

    def _safe_append_text(self, text, color=None):
        """Append text with professional auto-scroll behavior
        
        Args:
            text: Text to append
            color: Optional HTML color code (e.g., '#f44336' for red) to format the text
        """
        # Write all messages to log file (including internal messages)
        self._write_to_log_file(text)
        
        # Filter out internal status messages from user console display
        if text.strip().startswith('[Jackify]'):
            # Internal messages are logged but not shown in user console
            return
            
        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance
        
        # Format text with color if provided
        if color:
            # Escape HTML special characters
            escaped_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            formatted_text = f'<span style="color: {color};">{escaped_text}</span>'
            # Use insertHtml for colored text (QTextEdit supports HTML in append when using RichText)
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.console.setTextCursor(cursor)
            self.console.insertHtml(formatted_text + '<br>')
        else:
            # Add plain text
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

    def restart_steam_and_configure(self):
        """Restart Steam using backend service directly - DECOUPLED FROM CLI"""
        debug_print("DEBUG: restart_steam_and_configure called - using direct backend service")
        progress = QProgressDialog("Restarting Steam...", None, 0, 0, self)
        progress.setWindowTitle("Restarting Steam")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        
        def do_restart():
            debug_print("DEBUG: do_restart thread started - using direct backend service")
            try:
                from jackify.backend.handlers.shortcut_handler import ShortcutHandler
                
                # Use backend service directly instead of CLI subprocess
                shortcut_handler = ShortcutHandler(steamdeck=False)  # TODO: Use proper system info
                
                debug_print("DEBUG: About to call secure_steam_restart()")
                success = shortcut_handler.secure_steam_restart()
                debug_print(f"DEBUG: secure_steam_restart() returned: {success}")
                
                out = "Steam restart completed successfully." if success else "Steam restart failed."
                
            except Exception as e:
                debug_print(f"DEBUG: Exception in do_restart: {e}")
                success = False
                out = str(e)
                
            self.steam_restart_finished.emit(success, out)
            
        threading.Thread(target=do_restart, daemon=True).start()
        self._steam_restart_progress = progress  # Store to close later

    def _on_steam_restart_finished(self, success, out):
        debug_print("DEBUG: _on_steam_restart_finished called")
        # Safely cleanup progress dialog on main thread
        if hasattr(self, '_steam_restart_progress') and self._steam_restart_progress:
            try:
                self._steam_restart_progress.close()
                self._steam_restart_progress.deleteLater()  # Use deleteLater() for safer cleanup
            except Exception as e:
                debug_print(f"DEBUG: Error closing progress dialog: {e}")
            finally:
                self._steam_restart_progress = None
        
        # Controls are managed by the proper control management system
        if success:
            self._safe_append_text("Steam restarted successfully.")
            
            # Save context for later use in configuration
            self._manual_steps_retry_count = 0
            self._current_modlist_name = "TTW Installation"  # Fixed name for TTW
            self._current_resolution = None  # TTW doesn't need resolution changes
            
            # Use automated prefix creation instead of manual steps
            debug_print("DEBUG: Starting automated prefix creation workflow")
            self._safe_append_text("Starting automated prefix creation workflow...")
            self.start_automated_prefix_workflow()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.")

    def start_automated_prefix_workflow(self):
        # Ensure _current_resolution is always set before starting workflow
        if not hasattr(self, '_current_resolution') or self._current_resolution is None:
            resolution = None  # TTW doesn't need resolution changes
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution and resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None
        """Start the automated prefix creation workflow"""
        try:
            # Disable controls during installation
            self._disable_controls_during_operation()
            modlist_name = "TTW Installation"
            install_dir = self.install_dir_edit.text().strip()
            final_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
            
            if not os.path.exists(final_exe_path):
                # Check if this is Somnium specifically (uses files/ subdirectory)
                modlist_name_lower = modlist_name.lower()
                if "somnium" in modlist_name_lower:
                    somnium_exe_path = os.path.join(install_dir, "files", "ModOrganizer.exe")
                    if os.path.exists(somnium_exe_path):
                        final_exe_path = somnium_exe_path
                        self._safe_append_text(f"Detected Somnium modlist - will proceed with automated setup")
                        # Show Somnium guidance popup after automated workflow completes
                        self._show_somnium_guidance = True
                        self._somnium_install_dir = install_dir
                    else:
                        self._safe_append_text(f"ERROR: Somnium ModOrganizer.exe not found at {somnium_exe_path}")
                        MessageService.critical(self, "Somnium ModOrganizer.exe Not Found", 
                            f"Expected Somnium ModOrganizer.exe not found at:\n{somnium_exe_path}\n\nCannot proceed with automated setup.")
                        return
                else:
                    self._safe_append_text(f"ERROR: ModOrganizer.exe not found at {final_exe_path}")
                    MessageService.critical(self, "ModOrganizer.exe Not Found", 
                        f"ModOrganizer.exe not found at:\n{final_exe_path}\n\nCannot proceed with automated setup.")
                    return
            
            # Run automated prefix creation in separate thread
            from PySide6.QtCore import QThread, Signal
            
            class AutomatedPrefixThread(QThread):
                finished = Signal(bool, str, str, str)  # success, prefix_path, appid (as string), last_timestamp
                progress = Signal(str)  # progress messages
                error = Signal(str)  # error messages
                show_progress_dialog = Signal(str)  # show progress dialog with message
                hide_progress_dialog = Signal()  # hide progress dialog
                conflict_detected = Signal(list)  # conflicts list
                
                def __init__(self, modlist_name, install_dir, final_exe_path):
                    super().__init__()
                    self.modlist_name = modlist_name
                    self.install_dir = install_dir
                    self.final_exe_path = final_exe_path
                
                def run(self):
                    try:
                        from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
                        
                        def progress_callback(message):
                            self.progress.emit(message)
                            # Show progress dialog during Steam restart
                            if "Steam restarted successfully" in message:
                                self.hide_progress_dialog.emit()
                            elif "Restarting Steam..." in message:
                                self.show_progress_dialog.emit("Restarting Steam...")
                        
                        prefix_service = AutomatedPrefixService()
                        # Determine Steam Deck once and pass through the workflow
                        try:
                            import os
                            _is_steamdeck = False
                            if os.path.exists('/etc/os-release'):
                                with open('/etc/os-release') as f:
                                    if 'steamdeck' in f.read().lower():
                                        _is_steamdeck = True
                        except Exception:
                            _is_steamdeck = False
                        result = prefix_service.run_working_workflow(
                            self.modlist_name, self.install_dir, self.final_exe_path, progress_callback, steamdeck=_is_steamdeck
                        )
                        
                        # Handle the result - check for conflicts
                        if isinstance(result, tuple) and len(result) == 4:
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result with timestamp
                                success, prefix_path, new_appid, last_timestamp = result
                        elif isinstance(result, tuple) and len(result) == 3:
                            # Fallback for old format (backward compatibility)
                            if result[0] == "CONFLICT":
                                # Conflict detected - emit signal to main GUI
                                conflicts = result[1]
                                self.hide_progress_dialog.emit()
                                self.conflict_detected.emit(conflicts)
                                return
                            else:
                                # Normal result (old format)
                                success, prefix_path, new_appid = result
                                last_timestamp = None
                        else:
                            # Handle non-tuple result
                            success = result
                            prefix_path = ""
                            new_appid = "0"
                            last_timestamp = None
                        
                        # Ensure progress dialog is hidden when workflow completes
                        self.hide_progress_dialog.emit()
                        self.finished.emit(success, prefix_path or "", str(new_appid) if new_appid else "0", last_timestamp)
                        
                    except Exception as e:
                        # Ensure progress dialog is hidden on error
                        self.hide_progress_dialog.emit()
                        self.error.emit(str(e))
            
            # Create and start thread
            self.prefix_thread = AutomatedPrefixThread(modlist_name, install_dir, final_exe_path)
            self.prefix_thread.finished.connect(self.on_automated_prefix_finished)
            self.prefix_thread.error.connect(self.on_automated_prefix_error)
            self.prefix_thread.progress.connect(self.on_automated_prefix_progress)
            self.prefix_thread.show_progress_dialog.connect(self.show_steam_restart_progress)
            self.prefix_thread.hide_progress_dialog.connect(self.hide_steam_restart_progress)
            self.prefix_thread.conflict_detected.connect(self.show_shortcut_conflict_dialog)
            self.prefix_thread.start()
            
        except Exception as e:
            debug_print(f"DEBUG: Exception in start_automated_prefix_workflow: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            self._safe_append_text(f"ERROR: Failed to start automated workflow: {e}")
            # Re-enable controls on exception
            self._enable_controls_after_operation()
    
    def on_automated_prefix_finished(self, success, prefix_path, new_appid_str, last_timestamp=None):
        """Handle completion of automated prefix creation"""
        try:
            if success:
                debug_print(f"SUCCESS: Automated prefix creation completed!")
                debug_print(f"Prefix created at: {prefix_path}")
                if new_appid_str and new_appid_str != "0":
                    debug_print(f"AppID: {new_appid_str}")
                
                # Convert string AppID back to integer for configuration
                new_appid = int(new_appid_str) if new_appid_str and new_appid_str != "0" else None
                
                # Continue with configuration using the new AppID and timestamp
                modlist_name = "TTW Installation"
                install_dir = self.install_dir_edit.text().strip()
                self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
            else:
                self._safe_append_text(f"ERROR: Automated prefix creation failed")
                self._safe_append_text("Please check the logs for details")
                MessageService.critical(self, "Automated Setup Failed", 
                    "Automated prefix creation failed. Please check the console output for details.")
                # Re-enable controls on failure
                self._enable_controls_after_operation()
        finally:
            # Always ensure controls are re-enabled when workflow truly completes
            pass
    
    def on_automated_prefix_error(self, error_msg):
        """Handle error in automated prefix creation"""
        self._safe_append_text(f"ERROR: Error during automated prefix creation: {error_msg}")
        MessageService.critical(self, "Automated Setup Error", 
            f"Error during automated prefix creation: {error_msg}")
        # Re-enable controls on error
        self._enable_controls_after_operation()
    
    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
    
    def on_configuration_progress(self, progress_msg):
        """Handle progress updates from modlist configuration"""
        self._safe_append_text(progress_msg)
    
    def show_steam_restart_progress(self, message):
        """Show Steam restart progress dialog"""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt
        
        self.steam_restart_progress = QProgressDialog(message, None, 0, 0, self)
        self.steam_restart_progress.setWindowTitle("Restarting Steam")
        self.steam_restart_progress.setWindowModality(Qt.WindowModal)
        self.steam_restart_progress.setMinimumDuration(0)
        self.steam_restart_progress.setValue(0)
        self.steam_restart_progress.show()
    
    def hide_steam_restart_progress(self):
        """Hide Steam restart progress dialog"""
        if hasattr(self, 'steam_restart_progress') and self.steam_restart_progress:
            try:
                self.steam_restart_progress.close()
                self.steam_restart_progress.deleteLater()
            except Exception:
                pass
            finally:
                self.steam_restart_progress = None
        # Controls are managed by the proper control management system

    def on_configuration_complete(self, success, message, modlist_name, enb_detected=False):
        """Handle configuration completion on main thread"""
        try:
            # Re-enable controls now that installation/configuration is complete
            self._enable_controls_after_operation()
            
            if success:
                # Check if we need to show Somnium guidance
                if self._show_somnium_guidance:
                    self._show_somnium_post_install_guidance()
                
                # Show celebration SuccessDialog after the entire workflow
                from ..dialogs import SuccessDialog
                import time
                if not hasattr(self, '_install_workflow_start_time'):
                    self._install_workflow_start_time = time.time()
                time_taken = int(time.time() - self._install_workflow_start_time)
                mins, secs = divmod(time_taken, 60)
                time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"
                display_names = {
                    'skyrim': 'Skyrim',
                    'fallout4': 'Fallout 4',
                    'falloutnv': 'Fallout New Vegas',
                    'oblivion': 'Oblivion',
                    'starfield': 'Starfield',
                    'oblivion_remastered': 'Oblivion Remastered',
                    'enderal': 'Enderal'
                }
                game_name = display_names.get(self._current_game_type, self._current_game_name)
                success_dialog = SuccessDialog(
                    modlist_name=modlist_name,
                    workflow_type="install",
                    time_taken=time_str,
                    game_name=game_name,
                    parent=self
                )
                success_dialog.show()
                
                # Note: TTW workflow does NOT need ENB detection/dialog
            elif hasattr(self, '_manual_steps_retry_count') and self._manual_steps_retry_count >= 3:
                # Max retries reached - show failure message
                MessageService.critical(self, "Manual Steps Failed", 
                                   "Manual steps validation failed after multiple attempts.")
            else:
                # Configuration failed for other reasons
                MessageService.critical(self, "Configuration Failed", 
                                   "Post-install configuration failed. Please check the console output.")
        except Exception as e:
            # Ensure controls are re-enabled even on unexpected errors
            self._enable_controls_after_operation()
            raise
        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None

    def on_configuration_error(self, error_message):
        """Handle configuration error on main thread"""
        self._safe_append_text(f"Configuration failed with error: {error_message}")
        MessageService.critical(self, "Configuration Error", f"Configuration failed: {error_message}")

        # Re-enable all controls on error
        self._enable_controls_after_operation()

        # Clean up thread
        if hasattr(self, 'config_thread') and self.config_thread is not None:
            # Disconnect all signals to prevent "Internal C++ object already deleted" errors
            try:
                self.config_thread.progress_update.disconnect()
                self.config_thread.configuration_complete.disconnect()
                self.config_thread.error_occurred.disconnect()
            except:
                pass  # Ignore errors if already disconnected
            if self.config_thread.isRunning():
                self.config_thread.quit()
                self.config_thread.wait(5000)  # Wait up to 5 seconds
            self.config_thread.deleteLater()
            self.config_thread = None

    def show_manual_steps_dialog(self, extra_warning=""):
        modlist_name = "TTW Installation"
        msg = (
            f"<b>Manual Proton Setup Required for <span style='color:#3fd0ea'>{modlist_name}</span></b><br>"
            "After Steam restarts, complete the following steps in Steam:<br>"
            f"1. Locate the '<b>{modlist_name}</b>' entry in your Steam Library<br>"
            "2. Right-click and select 'Properties'<br>"
            "3. Switch to the 'Compatibility' tab<br>"
            "4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'<br>"
            "5. Select 'Proton - Experimental' from the dropdown menu<br>"
            "6. Close the Properties window<br>"
            f"7. Launch '<b>{modlist_name}</b>' from your Steam Library<br>"
            "8. Wait for Mod Organizer 2 to fully open<br>"
            "9. Once Mod Organizer has fully loaded, CLOSE IT completely and return here<br>"
            "<br>Once you have completed ALL the steps above, click OK to continue."
            f"{extra_warning}"
        )
        reply = MessageService.question(self, "Manual Steps Required", msg, safety_level="medium")
        if reply == QMessageBox.Yes:
            self.validate_manual_steps_completion()
        else:
            # User clicked Cancel or closed the dialog - cancel the workflow
            self._safe_append_text("\n🛑 Manual steps cancelled by user. Workflow stopped.")
            # Re-enable all controls when workflow is cancelled
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)

    def _get_mo2_path(self, install_dir, modlist_name):
        """Get ModOrganizer.exe path, handling Somnium's non-standard structure"""
        mo2_exe_path = os.path.join(install_dir, "ModOrganizer.exe")
        if not os.path.exists(mo2_exe_path) and "somnium" in modlist_name.lower():
            somnium_path = os.path.join(install_dir, "files", "ModOrganizer.exe")
            if os.path.exists(somnium_path):
                mo2_exe_path = somnium_path
        return mo2_exe_path

    def validate_manual_steps_completion(self):
        """Validate that manual steps were actually completed and handle retry logic"""
        modlist_name = "TTW Installation"
        install_dir = self.install_dir_edit.text().strip()
        mo2_exe_path = self._get_mo2_path(install_dir, modlist_name)
        
        # Add delay to allow Steam filesystem updates to complete
        self._safe_append_text("Waiting for Steam filesystem updates to complete...")
        import time
        time.sleep(2)
        
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
            self._safe_append_text("Suggestion: Check that Steam is running and shortcuts are visible in library")
            self.handle_validation_failure("Could not find Steam shortcut")
            return
        
        self._safe_append_text(f"Found Steam-assigned AppID: {current_appid}")
        self._safe_append_text(f"Validating manual steps completion for AppID: {current_appid}")
        
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
            modlist_handler.appid = current_appid
            modlist_handler.game_var = "skyrimspecialedition"  # Default for now
            
            # Set compat_data_path for Proton detection
            compat_data_path_str = path_handler.find_compat_data(current_appid)
            if compat_data_path_str:
                from pathlib import Path
                modlist_handler.compat_data_path = Path(compat_data_path_str)
            
            # Check Proton version
            self._safe_append_text(f"Attempting to detect Proton version for AppID {current_appid}...")
            if modlist_handler._detect_proton_version():
                self._safe_append_text(f"Raw detected Proton version: '{modlist_handler.proton_ver}'")
                if modlist_handler.proton_ver and 'experimental' in modlist_handler.proton_ver.lower():
                    proton_ok = True
                    self._safe_append_text(f"Proton version validated: {modlist_handler.proton_ver}")
                else:
                    self._safe_append_text(f"Error: Wrong Proton version detected: '{modlist_handler.proton_ver}' (expected 'experimental' in name)")
            else:
                self._safe_append_text("Error: Could not detect Proton version from any source")
                
        except Exception as e:
            self._safe_append_text(f"Error checking Proton version: {e}")
            proton_ok = False
        
        # Check 2: Compatdata directory exists
        compatdata_ok = False
        try:
            from jackify.backend.handlers.path_handler import PathHandler
            path_handler = PathHandler()
            
            self._safe_append_text(f"Searching for compatdata directory for AppID {current_appid}...")
            self._safe_append_text("Checking standard Steam locations and Flatpak Steam...")
            prefix_path_str = path_handler.find_compat_data(current_appid)
            self._safe_append_text(f"Compatdata search result: '{prefix_path_str}'")
            
            if prefix_path_str and os.path.isdir(prefix_path_str):
                compatdata_ok = True
                self._safe_append_text(f"Compatdata directory found: {prefix_path_str}")
            else:
                if prefix_path_str:
                    self._safe_append_text(f"Error: Path exists but is not a directory: {prefix_path_str}")
                else:
                    self._safe_append_text(f"Error: No compatdata directory found for AppID {current_appid}")
                    self._safe_append_text("Suggestion: Ensure you launched the shortcut from Steam at least once")
                    self._safe_append_text("Suggestion: Check if Steam is using Flatpak (different file paths)")
                
        except Exception as e:
            self._safe_append_text(f"Error checking compatdata: {e}")
            compatdata_ok = False
        
        # Handle validation results
        if proton_ok and compatdata_ok:
            self._safe_append_text("Manual steps validation passed!")
            self._safe_append_text("Continuing configuration with updated AppID...")
            
            # Continue configuration with the corrected AppID and context
            self.continue_configuration_after_manual_steps(current_appid, modlist_name, install_dir)
        else:
            # Validation failed - handle retry logic
            missing_items = []
            if not proton_ok:
                missing_items.append("• Proton - Experimental not set")
            if not compatdata_ok:
                missing_items.append("• Shortcut not launched from Steam (no compatdata)")
            
            missing_text = "\n".join(missing_items)
            self._safe_append_text(f"Manual steps validation failed:\n{missing_text}")
            self.handle_validation_failure(missing_text)
    
    def show_shortcut_conflict_dialog(self, conflicts):
        """Show dialog to resolve shortcut name conflicts"""
        conflict_names = [c['name'] for c in conflicts]
        conflict_info = f"Found existing Steam shortcut: '{conflict_names[0]}'"
        
        modlist_name = "TTW Installation"
        
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
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.warning(self, "Same Name", "Please enter a different name to resolve the conflict.")
            else:
                # Empty name
                from jackify.frontends.gui.services.message_service import MessageService
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
        # TTW doesn't need name editing
        
        # Restart the automated workflow
        self._safe_append_text(f"Retrying with new shortcut name: '{new_name}'")
        self.start_automated_prefix_workflow()
    
    def continue_configuration_after_automated_prefix(self, new_appid, modlist_name, install_dir, last_timestamp=None):
        """Continue the configuration process with the new AppID after automated prefix creation"""
        # Headers are now shown at start of Steam Integration
        # No need to show them again here
        debug_print("Configuration phase continues after Steam Integration")
        
        debug_print(f"continue_configuration_after_automated_prefix called with appid: {new_appid}")
        try:
            # Update the context with the new AppID (same format as manual steps)
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed since automated prefix is done
                'appid': new_appid,  # Use the NEW AppID from automated prefix creation
                'game_name': self.context.get('game_name', 'Skyrim Special Edition') if hasattr(self, 'context') else 'Skyrim Special Edition'
            }
            self.context = updated_context  # Ensure context is always set
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Get Steam Deck detection once and pass to ConfigThread
            from jackify.backend.services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            is_steamdeck = platform_service.is_steamdeck

            # Create new config thread with updated context
            class ConfigThread(QThread):
                progress_update = Signal(str)
                configuration_complete = Signal(bool, str, str)
                error_occurred = Signal(str)

                def __init__(self, context, is_steamdeck):
                    super().__init__()
                    self.context = context
                    self.is_steamdeck = is_steamdeck
                
                def run(self):
                    try:
                        from jackify.backend.services.modlist_service import ModlistService
                        from jackify.backend.models.configuration import SystemInfo
                        from jackify.backend.models.modlist import ModlistContext
                        from pathlib import Path
                        
                        # Initialize backend service with passed Steam Deck detection
                        system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
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
                            resolution=self.context.get('resolution'),
                            skip_confirmation=True,
                            engine_installed=True  # Skip path manipulation for engine workflows
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
            self.config_thread = ConfigThread(updated_context, is_steamdeck)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
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
            updated_context = {
                'name': modlist_name,
                'path': install_dir,
                'mo2_exe_path': self._get_mo2_path(install_dir, modlist_name),
                'modlist_value': None,
                'modlist_source': None,
                'resolution': getattr(self, '_current_resolution', None),
                'skip_confirmation': True,
                'manual_steps_completed': True,  # Mark as completed
                'appid': new_appid  # Use the NEW AppID from Steam
            }
            
            debug_print(f"Updated context with new AppID: {new_appid}")
            
            # Clean up old thread if exists and wait for it to finish
            if hasattr(self, 'config_thread') and self.config_thread is not None:
                # Disconnect all signals to prevent "Internal C++ object already deleted" errors
                try:
                    self.config_thread.progress_update.disconnect()
                    self.config_thread.configuration_complete.disconnect()
                    self.config_thread.error_occurred.disconnect()
                except:
                    pass  # Ignore errors if already disconnected
                if self.config_thread.isRunning():
                    self.config_thread.quit()
                    self.config_thread.wait(5000)  # Wait up to 5 seconds
                self.config_thread.deleteLater()
                self.config_thread = None
            
            # Start new config thread
            self.config_thread = self._create_config_thread(updated_context)
            self.config_thread.progress_update.connect(self.on_configuration_progress)
            self.config_thread.configuration_complete.connect(self.on_configuration_complete)
            self.config_thread.error_occurred.connect(self.on_configuration_error)
            self.config_thread.start()
            
        except Exception as e:
            self._safe_append_text(f"Error continuing configuration: {e}")
            self.on_configuration_error(str(e))

    def _create_config_thread(self, context):
        """Create a new ConfigThread with proper lifecycle management"""
        from PySide6.QtCore import QThread, Signal

        # Get Steam Deck detection once
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        is_steamdeck = platform_service.is_steamdeck

        class ConfigThread(QThread):
            progress_update = Signal(str)
            configuration_complete = Signal(bool, str, str)
            error_occurred = Signal(str)

            def __init__(self, context, is_steamdeck, parent=None):
                super().__init__(parent)
                self.context = context
                self.is_steamdeck = is_steamdeck
                
            def run(self):
                try:
                    from jackify.backend.models.configuration import SystemInfo
                    from jackify.backend.services.modlist_service import ModlistService
                    from jackify.backend.models.modlist import ModlistContext
                    from pathlib import Path
                    
                    # Initialize backend service with passed Steam Deck detection
                    system_info = SystemInfo(is_steamdeck=self.is_steamdeck)
                    modlist_service = ModlistService(system_info)
                    
                    # Convert context to ModlistContext for service
                    modlist_context = ModlistContext(
                        name=self.context['name'],
                        install_dir=Path(self.context['path']),
                        download_dir=Path(self.context['path']).parent / 'Downloads',  # Default
                        game_type='skyrim',  # Default for now
                        nexus_api_key='',  # Not needed for configuration
                        modlist_value=self.context.get('modlist_value', ''),
                        modlist_source=self.context.get('modlist_source', 'identifier'),
                        resolution=self.context.get('resolution'),  # Pass resolution from GUI
                        skip_confirmation=True,
                        engine_installed=True  # Skip path manipulation for engine workflows
                    )
                    
                    # Add app_id to context
                    if 'appid' in self.context:
                        modlist_context.app_id = self.context['appid']
                    
                    # Define callbacks
                    def progress_callback(message):
                        self.progress_update.emit(message)
                        
                    def completion_callback(success, message, modlist_name):
                        self.configuration_complete.emit(success, message, modlist_name)
                        
                    def manual_steps_callback(modlist_name, retry_count):
                        # This shouldn't happen since manual steps should be done
                        self.progress_update.emit(f"Unexpected manual steps callback for {modlist_name}")
                    
                    # Call the new service method for post-Steam configuration
                    result = modlist_service.configure_modlist_post_steam(
                        context=modlist_context,
                        progress_callback=progress_callback,
                        manual_steps_callback=manual_steps_callback,
                        completion_callback=completion_callback
                    )
                    
                    if not result:
                        self.progress_update.emit("WARNING: configure_modlist_post_steam returned False")
                    
                except Exception as e:
                    import traceback
                    error_details = f"Error in configuration: {e}\nTraceback: {traceback.format_exc()}"
                    self.progress_update.emit(f"DEBUG: {error_details}")
                    self.error_occurred.emit(str(e))
        
        return ConfigThread(context, is_steamdeck, parent=self)

    def handle_validation_failure(self, missing_text):
        """Handle failed validation with retry logic"""
        self._manual_steps_retry_count += 1
        
        if self._manual_steps_retry_count < 3:
            # Show retry dialog with increasingly detailed guidance
            retry_guidance = ""
            if self._manual_steps_retry_count == 1:
                retry_guidance = "\n\nTip: Make sure Steam is fully restarted before trying again."
            elif self._manual_steps_retry_count == 2:
                retry_guidance = "\n\nTip: If using Flatpak Steam, ensure compatdata is being created in the correct location."
            
            MessageService.critical(self, "Manual Steps Incomplete", 
                               f"Manual steps validation failed:\n\n{missing_text}\n\n"
                               f"Please complete the missing steps and try again.{retry_guidance}")
            # Show manual steps dialog again
            extra_warning = ""
            if self._manual_steps_retry_count >= 2:
                extra_warning = "<br><b style='color:#f33'>It looks like you have not completed the manual steps yet. Please try again.</b>"
            self.show_manual_steps_dialog(extra_warning)
        else:
            # Max retries reached
            MessageService.critical(self, "Manual Steps Failed", 
                               "Manual steps validation failed after multiple attempts.\n\n"
                               "Common issues:\n"
                               "• Steam not fully restarted\n"
                               "• Shortcut not launched from Steam\n"
                               "• Flatpak Steam using different file paths\n"
                               "• Proton - Experimental not selected")
            self.on_configuration_complete(False, "Manual steps validation failed after multiple attempts", self._current_modlist_name)

    def show_next_steps_dialog(self, message):
        # EXACT LEGACY show_next_steps_dialog
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
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
                self.stacked_widget.setCurrentIndex(0)  # Main menu
        def on_exit():
            QApplication.quit()
        btn_return.clicked.connect(on_return)
        btn_exit.clicked.connect(on_exit)
        dlg.exec()

    def cleanup_processes(self):
        """Clean up any running processes when the window closes or is cancelled"""
        debug_print("DEBUG: cleanup_processes called - cleaning up InstallationThread and other processes")
        
        # Clean up InstallationThread if running
        if hasattr(self, 'install_thread') and self.install_thread.isRunning():
            debug_print("DEBUG: Cancelling running InstallationThread")
            self.install_thread.cancel()
            self.install_thread.wait(3000)  # Wait up to 3 seconds
            if self.install_thread.isRunning():
                self.install_thread.terminate()
        
        # Clean up other threads
        threads = [
            'prefix_thread', 'config_thread', 'fetch_thread'
        ]
        for thread_name in threads:
            if hasattr(self, thread_name):
                thread = getattr(self, thread_name)
                if thread and thread.isRunning():
                    debug_print(f"DEBUG: Terminating {thread_name}")
                    thread.terminate()
                    thread.wait(1000)  # Wait up to 1 second
    
    def _perform_modlist_integration(self):
        """Integrate TTW into the modlist automatically

        This is called when in integration mode. It will:
        1. Copy TTW output to modlist's mods folder
        2. Update modlist.txt for all profiles
        3. Update plugins.txt with TTW ESMs in correct order
        4. Emit integration_complete signal
        """
        try:
            from pathlib import Path
            import re
            from PySide6.QtCore import QThread, Signal

            # Get TTW output directory
            ttw_output_dir = Path(self.install_dir_edit.text())
            if not ttw_output_dir.exists():
                error_msg = f"TTW output directory not found: {ttw_output_dir}"
                self._safe_append_text(f"\nError: {error_msg}")
                self.integration_complete.emit(False, "")
                return

            # Extract version from .mpi filename
            mpi_path = self.file_edit.text().strip()
            ttw_version = ""
            if mpi_path:
                mpi_filename = Path(mpi_path).stem
                version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', mpi_filename, re.IGNORECASE)
                if version_match:
                    ttw_version = version_match.group(1)

            # Create background thread for integration
            class IntegrationThread(QThread):
                finished = Signal(bool, str)  # success, ttw_version
                progress = Signal(str)  # progress message

                def __init__(self, ttw_output_path, modlist_install_dir, ttw_version):
                    super().__init__()
                    self.ttw_output_path = ttw_output_path
                    self.modlist_install_dir = modlist_install_dir
                    self.ttw_version = ttw_version

                def run(self):
                    try:
                        from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler

                        self.progress.emit("Integrating TTW into modlist...")
                        success = TTWInstallerHandler.integrate_ttw_into_modlist(
                            ttw_output_path=self.ttw_output_path,
                            modlist_install_dir=self.modlist_install_dir,
                            ttw_version=self.ttw_version
                        )
                        self.finished.emit(success, self.ttw_version)
                    except Exception as e:
                        debug_print(f"ERROR: Integration thread failed: {e}")
                        import traceback
                        traceback.print_exc()
                        self.finished.emit(False, self.ttw_version)

            # Show progress message
            self._safe_append_text("\nIntegrating TTW into modlist (this may take a few minutes)...")

            # Update status banner (only in integration mode - visible when collapsed)
            if self._integration_mode:
                self.status_banner.setText("Integrating TTW into modlist (this may take a few minutes)...")
                self.status_banner.setStyleSheet(f"""
                    QLabel {{
                        background-color: #FFA500;
                        color: white;
                        font-weight: bold;
                        padding: 8px;
                        border-radius: 5px;
                    }}
                """)

            # Create progress dialog for integration
            progress_dialog = QProgressDialog(
                f"Integrating TTW {ttw_version} into modlist...\n\n"
                "This involves copying several GB of files and may take a few minutes.\n"
                "Please wait...",
                None,  # No cancel button
                0, 0,  # Indeterminate progress
                self
            )
            progress_dialog.setWindowTitle("Integrating TTW")
            progress_dialog.setMinimumDuration(0)  # Show immediately
            progress_dialog.setWindowModality(Qt.ApplicationModal)
            progress_dialog.setCancelButton(None)
            progress_dialog.show()
            QApplication.processEvents()

            # Store reference to close later
            self._integration_progress_dialog = progress_dialog

            # Create and start integration thread
            self.integration_thread = IntegrationThread(
                ttw_output_dir,
                Path(self._integration_install_dir),
                ttw_version
            )
            self.integration_thread.progress.connect(self._safe_append_text)
            self.integration_thread.finished.connect(self._on_integration_thread_finished)
            self.integration_thread.start()

        except Exception as e:
            # Close progress dialog if it exists
            if hasattr(self, '_integration_progress_dialog'):
                self._integration_progress_dialog.close()
                delattr(self, '_integration_progress_dialog')

            error_msg = f"Integration error: {str(e)}"
            self._safe_append_text(f"\nError: {error_msg}")
            debug_print(f"ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            self.integration_complete.emit(False, "")

    def _on_integration_thread_finished(self, success: bool, ttw_version: str):
        """Handle completion of integration thread"""
        try:
            # Close progress dialog
            if hasattr(self, '_integration_progress_dialog'):
                self._integration_progress_dialog.close()
                delattr(self, '_integration_progress_dialog')

            if success:
                self._safe_append_text("\nTTW integration completed successfully!")

                # Update status banner (only in integration mode)
                if self._integration_mode:
                    self.status_banner.setText("TTW integration completed successfully!")
                    self.status_banner.setStyleSheet(f"""
                        QLabel {{
                            background-color: #28a745;
                            color: white;
                            font-weight: bold;
                            padding: 8px;
                            border-radius: 5px;
                        }}
                    """)

                MessageService.information(
                    self, "Integration Complete",
                    f"TTW {ttw_version} has been successfully integrated into {self._integration_modlist_name}!",
                    safety_level="medium"
                )
                self.integration_complete.emit(True, ttw_version)
            else:
                self._safe_append_text("\nTTW integration failed!")

                # Update status banner (only in integration mode)
                if self._integration_mode:
                    self.status_banner.setText("TTW integration failed!")
                    self.status_banner.setStyleSheet(f"""
                        QLabel {{
                            background-color: #dc3545;
                            color: white;
                            font-weight: bold;
                            padding: 8px;
                            border-radius: 5px;
                        }}
                    """)

                MessageService.critical(
                    self, "Integration Failed",
                    "Failed to integrate TTW into the modlist. Check the log for details."
                )
                self.integration_complete.emit(False, ttw_version)
        except Exception as e:
            debug_print(f"ERROR: Failed to handle integration completion: {e}")
            self.integration_complete.emit(False, ttw_version)

    def _create_ttw_mod_archive(self, automated=False):
        """Create a zipped mod archive of TTW output for MO2 installation.

        Args:
            automated: If True, runs silently without user prompts (for automation)
        """
        try:
            from pathlib import Path
            import re
            from PySide6.QtCore import QThread, Signal

            output_dir = Path(self.install_dir_edit.text())
            if not output_dir.exists():
                if not automated:
                    MessageService.warning(self, "Output Directory Not Found",
                                         f"Output directory does not exist:\n{output_dir}")
                return False

            # Extract version from .mpi filename (e.g., "TTW v3.4.mpi" -> "3.4")
            mpi_path = self.file_edit.text().strip()
            version_suffix = ""
            if mpi_path:
                mpi_filename = Path(mpi_path).stem
                version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', mpi_filename, re.IGNORECASE)
                if version_match:
                    version_suffix = f" {version_match.group(1)}"

            # Create archive filename
            archive_name = f"[NoDelete] Tale of Two Wastelands{version_suffix}"
            archive_path = output_dir.parent / archive_name

            # Create background thread for zip creation
            class ZipCreationThread(QThread):
                finished = Signal(bool, str)  # success, result_message

                def __init__(self, output_dir, archive_path):
                    super().__init__()
                    self.output_dir = output_dir
                    self.archive_path = archive_path

                def run(self):
                    try:
                        import shutil
                        final_archive = shutil.make_archive(
                            str(self.archive_path),
                            'zip',
                            str(self.output_dir)
                        )
                        self.finished.emit(True, str(final_archive))
                    except Exception as e:
                        self.finished.emit(False, str(e))

            # Create progress dialog (non-modal so UI stays responsive)
            progress_dialog = QProgressDialog(
                f"Creating mod archive: {archive_name}.zip\n\n"
                "This may take several minutes depending on installation size...",
                "Cancel",
                0, 0,  # 0,0 = indeterminate progress bar
                self
            )
            progress_dialog.setWindowTitle("Creating Archive")
            progress_dialog.setMinimumDuration(0)  # Show immediately
            progress_dialog.setWindowModality(Qt.ApplicationModal)
            progress_dialog.setCancelButton(None)  # Cannot cancel zip operation safely
            progress_dialog.show()
            QApplication.processEvents()

            # Create and start thread
            zip_thread = ZipCreationThread(output_dir, archive_path)

            def on_zip_finished(success, result):
                progress_dialog.close()
                if success:
                    final_archive = result
                    if not automated:
                        self._safe_append_text(f"\nArchive created successfully: {Path(final_archive).name}")
                        MessageService.information(
                            self, "Archive Created",
                            f"TTW mod archive created successfully!\n\n"
                            f"Location: {final_archive}\n\n"
                            f"You can now install this archive as a mod in MO2.",
                            safety_level="medium"
                        )
                else:
                    error_msg = f"Failed to create mod archive: {result}"
                    if not automated:
                        self._safe_append_text(f"\nError: {error_msg}")
                        MessageService.critical(self, "Archive Creation Failed", error_msg)

            zip_thread.finished.connect(on_zip_finished)
            zip_thread.start()

            # Keep reference to prevent garbage collection
            self._zip_thread = zip_thread

            return True

        except Exception as e:
            error_msg = f"Failed to create mod archive: {str(e)}"
            if not automated:
                self._safe_append_text(f"\nError: {error_msg}")
                MessageService.critical(self, "Archive Creation Failed", error_msg)
            return False

    def cancel_installation(self):
        """Cancel the currently running installation"""
        reply = MessageService.question(
            self, "Cancel Installation",
            "Are you sure you want to cancel the installation?",
            critical=False  # Non-critical, won't steal focus
        )

        if reply == QMessageBox.Yes:
            self._safe_append_text("\nCancelling installation...")

            # Stop the elapsed timer if running
            if hasattr(self, 'ttw_elapsed_timer') and self.ttw_elapsed_timer.isActive():
                self.ttw_elapsed_timer.stop()

            # Update status banner
            if hasattr(self, 'status_banner'):
                self.status_banner.setText("Installation cancelled by user")
                self.status_banner.setStyleSheet(f"""
                    background-color: #4d3d1a;
                    color: #FFA500;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 13px;
                """)

            # Cancel the installation thread if it exists
            if hasattr(self, 'install_thread') and self.install_thread.isRunning():
                self.install_thread.cancel()
                self.install_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.install_thread.isRunning():
                    self.install_thread.terminate()  # Force terminate if needed
                    self.install_thread.wait(1000)
            
            # Cancel the automated prefix thread if it exists
            if hasattr(self, 'prefix_thread') and self.prefix_thread.isRunning():
                self.prefix_thread.terminate()
                self.prefix_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.prefix_thread.isRunning():
                    self.prefix_thread.terminate()  # Force terminate if needed
                    self.prefix_thread.wait(1000)
            
            # Cancel the configuration thread if it exists
            if hasattr(self, 'config_thread') and self.config_thread.isRunning():
                self.config_thread.terminate()
                self.config_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                if self.config_thread.isRunning():
                    self.config_thread.terminate()  # Force terminate if needed
                    self.config_thread.wait(1000)
            
            # Cleanup any remaining processes
            self.cleanup_processes()
            
            # Reset button states and re-enable all controls
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            
            self._safe_append_text("Installation cancelled by user.")

    def _show_somnium_post_install_guidance(self):
        """Show guidance popup for Somnium post-installation steps"""
        from ..services.message_service import MessageService
        
        guidance_text = f"""<b>Somnium Post-Installation Required</b><br><br>
Due to Somnium's non-standard folder structure, you need to manually update the binary paths in ModOrganizer:<br><br>
<b>1.</b> Launch the Steam shortcut created for Somnium<br>
<b>2.</b> In ModOrganizer, go to Settings → Executables<br>
<b>3.</b> For each executable entry (SKSE64, etc.), update the binary path to point to:<br>
<code>{self._somnium_install_dir}/files/root/Enderal Special Edition/skse64_loader.exe</code><br><br>
<b>Note:</b> Full Somnium support will be added in a future Jackify update.<br><br>
<i>You can also refer to the Somnium installation guide at:<br>
https://wiki.scenicroute.games/Somnium/1_Installation.html</i>"""
        
        MessageService.information(self, "Somnium Setup Required", guidance_text)
        
        # Reset the guidance flag
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

    def cancel_and_cleanup(self):
        """Handle Cancel button - clean up processes and go back"""
        self.cleanup_processes()
        # Restore main window to standard Jackify size before leaving
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                
                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
            
            # Ensure we exit in collapsed state so next entry starts compact (both Desktop and Deck)
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
                # Only toggle console visibility on Desktop (on Deck it's always visible)
                if not is_steamdeck:
                    self._toggle_console_visibility(_Qt.Unchecked)
        except Exception:
            pass
        self.go_back()
    
    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.file_edit.setText("")
        self.install_dir_edit.setText(self.config_handler.get_modlist_install_base_dir())

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Re-enable controls (in case they were disabled from previous errors)
        self._enable_controls_after_operation()

        # Check requirements when screen is actually shown (not on app startup)
        self.check_requirements()

 