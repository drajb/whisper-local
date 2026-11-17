# ui/pages/style.py
# How dictated text is tidied and formatted, shown the way Wispr Flow shows
# its Styles: a cleanup level (how much of what you said gets tidied) and a
# writing style picked from example cards. Per-app styles (formal email,
# casual chat, verbatim code) come from app_rules.yaml and win over this one.

import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Card, Segmented

CLEANUP = (
    ('none', 'None', 'Exactly what Whisper heard, ums and all.'),
    ('light', 'Light', 'Removes stutters and filler words like "um" and "uh".'),
    ('medium', 'Medium', 'Also follows corrections you make out loud: "scratch that", '
                         '"meet at 2, actually 3" becomes "meet at 3".'),
    ('high', 'High', 'Also formats spoken times, emails and web addresses: '
                     '"john at example dot com" becomes john@example.com.'),
)

STYLES = (
    ('formal', 'Formal', 'Full sentences with capitals and punctuation.',
     'Hey, are you free for lunch tomorrow? Let’s do 12 if that works.'),
    ('casual', 'Casual', 'Capitalised, but no stiff period at the end.',
     'Hey, are you free for lunch tomorrow? Let’s do 12 if that works'),
    ('very_casual', 'Very casual', 'All lowercase, like texting a friend.',
     'hey, are you free for lunch tomorrow? let’s do 12 if that works'),
    ('verbatim', 'Verbatim', 'No automatic capitals or periods. For code and terminals.',
     'hey are you free for lunch tomorrow lets do 12 if that works'),
)


class Page(BasePage):
    title = 'Style'
    subtitle = 'Choose how much gets tidied and how your writing sounds.'

    def build(self, body):
        from ...text_postprocess import DEFAULT_CLEANUP
        kit, p = self.kit, self.p
        pp = self.config.get('postprocess') or {}
        self.cleanup = tk.StringVar(master=self.hub.root, value=str(pp.get('cleanup') or DEFAULT_CLEANUP))
        self.style = tk.StringVar(master=self.hub.root, value=str(pp.get('style') or ''))

        kit.label(body, 'Cleanup', 'heading').pack(anchor='w', pady=(kit.px(4), kit.px(8)))
        Segmented(body, kit, self.cleanup, [(k, label) for k, label, _ in CLEANUP],
                  command=self._set_cleanup).pack(anchor='w')
        self.cleanup_help = kit.label(body, '', 'small', 'text_muted', wrap=True)
        self.cleanup_help.pack(fill='x', pady=(kit.px(8), kit.px(24)))
        self._describe_cleanup()

        kit.label(body, 'Writing style', 'heading').pack(anchor='w', pady=(0, kit.px(8)))
        self.grid = tk.Frame(body, bg=p['bg'])
        self.grid.pack(fill='x')
        self._draw_cards()
        no_style = tk.Frame(body, bg=p['bg'])
        no_style.pack(fill='x', pady=(kit.px(10), 0))
        self.none_button = Button(no_style, kit, 'Use no style', lambda: self._set_style(''),
                                  variant='ghost', size='sm')
        self.none_button.pack(side='left')
        kit.label(no_style, 'Formatting then follows the individual toggles in Settings.', 'small',
                  'text_faint').pack(side='left', padx=(kit.px(6), 0))

        section = self.section(body, 'Per-app styles',
                               'Out of the box, email apps get formal, chat apps casual and code '
                               'editors verbatim. These rules win over the style above.')
        self.row(section, 'App rules', 'Edit app_rules.yaml to change which app gets which style.',
                 lambda parent: Button(parent, kit, 'Open file', self._open_rules, icon='external',
                                       bg=p['surface']), first=True)

    def _describe_cleanup(self):
        for key, _, text in CLEANUP:
            if key == self.cleanup.get():
                self.cleanup_help.configure(text=text)

    def _set_cleanup(self, value):
        self._describe_cleanup()
        if self.hub.save('postprocess.cleanup', value):
            self.hub.toast('Cleanup updated: applies to your next dictation', 'success')

    def _draw_cards(self):
        kit, p = self.kit, self.p
        for child in self.grid.winfo_children():
            child.destroy()
        for i, (key, name, help_text, example) in enumerate(STYLES):
            selected = self.style.get() == key
            card = Card(self.grid, kit, padding=18,
                        fill=p['accent_soft'] if selected else p['surface'])
            card.grid(row=i // 2, column=i % 2, sticky='nsew',
                      padx=(0, kit.px(6)) if i % 2 == 0 else (kit.px(6), 0), pady=(0, kit.px(12)))
            self.grid.grid_columnconfigure(i % 2, weight=1, uniform='styles')
            bg = p['accent_soft'] if selected else p['surface']
            b = card.body
            top = tk.Frame(b, bg=bg)
            top.pack(fill='x')
            kit.label(top, name, 'heading', 'accent' if selected else 'text', bg=bg).pack(side='left')
            if selected:
                tk.Label(top, image=kit.icon('check', 18, p['accent']), bg=bg).pack(side='right')
            kit.label(b, help_text, 'small', 'text_muted', bg=bg, wrap=True).pack(fill='x', pady=(kit.px(2), kit.px(10)))
            sample = Card(b, kit, padding=12, fill=p['field'], outline=False, radius=10, bg=bg)
            sample.pack(fill='x')
            kit.label(sample.body, example, 'body', bg=p['field'], wrap=True).pack(fill='x')
            for widget in (card, b, top, *b.winfo_children(), sample.body, *sample.body.winfo_children()):
                widget.bind('<Button-1>', lambda e, k=key: self._set_style(k))
                try:
                    widget.configure(cursor='hand2')
                except tk.TclError:
                    pass

    def _set_style(self, key):
        self.style.set(key)
        self._draw_cards()
        if self.hub.save('postprocess.style', key):
            label = next((n for k, n, _, _ in STYLES if k == key), 'No style')
            self.hub.toast(f"{label} style: applies to your next dictation", 'success')

    def _open_rules(self):
        from pathlib import Path
        from ...utils import get_user_app_data_path, open_file
        from ...app_rules import AppRules, USER_FILE
        path = Path(get_user_app_data_path()) / USER_FILE
        if not path.exists():
            AppRules()   # loading writes the user file, with its explanatory header
        open_file(str(path))
