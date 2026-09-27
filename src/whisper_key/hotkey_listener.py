# hotkey_listener.py
# Registers global hotkeys and maps them to StateManager actions: record (toggle
# or push-to-talk), stop, auto-send, cancel, command mode, AI rephrase, pause-all,
# paste-last and per-transform hotkeys. Handles PTT press/release (with optional
# double-tap-to-lock) and re-registration when transforms or hotkey config
# change. Backed by the platform.hotkeys layer.

import logging

from .hotkey_gestures import TapLatch
from .platform import hotkeys
from .state_manager import StateManager

class HotkeyListener:
    def __init__(self, state_manager: StateManager, recording_hotkey: str, stop_key: str,
                 auto_send_key: str = None, cancel_combination: str = None,
                 command_hotkey: str = None, rephrase_hotkey: str = None,
                 pause_hotkey: str = None, transforms_manager=None,
                 recording_mode: str = "push_to_talk", paste_last_hotkey: str = None,
                 double_tap_to_lock: bool = False, double_tap_window_ms: int = 400):
        self.state_manager = state_manager
        self.recording_hotkey = recording_hotkey
        self.stop_key = stop_key
        self.auto_send_key = auto_send_key
        self.cancel_combination = cancel_combination
        self.command_hotkey = command_hotkey
        self.rephrase_hotkey = rephrase_hotkey
        self.pause_hotkey = pause_hotkey
        self.transforms_manager = transforms_manager
        self.recording_mode = recording_mode
        self.paste_last_hotkey = paste_last_hotkey
        # Hands-free double-tap only applies to push-to-talk; toggle mode is
        # already hands-free.
        self.tap_latch = None
        if double_tap_to_lock and recording_mode == "push_to_talk":
            self.tap_latch = TapLatch(
                start=self._standard_hotkey_pressed,
                stop=self._push_to_talk_released,
                window_ms=double_tap_window_ms,
                is_recording=lambda: self.state_manager.audio_recorder.get_recording_status(),
            )
        self.keys_armed = True
        self.is_listening = False
        self.is_paused = False
        self.logger = logging.getLogger(__name__)

        self._setup_hotkeys()

        self.start_listening()

    # Builds the binding table handed to the platform backend. Push-to-talk needs
    # both press AND release callbacks (hold to record); toggle mode needs only
    # press. Optional hotkeys (rephrase / command / cancel / pause) are registered
    # only when configured, so an unset key never occupies a combination.
    def _setup_hotkeys(self):
        hotkey_configs = []

        if self.recording_mode == "push_to_talk" and self.tap_latch:
            hotkey_configs.append({
                'combination': self.recording_hotkey,
                'callback': self.tap_latch.press,
                'release_callback': self.tap_latch.release,
                'name': 'standard (push-to-talk, double-tap to lock)'
            })
        elif self.recording_mode == "push_to_talk":
            hotkey_configs.append({
                'combination': self.recording_hotkey,
                'callback': self._standard_hotkey_pressed,
                'release_callback': self._push_to_talk_released,
                'name': 'standard (push-to-talk)'
            })
        else:
            hotkey_configs.append({
                'combination': self.recording_hotkey,
                'callback': self._standard_hotkey_pressed,
                'release_callback': self._arm_keys_on_release,
                'name': 'standard'
            })

        hotkey_configs.append({
            'combination': self.stop_key,
            'callback': self._stop_key_pressed,
            'release_callback': self._arm_keys_on_release,
            'name': 'stop'
        })

        if self.auto_send_key:
            hotkey_configs.append({
                'combination': self.auto_send_key,
                'callback': self._auto_send_key_pressed,
                'release_callback': self._arm_keys_on_release,
                'name': 'auto-send'
            })

        if self.cancel_combination:
            hotkey_configs.append({
                'combination': self.cancel_combination,
                'callback': self._cancel_hotkey_pressed,
                'name': 'cancel'
            })

        if self.command_hotkey:
            if self.recording_mode == "push_to_talk":
                hotkey_configs.append({
                    'combination': self.command_hotkey,
                    'callback': self._command_hotkey_pressed,
                    'release_callback': self._push_to_talk_released,
                    'name': 'command (push-to-talk)'
                })
            else:
                hotkey_configs.append({
                    'combination': self.command_hotkey,
                    'callback': self._command_hotkey_pressed,
                    'name': 'command'
                })

        if self.rephrase_hotkey:
            hotkey_configs.append({
                'combination': self.rephrase_hotkey,
                'callback': self._rephrase_hotkey_pressed,
                'release_callback': self._rephrase_hotkey_released,
                'name': 'rephrase (push-to-talk)'
            })

        # Fires on press: the macOS backend only reports releases for
        # modifier-only chords. The paste itself waits for the modifiers to be
        # let go (StateManager._wait_for_modifiers_released).
        if self.paste_last_hotkey:
            hotkey_configs.append({
                'combination': self.paste_last_hotkey,
                'callback': self._paste_last_hotkey_pressed,
                'name': 'paste last'
            })

        if self.pause_hotkey:
            hotkey_configs.append({
                'combination': self.pause_hotkey,
                'callback': self._pause_hotkey_pressed,
                'name': 'pause'
            })

        if self.transforms_manager:
            def make_transform_callback(transform_name):
                return lambda: self.state_manager.apply_transform(transform_name)
            for transform in self.transforms_manager.transforms_with_hotkeys():
                hotkey_configs.append({
                    'combination': transform['hotkey'],
                    'callback': make_transform_callback(transform.get('name', '?')),
                    'name': f"transform:{transform.get('name', '?')}"
                })

        hotkey_configs.sort(key=self._get_hotkey_combination_specificity, reverse=True)

        self.hotkey_bindings = []
        for config in hotkey_configs:
            hotkey = config['combination'].lower().strip()
            is_pause = config['name'] == 'pause'
            self.hotkey_bindings.append([
                hotkey,
                self._gated(config['callback'], is_pause),
                self._gated(config.get('release_callback'), is_pause),
                False
            ])
            self.logger.info(f"Configured {config['name']} hotkey: {hotkey}")

        self.logger.info(f"Total hotkeys configured: {len(self.hotkey_bindings)}")

    # Pause works by GATING callbacks, never by re-registering hotkeys.
    #
    # Re-registering from inside a hotkey callback is unsafe with
    # global-hotkeys 0.1.7 (issue #7): its checker iterates a live view of the
    # bindings dict and invokes callbacks from inside that loop, so clearing
    # mid-iteration raises RuntimeError and kills the checker thread. And its
    # stop() only flips a flag without joining, so restarting while the pause
    # chord is still physically held gives the new thread blank press-state —
    # it sees the held chord as a fresh press and toggles pause again.
    #
    # So the registration set never changes while paused. Every non-pause
    # callback simply returns early, and the pause key only flips a flag.
    def _gated(self, callback, is_pause: bool):
        if callback is None:
            return None
        if is_pause:
            return callback  # pause itself must always work, to un-pause

        def gated_callback():
            if self.is_paused:
                return
            callback()

        return gated_callback

    def _get_hotkey_combination_specificity(self, hotkey_config: dict) -> int:
        combination = hotkey_config['combination'].lower()
        return len(combination.split('+'))

    def _standard_hotkey_pressed(self):
        self.logger.info(f"Standard hotkey pressed: {self.recording_hotkey}")
        self.keys_armed = False
        self.state_manager.start_recording()

    def _push_to_talk_released(self):
        self.logger.info("Push-to-talk key released")
        self.state_manager.stop_recording()

    def _stop_key_pressed(self):
        self.logger.debug(f"Stop key pressed: {self.stop_key}, keys_armed={self.keys_armed}")
        if self.tap_latch and self.tap_latch.intercept_stop_key():
            self.logger.debug("Stop key ignored - second tap of a double-tap")
            return

        if self.keys_armed:
            self.logger.info(f"Stop key activated: {self.stop_key}")
            self.state_manager.stop_recording()
        else:
            self.logger.debug("Stop key ignored - waiting for key release first")

    def _auto_send_key_pressed(self):
        self.logger.debug(f"Auto-send key pressed: {self.auto_send_key}, keys_armed={self.keys_armed}")
        if self.tap_latch and self.tap_latch.intercept_stop_key():
            return

        if not self.state_manager.audio_recorder.get_recording_status():
            self.logger.debug("Auto-send key ignored - not currently recording")
            return

        if not self.keys_armed:
            self.logger.debug("Auto-send key ignored - waiting for key release first")
            return

        self.keys_armed = False

        self.state_manager.stop_recording(use_auto_enter=True)

    def _cancel_hotkey_pressed(self):
        self.logger.info(f"Cancel hotkey pressed: {self.cancel_combination}")
        self.state_manager.cancel_recording_hotkey_pressed()

    def _command_hotkey_pressed(self):
        self.logger.info(f"Command hotkey pressed: {self.command_hotkey}")
        self.keys_armed = False
        self.state_manager.start_command_recording()

    def _rephrase_hotkey_pressed(self):
        self.logger.info(f"Rephrase hotkey pressed: {self.rephrase_hotkey}")
        self.keys_armed = False
        self.state_manager.start_rephrase_recording()

    def _rephrase_hotkey_released(self):
        self.logger.info("Rephrase hotkey released")
        self.keys_armed = True
        self.state_manager.stop_recording()

    # Own thread: the paste waits for modifiers to be let go, and the hotkey
    # listener thread must never block on that.
    def _paste_last_hotkey_pressed(self):
        import threading
        self.logger.info(f"Paste-last hotkey: {self.paste_last_hotkey}")
        threading.Thread(target=self.state_manager.paste_last_transcription,
                         daemon=True, name='paste-last').start()

    def _pause_hotkey_pressed(self):
        self.is_paused = not self.is_paused
        # Deliberately no stop()/register()/start() here — see _gated(). The
        # bindings stay exactly as registered; only this flag changes.
        if self.is_paused:
            self.logger.info("Hotkeys paused")
            print("\n⏸  Whisper Local hotkeys PAUSED. Press again to resume.")
        else:
            self.logger.info("Hotkeys resumed")
            print("\n▶  Whisper Local hotkeys RESUMED.")
        self.state_manager.set_paused(self.is_paused)

    def _arm_keys_on_release(self):
        self.logger.debug("Key released - arming stop/auto-send keys")
        self.keys_armed = True

    def start_listening(self):
        if self.is_listening:
            return

        try:
            hotkeys.register(self.hotkey_bindings)
            hotkeys.start()
            self.is_listening = True

        except Exception as e:
            self.logger.error(f"Failed to start hotkey listener: {e}")
            raise

    def stop_listening(self):
        if not self.is_listening:
            return

        try:
            hotkeys.stop()
            self.is_listening = False
            self.logger.info("Hotkey listener stopped")

        except Exception as e:
            self.logger.error(f"Error stopping hotkey listener: {e}")

    def change_hotkey_config(self, setting: str, value):
        valid_settings = ['recording_hotkey', 'stop_key', 'auto_send_key', 'cancel_combination', 'command_hotkey', 'rephrase_hotkey', 'pause_hotkey', 'paste_last_hotkey', 'recording_mode']

        if setting not in valid_settings:
            raise ValueError(f"Invalid setting '{setting}'. Valid options: {valid_settings}")

        old_value = getattr(self, setting)

        if old_value == value:
            return

        setattr(self, setting, value)
        self.logger.info(f"Changed {setting}: {old_value} -> {value}")

        self.stop_listening()
        self._setup_hotkeys()
        self.start_listening()

    def is_active(self) -> bool:
        return self.is_listening

    def refresh_transforms(self):
        if not self.transforms_manager:
            return
        self.transforms_manager.reload_if_changed()
        self.logger.info("Re-registering hotkeys to pick up transform changes")
        try:
            self.stop_listening()
            self._setup_hotkeys()
            self.start_listening()
        except Exception as e:
            self.logger.error(f"Failed to refresh transform hotkeys: {e}")
