"""Terminal input, tokenised properly.

Escape is the only thing that stops the screensaver. Not the mouse, not a
stray keypress, not the window losing focus. Up and down arrow change speed.
Everything else is swallowed.

That makes correct escape-sequence parsing load-bearing rather than a nicety:
Escape and the arrow keys share a first byte, and a read can land anywhere
inside a sequence. So this keeps a buffer, consumes only complete sequences,
and resolves a lone ESC the way terminals always have -- if nothing completes
it within a short timeout, it was the Escape key.
"""

import os
import select
import time

_TRACE = os.environ.get("ORRERY_INPUT_TRACE")


def _trace(msg):
    if not _TRACE:
        return
    try:
        with open(_TRACE, "a") as fh:
            fh.write("%.3f  %s\n" % (time.time() % 1000, msg))
    except Exception:
        pass

# Actions this can report.
QUIT = "quit"
FASTER = "faster"
SLOWER = "slower"

ESC = 0x1b
ESC_ALONE_TIMEOUT = 0.25     # a lone ESC this old really was the Escape key
MAX_BUFFER = 4096


class Reader:
    def __init__(self, fd):
        self.fd = fd
        self.buf = bytearray()
        self.esc_since = None
        self.focused = True
        self.unfocused_since = None

    # -- reading ---------------------------------------------------------

    def poll(self):
        """Drain the tty and return a list of actions."""
        while True:
            r, _, _ = select.select([self.fd], [], [], 0)
            if not r:
                break
            try:
                data = os.read(self.fd, 4096)
            except Exception:
                break
            if not data:
                break
            _trace("read %r" % (data[:60],))
            self.buf.extend(data)
            if len(self.buf) > MAX_BUFFER:
                del self.buf[:-MAX_BUFFER]

        actions = self._consume()

        # A lone ESC that nothing ever completed is the Escape key.
        if len(self.buf) == 1 and self.buf[0] == ESC:
            if self.esc_since is None:
                self.esc_since = time.time()
            elif time.time() - self.esc_since > ESC_ALONE_TIMEOUT:
                _trace("QUIT: lone ESC aged out")
                self.buf.clear()
                self.esc_since = None
                actions.append(QUIT)
        else:
            self.esc_since = None

        return actions

    # -- tokenising ------------------------------------------------------

    def _consume(self):
        """Eat complete sequences off the front of the buffer."""
        actions = []
        while self.buf:
            if self.buf[0] != ESC:
                # An ordinary keystroke. Not Escape, so it does nothing.
                _trace("byte %r ignored" % (bytes(self.buf[:1]),))
                del self.buf[0]
                continue

            n = self._seq_len()
            if n is None:
                break                      # incomplete, wait for more bytes
            seq = bytes(self.buf[:n])
            del self.buf[:n]
            _trace("seq %r" % (seq,))
            act = self._classify(seq)
            if act:
                actions.append(act)
        return actions

    def _seq_len(self):
        """Length of the complete escape sequence at the front, or None."""
        b = self.buf
        if len(b) < 2:
            return None

        c = b[1]
        if c == 0x5b:                      # ESC [   CSI
            i = 2
            while i < len(b) and (0x20 <= b[i] <= 0x3f):
                i += 1                     # parameter and intermediate bytes
            if i >= len(b):
                return None
            if not (0x40 <= b[i] <= 0x7e):  # final byte
                return None
            return i + 1

        if c == 0x4f:                      # ESC O   SS3 (application arrows)
            return 3 if len(b) >= 3 else None

        if c == 0x5d:                      # ESC ]   OSC, ends at BEL or ST
            i = 2
            while i < len(b):
                if b[i] == 0x07:
                    return i + 1
                if b[i] == ESC and i + 1 < len(b) and b[i + 1] == 0x5c:
                    return i + 2
                i += 1
            return None

        if c == ESC:                       # ESC ESC: treat the first as done
            return 1
        return 2                           # ESC + one byte

    def _classify(self, seq):
        # Arrows, in both normal (CSI) and application (SS3) form.
        if seq in (b"\x1b[A", b"\x1bOA"):
            return FASTER
        if seq in (b"\x1b[B", b"\x1bOB"):
            return SLOWER
        # Focus reporting. Tracked, but never an exit on its own.
        if seq == b"\x1b[I":
            self.focused = True
            self.unfocused_since = None
        elif seq == b"\x1b[O":
            if self.focused:
                self.unfocused_since = time.time()
            self.focused = False
        # Everything else -- mouse reports, cell-size replies, other keys --
        # is deliberately ignored.
        return None

    # -- startup ---------------------------------------------------------

    def drain(self, seconds=0.45):
        """Swallow the terminal's startup chatter before the loop begins."""
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], max(0.0, end - time.time()))
            if not r:
                break
            try:
                if not os.read(self.fd, 4096):
                    break
            except Exception:
                break
        self.buf.clear()
        self.esc_since = None
