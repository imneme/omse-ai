"""P-V2 the sprite card: the scene, defined once (PV2-`docs/next/DESIGN.md`).

pv2.asm's data (pv2_data.inc), the model's prediction (pv2_model.py) and the test
(test_next_video.Probes.test_pv2_sprite_card) all come from here. Hatch Fern, Fri 6 Nov 2026.
"""
T = 0xE3                                   # transparent (NR 0x4B default, zxnext:4955)
W_, R_, G_, B_, Y_, K_ = 0xFF, 0xE0, 0x1C, 0x03, 0xFC, 0x00


def pattern_grid():
    """16x16: white border and lines every 4 px; quadrants red, green / blue, yellow: shows orientation and
    makes each scale's repeat countable."""
    p = []
    for y in range(16):
        for x in range(16):
            if x in (0, 15) or y in (0, 15) or x % 4 == 0 or y % 4 == 0:
                p.append(W_)
            else:
                p.append([[R_, G_], [B_, Y_]][y // 8][x // 8])
    return p


def pattern_f():
    """An asymmetric F in yellow with a red corner dot (top right); the rest transparent."""
    rows = ["................",
            ".YYYYYYYYYYY..R.",
            ".YYYYYYYYYYY....",
            ".YY.............",
            ".YY.............",
            ".YYYYYYYY.......",
            ".YYYYYYYY.......",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            ".YY.............",
            "................"]
    return [{'Y': Y_, 'R': R_, '.': T}[c] for r in rows for c in r]


def pattern_solid():
    """Solid with a black outline; the palette offset (top nibble) colours it: entries 0x01, 0x11, ..."""
    return [K_ if x in (0, 15) or y in (0, 15) else 0x01 for y in range(16) for x in range(16)]


PATTERNS = [pattern_grid(), pattern_f(), pattern_solid()]          # patterns 0, 1, 2


def spr(x, y, pat, pal=0, xm=0, ym=0, rot=0, vis=1, five=None):
    """A 4- or 5-byte attribute list (sprites.vhd:381-437): x, y, pal|xm|ym|rot|x8, vis|e|pattern[, a4]."""
    a2 = (pal << 4) | (xm << 3) | (ym << 2) | (rot << 1) | ((x >> 8) & 1)
    a3 = (vis << 7) | (0x40 if five is not None else 0) | (pat & 0x3F)
    return [x & 0xFF, y & 0xFF, a2, a3] + ([five] if five is not None else [])


def sprites():
    """(index, attributes) for the card. Rows are wvc = paper row + 32; whc = paper x + 32."""
    s = {}
    # A. anchors (rows 0-31): composite at left, unified (rotate, x mirror, 2x) at right; three relatives each
    s[0] = spr(40, 34, 0, five=0x00)                      # composite anchor: grid
    s[1] = spr(16, 0, 0, pal=1, five=0x40)                # relative: right of it, palette shifted
    s[2] = spr(0, 16, 1, five=0x40)                       # relative: below it, the F
    s[3] = spr(16, 16, 0, xm=1, five=0x40)                # relative: diagonal, its own x mirror
    s[4] = spr(180, 34, 0, xm=1, rot=1, five=0x20)        # unified anchor: rotated and x-mirrored
    s[5] = spr(16, 0, 1, five=0x40)                       # relatives turn with it (and scale)
    s[6] = spr(0, 16, 1, pal=2, five=0x40)
    s[7] = spr(16, 16, 0, five=0x40)
    # B. scales (rows 32-63): X 1/2/4/8 (16, 32, 64, 128 wide) and Y 2x (32 tall), the grid pattern
    for i, (x, sc) in enumerate([(36, 0), (56, 1), (92, 2), (160, 3)]):
        s[8 + i] = spr(x, 66, 0, five=sc << 3)
    s[12] = spr(292, 66, 0, five=1 << 1)
    # C. eight orientations of the F (rows 64-95): index bits = rot, xm, ym
    for k in range(8):
        s[15 + k] = spr(44 + k * 32, 100, 1, rot=(k >> 2) & 1, xm=(k >> 1) & 1, ym=k & 1)
    # D. priority bands (rows 96-143, 12 rows each, copper sets NR 0x15): a sprite crossing the Layer 2
    #    stripe column and the ULA checker in each band, plus an overlapping pair (lower index under)
    for b in range(4):
        s[23 + 2 * b] = spr(60, 128 + 12 * b, 2, pal=3 + b)
        s[24 + 2 * b] = spr(140 + 8 * b, 128 + 12 * b, 2, pal=8 + b)
    s[31] = spr(200, 130, 2, pal=12)
    s[32] = spr(208, 134, 2, pal=13)                      # covers 31's lower right (zero-on-top is off)
    # E. the border and the clip (rows 144-159): half over the left border
    s[33] = spr(0, 178, 0)
    s[34] = spr(24, 178, 1)
    # F. the per-line strip (rows 160-175): 32 sprites at 8x, 8 px apart, a palette step each
    for i in range(32):
        s[96 + i] = spr(8 * i, 194, 2, pal=i % 16, five=3 << 3)
    return s


NR15 = 0x23                                               # sprites on, over the border, border clip (SLU)
ORDERS = [0, 1, 2, 4]                                     # SLU, LSU, SUL, USL in the four bands
CLIP19 = (4, 155, 0, 255)                                 # whc 8-311: cuts the border sprite and the strip


def copper_words():
    """WAIT (row - 1, 44) / MOVE NR 0x15 for each priority band, then SLU at row 144 (as PV1)."""
    w = []
    for b, o in enumerate(ORDERS):
        w += [0xD800 | (96 + 12 * b - 1), 0x1500 | NR15 | (o << 2)]
    w += [0xD800 | 143, 0x1500 | NR15, 0xFFFF]
    return w


def schedule():
    """The copper list as the model's row schedule (frame9 rows = paper rows + 48)."""
    out = [(48 + 96 + 12 * b, 0x15, NR15 | (o << 2)) for b, o in enumerate(ORDERS)]
    return out + [(48 + 144, 0x15, NR15)]


def sprite_palette():
    """Sprite first palette: identity (0x00-0xFF -> that colour) except entries x1 (the solid pattern's
    0x01 + offset), given distinct bright colours per palette offset."""
    pal = list(range(256))
    solid = [0xE0, 0xFC, 0x1C, 0x1F, 0x03, 0xE7, 0xF0, 0x9C, 0x8F, 0x6D, 0xB6, 0x52, 0xF3, 0x7C, 0x4B, 0xDA]
    for off in range(16):
        pal[(off << 4) | 0x01] = solid[off]
    return pal
