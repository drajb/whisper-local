# ui/hub.py
# The main app window, like Wispr Flow's hub: a sidebar of pages (Home,
# History, Notes, Transcribe, Dictionary, Snippets, Style, Settings, Shortcuts)
# and the selected page beside it. It runs in its own process (`--hub`,
# `--settings`, `--history` and the tray all start it), so Tk owns that
# process's main thread on every platform and the dictation engine is never
# disturbed. Only one hub runs at a time: a second launch hands its page
# request to the open window through a small file and exits.

import json
import logging
import os
import sys
import time
import tkinter as tk
from pathlib import Path

from . import theme
from .kit import new_window, Button, ScrollFrame, hotkey_chips, _bg_of

logger = logging.getLogger(__name__)

# (key, label, icon, module). Main pages, then the ones pinned to the bottom.
PAGES = (
    ('home', 'Home', 'home', 'home'),
    ('history', 'History', 'history', 'history'),
    ('notes', 'Notes', 'notes', 'notes'),
    ('transcribe', 'Transcribe', 'transcribe', 'transcribe'),
    ('dictionary', 'Dictionary', 'dictionary', 'dictionary'),
    ('snippets', 'Snippets', 'snippets', 'snippets'),
    ('style', 'Style', 'style', 'style'),
    ('settings', 'Settings', 'settings', 'settings'),
)
FOOTER_PAGES = (
    ('shortcuts', 'Shortcuts', 'keyboard', 'shortcuts'),
    ('help', 'Help & docs', 'help', 'help'),
)
PAGE_KEYS = tuple(p[0] for p in PAGES + FOOTER_PAGES)

LOCK_FILE = 'hub.lock'
REQUEST_FILE = 'hub-request.json'
REQUEST_POLL_MS = 400
WINDOW_TITLE = 'Whisper Local'


# ── Single instance ──────────────────────────────────────────────────────────

def _app_dir() -> Path:
    from ..utils import get_user_app_data_path
    path = Path(get_user_app_data_path())
    path.mkdir(parents=True, exist_ok=True)
    return path


# Whether a process with this id is still running. On Windows os.kill(pid, 0)
# would send Ctrl+C, so ask the kernel instead.
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                           # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _running_hub_pid():
    try:
        pid = int((_app_dir() / LOCK_FILE).read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and _pid_alive(pid) else None


# Entry point for every way of opening the hub. Returns a process exit code.
def open_hub(page: str = 'home') -> int:
    page = page if page in PAGE_KEYS else 'home'
    if _running_hub_pid():
        (_app_dir() / REQUEST_FILE).write_text(json.dumps({'page': page, 'at': time.time()}),
                                               encoding='utf-8')
        return 0
    lock = _app_dir() / LOCK_FILE
    lock.write_text(str(os.getpid()), encoding='utf-8')
    try:
        Hub(page).run()
    finally:
        try:
            if lock.read_text(encoding='utf-8').strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass
    return 0


# ── The window ───────────────────────────────────────────────────────────────

class Hub:
    SIDEBAR_WIDTH = 224

    def __init__(self, page: str = 'home'):
        from ..config_manager import ConfigManager
        self.cm = ConfigManager(quiet=True)
        self.root, self.kit = new_window(WINDOW_TITLE, size=(1100, 740), min_size=(900, 600))
        self.p = self.kit.p
        self._nav_items = {}
        self._current = None
        self._page = None
        self._build_shell()
        self.show(page)
        self.root.after(REQUEST_POLL_MS, self._poll_requests)
        self.root.bind('<Control-w>', lambda e: self.root.destroy())

    def run(self):
        self.root.mainloop()

    # Saves one setting through a FRESH ConfigManager, so a save never writes
    # back stale values for something another page (or the running app)
    # changed meanwhile, such as dictionary words. Three-part paths update
    # one key of a nested section. Returns True on success.
    def save(self, path: str, value) -> bool:
        from ..config_manager import ConfigManager
        try:
            cm = ConfigManager(quiet=True)
            parts = path.split('.')
            if len(parts) == 2:
                cm.update_user_setting(parts[0], parts[1], value)
            elif len(parts) == 3:
                section = dict((cm.config.get(parts[0]) or {}).get(parts[1]) or {})
                section[parts[2]] = value
                cm.update_user_setting(parts[0], parts[1], section)
            else:
                raise ValueError(f"Unsupported setting path {path}")
            self.cm = cm
            return True
        except Exception as e:
            logger.warning(f"Could not save {path}: {e}")
            self.kit.toast(self.root, f"Couldn't save: {e}", 'danger')
            return False

    def reload_config(self):
        from ..config_manager import ConfigManager
        self.cm = ConfigManager(quiet=True)

    def toast(self, text, kind='info'):
        self.kit.toast(self.root, text, kind)

    # Rebuilds the whole window, e.g. after the theme changed.
    def rebuild(self):
        current = self._current
        for child in self.root.winfo_children():
            child.destroy()
        from .kit import Kit
        self.kit = Kit(self.root)
        self.p = self.kit.p
        self.root.configure(bg=self.p['bg'])
        self.kit.apply_window_chrome(self.root)
        self._nav_items = {}
        self._current = None
        self._build_shell()
        self.show(current or 'home')

    # ── Layout ───────────────────────────────────────────────────────────

    def _build_shell(self):
        kit, p = self.kit, self.p
        self.sidebar = tk.Frame(self.root, bg=p['sidebar'], width=kit.px(self.SIDEBAR_WIDTH))
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Frame(self.root, bg=p['border'], width=max(1, kit.px(1))).pack(side='left', fill='y')
        self.content = tk.Frame(self.root, bg=p['bg'])
        self.content.pack(side='left', fill='both', expand=True)

        brand = tk.Frame(self.sidebar, bg=p['sidebar'])
        brand.pack(fill='x', padx=kit.px(18), pady=(kit.px(20), kit.px(18)))
        tk.Label(brand, image=kit.brand_mark(30), bg=p['sidebar']).pack(side='left')
        names = tk.Frame(brand, bg=p['sidebar'])
        names.pack(side='left', padx=(kit.px(10), 0))
        kit.label(names, 'Whisper Local', 'heading', bg=p['sidebar']).pack(anchor='w')
        kit.label(names, self._version_line(), 'caption', 'text_faint', bg=p['sidebar']).pack(anchor='w')

        nav = tk.Frame(self.sidebar, bg=p['sidebar'])
        nav.pack(fill='x', padx=kit.px(10))
        for key, label, icon, _ in PAGES:
            self._nav_item(nav, key, label, icon)

        footer = tk.Frame(self.sidebar, bg=p['sidebar'])
        footer.pack(side='bottom', fill='x', padx=kit.px(10), pady=(0, kit.px(14)))
        self._hotkey_hint(footer)
        for key, label, icon, _ in FOOTER_PAGES:
            self._nav_item(footer, key, label, icon)

    def _version_line(self):
        try:
            from ..utils import get_version
            return f"v{get_version()} · offline"
        except Exception:
            return 'offline'

    # The one thing every user needs to remember, always in view.
    def _hotkey_hint(self, parent):
        kit, p = self.kit, self.p
        box = tk.Frame(parent, bg=p['sidebar'])
        box.pack(fill='x', padx=kit.px(8), pady=(0, kit.px(12)))
        hk = (self.cm.config.get('hotkey') or {})
        mode = hk.get('recording_mode', 'push_to_talk')
        kit.label(box, 'Hold to dictate' if mode == 'push_to_talk' else 'Press to dictate',
                  'caption', 'text_faint', bg=p['sidebar']).pack(anchor='w', pady=(0, kit.px(6)))
        hotkey_chips(box, kit, hk.get('recording_hotkey', ''), bg=p['sidebar']).pack(anchor='w')

    def _nav_item(self, parent, key, label, icon):
        kit, p = self.kit, self.p
        height = kit.px(38)
        canvas = tk.Canvas(parent, height=height, bg=p['sidebar'], highlightthickness=0, bd=0,
                           cursor='hand2')
        canvas.pack(fill='x', pady=kit.px(1))
        state = {'hover': False}

        def draw(_e=None):
            canvas.delete('all')
            width = canvas.winfo_width()
            selected = (key == self._current)
            if selected:
                kit.round_rect(canvas, 0, 0, width, height, kit.px(9), p['accent_soft'])
            elif state['hover']:
                kit.round_rect(canvas, 0, 0, width, height, kit.px(9), p['surface_hover'])
            color = p['accent'] if selected else p['text_muted']
            canvas.create_image(kit.px(12), height // 2, image=kit.icon(icon, 18, color), anchor='w')
            canvas.create_text(kit.px(42), height // 2, text=label, anchor='w',
                               fill=p['text'] if selected else p['text_muted'],
                               font=kit.font('body_strong' if selected else 'body'))

        def hover(on):
            state['hover'] = on
            draw()
        canvas.bind('<Configure>', draw)
        canvas.bind('<Enter>', lambda e: hover(True))
        canvas.bind('<Leave>', lambda e: hover(False))
        canvas.bind('<ButtonRelease-1>', lambda e: self.show(key))
        self._nav_items[key] = draw

    # ── Pages ────────────────────────────────────────────────────────────

    def show(self, key: str):
        if key not in PAGE_KEYS:
            key = 'home'
        if key == self._current and self._page is not None:
            return
        if self._page is not None:
            try:
                self._page.on_leave()
            except Exception as e:
                logger.debug(f"Page leave failed: {e}")
            self._page.frame.destroy()
        self._current = key
        for draw in self._nav_items.values():
            draw()
        module = next(m for k, _, _, m in PAGES + FOOTER_PAGES if k == key)
        import importlib
        page_module = importlib.import_module(f'.pages.{module}', __package__)
        self.root.title(WINDOW_TITLE if key == 'home' else f"{WINDOW_TITLE} · {page_module.Page.title}")
        try:
            self._page = page_module.Page(self, self.content)
        except Exception as e:
            logger.exception(f"Page {key} failed to build")
            self._page = ErrorPage(self, self.content, key, e)
        self._page.frame.pack(fill='both', expand=True)

    # Another launch asked for a page: switch to it and come to the front.
    def _poll_requests(self):
        path = _app_dir() / REQUEST_FILE
        try:
            if path.exists():
                request = json.loads(path.read_text(encoding='utf-8') or '{}')
                path.unlink()
                self.show(request.get('page', 'home'))
                self.root.deiconify()
                self.root.lift()
                self.root.attributes('-topmost', True)
                self.root.after(250, lambda: self.root.attributes('-topmost', False))
                self.root.focus_force()
        except Exception as e:
            logger.debug(f"Hub request failed: {e}")
        self.root.after(REQUEST_POLL_MS, self._poll_requests)


class BasePage:
    """A page: a header (title, subtitle, actions) above its content.
    Subclasses set `title`/`subtitle` and implement build(body). With
    scroll=True the body scrolls; otherwise it fills the page."""

    title = ''
    subtitle = ''
    scroll = True

    def __init__(self, hub, parent):
        self.hub = hub
        self.kit = hub.kit
        self.p = hub.p
        self.config = hub.cm.config
        kit, p = self.kit, self.p
        self.frame = tk.Frame(parent, bg=p['bg'])
        header = tk.Frame(self.frame, bg=p['bg'])
        header.pack(fill='x', padx=kit.px(36), pady=(kit.px(30), kit.px(18)))
        self.actions = tk.Frame(header, bg=p['bg'])
        self.actions.pack(side='right', anchor='n')
        titles = tk.Frame(header, bg=p['bg'])
        titles.pack(side='left', fill='x', expand=True)
        kit.label(titles, self.heading(), 'display').pack(anchor='w')
        sub = self.subheading()
        if sub:
            kit.label(titles, sub, 'body', 'text_muted').pack(anchor='w', pady=(kit.px(4), 0))
        if self.scroll:
            self.scroller = ScrollFrame(self.frame, kit, bg=p['bg'])
            self.scroller.pack(fill='both', expand=True, padx=(kit.px(36), kit.px(12)))
            self.body = tk.Frame(self.scroller.inner, bg=p['bg'])
            self.body.pack(fill='both', expand=True, padx=(0, kit.px(22)), pady=(0, kit.px(30)))
        else:
            self.body = tk.Frame(self.frame, bg=p['bg'])
            self.body.pack(fill='both', expand=True, padx=kit.px(36), pady=(0, kit.px(28)))
        self.build(self.body)

    def heading(self):
        return self.title

    def subheading(self):
        return self.subtitle

    def build(self, body):
        raise NotImplementedError

    def on_leave(self):
        pass

    def action(self, text, command, variant='secondary', icon=None):
        button = Button(self.actions, self.kit, text, command, variant=variant, icon=icon)
        button.pack(side='left', padx=(self.kit.px(8), 0))
        return button

    # A titled group of rows in a card, the building block of most pages.
    def section(self, parent, title=None, description=None):
        from .kit import Card
        kit, p = self.kit, self.p
        if title:
            kit.label(parent, title, 'heading').pack(anchor='w', pady=(kit.px(10), kit.px(2)))
        if description:
            kit.label(parent, description, 'small', 'text_muted',
                      wrap=True).pack(fill='x', anchor='w', pady=(0, kit.px(6)))
        card = Card(parent, kit, padding=6)
        card.pack(fill='x', pady=(kit.px(6), kit.px(14)))
        return card.body

    # One row inside a section: label + help text on the left, a control on
    # the right. `control(parent)` builds the control. Returns the row frame.
    def row(self, section, label, help_text=None, control=None, first=False):
        kit, p = self.kit, self.p
        bg = p['surface']
        if not first and section.winfo_children():
            tk.Frame(section, bg=p['border'], height=max(1, kit.px(1))).pack(fill='x', padx=kit.px(12))
        row = tk.Frame(section, bg=bg)
        row.pack(fill='x', padx=kit.px(12), pady=kit.px(10))
        text = tk.Frame(row, bg=bg)
        text.pack(side='left', fill='x', expand=True)
        kit.label(text, label, 'body_strong', bg=bg).pack(anchor='w')
        if help_text:
            kit.label(text, help_text, 'small', 'text_muted', bg=bg,
                      wrap=True).pack(fill='x', anchor='w', pady=(kit.px(2), 0))
        if control:
            widget = control(row)
            widget.pack(side='right', padx=(kit.px(16), 0))
        return row

    # Centred illustration-free empty state.
    def empty_state(self, parent, icon, title, text):
        kit, p = self.kit, self.p
        box = tk.Frame(parent, bg=_bg_of(parent))
        box.pack(expand=True, pady=kit.px(60))
        tk.Label(box, image=kit.icon(icon, 40, p['text_faint']), bg=_bg_of(parent)).pack()
        kit.label(box, title, 'heading', anchor='center').pack(pady=(kit.px(12), kit.px(4)))
        kit.label(box, text, 'body', 'text_muted', anchor='center', justify='center',
                  wraplength=kit.px(420)).pack()
        return box


class ErrorPage(BasePage):
    title = 'Something went wrong'
    scroll = False

    def __init__(self, hub, parent, key, error):
        self._key, self._error = key, error
        super().__init__(hub, parent)

    def build(self, body):
        self.empty_state(body, 'info', f"The {self._key} page couldn't open",
                         f"{self._error}\n\nThe details are in app.log. Please report it on GitHub.")
