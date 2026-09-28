#!/usr/bin/env python3
"""Disassemble the 48K ROM (or any file) with tzxtools' z80dis.

    ./zxdis.py 15D4 15F7                 # the 48K ROM, from 0x15D4 up to 0x15F7
    ./zxdis.py 8000 8040 file.bin 8000   # a raw file loaded at 0x8000

The ROM comes from the same place the emulator finds it ($OMSE_AI_ROMS, or roms/).
Needs tzxtools: pip install tzxtools.
"""
import sys
from pathlib import Path

try:
    from tzxlib.z80dis import disassemble
except ImportError:
    disassemble = None


def dis(data, start, end, org=0):
    if disassemble is None:
        raise RuntimeError('zxdis needs tzxtools (its tzxlib.z80dis): pip install tzxtools')
    pc = start
    out = []
    while pc < end:
        text, length = disassemble(data, pc - org, org)
        b = data[pc - org: pc - org + length]
        out.append(f'{pc:04X}  {b.hex(" "):12}  {text}')
        pc += length
    return '\n'.join(out)


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        sys.exit(1)
    start, end = int(a[0], 16), int(a[1], 16)
    org = int(a[3], 16) if len(a) > 3 else 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from speccy import rom_bytes, ROMError
    try:
        data = Path(a[2]).read_bytes() if len(a) > 2 else rom_bytes('48')
        print(dis(data, start, end, org))
    except (ROMError, RuntimeError) as e:
        print(f'zxdis: {e}', file=sys.stderr)
        sys.exit(2)
