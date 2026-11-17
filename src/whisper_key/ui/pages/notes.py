# ui/pages/notes.py
# A scratchpad for drafts (Wispr Flow's Scratchpad, offline): a list of notes
# beside a roomy editor. It is an ordinary text field, so dictation lands in
# it like anywhere else. Every edit autosaves to a Markdown file in the notes
# folder (notes.py); deleting moves the note to notes/trash.

import tkinter as tk

from ..hub import BasePage
from ..kit import Button, Field, Card, ScrollFrame, ThinScrollbar

AUTOSAVE_MS = 700


def relative_time(when, now=None) -> str:
    import datetime
    now = now or datetime.datetime.now()
    seconds = (now - when).total_seconds()
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if when.date() == now.date():
        return when.strftime('%H:%M')
    if (now.date() - when.date()).days == 1:
        return 'yesterday'
    return when.strftime('%b %d').replace(' 0', ' ')


class Page(BasePage):
    title = 'Notes'
    subtitle = 'A scratchpad for drafts. Click into a note and dictate as usual.'
    scroll = False

    def build(self, body):
        from ... import notes as store
        self.store = store
        kit, p = self.kit, self.p
        self.current_id = None
        self._save_pending = None
        self.action('New note', self._new_note, variant='primary', icon='plus')

        layout = tk.Frame(body, bg=p['bg'])
        layout.pack(fill='both', expand=True)
        left = tk.Frame(layout, bg=p['bg'], width=kit.px(270))
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        self.query = tk.StringVar(master=self.hub.root)
        Field(left, kit, self.query, placeholder='Search notes', icon='search').pack(fill='x')
        self.query.trace_add('write', lambda *_: self._render_list())
        self.list = ScrollFrame(left, kit, bg=p['bg'])
        self.list.pack(fill='both', expand=True, pady=(kit.px(10), 0))

        editor_card = Card(layout, kit, padding=1, radius=14, stretch=True)
        editor_card.pack(side='left', fill='both', expand=True, padx=(kit.px(18), 0))
        self.editor_area = editor_card.body
        self._build_editor(editor_card.body)
        self._render_list()
        notes = store.list_notes()
        if notes:
            self._open(notes[0]['id'])
        else:
            self._new_note()

    def _build_editor(self, parent):
        kit, p = self.kit, self.p
        bg = p['surface']
        toolbar = tk.Frame(parent, bg=bg)
        toolbar.pack(fill='x', padx=kit.px(20), pady=(kit.px(14), 0))
        self.saved_label = kit.label(toolbar, '', 'caption', 'text_faint', bg=bg)
        self.saved_label.pack(side='left')
        Button(toolbar, kit, '', self._delete, variant='ghost', icon='trash', size='sm', bg=bg).pack(side='right')
        Button(toolbar, kit, '', self._copy, variant='ghost', icon='copy', size='sm', bg=bg).pack(side='right')
        wrap = tk.Frame(parent, bg=bg)
        wrap.pack(fill='both', expand=True, padx=(kit.px(24), kit.px(8)), pady=(kit.px(6), kit.px(18)))
        bar = ThinScrollbar(wrap, kit, bg=bg)
        bar.pack(side='right', fill='y')
        self.text = tk.Text(wrap, wrap='word', bd=0, highlightthickness=0, relief='flat',
                            bg=bg, fg=p['text'], insertbackground=p['accent'],
                            selectbackground=p['selection'], selectforeground=p['text'],
                            font=kit.font('body'), padx=0, pady=kit.px(4), undo=True,
                            spacing1=kit.px(2), spacing3=kit.px(6), insertwidth=kit.px(2))
        self.text.pack(side='left', fill='both', expand=True)
        self.text.configure(yscrollcommand=bar.set)
        bar.command = self.text.yview
        self.text.tag_configure('title', font=kit.font('title'), spacing3=kit.px(10))
        self.text.bind('<<Modified>>', self._on_modified)

    # The first line reads as the note's title, so give it a title's size.
    def _style_title(self):
        self.text.tag_remove('title', '1.0', 'end')
        self.text.tag_add('title', '1.0', '1.end')

    def _render_list(self):
        kit, p = self.kit, self.p
        for child in self.list.inner.winfo_children():
            child.destroy()
        q = self.query.get().strip().lower()
        notes = [n for n in self.store.list_notes()
                 if not q or q in n['title'].lower() or q in n['preview'].lower()]
        if not notes:
            kit.label(self.list.inner, 'No notes match.' if q else 'No notes yet.',
                      'small', 'text_faint').pack(anchor='w', pady=kit.px(8))
            return
        for note in notes:
            self._list_item(note)

    def _list_item(self, note):
        kit, p = self.kit, self.p
        selected = note['id'] == self.current_id
        fill = p['accent_soft'] if selected else p['bg']
        item = tk.Frame(self.list.inner, bg=fill, cursor='hand2')
        item.pack(fill='x', pady=kit.px(2), padx=(0, kit.px(6)))
        inner = tk.Frame(item, bg=fill)
        inner.pack(fill='x', padx=kit.px(12), pady=kit.px(9))
        kit.label(inner, note['title'], 'body_strong', bg=fill).pack(anchor='w')
        preview = note['preview'][len(note['title']):].strip()[:80] or ' '
        kit.label(inner, preview, 'small', 'text_muted', bg=fill).pack(anchor='w')
        kit.label(inner, relative_time(note['updated']), 'caption', 'text_faint', bg=fill).pack(anchor='w')
        for widget in (item, inner, *inner.winfo_children()):
            widget.bind('<Button-1>', lambda e, nid=note['id']: self._open(nid))

    def _open(self, note_id):
        self._flush()
        self.current_id = note_id
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', self.store.read_note(note_id))
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._style_title()
        self.saved_label.configure(text='Saved')
        self._render_list()
        self.text.focus_set()
        self.text.mark_set('insert', 'end-1c')

    def _new_note(self):
        self._flush()
        note_id = self.store.new_note_id()
        self.store.save_note(note_id, '')
        self._open(note_id)

    def _on_modified(self, _e=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self._style_title()
        self.saved_label.configure(text='Editing…')
        if self._save_pending:
            self.hub.root.after_cancel(self._save_pending)
        self._save_pending = self.hub.root.after(AUTOSAVE_MS, self._save)

    def _save(self):
        self._save_pending = None
        if not self.current_id:
            return
        self.store.save_note(self.current_id, self.text.get('1.0', 'end-1c'))
        self.saved_label.configure(text='Saved')
        self._render_list()

    # Writes any pending edit now (switching notes, leaving the page).
    def _flush(self):
        if self._save_pending:
            self.hub.root.after_cancel(self._save_pending)
            self._save()

    def on_leave(self):
        self._flush()

    def _copy(self):
        import pyperclip
        pyperclip.copy(self.text.get('1.0', 'end-1c'))
        self.hub.toast('Note copied', 'success')

    def _delete(self):
        if not self.current_id:
            return
        if not self.kit.confirm(self.hub.root, 'Delete this note?',
                                'It moves to the notes/trash folder, so you can still get it back.',
                                confirm_text='Delete', danger=True):
            return
        self._save_pending and self.hub.root.after_cancel(self._save_pending)
        self._save_pending = None
        self.store.delete_note(self.current_id)
        self.current_id = None
        notes = self.store.list_notes()
        if notes:
            self._open(notes[0]['id'])
        else:
            self._new_note()
        self.hub.toast('Note moved to trash')
