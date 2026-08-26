#!/usr/bin/env bash
# Installs simple-multi-terminal for the current user. Re-running is safe.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
SHARE="$HOME/.local/share/simple-multi-terminal"
DESKTOP="$HOME/.local/share/applications"
APP_ID="dev.phuongld.SimpleTerm"

echo "==> checking dependencies"
missing=()
python3 - <<'PY' 2>/dev/null || missing+=("gir1.2-vte-3.91 gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi")
import gi
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); gi.require_version('Vte','3.91')
from gi.repository import Gtk, Adw, Vte
PY
if (( ${#missing[@]} )); then
  echo "    missing python GI bindings. Install with:"
  echo "      sudo apt install ${missing[*]}"
  exit 1
fi
echo "    ok"

echo "==> installing binaries to $BIN"
mkdir -p "$BIN" "$SHARE" "$DESKTOP"
install -m 755 "$SRC/smt.py"     "$BIN/smt"
install -m 755 "$SRC/smt-notify" "$BIN/smt-notify"
install -m 644 "$SRC/shell-integration.bash" "$SHARE/shell-integration.bash"

echo "==> installing desktop entry"
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

echo "==> wiring shell integration into ~/.bashrc"
LINE="[ -f \"$SHARE/shell-integration.bash\" ] && . \"$SHARE/shell-integration.bash\""
if grep -qF "shell-integration.bash" "$HOME/.bashrc" 2>/dev/null; then
  echo "    already present, skipping"
else
  printf '\n# simple-multi-terminal\n%s\n' "$LINE" >> "$HOME/.bashrc"
  echo "    appended"
fi

echo "==> wiring Claude Code hooks"
python3 - "$HOME/.claude/settings.json" <<'PY'
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
    "UserPromptSubmit": "smt-notify clear",
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
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "NOTE: $BIN is not on your PATH; add it to ~/.bashrc" ;;
esac
echo "Open a NEW tab (or 'source ~/.bashrc') for shell integration to take effect."
