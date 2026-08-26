#!/usr/bin/env python3
"""simple-multi-terminal - a small GTK4/VTE terminal.

Four features, nothing else: tabs, tab rename, notifications when something
wants your attention, and persistence of each tab's working directory.
"""
import os

# Must happen before gi imports GTK: the cairo renderer skips the GL context,
# which measured ~30MB PSS cheaper with no throughput cost.
os.environ.setdefault("GSK_RENDERER", "cairo")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, Vte  # noqa: E402

import json  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from urllib.parse import unquote, urlparse  # noqa: E402

APP_ID = "dev.phuongld.SimpleTerm"
APP_NAME = "SMT"          # what shows in the window title and task switcher
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "simple-multi-terminal")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "simple-multi-terminal")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
SESSION_PATH = os.path.join(DATA_DIR, "session.json")

DEFAULT_CONFIG = {
    "font": "Monospace 11",
    "scrollback_lines": 10000,
    # A command must run at least this long before finishing it is worth a
    # notification. Below this you were probably watching it anyway.
    "notify_min_seconds": 10,
    "notify_on_bell": True,
    "notify_on_command_done": True,
    "notify_on_claude": True,
    "restore_session": True,
    "audible_bell": False,
    "cursor_blink": True,
    "shell": None,
    "login_shell": False,
    # Colour of the dot on tabs with a pending notification.
    "attention_color": "#f6d32d",
    # When to ask before closing a tab: "busy", "always", or "never".
    "confirm_close": "busy",
    # What "busy" means. Any subset of:
    #   foreground  a command has the terminal (pytest, vim, claude)
    #   suspended   a job parked with Ctrl+Z
    #   background  anything else alive in the tab's session, incl. `cmd &`
    # Background is off by default: you detached those on purpose, and a lot
    # of ordinary programs leave helper processes lying around.
    "count_as_busy": ["foreground", "suspended"],
    "scroll_on_output": False,
    "scroll_on_keystroke": True,
}

# Solarized-ish dark. 16 ANSI colours + fg/bg.
PALETTE = [
    "#232627", "#ed1515", "#11d116", "#f67400", "#1d99f3", "#9b59b6", "#1abc9c", "#fcfcfc",
    "#7f8c8d", "#c0392b", "#1cdc9a", "#fdbc4b", "#3daee9", "#8e44ad", "#16a085", "#ffffff",
]
FG, BG = "#d8d8d8", "#1b1d1e"


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip() or "a command"
    except OSError:
        return "a command"


def monospace_only(item):
    """Filter for the font picker. GTK passes a PangoFontFamily while browsing
    families and a PangoFontFace once inside one, so handle both."""
    family = item if isinstance(item, Pango.FontFamily) else None
    if family is None and isinstance(item, Pango.FontFace):
        family = item.get_family()
    return bool(family is not None and family.is_monospace())


def dot_icon(color):
    """A filled dot as a GIcon, for the tab attention indicator.

    Built from raw bytes rather than an icon name on purpose: GTK only strips
    the colour out of icons it considers symbolic, and a GBytesIcon never is,
    so the dot stays the colour we asked for in both light and dark themes.
    """
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="%s"/></svg>' % color
    ).encode()
    return Gio.BytesIcon.new(GLib.Bytes.new(svg))


def load_json(path, fallback):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return fallback


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"smt: could not write {path}: {exc}", file=sys.stderr)


DEBUG = bool(os.environ.get("SMT_DEBUG"))


def debug(*parts):
    if DEBUG:
        print("smt:", *parts, file=sys.stderr, flush=True)


def rgba(spec):
    c = Gdk.RGBA()
    c.parse(spec)
    return c


def hexcolor(c):
    return "#%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))


class Terminal(Vte.Terminal):
    """One tab's terminal. Owns its shell, its id, and its cwd tracking."""

    def __init__(self, app, cwd=None):
        super().__init__()
        self.app = app
        self.tab_id = uuid.uuid4().hex[:12]
        self.page = None
        self.custom_title = None   # set once the user renames; locks out OSC titles
        self.osc_title = None
        self.cwd = cwd or os.path.expanduser("~")
        self.attention_reason = None
        self.child_pid = None
        self.force_close = False   # the shell already exited; nothing to confirm

        self.apply_config()
        self.set_mouse_autohide(True)
        self.set_allow_hyperlink(True)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.connect("child-exited", self._on_child_exited)
        self.connect("bell", self._on_bell)
        self.connect("window-title-changed", self._on_osc_title)
        self.connect("current-directory-uri-changed", self._on_cwd_changed)
        self.connect("setup-context-menu", self._on_context_menu)

        self._spawn()

    # ---- settings --------------------------------------------------------
    def apply_config(self):
        """Push the current config onto this terminal. Called at construction
        and again whenever preferences change, so there is one place that
        knows how a setting maps onto VTE."""
        cfg = self.app.config
        self.set_scrollback_lines(int(cfg["scrollback_lines"]))
        self.set_font(Pango.FontDescription(cfg["font"]))
        self.set_colors(rgba(FG), rgba(BG), [rgba(c) for c in PALETTE])
        self.set_audible_bell(bool(cfg["audible_bell"]))
        self.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if cfg["cursor_blink"] else Vte.CursorBlinkMode.OFF
        )
        self.set_scroll_on_output(bool(cfg["scroll_on_output"]))
        self.set_scroll_on_keystroke(bool(cfg["scroll_on_keystroke"]))
        # Recolouring the dot only shows up on tabs currently wearing one.
        if self.attention_reason and self.page:
            self.page.set_indicator_icon(self.app.attention_icon)

    # ---- shell -----------------------------------------------------------
    def _child_env(self):
        env = dict(os.environ)
        # Don't force our renderer choice onto GUI apps launched from the shell.
        env.pop("GSK_RENDERER", None)
        env.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "SMT_TAB_ID": self.tab_id,
            "SMT_SOCKET": self.app.socket_path,
            "SMT_NOTIFY_MIN_SECONDS": str(self.app.config["notify_min_seconds"]),
        })
        return [f"{k}={v}" for k, v in env.items()]

    def _spawn(self):
        shell = self.app.config["shell"] or os.environ.get("SHELL") or "/bin/bash"
        cwd = self.cwd if os.path.isdir(self.cwd) else os.path.expanduser("~")
        argv = [shell, "-l"] if self.app.config["login_shell"] else [shell]
        self.spawn_async(
            Vte.PtyFlags.DEFAULT, cwd, argv, self._child_env(),
            GLib.SpawnFlags.DEFAULT, None, None, -1, None, self._spawned, None,
        )

    def _spawned(self, terminal, pid, error, _data):
        self.child_pid = pid
        if error:
            self.feed(f"\r\n\x1b[31mFailed to start shell: {error.message}\x1b[0m\r\n".encode())

    def _on_child_exited(self, _term, _status):
        self.child_pid = None
        self.app.window.close_terminal(self)

    # ---- busy state ------------------------------------------------------
    def _session_processes(self):
        """Every process sharing this tab's session, minus the shell itself.

        The session id is the shell's pid: VTE gives each tab its own pty and
        makes the shell the session leader, so this is exactly "things living
        in this tab" — and it is the same grouping the kernel would SIGHUP if
        the tab went away.
        """
        found = []
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == self.child_pid:
                continue
            try:
                with open(f"/proc/{name}/stat") as fh:
                    line = fh.read()
                # comm sits in parens and may itself contain spaces or parens,
                # so split around the last ')' rather than on whitespace.
                head = line.rindex(")")
                comm = line[line.index("(") + 1:head]
                fields = line[head + 2:].split()
                state, session = fields[0], int(fields[3])
            except (OSError, ValueError, IndexError):
                continue
            if session == self.child_pid:
                found.append((int(name), comm, state))
        return found

    def busy(self):
        """What is running in this tab, as (kind, command), or None if idle.

        Checked in order of how much the user would mind losing it.
        """
        if self.child_pid is None:
            return None
        counts = self.app.config["count_as_busy"]

        if "foreground" in counts:
            # The kernel already tracks this: the pty's foreground process
            # group is the shell itself when nothing is running.
            pty = self.get_pty()
            if pty:
                try:
                    fg = os.tcgetpgrp(pty.get_fd())
                except OSError:
                    fg = -1
                if fg > 0 and fg != self.child_pid:
                    return "foreground", _comm(fg)

        if not ("suspended" in counts or "background" in counts):
            return None

        procs = self._session_processes()
        if "suspended" in counts:
            for pid, comm, state in procs:
                if state == "T":
                    return "suspended", comm or _comm(pid)
        if "background" in counts and procs:
            return "background", procs[0][1] or _comm(procs[0][0])
        return None

    # ---- title / cwd -----------------------------------------------------
    def display_title(self):
        if self.custom_title:
            return self.custom_title
        if self.osc_title:
            return self.osc_title
        return os.path.basename(self.cwd.rstrip("/")) or "/"

    def refresh_title(self):
        if self.page:
            self.page.set_title(self.display_title())
            self.page.set_tooltip(self.cwd)
        window = self.app.window
        if window and window.current_terminal() is self:
            window.set_title(f"{self.display_title()} — {APP_NAME}")

    def _on_osc_title(self, _t):
        title = (self.get_window_title() or "").strip()
        # Shells set the title to "user@host:dir" by default, which is noise.
        self.osc_title = title if title and "@" not in title else None
        self.refresh_title()

    def _on_cwd_changed(self, _t):
        uri = self.get_current_directory_uri()
        if uri:
            self.cwd = unquote(urlparse(uri).path) or self.cwd
            self.refresh_title()
            self.app.schedule_session_save()

    def _on_context_menu(self, _t, _ctx):
        menu = Gio.Menu()
        menu.append("Copy", "win.copy")
        menu.append("Paste", "win.paste")
        section = Gio.Menu()
        section.append("Rename Tab…", "win.rename-tab")
        section.append("New Tab", "win.new-tab")
        menu.append_section(None, section)
        self.set_context_menu_model(menu)
        return False

    # ---- attention ------------------------------------------------------
    def set_attention(self, on, reason=None):
        """Flag or clear this tab's pending notification.

        Two indicators, because they are visible in different situations:
        libadwaita's own needs-attention glow, which is easy to miss on a wide
        tab bar, plus a coloured dot in the tab so it reads at a glance from
        whichever tab you happen to be on.
        """
        pending = self.attention_reason is not None
        self.attention_reason = reason if on else None
        if not self.page:
            return
        self.page.set_needs_attention(on)
        self.page.set_indicator_icon(self.app.attention_icon if on else None)
        self.page.set_indicator_tooltip(reason or "")
        if pending and not on:
            # Drop the desktop notification still sitting in the shell's tray;
            # you have looked at the tab, so it has done its job.
            self.app.withdraw_notification(f"smt-{self.tab_id}")

    def _on_bell(self, _t):
        if self.app.config["notify_on_bell"]:
            self.app.notify_tab(self, "Bell", self.display_title())


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_default_size(960, 640)

        self.tabview = Adw.TabView()
        self.tabview.connect("close-page", self._on_close_page)
        self.tabview.connect("notify::selected-page", self._on_page_switched)
        self.tabview.connect("setup-menu", self._on_setup_menu)
        self._menu_page = None
        self._close_confirmed = False   # set once the user okays closing the window
        self._close_asking = False

        tabbar = Adw.TabBar(view=self.tabview, autohide=False, expand_tabs=False)

        new_btn = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="New Tab (Ctrl+Shift+T)")
        new_btn.set_action_name("win.new-tab")
        prefs_btn = Gtk.Button(icon_name="emblem-system-symbolic",
                               tooltip_text="Preferences (Ctrl+,)")
        prefs_btn.set_action_name("win.preferences")
        header = Adw.HeaderBar()
        header.pack_start(new_btn)
        header.pack_end(prefs_btn)
        tabbar.set_start_action_widget(Gtk.Box())

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(tabbar)
        toolbar.set_content(self.tabview)
        self.set_content(toolbar)

        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close_request)
        self._install_actions()

    # ---- actions / shortcuts --------------------------------------------
    def _install_actions(self):
        specs = [
            ("new-tab",     self.action_new_tab,     ["<Control><Shift>t"]),
            ("close-tab",   self.action_close_tab,   ["<Control><Shift>w"]),
            ("rename-tab",  self.action_rename_tab,  ["<Control><Shift>r", "F2"]),
            ("preferences",  self.action_preferences, ["<Control>comma"]),
            ("copy",        self.action_copy,        ["<Control><Shift>c"]),
            ("paste",       self.action_paste,       ["<Control><Shift>v"]),
            ("next-tab",    self.action_next_tab,    ["<Control>Page_Down", "<Control><Shift>Right"]),
            ("prev-tab",    self.action_prev_tab,    ["<Control>Page_Up", "<Control><Shift>Left"]),
            ("zoom-in",     self.action_zoom_in,     ["<Control>plus", "<Control>equal"]),
            ("zoom-out",    self.action_zoom_out,    ["<Control>minus"]),
            ("zoom-reset",  self.action_zoom_reset,  ["<Control>0"]),
        ]
        for name, cb, accels in specs:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            self.app.set_accels_for_action(f"win.{name}", accels)

        # Alt+1..9 jumps to a tab.
        goto = Gio.SimpleAction.new("goto-tab", GLib.VariantType.new("i"))
        goto.connect("activate", self.action_goto_tab)
        self.add_action(goto)
        for i in range(1, 10):
            self.app.set_accels_for_action(f"win.goto-tab({i})", [f"<Alt>{i}"])

    def action_new_tab(self, *_):
        cur = self.current_terminal()
        self.add_tab(cwd=cur.cwd if cur else None)

    def action_preferences(self, *_):
        Preferences(self.app).present(self)

    def action_close_tab(self, *_):
        page = self.tabview.get_selected_page()
        if page:
            self.tabview.close_page(page)

    def action_copy(self, *_):
        t = self.current_terminal()
        if t and t.get_has_selection():
            t.copy_clipboard_format(Vte.Format.TEXT)

    def action_paste(self, *_):
        t = self.current_terminal()
        if t:
            t.paste_clipboard()

    def action_next_tab(self, *_):
        self.tabview.select_next_page()

    def action_prev_tab(self, *_):
        self.tabview.select_previous_page()

    def action_goto_tab(self, _a, param):
        idx = param.get_int32() - 1
        if 0 <= idx < self.tabview.get_n_pages():
            self.tabview.set_selected_page(self.tabview.get_nth_page(idx))

    def _zoom(self, delta):
        t = self.current_terminal()
        if t:
            t.set_font_scale(min(4.0, max(0.4, t.get_font_scale() + delta)))

    def action_zoom_in(self, *_):
        self._zoom(0.1)

    def action_zoom_out(self, *_):
        self._zoom(-0.1)

    def action_zoom_reset(self, *_):
        t = self.current_terminal()
        if t:
            t.set_font_scale(1.0)

    # ---- tabs ------------------------------------------------------------
    def add_tab(self, cwd=None, title=None, select=True):
        term = Terminal(self.app, cwd=cwd)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(term)
        page = self.tabview.append(scroller)
        term.page = page
        page.smt_terminal = term
        if title:
            term.custom_title = title
        term.refresh_title()
        if select:
            self.tabview.set_selected_page(page)
            term.grab_focus()
        return term

    def terminals(self):
        out = []
        for i in range(self.tabview.get_n_pages()):
            term = getattr(self.tabview.get_nth_page(i), "smt_terminal", None)
            if term:
                out.append(term)
        return out

    def current_terminal(self):
        page = self.tabview.get_selected_page()
        return getattr(page, "smt_terminal", None) if page else None

    def close_terminal(self, term):
        # Only reached when the shell itself exited, so there is nothing left
        # to ask about.
        term.force_close = True
        if term.page:
            self.tabview.close_page(term.page)

    # ---- closing ---------------------------------------------------------
    BUSY_PHRASE = {
        "foreground": "is still running {cmd}",
        "suspended":  "has {cmd} suspended",
        "background": "still has {cmd} running in the background",
    }

    def _confirm(self, heading, body, confirm_label, done):
        """Ask before something irreversible. Cancel is the default response,
        so Enter and Escape both back out."""
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("close", confirm_label)
        dialog.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: done(response == "close"))
        dialog.present(self)

    def _on_close_page(self, tabview, page):
        term = getattr(page, "smt_terminal", None)
        mode = self.app.config["confirm_close"]
        busy = term.busy() if term else None
        ask = (
            term is not None
            and not term.force_close
            and mode != "never"
            and (mode == "always" or busy is not None)
        )
        if not ask:
            self._finish_close(page, True)
            return True

        # AdwTabView lets the close run asynchronously: the page sits in a
        # closing state until close_page_finish, which is what makes a dialog
        # here possible at all.
        name = term.display_title()
        if busy:
            kind, cmd = busy
            body = (f"“{name}” {self.BUSY_PHRASE[kind].format(cmd=cmd)}. "
                    "Closing the tab kills it.")
        else:
            body = f"Close “{name}”?"
        self._confirm("Close Tab?", body, "Close Tab",
                      lambda ok: self._finish_close(page, ok))
        return True

    def _finish_close(self, page, closed):
        self.tabview.close_page_finish(page, closed)
        if not closed:
            term = self.current_terminal()
            if term:
                term.grab_focus()
            return
        self.app.schedule_session_save()
        if self.tabview.get_n_pages() == 0:
            self.close()

    def _on_page_switched(self, *_):
        page = self.tabview.get_selected_page()
        if not page:
            return
        term = getattr(page, "smt_terminal", None)
        if term:
            term.set_attention(False)
            term.grab_focus()
            term.refresh_title()

    def _on_setup_menu(self, _tv, page):
        self._menu_page = page

    def _on_active_changed(self, *_):
        # Clear the badge on the visible tab once the window regains focus.
        if self.is_active():
            term = self.current_terminal()
            if term:
                term.set_attention(False)

    def _on_close_request(self, *_):
        mode = self.app.config["confirm_close"]
        if not self._close_confirmed and mode != "never":
            if self._close_asking:
                return True   # dialog already up; ignore the second click
            busy = [
                (t.display_title(), state)
                for t in self.terminals()
                if (state := t.busy())
            ]
            count = self.tabview.get_n_pages()
            if busy or (mode == "always" and count > 1):
                if busy:
                    shown = "\n".join(
                        f"• {name} — {cmd}" + (" (suspended)" if kind == "suspended" else "")
                        for name, (kind, cmd) in busy[:6]
                    )
                    extra = f"\n… and {len(busy) - 6} more" if len(busy) > 6 else ""
                    body = (f"Still running:\n{shown}{extra}\n\n"
                            "Closing the window kills them.")
                else:
                    body = f"Close all {count} tabs?"
                self._close_asking = True
                self._confirm("Close Window?", body, "Close Window",
                              self._window_close_answered)
                return True
        self.app.save_session()
        return False

    def _window_close_answered(self, ok):
        self._close_asking = False
        if not ok:
            term = self.current_terminal()
            if term:
                term.grab_focus()
            return
        self._close_confirmed = True
        self.close()

    # ---- rename ----------------------------------------------------------
    def action_rename_tab(self, *_):
        page = self._menu_page or self.tabview.get_selected_page()
        self._menu_page = None
        term = getattr(page, "smt_terminal", None) if page else None
        if not term:
            return

        entry = Gtk.Entry(text=term.display_title(), activates_default=True)
        dialog = Adw.AlertDialog(
            heading="Rename Tab",
            body="Leave empty to go back to the automatic title.",
            extra_child=entry,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def done(_d, response):
            if response == "rename":
                name = entry.get_text().strip()
                term.custom_title = name or None
                term.refresh_title()
                self.app.schedule_session_save()
            term.grab_focus()

        dialog.connect("response", done)
        dialog.present(self)


class Preferences(Adw.PreferencesDialog):
    """Every config key, editable. Changes save and take effect immediately;
    the two that cannot (shell, login shell) say so in their subtitle."""

    BUSY_KINDS = [
        ("foreground", "Foreground command",
         "Something has the terminal: pytest, vim, claude"),
        ("suspended", "Suspended job", "Parked with Ctrl+Z"),
        # Row subtitles are parsed as Pango markup, so the ampersand needs
        # escaping or the whole subtitle silently fails to render.
        ("background", "Background process",
         "Anything else alive in the tab, including cmd &amp;"),
    ]
    CONFIRM = [("busy", "Only when the tab is busy"), ("always", "Always"), ("never", "Never")]

    def __init__(self, app):
        super().__init__(title="Preferences", content_width=520)
        self.app = app
        self.rows = {}          # config key -> row, so the whole dialog is addressable
        page = Adw.PreferencesPage()
        self.add(page)

        appearance = Adw.PreferencesGroup(title="Appearance")
        page.add(appearance)
        appearance.add(self._font_row())
        self._spin(appearance, "scrollback_lines", "Scrollback", 0, 1_000_000, 1000,
                   "Lines kept per tab. Allocated lazily, so a big number costs "
                   "nothing until you use it.")
        self._switch(appearance, "cursor_blink", "Blinking cursor")

        scrolling = Adw.PreferencesGroup(title="Scrolling")
        page.add(scrolling)
        self._switch(scrolling, "scroll_on_output", "Scroll on output",
                     "Jump to the bottom whenever a command prints")
        self._switch(scrolling, "scroll_on_keystroke", "Scroll on keystroke",
                     "Jump to the bottom when you start typing")

        notify = Adw.PreferencesGroup(
            title="Notifications",
            description="A tab only notifies when it is not the one you are looking at.",
        )
        page.add(notify)
        self._switch(notify, "notify_on_claude", "Claude Code",
                     "Needs input, or finished responding")
        self._switch(notify, "notify_on_command_done", "Finished commands")
        self._spin(notify, "notify_min_seconds", "Minimum duration", 0, 3600, 5,
                   "Seconds a command must run before finishing is worth a notification")
        self._switch(notify, "notify_on_bell", "Terminal bell")
        self._switch(notify, "audible_bell", "Play the bell sound")
        notify.add(self._color_row())

        closing = Adw.PreferencesGroup(title="Closing a tab")
        page.add(closing)
        self.confirm_row = self._combo(closing, "confirm_close", "Ask first", self.CONFIRM)
        self.busy_row = Adw.ExpanderRow(
            title="What counts as busy",
            subtitle="Checked against the processes living in the tab",
        )
        closing.add(self.busy_row)
        self.rows["count_as_busy"] = self.busy_row
        for key, title, subtitle in self.BUSY_KINDS:
            self.busy_row.add_row(self._busy_switch(key, title, subtitle))
        self._sync_busy_sensitivity()

        shell = Adw.PreferencesGroup(
            title="Shell", description="Takes effect in tabs you open from now on."
        )
        page.add(shell)
        shell.add(self._shell_row())
        self._switch(shell, "login_shell", "Login shell", "Run the shell with -l")
        self._switch(shell, "restore_session", "Restore tabs on launch",
                     "Reopen tabs in the directories you left them")

    # ---- row builders ----------------------------------------------------
    def _switch(self, group, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title, subtitle=subtitle or "",
                            active=bool(self.app.config[key]))
        row.connect("notify::active",
                    lambda r, _p: self.app.set_config(key, r.get_active()))
        group.add(row)
        self.rows[key] = row
        return row

    def _spin(self, group, key, title, low, high, step, subtitle=None):
        adj = Gtk.Adjustment(lower=low, upper=high, step_increment=step,
                             page_increment=step * 10,
                             value=float(self.app.config[key]))
        row = Adw.SpinRow(title=title, subtitle=subtitle or "", adjustment=adj)
        row.connect("notify::value",
                    lambda r, _p: self.app.set_config(key, int(r.get_value())))
        group.add(row)
        self.rows[key] = row
        return row

    def _combo(self, group, key, title, choices):
        values = [v for v, _ in choices]
        current = self.app.config[key]
        row = Adw.ComboRow(
            title=title,
            model=Gtk.StringList.new([label for _, label in choices]),
            selected=values.index(current) if current in values else 0,
        )

        def changed(r, _p):
            self.app.set_config(key, values[r.get_selected()])
            self._sync_busy_sensitivity()

        row.connect("notify::selected", changed)
        group.add(row)
        self.rows[key] = row
        return row

    def _busy_switch(self, kind, title, subtitle):
        row = Adw.SwitchRow(title=title, subtitle=subtitle,
                            active=kind in self.app.config["count_as_busy"])

        def toggled(r, _p):
            counts = [k for k, _t, _s in self.BUSY_KINDS
                      if (r.get_active() if k == kind
                          else k in self.app.config["count_as_busy"])]
            self.app.set_config("count_as_busy", counts)

        row.connect("notify::active", toggled)
        self.rows[f"count_as_busy:{kind}"] = row
        return row

    def _sync_busy_sensitivity(self):
        # Nothing to configure if closing never asks, or always does.
        self.busy_row.set_sensitive(self.app.config["confirm_close"] == "busy")

    def _font_row(self):
        dialog = Gtk.FontDialog()
        # Proportional fonts in a terminal are a mistake the picker can prevent.
        dialog.set_filter(Gtk.CustomFilter.new(monospace_only))
        button = Gtk.FontDialogButton(dialog=dialog, valign=Gtk.Align.CENTER,
                                      level=Gtk.FontLevel.FONT)
        button.set_font_desc(Pango.FontDescription(self.app.config["font"]))
        button.connect("notify::font-desc", lambda b, _p: self.app.set_config(
            "font", b.get_font_desc().to_string()))
        row = Adw.ActionRow(title="Font", subtitle="Monospace families only")
        row.add_suffix(button)
        row.set_activatable_widget(button)
        self.rows["font"] = row
        return row

    def _color_row(self):
        button = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
            rgba=rgba(self.app.config["attention_color"]),
        )
        button.connect("notify::rgba", lambda b, _p: self.app.set_config(
            "attention_color", hexcolor(b.get_rgba())))
        row = Adw.ActionRow(title="Attention dot",
                            subtitle="Marks tabs with a pending notification")
        row.add_suffix(button)
        row.set_activatable_widget(button)
        self.rows["attention_color"] = row
        return row

    def _shell_row(self):
        row = Adw.EntryRow(title="Command", show_apply_button=True,
                           text=self.app.config["shell"] or "")
        row.connect("apply", lambda r: self.app.set_config(
            "shell", r.get_text().strip() or None))
        self.rows["shell"] = row
        return row


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.config = {**DEFAULT_CONFIG, **load_json(CONFIG_PATH, {})}
        self.attention_icon = dot_icon(self.config["attention_color"])
        self.window = None
        self.socket_path = os.path.join(
            GLib.get_user_runtime_dir(), f"smt-{os.getpid()}.sock"
        )
        self._service = None
        self._save_source = 0
        self.add_main_option(
            "working-directory", ord("d"), GLib.OptionFlags.NONE,
            GLib.OptionArg.FILENAME, "Open the first tab here", "DIR",
        )

    # ---- lifecycle -------------------------------------------------------
    def do_command_line(self, command_line):
        opts = command_line.get_options_dict().end().unpack()
        self.activate()
        cwd = opts.get("working-directory")
        if cwd:
            self.window.add_tab(cwd=os.path.abspath(cwd))
        return 0

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        if not os.path.exists(CONFIG_PATH):
            save_json(CONFIG_PATH, DEFAULT_CONFIG)
        self._start_socket()
        for sig in (__import__("signal").SIGTERM, __import__("signal").SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)
        self.window = Window(self)
        self._restore_session()
        self.window.present()

    def _on_signal(self):
        debug("signal received, shutting down cleanly")
        self.save_session()
        self._cleanup_socket()
        self.quit()
        return GLib.SOURCE_REMOVE

    def _cleanup_socket(self):
        if self._service:
            self._service.stop()
            self._service.close()
            self._service = None
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def do_shutdown(self):
        self.save_session()
        self._cleanup_socket()
        Adw.Application.do_shutdown(self)

    # ---- settings --------------------------------------------------------
    def set_config(self, key, value):
        """Single funnel for a preference change: store, apply, persist."""
        if self.config.get(key) == value:
            return
        self.config[key] = value
        debug("config", key, "=", value)
        if key == "attention_color":
            self.attention_icon = dot_icon(value)
        if self.window:
            for term in self.window.terminals():
                term.apply_config()
        save_json(CONFIG_PATH, self.config)

    # ---- session ---------------------------------------------------------
    def _restore_session(self):
        tabs = []
        if self.config["restore_session"]:
            tabs = load_json(SESSION_PATH, {}).get("tabs", [])
        for tab in tabs:
            cwd = tab.get("cwd")
            if cwd and os.path.isdir(cwd):
                self.window.add_tab(cwd=cwd, title=tab.get("title"), select=False)
        if self.window.tabview.get_n_pages() == 0:
            self.window.add_tab()
        else:
            first = self.window.tabview.get_nth_page(0)
            self.window.tabview.set_selected_page(first)

    def schedule_session_save(self):
        # cwd changes on every prompt; debounce so we aren't writing constantly.
        if self._save_source:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add_seconds(2, self._save_session_now)

    def _save_session_now(self):
        self._save_source = 0
        self.save_session()
        return False

    def save_session(self):
        if not self.window:
            return
        tabs = [
            {"cwd": t.cwd, "title": t.custom_title}
            for t in self.window.terminals()
        ]
        save_json(SESSION_PATH, {"tabs": tabs})

    # ---- notifications ---------------------------------------------------
    def _sweep_stale_sockets(self):
        """Remove sockets from instances that were killed instead of closed."""
        runtime = GLib.get_user_runtime_dir()
        try:
            names = os.listdir(runtime)
        except OSError:
            return
        for name in names:
            if not (name.startswith("smt-") and name.endswith(".sock")):
                continue
            try:
                pid = int(name[4:-5])
            except ValueError:
                continue
            if pid == os.getpid():
                continue
            if os.path.isdir(f"/proc/{pid}"):
                continue  # still running
            try:
                os.unlink(os.path.join(runtime, name))
                debug("swept stale socket", name)
            except OSError:
                pass

    def _start_socket(self):
        self._sweep_stale_sockets()
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        self._service = Gio.SocketService.new()
        try:
            self._service.add_address(
                Gio.UnixSocketAddress.new(self.socket_path),
                Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None,
            )
        except GLib.Error as exc:
            print(f"smt: notification socket unavailable: {exc.message}", file=sys.stderr)
            return
        self._service.connect("incoming", self._on_socket_incoming)
        self._service.start()

    def _on_socket_incoming(self, _svc, connection, _src):
        stream = Gio.DataInputStream.new(connection.get_input_stream())
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_socket_line, connection)
        return True

    def _on_socket_line(self, stream, result, connection):
        try:
            line, _ = stream.read_line_finish(result)
        except GLib.Error:
            line = None
        if line:
            try:
                self._handle_message(json.loads(bytes(line).decode()))
            except (ValueError, UnicodeDecodeError):
                pass
        try:
            connection.close(None)
        except GLib.Error:
            pass

    def _find_terminal(self, tab_id):
        if not self.window:
            return None
        for term in self.window.terminals():
            if term.tab_id == tab_id:
                return term
        return None

    def _handle_message(self, msg):
        debug("recv", msg)
        term = self._find_terminal(msg.get("tab_id", ""))
        if not term:
            debug("no terminal for tab_id", msg.get("tab_id"))
            return
        kind = msg.get("kind")

        if kind == "command-done":
            if not self.config["notify_on_command_done"]:
                return
            secs = float(msg.get("seconds", 0))
            code = int(msg.get("exit_code", 0))
            cmd = (msg.get("command") or "").strip()[:60]
            mark = "✓" if code == 0 else f"✗ exit {code}"
            self.notify_tab(term, f"{mark}  {cmd or 'command'}", f"finished in {secs:.0f}s")

        elif kind == "claude-waiting":
            if self.config["notify_on_claude"]:
                body = msg.get("message") or "Claude is waiting for you"
                self.notify_tab(term, "Claude needs input", body)

        elif kind == "claude-done":
            if self.config["notify_on_claude"]:
                self.notify_tab(term, "Claude finished", msg.get("message") or "Response complete")

        elif kind == "clear":
            term.set_attention(False)

    def notify_tab(self, term, title, body):
        """Badge the tab, and raise a desktop notification if it isn't visible."""
        focused = (
            self.window
            and self.window.is_active()
            and self.window.current_terminal() is term
        )
        debug("notify", title, "|", body, "focused=", focused)
        if focused:
            return
        term.set_attention(True, f"{title} — {body}")

        notification = Gio.Notification.new(title)
        notification.set_body(f"{term.display_title()} — {body}")
        notification.set_priority(Gio.NotificationPriority.NORMAL)
        self.send_notification(f"smt-{term.tab_id}", notification)


def main():
    # GDK/Wayland takes the toplevel app_id from g_get_prgname(), NOT from the
    # GApplication id. Left alone it would be "smt", so GNOME would look for
    # smt.desktop, fail to match our entry, and label the window generically.
    # Must be set before GApplication.run(), which otherwise fills it from argv[0].
    GLib.set_prgname(APP_ID)
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
