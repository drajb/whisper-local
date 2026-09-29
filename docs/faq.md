# FAQ

## Privacy & data

### Is my audio sent anywhere?
**No.** Whisper Local runs the Whisper speech model entirely on your machine. The only network calls the app ever makes are:

1. **First-launch model download** from `huggingface.co` (~75 MB for `tiny`, up to ~2.9 GB for `large`). Once cached, never re-downloaded.
2. **Optional GPU runtime install** if you accept the on-screen prompt (CUDA from PyPI, ROCm from `repo.radeon.com`).
3. **Optional update check** — once a day, only if you opt in with `update_check.enabled: true`. Only sends the app version in the User-Agent header.
4. **Optional Ollama post-processing** — only if you point it at an Ollama server you control (defaults to `localhost`).

Search the source for `urllib`, `requests`, `httpx`, `socket.connect` if you don't believe us. Every entry point is gated.

### Can it run on a plane / fully offline?
Yes. After the first model download, Whisper Local works with zero network connectivity. This is why most of our power users love it.

### Are my transcripts stored anywhere?
Locally only, by default:
- `transcripts.jsonl` — last 2000 entries, opens in **Transcript history** in the tray menu
- `stats.jsonl` — metadata only (char count, app name, duration), never the text itself
- `app.log` — only if `logging.log_transcriptions: true` (default: false)

Delete the files in `%APPDATA%\whisperkey\` (Windows) or `~/.whisperkey/` (macOS) any time.

## Comparison

### How is this different from Whisper.cpp directly?
`whisper.cpp` is the inference runtime. Whisper Local is the full **desktop dictation app** wrapped around it — global hotkeys, push-to-talk, voice commands, transforms, system tray, audio capture with pre-roll buffer, fallback window, profile switching, per-app rules, AI rephrase via Ollama, and more. You *can* swap our default `faster-whisper` backend for `whisper.cpp` with `pip install 'whisper-local[whispercpp]'` and `whisper.backend: whisper_cpp`.

### How is this different from Windows Speech Recognition?
WSR uses an old Microsoft engine that's significantly less accurate than Whisper. Whisper Local is built on **modern AI transcription** (the same OpenAI Whisper model that powers most cloud dictation services), runs on your GPU, supports 99 languages, and has voice commands + transforms.

### How is this different from Wispr Flow?
Wispr Flow is closed-source and sends your audio to the cloud. Whisper Local is open-source, MIT-licensed, runs **100% on your machine**, and is free forever. We aim for feature parity on the dictation core (overlay, transforms, push-to-talk) — Wispr's strength is polish; ours is privacy and hackability.

### How is this different from Dragon NaturallySpeaking?
Dragon is a paid product (~$500 perpetual or subscription), Windows-only, with great accuracy on its own engine. Whisper Local is free, cross-platform (Windows + macOS), uses Whisper, and is open-source. Dragon has decades of dictation-specific UX (Read That Back, training profiles); we have voice commands + transforms + Ollama integration.

## Technical

### Which Whisper model should I use?
- **`tiny` (~75 MB)** — fast, OK for short commands. Bad for long dictation.
- **`base` (~141 MB)** — reasonable for most users. **This is the default.**
- **`small` (~464 MB)** — much better accuracy, still real-time on most CPUs.
- **`medium` (~1.4 GB)** — recommended for GPUs. Excellent accuracy.
- **`large-v3` (~2.9 GB)** — best, GPU strongly recommended.

Change in Settings → General → Model, or `whisper.model` in `user_settings.yaml`.

### Does GPU acceleration matter?
A lot. With a modern NVIDIA GPU (`device: cuda`, `compute_type: float16`):
- `tiny`: ~50ms transcription of a 5-second clip
- `medium`: ~120ms
- `large-v3`: ~250ms

On CPU with the same `medium` model: 2–6 seconds. The first transcription after launch is always slower due to model warmup.

### What about AMD GPUs?
Supported via ROCm on Linux/Windows. Run `whisper-local --setup` and accept the GPU install prompt; we use [PinW/ctranslate2-rocm-wheels](https://github.com/PinW/ctranslate2-rocm-wheels). Apple Silicon Macs should use the `whisper_cpp` backend (`pip install 'whisper-local[whispercpp]'`) for best performance.

### How do I make hotwords work?
`whisper-local --add-word "MyJargon"` or the **Add word to dictionary...** tray item. These get fed as `hotwords` to Whisper at recording time. Names, technical terms, codenames work best. For bulk import: `whisper-local --import-vocab FOLDER` scans a folder of text files and merges the top hotwords automatically.

### Can I use this as a server / API?
Yes! `whisper-local --serve` starts a **local OpenAI-compatible HTTP server** on `http://127.0.0.1:7777`. Drop-in for any tool that expects `POST /v1/audio/transcriptions` (Cursor, VS Code Continue, Open WebUI, etc.) — point them at your local server with a dummy API key. Fully offline, runs the same model you use for dictation.

## App behaviour

### Why does the tray icon disappear on Windows?
Windows 10/11 hides tray icons by default. Click the `^` arrow on the right of the taskbar and **drag** the Whisper Local icon out into the visible tray area to pin it.

### How do I autostart on login?
It's built in (since v0.11.0). Tick **Start on login** in the tray menu, check the box on the first-run welcome window, or run `whisper-local --enable-autostart` (`--disable-autostart` to undo). It launches windowless — no console window at boot. On Windows this uses an `HKCU\…\Run` entry.

On macOS it's a LaunchAgent that starts the app through a small helper, `~/Library/Application Support/Whisper Local/Whisper Local.app`. At the first login after you turn it on, macOS asks you to allow "Whisper Local" under Accessibility, and later under Microphone. The app starts as soon as you allow it, or after a minute either way. Building the helper needs Apple's Command Line Tools (`xcode-select --install`). Without them, the LaunchAgent runs Python directly and macOS asks about Python instead.

### Can I use voice punctuation in another language (e.g. Polish)?
Yes. The built-in "comma / period / open paren" triggers are English, but you can
define your own under `postprocess.inline_formatting_replacements` in
`user_settings.yaml`:

```yaml
postprocess:
  inline_formatting: true
  inline_formatting_replacements:
    - phrase: przecinek      # comma
      replacement: ","
    - phrase: strzałka       # arrow
      replacement: "→"
```

By default your list *replaces* the English one; set `inline_formatting_extend: true`
to keep the English defaults and add yours on top. Matching is whole-word and
case-insensitive. This runs after Whisper and before any optional Ollama cleanup,
so it's a reliable, deterministic step regardless of which local LLM you use.

**Spoken cue words get extra punctuation from Whisper.** When you say "comma",
Whisper hears speech and adds its own commas/periods around it based on prosody, so
`hello comma world` often transcribes as `Hello, comma, world.` — and a plain swap
leaves `Hello,, world.` Turn on `inline_formatting_absorb_punctuation: true` and each
cue phrase also eats the commas/periods/whitespace hugging it; put the spacing you
want into the replacement string:

```yaml
postprocess:
  inline_formatting: true
  inline_formatting_absorb_punctuation: true
  inline_formatting_replacements:
    - phrase: przecinek
      replacement: ", "
    - phrase: strzałka
      replacement: " → "
```

`Hello, comma, and welcome, arrow. Common greeting.` then comes out as
`Hello, and welcome → Common greeting.`

### Can I customize hotkeys?
Yes — Settings → Hotkeys. Or edit `hotkey.*` in `user_settings.yaml` directly. Changes take effect on next app restart.

### Does it work with games / fullscreen apps?
Mostly yes — hotkeys are registered globally. Some fullscreen-exclusive games (especially anti-cheat-protected) might suppress all global hotkeys. Switch to windowed fullscreen if you hit this.

### Can I dictate to multiple apps at once?
Whisper Local always delivers to the **foreground** app at the moment delivery starts. If you switch windows mid-recording, the text goes wherever you ended up.

## Support

### I found a bug — how do I report it?
1. Run `whisper-local --bundle-logs`
2. Open a [new issue](https://github.com/drajb/whisper-local/issues/new?template=bug_report.yml) using the bug template
3. Attach the bundle zip

### I want a feature
Open a [feature request](https://github.com/drajb/whisper-local/issues/new?template=feature_request.yml). For larger changes, please open a [Discussion](https://github.com/drajb/whisper-local/discussions) first.

### Is there a Discord / support forum?
GitHub Discussions for now: <https://github.com/drajb/whisper-local/discussions>

### Can I pay for support / priority?
This is a community project maintained on a best-effort basis. No paid tier exists.
