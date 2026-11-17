# dictionary.py
# Manages `whisper.hotwords` — the list of names and jargon Whisper is biased
# toward, which is the cheapest way to fix recurring misrecognitions. Provides
# CLI add/remove/list, a small Tk add-word dialog, and history mining that
# suggests hotwords from words the user actually dictates. Writes
# user_settings.yaml directly (round-trip YAML) so it works without a running app.

import logging
import threading
from pathlib import Path
from typing import List, Optional

from ruamel.yaml import YAML

from .utils import get_user_app_data_path

logger = logging.getLogger(__name__)
USER_SETTINGS = "user_settings.yaml"

# Singleton guard for the add-word dialog: re-invoking (tray click / repeated
# CLI) raises the existing window instead of stacking new Tk roots + threads.
_dialog_lock = threading.Lock()
_dialog_root = None


def list_hotwords() -> List[str]:
    user_path = Path(get_user_app_data_path()) / USER_SETTINGS
    if not user_path.exists():
        return []
    try:
        with open(user_path, encoding='utf-8') as f:
            data = YAML().load(f) or {}
        return list((data.get('whisper') or {}).get('hotwords') or [])
    except Exception as e:
        logger.warning(f"Could not read hotwords: {e}")
        return []


def add_word(word: str) -> bool:
    word = (word or '').strip()
    if not word:
        return False
    user_path = Path(get_user_app_data_path()) / USER_SETTINGS
    yaml = YAML()
    if user_path.exists():
        with open(user_path, encoding='utf-8') as f:
            data = yaml.load(f) or {}
    else:
        data = {}
    whisper = data.setdefault('whisper', {})
    current = list(whisper.get('hotwords') or [])
    if word in current:
        print(f"   '{word}' already in dictionary")
        return False
    current.append(word)
    whisper['hotwords'] = current
    with open(user_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)
    print(f"   ✓ Added '{word}' to whisper.hotwords ({len(current)} total)")
    return True


def remove_word(word: str) -> bool:
    word = (word or '').strip()
    if not word:
        return False
    user_path = Path(get_user_app_data_path()) / USER_SETTINGS
    if not user_path.exists():
        return False
    yaml = YAML()
    with open(user_path, encoding='utf-8') as f:
        data = yaml.load(f) or {}
    whisper = data.get('whisper') or {}
    current = list(whisper.get('hotwords') or [])
    if word not in current:
        print(f"   '{word}' not found in dictionary")
        return False
    current.remove(word)
    whisper['hotwords'] = current
    data['whisper'] = whisper
    with open(user_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)
    print(f"   ✓ Removed '{word}' from dictionary ({len(current)} left)")
    return True


# =============================================================================
# Hotword suggestions (mined from your own transcription history)
# =============================================================================

import re as _re

# Words that are Capitalized simply because they open a sentence — never good
# hotword candidates on their own, plus a few pronouns/filler that commonly
# start clauses. Kept small on purpose; the user confirms each suggestion.
_SUGGEST_STOPWORDS = {
    'i', 'the', 'a', 'an', 'and', 'but', 'or', 'so', 'then', 'this', 'that',
    'it', 'we', 'you', 'he', 'she', 'they', 'my', 'our', 'your', 'his', 'her',
    'if', 'when', 'while', 'yes', 'no', 'ok', 'okay', 'well', 'also', 'here',
    'there', 'what', 'who', 'how', 'why', 'let', 'please', 'thanks', 'hi', 'hey',
}

# A "namey" token: CamelCase, ALLCAPS acronym, alphanumeric tech term (h264,
# gpt4), or a plain Capitalized word (≥2 letters). Matched case-sensitively.
_NAMEY = _re.compile(r'[A-Za-z][A-Za-z0-9]*')


# Pure, testable core: scan already-spoken transcripts for frequently-used
# proper-noun-ish tokens the model likely gets wrong, biased toward tokens that
# appear MID-sentence (so ordinary sentence-initial capitals don't dominate).
# Returns (word, count) pairs, most frequent first, excluding known hotwords.
def suggest_hotwords(texts: List[str], known: Optional[set] = None,
                     min_count: int = 3, limit: int = 20) -> List[tuple]:
    known_lower = {w.lower() for w in (known or set())}
    counts = {}
    for text in texts:
        if not text:
            continue
        # Split into sentence-ish spans so we can tell "first word" from the rest.
        for span in _re.split(r'[.!?\n]+', text):
            tokens = _NAMEY.findall(span)
            for pos, tok in enumerate(tokens):
                is_namey = (
                    _re.search(r'[A-Z].*[A-Z]', tok)          # CamelCase / ALLCAPS
                    or _re.search(r'\d', tok)                  # has a digit (h264)
                    or (tok[:1].isupper() and pos > 0)         # Capitalized, not 1st word
                )
                if not is_namey or len(tok) < 2:
                    continue
                if tok.lower() in _SUGGEST_STOPWORDS or tok.lower() in known_lower:
                    continue
                counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [(w, c) for w, c in ranked if c >= min_count][:limit]


# Convenience wrapper: mine the on-disk transcript journal against the current
# hotword list. Used by the history window's "Suggest hotwords" action.
def suggest_hotwords_from_history(min_count: int = 3, limit: int = 20) -> List[tuple]:
    from .transcript_log import load_transcripts
    texts = [e.get('text', '') for e in load_transcripts()]
    return suggest_hotwords(texts, known=set(list_hotwords()),
                            min_count=min_count, limit=limit)


def show_dictionary() -> int:
    words = list_hotwords()
    if not words:
        print("Dictionary is empty. Add words with: whisper-local --add-word NAME")
        return 0
    print(f"\nWhisper Local — Dictionary ({len(words)} word{'s' if len(words) != 1 else ''})\n")
    for w in sorted(words, key=str.lower):
        print(f"  • {w}")
    print()
    print("Edit via:")
    print("  whisper-local --add-word NAME")
    print("  whisper-local --remove-word NAME")
    print(f"  Or open {Path(get_user_app_data_path()) / USER_SETTINGS} directly\n")
    return 0


# Opens the small "add a word" dialog (tray item / CLI). Singleton-guarded:
# re-invoking raises the existing window instead of stacking another Tk root and
# thread. `on_added` lets the caller refresh live state (e.g. the running engine's
# hotword list) once a word is actually saved. blocking=True runs the dialog on
# the calling thread, for platforms where Tk must own the main thread (macOS).
def show_add_word_dialog(on_added=None, blocking: bool = False):
    global _dialog_root
    with _dialog_lock:
        try:
            if _dialog_root is not None and _dialog_root.winfo_exists():
                _dialog_root.lift()
                _dialog_root.focus_force()
                return
        except Exception:
            pass

    def run():
        global _dialog_root
        try:
            import tkinter as tk
            from .ui.kit import new_window, Button, Field
        except ImportError:
            logger.info("Tkinter unavailable for add-word dialog")
            return
        try:
            root, kit = new_window("Whisper Local · Add word", size=(420, 250), resizable=False)
            p = kit.p
            with _dialog_lock:
                _dialog_root = root
            try:
                root.attributes('-topmost', True)
            except Exception:
                pass

            outer = kit.frame(root, bg=p['bg'])
            outer.pack(fill='both', expand=True, padx=kit.px(24), pady=kit.px(20))
            kit.label(outer, "Add to your dictionary", 'title').pack(anchor='w')
            kit.label(outer, "Names, jargon, acronyms: anything Whisper mishears.", 'small',
                      'text_muted').pack(anchor='w', pady=(kit.px(2), kit.px(14)))

            # master=root, or the variable binds to the first Tk root in the
            # process (the level overlay, on Windows) and entry_var.get() reads
            # that interpreter's empty copy: "Type a word first" on every Add.
            entry_var = tk.StringVar(master=root)
            status_var = tk.StringVar(master=root, value="")

            def commit(_=None):
                word = entry_var.get().strip()
                if not word:
                    status_var.set("Type a word first.")
                    return
                ok = add_word(word)
                if ok:
                    status_var.set(f"Added “{word}”. It applies from your next dictation.")
                    entry_var.set("")
                    if on_added:
                        try: on_added(word)
                        except Exception: pass
                else:
                    status_var.set(f"“{word}” is already in your dictionary.")

            def close(_=None):
                global _dialog_root
                with _dialog_lock:
                    _dialog_root = None
                try: root.destroy()
                except Exception: pass

            field = Field(outer, kit, entry_var, placeholder="e.g. Kubernetes", on_submit=commit)
            field.pack(fill='x')
            tk.Label(outer, textvariable=status_var, bg=p['bg'], fg=p['text_muted'],
                     font=kit.font('small'), anchor='w').pack(fill='x', pady=(kit.px(8), 0))
            buttons = kit.frame(outer)
            buttons.pack(side='bottom', fill='x')
            Button(buttons, kit, "Add", commit, variant='primary', icon='plus').pack(side='right')
            Button(buttons, kit, "Close", close).pack(side='right', padx=(0, kit.px(8)))
            field.focus()

            root.protocol("WM_DELETE_WINDOW", close)
            root.bind('<Escape>', close)
            root.mainloop()
        except Exception as e:
            logger.warning(f"Add-word dialog failed: {e}")
        finally:
            with _dialog_lock:
                _dialog_root = None

    if blocking:
        run()
        return
    threading.Thread(target=run, daemon=True, name='add-word-dialog').start()
