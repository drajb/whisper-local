# corrections.py
# Persistence for post-transcription corrections (postprocess.replacements) —
# the backing store for the history window's one-click "Fix this everywhere...".
# Writes user_settings.yaml directly (same pattern as dictionary.py) so callers
# don't need a live ConfigManager; the running app hot-reloads the postprocess
# section on file change, so a correction takes effect on the next dictation.

import logging
from pathlib import Path
from typing import List

from ruamel.yaml import YAML

from .utils import get_user_app_data_path

logger = logging.getLogger(__name__)
USER_SETTINGS = "user_settings.yaml"


def _settings_path() -> Path:
    return Path(get_user_app_data_path()) / USER_SETTINGS


# Read the current correction list from user_settings.yaml (empty if unset).
def list_replacements() -> List[dict]:
    path = _settings_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = YAML().load(f) or {}
        items = (data.get('postprocess') or {}).get('replacements') or []
        return [dict(i) for i in items if isinstance(i, dict)]
    except Exception as e:
        logger.warning(f"Could not read replacements: {e}")
        return []


# Append a correction (from_text → to_text). Returns False for empty input, a
# no-op fix (from == to), or an existing identical rule; True once persisted.
def add_replacement(from_text: str, to_text: str,
                    whole_word: bool = True, case_sensitive: bool = False) -> bool:
    from_text = (from_text or '').strip()
    to_text = (to_text or '')
    if not from_text or from_text == to_text:
        return False

    path = _settings_path()
    yaml = YAML()
    if path.exists():
        with open(path, encoding='utf-8') as f:
            data = yaml.load(f) or {}
    else:
        data = {}

    postprocess = data.setdefault('postprocess', {})
    current = list(postprocess.get('replacements') or [])

    # Skip an exact duplicate, but allow updating the target for an existing
    # "from" by replacing that entry rather than stacking a second. Match the
    # "from" case-INsensitively (matching is case-insensitive by default), so
    # adding "teh" when "Teh" already exists updates it instead of creating a
    # second rule that double-fires on the same text.
    for existing in current:
        if isinstance(existing, dict) and str(existing.get('from', '')).lower() == from_text.lower():
            if str(existing.get('to', '')) == to_text:
                return False
            existing['from'] = from_text
            existing['to'] = to_text
            _write(path, yaml, data)
            return True

    entry = {'from': from_text, 'to': to_text}
    if not whole_word:
        entry['whole_word'] = False
    if case_sensitive:
        entry['case_sensitive'] = True
    current.append(entry)
    postprocess['replacements'] = current
    _write(path, yaml, data)
    return True


# Removes the correction whose "from" matches (case-insensitively). Returns
# True when one was removed.
def remove_replacement(from_text: str) -> bool:
    path = _settings_path()
    if not path.exists():
        return False
    yaml = YAML()
    with open(path, encoding='utf-8') as f:
        data = yaml.load(f) or {}
    postprocess = data.get('postprocess') or {}
    current = list(postprocess.get('replacements') or [])
    target = (from_text or '').strip().lower()
    kept = [r for r in current
            if not (isinstance(r, dict) and str(r.get('from', '')).strip().lower() == target)]
    if len(kept) == len(current):
        return False
    postprocess['replacements'] = kept
    data['postprocess'] = postprocess
    _write(path, yaml, data)
    return True


def _write(path: Path, yaml: YAML, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)
    logger.info("Saved a post-transcription correction to user_settings.yaml")
