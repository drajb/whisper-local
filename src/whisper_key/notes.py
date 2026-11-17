# notes.py
# The Notes scratchpad's storage (Wispr Flow's Scratchpad, offline): plain
# Markdown files in %APPDATA%\whisperkey\notes (~/.whisperkey/notes on macOS),
# one per note, so they open in any editor and survive an uninstall of the
# app's settings. Deleting moves a note to notes/trash rather than erasing it.

import datetime
import logging
import re
from pathlib import Path

from .utils import get_user_app_data_path

logger = logging.getLogger(__name__)

NOTES_DIR = 'notes'
TRASH_DIR = 'trash'
TITLE_LENGTH = 60


def notes_dir() -> Path:
    path = Path(get_user_app_data_path()) / NOTES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


# A note's title is its first non-empty line, without Markdown heading marks.
def title_of(text: str) -> str:
    for line in (text or '').splitlines():
        line = line.strip().lstrip('#').strip()
        if line:
            return line[:TITLE_LENGTH] + ('…' if len(line) > TITLE_LENGTH else '')
    return 'Untitled'


# Note ids are file stems: a timestamp, so new notes sort naturally and two
# notes can never collide. Only these characters are ever accepted back.
_ID = re.compile(r'^[0-9A-Za-z_-]{1,64}$')


def _path(note_id: str) -> Path:
    if not _ID.match(note_id or ''):
        raise ValueError(f"Bad note id: {note_id!r}")
    return notes_dir() / f'{note_id}.md'


def new_note_id() -> str:
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    return stamp


# All notes, most recently edited first: [{'id', 'title', 'updated', 'preview'}].
def list_notes() -> list:
    notes = []
    for path in notes_dir().glob('*.md'):
        try:
            text = path.read_text(encoding='utf-8')
            updated = datetime.datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        body = ' '.join(text.split())
        notes.append({'id': path.stem, 'title': title_of(text), 'updated': updated,
                      'preview': body[:120]})
    notes.sort(key=lambda n: n['updated'], reverse=True)
    return notes


def read_note(note_id: str) -> str:
    try:
        return _path(note_id).read_text(encoding='utf-8')
    except OSError:
        return ''


def save_note(note_id: str, text: str):
    _path(note_id).write_text(text, encoding='utf-8')


# Moves the note into notes/trash, so a slip of the mouse is recoverable.
def delete_note(note_id: str) -> bool:
    source = _path(note_id)
    if not source.exists():
        return False
    trash = notes_dir() / TRASH_DIR
    trash.mkdir(exist_ok=True)
    source.replace(trash / source.name)
    return True
