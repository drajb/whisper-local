# ui/pages/settings.py
# Every setting, grouped and searchable, each saved the moment it changes (no
# Save button). The table below declares each row: its setting path, label,
# help text and control. Changes to formatting apply on the next dictation;
# changes the running engine only reads at start (hotkeys, model, audio) raise
# a "restart to apply" banner with a one-click restart.

import logging
import os
import sys
import threading
import time
import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Field, Select, Segmented, Toggle

logger = logging.getLogger(__name__)

LANGUAGES = [('auto', 'Detect automatically')] + [(c, c) for c in (
    'en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl', 'ru', 'uk', 'tr', 'ar', 'hi', 'ja', 'zh', 'ko',
    'sv', 'da', 'no', 'fi', 'cs', 'el', 'he', 'id', 'vi', 'th')]

MOUSE_OFF = ''

# Rows: (path, label, help, control, options). Controls: toggle, select,
# segmented, text, mono (a hotkey), number, numberblank (blank = null),
# list (comma-separated codes), autostart (special), models (special).
SECTIONS = (
    ('General', (
        ('ui.theme', 'Appearance', 'Follow your system setting, or choose light or dark.', 'segmented',
         [('system', 'System'), ('light', 'Light'), ('dark', 'Dark')]),
        ('_autostart', 'Start on login', 'Open Whisper Local in the background when you sign in.', 'autostart', None),
        ('clipboard.auto_paste', 'Paste at the cursor', 'Off copies to the clipboard only. Per-app rules can override this.', 'toggle', None),
        ('audio.continuous_mode', 'Continuous dictation', 'Starts listening again after each dictation, for long notes.', 'toggle', None),
        ('history.retention_days', 'Keep history for (days)', 'Blank keeps the newest 2,000 dictations; 0 keeps none.', 'numberblank', None),
        ('stats.typing_wpm', 'Your typing speed (wpm)', 'Used to estimate the time dictation saves you.', 'number', None),
    )),
    ('Dictation', (
        ('whisper.model', 'Model', 'Larger models are more accurate but slower. "turbo" is a good balance on a GPU.', 'models', None),
        ('whisper.language', 'Language', 'Pick one, or let Whisper detect it each time.', 'select', LANGUAGES),
        ('whisper.languages', 'Languages you speak', 'Codes such as "en, fr". Detection then picks only from these.', 'list', None),
        ('hotkey.recording_mode', 'Recording mode', 'Hold the hotkey while you talk, or press once to start and again to stop.', 'segmented',
         [('push_to_talk', 'Hold to talk'), ('toggle', 'Press to toggle')]),
        ('hotkey.double_tap_to_lock', 'Hands-free double-tap', 'Double-tap the hotkey to keep recording without holding it.', 'toggle', None),
        ('whisper.task', 'Output language', 'Translate turns speech in any language into English text.', 'segmented',
         [('transcribe', 'As spoken'), ('translate', 'English')]),
    )),
    ('Hotkeys', (
        ('hotkey.recording_hotkey', 'Record', 'Lowercase keys joined by +, e.g. ctrl+win or ctrl+shift+space.', 'mono', None),
        ('hotkey.stop_key', 'Stop and paste', None, 'mono', None),
        ('hotkey.auto_send_key', 'Stop, paste and press Enter', 'For chat apps.', 'mono', None),
        ('hotkey.cancel_combination', 'Cancel recording', None, 'mono', None),
        ('hotkey.paste_last_hotkey', 'Paste last dictation', None, 'mono', None),
        ('hotkey.command_hotkey', 'Voice commands', 'Say a phrase from commands.yaml to run it.', 'mono', None),
        ('hotkey.rephrase_hotkey', 'AI rephrase', 'Select text, hold, say how to change it. Needs Ollama.', 'mono', None),
        ('hotkey.pause_hotkey', 'Pause all hotkeys', None, 'mono', None),
        ('hotkey.mouse_button', 'Mouse button', 'Hold a mouse button to dictate. x1/x2 are the side buttons. Windows only.', 'select',
         [(MOUSE_OFF, 'Off'), ('middle', 'Middle button'), ('x1', 'Side button (back)'),
          ('x2', 'Side button (forward)'), ('both', 'Either side button')]),
    )),
    ('Audio', (
        ('audio_feedback.enabled', 'Sounds', 'A soft cue when recording starts and stops.', 'toggle', None),
        ('vad.vad_realtime_enabled', 'Stop on silence', 'Ends a recording after a long silence.', 'toggle', None),
        ('vad.vad_silence_timeout_seconds', 'Silence timeout (seconds)', None, 'number', None),
        ('audio.max_duration', 'Longest recording (seconds)', None, 'number', None),
        ('audio.pause_media_on_record', 'Pause music while recording', 'Pauses the media player when you start talking.', 'toggle', None),
        ('audio.whisper_mode.enabled', 'Whisper mode', 'Boosts quiet speech, for dictating in an open office.', 'toggle', None),
        ('audio.noise_suppression.enabled', 'Noise suppression', 'Cleans up background noise. Needs: pip install noisereduce.', 'toggle', None),
        ('notifications.silent_microphone', 'Silent-mic notification', 'The overlay always warns. Auto notifies only when the overlay is off.', 'segmented',
         [('auto', 'Auto'), (True, 'Always'), (False, 'Never')]),
    )),
    ('AI polish', (
        ('postprocess.ollama.enabled', 'Polish with a local AI', 'Runs each dictation through Ollama on this computer for punctuation and flow.', 'toggle', None),
        ('postprocess.ollama.model', 'Ollama model', 'Any model you have pulled, e.g. llama3.2.', 'text', None),
        ('postprocess.ollama.endpoint', 'Ollama address', None, 'text', None),
        ('postprocess.ollama.timeout', 'Timeout (seconds)', 'Falls back to the plain transcript if Ollama is slower.', 'number', None),
    )),
    ('Advanced', (
        ('whisper.device', 'Compute device', 'cuda uses an NVIDIA or AMD GPU.', 'segmented', [('cpu', 'CPU'), ('cuda', 'GPU')]),
        ('whisper.compute_type', 'Precision', 'int8 is fastest on CPU; float16 suits GPUs.', 'segmented',
         [('int8', 'int8'), ('float16', 'float16'), ('float32', 'float32')]),
        ('whisper.beam_size', 'Beam size', '1 to 10. Higher is a little more accurate and slower.', 'number', None),
        ('whisper.initial_prompt', 'Context prompt', 'Words or a sentence that prime Whisper with your topic.', 'text', None),
        ('whisper.prompt_from_selection', 'Use selected text as context', 'Reads your selection when recording starts, to spell names right.', 'toggle', None),
        ('postprocess.inline_formatting', 'Spoken punctuation', 'Say "comma", "new paragraph" and so on.', 'toggle', None),
        ('postprocess.list_formatting', 'Spoken lists', '"first ... second ..." becomes a numbered list.', 'toggle', None),
    )),
)

# Settings the dictation engine reads continuously; everything else it only
# reads when it starts.
LIVE_PREFIXES = ('postprocess.', 'ui.')

NUMERIC = ('number', 'numberblank')


def needs_restart(path: str) -> bool:
    return not path.startswith(LIVE_PREFIXES) and not path.startswith('_')


# The raw value from a control, as the config wants it.
def coerce(path: str, control: str, raw):
    if control in ('toggle', 'autostart'):
        return bool(raw)
    if control == 'list':
        from ...dictation_languages import normalize_languages
        return normalize_languages(raw)
    if control == 'numberblank':
        text = str(raw).strip()
        if text == '':
            return None
        control = 'number'
    if control == 'number':
        text = str(raw).strip()
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                raise ValueError('Enter a number')
    if control == 'mono':
        return str(raw).strip().lower().replace(' ', '')
    return raw


def get_value(config: dict, path: str, default=None):
    node = config
    for key in path.split('.'):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return default if node is None else node


# Closes the running app and starts it again (the hub stays open). Waits for
# the old process to exit so the single-instance lock is free.
def restart_app():
    import subprocess
    from ...main import _send_quit_to_running_instance
    from ...utils import build_relaunch_command, get_user_app_data_path
    from ..hub import _pid_alive
    from pathlib import Path
    pid_file = Path(get_user_app_data_path()) / 'WhisperKeyLocal.pid'
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    _send_quit_to_running_instance()
    deadline = time.time() + 10
    while pid and _pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0) if sys.platform == 'win32' else 0
    subprocess.Popen(build_relaunch_command(), creationflags=flags,
                     start_new_session=(sys.platform != 'win32'))


class Page(BasePage):
    title = 'Settings'
    subtitle = 'Changes save as you make them.'

    def build(self, body):
        kit, p = self.kit, self.p
        self.query = tk.StringVar(master=self.hub.root)
        self.banner = tk.Frame(body, bg=p['bg'])
        self.banner.pack(fill='x')
        Field(body, kit, self.query, placeholder='Search settings', icon='search').pack(fill='x', pady=(0, kit.px(6)))
        self.sections = tk.Frame(body, bg=p['bg'])
        self.sections.pack(fill='x')
        self._pending_query = None
        self.query.trace_add('write', lambda *_: self._schedule_render())
        self._render()
        if getattr(self.hub, 'restart_pending', False):
            self._show_restart_banner()

    def _schedule_render(self):
        if self._pending_query:
            self.hub.root.after_cancel(self._pending_query)
        self._pending_query = self.hub.root.after(200, self._render)

    def _render(self):
        kit, p = self.kit, self.p
        self._pending_query = None
        for child in self.sections.winfo_children():
            child.destroy()
        q = self.query.get().strip().lower()
        config = self.hub.cm.config
        shown = 0
        for title, rows in SECTIONS:
            matches = [r for r in rows if not q or q in ' '.join(
                str(x) for x in (r[0], r[1], r[2] or '', title)).lower()]
            if not matches:
                continue
            section = self.section(self.sections, title)
            for i, (path, label, help_text, control, options) in enumerate(matches):
                self.row(section, label, help_text,
                         lambda parent, a=(path, control, options): self._control(parent, config, *a),
                         first=(i == 0))
                shown += 1
        if not q:
            self._data_section()
        elif not shown:
            self.empty_state(self.sections, 'search', 'No settings match',
                             'Try another word. Everything else lives in user_settings.yaml '
                             '(Your data → Open settings file).')

    # Builds the control for one row and wires it to save on change.
    def _control(self, parent, config, path, control, options):
        kit, p = self.kit, self.p
        bg = p['surface']
        root = self.hub.root
        if control == 'autostart':
            from ... import autostart
            if not autostart.is_supported():
                return kit.label(parent, 'Not available here', 'small', 'text_faint', bg=bg)
            var = tk.BooleanVar(master=root, value=autostart.is_enabled())
            return Toggle(parent, kit, var, command=self._set_autostart, bg=bg)
        value = get_value(config, path, '')
        if control == 'toggle':
            var = tk.BooleanVar(master=root, value=bool(value))
            return Toggle(parent, kit, var, command=lambda v: self._save(path, control, v), bg=bg)
        if control == 'segmented':
            current = value
            if path == 'notifications.silent_microphone':
                current = {True: True, False: False}.get(value, 'auto') if isinstance(value, bool) else str(value).lower()
                if current in ('true', 'false'):
                    current = current == 'true'
            var = tk.StringVar(master=root, value=str(current))
            lookup = {str(v): v for v, _ in options}
            return Segmented(parent, kit, var, [(str(v), lbl) for v, lbl in options],
                             command=lambda v: self._save(path, control, lookup.get(v, v)), bg=bg)
        if control in ('select', 'models'):
            if control == 'models':
                models = list(((config.get('whisper') or {}).get('models') or {}).keys())
                options = [(m, m) for m in models]
            var = tk.StringVar(master=root, value=str(value if value is not None else ''))
            return Select(parent, kit, var, options, command=lambda v: self._save(path, control, v),
                          width=220, bg=bg)
        # Text-like controls save when you leave the field or press Enter.
        if control == 'list':
            from ...dictation_languages import normalize_languages
            value = ', '.join(normalize_languages(value))
        var = tk.StringVar(master=root, value='' if value is None else str(value))
        field = Field(parent, kit, var, width=220 if control != 'text' else 260,
                      mono=(control == 'mono'), bg=bg,
                      on_submit=lambda: self._save(path, control, var.get()))
        field.entry.bind('<FocusOut>', lambda e: self._save(path, control, var.get(), quiet_if_same=True), add='+')
        return field

    def _save(self, path, control, raw, quiet_if_same=False):
        try:
            value = coerce(path, control, raw)
        except ValueError as e:
            self.hub.toast(str(e), 'danger')
            return
        if quiet_if_same and get_value(self.hub.cm.config, path, None) == value:
            return
        if not self.hub.save(path, value):
            return
        if path == 'ui.theme':
            from .. import theme
            theme.set_active(value)
            self.hub.rebuild()
            return
        if needs_restart(path):
            self.hub.restart_pending = True
            self._show_restart_banner()
            self.hub.toast('Saved')
        else:
            self.hub.toast('Saved: applies to your next dictation', 'success')

    def _set_autostart(self, on):
        from ... import autostart
        ok = autostart.enable() if on else (autostart.disable() or True)
        self.hub.toast(('Will start on login' if on else "Won't start on login") if ok
                       else "Couldn't change the login item", 'success' if ok else 'danger')

    def _show_restart_banner(self):
        kit, p = self.kit, self.p
        for child in self.banner.winfo_children():
            child.destroy()
        from ..kit import Card
        card = Card(self.banner, kit, padding=14, fill=p['accent_soft'], outline=False)
        card.pack(fill='x', pady=(0, kit.px(14)))
        b = card.body
        Button(b, kit, 'Restart now', self._restart, variant='primary', icon='restart',
               bg=p['accent_soft']).pack(side='right')
        tk.Label(b, image=kit.icon('info', 18, p['accent']), bg=p['accent_soft']).pack(side='left')
        kit.label(b, 'Some changes take effect when Whisper Local restarts.', 'body_strong',
                  bg=p['accent_soft']).pack(side='left', padx=(kit.px(8), 0))

    def _restart(self):
        self.hub.toast('Restarting Whisper Local…')

        def work():
            try:
                restart_app()
            except Exception as e:
                logger.warning(f"Restart failed: {e}")
        threading.Thread(target=work, daemon=True, name='restart-app').start()
        self.hub.restart_pending = False
        for child in self.banner.winfo_children():
            child.destroy()

    # ── Your data ────────────────────────────────────────────────────────

    def _data_section(self):
        kit, p = self.kit, self.p
        bg = p['surface']
        section = self.section(self.sections, 'Your data',
                               'Everything stays in your settings folder on this computer.')
        self.row(section, 'Settings file', 'Every option, including ones not shown here.',
                 lambda parent: Button(parent, kit, 'Open', self._open_settings_file, icon='external', bg=bg),
                 first=True)
        self.row(section, 'Settings folder', 'History, notes, stats and your rules files.',
                 lambda parent: Button(parent, kit, 'Open', self._open_folder, icon='folder', bg=bg))
        self.row(section, 'Back up', 'Save your settings, commands and rules to a folder.',
                 lambda parent: Button(parent, kit, 'Back up…', self._backup, icon='download', bg=bg))
        self.row(section, 'Restore', 'Bring back settings from a backup folder.',
                 lambda parent: Button(parent, kit, 'Restore…', self._restore, icon='upload', bg=bg))
        self.row(section, 'Reset settings', 'Back to defaults. Your dictionary, history and notes are kept.',
                 lambda parent: Button(parent, kit, 'Reset…', self._reset, variant='danger', bg=bg))

    def _open_settings_file(self):
        from ...utils import open_file
        open_file(self.hub.cm.user_settings_path)

    def _open_folder(self):
        from ...utils import open_file, get_user_app_data_path
        open_file(get_user_app_data_path())

    def _backup(self):
        from tkinter import filedialog
        from ...settings_io import export_settings
        target = filedialog.askdirectory(parent=self.hub.root, title='Choose a folder for the backup')
        if target:
            ok = export_settings(target) == 0
            self.hub.toast('Backed up' if ok else 'Backup failed', 'success' if ok else 'danger')

    def _restore(self):
        from tkinter import filedialog
        from ...settings_io import import_settings
        source = filedialog.askdirectory(parent=self.hub.root, title='Choose a backup folder')
        if not source:
            return
        if not self.kit.confirm(self.hub.root, 'Restore settings?',
                                'Your current settings will be replaced by the backup.',
                                confirm_text='Restore', danger=True):
            return
        ok = import_settings(source) == 0
        self.hub.reload_config()
        self.hub.restart_pending = ok
        self._render()
        if ok:
            self._show_restart_banner()
        self.hub.toast('Restored' if ok else 'Restore failed', 'success' if ok else 'danger')

    def _reset(self):
        if not self.kit.confirm(self.hub.root, 'Reset all settings?',
                                'Every setting goes back to its default. Your dictionary words, '
                                'history and notes are kept.', confirm_text='Reset', danger=True):
            return
        from ...utils import get_user_app_data_path
        reset_settings_preserving_hotwords(os.path.join(get_user_app_data_path(), 'user_settings.yaml'))
        self.hub.reload_config()
        self.hub.restart_pending = True
        self._render()
        self._show_restart_banner()
        self.hub.toast('Settings reset')


# Reset user settings to defaults while PRESERVING whisper.hotwords, which live
# inside user_settings.yaml. The reset promises the dictionary survives, so the
# file can't simply be deleted. Module-level so it's testable.
def reset_settings_preserving_hotwords(settings_path) -> list:
    from ruamel.yaml import YAML
    preserved = []
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding='utf-8') as f:
                existing = YAML().load(f) or {}
            preserved = list((existing.get('whisper') or {}).get('hotwords') or [])
        except Exception:
            preserved = []
        os.remove(settings_path)
    if preserved:
        with open(settings_path, 'w', encoding='utf-8') as f:
            YAML().dump({'whisper': {'hotwords': preserved}}, f)
    return preserved
