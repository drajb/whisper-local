# window_launcher.py
# Opens the app's small Tk windows (fallback, cheat sheet, add-word, history) in
# a child process on platforms where Tk must own the main thread (macOS). In the
# running app that thread is busy with the menu-bar loop, and a Tk root on a
# worker thread aborts the whole process (issue #14). Elsewhere it's a no-op.

import json
import logging
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

# The --window names main.py accepts; keep in sync with its argparse choices.
WINDOW_NAMES = ('cheat-sheet', 'add-word', 'fallback', 'history')

# The open child per window name, so a second tray click doesn't stack another
# copy (the in-process windows have the same singleton guard). Fallback windows
# are exempt: each one carries a different transcript.
_open_children = {}
_children_lock = threading.Lock()


# ── Parent side ──────────────────────────────────────────────────────────────

# Returns True when the window has been handed to a child process, meaning the
# caller must NOT also open it in-process. Returns False where in-process Tk is
# fine (Windows), so callers keep their normal path. A failed spawn still
# returns True: falling back to in-process Tk on macOS would abort the app.
def open_in_child_process(name: str, payload: dict = None) -> bool:
    from .utils import tk_requires_main_thread
    if not tk_requires_main_thread():
        return False
    if name not in WINDOW_NAMES:
        raise ValueError(f"Unknown window: {name}")
    with _children_lock:
        running = _open_children.get(name)
        if running is not None and running.poll() is None:
            logger.info(f"The {name} window is already open")
            return True
    command = [sys.executable, '-m', 'whisper_key.main', '--window', name]
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE)
        # Over a pipe rather than argv, so a transcript never shows up in `ps`.
        child.stdin.write(json.dumps(payload or {}).encode('utf-8'))
        child.stdin.close()
    except Exception as e:
        logger.error(f"Could not open the {name} window: {e}")
        return True
    if name != 'fallback':
        with _children_lock:
            _open_children[name] = child
    # Reap the child when it closes so it doesn't linger as a zombie.
    threading.Thread(target=child.wait, daemon=True, name=f'{name}-window-reaper').start()
    return True


# ── Child side ───────────────────────────────────────────────────────────────

# Reads the JSON payload the parent piped in. A missing or malformed payload is
# treated as empty; each window decides whether it can run without one.
def read_payload(stream) -> dict:
    try:
        data = json.loads((stream.read() if stream else '') or '{}')
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


# Entry point for `--window NAME`: runs one window on this (main) thread and
# returns the process exit code once it closes.
def run_window(name: str, stream) -> int:
    payload = read_payload(stream)
    if name == 'cheat-sheet':
        from .cheat_sheet import show_cheat_sheet
        show_cheat_sheet(blocking=True)
    elif name == 'add-word':
        from .dictionary import show_add_word_dialog
        show_add_word_dialog(blocking=True)
    elif name == 'history':
        from .history_window import show_history
        show_history(blocking=True)
    elif name == 'fallback':
        transcript = payload.get('transcript') or ''
        if not transcript:
            return 1
        from .fallback_window import FallbackWindow
        FallbackWindow()._run_window(transcript, payload.get('reason') or '',
                                     bool(payload.get('allow_clipboard', True)))
    else:
        return 2
    return 0
