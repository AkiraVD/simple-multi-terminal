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

- **A tab's dot says what the tab is doing: yellow working, green finished,
  red failed.** Replaces the single attention colour, and covers what used to
  be unsaid — that something is running at all. Working outranks finished and
  a failure outranks both, so one dot per tab is enough. The shell raises it at `preexec` and drops it at the
  next prompt using an `OSC 6` escape — one `printf`, measured 12 µs per
  command, against ~246 µs for the fork a helper process would cost, so it can
  afford to fire on every command where `smt-notify` could not. Claude Code's
  `UserPromptSubmit` hook raises it inside a claude session, where the shell
  sees only one long-running command, and `Stop` or a permission prompt drops
  it — so the tab is yellow exactly while Claude is writing. The tooltip names
  the program when its name travels safely in a URI, and in a split tab the dot
  speaks for whichever pane has the most to say.

  The shell only marks a command once it has reached its first prompt, and the
  marker is cleared by the *last* entry in `PROMPT_COMMAND` rather than by
  ours. Both matter, and both were found by capturing what a real bash emits on
  a pty: the `DEBUG` trap fires for the rc file's own commands, which left
  every tab yellow from launch until its first prompt, and it fires again for
  any other `PROMPT_COMMAND` entry — `history -a`, direnv, atuin — which landed
  a busy mark *after* our clear and left the tab yellow the whole time it sat
  at the prompt. An array-valued `PROMPT_COMMAND` is appended to rather than
  overwritten, which also fixes a pre-existing clobber of element zero.

  It is a dot rather than libadwaita's spinner because the spinner is animated:
  measured ~5% of a core for one tab and 7–14% for four, for as long as they
  turned, where the dot measures 0.0–0.2%, the same as an idle tab. Memory is
  unchanged either way (57 MB with four tabs, inside the noise of the version
  before it).

  `attention_color` is replaced by `color_working`, `color_done` and
  `color_error`; an old key left in config.json is ignored. New `show_activity`
  preference turns the yellow dot off on its own. Existing installs want
  `./install.sh` re-run for the hook, and a new shell for the rest.
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
