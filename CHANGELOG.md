# Changelog

Nothing has been tagged yet, so everything below is unreleased. Newest first.

## Unreleased

### Fixed

- **A pane could be dragged down to two columns, and the shell filled it with
  garbage.** `Gtk.Paned` only refuses to shrink a child past that child's own
  minimum, and VTE asks for 20 pixels, so a divider could squeeze a terminal to
  about two columns. Readline redraws its prompt on every `SIGWINCH`, and at
  that width the redraws pile up as fragments that stay in the scrollback long
  after the pane is widened again — `rewrap_on_resize` then repacks them into
  full-width lines, which is why the mess showed up in panes that looked
  perfectly roomy. Each leaf now asks for at least 20 columns by 4 rows,
  measured from the font's cell size so it follows a font change. Measured over
  a ~200-step drag: 32 stray prompt copies before, 1–3 after, which is what a
  bare VTE terminal leaves behind too.
- `smt -d DIR` crashed instead of opening the directory. `GOptionArg.FILENAME`
  unpacks to a list of ints, which `os.path.abspath` rejects.
- Commands are timed with `$EPOCHREALTIME` rather than `$SECONDS`, which
  truncates at both ends and let a command that ran 10.0s measure 9 and never
  notify.

### Added

- **Find in the scrollback.** `Ctrl+Shift+F` (`Cmd+F` on macOS) opens a search
  bar for the focused pane; `Enter` walks back through older matches,
  `Shift+Enter` forward, `Escape` closes. Literal text, escaped, not a regex.
  The bar is built on first use rather than at startup, and closing it clears
  the regex from every terminal in the window, so a session that never searches
  pays nothing: measured 0.00 MB until the key is pressed, then ~1.5 MB the
  first time — of which only ~0.2 MB is the search itself, the rest being GTK's
  text-input machinery, which the tab-rename dialog also pays for whichever of
  the two you open first. Searching 1,200 lines 20 times measured +0.02 MB.
  Because VTE keeps the search regex per terminal and this window has several,
  the regex is swept off all of them and set on the focused one at each step.
- **Links are clickable, without costing anything when they are not.**
  `Ctrl+click` (`Cmd+click` on macOS) opens the URL under the pointer, and
  right-clicking one offers *Open Link* and *Copy Link Address*. The URL regex
  is added for the length of a single lookup and removed again, rather than
  being attached to every terminal for the life of the process the way
  `match_add_regex` is normally used: idle mouse-motion cost measured 1.24 µs
  per event against 1.29 µs before the feature, i.e. unchanged. The trade is
  that links do not underline on hover, since nothing is watching. Only
  `http`, `https`, `ftp` and `file` URLs are opened, and never through a shell.
- **A keyboard shortcut list inside the app.** `Ctrl+?` or `F1` (`Cmd+?` or
  `Cmd+/` on macOS), the keyboard button in the header bar, or *Keyboard
  Shortcuts* in a terminal's right-click menu. The rows are built by asking the
  application which accelerators each action ended up with, so the list cannot
  drift from the bindings, and on macOS it shows the Command set without a
  second table to keep in step.
- **macOS support, and a standalone app bundle.** Re-applies the work that was
  merged in #4 and reverted in #5, unchanged apart from being rebased past the
  split-pane and prompt-garbling fixes. Every platform-specific path sits
  behind `IS_MAC`: Command-key accelerators and the eight line-editing keys VTE
  does not translate, process inspection through `ps(1)` where there is no
  `/proc`, notifications via terminal-notifier or osascript because
  GNotification has no usable Cocoa backend, and single-instance hand-off over
  the notification socket because macOS has no D-Bus session bus for
  GApplication to use. `make-app.sh` builds `~/Applications/SMT.app`. Linux
  keeps GNotification, the `.desktop` entry, the Ctrl+Shift bindings, its
  per-pid socket and its `env python3` shebang; verified by running the app
  under Xvfb, splits, tabs, `/proc` inspection and notifications included.

- **Split panes.** A tab holds a tree rather than one terminal: a `Gtk.Paned`
  per split, a terminal at each leaf, nesting in either direction. Moving
  between panes picks the nearest one geometrically, closing a pane hangs its
  shell up with `killpg`, and layouts persist with their divider positions.
  Sessions written before splits existed still load.
- zsh shell integration, and `install.sh` now wires whichever rc file the login
  shell actually reads. A user on zsh previously got a `~/.bashrc` that was
  never sourced, and so no OSC 7 and no notifications.
