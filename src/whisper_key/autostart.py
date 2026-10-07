# autostart.py
# Enable/disable launching Whisper Local automatically at login. Opt-in: nothing
# here runs unless the user ticks the first-run prompt, the tray "Start on login"
# item, or passes --enable-autostart.
#
# Windows: a value under HKCU\...\CurrentVersion\Run (stdlib winreg, no extra dep,
#          visible in Task Manager → Startup). Launches windowless (pythonw / the
#          GUI-subsystem .exe) so there's no console flash at boot.
# macOS:   a LaunchAgent plist in ~/Library/LaunchAgents. It starts the app through
#          a small helper app, so macOS permissions attach to that app.
# Other:   not supported — returns a clear message; the caller falls back to docs.

import hashlib
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

from .utils import build_relaunch_command

logger = logging.getLogger(__name__)

_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_WIN_VALUE_NAME = "WhisperLocal"
_MAC_LABEL = "com.drajb.whisper-local"


def is_supported() -> bool:
    return sys.platform in ("win32", "darwin")


# Build the command Whisper Local should be relaunched with at login. The real
# logic lives in utils.build_relaunch_command so autostart and the tray's
# Restart item can never disagree about how to start this app again — they did
# once, which is how issue #3 happened after issue #2 was fixed here only.
def _launch_command() -> list:
    return build_relaunch_command(windowless=True)


def _win_command_string() -> str:
    # winreg Run values are a single command string; quote each part with spaces.
    parts = _launch_command()
    return " ".join(f'"{p}"' if " " in p else p for p in parts)


# ── Windows (registry Run key) ──

def _win_is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as key:
            winreg.QueryValueEx(key, _WIN_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _win_stored_command() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _WIN_VALUE_NAME)
        return str(value or "")
    except (FileNotFoundError, OSError):
        return ""


# A Run entry that is a lone interpreter path with no script — the exact broken
# value the pre-fix pyapp build wrote (issue #2). Booting it opens an interactive
# Python console instead of the app. Matched narrowly (single token, no args) so
# we only ever touch entries that are genuinely broken.
def _is_broken_bare_interpreter(command: str) -> bool:
    command = (command or "").strip()
    if not command:
        return False
    if command.startswith('"'):
        end = command.find('"', 1)
        if end == -1:
            return False
        token, rest = command[1:end], command[end + 1:]
    else:
        token, _, rest = command.partition(" ")
    if rest.strip():
        return False  # has arguments (e.g. -m whisper_key.main) → fine
    # PureWindowsPath, not Path: this parses a Windows registry value, so
    # backslashes are separators even when the tests run on macOS/Linux.
    return PureWindowsPath(token).name.lower() in ("python.exe", "pythonw.exe", "python3.exe")


def _win_enable() -> bool:
    import winreg
    cmd = _win_command_string()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _WIN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
    logger.info(f"Autostart enabled (Run key): {cmd}")
    return True


def _win_disable() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _WIN_VALUE_NAME)
    except FileNotFoundError:
        pass
    logger.info("Autostart disabled (Run key removed)")
    return True


# ── macOS (LaunchAgent) ──

# launchd runs a LaunchAgent's program directly, so macOS would check
# Accessibility and Microphone against the bare Python binary, which nobody has
# granted anything (issue #19). The agent starts Whisper Local through a small
# app instead, built from platform/macos/assets/launcher.c with the command
# compiled in. macOS checks a process against the app that started it, so the
# grants land on "Whisper Local".
_MAC_LAUNCHER_SOURCE = Path(__file__).parent / "platform" / "macos" / "assets" / "launcher.c"
_MAC_LAUNCHER_NAME = "Whisper Local"
# macOS files the grants under the app's code signature, which covers this
# Info.plist. Keep it constant, with no version numbers, so rebuilds keep them.
_MAC_LAUNCHER_INFO = {
    "CFBundleExecutable": _MAC_LAUNCHER_NAME,
    "CFBundleIdentifier": _MAC_LABEL,
    "CFBundleName": _MAC_LAUNCHER_NAME,
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "1",
    "CFBundleVersion": "1",
    "LSUIElement": True,
    "NSMicrophoneUsageDescription": "Whisper Local transcribes your dictation on this Mac.",
}
_LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
               "LaunchServices.framework/Support/lsregister")


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"


# Kept out of ~/.whisperkey, which people clear to reset their settings.
def _mac_launcher_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / _MAC_LAUNCHER_NAME


def _mac_run(args, check=False, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)


# The launcher's command as C source. Every byte is written as a hex escape, so
# no path can break out of its string.
def _mac_command_header(command) -> bytes:
    strings = ", ".join('"' + "".join(f"\\x{byte:02x}" for byte in os.fsencode(arg)) + '"'
                        for arg in command)
    return f"static char *const COMMAND[] = {{{strings}, NULL}};\n".encode()


# Returns the launcher's executable for `command`, building it first if needed,
# or None if it can't be built. Building needs clang from Apple's Command Line
# Tools. It happens in a temporary folder, and the new app replaces the old one
# only once it is signed, so a failed build leaves a working launcher alone.
def _mac_build_launcher(command):
    app = _mac_launcher_dir() / f"{_MAC_LAUNCHER_NAME}.app"
    executable = app / "Contents" / "MacOS" / _MAC_LAUNCHER_NAME
    # Outside the bundle, so it isn't part of the signature.
    record = _mac_launcher_dir() / "built-from.sha256"
    try:
        header = _mac_command_header(command)
        info = plistlib.dumps(_MAC_LAUNCHER_INFO)
        built_from = hashlib.sha256(
            b"\0".join([_MAC_LAUNCHER_SOURCE.read_bytes(), header, info])).hexdigest()
        if (record.is_file() and record.read_text() == built_from
                and _mac_run(["/usr/bin/codesign", "--verify", "--strict", str(app)]).returncode == 0):
            return executable

        # Checked first because running xcrun or clang without the tools opens
        # macOS's "install the command line developer tools" dialog.
        tools = _mac_run(["/usr/bin/xcode-select", "-p"])
        if tools.returncode != 0 or not Path(tools.stdout.strip()).is_dir():
            logger.warning("Start on login needs Apple's Command Line Tools to give Whisper Local "
                           "its own permissions. Install them with: xcode-select --install")
            return None

        app.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=app.parent) as build:
            staged = Path(build) / app.name
            (staged / "Contents" / "MacOS").mkdir(parents=True)
            (staged / "Contents" / "Info.plist").write_bytes(info)
            (Path(build) / "command.h").write_bytes(header)
            _mac_run(["/usr/bin/xcrun", "clang", "-O2", "-I", build, "-framework", "ApplicationServices",
                      "-o", str(staged / "Contents" / "MacOS" / _MAC_LAUNCHER_NAME),
                      str(_MAC_LAUNCHER_SOURCE)], check=True, timeout=120)
            # The hardened runtime makes dyld ignore DYLD_* variables, so no code
            # can be injected into the launcher itself.
            _mac_run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime",
                      str(staged)], check=True)
            _mac_run(["/usr/bin/codesign", "--verify", "--strict", str(staged)], check=True)
            if app.exists():
                os.replace(app, Path(build) / "replaced.app")
            os.replace(staged, app)
        record.write_text(built_from)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Could not build the login launcher: {e}")
        return None

    # System Settings looks apps up through LaunchServices to list them under
    # Privacy & Security, and LaunchServices doesn't look in Application Support
    # on its own.
    try:
        _mac_run([_LSREGISTER, "-f", str(app)])
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Could not register the login launcher with LaunchServices: {e}")
    return executable


def _mac_is_enabled() -> bool:
    return _mac_plist_path().exists()


def _mac_enable() -> bool:
    from xml.sax.saxutils import escape
    # Without the launcher the agent runs Python directly, as before.
    launcher = _mac_build_launcher(_launch_command())
    args = [str(launcher)] if launcher else _launch_command()
    # Escape &, <, > — a username/path containing them would otherwise produce an
    # invalid plist that launchd silently refuses to load.
    args_xml = "\n".join(f"        <string>{escape(a)}</string>" for a in args)
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '    <key>Label</key>\n'
        f'    <string>{_MAC_LABEL}</string>\n'
        '    <key>ProgramArguments</key>\n'
        '    <array>\n'
        f'{args_xml}\n'
        '    </array>\n'
        '    <key>RunAtLoad</key>\n'
        '    <true/>\n'
        '</dict>\n'
        '</plist>\n'
    )
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    logger.info(f"Autostart enabled (LaunchAgent): {path}")
    return True


def _mac_disable() -> bool:
    path = _mac_plist_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    # The launcher exists only for the LaunchAgent. Turning Start on login back
    # on rebuilds it, and the same inputs give the same signature, so macOS
    # keeps the grants.
    shutil.rmtree(_mac_launcher_dir(), ignore_errors=True)
    logger.info("Autostart disabled (LaunchAgent removed)")
    return True


# ── public API ──

def is_enabled() -> bool:
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        if sys.platform == "darwin":
            return _mac_is_enabled()
    except Exception as e:
        logger.debug(f"autostart.is_enabled check failed: {e}")
    return False


# Returns True on success. Never raises — callers surface a friendly message.
def enable() -> bool:
    try:
        if sys.platform == "win32":
            return _win_enable()
        if sys.platform == "darwin":
            return _mac_enable()
        logger.warning("Autostart not supported on this platform")
        return False
    except Exception as e:
        logger.error(f"Failed to enable autostart: {e}")
        return False


def disable() -> bool:
    try:
        if sys.platform == "win32":
            return _win_disable()
        if sys.platform == "darwin":
            return _mac_disable()
        return False
    except Exception as e:
        logger.error(f"Failed to disable autostart: {e}")
        return False


# Self-heal a Run entry left broken by the pre-0.16.2 pyapp bug (issue #2), where
# autostart pointed at a bare interpreter and boot opened a Python console instead
# of the app. Called once at startup: without it, affected users would have to
# notice the problem and toggle autostart off/on themselves. Deliberately narrow —
# it only rewrites an entry that is a lone interpreter with no arguments, never one
# the user or a working version wrote. Returns True if it repaired something.
def repair_if_broken() -> bool:
    try:
        if sys.platform != "win32" or not _win_is_enabled():
            return False
        stored = _win_stored_command()
        if not _is_broken_bare_interpreter(stored):
            return False
        corrected = _win_command_string()
        if corrected.strip() == stored.strip():
            return False  # nothing better to offer; leave it alone
        _win_enable()
        logger.warning(f"Repaired broken autostart entry: {stored!r} -> {corrected!r}")
        return True
    except Exception as e:
        logger.debug(f"Autostart repair check failed: {e}")
        return False


def toggle() -> bool:
    # Returns the achieved state, not the intended one — if enable()/disable()
    # fails (e.g. permissions), the caller sees the truth.
    if is_enabled():
        disable()
        return is_enabled()
    enable()
    return is_enabled()
