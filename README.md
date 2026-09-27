<div align="center">

# Whisper Local

### Free, Open-Source, **100% Offline** AI Dictation for Windows & macOS

**Press a hotkey. Speak. Your words appear at the cursor.**
No cloud. No subscription. No telemetry. Powered by [OpenAI Whisper](https://github.com/openai/whisper).

[![Tests](https://github.com/drajb/whisper-local/actions/workflows/test.yml/badge.svg)](https://github.com/drajb/whisper-local/actions/workflows/test.yml)
[![Release](https://github.com/drajb/whisper-local/actions/workflows/release.yml/badge.svg)](https://github.com/drajb/whisper-local/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/whisper-local.svg)](https://pypi.org/project/whisper-local/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey.svg)](#-quick-start)
[![Code of Conduct](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

[**Quick Start**](#-quick-start) · [**Features**](#-features) · [**vs. Wispr Flow / Dragon**](#-why-whisper-local) · [**Voice Commands**](#-voice-commands) · [**Contributing**](#-contributing)

</div>

![Whisper Local — press, speak, type](docs/hero.svg)

<sub>Want a real screen-recording demo here? See [`docs/demo-recording.md`](docs/demo-recording.md) — drop a `docs/demo.gif` in and uncomment the line below.</sub>
<!-- ![Demo](docs/demo.gif) -->


Whisper Local is a **free, open-source, fully offline alternative to Wispr Flow, Dragon, and Otter** for power users who want **AI dictation without sending audio to the cloud**. Built on [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2), it delivers **push-to-talk speech-to-text in any application** — chat apps, code editors, browsers, terminals, design tools, anywhere a cursor blinks. Self-hosted, hackable, MIT-licensed.

**Looking for:** *Wispr Flow alternative*, *offline voice typing*, *local Whisper dictation*, *free Dragon NaturallySpeaking alternative*, *privacy-first speech-to-text*, *Windows voice dictation without cloud*, *macOS push-to-talk transcription*. You found it.

---

## 🌟 Why this exists

Most AI dictation tools are great — until you check the privacy policy. Your audio goes to a server, gets processed, and (sometimes) stored. You pay a monthly fee or get cut off.

Whisper Local exists because **you shouldn't have to choose between accuracy and privacy.**

- 🔒 Your voice never leaves your machine — not even metadata
- 🆓 Free forever — no account, no API key, no subscription
- 🔌 Works offline, air-gapped, after the internet is gone
- 🛠️ Fork it, hack it, ship your own version — MIT licensed
- 💡 Same Whisper model quality as cloud services, running on your own GPU

This is a **community tool**, not a product. There's no support SLA, no roadmap committee, no marketing. If it's useful to you, great. If something's broken, PRs are welcome.

> **A note from the maintainer:** I built this for myself, then realised it might help others. So I'm releasing it **for anyone who wants it** — no strings attached. Use it. Fork it. Rebrand it. Ship your own version. The only thing I ask is that you keep the LICENSE notice intact. If you build something cool on top of it, I'd love to hear about it via a [Discussion](https://github.com/drajb/whisper-local/discussions) — but you don't owe anyone anything.
>
> — **Rohit Burani**

---

## ✨ Why Whisper Local?

| Feature | **Whisper Local** | Wispr Flow | Dragon / Dragon Anywhere | Otter.ai | Windows Speech Recognition |
|---|:---:|:---:|:---:|:---:|:---:|
| **Runs 100% offline** | ✅ | ❌ | ❌ (Anywhere) | ❌ | ✅ |
| **Audio never leaves your machine** | ✅ | ❌ | ❌ | ❌ | partial |
| **Free / open source** | ✅ | ❌ | ❌ ($$$/yr) | ❌ ($$/mo) | ✅ |
| **Modern AI accuracy (Whisper)** | ✅ | ✅ | partial | ✅ | ❌ |
| **Works in any app via hotkey** | ✅ | ✅ | partial | ❌ | partial |
| **Customisable voice commands** | ✅ | partial | ✅ | ❌ | ❌ |
| **Push-to-talk + auto-paste + auto-send** | ✅ | ✅ | partial | ❌ | ❌ |
| **GPU acceleration (NVIDIA & AMD)** | ✅ | n/a | n/a | n/a | ❌ |
| **AI rephrase / transforms (Ollama)** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Hackable / MIT licensed** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **No account required** | ✅ | ❌ | ❌ | ❌ | ✅ |

---

## 🎯 Features

- 🎙️ **Global push-to-talk hotkey** — start recording from any app with `Ctrl+Win` (Windows) or `Fn+Ctrl` (macOS)
- ⚡ **Pre-roll buffer + warmup** — captures the 500 ms before you press the key *and* pre-loads Whisper at boot, so the first word is never clipped and the first recording feels instant
- 🏷️ **Terminal tab title status** — the tab shows what the app is doing (idle / recording / processing), handy when the tray icon is hidden in the overflow area
- 🔵 **Floating level overlay** — a small pill at the screen edge shows you're being heard, with the transcript appearing next to the level bar (Wispr Flow–style). Optional [real-time streaming preview](docs/streaming.md) shows words *as you speak*. *(Windows; the macOS menu-bar icon shows status instead.)*
- 📝 **Inline voice formatting** — say "comma", "period", "question mark", "new paragraph", "open quote", etc. mid-sentence. **Fully customizable** for any language via `postprocess.inline_formatting_replacements` (e.g. map Polish phrases to punctuation, or "arrow" → →)
- ✂️ **Voice editing** — say "scratch that" to erase what you just said, back to the start of the sentence (`postprocess.voice_editing`, opt-in)
- ↩️ **Backtrack** — correct yourself mid-sentence: "meet at 2, actually 3" types "meet at 3" (`postprocess.backtrack`, opt-in). See [Smart editing](#️-smart-editing)
- 🧾 **Spoken lists** — "first, milk. second, eggs" becomes a numbered or bulleted list (`postprocess.list_formatting`, opt-in)
- ✨ **Snippets** — say "my signature" (or any trigger you define) mid-dictation and the full text is typed, with `${date}` / `${time}` / `${clipboard}` filled in
- 🎨 **Writing styles** — formal, casual, very casual or verbatim, globally or per app (email formal, chat casual, code verbatim out of the box)
- 📌 **Paste last dictation** — `Alt+Shift+Z` types your last dictation again when it landed in the wrong window
- 🙌 **Hands-free lock** — double-tap the record hotkey to keep recording without holding it; tap again to stop (`hotkey.double_tap_to_lock`, opt-in)
- 🤫 **Whisper mode** — boosts quiet speech so you can dictate in an open office (`audio.whisper_mode`, opt-in)
- 🔢 **Smart formatting** — deterministic, offline: "3 p.m." → "3 PM", "john at example dot com" → "john@example.com" (`postprocess.smart_formatting`, each toggle opt-in)
- 🤖 **AI rephrase** — dedicated `Ctrl+Shift+Win` hotkey: select text, hold, speak your instruction, release — local Ollama rewrites it in place
- 🌐 **Translation mode** — speak any language, get English; tray → Profile → Translate
- 🔁 **Continuous dictation mode** — for long-form notes, the app auto-restarts recording after each delivery
- 📋 **Fallback window** — if no text field is focused, the transcript appears in a small window (pre-selected, copy button, already on clipboard)
- ⏸ **Pause-all hotkey** — `Ctrl+Alt+Win` disables every Whisper Local hotkey until you press it again
- 📋 **Auto-paste at cursor** — transcript lands wherever you're typing, optionally followed by Enter (auto-send)
- 🔒 **100 % local & private** — no network calls during use; Whisper models cached on disk
- 🚀 **GPU acceleration** — NVIDIA CUDA and AMD ROCm supported, CPU works out of the box
- 🗣️ **Voice commands** — say a trigger phrase to send a hotkey, type pre-written text, or run a shell command
- 🔁 **Hot-reload** — edit `commands.yaml` and your change applies on the next transcription, no restart
- 🩺 **Built-in diagnostics** — `whisper-local --doctor` checks audio devices, model cache, hotkeys, and recent errors
- 🎛️ **Profiles** — switch between Dictation / Chat / Code / Notes presets from the tray
- 🪟 **Per-app rules** — different behaviour *and* formatting per foreground app: auto-send in Slack, copy-only + verbatim (no auto-caps/periods) in VS Code, full sentences in email, suppress in 1Password
- ⌨️ **Type-as-you-speak** *(experimental, opt-in)* — `streaming.deliver_to_cursor` commits finalized phrases to the cursor live, Wispr-Flow style (trades full-Whisper accuracy for latency; see [docs/streaming.md](docs/streaming.md))
- 🧹 **Optional LLM cleanup** — pipe transcripts through a local [Ollama](https://ollama.ai) model for punctuation / capitalisation polish (off by default, fully local)
- 📜 **Recent transcriptions** — last 10 results in the tray menu, click to copy back
- 🔧 **Settings backup/restore** — `--export-settings` / `--import-settings` for portability
- 🖥️ **Settings UI** — `whisper-local --settings` opens a GUI settings window (no YAML editing required)
- 📜 **Transcript history** — `whisper-local --history` opens a searchable log of everything you've dictated
- 📖 **Vocabulary corrections** — map one canonical spelling to every way Whisper mishears it (`CAPEX: [cap x, copics]`), applied in a single pass with longest-match-wins
- 🧠 **Self-improving accuracy** — from the history window, turn any misrecognition into a permanent correction ("Fix this everywhere…"), or let it mine your own history for names to add to your dictionary ("Suggest hotwords"). All offline; corrections apply on your next dictation, no restart
- 🔊 **System-audio capture** *(experimental)* — `whisper-local --transcribe-system` transcribes what you *hear* (meetings, videos), not just the mic (`pip install 'whisper-local[loopback]'`, Windows-first)
- 🔔 **Opt-in update notifications** — daily GitHub release check, fully offline by default (`update_check.enabled: true` to opt in)
- 🎚️ **Noise suppression** — spectral gating via `noisereduce`, off by default (`pip install 'whisper-local[noise]'`)
- 🩺 **`--selftest`** — one-command sanity check (mic, model, transcription, clipboard) — perfect for first-launch
- 🎯 **Hotkey cheat sheet** — `whisper-local --cheat-sheet` or tray menu — shows your *current* configured hotkeys at a glance
- 📦 **`--bundle-logs`** — zip up redacted logs + diagnostics for bug reports with one command
- 🌐 **Local OpenAI-compatible API** — `whisper-local --serve` exposes `POST /v1/audio/transcriptions` on `localhost:7777` for Cursor, Open WebUI, anything that speaks OpenAI Whisper API
- 🛡️ **Auto-recovery** — silently reconnects when a USB mic is unplugged mid-recording
- 🛡️ **Crash reports** — uncaught errors write a self-contained dump to disk
- 🪟 **System tray UI** — model selection, mic selection, profile switch, diagnostics
- 🍎 **Cross-platform** — Windows 10+, macOS

---

## 🚀 Quick Start

### Option 1 — Standalone Windows app (no Python needed)

1. Download **`whisper-local.exe`** from the [latest release](https://github.com/drajb/whisper-local/releases/latest).
2. Double-click it. Windows SmartScreen will warn because the app isn't code-signed (a paid certificate) — click **More info → Run anyway**. The source is fully open if you'd rather audit first.
3. First launch takes a few minutes: it sets up a private Python runtime, then downloads the Whisper model. Every launch after that is instant.

### Option 2 — pip (Windows / macOS, Python 3.11–3.13)

```bash
pip install whisper-local
whisper-local
```

### Option 3 — from source

```bash
git clone https://github.com/drajb/whisper-local.git
cd whisper-local
pip install -e .
```

### Launch

| | |
|---|---|
| **Terminal** | `whisper-local` (or `wl` for short) |
| **Double-click** | `whisper-local.cmd` (Windows) |
| **Start on login** | Tick **Start on login** in the tray menu (or the first-run welcome), or run `whisper-local --enable-autostart`. Disable anytime the same way. |

First launch downloads the default [`base`](https://huggingface.co/Systran/faster-whisper-base) Whisper model (~141 MB) into your HuggingFace cache. After that, **everything runs offline**. (Prefer a smaller/faster download? Set `whisper.model: tiny` — ~75 MB.)

> **`huggingface.co` blocked at work?** Common on corporate networks. Export the
> model from a machine that has internet and import it on the one that doesn't —
> no admin rights needed:
> ```bash
> whisper-local --export-model            # machine WITH internet — writes to your Desktop
> whisper-local --import-model "<the folder you copied over>"   # the offline machine
> ```
> Pass a path to `--export-model` (a USB drive, say) to put it somewhere else.
> Network-share and internal-mirror setups are covered in
> **[docs/offline-models.md](docs/offline-models.md)**.

### Use it

| Action | Windows | macOS |
|---|---|---|
| Hold to record | `Ctrl+Win` | `Fn+Ctrl` |
| Stop & paste | release key (push-to-talk) or `Ctrl` | release or `Fn` |
| Stop & auto-send (Enter) | `Alt` | `Option` |
| Cancel | `Esc` | `Shift` |
| Voice command mode | `Alt+Win` | `Fn+Command` |

### Verify everything works

```bash
whisper-local --doctor
```

Runs through Python version, dependencies, config validation, audio devices, model cache, hotkey backend, and recent log errors. Exit 0 = clean.

---

## ✍️ Smart editing

Say it naturally; it gets typed the way you'd have written it. Everything runs offline, with no LLM. Turn each one on under **Settings → Post-process**, or in `user_settings.yaml`:

| You say | You get | Setting |
|---|---|---|
| "Let's meet at 2, actually 3" | Let's meet at 3 | `postprocess.backtrack.enabled` |
| "Ship it Tuesday, no wait, Wednesday" | Ship it Wednesday | `postprocess.backtrack.enabled` |
| "I I think we we should go" | I think we should go | `postprocess.remove_repeated_words` |
| "Groceries: first, milk. Second, eggs." | Groceries:<br>1. Milk<br>2. Eggs | `postprocess.list_formatting` |
| "Thanks for your help. My signature." | Thanks for your help. Best,<br>Rohit | `postprocess.snippets` |
| "book the flight, scratch that, cancel it" | cancel it | `postprocess.voice_editing` |

Backtrack only acts when a cue ("actually", "I mean", "no wait", "sorry", …) is followed by a number, time, weekday or month that replaces an earlier one in the same sentence, so everyday prose like "I actually like it" is never changed.

**Snippets** are defined once:

```yaml
postprocess:
  snippets:
    - trigger: my signature
      expansion: "Best,\nRohit"
    - trigger: my address          # mode: alone = only when it's the whole dictation
      expansion: "1 Main St, Dallas, TX 75201"
      mode: alone
```

**Styles** set capitalization and punctuation in one choice: `formal` (full sentences), `casual` (no trailing period), `very_casual` (all lowercase except acronyms and your own terms) and `verbatim` (no automatic capitals, periods or lists). Set `postprocess.style` globally, or `style:` on a rule in `app_rules.yaml`. The shipped rules make email formal, chat casual, and code editors and terminals verbatim.

---

## 🗣️ Voice Commands

Speak a trigger to run keyboard shortcuts, type snippets, or launch programs. Defined in:

- **Windows:** `%APPDATA%\whisperkey\commands.yaml`
- **macOS:** `~/.whisperkey/commands.yaml`

```yaml
commands:
  # Send a keyboard shortcut
  - trigger: "undo"
    hotkey: "ctrl+z"

  # Deliver pre-written text
  - trigger: "my email"
    type: "user@example.com"

  # Run a shell command
  - trigger: "open notepad"
    run: 'notepad.exe'
```

Edits hot-reload — no app restart required. See **[docs/voice-commands.md](docs/voice-commands.md)** for the full guide.

> ⚠️ Voice commands with `run:` execute through your system shell with your user privileges. Only add commands you trust.

---

## ⚡ GPU Acceleration

On first launch, Whisper Local detects your GPU and offers one-press install of the required runtime libraries. Supports **NVIDIA CUDA** and **AMD ROCm**.

For manual setup or AMD RDNA 1, see **[docs/gpu-setup.md](docs/gpu-setup.md)**.

---

## 🌐 Local OpenAI-Compatible API

Whisper Local doubles as a **drop-in local replacement for the OpenAI Whisper API** — fully offline. Point any tool that speaks `POST /v1/audio/transcriptions` at it (Cursor, VS Code Continue, Open WebUI, n8n, custom scripts, anything else).

```bash
whisper-local --serve            # listens on http://127.0.0.1:7777
whisper-local --serve --serve-port 8080
```

```bash
# Drop-in compatible with the OpenAI SDK:
curl -X POST http://127.0.0.1:7777/v1/audio/transcriptions \
  -F file=@audio.wav -F model=whisper-1 -F response_format=text
```

Same Whisper model you use for dictation. Same GPU. No API key. No rate limit. No outgoing traffic.

---

## 🎛️ Profiles

Switch between presets from the tray icon → **Profile**:

| Profile | Behaviour |
|---|---|
| **Dictation** | General-purpose voice typing, auto-paste on |
| **Chat** | Push-to-talk, auto-paste + auto-send via `Alt` |
| **Code** | Copy-only mode for editors, never auto-sends |
| **Notes** | Quiet copy-to-clipboard, voice commands disabled |

Edit or add new profiles in `%APPDATA%\whisperkey\profiles.yaml`.

---

## 🪟 Per-app rules

Different apps want different behaviour. Whisper Local detects the
foreground window before delivering each transcription and matches it
against rules in `%APPDATA%\whisperkey\app_rules.yaml`:

```yaml
rules:
  # Chat apps: send the message immediately
  - match: ["slack.exe", "discord.exe"]
    auto_send: true

  # Code editors: copy only, and keep it verbatim (no auto-caps or trailing period)
  - match: ["code.exe", "cursor.exe"]
    auto_paste: false
    capitalize_first: false
    ensure_punctuation: false

  # Password managers: skip delivery entirely
  - match: ["1password.exe", "bitwarden.exe"]
    suppress: true
```

A rule can override delivery (`auto_send`, `auto_paste`, `suppress`), Whisper
context (`initial_prompt`, `language`, `task`), **and** formatting
(`capitalize_first`, `ensure_punctuation`, `strip_trailing_period`,
`inline_formatting`). Hot-reloads — edit and the next transcription picks it up.

## 🧹 Optional LLM cleanup

If you have [Ollama](https://ollama.ai) running locally, Whisper Local can
pipe each transcript through a small local model for punctuation and
capitalisation polish. **Off by default and fully local** — set
`postprocess.ollama.enabled: true` in `user_settings.yaml` to enable.

```yaml
postprocess:
  capitalize_first: true        # works without Ollama
  ensure_punctuation: true      # works without Ollama
  strip_filler_words: true      # works without Ollama
  ollama:
    enabled: false              # set true to opt in
    endpoint: http://localhost:11434
    model: llama3.2
    timeout: 5
```

## ⚙️ Configuration

Local settings live at:

- **Windows:** `%APPDATA%\whisperkey\user_settings.yaml`
- **macOS:** `~/.whisperkey/user_settings.yaml`

Delete the file and restart to reset to defaults. Highlights:

| Option | Default | Notes |
|---|---|---|
| `whisper.model` | `base` | Any model from `whisper.models`. `tiny` = smallest/fastest, larger = more accurate/slower |
| `whisper.device` | `cpu` | `cpu` or `cuda` (NVIDIA/AMD) |
| `whisper.compute_type` | `int8` | `int8`/`float16`/`float32` |
| `whisper.language` | `auto` | Auto-detect or specific language code |
| `whisper.hotwords` | `[]` | Words the model should favour — names, jargon |
| `hotkey.recording_hotkey` | `ctrl+win` | Configurable |
| `hotkey.recording_mode` | `push_to_talk` | `push_to_talk` (hold to talk) or `toggle` |
| `hotkey.double_tap_to_lock` | `false` | Double-tap the record hotkey for hands-free recording |
| `hotkey.paste_last_hotkey` | `alt+shift+z` | Type your last dictation again (`ctrl+option+v` on macOS) |
| `postprocess.style` | `""` | `formal` / `casual` / `very_casual` / `verbatim`, or per app in `app_rules.yaml` |
| `postprocess.snippets` | `[]` | Spoken shortcuts expanded inline |
| `audio.whisper_mode.enabled` | `false` | Boost quiet speech before transcription |
| `vad.vad_realtime_enabled` | `true` | Auto-stop on silence |
| `clipboard.auto_paste` | `true` | `false` = copy only |
| `clipboard.delivery_method` | `paste` | `paste` (Ctrl+V) or `type` (direct injection) |
| `voice_commands.enabled` | `true` | Enable command mode |
| `audio.host` | `null` | `WASAPI` recommended on Windows for low latency |

Full reference: [`config.defaults.yaml`](src/whisper_key/config.defaults.yaml).

---

## 🛠️ CLI Reference

```bash
whisper-local                      # Run the app (or use `wl`)
whisper-local --setup              # Interactive setup wizard (model, mode, mic)
whisper-local --doctor             # Run diagnostics
whisper-local --stats              # Transcription history & time saved
whisper-local --version            # Print version
whisper-local --quit               # Stop the running instance
whisper-local --export-settings DIR        # Back up user_settings + commands
whisper-local --import-settings DIR        # Restore from a backup
whisper-local --export-transcripts FILE    # Dump history (.txt/.md/.csv)
whisper-local --import-vocab FOLDER        # Mine a folder for hotwords
whisper-local --settings           # Open the settings GUI (no YAML editing required)
whisper-local --history            # Browse and search transcript history
whisper-local --cheat-sheet        # Show your currently configured hotkeys
whisper-local --selftest           # Run an automated self-test (mic, model, transcription)
whisper-local --bundle-logs        # Create a redacted diagnostic zip for bug reports
whisper-local --serve              # Run a local OpenAI-compatible Whisper API on :7777
whisper-local --enable-autostart   # Launch automatically at login (--disable-autostart to undo)
whisper-local --test               # Run a separate test instance (own mutex)
```

Launching while an instance is already running **takes over** — the old one is replaced cleanly, no manual quit needed.

---

## 🏗️ How it works

```
┌─────────────────────┐  ┌──────────────────┐  ┌─────────────────────┐
│  global-hotkeys /   │  │   sounddevice +  │  │  faster-whisper /   │
│  NSEvent (macOS)    │─▶│  500ms ring buf  │─▶│  ctranslate2 (GPU)  │
└─────────────────────┘  │  + TEN VAD       │  └──────────┬──────────┘
                         └──────────────────┘             │
                                                          ▼
                         ┌──────────────────┐  ┌─────────────────────┐
                         │  Voice command   │◀─│  Transcribed text   │
                         │  matcher         │  │                     │
                         └──────────────────┘  └──────────┬──────────┘
                                                          ▼
                                                ┌─────────────────────┐
                                                │  ctypes SendInput / │
                                                │  Quartz CGEvent     │
                                                │  → cursor           │
                                                └─────────────────────┘
```

---

## 🔒 Privacy pledge

Whisper Local makes the following network calls and **no others**:

1. **First launch only:** downloads the Whisper model from `huggingface.co` into your local cache.
2. **GPU onboarding (opt-in):** if you accept the GPU setup prompt, `pip install` pulls CUDA / ROCm runtime packages from PyPI / `repo.radeon.com`.

After setup, **zero network traffic**. Confirm by running `whisper-local --doctor` and inspecting the source — every network entry point lives in [`onboarding.py`](src/whisper_key/onboarding.py) and is gated behind explicit user prompts.

---

## 📦 Tech stack

`faster-whisper` · `ctranslate2` · `sounddevice` · `ten-vad` · `pyperclip` · `pystray` · `ruamel.yaml` · `playsound3`
**Windows-only:** `global-hotkeys` · `pywin32` · ctypes `SendInput`
**macOS-only:** `pyobjc-framework-Quartz` · `pyobjc-framework-ApplicationServices`

---

## 📚 Documentation

- **[docs/troubleshooting.md](docs/troubleshooting.md)** — symptom → cause → fix table for the most common issues
- **[docs/faq.md](docs/faq.md)** — privacy, comparisons (Whisper.cpp / WSR / Wispr Flow / Dragon), model picks, GPU notes
- **[docs/distribution.md](docs/distribution.md)** — how releases work (standalone `.exe`, PyPI, winget, Homebrew) and how to ship one
- **[docs/voice-commands.md](docs/voice-commands.md)** — the full voice command DSL
- **[docs/gpu-setup.md](docs/gpu-setup.md)** — manual GPU setup for NVIDIA / AMD
- **[CHANGELOG.md](CHANGELOG.md)** — release notes

Hit a wall? Run `whisper-local --doctor` or `whisper-local --selftest` first — they catch 90% of issues.

---

## 🤝 Contributing

Contributions of all kinds are welcome — bug fixes, new features, docs improvements, or just opening an issue with a clear reproduction. This project is maintained on a best-effort basis with no SLA; please be patient with response times.

```bash
git clone https://github.com/drajb/whisper-local.git
pip install -e .
python -m unittest tests.test_smoke   # smoke suite — should report OK
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community standards. By contributing you agree your code will be MIT licensed. Found a security issue? See [SECURITY.md](SECURITY.md) — please don't open a public issue.

Good first issues are tagged [here](https://github.com/drajb/whisper-local/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22). The full credit list is in [AUTHORS.md](AUTHORS.md).

---

## ☕ Support

Whisper Local is free and always will be. If it saves you time or a monthly subscription, consider starring the repo and sharing it with people who'd find it useful — it helps the project grow.

No pressure. Starring the repo and sharing it with people who'd find it useful is just as helpful.

---

## 🙏 Credit

Whisper Local builds on a lot of excellent open-source work. The full list is in [`AUTHORS.md`](AUTHORS.md).

MIT licensed; see [`LICENSE`](LICENSE).

---

<div align="center">

### ⭐ If you find this useful, please [star the repo](https://github.com/drajb/whisper-local) — it helps others discover it.

**Maintained by [Rohit Burani](https://gekro.com) ([@drajb](https://github.com/drajb))**

[Website](https://gekro.com) · [GitHub](https://github.com/drajb) · [Discussions](https://github.com/drajb/whisper-local/discussions) · [Report a bug](https://github.com/drajb/whisper-local/issues/new?template=bug_report.yml) · [Request a feature](https://github.com/drajb/whisper-local/issues/new?template=feature_request.yml)

<sub>Tags: whisper · dictation · speech-to-text · voice-typing · transcription · ai-dictation · local-ai · offline · push-to-talk · voice-recognition · accessibility · faster-whisper · privacy · self-hosted · wispr-flow-alternative · dragon-naturallyspeaking-alternative · otter-alternative · ollama · voice-commands · windows · macos · python</sub>

</div>
