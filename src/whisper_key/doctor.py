# doctor.py
# `whisper-local --doctor` health check. Walks runtime, dependencies, config,
# audio devices, Whisper model cache, hotkeys, post-process/Ollama, transforms,
# and recent log errors, printing a per-section report. Exit 0 = clean, 1 = issues.

import importlib
import os
import platform
import sys
from pathlib import Path

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

OK = f"{GREEN}[OK]{RESET}  "
WARN = f"{YELLOW}[!]{RESET}   "
FAIL = f"{RED}[X]{RESET}   "
INFO = f"{DIM}[i]{RESET}   "

REQUIRED_PACKAGES = [
    "faster_whisper", "ctranslate2", "numpy", "soxr", "sounddevice",
    "pyperclip", "ruamel.yaml", "pystray", "PIL", "playsound3", "ten_vad",
]


class Check:
    def __init__(self, name):
        self.name = name
        self.status = None
        self.detail = ""

    def ok(self, detail=""):
        self.status = OK
        self.detail = detail
        return self

    def warn(self, detail=""):
        self.status = WARN
        self.detail = detail
        return self

    def fail(self, detail=""):
        self.status = FAIL
        self.detail = detail
        return self

    def info(self, detail=""):
        self.status = INFO
        self.detail = detail
        return self

    def print(self):
        line = f"{self.status}{self.name}"
        if self.detail:
            line += f"  {DIM}{self.detail}{RESET}"
        print(line)


def run_doctor() -> int:
    print(f"\n{BOLD}Whisper Local — Doctor{RESET}\n{'=' * 24}\n")

    failures = 0
    failures += _section_runtime()
    failures += _section_packages()
    failures += _section_config()
    failures += _section_audio()
    failures += _section_model()
    failures += _section_hotkeys()
    failures += _section_postprocess_and_rules()
    failures += _section_logs()

    print()
    if failures == 0:
        print(f"{GREEN}{BOLD}All checks passed.{RESET}\n")
        return 0
    print(f"{RED}{BOLD}{failures} issue(s) found.{RESET}  Review the [X] lines above.\n")
    return 1


def _section_runtime() -> int:
    print(f"{BOLD}Runtime{RESET}")
    failures = 0

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        Check("Python version").ok(py_version).print()
    else:
        Check("Python version").fail(f"{py_version} (need ≥3.11)").print()
        failures += 1

    Check("Platform").info(f"{platform.system()} {platform.release()}").print()

    try:
        from .utils import get_version
        Check("Whisper Local version").ok(get_version()).print()
    except Exception as e:
        Check("Whisper Local version").fail(str(e)).print()
        failures += 1

    print()
    return failures


def _section_packages() -> int:
    print(f"{BOLD}Dependencies{RESET}")
    failures = 0

    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            Check(pkg).ok().print()
        except ImportError as e:
            Check(pkg).fail(str(e)).print()
            failures += 1

    if sys.platform == "win32":
        for pkg in ("win32api", "global_hotkeys"):
            try:
                importlib.import_module(pkg)
                Check(pkg).ok().print()
            except ImportError as e:
                Check(pkg).fail(str(e)).print()
                failures += 1

    print()
    return failures


def _section_config() -> int:
    print(f"{BOLD}Configuration{RESET}")
    failures = 0

    try:
        from .utils import get_user_app_data_path
        config_dir = Path(get_user_app_data_path())
        Check("Config directory").ok(str(config_dir)).print()

        if not os.access(config_dir, os.W_OK):
            Check("Config directory writable").fail("not writable").print()
            failures += 1
        else:
            Check("Config directory writable").ok().print()
    except Exception as e:
        Check("Config directory").fail(str(e)).print()
        return failures + 1

    user_settings = config_dir / "user_settings.yaml"
    failures += _check_yaml_parses("user_settings.yaml", user_settings, required=False)

    commands_yaml = config_dir / "commands.yaml"
    failures += _check_yaml_parses("commands.yaml", commands_yaml, required=False, count_key="commands")

    # What the app will actually match on, shipped commands included.
    try:
        from .defaults_merge import load_layered
        from .voice_commands import DEFAULTS_FILE, USER_FILE_HEADER
        merged, _ = load_layered(DEFAULTS_FILE, commands_yaml, "commands",
                                 USER_FILE_HEADER, id_key="trigger")
        Check("Voice commands in effect").info(f"{len(merged)} total").print()
    except Exception as e:
        Check("Voice commands in effect").warn(str(e)).print()

    try:
        from .config_manager import ConfigManager
        cfg = ConfigManager(quiet=True)
        Check("Effective config loads").ok().print()
        whisper_cfg = cfg.get_whisper_config()
        Check("Selected model").info(f"{whisper_cfg.get('model', '?')} on {whisper_cfg.get('device', '?')}").print()
        hotkey_cfg = cfg.get_hotkey_config()
        Check("Recording mode").info(hotkey_cfg.get('recording_mode', 'toggle')).print()
        Check("Recording hotkey").info(hotkey_cfg.get('recording_hotkey', '?')).print()
    except Exception as e:
        Check("Effective config loads").fail(str(e)).print()
        failures += 1

    print()
    return failures


def _check_yaml_parses(label: str, path: Path, required: bool, count_key: str = None) -> int:
    if not path.exists():
        if required:
            Check(label).fail(f"missing at {path}").print()
            return 1
        Check(label).info("not present (defaults will be used)").print()
        return 0
    try:
        from ruamel.yaml import YAML
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        detail = ""
        if count_key and isinstance(data, dict) and isinstance(data.get(count_key), list):
            # These files hold only the user's own entries now; the shipped ones
            # are layered underneath from the package, so the effective total is
            # reported separately.
            detail = f"{len(data[count_key])} of your own"
        Check(label).ok(detail).print()
        return 0
    except Exception as e:
        Check(label).fail(str(e)).print()
        return 1


def _section_audio() -> int:
    print(f"{BOLD}Audio{RESET}")
    failures = 0

    try:
        import sounddevice as sd
        from .config_manager import ConfigManager
        cfg = ConfigManager(quiet=True).get_audio_config()
        configured_host = cfg.get('host')

        default_input = sd.query_devices(kind='input')
        Check("Default input device").ok(default_input.get('name', '?')).print()
        os_host = sd.query_hostapis(default_input['hostapi'])['name']
        if configured_host:
            Check("Host API (configured)").info(f"{configured_host}  (OS default: {os_host})").print()
        else:
            Check("Host API").info(f"{os_host}  (auto-selected)").print()
        Check("Sample rate").info(f"{int(default_input.get('default_samplerate', 0))} Hz").print()
    except Exception as e:
        Check("Audio device probe").fail(str(e)).print()
        failures += 1

    print()
    return failures


def _section_model() -> int:
    print(f"{BOLD}Whisper model cache{RESET}")
    failures = 0

    try:
        from .config_manager import ConfigManager
        from .model_registry import ModelRegistry
        cfg = ConfigManager(quiet=True)
        whisper_cfg = cfg.get_whisper_config()
        backend = whisper_cfg.get('backend', 'faster_whisper')
        Check("Whisper backend").info(backend).print()
        if backend == 'whisper_cpp':
            try:
                import pywhispercpp  # noqa
                Check("pywhispercpp installed").ok(getattr(pywhispercpp, '__version__', '?')).print()
            except ImportError:
                Check("pywhispercpp installed").fail("missing — run: pip install 'whisper-local[whispercpp]'").print()
                failures += 1
        elif whisper_cfg.get('device') == 'cuda':
            failures += _check_gpu_libraries()
        streaming_cfg = cfg.get_streaming_config()
        registry = ModelRegistry(
            whisper_models_config=whisper_cfg.get('models', {}),
            streaming_models_config=streaming_cfg.get('models', {}),
        )
        model_key = whisper_cfg.get('model', 'tiny')
        cached = False
        for getter in ('is_cached', 'is_model_cached', 'get_cached_models'):
            if hasattr(registry, getter):
                try:
                    result = getattr(registry, getter)(model_key) if getter != 'get_cached_models' else getattr(registry, getter)()
                    cached = bool(result) if getter != 'get_cached_models' else (model_key in (result or []))
                    break
                except TypeError:
                    continue
        if cached:
            Check(f"Model '{model_key}' cached").ok().print()
        else:
            Check(f"Model '{model_key}' cache").info("will download on first use").print()
    except Exception as e:
        Check("Model cache check").warn(str(e)).print()

    print()
    return failures


# A CUDA config can pass every other check and still hang on the first
# transcription because cuBLAS/cuDNN won't load; that's what issue #15 looked
# like from here. Returns the number of failures (0 or 1).
def _check_gpu_libraries() -> int:
    try:
        from .hardware_detection import missing_gpu_libraries
        missing = missing_gpu_libraries()
    except Exception as e:
        Check("CUDA libraries").warn(f"could not check: {e}").print()
        return 0
    if missing:
        Check("CUDA libraries").fail(
            f"missing {', '.join(missing)} — launch Whisper Local and "
            "choose 'Re-run GPU setup' to install them"
        ).print()
        return 1
    Check("CUDA libraries").ok().print()
    return 0


def _section_hotkeys() -> int:
    print(f"{BOLD}Hotkeys{RESET}")
    failures = 0

    try:
        from .platform import hotkeys  # noqa
        Check("Hotkey backend importable").ok().print()
    except Exception as e:
        Check("Hotkey backend importable").fail(str(e)).print()
        failures += 1

    if sys.platform == "win32":
        try:
            from .platform.windows import keyboard  # noqa
            Check("Keyboard simulation backend").ok("ctypes SendInput").print()
        except Exception as e:
            Check("Keyboard simulation backend").fail(str(e)).print()
            failures += 1

    print()
    return failures


def _section_postprocess_and_rules() -> int:
    print(f"{BOLD}Post-process & app rules{RESET}")
    failures = 0

    try:
        from .config_manager import ConfigManager
        cfg = ConfigManager(quiet=True)
        post_cfg = cfg.get_postprocess_config()
        if post_cfg.get('strip_filler_words') or post_cfg.get('capitalize_first') or post_cfg.get('ensure_punctuation'):
            enabled = [k for k in ('strip_filler_words', 'capitalize_first', 'ensure_punctuation') if post_cfg.get(k)]
            Check("Text filters").ok(", ".join(enabled)).print()
        else:
            Check("Text filters").info("none enabled").print()

        ollama_cfg = post_cfg.get('ollama') or {}
        if ollama_cfg.get('enabled'):
            failures += _probe_ollama(ollama_cfg)
        else:
            Check("Ollama post-edit").info("disabled").print()
    except Exception as e:
        Check("Post-process config").warn(str(e)).print()

    try:
        from pathlib import Path
        from .utils import get_user_app_data_path
        rules_path = Path(get_user_app_data_path()) / "app_rules.yaml"
        existed = rules_path.exists()          # AppRules() creates it, so ask first
        # Report what actually applies: the shipped rules plus the user's, not
        # just the contents of their (overrides-only) file.
        from .app_rules import AppRules
        rules = AppRules().rules
        own = sum(1 for r in rules if not r.get('id'))
        detail = f"{len(rules)} rules in effect"
        if own:
            detail += f" ({own} of your own)"
        if not existed:
            detail += ", app_rules.yaml just created"
        Check("Per-app rules").ok(detail).print()
    except Exception as e:
        Check("Per-app rules").warn(str(e)).print()

    print()
    return failures


def _probe_ollama(cfg: dict) -> int:
    import json
    import urllib.error
    import urllib.request
    endpoint = cfg.get('endpoint', 'http://localhost:11434').rstrip('/')
    timeout = float(cfg.get('timeout', 5))
    try:
        with urllib.request.urlopen(f"{endpoint}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read())
        names = [m.get('name', '') for m in data.get('models', [])]
        target = cfg.get('model', 'llama3.2')
        if any(target in n for n in names):
            Check("Ollama post-edit").ok(f"{endpoint} reachable, model '{target}' available").print()
            return 0
        Check("Ollama post-edit").warn(f"{endpoint} reachable but '{target}' not pulled").print()
        return 1
    except (urllib.error.URLError, OSError) as e:
        Check("Ollama post-edit").fail(f"unreachable at {endpoint} ({e})").print()
        return 1


def _section_logs() -> int:
    print(f"{BOLD}Recent log activity{RESET}")
    failures = 0

    try:
        from .utils import get_user_app_data_path
        log_path = Path(get_user_app_data_path()) / "app.log"
        if not log_path.exists():
            Check("app.log").info("not yet created").print()
            print()
            return 0

        size_kb = log_path.stat().st_size / 1024
        Check("app.log size").info(f"{size_kb:.1f} KB").print()

        recent_errors = _scan_recent_errors(log_path)
        if recent_errors:
            Check(f"Recent errors (last 200 lines): {len(recent_errors)}").warn().print()
            for line in recent_errors[-3:]:
                print(f"   {DIM}{line.strip()[:140]}{RESET}")
        else:
            Check("No recent ERROR/CRITICAL in log").ok().print()
    except Exception as e:
        Check("Log scan").warn(str(e)).print()

    print()
    return failures


def _scan_recent_errors(log_path: Path):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-200:]
    except OSError:
        return []
    return [line for line in tail if " ERROR " in line or " CRITICAL " in line]
