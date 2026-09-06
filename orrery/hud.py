"""Status line. Local sources only, gathered off the render thread.

Nothing here reaches the network. Tailscale is queried through its local
daemon; the fleet count and verification dates come from the cached
registry. A source that fails is omitted rather than guessed at -- the HUD
says `verified 25d` because that is what the registry knows, not `live`,
because nothing here checked.
"""

import json
import os
import subprocess
import threading
import time

from . import font
from .canvas import DUST, TRACE, DIM, MUTED, PRIMARY, BRIGHT, GREEN, AMBER, RED

BACKUP_PATHS = [
    os.path.expanduser("~/.local/state/backup-monitor/last.json"),
    os.path.expanduser("~/.local/share/backup-monitor/last.json"),
    os.path.expanduser("~/.cache/backup-monitor/last"),
]


class Hud:
    REFRESH = 45.0

    def __init__(self, fleet):
        self.fleet = fleet
        self.hosts = []          # (name, up)
        self.backup_age = None   # seconds, or None
        self.verified_age = None
        self._lock = threading.Lock()
        self._stop = False
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self):
        self._stop = True

    def _loop(self):
        while not self._stop:
            try:
                self._gather()
            except Exception:
                pass
            for _ in range(int(self.REFRESH * 4)):
                if self._stop:
                    return
                time.sleep(0.25)

    def _gather(self):
        hosts = []
        try:
            out = subprocess.run(["tailscale", "status", "--json"],
                                 capture_output=True, timeout=6, text=True)
            if out.returncode == 0:
                d = json.loads(out.stdout)
                peers = list((d.get("Peer") or {}).values())
                me = d.get("Self") or {}
                if me:
                    hosts.append((me.get("HostName", "self"), True))
                for p in sorted(peers, key=lambda x: x.get("HostName", "")):
                    hosts.append((p.get("HostName", "?"), bool(p.get("Online"))))
        except Exception:
            hosts = []

        backup = None
        for p in BACKUP_PATHS:
            try:
                backup = time.time() - os.path.getmtime(p)
                break
            except Exception:
                continue

        vage = None
        try:
            gen = self.fleet.registry.get("generated")
            if gen:
                st = time.mktime(time.strptime(gen, "%Y-%m-%d"))
                vage = time.time() - st
        except Exception:
            vage = None

        with self._lock:
            self.hosts = hosts
            self.backup_age = backup
            self.verified_age = vage

    @staticmethod
    def _age(sec):
        if sec is None:
            return None
        if sec < 5400:
            return "%dm" % (sec // 60)
        if sec < 172800:
            return "%dh" % (sec // 3600)
        return "%dd" % (sec // 86400)

    def render(self, c, alpha=1.0):
        """One line, right-aligned count, everything else fitted to the left.

        With 35 peers on the tailnet a dot per host will happily run over the
        site count, so the dot row is capped and the remainder summarised,
        and each field is only drawn if it actually fits.
        """
        with self._lock:
            hosts = list(self.hosts)
            backup = self.backup_age
            vage = self.verified_age

        y = c.H - 9
        x = 8
        col_dim = MUTED if alpha > 0.5 else DIM

        n = len(self.fleet.bodies) + 1
        label = "%d LIVE" % n
        right_x = c.W - font.text_width(label, 1) - 8
        font.draw_text(c, right_x, y, label,
                       PRIMARY if alpha > 0.5 else DIM, scale=1)
        limit = right_x - 12

        def fits(w):
            return x + w <= limit

        if hosts:
            up = sum(1 for _, o in hosts if o)
            shown = hosts[:20]
            if fits(len(shown) * 6 + 10):
                for _, online in shown:
                    c.blob(x, y + 3, 1.4, GREEN if online else RED)
                    x += 6
                if len(hosts) > len(shown):
                    x = font.draw_text(c, x + 4, y, "+%d" % (len(hosts) - len(shown)),
                                       col_dim, scale=1)
                x += 10
            txt = "tailnet %d/%d" % (up, len(hosts))
            if fits(font.text_width(txt, 1) + 14):
                x = font.draw_text(c, x, y, txt, col_dim, scale=1) + 14

        a = self._age(backup)
        if a:
            txt = "backup %s" % a
            if fits(font.text_width(txt, 1) + 14):
                x = font.draw_text(c, x, y, txt, col_dim, scale=1) + 14

        a = self._age(vage)
        if a:
            txt = "verified %s" % a
            if fits(font.text_width(txt, 1) + 14):
                x = font.draw_text(c, x, y, txt, col_dim, scale=1) + 14
