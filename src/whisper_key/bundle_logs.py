# bundle_logs.py
# Creates a redacted diagnostic zip for bug reports. Users running `--bundle-logs`
# (or clicking the tray item) get a single zip they can attach to an issue without
# manually scrubbing usernames or emails. Captures: app.log (last 500 lines),
# rotated logs, user_settings.yaml, last 10 crash dumps from past 7 days, plus
# the live output of --doctor. All paths and emails are regex-redacted before
# writing into the archive.

import datetime
import io
import logging
import re
import sys
import zipfile
from pathlib import Path

from .utils import get_user_app_data_path, get_version

logger = logging.getLogger(__name__)

# Regex pairs applied to every file before zipping. Cover Windows, macOS, and
# Linux user-directory shapes plus a broad RFC-5322-ish email matcher. Anything
# more aggressive risks munging legitimate log content (file paths, IPs, etc.).
_REDACTIONS = [
    (re.compile(r'(C:\\Users\\)([^\\]+)', re.IGNORECASE), r'\1<USER>'),
    # The same path with forward slashes, which URL-style and library logging
    # (file:///C:/Users/...) produce on Windows.
    (re.compile(r'(C:/Users/)([^/]+)', re.IGNORECASE), r'\1<USER>'),
    (re.compile(r'(/Users/)([^/]+)'), r'\1<USER>'),
    (re.compile(r'(/home/)([^/]+)'), r'\1<USER>'),
    # URL credentials (scheme://user:pass@host) — applied to EVERY bundled file, so
    # a custom Ollama endpoint with embedded creds is masked in doctor.txt and logs
    # too, not just user_settings.yaml (which _redact_yaml handles separately).
    (re.compile(r'(\bhttps?://)[^/\s:@]+:[^/\s@]+@', re.IGNORECASE), r'\1<REDACTED>@'),
    # Secret-ish query params.
    (re.compile(r'([?&](?:token|key|api[_-]?key|password|secret|access[_-]?token)=)[^&\s]+',
                re.IGNORECASE), r'\1<REDACTED>'),
    (re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'), '<EMAIL>'),
]

# Config fields that can carry personal or sensitive data. These are scrubbed
# from user_settings.yaml specifically, because the bundle is meant to be
# attached to public GitHub issues. Users routinely put names, codewords, and
# occasionally secrets in hotwords; Ollama endpoints may embed user:pass or
# ?token=; initial_prompt can contain private instructions.
#  - hotwords:        a YAML list, possibly inline [a, b] or block over lines
#  - endpoint:        scalar URL
#  - initial_prompt:  scalar (possibly quoted) string
_YAML_REDACTIONS = [
    # inline list form: hotwords: [a, b, c]
    (re.compile(r'(^\s*hotwords\s*:\s*)\[[^\]]*\]', re.MULTILINE), r'\1[<REDACTED>]'),
    # block list form: hotwords: followed by "- item" lines
    (re.compile(r'(^\s*hotwords\s*:\s*)\n(\s*-\s.*\n?)+', re.MULTILINE), r'\1 [<REDACTED>]\n'),
    (re.compile(r'(^\s*endpoint\s*:\s*).+$', re.MULTILINE), r'\1<REDACTED>'),
    (re.compile(r'(^\s*initial_prompt\s*:\s*).+$', re.MULTILINE), r'\1<REDACTED>'),
]


# Build the diagnostic archive. If output_path is None, write to the cwd with
# a timestamped name. Returns 0 always (the operation is opportunistic — partial
# captures are still useful, so we keep going even if a sub-step fails).
def bundle_logs(output_path: str = None) -> int:
    app_data = Path(get_user_app_data_path())

    if not output_path:
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        output_path = str(Path.cwd() / f"whisper-local-bundle-{stamp}.zip")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    bundled = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('about.txt', _build_about())
        bundled.append('about.txt')

        zf.writestr('doctor.txt', _capture_doctor())
        bundled.append('doctor.txt')

        log_path = app_data / 'app.log'
        if log_path.exists():
            tail = _tail_lines(log_path, 500)
            zf.writestr('app.log', _redact(tail))
            bundled.append('app.log')

        for older in sorted(app_data.glob('app.log.*'))[-2:]:
            try:
                content = older.read_text(encoding='utf-8', errors='replace')
                zf.writestr(older.name, _redact(content))
                bundled.append(older.name)
            except Exception:
                pass

        settings = app_data / 'user_settings.yaml'
        if settings.exists():
            try:
                raw = settings.read_text(encoding='utf-8', errors='replace')
                zf.writestr('user_settings.yaml', _redact_yaml(_redact(raw)))
                bundled.append('user_settings.yaml')
            except Exception:
                pass

        crash_dir = app_data / 'crashes'
        if crash_dir.exists():
            cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
            for crash_file in sorted(crash_dir.iterdir())[-10:]:
                try:
                    mtime = datetime.datetime.fromtimestamp(crash_file.stat().st_mtime)
                    if mtime < cutoff:
                        continue
                    content = crash_file.read_text(encoding='utf-8', errors='replace')
                    zf.writestr(f'crashes/{crash_file.name}', _redact(content))
                    bundled.append(f'crashes/{crash_file.name}')
                except Exception:
                    pass

    print(f"\n📦 Diagnostic bundle written to: {output}")
    print(f"   {len(bundled)} files included:")
    for f in bundled:
        print(f"   • {f}")
    print("\n   ℹ Redacted: usernames in paths, emails, and sensitive settings")
    print("     (hotwords, Ollama endpoint, initial_prompt).")
    print("   ℹ Review the zip before sharing if you've enabled log_transcriptions.\n")
    return 0


# Top-level README inside the zip. Tells the recipient (issue triager, the user,
# or a future you) exactly what's inside and how it was redacted.
def _build_about() -> str:
    return (
        f"Whisper Local diagnostic bundle\n"
        f"Generated: {datetime.datetime.now().isoformat()}\n"
        f"Version: {get_version()}\n"
        f"Python: {sys.version}\n"
        f"Platform: {sys.platform}\n\n"
        "Contents:\n"
        "  about.txt        — this file\n"
        "  doctor.txt       — output of `whisper-local --doctor`\n"
        "  app.log          — last ~500 lines of the main log (redacted)\n"
        "  app.log.N        — last 2 rotated logs if present\n"
        "  user_settings.yaml  — your settings (redacted)\n"
        "  crashes/*        — last 10 crash reports from the past 7 days\n\n"
        "Privacy:\n"
        "  Usernames in paths and any email-shaped strings have been replaced\n"
        "  with placeholders. In user_settings.yaml, hotwords, the Ollama endpoint,\n"
        "  and initial_prompt are masked with <REDACTED>. Transcript text is NOT in\n"
        "  the log unless you enabled `logging.log_transcriptions: true`. Please\n"
        "  review before sharing.\n"
    )


# Runs the existing --doctor flow and captures its stdout into a string so we
# can embed it in the zip without invoking a subprocess.
def _capture_doctor() -> str:
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        from .doctor import run_doctor
        run_doctor()
    except Exception as e:
        buf.write(f"\n[bundle-logs: doctor crashed: {e}]\n")
    finally:
        sys.stdout = old_stdout
    return _redact(buf.getvalue())


# Read just the last N lines of a (potentially huge) log file. Bundles get
# attached to GitHub issues which cap at 25 MB total, so we keep this tight.
def _tail_lines(path: Path, n: int) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return ''.join(lines[-n:])
    except Exception as e:
        return f"[bundle-logs: could not read {path}: {e}]"


# Applied to every file we put in the zip. Order doesn't matter — each pattern
# operates on disjoint regions of typical log content.
def _redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# Extra scrub applied only to user_settings.yaml: masks config fields that may
# hold personal data or secrets (hotwords, Ollama endpoint, initial_prompt).
def _redact_yaml(text: str) -> str:
    for pattern, replacement in _YAML_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text
