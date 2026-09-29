import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LF = chr(10)  # newline, for readable assertions about layout
sys.path.insert(0, str(ROOT / "src"))


# ── Faking the platform layer ─────────────────────────────────────────────────
# whisper_key.platform imports the OS backend (pyobjc / pywin32 / PIL), which
# the lean CI env doesn't install, so a test that needs a module importing it
# swaps in a stand-in for the WHOLE package. Faking only a submodule is not
# enough: `from .platform import app` still runs the real package __init__.
# The real platform modules are never evicted either. On macOS, re-running
# platform/macos/app.py redefines an Objective-C class, which pyobjc refuses.
_PLATFORM_SUBMODULES = ('hotkeys', 'keyboard', 'foreground', 'app', 'console',
                        'permissions', 'icons', 'paths', 'instance_lock', 'gpu')


# A module whose every attribute is a MagicMock unless set explicitly.
def _stand_in_module(name):
    import types
    import unittest.mock as mock

    class StandIn(types.ModuleType):
        __path__ = []

        def __getattr__(self, attr):
            if attr.startswith('__'):
                raise AttributeError(attr)
            value = mock.MagicMock(name=f'{self.__name__}.{attr}')
            setattr(self, attr, value)
            return value
    return StandIn(name)


# sys.modules entries for a stand-in platform package. `app_attrs` are set on
# the fake platform.app (TK_MAIN_THREAD_ONLY defaults to False).
def fake_platform_modules(**app_attrs) -> dict:
    modules = {f'whisper_key.platform.{m}': _stand_in_module(f'whisper_key.platform.{m}')
               for m in _PLATFORM_SUBMODULES}
    package = _stand_in_module('whisper_key.platform')
    package.IS_MACOS = package.IS_WINDOWS = False
    package.PLATFORM = 'unsupported'
    for m in _PLATFORM_SUBMODULES:
        setattr(package, m, modules[f'whisper_key.platform.{m}'])
    app = modules['whisper_key.platform.app']
    app.TK_MAIN_THREAD_ONLY = False
    for key, value in app_attrs.items():
        setattr(app, key, value)
    modules['whisper_key.platform'] = package
    return modules


# For the rest of `test`: patch sys.modules with `fakes` and drop the app's own
# modules so they re-import against them. Everything (including the attributes
# the re-imports bind on the whisper_key package) is restored afterwards, so
# nothing faked leaks into later tests.
def reimport_under(test, fakes: dict):
    import unittest.mock as mock
    import whisper_key
    saved_attrs = dict(vars(whisper_key))
    patcher = mock.patch.dict(sys.modules, fakes)
    patcher.start()

    def restore():
        patcher.stop()
        for key in [k for k in vars(whisper_key) if k not in saved_attrs]:
            delattr(whisper_key, key)
        for key, value in saved_attrs.items():
            setattr(whisper_key, key, value)
    test.addCleanup(restore)
    for name in [n for n in sys.modules
                 if n.startswith('whisper_key.') and n not in fakes
                 and not n.startswith('whisper_key.platform') and n != 'whisper_key.utils']:
        sys.modules.pop(name)


class HotkeyParsingTests(unittest.TestCase):
    def test_parse_hotkey_splits_on_plus(self):
        from whisper_key.utils import parse_hotkey
        self.assertEqual(parse_hotkey("ctrl+a"), ["ctrl", "a"])
        self.assertEqual(parse_hotkey("Ctrl+Shift+F1"), ["ctrl", "shift", "f1"])

    def test_parse_hotkey_handles_empty(self):
        from whisper_key.utils import parse_hotkey
        self.assertEqual(parse_hotkey(""), [])
        self.assertEqual(parse_hotkey(None), [])

    def test_beautify_hotkey_uppercases(self):
        from whisper_key.utils import beautify_hotkey
        self.assertEqual(beautify_hotkey("ctrl+a"), "CTRL+A")
        self.assertEqual(beautify_hotkey(""), "")


class DocumentationStandardTests(unittest.TestCase):
    # CLAUDE.md mandates that every module opens with a 2-4 line header comment
    # describing its purpose. Enforced here so the standard can't silently decay
    # as new modules are added — a new file without a header fails the suite.
    def test_every_module_has_a_header_comment(self):
        pkg = ROOT / "src" / "whisper_key"
        missing = []
        for path in sorted(pkg.rglob("*.py")):
            if "__pycache__" in path.as_posix() or path.name == "__init__.py":
                continue
            header_lines = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    if header_lines:
                        break
                    continue  # tolerate blank lines before the header starts
                if stripped.startswith("#"):
                    header_lines += 1
                else:
                    break  # hit code — header (if any) is over
            if header_lines < 2:
                missing.append(f"{path.relative_to(pkg).as_posix()} ({header_lines} line(s))")
        self.assertEqual(
            missing, [],
            "Modules missing a 2+ line header comment (see CLAUDE.md):\n  "
            + "\n  ".join(missing),
        )


class VersionMetadataTests(unittest.TestCase):
    def test_pyproject_has_local_name(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["project"]["name"], "whisper-local")
        self.assertIn("whisper-local", data["project"]["scripts"])
        self.assertIn("wl", data["project"]["scripts"])

    def test_no_orphan_update_checker(self):
        self.assertFalse((ROOT / "src" / "whisper_key" / "update_checker.py").exists())

    def test_main_does_not_import_update_checker(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("update_checker", main_src)
        self.assertNotIn("check_for_updates", main_src)


class VoiceCommandsDefaultsTests(unittest.TestCase):
    def test_no_registry_writes_in_defaults(self):
        defaults = (ROOT / "src" / "whisper_key" / "commands.defaults.yaml").read_text(encoding="utf-8")
        self.assertNotIn("reg add", defaults.lower())


class WhisperBackendTests(unittest.TestCase):
    def test_default_backend_is_faster_whisper(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertEqual(cfg["whisper"].get("backend"), "faster_whisper")

    def test_whisper_cpp_module_imports_lazily(self):
        # Import the module — the heavy pywhispercpp import is lazy inside __init__
        from whisper_key import whisper_engine_cpp
        self.assertTrue(hasattr(whisper_engine_cpp, 'WhisperEngineCpp'))

    def test_optional_dep_declared(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        extras = data.get("project", {}).get("optional-dependencies", {})
        self.assertIn("whispercpp", extras)
        self.assertTrue(any("pywhispercpp" in d for d in extras["whispercpp"]))


class InstanceManagerTests(unittest.TestCase):
    def test_exposes_cleanup_pid_file(self):
        src = (ROOT / "src" / "whisper_key" / "instance_manager.py").read_text(encoding="utf-8")
        self.assertIn("def cleanup_pid_file", src)
        self.assertIn("os.kill", src)
        self.assertIn("_wait_for_lock", src)

    def test_main_calls_cleanup_pid_file(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertIn("cleanup_pid_file(instance_name)", main_src)


class TextPostprocessTests(unittest.TestCase):
    def test_strip_filler_words(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'strip_filler_words': True}
        self.assertEqual(postprocess("um, hello like world", cfg), "hello world")

    def test_capitalize_first(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'capitalize_first': True}
        self.assertEqual(postprocess("hello world", cfg), "Hello world")

    def test_ensure_punctuation(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'ensure_punctuation': True}
        self.assertEqual(postprocess("hello world", cfg), "hello world.")
        self.assertEqual(postprocess("hello world.", cfg), "hello world.")

    def test_postprocess_passthrough_when_empty(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess("hello", {}), "hello")
        self.assertEqual(postprocess("", {'capitalize_first': True}), "")

    def test_strip_trailing_period(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'strip_trailing_period': True}
        self.assertEqual(postprocess("hello world.", cfg), "hello world")
        self.assertEqual(postprocess("done.\n", cfg), "done\n")
        self.assertEqual(postprocess("e.g..", cfg), "e.g..")  # don't touch ellipsis-like
        self.assertEqual(postprocess("no period here", cfg), "no period here")

    def test_inline_formatting_basics(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'inline_formatting': True}
        self.assertEqual(postprocess("hello comma world period", cfg), "hello, world.")
        self.assertEqual(postprocess("what time is it question mark", cfg), "what time is it?")

    def test_inline_formatting_custom_replaces_defaults(self):
        # Custom list replaces the English defaults (non-English use case).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [
                {'phrase': 'przecinek', 'replacement': ','},
                {'phrase': 'strzałka', 'replacement': '→'},
            ],
        }
        self.assertEqual(postprocess("tekst przecinek dalej", cfg), "tekst, dalej")
        self.assertEqual(postprocess("a strzałka b", cfg), "a → b")
        # English defaults are NOT active in replace mode.
        self.assertEqual(postprocess("hello comma world", cfg), "hello comma world")

    def test_inline_formatting_extend_keeps_defaults(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_extend': True,
            'inline_formatting_replacements': [{'phrase': 'arrow', 'replacement': '→'}],
        }
        # both the English default AND the custom phrase apply
        self.assertEqual(postprocess("hello comma arrow there", cfg), "hello, → there")

    def test_absorb_cleans_whisper_prosody_punctuation(self):
        # Whisper adds its own commas/periods around spoken cue words; absorb should
        # eat them so the output isn't polluted (Discussion #1 bug report).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_absorb_punctuation': True,
            'inline_formatting_replacements': [
                {'phrase': 'comma', 'replacement': ', '},
                {'phrase': 'arrow', 'replacement': ' → '},
            ],
        }
        whisper_out = "Hello, comma, and welcome, arrow. Common greeting."
        self.assertEqual(postprocess(whisper_out, cfg),
                         "Hello, and welcome → Common greeting.")

    def test_absorb_off_leaves_prosody_artifacts(self):
        # Documents that WITHOUT absorb the artifacts remain (opt-in, no regression).
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [{'phrase': 'comma', 'replacement': ','}],
        }
        self.assertIn(",,", postprocess("a, comma, b", cfg))

    def test_absorb_with_builtins_does_not_glue_or_eat_breaks(self):
        # SEC #4: absorb + built-in English cue words must keep spacing and newlines.
        from whisper_key.text_postprocess import postprocess
        cfg = {'inline_formatting': True, 'inline_formatting_absorb_punctuation': True}
        self.assertEqual(postprocess("Hello, comma, world.", cfg), "Hello, world.")
        # "new paragraph" break must survive a following cue's absorb
        out = postprocess("first new paragraph second period", cfg)
        self.assertIn("\n\n", out)

    def test_absorb_respects_word_boundary(self):
        # "comma" must not fire inside "commander"/"Common".
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_absorb_punctuation': True,
            'inline_formatting_replacements': [{'phrase': 'comma', 'replacement': ', '}],
        }
        out = postprocess("the commander said comma done", cfg)
        self.assertIn("commander", out)
        self.assertNotIn("commaander", out)

    def test_inline_formatting_replacement_is_literal(self):
        # A replacement containing regex-special chars must be inserted literally.
        from whisper_key.text_postprocess import postprocess
        cfg = {
            'inline_formatting': True,
            'inline_formatting_replacements': [{'phrase': 'backref', 'replacement': r'\1\g<0>'}],
        }
        self.assertEqual(postprocess("x backref y", cfg), r"x \1\g<0> y")

    def test_ollama_polish_handles_curly_braces_in_text(self):
        from whisper_key.text_postprocess import _ollama_polish
        cfg = {'enabled': True, 'endpoint': 'http://127.0.0.1:0', 'timeout': 0.1,
               'prompt': 'Polish:\n\n{text}'}
        result = _ollama_polish("config = {a: 1, b: 2}", cfg)
        self.assertEqual(result, '')

    def test_ollama_polish_handles_curly_braces_in_prompt(self):
        from whisper_key.text_postprocess import _ollama_polish
        cfg = {'enabled': True, 'endpoint': 'http://127.0.0.1:0', 'timeout': 0.1,
               'prompt': 'Format: {format_var} not a placeholder. {text}'}
        result = _ollama_polish("hi", cfg)
        self.assertEqual(result, '')

    # --- Post-transcription replacements (correction-learning backing store) ---
    def test_replacement_literal_whole_word(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': 'see translate two', 'to': 'CTranslate2'}]}
        self.assertEqual(postprocess("we use see translate two here", cfg),
                         "we use CTranslate2 here")

    def test_replacement_whole_word_does_not_match_substring(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': 'cat', 'to': 'dog'}]}
        self.assertEqual(postprocess("the category cat", cfg), "the category dog")

    def test_replacement_case_insensitive_by_default(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': 'my sequel', 'to': 'MySQL'}]}
        self.assertEqual(postprocess("I love My Sequel", cfg), "I love MySQL")

    def test_replacement_to_text_is_literal(self):
        # Replacement text with regex-special chars is inserted verbatim.
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': 'foo', 'to': r'\1$&'}]}
        self.assertEqual(postprocess("a foo b", cfg), r"a \1$& b")

    def test_replacement_invalid_regex_is_skipped(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': '(unclosed', 'to': 'x', 'regex': True}]}
        # Must not raise; text passes through unchanged.
        self.assertEqual(postprocess("hello (unclosed world", cfg),
                         "hello (unclosed world")

    def test_replacement_matches_punctuation_edged_terms(self):
        # Regression: \b…\b silently dropped C++ / C# / .NET (non-word edges).
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [
            {'from': 'C++', 'to': 'CPP'},
            {'from': '.NET', 'to': 'dotnet'},
        ]}
        self.assertEqual(postprocess("I love C++ and .NET here", cfg),
                         "I love CPP and dotnet here")

    def test_replacement_whole_word_still_holds_for_normal_terms(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': [{'from': 'cat', 'to': 'dog'}]}
        self.assertEqual(postprocess("category cat scatter", cfg),
                         "category dog scatter")

    # --- Deterministic smart formatting ---
    def test_smart_formatting_times(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'times': True}}
        self.assertEqual(postprocess("meet at 3 p.m. sharp", cfg), "meet at 3 PM sharp")
        self.assertEqual(postprocess("call at 3:30pm", cfg), "call at 3:30 PM")

    def test_smart_formatting_times_does_not_touch_words(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'times': True}}
        self.assertEqual(postprocess("spam and jam", cfg), "spam and jam")

    def test_smart_formatting_times_ignores_digit_suffixed_token(self):
        # Regression: "pm2.5" must not be mangled into a time.
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'times': True}}
        self.assertEqual(postprocess("pm2.5 was high at 3 pm2 station", cfg),
                         "pm2.5 was high at 3 pm2 station")

    def test_smart_formatting_email(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'emails': True}}
        self.assertEqual(postprocess("email john at example dot com please", cfg),
                         "email john@example.com please")

    def test_smart_formatting_email_ignores_plain_prose(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'emails': True}}
        self.assertEqual(postprocess("let us meet at noon", cfg), "let us meet at noon")

    def test_smart_formatting_url(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'smart_formatting': {'urls': True}}
        self.assertEqual(postprocess("go to example dot com now", cfg),
                         "go to example.com now")

    def test_smart_formatting_off_by_default(self):
        from whisper_key.text_postprocess import postprocess
        # No smart_formatting key → spoken forms left untouched.
        self.assertEqual(postprocess("john at example dot com", {'inline_formatting': False}),
                         "john at example dot com")

    # --- Voice editing ("scratch that") ---
    def test_voice_editing_scratch_that(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'voice_editing': True}
        self.assertEqual(postprocess("book the flight. scratch that cancel it", cfg),
                         "book the flight. cancel it")

    def test_voice_editing_delete_and_strike_variants(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'voice_editing': True}
        self.assertEqual(postprocess("hello world delete that", cfg), "")  # nothing survives
        self.assertEqual(postprocess("first. junk here strike that", cfg), "first.")

    def test_voice_editing_off_leaves_phrase(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess("please scratch that itch", {'voice_editing': False}),
                         "please scratch that itch")

    def test_malformed_config_sections_do_not_crash(self):
        # A hand-edited user_settings.yaml can put a scalar where a mapping/list
        # belongs. That's a config mistake, but it must never take down the
        # transcription pipeline — degrade to "feature off" instead.
        from whisper_key.text_postprocess import postprocess
        for bad in (
            {'smart_formatting': 'not-a-dict'},
            {'smart_formatting': True},
            {'ollama': 'not-a-dict'},
            {'replacements': 'not-a-list'},
            {'replacements': [None, 42, 'str', {'no_from_key': 1}]},
            {'inline_formatting': True, 'inline_formatting_replacements': 'nope'},
        ):
            self.assertEqual(postprocess("some text here", bad), "some text here",
                             f"malformed config mishandled: {bad}")

    def test_long_transcript_postprocesses_quickly(self):
        # Regression: both the absorb pass and voice editing used to be O(n^2)
        # (a lazy leading scan / a re-scanned leading run), taking 6-13 s on a
        # long dictation and appearing to freeze the app. Both are linear now;
        # this budget is ~100x the measured time, so it only fires on a genuine
        # complexity regression, not on slow CI hardware.
        import time
        from whisper_key.text_postprocess import postprocess
        text = "comma " * 3000 + "scratch that " * 200 + "word " * 3000
        cfg = {
            'inline_formatting': True,
            'inline_formatting_absorb_punctuation': True,
            'voice_editing': True,
            'smart_formatting': {'times': True, 'emails': True, 'urls': True},
        }
        started = time.perf_counter()
        postprocess(text, cfg)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0,
                        f"post-processing a {len(text)}-char transcript took {elapsed:.2f}s "
                        "— suspect an O(n^2) regression in absorb or voice editing")

    def test_absorb_equivalence_on_representative_inputs(self):
        # The absorb pass was rewritten from a regex to find-then-expand; these
        # pin the exact behaviour that rewrite had to preserve.
        from whisper_key.text_postprocess import postprocess
        cfg = {'inline_formatting': True, 'inline_formatting_absorb_punctuation': True,
               'inline_formatting_replacements': [{'phrase': 'comma', 'replacement': ', '},
                                                  {'phrase': 'arrow', 'replacement': ' -> '}]}
        self.assertEqual(postprocess("Hello, comma, world.", cfg), "Hello, world.")
        self.assertEqual(postprocess("a arrow b", cfg), "a -> b")
        # Two spoken cues in a row yield two symbols — matches the pre-rewrite
        # behaviour exactly (verified by differential test against the old impl).
        self.assertEqual(postprocess("x comma comma y", cfg), "x,, y")
        self.assertEqual(postprocess("a,,, comma ,,, b", cfg), "a, b")
        self.assertEqual(postprocess("no cues here", cfg), "no cues here")

    def test_voice_editing_preserves_line_break_after_command(self):
        # Regression: the trailing class must not eat the newline separating the
        # scratched clause from the next line.
        from whisper_key.text_postprocess import postprocess
        cfg = {'voice_editing': True}
        self.assertEqual(postprocess("alpha. beta scratch that\ngamma", cfg),
                         "alpha.\ngamma")


class AppRulesShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "app_rules.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('rules', data)
        self.assertIsInstance(data['rules'], list)
        for rule in data['rules']:
            self.assertIn('match', rule)


class AppRulesFormattingTests(unittest.TestCase):
    def test_formatting_overrides_extracts_only_format_keys(self):
        from whisper_key.app_rules import formatting_overrides
        rule = {
            'match': ['code.exe'],
            'auto_paste': False,          # delivery key, not a formatting key
            'capitalize_first': False,
            'ensure_punctuation': False,
        }
        self.assertEqual(
            formatting_overrides(rule),
            {'capitalize_first': False, 'ensure_punctuation': False},
        )

    def test_formatting_overrides_empty_and_none(self):
        from whisper_key.app_rules import formatting_overrides
        self.assertEqual(formatting_overrides(None), {})
        self.assertEqual(formatting_overrides({'match': ['x'], 'auto_send': True}), {})

    def test_merge_overrides_global_postprocess(self):
        # Simulate the pipeline merge: rule formatting overrides global config.
        from whisper_key.app_rules import formatting_overrides
        global_cfg = {'capitalize_first': True, 'ensure_punctuation': True, 'inline_formatting': True}
        rule = {'capitalize_first': False, 'ensure_punctuation': False}
        merged = {**global_cfg, **formatting_overrides(rule)}
        self.assertFalse(merged['capitalize_first'])
        self.assertFalse(merged['ensure_punctuation'])
        self.assertTrue(merged['inline_formatting'])  # untouched key inherited


class TransformsShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "transforms.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('transforms', data)
        for t in data['transforms']:
            self.assertIn('name', t)
            self.assertIn('prompt', t)

    def test_transforms_manager_loads(self):
        # Against a throwaway config dir, never the developer's own: the
        # manager writes to it now (it seeds and migrates transforms.yaml),
        # and a test has no business touching a real install.
        import tempfile
        import unittest.mock as mock
        import whisper_key.transforms as tr
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(tr, 'get_user_app_data_path', return_value=tmp):
                manager = tr.TransformsManager()
            names = [t.get('name') for t in manager.list_transforms()]
        self.assertIn('polish', names)
        self.assertIn('prompt-engineer', names)


class StreakComputationTests(unittest.TestCase):
    def test_streak_basic(self):
        import datetime
        from whisper_key.stats import _compute_streaks
        today = datetime.date(2026, 5, 18)
        active = {
            '2026-05-18', '2026-05-17', '2026-05-16',
            '2026-05-10', '2026-05-09',
        }
        current, longest = _compute_streaks(active, today)
        self.assertEqual(current, 3)
        self.assertEqual(longest, 3)

    def test_streak_breaks_yesterday(self):
        import datetime
        from whisper_key.stats import _compute_streaks
        today = datetime.date(2026, 5, 18)
        active = {'2026-05-10'}
        current, longest = _compute_streaks(active, today)
        self.assertEqual(current, 0)
        self.assertEqual(longest, 1)


class ProfilesShapeTests(unittest.TestCase):
    def test_defaults_yaml_is_valid(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "profiles.defaults.yaml"
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        self.assertIn('profiles', data)
        self.assertIn('dictation', data['profiles'])


class UtilsTests(unittest.TestCase):
    def test_resolve_asset_path_relative(self):
        from whisper_key.utils import resolve_asset_path
        result = resolve_asset_path("config.defaults.yaml")
        self.assertTrue(result.endswith("config.defaults.yaml"))

    def test_resolve_asset_path_absolute_passthrough(self):
        from whisper_key.utils import resolve_asset_path
        absolute = os.path.abspath(__file__)
        self.assertEqual(resolve_asset_path(absolute), absolute)


class NoiseSuppresionTests(unittest.TestCase):
    def test_passthrough_without_noisereduce(self):
        import sys
        import unittest.mock as mock
        import numpy as np
        sys.modules.pop('whisper_key.noise_suppression', None)
        import importlib
        with mock.patch.dict(sys.modules, {'noisereduce': None}):
            import whisper_key.noise_suppression as ns_mod
            importlib.reload(ns_mod)
            audio = np.zeros(16000, dtype=np.float32)
            result = ns_mod.apply_noise_reduction(audio, 16000, 0.75)
            np.testing.assert_array_equal(result, audio)

    def test_config_in_defaults(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        ns = cfg["audio"]["noise_suppression"]
        self.assertFalse(ns["enabled"])
        self.assertAlmostEqual(float(ns["strength"]), 0.75, places=2)


class UpdateCheckTests(unittest.TestCase):
    def test_is_newer_basic(self):
        from whisper_key.update_check import _is_newer
        self.assertTrue(_is_newer("1.0.0", "0.9.0"))
        self.assertFalse(_is_newer("0.9.0", "1.0.0"))
        self.assertFalse(_is_newer("0.9.0", "0.9.0"))

    def test_no_network_when_disabled(self):
        import unittest.mock as mock
        from whisper_key.update_check import maybe_check_for_update
        with mock.patch('whisper_key.update_check._check_in_background') as m:
            maybe_check_for_update(lambda _: None, {'enabled': False})
            m.assert_not_called()

    def test_update_check_in_config_defaults(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertIn("update_check", cfg)
        self.assertFalse(cfg["update_check"]["enabled"])


class TranscriptLogTests(unittest.TestCase):
    def test_record_and_load(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                transcript_log.record_transcript("Hello world", app="test.exe", duration_s=1.5)
                entries = transcript_log.load_transcripts()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["text"], "Hello world")
        self.assertEqual(entries[0]["app"], "test.exe")

    def test_empty_text_not_logged(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import transcript_log
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.transcript_log.get_user_app_data_path', return_value=tmpdir):
                transcript_log.record_transcript("", app="test.exe")
                entries = transcript_log.load_transcripts()
        self.assertEqual(len(entries), 0)


class SettingsUiModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import settings_ui
        self.assertTrue(hasattr(settings_ui, 'run_settings_window'))


class ModelTransferTests(unittest.TestCase):
    # Offline model transfer for locked-down networks where huggingface.co is
    # blocked. These use a stub model folder so they never need a real download.
    def _stub_model(self, root, name="whisper-local-model-base"):
        from pathlib import Path
        folder = Path(root) / name
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"weights")
        (folder / "config.json").write_text('{"model_type":"whisper"}', encoding="utf-8")
        (folder / "tokenizer.json").write_text("{}", encoding="utf-8")
        return folder

    def test_export_destination_with_a_dot_is_not_rewritten(self):
        # Regression: an earlier version treated any dot in DEST as a file
        # extension and stripped it, so "D:\transfer.v2" silently became
        # "D:\transfer" and the model landed in the wrong directory.
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import model_transfer
        # export_model pulls ModelRegistry -> faster_whisper, absent in lean CI.
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            self.skipTest("faster_whisper not installed")
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "transfer.v2"
            snapshot = self._stub_model(root, name="snap")
            with mock.patch.object(model_transfer, '_find_cached_snapshot', return_value=snapshot):
                with mock.patch('whisper_key.config_manager.ConfigManager') as CM:
                    CM.return_value.get_whisper_config.return_value = {'model': 'base', 'models': {}}
                    rc = model_transfer.export_model(str(dest))
            # Assert INSIDE the context — the temp tree is gone once it exits.
            self.assertEqual(rc, 0)
            self.assertTrue((dest / "whisper-local-model-base" / "model.bin").exists(),
                            "export must land inside the dotted destination, not a truncated one")
            self.assertFalse((Path(root) / "transfer").exists(),
                             "must not create a truncated path")

    def test_export_to_missing_drive_explains_itself(self):
        # Reported in use: `--export-model D:\transfer` on a machine with no D:
        # drive produced a raw "[WinError 3] cannot find the path", which doesn't
        # tell the user the actual problem. The message must name the drive and
        # offer a destination that exists.
        import io
        import contextlib
        from pathlib import Path
        from whisper_key import model_transfer
        if sys.platform != 'win32':
            self.skipTest("drive-letter validation is Windows-only")
        # Find a drive letter that genuinely doesn't exist on this machine.
        import os
        import string
        free = [d for d in string.ascii_uppercase if not os.path.exists(d + ':' + os.sep)]
        if not free:
            self.skipTest("no unused drive letter to test with")
        problem = model_transfer._validate_destination(Path(f"{free[0]}:\\transfer"))
        self.assertTrue(problem, "missing drive must be reported as a problem")
        self.assertIn(f"{free[0]}:", problem)
        self.assertIn("Drives on this machine", problem)
        self.assertIn("--export-model", problem)  # actionable suggestion

    def test_export_default_destination_is_usable(self):
        from pathlib import Path
        from whisper_key import model_transfer
        default = model_transfer._default_export_dir()
        self.assertTrue(Path(default).is_dir(), "default export dir must exist")
        self.assertEqual(model_transfer._validate_destination(Path(default)), "")

    def test_import_rejects_non_model_folder(self):
        import tempfile
        from whisper_key import model_transfer
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(model_transfer.import_model(d), 1)  # empty dir
            self.assertEqual(model_transfer.import_model(d + "/nope"), 1)  # missing

    def test_import_registers_and_activates_model(self):
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from ruamel.yaml import YAML
        from whisper_key import model_transfer
        with tempfile.TemporaryDirectory() as src_root, tempfile.TemporaryDirectory() as appdata:
            bundle = self._stub_model(src_root)
            with mock.patch.object(model_transfer, 'get_user_app_data_path', return_value=appdata):
                rc = model_transfer.import_model(str(bundle))
            self.assertEqual(rc, 0)
            settings = Path(appdata) / "user_settings.yaml"
            data = YAML().load(settings.read_text(encoding="utf-8"))
            key = data["whisper"]["model"]
            self.assertEqual(key, "local-base")
            entry = data["whisper"]["models"][key]
            self.assertTrue(Path(entry["source"]).is_dir())
            # Model files must have been copied, not just referenced.
            self.assertTrue((Path(entry["source"]) / "model.bin").exists())

    def test_import_keep_in_place_does_not_copy(self):
        # The network-share case: IT hosts one copy, every machine points at it.
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from ruamel.yaml import YAML
        from whisper_key import model_transfer
        with tempfile.TemporaryDirectory() as src_root, tempfile.TemporaryDirectory() as appdata:
            bundle = self._stub_model(src_root)
            with mock.patch.object(model_transfer, 'get_user_app_data_path', return_value=appdata):
                rc = model_transfer.import_model(str(bundle), keep_in_place=True)
            self.assertEqual(rc, 0)
            data = YAML().load((Path(appdata) / "user_settings.yaml").read_text(encoding="utf-8"))
            entry = data["whisper"]["models"][data["whisper"]["model"]]
            self.assertEqual(Path(entry["source"]), bundle)
            self.assertFalse((Path(appdata) / "models").exists())

    def test_imported_model_is_seen_as_cached_by_registry(self):
        # The whole point: a local path must count as "already downloaded" so the
        # app never tries to reach huggingface.co for it.
        import tempfile
        try:
            from whisper_key.model_registry import ModelRegistry
        except Exception:
            self.skipTest("model_registry not importable (faster_whisper absent)")
        with tempfile.TemporaryDirectory() as d:
            bundle = self._stub_model(d)
            reg = ModelRegistry(whisper_models_config={
                'local-base': {'source': str(bundle), 'label': 'x', 'group': 'custom'}})
            self.assertTrue(reg.get_model('local-base').is_local_path)
            self.assertTrue(reg.is_model_cached('local-base'))
            self.assertEqual(reg.get_source('local-base'), str(bundle))

    def test_registered_settings_survive_existing_content(self):
        # Registering must not wipe the user's other settings/comments.
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from ruamel.yaml import YAML
        from whisper_key import model_transfer
        with tempfile.TemporaryDirectory() as src_root, tempfile.TemporaryDirectory() as appdata:
            settings = Path(appdata) / "user_settings.yaml"
            settings.write_text(
                "# my header\nwhisper:\n  hotwords:\n    - Kubernetes\naudio:\n  max_duration: 90\n",
                encoding="utf-8")
            bundle = self._stub_model(src_root)
            with mock.patch.object(model_transfer, 'get_user_app_data_path', return_value=appdata):
                model_transfer.import_model(str(bundle))
            data = YAML().load(settings.read_text(encoding="utf-8"))
            self.assertEqual(list(data["whisper"]["hotwords"]), ["Kubernetes"])
            self.assertEqual(data["audio"]["max_duration"], 90)
            self.assertEqual(data["whisper"]["model"], "local-base")


class SystemAudioTests(unittest.TestCase):
    # The real capture path needs audio hardware (verified separately); here we
    # test the plumbing: graceful absence of soundcard, and mono/rate shaping.
    def test_capture_without_soundcard_returns_none(self):
        import io
        import contextlib
        # Simulate soundcard being ABSENT even when it's actually installed:
        # binding the name to None in sys.modules makes `import soundcard` raise
        # ImportError (documented CPython behaviour). Merely popping it would let
        # a real installed copy be re-imported, so this test would pass only on
        # machines without the optional extra.
        saved = sys.modules.get('soundcard')
        sys.modules['soundcard'] = None
        try:
            from whisper_key import system_audio
            self.assertFalse(system_audio.is_available())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                out = system_audio.capture_loopback(1)
            self.assertIsNone(out)
            self.assertIn('loopback', buf.getvalue().lower())
        finally:
            # Restore exactly: put back a real module, or REMOVE the None
            # sentinel entirely — leaving it would break soundcard imports for
            # every later test in this process.
            if saved is not None:
                sys.modules['soundcard'] = saved
            else:
                sys.modules.pop('soundcard', None)

    def test_capture_with_mock_soundcard_returns_mono_float32(self):
        import types
        import numpy as np

        class _Rec:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes):
                return np.full((numframes, 2), 0.5, dtype=np.float32)  # stereo

        class _Mic:
            def recorder(self, samplerate, channels):
                return _Rec()

        class _Spk:
            name = 'Speakers'

        fake = types.ModuleType('soundcard')
        fake.default_speaker = lambda: _Spk()
        fake.get_microphone = lambda id, include_loopback=False: _Mic()
        sys.modules['soundcard'] = fake
        try:
            from whisper_key import system_audio
            out = system_audio.capture_loopback(1, samplerate=16000)
            self.assertIsNotNone(out)
            self.assertEqual(out.ndim, 1)              # collapsed to mono
            self.assertEqual(str(out.dtype), 'float32')
            self.assertEqual(len(out), 16000)          # 1s @ 16 kHz
        finally:
            del sys.modules['soundcard']


class ModelDownloadHintTests(unittest.TestCase):
    # First-run UX: the download message names an approximate size per model.
    def test_size_hint_for_known_models(self):
        try:
            from whisper_key.whisper_engine import _model_size_hint
        except Exception:
            self.skipTest("whisper_engine not importable (faster_whisper absent)")
        self.assertEqual(_model_size_hint('base'), '~141 MB')
        self.assertEqual(_model_size_hint('base.en'), '~141 MB')
        self.assertEqual(_model_size_hint('large-v3'), '~3 GB')
        self.assertEqual(_model_size_hint('unknown-model'), '')


class InstanceManagerNoConsoleTests(unittest.TestCase):
    # The silent-close fix must import cleanly and print on all platforms.
    def test_notify_no_console_prints(self):
        import io
        import contextlib
        import unittest.mock as mock
        # instance_manager pulls `.platform`, which eagerly imports the OS backend
        # (win32api / AppKit) — absent in the lean CI env, so skip there.
        try:
            from whisper_key import instance_manager
        except Exception:
            self.skipTest("instance_manager not importable on this platform")
        buf = io.StringIO()
        # Force "console attached" so the blocking MessageBox path can never run
        # (this process may itself be headless).
        with mock.patch.object(instance_manager, '_console_attached', return_value=True):
            with contextlib.redirect_stdout(buf):
                instance_manager._notify_no_console("T", "already running message")
        self.assertIn("already running message", buf.getvalue())


class CorrectionsTests(unittest.TestCase):
    # Correction persistence (postprocess.replacements) — the learning-loop store.
    def _with_temp_settings(self):
        import tempfile
        import unittest.mock as mock
        d = tempfile.mkdtemp()
        from whisper_key import corrections as cmod
        patcher = mock.patch.object(cmod, 'get_user_app_data_path', return_value=d)
        patcher.start()
        self.addCleanup(patcher.stop)
        return cmod, d

    def test_add_and_list_replacement(self):
        cmod, _ = self._with_temp_settings()
        self.assertTrue(cmod.add_replacement('see translate two', 'CTranslate2'))
        items = cmod.list_replacements()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['from'], 'see translate two')
        self.assertEqual(items[0]['to'], 'CTranslate2')

    def test_add_replacement_rejects_empty_and_noop(self):
        cmod, _ = self._with_temp_settings()
        self.assertFalse(cmod.add_replacement('', 'x'))
        self.assertFalse(cmod.add_replacement('same', 'same'))
        self.assertEqual(cmod.list_replacements(), [])

    def test_add_replacement_updates_existing_from(self):
        cmod, _ = self._with_temp_settings()
        cmod.add_replacement('foo', 'bar')
        self.assertTrue(cmod.add_replacement('foo', 'baz'))  # same from, new to → update
        items = cmod.list_replacements()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['to'], 'baz')

    def test_add_replacement_dedupes_identical(self):
        cmod, _ = self._with_temp_settings()
        cmod.add_replacement('foo', 'bar')
        self.assertFalse(cmod.add_replacement('foo', 'bar'))  # exact dup → no-op
        self.assertEqual(len(cmod.list_replacements()), 1)

    def test_add_replacement_updates_case_insensitively(self):
        # "teh" and "Teh" must not create two rules that both fire (matching is
        # case-insensitive), so adding a case variant updates in place.
        cmod, _ = self._with_temp_settings()
        cmod.add_replacement('Teh', 'The')
        self.assertTrue(cmod.add_replacement('teh', 'THE'))
        items = cmod.list_replacements()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['to'], 'THE')

    def test_saved_correction_is_applied_by_postprocess(self):
        # End-to-end: what corrections.py writes must be consumable by postprocess.
        cmod, _ = self._with_temp_settings()
        cmod.add_replacement('my sequel', 'MySQL')
        from whisper_key.text_postprocess import postprocess
        cfg = {'replacements': cmod.list_replacements()}
        self.assertEqual(postprocess('I use my sequel daily', cfg), 'I use MySQL daily')


class HotwordSuggestTests(unittest.TestCase):
    def test_suggest_picks_frequent_proper_nouns(self):
        from whisper_key.dictionary import suggest_hotwords
        texts = [
            "We deployed Kubernetes today.",
            "The Kubernetes cluster is fine. Kubernetes again.",
            "I love Kubernetes and also PostgreSQL.",
        ]
        got = dict(suggest_hotwords(texts, min_count=3))
        self.assertIn('Kubernetes', got)
        self.assertEqual(got['Kubernetes'], 3)  # sentence-initial one not counted

    def test_suggest_excludes_known_hotwords(self):
        from whisper_key.dictionary import suggest_hotwords
        texts = ["Use Redis now.", "Redis is great with Redis.", "More Redis here."]
        got = dict(suggest_hotwords(texts, known={'redis'}, min_count=2))
        self.assertNotIn('Redis', got)

    def test_suggest_ignores_plain_sentence_starts(self):
        from whisper_key.dictionary import suggest_hotwords
        texts = ["Today was good.", "Today is better.", "Today we ship."]
        # "Today" only ever appears sentence-initial → not a suggestion.
        self.assertEqual(suggest_hotwords(texts, min_count=2), [])


class OnboardingBannerTests(unittest.TestCase):
    # UX #4b: the first-launch banner must reflect the user's ACTUAL configured
    # hotkeys (and notify message), not hardcoded Windows defaults.
    def test_banner_uses_supplied_hotkeys(self):
        import io
        import contextlib
        import unittest.mock as mock
        from whisper_key import onboarding_tutorial
        seen = {}

        def fake_notify(msg):
            seen['notify'] = msg

        buf = io.StringIO()
        with mock.patch.object(onboarding_tutorial, 'mark_complete', lambda: None):
            with contextlib.redirect_stdout(buf):
                onboarding_tutorial.show_console_welcome(
                    hotkeys={'record': 'F9', 'rephrase': 'F10', 'command': 'F11',
                             'cancel': 'F12', 'pause': 'F8'},
                    notify=fake_notify,
                )
        out = buf.getvalue()
        self.assertIn('F9', out)
        self.assertIn('F10', out)
        self.assertNotIn('Ctrl+Win', out)  # no leaked default
        self.assertEqual(seen.get('notify'), 'Welcome! Hold F9 to start dictating.')


class PostprocessHotReloadTests(unittest.TestCase):
    # UX #1/#3: editing postprocess in user_settings.yaml applies on next dictation
    # (get_postprocess_config) without an app restart.
    def test_postprocess_reloads_on_file_change(self):
        import os
        import tempfile
        import unittest.mock as mock
        from ruamel.yaml import YAML
        # Import the submodule object so patch.object resolves it without relying
        # on it already being an attribute of the package (string-target patches
        # fail under a fresh `unittest` run where nothing imported it first).
        # config_manager pulls `.platform`, which eagerly imports the OS-specific
        # backend (win32api / AppKit) — absent in the lean CI env, so skip there.
        try:
            from whisper_key import config_manager as cm_mod
        except Exception:
            self.skipTest("config_manager not importable on this platform")
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cm_mod, 'get_user_app_data_path', return_value=d):
                cm = cm_mod.ConfigManager(quiet=True)
                self.assertFalse(cm.get_postprocess_config().get('strip_filler_words'))
                sp = os.path.join(d, 'user_settings.yaml')
                base = cm._postprocess_mtime or os.path.getmtime(sp)
                with open(sp, 'w', encoding='utf-8') as f:
                    YAML().dump({'postprocess': {'strip_filler_words': True}}, f)
                os.utime(sp, (base + 10, base + 10))  # guarantee a newer mtime
                self.assertTrue(cm.get_postprocess_config().get('strip_filler_words'))


class SettingsResetTests(unittest.TestCase):
    # SEC #1: "Reset to defaults" promises hotwords survive — verify they do.
    def test_reset_preserves_hotwords(self):
        import tempfile, os
        from ruamel.yaml import YAML
        from whisper_key.settings_ui import reset_settings_preserving_hotwords
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'user_settings.yaml')
            with open(path, 'w', encoding='utf-8') as f:
                YAML().dump({'whisper': {'model': 'small', 'hotwords': ['Kubernetes', 'drajb']},
                             'clipboard': {'auto_paste': False}}, f)
            preserved = reset_settings_preserving_hotwords(path)
            self.assertEqual(preserved, ['Kubernetes', 'drajb'])
            with open(path, encoding='utf-8') as f:
                after = YAML().load(f)
            # hotwords kept, everything else gone (back to defaults)
            self.assertEqual(list(after['whisper']['hotwords']), ['Kubernetes', 'drajb'])
            self.assertNotIn('clipboard', after)
            self.assertNotIn('model', after['whisper'])

    def test_reset_with_no_hotwords_removes_file(self):
        import tempfile, os
        from ruamel.yaml import YAML
        from whisper_key.settings_ui import reset_settings_preserving_hotwords
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'user_settings.yaml')
            with open(path, 'w', encoding='utf-8') as f:
                YAML().dump({'clipboard': {'auto_paste': False}}, f)
            self.assertEqual(reset_settings_preserving_hotwords(path), [])
            self.assertFalse(os.path.exists(path))  # clean wipe when nothing to keep


class HistoryWindowModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import history_window
        self.assertTrue(hasattr(history_window, 'show_history'))


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_exists(self):
        self.assertTrue((ROOT / ".github" / "workflows" / "release.yml").exists())

    def test_release_workflow_triggers_on_tag(self):
        with open(ROOT / ".github" / "workflows" / "release.yml", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("tags:", content)
        self.assertIn("v*", content)
        self.assertIn("pypa/gh-action-pypi-publish", content)


class PyprojectOptionalDepsTests(unittest.TestCase):
    def test_noise_optional_dep(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        extras = data.get("project", {}).get("optional-dependencies", {})
        self.assertIn("noise", extras)
        self.assertTrue(any("noisereduce" in d for d in extras["noise"]))


class SelftestModuleTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import selftest
        self.assertTrue(hasattr(selftest, 'run_selftest'))

    def test_report_helper(self):
        import io
        import sys
        from whisper_key.selftest import _report
        failures = []
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _report(True, "looks good", failures, "fake")
            _report(False, ("uh oh", "fix-me"), failures, "fake-2")
        finally:
            sys.stdout = old_stdout
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], "fake-2")


class FirstRunTests(unittest.TestCase):
    def test_flag_file_lifecycle(self):
        import tempfile
        import unittest.mock as mock
        from whisper_key import first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch('whisper_key.first_run.get_user_app_data_path', return_value=tmpdir):
                self.assertTrue(first_run.is_first_run())
                first_run.mark_first_run_complete()
                self.assertFalse(first_run.is_first_run())

    def test_show_welcome_module_importable(self):
        from whisper_key import first_run
        self.assertTrue(hasattr(first_run, 'show_welcome_window'))


class CheatSheetTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import cheat_sheet
        self.assertTrue(hasattr(cheat_sheet, 'show_cheat_sheet'))


class BundleLogsTests(unittest.TestCase):
    def test_redaction_replaces_usernames(self):
        from whisper_key.bundle_logs import _redact
        sample = "Path: C:\\Users\\rohit\\AppData\\Roaming and email me at test@example.com"
        red = _redact(sample)
        self.assertNotIn("rohit", red.lower())
        self.assertNotIn("test@example.com", red)
        self.assertIn("<USER>", red)
        self.assertIn("<EMAIL>", red)

    def test_redaction_macos_linux_paths(self):
        from whisper_key.bundle_logs import _redact
        self.assertIn("<USER>", _redact("/Users/alice/.whisperkey/"))
        self.assertIn("<USER>", _redact("/home/bob/log.txt"))

    def test_bundle_creates_zip(self):
        import io
        import sys
        import tempfile
        import unittest.mock as mock
        import zipfile
        from whisper_key import bundle_logs

        with tempfile.TemporaryDirectory() as appdata:
            with tempfile.TemporaryDirectory() as out:
                output = f"{out}/bundle.zip"
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    with mock.patch('whisper_key.bundle_logs.get_user_app_data_path', return_value=appdata), \
                         mock.patch('whisper_key.bundle_logs._capture_doctor', return_value='[doctor mocked]'):
                        rc = bundle_logs.bundle_logs(output)
                finally:
                    sys.stdout = old_stdout
                self.assertEqual(rc, 0)
                with zipfile.ZipFile(output) as zf:
                    names = zf.namelist()
                self.assertIn('about.txt', names)
                self.assertIn('doctor.txt', names)


class LocalServerTests(unittest.TestCase):
    def test_module_importable(self):
        from whisper_key import local_server
        self.assertTrue(hasattr(local_server, 'run_server'))
        self.assertEqual(local_server.DEFAULT_PORT, 7777)

    def test_decode_wav_fallback(self):
        import io
        import wave
        import numpy as np
        from whisper_key.local_server import _decode_wav_fallback

        with io.BytesIO() as buf:
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                samples = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 32767).astype(np.int16)
                wf.writeframes(samples.tobytes())
            wav_bytes = buf.getvalue()

        decoded = _decode_wav_fallback(wav_bytes)
        self.assertEqual(decoded.dtype, np.float32)
        self.assertEqual(len(decoded), 16000)
        self.assertGreater(float(np.max(np.abs(decoded))), 0.5)


class MainCliFlagsTests(unittest.TestCase):
    def test_main_registers_new_flags(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        for flag in ('--selftest', '--cheat-sheet', '--bundle-logs', '--serve'):
            self.assertIn(flag, main_src, f"main.py should register {flag}")


class TroubleshootingDocTests(unittest.TestCase):
    def test_docs_exist(self):
        self.assertTrue((ROOT / "docs" / "troubleshooting.md").exists())
        self.assertTrue((ROOT / "docs" / "faq.md").exists())


class VersionBumpTests(unittest.TestCase):
    def test_pyproject_version(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        version = data["project"]["version"]
        major, minor = version.split('.')[:2]
        self.assertGreaterEqual((int(major), int(minor)), (0, 10))

    def test_citation_matches_pyproject(self):
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            pyproject_version = tomllib.load(f)["project"]["version"]
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn(f"version: {pyproject_version}", citation,
                      "CITATION.cff version must match pyproject.toml")


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler for parser tests."""
    def __init__(self, body: bytes, boundary: str, content_length=None):
        import io
        self.headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(content_length if content_length is not None else len(body)),
        }
        self.rfile = io.BytesIO(body)


def _build_multipart(boundary: str, file_bytes: bytes) -> bytes:
    b = boundary.encode()
    return (
        b'--' + b + b'\r\n'
        b'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n'
        + file_bytes + b'\r\n'
        b'--' + b + b'--\r\n'
    )


class LocalServerSecurityTests(unittest.TestCase):
    # SRV-1: binary audio ending in 0x2D ('-') must NOT be truncated.
    def test_parse_multipart_preserves_trailing_dashes(self):
        from whisper_key.local_server import _parse_multipart
        audio = b'\x00\x01\x02\x2d\x2d\x2d'  # ends in three dashes
        body = _build_multipart('BoUnDaRy123', audio)
        fields = _parse_multipart(_FakeHandler(body, 'BoUnDaRy123'))
        self.assertEqual(fields['file']['data'], audio)

    # SRV-2: oversized Content-Length is rejected before the body is read.
    def test_oversized_content_length_rejected(self):
        from whisper_key import local_server
        huge = local_server.MAX_UPLOAD_BYTES + 1
        handler = _FakeHandler(b'x', 'B', content_length=huge)
        with self.assertRaises(ValueError):
            local_server._parse_multipart(handler)

    # SEC #3: negative Content-Length must be rejected (read(-1) would drain socket).
    def test_negative_content_length_rejected(self):
        from whisper_key import local_server
        handler = _FakeHandler(b'x', 'B', content_length=-1)
        with self.assertRaises(ValueError):
            local_server._parse_multipart(handler)


class BundleRedactionTests(unittest.TestCase):
    # SEC #2: URL credentials + secret query params masked in ALL bundled files
    # (this is what protects doctor.txt, not just user_settings.yaml).
    def test_redact_masks_url_credentials_and_tokens(self):
        from whisper_key.bundle_logs import _redact
        out = _redact("Ollama post-edit: http://user:s3cret@ollama.host:11434 reachable")
        self.assertNotIn("s3cret", out)
        self.assertIn("<REDACTED>@", out)
        out2 = _redact("GET https://api.example.com/x?token=abc123&z=1")
        self.assertNotIn("abc123", out2)
        self.assertIn("<REDACTED>", out2)

    # PRIV-1: sensitive config fields are masked in user_settings.yaml.
    def test_redact_yaml_masks_sensitive_fields(self):
        from whisper_key.bundle_logs import _redact_yaml
        sample = (
            "whisper:\n"
            "  hotwords: [SecretName, CodeWord]\n"
            "  initial_prompt: my private context\n"
            "postprocess:\n"
            "  ollama:\n"
            "    endpoint: http://user:pass@host:11434\n"
        )
        out = _redact_yaml(sample)
        self.assertNotIn('SecretName', out)
        self.assertNotIn('CodeWord', out)
        self.assertNotIn('private context', out)
        self.assertNotIn('user:pass', out)
        self.assertIn('<REDACTED>', out)

    def test_redact_yaml_masks_block_hotwords(self):
        from whisper_key.bundle_logs import _redact_yaml
        sample = "whisper:\n  hotwords:\n    - Alpha\n    - Bravo\n  model: tiny\n"
        out = _redact_yaml(sample)
        self.assertNotIn('Alpha', out)
        self.assertNotIn('Bravo', out)
        self.assertIn('model: tiny', out)  # non-sensitive keys untouched


class VoiceCommandQuotingTests(unittest.TestCase):
    # VC-1: clipboard content is shell-quoted when expanded into a run: command.
    def test_shell_safe_quotes_clipboard(self):
        try:
            from whisper_key.voice_commands import VoiceCommandManager
        except Exception:
            self.skipTest("voice_commands not importable on this platform")
        import shlex
        import unittest.mock as mock
        vc = VoiceCommandManager.__new__(VoiceCommandManager)
        with mock.patch('whisper_key.voice_commands.pyperclip.paste', return_value='; rm -rf ~'):
            safe = vc._expand_template('echo ${clipboard}', shell_safe=True)
            raw = vc._expand_template('echo ${clipboard}', shell_safe=False)
        self.assertEqual(safe, 'echo ' + shlex.quote('; rm -rf ~'))
        self.assertEqual(raw, 'echo ; rm -rf ~')


class AutostartTests(unittest.TestCase):
    def test_module_and_api(self):
        from whisper_key import autostart
        for fn in ('is_supported', 'is_enabled', 'enable', 'disable', 'toggle'):
            self.assertTrue(callable(getattr(autostart, fn, None)), f"missing {fn}")

    def test_is_supported_matches_platform(self):
        import sys
        from whisper_key import autostart
        self.assertEqual(autostart.is_supported(), sys.platform in ('win32', 'darwin'))

    def test_launch_command_nonempty(self):
        from whisper_key import autostart
        cmd = autostart._launch_command()
        self.assertIsInstance(cmd, list)
        self.assertTrue(cmd and cmd[0])

    def test_pyapp_autostart_uses_exe_not_bare_interpreter(self):
        # Regression for issue #2. Under pyapp, sys.executable is the private
        # unpacked CPython, NOT whisper-local.exe. Using it put a bare interpreter
        # in the Run key, so boot opened an interactive Python console instead of
        # the app. $PYAPP carries the real .exe path (PYAPP_PASS_LOCATION=1).
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        with tempfile.TemporaryDirectory() as d:
            fake_exe = Path(d) / "whisper-local.exe"
            fake_exe.write_text("stub", encoding="utf-8")
            unpacked_python = str(Path(d) / "python.exe")
            with mock.patch.dict(os.environ, {"PYAPP": str(fake_exe)}):
                with mock.patch.object(autostart.sys, 'executable', unpacked_python):
                    cmd = autostart._launch_command()
        self.assertEqual(cmd, [str(fake_exe)],
                         "pyapp autostart must launch the .exe, not sys.executable")
        # The whole failure mode was "a bare interpreter with no script".
        self.assertFalse(cmd[0].endswith("python.exe"))

    def test_broken_bare_interpreter_detection(self):
        # The repair must fire on the broken issue-#2 value and on nothing else,
        # so it can never clobber a healthy or user-customised Run entry.
        from whisper_key.autostart import _is_broken_bare_interpreter as broken
        # Broken: a lone interpreter, no script to run.
        self.assertTrue(broken(r"C:\pyapp\python.exe"))
        self.assertTrue(broken(r'"C:\Program Files\pyapp\python.exe"'))
        self.assertTrue(broken(r"C:\x\pythonw.exe"))
        self.assertTrue(broken(r"C:\x\python3.exe"))
        # Healthy: has arguments, or is the app executable itself.
        self.assertFalse(broken(r"C:\x\pythonw.exe -m whisper_key.main"))
        self.assertFalse(broken(r'"C:\Program Files\py\pythonw.exe" -m whisper_key.main'))
        self.assertFalse(broken(r"C:\apps\whisper-local.exe"))
        self.assertFalse(broken(""))
        self.assertFalse(broken("   "))

    def test_repair_is_noop_when_not_enabled(self):
        import unittest.mock as mock
        from whisper_key import autostart
        with mock.patch.object(autostart, '_win_is_enabled', return_value=False):
            self.assertFalse(autostart.repair_if_broken())

    def test_repair_rewrites_only_broken_entry(self):
        import unittest.mock as mock
        from whisper_key import autostart
        if sys.platform != 'win32':
            self.skipTest("registry repair is Windows-only")
        good = r"C:\x\pythonw.exe -m whisper_key.main"
        with mock.patch.object(autostart, '_win_is_enabled', return_value=True):
            # Healthy entry -> untouched.
            with mock.patch.object(autostart, '_win_stored_command', return_value=good):
                with mock.patch.object(autostart, '_win_enable') as enable:
                    self.assertFalse(autostart.repair_if_broken())
                    enable.assert_not_called()
            # Broken entry -> rewritten.
            with mock.patch.object(autostart, '_win_stored_command', return_value=r"C:\p\python.exe"):
                with mock.patch.object(autostart, '_win_command_string', return_value=good):
                    with mock.patch.object(autostart, '_win_enable') as enable:
                        self.assertTrue(autostart.repair_if_broken())
                        enable.assert_called_once()

    def test_pip_install_autostart_prefers_windowless_interpreter(self):
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        if sys.platform != 'win32':
            self.skipTest("pythonw.exe selection is Windows-only")
        with tempfile.TemporaryDirectory() as d:
            py = Path(d) / "python.exe"
            pyw = Path(d) / "pythonw.exe"
            py.write_text("stub", encoding="utf-8")
            pyw.write_text("stub", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != 'PYAPP'}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(autostart.sys, 'executable', str(py)):
                    cmd = autostart._launch_command()
        self.assertEqual(cmd, [str(pyw), "-m", "whisper_key.main"])

    def test_missing_pythonw_falls_back_without_crashing(self):
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        if sys.platform != 'win32':
            self.skipTest("pythonw.exe selection is Windows-only")
        with tempfile.TemporaryDirectory() as d:
            py = Path(d) / "python.exe"
            py.write_text("stub", encoding="utf-8")  # no pythonw beside it
            env = {k: v for k, v in os.environ.items() if k != 'PYAPP'}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(autostart.sys, 'executable', str(py)):
                    with mock.patch.object(autostart.sys, '_base_executable', str(py)):
                        cmd = autostart._launch_command()
        # Falls back to console python, but still passes -m so the APP runs.
        self.assertEqual(cmd, [str(py), "-m", "whisper_key.main"])

    def test_macos_plist_roundtrip(self):
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'agent.plist'
            with mock.patch('whisper_key.autostart._mac_plist_path', return_value=p):
                self.assertFalse(autostart._mac_is_enabled())
                autostart._mac_enable()
                self.assertTrue(autostart._mac_is_enabled())
                content = p.read_text(encoding='utf-8')
                self.assertIn('RunAtLoad', content)
                self.assertIn('com.drajb.whisper-local', content)
                autostart._mac_disable()
                self.assertFalse(autostart._mac_is_enabled())

    def test_main_registers_autostart_flags(self):
        main_src = (ROOT / "src" / "whisper_key" / "main.py").read_text(encoding="utf-8")
        self.assertIn('--enable-autostart', main_src)
        self.assertIn('--disable-autostart', main_src)


class DefaultsTests(unittest.TestCase):
    def test_default_model_and_recording_mode(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "config.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            cfg = YAML().load(f)
        self.assertEqual(cfg["whisper"]["model"], "base")
        self.assertEqual(cfg["hotkey"]["recording_mode"], "push_to_talk")

    def test_profiles_no_tiny_downgrade(self):
        from ruamel.yaml import YAML
        path = ROOT / "src" / "whisper_key" / "profiles.defaults.yaml"
        with open(path, encoding="utf-8") as f:
            data = YAML().load(f)
        for name, prof in data["profiles"].items():
            model = (prof.get("overrides", {}).get("whisper") or {}).get("model")
            self.assertNotEqual(model, "tiny", f"profile '{name}' still pins tiny")

    def test_export_covers_all_user_files(self):
        # backup/restore must include every user-editable config file.
        from whisper_key.settings_io import EXPORTABLE_FILES
        for f in ("user_settings.yaml", "commands.yaml", "profiles.yaml",
                  "app_rules.yaml", "transforms.yaml"):
            self.assertIn(f, EXPORTABLE_FILES)


class ReviewFixTests(unittest.TestCase):
    # update_check must not crash on a "-dev" suffixed local version.
    def test_is_newer_handles_dev_suffix(self):
        from whisper_key.update_check import _is_newer
        self.assertTrue(_is_newer("0.12.0", "0.11.0-dev"))
        self.assertFalse(_is_newer("0.11.0", "0.11.0-dev"))   # same core, not newer
        self.assertFalse(_is_newer("1.2", "1.2.0"))           # padded equal
        self.assertTrue(_is_newer("v1.3.0", "1.2.9"))         # leading v tolerated

    # settings_ui._coerce must keep free-text settings as strings even when numeric-looking.
    def test_coerce_is_type_aware(self):
        from whisper_key.settings_ui import _coerce
        sentinel = object()  # not a BooleanVar
        self.assertEqual(_coerce(sentinel, "2024", "whisper.initial_prompt"), "2024")
        self.assertEqual(_coerce(sentinel, "3", "postprocess.ollama.model"), "3")
        self.assertEqual(_coerce(sentinel, "5", "whisper.beam_size"), 5)
        self.assertAlmostEqual(_coerce(sentinel, "0.75", "audio.noise_suppression.strength"), 0.75)

    # autostart.toggle returns the achieved state (macOS path, temp plist).
    def test_autostart_toggle_returns_state(self):
        import sys
        if sys.platform != "darwin":
            self.skipTest("toggle round-trip exercised via macOS plist path only")
        import tempfile, unittest.mock as mock
        from pathlib import Path
        from whisper_key import autostart
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("whisper_key.autostart._mac_plist_path", return_value=Path(d) / "a.plist"):
                self.assertTrue(autostart.toggle())
                self.assertFalse(autostart.toggle())


class StreamingDeliveryDecisionTests(unittest.TestCase):
    def _cfg(self, on=True):
        return {'deliver_to_cursor': on}

    def test_off_by_default(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery({}, True, True, True, None))

    def test_all_conditions_met(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertTrue(decide_stream_delivery(self._cfg(), True, True, True, None))

    def test_requires_streaming_available(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), False, True, True, None))

    def test_requires_auto_paste(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, False, True, None))

    def test_requires_textable_foreground(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, False, None))

    def test_respects_app_rule_suppress_and_copyonly(self):
        from whisper_key.streaming_delivery import decide_stream_delivery
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, True, {'suppress': True}))
        self.assertFalse(decide_stream_delivery(self._cfg(), True, True, True, {'auto_paste': False}))
        # a rule that doesn't touch delivery is fine
        self.assertTrue(decide_stream_delivery(self._cfg(), True, True, True, {'initial_prompt': 'x'}))


class StreamingDeliveryWorkerTests(unittest.TestCase):
    def test_segments_delivered_in_order_and_recorded(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("hello")
        sd.submit_final("world")
        full = sd.stop()
        self.assertEqual(delivered, ["hello ", "world "])
        self.assertEqual(full, "hello world")
        self.assertTrue(sd.submitted_any)

    def test_blank_segments_ignored(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("   ")
        sd.submit_final("")
        self.assertEqual(sd.stop(), "")
        self.assertEqual(delivered, [])
        self.assertFalse(sd.submitted_any)

    def test_stop_is_idempotent(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        sd = StreamingDelivery(deliver_fn=lambda s: None)
        sd.start()
        sd.submit_final("x")
        self.assertEqual(sd.stop(), "x")
        self.assertEqual(sd.stop(), "x")  # second stop returns same, no error

    def test_deliver_fn_exception_does_not_crash_and_flags_failure(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        def boom(_):
            raise RuntimeError("boom")
        sd = StreamingDelivery(deliver_fn=boom)
        sd.start()
        sd.submit_final("x")
        # stop() must still return cleanly even though delivery raised
        self.assertEqual(sd.stop(), "")
        self.assertTrue(sd.had_failure)

    def test_no_failure_flag_on_clean_delivery(self):
        from whisper_key.streaming_delivery import StreamingDelivery
        sd = StreamingDelivery(deliver_fn=lambda s: None)
        sd.start()
        sd.submit_final("ok")
        sd.stop()
        self.assertFalse(sd.had_failure)

    def test_submit_after_stop_is_ignored(self):
        # Closes the submit/stop race: a late segment after stop is dropped, not enqueued.
        from whisper_key.streaming_delivery import StreamingDelivery
        delivered = []
        sd = StreamingDelivery(deliver_fn=delivered.append)
        sd.start()
        sd.submit_final("a")
        sd.stop()
        sd.submit_final("late")
        self.assertEqual(delivered, ["a "])


if __name__ == "__main__":
    unittest.main()


class MergedFeatureTests(unittest.TestCase):
    """Features merged in 0.18.0, pinned here so a
    future refactor can't quietly drop them."""

    # --- AMD GPU classification ---
    def test_amd_gpu_classification(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'wk_gpu', str(ROOT / 'src' / 'whisper_key' / 'platform' / 'windows' / 'gpu.py'))
        gpu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gpu)
        cases = [
            # RX 580 is Polaris, NOT RDNA. The old one-digit match classified it
            # as RDNA1 and offered a runtime that cannot drive it.
            ('AMD Radeon RX 580', None),
            ('AMD Radeon RX 5700 XT', 'amd_rdna1'),
            ('RX5700', 'amd_rdna1'),          # vendor strings omit the space
            ('AMD Radeon RX 7900 XTX', 'amd_rdna2+'),
            ('AMD Radeon RX 9070 XT', 'amd_rdna2+'),
            # Strix Halo / Ryzen AI MAX report no "RX" at all.
            ('AMD Radeon 8060S Graphics', 'amd_rdna2+'),
            ('AMD Radeon 8040S', 'amd_rdna2+'),
            ('AMD Radeon 780M', None),
        ]
        for name, expected in cases:
            self.assertEqual(gpu._classify_gpu('amd', name), expected, f"for {name!r}")
        self.assertEqual(gpu._classify_gpu('nvidia', 'GeForce RTX 4090'), 'nvidia')

    # --- Vocabulary corrections ---
    def test_corrections_map_many_variants_to_one_term(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'corrections': {'CAPEX': ['cap x', 'copics'], 'MySQL': ['my sequel']}}
        self.assertEqual(postprocess('the cap x budget', cfg), 'the CAPEX budget')
        self.assertEqual(postprocess('we use copics here', cfg), 'we use CAPEX here')
        self.assertEqual(postprocess('I love my sequel', cfg), 'I love MySQL')

    def test_corrections_prefer_longest_variant(self):
        # "cap" must not shadow "cap x" and leave a dangling "x".
        from whisper_key.text_postprocess import postprocess
        cfg = {'corrections': {'CAP': ['cap'], 'CAPEX': ['cap x']}}
        self.assertEqual(postprocess('the cap x budget', cfg), 'the CAPEX budget')

    def test_corrections_are_whole_word_and_case_insensitive(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'corrections': {'MySQL': ['my sequel']}}
        self.assertEqual(postprocess('MY SEQUEL rocks', cfg), 'MySQL rocks')
        cfg2 = {'corrections': {'DOG': ['cat']}}
        self.assertEqual(postprocess('category cat', cfg2), 'category DOG')

    def test_corrections_tolerate_malformed_config(self):
        from whisper_key.text_postprocess import postprocess
        for bad in ({'corrections': 'nope'}, {'corrections': {'A': None}},
                    {'corrections': {'A': 123}}, {'corrections': []},
                    {'corrections': {'A': {'not': 'a list'}}}):
            self.assertEqual(postprocess('some text', bad), 'some text', f"for {bad}")

    def test_corrections_and_replacements_coexist(self):
        # Our per-entry `replacements` must still work alongside the new map.
        from whisper_key.text_postprocess import postprocess
        cfg = {'corrections': {'CAPEX': ['cap x']},
               'replacements': [{'from': 'budget', 'to': 'spend'}]}
        self.assertEqual(postprocess('the cap x budget', cfg), 'the CAPEX spend')

    # --- Terminal tab title ---
    def test_terminal_title_parses_static_and_animated_states(self):
        from whisper_key.terminal_title import TerminalTitle
        t = TerminalTitle({'idle': '', 'recording': [['R', 0.1], ['  ', 0.2]],
                           'processing': '...'})
        self.assertEqual(t._frames['idle'], [('Whisper Local', 60.0)])
        self.assertEqual(t._frames['recording'],
                         [('R Whisper Local', 0.1), ('   Whisper Local', 0.2)])
        self.assertEqual(t._frames['processing'], [('... Whisper Local', 60.0)])

    def test_terminal_title_falls_back_on_bad_frames(self):
        from whisper_key.terminal_title import TerminalTitle
        t = TerminalTitle({'recording': [['R', 'not-a-number']], 'idle': {'bad': 1}})
        # Bad frames fall back to the shipped defaults rather than raising.
        self.assertTrue(t._frames['recording'])
        self.assertEqual(t._frames['idle'], [('Whisper Local', 60.0)])

    def test_terminal_title_lifecycle_is_safe_without_a_tty(self):
        from whisper_key.terminal_title import TerminalTitle
        t = TerminalTitle({})
        t.update_state('recording')
        t.start()
        t.stop()  # must not raise even when disabled

    # --- Startup ready sound ---
    def test_ready_sound_wired_and_asset_present(self):
        import inspect
        # The asset must ship regardless of whether the audio backend is
        # installed, so assert that before the import that may be skipped.
        asset = ROOT / 'src' / 'whisper_key' / 'assets' / 'sounds' / 'app_ready.wav'
        self.assertTrue(asset.is_file(), 'app_ready.wav must ship with the package')
        # audio_feedback pulls playsound3, which the lean CI env lacks.
        try:
            from whisper_key.audio_feedback import AudioFeedback
        except Exception:
            self.skipTest('audio_feedback not importable (playsound3 absent)')
        params = inspect.signature(AudioFeedback.__init__).parameters
        self.assertIn('ready_enabled', params)
        self.assertIn('ready_sound', params)
        self.assertTrue(hasattr(AudioFeedback, 'play_ready_sound'))

    # --- config defaults for all of the above ---
    def test_new_config_sections_present_and_inert(self):
        from ruamel.yaml import YAML
        with open(ROOT / 'src' / 'whisper_key' / 'config.defaults.yaml', encoding='utf-8') as f:
            cfg = YAML().load(f)
        self.assertEqual(cfg['postprocess']['corrections'], {})
        self.assertTrue(cfg['audio_feedback']['ready_enabled'])
        self.assertEqual(cfg['audio_feedback']['ready_sound'],
                         'assets/sounds/app_ready.wav')
        self.assertIn('terminal_title', cfg)
        for state in ('idle', 'recording', 'processing'):
            self.assertIn(state, cfg['terminal_title'])
        # Shipping defaults must not alter ordinary text.
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('hello world', dict(cfg['postprocess'])), 'hello world')


class ReportedIssueTests(unittest.TestCase):
    """Bugs reported by users, pinned so they cannot come back."""

    # --- #6: pause hotkey permanently disabled every hotkey (Windows) ---
    def test_windows_register_replaces_bindings(self):
        # global-hotkeys keeps registrations across stop_checking_hotkeys(), so a
        # second register() raised "already registered". That exception aborted
        # the pause path before start() ran, leaving every hotkey dead — pause
        # included, so there was no way back short of restarting the app.
        if sys.platform != 'win32':
            self.skipTest('global-hotkeys is Windows-only')
        try:
            from whisper_key.platform.windows import hotkeys
        except Exception:
            self.skipTest('global_hotkeys not installed')
        full = [['ctrl+shift+f13', lambda: None, None],
                ['ctrl+alt+f14', lambda: None, None]]
        pause_only = [['ctrl+alt+f14', lambda: None, None]]
        try:
            # The exact sequence the pause hotkey performs, twice over.
            for _ in range(2):
                hotkeys.register(full)
                hotkeys.start()
                hotkeys.stop()
                hotkeys.register(pause_only)   # raised before the fix
                hotkeys.start()
                hotkeys.stop()
        finally:
            try:
                hotkeys.stop()
            except Exception:
                pass

    def test_windows_register_clears_first(self):
        # The mechanism behind the fix: register() must have replace semantics,
        # matching the macOS mirror, per docs/platform-abstraction.md.
        source = (ROOT / 'src' / 'whisper_key' / 'platform' / 'windows' / 'hotkeys.py').read_text(encoding='utf-8')
        self.assertIn('clear_hotkeys()', source,
                      'register() must clear before registering (issue #6)')

    # --- #3: tray Restart broke on pip installs (Windows) ---
    def test_relaunch_command_never_uses_argv(self):
        # argv[0] for a pip console script is the launcher path, and pip ships
        # only a compiled .exe stub there — handing it to python.exe fails with
        # "can't open file". The command must invoke the module instead.
        from whisper_key.utils import build_relaunch_command
        import os
        saved = os.environ.pop('PYAPP', None)
        try:
            cmd = build_relaunch_command()
        finally:
            if saved is not None:
                os.environ['PYAPP'] = saved
        self.assertIn('-m', cmd)
        self.assertIn('whisper_key.main', cmd)
        for part in cmd:
            self.assertFalse(
                part.endswith('Scripts\\whisper-local') or part.endswith('Scripts/whisper-local'),
                f'relaunch command must not reference the console script: {cmd}')

    def test_relaunch_command_prefers_pyapp_executable(self):
        # The standalone build must relaunch the .exe, not pyapp's private
        # interpreter (the issue #2 failure mode, shared by this code path).
        import os
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import utils
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / 'whisper-local.exe'
            fake.write_text('stub', encoding='utf-8')
            with mock.patch.dict(os.environ, {'PYAPP': str(fake)}):
                with mock.patch.object(utils.sys, 'executable', str(Path(d) / 'python.exe')):
                    self.assertEqual(utils.build_relaunch_command(), [str(fake)])

    def test_windowless_variant_used_only_for_autostart(self):
        # Autostart wants pythonw (no console at login); the tray restart wants
        # the console-visible interpreter so a terminal user keeps their console.
        import os
        if sys.platform != 'win32':
            self.skipTest('pythonw selection is Windows-only')
        from whisper_key.utils import build_relaunch_command
        saved = os.environ.pop('PYAPP', None)
        try:
            windowed = build_relaunch_command(windowless=False)
            hidden = build_relaunch_command(windowless=True)
        finally:
            if saved is not None:
                os.environ['PYAPP'] = saved
        self.assertTrue(windowed[0].lower().endswith('python.exe'))
        self.assertTrue(hidden[0].lower().endswith('pythonw.exe'))

    def test_autostart_delegates_to_shared_builder(self):
        # The two call sites disagreed once (autostart fixed for #2, tray left
        # broken for #3). They must share one implementation now.
        try:
            from whisper_key import autostart
        except Exception:
            self.skipTest('autostart not importable on this platform')
        from whisper_key.utils import build_relaunch_command
        self.assertEqual(autostart._launch_command(), build_relaunch_command(windowless=True))

    # --- #4: macOS hotkeys must be able to suppress the underlying key ---
    def test_macos_hotkeys_use_event_tap_with_fallback(self):
        source = (ROOT / 'src' / 'whisper_key' / 'platform' / 'macos' / 'hotkeys.py').read_text(encoding='utf-8')
        self.assertIn('CGEventTapCreate', source, 'event tap needed to consume keystrokes')
        # The NSEvent monitor must survive as the no-permission fallback.
        self.assertIn('addGlobalMonitorForEventsMatchingMask_handler_', source)
        # A disabled tap must be re-enabled or hotkeys silently die after a timeout.
        self.assertIn('kCGEventTapDisabledByTimeout', source)


class ReportedIssueHandlerTests(unittest.TestCase):
    """Drive the real handlers, not just the primitives underneath them."""

    # --- #6: the actual pause handler must survive a full round trip ---
    def _listener(self):
        import unittest.mock as mock
        try:
            from whisper_key.hotkey_listener import HotkeyListener
        except Exception:
            self.skipTest('hotkey_listener not importable on this platform')
        # Build without __init__ so no real hotkeys are registered by construction.
        listener = HotkeyListener.__new__(HotkeyListener)
        listener.logger = __import__('logging').getLogger('test')
        listener.is_paused = False
        listener.pause_hotkey = 'ctrl+alt+f14'
        listener.hotkey_bindings = [
            ['ctrl+shift+f13', lambda: None, None],
            ['ctrl+alt+f14', lambda: None, None],
        ]
        listener.state_manager = mock.Mock()
        return listener

    def test_pause_never_touches_registrations(self):
        # Issue #7. Re-registering from inside a hotkey callback is unsafe with
        # global-hotkeys 0.1.7: the checker iterates a LIVE view of its bindings
        # dict and calls back from inside that loop, so clearing mid-iteration
        # raises RuntimeError and kills the thread; and its stop() never joins,
        # so restarting while the chord is still held re-fires pause instantly.
        # Pause must therefore only flip a flag.
        import io
        import contextlib
        import unittest.mock as mock
        listener = self._listener()
        try:
            from whisper_key.platform import hotkeys as hk
        except Exception:
            self.skipTest('platform hotkeys not importable')

        with mock.patch.object(hk, 'register') as reg, \
             mock.patch.object(hk, 'start') as start, \
             mock.patch.object(hk, 'stop') as stop:
            with contextlib.redirect_stdout(io.StringIO()):
                listener._pause_hotkey_pressed()   # pause
                listener._pause_hotkey_pressed()   # resume
        reg.assert_not_called()
        start.assert_not_called()
        stop.assert_not_called()
        self.assertFalse(listener.is_paused, 'second press must resume')

    def test_pause_gates_other_callbacks_but_not_itself(self):
        # The flag is only useful if it actually suppresses the other hotkeys —
        # and if pause itself stays live, otherwise you could never un-pause.
        import io
        import contextlib
        listener = self._listener()
        fired = []
        gated = listener._gated(lambda: fired.append('record'), is_pause=False)
        pause_cb = listener._gated(lambda: fired.append('pause'), is_pause=True)

        gated(); pause_cb()
        self.assertEqual(fired, ['record', 'pause'], 'both fire while running')

        fired.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            listener._pause_hotkey_pressed()          # now paused
        gated(); pause_cb()
        self.assertEqual(fired, ['pause'],
                         'while paused only the pause key may fire (issue #7)')

        fired.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            listener._pause_hotkey_pressed()          # resumed
        gated()
        self.assertEqual(fired, ['record'], 'resume must re-enable the others')

    def test_gate_passes_through_none_release_callbacks(self):
        # Bindings without a release callback must stay None, not become a
        # wrapper that the backend would try to call.
        listener = self._listener()
        self.assertIsNone(listener._gated(None, is_pause=False))
        self.assertIsNone(listener._gated(None, is_pause=True))

    def test_pause_state_is_reported_to_state_manager(self):
        import io
        import contextlib
        listener = self._listener()
        with contextlib.redirect_stdout(io.StringIO()):
            listener._pause_hotkey_pressed()
            listener._pause_hotkey_pressed()
        calls = [c.args[0] for c in listener.state_manager.set_paused.call_args_list]
        self.assertEqual(calls, [True, False])

    # --- #3: the actual tray handler must spawn a runnable command ---
    def test_tray_restart_spawns_a_runnable_command(self):
        import unittest.mock as mock
        try:
            from whisper_key.system_tray import SystemTray
        except Exception:
            self.skipTest('system_tray not importable on this platform')
        tray = SystemTray.__new__(SystemTray)
        tray.logger = __import__('logging').getLogger('test')
        tray.notify = lambda *a, **k: None

        spawned = {}
        with mock.patch('subprocess.Popen', side_effect=lambda cmd, *a, **k: spawned.update(cmd=cmd)), \
             mock.patch('os.kill') as killed:
            tray._restart_application_from_tray()
        cmd = spawned.get('cmd')
        self.assertTrue(cmd, 'restart must spawn something')
        self.assertTrue(killed.called, 'the old instance must exit after a successful spawn')
        # It must be runnable: either the app executable, or python -m.
        if len(cmd) > 1:
            self.assertIn('-m', cmd)
            self.assertIn('whisper_key.main', cmd)

    def test_tray_restart_does_not_exit_when_spawn_fails(self):
        # A failed relaunch must never leave the user with no app at all.
        import unittest.mock as mock
        try:
            from whisper_key.system_tray import SystemTray
        except Exception:
            self.skipTest('system_tray not importable on this platform')
        tray = SystemTray.__new__(SystemTray)
        tray.logger = __import__('logging').getLogger('test')
        notes = []
        tray.notify = lambda msg, *a, **k: notes.append(msg)
        with mock.patch('subprocess.Popen', side_effect=OSError('boom')), \
             mock.patch('os.kill') as killed:
            tray._restart_application_from_tray()
        self.assertFalse(killed.called, 'must NOT kill the running app if relaunch failed')
        self.assertTrue(notes, 'user must be told the restart failed')


class MacOSHotkeyTests(unittest.TestCase):
    """Real coverage for the #4 event-tap patch. Skips off macOS / without
    pyobjc, but CI installs pyobjc on the macOS runner so this actually runs."""

    def _module(self):
        if sys.platform != 'darwin':
            self.skipTest('macOS-only')
        try:
            from whisper_key.platform.macos import hotkeys
        except Exception as e:
            self.skipTest(f'pyobjc not available: {e}')
        return hotkeys

    def test_module_imports_and_quartz_symbols_resolve(self):
        # The main risk in code I could not run: a mistyped Quartz symbol would
        # only surface at import time on a real Mac.
        hotkeys = self._module()
        for name in ('CGEventTapCreate', 'CGEventTapEnable', 'CGEventMaskBit',
                     'CGEventGetIntegerValueField', 'CFMachPortCreateRunLoopSource',
                     'CFRunLoopAddSource', 'CFRunLoopGetCurrent', 'CFRunLoopStop',
                     'kCGEventKeyDown', 'kCGEventKeyUp', 'kCGEventFlagsChanged',
                     'kCGEventTapDisabledByTimeout', 'kCGSessionEventTap',
                     'kCGKeyboardEventKeycode'):
            self.assertTrue(hasattr(hotkeys, name), f'Quartz symbol missing: {name}')

    def test_register_and_stop_are_safe_without_permission(self):
        # stop() must be callable even when start() never created a tap, and
        # must not raise when there is nothing to tear down.
        hotkeys = self._module()
        hotkeys.register([['ctrl+shift+f13', lambda: None, None]])
        hotkeys.stop()
        hotkeys.stop()  # idempotent

    def test_key_down_dispatch_reports_whether_it_matched(self):
        # The patch changed _handle_key_down to return True/False so the tap can
        # decide whether to consume the event. A silent revert to None would make
        # every keystroke pass through again — the exact bug #4 reported.
        import inspect
        hotkeys = self._module()
        source = inspect.getsource(hotkeys._handle_key_down)
        self.assertIn('return True', source)
        self.assertIn('return False', source)


class UninstallSafetyTests(unittest.TestCase):
    """--uninstall is the only code here that deletes user data. These pin the
    safety properties, especially that a SHARED HuggingFace cache is respected."""

    def test_only_our_models_are_ever_selected(self):
        # The cache holds other tools' models (CLIP, diarization, ...). Selecting
        # one of those for deletion would destroy unrelated work.
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import uninstall
        with tempfile.TemporaryDirectory() as d:
            hub = Path(d) / 'hub'
            hub.mkdir()
            ours = ['models--Systran--faster-whisper-base',
                    'models--Systran--faster-distil-whisper-small.en',
                    'models--openai--whisper-tiny']
            theirs = ['models--openai--clip-vit-base-patch32',
                      'models--pyannote--speaker-diarization-community-1',
                      '.locks', 'models--meta-llama--Llama-3']
            for name in ours + theirs:
                (hub / name).mkdir()
                (hub / name / 'blob').write_bytes(b'x' * 10)
            with mock.patch.object(uninstall, '_hf_hub_root', return_value=hub):
                selected = {p.name for p, _ in uninstall._our_cached_models()}
        self.assertEqual(selected, set(ours))
        for name in theirs:
            self.assertNotIn(name, selected, f'must never select {name}')

    def test_no_models_selected_when_cache_absent(self):
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import uninstall
        with mock.patch.object(uninstall, '_hf_hub_root', return_value=Path('/nonexistent-xyz')):
            self.assertEqual(uninstall._our_cached_models(), [])

    def test_declining_removes_nothing(self):
        # Answering "no" at the first prompt must leave everything untouched.
        import io
        import contextlib
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import uninstall
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'whisperkey'
            cfg.mkdir()
            (cfg / 'user_settings.yaml').write_text('x', encoding='utf-8')
            with mock.patch.object(uninstall, 'get_user_app_data_path', return_value=str(cfg)),                  mock.patch.object(uninstall, '_our_cached_models', return_value=[]),                  mock.patch.object(uninstall, '_confirm', return_value=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = uninstall.run_uninstall()
            self.assertEqual(rc, 1)
            self.assertTrue(cfg.exists(), 'declining must not delete anything')
            self.assertTrue((cfg / 'user_settings.yaml').exists())

    def test_models_need_their_own_confirmation(self):
        # Confirming the settings removal must NOT imply consent to delete
        # gigabytes of models -- that is a second, separate decision.
        import io
        import contextlib
        import tempfile
        import unittest.mock as mock
        from pathlib import Path
        from whisper_key import uninstall
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'whisperkey'; cfg.mkdir()
            model = Path(d) / 'models--Systran--faster-whisper-base'; model.mkdir()
            (model / 'model.bin').write_bytes(b'x' * 100)
            answers = iter([True, False])   # yes to settings, NO to models
            with mock.patch.object(uninstall, 'get_user_app_data_path', return_value=str(cfg)),                  mock.patch.object(uninstall, '_our_cached_models', return_value=[(model, 100)]),                  mock.patch.object(uninstall, '_confirm', side_effect=lambda *a: next(answers)):
                with contextlib.redirect_stdout(io.StringIO()):
                    uninstall.run_uninstall()
            self.assertFalse(cfg.exists(), 'settings should have been removed')
            self.assertTrue(model.exists(), 'models must survive a "no" on the second prompt')

    def test_clean_machine_reports_nothing_to_do(self):
        import io
        import contextlib
        import unittest.mock as mock
        from whisper_key import uninstall
        with mock.patch.object(uninstall, 'get_user_app_data_path', return_value='/nonexistent-xyz'),              mock.patch.object(uninstall, '_our_cached_models', return_value=[]),              mock.patch.object(uninstall, '_confirm', side_effect=AssertionError('must not prompt')):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = uninstall.run_uninstall()
        self.assertEqual(rc, 0)
        self.assertIn('already clean', buf.getvalue())


class UserReportedSeptemberTests(unittest.TestCase):
    """Issues #9-#13, reported by users running 0.18.3."""

    # --- #9: filler stripping destroyed inline-formatting newlines ---
    def _fmt_cfg(self, **extra):
        cfg = {'inline_formatting': True, 'inline_formatting_absorb_punctuation': True,
               'inline_formatting_replacements': [
                   {'phrase': 'period', 'replacement': '. '},
                   {'phrase': 'new line', 'replacement': LF},
                   {'phrase': 'new paragraph', 'replacement': LF + LF}]}
        cfg.update(extra)
        return cfg

    def test_filler_stripping_preserves_line_structure(self):
        from whisper_key.text_postprocess import postprocess
        text = 'alpha like period new paragraph bravo new line charlie'
        without = postprocess(text, self._fmt_cfg(strip_filler_words=False))
        with_strip = postprocess(text, self._fmt_cfg(strip_filler_words=True))
        # The ONLY difference may be the filler word itself.
        self.assertEqual(without.replace(' like', ''), with_strip)
        self.assertIn(LF + LF, with_strip, 'paragraph break must survive (issue #9)')

    def test_filler_stripping_still_removes_fillers(self):
        from whisper_key.text_postprocess import postprocess
        got = postprocess('um hello uh there you know friend', {'strip_filler_words': True})
        for filler in ('um ', 'uh ', 'you know'):
            self.assertNotIn(filler, got)
        self.assertIn('hello', got)

    def test_filler_stripping_does_not_collapse_paragraphs(self):
        # The second half of the bug: even newlines that survived the filler
        # pattern were flattened by a blanket whitespace collapse.
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('one' + LF + LF + 'two', {'strip_filler_words': True}),
                         'one' + LF + LF + 'two')
        # Runs of plain spaces SHOULD still collapse.
        self.assertEqual(postprocess('one    two', {'strip_filler_words': True}), 'one two')

    # --- #10: --history killed its own window ---
    def test_window_launchers_return_their_thread(self):
        # main.py waits on this thread. Returning None again would restore the
        # bug: the window lives on a daemon thread and sys.exit kills it.
        import inspect
        for module, func in (('history_window', 'show_history'),
                             ('cheat_sheet', 'show_cheat_sheet')):
            try:
                mod = __import__('whisper_key.' + module, fromlist=[func])
            except Exception:
                self.skipTest(module + ' not importable on this platform')
            source = inspect.getsource(getattr(mod, func))
            self.assertIn('return thread', source,
                          func + ' must return its thread so the CLI can join it (issue #10)')

    def test_history_cli_joins_instead_of_sleeping(self):
        source = (ROOT / 'src' / 'whisper_key' / 'main.py').read_text(encoding='utf-8')
        block = source[source.index('if args.history:'):source.index('if args.enable_autostart:')]
        self.assertIn('.join()', block)
        self.assertNotIn('time.sleep(0.5)', block,
                         'sleeping then exiting kills the daemon window (issue #10)')

    # --- #12: clipboard-free dictation leaked to the clipboard ---
    def _clipboard(self, method, also_copy):
        # clipboard_manager pulls the platform keyboard backend and PIL,
        # neither of which the lean CI env installs.
        try:
            from whisper_key.clipboard_manager import ClipboardManager
        except Exception:
            self.skipTest('clipboard_manager not importable in this env')
        c = ClipboardManager.__new__(ClipboardManager)
        c.delivery_method = method
        c.type_also_copy_to_clipboard = also_copy
        return c

    def test_silent_copy_policy(self):
        self.assertFalse(self._clipboard('type', False).silent_copy_allowed,
                         'clipboard-free dictation must stay clipboard-free (issue #12)')
        self.assertTrue(self._clipboard('type', True).silent_copy_allowed)
        # Paste delivery needs the clipboard by definition.
        self.assertTrue(self._clipboard('paste', False).silent_copy_allowed)

    def test_fallback_window_respects_clipboard_policy(self):
        import inspect
        from whisper_key import fallback_window
        params = inspect.signature(fallback_window.FallbackWindow.show).parameters
        self.assertIn('allow_clipboard', params)
        body = inspect.getsource(fallback_window.FallbackWindow._run_window)
        self.assertIn('if allow_clipboard:', body,
                      'the popup must not auto-copy when copying is off')
        # The explicit Copy button stays unconditional - that is the user asking.
        self.assertIn('def _copy_again', body)

    def test_recovery_paths_check_the_policy(self):
        source = (ROOT / 'src' / 'whisper_key' / 'state_manager.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('silent_copy_allowed'), 2,
                         'both recovery paths (suppress + no-text-field) must check it')

    # --- #11: an app rule silencing paste looked like a broken app ---
    def test_copy_only_is_announced_once_per_rule(self):
        import unittest.mock as mock
        try:
            from whisper_key.state_manager import StateManager
        except Exception:
            self.skipTest('state_manager not importable on this platform')
        sm = StateManager.__new__(StateManager)
        sm.logger = __import__('logging').getLogger('test')
        sm.system_tray = mock.Mock()
        rule = {'match': ['code.exe', 'cursor.exe'], 'auto_paste': False}
        sm._announce_copy_only(rule)
        sm._announce_copy_only(rule)                    # same rule again
        sm._announce_copy_only({'match': ['slack.exe']})
        self.assertEqual(sm.system_tray.notify.call_count, 2,
                         'once per rule, not once per dictation')
        said = sm.system_tray.notify.call_args_list[0].args[0]
        self.assertIn('code.exe', said)
        self.assertIn('app_rules.yaml', said, 'tell them where to change it')

    # --- #13: macOS 27 SIGTRAP from off-main-thread tray writes ---
    def test_platform_exposes_ui_thread_marshal(self):
        # Importing the platform package loads the OS backend (win32api /
        # AppKit), which the lean CI env doesn't install.
        try:
            from whisper_key.platform import app as platform_app
        except Exception:
            self.skipTest('platform backend not importable in this env')
        self.assertTrue(hasattr(platform_app, 'run_on_ui_thread'))
        ran = []
        platform_app.run_on_ui_thread(lambda: ran.append(1))
        self.assertEqual(ran, [1], 'must actually run the callable')

    def test_no_unguarded_tray_writes_remain(self):
        # Every AppKit-touching write must go through _on_ui_thread. A direct
        # assignment from a worker thread is an instant SIGTRAP on macOS 27.
        import re
        source = (ROOT / 'src' / 'whisper_key' / 'system_tray.py').read_text(encoding='utf-8')
        offenders = []
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if re.match(r'^self[.]icon[.](icon|menu|title)\s*=', stripped):
                offenders.append(str(i) + ': ' + stripped)
            if stripped.startswith('self.icon.notify(') and '_on_ui_thread' not in line:
                offenders.append(str(i) + ': ' + stripped)
        self.assertEqual(offenders, [],
                         'tray writes must be marshalled to the UI thread (issue #13)')

    def test_macos_marshal_uses_main_queue(self):
        source = (ROOT / 'src' / 'whisper_key' / 'platform' / 'macos' / 'app.py').read_text(encoding='utf-8')
        self.assertIn('NSThread.isMainThread()', source, 'fast path when already on main')
        self.assertIn('mainQueue', source, 'must dispatch to the main queue')


class UserReportedLateSeptemberTests(unittest.TestCase):
    """Issues #14 and #15, reported by users running 0.19.0."""

    # Load a platform backend file directly, so it can be exercised on any OS
    # with its OS-only dependencies faked out.
    def _load(self, relative_path, name):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            name, str(ROOT / 'src' / 'whisper_key' / relative_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # --- #15: pip-installed CUDA libraries were on no DLL search path ---
    def test_nvidia_dll_dirs_are_found_in_site_packages(self):
        import tempfile
        from whisper_key.utils import find_nvidia_dll_dirs
        with tempfile.TemporaryDirectory() as root:
            for lib in ('cublas', 'cudnn', 'cuda_runtime'):
                (Path(root) / 'nvidia' / lib / 'bin').mkdir(parents=True)
            (Path(root) / 'nvidia' / 'cudnn' / 'include').mkdir()
            found = find_nvidia_dll_dirs([root, root])  # duplicate root on purpose
        names = sorted(Path(d).parent.name for d in found)
        self.assertEqual(names, ['cublas', 'cuda_runtime', 'cudnn'], 'each bin dir exactly once')

    def test_nvidia_dll_path_registers_both_loaders_on_windows(self):
        import unittest.mock as mock
        from whisper_key import utils
        dirs = [os.path.join('sp', 'nvidia', 'cublas', 'bin'),
                os.path.join('sp', 'nvidia', 'cudnn', 'bin')]
        added = []
        with mock.patch.object(utils.sys, 'platform', 'win32'), \
             mock.patch.object(utils, 'find_nvidia_dll_dirs', return_value=dirs), \
             mock.patch.object(utils.os, 'add_dll_directory', added.append, create=True), \
             mock.patch.dict(os.environ, {'PATH': 'existing'}):
            utils.setup_nvidia_dll_path()
            utils.setup_nvidia_dll_path()  # idempotent: no PATH growth
            path_parts = os.environ['PATH'].split(os.pathsep)
        # add_dll_directory serves ctypes/extension loads; PATH serves the plain
        # LoadLibrary calls ctranslate2 and cuDNN make. Both are needed.
        self.assertEqual(added[:2], dirs)
        self.assertEqual(path_parts, dirs + ['existing'])

    def test_nvidia_dll_path_is_a_no_op_off_windows(self):
        import unittest.mock as mock
        from whisper_key import utils
        with mock.patch.object(utils.sys, 'platform', 'darwin'), \
             mock.patch.object(utils, 'find_nvidia_dll_dirs') as finder:
            utils.setup_nvidia_dll_path()
        finder.assert_not_called()

    def test_dll_path_is_set_up_before_the_ml_stack_imports(self):
        source = (ROOT / 'src' / 'whisper_key' / 'main.py').read_text(encoding='utf-8')
        self.assertLess(source.index('setup_nvidia_dll_path()'),
                        source.index('from .whisper_engine import'))

    def _gpu_probe(self, loadable, compute_types=('float16',)):
        import types
        import unittest.mock as mock
        gpu = self._load('platform/windows/gpu.py', 'wk_gpu_probe')

        def win_dll(name, winmode=None):
            # winmode=0 means the plain LoadLibrary search (PATH included),
            # which is what ctranslate2 itself uses.
            self.assertEqual(winmode, 0)
            if name not in loadable:
                raise OSError(f'{name} not found')
        gpu.ctypes = types.SimpleNamespace(WinDLL=win_dll)
        ct2 = types.ModuleType('ctranslate2')
        ct2.get_supported_compute_types = lambda device: list(compute_types)
        patcher = mock.patch.dict(sys.modules, {'ctranslate2': ct2})
        patcher.start()
        self.addCleanup(patcher.stop)
        return gpu

    def test_gpu_probe_fails_without_cublas_and_cudnn(self):
        import io
        import contextlib
        # The reported machine: driver present, no cuBLAS/cuDNN anywhere. The
        # probe used to pass here and onboarding switched the app to CUDA.
        gpu = self._gpu_probe(loadable=())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertFalse(gpu._test_ct2_gpu('cuda'))
        self.assertIn('cublas64_12.dll', out.getvalue(), 'name what is missing')

    def test_gpu_probe_passes_when_every_library_loads(self):
        gpu = self._gpu_probe(loadable=('cublas64_12.dll', 'cublasLt64_12.dll', 'cudnn64_9.dll',
                                        'cudnn_ops64_9.dll', 'cudnn_cnn64_9.dll'))
        self.assertTrue(gpu._test_ct2_gpu('cuda'))
        self.assertEqual(gpu._missing_cuda_libraries(), [])

    def test_gpu_probe_reports_a_single_missing_cudnn_part(self):
        gpu = self._gpu_probe(loadable=('cublas64_12.dll', 'cublasLt64_12.dll',
                                        'cudnn64_9.dll', 'cudnn_ops64_9.dll'))
        self.assertEqual(gpu._missing_cuda_libraries(), ['cudnn_cnn64_9.dll'])

    def test_rocm_builds_are_not_held_to_nvidia_libraries(self):
        import unittest.mock as mock
        gpu = self._gpu_probe(loadable=())
        self.assertTrue(gpu._test_ct2_gpu('rocm'))
        with mock.patch.object(gpu, '_detect_ct2_variant', return_value='rocm'):
            self.assertEqual(gpu.missing_gpu_libraries(), [])
        with mock.patch.object(gpu, '_detect_ct2_variant', return_value='cuda'):
            self.assertIn('cudnn64_9.dll', gpu.missing_gpu_libraries())

    def test_macos_gpu_mirror_has_the_same_api(self):
        mac = self._load('platform/macos/gpu.py', 'wk_gpu_mac')
        self.assertEqual(mac.missing_gpu_libraries(), [])

    # whisper_engine imports numpy, which refuses a second import per process.
    # Import it BEFORE patch.dict snapshots sys.modules so the restore keeps it.
    def _preload_numpy(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest('numpy not installed')

    def _fake_hardware_detection(self, missing):
        import types
        fake = types.ModuleType('whisper_key.hardware_detection')
        fake.missing_gpu_libraries = lambda: list(missing)
        return fake

    def test_cuda_engine_fails_fast_instead_of_hanging(self):
        # Existing configs already say device: cuda. With the libraries absent the
        # model loads, then the first dictation hangs; the engine must refuse up
        # front so main's GPU-failure path can offer setup or CPU.
        self._preload_numpy()
        import contextlib
        import io
        import types
        import unittest.mock as mock
        fake_fw = types.ModuleType('faster_whisper')
        fake_fw.WhisperModel = mock.Mock(name='WhisperModel')
        with mock.patch.dict(sys.modules, {
                'faster_whisper': fake_fw,
                'whisper_key.hardware_detection': self._fake_hardware_detection(['cudnn_ops64_9.dll'])}):
            sys.modules.pop('whisper_key.whisper_engine', None)
            from whisper_key.whisper_engine import WhisperEngine
            # The engine prints emoji progress lines; main() switches stdout to
            # UTF-8 first, but a cp1252 test console (Windows CI) would choke.
            with self.assertRaises(RuntimeError) as ctx, contextlib.redirect_stdout(io.StringIO()):
                WhisperEngine(model_key='base', device='cuda', compute_type='float16')
            fake_fw.WhisperModel.assert_not_called()
        self.assertIn('cudnn_ops64_9.dll', str(ctx.exception))

    def test_cpu_engine_skips_the_gpu_check(self):
        self._preload_numpy()
        import contextlib
        import io
        import types
        import unittest.mock as mock
        fake_fw = types.ModuleType('faster_whisper')
        fake_fw.WhisperModel = mock.Mock(name='WhisperModel')
        with mock.patch.dict(sys.modules, {
                'faster_whisper': fake_fw,
                'whisper_key.hardware_detection': self._fake_hardware_detection(['cublas64_12.dll'])}):
            sys.modules.pop('whisper_key.whisper_engine', None)
            from whisper_key.whisper_engine import WhisperEngine
            with contextlib.redirect_stdout(io.StringIO()):  # emoji vs a cp1252 console
                WhisperEngine(model_key='base', device='cpu', compute_type='int8')
            fake_fw.WhisperModel.assert_called_once()

    def test_gpu_recovery_prompt_is_skipped_without_a_console(self):
        # The fail-fast check above lands in this prompt. Under pythonw/autostart
        # nobody can answer it, so it must fall back to CPU rather than wait.
        import types
        import io
        import contextlib
        import unittest.mock as mock
        reimport_under(self, fake_platform_modules(getch=lambda: self.fail('must not wait for a keypress')))
        from whisper_key import onboarding
        with mock.patch.object(onboarding.sys, 'stdin', None), \
             mock.patch.object(onboarding, 'prompt_choice') as prompt, \
             contextlib.redirect_stdout(io.StringIO()):
            onboarding.handle_gpu_failure(RuntimeError('CUDA libraries not found'), mock.Mock())
        prompt.assert_not_called()

    def test_doctor_flags_missing_cuda_libraries(self):
        import io
        import contextlib
        import unittest.mock as mock
        from whisper_key import doctor
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with mock.patch.dict(sys.modules, {
                    'whisper_key.hardware_detection': self._fake_hardware_detection(['cublas64_12.dll'])}):
                self.assertEqual(doctor._check_gpu_libraries(), 1)
            with mock.patch.dict(sys.modules, {
                    'whisper_key.hardware_detection': self._fake_hardware_detection([])}):
                self.assertEqual(doctor._check_gpu_libraries(), 0)
        self.assertIn('cublas64_12.dll', out.getvalue())

    # --- #14: macOS abort (exit 134) from Tk vs pyobjc's NSApplication ---
    def test_platform_app_mirrors_declare_the_tk_constraint(self):
        import re
        for plat, expected in (('macos', 'True'), ('windows', 'False')):
            source = (ROOT / 'src' / 'whisper_key' / 'platform' / plat / 'app.py').read_text(encoding='utf-8')
            self.assertRegex(source, r'(?m)^TK_MAIN_THREAD_ONLY = ' + re.escape(expected) + '$',
                             plat + ' app.py must declare TK_MAIN_THREAD_ONLY (mirrored API)')

    def test_tk_constraint_helper(self):
        import unittest.mock as mock
        from whisper_key.utils import tk_requires_main_thread
        for constraint in (True, False):
            with mock.patch.dict(sys.modules, fake_platform_modules(TK_MAIN_THREAD_ONLY=constraint)):
                self.assertIs(tk_requires_main_thread(), constraint)

    def test_macos_setup_lets_tk_create_the_shared_application(self):
        # Whoever calls sharedApplication() first decides NSApp's class. Tk must
        # win, or its drawing code sends TKApplication-only selectors to a plain
        # NSApplication and the process aborts.
        import types
        import unittest.mock as mock
        order = []

        class FakeNSObject:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                return self

        class FakeNSApp:
            def setActivationPolicy_(self, policy):
                pass

            def setDelegate_(self, delegate):
                pass

        class FakeNSApplication:
            @staticmethod
            def sharedApplication():
                order.append('sharedApplication')
                return FakeNSApp()

        class FakeTk:
            def __init__(self):
                order.append('tk.Tk')

            def withdraw(self):
                pass

        appkit = types.ModuleType('AppKit')
        appkit.NSApplication = FakeNSApplication
        appkit.NSApplicationActivationPolicyAccessory = 1
        appkit.NSEventMaskAny = 0
        appkit.NSDefaultRunLoopMode = 'default'
        foundation = types.ModuleType('Foundation')
        foundation.NSDate = foundation.NSOperationQueue = foundation.NSThread = mock.Mock()
        foundation.NSObject = FakeNSObject
        tkinter = types.ModuleType('tkinter')
        tkinter.Tk = FakeTk
        with mock.patch.dict(sys.modules, {'AppKit': appkit, 'Foundation': foundation, 'tkinter': tkinter}):
            mac_app = self._load('platform/macos/app.py', 'wk_mac_app')
            mac_app.setup()
        self.assertEqual(order, ['tk.Tk', 'sharedApplication'])
        self.assertIsNotNone(mac_app._tk_preload_root, 'the hidden root must stay alive')

    def test_overlay_stands_down_where_tk_is_main_thread_only(self):
        import unittest.mock as mock
        from whisper_key.level_overlay import LevelOverlay
        overlay = LevelOverlay(level_provider=lambda: 0.0)
        overlay._available = True  # as if tkinter were importable
        with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=True), \
             mock.patch('whisper_key.level_overlay.threading.Thread') as thread:
            overlay.start()
        thread.assert_not_called()
        self.assertFalse(overlay._available, 'every later overlay call must be a no-op')
        overlay.show_recording()
        overlay.flash_failure('still safe')

    def test_welcome_runs_inline_on_macos_and_threaded_elsewhere(self):
        import threading
        import unittest.mock as mock
        from whisper_key import first_run
        seen = []
        done = threading.Event()

        def fake_run(on_close, hotkey_label, shutdown_event):
            seen.append(threading.current_thread() is threading.main_thread())
            done.set()
        event = threading.Event()
        with mock.patch.object(first_run, '_run_welcome', fake_run):
            with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=True):
                first_run.show_welcome_window(shutdown_event=event)
            with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=False):
                done.clear()
                first_run.show_welcome_window(shutdown_event=event)
                self.assertTrue(done.wait(2))
        self.assertEqual(seen, [True, False])

    # A just-enough tkinter for the welcome window. mainloop() models the real
    # one: it only returns once quit() has been called, because with the macOS
    # preload root alive, destroy() alone never ends it.
    def _run_welcome_with_fake_tk(self, drive, shutdown_event=None):
        import types
        import unittest.mock as mock
        calls = []

        class Widget:
            def __init__(self, *args, **kwargs):
                pass

            def __getattr__(self, name):
                return lambda *args, **kwargs: None

        class BooleanVar(Widget):
            def get(self):
                return False

        class Tk(Widget):
            def __init__(self):
                self.after_callbacks = []
                self.close_handler = None

            def protocol(self, name, handler):
                self.close_handler = handler

            def after(self, ms, callback):
                self.after_callbacks.append(callback)

            def quit(self):
                calls.append('quit')

            def destroy(self):
                calls.append('destroy')

            def mainloop(self):
                calls.append('mainloop')
                drive(self)
                if 'quit' not in calls:
                    raise AssertionError('mainloop() would never return: quit() was not called')
                calls.append('mainloop returned')

        tkinter = types.ModuleType('tkinter')
        tkinter.Tk = Tk
        tkinter.Frame = tkinter.Label = tkinter.Button = tkinter.Checkbutton = Widget
        tkinter.BooleanVar = BooleanVar
        on_close = mock.Mock()
        from whisper_key import first_run
        with mock.patch.dict(sys.modules, {'tkinter': tkinter}), \
             mock.patch.object(first_run, 'mark_first_run_complete') as mark:
            first_run._run_welcome(on_close, 'CTRL+WIN', shutdown_event)
        return calls, on_close, mark

    def test_welcome_dismissal_quits_before_destroying(self):
        calls, on_close, mark = self._run_welcome_with_fake_tk(lambda root: root.close_handler())
        self.assertEqual(calls, ['mainloop', 'quit', 'mainloop returned', 'destroy'])
        mark.assert_called_once()
        on_close.assert_called_once()

    def test_welcome_closes_on_shutdown_without_counting_as_dismissed(self):
        import threading
        event = threading.Event()

        def drive(root):
            event.set()  # SIGTERM arrives while the window is open
            for callback in list(root.after_callbacks):
                callback()
        calls, on_close, mark = self._run_welcome_with_fake_tk(drive, shutdown_event=event)
        self.assertIn('quit', calls)
        self.assertEqual(calls[-1], 'destroy')
        mark.assert_not_called()
        on_close.assert_not_called()

    def test_main_hands_the_welcome_window_the_shutdown_event(self):
        source = (ROOT / 'src' / 'whisper_key' / 'main.py').read_text(encoding='utf-8')
        call = source[source.index('show_welcome_window('):]
        call = call[:call.index(')\n')]
        self.assertIn('shutdown_event=shutdown_event', call)

    # --- #14 follow-through: every other Tk window on macOS ---
    def test_windows_stay_in_process_where_tk_threads_are_fine(self):
        import unittest.mock as mock
        from whisper_key import window_launcher
        with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=False), \
             mock.patch.object(window_launcher.subprocess, 'Popen') as popen:
            self.assertFalse(window_launcher.open_in_child_process('cheat-sheet'))
        popen.assert_not_called()

    def test_macos_windows_open_in_a_child_with_the_payload_on_stdin(self):
        import json
        import unittest.mock as mock
        from whisper_key import window_launcher
        child = mock.Mock()
        with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=True), \
             mock.patch.object(window_launcher.subprocess, 'Popen', return_value=child) as popen, \
             mock.patch.object(window_launcher.threading, 'Thread'):
            handled = window_launcher.open_in_child_process('fallback', {'transcript': 'secret words'})
        self.assertTrue(handled)
        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ['--window', 'fallback'])
        self.assertNotIn('secret words', ' '.join(command), 'transcripts must not go in argv')
        sent = json.loads(child.stdin.write.call_args.args[0].decode('utf-8'))
        self.assertEqual(sent['transcript'], 'secret words')
        child.stdin.close.assert_called_once()

    def test_failed_spawn_never_falls_back_to_in_process_tk(self):
        import unittest.mock as mock
        from whisper_key import window_launcher
        with mock.patch('whisper_key.utils.tk_requires_main_thread', return_value=True), \
             mock.patch.object(window_launcher.subprocess, 'Popen', side_effect=OSError('nope')):
            self.assertTrue(window_launcher.open_in_child_process('add-word'))

    def test_child_runs_each_window_blocking_on_its_main_thread(self):
        import io
        import unittest.mock as mock
        from whisper_key import window_launcher
        for name, target in (('cheat-sheet', 'whisper_key.cheat_sheet.show_cheat_sheet'),
                             ('add-word', 'whisper_key.dictionary.show_add_word_dialog'),
                             ('history', 'whisper_key.history_window.show_history')):
            with mock.patch(target) as show:
                self.assertEqual(window_launcher.run_window(name, io.StringIO('')), 0)
            self.assertTrue(show.call_args.kwargs.get('blocking'), name + ' must run blocking')
        with mock.patch('whisper_key.fallback_window.FallbackWindow._run_window') as run:
            code = window_launcher.run_window(
                'fallback', io.StringIO('{"transcript": "hi", "reason": "r", "allow_clipboard": false}'))
        self.assertEqual(code, 0)
        run.assert_called_once_with('hi', 'r', False)
        self.assertEqual(window_launcher.run_window('fallback', io.StringIO('not json')), 1)

    def test_fallback_window_hands_off_instead_of_threading(self):
        import unittest.mock as mock
        from whisper_key.fallback_window import FallbackWindow
        window = FallbackWindow()
        window._available = True
        with mock.patch('whisper_key.window_launcher.open_in_child_process', return_value=True) as launch, \
             mock.patch('whisper_key.fallback_window.threading.Thread') as thread:
            window.show('dictated text', allow_clipboard=False)
        thread.assert_not_called()
        payload = launch.call_args.args[1]
        self.assertEqual(payload['transcript'], 'dictated text')
        self.assertFalse(payload['allow_clipboard'])
        self.assertTrue(payload['reason'], 'the default reason must travel with it')

    def test_window_flag_choices_match_the_launcher(self):
        from whisper_key.window_launcher import WINDOW_NAMES
        source = (ROOT / 'src' / 'whisper_key' / 'main.py').read_text(encoding='utf-8')
        line = source[source.index("'--window'"):]
        line = line[:line.index('\n')]
        for name in WINDOW_NAMES:
            self.assertIn(repr(name), line)


class WisprStyleFeatureTests(unittest.TestCase):
    """Wispr Flow–style editing added in 0.20.0: backtrack, stutters, spoken
    lists, styles, snippets, paste-last, double-tap lock, whisper mode."""

    # --- Backtrack ---
    def test_backtrack_replaces_the_value_it_corrects(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        cases = {
            "Let's meet at 2, actually 3 tomorrow.": "Let's meet at 3 tomorrow.",
            'Tuesday, no wait, Wednesday works.': 'Wednesday works.',
            'Send 5 dollars, I mean 6.': 'Send 6 dollars.',
            'I have 2 kids, sorry, 3 kids.': 'I have 3 kids.',
            'At 2pm, actually 3pm works.': 'At 3pm works.',
            'We ship in March, no wait, April. It costs 5, actually 7.': 'We ship in April. It costs 7.',
        }
        for spoken, typed in cases.items():
            self.assertEqual(apply_backtrack(spoken), typed, spoken)

    def test_backtrack_leaves_ordinary_prose_alone(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        for text in ('I actually like it.', 'Sorry, 3 people are here.',
                     'It was 2. Actually 3 would be better.',   # never reaches across a sentence
                     'Meet Tuesday at 2, actually Friday.'):    # class mismatch picks the weekday
            expected = 'Meet Friday at 2.' if 'Friday' in text else text
            self.assertEqual(apply_backtrack(text), expected, text)

    def test_backtrack_is_linear_on_huge_dictations(self):
        import time
        from whisper_key.dictation_cleanup import apply_backtrack
        text = 'I actually think ' * 20000 + 'at 2 actually 3'
        start = time.monotonic()
        self.assertTrue(apply_backtrack(text).endswith('at 3'))
        self.assertLess(time.monotonic() - start, 2.0, 'must stay O(n)')

    def test_backtrack_runs_only_when_enabled(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('at 2 actually 3', {'voice_editing': False}), 'at 2 actually 3')
        self.assertEqual(postprocess('at 2 actually 3', {'backtrack': {'enabled': True}}), 'at 3')
        self.assertEqual(postprocess('at 2 swap 3', {'backtrack': {'enabled': True, 'cues': ['swap']}}), 'at 3')

    # --- Stutters ---
    def test_repeated_words_collapse_but_real_doubles_stay(self):
        from whisper_key.dictation_cleanup import remove_repeated_words
        self.assertEqual(remove_repeated_words('I I think the the cat'), 'I think the cat')
        self.assertEqual(remove_repeated_words('We, we should go'), 'We should go')
        for keep in ('I had had enough', 'very very good', 'Bye bye', '11 11'):
            self.assertEqual(remove_repeated_words(keep), keep)

    # --- Spoken lists ---
    def test_spoken_list_becomes_a_list(self):
        from whisper_key.dictation_cleanup import apply_list_formatting
        self.assertEqual(apply_list_formatting('My list: first, milk. Second, eggs. Third, bread.'),
                         'My list:\n1. Milk\n2. Eggs\n3. Bread')
        self.assertEqual(apply_list_formatting('One, buy milk. Two, call mom, and three, pay rent.'),
                         '1. Buy milk\n2. Call mom\n3. Pay rent')
        self.assertEqual(apply_list_formatting('first, milk. second, eggs', style='bullets'),
                         '- Milk\n- Eggs')

    def test_prose_that_counts_is_not_a_list(self):
        from whisper_key.dictation_cleanup import apply_list_formatting
        for text in ('One of the two options is fine.', 'First, we go.',
                     'First of all, hello. Second, world.'):
            self.assertEqual(apply_list_formatting(text), text)

    def test_list_takes_no_closing_period(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('first, milk. second, eggs.',
                                     {'list_formatting': True, 'ensure_punctuation': True}),
                         '1. Milk\n2. Eggs')

    # --- Lowercase / styles ---
    def test_lowercase_keeps_acronyms_mixed_case_and_taught_terms(self):
        from whisper_key.dictation_cleanup import apply_lowercase
        self.assertEqual(apply_lowercase('Hello There, NASA and iPhone and Rohit.', protected=['Rohit']),
                         'hello there, NASA and iPhone and Rohit.')

    def test_style_resolution(self):
        from whisper_key.styles import resolve_style
        self.assertTrue(resolve_style('very casual')['lowercase'])
        self.assertEqual(resolve_style('nope'), {}, 'unknown styles are ignored')
        self.assertEqual(resolve_style(''), {})
        custom = resolve_style('shouty', {'styles': {'shouty': {'capitalize_first': True, 'ollama': True}}})
        self.assertEqual(custom, {'capitalize_first': True}, 'a style can only set formatting toggles')

    def test_style_precedence(self):
        from whisper_key.app_rules import effective_postprocess_config
        global_cfg = {'style': 'formal', 'capitalize_first': False}
        cfg = effective_postprocess_config(global_cfg)
        self.assertTrue(cfg['capitalize_first'], 'the global style wins over global toggles')
        self.assertNotIn('style', cfg, 'resolved once, so postprocess() cannot re-apply it')
        cfg = effective_postprocess_config(global_cfg, {'style': 'very_casual'})
        self.assertTrue(cfg['lowercase'])
        self.assertFalse(cfg['ensure_punctuation'], "the app's style beats the global one")
        cfg = effective_postprocess_config(global_cfg, {'style': 'very_casual', 'lowercase': False})
        self.assertFalse(cfg['lowercase'], "a rule's own toggle beats its style")

    def test_postprocess_applies_a_style_key(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('Hello There', {'style': 'formal'}), 'Hello There.')
        self.assertEqual(postprocess('Hello There.', {'style': 'very_casual'}), 'hello there')

    def test_shipped_app_rules_use_known_styles(self):
        from ruamel.yaml import YAML
        from whisper_key.styles import STYLE_PRESETS
        rules = YAML().load((ROOT / 'src' / 'whisper_key' / 'app_rules.defaults.yaml').read_text(encoding='utf-8'))['rules']
        styles = [r['style'] for r in rules if 'style' in r]
        self.assertTrue(styles)
        for style in styles:
            self.assertIn(style, STYLE_PRESETS)

    # --- Snippets ---
    _SNIPPETS = [{'trigger': 'my signature', 'expansion': 'Best,\nRohit'},
                 {'trigger': 'my work signature', 'expansion': 'Rohit B.\nEngineer'},
                 {'trigger': 'my address', 'expansion': '1 Main St', 'mode': 'alone'},
                 {'trigger': 'weird', 'expansion': r'\1 $0 (.*)'},
                 {'nonsense': True}, 'not even a dict']

    def test_snippet_expands_inline(self):
        from whisper_key.snippets import expand_snippets
        self.assertEqual(expand_snippets('Thanks. My signature.', self._SNIPPETS), ('Thanks. Best,\nRohit', False))
        self.assertEqual(expand_snippets('Thanks. my work signature', self._SNIPPETS)[0],
                         'Thanks. Rohit B.\nEngineer', 'the longer trigger wins')

    def test_whole_utterance_snippet_is_delivered_verbatim(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'capitalize_first': True, 'ensure_punctuation': True, 'snippets': self._SNIPPETS}
        self.assertEqual(postprocess('My signature.', cfg), 'Best,\nRohit')
        self.assertEqual(postprocess('My address', cfg), '1 Main St')
        self.assertEqual(postprocess('send my address now', cfg), 'Send my address now.',
                         '"alone" snippets never fire mid-sentence')

    def test_snippet_expansion_is_literal_and_variables_fill_in(self):
        import datetime
        from whisper_key.snippets import expand_snippets
        self.assertEqual(expand_snippets('weird', self._SNIPPETS)[0], r'\1 $0 (.*)')
        today = datetime.date.today().strftime('%Y-%m-%d')
        text, _ = expand_snippets('stamp', [{'trigger': 'stamp', 'expansion': 'On ${date}'}])
        self.assertEqual(text, 'On ' + today)

    def test_lowercase_style_never_touches_a_snippet(self):
        from whisper_key.text_postprocess import postprocess
        cfg = {'style': 'very_casual', 'snippets': self._SNIPPETS}
        self.assertEqual(postprocess('Thanks. My signature.', cfg), 'thanks. Best,\nRohit')

    # --- Double-tap lock ---
    def _latch(self, recording=True):
        from whisper_key.hotkey_gestures import TapLatch
        now = [0.0]
        timers = []

        class FakeTimer:
            def __init__(self, seconds, callback):
                self.callback, self.cancelled = callback, False
                timers.append(self)

            def cancel(self):
                self.cancelled = True
        events = []
        latch = TapLatch(start=lambda: events.append('start'), stop=lambda: events.append('stop'),
                         window_ms=400, is_recording=lambda: recording,
                         clock=lambda: now[0], timer_factory=FakeTimer)
        return latch, events, now, timers

    def test_hold_is_plain_push_to_talk(self):
        latch, events, now, _ = self._latch()
        latch.press()
        now[0] = 2.0
        latch.release()
        self.assertEqual(events, ['start', 'stop'])
        self.assertEqual(latch.state, latch.IDLE)

    def test_single_quick_tap_stops_after_the_window(self):
        latch, events, now, timers = self._latch()
        latch.press()
        now[0] = 0.1
        latch.release()
        self.assertEqual(events, ['start'], 'must not stop inside the double-tap window')
        timers[-1].callback()
        self.assertEqual(events, ['start', 'stop'])

    def test_double_tap_locks_and_a_third_tap_stops(self):
        latch, events, now, timers = self._latch()
        latch.press(); now[0] = 0.1; latch.release()
        now[0] = 0.2; latch.press()
        self.assertTrue(timers[-1].cancelled)
        self.assertEqual(latch.state, latch.LATCHED)
        now[0] = 0.3; latch.release()
        self.assertEqual(events, ['start'], 'releasing while locked does nothing')
        now[0] = 9.0; latch.press()
        self.assertEqual(events, ['start', 'stop'])

    def test_lock_resyncs_when_recording_ended_elsewhere(self):
        latch, events, now, _ = self._latch(recording=False)
        latch.state = latch.LATCHED          # e.g. the silence timeout stopped it
        latch.press()
        self.assertEqual(events, ['start'], 'the next tap starts a new recording')

    # --- Paste-last and hotkey wiring (real classes, heavy deps faked) ---
    def _import_app_modules(self):
        import types
        import unittest.mock as mock
        try:
            import numpy  # noqa: F401  (must predate the sys.modules snapshot)
        except ImportError:
            self.skipTest('numpy not installed')
        fakes = fake_platform_modules()
        for name in ('PIL', 'PIL.Image', 'PIL.ImageDraw', 'pystray', 'sounddevice', 'soxr',
                     'faster_whisper', 'playsound3'):
            fakes[name] = _stand_in_module(name)
        reimport_under(self, fakes)
        from whisper_key.hotkey_listener import HotkeyListener
        from whisper_key.state_manager import StateManager
        return HotkeyListener, StateManager

    def _state_manager(self, last=None, state='idle'):
        import unittest.mock as mock
        _, StateManager = self._import_app_modules()
        sm = StateManager.__new__(StateManager)
        sm.logger = __import__('logging').getLogger('test')
        sm.last_transcription = last
        sm.clipboard_manager = mock.Mock()
        sm.system_tray = mock.Mock()
        sm.get_current_state = lambda: state
        sm._wait_for_modifiers_released = lambda: None
        return sm

    def test_paste_last_retypes_without_auto_send(self):
        sm = self._state_manager(last='hello world')
        self.assertTrue(sm.paste_last_transcription())
        sm.clipboard_manager.deliver_transcription.assert_called_once_with('hello world', use_auto_enter=False)

    def test_paste_last_with_nothing_to_paste_says_so(self):
        sm = self._state_manager(last=None)
        self.assertFalse(sm.paste_last_transcription())
        sm.clipboard_manager.deliver_transcription.assert_not_called()
        sm.system_tray.notify.assert_called_once()

    def test_paste_last_waits_while_recording(self):
        sm = self._state_manager(last='x', state='recording')
        self.assertFalse(sm.paste_last_transcription())
        sm.clipboard_manager.deliver_transcription.assert_not_called()

    def test_listener_registers_the_new_hotkeys(self):
        import unittest.mock as mock
        HotkeyListener, _ = self._import_app_modules()
        with mock.patch.object(HotkeyListener, 'start_listening'):
            listener = HotkeyListener(mock.Mock(), 'ctrl+win', 'ctrl', paste_last_hotkey='alt+shift+z',
                                      double_tap_to_lock=True, double_tap_window_ms=300)
        combos = [binding[0] for binding in listener.hotkey_bindings]
        self.assertIn('alt+shift+z', combos)
        self.assertIsNotNone(listener.tap_latch)
        self.assertAlmostEqual(listener.tap_latch.window, 0.3)
        paste = next(b for b in listener.hotkey_bindings if b[0] == 'alt+shift+z')
        # On press: the macOS backend only reports releases for modifier-only
        # chords, so a release-only binding never fired there.
        self.assertIsNotNone(paste[1])
        self.assertIsNone(paste[2])
        with mock.patch.object(HotkeyListener, 'start_listening'):
            plain = HotkeyListener(mock.Mock(), 'ctrl+win', 'ctrl', recording_mode='toggle',
                                   double_tap_to_lock=True)
        self.assertIsNone(plain.tap_latch, 'toggle mode is already hands-free')

    # --- Whisper mode ---
    def test_whisper_mode_boosts_only_quiet_speech(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest('numpy not installed')
        from whisper_key.audio_gain import boost_quiet_audio, TARGET_PEAK
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        quiet = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)  # needs 6x, under the 8x cap
        boosted = boost_quiet_audio(quiet, max_gain=8.0)
        self.assertAlmostEqual(float(np.max(np.abs(boosted))), TARGET_PEAK, delta=0.02)
        self.assertEqual(boosted.dtype, np.float32)
        capped = boost_quiet_audio((0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), max_gain=4.0)
        self.assertAlmostEqual(float(np.max(np.abs(capped))), 0.04, delta=0.005)
        loud = (0.9 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        self.assertIs(boost_quiet_audio(loud), loud, 'never turns the volume down')
        silence = np.full(16000, 1e-5, dtype=np.float32)
        self.assertIs(boost_quiet_audio(silence), silence, 'never amplifies a muted mic')

    # --- Config & settings ---
    def test_new_settings_ship_with_safe_defaults(self):
        from ruamel.yaml import YAML
        cfg = YAML().load((ROOT / 'src' / 'whisper_key' / 'config.defaults.yaml').read_text(encoding='utf-8'))
        pp = cfg['postprocess']
        self.assertFalse(pp['backtrack']['enabled'])
        self.assertFalse(pp['remove_repeated_words'])
        self.assertFalse(pp['list_formatting'])
        self.assertFalse(pp['lowercase'])
        self.assertEqual(pp['style'], '')
        self.assertEqual(list(pp['snippets']), [])
        self.assertFalse(cfg['hotkey']['double_tap_to_lock'])
        self.assertFalse(cfg['audio']['whisper_mode']['enabled'])
        self.assertIn('macos:', cfg['hotkey']['paste_last_hotkey'])


class ReleaseReviewFixTests(unittest.TestCase):
    """Findings from the pre-release review of 0.20.0, each pinned so it can't
    come back."""

    def test_backtrack_handles_decimals_and_money(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        self.assertEqual(apply_backtrack('The rate is 2.5, actually 3'), 'The rate is 3')
        self.assertEqual(apply_backtrack('It costs $1.50, sorry, $2'), 'It costs $2')
        self.assertEqual(apply_backtrack('Version 3.1, I mean 4'), 'Version 4')

    def test_backtrack_am_pm_needs_a_word_end(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        self.assertEqual(apply_backtrack('I have 2 amazing kids, actually 3'), 'I have 3 amazing kids')

    def test_backtrack_leaves_prose_after_a_cue_alone(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        for text in ('We saw 3 movies, actually one of them was great',
                     'I have 2 questions, actually one more thing',
                     'Invite 2 guests, actually 3 amazing people'):
            self.assertEqual(apply_backtrack(text), text)

    def test_backtrack_string_cue_is_one_cue(self):
        from whisper_key.dictation_cleanup import apply_backtrack
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(apply_backtrack('I bought 2 apples and a 3 pack', 'actually'),
                         'I bought 2 apples and a 3 pack')
        self.assertEqual(postprocess('at 2 actually 3', {'backtrack': {'enabled': True, 'cues': 'actually'}}),
                         'at 3')

    def test_backtrack_stays_linear_with_many_corrections(self):
        import time
        from whisper_key.dictation_cleanup import apply_backtrack
        text = 'at 2 tomorrow actually 3. ' * 20000
        start = time.monotonic()
        result = apply_backtrack(text)
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertTrue(result.startswith('at 3 tomorrow. at 3 tomorrow.'))

    def test_stutter_removal_respects_contractions_and_clauses(self):
        from whisper_key.dictation_cleanup import remove_repeated_words
        for text in ("Thank you, you're welcome.", "You can, can't you?",
                     "If you want it, it's yours.", 'Whatever you choose, choose wisely.'):
            self.assertEqual(remove_repeated_words(text), text)
        self.assertEqual(remove_repeated_words('Ok. I, I think so'), 'Ok. I think so')

    def test_list_ends_at_its_last_sentence(self):
        from whisper_key.dictation_cleanup import apply_list_formatting
        self.assertEqual(apply_list_formatting('Groceries: first, milk. second, eggs. See you tonight.'),
                         'Groceries:\n1. Milk\n2. Eggs\n\nSee you tonight.')

    def test_odd_case_folding_never_raises(self):
        from whisper_key.dictation_cleanup import apply_list_formatting
        from whisper_key.snippets import expand_snippets
        self.assertEqual(apply_list_formatting('FİRST, milk. second, eggs.'), 'FİRST, milk. second, eggs.')
        expand_snippets('say fİve now', [{'trigger': 'five', 'expansion': '5'}])

    def test_snippet_keeps_sentence_punctuation_mid_text(self):
        from whisper_key.snippets import expand_snippets
        text, _ = expand_snippets('Send it to my email, then call me. My email.',
                                  [{'trigger': 'my email', 'expansion': 'me@x.com'}])
        self.assertEqual(text, 'Send it to me@x.com, then call me. me@x.com')

    def test_lowercase_keeps_contracted_i_and_multiword_terms(self):
        from whisper_key.dictation_cleanup import apply_lowercase
        self.assertEqual(apply_lowercase("I'm sure Rohit Burani and I'll Go", protected=['Rohit Burani']),
                         "I'm sure Rohit Burani and I'll go")

    def test_settings_save_keeps_custom_styles_and_corrections(self):
        reimport_under(self, fake_platform_modules())  # config_manager imports the platform layer
        from whisper_key.config_manager import _compute_overrides
        defaults = {'postprocess': {'styles': {}, 'corrections': {}, 'style': ''}}
        user = {'postprocess': {'styles': {'shouty': {'capitalize_first': True}},
                                'corrections': {'CAPEX': ['cap x']}, 'style': 'shouty'}}
        kept = _compute_overrides(user, defaults)['postprocess']
        self.assertIn('shouty', kept['styles'])
        self.assertIn('CAPEX', kept['corrections'])

    def test_verbatim_keeps_spoken_formatting(self):
        from whisper_key.styles import resolve_style
        self.assertNotIn('inline_formatting', resolve_style('verbatim'),
                         '"new line" / "comma" must keep working in code editors')

    def test_specific_app_rules_come_before_title_matches(self):
        from ruamel.yaml import YAML
        rules = YAML().load((ROOT / 'src' / 'whisper_key' / 'app_rules.defaults.yaml').read_text(encoding='utf-8'))['rules']
        order = [r['match'][0] for r in rules]
        self.assertLess(order.index('code.exe'), order.index('slack.exe'),
                        'a VS Code window titled "slack_bot.py" must not auto-send')
        self.assertLess(order.index('code.exe'), order.index('outlook.exe'))

    # --- Hands-free lock vs a stop key inside the record chord ---
    def _latch(self, recording=True):
        from whisper_key.hotkey_gestures import TapLatch
        now = [0.0]
        events = []

        class FakeTimer:
            def __init__(self, seconds, callback):
                self.callback = callback

            def cancel(self):
                pass
        latch = TapLatch(start=lambda: events.append('start'), stop=lambda: events.append('stop'),
                         window_ms=400, is_recording=lambda: recording,
                         clock=lambda: now[0], timer_factory=FakeTimer)
        return latch, events, now

    def test_stop_key_is_ignored_while_the_second_tap_begins(self):
        latch, events, now = self._latch()
        latch.press(); now[0] = 0.1; latch.release()
        now[0] = 0.2
        self.assertTrue(latch.intercept_stop_key(), 'Ctrl of the 2nd Ctrl+Win tap must not stop')
        latch.press()
        self.assertEqual(latch.state, latch.LATCHED)

    def test_stop_key_ends_a_lock_without_restarting(self):
        latch, events, now = self._latch()
        latch.state = latch.LATCHED
        self.assertFalse(latch.intercept_stop_key(), 'a real stop while locked')
        now[0] = 0.05
        latch.press()                    # the chord completing right after Ctrl
        self.assertEqual(events, [], 'must not start a junk recording')
        now[0] = 5.0
        latch.press()
        self.assertEqual(events, ['start'], 'later presses work normally')

    # --- Paste-last honours app rules ---
    def _paste_sm(self, rule):
        import unittest.mock as mock
        helper = WisprStyleFeatureTests('test_paste_last_retypes_without_auto_send')
        helper.addCleanup = self.addCleanup
        helper.skipTest = self.skipTest
        sm = helper._state_manager(last='rm -rf build\n')
        sm.app_rules = mock.Mock()
        sm.app_rules.match_for_foreground.return_value = rule
        return sm

    def test_paste_last_skips_suppressed_apps(self):
        sm = self._paste_sm({'match': ['1password.exe'], 'suppress': True})
        self.assertFalse(sm.paste_last_transcription())
        sm.clipboard_manager.deliver_transcription.assert_not_called()
        sm.clipboard_manager.copy_text.assert_not_called()

    def test_paste_last_only_copies_in_copy_only_apps(self):
        sm = self._paste_sm({'match': ['wt.exe'], 'auto_paste': False})
        self.assertTrue(sm.paste_last_transcription())
        sm.clipboard_manager.deliver_transcription.assert_not_called()
        sm.clipboard_manager.copy_text.assert_called_once()

    # --- Whisper mode config is validated, and boosts after the trims ---
    def test_whisper_mode_config_is_validated(self):
        helper = WisprStyleFeatureTests('test_paste_last_retypes_without_auto_send')
        helper.addCleanup = self.addCleanup
        helper.skipTest = self.skipTest
        helper._import_app_modules()
        from whisper_key.audio_recorder import AudioRecorder
        parse = AudioRecorder._parse_whisper_mode
        self.assertIsNone(parse(True))
        self.assertIsNone(parse({'enabled': False}))
        self.assertIsNone(parse({'enabled': 'no'}), 'YAML 1.2 "no" is a string, not an opt-in')
        self.assertEqual(parse({'enabled': True, 'max_gain': '8x'}), 8.0)
        self.assertEqual(parse({'enabled': True, 'max_gain': 4}), 4.0)

    def test_whisper_mode_boosts_after_silence_trimming(self):
        source = (ROOT / 'src' / 'whisper_key' / 'audio_recorder.py').read_text(encoding='utf-8')
        body = source[source.index('def _build_audio_array'):source.index('def _parse_whisper_mode')]
        self.assertLess(body.index('_trim_trailing_silence(audio_array)'), body.index('boost_quiet_audio('),
                        'a boosted noise floor would defeat the anti-hallucination trims')

    def test_settings_window_tolerates_non_mapping_sections(self):
        source = (ROOT / 'src' / 'whisper_key' / 'settings_ui.py').read_text(encoding='utf-8')
        self.assertIn("wm = wm if isinstance(wm, dict) else {}", source)
        self.assertIn("bt = bt if isinstance(bt, dict) else {}", source)

    def test_bad_numeric_hotkey_setting_falls_back(self):
        source = (ROOT / 'src' / 'whisper_key' / 'main.py').read_text(encoding='utf-8')
        self.assertIn("_int_setting(hotkey_config.get('double_tap_window_ms'), 400)", source)

    def test_yaml_no_means_off(self):
        from whisper_key.text_postprocess import postprocess
        self.assertEqual(postprocess('first, milk. second, eggs', {'list_formatting': 'no'}),
                         'first, milk. second, eggs')
        self.assertEqual(postprocess('first, milk. second, eggs', {'list_formatting': 'yes'}),
                         '1. Milk\n2. Eggs')
        self.assertEqual(postprocess('hello', {'capitalize_first': True}), 'Hello')


# ── Layered defaults (0.21.0) ────────────────────────────────────────────────
# Until 0.21 each of app_rules / commands / transforms / profiles was copied out
# of the package once, on first launch, and never touched again. Every later
# improvement to a shipped file reached new installs only: a machine set up in
# May still had May's rules eleven releases on, including the ordering bug that
# let a code editor showing "slack_bot.py" match the chat rule and auto-send.
# The shipped entries now load from the package every time, and the user's file
# holds only their own entries plus per-id overrides.
class LayeredDefaultsTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix='wl-layer-'))

    def _read(self, name):
        from ruamel.yaml import YAML
        with open(self.dir / name, encoding='utf-8') as f:
            return YAML().load(f) or {}

    def _write(self, name, text):
        (self.dir / name).write_text(text, encoding='utf-8')

    # A user file in the pre-0.21 shape: a full copy of the defaults as they
    # were, chat rules ahead of code editors, and no styles.
    def _write_old_app_rules(self):
        self._write('app_rules.yaml', (
            'rules:\n'
            '  - match: ["slack.exe", "discord.exe", "telegram.exe", "whatsapp.exe", "Slack", "Discord"]\n'
            '    auto_send: true\n'
            '    initial_prompt: "Casual chat message. Conversational tone."\n'
            '  - match: ["code.exe", "cursor.exe", "windsurf.exe", "rider64.exe", "pycharm64.exe", "idea64.exe"]\n'
            '    auto_paste: false\n'
            '    initial_prompt: "Programming context. Identifiers, snake_case, camelCase, file paths, regex."\n'
            '  - match: ["mytool.exe"]\n'
            '    suppress: true\n'))

    def _load_rules(self):
        import unittest.mock as mock
        import whisper_key.app_rules as ar
        with mock.patch.object(ar, 'get_user_app_data_path', return_value=str(self.dir)):
            return ar.AppRules().rules

    def test_shipped_rules_load_with_no_user_file(self):
        rules = self._load_rules()
        self.assertEqual([r.get('id') for r in rules],
                         ['password-managers', 'terminals', 'code-editors',
                          'chat-apps', 'email-clients'])
        self.assertEqual(self._read('app_rules.yaml').get('rules'), [],
                         'a fresh user file must start empty, not as a copy of the defaults')

    def test_every_shipped_rule_has_an_id(self):
        # An id-less shipped rule could never be overridden or disabled, and a
        # migration would keep re-adding the user's copy of it as a duplicate.
        from ruamel.yaml import YAML
        path = ROOT / 'src' / 'whisper_key' / 'app_rules.defaults.yaml'
        with open(path, encoding='utf-8') as f:
            shipped = YAML().load(f)['rules']
        ids = [r.get('id') for r in shipped]
        self.assertTrue(all(ids), f'shipped rule without an id: {ids}')
        self.assertEqual(len(ids), len(set(ids)), f'duplicate shipped ids: {ids}')

    def test_editors_are_matched_before_chat(self):
        # The slack_bot.py bug: window titles match by substring, so the code
        # editor rule has to come first.
        ids = [r.get('id') for r in self._load_rules()]
        self.assertLess(ids.index('code-editors'), ids.index('chat-apps'))

    def test_old_file_gains_later_shipped_rules_and_order(self):
        self._write_old_app_rules()
        rules = self._load_rules()
        ids = [r.get('id') for r in rules]
        self.assertIn('email-clients', ids, 'a rule added after the user first launched')
        self.assertLess(ids.index('code-editors'), ids.index('chat-apps'))
        editors = next(r for r in rules if r.get('id') == 'code-editors')
        self.assertEqual(editors.get('style'), 'verbatim',
                         'a key added to a shipped rule after the copy was made')

    def test_migration_keeps_the_users_own_rule_and_drops_the_copies(self):
        self._write_old_app_rules()
        rules = self._load_rules()
        own = [r for r in rules if not r.get('id')]
        self.assertEqual([r['match'] for r in own], [['mytool.exe']])
        self.assertEqual(self._read('app_rules.yaml').get('rules'),
                         [{'match': ['mytool.exe'], 'suppress': True}],
                         'unedited copies of shipped rules should not survive migration')

    def test_migration_backs_up_the_original(self):
        self._write_old_app_rules()
        before = (self.dir / 'app_rules.yaml').read_text(encoding='utf-8')
        self._load_rules()
        backups = list(self.dir.glob('app_rules.yaml.*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'), before)

    def test_migration_runs_once(self):
        self._write_old_app_rules()
        first = self._load_rules()
        second = self._load_rules()
        self.assertEqual([r.get('id') for r in first], [r.get('id') for r in second])
        self.assertEqual(len(list(self.dir.glob('*.bak'))), 1)

    def test_an_edited_shipped_rule_becomes_an_override(self):
        # Only the edited key is kept, so every other key keeps following the
        # shipped rule as it changes.
        self._write('app_rules.yaml', (
            'rules:\n'
            '  - match: ["outlook.exe", "thunderbird.exe", "Mail"]\n'
            '    style: casual\n'
            '    initial_prompt: "Professional email body. Polite, clear sentences."\n'))
        rules = self._load_rules()
        self.assertEqual(self._read('app_rules.yaml')['rules'],
                         [{'id': 'email-clients', 'style': 'casual'}])
        email = next(r for r in rules if r.get('id') == 'email-clients')
        self.assertEqual(email['style'], 'casual')
        self.assertEqual(email['match'], ['outlook.exe', 'thunderbird.exe', 'Mail'])

    def test_user_rules_are_matched_before_shipped_rules(self):
        self._write('app_rules.yaml',
                    'format: 2\nrules:\n  - match: ["code.exe"]\n    style: casual\n')
        rules = self._load_rules()
        self.assertEqual(rules[0]['match'], ['code.exe'])
        self.assertEqual(rules[0]['style'], 'casual')

    def test_disabled_drops_a_shipped_rule(self):
        self._write('app_rules.yaml',
                    'format: 2\nrules:\n  - id: terminals\n    disabled: true\n')
        rules = self._load_rules()
        self.assertNotIn('terminals', [r.get('id') for r in rules])
        self.assertTrue(all('disabled' not in r for r in rules))

    def test_override_inherits_the_keys_it_does_not_set(self):
        self._write('app_rules.yaml',
                    'format: 2\nrules:\n  - id: chat-apps\n    auto_send: false\n')
        chat = next(r for r in self._load_rules() if r.get('id') == 'chat-apps')
        self.assertIs(chat['auto_send'], False)
        self.assertEqual(chat['style'], 'casual')
        self.assertIn('slack.exe', chat['match'])

    def test_a_broken_package_falls_back_to_the_user_file(self):
        # Losing the shipped file must not throw the user's own rules away.
        import unittest.mock as mock
        import whisper_key.defaults_merge as dm
        self._write('app_rules.yaml', 'format: 2\nrules:\n  - match: ["mytool.exe"]\n')
        with mock.patch.object(dm, 'resolve_asset_path', return_value=str(self.dir / 'nope.yaml')):
            merged, _ = dm.load_layered('nope.yaml', self.dir / 'app_rules.yaml',
                                        'rules', '', id_key='id')
        self.assertEqual(merged, [{'match': ['mytool.exe']}])

    def test_profiles_active_falls_back_to_the_shipped_default(self):
        import unittest.mock as mock
        import whisper_key.profiles as pf
        with mock.patch.object(pf, 'get_user_app_data_path', return_value=str(self.dir)):
            manager = pf.ProfileManager(config_manager=mock.MagicMock())
        self.assertEqual(manager.active, 'dictation')
        self.assertEqual(sorted(manager.profiles),
                         ['chat', 'code', 'dictation', 'notes', 'translate'])

    def test_profiles_migration_preserves_the_active_choice(self):
        import unittest.mock as mock
        import whisper_key.profiles as pf
        self._write('profiles.yaml',
                    'active: code\nprofiles:\n  code:\n    description: Mine\n')
        with mock.patch.object(pf, 'get_user_app_data_path', return_value=str(self.dir)):
            manager = pf.ProfileManager(config_manager=mock.MagicMock())
        self.assertEqual(manager.active, 'code')
        self.assertEqual(manager.profiles['code']['description'], 'Mine')
        self.assertIn('overrides', manager.profiles['code'], 'the shipped body should survive')

    def test_transform_override_inherits_the_prompt(self):
        import unittest.mock as mock
        try:
            import whisper_key.transforms as tr
        except ImportError as e:
            self.skipTest(f'transforms needs deps the lean env lacks: {e}')
        self._write('transforms.yaml',
                    'format: 2\ntransforms:\n  - name: polish\n    hotkey: "win+alt+9"\n'
                    '  - name: expand\n    disabled: true\n')
        with mock.patch.object(tr, 'get_user_app_data_path', return_value=str(self.dir)):
            manager = tr.TransformsManager()
        names = [t.get('name') for t in manager.transforms]
        self.assertNotIn('expand', names)
        polish = next(t for t in manager.transforms if t['name'] == 'polish')
        self.assertEqual(polish['hotkey'], 'win+alt+9')
        self.assertTrue(polish.get('prompt'), 'the shipped prompt should still be there')

    def test_a_null_action_lets_an_override_swap_a_commands_action(self):
        # The merge keeps the shipped `hotkey` key, so clearing it has to mean
        # "no action here" to both the validator and the dispatcher.
        import unittest.mock as mock
        reimport_under(self, fake_platform_modules())
        try:
            import whisper_key.voice_commands as vc
        except ImportError as e:
            self.skipTest(f'voice_commands needs deps the lean env lacks: {e}')
        self._write('commands.yaml',
                    'format: 2\ncommands:\n  - trigger: "maximize"\n'
                    '    hotkey: null\n    type: "maximised"\n')
        with mock.patch.object(vc, 'get_user_app_data_path', return_value=str(self.dir)):
            manager = vc.VoiceCommandManager(enabled=True)
        swapped = next(c for c in manager.commands if c.get('trigger') == 'maximize')
        self.assertIsNone(swapped['hotkey'])
        self.assertEqual(swapped['type'], 'maximised')

    def test_dispatcher_tests_action_values_not_key_presence(self):
        source = (ROOT / 'src' / 'whisper_key' / 'voice_commands.py').read_text(encoding='utf-8')
        body = source[source.index('def _execute_action'):]
        body = body[:body.index('def ', 10)]
        for key in ('run', 'hotkey', 'type', 'rephrase'):
            self.assertIn("command.get('" + key + "') is not None", body,
                          f"a cleared '{key}' would still be dispatched")

    def test_doctor_reports_the_effective_counts(self):
        # The user file holds overrides only, so counting its entries would tell
        # someone they have 0 rules while five are in force.
        source = (ROOT / 'src' / 'whisper_key' / 'doctor.py').read_text(encoding='utf-8')
        self.assertIn('rules in effect', source)
        self.assertIn('Voice commands in effect', source)

    def test_an_edited_match_list_overrides_instead_of_duplicating(self):
        # Dropping an app from a shipped rule has to actually drop it. If the
        # edited rule were kept as a separate one, the shipped rule would sit
        # behind it and go on auto-sending in the app that was removed.
        self._write('app_rules.yaml',
                    'rules:' + LF +
                    '  - match: ["slack.exe", "telegram.exe"]' + LF +
                    '    auto_send: true' + LF)
        rules = self._load_rules()
        chat = [r for r in rules if r.get('id') == 'chat-apps']
        self.assertEqual(len(chat), 1, 'the edited rule and the shipped one both loaded')
        self.assertEqual(chat[0]['match'], ['slack.exe', 'telegram.exe'])
        self.assertEqual([r for r in rules if not r.get('id')], [],
                         'it should have become an override, not a rule of its own')
        import whisper_key.app_rules as ar
        matcher = ar.AppRules._matches
        self.assertFalse(any(matcher(None, r, 'discord.exe', '') for r in rules),
                         'discord was removed from the list but still matches')
        self.assertTrue(any(matcher(None, r, 'slack.exe', '') for r in rules))

    def test_broken_user_yaml_is_never_overwritten(self):
        # A typo in their file must not read as "no entries" and trigger the
        # migration, which would rewrite what they were in the middle of
        # editing. The app runs on the shipped rules until they fix it.
        broken = 'rules:' + LF + '  - match: ["a.exe"' + LF + '    style: casual' + LF
        self._write('app_rules.yaml', broken)
        rules = self._load_rules()
        self.assertEqual([r.get('id') for r in rules],
                         ['password-managers', 'terminals', 'code-editors',
                          'chat-apps', 'email-clients'])
        self.assertEqual((self.dir / 'app_rules.yaml').read_text(encoding='utf-8'), broken)
        self.assertEqual(list(self.dir.glob('*.bak')), [])

    def test_broken_package_hands_back_the_right_container(self):
        # A list-shaped section must not come back as a dict just because the
        # shipped file is unreadable: the callers iterate it.
        import unittest.mock as mock
        import whisper_key.defaults_merge as dm
        missing = str(self.dir / 'nope.yaml')
        with mock.patch.object(dm, 'resolve_asset_path', return_value=missing):
            commands, _ = dm.load_layered('nope.yaml', self.dir / 'commands.yaml',
                                          'commands', '', id_key='trigger')
            profiles, _ = dm.load_layered('nope.yaml', self.dir / 'profiles.yaml',
                                          'profiles', '', mapping=True)
        self.assertEqual(commands, [])
        self.assertEqual(profiles, {})

    def test_a_corrupt_shipped_file_does_not_crash_the_loader(self):
        import unittest.mock as mock
        import whisper_key.defaults_merge as dm
        bad = self.dir / 'bad.defaults.yaml'
        bad.write_text('rules:' + LF + '  - match: ["a.exe"' + LF, encoding='utf-8')
        self._write('app_rules.yaml', 'format: 2' + LF + 'rules: []' + LF)
        with mock.patch.object(dm, 'resolve_asset_path', return_value=str(bad)):
            merged, _ = dm.load_layered('bad.defaults.yaml', self.dir / 'app_rules.yaml',
                                        'rules', '', id_key='id')
        self.assertEqual(merged, [])
