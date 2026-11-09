"""What the VHDL says P-V3 looks like: the model's picture of the blend card (pv3_scene.py).

  pv3_model.py        writes build/pv3-vhdl.png (2x tall) and prints the expected read-backs.

Row 22's text (the read-backs the probe prints) isn't drawn here; VIDEO-NOTES lists its expected values.
Hatch Fern, Fri 6 Nov 2026.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
sys.path.insert(0, str(HERE))
import nextvideo as nv  # noqa: E402
import pv3_scene as sc  # noqa: E402


def writes():
    """The card's register and port writes, in the probe's order: [(kind, a, b)]. Ends with the read-back
    setups: NR 0x44's first byte A5 (NR 0x28 then reads A5) and NR 0x34 = 100 with one NR 0x75 step (NR 0x34
    then reads 101; sprite 100 stays invisible)."""
    w = [('nr', a, b) for a, b in sc.regs()]
    w += [('nr', 0x43, 0x20), ('nr', 0x40, 0x00)] + [('nr', 0x41, c) for c in sc.sprite_palette()]
    w += [('nr', 0x43, 0x00), ('io', 0x303B, 0x00)] + [('io', 0x5B, b) for p in sc.PATTERNS for b in p]
    for idx, attrs in sorted(sc.sprites().items()):
        w += [('io', 0x303B, idx)] + [('io', 0x57, b) for b in attrs]
    w += [('io', 0x123B, 0x02), ('io', 0x00FE, 0x00)]
    w += [('nr', 0x43, 0x00), ('nr', 0x40, 0xF0), ('nr', 0x44, 0xA5), ('nr', 0x34, 100), ('nr', 0x75, 0x00)]
    return w


def scene_model():
    v = nv.Video()
    for kind, a, b in writes():
        (v.nr_write if kind == 'nr' else v.io_out)(a, b)
    bm, at = sc.ula()
    v.bram5[0:6144], v.bram5[0x1800:0x1B00] = bm, at
    base = nv.L2_SRAM_BASE + sc.L2_BANK * 0x4000
    v.sram[base:base + 49152] = sc.layer2()
    return v


if __name__ == '__main__':
    from PIL import Image
    v = scene_model()
    w, h, f = nv.frame9_np(v, sc.schedule())
    im = Image.new('RGB', (w, h))
    im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in f])
    im.resize((w, h * 2), Image.NEAREST).save(HERE / 'build' / 'pv3-vhdl.png')
    print('wrote build/pv3-vhdl.png;', len(set(f)), 'colours; expected NR 0x28 %02X, NR 0x34 %02X, status %02X'
          % (v.nr_read(0x28), v.nr_read(0x34), nv.sprite_status(v)))
