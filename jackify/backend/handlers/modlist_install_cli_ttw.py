"""TTW integration methods for ModlistInstallCLI (Mixin)."""
import logging
import os
from pathlib import Path

from .ui_colors import COLOR_PROMPT, COLOR_INFO, COLOR_ERROR, COLOR_RESET

logger = logging.getLogger(__name__)


class ModlistInstallCLITTWMixin:
    """Mixin providing TTW integration methods."""

    def _check_and_prompt_ttw_integration(self, install_dir: str, game_type: str, modlist_name: str):
        """Check if modlist is eligible for TTW integration and prompt user"""
        try:
            # Check eligibility: FNV game, TTW-compatible modlist, no existing TTW
            if not self._is_ttw_eligible(install_dir, game_type, modlist_name):
                return

            # Prompt user for TTW installation
            print(f"\n{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
            print(f"{COLOR_INFO}TTW Integration Available{COLOR_RESET}")
            print(f"{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
            print(f"\nThis modlist ({modlist_name}) supports Tale of Two Wastelands (TTW).")
            print(f"TTW combines Fallout 3 and New Vegas into a single game.")
            print(f"\nWould you like to install TTW now?")

            user_input = input(f"{COLOR_PROMPT}Install TTW? (yes/no): {COLOR_RESET}").strip().lower()

            if user_input in ['yes', 'y']:
                self._launch_ttw_installation(modlist_name, install_dir)
            else:
                print(f"{COLOR_INFO}Skipping TTW installation. You can install it later from the main menu.{COLOR_RESET}")

        except Exception as e:
            self.logger.error(f"Error during TTW eligibility check: {e}", exc_info=True)

    def _is_ttw_eligible(self, install_dir: str, game_type: str, modlist_name: str) -> bool:
        """Check if modlist is eligible for TTW integration"""
        try:
            from pathlib import Path

            # Check 1: Must be Fallout New Vegas
            if not game_type or game_type.lower() not in ['falloutnv', 'fallout new vegas', 'fallout_new_vegas']:
                return False

            # Check 2: Must be on TTW compatibility whitelist
            from jackify.backend.data.ttw_compatible_modlists import is_ttw_compatible
            if not is_ttw_compatible(modlist_name):
                return False

            # Check 3: TTW must not already be installed
            if self._detect_existing_ttw(install_dir):
                self.logger.info(f"TTW already installed in {install_dir}, skipping prompt")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error checking TTW eligibility: {e}")
            return False

    def _detect_existing_ttw(self, install_dir: str) -> bool:
        """Detect if TTW is already installed in the modlist"""
        try:
            from pathlib import Path

            install_path = Path(install_dir)

            # Search for TTW indicators in common locations
            search_paths = [
                install_path,
                install_path / "mods",
                install_path / "Stock Game",
                install_path / "Game Root"
            ]

            for search_path in search_paths:
                if not search_path.exists():
                    continue

                # Look for folders containing "tale" and "two" and "wastelands"
                for folder in search_path.iterdir():
                    if not folder.is_dir():
                        continue

                    folder_name_lower = folder.name.lower()
                    if all(keyword in folder_name_lower for keyword in ['tale', 'two', 'wastelands']):
                        # Verify it has the TTW ESM file
                        for file in folder.rglob('*.esm'):
                            if 'taleoftwowastelands' in file.name.lower():
                                self.logger.info(f"Found existing TTW installation: {file}")
                                return True

            return False

        except Exception as e:
            self.logger.error(f"Error detecting existing TTW: {e}")
            return False

    def _launch_ttw_installation(self, modlist_name: str, install_dir: str):
        """Launch TTW installation workflow"""
        try:
            print(f"\n{COLOR_INFO}Starting TTW installation workflow...{COLOR_RESET}")

            # Import TTW installation handler
            from jackify.backend.handlers.ttw_installer_handler import TTWInstallerHandler
            from jackify.backend.models.configuration import SystemInfo
            from pathlib import Path

            system_info = SystemInfo()
            ttw_installer_handler = TTWInstallerHandler(
                steamdeck=system_info.is_steamdeck if hasattr(system_info, 'is_steamdeck') else False,
                verbose=self.verbose if hasattr(self, 'verbose') else False,
                filesystem_handler=self.filesystem_handler if hasattr(self, 'filesystem_handler') else None,
                config_handler=self.config_handler if hasattr(self, 'config_handler') else None
            )

            # Check if TTW_Linux_Installer is installed
            ttw_installer_handler._check_installation()

            if not ttw_installer_handler.ttw_installer_installed:
                print(f"{COLOR_INFO}TTW_Linux_Installer is not installed.{COLOR_RESET}")
                user_input = input(f"{COLOR_PROMPT}Install TTW_Linux_Installer? (yes/no): {COLOR_RESET}").strip().lower()

                if user_input not in ['yes', 'y']:
                    print(f"{COLOR_INFO}TTW installation cancelled.{COLOR_RESET}")
                    return

                # Install TTW_Linux_Installer
                print(f"{COLOR_INFO}Installing TTW_Linux_Installer...{COLOR_RESET}")
                success, message = ttw_installer_handler.install_ttw_installer()

                if not success:
                    print(f"{COLOR_ERROR}Failed to install TTW_Linux_Installer: {message}{COLOR_RESET}")
                    return

                print(f"{COLOR_INFO}TTW_Linux_Installer installed successfully.{COLOR_RESET}")

            # Prompt for TTW .mpi file
            print(f"\n{COLOR_PROMPT}TTW Installer File (.mpi){COLOR_RESET}")
            mpi_path = input(f"{COLOR_PROMPT}Path to TTW .mpi file: {COLOR_RESET}").strip()
            if not mpi_path:
                print(f"{COLOR_WARNING}No .mpi file specified. Cancelling.{COLOR_RESET}")
                return

            mpi_path = Path(mpi_path).expanduser()
            if not mpi_path.exists() or not mpi_path.is_file():
                print(f"{COLOR_ERROR}TTW .mpi file not found: {mpi_path}{COLOR_RESET}")
                return

            # Prompt for TTW installation directory
            print(f"\n{COLOR_PROMPT}TTW Installation Directory{COLOR_RESET}")
            default_ttw_dir = os.path.join(install_dir, 'TTW')
            print(f"Default: {default_ttw_dir}")
            ttw_install_dir = input(f"{COLOR_PROMPT}TTW install directory (Enter for default): {COLOR_RESET}").strip()

            if not ttw_install_dir:
                ttw_install_dir = default_ttw_dir

            # Run TTW installation
            print(f"\n{COLOR_INFO}Installing TTW using TTW_Linux_Installer...{COLOR_RESET}")
            print(f"{COLOR_INFO}This may take a while (15-30 minutes depending on your system).{COLOR_RESET}")

            success, message = ttw_installer_handler.install_ttw_backend(Path(mpi_path), Path(ttw_install_dir))

            if success:
                print(f"\n{COLOR_INFO}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
                print(f"{COLOR_INFO}TTW Installation Complete!{COLOR_RESET}")
                print(f"{COLOR_PROMPT}═══════════════════════════════════════════════════════════════{COLOR_RESET}")
                print(f"\nTTW has been installed to: {ttw_install_dir}")
                print(f"The modlist '{modlist_name}' is now ready to use with TTW.")
            else:
                print(f"\n{COLOR_ERROR}TTW installation failed. Check the logs for details.{COLOR_RESET}")
                print(f"{COLOR_ERROR}Error: {message}{COLOR_RESET}")

        except Exception as e:
            self.logger.error(f"Error during TTW installation: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error during TTW installation: {e}{COLOR_RESET}")