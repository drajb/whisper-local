# hotkey_gestures.py
# Double-tap-to-lock for push-to-talk: hold the record hotkey to dictate as
# usual, or double-tap it to keep recording hands-free and tap once more to
# stop. A pure state machine; the clock and timer are injected so it's tested
# without real key events. hotkey_listener.py feeds it press/release events.

import threading
import time


class TapLatch:
    # States of the push-to-talk hotkey.
    IDLE = 'idle'          # not recording
    HELD = 'held'          # recording while the key is held
    PENDING = 'pending'    # a quick tap just ended; waiting to see if a 2nd tap follows
    LATCHED = 'latched'    # hands-free: recording without holding

    # is_recording reports the recorder's real state, so the latch resyncs when
    # a recording ends some other way (silence timeout, cancel key) and the
    # next tap starts a new one instead of being swallowed as a "stop".
    def __init__(self, start, stop, window_ms: int = 400, is_recording=None,
                 clock=time.monotonic, timer_factory=None):
        self._start = start
        self._stop = stop
        self._is_recording = is_recording
        self.window = max(50, int(window_ms)) / 1000.0
        self._clock = clock
        self._timer_factory = timer_factory or self._thread_timer
        self._timer = None
        self._pressed_at = 0.0
        self._ignore_press_until = 0.0
        self._lock = threading.Lock()
        self.state = self.IDLE

    @staticmethod
    def _thread_timer(seconds, callback):
        timer = threading.Timer(seconds, callback)
        timer.daemon = True
        timer.start()
        return timer

    def _cancel_timer(self):
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    # Key down. From idle it starts recording; during the double-tap window it
    # latches (recording simply continues); while latched it stops.
    def press(self):
        with self._lock:
            state = self.state
            if state in (self.LATCHED, self.PENDING) and self._is_recording and not self._is_recording():
                self._cancel_timer()
                state = self.IDLE
            if state == self.IDLE and self._clock() < self._ignore_press_until:
                action = None  # the chord finishing after a stop key; see intercept_stop_key()
            elif state == self.IDLE:
                self.state = self.HELD
                self._pressed_at = self._clock()
                action = self._start
            elif state == self.PENDING:
                self._cancel_timer()
                self.state = self.LATCHED
                action = None
            elif state == self.LATCHED:
                self.state = self.IDLE
                action = self._stop
            else:
                action = None  # key repeat while held
        if action:
            action()

    # Key up. A long hold stops as normal push-to-talk does. A quick tap waits
    # out the window first, because stopping at once would transcribe a
    # fraction of a second and discard the start of a hands-free session.
    def release(self):
        with self._lock:
            if self.state != self.HELD:
                return  # latched (or already idle): release means nothing
            if self._clock() - self._pressed_at >= self.window:
                self.state = self.IDLE
                action = self._stop
            else:
                self.state = self.PENDING
                self._timer = self._timer_factory(self.window, self._window_expired)
                action = None
        if action:
            action()

    # No second tap arrived in time: that was just a short push-to-talk.
    def _window_expired(self):
        with self._lock:
            if self.state != self.PENDING:
                return
            self.state = self.IDLE
            self._timer = None
        self._stop()

    # Called by the listener when the stop key is pressed. The default stop key
    # is part of the record chord (Ctrl in Ctrl+Win, Fn in Fn+Ctrl), so it fires
    # the moment a tap on the chord begins. Returns True when that stop must be
    # ignored: during the double-tap window it's the start of the second tap.
    # While locked the stop is real, and the chord press that may complete an
    # instant later is swallowed so it can't start a new recording.
    def intercept_stop_key(self) -> bool:
        with self._lock:
            if self.state == self.PENDING:
                return True
            if self.state == self.LATCHED:
                self.state = self.IDLE
                self._ignore_press_until = self._clock() + self.window
            return False
