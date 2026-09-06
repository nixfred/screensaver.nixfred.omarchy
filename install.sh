#!/bin/bash
# Install the ORRERY as this machine's screensaver.
#
# Nothing under /usr/share/omarchy is touched. The idle service is taken
# over the supported way: `omarchy plugin clone omarchy.idle` makes a
# user-owned copy in ~/.config/omarchy/plugins, and only that copy is
# edited. `omarchy update` cannot clobber it, and uninstall.sh puts it back.

set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"
STAMP="$(date +%Y-%m-%d-%H%M%S)"

say() { printf '  %s\n' "$*"; }

echo "ORRERY install"

# --- 1. binaries on PATH -------------------------------------------------
mkdir -p "$BIN"
for f in orrery orrery-launch orrery-stop orrery-refresh; do
  ln -sfn "$ROOT/bin/$f" "$BIN/$f"
done
say "linked orrery, orrery-launch, orrery-stop, orrery-refresh -> $BIN"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "NOTE: $BIN is not on your PATH" ;;
esac

# --- 2. data cache -------------------------------------------------------
"$ROOT/bin/orrery-refresh" || say "WARNING: refresh failed; the bundled snapshot will be used"

# --- 3. take over idle ---------------------------------------------------
CLONE=""
for d in "$HOME/.config/omarchy/plugins"/*.idle; do
  [ -d "$d" ] && CLONE="$d" && break
done

if [ -z "$CLONE" ]; then
  say "cloning the idle service into your own config..."
  omarchy plugin clone omarchy.idle >/dev/null
  for d in "$HOME/.config/omarchy/plugins"/*.idle; do
    [ -d "$d" ] && CLONE="$d" && break
  done
fi

if [ -z "$CLONE" ] || [ ! -f "$CLONE/Service.qml" ]; then
  echo "ERROR: could not find a cloned idle service to edit." >&2
  echo "       Run 'omarchy plugin clone omarchy.idle' yourself, then re-run this." >&2
  exit 1
fi

SVC="$CLONE/Service.qml"
if grep -q 'orrery-launch' "$SVC"; then
  say "idle service already points at the orrery"
else
  cp "$SVC" "$SVC.bak-$STAMP"
  # Absolute path: the Quickshell process's PATH is not guaranteed to
  # include ~/.local/bin, and a screensaver that silently never starts is
  # worse than one that fails loudly.
  sed -i "s|omarchy-launch-screensaver|$ROOT/bin/orrery-launch|g" "$SVC"
  if grep -q 'orrery-launch' "$SVC"; then
    say "patched $(basename "$CLONE")/Service.qml  (backup: Service.qml.bak-$STAMP)"
  else
    cp "$SVC.bak-$STAMP" "$SVC"
    echo "ERROR: could not patch $SVC; restored the backup." >&2
    exit 1
  fi
fi

# --- 4. any other launch path -------------------------------------------
# The idle service is not the only way a screensaver starts. But shell.json
# holds the entire bar and is written by the running shell and by any other
# session at any moment, so this REPORTS what still points at the stock
# screensaver rather than rewriting the file underneath them. There is no
# IPC for a service plugin's settings -- setBarWidget only knows bar widgets.
python3 - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
launch = os.path.join(root, "bin", "orrery-launch")
try:
    with open(os.path.expanduser("~/.config/omarchy/shell.json")) as fh:
        doc = json.load(fh)
except Exception:
    raise SystemExit(0)

stale = []
for p in doc.get("plugins", []):
    for k, v in p.items():
        if k.endswith("Command") and isinstance(v, str) and \
                ("omarchy-launch-screensaver" in v or "omarchy launch screensaver" in v):
            stale.append((p.get("id", "?"), k, v))

if stale:
    print("  these still launch the stock screensaver:")
    for pid, k, v in stale:
        print("    %s.%s = %s" % (pid, k, v))
    print("  point them at: %s force" % launch)
    print("  (edit via the Omarchy settings UI, not by rewriting shell.json)")
else:
    print("  no other launchers point at the stock screensaver")
PY

# The stock screensaver needs no toggling: the patched idle service calls
# the orrery directly, so omarchy-launch-screensaver is simply never invoked.
# `omarchy toggle screensaver-off` is a blind flag flip and would undo itself
# on a second run, so it is deliberately not used here.

echo
echo "Done. The orrery takes over after your configured idle timeout"
echo "(idle.screensaver in ~/.config/omarchy/shell.json; currently"
echo "$(python3 -c "import json;print('  '+str(json.load(open('$HOME/.config/omarchy/shell.json'))['idle']['screensaver'])+' seconds')" 2>/dev/null || echo '  unknown'))."
echo
echo "  orrery-launch          start it now"
echo "  orrery-stop            stop it"
echo "  orrery --act 1         preview a movement in this terminal"
echo "  orrery-refresh --larry refresh the fleet and write Larry lines for new sites"
echo "  ./uninstall.sh         put everything back"
