# update_check.py
# Once-per-day check against the GitHub Releases API for newer versions.
# OFF by default — users must opt in via `update_check.enabled: true`.
# No audio or transcript data is ever transmitted; the only thing leaving
# the machine is the User-Agent header with the current app version.

import datetime
import json
import logging
import threading
from pathlib import Path

from .utils import get_user_app_data_path, get_version

logger = logging.getLogger(__name__)

# Public unauthenticated endpoint; 60 req/hour rate limit per IP is plenty
# for a once-a-day per-user check.
_API_URL = 'https://api.github.com/repos/drajb/whisper-local/releases/latest'

# We rate-limit ourselves to one check per calendar day by writing the date here.
_LAST_CHECK_FILE = 'last_update_check.txt'


# Called from main.py at startup. Hard short-circuits when disabled — no
# thread is spawned, no network state is touched.
def maybe_check_for_update(notify_callback, config: dict):
    if not (config or {}).get('enabled', False):
        return
    threading.Thread(
        target=_check_in_background,
        args=(notify_callback,),
        daemon=True,
        name='update-check',
    ).start()


# Runs on a daemon thread so startup isn't delayed by network latency.
# Writes the current date to the rate-limit file regardless of outcome so a
# transient network failure doesn't cause us to retry every launch.
def _check_in_background(notify_callback):
    last_file = Path(get_user_app_data_path()) / _LAST_CHECK_FILE
    today = datetime.date.today().isoformat()

    if last_file.exists():
        try:
            if last_file.read_text(encoding='utf-8').strip() == today:
                return
        except Exception:
            pass

    try:
        import urllib.request
        current = get_version()
        req = urllib.request.Request(
            _API_URL,
            headers={'User-Agent': f'whisper-local/{current}'},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        latest_tag = data.get('tag_name', '').lstrip('v')
        if latest_tag and _is_newer(latest_tag, current):
            notify_callback(f"Update available: v{latest_tag} — {_how_to_update()}")
        try:
            last_file.write_text(today, encoding='utf-8')
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"Update check failed: {e}")


# The right upgrade step for how this copy was installed. Telling someone on
# the standalone .exe to run pip sends them to a terminal they don't have.
def _how_to_update() -> str:
    import os
    if os.environ.get('PYAPP'):
        return "download the new whisper-local.exe from github.com/drajb/whisper-local/releases"
    return "run: pip install --upgrade whisper-local"


# Compare two semver strings. Strips any pre-release/build suffix first — notably
# get_version() returns "X.Y.Z-dev" for source/dev installs, which would otherwise
# make int() throw and silently disable update checks forever.
def _is_newer(latest: str, current: str) -> bool:
    try:
        def _parts(v):
            core = v.lstrip('v').split('-')[0].split('+')[0]
            nums = [int(x) for x in core.split('.')[:3]]
            nums += [0] * (3 - len(nums))  # pad short versions (e.g. "1.2" -> 1.2.0)
            return tuple(nums)
        return _parts(latest) > _parts(current)
    except Exception:
        return False
