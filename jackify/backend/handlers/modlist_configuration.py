"""Configuration workflow methods for ModlistHandler (Mixin)."""
from pathlib import Path
import os
import logging
import requests
import re
from typing import Optional

from .ui_colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_ERROR
from .resolution_handler import ResolutionHandler

logger = logging.getLogger(__name__)


class ModlistConfigurationMixin:
    """Mixin providing configuration workflow methods for ModlistHandler."""

    def display_modlist_summary(self, skip_confirmation: bool = False) -> bool:
        """Display the detected modlist summary and ask for confirmation."""
        if not self.appid or not self.modlist_dir or not self.modlist_ini:
            logger.error("Cannot display summary: Missing essential modlist context.")
            return False

        # Detect potentially missing info if not already set
        if not self.game_name:
             self._detect_game_variables()
        if not self.proton_ver or self.proton_ver == "Unknown":
             self._detect_proton_version()

        # Don't reset timing - continue from Steam Integration timing
        print("=== Configuration Summary ===")
        print(f"{self._get_progress_timestamp()} Selected Modlist: {self.game_name}")
        print(f"{self._get_progress_timestamp()} Game Type: {self.game_var_full if self.game_var_full else 'Unknown'}")
        print(f"{self._get_progress_timestamp()} Steam App ID: {self.appid}")
        print(f"{self._get_progress_timestamp()} Modlist Directory: {self.modlist_dir}")
        print(f"{self._get_progress_timestamp()} ModOrganizer.ini: {self.modlist_dir}/ModOrganizer.ini")
        print(f"{self._get_progress_timestamp()} Proton Version: {self.proton_ver if self.proton_ver else 'Unknown'}")
        print(f"{self._get_progress_timestamp()} Resolution: {self.selected_resolution if self.selected_resolution else 'Default'}")
        print(f"{self._get_progress_timestamp()} Modlist on SD Card: {self.modlist_sdcard}")
        print("")

        if skip_confirmation:
            return True
        # Ask for confirmation
        proceed = input(f"{COLOR_PROMPT}Proceed with configuration? (Y/n): {COLOR_RESET}").lower()
        if proceed == 'n': # Now defaults to Yes unless 'n' is entered
            logger.info("Configuration cancelled by user after summary.")
            return False
        else:
            return True

    def _execute_configuration_steps(self, status_callback=None, manual_steps_completed=False, skip_manual_for_existing=False):
        """
        Runs the actual configuration steps for the selected modlist.
        Args:
            status_callback (callable, optional): A function to call with status updates during configuration.
            manual_steps_completed (bool): If True, skip the manual steps prompt (used for new modlist flow).
            skip_manual_for_existing (bool): If True, always skip manual steps (for existing modlists that are already configured).
        """
        try:
            # Store status_callback for Configuration Summary
            self._current_status_callback = status_callback
            
            self.logger.info("Executing configuration steps...")
            
            # Ensure required context is set
            if not all([self.modlist_dir, self.appid, self.game_var, self.steamdeck is not None]):
                self.logger.error("Cannot execute configuration steps: Missing required context (modlist_dir, appid, game_var, steamdeck status).")
                self.logger.error("Missing required information to start configuration.")
                return False
        except Exception as e:
            self.logger.error(f"Exception in _execute_configuration_steps initialization: {e}", exc_info=True)
            return False
            
        # Step 1: Set protontricks permissions
        if status_callback:
            # Reset timing for Prefix Configuration section
            from jackify.shared.timing import start_new_phase
            start_new_phase()
            
            status_callback("")  # Blank line after Configuration Summary
            status_callback("")  # Extra blank line before Prefix Configuration  
            status_callback("=== Prefix Configuration ===")
            status_callback(f"{self._get_progress_timestamp()} Setting Protontricks permissions")
        self.logger.info("Step 1: Setting Protontricks permissions...")
        if not self.protontricks_handler.set_protontricks_permissions(self.modlist_dir, self.steamdeck):
            self.logger.error("Failed to set Protontricks permissions. Configuration aborted.")
            self.logger.error("Could not set necessary Protontricks permissions.")
            return False # Abort on failure
        self.logger.info("Step 1: Setting Protontricks permissions... Done")

        # Step 2: Prompt user for manual steps and wait for compatdata
        skip_manual_prompt = skip_manual_for_existing  # Existing modlists skip manual steps
        if not manual_steps_completed and not skip_manual_for_existing:
            # Check if Proton Experimental is already set and compatdata exists
            proton_ok = False
            compatdata_ok = False
            
            # Check Proton version
            self.logger.debug(f"[MANUAL STEPS DEBUG] Checking Proton version for AppID {self.appid}")
            if self._detect_proton_version():
                self.logger.debug(f"[MANUAL STEPS DEBUG] Detected Proton version: {self.proton_ver}")
                if self.proton_ver and 'experimental' in self.proton_ver.lower():
                    proton_ok = True
                    self.logger.debug("[MANUAL STEPS DEBUG] Proton Experimental detected - proton_ok = True")
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Could not detect Proton version")
                
            # Check compatdata/prefix
            prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
            self.logger.debug(f"[MANUAL STEPS DEBUG] Compatdata path search result: {prefix_path_str}")

            if prefix_path_str and os.path.isdir(prefix_path_str):
                compatdata_ok = True
                self.logger.debug("[MANUAL STEPS DEBUG] Compatdata directory exists - compatdata_ok = True")
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Compatdata directory does not exist")
                
            self.logger.debug(f"[MANUAL STEPS DEBUG] proton_ok: {proton_ok}, compatdata_ok: {compatdata_ok}")
            
            if proton_ok and compatdata_ok:
                self.logger.info("Proton Experimental and compatdata already set for this AppID; skipping manual steps prompt.")
                skip_manual_prompt = True
            else:
                self.logger.debug("[MANUAL STEPS DEBUG] Manual steps will be required")
                
        self.logger.debug(f"[MANUAL STEPS DEBUG] manual_steps_completed: {manual_steps_completed}, skip_manual_prompt: {skip_manual_prompt}")
        
        if not manual_steps_completed and not skip_manual_prompt:
            # Check if we're in GUI mode - if so, don't show CLI prompts, just fail and let GUI callbacks handle it
            gui_mode = os.environ.get('JACKIFY_GUI_MODE') == '1'
            
            if gui_mode:
                # In GUI mode: don't show CLI prompts, just fail so GUI can show dialog and retry
                self.logger.info("GUI mode detected: skipping CLI manual steps prompt, will fail configuration to trigger GUI callback")
                if status_callback:
                    status_callback("Manual Steam/Proton setup required - this will be handled by GUI dialog")
                # Return False to trigger manual steps callback in GUI
                return False
            else:
                # CLI mode: show the traditional CLI prompt
                if status_callback:
                    status_callback("Please perform the manual steps in Steam (set Proton, launch shortcut, then close MO2)...")
                self.logger.info("Prompting user to perform manual Steam/Proton steps and launch shortcut.")
                print("\n───────────────────────────────────────────────────────────────────")
                print(f"{COLOR_INFO}Manual Steps Required:{COLOR_RESET} Please follow the on-screen instructions to set Proton Experimental and launch the shortcut from Steam.")
                print("───────────────────────────────────────────────────────────────────")
                input(f"{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
                self.logger.info("User confirmed completion of manual steps.")
        # Step 3: Download and apply curated user.reg.modlist and system.reg.modlist
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Applying curated registry files for modlist configuration")
        self.logger.info("Step 3: Downloading and applying curated user.reg.modlist and system.reg.modlist...")
        try:
            prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
            if not prefix_path_str or not os.path.isdir(prefix_path_str):
                raise Exception("Could not determine Wine prefix path for this modlist. Please ensure you have launched the shortcut from Steam at least once.")
            user_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/user.reg.modlist"
            user_reg_dest = Path(prefix_path_str) / "user.reg"
            response = requests.get(user_reg_url, verify=True)
            response.raise_for_status()
            with open(user_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Curated user.reg.modlist downloaded and applied to {user_reg_dest}")
            system_reg_url = "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/refs/heads/main/files/system.reg.modlist"
            system_reg_dest = Path(prefix_path_str) / "system.reg"
            response = requests.get(system_reg_url, verify=True)
            response.raise_for_status()
            with open(system_reg_dest, "wb") as f:
                f.write(response.content)
            self.logger.info(f"Curated system.reg.modlist downloaded and applied to {system_reg_dest}")
        except Exception as e:
            self.logger.error(f"Failed to download or apply curated user.reg.modlist or system.reg.modlist: {e}")
            self.logger.error(f"Failed to download or apply curated user.reg.modlist or system.reg.modlist. {e}")
            return False
        self.logger.info("Step 3: Curated user.reg.modlist and system.reg.modlist applied successfully.")

        # Step 4: Install Wine Components
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Installing Wine components (this may take a while)")
        self.logger.info("Step 4: Installing Wine components (this may take a while)...")
        
        # Use canonical logic for all modlists/games
        components = self.get_modlist_wine_components(self.game_name, self.game_var_full)
        
        # All modlists now use their own AppID for wine components
        target_appid = self.appid
        
        # Use user's preferred component installation method (respects settings toggle)
        self.logger.debug(f"Getting WINEPREFIX for AppID {target_appid}...")
        wineprefix = self.protontricks_handler.get_wine_prefix_path(target_appid)
        if not wineprefix:
            self.logger.error("Failed to get WINEPREFIX path for component installation.")
            self.logger.error("Could not determine wine prefix location.")
            return False
        self.logger.debug(f"WINEPREFIX obtained: {wineprefix}")

        # Use the winetricks handler which respects the user's toggle setting
        try:
            self.logger.info("Installing Wine components using user's preferred method...")
            self.logger.debug(f"Calling winetricks_handler.install_wine_components with wineprefix={wineprefix}, game_var={self.game_var_full}, components={components}")
            success = self.winetricks_handler.install_wine_components(wineprefix, self.game_var_full, specific_components=components, status_callback=status_callback, appid=str(target_appid) if target_appid else None)
            if success:
                self.logger.info("Wine component installation completed successfully")
                if status_callback:
                    status_callback(f"{self._get_progress_timestamp()} Wine components verified and installed successfully")
            else:
                self.logger.error("Wine component installation failed")
                self.logger.error("Failed to install necessary Wine components.")
                return False
        except Exception as e:
            self.logger.error(f"Wine component installation failed with exception: {e}")
            self.logger.error("Failed to install necessary Wine components.")
            return False
        self.logger.info("Step 4: Installing Wine components... Done")

        # Step 4.5: Apply universal dotnet4.x compatibility registry fixes AFTER wine components
        # Apply after components to avoid overwrite
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Applying universal dotnet4.x compatibility fixes")
        self.logger.info("Step 4.5: Applying universal dotnet4.x compatibility registry fixes...")
        registry_success = False
        try:
            registry_success = self._apply_universal_dotnet_fixes()
        except Exception as e:
            error_msg = f"CRITICAL: Registry fixes failed - modlist may have .NET compatibility issues: {e}"
            self.logger.error(error_msg)
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} ERROR: {error_msg}")
            registry_success = False

        if not registry_success:
            failure_msg = "WARNING: Universal dotnet4.x registry fixes FAILED! This modlist may experience .NET Framework compatibility issues."
            self.logger.error("=" * 80)
            self.logger.error(failure_msg)
            self.logger.error("Consider manually setting mscoree=native in winecfg if problems occur.")
            self.logger.error("=" * 80)
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} {failure_msg}")
            # Continue but user should be aware of potential issues

        # Step 4.6: Enable dotfiles visibility for Wine prefix
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Enabling dotfiles visibility")
        self.logger.info("Step 4.6: Enabling dotfiles visibility in Wine prefix...")
        try:
            if self.protontricks_handler.enable_dotfiles(self.appid):
                self.logger.info("Dotfiles visibility enabled successfully")
            else:
                self.logger.warning("Failed to enable dotfiles visibility (non-critical, continuing)")
        except Exception as e:
            self.logger.warning(f"Error enabling dotfiles visibility: {e} (non-critical, continuing)")
        self.logger.info("Step 4.6: Enabling dotfiles visibility... Done")

        # Step 4.7: Create Wine prefix Documents directories for USVFS
        # Critical for USVFS profile INI virtualization on first launch
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Creating Wine prefix Documents directories for USVFS")
        self.logger.info("Step 4.7: Creating Wine prefix Documents directories for USVFS...")
        try:
            if self.appid and self.game_var:
                # Map game_var to game_name for create_required_dirs
                game_name_map = {
                    "skyrimspecialedition": "skyrimse",
                    "fallout4": "fallout4",
                    "falloutnv": "falloutnv",
                    "oblivion": "oblivion",
                    "enderalspecialedition": "enderalse"
                }
                game_name = game_name_map.get(self.game_var.lower(), None)
                
                if game_name:
                    appid_str = str(self.appid)
                    if self.filesystem_handler.create_required_dirs(game_name, appid_str):
                        self.logger.info("Wine prefix Documents directories created successfully for USVFS")
                    else:
                        self.logger.warning("Failed to create Wine prefix Documents directories (non-critical, continuing)")
                else:
                    self.logger.debug(f"Game {self.game_var} not in directory creation map, skipping")
            else:
                self.logger.warning("AppID or game_var not available, skipping Wine prefix Documents directory creation")
        except Exception as e:
            self.logger.warning(f"Error creating Wine prefix Documents directories: {e} (non-critical, continuing)")
        self.logger.info("Step 4.7: Creating Wine prefix Documents directories... Done")

        # Step 5: Verify ownership of Modlist directory
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Verifying modlist directory ownership")
        self.logger.info("Step 5: Verifying ownership of modlist directory...")
        # Convert modlist_dir string to Path object for the method
        modlist_path_obj = Path(self.modlist_dir)
        success, error_msg = self.filesystem_handler.verify_ownership_and_permissions(modlist_path_obj)
        if not success:
            self.logger.error("Ownership verification failed for modlist directory. Configuration aborted.")
            print(f"\n{COLOR_ERROR}{error_msg}{COLOR_RESET}")
            return False # Abort on failure
        self.logger.info("Step 5: Ownership verification... Done")

        # Step 6: Backup ModOrganizer.ini
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Backing up ModOrganizer.ini")
        self.logger.info(f"Step 6: Backing up {self.modlist_ini}...")
        modlist_ini_path_obj = Path(self.modlist_ini)
        backup_path = self.filesystem_handler.backup_file(modlist_ini_path_obj)
        if not backup_path:
            self.logger.error("Failed to back up ModOrganizer.ini. Configuration aborted.")
            self.logger.error("Failed to back up ModOrganizer.ini.")
            return False # Abort on failure
        self.logger.info(f"ModOrganizer.ini backed up to: {backup_path}")
        self.logger.info("Step 6: Backing up ModOrganizer.ini... Done")

        # Step 6.5: Handle symlinked downloads directory
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Checking for symlinked downloads directory")
        self.logger.info("Step 6.5: Checking for symlinked downloads directory...")
        if not self._handle_symlinked_downloads():
            self.logger.warning("Warning during symlink handling (non-critical)")
        self.logger.info("Step 6.5: Checking for symlinked downloads directory... Done")

        # Step 7a: Detect Stock Game/Game Root path
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting stock game path")
        # Sets self.stock_game_path if found
        if not self._detect_stock_game_path():
            self.logger.error("Failed during stock game path detection.")
            self.logger.error("Failed during stock game path detection.")
            return False

        # Step 7b: Detect Steam Library Info (Needed for Step 8)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Detecting Steam Library info")
        self.logger.info("Step 7b: Detecting Steam Library info...")
        if not self._detect_steam_library_info():
             self.logger.error("Failed to detect necessary Steam Library information.")
             self.logger.error("Could not find Steam library information.")
             return False
        self.logger.info("Step 7b: Detecting Steam Library info... Done")

        # Step 8: Update ModOrganizer.ini Paths (gamePath, Binary, workingDirectory)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Updating ModOrganizer.ini paths")
        self.logger.info("Step 8: Updating gamePath, Binary, and workingDirectory paths in ModOrganizer.ini...")
        
        # Update gamePath using replace_gamepath method
        modlist_dir_path_obj = Path(self.modlist_dir)
        modlist_ini_path_obj = Path(self.modlist_ini)
        stock_game_path_obj = Path(self.stock_game_path) if self.stock_game_path else None
        # Only call replace_gamepath if we have a valid stock game path
        if stock_game_path_obj:
            if not self.path_handler.replace_gamepath(
                modlist_ini_path=modlist_ini_path_obj, 
                new_game_path=stock_game_path_obj,
                modlist_sdcard=self.modlist_sdcard
            ):
                self.logger.error("Failed to update gamePath in ModOrganizer.ini. Configuration aborted.")
                self.logger.error("Failed to update game path in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.info("No stock game path found, skipping gamePath update - edit_binary_working_paths will handle all path updates.")
            self.logger.info("Using unified path manipulation to avoid duplicate processing.")
        
        # Conditionally update binary and working directory paths
        # Skip for jackify-engine workflows since paths are already correct
        # Exception: Always run for SD card installs to fix Z:/run/media/... to D:/... paths

        # DEBUG: Add comprehensive logging to identify Steam Deck SD card path manipulation issues
        engine_installed = getattr(self, 'engine_installed', False)
        self.logger.debug(f"[SD_CARD_DEBUG] ModlistHandler instance: id={id(self)}")
        self.logger.debug(f"[SD_CARD_DEBUG] engine_installed: {engine_installed}")
        self.logger.debug(f"[SD_CARD_DEBUG] modlist_sdcard: {self.modlist_sdcard}")
        self.logger.debug(f"[SD_CARD_DEBUG] steamdeck parameter passed to constructor: {getattr(self, 'steamdeck', 'NOT_SET')}")
        self.logger.debug(f"[SD_CARD_DEBUG] Path manipulation condition: not {engine_installed} or {self.modlist_sdcard} = {not engine_installed or self.modlist_sdcard}")

        if not getattr(self, 'engine_installed', False) or self.modlist_sdcard:
            # Convert steamapps/common path to library root path
            steam_libraries = None
            if self.steam_library:
                # self.steam_library is steamapps/common, need to go up 2 levels to get library root
                steam_library_root = Path(self.steam_library).parent.parent
                steam_libraries = [steam_library_root]
                self.logger.debug(f"Using Steam library root: {steam_library_root}")
            
            if not self.path_handler.edit_binary_working_paths(
                modlist_ini_path=modlist_ini_path_obj,
                modlist_dir_path=modlist_dir_path_obj,
                modlist_sdcard=self.modlist_sdcard,
                steam_libraries=steam_libraries
            ):
                self.logger.error("Failed to update binary and working directory paths in ModOrganizer.ini. Configuration aborted.")
                self.logger.error("Failed to update binary and working directory paths in ModOrganizer.ini.")
                return False  # Abort on failure
        else:
            self.logger.debug("[SD_CARD_DEBUG] Skipping path manipulation - jackify-engine already set correct paths in ModOrganizer.ini")
            self.logger.debug(f"[SD_CARD_DEBUG] SKIPPED because: engine_installed={engine_installed} and modlist_sdcard={self.modlist_sdcard}")

        if getattr(self, 'download_dir', None):
            if self.path_handler.set_download_directory(
                modlist_ini_path_obj, str(self.download_dir), self.modlist_sdcard
            ):
                self.logger.info("Set download_directory in ModOrganizer.ini (Install flow)")
            else:
                self.logger.warning("Could not set download_directory in ModOrganizer.ini")

        # Step 8.5: Align /home vs /var/home basis for Z: paths to match modlist install directory.
        # This is intentionally separate from broad binary-path rewriting so it still runs when
        # engine-installed workflows skip edit_binary_working_paths.
        if not self.path_handler.align_home_path_basis(
            modlist_ini_path=modlist_ini_path_obj,
            modlist_dir_path=modlist_dir_path_obj,
            modlist_sdcard=self.modlist_sdcard,
        ):
            self.logger.error("Failed to align home-path basis in ModOrganizer.ini. Configuration aborted.")
            self.logger.error("Failed to align /home path basis in ModOrganizer.ini.")
            return False

        self.logger.info("Step 8: Updating ModOrganizer.ini paths... Done")

        # Step 9: Update Resolution Settings (if applicable)
        if hasattr(self, 'selected_resolution') and self.selected_resolution:
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Updating resolution settings")
            # Ensure resolution_handler call uses correct args if needed
            # Assuming it uses modlist_dir (str) and game_var_full (str)
            # Construct vanilla game directory path for fallback
            vanilla_game_dir = None
            if self.steam_library and self.game_var_full:
                vanilla_game_dir = str(Path(self.steam_library) / "steamapps" / "common" / self.game_var_full)

            if not ResolutionHandler.update_ini_resolution(
                modlist_dir=self.modlist_dir,
                game_var=self.game_var_full,
                set_res=self.selected_resolution,
                vanilla_game_dir=vanilla_game_dir
            ):
                self.logger.warning("Failed to update resolution settings in some INI files.")
                self.logger.warning("Failed to update resolution settings.")
            self.logger.info("Step 9: Updating resolution in INI files... Done")
        else:
            self.logger.info("Step 9: Skipping resolution update (no resolution selected).")

        # Step 10: Create dxvk.conf (skip for special games using vanilla compatdata)
        special_game_type = self.detect_special_game_type(self.modlist_dir)
        self.logger.debug(f"DXVK step - modlist_dir='{self.modlist_dir}', special_game_type='{special_game_type}'")
        
        # Force check specific files for debugging
        nvse_path = Path(self.modlist_dir) / "nvse_loader.exe" if self.modlist_dir else None
        enderal_path = Path(self.modlist_dir) / "Enderal Launcher.exe" if self.modlist_dir else None
        self.logger.debug(f"nvse_loader.exe exists: {nvse_path.exists() if nvse_path else 'N/A'}")
        self.logger.debug(f"Enderal Launcher.exe exists: {enderal_path.exists() if enderal_path else 'N/A'}")
        
        if special_game_type:
            self.logger.info(f"Step 10: Skipping dxvk.conf creation for {special_game_type.upper()} (uses vanilla compatdata)")
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Skipping dxvk.conf for {special_game_type.upper()} modlist")
        else:
            if status_callback:
                status_callback(f"{self._get_progress_timestamp()} Creating dxvk.conf file")
            self.logger.info("Step 10: Creating dxvk.conf file...")
            # Assuming create_dxvk_conf still uses string paths
            # Construct vanilla game directory path for fallback
            vanilla_game_dir = None
            if self.steam_library and self.game_var_full:
                vanilla_game_dir = str(Path(self.steam_library) / "steamapps" / "common" / self.game_var_full)
                
            dxvk_created = self.path_handler.create_dxvk_conf(
                modlist_dir=self.modlist_dir, 
                modlist_sdcard=self.modlist_sdcard, 
                steam_library=str(self.steam_library) if self.steam_library else None, # Pass as string or None 
                basegame_sdcard=self.basegame_sdcard, 
                game_var_full=self.game_var_full,
                vanilla_game_dir=vanilla_game_dir,
                stock_game_path=self.stock_game_path
            )
            dxvk_verified = self.path_handler.verify_dxvk_conf_exists(
                modlist_dir=self.modlist_dir,
                steam_library=str(self.steam_library) if self.steam_library else None,
                game_var_full=self.game_var_full,
                vanilla_game_dir=vanilla_game_dir,
                stock_game_path=self.stock_game_path
            )
            if not dxvk_created or not dxvk_verified:
                self.logger.warning("DXVK configuration file is missing or incomplete after post-install steps.")
                self.logger.warning("Failed to verify dxvk.conf file (required for AMD GPUs).")
            self.logger.info("Step 10: Creating dxvk.conf... Done")

        # Step 11a: Small Tasks - Delete Incompatible Plugins
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Deleting incompatible MO2 plugins")
        self.logger.info("Step 11a: Deleting incompatible MO2 plugins...")

        # Delete FixGameRegKey.py plugin
        fixgamereg_path = Path(self.modlist_dir) / "plugins" / "FixGameRegKey.py"
        if fixgamereg_path.exists():
            try:
                fixgamereg_path.unlink()
                self.logger.info("FixGameRegKey.py plugin deleted successfully.")
            except Exception as e:
                self.logger.warning(f"Failed to delete FixGameRegKey.py plugin: {e}")
                self.logger.warning("Failed to delete FixGameRegKey.py plugin file.")
        else:
            self.logger.debug("FixGameRegKey.py plugin not found (this is normal).")

        # Delete PageFileManager plugin directory (Linux has no PageFile)
        pagefilemgr_path = Path(self.modlist_dir) / "plugins" / "PageFileManager"
        if pagefilemgr_path.exists():
            try:
                import shutil
                shutil.rmtree(pagefilemgr_path)
                self.logger.info("PageFileManager plugin directory deleted successfully.")
            except Exception as e:
                self.logger.warning(f"Failed to delete PageFileManager plugin directory: {e}")
                self.logger.warning("Failed to delete PageFileManager plugin directory.")
        else:
            self.logger.debug("PageFileManager plugin not found (this is normal).")

        self.logger.info("Step 11a: Incompatible plugin deletion check complete.")


        # Step 11b: Download Font
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Downloading required font")
        prefix_path_str = self.path_handler.find_compat_data(str(self.appid))
        if prefix_path_str:
            prefix_path = Path(prefix_path_str)
            fonts_dir = prefix_path / "pfx" / "drive_c" / "windows" / "Fonts"
            font_url = "https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf"
            font_dest_path = fonts_dir / "seguisym.ttf"
            
            # Pass quiet=True to suppress print during configuration steps
            if not self.filesystem_handler.download_file(font_url, font_dest_path, quiet=True):
                self.logger.warning(f"Failed to download {font_url} to {font_dest_path}")
                self.logger.warning("Failed to download necessary font file (seguisym.ttf).")
                # Continue anyway, not critical for all lists
            else:
                self.logger.info("Font downloaded successfully.")
        else:
            self.logger.error("Could not get WINEPREFIX path, skipping font download.")
            self.logger.warning("Could not determine Wine prefix path, skipping font download.")

        # Step 12: Modlist-specific steps
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Checking for modlist-specific steps")
            status_callback("")  # Blank line after final Prefix Configuration step
        self.logger.info("Step 12: Checking for modlist-specific steps...")

        # Step 13: Launch options for special games are now set during automated prefix workflow (before Steam restart)
        # Avoids a second Steam restart
        special_game_type = self.detect_special_game_type(self.modlist_dir)
        if special_game_type:
            self.logger.info(f"Step 13: Launch options for {special_game_type.upper()} were set during automated workflow")
        else:
            self.logger.debug("Step 13: No special launch options needed for this modlist type")

        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Finalizing post-install configuration")

        # Do not call status_callback here, the final message is handled in menu_handler
        # if status_callback:
        #     status_callback("Configuration completed successfully!")
            
        self.logger.info("Configuration steps completed successfully.")

        # Step 14: Re-enforce Windows 10 mode after modlist-specific configurations (matches legacy script line 1333)
        if status_callback:
            status_callback(f"{self._get_progress_timestamp()} Re-applying final Windows compatibility settings")
        self._re_enforce_windows_10_mode()

        return True # Return True on success

    def run_modlist_configuration_phase(self, context: dict = None) -> bool:
        """
        Main entry point to run the full modlist configuration sequence.
        This orchestrates all the individual steps.
        """
        self.logger.info(f"Starting configuration phase for modlist: {self.game_name}")
        # Call the private method that contains the actual steps
        # Pass along the status_callback if it was provided in the context
        status_callback = context.get('status_callback') if context else None
        return self._execute_configuration_steps(status_callback=status_callback)

    def _prompt_or_set_resolution(self):
        # If on Steam Deck, set 1280x800 automatically
        if self._is_steam_deck():
            self.selected_resolution = "1280x800"
            self.logger.info("Steam Deck detected: setting resolution to 1280x800.")
        else:
            print("Do you wish to set the display resolution? (This can be changed manually later)")
            response = input("Set resolution? (y/N): ").strip().lower()
            if response == 'y':
                while True:
                    user_res = input("Enter resolution (e.g., 1920x1080): ").strip()
                    if re.match(r'^[0-9]+x[0-9]+$', user_res):
                        self.selected_resolution = user_res
                        self.logger.info(f"User selected resolution: {user_res}")
                        break
                    else:
                        print("Invalid format. Please use format: 1920x1080")
            else:
                self.selected_resolution = None
                self.logger.info("Resolution setup skipped by user.")
