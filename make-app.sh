#!/usr/bin/env bash
# Builds SMT.app into ~/Applications, so the terminal opens from Spotlight,
# the Dock and Launchpad like any other Mac app instead of having to be
# started from inside another terminal. Re-running rebuilds it in place.
#
#   ./make-app.sh [python-with-gi-bindings]
#
# install.sh calls this on macOS and passes the interpreter it already found.
set -euo pipefail

[ "$(uname -s)" = "Darwin" ] || { echo "make-app.sh is macOS-only"; exit 1; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="$HOME/Applications"
# The display name lives in smt.py and nowhere else; read it rather than
# repeating it, otherwise renaming the app renames only half of it.
NAME="$(sed -n 's/^APP_NAME = "\([^"]*\)".*/\1/p' "$SRC/smt.py")"
APP_ID="$(sed -n 's/^APP_ID = "\([^"]*\)".*/\1/p' "$SRC/smt.py")"
APP="$APPS/$NAME.app"

PY="${1:-}"
if [ -z "$PY" ]; then
  for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Vte", "3.91")
from gi.repository import Gtk, Adw, Vte' 2>/dev/null; then
      PY="$(command -v "$candidate")"
      break
    fi
  done
fi
[ -n "$PY" ] || { echo "no python with the GTK4 bindings; run ./install.sh first"; exit 1; }

echo "==> building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The app's own copy, so the bundle keeps working even if ~/.local/bin is
# cleaned out. install.sh refreshes both on every run.
install -m 644 "$SRC/smt.py" "$APP/Contents/Resources/smt.py"

# The app has to run an interpreter that lives inside itself. A framework
# python is a stub that re-execs the framework's own Python.app, and macOS
# then attributes the running app to *that* bundle: the Dock, the menu bar and
# Cmd+Tab all say "Python", with Python's icon. Copying the real interpreter in
# and giving it a pyvenv.cfg — the same mechanism a virtualenv uses — keeps the
# process inside this bundle, so it shows up as the app it actually is.
#
# It has to be copied in under the app's own name too: what the Dock and
# Cmd+Tab label a process is the name of the image it is running, and the
# launcher below execs this, so a copy called anything else would put that
# name on the app. Resources rather than MacOS only because the launcher has
# already claimed the app's name there, and pyvenv.cfg is found from either.
PYHOME="$("$PY" -c 'import sys; print(sys.base_prefix)')"
PYBIN="$PYHOME/Resources/Python.app/Contents/MacOS/Python"
[ -x "$PYBIN" ] || PYBIN="$(readlink -f "$PY" 2>/dev/null || echo "$PY")"
install -m 755 "$PYBIN" "$APP/Contents/Resources/$NAME"
cat > "$APP/Contents/pyvenv.cfg" <<CFG
home = $PYHOME/bin
include-system-site-packages = true
CFG

# Finder hands a bundle almost no environment: no PATH worth using, and on
# some systems no SHELL, which would silently drop every tab to /bin/bash.
cat > "$APP/Contents/MacOS/$NAME" <<LAUNCH
#!/bin/sh
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -z "\$SHELL" ]; then
  SHELL="\$(dscl . -read "/Users/\$(id -un)" UserShell 2>/dev/null | awk '{print \$2}')"
  [ -n "\$SHELL" ] || SHELL=/bin/zsh
  export SHELL
fi
cd "\$HOME" || exit 1
RES="\$(dirname "\$0")/../Resources"
exec "\$RES/$NAME" "\$RES/smt.py" "\$@"
LAUNCH
chmod 755 "$APP/Contents/MacOS/$NAME"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>$APP_ID</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundleIconFile</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

echo "==> drawing the icon"
ICONSET="$(mktemp -d)/$NAME.iconset"
mkdir -p "$ICONSET"
if "$PY" - "$ICONSET" <<'PY'
import sys
try:
    import cairo
except ImportError:
    sys.exit(1)

out = sys.argv[1]

def draw(size, path):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    c = cairo.Context(surface)
    s = size / 1024.0
    # A rounded square the same shape macOS gives its own icons, then a
    # prompt on it. Nothing here is theme-aware: an icon is one image.
    margin, radius = 96 * s, 200 * s
    x0, x1 = margin, size - margin
    c.new_path()
    c.arc(x0 + radius, x0 + radius, radius, 3.14159, 4.71239)
    c.arc(x1 - radius, x0 + radius, radius, 4.71239, 0)
    c.arc(x1 - radius, x1 - radius, radius, 0, 1.5708)
    c.arc(x0 + radius, x1 - radius, radius, 1.5708, 3.14159)
    c.close_path()
    gradient = cairo.LinearGradient(0, 0, 0, size)
    gradient.add_color_stop_rgb(0, 0.16, 0.18, 0.22)
    gradient.add_color_stop_rgb(1, 0.09, 0.10, 0.13)
    c.set_source(gradient)
    c.fill()

    c.set_line_width(58 * s)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)
    c.set_source_rgb(0.51, 0.83, 0.42)          # the chevron of a prompt
    c.move_to(320 * s, 390 * s)
    c.line_to(470 * s, 512 * s)
    c.line_to(320 * s, 634 * s)
    c.stroke()
    c.set_source_rgb(0.88, 0.89, 0.92)          # and its cursor
    c.move_to(560 * s, 648 * s)
    c.line_to(730 * s, 648 * s)
    c.stroke()
    surface.write_to_png(path)

for size in (16, 32, 128, 256, 512):
    draw(size, f"{out}/icon_{size}x{size}.png")
    draw(size * 2, f"{out}/icon_{size}x{size}@2x.png")
PY
then
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$NAME.icns"
else
  echo "    pycairo missing; the app gets the generic icon"
fi
rm -rf "$(dirname "$ICONSET")"

# Tell LaunchServices about it now, so Spotlight finds it without a relogin.
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$APP" || true
touch "$APP"

echo "    done: $APP"
echo "    open it from Spotlight (Cmd+Space, \"$NAME\") or: open -a $NAME"
