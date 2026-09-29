# app_rules.py
# Per-application behaviour overrides driven by `app_rules.yaml`: match the
# foreground app and adjust delivery (auto-send, copy-only, suppress entirely)
# and formatting (verbatim in a code editor, full sentences in email). The
# foreground-detection import is deliberately lazy so this module stays
# importable in lean/test environments without the platform backend installed.
import logging
from pathlib import Path
from typing import Optional

# `foreground` is imported lazily inside match_for_foreground: the .platform
# chain pulls in OS-specific deps (pywin32 / pyobjc) that lean environments
# (CI smoke tests, dev checkouts) don't have. Keeping it lazy lets app_rules —
# and its pure formatting_overrides() helper — import anywhere.
from .defaults_merge import load_layered
from .utils import get_user_app_data_path

USER_FILE = "app_rules.yaml"
DEFAULTS_FILE = "app_rules.defaults.yaml"

USER_FILE_HEADER = """\
# Whisper Local — your per-app rules
#
# The rules that ship with the app are applied underneath this file, so they
# keep improving with each update. Here you only write what's yours:
#
#   rules:
#     # a rule of your own — these are matched before any shipped rule
#     - match: ["obsidian.exe"]
#       style: casual
#
#     # change a shipped rule, naming its id and only the keys you want different
#     - id: chat-apps
#       auto_send: false
#
#     # turn a shipped rule off
#     - id: terminals
#       disabled: true
#
# Shipped ids: password-managers, terminals, code-editors, chat-apps,
# email-clients. Run --doctor to see the rules that are actually in effect.
# This file hot-reloads on the next transcription.

"""

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


# What identified a rule before ids existed: the set of strings it matches on.
# Used once, to work out which shipped rule an old hand-copied rule came from.
def _match_identity(rule: dict) -> tuple:
    patterns = rule.get('match')
    if isinstance(patterns, str):
        patterns = [patterns]
    return tuple(sorted(str(p).lower() for p in (patterns or [])))


# Editing a shipped rule's match list is the commonest edit there is: adding
# your own editor, or dropping an app you didn't want the rule to catch. That
# changes the rule's identity, so an exact match fails and the shipped rule
# would load behind the user's, still catching whatever they removed. Picking
# the shipped rule they share the most apps with keeps their list authoritative.
def _closest_shipped(rule: dict, shipped: list):
    patterns = set(_match_identity(rule))
    if not patterns:
        return None
    best, best_overlap = None, 0
    for candidate in shipped:
        overlap = len(patterns & set(_match_identity(candidate)))
        if overlap > best_overlap:
            best, best_overlap = candidate, overlap
    return best


class AppRules:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rules: list = []
        self._mtime = 0.0
        self._path: Optional[Path] = None
        self._load()

    def _load(self):
        self._path = Path(get_user_app_data_path()) / USER_FILE
        self._reload_from_disk()

    def _reload_from_disk(self):
        if not self._path:
            return
        try:
            self.rules, _ = load_layered(
                DEFAULTS_FILE, self._path, "rules", USER_FILE_HEADER,
                id_key="id", identity=_match_identity, rematch=_closest_shipped)
            self._mtime = self._path.stat().st_mtime if self._path.exists() else 0.0
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
