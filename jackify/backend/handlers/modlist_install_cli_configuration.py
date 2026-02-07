"""Configuration phase methods for ModlistInstallCLI (Mixin)."""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from .engine_monitor import EnginePerformanceMonitor, create_stall_alert_callback
from .ui_colors import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_INFO,
    COLOR_ERROR,
    COLOR_WARNING,
)

logger = logging.getLogger(__name__)


class ModlistInstallCLIConfigurationMixin:
    """Mixin providing configuration phase methods."""

    def configuration_phase(self):
        """
        Run the configuration phase: execute the Linux-native Jackify Install Engine.
        """
        import subprocess
        import time
        import sys
        from pathlib import Path
        from .modlist_install_cli import get_jackify_engine_path

                            # UI Colors and LoggingHandler already imported at module level
        print(f"\n{COLOR_PROMPT}--- Configuration Phase: Installing Modlist ---{COLOR_RESET}")
        start_time = time.time()

        # --- BEGIN: TEE LOGGING SETUP & LOG ROTATION ---
        from jackify.shared.paths import get_jackify_logs_dir
        log_dir = get_jackify_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        workflow_log_path = log_dir / "Modlist_Install_workflow.log"
        # Log rotation: keep last 3 logs, 1MB each (adjust as needed)
        max_logs = 3
        max_size = 1024 * 1024  # 1MB
        if workflow_log_path.exists() and workflow_log_path.stat().st_size > max_size:
            for i in range(max_logs, 0, -1):
                prev = log_dir / f"Modlist_Install_workflow.log.{i-1}" if i > 1 else workflow_log_path
                dest = log_dir / f"Modlist_Install_workflow.log.{i}"
                if prev.exists():
                    if dest.exists():
                        dest.unlink()
                    prev.rename(dest)
        workflow_log = open(workflow_log_path, 'a')
        class TeeStdout:
            def __init__(self, *files):
                self.files = files
            def write(self, data):
                for f in self.files:
                    f.write(data)
                    f.flush()
            def flush(self):
                for f in self.files:
                    f.flush()
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout = TeeStdout(sys.stdout, workflow_log)
        sys.stderr = TeeStdout(sys.stderr, workflow_log)
        # --- END: TEE LOGGING SETUP & LOG ROTATION ---
        try:
            # --- Process Paths from context ---
            install_dir_context = self.context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]: # Second element is True if creation was intended
                    self.logger.info(f"Creating install directory as it was marked for creation: {actual_install_path}")
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else: # Should be a Path object or string already
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)
            self.logger.debug(f"Processed install directory for engine: {install_dir_str}")

            download_dir_context = self.context['download_dir']
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]: # Second element is True if creation was intended
                    self.logger.info(f"Creating download directory as it was marked for creation: {actual_download_path}")
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else: # Should be a Path object or string already
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)
            self.logger.debug(f"Processed download directory for engine: {download_dir_str}")
            # --- End Process Paths ---

            modlist_arg = self.context.get('modlist_value') or self.context.get('machineid')
            machineid = self.context.get('machineid')
            
            # CRITICAL: Re-check authentication right before launching engine
            # Use current auth state, not stale cached context
            # (e.g., if user revoked OAuth after context was created)
            from jackify.backend.services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            current_api_key, current_oauth_info = auth_service.get_auth_for_engine()
            
            # Use current auth state, fallback to context values only if current check failed
            api_key = current_api_key or self.context.get('nexus_api_key')
            oauth_info = current_oauth_info or self.context.get('nexus_oauth_info')

            # Path to the engine binary
            engine_path = get_jackify_engine_path()
            engine_dir = os.path.dirname(engine_path)
            if not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                print(f"{COLOR_ERROR}Jackify Install Engine not found or not executable at: {engine_path}{COLOR_RESET}")
                return

            # --- Patch for GUI/auto: always set modlist_source to 'identifier' if not set, and ensure modlist_value is present ---
            if os.environ.get('JACKIFY_GUI_MODE') == '1':
                if not self.context.get('modlist_source'):
                    self.context['modlist_source'] = 'identifier'
                if not self.context.get('modlist_value'):
                    self.logger.error("modlist_value is missing in context for GUI workflow!")
                    return
            # --- End Patch ---

            # Build command
            cmd = [engine_path, 'install', '--show-file-progress']

            # Check for debug mode and pass --debug to engine if needed
            from jackify.backend.handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            debug_mode = config_handler.get('debug_mode', False)
            if debug_mode:
                cmd.append('--debug')
                self.logger.info("Debug mode enabled in config - passing --debug flag to jackify-engine")

            # Determine if this is a local .wabbajack file or an online modlist
            modlist_value = self.context.get('modlist_value')
            machineid = self.context.get('machineid')
            
            # Check if there's a cached .wabbajack file for this modlist
            cached_wabbajack_path = None
            if machineid:
                # Convert machineid to filename (e.g., "Tuxborn/Tuxborn" -> "Tuxborn.wabbajack")
                modlist_name = machineid.split('/')[-1] if '/' in machineid else machineid
                from jackify.shared.paths import get_jackify_downloads_dir
                cached_wabbajack_path = get_jackify_downloads_dir() / f"{modlist_name}.wabbajack"
                self.logger.debug(f"Checking for cached .wabbajack file: {cached_wabbajack_path}")
            
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
                self.logger.info(f"Using local .wabbajack file: {modlist_value}")
            elif cached_wabbajack_path and os.path.isfile(cached_wabbajack_path):
                cmd += ['-w', cached_wabbajack_path]
                self.logger.info(f"Using cached .wabbajack file: {cached_wabbajack_path}")
            elif modlist_value:
                cmd += ['-m', modlist_value]
                self.logger.info(f"Using modlist identifier: {modlist_value}")
            elif machineid:
                cmd += ['-m', machineid]
                self.logger.info(f"Using machineid: {machineid}")
            cmd += ['-o', install_dir_str, '-d', download_dir_str]

            # Store original environment values to restore later
            original_env_values = {
                'NEXUS_API_KEY': os.environ.get('NEXUS_API_KEY'),
                'NEXUS_OAUTH_INFO': os.environ.get('NEXUS_OAUTH_INFO'),
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': os.environ.get('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT')
            }

            try:
                # Temporarily modify current process's environment
                # Prefer NEXUS_OAUTH_INFO (supports auto-refresh) over NEXUS_API_KEY (legacy)
                if oauth_info:
                    os.environ['NEXUS_OAUTH_INFO'] = oauth_info
                    # CRITICAL: Set client_id so engine can refresh tokens with correct client_id
                    # Engine's RefreshToken method reads this to use our "jackify" client_id instead of hardcoded "wabbajack"
                    from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                    os.environ['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                    self.logger.debug(f"Set NEXUS_OAUTH_INFO and NEXUS_OAUTH_CLIENT_ID={NexusOAuthService.CLIENT_ID} for engine (supports auto-refresh)")
                    # Also set NEXUS_API_KEY for backward compatibility
                    if api_key:
                        os.environ['NEXUS_API_KEY'] = api_key
                elif api_key:
                    # No OAuth info, use API key only (no auto-refresh support)
                    os.environ['NEXUS_API_KEY'] = api_key
                    self.logger.debug(f"Set NEXUS_API_KEY for engine (no auto-refresh)")
                else:
                    # No auth available, clear any inherited values
                    if 'NEXUS_API_KEY' in os.environ:
                        del os.environ['NEXUS_API_KEY']
                    if 'NEXUS_OAUTH_INFO' in os.environ:
                        del os.environ['NEXUS_OAUTH_INFO']
                    if 'NEXUS_OAUTH_CLIENT_ID' in os.environ:
                        del os.environ['NEXUS_OAUTH_CLIENT_ID']
                    self.logger.debug(f"No Nexus auth available, cleared inherited env vars")

                os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"
                self.logger.debug(f"Temporarily set os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1' for engine call.")

                self.logger.info("Environment prepared for jackify-engine install process by modifying os.environ.")
                self.logger.debug(f"NEXUS_API_KEY in os.environ (pre-call): {'[SET]' if os.environ.get('NEXUS_API_KEY') else '[NOT SET]'}")
                self.logger.debug(f"NEXUS_OAUTH_INFO in os.environ (pre-call): {'[SET]' if os.environ.get('NEXUS_OAUTH_INFO') else '[NOT SET]'}")
                
                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                print(f"{COLOR_INFO}Launching Jackify Install Engine with command:{COLOR_RESET} {pretty_cmd}")
                
                # Temporarily increase file descriptor limit for engine process
                from jackify.backend.handlers.subprocess_utils import increase_file_descriptor_limit
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if success:
                    self.logger.debug(f"File descriptor limit: {message}")
                else:
                    self.logger.warning(f"File descriptor limit: {message}")
                
                # Use cleaned environment to prevent AppImage variable inheritance
                from jackify.backend.handlers.subprocess_utils import get_clean_subprocess_env
                clean_env = get_clean_subprocess_env()
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, env=clean_env, cwd=engine_dir)
                
                # Start performance monitoring for the engine process
                # Adjust monitoring based on debug mode
                if debug_mode:
                    # More aggressive monitoring in debug mode
                    performance_monitor = EnginePerformanceMonitor(
                        logger=self.logger,
                        stall_threshold=5.0,  # CPU below 5% is considered stalled
                        stall_duration=60.0,  # 1 minute of low CPU = stall (faster detection)
                        sample_interval=5.0   # Check every 5 seconds (more frequent)
                    )
                    # Add debug callback for detailed metrics
                    from .engine_monitor import create_debug_callback
                    performance_monitor.add_callback(create_debug_callback(self.logger))
                    self.logger.info("Enhanced performance monitoring enabled for debug mode")
                else:
                    # Standard monitoring
                    performance_monitor = EnginePerformanceMonitor(
                        logger=self.logger,
                        stall_threshold=5.0,  # CPU below 5% is considered stalled
                        stall_duration=120.0,  # 2 minutes of low CPU = stall
                        sample_interval=10.0   # Check every 10 seconds
                    )
                
                # Add callback to alert about performance issues
                def stall_alert(message: str):
                    print(f"\nWarning: {message}")
                    print("If the process appears stuck, you may need to restart it.")
                    if debug_mode:
                        print("Debug mode: Use 'python -m jackify.backend.handlers.diagnostic_helper' for detailed analysis")
                    
                performance_monitor.add_callback(create_stall_alert_callback(self.logger, stall_alert))
                
                # Start monitoring
                monitoring_started = performance_monitor.start_monitoring(proc.pid)
                if monitoring_started:
                    self.logger.info(f"Performance monitoring started for engine PID {proc.pid}")
                else:
                    self.logger.warning("Failed to start performance monitoring")
                
                try:
                    # Read output in binary mode to properly handle carriage returns
                    buffer = b''
                    last_progress_time = time.time()
                    
                    while True:
                        chunk = proc.stdout.read(1)
                        if not chunk:
                            break
                        buffer += chunk
                        
                        # Process complete lines or carriage return updates
                        if chunk == b'\n':
                            # Complete line - decode and print
                            line = buffer.decode('utf-8', errors='replace')
                            # Filter FILE_PROGRESS spam but keep the status line before it
                            if '[FILE_PROGRESS]' in line:
                                parts = line.split('[FILE_PROGRESS]', 1)
                                if parts[0].strip():
                                    line = parts[0].rstrip()
                                else:
                                    # Skip this line entirely if it's only FILE_PROGRESS
                                    buffer = b''
                                    last_progress_time = time.time()
                                    continue
                            # Enhance Nexus download errors with modlist context
                            enhanced_line = self._enhance_nexus_error(line)
                            print(enhanced_line, end='')
                            buffer = b''
                            last_progress_time = time.time()
                        elif chunk == b'\r':
                            # Carriage return - decode and print without newline
                            line = buffer.decode('utf-8', errors='replace')
                            # Filter FILE_PROGRESS spam but keep the status line before it
                            if '[FILE_PROGRESS]' in line:
                                parts = line.split('[FILE_PROGRESS]', 1)
                                if parts[0].strip():
                                    line = parts[0].rstrip()
                                else:
                                    # Skip this line entirely if it's only FILE_PROGRESS
                                    buffer = b''
                                    last_progress_time = time.time()
                                    continue
                            # Enhance Nexus download errors with modlist context
                            enhanced_line = self._enhance_nexus_error(line)
                            print(enhanced_line, end='')
                            sys.stdout.flush()
                            buffer = b''
                            last_progress_time = time.time()
                            
                        # Check for timeout (no output for too long)
                        current_time = time.time()
                        if current_time - last_progress_time > 300:  # 5 minutes no output
                            self.logger.warning("No output from engine for 5 minutes - possible stall")
                            last_progress_time = current_time  # Reset to avoid spam
                    
                    # Print any remaining buffer content
                    if buffer:
                        line = buffer.decode('utf-8', errors='replace')
                        print(line, end='')
                    
                    proc.wait()
                    
                finally:
                    # Stop performance monitoring and get summary
                    if monitoring_started:
                        performance_monitor.stop_monitoring()
                        summary = performance_monitor.get_metrics_summary()
                        
                        if summary:
                            self.logger.info(f"Engine Performance Summary: "
                                           f"Duration: {summary.get('monitoring_duration', 0):.1f}s, "
                                           f"Avg CPU: {summary.get('avg_cpu_percent', 0):.1f}%, "
                                           f"Max Memory: {summary.get('max_memory_mb', 0):.1f}MB, "
                                           f"Stalls: {summary.get('stall_percentage', 0):.1f}%")
                            
                            # Log detailed summary for debugging
                            self.logger.debug(f"Detailed performance summary: {summary}")
                if proc.returncode != 0:
                    print(f"{COLOR_ERROR}Jackify Install Engine exited with code {proc.returncode}.{COLOR_RESET}")
                    self.logger.error(f"Engine exited with code {proc.returncode}.")
                    return # Configuration phase failed
                self.logger.info(f"Engine completed with code {proc.returncode}.")
            except Exception as e:
                print(f"{COLOR_ERROR}Error running Jackify Install Engine: {e}{COLOR_RESET}\n")
                self.logger.error(f"Exception running engine: {e}", exc_info=True)
                return # Configuration phase failed
            finally:
                # Restore original environment state
                for key, original_value in original_env_values.items():
                    current_value_in_os_environ = os.environ.get(key) # Value after Popen and before our restoration for this key

                    # Determine display values for logging, redacting NEXUS_API_KEY
                    display_original_value = f"'[REDACTED]'" if key == 'NEXUS_API_KEY' else f"'{original_value}'"
                    # display_current_value_before_restore = f"'[REDACTED]'" if key == 'NEXUS_API_KEY' else f"'{current_value_in_os_environ}'"

                    if original_value is not None:
                        # Original value existed. We must restore it.
                        if current_value_in_os_environ != original_value:
                            os.environ[key] = original_value
                            self.logger.debug(f"Restored os.environ['{key}'] to its original value: {display_original_value}.")
                        else:
                            # If current value is already the original, ensure it's correctly set (os.environ[key] = original_value is harmless)
                            os.environ[key] = original_value # Ensure it is set
                            self.logger.debug(f"os.environ['{key}'] ('{display_original_value}') matched original value. Ensured restoration.")
                    else:
                        # Original value was None (key was not in os.environ initially).
                        if key in os.environ: # If it's in os.environ now, it means we must have set it or it was set by other means.
                            self.logger.debug(f"Original os.environ['{key}'] was not set. Removing current value ('{'[REDACTED]' if os.environ.get(key) and key == 'NEXUS_API_KEY' else os.environ.get(key)}') that was set for the call.")
                            del os.environ[key]
                        # If original_value was None and key is not in os.environ now, nothing to do.

        except Exception as e:
            print(f"{COLOR_ERROR}Error during Tuxborn installation workflow: {e}{COLOR_RESET}\n")
            self.logger.error(f"Exception in Tuxborn workflow: {e}", exc_info=True)
            return
        finally:
            # --- BEGIN: RESTORE STDOUT/STDERR ---
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            workflow_log.close()
            # --- END: RESTORE STDOUT/STDERR ---

        elapsed = int(time.time() - start_time)
        print(f"\nElapsed time: {elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d} (hh:mm:ss)\n")
        print(f"{COLOR_INFO}Your modlist has been installed to: {install_dir_str}{COLOR_RESET}\n")
        if self.context.get('machineid') != 'Tuxborn/Tuxborn':
            print(f"{COLOR_WARNING}Only Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, and Oblivion Remastered modlists are compatible with Jackify's post-install configuration. Any modlist can be downloaded/installed, but only these games are supported for automated configuration.{COLOR_RESET}")
        # After install, use self.context['modlist_game'] to determine if configuration should be offered
        # After install, detect game type from ModOrganizer.ini
        modorganizer_ini = os.path.join(install_dir_str, "ModOrganizer.ini")
        detected_game = None
        if os.path.isfile(modorganizer_ini):
            from .modlist_handler import ModlistHandler
            handler = ModlistHandler({}, steamdeck=self.steamdeck)
            handler.modlist_ini = modorganizer_ini
            handler.modlist_dir = install_dir_str
            if handler._detect_game_variables():
                detected_game = handler.game_var_full
        supported_games = ["Skyrim Special Edition", "Fallout 4", "Fallout New Vegas", "Oblivion", "Starfield", "Oblivion Remastered", "Enderal"]
        is_tuxborn = self.context.get('machineid') == 'Tuxborn/Tuxborn'
        if (detected_game in supported_games) or is_tuxborn:
            shortcut_name = self.context.get('modlist_name')
            if is_tuxborn and not shortcut_name:
                self.logger.warning("Tuxborn is true, but shortcut_name (modlist_name in context) is missing. Defaulting to 'Tuxborn Automatic Installer'")
                shortcut_name = "Tuxborn Automatic Installer" # Provide a fallback default
            elif not shortcut_name: # For non-Tuxborn, prompt if missing
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Please provide a name for the Steam shortcut for '{self.context.get('modlist_name', 'this modlist')}'.{COLOR_RESET}")
                raw_shortcut_name = input(f"{COLOR_PROMPT}Steam Shortcut Name (or 'q' to cancel): {COLOR_RESET} ").strip()
                if raw_shortcut_name.lower() == 'q' or not raw_shortcut_name:
                    return
                shortcut_name = raw_shortcut_name
            
            # Check if GUI mode to skip interactive prompts
            is_gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            
            if not is_gui_mode:
                # Prompt user if they want to configure Steam shortcut now
                print("\n" + "-" * 28)
                print(f"{COLOR_PROMPT}Would you like to add '{shortcut_name}' to Steam and configure it now?{COLOR_RESET}")
                configure_choice = input(f"{COLOR_PROMPT}Configure now? (Y/n): {COLOR_RESET}").strip().lower()
                
                if configure_choice == 'n':
                    print(f"{COLOR_INFO}Skipping Steam configuration. You can configure it later using 'Configure New Modlist'.{COLOR_RESET}")
                    return
            
            # Proceed with Steam configuration
            self.logger.info(f"Starting Steam configuration for '{shortcut_name}'")
            
            # Step 1: Create Steam shortcut first
            mo2_exe_path = os.path.join(install_dir_str, 'ModOrganizer.exe')
            
            # Use the working shortcut creation process from legacy code
            from .shortcut_handler import ShortcutHandler
            shortcut_handler = ShortcutHandler(steamdeck=self.steamdeck, verbose=False)
            
            # Create nxmhandler.ini to suppress NXM popup
            shortcut_handler.write_nxmhandler_ini(install_dir_str, mo2_exe_path)
            
            # Create shortcut with working NativeSteamService
            from ..services.native_steam_service import NativeSteamService
            steam_service = NativeSteamService()
            
            success, app_id = steam_service.create_shortcut_with_proton(
                app_name=shortcut_name,
                exe_path=mo2_exe_path,
                start_dir=os.path.dirname(mo2_exe_path),
                launch_options="%command%",
                tags=["Jackify"],
                proton_version="proton_experimental"
            )
            
            if not success or not app_id:
                self.logger.error("Failed to create Steam shortcut")
                print(f"{COLOR_ERROR}Failed to create Steam shortcut. Check logs for details.{COLOR_RESET}")
                return
            
            # Step 2: Handle Steam restart and manual steps (if not in GUI mode)
            if not is_gui_mode:
                print(f"\n{COLOR_INFO}Steam shortcut created successfully!{COLOR_RESET}")
                print("Steam needs to restart to detect the new shortcut.")
                
                restart_choice = input("\nRestart Steam automatically now? (Y/n): ").strip().lower()
                if restart_choice == 'n':
                    print("\nPlease restart Steam manually and complete the Proton setup steps.")
                    print("You can configure this modlist later using 'Configure Existing Modlist'.")
                    return
                
                # Restart Steam
                print("\nRestarting Steam...")
                if shortcut_handler.secure_steam_restart():
                    print(f"{COLOR_INFO}Steam restarted successfully.{COLOR_RESET}")
                    
                    # Display manual Proton steps
                    from .menu_handler import ModlistMenuHandler
                    from .config_handler import ConfigHandler
                    config_handler = ConfigHandler()
                    menu_handler = ModlistMenuHandler(config_handler)
                    menu_handler._display_manual_proton_steps(shortcut_name)
                    
                    input(f"\n{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                    
                    # Get the updated AppID after launch
                    new_app_id = shortcut_handler.get_appid_for_shortcut(shortcut_name, mo2_exe_path)
                    if new_app_id and new_app_id.isdigit() and int(new_app_id) > 0:
                        app_id = new_app_id
                    else:
                        print(f"{COLOR_ERROR}Could not find valid AppID after launch. Configuration may not work properly.{COLOR_RESET}")
                else:
                    print(f"{COLOR_ERROR}Steam restart failed. Please restart manually and configure later.{COLOR_RESET}")
                    return
            
            # Step 3: Build configuration context with the AppID
            config_context = {
                'name': shortcut_name,
                'appid': app_id,
                'path': install_dir_str,
                'mo2_exe_path': mo2_exe_path,
                'resolution': self.context.get('resolution'),
                'skip_confirmation': is_gui_mode,
                'manual_steps_completed': not is_gui_mode  # True if we did manual steps above
            }
            
            # Step 4: Use ModlistMenuHandler to run the complete configuration
            from .menu_handler import ModlistMenuHandler
            from .config_handler import ConfigHandler
            
            config_handler = ConfigHandler()
            modlist_menu = ModlistMenuHandler(config_handler)
            
            self.logger.info("Running post-installation configuration phase")
            configuration_success = modlist_menu.run_modlist_configuration_phase(config_context)
            
            if configuration_success:
                self.logger.info("Post-installation configuration completed successfully")

                # Check for TTW integration eligibility
                self._check_and_prompt_ttw_integration(install_dir_str, detected_game, shortcut_name)
            else:
                self.logger.warning("Post-installation configuration had issues")
        else:
            # Game not supported for automated configuration
            print(f"{COLOR_INFO}Modlist installation complete.{COLOR_RESET}")
            if detected_game:
                print(f"{COLOR_WARNING}Detected game '{detected_game}' is not supported for automated Steam configuration.{COLOR_RESET}")
            else:
                print(f"{COLOR_WARNING}Could not detect game type from ModOrganizer.ini for automated configuration.{COLOR_RESET}")
            print(f"{COLOR_INFO}You may need to manually configure the modlist for Steam/Proton.{COLOR_RESET}")

