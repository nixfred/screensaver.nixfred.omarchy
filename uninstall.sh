#!/bin/bash
# Undo install.sh: hand idle back to Omarchy's own screensaver.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"

echo "ORRERY uninstall"

for d in "$HOME/.config/omarchy/plugins"/*.idle; do
  [ -f "$d/Service.qml" ] || continue
  if grep -q 'orrery-launch' "$d/Service.qml"; then
    newest=$(ls -1t "$d"/Service.qml.bak-* 2>/dev/null | head -1 || true)
    if [ -n "$newest" ]; then
      cp "$newest" "$d/Service.qml"
      echo "  restored $(basename "$d")/Service.qml from $(basename "$newest")"
    else
      sed -i 's|[^"]*orrery-launch|omarchy-launch-screensaver|g' "$d/Service.qml"
      echo "  reverted $(basename "$d")/Service.qml by substitution"
    fi
  fi
done

for f in orrery orrery-launch orrery-stop orrery-refresh; do
  [ -L "$BIN/$f" ] && rm -f "$BIN/$f" && echo "  removed $BIN/$f"
done

echo
echo "Omarchy's own screensaver is back. The cloned idle plugin is kept"
echo "(remove it with: omarchy plugin remove <id>)."
echo "Cached fleet data is kept at ~/.local/share/orrery -- delete if you want."
