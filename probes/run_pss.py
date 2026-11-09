"""Run PSS on omse-ai's Spectrum Next core through both photos, with the port enables the test machine had under
NextZXOS (P-1: NR 0x82-0x85 = FF FF FF 8F), and check what the tape puts back.

  run_pss.py [--worktree DIR] [--png PATH]

Prints photo 1's screen as text; samples photo 2's border and paper colours (9-bit RRRGGGBBB) and saves it as a
PNG; then lets the tape restore and reset, and reads back the two palette entries it borrowed. Builds on Kelp
Fern's run_next_probe.py. Needs OMSE_AI_NEXT_ROMS. Hart's-tongue Fern, Fri 06 Nov 2026.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('--worktree', default=str(HERE.parent))
ap.add_argument('--png', default=str(HERE / 'build' / 'pss-photo2.png'))
a = ap.parse_args()
sys.path.insert(0, a.worktree)
from next import Next  # noqa: E402

code = (HERE / 'build' / 'pss.bin').read_bytes()
syms = {}
for line in (HERE / 'build' / 'pss.sym').read_text().splitlines():
    m = re.match(r'(\w+)\s+EQU\s+0?([0-9A-Fa-f]+)H', line)
    if m:
        syms[m.group(1).lower()] = int(m.group(2), 16)
FRAME = 70908 * 8

zx = Next(timing='p3', boot='fast')
for r, v in zip((0x82, 0x83, 0x84, 0x85), (0xFF, 0xFF, 0xFF, 0x8F)):
    zx.nr_write(r, v)


def palette(idx):
    zx.nr_write(0x43, 0x00)
    zx.nr_write(0x40, idx)
    return zx.nr_read(0x41), zx.nr_read(0x44)


before = {i: palette(i) for i in (56, 130)}
regs_before = [zx.nr_read(r) for r in (0x03, 0x05, 0x42, 0x4A)]
zx.load(0x8000, code)
zx.set_regs(pc=0x8000, sp=0xBFF0)


def screen():
    font = zx.read(0xB000, 96 * 8)
    glyphs = {bytes(font[i * 8:i * 8 + 8]): chr(32 + i) for i in range(96)}
    scr = zx.read(0x4000, 6144)
    for r in range(24):
        row = ''
        for c in range(32):
            cell = bytes(scr[((r & 0x18) << 8) | ((r & 7) << 5) | c | (k << 8)] for k in range(8))
            row += glyphs.get(cell, '?')
        print(row.rstrip())


SPACE = [0, 0, 0, 0, 0, 0, 0, 0x01]                 # row 7, bit 0


def key(until):
    """As her finger does it: no key for a frame (waitkey first waits for release), then a press held until the
    tape reaches `until`, then let go."""
    zx.set_keys([0] * 8)
    zx.run_frames(1)
    zx.set_keys(SPACE)
    ok = zx.run_until_pc(until, max_ticks=60 * FRAME)
    zx.set_keys([0] * 8)
    return ok


print('photo 1 reached:', zx.run_until_pc(syms['waitkey'], max_ticks=900 * FRAME), 'frame', zx.frame)
screen()
print('photo 2 reached:', key(syms['waitkey']), 'frame', zx.frame)
zx.run_frames(2)
screen()
w, h, f9 = zx.frame9()
at = lambda x, y: f9[y * w + x]
print(f'photo 2 colours (9-bit): border {at(20, 20):03o}  paper {at(96 + 2 * 250, 48 + 180):03o}  '
      f'(yellow 774, green 034, red/standard {0o700:03o}-ish, white 777)')
zx.image(a.png)
print('saved', a.png)
print('reset reached:', key(syms['softreset']))
after = {i: palette(i) for i in (56, 130)}
print('palette 56, 130 before:', before, ' after:', after, ' restored' if before == after else ' NOT RESTORED')
regs_after = [zx.nr_read(r) for r in (0x03, 0x05, 0x42, 0x4A)]
print('NR 03 05 42 4A before:', [hex(v) for v in regs_before], ' at the reset:', [hex(v) for v in regs_after],
      ' restored' if regs_before == regs_after else ' DIFFERENT')
