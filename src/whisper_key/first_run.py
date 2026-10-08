# first_run.py
# Shows a one-time welcome window on the very first launch.
# A flag file in %APPDATA%\whisperkey marks completion so the window never
# re-appears unless the user deletes that file. The window is intentionally
# minimal: 3 tips + a privacy promise, no settings, no wizard. The full
# wizard lives in setup_wizard.py for users who run `--setup` explicitly.

import logging
import threading
from pathlib import Path

from .utils import get_user_app_data_path

logger = logging.getLogger(__name__)

# Sentinel file written after the user dismisses the welcome window.
_FLAG_FILE = 'first_run_complete.txt'


# Returns True only when the user has never completed first-run before.
# Cheap call — just a filesystem stat — safe to invoke on every launch.
def is_first_run() -> bool:
    return not (Path(get_user_app_data_path()) / _FLAG_FILE).exists()


# Called from the welcome window's Close handler. Writes the sentinel so we
# don't re-show on next launch.
def mark_first_run_complete():
    try:
        path = Path(get_user_app_data_path())
        path.mkdir(parents=True, exist_ok=True)
        (path / _FLAG_FILE).write_text("ok", encoding='utf-8')
    except Exception as e:
        logger.debug(f"Could not write first-run flag: {e}")


# How often the window checks whether the app was asked to shut down.
_SHUTDOWN_POLL_MS = 200


# Closes the welcome window if the app is asked to shut down while it's open.
# Keep this at module level. As a nested function it referred to itself to
# reschedule, and the reference cycle kept the window's Tk interpreter alive
# after _run_welcome() returned. The garbage collector then freed it on
# whichever thread it happened to run on, and Tcl aborts the process when an
# interpreter is deleted off the thread that created it (issue #18).
def _close_on_shutdown(root, shutdown_event):
    if shutdown_event.is_set():
        root.quit()
        return
    root.after(_SHUTDOWN_POLL_MS, _close_on_shutdown, root, shutdown_event)


# Shows the welcome window. `hotkey_label` is the user's *current* configured
# recording hotkey, displayed in the tip text so it's accurate.
#
# Normally it runs on a daemon thread so it doesn't hold up startup. Where Tk is
# main-thread-only (macOS, issue #14) it runs inline instead, and the caller
# must be on the main thread; it blocks until dismissed. Tk's own loop keeps
# pumping Cocoa events meanwhile, so the tray and hotkeys stay live. The signal
# handler only sets `shutdown_event`, which nothing else polls while this
# blocks, so the window watches it itself; otherwise SIGTERM would be swallowed.
def show_welcome_window(on_close=None, hotkey_label: str = "Ctrl+Win", shutdown_event=None):
    from .utils import tk_requires_main_thread
    if tk_requires_main_thread():
        _run_welcome(on_close, hotkey_label, shutdown_event)
        return
    threading.Thread(
        target=_run_welcome,
        args=(on_close, hotkey_label, shutdown_event),
        daemon=True,
        name='welcome-window',
    ).start()


# Window body, with its own Tk root. Shown exactly once (the caller gates on a
# marker file); `on_close` fires afterwards so first-run follow-ups, such as the
# autostart prompt, happen only after the user has actually seen and dismissed
# this. A shutdown request closes the window without counting as a dismissal.
def _run_welcome(on_close, hotkey_label, shutdown_event=None):
    try:
        import tkinter as tk
    except ImportError:
        logger.warning("Tkinter unavailable — skipping welcome window")
        if on_close:
            on_close()
        return

    BG = '#0d1117'
    BG2 = '#161b22'
    FG = '#c9d1d9'
    FG_DIM = '#8b949e'
    ACCENT = '#1f6feb'

    root = tk.Tk()
    root.title("Welcome to Whisper Local")
    root.geometry("560x560")
    root.configure(bg=BG)
    root.resizable(False, False)
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass

    container = tk.Frame(root, bg=BG)
    container.pack(fill='both', expand=True, padx=24, pady=20)

    tk.Label(container, text="👋  Welcome to Whisper Local",
             bg=BG, fg=FG, font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    tk.Label(container, text="Free, fully offline AI dictation. Three quick things:",
             bg=BG, fg=FG_DIM, font=('Segoe UI', 10)).pack(anchor='w', pady=(2, 14))

    items = [
        ("1.", f"Hold {hotkey_label} anywhere, speak, release.",
         "Your words appear at the cursor in any app — chat, code, browser, terminal."),
        ("2.", "The tray icon shows status & settings.",
         "On Windows the tray hides icons by default — click the ^ arrow on the taskbar "
         "and drag the Whisper Local icon out for one-click access."),
        ("3.", "If something's off, the tray icon can diagnose it.",
         "Right-click it → Help & diagnostics → Run diagnostics. It checks the mic, "
         "permissions, the model and the hotkeys and says what to fix."),
    ]

    for num, title, body in items:
        row = tk.Frame(container, bg=BG2, bd=0)
        row.pack(fill='x', pady=4)
        inner = tk.Frame(row, bg=BG2)
        inner.pack(fill='x', padx=14, pady=10)
        tk.Label(inner, text=num, bg=BG2, fg=ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(side='left', anchor='n')
        body_frame = tk.Frame(inner, bg=BG2)
        body_frame.pack(side='left', fill='x', expand=True, padx=(10, 0))
        tk.Label(body_frame, text=title, bg=BG2, fg=FG,
                 font=('Segoe UI', 10, 'bold'),
                 anchor='w', justify='left', wraplength=440).pack(fill='x')
        tk.Label(body_frame, text=body, bg=BG2, fg=FG_DIM,
                 font=('Segoe UI', 9),
                 anchor='w', justify='left', wraplength=440).pack(fill='x', pady=(2, 0))

    # Somewhere to try it before the window closes. Seeing their own words land
    # here is the moment it clicks for most people, and it proves the hotkey,
    # the mic and the paste all work while the instructions are still on
    # screen. The hotkeys are already live by the time this window opens.
    try_box = tk.Text(container, height=3, bg=BG2, fg=FG, insertbackground=FG,
                      bd=0, highlightthickness=1, highlightbackground=ACCENT,
                      highlightcolor=ACCENT, font=('Segoe UI', 10), wrap='word',
                      padx=10, pady=8)
    try_box.insert('1.0', f"Try it now: click here, hold {hotkey_label}, say something, let go.")
    try_box.tag_add('hint', '1.0', 'end')
    try_box.tag_config('hint', foreground=FG_DIM)
    try_box.pack(fill='x', pady=(12, 0))

    # The hint goes on the first click or keystroke. Bound on the widget, which
    # Tk runs before the Text class's own paste handler, so a pasted dictation
    # never lands behind the hint text.
    def _clear_hint(_event=None):
        if try_box.tag_ranges('hint'):
            try_box.delete('1.0', 'end')
            try_box.tag_delete('hint')
    for sequence in ('<Button-1>', '<Key>', '<<Paste>>'):
        try_box.bind(sequence, _clear_hint, add='+')

    tk.Label(container,
             text="No audio or transcripts ever leave your machine. Promise.",
             bg=BG, fg=FG_DIM, font=('Segoe UI', 9, 'italic')).pack(anchor='w', pady=(14, 0))

    # Opt-in autostart: offered here, off unless the user ticks it. Only shown on
    # platforms where we can actually wire it up (Windows / macOS).
    from . import autostart
    # The variable has to belong to this window. Without a master it goes to the
    # first Tk root in the process, which on macOS is the hidden root from
    # platform/macos/app.py. The tick then landed in this window's interpreter
    # while get() read the hidden root's copy, which stayed False (issue #17).
    autostart_var = tk.BooleanVar(master=root, value=False)
    if autostart.is_supported():
        cb = tk.Checkbutton(
            container, variable=autostart_var,
            text="  Start Whisper Local automatically when I log in",
            bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=('Segoe UI', 9), anchor='w', bd=0, highlightthickness=0,
        )
        cb.pack(anchor='w', pady=(10, 0))

    btn_frame = tk.Frame(container, bg=BG)
    btn_frame.pack(fill='x', pady=(14, 0))

    dismissed = False

    # Button and window-close both land here. quit() only stops mainloop();
    # the root is destroyed once mainloop() has returned (see below).
    def _done():
        nonlocal dismissed
        dismissed = True
        mark_first_run_complete()
        if autostart_var.get():
            try:
                autostart.enable()
            except Exception as e:
                logger.debug(f"Autostart enable from welcome failed: {e}")
        root.quit()

    tk.Button(btn_frame, text="Got it — let's dictate",
              command=_done, bg=ACCENT, fg='white', relief='flat',
              padx=22, pady=6, font=('Segoe UI', 10, 'bold')).pack(side='right')

    root.protocol("WM_DELETE_WINDOW", _done)
    if shutdown_event is not None:
        root.after(_SHUTDOWN_POLL_MS, _close_on_shutdown, root, shutdown_event)

    # Quit first, destroy after. mainloop() runs until no Tk roots are left on
    # this thread, and on macOS the platform layer keeps a hidden root alive on
    # the main thread for the whole process (platform/macos/app.py). There,
    # destroy() alone leaves mainloop() blocked forever after "Got it", hanging
    # every first launch. quit() ends the loop regardless of other roots.
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass
    if dismissed and on_close:
        on_close()
