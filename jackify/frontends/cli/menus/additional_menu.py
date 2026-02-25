"""
Additional Tasks Menu Handler for Jackify CLI Frontend
Extracted from src.modules.menu_handler.MenuHandler.show_additional_tasks_menu()
"""

import time

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT, COLOR_INFO, COLOR_DISABLED, COLOR_WARNING
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen

class AdditionalMenuHandler:
    """
    Handles the Additional Tasks menu (MO2, NXM Handling & Recovery)
    Extracted from legacy MenuHandler class
    """
    
    def __init__(self):
        self.logger = None  # Will be set by CLI when needed
    
    def _clear_screen(self):
        """Clear the terminal screen with AppImage compatibility"""
        clear_screen()
    
    def show_additional_tasks_menu(self, cli_instance):
        """Show the Additional Tasks & Tools submenu"""
        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header("Additional Tasks & Tools")
            print(f"{COLOR_INFO}Nexus Authentication, TTW Install & more{COLOR_RESET}\n")

            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Nexus Mods Authorization")
            print(f"   {COLOR_ACTION}→ Authorize with Nexus using OAuth or manage API key{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Tale of Two Wastelands (TTW) Installation")
            print(f"   {COLOR_ACTION}→ Install TTW using TTW_Linux_Installer{COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Install Wabbajack Application")
            print(f"   {COLOR_ACTION}→ Downloads and configures the Wabbajack app itself (via Proton){COLOR_RESET}")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Setup Mod Organizer 2")
            print(f"   {COLOR_ACTION}→ Download and configure a standalone MO2 instance{COLOR_RESET}")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(f"\n{COLOR_PROMPT}Enter your selection (0-4): {COLOR_RESET}").strip()

            if selection.lower() == 'q':  # Allow 'q' to re-display menu
                continue
            if selection == "1":
                self._execute_nexus_authorization(cli_instance)
            elif selection == "2":
                self._execute_ttw_install(cli_instance)
            elif selection == "3":
                self._execute_install_wabbajack(cli_instance)
            elif selection == "4":
                self._execute_setup_mo2(cli_instance)
            elif selection == "0":
                break
            else:
                print("Invalid selection. Please try again.")
                time.sleep(1)

    def _execute_legacy_recovery_menu(self, cli_instance):
        """LEGACY BRIDGE: Execute recovery menu"""
        # Handled by RecoveryMenuHandler
        from .recovery_menu import RecoveryMenuHandler
        
        recovery_handler = RecoveryMenuHandler()
        recovery_handler.logger = self.logger
        recovery_handler.show_recovery_menu(cli_instance)

    def _execute_ttw_install(self, cli_instance):
        """Execute TTW installation using TTW_Linux_Installer handler"""
        from ....backend.handlers.ttw_installer_handler import TTWInstallerHandler
        from ....backend.models.configuration import SystemInfo
        from ....shared.colors import COLOR_ERROR, COLOR_WARNING, COLOR_SUCCESS, COLOR_INFO, COLOR_PROMPT
        from pathlib import Path

        system_info = SystemInfo(is_steamdeck=cli_instance.system_info.is_steamdeck)
        ttw_installer_handler = TTWInstallerHandler(
            steamdeck=system_info.is_steamdeck,
            verbose=cli_instance.verbose,
            filesystem_handler=cli_instance.filesystem_handler,
            config_handler=cli_instance.config_handler
        )

        # First check if TTW_Linux_Installer is installed
        if not ttw_installer_handler.ttw_installer_installed:
            print(f"\n{COLOR_WARNING}TTW_Linux_Installer is not installed. Installing TTW_Linux_Installer first...{COLOR_RESET}")
            success, message = ttw_installer_handler.install_ttw_installer()
            if not success:
                print(f"{COLOR_ERROR}Failed to install TTW_Linux_Installer. Cannot proceed with TTW installation.{COLOR_RESET}")
                print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")
                input("Press Enter to return to menu...")
                return

        # Check for required games
        detected_games = ttw_installer_handler.path_handler.find_vanilla_game_paths()
        required_games = ['Fallout 3', 'Fallout New Vegas']
        missing_games = [game for game in required_games if game not in detected_games]
        if missing_games:
            print(f"\n{COLOR_ERROR}Missing required games: {', '.join(missing_games)}")
            print(f"TTW requires both Fallout 3 and Fallout New Vegas to be installed.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        # Prompt for TTW .mpi file with tab completion
        try:
            import readline
            from ....backend.handlers.completers import path_completer
            READLINE_AVAILABLE = True
        except ImportError:
            READLINE_AVAILABLE = False
        
        print(f"\n{COLOR_PROMPT}TTW Installer File (.mpi){COLOR_RESET}")
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind("tab: complete")
        try:
            mpi_path = input(f"{COLOR_PROMPT}Path to TTW .mpi file: {COLOR_RESET}").strip()
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)
        
        if not mpi_path:
            print(f"{COLOR_WARNING}No .mpi file specified. Cancelling.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        mpi_path = Path(mpi_path).expanduser()
        if not mpi_path.exists() or not mpi_path.is_file():
            print(f"{COLOR_ERROR}TTW .mpi file not found: {mpi_path}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        # Prompt for output directory with tab completion
        print(f"\n{COLOR_PROMPT}TTW Installation Directory{COLOR_RESET}")
        default_output = Path.home() / "ModdedGames" / "TTW"
        if READLINE_AVAILABLE:
            readline.set_completer_delims(' \t\n;')
            readline.set_completer(path_completer)
            readline.parse_and_bind("tab: complete")
        try:
            output_path = input(f"{COLOR_PROMPT}TTW install directory (Enter for default: {default_output}): {COLOR_RESET}").strip()
        finally:
            if READLINE_AVAILABLE:
                readline.set_completer(None)
        
        if not output_path:
            output_path = default_output
        else:
            output_path = Path(output_path).expanduser()

        # Run TTW installation
        print(f"\n{COLOR_INFO}Starting TTW installation workflow...{COLOR_RESET}")
        success, message = ttw_installer_handler.install_ttw_backend(mpi_path, output_path)
        
        if success:
            print(f"\n{COLOR_SUCCESS}TTW installation completed successfully!{COLOR_RESET}")
            print(f"{COLOR_INFO}TTW installed to: {output_path}{COLOR_RESET}")
        else:
            print(f"\n{COLOR_ERROR}TTW installation failed.{COLOR_RESET}")
            print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")
            input("Press Enter to return to menu...")

    def _execute_nexus_authorization(self, cli_instance):
        """Execute Nexus authorization menu (OAuth or API key)"""
        from ....backend.services.nexus_auth_service import NexusAuthService
        from ....backend.services.api_key_service import APIKeyService
        from ....shared.colors import COLOR_ERROR, COLOR_SUCCESS

        auth_service = NexusAuthService()

        while True:
            self._clear_screen()
            print_jackify_banner()
            print_section_header("Nexus Mods Authorization")

            # Get current auth status
            authenticated, method, username = auth_service.get_auth_status()

            if authenticated:
                if method == 'oauth':
                    print(f"\n{COLOR_SUCCESS}Status: Authorized via OAuth{COLOR_RESET}")
                    if username:
                        print(f"{COLOR_INFO}Logged in as: {username}{COLOR_RESET}")
                elif method == 'api_key':
                    print(f"\n{COLOR_WARNING}Status: Using API Key (Legacy){COLOR_RESET}")
                    print(f"{COLOR_INFO}Consider switching to OAuth for better security{COLOR_RESET}")
            else:
                print(f"\n{COLOR_WARNING}Status: Not Authorized{COLOR_RESET}")
                print(f"{COLOR_INFO}You need to authorize to download mods from Nexus{COLOR_RESET}")

            print(f"\n{COLOR_SELECTION}1.{COLOR_RESET} Authorize with Nexus (OAuth)")
            print(f"   {COLOR_ACTION}→ Opens browser for secure authorization{COLOR_RESET}")

            if method == 'oauth':
                print(f"{COLOR_SELECTION}2.{COLOR_RESET} Revoke OAuth Authorization")
                print(f"   {COLOR_ACTION}→ Remove OAuth token{COLOR_RESET}")

            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Set API Key (Legacy Fallback)")
            print(f"   {COLOR_ACTION}→ Manually enter Nexus API key{COLOR_RESET}")

            if authenticated:
                print(f"{COLOR_SELECTION}4.{COLOR_RESET} Clear All Authentication")
                print(f"   {COLOR_ACTION}→ Remove both OAuth and API key{COLOR_RESET}")

            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Return to Additional Tasks Menu")

            selection = input(f"\n{COLOR_PROMPT}Enter your selection: {COLOR_RESET}").strip()

            if selection == "1":
                # OAuth authorization
                print(f"\n{COLOR_INFO}Starting OAuth authorization...{COLOR_RESET}")
                print(f"{COLOR_WARNING}Your browser will open shortly.{COLOR_RESET}")
                print(f"{COLOR_WARNING}Please check your browser and authorize Jackify.{COLOR_RESET}")
                print(f"\n{COLOR_INFO}Note: Your browser may ask permission to open 'xdg-open' or{COLOR_RESET}")
                print(f"{COLOR_INFO}Jackify's protocol handler - please click 'Open' or 'Allow'.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to open browser...{COLOR_RESET}")

                # Perform OAuth authorization
                def show_message(msg):
                    print(f"\n{COLOR_INFO}{msg}{COLOR_RESET}")

                success = auth_service.authorize_oauth(show_browser_message_callback=show_message)

                if success:
                    print(f"\n{COLOR_SUCCESS}OAuth authorization successful!{COLOR_RESET}")
                    # Get username
                    _, _, username = auth_service.get_auth_status()
                    if username:
                        print(f"{COLOR_INFO}Authorized as: {username}{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_ERROR}OAuth authorization failed.{COLOR_RESET}")
                    print(f"{COLOR_INFO}You can try again or use API key as fallback.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "2" and method == 'oauth':
                # Revoke OAuth
                print(f"\n{COLOR_WARNING}Are you sure you want to revoke OAuth authorization?{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}Type 'yes' to confirm: {COLOR_RESET}").strip().lower()

                if confirm == 'yes':
                    if auth_service.revoke_oauth():
                        print(f"\n{COLOR_SUCCESS}OAuth authorization revoked.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_ERROR}Failed to revoke OAuth authorization.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "3":
                # Set API key
                print(f"\n{COLOR_INFO}Enter your Nexus API Key{COLOR_RESET}")
                print(f"{COLOR_INFO}(Get it from: https://www.nexusmods.com/users/myaccount?tab=api){COLOR_RESET}")

                api_key = input(f"\n{COLOR_PROMPT}API Key: {COLOR_RESET}").strip()

                if api_key:
                    if auth_service.save_api_key(api_key):
                        print(f"\n{COLOR_SUCCESS}API key saved successfully.{COLOR_RESET}")

                        # Optionally validate
                        print(f"\n{COLOR_INFO}Validating API key...{COLOR_RESET}")
                        valid, result = auth_service.validate_api_key(api_key)

                        if valid:
                            print(f"{COLOR_SUCCESS}API key validated successfully!{COLOR_RESET}")
                            print(f"{COLOR_INFO}Username: {result}{COLOR_RESET}")
                        else:
                            print(f"{COLOR_WARNING}Warning: API key validation failed: {result}{COLOR_RESET}")
                            print(f"{COLOR_INFO}Key saved, but may not work correctly.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_ERROR}Failed to save API key.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "4" and authenticated:
                # Clear all authentication
                print(f"\n{COLOR_WARNING}Are you sure you want to clear ALL authentication?{COLOR_RESET}")
                print(f"{COLOR_WARNING}This will remove both OAuth token and API key.{COLOR_RESET}")
                confirm = input(f"{COLOR_PROMPT}Type 'yes' to confirm: {COLOR_RESET}").strip().lower()

                if confirm == 'yes':
                    if auth_service.clear_all_auth():
                        print(f"\n{COLOR_SUCCESS}All authentication cleared.{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_INFO}No authentication to clear.{COLOR_RESET}")
                else:
                    print(f"\n{COLOR_INFO}Cancelled.{COLOR_RESET}")

                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

            elif selection == "0":
                break
            else:
                print(f"\n{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                time.sleep(1)

    def _execute_install_wabbajack(self, cli_instance):
        """Execute Wabbajack application installation"""
        from jackify.frontends.cli.commands.install_wabbajack import InstallWabbajackCommand

        command = InstallWabbajackCommand()
        if self.logger:
            self.logger.debug("AdditionalMenuHandler: Executing Install Wabbajack command")
        command.run()

    def _execute_setup_mo2(self, cli_instance):
        """Execute standalone MO2 setup"""
        from jackify.frontends.cli.commands.setup_mo2 import SetupMO2Command

        command = SetupMO2Command()
        if self.logger:
            self.logger.debug("AdditionalMenuHandler: Executing Setup MO2 command")
        command.run()
