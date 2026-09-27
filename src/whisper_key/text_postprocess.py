# text_postprocess.py
# The text-shaping stage between Whisper and delivery. Runs an ordered pipeline
# over the raw transcript: spoken editing ("scratch that", "actually 3") →
# inline voice formatting (say "comma") → deterministic smart formatting
# (times/emails/URLs) → user corrections → fillers, lists, style → snippets →
# casing/punctuation tidying → optional Ollama polish. Every stage is opt-in via
# the `postprocess` config section and pure except the final Ollama call, so
# output stays predictable and fully offline.

import functools
import json
import logging
import re
import urllib.error
import urllib.request

from . import dictation_cleanup
from .snippets import expand_snippets
from .styles import resolve_style

logger = logging.getLogger(__name__)

_SENTENCE_END = ('.', '!', '?', '"', "'", ')', ']', ':', ';', ',', '…')

INLINE_FORMAT_REPLACEMENTS = [
    (r'\bnew paragraph\b', '\n\n'),
    (r'\bnew line\b', '\n'),
    # Trailing space baked in so absorb mode doesn't glue words together
    # ("hello comma world" → "hello, world", not "hello,world"). With absorb OFF
    # the extra space is normalized away by the cleanup pass below.
    (r'\b(?:full stop|period)\b', '. '),
    (r'\bcomma\b', ', '),
    (r'\bquestion mark\b', '? '),
    (r'\bexclamation (?:mark|point)\b', '! '),
    (r'\bcolon\b', ': '),
    (r'\bsemi[- ]?colon\b', '; '),
    (r'\bopen (?:quote|quotes)\b', ' "'),
    (r'\bclose (?:quote|quotes)\b', '" '),
    (r'\bopen paren(?:thesis)?\b', ' ('),
    (r'\bclose paren(?:thesis)?\b', ') '),
    (r'\bopen bracket\b', ' ['),
    (r'\bclose bracket\b', '] '),
    (r'\bdash\b', ' — '),
    (r'\bhyphen\b', '-'),
]


# A toggle's on/off value. ruamel reads YAML 1.2, where `no` / `off` are
# strings, and bool("no") is True, so a hand-written `list_formatting: no`
# would switch the feature ON. Only real true values and yes/on/true count.
def _on(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ('true', 'yes', 'on', '1')
    return value is True or (isinstance(value, int) and not isinstance(value, bool) and value != 0)


def postprocess(text: str, config: dict) -> str:
    if not text or not config:
        return text

    # A named style is shorthand for a set of the toggles below. The app-rule
    # path resolves it beforehand (see app_rules.effective_postprocess_config)
    # and drops the key; this covers every other caller.
    if config.get('style'):
        config = {**config, **resolve_style(config['style'], config)}

    # Spoken editing commands ("scratch that") operate on the raw dictation flow,
    # so they run first — before any symbol/format rewriting.
    if _on(config.get('voice_editing')):
        text = _apply_voice_editing(text)

    # "at 2, actually 3" → "at 3". Same raw-flow reasoning as voice editing.
    backtrack_cfg = config.get('backtrack')
    if isinstance(backtrack_cfg, dict) and _on(backtrack_cfg.get('enabled')):
        cues = backtrack_cfg.get('cues') or dictation_cleanup.DEFAULT_BACKTRACK_CUES
        if isinstance(cues, str):
            cues = [cues]
        text = dictation_cleanup.apply_backtrack(text, cues)

    if _on(config.get('remove_repeated_words')):
        text = dictation_cleanup.remove_repeated_words(text)

    if _on(config.get('inline_formatting')):
        text = _apply_inline_formatting(text, config)

    # Deterministic, offline symbol formatting (times / emails / URLs). Each
    # sub-toggle is off by default; only run the pass if at least one is on.
    # The isinstance guard matters: a hand-edited `smart_formatting: true`
    # instead of a mapping must not take down the whole transcription.
    smart_cfg = config.get('smart_formatting')
    if isinstance(smart_cfg, dict) and any(smart_cfg.get(k) for k in ('times', 'emails', 'urls')):
        text = _apply_smart_formatting(text, smart_cfg)

    # Both correction passes run late — after formatting, so they win over it,
    # but before Ollama so the LLM sees already-corrected text.
    #
    # `corrections` is the vocabulary map (one canonical term, many misheard
    # variants). It runs first so a specific `replacements` entry can still
    # override a broad vocabulary mapping.
    text = _apply_corrections(text, config.get('corrections'))

    # `replacements` is the per-entry form (whole_word / case_sensitive /
    # regex) and is what the history window's "Fix this everywhere" writes.
    replacements = config.get('replacements')
    if isinstance(replacements, (list, tuple)) and replacements:
        text = _apply_replacements(text, replacements)

    if _on(config.get('strip_filler_words')):
        text = _strip_fillers(text)

    became_list = False
    if _on(config.get('list_formatting')):
        before = text
        text = dictation_cleanup.apply_list_formatting(
            text, style=str(config.get('list_style', 'numbered')))
        became_list = text != before

    # Before snippets, so a style never lowercases a snippet's expansion; the
    # user's corrected terms keep their casing too.
    if _on(config.get('lowercase')):
        text = dictation_cleanup.apply_lowercase(text, _protected_terms(config))

    # A dictation that was only a snippet trigger is delivered exactly as the
    # snippet is written: no casing or punctuation tidying, no LLM polish.
    text, whole_snippet = expand_snippets(text, config.get('snippets'))
    if whole_snippet:
        return text

    if _on(config.get('strip_trailing_period')):
        text = _strip_trailing_period(text)

    if _on(config.get('capitalize_first')):
        text = _capitalize_first(text)

    # A list's last item takes no closing period.
    if _on(config.get('ensure_punctuation')) and not became_list:
        text = _ensure_punctuation(text)

    # Same defensive shape check as smart_formatting above — a malformed
    # `ollama:` value must degrade to "no polish", not raise mid-dictation.
    ollama_cfg = config.get('ollama')
    if isinstance(ollama_cfg, dict) and _on(ollama_cfg.get('enabled')):
        polished = _ollama_polish(text, ollama_cfg)
        if polished:
            text = polished

    return text


# Terms the user has taught the app (corrections and replacement targets),
# whose casing the lowercase style must leave alone.
def _protected_terms(config: dict) -> list:
    terms = []
    corrections = config.get('corrections')
    if isinstance(corrections, dict):
        terms.extend(str(k) for k in corrections)
    for item in config.get('replacements') or ():
        if isinstance(item, dict) and item.get('to'):
            terms.extend(str(item['to']).split())
    return terms


def _strip_trailing_period(text: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return text
    trailing = text[len(stripped):]
    if stripped.endswith('.') and not stripped.endswith('..'):
        return stripped[:-1] + trailing
    return text


# Build the (pattern, replacement) list to apply. With no user config, this is
# just the built-in English map. A user can supply their own phrases via
# postprocess.inline_formatting_replacements — essential for non-English dictation
# (e.g. Polish), where Whisper won't emit the English trigger words. By default a
# user list REPLACES the English defaults; set inline_formatting_extend: true to
# append to them instead. User phrases are matched as whole, case-insensitive,
# regex-escaped words, so no regex injection or ReDoS is possible.
def _resolve_inline_replacements(config: dict):
    cfg = config or {}
    custom = cfg.get('inline_formatting_replacements') or []

    entries = []
    if not custom or cfg.get('inline_formatting_extend', False):
        entries.extend(INLINE_FORMAT_REPLACEMENTS)

    for item in custom:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get('phrase', '')).strip()
        if not phrase:
            continue
        replacement = str(item.get('replacement', ''))
        entries.append((r'\b' + re.escape(phrase) + r'\b', replacement))
    return entries


# Characters a cue word "absorbs" from either side. Newline is deliberately
# excluded so "new paragraph"/"new line" breaks survive a neighbouring cue.
_ABSORB_CHARS = ' \t,.'


# Replace each cue match together with the punctuation/whitespace hugging it.
#
# Written as find-then-expand rather than wrapping the pattern in `[ \t,.]*…`
# runs. That regex form is O(n²): once an earlier cue has been swapped for ", "
# the text is largely punctuation, and the engine re-scans a long leading run
# from every start position only to fail (measured ~6.5 s on a long dictation).
# Here `finditer` locates the cue in one linear pass and each side is expanded
# over a run that no other match can revisit, so the whole pass is O(n).
def _absorb_sub(pattern: str, replacement: str, text: str) -> str:
    pieces = []
    cursor = 0
    limit = len(text)
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        if match.start() < cursor:
            continue  # inside a region a previous match already absorbed
        start = match.start()
        while start > cursor and text[start - 1] in _ABSORB_CHARS:
            start -= 1
        end = match.end()
        while end < limit and text[end] in _ABSORB_CHARS:
            end += 1
        pieces.append(text[cursor:start])
        pieces.append(replacement)  # inserted literally — never a regex template
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


def _apply_inline_formatting(text: str, config: dict = None) -> str:
    cfg = config or {}
    # When you SPEAK a cue word, Whisper also inserts its own punctuation around it
    # based on prosody (e.g. "hello comma world" → "Hello, comma, world."), so a bare
    # swap leaves artifacts ("Hello,, world."). With absorb on, each phrase also eats
    # the runs of commas/periods/whitespace hugging it, and the replacement's own
    # spacing wins — so define replacements like ", " or " → ". Off by default.
    absorb = cfg.get('inline_formatting_absorb_punctuation', False)
    for pattern, replacement in _resolve_inline_replacements(cfg):
        if absorb:
            text = _absorb_sub(pattern, replacement, text)
        else:
            # Literal replacement via a function repl: avoids re interpreting \1,
            # \g<>, or stray backslashes in user-provided replacement strings.
            text = re.sub(pattern, lambda _m, r=replacement: r, text, flags=re.IGNORECASE)
    text = re.sub(r' +([.,!?:;])', r'\1', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


# =============================================================================
# Spoken editing commands
# =============================================================================

# "scratch that" / "delete that" / "strike that" — Wispr-style self-correction.
# Matches ONLY the command itself. Deliberately no leading `[^.!?\n]*?` clause
# scan: a lazy prefix like that makes re expand it one character at a time from
# every start position, which is O(n²) and froze the pipeline for ~7 s on a long
# dictation (measured). The clause is found instead by a linear backward search
# in _apply_voice_editing.
# Trailing class is [ \t,.]* (NOT \s*): it must not eat the newline after the
# command, or "first scratch that\nsecond" would pull "second" onto the first line.
_VOICE_EDIT_CMD = re.compile(
    r'\b(?:scratch|delete|strike)\s+that\b[ \t,.]*',
    flags=re.IGNORECASE,
)

# Sentence terminators that bound how far back a "scratch that" erases.
_CLAUSE_BOUNDARIES = ('.', '!', '?', '\n')


def _apply_voice_editing(text: str) -> str:
    # For each command, erase back to the start of the clause it belongs to (just
    # after the previous terminator), never past the end of an earlier deletion.
    # Each backward search covers a disjoint span, so the whole pass is O(n).
    pieces = []
    cursor = 0
    for match in _VOICE_EDIT_CMD.finditer(text):
        if match.start() < cursor:
            continue  # already inside a region an earlier command removed
        segment = text[cursor:match.start()]
        last_boundary = max(segment.rfind(c) for c in _CLAUSE_BOUNDARIES)
        keep_until = cursor + last_boundary + 1 if last_boundary >= 0 else cursor
        pieces.append(text[cursor:keep_until])
        # Emit a single space in place of the removed clause+command, so the
        # separator after a preceding sentence survives ("flight. scratch that go"
        # → "flight. go", not "flight.go").
        pieces.append(' ')
        cursor = match.end()
    pieces.append(text[cursor:])

    cleaned = ''.join(pieces)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)         # no trailing space before a break
    cleaned = re.sub(r'\s+([.,!?;:])', r'\1', cleaned)   # no space before punctuation
    return cleaned.strip()


# =============================================================================
# Deterministic smart formatting (times / emails / URLs)
# =============================================================================

# Known TLDs we're willing to collapse from speech. Kept deliberately small and
# common so "<word> dot <tld>" only fires on things that really look like a
# domain, not ordinary prose ("connect the dots" has no trailing TLD).
_TLDS = 'com|org|net|io|dev|co|edu|gov|ai|app|uk|us|ca|de|fr'

# "3pm" / "3 p.m." / "3:30 pm" → "3 PM" / "3:30 PM". Requires a leading digit,
# so it can't fire inside words like "spam".
# The trailing (?![A-Za-z0-9]) excludes a following letter OR digit, so "pm2.5"
# (an air-quality token) and "3 pm2" aren't mangled into a time.
_TIME_RE = re.compile(
    r'\b(\d{1,2}(?::\d{2})?)\s*([ap])\.?\s*m\.?(?![A-Za-z0-9])',
    flags=re.IGNORECASE,
)

# "john at example dot com" → "john@example.com". The "at ... dot <tld>" shape is
# a strong signal, so this rarely fires on prose ("meet me at noon" has no
# "dot <tld>"). Emails run before URLs so the domain isn't collapsed twice.
_EMAIL_RE = re.compile(
    r'\b([A-Za-z0-9][A-Za-z0-9._%+-]*)\s+at\s+([A-Za-z0-9][A-Za-z0-9.-]*)\s+dot\s+(' + _TLDS + r')\b',
    flags=re.IGNORECASE,
)

# "example dot com" → "example.com". Opt-in; can occasionally fire on
# "<word> dot <tld>" in prose, which is why it's its own toggle.
_URL_RE = re.compile(
    r'\b([A-Za-z0-9][A-Za-z0-9-]*)\s+dot\s+(' + _TLDS + r')\b',
    flags=re.IGNORECASE,
)


def _apply_smart_formatting(text: str, cfg: dict) -> str:
    if cfg.get('emails'):
        text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}@{m.group(2)}.{m.group(3).lower()}", text)
    if cfg.get('urls'):
        text = _URL_RE.sub(lambda m: f"{m.group(1)}.{m.group(2).lower()}", text)
    if cfg.get('times'):
        text = _TIME_RE.sub(lambda m: f"{m.group(1)} {m.group(2).upper()}M", text)
    return text


# =============================================================================
# Vocabulary corrections (one canonical term, many misheard variants)
# =============================================================================

# Config shape:  corrections: {CAPEX: [cap x, copics], MySQL: [my sequel]}
#
# Complements `replacements` rather than duplicating it. This shape is the
# ergonomic one when Whisper mangles the SAME term several different ways —
# you write the correct spelling once and list what you actually hear back.
# `replacements` stays the per-entry form (whole_word / case_sensitive / regex)
# and is what the history window's "Fix this everywhere" writes.
#
# Every variant compiles into ONE alternation applied in a single pass, so cost
# is independent of how many corrections you define. Sorting longest-first
# matters for correctness, not just speed: with "cap" and "cap x" both defined,
# the longer variant must win, otherwise the shorter one shadows it and leaves a
# dangling "x". Matching is case-insensitive; the replacement is inserted with
# the exact casing the user wrote.
@functools.lru_cache(maxsize=8)
def _compile_corrections(items: tuple):
    lookup = {}
    for canonical, variants in items:
        for variant in variants:
            variant = str(variant).strip()
            if variant:
                lookup[variant.casefold()] = str(canonical)
    if not lookup:
        return None, {}
    longest_first = sorted(lookup, key=len, reverse=True)
    pattern = '|'.join(re.escape(v) for v in longest_first)
    return re.compile(rf'\b(?:{pattern})\b', re.IGNORECASE), lookup


# Normalise the config into a hashable tuple so the compiled regex can be
# cached across dictations. A malformed section degrades to 'no corrections'
# rather than raising mid-pipeline.
def _corrections_key(corrections) -> tuple:
    if not isinstance(corrections, dict):
        return ()
    items = []
    for canonical, variants in corrections.items():
        if variants is None:
            continue
        if isinstance(variants, (str, int, float)):
            variants = [variants]
        if not isinstance(variants, (list, tuple)):
            continue
        items.append((str(canonical), tuple(str(v) for v in variants)))
    return tuple(items)


def _apply_corrections(text: str, corrections) -> str:
    key = _corrections_key(corrections)
    if not key:
        return text
    regex, lookup = _compile_corrections(key)
    if regex is None:
        return text
    return regex.sub(lambda m: lookup.get(m.group().casefold(), m.group()), text)


# =============================================================================
# User corrections (post-transcription replacements)
# =============================================================================

# Literal, whole-word, case-insensitive text corrections applied after
# transcription. Each item: {from, to, whole_word=true, case_sensitive=false,
# regex=false}. Literal replacement text is inserted verbatim (no backref
# interpretation), and a bad regex is skipped rather than crashing the pipeline.
def _apply_replacements(text: str, items: list) -> str:
    for item in items:
        if not isinstance(item, dict):
            continue
        frm = str(item.get('from', ''))
        if not frm.strip():
            continue
        to = str(item.get('to', ''))
        flags = 0 if item.get('case_sensitive', False) else re.IGNORECASE
        if item.get('regex', False):
            pattern = frm
        else:
            escaped = re.escape(frm)
            # Edge-aware boundaries, not \b…\b: \b needs a word char on the inside
            # edge, so a `from` like "C++", "C#" or ".NET" (non-word edge) would
            # never match. (?<!\w)…(?!\w) still enforces whole-word for normal
            # terms ("cat" won't hit "category") while allowing punctuation edges.
            pattern = r'(?<!\w)' + escaped + r'(?!\w)' if item.get('whole_word', True) else escaped
        try:
            text = re.sub(pattern, lambda _m, r=to: r, text, flags=flags)
        except re.error as e:
            logger.debug(f"Skipping invalid replacement {frm!r}: {e}")
    return text


# Remove filler words without touching layout. Both the trailing run and the
# whitespace collapse are restricted to spaces and tabs ([ \t]), never \s:
# \s matches newlines, so the old version ate the line and paragraph breaks
# that inline formatting had just inserted — "like\n\nBravo" lost its
# paragraph, and any surviving \n\n was then collapsed to a single space by
# the \s{2,} pass (issue #9). Structural whitespace is someone else's output,
# and this filter has no business rewriting it.
def _strip_fillers(text: str) -> str:
    pattern = re.compile(
        r'\b(um|uh|erm|uhm|like|you know)\b[,]?[ \t]*',
        flags=re.IGNORECASE,
    )
    cleaned = pattern.sub('', text)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    # A filler removed at the start of a line leaves the indent behind; drop
    # spaces that now sit against a break, but keep the break itself.
    cleaned = re.sub(r'[ \t]+(\r?\n)', r'\1', cleaned)
    cleaned = re.sub(r'(\r?\n)[ \t]+', r'\1', cleaned)
    return cleaned.strip() or text


def _capitalize_first(text: str) -> str:
    stripped = text.lstrip()
    if not stripped:
        return text
    leading = text[: len(text) - len(stripped)]
    return leading + stripped[0].upper() + stripped[1:]


def _ensure_punctuation(text: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return text
    trailing = text[len(stripped):]
    if stripped.endswith(_SENTENCE_END):
        return text
    return stripped + '.' + trailing


def _ollama_polish(text: str, cfg: dict) -> str:
    endpoint = cfg.get('endpoint', 'http://localhost:11434').rstrip('/')
    model = cfg.get('model', 'llama3.2')
    prompt_template = cfg.get(
        'prompt',
        "Polish this dictation. Fix punctuation and capitalization only. Do not change wording or add anything. Output ONLY the polished text:\n\n{text}",
    )
    timeout = float(cfg.get('timeout', 5))

    if '{text}' in prompt_template:
        final_prompt = prompt_template.replace('{text}', text)
    else:
        final_prompt = f"{prompt_template}\n\n{text}"

    payload = {
        'model': model,
        'prompt': final_prompt,
        'stream': False,
    }

    try:
        req = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        polished = (data.get('response') or '').strip()
        if polished:
            logger.debug("Ollama polish applied")
            return polished
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning(f"Ollama post-edit unavailable ({e}); using raw transcript")
    return ''
