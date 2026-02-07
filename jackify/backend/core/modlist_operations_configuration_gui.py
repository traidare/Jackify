"""GUI configuration phase methods for ModlistInstallCLI (Mixin)."""
import logging
import os

logger = logging.getLogger(__name__)


class ModlistOperationsConfigurationGUIMixin:
    """Mixin providing GUI configuration phase methods."""

    def configuration_phase_gui_mode(self, context,
                                     progress_callback=None,
                                     manual_steps_callback=None,
                                     completion_callback=None):
        """
        GUI-friendly configuration phase that uses callbacks instead of prompts.

        This method provides the same functionality as configuration_phase() but
        integrates with GUI frontends using Qt callbacks instead of CLI prompts.

        Args:
            context: Configuration context dict with modlist details
            progress_callback: Called with progress messages (str)
            manual_steps_callback: Called when manual steps needed (modlist_name, retry_count)
            completion_callback: Called when configuration completes (success, message, modlist_name)
        """
        try:
            from .modlist_operations import _get_user_proton_version

            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')

            try:
                config_context = {
                    'name': context.get('modlist_name', ''),
                    'path': context.get('install_dir', ''),
                    'mo2_exe_path': context.get('mo2_exe_path', ''),
                    'modlist_value': context.get('modlist_value'),
                    'modlist_source': context.get('modlist_source'),
                    'resolution': context.get('resolution'),
                    'skip_confirmation': True,
                    'manual_steps_completed': False
                }

                existing_app_id = context.get('app_id')
                if existing_app_id:
                    config_context['appid'] = existing_app_id

                    if progress_callback:
                        progress_callback(f"Configuring existing modlist with AppID {existing_app_id}...")

                    from jackify.backend.handlers.menu_handler import ModlistMenuHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler

                    config_handler = ConfigHandler()
                    modlist_menu = ModlistMenuHandler(config_handler)

                    retry_count = 0
                    max_retries = 3

                    while retry_count < max_retries:
                        if progress_callback:
                            progress_callback("Running modlist configuration...")

                        result = modlist_menu.run_modlist_configuration_phase(config_context)

                        if progress_callback:
                            progress_callback(f"Configuration attempt {retry_count}: {'Success' if result else 'Failed'}")

                        if result:
                            if completion_callback:
                                completion_callback(True, "Configuration completed successfully!", config_context['name'])
                            return True
                        else:
                            retry_count += 1

                            if retry_count < max_retries:
                                if progress_callback:
                                    progress_callback(f"Configuration failed on attempt {retry_count}, showing manual steps dialog...")
                                if manual_steps_callback:
                                    if progress_callback:
                                        progress_callback(f"Calling manual_steps_callback for {config_context['name']}, retry {retry_count}")
                                    manual_steps_callback(config_context['name'], retry_count)

                                config_context['manual_steps_completed'] = True
                            else:
                                if completion_callback:
                                    completion_callback(False, "Manual steps failed after multiple attempts", config_context['name'])
                                return False

                    if completion_callback:
                        completion_callback(False, "Configuration failed", config_context['name'])
                    return False

                else:
                    from jackify.backend.handlers.menu_handler import ModlistMenuHandler
                    from jackify.backend.handlers.config_handler import ConfigHandler

                    config_handler = ConfigHandler()
                    modlist_menu = ModlistMenuHandler(config_handler)

                    if progress_callback:
                        progress_callback("Creating Steam shortcut...")

                    from jackify.backend.services.native_steam_service import NativeSteamService
                    steam_service = NativeSteamService()

                    proton_version = _get_user_proton_version()

                    success, app_id = steam_service.create_shortcut_with_proton(
                        app_name=config_context['name'],
                        exe_path=config_context['mo2_exe_path'],
                        start_dir=os.path.dirname(config_context['mo2_exe_path']),
                        launch_options="%command%",
                        tags=["Jackify"],
                        proton_version=proton_version
                    )

                    if not success or not app_id:
                        if completion_callback:
                            completion_callback(False, "Failed to create Steam shortcut", config_context['name'])
                        return False

                    config_context['appid'] = app_id

                    if progress_callback:
                        from jackify.shared.timing import get_timestamp
                        progress_callback(f"{get_timestamp()} Steam shortcut created successfully")

                    if progress_callback:
                        progress_callback("Running modlist configuration...")

                    if progress_callback:
                        progress_callback(f"About to call run_modlist_configuration_phase with context: {config_context}")

                    result = modlist_menu.run_modlist_configuration_phase(config_context)

                    if progress_callback:
                        progress_callback(f"run_modlist_configuration_phase returned: {result}")

                    if result:
                        if completion_callback:
                            completion_callback(True, "Configuration completed successfully!", config_context['name'])
                        return True
                    else:
                        if progress_callback:
                            progress_callback("Configuration failed, manual Steam/Proton setup required")
                        if manual_steps_callback:
                            if progress_callback:
                                progress_callback(f"About to call manual_steps_callback for {config_context['name']}, retry 1")
                            manual_steps_callback(config_context['name'], 1)
                        if progress_callback:
                            progress_callback("manual_steps_callback completed")

                        return True

                    if completion_callback:
                        completion_callback(False, "Configuration failed", config_context['name'])
                    return False

            finally:
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)

        except Exception as e:
            error_msg = f"Configuration failed: {str(e)}"
            if completion_callback:
                completion_callback(False, error_msg, context.get('modlist_name', 'Unknown'))
            return False
