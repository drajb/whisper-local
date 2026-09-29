# transforms.py
# Wispr-style AI text transforms: take the current selection or clipboard and
# rewrite it with a local Ollama model using a named prompt from
# `transforms.yaml` (e.g. "make it formal", "summarise"). User-editable and
# hot-reloaded on file change. Entirely local — no cloud call — and a no-op when
# Ollama isn't running, so the feature degrades quietly rather than erroring.

import logging
import time
from pathlib import Path
from typing import Optional

import pyperclip

# `keyboard` is imported lazily inside the methods that need it. The chain
# .platform → .platform.windows pulls in win32api, which doesn't exist on Linux.
# Keeping the import lazy means transforms.py is importable on CI (Linux smoke
# tests) and from tools that only need to read transforms.yaml metadata.
from .defaults_merge import load_layered
from .text_postprocess import _ollama_polish
from .utils import get_user_app_data_path

USER_FILE = "transforms.yaml"
DEFAULTS_FILE = "transforms.defaults.yaml"

USER_FILE_HEADER = """\
# Whisper Local — your transforms
#
# The transforms that ship with the app are applied underneath this file, so
# they keep improving with each update. Here you only write what's yours:
#
#   transforms:
#     # one of your own
#     - name: shorten
#       description: Cut it in half
#       hotkey: "win+alt+7"
#       prompt: "Rewrite this in half the words. Output only the result:"
#
#     # change a shipped one, naming it and only the keys you want different
#     - name: polish
#       hotkey: "win+alt+9"
#
#     # turn a shipped one off
#     - name: expand
#       disabled: true
#
# Shipped names: polish, prompt-engineer, professional, casual, bullets,
# expand. Hot-reloads on save — no app restart needed.

"""


class TransformsManager:
    def __init__(self, ollama_config_provider=None, system_tray=None):
        self.logger = logging.getLogger(__name__)
        self.transforms: list = []
        self._mtime = 0.0
        self._path: Optional[Path] = None
        self.ollama_config_provider = ollama_config_provider
        self.system_tray = system_tray
        self._load()

    def _load(self):
        self._path = Path(get_user_app_data_path()) / USER_FILE
        self._reload_from_disk()

    def _reload_from_disk(self):
        if not self._path:
            return
        try:
            self.transforms, _ = load_layered(
                DEFAULTS_FILE, self._path, "transforms", USER_FILE_HEADER,
                id_key="name")
            self._mtime = self._path.stat().st_mtime if self._path.exists() else 0.0
            self.logger.info(f"Loaded {len(self.transforms)} transforms")
        except Exception as e:
            self.logger.error(f"Failed to load transforms: {e}")

    def reload_if_changed(self):
        if not self._path:
            return
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if mtime > self._mtime:
            self.logger.info("Transforms file changed; reloading")
            self._reload_from_disk()

    def list_transforms(self) -> list:
        return list(self.transforms)

    def transforms_with_hotkeys(self) -> list:
        return [t for t in self.transforms if t.get('hotkey')]

    def find(self, name: str) -> Optional[dict]:
        if not name:
            return None
        for t in self.transforms:
            if t.get('name', '').lower() == name.lower():
                return t
        return None

    # Runs a named transform end-to-end: grab the user's selection (falling back
    # to clipboard), send it to Ollama with that transform's prompt, and paste the
    # rewrite back over the selection. Returns False rather than raising on any
    # failure (unknown name, Ollama down, empty selection) so a missing optional
    # dependency can never break the hotkey that triggered it.
    def apply(self, name: str) -> bool:
        self.reload_if_changed()
        transform = self.find(name)
        if not transform:
            self.logger.warning(f"Unknown transform: {name}")
            self._notify(f"Transform '{name}' not found")
            return False

        prompt = transform.get('prompt')
        if not prompt:
            self._notify(f"Transform '{name}' has no prompt")
            return False

        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            original_clipboard = ''

        try:
            from .platform import keyboard as kb
            kb.send_hotkey('ctrl', 'c')
            time.sleep(0.12)
            selection = pyperclip.paste()
        except Exception as e:
            self.logger.error(f"Selection capture failed: {e}")
            return False

        if not selection or selection == original_clipboard:
            self.logger.info(f"Transform '{name}': no selection")
            self._notify(f"Select text first, then apply '{transform.get('name', name)}'")
            try: pyperclip.copy(original_clipboard)
            except Exception: pass
            return False

        if not self.ollama_config_provider:
            self._notify("Transforms require Ollama config (postprocess.ollama)")
            try: pyperclip.copy(original_clipboard)
            except Exception: pass
            return False

        full_prompt = f"{prompt}\n\n{selection}"
        ollama_cfg = dict(self.ollama_config_provider() or {})
        ollama_cfg['enabled'] = True
        ollama_cfg['prompt'] = '{text}'
        if transform.get('model'):
            ollama_cfg['model'] = transform['model']
        if transform.get('timeout') is not None:
            ollama_cfg['timeout'] = transform['timeout']

        result = _ollama_polish(full_prompt, ollama_cfg)
        if not result:
            self.logger.warning(f"Transform '{name}' returned empty from Ollama")
            self._notify(f"Transform '{name}' failed — Ollama unreachable?")
            try: pyperclip.copy(original_clipboard)
            except Exception: pass
            return False

        try:
            from .platform import keyboard as kb
            pyperclip.copy(result)
            time.sleep(0.05)
            kb.send_hotkey('ctrl', 'v')
            time.sleep(0.2)
        finally:
            try: pyperclip.copy(original_clipboard)
            except Exception: pass

        self.logger.info(f"Transform '{name}' applied: {len(selection)} → {len(result)} chars")
        print(f"   ✓ Transform '{transform.get('name', name)}' applied")
        return True

    def _notify(self, msg: str):
        if self.system_tray:
            try:
                self.system_tray.notify(msg)
            except Exception:
                pass
        print(f"   ⚠ {msg}")
