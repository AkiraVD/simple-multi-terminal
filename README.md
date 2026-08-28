# simple-multi-terminal

A small GTK4/VTE terminal for claude code that does five things and nothing else.

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

```bash
sudo apt install gir1.2-vte-3.91 gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi
./install.sh
```

`install.sh` is idempotent. It installs `smt` and `smt-notify` into
`~/.local/bin`, adds a desktop entry, appends one line to the rc file of your
login shell (`~/.zshrc` or `~/.bashrc`), and
adds three hooks to `~/.claude/settings.json` (backing up the existing file
first). Then:

```bash
smt
```

Open a new tab or `source ~/.bashrc` for the shell integration to take effect.

## Keys

|                       |                     |
| --------------------- | ------------------- |
| `Ctrl+Shift+T`        | new tab             |
| `Ctrl+Shift+W`        | close tab (asks if busy) |
| `Ctrl+Shift+R` / `F2` | rename tab          |
| `Ctrl+Shift+C` / `V`  | copy / paste        |
| `Ctrl+PageUp/Down`    | previous / next tab |
| `Alt+1`…`Alt+9`       | jump to tab         |
| `Ctrl+±` / `Ctrl+0`   | font size           |
| `Ctrl+,`              | preferences         |
| `Ctrl+Shift+D`        | split right         |
| `Ctrl+Shift+E`        | split down          |
| `Ctrl+Shift+X`        | close pane          |
| `Alt+←↑↓→`            | move between panes  |

Tabs also rename from the right-click menu, and drag to reorder. Splitting is
also in the right-click menu.

`Alt+←→` and `Alt+↑↓` are window accelerators, so they no longer reach the
shell or a full-screen program inside a tab.

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

## How the notifications work

Everything funnels through one Unix socket. The terminal exports `SMT_SOCKET`
and `SMT_TAB_ID` into every tab's shell, so anything running in a tab can say
"this tab wants attention" and the terminal knows which tab that is.

A notification marks the tab and raises a desktop notification — **but only if
that tab isn't already the one you're looking at.** Focused tabs never notify.

The tab gets two marks, because they are visible in different situations:
libadwaita's `needs-attention` glow, which is easy to miss on a wide tab bar,
and a **yellow dot** in the tab itself, which reads at a glance from whichever
tab you happen to be on. Hovering the dot shows what the notification said.
Both clear the moment you switch to that tab, along with the desktop
notification if it is still sitting in the shell's tray.

Recolour it with `attention_color` in `config.json`.

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
The other two walk `/proc` for processes sharing the pane's session id — the
same set the kernel would `SIGHUP` if the pane went away. So the dialog names
the actual command: *"api" is still running pytest.*

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
