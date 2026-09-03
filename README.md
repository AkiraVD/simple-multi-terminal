# simple-multi-terminal

A small GTK4/VTE terminal for claude code that does five things and nothing
else. Runs on Linux and on macOS.

- **Multiple tabs**
- **Split panes** — several terminals side by side in one tab
- **Tab rename**
- **Notifications** when Claude Code wants your input, or a long command finishes in a background tab
- **Persistent project paths** — tabs come back in the directories you left them

![SMT with three tabs open: "api", "web" and "dotfiles". The api tab wears a
yellow dot because Claude Code is waiting on it.](docs/screenshot.png)

*The yellow dot on `api` is Claude Code asking for something while you work in
`web`.*

Measured on Ubuntu 24.04 / GNOME 46: **49.9 MB total (PSS) with 8 tabs open**,
including the eight bash processes. For scale, VS Code's main process alone
measures 115 MB on the same machine.

## Install

Linux:

```bash
sudo apt install gir1.2-vte-3.91 gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi
./install.sh
```

macOS:

```bash
brew install gtk4 libadwaita vte3 pygobject3 adwaita-icon-theme
brew install terminal-notifier   # optional, see below
./install.sh
```

`install.sh` is idempotent. It installs `smt` and `smt-notify` into
`~/.local/bin`, appends one line to the rc file of your login shell
(`~/.zshrc` or `~/.bashrc`), and adds three hooks to `~/.claude/settings.json`
(backing up the existing file first). On Linux it also adds a desktop entry,
on macOS an app bundle. It pins the installed `smt`'s shebang to whichever
python actually has the GI bindings, which on macOS is Homebrew's rather than
the system one. Then:

```bash
smt
```

Open a new tab or `source ~/.bashrc` for the shell integration to take effect.

## Opening it as an app

Started as `smt`, the terminal is a child of whatever terminal you typed that
in: close the parent and you take the tabs down with it. On macOS `install.sh`
also builds `~/Applications/SMT.app`, which opens from Spotlight, the Dock and
Launchpad like any other app and belongs to no other terminal:

```bash
./make-app.sh          # install.sh already did this; this rebuilds it
open -a SMT
```

Both routes reach the same instance — see [One window](#one-window) — so a
`smt` typed in a shell raises the window the app opened, and vice versa.

Getting the app to be an app takes one trick. A framework python is a stub
that re-execs the interpreter inside Python's *own* bundle, and macOS names a
process after the image it ends up running, so the Dock, the menu bar and
Cmd+Tab would all say "Python". The bundle therefore carries its own copy of
the real interpreter, under the app's name, with a `pyvenv.cfg` next to it —
the same mechanism a virtualenv uses — so nothing ever leaves the bundle.

Finder also hands an app almost no environment. The launcher puts Homebrew
back on `PATH` and falls back to your login shell from the account record when
`SHELL` is unset, which is why a tab opened from Spotlight still gets zsh and
still finds `terminal-notifier`.

On Linux the desktop entry does the same job, and `make-app.sh` is not used.

## Keys

|                       | macOS also            |                     |
| --------------------- | --------------------- | ------------------- |
| `Ctrl+Shift+T`        | `Cmd+T`               | new tab             |
| `Ctrl+Shift+W`        | `Cmd+W`               | close tab (asks if busy) |
| `Ctrl+Shift+R` / `F2` | `Cmd+Shift+R`         | rename tab          |
| `Ctrl+Shift+C` / `V`  | `Cmd+C` / `Cmd+V`     | copy / paste        |
| `Ctrl+Shift+F`        | `Cmd+F`               | find in the scrollback |
| `Ctrl+PageUp/Down`    | `Cmd+Shift+[` / `]`   | previous / next tab |
| `Alt+1`…`Alt+9`       | `Cmd+1`…`Cmd+9`       | jump to tab         |
| `Ctrl+±` / `Ctrl+0`   | `Cmd+±` / `Cmd+0`     | font size           |
| `Ctrl+,`              | `Cmd+,`               | preferences         |
| `Ctrl+?` / `F1`       | `Cmd+?` / `Cmd+/`     | this list, in the app |
| `Ctrl+click` a link   | `Cmd+click`           | open it in your browser |
| `Ctrl+Shift+D`        | `Cmd+D`               | split right         |
| `Ctrl+Shift+E`        | `Cmd+Shift+D`         | split down          |
| `Ctrl+Shift+X`        | `Cmd+Shift+W`         | close pane          |
| `Alt+←↑↓→`            | `Cmd+Option+←↑↓→`     | move between panes  |

`Ctrl+Shift+F` searches the scrollback of the pane you are in. `Enter` walks
backwards through older matches and `Shift+Enter` forwards, because the
viewport sits at the newest output when the bar opens and searching forwards
from there would wrap straight to the oldest match in the buffer. `Escape`
closes the bar and hands the keyboard back to the terminal. The search is
literal, not a regex — the text you type is escaped.

The bar is built the first time you press the key, and the regex is taken back
off every terminal when you close it, so a session that never searches carries
none of it. Opening it for the first time costs ~1.5 MB, almost all of which is
GTK's text-input machinery: the same cost the rename dialog pays, so whichever
you use first pays it and the other is then ~0.2 MB.

Right-clicking a link offers *Open Link* and *Copy Link Address*, and the two
appear only when the click actually landed on one. Links are matched at the
moment you click and forgotten immediately: a match regex left attached makes
VTE test every mouse-motion event over every pane for as long as the process
lives, which is a standing cost for a feature used a few times a day. Nothing
underlines on hover, and that is the trade — hovering costs the same as it did
before links existed (measured: 1.24 vs 1.29 µs per motion event). Only
`http`, `https`, `ftp` and `file` are opened, since an OSC 8 hyperlink carries
whatever scheme the program that printed it chose, and the URL is passed as
one argv entry, never through a shell.

The keyboard button in the header bar opens the same list, and so does
*Keyboard Shortcuts* in a terminal's right-click menu. It is generated from the
bindings the window actually installs, so it shows the platform's own set
rather than a copy of this table.

On macOS both sets are live. The Command bindings exist because `Alt+digit`
types an accented character on a Mac keyboard, and because `Cmd` collides with
nothing the shell wants — `Ctrl+C` in a tab stays `Ctrl+C`.

The pane keys are the exception to "both sets are live": on macOS the plain
`Alt+arrow` bindings are dropped rather than added, because Option+arrow is a
line-editing key inside the tab (below) and an accelerator would win first.

On Linux they are not dropped, so `Alt+←→` and `Alt+↑↓` are window
accelerators there and no longer reach the shell or a full-screen program
inside a tab.

Tabs also rename from the right-click menu, and drag to reorder. Splitting is
also in the right-click menu.

### Line editing on macOS

VTE sends Cmd and Option straight to the shell, so out of the box `Cmd+Delete`
erases one character and `Option+Left` does nothing — the translation into
control sequences is the emulator's job, and Terminal.app and iTerm2 are the
ones normally doing it. On macOS these eight keys are translated to the
sequences readline and zle already bind:

| Key               | Does                        | Sends      |
| ----------------- | --------------------------- | ---------- |
| `Cmd+Delete`      | delete to start of line     | `Ctrl+U`   |
| `Cmd+fn+Delete`   | delete to end of line       | `Ctrl+K`   |
| `Option+Delete`   | delete the word behind      | `Esc Del`  |
| `Option+fn+Delete`| delete the word ahead       | `Esc d`    |
| `Option+←` / `→`  | move a word at a time       | `Esc b/f`  |
| `Cmd+←` / `→`     | start / end of line         | `Ctrl+A/E` |

Everything else passes through untouched, `Option`+letter included, so
composing accented characters still works.

## Splits

`Ctrl+Shift+D` cuts the pane you are in half, the new half opening in the same
directory. Splits nest, so a pane can be split again in either direction, and
every divider drags. The tab bar does not change: a split lives inside one tab,
however many panes it grows.

Moving between panes goes by geometry, not by the order they were created in —
`Alt+→` is whichever pane your eye lands on to the right, which stops matching
the tree as soon as splits nest.

Closing follows the panes. `Ctrl+Shift+X` closes one and the split collapses
back; in a tab with a single pane there is nothing to collapse, so the same key
closes the tab. A shell that exits on its own takes only its own pane with it.
Closing the tab closes all of them, and asks first if any one of them is busy —
naming the busy one, not the tab.

The pane you are typing in is the one its tab speaks for: it owns the tab's
title, and a notification in *any* pane badges the tab, including a background
pane of the tab you are looking at. That last part is the point — Claude
working in the right-hand pane still tells you it needs an answer while you
carry on in the left.

## One window

Running `smt` again does not open a second window — it hands the launch to the
window already open and exits, so `smt -d ~/work/api` opens the project as a
new tab in the terminal you are already using.

GTK normally arranges that through GApplication, which needs a D-Bus session
bus; macOS has none, so without help every launch would become its own window,
and two windows restoring and then saving the same session would mean whichever
you close last silently discards the other one's tabs. The socket below does
the introduction instead: a launch that finds it live hands over, and one that
finds it refusing connections — the last instance was killed rather than closed
— clears it and takes over.

## How the notifications work

Everything funnels through one Unix socket, `smt.sock` in the runtime
directory. The terminal exports `SMT_SOCKET` and `SMT_TAB_ID` into every tab's
shell, so anything running in a tab can say "this tab wants attention" and the
terminal knows which tab that is.

A notification marks the tab and raises a desktop notification — **but only if
that pane isn't already the one you're looking at.** The focused pane never
notifies; a split-off pane running in the same tab does.

The tab gets two marks, because they are visible in different situations:
libadwaita's `needs-attention` glow, which is easy to miss on a wide tab bar,
and a **yellow dot** in the tab itself, which reads at a glance from whichever
tab you happen to be on. Hovering the dot shows what the notification said.
Both clear the moment you switch to that tab, along with the desktop
notification if it is still sitting in the shell's tray.

Recolour it with `attention_color` in `config.json`.

On Linux the desktop notification is a `GNotification`, which the shell can
withdraw again. macOS has no working backend for those — the Cocoa path wants
an app bundle — so notifications go out through `terminal-notifier` when it is
installed, and otherwise through `osascript`, which every Mac already has.
Only `terminal-notifier` can pull a notification back when you switch to the
tab; osascript ones age out on their own. The first osascript notification may
ask for permission in **System Settings → Notifications**.

### Claude Code

`install.sh` wires three hooks:

| Hook               | Fires                                              |
| ------------------ | -------------------------------------------------- |
| `Notification`     | Claude needs permission or has been waiting on you |
| `Stop`             | Claude finished responding                         |
| `UserPromptSubmit` | clears the badge when you reply                    |

This uses Claude Code's own hook events rather than scraping terminal output,
so there is no guessing and no false positives.

### Long-running commands

`shell-integration.bash` uses a `DEBUG` trap to time each command, and
`shell-integration.zsh` does the same job with zsh's own `preexec`/`precmd`
hooks. When a command finishes that ran longer than `notify_min_seconds`
(default 10), you get a notification with the command, its exit code, and how
long it took. `install.sh` wires whichever one matches your login shell.

Cost on a normal prompt is a few shell builtins and one `printf`. The helper
process only ever spawns *after* a command that already ran 10+ seconds, so its
startup time is irrelevant by construction.

### Anything else

`smt-notify` is available inside any tab:

```bash
long-build.sh; smt-notify command-done --exit $? --seconds 120 --command "build"
smt-notify claude-waiting "custom message"
smt-notify clear
```

Outside the terminal it silently does nothing, so it is safe in shared scripts.

## How paths persist

The shell reports its directory via OSC 7 on every prompt. The terminal tracks
that per pane, writes `~/.local/share/simple-multi-terminal/session.json`
(debounced, 2s), and restores those directories on next launch. A new tab opens
in the current pane's directory.

What is saved is the shape of each tab, not just a path: the splits come back
in the same directions with their dividers where you left them, including on
tabs you have not switched to yet. The tab you were on comes back selected and
holding the keyboard, and the order you dragged your tabs into is kept.
Sessions written before splits or the remembered selection existed still load —
one directory per tab is a tree of one pane, and no recorded selection means
the first tab.

A tab whose directory is gone — an unmounted volume, a deleted project — comes
back at your home directory, keeping its name. Dropping it instead would erase
it from the session on the next save, so a volume you forgot to plug in would
cost you the tab permanently.

## Closing a tab

Closing a tab that is busy asks first. The `×` on the tab and `Ctrl+Shift+W`
both go through the same guard, and so does closing the whole window — that
dialog lists every pane still running something. `Ctrl+Shift+X` asks on the
same terms before killing one pane.

Two settings, deliberately separate: `confirm_close` decides *when* to ask,
`count_as_busy` decides *what counts*.

| `confirm_close` | |
|---|---|
| `busy` (default) | ask only for tabs that count as busy |
| `always` | ask for every tab, idle or not |
| `never` | never ask |

| `count_as_busy` | example | default |
|---|---|---|
| `foreground` | `pytest`, `vim`, `claude` — has the terminal | on |
| `suspended` | a job you parked with `Ctrl+Z` | on |
| `background` | `cmd &`, and any other process alive in the tab | off |

Set it to any subset, e.g. `["foreground"]`, or `[]` to disable busy detection
entirely. `background` is off by default because you detached those on purpose
and plenty of ordinary programs leave helper processes lying around — turning
it on will flag tabs you think of as idle.

None of this is guesswork about terminal output. `foreground` reads the pty's
foreground process group, which is the shell itself when nothing is running.
The other two walk `/proc` for processes sharing the tab's session id — the
same set the kernel would `SIGHUP` if the tab went away. On macOS, where there
is no `/proc` and BSD `ps` cannot report a session id, they ask `ps` for the
processes attached to the tab's tty instead; VTE gives every tab its own pty,
so that is the same set. Either way the dialog names the actual command:
*"api" is still running pytest.*

Cancel is the default response, so Enter and Escape both back out.

## Config

The gear button in the header bar, or `Ctrl+,`, opens preferences covering
every setting below. Changes save and take effect immediately — font, colours,
scrollback and scrolling apply to open tabs as you change them. The two that
cannot, `shell` and `login_shell`, say so in the dialog and apply to the next
tab you open.

Editing the file by hand still works: `~/.config/simple-multi-terminal/config.json`,
written on first run.

| Key                      | Default        |                                            |
| ------------------------ | -------------- | ------------------------------------------ |
| `font`                   | `Monospace 11` | any Pango font string                      |
| `scrollback_lines`       | `10000`        | allocated lazily; costs nothing until used |
| `notify_min_seconds`     | `10`           | threshold for command-done notifications   |
| `notify_on_bell`         | `true`         | notify on terminal bell                    |
| `notify_on_command_done` | `true`         |                                            |
| `notify_on_claude`       | `true`         |                                            |
| `restore_session`        | `true`         |                                            |
| `audible_bell`           | `false`        |                                            |
| `cursor_blink`           | `true`         |                                            |
| `login_shell`            | `false`        | `true` runs the shell with `-l`            |
| `attention_color`        | `#f6d32d`      | the dot on tabs with a pending notification |
| `confirm_close`          | `busy`         | `busy` \| `always` \| `never`               |
| `count_as_busy`          | `["foreground", "suspended"]` | what closing asks about      |

The display name lives in one place: `APP_NAME` at the top of `smt.py`.
Changing it renames the window title and the desktop entry only — paths,
env vars and the `smt` command are independent of it.
| `shell` | `null` | overrides `$SHELL` |

## Why cairo rendering

`smt.py` sets `GSK_RENDERER=cairo` before importing GTK. GTK4's default GL
renderer allocates a GPU context costing ~30 MB PSS / ~65 MB RSS, and measured
**no throughput benefit** for a terminal (194k vs 202k lines/sec — noise), since
the bottleneck is VTE's PTY parsing, not drawing.

If scrolling ever feels less smooth than you want, delete that line in
`smt.py` and you get the GL renderer back. No other code changes.

## Debugging

```bash
SMT_DEBUG=1 smt
```

Traces every socket message and notification decision to stderr, including
whether a notification was suppressed for being focused.
