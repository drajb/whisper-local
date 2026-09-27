# app_rules.py
# Per-application behaviour overrides driven by `app_rules.yaml`: match the
# foreground app and adjust delivery (auto-send, copy-only, suppress entirely)
# and formatting (verbatim in a code editor, full sentences in email). The
# foreground-detection import is deliberately lazy so this module stays
# importable in lean/test environments without the platform backend installed.
import logging
import shutil
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

# `foreground` is imported lazily inside match_for_foreground: the .platform
# chain pulls in OS-specific deps (pywin32 / pyobjc) that lean environments
# (CI smoke tests, dev checkouts) don't have. Keeping it lazy lets app_rules —
# and its pure formatting_overrides() helper — import anywhere.
from .utils import get_user_app_data_path, resolve_asset_path

USER_FILE = "app_rules.yaml"
DEFAULTS_FILE = "app_rules.defaults.yaml"

# Post-processing toggles a rule may override per app (e.g. code editors: no
# auto-capitalization or trailing periods; email: full sentences). Only keys
# present in the rule override the global postprocess config.
FORMATTING_KEYS = ('capitalize_first', 'ensure_punctuation',
                   'strip_trailing_period', 'inline_formatting',
                   'lowercase', 'list_formatting')


# A rule's formatting overrides: its `style` expanded into toggles first, then
# any toggle the rule sets explicitly, which wins over the style.
def formatting_overrides(rule, postprocess_cfg: dict = None) -> dict:
    if not rule:
        return {}
    from .styles import resolve_style
    overrides = resolve_style(rule.get('style'), postprocess_cfg)
    overrides.update({k: bool(rule[k]) for k in FORMATTING_KEYS if k in rule})
    return overrides


# The postprocess config for one delivery. Precedence, lowest to highest:
# global toggles < global `style` < the app rule's style < the rule's explicit
# toggles. The style is resolved here, once, so postprocess() can't re-apply
# the global one over a rule's choice.
def effective_postprocess_config(postprocess_cfg: dict, rule=None) -> dict:
    from .styles import resolve_style
    cfg = dict(postprocess_cfg or {})
    cfg.update(resolve_style(cfg.pop('style', None), cfg))
    cfg.update(formatting_overrides(rule, cfg))
    return cfg


class AppRules:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rules: list = []
        self._mtime = 0.0
        self._path: Optional[Path] = None
        self._load()

    def _load(self):
        user_path = Path(get_user_app_data_path()) / USER_FILE
        if not user_path.exists():
            defaults = Path(resolve_asset_path(DEFAULTS_FILE))
            if defaults.exists():
                shutil.copy2(defaults, user_path)

        if not user_path.exists():
            return

        self._path = user_path
        self._reload_from_disk()

    def _reload_from_disk(self):
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = YAML().load(f) or {}
            self.rules = data.get("rules", []) or []
            self._mtime = self._path.stat().st_mtime
        except Exception as e:
            self.logger.error(f"Failed to load {self._path}: {e}")

    def _reload_if_changed(self):
        if not self._path:
            return
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if mtime > self._mtime:
            self.logger.info(f"Reloading {self._path}")
            self._reload_from_disk()

    def match_for_foreground(self) -> Optional[dict]:
        self._reload_if_changed()
        if not self.rules:
            return None
        from .platform import foreground
        info = foreground.get_foreground_app()
        if not info:
            return None
        exe = info.get('exe', '').lower()
        title = info.get('title', '').lower()
        if not exe and not title:
            return None
        for rule in self.rules:
            if self._matches(rule, exe, title):
                return rule
        return None

    def _matches(self, rule: dict, exe: str, title: str) -> bool:
        patterns = rule.get('match')
        if isinstance(patterns, str):
            patterns = [patterns]
        if not patterns:
            return False
        for pattern in patterns:
            p = str(pattern).lower()
            if p and (p in exe or p in title):
                return True
        return False
