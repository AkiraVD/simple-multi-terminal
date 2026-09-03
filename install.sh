#!/usr/bin/env bash
# Installs simple-multi-terminal for the current user. Re-running is safe.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
SHARE="$HOME/.local/share/simple-multi-terminal"
DESKTOP="$HOME/.local/share/applications"
APP_ID="dev.phuongld.SimpleTerm"
OS="$(uname -s)"

echo "==> checking dependencies"
# The GI bindings belong to one specific python. On Linux that is the system
# python3; on macOS it is Homebrew's, which is not always first on PATH. Try
# the candidates and remember which one works, because that is the interpreter
# the installed script has to run under.
PY=""
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" - <<'PY' 2>/dev/null
import gi
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); gi.require_version('Vte','3.91')
from gi.repository import Gtk, Adw, Vte
PY
  then
    PY="$(command -v "$candidate")"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "    missing GTK4 / libadwaita / VTE python bindings. Install with:"
  if [ "$OS" = "Darwin" ]; then
    echo "      brew install gtk4 libadwaita vte3 pygobject3 adwaita-icon-theme"
  else
    echo "      sudo apt install gir1.2-vte-3.91 gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi"
  fi
  exit 1
fi
echo "    ok ($PY)"

echo "==> installing binaries to $BIN"
mkdir -p "$BIN" "$SHARE"
install -m 755 "$SRC/smt.py"     "$BIN/smt"
install -m 755 "$SRC/smt-notify" "$BIN/smt-notify"
install -m 644 "$SRC/shell-integration.bash" "$SHARE/shell-integration.bash"
install -m 644 "$SRC/shell-integration.zsh"  "$SHARE/shell-integration.zsh"
# Pin the shebang to the interpreter that actually has the bindings; on macOS
# `env python3` would pick the system python over Homebrew's. Linux keeps the
# `env python3` it shipped with, which survives the interpreter moving.
if [ "$OS" = "Darwin" ]; then
  "$PY" - "$BIN/smt" "$PY" <<'PY'
import sys
path, interpreter = sys.argv[1], sys.argv[2]
with open(path) as fh:
    lines = fh.readlines()
lines[0] = f"#!{interpreter}\n"
with open(path, "w") as fh:
    fh.writelines(lines)
PY
fi

if [ "$OS" = "Darwin" ]; then
  echo "==> building the app bundle"
  # The Linux side gets a .desktop file; the Mac equivalent is a real bundle,
  # which is also what lets the terminal be opened from Spotlight or the Dock
  # instead of only from inside another terminal.
  "$SRC/make-app.sh" "$PY" | sed 's/^/  /'
  if ! command -v terminal-notifier >/dev/null 2>&1; then
    echo "    optional: brew install terminal-notifier"
    echo "    (without it notifications go through osascript and cannot be"
    echo "     withdrawn when you switch to the tab)"
  fi
else
  echo "==> installing desktop entry"
  mkdir -p "$DESKTOP"
  # The desktop file must be named after the app id, otherwise Wayland shows a
  # generic icon and Gio.Notification has no icon to attach.
  cat > "$DESKTOP/$APP_ID.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=SMT
Comment=simple-multi-terminal — tabs, rename, notify, persistent paths
Exec=$BIN/smt
Icon=utilities-terminal
Terminal=false
Categories=System;TerminalEmulator;
StartupNotify=true
StartupWMClass=$APP_ID
DESK
  update-desktop-database "$DESKTOP" 2>/dev/null || true
fi

# Wire the integration for the login shell, not for whatever runs this script.
case "$(basename "${SHELL:-/bin/bash}")" in
  zsh) RC="$HOME/.zshrc";  INTEGRATION="$SHARE/shell-integration.zsh" ;;
  *)   RC="$HOME/.bashrc"; INTEGRATION="$SHARE/shell-integration.bash" ;;
esac
echo "==> wiring shell integration into $RC"
LINE="[ -f \"$INTEGRATION\" ] && . \"$INTEGRATION\""
if grep -qF "$INTEGRATION" "$RC" 2>/dev/null; then
  echo "    already present, skipping"
else
  printf '\n# simple-multi-terminal\n%s\n' "$LINE" >> "$RC"
  echo "    appended"
fi

echo "==> wiring Claude Code hooks"
"$PY" - "$HOME/.claude/settings.json" <<'PY'
import json, os, sys

path = sys.argv[1]
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    with open(path) as fh:
        settings = json.load(fh)
except (OSError, ValueError):
    settings = {}

wanted = {
    "Notification":     "smt-notify claude-waiting",
    "Stop":             "smt-notify claude-done",
    "UserPromptSubmit": "smt-notify working",
}
hooks = settings.setdefault("hooks", {})
changed = False
for event, command in wanted.items():
    entries = hooks.setdefault(event, [])
    existing = [
        h.get("command", "")
        for entry in entries
        for h in entry.get("hooks", [])
    ]
    if any(command in c for c in existing):
        continue
    entries.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})
    changed = True

if changed:
    if os.path.exists(path):
        os.replace(path, path + ".bak")
        print(f"    backed up existing settings to {path}.bak")
    with open(path, "w") as fh:
        json.dump(settings, fh, indent=2)
    print("    hooks added: Notification, Stop, UserPromptSubmit")
else:
    print("    hooks already present, skipping")
PY

echo
echo "Done. Launch with:  smt"
if [ "$OS" = "Darwin" ]; then
  echo "                or:  open -a SMT   (also in Spotlight and Launchpad)"
fi
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "NOTE: $BIN is not on your PATH; add it to $RC" ;;
esac
echo "Open a NEW tab (or 'source $RC') for shell integration to take effect."
