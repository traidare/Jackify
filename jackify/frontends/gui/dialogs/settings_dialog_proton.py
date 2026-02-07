"""
Settings dialog Proton dropdown population and refresh.
"""

import logging

logger = logging.getLogger(__name__)


class SettingsDialogProtonMixin:
    """Mixin providing Proton dropdown population and refresh for SettingsDialog."""

    def _get_proton_10_path(self):
        try:
            from jackify.backend.handlers.wine_utils import WineUtils
            available_protons = WineUtils.scan_valve_proton_versions()
            for proton in available_protons:
                if proton['version'].startswith('10.'):
                    return proton['path']
            return 'auto'
        except Exception:
            return 'auto'

    def _populate_install_proton_dropdown(self):
        try:
            from jackify.backend.handlers.wine_utils import WineUtils
            available_protons = WineUtils.scan_all_proton_versions()
            has_proton = len(available_protons) > 0
            if has_proton:
                self.install_proton_dropdown.addItem("Auto (Recommended)", "auto")
            else:
                self.install_proton_dropdown.addItem("No Proton Versions Detected", "none")

            fast_protons = []
            slow_protons = []
            for proton in available_protons:
                proton_name = proton.get('name', 'Unknown Proton')
                proton_type = proton.get('type', 'Unknown')
                if proton_type not in ('GE-Proton', 'Valve-Proton'):
                    logger.debug(
                        "Skipping %s (%s) from Install Proton dropdown - third-party builds may have compatibility issues",
                        proton_name, proton_type
                    )
                    continue
                slow_warning = False
                is_fast_proton = False
                display_name = proton_name
                if proton_name == "Proton - Experimental":
                    is_fast_proton = True
                elif proton_type == 'GE-Proton':
                    major_version = proton.get('major_version')
                    if major_version is not None and isinstance(major_version, int) and major_version >= 10:
                        is_fast_proton = True
                    elif 'GE-Proton9' in proton_name or 'GE-Proton8' in proton_name:
                        slow_warning = True
                    display_name = f"{proton_name} (GE)"
                elif proton_type == 'Valve-Proton':
                    if proton_name.startswith("Proton 9") or "9.0" in proton_name:
                        slow_warning = True
                if slow_warning:
                    display_name = f"{display_name} (Slow texture processing)"
                    slow_protons.append((display_name, str(proton['path'])))
                else:
                    fast_protons.append((display_name, str(proton['path'])))

            for display_name, path in fast_protons:
                self.install_proton_dropdown.addItem(display_name, path)
            if slow_protons:
                self.install_proton_dropdown.insertSeparator(self.install_proton_dropdown.count())
                for display_name, path in slow_protons:
                    self.install_proton_dropdown.addItem(display_name, path)
            saved_proton = self.config_handler.get('proton_path', self._get_proton_10_path())
            self._set_dropdown_selection(self.install_proton_dropdown, saved_proton)
        except Exception as e:
            logger.error("Failed to populate install Proton dropdown: %s", e)
            self.install_proton_dropdown.addItem("Auto (Recommended)", "auto")

    def _populate_game_proton_dropdown(self):
        try:
            from jackify.backend.handlers.wine_utils import WineUtils
            available_protons = WineUtils.scan_all_proton_versions()
            self.game_proton_dropdown.addItem("Same as Install Proton", "same_as_install")
            for proton in available_protons:
                proton_name = proton.get('name', 'Unknown Proton')
                proton_type = proton.get('type', 'Unknown')
                display_name = f"{proton_name} (GE)" if proton_type == 'GE-Proton' else proton_name
                self.game_proton_dropdown.addItem(display_name, str(proton['path']))
            saved_game_proton = self.config_handler.get('game_proton_path', 'same_as_install')
            self._set_dropdown_selection(self.game_proton_dropdown, saved_game_proton)
        except Exception as e:
            logger.error("Failed to populate game Proton dropdown: %s", e)
            self.game_proton_dropdown.addItem("Same as Install Proton", "same_as_install")

    def _set_dropdown_selection(self, dropdown, saved_value):
        found_match = False
        for i in range(dropdown.count()):
            if dropdown.itemData(i) == saved_value:
                dropdown.setCurrentIndex(i)
                found_match = True
                break
        if not found_match and saved_value not in ["auto", "same_as_install"]:
            dropdown.setCurrentIndex(0)

    def _refresh_install_proton_dropdown(self):
        current_selection = self.install_proton_dropdown.currentData()
        self.install_proton_dropdown.clear()
        self._populate_install_proton_dropdown()
        self._set_dropdown_selection(self.install_proton_dropdown, current_selection)

    def _refresh_game_proton_dropdown(self):
        current_selection = self.game_proton_dropdown.currentData()
        self.game_proton_dropdown.clear()
        self._populate_game_proton_dropdown()
        self._set_dropdown_selection(self.game_proton_dropdown, current_selection)
