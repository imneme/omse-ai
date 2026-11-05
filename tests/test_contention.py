"""Contention: the ULA holding the CPU, held to the documented tables.

Each test runs a long straight line of one kind of instruction and measures,
to the T-state, how long it takes from its first fetch to the fetch after it.
A reference written from the documented contention tables (docs/contention.md:
"pc:4, hl:3" and so on, the delay pattern 6,5,4,3,2,1,0,0, the I/O cases)
works out the same time from the same starting T-state, through every phase of
the pattern, inside and outside the screen's contended window. They must agree
exactly. Then the same with contention off, which must take no longer than
the instructions' own T-states.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import speccy                                           # noqa: E402
from speccy import Speccy, ROMError                     # noqa: E402

OUT = ROOT / 'tests' / 'out'
OUT.mkdir(parents=True, exist_ok=True)
INT_AT = 24
TIMING = {48: (14335, 224, 312), 128: (14361, 228, 311)}    # contention start, T a line, lines


def have_128():
    try:
        speccy.rom_bytes('128-0'), speccy.rom_bytes('128-1')
        return True
    except ROMError:
        return False


class Ref:
    """The documented model: a check at T-state t waits PATTERN[...] if the
    address is contended and t is in the window."""

    def __init__(self, model, bank_c000=0):
        self.start, self.tline, self.lines = TIMING[model]
        self.model, self.bank = model, bank_c000

    def contended(self, a):
        return 0x4000 <= a < 0x8000 or (self.model == 128 and a >= 0xC000 and self.bank & 1)

    def delay(self, t):
        rel = t % (self.tline * self.lines) - self.start
        if rel < 0 or rel // self.tline >= 192 or rel % self.tline >= 128:
            return 0
        return [6, 5, 4, 3, 2, 1, 0, 0][rel % self.tline % 8]

    def run(self, t, events):
        """events: (address or None, T-states): a check at the address, then
        the T-states; ('io', port): an I/O cycle by the four-case rule."""
        for e in events:
            if e[0] == 'io':
                port = e[1]
                hc, ula = self.contended(port), not (port & 1)
                steps = ([(True, 1), (True, 3)] if hc and ula else [(True, 1)] * 4 if hc
                         else [(False, 1), (True, 3)] if ula else [(False, 4)])
                for check, n in steps:
                    if check:
                        t += self.delay(t)
                    t += n
            else:
                a, n = e
                if a is not None and self.contended(a):
                    t += self.delay(t)
                t += n
        return t


def measure(zx, start, end):
    """T-states from the first fetch at `start` to the fetch at `end` (both in
    uncontended memory), and the T-state (since INT went up) of the first."""
    flen = zx.frame_len
    assert zx.run_until(start, frames=100) == start
    t0 = zx.lib.zx_tstates(zx.z) - 1
    doc0 = (zx.lib.zx_frame_pos(zx.z) - 1 - INT_AT) % flen
    assert zx.run_until(end, frames=1000) == end
    return zx.lib.zx_tstates(zx.z) - 1 - t0, doc0


def program(setup, body, reps):
    """At 8000h: DI, setup, then (at S) body * reps, then (at E) JR $."""
    code = bytes([0xF3]) + bytes(setup)
    s = 0x8000 + len(code)
    code += bytes(body) * reps
    e = 0x8000 + len(code)
    return code + bytes([0x18, 0xFE]), s, e


def run48(setup, body, reps, contention=True):
    code, s, e = program(setup, body, reps)
    zx = Speccy()
    zx.contention(contention)
    zx.stalled0 = zx.stalled                               # the boot had contention on
    zx.write(0x8000, code)
    zx.type('RANDOMIZE USR 32768')
    zx.press('ENTER')
    return zx, measure(zx, s, e), s


class Test48(unittest.TestCase):
    REPS = 3000                                             # several lines' worth, every phase

    def check(self, setup, body, per, name):
        zx, (got, doc0), s = run48(setup, body, self.REPS)
        zx.release('ENTER')
        want = Ref(48).run(doc0, [ev for i in range(self.REPS) for ev in per(s + i * len(body))]) - doc0
        self.assertEqual(got, want, f'{name}: measured {got}, the documented model says {want}')
        plain = sum(n for ev in per(s) for n in ([ev[1]] if ev[0] != 'io' else [4])) * self.REPS
        self.assertGreater(got, plain, f'{name}: no contention at all')
        return got

    def test_reads_hl3(self):                               # LD A,(HL): pc:4, hl:3
        self.check([0x21, 0x00, 0x60], [0x7E], lambda pc: [(pc, 4), (0x6000, 3)], 'LD A,(HL)')

    def test_a_whole_frame_of_reads(self):                 # past the last screen line and round again
        self.REPS, keep = 11000, self.REPS
        try:
            self.check([0x21, 0x00, 0x60], [0x7E], lambda pc: [(pc, 4), (0x6000, 3)], 'LD A,(HL) x 11000')
        finally:
            self.REPS = keep

    def test_every_phase(self):                             # LD A,(HL); NOP: 11 T, which doesn't divide a
        self.check([0x21, 0x00, 0x60], [0x7E, 0x00],        # 224-T line, so every entry phase comes round
                   lambda pc: [(pc, 4), (0x6000, 3), (pc + 1, 4)], 'LD A,(HL); NOP')

    def test_from_many_starting_points(self):              # the same, started 4 T later each time:
        for k in range(32):                                 # some faults show only from a few phases
            with self.subTest(nops=k):
                zx, (got, doc0), st = run48([0x00] * k + [0x21, 0x00, 0x60], [0x7E, 0x00], 600)
                zx.release('ENTER')
                ev = [e for i in range(600) for e in [(st + 2 * i, 4), (0x6000, 3), (st + 2 * i + 1, 4)]]
                self.assertEqual(got, Ref(48).run(doc0, ev) - doc0)

    def test_writes_hl3(self):                              # LD (HL),A: pc:4, hl:3
        self.check([0x21, 0x00, 0x60], [0x77], lambda pc: [(pc, 4), (0x6000, 3)], 'LD (HL),A')

    def test_internal_cycles_ir(self):                      # INC HL with I = 40h: pc:4, ir:1 x2
        ir = 0x4000
        self.check([0x3E, 0x40, 0xED, 0x47], [0x23], lambda pc: [(pc, 4), (ir, 1), (ir, 1)], 'INC HL')

    def test_io_four_cases(self):                           # OUT (n),A: pc:4, pc+1:3, then the I/O cycle
        for a, n in ((0x40, 0xFE), (0x40, 0xFF), (0x80, 0xFE), (0x80, 0xFF)):
            with self.subTest(port=f'{a:02X}{n:02X}'):
                body = [0xD3, n]
                port = a << 8 | n
                zx, (got, doc0), s = run48([0x3E, a], body, 1000)
                zx.release('ENTER')
                ev = [e for i in range(1000) for e in [(s + 2 * i, 4), (s + 2 * i + 1, 3), ('io', port)]]
                want = Ref(48).run(doc0, ev) - doc0
                self.assertEqual(got, want, f'port {port:04X}')

    def test_fetches_in_contended_memory(self):             # NOPs at 6000h: pc:4 each, then JP 8xxx
        reps = 3000
        zx = Speccy()
        tail = 0x8100
        zx.write(0x6000, bytes(reps) + bytes([0xC3, tail & 0xFF, tail >> 8]))
        zx.write(0x8000, bytes([0xF3, 0xC3, 0x00, 0x60]))
        zx.write(tail, bytes([0x18, 0xFE]))
        zx.type('RANDOMIZE USR 32768')
        zx.press('ENTER')
        assert zx.run_until(0x8001, frames=100) == 0x8001     # JP 6000h: pc:4, pc+1:3, pc+2:3
        t0 = zx.lib.zx_tstates(zx.z) - 1
        doc0 = (zx.lib.zx_frame_pos(zx.z) - 1 - INT_AT) % zx.frame_len
        assert zx.run_until(tail, frames=1000) == tail
        zx.release('ENTER')
        got = zx.lib.zx_tstates(zx.z) - 1 - t0
        ev = [(0x8001, 4), (0x8002, 3), (0x8003, 3)] + [(0x6000 + i, 4) for i in range(reps)]
        ev += [(0x6000 + reps, 4), (0x6001 + reps, 3), (0x6002 + reps, 3)]
        self.assertEqual(got, Ref(48).run(doc0, ev) - doc0)

    def test_off_means_no_contention(self):
        zx, (got, doc0), s = run48([0x21, 0x00, 0x60], [0x7E], 3000, contention=False)
        zx.release('ENTER')
        self.assertEqual(got, 3000 * 7)
        self.assertEqual(zx.stalled, zx.stalled0)


@unittest.skipUnless(have_128(), 'needs the 128K ROMs (128-0.rom, 128-1.rom)')
class Test128(unittest.TestCase):
    """On the 128: 228-T lines, contention from 14361, and the odd banks at C000."""

    def run128(self, setup, body, reps):
        code, s, e = program(setup, body, reps)
        zx = Speccy(model=128)
        snap = OUT / 'contention128.sna'
        zx.save_sna(snap)
        d = bytearray(snap.read_bytes())
        d[27 + 0x4000:27 + 0x4000 + len(code)] = code                 # bank 2, at 8000h
        d[49179:49181] = (0x8000).to_bytes(2, 'little')               # PC
        snap.write_bytes(bytes(d))
        zx.load_sna(snap)
        return zx, measure(zx, s, e), s

    def paged(self, bank):                                          # LD BC,7FFDh; LD A,10h+bank; OUT (C),A
        return [0x01, 0xFD, 0x7F, 0x3E, 0x10 | bank, 0xED, 0x79]

    def test_odd_banks_at_c000_are_contended(self):
        for bank in (0, 1, 2, 3, 7):
            with self.subTest(bank=bank):
                zx, (got, doc0), s = self.run128(self.paged(bank) + [0x21, 0x00, 0xC0], [0x7E], 3000)
                want = Ref(128, bank).run(doc0, [e for i in range(3000) for e in [(s + i, 4), (0xC000, 3)]]) - doc0
                self.assertEqual(got, want)
                self.assertEqual(got > 3000 * 7, bool(bank & 1))

    def test_bank_5_at_4000_is_contended(self):
        zx, (got, doc0), s = self.run128(self.paged(0) + [0x21, 0x00, 0x60], [0x7E], 3000)
        want = Ref(128, 0).run(doc0, [e for i in range(3000) for e in [(s + i, 4), (0x6000, 3)]]) - doc0
        self.assertEqual(got, want)


if __name__ == '__main__':
    unittest.main()
