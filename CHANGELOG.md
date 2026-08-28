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

- **Split panes.** A tab holds a tree rather than one terminal: a `Gtk.Paned`
  per split, a terminal at each leaf, nesting in either direction. Moving
  between panes picks the nearest one geometrically, closing a pane hangs its
  shell up with `killpg`, and layouts persist with their divider positions.
  Sessions written before splits existed still load.
- zsh shell integration, and `install.sh` now wires whichever rc file the login
  shell actually reads. A user on zsh previously got a `~/.bashrc` that was
  never sourced, and so no OSC 7 and no notifications.
