# tools/make_icons.py
# Regenerates every shipped icon file from the brand mark in
# src/whisper_key/ui/brand.py: the Windows .ico (also used by the .exe), the
# tray icons for each state on Windows and macOS, and the logo used by the
# README. Run from the repo root after changing the mark:
#
#     python tools/make_icons.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from whisper_key.ui.brand import render_mark  # noqa: E402

WINDOWS_ASSETS = ROOT / 'src' / 'whisper_key' / 'platform' / 'windows' / 'assets'
MACOS_ASSETS = ROOT / 'src' / 'whisper_key' / 'platform' / 'macos' / 'assets'
DOCS_ASSETS = ROOT / 'docs' / 'assets'

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    # The .ico holds a separately drawn image per size, so the 16 px one gets
    # the three-bar waveform instead of a blurry downscale of the big one.
    frames = [render_mark(s, 'idle', margin=0.0 if s <= 24 else 0.04) for s in ICO_SIZES]
    frames[-1].save(WINDOWS_ASSETS / 'whisperkey-icon.ico', format='ICO',
                    sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])

    # Tray: 64 px with no margin; pystray scales to the taskbar's size.
    for state in ('idle', 'recording', 'processing'):
        render_mark(64, state, margin=0.0).save(WINDOWS_ASSETS / f'tray_{state}.png')
        render_mark(44, state, margin=0.04).save(MACOS_ASSETS / f'tray_{state}.png')

    DOCS_ASSETS.mkdir(parents=True, exist_ok=True)
    render_mark(512, 'idle').save(DOCS_ASSETS / 'logo.png')
    print("Icons written.")


if __name__ == '__main__':
    main()
