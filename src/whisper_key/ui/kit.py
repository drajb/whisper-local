# ui/kit.py
# The widget kit every window is built from: rounded buttons, toggle switches,
# text fields, select menus, segmented controls, cards, key-cap chips, a thin
# scrollbar, toasts and a confirm dialog, all in the active theme.
#
# Plain Tk draws square, aliased, 1990s widgets. Here every rounded shape is
# assembled from four antialiased corner images (cached, drawn 4x with Pillow)
# plus flat rectangles, so it is smooth at any size, resizes for free, and
# costs no extra dependency. Windows also get crisp per-monitor DPI rendering,
# the brand icon, and a title bar coloured to match the window.

import logging
import sys
import tkinter as tk
import tkinter.font as tkfont

from . import theme

logger = logging.getLogger(__name__)

SUPERSAMPLE = 4


# ── Window setup ─────────────────────────────────────────────────────────────

# Makes Tk windows created on THIS thread render at the monitor's real DPI.
# Without it Windows bitmap-stretches the whole window at 125/150% scaling,
# which is most of why Tk apps look blurry. Per-thread, so the rest of the
# app (tray, hotkeys) is untouched. Call before tk.Tk().
def prepare_dpi():
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        per_monitor_v2 = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetThreadDpiAwarenessContext(per_monitor_v2)
    except Exception as e:
        logger.debug(f"DPI awareness not available: {e}")


# Creates a themed top-level window and its Kit. `size` and `min_size` are in
# logical (96-dpi) pixels; the kit scales them. Returns (root, kit).
def new_window(title: str, size=(960, 680), min_size=None, resizable=True, center=True,
               master=None):
    if master is None:
        prepare_dpi()
        root = tk.Tk()
    else:
        root = tk.Toplevel(master)
    kit = Kit(root)
    root.title(title)
    root.configure(bg=kit.p['bg'])
    w, h = kit.px(size[0]), kit.px(size[1])
    if center:
        x = max(0, (root.winfo_screenwidth() - w) // 2)
        y = max(0, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"{w}x{h}+{x}+{y}")
    else:
        root.geometry(f"{w}x{h}")
    if min_size:
        root.minsize(kit.px(min_size[0]), kit.px(min_size[1]))
    root.resizable(resizable, resizable)
    kit.apply_window_chrome(root)
    return root, kit


def _hex_rgb(color: str):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


# Picks the best available UI font families for this OS.
def _font_families(root):
    families = set(tkfont.families(root))

    def first(*names):
        for name in names:
            if name in families:
                return name
        return names[-1]
    if sys.platform == 'win32':
        return {
            'text': first('Segoe UI Variable Text', 'Segoe UI'),
            'semibold': first('Segoe UI Variable Text Semibold', 'Segoe UI Semibold'),
            'display': first('Segoe UI Variable Display Semib', 'Segoe UI Semibold'),
            'mono': first('Cascadia Mono', 'Consolas'),
            'weight': 'normal',   # the semibold families carry their own weight
        }
    if sys.platform == 'darwin':
        return {
            'text': first('SF Pro Text', 'Helvetica Neue'),
            'semibold': first('SF Pro Text', 'Helvetica Neue'),
            'display': first('SF Pro Display', 'Helvetica Neue'),
            'mono': first('SF Mono', 'Menlo'),
            'weight': 'bold',
        }
    return {
        'text': first('Inter', 'Cantarell', 'DejaVu Sans'),
        'semibold': first('Inter', 'Cantarell', 'DejaVu Sans'),
        'display': first('Inter', 'Cantarell', 'DejaVu Sans'),
        'mono': first('JetBrains Mono', 'DejaVu Sans Mono'),
        'weight': 'bold',
    }


# Type scale: role -> (family key, point size, bold?).
TYPE_SCALE = {
    'display': ('display', 22, True),
    'stat': ('display', 20, True),
    'title': ('display', 15, True),
    'heading': ('semibold', 11, True),
    'body': ('text', 10, False),
    'body_strong': ('semibold', 10, True),
    'small': ('text', 9, False),
    'small_strong': ('semibold', 9, True),
    'caption': ('text', 8, False),
    'mono': ('mono', 10, False),
    'mono_small': ('mono', 9, False),
}


class Kit:
    """Theme, scale, fonts and image cache for one Tk root and its children."""

    def __init__(self, root, theme_name: str = None):
        self.root = root
        self.p = theme.palette(theme_name)
        self.dark = (theme_name or theme.active()) == 'dark'
        try:
            self.scale = max(1.0, root.winfo_fpixels('1i') / 96.0)
        except Exception:
            self.scale = 1.0
        self._families = _font_families(root)
        self._images = {}
        self._fonts = {}

    # Logical pixels -> device pixels.
    def px(self, n) -> int:
        return int(round(n * self.scale))

    def font(self, role: str = 'body'):
        family_key, size, bold = TYPE_SCALE[role]
        if sys.platform == 'darwin':
            size = int(round(size * 1.3))   # Tk on macOS uses 72-dpi points
        weight = self._families['weight'] if bold else 'normal'
        return (self._families[family_key], size, weight)

    def measure(self, text: str, role: str = 'body') -> int:
        key = self.font(role)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self.root, font=key)
        return self._fonts[key].measure(text)

    def line_height(self, role: str = 'body') -> int:
        key = self.font(role)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self.root, font=key)
        return self._fonts[key].metrics('linespace')

    # A themed line icon as a PhotoImage (kept alive by the cache).
    def icon(self, name: str, size: int = 18, color: str = None):
        color = color or self.p['text']
        key = ('icon', name, size, color)
        if key not in self._images:
            from PIL import ImageTk
            from .icons import render
            self._images[key] = ImageTk.PhotoImage(render(name, self.px(size), color), master=self.root)
        return self._images[key]

    def brand_mark(self, size: int, state: str = 'idle'):
        key = ('brand', size, state)
        if key not in self._images:
            from PIL import ImageTk
            from .brand import render_mark
            self._images[key] = ImageTk.PhotoImage(render_mark(self.px(size), state), master=self.root)
        return self._images[key]

    # The four antialiased corner pieces of a rounded rectangle with radius
    # `r` device pixels, filled with `fill` and outlined `outline` (or none).
    def _corners(self, r: int, fill: str, outline: str = None, border: int = 1):
        key = ('corners', r, fill, outline, border)
        if key in self._images:
            return self._images[key]
        from PIL import Image, ImageDraw, ImageTk
        big = 2 * r * SUPERSAMPLE
        image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if outline:
            draw.ellipse((0, 0, big - 1, big - 1), fill=_hex_rgb(outline) + (255,))
            inset = border * SUPERSAMPLE
            draw.ellipse((inset, inset, big - 1 - inset, big - 1 - inset), fill=_hex_rgb(fill) + (255,))
        else:
            draw.ellipse((0, 0, big - 1, big - 1), fill=_hex_rgb(fill) + (255,))
        image = image.resize((2 * r, 2 * r), Image.LANCZOS)
        pieces = (image.crop((0, 0, r, r)), image.crop((r, 0, 2 * r, r)),
                  image.crop((0, r, r, 2 * r)), image.crop((r, r, 2 * r, 2 * r)))
        self._images[key] = tuple(ImageTk.PhotoImage(p, master=self.root) for p in pieces)
        return self._images[key]

    # Draws a rounded rectangle on `canvas` from corner images and flat
    # rectangles, tagged `tag` so callers can delete or restack it.
    def round_rect(self, canvas, x0, y0, x1, y1, r, fill, outline=None, tag='shape', border=None):
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        r = int(max(1, min(r, (x1 - x0) // 2, (y1 - y0) // 2)))
        border = border or max(1, self.px(1))
        tl, tr, bl, br = self._corners(r, fill, outline, border)
        canvas.create_image(x0, y0, image=tl, anchor='nw', tags=tag)
        canvas.create_image(x1 - r, y0, image=tr, anchor='nw', tags=tag)
        canvas.create_image(x0, y1 - r, image=bl, anchor='nw', tags=tag)
        canvas.create_image(x1 - r, y1 - r, image=br, anchor='nw', tags=tag)
        canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline='', tags=tag)
        canvas.create_rectangle(x0, y0 + r, x0 + r, y1 - r, fill=fill, outline='', tags=tag)
        canvas.create_rectangle(x1 - r, y0 + r, x1, y1 - r, fill=fill, outline='', tags=tag)
        if outline:
            canvas.create_rectangle(x0 + r, y0, x1 - r, y0 + border, fill=outline, outline='', tags=tag)
            canvas.create_rectangle(x0 + r, y1 - border, x1 - r, y1, fill=outline, outline='', tags=tag)
            canvas.create_rectangle(x0, y0 + r, x0 + border, y1 - r, fill=outline, outline='', tags=tag)
            canvas.create_rectangle(x1 - border, y0 + r, x1, y1 - r, fill=outline, outline='', tags=tag)

    # Window icon (the brand mark) and, on Windows 11, a title bar in the
    # window's own colours instead of the default white/black strip.
    def apply_window_chrome(self, window):
        try:
            from PIL import ImageTk
            from .brand import render_mark
            icons = [ImageTk.PhotoImage(render_mark(s), master=self.root) for s in (16, 32, 48, 64, 128)]
            self._images[('window-icons', id(window))] = icons
            window.iconphoto(True, *icons)
        except Exception as e:
            logger.debug(f"Window icon failed: {e}")
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            window.update_idletasks()
            hwnd = int(window.wm_frame(), 16)
            dwm = ctypes.windll.dwmapi

            def set_attr(attribute, value):
                data = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

            def colorref(color):
                r, g, b = _hex_rgb(color)
                return r | (g << 8) | (b << 16)
            set_attr(20, 1 if self.dark else 0)              # DWMWA_USE_IMMERSIVE_DARK_MODE
            set_attr(35, colorref(self.p['sidebar']))        # DWMWA_CAPTION_COLOR (Win11)
            set_attr(36, colorref(self.p['text']))           # DWMWA_TEXT_COLOR
            set_attr(34, colorref(self.p['sidebar']))        # DWMWA_BORDER_COLOR
        except Exception as e:
            logger.debug(f"Title bar styling failed: {e}")

    # ── Small conveniences ──────────────────────────────────────────────────

    def label(self, parent, text='', role='body', color='text', bg=None, **kw):
        return tk.Label(parent, text=text, font=self.font(role), fg=self.p.get(color, color),
                        bg=bg or _bg_of(parent), anchor=kw.pop('anchor', 'w'),
                        justify=kw.pop('justify', 'left'), bd=0, **kw)

    def frame(self, parent, bg=None, **kw):
        return tk.Frame(parent, bg=bg or _bg_of(parent), bd=0, highlightthickness=0, **kw)

    def separator(self, parent, bg=None):
        line = tk.Frame(parent, bg=self.p['border'], height=max(1, self.px(1)), bd=0)
        return line

    # Short-lived message at the bottom of `window` ("Saved", "Copied").
    def toast(self, window, text: str, kind: str = 'info', ms: int = 2200):
        try:
            old = getattr(window, '_kit_toast', None)
            if old is not None:
                old.destroy()
        except Exception:
            pass
        fill = {'info': self.p['text'], 'success': self.p['success'],
                'danger': self.p['danger']}.get(kind, self.p['text'])
        fg = self.p['bg']
        width = self.measure(text, 'body_strong') + self.px(36)
        height = self.px(38)
        canvas = tk.Canvas(window, width=width, height=height, bg=_bg_of(window),
                           highlightthickness=0, bd=0)
        self.round_rect(canvas, 0, 0, width, height, height // 2, fill)
        canvas.create_text(width // 2, height // 2, text=text, fill=fg, font=self.font('body_strong'))
        canvas.place(relx=0.5, rely=1.0, y=-self.px(24), anchor='s')
        window._kit_toast = canvas

        def remove():
            try:
                canvas.destroy()
            except Exception:
                pass
        window.after(ms, remove)

    # A themed yes/no dialog. Returns True when confirmed.
    def confirm(self, parent, title: str, message: str, confirm_text: str = 'Continue',
                danger: bool = False) -> bool:
        dialog, kit = new_window(title, size=(420, 200), resizable=False, master=parent)
        dialog.transient(parent.winfo_toplevel())
        result = {'ok': False}
        body = kit.frame(dialog, bg=kit.p['bg'])
        body.pack(fill='both', expand=True, padx=kit.px(24), pady=kit.px(20))
        kit.label(body, title, 'title').pack(fill='x')
        kit.label(body, message, 'body', 'text_muted', wraplength=kit.px(370)).pack(fill='x', pady=(kit.px(8), 0))
        row = kit.frame(body)
        row.pack(side='bottom', fill='x')

        def finish(ok):
            result['ok'] = ok
            dialog.destroy()
        Button(row, kit, confirm_text, lambda: finish(True),
               variant='danger' if danger else 'primary').pack(side='right')
        Button(row, kit, 'Cancel', lambda: finish(False), variant='secondary').pack(side='right', padx=(0, kit.px(8)))
        dialog.update_idletasks()
        dialog.geometry(f"{dialog.winfo_width()}x{body.winfo_reqheight() + kit.px(40)}")
        dialog.bind('<Escape>', lambda e: finish(False))
        dialog.bind('<Return>', lambda e: finish(True))
        dialog.grab_set()
        dialog.wait_window()
        return result['ok']


def _bg_of(widget):
    try:
        return widget.cget('bg')
    except Exception:
        try:
            return widget.cget('background')
        except Exception:
            return '#000000'


# ── Widgets ──────────────────────────────────────────────────────────────────

class Button(tk.Canvas):
    """Rounded button. variant: primary, secondary, ghost, danger, soft."""

    SIZES = {'sm': (28, 10, 'small_strong', 14), 'md': (34, 14, 'body_strong', 16),
             'lg': (40, 18, 'body_strong', 18)}

    def __init__(self, parent, kit, text='', command=None, variant='secondary', icon=None,
                 size='md', width=None, bg=None):
        self.kit = kit
        self.text = text
        self.command = command
        self.variant = variant
        self.icon_name = icon
        self.size = size
        self._hover = self._pressed = self._focused = False
        self._enabled = True
        height, self._pad, self._role, self._icon_px = self.SIZES[size]
        self._h = kit.px(height)
        self._width = kit.px(width) if width else self._natural_width()
        super().__init__(parent, width=self._width, height=self._h, bg=bg or _bg_of(parent),
                         highlightthickness=0, bd=0, cursor='hand2', takefocus=1)
        for seq, fn in (('<Enter>', self._enter), ('<Leave>', self._leave),
                        ('<ButtonPress-1>', self._press), ('<ButtonRelease-1>', self._release),
                        ('<FocusIn>', self._focus_in), ('<FocusOut>', self._focus_out),
                        ('<Return>', self._invoke), ('<space>', self._invoke)):
            self.bind(seq, fn)
        self._draw()

    def _natural_width(self):
        kit = self.kit
        width = 2 * kit.px(self._pad)
        if self.text:
            width += kit.measure(self.text, self._role)
        if self.icon_name:
            width += kit.px(self._icon_px) + (kit.px(7) if self.text else 0)
        if not self.text:
            width = self._h   # icon-only buttons are square
        return width

    def _colors(self):
        p = self.kit.p
        hot = self._hover or self._pressed
        if not self._enabled:
            return p['field'], None, p['text_faint']
        return {
            'primary': (p['accent_hover'] if hot else p['accent'], None, p['accent_text']),
            'secondary': (p['surface_hover'] if hot else p['surface'], p['border_strong'] if hot else p['border'], p['text']),
            'ghost': (p['surface_hover'] if hot else _bg_of(self), None, p['text'] if hot else p['text_muted']),
            'danger': (p['danger'] if hot else p['danger_soft'], None, p['accent_text'] if hot else p['danger']),
            'soft': (p['accent_soft'], p['accent'] if hot else None, p['accent']),
        }[self.variant]

    def _draw(self):
        kit = self.kit
        self.delete('all')
        fill, outline, fg = self._colors()
        if self._focused:
            outline = kit.p['accent']
        if fill != _bg_of(self) or outline:   # an idle ghost button has no shape at all
            kit.round_rect(self, 0, 0, self._width, self._h, kit.px(9), fill, outline)
        content_w = (kit.measure(self.text, self._role) if self.text else 0)
        icon_w = kit.px(self._icon_px) if self.icon_name else 0
        gap = kit.px(7) if (self.text and self.icon_name) else 0
        x = (self._width - content_w - icon_w - gap) // 2
        cy = self._h // 2 + (1 if self._pressed else 0)
        if self.icon_name:
            self.create_image(x, cy, image=kit.icon(self.icon_name, self._icon_px, fg), anchor='w')
            x += icon_w + gap
        if self.text:
            self.create_text(x, cy, text=self.text, fill=fg, font=kit.font(self._role), anchor='w')

    def configure_text(self, text):
        self.text = text
        self._draw()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.configure(cursor='hand2' if enabled else 'arrow')
        self._draw()

    def _enter(self, _e):
        self._hover = True
        self._draw()

    def _leave(self, _e):
        self._hover = self._pressed = False
        self._draw()

    def _press(self, _e):
        if self._enabled:
            self._pressed = True
            self._draw()

    def _release(self, e):
        was = self._pressed
        self._pressed = False
        self._draw()
        inside = 0 <= e.x <= self._width and 0 <= e.y <= self._h
        if was and inside:
            self._invoke()

    def _focus_in(self, _e):
        self._focused = True
        self._draw()

    def _focus_out(self, _e):
        self._focused = False
        self._draw()

    def _invoke(self, _e=None):
        if self._enabled and self.command:
            self.command()


class Toggle(tk.Canvas):
    """On/off switch bound to a BooleanVar; `command(value)` runs on change."""

    def __init__(self, parent, kit, variable, command=None, bg=None):
        self.kit = kit
        self.variable = variable
        self.command = command
        self._width, self._h = kit.px(38), kit.px(22)
        super().__init__(parent, width=self._width, height=self._h, bg=bg or _bg_of(parent),
                         highlightthickness=0, bd=0, cursor='hand2', takefocus=1)
        self._pos = 1.0 if variable.get() else 0.0
        self.bind('<ButtonRelease-1>', lambda e: self.flip())
        self.bind('<space>', lambda e: self.flip())
        self._draw()

    def flip(self):
        self.variable.set(not self.variable.get())
        self._animate()
        if self.command:
            self.command(self.variable.get())

    def _animate(self, step=0):
        target = 1.0 if self.variable.get() else 0.0
        self._pos += (target - self._pos) * 0.5
        if abs(target - self._pos) < 0.05 or step > 8:
            self._pos = target
        self._draw()
        if self._pos != target:
            self.after(12, lambda: self._animate(step + 1))

    def _draw(self):
        kit, p = self.kit, self.kit.p
        self.delete('all')
        on = self._pos > 0.5
        track = p['accent'] if on else p['border_strong']
        kit.round_rect(self, 0, 0, self._width, self._h, self._h // 2, track)
        inset = kit.px(3)
        d = self._h - 2 * inset
        x = inset + (self._width - 2 * inset - d) * self._pos
        knob = kit._corners(d // 2, '#ffffff')
        # Four quarter images make the circle.
        self.create_image(x, inset, image=knob[0], anchor='nw')
        self.create_image(x + d // 2, inset, image=knob[1], anchor='nw')
        self.create_image(x, inset + d // 2, image=knob[2], anchor='nw')
        self.create_image(x + d // 2, inset + d // 2, image=knob[3], anchor='nw')


class Field(tk.Canvas):
    """Rounded single-line text field with an optional icon and placeholder."""

    def __init__(self, parent, kit, variable, placeholder='', icon=None, width=None,
                 mono=False, bg=None, on_submit=None):
        self.kit = kit
        self.variable = variable
        self.placeholder = placeholder
        self.icon_name = icon
        self._h = kit.px(36)
        self._focused = False
        super().__init__(parent, height=self._h, width=kit.px(width) if width else kit.px(200),
                         bg=bg or _bg_of(parent), highlightthickness=0, bd=0, cursor='xterm')
        p = kit.p
        self.entry = tk.Entry(self, textvariable=variable, bd=0, relief='flat', highlightthickness=0,
                              bg=p['field'], fg=p['text'], insertbackground=p['text'],
                              selectbackground=p['selection'], selectforeground=p['text'],
                              font=kit.font('mono' if mono else 'body'))
        self._window = self.create_window(0, 0, window=self.entry, anchor='w')
        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<Button-1>', lambda e: self.entry.focus_set())
        self.entry.bind('<FocusIn>', lambda e: self._set_focus(True))
        self.entry.bind('<FocusOut>', lambda e: self._set_focus(False))
        if on_submit:
            self.entry.bind('<Return>', lambda e: on_submit())
        variable.trace_add('write', lambda *_: self._draw())

    def _set_focus(self, focused):
        self._focused = focused
        self._draw()

    def focus(self):
        self.entry.focus_set()

    def _draw(self):
        kit, p = self.kit, self.kit.p
        try:
            w = self.winfo_width()
        except tk.TclError:
            return
        if w <= 1:
            w = int(self.cget('width'))
        self.delete('shape')
        self.delete('ph')
        outline = p['accent'] if self._focused else p['border']
        kit.round_rect(self, 0, 0, w, self._h, kit.px(9), p['field'], outline)
        left = kit.px(12)
        if self.icon_name:
            self.create_image(left, self._h // 2, image=kit.icon(self.icon_name, 16, p['text_faint']),
                              anchor='w', tags='shape')
            left += kit.px(24)
        self.coords(self._window, left, self._h // 2)
        self.itemconfigure(self._window, width=max(10, w - left - kit.px(12)))
        self.tag_lower('shape')
        empty = not self.variable.get()
        if empty and not self._focused and self.placeholder:
            self.itemconfigure(self._window, state='hidden')
            self.create_text(left, self._h // 2, text=self.placeholder, anchor='w',
                             fill=p['text_faint'], font=kit.font('body'), tags='ph')
        else:
            self.itemconfigure(self._window, state='normal')


class Select(Button):
    """A button showing the current choice; clicking opens a menu of options.
    `options` is a list of (value, label)."""

    def __init__(self, parent, kit, variable, options, command=None, width=None, bg=None):
        self.variable = variable
        self.options = list(options)
        self.on_change = command
        label_w = max((kit.measure(lbl, 'body') for _, lbl in self.options), default=60)
        natural = label_w + kit.px(14) * 2 + kit.px(22)
        super().__init__(parent, kit, self._label(), self._open, variant='secondary', size='md',
                         bg=bg, width=None)
        self._width = max(kit.px(width) if width else 0, natural)
        self.configure(width=self._width)
        variable.trace_add('write', lambda *_: self.configure_text(self._label()))
        self._draw()

    def _label(self):
        current = str(self.variable.get())
        for value, label in self.options:
            if str(value) == current:
                return label
        return current or '—'

    def _draw(self):
        kit = self.kit
        self.delete('all')
        fill, outline, fg = self._colors()
        if self._focused:
            outline = kit.p['accent']
        kit.round_rect(self, 0, 0, self._width, self._h, kit.px(9), fill, outline)
        self.create_text(kit.px(12), self._h // 2, text=self.text, fill=fg,
                         font=kit.font('body'), anchor='w')
        self.create_image(self._width - kit.px(10), self._h // 2,
                          image=kit.icon('chevron_down', 14, kit.p['text_muted']), anchor='e')

    def _open(self):
        p = self.kit.p
        menu = tk.Menu(self, tearoff=0, bg=p['surface'], fg=p['text'], activebackground=p['accent'],
                       activeforeground=p['accent_text'], bd=0, font=self.kit.font('body'))
        for value, label in self.options:
            menu.add_radiobutton(label=label, value=value, variable=self.variable,
                                 command=lambda v=value: self._chosen(v))
        try:
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self._h + self.kit.px(2))
        finally:
            menu.grab_release()

    def _chosen(self, value):
        if self.on_change:
            self.on_change(value)


class Segmented(tk.Canvas):
    """A row of mutually exclusive options. `options`: list of (value, label)."""

    def __init__(self, parent, kit, variable, options, command=None, bg=None):
        self.kit = kit
        self.variable = variable
        self.options = list(options)
        self.command = command
        self._h = kit.px(34)
        self._seg_w = max(kit.measure(lbl, 'body_strong') for _, lbl in self.options) + kit.px(28)
        self._width = self._seg_w * len(self.options) + kit.px(8)
        super().__init__(parent, width=self._width, height=self._h, bg=bg or _bg_of(parent),
                         highlightthickness=0, bd=0, cursor='hand2')
        self.bind('<ButtonRelease-1>', self._click)
        variable.trace_add('write', lambda *_: self._draw())
        self._draw()

    def _click(self, e):
        index = int((e.x - self.kit.px(4)) // self._seg_w)
        if 0 <= index < len(self.options):
            value = self.options[index][0]
            self.variable.set(value)
            if self.command:
                self.command(value)

    def _draw(self):
        kit, p = self.kit, self.kit.p
        self.delete('all')
        kit.round_rect(self, 0, 0, self._width, self._h, kit.px(10), p['field'], p['border'])
        inset = kit.px(4)
        current = str(self.variable.get())
        for i, (value, label) in enumerate(self.options):
            x0 = inset + i * self._seg_w
            selected = str(value) == current
            if selected:
                kit.round_rect(self, x0, inset, x0 + self._seg_w, self._h - inset, kit.px(7),
                               p['surface'], p['border'], tag='sel')
            self.create_text(x0 + self._seg_w // 2, self._h // 2, text=label,
                             fill=p['text'] if selected else p['text_muted'],
                             font=kit.font('body_strong' if selected else 'body'))


class Card(tk.Canvas):
    """A rounded, bordered panel. Put content in `card.body`; the card grows
    to fit it and stretches to the width it is packed into."""

    def __init__(self, parent, kit, padding=18, fill=None, outline=True, radius=14, bg=None):
        self.kit = kit
        self._pad = kit.px(padding)
        self._fill = fill or kit.p['surface']
        self._outline = kit.p['border'] if outline else None
        self._radius = kit.px(radius)
        # Start tall enough for the body to be on-canvas: an embedded window
        # that starts out of view is never mapped, so it never reports its
        # size and the card would stay collapsed.
        super().__init__(parent, bg=bg or _bg_of(parent), highlightthickness=0, bd=0,
                         height=2 * self._pad + 4)
        self.body = tk.Frame(self, bg=self._fill, bd=0, highlightthickness=0)
        self._window = self.create_window(self._pad, self._pad, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._fit_height)
        self.bind('<Configure>', self._redraw)

    def _fit_height(self, _e=None):
        height = self.body.winfo_reqheight() + 2 * self._pad
        if int(self.cget('height')) != height:
            self.configure(height=height)

    def _redraw(self, e):
        self.delete('shape')
        self.kit.round_rect(self, 0, 0, e.width, e.height, self._radius, self._fill, self._outline)
        self.tag_lower('shape')
        self.itemconfigure(self._window, width=max(10, e.width - 2 * self._pad))


def kbd(parent, kit, text: str, bg=None):
    """A key-cap chip for showing a hotkey ("CTRL", "WIN")."""
    p = kit.p
    role = 'mono_small'
    w = kit.measure(text, role) + kit.px(16)
    h = kit.px(24)
    canvas = tk.Canvas(parent, width=w, height=h, bg=bg or _bg_of(parent), highlightthickness=0, bd=0)
    kit.round_rect(canvas, 0, 0, w, h, kit.px(6), p['field'], p['border_strong'])
    canvas.create_text(w // 2, h // 2, text=text, fill=p['text'], font=kit.font(role))
    return canvas


def hotkey_chips(parent, kit, combination: str, bg=None):
    """A row of key-cap chips for a "ctrl+win" style combination."""
    row = tk.Frame(parent, bg=bg or _bg_of(parent))
    parts = [part.strip().upper() for part in str(combination or '').split('+') if part.strip()]
    for i, part in enumerate(parts):
        if i:
            kit.label(row, '+', 'small', 'text_faint').pack(side='left', padx=kit.px(3))
        kbd(row, kit, part).pack(side='left')
    return row


class ThinScrollbar(tk.Canvas):
    """A slim, rounded scrollbar that only shows when there is something to
    scroll. Speaks the standard Tk scrollbar protocol (set / command)."""

    def __init__(self, parent, kit, command=None, bg=None):
        self.kit = kit
        self.command = command
        self._first, self._last = 0.0, 1.0
        self._drag_from = None
        super().__init__(parent, width=kit.px(10), bg=bg or _bg_of(parent), highlightthickness=0, bd=0)
        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<Enter>', lambda e: self._draw(hover=True))
        self.bind('<Leave>', lambda e: self._draw())

    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    def _draw(self, hover=False):
        self.delete('all')
        if self._last - self._first >= 0.999:
            return
        h = self.winfo_height()
        w = self.winfo_width()
        top = int(self._first * h)
        bottom = max(top + self.kit.px(24), int(self._last * h))
        color = self.kit.p['text_faint'] if hover else self.kit.p['border_strong']
        inset = self.kit.px(2)
        self.kit.round_rect(self, inset, top, w - inset, bottom, (w - 2 * inset) // 2, color)

    def _press(self, e):
        self._drag_from = (e.y, self._first)

    def _drag(self, e):
        if self._drag_from and self.command:
            y0, first0 = self._drag_from
            h = max(1, self.winfo_height())
            self.command('moveto', first0 + (e.y - y0) / h)


class ScrollFrame(tk.Frame):
    """A vertically scrolling area. Put content in `.inner`."""

    def __init__(self, parent, kit, bg=None):
        bg = bg or _bg_of(parent)
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.kit = kit
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ThinScrollbar(self, kit, command=self.canvas.yview, bg=bg)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y', padx=(0, kit.px(2)))
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg, bd=0)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.bind('<Enter>', self._bind_wheel)
        self.bind('<Leave>', self._unbind_wheel)

    def _bind_wheel(self, _e):
        self.bind_all('<MouseWheel>', self._wheel)
        self.bind_all('<Button-4>', lambda e: self.canvas.yview_scroll(-3, 'units'))
        self.bind_all('<Button-5>', lambda e: self.canvas.yview_scroll(3, 'units'))

    def _unbind_wheel(self, _e):
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.unbind_all(seq)

    def _wheel(self, e):
        if self.canvas.yview() == (0.0, 1.0):
            return
        step = -1 * (e.delta // 120 if sys.platform == 'win32' else e.delta)
        self.canvas.yview_scroll(step * 3, 'units')

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)
