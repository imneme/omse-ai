"""The floating bus through IN A,(C) from port xxFF, swept across the beam: a second foil for Speccy-Zone's fix.

Hatch Fern, Sat 7 Nov 2026. Written from the VHDL (core 3.02.02) and the docstring of Speccy-Zone's
tests/test_next_floating.py (its citations only), never from her code or nextcore.cpp. The reading is in
floating_ref.py, line by line; in short: the ULA's register loads pixel 2G, attribute 2G, pixel 2G+1 and
attribute 2G+1 in the middle of slots 9, B, D and F (FF from slot 1, and in the border); the T80N takes the
byte on the falling CPU clock edge inside the I/O cycle's fourth T-state (T1, T1 again, T2, T3); a T-state of
an I/O cycle whose port address lies in a contended page is held at the end of odd slots 3..13 of the paper.

Instead of a few chosen moments, each case runs a loop of IN A,(C) (35 T-states a pass, so the IN starts at
all eight phases of a 16-pixel group and drifts across lines) from just above the paper for 2000 passes, and
every byte must be what the reading says, given only where the instruction began (a run_until_pc stop,
§9.1 (11): T1 is hc_ula + 1). The screen's bytes are chosen so neighbouring slots always differ and none is FF.
A is read at the stop after the next instruction: the T80 writes an IN's byte into A during the following
instruction's first T-state, so the stop at the very next fetch still sees the old A.

Cases, chosen to differ from Speccy-Zone's: 48K timing with the port's page contended (40FF) and contention on;
the same with contention off; an uncontended port page (00FF) with contention on; 128K timing (456-pixel lines,
so the phase moves line to line) with 40FF; 128K with the port in slot 6 on bank 7 (odd, contended) and on
bank 6 (even, not); the 128K shadow screen (7FFD b3: the bytes come from bank 7); and the line's last group,
where a held IN released at the end of hc 255 latches as hc becomes 256: attribute 31 on the reading that the
CPU's edge, made from the same CLK_7 edge that steps hc, sees the counter from before it (a design meeting hold
timing). If that's ever ruled the other way, test_line_end only needs its expected byte changed to FF.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import floating_ref as R                                # noqa: E402

os.environ.setdefault('OMSE_AI_ROMS', str(Path.home() / 'omse-ai' / 'roms'))
os.environ.setdefault('OMSE_AI_NEXT_ROMS', str(Path.home() / 'next-build/sources/tbblue/machines/next'))


def _machine():
    try:
        import next as nextmod                          # noqa: F401
    except ModuleNotFoundError as e:
        if e.name == 'next':
            return None, 'needs the Next machine (next.py, DESIGN.md §9), not built yet'
        raise
    return nextmod.Next, None


Next, WHY = _machine()
needs_next = unittest.skipIf(Next is None, WHY or '')

CODE = 0x8000
PAD = b'\x19'                                           # ADD HL,DE: 11 T-states, so a pass is 12 + 11 + 12 = 35


def pix(row, col):                                      # the main screen's bytes: never FF, never an attribute
    return (col * 7 + row * 3) & 0x7F


def att(arow, col):
    return 0x80 | ((col * 5 + arow * 11) & 0x7E)


def pix7(row, col):                                     # the shadow screen's: different everywhere
    return (col * 13 + row * 5 + 0x40) & 0x7F


def att7(arow, col):
    return 0x80 | ((col * 3 + arow * 7 + 0x21) & 0x7E)


def screen(p, a):
    b = bytearray(6912)
    for y in range(192):
        for c in range(32):
            b[((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | c] = p(y, c)
    for r in range(24):
        for c in range(32):
            b[6144 + r * 32 + c] = a(r, c)
    return bytes(b)


def slot_name(edge, timing):
    L = R.LINE[timing]
    hc = (edge - 1) % L
    return f'hc {hc} (slot {hc % 16:X})'


class FloatingSweep(unittest.TestCase):

    def machine(self, timing, contention):
        zx = Next(timing=timing, boot='fast')
        nr08 = zx.nr_read(0x08)
        zx.nr_write(0x08, (nr08 & ~0x44) | (0 if contention else 0x40))   # b6 off = contention; b2 off = no Timex read
        zx.write(0x4000, screen(pix, att))
        zx.load(CODE, bytes([0xED, 0x78]) + PAD + bytes([0x18, (-(2 + len(PAD) + 2)) & 0xFF]))
        return zx

    def sweep(self, zx, timing, port, contention, n=2000, p=pix, a=att, page_contended=None):
        """n passes from two lines above the paper; returns (samples, mismatches, bytes expected not FF)."""
        zx.set_regs(pc=CODE, sp=0xBFF0, bc=port)
        if page_contended is None:
            page_contended = R.contended_page(zx.slot_page(port >> 13), timing)
        L, N = R.LINE[timing], R.LINES[timing]
        while True:
            self.assertTrue(zx.run_until_pc(CODE))
            if zx.vc_ula == N - 2:
                break
        samples, bad, live = [], [], 0
        for _ in range(n):
            self.assertTrue(zx.run_until_pc(CODE))
            vc, hc = zx.vc_ula, zx.hc_ula
            start = vc * L + hc + 1
            self.assertTrue(zx.run_until_pc(CODE + 2 + len(PAD)))
            got = zx.regs()['af'] >> 8
            edge = R.io_sample_edge(start, timing, page_contended, contention)
            want = R.floating_byte(edge, timing, p, a)
            live += want != 0xFF
            samples.append((vc, hc, edge, got, want))
            if got != want:
                bad.append((vc, hc, edge, got, want))
        return samples, bad, live

    def check(self, timing, port, contention, **kw):
        zx = self.machine(timing, contention)
        if 'setup' in kw:
            kw.pop('setup')(zx)
        samples, bad, live = self.sweep(zx, timing, port, contention, **kw)
        self.assertGreater(live, 150, 'the sweep should read the screen often')
        msg = '; '.join(f'line {vc} IN at hc {hc + 1}: got {got:02X}, want {want:02X} at {slot_name(e, timing)}'
                        for vc, hc, e, got, want in bad[:6])
        self.assertEqual(len(bad), 0, f'{len(bad)} of {len(samples)} INs took another byte ({live} expected '
                                      f'off the screen): {msg}')
        return samples

    @needs_next
    def test_48k_contended_port_contention_on(self):
        self.check('48k', 0x40FF, True)

    @needs_next
    def test_48k_contention_off(self):
        """No holds: the byte at the falling edge in the I/O cycle's fourth T-state, T1 + 23 pixels."""
        self.check('48k', 0x40FF, False)

    @needs_next
    def test_48k_uncontended_port_page(self):
        """Port 00FF's page is the ROM's: nothing is held even with contention on."""
        self.check('48k', 0x00FF, True)

    @needs_next
    def test_128k_contended_port(self):
        self.check('128k', 0x40FF, True)

    @needs_next
    def test_128k_port_page_decides(self):
        """The port's high byte picks the page that decides contention: slot 6 on bank 7 (odd) holds, on bank 6
        (even) it doesn't."""
        for bank, held in ((7, True), (6, False)):
            with self.subTest(bank=bank):
                def setup(zx, bank=bank):
                    zx.nr_write(0x56, 2 * bank)
                    zx.nr_write(0x57, 2 * bank + 1)
                samples = self.check('128k', 0xC0FF, True, setup=setup)
                self.assertTrue(samples)
                zx = self.machine('128k', True)
                setup(zx)
                self.assertEqual(R.contended_page(zx.slot_page(6), '128k'), held)

    @needs_next
    def test_128k_shadow_screen(self):
        """7FFD b3 shows bank 7: the floating bus carries bank 7's bytes."""
        def setup(zx):
            zx.nr_write(0x56, 14)                       # bank 7's first 8K at C000 to write it
            zx.write(0xC000, screen(pix7, att7))
            zx.nr_write(0x56, 0)
            zx.io_out(0x7FFD, 0x08)                     # shadow screen; top 16K back to bank 0
        self.check('128k', 0x40FF, True, setup=setup, p=pix7, a=att7)

    @needs_next
    def test_line_end(self):
        """Held INs released at the end of hc 255 latch as hc becomes 256: attribute 31 of their row, not FF."""
        zx = self.machine('48k', True)
        samples, bad, live = self.sweep(zx, '48k', 0x40FF, True)
        at_end = [s for s in samples if (s[2] - 1) % R.LINE['48k'] == 255 and s[0] < 192]
        self.assertGreater(len(at_end), 10, 'the sweep should reach the last group often')
        wrong = [(vc, hc, got, want) for vc, hc, e, got, want in at_end if got != want]
        self.assertEqual(wrong, [], f'{len(wrong)} of {len(at_end)} at the line end differ (line, hc, got, want)')
        self.assertTrue(all(want == att(vc >> 3, 31) for vc, hc, e, got, want in at_end))


if __name__ == '__main__':
    unittest.main()
