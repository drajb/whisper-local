# platform/windows/audio_endpoints.py
# Reads the ID of Windows' current default microphone straight from Core Audio.
# PortAudio enumerates devices only once at init, so this is how we notice a
# dock/headset switch or a wake-up at a desk with different hardware.
# macOS mirror: platform/macos/audio_endpoints.py.
import ctypes
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_ole32 = ctypes.windll.ole32
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.c_void_p, ctypes.c_void_p]
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None

CLSCTX_ALL = 0x17
COINIT_MULTITHREADED = 0x0
E_CAPTURE = 1       # EDataFlow.eCapture
E_MULTIMEDIA = 1    # ERole.eMultimedia, the role PortAudio's WASAPI backend reads

# Vtable slots (IUnknown takes 0-2)
_RELEASE = 2
_ENUMERATOR_GET_DEFAULT_AUDIO_ENDPOINT = 4
_DEVICE_GET_ID = 5


def _guid(text: str):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


_CLSID_MM_DEVICE_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_IMM_DEVICE_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")


# Binds vtable slot `index` of a COM object so it can be called like a function.
def _method(com_object, index, *argtypes):
    vtable = ctypes.cast(com_object, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])


def _release(com_object):
    _method(com_object, _RELEASE)(com_object)


# Endpoint ID string of the default microphone, or None when there is no
# microphone at all or Core Audio is unreachable.
def get_default_input_id() -> Optional[str]:
    com_init = _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    enumerator = ctypes.c_void_p()
    device = ctypes.c_void_p()
    try:
        hr = _ole32.CoCreateInstance(ctypes.byref(_CLSID_MM_DEVICE_ENUMERATOR), None, CLSCTX_ALL,
                                     ctypes.byref(_IID_IMM_DEVICE_ENUMERATOR), ctypes.byref(enumerator))
        if hr < 0:
            return None

        get_default = _method(enumerator, _ENUMERATOR_GET_DEFAULT_AUDIO_ENDPOINT,
                              ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        if get_default(enumerator, E_CAPTURE, E_MULTIMEDIA, ctypes.byref(device)) < 0:
            return None  # E_NOTFOUND: no microphone connected

        id_buffer = ctypes.c_void_p()
        get_id = _method(device, _DEVICE_GET_ID, ctypes.POINTER(ctypes.c_void_p))
        if get_id(device, ctypes.byref(id_buffer)) < 0:
            return None
        try:
            return ctypes.wstring_at(id_buffer.value)
        finally:
            _ole32.CoTaskMemFree(id_buffer)
    except Exception as e:
        logger.debug(f"Could not read default input endpoint: {e}")
        return None
    finally:
        if device.value:
            _release(device)
        if enumerator.value:
            _release(enumerator)
        # S_OK / S_FALSE must be balanced; RPC_E_CHANGED_MODE (thread already
        # initialised as STA) must not be.
        if com_init >= 0:
            _ole32.CoUninitialize()
