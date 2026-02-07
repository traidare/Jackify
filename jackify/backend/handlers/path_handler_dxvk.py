#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXVK config mixin for PathHandler.
Extracted from path_handler for file-size and domain separation.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class PathHandlerDXVKMixin:
    """Mixin providing DXVK config creation and verification."""

    @staticmethod
    def _normalize_common_library_path(steam_library: Optional[str]) -> Optional[Path]:
        if not steam_library:
            return None
        path = Path(steam_library)
        parts_lower = [part.lower() for part in path.parts]
        if len(parts_lower) >= 2 and parts_lower[-2:] == ['steamapps', 'common']:
            return path
        if parts_lower and parts_lower[-1] == 'common':
            return path
        if 'steamapps' in parts_lower:
            idx = parts_lower.index('steamapps')
            truncated = Path(*path.parts[:idx + 1])
            return truncated / 'common'
        return path / 'steamapps' / 'common'

    @staticmethod
    def _build_dxvk_candidate_dirs(modlist_dir, stock_game_path, steam_library, game_var_full, vanilla_game_dir) -> List[Path]:
        candidates: List[Path] = []
        seen = set()

        def add_candidate(path_obj: Optional[Path]):
            if not path_obj:
                return
            key = path_obj.resolve() if path_obj.exists() else path_obj
            if key in seen:
                return
            seen.add(key)
            candidates.append(path_obj)

        if stock_game_path:
            add_candidate(Path(stock_game_path))
        if modlist_dir:
            base_path = Path(modlist_dir)
            common_names = [
                "Stock Game", "Game Root", "STOCK GAME", "Stock Game Folder",
                "Stock Folder", "Skyrim Stock", os.path.join("root", "Skyrim Special Edition")
            ]
            for name in common_names:
                add_candidate(base_path / name)
        steam_common = PathHandlerDXVKMixin._normalize_common_library_path(steam_library)
        if steam_common and game_var_full:
            add_candidate(steam_common / game_var_full)
        if vanilla_game_dir:
            add_candidate(Path(vanilla_game_dir))
        if modlist_dir:
            add_candidate(Path(modlist_dir))
        return candidates

    @staticmethod
    def create_dxvk_conf(modlist_dir, modlist_sdcard, steam_library, basegame_sdcard, game_var_full,
                         vanilla_game_dir=None, stock_game_path=None) -> bool:
        """Create dxvk.conf file in the appropriate location."""
        try:
            logger.info("Creating dxvk.conf file...")
            candidate_dirs = PathHandlerDXVKMixin._build_dxvk_candidate_dirs(
                modlist_dir=modlist_dir, stock_game_path=stock_game_path, steam_library=steam_library,
                game_var_full=game_var_full, vanilla_game_dir=vanilla_game_dir
            )
            if not candidate_dirs:
                logger.error("Could not determine location for dxvk.conf (no candidate directories found)")
                return False
            target_dir = None
            for directory in candidate_dirs:
                if directory.is_dir():
                    target_dir = directory
                    break
            if target_dir is None:
                fallback_dir = Path(modlist_dir) if modlist_dir and Path(modlist_dir).is_dir() else None
                if fallback_dir:
                    logger.warning(f"No stock/vanilla directories found; falling back to modlist directory: {fallback_dir}")
                    target_dir = fallback_dir
                else:
                    logger.error("All candidate directories for dxvk.conf are missing.")
                    return False
            dxvk_conf_path = target_dir / "dxvk.conf"
            required_line = "dxvk.enableGraphicsPipelineLibrary = False"
            if dxvk_conf_path.exists():
                try:
                    with open(dxvk_conf_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read().strip()
                    existing_lines = existing_content.split('\n') if existing_content else []
                    has_required_line = any(line.strip() == required_line for line in existing_lines)
                    if has_required_line:
                        logger.info("Required DXVK setting already present in existing file")
                        return True
                    updated_content = existing_content + '\n' + required_line + '\n' if existing_content else required_line + '\n'
                    with open(dxvk_conf_path, 'w', encoding='utf-8') as f:
                        f.write(updated_content)
                    logger.info(f"dxvk.conf updated successfully at {dxvk_conf_path}")
                    return True
                except Exception as e:
                    logger.error(f"Error reading/updating existing dxvk.conf: {e}")
                    logger.info("Falling back to creating new dxvk.conf file")
            dxvk_conf_content = required_line + '\n'
            dxvk_conf_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dxvk_conf_path, 'w', encoding='utf-8') as f:
                f.write(dxvk_conf_content)
            logger.info(f"dxvk.conf created successfully at {dxvk_conf_path}")
            return True
        except Exception as e:
            logger.error(f"Error creating dxvk.conf: {e}")
            return False

    @staticmethod
    def verify_dxvk_conf_exists(modlist_dir, steam_library, game_var_full, vanilla_game_dir=None,
                                stock_game_path=None) -> bool:
        """Verify that dxvk.conf exists in at least one candidate directory and contains the required setting."""
        required_line = "dxvk.enableGraphicsPipelineLibrary = False"
        candidate_dirs = PathHandlerDXVKMixin._build_dxvk_candidate_dirs(
            modlist_dir=modlist_dir, stock_game_path=stock_game_path, steam_library=steam_library,
            game_var_full=game_var_full, vanilla_game_dir=vanilla_game_dir
        )
        for directory in candidate_dirs:
            conf_path = directory / "dxvk.conf"
            if conf_path.is_file():
                try:
                    with open(conf_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if required_line not in content:
                        logger.warning(f"dxvk.conf found at {conf_path} but missing required setting. Appending now.")
                        with open(conf_path, 'a', encoding='utf-8') as f:
                            if not content.endswith('\n'):
                                f.write('\n')
                            f.write(required_line + '\n')
                    logger.info(f"Verified dxvk.conf at {conf_path}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to verify dxvk.conf at {conf_path}: {e}")
        logger.warning("dxvk.conf verification failed - file not found in any candidate directory.")
        return False
