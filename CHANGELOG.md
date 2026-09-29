# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.21.0]

### Changed
- **Your shipped rules, commands, transforms and profiles now keep updating.**
  Each of these four files used to be copied out of the app once, on first
  launch, and never touched again, so every later improvement reached new
  installs only. A machine set up in May still had May's rules eleven releases
  later. The shipped entries now load from the app every time, and your file
  holds only what's yours.

  Your file is rewritten once, on the first launch after updating, and the
  original is kept beside it as `<name>.yaml.<date>.bak`. Entries you never
  edited are dropped, because the app supplies them now. Entries you did edit
  become an override that records only the keys you changed, so the rest keeps
  following the shipped version. Anything with no shipped counterpart is yours
  and is left alone.

  In `app_rules.yaml`, `commands.yaml`, `transforms.yaml` and `profiles.yaml`
  you can now:
  ```yaml
  rules:
    - match: ["obsidian.exe"]   # your own, matched before any shipped rule
      style: casual
    - id: chat-apps             # change a shipped one, only the keys you list
      auto_send: false
    - id: terminals             # or turn it off
      disabled: true
  ```
  Shipped app rules are named by `id`; commands by their `trigger`, transforms
  and profiles by their `name`.

### Fixed
- **A code editor showing a file called `slack_bot.py` auto-sent your
  dictation.** Window titles match by substring, so the chat rule caught it.
  0.20.0 fixed the shipped rule order, but that fix could only reach people
  installing for the first time. It now reaches everyone.
- **Existing installs never got the per-app writing styles** added in 0.20.0,
  the email rule, or the four voice commands added since. All of them arrive
  with this release.
- **A voice command override can swap the action it came with.** Setting
  `hotkey: null` and adding `type:` now works; the dispatcher tested for the
  key being present rather than having a value, so a cleared action still fired.
- **`--doctor` reported the size of your overrides file**, which would have read
  as "0 rules" while five were in force. It now reports what is actually in
  effect, and how many of those are yours.

## [0.20.0]

Wispr Flow–style editing, fully offline, plus fixes for both issues reported
on 0.19.0. Every new feature is off by default except the paste-last hotkey
and the per-app styles in the shipped app rules.

### Added
- **Backtrack.** Correct yourself mid-sentence: "let's meet at 2, actually 3"
  types "let's meet at 3", and "Tuesday, no wait, Wednesday" types
  "Wednesday". It acts only when a cue ("actually", "I mean", "no wait",
  "sorry", "make that", …) is followed by a number, time, weekday or month that
  replaces an earlier one in the same sentence, so "I actually like it" is
  never touched. Deterministic, no LLM. (`postprocess.backtrack`)
- **Stutter removal.** "I I think" becomes "I think". Genuine doubles ("had
  had") and emphasis ("very very") are kept. (`postprocess.remove_repeated_words`)
- **Spoken lists.** "first, milk. second, eggs" becomes a numbered (or
  bulleted) list on separate lines. It fires only on markers counting up from
  one, each followed by punctuation, so "one of the two options" stays prose.
  (`postprocess.list_formatting`, `list_style`)
- **Snippets.** Say a trigger such as "my signature" anywhere in normal
  dictation and its expansion is typed, with `${date}`, `${time}` and
  `${clipboard}` filled in. `mode: alone` limits a snippet to dictations that
  are only the trigger. (`postprocess.snippets`)
- **Writing styles.** `formal`, `casual`, `very_casual` (all lowercase except
  acronyms and your own terms) and `verbatim` bundle the formatting toggles
  into one choice. Set one globally (`postprocess.style`) or per app
  (`style:` in `app_rules.yaml`), or define your own under `postprocess.styles`.
  The shipped rules now make email formal, chat casual, and code editors and
  terminals verbatim.
- **Paste last dictation.** `Alt+Shift+Z` (`Ctrl+Option+V` on macOS) types
  your last dictation again, e.g. after it landed in the wrong window. It waits
  until you let go of the keys, so held modifiers can't merge into the paste,
  and it never presses Enter. App rules still apply: nothing is pasted into a
  password manager, and copy-only apps like terminals get the clipboard
  instead. (`hotkey.paste_last_hotkey`)
- **Hands-free lock.** In push-to-talk mode, double-tap the record hotkey to
  keep recording without holding it, and tap once more (or press the stop key)
  to stop. A normal hold works as before. (`hotkey.double_tap_to_lock`)
- **Whisper mode.** Boosts quiet recordings before transcription so you can
  dictate under your breath. It only ever raises the volume, capped, and
  leaves silence alone. (`audio.whisper_mode`)
- The new options are in the Settings window, the hotkey cheat sheet and the
  startup hints.
- **`--doctor` checks the CUDA libraries** when `device: cuda` is configured.
  Before, it reported "All checks passed" on a machine that could not transcribe.

### Fixed
- **macOS: the app aborted on every launch (exit 134)**
  ([#14](https://github.com/drajb/whisper-local/issues/14), @rusifele). Startup
  created the shared `NSApplication` through pyobjc before any Tk window
  existed. Tk 9 installs its own subclass, `TKApplication`, only when it gets
  there first, and its drawing code calls selectors that exist only on that
  subclass. So when the level overlay built its window, Tk sent `-macOSVersion`
  to a plain `NSApplication` and the resulting `NSException` killed the process.
  That isn't a Python exception, so the overlay's `try`/`except` couldn't catch
  it and the log just stopped. Tk now creates the shared application first,
  through a hidden root kept for the life of the process. Tk windows on macOS
  also have to live on the main thread, which the menu-bar loop already owns, so
  the level overlay is off on macOS for now. The first-run welcome window runs on
  the main thread there, closes with `quit()` before `destroy()` (with the hidden
  root alive, `destroy()` alone would have hung every first launch), and closes
  when the app is asked to quit, where SIGTERM used to be swallowed.
- **NVIDIA GPU: transcription hung at "Transcribing…"**
  ([#15](https://github.com/drajb/whisper-local/issues/15), @stusona, diagnosed
  by @mav8557). Two bugs. First, the GPU check only asked CTranslate2 whether
  CUDA was supported, which the driver alone answers yes to, so onboarding
  switched the app to CUDA on machines with no cuBLAS or cuDNN at all. Those
  libraries load lazily on the first transcription, which then hung. The check
  now also loads `cublas64_12`, `cublasLt64_12`, `cudnn64_9`, `cudnn_ops64_9` and
  `cudnn_cnn64_9`, and offers to install them if any are missing. Second, the
  CUDA libraries onboarding pip-installs land in `site-packages\nvidia\*\bin`,
  which is on no DLL search path. Installing them did nothing until they were
  copied by hand into CTranslate2's folder. Those folders are now registered at
  startup.
  Configs already set to `device: cuda` without the libraries now stop at launch
  with a message naming what is missing, and offer to re-run GPU setup or use
  the CPU, instead of hanging on the first dictation. On windowless launches
  (autostart), where nobody can answer that prompt, the app uses the CPU for
  that session.
- **macOS: the fallback window, hotkey cheat sheet and add-word dialog could
  never open** (follow-through on
  [#14](https://github.com/drajb/whisper-local/issues/14)). Each built its Tk
  window on a background thread, which macOS doesn't allow. They now open in a
  small child process where Tk has the main thread to itself. A dictated
  transcript is handed over through a pipe, never on the command line. The
  `--history` and `--cheat-sheet` commands run their window on the main thread.
  Nothing changes on Windows.

### Changed
- The shipped per-app rules use named styles instead of individual toggles, and
  the specific app rules (password managers, terminals, code editors) now come
  before the chat and email rules. Title matching is by substring, so a code
  editor showing `slack_bot.py` used to match the chat rule and auto-send.
  Existing `app_rules.yaml` files are left as they are.
- Custom `postprocess.corrections` entries are no longer dropped when a setting
  is saved from the Settings window or the tray.
- `no` / `off` in the post-processing settings now mean off. YAML 1.2 reads
  them as text, which Python treated as "on".

## [0.19.0]

Everything reported by users on 0.18.3.

### Fixed
- **macOS 27: the app died on the first recording**
  ([#13](https://github.com/drajb/whisper-local/issues/13), @rusifele). Cocoa has
  always required AppKit to be touched from the main thread; through macOS 26 a
  background-thread menu-bar write only logged a warning, and macOS 27 turned it
  into a hard `SIGTRAP`. The tray was written from two worker threads — the
  recording thread swapping the icon and menu, and the level monitor rewriting
  the title every 150 ms — so pressing the hotkey killed the process outright,
  with nothing in the log. `SIGTRAP` is not a Python exception, which is why the
  `try`/`except` around every tray write could never have caught it.
  All tray writes now go through a platform `run_on_ui_thread()`, which
  dispatches to the main queue on macOS and calls straight through on Windows.
- **Filler-word stripping destroyed line and paragraph breaks**
  ([#9](https://github.com/drajb/whisper-local/issues/9), @Eevoo). With
  `strip_filler_words: true`, the `\n` and `\n\n` that inline formatting had
  just inserted were flattened into ordinary spaces, so "new paragraph" silently
  did nothing. Two causes, both fixed: the filler pattern's trailing `\s*` ate
  the following newlines, and a blanket `\s{2,}` collapse then flattened any
  that survived. Both are now restricted to spaces and tabs. Output is
  byte-identical with stripping on or off apart from the filler words themselves.
- **Transcript history closed the instant it opened**
  ([#10](https://github.com/drajb/whisper-local/issues/10), @ForrestOfBarnes).
  `--history` started the window on a daemon thread, slept half a second, then
  exited — and exiting kills daemon threads. The window really did appear and
  vanish. It now waits for the window to close. `--cheat-sheet` had the identical
  bug and is fixed too.
- **Clipboard-free dictation still touched the clipboard**
  ([#12](https://github.com/drajb/whisper-local/issues/12), @explorerzkb). With
  `delivery_method: type` and `type_also_copy_to_clipboard: false`, the two
  recovery paths (app-rule suppression, and no focused text field) copied anyway,
  and the popup copied a second time. Both now honour the setting.
  Those copies existed so the transcript could not be lost, so rather than just
  removing them, the text is surfaced in the recovery window — which holds it and
  offers an explicit Copy button. Privacy fixed without trading it for data loss.

### Changed
- **A per-app rule turning off auto-paste now says so**
  ([#11](https://github.com/drajb/whisper-local/issues/11), @ForrestOfBarnes,
  diagnosed by @Syncriix). Dictating into VS Code copies instead of pasting —
  that is the shipped code-editor rule working as intended, so nothing types into
  source unexpectedly — but nothing said so, and it reads as a broken app. The
  first time a rule makes delivery copy-only for an app, a notification explains
  it and points at `app_rules.yaml`. Once per rule per session, not once per
  dictation. The settings checkbox and the config comment now mention that
  per-app rules can override the global setting.

## [0.18.3]

### Added
- **`whisper-local --uninstall`** ([#8](https://github.com/drajb/whisper-local/issues/8),
  @JzTurrini). The standalone build is a portable `.exe` with no installer, so it
  never appears in Add/Remove Programs, and a `pip uninstall` leaves settings,
  logs, transcripts, an autostart entry and potentially gigabytes of downloaded
  models behind with no obvious way to find them.
  The command shows exactly what it found, with real sizes, and removes nothing
  without confirmation. Downloaded models are a **separate** prompt, because they
  are the large, slow-to-replace part and you may just be reinstalling. The
  HuggingFace cache is shared with other tools, so only directories matching
  Whisper's own model naming are ever considered — a CLIP or diarization model
  sitting beside them is never touched.

## [0.18.2]

### Fixed
- **Pause hotkey, properly this time**
  ([#7](https://github.com/drajb/whisper-local/issues/7), @Syncriix). The 0.18.1
  fix was necessary but incomplete. Pause re-registered hotkeys *from inside a
  hotkey callback*, and `global-hotkeys` 0.1.7 can't survive that: its checker
  iterates a **live view** of the bindings dict and invokes callbacks from inside
  that loop, so clearing mid-iteration raises `RuntimeError` and kills the
  checker thread; and its stop only flips a flag without joining, so restarting
  while the pause chord is still physically held gives the new thread blank
  press-state — it reads the held chord as a fresh press and toggles pause again,
  landing wherever timing decides.
  Pause now **never touches registrations**. Non-pause callbacks are wrapped in a
  gate that returns early while paused, and the pause key only flips the flag.
  Registration changes remain on the non-callback paths (startup, settings
  change, transforms refresh), where the 0.18.1 clear-first change is still
  correct and necessary.
- **`stop()` now lets the checker thread settle** before returning. The library's
  stop never joins and the checker polls every 20 ms, leaving a race where a
  caller that re-registers immediately clears the dict mid-iteration. Waits 200 ms
  (10 poll cycles; the library's own restart path waits 700 ms).

## [0.18.1]

All three open issues, reported with diagnoses and patches by
@Syncriix, @FosselDev and @chrysb.

### Fixed
- **The pause hotkey killed every hotkey until you restarted the app**
  ([#6](https://github.com/drajb/whisper-local/issues/6), @Syncriix). `global-hotkeys`
  keeps its registrations across `stop_checking_hotkeys()`, so re-registering the
  reduced pause-only set raised "already registered". The exception aborted the
  pause path *before* it could start listening again — leaving the app with no
  live hotkeys at all, pause included, so there was no way back. Windows
  `register()` now clears first, giving it the same replace semantics the macOS
  side always had.
- **Tray "Restart Whisper Local" failed on pip installs**
  ([#3](https://github.com/drajb/whisper-local/issues/3), @FosselDev). Restart
  built its command from `sys.argv`, but for a pip console script `argv[0]` is the
  launcher path and pip ships only a compiled `whisper-local.exe` stub there — no
  plain script for `python.exe` to open, so it died with "can't open file".
  Both restart paths now share one `utils.build_relaunch_command()`, which invokes
  the module with `-m`. They had drifted apart, which is exactly why fixing
  autostart in 0.16.2 left the tray broken.
- **macOS: a matched hotkey no longer types its key into your app**
  ([#4](https://github.com/drajb/whisper-local/issues/4), patch by @chrysb).
  `Option+Space` started dictation *and* inserted a space, because a global
  NSEvent monitor can observe keystrokes but never consume them. Hotkey detection
  now prefers a Quartz event tap, which consumes matched key-down/key-up events
  while leaving ordinary typing alone, ignores key-repeat, and re-enables itself
  if macOS disables the tap. The NSEvent monitor remains as a fallback when the
  tap can't be created (normally a missing Accessibility permission), so
  behaviour degrades to today's rather than breaking.

## [0.18.0]

Merges a round of outside improvements. Nothing existing was given up to do it —
where two approaches solved the same problem, both are kept and each is used
where it is genuinely better.

### Added
- **Startup "ready" chime** (`audio_feedback.ready_enabled`, on by default). A
  cold start spends a while loading the model and the app has no window, so an
  audible cue is the clearest signal that the hotkey is finally live.
- **Terminal tab title shows app state** — the tab reads
  `<prefix> Whisper Local` and follows idle/recording/processing. Each state is a
  static prefix or a list of `[prefix, seconds]` frames cycled as an animation
  (`terminal_title` config). Useful when the tray icon is buried in the overflow
  area. Self-disables when stdout isn't a terminal, so a windowless launch pays
  nothing and no escape codes leak into redirected logs.
- **Vocabulary corrections** (`postprocess.corrections`) — one canonical spelling,
  many misheard variants:
  ```yaml
  corrections:
      CAPEX: [cap x, copics]
      CTranslate2: [see translate two]
  ```
  This is the ergonomic shape when Whisper mangles the same term several ways.
  It complements, and does not replace, the existing per-entry
  `postprocess.replacements` (which keeps `whole_word` / `case_sensitive` /
  `regex` and is what the history window's "Fix this everywhere" writes).
  All variants compile into a single alternation applied in one pass, so cost
  doesn't grow with the size of your vocabulary, and longer variants always win
  over shorter ones they contain — with both `cap` and `cap x` defined, "cap x"
  can no longer be shadowed into a dangling "x".

### Fixed
- **AMD GPU detection misclassified several cards.** An RX 580 (Polaris, not
  RDNA) was read as RDNA1 and offered a runtime that cannot drive it, because the
  match only looked at one digit; a vendor string without a space (`RX5700`)
  wasn't matched at all; and Strix Halo / Ryzen AI MAX APUs (8040S/8050S/8060S)
  were never recognised, so GPU onboarding never fired for them. Now requires
  four digits, tolerates the missing space, and classifies the APUs.

## [0.17.1]

### Fixed
- **`--export-model` now explains a bad destination instead of dumping a Win32
  error.** Passing a drive that doesn't exist (e.g. `D:\transfer` on a machine
  with no D: drive) produced a raw `[WinError 3] The system cannot find the path
  specified`. It now says which drive is missing, lists the drives you do have,
  and suggests a working command. Permission problems get the same treatment,
  and the destination is validated *before* copying 148 MB rather than after.
- **`--export-model` takes no argument now** and writes to your Desktop, so the
  common case needs no path at all. Pass a folder to send it elsewhere.
- Docs no longer use `D:\transfer` in examples — it assumed a drive many
  machines don't have, which is what prompted this.

## [0.17.0]

### Added
- **Offline model transfer, for networks where `huggingface.co` is blocked.**
  Corporate networks routinely block or gate HuggingFace, which made first run
  impossible on a work machine. Two new commands move the model by hand — no
  admin rights, no IT ticket:
  ```bash
  whisper-local --export-model D:\transfer                             # machine with internet
  whisper-local --import-model D:\transfer\whisper-local-model-base    # offline machine
  ```
  Export copies the model out of the HuggingFace cache into a plain folder
  (resolving the cache's symlinks into real files, ~148 MB for `base`); import
  installs it, registers it, and makes it active. The app then treats it as
  already-downloaded and never contacts HuggingFace for it.
- **`--import-model --keep-in-place`** registers a folder without copying, so IT
  can host one canonical copy on a network share and every machine points at it.
  UNC paths and mapped drives both work.
- **[docs/offline-models.md](docs/offline-models.md)** covers all four routes:
  export/import, shared network drive, an internal HuggingFace mirror via
  `HF_ENDPOINT`, and exactly what to ask IT to allowlist (one host, four static
  files, once). It also explains why *self-hosting the model on HuggingFace does
  not help* — a domain block applies to your repo there too.

## [0.16.2]

### Fixed
- **"Start on login" opened a Python console instead of the app**
  ([#2](https://github.com/drajb/whisper-local/issues/2), thanks @asherwin86).
  On the standalone `.exe`, autostart registered `sys.executable` — but pyapp
  unpacks a private CPython and runs the app with it, so that path is the bare
  *interpreter*, not `whisper-local.exe`. Booting it launched an interactive
  Python prompt in a terminal and Whisper Local never started. Autostart now
  uses the executable path pyapp exports as `$PYAPP`, matching what the tray's
  Restart item and the GPU-onboarding relaunch already did.
- **Existing broken entries repair themselves.** Anyone who already enabled
  autostart still had the bad value in their registry, which a code fix alone
  wouldn't touch. On startup the app now detects an entry that is a lone
  interpreter with no script and rewrites it. Deliberately narrow — an entry
  with arguments, or one pointing at the app executable, is never modified.
- **No more console window at boot for some pip installs.** If `pythonw.exe`
  wasn't beside the interpreter (seen with some venv and Microsoft Store
  layouts), autostart silently fell back to console `python.exe`. It now also
  checks the base interpreter before falling back, and logs a warning when it
  genuinely can't find a windowless launcher.

### Internal
- Lint sweep with no behaviour change: removed 9 genuinely unused imports and
  dropped the `f` prefix from 19 f-strings that had no placeholders. The
  remaining flagged imports are deliberate availability probes and are left
  as-is. Personal AI-assistant scaffolding in the working copy is now
  gitignored so it can't be published by an `add -A`.
- Roadmap bug list reconciled with what actually shipped in 0.16.0.

## [0.16.1]

### Fixed
- **Long dictations no longer freeze the app.** Post-processing was quadratic in
  two places: the "scratch that" scan and the punctuation-absorb pass. A ~3,000
  word transcript took **6-13 seconds** to process — long enough to look like a
  hang, and increasingly likely with continuous dictation and system-audio
  capture. Both are now linear: the same transcript processes in **under 0.03 s**
  (~700x faster for absorb, ~1650x for voice editing). Behaviour is byte-for-byte
  identical — verified by a 4,000-case randomised differential test against the
  previous implementation, plus a performance regression test.
- **A malformed settings file can no longer break transcription.** A scalar where
  a mapping belongs (e.g. `smart_formatting: true` instead of the sub-toggles)
  raised mid-pipeline and lost the dictation; malformed `smart_formatting`,
  `ollama`, and `replacements` sections now degrade to "feature off".
- **`--transcribe-system` test no longer depends on the machine's setup.** The
  soundcard-absent test passed only where the optional extra wasn't installed and
  failed everywhere it was; it now simulates absence properly.

### Documentation
- **Every module now opens with a header comment explaining its purpose** — 46 of
  73 modules were missing one, including core files (`state_manager`'s pipeline,
  `config_manager`, `system_tray`, `text_postprocess`) and the whole platform
  layer, where each header now also names its counterpart on the other OS.
- Intent comments added to the largest previously-bare functions (the
  transcription pipeline, tray menu construction, hotkey setup, PE import
  parsing, and the Tk window bodies).
- A test now enforces the module-header rule from CLAUDE.md, so the standard
  can't silently decay as files are added.

## [0.16.0]

### Added
- **Post-transcription corrections** (`postprocess.replacements`) — literal,
  whole-word, case-insensitive text fixes applied after Whisper and before any
  Ollama step, for consistent misrecognitions ("see translate two" →
  "CTranslate2"). Regex-escaped by default; an optional `regex: true` per entry
  for power users (a bad pattern is skipped, never crashes the pipeline).
- **Self-improving accuracy from the history window.** "Fix this everywhere…"
  turns a misrecognition in any past transcript into a persistent correction,
  and "Suggest hotwords" mines your own dictation history for frequent
  proper-noun-ish words and offers to add them to your dictionary — all offline,
  you confirm each one. The running app hot-reloads corrections, so a fix
  applies on your next dictation without a restart.
- **Deterministic smart formatting** (`postprocess.smart_formatting`, each
  sub-toggle off by default): `times` ("3 p.m." → "3 PM"), `emails` ("john at
  example dot com" → "john@example.com"), `urls` ("example dot com" →
  "example.com"). Pure regex, no LLM; gated on a trailing known TLD so they
  rarely touch ordinary prose.
- **Voice editing** (`postprocess.voice_editing`) — say "scratch that" (or
  "delete that" / "strike that") to erase what you just said back to the start
  of the sentence: "book the flight, scratch that, cancel it" → "cancel it".
- **System-audio capture (experimental, opt-in)** — `whisper-local
  --transcribe-system [SECONDS]` transcribes what you *hear* (meetings, videos),
  not just the mic, via the optional loopback extra
  (`pip install whisper-local[loopback]`). Fully isolated from the live mic
  stream. Windows/macOS; needs the extra installed.
- New settings-window checkboxes for voice editing and the three smart-formatting
  toggles.

### Fixed
- **First-run model download now says what it's doing.** The download message
  names the model and its approximate size ("Downloading the 'base' model
  (~141 MB) — first run only…") instead of a bare "Downloading model".
- **No more silent close when another copy is already running and unresponsive.**
  The standalone `.exe` / autostart launch is windowless, so the takeover-failed
  message went nowhere; it now shows a dialog box on Windows explaining what to do.

## [0.15.0]

### Added
- **Formatting changes now apply on your next dictation — no restart needed.**
  Editing the post-processing section (inline formatting, filler-word stripping,
  cue-word phrases) in `user_settings.yaml` or the settings window used to require
  a full app restart. The config now hot-reloads that section on file change, so
  tweaks to how your speech is punctuated take effect immediately.
- **"Restart Whisper Local" tray item.** Hotkey, model, and audio-device changes
  still need a restart to take effect; you can now do it from the tray in one
  click instead of hunting down the process. Relaunches the standalone `.exe`
  when running as one, otherwise re-execs the current interpreter.
- **Errors now flash where you're looking.** When a dictation produces no audio
  ("No audio — mic muted?") or no speech ("No speech detected"), the level
  overlay shows the reason for two seconds instead of silently vanishing — tray
  balloon notifications are often suppressed by Windows focus-assist, so the
  failure was easy to miss.
- **Two new checkboxes in the settings window's Post-process tab** for
  `inline_formatting_absorb_punctuation` (fixes doubled punctuation like
  "hello,, world") and `inline_formatting_extend`, with a pointer to the
  `inline_formatting_replacements` map in the settings file.

### Changed
- **First-launch console banner shows your actual hotkeys.** It previously
  hardcoded the Windows defaults (`Ctrl+Win`, etc.), which were wrong on macOS
  and after any customization; it now interpolates the configured record,
  rephrase, command, cancel, and pause keys.
- **Tray menu decluttered.** Removed the duplicate "Open settings file..." entry
  (it did the same thing as "Edit hotwords / settings..."), renamed the survivor
  to "Edit settings file...", and folded the six diagnostic actions into a
  "Help & diagnostics" submenu.
- **Honest Save dialog.** The settings-window save confirmation no longer implies
  every change is instant; it spells out that formatting applies on the next
  dictation while hotkey/model/audio changes need a restart.

## [0.14.1]

### Fixed (security sweep)
- **Reset to defaults no longer wipes your dictionary.** The `--settings` reset
  promised hotwords survive but deleted the file they live in; it now preserves
  `whisper.hotwords` across the reset.
- **Diagnostic bundle no longer leaks Ollama credentials.** A custom endpoint with
  `user:pass@` or `?token=` was masked in `user_settings.yaml` but printed verbatim
  in `doctor.txt` in the same public-issue zip; URL credentials and secret query
  params are now scrubbed from every bundled file.
- **`--serve` rejects negative `Content-Length`** (previously bypassed the upload cap).
- **Inline-formatting absorb mode** no longer glues words or eats paragraph/line
  breaks when used with the built-in English cue words.
- README now documents the standalone `.exe` install path + SmartScreen note;
  troubleshooting covers the unsigned-app warning and first-launch bootstrap wait.

## [0.14.0]

### Added
- **`inline_formatting_absorb_punctuation`** (opt-in) — when you speak cue words,
  Whisper inserts its own prosody punctuation around them ("hello comma world" →
  "Hello, comma, world."), which a literal swap left as artifacts ("Hello,, world.").
  With this on, each cue phrase also absorbs the runs of commas/periods/whitespace
  hugging it, and the replacement's own spacing wins (define e.g. `", "` / `" → "`).
  Pure-`re`, regex-escaped, word-boundary guarded — no ReDoS/injection. Fixes the
  polluted-output bug reported in Discussion #1 by @mz8i. Default off (no regression).

## [0.13.0]

### Added
- **Per-app formatting overrides** — app rules (`app_rules.yaml`) can now set
  `capitalize_first`, `ensure_punctuation`, `strip_trailing_period`, and
  `inline_formatting` per app, on top of the existing prompt/language/delivery
  controls. Adapt the writing style by context: verbatim in a code editor, full
  sentences in email. Ships with a sensible code-editor default.
- **Streaming commit-on-endpoint delivery (experimental, opt-in)** —
  `streaming.deliver_to_cursor: true` (requires `streaming_enabled`). Finalized
  phrases are typed to the cursor *as you speak* (Wispr-Flow style) and the final
  Whisper pass is skipped for that recording. Delivery runs on a dedicated worker
  thread so the audio callback never blocks. Only applies to plain dictation into
  a real text field with auto-paste on; command/rephrase modes and
  copy-only/suppressed apps are unaffected. Trade-off: the lighter streaming
  model's accuracy instead of the full Whisper transcription.

## [0.12.0]

### Added
- **Customizable inline voice formatting** (`postprocess.inline_formatting_replacements`)
  — define your own spoken-phrase → symbol map, essential for non-English dictation
  (e.g. Polish) where Whisper won't emit the built-in English triggers. Runs after
  Whisper and before any Ollama step; whole-word, case-insensitive, regex-safe. By
  default replaces the English defaults; `inline_formatting_extend: true` keeps them
  and appends yours. (Requested in Discussion #1 by @mz8i.)

## [0.11.0]

### Added
- **Start on login (autostart)** — opt-in, built in. New `autostart` module (Windows
  `HKCU\...\Run` via stdlib `winreg`; macOS LaunchAgent). Enable via the tray
  **Start on login** checkbox, the first-run welcome checkbox, or
  `whisper-local --enable-autostart` / `--disable-autostart`. Launches windowless
  (no console flash). Off until you choose it.

### Changed
- **Default Whisper model is now `base`** (was `tiny`) — noticeably more accurate out
  of the box and still real-time on CPU (~141 MB first download).
- **Default recording mode is now `push_to_talk`** (was `toggle`) — hold the hotkey to
  talk, release to transcribe. This matches the onboarding/setup-wizard guidance
  (previously the welcome screens said "hold" while the default was toggle).

## [0.10.0]

### Added
- **Local OpenAI-compatible API server** (`whisper-local --serve`) — exposes `POST /v1/audio/transcriptions` on `localhost:7777`. Drop-in for Cursor, Open WebUI, VS Code Continue, n8n, anything that speaks the OpenAI Whisper API. Fully offline.
- **`--selftest` command** — automated sanity check: audio capture, model load, end-to-end transcription, clipboard round-trip. Catches 90% of first-launch issues in one command.
- **`--cheat-sheet` command** — opens a window showing your **currently configured** hotkeys, including transform hotkeys. Reachable from the tray (**Hotkey cheat sheet...**).
- **`--bundle-logs` command** — creates a redacted zip of recent logs + `--doctor` output + crash dumps. Attach to bug reports. Reachable from the tray (**Bundle logs for bug report...**).
- **First-run welcome window** — appears once on first launch with 3 short tips (tray icon location, hotkey hint, troubleshooting commands). Privacy assurance baked in.
- **Audio device disconnect recovery** — if a USB mic is unplugged mid-recording, the app falls back to default input and resumes silently (up to 3 retries).
- **Silent-mic detection** — if the recording is essentially zero amplitude, the app warns the user (mic muted / unplugged / OS permission denied).
- **Settings UI search box** — filter settings across all tabs with live highlighting. Ctrl+F focuses search.
- **Settings UI Reset / Backup / Restore buttons** — one-click reset to defaults, plus Backup… and Restore… file pickers wired to `--export-settings` / `--import-settings`.
- **Settings UI** — 4-tab Tkinter window covering all common settings; no YAML editing required.
- **Transcript history window** (`--history`) — searchable browser of every past transcription with preview pane and click-to-copy.
- **Persistent transcript journal** — every successful delivery is appended to `transcripts.jsonl` (last 2000 entries, auto-rotates).
- **Noise suppression** (`audio.noise_suppression.enabled`) — opt-in spectral gating via `noisereduce`; install with `pip install 'whisper-local[noise]'`.
- **Opt-in update notifications** (`update_check.enabled`) — daily GitHub release check; no audio or transcript data is ever transmitted.
- **Release pipeline** (`.github/workflows/release.yml`) — tag-triggered CI: tests → build wheel → publish to PyPI → create GitHub Release with the wheel attached.
- **Community setup** — `CODE_OF_CONDUCT.md`, `SECURITY.md`, `AUTHORS.md`, `CITATION.cff`, issue/PR templates, Dependabot, `.editorconfig`.
- **Docs** — `docs/troubleshooting.md` and `docs/faq.md` for the most common questions and symptom→fix table.

### Changed
- Repositioned README for open-source / privacy-first audience; expanded SEO and comparison tables (Wispr Flow, Dragon, Otter, WSR).

## [0.9.0] - 2026-05-11 (drajb/whisper-local fork)

### Added
- **Floating level overlay** — Wispr Flow–style pill at the screen edge that vibrates with your voice, shows the live streaming transcript, morphs to "Transcribing…" during processing, and flashes green/red on success/failure. Configurable position (6 presets), click-through by default.
- **Notepad fallback** — if the foreground window is the desktop / Start Menu / no text field, the transcript opens in Notepad instead of disappearing.
- **Always-clipboard safety net** — every transcript is copied to the clipboard *before* any paste routing; you can always `Ctrl+V` anywhere as a recovery.
- **Dedicated rephrase hotkey** — `Ctrl+Shift+Win` selects, records instruction, sends to Ollama, pastes the rewrite back. No voice-command-mode detour.
- **Pause-all hotkey** — `Ctrl+Alt+Win` disables all Whisper Local hotkeys (except itself) until pressed again.
- **Smart Whisper prompt from selection** — opt-in `whisper.prompt_from_selection`: at recording start, the active selection seeds Whisper's `initial_prompt` for that recording.
- **Translation profile** — Whisper `task=translate`: speak any language, get English.
- **Continuous mode** — `audio.continuous_mode`: auto-restart recording after each delivery (Esc exits).
- **Auto-pause media** — `audio.pause_media_on_record`: sends system play/pause on recording start so Spotify/YouTube go quiet.
- **Voice command macros** — `then:` chain in `commands.yaml`, with a `delay: <seconds>` step for pacing.
- **Vocab import** — `whisper-local --import-vocab FOLDER` scans text files, ranks proper nouns / jargon by frequency, merges top 50 into `whisper.hotwords`.
- **Transcript export** — `whisper-local --export-transcripts FILE.{txt,md,csv}`.
- **Daily summary toast** — first launch of the day shows yesterday's word count and minutes saved.
- **Audit log** — opt-in `audit.enabled`: append-only `audit.log` of timestamp + event + app + char-count (no transcript text).
- **AI rephrase voice commands** — select text, say "make this concise" / "make this professional" / "fix grammar"; the selection is sent to local Ollama and the response replaces it.
- **Inline voice formatting** — say "comma", "period", "new line", "new paragraph", "question mark", "open quote", "dash" etc. mid-sentence to insert punctuation/structure.
- **Voice command DSL upgrade** — `match_regex:` patterns, `${selection}` / `${clipboard}` template vars, per-command `confirm:` flag.
- **Risky-shell confirmation** — voice commands matching dangerous patterns (`rm -r`, `format`, `shutdown`, redirects, `sudo`, etc.) now prompt before executing.
- **Setup wizard** — `whisper-local --setup` walks model selection (hardware-aware), recording mode, and microphone.
- **Stats dashboard** — `whisper-local --stats` and tray item show transcription history, words, minutes saved vs typing.
- **Multi-language quick-switch** — tray submenu of 15 languages, hot-swaps `whisper.language`.
- **Whisper warmup** — model runs a 1-second zeros transcription right after load so the first real recording skips JIT.
- **Auto-trim trailing silence** — VAD-style RMS scan trims the tail of each recording, removing Whisper's silence-induced hallucinations.
- **Tray mic level meter** — animated 6-bar level inside the tray icon's tooltip while recording.
- **Per-profile Whisper `initial_prompt`** — each profile primes Whisper for its context (code identifiers, chat tone, markdown notes).
- **Pre-roll audio buffer** — `sd.InputStream` is opened once at startup and runs continuously. A 500ms ring buffer is prepended to every recording, eliminating first-word clipping on push-to-talk launches. `latency='low'` for smaller PortAudio buffers.
- **Restart-on-second-launch** — launching while an instance is running now terminates the existing process via PID file + SIGTERM and takes over the lock instead of refusing to start.
- **`whisper-local --doctor`** — structured health check across runtime, dependencies, config, audio, model cache, hotkeys, and recent log errors.
- **Recent transcriptions menu** — last 10 transcriptions kept in a deque and exposed via `Recent` submenu in the system tray; click any to copy back to clipboard.
- **Hot-reload commands.yaml** — the file's mtime is checked before each match; edits take effect on the next transcription with no restart.
- **Tray notifications on failure** — empty transcription / no audio captured surface as a tray toast instead of silently dropping.
- **Crash reports** — uncaught exceptions write a timestamped report to `%APPDATA%\whisperkey\crashes\` with the traceback and last 50 log lines.
- **Log rotation** — `app.log` rotates at 5MB with 3 backups (was unbounded).
- **Smoke test suite** — `python -m unittest tests.test_smoke` covers package metadata, instance-manager wiring, hotkey utilities, asset path resolution, and YAML safety properties.
- **Personal launcher** — `whisper-local.cmd` plus Start Menu and Startup-folder shortcuts.

### Changed
- Rebrand from `whisper-key-local` → `whisper-local`. CLI: `whisper-local` / `wl`. Display name: "Whisper Local". Repo URL: `drajb/whisper-local`.
- Audio host matcher now does substring matching, so `audio.host: WASAPI` correctly resolves to "Windows WASAPI" instead of falling back to MME.
- Auto-updater removed entirely (network call + pip install path).
- Risky `reg add` voice commands removed from defaults.
- GitHub Actions workflows for Claude review removed (no longer wired to a secret).

### Fixed
- Defensive `os.path.isdir` checks around DLL search dirs in `platform/windows/gpu.py` (skips non-existent entries from `PATH`).

---

## [0.8.1] - 2026-04-18

### Added
- **Push-to-talk mode** - New `hotkey.recording_mode` config: hold the recording hotkey to record, release to stop and transcribe (#45)
- **Console window management** - Two exe variants:
  - `whisper-key.exe` - runs in Windows Terminal with full color (same as before)
  - `whisper-key-hideable.exe` - conhost with hide-to-tray support (`console.start_hidden` config option) (#50)

### Fixed
- Stop key requiring two presses in toggle mode (#54)

## [0.8.0] - 2026-03-17

### Added
- **GPU onboarding** - Detects your GPU on first launch and offers one-press install of CUDA or ROCm runtime libraries. Supports NVIDIA, AMD RDNA 2+, and RDNA 1 (manual setup) (#44)
- **Auto-update** - Checks PyPI for new versions on startup with option to update in-place (#43)
- **GPU and runtime detection** - Shows GPU model and runtime status on startup (#41)
- **Overlay config** - Config updates now merge cleanly without overwriting user comments or structure (#40)
- `initial_prompt` config option to bias Whisper transcription toward expected content (#39)
- `log_transcriptions` config option (default: off) for privacy

### Changed
- **Replaced PyInstaller with pyapp** - Windows exe is now a single `whisper-key.exe` that bootstraps its own Python environment. No more zip extraction or separate AMD variant (#42)
- Updated README for new install flow

### Removed
- PyInstaller build system and related runtime hooks

## [0.7.1] - 2026-03-08

### Added
- **Transcription complete sound** - Optional audio notification when transcription finishes (`audio_feedback.transcription_complete_enabled`) (#35)
- **Custom hotwords** - Bias transcription toward specific words/phrases via `whisper.hotwords` config (#34)
- **Open model cache** shortcut in system tray menu
- CONTRIBUTING.md with PR guidelines

### Fixed
- **Portable exe crash on startup** - `commands.defaults.yaml` was not bundled in PyInstaller build, causing `[WinError 2]` crash when voice commands initialize (#37)
- Startup error handler now logs full traceback for better crash diagnostics

## [0.7.0] - 2026-02-27

### Added
- **Voice command mode** - Dedicated hotkey (`Alt+Win` / `Fn+Command`) records speech and matches against user-defined trigger phrases in `commands.yaml` (#33)
  - `run` action — execute shell commands (e.g., "open notepad" → `notepad.exe`)
  - `hotkey` action — send keyboard shortcuts (e.g., "undo" → `Ctrl+Z`)
  - `type` action — deliver pre-written text (e.g., "my email" → `user@example.com`)
  - Case-insensitive substring matching with longest-trigger-first priority
  - Auto-send support — press `Alt` to stop and send ENTER after type commands
- **Commands file shortcuts** in system tray menu for quick editing
- Terminal tab title set to "Whisper Key" on startup

### Changed
- **Hotkey config refactored** — replaced `stop_with_modifier` toggle with explicit `stop_key` and `auto_send_key` settings
- Recording hotkey is now start-only (no longer toggles)
- Cleaner console messages: one-line-per-hotkey format, indented recording output
- Renamed `documentation/` folder to `docs/`
- macOS config path moved to `~/.whisperkey`
- Updated GPU setup guide: simplified ROCm instructions, updated wheel versions

### Fixed
- ROCm runtime hook now finds pip-installed HIP SDK

## [0.6.3] - 2026-02-17

### Added
- **Direct text injection** - New `type` delivery method using native ctypes `SendInput` with `KEYEVENTF_UNICODE`, bypassing clipboard entirely (Windows only) (#21)
- **Configurable delivery method** - Choose between `paste` (clipboard + Ctrl+V) and `type` (direct key injection) via `clipboard.delivery_method`
- **Pre-paste delay** - `paste_pre_paste_delay` setting (50ms default) fixes intermittent empty paste caused by Windows Clipboard History service contention (#21)
- **Scaling auto-enter delay** - Type mode delay before Enter now scales with text length: `type_auto_enter_delay + chars/100 * type_auto_enter_delay_per_100_chars`
- **Real-time speech preview** - Experimental streaming transcription using sherpa-onnx (enable with `streaming.streaming_enabled: true`; downloads a small ~20MB model on first use)
- **Application icon** - PyInstaller exe now has a proper app icon
- **`wk` CLI alias** - Short command alias for `whisper-key`

### Fixed
- **Auto-paste empty text bug** - Clipboard race condition where Windows Clipboard History service contests clipboard between copy and paste, causing target app to receive nothing (#21)

### Changed
- Replaced pyautogui with native ctypes `SendInput` for keyboard simulation on Windows (smaller dependency footprint, atomic key injection)
- Restructured clipboard config: `paste_*` prefix for paste-mode settings, `type_*` for type-mode settings, `macos_*` for macOS-only
- Delivery method validation moved into platform keyboard modules
- Default `paste_clipboard_restore_delay` set to 0.5s

### Removed
- **pyautogui** dependency — replaced by native ctypes

## [0.6.2] - 2026-02-09

### Added
- **AMD GPU portable exe** - Separate ROCm build variant for AMD RX 5000+ GPUs
- **CPU/GPU mode display** - Shows device mode and compute type on startup
- **Distil-whisper models** - Added distil-medium.en and distil-small.en to default config

### Fixed
- **Model load crash** - Bundled correct MSVCP140.dll instead of PyInstaller's incompatible version (#22)
- **Tray icon path** - Fixed icon resolution for PyInstaller builds using `resolve_asset_path()`

### Changed
- Updated GPU setup guide with pip, pipx, and portable exe instructions for AMD GPUs
- Updated README with AMD GPU download variant

## [0.6.1] - 2026-02-04

### Added
- **macOS support** - Full platform abstraction layer with native integration for hotkeys (NSEvent), keyboard simulation (Quartz CGEvent), and system tray (#23)
  - Fn key modifier support for hotkeys
  - Accessibility permission prompt for auto-paste
  - Platform-specific default hotkeys: fn+ctrl (record), shift (cancel), cmd+v (paste)
- `--test` flag for running a separate test instance alongside the main app
- CUDA setup instructions in config file comments (cuDNN no longer required)

### Changed
- Reduced console verbosity by removing config update messages
- ten-vad is now a standard PyPI dependency (no separate install step needed)
- Updated README with macOS installation and usage instructions

### Fixed
- UTF-8 stdout encoding for special characters on Windows
- Audio feedback sounds going silent after idle periods on Windows (switched to winmm backend)
- PyPI package missing platform-specific tray icons
- PyInstaller build: ten_vad path and Windows platform assets

### Dependencies
- **ten-vad**: Now `>=1.0.6` (was git-only)
- **pyobjc-framework-Quartz**: Added for macOS (keyboard simulation)
- **pyobjc-framework-ApplicationServices**: Added for macOS (Accessibility permissions)

## [0.5.3] - 2026-01-19

### Fixed
- PyInstaller crash with ctranslate2 4.6.3 due to bundled MSVCP140.dll version mismatch

### Changed
- Replaced scipy with soxr for audio resampling (smaller bundle size)

### Dependencies
- **scipy**: Removed - no longer required
- **soxr**: Added `>=0.5.0` for high-quality audio resampling

## [0.5.2] - 2026-01-16

### Fixed
- Single-key hotkeys (e.g., F13) causing "hotkey already registered" error when `stop_with_modifier_enabled` was true (#14)

## [0.5.1] - 2026-01-16

### Fixed
- User settings file was showing "DO NOT EDIT THIS FILE" header from the defaults template

### Added
- Configurable paste hotkey setting (`clipboard.paste_hotkey`) - workaround for Claude Code changing CTRL+V to CTRL+SHIFT+V (possibly a bug)
- Console messages when opening log file and settings from system tray

## [0.5.0] - 2026-01-15

### Added
- **Custom local model support** - Load any Whisper model from a local folder or HuggingFace path (#10)
- **New models**: large-v3-turbo and distil-large-v3.5
- **View Log** shortcut in system tray menu (#9)
- **Advanced Settings** shortcut in system tray menu

### Changed
- Config key renamed from `whisper.model_size` to `whisper.model`
- Model menu in system tray now built dynamically with grouped separators
- Updated model download sizes to reflect actual faster-whisper downloads

### Fixed
- Cache detection for non-Systran models (e.g., large-v3-turbo showed "Downloading..." when already cached)
- Config section headers duplicating on save

### Dependencies
- **faster-whisper**: `>=1.1.1` → `>=1.2.1`
  Required for distil-large-v3.5 support
- **ctranslate2**: Added explicit `>=4.6.3` requirement
  May fix GPU crashes on systems without cuDNN installed (#15)

## [0.4.0] - 2026-01-14

### Added
- Audio source selection from system tray menu (WASAPI devices)
- WASAPI loopback support with bundled custom PortAudio DLL for recording system audio
- Version display in startup message

### Fixed
- WASAPI devices that don't support 16kHz now work via automatic resampling
- WASAPI stream reopen race condition with OS-level cleanup delay
- User feedback when audio device switch fails

## [0.3.0] - 2025-08-19

### Added
- Complete PyPI package distribution support with robust asset resolution
- Audio recording duration display
- Cancel recording hotkey with distinct sound feedback

### Changed
- Unified version tracking from pyproject.toml
- Centralized user data directory with proper app.log location handling
- Enhanced release script to include git push and use version-specific changelog notes
- Updated README with new install instructions

### Fixed
- Various typos and documentation inconsistencies

## [0.2.0] - 2025-08-15

### Added
- Max recording duration with callback-based duration limiting for audio capture
- Intelligent hotkey conflict detection with automatic resolution
- Global exception handling with stderr redirection to app.log
- VAD configuration reorganization into dedicated Voice Activity Detection section
- Instance Manager component (renamed from single_instance.py for consistency)

### Changed
- Massive code reduction: 50% reduction across 11 core files (4,200 → 2,087 lines)
- Complete removal of redundant docstrings and beginner-friendly comments
- Simplified component interfaces and eliminated circular dependencies
- Enhanced build script with improved Start Menu compatibility and asset path resolution
- Updated automation workflow to focus on real issues over defensive programming
- Exception handling standardization across all components
- Import reorganization following PEP 8 standards
- Magic number extraction to named constants
- Component interface simplification with better separation of concerns

### Fixed
- Critical race conditions in transcription pipeline and pending model changes
- Bare except clause that could mask critical exceptions
- Inconsistent OptionalComponent usage in SystemTray type annotations

### Removed
- Entire test suite to focus on shipping over ceremony
- Defensive programming patterns and unnecessary validation
- Windows API clipboard fallback complexity
- Complex model loading progress tracking
- Redundant configuration options and unused settings
- Dead code and unused functions throughout codebase

## [0.1.3] - 2025-08-11

### Added
- Comprehensive CHANGELOG.md for project releases
- Version bump command for Claude AI assistant

### Changed
- Updated build instructions and removed redundant builder.py

### Fixed
- Single instance detector exit error in built executable

## [0.1.2] - 2025-08-11

### Added
- Single-instance detection with mutex to prevent multiple app instances
- TEN VAD (Voice Activity Detection) pre-check system with advanced post-processing
- Audio feedback component for recording events
- PyInstaller packaging system for Windows executable distribution
- Auto-enter hotkey functionality with configurable modifiers
- Stop-with-modifier hotkey functionality
- Alternative keycode checker tool for hotkey configuration
- Context manager for consistent error handling across components

### Changed
- Default Whisper model changed from `tiny` to `base` for better accuracy
- Default hotkeys updated to CTRL+WIN+SPACE (record) and CTRL+WIN+SHIFT+SPACE (stop)
- Renamed `auto_enter_delay` to `key_simulation_delay` for clarity
- Simplified clipboard copy operation for better performance
- Default console logging level set to warning for regular users
- Disabled UPX compression in PyInstaller to reduce antivirus false positives
- Improved system tray model selection to show actual model names
- Streamlined user feedback messages around clipboard actions and startup

### Fixed
- CTRL+C unresponsiveness by adding proper hotkey listener cleanup during shutdown
- Windows key support in hotkey detection
- Auto-enter hotkey now respects auto-paste setting
- Config validation now persists properly to user settings file
- YAML structure corruption by using clean config template
- Unicode logging errors on Windows
- Executable Start Menu launch bug with working directory
- Module imports after directory refactor

### Removed
- `suppress_warnings` config option and related code
- Redundant system tray print statements
- Duplicate "Ready to paste" message

## [0.1.1] - 2025-07-15

### Added
- Complete working whisper speech-to-text application
- Comprehensive configuration system with YAML support
- Interactive key helper utility for hotkey configuration
- Auto-paste feature with Windows API integration
- System tray icon functionality with visual recording status
- User settings system with system tray controls
- Clipboard preservation feature
- Model selection submenu in system tray
- English-specific model options
- Async model loading with responsive system tray
- Tool to clear application log file
- Tool to clear model cache

### Changed
- Refactored project structure and updated documentation
- Renamed main.py to whisper-key.py for better clarity
- Renamed log file from whisper_app.log to app.log
- Updated to use faster-whisper framework
- Improved model download messaging with cache detection

### Fixed
- Module imports and directory structure issues
- System tray menu organization and cleanup

## [0.1.0] - 2025-06-01

### Added
- Initial project setup
- Core speech-to-text functionality
- Basic hotkey detection
- Audio recording capabilities
- Clipboard integration