"""What the VHDL says P-V5 looks like: the model's picture of the budget ruler (pv5_scene.py), and where each
strip's line runs out by the VHDL reading.

  pv5_model.py        writes build/pv5-vhdl.png (2x tall) and prints each strip's last sprite and pixel.

The status line the probe prints isn't drawn here. Hatch Fern, Fri 6 Nov 2026.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
sys.path.insert(0, str(HERE))
import nextvideo as nv  # noqa: E402
import pv5_scene as sc  # noqa: E402


def writes():
    """The card's register and port writes, in the probe's order: [(kind, a, b)]."""
    w = [('nr', 0x6B, 0x00), ('nr', 0x15, 0x00), ('nr', 0x68, 0x00), ('nr', 0x43, 0x00)]   # as screen_init
    w += [('nr', a, b) for a, b in sc.regs()]
    w += [('nr', 0x43, 0x20), ('nr', 0x40, 0x00)] + [('nr', 0x41, c) for c in sc.sprite_palette()]
    w += [('nr', 0x43, 0x00), ('io', 0x303B, 0x00)] + [('io', 0x5B, b) for p in sc.PATTERNS for b in p]
    w += [('io', 0x303B, 0x00)]
    for idx in range(128):
        w += [('io', 0x57, b) for b in sc.sprites()[idx]]
    return w + [('nr', 0x15, sc.NR15), ('io', 0x00FE, 0x01)]


def scene_model():
    v = nv.Video()
    for kind, a, b in writes():
        (v.nr_write if kind == 'nr' else v.io_out)(a, b)
    bm, at = sc.ula()
    v.bram5[0:6144], v.bram5[0x1800:0x1B00] = bm, at
    return v


def cuts(v):
    """For each strip: (last sprite drawn, its last pixel in whc, overtime) on its first row."""
    out = {}
    for name, (first, count, scale, step, wvc) in sc.STRIPS.items():
        owners = [None] * 320
        _, over, _ = nv._sprite_line(v, wvc, owners)
        mine = [(x, o) for x, o in enumerate(owners) if o is not None and first <= o < first + count]
        last = max(o for _, o in mine)
        out[name] = (last, max(x for x, o in mine if o == last), over)
    return out


if __name__ == '__main__':
    from PIL import Image
    v = scene_model()
    w, h, f = nv.frame9_np(v, sc.schedule())
    im = Image.new('RGB', (w, h))
    im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in f])
    im.resize((w, h * 2), Image.NEAREST).save(HERE / 'build' / 'pv5-vhdl.png')
    print('wrote build/pv5-vhdl.png; status %02X' % nv.sprite_status(v))
    for name, (last, x, over) in cuts(v).items():
        first, count, scale, step, _ = sc.STRIPS[name]
        print(f'  strip {name}: last sprite {last} (strip index {last - first}), to whc {x}; '
              f'its start whc {step * (last - first)}; overtime {over}')
