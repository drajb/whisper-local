# platform/macos/permissions.py
# Checks and requests the Accessibility / Input Monitoring grants that macOS
# requires before global hotkeys or synthetic keystrokes work at all. Without
# these the app appears silently broken, so failures must be explained clearly.
# Windows mirror: platform/windows/permissions.py (always-granted stubs).
import logging
import os
import signal
import sys

logger = logging.getLogger(__name__)

try:
    from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
    _appservices_available = True
except ImportError:
    _appservices_available = False
    logger.warning("ApplicationServices not available - permission checks disabled")


def _get_terminal_app_name() -> str:
    term_program = os.environ.get('TERM_PROGRAM', '')
    if 'iTerm' in term_program:
        return 'iTerm'
    elif term_program == 'Apple_Terminal':
        return 'Terminal'
    elif term_program:
        return term_program.replace('.app', '')
    return 'your terminal app'


def check_accessibility_permission() -> bool:
    if not _appservices_available:
        return True
    return AXIsProcessTrusted()


def request_accessibility_permission():
    if not _appservices_available:
        return
    options = {'AXTrustedCheckOptionPrompt': True}
    AXIsProcessTrustedWithOptions(options)


def handle_missing_permission(config_manager) -> bool:
    # Under launchd (Start on login) nobody can answer the terminal prompt
    # below. Reading a key from launchd's /dev/null stdin raised termios.error
    # and ended the app at every login (issue #19). Ask macOS instead: its
    # dialog adds the app to the Accessibility list, and a restart after the
    # grant picks it up.
    if sys.stdin is None or not sys.stdin.isatty():
        request_accessibility_permission()
        return True

    from ...terminal_ui import prompt_choice

    app_name = _get_terminal_app_name()

    title = "Auto-paste requires permission to simulate [Cmd+V] keypress..."
    options = [
        (f"Grant accessibility permission to {app_name}", "Transcribe directly to cursor, with option to auto-send"),
        ("Disable auto-paste", "Transcribe to clipboard, then manually paste"),
    ]

    choice = prompt_choice(title, options)

    if choice == 1:
        config_manager.update_user_setting('clipboard', 'auto_paste', True)
        request_accessibility_permission()
        print()
        print("Please restart Whisper Local after permission is granted")
        os.kill(os.getpid(), signal.SIGINT)
        return False
    elif choice == 2:
        config_manager.update_user_setting('clipboard', 'auto_paste', False)
        print()
        return True
    else:
        os.kill(os.getpid(), signal.SIGINT)
        return False
