# ui/theme.py
# Design tokens for light and dark, and which one is active. `ui.theme` is
# system (follow the OS), dark or light. Every window asks palette() for named
# roles (surface, text_muted, accent...) instead of hard-coding colours, so the
# two themes can never drift apart. The floating recording pill keeps its own
# fixed dark look because it sits over whatever the user is working in.

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

THEMES = ('system', 'dark', 'light')

# Roles, by what they are for rather than how they look:
#   bg / sidebar / surface / surface_hover / field   window and container fills
#   border / border_strong                           hairlines, control outlines
#   text / text_muted / text_faint                   three levels of emphasis
#   accent / accent_hover / accent_text / accent_soft  the one brand colour
#   success / warning / danger (+ _soft fills)       status
#   selection                                        selected text background
DARK = {
    'bg': '#0f1013',
    'sidebar': '#131418',
    'surface': '#18191d',
    'surface_hover': '#1f2025',
    'field': '#1d1e23',
    'border': '#2a2b31',
    'border_strong': '#3a3b43',
    'text': '#ececef',
    'text_muted': '#a3a3ad',
    'text_faint': '#71717b',
    'accent': '#6e5cff',
    'accent_hover': '#7f6fff',
    'accent_text': '#ffffff',
    'accent_soft': '#25204a',
    'success': '#3ccf7a',
    'success_soft': '#16301f',
    'warning': '#f2b544',
    'danger': '#ff6161',
    'danger_soft': '#3a1d20',
    'selection': '#3d3577',
}

LIGHT = {
    'bg': '#f6f6f8',
    'sidebar': '#eeeef2',
    'surface': '#ffffff',
    'surface_hover': '#f3f3f6',
    'field': '#f1f1f4',
    'border': '#e2e2e8',
    'border_strong': '#cdcdd5',
    'text': '#17171c',
    'text_muted': '#55555f',
    'text_faint': '#83838d',
    'accent': '#5b4bff',
    'accent_hover': '#4a3aee',
    'accent_text': '#ffffff',
    'accent_soft': '#ecebff',
    'success': '#13814f',
    'success_soft': '#e2f5ea',
    'warning': '#a8680c',
    'danger': '#d42f2f',
    'danger_soft': '#fde9e9',
    'selection': '#d8d4ff',
}

# The brand gradient (app icon, Home greeting accent). Fixed across themes.
BRAND_GRADIENT = ('#8b5cf6', '#4f6bff')

_resolved = None   # 'dark' or 'light', worked out once per process


# Whether the OS is in dark mode. Windows: the "app mode" switch in Settings >
# Personalization > Colors. macOS: AppleInterfaceStyle is "Dark" only in dark
# mode. Anything unreadable counts as light, the OS default.
def system_prefers_dark() -> bool:
    try:
        if sys.platform == 'win32':
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
        if sys.platform == 'darwin':
            out = subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                                 capture_output=True, text=True, timeout=2)
            return out.stdout.strip().lower() == 'dark'
    except Exception as e:
        logger.debug(f"Could not read the system theme: {e}")
    return False


# ui.theme from the user's settings file, read directly rather than through
# ConfigManager so any window can ask cheaply. Missing or invalid -> system.
def configured_theme() -> str:
    try:
        from pathlib import Path
        from ruamel.yaml import YAML
        from ..utils import get_user_app_data_path
        path = Path(get_user_app_data_path()) / 'user_settings.yaml'
        if path.exists():
            with open(path, encoding='utf-8') as f:
                data = YAML(typ='safe').load(f) or {}
            theme = str(((data.get('ui') or {}).get('theme')) or 'system').strip().lower()
            if theme in THEMES:
                return theme
    except Exception as e:
        logger.debug(f"Could not read ui.theme: {e}")
    return 'system'


def resolve(theme: str = None) -> str:
    theme = theme or configured_theme()
    if theme == 'system':
        return 'dark' if system_prefers_dark() else 'light'
    return theme if theme in ('dark', 'light') else 'dark'


def active() -> str:
    global _resolved
    if _resolved is None:
        _resolved = resolve()
    return _resolved


# Switches the theme for windows built from now on (the Settings page calls it
# so a change shows immediately when the hub rebuilds itself).
def set_active(theme: str):
    global _resolved
    _resolved = resolve(theme)


# The active theme's tokens, as a fresh dict the caller may keep.
def palette(theme: str = None) -> dict:
    return dict(LIGHT if (theme or active()) == 'light' else DARK)
