"""Trace Z80NTIME's tests on omse-ai: which test, how many loops, and where it goes if it's lost.
  trace_omse.py OMSE_AI_DIR"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from speccy import Speccy  # noqa: E402
syms = {}
for line in open(HERE / 'build' / 'z80ntime.sym'):
    p = line.split()
    if len(p) >= 3 and p[1] == 'EQU':
        syms[p[0]] = int(p[2].rstrip('H'), 16)
names = {v: k for k, v in syms.items()}
zx = Speccy()
zx.insert_tape((HERE / 'build' / 'Z80NTIME.TAP').read_bytes())
zx.type('LOAD ""')
zx.keystroke('ENTER')
zx.run_until(syms['run_table'], frames=300)
for i in range(400):
    got = zx.run_until(syms['measure'], syms['m_done'], syms['report'], syms['fl1'], frames=20)
    r = zx.regs()
    if got is None:
        print('\nlost', {x: hex(r[x]) for x in ('pc', 'sp', 'iy', 'ix', 'hl', 'de', 'bc')})
        break
    if got in (syms['report'], syms['fl1']):
        print('\n' + names[got])
        if got == syms['fl1']:
            continue
        break
    if got == syms['measure']:
        print(names.get(r['hl'], hex(r['hl'])), end=' ')
    else:
        print(r['iy'], end='  ', flush=True)
