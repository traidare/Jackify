"""
Wabbajack Installer Screen

Automated Wabbajack.exe installation via Proton with progress tracking.
Follows standard Jackify screen layout.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QGridLayout, QTextEdit, QTabWidget, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QTextCursor

from jackify.backend.models.configuration import SystemInfo
from jackify.backend.handlers.wabbajack_installer_handler import WabbajackInstallerHandler
from ..services.message_service import MessageService
from ..shared_theme import JACKIFY_COLOR_BLUE, DEBUG_BORDERS
from ..utils import set_responsive_minimum
from ..widgets.file_progress_list import FileProgressList
from ..widgets.progress_indicator import OverallProgressIndicator

logger = logging.getLogger(__name__)


class WabbajackInstallerWorker(QThread):
    """Background worker for Wabbajack installation"""

    progress_update = Signal(str, int)  # Status message, percentage
    activity_update = Signal(str, int, int)  # Activity label, current, total
    log_output = Signal(str)  # Console log output
    installation_complete = Signal(bool, str, str, str, str)  # Success, message, launch_options, app_id, time_taken

    def __init__(self, install_folder: Path, shortcut_name: str = "Wabbajack", enable_gog: bool = True):
        super().__init__()
        self.install_folder = install_folder
        self.shortcut_name = shortcut_name
        self.enable_gog = enable_gog
        self.handler = WabbajackInstallerHandler()
        self.launch_options = ""  # Store launch options for success message
        self.start_time = None  # Track installation start time

    def _log(self, message: str):
        """Emit log message"""
        self.log_output.emit(message)
        logger.info(message)

    def run(self):
        """Run the installation workflow"""
        import time
        self.start_time = time.time()
        try:
            total_steps = 12

            # Step 1: Check requirements
            self.progress_update.emit("Checking requirements...", 5)
            self.activity_update.emit("Checking requirements", 1, total_steps)
            self._log("Checking system requirements...")

            proton_path = self.handler.find_proton_experimental()
            if not proton_path:
                self.installation_complete.emit(
                    False,
                    "Proton Experimental not found.\nPlease install it from Steam."
                )
                return
            self._log(f"Found Proton Experimental: {proton_path}")

            userdata = self.handler.find_steam_userdata_path()
            if not userdata:
                self.installation_complete.emit(
                    False,
                    "Steam userdata not found.\nPlease ensure Steam is installed and you're logged in."
                )
                return
            self._log(f"Found Steam userdata: {userdata}")

            # Step 2: Download Wabbajack
            self.progress_update.emit("Downloading Wabbajack.exe...", 15)
            self.activity_update.emit("Downloading Wabbajack.exe", 2, total_steps)
            self._log("Downloading Wabbajack.exe from GitHub...")
            wabbajack_exe = self.handler.download_wabbajack(self.install_folder)
            self._log(f"Downloaded to: {wabbajack_exe}")

            # Step 3: Create dotnet cache
            self.progress_update.emit("Creating .NET cache directory...", 20)
            self.activity_update.emit("Creating .NET cache", 3, total_steps)
            self._log("Creating .NET bundle extract cache...")
            self.handler.create_dotnet_cache(self.install_folder)

            # Step 4: Stop Steam before modifying shortcuts.vdf
            self.progress_update.emit("Stopping Steam...", 25)
            self.activity_update.emit("Stopping Steam", 4, total_steps)
            self._log("Stopping Steam (required to safely modify shortcuts.vdf)...")
            import subprocess
            import time
            
            # Kill Steam using pkill (simple approach like AuCu)
            try:
                subprocess.run(['steam', '-shutdown'], timeout=5, capture_output=True)
                time.sleep(2)
                subprocess.run(['pkill', '-9', 'steam'], timeout=5, capture_output=True)
                time.sleep(2)
                self._log("Steam stopped successfully")
            except Exception as e:
                self._log(f"Warning: Steam shutdown had issues: {e}. Proceeding anyway...")

            # Step 5: Add to Steam shortcuts (NO Proton - like AuCu, but with STEAM_COMPAT_MOUNTS for libraries)
            self.progress_update.emit("Adding to Steam shortcuts...", 30)
            self.activity_update.emit("Adding to Steam", 5, total_steps)
            self._log("Adding Wabbajack to Steam shortcuts...")
            from jackify.backend.services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            
            # Generate launch options with STEAM_COMPAT_MOUNTS for additional Steam libraries (like modlist installs)
            # Default to empty string (like AuCu) - only add options if we have additional libraries
            # Note: Users may need to manually add other paths (e.g., download directories on different drives) to launch options
            launch_options = ""
            try:
                from jackify.backend.handlers.path_handler import PathHandler
                path_handler = PathHandler()
                
                all_libs = path_handler.get_all_steam_library_paths()
                main_steam_lib_path_obj = path_handler.find_steam_library()
                if main_steam_lib_path_obj and main_steam_lib_path_obj.name == "common":
                    main_steam_lib_path = main_steam_lib_path_obj.parent.parent
                    
                    filtered_libs = [lib for lib in all_libs if str(lib) != str(main_steam_lib_path)]
                    if filtered_libs:
                        mount_paths = ":".join(str(lib) for lib in filtered_libs)
                        launch_options = f'STEAM_COMPAT_MOUNTS="{mount_paths}" %command%'
                        self._log(f"Added STEAM_COMPAT_MOUNTS for additional Steam libraries: {mount_paths}")
                    else:
                        self._log("No additional Steam libraries found - using empty launch options (like AuCu)")
            except Exception as e:
                self._log(f"Could not generate STEAM_COMPAT_MOUNTS (non-critical): {e}")
                # Keep empty string like AuCu
            
            # Store launch options for success message
            self.launch_options = launch_options
            
            # Create shortcut WITHOUT Proton (AuCu does this separately later)
            success, app_id = steam_service.create_shortcut(
                app_name=self.shortcut_name,
                exe_path=str(wabbajack_exe),
                start_dir=str(wabbajack_exe.parent),
                launch_options=launch_options,  # Empty or with STEAM_COMPAT_MOUNTS
                tags=["Jackify"]
            )
            if not success or app_id is None:
                raise RuntimeError("Failed to create Steam shortcut")
            self._log(f"Created Steam shortcut with AppID: {app_id}")

            # Step 6: Initialize Wine prefix
            self.progress_update.emit("Initializing Wine prefix...", 45)
            self.activity_update.emit("Initializing Wine prefix", 6, total_steps)
            self._log("Initializing Wine prefix with Proton...")
            prefix_path = self.handler.init_wine_prefix(app_id)
            self._log(f"Wine prefix created: {prefix_path}")

            # Step 7: Install WebView2
            self.progress_update.emit("Installing WebView2 runtime...", 60)
            self.activity_update.emit("Installing WebView2", 7, total_steps)
            self._log("Downloading and installing WebView2...")
            try:
                self.handler.install_webview2(app_id, self.install_folder)
                self._log("WebView2 installed successfully")
            except Exception as e:
                self._log(f"WARNING: WebView2 installation may have failed: {e}")
                self._log("This may prevent Nexus login in Wabbajack. You can manually install WebView2 later.")
                # Continue installation - WebView2 is not critical for basic functionality

            # Step 8: Apply Win7 registry
            self.progress_update.emit("Applying Windows 7 registry settings...", 75)
            self.activity_update.emit("Applying registry settings", 8, total_steps)
            self._log("Applying Windows 7 compatibility settings...")
            self.handler.apply_win7_registry(app_id)
            self._log("Registry settings applied")

            # Step 9: GOG game detection (optional)
            gog_count = 0
            if self.enable_gog:
                self.progress_update.emit("Detecting GOG games from Heroic...", 80)
                self.activity_update.emit("Detecting GOG games", 9, total_steps)
                self._log("Searching for GOG games in Heroic...")
                try:
                    gog_count = self.handler.inject_gog_registry(app_id)
                    if gog_count > 0:
                        self._log(f"Detected and injected {gog_count} GOG games")
                    else:
                        self._log("No GOG games found in Heroic")
                except Exception as e:
                    self._log(f"GOG injection failed (non-critical): {e}")

            # Step 10: Create Steam library symlinks
            self.progress_update.emit("Creating Steam library symlinks...", 85)
            self.activity_update.emit("Creating library symlinks", 10, total_steps)
            self._log("Creating Steam library symlinks for game detection...")
            steam_service.create_steam_library_symlinks(app_id)
            self._log("Steam library symlinks created")

            # Step 11: Set Proton Experimental (separate step like AuCu)
            self.progress_update.emit("Setting Proton compatibility...", 90)
            self.activity_update.emit("Setting Proton compatibility", 11, total_steps)
            self._log("Setting Proton Experimental as compatibility tool...")
            try:
                steam_service.set_proton_version(app_id, "proton_experimental")
                self._log("Proton Experimental set successfully")
            except Exception as e:
                self._log(f"Warning: Failed to set Proton version (non-critical): {e}")
                self._log("You can set it manually in Steam: Properties → Compatibility → Proton Experimental")

            # Step 12: Start Steam at the end
            self.progress_update.emit("Starting Steam...", 95)
            self.activity_update.emit("Starting Steam", 12, total_steps)
            self._log("Starting Steam...")
            from jackify.backend.services.steam_restart_service import start_steam
            start_steam()
            time.sleep(3)  # Give Steam time to start
            self._log("Steam started successfully")

            # Done!
            self.progress_update.emit("Installation complete!", 100)
            self.activity_update.emit("Installation complete", 12, total_steps)
            self._log("\n=== Installation Complete ===")
            self._log(f"Wabbajack installed to: {self.install_folder}")
            self._log(f"Steam AppID: {app_id}")
            if gog_count > 0:
                self._log(f"GOG games detected: {gog_count}")
            self._log("You can now launch Wabbajack from Steam")

            # Calculate time taken
            import time
            time_taken = int(time.time() - self.start_time)
            mins, secs = divmod(time_taken, 60)
            time_str = f"{mins} minutes, {secs} seconds" if mins else f"{secs} seconds"

            # Store data for success dialog (app_id as string to avoid overflow)
            self.installation_complete.emit(True, "", self.launch_options, str(app_id), time_str)

        except Exception as e:
            error_msg = f"Installation failed: {str(e)}"
            self._log(f"\nERROR: {error_msg}")
            logger.error(f"Wabbajack installation failed: {e}", exc_info=True)
            self.installation_complete.emit(False, error_msg, "", "", "")


class WabbajackInstallerScreen(QWidget):
    """Wabbajack installer GUI screen following standard Jackify layout"""

    resize_request = Signal(str)

    def __init__(self, stacked_widget=None, additional_tasks_index=3, system_info: Optional[SystemInfo] = None):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.additional_tasks_index = additional_tasks_index
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        self.debug = DEBUG_BORDERS

        self.install_folder = None
        self.shortcut_name = "Wabbajack"
        self.worker = None
        
        # Get config handler for default paths
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.config_handler = ConfigHandler()

        # Scroll tracking for professional auto-scroll behavior
        self._user_manually_scrolled = False
        self._was_at_bottom = True

        # Initialize progress reporting
        self.progress_indicator = OverallProgressIndicator(show_progress_bar=True)
        self.progress_indicator.set_status("Ready", 0)
        self.file_progress_list = FileProgressList()

        self._setup_ui()

    def _setup_ui(self):
        """Set up UI following standard Jackify pattern"""
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        main_layout.setContentsMargins(50, 50, 50, 0)
        main_layout.setSpacing(12)
        if self.debug:
            self.setStyleSheet("border: 2px solid magenta;")

        # Header
        self._setup_header(main_layout)

        # Upper section: Form (left) + Activity/Process Monitor (right)
        self._setup_upper_section(main_layout)

        # Status banner with "Show details" toggle
        self._setup_status_banner(main_layout)

        # Console output (hidden by default)
        self._setup_console(main_layout)

        # Buttons
        self._setup_buttons(main_layout)

    def _setup_header(self, layout):
        """Set up header section"""
        header_layout = QVBoxLayout()
        header_layout.setSpacing(1)

        title = QLabel("<b>Install Wabbajack via Proton</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE}; margin: 0px; padding: 0px;")
        title.setAlignment(Qt.AlignHCenter)
        title.setMaximumHeight(30)
        header_layout.addWidget(title)

        desc = QLabel(
            "Automated Wabbajack.exe Installation and configuration for running via Proton"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; margin: 0px; padding: 0px; line-height: 1.2;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(40)
        header_layout.addWidget(desc)

        header_widget = QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setMaximumHeight(75)
        layout.addWidget(header_widget)

    def _setup_upper_section(self, layout):
        """Set up upper section: Form (left) + Activity/Process Monitor (right)"""
        upper_hbox = QHBoxLayout()
        upper_hbox.setContentsMargins(0, 0, 0, 0)
        upper_hbox.setSpacing(16)

        # LEFT: Form and controls
        left_vbox = QVBoxLayout()
        left_vbox.setAlignment(Qt.AlignTop)

        # [Options] header
        options_header = QLabel("<b>[Options]</b>")
        options_header.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px; font-weight: bold;")
        options_header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        left_vbox.addWidget(options_header)

        # Form grid
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(12)
        form_grid.setVerticalSpacing(6)
        form_grid.setContentsMargins(0, 0, 0, 0)

        # Shortcut Name
        shortcut_name_label = QLabel("Shortcut Name:")
        self.shortcut_name_edit = QLineEdit("Wabbajack")
        self.shortcut_name_edit.setMaximumHeight(25)
        self.shortcut_name_edit.setToolTip("Name for the Steam shortcut (useful if installing multiple Wabbajack instances)")
        form_grid.addWidget(shortcut_name_label, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addWidget(self.shortcut_name_edit, 0, 1)
        
        # Installation Directory
        install_dir_label = QLabel("Installation Directory:")
        # Set default to $Install_Base_Dir/Wabbajack with actual text (not placeholder)
        default_install_dir = Path(self.config_handler.get_modlist_install_base_dir()) / "Wabbajack"
        self.install_dir_edit = QLineEdit(str(default_install_dir))
        self.install_dir_edit.setMaximumHeight(25)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedSize(80, 25)
        browse_btn.clicked.connect(self._browse_folder)

        install_dir_hbox = QHBoxLayout()
        install_dir_hbox.addWidget(self.install_dir_edit)
        install_dir_hbox.addWidget(browse_btn)

        form_grid.addWidget(install_dir_label, 1, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        form_grid.addLayout(install_dir_hbox, 1, 1)

        form_section_widget = QWidget()
        form_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form_section_widget.setLayout(form_grid)
        form_section_widget.setMinimumHeight(80)
        form_section_widget.setMaximumHeight(120)
        left_vbox.addWidget(form_section_widget)

        # Info text
        info_label = QLabel(
            "Enter your preferred name for the Steam shortcut for Wabbajack, then select where Wabbajack should be installed.\n\n"
            "Jackify will then download Wabbajack.exe, add it as a new non-Steam game and configure the Proton prefix. "
            "The WebView2 installation and prefix configuration will then take place.\n\n"
            "While there is initial support for GOG versions, please note that it relies on the game being installed via Heroic Game Launcher. "
            "The modlist itself must also support the GOG version of the game."
        )
        info_label.setStyleSheet("color: #999; font-size: 11px;")
        info_label.setWordWrap(True)
        left_vbox.addWidget(info_label)

        left_widget = QWidget()
        left_widget.setLayout(left_vbox)

        # RIGHT: Activity/Process Monitor tabs
        # No Process Monitor tab - we're not tracking processes
        # Just show Activity directly

        # Activity heading
        activity_heading = QLabel("<b>[Activity]</b>")
        activity_heading.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 13px;")

        activity_vbox = QVBoxLayout()
        activity_vbox.setContentsMargins(0, 0, 0, 0)
        activity_vbox.setSpacing(2)
        activity_vbox.addWidget(activity_heading)
        activity_vbox.addWidget(self.file_progress_list)

        activity_widget = QWidget()
        activity_widget.setLayout(activity_vbox)

        upper_hbox.addWidget(left_widget, stretch=11)
        upper_hbox.addWidget(activity_widget, stretch=9)

        upper_section_widget = QWidget()
        upper_section_widget.setLayout(upper_hbox)
        upper_section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_section_widget.setMaximumHeight(280)
        layout.addWidget(upper_section_widget)

    def _setup_status_banner(self, layout):
        """Set up status banner with Show details checkbox"""
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        banner_row.setSpacing(8)
        banner_row.addWidget(self.progress_indicator, 1)
        banner_row.addStretch()

        self.show_details_checkbox = QCheckBox("Show details")
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.setToolTip("Toggle detailed console output")
        self.show_details_checkbox.toggled.connect(self._on_show_details_toggled)
        banner_row.addWidget(self.show_details_checkbox)

        banner_row_widget = QWidget()
        banner_row_widget.setLayout(banner_row)
        banner_row_widget.setMaximumHeight(45)
        banner_row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(banner_row_widget)

    def _setup_console(self, layout):
        """Set up console output area (hidden by default)"""
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.console.setMinimumHeight(50)
        self.console.setMaximumHeight(1000)
        self.console.setFontFamily('monospace')
        self.console.setVisible(False)
        if self.debug:
            self.console.setStyleSheet("border: 2px solid yellow;")

        # Set up scroll tracking for professional auto-scroll behavior
        self._setup_scroll_tracking()

        layout.addWidget(self.console, stretch=1)

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
        self._was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1

    def _setup_buttons(self, layout):
        """Set up action buttons"""
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignHCenter)

        self.start_btn = QPushButton("Start Installation")
        self.start_btn.setFixedHeight(35)
        # Enable by default since we have a default directory
        self.start_btn.setEnabled(True)
        self.start_btn.clicked.connect(self._start_installation)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(35)
        self.cancel_btn.clicked.connect(self._go_back)
        btn_row.addWidget(self.cancel_btn)

        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        btn_row_widget.setMaximumHeight(50)
        layout.addWidget(btn_row_widget)

    def _on_show_details_toggled(self, checked):
        """Handle Show details checkbox toggle"""
        self.console.setVisible(checked)
        if checked:
            self.resize_request.emit("expand")
        else:
            self.resize_request.emit("compact")

    def _browse_folder(self):
        """Browse for installation folder"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Wabbajack Installation Folder",
            str(Path.home()),
            QFileDialog.ShowDirsOnly
        )

        if folder:
            self.install_folder = Path(folder)
            self.install_dir_edit.setText(str(self.install_folder))
            self.start_btn.setEnabled(True)
        
        # Update shortcut name from field
        self.shortcut_name = self.shortcut_name_edit.text().strip() or "Wabbajack"

    def _start_installation(self):
        """Start the installation process"""
        # Get install folder from text field (may be default or user-selected)
        install_dir_text = self.install_dir_edit.text().strip()
        if not install_dir_text:
            MessageService.warning(self, "No Folder Selected", "Please select an installation folder first.")
            return
        
        self.install_folder = Path(install_dir_text)
        
        # Get shortcut name
        self.shortcut_name = self.shortcut_name_edit.text().strip() or "Wabbajack"

        # Confirm with user
        confirm = MessageService.question(
            self,
            "Confirm Installation",
            f"Install Wabbajack to:\n{self.install_folder}\n\n"
            "This will download Wabbajack, add to Steam, install WebView2,\n"
            "and configure the Wine prefix automatically.\n\n"
            "Steam will be restarted during installation.\n\n"
            "Continue?"
        )

        if not confirm:
            return

        # Clear displays
        self.console.clear()
        self.file_progress_list.clear()

        # Update UI state
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_indicator.set_status("Starting installation...", 0)

        # Start worker thread
        self.worker = WabbajackInstallerWorker(self.install_folder, shortcut_name=self.shortcut_name, enable_gog=True)
        self.worker.progress_update.connect(self._on_progress_update)
        self.worker.activity_update.connect(self._on_activity_update)
        self.worker.log_output.connect(self._on_log_output)
        self.worker.installation_complete.connect(self._on_installation_complete)
        self.worker.start()

    def _on_progress_update(self, message: str, percentage: int):
        """Handle progress updates"""
        self.progress_indicator.set_status(message, percentage)

    def _on_activity_update(self, label: str, current: int, total: int):
        """Handle activity tab updates"""
        self.file_progress_list.update_files(
            [],
            current_phase=label,  # Use the actual step label (e.g., "Checking requirements", "Downloading Wabbajack.exe", etc.)
            summary_info={"current_step": current, "max_steps": total}
        )

    def _on_log_output(self, message: str):
        """Handle log output with professional auto-scroll"""
        scrollbar = self.console.verticalScrollBar()
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)

        self.console.append(message)

        # Auto-scroll if user was at bottom and hasn't manually scrolled
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _on_installation_complete(self, success: bool, message: str, launch_options: str = "", app_id: str = "", time_taken: str = ""):
        """Handle installation completion"""
        if success:
            self.progress_indicator.set_status("Installation complete!", 100)
            
            # Use SuccessDialog like other screens
            from ..dialogs.success_dialog import SuccessDialog
            from PySide6.QtWidgets import QLabel, QFrame
            
            success_dialog = SuccessDialog(
                modlist_name="Wabbajack",
                workflow_type="install",
                time_taken=time_taken,
                game_name=None,
                parent=self
            )
            
            # Increase dialog size to accommodate note section (Steam Deck: 1280x800)
            # Use wider dialog to reduce vertical space needed (more horizontal space available)
            success_dialog.setFixedSize(650, 550)  # Wider for Steam Deck (1280px width)
            
            # Add compat mounts note in a separate bordered section
            note_text = ""
            if launch_options and "STEAM_COMPAT_MOUNTS" in launch_options:
                note_text = "<b>Note:</b> To access other drives, add paths to launch options (Steam → Properties). "
                note_text += "Append with colons: <code>STEAM_COMPAT_MOUNTS=\"/existing:/new/path\" %command%</code>"
            elif not launch_options:
                note_text = "<b>Note:</b> To access other drives, add to launch options (Steam → Properties): "
                note_text += "<code>STEAM_COMPAT_MOUNTS=\"/path/to/directory\" %command%</code>"
            
            if note_text:
                # Find the card widget and add a note section after the next steps
                card = success_dialog.findChild(QFrame, "successCard")
                if card:
                    # Remove fixed height constraint and increase minimum (Steam Deck optimized)
                    card.setFixedWidth(590)  # Wider card to match wider dialog
                    card.setMinimumHeight(380)  # Reduced height due to wider text wrapping
                    card.setMaximumHeight(16777215)  # Remove max height constraint
                    
                    card_layout = card.layout()
                    if card_layout:
                        # Create a bordered note frame with proper sizing
                        note_frame = QFrame()
                        note_frame.setFrameShape(QFrame.StyledPanel)
                        note_frame.setStyleSheet(
                            "QFrame { "
                            "  background: #2a2f36; "
                            "  border: 1px solid #3fb7d6; "
                            "  border-radius: 6px; "
                            "  padding: 10px; "
                            "  margin-top: 6px; "
                            "}"
                        )
                        # Make note frame size naturally based on content (Steam Deck optimized)
                        note_frame.setMinimumHeight(80)
                        note_frame.setMaximumHeight(16777215)  # No max constraint
                        note_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
                        
                        note_layout = QVBoxLayout(note_frame)
                        note_layout.setContentsMargins(10, 10, 10, 10)  # Reduced padding
                        note_layout.setSpacing(0)
                        
                        note_label = QLabel(note_text)
                        note_label.setWordWrap(True)
                        note_label.setTextFormat(Qt.RichText)
                        note_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                        note_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
                        # No minimum height - let it size naturally based on content
                        note_label.setStyleSheet(
                            "QLabel { "
                            "  font-size: 11px; "
                            "  color: #b0b0b0; "
                            "  line-height: 1.3; "
                            "}"
                        )
                        note_layout.addWidget(note_label)
                        
                        # Insert before the Ko-Fi link (which should be near the end)
                        # Find the index of the Ko-Fi label or add at the end
                        insert_index = card_layout.count() - 2  # Before buttons, after next steps
                        card_layout.insertWidget(insert_index, note_frame)
            
            success_dialog.show()
            # Reset UI
            self.install_folder = None
            # Reset to default directory
            default_install_dir = Path(self.config_handler.get_modlist_install_base_dir()) / "Wabbajack"
            self.install_dir_edit.setText(str(default_install_dir))
            self.shortcut_name_edit.setText("Wabbajack")
            self.start_btn.setEnabled(True)  # Re-enable since we have default directory
            self.cancel_btn.setEnabled(True)
        else:
            self.progress_indicator.set_status("Installation failed", 0)
            MessageService.critical(self, "Installation Failed", message)
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)

    def _go_back(self):
        """Return to Additional Tasks menu"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.additional_tasks_index)

    def showEvent(self, event):
        """Called when widget becomes visible"""
        super().showEvent(event)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception:
            pass
