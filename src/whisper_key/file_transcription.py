# file_transcription.py
# Transcribe an audio or video file (MacWhisper's core feature, offline):
# meetings, voice memos, lectures, interviews. faster-whisper decodes the file
# itself (through PyAV, so mp3/m4a/wav/flac/ogg and mp4/mov/mkv all work) and
# returns timestamped segments, which export as plain text, SRT or WebVTT
# subtitles, or Markdown. Used by the Transcribe page and `--transcribe FILE`.

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma', '.webm')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.mkv', '.avi', '.m4v', '.wmv')
FORMATS = ('txt', 'srt', 'vtt', 'md')


@dataclass
class Segment:
    start: float
    end: float
    text: str


class Cancelled(Exception):
    pass


# ── Export formats ───────────────────────────────────────────────────────────

def _clock(seconds: float, separator: str) -> str:
    millis = int(round(max(0.0, seconds) * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def to_txt(segments) -> str:
    return '\n'.join(s.text.strip() for s in segments if s.text.strip()) + '\n'


def to_srt(segments) -> str:
    blocks = []
    for i, s in enumerate((s for s in segments if s.text.strip()), start=1):
        blocks.append(f"{i}\n{_clock(s.start, ',')} --> {_clock(s.end, ',')}\n{s.text.strip()}\n")
    return '\n'.join(blocks)


def to_vtt(segments) -> str:
    cues = [f"{_clock(s.start, '.')} --> {_clock(s.end, '.')}\n{s.text.strip()}\n"
            for s in segments if s.text.strip()]
    return 'WEBVTT\n\n' + '\n'.join(cues)


# Markdown with a timestamp per paragraph, for notes you skim later.
def to_markdown(segments, title: str = 'Transcript') -> str:
    lines = [f"# {title}", '']
    for s in segments:
        if s.text.strip():
            minutes, secs = divmod(int(s.start), 60)
            lines.append(f"**[{minutes:02d}:{secs:02d}]** {s.text.strip()}")
            lines.append('')
    return '\n'.join(lines)


def render(segments, fmt: str, title: str = 'Transcript') -> str:
    fmt = fmt.lower().lstrip('.')
    if fmt == 'srt':
        return to_srt(segments)
    if fmt == 'vtt':
        return to_vtt(segments)
    if fmt in ('md', 'markdown'):
        return to_markdown(segments, title)
    return to_txt(segments)


# ── Transcription ────────────────────────────────────────────────────────────

def is_supported_file(path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS + VIDEO_EXTENSIONS


# Loads the user's configured model (the same one dictation uses) for a
# one-off file job, in this process.
def load_model(config: dict):
    from faster_whisper import WhisperModel
    from .model_registry import ModelRegistry
    whisper = config.get('whisper', {}) or {}
    registry = ModelRegistry(whisper.get('models'))
    key = whisper.get('model', 'base')
    try:
        source = registry.get_source(key)
    except Exception:
        source = key
    return WhisperModel(source, device=whisper.get('device', 'cpu'),
                        compute_type=whisper.get('compute_type', 'int8'))


# Transcribes `path` and returns its segments. on_progress(fraction, segment)
# is called as each segment arrives; setting `cancel` (a threading.Event)
# stops between segments by raising Cancelled.
def transcribe_file(path, config: dict, model=None, on_progress=None,
                    cancel: threading.Event = None) -> list:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    whisper = config.get('whisper', {}) or {}
    model = model or load_model(config)
    language = whisper.get('language')
    language = None if language in (None, '', 'auto') else language
    hotwords = whisper.get('hotwords') or None
    segments_iter, info = model.transcribe(
        str(path),
        language=language,
        beam_size=int(whisper.get('beam_size', 5) or 5),
        vad_filter=True,                       # skips long silences in recordings
        hotwords=', '.join(hotwords) if hotwords else None,
        task=whisper.get('task', 'transcribe') if whisper.get('task') in ('transcribe', 'translate') else 'transcribe',
    )
    duration = float(getattr(info, 'duration', 0.0) or 0.0)
    segments = []
    for raw in segments_iter:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        segment = Segment(float(raw.start), float(raw.end), raw.text)
        segments.append(segment)
        if on_progress:
            fraction = min(1.0, segment.end / duration) if duration else 0.0
            on_progress(fraction, segment)
    if on_progress:
        on_progress(1.0, None)
    return segments


# `--transcribe FILE`: transcribes, writes FILE.<fmt> next to it (or to
# `output`), prints where. Returns a process exit code.
def run_cli(path: str, fmt: str = 'txt', output: str = None) -> int:
    from .config_manager import ConfigManager
    fmt = (fmt or 'txt').lower()
    if fmt not in FORMATS:
        print(f"Unknown format '{fmt}'. Use one of: {', '.join(FORMATS)}")
        return 2
    source = Path(path).expanduser()
    if not source.is_file():
        print(f"No such file: {source}")
        return 1
    config = ConfigManager(quiet=True).config
    print(f"Transcribing {source.name} with the '{config.get('whisper', {}).get('model', 'base')}' model…")

    def progress(fraction, _segment):
        print(f"\r   {fraction * 100:5.1f}%", end='', flush=True)
    try:
        segments = transcribe_file(source, config, on_progress=progress)
    except Exception as e:
        print(f"\nTranscription failed: {e}")
        return 1
    target = Path(output).expanduser() if output else source.with_suffix(f'.{fmt}')
    target.write_text(render(segments, fmt, title=source.stem), encoding='utf-8')
    print(f"\n✓ Wrote {target}")
    return 0
