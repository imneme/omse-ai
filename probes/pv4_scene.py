"""P-V4 the Layer 2 card: the scene, defined once.

pv4.asm's data (pv4_data.inc), the model's picture (pv4_model.py) and the test (test_next_video.ProbeV4) all
come from here. Hatch Fern, Fri 6 Nov 2026.

Twelve 16-row bands. In each, the copper sets Layer 2's resolution and palette offset (NR 0x70), its bank
(NR 0x12), its scroll (NR 0x17, NR 0x16) and whether it shows (NR 0x69 b7), over one image in banks 8-10:
byte (y, x) = (y + x / 4) & FF, through an identity palette. The card touches no memory but banks 8-10 (as
P-V1 and P-V2 did): the clip window keeps the wide modes to their first 192 columns, which live there, and
the two "past the end" bands need no memory at all. Each band is labelled in the ULA on the right.
"""
from pathlib import Path

L2_BANK = 8
ULA_ATTR = 0x0F                 # ink 7 on paper 1, every cell
ULA_INK7, ULA_PAPER1 = 0xFF, 0x02
CLIP18 = (0, 95, 0, 255)        # 256 x 192: x 0-95; the wide modes: whc 0-191 (layer2:129-135)
LABEL_COL = 21

# (resolution, palette offset, NR 0x12 bank, NR 0x17, NR 0x16, Layer 2 on, label)
BANDS = [
    (0, 0, 8, 0, 0, 1, '256 ref'),
    (1, 0, 8, 0, 0, 1, '320x8'),
    (2, 0, 8, 0, 0, 1, '640 r10'),
    (3, 0, 8, 0, 0, 1, '640 r11=r10'),      # layer2:41, 198, 202: bit 1 alone picks 640x4
    (0, 0, 0x70, 0, 0, 1, 'bank70 none'),  # bank_eff 80h: address bit 21, transparent (layer2:172-175)
    (2, 0, 0x70, 0, 0, 1, '640 70 none'),
    (0, 0, 8, 100, 0, 1, 'y+100 wrap'),     # rows 96-111: vc + 100 >= 192, so rows 4-19 (layer2:156-158)
    (2, 3, 8, 0, 0, 1, '640 off 3'),        # offset added to the nibble's empty top (layer2:202-203)
    (3, 3, 8, 0, 0, 1, 'r11 off3=r7'),
    (0, 0, 6, 255, 0, 1, 'b6 y255=r79'),    # vc + 255 >= 384: y - 192 once is 207-222, bank 6 + 3 = 9
    (0, 0, 8, 0, 100, 1, 'x+100'),
    (0, 0, 8, 0, 0, 0, 'L2 off'),
]
RESET_ROW = 200


assert all(len(b[6]) <= 32 - LABEL_COL for b in BANDS), 'a label runs past column 31'


def band_regs(b):
    res, off, bank, sy, sx, on, _ = BANDS[b]
    return [(0x70, (res << 4) | off), (0x12, bank), (0x17, sy), (0x16, sx), (0x69, 0x80 if on else 0x00)]


def layer2():
    """Banks 8-10: 256 x 192, byte (y, x) = (y + x // 4) & 0xFF."""
    return bytes((y + (x >> 2)) & 0xFF for y in range(192) for x in range(256))


def labels():
    """(row, col, text) for the probe's pstr: each band's label on its first character row, and the
    prompt that probe.inc's finish prints on row 23."""
    out = [(2 * b, LABEL_COL, BANDS[b][6]) for b in range(12)]
    return out + [(23, 0, 'Photo, please. Key: soft reset')]


def ula():
    """The bitmap the probe prints (the ROM font, as probe.inc's getfont copies it) and the attributes."""
    rom = (Path(__file__).resolve().parent.parent / 'roms' / '48.rom').read_bytes()
    bm = bytearray(6144)
    for row, col, text in labels():
        for k, ch in enumerate(text):
            for line in range(8):
                a = ((row & 0x18) << 8) | (line << 8) | ((row & 7) << 5) | (col + k)
                bm[a] = rom[0x3D00 + (ord(ch) - 32) * 8 + line]
    return bytes(bm), bytes([ULA_ATTR] * 768)


def regs():
    """(register, value) pairs in the probe's order: the ULA and Layer 2 palettes, transparency, fallback,
    Layer 2's clip and x scroll MSB, band 0's registers."""
    r = [(0x43, 0x00), (0x40, 0x07), (0x41, ULA_INK7), (0x40, 0x11), (0x41, ULA_PAPER1),
         (0x43, 0x10), (0x40, 0x00)] + [(0x41, i) for i in range(256)]
    r += [(0x43, 0x00), (0x14, 0xE3), (0x4A, 0x00), (0x71, 0x00), (0x1C, 0x01)] + [(0x18, v) for v in CLIP18]
    return r + band_regs(0)


def copper_words():
    """For each band after the first: WAIT (row - 1, 44), then its five MOVEs; band 0's again at RESET_ROW;
    then halt (mode 11 restarts it each frame)."""
    w = []
    for b in list(range(1, 12)) + [0]:
        row = 16 * b if b else RESET_ROW
        w += [0xD800 | (row - 1)] + [(n << 8) | v for n, v in band_regs(b)]
    return w + [0xFFFF]


def schedule():
    """The copper list as the model's row schedule (frame9 rows = paper rows + 48)."""
    out = []
    for b in list(range(1, 12)) + [0]:
        row = 16 * b if b else RESET_ROW
        out += [(48 + row, n, v) for n, v in band_regs(b)]
    return out
