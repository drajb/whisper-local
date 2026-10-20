# stats.py
# Usage metrics only — character counts, durations and the app dictated into,
# appended to `stats.jsonl`. Deliberately stores NO transcript text (that lives
# in transcript_log.py) so this file stays safe to share in a bug report. Backs
# `--stats`, the once-a-day summary notification, and streak tracking. Writes are
# lock-serialised because deliveries can land from several threads at once.

import datetime
import json
import logging
import threading
from collections import Counter
from pathlib import Path
from typing import Optional

from .utils import get_user_app_data_path

STATS_FILE = "stats.jsonl"
DAILY_NOTIFY_MARKER = "stats-last-notify.txt"

# Serialise appends — back-to-back deliveries (continuous mode) can write from
# different threads. Append-only, so this is lighter than transcript_log's lock.
_write_lock = threading.Lock()

GREEN = "\033[32m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Fallback for stats.typing_wpm: a typical average typing speed.
DEFAULT_TYPING_WPM = 40
CHARS_PER_WORD = 5

logger = logging.getLogger(__name__)


# Time it would have taken to type `words` at `typing_wpm`, minus the time
# spent speaking them. Never negative: a slow dictation saved nothing.
def _minutes_saved(words: int, speaking_seconds: float, typing_wpm: float) -> float:
    return max(0.0, (words / typing_wpm) - (speaking_seconds / 60))


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def record_transcription(char_count: int, duration_seconds: float, app: Optional[str] = None):
    if char_count <= 0:
        return
    try:
        entry = {
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'chars': char_count,
            'duration_s': round(float(duration_seconds), 2),
            'app': (app or '').lower(),
        }
        path = Path(get_user_app_data_path()) / STATS_FILE
        with _write_lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.debug(f"Stats record failed: {e}")


def maybe_show_daily_summary(notify_callback, typing_wpm: float = DEFAULT_TYPING_WPM) -> Optional[str]:
    today = datetime.date.today().isoformat()
    marker = Path(get_user_app_data_path()) / DAILY_NOTIFY_MARKER

    try:
        last = marker.read_text(encoding='utf-8').strip()
    except OSError:
        last = ''

    if last == today:
        return None

    path = Path(get_user_app_data_path()) / STATS_FILE
    if not path.exists():
        try:
            marker.write_text(today, encoding='utf-8')
        except OSError:
            pass
        return None

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    chars = 0
    count = 0
    seconds = 0.0
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get('ts', '').startswith(yesterday):
                    count += 1
                    chars += _safe_int(entry.get('chars'))
                    seconds += _safe_float(entry.get('duration_s'))
    except OSError:
        return None

    try:
        marker.write_text(today, encoding='utf-8')
    except OSError:
        pass

    if count == 0:
        return None

    words = chars // CHARS_PER_WORD
    minutes_saved = _minutes_saved(words, seconds, typing_wpm)
    msg = f"Yesterday: {count} dictations, {words:,} words, ~{minutes_saved:.0f} min saved"
    try:
        notify_callback(msg)
    except Exception:
        pass
    return msg


def export_transcripts(dest: str) -> int:
    path = Path(get_user_app_data_path()) / STATS_FILE
    if not path.exists():
        print("No transcription history to export.")
        return 1

    dest_path = Path(dest).expanduser().resolve()
    fmt = dest_path.suffix.lower()
    if fmt not in ('.txt', '.md', '.csv'):
        print(f"Unknown extension '{fmt}'. Use .txt, .md, or .csv")
        return 1
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Could not create destination directory: {e}")
        return 1

    entries = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _seconds(entry):
        return _safe_float(entry.get('duration_s'))

    def _chars(entry):
        return _safe_int(entry.get('chars'))

    try:
        if fmt == '.csv':
            import csv
            with open(dest_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'app', 'duration_seconds', 'characters'])
                for e in entries:
                    writer.writerow([e.get('ts', ''), e.get('app', ''),
                                     _seconds(e), _chars(e)])
        elif fmt == '.md':
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write("# Whisper Local — Transcription Log\n\n")
                f.write("| Time | App | Seconds | Chars |\n|---|---|---|---|\n")
                for e in entries:
                    f.write(f"| {e.get('ts','')} | {e.get('app','')} | {_seconds(e):.1f} | {_chars(e)} |\n")
        else:
            with open(dest_path, 'w', encoding='utf-8') as f:
                for e in entries:
                    f.write(f"{e.get('ts','')}\t{e.get('app','')}\t{_seconds(e):.1f}s\t{_chars(e)} chars\n")
    except OSError as e:
        print(f"Write failed: {e}")
        return 1

    print(f"Exported {len(entries)} entries to {dest_path}")
    return 0


# `--stats`: renders the whole journal as a console report — totals, time saved
# (vs a typing-speed baseline), busiest apps, and the current/longest streak.
# Returns a process exit code so main() can hand it straight to sys.exit().
def show_stats(typing_wpm: float = DEFAULT_TYPING_WPM) -> int:
    path = Path(get_user_app_data_path()) / STATS_FILE
    if not path.exists():
        print("No transcription history yet — go dictate something!")
        return 0

    entries = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        print(f"Could not read {path}: {e}")
        return 1

    if not entries:
        print("Stats file is empty.")
        return 0

    total = len(entries)
    total_chars = sum(_safe_int(e.get('chars')) for e in entries)
    total_seconds = sum(_safe_float(e.get('duration_s')) for e in entries)
    words = total_chars // CHARS_PER_WORD
    minutes_speaking = total_seconds / 60
    saved_minutes = _minutes_saved(words, total_seconds, typing_wpm)
    avg_wpm = (words / minutes_speaking) if minutes_speaking > 0 else 0

    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    two_weeks_ago = (today - datetime.timedelta(days=14)).isoformat()
    last_week = [e for e in entries if e.get('ts', '') >= week_ago]
    prior_week = [e for e in entries if two_weeks_ago <= e.get('ts', '') < week_ago]
    by_app = Counter(e.get('app') or '<unknown>' for e in last_week or entries)

    active_days = set()
    for e in entries:
        ts = e.get('ts', '')
        if ts:
            active_days.add(ts[:10])
    streak, longest_streak = _compute_streaks(active_days, today)

    print(f"\n{BOLD}Whisper Local — Insights{RESET}\n{'=' * 26}\n")
    print(f"{BOLD}Lifetime{RESET}")
    print(f"  {GREEN}{BOLD}{total:>7,}{RESET}  transcriptions")
    print(f"  {GREEN}{BOLD}{total_chars:>7,}{RESET}  characters delivered")
    print(f"  {GREEN}{BOLD}{words:>7,}{RESET}  words")
    print(f"  {GREEN}{BOLD}{avg_wpm:>7.0f}{RESET}  average WPM ({DIM}{minutes_speaking:.1f} min spoken{RESET})")
    print(f"  {GREEN}{BOLD}{saved_minutes:>7.1f}{RESET}  minutes saved vs typing at {typing_wpm:g} wpm")

    print(f"\n{BOLD}Streaks{RESET}")
    print(f"  {GREEN}{BOLD}{streak:>7}{RESET}  current day streak")
    print(f"  {GREEN}{BOLD}{longest_streak:>7}{RESET}  longest day streak")
    print(f"  {GREEN}{BOLD}{len(active_days):>7}{RESET}  total active days")

    print(f"\n{BOLD}This week vs last week{RESET}")
    this_words = sum(_safe_int(e.get('chars')) for e in last_week) // CHARS_PER_WORD
    prior_words = sum(_safe_int(e.get('chars')) for e in prior_week) // CHARS_PER_WORD
    delta = this_words - prior_words
    delta_pct = (delta / prior_words * 100) if prior_words > 0 else None
    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
    if delta_pct is not None:
        pct_color = GREEN if delta >= 0 else "\033[31m"
        delta_str += f"  ({pct_color}{delta_pct:+.0f}%{RESET})"
    print(f"  This week:  {len(last_week):>4} sessions, {this_words:>5,} words")
    print(f"  Last week:  {len(prior_week):>4} sessions, {prior_words:>5,} words")
    print(f"  Δ words:    {delta_str}")

    if by_app:
        print(f"\n{BOLD}Top apps (last 7 days){RESET}")
        for app, count in by_app.most_common(8):
            label = app if app else '<unknown>'
            bar_width = max(1, int(count * 30 / by_app.most_common(1)[0][1]))
            bar = '█' * bar_width
            print(f"  {count:>4}  {GREEN}{bar}{RESET}{DIM} {label}{RESET}")

    if entries:
        first_ts = entries[0].get('ts', '?')
        last_ts = entries[-1].get('ts', '?')
        print(f"\n{DIM}First entry: {first_ts}{RESET}")
        print(f"{DIM}Latest entry: {last_ts}{RESET}\n")

    return 0


def _compute_streaks(active_days: set, today: datetime.date) -> tuple:
    if not active_days:
        return 0, 0
    sorted_days = sorted(active_days)
    longest = 1
    current = 1
    for i in range(1, len(sorted_days)):
        prev = datetime.date.fromisoformat(sorted_days[i - 1])
        curr = datetime.date.fromisoformat(sorted_days[i])
        if (curr - prev).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1

    if today.isoformat() in active_days:
        cs = 1
        d = today
        while True:
            d -= datetime.timedelta(days=1)
            if d.isoformat() in active_days:
                cs += 1
            else:
                break
        return cs, longest
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    if yesterday in active_days:
        cs = 1
        d = today - datetime.timedelta(days=1)
        while True:
            d -= datetime.timedelta(days=1)
            if d.isoformat() in active_days:
                cs += 1
            else:
                break
        return cs, longest
    return 0, longest
