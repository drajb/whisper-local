# audio_gain.py
# "Whisper mode": lifts quiet recordings (whispering, a distant mic) to a level
# Whisper transcribes reliably. It only ever raises the volume, by at most a
# capped factor, so normal speech is untouched and the noise floor of a silent
# clip isn't blown up into hallucination bait. Pure numpy, no extra deps.

import numpy as np

# Level the loudest speech is brought up to, in full-scale units. Kept below
# 1.0 so the boost can never clip.
TARGET_PEAK = 0.6

# Below this the clip is silence (or a muted mic), not quiet speech. Boosting
# it would only amplify hiss, which Whisper tends to "transcribe".
SILENCE_PEAK = 1e-3


# Returns the audio scaled so its loud parts reach TARGET_PEAK, never by more
# than max_gain and never downward. The 99.9th percentile stands in for the
# peak so a single click or pop can't cap the gain for the whole recording.
def boost_quiet_audio(audio: np.ndarray, max_gain: float = 8.0) -> np.ndarray:
    if audio is None or audio.size == 0:
        return audio
    peak = float(np.percentile(np.abs(audio), 99.9))
    if peak < SILENCE_PEAK:
        return audio
    gain = min(float(max_gain), TARGET_PEAK / peak)
    if gain <= 1.0:
        return audio
    return np.clip(audio * gain, -1.0, 1.0).astype(audio.dtype, copy=False)
