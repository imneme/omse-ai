"""Run a probe tape on omse-ai's 48K (not a Next: every Next register reads FF there and writes go nowhere), to
check the tape loads, runs to its last screen and lays out right. Prints the screen as text; --png saves it.

  run_probe.py build/P1.TAP [--png OUT.png] [--keys W]    (--keys: a key to press at the end, e.g. W for P-2)

Hart's-tongue Fern, Fri 06 Nov 2026.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from speccy import Speccy  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('tap')
ap.add_argument('--png')
ap.add_argument('--frames', type=int, default=1500)
ap.add_argument('--keys', default='')
a = ap.parse_args()
zx = Speccy(model=48)
zx.insert_tape(a.tap)
zx.type('LOAD ""\n')
f0 = zx.frame
while zx.frame - f0 < a.frames and 'Photo' not in zx.screen_text():
    zx.run(10)
zx.run(5)
print(f'after {zx.frame - f0} frames:')
print(zx.screen_text())
if a.png:
    zx.image(border=True, scale=2).save(a.png)
if a.keys:
    zx.tap(a.keys.upper() if len(a.keys) > 1 else a.keys.upper())
    zx.run(50)
    print('--- after the key:')
    print(zx.screen_text())
