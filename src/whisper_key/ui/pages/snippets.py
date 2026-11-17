# ui/pages/snippets.py
# Spoken shortcuts: say a trigger phrase mid-dictation ("my email") and the
# full text is typed instead. ${date}, ${time} and ${clipboard} are filled in
# when the snippet is used. Stored under postprocess.snippets and applied by
# snippets.py on the next dictation, no restart needed.

import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Field, Card, ThinScrollbar


def normalize_trigger(trigger: str) -> str:
    return ' '.join((trigger or '').split()).lower()


# Returns the new snippet list with (trigger -> expansion) added, replacing an
# existing snippet with the same trigger. None when the input isn't usable.
def with_snippet(snippets, trigger: str, expansion: str):
    trigger = normalize_trigger(trigger)
    if not trigger or not (expansion or '').strip():
        return None
    kept = [dict(s) for s in (snippets or [])
            if isinstance(s, dict) and normalize_trigger(s.get('trigger', '')) != trigger]
    kept.append({'trigger': trigger, 'expansion': expansion.rstrip('\n')})
    return kept


def without_snippet(snippets, trigger: str):
    trigger = normalize_trigger(trigger)
    return [dict(s) for s in (snippets or [])
            if isinstance(s, dict) and normalize_trigger(s.get('trigger', '')) != trigger]


class Page(BasePage):
    title = 'Snippets'
    subtitle = 'Say a short phrase, get the full text. Great for emails, links and sign-offs.'

    def build(self, body):
        kit, p = self.kit, self.p
        self.list_area = tk.Frame(body, bg=p['bg'])
        self._editor(body)
        self.list_area.pack(fill='x')
        self._refresh()

    def _snippets(self):
        self.hub.reload_config()
        return list(((self.hub.cm.config.get('postprocess') or {}).get('snippets')) or [])

    def _editor(self, body):
        kit, p = self.kit, self.p
        section = self.section(body, 'New snippet')
        bg = p['surface']
        box = tk.Frame(section, bg=bg)
        box.pack(fill='x', padx=kit.px(12), pady=kit.px(12))
        self.trigger = tk.StringVar(master=self.hub.root)
        kit.label(box, 'When you say', 'small_strong', bg=bg).pack(anchor='w')
        Field(box, kit, self.trigger, placeholder='e.g. my email', bg=bg).pack(fill='x', pady=(kit.px(4), kit.px(10)))
        kit.label(box, 'Type this', 'small_strong', bg=bg).pack(anchor='w')
        wrap = tk.Frame(box, bg=p['field'], highlightthickness=max(1, kit.px(1)),
                        highlightbackground=p['border'], highlightcolor=p['accent'])
        wrap.pack(fill='x', pady=(kit.px(4), kit.px(6)))
        self.expansion = tk.Text(wrap, height=3, bd=0, highlightthickness=0, wrap='word',
                                 bg=p['field'], fg=p['text'], insertbackground=p['text'],
                                 selectbackground=p['selection'], font=kit.font('body'),
                                 padx=kit.px(10), pady=kit.px(8))
        self.expansion.pack(fill='x')
        kit.label(box, 'Tip: ${date}, ${time} and ${clipboard} are filled in when the snippet is used.',
                  'caption', 'text_faint', bg=bg).pack(anchor='w')
        Button(box, kit, 'Save snippet', self._save, variant='primary', icon='check',
               bg=bg).pack(anchor='e', pady=(kit.px(10), 0))

    def _refresh(self):
        kit, p = self.kit, self.p
        for child in self.list_area.winfo_children():
            child.destroy()
        snippets = self._snippets()
        if not snippets:
            self.empty_state(self.list_area, 'snippets', 'No snippets yet',
                             'Add one above. Say the phrase in any dictation and the full text '
                             'is typed in its place.')
            return
        section = self.section(self.list_area, f"Your snippets ({len(snippets)})")
        bg = p['surface']
        for i, item in enumerate(snippets):
            if not isinstance(item, dict):
                continue
            if i:
                tk.Frame(section, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(12))
            row = tk.Frame(section, bg=bg)
            row.pack(fill='x', padx=kit.px(12), pady=kit.px(10))
            trigger = str(item.get('trigger', ''))
            actions = tk.Frame(row, bg=bg)
            actions.pack(side='right', anchor='n')
            Button(actions, kit, '', lambda t=trigger, e=str(item.get('expansion', '')): self._edit(t, e),
                   variant='ghost', icon='style', size='sm', bg=bg).pack(side='left')
            Button(actions, kit, '', lambda t=trigger: self._delete(t), variant='ghost', icon='trash',
                   size='sm', bg=bg).pack(side='left')
            text = tk.Frame(row, bg=bg)
            text.pack(side='left', fill='x', expand=True)
            kit.label(text, f"“{trigger}”", 'body_strong', bg=bg).pack(anchor='w')
            kit.label(text, str(item.get('expansion', '')), 'small', 'text_muted', bg=bg,
                      wrap=True).pack(fill='x', pady=(kit.px(2), 0))

    def _save(self):
        updated = with_snippet(self._snippets(), self.trigger.get(), self.expansion.get('1.0', 'end-1c'))
        if updated is None:
            self.hub.toast('Enter a phrase and the text it should type')
            return
        if self.hub.save('postprocess.snippets', updated):
            self.hub.toast('Snippet saved: works from your next dictation', 'success')
            self.trigger.set('')
            self.expansion.delete('1.0', 'end')
            self._refresh()

    def _edit(self, trigger, expansion):
        self.trigger.set(trigger)
        self.expansion.delete('1.0', 'end')
        self.expansion.insert('1.0', expansion)
        self.scroller.scroll_to_top()
        self.expansion.focus_set()

    def _delete(self, trigger):
        if self.hub.save('postprocess.snippets', without_snippet(self._snippets(), trigger)):
            self.hub.toast('Snippet deleted')
            self._refresh()
