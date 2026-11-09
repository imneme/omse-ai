"""Run a probe's code on omse-ai's Spectrum Next core (next.py), from boot='fast' (the firmware's state, CPU at 0),
to its "photo, then press a key" pause, and print the screen as text, read back through the probe's own copy of
the ROM font (FONTBUF, probe.inc). Unlike run_probe.py's 48K, the Next registers are real here.

  run_next_probe.py N [--worktree DIR] [--speed S]      (N: build/pN.bin and build/pN.sym, from build_probes.py)

Needs OMSE_AI_NEXT_ROMS (the distribution's machines/next folder). Kelp Fern, Fri 06 Nov 2026.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('n')
ap.add_argument('--worktree', default=str(HERE.parent))
ap.add_argument('--max-frames', type=int, default=600)
a = ap.parse_args()
sys.path.insert(0, a.worktree)
from next import Next  # noqa: E402

code = (HERE / 'build' / f'p{a.n}.bin').read_bytes()
syms = {}
for line in (HERE / 'build' / f'p{a.n}.sym').read_text().splitlines():
    m = re.match(r'(\w+)\s+EQU\s+0?([0-9A-Fa-f]+)H', line)
    if m:
        syms[m.group(1).lower()] = int(m.group(2), 16)
wait = syms['waitkey']

zx = Next(timing='p3', boot='fast')
zx.load(0x8000, code)
zx.set_regs(pc=0x8000, sp=0xBFF0)
frame_t28 = 70908 * 8
ok = zx.run_until_pc(wait, max_ticks=a.max_frames * frame_t28)
print(f'reached waitkey: {ok}, after {zx.frame} frames')

font = zx.read(0xB000, 96 * 8)
glyphs = {bytes(font[i * 8:i * 8 + 8]): chr(32 + i) for i in range(96)}
scr = zx.read(0x4000, 6144)
for r in range(24):
    row = ''
    for c in range(32):
        cell = bytes(scr[((r & 0x18) << 8) | ((r & 7) << 5) | c | (k << 8)] for k in range(8))
        row += glyphs.get(cell, '?')
    print(row.rstrip())
