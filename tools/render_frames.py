#!/usr/bin/env python3
"""Render ORRERY frames to PPM without a screen or a font.

Screen-recording the real thing means fighting for the display: the moment
anyone touches the machine the screensaver correctly exits and the capture is
ruined. This drives the same Scene the screensaver drives and paints its dot
buffer straight to pixels -- every braille dot becomes a small square block,
which is what a braille cell looks like anyway. No font metrics to fight, no
display involved, and fast enough to render minutes of program time.

    tools/render_frames.py --start 0 --seconds 26 --fps 12 --out frames/
    ffmpeg -framerate 12 -i frames/f%05d.ppm ...
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orrery.canvas import Canvas, PALETTE
from orrery.model import load_fleet, Camera
from orrery.larry import load_larry
from orrery.hud import Hud
from orrery import acts
from orrery.main import BASE_SPEED

BG = (0x0c, 0x0c, 0x0c)

# dot (dx, dy) -> bit, matching canvas.py
BITS = []
for _dy in range(4):
    for _dx in range(2):
        BITS.append(((1 << (_dx * 3 + _dy)) if _dy < 3 else (1 << (6 + _dx)), _dx, _dy))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=26.0)
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--cols", type=int, default=200)
    ap.add_argument("--rows", type=int, default=61)
    ap.add_argument("--scale", type=int, default=4, help="pixels per braille dot")
    ap.add_argument("--dot", type=int, default=3, help="lit size within each dot cell")
    ap.add_argument("--speed", type=float, default=BASE_SPEED)
    ap.add_argument("--hud", action="store_true")
    ap.add_argument("--out", default="frames")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    fleet, _ = load_fleet()
    larry = load_larry()
    canvas = Canvas(args.cols, args.rows, 1.0)
    cam = Camera(min(canvas.W, canvas.H) * 0.46)
    hud = Hud(fleet) if args.hud else None
    scene = acts.Scene(canvas, fleet, cam, larry, hud)
    program = acts.build_program(fleet)

    S = args.scale
    D = min(args.dot, S)
    PW = canvas.W * S
    PH = canvas.H * S
    header = b"P6\n%d %d\n255\n" % (PW, PH)
    row_bytes = PW * 3
    blank = bytes(BG) * PW

    elapsed = args.start
    if elapsed > 0:
        fleet.advance(elapsed, elapsed)
    dt = (1.0 / args.fps) * args.speed
    n = int(args.seconds * args.fps)

    try:
        for i in range(n):
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
            act.update(scene, local, dt)
            acts.render_overlay(scene)
            acts.render_banner(scene)
            if hud is not None and not isinstance(act, acts.ColdStart):
                hud.render(canvas, scene.field_alpha)

            fb = bytearray(blank * PH)
            for idx, (mask, col) in canvas.cells.items():
                crow, ccol = divmod(idx, args.cols)
                if crow >= args.rows:
                    continue
                rgb = bytes(PALETTE[col])
                block = rgb * D
                bx = ccol * 2 * S
                by = crow * 4 * S
                for bit, dx, dy in BITS:
                    if not (mask & bit):
                        continue
                    px = bx + dx * S
                    py = by + dy * S
                    off = py * row_bytes + px * 3
                    for r in range(D):
                        o = off + r * row_bytes
                        fb[o:o + D * 3] = block

            with open(os.path.join(args.out, "f%05d.ppm" % i), "wb") as fh:
                fh.write(header)
                fh.write(fb)

            if i % 50 == 0:
                print("  frame %d/%d  %s  t=%.1fs" % (i, n, act.name, elapsed))
    finally:
        if hud:
            hud.stop()

    print("wrote %d frames (%dx%d) to %s" % (n, PW, PH, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
