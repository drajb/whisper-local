# transcript_log.py
# Append-only journal of every successful transcription. Backs the
# `--history` browser window so users can search their dictation history.
# Separate from `stats.jsonl` (which only stores metadata) — this file
# contains the actual transcribed text and is auto-rotated to keep the
# last ~2000 entries.

import datetime
import json
import logging
import threading
from pathlib import Path

from .utils import get_user_app_data_path

logger = logging.getLogger(__name__)

# Newline-delimited JSON — one transcript per line.
_LOG_FILE = 'transcripts.jsonl'
_MAX_ENTRIES = 2000

# Serialise append + rotate. Continuous mode and rapid voice commands can fire
# deliveries back-to-back from different threads; without this an append could
# interleave with the read-truncate-rewrite rotation and drop or corrupt lines.
_write_lock = threading.Lock()


# The history.retention_days setting as an int, or None for "keep". A
# hand-edited value ("30 days", "") must not take the journal down with it.
def _retention(value):
    if value is None or value == '':
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days >= 0 else None


# Called from state_manager._transcription_pipeline after every successful
# delivery. Silent no-op for empty text (which means a failed/silent recording).
# `retention_days`: None keeps everything (capped at _MAX_ENTRIES), 0 stores
# nothing at all, and N drops entries older than N days on the next write.
def record_transcript(text: str, app: str = '', duration_s: float = 0.0, retention_days=None):
    if not text:
        return
    days = _retention(retention_days)
    if days == 0:
        return
    entry = {
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'text': text,
        'app': app,
        'duration_s': round(duration_s, 2),
        'chars': len(text),
    }
    path = Path(get_user_app_data_path()) / _LOG_FILE
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            _maybe_rotate(path, days)
    except Exception as e:
        logger.debug(f"Transcript log write failed: {e}")


# Reads the journal back into a list of dicts, newest-first. Used by the
# history window. Silently skips malformed lines so a single corrupted entry
# doesn't break the whole UI.
def load_transcripts() -> list:
    path = Path(get_user_app_data_path()) / _LOG_FILE
    entries = []
    if not path.exists():
        return entries
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('text'):
                        entries.append(obj)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning(f"Failed to load transcripts: {e}")
    return list(reversed(entries))


# An entry's timestamp for the age cut-off. A malformed line reads as the
# beginning of time, so the age prune also sweeps it out.
def _stamp(line: str) -> str:
    try:
        return str(json.loads(line).get('timestamp') or '')
    except (ValueError, AttributeError):
        return ''


# Cap the journal at roughly _MAX_ENTRIES, and when a retention is set, drop
# entries older than that many days. We allow the count to grow to 1.2× before
# truncating to amortise the cost — counting lines on every write would dominate
# the actual transcription work.
def _maybe_rotate(path: Path, retention_days=None):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        changed = False
        if retention_days:
            cutoff = (datetime.datetime.now()
                      - datetime.timedelta(days=retention_days)).isoformat(timespec='seconds')
            kept = [line for line in lines if _stamp(line) >= cutoff]
            if len(kept) != len(lines):
                lines, changed = kept, True
        if len(lines) > _MAX_ENTRIES * 1.2:
            lines, changed = lines[-_MAX_ENTRIES:], True
        if changed:
            path.write_text(('\n'.join(lines) + '\n') if lines else '', encoding='utf-8')
    except Exception:
        pass
