"""Build the video probe tapes (PV1.TAP, ...) from pv1.asm, ... beside Hart's-tongue Fern's probes.

  build_pv.py [N ...]        (default: every pvN.asm here)

Same shape as build_probes.py (her BASIC loader: CLEAR 32767 : LOAD "" CODE : RANDOMIZE USR 32768, code at
32768, each source including probe.inc), with Tally Fern's TAP helpers and check_tap from
Strobe Fern's z80ntime/build_probe.py. On the Next: `.tapein pv1.tap`, then LOAD "".
Hatch Fern, Fri 06 Nov 2026.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'z80ntime'))
from build_probe import tap_block, header, check_tap, num, PASMO  # noqa: E402

NAMES = {1: 'pv1-layers', 2: 'pv2-sprites', 3: 'pv3-blends', 4: 'pv4-layer2', 5: 'pv5-ruler', 6: 'pv6-deadline'}


def build(n):
    out = HERE / 'build'
    out.mkdir(exist_ok=True)
    binp, sym = out / f'pv{n}.bin', out / f'pv{n}.sym'
    r = subprocess.run([str(PASMO), '--bin', f'pv{n}.asm', str(binp), str(sym)], cwd=HERE,
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'pv{n}.asm:\n{r.stdout}{r.stderr}')
    code = binp.read_bytes()
    assert len(code) <= 0x1000, f'pv{n}: code is {len(code)} bytes, past 0x8FFF'
    line = bytes([0xFD]) + num(32767) + b':' + bytes([0xEF]) + b'""' + bytes([0xAF]) + b':' + \
        bytes([0xF9, 0xC0]) + num(32768) + b'\r'
    prog = (10).to_bytes(2, 'big') + len(line).to_bytes(2, 'little') + line
    name = NAMES.get(n, f'pv{n}')
    tap = header(0, name, len(prog), 10, len(prog)) + tap_block(0xFF, prog)
    tap += header(3, name, len(code), 32768, 32768) + tap_block(0xFF, code)
    check_tap(tap)
    (out / f'PV{n}.TAP').write_bytes(tap)
    print(f'PV{n}.TAP: {len(tap)} bytes (code {len(code)}), "{name}"')


if __name__ == '__main__':
    ns = [int(a) for a in sys.argv[1:]] or sorted(int(m.group(1)) for p in HERE.glob('pv*.asm')
                                                  if (m := re.fullmatch(r'pv(\d+)\.asm', p.name)))
    for n in ns:
        build(n)
