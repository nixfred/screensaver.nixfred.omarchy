"""The six movements.

The ORRERY does not loop. It descends: it assembles, walks the whole fleet,
dives each section, dissolves into the connected graph, pulls back until the
fleet is one cluster, and then holds that indefinitely. Roughly 65 minutes
before the final movement, which never ends.

The aircraft crosses on its own timer straight through all of it.
"""

import math

from . import font
from .canvas import (DUST, TRACE, DIM, MUTED, PRIMARY, BRIGHT,
                     GREEN, AMBER, RED)

TAU = math.tau


def ease(t):
    """Smoothstep, clamped."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def fade_window(t, dur, rise, fall):
    """1.0 in the middle of a window, ramping at each end."""
    if t < 0 or t > dur:
        return 0.0
    return min(ease(t / rise) if rise > 0 else 1.0,
               ease((dur - t) / fall) if fall > 0 else 1.0)


def shade(color, alpha):
    """Step a colour down the palette as it fades, since dots have no opacity."""
    if alpha >= 0.85:
        return color
    if alpha >= 0.55:
        return max(DIM, color - 1) if color <= PRIMARY else PRIMARY
    if alpha >= 0.25:
        return DIM
    return DUST


class Scene:
    def __init__(self, canvas, fleet, camera, larry, hud):
        self.c = canvas
        self.fleet = fleet
        self.cam = camera
        self.larry = larry
        self.hud = hud
        self.overlay = None      # (title, host, line, larry_lines, alpha, scale)
        self.banner = None       # (text, alpha, scale) centred announcement
        self.field_alpha = 1.0
        self.trace_alpha = 1.0
        self.label_shells = set()
        self.focus = None
        self.graph_mix = 0.0     # 0 = orbits, 1 = connected graph
        self.graph_spin = 0.0
        self.scrim = None        # rect the field yields to, so text stays readable

    # --- world -> screen ------------------------------------------------

    def project(self, wx, wy):
        c = self.c
        return (c.W * 0.5 + (wx - self.cam.x) * self.cam.zoom,
                c.H * 0.5 + (wy - self.cam.y) * self.cam.zoom * c.aspect)


# ---------------------------------------------------------------------------
# shared field renderer
# ---------------------------------------------------------------------------

def render_field(s, t):
    c = s.c
    lay = layout_overlay(s)
    if lay:
        sx, sy, sw, sh = lay[0], lay[1], lay[2], lay[3]
        s.scrim = (sx - 5, sy - 5, sx + sw + 5, sy + sh + 5)
    else:
        s.scrim = None
    scrim = s.scrim
    fleet = s.fleet
    ac = fleet.aircraft
    yield_to_aircraft = ac.dim
    fa = s.field_alpha * (1.0 - 0.55 * yield_to_aircraft)

    # Dust is drawn in screen space and wrapped, so its density stays constant
    # no matter how far the camera pulls back. Depth gives it parallax.
    if fa > 0.04:
        W, H = c.W, c.H
        camx, camy = s.cam.x * s.cam.zoom, s.cam.y * s.cam.zoom * c.aspect
        bright = fa > 0.6
        for (dx, dy, depth) in fleet.dust:
            px = (dx * 0.5 + 0.5) * W - camx * depth * 0.35
            py = (dy * 0.5 + 0.5) * H - camy * depth * 0.35
            px %= W
            py %= H
            if scrim and scrim[0] <= px <= scrim[2] and scrim[1] <= py <= scrim[3]:
                continue
            c.dot(px, py, TRACE if (bright and depth > 0.85) else DUST)

    # orbit traces
    ta = s.trace_alpha * fa * (1.0 - s.graph_mix)
    if ta > 0.06:
        seen = set()
        for b in fleet.bodies:
            if b.shell in seen:
                continue
            seen.add(b.shell)
            px, py = s.project(0, 0)
            rx = b.a * s.cam.zoom
            ry = b.b * s.cam.zoom * c.aspect
            if rx < 1.0 and ry < 1.0:
                continue
            # Entirely off screen in every direction?
            if (px + rx < 0 or px - rx > c.W) and (py + ry < 0 or py - ry > c.H):
                continue
            col = TRACE if ta < 0.7 else (MUTED if b.shell in s.label_shells else TRACE)
            # One sample per dot of perimeter, else big rings render dotted.
            steps = max(48, int(3.4 * (rx + ry)))
            step = 1 if ta > 0.6 else (2 if ta > 0.3 else 4)
            for i in range(0, steps, step):
                a = (i / steps) * TAU
                x = px + rx * math.cos(a)
                if x < -2 or x > c.W + 2:
                    continue
                y = py + ry * math.sin(a)
                if y < -2 or y > c.H + 2:
                    continue
                if scrim and scrim[0] <= x <= scrim[2] and scrim[1] <= y <= scrim[3]:
                    continue
                c.dot(x, y, col)

    # bodies
    labels = []
    for b in fleet.bodies:
        if s.graph_mix > 0.001:
            wx, wy = graph_pos(s, b)
            wx = b.x + (wx - b.x) * s.graph_mix
            wy = b.y + (wy - b.y) * s.graph_mix
        else:
            wx, wy = b.x, b.y
        px, py = s.project(wx, wy)
        b.sx, b.sy = px, py
        if px < -20 or py < -20 or px > c.W + 20 or py > c.H + 20:
            continue

        focused = (s.focus is b)
        near = b.z >= 0
        if focused:
            col = BRIGHT
        elif fa < 0.35:
            col = DUST
        elif b.shell in s.label_shells:
            col = PRIMARY if near else DIM
        elif fa < 0.7:
            col = DIM
        else:
            col = PRIMARY if near else DIM
        if not b.alive:
            col = RED

        r = b.size * (1.0 + 0.55 * (0.5 + 0.5 * b.z))
        if focused:
            r *= 1.9
        r *= max(0.35, min(1.6, s.cam.zoom / 210.0))

        # A body sitting on top of the text makes the text unreadable, so
        # inside the scrim it shrinks and drops back to a background tone.
        # The focused body is exempt: it is the thing being talked about.
        if scrim and not focused and \
                scrim[0] - r <= px <= scrim[2] + r and \
                scrim[1] - r <= py <= scrim[3] + r:
            if col not in (RED, GREEN):
                col = DUST if fa < 0.7 else TRACE
            r *= 0.45

        c.blob(px, py, r, col)

        if focused:
            # halo
            c.ring(px, py, r + 5, (r + 5) * c.aspect, MUTED, phase=t * 0.6)

        if b.shell in s.label_shells and not focused and fa > 0.5:
            labels.append((py, px + int(r) + 5, py - 3, b.title.upper()[:26], b.z))

    # Labels, placed greedily: near-side bodies win, and a label that would
    # land on top of one already placed is dropped rather than overprinted.
    # Eight sites in one shell will cluster, and two labels in the same space
    # are worth less than one.
    if labels:
        placed = []
        labels.sort(key=lambda L: (-L[4], L[0]))
        for _, lx, ly, text, _z in labels:
            w = font.text_width(text, 1)
            box = (lx - 3, ly - 2, lx + w + 3, ly + font.GLYPH_H + 2)
            if scrim and not (box[2] < scrim[0] or box[0] > scrim[2] or
                              box[3] < scrim[1] or box[1] > scrim[3]):
                continue
            if box[0] < 0 or box[2] > c.W or box[1] < 0 or box[3] > c.H:
                continue
            clash = False
            for q in placed:
                if not (box[2] < q[0] or box[0] > q[2] or
                        box[3] < q[1] or box[1] > q[3]):
                    clash = True
                    break
            if clash:
                continue
            placed.append(box)
            font.draw_text(c, lx, ly, text, MUTED, scale=1)

    # the aircraft
    if ac.active:
        px, py = ac.path(c.W, c.H)
        ac.trail.append((px, py))
        if len(ac.trail) > 260:
            del ac.trail[0]
        n = len(ac.trail)
        for i, (tx, ty) in enumerate(ac.trail):
            f = i / max(1, n - 1)
            if f < 0.35 and (i % 3):
                continue
            c.dot(tx, ty, DUST if f < 0.5 else (TRACE if f < 0.8 else MUTED))
        c.blob(px, py, 3.4, BRIGHT)
        for w in range(3, 9):
            c.dot(px - w, py + 1, MUTED if w < 7 else DIM)
            c.dot(px + w, py + 1, MUTED if w < 7 else DIM)

        a = ac.dim
        if a > 0.15:
            tw = font.text_width(ac.title, 2)
            font.draw_text(c, (c.W - tw) // 2, int(c.H * 0.80),
                           ac.title, shade(PRIMARY, a), scale=2, alpha=a)
            yw = font.text_width(ac.years, 1)
            font.draw_text(c, (c.W - yw) // 2, int(c.H * 0.80) + 22,
                           ac.years, shade(MUTED, a), scale=1, alpha=a)


def graph_pos(s, b):
    """Where a body sits once the orbits dissolve into the wiring."""
    idx = s.fleet.bodies.index(b) if not hasattr(b, "_gi") else b._gi
    ga = idx * 2.399963           # golden angle
    rad = 0.16 + 0.115 * math.sqrt(idx + 1)
    spin = s.graph_spin
    x = rad * math.cos(ga + spin)
    z = rad * math.sin(ga + spin)
    y = (b.shell - 3.5) * 0.085 + 0.28 * z
    return x, y


def render_graph_edges(s):
    if s.graph_mix < 0.15:
        return
    c = s.c
    alpha = (s.graph_mix - 0.15) / 0.85
    fleet = s.fleet
    hubs = {}
    for sec, bs in fleet.by_section.items():
        hubs[sec] = bs[0]
    for b in fleet.bodies:
        h = hubs.get(b.section)
        if h is None or h is b:
            continue
        c.line(b.sx, b.sy, h.sx, h.sy, TRACE, alpha=alpha * 0.5)
    order = fleet.section_order
    for i in range(len(order) - 1):
        a = hubs.get(order[i])
        d = hubs.get(order[i + 1])
        if a and d:
            c.line(a.sx, a.sy, d.sx, d.sy, DIM, alpha=alpha * 0.8)


# ---------------------------------------------------------------------------
# overlay
# ---------------------------------------------------------------------------

def layout_overlay(s):
    """Measure the text block without drawing it.

    Returns (x, y, w, h, title, tscale, body) or None. render_field uses the
    rect to suppress dust and orbit traces behind the text, which is the only
    reason any of it is readable over a starfield.
    """
    if not s.overlay:
        return None
    title, host, line, larry_lines, alpha, scale = s.overlay
    if alpha <= 0.03:
        return None
    c = s.c
    x = max(6, c.W // 90)

    # The block lives in a column, never the full width.
    colw = int(c.W * 0.56)
    colw = max(min(colw, c.W - 2 * x), 34 * 6)
    chars = max(18, colw // 6)

    # Title scale: as large as fits the column, and capped by canvas size so a
    # small terminal does not end up with three-inch letters.
    tscale = min(scale, max(1, c.W // 150 + 1))
    if title:
        while tscale > 1 and font.text_width(title.upper(), tscale) > colw:
            tscale -= 1

    body = []
    if host:
        body.append((host, MUTED, 0))
    for seg in wrap(line, chars):
        body.append((seg, PRIMARY, 0))
    if larry_lines:
        first = True
        for seg in larry_lines:
            if not seg:
                continue
            for sub in wrap(seg, chars):
                body.append((sub, MUTED, 5 if first else 0))
                first = False

    h = (font.GLYPH_H * tscale + 7) if title else 0
    for i, (_, _, pad) in enumerate(body):
        h += pad + (12 if (host and i == 0) else 10)

    y = max(4, c.H - 16 - h)
    w = colw
    if title:
        w = max(w, font.text_width(title.upper(), tscale))
    return (x, y, min(w, c.W - x), h, title, tscale, body)


def render_overlay(s):
    lay = layout_overlay(s)
    if not lay:
        return
    x, y, w, h, title, tscale, body = lay
    alpha = s.overlay[4]
    host = s.overlay[1]
    c = s.c
    if title:
        font.draw_text(c, x, y, title.upper(), shade(BRIGHT, alpha),
                       scale=tscale, alpha=alpha)
        y += font.GLYPH_H * tscale + 7
    for i, (seg, col, pad) in enumerate(body):
        y += pad
        font.draw_text(c, x + (5 if col is MUTED and i else 0), y, seg,
                       shade(col, alpha), scale=1, alpha=alpha)
        y += 12 if (host and i == 0) else 10


def render_banner(s):
    if not s.banner:
        return
    text, alpha, scale = s.banner
    if alpha <= 0.03:
        return
    c = s.c
    w = font.text_width(text, scale)
    font.draw_text(c, (c.W - w) // 2, int(c.H * 0.44),
                   text, shade(BRIGHT, alpha), scale=scale, alpha=alpha)


def wrap(text, width):
    words = text.split()
    out, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# the acts
# ---------------------------------------------------------------------------

class Act:
    name = "act"
    duration = 60.0

    def update(self, s, t, dt):
        raise NotImplementedError


class ColdStart(Act):
    """Black, then one dot, then dust, then the shells draw, then the fleet."""
    name = "COLD START"
    duration = 74.0

    def update(self, s, t, dt):
        c = s.c
        s.cam.target(0, 0, min(c.W, c.H / c.aspect) * 0.46)
        s.cam.advance(dt, 1.4)
        s.focus = None
        s.label_shells = set()

        if t < 7.0:
            s.field_alpha = 0.0
            s.trace_alpha = 0.0
            px, py = s.project(0, 0)
            pulse = 0.5 + 0.5 * math.sin(t * 2.2)
            c.blob(px, py, 1.0 + pulse * 1.6, BRIGHT if pulse > 0.5 else MUTED)
            return

        s.field_alpha = ease((t - 7.0) / 11.0)

        # shells draw themselves, outermost inward
        if 18.0 <= t < 48.0:
            s.trace_alpha = 0.0
            k = (t - 18.0) / 30.0
            order = list(reversed(range(8)))
            per = 1.0 / 8.0
            px, py = s.project(0, 0)
            seen = set()
            for slot, shell in enumerate(order):
                lo = slot * per
                arc = max(0.0, min(1.0, (k - lo) / per))
                if arc <= 0:
                    continue
                for b in s.fleet.bodies:
                    if b.shell != shell or b.shell in seen:
                        continue
                    seen.add(shell)
                    c.ring(px, py, b.a * s.cam.zoom, b.b * s.cam.zoom * c.aspect,
                           MUTED if arc < 1.0 else TRACE, phase=-math.pi / 2, arc=arc)
                    if 0.15 < arc < 0.98:
                        nm = s.fleet.section_order[shell].upper()
                        w = font.text_width(nm, 2)
                        font.draw_text(c, (c.W - w) // 2, int(c.H * 0.5) - 8,
                                       nm, MUTED, scale=2, alpha=fade_window(arc, 1.0, 0.2, 0.25))
                    break
            # bodies arrive with their shell
            for b in s.fleet.bodies:
                slot = order.index(b.shell)
                if k >= slot * per + per * 0.55:
                    px2, py2 = s.project(b.x, b.y)
                    c.blob(px2, py2, b.size, PRIMARY if b.z >= 0 else DIM)
            return

        s.trace_alpha = ease((t - 48.0) / 8.0)
        render_field(s, t)
        if t > 56.0:
            a = fade_window(t - 56.0, 18.0, 2.0, 5.0)
            s.banner = ("THE ORRERY", a, 4)
            if t > 62.0:
                sub = "%d live" % (len(s.fleet.bodies) + 1)
                w = font.text_width(sub, 1)
                font.draw_text(c, (c.W - w) // 2, int(c.H * 0.44) + 34,
                               sub, shade(MUTED, a), scale=1, alpha=a)


class Tour(Act):
    """Settle on each of the fleet in turn. The long middle."""
    name = "THE TOUR"
    PER = 22.0

    def __init__(self, fleet):
        self.order = fleet.tour_order()
        self.duration = self.PER * len(self.order)

    def update(self, s, t, dt):
        i = min(int(t / self.PER), len(self.order) - 1)
        local = t - i * self.PER
        b = self.order[i]
        s.focus = b
        s.label_shells = set()
        s.field_alpha = 1.0
        s.trace_alpha = 1.0

        # ease toward the body, then let it drift under the camera
        hold = ease(min(1.0, local / 4.0))
        zoom = s.c.W * (0.44 + 0.30 * hold)
        s.cam.target(b.x * hold * 0.55, b.y * hold * 0.55, zoom)
        s.cam.advance(dt, 0.75)

        a = fade_window(local, self.PER, self.PER * 0.10, self.PER * 0.12)
        if s.fleet.aircraft.dim > 0.2:
            a *= (1.0 - s.fleet.aircraft.dim)     # Larry yields to the aircraft
        s.overlay = (b.title, b.host, b.line, s.larry.for_site(b.sid), a, 3)
        render_field(s, t)


class SectionDives(Act):
    """Drop into each shell in turn and let it fill the frame."""
    name = "SECTION DIVES"
    PER = 150.0

    def __init__(self, fleet):
        self.sections = [x for x in fleet.section_order if fleet.by_section.get(x)]
        self.duration = self.PER * len(self.sections)

    def update(self, s, t, dt):
        i = min(int(t / self.PER), len(self.sections) - 1)
        local = t - i * self.PER
        sec = self.sections[i]
        bs = s.fleet.by_section[sec]
        shell = bs[0].shell
        s.focus = None
        s.label_shells = {shell}
        s.field_alpha = 1.0
        s.trace_alpha = 0.85

        # zoom so this shell fills the frame
        target_zoom = (s.c.H / max(bs[0].b * 2.6, 0.02)) * 0.5
        target_zoom = min(target_zoom, s.c.W / max(bs[0].a * 2.4, 0.02) * 0.5)
        k = ease(min(1.0, local / 8.0)) * ease(min(1.0, (self.PER - local) / 8.0))
        base = min(s.c.W, s.c.H / s.c.aspect) * 0.46
        s.cam.target(0, 0, base + (target_zoom - base) * k)
        s.cam.advance(dt, 0.55)

        a0 = fade_window(local, self.PER, self.PER * 0.05, self.PER * 0.06)
        a = a0
        if s.fleet.aircraft.dim > 0.2:
            a *= (1.0 - s.fleet.aircraft.dim)
        s.overlay = ("", "", "", s.larry.for_section(sec), a * 0.9, 2)
        render_field(s, t)
        a = a0
        nm = sec.upper()
        w = font.text_width(nm, 3)
        font.draw_text(s.c, (s.c.W - w) // 2, 10, nm, shade(BRIGHT, a), scale=3, alpha=a)
        cnt = "%d site%s" % (len(bs), "" if len(bs) == 1 else "s")
        font.draw_text(s.c, (s.c.W - w) // 2, 10 + 7 * 3 + 6, cnt,
                       shade(MUTED, a), scale=1, alpha=a)


class Galaxy(Act):
    """The orbits dissolve and the wiring shows."""
    name = "THE GALAXY"
    duration = 620.0

    def update(self, s, t, dt):
        s.focus = None
        s.label_shells = set()
        s.field_alpha = 1.0
        s.graph_mix = ease(min(1.0, t / 30.0)) * ease(min(1.0, (self.duration - t) / 30.0))
        s.trace_alpha = 1.0 - s.graph_mix
        s.graph_spin = t * 0.035

        base = min(s.c.W, s.c.H / s.c.aspect) * 0.46
        s.cam.target(0, 0, base * (1.0 + 0.12 * math.sin(t * 0.02)))
        s.cam.advance(dt, 0.4)

        a = fade_window(t, self.duration, 6.0, 8.0)
        s.overlay = ("", "", "", s.larry.ambient("drift", t, 34.0), a * 0.75, 2)
        render_field(s, t)
        render_graph_edges(s)
        nm = "ONE CONNECTED SYSTEM"
        w = font.text_width(nm, 2)
        font.draw_text(s.c, (s.c.W - w) // 2, 12, nm, shade(MUTED, a * 0.8), scale=2, alpha=a * 0.8)


class DeepField(Act):
    """Pull back until the whole fleet is one cluster."""
    name = "DEEP FIELD"
    duration = 900.0

    def update(self, s, t, dt):
        s.focus = None
        s.label_shells = set()
        s.graph_mix = 0.0
        k = ease(min(1.0, t / 90.0))
        s.field_alpha = 1.0 - 0.45 * k
        s.trace_alpha = max(0.0, 0.5 - 0.5 * k)

        base = min(s.c.W, s.c.H / s.c.aspect) * 0.46
        s.cam.target(0, 0, base * (1.0 - 0.80 * k))
        s.cam.advance(dt, 0.25)

        s.overlay = ("", "", "", s.larry.ambient("deep", t, 95.0), 0.55, 2)
        render_field(s, t)


class LongNight(Act):
    """Minimum energy. Runs until something touches the machine."""
    name = "THE LONG NIGHT"
    duration = float("inf")

    def update(self, s, t, dt):
        s.focus = None
        s.label_shells = set()
        s.graph_mix = 0.0
        s.field_alpha = 0.30
        s.trace_alpha = 0.0

        base = min(s.c.W, s.c.H / s.c.aspect) * 0.46
        drift = 0.09 * math.sin(t * 0.006)
        s.cam.target(drift, drift * 0.4, base * 0.16)
        s.cam.advance(dt, 0.15)

        s.overlay = ("", "", "", s.larry.ambient("night", t, 240.0), 0.4, 2)
        render_field(s, t)


def build_program(fleet):
    return [ColdStart(), Tour(fleet), SectionDives(fleet), Galaxy(), DeepField(), LongNight()]
