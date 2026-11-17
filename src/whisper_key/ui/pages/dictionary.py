# ui/pages/dictionary.py
# Teach Whisper your words. Two lists: dictionary words (names, jargon,
# acronyms Whisper is nudged toward while it listens) and corrections (text
# Whisper keeps writing, replaced by what you meant after it transcribes).
# Both write straight to user_settings.yaml through dictionary.py and
# corrections.py, and apply from the next dictation.

import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Field, Card, _bg_of
from .history import open_suggest_dialog


class Page(BasePage):
    title = 'Dictionary'
    subtitle = 'Names, jargon and fixes, so your words come out right.'

    def build(self, body):
        kit, p = self.kit, self.p
        self.action('Suggest from history', lambda: open_suggest_dialog(self.hub, self._refresh),
                    icon='sparkles')
        self.words_area = tk.Frame(body, bg=p['bg'])
        self.words_area.pack(fill='x')
        self.fixes_area = tk.Frame(body, bg=p['bg'])
        self.fixes_area.pack(fill='x')
        self._refresh()

    def _refresh(self):
        for area in (self.words_area, self.fixes_area):
            for child in area.winfo_children():
                child.destroy()
        self._words(self.words_area)
        self._corrections(self.fixes_area)

    # ── Words ────────────────────────────────────────────────────────────

    def _words(self, parent):
        from ...dictionary import list_hotwords
        kit, p = self.kit, self.p
        section = self.section(parent, 'Words',
                               'Whisper listens for these and spells them as written. Best for '
                               'names, product names and acronyms.')
        bg = p['surface']
        add = tk.Frame(section, bg=bg)
        add.pack(fill='x', padx=kit.px(12), pady=kit.px(12))
        word = tk.StringVar(master=self.hub.root)

        def submit():
            self._add_word(word.get())
        Button(add, kit, 'Add', submit, variant='primary', icon='plus', bg=bg).pack(side='right')
        Field(add, kit, word, placeholder='Add a word, e.g. Kubernetes', bg=bg,
              on_submit=submit).pack(side='left', fill='x', expand=True, padx=(0, kit.px(10)))
        words = sorted(list_hotwords(), key=str.lower)
        if not words:
            kit.label(section, 'No words yet.', 'small', 'text_faint', bg=bg).pack(
                anchor='w', padx=kit.px(14), pady=(0, kit.px(12)))
            return
        # A read-only Text holding chip widgets wraps them like words in a line.
        flow = tk.Text(section, bg=bg, bd=0, highlightthickness=0, wrap='char', cursor='arrow',
                       height=1, padx=0, pady=0, font=kit.font('caption'))
        flow.pack(fill='x', padx=kit.px(12), pady=(0, kit.px(12)))
        for w in words:
            flow.window_create('end', window=self._chip(flow, w), padx=kit.px(3), pady=kit.px(3))
        flow.configure(state='disabled')

        # A Text's height is set in lines of its font, so convert the pixel
        # height of the wrapped chips into caption-size lines.
        def fit(_e=None):
            try:
                pixels = flow.count('1.0', 'end', 'ypixels')[0]
            except Exception:
                pixels = kit.px(40)
            line = max(1, kit.line_height('caption'))
            wanted = max(1, -(-pixels // line))
            if int(flow.cget('height')) != wanted:
                flow.configure(height=wanted)
        flow.bind('<Configure>', lambda e: flow.after_idle(fit))

    def _chip(self, parent, word):
        kit, p = self.kit, self.p
        role = 'body'
        w = kit.measure(word, role) + kit.px(46)
        h = kit.px(32)
        chip = tk.Canvas(parent, width=w, height=h, bg=_bg_of(parent), highlightthickness=0, bd=0)
        kit.round_rect(chip, 0, 0, w, h, h // 2, p['field'], p['border'])
        chip.create_text(kit.px(14), h // 2, text=word, anchor='w', fill=p['text'], font=kit.font(role))
        x_icon = chip.create_image(w - kit.px(16), h // 2, image=kit.icon('x', 14, p['text_faint']))
        chip.tag_bind(x_icon, '<Button-1>', lambda e: self._remove_word(word))
        chip.tag_bind(x_icon, '<Enter>', lambda e: chip.configure(cursor='hand2'))
        chip.tag_bind(x_icon, '<Leave>', lambda e: chip.configure(cursor='arrow'))
        return chip

    def _add_word(self, word):
        from ...dictionary import add_word
        word = (word or '').strip()
        if not word:
            return
        if add_word(word):
            self.hub.toast(f"Added “{word}”", 'success')
        else:
            self.hub.toast(f"“{word}” is already in your dictionary")
        self._refresh()

    def _remove_word(self, word):
        from ...dictionary import remove_word
        remove_word(word)
        self.hub.toast(f"Removed “{word}”")
        self._refresh()

    # ── Corrections ──────────────────────────────────────────────────────

    def _corrections(self, parent):
        from ...corrections import list_replacements
        kit, p = self.kit, self.p
        section = self.section(parent, 'Corrections',
                               'When Whisper writes the text on the left, you get the text on the '
                               'right. Whole words, any capitalisation.')
        bg = p['surface']
        add = tk.Frame(section, bg=bg)
        add.pack(fill='x', padx=kit.px(12), pady=kit.px(12))
        wrong, right = tk.StringVar(master=self.hub.root), tk.StringVar(master=self.hub.root)

        def submit():
            self._add_correction(wrong.get(), right.get())
        Button(add, kit, 'Add', submit, variant='primary', icon='plus', bg=bg).pack(side='right')
        Field(add, kit, right, placeholder='You meant', bg=bg, on_submit=submit).pack(
            side='right', fill='x', expand=True, padx=(kit.px(8), kit.px(10)))
        tk.Label(add, image=kit.icon('chevron_right', 16, p['text_faint']), bg=bg).pack(side='right')
        Field(add, kit, wrong, placeholder='Whisper writes', bg=bg, on_submit=submit).pack(
            side='right', fill='x', expand=True, padx=(0, kit.px(8)))
        for item in list_replacements():
            source, target = str(item.get('from', '')), str(item.get('to', ''))
            tk.Frame(section, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(12))
            row = tk.Frame(section, bg=bg)
            row.pack(fill='x', padx=kit.px(12), pady=kit.px(8))
            Button(row, kit, '', lambda s=source: self._remove_correction(s), variant='ghost',
                   icon='trash', size='sm', bg=bg).pack(side='right')
            kit.label(row, source, 'body', 'text_muted', bg=bg).pack(side='left')
            tk.Label(row, image=kit.icon('chevron_right', 14, p['text_faint']), bg=bg).pack(
                side='left', padx=kit.px(8))
            kit.label(row, target, 'body_strong', bg=bg).pack(side='left')

    def _add_correction(self, wrong, right):
        from ...corrections import add_replacement
        if add_replacement(wrong, right):
            self.hub.toast('Correction added', 'success')
            self._refresh()
        else:
            self.hub.toast('Enter what Whisper writes and a different correction')

    def _remove_correction(self, source):
        from ...corrections import remove_replacement
        remove_replacement(source)
        self.hub.toast('Correction removed')
        self._refresh()
