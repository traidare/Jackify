"""Steam restart methods for ShortcutHandler (Mixin)."""
import logging
import os
import subprocess
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def _resolve_steam_exe():
    """Resolve steam executable for legacy restart path (same logic as steam_restart_service)."""
    try:
        from jackify.backend.services.steam_restart_service import _get_steam_executable
        return _get_steam_executable(os.environ)
    except Exception:
        import shutil
        exe = shutil.which("steam")
        if exe:
            return exe
        for p in ("/usr/games/steam", "/usr/bin/steam"):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return "steam"


class ShortcutSteamRestartMixin:
    """Mixin providing Steam restart methods."""

    def secure_steam_restart(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Secure Steam restart with comprehensive error handling to prevent segfaults.
        Now delegates to the robust steam restart service for cross-distro compatibility.
        """
        try:
            from ..services.steam_restart_service import robust_steam_restart
            return robust_steam_restart(progress_callback=status_callback, timeout=60)
        except ImportError as e:
            self.logger.error(f"Failed to import steam restart service: {e}")
            return self._legacy_secure_steam_restart(status_callback)
        except Exception as e:
            self.logger.error(f"Error in robust steam restart: {e}")
            return self._legacy_secure_steam_restart(status_callback)

    def _legacy_secure_steam_restart(self, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Legacy secure Steam restart implementation (fallback).
        """
        self.logger.info("Attempting secure Steam restart sequence...")

        def safe_subprocess_run(cmd, **kwargs):
            try:
                return subprocess.run(cmd, **kwargs)
            except Exception as e:
                self.logger.error(f"Subprocess error with cmd {cmd}: {e}")
                return subprocess.CompletedProcess(cmd, 1, "", str(e))

        def safe_subprocess_popen(cmd, **kwargs):
            try:
                return subprocess.Popen(cmd, **kwargs)
            except Exception as e:
                self.logger.error(f"Popen error with cmd {cmd}: {e}")
                return None

        if self._is_steam_deck():
            self.logger.info("Detected Steam Deck. Using systemd to restart Steam.")
            if status_callback:
                try:
                    status_callback("Restarting Steam via systemd...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")

            try:
                result = safe_subprocess_run(['systemctl', '--user', 'restart', 'app-steam@autostart.service'], capture_output=True, text=True, timeout=30)
                self.logger.info(f"systemctl restart output: {result.stdout.strip()} {result.stderr.strip()}")
                time.sleep(10)
                check = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                if check.returncode == 0:
                    self.logger.info("Steam restarted successfully via systemd.")
                    if status_callback:
                        try:
                            status_callback("Steam Started")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return True
                else:
                    self.logger.error("Steam did not start after systemd restart.")
                    if status_callback:
                        try:
                            status_callback("Start Failed")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return False
            except Exception as e:
                self.logger.error(f"Error restarting Steam via systemd: {e}")
                if status_callback:
                    try:
                        status_callback("Restart Failed")
                    except Exception as e:
                        self.logger.warning(f"Status callback error: {e}")
                return False

        try:
            if status_callback:
                try:
                    status_callback("Stopping Steam...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")

            self.logger.info("Attempting clean Steam shutdown via 'steam -shutdown'...")
            shutdown_timeout = 30
            result = safe_subprocess_run(['steam', '-shutdown'], timeout=shutdown_timeout, check=False, capture_output=True, text=True)
            if result.returncode != 1:
                self.logger.debug("'steam -shutdown' command executed (exit code ignored, verification follows).")
            else:
                self.logger.warning(f"'steam -shutdown' had issues: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Error executing 'steam -shutdown': {e}. Will proceed to check processes.")

        if status_callback:
            try:
                status_callback("Waiting for Steam to close...")
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")

        self.logger.info("Verifying Steam processes are terminated...")
        max_attempts = 6
        steam_closed_successfully = False

        for attempt in range(max_attempts):
            try:
                check_cmd = ['pgrep', '-f', 'steamwebhelper']
                self.logger.debug(f"Executing check: {' '.join(check_cmd)}")
                result = safe_subprocess_run(check_cmd, capture_output=True, timeout=10)
                if result.returncode != 0:
                    self.logger.info("No Steam web helper processes found via pgrep.")
                    steam_closed_successfully = True
                    break
                else:
                    try:
                        steam_pids = result.stdout.decode().strip().split('\n') if result.stdout else []
                        self.logger.debug(f"Steam web helper processes still detected (PIDs: {steam_pids}). Waiting... (Attempt {attempt + 1}/{max_attempts} after shutdown cmd)")
                    except Exception as e:
                        self.logger.warning(f"Error parsing pgrep output: {e}")
                    time.sleep(5)
            except Exception as e:
                self.logger.warning(f"Error checking Steam processes (attempt {attempt + 1}): {e}")
                time.sleep(5)

        if not steam_closed_successfully:
            self.logger.debug("Steam processes still running after 'steam -shutdown'. Attempting fallback with 'pkill steam'...")
            if status_callback:
                try:
                    status_callback("Force stopping Steam...")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")

            try:
                self.logger.info("Attempting force shutdown via 'pkill steam'...")
                pkill_result = safe_subprocess_run(['pkill', '-f', 'steam'], timeout=15, check=False, capture_output=True, text=True)
                self.logger.info(f"pkill steam result: {pkill_result.returncode} - {pkill_result.stdout.strip()} {pkill_result.stderr.strip()}")

                time.sleep(3)

                final_check = safe_subprocess_run(['pgrep', '-f', 'steamwebhelper'], capture_output=True, timeout=10)
                if final_check.returncode != 0:
                    self.logger.info("Steam processes successfully terminated via pkill fallback.")
                    steam_closed_successfully = True
                else:
                    self.logger.debug("Steam processes still running after pkill fallback.")
                    if status_callback:
                        try:
                            status_callback("Shutdown Failed")
                        except Exception as e:
                            self.logger.warning(f"Status callback error: {e}")
                    return False

            except Exception as e:
                self.logger.error(f"Error during pkill fallback: {e}")
                if status_callback:
                    try:
                        status_callback("Shutdown Failed")
                    except Exception as e:
                        self.logger.warning(f"Status callback error: {e}")
                return False

        if not steam_closed_successfully:
            self.logger.error("Failed to terminate Steam processes via all methods.")
            if status_callback:
                try:
                    status_callback("Shutdown Failed")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            return False

        self.logger.info("Steam confirmed closed.")

        steam_exe = _resolve_steam_exe()
        start_methods = [
            {"name": "Popen", "cmd": [steam_exe, "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True}},
            {"name": "setsid", "cmd": ["setsid", steam_exe, "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}},
            {"name": "nohup", "cmd": ["nohup", steam_exe, "-silent"], "kwargs": {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "start_new_session": True}}
        ]
        steam_start_initiated = False

        for i, method in enumerate(start_methods):
            method_name = method["name"]
            status_msg = f"Starting Steam ({method_name})"
            if status_callback:
                try:
                    status_callback(status_msg)
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")

            self.logger.info(f"Attempting to start Steam using method: {method_name}")
            try:
                process = safe_subprocess_popen(method["cmd"], **method["kwargs"])
                if process is not None:
                    self.logger.info(f"Initiated Steam start with {method_name}.")
                    time.sleep(5)
                    check_result = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                    if check_result.returncode == 0:
                        self.logger.info(f"Steam process detected after using {method_name}. Proceeding to wait phase.")
                        steam_start_initiated = True
                        break
                    else:
                        self.logger.warning(f"Steam process not detected after initiating with {method_name}. Trying next method.")
                else:
                    self.logger.warning(f"Failed to start process with {method_name}. Trying next method.")
            except FileNotFoundError:
                self.logger.error(f"Command not found for method {method_name} (e.g., setsid, nohup). Trying next method.")
            except Exception as e:
                self.logger.error(f"Error starting Steam with {method_name}: {e}. Trying next method.")

        if not steam_start_initiated:
            self.logger.error("All methods to initiate Steam start failed.")
            if status_callback:
                try:
                    status_callback("Start Failed")
                except Exception as e:
                    self.logger.warning(f"Status callback error: {e}")
            return False

        status_msg = "Waiting for Steam to fully start"
        if status_callback:
            try:
                status_callback(status_msg)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")

        self.logger.info("Waiting up to 2 minutes for Steam to fully initialize...")
        max_startup_wait = 120
        elapsed_wait = 0
        initial_wait_done = False

        while elapsed_wait < max_startup_wait:
            try:
                result = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                if result.returncode == 0:
                    if not initial_wait_done:
                        self.logger.info("Steam process detected. Waiting additional time for full initialization...")
                        initial_wait_done = True
                    time.sleep(5)
                    elapsed_wait += 5
                    if initial_wait_done and elapsed_wait >= 15:
                        final_check = safe_subprocess_run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
                        if final_check.returncode == 0:
                            if status_callback:
                                try:
                                    status_callback("Steam Started")
                                except Exception as e:
                                    self.logger.warning(f"Status callback error: {e}")
                            self.logger.info("Steam confirmed running after wait.")
                            return True
                        else:
                            self.logger.warning("Steam process disappeared during final initialization wait.")
                            break
                else:
                    self.logger.debug(f"Steam process not yet detected. Waiting... ({elapsed_wait + 5}s)")
                    time.sleep(5)
                    elapsed_wait += 5
            except Exception as e:
                self.logger.warning(f"Error during Steam startup wait: {e}")
                time.sleep(5)
                elapsed_wait += 5

        self.logger.error("Steam failed to start/initialize within the allowed time.")
        if status_callback:
            try:
                status_callback("Start Timed Out")
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        return False
