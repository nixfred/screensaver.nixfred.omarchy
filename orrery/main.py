"""Entry point. Terminal setup, the frame loop, and getting out cleanly.

Escape is the only thing that stops it. The mouse does not, other keys do
not, and losing focus does not. Up and down arrow step the speed between
1x and 5x so you can wind through the program without waiting an hour.

Because losing focus no longer ends it, a fullscreen window that quietly
stopped receiving keys would be unstoppable except by `orrery-stop`. So it
asks the compositor for focus back, and if it cannot get it for long enough
it exits rather than sit there uncloseable.
"""

import argparse
import os
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty

from .canvas import Canvas, MUTED, BRIGHT
from .model import load_fleet, Camera
from .larry import load_larry
from .hud import Hud
from .input import Reader, QUIT, FASTER, SLOWER
from . import acts, font

ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
CURSOR_OFF = "\x1b[?25l"
CURSOR_ON = "\x1b[?25h"
MOUSE_ON = "\x1b[?1003h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1006l\x1b[?1003l"
FOCUS_ON = "\x1b[?1004h"
FOCUS_OFF = "\x1b[?1004l"

WINDOW_CLASS = "org.omarchy.screensaver"

# How fast the program runs before the arrow keys touch it. The movements
# were originally timed at 1.0 and that read as static on a real screen, so
# the baseline is what used to take four presses of the up arrow to reach.
# The OSD still shows the arrow step (x1..x5), not this multiplier.
BASE_SPEED = 4.0
MAX_SPEED = 5
REFOCUS_EVERY = 2.0          # seconds between attempts to get focus back
UNFOCUSED_GIVE_UP = 45.0     # unfocused this long: exit rather than be unkillable


def _log_exit(reason, extra=""):
    """One line saying why it ended. Turns 'it just closed' into a question
    with an answer."""
    try:
        path = os.path.expanduser("~/.local/share/orrery/exit.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) > 64 * 1024:
                with open(path) as fh:
                    keep = fh.readlines()[-200:]
                with open(path, "w") as fh:
                    fh.writelines(keep)
        except Exception:
            pass
        with open(path, "a") as fh:
            fh.write("%s  %s  %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), reason, extra))
    except Exception:
        pass


def _refocus():
    """Ask Hyprland to give the screensaver keyboard focus back."""
    for cmd in (["hyprctl", "dispatch",
                 'hl.win.focus({ class = "%s" })' % WINDOW_CLASS],
                ["hyprctl", "dispatch", "focuswindow", "class:%s" % WINDOW_CLASS]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=3)
            if r.returncode == 0 and b"ok" in r.stdout.lower():
                return True
        except Exception:
            pass
    return False


class Terminal:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.saved = None

    def __enter__(self):
        try:
            self.saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        except Exception:
            self.saved = None
        sys.stdout.write(ALT_ON + CURSOR_OFF + FOCUS_ON + MOUSE_ON + "\x1b[2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *a):
        sys.stdout.write(MOUSE_OFF + FOCUS_OFF + "\x1b[0m" + CURSOR_ON + ALT_OFF)
        sys.stdout.flush()
        if self.saved is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
            except Exception:
                pass

    def probe_cell(self, timeout=0.35):
        """CSI 16 t -> cell size in pixels. Used to keep circles round."""
        try:
            sys.stdout.write("\x1b[16t")
            sys.stdout.flush()
            deadline = time.time() + timeout
            buf = ""
            while time.time() < deadline:
                r, _, _ = select.select([self.fd], [], [], deadline - time.time())
                if not r:
                    break
                buf += os.read(self.fd, 64).decode("ascii", "ignore")
                m = re.search(r"\x1b\[6;(\d+);(\d+)t", buf)
                if m:
                    ch, cw = int(m.group(1)), int(m.group(2))
                    if ch > 0 and cw > 0:
                        return (cw / 2.0) / (ch / 4.0)
        except Exception:
            pass
        return None


def wait_for_resize(deadline=2.0):
    """Terminals allocate the pty at 80x24 and resize once mapped.

    Same problem Omarchy's own screensaver documents: measure too early and
    you size the canvas to a corner of a fullscreen window.
    """
    end = time.time() + deadline
    while time.time() < end:
        try:
            sz = os.get_terminal_size()
            if (sz.columns, sz.lines) != (80, 24):
                return sz
        except Exception:
            pass
        time.sleep(0.02)
    try:
        sz = os.get_terminal_size()
        if sz.columns > 0 and sz.lines > 0:
            return sz
    except Exception:
        pass
    return os.terminal_size((80, 24))


def draw_speed_osd(canvas, speed, alpha):
    """Brief 'x3' in the top right when the speed changes, so an arrow press
    visibly does something."""
    if alpha <= 0.02:
        return
    label = "x%d" % speed
    scale = 3
    w = font.text_width(label, scale)
    font.draw_text(canvas, canvas.W - w - 10, 10, label,
                   BRIGHT if alpha > 0.5 else MUTED, scale=scale, alpha=alpha)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orrery", description="The nixfred fleet, as an orrery.")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--act", type=int, default=None,
                    help="start at movement N (0-5), for previewing")
    ap.add_argument("--seek", type=float, default=0.0,
                    help="seconds into the program to start")
    ap.add_argument("--speed", type=float, default=BASE_SPEED,
                    help="base time multiplier (default %g); arrows step 1x-5x on top" % BASE_SPEED)
    ap.add_argument("--aspect", type=float, default=None,
                    help="dot aspect override; default probes the terminal")
    ap.add_argument("--no-hud", action="store_true")
    ap.add_argument("--frames", type=int, default=0,
                    help="render N frames then exit (headless self-test)")
    args = ap.parse_args(argv)

    fleet, src = load_fleet()
    if not fleet.bodies:
        sys.stderr.write("orrery: no fleet data; run orrery-refresh\n")
        return 1
    larry = load_larry()

    sz = wait_for_resize()
    cols = max(40, sz.columns)
    rows = max(12, sz.lines - 1)

    stop = {"now": False}

    def _sig(sig, frame):
        _log_exit("signal-%d" % sig)
        stop["now"] = True

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        try:
            signal.signal(s, _sig)
        except Exception:
            pass

    if args.frames:
        import io
        canvas = Canvas(cols, rows, args.aspect or 1.0)
        return _run(canvas, fleet, larry, args, stop, sink=io.StringIO(),
                    max_frames=args.frames, hud=None, reader=None)

    with Terminal() as term:
        aspect = args.aspect if args.aspect else (term.probe_cell() or 1.0)
        reader = Reader(term.fd)
        reader.drain()
        canvas = Canvas(cols, rows, aspect)
        hud = None if args.no_hud else Hud(fleet)
        try:
            return _run(canvas, fleet, larry, args, stop, sink=sys.stdout,
                        max_frames=0, hud=hud, reader=reader)
        finally:
            if hud:
                hud.stop()


def _run(canvas, fleet, larry, args, stop, sink, max_frames, hud, reader):
    program = acts.build_program(fleet)
    cam = Camera(min(canvas.W, canvas.H / canvas.aspect) * 0.46)
    scene = acts.Scene(canvas, fleet, cam, larry, hud)

    elapsed = args.seek
    if args.act is not None:
        elapsed = 0.0
        for a in program[:max(0, min(args.act, len(program) - 1))]:
            if a.duration != float("inf"):
                elapsed += a.duration
    if elapsed > 0:
        fleet.advance(elapsed, elapsed)

    target = 1.0 / max(args.fps, 1.0)
    last = time.monotonic()
    frames = 0

    speed = 1                   # the 1x-5x step the arrows drive
    osd_until = 0.0
    last_refocus = 0.0
    refocusing = {"busy": False}

    def _try_refocus():
        _refocus()
        refocusing["busy"] = False

    while not stop["now"]:
        now = time.monotonic()
        raw_dt = min(0.25, now - last)
        last = now

        if reader is not None:
            for action in reader.poll():
                if action is QUIT:
                    _log_exit("escape")
                    stop["now"] = True
                    break
                elif action is FASTER and speed < MAX_SPEED:
                    speed += 1
                    osd_until = now + 1.6
                elif action is SLOWER and speed > 1:
                    speed -= 1
                    osd_until = now + 1.6
            if stop["now"]:
                break

            # Focus is not an exit, but without it Escape cannot arrive.
            # Ask for it back; give up only if it stays gone a long time.
            if not reader.focused and reader.unfocused_since:
                gone = time.time() - reader.unfocused_since
                if gone > UNFOCUSED_GIVE_UP:
                    _log_exit("unfocused", "%.0fs without focus" % gone)
                    break
                if gone > 1.0 and (now - last_refocus) > REFOCUS_EVERY \
                        and not refocusing["busy"]:
                    last_refocus = now
                    refocusing["busy"] = True
                    threading.Thread(target=_try_refocus, daemon=True).start()

        dt = raw_dt * args.speed * speed
        elapsed += dt
        fleet.advance(dt, elapsed)

        acc = 0.0
        act = program[-1]
        local = elapsed
        for a in program:
            if a.duration == float("inf") or elapsed < acc + a.duration:
                act = a
                local = elapsed - acc
                break
            acc += a.duration

        canvas.clear()
        scene.overlay = None
        scene.banner = None
        try:
            act.update(scene, local, dt)
            acts.render_overlay(scene)
            acts.render_banner(scene)
        except Exception:
            import traceback
            try:
                log = os.path.expanduser("~/.local/share/orrery/crash.log")
                os.makedirs(os.path.dirname(log), exist_ok=True)
                with open(log, "a") as fh:
                    fh.write("--- %s  act=%s local=%.1f\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), act.name, local))
                    traceback.print_exc(file=fh)
            except Exception:
                pass
            _log_exit("crash", act.name)
            return 1

        if hud is not None and not isinstance(act, acts.ColdStart):
            hud.render(canvas, scene.field_alpha)
        elif hud is not None and local > 64.0:
            hud.render(canvas, (local - 64.0) / 10.0)

        if now < osd_until:
            draw_speed_osd(canvas, speed, min(1.0, (osd_until - now) / 0.4))

        canvas.flush(sink)
        frames += 1
        if max_frames and frames >= max_frames:
            break

        sleep = target - (time.monotonic() - now)
        if sleep > 0:
            time.sleep(sleep)

    return 0
