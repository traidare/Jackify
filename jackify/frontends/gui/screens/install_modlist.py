"""
InstallModlistScreen for Jackify GUI
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QGridLayout, QFileDialog, QTextEdit, QSizePolicy, QTabWidget, QDialog, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QApplication, QCheckBox, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView, QMainWindow
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QProcess, QMetaObject, QUrl
from PySide6.QtGui import QPixmap, QTextCursor, QColor, QPainter, QFont
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import ansi_to_html, set_responsive_minimum
from ..widgets.unsupported_game_dialog import UnsupportedGameDialog
import os
import subprocess
import sys
import threading
from typing import Optional
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
from jackify.backend.utils.nexus_premium_detector import is_non_premium_indicator
# R&D: Progress reporting components
from jackify.backend.handlers.progress_parser import ProgressStateManager
from jackify.frontends.gui.widgets.progress_indicator import OverallProgressIndicator
from jackify.frontends.gui.widgets.file_progress_list import FileProgressList
from jackify.shared.progress_models import InstallationPhase, InstallationProgress, OperationType
# Modlist gallery (imported at module level to avoid import delay when opening dialog)
from jackify.frontends.gui.screens.modlist_gallery import ModlistGalleryDialog

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


class SelectionDialog(QDialog):
    def __init__(self, title, items, parent=None, show_search=True, placeholder_text="Search modlists...", show_legend=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)

        self.show_search = show_search
        if self.show_search:
            # Search box with clear button
            search_layout = QHBoxLayout()
            self.search_box = QLineEdit()
            self.search_box.setPlaceholderText(placeholder_text)
            # Make placeholder text lighter
            self.search_box.setStyleSheet("QLineEdit { color: #ccc; } QLineEdit:placeholder { color: #aaa; }")
            self.clear_btn = QPushButton("Clear")
            self.clear_btn.setFixedWidth(50)
            search_layout.addWidget(self.search_box)
            search_layout.addWidget(self.clear_btn)
            layout.addLayout(search_layout)

        if show_legend:
            # Use table for modlist selection with proper columns
            self.table_widget = QTableWidget()
            self.table_widget.setColumnCount(4)
            self.table_widget.setHorizontalHeaderLabels(["Modlist Name", "Download", "Install", "Total"])
            
            # Configure table appearance
            self.table_widget.setSelectionBehavior(QTableWidget.SelectRows)
            self.table_widget.setSelectionMode(QTableWidget.SingleSelection)
            self.table_widget.verticalHeader().setVisible(False)
            self.table_widget.setAlternatingRowColors(True)
            
            # Set column widths
            header = self.table_widget.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.Stretch)  # Modlist name takes remaining space
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Download size
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Install size  
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Total size
            
            
            self._all_items = list(items)
            self._populate_table(self._all_items)
            layout.addWidget(self.table_widget)
            
            # Apply initial NSFW filter since checkbox starts unchecked
            self._filter_nsfw(False)
        else:
            # Use list for non-modlist dialogs (backward compatibility)
            self.list_widget = QListWidget()
            self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._all_items = list(items)
            self._populate_list(self._all_items)
            layout.addWidget(self.list_widget)
        
        # Add interactive legend bar only for modlist selection dialogs
        if show_legend:
            legend_layout = QHBoxLayout()
            legend_layout.setContentsMargins(10, 5, 10, 5)
            
            # Status indicator explanation (far left)
            status_label = QLabel('<small><b>[DOWN]</b> Unavailable</small>')
            status_label.setStyleSheet("color: #bbb;")
            legend_layout.addWidget(status_label)
            
            # Spacer after DOWN legend
            legend_layout.addSpacing(15)
            
            # No need for size format explanation since we have table headers now
            # Just add some spacing
            
            # Main spacer to push NSFW checkbox to far right
            legend_layout.addStretch()
            
            # NSFW filter checkbox (far right)
            self.nsfw_checkbox = QCheckBox("Show NSFW")
            self.nsfw_checkbox.setStyleSheet("color: #bbb; font-size: 11px;")
            self.nsfw_checkbox.setChecked(False)  # Default to hiding NSFW content
            self.nsfw_checkbox.toggled.connect(self._filter_nsfw)
            legend_layout.addWidget(self.nsfw_checkbox)
            
            # Legend container
            legend_widget = QWidget()
            legend_widget.setLayout(legend_layout)
            legend_widget.setStyleSheet("background-color: #333; border-radius: 3px; margin: 2px;")
            layout.addWidget(legend_widget)
        
        self.selected_item = None
        
        # Connect appropriate signals based on widget type
        if show_legend:
            self.table_widget.itemClicked.connect(self.on_table_item_clicked)
            if self.show_search:
                self.search_box.textChanged.connect(self._filter_table)
                self.clear_btn.clicked.connect(self._clear_search)
                self.search_box.returnPressed.connect(self._focus_table)
                self.search_box.installEventFilter(self)
        else:
            self.list_widget.itemClicked.connect(self.on_item_clicked)
            if self.show_search:
                self.search_box.textChanged.connect(self._filter_list)
                self.clear_btn.clicked.connect(self._clear_search)
                self.search_box.returnPressed.connect(self._focus_list)
                self.search_box.installEventFilter(self)

    def _populate_list(self, items):
        self.list_widget.clear()
        for item in items:
            # Create list item - custom delegate handles all styling
            QListWidgetItem(item, self.list_widget)

    def _populate_table(self, items):
        self.table_widget.setRowCount(len(items))
        for row, item in enumerate(items):
            # Parse the item string to extract components
            # Format: "[STATUS] Modlist Name    Download|Install|Total"
            
            # Extract status indicators
            status_down = '[DOWN]' in item
            status_nsfw = '[NSFW]' in item
            
            # Clean the item string
            clean_item = item.replace('[DOWN]', '').replace('[NSFW]', '').strip()
            
            # Split into name and sizes
            # The format should be "Name    Download|Install|Total"
            parts = clean_item.rsplit('    ', 1)  # Split from right to separate name from sizes
            if len(parts) == 2:
                name = parts[0].strip()
                sizes = parts[1].strip()
                size_parts = sizes.split('|')
                if len(size_parts) == 3:
                    download_size, install_size, total_size = [s.strip() for s in size_parts]
                else:
                    # Fallback if format is unexpected
                    download_size = install_size = total_size = sizes
            else:
                # Fallback if format is unexpected
                name = clean_item
                download_size = install_size = total_size = ""
            
            # Create table items
            name_item = QTableWidgetItem(name)
            download_item = QTableWidgetItem(download_size)
            install_item = QTableWidgetItem(install_size)
            total_item = QTableWidgetItem(total_size)
            
            # Apply styling
            if status_down:
                # Gray out and strikethrough for DOWN items
                for item_widget in [name_item, download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#999999'))
                    font = item_widget.font()
                    font.setStrikeOut(True)
                    item_widget.setFont(font)
            elif status_nsfw:
                # Red text for NSFW items - but only the name, sizes stay white
                name_item.setForeground(QColor('#ff4444'))
                for item_widget in [download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#ffffff'))
            else:
                # White text for normal items
                for item_widget in [name_item, download_item, install_item, total_item]:
                    item_widget.setForeground(QColor('#ffffff'))
            
            # Add status indicators to name if present
            if status_nsfw:
                name_item.setText(f"[NSFW] {name}")
            if status_down:
                # For DOWN items, we want [DOWN] normal and the name strikethrough
                # Since we can't easily mix fonts in a single QTableWidgetItem, 
                # we'll style the whole item but the visual effect will be clear
                name_item.setText(f"[DOWN] {name_item.text()}")
            
            # Right-align size columns
            download_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            install_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            # Add items to table
            self.table_widget.setItem(row, 0, name_item)
            self.table_widget.setItem(row, 1, download_item)
            self.table_widget.setItem(row, 2, install_item)
            self.table_widget.setItem(row, 3, total_item)
            
            # Store original item text as data for filtering
            name_item.setData(Qt.UserRole, item)

    def _filter_list(self, text):
        text = text.strip().lower()
        if not text:
            filtered = self._all_items
        else:
            filtered = [item for item in self._all_items if text in item.lower()]
        self._populate_list(filtered)
        if filtered:
            self.list_widget.setCurrentRow(0)

    def _clear_search(self):
        self.search_box.clear()
        self.search_box.setFocus()

    def _focus_list(self):
        self.list_widget.setFocus()
        self.list_widget.setCurrentRow(0)

    def _focus_table(self):
        self.table_widget.setFocus()
        self.table_widget.setCurrentCell(0, 0)

    def _filter_table(self, text):
        text = text.strip().lower()
        if not text:
            # Show all rows
            for row in range(self.table_widget.rowCount()):
                self.table_widget.setRowHidden(row, False)
        else:
            # Filter rows based on modlist name
            for row in range(self.table_widget.rowCount()):
                name_item = self.table_widget.item(row, 0)
                if name_item:
                    # Search in the modlist name
                    match = text in name_item.text().lower()
                    self.table_widget.setRowHidden(row, not match)

    def on_table_item_clicked(self, item):
        # Get the original item text from the name column
        row = item.row()
        name_item = self.table_widget.item(row, 0)
        if name_item:
            original_item = name_item.data(Qt.UserRole)
            self.selected_item = original_item
            self.accept()

    def _filter_nsfw(self, show_nsfw):
        """Filter NSFW modlists based on checkbox state"""
        if show_nsfw:
            # Show all items
            filtered_items = self._all_items
        else:
            # Hide NSFW items
            filtered_items = [item for item in self._all_items if '[NSFW]' not in item]
        
        # Use appropriate populate method based on widget type
        if hasattr(self, 'table_widget'):
            self._populate_table(filtered_items)
            # Apply search filter if there's search text
            if hasattr(self, 'search_box') and self.search_box.text().strip():
                self._filter_table(self.search_box.text())
        else:
            self._populate_list(filtered_items)
            # Apply search filter if there's search text
            if hasattr(self, 'search_box') and self.search_box.text().strip():
                self._filter_list(self.search_box.text())

    def eventFilter(self, obj, event):
        if self.show_search and obj == self.search_box and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
                # Focus appropriate widget
                if hasattr(self, 'table_widget'):
                    self._focus_table()
                else:
                    self._focus_list()
                return True
        return super().eventFilter(obj, event)

    def on_item_clicked(self, item):
        self.selected_item = item.text()
        self.accept()

class InstallModlistScreen(QWidget):
    steam_restart_finished = Signal(bool, str)
    resize_request = Signal(str)  # Signal for expand/collapse like TTW screen
    def __init__(self, stacked_widget=None, main_menu_index=0):
        super().__init__()
        # Set size policy to prevent unnecessary expansion - let content determine size
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.debug = DEBUG_BORDERS
        # Remember original main window geometry/min-size to restore on expand (like TTW screen)
        self._saved_geometry = None
        self._saved_min_size = None
        self.online_modlists = {}  # {game_type: [modlist_dict, ...]}
        self.modlist_details = {}  # {modlist_name: modlist_dict}

        # Initialize log path (can be refreshed via refresh_paths method)
        self.refresh_paths()

        # Initialize services early
        from jackify.backend.services.api_key_service import APIKeyService
        from jackify.backend.services.nexus_auth_service import NexusAuthService
        from jackify.backend.services.resolution_service import ResolutionService
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.api_key_service = APIKeyService()
        self.auth_service = NexusAuthService()
        self.resolution_service = ResolutionService()
        self.config_handler = ConfigHandler()
        self.protontricks_service = ProtontricksDetectionService()
        
        # Somnium guidance tracking
        self._show_somnium_guidance = False
        self._somnium_install_dir = None

        # Console deduplication tracking
        self._last_console_line = None
        
        # Gallery cache preloading tracking
        self._gallery_cache_preload_started = False
        self._gallery_cache_preload_thread = None

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True
        
        # Initialize Wabbajack parser for game detection
        self.wabbajack_parser = WabbajackParser()
        
        # R&D: Initialize progress reporting components
        self.progress_state_manager = ProgressStateManager()
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.file_progress_list = FileProgressList()  # Shows all active files (scrolls if needed)
        self._premium_notice_shown = False
        self._premium_failure_active = False
        self._stalled_download_start_time = None  # Track when downloads stall
        self._stalled_download_notified = False
        self._post_install_sequence = self._build_post_install_sequence()
        self._post_install_total_steps = len(self._post_install_sequence)
        self._post_install_current_step = 0
        self._post_install_active = False
        self._post_install_last_label = ""
        self._bsa_hold_deadline = 0.0

        # No throttling needed - render loop handles smooth updates at 60fps

        # R&D: Create "Show Details" checkbox (reuse TTW pattern)
        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)  # Start collapsed
        self.show_details_checkbox.setToolTip("Toggle between activity summary and detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)

        main_overall_vbox = QVBoxLayout(self)
        self.main_overall_vbox = main_overall_vbox  # Store reference for expand/collapse
        main_overall_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_overall_vbox.setContentsMargins(50, 50, 50, 0)  # No bottom margin
        main_overall_vbox.setSpacing(0)  # No spacing between widgets to eliminate gaps
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # --- Header (title, description) ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)  # Reduce spacing between title and description
        # Title (no logo)
        title = QLabel("<b>Install a Modlist (Automated)</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)  # Force compact height
        header_layout.addWidget(title)
        # Description
        desc = QLabel(
            "This screen allows you to install a Wabbajack modlist using Jackify. "
            "Configure your options and start the installation."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px; line-height: 1.2;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)  # Force compact height for description
        header_layout.addWidget(desc)
        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)  # Increase header height by 25% (60 + 15)
        if self.debug:
            header_widget.setStyleSheet("border: 2px solid pink;")
            header_widget.setToolTip("HEADER_SECTION")
        main_overall_vbox.addWidget(header_widget)

        # --- Upper section: user-configurables (left) + process monitor (right) ---
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)
        upper_hbox.setAlignment(Qt.AlignTop)  # Align both sides at the top
        # Left: user-configurables (form and controls)
        user_config_vbox = QVBoxLayout()
        user_config_vbox.setAlignment(Qt.AlignTop)
        user_config_vbox.setSpacing(4)  # Reduce spacing between major form sections
        user_config_vbox.setContentsMargins(0, 0, 0, 0)  # No margins to ensure tab alignment
        # --- Tabs for source selection ---
        self.source_tabs = QTabWidget()
        self.source_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.source_tabs.setContentsMargins(0, 0, 0, 0)  # Ensure no margins for alignment
        self.source_tabs.setDocumentMode(False)  # Keep frame for consistency
        self.source_tabs.setTabPosition(QTabWidget.North)  # Ensure tabs are at top
        if self.debug:
            self.source_tabs.setStyleSheet("border: 2px solid cyan;")
            self.source_tabs.setToolTip("SOURCE_TABS")
        # --- Online List Tab ---
        online_tab = QWidget()
        online_tab_vbox = QVBoxLayout()
        online_tab_vbox.setAlignment(Qt.AlignTop)
        # Online List Controls
        self.online_group = QWidget()
        online_layout = QHBoxLayout()
        online_layout.setContentsMargins(0, 0, 0, 0)
        # --- Game Type Selection ---
        self.game_types = ["Skyrim", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal", "Other"]
        self.game_type_btn = QPushButton("Please Select...")
        self.game_type_btn.setMinimumWidth(200)
        self.game_type_btn.clicked.connect(self.open_game_type_dialog)
        # --- Modlist Selection ---
        self.modlist_btn = QPushButton("Select Modlist")
        self.modlist_btn.setMinimumWidth(300)
        self.modlist_btn.clicked.connect(self.open_modlist_dialog)
        self.modlist_btn.setEnabled(False)
        online_layout.addWidget(QLabel("Game Type:"))
        online_layout.addWidget(self.game_type_btn)
        online_layout.addSpacing(4)  # Reduced from 16 to 4
        online_layout.addWidget(QLabel("Modlist:"))
        online_layout.addWidget(self.modlist_btn)
        self.online_group.setLayout(online_layout)
        online_tab_vbox.addWidget(self.online_group)
        online_tab.setLayout(online_tab_vbox)
        self.source_tabs.addTab(online_tab, "Select Modlist")
        # --- File Picker Tab ---
        file_tab = QWidget()
        file_tab_vbox = QVBoxLayout()
        file_tab_vbox.setAlignment(Qt.AlignTop)
        self.file_group = QWidget()
        file_layout = QHBoxLayout()
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setMinimumWidth(400)
        self.file_btn = QPushButton("Browse")
        self.file_btn.clicked.connect(self.browse_wabbajack_file)
        file_layout.addWidget(QLabel(".wabbajack File:"))
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(self.file_btn)
        self.file_group.setLayout(file_layout)
        file_tab_vbox.addWidget(self.file_group)
        file_tab.setLayout(file_tab_vbox)
        self.source_tabs.addTab(file_tab, "Use .wabbajack File")
        user_config_vbox.addWidget(self.source_tabs)
        # --- Install/Downloads Dir/API Key (reuse Tuxborn style) ---
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)  # Increased from 1 to 6 for better readability
        form_grid.setContentsMargins(0, 0, 0, 0)
        # Modlist Name (NEW FIELD)
        modlist_name_label = QLabel("Modlist Name:")
        self.modlist_name_edit = QLineEdit()
        self.modlist_name_edit.setMaximumHeight(25)  # Force compact height
        form_grid.addWidget(modlist_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.modlist_name_edit, 0, 1)
        # Install Dir
        install_dir_label = QLabel("Install Directory:")
        self.install_dir_edit = QLineEdit(self.config_handler.get_modlist_install_base_dir())
        self.install_dir_edit.setMaximumHeight(25)  # Force compact height
        self.browse_install_btn = QPushButton("Browse")
        self.browse_install_btn.clicked.connect(self.browse_install_dir)
        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(self.browse_install_btn)
        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)
        # Downloads Dir
        downloads_dir_label = QLabel("Downloads Directory:")
        self.downloads_dir_edit = QLineEdit(self.config_handler.get_modlist_downloads_base_dir())
        self.downloads_dir_edit.setMaximumHeight(25)  # Force compact height
        self.browse_downloads_btn = QPushButton("Browse")
        self.browse_downloads_btn.clicked.connect(self.browse_downloads_dir)
        downloads_dir_hbox = QHBoxLayout()
        downloads_dir_hbox.addWidget(self.downloads_dir_edit)
        downloads_dir_hbox.addWidget(self.browse_downloads_btn)
        form_grid.addWidget(downloads_dir_label, 2, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(downloads_dir_hbox, 2, 1)

        # Nexus Login (OAuth)
        nexus_login_label = QLabel("Nexus Login:")
        self.nexus_status = QLabel("Checking...")
        self.nexus_status.setStyleSheet("color: #ccc;")
        self.nexus_login_btn = QPushButton("Authorise")
        self.nexus_login_btn.setStyleSheet("""
            QPushButton:hover { opacity: 0.95; }
            QPushButton:disabled { opacity: 0.6; }
        """)
        self.nexus_login_btn.setMaximumWidth(90)
        self.nexus_login_btn.setVisible(False)
        self.nexus_login_btn.clicked.connect(self._handle_nexus_login_click)

        nexus_hbox = QHBoxLayout()
        nexus_hbox.setContentsMargins(0, 0, 0, 0)
        nexus_hbox.setSpacing(8)
        nexus_hbox.addWidget(self.nexus_login_btn)
        nexus_hbox.addWidget(self.nexus_status)
        nexus_hbox.addStretch()

        form_grid.addWidget(nexus_login_label, 3, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(nexus_hbox, 3, 1)

        # Update nexus status on init
        self._update_nexus_status()

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
        form_grid.addWidget(resolution_label, 5, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        
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
        self.auto_restart_checkbox.setToolTip("When checked, Steam restart dialog will be automatically accepted, allowing unattended installation")
        resolution_and_restart_layout.addWidget(self.auto_restart_checkbox)
        
        form_grid.addLayout(resolution_and_restart_layout, 5, 1)
        form_section_widget = QWidget()
        form_section_widget.setLayout(form_grid)
        # Let form section size naturally to its content
        # Don't force a fixed height - let it calculate based on grid content
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if self.debug:
            form_section_widget.setStyleSheet("border: 2px solid blue;")
            form_section_widget.setToolTip("FORM_SECTION")
        user_config_vbox.addWidget(form_section_widget)
        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)
        self.start_btn = QPushButton("Start Installation")
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
        
        # Wrap button row in widget for debug borders
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)  # Limit height to make it more compact
        if self.debug:
            btn_row_widget.setStyleSheet("border: 2px solid red;")
            btn_row_widget.setToolTip("BUTTON_ROW")
        user_config_widget = QWidget()
        self.user_config_widget = user_config_widget  # Store reference for height calculation
        user_config_widget.setLayout(user_config_vbox)
        user_config_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)  # Fixed height - don't expand unnecessarily
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
        # Match size policy - Process Monitor should expand to fill available space
        process_monitor_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self.debug:
            process_monitor_widget.setStyleSheet("border: 2px solid purple;")
            process_monitor_widget.setToolTip("PROCESS_MONITOR")
        # Store reference
        self.process_monitor_widget = process_monitor_widget
        
        # Set up File Progress List (Activity tab)
        # Match Process Monitor size policy exactly - expand to fill available space
        self.file_progress_list.setMinimumSize(QSize(300, 20))
        self.file_progress_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Create tab widget to hold both Activity and Process Monitor
        # Match styling of source_tabs on the left for consistency
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet("QTabWidget::pane { background: #222; border: 1px solid #444; } QTabBar::tab { background: #222; color: #ccc; padding: 6px 16px; } QTabBar::tab:selected { background: #333; color: #3fd0ea; } QTabWidget { margin: 0px; padding: 0px; } QTabBar { margin: 0px; padding: 0px; }")
        self.activity_tabs.setContentsMargins(0, 0, 0, 0)  # Ensure no margins for alignment
        self.activity_tabs.setDocumentMode(False)  # Match left tabs
        self.activity_tabs.setTabPosition(QTabWidget.North)  # Ensure tabs are at top
        if self.debug:
            self.activity_tabs.setStyleSheet("border: 2px solid cyan;")
            self.activity_tabs.setToolTip("ACTIVITY_TABS")
        
        # Add both widgets as tabs
        self.activity_tabs.addTab(self.file_progress_list, "Activity")
        self.activity_tabs.addTab(process_monitor_widget, "Process Monitor")
        
        upper_hbox.addWidget(user_config_widget, stretch=1, alignment=Qt.AlignTop)
        # Add tab widget with stretch=3 to match original Process Monitor stretch
        upper_hbox.addWidget(self.activity_tabs, stretch=3, alignment=Qt.AlignTop)
        upper_section_widget = QWidget()
        self.upper_section_widget = upper_section_widget  # Store reference for showEvent
        upper_section_widget.setLayout(upper_hbox)
        # Use Fixed size policy - the height should be based on LEFT side only
        # This ensures consistent height whether Active Files or Process Monitor is shown
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Calculate height based on LEFT side (user_config_widget) only
        # This ensures the same height regardless of which right widget is visible
        self._upper_section_fixed_height = None  # Will be set in showEvent based on left side
        if self.debug:
            upper_section_widget.setStyleSheet("border: 2px solid green;")
            upper_section_widget.setToolTip("UPPER_SECTION")
        main_overall_vbox.addWidget(upper_section_widget)
        
        # Add spacing between upper section and progress banner
        main_overall_vbox.addSpacing(8)
        
        # R&D: Progress indicator banner row (similar to TTW screen)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()
        banner_row.addWidget(self.show_details_checkbox)
        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        # Constrain height to prevent unwanted vertical expansion
        banner_row_widget.setMaximumHeight(45)  # Compact height: 34px label + small margin
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_overall_vbox.addWidget(banner_row_widget)
        
        # Add spacing between progress banner and console/details area
        main_overall_vbox.addSpacing(8)
        
        # R&D: File progress list is now in the upper section (replacing Process Monitor)
        # Console shows below when "Show details" is checked
        # NOTE: File progress list is already added to upper_hbox above
        
        # Remove spacing - console should expand to fill available space
        # --- Console output area (full width, placeholder for now) ---
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        # R&D: Console starts hidden (only shows when "Show details" is checked)
        self.console.setMinimumHeight(0)
        self.console.setMaximumHeight(0)
        self.console.setVisible(False)
        self.console.setFontFamily('monospace')
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")
            self.console.setToolTip("CONSOLE")
        
        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()
        
        # Create a container that holds console + button row with proper spacing
        console_and_buttons_widget = QWidget()
        console_and_buttons_layout = QVBoxLayout()
        console_and_buttons_layout.setContentsMargins(0, 0, 0, 0)
        console_and_buttons_layout.setSpacing(0)  # No spacing - console is hidden initially
        
        # Console with stretch only when visible, buttons always at natural size
        console_and_buttons_layout.addWidget(self.console)  # No stretch initially - will be set dynamically
        console_and_buttons_layout.addWidget(btn_row_widget)  # Buttons at bottom of this container
        
        console_and_buttons_widget.setLayout(console_and_buttons_layout)
        self.console_and_buttons_widget = console_and_buttons_widget  # Store reference for stretch control
        self.console_and_buttons_layout = console_and_buttons_layout  # Store reference for spacing control
        # Use Minimum size policy - takes only the minimum space needed
        console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # Constrain height to button row only when console is hidden - match button row height exactly
        # Button row is 50px max, so container should be exactly that when collapsed
        console_and_buttons_widget.setFixedHeight(50)  # Lock to exact button row height when console is hidden
        if self.debug:
            console_and_buttons_widget.setStyleSheet("border: 2px solid lightblue;")
            console_and_buttons_widget.setToolTip("CONSOLE_AND_BUTTONS_CONTAINER")
        # Add without stretch - let it size naturally to content
        main_overall_vbox.addWidget(console_and_buttons_widget)
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
        
        # Now collect all actionable controls after UI is fully built
        self._collect_actionable_controls()
    
    def _collect_actionable_controls(self):
        """Collect all actionable controls that should be disabled during operations (except Cancel)"""
        self._actionable_controls = [
            # Main action button
            self.start_btn,
            # Game/modlist selection
            self.game_type_btn,
            self.modlist_btn,
            # Source tabs (entire tab widget)
            self.source_tabs,
            # Form fields
            self.modlist_name_edit,
            self.install_dir_edit,
            self.downloads_dir_edit,
            self.file_edit,
            # Browse buttons
            self.browse_install_btn,
            self.browse_downloads_btn,
            self.file_btn,
            # Resolution controls
            self.resolution_combo,
            # Nexus login button
            self.nexus_login_btn,
            # Checkboxes
            self.auto_restart_checkbox,
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

    def _abort_install_validation(self):
        """Reset UI state when validation is aborted early."""
        self._enable_controls_after_operation()
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        self.progress_indicator.reset()
        self.process_monitor.clear()

    def _abort_with_message(self, level: str, title: str, message: str, **kwargs):
        """Show a message and abort the validation workflow."""
        messenger = getattr(MessageService, level, MessageService.warning)
        messenger(self, title, message, **kwargs)
        self._abort_install_validation()

    def refresh_paths(self):
        """Refresh cached paths when config changes."""
        from jackify.shared.paths import get_jackify_logs_dir
        self.modlist_log_path = get_jackify_logs_dir() / 'Modlist_Install_workflow.log'
        os.makedirs(os.path.dirname(self.modlist_log_path), exist_ok=True)

    def _open_url_safe(self, url):
        """Safely open URL via subprocess to avoid Qt library clashes inside the AppImage runtime"""
        import subprocess
        try:
            subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Warning: Could not open URL {url}: {e}")

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

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure collapsed state"""
        super().showEvent(event)

        # Refresh Nexus auth status when screen becomes visible
        # This ensures auth status is updated after user completes OAuth from Settings menu
        self._update_nexus_status()

        # Do NOT load saved parent directories

        # Note: Gallery cache preload now happens at app startup (see JackifyMainWindow.__init__)
        # This ensures cache is ready before user even navigates to this screen

        # Ensure initial collapsed layout each time this screen is opened (like TTW screen)
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            # Force collapsed state
            self._toggle_console_visibility(_Qt.Unchecked)
            # Force the window to compact height
            main_window = self.window()
            if main_window:
                # Save original geometry once
                if self._saved_geometry is None:
                    self._saved_geometry = main_window.geometry()
                if self._saved_min_size is None:
                    self._saved_min_size = main_window.minimumSize()
                # Use Qt's standard approach: let layout size naturally, only set minimum
                # This allows manual resizing and prevents content cut-off
                from PySide6.QtCore import QTimer, QSize
                from PySide6.QtWidgets import QApplication
                
                def calculate_and_set_upper_section_height():
                    """Calculate and lock the upper section height based on left side only"""
                    try:
                        if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                            # Only calculate if we haven't stored it yet
                            if not hasattr(self, '_upper_section_fixed_height') or self._upper_section_fixed_height is None:
                                # Calculate height based on LEFT side (user_config_widget) only
                                if hasattr(self, 'user_config_widget') and self.user_config_widget is not None:
                                    # Force layout updates to ensure everything is calculated
                                    self.user_config_widget.updateGeometry()
                                    self.user_config_widget.layout().update()
                                    self.updateGeometry()
                                    self.layout().update()
                                    QApplication.processEvents()
                                    # Get the natural height of the left side
                                    left_height = self.user_config_widget.sizeHint().height()
                                    # Add a small margin for spacing
                                    self._upper_section_fixed_height = left_height + 20
                                else:
                                    # Fallback: use sizeHint of upper section
                                    self.upper_section_widget.updateGeometry()
                                    self._upper_section_fixed_height = self.upper_section_widget.sizeHint().height()
                            # Lock the height - same in both modes
                            self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                            self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)
                    except Exception as e:
                        if self.debug:
                            print(f"DEBUG: Error calculating upper section height: {e}")
                        pass
                
                # Calculate heights immediately after forcing layout update
                # This prevents visible layout shift
                self.updateGeometry()
                self.layout().update()
                QApplication.processEvents()
                
                # Calculate upper section height immediately
                calculate_and_set_upper_section_height()

                # Only set minimum size - DO NOT RESIZE
                from PySide6.QtCore import QSize
                # On Steam Deck, keep fullscreen; on other systems, set normal window state
                if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                    main_window.showNormal()
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception as e:
            debug_print(f"DEBUG: showEvent exception: {e}")
    
    def _start_gallery_cache_preload(self):
        """DEPRECATED: Gallery cache preload now happens at app startup in JackifyMainWindow"""
        # Only start once per session
        if self._gallery_cache_preload_started:
            return

        self._gallery_cache_preload_started = True
        
        # Create background thread to preload gallery cache
        class GalleryCachePreloadThread(QThread):
            finished_signal = Signal(bool, str)  # success, message
            
            def run(self):
                try:
                    from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
                    service = ModlistGalleryService()
                    
                    # Fetch with search index to build cache (this will take time but is invisible)
                    # Use force_refresh=False to allow using existing cache if it has mods
                    metadata = service.fetch_modlist_metadata(
                        include_validation=False,  # Skip validation for speed
                        include_search_index=True,  # Include mods for search
                        sort_by="title",
                        force_refresh=False  # Use cache if it has mods, otherwise fetch fresh
                    )
                    
                    if metadata:
                        # Check if we got mods
                        modlists_with_mods = sum(1 for m in metadata.modlists if hasattr(m, 'mods') and m.mods)
                        if modlists_with_mods > 0:
                            debug_print(f"DEBUG: Gallery cache ready ({modlists_with_mods} modlists with mods)")
                        else:
                            # Cache didn't have mods, but we fetched fresh - should have mods now
                            debug_print("DEBUG: Gallery cache updated")
                    else:
                        debug_print("DEBUG: Failed to load gallery cache")
                        
                except Exception as e:
                    debug_print(f"DEBUG: Gallery cache preload error: {str(e)}")
        
        # Start thread (non-blocking, invisible to user)
        self._gallery_cache_preload_thread = GalleryCachePreloadThread()
        # Don't connect finished signal - we don't need to do anything, just let it run
        self._gallery_cache_preload_thread.start()
        
        debug_print("DEBUG: Started background gallery cache preload")

    def hideEvent(self, event):
        """Called when the widget is hidden - restore window size constraints"""
        super().hideEvent(event)
        try:
            # Check if we're on Steam Deck - if so, clear constraints to prevent affecting other screens
            main_window = self.window()
            is_steamdeck = False
            if hasattr(main_window, 'system_info') and main_window.system_info:
                is_steamdeck = getattr(main_window.system_info, 'is_steamdeck', False)
            
            if main_window:
                from PySide6.QtCore import QSize
                # Clear any size constraints that might have been set to prevent affecting other screens
                # This is especially important for Steam Deck but also helps on desktop
                main_window.setMaximumSize(QSize(16777215, 16777215))
                main_window.setMinimumSize(QSize(0, 0))
                debug_print("DEBUG: Install Modlist hideEvent - cleared window size constraints")
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
                self.downloads_dir_edit.setText(suggested_download_dir)
                debug_print(f"DEBUG: Updated download directory suggestion: {suggested_download_dir}")
                
        except Exception as e:
            debug_print(f"DEBUG: Error updating directory suggestions: {e}")
    
    def _save_parent_directories(self, install_dir, downloads_dir):
        """Removed automatic saving - user should set defaults in settings"""
        pass

    def _update_nexus_status(self):
        """Update the Nexus login status display"""
        authenticated, method, username = self.auth_service.get_auth_status()

        if authenticated and method == 'oauth':
            # OAuth authorised
            status_text = "Authorised"
            if username:
                status_text += f" ({username})"
            self.nexus_status.setText(status_text)
            self.nexus_status.setStyleSheet("color: #3fd0ea;")
            self.nexus_login_btn.setText("Revoke")
            self.nexus_login_btn.setVisible(True)
        elif authenticated and method == 'api_key':
            # API Key in use (fallback - configured in Settings)
            self.nexus_status.setText("API Key")
            self.nexus_status.setStyleSheet("color: #FFA726;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)
        else:
            # Not authorised
            self.nexus_status.setText("Not Authorised")
            self.nexus_status.setStyleSheet("color: #f44336;")
            self.nexus_login_btn.setText("Authorise")
            self.nexus_login_btn.setVisible(True)

    def _show_copyable_url_dialog(self, url: str):
        """Show a dialog with a copyable URL"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QApplication
        from PySide6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle("Manual Browser Open Required")
        dialog.setModal(True)
        dialog.setMinimumWidth(600)

        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Explanation label
        info_label = QLabel(
            "Could not open browser automatically.\n\n"
            "Please copy the URL below and paste it into your browser:"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #ccc; font-size: 12px;")
        layout.addWidget(info_label)

        # URL input (read-only but selectable)
        url_input = QLineEdit()
        url_input.setText(url)
        url_input.setReadOnly(True)
        url_input.selectAll()  # Pre-select text for easy copying
        url_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #3fd0ea;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(url_input)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Copy button
        copy_btn = QPushButton("Copy URL")
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3fd0ea;
                color: #000;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5fdfff;
            }
        """)
        def copy_to_clipboard():
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            copy_btn.setText("Copied!")
            copy_btn.setEnabled(False)
        copy_btn.clicked.connect(copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.setLayout(layout)
        dialog.exec()

    def _handle_nexus_login_click(self):
        """Handle Nexus login button click"""
        from jackify.frontends.gui.services.message_service import MessageService
        from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication
        from PySide6.QtCore import Qt, QThread, Signal

        authenticated, method, _ = self.auth_service.get_auth_status()
        if authenticated and method == 'oauth':
            # OAuth is active - offer to revoke
            reply = MessageService.question(self, "Revoke", "Revoke OAuth authorisation?", safety_level="low")
            if reply == QMessageBox.Yes:
                self.auth_service.revoke_oauth()
                self._update_nexus_status()
        else:
            # Not authorised or using API key - offer to authorise with OAuth
            reply = MessageService.question(self, "Authorise with Nexus",
                "Your browser will open for Nexus authorisation.\n\n"
                "Note: Your browser may ask permission to open 'xdg-open'\n"
                "or Jackify's protocol handler - please click 'Open' or 'Allow'.\n\n"
                "Please log in and authorise Jackify when prompted.\n\n"
                "Continue?", safety_level="low")

            if reply != QMessageBox.Yes:
                return

            # Create progress dialog
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

            # Track cancellation
            oauth_cancelled = [False]

            def on_cancel():
                oauth_cancelled[0] = True

            progress.canceled.connect(on_cancel)
            progress.show()
            QApplication.processEvents()

            # Create OAuth thread to prevent GUI freeze
            class OAuthThread(QThread):
                finished_signal = Signal(bool)
                message_signal = Signal(str)
                manual_url_signal = Signal(str)  # Signal when browser fails to open

                def __init__(self, auth_service, parent=None):
                    super().__init__(parent)
                    self.auth_service = auth_service

                def run(self):
                    def show_message(msg):
                        # Check if this is a "browser failed" message with URL
                        if "Could not open browser" in msg and "Please open this URL manually:" in msg:
                            # Extract URL from message
                            url_start = msg.find("Please open this URL manually:") + len("Please open this URL manually:")
                            url = msg[url_start:].strip()
                            self.manual_url_signal.emit(url)
                        else:
                            self.message_signal.emit(msg)

                    success = self.auth_service.authorize_oauth(show_browser_message_callback=show_message)
                    self.finished_signal.emit(success)

            oauth_thread = OAuthThread(self.auth_service, self)

            # Connect message signal to update progress dialog
            def update_progress_message(msg):
                if not oauth_cancelled[0]:
                    progress.setLabelText(f"Waiting for authorisation...\n\n{msg}")
                    QApplication.processEvents()

            # Connect manual URL signal to show copyable dialog
            def show_manual_url_dialog(url):
                if not oauth_cancelled[0]:
                    progress.hide()  # Hide progress dialog temporarily
                    self._show_copyable_url_dialog(url)
                    progress.show()

            oauth_thread.message_signal.connect(update_progress_message)
            oauth_thread.manual_url_signal.connect(show_manual_url_dialog)

            # Wait for thread completion
            oauth_success = [False]
            def on_oauth_finished(success):
                oauth_success[0] = success

            oauth_thread.finished_signal.connect(on_oauth_finished)
            oauth_thread.start()

            # Wait for thread to finish (non-blocking event loop)
            while oauth_thread.isRunning():
                QApplication.processEvents()
                oauth_thread.wait(100)  # Check every 100ms
                if oauth_cancelled[0]:
                    # User cancelled - thread will still complete but we ignore result
                    oauth_thread.wait(2000)
                    if oauth_thread.isRunning():
                        oauth_thread.terminate()
                    break

            progress.close()
            QApplication.processEvents()

            self._update_nexus_status()
            self._enable_controls_after_operation()

            # Check success first - if OAuth succeeded, ignore cancellation flag
            # (progress dialog close can trigger cancel handler even on success)
            if oauth_success[0]:
                _, _, username = self.auth_service.get_auth_status()
                if username:
                    msg = f"OAuth authorisation successful!<br><br>Authorised as: {username}"
                else:
                    msg = "OAuth authorisation successful!"
                MessageService.information(self, "Success", msg, safety_level="low")
            elif oauth_cancelled[0]:
                MessageService.information(self, "Cancelled", "OAuth authorisation cancelled.", safety_level="low")
            else:
                MessageService.warning(
                    self,
                    "Authorisation Failed",
                    "OAuth authorisation failed.\n\n"
                    "If you see 'redirect URI mismatch' in your browser,\n"
                    "the OAuth redirect URI needs to be configured by Nexus.\n\n"
                    "You can configure an API key in Settings as a fallback.",
                    safety_level="medium"
                )

    def open_game_type_dialog(self):
        dlg = SelectionDialog("Select Game Type", self.game_types, self, show_search=False)
        if dlg.exec() == QDialog.Accepted and dlg.selected_item:
            self.game_type_btn.setText(dlg.selected_item)
            # Store game type for gallery filter
            self.current_game_type = dlg.selected_item
            # Enable modlist button immediately - gallery will fetch its own data
            self.modlist_btn.setEnabled(True)
            self.modlist_btn.setText("Select Modlist")
            # No need to fetch modlists here - gallery does it when opened

    def fetch_modlists_for_game_type(self, game_type):
        self.current_game_type = game_type  # Store for display formatting
        self.modlist_btn.setText("Fetching modlists...")
        self.modlist_btn.setEnabled(False)
        game_type_map = {
            "Skyrim": "skyrim",
            "Fallout 4": "fallout4",
            "Fallout New Vegas": "falloutnv",
            "Oblivion": "oblivion",
            "Starfield": "starfield",
            "Oblivion Remastered": "oblivion_remastered",
            "Enderal": "enderal",
            "Other": "other"
        }
        cli_game_type = game_type_map.get(game_type, "other")
        log_path = self.modlist_log_path
        # Use backend service directly - NO CLI CALLS
        self.fetch_thread = ModlistFetchThread(
            cli_game_type, log_path, mode='list-modlists')
        self.fetch_thread.result.connect(self.on_modlists_fetched)
        self.fetch_thread.start()

    def on_modlists_fetched(self, modlist_infos, error):
        # Handle the case where modlist_infos might be strings (backward compatibility)
        if modlist_infos and isinstance(modlist_infos[0], str):
            # Old format - just IDs as strings
            filtered = [m for m in modlist_infos if m and not m.startswith('DEBUG:')]
            self.current_modlists = filtered
            self.current_modlist_display = filtered
        else:
            # New format - full modlist objects with enhanced metadata
            filtered_modlists = [m for m in modlist_infos if m and hasattr(m, 'id')]
            filtered = filtered_modlists  # Set filtered for the condition check below
            self.current_modlists = [m.id for m in filtered_modlists]  # Keep IDs for selection
            
            # Create enhanced display strings with size info and status indicators
            display_strings = []
            for modlist in filtered_modlists:
                # Get enhanced metadata
                download_size = getattr(modlist, 'download_size', '')
                install_size = getattr(modlist, 'install_size', '')
                total_size = getattr(modlist, 'total_size', '')
                status_down = getattr(modlist, 'status_down', False)
                status_nsfw = getattr(modlist, 'status_nsfw', False)
                
                # Format display string without redundant game type: "Modlist Name - Download|Install|Total"
                # For "Other" category, include game type in brackets for clarity
                # Use padding to create alignment: left-aligned name, right-aligned sizes
                if hasattr(self, 'current_game_type') and self.current_game_type == "Other":
                    name_part = f"{modlist.name} [{modlist.game}]"
                else:
                    name_part = modlist.name
                size_part = f"{download_size}|{install_size}|{total_size}"
                
                # Create aligned display using string formatting (approximate alignment)
                display_str = f"{name_part:<50} {size_part:>15}"
                
                # Add status indicators at the beginning if present
                if status_down or status_nsfw:
                    status_parts = []
                    if status_down:
                        status_parts.append("[DOWN]")
                    if status_nsfw:
                        status_parts.append("[NSFW]") 
                    display_str = " ".join(status_parts) + " " + display_str
                
                display_strings.append(display_str)
            
            self.current_modlist_display = display_strings
        
        # Create mapping from display string back to modlist ID for selection
        self._modlist_id_map = {}
        if len(self.current_modlist_display) == len(self.current_modlists):
            self._modlist_id_map = {display: modlist_id for display, modlist_id in 
                                  zip(self.current_modlist_display, self.current_modlists)}
        else:
            # Fallback for backward compatibility
            self._modlist_id_map = {mid: mid for mid in self.current_modlists}
        if error:
            self.modlist_btn.setText("Error fetching modlists.")
            self.modlist_btn.setEnabled(False)
            # Don't write to log file before workflow starts - just show error in UI
        elif filtered:
            self.modlist_btn.setText("Select Modlist")
            self.modlist_btn.setEnabled(True)
        else:
            self.modlist_btn.setText("No modlists found.")
            self.modlist_btn.setEnabled(False)

    def open_modlist_dialog(self):
        # CRITICAL: Prevent opening gallery without game type selected
        # This prevents potential issues with engine path resolution and subprocess spawning
        if not hasattr(self, 'current_game_type') or not self.current_game_type:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Game Type Required",
                "Please select a game type before opening the modlist gallery."
            )
            return
        
        from PySide6.QtWidgets import QApplication
        self.modlist_btn.setEnabled(False)
        cursor_overridden = False
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            cursor_overridden = True

            game_type_to_human_friendly = {
                "Skyrim": "Skyrim Special Edition",
                "Fallout 4": "Fallout 4",
                "Fallout New Vegas": "Fallout New Vegas",
                "Oblivion": "Oblivion",
                "Starfield": "Starfield",
                "Oblivion Remastered": "Oblivion",
                "Enderal": "Enderal Special Edition",
                "Other": None
            }

            game_filter = None
            if hasattr(self, 'current_game_type'):
                game_filter = game_type_to_human_friendly.get(self.current_game_type)

            dlg = ModlistGalleryDialog(game_filter=game_filter, parent=self)
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
                cursor_overridden = False

            if dlg.exec() == QDialog.Accepted and dlg.selected_metadata:
                metadata = dlg.selected_metadata
                self.modlist_btn.setText(metadata.title)
                self.selected_modlist_info = {
                    'machine_url': metadata.namespacedName,
                    'title': metadata.title,
                    'author': metadata.author,
                    'game': metadata.gameHumanFriendly,
                    'description': metadata.description,
                    'nsfw': metadata.nsfw,
                    'force_down': metadata.forceDown
                }
                self.modlist_name_edit.setText(metadata.title)

                # Auto-append modlist name to install directory
                base_install_dir = self.config_handler.get_modlist_install_base_dir()
                if base_install_dir:
                    # Sanitize modlist title for filesystem use
                    import re
                    safe_title = re.sub(r'[<>:"/\\|?*]', '', metadata.title)
                    safe_title = safe_title.strip()
                    modlist_install_path = os.path.join(base_install_dir, safe_title)
                    self.install_dir_edit.setText(modlist_install_path)
        finally:
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
            self.modlist_btn.setEnabled(True)

    def browse_wabbajack_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select .wabbajack File", os.path.expanduser("~"), "Wabbajack Files (*.wabbajack)")
        if file:
            self.file_edit.setText(file)

    def browse_install_dir(self):
        dir = QFileDialog.getExistingDirectory(self, "Select Install Directory", self.install_dir_edit.text())
        if dir:
            self.install_dir_edit.setText(dir)

    def browse_downloads_dir(self):
        dir = QFileDialog.getExistingDirectory(self, "Select Downloads Directory", self.downloads_dir_edit.text())
        if dir:
            self.downloads_dir_edit.setText(dir)

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
                     "hoolamike" in line_lower)
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

    def _check_ttw_eligibility(self, modlist_name: str, game_type: str, install_dir: str) -> bool:
        """Check if modlist is FNV, TTW-compatible, and doesn't already have TTW

        Args:
            modlist_name: Name of the installed modlist
            game_type: Game type (e.g., 'falloutnv')
            install_dir: Modlist installation directory

        Returns:
            bool: True if should offer TTW integration
        """
        try:
            # Check 1: Must be Fallout New Vegas
            if game_type.lower() not in ['falloutnv', 'fallout new vegas', 'fallout_new_vegas']:
                return False

            # Check 2: Must be on whitelist
            from jackify.backend.data.ttw_compatible_modlists import is_ttw_compatible
            if not is_ttw_compatible(modlist_name):
                return False

            # Check 3: TTW must not already be installed
            if self._detect_existing_ttw(install_dir):
                debug_print("DEBUG: TTW already installed, skipping prompt")
                return False

            return True

        except Exception as e:
            debug_print(f"DEBUG: Error checking TTW eligibility: {e}")
            return False

    def _detect_existing_ttw(self, install_dir: str) -> bool:
        """Check if TTW is already installed in the modlist

        Args:
            install_dir: Modlist installation directory

        Returns:
            bool: True if TTW is already present
        """
        try:
            from pathlib import Path

            mods_dir = Path(install_dir) / "mods"
            if not mods_dir.exists():
                return False

            # Check for folders containing "Tale of Two Wastelands" that have actual TTW content
            # Exclude separators and placeholder folders
            for folder in mods_dir.iterdir():
                if not folder.is_dir():
                    continue

                folder_name_lower = folder.name.lower()

                # Skip separator folders and placeholders
                if "_separator" in folder_name_lower or "put" in folder_name_lower or "here" in folder_name_lower:
                    continue

                # Check if folder name contains TTW indicator
                if "tale of two wastelands" in folder_name_lower:
                    # Verify it has actual TTW content by checking for the main ESM
                    ttw_esm = folder / "TaleOfTwoWastelands.esm"
                    if ttw_esm.exists():
                        debug_print(f"DEBUG: Found existing TTW installation: {folder.name}")
                        return True
                    else:
                        debug_print(f"DEBUG: Found TTW folder but no ESM, skipping: {folder.name}")

            return False

        except Exception as e:
            debug_print(f"DEBUG: Error detecting existing TTW: {e}")
            return False  # Assume not installed on error

    def _initiate_ttw_workflow(self, modlist_name: str, install_dir: str):
        """Navigate to TTW screen and set it up for modlist integration

        Args:
            modlist_name: Name of the modlist that needs TTW integration
            install_dir: Path to the modlist installation directory
        """
        try:
            # Store modlist context for later use when TTW completes
            self._ttw_modlist_name = modlist_name
            self._ttw_install_dir = install_dir

            # Get reference to TTW screen BEFORE navigation
            if self.stacked_widget:
                ttw_screen = self.stacked_widget.widget(5)

                # Set integration mode BEFORE navigating to avoid showEvent race condition
                if hasattr(ttw_screen, 'set_modlist_integration_mode'):
                    ttw_screen.set_modlist_integration_mode(modlist_name, install_dir)

                    # Connect to completion signal to show success dialog after TTW
                    if hasattr(ttw_screen, 'integration_complete'):
                        ttw_screen.integration_complete.connect(self._on_ttw_integration_complete)
                else:
                    debug_print("WARNING: TTW screen does not support modlist integration mode yet")

                # Navigate to TTW screen AFTER setting integration mode
                self.stacked_widget.setCurrentIndex(5)

                # Force collapsed state shortly after navigation to avoid any
                # showEvent/layout timing races that may leave it expanded
                try:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(50, lambda: getattr(ttw_screen, 'force_collapsed_state', lambda: None)())
                except Exception:
                    pass

        except Exception as e:
            debug_print(f"ERROR: Failed to initiate TTW workflow: {e}")
            MessageService.critical(
                self,
                "TTW Navigation Failed",
                f"Failed to navigate to TTW installation screen: {str(e)}"
            )

    def _on_ttw_integration_complete(self, success: bool, ttw_version: str = ""):
        """Handle completion of TTW integration and show final success dialog

        Args:
            success: Whether TTW integration completed successfully
            ttw_version: Version of TTW that was installed
        """
        try:
            if not success:
                MessageService.critical(
                    self,
                    "TTW Integration Failed",
                    "Tale of Two Wastelands integration did not complete successfully."
                )
                return

            # Navigate back to this screen to show success dialog
            if self.stacked_widget:
                self.stacked_widget.setCurrentIndex(4)

            # Calculate elapsed time from workflow start
            import time
            if hasattr(self, '_install_workflow_start_time'):
                time_taken = int(time.time() - self._install_workflow_start_time)
                mins, secs = divmod(time_taken, 60)
                time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"
            else:
                time_str = "unknown"

            # Build success message including TTW installation
            modlist_name = getattr(self, '_ttw_modlist_name', 'Unknown')
            game_name = "Fallout New Vegas"

            # Clear Activity window before showing success dialog
            self.file_progress_list.clear()

            # Show enhanced success dialog
            success_dialog = SuccessDialog(
                modlist_name=modlist_name,
                workflow_type="install",
                time_taken=time_str,
                game_name=game_name,
                parent=self
            )

            # Add TTW installation info to dialog if possible
            if hasattr(success_dialog, 'add_info_line'):
                success_dialog.add_info_line(f"TTW {ttw_version} integrated successfully")

            success_dialog.show()

        except Exception as e:
            debug_print(f"ERROR: Failed to show final success dialog: {e}")
            MessageService.critical(
                self,
                "Display Error",
                f"TTW integration completed but failed to show success dialog: {str(e)}"
            )



    def validate_and_start_install(self):
        import time
        self._install_workflow_start_time = time.time()
        debug_print('DEBUG: validate_and_start_install called')

        # Immediately show "Initialising" status to provide feedback
        self.progress_indicator.set_status("Initialising...", 0)
        QApplication.processEvents()  # Force UI update

        # Reload config to pick up any settings changes made in Settings dialog
        self.config_handler.reload_config()

        # Check protontricks before proceeding
        if not self._check_protontricks():
            self.progress_indicator.reset()
            return

        # Disable all controls during installation (except Cancel)
        self._disable_controls_during_operation()
        
        try:
            tab_index = self.source_tabs.currentIndex()
            install_mode = 'online'
            if tab_index == 1:  # .wabbajack File tab
                modlist = self.file_edit.text().strip()
                if not modlist or not os.path.isfile(modlist) or not modlist.endswith('.wabbajack'):
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Please select a valid .wabbajack file."
                    )
                    return
                install_mode = 'file'
            else:
                # For online modlists, ALWAYS use machine_url from selected_modlist_info
                # Button text is now the display name (title), NOT the machine URL
                if not hasattr(self, 'selected_modlist_info') or not self.selected_modlist_info:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
                
                machine_url = self.selected_modlist_info.get('machine_url')
                if not machine_url:
                    self._abort_with_message(
                        "warning",
                        "Invalid Modlist",
                        "Modlist information is incomplete. Please select the modlist again from the gallery."
                    )
                    return
                
                # CRITICAL: Use machine_url, NOT button text
                modlist = machine_url
            install_dir = self.install_dir_edit.text().strip()
            downloads_dir = self.downloads_dir_edit.text().strip()

            # Get authentication token (OAuth or API key) with automatic refresh
            api_key, oauth_info = self.auth_service.get_auth_for_engine()
            if not api_key:
                self._abort_with_message(
                    "warning",
                    "Authorisation Required",
                    "Please authorise with Nexus Mods before installing modlists.\n\n"
                    "Click the 'Authorise' button above to log in with OAuth,\n"
                    "or configure an API key in Settings.",
                    safety_level="medium"
                )
                return

            # Log authentication status at install start (Issue #111 diagnostics)
            import logging
            logger = logging.getLogger(__name__)
            auth_method = self.auth_service.get_auth_method()
            logger.info("=" * 60)
            logger.info("Authentication Status at Install Start")
            logger.info(f"Method: {auth_method or 'UNKNOWN'}")
            logger.info(f"Token length: {len(api_key)} chars")
            if len(api_key) >= 8:
                logger.info(f"Token (partial): {api_key[:4]}...{api_key[-4:]}")

            if auth_method == 'oauth':
                token_handler = self.auth_service.token_handler
                token_info = token_handler.get_token_info()
                if 'expires_in_minutes' in token_info:
                    logger.info(f"OAuth expires in: {token_info['expires_in_minutes']:.1f} minutes")
                if token_info.get('refresh_token_likely_expired'):
                    logger.warning(f"OAuth refresh token age: {token_info['refresh_token_age_days']:.1f} days (may need re-auth)")
            logger.info("=" * 60)

            modlist_name = self.modlist_name_edit.text().strip()
            missing_fields = []
            if not modlist_name:
                missing_fields.append("Modlist Name")
            if not install_dir:
                missing_fields.append("Install Directory")
            if not downloads_dir:
                missing_fields.append("Downloads Directory")
            if missing_fields:
                self._abort_with_message(
                    "warning",
                    "Missing Required Fields",
                    "Please fill in all required fields before starting the install:\n- " + "\n- ".join(missing_fields)
                )
                return
            validation_handler = ValidationHandler()
            from pathlib import Path
            is_safe, reason = validation_handler.is_safe_install_directory(Path(install_dir))
            if not is_safe:
                dlg = WarningDialog(reason, parent=self)
                result = dlg.exec()
                if not result or not dlg.confirmed:
                    self._abort_install_validation()
                    return
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
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
                    return
            if not os.path.isdir(downloads_dir):
                create = MessageService.question(self, "Create Directory?",
                    f"The downloads directory does not exist:\n{downloads_dir}\n\nWould you like to create it?",
                    critical=False  # Non-critical, won't steal focus
                )
                if create == QMessageBox.Yes:
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                    except Exception as e:
                        MessageService.critical(self, "Error", f"Failed to create downloads directory:\n{e}")
                        self._abort_install_validation()
                        return
                else:
                    self._abort_install_validation()
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
            
            # Handle parent directory saving
            self._save_parent_directories(install_dir, downloads_dir)
            
            # Detect game type and check support
            game_type = None
            game_name = None
            
            if install_mode == 'file':
                # Parse .wabbajack file to get game type
                from pathlib import Path
                wabbajack_path = Path(modlist)
                result = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_path)
                if result:
                    if isinstance(result, tuple):
                        game_type, raw_game_type = result
                        # Get display name for the game
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        if game_type == 'unknown' and raw_game_type:
                            game_name = raw_game_type
                        else:
                            game_name = display_names.get(game_type, game_type)
                    else:
                        game_type = result
                        display_names = {
                            'skyrim': 'Skyrim',
                            'fallout4': 'Fallout 4',
                            'falloutnv': 'Fallout New Vegas',
                            'oblivion': 'Oblivion',
                            'starfield': 'Starfield',
                            'oblivion_remastered': 'Oblivion Remastered',
                            'enderal': 'Enderal'
                        }
                        game_name = display_names.get(game_type, game_type)
            else:
                # For online modlists, try to get game type from selected modlist
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    game_name = self.selected_modlist_info.get('game', '')
                    debug_print(f"DEBUG: Detected game_name from selected_modlist_info: '{game_name}'")
                    
                    # Map game name to game type
                    game_mapping = {
                        'skyrim special edition': 'skyrim',
                        'skyrim': 'skyrim',
                        'fallout 4': 'fallout4',
                        'fallout new vegas': 'falloutnv',
                        'oblivion': 'oblivion',
                        'starfield': 'starfield',
                        'oblivion_remastered': 'oblivion_remastered',
                        'enderal': 'enderal',
                        'enderal special edition': 'enderal'
                    }
                    game_type = game_mapping.get(game_name.lower())
                    debug_print(f"DEBUG: Mapped game_name '{game_name}' to game_type: '{game_type}'")
                    if not game_type:
                        game_type = 'unknown'
                        debug_print(f"DEBUG: Game type not found in mapping, setting to 'unknown'")
                else:
                    debug_print(f"DEBUG: No selected_modlist_info found")
                    game_type = 'unknown'
            
            # Store game type and name for later use
            self._current_game_type = game_type
            self._current_game_name = game_name
            
            # Check if game is supported
            debug_print(f"DEBUG: Checking if game_type '{game_type}' is supported")
            debug_print(f"DEBUG: game_type='{game_type}', game_name='{game_name}'")
            is_supported = self.wabbajack_parser.is_supported_game(game_type) if game_type else False
            debug_print(f"DEBUG: is_supported_game('{game_type}') returned: {is_supported}")
            
            if game_type and not is_supported:
                debug_print(f"DEBUG: Game '{game_type}' is not supported, showing dialog")
                # Show unsupported game dialog
                dialog = UnsupportedGameDialog(self, game_name)
                if not dialog.show_dialog(self, game_name):
                    self._abort_install_validation()
                    return
            
            self.console.clear()
            self.process_monitor.clear()
            
            # R&D: Reset progress indicator for new installation
            self.progress_indicator.reset()
            self.progress_state_manager.reset()
            self.file_progress_list.clear()
            self.file_progress_list.start_cpu_tracking()  # Start tracking CPU during installation
            self._premium_notice_shown = False
            self._stalled_download_start_time = None  # Reset stall detection
            self._stalled_download_notified = False
            self._token_error_notified = False  # Reset token error notification
            self._premium_failure_active = False
            self._post_install_active = False
            self._post_install_current_step = 0
            # Activity tab is always visible (tabs handle visibility automatically)
            
            # Update button states for installation
            self.start_btn.setEnabled(False)
            self.cancel_btn.setVisible(False)
            self.cancel_install_btn.setVisible(True)
            
            # CRITICAL: Final safety check - ensure online modlists use machine_url
            if install_mode == 'online':
                if hasattr(self, 'selected_modlist_info') and self.selected_modlist_info:
                    expected_machine_url = self.selected_modlist_info.get('machine_url')
                    if expected_machine_url:
                        modlist = expected_machine_url  # Force use machine_url
                    else:
                        self._abort_with_message(
                            "critical",
                            "Installation Error",
                            "Cannot determine modlist machine URL. Please select the modlist again."
                        )
                        return
                else:
                    self._abort_with_message(
                        "critical",
                        "Installation Error",
                        "Modlist information is missing. Please select the modlist again from the gallery."
                    )
                    return
            
            debug_print(f'DEBUG: Calling run_modlist_installer with modlist={modlist}, install_dir={install_dir}, downloads_dir={downloads_dir}, install_mode={install_mode}')
            self.run_modlist_installer(modlist, install_dir, downloads_dir, api_key, install_mode, oauth_info)
        except Exception as e:
            debug_print(f"DEBUG: Exception in validate_and_start_install: {e}")
            import traceback
            debug_print(f"DEBUG: Traceback: {traceback.format_exc()}")
            # Re-enable all controls after exception
            self._enable_controls_after_operation()
            self.cancel_btn.setVisible(True)
            self.cancel_install_btn.setVisible(False)
            debug_print(f"DEBUG: Controls re-enabled in exception handler")

    def run_modlist_installer(self, modlist, install_dir, downloads_dir, api_key, install_mode='online', oauth_info=None):
        debug_print('DEBUG: run_modlist_installer called - USING THREADED BACKEND WRAPPER')
        
        # Rotate log file at start of each workflow run (keep 5 backups)
        from jackify.backend.handlers.logging_handler import LoggingHandler
        from pathlib import Path
        log_handler = LoggingHandler()
        log_handler.rotate_log_file_per_run(Path(self.modlist_log_path), backup_count=5)
        
        # Clear console for fresh installation output
        self.console.clear()
        from jackify import __version__ as jackify_version
        self._safe_append_text(f"Jackify v{jackify_version}")
        self._safe_append_text("Starting modlist installation with custom progress handling...")
        
        # Update UI state for installation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)
        
        # Create installation thread
        from PySide6.QtCore import QThread, Signal
        
        class InstallationThread(QThread):
            output_received = Signal(str)
            progress_received = Signal(str)
            progress_updated = Signal(object)  # R&D: Emits InstallationProgress object
            installation_finished = Signal(bool, str)
            premium_required_detected = Signal(str)
            
            def __init__(self, modlist, install_dir, downloads_dir, api_key, modlist_name, install_mode='online', progress_state_manager=None, auth_service=None, oauth_info=None):
                super().__init__()
                self.modlist = modlist
                self.install_dir = install_dir
                self.downloads_dir = downloads_dir
                self.api_key = api_key
                self.modlist_name = modlist_name
                self.install_mode = install_mode
                self.cancelled = False
                self.process_manager = None
                # R&D: Progress state manager for parsing
                self.progress_state_manager = progress_state_manager
                self.auth_service = auth_service
                self.oauth_info = oauth_info
                self._premium_signal_sent = False
                # Rolling buffer for Premium detection diagnostics
                self._engine_output_buffer = []
                self._buffer_size = 10
            
            def cancel(self):
                self.cancelled = True
                if self.process_manager:
                    self.process_manager.cancel()
            
            def run(self):
                try:
                    engine_path = get_jackify_engine_path()
                    
                    # Verify engine exists and is executable
                    if not os.path.exists(engine_path):
                        error_msg = f"Engine not found at: {engine_path}"
                        debug_print(f"DEBUG: {error_msg}")
                        self.installation_finished.emit(False, error_msg)
                        return
                    
                    if not os.access(engine_path, os.X_OK):
                        error_msg = f"Engine is not executable: {engine_path}"
                        debug_print(f"DEBUG: {error_msg}")
                        self.installation_finished.emit(False, error_msg)
                        return
                    
                    debug_print(f"DEBUG: Using engine at: {engine_path}")
                    
                    if self.install_mode == 'file':
                        cmd = [engine_path, "install", "--show-file-progress", "-w", self.modlist, "-o", self.install_dir, "-d", self.downloads_dir]
                    else:
                        cmd = [engine_path, "install", "--show-file-progress", "-m", self.modlist, "-o", self.install_dir, "-d", self.downloads_dir]
                    
                    # Check for debug mode and add --debug flag
                    from jackify.backend.handlers.config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    debug_mode = config_handler.get('debug_mode', False)
                    if debug_mode:
                        cmd.append('--debug')
                        debug_print("DEBUG: Added --debug flag to jackify-engine command")

                    # CRITICAL: Print the FULL command so we can see exactly what's being passed
                    debug_print(f"DEBUG: FULL Engine command: {' '.join(cmd)}")
                    debug_print(f"DEBUG: modlist value being passed: '{self.modlist}'")

                    # Use clean subprocess environment to prevent AppImage variable inheritance
                    from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                    env_vars = {'NEXUS_API_KEY': self.api_key}
                    if self.oauth_info:
                        env_vars['NEXUS_OAUTH_INFO'] = self.oauth_info
                        # CRITICAL: Set client_id so engine can refresh tokens with correct client_id
                        # Engine's RefreshToken method reads this to use our "jackify" client_id instead of hardcoded "wabbajack"
                        from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                        env_vars['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                    env = get_clean_subprocess_env(env_vars)
                    self.process_manager = ProcessManager(cmd, env=env, text=False)
                    ansi_escape = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
                    buffer = b''
                    last_was_blank = False
                    while True:
                        if self.cancelled:
                            self.cancel()
                            break
                        char = self.process_manager.read_stdout_char()
                        if not char:
                            break
                        buffer += char
                        while b'\n' in buffer or b'\r' in buffer:
                            if b'\r' in buffer and (buffer.index(b'\r') < buffer.index(b'\n') if b'\n' in buffer else True):
                                line, buffer = buffer.split(b'\r', 1)
                                line = ansi_escape.sub(b'', line)
                                decoded = line.decode('utf-8', errors='replace')

                                # Notify when Nexus requires Premium before continuing
                                from jackify.backend.handlers.config_handler import ConfigHandler
                                config_handler = ConfigHandler()
                                debug_mode = config_handler.get('debug_mode', False)

                                # Check for Premium detection
                                is_premium_error, matched_pattern = is_non_premium_indicator(decoded)
                                if not self._premium_signal_sent and is_premium_error:
                                    self._premium_signal_sent = True

                                    # DIAGNOSTIC LOGGING: Capture false positive details
                                    import logging
                                    logger = logging.getLogger(__name__)
                                    logger.warning("=" * 80)
                                    logger.warning("PREMIUM DETECTION TRIGGERED - DIAGNOSTIC DUMP (Issue #111)")
                                    logger.warning("=" * 80)
                                    logger.warning(f"Matched pattern: '{matched_pattern}'")
                                    logger.warning(f"Triggering line: '{decoded.strip()}'")

                                    # Detailed auth diagnostics
                                    logger.warning("")
                                    logger.warning("AUTHENTICATION DIAGNOSTICS:")
                                    logger.warning(f"  Auth value present: {'YES' if self.api_key else 'NO'}")
                                    if self.api_key:
                                        logger.warning(f"  Auth value length: {len(self.api_key)} chars")
                                        if len(self.api_key) >= 8:
                                            logger.warning(f"  Auth value (partial): {self.api_key[:4]}...{self.api_key[-4:]}")

                                        # Determine auth method and get detailed status
                                        auth_method = self.auth_service.get_auth_method()
                                        logger.warning(f"  Auth method: {auth_method or 'UNKNOWN'}")

                                        if auth_method == 'oauth':
                                            # Get detailed OAuth token status
                                            token_handler = self.auth_service.token_handler
                                            token_info = token_handler.get_token_info()

                                            logger.warning("  OAuth Token Status:")
                                            logger.warning(f"    Has token file: {token_info.get('has_token', False)}")
                                            logger.warning(f"    Has refresh token: {token_info.get('has_refresh_token', False)}")

                                            if 'expires_in_minutes' in token_info:
                                                logger.warning(f"    Expires in: {token_info['expires_in_minutes']:.1f} minutes")
                                                logger.warning(f"    Is expired: {token_info.get('is_expired', False)}")
                                                logger.warning(f"    Expires soon (5min): {token_info.get('expires_soon_5min', False)}")

                                            if 'refresh_token_age_days' in token_info:
                                                logger.warning(f"    Refresh token age: {token_info['refresh_token_age_days']:.1f} days")
                                                logger.warning(f"    Refresh token likely expired: {token_info.get('refresh_token_likely_expired', False)}")

                                            if token_info.get('error'):
                                                logger.warning(f"    Error: {token_info['error']}")

                                    logger.warning("")
                                    logger.warning("Previous engine output (last 10 lines):")
                                    for i, buffered_line in enumerate(self._engine_output_buffer, 1):
                                        logger.warning(f"  -{len(self._engine_output_buffer) - i + 1}: {buffered_line}")
                                    logger.warning("")
                                    logger.warning("If user HAS Premium, this is a FALSE POSITIVE")
                                    logger.warning("Report to: https://github.com/Omni-guides/Jackify/issues/111")
                                    logger.warning("=" * 80)

                                    self.premium_required_detected.emit(decoded.strip() or "Nexus Premium required")

                                # Maintain rolling buffer of engine output for diagnostics
                                self._engine_output_buffer.append(decoded.strip())
                                if len(self._engine_output_buffer) > self._buffer_size:
                                    self._engine_output_buffer.pop(0)

                                # R&D: Process through progress parser
                                if self.progress_state_manager:
                                    updated = self.progress_state_manager.process_line(decoded)
                                    if updated:
                                        progress_state = self.progress_state_manager.get_state()
                                        # Debug: Log when we detect file progress
                                        if progress_state.active_files and debug_mode:
                                            debug_print(f"DEBUG: Parser detected {len(progress_state.active_files)} active files from line: {decoded[:80]}")
                                        self.progress_updated.emit(progress_state)
                                # Filter FILE_PROGRESS spam but keep the status line before it
                                if '[FILE_PROGRESS]' in decoded:
                                    parts = decoded.split('[FILE_PROGRESS]', 1)
                                    if parts[0].strip():
                                        self.progress_received.emit(parts[0].rstrip())
                                else:
                                    # Preserve \r line ending for progress updates
                                    self.progress_received.emit(decoded + '\r')
                            elif b'\n' in buffer:
                                line, buffer = buffer.split(b'\n', 1)
                                line = ansi_escape.sub(b'', line)
                                decoded = line.decode('utf-8', errors='replace')

                                # Notify when Nexus requires Premium before continuing
                                is_premium_error, matched_pattern = is_non_premium_indicator(decoded)
                                if not self._premium_signal_sent and is_premium_error:
                                    self._premium_signal_sent = True

                                    # DIAGNOSTIC LOGGING: Capture false positive details
                                    import logging
                                    logger = logging.getLogger(__name__)
                                    logger.warning("=" * 80)
                                    logger.warning("PREMIUM DETECTION TRIGGERED - DIAGNOSTIC DUMP (Issue #111)")
                                    logger.warning("=" * 80)
                                    logger.warning(f"Matched pattern: '{matched_pattern}'")
                                    logger.warning(f"Triggering line: '{decoded.strip()}'")

                                    # Detailed auth diagnostics
                                    logger.warning("")
                                    logger.warning("AUTHENTICATION DIAGNOSTICS:")
                                    logger.warning(f"  Auth value present: {'YES' if self.api_key else 'NO'}")
                                    if self.api_key:
                                        logger.warning(f"  Auth value length: {len(self.api_key)} chars")
                                        if len(self.api_key) >= 8:
                                            logger.warning(f"  Auth value (partial): {self.api_key[:4]}...{self.api_key[-4:]}")

                                        # Determine auth method and get detailed status
                                        auth_method = self.auth_service.get_auth_method()
                                        logger.warning(f"  Auth method: {auth_method or 'UNKNOWN'}")

                                        if auth_method == 'oauth':
                                            # Get detailed OAuth token status
                                            token_handler = self.auth_service.token_handler
                                            token_info = token_handler.get_token_info()

                                            logger.warning("  OAuth Token Status:")
                                            logger.warning(f"    Has token file: {token_info.get('has_token', False)}")
                                            logger.warning(f"    Has refresh token: {token_info.get('has_refresh_token', False)}")

                                            if 'expires_in_minutes' in token_info:
                                                logger.warning(f"    Expires in: {token_info['expires_in_minutes']:.1f} minutes")
                                                logger.warning(f"    Is expired: {token_info.get('is_expired', False)}")
                                                logger.warning(f"    Expires soon (5min): {token_info.get('expires_soon_5min', False)}")

                                            if 'refresh_token_age_days' in token_info:
                                                logger.warning(f"    Refresh token age: {token_info['refresh_token_age_days']:.1f} days")
                                                logger.warning(f"    Refresh token likely expired: {token_info.get('refresh_token_likely_expired', False)}")

                                            if token_info.get('error'):
                                                logger.warning(f"    Error: {token_info['error']}")

                                    logger.warning("")
                                    logger.warning("Previous engine output (last 10 lines):")
                                    for i, buffered_line in enumerate(self._engine_output_buffer, 1):
                                        logger.warning(f"  -{len(self._engine_output_buffer) - i + 1}: {buffered_line}")
                                    logger.warning("")
                                    logger.warning("If user HAS Premium, this is a FALSE POSITIVE")
                                    logger.warning("Report to: https://github.com/Omni-guides/Jackify/issues/111")
                                    logger.warning("=" * 80)

                                    self.premium_required_detected.emit(decoded.strip() or "Nexus Premium required")

                                # Maintain rolling buffer of engine output for diagnostics
                                self._engine_output_buffer.append(decoded.strip())
                                if len(self._engine_output_buffer) > self._buffer_size:
                                    self._engine_output_buffer.pop(0)

                                # R&D: Process through progress parser
                                from jackify.backend.handlers.config_handler import ConfigHandler
                                config_handler = ConfigHandler()
                                debug_mode = config_handler.get('debug_mode', False)
                                if self.progress_state_manager:
                                    updated = self.progress_state_manager.process_line(decoded)
                                    if updated:
                                        progress_state = self.progress_state_manager.get_state()
                                        # Debug: Log when we detect file progress
                                        if progress_state.active_files and debug_mode:
                                            debug_print(f"DEBUG: Parser detected {len(progress_state.active_files)} active files from line: {decoded[:80]}")
                                        self.progress_updated.emit(progress_state)
                                # Filter FILE_PROGRESS spam but keep the status line before it
                                if '[FILE_PROGRESS]' in decoded:
                                    parts = decoded.split('[FILE_PROGRESS]', 1)
                                    if parts[0].strip():
                                        self.output_received.emit(parts[0].rstrip())
                                    last_was_blank = False
                                    continue

                                # Collapse multiple blank lines to one
                                if decoded.strip() == '':
                                    if not last_was_blank:
                                        self.output_received.emit('\n')
                                    last_was_blank = True
                                else:
                                    # Preserve \n line ending for normal output
                                    self.output_received.emit(decoded + '\n')
                                    last_was_blank = False
                    if buffer:
                        line = ansi_escape.sub(b'', buffer)
                        decoded = line.decode('utf-8', errors='replace')
                        # Filter FILE_PROGRESS from final buffer flush too
                        if '[FILE_PROGRESS]' in decoded:
                            parts = decoded.split('[FILE_PROGRESS]', 1)
                            if parts[0].strip():
                                self.output_received.emit(parts[0].rstrip())
                        else:
                            self.output_received.emit(decoded)
                    
                    # Wait for process to complete
                    returncode = self.process_manager.wait()
                    
                    # Capture any remaining output after process ends
                    if self.process_manager.proc and self.process_manager.proc.stdout:
                        try:
                            remaining = self.process_manager.proc.stdout.read()
                            if remaining:
                                decoded_remaining = remaining.decode('utf-8', errors='replace')
                                if decoded_remaining.strip():
                                    debug_print(f"DEBUG: Remaining output after process exit: {decoded_remaining[:500]}")
                                    # Filter FILE_PROGRESS from remaining output too
                                    if '[FILE_PROGRESS]' in decoded_remaining:
                                        parts = decoded_remaining.split('[FILE_PROGRESS]', 1)
                                        if parts[0].strip():
                                            self.output_received.emit(parts[0].rstrip())
                                    else:
                                        self.output_received.emit(decoded_remaining)
                        except Exception as e:
                            debug_print(f"DEBUG: Error reading remaining output: {e}")
                    
                    if self.cancelled:
                        self.installation_finished.emit(False, "Installation cancelled by user")
                    elif returncode == 0:
                        self.installation_finished.emit(True, "Installation completed successfully")
                    else:
                        error_msg = f"Installation failed (exit code {returncode})"
                        debug_print(f"DEBUG: Engine exited with code {returncode}")
                        # Try to get more details from the process
                        if self.process_manager.proc:
                            debug_print(f"DEBUG: Process stderr/stdout may contain error details")
                        self.installation_finished.emit(False, error_msg)
                except Exception as e:
                    self.installation_finished.emit(False, f"Installation error: {str(e)}")
                finally:
                    if self.cancelled and self.process_manager:
                        self.process_manager.cancel()

        # After the InstallationThread class definition, add:
        self.install_thread = InstallationThread(
            modlist, install_dir, downloads_dir, api_key, self.modlist_name_edit.text().strip(), install_mode,
            progress_state_manager=self.progress_state_manager,  # R&D: Pass progress state manager
            auth_service=self.auth_service,  # Fix Issue #127: Pass auth_service for Premium detection diagnostics
            oauth_info=oauth_info  # Pass OAuth state for auto-refresh
        )
        self.install_thread.output_received.connect(self.on_installation_output)
        self.install_thread.progress_received.connect(self.on_installation_progress)
        self.install_thread.progress_updated.connect(self.on_progress_updated)  # R&D: Connect progress update
        self.install_thread.installation_finished.connect(self.on_installation_finished)
        self.install_thread.premium_required_detected.connect(self.on_premium_required_detected)
        # R&D: Pass progress state manager to thread
        self.install_thread.progress_state_manager = self.progress_state_manager
        self.install_thread.start()

    def on_installation_output(self, message):
        """Handle regular output from installation thread"""
        # Filter out internal status messages from user console
        if message.strip().startswith('[Jackify]'):
            # Log internal messages to file but don't show in console
            self._write_to_log_file(message)
            return
        
        # CRITICAL: Detect token/auth errors and ALWAYS show them (even when not in debug mode)
        msg_lower = message.lower()
        token_error_keywords = [
            'token has expired',
            'token expired',
            'oauth token',
            'authentication failed',
            'unauthorized',
            '401',
            '403',
            'refresh token',
            'authorization failed',
            'nexus.*premium.*required',
            'premium.*required',
        ]
        
        is_token_error = any(keyword in msg_lower for keyword in token_error_keywords)
        if is_token_error:
            # CRITICAL ERROR - always show, even if console is hidden
            if not hasattr(self, '_token_error_notified'):
                self._token_error_notified = True
                # Show error dialog immediately
                from jackify.frontends.gui.services.message_service import MessageService
                MessageService.error(
                    self,
                    "Authentication Error",
                    (
                        "Nexus Mods authentication has failed. This may be due to:\n\n"
                        "• OAuth token expired and refresh failed\n"
                        "• Nexus Premium required for this modlist\n"
                        "• Network connectivity issues\n\n"
                        "Please check the console output (Show Details) for more information.\n"
                        "You may need to re-authorize in Settings."
                    ),
                    safety_level="high"
                )
                # Also show in console
                guidance = (
                    "\n[Jackify] ⚠️ CRITICAL: Authentication/Token Error Detected!\n"
                    "[Jackify] This may cause downloads to stop. Check the error message above.\n"
                    "[Jackify] If OAuth token expired, go to Settings and re-authorize.\n"
                )
                self._safe_append_text(guidance)
                # Force console to be visible so user can see the error
                if not self.show_details_checkbox.isChecked():
                    self.show_details_checkbox.setChecked(True)
        
        # Detect known engine bugs and provide helpful guidance
        if 'destination array was not long enough' in msg_lower or \
           ('argumentexception' in msg_lower and 'downloadmachineurl' in msg_lower):
            # This is a known bug in jackify-engine 0.4.0 during .wabbajack download
            if not hasattr(self, '_array_error_notified'):
                self._array_error_notified = True
                guidance = (
                    "\n[Jackify] Engine Error Detected: Buffer size issue during .wabbajack download.\n"
                    "[Jackify] This is a known bug in jackify-engine 0.4.0.\n"
                    "[Jackify] Workaround: Delete any partial .wabbajack files in your downloads directory and try again.\n"
                )
                self._safe_append_text(guidance)
        
        # R&D: Always write output to console buffer so it's available when user toggles Show Details
        # The console visibility is controlled by the checkbox, not whether we write to it
        self._safe_append_text(message)
    
    def on_installation_progress(self, progress_message):
        """
        Handle progress messages from installation thread.

        NOTE: This is called for MOST engine output, not just progress lines!
        The name is misleading - it's actually the main output path.
        """
        # Always write output to console buffer (same as on_installation_output)
        self._safe_append_text(progress_message)

    def on_premium_required_detected(self, engine_line: str):
        """Handle detection of Nexus Premium requirement."""
        if self._premium_notice_shown:
            return

        self._premium_notice_shown = True
        self._premium_failure_active = True

        user_message = (
            "Nexus Mods rejected the automated download because this account is not Premium. "
            "Jackify currently requires a Nexus Premium membership for automated installs, "
            "and non-premium support is still planned."
        )

        if engine_line:
            self._safe_append_text(f"[Jackify] Engine message: {engine_line}")
        self._safe_append_text("[Jackify] Jackify detected that Nexus Premium is required for this modlist install.")

        MessageService.critical(
            self,
            "Nexus Premium Required",
            f"{user_message}\n\nDetected engine output:\n{engine_line or 'Buy Nexus Premium to automate this process.'}",
            safety_level="medium"
        )

        if hasattr(self, 'install_thread') and self.install_thread:
            self.install_thread.cancel()
    
    def on_progress_updated(self, progress_state):
        """R&D: Handle structured progress updates from parser"""
        # Calculate proper overall progress during BSA building
        # During BSA building, file installation is at 100% but BSAs are still being built
        # Override overall_percent to show BSA building progress instead
        if progress_state.bsa_building_total > 0 and progress_state.bsa_building_current > 0:
            bsa_percent = (progress_state.bsa_building_current / progress_state.bsa_building_total) * 100.0
            progress_state.overall_percent = min(99.0, bsa_percent)  # Cap at 99% until fully complete

        # CRITICAL: Detect stalled downloads (0.0MB/s for extended period)
        # This catches cases where token refresh fails silently or network issues occur
        # IMPORTANT: Only check during DOWNLOAD phase, not during VALIDATE phase
        # Validation checks existing files and shows 0.0MB/s, which is expected behavior
        import time
        if progress_state.phase == InstallationPhase.DOWNLOAD:
            speed_display = progress_state.get_overall_speed_display()
            # Check if speed is 0 or very low (< 0.1MB/s) for more than 2 minutes
            # Only trigger if we're actually in download phase (not validation)
            is_stalled = not speed_display or speed_display == "0.0B/s" or \
                        (speed_display and any(x in speed_display.lower() for x in ['0.0mb/s', '0.0kb/s', '0b/s']))
            
            # Additional check: Only consider it stalled if we have active download files
            # If no files are being downloaded, it might just be between downloads
            has_active_downloads = any(
                f.operation == OperationType.DOWNLOAD and not f.is_complete 
                for f in progress_state.active_files
            )
            
            if is_stalled and has_active_downloads:
                if self._stalled_download_start_time is None:
                    self._stalled_download_start_time = time.time()
                else:
                    stalled_duration = time.time() - self._stalled_download_start_time
                    # Warn after 2 minutes of stalled downloads
                    if stalled_duration > 120 and not self._stalled_download_notified:
                        self._stalled_download_notified = True
                        from jackify.frontends.gui.services.message_service import MessageService
                        MessageService.warning(
                            self,
                            "Download Stalled",
                            (
                                "Downloads have been stalled (0.0MB/s) for over 2 minutes.\n\n"
                                "Possible causes:\n"
                                "• OAuth token expired and refresh failed\n"
                                "• Network connectivity issues\n"
                                "• Nexus Mods server issues\n\n"
                                "Please check the console output (Show Details) for error messages.\n"
                                "If authentication failed, you may need to re-authorize in Settings."
                            ),
                            safety_level="low"
                        )
                        # Force console to be visible
                        if not self.show_details_checkbox.isChecked():
                            self.show_details_checkbox.setChecked(True)
                        # Add warning to console
                        self._safe_append_text(
                            "\n[Jackify] ⚠️ WARNING: Downloads have stalled (0.0MB/s for 2+ minutes)\n"
                            "[Jackify] This may indicate an authentication or network issue.\n"
                            "[Jackify] Check the console above for error messages.\n"
                        )
            else:
                # Downloads are active - reset stall timer
                self._stalled_download_start_time = None
                self._stalled_download_notified = False

        # Update progress indicator widget
        self.progress_indicator.update_progress(progress_state)
        
        # Only show file progress list if console is not visible (mutually exclusive)
        console_visible = self.show_details_checkbox.isChecked()
        
        # Determine phase display name up front (short/stable label)
        phase_label = progress_state.get_phase_label()
        
        # During installation or extraction phase, show summary counter instead of individual files
        # This avoids cluttering the UI with hundreds of completed files
        is_installation_phase = (
            progress_state.phase == InstallationPhase.INSTALL or
            (progress_state.phase_name and 'install' in progress_state.phase_name.lower())
        )
        is_extraction_phase = (
            progress_state.phase == InstallationPhase.EXTRACT or
            (progress_state.phase_name and 'extract' in progress_state.phase_name.lower())
        )
        
        # Detect BSA building phase - check multiple indicators
        is_bsa_building = False
        
        # Check phase name for BSA indicators
        if progress_state.phase_name:
            phase_lower = progress_state.phase_name.lower()
            if 'bsa' in phase_lower or ('building' in phase_lower and progress_state.phase == InstallationPhase.INSTALL):
                is_bsa_building = True
        
        # Check message/status text for BSA building indicators
        if not is_bsa_building and progress_state.message:
            msg_lower = progress_state.message.lower()
            if ('building' in msg_lower or 'writing' in msg_lower or 'verifying' in msg_lower) and '.bsa' in msg_lower:
                is_bsa_building = True
        
        # Check if we have BSA files being processed (even if they're at 100%, they indicate BSA phase)
        if not is_bsa_building and progress_state.active_files:
            bsa_files = [f for f in progress_state.active_files if f.filename.lower().endswith('.bsa')]
            if len(bsa_files) > 0:
                # If we have any BSA files and we're in INSTALL phase, likely BSA building
                if progress_state.phase == InstallationPhase.INSTALL:
                    is_bsa_building = True
        
        # Also check display text for BSA mentions (fallback)
        if not is_bsa_building:
            display_lower = progress_state.display_text.lower()
            if 'bsa' in display_lower and progress_state.phase == InstallationPhase.INSTALL:
                is_bsa_building = True
        
        now_mono = time.monotonic()
        if is_bsa_building:
            self._bsa_hold_deadline = now_mono + 1.5
        elif now_mono < self._bsa_hold_deadline:
            is_bsa_building = True
        else:
            self._bsa_hold_deadline = now_mono

        if is_installation_phase:
            # During installation, we may have BSA building AND file installation happening
            # Show both: install summary + any active BSA files
            # Render loop handles smooth updates - just set target state
            
            current_step = progress_state.phase_step
            from jackify.shared.progress_models import FileProgress, OperationType

            display_items = []

            # Line 1: Always show "Installing Files: X/Y" at the top (no progress bar, no size)
            if current_step > 0 or progress_state.phase_max_steps > 0:
                install_line = FileProgress(
                    filename=f"Installing Files: {current_step}/{progress_state.phase_max_steps}",
                    operation=OperationType.INSTALL,
                    percent=0.0,
                    speed=-1.0
                )
                install_line._no_progress_bar = True  # Flag to hide progress bar
                display_items.append(install_line)

            # Lines 2+: Show converting textures and BSA files
            # Extract and categorize active files
            for f in progress_state.active_files:
                if f.operation == OperationType.INSTALL:
                    if f.filename.lower().endswith('.bsa') or f.filename.lower().endswith('.ba2'):
                        # BSA: filename.bsa (42/89) - Use state-level BSA counter
                        if progress_state.bsa_building_total > 0:
                            display_filename = f"BSA: {f.filename} ({progress_state.bsa_building_current}/{progress_state.bsa_building_total})"
                        else:
                            display_filename = f"BSA: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break
                    elif f.filename.lower().endswith(('.dds', '.png', '.tga', '.bmp')):
                        # Converting Texture: filename.dds (234/1078)
                        # Use state-level texture counter (more reliable than file-level)
                        if progress_state.texture_conversion_total > 0:
                            display_filename = f"Converting Texture: {f.filename} ({progress_state.texture_conversion_current}/{progress_state.texture_conversion_total})"
                        else:
                            # No texture counter available, just show filename
                            display_filename = f"Converting Texture: {f.filename}"

                        display_file = FileProgress(
                            filename=display_filename,
                            operation=f.operation,
                            percent=f.percent,
                            current_size=0,  # Don't show size
                            total_size=0,
                            speed=-1.0  # No speed
                        )
                        display_items.append(display_file)
                        if len(display_items) >= 4:  # Max 1 install line + 3 operations
                            break

            # Update target state (render loop handles smooth display)
            # Explicitly pass None for summary_info to clear any stale summary data
            if display_items:
                self.file_progress_list.update_files(display_items, current_phase="Installing", summary_info=None)
            return
        elif is_extraction_phase:
            # Show summary info for Extracting phase (step count)
            # Render loop handles smooth updates - just set target state
            # Explicitly pass empty list for file_progresses to clear any stale file list
            current_step = progress_state.phase_step
            summary_info = {
                'current_step': current_step,
                'max_steps': progress_state.phase_max_steps,
            }
            phase_display_name = phase_label or "Extracting"
            self.file_progress_list.update_files([], current_phase=phase_display_name, summary_info=summary_info)
            return
        elif progress_state.active_files:
            if self.debug:
                debug_print(f"DEBUG: Updating file progress list with {len(progress_state.active_files)} files")
                for fp in progress_state.active_files:
                    debug_print(f"DEBUG:   - {fp.filename}: {fp.percent:.1f}% ({fp.operation.value})")
            # Pass phase label to update header (e.g., "[Activity - Downloading]")
            # Explicitly clear summary_info when showing file list
            try:
                self.file_progress_list.update_files(progress_state.active_files, current_phase=phase_label, summary_info=None)
            except RuntimeError as e:
                # Widget was deleted - ignore to prevent coredump
                if "already deleted" in str(e):
                    if self.debug:
                        debug_print(f"DEBUG: Ignoring widget deletion error: {e}")
                    return
                raise
            except Exception as e:
                # Catch any other exceptions to prevent coredump
                if self.debug:
                    debug_print(f"DEBUG: Error updating file progress list: {e}")
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
        else:
            # Show empty state so widget stays visible even when no files are active
            try:
                self.file_progress_list.update_files([], current_phase=phase_label)
            except RuntimeError as e:
                # Widget was deleted - ignore to prevent coredump
                if "already deleted" in str(e):
                    return
                raise
            except Exception as e:
                # Catch any other exceptions to prevent coredump
                import logging
                logging.getLogger(__name__).error(f"Error updating file progress list: {e}", exc_info=True)
    
    def _on_show_details_toggled(self, checked: bool):
        """R&D: Toggle console visibility (reuse TTW pattern)"""
        from PySide6.QtCore import Qt as _Qt
        self._toggle_console_visibility(_Qt.Checked if checked else _Qt.Unchecked)
    
    def _toggle_console_visibility(self, state):
        """R&D: Toggle console visibility only
        
        When "Show Details" is checked:
            - Show Console (below tabs)
            - Expand window height
        When "Show Details" is unchecked:
            - Hide Console
            - Collapse window height
        
        Note: Activity and Process Monitor tabs are always available via tabs.
        """
        is_checked = (state == Qt.Checked)
        
        # Get main window reference (like TTW screen)
        main_window = None
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                main_window = app.activeWindow()
                # Try to find the actual main window (parent of stacked widget)
                if self.stacked_widget and self.stacked_widget.parent():
                    main_window = self.stacked_widget.parent()
        except Exception:
            pass
        
        # Save geometry on first expand (like TTW screen)
        if is_checked and main_window and self._saved_geometry is None:
            try:
                self._saved_geometry = main_window.geometry()
                self._saved_min_size = main_window.minimumSize()
            except Exception:
                pass
        
        if is_checked:
            # Keep upper section height consistent - don't change it
            # This prevents buttons from being cut off
            try:
                if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                    # Maintain consistent height - ALWAYS use the stored fixed height
                    # Never recalculate - use the exact same height calculated in showEvent
                    if hasattr(self, '_upper_section_fixed_height') and self._upper_section_fixed_height is not None:
                        self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                        self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)  # Lock it
                    # If somehow not stored, it should have been set in showEvent - don't recalculate here
                    self.upper_section_widget.updateGeometry()
            except Exception:
                pass
            # Show console
            self.console.setVisible(True)
            self.console.show()
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)  # Remove height limit
            try:
                self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                # Set stretch on console in its layout to fill space
                console_layout = self.console.parent().layout()
                if console_layout:
                    console_layout.setStretchFactor(console_layout.indexOf(self.console), 1)
                    # Restore spacing when console is visible
                    console_layout.setSpacing(4)
            except Exception:
                pass
            try:
                # Set spacing in console_and_buttons_layout when console is visible
                if hasattr(self, 'console_and_buttons_layout'):
                    self.console_and_buttons_layout.setSpacing(4)  # Small gap between console and buttons
                # Set stretch on console_and_buttons_widget to fill space when expanded
                if hasattr(self, 'console_and_buttons_widget'):
                    self.main_overall_vbox.setStretchFactor(self.console_and_buttons_widget, 1)
                    # Allow expansion when console is visible - remove fixed height constraint
                    self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    # Clear fixed height by setting min/max (setFixedHeight sets both, so we override it)
                    self.console_and_buttons_widget.setMinimumHeight(0)
                    self.console_and_buttons_widget.setMaximumHeight(16777215)
                    self.console_and_buttons_widget.updateGeometry()
            except Exception:
                pass
            
            # Notify parent to expand - let main window handle resizing
            try:
                self.resize_request.emit('expand')
            except Exception:
                pass
        else:
            # Keep upper section height consistent - use same constraint
            # This prevents buttons from being cut off
            try:
                if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                    # Use the same stored fixed height for consistency
                    # ALWAYS use the stored height - never recalculate to avoid drift
                    if hasattr(self, '_upper_section_fixed_height') and self._upper_section_fixed_height is not None:
                        self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                        self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)  # Lock it
                    # If somehow not stored, it should have been set in showEvent - don't recalculate here
                    self.upper_section_widget.updateGeometry()
            except Exception:
                pass
            # Hide console and ensure it takes zero space
            self.console.setVisible(False)
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            # Use Ignored size policy so it doesn't participate in layout calculations
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            try:
                # Remove stretch from console in its layout
                console_layout = self.console.parent().layout()
                if console_layout:
                    console_layout.setStretchFactor(console_layout.indexOf(self.console), 0)
                    # CRITICAL: Set spacing to 0 when console is hidden to eliminate gap
                    console_layout.setSpacing(0)
            except Exception:
                pass
            try:
                # CRITICAL: Set spacing to 0 in console_and_buttons_layout when console is hidden
                if hasattr(self, 'console_and_buttons_layout'):
                    self.console_and_buttons_layout.setSpacing(0)
                # Remove stretch from console container when collapsed
                console_container = self.console.parent()
                if console_container:
                    self.main_overall_vbox.setStretchFactor(console_container, 0)
                # Also remove stretch from console_and_buttons_widget to prevent large gaps
                if hasattr(self, 'console_and_buttons_widget'):
                    self.main_overall_vbox.setStretchFactor(self.console_and_buttons_widget, 0)
                    # Use Minimum size policy - takes only the minimum space needed (just buttons)
                    self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    # Lock height to exactly button row height when collapsed
                    self.console_and_buttons_widget.setFixedHeight(50)  # Match button row height exactly
                    # Update geometry to force recalculation
                    self.console_and_buttons_widget.updateGeometry()
            except Exception:
                pass
            
            # Notify parent to collapse - let main window handle resizing
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass
    
    def on_installation_finished(self, success, message):
        """Handle installation completion"""
        debug_print(f"DEBUG: on_installation_finished called with success={success}, message={message}")
        # R&D: Clear all progress displays when installation completes
        self.progress_state_manager.reset()
        # Clear file list but keep CPU tracking running for configuration phase
        self.file_progress_list.list_widget.clear()
        self.file_progress_list._file_items.clear()
        self.file_progress_list._summary_widget = None
        self.file_progress_list._transition_label = None
        self.file_progress_list._last_phase = None
        
        if success:
            # Update progress indicator with completion
            from jackify.shared.progress_models import InstallationProgress, InstallationPhase
            final_state = InstallationProgress(
                phase=InstallationPhase.FINALIZE,
                phase_name="Installation Complete",
                overall_percent=100.0
            )
            self.progress_indicator.update_progress(final_state)
            
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nSuccess: {message}")
            self.process_finished(0, QProcess.NormalExit)  # Simulate successful completion
        else:
            # Reset to initial state on failure
            self.progress_indicator.reset()

            if self._premium_failure_active:
                message = "Installation stopped because Nexus Premium is required for automated downloads."
            
            if self.show_details_checkbox.isChecked():
                self._safe_append_text(f"\nError: {message}")
            self.process_finished(1, QProcess.CrashExit)  # Simulate error

    def process_finished(self, exit_code, exit_status):
        debug_print(f"DEBUG: process_finished called with exit_code={exit_code}, exit_status={exit_status}")
        # Reset button states
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)
        debug_print("DEBUG: Button states reset in process_finished")
        

        if exit_code == 0:
            # Check if this was an unsupported game
            game_type = getattr(self, '_current_game_type', None)
            game_name = getattr(self, '_current_game_name', None)
            
            if game_type and not self.wabbajack_parser.is_supported_game(game_type):
                # Show success message for unsupported games without post-install configuration
                MessageService.information(
                    self, "Modlist Install Complete!",
                    f"Modlist installation completed successfully!\n\n"
                    f"Note: Post-install configuration was skipped for unsupported game type: {game_name or game_type}\n\n"
                    f"You will need to manually configure Steam shortcuts and other post-install steps."
                )
                self._safe_append_text(f"\nModlist installation completed successfully.")
                self._safe_append_text(f"\nWarning: Post-install configuration skipped for unsupported game: {game_name or game_type}")
            else:
                # Check if auto-restart is enabled
                auto_restart_enabled = hasattr(self, 'auto_restart_checkbox') and self.auto_restart_checkbox.isChecked()
                
                if auto_restart_enabled:
                    # Auto-accept Steam restart - proceed without dialog
                    self._safe_append_text("\nAuto-accepting Steam restart (unattended mode enabled)")
                    reply = QMessageBox.Yes  # Simulate user clicking Yes
                else:
                    # Show the normal install complete dialog for supported games
                    reply = MessageService.question(
                        self, "Modlist Install Complete!",
                        "Modlist install complete!\n\nWould you like to add this modlist to Steam and configure it now? Steam will restart, closing any game you have open!",
                        critical=False  # Non-critical, won't steal focus
                    )
                
                if reply == QMessageBox.Yes:
                    # --- Create Steam shortcut BEFORE restarting Steam ---
                    # Proceed directly to automated prefix creation
                    self.start_automated_prefix_workflow()
                else:
                    # User selected "No" - show completion message and keep GUI open
                    self._safe_append_text("\nModlist installation completed successfully!")
                    self._safe_append_text("Note: You can manually configure Steam integration later if needed.")
                    MessageService.information(
                        self, "Installation Complete", 
                        "Modlist installation completed successfully!\n\n"
                        "The modlist has been installed but Steam integration was skipped.\n"
                        "You can manually add the modlist to Steam later if desired.",
                        safety_level="medium"
                    )
                    # Re-enable controls since operation is complete
                    self._enable_controls_after_operation()
        else:
            # Check for user cancellation first - check message parameter first, then console
            if self._premium_failure_active:
                MessageService.warning(
                    self,
                    "Nexus Premium Required",
                    "Jackify stopped the installation because Nexus Mods reported that this account is not Premium.\n\n"
                    "Automatic installs currently require Nexus Premium. Non-premium support is planned.",
                    safety_level="medium"
                )
                self._safe_append_text("\nInstall stopped: Nexus Premium required.")
                self._premium_failure_active = False
            elif hasattr(self, '_cancellation_requested') and self._cancellation_requested:
                # User explicitly cancelled via cancel button
                MessageService.information(self, "Installation Cancelled", "The installation was cancelled by the user.", safety_level="low")
                self._cancellation_requested = False
            else:
                # Check console as fallback
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
    
    def _build_post_install_sequence(self):
        """
        Define the ordered steps for post-install (Jackify-managed) operations.

        These steps represent Jackify's automated Steam integration and configuration workflow
        that runs AFTER the jackify-engine completes modlist installation. Progress is shown as
        "X/Y" in the progress banner and Activity window.

        The post-install steps are:
        1. Preparing Steam integration - Initial setup before creating Steam shortcut
        2. Creating Steam shortcut - Add modlist to Steam library with proper Proton settings
        3. Restarting Steam - Restart Steam to make shortcut visible and create AppID
        4. Creating Proton prefix - Launch temporary batch file to initialize Proton prefix
        5. Verifying Steam setup - Confirm prefix exists and Proton version is correct
        6. Steam integration complete - Steam setup finished successfully
        7. Installing Wine components - Install vcrun, dotnet, and other Wine dependencies
        8. Applying registry files - Import .reg files for game configuration
        9. Installing .NET fixes - Apply .NET framework workarounds if needed
        10. Enabling dotfiles - Make hidden config files visible in file manager
        11. Setting permissions - Ensure modlist files have correct permissions
        12. Backing up configuration - Create backup of ModOrganizer.ini
        13. Finalising Jackify configuration - All post-install steps complete
        """
        return [
            {
                'id': 'prepare',
                'label': "Preparing Steam integration",
                'keywords': [
                    "starting automated steam setup",
                    "starting configuration phase",
                    "starting configuration"
                ],
            },
            {
                'id': 'steam_shortcut',
                'label': "Creating Steam shortcut",
                'keywords': [
                    "creating steam shortcut",
                    "steam shortcut created successfully"
                ],
            },
            {
                'id': 'steam_restart',
                'label': "Restarting Steam",
                'keywords': [
                    "restarting steam",
                    "steam restarted successfully"
                ],
            },
            {
                'id': 'proton_prefix',
                'label': "Creating Proton prefix",
                'keywords': [
                    "creating proton prefix",
                    "proton prefix created successfully",
                    "temporary batch file launched",
                    "verifying prefix creation"
                ],
            },
            {
                'id': 'steam_verify',
                'label': "Verifying Steam setup",
                'keywords': [
                    "verifying setup",
                    "verifying prefix",
                    "setup verification completed",
                    "detecting actual appid",
                    "steam configuration complete"
                ],
            },
            {
                'id': 'steam_complete',
                'label': "Steam integration complete",
                'keywords': [
                    "steam integration complete",
                    "steam integration",
                    "steam configuration complete!"
                ],
            },
            {
                'id': 'wine_components',
                'label': "Installing Wine components",
                'keywords': [
                    "installing wine components",
                    "wine components",
                    "vcrun",
                    "dotnet",
                    "running winetricks",
                ],
            },
            {
                'id': 'registry_files',
                'label': "Applying registry files",
                'keywords': [
                    "applying registry",
                    "importing registry",
                    ".reg file",
                    "registry files",
                ],
            },
            {
                'id': 'dotnet_fixes',
                'label': "Installing .NET fixes",
                'keywords': [
                    "dotnet fix",
                    ".net fix",
                    "installing .net",
                ],
            },
            {
                'id': 'enable_dotfiles',
                'label': "Enabling dotfiles",
                'keywords': [
                    "enabling dotfiles",
                    "dotfiles",
                    "hidden files",
                ],
            },
            {
                'id': 'set_permissions',
                'label': "Setting permissions",
                'keywords': [
                    "setting permissions",
                    "chmod",
                    "permissions",
                ],
            },
            {
                'id': 'backup_config',
                'label': "Backing up configuration",
                'keywords': [
                    "backing up",
                    "modorganizer.ini",
                    "backup",
                ],
            },
            {
                'id': 'config_finalize',
                'label': "Finalising Jackify configuration",
                'keywords': [
                    "configuration completed successfully",
                    "configuration complete",
                    "manual steps validation failed",
                    "configuration failed"
                ],
            },
        ]
    
    def _begin_post_install_feedback(self):
        """Reset trackers and surface post-install progress in collapsed mode."""
        self._post_install_active = True
        self._post_install_current_step = 0
        self._post_install_last_label = "Preparing Steam integration"
        total = max(1, self._post_install_total_steps)
        self._update_post_install_ui(self._post_install_last_label, 0, total)
    
    def _handle_post_install_progress(self, message: str):
        """Translate backend progress messages into collapsed-mode feedback."""
        if not self._post_install_active or not message:
            return
        
        text = message.strip()
        if not text:
            return
        normalized = text.lower()
        total = max(1, self._post_install_total_steps)
        matched = False
        matched_step = None
        for idx, step in enumerate(self._post_install_sequence, start=1):
            if any(keyword in normalized for keyword in step['keywords']):
                matched = True
                matched_step = idx
                # Always update to the highest step we've seen (don't go backwards)
                if idx >= self._post_install_current_step:
                    self._post_install_current_step = idx
                    self._post_install_last_label = step['label']
                # CRITICAL: Always use the current step (not the matched step) to ensure consistency
                # This prevents Activity window showing different step than progress banner
                self._update_post_install_ui(step['label'], self._post_install_current_step, total, detail=text)
                break
        
        # If no match but we have a current step, update with that step (not a new one)
        if not matched and self._post_install_current_step > 0:
            label = self._post_install_last_label or "Post-installation"
            # CRITICAL: Use _post_install_current_step (not a new step) to keep displays in sync
            self._update_post_install_ui(label, self._post_install_current_step, total, detail=text)
    
    def _strip_timestamp_prefix(self, text: str) -> str:
        """Remove timestamp prefix like '[00:03:15]' from text."""
        import re
        # Match timestamps like [00:03:15], [01:23:45], etc.
        timestamp_pattern = r'^\[\d{2}:\d{2}:\d{2}\]\s*'
        return re.sub(timestamp_pattern, '', text)

    def _update_post_install_ui(self, label: str, step: int, total: int, detail: Optional[str] = None):
        """Update progress indicator + activity summary for post-install steps."""
        # Use the label as the primary display, but include step info in Activity window
        display_label = label
        if detail:
            # Remove timestamp prefix from detail messages
            clean_detail = self._strip_timestamp_prefix(detail.strip())
            if clean_detail:
                # For Activity window, show the detail with step counter
                # But keep label simple for progress banner
                if clean_detail.lower().startswith(label.lower()):
                    display_label = clean_detail
                else:
                    display_label = clean_detail
        total = max(1, total)
        step_clamped = max(0, min(step, total))
        overall_percent = (step_clamped / total) * 100.0
        
        # CRITICAL: Ensure both displays use the SAME step counter
        # Progress banner uses phase_step/phase_max_steps from progress_state
        progress_state = InstallationProgress(
            phase=InstallationPhase.FINALIZE,
            phase_name=display_label,  # This will show in progress banner
            phase_step=step_clamped,    # This creates [step/total] in display_text
            phase_max_steps=total,
            overall_percent=overall_percent
        )
        self.progress_indicator.update_progress(progress_state)
        
        # Activity window uses summary_info with the SAME step counter
        summary_info = {
            'current_step': step_clamped,  # Must match phase_step above
            'max_steps': total,            # Must match phase_max_steps above
        }
        # Use the same label for consistency
        self.file_progress_list.update_files([], current_phase=display_label, summary_info=summary_info)
    
    def _end_post_install_feedback(self, success: bool):
        """Mark the end of post-install feedback."""
        if not self._post_install_active:
            return
        total = max(1, self._post_install_total_steps)
        final_step = total if success else max(0, self._post_install_current_step)
        label = "Post-installation complete" if success else "Post-installation stopped"
        self._update_post_install_ui(label, final_step, total)
        self._post_install_active = False
        self._post_install_last_label = label
    
    def _reset_manual_scroll_if_at_bottom(self):
        """Reset manual scroll flag if user is still at bottom after delay"""
        scrollbar = self.console.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 1:
            self._user_manually_scrolled = False

    def _safe_append_text(self, text):
        """
        Append text with professional auto-scroll behavior.

        Handles carriage return (\\r) for in-place updates and newline (\\n) for new lines.
        """
        # Write all messages to log file (including internal messages)
        self._write_to_log_file(text)

        # Filter out internal status messages from user console display
        if text.strip().startswith('[Jackify]'):
            # Internal messages are logged but not shown in user console
            return

        # Check if this is a carriage return update (should replace last line)
        if '\r' in text and '\n' not in text:
            # Carriage return - replace last line
            self._replace_last_console_line(text.replace('\r', ''))
            return

        # Handle mixed \r\n or just \n - normal append
        # Clean up any remaining \r characters
        clean_text = text.replace('\r', '')

        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance

        # Add the text
        self.console.append(clean_text)

        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _is_similar_progress_line(self, text):
        """Check if this line is a similar progress update to the last line"""
        if not hasattr(self, '_last_console_line') or not self._last_console_line:
            return False

        # Don't deduplicate if either line contains important markers
        important_markers = [
            'complete',
            'failed',
            'error',
            'warning',
            'starting',
            '===',
            '---',
            'SUCCESS',
            'FAILED',
        ]

        text_lower = text.lower()
        last_lower = self._last_console_line.lower()

        for marker in important_markers:
            if marker.lower() in text_lower or marker.lower() in last_lower:
                return False

        # Patterns that indicate this is a progress line that should replace the previous
        # These are the status lines that update rapidly with changing numbers
        progress_patterns = [
            'Installing files',
            'Extracting files',
            'Downloading:',
            'Building BSAs',
            'Validating',
        ]

        # Check if both current and last line contain the same progress pattern
        # AND the lines are actually different (not exact duplicates)
        for pattern in progress_patterns:
            if pattern in text and pattern in self._last_console_line:
                # Only deduplicate if the numbers/progress changed (not exact duplicate)
                if text.strip() != self._last_console_line.strip():
                    return True

        # Special case: texture conversion status is embedded in Installing files lines
        # Match lines like "Installing files X/Y (A/B) - Converting textures: N/M"
        if '- Converting textures:' in text and '- Converting textures:' in self._last_console_line:
            if text.strip() != self._last_console_line.strip():
                return True

        return False

    def _replace_last_console_line(self, text):
        """Replace the last line in the console with new text"""
        scrollbar = self.console.verticalScrollBar()
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)

        # Move cursor to end and select the last line
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()  # Remove the newline

        # Insert the new text
        self.console.append(text)

        # Track this line
        self._last_console_line = text

        # Restore scroll position
        if was_at_bottom or not self._user_manually_scrolled:
            scrollbar.setValue(scrollbar.maximum())

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

            # Force Steam GUI to start after restart
            # Ensure Steam GUI is visible after restart
            # start_steam() now uses -foreground, but we'll also try to bring GUI to front
            debug_print("DEBUG: Ensuring Steam GUI is visible after restart")
            try:
                import subprocess
                import time
                # Wait a moment for Steam processes to stabilize
                time.sleep(3)
                # Try multiple methods to ensure GUI opens
                # Method 1: steam:// protocol (works if Steam is running)
                try:
                    subprocess.Popen(['xdg-open', 'steam://open/main'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    debug_print("DEBUG: Issued steam://open/main command")
                    time.sleep(1)
                except Exception as e:
                    debug_print(f"DEBUG: steam://open/main failed: {e}")
                
                # Method 2: Direct steam -foreground command (redundant but ensures GUI)
                try:
                    subprocess.Popen(['steam', '-foreground'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    debug_print("DEBUG: Issued steam -foreground command")
                except Exception as e2:
                    debug_print(f"DEBUG: steam -foreground failed: {e2}")
            except Exception as e:
                debug_print(f"DEBUG: Error ensuring Steam GUI visibility: {e}")
            
            # CRITICAL: Bring Jackify window back to focus after Steam restart
            # This ensures the user can continue with the installation workflow
            debug_print("DEBUG: Bringing Jackify window back to focus")
            try:
                # Get the main window - use window() to get top-level widget, then find QMainWindow
                top_level = self.window()
                main_window = None
                
                # Try to find QMainWindow in the widget hierarchy
                if isinstance(top_level, QMainWindow):
                    main_window = top_level
                else:
                    # Walk up the parent chain
                    current = self
                    while current:
                        if isinstance(current, QMainWindow):
                            main_window = current
                            break
                        current = current.parent()
                    
                    # Last resort: use top-level widget
                    if not main_window and top_level:
                        main_window = top_level
                
                if main_window:
                    # Restore window if minimized
                    if hasattr(main_window, 'isMinimized') and main_window.isMinimized():
                        main_window.showNormal()
                    
                    # Bring to front and activate - use multiple methods for reliability
                    main_window.raise_()
                    main_window.activateWindow()
                    main_window.show()
                    
                    # Force focus with multiple attempts (some window managers need this)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(50, lambda: main_window.activateWindow() if main_window else None)
                    QTimer.singleShot(200, lambda: (main_window.raise_(), main_window.activateWindow()) if main_window else None)
                    QTimer.singleShot(500, lambda: main_window.activateWindow() if main_window else None)
                    
                    debug_print(f"DEBUG: Jackify window brought back to focus (type: {type(main_window).__name__})")
                else:
                    debug_print("DEBUG: Could not find main window to bring to focus")
            except Exception as e:
                debug_print(f"DEBUG: Error bringing Jackify to focus: {e}")

            # Save context for later use in configuration
            self._manual_steps_retry_count = 0
            self._current_modlist_name = self.modlist_name_edit.text().strip()

            # Save resolution for later use in configuration
            resolution = self.resolution_combo.currentText()
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None

            # Use automated prefix creation instead of manual steps
            debug_print("DEBUG: Starting automated prefix creation workflow")
            self._safe_append_text("Starting automated prefix creation workflow...")
            self.start_automated_prefix_workflow()
        else:
            self._safe_append_text("Failed to restart Steam.\n" + out)
            MessageService.critical(self, "Steam Restart Failed", "Failed to restart Steam automatically. Please restart Steam manually, then try again.")

    def start_automated_prefix_workflow(self):
        """Start the automated prefix creation workflow"""
        # CRITICAL: Reload config from disk to pick up any settings changes from Settings dialog
        # This ensures Proton version and winetricks settings are current
        self.config_handler._load_config()

        # Ensure _current_resolution is always set before starting workflow
        if not hasattr(self, '_current_resolution') or self._current_resolution is None:
            resolution = self.resolution_combo.currentText() if hasattr(self, 'resolution_combo') else None
            # Extract resolution properly (e.g., "1280x800" from "1280x800 (Steam Deck)")
            if resolution and resolution != "Leave unchanged":
                if " (" in resolution:
                    self._current_resolution = resolution.split(" (")[0]
                else:
                    self._current_resolution = resolution
            else:
                self._current_resolution = None

        try:
            # Disable controls during installation
            self._disable_controls_during_operation()
            modlist_name = self.modlist_name_edit.text().strip()
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
            
            self._begin_post_install_feedback()

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
                modlist_name = self.modlist_name_edit.text().strip()
                install_dir = self.install_dir_edit.text().strip()
                self.continue_configuration_after_automated_prefix(new_appid, modlist_name, install_dir, last_timestamp)
            else:
                self._safe_append_text(f"ERROR: Automated prefix creation failed")
                self._safe_append_text("Please check the logs for details")
                MessageService.critical(self, "Automated Setup Failed", 
                    "Automated prefix creation failed. Please check the console output for details.")
                # Re-enable controls on failure
                self._enable_controls_after_operation()
                self._end_post_install_feedback(success=False)
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
        self._end_post_install_feedback(success=False)
    
    def on_automated_prefix_progress(self, progress_msg):
        """Handle progress updates from automated prefix creation"""
        self._safe_append_text(progress_msg)
        self._handle_post_install_progress(progress_msg)
    
    def on_configuration_progress(self, progress_msg):
        """Handle progress updates from modlist configuration"""
        self._safe_append_text(progress_msg)
        self._handle_post_install_progress(progress_msg)
    
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
            # Stop CPU tracking now that everything is complete
            self.file_progress_list.stop_cpu_tracking()
            # Re-enable controls now that installation/configuration is complete
            self._enable_controls_after_operation()
            self._end_post_install_feedback(success)
            
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

                # Check for TTW eligibility before showing final success dialog
                install_dir = self.install_dir_edit.text().strip()
                if self._check_ttw_eligibility(modlist_name, self._current_game_type, install_dir):
                    # Offer TTW installation
                    reply = MessageService.question(
                        self,
                        "Install TTW?",
                        f"{modlist_name} requires Tale of Two Wastelands!\n\n"
                        "Would you like to install TTW now?\n\n"
                        "This will:\n"
                        "• Guide you through TTW installation\n"
                        "• Attempt to integrate TTW into your modlist automatically\n"
                        "• Configure load order if integration is supported\n\n"
                        "Note: Automatic integration works for some modlists (like Begin Again). "
                        "Other modlists may require manual TTW setup. "
                        "TTW installation can take a while.\n\n"
                        "You can also install TTW later from Additional Tasks & Tools.",
                        critical=False,
                        safety_level="medium"
                    )

                    if reply == QMessageBox.Yes:
                        # Navigate to TTW screen
                        self._initiate_ttw_workflow(modlist_name, install_dir)
                        return  # Don't show success dialog yet, will show after TTW completes

                # Clear Activity window before showing success dialog
                self.file_progress_list.clear()

                # Show normal success dialog
                success_dialog = SuccessDialog(
                    modlist_name=modlist_name,
                    workflow_type="install",
                    time_taken=time_str,
                    game_name=game_name,
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
        modlist_name = self.modlist_name_edit.text().strip() or "your modlist"
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
        modlist_name = self.modlist_name_edit.text().strip()
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
        original_name = self.modlist_name_edit.text()
        self.modlist_name_edit.setText(new_name)
        
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
                configuration_complete = Signal(bool, str, str, bool)
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
    
    def cancel_installation(self):
        """Cancel the currently running installation"""
        reply = MessageService.question(
            self, "Cancel Installation", 
            "Are you sure you want to cancel the installation?",
            critical=False  # Non-critical, won't steal focus
        )
        
        if reply == QMessageBox.Yes:
            self._safe_append_text("\n🛑 Cancelling installation...")

            # Set flag so we can detect cancellation reliably
            self._cancellation_requested = True

            try:
                # Clear Active Files window and reset progress indicator
                if hasattr(self, 'file_progress_list'):
                    self.file_progress_list.clear()
                if hasattr(self, 'progress_indicator'):
                    self.progress_indicator.reset()

                # Cancel the installation thread if it exists
                if hasattr(self, 'install_thread') and self.install_thread and self.install_thread.isRunning():
                    self.install_thread.cancel()
                    self.install_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                    if self.install_thread.isRunning():
                        self.install_thread.terminate()  # Force terminate if needed
                        self.install_thread.wait(1000)

                # Cancel the automated prefix thread if it exists
                if hasattr(self, 'prefix_thread') and self.prefix_thread and self.prefix_thread.isRunning():
                    self.prefix_thread.terminate()
                    self.prefix_thread.wait(3000)  # Wait up to 3 seconds for graceful shutdown
                    if self.prefix_thread.isRunning():
                        self.prefix_thread.terminate()  # Force terminate if needed
                        self.prefix_thread.wait(1000)

                # Cancel the configuration thread if it exists
                if hasattr(self, 'config_thread') and self.config_thread and self.config_thread.isRunning():
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

            except Exception as e:
                debug_print(f"ERROR: Exception during cancellation cleanup: {e}")
                import traceback
                traceback.print_exc()

            finally:
                # Always write cancellation message to console so detection works
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
        self.go_back()
    
    def reset_screen_to_defaults(self):
        """Reset the screen to default state when navigating back from main menu"""
        # Reset form fields
        self.modlist_btn.setText("Select Modlist")
        self.modlist_btn.setEnabled(False)
        self.file_edit.setText("")
        self.modlist_name_edit.setText("")
        self.install_dir_edit.setText(self.config_handler.get_modlist_install_base_dir())
        # Reset game type button
        self.game_type_btn.setText("Please Select...")

        # Clear console and process monitor
        self.console.clear()
        self.process_monitor.clear()

        # Reset tabs to first tab (Online)
        self.source_tabs.setCurrentIndex(0)

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

 