# styles.py
# Named writing styles (formal, casual, very casual, verbatim) that bundle the
# post-processing toggles into one choice, like Wispr Flow's per-app Styles.
# A style can be set globally (postprocess.style) or per app rule (style: …);
# users can redefine the presets or add their own under postprocess.styles.

import logging

logger = logging.getLogger(__name__)

# Unknown style names already reported, so a typo is logged once, not on
# every dictation.
_warned_unknown = set()

# The toggles a style may set. Anything else in a style entry is ignored, so a
# style can never switch on something like Ollama or change delivery.
STYLE_KEYS = ('capitalize_first', 'ensure_punctuation', 'strip_trailing_period',
              'inline_formatting', 'lowercase', 'list_formatting')

STYLE_PRESETS = {
    # Full sentences: capital first letter, always ends with punctuation.
    'formal': {'capitalize_first': True, 'ensure_punctuation': True,
               'strip_trailing_period': False, 'lowercase': False},
    # Chat: capitalized, but no stiff trailing period.
    'casual': {'capitalize_first': True, 'ensure_punctuation': False,
               'strip_trailing_period': True, 'lowercase': False},
    # Texting: all lowercase except acronyms and your own terms, no final period.
    'very_casual': {'capitalize_first': False, 'ensure_punctuation': False,
                    'strip_trailing_period': True, 'lowercase': True},
    # No automatic capitals, periods or lists, for code editors and terminals.
    # Spoken "new line" / "comma" still work, and so do your corrections.
    'verbatim': {'capitalize_first': False, 'ensure_punctuation': False,
                 'strip_trailing_period': False, 'lowercase': False,
                 'list_formatting': False},
}


# The user's style table: built-in presets, with postprocess.styles entries
# replacing or adding to them.
def available_styles(postprocess_cfg: dict = None) -> dict:
    styles = {name: dict(values) for name, values in STYLE_PRESETS.items()}
    custom = (postprocess_cfg or {}).get('styles')
    if isinstance(custom, dict):
        for name, values in custom.items():
            if isinstance(values, dict):
                styles[str(name).lower()] = {k: bool(v) for k, v in values.items() if k in STYLE_KEYS}
    return styles


# The toggles a style name stands for. Empty (and logged) for an unknown name,
# so a typo in a rule leaves formatting as it was rather than failing.
def resolve_style(name, postprocess_cfg: dict = None) -> dict:
    if not name:
        return {}
    key = str(name).strip().lower().replace(' ', '_').replace('-', '_')
    styles = available_styles(postprocess_cfg)
    if key not in styles:
        if key not in _warned_unknown:
            _warned_unknown.add(key)
            logger.warning(f"Unknown style '{name}' — known styles: {', '.join(sorted(styles))}")
        return {}
    return dict(styles[key])
