"""What the VHDL says P-V1 looks like on a Next: the model's picture of the probe's scene.

  pv1_model.py            writes build/pv1-ula.bin (the ULA screen, from a run on omse-ai's 48K) once, then
                          build/pv1-vhdl.png (the model's frame, 2x) for the photograph to be held against.

The scene is pv1.asm's: its register list, its Layer 2 rule (ported line for line), its ULA screen (which uses
nothing Next-specific, so the 48K run's screen memory is the Next's too), border 1, and the copper list as a
row schedule (each MOVE lands in the blanking before its band). Hatch Fern, Fri 06 Nov 2026.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
import nextvideo as nv  # noqa: E402

REGS = [(0x43, 0x00), (0x40, 0x00), (0x41, 0x00), (0x40, 0x07), (0x41, 0xFF), (0x40, 0x10), (0x41, 0x00),
        (0x40, 0x11), (0x41, 0x02), (0x40, 0x15), (0x41, 0x1F), (0x40, 0x17), (0x41, 0xE3),
        (0x43, 0x10), (0x40, 0xE3), (0x41, 0xE3), (0x40, 0xE0), (0x41, 0xE0), (0x40, 0x00), (0x41, 0x00),
        (0x40, 0xFC), (0x44, 0xFC), (0x44, 0x80), (0x43, 0x00), (0x14, 0xE3), (0x4A, 0x49), (0x15, 0x00),
        (0x68, 0x00), (0x70, 0x00), (0x16, 0x00), (0x17, 0x00), (0x71, 0x00),
        (0x1C, 0x01), (0x18, 0x00), (0x18, 0xFF), (0x18, 0x00), (0x18, 0xBF)]
SCHEDULE = [(48 + 16 * b, 0x15, b << 2) for b in range(1, 8)] + [(48 + 128, 0x15, 0x00)]
COPPER = [(0xD800 | (16 * b - 1), 0x1500 | (b << 2)) for b in range(1, 8)] + [(0xD87F, 0x1500)]


def layer2():
    """pv1.asm's l2row, for Y = 0-191, X = 0-255."""
    out = bytearray(256 * 192)
    for y in range(192):
        for x in range(256):
            if y < 128:
                if x < 128:
                    if 96 <= x < 120 and 4 <= (y & 15) < 12:
                        p = 0xFC
                    else:
                        p = 0xE0 if ((x + y) & 15) < 6 else 0xE3
                else:
                    p = 0x00 if y >= 96 else 0xE3
            elif y < 144:
                p = 0xE0 if (x & 15) == 0 else 0xE3
            elif y < 160:
                p = 0xE0 if (x & 15) == 1 else 0xE3
            else:
                p = 0xE3
            out[y * 256 + x] = p
    return bytes(out)


def ula_screen():
    path = HERE / 'build' / 'pv1-ula.bin'
    if not path.exists():
        sys.path.insert(0, str(HERE.parent))
        from speccy import Speccy
        zx = Speccy(model=48)
        zx.insert_tape(str(HERE / 'build' / 'PV1.TAP'))
        zx.type('LOAD ""\n')
        f0 = zx.frame
        while zx.frame - f0 < 1500 and 'Photo' not in zx.screen_text():
            zx.run(10)
        zx.run(5)
        path.write_bytes(bytes(zx.mem[0x4000:0x5B00]))
    return path.read_bytes()


def scene_model(l2_bank=8):
    v = nv.Video()
    for n, val in REGS:
        v.nr_write(n, val)
    v.nr_write(0x12, l2_bank)
    v.io_out(0x123B, 0x02)
    v.io_out(0xFE, 0x01)
    v.bram5[0:6912] = ula_screen()
    base = nv.L2_SRAM_BASE + l2_bank * 0x4000
    v.sram[base:base + 49152] = layer2()
    return v


if __name__ == '__main__':
    from PIL import Image
    w, h, f = scene_model().frame9(SCHEDULE)
    im = Image.new('RGB', (w, h))
    im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in f])
    im = im.resize((w, h * 2), Image.NEAREST)          # square-ish pixels: 2 samples across, 1 line down
    im.save(HERE / 'build' / 'pv1-vhdl.png')
    print('wrote build/pv1-vhdl.png', len(set(f)), 'colours')
