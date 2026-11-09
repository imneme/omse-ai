"""Build the Spectrum Next probe tapes: P1.TAP, P2.TAP, ... from p1.asm, p2.asm, ... (each includes probe.inc).

  build_probes.py [N ...]          (default: every pN.asm here)

Each tape is a BASIC loader (CLEAR 32767 : LOAD "" CODE : RANDOMIZE USR 32768, autostart line 10) and the
code at 32768. The TAP helpers, check_tap included, are Tally Fern's design, imported from Strobe Fern's
z80ntime/build_probe.py so there's one copy. On the Next: `.tapein p1.tap`, then LOAD "".
Hart's-tongue Fern, Fri 06 Nov 2026.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'z80ntime'))
from build_probe import tap_block, header, check_tap, num, PASMO  # noqa: E402

NAMES = {'2b': 'p2b-nr7f', 1: 'p1-ident', 2: 'p2-nr7f', 7: 'p7-intbeam', 3: 'p3-ctc', 4: 'p4-mmu', 6: 'p6-waits', 8: 'p8-layer2', 13: 'p13-port1f', 81: 'p81-l2diag', 82: 'p82-l2bank', 20: 'p20-dma', 'ss': 'pss-2ndsrc', 'bd': 'pbd-busdrows', 'nm': 'pnm-nmiflags', 'cf': 'pcf-config', 'ua': 'pua-espuart'}


def build(n):
    src = HERE / f'p{n}.asm'
    out = HERE / 'build'
    out.mkdir(exist_ok=True)
    binp, sym = out / f'p{n}.bin', out / f'p{n}.sym'
    r = subprocess.run([str(PASMO), '--bin', src.name, str(binp), str(sym)], cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'p{n}.asm:\n{r.stdout}{r.stderr}')
    code = binp.read_bytes()
    assert len(code) <= 0x1000, f'p{n}: code is {len(code)} bytes, past 0x8FFF (the buffer starts at 0x9000)'
    line = bytes([0xFD]) + num(32767) + b':' + bytes([0xEF]) + b'""' + bytes([0xAF]) + b':' + \
        bytes([0xF9, 0xC0]) + num(32768) + b'\r'
    prog = (10).to_bytes(2, 'big') + len(line).to_bytes(2, 'little') + line
    name = NAMES.get(n, f'p{n}')
    tap = header(0, name, len(prog), 10, len(prog)) + tap_block(0xFF, prog)
    tap += header(3, name, len(code), 32768, 32768) + tap_block(0xFF, code)
    check_tap(tap)
    (out / f'P{n}.TAP').write_bytes(tap)
    print(f'P{n}.TAP: {len(tap)} bytes (code {len(code)}), "{name}"')


def main():
    ns = [a if not a.isdigit() else int(a) for a in sys.argv[1:]] or sorted(int(m.group(1)) for p in HERE.glob('p*.asm')
                                                  if (m := re.fullmatch(r'p(\d+)\.asm', p.name))) + ['2b', 'ss', 'bd', 'nm', 'cf', 'ua']
    for n in ns:
        build(n)


if __name__ == '__main__':
    main()
