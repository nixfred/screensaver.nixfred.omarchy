"""5x7 bitmap font, column-major, bit 0 = top row.

Every glyph in the ORRERY is drawn into the braille dot buffer rather than
printed as terminal text. That keeps text legibility independent of the
terminal font size, so the canvas can run at a small font for resolution
while titles still render enormous.
"""

_GLYPHS = {
    ' ': "0000000000", '!': "000000 5f0000".replace(" ", ""), '"': "0007000700",
    '#': "147f147f14", '$': "242a7f2a12", '%': "2313086462", '&': "3649552250",
    "'": "0005030000", '(': "001c224100", ')': "004122 1c00".replace(" ", ""),
    '*': "1408 3e0814".replace(" ", ""), '+': "08083e0808", ',': "0050300000",
    '-': "0808080808", '.': "0060600000", '/': "2010080402",
    '0': "3e5149453e", '1': "00427f4000", '2': "4261514946", '3': "2141454b31",
    '4': "1814127f10", '5': "2745454539", '6': "3c4a494930", '7': "0171090503",
    '8': "3649494936", '9': "06494929 1e".replace(" ", ""),
    ':': "0036360000", ';': "0056360000", '<': "0814224100", '=': "1414141414",
    '>': "0041221408", '?': "0201510906", '@': "3249794 13e".replace(" ", ""),
    'A': "7e1111117e", 'B': "7f49494936", 'C': "3e41414122", 'D': "7f4141221c",
    'E': "7f49494941", 'F': "7f09090901", 'G': "3e4149497a", 'H': "7f0808087f",
    'I': "00417f4100", 'J': "2040413f01", 'K': "7f08142241", 'L': "7f40404040",
    'M': "7f020c027f", 'N': "7f0408107f", 'O': "3e4141413e", 'P': "7f09090906",
    'Q': "3e4151215e", 'R': "7f09192946", 'S': "4649494931", 'T': "01017f0101",
    'U': "3f4040403f", 'V': "1f2040201f", 'W': "3f4038403f", 'X': "6314081463",
    'Y': "0708700807", 'Z': "6151494543",
    '[': "007f414100", '\\': "0204081020", ']': "0041417f00", '^': "0402010204",
    '_': "4040404040", '`': "0001020400",
    'a': "2054545478", 'b': "7f48444438", 'c': "3844444420", 'd': "384444487f",
    'e': "3854545418", 'f': "087e090102", 'g': "0c5252523e", 'h': "7f08040478",
    'i': "00447d4000", 'j': "2040443d00", 'k': "7f10284400", 'l': "00417f4000",
    'm': "7c04180478", 'n': "7c08040478", 'o': "3844444438", 'p': "7c14141408",
    'q': "0814141 87c".replace(" ", ""), 'r': "7c08040408", 's': "4854545420",
    't': "043f444020", 'u': "3c4040207c", 'v': "1c2040201c", 'w': "3c4030403c",
    'x': "4428102844", 'y': "0c5050503c", 'z': "446454 4c44".replace(" ", ""),
    '{': "0008364100", '|': "00007f0000", '}': "0041360800", '~': "0804081008",
    '·': "0000180000", '—': "0808080808", '–': "0808080808",
    '•': "0018181800", '°': "0002050200", '→': "0808081408",
}

# Decoded lazily into tuples of 5 column bitmaps.
_CACHE = {}


def glyph(ch):
    g = _CACHE.get(ch)
    if g is not None:
        return g
    src = _GLYPHS.get(ch)
    if src is None:
        src = _GLYPHS.get(ch.upper()) if ch.upper() in _GLYPHS else None
    if src is None:
        src = "7f41417f00"  # tofu box for anything unmapped
    g = tuple(int(src[i:i + 2], 16) for i in range(0, 10, 2))
    _CACHE[ch] = g
    return g


GLYPH_W = 5
GLYPH_H = 7


def text_width(s, scale=1, tracking=1):
    """Width in dots of `s` rendered at `scale`."""
    if not s:
        return 0
    per = GLYPH_W * scale + tracking * scale
    return per * len(s) - tracking * scale


def draw_text(canvas, x, y, s, color, scale=1, tracking=1, alpha=1.0):
    """Stamp `s` into the canvas dot buffer with its top-left at (x, y).

    `alpha` below 1.0 thins the glyph stochastically-but-deterministically,
    which is how text fades in and out on a canvas that has no real opacity.
    """
    step = (GLYPH_W + tracking) * scale
    cx = x
    thin = alpha < 0.999
    for i, ch in enumerate(s):
        cols = glyph(ch)
        for col in range(GLYPH_W):
            bits = cols[col]
            if not bits:
                continue
            for row in range(GLYPH_H):
                if not (bits >> row) & 1:
                    continue
                if thin and (((col * 7 + row) * 2654435761) & 1023) / 1023.0 > alpha:
                    continue
                px = cx + col * scale
                py = y + row * scale
                if scale == 1:
                    canvas.dot(px, py, color)
                else:
                    for sy in range(scale):
                        for sx in range(scale):
                            canvas.dot(px + sx, py + sy, color)
        cx += step
    return cx
