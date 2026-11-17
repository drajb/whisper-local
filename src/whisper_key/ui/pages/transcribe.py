# ui/pages/transcribe.py
# Turn an audio or video file into text or subtitles, offline (the feature
# MacWhisper is built around). Pick a file, watch the transcript arrive with a
# progress bar, then copy it or save it as text, SRT, WebVTT or Markdown. The
# work runs on a thread; results come back through a queue the page polls, so
# the window never freezes.

import queue
import threading
import tkinter as tk
from pathlib import Path

from ..hub import BasePage
from ..kit import Button, Card, Select, ThinScrollbar

POLL_MS = 120
_model_cache = {}   # one loaded model per hub session, reused between files


class Page(BasePage):
    title = 'Transcribe'
    subtitle = 'Turn recordings into text or subtitles. Nothing leaves this computer.'
    scroll = False

    def build(self, body):
        self.events = queue.Queue()
        self.cancel = None
        self.worker = None
        self.segments = []
        self.source = None
        self.container = tk.Frame(body, bg=self.p['bg'])
        self.container.pack(fill='both', expand=True)
        self._show_picker()

    def _clear(self):
        for child in self.container.winfo_children():
            child.destroy()

    # ── Step 1: choose a file ─────────────────────────────────────────────

    def _show_picker(self, message=None):
        from ...file_transcription import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
        kit, p = self.kit, self.p
        self._clear()
        card = Card(self.container, kit, padding=40)
        card.pack(fill='x')
        b = card.body
        badge = tk.Canvas(b, width=kit.px(64), height=kit.px(64), bg=p['surface'], highlightthickness=0)
        kit.round_rect(badge, 0, 0, kit.px(64), kit.px(64), kit.px(18), p['accent_soft'])
        badge.create_image(kit.px(32), kit.px(32), image=kit.icon('upload', 28, p['accent']))
        badge.pack(pady=(kit.px(6), kit.px(14)))
        kit.label(b, 'Choose a recording to transcribe', 'title', anchor='center').pack()
        formats = ', '.join(e.lstrip('.') for e in AUDIO_EXTENSIONS + VIDEO_EXTENSIONS)
        kit.label(b, f"Audio or video: {formats}", 'small', 'text_muted', anchor='center',
                  justify='center', wrap=True).pack(fill='x', pady=(kit.px(6), kit.px(18)))
        Button(b, kit, 'Choose file…', self._choose, variant='primary', icon='folder', size='lg').pack()
        model = (self.config.get('whisper') or {}).get('model', 'base')
        kit.label(b, f"Uses your dictation model ({model}). Bigger models are slower but more accurate; "
                  f"change it in Settings.", 'caption', 'text_faint', anchor='center', justify='center',
                  wrap=True).pack(fill='x', pady=(kit.px(16), 0))
        if message:
            kit.label(b, message, 'small', 'danger', anchor='center').pack(pady=(kit.px(10), 0))

    def _choose(self):
        from tkinter import filedialog
        from ...file_transcription import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, is_supported_file
        patterns = ' '.join(f'*{e}' for e in AUDIO_EXTENSIONS + VIDEO_EXTENSIONS)
        path = filedialog.askopenfilename(parent=self.hub.root, title='Choose a recording',
                                          filetypes=[('Audio and video', patterns), ('All files', '*.*')])
        if not path:
            return
        if not is_supported_file(path):
            self._show_picker("That file type isn't supported.")
            return
        self._start(Path(path))

    # ── Step 2: transcribing ──────────────────────────────────────────────

    def _start(self, path: Path):
        kit, p = self.kit, self.p
        self.source = path
        self.segments = []
        self.cancel = threading.Event()
        self._clear()
        card = Card(self.container, kit, padding=22, stretch=True)
        card.pack(fill='both', expand=True)
        b = card.body
        bg = p['surface']
        head = tk.Frame(b, bg=bg)
        head.pack(fill='x')
        tk.Label(head, image=kit.icon('transcribe', 20, p['accent']), bg=bg).pack(side='left')
        kit.label(head, path.name, 'heading', bg=bg).pack(side='left', padx=(kit.px(8), 0))
        self.actions_row = tk.Frame(head, bg=bg)
        self.actions_row.pack(side='right')
        self.cancel_button = Button(self.actions_row, kit, 'Cancel', self._cancel, bg=bg)
        self.cancel_button.pack(side='right')

        self.status = kit.label(b, 'Loading the model…', 'small', 'text_muted', bg=bg)
        self.status.pack(anchor='w', pady=(kit.px(12), kit.px(6)))
        self.bar = tk.Canvas(b, height=kit.px(8), bg=bg, highlightthickness=0, bd=0)
        self.bar.pack(fill='x')
        self.bar.bind('<Configure>', lambda e: self._draw_bar())
        self.fraction = 0.0

        wrap = tk.Frame(b, bg=bg)
        wrap.pack(fill='both', expand=True, pady=(kit.px(16), 0))
        scrollbar = ThinScrollbar(wrap, kit, bg=bg)
        scrollbar.pack(side='right', fill='y')
        self.text = tk.Text(wrap, wrap='word', bd=0, highlightthickness=0, bg=bg, fg=p['text'],
                            font=kit.font('body'), selectbackground=p['selection'],
                            insertbackground=p['accent'], spacing3=kit.px(6))
        self.text.pack(side='left', fill='both', expand=True)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.command = self.text.yview
        self.text.tag_configure('time', foreground=p['text_faint'], font=kit.font('mono_small'))

        config = self.hub.cm.config
        self.worker = threading.Thread(target=self._work, args=(path, config, self.cancel),
                                       daemon=True, name='file-transcription')
        self.worker.start()
        self.hub.root.after(POLL_MS, self._poll)

    def _draw_bar(self):
        kit, p = self.kit, self.p
        self.bar.delete('all')
        w, h = self.bar.winfo_width(), self.bar.winfo_height()
        kit.round_rect(self.bar, 0, 0, w, h, h // 2, p['field'])
        if self.fraction > 0:
            kit.round_rect(self.bar, 0, 0, max(h, w * self.fraction), h, h // 2, p['accent'])

    # Worker thread: never touches Tk, only posts events.
    def _work(self, path, config, cancel):
        from ...file_transcription import transcribe_file, load_model, Cancelled
        try:
            whisper = config.get('whisper') or {}
            key = (whisper.get('model'), whisper.get('device'), whisper.get('compute_type'))
            if key not in _model_cache:
                _model_cache.clear()
                _model_cache[key] = load_model(config)
            self.events.put(('started', None))
            transcribe_file(path, config, model=_model_cache[key], cancel=cancel,
                            on_progress=lambda f, s: self.events.put(('progress', (f, s))))
            self.events.put(('done', None))
        except Cancelled:
            self.events.put(('cancelled', None))
        except Exception as e:
            self.events.put(('error', str(e)))

    def _poll(self):
        try:
            if not self.frame.winfo_exists():
                return
        except tk.TclError:
            return
        finished = False
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'started':
                self.status.configure(text='Transcribing…')
            elif kind == 'progress':
                fraction, segment = data
                self.fraction = fraction
                self._draw_bar()
                if segment is not None:
                    self.segments.append(segment)
                    minutes, secs = divmod(int(segment.start), 60)
                    self.text.insert('end', f"{minutes:02d}:{secs:02d}  ", 'time')
                    self.text.insert('end', segment.text.strip() + '\n')
                    self.text.see('end')
                    self.status.configure(text=f"Transcribing… {int(fraction * 100)}%")
            elif kind == 'done':
                finished = True
                self._finished()
            elif kind == 'cancelled':
                finished = True
                self._show_picker('Cancelled.')
            elif kind == 'error':
                finished = True
                self._show_picker(f"Couldn't transcribe that file: {data}")
        if not finished:
            self.hub.root.after(POLL_MS, self._poll)

    def _cancel(self):
        if self.cancel:
            self.cancel.set()
            self.status.configure(text='Stopping…')

    # ── Step 3: done ──────────────────────────────────────────────────────

    def _finished(self):
        kit, p = self.kit, self.p
        bg = p['surface']
        self.fraction = 1.0
        self._draw_bar()
        words = sum(len(s.text.split()) for s in self.segments)
        self.status.configure(text=f"Done · {len(self.segments)} segments · {words:,} words")
        self.cancel_button.destroy()
        self.format_var = tk.StringVar(master=self.hub.root, value='txt')
        Button(self.actions_row, kit, 'Transcribe another', self._show_picker, variant='ghost',
               bg=bg).pack(side='right', padx=(kit.px(8), 0))
        Button(self.actions_row, kit, 'Save…', self._save, variant='primary', icon='download',
               bg=bg).pack(side='right', padx=(kit.px(8), 0))
        Select(self.actions_row, kit, self.format_var,
               [('txt', 'Plain text'), ('srt', 'SRT subtitles'), ('vtt', 'WebVTT subtitles'),
                ('md', 'Markdown')], bg=bg).pack(side='right', padx=(kit.px(8), 0))
        Button(self.actions_row, kit, 'Copy', self._copy, icon='copy', bg=bg).pack(side='right')

    def _copy(self):
        import pyperclip
        from ...file_transcription import to_txt
        pyperclip.copy(to_txt(self.segments))
        self.hub.toast('Transcript copied', 'success')

    def _save(self):
        from tkinter import filedialog
        from ...file_transcription import render
        fmt = self.format_var.get()
        path = filedialog.asksaveasfilename(
            parent=self.hub.root, title='Save transcript', defaultextension=f'.{fmt}',
            initialdir=str(self.source.parent), initialfile=f"{self.source.stem}.{fmt}")
        if not path:
            return
        Path(path).write_text(render(self.segments, fmt, title=self.source.stem), encoding='utf-8')
        self.hub.toast(f"Saved {Path(path).name}", 'success')

    def on_leave(self):
        if self.cancel:
            self.cancel.set()
