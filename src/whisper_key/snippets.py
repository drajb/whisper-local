# snippets.py
# Spoken shortcuts that expand inline during normal dictation: say "my
# signature" and the full sign-off is typed. Unlike `type:` voice commands they
# need no separate hotkey. Configured under postprocess.snippets and applied by
# text_postprocess.postprocess(), so they hot-reload with the rest of it.

import datetime
import functools
import logging
import re

logger = logging.getLogger(__name__)

# Punctuation Whisper hangs on a spoken trigger ("My signature.") that the
# expansion replaces. Spaces are left alone so the words around it stay apart.
_TRAILING_PUNCT = '.,!?;:'


# Normalizes the configured list into (trigger, expansion, mode) tuples,
# skipping malformed entries rather than failing a dictation over them.
def _parse(snippets) -> tuple:
    parsed = []
    for item in snippets or ():
        if not isinstance(item, dict):
            continue
        trigger = ' '.join(str(item.get('trigger', '')).split()).lower()
        expansion = item.get('expansion')
        if not trigger or expansion is None:
            continue
        mode = str(item.get('mode', 'anywhere')).lower()
        parsed.append((trigger, str(expansion), 'alone' if mode == 'alone' else 'anywhere'))
    return tuple(parsed)


# One alternation of every "anywhere" trigger, longest first, so "my work
# signature" wins over "my signature". Whitespace inside a trigger matches any
# run of spaces, since Whisper's spacing isn't guaranteed.
@functools.lru_cache(maxsize=8)
def _compile(triggers: tuple):
    if not triggers:
        return None
    parts = [r'[ \t]+'.join(re.escape(w) for w in t.split()) for t in sorted(triggers, key=len, reverse=True)]
    return re.compile(r'\b(?:' + '|'.join(parts) + r')\b[' + re.escape(_TRAILING_PUNCT) + r']*',
                      re.IGNORECASE)


# ${date}, ${time} and ${clipboard} are filled in at expansion time. Anything
# else in the expansion is inserted literally — never treated as a regex.
def _render(expansion: str) -> str:
    if '${' not in expansion:
        return expansion
    now = datetime.datetime.now()
    values = {'${date}': now.strftime('%Y-%m-%d'), '${time}': now.strftime('%H:%M')}
    if '${clipboard}' in expansion:
        try:
            import pyperclip
            values['${clipboard}'] = pyperclip.paste() or ''
        except Exception as e:
            logger.debug(f"Snippet clipboard read failed: {e}")
            values['${clipboard}'] = ''
    for key, value in values.items():
        expansion = expansion.replace(key, value)
    return expansion


# Returns (text, whole_utterance). whole_utterance is True when the dictation
# was nothing but a trigger; the caller then skips sentence tidying (capitals,
# trailing periods) so the expansion lands exactly as written.
def expand_snippets(text: str, snippets) -> tuple:
    parsed = _parse(snippets)
    if not text or not parsed:
        return text, False

    spoken = ' '.join(text.strip().strip(_TRAILING_PUNCT).split()).lower()
    for trigger, expansion, _mode in parsed:
        if spoken == trigger:
            return _render(expansion), True

    lookup = {t: e for t, e, mode in parsed if mode == 'anywhere'}
    pattern = _compile(tuple(lookup))
    if pattern is None:
        return text, False

    text_end = len(text.rstrip())

    def replace(match):
        spoken = match.group(0)
        trigger_text = spoken.rstrip(_TRAILING_PUNCT)
        expansion = lookup.get(' '.join(trigger_text.split()).lower())
        if expansion is None:
            return spoken  # case-folding quirk (e.g. Turkish İ): leave as spoken
        expansion = _render(expansion)
        # Whisper's own punctuation after the trigger is dropped only at the
        # very end; mid-sentence it belongs to the sentence ("…my email, then…").
        if match.end() < text_end:
            expansion += spoken[len(trigger_text):]
        return expansion
    return pattern.sub(replace, text), False
