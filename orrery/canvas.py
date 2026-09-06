"""Sparse braille canvas with frame differencing.

A starfield lights a few thousand dots on a mostly-black screen, so this
keeps a dict of touched cells rather than a full framebuffer, and emits only
the cells that changed since the previous frame. That is what lets it run in
pure Python with no numpy and still hold a steady frame rate on a 532x332
dot canvas.

Dot bit layout inside one braille cell (U+2800 + mask):

    1 4      bit0 bit3
    2 5      bit1 bit4
    3 6      bit2 bit5
    7 8      bit6 bit7
"""

import sys

# Palette. Index order is also z-order: a higher index wins the cell.
# Values are straight off nixfred.com.
PALETTE = [
    (0x2a, 0x33, 0x3d),   # 0 DUST      background stars
    (0x50, 0x61, 0x72),   # 1 TRACE     orbit lines
    (0x74, 0x92, 0xb0),   # 2 DIM       de-emphasised bodies
    (0x8f, 0xa3, 0xb5),   # 3 MUTED     HUD, labels, section names
    (0xd7, 0xe2, 0xea),   # 4 PRIMARY   body text, active bodies
    (0xff, 0xff, 0xff),   # 5 BRIGHT    the settled body, titles
    (0x28, 0xc8, 0x40),   # 6 GREEN     healthy
    (0xfe, 0xbc, 0x2e),   # 7 AMBER     warning / stale
    (0xff, 0x5f, 0x57),   # 8 RED       down
]
DUST, TRACE, DIM, MUTED, PRIMARY, BRIGHT, GREEN, AMBER, RED = range(9)

_SGR = ["\x1b[38;2;%d;%d;%dm" % c for c in PALETTE]
_RESET = "\x1b[0m"

# dot (dx, dy) -> bit
_BIT = {}
for _dx in (0, 1):
    for _dy in (0, 1, 2, 3):
        _BIT[(_dx, _dy)] = (1 << (_dx * 3 + _dy)) if _dy < 3 else (1 << (6 + _dx))


class Canvas:
    def __init__(self, cols, rows, aspect=1.0):
        self.cols = cols
        self.rows = rows
        self.W = cols * 2          # dot width
        self.H = rows * 4          # dot height
        self.aspect = aspect       # multiply y by this to correct non-square dots
        self.cells = {}            # idx -> [mask, color]
        self.prev = {}
        self._out = []

    # ---- drawing -------------------------------------------------------

    def clear(self):
        self.cells = {}

    def dot(self, x, y, color):
        x = int(x)
        y = int(y)
        if x < 0 or y < 0 or x >= self.W or y >= self.H:
            return
        idx = (y >> 2) * self.cols + (x >> 1)
        bit = _BIT[(x & 1, y & 3)]
        c = self.cells.get(idx)
        if c is None:
            self.cells[idx] = [bit, color]
        else:
            c[0] |= bit
            if color > c[1]:
                c[1] = color

    def blob(self, x, y, r, color):
        """Filled disc of radius r in dots. r<=0 draws a single dot."""
        if r <= 0.5:
            self.dot(x, y, color)
            return
        ri = int(r) + 1
        rr = r * r
        for dy in range(-ri, ri + 1):
            for dx in range(-ri, ri + 1):
                if dx * dx + dy * dy <= rr:
                    self.dot(x + dx, y + dy, color)

    def ring(self, cx, cy, rx, ry, color, steps=None, phase=0.0, arc=1.0):
        """Ellipse outline. `arc` < 1 draws only the leading fraction."""
        import math
        if rx < 1 and ry < 1:
            return
        if steps is None:
            steps = max(24, int((rx + ry) * 1.6))
        n = max(1, int(steps * arc))
        for i in range(n):
            t = phase + (i / steps) * math.tau
            self.dot(cx + rx * math.cos(t), cy + ry * math.sin(t), color)

    def line(self, x0, y0, x1, y1, color, alpha=1.0):
        dx = x1 - x0
        dy = y1 - y0
        n = int(max(abs(dx), abs(dy)))
        if n <= 0:
            self.dot(x0, y0, color)
            return
        if alpha >= 0.999:
            for i in range(n + 1):
                t = i / n
                self.dot(x0 + dx * t, y0 + dy * t, color)
        else:
            step = max(1, int(1.0 / max(alpha, 0.02)))
            for i in range(0, n + 1, step):
                t = i / n
                self.dot(x0 + dx * t, y0 + dy * t, color)

    # ---- output --------------------------------------------------------

    def flush(self, out=sys.stdout):
        """Emit only what changed. Contiguous same-colour runs share one SGR."""
        cur = self.cells
        prev = self.prev
        buf = self._out
        buf.clear()

        touched = set(cur)
        touched.update(prev)
        if not touched:
            self.prev = cur
            return

        byrow = {}
        for idx in touched:
            c = cur.get(idx)
            p = prev.get(idx)
            if c is not None and p is not None and c[0] == p[0] and c[1] == p[1]:
                continue
            r, col = divmod(idx, self.cols)
            byrow.setdefault(r, []).append((col, c))

        last_color = -1
        for r in sorted(byrow):
            items = sorted(byrow[r])
            i = 0
            n = len(items)
            while i < n:
                col, c = items[i]
                # Start a run at this column and extend while columns stay
                # contiguous and the colour does not change.
                run = []
                runcolor = c[1] if c is not None else -1
                j = i
                nextcol = col
                while j < n:
                    cc, ce = items[j]
                    if cc != nextcol:
                        break
                    ecolor = ce[1] if ce is not None else -1
                    if ce is not None and runcolor != -1 and ecolor != runcolor:
                        break
                    if ce is not None and runcolor == -1:
                        runcolor = ecolor
                    run.append(chr(0x2800 + ce[0]) if ce is not None else ' ')
                    nextcol = cc + 1
                    j += 1
                buf.append("\x1b[%d;%dH" % (r + 1, col + 1))
                if runcolor != -1 and runcolor != last_color:
                    buf.append(_SGR[runcolor])
                    last_color = runcolor
                buf.append(''.join(run))
                i = j

        out.write(''.join(buf))
        out.flush()
        self.prev = cur

    def full_repaint(self):
        """Force the next flush to redraw everything."""
        self.prev = {}
