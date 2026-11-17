# ui/pages/home.py
# The hub's landing page: a greeting, the numbers that make dictation feel
# worth it (words, time saved, streak, speaking speed), a seven-day activity
# chart, the latest dictations one click from the clipboard, and a tip.

import datetime
import random
import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Card

TIPS = (
    ('Say "new paragraph"', 'Spoken formatting works mid-sentence: "comma", "question mark", "new line".'),
    ('Change your mind out loud', 'With cleanup at medium, "meet at 2, actually 3" types "meet at 3".'),
    ('Double-tap for hands-free', 'Turn on Settings → Hotkeys → Hands-free, then double-tap the hotkey to keep recording.'),
    ('Fix a word everywhere', 'In History, select a dictation and use "Fix everywhere" to correct a misheard word for good.'),
    ('Dictate into Notes', 'Notes is a scratchpad for drafts: click into a note and dictate as usual.'),
    ('Transcribe a recording', 'Transcribe turns audio and video files into text or subtitles, fully offline.'),
    ('Teach it your words', 'Add names and jargon under Dictionary so they come out spelled right.'),
    ('Shortcuts that type for you', 'Snippets expand phrases like "my email" into the full text as you speak.'),
)


def greeting(now: datetime.datetime = None) -> str:
    hour = (now or datetime.datetime.now()).hour
    if hour < 5:
        return 'Working late'
    if hour < 12:
        return 'Good morning'
    if hour < 18:
        return 'Good afternoon'
    return 'Good evening'


# "1,234", "12.3k", "1.2M".
def compact_number(value: float) -> str:
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1000:.1f}k"
    return f"{int(round(value)):,}"


def duration_label(minutes: float) -> str:
    if minutes >= 120:
        return f"{minutes / 60:.1f} h"
    return f"{int(round(minutes))} min"


class Page(BasePage):
    title = 'Home'

    def heading(self):
        return greeting()

    def subheading(self):
        return 'Your words, on this computer only.'

    def build(self, body):
        from ...stats import compute_summary, DEFAULT_TYPING_WPM
        kit, p = self.kit, self.p
        wpm = (self.config.get('stats') or {}).get('typing_wpm') or DEFAULT_TYPING_WPM
        try:
            summary = compute_summary(float(wpm))
        except Exception:
            summary = compute_summary(DEFAULT_TYPING_WPM, entries=[])
        self.action('Open Notes', lambda: self.hub.show('notes'), icon='notes')

        cards = tk.Frame(body, bg=p['bg'])
        cards.pack(fill='x')
        stats = (
            ('words', 'Words dictated', compact_number(summary['words']), None),
            ('hourglass', 'Time saved', duration_label(summary['minutes_saved']),
             f"vs typing at {int(float(wpm))} wpm"),
            ('flame', 'Day streak', str(summary['streak']), f"best {summary['longest_streak']}"),
            ('gauge', 'Speaking speed', f"{int(summary['avg_wpm'])} wpm", None),
        )
        for column, (icon, label, value, note) in enumerate(stats):
            card = Card(cards, kit, padding=16)
            card.grid(row=0, column=column, sticky='nsew', padx=(0 if column == 0 else kit.px(12), 0))
            cards.grid_columnconfigure(column, weight=1, uniform='stats')
            b = card.body
            top = tk.Frame(b, bg=p['surface'])
            top.pack(fill='x')
            tk.Label(top, image=kit.icon(icon, 16, p['accent']), bg=p['surface']).pack(side='left')
            kit.label(top, label, 'small', 'text_muted', bg=p['surface']).pack(side='left', padx=(kit.px(6), 0))
            kit.label(b, value, 'stat', bg=p['surface']).pack(anchor='w', pady=(kit.px(8), 0))
            kit.label(b, note or ' ', 'caption', 'text_faint', bg=p['surface']).pack(anchor='w')

        lower = tk.Frame(body, bg=p['bg'])
        lower.pack(fill='both', expand=True, pady=(kit.px(16), 0))
        lower.grid_columnconfigure(0, weight=3, uniform='lower')
        lower.grid_columnconfigure(1, weight=2, uniform='lower')
        self._recent(lower)
        side = tk.Frame(lower, bg=p['bg'])
        side.grid(row=0, column=1, sticky='nsew', padx=(kit.px(16), 0))
        self._week_chart(side, summary['week'])
        self._tip(side)

    def _recent(self, parent):
        import pyperclip
        from ...transcript_log import load_transcripts
        kit, p = self.kit, self.p
        card = Card(parent, kit, padding=18)
        card.grid(row=0, column=0, sticky='nsew')
        b = card.body
        head = tk.Frame(b, bg=p['surface'])
        head.pack(fill='x', pady=(0, kit.px(8)))
        kit.label(head, 'Recent', 'heading', bg=p['surface']).pack(side='left')
        Button(head, kit, 'View all', lambda: self.hub.show('history'), variant='ghost', size='sm',
               bg=p['surface']).pack(side='right')
        try:
            entries = load_transcripts()[:6]   # newest first
        except Exception:
            entries = []
        if not entries:
            hk = (self.config.get('hotkey') or {}).get('recording_hotkey', 'ctrl+win').upper()
            kit.label(b, f"Nothing yet. Hold {hk.replace('+', ' + ')} in any app and start talking.",
                      'body', 'text_muted', bg=p['surface'], wrap=True).pack(fill='x', pady=kit.px(12))
            return
        for i, entry in enumerate(entries):
            if i:
                tk.Frame(b, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x')
            row = tk.Frame(b, bg=p['surface'])
            row.pack(fill='x', pady=kit.px(9))
            text = (entry.get('text') or '').strip()
            when = (entry.get('timestamp') or '')[11:16]
            meta = when + (f"  ·  {entry.get('app')}" if entry.get('app') else '')

            def copy(t=text):
                pyperclip.copy(t)
                self.hub.toast('Copied to clipboard', 'success')
            Button(row, kit, '', copy, variant='ghost', icon='copy', size='sm',
                   bg=p['surface']).pack(side='right', anchor='n')
            words = tk.Frame(row, bg=p['surface'])
            words.pack(side='left', fill='x', expand=True)
            kit.label(words, text[:220] + ('…' if len(text) > 220 else ''), 'body', bg=p['surface'],
                      wrap=True).pack(fill='x')
            kit.label(words, meta, 'caption', 'text_faint', bg=p['surface']).pack(anchor='w', pady=(kit.px(2), 0))

    def _week_chart(self, parent, week):
        kit, p = self.kit, self.p
        card = Card(parent, kit, padding=18)
        card.pack(fill='x')
        b = card.body
        total = sum(words for _, words in week)
        kit.label(b, 'Last 7 days', 'heading', bg=p['surface']).pack(anchor='w')
        kit.label(b, f"{total:,} words", 'small', 'text_muted', bg=p['surface']).pack(anchor='w')
        height = kit.px(120)
        chart = tk.Canvas(b, height=height + kit.px(22), bg=p['surface'], highlightthickness=0, bd=0)
        chart.pack(fill='x', pady=(kit.px(12), 0))
        peak = max([words for _, words in week] + [1])

        def draw(_e=None):
            chart.delete('all')
            width = chart.winfo_width()
            slot = width / 7
            bar_w = min(kit.px(26), slot * 0.55)
            for i, (day, words) in enumerate(week):
                cx = slot * i + slot / 2
                bar_h = max(kit.px(4), height * words / peak) if words else kit.px(4)
                color = p['accent'] if i == 6 else (p['accent_soft'] if words else p['field'])
                kit.round_rect(chart, cx - bar_w / 2, height - bar_h, cx + bar_w / 2, height,
                               kit.px(5), color, tag=f'bar{i}')
                chart.create_text(cx, height + kit.px(12), text=day.strftime('%a')[0],
                                  fill=p['text_muted'] if i == 6 else p['text_faint'],
                                  font=kit.font('caption'))
        chart.bind('<Configure>', draw)

    def _tip(self, parent):
        kit, p = self.kit, self.p
        title, text = random.choice(TIPS)
        card = Card(parent, kit, padding=18, fill=p['accent_soft'], outline=False)
        card.pack(fill='x', pady=(kit.px(16), 0))
        b = card.body
        head = tk.Frame(b, bg=p['accent_soft'])
        head.pack(fill='x')
        tk.Label(head, image=kit.icon('sparkles', 16, p['accent']), bg=p['accent_soft']).pack(side='left')
        kit.label(head, 'Tip', 'small_strong', 'accent', bg=p['accent_soft']).pack(side='left', padx=(kit.px(6), 0))
        kit.label(b, title, 'body_strong', bg=p['accent_soft']).pack(anchor='w', pady=(kit.px(8), kit.px(2)))
        kit.label(b, text, 'small', 'text_muted', bg=p['accent_soft'], wrap=True).pack(fill='x')
