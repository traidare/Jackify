"""
Main window UI setup mixin.
Stacked widget, screens, bottom bar, screen change handling.
"""

import sys

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QSizePolicy,
)
from PySide6.QtCore import Qt

from jackify import __version__
from jackify.frontends.gui.shared_theme import DEBUG_BORDERS
from jackify.frontends.gui.widgets.feature_placeholder import FeaturePlaceholder


def _debug_print(message):
    from jackify.backend.handlers.config_handler import ConfigHandler
    ch = ConfigHandler()
    if ch.get('debug_mode', False):
        print(message)


class MainWindowUIMixin:
    """Mixin for main window UI: stacked widget, screens, bottom bar."""

    def _setup_ui(self, dev_mode=False):
        self.stacked_widget = QStackedWidget()
        from jackify.frontends.gui.screens import (
            MainMenu, ModlistTasksScreen, AdditionalTasksScreen,
            InstallModlistScreen, ConfigureNewModlistScreen, ConfigureExistingModlistScreen,
        )
        from jackify.frontends.gui.screens.install_ttw import InstallTTWScreen
        from jackify.frontends.gui.screens.wabbajack_installer import WabbajackInstallerScreen

        self.main_menu = MainMenu(stacked_widget=self.stacked_widget, dev_mode=dev_mode)
        self.feature_placeholder = FeaturePlaceholder(stacked_widget=self.stacked_widget)
        self.modlist_tasks_screen = ModlistTasksScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, dev_mode=dev_mode
        )
        self.additional_tasks_screen = AdditionalTasksScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, system_info=self.system_info
        )
        self.install_modlist_screen = InstallModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, system_info=self.system_info
        )
        self.configure_new_modlist_screen = ConfigureNewModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, system_info=self.system_info
        )
        self.configure_existing_modlist_screen = ConfigureExistingModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, system_info=self.system_info
        )
        self.install_ttw_screen = InstallTTWScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, system_info=self.system_info
        )
        self.wabbajack_installer_screen = WabbajackInstallerScreen(
            stacked_widget=self.stacked_widget, additional_tasks_index=3, system_info=self.system_info
        )

        try:
            self.install_ttw_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        try:
            self.install_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        try:
            self.configure_new_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        try:
            self.configure_existing_modlist_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        try:
            self.wabbajack_installer_screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass

        self.stacked_widget.addWidget(self.main_menu)
        self.stacked_widget.addWidget(self.feature_placeholder)
        self.stacked_widget.addWidget(self.modlist_tasks_screen)
        self.stacked_widget.addWidget(self.additional_tasks_screen)
        self.stacked_widget.addWidget(self.install_modlist_screen)
        self.stacked_widget.addWidget(self.install_ttw_screen)
        self.stacked_widget.addWidget(self.configure_new_modlist_screen)
        self.stacked_widget.addWidget(self.wabbajack_installer_screen)
        self.stacked_widget.addWidget(self.configure_existing_modlist_screen)

        self.stacked_widget.currentChanged.connect(self._debug_screen_change)
        self.stacked_widget.currentChanged.connect(self._maintain_fullscreen_on_deck)

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

        version_label = QLabel(f"Jackify v{__version__}")
        version_label.setStyleSheet("color: #bbb; font-size: 13px;")
        bottom_bar_layout.addWidget(version_label, alignment=Qt.AlignLeft)
        bottom_bar_layout.addStretch(1)
        kofi_link = QLabel('<a href="#" style="color:#72A5F2; text-decoration:none;">Support on Ko-fi</a>')
        kofi_link.setStyleSheet("color: #72A5F2; font-size: 13px;")
        kofi_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_link.setOpenExternalLinks(False)
        kofi_link.linkActivated.connect(lambda: self._open_url("https://ko-fi.com/omni1"))
        kofi_link.setToolTip("Support Jackify development")
        bottom_bar_layout.addWidget(kofi_link, alignment=Qt.AlignCenter)
        bottom_bar_layout.addStretch(1)
        settings_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">Settings</a>')
        settings_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        settings_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        settings_btn.setOpenExternalLinks(False)
        settings_btn.linkActivated.connect(self.open_settings_dialog)
        bottom_bar_layout.addWidget(settings_btn, alignment=Qt.AlignRight)
        about_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">About</a>')
        about_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        about_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_btn.setOpenExternalLinks(False)
        about_btn.linkActivated.connect(self.open_about_dialog)
        bottom_bar_layout.addWidget(about_btn, alignment=Qt.AlignRight)

        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(bottom_bar)
        self.stacked_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        self.stacked_widget.setCurrentIndex(0)
        self._check_protontricks_on_startup()

    def _debug_screen_change(self, index):
        try:
            idx = int(index) if index is not None else 0
            widget = self.stacked_widget.widget(idx)
        except (OverflowError, TypeError, ValueError):
            widget = self.stacked_widget.currentWidget()
            idx = None
        if widget and hasattr(widget, 'reset_screen_to_defaults'):
            widget.reset_screen_to_defaults()
        from jackify.backend.handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        if not config_handler.get('debug_mode', False):
            return
        if idx is None:
            return
        try:
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
            screen_name = screen_names.get(idx, f"Unknown Screen (Index {idx})")
            widget = self.stacked_widget.widget(idx)
        except (OverflowError, TypeError, ValueError):
            return
        widget_class = widget.__class__.__name__ if widget else "None"
        print(f"[DEBUG] Screen changed to Index {idx}: {screen_name} (Widget: {widget_class})", file=sys.stderr)
        if idx == 4:
            print("   Install Modlist Screen details:", file=sys.stderr)
            print(f"      - Widget type: {type(widget)}", file=sys.stderr)
            print(f"      - Widget file: {widget.__class__.__module__}", file=sys.stderr)
            if hasattr(widget, 'windowTitle'):
                print(f"      - Window title: {widget.windowTitle()}", file=sys.stderr)
            if hasattr(widget, 'layout'):
                layout = widget.layout()
                if layout:
                    print(f"      - Layout type: {type(layout)}", file=sys.stderr)
                    print(f"      - Layout children count: {layout.count()}", file=sys.stderr)
