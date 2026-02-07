"""
Modlist menu handler: modlist-specific CLI menu operations.
ModlistMenuHandler class. Lazy-imports MenuHandler to avoid circular import.
"""

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

from .ui_colors import (
    COLOR_PROMPT, COLOR_SELECTION, COLOR_RESET, COLOR_INFO, COLOR_ERROR,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_ACTION, COLOR_INPUT
)
from .modlist_handler import ModlistHandler
from .filesystem_handler import FileSystemHandler
from .path_handler import PathHandler
from .vdf_handler import VDFHandler
from .resolution_handler import ResolutionHandler
from jackify.shared.ui_utils import print_section_header

logger = logging.getLogger(__name__)


class ModlistMenuHandler:
    """Handles modlist-specific menu operations."""

    def __init__(self, config_handler, test_mode=False):
        self.config_handler = config_handler
        self.test_mode = test_mode
        self.exit_flag = False
        self.logger = logging.getLogger(__name__)
        try:
            self.filesystem_handler = FileSystemHandler()
            self.path_handler = PathHandler()
            self.vdf_handler = VDFHandler()
            from ..services.platform_detection_service import PlatformDetectionService
            platform_service = PlatformDetectionService.get_instance()
            self.steamdeck = platform_service.is_steamdeck
            self.resolution_handler = ResolutionHandler()
            from .menu_handler import MenuHandler
            self.menu_handler = MenuHandler()
            self.modlist_handler = ModlistHandler(
                self.config_handler.settings,
                steamdeck=self.steamdeck,
                verbose=False,
                filesystem_handler=self.filesystem_handler
            )
            self.shortcut_handler = self.modlist_handler.shortcut_handler
            self.install_wabbajack_handler = None
        except Exception as e:
            self.logger.error(f"Error initializing ModlistMenuHandler: {e}")
            self.filesystem_handler = FileSystemHandler()
            try:
                from ..services.platform_detection_service import PlatformDetectionService
                platform_service = PlatformDetectionService.get_instance()
                self.steamdeck = platform_service.is_steamdeck
            except Exception:
                self.steamdeck = False
            self.modlist_handler = None

    def show_modlist_menu(self):
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            # Banner display handled by frontend
            print_section_header('Modlist Configuration')
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Configure a New modlist not yet in Steam")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Configure a modlist already in Steam")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            choice = input(f"\n{COLOR_PROMPT}Enter your selection (0-2): {COLOR_RESET}")
            if choice == "1":
                if not self._configure_new_modlist():
                    return False
            elif choice == "2":
                if not self._configure_existing_modlist():
                    return False
            elif choice == "0":
                logger.info("Returning to main menu from Modlist Configuration menu.")
                return False
            else:
                logger.warning(f"Invalid menu selection: {choice}")
                print("\nInvalid selection. Please try again.")
                input("\nPress Enter to continue...")

    def _display_manual_proton_steps(self, modlist_name):
        """Displays the detailed manual steps required for Proton setup."""
        # Keep these as print for clear user instructions
        print(f"\n{COLOR_PROMPT}--- Manual Proton Setup Required ---{COLOR_RESET}") 
        print("Please complete the following steps in Steam:")
        print(f"  1. Locate the '{COLOR_INFO}{modlist_name}{COLOR_RESET}' entry in your Steam Library")
        print("  2. Right-click and select 'Properties'")
        print("  3. Switch to the 'Compatibility' tab")
        print("  4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'")
        print("  5. Select 'Proton - Experimental' from the dropdown menu")
        print("  6. Close the Properties window")
        print(f"  7. Launch '{COLOR_INFO}{modlist_name}{COLOR_RESET}' from your Steam Library")
        print("  8. If Mod Organizer opens or produces any error message, that's normal")
        print("  9. No matter what,CLOSE Mod Organizer completely and return here")
        print(f"{COLOR_PROMPT}------------------------------------{COLOR_RESET}")

    def _get_mo2_path(self) -> Optional[str]:
        """
        Get the path to ModOrganizer.exe from user input.
        Returns the validated path or None if cancelled/invalid.
        """
        self.logger.info("Prompting for ModOrganizer.exe path...")
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}Please provide the path to ModOrganizer.exe for your modlist.{COLOR_RESET}")
        print(f"{COLOR_INFO}This is typically found in the modlist's installation directory.")
        print(f"{COLOR_INFO}Example: ~/Games/MyModlist/ModOrganizer.exe")
        print(f"{COLOR_INFO}You can also provide the path to the directory containing ModOrganizer.exe.")

        # Use the menu_handler's get_existing_file_path for consistency if self.menu_handler is available
        # self.menu_handler is MenuHandler, not ModlistMenuHandler
        if hasattr(self, 'menu_handler') and self.menu_handler is not None:
            # get_existing_file_path will use its own standard prompting style internally
            # We pass no_header=False so it shows its full prompt.
            # The prompt_message here becomes the main instruction for get_existing_file_path.
            path_result = self.menu_handler.get_existing_file_path(
                prompt_message=f"Path to ModOrganizer.exe or its directory",
                extension_filter=".exe",
                no_header=False # Let get_existing_file_path handle its full prompt including separator
            )
            if path_result is None: # User cancelled
                self.logger.info("User cancelled ModOrganizer.exe path input via get_existing_file_path.")
                return None
            
            path_str = str(path_result)
            if os.path.isdir(path_str):
                potential_mo2_path = os.path.join(path_str, "ModOrganizer.exe")
                if os.path.isfile(potential_mo2_path):
                    self.logger.info(f"Found ModOrganizer.exe in directory: {potential_mo2_path}")
                    return potential_mo2_path
                else:
                    print(f"{COLOR_ERROR}ModOrganizer.exe not found in directory: {path_str}{COLOR_RESET}")
                    # Allow to try again - this might need a loop or rely on get_existing_file_path loop
                    return self._get_mo2_path() # Recursive call to try again, simple loop better
            elif os.path.isfile(path_str) and os.path.basename(path_str).lower() == "modorganizer.exe":
                self.logger.info(f"ModOrganizer.exe path validated: {path_str}")
                return path_str
            else:
                print(f"{COLOR_ERROR}Path is not ModOrganizer.exe or a directory containing it.{COLOR_RESET}")
                return self._get_mo2_path() # Recursive call

        # Fallback to basic input if self.menu_handler is not available (should ideally not happen)
        self.logger.warning("_get_mo2_path: self.menu_handler not available, using basic input as fallback.")
        while True:
            try:
                # Basic input prompt if menu_handler isn't used
                mo2_path_input = input(f"{COLOR_PROMPT}Enter path to ModOrganizer.exe (or 'q' to cancel): {COLOR_RESET}").strip()
                if mo2_path_input.lower() == 'q':
                    self.logger.info("User cancelled ModOrganizer.exe path input (fallback).")
                    return None
                
                expanded_path = os.path.expanduser(mo2_path_input)
                normalized_path = os.path.normpath(expanded_path)

                if os.path.isdir(normalized_path):
                    potential_mo2_path = os.path.join(normalized_path, "ModOrganizer.exe")
                    if os.path.isfile(potential_mo2_path):
                        self.logger.info(f"Found ModOrganizer.exe in directory (fallback): {potential_mo2_path}")
                        return potential_mo2_path
                    else:
                        print(f"{COLOR_ERROR}ModOrganizer.exe not found in directory: {normalized_path}{COLOR_RESET}")
                        continue
                
                if not normalized_path.lower().endswith('modorganizer.exe'):
                    print(f"{COLOR_ERROR}Path must be ModOrganizer.exe or a directory containing it.{COLOR_RESET}")
                    continue
                if not os.path.isfile(normalized_path):
                    print(f"{COLOR_ERROR}File does not exist: {normalized_path}{COLOR_RESET}")
                    continue
                
                self.logger.info(f"ModOrganizer.exe path validated (fallback): {normalized_path}")
                return normalized_path
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                self.logger.info("User cancelled ModOrganizer.exe path input via Ctrl+C (fallback).")
                return None
            except Exception as e:
                self.logger.error(f"Error processing ModOrganizer.exe path (fallback): {e}")
                print(f"{COLOR_ERROR}An error occurred: {e}{COLOR_RESET}")
                return None

    def _get_modlist_name(self) -> Optional[str]:
        """
        Get the modlist name from user input.
        Returns the validated name or None if cancelled.
        """
        self.logger.info("Prompting for modlist name...")
        
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}Please provide a name for your modlist.{COLOR_RESET}")
        print(f"{COLOR_INFO}(This will be the name used for the Steam shortcut.){COLOR_RESET}")
        
        while True:
            try:
                modlist_name = input(f"{COLOR_PROMPT}Modlist Name (or 'q' to cancel): {COLOR_RESET}").strip()
                
                if modlist_name.lower() == 'q':
                    self.logger.info("User cancelled modlist name input.")
                    return None
                
                if not modlist_name:
                    print(f"{COLOR_ERROR}Name cannot be empty.{COLOR_RESET}")
                    continue
                    
                if len(modlist_name) > 100: 
                    print(f"{COLOR_ERROR}Name is too long (max 100 characters).{COLOR_RESET}")
                    continue
                    
                invalid_chars = '< > : " / \\ | ? *' # String of invalid chars for message
                if any(char in modlist_name for char in invalid_chars.replace(' ','')):
                    print(f"{COLOR_ERROR}Name contains invalid characters (e.g., {invalid_chars}).{COLOR_RESET}")
                    continue
                
                self.logger.info(f"Modlist name validated: {modlist_name}")
                return modlist_name
                
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                self.logger.info("User cancelled modlist name input via Ctrl+C.")
                return None
            except Exception as e:
                self.logger.error(f"Error processing modlist name: {e}")
                print(f"{COLOR_ERROR}An error occurred: {e}{COLOR_RESET}")
                return None

    def _configure_new_modlist(self, default_modlist_dir=None, default_modlist_name=None):
        """Handle configuration of a new modlist. Returns True to continue menu, False to exit."""
        # --- Get ModOrganizer.exe Path ---
        if default_modlist_dir:
            # Try to infer ModOrganizer.exe path
            mo2_path = os.path.join(default_modlist_dir, "ModOrganizer.exe")
            if not os.path.isfile(mo2_path):
                print(f"{COLOR_ERROR}Could not find ModOrganizer.exe in {default_modlist_dir}{COLOR_RESET}")
                mo2_path = self._get_mo2_path()
        else:
            mo2_path = self._get_mo2_path()
        if not mo2_path:
            return True
        # --- Get Modlist Name ---
        if default_modlist_name:
            modlist_name = default_modlist_name
        else:
            modlist_name = self._get_modlist_name()
        if not modlist_name:
            return True
        # Add a blank line for padding
        print("")
        try:
            # --- Ensure SteamIcons directory is normalized before icon selection ---
            mo2_dir = os.path.dirname(mo2_path)
            # --- Auto-create nxmhandler.ini to suppress NXM Handling popup (MOVED UP) ---
            self.shortcut_handler.write_nxmhandler_ini(mo2_dir, mo2_path)
            steam_icons_path = os.path.join(mo2_dir, "Steam Icons")
            steamicons_path = os.path.join(mo2_dir, "SteamIcons")
            if os.path.isdir(steam_icons_path) and not os.path.isdir(steamicons_path):
                try:
                    os.rename(steam_icons_path, steamicons_path)
                    self.logger.info(f"Renamed 'Steam Icons' to 'SteamIcons' in {mo2_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to rename 'Steam Icons' to 'SteamIcons': {e}")
            self.logger.debug(f"[DEBUG] After normalization, SteamIcons exists: {os.path.isdir(steamicons_path)}")
            # --- Use automated prefix workflow (replaces old manual workflow) ---
            try:
                mo2_dir = os.path.dirname(mo2_path)
                install_dir = mo2_dir
                
                # Use automated prefix service for modern workflow
                print(f"\n{COLOR_INFO}Using automated Steam setup workflow...{COLOR_RESET}")
                
                from ..services.automated_prefix_service import AutomatedPrefixService
                prefix_service = AutomatedPrefixService()
                
                # Define progress callback for CLI with jackify-engine style timestamps
                import time
                start_time = time.time()
                
                def progress_callback(message):
                    elapsed = time.time() - start_time
                    hours = int(elapsed // 3600)
                    minutes = int((elapsed % 3600) // 60)
                    seconds = int(elapsed % 60)
                    timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                    print(f"{COLOR_INFO}{timestamp} {message}{COLOR_RESET}")
                
                # Run the automated workflow
                result = prefix_service.run_working_workflow(
                    modlist_name, install_dir, mo2_path, progress_callback, steamdeck=self.steamdeck
                )
                
                # Handle the result
                if isinstance(result, tuple) and len(result) == 4:
                    if result[0] == "CONFLICT":
                        # Handle conflict - ask user what to do
                        conflicts = result[1]
                        print(f"\n{COLOR_WARNING}Found existing Steam shortcut(s) with the same name and path:{COLOR_RESET}")
                        for i, conflict in enumerate(conflicts, 1):
                            print(f"  {i}. Name: {conflict['name']}")
                            print(f"     Executable: {conflict['exe']}")
                            print(f"     Start Directory: {conflict['startdir']}")
                        print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
                        print("  1. Use existing shortcut (recommended)")
                        print("  2. Create new shortcut anyway")
                        choice = input(f"{COLOR_PROMPT}Enter choice (1-2): {COLOR_RESET}").strip()
                        if choice == "1":
                            # Use existing shortcut
                            existing_appid = conflicts[0].get('appid')
                            if existing_appid:
                                context = {
                                    "name": modlist_name,
                                    "appid": str(existing_appid),
                                    "path": mo2_dir,
                                    "manual_steps_completed": True,
                                    "resolution": None
                                }
                                return self.run_modlist_configuration_phase(context)
                        elif choice == "2":
                            # Create new shortcut - would need to handle this, but for now just fail
                            print(f"{COLOR_ERROR}Creating new shortcut with same name not supported in this flow.{COLOR_RESET}")
                            return True
                        else:
                            print(f"{COLOR_ERROR}Invalid choice.{COLOR_RESET}")
                            return True
                    else:
                        # Success - get the results
                        success, prefix_path, appid_int, last_timestamp = result
                        if success and appid_int:
                            context = {
                                "name": modlist_name,
                                "appid": str(appid_int),
                                "path": mo2_dir,
                                "manual_steps_completed": True,
                                "resolution": None
                            }
                            self.logger.debug(f"[DEBUG] New Modlist Context (automated workflow): {context}")
                            return self.run_modlist_configuration_phase(context)
                        else:
                            print(f"{COLOR_ERROR}Automated workflow completed but no AppID was returned.{COLOR_RESET}")
                            return True
                else:
                    # Unexpected result format
                    print(f"{COLOR_ERROR}Automated workflow returned unexpected format.{COLOR_RESET}")
                    self.logger.error(f"Unexpected result format from automated workflow: {result}")
                    return True
            except Exception as e:
                self.logger.error(f"Error creating Steam shortcut: {e}", exc_info=True)
                print(f"\n{COLOR_ERROR}Failed to create Steam shortcut: {e}{COLOR_RESET}")
                return True
        except Exception as e:
            self.logger.error(f"Error in _configure_new_modlist: {e}", exc_info=True)
            print(f"\n{COLOR_ERROR}Unexpected error in new modlist configuration: {e}{COLOR_RESET}")
            return True

    def _configure_existing_modlist(self):
        """Handle configuration of an existing modlist. Returns True to continue menu, False to exit."""
        logger.info("Detecting installed modlists...")
        try:
            if not self.modlist_handler:
                logger.error("Internal Error: Modlist handler not available.")
                input("\nPress Enter to continue...")
                return True
            configurable_modlists = self.modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
            if not configurable_modlists:
                logger.warning("No configurable ModOrganizer modlists found.")
                print(f"{COLOR_ERROR}\nCould not find any recognized ModOrganizer modlists.{COLOR_RESET}")
                print("Ensure the shortcut exists in Steam, points to ModOrganizer.exe, and has been run once.")
                input(f"\n{COLOR_PROMPT}Press Enter to return to menu...{COLOR_RESET}")
                return True
            selected_modlist_dict = self.select_from_list(configurable_modlists, f"{COLOR_PROMPT}Select Modlist to Configure:{COLOR_RESET}")
            if not selected_modlist_dict:
                logger.info("Modlist selection cancelled by user.")
                return True
            logger.info(f"Setting context for selected modlist: {selected_modlist_dict.get('name')}")
            context = {
                "name": selected_modlist_dict.get("name"),
                "appid": selected_modlist_dict.get("appid"),
                "path": selected_modlist_dict.get("path"),
                "resolution": selected_modlist_dict.get("resolution") if selected_modlist_dict.get("resolution") else None,
                "modlist_source": "existing"  # Mark as existing modlist to skip manual steps
            }
            self.logger.debug(f"[DEBUG] Existing Modlist Context: {context}")
            return self.run_modlist_configuration_phase(context)
        except KeyboardInterrupt:
            print("\nConfiguration cancelled by user.")
            return True
        except Exception as e:
            logger.exception(f"Error configuring existing modlist: {e}", exc_info=True)
            print(f"{COLOR_ERROR}\nAn unexpected error occurred: {str(e)}{COLOR_RESET}")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return True

    def select_from_list(self, items: List[Dict], prompt="Select an option") -> Optional[Dict]:
        """
        Display a list of items (dictionaries) and let the user select one.
        
        Args:
            items: A list of dictionaries, each expected to have at least 'name' and 'appid'.
            prompt: The message to display before the list.
            
        Returns:
            The selected dictionary item or None if cancelled.
        """
        if not items:
            print(f"{COLOR_WARNING}No items available to select from.{COLOR_RESET}")
            return None
        
        print("\n" + "-" * 28) # Separator
        print(f"{COLOR_PROMPT}{prompt}{COLOR_RESET}") # Main prompt message (e.g., "Select Modlist to Configure:")
        
        for i, item_dict in enumerate(items, 1):
            display_name = item_dict.get('name', 'Unknown Item')
            # Optionally display other relevant info if available, e.g., AppID or path
            # For now, keeping it simple with just the name for selection clarity.
            print(f"  {COLOR_SELECTION}{i}.{COLOR_RESET} {display_name}")
        print(f"  {COLOR_SELECTION}0.{COLOR_RESET} Cancel selection") # Added cancel option
        
        while True:
            try:
                choice_input = input(f"{COLOR_PROMPT}Enter your choice (0-{len(items)}): {COLOR_RESET}").strip()
                if choice_input.lower() == 'q' or choice_input == '0': # Allow 'q' or '0' for cancel
                    self.logger.info("User cancelled selection from list.")
                    print(f"{COLOR_INFO}Selection cancelled.{COLOR_RESET}")
                    return None
                if choice_input.isdigit():
                    choice_int = int(choice_input)
                    if 1 <= choice_int <= len(items):
                        return items[choice_int - 1]
                
                print(f"{COLOR_ERROR}Invalid choice. Please enter a number between 0 and {len(items)}.{COLOR_RESET}")
            except ValueError:
                print(f"{COLOR_ERROR}Invalid input. Please enter a number.{COLOR_RESET}")
            except KeyboardInterrupt:
                print("\nSelection cancelled (Ctrl+C).")
                self.logger.info("User cancelled selection from list via Ctrl+C.")
                return None
                
    def run_modlist_configuration_phase(self, context: dict) -> bool:
        """
        Shared configuration phase for both new and existing modlists.
        Expects context dict with keys: name, appid, path (at minimum).
        """
        self.logger.debug(f"[DEBUG] Entering run_modlist_configuration_phase with context: {context}")
        # Robust AppID lookup for GUI/CLI: if appid missing but mo2_exe_path present, look it up
        if 'appid' not in context or not context.get('appid'):
            if 'mo2_exe_path' in context and context['mo2_exe_path']:
                appid = self.shortcut_handler.get_appid_for_shortcut(context['name'], context['mo2_exe_path'])
                if appid:
                    context['appid'] = appid
                else:
                    self.logger.warning(f"[DEBUG] Could not find AppID for {context['name']} with exe {context['mo2_exe_path']}")
        set_modlist_result = self.modlist_handler.set_modlist(context)
        self.logger.debug(f"[DEBUG] set_modlist returned: {set_modlist_result}")

        # Check GUI mode early to avoid input() calls in GUI context
        import os
        gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'

        if not set_modlist_result:
            print(f"{COLOR_ERROR}\nError setting up context for configuration.{COLOR_RESET}")
            self.logger.error(f"set_modlist failed for {context.get('name')}")
            if not gui_mode:
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return False

        # --- Resolution selection logic for GUI mode ---
        selected_resolution = context.get('resolution', None)
        if gui_mode:
            # If resolution is provided, set it and do not prompt
            if selected_resolution:
                self.modlist_handler.selected_resolution = selected_resolution
                self.logger.info(f"[GUI MODE] Resolution set from GUI: {selected_resolution}")
            else:
                # If on Steam Deck, set to 1280x800; else leave unchanged
                if self.steamdeck:
                    self.modlist_handler.selected_resolution = "1280x800"
                    self.logger.info("[GUI MODE] Steam Deck detected, setting resolution to 1280x800.")
                else:
                    self.logger.info("[GUI MODE] No resolution set, leaving unchanged.")
        else:
            # CLI mode: prompt as before
            print()  # Add padding before resolution prompt
            selected_res = self.resolution_handler.select_resolution(steamdeck=self.steamdeck)
            if selected_res:
                self.modlist_handler.selected_resolution = selected_res
                self.logger.info(f"Resolution preference set to: {selected_res}")
            elif self.steamdeck:
                self.modlist_handler.selected_resolution = "1280x800"
                self.logger.info(f"Using default Steam Deck resolution: {self.modlist_handler.selected_resolution}")
            else:
                self.logger.info("User cancelled resolution selection or not applicable.")

        skip_confirmation = context.get('skip_confirmation', False)
        if gui_mode:
            skip_confirmation = True
        if not self.modlist_handler.display_modlist_summary(skip_confirmation=skip_confirmation):
            self.logger.info("User chose not to proceed with configuration after summary.")
            return True

        self.logger.info(f"Starting configuration steps for {context.get('name')}")
        print()  # Add padding before status line
        status_line = ""
        import os
        gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
        def update_status(msg):
            nonlocal status_line
            if status_line:
                print("\r" + " " * len(status_line), end="\r")
            if gui_mode:
                print(msg, flush=True)
            else:
                status_line = f"\r{COLOR_INFO}{msg}{COLOR_RESET}"
                print(status_line, end="", flush=True)
        manual_steps_completed = context.get("manual_steps_completed", False)
        skip_manual_for_existing = context.get("modlist_source") == "existing"  # Existing modlists skip manual steps
        if not self.modlist_handler._execute_configuration_steps(status_callback=update_status, manual_steps_completed=manual_steps_completed, skip_manual_for_existing=skip_manual_for_existing):
            if status_line:
                print()
            self.logger.error(f"Core configuration steps failed for {context.get('name')}")
            print(f"{COLOR_ERROR}\nModlist configuration failed. Check logs for details.{COLOR_RESET}")
            # Only wait for input in CLI mode, not GUI mode
            if not gui_mode:
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return False
        if status_line:
            print()
        
        # Configure ENB for Linux compatibility (non-blocking, same as GUI)
        enb_detected = False
        try:
            from ..handlers.enb_handler import ENBHandler
            from pathlib import Path
            
            enb_handler = ENBHandler()
            install_dir = Path(context.get('path', ''))
            
            if install_dir.exists():
                enb_success, enb_message, enb_detected = enb_handler.configure_enb_for_linux(install_dir)
                
                if enb_message:
                    if enb_success:
                        self.logger.info(enb_message)
                        update_status(enb_message)
                    else:
                        self.logger.warning(enb_message)
                        # Non-blocking: continue workflow even if ENB config fails
        except Exception as e:
            self.logger.warning(f"ENB configuration skipped due to error: {e}")
            # Continue workflow - ENB config is optional

        # Run modlist-specific post-install automation (e.g., VNV) before showing completion
        # Only in CLI mode - GUI handles this in install_modlist.py
        if not gui_mode:
            from jackify.backend.services.vnv_integration_helper import run_vnv_automation_if_applicable
            from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
            from pathlib import Path

            modlist_name = context.get('name', '')
            modlist_path = Path(context.get('path', ''))

            try:
                print("")
                print("Running VNV post-install automation...")
                automation_ran, error = run_vnv_automation_if_applicable(
                    modlist_name=modlist_name,
                    modlist_install_location=modlist_path,
                    game_root=None,  # Will be auto-detected
                    ttw_installer_path=AutomatedPrefixService.get_ttw_installer_path(),
                    progress_callback=lambda msg: print(msg),
                    manual_file_callback=None,  # CLI doesn't support manual file callback yet
                    confirmation_callback=None  # Will use default confirmation in CLI
                )
                if error:
                    print(f"{COLOR_WARNING}VNV automation encountered an error: {error}{COLOR_RESET}")
                    print(f"{COLOR_INFO}You can complete these steps manually by following: https://vivanewvegas.moddinglinked.com/wabbajack.html{COLOR_RESET}")
            except Exception as e:
                self.logger.debug(f"VNV automation check skipped: {e}")
                # Not an error - just means VNV automation wasn't applicable

        print("")
        print("")
        print("")  # Extra blank line before completion
        print("=" * 35)
        print("= Configuration phase complete =")
        print("=" * 35)
        print("")
        print("Modlist Install and Configuration complete!")
        print(f"• You should now be able to Launch '{context.get('name')}' through Steam")
        print("• Congratulations and enjoy the game!")
        print("")
        
        # Show ENB-specific warning if ENB was detected (replaces generic note)
        if enb_detected:
            print(f"{COLOR_WARNING}ENB DETECTED{COLOR_RESET}")
            print("")
            print("If you plan on using ENB as part of this modlist, you will need to use")
            print("one of the following Proton versions, otherwise you will have issues:")
            print("")
            print("  (in order of recommendation)")
            print(f"  {COLOR_SUCCESS}• Proton-CachyOS{COLOR_RESET}")
            print(f"  {COLOR_INFO}• GE-Proton 10-14 or lower{COLOR_RESET}")
            print(f"  {COLOR_WARNING}• Proton 9 from Valve{COLOR_RESET}")
            print("")
            print(f"{COLOR_WARNING}Note: Valve's Proton 10 has known ENB compatibility issues.{COLOR_RESET}")
            print("")
        else:
            # No ENB detected - no warning needed
            pass
        from jackify.shared.paths import get_jackify_logs_dir
        print(f"Detailed log available at: {get_jackify_logs_dir()}/Configure_New_Modlist_workflow.log")
        # Only wait for input in CLI mode, not GUI mode
        if not gui_mode:
            input(f"{COLOR_PROMPT}Press Enter to return to the menu...{COLOR_RESET}")
        return True
