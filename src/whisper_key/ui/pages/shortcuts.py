# ui/pages/shortcuts.py
# Every hotkey as it is configured right now, shown as key caps, grouped by
# what you use it for. Replaces the old standalone cheat-sheet window.

import tkinter as tk

from ..hub import BasePage
from ..kit import Button, hotkey_chips


# The rows to show, from the hotkey config: [(group, label, combination,
# description)]. Unset hotkeys are left out. Pure, so it's easy to test.
def hotkey_rows(hk: dict, transforms=()) -> list:
    from ...utils import MOUSE_BUTTON_LABELS
    hk = hk or {}
    hold = hk.get('recording_mode', 'push_to_talk') == 'push_to_talk'
    record_help = 'Hold to record, release to transcribe.' if hold else 'Press to start, press stop to finish.'
    if hold and hk.get('double_tap_to_lock'):
        record_help += ' Double-tap for hands-free.'
    rows = [
        ('Dictate', 'Record', hk.get('recording_hotkey'), record_help),
        ('Dictate', 'Stop and paste', hk.get('stop_key'), 'Ends a recording and types the text.'),
        ('Dictate', 'Stop, paste and send', hk.get('auto_send_key'), 'Also presses Enter: handy in chat apps.'),
        ('Dictate', 'Cancel', hk.get('cancel_combination'), 'Throws the recording away. Retry from the tray brings it back.'),
        ('Dictate', 'Paste last dictation', hk.get('paste_last_hotkey'), 'Types your last dictation again.'),
        ('Do more', 'Voice commands', hk.get('command_hotkey'), 'Say a phrase from commands.yaml to run it.'),
        ('Do more', 'AI rephrase', hk.get('rephrase_hotkey'), 'Select text, hold, say how to change it.'),
        ('Do more', 'Pause all hotkeys', hk.get('pause_hotkey'), 'Press again to turn them back on.'),
    ]
    mouse = hk.get('mouse_button')
    if mouse in MOUSE_BUTTON_LABELS:
        rows.insert(1, ('Dictate', 'Record with the mouse', MOUSE_BUTTON_LABELS[mouse],
                        'Works exactly like the record hotkey.'))
    for t in transforms or ():
        if t.get('hotkey'):
            rows.append(('AI transforms', str(t.get('name', 'Transform')).replace('-', ' ').title(),
                         t['hotkey'], (t.get('prompt') or '').strip().split('\n')[0][:90]))
    return [r for r in rows if r[2]]


class Page(BasePage):
    title = 'Shortcuts'
    subtitle = 'Your hotkeys as they are set right now.'

    def build(self, body):
        kit, p = self.kit, self.p
        self.action('Change hotkeys', lambda: self.hub.show('settings'), icon='settings')
        transforms = []
        try:
            from ...transforms import TransformsManager
            transforms = TransformsManager().list_transforms()
        except Exception:
            pass
        rows = hotkey_rows(self.config.get('hotkey') or {}, transforms)
        groups = []
        for row in rows:
            if row[0] not in groups:
                groups.append(row[0])
        for group in groups:
            section = self.section(body, group)
            for i, (_, label, combo, description) in enumerate(r for r in rows if r[0] == group):
                if label == 'Record with the mouse':
                    control = (lambda c: lambda parent: kit.label(parent, c.title(), 'body_strong',
                                                                  bg=p['surface']))(combo)
                else:
                    control = (lambda c: lambda parent: hotkey_chips(parent, kit, c, bg=p['surface']))(combo)
                self.row(section, label, description, control, first=(i == 0))
        kit.label(body, 'Hotkey changes take effect after Whisper Local restarts.', 'small',
                  'text_faint').pack(anchor='w', pady=(kit.px(4), 0))
