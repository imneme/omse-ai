"""Generate z80.h's table for z80_mcycle_end: which decoder steps run the last T-state of a machine cycle.

  gen_mcend.py            prints the C table (and checks; non-zero exit if any step disagrees with itself)

Runs every instruction on tests/bare_z80.cpp's bare Z80 (every opcode, prefix, condition, repeat, interrupt mode,
the NMI and HALT), lines the ticks up with tests/mcref.py (the T80N's machine cycles, from t80n_mcode.vhd), and
records, for each step, whether the tick that ran it ended a machine cycle. Every step must agree with itself
across all its paths, except the shared M1 T4 steps, whose answer depends on how long that M1 is (z80.h asks
the opcode); this checks the rule z80.h uses for them too. tests/test_mcycle.py then holds the result to the
reference, tick by tick.
"""
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
from test_z80n import Bare, fill_regs          # noqa: E402
import mcref                                   # noqa: E402

M1_T4, ED_M1_T4, CB_M1_T4, DDFD_M1_T4 = 1708, 1705, 1702, 1687


def m1_is_4(op):                                # z80.h's rule for Z80_M1_T4 and Z80_DDFD_M1_T4
    return not ((op & 0xC7) in (0xC0, 0xC7, 0x03) or (op & 0xCF) == 0xC5 or op in (0x10, 0xF9))


def ed_m1_is_4(op, z80n):                       # ... and for Z80_ED_M1_T4
    return not ((op & 0xE7) == 0x47 or (op & 0xE6) == 0xA2 or (z80n and op == 0x90))


def variants(rng):
    """(code, regs, extra cycles, int_on) for everything"""
    states = []
    for f, b in ((0x00, 0x01), (0xFF, 0x05)):
        r = fill_regs(rng)
        r['af'] = (r['af'] & 0xFF00) | f
        r['bc'] = (b << 8) | (r['bc'] & 0xFF)
        states.append(r)
    for op in range(256):
        if op not in (0xCB, 0xDD, 0xED, 0xFD, 0x76):
            for r in states:
                yield [op, rng.randrange(256), rng.randrange(256)], r, [], False
        yield [0xCB, op], fill_regs(rng), [], False
        for bc in (0x0103, 0x0301, 0x0001):
            yield [0xED, op, rng.randrange(256), rng.randrange(256)], fill_regs(rng, bc=bc), [], False
        for pre in (0xDD, 0xFD):
            if op not in (0x76, 0xCB):
                code = [pre, op] + [rng.randrange(256) for _ in range(3)]
                if op in (0xDD, 0xFD, 0xED) and code[2] == 0x76:
                    code[2] = 0
                for r in states:
                    yield code, r, [], False
            yield [pre, 0xCB, rng.randrange(256), op], fill_regs(rng), [], False
    yield [0x76], fill_regs(rng), [], False
    for mode in (0, 1, 2):
        yield [0x00], fill_regs(rng, im=mode, iff1=1, iff2=1), mcref.interrupt(mode), True
    yield [0x00], fill_regs(rng, iff1=1, iff2=1), None, 'nmi'          # the NMI response after a NOP


def main():
    marks, bad, seen, obs = {}, [], set(), {}
    for z80n in (True, False):
        cpu = Bare(z80n=z80n)
        rng = random.Random(50)
        for code, regs, extra, int_on in variants(rng):
            for i, v in enumerate(code):
                cpu.mem[0x8000 + i] = v
            cpu.set({**regs, 'pc': 0x8000})
            if int_on == 'nmi':
                cpu.nmi()
                cpu.step()                                  # the NOP; then the NMI is the next "instruction"
                cycles = mcref.NMI
            else:
                if int_on:
                    cpu.interrupt(True)
                start = cpu.regs()
                cycles = mcref.mcycles(code, start, z80n=z80n, mem={start['hl']: cpu.mem[start['hl']]}) + extra
            cpu.step()
            cpu.interrupt(False)
            steps = cpu.steps()
            ends, t = set(), 0
            for n in cycles:
                t += n
                ends.add(t - 1)
            if len(steps) != t:
                bad.append(f'{code}: {len(steps)} ticks, reference {t}')
                continue
            for i, s in enumerate(steps):
                e = i in ends
                seen.add(s)
                if s in (M1_T4, DDFD_M1_T4):
                    op = code[1] if s == DDFD_M1_T4 else code[i // 4] if code[0] not in (0xDD, 0xFD) else code[1]
                    if s == M1_T4 and code[0] in (0xDD, 0xFD, 0xCB, 0xED) and i < 4:
                        op = code[0]
                    if s == M1_T4 and code[0] == 0x76:
                        op = 0x76
                    if e != m1_is_4(op if s == DDFD_M1_T4 or i < 4 else code[0]):
                        bad.append(f'{code}: step {s} at tick {i}: end {e}, rule says {not e}')
                    continue
                if s == ED_M1_T4:
                    if e != ed_m1_is_4(code[code.index(0xED) + 1], z80n):
                        bad.append(f'{code}: ED M1 T4 at tick {i}: end {e}, rule says {not e}')
                    continue
                nxt = steps[i + 1] if i + 1 < len(steps) else None     # None: the next instruction's T1 follows
                branched = nxt != s + 1
                obs.setdefault(s, []).append((e, branched, code, i))
    branch = []                                         # steps whose answer is the way they went (CALL cc's M3 T3)
    for s, os in obs.items():
        es = {e for e, _, _, _ in os}
        if len(es) == 1:
            marks[s] = (es.pop(), os[0][2])
        elif all(e == br for e, br, _, _ in os):
            branch.append(s)
            marks[s] = (False, os[0][2])
        else:
            e0 = os[0]
            other = next(o for o in os if o[0] != e0[0])
            bad.append(f'step {s}: {e0[0]} for {e0[2]} (tick {e0[3]}) but {other[0]} for {other[2]} (tick {other[3]})')
    for b in bad[:40]:
        print('DISAGREES:', b, file=sys.stderr)
    top = max(max(seen), 1830)
    bits = [0] * ((top >> 3) + 1)
    for s, (e, _) in marks.items():
        if e:
            bits[s >> 3] |= 1 << (s & 7)
    print(f'// generated by tools/gen_mcend.py from tests/mcref.py: bit s is set if decoder step s runs the last')
    print(f'// T-state of a machine cycle ({sum(e for e, _ in marks.values())} of the {len(seen)} steps that run)')
    print(f'static const uint8_t _z80_mcend_bits[{len(bits)}] = {{')
    for k in range(0, len(bits), 16):
        print('    ' + ','.join(f'0x{v:02X}' for v in bits[k:k + 16]) + ',')
    print('};')
    print(f'// steps that end a machine cycle only when they branch (the next step isn\'t the one after): {len(branch)}')
    print('static inline bool _z80_mcend_branch(uint16_t s) {')
    print('    switch (s) {')
    print('        ' + ' '.join(f'case {s}:' for s in sorted(branch)) + ' return true;')
    print('        default: return false;')
    print('    }')
    print('}')
    unseen = [s for s in range(top + 1) if s not in seen]
    print(f'// steps never reached by the generator: {len(unseen)}', file=sys.stderr)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
