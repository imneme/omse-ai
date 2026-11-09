"""Check P-7 on omse-ai 48K: for each pass, the T-state (into the frame) at sync0 (first contended read),
synced (after the four reads) and doin (the IN). All passes should agree on synced and the IN should step 1 T.
  python3 check_p7.py build/P7.TAP build/p7.sym
Hart's-tongue Fern, Fri 06 Nov 2026.
"""
import sys, re
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from speccy import Speccy
sym = {m.group(1).lower(): int(m.group(2), 16) for m in re.finditer(r'(\w+)\s+EQU\s+0?([0-9A-F]+)H', open(sys.argv[2]).read())}
zx = Speccy(model=48)
zx.insert_tape(sys.argv[1]); zx.type('LOAD ""\n')
L = zx.lib
for it in range(12):
    for name in ('sync0', 'synced', 'doin'):
        a = sym[name]
        if not L.zx_run_until_pc(zx.z, a, a, 2000000):
            print('missed', name); sys.exit()
        if name == 'sync0': s0 = L.zx_frame_pos(zx.z)
        elif name == 'synced': s1 = L.zx_frame_pos(zx.z)
        else: s2 = L.zx_frame_pos(zx.z)
        L.zx_run_tstates(zx.z, 1)
    print(f'iter {it:2d}: first read at frame T {s0} (T after INT {s0-24}), synced at {s1}, IN at {s2} (frame len {L.zx_frame_len(zx.z)})')
