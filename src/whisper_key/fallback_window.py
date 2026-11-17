# fallback_window.py
# Safety net for dictation with nowhere to go. When no text field is focused,
# auto-paste would silently drop the transcript — instead it appears here in a
# small window, pre-selected, so the user never loses what they just said.
# Runs its own Tk root on a daemon thread.
#
# Normally the transcript is also placed on the clipboard. When the user has
# asked for clipboard-free dictation (allow_clipboard=False) this window is the
# ONLY copy of the text, so it never copies on its own — the Copy button is
# there for when they want it.

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

WIDTH = 540        # logical pixels; the kit scales them for the display
MIN_LINES = 3
MAX_LINES = 14


class FallbackWindow:
    def __init__(self):
        self._available = self._check_tk()
        # Guard against stacking: only one fallback window (and its Tk root) is
        # alive at a time. This both avoids a window pile-up on repeated failed
        # deliveries and keeps us to a single transient Tk root coexisting with
        # the always-on level overlay. Normally the caller has already copied the
        # transcript before show(), so skipping a duplicate never loses it. With
        # clipboard copying off there is no such safety net, and show() logs a
        # warning in that case.
        self._lock = threading.Lock()
        self._open = False

    def _check_tk(self) -> bool:
        try:
            import tkinter  # noqa
            return True
        except ImportError:
            return False

    # allow_clipboard=False means the user asked for clipboard-free dictation,
    # so the window shows the text but never copies it on its own. The Copy
    # button still works — that is the user asking (issue #12).
    def show(self, transcript: str, reason: Optional[str] = None,
             allow_clipboard: bool = True):
        if not self._available or not transcript:
            return
        reason = reason or "No text field was focused — your dictation is safe here."
        # Where Tk can't run on this worker thread (macOS), the window gets its
        # own process instead. The transcript travels over a pipe, never argv.
        from .window_launcher import open_in_child_process
        if open_in_child_process('fallback', {'transcript': transcript, 'reason': reason,
                                              'allow_clipboard': allow_clipboard}):
            return
        with self._lock:
            if self._open:
                if allow_clipboard:
                    logger.info("Fallback window already open; skipping duplicate "
                                "(transcript is already on the clipboard).")
                else:
                    # Nothing is on the clipboard to fall back on, so this one
                    # really is lost. Say so loudly rather than at info level.
                    logger.warning("Fallback window already open and clipboard "
                                   "copying is off; this transcript was not shown.")
                return
            self._open = True
        thread = threading.Thread(
            target=self._run_window,
            args=(transcript, reason, allow_clipboard),
            daemon=True,
            name='fallback-window',
        )
        thread.start()

    # Window body, run on a daemon thread with its own Tk root. The transcript is
    # inserted pre-selected so a single Ctrl+C (or the Copy button) rescues it —
    # this window only ever appears when delivery already had nowhere to go.
    def _run_window(self, transcript: str, reason: str,
                    allow_clipboard: bool = True):
        try:
            import tkinter as tk
            import pyperclip
            from .ui.kit import new_window, Button, Card, ThinScrollbar

            root, kit = new_window("Whisper Local · Dictation captured", size=(WIDTH, 300),
                                   resizable=True)
            p = kit.p
            try:
                root.attributes('-topmost', True)
            except Exception:
                pass

            outer = kit.frame(root, bg=p['bg'])
            outer.pack(fill='both', expand=True, padx=kit.px(22), pady=kit.px(18))

            head = kit.frame(outer)
            head.pack(fill='x')
            badge = tk.Canvas(head, width=kit.px(40), height=kit.px(40), bg=p['bg'], highlightthickness=0)
            kit.round_rect(badge, 0, 0, kit.px(40), kit.px(40), kit.px(11), p['accent_soft'])
            badge.create_image(kit.px(20), kit.px(20), image=kit.icon('copy', 20, p['accent']))
            badge.pack(side='left', anchor='n')
            titles = kit.frame(head)
            titles.pack(side='left', fill='x', expand=True, padx=(kit.px(12), 0))
            kit.label(titles, "Dictation captured", 'title').pack(anchor='w')
            kit.label(titles, reason, 'small', 'text_muted', wrap=True).pack(fill='x', pady=(kit.px(2), 0))

            # Footer first, so it keeps its place when the window is short.
            button_row = kit.frame(outer)
            button_row.pack(side='bottom', fill='x', pady=(kit.px(14), 0))

            card = Card(outer, kit, padding=12, fill=p['field'], stretch=True)
            card.pack(fill='both', expand=True, pady=(kit.px(14), 0))
            scrollbar = ThinScrollbar(card.body, kit, bg=p['field'])
            scrollbar.pack(side='right', fill='y')
            text_widget = tk.Text(
                card.body, wrap='word', bg=p['field'], fg=p['text'], insertbackground=p['accent'],
                selectbackground=p['selection'], selectforeground=p['text'],
                bd=0, highlightthickness=0, relief='flat', font=kit.font('body'),
                spacing3=kit.px(4), padx=kit.px(2))
            text_widget.pack(side='left', fill='both', expand=True)
            text_widget.configure(yscrollcommand=scrollbar.set)
            scrollbar.command = text_widget.yview
            text_widget.insert('1.0', transcript)
            text_widget.tag_add('sel', '1.0', 'end-1c')

            # Grow with the transcript, within reason.
            lines = max(MIN_LINES, min(MAX_LINES, transcript.count(chr(10)) + 1 + len(transcript) // 64))
            height = kit.px(190) + lines * kit.line_height('body')
            root.geometry(f"{kit.px(WIDTH)}x{height}")

            # master=root: a Variable without one binds to the first Tk root in
            # the process (the level overlay, on Windows), and this label then
            # shows that interpreter's empty copy instead of the text below.
            status_var = tk.StringVar(master=root, value=(
                "Already on your clipboard: paste anywhere with Ctrl+V."
                if allow_clipboard else
                "Clipboard copying is off. Press Copy if you want it there."))
            tk.Label(button_row, textvariable=status_var, bg=p['bg'], fg=p['text_muted'],
                     font=kit.font('small')).pack(side='left')

            def _copy_again(_=None):
                try:
                    pyperclip.copy(transcript)
                    status_var.set("Copied! Paste anywhere with Ctrl+V.")
                    btn_copy.configure_text("Copied")
                    root.after(1400, lambda: btn_copy.configure_text("Copy"))
                except Exception as e:
                    status_var.set(f"Copy failed: {e}")

            def _dismiss(_=None):
                try:
                    root.destroy()
                except Exception:
                    pass

            btn_copy = Button(button_row, kit, "Copy", _copy_again, variant='primary', icon='copy')
            btn_copy.pack(side='right')
            Button(button_row, kit, "Close", _dismiss).pack(side='right', padx=(0, kit.px(8)))

            root.bind('<Escape>', _dismiss)
            root.bind('<Control-c>', _copy_again)
            text_widget.focus_set()

            # Only pre-fill the clipboard when automatic copying is permitted.
            if allow_clipboard:
                try:
                    pyperclip.copy(transcript)
                except Exception:
                    pass

            root.mainloop()
        except Exception as e:
            logger.warning(f"Fallback window failed: {e}")
        finally:
            with self._lock:
                self._open = False
