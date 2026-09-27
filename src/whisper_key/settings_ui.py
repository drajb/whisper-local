# settings_ui.py
# GUI settings editor — launched by `whisper-local --settings` or the tray
# "Settings..." item. Tkinter-only, no extra deps. Reads/writes user_settings.yaml
# via ConfigManager, preserving comments and overrides-only semantics.
#
# Layout:
#   • Top: search box (Ctrl+F to focus) that hides/shows rows across all tabs
#   • Middle: Notebook with 4 tabs — General, Audio, Hotkeys, Post-process
#   • Bottom-left: Backup… / Restore… / Reset-to-defaults
#   • Bottom-right: Save / Cancel
#
# Each setting row is its own packed Frame so the search filter can pack_forget/pack
# it without disturbing the rest. row_index[path] = {widgets, label, tab_index}
# is the structure that powers search.

import logging

# Imported lazily up here so module-level helper functions can use it. Falls
# back to None on systems without Tkinter — the run_settings_window() entry
# point checks again before touching anything.
try:
    from tkinter import ttk
except ImportError:
    ttk = None

logger = logging.getLogger(__name__)


# Reset user settings to defaults while PRESERVING whisper.hotwords, which live
# inside user_settings.yaml. The reset dialog promises the dictionary survives, so
# we can't just delete the file. Module-level (not a Tk closure) so it's testable.
def reset_settings_preserving_hotwords(settings_path) -> list:
    from ruamel.yaml import YAML
    import os
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

BG = '#0d1117'
BG2 = '#161b22'
BG3 = '#21262d'
FG = '#c9d1d9'
FG_DIM = '#8b949e'
ACCENT = '#1f6feb'
SEP = '#30363d'


# Public entry point. Loads the live config, builds the window, blocks on
# mainloop. Designed to be invoked as a subprocess (`python -m whisper_key.main
# --settings`) from the tray so the running app's Tk root isn't disturbed.
def run_settings_window():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
    except ImportError:
        logger.error("Tkinter not available")
        return

    from .config_manager import ConfigManager
    cm = ConfigManager(quiet=True)

    root = tk.Tk()
    root.title("Whisper Local — Settings")
    root.geometry("600x680")
    root.minsize(560, 560)
    root.configure(bg=BG)
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass

    _apply_style(root)

    search_bar = tk.Frame(root, bg=BG)
    search_bar.pack(fill='x', padx=10, pady=(10, 4))
    tk.Label(search_bar, text='🔍', bg=BG, fg=FG_DIM,
             font=('Segoe UI', 11)).pack(side='left')
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_bar, textvariable=search_var, bg=BG2,
                            fg=FG, insertbackground=FG, relief='flat', bd=4,
                            font=('Segoe UI', 10))
    search_entry.pack(side='left', fill='x', expand=True, padx=(4, 0))
    hint_var = tk.StringVar(value='Type to search settings…')
    tk.Label(search_bar, textvariable=hint_var, bg=BG, fg=FG_DIM,
             font=('Segoe UI', 8)).pack(side='left', padx=(8, 0))

    nb = ttk.Notebook(root)
    nb.pack(fill='both', expand=True, padx=8, pady=4)

    vars_ = {}
    row_index = {}
    _TAB_COUNTER['n'] = 0

    _build_general_tab(nb, cm, vars_, row_index)
    _build_audio_tab(nb, cm, vars_, row_index)
    _build_hotkeys_tab(nb, cm, vars_, row_index)
    _build_postprocess_tab(nb, cm, vars_, row_index)

    sep = tk.Frame(root, bg=SEP, height=1)
    sep.pack(fill='x', padx=8)

    bottom = tk.Frame(root, bg=BG)
    bottom.pack(fill='x', padx=8, pady=8)

    def save():
        _save_all(cm, vars_)
        messagebox.showinfo(
            "Saved",
            "Settings saved.\n\n"
            "• Formatting / post-processing changes apply on your next dictation.\n"
            "• Hotkey, model, and audio-device changes take effect after you "
            "restart Whisper Local (tray → Restart).",
            parent=root,
        )
        root.destroy()

    def reset_defaults():
        if not messagebox.askyesno(
            "Reset all settings?",
            "This will reset every setting to its default value.\n\nYour hotwords, commands, transforms, and transcript history will NOT be affected.\n\nContinue?",
            parent=root, icon='warning',
        ):
            return
        try:
            from .utils import get_user_app_data_path
            import os
            settings_path = os.path.join(get_user_app_data_path(), 'user_settings.yaml')
            reset_settings_preserving_hotwords(settings_path)
            messagebox.showinfo(
                "Reset complete",
                "Settings reset to defaults (your dictionary was kept). "
                "Restart Whisper Local to apply.",
                parent=root,
            )
            root.destroy()
        except Exception as e:
            messagebox.showerror("Reset failed", str(e), parent=root)

    def export_settings_action():
        target = filedialog.askdirectory(
            title="Choose a folder for the settings backup",
            parent=root,
        )
        if not target:
            return
        try:
            from .settings_io import export_settings
            if export_settings(target) == 0:
                messagebox.showinfo("Exported", f"Settings backed up to:\n{target}", parent=root)
            else:
                messagebox.showerror("Export failed", "See console for details.", parent=root)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=root)

    def import_settings_action():
        source = filedialog.askdirectory(
            title="Choose a settings backup folder to restore",
            parent=root,
        )
        if not source:
            return
        if not messagebox.askyesno(
            "Restore settings?",
            f"Restore settings from:\n{source}\n\nYour current settings will be overwritten.",
            parent=root, icon='warning',
        ):
            return
        try:
            from .settings_io import import_settings
            if import_settings(source) == 0:
                messagebox.showinfo("Restored", "Settings restored. Restart the app to apply.", parent=root)
                root.destroy()
            else:
                messagebox.showerror("Restore failed", "See console for details.", parent=root)
        except Exception as e:
            messagebox.showerror("Restore failed", str(e), parent=root)

    left = tk.Frame(bottom, bg=BG)
    left.pack(side='left')
    tk.Button(left, text='Backup…', command=export_settings_action,
              bg=BG3, fg=FG, relief='flat', padx=10, pady=4,
              font=('Segoe UI', 9)).pack(side='left', padx=(0, 4))
    tk.Button(left, text='Restore…', command=import_settings_action,
              bg=BG3, fg=FG, relief='flat', padx=10, pady=4,
              font=('Segoe UI', 9)).pack(side='left', padx=(0, 4))
    tk.Button(left, text='Reset to defaults', command=reset_defaults,
              bg=BG3, fg='#f85149', relief='flat', padx=10, pady=4,
              font=('Segoe UI', 9)).pack(side='left')

    right = tk.Frame(bottom, bg=BG)
    right.pack(side='right')
    tk.Button(right, text='Save', command=save,
              bg=ACCENT, fg='white', relief='flat',
              padx=18, pady=5, font=('Segoe UI', 9, 'bold')).pack(side='right', padx=(4, 0))
    tk.Button(right, text='Cancel', command=root.destroy,
              bg=BG3, fg=FG, relief='flat',
              padx=18, pady=5, font=('Segoe UI', 9)).pack(side='right')

    # Snapshot each row widget's real pack geometry now, while everything is laid
    # out exactly as the builders intended. The search filter restores from this
    # instead of guessing at padx/pady (footnotes and note-rows differ), and
    # re-packs in creation order so filtering never reshuffles rows.
    pack_specs = {}
    for rec in row_index.values():
        for w in rec['widgets']:
            try:
                info = {k: v for k, v in w.pack_info().items() if k != 'in'}
                pack_specs[w] = info
            except Exception:
                pack_specs[w] = {'fill': 'x', 'padx': (12, 12), 'pady': 2}

    def _show(w):
        try:
            w.pack(**pack_specs.get(w, {'fill': 'x', 'padx': (12, 12), 'pady': 2}))
        except Exception:
            pass

    def on_search(*_):
        query = search_var.get().lower().strip()
        # Forget everything first, then re-pack the visible rows in their original
        # creation order — guarantees stable ordering regardless of match set.
        for rec in row_index.values():
            for w in rec['widgets']:
                try: w.pack_forget()
                except Exception: pass

        if not query:
            hint_var.set('')
            for rec in row_index.values():
                for w in rec['widgets']:
                    _show(w)
            return

        matched_count = 0
        matched_tabs = set()
        for path, rec in row_index.items():
            haystack = (path + ' ' + rec.get('label', '')).lower()
            if query in haystack:
                matched_count += 1
                matched_tabs.add(rec['tab_index'])
                for w in rec['widgets']:
                    _show(w)
        if matched_tabs:
            try:
                nb.select(min(matched_tabs))
            except Exception:
                pass
        hint_var.set(f'{matched_count} match{"" if matched_count == 1 else "es"}')

    search_var.trace_add('write', on_search)
    root.bind('<Control-f>', lambda e: search_entry.focus_set())
    root.bind('<Escape>', lambda e: root.destroy())

    root.mainloop()


def _apply_style(root):
    try:
        import tkinter.ttk as ttk
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, borderwidth=0)
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=BG3, foreground=FG_DIM,
                         padding=[10, 4])
        style.map('TNotebook.Tab',
                  background=[('selected', BG2)],
                  foreground=[('selected', FG)])
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.configure('TEntry', fieldbackground=BG2, foreground=FG,
                         insertcolor=FG, bordercolor=SEP)
        style.configure('TCombobox', fieldbackground=BG2, foreground=FG,
                         selectbackground=BG2, selectforeground=FG)
        style.configure('TSeparator', background=SEP)
    except Exception:
        pass


_TAB_COUNTER = {'n': 0}


def _frame(nb, title, row_index):
    import tkinter as tk
    outer = ttk.Frame(nb)
    nb.add(outer, text=title)
    tab_idx = _TAB_COUNTER['n']
    _TAB_COUNTER['n'] += 1
    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill='both', expand=True)
    return {'outer': outer, 'inner': inner, 'tab_index': tab_idx}


def _row(tab, path, label, widget_fn, row_index, note=None):
    import tkinter as tk
    parent = tab['inner']
    row_frame = tk.Frame(parent, bg=BG)
    row_frame.pack(fill='x', padx=(12, 12), pady=2)
    tk.Label(row_frame, text=label, fg=FG_DIM, bg=BG,
             font=('Segoe UI', 9), anchor='w', width=24).pack(side='left')
    w = widget_fn(row_frame)
    w.pack(side='right', fill='x', expand=True)
    row_index[path] = {'widgets': [row_frame], 'label': label, 'tab_index': tab['tab_index']}
    if note:
        note_frame = tk.Frame(parent, bg=BG)
        note_frame.pack(fill='x', padx=(12, 12), pady=(0, 4))
        tk.Label(note_frame, text=note, fg=FG_DIM, bg=BG,
                 font=('Segoe UI', 8), anchor='w').pack(side='left')
        row_index[path]['widgets'].append(note_frame)
    return w


def _check(tab, path, label, var, row_index):
    import tkinter as tk
    parent = tab['inner']
    row_frame = tk.Frame(parent, bg=BG)
    row_frame.pack(fill='x', padx=(12, 12), pady=2)
    cb = ttk.Checkbutton(row_frame, text=label, variable=var)
    cb.pack(side='left', anchor='w')
    row_index[path] = {'widgets': [row_frame], 'label': label, 'tab_index': tab['tab_index']}
    return cb


def _separator(tab):
    import tkinter as tk
    parent = tab['inner']
    sep = tk.Frame(parent, bg=SEP, height=1)
    sep.pack(fill='x', padx=12, pady=8)


def _footnote(tab, text):
    import tkinter as tk
    parent = tab['inner']
    fn = tk.Frame(parent, bg=BG)
    fn.pack(fill='x', padx=(12, 12), pady=(8, 4))
    tk.Label(fn, text=text, fg=FG_DIM, bg=BG,
             font=('Segoe UI', 8), anchor='w',
             justify='left', wraplength=520).pack(side='left')


def _combo(parent, var, values):
    cb = ttk.Combobox(parent, textvariable=var, values=values,
                      state='readonly', width=22)
    return cb


def _entry(parent, var):
    import tkinter as tk
    return tk.Entry(parent, textvariable=var,
                    bg=BG2, fg=FG, insertbackground=FG,
                    relief='flat', bd=4, font=('Consolas', 9), width=24)


def _v(cfg, *path, default=''):
    obj = cfg
    for k in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj if obj is not None else default


def _build_general_tab(nb, cm, vars_, row_index):
    import tkinter as tk
    tab = _frame(nb, 'General', row_index)
    cfg = cm.config
    whisper = cfg.get('whisper', {})

    models = list((whisper.get('models') or {}).keys())
    v = tk.StringVar(value=_v(cfg, 'whisper', 'model', default='tiny'))
    vars_['whisper.model'] = v
    _row(tab, 'whisper.model', 'Model', lambda p: _combo(p, v, models), row_index)

    langs = ['auto', 'en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl',
             'ru', 'ja', 'zh', 'ko', 'hi', 'ar']
    v = tk.StringVar(value=_v(cfg, 'whisper', 'language', default='auto'))
    vars_['whisper.language'] = v
    _row(tab, 'whisper.language', 'Language', lambda p: _combo(p, v, langs), row_index)

    modes = ['toggle', 'push_to_talk']
    v = tk.StringVar(value=_v(cfg, 'hotkey', 'recording_mode', default='toggle'))
    vars_['hotkey.recording_mode'] = v
    _row(tab, 'hotkey.recording_mode', 'Recording mode',
         lambda p: _combo(p, v, modes), row_index)

    devs = ['cpu', 'cuda']
    v = tk.StringVar(value=_v(cfg, 'whisper', 'device', default='cpu'))
    vars_['whisper.device'] = v
    _row(tab, 'whisper.device', 'Compute device',
         lambda p: _combo(p, v, devs), row_index)

    ctypes = ['int8', 'float16', 'float32']
    v = tk.StringVar(value=_v(cfg, 'whisper', 'compute_type', default='int8'))
    vars_['whisper.compute_type'] = v
    _row(tab, 'whisper.compute_type', 'Compute type',
         lambda p: _combo(p, v, ctypes), row_index)

    v = tk.StringVar(value=str(_v(cfg, 'whisper', 'beam_size', default=5)))
    vars_['whisper.beam_size'] = v
    _row(tab, 'whisper.beam_size', 'Beam size (1–10)',
         lambda p: _entry(p, v), row_index)

    v = tk.StringVar(value=str(_v(cfg, 'whisper', 'initial_prompt', default='')))
    vars_['whisper.initial_prompt'] = v
    _row(tab, 'whisper.initial_prompt', 'Initial prompt',
         lambda p: _entry(p, v), row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'whisper', 'prompt_from_selection', default=False)))
    vars_['whisper.prompt_from_selection'] = v
    _check(tab, 'whisper.prompt_from_selection',
           'Seed prompt from selected text at recording start', v, row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'clipboard', 'auto_paste', default=True)))
    vars_['clipboard.auto_paste'] = v
    _check(tab, 'clipboard.auto_paste',
           'Auto-paste at cursor after transcription  (per-app rules can override)',
           v, row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'audio', 'continuous_mode', default=False)))
    vars_['audio.continuous_mode'] = v
    _check(tab, 'audio.continuous_mode',
           'Continuous dictation mode (auto-restarts recording)', v, row_index)


def _build_audio_tab(nb, cm, vars_, row_index):
    import tkinter as tk
    tab = _frame(nb, 'Audio', row_index)
    cfg = cm.config
    ns = (cfg.get('audio') or {}).get('noise_suppression') or {}

    v = tk.BooleanVar(value=bool(ns.get('enabled', False)))
    vars_['audio.noise_suppression.enabled'] = v
    _check(tab, 'audio.noise_suppression.enabled',
           'Noise suppression  (pip install noisereduce)', v, row_index)

    v = tk.StringVar(value=str(ns.get('strength', 0.75)))
    vars_['audio.noise_suppression.strength'] = v
    _row(tab, 'audio.noise_suppression.strength',
         'Noise strength (0.0 – 1.0)', lambda p: _entry(p, v), row_index)

    wm = (cfg.get('audio') or {}).get('whisper_mode')
    wm = wm if isinstance(wm, dict) else {}
    v = tk.BooleanVar(value=bool(wm.get('enabled', False)))
    vars_['audio.whisper_mode.enabled'] = v
    _check(tab, 'audio.whisper_mode.enabled',
           'Whisper mode  (boost quiet speech before transcribing)', v, row_index)

    v = tk.StringVar(value=str(wm.get('max_gain', 8.0)))
    vars_['audio.whisper_mode.max_gain'] = v
    _row(tab, 'audio.whisper_mode.max_gain', 'Whisper mode max boost (×)',
         lambda p: _entry(p, v), row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'audio', 'pause_media_on_record', default=False)))
    vars_['audio.pause_media_on_record'] = v
    _check(tab, 'audio.pause_media_on_record',
           'Pause media player when recording starts', v, row_index)

    v = tk.StringVar(value=str(_v(cfg, 'audio', 'max_duration', default=900)))
    vars_['audio.max_duration'] = v
    _row(tab, 'audio.max_duration', 'Max recording duration (s)',
         lambda p: _entry(p, v), row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'vad', 'vad_realtime_enabled', default=True)))
    vars_['vad.vad_realtime_enabled'] = v
    _check(tab, 'vad.vad_realtime_enabled',
           'Auto-stop on silence (realtime VAD)', v, row_index)

    v = tk.StringVar(value=str(_v(cfg, 'vad', 'vad_silence_timeout_seconds', default=30.0)))
    vars_['vad.vad_silence_timeout_seconds'] = v
    _row(tab, 'vad.vad_silence_timeout_seconds', 'Silence timeout (s)',
         lambda p: _entry(p, v), row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'audio_feedback', 'enabled', default=True)))
    vars_['audio_feedback.enabled'] = v
    _check(tab, 'audio_feedback.enabled',
           'Audio feedback sounds (start / stop beeps)', v, row_index)


def _build_hotkeys_tab(nb, cm, vars_, row_index):
    import tkinter as tk
    tab = _frame(nb, 'Hotkeys', row_index)
    cfg = cm.config

    pairs = [
        ('hotkey.recording_hotkey', 'Record hotkey'),
        ('hotkey.stop_key', 'Stop key'),
        ('hotkey.auto_send_key', 'Auto-send key'),
        ('hotkey.cancel_combination', 'Cancel'),
        ('hotkey.command_hotkey', 'Command mode'),
        ('hotkey.rephrase_hotkey', 'Rephrase (PTT)'),
        ('hotkey.pause_hotkey', 'Pause all hotkeys'),
        ('hotkey.paste_last_hotkey', 'Paste last dictation'),
    ]
    for path, label in pairs:
        parts = path.split('.')
        v = tk.StringVar(value=str(_v(cfg, *parts, default='')))
        vars_[path] = v
        _row(tab, path, label, lambda p, var=v: _entry(p, var), row_index)

    v = tk.BooleanVar(value=bool(_v(cfg, 'hotkey', 'double_tap_to_lock', default=False)))
    vars_['hotkey.double_tap_to_lock'] = v
    _check(tab, 'hotkey.double_tap_to_lock',
           'Hands-free: double-tap the record hotkey to lock recording on', v, row_index)

    _footnote(tab, 'Hotkey changes take effect on next app restart. '
                   'Format: lowercase modifiers separated by + (e.g. "ctrl+win+space").')


def _build_postprocess_tab(nb, cm, vars_, row_index):
    import tkinter as tk
    tab = _frame(nb, 'Post-process', row_index)
    cfg = cm.config
    pp = cfg.get('postprocess') or {}

    from .styles import available_styles
    style_names = [_NO_STYLE] + sorted(available_styles(pp))
    v = tk.StringVar(value=str(pp.get('style') or _NO_STYLE))
    vars_['postprocess.style'] = v
    _row(tab, 'postprocess.style', 'Writing style',
         lambda p: _combo(p, v, style_names), row_index,
         note='formal · casual · very_casual (all lowercase) · verbatim. '
              'Per-app styles live in app_rules.yaml.')

    checks = [
        ('postprocess.strip_filler_words', 'Strip filler words  (um, uh, like, you know)', 'strip_filler_words'),
        ('postprocess.capitalize_first', 'Capitalize first letter', 'capitalize_first'),
        ('postprocess.ensure_punctuation', 'Ensure sentence ends with punctuation', 'ensure_punctuation'),
        ('postprocess.strip_trailing_period', 'Strip trailing period', 'strip_trailing_period'),
        ('postprocess.inline_formatting', 'Inline voice formatting  (say "comma", "period")', 'inline_formatting'),
        ('postprocess.inline_formatting_absorb_punctuation',
         'Absorb Whisper punctuation around spoken cues  (fixes "hello,, world")', 'inline_formatting_absorb_punctuation'),
        ('postprocess.inline_formatting_extend',
         'Keep English cue words when adding your own', 'inline_formatting_extend'),
        ('postprocess.voice_editing',
         'Voice editing  (say "scratch that" to erase the last sentence)', 'voice_editing'),
        ('postprocess.remove_repeated_words',
         'Remove stutters  ("I I think" → "I think")', 'remove_repeated_words'),
        ('postprocess.list_formatting',
         'Spoken lists  ("first … second …" → numbered list)', 'list_formatting'),
    ]
    for path, label, cfg_key in checks:
        v = tk.BooleanVar(value=bool(pp.get(cfg_key, False)))
        vars_[path] = v
        _check(tab, path, label, v, row_index)

    # Smart-formatting sub-toggles live under a nested dict; surface them here too.
    sf = pp.get('smart_formatting') or {}
    smart_checks = [
        ('postprocess.smart_formatting.times', 'Smart times  ("3 p.m." → "3 PM")', 'times'),
        ('postprocess.smart_formatting.emails', 'Smart emails  ("john at x dot com" → "john@x.com")', 'emails'),
        ('postprocess.smart_formatting.urls', 'Smart URLs  ("example dot com" → "example.com")', 'urls'),
    ]
    for path, label, cfg_key in smart_checks:
        v = tk.BooleanVar(value=bool(sf.get(cfg_key, False)))
        vars_[path] = v
        _check(tab, path, label, v, row_index)

    bt = pp.get('backtrack')
    bt = bt if isinstance(bt, dict) else {}
    v = tk.BooleanVar(value=bool(bt.get('enabled', False)))
    vars_['postprocess.backtrack.enabled'] = v
    _check(tab, 'postprocess.backtrack.enabled',
           'Backtrack  ("at 2, actually 3" → "at 3")', v, row_index)

    _footnote(tab, 'Snippets (spoken shortcuts like "my signature") live under snippets '
                   'in the settings file. '
                   'Custom phrase→symbol mappings (for other languages) live under '
                   'inline_formatting_replacements in the settings file; misrecognition '
                   'fixes go under replacements (or use the history window\'s "Fix this '
                   'everywhere...").')

    _separator(tab)

    ollama = pp.get('ollama') or {}

    v = tk.BooleanVar(value=bool(ollama.get('enabled', False)))
    vars_['postprocess.ollama.enabled'] = v
    _check(tab, 'postprocess.ollama.enabled',
           'Ollama polish  (local LLM punctuation cleanup)', v, row_index)

    v = tk.StringVar(value=str(ollama.get('endpoint', 'http://localhost:11434')))
    vars_['postprocess.ollama.endpoint'] = v
    _row(tab, 'postprocess.ollama.endpoint', 'Ollama endpoint',
         lambda p: _entry(p, v), row_index)

    v = tk.StringVar(value=str(ollama.get('model', 'llama3.2')))
    vars_['postprocess.ollama.model'] = v
    _row(tab, 'postprocess.ollama.model', 'Ollama model',
         lambda p: _entry(p, v), row_index)

    v = tk.StringVar(value=str(ollama.get('timeout', 5)))
    vars_['postprocess.ollama.timeout'] = v
    _row(tab, 'postprocess.ollama.timeout', 'Ollama timeout (s)',
         lambda p: _entry(p, v), row_index)


# Flatten the {dotted.path: tkinter.Var} dict back into ConfigManager updates.
# Two-level paths (e.g. "whisper.model") become direct update_user_setting calls.
# Three-level paths (e.g. "postprocess.ollama.enabled") get batched per parent
# so we issue a single update per nested dict, preserving sibling keys.
def _save_all(cm, vars_):
    pending_nested = {}

    for path, var in vars_.items():
        raw = var.get()
        value = _coerce(var, raw, path)
        parts = path.split('.')

        if len(parts) == 2:
            try:
                cm.update_user_setting(parts[0], parts[1], value)
            except Exception as e:
                logger.warning(f"Could not save {path}: {e}")

        elif len(parts) == 3:
            key = (parts[0], parts[1])
            if key not in pending_nested:
                parent = cm.config.get(parts[0], {})
                pending_nested[key] = dict(parent.get(parts[1]) or {})
            pending_nested[key][parts[2]] = value

    for (section, sub_key), sub_dict in pending_nested.items():
        try:
            cm.update_user_setting(section, sub_key, sub_dict)
        except Exception as e:
            logger.warning(f"Could not save {section}.{sub_key}: {e}")


# Settings whose values are genuinely numeric. ONLY these are int/float-coerced;
# everything else stays a string so free-text fields (initial_prompt, hotkeys,
# ollama model/endpoint) aren't silently turned into numbers when they happen to
# look numeric — e.g. initial_prompt "2024" must stay the string "2024".
_NUMERIC_PATHS = {
    'whisper.beam_size',
    'audio.max_duration',
    'audio.noise_suppression.strength',
    'vad.vad_silence_timeout_seconds',
    'postprocess.ollama.timeout',
    'audio.whisper_mode.max_gain',
    'hotkey.double_tap_window_ms',
}

# Shown in the style picker for "no style: use the individual toggles".
_NO_STYLE = '(none)'


# Turn the string-based Tkinter value back into the right Python type, keyed by
# the setting's path so coercion is by declared type, not by guessing from the
# string contents.
def _coerce(var, raw, path):
    import tkinter as tk
    if isinstance(var, tk.BooleanVar):
        return bool(raw)
    if path == 'postprocess.style' and raw == _NO_STYLE:
        return ''
    if path in _NUMERIC_PATHS:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
        try:
            return float(raw)
        except (ValueError, TypeError):
            pass
    return raw
