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
        from .ui.kit import new_window, Button, Toggle, Card
    except ImportError:
        logger.warning("Tkinter unavailable — skipping welcome window")
        if on_close:
            on_close()
        return

    root, kit = new_window("Welcome to Whisper Local", size=(580, 640), resizable=False)
    p = kit.p
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass

    container = kit.frame(root, bg=p['bg'])
    container.pack(fill='both', expand=True, padx=kit.px(32), pady=kit.px(26))

    head = kit.frame(container)
    head.pack(fill='x')
    tk.Label(head, image=kit.brand_mark(48), bg=p['bg']).pack(side='left')
    titles = kit.frame(head)
    titles.pack(side='left', padx=(kit.px(14), 0))
    kit.label(titles, "Welcome to Whisper Local", 'title').pack(anchor='w')
    kit.label(titles, "Free, private dictation that never leaves your computer.", 'small',
              'text_muted').pack(anchor='w', pady=(kit.px(2), 0))

    items = [
        ("1", f"Hold {hotkey_label} anywhere, speak, let go.",
         "Your words appear at the cursor in any app: chat, email, code, the browser."),
        ("2", "Everything else lives in the tray icon.",
         "Click it to open Whisper Local: history, notes, your dictionary and settings. "
         "On Windows, drag it out of the ^ overflow so it's always one click away."),
        ("3", "If something's off, it can tell you why.",
         "Help & docs → Run diagnostics checks the mic, permissions, model and hotkeys."),
    ]
    steps = Card(container, kit, padding=8)
    steps.pack(fill='x', pady=(kit.px(22), 0))
    for i, (num, title, body) in enumerate(items):
        if i:
            tk.Frame(steps.body, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(10))
        row = tk.Frame(steps.body, bg=p['surface'])
        row.pack(fill='x', padx=kit.px(10), pady=kit.px(10))
        badge = tk.Canvas(row, width=kit.px(28), height=kit.px(28), bg=p['surface'], highlightthickness=0)
        kit.round_rect(badge, 0, 0, kit.px(28), kit.px(28), kit.px(14), p['accent_soft'])
        badge.create_text(kit.px(14), kit.px(14), text=num, fill=p['accent'], font=kit.font('small_strong'))
        badge.pack(side='left', anchor='n')
        text = tk.Frame(row, bg=p['surface'])
        text.pack(side='left', fill='x', expand=True, padx=(kit.px(12), 0))
        kit.label(text, title, 'body_strong', bg=p['surface'], wrap=True).pack(fill='x')
        kit.label(text, body, 'small', 'text_muted', bg=p['surface'], wrap=True).pack(fill='x', pady=(kit.px(2), 0))

    # Somewhere to try it before the window closes. Seeing their own words land
    # here is the moment it clicks for most people, and it proves the hotkey,
    # the mic and the paste all work while the instructions are still on
    # screen. The hotkeys are already live by the time this window opens.
    try_card = Card(container, kit, padding=12, fill=p['field'])
    try_card.pack(fill='x', pady=(kit.px(16), 0))
    try_box = tk.Text(try_card.body, height=3, bg=p['field'], fg=p['text'], insertbackground=p['accent'],
                      bd=0, highlightthickness=0, font=kit.font('body'), wrap='word',
                      selectbackground=p['selection'])
    try_box.insert('1.0', f"Try it now: click here, hold {hotkey_label}, say something, let go.")
    try_box.tag_add('hint', '1.0', 'end')
    try_box.tag_config('hint', foreground=p['text_faint'])
    try_box.pack(fill='x')

    # The hint goes on the first click or keystroke. Bound on the widget, which
    # Tk runs before the Text class's own paste handler, so a pasted dictation
    # never lands behind the hint text.
    def _clear_hint(_event=None):
        if try_box.tag_ranges('hint'):
            try_box.delete('1.0', 'end')
            try_box.tag_delete('hint')
    for sequence in ('<Button-1>', '<Key>', '<<Paste>>'):
        try_box.bind(sequence, _clear_hint, add='+')

    # Opt-in autostart: offered here, off unless the user turns it on. Only shown
    # on platforms where we can actually wire it up (Windows / macOS).
    from . import autostart
    # The variable has to belong to this window. Without a master it goes to the
    # first Tk root in the process, which on macOS is the hidden root from
    # platform/macos/app.py. The tick then landed in this window's interpreter
    # while get() read the hidden root's copy, which stayed False (issue #17).
    autostart_var = tk.BooleanVar(master=root, value=False)
    bottom = kit.frame(container)
    bottom.pack(side='bottom', fill='x')
    if autostart.is_supported():
        toggle_row = kit.frame(container)
        toggle_row.pack(side='bottom', fill='x', pady=(0, kit.px(16)))
        Toggle(toggle_row, kit, autostart_var).pack(side='left')
        kit.label(toggle_row, "Start Whisper Local when I sign in", 'body').pack(side='left', padx=(kit.px(10), 0))
    kit.label(bottom, "No audio or text ever leaves this computer.", 'caption', 'text_faint').pack(side='left')

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

    Button(bottom, kit, "Let's dictate", _done, variant='primary', size='lg').pack(side='right')

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
