# dictation_cleanup.py
# Deterministic, offline clean-up passes that make spoken text read like typed
# text: backtracking ("at 2, actually 3" → "at 3"), stutter removal ("I I think"
# → "I think"), spoken lists ("first … second …" → a numbered list) and the
# lowercase used by the "very casual" style. Pure functions, all O(n).
# Wired into the pipeline by text_postprocess.postprocess().

import re

# Where a sentence ends. A backtrack never reaches across one, so a
# correction can only replace something in the sentence it was spoken in.
# Terminal punctuation only counts when whitespace follows it: the "." in
# "2.5" or "$1.50" is part of a number, not a sentence end.
_SENTENCE_END_RE = re.compile(r'[.!?](?=\s)|\n')


# Index just past the last sentence end in text[start:end], else `start`.
def _clause_start(text: str, start: int, end: int) -> int:
    last = start
    for match in _SENTENCE_END_RE.finditer(text, start, end):
        last = match.end()
    return last


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
    'number': (r'\$?\d+(?:[.,:]\d+)?%?(?:\s?(?:am|pm|a\.m\.|p\.m\.)(?![A-Za-z]))?'
               r'|\b(?:' + _NUMBER_WORDS + r')\b'),
    'weekday': r'\b(?:' + _WEEKDAYS + r')\b',
    'month': r'\b(?:' + _MONTHS + r')\b',
}
_VALUE_RES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _VALUE_CLASSES.items()}
_ANY_VALUE = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in _VALUE_CLASSES.items())

# Punctuation or the end of the text right after the new value: the clearest
# sign it is a finished correction rather than the start of a new phrase.
_VALUE_ENDS_RE = re.compile(r'[ \t]*(?:[.,!?;:]|$)')


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
    if isinstance(cues, str):
        cues = [cues]  # a hand-edited `cues: actually` must not become one cue per letter
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
        clause_start = _clause_start(segment, 0, len(segment))
        previous = None
        for candidate in _VALUE_RES[value_class].finditer(segment, clause_start):
            previous = candidate
        between = segment[previous.end():].rstrip(' \t,.') if previous else ''
        spoken_after = between.strip()
        # Only act on an unmistakable correction. With words between the old
        # value and the cue ("3 movies, actually one of them…"), the new value
        # must either end the phrase or repeat those words ("2 kids, sorry,
        # 3 kids"); otherwise it is prose that happens to follow a cue.
        repeated = False
        if spoken_after:
            upcoming = text[match.end():match.end() + len(spoken_after) + 8].lstrip(' \t,.')
            repeated = upcoming.lower().startswith(spoken_after.lower())
        ends_phrase = _VALUE_ENDS_RE.match(text, match.end()) is not None
        if previous is None or (spoken_after and not repeated and not ends_phrase):
            # Keep the cue and value as spoken, and move past them so later
            # matches never rescan this span.
            pieces.append(text[cursor:match.end()])
            cursor = match.end()
            continue
        if repeated:
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
# copies of itself. The copy must be a whole word, so "you, you're" and
# "can, can't" are different words, not a stutter.
_WORD_END = r"(?![\w'’])"
_REPEAT_RE = re.compile(r"\b([^\W\d_][\w'’]*)(?:[ \t]+\1" + _WORD_END + ")+", re.IGNORECASE)

# The comma form ("We, we should") only at the start of a sentence. Mid-
# sentence a comma usually separates clauses: "whatever you choose, choose
# wisely" is not a stutter.
_SENTENCE_START_REPEAT_RE = re.compile(
    r"(?:^|(?<=[.!?][ \t])|(?<=\n))([^\W\d_][\w'’]*)(?:[ \t]*,[ \t]*\1" + _WORD_END + ")+",
    re.IGNORECASE)


def remove_repeated_words(text: str) -> str:
    if not text:
        return text

    def keep_first(match):
        word = match.group(1)
        return match.group(0) if word.lower() in _LEGIT_REPEATS else word
    text = _SENTENCE_START_REPEAT_RE.sub(keep_first, text)
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
        # .get: case-insensitive regex matches (Turkish "İ", "ſ") can lower()
        # to something that isn't a key; skip those rather than raise.
        value = _MARKER_VALUES.get(' '.join(match.group('marker').lower().split()))
        if value is None:
            continue
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

    # The last item ends at its sentence end; anything said after the list
    # ("…third, bread. See you tonight.") follows it as its own paragraph.
    tail = ''
    last_start = run[-1].end()
    sentence_end = _SENTENCE_END_RE.search(text, last_start)
    if sentence_end and text[sentence_end.end():].strip():
        items[-1] = _clean_item(text[last_start:sentence_end.start()])
        tail = text[sentence_end.end():].strip()
        if not items[-1]:
            return text

    bullet = (lambda n: '- ') if style == 'bullets' else (lambda n: f'{n}. ')
    listed = '\n'.join(bullet(n) + item for n, item in enumerate(items, start=1))
    if lead_in:
        if not lead_in.endswith((':', '.', '!', '?')):
            lead_in += ':'
        listed = lead_in + '\n' + listed
    return listed + ('\n\n' + tail if tail else '')


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
    protected_lower = set()
    for term in protected:
        if isinstance(term, str):
            protected_lower.update(w.lower() for w in term.split())

    def lower_word(match):
        word = match.group(0)
        if word.lower() in protected_lower:
            return word
        if word[:2] in ("I'", 'I’'):
            return word  # I'm / I'll / I've keep their capital I, like "I" does
        if len(word) > 1 and word[0].isupper() and word[1:] == word[1:].lower():
            return word.lower()
        return word
    return _WORD_RE.sub(lower_word, text)
