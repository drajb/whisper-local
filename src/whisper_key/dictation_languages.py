# dictation_languages.py
# "Languages you speak", like Wispr Flow's Dictation Languages. With
# `whisper.language: auto`, Whisper picks from all ~100 languages, and on a
# short or accented clip it sometimes picks one the user never speaks (English
# heard as Welsh or Malay). Listing the languages you dictate in restricts the
# choice to those. Speech that is clearly in some other language is reported,
# so the user can add it, instead of being silently forced into the wrong one.
# Pure functions; both engines (faster-whisper and whisper.cpp) use them.

import re

# How sure detection must be before speech outside the list is called out.
# Below this the top guess is noise, and nagging about it would be worse than
# saying nothing.
OUTSIDER_CONFIDENCE = 0.7

# Names for the notice. Anything missing is shown by its code.
LANGUAGE_NAMES = {
    'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
    'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'pl': 'Polish',
    'ru': 'Russian', 'uk': 'Ukrainian', 'ja': 'Japanese', 'zh': 'Chinese',
    'ko': 'Korean', 'hi': 'Hindi', 'ar': 'Arabic', 'tr': 'Turkish',
    'sv': 'Swedish', 'da': 'Danish', 'no': 'Norwegian', 'fi': 'Finnish',
    'cs': 'Czech', 'el': 'Greek', 'he': 'Hebrew', 'id': 'Indonesian',
    'ms': 'Malay', 'vi': 'Vietnamese', 'th': 'Thai', 'ro': 'Romanian',
    'hu': 'Hungarian', 'cy': 'Welsh', 'ca': 'Catalan', 'bn': 'Bengali',
    'ta': 'Tamil', 'ur': 'Urdu', 'fa': 'Persian', 'tl': 'Tagalog',
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


# The configured list as clean codes. Accepts a YAML list or the Settings
# window's "en, fr" string; drops blanks, "auto" and duplicates, keeps order.
def normalize_languages(value) -> list:
    if value is None:
        return []
    items = re.split(r'[,\s]+', value) if isinstance(value, str) else list(value)
    codes = []
    for item in items:
        code = str(item).strip().lower()
        if code and code != 'auto' and re.fullmatch(r'[a-z]{2,3}', code) and code not in codes:
            codes.append(code)
    return codes


# Chooses the language to transcribe in from detection results.
#   probabilities: {code: probability} over every language the model knows
#   allowed:       the user's languages (normalized)
# Returns (language, outsider): language is the most likely of the allowed
# ones, and outsider is the code of a language outside the list that the
# speech was confidently in (else None), so the caller can offer to add it.
def choose_language(probabilities: dict, allowed: list):
    if not allowed:
        return None, None
    if len(allowed) == 1:
        language = allowed[0]
    else:
        language = max(allowed, key=lambda code: probabilities.get(code, 0.0))
    outsider = None
    if probabilities:
        top = max(probabilities, key=probabilities.get)
        if top not in allowed and probabilities[top] >= OUTSIDER_CONFIDENCE:
            outsider = top
    return language, outsider
