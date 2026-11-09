"""P-V3 the blend card: the scene, defined once (PV3-`docs/next/DESIGN.md`).

pv3.asm's data (pv3_data.inc), the model's picture (pv3_model.py) and the test
(test_next_video.ProbeV3) all come from here. Hatch Fern, Fri 6 Nov 2026.

Twelve 16-row bands. In each, the copper sets NR 0x15 (layer order), NR 0x68 (blend source, ULA off) and
NR 0x6B (bit 0, which with the tilemap off decides tm_pixel_below, zxnext:6770) over the same three layers:
Layer 2 colour columns in the left half (transparent right half), ULA paper columns (two colours and the
transparent one), and three solid sprites per band.
"""
T = 0xE3
FALLBACK = 0xA2                 # NR 0x4A: (5,0,5), where nothing is drawn
ULA_INK7, ULA_PAPER0 = 0xFF, 0x00
ULA_PAPERS = {1: 0x6D, 2: 0xA8, 3: T}          # (3,3,3), (5,2,0), transparent
L2_COLOURS = [0x49, 0x84, 0x31, 0xD8]          # (2,2,3), (4,1,0), (1,4,3), (6,6,0), indices 0x10-0x13
SPRITE_COLOURS = [0xFF, 0xFC, 0x1F]            # white, yellow, cyan: patterns 0-2
SPRITE_X = [40, 120, 168]                      # paper x: over L2 and ULA; across L2's edge; L2 transparent

# (NR 0x15 order, NR 0x68, NR 0x6B) for bands 0-11; the comment is what the VHDL says each shows
BANDS = [
    (0, 0x00, 0x00),    # 0  SLU: the reference
    (6, 0x00, 0x00),    # 1  L + U, clamped; B never shows where L is transparent (fallback there)
    (7, 0x00, 0x00),    # 2  L + U - 5
    (6, 0x80, 0x00),    # 3  as band 1: blend 00 takes ula_mix, which ignores "ULA off" (zxnext:7007-7008)
    (6, 0xC0, 0x00),    # 4  blend 10 takes ula_final, which "ULA off" empties: L alone
    (6, 0x40, 0x00),    # 5  blend 10, ULA on: as band 1
    (6, 0x20, 0x00),    # 6  blend 01, below = 1: the ULA over the sprites (zxnext:7073-7077)
    (6, 0x20, 0x01),    # 7  blend 01, below = 0: the sprites over the ULA
    (6, 0x60, 0x00),    # 8  blend 11, below = 1: as band 6 (zxnext:7063-7069)
    (6, 0x60, 0x01),    # 9  blend 11, below = 0: as band 7
    (7, 0x80, 0x00),    # 10 as band 2: "ULA off" again ignored
    (0, 0x00, 0x00),    # 11 SLU: the read-back text (char row 22)
]
RESET_ROW = 200                                # band 0's registers again, in the bottom border


def nr15(order):
    return 0x01 | (order << 2)                 # sprites on, inside the paper


def pattern_solid(colour):
    return [0x00 if x in (0, 15) or y in (0, 15) else colour for y in range(16) for x in range(16)]


PATTERNS = [pattern_solid(c) for c in SPRITE_COLOURS]


def sprites():
    """(index, 4 attribute bytes): three per band in bands 0-10, at whc = x + 32, wvc = 16b + 32."""
    s = {}
    for b in range(11):
        for k, x in enumerate(SPRITE_X):
            s[3 * b + k] = [(x + 32) & 0xFF, 16 * b + 32, (x + 32) >> 8, 0x80 | k]
    return s


def ula():
    """Bitmap (empty: the probe prints row 22's text) and attributes: paper 1 + (col // 2) mod 3 in rows
    0-21, ink 7 on paper 0 in rows 22-23."""
    at = bytearray(768)
    for row in range(24):
        for col in range(32):
            at[row * 32 + col] = 0x07 if row >= 22 else ((1 + (col // 2) % 3) << 3) | 7
    return bytes(6144), bytes(at)


def layer2():
    """256 x 192: index 0x10 + x // 32 in the left half, transparent E3 on the right."""
    return bytes((0x10 + (x >> 5)) if x < 128 else T for y in range(192) for x in range(256))


def copper_words():
    """For each band after the first: WAIT (row - 1, 44), then the three MOVEs; band 0's again at
    RESET_ROW; then halt (mode 11 restarts it each frame)."""
    w = []
    for b in range(1, 12):
        o, n68, n6b = BANDS[b]
        w += [0xD800 | (16 * b - 1), 0x1500 | nr15(o), 0x6800 | n68, 0x6B00 | n6b]
    o, n68, n6b = BANDS[0]
    w += [0xD800 | (RESET_ROW - 1), 0x1500 | nr15(o), 0x6800 | n68, 0x6B00 | n6b, 0xFFFF]
    return w


def schedule():
    """The copper list as the model's row schedule (frame9 rows = paper rows + 48)."""
    out = []
    for b in range(1, 12):
        o, n68, n6b = BANDS[b]
        out += [(48 + 16 * b, 0x15, nr15(o)), (48 + 16 * b, 0x68, n68), (48 + 16 * b, 0x6B, n6b)]
    o, n68, n6b = BANDS[0]
    return out + [(48 + RESET_ROW, 0x15, nr15(o)), (48 + RESET_ROW, 0x68, n68), (48 + RESET_ROW, 0x6B, n6b)]


L2_BANK = 8


def regs():
    """(register, value) pairs, in the probe's order, before the sprites: palettes, transparency, fallback,
    Layer 2's mode and clip, band 0's registers."""
    r = [(0x43, 0x00), (0x40, 0x07), (0x41, ULA_INK7), (0x40, 0x10), (0x41, ULA_PAPER0)]
    for p, c in ULA_PAPERS.items():
        r += [(0x40, 0x10 + p), (0x41, c)]
    r += [(0x43, 0x10), (0x40, 0x10)] + [(0x41, c) for c in L2_COLOURS] + [(0x40, T), (0x41, T)]
    r += [(0x43, 0x00), (0x14, T), (0x4A, FALLBACK), (0x4B, T), (0x12, L2_BANK), (0x70, 0x00), (0x16, 0),
          (0x17, 0), (0x71, 0), (0x1C, 0x0F), (0x18, 0), (0x18, 255), (0x18, 0), (0x18, 191),
          (0x19, 0), (0x19, 255), (0x19, 0), (0x19, 255)]
    o, n68, n6b = BANDS[0]
    return r + [(0x15, nr15(o)), (0x68, n68), (0x6B, n6b)]


def sprite_palette():
    return list(range(256))                    # identity: entry i is colour i
