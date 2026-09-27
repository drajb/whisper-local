# cheat_sheet.py
# Pops up a window showing the user's currently configured hotkeys. Users forget
# their bindings mid-week, especially after editing user_settings.yaml. Reading
# the live config (not the defaults) means what the user sees is always what
# the app actually responds to. Also lists transform hotkeys when transforms_manager
# is supplied.

import logging
import threading

logger = logging.getLogger(__name__)

# Singleton guard — re-invoking the tray menu item or the CLI flag should just
# raise the existing window instead of stacking duplicates.
_thread_lock = threading.Lock()
_current_root = None


# Public entry point. Pass config_manager and transforms_manager from the running
# app when calling from the tray; the CLI path (--cheat-sheet) constructs a fresh
# ConfigManager since no app instance is running. blocking=True runs the window
# on the calling thread, for platforms where Tk must own the main thread (macOS).
def show_cheat_sheet(config_manager=None, transforms_manager=None, blocking: bool = False):
    global _current_root
    with _thread_lock:
        try:
            if _current_root and _current_root.winfo_exists():
                _current_root.lift()
                _current_root.focus_force()
                return
        except Exception:
            pass

    if blocking:
        _run(config_manager, transforms_manager)
        return None

    # Returned so a CLI caller can wait on it; see issue #10.
    thread = threading.Thread(
        target=_run,
        args=(config_manager, transforms_manager),
        daemon=True,
        name='cheat-sheet',
    )
    thread.start()
    return thread


# Window body, run on a daemon thread with its own Tk root (same one-root-per-
# window pattern as the other windows). Reads the LIVE config so the sheet always
# reflects the user's current bindings rather than the shipped defaults.
def _run(config_manager, transforms_manager):
    global _current_root
    try:
        import tkinter as tk
    except ImportError:
        logger.warning("Tkinter not available; cheat sheet disabled")
        return

    BG = '#0d1117'
    BG2 = '#161b22'
    FG = '#c9d1d9'
    FG_DIM = '#8b949e'
    KEY_BG = '#21262d'
    ACCENT = '#1f6feb'

    if config_manager is None:
        try:
            from .config_manager import ConfigManager
            config_manager = ConfigManager(quiet=True)
        except Exception as e:
            logger.error(f"Could not load config: {e}")
            return

    cfg = config_manager.config or {}
    hk = cfg.get('hotkey', {}) or {}

    record_help = "Hold to start recording (release to stop in push-to-talk mode)"
    if hk.get('double_tap_to_lock') and hk.get('recording_mode', 'push_to_talk') == 'push_to_talk':
        record_help += ". Double-tap to keep recording hands-free; tap again to stop"
    items = [
        ("Record / dictate", hk.get('recording_hotkey'), record_help),
        ("Stop & paste", hk.get('stop_key'),
         "Stop recording and deliver text to the cursor"),
        ("Stop & auto-send (Enter)", hk.get('auto_send_key'),
         "Stop, paste, and press Enter — perfect for chat apps"),
        ("Cancel recording", hk.get('cancel_combination'),
         "Discard the current recording without transcribing"),
        ("Voice command mode", hk.get('command_hotkey'),
         "Say a trigger phrase from commands.yaml to run shortcuts/macros"),
        ("AI rephrase (PTT)", hk.get('rephrase_hotkey'),
         "Select text, hold, speak your instruction, release — local Ollama rewrites it"),
        ("Paste last dictation", hk.get('paste_last_hotkey'),
         "Type your last dictation again, e.g. after it landed in the wrong window"),
        ("Pause all hotkeys", hk.get('pause_hotkey'),
         "Disable every Whisper Local hotkey until pressed again"),
    ]

    transforms = []
    if transforms_manager:
        try:
            transforms = [
                (t.get('name'), t.get('hotkey'), t.get('prompt', '')[:60])
                for t in transforms_manager.list_transforms()
                if t.get('hotkey')
            ]
        except Exception:
            pass

    root = tk.Tk()
    with _thread_lock:
        _current_root = root

    root.title("Whisper Local — Hotkey Cheat Sheet")
    root.geometry("620x560")
    root.configure(bg=BG)
    root.resizable(False, True)
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass

    header = tk.Frame(root, bg=BG)
    header.pack(fill='x', padx=20, pady=(18, 4))
    tk.Label(header, text="🎯 Your current hotkeys",
             bg=BG, fg=FG, font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    tk.Label(header, text="Change these in Settings → Hotkeys (changes take effect on next launch).",
             bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 4))

    body = tk.Frame(root, bg=BG)
    body.pack(fill='both', expand=True, padx=20, pady=(6, 10))

    def _row(parent, label, key, desc):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill='x', pady=3)
        inner = tk.Frame(row, bg=BG2)
        inner.pack(fill='x', padx=12, pady=8)
        tk.Label(inner, text=label, bg=BG2, fg=FG,
                 font=('Segoe UI', 10, 'bold'),
                 anchor='w', width=24).pack(side='left')
        key_text = (key or '—').upper() if key else '—'
        tk.Label(inner, text=key_text, bg=KEY_BG, fg=ACCENT,
                 font=('Consolas', 9, 'bold'),
                 padx=8, pady=2).pack(side='left', padx=(0, 10))
        tk.Label(inner, text=desc, bg=BG2, fg=FG_DIM,
                 font=('Segoe UI', 9), anchor='w', justify='left',
                 wraplength=300).pack(side='left', fill='x', expand=True)

    for label, key, desc in items:
        _row(body, label, key, desc)

    if transforms:
        tk.Label(body, text="\n🪄 Transform hotkeys",
                 bg=BG, fg=FG, font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(8, 4))
        for name, key, prompt in transforms:
            _row(body, name.title(), key, prompt + ('…' if len(prompt) >= 60 else ''))

    footer = tk.Frame(root, bg=BG)
    footer.pack(fill='x', padx=20, pady=(0, 14))
    tk.Label(footer, text="Tip: press Ctrl+W or Esc to close this window.",
             bg=BG, fg=FG_DIM, font=('Segoe UI', 8)).pack(side='left')
    tk.Button(footer, text="Close", command=root.destroy,
              bg=KEY_BG, fg=FG, relief='flat',
              padx=14, pady=3, font=('Segoe UI', 9)).pack(side='right')

    root.bind('<Escape>', lambda e: root.destroy())
    root.bind('<Control-w>', lambda e: root.destroy())

    def _clear_ref():
        global _current_root
        with _thread_lock:
            _current_root = None
    root.protocol("WM_DELETE_WINDOW", lambda: (_clear_ref(), root.destroy()))

    root.mainloop()
    _clear_ref()
