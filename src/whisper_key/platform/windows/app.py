# platform/windows/app.py
# Windows app-lifecycle bits: single-keypress input (msvcrt) and the thread
# requirements the main loop must respect. Windows needs no special main-thread
# handling, so these are mostly trivial.
# macOS mirror: platform/macos/app.py (NSApplication run loop, which DOES
# require the main thread).
import msvcrt

# Tk windows each run their own root on a worker thread, which Windows allows.
# macOS mirror is True: Tk there must live on the main thread.
TK_MAIN_THREAD_ONLY = False


def setup():
    pass

def run_event_loop(shutdown_event):
    while not shutdown_event.wait(timeout=0.1):
        pass

def getch():
    return msvcrt.getwch()


# Windows has no main-thread requirement for tray/UI objects, so this just
# calls through. It exists so callers never have to branch on platform.
# macOS mirror marshals onto the main thread — see the note there.
def run_on_ui_thread(fn):
    fn()
