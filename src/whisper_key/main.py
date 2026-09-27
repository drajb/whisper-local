#!/usr/bin/env python3
# main.py
# Entry point invoked by the `whisper-local` and `wl` console scripts (see
# pyproject.toml [project.scripts]). Responsible for:
#   1. CLI argument parsing — every --flag dispatches to a module
#   2. Logging + crash handler setup
#   3. Single-instance enforcement (mutex / PID file)
#   4. Wiring all the components together (audio, whisper, hotkeys, tray)
#   5. Driving the platform event loop until shutdown
#
# Most --flags short-circuit and exit before the heavy app is even constructed,
# so utility commands like --version, --doctor, --settings stay fast.

from .utils import setup_nvidia_dll_path, setup_portaudio_path
# PortAudio DLLs ship inside the package on Windows; this prepends the right
# directory to PATH *before* sounddevice tries to load them.
setup_portaudio_path()
# Same idea for the CUDA libraries GPU onboarding pip-installs: ctranslate2
# can't find them on its own, and a CUDA model without them hangs (issue #15).
setup_nvidia_dll_path()

import argparse
import logging
import os
import signal
import sys
import threading

from .platform import app, permissions, console
from .config_manager import ConfigManager
from .audio_recorder import AudioRecorder
from .hotkey_listener import HotkeyListener
from .whisper_engine import WhisperEngine
from .voice_activity_detection import VadManager
from .clipboard_manager import ClipboardManager
from .state_manager import StateManager
from .system_tray import SystemTray
from .audio_feedback import AudioFeedback
from .terminal_title import TerminalTitle
from .instance_manager import cleanup_pid_file, guard_against_multiple_instances
from .model_registry import ModelRegistry
from .streaming_manager import StreamingManager
from .voice_commands import VoiceCommandManager
from .hardware_detection import detect_and_print as detect_hardware
from .onboarding import check_gpu
from .utils import get_user_app_data_path, get_version

def setup_logging(config_manager: ConfigManager):
    log_config = config_manager.get_logging_config()
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Set to lowest level, handlers will filter
    
    root_logger.handlers.clear()
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    if log_config['file']['enabled']:
        from logging.handlers import RotatingFileHandler
        whisperkey_dir = get_user_app_data_path()
        log_file_path = os.path.join(whisperkey_dir, log_config['file']['filename'])
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=5_000_000, backupCount=3, encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_config['level']))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    if log_config['console']['enabled']:
        console_handler = logging.StreamHandler()
        console_level = log_config['console'].get('level', 'WARNING')
        console_handler.setLevel(getattr(logging, console_level))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

def setup_exception_handler():
    def exception_handler(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.getLogger().error(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
        _write_crash_report(exc_type, exc_value, exc_traceback)

    sys.excepthook = exception_handler


def _send_quit_to_running_instance() -> int:
    import signal
    from pathlib import Path
    pid_file = Path(get_user_app_data_path()) / "WhisperKeyLocal.pid"
    if not pid_file.exists():
        print("No running Whisper Local instance found.")
        return 0
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        print("PID file is unreadable; removing.")
        try: pid_file.unlink()
        except OSError: pass
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")
        return 0
    except (ProcessLookupError, PermissionError, OSError):
        print(f"No running instance (stale PID {pid}); removing PID file.")
        try: pid_file.unlink()
        except OSError: pass
        return 0


def _write_crash_report(exc_type, exc_value, exc_traceback):
    import datetime
    import traceback
    try:
        crash_dir = os.path.join(get_user_app_data_path(), "crashes")
        os.makedirs(crash_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        crash_path = os.path.join(crash_dir, f"crash-{stamp}.txt")
        with open(crash_path, 'w', encoding='utf-8') as f:
            f.write(f"Whisper Local crash report\nTime: {datetime.datetime.now().isoformat()}\n")
            f.write(f"Version: {get_version()}\nPython: {sys.version}\n\n")
            f.write("Traceback:\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write("\nLast 50 log lines:\n")
            log_path = os.path.join(get_user_app_data_path(), "app.log")
            if os.path.exists(log_path):
                with open(log_path, encoding='utf-8', errors='replace') as logf:
                    f.writelines(logf.readlines()[-50:])
        print(f"\nCrash report written to: {crash_path}\n")
    except Exception:
        pass

def setup_audio_recorder(audio_config, state_manager, vad_manager, streaming_manager):
    return AudioRecorder(
        channels=audio_config['channels'],
        dtype=audio_config['dtype'],
        max_duration=audio_config['max_duration'],
        on_max_duration_reached=state_manager.handle_max_recording_duration_reached,
        on_vad_event=state_manager.handle_vad_event,
        vad_manager=vad_manager,
        streaming_manager=streaming_manager,
        on_streaming_result=state_manager.handle_streaming_result,
        device=audio_config['input_device'],
        noise_suppression_config=audio_config.get('noise_suppression') or {},
        whisper_mode_config=audio_config.get('whisper_mode') or {},
    )

def setup_vad(vad_config):
    return VadManager(
        vad_precheck_enabled=vad_config['vad_precheck_enabled'],
        vad_realtime_enabled=vad_config['vad_realtime_enabled'],
        vad_onset_threshold=vad_config['vad_onset_threshold'],
        vad_offset_threshold=vad_config['vad_offset_threshold'],
        vad_min_speech_duration=vad_config['vad_min_speech_duration'],
        vad_silence_timeout_seconds=vad_config['vad_silence_timeout_seconds']
    )

def setup_streaming(streaming_config, model_registry):
    return StreamingManager(
        streaming_enabled=streaming_config.get('streaming_enabled', False),
        streaming_model=streaming_config.get('streaming_model', 'standard'),
        model_registry=model_registry
    )

def setup_whisper_engine(whisper_config, vad_manager, model_registry, log_transcriptions=False, config_manager=None):
    backend = whisper_config.get('backend', 'faster_whisper')

    if backend == 'whisper_cpp':
        from .whisper_engine_cpp import WhisperEngineCpp
        return WhisperEngineCpp(
            model_key=whisper_config['model'],
            device=whisper_config['device'],
            compute_type=whisper_config['compute_type'],
            language=whisper_config['language'],
            beam_size=whisper_config['beam_size'],
            initial_prompt=whisper_config.get('initial_prompt', ''),
            hotwords=whisper_config.get('hotwords', []),
            task=whisper_config.get('task', 'transcribe'),
            vad_manager=vad_manager,
            model_registry=model_registry,
            log_transcriptions=log_transcriptions
        )

    try:
        return WhisperEngine(
            model_key=whisper_config['model'],
            device=whisper_config['device'],
            compute_type=whisper_config['compute_type'],
            language=whisper_config['language'],
            beam_size=whisper_config['beam_size'],
            initial_prompt=whisper_config.get('initial_prompt', ''),
            hotwords=whisper_config.get('hotwords', []),
            task=whisper_config.get('task', 'transcribe'),
            vad_manager=vad_manager,
            model_registry=model_registry,
            log_transcriptions=log_transcriptions
        )
    except RuntimeError as e:
        if whisper_config['device'] != 'cuda' or not config_manager:
            raise
        return _handle_gpu_failure(e, whisper_config, vad_manager, model_registry, log_transcriptions, config_manager)

def setup_clipboard_manager(clipboard_config):
    return ClipboardManager(
        auto_paste=clipboard_config['auto_paste'],
        delivery_method=clipboard_config['delivery_method'],
        paste_hotkey=clipboard_config['paste_hotkey'],
        paste_pre_paste_delay=clipboard_config['paste_pre_paste_delay'],
        paste_preserve_clipboard=clipboard_config['paste_preserve_clipboard'],
        paste_clipboard_restore_delay=clipboard_config['paste_clipboard_restore_delay'],
        type_also_copy_to_clipboard=clipboard_config['type_also_copy_to_clipboard'],
        type_auto_enter_delay=clipboard_config['type_auto_enter_delay'],
        type_auto_enter_delay_per_100_chars=clipboard_config['type_auto_enter_delay_per_100_chars'],
        macos_key_simulation_delay=clipboard_config['macos_key_simulation_delay']
    )

def setup_audio_feedback(audio_feedback_config):
    return AudioFeedback(
        enabled=audio_feedback_config['enabled'],
        transcription_complete_enabled=audio_feedback_config['transcription_complete_enabled'],
        ready_enabled=audio_feedback_config['ready_enabled'],
        start_sound=audio_feedback_config['start_sound'],
        stop_sound=audio_feedback_config['stop_sound'],
        cancel_sound=audio_feedback_config['cancel_sound'],
        transcription_complete_sound=audio_feedback_config['transcription_complete_sound'],
        ready_sound=audio_feedback_config['ready_sound']
    )

def setup_voice_commands(voice_commands_config, clipboard_manager, log_transcriptions=False, config_manager=None):
    provider = None
    if config_manager is not None:
        provider = lambda: (config_manager.get_postprocess_config().get('ollama') or {})
    return VoiceCommandManager(
        enabled=voice_commands_config['enabled'],
        clipboard_manager=clipboard_manager,
        log_transcriptions=log_transcriptions,
        ollama_config_provider=provider,
    )

def setup_system_tray(tray_config, config_manager, state_manager, model_registry, console_config=None):
    return SystemTray(
        state_manager=state_manager,
        tray_config=tray_config,
        config_manager=config_manager,
        model_registry=model_registry,
        console_config=console_config
    )

def run_gpu_onboarding(config_manager, whisper_config):
    gpu_status = config_manager.config.get('onboarding', {}).get('gpu', 'pending')
    if gpu_status != 'pending':
        return whisper_config
    # GPU onboarding is interactive (reads a keypress). Under a windowless launch
    # (pythonw / autostart, no console) there's no way to answer the prompt, so
    # defer it — leave status 'pending' and let the next normal (console) launch
    # handle it. Without this, a first-ever windowless launch on a GPU machine
    # could hang on the prompt. (sys.stdout is reassigned to devnull earlier under
    # pythonw, so sys.stdin is the reliable no-console signal here.)
    if sys.stdin is None:
        logging.getLogger(__name__).info("Skipping GPU onboarding prompt (no console); deferring to next launch")
        return whisper_config
    gpu_class, gpu_name, ct2_works = detect_hardware(whisper_config['device'])
    check_gpu(gpu_class, gpu_name, ct2_works, whisper_config['device'], config_manager)
    return config_manager.get_whisper_config()


def _handle_gpu_failure(error, whisper_config, vad_manager, model_registry, log_transcriptions, config_manager):
    from .onboarding import handle_gpu_failure
    handle_gpu_failure(error, config_manager)
    whisper_config['device'] = 'cpu'
    whisper_config['compute_type'] = 'int8'
    return setup_whisper_engine(whisper_config, vad_manager, model_registry, log_transcriptions)


def setup_signal_handlers(shutdown_event):
    def signal_handler(signum, frame):
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def setup_hotkey_listener(hotkey_config, state_manager, voice_commands_enabled=True):
    return HotkeyListener(
        state_manager=state_manager,
        recording_hotkey=hotkey_config['recording_hotkey'],
        stop_key=hotkey_config['stop_key'],
        auto_send_key=hotkey_config.get('auto_send_key'),
        cancel_combination=hotkey_config.get('cancel_combination'),
        command_hotkey=hotkey_config.get('command_hotkey') if voice_commands_enabled else None,
        rephrase_hotkey=hotkey_config.get('rephrase_hotkey'),
        pause_hotkey=hotkey_config.get('pause_hotkey'),
        transforms_manager=getattr(state_manager, 'transforms_manager', None),
        recording_mode=hotkey_config.get('recording_mode', 'push_to_talk'),
        paste_last_hotkey=hotkey_config.get('paste_last_hotkey'),
        double_tap_to_lock=bool(hotkey_config.get('double_tap_to_lock', False)),
        double_tap_window_ms=_int_setting(hotkey_config.get('double_tap_window_ms'), 400),
    )

# A numeric setting from hand-edited YAML, falling back to `default` rather
# than crashing startup over a typo.
def _int_setting(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def shutdown_app(hotkey_listener: HotkeyListener, state_manager: StateManager, logger: logging.Logger):
    try:
        if hotkey_listener and hotkey_listener.is_active():
            logger.info("Stopping hotkey listener...")
            hotkey_listener.stop_listening()
    except Exception as ex:
        logger.error(f"Error stopping hotkey listener: {ex}")

    if state_manager:
        state_manager.shutdown()

def main():
    # Under pythonw.exe (windowless launch — autostart shortcuts, the pyapp .exe
    # before it allocates a console, etc.) there is no console, so sys.stdout and
    # sys.stderr are None and every print() in the app would raise AttributeError.
    # Route them to a null sink; real diagnostics still go to app.log via the
    # logging handlers configured in setup_logging().
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8', errors='replace')
    else:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8', errors='replace')

    # Opt-in spawn probe (set WHISPER_DEBUG_SPAWN=1) — records pid/ppid/interpreter
    # at every main() entry so a duplicate-instance/relaunch can be diagnosed.
    if os.environ.get('WHISPER_DEBUG_SPAWN'):
        try:
            import datetime as _dt
            with open(os.path.join(get_user_app_data_path(), 'spawn-debug.log'), 'a', encoding='utf-8') as _f:
                _f.write(f"{_dt.datetime.now().isoformat()} pid={os.getpid()} "
                         f"ppid={os.getppid()} exe={sys.executable} argv={sys.argv}\n")
        except Exception:
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run as separate test instance')
    parser.add_argument('--doctor', action='store_true', help='Run diagnostics and exit')
    parser.add_argument('--version', action='store_true', help='Print version and exit')
    parser.add_argument('--quit', action='store_true', help='Stop a running instance and exit')
    parser.add_argument('--export-settings', metavar='PATH', help='Export user settings + commands to a directory')
    parser.add_argument('--import-settings', metavar='PATH', help='Restore user settings + commands from an export directory')
    parser.add_argument('--stats', action='store_true', help='Show transcription stats and exit')
    parser.add_argument('--setup', action='store_true', help='Run interactive setup wizard')
    parser.add_argument('--export-transcripts', metavar='PATH', help='Export transcription history to .txt / .md / .csv')
    parser.add_argument('--import-vocab', metavar='PATH', help='Scan a folder for terms and merge into whisper.hotwords')
    parser.add_argument('--add-word', metavar='WORD', help='Add a word to your hotwords dictionary')
    parser.add_argument('--remove-word', metavar='WORD', help='Remove a word from your hotwords dictionary')
    parser.add_argument('--list-dictionary', action='store_true', help='Show all words in your hotwords dictionary')
    parser.add_argument('--settings', action='store_true', help='Open the settings window')
    parser.add_argument('--history', action='store_true', help='Browse transcript history')
    # Internal: how window_launcher opens a Tk window in its own process where Tk
    # must own the main thread (macOS). Not meant to be typed by users.
    parser.add_argument('--window', choices=('cheat-sheet', 'add-word', 'fallback', 'history'),
                        help=argparse.SUPPRESS)
    parser.add_argument('--enable-autostart', action='store_true', help='Launch Whisper Local automatically at login')
    parser.add_argument('--disable-autostart', action='store_true', help='Stop launching at login')
    parser.add_argument('--selftest', action='store_true', help='Run automated self-test (mic, model, transcription, clipboard)')
    parser.add_argument('--cheat-sheet', action='store_true', help='Show your currently configured hotkeys in a window')
    parser.add_argument('--bundle-logs', metavar='PATH', nargs='?', const='', help='Create a redacted diagnostic zip for bug reports')
    parser.add_argument('--serve', action='store_true', help='Run a local OpenAI-compatible Whisper API server')
    parser.add_argument('--serve-host', default='127.0.0.1', help='Server bind host (default: 127.0.0.1)')
    parser.add_argument('--serve-port', type=int, default=7777, help='Server bind port (default: 7777)')
    parser.add_argument('--uninstall', action='store_true',
                        help='Remove settings, data, autostart entry and (optionally) downloaded models')
    parser.add_argument('--export-model', metavar='DEST', nargs='?', const='',
                        help='Copy the configured model into a portable folder for an offline '
                             'machine (defaults to your Desktop)')
    parser.add_argument('--import-model', metavar='SRC',
                        help='Install a model folder produced by --export-model and make it active')
    parser.add_argument('--keep-in-place', action='store_true',
                        help='With --import-model: reference the folder where it is (e.g. a network share) instead of copying')
    parser.add_argument('--transcribe-system', metavar='SECONDS', nargs='?', const=10, type=int,
                        help='Transcribe N seconds of system audio / loopback (default 10). '
                             'Needs the loopback extra: pip install whisper-local[loopback]. EXPERIMENTAL.')
    args = parser.parse_args()

    # '' means the flag was given with no path → export_model picks the default.
    if args.uninstall:
        from .uninstall import run_uninstall
        sys.exit(run_uninstall())

    if args.export_model is not None:
        from .model_transfer import export_model
        sys.exit(export_model(args.export_model or None))

    if args.import_model:
        from .model_transfer import import_model
        sys.exit(import_model(args.import_model, keep_in_place=args.keep_in_place))

    if args.transcribe_system is not None:  # 0 is a valid (if silly) value; None = flag absent
        from .system_audio import run_cli
        sys.exit(run_cli(args.transcribe_system))

    if args.version:
        print(f"whisper-local {get_version()}")
        sys.exit(0)

    if args.doctor:
        from .doctor import run_doctor
        sys.exit(run_doctor())

    if args.quit:
        sys.exit(_send_quit_to_running_instance())

    if args.export_settings:
        from .settings_io import export_settings
        sys.exit(export_settings(args.export_settings))

    if args.import_settings:
        from .settings_io import import_settings
        sys.exit(import_settings(args.import_settings))

    if args.stats:
        from .stats import show_stats
        sys.exit(show_stats())

    if args.setup:
        from .setup_wizard import run_wizard
        sys.exit(run_wizard())

    if args.export_transcripts:
        from .stats import export_transcripts
        sys.exit(export_transcripts(args.export_transcripts))

    if args.import_vocab:
        from .vocab_import import import_vocab
        sys.exit(import_vocab(args.import_vocab))

    if args.add_word:
        from .dictionary import add_word
        sys.exit(0 if add_word(args.add_word) else 1)

    if args.remove_word:
        from .dictionary import remove_word
        sys.exit(0 if remove_word(args.remove_word) else 1)

    if args.list_dictionary:
        from .dictionary import show_dictionary
        sys.exit(show_dictionary())

    if args.window:
        from .window_launcher import run_window
        sys.exit(run_window(args.window, sys.stdin))

    if args.settings:
        from .settings_ui import run_settings_window
        run_settings_window()
        sys.exit(0)

    if args.history:
        from .history_window import show_history
        from .utils import tk_requires_main_thread
        # Wait for the window to close. It runs on a daemon thread, so exiting
        # here would kill it on the spot — the window opened and vanished
        # immediately when launched from the tray (issue #10). On macOS Tk must
        # own the main thread, so there it runs right here instead.
        window = show_history(blocking=tk_requires_main_thread())
        if window:
            window.join()
        sys.exit(0)

    if args.enable_autostart:
        from . import autostart
        if autostart.enable():
            print("✓ Whisper Local will now start automatically when you log in.")
            sys.exit(0)
        print("✗ Could not enable autostart on this platform. See docs/distribution.md.")
        sys.exit(1)

    if args.disable_autostart:
        from . import autostart
        autostart.disable()
        print("✓ Whisper Local will no longer start automatically at login.")
        sys.exit(0)

    if args.selftest:
        from .selftest import run_selftest
        sys.exit(run_selftest())

    if args.cheat_sheet:
        from .cheat_sheet import show_cheat_sheet
        from .utils import tk_requires_main_thread
        # Same daemon-thread trap (and macOS main-thread rule) as --history above.
        window = show_cheat_sheet(blocking=tk_requires_main_thread())
        if window:
            window.join()
        sys.exit(0)

    if args.bundle_logs is not None:
        from .bundle_logs import bundle_logs
        sys.exit(bundle_logs(args.bundle_logs or None))

    if args.serve:
        from .local_server import run_server
        sys.exit(run_server(args.serve_host, args.serve_port))

    console.setup()
    sys.stdout.write("\033]0;Whisper Local\007")
    sys.stdout.flush()
    app.setup()

    instance_name = "WhisperKeyLocal_test" if args.test else "WhisperKeyLocal"
    # Keep this handle referenced for the whole process lifetime. It looks unused
    # (linters flag it), but dropping it would close the mutex/flock and let a
    # second instance start alongside this one. Do NOT "clean up" this variable.
    mutex_handle = guard_against_multiple_instances(instance_name)  # noqa: F841

    mode_label = " [TEST]" if args.test else ""
    print(f"Starting Whisper Local [{get_version()}]{mode_label}...")
    
    shutdown_event = threading.Event()
    setup_signal_handlers(shutdown_event)
    
    hotkey_listener = None
    state_manager = None
    logger = None
    
    try:
        config_manager = ConfigManager()
        setup_logging(config_manager)

        # Self-heal an autostart entry left broken by the pre-0.16.2 pyapp bug
        # (issue #2): it pointed at a bare interpreter, so boot opened a Python
        # console instead of the app. Runs after logging is up so the repair is
        # recorded; a no-op for everyone whose entry is absent or already correct.
        try:
            from . import autostart
            if autostart.repair_if_broken():
                print("   ✓ Repaired a broken 'start on login' entry from an earlier version")
        except Exception as e:
            logging.getLogger(__name__).debug(f"Autostart repair skipped: {e}")
        logger = logging.getLogger(__name__)
        setup_exception_handler()

        whisper_config = config_manager.get_whisper_config()
        audio_config = config_manager.get_audio_config()
        hotkey_config = config_manager.get_hotkey_config()
        clipboard_config = config_manager.get_clipboard_config()
        tray_config = config_manager.get_system_tray_config()
        audio_feedback_config = config_manager.get_audio_feedback_config()
        vad_config = config_manager.get_vad_config()
        streaming_config = config_manager.get_streaming_config()
        voice_commands_config = config_manager.get_voice_commands_config()
        console_config = config_manager.get_console_config()
        log_config = config_manager.get_logging_config()
        log_transcriptions = log_config.get('log_transcriptions', False)

        whisper_config = run_gpu_onboarding(config_manager, whisper_config)

        model_registry = ModelRegistry(
            whisper_models_config=whisper_config.get('models', {}),
            streaming_models_config=streaming_config.get('models', {})
        )
        vad_manager = setup_vad(vad_config)
        streaming_manager = setup_streaming(streaming_config, model_registry)
        whisper_engine = setup_whisper_engine(whisper_config, vad_manager, model_registry, log_transcriptions, config_manager)
        streaming_manager.initialize()
        clipboard_manager = setup_clipboard_manager(clipboard_config)
        audio_feedback = setup_audio_feedback(audio_feedback_config)
        voice_command_manager = setup_voice_commands(voice_commands_config, clipboard_manager, log_transcriptions, config_manager)

        # Terminal tab title mirrors app state for people running in a visible
        # terminal. Self-disables when stdout isn't a TTY, so it costs nothing
        # under a windowless launch.
        terminal_title = TerminalTitle(config_manager.get_terminal_title_config())
        state_manager = StateManager(
            audio_recorder=None,
            whisper_engine=whisper_engine,
            clipboard_manager=clipboard_manager,
            system_tray=None,
            config_manager=config_manager,
            audio_feedback=audio_feedback,
            vad_manager=vad_manager,
            voice_command_manager=voice_command_manager,
            terminal_title=terminal_title
        )
        audio_recorder = setup_audio_recorder(audio_config, state_manager, vad_manager, streaming_manager)
        system_tray = setup_system_tray(tray_config, config_manager, state_manager, model_registry, console_config)
        state_manager.attach_components(audio_recorder, system_tray)
        
        try:
            hotkey_listener = setup_hotkey_listener(hotkey_config, state_manager, voice_commands_config['enabled'])
            state_manager.set_hotkey_listener(hotkey_listener)
        except Exception as hotkey_error:
            logger.error(f"Hotkey registration failed: {hotkey_error}")
            print(f"\n❌ Could not register hotkeys ({hotkey_error}).")
            print("   Likely cause: another app is holding the same combination.")
            print(f"   Check the recording_hotkey in user_settings.yaml: {hotkey_config.get('recording_hotkey')}")
            raise

        system_tray.start()
        terminal_title.start()

        if clipboard_config['auto_paste']:
            if not permissions.check_accessibility_permission():
                if not permissions.handle_missing_permission(config_manager):
                    app.run_event_loop(shutdown_event)
                    return
                clipboard_manager.update_auto_paste(False)

        print("🚀 Whisper Local ready!")
        # Audible counterpart to the message above: on a cold start the model
        # load is slow and the app has no window, so the chime is how a user
        # knows the hotkey is finally live without watching the console.
        audio_feedback.play_ready_sound()
        config_manager.print_startup_hotkey_instructions()
        print("   [CTRL+C] to quit", flush=True)

        try:
            from .onboarding_tutorial import needs_tutorial, show_console_welcome
            from .utils import beautify_hotkey
            if needs_tutorial():
                hk = {
                    'record': beautify_hotkey(hotkey_config.get('recording_hotkey', '')),
                    'rephrase': beautify_hotkey(hotkey_config.get('rephrase_hotkey', '')),
                    'command': beautify_hotkey(hotkey_config.get('command_hotkey', '')) if voice_commands_config['enabled'] else '',
                    'cancel': beautify_hotkey(hotkey_config.get('cancel_combination', '')),
                    'pause': beautify_hotkey(hotkey_config.get('pause_hotkey', '')),
                }
                show_console_welcome(hotkeys=hk, notify=lambda msg: system_tray.notify(msg))
        except Exception as e:
            logger.debug(f"Onboarding skipped: {e}")

        try:
            from .first_run import is_first_run, show_welcome_window
            from .utils import beautify_hotkey
            if is_first_run():
                # Blocks here on macOS, where Tk must own the main thread for
                # as long as the window is open (issue #14).
                show_welcome_window(
                    hotkey_label=beautify_hotkey(hotkey_config.get('recording_hotkey', 'ctrl+win')),
                    shutdown_event=shutdown_event,
                )
        except Exception as e:
            logger.debug(f"First-run welcome skipped: {e}")

        try:
            from .stats import maybe_show_daily_summary
            summary = maybe_show_daily_summary(lambda msg: system_tray.notify(msg))
            if summary:
                print(f"\n📈 {summary}")
        except Exception as e:
            logger.debug(f"Daily summary skipped: {e}")

        try:
            from .update_check import maybe_check_for_update
            update_cfg = config_manager.config.get('update_check') or {}
            maybe_check_for_update(lambda msg: system_tray.notify(msg), update_cfg)
        except Exception as e:
            logger.debug(f"Update check skipped: {e}")

        system_tray.apply_console_settings()

        app.run_event_loop(shutdown_event)
            
    except KeyboardInterrupt:
        logger.info("Application shutting down...")
        print("\nShutting down application...")
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Error occurred: {e}")
        
    finally:
        shutdown_app(hotkey_listener, state_manager, logger)
        cleanup_pid_file(instance_name)

if __name__ == "__main__":
    main()
