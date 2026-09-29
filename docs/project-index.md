Local faster-whisper speech-to-text app with global hotkeys for Windows 10+ and macOS

Open-source project maintained as `drajb/whisper-local` by Rohit Burani. Internal Python module name remains `whisper_key`; the config directory remains `%APPDATA%\whisperkey` (`~/.whisperkey` on macOS).

- Start here: `state_manager.py` coordinates all components workflow

## Component Architecture

| Component | File | Primary Responsibility | Key Technologies |
|-----------|------|----------------------|------------------|
| **Entry Point** | `main.py` | Component initialization, signal handling | logging, threading |
| **State Coordination** | `state_manager.py` | Component orchestration & workflow | threading, logging |
| **Audio Capture** | `audio_recorder.py` | Microphone recording & audio buffering | sounddevice, numpy |
| **Audio Feedback** | `audio_feedback.py` | Recording event sound notifications | playsound3 |
| **Speech Recognition** | `whisper_engine.py` | Audio transcription using AI | faster-whisper |
| **Model Management** | `model_registry.py` | Whisper model registry & cache detection | faster-whisper |
| **Voice Activity Detection** | `voice_activity_detection.py` | Continuous VAD monitoring & silence detection | ten-vad, threading |
| **Clipboard Operations** | `clipboard_manager.py` | Text copying & auto-paste functionality | pyperclip, ctypes SendInput (Win), Quartz (Mac) |
| **Hotkey Detection** | `hotkey_listener.py` | Global hotkey monitoring | global-hotkeys (Win), NSEvent (Mac) |
| **Configuration** | `config_manager.py` | YAML settings management & validation | ruamel.yaml |
| **System Integration** | `system_tray.py` | System tray icon & menu interface | pystray, Pillow |
| **Instance Management** | `instance_manager.py` | Single instance enforcement | win32event (Win), fcntl (Mac) |
| **Voice Commands** | `voice_commands.py` | Trigger matching & command execution | subprocess |
| **Platform Abstraction** | `platform/` | OS-specific implementations | pywin32 (Win), pyobjc (Mac) |
| **GPU Onboarding** | `onboarding.py` | GPU setup prompt & package installation | subprocess |
| **Hardware Detection** | `hardware_detection.py` | Platform GPU detection wrapper | - |
| **Terminal UI** | `terminal_ui.py` | Interactive terminal prompts | - |
| **Utilities** | `utils.py` | Common utility functions | - |
| **Diagnostics** | `doctor.py` | `--doctor` health checks across all subsystems | - |
| **Self-Test** | `selftest.py` | `--selftest` automated mic/model/transcribe/clipboard check | sounddevice |
| **Log Bundler** | `bundle_logs.py` | `--bundle-logs` redacted diagnostic zip for bug reports | zipfile, re |
| **Local API Server** | `local_server.py` | `--serve` OpenAI-compatible Whisper HTTP endpoint | http.server |
| **Settings GUI** | `settings_ui.py` | `--settings` Tkinter settings editor with search | tkinter |
| **Transcript History** | `history_window.py` + `transcript_log.py` | `--history` searchable journal of past transcriptions | tkinter, json |
| **Hotkey Cheat Sheet** | `cheat_sheet.py` | Window listing currently configured hotkeys | tkinter |
| **Window Launcher** | `window_launcher.py` | Opens Tk windows in a child process where Tk needs the main thread (macOS) | subprocess, json |
| **First-Run Welcome** | `first_run.py` | One-time onboarding window on first launch | tkinter |
| **Terminal Title** | `terminal_title.py` | Animated terminal tab title reflecting app state | - |
| **Level Overlay** | `level_overlay.py` | Floating level meter + streaming text pill | tkinter |
| **Fallback Window** | `fallback_window.py` | Capture window when no text field is focused | tkinter |
| **Transforms** | `transforms.py` | Wispr-style AI text transforms via Ollama | ruamel.yaml |
| **Dictionary** | `dictionary.py` | Hotword add/remove/list + add-word dialog | tkinter, ruamel.yaml |
| **Profiles** | `profiles.py` | Dictation/Chat/Code/Notes/Translate presets | ruamel.yaml |
| **Per-App Rules** | `app_rules.py` | Foreground-app-specific behaviour overrides | ruamel.yaml |
| **Layered Defaults** | `defaults_merge.py` | Loads shipped defaults under the user's app_rules/commands/transforms/profiles, and migrates pre-0.21 full copies | ruamel.yaml |
| **Text Post-Process** | `text_postprocess.py` | Inline formatting, smart formatting, voice editing, corrections + optional Ollama polish | urllib |
| **Dictation Cleanup** | `dictation_cleanup.py` | Backtrack ("actually 3"), stutter removal, spoken lists, lowercase | re |
| **Snippets** | `snippets.py` | Spoken shortcuts expanded inline during dictation | re |
| **Styles** | `styles.py` | Named writing styles (formal/casual/very casual/verbatim), global or per app | - |
| **Hotkey Gestures** | `hotkey_gestures.py` | Double-tap-to-lock state machine for push-to-talk | threading |
| **Whisper Mode** | `audio_gain.py` | Boosts quiet recordings before transcription | numpy |
| **Corrections** | `corrections.py` | Persist post-transcription replacements (history "Fix this everywhere") | ruamel.yaml |
| **System Audio** | `system_audio.py` | `--transcribe-system` loopback capture (experimental, opt-in) | soundcard |
| **Streaming** | `streaming_manager.py` + `streaming_recognizer.py` | Real-time partial transcription (experimental) | sherpa-onnx |
| **Noise Suppression** | `noise_suppression.py` | Optional spectral-gating noise reduction | noisereduce |
| **Stats** | `stats.py` | Usage stats, streaks, daily summary | json |
| **Audit Log** | `audit_log.py` | Optional append-only delivery audit trail | - |
| **Update Check** | `update_check.py` | Opt-in daily GitHub release check | urllib |
| **Uninstall** | `uninstall.py` | `--uninstall` removes settings/data/autostart, models opt-in | shutil |
| **Settings I/O** | `settings_io.py` | `--export-settings` / `--import-settings` | shutil |
| **Offline Models** | `model_transfer.py` | `--export-model` / `--import-model` for HF-blocked networks | shutil, ruamel.yaml |
| **Vocab Import** | `vocab_import.py` | `--import-vocab` hotword mining from a folder | - |
| **Setup Wizard** | `setup_wizard.py` | `--setup` interactive first-time configuration | - |
| **Autostart** | `autostart.py` | Opt-in launch-on-login (Windows Run key / macOS LaunchAgent) | winreg |
| **Console Welcome** | `onboarding_tutorial.py` | One-time first-launch console welcome banner | - |
| **Whisper.cpp Backend** | `whisper_engine_cpp.py` | Opt-in `whisper_cpp` backend mirroring WhisperEngine's API | pywhispercpp |
| **Foreground App** | `platform/*/foreground.py` | Detects the active window/app for per-app rules | pywin32 / pyobjc |
| **Console Control** | `platform/windows/console.py` | Show/hide/own the console window (pyapp builds) | ctypes |

## Project Structure

```
whisper-local/
├── whisper-local.py                   # Development wrapper script
├── pyproject.toml                     # Dependencies & PyPI config
├── CLAUDE.md                          # Claude AI project instructions
├── README.md                          # Project documentation
├── CHANGELOG.md                       # Version history and changes
│
├── src/
│   └── whisper_key/                   # Python package
│       ├── __init__.py                # Package initialization
│       ├── main.py                    # Main application entry point
│       ├── config.defaults.yaml       # Default configuration template
│       ├── commands.defaults.yaml     # Default voice commands template
│       ├── assets/                    # Application assets
│       │   ├── sounds/                # Audio feedback sounds
│       ├── platform/                  # Platform abstraction layer
│       │   ├── __init__.py            # Platform detection & import routing
│       │   └── {macos,windows}/       # Platform-specific implementations
│       │       ├── assets/            # Platform-specific assets
│       │       ├── app.py             # Thread requirements, getch()
│       │       ├── hotkeys.py         # Hotkey detection
│       │       ├── icons.py           # Tray icons
│       │       ├── instance_lock.py   # Instance control
│       │       ├── keyboard.py        # Key simulation
│       │       ├── paths.py           # Path management
│       │       ├── gpu.py              # GPU detection (Windows)
│       │       └── permissions.py     # Permission management
│       ├── audio_feedback.py          # Audio feedback for recording events
│       ├── audio_recorder.py          # Sounddevice audio capture
│       ├── clipboard_manager.py       # Clipboard & auto-paste operations
│       ├── config_manager.py          # YAML configuration management
│       ├── hotkey_listener.py         # Global hotkey detection
│       ├── instance_manager.py        # Single instance enforcement
│       ├── model_registry.py          # Whisper model registry & caching
│       ├── onboarding.py              # GPU setup prompt & installation
│       ├── state_manager.py           # Component coordination & workflow
│       ├── system_tray.py             # System tray icon & menu
│       ├── utils.py                   # Common utility functions
│       ├── voice_activity_detection.py # Voice activity detection
│       ├── voice_commands.py          # Voice command matching & execution
│       ├── hardware_detection.py       # Platform GPU detection wrapper
│       ├── terminal_ui.py             # Interactive terminal prompts
│       └── whisper_engine.py          # Faster-whisper transcription
│
├── docs/                              # Project documentation
│   ├── project-index.md
│   ├── voice-commands.md              # Voice commands user guide
│   ├── design/                        # Design docs
│   ├── plans/                         # Planning docs
│   ├── research/                      # Research docs
│   ├── roadmap/                       # Feature roadmap & user stories
│   │   ├── roadmap.md                 # Active feature roadmap
│   │   └── completed.md               # Completed user stories
│   └── ...
│
├── .temp/                             # Temporary working files (gitignored)
└── pyapp-build/                       # pyapp build script and config
```

---

*Last Updated: 2026-06-11 | Project Status: Active Development*