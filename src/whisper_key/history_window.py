# history_window.py
# Searchable browser over `transcripts.jsonl`. Launched by `whisper-local --history`
# or the tray "Transcript history..." item. Pure Tkinter, no external deps.
# Highlights matching rows live as the user types, with a click-to-copy action.

import logging
import threading

logger = logging.getLogger(__name__)

# Singleton — re-opening the window just raises the existing one.
_lock = threading.Lock()
_instance = None


# Public entry point. Spawns the window on a daemon thread so the caller
# (CLI or tray) doesn't block. The window manages its own lifecycle.
# blocking=True runs it on the calling thread instead, for platforms where Tk
# must own the main thread (macOS; see window_launcher.py).
def show_history(blocking: bool = False):
    global _instance
    with _lock:
        try:
            if _instance and _instance.winfo_exists():
                _instance.lift()
                _instance.focus_force()
                return
        except Exception:
            pass

    # Builds and owns the window. Runs as the body of a daemon thread with its
    # OWN Tk root — this app has no single Tk main loop, so each window is
    # self-contained (see docs/AUDIT.md on the multi-root decision). Everything
    # is defined inside so the widgets and the `visible` list share one closure.
    def _run():
        global _instance
        try:
            import tkinter as tk
            import pyperclip
        except ImportError:
            logger.warning("Tkinter not available for history window")
            return

        from .transcript_log import load_transcripts
        all_entries = load_transcripts()

        root = tk.Tk()
        with _lock:
            _instance = root

        # Reset the singleton on close so a later open creates a fresh root
        # instead of probing a destroyed one.
        def _clear_ref():
            global _instance
            with _lock:
                _instance = None
        root.protocol("WM_DELETE_WINDOW", lambda: (_clear_ref(), root.destroy()))

        root.title("Transcript History — Whisper Local")
        root.geometry("680x520")
        root.configure(bg='#0d1117')
        root.resizable(True, True)
        try:
            root.attributes('-topmost', True)
        except Exception:
            pass

        # ── search bar ──
        top = tk.Frame(root, bg='#0d1117')
        top.pack(fill='x', padx=10, pady=(10, 4))
        tk.Label(top, text='🔍', bg='#0d1117', fg='#8b949e',
                 font=('Segoe UI', 11)).pack(side='left')
        search_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=search_var, bg='#161b22',
                         fg='#c9d1d9', insertbackground='#c9d1d9',
                         relief='flat', bd=4, font=('Segoe UI', 10))
        entry.pack(side='left', fill='x', expand=True, padx=(4, 0))
        entry.focus_set()

        # ── listbox ──
        mid = tk.Frame(root, bg='#0d1117')
        mid.pack(fill='both', expand=True, padx=10, pady=4)

        scroll = tk.Scrollbar(mid)
        scroll.pack(side='right', fill='y')
        listbox = tk.Listbox(mid, yscrollcommand=scroll.set,
                             bg='#161b22', fg='#c9d1d9',
                             selectbackground='#1f6feb',
                             relief='flat', bd=0,
                             font=('Consolas', 9),
                             activestyle='none')
        listbox.pack(fill='both', expand=True)
        scroll.config(command=listbox.yview)

        # ── preview pane ──
        preview_var = tk.StringVar(value='')
        preview = tk.Label(root, textvariable=preview_var,
                           bg='#161b22', fg='#8b949e',
                           font=('Segoe UI', 9), anchor='w',
                           wraplength=620, justify='left',
                           padx=8, pady=4)
        preview.pack(fill='x', padx=10, pady=(0, 4))

        # ── status + buttons ──
        status_var = tk.StringVar()
        tk.Label(root, textvariable=status_var, bg='#0d1117', fg='#58a6ff',
                 anchor='w', font=('Segoe UI', 8)).pack(fill='x', padx=10)

        btns = tk.Frame(root, bg='#0d1117')
        btns.pack(fill='x', padx=10, pady=(4, 10))

        visible = []

        def copy_selected():
            try:
                idx = listbox.curselection()[0]
                text = visible[idx].get('text', '')
                pyperclip.copy(text)
                status_var.set(f'Copied {len(text)} chars ✓')
                root.after(2500, lambda: _update_status())
            except IndexError:
                pass

        # "Fix this everywhere..." turns a misrecognition in the selected row into
        # a persistent post-transcription correction (postprocess.replacements).
        def fix_always():
            source = ''
            try:
                source = visible[listbox.curselection()[0]].get('text', '')
            except IndexError:
                pass
            _open_correction_dialog(root, source, status_var, _update_status)

        # "Suggest hotwords" mines your own history for frequent proper nouns.
        def suggest_hotwords_action():
            _open_hotword_suggest_dialog(root, status_var, _update_status)

        tk.Button(btns, text='Copy', command=copy_selected,
                  bg='#1f6feb', fg='white', relief='flat',
                  padx=14, pady=3,
                  font=('Segoe UI', 9)).pack(side='left')
        tk.Button(btns, text='Fix this everywhere…', command=fix_always,
                  bg='#21262d', fg='#c9d1d9', relief='flat',
                  padx=14, pady=3,
                  font=('Segoe UI', 9)).pack(side='left', padx=(6, 0))
        tk.Button(btns, text='Suggest hotwords', command=suggest_hotwords_action,
                  bg='#21262d', fg='#c9d1d9', relief='flat',
                  padx=14, pady=3,
                  font=('Segoe UI', 9)).pack(side='left', padx=(6, 0))
        tk.Button(btns, text='Close', command=root.destroy,
                  bg='#21262d', fg='#c9d1d9', relief='flat',
                  padx=14, pady=3,
                  font=('Segoe UI', 9)).pack(side='right')

        def _update_status():
            status_var.set(f'{len(visible)} shown  ·  {len(all_entries)} total')

        def _refresh(query=''):
            q = query.lower().strip()
            del visible[:]
            visible.extend(
                e for e in all_entries
                if not q or q in (e.get('text') or '').lower()
            )
            listbox.delete(0, 'end')
            for e in visible:
                ts = (e.get('timestamp') or '')[:16].replace('T', ' ')
                app = e.get('app', '')
                app_hint = f' [{app}]' if app else ''
                text = (e.get('text') or '')
                snippet = text[:72] + ('…' if len(text) > 72 else '')
                listbox.insert('end', f'{ts}{app_hint}  {snippet}')
            _update_status()

        def _on_select(evt):
            try:
                idx = listbox.curselection()[0]
                text = visible[idx].get('text', '')
                preview_var.set(text[:300] + ('…' if len(text) > 300 else ''))
            except IndexError:
                preview_var.set('')

        listbox.bind('<<ListboxSelect>>', _on_select)
        search_var.trace_add('write', lambda *_: _refresh(search_var.get()))

        if not all_entries:
            status_var.set('No transcripts yet — start dictating!')
        else:
            _refresh()

        root.mainloop()

    if blocking:
        _run()
        return None

    # Returned so a CLI caller can wait on it. The thread is a daemon, so a
    # process that exits without joining kills the window instantly — which is
    # exactly what `--history` used to do (issue #10).
    thread = threading.Thread(target=_run, daemon=True, name='history-window')
    thread.start()
    return thread


# Modal-ish correction editor. `source` is the selected transcript (shown as a
# hint); the user types the misheard text and the fix. Saves a whole-word,
# case-insensitive correction that applies to all FUTURE dictations.
def _open_correction_dialog(parent, source, status_var, on_saved):
    import tkinter as tk
    from .corrections import add_replacement

    dlg = tk.Toplevel(parent)
    dlg.title("Fix this everywhere")
    dlg.configure(bg='#0d1117')
    dlg.geometry("460x300")
    try:
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
    except Exception:
        pass

    def _lbl(text, **kw):
        tk.Label(dlg, text=text, bg='#0d1117', fg='#8b949e',
                 anchor='w', justify='left', font=('Segoe UI', 9), **kw).pack(
            fill='x', padx=14, pady=(10, 2))

    _lbl("Replace this text (as Whisper hears it):")
    from_var = tk.StringVar()
    tk.Entry(dlg, textvariable=from_var, bg='#161b22', fg='#c9d1d9',
             insertbackground='#c9d1d9', relief='flat', bd=4,
             font=('Segoe UI', 10)).pack(fill='x', padx=14)

    _lbl("With this:")
    to_var = tk.StringVar()
    to_entry = tk.Entry(dlg, textvariable=to_var, bg='#161b22', fg='#c9d1d9',
                        insertbackground='#c9d1d9', relief='flat', bd=4,
                        font=('Segoe UI', 10))
    to_entry.pack(fill='x', padx=14)

    if source:
        snippet = source[:120] + ('…' if len(source) > 120 else '')
        _lbl(f"From: “{snippet}”")

    msg_var = tk.StringVar()
    tk.Label(dlg, textvariable=msg_var, bg='#0d1117', fg='#58a6ff',
             anchor='w', font=('Segoe UI', 8)).pack(fill='x', padx=14, pady=(8, 0))

    def save():
        if add_replacement(from_var.get(), to_var.get()):
            # Refresh counts first, THEN set the confirmation, so the count
            # refresh doesn't clobber the message in the same Tk callback.
            if on_saved:
                on_saved()
            status_var.set('Correction saved — applies to future dictations ✓')
            dlg.destroy()
        else:
            msg_var.set("Nothing saved — enter text to replace, and a different result.")

    row = tk.Frame(dlg, bg='#0d1117')
    row.pack(fill='x', padx=14, pady=14, side='bottom')
    tk.Button(row, text='Save correction', command=save, bg='#1f6feb', fg='white',
              relief='flat', padx=14, pady=3, font=('Segoe UI', 9)).pack(side='left')
    tk.Button(row, text='Cancel', command=dlg.destroy, bg='#21262d', fg='#c9d1d9',
              relief='flat', padx=14, pady=3, font=('Segoe UI', 9)).pack(side='right')


# Shows mined hotword candidates from history with checkboxes; adds the ticked
# ones to whisper.hotwords. Candidates the user hasn't confirmed are never added.
def _open_hotword_suggest_dialog(parent, status_var, on_saved):
    import tkinter as tk
    from .dictionary import add_word, suggest_hotwords_from_history

    candidates = suggest_hotwords_from_history()

    dlg = tk.Toplevel(parent)
    dlg.title("Suggested hotwords")
    dlg.configure(bg='#0d1117')
    dlg.geometry("360x420")
    try:
        dlg.transient(parent)
        dlg.attributes('-topmost', True)
    except Exception:
        pass

    if not candidates:
        tk.Label(dlg, text="No strong suggestions yet.\nKeep dictating — names you "
                 "use often will show up here.", bg='#0d1117', fg='#8b949e',
                 justify='left', font=('Segoe UI', 10)).pack(padx=16, pady=20)
        tk.Button(dlg, text='Close', command=dlg.destroy, bg='#21262d', fg='#c9d1d9',
                  relief='flat', padx=14, pady=3, font=('Segoe UI', 9)).pack(pady=10)
        return

    tk.Label(dlg, text="Frequent words in your history. Tick any to add to your "
             "dictionary so Whisper biases toward them:", bg='#0d1117', fg='#8b949e',
             wraplength=320, justify='left', font=('Segoe UI', 9)).pack(
        fill='x', padx=14, pady=(12, 6))

    checks = []
    body = tk.Frame(dlg, bg='#0d1117')
    body.pack(fill='both', expand=True, padx=14)
    for word, count in candidates:
        var = tk.BooleanVar(value=False)
        checks.append((word, var))
        tk.Checkbutton(body, text=f'{word}   ·  {count}×', variable=var,
                       bg='#0d1117', fg='#c9d1d9', selectcolor='#161b22',
                       activebackground='#0d1117', activeforeground='#c9d1d9',
                       anchor='w', font=('Segoe UI', 10)).pack(fill='x')

    def add_ticked():
        added = 0
        for word, var in checks:
            if var.get() and add_word(word):
                added += 1
        if on_saved:
            on_saved()
        status_var.set(f'Added {added} hotword{"s" if added != 1 else ""} ✓')
        dlg.destroy()

    row = tk.Frame(dlg, bg='#0d1117')
    row.pack(fill='x', padx=14, pady=12, side='bottom')
    tk.Button(row, text='Add selected', command=add_ticked, bg='#1f6feb', fg='white',
              relief='flat', padx=14, pady=3, font=('Segoe UI', 9)).pack(side='left')
    tk.Button(row, text='Cancel', command=dlg.destroy, bg='#21262d', fg='#c9d1d9',
              relief='flat', padx=14, pady=3, font=('Segoe UI', 9)).pack(side='right')
