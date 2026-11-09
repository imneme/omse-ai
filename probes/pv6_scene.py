"""P-V6 the deadline: the scene, defined once.

pv6.asm's data, the model's picture (pv6_model.py) and the test (test_next_video.ProbeV6) all come from here.
Hatch Fern, Fri 6 Nov 2026.

PV5 showed the real Next draws whole sprites only: a sprite is drawn if it can finish by a deadline D after
the line reset, 1265 <= D <= 1297 cycles (counting "finishes" as the next free cycle: START at 1, the first
qualify at 2, then 1 cycle per sprite qualified and 1 per pixel drawn; readings-sitting3-pv5.md). PV6 asks:
  * D to a few cycles: six rows, each a block of wide sprites (all certain to fit), then four 1x sprites
    17 cycles apart whose thresholds straddle the window; the rows' offsets differ, so their counts of 1x
    sprites drawn bracket D;
  * skip or stop: one row (sprites 0-14, first in order) draws 9 sprites at 8x and one at 2x, then an 8x
    sprite that cannot fit, then four 1x sprites that would all fit if the engine skips past a dropped
    sprite. Drawn: it skips (and a dropped sprite costs only its qualify). Not drawn: it stops (or a
    dropped sprite costs its whole time).
All 128 slots are written; the spare ones are invisible and come last.
"""
NR15 = 0x23
CLIP19 = (4, 155, 0, 255)               # whc 8-311
COST = {0: 17, 1: 33, 2: 65, 3: 129}   # qualify + pixels, by scale (1x, 2x, 4x, 8x)
WINDOW = (1265, 1297)
X1 = [220, 240, 260, 280]               # the four 1x sprites' x (whc), each row
SKIP_ROW = 40                           # wvc (paper row 8)
D_ROWS = [64, 88, 112, 136, 160, 184]  # wvc, the six deadline rows (paper rows 32-167)


def plan():
    """[(wvc, [(scale, x) or ('pad', 0) ...])] in index order: the skip row, then the six deadline rows. Each
    deadline row's block is chosen so the next free cycle before its 1x sprites (its base) is in 1230-1250,
    with invisible padding sprites (one cycle each) to put the bases' offsets mod 17 where they should be."""
    rows = []
    skip = [(3, 8 * i) for i in range(9)] + [(1, 176), (3, 96)] + [(0, x) for x in X1]
    rows.append((SKIP_ROW, skip))
    used = len(skip)
    targets = [0, 3, 6, 9, 12, 15]          # base mod 17 wanted, one per row (about 3 cycles apart)
    spare = 128 - used - 6 * 4
    for r, wvc in enumerate(D_ROWS):
        best = None
        for n8 in range(5, 10):
            for n4 in range(0, 4):
                for n2 in range(0, 4):
                    for n1 in range(0, 3):
                        for pad in range(0, 17):
                            base = 2 + used + pad + 129 * n8 + 65 * n4 + 33 * n2 + 17 * n1
                            if not 1230 <= base <= 1250:
                                continue
                            size = n8 + n4 + n2 + n1 + pad
                            if size > (128 - used) // (6 - r) - 4:   # a fair share of the slots left
                                continue
                            miss = min((base - targets[r]) % 17, (targets[r] - base) % 17)
                            key = (miss, size)
                            if best is None or key < best[0]:
                                best = (key, n8, n4, n2, n1, pad)
        _, n8, n4, n2, n1, pad = best
        block = [('pad', 0)] * pad + [(3, 8 * i) for i in range(n8)] + [(2, 8 * n8 + 8 * i) for i in range(n4)] + \
                [(1, 8 * (n8 + n4) + 8 * i) for i in range(n2)] + [(0, 8 * (n8 + n4 + n2) + 8 * i) for i in range(n1)]
        row = block + [(0, x) for x in X1]
        rows.append((wvc, row))
        used += len(row)
        spare -= n8 + n4 + n2 + n1 + pad
    assert used <= 128, used
    return rows


def sprites():
    """All 128 slots, five bytes each: palette offset steps by sprite along each row."""
    s, idx = {}, 0
    for wvc, row in plan():
        for k, (scale, x) in enumerate(row):
            if scale == 'pad':
                s[idx] = [0, 0, 0, 0x40, 0]         # invisible: one qualify cycle
            else:
                s[idx] = [x & 0xFF, wvc, ((k * 5 + 3) % 16) << 4 | (x >> 8), 0xC0, scale << 3]
            idx += 1
    for i in range(idx, 128):
        s[i] = [0, 0, 0, 0x40, 0]
    return s


def sprite_palette():
    pal = list(range(256))
    solid = [0xE0, 0xFC, 0x1C, 0x1F, 0x03, 0xE7, 0xF0, 0x9C, 0x8F, 0x6D, 0xB6, 0x52, 0xF3, 0x7C, 0x4B, 0xDA]
    for off in range(16):
        pal[(off << 4) | 0x01] = solid[off]
    return pal


def pattern_solid():
    return [0x00 if x in (0, 15) or y in (0, 15) else 0x01 for y in range(16) for x in range(16)]


PATTERNS = [pattern_solid()]
STATUS_ROW = 0                          # clear of every row and of the prompt


def ula():
    return bytes(6144), bytes([0x07] * 768)


def regs():
    r = [(0x43, 0x00), (0x40, 0x07), (0x41, 0xFF), (0x40, 0x10), (0x41, 0x00), (0x40, 0x11), (0x41, 0x02),
         (0x14, 0xE3), (0x4A, 0x00), (0x4B, 0xE3), (0x1C, 0x02)]
    return r + [(0x19, v) for v in CLIP19]


def schedule():
    return []


def predict(D, mode):
    """The whole-sprite rule: per row, how many of its four 1x sprites draw, for deadline D ('finishes' =
    next free cycle) and mode 'skip' (a dropped sprite costs its qualify) or 'stop'."""
    out = []
    for wvc, _ in plan():
        t, stopped, drawn1x = 2, False, 0
        idx_rows = [(w, row) for w, row in plan()]
        for w, row in idx_rows:
            for scale, x in row:
                if w != wvc or scale == 'pad':
                    t += 1                          # qualify only: not on this row, or invisible
                    continue
                if stopped:
                    continue
                if t + COST[scale] <= D:
                    t += COST[scale]
                    if scale == 0 and x in X1:
                        drawn1x += 1
                else:
                    if mode == 'stop':
                        stopped = True
                    else:
                        t += 1
        out.append(drawn1x)
    return out
