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
from jackify.frontends.gui.dialogs.settings_dialog import SettingsDialog
from jackify.frontends.gui.mixins.main_window_geometry import MainWindowGeometryMixin
from jackify.frontends.gui.mixins.main_window_backend import MainWindowBackendMixin
from jackify.frontends.gui.mixins.main_window_ui import MainWindowUIMixin
from jackify.frontends.gui.mixins.main_window_startup import MainWindowStartupMixin
from jackify.frontends.gui.mixins.main_window_dialogs import MainWindowDialogsMixin
from jackify.frontends.gui.widgets.feature_placeholder import FeaturePlaceholder

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


class JackifyMainWindow(
    MainWindowGeometryMixin,
    MainWindowBackendMixin,
    MainWindowUIMixin,
    MainWindowStartupMixin,
    MainWindowDialogsMixin,
    QMainWindow,
):
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

    def resizeEvent(self, event):
        self._on_resize_event_geometry(event)

    def showEvent(self, event):
        self._geometry_show_event(event)



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
    # Print Python stack traces on segfault
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
    # DEBUG messages from child loggers must propagate
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