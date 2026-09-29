# Whisper Local — Code Audit & Improvement Backlog

**Last updated:** 2026-09-28
**Audited versions:** 0.10.0 (Round 1, below) and 0.11.x (Round 2, next section)
**Method:** Parallel subsystem reviews + manual verification of every finding before fixing.

> This is a living document. Each issue has a stable ID (e.g. `SRV-1`) so commits and PRs can reference it. When you fix one, change its **Status** to `FIXED (<commit>)` rather than deleting it, so history stays readable.

---

## Round 13 (0.21.0) — the defaults that never updated (2026-09)

Found while checking whether 0.20.0's app-rule reordering actually reached
anyone. It hadn't. `app_rules.py`, `voice_commands.py`, `transforms.py` and
`profiles.py` each copied their shipped defaults into the user's config folder
once, on first launch, and read only that copy afterwards. So every improvement
to a shipped file landed for new installs and for nobody else.

Measured on the maintainer's own machine, seeded 7 May:

| file | shipped | theirs |
|---|---|---|
| `app_rules.yaml` | 5 | 4 |
| `commands.yaml` | 21 | 19 |
| `profiles.yaml` | 5 | 4 |
| `transforms.yaml` | 6 | 6 |

Eleven releases of drift, including the fix for a code editor showing
`slack_bot.py` matching the chat rule and auto-sending.

The fix follows the split config already used (`config.defaults.yaml` ships the
base, `user_settings.yaml` holds overrides): `defaults_merge.py` loads the
shipped entries from the package on every start and layers the user's file over
them. Shipped app rules carry a stable `id`; commands, transforms and profiles
keep the identity they already had (`trigger`, `name`, the mapping key) rather
than growing a parallel naming scheme.

Decisions worth recording:
- **User entries are matched before shipped ones.** For app rules first match
  wins, so anything someone wrote themselves has to outrank the defaults.
- **A key the user left out is not an override.** Their file predates the key,
  so it keeps following the shipped entry. This is what lets the new `style:`
  values reach an old file.
- **An edited match list re-binds to the shipped rule it overlaps most.**
  Caught during review: editing a rule's `match` changes its identity, so the
  migration saw a brand-new rule and the shipped one loaded behind it. Someone
  who removed Discord from the chat rule would have had Discord auto-sending
  again, silently. The override now replaces the shipped list.
- **A null action clears the one a shipped command came with.** The merge keeps
  the shipped `hotkey` key, so `_execute_action` had to test values rather than
  key presence; it was dispatching cleared actions.
- **`--doctor` reports effective totals**, since counting an overrides-only file
  would have told people they had 0 rules while five were in force.

The original file is backed up to `<name>.yaml.<date>.bak` before the one-time
rewrite. 19 tests in `LayeredDefaultsTests`; 282 pass.

## Round 12 (0.20.0) — Wispr Flow–style features (2026-09)

Gap analysis against Wispr Flow's shipped features (Command Mode, Styles,
Snippets, Backtrack, hands-free, paste-last, whisper mode, …). Built only what
works fully offline and can be tested without a desktop: `dictation_cleanup.py`
(backtrack, stutters, spoken lists, lowercase), `snippets.py`, `styles.py`,
`hotkey_gestures.py` (double-tap lock), and `audio_gain.py` (whisper mode),
plus a paste-last hotkey.

Design constraints carried over from earlier rounds:
- **Every text pass is O(n).** Two earlier regex passes froze the pipeline for
  about 7 s on long dictations, so the new passes use find-then-expand scans
  and have a large-input timing test.
- **Nothing rewrites prose on a guess.** Backtrack needs a typed value after
  the cue, lists need markers counting up from one plus punctuation, and
  lowercase leaves acronyms, mixed case and the user's corrections alone.
- **Style resolution happens once** (`app_rules.effective_postprocess_config`),
  so the global style can't override an app rule's.
- **Paste-last fires on key release** and waits for physical modifiers
  (`keyboard.modifiers_held()`, new and mirrored), because a synthetic Ctrl+V
  while Alt+Shift is held arrives as Ctrl+Alt+Shift+V.

A pre-release adversarial review found, and this round fixed:
- a blocker: paste-last never fired on macOS, whose backend only reports
  releases for modifier-only chords (it now fires on press and waits for the
  modifiers);
- custom `styles`/`corrections` being dropped on any settings save (now in
  `EXTENSIBLE_PATHS`);
- backtrack treating the "." in "2.5" as a sentence end, matching "am" inside
  "amazing", and rewriting prose after a cue ("3 movies, actually one of
  them…"): a correction now needs the value to end the phrase or repeat the
  words it replaces;
- stutter removal merging "you, you're" and clause-spanning repeats;
- the default stop key (part of the record chord) breaking the double-tap
  lock;
- paste-last ignoring `suppress`/copy-only app rules;
- whisper mode boosting before the silence trims;
- hand-edited non-mapping sections crashing the Settings window;
- YAML `no` switching toggles on.
All pinned in `ReleaseReviewFixTests`.

Real hotkey feel (double-tap timing, paste-last) and the macOS Tk preload with
the menu-bar loop still need a hands-on test on Windows and macOS; the state
machine and wiring are unit-tested with fakes. Settings round trip and all
Tk windows verified with real Tk under Xvfb.

---

## Round 11 (0.20.0) — user-reported issues (2026-09)

Both open issues. Each came with a diagnosis and a patch on a fork. The root
causes were confirmed against our own code and the fixes written here. Neither
fork was merged.

- **ISS-14 (Critical, macOS app unusable)** Whoever calls `sharedApplication()`
  first decides NSApp's class. pyobjc did, so Tk 9's drawing code sent
  `TKApplication`-only selectors to a plain `NSApplication` and the process
  aborted (an `NSException`, invisible to Python). Tk now creates the app first
  via a hidden root kept alive in `platform/macos/app.py`. Added the mirrored
  `TK_MAIN_THREAD_ONLY` constant and `utils.tk_requires_main_thread()`: the
  overlay stands down on macOS, and the welcome window runs inline on the main
  thread with a `quit()`-then-`destroy()` teardown and shutdown-event polling.
  The teardown trap was reproduced with real Tk under Xvfb: with a second root
  alive on the thread, the 0.19.0 `destroy()`-only close hangs `mainloop()`, and
  the new one returns.
  **This amends the multi-Tk-root decision below.** "Each root on its own daemon
  thread" holds on Windows only. On macOS a Tk window must be created on the
  main thread. The fallback window, cheat sheet and add-word dialog now open
  in a child process there (`window_launcher.py`, hidden `--window NAME` flag,
  payload over stdin so a transcript never lands in argv), and the `--history`
  / `--cheat-sheet` CLI windows run on the main thread. All four were built
  with real Tk on the main thread under Xvfb.
- **ISS-15 (High, GPU dictation hangs)** `_test_ct2_gpu` only proved the NVIDIA
  driver answers, so onboarding enabled CUDA with no cuBLAS/cuDNN on disk. It now
  loads the five libraries ctranslate2 4.x pulls in on first inference, using
  `winmode=0` so the probe searches exactly as ctranslate2 does, PATH included.
  pip's `nvidia-*-cu12` DLL folders are registered at startup (`add_dll_directory`
  for Python-side loads, PATH for native `LoadLibrary`). A CUDA engine now fails
  fast into the existing GPU-recovery prompt instead of hanging. That prompt no
  longer waits for a key on windowless launches, and `--doctor` gained a CUDA
  libraries check. Not verifiable on real hardware from here, so the probe and
  path logic are covered with faked loaders.

212 tests pass (21 new).

---

## Round 10 (0.19.0) — user-reported issues (2026-09)

Five issues from users running 0.18.3. Every root cause was reproduced locally
before any fix; two turned out to be more interesting than the report suggested.

- **ISS-13 (Critical, app unusable)** macOS 27 made off-main-thread AppKit access
  a hard `SIGTRAP` instead of a logged warning, so the first hotkey press killed
  the process. Ten tray writes were reached from worker threads — the recording
  thread and a level monitor rewriting the title every 150 ms. `SIGTRAP` is not a
  Python exception, so the existing per-write `try`/`except` was decorative.
  Added `run_on_ui_thread()` to the platform layer (main-queue dispatch on macOS,
  passthrough on Windows) and routed every tray mutation through it; menus are
  still BUILT off-thread and only ASSIGNED on it. +3 tests, one of which scans
  the source for unguarded writes so a new one fails CI.
- **ISS-9 (High, silent data mangling)** `_strip_fillers` used `\s` in both its
  trailing run and its whitespace collapse, so enabling filler stripping deleted
  the line and paragraph breaks inline formatting had just inserted. Narrowed
  both to `[ \t]`. +3 tests, including one asserting output is identical with
  stripping on and off apart from the fillers.
- **ISS-10 (High, feature entirely broken)** `--history` and `--cheat-sheet`
  spawned their window on a daemon thread, slept 0.5 s and exited, killing it.
  The launchers now return the thread and the CLI joins it. Verified by
  subprocess: alive past 3 s where it previously died at 0.5 s.
- **ISS-12 (Med, privacy)** The clipboard-free setting was honoured on delivery
  but not on the two recovery paths. Fixed via a single
  `ClipboardManager.silent_copy_allowed` policy. Note the nuance: those copies
  were the reason a suppressed or undeliverable transcript was not lost, so the
  fix routes such cases to the recovery window instead of silently dropping the
  safety net. An explicit Copy button is always still allowed.
- **ISS-11 (Not a bug, real UX failure)** "Fails to transcribe in VS Code" was
  the shipped copy-only code-editor rule working correctly — @Syncriix diagnosed
  it from the log. But the app said nothing, so the only available conclusion was
  that it was broken. Now announced once per rule per session, with a pointer to
  `app_rules.yaml`; the settings label and config comment no longer imply the
  global toggle is the final word. Worth remembering: a correct behaviour nobody
  can discover is still a defect.

187 tests pass; `--doctor` green.

---

## Round 9 (0.18.1) — reported issues (2026-08)

All three open issues, each reported with a correct diagnosis. Every root cause
was reproduced locally before fixing rather than taken on trust.

- **ISS-6 (Critical, feature dead until restart)** The pause hotkey disabled every
  hotkey. `global-hotkeys` keeps registrations across `stop_checking_hotkeys()`,
  so the pause path's re-register raised "already registered" and the exception
  aborted before `start_checking_hotkeys()` — no live hotkeys, pause included.
  Reproduced against the bare library, then fixed by giving Windows `register()`
  the replace semantics the macOS mirror already had (`clear_hotkeys()` first),
  restoring the mirrored-API contract in docs/platform-abstraction.md.
  +2 tests, one of which was verified to fail without the fix.
- **ISS-3 (High, our own regression)** Tray Restart built its command from
  `sys.argv`; for a pip console script that path has no plain script file, so
  `python.exe` failed with "can't open file". Reproduced exactly. Root problem was
  duplication: autostart was fixed for ISS-2 and the tray was left behind, so both
  now share `utils.build_relaunch_command(windowless=...)`. +4 tests.
- **ISS-4 (Med, macOS)** Global NSEvent monitors cannot consume events, so a
  matched shortcut also typed its key. Adopted @chrysb's Quartz event-tap patch
  (applies cleanly; verified `pyobjc-framework-Quartz` is already a declared
  macOS dependency and already used by `platform/macos/keyboard.py`). The NSEvent
  monitor is retained as a fallback, so a machine without Accessibility permission
  degrades to current behaviour instead of losing hotkeys. **Not verified on real
  macOS hardware by us** — the contributor validated it on their machine.

**Process note:** two contributors report being unable to open PRs against this
repo. No interaction limits are set and forking is enabled — the cause is that
this repo is itself a fork, so GitHub defaults a PR's base to the root parent. Worth resolving; there is a finished Intel GPU
(OpenVINO) backend waiting on it in discussion #5.

---

## Round 8 (0.18.0) — merged improvements (2026-08)

Reviewed 16 outside commits since af0e8b1 and adopted what is genuinely better,
without surrendering anything already here.

**Adopted:**
- **UP-1 (Bug, real hardware)** `_classify_gpu` matched a single digit after
  "RX", so an **RX 580 — Polaris, not RDNA — was classified as RDNA1** and the
  app offered a runtime that cannot drive it. It also required a literal space,
  missing the "RX5700" form vendors emit, and had no pattern for Strix Halo /
  Ryzen AI MAX APUs (8040S/8050S/8060S), so GPU onboarding never fired on that
  hardware. Adopted a four-digit match. +8-case test.
- **UP-2 (Feature)** Startup "ready" chime (`audio_feedback.ready_enabled`) plus
  the `app_ready.wav` asset. A cold start is slow and the app has no window; an
  audible cue is the clearest "the hotkey is live now" signal.
- **UP-3 (Feature)** `terminal_title.py` — animated terminal tab title following
  idle/recording/processing, retitled to "Whisper Local". Self-disables when
  stdout is not a TTY, so a windowless launch pays nothing and no escape codes
  reach redirected logs. All eight `system_tray.update_state()` call sites in
  StateManager now route through one `_update_ui_state()` fan-out, so the tray
  and the tab title cannot drift apart.
- **UP-4 (Design, better than ours)** Vocabulary corrections
  (`postprocess.corrections`): one canonical term, many misheard variants. Two
  concrete advantages over our per-entry `postprocess.replacements`:
  (a) the ergonomic shape when Whisper mangles one term several ways, and
  (b) a single compiled alternation sorted longest-first — one pass regardless
  of vocabulary size, and it removes a real ordering ambiguity ours has, where
  with both `cap` and `cap x` defined the YAML order decided which won and a
  short variant could shadow a longer one, leaving a dangling "x".
  **Both are kept**: `replacements` retains whole_word/case_sensitive/regex and
  remains what the history window's "Fix this everywhere" writes; `corrections`
  runs first so a specific replacement can still override a broad mapping.

**Already present, no action:** push-to-talk for the command hotkey,
`strip_trailing_period`.

**Deliberately not taken:** a CLAUDE.md trim and the replacement of
`project-index.md` with a condensed map (this fork's docs are richer and are
enforced by `DocumentationStandardTests`), their plan-doc removal, and the 0.8.2
version bump.

**Verification:** 157 tests pass (11 new pinning the adopted behaviour); every
pre-existing feature of this fork re-checked by hand (voice editing, smart
formatting, absorb, replacements, offline model transfer, autostart repair,
history learning loop); `--doctor` green. Line endings were normalised to the
repo's convention after scripted edits so the diff shows only real changes.

---

## Round 7 (0.16.2) — first external bug report (2026-08)

- **BUG-2 (High, feature completely broken on the .exe)** — reported as
  [#2](https://github.com/drajb/whisper-local/issues/2) by @asherwin86: enabling
  "start on login" on Windows 11 opened a Python terminal at boot and the app
  never started. Root cause: `autostart._launch_command()` treated a truthy
  `$PYAPP` as "sys.executable IS the launcher", but pyapp unpacks a private
  CPython and runs the app with it — so `sys.executable` is the *interpreter*.
  The Run key therefore held a bare interpreter path with no script, which boots
  straight into an interactive Python prompt. Fixed to use the `$PYAPP` value
  itself (the real .exe path, exported because the build sets
  `PYAPP_PASS_LOCATION=1`) — the same convention `utils.restart_or_exit` and
  `console._set_icon` already followed, so `autostart` was the odd one out.
  +3 regression tests, including one asserting the command is not a bare
  interpreter.
- **BUG-2b (self-heal)** A code fix alone leaves every already-affected user with
  the bad registry value. `autostart.repair_if_broken()` now runs at startup and
  rewrites an entry that is a lone interpreter with no arguments. Narrow by
  design: entries with arguments, or pointing at the app executable, are never
  touched. +3 tests covering the healthy-entry and not-enabled cases.
- **BUG-2c (related)** For pip installs where `pythonw.exe` isn't beside the
  interpreter (some venv / Microsoft Store layouts), autostart silently used
  console `python.exe`, giving a terminal window at every boot. Now also checks
  `sys._base_executable` and warns when no windowless launcher exists.

Verified by unit tests, a proof that the old code produced a bare-interpreter
command where the new code produces the .exe, and a real enable→inspect→disable
round-trip against the Windows registry. Not reboot-tested (see issue reply).

---

## Round 6 (0.16.1) — performance, robustness & documentation sweep (2026-07-12)

Whole-repo pass driven by measurement rather than reading alone: static analysis
(pyflakes) over all 73 modules, an import check of every module, a functional
integration sweep through the *shipped* defaults, adversarial/pathological
inputs, and profiling of the post-processing pipeline.

**Fixed:**
- **R6-1 (High, user-visible hang)** Post-processing was **O(n²)** in two
  independent places, so a long transcript froze the app for seconds:
  `_apply_voice_editing`'s lazy leading scan (`[^.!?\n]*?…`) re-expanded from
  every start position, and the absorb pass re-scanned a long leading
  `[ \t,.]*` run from every position once earlier cues had turned the text
  mostly-punctuation. Measured on an 18k-char transcript: voice editing 6.61 s,
  absorb 6.46 s (11.9 s at 24k). Both rewritten as linear find-then-expand:
  **0.004 s and 0.009 s** respectively. Behaviour proven identical by a
  4,000-case randomised differential test against the old implementation;
  a performance regression test now guards the complexity.
- **R6-2 (Med, crash on bad config)** A scalar where a mapping/list belongs
  (`smart_formatting: true`, a stringy `ollama:` or `replacements:`) raised
  `AttributeError` mid-pipeline and lost the dictation. All three sections are
  now shape-checked and degrade to "feature off". +test.
- **R6-3 (Med, environment-dependent test)** `test_capture_without_soundcard_
  returns_none` only passed on machines *without* the optional loopback extra —
  it popped `soundcard` from `sys.modules`, which let a real install be
  re-imported. Now binds the name to `None` (making the import raise) and
  restores exactly, so the sentinel can't leak into later tests.
- **R6-4 (Low)** `mutex_handle` in `main()` looked like dead code to linters but
  holds the single-instance lock open; documented with an explicit warning and
  `# noqa` so nobody "cleans it up". Removed two redundant local `Path`
  re-imports shadowing the module-level import in `system_tray`.

**Documentation (CLAUDE.md compliance):**
- 46 of 73 modules had **no header comment**, against the project rule of a 2-4
  line header on every module — including `state_manager`'s neighbours,
  `config_manager`, `system_tray`, `text_postprocess`, and the entire platform
  layer. All 73 now have one; platform headers also name their opposite-OS
  mirror, making the mirrored-API contract self-evident.
- Intent comments added to the largest previously-bare functions
  (`_transcription_pipeline`, `_create_menu`, `_setup_hotkeys`,
  `transcribe_audio`, `transforms.apply`, `show_stats`, `_parse_pe_imports`,
  and the Tk window bodies).
- `DocumentationStandardTests` enforces the header rule in CI so it can't decay.

**Verified clean:** every module imports; 132 tests pass; no ReDoS or crash on
pathological inputs (20k-char, punctuation-only, Unicode/Polish, regex
metacharacters) — worst case now 0.033 s.

---

## Round 5 (0.16.0) — feature build + adversarial review (2026-07)

Shipped five features (post-transcription corrections + history "Fix this
everywhere" / hotword mining; deterministic smart formatting; voice editing;
experimental system-audio capture) and two first-run fixes (download size hint,
windowless silent-close dialog). Then ran three parallel adversarial reviewers;
every confirmed finding was hand-verified and fixed with a regression test.

**Fixed after review:**
- **R5-1 (Critical, test/CI hang)** `instance_manager._notify_no_console` called a
  *blocking* `MessageBoxW` whenever `GetConsoleWindow()==0`; a headless test/CI
  process has no console, so the modal hung forever (caught by a 4-min suite
  timeout). Split out `_console_attached()` so it's stubbable, and the test forces
  it True. Real windowless app still gets the dialog.
- **R5-2 (Correctness)** `text_postprocess._apply_replacements` used `\b…\b`, which
  silently dropped corrections whose `from` has a non-word edge (`C++`, `C#`,
  `.NET`, `@handle`). Switched to `(?<!\w)…(?!\w)` — still whole-word for normal
  terms. +test.
- **R5-3 (Bug)** `_TIME_RE` mangled digit-suffixed tokens like `pm2.5`; trailing
  guard tightened to `(?![A-Za-z0-9])`. +test.
- **R5-4 (Bug)** voice-editing's trailing `[\s,.]*` ate the newline after the
  command, pulling the next line up; narrowed to `[ \t,.]*` + strip trailing
  space before breaks. +test.
- **R5-5 (Correctness)** `system_audio.run_cli` ignored `backend: whisper_cpp`
  (would use faster-whisper and re-download); now mirrors selftest's branch.
- **R5-6 (Bug)** `--transcribe-system 0` was falsy and fell through to a full app
  launch (terminating a running instance); guard is now `is not None`.
- **R5-7 (UX)** history "saved ✓" confirmation was clobbered by a synchronous
  count-refresh in the same Tk callback; reordered. Correction dedup is now
  case-insensitive so "teh"/"Teh" don't create two rules.
- **R5-8 (Docs)** system-audio module/pyproject/config comments corrected:
  loopback is Windows-first (macOS needs a virtual device); emails/urls smart
  formatting documented as aggressive (fires on same-shaped prose), off by default.

**Verified CLEAN (no change needed):** `add_replacement` ruamel round-trip
(comments/sections preserved; update-in-place aliasing correct), WhisperEngine
constructor arg match, soundcard loopback API, `_model_size_hint` prefix matching,
`_notify_no_console` non-Windows safety, no ReDoS in the four new regexes, Unicode
`\b` behaviour, Tk threading in the new dialogs, `suggest_hotwords` sentence-initial
detection.

---

## Round 4 (0.15.0) — user-friendliness pass (2026-07)

UX review of the running product. Four code-level friction points, all fixed with
tests where testable.

- **UX-1 (settings apply latency)** Formatting/post-process edits required a full app
  restart to take effect, but the Save dialog implied changes were instant. `config_manager`
  now hot-reloads the `postprocess` section on file mtime change (`get_postprocess_config`
  re-reads + re-merges), so tweaks apply on the next dictation. Save dialog reworded to be
  honest about what is instant vs restart-gated. +test (`PostprocessHotReloadTests`).
- **UX-2 (silent failures)** A no-audio or no-speech dictation just hid the overlay; tray
  balloons are frequently suppressed by Windows focus-assist, so users saw nothing.
  `level_overlay.flash_failure(message)` now shows the reason ("No audio — mic muted?",
  "No speech detected") in the overlay for 2 s where the user is already looking.
- **UX-3 (discoverability)** Added Post-process-tab checkboxes for
  `inline_formatting_absorb_punctuation` and `inline_formatting_extend` (previously
  file-only), with a footnote pointing at `inline_formatting_replacements`.
- **UX-4 (tray + onboarding)** (a) Removed the duplicate "Open settings file..." tray item,
  folded six diagnostics into a "Help & diagnostics" submenu, and added a "Restart Whisper
  Local" item so hotkey/model/device changes can be applied without hunting the process.
  (b) First-launch console banner now interpolates the user's actual configured hotkeys
  instead of hardcoded Windows defaults (wrong on macOS / after customization).
  +test (`OnboardingBannerTests`).

---

## Round 3 (0.14.x) — security-focused sweep (2026-07)

Agent security sweep + hand-verified. Four confirmed, all fixed with tests.

- **SEC-1 (Med, data loss)** `settings_ui` "Reset to defaults" deleted `user_settings.yaml`,
  wiping `whisper.hotwords` despite the dialog promising the dictionary survives. Now
  preserves hotwords across the reset (`reset_settings_preserving_hotwords`). +test.
- **SEC-2 (Med, privacy)** `bundle_logs` masked the Ollama endpoint only in
  user_settings.yaml, but `doctor.txt` (same public-issue zip) printed it verbatim —
  reopening PRIV-1 for `user:pass@`/`?token=` endpoints. Added URL-credential + secret-
  query-param scrubbing to the general `_redact()` (covers doctor.txt AND logs). +test.
- **SEC-3 (Low)** `--serve` accepted a negative `Content-Length`, bypassing the SRV-2
  cap (`read(-1)` drains the socket). Now rejects `< 0`. +test. Loopback-only.
- **SEC-4 (Low)** `inline_formatting_absorb_punctuation` with the built-in English cue
  words glued words ("hello,world") and ate `new paragraph`/`new line` breaks. Fixed:
  built-in punctuation replacements bake a trailing space; absorb class excludes
  newlines (`[ \t,.]*`). +test.

Everything else re-verified CLEAN (subprocess/shell, full network inventory, YAML
loaders, streaming worker lifecycle, autostart writes, VC-1/SRV-1/PRIV-1/LOG-1/R2 fixes).

---

## Round 2 (0.11.x) — intensive word-by-word review

Six parallel reviewers swept the whole repo; every claimed bug was hand-verified in the
code before fixing (many agent "findings" were over-reported and dropped).

### Fixed (confirmed, with tests where applicable)
- **R2-1 (Med, race)** `audio_recorder.py` — pre-roll `deque` had no lock; `list(deque)`
  during a concurrent callback append could raise `RuntimeError: deque mutated during
  iteration`. Added `_buffer_lock` around append/trim and every snapshot+clear.
- **R2-2 (Med)** `voice_activity_detection.py` — realtime `process_chunk` fed a full chunk
  to TEN VAD, which asserts exactly 256 samples; off-by-a-few chunks from non-48 kHz mics
  silently killed the silence-timeout. Now slices/pads to 256 like the pre-check path.
- **R2-3 (Med)** `settings_ui._coerce` — coerced ALL numeric-looking strings to int/float,
  corrupting free-text settings (`initial_prompt`, hotkeys, ollama model/endpoint). Now
  type-aware (only known numeric paths). +test.
- **R2-4 (Med)** `update_check._is_newer` — `int("0-dev")` threw on source installs,
  permanently disabling update checks; now strips pre-release/build suffix + pads. +test.
- **R2-5 (Low)** `whisper_engine.py` — `old_model_key` could be unbound in the async-load
  error path (UnboundLocalError masking the real error); captured before any callback.
- **R2-6 (Low)** `level_overlay.py` — mode switches stacked multiple self-rescheduling
  `after()` animation loops; now cancels the prior loop first.
- **R2-7 (Low)** `autostart.py` — macOS plist now XML-escaped; `toggle()` returns achieved
  state, not intended.
- **R2-8 (Low)** `platform/windows/console.py` — `show()` did `SW_HIDE` then `SW_RESTORE`
  (copy-paste from `hide()`), causing a flicker; removed the stray hide.
- **R2-9 (Med, config)** `profiles.defaults.yaml` — `dictation`/`notes` pinned `model:tiny`,
  silently downgrading the new `base` default; now `base`. +test.
- **R2-10 (Low)** `utils.beautify_hotkey` no-op `.replace('+','+')` removed.
- **R2-11 (Low, consistency)** `main.py` / `hotkey_listener.py` `recording_mode` code
  fallback was still `toggle`; now `push_to_talk` to match the shipped default.
- **R2-12 (docs)** `faq.md` autostart answer rewritten to the built-in feature;
  `project-index.md` gained the missing module rows; six modules got header comments.

### Deferred (real but intentionally not changed this pass — risk > reward)
- **R2-D1** Transcription runs synchronously on the hotkey/release thread
  (`state_manager.stop_recording` → `_transcription_pipeline`). Moving it to a worker
  thread is a real architecture change (re-entrancy, the `is_processing` guard, cancel
  semantics) and the current design works; left as a deliberate design note.
- **R2-D2** Cross-thread Tk access + singleton spawn race in `history_window` /
  `cheat_sheet` / `dictionary` (caller thread calls `winfo_exists/lift/focus_force` on
  another thread's root; lock released before the root is assigned). Real but
  low-frequency; the correct fix (marshal via `root.after` + reserve sentinel under lock)
  touches working code in 3 files — scheduled, not done blind.
- **R2-D3** `platform/windows/gpu.py:_test_ct2_gpu` ignores its `ct2_variant` arg and
  hardcodes `device='cuda'`. Flagged as an AMD-demotion bug, but CTranslate2's ROCm build
  also uses the `'cuda'` device string, so this is likely correct — left unchanged pending
  confirmation on real AMD hardware rather than acting on an unverified claim.
- **R2-D4** `text_postprocess` filler-word stripping removes "like"/"you know"
  unconditionally (opt-in, off by default) — destructive but by-design; documented risk.

---

## How to read this

- **Severity** reflects real-world user/security impact for *this* app (a local, opt-in, privacy-first desktop tool), not raw CVSS. I deliberately down-rated several agent-flagged "critical" items that are only reachable by local processes or require unusual user configuration.
- **Verified** = I read the code and confirmed the issue first-hand. **Reported** = surfaced by a review agent, plausible, not yet hand-verified.
- Line numbers are as of the audit date; they drift as the file changes.

---

## Priority summary

| ID | Severity | Area | One-liner | Status |
|----|----------|------|-----------|--------|
| SRV-1 | High | local_server | `rstrip(b'-')` corrupts binary audio uploads | **FIXED** (2026-06-11) |
| SRV-2 | Medium | local_server | Unbounded `Content-Length` read → local OOM | **FIXED** (2026-06-11) |
| PRIV-1 | High | bundle_logs | Diagnostic zip doesn't redact hotwords / Ollama endpoint / prompts | **FIXED** (2026-06-11) |
| SPAWN-1 | High→None | startup | Windowless (`pythonw`) "double-spawn" | **NOT A BUG** (2026-06-11) |
| VC-1 | Medium | voice_commands | `${clipboard}` expanded before risky-command check; no shell-escaping | **FIXED** (2026-06-11) |
| UI-1 | Medium | history_window | Singleton `_instance` never reset on close | **FIXED** (2026-06-11) |
| LOG-1 | Medium | transcript_log / stats | Concurrent appends + rotation have no lock → rare corruption/loss | **FIXED** (2026-06-11) |
| CI-1 | Medium | CI | Tests run only on Ubuntu; Windows is the primary platform | **FIXED** (2026-06-11) |
| UI-2 | Low | dictionary | Add-word dialog leaks a daemon thread + Tk root per open | **FIXED** (2026-06-11) |
| UI-3 | Low | settings_ui | Search filter re-packs rows with hardcoded geometry | **FIXED** (2026-06-11) |
| REC-1 | Low | audio_recorder | `is_recording` read/written across threads without lock | **WONTFIX** (2026-06-11) |
| VAD-1 | Low | vad | One short-lived thread spawned per VAD event | **WONTFIX** (2026-06-11) |
| DOC-1 | Low | docs | `project-index.md` missing ~10 newer modules | **FIXED** (2026-06-11) |
| DOC-2 | Low | CITATION.cff | Version says 0.9.0, project is 0.10.0 | **FIXED** (2026-06-11) |
| DOC-3 | Low | README | "all 40 should pass" — actual count is 53 | **FIXED** (2026-06-11) |

### Resolution log (2026-06-11)

- **SRV-1** — `local_server._parse_multipart` now strips only the trailing CRLF, never `-`. Regression test `test_parse_multipart_preserves_trailing_dashes`.
- **SRV-2** — added `MAX_UPLOAD_BYTES` (500 MB); oversized `Content-Length` raises before reading. Test `test_oversized_content_length_rejected`.
- **PRIV-1** — `bundle_logs` adds `_redact_yaml` masking `hotwords`, `endpoint`, `initial_prompt` in `user_settings.yaml`; `about.txt` + console note updated. Tests `test_redact_yaml_*`.
- **VC-1** — `_expand_template(shell_safe=True)` `shlex.quote`s clipboard/selection for `run:`; `_execute_shell` now force-confirms any `run:` built from `${...}` content. Test `test_shell_safe_quotes_clipboard`. (Windows `cmd.exe` quoting is imperfect, hence the belt-and-braces forced confirm.)
- **UI-1 / UI-2** — `history_window` and `dictionary` add-word dialog now reset their singleton on close (`WM_DELETE_WINDOW` + `finally`), matching `cheat_sheet`.
- **UI-3** — `settings_ui` snapshots each row's real `pack_info()` at build and forgets-all-then-repacks-in-order on search, preserving geometry + order.
- **LOG-1** — `transcript_log` and `stats` wrap append (+rotate) in a module `threading.Lock`.
- **CI-1** — `test.yml` now runs on `[ubuntu, windows, macos]` via matrix.
- **DOC-1/2/3** — `project-index.md` refreshed with all current modules; `CITATION.cff` → 0.10.0 (now guarded by `test_citation_matches_pyproject`); README test line de-numbered.
- **SPAWN-1 — NOT A BUG.** A `WHISPER_DEBUG_SPAWN=1` startup probe proved `main()` runs **exactly once** under `pythonw`. The "two processes" are the venv `pythonw.exe` *launcher stub* (parent) plus the base interpreter it delegates to (child, which reports `sys.executable` as the venv path via `__PYVENV_LAUNCHER__`) — normal Windows venv-launcher behaviour, one logical instance, one lock, no hotkey conflict. The `.cmd` launcher shows one process because it invokes the base `python` directly. Note: this machine's `.venv/pyvenv.cfg` still points at the pre-rename `whisper-key-local` path — harmless but worth recreating the venv for cleanliness. The probe is retained (env-gated) as a debugging aid.
- **REC-1 / VAD-1 — WONTFIX (by design).** REC-1: `is_recording` is read once per audio callback; a ±1-chunk staleness at a start/stop edge is exactly what the 500 ms pre-roll buffer absorbs — adding a lock to a callback firing every ~10 ms is net-negative for a theoretical race. VAD-1: the VAD state machine fires `SILENCE_TIMEOUT` at most **once** per recording (then idles in `TIMEOUT_TRIGGERED`), so it spawns one detached thread per session, not per event — and that thread is intentional (must not block the audio callback). Both left as-is deliberately.

---

## High severity

### SRV-1 — Multipart parser corrupts binary audio `local_server.py:247`
**Verified.** `body = body.rstrip(b'\r\n').rstrip(b'-')` strips *any* trailing `0x2D` ("-") bytes from every field body, including the binary `file` part. Audio whose final bytes are `0x2D` get silently truncated, so the OpenAI-compatible `--serve` endpoint can mis-transcribe or fail on otherwise valid uploads. The `rstrip(b'-')` was presumably meant to handle the closing `--` boundary, but `raw.split(sep)` already separates parts — the trailing-boundary dashes live in their own trailing chunk, not in a field body.
**Fix:** drop `.rstrip(b'-')`; keep only `.rstrip(b'\r\n')`. Add a regression test that round-trips a WAV ending in `0x2D` through `_parse_multipart` + `_decode_audio`.

### PRIV-1 — Diagnostic bundle leaks config secrets `bundle_logs.py:_redact / ~line 71`
**Verified.** `_redact()` only masks usernames in paths and email addresses. The bundle includes `user_settings.yaml` verbatim otherwise, which can contain: `whisper.hotwords` (people put names, codewords, sometimes secrets here), `postprocess.ollama.endpoint` (may embed `user:pass@host` or `?token=`), custom model paths, and `initial_prompt`. Bundles are explicitly meant to be attached to public GitHub issues, so this is a real privacy-first-tool regression.
**Fix:** add redaction rules for `hotwords:`, `endpoint:`, `initial_prompt:` (and consider an allowlist approach — only bundle known-safe keys). Mention in the bundle's `about.txt` exactly which fields were scrubbed.

### SPAWN-1 — Windowless launch double-spawns a second instance (startup)
**Verified during this session.** Launching via `pythonw.exe whisper-local.py` *or* `pythonw.exe -m whisper_key.main` reliably produces two processes: the launched one (parent) spawns a child running the same entrypoint under the **system** Python (`...\Programs\Python\Python312\pythonw.exe`), and the child takes the lock. The canonical `whisper-local.cmd` (console, system python) does **not** reproduce it — exactly one instance. Root cause **not yet identified**: it is not the `.py` file association (reproduces with `-m`), not `instance_manager` (it only SIGTERMs + locks, never spawns), and not `multiprocessing` (that would use the venv `sys.executable`, but the child is system python). Something resolves an interpreter via PATH/registry and re-execs only under the no-console condition.
**Impact:** two instances briefly (or persistently) contend for global hotkeys → "hotkey already registered" + double-trigger. Only affects windowless autostart; the shipped `.cmd` launcher is safe.
**Next step:** instrument startup — log `sys.executable`, `sys.argv`, `os.getpid()`, parent pid at the very top of `main()`; reproduce under `pythonw`; bisect by disabling subsystems (tray, sherpa-onnx streaming, ten-vad, playsound3) to find which import/init re-execs. Suspect a dependency calling `freeze_support()`/relaunch or a console-acquisition shim.

---

## Medium severity

### SRV-2 — Unbounded request body read `local_server.py:222-223`
**Verified.** `length = int(headers['Content-Length']); raw = rfile.read(length)` with no cap. A local process (the server binds loopback only, so not remote) can send a huge `Content-Length` and exhaust memory. Lower severity than a public service, but `--serve` is meant to sit running in the background.
**Fix:** reject `length > MAX_UPLOAD` (e.g. 500 MB) with HTTP 413 before reading.

### VC-1 — Voice-command clipboard expansion precedes safety check `voice_commands.py` (reported, ~line 160 vs 232)
**Reported, not hand-verified.** `${clipboard}` / `${selection}` templates appear to be expanded into the `run:` string before the risky-pattern regex runs, and substitution is raw (no shell-escaping). A user with a `run:` command containing `${clipboard}` who pastes shell metacharacters could slip past the confirm dialog if the regex doesn't match the injected payload. Requires user-authored `run:` command + `shell=True`.
**Fix:** `shlex.quote()` clipboard/selection before substitution; run the risky-pattern check on the final expanded string; consider defaulting `run:` commands to confirm-always.
**Verify first:** confirm the actual expansion/check ordering in the current file before acting.

### UI-1 — History window singleton never cleared `history_window.py:~155`
**Verified.** `_instance` is set on open but there's no `WM_DELETE_WINDOW` handler resetting it to `None` (cheat_sheet.py does this correctly — copy that pattern). After close+reopen, the guard calls `winfo_exists()` on a destroyed root.
**Fix:** add `root.protocol("WM_DELETE_WINDOW", lambda: (_clear_ref(), root.destroy()))` mirroring `cheat_sheet.py`.

### LOG-1 — Transcript/stats writes + rotation unsynchronized `transcript_log.py:~38,73 / stats.py:~49`
**Verified (no lock present).** Append writes and the read-truncate-rewrite rotation share no lock. Back-to-back deliveries (continuous mode, rapid commands) can interleave a line (load silently skips malformed JSON → data loss) or lose entries appended during a rotation window. Low frequency in practice.
**Fix:** module-level `threading.Lock` around both append and rotate.

### CI-1 — No Windows/macOS CI `.github/workflows/test.yml`
**Verified.** `runs-on: ubuntu-latest` only. Windows is the primary platform; platform-specific code (hotkeys, WASAPI host matching, clipboard, permissions) is never exercised in CI.
**Fix:** matrix `[ubuntu-latest, windows-latest, macos-latest]`. The smoke suite already imports cleanly without the heavy ML stack on Linux; verify the same on Windows (it should, given local runs pass).

---

## Low severity

### UI-2 — Add-word dialog thread/root leak `dictionary.py:~182` (reported)
Each `show_add_word_dialog()` spawns a fresh daemon thread + Tk root with no singleton; repeated opens accumulate. Apply the cheat_sheet singleton pattern or ensure clean mainloop exit.

### UI-3 — Settings search re-packs with hardcoded geometry `settings_ui.py:~185-215` (verified)
On filter-show, rows are re-`pack()`ed with literal `padx/pady` instead of their saved `pack_info()`. Works today because all rows share the same geometry; will silently misplace rows if any row's packing ever differs. Cache `pack_info()` before `pack_forget()`.

### REC-1 — `is_recording` cross-thread without lock `audio_recorder.py` (verified)
Read in the audio callback thread, written from main/VAD threads. In CPython a bool assignment is atomic so this is mostly benign today, but the flag gates buffering/VAD and could mis-sequence on a stop/start boundary. Consider a lock or `threading.Event`. Low priority.

### VAD-1 — Thread per VAD event `voice_activity_detection.py:~228` (reported)
A new daemon thread is spawned for each dispatched event. Under rapid state flips this is wasteful; prefer a single dispatcher thread + queue. Verify the actual dispatch code before changing.

### DOC-1 — `project-index.md` stale (verified)
Missing entries for: `selftest`, `local_server`, `bundle_logs`, `cheat_sheet`, `first_run`, `settings_ui`, `history_window`, `transcript_log`, `update_check`, `noise_suppression`, `setup_wizard`, `streaming_manager`, `terminal_ui`. CLAUDE.md @-includes this file, so keeping it current directly improves future automated work.

### DOC-2 — CITATION.cff version drift (verified)
`version: 0.9.0` → should be `0.10.0`. Consider a release checklist (or a `bump` step) that updates pyproject, CITATION.cff, and CHANGELOG together.

### DOC-3 — README test count (verified)
README says "all 40 should pass"; the suite is now **53**. Either drop the number or wire it to reality.

---

## Audited and found CLEAN

Recorded so future audits don't re-tread:

- **State machine** (`state_manager`): `can_start_recording`/`get_current_state` correctly locked; `_transcription_pipeline` resets `is_processing` in `finally`; early-return paths hide/flash the overlay.
- **Hotkey listener**: `keys_armed` correctly prevents double-trigger; PTT vs toggle paths sound.
- **Audio trimming/resampling/preroll**: long-pause + trailing-silence algorithms correct; preroll deque trimmed when idle (no unbounded growth); WASAPI resample-on-stop logic correct.
- **USB disconnect recovery**: retry loop + default-device fallback correct.
- **Whisper engines** (faster-whisper + cpp): kwargs built correctly; model-load errors logged and re-raised.
- **update_check**: opt-in, disabled by default, sends only a version string in the UA header, once/day rate-limited. Privacy claim holds.
- **Privacy pledge overall**: the only network touchpoints are HuggingFace model download (first run), opt-in GPU install, opt-in update check, and user-local Ollama (`localhost`). No undisclosed calls. **Verified by grep across `src/`.**
- **level_overlay**: correct cross-thread pattern (`_call` → `root.after`).
- **system_tray**: launches settings/history/cheat-sheet/doctor as subprocesses — the safest way to avoid multi-Tk-root conflicts.
- **Packaging**: `package-data` includes all five `*.defaults.yaml`, assets, platform assets, and the bundled `portaudio.dll`. Entry points (`whisper-local`, `wl`) correct.
- **README feature/flag claims**: all 21 CLI flags exist; every feature bullet maps to real code; hotkey table matches `config.defaults.yaml`.
- **Utility modules** found clean: `selftest`, `transforms`, `noise_suppression`, `text_postprocess`, `app_rules`, `profiles`, `settings_io`, `vocab_import`, `audit_log`, `doctor`.

---

## Cross-cutting recommendation: the multi-Tk-root architecture

The app can have several `Tk()` roots alive at once, each with its own `mainloop` on its own daemon thread (overlay always-on + any of: first-run, fallback, cheat-sheet, dictionary, history). Tkinter tolerates this *only* as long as the roots never touch each other and each stays on its creating thread. It works today but is fragile. The tray already dodges this by launching the big windows (`--settings`, `--history`) as **subprocesses** — that's the robust pattern.

### Researched & decided (2026-06-11)

Mapped every `tk.Tk()` site and how each is launched. Findings:

- Tray-launched windows (`--settings`, `--history`, `--doctor`, `--stats`, `--selftest`) already run as **separate subprocesses** — no shared-root risk.
- The genuinely in-process roots are the **always-on level overlay** plus transient
  ones (`fallback`, `cheat_sheet`, `dictionary`, `first_run`). `cheat_sheet`,
  `dictionary`, and `history` already have **singleton guards**.
- The only realistic coexistence is **overlay + fallback window**. Each lives entirely
  on its own daemon thread with its own Tcl interpreter and never touches the other's
  widgets, which is why it has shipped without incident. The remaining real defect was
  that `fallback` could **stack multiple windows/roots** on repeated failed deliveries.

**Decision:** the big-bang "single global Tk root + Toplevels with cross-thread event
marshalling" refactor was considered and **deferred** — it's invasive, touches every
window + the audio/VAD threads, and can't be validated without a live desktop Tk
session. Risk ≫ reward for a hazard that hasn't manifested.

**Done instead:** added a singleton guard to `fallback_window` (only one alive at a
time; the transcript is already on the clipboard before `show()`, so skipping a
duplicate loses nothing). This removes the one concrete defect (stacking) and caps
in-process roots at "overlay + at most one transient", which is the safe, proven
configuration. The single-root refactor remains a documented future option if the
window set grows.

---

## Status (2026-06-11)

All 15 findings are resolved — 11 fixed with regression tests, 1 reclassified
NOT-A-BUG (SPAWN-1), 2 deliberate WONTFIX (REC-1, VAD-1), and the rest doc/CI.
See the **Resolution log** above for per-item detail. Smoke suite: 59 tests, green.

Nothing in this audit is outstanding. The architectural note below (multi-Tk-root)
and the product ideas remain as future, non-blocking improvements.

## Product ideas (not bugs) — see also README "Why this exists"

- Single-`.exe` distribution (PyInstaller/pyapp is scaffolded) + `winget` / Homebrew manifests — biggest reach unlock.
- Demo GIF in the README (highest single discoverability win; the recorder script exists in `tools/`).
- Streaming: the live **overlay preview** is now a documented feature (`docs/streaming.md`, opt-in via `streaming.streaming_enabled`). True type-as-you-go to the cursor was researched and intentionally NOT shipped as default — pasting unstable partial tokens corrupts documents. The safe form (commit only finalized/post-endpoint segments, trading Whisper accuracy for latency) is a future opt-in; `streaming_recognizer.is_endpoint()` already exists for it.
- Windowless autostart is viable (SPAWN-1 was a non-bug); a future installer could create a `pythonw` shortcut for a console-free launch. Recreate the venv first so `pyvenv.cfg` reflects the current path.
