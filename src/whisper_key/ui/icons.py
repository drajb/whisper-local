# ui/icons.py
# The app's line-icon set, drawn in code so it stays crisp at any display
# scaling and any colour: each icon is a list of strokes on a 24-unit grid
# (rounded caps and joins, the look of modern icon sets), rendered 4x larger
# with Pillow and scaled down for clean antialiasing. No icon font or image
# files to ship, and a new icon is a few lines below.

import math

STROKE = 1.8      # stroke width in grid units
SUPERSAMPLE = 4

# Each icon: a list of operations.
#   ('line', [(x, y), ...])           open polyline
#   ('poly', [(x, y), ...])           closed polyline
#   ('circle', cx, cy, r)             outlined circle
#   ('dot', cx, cy, r)                filled circle
#   ('arc', cx, cy, r, start, end)    outlined arc, degrees clockwise from 3 o'clock
#   ('rect', x0, y0, x1, y1, radius)  outlined rounded rectangle
ICONS = {
    'home': [('line', [(3, 11), (12, 3.5), (21, 11)]),
             ('line', [(5.5, 9.5), (5.5, 20), (18.5, 20), (18.5, 9.5)]),
             ('line', [(10, 20), (10, 14.5), (14, 14.5), (14, 20)])],
    'history': [('circle', 12, 12, 9), ('line', [(12, 7), (12, 12), (15.5, 14)])],
    'notes': [('rect', 5, 3, 19, 21, 2.5), ('line', [(9, 8), (15, 8)]),
              ('line', [(9, 12), (15, 12)]), ('line', [(9, 16), (12.5, 16)])],
    'transcribe': [('rect', 4.5, 3, 19.5, 21, 2.5), ('line', [(9, 10.5), (9, 15)]),
                   ('line', [(12, 8), (12, 17.5)]), ('line', [(15, 11), (15, 14.5)])],
    'dictionary': [('line', [(12, 6.5), (12, 20)]),
                   ('line', [(12, 6.5), (9.5, 5), (4, 5), (4, 18.5), (9.5, 18.5), (12, 20)]),
                   ('line', [(12, 6.5), (14.5, 5), (20, 5), (20, 18.5), (14.5, 18.5), (12, 20)])],
    'snippets': [('poly', [(13, 2.5), (4.5, 13.5), (11.5, 13.5), (10.5, 21.5),
                           (19.5, 10.5), (12.5, 10.5)])],
    'style': [('poly', [(4, 20), (8, 19), (19, 8), (16, 5), (5, 16)]),
              ('line', [(14, 7), (17, 10)])],
    'settings': [('line', [(4, 7), (6.6, 7)]), ('circle', 9, 7, 2.3), ('line', [(11.4, 7), (20, 7)]),
                 ('line', [(4, 12), (13.6, 12)]), ('circle', 16, 12, 2.3), ('line', [(18.4, 12), (20, 12)]),
                 ('line', [(4, 17), (5.6, 17)]), ('circle', 8, 17, 2.3), ('line', [(10.4, 17), (20, 17)])],
    'keyboard': [('rect', 2.5, 6, 21.5, 18, 2.5), ('dot', 7, 10, 0.9), ('dot', 10.3, 10, 0.9),
                 ('dot', 13.7, 10, 0.9), ('dot', 17, 10, 0.9), ('line', [(8, 14.5), (16, 14.5)])],
    'help': [('circle', 12, 12, 9), ('arc', 12, 9.8, 2.7, 180, 400),
             ('line', [(14.05, 11.55), (12, 13), (12, 13.8)]), ('dot', 12, 16.9, 1.0)],
    'info': [('circle', 12, 12, 9), ('line', [(12, 11), (12, 16.5)]), ('dot', 12, 7.8, 1.0)],
    'mic': [('rect', 9, 3, 15, 14.5, 3), ('arc', 12, 11.5, 6, 0, 180),
            ('line', [(12, 17.5), (12, 21)]), ('line', [(9, 21), (15, 21)])],
    'search': [('circle', 10.5, 10.5, 6.5), ('line', [(15.5, 15.5), (20, 20)])],
    'copy': [('rect', 8.5, 8.5, 20, 20, 2.5), ('line', [(4, 15.5), (4, 6.5)]),
             ('arc', 6.5, 6.5, 2.5, 180, 270), ('line', [(6.5, 4), (15.5, 4)])],
    'check': [('line', [(5, 12.5), (10, 17.5), (19.5, 7)])],
    'x': [('line', [(6, 6), (18, 18)]), ('line', [(18, 6), (6, 18)])],
    'plus': [('line', [(12, 5), (12, 19)]), ('line', [(5, 12), (19, 12)])],
    'trash': [('line', [(4, 6.5), (20, 6.5)]), ('line', [(9, 6.5), (9.5, 4), (14.5, 4), (15, 6.5)]),
              ('line', [(6, 6.5), (7, 20), (17, 20), (18, 6.5)]),
              ('line', [(10, 10.5), (10, 16)]), ('line', [(14, 10.5), (14, 16)])],
    'sparkles': [('poly', [(11, 3), (12.7, 8.3), (18, 10), (12.7, 11.7), (11, 17),
                           (9.3, 11.7), (4, 10), (9.3, 8.3)]),
                 ('line', [(18.5, 15), (18.5, 21)]), ('line', [(15.5, 18), (21.5, 18)])],
    'chevron_down': [('line', [(6, 9), (12, 15), (18, 9)])],
    'chevron_right': [('line', [(9, 6), (15, 12), (9, 18)])],
    'external': [('line', [(14, 4), (20, 4), (20, 10)]), ('line', [(20, 4), (11, 13)]),
                 ('line', [(17, 14), (17, 19), (5, 19), (5, 7), (10, 7)])],
    'refresh': [('arc', 12, 12, 8, -55, 235), ('line', [(3.6, 4.6), (7.4, 5.2), (8, 1.6)])],
    'download': [('line', [(12, 4), (12, 15)]), ('line', [(7.5, 10.5), (12, 15), (16.5, 10.5)]),
                 ('line', [(5, 19.5), (19, 19.5)])],
    'upload': [('line', [(12, 15.5), (12, 4)]), ('line', [(7.5, 8.5), (12, 4), (16.5, 8.5)]),
               ('line', [(5, 19.5), (19, 19.5)])],
    'pause': [('line', [(9, 6), (9, 18)]), ('line', [(15, 6), (15, 18)])],
    'play': [('poly', [(8, 5), (19, 12), (8, 19)])],
    'calendar': [('rect', 4, 5, 20, 20, 2.5), ('line', [(4, 10), (20, 10)]),
                 ('line', [(8, 3), (8, 7)]), ('line', [(16, 3), (16, 7)]),
                 ('line', [(9, 15), (11, 17), (15, 13)])],
    'words': [('line', [(5, 7.5), (5, 5), (19, 5), (19, 7.5)]), ('line', [(12, 5), (12, 19)]),
              ('line', [(9.5, 19), (14.5, 19)])],
    'hourglass': [('line', [(6, 3), (18, 3)]), ('line', [(6, 21), (18, 21)]),
                  ('line', [(7.5, 3), (7.5, 7), (12, 12), (16.5, 7), (16.5, 3)]),
                  ('line', [(7.5, 21), (7.5, 17), (12, 12), (16.5, 17), (16.5, 21)])],
    'gauge': [('arc', 12, 15, 8.5, 180, 360), ('line', [(12, 15), (16, 10)]), ('dot', 12, 15, 1.3),
              ('line', [(3.5, 15), (3.5, 15.01)]), ('line', [(20.5, 15), (20.5, 15.01)])],
    'wand': [('line', [(4, 20), (14.5, 9.5)]), ('line', [(15, 3), (15, 6)]),
             ('line', [(13.5, 4.5), (16.5, 4.5)]), ('line', [(19.5, 8), (19.5, 11)]),
             ('line', [(18, 9.5), (21, 9.5)]), ('line', [(19, 3.5), (19, 3.51)])],
    'folder': [('line', [(3, 7), (3, 18.5), (21, 18.5), (21, 8.5), (12, 8.5), (10, 5.5), (3, 5.5), (3, 7)])],
    'restart': [('arc', 12, 13, 7.5, -70, 250), ('line', [(9, 2.8), (12, 5.5), (9, 8.2)])],
    'flame': [('line', [(12, 21), (8.5, 19.5), (6.5, 16), (7, 12), (10, 8.5), (11, 5),
                        (11.5, 3), (14.5, 6.5), (17, 10.5), (17.5, 15), (16, 19), (12, 21)]),
              ('line', [(12, 21), (10.5, 18.5), (11, 15.5), (12.5, 13), (14, 16), (13.5, 19.5), (12, 21)])],
    'logo': [('line', [(5, 10), (5, 14)]), ('line', [(9, 7), (9, 17)]), ('line', [(12, 4.5), (12, 19.5)]),
             ('line', [(15, 7), (15, 17)]), ('line', [(19, 10), (19, 14)])],
}


def _hex_to_rgba(color: str):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


# Draws one icon as an RGBA Pillow image, `size` pixels square.
def render(name: str, size: int, color: str = '#000000', stroke: float = STROKE):
    from PIL import Image, ImageDraw
    ops = ICONS[name]
    big = size * SUPERSAMPLE
    unit = big / 24.0
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    rgba = _hex_to_rgba(color)
    width = max(1, int(round(stroke * unit)))
    cap = width / 2.0

    def at(p):
        return (p[0] * unit, p[1] * unit)

    def round_cap(p):
        x, y = at(p)
        draw.ellipse((x - cap, y - cap, x + cap, y + cap), fill=rgba)

    for op in ops:
        kind = op[0]
        if kind in ('line', 'poly'):
            points = [at(p) for p in op[1]]
            if kind == 'poly':
                points = points + [points[0]]
            draw.line(points, fill=rgba, width=width, joint='curve')
            for p in op[1]:
                round_cap(p)   # rounds every joint, not just the ends
        elif kind == 'circle':
            _, cx, cy, r = op
            x, y = at((cx, cy))
            rr = r * unit
            draw.ellipse((x - rr, y - rr, x + rr, y + rr), outline=rgba, width=width)
        elif kind == 'dot':
            _, cx, cy, r = op
            x, y = at((cx, cy))
            rr = r * unit
            draw.ellipse((x - rr, y - rr, x + rr, y + rr), fill=rgba)
        elif kind == 'arc':
            _, cx, cy, r, start, end = op
            x, y = at((cx, cy))
            rr = r * unit
            draw.arc((x - rr, y - rr, x + rr, y + rr), start, end, fill=rgba, width=width)
            for angle in (start, end):
                rad = math.radians(angle)
                round_cap((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        elif kind == 'rect':
            _, x0, y0, x1, y1, radius = op
            draw.rounded_rectangle((*at((x0, y0)), *at((x1, y1))), radius=radius * unit,
                                   outline=rgba, width=width)
    return image.resize((size, size), Image.LANCZOS)
