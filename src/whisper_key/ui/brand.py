# ui/brand.py
# The app's mark: a rounded "squircle" tile with a violet-to-blue gradient and
# a white voice waveform. Drawn in code (Pillow) so the window icon, the
# sidebar logo, the tray states and the shipped .ico/.png files all come from
# one definition. tools/make_icons.py writes the asset files from here.

import math

from .theme import BRAND_GRADIENT

SUPERSAMPLE = 4

# Tile gradients for the tray states: idle wears the brand colours, recording
# is red (the universal "live" colour), processing amber, matching the
# status colours other dictation apps have taught people.
STATE_GRADIENTS = {
    'idle': BRAND_GRADIENT,
    'recording': ('#ff5f6d', '#e5243b'),
    'processing': ('#ffb547', '#f07b16'),
}


def _rgb(color: str):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


# Points of a superellipse |x|^n + |y|^n = 1 (n=5 is close to Apple's
# continuous-corner squircle), scaled into a size x size box with a margin.
def _squircle(size: float, margin: float, n: float = 5.0, steps: int = 240):
    half = size / 2.0
    radius = half - margin
    points = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = math.copysign(abs(c) ** (2 / n), c)
        y = math.copysign(abs(s) ** (2 / n), s)
        points.append((half + radius * x, half + radius * y))
    return points


# A diagonal gradient (top-left to bottom-right) filling the whole square.
def _gradient(size: int, start: str, end: str):
    from PIL import Image
    a, b = _rgb(start), _rgb(end)
    image = Image.new('RGB', (size, size))
    pixels = image.load()
    span = 2 * (size - 1) or 1
    for y in range(size):
        for x in range(size):
            t = (x + y) / span
            pixels[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return image


# The white waveform. Five bars from 24 px up; three below that, where five
# would blur into a block.
def _draw_bars(draw, big: int, scale_to_tile: float, state: str):
    if state == 'processing':
        # Three dots: "working on it".
        r = big * 0.075
        for k in (-1, 0, 1):
            cx = big / 2 + k * big * 0.2
            cy = big / 2
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))
        return
    small = scale_to_tile < 24
    heights = (0.30, 0.58, 0.30) if small else (0.22, 0.42, 0.62, 0.42, 0.22)
    if state == 'recording':
        heights = (0.36, 0.64, 0.36) if small else (0.30, 0.50, 0.66, 0.50, 0.30)
    gap = big * (0.17 if small else 0.125)
    width = big * (0.105 if small else 0.075)
    first = big / 2 - gap * (len(heights) - 1) / 2
    for i, h in enumerate(heights):
        x = first + i * gap
        half = big * h / 2
        draw.rounded_rectangle((x - width / 2, big / 2 - half, x + width / 2, big / 2 + half),
                               radius=width / 2, fill=(255, 255, 255, 255))


# The tile as an RGBA image, `size` pixels square. `margin` is the transparent
# border as a fraction of the size (tray icons want almost none, the app icon
# a little so it sits like other apps' icons).
def render_mark(size: int, state: str = 'idle', margin: float = 0.04):
    from PIL import Image, ImageDraw
    big = size * SUPERSAMPLE
    start, end = STATE_GRADIENTS.get(state, BRAND_GRADIENT)
    fill = _gradient(big, start, end).convert('RGBA')
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).polygon(_squircle(big, big * margin), fill=255)
    tile = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    tile.paste(fill, (0, 0), mask)
    # A soft sheen fading out by the middle gives the tile some depth without
    # the hard-edged gloss of older icon styles.
    sheen = Image.new('L', (1, big), 0)
    fade_to = big * 0.6
    for y in range(big):
        sheen.putpixel((0, y), int(34 * max(0.0, 1 - y / fade_to)))
    sheen = sheen.resize((big, big))
    white = Image.new('RGBA', (big, big), (255, 255, 255, 255))
    tile.paste(white, (0, 0), Image.composite(sheen, Image.new('L', (big, big), 0), mask))
    _draw_bars(ImageDraw.Draw(tile), big, size, state)
    return tile.resize((size, size), Image.LANCZOS)
