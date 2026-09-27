# state_manager.py
# Central coordinator that owns the dictation pipeline state and routes events
# between components. Roughly:
#
#   HotkeyListener  ─►  StateManager  ─►  AudioRecorder.stop_recording()
#                            │                       │
#                            ▼                       ▼
#                     WhisperEngine.transcribe ──► ClipboardManager.deliver
#                                                     │
#                                                     ▼
#                                            stats + transcripts + audit
#
# Also owns the LevelOverlay + FallbackWindow lifecycle and the cross-cutting
# concerns: profile activation, app-rule application, AI rephrase, command mode,
# and the continuous-dictation restart loop.
#
# Thread safety: most state lives behind self._state_lock. The audio capture
# thread writes recording-status atomically; everything else mutates state
# only from the main thread or via the lock.

import collections
import logging
import time
import threading
import platform
from typing import Optional

import sounddevice as sd

from .audio_recorder import AudioRecorder
from .whisper_engine import WhisperEngine
from .clipboard_manager import ClipboardManager
from .system_tray import SystemTray
from .config_manager import ConfigManager
from .audio_feedback import AudioFeedback
from .utils import OptionalComponent
from .voice_activity_detection import VadEvent, VadManager
from .voice_commands import VoiceCommandManager
from .profiles import ProfileManager
from .app_rules import AppRules, formatting_overrides as app_rules_formatting_overrides, effective_postprocess_config
from .streaming_delivery import StreamingDelivery, decide_stream_delivery
from .transforms import TransformsManager
from .text_postprocess import postprocess
from .stats import record_transcription
from .audit_log import record as audit_record
from .terminal_title import TerminalTitle
from .transcript_log import record_transcript
from .platform import foreground
from .level_overlay import LevelOverlay
from .fallback_window import FallbackWindow

class StateManager:
    def __init__(self,
                 audio_recorder: AudioRecorder,
                 whisper_engine: WhisperEngine,
                 clipboard_manager: ClipboardManager,
                 config_manager: ConfigManager,
                 vad_manager: VadManager,
                 system_tray: Optional[SystemTray] = None,
                 audio_feedback: Optional[AudioFeedback] = None,
                 voice_command_manager: Optional[VoiceCommandManager] = None,
                 terminal_title: Optional[TerminalTitle] = None):

        self.audio_recorder = audio_recorder
        self.whisper_engine = whisper_engine
        self.clipboard_manager = clipboard_manager
        self.system_tray = OptionalComponent(system_tray)
        self.terminal_title = OptionalComponent(terminal_title)
        self.config_manager = config_manager
        self.audio_feedback = OptionalComponent(audio_feedback)
        self.vad_manager = vad_manager
        self.voice_command_manager = voice_command_manager

        self.is_processing = False
        self.is_model_loading = False
        self.is_paused = False
        self.last_transcription = None
        self.recent_transcriptions = collections.deque(maxlen=10)
        self._rephrase_mode = False
        self._rephrase_selection = ''
        self._rephrase_original_clipboard = ''
        self._continuous_aborted = False
        self._hotkey_listener_ref = None
        self._pending_model_change = None
        self._pending_device_change = None
        self._command_mode = False
        self._state_lock = threading.Lock()
        self._streaming_display_active = False
        # Commit-on-endpoint streaming delivery (opt-in). Active only for the
        # current recording when conditions are met; default off → zero impact.
        self._streaming_delivery_active = False
        self.streaming_delivery = None

        self.logger = logging.getLogger(__name__)
        self._current_audio_host = None
        self._initialize_audio_host()
        self.profile_manager = ProfileManager(config_manager)
        self.app_rules = AppRules()
        self.transforms_manager = TransformsManager(
            ollama_config_provider=lambda: (config_manager.get_postprocess_config().get('ollama') or {}),
        )
        self.level_overlay = None
        self.fallback_window = FallbackWindow()

    def attach_components(self,
                          audio_recorder: AudioRecorder,
                          system_tray: Optional[SystemTray]):
        self.audio_recorder = audio_recorder
        self.system_tray = OptionalComponent(system_tray)
        self._ensure_audio_device_for_host(self._current_audio_host)

        try:
            self.transforms_manager.system_tray = system_tray
        except Exception:
            pass

        overlay_cfg = self.config_manager.config.get('overlay', {}) or {}
        if overlay_cfg.get('enabled', True):
            try:
                self.level_overlay = LevelOverlay(
                    level_provider=self.audio_recorder.get_current_level,
                    click_through=overlay_cfg.get('click_through', True),
                    position=overlay_cfg.get('position', 'bottom-center'),
                )
                self.level_overlay.start()
            except Exception as e:
                self.logger.warning(f"Level overlay disabled: {e}")
                self.level_overlay = None
    
    def handle_max_recording_duration_reached(self, audio_data):
        self.logger.info("Max recording duration reached - starting transcription")
        self._transcription_pipeline(audio_data, use_auto_enter=False)

    def handle_vad_event(self, event: VadEvent):
        if event == VadEvent.SILENCE_TIMEOUT:
            self.logger.info("VAD silence timeout detected - stopping recording")
            timeout_seconds = int(self.vad_manager.vad_silence_timeout_seconds)
            self._clear_streaming_display()
            print(f"⏰ Stopping recording after {timeout_seconds} seconds of silence...")
            audio_data = self.audio_recorder.stop_recording()
            self._transcription_pipeline(audio_data, use_auto_enter=False)

    # Called on the audio thread for each streaming result. Updates the overlay
    # preview always; when commit-on-endpoint delivery is active, hands FINALIZED
    # phrases to the delivery worker (never the revising partials).
    def handle_streaming_result(self, text: str, is_final: bool):
        if is_final:
            if self._streaming_display_active:
                print(f"\r   {text:<70}")
                self._streaming_display_active = False
            if self._streaming_delivery_active and self.streaming_delivery:
                self.streaming_delivery.submit_final(text)
        else:
            display_text = text if len(text) < 67 else "..." + text[-64:]
            print(f"\r   {display_text:<70}", end="", flush=True)
            self._streaming_display_active = True
        if self.level_overlay and text:
            self.level_overlay.set_streaming_text(text)

    def _clear_streaming_display(self):
        if self._streaming_display_active:
            print("\r" + " " * 75 + "\r", end="", flush=True)
            self._streaming_display_active = False
    
    def stop_recording(self, use_auto_enter: bool = False) -> bool:
        currently_recording = self.audio_recorder.get_recording_status()

        if currently_recording:
            self._clear_streaming_display()
            audio_data = self.audio_recorder.stop_recording()
            self._transcription_pipeline(audio_data, use_auto_enter)
            return True
        else:
            return False
    
    def cancel_active_recording(self):
        self._clear_streaming_display()
        # Tear down the streaming-delivery worker (already-typed text stays — you
        # can't un-type live output, same as Wispr).
        if self.streaming_delivery:
            try:
                self.streaming_delivery.stop()
            except Exception:
                pass
            self.streaming_delivery = None
        self._streaming_delivery_active = False
        with self._state_lock:
            self._command_mode = False
            self._rephrase_mode = False
            self._rephrase_selection = ''
        self._continuous_aborted = True
        self.audio_recorder.cancel_recording()
        self.audio_feedback.play_cancel_sound()
        self._update_ui_state("idle")
        if self.level_overlay:
            self.level_overlay.hide()
    
    def cancel_recording_hotkey_pressed(self) -> bool:
        current_state = self.get_current_state()
        
        if current_state == "recording":
            print("🎤 Recording cancelled!")            
            self.cancel_active_recording()
            return True
        else:
            return False
    
    def start_recording(self):
        if not self.can_start_recording():
            current_state = self.get_current_state()
            if self.is_processing:
                print("⏳ Still processing previous recording...")
            elif self.is_model_loading:
                print("⏳ Still loading model...")
            else:
                print(f"⏳ Cannot record while {current_state}...")
            return

        self._begin_recording()

    def set_paused(self, paused: bool):
        self.is_paused = paused
        if paused and self.audio_recorder.get_recording_status():
            self.cancel_active_recording()
        self.system_tray.notify("Hotkeys paused" if paused else "Hotkeys resumed")

    def start_rephrase_recording(self):
        if not self.can_start_recording():
            return
        import time
        import pyperclip
        from .platform import keyboard as kb

        try:
            self._rephrase_original_clipboard = pyperclip.paste()
        except Exception:
            self._rephrase_original_clipboard = ''

        kb.send_hotkey('ctrl', 'c')
        time.sleep(0.12)
        try:
            selection = pyperclip.paste()
        except Exception:
            selection = ''
        try:
            pyperclip.copy(self._rephrase_original_clipboard)
        except Exception:
            pass

        if not selection or selection == self._rephrase_original_clipboard:
            print("\n   ✗ Nothing selected — rephrase needs selected text. Recording dictation instead.")
            self._rephrase_selection = ''
        else:
            self._rephrase_selection = selection
            print(f"\n🎙  Rephrase mode: selection captured ({len(selection)} chars)")
            print("   Speak instructions, then release to apply.")

        self._rephrase_mode = True
        self._streaming_delivery_active = False  # rephrase is never live-typed
        self.streaming_delivery = None
        if self.audio_recorder.start_recording():
            self.audio_feedback.play_start_sound()
            self._update_ui_state("recording")
            if self.level_overlay:
                self.level_overlay.show_recording()

    def start_command_recording(self):
        if not self.can_start_recording():
            return

        with self._state_lock:
            self._command_mode = True
        self._streaming_delivery_active = False  # command mode is never live-typed
        self.streaming_delivery = None

        self.logger.info("Starting command mode recording")
        success = self.audio_recorder.start_recording()
        if success:
            print("\n🎤 Command mode activated! Speak a command...")
            self.config_manager.print_command_stop_instructions()
            self.audio_feedback.play_start_sound()
            self._update_ui_state("recording")
            if self.level_overlay:
                self.level_overlay.show_recording()

    def _begin_recording(self):
        self._apply_recording_context()
        self._maybe_pause_media()
        success = self.audio_recorder.start_recording()

        if success:
            # Only spin up the streaming-delivery worker once recording is
            # confirmed — otherwise a failed start would leak the worker thread.
            self._setup_streaming_delivery()
            print("\n🎤 Recording started! Speak now...")
            self.config_manager.print_stop_instructions_based_on_config()
            self.audio_feedback.play_start_sound()
            self._update_ui_state("recording")
            if self.level_overlay:
                self.level_overlay.show_recording()

    # Decide whether this (plain dictation) recording should stream finalized
    # phrases to the cursor live, and if so spin up the delivery worker. Only the
    # plain-dictation path calls this; command/rephrase never stream-deliver.
    def _setup_streaming_delivery(self):
        self._streaming_delivery_active = False
        self.streaming_delivery = None
        streaming_available = bool(getattr(self.audio_recorder, 'continuous_streaming', None))
        active = decide_stream_delivery(
            self.config_manager.get_streaming_config(),
            streaming_available,
            bool(self.clipboard_manager.auto_paste),
            self._foreground_is_textable(),
            self.app_rules.match_for_foreground(),
        )
        if not active:
            return
        self.streaming_delivery = StreamingDelivery(
            deliver_fn=lambda seg: self.clipboard_manager.deliver_transcription(seg, use_auto_enter=False)
        )
        self.streaming_delivery.start()
        self._streaming_delivery_active = True
        self.logger.info("Streaming commit-on-endpoint delivery active for this recording")

    # Flush the trailing in-progress phrase, wait for the worker to finish typing
    # everything, then record + (optionally) press Enter. Returns the delivered
    # text, or '' if nothing was finalized (caller then falls back to Whisper).
    def _finalize_streaming_delivery(self, use_auto_enter: bool, duration: float) -> str:
        sd = self.streaming_delivery
        self._streaming_delivery_active = False
        self.streaming_delivery = None
        if sd is None:
            return ''

        # Deliver the un-endpointed remainder, if any.
        try:
            cont = getattr(self.audio_recorder, 'continuous_streaming', None)
            if cont:
                trailing = cont.finalize()
                if trailing:
                    sd.submit_final(trailing)
        except Exception as e:
            self.logger.debug(f"Streaming flush failed: {e}")

        text = sd.stop()  # drains + joins the worker: all text is on screen now
        if not text:
            return ''

        # If a segment failed to type, some words may be missing. We can't re-run
        # Whisper (it would duplicate what's already typed), so warn instead.
        if sd.had_failure:
            self.logger.warning("Streaming delivery had a failed segment; some words may be missing")
            self.system_tray.notify("Some dictated words may not have typed — please review.")

        if use_auto_enter:
            self.clipboard_manager.send_enter_key()

        self.last_transcription = text
        self.recent_transcriptions.appendleft(text)
        self.system_tray.refresh_menu()
        self.audio_feedback.play_transcription_complete_sound()
        if self.level_overlay:
            self.level_overlay.flash_success()

        fg = foreground.get_foreground_app() or {}
        record_transcription(char_count=len(text), duration_seconds=duration, app=fg.get('exe', ''))
        record_transcript(text, app=fg.get('exe', ''), duration_s=duration)
        audit_enabled = (self.config_manager.config.get('audit') or {}).get('enabled', False)
        audit_record('delivered', text, fg.get('exe', ''), audit_enabled)

        self.logger.info(f"Streaming delivery complete: {len(text)} chars")
        self._maybe_restart_continuous()
        return text

    def _maybe_restart_continuous(self):
        audio_cfg = self.config_manager.config.get('audio', {})
        if not audio_cfg.get('continuous_mode', False) or self.is_paused:
            return
        self._continuous_aborted = False
        import threading
        def restart():
            import time
            time.sleep(0.6)
            if self.is_paused or self._continuous_aborted:
                self.logger.info("Continuous mode: restart aborted")
                return
            if not self.audio_recorder.get_recording_status():
                self.logger.info("Continuous mode: auto-restarting recording")
                self._begin_recording()
        threading.Thread(target=restart, daemon=True, name='continuous-restart').start()

    def _maybe_pause_media(self):
        audio_cfg = self.config_manager.config.get('audio', {})
        if not audio_cfg.get('pause_media_on_record', False):
            return
        try:
            from .platform import keyboard as kb
            kb.send_key('media_play_pause')
            self.logger.debug("Sent media play/pause on recording start")
        except Exception as e:
            self.logger.debug(f"Media pause skipped: {e}")

    def _apply_recording_context(self):
        whisper_cfg = self.config_manager.get_whisper_config()
        prompt_parts = []
        base_prompt = whisper_cfg.get('initial_prompt') or ''
        if base_prompt:
            prompt_parts.append(base_prompt)
        language = whisper_cfg.get('language') or 'auto'
        task = whisper_cfg.get('task') or 'transcribe'

        try:
            rule = self.app_rules.match_for_foreground() or {}
        except Exception:
            rule = {}
        if rule.get('initial_prompt'):
            prompt_parts.append(str(rule['initial_prompt']))
            self.logger.debug(f"App rule {rule.get('match')} → initial_prompt applied")
        if rule.get('language'):
            language = rule['language']
        if rule.get('task'):
            task = rule['task']

        if whisper_cfg.get('prompt_from_selection', False):
            sel = self._grab_selection_text()
            if sel:
                prompt_parts.append(sel)
                self.logger.info(f"Selection seed applied ({len(sel)} chars)")

        combined_prompt = ' '.join(prompt_parts).strip()
        try:
            self.whisper_engine.initial_prompt = combined_prompt or None
            self.whisper_engine.language = None if language == 'auto' else language
            self.whisper_engine.task = task if task in ('transcribe', 'translate') else 'transcribe'
        except Exception as e:
            self.logger.debug(f"Engine context update failed: {e}")

    def _grab_selection_text(self) -> str:
        try:
            import time
            import pyperclip
            from .platform import keyboard as kb
            original = pyperclip.paste()
            kb.send_hotkey('ctrl', 'c')
            time.sleep(0.08)
            selection = pyperclip.paste()
            try: pyperclip.copy(original)
            except Exception: pass
            if selection and selection != original:
                return selection[-200:].replace('\n', ' ')
        except Exception as e:
            self.logger.debug(f"Selection grab failed: {e}")
        return ''
    
    # Tell the user, once per app per session, that a per-app rule made this
    # delivery copy-only. Without it the app looks broken in exactly the place
    # the rule is most useful — a code editor, where the shipped default is
    # copy-only so dictation never types into source by surprise.
    def _announce_copy_only(self, rule):
        try:
            seen = self._copy_only_announced
        except AttributeError:
            seen = self._copy_only_announced = set()
        # Identify by the rule's own match pattern: it is always present,
        # unlike the foreground exe, which isn't looked up until later in
        # the pipeline.
        match = rule.get('match')
        key = str(match)
        if key in seen:
            return
        seen.add(key)
        where = ', '.join(match) if isinstance(match, (list, tuple)) else (match or 'this app')
        self.system_tray.notify(
            f"Copied, not pasted — your app rule for {where} is copy-only. "
            "Press Ctrl+V, or edit app_rules.yaml to change it.")
        self.logger.info(f"Copy-only delivery for {where} (app rule)")

    # The heart of the app: everything between "user released the hotkey" and
    # "text is in their editor". Runs on a worker thread so the hotkey listener
    # never blocks. Order matters — transcribe, then branch by mode (command /
    # rephrase / dictation), then apply app rules + post-processing, then choose a
    # delivery route (suppressed, fallback window, or paste at cursor), and only
    # record stats/history once delivery actually succeeded. Every early return
    # is a legitimate "nothing to deliver" case and must still clear state via
    # the finally block.
    def _transcription_pipeline(self, audio_data, use_auto_enter: bool = False):
        try:
            with self._state_lock:
                self.is_processing = True
                command_mode = self._command_mode
                self._command_mode = False
                rephrase_mode = self._rephrase_mode
                rephrase_selection = self._rephrase_selection
                self._rephrase_mode = False
                self._rephrase_selection = ''

            self.audio_feedback.play_stop_sound()

            if audio_data is None:
                self.system_tray.notify("No audio captured — was the mic muted?")
                # Flash the overlay too — tray balloons are often suppressed by Windows.
                if self.level_overlay:
                    self.level_overlay.flash_failure("No audio — mic muted?")
                return

            duration = self.audio_recorder.get_audio_duration(audio_data)

            # Commit-on-endpoint streaming: if finalized phrases were already typed
            # live during this recording, flush the trailing phrase, record it, and
            # skip the (now redundant) Whisper pass. Falls through to Whisper if
            # nothing was actually finalized (e.g. a very short utterance).
            if self._streaming_delivery_active and self.streaming_delivery:
                if self._finalize_streaming_delivery(use_auto_enter, duration):
                    return

            print(f"   ✓ Recorded {duration:.1f} seconds, transcribing...")

            self._update_ui_state("processing")
            if self.level_overlay:
                self.level_overlay.show_processing()

            transcribed_text = self.whisper_engine.transcribe_audio(audio_data)

            if not transcribed_text:
                self.system_tray.notify("Transcription was empty (silence or noise only).")
                if self.level_overlay:
                    self.level_overlay.flash_failure("No speech detected")
                return

            if command_mode:
                matched = self._handle_command_transcription(transcribed_text, use_auto_enter)
                if self.level_overlay:
                    if matched:
                        self.level_overlay.flash_success()
                    else:
                        self.level_overlay.flash_failure()
                return

            if rephrase_mode and rephrase_selection:
                self._handle_rephrase(rephrase_selection, transcribed_text)
                return

            # Match the foreground app once, before post-processing, so a rule can
            # override formatting (e.g. code editors: verbatim, no auto-caps/periods)
            # in addition to the delivery behaviour handled further down.
            rule = self.app_rules.match_for_foreground()
            raw_postprocess_cfg = self.config_manager.get_postprocess_config()
            fmt_overrides = app_rules_formatting_overrides(rule, raw_postprocess_cfg)
            if fmt_overrides:
                self.logger.info(f"App rule {rule.get('match')} → formatting overrides {fmt_overrides}")
            postprocess_cfg = effective_postprocess_config(raw_postprocess_cfg, rule)
            transcribed_text = postprocess(transcribed_text, postprocess_cfg)

            # Post-processing can legitimately empty the text — e.g. "scratch that"
            # erasing the whole utterance. Don't deliver an empty string (which
            # with auto-enter would just press Enter into the focused field).
            if not transcribed_text or not transcribed_text.strip():
                self.logger.info("Post-processing produced empty text; nothing to deliver")
                if self.level_overlay:
                    self.level_overlay.flash_failure("Nothing to type")
                return

            if rule and rule.get('suppress'):
                self.logger.info(f"Delivery suppressed by app rule: {rule.get('match')}")
                # Clipboard-free setups get the recovery window instead of a
                # silent copy, so the transcript is still retrievable without
                # touching the clipboard behind the user's back (issue #12).
                may_copy = self.clipboard_manager.silent_copy_allowed
                if may_copy:
                    self.clipboard_manager.copy_text(transcribed_text)
                else:
                    self.fallback_window.show(
                        transcribed_text,
                        reason="Delivery is suppressed for this app, and clipboard "
                               "copying is off — your dictation is safe here.",
                        allow_clipboard=False,
                    )
                self.last_transcription = transcribed_text
                self.recent_transcriptions.appendleft(transcribed_text)
                self.system_tray.refresh_menu()
                self.system_tray.notify(
                    "Delivery suppressed for this app — text on clipboard." if may_copy
                    else "Delivery suppressed for this app — see the popup.")
                if self.level_overlay:
                    self.level_overlay.flash_success()
                return

            if not self._foreground_is_textable():
                self.logger.info("No textable foreground window; opening fallback window")
                may_copy = self.clipboard_manager.silent_copy_allowed
                if may_copy:
                    self.clipboard_manager.copy_text(transcribed_text)
                self.fallback_window.show(
                    transcribed_text,
                    reason=("No text field was focused — your dictation is safe here. "
                            "Already on your clipboard.") if may_copy else
                           ("No text field was focused — your dictation is safe here. "
                            "Clipboard copying is off; use Copy if you want it."),
                    allow_clipboard=may_copy,
                )
                self.last_transcription = transcribed_text
                self.recent_transcriptions.appendleft(transcribed_text)
                self.system_tray.refresh_menu()
                self.system_tray.notify("Captured your dictation — see the popup.")
                if self.level_overlay:
                    self.level_overlay.flash_success()
                return

            effective_auto_enter = use_auto_enter
            effective_auto_paste = None
            if rule:
                if rule.get('auto_send') is True:
                    effective_auto_enter = True
                elif rule.get('auto_send') is False:
                    effective_auto_enter = False
                if 'auto_paste' in rule:
                    effective_auto_paste = bool(rule['auto_paste'])

            previous_auto_paste = None
            if effective_auto_paste is not None:
                previous_auto_paste = self.clipboard_manager.auto_paste
                self.clipboard_manager.update_auto_paste(effective_auto_paste)
                # An app rule silently turning paste off reads as "the app is
                # broken" — it was reported as exactly that (issue #11). Say it
                # once per app per session: often enough to explain, rare enough
                # not to nag.
                if previous_auto_paste and not effective_auto_paste:
                    self._announce_copy_only(rule)

            try:
                success = self.clipboard_manager.deliver_transcription(
                    transcribed_text, effective_auto_enter
                )
            finally:
                if previous_auto_paste is not None:
                    self.clipboard_manager.update_auto_paste(previous_auto_paste)

            if success:
                self.last_transcription = transcribed_text
                self.recent_transcriptions.appendleft(transcribed_text)
                self.system_tray.refresh_menu()
                self.audio_feedback.play_transcription_complete_sound()
                if self.level_overlay:
                    self.level_overlay.flash_success()
                fg = foreground.get_foreground_app() or {}
                record_transcription(
                    char_count=len(transcribed_text),
                    duration_seconds=duration,
                    app=fg.get('exe', ''),
                )
                record_transcript(transcribed_text, app=fg.get('exe', ''), duration_s=duration)
                audit_enabled = (self.config_manager.config.get('audit') or {}).get('enabled', False)
                audit_record('delivered', transcribed_text, fg.get('exe', ''), audit_enabled)
                self._maybe_restart_continuous()
            elif self.level_overlay:
                self.level_overlay.flash_failure()
            
        except Exception as e:
            self.logger.error(f"Error in processing workflow: {e}")
            print(f"❌ Error processing recording: {e}")
            if self.level_overlay:
                self.level_overlay.flash_failure()

        finally:
            # Safety net: if a streaming-delivery worker is still around (e.g. the
            # audio came back None and we returned before _finalize_streaming_delivery,
            # or an exception fired), stop+join it here so no path can leak the
            # worker thread or leave _streaming_delivery_active stuck True.
            if self.streaming_delivery is not None:
                try:
                    self.streaming_delivery.stop()
                except Exception:
                    pass
                self.streaming_delivery = None
            self._streaming_delivery_active = False

            with self._state_lock:
                self.is_processing = False
                pending_model = self._pending_model_change
                pending_device = self._pending_device_change

            if pending_device:
                device_id, device_name = pending_device
                self.logger.info(f"Executing pending device change to: {device_name}")
                self._execute_audio_device_change(device_id, device_name)
                self._pending_device_change = None

            if pending_model:
                self.logger.info(f"Executing pending model change to: {pending_model}")
                print(f"🔄 Processing complete, now switching to [{pending_model}] model...")
                self._execute_model_change(pending_model)
                self._pending_model_change = None

            if not (pending_device or pending_model):
                self._update_ui_state("idle")

    def _handle_command_transcription(self, text: str, use_auto_enter: bool = False) -> bool:
        log_config = self.config_manager.get_logging_config()
        if log_config.get('log_transcriptions', False):
            self.logger.info(f"Command mode transcription: '{text}'")
        else:
            self.logger.info("Command mode transcription received")

        if not self.voice_command_manager.enabled:
            self.logger.warning("Voice commands disabled")
            return False

        matched = self.voice_command_manager.match_command(text)
        if matched:
            self.voice_command_manager.execute_command(matched, use_auto_enter)
            return True
        print(f"   ✗ No matching command for: \"{text[:60]}\"")
        return False

    def get_application_state(self) -> dict:
        status = {
            "recording": self.audio_recorder.get_recording_status(),
            "processing": self.is_processing,
            "model_loading": self.is_model_loading,
        }
        
        return status
    
    def manual_transcribe_test(self, duration_seconds: int = 5):
        try:
            print(f"🎤 Recording for {duration_seconds} seconds...")
            print("Speak now!")
            
            self.audio_recorder.start_recording()
            
            time.sleep(duration_seconds)
            
            audio_data = self.audio_recorder.stop_recording()
            self._transcription_pipeline(audio_data)
            
        except Exception as e:
            self.logger.error(f"Manual test failed: {e}")
            print(f"❌ Test failed: {e}")

    # Single place that fans a state change out to every status surface, so
    # the tray icon and the terminal tab title can never drift apart. Both are
    # OptionalComponent-wrapped: a disabled tray or a non-TTY terminal is a
    # silent no-op rather than a branch at each call site.
    def _update_ui_state(self, state: str):
        self.system_tray.update_state(state)
        self.terminal_title.update_state(state)

    
    def shutdown(self):        
        self.terminal_title.stop()
        print("Whisper Local is shutting down... goodbye!")

        if self.audio_recorder.get_recording_status():
            self.audio_recorder.stop_recording()
        self.audio_recorder.shutdown()

        if self.level_overlay:
            self.level_overlay.shutdown()

        self.system_tray.stop()
    
    def set_model_loading(self, loading: bool):
        with self._state_lock:
            old_state = self.is_model_loading
            self.is_model_loading = loading
            
            if old_state != loading:
                if loading:
                    self._update_ui_state("processing")
                else:
                    self._update_ui_state("idle")
    
    def is_transcription_recording(self) -> bool:
        return self.audio_recorder.get_recording_status() and not self._command_mode

    def can_start_recording(self) -> bool:
        with self._state_lock:
            return not (self.is_processing or self.is_model_loading or self.audio_recorder.get_recording_status())
    
    def get_current_state(self) -> str:
        with self._state_lock:
            if self.is_model_loading:
                return "model_loading"
            elif self.is_processing:
                return "processing"
            elif self.audio_recorder.get_recording_status():
                return "recording"
            else:
                return "idle"
    
    def request_model_change(self, new_model_key: str) -> bool:
        current_state = self.get_current_state()
        
        if new_model_key == self.whisper_engine.model_key:
            return True
        
        if current_state == "model_loading":
            print("⏳ Model already loading, please wait...")
            return False
        
        if current_state == "recording":
            print(f"🎤 Cancelling recording to switch to [{new_model_key}] model...")
            self.cancel_active_recording()
            self._execute_model_change(new_model_key)
            return True
        
        if current_state == "processing":
            print(f"⏳ Queueing model change to [{new_model_key}] until transcription completes...")
            self._pending_model_change = new_model_key
            return True
        
        if current_state == "idle":
            self._execute_model_change(new_model_key)
            return True
        
        self.logger.warning(f"Unexpected state for model change: {current_state}")
        return False
    
    def update_transcription_mode(self, value):
        self.config_manager.update_user_setting('clipboard', 'auto_paste', value)
        self.clipboard_manager.update_auto_paste(value)

    def _execute_model_change(self, new_model_key: str):
        def progress_callback(message: str):
            if "ready" in message.lower() or "already loaded" in message.lower():
                print(f"✅ Successfully switched to [{new_model_key}] model")
                self.set_model_loading(False)
            elif "failed" in message.lower():
                print(f"❌ Failed to change model: {message}")
                self.set_model_loading(False)
            else:
                print(f"🔄 {message}")
                self.set_model_loading(True)
        
        try:
            self.set_model_loading(True)
            print(f"🔄 Switching to [{new_model_key}] model...")
            
            self.whisper_engine.change_model(new_model_key, progress_callback)
            
        except Exception as e:
            self.logger.error(f"Failed to initiate model change: {e}")
            print(f"❌ Failed to change model: {e}")
            self.set_model_loading(False)

    def _handle_rephrase(self, selection: str, instruction: str):
        import time
        import pyperclip
        from .text_postprocess import _ollama_polish
        from .platform import keyboard as kb

        print(f"\n   🤖 Rephrasing ({len(selection)} chars) with instruction: '{instruction[:60]}'")

        full_prompt = (
            f"{instruction}\n\n"
            "Output ONLY the rewritten text with no preamble, no quotes, no commentary.\n\n"
            f"Input:\n{selection}"
        )
        ollama_cfg = dict(self.config_manager.get_postprocess_config().get('ollama') or {})
        ollama_cfg['enabled'] = True
        ollama_cfg['prompt'] = '{text}'

        polished = _ollama_polish(full_prompt, ollama_cfg)
        if not polished:
            print("   ✗ Rephrase failed — Ollama unreachable or returned nothing")
            self.system_tray.notify("Rephrase failed — is Ollama running?")
            if self.level_overlay:
                self.level_overlay.flash_failure()
            return

        try:
            pyperclip.copy(polished)
            time.sleep(0.05)
            kb.send_hotkey('ctrl', 'v')
            time.sleep(0.2)
        finally:
            try:
                if self._rephrase_original_clipboard:
                    pyperclip.copy(self._rephrase_original_clipboard)
            except Exception:
                pass

        self.last_transcription = polished
        self.recent_transcriptions.appendleft(polished)
        self.system_tray.refresh_menu()
        self.system_tray.notify("Rephrased and pasted")
        if self.level_overlay:
            self.level_overlay.flash_success()
        self.logger.info(f"Rephrase complete: {len(selection)} -> {len(polished)} chars")
        print("   ✓ Rephrased and pasted")

    NON_TEXT_EXES = {'progman.exe', 'workerw.exe', 'dwm.exe', 'searchhost.exe',
                     'shellexperiencehost.exe', 'startmenuexperiencehost.exe',
                     'lockapp.exe', 'sihost.exe'}

    def _foreground_is_textable(self) -> bool:
        try:
            info = foreground.get_foreground_app() or {}
        except Exception:
            return True
        exe = (info.get('exe') or '').lower()
        if not exe:
            return False
        return exe not in self.NON_TEXT_EXES


    def set_overlay_position(self, name: str) -> bool:
        if not self.level_overlay:
            return False
        self.level_overlay.set_position(name)
        self.config_manager.update_user_setting('overlay', 'position', name)
        self.logger.info(f"Overlay position set to {name}")
        return True

    def get_overlay_position(self) -> str:
        return self.config_manager.config.get('overlay', {}).get('position', 'bottom-center')

    def get_current_language(self) -> str:
        return self.config_manager.config.get('whisper', {}).get('language', 'auto')

    def set_language(self, code: str) -> bool:
        current = self.get_current_language()
        if current == code:
            return False
        self.config_manager.update_user_setting('whisper', 'language', code)
        try:
            self.whisper_engine.language = None if code == 'auto' else code
        except Exception:
            pass
        self.logger.info(f"Language switched: {current} -> {code}")
        print(f"   ✓ Language set to: {code}")
        self.system_tray.notify(f"Language: {code}")
        self.system_tray.refresh_menu()
        return True

    def apply_transform(self, name: str) -> bool:
        success = self.transforms_manager.apply(name)
        if self.level_overlay:
            if success:
                self.level_overlay.flash_success()
            else:
                self.level_overlay.flash_failure()
        return success

    def list_transforms(self) -> list:
        return self.transforms_manager.list_transforms()

    def reload_transforms(self) -> bool:
        old = [(t.get('name'), t.get('hotkey')) for t in self.transforms_manager.list_transforms()]
        self.transforms_manager.reload_if_changed()
        new = [(t.get('name'), t.get('hotkey')) for t in self.transforms_manager.list_transforms()]
        changed = old != new
        if changed:
            self.system_tray.notify(f"Transforms reloaded ({len(new)} active)")
            self.system_tray.refresh_menu()
            if self._hotkey_listener_ref:
                self._hotkey_listener_ref.refresh_transforms()
        return changed

    def set_hotkey_listener(self, listener):
        self._hotkey_listener_ref = listener

    def list_profiles(self) -> list:
        return self.profile_manager.list_profiles()

    def get_active_profile(self) -> Optional[str]:
        return self.profile_manager.get_active()

    def activate_profile(self, name: str) -> bool:
        old_whisper = dict(self.config_manager.get_whisper_config())

        if not self.profile_manager.apply(name):
            return False

        new_whisper = self.config_manager.get_whisper_config()

        if new_whisper.get('language') != old_whisper.get('language'):
            lang = new_whisper.get('language', 'auto')
            try:
                self.whisper_engine.language = None if lang == 'auto' else lang
            except Exception:
                pass

        if new_whisper.get('task') != old_whisper.get('task'):
            task = new_whisper.get('task') or 'transcribe'
            try:
                self.whisper_engine.task = task if task in ('transcribe', 'translate') else 'transcribe'
            except Exception:
                pass

        new_prompt = new_whisper.get('initial_prompt') or ''
        if new_prompt != (old_whisper.get('initial_prompt') or ''):
            try:
                self.whisper_engine.initial_prompt = new_prompt or None
            except Exception:
                pass

        if new_whisper.get('model') and new_whisper.get('model') != old_whisper.get('model'):
            try:
                self._execute_model_change(new_whisper['model'])
            except Exception as e:
                self.logger.error(f"Profile model change failed: {e}")

        self.logger.info(f"Activated profile: {name}")
        print(f"   ✓ Profile activated: {name}")
        self.system_tray.notify(f"Profile: {name}")
        self.system_tray.refresh_menu()
        return True

    def get_recent_transcriptions(self) -> list:
        return list(self.recent_transcriptions)

    # Types the last dictation again at the cursor (paste-last hotkey), e.g.
    # after it went to the wrong window. Never auto-sends, and the foreground
    # app's rule still applies: nothing goes into a suppressed app (password
    # managers), and copy-only apps (terminals, where a pasted newline runs a
    # command) get the clipboard instead.
    def paste_last_transcription(self) -> bool:
        text = self.last_transcription
        if not text:
            self.system_tray.notify("Nothing to paste yet — dictate something first.")
            return False
        if self.get_current_state() != "idle":
            self.logger.info("Paste-last ignored: busy recording or transcribing")
            return False
        self._wait_for_modifiers_released()
        rule = None
        try:
            rule = self.app_rules.match_for_foreground()
        except Exception as e:
            self.logger.debug(f"Paste-last rule lookup failed: {e}")
        try:
            if rule and rule.get('suppress'):
                self.logger.info(f"Paste-last suppressed by app rule: {rule.get('match')}")
                self.system_tray.notify("Not pasted: this app is excluded in app_rules.yaml.")
                return False
            if rule and rule.get('auto_paste') is False:
                self.clipboard_manager.copy_text(text)
                self.system_tray.notify("Last dictation copied — this app is copy-only.")
                return True
            self.clipboard_manager.deliver_transcription(text, use_auto_enter=False)
        except Exception as e:
            self.logger.error(f"Paste-last failed: {e}")
            self.system_tray.notify("Couldn't paste the last dictation.")
            return False
        return True

    # A hotkey's release event can arrive while its other modifiers are still
    # down, and those would merge into the paste. Wait briefly for the user to
    # let go; after the timeout, deliver anyway rather than drop the request.
    def _wait_for_modifiers_released(self, timeout: float = 1.5):
        import time
        try:
            from .platform import keyboard as kb
            modifiers_held = kb.modifiers_held
        except (ImportError, AttributeError):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if not modifiers_held():
                    return
            except Exception:
                return
            time.sleep(0.02)

    def recopy_recent_transcription(self, index: int):
        if 0 <= index < len(self.recent_transcriptions):
            text = self.recent_transcriptions[index]
            self.clipboard_manager.copy_text(text)
            print(f"   ✓ Re-copied: {text[:60]}{'...' if len(text) > 60 else ''}")

    def get_available_audio_devices(self, host_filter: Optional[str] = None):
        host_name = host_filter if host_filter is not None else self._current_audio_host
        return AudioRecorder.get_available_audio_devices(host_name)

    def get_current_audio_device_id(self):
        return self.audio_recorder.get_device_id()

    def get_available_audio_hosts(self):
        try:
            hostapis = sd.query_hostapis()
            devices = sd.query_devices()
        except Exception as e:
            self.logger.error(f"Failed to query audio hosts: {e}")
            return []

        hosts_with_input = {}
        for index, host in enumerate(hostapis):
            hosts_with_input[index] = {
                'name': host['name'],
                'index': index,
                'has_input': False
            }

        for device in devices:
            if device.get('max_input_channels', 0) > 0:
                host_index = device['hostapi']
                if host_index in hosts_with_input:
                    hosts_with_input[host_index]['has_input'] = True

        return [
            {'name': host['name'], 'index': host['index']}
            for host in hosts_with_input.values()
            if host['has_input']
        ]

    def get_current_audio_host(self) -> Optional[str]:
        return self._current_audio_host

    def set_audio_host(self, host_name: str) -> bool:
        if not host_name:
            return False

        available_hosts = self.get_available_audio_hosts()
        normalized_lookup = {host['name'].lower(): host for host in available_hosts}
        host_entry = normalized_lookup.get(host_name.lower())

        if not host_entry:
            self.logger.warning(f"Requested audio host '{host_name}' is not available")
            return False

        canonical_name = host_entry['name']
        if canonical_name == self._current_audio_host:
            return True

        self._current_audio_host = canonical_name
        self.config_manager.update_audio_host(canonical_name)
        self.logger.info(f"Audio host changed to {canonical_name}")

        self._ensure_audio_device_for_host(canonical_name)
        self.system_tray.refresh_menu()
        return True

    def request_audio_device_change(self, device_id: int, device_name: str):
        current_state = self.get_current_state()

        if device_id == self.audio_recorder.device:
            return True

        if current_state == "recording":
            print("🎤 Cancelling recording to switch audio device...")
            self.cancel_active_recording()
            self._execute_audio_device_change(device_id, device_name)
            return True

        if current_state == "processing":
            print("⏳ Queueing audio device change until transcription completes...")
            self._pending_device_change = (device_id, device_name)
            return True

        if current_state == "idle":
            self._execute_audio_device_change(device_id, device_name)
            return True

        self.logger.warning(f"Unexpected state for device change: {current_state}")
        return False

    def _execute_audio_device_change(self, device_id: int, device_name: str):
        try:
            print(f"🎤 Switching to: {device_name}")

            channels = self.audio_recorder.channels
            dtype = self.audio_recorder.dtype
            max_duration = self.audio_recorder.max_duration
            on_max_duration = self.audio_recorder.on_max_duration_reached
            vad_manager = self.audio_recorder.vad_manager
            streaming_manager = self.audio_recorder.streaming_manager
            on_streaming_result = self.audio_recorder.on_streaming_result

            audio_cfg = self.config_manager.config.get('audio') or {}
            noise_cfg = audio_cfg.get('noise_suppression') or {}
            new_recorder = AudioRecorder(
                on_vad_event=self.handle_vad_event,
                channels=channels,
                dtype=dtype,
                max_duration=max_duration,
                on_max_duration_reached=on_max_duration,
                vad_manager=vad_manager,
                streaming_manager=streaming_manager,
                on_streaming_result=on_streaming_result,
                device=device_id if device_id != -1 else None,
                noise_suppression_config=noise_cfg,
                whisper_mode_config=audio_cfg.get('whisper_mode') or {},
            )

            self.audio_recorder = new_recorder

            print(f"✅ Successfully switched audio device to: {device_name}")

        except Exception as e:
            self.logger.error(f"Failed to change audio device: {e}")
            print(f"❌ Failed to switch audio device: {e}")

    def _initialize_audio_host(self):
        try:
            configured_host = self.config_manager.get_setting('audio', 'host')
        except KeyError:
            configured_host = None

        available_hosts = self.get_available_audio_hosts()
        resolved_host = self._resolve_audio_host(configured_host, available_hosts)

        self._current_audio_host = resolved_host

        if resolved_host != configured_host:
            self.config_manager.update_audio_host(resolved_host)

    def _resolve_audio_host(self, configured_host: Optional[str], available_hosts):
        if not available_hosts:
            return None

        if configured_host:
            match = self._match_host(configured_host, available_hosts)
            if match:
                return match

        preferred_host = self._preferred_platform_host()
        if preferred_host:
            preferred_match = self._match_host(preferred_host, available_hosts)
            if preferred_match:
                return preferred_match

        return available_hosts[0]['name']

    def _match_host(self, requested: str, available_hosts) -> Optional[str]:
        requested_lower = requested.lower().strip()
        for host in available_hosts:
            if host['name'].lower() == requested_lower:
                return host['name']
        for host in available_hosts:
            if requested_lower in host['name'].lower():
                return host['name']
        return None

    def _preferred_platform_host(self) -> Optional[str]:
        system_name = platform.system().lower()
        if system_name == 'windows':
            return 'WASAPI'
        return None

    def _ensure_audio_device_for_host(self, host_name: Optional[str]):
        if not host_name or not self.audio_recorder:
            return

        try:
            current_device_id = self.audio_recorder.get_device_id()
        except Exception as e:
            self.logger.error(f"Unable to read current audio device: {e}")
            return

        if self._device_matches_host(current_device_id, host_name):
            return

        fallback_device_id = self._get_default_device_for_host(host_name)
        if fallback_device_id is None:
            self.logger.warning(f"No input devices available for host {host_name}")
            return

        device_name = self._get_device_name(fallback_device_id)
        success = self.request_audio_device_change(fallback_device_id, device_name)

        if not success:
            self.logger.warning(f"Failed to switch to fallback device {fallback_device_id} for host {host_name}")

    def _device_matches_host(self, device_id: int, host_name: str) -> bool:
        try:
            device_info = sd.query_devices(device_id)
            host_info = sd.query_hostapis(device_info['hostapi'])
            return host_info['name'].lower() == host_name.lower()
        except Exception:
            return False

    def _get_default_device_for_host(self, host_name: str) -> Optional[int]:
        try:
            target_index = None
            target_host = None
            hostapis = sd.query_hostapis()
            for idx, host in enumerate(hostapis):
                if host['name'].lower() == host_name.lower():
                    target_index = idx
                    target_host = host
                    break
            else:
                return None

            default_input = target_host.get('default_input_device', -1)
            if default_input is not None and default_input >= 0:
                device_info = sd.query_devices(default_input)
                if device_info.get('max_input_channels', 0) > 0:
                    return default_input

            all_devices = sd.query_devices()
            for idx, device in enumerate(all_devices):
                if device['hostapi'] == target_index and device.get('max_input_channels', 0) > 0:
                    return idx
        except Exception as e:
            self.logger.error(f"Failed to determine default device for host {host_name}: {e}")

        return None

    def _get_device_name(self, device_id: int) -> str:
        try:
            device_info = sd.query_devices(device_id)
            return device_info.get('name', f"Device {device_id}")
        except Exception:
            return f"Device {device_id}"
