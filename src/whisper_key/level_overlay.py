# level_overlay.py
# Small always-on-top pill near the screen edge that proves the app is hearing
# you: a live mic level bar, the streaming transcript preview, and success or
# failure flashes at the end of a recording. Failures show their reason here
# (not just a tray balloon) because Windows focus-assist silently swallows
# balloons. All Tk work is marshalled onto the overlay's own thread via _call().

import logging
import platform
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class LevelOverlay:
    WIDTH = 320
    HEIGHT = 28
    BG = '#0d1117'
    BAR = '#3fb950'
    BAR_ERROR = '#f85149'
    DIM = '#30363d'
    TEXT = '#c9d1d9'
    LEVEL_AREA_PX = 96
    BOTTOM_OFFSET_PX = 80
    LEVEL_AMP = 25.0
    UPDATE_HZ = 25
    FLASH_MS = 400

    POSITIONS = {
        'bottom-center': 'BC',
        'bottom-right': 'BR',
        'bottom-left': 'BL',
        'top-center': 'TC',
        'top-right': 'TR',
        'top-left': 'TL',
    }

    def __init__(self, level_provider: Callable[[], float],
                 click_through: bool = True,
                 position: str = 'bottom-center'):
        self.level_provider = level_provider
        self.click_through = click_through
        self.position = position if position in self.POSITIONS else 'bottom-center'

        self.root: Optional[object] = None
        self.canvas = None
        self._level_canvas = None
        self._text_var = None
        self._thread = None
        self._ready = threading.Event()
        self._mode = 'hidden'
        self._smoothed = 0.0
        self._streaming_text = ''
        self._displayed_chars = 0
        self._flash_color = None
        # Tracks the pending _update_loop after() callback so a new mode switch
        # cancels the old animation loop instead of stacking a second one (which
        # would multiply redraw/CPU load over many record cycles).
        self._update_after_id = None
        self._available = self._check_tk()

    def _check_tk(self) -> bool:
        try:
            import tkinter  # noqa
            return True
        except ImportError:
            logger.info("Tkinter not available; level overlay disabled")
            return False

    def start(self):
        if not self._available or (self._thread and self._thread.is_alive()):
            return
        # The pill needs a Tk mainloop running for the life of the app. Where Tk
        # is main-thread-only (macOS), the main thread is already pumping the
        # NSApplication loop, and a worker-thread root aborts the whole process
        # (issue #14). Stand down rather than take the app with us; every other
        # method is inert once _available is False.
        from .utils import tk_requires_main_thread
        if tk_requires_main_thread():
            logger.info("Level overlay not supported on this platform yet; disabled")
            self._available = False
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name='level-overlay')
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def show_recording(self):
        self._call(lambda: self._set_mode('recording'))

    def show_processing(self):
        self._call(lambda: self._set_mode('processing'))

    def hide(self):
        self._call(lambda: self._set_mode('hidden'))

    def flash_success(self):
        self._flash(self.BAR)

    # message: shown in the pill during the flash (held longer so it's readable).
    # Used to surface failures where the user is already looking, since Windows
    # often suppresses tray balloons.
    def flash_failure(self, message: str = None):
        self._flash(self.BAR_ERROR, message)

    def set_streaming_text(self, text: str):
        new_text = (text or '').strip()
        if new_text == self._streaming_text:
            return
        if not new_text.startswith(self._streaming_text):
            self._displayed_chars = 0
        self._streaming_text = new_text
        self._call(self._tick_typewriter)

    def _tick_typewriter(self):
        if not self._text_var or self._mode not in ('recording', 'processing'):
            return
        target = self._streaming_text
        if self._displayed_chars >= len(target):
            return
        self._displayed_chars = min(len(target), self._displayed_chars + 3)
        visible = target[:self._displayed_chars]
        display = '…' + visible[-31:] if len(visible) > 32 else visible
        try:
            self._text_var.set(display)
        except Exception:
            return
        if self._displayed_chars < len(target):
            try:
                self.root.after(30, self._tick_typewriter)
            except Exception:
                pass

    def set_position(self, name: str):
        if name not in self.POSITIONS:
            return
        self.position = name
        self._call(self._position)

    def shutdown(self):
        if not self.root:
            return
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    def _call(self, fn):
        if not self._available or not self.root:
            return
        try:
            self.root.after(0, fn)
        except Exception as e:
            logger.debug(f"Overlay call failed: {e}")

    def _set_mode(self, mode: str):
        self._mode = mode
        if mode == 'hidden':
            self._streaming_text = ''
            self._displayed_chars = 0
            self._refresh_text()
            try: self.root.withdraw()
            except Exception: pass
        else:
            try: self.root.deiconify()
            except Exception: pass
            self._smoothed = 0.0
            if mode == 'recording':
                self._displayed_chars = 0
            # Cancel any in-flight loop before starting a fresh one.
            if self._update_after_id is not None:
                try: self.root.after_cancel(self._update_after_id)
                except Exception: pass
                self._update_after_id = None
            self._update_loop()
            self._refresh_text()

    def _refresh_text(self):
        if not self._text_var:
            return
        if self._mode == 'processing':
            self._text_var.set('Transcribing…')
        elif self._streaming_text:
            text = self._streaming_text
            if len(text) > 32:
                text = '…' + text[-31:]
            self._text_var.set(text)
        else:
            self._text_var.set('Listening…')

    def _flash(self, color: str, message: str = None):
        if not self._available:
            return

        def do():
            if not self.root:
                return
            self._mode = 'flash'
            self._flash_color = color
            if message and self._text_var:
                try: self._text_var.set(message)
                except Exception: pass
            try: self.root.deiconify()
            except Exception: pass
            self._draw(1.0, override_color=color)
            # Hold a message flash longer so it's actually readable.
            hold = 2000 if message else self.FLASH_MS
            try:
                self.root.after(hold, lambda: self._set_mode('hidden'))
            except Exception:
                pass
        self._call(do)

    def _run(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes('-topmost', True)
            try:
                self.root.attributes('-alpha', 0.93)
            except Exception:
                pass

            outer = tk.Frame(self.root, bg=self.BG, bd=0, highlightthickness=0)
            outer.pack(fill='both', expand=True)

            self._level_canvas = tk.Canvas(outer, width=self.LEVEL_AREA_PX, height=self.HEIGHT,
                                           bg=self.BG, highlightthickness=0, borderwidth=0)
            self._level_canvas.pack(side='left', padx=(8, 0))

            self._text_var = tk.StringVar(value='')
            self._text_label = tk.Label(outer, textvariable=self._text_var,
                                        bg=self.BG, fg=self.TEXT,
                                        font=('Segoe UI', 9),
                                        anchor='w')
            self._text_label.pack(side='left', fill='x', expand=True, padx=(6, 8))

            self._position()
            self._make_click_through()
            self._ready.set()
            self.root.mainloop()
        except Exception as e:
            logger.warning(f"Level overlay crashed: {e}")
            self._available = False
            self._ready.set()

    def _position(self):
        try:
            self.root.update_idletasks()
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()

            margin = self.BOTTOM_OFFSET_PX
            top_margin = 60
            x_margin = 30

            pos = self.POSITIONS[self.position]
            if pos.startswith('B'):
                y = screen_h - margin
            else:
                y = top_margin
            if pos.endswith('C'):
                x = (screen_w - self.WIDTH) // 2
            elif pos.endswith('R'):
                x = screen_w - self.WIDTH - x_margin
            else:
                x = x_margin

            self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        except Exception as e:
            logger.debug(f"Position failed: {e}")

    def _make_click_through(self):
        if not self.click_through or platform.system() != 'Windows':
            return
        try:
            import ctypes
            hwnd = self.root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            user32 = ctypes.windll.user32
            current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception as e:
            logger.debug(f"Click-through setup failed: {e}")

    def _update_loop(self):
        if self._mode not in ('recording', 'processing') or not self.root:
            return
        try:
            level = float(self.level_provider())
        except Exception:
            level = 0.0

        target = min(1.0, max(0.0, level * self.LEVEL_AMP))
        if self._mode == 'processing':
            import time
            target = 0.3 + 0.3 * abs((time.time() * 2) % 2 - 1)
        self._smoothed = self._smoothed * 0.55 + target * 0.45
        self._draw(self._smoothed)

        try:
            self._update_after_id = self.root.after(int(1000 / self.UPDATE_HZ), self._update_loop)
        except Exception:
            self._update_after_id = None

    def _draw(self, level: float, override_color: Optional[str] = None):
        if not self._level_canvas:
            return
        try:
            c = self._level_canvas
            c.delete('all')

            pad = 6
            bar_total_w = self.LEVEL_AREA_PX - 2 * pad
            baseline_y = self.HEIGHT // 2

            c.create_rectangle(pad, baseline_y - 1, pad + bar_total_w, baseline_y + 1,
                               fill=self.DIM, outline='')

            color = override_color or self.BAR
            fill_w = int(bar_total_w * level)
            if fill_w > 0:
                fill_h = max(4, int(self.HEIGHT * 0.6 * level + 4))
                top = baseline_y - fill_h // 2
                bottom = baseline_y + fill_h // 2
                center_x = pad + bar_total_w // 2
                left = center_x - fill_w // 2
                right = center_x + fill_w // 2
                c.create_rectangle(left, top, right, bottom,
                                   fill=color, outline='')
        except Exception:
            pass
