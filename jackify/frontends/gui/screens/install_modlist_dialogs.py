"""
Helper dialog classes for InstallModlistScreen
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QAbstractItemView, QLabel, QWidget, QSizePolicy)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QBrush
import logging
import os

logger = logging.getLogger(__name__)


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

