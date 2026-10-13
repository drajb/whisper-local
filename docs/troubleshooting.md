# Troubleshooting

Most issues are caught by `whisper-local --doctor` or `whisper-local --selftest`. Run one of those first.

If you need to file a bug, run:

```bash
whisper-local --bundle-logs
```

This creates a zip with redacted logs, `--doctor` output, and recent crashes. Attach it to your issue.

## Quick reference

| Symptom | Most likely cause | Fix |
|---|---|---|
| "Windows protected your PC" (SmartScreen) when running the `.exe` | The app is open-source but not code-signed (certificates cost money) | Click **More info → Run anyway**. Verify the download with the `.sha256` file from the release if you want certainty |
| First `.exe` launch sits for minutes with no window | It is installing the app's libraries from PyPI (one-time; Python itself is built into the `.exe` since 0.22.0) | Wait it out — subsequent launches are instant. Then the Whisper model download (~141 MB) follows |
| `.exe` 0.21.0 or older: `download failed: …python-build-standalone… operation timed out` | Old builds fetched Python from github.com on first launch with their own HTTP client, which ignores the Windows proxy settings | Use 0.22.0 or later, which has Python built in. If a corporate network also blocks PyPI, use `pip install whisper-local` with your usual proxy settings instead |
| One antivirus engine on VirusTotal flags `whisper-local.exe` | The `.exe` is unsigned and unpacks a standard Python runtime, which some heuristics treat as suspicious (e.g. "vcruntime140 sideloading": Python ships that Microsoft runtime DLL next to `python.exe`) | Verify the file instead of trusting the score: `gh attestation verify whisper-local.exe --repo drajb/whisper-local` proves it was built by this repo's CI, or compare its SHA-256 with the release's `.sha256` file. Or install with `pip install whisper-local` |
| Recording starts but no text appears | Default Whisper task changed accidentally | Settings → General → Language = `auto` (or your language); Profile = `Dictation` |
| First word is cut off | (Should be fixed by pre-roll) Mic was slow to wake | Check `audio.host` is set to `WASAPI` on Windows |
| Hotkey does nothing | Another app holds the same combination | Change `hotkey.recording_hotkey` in Settings; restart |
| Text appears as ALL CAPS | Caps Lock was on when hotkey pressed | Push-to-talk releases reset modifiers — try toggling Caps Lock off |
| "Mic captured pure silence" in `--selftest` | OS denied mic permission to your shell/terminal | Windows: Settings → Privacy & Security → Microphone. macOS: System Settings → Privacy & Security → Microphone |
| Tray icon missing | Windows hides tray icons by default | Click the `^` in the taskbar, drag the Whisper Local icon out |
| App seems frozen on launch | Whisper model is downloading (first run) | Wait — `tiny` is ~75 MB, `large` is ~2.9 GB. Watch `%APPDATA%\whisperkey\app.log` |
| "Could not register hotkeys" | Another instance is already running, or another app owns the combo | `whisper-local --quit` then relaunch. Or change the hotkey |
| GPU not used despite `device: cuda` | CTranslate2 CUDA runtime not installed | Run `whisper-local --setup` and accept the GPU install prompt |
| Transcription accuracy is poor | Tiny model + noisy environment | Settings → General → Model = `base` or `small`. Settings → Audio → Noise suppression = on (`pip install 'whisper-local[noise]'`) |
| `Ollama unreachable` in tray | Ollama service not running locally | `ollama serve` in a terminal, or disable in Settings → Post-process |
| Text appears twice in chat apps | `auto_send_key` pressed by accident | The Esc cancel + retry; consider switching off auto-send for that app via `app_rules.yaml` |
| Audio device unplugged mid-recording | USB mic disconnect | App should auto-recover to default input. If not, restart and tell the maintainer |
| Settings change didn't take effect | Hotkeys / device changes require restart | Quit and relaunch the app |
| `pyperclip.PyperclipException` on macOS | Missing `pbcopy`/`pbpaste` permissions | Open System Settings → Privacy → Accessibility, add Terminal |
| Stale lock prevents launch | Previous instance crashed without cleanup | `whisper-local --quit` clears the lock. As a last resort delete `%APPDATA%\whisperkey\WhisperKeyLocal.pid` |

## When all else fails

1. **Reset the app to defaults:** delete `%APPDATA%\whisperkey\user_settings.yaml` (Windows) or `~/.whisperkey/user_settings.yaml` (macOS). The defaults will be regenerated on next launch. Your hotwords/commands/transforms are kept.
2. **Reinstall:** `pip uninstall whisper-local && pip install whisper-local`
3. **Wipe everything:** delete the entire `%APPDATA%\whisperkey` directory — this resets settings, dictionary, stats, transcript history.
4. **File a bug:** run `whisper-local --bundle-logs` and attach the resulting zip to a new issue via [bug report template](https://github.com/drajb/whisper-local/issues/new?template=bug_report.yml).
