"""z80_mcycle_end: the last T-state of every machine cycle, as the Next's CPU divides an instruction.

The ZX Spectrum Next's DMA takes the bus only on the last T-state of a machine cycle (the T80N grants BUSAK there,
t80n.vhd 1738-1748), and floooh's z80.h shows a machine cycle's start on its pins only when it reads, writes or
does I/O: an internal cycle (JR's 5 T, ADD HL's 4 + 3, DJNZ, the (IX+d) cycles, the block instructions' repeats)
can't be seen. z80_mcycle_end(cpu) says it: true after the tick that ended a machine cycle.

These tests hold it, tick by tick, to tests/mcref.py, the T80N's machine cycles transcribed from t80n_mcode.vhd:
every unprefixed, CB, ED (the Z80N's included), DD/FD and DD/FD CB opcode, each condition both ways, the repeats
running and ending, the three interrupt modes, the NMI and HALT; with waits too (a held T2 is never an end); and
with the z80n flag off (the Zilog instructions divide the same way).
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_z80n import Bare, fill_regs                   # noqa: E402
import mcref                                            # noqa: E402


def want_ends(cycles):
    """the ticks (0, 1, ...) that end a machine cycle, from the cycles' lengths"""
    ends, t = set(), 0
    for n in cycles:
        t += n
        ends.add(t - 1)
    return ends


class McCase(unittest.TestCase):
    z80n = True

    @classmethod
    def setUpClass(cls):
        cls.cpu = Bare(z80n=cls.z80n)

    def check(self, code, regs, cpu=None, label=None, extra=None, int_on=False):
        """run the instruction at 8000h; its ticks must end machine cycles exactly where the T80N's do"""
        cpu = cpu or self.cpu
        for i, v in enumerate(code):
            cpu.mem[(0x8000 + i) & 0xFFFF] = v
        regs = {**regs, 'pc': 0x8000}
        cpu.set(regs)
        if int_on:
            cpu.interrupt(True)                             # (after set: its prefetch clears the pins)
        start = cpu.regs()
        mem = {start['hl']: cpu.mem[start['hl']]}
        cycles = mcref.mcycles(code, start, z80n=self.z80n and cpu.h.bare_z80n(cpu.b), mem=mem) + (extra or [])
        ticks = cpu.step()
        got = cpu.ends()
        label = label or ' '.join(f'{b:02X}' for b in code)
        self.assertEqual(len(ticks), sum(cycles), f'{label}: {len(ticks)} T-states, the T80N takes {sum(cycles)} '
                         f'({cycles})')
        want = want_ends(cycles)
        got_at = [i for i, e in enumerate(got) if e]
        self.assertEqual(got_at, sorted(want), f'{label}: machine cycles end at ticks {got_at}, the T80N\'s at '
                         f'{sorted(want)} ({cycles})')
        return got


def flag_states(rng):
    """two states that put every condition both ways (flags all clear, all set), and B = 1 and 5 for DJNZ"""
    for f, b in ((0x00, 0x01), (0xFF, 0x05), (0x00, 0x05), (0xFF, 0x01)):
        r = fill_regs(rng)
        r['af'] = (r['af'] & 0xFF00) | f
        r['bc'] = (b << 8) | (r['bc'] & 0xFF)
        yield r


class TestUnprefixed(McCase):
    def test_every_opcode(self):
        rng = random.Random(30)
        for op in range(256):
            if op in (0xCB, 0xDD, 0xED, 0xFD, 0x76):
                continue
            for k, regs in enumerate(flag_states(rng)):
                with self.subTest(op=f'{op:02X}', state=k):
                    self.check([op, rng.randrange(256), rng.randrange(256)], regs)

    def test_halt(self):
        """HALT, and the M1s it repeats: each a machine cycle of 4"""
        regs = fill_regs(random.Random(31))
        self.check([0x76], regs)
        for _ in range(3):
            self.cpu.step()
            self.assertEqual([i for i, e in enumerate(self.cpu.ends()) if e], [3])


class TestCB(McCase):
    def test_every_opcode(self):
        rng = random.Random(32)
        for op in range(256):
            with self.subTest(op=f'CB {op:02X}'):
                self.check([0xCB, op], fill_regs(rng))


class TestED(McCase):
    def test_every_opcode(self):
        rng = random.Random(33)
        for op in range(256):
            for bc in (0x0103, 0x0301, 0x0001):
                with self.subTest(op=f'ED {op:02X}', bc=f'{bc:04X}'):
                    self.check([0xED, op, rng.randrange(256), rng.randrange(256)], fill_regs(rng, bc=bc))

    def test_cpir_found_and_not(self):
        rng = random.Random(34)
        for op in (0xA1, 0xA9, 0xB1, 0xB9):
            for same in (True, False):
                with self.subTest(op=f'ED {op:02X}', found=same):
                    regs = fill_regs(rng, bc=5, hl=0x9000)
                    self.cpu.mem[0x9000] = (regs['af'] >> 8) if same else ((regs['af'] >> 8) ^ 1)
                    self.check([0xED, op], regs)


class TestEDWithoutTheFlag(TestED):
    z80n = False


class TestDDFD(McCase):
    def test_every_opcode(self):
        rng = random.Random(35)
        for pre in (0xDD, 0xFD):
            for op in range(256):
                if op in (0x76, 0xCB):
                    continue
                for k, regs in enumerate(flag_states(rng)):
                    if k > 1 and op not in (0x10, 0x20, 0x28, 0x30, 0x38) and op & 0xC7 not in (0xC0, 0xC4):
                        continue
                    with self.subTest(op=f'{pre:02X} {op:02X}', state=k):
                        code = [pre, op] + [rng.randrange(256) for _ in range(3)]
                        if op in (0xDD, 0xFD, 0xED) and code[2] == 0x76:
                            code[2] = 0x00
                        self.check(code, regs)

    def test_ddcb(self):
        rng = random.Random(36)
        for pre in (0xDD, 0xFD):
            for op in range(256):
                with self.subTest(op=f'{pre:02X} CB d {op:02X}'):
                    self.check([pre, 0xCB, rng.randrange(256), op], fill_regs(rng))


class TestInterrupts(McCase):
    def test_im0_im1_im2(self):
        """after a NOP, with INT held and interrupts on: the acknowledge's cycles follow the NOP's"""
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                regs = fill_regs(random.Random(37), im=mode, iff1=1, iff2=1)
                try:
                    self.check([0x00], regs, extra=mcref.interrupt(mode), label=f'IM {mode}', int_on=True)
                finally:
                    self.cpu.interrupt(False)

    def test_nmi(self):
        regs = fill_regs(random.Random(38), iff1=1, iff2=1)
        self.cpu.mem[0x8000] = 0x00
        self.cpu.set({**regs, 'pc': 0x8000})
        self.cpu.nmi()
        self.cpu.step()
        self.cpu.step()
        self.assertEqual([i for i, e in enumerate(self.cpu.ends()) if e], sorted(want_ends(mcref.NMI)))


class TestWaits(unittest.TestCase):
    """With waits, every held T2 is extra and none is an end: take them out and the ends are as without"""

    def test_waits(self):
        plain = Bare(z80n=True)
        rng = random.Random(39)
        codes = [[op, 0x12, 0x34] for op in (0x00, 0x18, 0x10, 0x09, 0xC5, 0xCD, 0xE3, 0x34, 0x36)]
        codes += [[0xED, op, 0x12, 0x34] for op in (0xB0, 0xB1, 0xB2, 0xB3, 0x91, 0x8A, 0x98, 0xB4, 0x57, 0x67)]
        codes += [[0xDD, op, 0x05, 0x34] for op in (0x34, 0x36, 0x7E, 0xE3, 0x09)] + [[0xDD, 0xCB, 0x05, 0x46]]
        for wm, wr in ((0, 1), (1, 0), (2, 0)):
            waits = Bare(z80n=True, wait_mem=wm, wait_rd=wr)
            for code in codes:
                with self.subTest(code=' '.join(f'{b:02X}' for b in code), wait_mem=wm, wait_rd=wr):
                    regs = fill_regs(rng, bc=0x0203)
                    res = []
                    for cpu in (plain, waits):
                        for i, v in enumerate(code):
                            cpu.mem[0x8000 + i] = v
                        cpu.set({**regs, 'pc': 0x8000})
                        cpu.step()
                        res.append((cpu.steps(), cpu.ends()))
                    (s0, e0), (s1, e1) = res
                    kept = [i for i in range(len(s1)) if i == 0 or s1[i] != s1[i - 1]]   # a held tick repeats its step
                    self.assertEqual([s1[i] for i in kept], s0)
                    self.assertEqual([e1[i] for i in kept], e0)
                    self.assertFalse(any(e1[i] for i in range(len(s1)) if i not in kept), 'an end on a held T2')


class TestWithoutTheFlag(McCase):
    """The Zilog instructions divide into machine cycles the same with the z80n flag off."""
    z80n = False

    def test_unprefixed_and_cb(self):
        rng = random.Random(40)
        for op in range(256):
            if op in (0xCB, 0xDD, 0xED, 0xFD, 0x76):
                continue
            with self.subTest(op=f'{op:02X}'):
                self.check([op, rng.randrange(256), rng.randrange(256)], next(flag_states(rng)))
        for op in range(256):
            with self.subTest(op=f'CB {op:02X}'):
                self.check([0xCB, op], fill_regs(rng))


if __name__ == '__main__':
    unittest.main()
