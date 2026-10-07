import platform as _platform

# Resolve the platform once at import time. Whisper Local officially supports
# Windows and macOS; Linux is "best-effort import only" so smoke tests and the
# release toolchain on Linux CI can load most modules without exploding.
_system = _platform.system()
if _system == 'Darwin':
    PLATFORM = 'macos'
elif _system == 'Windows':
    PLATFORM = 'windows'
else:
    PLATFORM = 'unsupported'

IS_MACOS = PLATFORM == 'macos'
IS_WINDOWS = PLATFORM == 'windows'

# Only pull in the platform-specific implementation on a supported OS. On Linux
# we leave the submodule namespace empty — any code that actually USES platform
# functionality at runtime will get an AttributeError, which surfaces as a clear
# "unsupported platform" failure where it matters, rather than blowing up
# at module import on every developer's CI box.
if IS_MACOS:
    from .macos import instance_lock, keyboard, hotkeys, paths, app, permissions, icons, gpu, console, foreground, audio_endpoints
elif IS_WINDOWS:
    from .windows import instance_lock, keyboard, hotkeys, paths, app, permissions, icons, gpu, console, foreground, audio_endpoints
