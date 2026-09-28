#!/usr/bin/env python3
"""A tour of the Python side: type a program in, run it, and find out what it
did as text and numbers first (the screen, the ROM's report, the notes the
beeper played, a colour), then as a picture.

    python3 examples/tour.py            -> prints its findings, and out/tour/scale.png
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speccy                      # noqa: E402
from speccy import Speccy          # noqa: E402

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

zx = Speccy()                      # a 48K, booted to the (c) screen
zx.type('10 PRINT AT 10,6; INK 2; "a C major scale"\n')
zx.type('20 FOR i=1 TO 8: READ n: BEEP 0.2,n: NEXT i\n')
zx.type('30 DATA 0,2,4,5,7,9,11,12\n')
zx.record_audio()
zx.type('RUN\n')
frames = zx.wait_ready()           # until the editor wants a key again
zx.run(50)                         # the report is printed just after that

print(f'RUN took {frames} frames ({frames / zx.fps:.1f} Spectrum-seconds)')
print(f'the ROM reports: {zx.report()}')
print('the screen, read as text (rows as PRINT AT counts them):')
for row, line in enumerate(zx.screen_text().split('\n')):
    if line.strip():
        print(f'  row {row:2}: {line}')
print('the beeper played:')
for start, dur, hz in zx.beeper_notes():
    midi = round(69 + 12 * math.log2(hz / 440))
    print(f'  {start:5.2f} s  {dur:.2f} s  {hz:6.1f} Hz  {NAMES[midi % 12]}{midi // 12 - 1}')
a = zx.peek(22528 + 32 * 10 + 6)   # the attribute of row 10, column 6
print(f'the colour at 10,6: INK {a & 7}, PAPER {(a >> 3) & 7}, BRIGHT {a >> 6 & 1}')
try:
    print('picture:', zx.shot('out/tour/scale.png'))
except speccy.MissingTool as e:     # no Pillow: everything above still works
    print(f'picture: skipped ({e})')
