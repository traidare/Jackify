"""Workflow methods for AutomatedPrefixService (Mixin)."""
from pathlib import Path
from typing import Optional, Union, List, Dict, Tuple
import logging
import os
import time
import subprocess
import vdf

logger = logging.getLogger(__name__)


def debug_print(message):
    """Log debug message only if debug mode is enabled"""
    from jackify.backend.handlers.config_handler import ConfigHandler
    config_handler = ConfigHandler()
    if config_handler.get('debug_mode', False):
        logger.debug(message)


class WorkflowMixin:
    """Mixin providing workflow methods for AutomatedPrefixService."""

    def handle_existing_shortcut_conflict(self, shortcut_name: str, exe_path: str, modlist_install_dir: str) -> Union[bool, List[Dict]]:
        """
        Check for existing shortcut with same name and path, prompt user if found.
        
        Args:
            shortcut_name: Name of the shortcut to create
            exe_path: Path to the executable
            modlist_install_dir: Directory where the modlist is installed
            
        Returns:
            True if we should proceed (no conflict or user chose to replace), False if user cancelled
        """
        try:
            shortcuts_path = self._get_shortcuts_path()
            if not shortcuts_path:
                return True  # No shortcuts file, no conflict
            
            with open(shortcuts_path, 'rb') as f:
                shortcuts_data = vdf.binary_load(f)
            
            shortcuts = shortcuts_data.get('shortcuts', {})
            conflicts = []
            
            # Look for shortcuts with the same name AND path
            for i in range(len(shortcuts)):
                shortcut = shortcuts[str(i)]
                name = shortcut.get('AppName', '')
                shortcut_exe = shortcut.get('Exe', '').strip('"')  # Remove quotes
                shortcut_startdir = shortcut.get('StartDir', '').strip('"')  # Remove quotes
                
                # Check if name matches AND (exe path matches OR startdir matches)
                # Use exact name match instead of partial match to avoid false positives
                name_matches = shortcut_name == name
                exe_matches = shortcut_exe == exe_path
                startdir_matches = shortcut_startdir == modlist_install_dir
                
                if (name_matches and (exe_matches or startdir_matches)):
                    conflicts.append({
                        'index': i,
                        'name': name,
                        'exe': shortcut_exe,
                        'startdir': shortcut_startdir
                    })
            
            if conflicts:
                logger.warning(f"Found {len(conflicts)} existing shortcut(s) with same name and path")
                
                # Log details about each conflict for debugging
                for i, conflict in enumerate(conflicts):
                    logger.info(f"Conflict {i+1}: Name='{conflict['name']}', Exe='{conflict['exe']}', StartDir='{conflict['startdir']}'")
                
                # Return the conflict information so the frontend can handle it
                return conflicts
            else:
                logger.debug("No conflicting shortcuts found")
                return True
                
        except Exception as e:
            logger.error(f"Error handling shortcut conflict: {e}")
            return True  # Proceed on error to avoid blocking

    def format_conflict_message(self, conflicts: List[Dict]) -> str:
        """
        Format conflict information into a user-friendly message.
        
        Args:
            conflicts: List of conflict dictionaries from handle_existing_shortcut_conflict
            
        Returns:
            Formatted message for the user
        """
        if not conflicts:
            return "No conflicts found."
        
        message = f"Found {len(conflicts)} existing Steam shortcut(s) with the same name and path:\n\n"
        
        for i, conflict in enumerate(conflicts, 1):
            message += f"{i}. **Name:** {conflict['name']}\n"
            message += f"   **Executable:** {conflict['exe']}\n"
            message += f"   **Start Directory:** {conflict['startdir']}\n\n"
        
        message += "**Options:**\n"
        message += "• **Replace** - Remove the existing shortcut and create a new one\n"
        message += "• **Cancel** - Keep the existing shortcut and stop the installation\n"
        message += "• **Skip** - Continue without creating a Steam shortcut\n\n"
        message += "The existing shortcut will be removed if you choose to replace it."
        
        return message

    def run_complete_workflow(self, shortcut_name: str, modlist_install_dir: str, 
                            final_exe_path: str, progress_callback=None) -> Tuple[bool, Optional[Path], Optional[int]]:
        """
        Run the simple automated prefix creation workflow.
        
        Args:
            shortcut_name: Name for the Steam shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to ModOrganizer.exe
            
        Returns:
            Tuple of (success, prefix_path, appid)
        """
        debug_print(f"[DEBUG] run_complete_workflow called with shortcut_name={shortcut_name}, modlist_install_dir={modlist_install_dir}, final_exe_path={final_exe_path}")
        logger.info("Starting simple automated prefix creation workflow")
        
        # Initialize shared timing to continue from jackify-engine
        from jackify.shared.timing import initialize_from_console_output
        # TODO: Pass console output if available to continue timeline
        initialize_from_console_output()
        
        # Show immediate feedback to user
        if progress_callback:
            progress_callback("Starting automated Steam setup...")
        
        try:
            # Step 1: Create shortcut directly (NO STL needed!)
            logger.info("Step 1: Creating shortcut directly to ModOrganizer.exe")
            if progress_callback:
                progress_callback("Creating Steam shortcut...")
            if not self.create_shortcut_directly_with_proton(shortcut_name, final_exe_path, modlist_install_dir):
                logger.error("Failed to create shortcut directly")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shortcut created successfully")
            logger.info("Step 1 completed: Shortcut created directly")
            
            # Step 2: Calculate the predictable AppID and rungameid
            logger.info("Step 2: Calculating predictable AppID")
            if progress_callback:
                progress_callback("Calculating AppID...")
            
            # Calculate AppID using the same method as create_shortcut_directly_with_proton
            from zlib import crc32
            combined_string = final_exe_path + shortcut_name
            crc = crc32(combined_string.encode('utf-8'))
            initial_appid = -(crc & 0x7FFFFFFF)  # Make it negative and within 32-bit range
            
            # Calculate rungameid for launching
            rungameid = (initial_appid << 32) | 0x02000000
            
            # Convert AppID to positive prefix ID
            expected_prefix_id = str(abs(initial_appid))
            
            if progress_callback:
                progress_callback("AppID calculated")
            logger.info(f"Step 2 completed: AppID = {initial_appid}, rungameid = {rungameid}, expected_prefix_id = {expected_prefix_id}")
            
            # Step 3: Restart Steam
            logger.info("Step 3: Restarting Steam")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            logger.info("Step 3 completed: Steam restarted")
            
            # Step 4: Launch temporary batch file to create prefix invisibly
            logger.info("Step 4: Launching temporary batch file to create prefix")
            debug_print(f"[DEBUG] About to launch temporary batch file with rungameid={rungameid}")
            
            # Launch using rungameid (this will run the batch file invisibly)
            try:
                result = subprocess.run(['steam', f'steam://rungameid/{rungameid}'], 
                                      capture_output=True, text=True, timeout=5)
                debug_print(f"[DEBUG] Launch result: return_code={result.returncode}")
                if result.returncode != 0:
                    logger.error(f"Failed to launch temporary batch file: {result.stderr}")
                    return False, None, None, None
            except subprocess.TimeoutExpired:
                debug_print("[DEBUG] Launch timed out (expected)")
            except Exception as e:
                logger.error(f"Error launching temporary batch file: {e}")
                return False, None, None, None
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Temporary batch file launched")
            logger.info("Step 4 completed: Temporary batch file launched")
            
            # Step 5: Wait for temporary batch file to complete (invisible)
            logger.info("Step 5: Waiting for temporary batch file to complete")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix (please wait)...")
            
            # Wait for batch file to complete (3 seconds + buffer)
            time.sleep(5)
            logger.info("Step 5 completed: Temporary batch file completed")
            
            # Step 6: Verify prefix was created
            logger.info("Step 6: Verifying prefix creation")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying prefix creation...")
            
            compatdata_path = Path.home() / ".local/share/Steam/steamapps/compatdata" / expected_prefix_id
            if not compatdata_path.exists():
                logger.error(f"Prefix not found at {compatdata_path}")
                return False, None, None, None
            
            logger.info(f"Step 6 completed: Prefix verified at {compatdata_path}")
            
            # Step 7: Replace temporary batch file with final ModOrganizer.exe
            logger.info("Step 7: Replacing temporary batch file with final ModOrganizer.exe")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Updating shortcut...")
            
            if not self.replace_shortcut_with_final_exe(shortcut_name, final_exe_path, modlist_install_dir):
                logger.error("Failed to replace shortcut with final exe")
                return False, None, None, None
            
            logger.info("Step 7 completed: Shortcut updated with final ModOrganizer.exe")
            
            # Step 8: Detect actual AppID using protontricks -l
            logger.info("Step 8: Detecting actual AppID")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Detecting actual AppID...")
            actual_appid = self.detect_actual_prefix_appid(initial_appid, shortcut_name)
            if actual_appid is None:
                logger.error("Failed to detect actual AppID")
                return False, None, None, None
            logger.info(f"Step 8 completed: Actual AppID = {actual_appid}")
            
            # Step 9: Verify prefix was created successfully
            logger.info("Step 9: Verifying prefix creation")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying prefix creation...")
            prefix_path = self._get_compatdata_path_for_appid(actual_appid)
            if not prefix_path or not prefix_path.exists():
                logger.error(f"Prefix path not found: {prefix_path}")
                return False, None, None, None
            
            if not self.verify_prefix_creation(prefix_path):
                logger.error("Prefix verification failed")
                return False, None, None, None
            logger.info(f"Step 9 completed: Prefix verified at {prefix_path}")
            
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam Configuration complete!")
            # Show Proton override notification if applicable
            self._show_proton_override_notification(progress_callback)

            logger.info(" Simple automated prefix creation workflow completed successfully")
            return True, prefix_path, actual_appid
            
        except Exception as e:
            logger.error(f"Error in automated prefix creation workflow: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False, None, None, None

    def run_working_workflow(self, shortcut_name: str, modlist_install_dir: str,
                            final_exe_path: str, progress_callback=None, steamdeck: Optional[bool] = None,
                            download_dir=None, auto_restart: bool = True) -> Tuple[bool, Optional[Path], Optional[int], Optional[str]]:
        """
        Run the proven working automated prefix creation workflow.

        This implements our tested and working approach:
        1. Create shortcut with native Steam service (pointing to ModOrganizer.exe initially)
        2. Restart Steam using Jackify's robust method
        3. Create Proton prefix invisibly using Proton wrapper with DISPLAY=
        4. Verify everything persists

        Args:
            shortcut_name: Name for the Steam shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to ModOrganizer.exe
            progress_callback: Optional callback for progress updates
            steamdeck: Optional Steam Deck detection override
            download_dir: Optional download path; its mountpoint is added to STEAM_COMPAT_MOUNTS
            auto_restart: If True, automatically restart Steam. If False, skip restart step.

        Returns:
            Tuple of (success, prefix_path, appid, last_timestamp)
        """
        logger.info("Starting proven working automated prefix creation workflow")
        
        # Show installation complete and configuration start headers FIRST
        if progress_callback:
            progress_callback("")
            progress_callback("=" * 64)
            progress_callback("= Installation phase complete =")
            progress_callback("=" * 64)
            progress_callback("")
            progress_callback("=" * 64)
            progress_callback("= Starting Configuration Phase =")
            progress_callback("=" * 64)
            progress_callback("")
        
        # Reset timing for Steam Integration section (part of Configuration Phase)
        from jackify.shared.timing import start_new_phase
        start_new_phase()
        
        # Show immediate feedback to user with section header
        if progress_callback:
            progress_callback("")  # Blank line before Steam Integration
            progress_callback("=== Steam Integration ===")
            progress_callback(f"{self._get_progress_timestamp()} Creating Steam shortcut with native service")
        
        # Registry injection approach for both FNV and Enderal
        from ..handlers.modlist_handler import ModlistHandler
        modlist_handler = ModlistHandler()
        special_game_type = modlist_handler.detect_special_game_type(modlist_install_dir)

        # No launch options needed - both FNV and Enderal use registry injection
        custom_launch_options = None
        if special_game_type in ["fnv", "enderal"]:
            logger.info(f"Using registry injection approach for {special_game_type.upper()} modlist")
        else:
            logger.debug("Standard modlist - no special game handling needed")
        
        try:
            # Step 0: Shut down Steam before modifying VDF files
            # Required to safely modify shortcuts.vdf and config.vdf without race conditions
            logger.info("Step 0: Shutting down Steam before modifying VDF files")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Shutting down Steam...")

            from .steam_restart_service import shutdown_steam
            try:
                if not shutdown_steam():
                    logger.warning("Steam shutdown returned False, continuing anyway")
            except Exception as e:
                logger.warning(f"Steam shutdown failed: {e}, continuing anyway")

            logger.info("Step 0 completed: Steam shut down")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shut down")

            # Step 1: Create shortcut with native Steam service (Steam is now shut down)
            logger.info("Step 1: Creating shortcut with native Steam service")

            # DISABLED: Shortcut conflict detection temporarily disabled pending rework
            # Re-enable after conflict resolution workflow refactor
            # When re-enabled, this will detect and handle cases where shortcuts with the same
            # name and path already exist in Steam, allowing users to resolve conflicts
            # Disabled pending workflow improvements - planned for future release
            # conflict_result = self.handle_existing_shortcut_conflict(shortcut_name, final_exe_path, modlist_install_dir)
            # if isinstance(conflict_result, list):  # Conflicts found
            #     logger.warning(f"Found {len(conflict_result)} existing shortcut(s) with same name and path")
            #     # Return a special tuple to indicate conflict that needs user resolution
            #     return ("CONFLICT", conflict_result, None)
            # elif not conflict_result:  # User cancelled or other failure
            #     logger.error("User cancelled due to shortcut conflict")
            #     return False, None, None, None
            logger.info("Conflict detection temporarily disabled - proceeding with shortcut creation")

            # Create shortcut using native Steam service with special game launch options
            success, appid = self.create_shortcut_with_native_service(
                shortcut_name, final_exe_path, modlist_install_dir, custom_launch_options, download_dir=download_dir
            )
            if not success:
                logger.error("Failed to create shortcut with native Steam service")
                return False, None, None, None
            
            logger.info(f"Step 1 completed: Shortcut created with native service, AppID: {appid}")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam shortcut created successfully")
            
            # Apply Steam artwork if available
            try:
                from ..handlers.modlist_handler import ModlistHandler
                modlist_handler = ModlistHandler()
                modlist_handler.set_steam_grid_images(str(appid), modlist_install_dir)
                logger.info(f"Applied Steam artwork for shortcut '{shortcut_name}' (AppID: {appid})")
            except Exception as e:
                logger.warning(f"Failed to apply Steam artwork: {e}")
            
            # Step 2: Start Steam (if auto_restart enabled)
            logger.info("Step 2: auto_restart=%s", auto_restart)
            if auto_restart:
                logger.info("Step 2: Starting Steam using Jackify's robust method")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Starting Steam...")

                restart_ok = self.restart_steam()
                logger.info("Step 2: restart_steam() returned %s", restart_ok)
                if not restart_ok:
                    logger.error("Failed to start Steam")
                    return False, None, None, None

                logger.info("Step 2 completed: Steam started")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Steam started successfully")
            else:
                logger.info("Step 2 skipped: Auto-restart disabled by user")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Steam restart skipped (auto-restart disabled)")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                return False, None, None, None
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Step 5: Inject game registry entries for FNV and Enderal modlists
            # Get prefix path (needed for logging regardless of game type)
            prefix_path = self.get_prefix_path(appid)

            if special_game_type in ["fnv", "enderal"]:
                logger.info(f"Step 5: Injecting {special_game_type.upper()} game registry entries")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} Injecting {special_game_type.upper()} game registry entries...")

                if prefix_path:
                    self._inject_game_registry_entries(str(prefix_path), special_game_type)
                else:
                    logger.warning("Could not find prefix path for registry injection")
            else:
                logger.info("Step 5: Skipping registry injection for standard modlist")
                if progress_callback:
                    progress_callback(f"{self._get_progress_timestamp()} No special game registry injection needed")

            # Step 5.5: Pre-create game-specific directories for all modlists
            logger.info(f"Step 5.5: Creating game-specific user directories")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating game user directories...")

            if prefix_path:
                self._create_game_user_directories(str(prefix_path), special_game_type)
            else:
                logger.warning("Could not find prefix path for directory creation")
            
            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Working workflow completed successfully! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Steam integration complete")
                progress_callback("")  # Blank line after Steam integration complete

            # Show Proton override notification if applicable
            self._show_proton_override_notification(progress_callback)

            if progress_callback:
                progress_callback("")  # Extra blank line to span across Configuration Summary
                progress_callback("")  # And one more to create space before Prefix Configuration

            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error in working workflow: {e}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return False, None, None, None

    def continue_workflow_after_conflict_resolution(self, shortcut_name: str, modlist_install_dir: str, 
                                                  final_exe_path: str, appid: int, progress_callback=None) -> Tuple[bool, Optional[Path], Optional[int]]:
        """
        Continue the workflow after a shortcut conflict has been resolved.
        
        Args:
            shortcut_name: Name of the shortcut
            modlist_install_dir: Directory where the modlist is installed
            final_exe_path: Path to the final executable
            appid: The AppID of the shortcut that was created/replaced
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (success, prefix_path, appid)
        """
        try:
            logger.info("Continuing workflow after conflict resolution")
            
            # Step 2: Restart Steam using Jackify's robust method
            logger.info("Step 2: Restarting Steam using Jackify's robust method")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Restarting Steam...")
            
            if not self.restart_steam():
                logger.error("Failed to restart Steam")
                return False, None, None, None
            
            logger.info("Step 2 completed: Steam restarted")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Steam restarted successfully")
            
            # Step 3: Create Proton prefix invisibly using Proton wrapper
            logger.info("Step 3: Creating Proton prefix invisibly")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Creating Proton prefix...")
            
            if not self.create_prefix_with_proton_wrapper(appid):
                logger.error("Failed to create Proton prefix")
                return False, None, None, None
            
            logger.info("Step 3 completed: Proton prefix created")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Proton prefix created successfully")
            
            # Step 4: Verify everything persists
            logger.info("Step 4: Verifying compatibility tool persists")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Verifying setup...")
            
            if not self.verify_compatibility_tool_persists(appid):
                logger.warning("Compatibility tool verification failed, but continuing")
            
            logger.info("Step 4 completed: Verification done")
            if progress_callback:
                progress_callback(f"{self._get_progress_timestamp()} Setup verification completed")
            
            # Get the prefix path
            prefix_path = self.get_prefix_path(appid)
            
            last_timestamp = self._get_progress_timestamp()
            logger.info(f" Workflow completed successfully after conflict resolution! AppID: {appid}, Prefix: {prefix_path}")
            if progress_callback:
                progress_callback(f"{last_timestamp} Automated Steam setup completed successfully!")
            
            return True, prefix_path, appid, last_timestamp
            
        except Exception as e:
            logger.error(f"Error continuing workflow after conflict resolution: {e}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}")
            return False, None, None, None

