# dictation_cleanup.py
# Deterministic, offline clean-up passes that make spoken text read like typed
# text: backtracking ("at 2, actually 3" → "at 3"), stutter removal ("I I think"
# → "I think"), spoken lists ("first … second …" → a numbered list) and the
# lowercase used by the "very casual" style. Pure functions, all O(n).
# Wired into the pipeline by text_postprocess.postprocess().

import re

# Characters that end a clause. A backtrack never reaches across one, so a
# correction can only replace something in the sentence it was spoken in.
_CLAUSE_BOUNDARIES = ('.', '!', '?', '\n')


# =============================================================================
# Backtrack: "at 2, actually 3" → "at 3"
# =============================================================================

# Spoken self-corrections. Only a cue followed by a TYPED value (number, time,
# weekday, month) is acted on: "I actually like it" has no value after the cue,
# so it is left alone. That restriction is what makes this safe to run without
# an LLM — prose that merely contains "actually" or "sorry" never changes.
DEFAULT_BACKTRACK_CUES = ('actually', 'i mean', 'no wait', 'wait no', 'sorry',
                          'make that', 'or rather', 'correction')

_NUMBER_WORDS = ('zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
                 'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|'
                 'thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand')
_WEEKDAYS = 'monday|tuesday|wednesday|thursday|friday|saturday|sunday'
_MONTHS = ('january|february|march|april|may|june|july|august|september|october|'
           'november|december')

# One pattern per value class. A replacement only ever swaps a value for one of
# the same class, so "Tuesday at 2, actually 3" changes the 2, never Tuesday.
_VALUE_CLASSES = {
    'number': (r'\$?\d+(?:[.,:]\d+)?%?(?:\s?(?:am|pm|a\.m\.|p\.m\.))?'
               r'|\b(?:' + _NUMBER_WORDS + r')\b'),
    'weekday': r'\b(?:' + _WEEKDAYS + r')\b',
    'month': r'\b(?:' + _MONTHS + r')\b',
}
_VALUE_RES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _VALUE_CLASSES.items()}
_ANY_VALUE = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in _VALUE_CLASSES.items())


def _compile_backtrack(cues) -> re.Pattern:
    alternation = '|'.join(re.escape(c) for c in sorted(cues, key=len, reverse=True))
    # cue, then any hugging commas/periods/spaces, then the replacement value.
    return re.compile(r'\b(?:' + alternation + r')\b[ \t,.]*(?:' + _ANY_VALUE + r')',
                      re.IGNORECASE)


# Replaces the value a cue corrects. For each "<cue> <new value>", the nearest
# earlier value of the same class in the same clause is swapped for the new
# one and the cue is dropped. With nothing to correct, the text is untouched.
# Each backward search covers a span no other match revisits, so this is O(n).
def apply_backtrack(text: str, cues=DEFAULT_BACKTRACK_CUES) -> str:
    cues = [c.strip() for c in (cues or ()) if isinstance(c, str) and c.strip()]
    if not text or not cues:
        return text
    pattern = _compile_backtrack(cues)
    pieces = []
    cursor = 0
    changed = False
    for match in pattern.finditer(text):
        if match.start() < cursor:
            continue
        value_class = match.lastgroup
        new_value = match.group(value_class)
        segment = text[cursor:match.start()]
        boundary = max(segment.rfind(c) for c in _CLAUSE_BOUNDARIES)
        clause_start = boundary + 1
        previous = None
        for candidate in _VALUE_RES[value_class].finditer(segment, clause_start):
            previous = candidate
        if previous is None:
            # Nothing earlier to correct: keep the cue and value as spoken, and
            # move past them so later matches never rescan this span.
            pieces.append(text[cursor:match.end()])
            cursor = match.end()
            continue
        between = segment[previous.end():].rstrip(' \t,.')
        rest = text[match.end():]
        # "2 kids, sorry, 3 kids": the words after the old value are repeated
        # after the new one, so keep only one copy.
        if between.strip() and rest.lstrip(' \t,.').lower().startswith(between.strip().lower()):
            between = ''
        pieces.append(segment[:previous.start()])
        pieces.append(new_value)
        pieces.append(between)
        cursor = match.end()
        changed = True
    if not changed:
        return text
    pieces.append(text[cursor:])
    return re.sub(r'[ \t]{2,}', ' ', ''.join(pieces)).strip()


# =============================================================================
# Repeated words: "I I think" → "I think"
# =============================================================================

# Doubled words that are real English, or deliberate emphasis. Never collapsed.
_LEGIT_REPEATS = frozenset({'had', 'that', 'is', 'very', 'so', 'no', 'bye', 'yeah',
                            'really', 'ha', 'haha', 'go', 'tsk', 'knock', 'there'})

# A word (letters first, so numbers like "11 11" are left alone) followed by
# one or more copies of itself, separated by spaces or a comma.
_REPEAT_RE = re.compile(r"\b([^\W\d_][\w']*)(?:[ \t]*,?[ \t]+\1\b)+", re.IGNORECASE)


def remove_repeated_words(text: str) -> str:
    if not text:
        return text

    def keep_first(match):
        word = match.group(1)
        return match.group(0) if word.lower() in _LEGIT_REPEATS else word
    return _REPEAT_RE.sub(keep_first, text)


# =============================================================================
# Spoken lists: "first, milk. second, eggs" → "1. Milk\n2. Eggs"
# =============================================================================

_ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth',
             'sixth', 'seventh', 'eighth', 'ninth', 'tenth')
_CARDINALS = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')
_MARKER_VALUES = {}
for _i, (_ord, _card) in enumerate(zip(_ORDINALS, _CARDINALS), start=1):
    _MARKER_VALUES[_ord] = _MARKER_VALUES[_ord + 'ly'] = _i
    _MARKER_VALUES[_card] = _MARKER_VALUES['number ' + _card] = _i
    _MARKER_VALUES[str(_i)] = _i

# A list marker must open a clause (start of text, or after punctuation or a
# break, optionally followed by "and"/"then") AND be followed by punctuation.
# That's how Whisper writes a spoken list ("First, … Second, …"), and it keeps
# ordinary prose like "one of the two options" from ever looking like a list.
_MARKER_RE = re.compile(
    r'(?:^|(?<=[.!?;:,\n]))[ \t]*(?:(?:and|then)[ \t]+)?'
    r'(?P<marker>' + '|'.join(sorted((re.escape(k) for k in _MARKER_VALUES), key=len, reverse=True)) + r')'
    r'[ \t]*[,:.)][ \t]*',
    re.IGNORECASE,
)


def _clean_item(item: str) -> str:
    item = item.strip().rstrip(' \t,;.')
    item = re.sub(r'[ \t,]+(?:and|then)$', '', item, flags=re.IGNORECASE).strip()
    return item[:1].upper() + item[1:] if item else item


# Rewrites a spoken, counted list as a list. Only fires on a run of at least
# `min_items` markers counting up from one; anything else is returned as-is.
def apply_list_formatting(text: str, style: str = 'numbered', min_items: int = 2) -> str:
    if not text:
        return text
    run = []
    for match in _MARKER_RE.finditer(text):
        value = _MARKER_VALUES[match.group('marker').lower()]
        if value == len(run) + 1:
            run.append(match)
        elif value == 1 and len(run) < max(2, min_items):
            run = [match]  # a fresh "first" before a real run formed: restart
    if len(run) < max(2, min_items):
        return text

    lead_in = text[:run[0].start()].strip().rstrip(',;')
    items = []
    for index, match in enumerate(run):
        end = run[index + 1].start() if index + 1 < len(run) else len(text)
        items.append(_clean_item(text[match.end():end]))
    if not all(items):
        return text  # a marker with nothing after it isn't a list item

    bullet = (lambda n: '- ') if style == 'bullets' else (lambda n: f'{n}. ')
    lines = [bullet(n) + item for n, item in enumerate(items, start=1)]
    if lead_in:
        if not lead_in.endswith((':', '.', '!', '?')):
            lead_in += ':'
        return lead_in + '\n' + '\n'.join(lines)
    return '\n'.join(lines)


# =============================================================================
# Lowercase ("very casual" style)
# =============================================================================

_WORD_RE = re.compile(r"[^\W\d_][\w'’-]*")


# Lowercases ordinary capitalized words only. ALLCAPS (acronyms, "I"), mixed
# case (iPhone, McDonald) and every term in `protected` (the user's corrections
# and replacement targets) keep their casing, so the terms people have taught
# the app are never undone by a style.
def apply_lowercase(text: str, protected=()) -> str:
    if not text:
        return text
    protected_lower = {p.lower() for p in protected if isinstance(p, str)}

    def lower_word(match):
        word = match.group(0)
        if word.lower() in protected_lower:
            return word
        if len(word) > 1 and word[0].isupper() and word[1:] == word[1:].lower():
            return word.lower()
        return word
    return _WORD_RE.sub(lower_word, text)
