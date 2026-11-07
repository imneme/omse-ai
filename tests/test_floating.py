"""The floating bus: what an IN from a port nobody answers reads.

A reference written from the documented rule (docs/contention.md: Ramsoft's
pattern, timed as Fuse times it) works out each read from the T-state it
samples at, counted as Fuse counts an IN: its fetch (4) and operand read (3),
then the I/O cycle's first T-state and two more, so 10 T after the IN begins
for a port whose high byte isn't contended. Every read must match.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from speccy import Speccy                               # noqa: E402
from test_contention import measure, have_128, OUT, Ref    # noqa: E402

TIMING = {48: (14335, 224), 128: (14361, 228)}          # contention start, T a line


def ref_float(scr, t, model):
    """The byte on the bus t T-states after INT: in each 8 T of a screen line's
    first 128, bitmap, attribute, bitmap + 1, attribute + 1, then idle."""
    start, tline = TIMING[model]
    u = t - (start + 1)                                 # the first byte at 14338 / 14364
    if u < 0:
        return 0xFF
    line, col = divmod(u, tline)
    if line >= 192 or col >= 128:
        return 0xFF
    x, k = (col >> 3) * 2, col & 7
    if k in (2, 4):
        x += k == 4
        return scr[((line & 0xC0) << 5) | ((line & 7) << 8) | ((line & 0x38) << 2) | x]
    if k in (3, 5):
        x += k == 5
        return scr[0x1800 + (line >> 3) * 32 + x]
    return 0xFF


def screen_bytes():
    """A screen whose every byte differs from its neighbours and is never FFh."""
    return bytes(((o * 7) + 3) % 255 for o in range(0x1800)) + bytes(((o * 13) + 1) % 255 for o in range(0x300))


N = 580                                                 # reads: XOR A; IN A,(FFh); LD (HL),A; INC HL; LD B,0
BODY = bytes([0xAF, 0xDB, 0xFF, 0x77, 0x23, 0x06, 0x00])   # 35 T, odd, so every phase of 8 comes round


def program():
    """EI; HALT (to INT); DI; a delay to just before the screen; then N reads into 9000h."""
    head = bytes([0xFB, 0x76, 0xF3, 0x01, 0x12, 0x02,          # EI; HALT; DI; LD BC,530
                  0x0B, 0x78, 0xB1, 0x20, 0xFB,                 # DEC BC; LD A,B; OR C; JR NZ
                  0x21, 0x00, 0x90])                            # LD HL,9000h
    s = 0x8000 + len(head)
    code = head + BODY * N
    return code + bytes([0x18, 0xFE]), s, 0x8000 + len(code)


class Floating48(unittest.TestCase):
    def run_reads(self, floating=True):
        zx = Speccy()
        zx.floating_bus(floating)
        scr = screen_bytes()
        zx.write(0x4000, scr)
        code, s, e = program()
        zx.write(0x8000, code)
        zx.type('RANDOMIZE USR 32768')
        zx.press('ENTER')
        _, doc0 = measure(zx, s, e)
        zx.release('ENTER')
        return scr, doc0, zx.read(0x9000, N)

    def test_reads_follow_the_ulas_fetches(self):
        scr, doc0, got = self.run_reads()
        want = bytes(ref_float(scr, doc0 + 35 * i + 4 + 10, 48) for i in range(N))
        bad = [(i, got[i], want[i]) for i in range(N) if got[i] != want[i]]
        self.assertEqual(bad[:5], [], f'{len(bad)} of {N} reads differ (index, got, want)')
        self.assertGreater(sum(b != 0xFF for b in got), N // 5, 'too few reads saw the screen to mean anything')

    def test_a_contended_high_byte(self):
        # LD A,40h; IN A,(FFh) reads port 40FF, whose high byte is contended: C:1 on all
        # four T-states of the I/O cycle, and the sample is taken after the fourth hold.
        # A hold always ends at position 6 of the 8; with INC DE in the body, the INs arrive
        # so that reads alternate between a held fourth T-state (sampling the attribute beat)
        # and an unheld one (sampling idle): LD (HL),A; INC HL; INC DE; LD B,0; LD C,0.
        body = bytes([0x3E, 0x40, 0xDB, 0xFF, 0x77, 0x23, 0x13, 0x06, 0x00, 0x0E, 0x00])
        n = 360
        zx = Speccy()
        scr = screen_bytes()
        zx.write(0x4000, scr)
        head, s, _ = program()
        head = head[:s - 0x8000]
        code = head + body * n
        e = 0x8000 + len(code)
        zx.write(0x8000, code + bytes([0x18, 0xFE]))
        zx.type('RANDOMIZE USR 32768')
        zx.press('ENTER')
        _, doc0 = measure(zx, s, e)
        zx.release('ENTER')
        got = zx.read(0x9000, n)
        ref = Ref(48)
        t, want = doc0, []
        for _ in range(n):
            t += 7 + 4 + 3                                  # LD A,40h; the IN's fetch and operand
            for phase in range(4):
                t += ref.delay(t)
                if phase == 3:
                    want.append(ref_float(scr, t, 48))      # sampled after the last hold
                t += 1
            t += 7 + 6 + 6 + 7 + 7                          # LD (HL),A; INC HL; INC DE; LD B,0; LD C,0
        bad = [(i, got[i], want[i]) for i in range(n) if got[i] != want[i]]
        self.assertEqual(bad[:5], [], f'{len(bad)} of {n} reads differ (index, got, want)')
        self.assertGreater(sum(b != 0xFF for b in got), n // 5)

    def test_off_reads_ff(self):
        _, _, got = self.run_reads(floating=False)
        self.assertEqual(set(got), {0xFF})


@unittest.skipUnless(have_128(), 'needs the 128K ROMs (128-0.rom, 128-1.rom)')
class Quirk128(unittest.TestCase):
    def test_an_in_from_7ffd_writes_what_it_read(self):
        # just after INT (the top border, so the bus reads FFh), IN A,(FDh) with A = 7Fh
        # reads port 7FFD, and the 128 writes the FFh into its paging register: bank 7,
        # ROM 1, the shadow screen, and the lock
        code = bytes([0xFB, 0x76, 0xF3, 0x3E, 0x7F, 0xDB, 0xFD, 0x18, 0xFE])
        zx = Speccy(model=128)
        snap = OUT / 'floating128.sna'
        zx.save_sna(snap)
        d = bytearray(snap.read_bytes())
        d[27 + 0x4000:27 + 0x4000 + len(code)] = code                 # bank 2, at 8000h
        d[49179:49181] = (0x8000).to_bytes(2, 'little')               # PC
        snap.write_bytes(bytes(d))
        zx.load_sna(snap)
        assert zx.run_until(0x8007, frames=10) == 0x8007
        self.assertEqual(zx.lib.zx_paging(zx.z) & 0x3F, 0x3F)


if __name__ == '__main__':
    unittest.main()
