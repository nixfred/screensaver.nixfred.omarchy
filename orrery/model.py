"""The fleet, as an orbital system.

Layout is deterministic: every body's starting angle and jitter is derived
from a hash of its site id, so the orrery looks like the same fleet every
night rather than reshuffling itself on each launch. Add a site to
sites.json and it appears in its section's shell; nothing else moves.
"""

import json
import math
import os
import time

DATA = os.path.expanduser("~/.local/share/orrery")
BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SECTION_ORDER = [
    "Featured", "Flagships", "Labs", "Security",
    "Field Guides", "Signal", "Personal", "Beyond nixfred.com",
]
# Inner shells are tight and quick; outer shells are wide and slow.
SHELL_R = [0.115, 0.205, 0.300, 0.395, 0.495, 0.600, 0.712, 0.845]
TILT = 0.335          # ecliptic squash: ry = rx * TILT
KEPLER = 0.00085      # angular velocity constant


def _h(s, salt=0):
    """Stable 32-bit hash. Python's hash() is salted per process."""
    v = 2166136261 ^ salt
    for ch in s:
        v = ((v ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return v


def _frac(s, salt=0):
    return _h(s, salt) / 4294967296.0


class Body:
    __slots__ = ("site", "sid", "title", "host", "line", "card", "section",
                 "shell", "weight", "tag", "a", "b", "ang", "omega", "size",
                 "x", "y", "z", "sx", "sy", "alive", "verified")

    def __init__(self, site, shell):
        self.site = site
        self.sid = site.get("id", "?")
        self.title = site.get("title", self.sid)
        self.host = site.get("host", "")
        d = site.get("desc") or {}
        self.line = d.get("line", "")
        self.card = d.get("card", self.line)
        self.section = site.get("section", "")
        self.tag = site.get("tag", "")
        self.shell = shell
        self.weight = site.get("weight", 0)
        self.verified = site.get("lastVerified", "")
        self.alive = site.get("lastVerifiedStatus", 200) == 200 and site.get("status") == "live"

        base = SHELL_R[min(shell, len(SHELL_R) - 1)]
        # Small per-body radial jitter so a shell reads as a belt, not a wire.
        self.a = base * (0.955 + 0.09 * _frac(self.sid, 7))
        self.b = self.a * (TILT * (0.9 + 0.2 * _frac(self.sid, 11)))
        self.ang = _frac(self.sid, 3) * math.tau
        direction = 1.0 if _h(self.sid, 5) & 1 else 1.0   # all prograde; a retrograde body reads as a bug
        self.omega = direction * KEPLER / (self.a ** 1.5)
        # Featured and low-weight bodies are physically bigger.
        self.size = 3.4 - min(self.weight, 40) * 0.032
        self.x = self.y = self.z = 0.0
        self.sx = self.sy = 0.0

    def advance(self, dt):
        self.ang = (self.ang + self.omega * dt) % math.tau
        self.x = self.a * math.cos(self.ang)
        self.y = self.b * math.sin(self.ang)
        self.z = math.sin(self.ang)      # <0 is the far side of the orbit


class Aircraft:
    """dad.nixfred.com. Not a body. It does not orbit anything.

    It crosses the whole field corner to corner on its own timer, never
    synchronised to the act structure, and everything else gets out of its
    way while it does. Larry has no line for it.
    """

    PERIOD = 419.0        # seconds between crossings; prime-ish, never locks to an act
    DURATION = 74.0       # seconds to cross

    def __init__(self, site):
        self.site = site or {}
        self.title = "Freddie Wright Nix Sr."
        self.years = "Fifty years in the air."
        self.t = -180.0   # first crossing a few minutes in, not immediately
        self.active = False
        self.progress = 0.0
        self.trail = []

    def advance(self, dt, elapsed):
        self.t += dt
        if self.t >= self.PERIOD:
            self.t -= self.PERIOD
        # Crossing occupies the first DURATION seconds of each period.
        if 0.0 <= self.t < self.DURATION:
            self.active = True
            self.progress = self.t / self.DURATION
        else:
            self.active = False
            self.progress = 0.0
            if self.trail:
                self.trail = []

    def path(self, w, h):
        """Corner to corner, drifting slightly off the true diagonal."""
        p = self.progress
        x = -0.1 * w + p * 1.2 * w
        y = 0.86 * h - p * 0.74 * h + math.sin(p * math.pi) * 0.05 * h
        return x, y

    @property
    def dim(self):
        """How much the rest of the field yields to it, 0..1."""
        if not self.active:
            return 0.0
        p = self.progress
        return min(1.0, min(p / 0.12, (1.0 - p) / 0.12))


class Fleet:
    def __init__(self, registry):
        self.registry = registry
        self.sites = [s for s in registry.get("sites", []) if s.get("status") == "live"]
        order = registry.get("sectionOrder") or SECTION_ORDER
        self.section_order = order

        self.aircraft = None
        self.bodies = []
        for s in self.sites:
            if s.get("id") == "dad":
                self.aircraft = Aircraft(s)
                continue
            sec = s.get("section", "")
            shell = order.index(sec) if sec in order else len(order) - 1
            self.bodies.append(Body(s, shell))
        if self.aircraft is None:
            self.aircraft = Aircraft(None)

        # Registry order within a section drives the tour order.
        self.bodies.sort(key=lambda b: (b.shell, b.weight, b.sid))
        self.by_section = {}
        for b in self.bodies:
            self.by_section.setdefault(b.section, []).append(b)

        self.dust = self._make_dust()

    def _make_dust(self):
        """Background starfield. Fixed, deterministic, slowly parallaxed."""
        pts = []
        for i in range(2600):
            fx = _frac("dust%d" % i, 1)
            fy = _frac("dust%d" % i, 2)
            fd = _frac("dust%d" % i, 3)
            pts.append((fx * 2.6 - 1.3, fy * 2.6 - 1.3, 0.25 + fd * 0.9))
        return pts

    def advance(self, dt, elapsed):
        for b in self.bodies:
            b.advance(dt)
        self.aircraft.advance(dt, elapsed)

    def tour_order(self):
        """The order Act II walks the fleet: by section, inner shell first."""
        out = []
        for sec in self.section_order:
            out.extend(self.by_section.get(sec, []))
        for b in self.bodies:
            if b not in out:
                out.append(b)
        return out


def load_fleet():
    """Cached registry first, bundled snapshot second. Never fetches."""
    for path in (os.path.join(DATA, "fleet.json"),
                 os.path.join(BUNDLED, "fleet.json")):
        try:
            with open(path) as fh:
                return Fleet(json.load(fh)), path
        except Exception:
            continue
    return Fleet({"sites": [], "sectionOrder": SECTION_ORDER}), None


class Camera:
    """Eased camera over world space. Critically damped, never overshoots."""

    def __init__(self, zoom):
        self.x = 0.0
        self.y = 0.0
        self.zoom = zoom
        self.tx = 0.0
        self.ty = 0.0
        self.tzoom = zoom

    def target(self, x, y, zoom):
        self.tx, self.ty, self.tzoom = x, y, zoom

    def advance(self, dt, rate=0.9):
        k = 1.0 - math.exp(-rate * dt)
        self.x += (self.tx - self.x) * k
        self.y += (self.ty - self.y) * k
        self.zoom += (self.tzoom - self.zoom) * k
