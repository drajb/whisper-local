# platform/windows/gpu.py
# Windows GPU probe: identifies NVIDIA/AMD hardware and, crucially, verifies that
# CTranslate2 can actually load its CUDA/cuBLAS DLLs — a card being present is
# not the same as the runtime working. It parses the PE import table to report
# exactly which DLL is missing, turning an opaque crash into an actionable
# message. macOS mirror: platform/macos/gpu.py (a no-op stub).
import ctypes
import glob
import importlib.metadata
import importlib.util
import logging
import os
import pathlib
import re
import site
import subprocess

logger = logging.getLogger(__name__)

_NO_WINDOW = {'creationflags': 0x08000000}

_GPU_REQUIREMENTS = {
    'nvidia': {'runtime_name': 'CUDA', 'runtime_version': (12,), 'ct2_variant': 'cuda'},
    'amd_rdna2+': {'runtime_name': 'HIP', 'runtime_version': (7, 2), 'ct2_variant': 'rocm'},
    'amd_rdna1': {'runtime_name': 'HIP', 'runtime_version': (6, 2), 'ct2_variant': 'rocm', 'ct2_custom': True},
}


def detect_and_print(configured_device):
    gpu_vendor, gpu_name = _detect_gpu()
    if not gpu_name:
        return (None, None, False)

    _status("🖥️ System check...")
    _status(f"   ✓ Detected {gpu_name}")

    gpu_class = _classify_gpu(gpu_vendor, gpu_name)
    reqs = _GPU_REQUIREMENTS.get(gpu_class)

    runtime_version = None
    if gpu_vendor == 'nvidia':
        runtime_version = _find_cuda_runtime()
        if runtime_version:
            _status(f"   ✓ NVIDIA CUDA {runtime_version} runtime available")
        else:
            _status("   ✗ NVIDIA CUDA runtime not found", 'warning')
    elif gpu_vendor == 'amd':
        runtime_version = _find_rocm_runtime()
        if runtime_version:
            _status(f"   ✓ AMD HIP {runtime_version} runtime available")
        else:
            _status("   ✗ AMD HIP runtime not found", 'warning')

    ct2_variant = _detect_ct2_variant()
    ct2_version, ct2_is_custom = _detect_ct2_version()
    if ct2_variant != 'not_installed':
        variant_label = {'cuda': 'CUDA', 'rocm': 'ROCm'}.get(ct2_variant, ct2_variant)
        _status(f"   ✓ CTranslate2 {ct2_version} ({variant_label})")
    else:
        _status("   ✗ CTranslate2 not installed", 'warning')

    if ct2_variant == 'not_installed' or not reqs:
        return (gpu_class, gpu_name, False)

    if ct2_variant != reqs['ct2_variant']:
        expected = 'ROCm' if reqs['ct2_variant'] == 'rocm' else 'CUDA'
        actual = 'ROCm' if ct2_variant == 'rocm' else 'CUDA'
        _status(f"   ✗ GPU requires {expected} CTranslate2, found {actual}", 'warning')
    elif reqs.get('ct2_custom') and not ct2_is_custom:
        _status(f"   ✗ {gpu_name} requires custom CTranslate2 wheel", 'warning')

    if not runtime_version:
        _status(f"   ✗ {reqs['runtime_name']} runtime required for GPU acceleration", 'warning')
    else:
        _check_runtime_compatibility(reqs, runtime_version)

    ct2_works = _test_ct2_gpu(ct2_variant)
    if ct2_works:
        _status("   ✓ GPU acceleration available")
    else:
        _status("   ✗ GPU acceleration test failed", 'warning')

    return (gpu_class, gpu_name, ct2_works)


def _status(msg, level='info'):
    # Always DEBUG — level param reserved for future use (avoid console spam during testing)
    print(msg)
    logger.log(logging.DEBUG, msg.strip())


# Map a GPU name to the class that decides which runtime we need.
#
# The AMD matching is fussier than it looks. Requiring FOUR digits is deliberate:
# a 3-digit part like "RX 580" is Polaris (GCN), not RDNA, and a loose one-digit
# match classified it as RDNA1 and offered a runtime that cannot drive it. \s*
# rather than \s+ because vendor strings are inconsistent ("RX5700" appears
# without a space). Strix Halo / Ryzen AI MAX APUs (8040S/8050S/8060S) report no
# "RX" at all, so they need their own pattern or GPU onboarding never fires for
# them. Anything unrecognised returns None and we simply stay on CPU.
def _classify_gpu(gpu_vendor: str, gpu_name: str) -> str | None:
    if gpu_vendor == 'nvidia':
        return 'nvidia'
    if gpu_vendor == 'amd':
        name = gpu_name.upper()
        match = re.search(r'RX\s*(\d{4})', name)
        if match:
            series = int(match.group(1)) // 1000
            if series == 5:
                return 'amd_rdna1'
            if series in (6, 7, 9):
                return 'amd_rdna2+'
            return None
        if re.search(r'\b80[0-9]0S\b', name):
            return 'amd_rdna2+'
    return None


def _detect_gpu() -> tuple[str | None, str | None]:
    nvidia = _detect_nvidia_gpu()
    if nvidia:
        return 'nvidia', nvidia

    amd = _detect_amd_gpu()
    if amd:
        return 'amd', amd

    return None, None


def _detect_nvidia_gpu() -> str | None:
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5, **_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _detect_amd_gpu() -> str | None:
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command',
             "(Get-CimInstance Win32_VideoController"
             " | Where-Object {$_.Name -match 'AMD|Radeon'}).Name"],
            capture_output=True, text=True, timeout=5, **_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _find_cuda_runtime() -> str | None:
    search_dirs = []

    cuda_path = os.environ.get('CUDA_PATH')
    if cuda_path:
        search_dirs.append(os.path.join(cuda_path, 'bin'))

    for sp in site.getsitepackages():
        search_dirs.append(os.path.join(sp, 'nvidia', 'cuda_runtime', 'bin'))

    search_dirs.extend(os.environ.get('PATH', '').split(os.pathsep))

    for search_dir in search_dirs:
        if not search_dir or not os.path.isdir(search_dir):
            continue
        for dll_path in glob.glob(os.path.join(search_dir, 'cudart64_*.dll')):
            version = _get_cuda_version_from_dll(dll_path)
            if version:
                return version

    return None


def _get_cuda_version_from_dll(dll_path: str) -> str | None:
    try:
        cudart = ctypes.CDLL(dll_path)
        cudart.cudaRuntimeGetVersion.restype = ctypes.c_int
        cudart.cudaRuntimeGetVersion.argtypes = [ctypes.POINTER(ctypes.c_int)]
        version = ctypes.c_int(0)
        if cudart.cudaRuntimeGetVersion(ctypes.byref(version)) == 0:
            v = version.value
            major = v // 1000
            minor = (v % 1000) // 10
            return f"{major}.{minor}"
    except OSError:
        pass
    return None


def _find_rocm_runtime() -> str | None:
    search_dirs = []

    for var in ('HIP_PATH', 'HIP_DIR'):
        hip_path = os.environ.get(var)
        if hip_path:
            search_dirs.append(os.path.join(hip_path, 'bin'))

    spec = importlib.util.find_spec('_rocm_sdk_core')
    if spec and spec.submodule_search_locations:
        search_dirs.append(os.path.join(spec.submodule_search_locations[0], 'bin'))

    system32 = r'C:\Windows\System32'
    if os.path.isdir(system32):
        search_dirs.append(system32)
    search_dirs.extend(os.environ.get('PATH', '').split(os.pathsep))

    for search_dir in search_dirs:
        if not search_dir or not os.path.isdir(search_dir):
            continue
        for dll_path in glob.glob(os.path.join(search_dir, 'amdhip64_*.dll')):
            version = _get_hip_version_from_dll(dll_path)
            if version:
                return version

    return None


def _get_hip_version_from_dll(dll_path: str) -> str | None:
    try:
        hip = ctypes.CDLL(dll_path)
        hip.hipRuntimeGetVersion.restype = ctypes.c_int
        hip.hipRuntimeGetVersion.argtypes = [ctypes.POINTER(ctypes.c_int)]
        version = ctypes.c_int(0)
        if hip.hipRuntimeGetVersion(ctypes.byref(version)) == 0:
            v = version.value
            major = v // 10_000_000
            minor = (v % 10_000_000) // 100_000
            return f"{major}.{minor}"
    except OSError:
        pass
    return None


def _read_pe_imports(dll_path: pathlib.Path) -> list[str]:
    try:
        return _parse_pe_imports(dll_path)
    except Exception:
        return []


# Reads a DLL's import table straight from the PE headers to learn which other
# DLLs it needs. We do this by hand — rather than just trying to load the library
# — so that when CTranslate2's CUDA support fails we can name the exact missing
# dependency (e.g. cublas64_12.dll) instead of surfacing a generic load error.
# Walks: DOS header e_lfanew (0x3C) → PE signature → optional header → import
# directory RVA → section table to map that RVA to a file offset.
def _parse_pe_imports(dll_path: pathlib.Path) -> list[str]:
    with open(dll_path, 'rb') as f:
        f.seek(0x3C)
        pe_offset = int.from_bytes(f.read(4), 'little')

        f.seek(pe_offset + 4)
        f.read(2)
        num_sections = int.from_bytes(f.read(2), 'little')
        f.read(12)
        optional_header_size = int.from_bytes(f.read(2), 'little')
        f.read(2)

        opt_start = f.tell()
        magic = int.from_bytes(f.read(2), 'little')
        is_pe32_plus = magic == 0x20B

        data_dir_offset = opt_start + (112 if is_pe32_plus else 96)
        f.seek(data_dir_offset + 8)
        import_rva = int.from_bytes(f.read(4), 'little')
        if import_rva == 0:
            return []

        sections_offset = opt_start + optional_header_size
        sections = []
        for i in range(num_sections):
            f.seek(sections_offset + i * 40)
            f.read(8)
            virtual_size = int.from_bytes(f.read(4), 'little')
            virtual_addr = int.from_bytes(f.read(4), 'little')
            raw_size = int.from_bytes(f.read(4), 'little')
            raw_offset = int.from_bytes(f.read(4), 'little')
            sections.append((virtual_addr, virtual_size, raw_offset, raw_size))

        def rva_to_offset(rva):
            for va, vs, ro, rs in sections:
                if va <= rva < va + vs:
                    return ro + (rva - va)
            return None

        entry_offset = rva_to_offset(import_rva)
        if entry_offset is None:
            return []

        imports = []
        while True:
            f.seek(entry_offset)
            entry = f.read(20)
            if len(entry) < 20:
                break
            name_rva = int.from_bytes(entry[12:16], 'little')
            if name_rva == 0:
                break
            name_offset = rva_to_offset(name_rva)
            if name_offset:
                f.seek(name_offset)
                dll_name = b''
                while True:
                    ch = f.read(1)
                    if not ch or ch == b'\x00':
                        break
                    dll_name += ch
                if dll_name:
                    imports.append(dll_name.decode('ascii', errors='ignore').lower())
            entry_offset += 20

        return imports


def _detect_ct2_variant() -> str:
    try:
        import ctranslate2
    except ImportError:
        return 'not_installed'

    dll_path = pathlib.Path(ctranslate2.__file__).parent / 'ctranslate2.dll'
    if not dll_path.exists():
        return 'cuda'

    imports = _read_pe_imports(dll_path)
    if any('amdhip' in name or 'hipblas' in name for name in imports):
        return 'rocm'
    return 'cuda'


def _detect_ct2_version() -> tuple[str, bool]:
    try:
        version = importlib.metadata.version('ctranslate2')
        return version, '+' in version
    except importlib.metadata.PackageNotFoundError:
        return 'unknown', False


def _check_runtime_compatibility(reqs: dict, runtime_version: str) -> bool:
    required = reqs['runtime_version']
    parts = [int(x) for x in runtime_version.split('.')]
    actual = tuple(parts[:len(required)])

    if actual < required:
        name = reqs['runtime_name']
        required_str = '.'.join(str(x) for x in required)
        _status(
            f"   ✗ GPU requires {name} {required_str}, found {name} {runtime_version}",
            'warning'
        )
        return False
    return True


# ── CUDA runtime libraries (issue #15) ───────────────────────────────────────
# What ctranslate2's CUDA build (4.x: CUDA 12 + cuDNN 9) loads by bare name on
# the FIRST INFERENCE, not at import or model load. So a CUDA model loads fine
# without them, and the first transcription then hangs instead of raising.
# cudnn64_9 is only a front; it pulls in the ops/cnn sub-libraries lazily, so
# those are probed by name too rather than assumed to come along.
_CUDA_RUNTIME_LIBRARIES = (
    'cublas64_12.dll',
    'cublasLt64_12.dll',
    'cudnn64_9.dll',
    'cudnn_ops64_9.dll',
    'cudnn_cnn64_9.dll',
)


# Names from _CUDA_RUNTIME_LIBRARIES that won't load. winmode=0 is the plain
# LoadLibrary search order (PATH included), i.e. exactly how ctranslate2 will
# look. ctypes' default mode skips PATH and would wrongly flag a CUDA toolkit
# that is installed system-wide.
def _missing_cuda_libraries() -> list[str]:
    missing = []
    for name in _CUDA_RUNTIME_LIBRARIES:
        try:
            ctypes.WinDLL(name, winmode=0)
        except OSError:
            missing.append(name)
    return missing


# CUDA libraries the configured GPU backend needs but can't load; empty when
# the setup is complete. Only the NVIDIA build of ctranslate2 is checked, since
# ROCm builds also run as device 'cuda' but need none of these.
# macOS mirror: platform/macos/gpu.py (always empty).
def missing_gpu_libraries() -> list[str]:
    if _detect_ct2_variant() != 'cuda':
        return []
    return _missing_cuda_libraries()


# Whether GPU transcription would actually work. get_supported_compute_types()
# alone only proves the driver answers: it passes on a machine with no cuBLAS or
# cuDNN anywhere, and onboarding then switched the app to CUDA without
# installing them (issue #15). For NVIDIA the runtime libraries must load too.
def _test_ct2_gpu(ct2_variant: str) -> bool:
    try:
        import ctranslate2
        if not ctranslate2.get_supported_compute_types('cuda'):
            return False
    except Exception:
        return False

    if ct2_variant == 'cuda':
        missing = _missing_cuda_libraries()
        if missing:
            _status(f"   ✗ Missing CUDA libraries: {', '.join(missing)}", 'warning')
            return False
    return True
