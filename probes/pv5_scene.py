"""P-V5 the budget ruler: the scene, defined once.

pv5.asm's data (pv5_data.inc), the model's picture (pv5_model.py) and the test (test_next_video.ProbeV5) all
come from here. Hatch Fern, Fri 6 Nov 2026.

PV2's limit strip ran out of time on the test machine far sooner than the VHDL reading says, and on a sprite
boundary. This card measures it, with **every one of the 128 slots written**, so no leftover sprite can
take the line's time. Three strips, each on rows of its own:
  A: sprites 96-127 at 8x, x = 8i, wvc 194: exactly PV2's strip;
  B: sprites 10-41 at 4x, x = 8i, wvc 40;
  C: sprites 42-95 at 2x, x = 4i, wvc 100.
Slots 0-9 are invisible. Each strip has a different number of undrawn qualifies before it (10, 42,
96) and draws sprites of a different width (64, 32, 128), so a late start, a per-qualify cost and
a per-drawn-sprite cost can be told apart (Ratio's point).
Each sprite is the solid pattern (outline, interior) with palette offset i mod 16, so every step shows its
outline colour (offset x 16) and a whole sprite ends with its interior then its outline.
"""
T = 0xE3
NR15 = 0x23                     # sprites on, over the border, border clip on
CLIP19 = (4, 155, 0, 255)       # whc 8-311
STRIPS = {                      # name: (first index, count, scale (a4 bits 4:3), x step, wvc)
    'A': (96, 32, 3, 8, 194),
    'B': (10, 32, 2, 8, 40),
    'C': (42, 54, 1, 4, 100),
}
STATUS_ROW = 22


def pattern_solid():
    return [0x00 if x in (0, 15) or y in (0, 15) else 0x01 for y in range(16) for x in range(16)]


PATTERNS = [pattern_solid()]


def sprites():
    """All 128 slots, five bytes each: the strips' sprites visible, nothing else (and nothing undefined)."""
    s = {}
    for first, count, scale, step, wvc in STRIPS.values():
        for i in range(count):
            x = step * i
            s[first + i] = [x & 0xFF, wvc, (i % 16) << 4 | (x >> 8), 0xC0, scale << 3]
    for idx in range(128):
        s.setdefault(idx, [0, 0, 0, 0x40, 0])     # invisible, five bytes, so byte 4 is written too
    return s


def sprite_palette():
    """Identity, except entry (offset x 16 + 1), the interior, a distinct bright colour per offset."""
    pal = list(range(256))
    solid = [0xE0, 0xFC, 0x1C, 0x1F, 0x03, 0xE7, 0xF0, 0x9C, 0x8F, 0x6D, 0xB6, 0x52, 0xF3, 0x7C, 0x4B, 0xDA]
    for off in range(16):
        pal[(off << 4) | 0x01] = solid[off]
    return pal


def ula():
    """Empty bitmap; ink 7 on paper 0 everywhere."""
    return bytes(6144), bytes([0x07] * 768)


def regs():
    """(register, value) pairs before the sprites: ULA ink 7 and paper 0 and 1 (the border), transparency,
    fallback, the sprite clip."""
    r = [(0x43, 0x00), (0x40, 0x07), (0x41, 0xFF), (0x40, 0x10), (0x41, 0x00), (0x40, 0x11), (0x41, 0x02),
         (0x14, T), (0x4A, 0x00), (0x4B, T), (0x1C, 0x02)]
    return r + [(0x19, v) for v in CLIP19]


def schedule():
    return []
