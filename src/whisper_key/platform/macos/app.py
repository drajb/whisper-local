# platform/macos/app.py
# macOS app lifecycle: runs an NSApplication as an accessory (no Dock icon) and
# pumps its run loop, which Cocoa requires on the MAIN thread — the reason the
# platform layer exposes thread requirements at all.
# Windows mirror: platform/windows/app.py (no such constraint).
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSEventMaskAny, NSDefaultRunLoopMode
from Foundation import NSDate, NSObject, NSOperationQueue, NSThread

class AppDelegate(NSObject):
    def applicationSupportsSecureRestorableState_(self, app):
        return True

_delegate = None

# ── Tk coexistence (issue #14) ────────────────────────────────────────────────
# Tk on macOS draws through Cocoa, so a Tk window can only be created on the
# main thread, which here belongs to the NSApplication run loop. Windows that
# normally run on a worker thread (level overlay, first-run welcome) read this
# through utils.tk_requires_main_thread() and adapt.
TK_MAIN_THREAD_ONLY = True

# Held for the process lifetime; see _preload_tk().
_tk_preload_root = None


# Let Tk create the shared NSApplication before pyobjc does.
#
# Whoever calls sharedApplication() first decides its class. Tk 9 installs its
# own subclass (TKApplication) and its drawing code then calls selectors only
# that subclass has, e.g. -macOSVersion from GetRGBA. If pyobjc gets there
# first, NSApp is a plain NSApplication and the first later tk.Tk() dies on an
# unrecognised selector. That's an NSException, not a Python exception, so no
# try/except can catch it: the process aborts with exit 134.
#
# The hidden root must stay alive: destroying the last Tk root tears down Tk's
# app-level state, and the next tk.Tk() would start the fight again. Best effort
# only. Without Tk (or without a display) we fall back to a plain NSApplication
# and the Tk windows skip themselves.
def _preload_tk():
    global _tk_preload_root
    try:
        import tkinter as tk
        _tk_preload_root = tk.Tk()
        _tk_preload_root.withdraw()
    except Exception:
        _tk_preload_root = None


def setup():
    global _delegate
    _preload_tk()  # must run before sharedApplication() below
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _delegate = AppDelegate.alloc().init()
    app.setDelegate_(_delegate)

def getch():
    import tty
    import termios
    import sys
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

# Run fn on the main thread, because Cocoa requires every AppKit mutation to
# happen there.
#
# This is not a nicety. Through macOS 26 a background-thread menu-bar write
# only logged a warning; macOS 27 made it a hard trap — BSServiceMainRunLoopQueue's
# barrier assertion raises SIGTRAP and the process dies instantly (issue #13).
# SIGTRAP is not a Python exception, so no try/except at the call site can save
# it; the write simply must not happen off-thread.
#
# Dispatch is async on purpose: the callers are the recording thread and the
# level monitor, and neither may block on the UI. Blocks queued before the run
# loop starts simply run once it does. run_event_loop() below pumps
# NSDefaultRunLoopMode, which services the main queue.
def run_on_ui_thread(fn):
    if NSThread.isMainThread():
        fn()
        return
    NSOperationQueue.mainQueue().addOperationWithBlock_(fn)


def run_event_loop(shutdown_event):
    app = NSApplication.sharedApplication()
    while not shutdown_event.is_set():
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny,
            NSDate.dateWithTimeIntervalSinceNow_(0.1),
            NSDefaultRunLoopMode,
            True
        )
        if event:
            app.sendEvent_(event)
