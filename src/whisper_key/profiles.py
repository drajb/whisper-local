# profiles.py
# Named presets (Dictation / Chat / Code / Notes / Translate) that flip several
# settings at once from the tray, so switching context doesn't mean editing YAML.
# A profile applies a small patch over current settings rather than replacing
# them, leaving unrelated user choices untouched.
from pathlib import Path
from typing import Dict, List, Optional

from ruamel.yaml import YAML

from .defaults_merge import load_layered, shipped_value
from .utils import get_user_app_data_path

PROFILES_FILE = "profiles.yaml"
PROFILES_DEFAULTS = "profiles.defaults.yaml"

USER_FILE_HEADER = """\
# Whisper Local — your profiles
#
# The profiles that ship with the app are applied underneath this file, so they
# keep improving with each update. Here you only write what's yours:
#
#   profiles:
#     # one of your own
#     meetings:
#       description: Long-form notes
#       overrides:
#         whisper:
#           model: small
#
#     # change a shipped one, naming it and only what you want different.
#     # `overrides` is taken whole, so list every section you want that
#     # profile to set, not just the one you're changing.
#     code:
#       overrides:
#         whisper:
#           model: medium
#
#     # turn a shipped one off
#     translate:
#       disabled: true
#
# Shipped profiles: dictation, chat, code, notes, translate.
# `active` below is managed by the tray menu.

"""


class ProfileManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.profiles: Dict[str, dict] = {}
        self.active: Optional[str] = None
        self._load()

    def _load(self):
        user_path = Path(get_user_app_data_path()) / PROFILES_FILE
        self.profiles, data = load_layered(
            PROFILES_DEFAULTS, user_path, "profiles", USER_FILE_HEADER,
            mapping=True)
        # A fresh user file holds no `active`, so fall back to the shipped one.
        self.active = data.get("active") or shipped_value(PROFILES_DEFAULTS, "active")

    def list_profiles(self) -> List[str]:
        return list(self.profiles.keys())

    def get_active(self) -> Optional[str]:
        return self.active

    def apply(self, name: str) -> bool:
        if name not in self.profiles:
            return False
        overrides = self.profiles[name].get("overrides", {})
        for section, values in overrides.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                self.config_manager.update_user_setting(section, key, value)
        self.active = name
        self._persist_active()
        return True

    def _persist_active(self):
        path = Path(get_user_app_data_path()) / PROFILES_FILE
        if not path.exists():
            return
        try:
            yaml = YAML()
            with open(path, encoding="utf-8") as f:
                data = yaml.load(f) or {}
            data["active"] = self.active
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f)
        except Exception:
            pass
