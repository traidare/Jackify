"""Game detection methods for ModlistInstallCLI (Mixin)."""
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class ModlistOperationsGameDetectionMixin:
    """Mixin providing game type detection methods."""

    def detect_game_type(self, modlist_info: Optional[Dict] = None, wabbajack_file_path: Optional[Path] = None) -> Optional[str]:
        """
        Detect the game type for a modlist installation.

        Args:
            modlist_info: Dictionary containing modlist information (for online modlists)
            wabbajack_file_path: Path to .wabbajack file (for local files)

        Returns:
            Jackify game type string or None if detection fails
        """
        if wabbajack_file_path:
            self.logger.info(f"Detecting game type from .wabbajack file: {wabbajack_file_path}")
            game_type = self.wabbajack_parser.parse_wabbajack_game_type(wabbajack_file_path)
            if game_type:
                self.logger.info(f"Detected game type from .wabbajack file: {game_type}")
                return game_type
            else:
                self.logger.warning(f"Could not detect game type from .wabbajack file: {wabbajack_file_path}")
                return None
        elif modlist_info and 'game' in modlist_info:
            game_name = modlist_info['game'].lower()
            self.logger.info(f"Detecting game type from modlist info: {game_name}")

            game_mapping = {
                'skyrim special edition': 'skyrim',
                'skyrim': 'skyrim',
                'fallout 4': 'fallout4',
                'fallout new vegas': 'falloutnv',
                'oblivion': 'oblivion',
                'starfield': 'starfield',
                'oblivion remastered': 'oblivion_remastered'
            }

            game_type = game_mapping.get(game_name)
            if game_type:
                self.logger.info(f"Mapped game name '{game_name}' to game type: {game_type}")
                return game_type
            else:
                self.logger.warning(f"Unknown game name in modlist info: {game_name}")
                return None
        else:
            self.logger.warning("No modlist info or .wabbajack file path provided for game detection")
            return None

    def check_game_support(self, game_type: str) -> bool:
        """
        Check if a game type is supported by Jackify's post-install configuration.

        Args:
            game_type: Jackify game type string

        Returns:
            True if the game is supported, False otherwise
        """
        return self.wabbajack_parser.is_supported_game(game_type)
