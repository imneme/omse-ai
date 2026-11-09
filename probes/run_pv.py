"""Run a video probe's own code (build/pvN.bin) on omse-ai's Next core from boot='fast' (the firmware's
state) to its key wait, then: print the text of rows 19-23 (read through the probe's copy of the ROM font),
save the frame as build/pvN-core.png, and count the samples that differ from pvN_model's picture outside
the text the probe printed. Runs the core, never reads it. After Kelp Fern's run_next_probe.py.

  run_pv.py N [--core DIR]          (default core: this repository)

Needs OMSE_AI_NEXT_ROMS. Hatch Fern, Fri 6 Nov 2026.
"""
import argparse
import importlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('n')
ap.add_argument('--core', default=str(HERE.parent))
ap.add_argument('--max-frames', type=int, default=600)
a = ap.parse_args()
sys.path.insert(0, a.core)
sys.path.insert(0, str(HERE.parent / 'tests'))
sys.path.insert(0, str(HERE))
from next import Next  # noqa: E402
import nextvideo as nv  # noqa: E402

code = (HERE / 'build' / f'pv{a.n}.bin').read_bytes()
syms = {}
for line in (HERE / 'build' / f'pv{a.n}.sym').read_text().splitlines():
    m = re.match(r'(\w+)\s+EQU\s+0?([0-9A-Fa-f]+)H', line)
    if m:
        syms[m.group(1).lower()] = int(m.group(2), 16)
zx = Next(timing='p3', boot='fast')
zx.load(0x8000, code)
zx.set_regs(pc=0x8000, sp=0xBFF0)
ok = zx.run_until_pc(syms['waitkey'], max_ticks=a.max_frames * 70908 * 8)
print(f'reached waitkey: {ok}, after {zx.frame} frames')
zx.run_frames(2)

font = zx.read(0xB000, 96 * 8)
glyphs = {bytes(font[i * 8:i * 8 + 8]): chr(32 + i) for i in range(96)}
scr = zx.read(0x4000, 6144)
for row in range(19, 24):
    text = ''
    for col in range(32):
        cell = bytes(scr[((row & 0x18) << 8) | (line << 8) | ((row & 7) << 5) | col] for line in range(8))
        text += glyphs.get(cell, '?' if any(cell) else ' ')
    print(f'{row:2d} |{text}|')

w, h, got = zx.frame9()
from PIL import Image  # noqa: E402
im = Image.new('RGB', (w, h))
im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in got])
im.resize((w, h * 2), Image.NEAREST).save(HERE / 'build' / f'pv{a.n}-core.png')
pm = importlib.import_module(f'pv{a.n}_model')
sc = importlib.import_module(f'pv{a.n}_scene')
want = nv.frame9_np(pm.scene_model(), sc.schedule())[2]
text = set()                                    # the probe's printed pixels (the model has no text)
for y in range(192):
    for x in range(256):
        byte = scr[((y >> 6) << 11) | ((y & 7) << 8) | (((y >> 3) & 7) << 5) | (x >> 3)]
        if (byte >> (7 - (x & 7))) & 1:
            i = (48 + y) * w + 96 + 2 * x
            text |= {i, i + 1}
bad = [i for i in range(len(want)) if got[i] != want[i] and i not in text]
print(f'build/pv{a.n}-core.png; {len(bad)} samples differ from the model, outside the printed text'
      + (f', first at ({bad[0] % w},{bad[0] // w})' if bad else ''))
if bad:
    rows = sorted({i // w for i in bad})
    print(f'  in frame rows {rows[0]}-{rows[-1]} ({len(rows)} rows; paper rows {rows[0] - 48}-{rows[-1] - 48})')
