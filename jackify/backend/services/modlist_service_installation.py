"""
Modlist installation phase for ModlistService (Mixin).

Runs engine installation only; configuration is handled separately after Steam setup.
"""

import logging
import os
import subprocess
from pathlib import Path

from ..models.modlist import ModlistContext

logger = logging.getLogger(__name__)


class ModlistServiceInstallationMixin:
    """Mixin providing install_modlist and _run_installation_only for ModlistService."""

    def install_modlist(self, context: ModlistContext,
                        progress_callback=None,
                        output_callback=None) -> bool:
        """Install a modlist (installation only, no configuration).

        Configuration must be called separately after Steam setup.
        """
        logger.info(f"Installing modlist (INSTALLATION ONLY): {context.name}")

        try:
            if not self._validate_install_context(context):
                logger.error("Invalid installation context")
                return False

            fs_handler = self._get_filesystem_handler()
            fs_handler.ensure_directory(context.install_dir)
            fs_handler.ensure_directory(context.download_dir)

            from ..core.modlist_operations import ModlistInstallCLI

            modlist_cli = ModlistInstallCLI(self.system_info)

            install_context = {
                'modlist_name': context.name,
                'install_dir': context.install_dir,
                'download_dir': context.download_dir,
                'nexus_api_key': context.nexus_api_key,
                'game_type': context.game_type,
                'modlist_value': context.modlist_value,
                'resolution': getattr(context, 'resolution', None),
                'skip_confirmation': True
            }

            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')
            os.environ['JACKIFY_GUI_MODE'] = '1'

            try:
                confirmed_context = modlist_cli.run_discovery_phase(context_override=install_context)
                if not confirmed_context:
                    logger.error("Discovery phase failed or was cancelled")
                    return False

                success = self._run_installation_only(
                    confirmed_context,
                    progress_callback=progress_callback,
                    output_callback=output_callback
                )

                if success:
                    logger.info("Modlist installation completed successfully (configuration done separately)")
                    return True
                logger.error("Modlist installation failed")
                return False

            finally:
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)

        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to install modlist {context.name}: {error_message}")

            from .resource_manager import handle_file_descriptor_error
            try:
                if any(indicator in error_message.lower() for indicator in
                       ['too many open files', 'emfile', 'resource temporarily unavailable']):
                    result = handle_file_descriptor_error(error_message, "modlist installation")
                    if result['auto_fix_success']:
                        logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                    elif result['error_detected']:
                        logger.warning(f"File descriptor issue detected but automatic fix failed. {result['recommendation']}")
                        if result.get('manual_instructions'):
                            distro = result['manual_instructions']['distribution']
                            logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
            except Exception as resource_error:
                logger.debug(f"Error checking for resource limit issues: {resource_error}")

            return False

    def _run_installation_only(self, context, progress_callback=None, output_callback=None) -> bool:
        """Run only the installation phase using the engine."""
        from ..core.modlist_operations import get_jackify_engine_path

        try:
            install_dir_context = context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]:
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)

            download_dir_context = context['download_dir']
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]:
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)

            from ..services.nexus_auth_service import NexusAuthService
            auth_service = NexusAuthService()
            current_api_key, current_oauth_info = auth_service.get_auth_for_engine()

            api_key = current_api_key or context.get('nexus_api_key')
            oauth_info = current_oauth_info or context.get('nexus_oauth_info')

            engine_path = get_jackify_engine_path()
            engine_dir = os.path.dirname(engine_path)
            if not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                if output_callback:
                    output_callback(f"Jackify Install Engine not found or not executable at: {engine_path}")
                return False

            cmd = [engine_path, 'install', '--show-file-progress']

            modlist_value = context.get('modlist_value')
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
            elif modlist_value:
                cmd += ['-m', modlist_value]
            elif context.get('machineid'):
                cmd += ['-m', context['machineid']]
            cmd += ['-o', install_dir_str, '-d', download_dir_str]

            original_env_values = {
                'NEXUS_API_KEY': os.environ.get('NEXUS_API_KEY'),
                'NEXUS_OAUTH_INFO': os.environ.get('NEXUS_OAUTH_INFO'),
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': os.environ.get('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT')
            }

            try:
                if oauth_info:
                    os.environ['NEXUS_OAUTH_INFO'] = oauth_info
                    from jackify.backend.services.nexus_oauth_service import NexusOAuthService
                    os.environ['NEXUS_OAUTH_CLIENT_ID'] = NexusOAuthService.CLIENT_ID
                    if api_key:
                        os.environ['NEXUS_API_KEY'] = api_key
                elif api_key:
                    os.environ['NEXUS_API_KEY'] = api_key
                else:
                    if 'NEXUS_API_KEY' in os.environ:
                        del os.environ['NEXUS_API_KEY']
                    if 'NEXUS_OAUTH_INFO' in os.environ:
                        del os.environ['NEXUS_OAUTH_INFO']

                os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"

                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                if output_callback:
                    output_callback(f"Launching Jackify Install Engine with command: {pretty_cmd}")

                from jackify.backend.handlers.subprocess_utils import (
                    increase_file_descriptor_limit,
                    get_clean_subprocess_env,
                )
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if output_callback:
                    if success:
                        output_callback(f"File descriptor limit: {message}")
                    else:
                        output_callback(f"File descriptor limit warning: {message}")

                clean_env = get_clean_subprocess_env()
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=False, env=clean_env, cwd=engine_dir
                )

                buffer = b''
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    buffer += chunk

                    if chunk == b'\n':
                        line = buffer.decode('utf-8', errors='replace')
                        if output_callback:
                            output_callback(line.rstrip())
                        buffer = b''
                    elif chunk == b'\r':
                        line = buffer.decode('utf-8', errors='replace')
                        if output_callback:
                            output_callback(line.rstrip())
                        buffer = b''

                if buffer:
                    line = buffer.decode('utf-8', errors='replace')
                    if output_callback:
                        output_callback(line.rstrip())

                proc.wait()
                if proc.returncode != 0:
                    if output_callback:
                        output_callback(f"Jackify Install Engine exited with code {proc.returncode}.")
                    return False
                if output_callback:
                    output_callback("Installation completed successfully")
                return True

            finally:
                for key, original_value in original_env_values.items():
                    if original_value is not None:
                        os.environ[key] = original_value
                    elif key in os.environ:
                        del os.environ[key]

        except Exception as e:
            error_msg = f"Error running Jackify Install Engine: {e}"
            logger.error(error_msg)
            if output_callback:
                output_callback(error_msg)
            return False
