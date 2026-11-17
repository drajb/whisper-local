# ui/pages/history.py
# Every past dictation, newest first and grouped by day, with live search.
# Each entry can be copied or turned into a permanent correction ("Fix
# everywhere": misheard text -> what you meant, applied to every future
# dictation). "Suggest words" mines the history for names worth adding to the
# dictionary; Export writes the history to a text or Markdown file.

import datetime
import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Field, Card, Toggle, ScrollFrame, new_window

BATCH = 80   # entries drawn at a time; "Show more" adds another batch


def day_label(day: datetime.date, today: datetime.date = None) -> str:
    today = today or datetime.date.today()
    if day == today:
        return 'Today'
    if day == today - datetime.timedelta(days=1):
        return 'Yesterday'
    if (today - day).days < 7:
        return day.strftime('%A')
    return day.strftime('%a, %b %d, %Y').replace(' 0', ' ')


def filter_entries(entries, query: str):
    q = (query or '').strip().lower()
    if not q:
        return list(entries)
    return [e for e in entries
            if q in (e.get('text') or '').lower() or q in (e.get('app') or '').lower()]


# The history as a Markdown or plain-text document, oldest first.
def export_text(entries, markdown: bool) -> str:
    lines = ['# Whisper Local history', ''] if markdown else []
    for e in reversed(list(entries)):
        stamp = (e.get('timestamp') or '').replace('T', ' ')[:16]
        app = e.get('app') or ''
        text = (e.get('text') or '').strip()
        if markdown:
            lines.append(f"**{stamp}**{f' · {app}' if app else ''}  ")
            lines.append(text)
            lines.append('')
        else:
            lines.append(f"[{stamp}]{f' ({app})' if app else ''} {text}")
    return '\n'.join(lines) + '\n'


class Page(BasePage):
    title = 'History'
    subtitle = 'Everything you dictated, searchable. Stored only on this computer.'
    scroll = False

    def build(self, body):
        from ...transcript_log import load_transcripts
        kit, p = self.kit, self.p
        self.all_entries = load_transcripts()
        self.shown = BATCH
        self.action('Suggest words', self._suggest_words, icon='sparkles')
        self.action('Export', self._export, icon='download')

        self.query = tk.StringVar(master=self.hub.root)
        field = Field(body, kit, self.query, placeholder='Search your dictations', icon='search')
        field.pack(fill='x')
        self.status = kit.label(body, '', 'small', 'text_faint')
        self.status.pack(anchor='w', pady=(kit.px(10), kit.px(4)))
        self.list = ScrollFrame(body, kit, bg=p['bg'])
        self.list.pack(fill='both', expand=True)
        self._pending = None
        self.query.trace_add('write', lambda *_: self._schedule_refresh())
        self._refresh()
        field.focus()

    # Debounced, so typing a word doesn't redraw the list once per letter.
    def _schedule_refresh(self):
        if self._pending:
            self.hub.root.after_cancel(self._pending)
        self.shown = BATCH
        self._pending = self.hub.root.after(180, self._refresh)

    def _refresh(self):
        kit, p = self.kit, self.p
        self._pending = None
        for child in self.list.inner.winfo_children():
            child.destroy()
        matches = filter_entries(self.all_entries, self.query.get())
        total = len(self.all_entries)
        if not total:
            self.status.configure(text='')
            self.empty_state(self.list.inner, 'history', 'No dictations yet',
                             'Everything you dictate shows up here, so you can find it, copy it '
                             'again or fix a word Whisper keeps mishearing.')
            return
        self.status.configure(text=f"{len(matches):,} of {total:,} dictations" if self.query.get()
                              else f"{total:,} dictations")
        if not matches:
            self.empty_state(self.list.inner, 'search', 'Nothing matches',
                             'Try a different word, or part of an app name.')
            return
        current_day = None
        group = None
        for entry in matches[:self.shown]:
            try:
                when = datetime.datetime.fromisoformat(entry.get('timestamp', ''))
            except ValueError:
                when = None
            day = when.date() if when else None
            if day != current_day or group is None:
                current_day = day
                kit.label(self.list.inner, day_label(day) if day else 'Earlier', 'small_strong',
                          'text_muted').pack(anchor='w', pady=(kit.px(14), kit.px(6)))
                card = Card(self.list.inner, kit, padding=4)
                card.pack(fill='x', padx=(0, kit.px(14)))
                group = card.body
            self._entry_row(group, entry, when)
        if len(matches) > self.shown:
            more = Button(self.list.inner, kit, f"Show more ({len(matches) - self.shown:,} left)",
                          self._show_more, variant='secondary')
            more.pack(pady=kit.px(16))
        self.list.scroll_to_top()

    def _show_more(self):
        self.shown += BATCH
        self._refresh()

    def _entry_row(self, group, entry, when):
        import pyperclip
        kit, p = self.kit, self.p
        bg = p['surface']
        if group.winfo_children():
            tk.Frame(group, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(12))
        row = tk.Frame(group, bg=bg)
        row.pack(fill='x', padx=kit.px(12), pady=kit.px(10))
        text = (entry.get('text') or '').strip()
        time_label = when.strftime('%H:%M') if when else ''
        kit.label(row, time_label, 'mono_small', 'text_faint', bg=bg, width=6).pack(side='left', anchor='n')

        def copy():
            pyperclip.copy(text)
            self.hub.toast('Copied to clipboard', 'success')
        actions = tk.Frame(row, bg=bg)
        actions.pack(side='right', anchor='n')
        Button(actions, kit, '', copy, variant='ghost', icon='copy', size='sm', bg=bg).pack(side='left')
        Button(actions, kit, '', lambda: self._fix_dialog(text), variant='ghost', icon='wand',
               size='sm', bg=bg).pack(side='left')
        words = tk.Frame(row, bg=bg)
        words.pack(side='left', fill='x', expand=True, padx=(kit.px(8), kit.px(8)))
        kit.label(words, text, 'body', bg=bg, wrap=True).pack(fill='x')
        if entry.get('app'):
            kit.label(words, entry['app'], 'caption', 'text_faint', bg=bg).pack(anchor='w', pady=(kit.px(3), 0))

    # ── Dialogs ──────────────────────────────────────────────────────────

    # "Fix everywhere": what Whisper wrote -> what you meant, for good.
    def _fix_dialog(self, source_text: str):
        from ...corrections import add_replacement
        dialog, kit = new_window('Fix everywhere', size=(460, 330), resizable=False, master=self.hub.root)
        dialog.transient(self.hub.root)
        p = kit.p
        body = kit.frame(dialog, bg=p['bg'])
        body.pack(fill='both', expand=True, padx=kit.px(24), pady=kit.px(20))
        kit.label(body, 'Fix a word everywhere', 'title').pack(anchor='w')
        kit.label(body, 'Every future dictation gets this correction. Matching ignores case '
                  'and whole words only.', 'small', 'text_muted', wrap=True).pack(fill='x', pady=(kit.px(4), kit.px(14)))
        wrong, right = tk.StringVar(master=dialog), tk.StringVar(master=dialog)
        kit.label(body, 'Whisper writes', 'small_strong').pack(anchor='w')
        first = Field(body, kit, wrong, placeholder='e.g. cooper netties')
        first.pack(fill='x', pady=(kit.px(4), kit.px(10)))
        kit.label(body, 'You meant', 'small_strong').pack(anchor='w')
        Field(body, kit, right, placeholder='e.g. Kubernetes').pack(fill='x', pady=(kit.px(4), kit.px(14)))
        message = kit.label(body, '', 'small', 'danger')
        message.pack(anchor='w')

        def save():
            if add_replacement(wrong.get(), right.get()):
                dialog.destroy()
                self.hub.toast('Correction saved: applies to your next dictation', 'success')
            else:
                message.configure(text='Enter the misheard text and a different correction.')
        row = kit.frame(body)
        row.pack(side='bottom', fill='x')
        Button(row, kit, 'Save correction', save, variant='primary').pack(side='right')
        Button(row, kit, 'Cancel', dialog.destroy).pack(side='right', padx=(0, kit.px(8)))
        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        first.focus()

    def _suggest_words(self):
        from ...dictionary import add_word, suggest_hotwords_from_history
        candidates = suggest_hotwords_from_history()
        if not candidates:
            self.hub.toast('No strong suggestions yet. Keep dictating!')
            return
        dialog, kit = new_window('Suggested words', size=(420, 520), master=self.hub.root)
        dialog.transient(self.hub.root)
        p = kit.p
        body = kit.frame(dialog, bg=p['bg'])
        body.pack(fill='both', expand=True, padx=kit.px(24), pady=kit.px(20))
        kit.label(body, 'Words you use often', 'title').pack(anchor='w')
        kit.label(body, 'Names and terms from your history. Turn on the ones to add to your '
                  'dictionary so Whisper spells them right.', 'small', 'text_muted',
                  wrap=True).pack(fill='x', pady=(kit.px(4), kit.px(12)))
        buttons = kit.frame(body)
        buttons.pack(side='bottom', fill='x', pady=(kit.px(12), 0))
        area = ScrollFrame(body, kit, bg=p['bg'])
        area.pack(fill='both', expand=True)
        card = Card(area.inner, kit, padding=4)
        card.pack(fill='x', padx=(0, kit.px(8)))
        choices = []
        for i, (word, count) in enumerate(candidates):
            if i:
                tk.Frame(card.body, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(12))
            row = tk.Frame(card.body, bg=p['surface'])
            row.pack(fill='x', padx=kit.px(12), pady=kit.px(8))
            var = tk.BooleanVar(master=dialog, value=False)
            choices.append((word, var))
            Toggle(row, kit, var, bg=p['surface']).pack(side='right')
            kit.label(row, word, 'body_strong', bg=p['surface']).pack(side='left')
            kit.label(row, f"  {count}×", 'small', 'text_faint', bg=p['surface']).pack(side='left')

        def add():
            added = sum(1 for word, var in choices if var.get() and add_word(word))
            dialog.destroy()
            self.hub.toast(f"Added {added} word{'s' if added != 1 else ''} to your dictionary", 'success')
        Button(buttons, kit, 'Add to dictionary', add, variant='primary').pack(side='right')
        Button(buttons, kit, 'Cancel', dialog.destroy).pack(side='right', padx=(0, kit.px(8)))

    def _export(self):
        from tkinter import filedialog
        if not self.all_entries:
            self.hub.toast('Nothing to export yet')
            return
        path = filedialog.asksaveasfilename(
            parent=self.hub.root, title='Export history', defaultextension='.md',
            initialfile='whisper-local-history.md',
            filetypes=[('Markdown', '*.md'), ('Text', '*.txt')])
        if not path:
            return
        entries = filter_entries(self.all_entries, self.query.get())
        with open(path, 'w', encoding='utf-8') as f:
            f.write(export_text(entries, markdown=path.lower().endswith('.md')))
        self.hub.toast(f"Exported {len(entries):,} dictations", 'success')
