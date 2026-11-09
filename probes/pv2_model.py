"""What the VHDL says P-V2 looks like: the model's picture of the sprite card (pv2_scene.py).

  pv2_model.py        writes build/pv2-vhdl.png (2x tall), and prints which sprites draw on the strip's line.

The ULA side (checker in the priority rows, labels) and Layer 2's stripe column are defined here and in
pv2.asm alike. The per-line limit is NOT modelled: the strip shows every sprite drawn. Hatch Fern, Fri 6 Nov 2026.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
sys.path.insert(0, str(HERE))
import nextvideo as nv  # noqa: E402
import pv2_scene as sc  # noqa: E402

L2_BANK = 8


def layer2():
    """A red stripe column at x 120-135 in the priority rows (96-143), transparent elsewhere."""
    out = bytearray([0xE3] * (256 * 192))
    for y in range(96, 144):
        for x in range(120, 136):
            out[y * 256 + x] = 0xE0 if (x + y) % 4 < 2 else 0xE3
    return bytes(out)


def ula():
    """Attributes: black paper, white ink; the priority rows' left half a cyan / transparent checker."""
    bm, at = bytearray(6144), bytearray([0x07] * 768)
    for row in range(12, 18):
        for col in range(0, 16):
            at[row * 32 + col] = 0x28 if (row + col) & 1 else 0x38
    for col in range(32):
        at[23 * 32 + col] = 0x30
    return bytes(bm), bytes(at)


def writes():
    """The register and port writes, in the probe's order: [(kind, a, b)]."""
    w = [('nr', 0x43, 0x00), ('nr', 0x40, 0x07), ('nr', 0x41, 0xFF), ('nr', 0x40, 0x10), ('nr', 0x41, 0x00),
         ('nr', 0x40, 0x11), ('nr', 0x41, 0x02), ('nr', 0x40, 0x15), ('nr', 0x41, 0x1F), ('nr', 0x40, 0x17),
         ('nr', 0x41, 0xE3), ('nr', 0x43, 0x20), ('nr', 0x40, 0x00)]
    w += [('nr', 0x41, c) for c in sc.sprite_palette()]
    w += [('nr', 0x43, 0x10), ('nr', 0x40, 0xE0), ('nr', 0x41, 0xE0), ('nr', 0x40, 0xE3), ('nr', 0x41, 0xE3),
          ('nr', 0x43, 0x00), ('nr', 0x14, 0xE3), ('nr', 0x4A, 0x49), ('nr', 0x4B, 0xE3),
          ('nr', 0x12, L2_BANK), ('nr', 0x70, 0x00), ('nr', 0x16, 0), ('nr', 0x17, 0), ('nr', 0x71, 0),
          ('nr', 0x1C, 0x03), ('nr', 0x18, 0), ('nr', 0x18, 255), ('nr', 0x18, 0), ('nr', 0x18, 191)]
    w += [('nr', 0x19, v) for v in sc.CLIP19]
    w += [('io', 0x303B, 0x00)] + [('io', 0x5B, b) for p in sc.PATTERNS for b in p]
    for idx, attrs in sorted(sc.sprites().items()):
        w += [('io', 0x303B, idx)] + [('io', 0x57, b) for b in attrs]
    w += [('nr', 0x15, sc.NR15), ('io', 0x123B, 0x02), ('io', 0x00FE, 0x01)]
    return w


def scene_model():
    v = nv.Video()
    for kind, a, b in writes():
        (v.nr_write if kind == 'nr' else v.io_out)(a, b)
    bm, at = ula()
    v.bram5[0:6144], v.bram5[0x1800:0x1B00] = bm, at
    base = nv.L2_SRAM_BASE + L2_BANK * 0x4000
    v.sram[base:base + 49152] = layer2()
    return v


if __name__ == '__main__':
    from PIL import Image
    v = scene_model()
    w, h, f = nv.frame9_np(v, sc.schedule())
    im = Image.new('RGB', (w, h))
    im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in f])
    im.resize((w, h * 2), Image.NEAREST).save(HERE / 'build' / 'pv2-vhdl.png')
    print('wrote build/pv2-vhdl.png;', len(set(f)), 'colours')
