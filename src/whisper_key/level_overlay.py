# level_overlay.py
# The floating recording pill near the screen edge that proves the app is
# hearing you: a live waveform that moves with your voice, the streaming
# transcript preview, and success or failure flashes at the end of a
# recording. Failures show their reason here (not just a tray balloon)
# because Windows focus-assist silently swallows balloons. Other threads never
# touch Tk: _call() queues work, and the overlay's own thread drains the queue
# (see _pump), because a cross-thread Tk call can deadlock.
#
# It is a true capsule: drawn on a canvas whose background colour is made
# transparent, so only the rounded pill shows, and it renders at the
# monitor's real DPI. It stays dark in both themes because it floats over
# whatever the user is working in.

import logging
import math
import platform
import queue
import random
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class LevelOverlay:
    # Sizes in logical (96-dpi) pixels; scaled for the display at start.
    WIDTH = 300
    HEIGHT = 40
    WAVE_AREA_PX = 74
    BOTTOM_OFFSET_PX = 96
    BARS = 9

    BG = '#141418'
    OUTLINE = '#2c2c34'
    BAR = '#f4f4f6'
    BAR_PROCESSING = '#8f80ff'
    BAR_SUCCESS = '#3ccf7a'
    BAR_ERROR = '#ff6161'
    TEXT = '#e9e9ee'
    TEXT_DIM = '#9a9aa6'
    # Painted where the window should be see-through. Near the pill colour, so
    # the antialiased edge pixels blend into a dark rim, not a bright fringe.
    TRANSPARENT_KEY = '#010102'

    LEVEL_AMP = 25.0
    UPDATE_HZ = 30
    PUMP_MS = 30   # how often the overlay thread picks up queued work
    FLASH_MS = 450

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
        self._kit = None
        self._text_var = None
        self._text_label = None
        self._thread = None
        self._ready = threading.Event()
        self._mode = 'hidden'
        self._smoothed = 0.0
        self._bar_levels = [0.0] * self.BARS
        self._streaming_text = ''
        self._displayed_chars = 0
        self._flash_color = None
        # Tracks the pending _update_loop after() callback so a new mode switch
        # cancels the old animation loop instead of stacking a second one (which
        # would multiply redraw/CPU load over many record cycles).
        self._update_after_id = None
        self._queue = queue.SimpleQueue()
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

    # ── Public API (any thread) ─────────────────────────────────────────

    def show_recording(self):
        self._call(lambda: self._set_mode('recording'))

    def show_processing(self):
        self._call(lambda: self._set_mode('processing'))

    def hide(self):
        self._call(lambda: self._set_mode('hidden'))

    def flash_success(self):
        self._flash(self.BAR_SUCCESS)

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

    # A warning shown in the pill WHILE recording continues (the pill stays
    # up, unlike a flash). Cleared by clear_notice() or the next mode change.
    def show_notice(self, message: str):
        def do():
            if not self._text_var or self._mode not in ('recording', 'processing'):
                return
            try:
                self._text_var.set(message)
                self._text_label.configure(fg=self.BAR_ERROR)
            except Exception:
                pass
        self._call(do)

    # Takes a notice down again (the mic came back) and restores the normal
    # "Listening…" / streaming text. Does nothing outside a recording.
    def clear_notice(self):
        def do():
            if self._mode in ('recording', 'processing'):
                self._refresh_text()
        self._call(do)

    def set_position(self, name: str):
        if name not in self.POSITIONS:
            return
        self.position = name
        self._call(self._position)

    def shutdown(self):
        if not self.root:
            return
        self._queue.put(self.root.destroy)

    # Hands `fn` to the overlay thread. Never calls into Tk from here: a Tk
    # call from another thread waits on the Tk thread and can deadlock it
    # (it froze the pill whenever another program asked it to repaint).
    def _call(self, fn):
        if not self._available or not self.root:
            return
        self._queue.put(fn)

    # Overlay thread: runs whatever other threads queued, then checks again
    # shortly. The only place queued work executes.
    def _pump(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                logger.warning(f"Overlay call failed: {e}")
        try:
            self.root.after(self.PUMP_MS, self._pump)
        except Exception:
            pass   # the window is gone (shutdown)

    # ── Overlay thread ──────────────────────────────────────────────────

    def _tick_typewriter(self):
        if not self._text_var or self._mode not in ('recording', 'processing'):
            return
        target = self._streaming_text
        if self._displayed_chars >= len(target):
            return
        self._displayed_chars = min(len(target), self._displayed_chars + 3)
        visible = target[:self._displayed_chars]
        display = '…' + visible[-27:] if len(visible) > 28 else visible
        try:
            self._text_var.set(display)
            self._text_label.configure(fg=self.TEXT)
        except Exception:
            return
        if self._displayed_chars < len(target):
            try:
                self.root.after(30, self._tick_typewriter)
            except Exception:
                pass

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
        try:
            self._text_label.configure(fg=self.TEXT_DIM)   # drop any notice colour
        except Exception:
            pass
        if self._mode == 'processing':
            self._text_var.set('Transcribing…')
        elif self._streaming_text:
            text = self._streaming_text
            if len(text) > 28:
                text = '…' + text[-27:]
            self._text_var.set(text)
            self._text_label.configure(fg=self.TEXT)
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
            if self._text_var:
                try:
                    self._text_var.set(message or ('Done' if color == self.BAR_SUCCESS else ''))
                    self._text_label.configure(fg=color if message else self.TEXT_DIM)
                except Exception:
                    pass
            try: self.root.deiconify()
            except Exception: pass
            self._draw_wave([0.55] * self.BARS, color)
            # Hold a message flash longer so it's actually readable.
            hold = 2200 if message else self.FLASH_MS
            try:
                self.root.after(hold, lambda: self._set_mode('hidden'))
            except Exception:
                pass
        self._call(do)

    def _run(self):
        try:
            import tkinter as tk
            from .ui.kit import prepare_dpi, Kit
            prepare_dpi()
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes('-topmost', True)
            self._kit = Kit(self.root)
            kit = self._kit
            self._w, self._h = kit.px(self.WIDTH), kit.px(self.HEIGHT)
            key = self.BG
            try:
                self.root.attributes('-transparentcolor', self.TRANSPARENT_KEY)
                key = self.TRANSPARENT_KEY
            except Exception:
                pass   # no colour keys here: the pill keeps square corners
            try:
                self.root.attributes('-alpha', 0.96)
            except Exception:
                pass
            self.root.configure(bg=key)

            self.canvas = tk.Canvas(self.root, width=self._w, height=self._h, bg=key,
                                    highlightthickness=0, bd=0)
            self.canvas.pack(fill='both', expand=True)
            kit.round_rect(self.canvas, 0, 0, self._w, self._h, self._h // 2, self.BG,
                           self.OUTLINE, tag='pill', antialias=(key == self.BG))

            self._text_var = tk.StringVar(master=self.root, value='')
            self._text_label = tk.Label(self.canvas, textvariable=self._text_var, bg=self.BG,
                                        fg=self.TEXT_DIM, font=kit.font('small'), anchor='w', bd=0)
            text_x = kit.px(14 + self.WAVE_AREA_PX + 6)
            self.canvas.create_window(text_x, self._h // 2, window=self._text_label, anchor='w',
                                      width=self._w - text_x - kit.px(16))

            self._position()
            self._make_click_through()
            self.root.after(self.PUMP_MS, self._pump)
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
            kit = self._kit
            px = kit.px if kit else (lambda n: n)
            width = getattr(self, '_w', self.WIDTH)
            height = getattr(self, '_h', self.HEIGHT)

            margin = px(self.BOTTOM_OFFSET_PX)
            top_margin = px(56)
            x_margin = px(28)

            pos = self.POSITIONS[self.position]
            y = screen_h - margin - height if pos.startswith('B') else top_margin
            if pos.endswith('C'):
                x = (screen_w - width) // 2
            elif pos.endswith('R'):
                x = screen_w - width - x_margin
            else:
                x = x_margin

            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except Exception as e:
            logger.debug(f"Position failed: {e}")

    # Lets mouse clicks pass through the pill to whatever is underneath.
    #
    # The style must go on the top-level FRAME window. winfo_id() is Tk's inner
    # child window, and this used to set WS_EX_LAYERED | WS_EX_TRANSPARENT on
    # that child: a layered window paints nothing until its layer attributes
    # are set, so the pill stayed invisible whenever click-through was on (the
    # default), and clicks didn't pass through either, because the frame never
    # got WS_EX_TRANSPARENT (issue #35). Tk has already made the frame layered
    # for its -alpha, so adding WS_EX_TRANSPARENT there is all that's needed.
    def _make_click_through(self):
        if not self.click_through or platform.system() != 'Windows':
            return
        try:
            import ctypes
            self.root.update_idletasks()   # the frame exists once Tk has mapped it
            frame = int(self.root.wm_frame(), 16)
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            user32 = ctypes.windll.user32
            current = user32.GetWindowLongW(frame, GWL_EXSTYLE)
            user32.SetWindowLongW(frame, GWL_EXSTYLE, current | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception as e:
            # Visible, at a level that reaches app.log: a failure here used to
            # vanish at debug level, so a broken overlay left no trace.
            logger.warning(f"Overlay click-through setup failed: {e}")

    # One animation frame: each bar chases the mic level, shaped so the middle
    # bars move most, with a little per-bar randomness so it reads as a voice
    # rather than a single meter. While transcribing, a soft wave travels
    # across the bars instead.
    def _update_loop(self):
        if self._mode not in ('recording', 'processing') or not self.root:
            return
        try:
            level = float(self.level_provider())
        except Exception:
            level = 0.0
        target = min(1.0, max(0.0, level * self.LEVEL_AMP))
        self._smoothed = self._smoothed * 0.5 + target * 0.5
        heights = []
        now = time.time()
        for i in range(self.BARS):
            if self._mode == 'processing':
                wanted = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(now * 6 - i * 0.7))
            else:
                profile = 1.0 - abs(i - (self.BARS - 1) / 2) / ((self.BARS + 1) / 2)
                wanted = 0.12 + self._smoothed * (0.45 + 0.55 * profile) * random.uniform(0.7, 1.15)
            self._bar_levels[i] = self._bar_levels[i] * 0.45 + min(1.0, wanted) * 0.55
            heights.append(self._bar_levels[i])
        color = self.BAR_PROCESSING if self._mode == 'processing' else self.BAR
        self._draw_wave(heights, color)
        try:
            self._update_after_id = self.root.after(int(1000 / self.UPDATE_HZ), self._update_loop)
        except Exception:
            self._update_after_id = None

    def _draw_wave(self, heights, color):
        if not self.canvas or not self._kit:
            return
        try:
            kit = self._kit
            c = self.canvas
            c.delete('wave')
            left = kit.px(16)
            area = kit.px(self.WAVE_AREA_PX)
            step = area / self.BARS
            bar_w = max(2, int(step * 0.45))
            mid = self._h / 2
            max_half = self._h * 0.30
            for i, level in enumerate(heights):
                x = left + step * i + step / 2
                half = max(bar_w / 2, max_half * level)
                c.create_line(x, mid - half + bar_w / 2, x, mid + half - bar_w / 2, fill=color,
                              width=bar_w, capstyle='round', tags='wave')
        except Exception:
            pass

    # Kept for callers and tests that draw a single level.
    def _draw(self, level: float, override_color: Optional[str] = None):
        self._draw_wave([level] * self.BARS, override_color or self.BAR)
