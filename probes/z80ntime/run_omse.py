"""Run Z80NTIME.TAP on omse-ai's 48K and print the screen it leaves (a check of the probe's own machinery).

  run_omse.py OMSE_AI_DIR [TAP]

With the standard omse-ai the Z80N opcodes are a Zilog's 8 T no-ops, so every 3.5 MHz cell should read 8 (JP (C)
falls through to its own loop). With the scratch build that sets the z80n flag (OMSE_Z80N=1), the 3.5 MHz cells
and the flags should read what omse-ai's Z80N predicts. NEXTREG does nothing on a 48K, so the 28 MHz section is
still at 3.5 MHz there and means nothing.
"""
import sys
from pathlib import Path

omse = Path(sys.argv[1]).resolve()
tap = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parent / 'build' / 'Z80NTIME.TAP')
sys.path.insert(0, str(omse))
from speccy import Speccy  # noqa: E402

zx = Speccy()
zx.insert_tape(tap.read_bytes())
zx.type('LOAD ""\n')
zx.run(400)                                         # (it waits for a key at the end)
print(zx.screen_text())
zx.shot(str(Path(__file__).resolve().parent / 'build' / f'omse-{omse.name}-{tap.stem}.png'))
zx.hold('SPACE', 10)                                # the key it asks for: then it returns to BASIC
zx.wait_ready(max_frames=50 * 10)
zx.run(50)
print('after the key:', zx.screen_text().rstrip().splitlines()[-1].strip())
