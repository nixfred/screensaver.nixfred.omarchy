"""Larry's commentary.

Pre-written and cached, never generated live. At idle time this reads a
file and nothing else, which is what keeps the whole screensaver off the
network. orrery-refresh regenerates the cache while the machine is awake.

Two rules encoded here:
  - Larry has no line for `dad`. for_site("dad") returns nothing, always.
  - Ambient lines rotate on a long period so the same line does not come
    back around inside one sitting.
"""

import json
import os

DATA = os.path.expanduser("~/.local/share/orrery")
BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SILENT = {"dad"}


def _h(s):
    v = 2166136261
    for ch in s:
        v = ((v ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return v


class Larry:
    def __init__(self, doc):
        self.sites = doc.get("sites", {})
        self.sections = doc.get("sections", {})
        self._pools = doc.get("ambient", {})
        self._order = {}

    def for_site(self, sid):
        if sid in SILENT:
            return []
        return list(self.sites.get(sid, []))[:3]

    def for_section(self, sec):
        return list(self.sections.get(sec, []))[:3]

    def ambient_pool(self, name):
        return self._pools.get(name, [])

    def ambient(self, name, t, period):
        """One line from `name`, changing every `period` seconds."""
        pool = self._pools.get(name) or []
        if not pool:
            return []
        idx = int(t // max(period, 1.0))
        # Walk the pool in a fixed shuffled order rather than straight through.
        order = self._order.get(name)
        if order is None:
            order = sorted(range(len(pool)), key=lambda i: _h("%s%d" % (name, i)))
            self._order[name] = order
        line = pool[order[idx % len(order)]]
        return [line] if line else []


def load_larry():
    for path in (os.path.join(DATA, "larry.json"),
                 os.path.join(BUNDLED, "larry.json")):
        try:
            with open(path) as fh:
                return Larry(json.load(fh))
        except Exception:
            continue
    return Larry({})
