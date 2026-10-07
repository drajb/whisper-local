# platform/macos/audio_endpoints.py
# Mirror of platform/windows/audio_endpoints.py. Not implemented on macOS yet:
# returning None leaves the default-input watcher idle, so behaviour there is
# unchanged.
from typing import Optional


def get_default_input_id() -> Optional[str]:
    return None
