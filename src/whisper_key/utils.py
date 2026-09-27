# utils.py
# Small cross-cutting helpers shared by nearly every module: locating the user's
# config directory, resolving bundled asset paths (source checkout vs installed
# wheel vs frozen .exe), hotkey string parsing/prettifying, version lookup, and
# the OptionalComponent shim used for gracefully-absent dependencies.
import os
import site
import subprocess
import sys
import importlib.resources
import tomllib
from pathlib import Path

class OptionalComponent:
    def __init__(self, component):
        self._component = component
    
    def __getattr__(self, name):
        if self._component and hasattr(self._component, name):
            attr = getattr(self._component, name)
            return attr
        else:
            # Return a no-op function for missing methods/attributes
            return lambda *args, **kwargs: None


def beautify_hotkey(hotkey_string: str) -> str:
    if not hotkey_string:
        return ""

    return hotkey_string.upper()

def parse_hotkey(hotkey_string: str) -> list:
    if not hotkey_string:
        return []
    return hotkey_string.lower().split('+')

def is_installed_package():
    # Check if running from an installed package
    return 'site-packages' in __file__

def get_user_app_data_path():
    # On Linux CI / unsupported platforms, .platform doesn't ship a `paths`
    # module. Fall back to ~/.whisperkey so tests and tools that just need a
    # directory keep working — actual app functionality is Windows/macOS only.
    try:
        from .platform import paths
        whisperkey_dir = paths.get_app_data_path()
    except ImportError:
        whisperkey_dir = Path.home() / ".whisperkey"
    whisperkey_dir.mkdir(parents=True, exist_ok=True)
    return str(whisperkey_dir)

def open_file(path):
    # Best-effort on Linux: log only, don't crash. Real Windows/macOS path goes
    # through the platform module's xdg-open / explorer.exe wrapper.
    try:
        from .platform import paths
        paths.open_file(path)
    except ImportError:
        import logging
        logging.getLogger(__name__).warning(f"open_file('{path}'): unsupported platform")

# True where a Tk window may only be created on the main thread (macOS; see
# platform/macos/app.py). Windows that normally run on a worker thread check
# this and either run inline on the main thread or stand down (issue #14).
# Unsupported platforms (Linux CI) have no platform backend and no constraint.
def tk_requires_main_thread() -> bool:
    try:
        from .platform import app
    except ImportError:
        return False
    return app.TK_MAIN_THREAD_ONLY

def resolve_asset_path(relative_path: str) -> str:
    if not relative_path or os.path.isabs(relative_path):
        return relative_path

    if is_installed_package():
        files = importlib.resources.files("whisper_key")
        return str(files / relative_path)

    return str(Path(__file__).parent / relative_path)

def setup_portaudio_path():
    # Called first in main.py - platform module imports break WASAPI
    if sys.platform != 'win32':
        return
    assets_dir = Path(resolve_asset_path('platform/windows/assets'))
    if assets_dir.exists():
        os.environ['PATH'] = str(assets_dir) + os.pathsep + os.environ.get('PATH', '')

# Every site-packages\nvidia\<lib>\bin folder the pip NVIDIA wheels created
# (cuBLAS, cuDNN, CUDA runtime). `roots` defaults to this interpreter's
# site-packages; tests pass their own.
def find_nvidia_dll_dirs(roots=None) -> list:
    if roots is None:
        # Runs at import on every launch, so it must never raise: embedded and
        # old-virtualenv interpreters can lack either of these functions.
        roots = []
        for getter in ('getsitepackages', 'getusersitepackages'):
            try:
                found_roots = getattr(site, getter)()
            except AttributeError:
                continue
            roots.extend([found_roots] if isinstance(found_roots, str) else found_roots)
    found = []
    for root in roots:
        for bin_dir in sorted(Path(root).glob('nvidia/*/bin')):
            if bin_dir.is_dir() and str(bin_dir) not in found:
                found.append(str(bin_dir))
    return found

# Make pip-installed CUDA libraries loadable (issue #15). GPU onboarding installs
# nvidia-cublas-cu12 / nvidia-cudnn-cu12, whose DLLs land in folders no search
# path covers: ctranslate2 registers only its own package folder, then loads
# cuBLAS/cuDNN by bare name on the first inference, so the install was invisible
# and the first transcription hung. Two registrations, because there are two
# loaders: add_dll_directory serves Python-side loads (ctypes, extension
# imports); PATH serves the plain LoadLibrary calls ctranslate2 and cuDNN make.
# Called next to setup_portaudio_path(), before ctranslate2 is imported.
def setup_nvidia_dll_path():
    if sys.platform != 'win32':
        return
    dll_dirs = find_nvidia_dll_dirs()
    if not dll_dirs:
        return
    for dll_dir in dll_dirs:
        try:
            os.add_dll_directory(dll_dir)
        except OSError:
            pass  # PATH below still covers the native loader
    current = os.environ.get('PATH', '')
    on_path = set(current.split(os.pathsep))
    new_dirs = [d for d in dll_dirs if d not in on_path]
    if new_dirs:
        os.environ['PATH'] = os.pathsep.join(new_dirs + [current])

# Find pythonw.exe for the interpreter we're running under. It normally sits
# beside python.exe, but not always: a venv created with --without-pip, and some
# Microsoft Store layouts, ship python.exe alone. Fall back to the BASE
# interpreter's pythonw (sys._base_executable) before giving up.
def _windowless_python(exe: str) -> str:
    candidates = [Path(exe).with_name("pythonw.exe")]
    base = getattr(sys, "_base_executable", None)
    if base and base != exe:
        candidates.append(Path(base).with_name("pythonw.exe"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return exe


# The single answer to "what command relaunches this app?". Used by autostart
# (windowless=True, so login doesn't pop a console) and by the tray's Restart
# item (windowless=False, so a user who launched from a console keeps it).
#
# Never build this from sys.argv. For a pip install, argv[0] is the console-script
# path, and pip only ships a compiled `whisper-local.exe` stub there — no plain
# script file — so handing it to python.exe fails with "can't open file"
# (issue #3). Invoking the module with -m is layout-independent.
#
# sys.executable is equally wrong under the standalone build: pyapp unpacks a
# private CPython and runs the app with it, so sys.executable is that interpreter,
# not the .exe. pyapp exports the real path as $PYAPP (PYAPP_PASS_LOCATION=1),
# which is what issue #2 turned on.
def build_relaunch_command(windowless: bool = False) -> list:
    exe = sys.executable

    pyapp_exe = os.environ.get("PYAPP", "")
    if pyapp_exe and os.path.isfile(pyapp_exe):
        return [pyapp_exe]

    # Frozen builds (PyInstaller-style) genuinely do have sys.executable == the app.
    if getattr(sys, "frozen", False) or exe.lower().endswith("whisper-local.exe"):
        return [exe]

    runner = _windowless_python(exe) if (windowless and sys.platform == "win32") else exe
    return [runner, "-m", "whisper_key.main"]


def restart_or_exit(message_restart, message_exit):
    pyapp_exe = os.environ.get('PYAPP', '')
    if os.path.isfile(pyapp_exe):
        print(message_restart)
        subprocess.Popen([pyapp_exe], creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        print(message_exit)
    sys.exit(0)


def get_version():
    if is_installed_package():
        import importlib.metadata
        return importlib.metadata.version("whisper-local")

    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject_path, 'rb') as f:
        data = tomllib.load(f)
        return f"{data['project']['version']}-dev"