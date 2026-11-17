# ui/pages/help.py
# Where to go when something is off or you want to learn more: the guides,
# one-click diagnostics, a log bundle for bug reports, and the privacy promise.

import sys
import threading
import webbrowser
import tkinter as tk

from ..hub import BasePage
from ..kit import Button

REPO = 'https://github.com/drajb/whisper-local'
GUIDES = (
    ('Getting started', 'Install, the first dictation, and the hotkeys.', f'{REPO}#-quick-start'),
    ('Troubleshooting', 'Fixes for the most common problems.', f'{REPO}/blob/master/docs/troubleshooting.md'),
    ('Frequently asked questions', 'Privacy, models, GPUs, and how it compares.', f'{REPO}/blob/master/docs/faq.md'),
    ('Voice commands', 'Run shortcuts and type text by saying a phrase.', f'{REPO}/blob/master/docs/voice-commands.md'),
    ('Release notes', "What's new in each version.", f'{REPO}/blob/master/CHANGELOG.md'),
)


class Page(BasePage):
    title = 'Help & docs'
    subtitle = 'Guides, diagnostics and how to get in touch.'

    def build(self, body):
        kit, p = self.kit, self.p
        bg = p['surface']
        guides = self.section(body, 'Guides')
        for i, (name, text, url) in enumerate(GUIDES):
            self.row(guides, name, text,
                     lambda parent, u=url: Button(parent, kit, 'Open', lambda: webbrowser.open(u),
                                                  icon='external', bg=bg), first=(i == 0))

        tools = self.section(body, 'Something not working?')
        self.row(tools, 'Run diagnostics', 'Checks the microphone, permissions, model and hotkeys, '
                 'and says what to fix.',
                 lambda parent: Button(parent, kit, 'Run', lambda: self._run_flag('--doctor'),
                                       icon='play', bg=bg), first=True)
        self.row(tools, 'Self-test', 'Records a second of audio, transcribes it and tests the clipboard.',
                 lambda parent: Button(parent, kit, 'Run', lambda: self._run_flag('--selftest'),
                                       icon='play', bg=bg))
        self.row(tools, 'Bundle logs for a bug report', 'A zip on your Desktop with private details '
                 'removed. Attach it to a GitHub issue.',
                 lambda parent: Button(parent, kit, 'Create', self._bundle, icon='download', bg=bg))
        self.row(tools, 'Report a problem or ask for a feature', 'Opens a new GitHub issue.',
                 lambda parent: Button(parent, kit, 'Open', lambda: webbrowser.open(f'{REPO}/issues/new/choose'),
                                       icon='external', bg=bg))

        about = self.section(body, 'About')
        from ...utils import get_version
        self.row(about, f'Whisper Local {get_version()}',
                 'Free and open source (MIT). Speech recognition by OpenAI Whisper through faster-whisper.',
                 lambda parent: Button(parent, kit, 'GitHub', lambda: webbrowser.open(REPO),
                                       icon='external', bg=bg), first=True)
        self.row(about, 'Private by design', 'Your audio and text never leave this computer. '
                 'No account, no cloud, no telemetry.', None)

    # Opens a diagnostics command in its own console window, where it can
    # print its report and wait for a key.
    def _run_flag(self, flag):
        import subprocess
        from ...utils import build_relaunch_command
        flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0) if sys.platform == 'win32' else 0
        try:
            subprocess.Popen(build_relaunch_command() + [flag], creationflags=flags)
        except Exception as e:
            self.hub.toast(f"Couldn't start it: {e}", 'danger')

    def _bundle(self):
        self.hub.toast('Creating the bundle…')

        def work():
            import datetime
            from pathlib import Path
            from ...bundle_logs import bundle_logs
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            target = Path.home() / 'Desktop' / f'whisper-local-bundle-{stamp}.zip'
            try:
                bundle_logs(str(target))
                message, kind = f"Saved to your Desktop: {target.name}", 'success'
            except Exception as e:
                message, kind = f"Bundle failed: {e}", 'danger'
            self.hub.root.after(0, lambda: self.hub.toast(message, kind))
        threading.Thread(target=work, daemon=True, name='bundle-logs').start()
