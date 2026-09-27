# whisper_engine.py
# The default speech-recognition backend, wrapping faster-whisper (CTranslate2).
# Loads the model once at startup and warms it with a dummy transcription so the
# user's first real recording isn't slowed by lazy initialisation. Model switches
# happen on a background thread with progress callbacks so the UI stays live.
# `whisper_engine_cpp.py` mirrors this class's API for the opt-in whisper.cpp
# backend — keep the two signatures in sync.

import logging
import time
import threading
from typing import Optional, Callable

import numpy as np
from faster_whisper import WhisperModel

# Approximate on-disk download sizes for the standard Whisper models, shown in
# the first-run download message so the wait is expected, not mysterious. Keyed
# by the leading size token (handles ".en" and "large-v3" style keys). Unknown
# models just omit the size hint.
_MODEL_SIZE_HINTS = {
    'tiny': '~75 MB',
    'base': '~141 MB',
    'small': '~465 MB',
    'medium': '~1.5 GB',
    'large': '~3 GB',
    'distil': '~1.5 GB',
}


def _model_size_hint(model_key: str) -> str:
    key = (model_key or '').lower()
    for prefix, size in _MODEL_SIZE_HINTS.items():
        if key.startswith(prefix):
            return size
    return ''


class WhisperEngine:
    def __init__(self,
                 model_key: str = "tiny",
                 device: str = "cpu",
                 compute_type: str = "int8",
                 language: str = None,
                 beam_size: int = 5,
                 initial_prompt: str = "",
                 hotwords: list = None,
                 task: str = "transcribe",
                 vad_manager = None,
                 model_registry = None,
                 log_transcriptions: bool = False):

        self.model_key = model_key
        self.device = device
        self.compute_type = compute_type
        self.language = None if language == 'auto' else language
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None
        self.hotwords = ", ".join(hotwords) if hotwords else None
        self.task = task if task in ('transcribe', 'translate') else 'transcribe'
        self.model = None
        self.logger = logging.getLogger(__name__)
        self.registry = model_registry
        self.log_transcriptions = log_transcriptions

        self._loading_thread = None
        self._progress_callback = None

        self.vad_manager = vad_manager

        self._load_model()
    
    def _get_model_source(self, model_key: str) -> str:
        if self.registry:
            return self.registry.get_source(model_key)
        return model_key

    def _is_model_cached(self, model_key: str = None) -> bool:
        if model_key is None:
            model_key = self.model_key
        if self.registry:
            return self.registry.is_model_cached(model_key)
        return False

    def _load_model(self):
        try:
            print(f"🧠 Loading Whisper AI model [{self.model_key}]...")

            was_cached = self._is_model_cached()
            if not was_cached:
                size = _model_size_hint(self.model_key)
                size_note = f" ({size})" if size else ""
                print(f"⬇  Downloading the '{self.model_key}' model{size_note} — "
                      "first run only. This can take a few minutes; a progress bar "
                      "appears below.")

            if self.device == 'cuda':
                self._verify_gpu_runtime()

            model_source = self._get_model_source(self.model_key)
            self.model = WhisperModel(
                model_source,
                device=self.device,
                compute_type=self.compute_type
            )

            if not was_cached:
                print("\n")  # Workaround for download status bar misplacement

            print(f"   ✓ Whisper model [{self.model_key}] ready!")
            device_label = "GPU" if self.device == "cuda" else "CPU"
            print(f"   ✓ Running on {device_label} with {self.compute_type} precision")
            self._warmup()

        except Exception as e:
            self.logger.error(f"Failed to load Whisper model: {e}")
            raise

    # Fail fast when the CUDA runtime is incomplete. The model itself loads
    # without cuBLAS/cuDNN; their absence only shows on the first inference,
    # as a hang rather than an error (issue #15). Raising RuntimeError here
    # routes through the caller's GPU-failure path, which offers GPU setup or
    # CPU instead of freezing on the user's first dictation.
    def _verify_gpu_runtime(self):
        try:
            from .hardware_detection import missing_gpu_libraries
        except ImportError:
            return  # no platform backend (Linux CI): nothing to probe
        missing = missing_gpu_libraries()
        if missing:
            raise RuntimeError(
                f"CUDA libraries not found: {', '.join(missing)}. "
                "Re-run GPU setup to install them, or switch to CPU."
            )

    def _load_model_async(self,
                          new_model_key: str,
                          progress_callback: Optional[Callable[[str], None]] = None):
        def _background_loader():
            # Capture before any callback so the except handler can always restore
            # it (a progress_callback that raises must not cause UnboundLocalError).
            old_model_key = self.model_key
            try:
                if progress_callback:
                    progress_callback("Checking model cache...")

                was_cached = self._is_model_cached(new_model_key)

                if progress_callback:
                    if was_cached:
                        progress_callback("Loading cached model...")
                    else:
                        progress_callback("Downloading model...")

                self.logger.info(f"Loading Whisper model: {new_model_key} (async)")

                model_source = self._get_model_source(new_model_key)
                new_model = WhisperModel(
                    model_source,
                    device=self.device,
                    compute_type=self.compute_type
                )
                self.model = new_model

                self.model_key = new_model_key
                self.logger.info(f"Whisper model [{new_model_key}] loaded successfully (async)")

                if progress_callback:
                    progress_callback("Model ready!")

            except Exception as e:
                self.model_key = old_model_key
                self.logger.error(f"Failed to load Whisper model async: {e}")
                if progress_callback:
                    progress_callback(f"Failed to load model: {e}")
                raise
            finally:
                self._loading_thread = None
                self._progress_callback = None

        if self._loading_thread and self._loading_thread.is_alive():
            self.logger.warning("Model loading already in progress, ignoring new request")
            return
        
        self._progress_callback = progress_callback
        self._loading_thread = threading.Thread(target=_background_loader, daemon=True)
        self._loading_thread.start()
    
    def is_loading(self) -> bool:
        return self._loading_thread is not None and self._loading_thread.is_alive()
    

    def _warmup(self):
        try:
            silent = np.zeros(16000, dtype=np.float32)
            t0 = time.time()
            segments, _ = self.model.transcribe(
                silent, language=self.language, beam_size=1, vad_filter=False
            )
            for _ in segments:
                pass
            self.logger.info(f"Whisper warmup completed in {time.time() - t0:.2f}s")
        except Exception as e:
            self.logger.debug(f"Whisper warmup skipped: {e}")

    # Mono float32 @ 16 kHz in, plain text out (None/'' when there's no speech).
    # An optional VAD pre-check short-circuits silent clips so we don't pay for a
    # full decode on an accidental hotkey press. Callers rely on this contract —
    # whisper_engine_cpp and system_audio both feed it the same array shape.
    def transcribe_audio(self,
                         audio_data: np.ndarray) -> Optional[str]:
        if self.model is None:
            return None
        
        if audio_data is None or len(audio_data) == 0:
            self.logger.warning("No audio data to transcribe")
            return None
        
        try:
            speech_detected = True
            if self.vad_manager and self.vad_manager.is_available():
                speech_detected = self.vad_manager.check_audio_for_speech(audio_data)
            
            if not speech_detected:
                print("   ✗ No speech detected, skipping transcription")
                return None
                       
            start_time = time.time() # Time transcription for user feedback
            
            # Prep audio for faster-whisper
            if len(audio_data.shape) > 1:
                audio_data = audio_data.flatten()
            
            audio_data = audio_data.astype(np.float32)
            
            transcribe_kwargs = dict(
                beam_size=self.beam_size,
                language=self.language,
                task=self.task,
                condition_on_previous_text=False,
            )
            if self.initial_prompt:
                transcribe_kwargs["initial_prompt"] = self.initial_prompt
            if self.hotwords:
                transcribe_kwargs["hotwords"] = self.hotwords

            segments, info = self.model.transcribe(audio_data, **transcribe_kwargs)
            
            transcribed_text = ""
            for segment in segments:
                transcribed_text += segment.text
            
            transcribed_text = transcribed_text.strip()
            
            end_time = time.time()
            transcription_time = end_time - start_time
            print(f"   ✓ Transcription completed in {transcription_time:.1f} seconds")
            
            # Log some info about what we transcribed
            detected_language = info.language
            confidence = info.language_probability
            self.logger.info(f"Transcription complete. Language: {detected_language} (confidence: {confidence:.2f}) - Time: {transcription_time:.2f}s")
            if self.log_transcriptions:
                self.logger.info(f"Transcribed text: '{transcribed_text}'")
            else:
                self.logger.info(f"Transcribed {len(transcribed_text)} chars")
            
            if transcribed_text:
                print(f"   ✓ Transcribed: '{transcribed_text}'")
                return transcribed_text
            else:
                self.logger.info("Transcription was empty")
                return None
                
        except Exception as e:
            self.logger.error(f"Transcription failed: {e}")
            return None
    
    
    def change_model(self,
                     new_model_key: str,
                     progress_callback: Optional[Callable[[str], None]] = None):
        
        if new_model_key == self.model_key:
            if progress_callback:
                progress_callback("Model already loaded")
            return
        
        self._load_model_async(new_model_key, progress_callback)
    