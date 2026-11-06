"""The Next's copper: WAIT against the beam, MOVE, its modes and restarts
(the foil, Loam Fern).

From the survey's §2.4 and §8, copper.vhd (whole, 125 lines) and
zxnext.vhd:3883-3940, 5356-5376, core 3.02.02, through DESIGN.md §9 only.
The copper's MOVEs write NR 0x7F, the user register (it can reach 0x00-0x7F
only, its register field being 7 bits), which the tests watch from Python.

  WAIT  bit 15 = 1, h = bits 14:9, v = bits 8:0: advance once cvc = v and
        hc_ula >= 8h + 12 (copper.vhd:94)
  MOVE  bit 15 = 0, register = bits 14:8, value = bits 7:0; two cycles
        (copper.vhd:87-110)
  NR 0x62 b7:6: entering 01 or 11 restarts at 0, rewriting the same mode
  doesn't, 10 resumes, 11 also restarts at cvc = 0, hc_ula = 0 (copper.vhd:69-85)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402

L48, N48 = ref.TIMINGS[('48k', 50)][:2]
STOP, RUN, RESUME, RUN_EACH_FRAME = 0x00, 0x40, 0x80, 0xC0


def WAIT(v, h=0):
    return 0x8000 | h << 9 | v


def MOVE(reg, val):
    return reg << 8 | val


NEVER = WAIT(511, 63)                                   # no such line: the copper rests here


def load(zx, words):
    """Stop the copper and write words from address 0 through NR 0x63, MSB
    first (zxnext:5371-5375, 3918)."""
    zx.nr_write(0x62, STOP)
    zx.nr_write(0x61, 0x00)
    for w in words:
        zx.nr_write(0x63, w >> 8)
        zx.nr_write(0x63, w & 0xFF)


def to_line(zx, line, hc=0):
    """Run until the beam is at ULA row `line`, pixel `hc` (48K timing)."""
    now = zx.vc_ula * L48 + zx.hc_ula
    zx.run_ticks(((line * L48 + hc - now) % (L48 * N48)) * ref.TICKS_PER_PIXEL)


def first_change(case, zx, want, limit_lines=3):
    """Step tick by tick until NR 0x7F reads `want`; return (cvc, hc_ula)."""
    for _ in range(limit_lines * L48 * ref.TICKS_PER_PIXEL):
        if zx.nr_read(0x7F) == want:
            return zx.cvc, zx.hc_ula
        zx.run_ticks(1)
    case.fail(f'NR 0x7F never became {want:#04x}')


@needs_next
class Copper(NextCase):

    def machine(self, words, mode=RUN):
        zx = bare(timing='48k')
        zx.nr_write(0x7F, 0x00)
        load(zx, words)
        return zx

    def test_write_address_reads_back(self):
        zx = self.machine([MOVE(0x7F, 1), MOVE(0x7F, 2), NEVER])
        self.assertEqual(zx.nr_read(0x61), 6, 'three words, six bytes (zxnext:5990-5991)')
        self.assertEqual(zx.nr_read(0x62), 0x00, 'stopped, address MSB 0 (zxnext:5993-5994)')

    def test_move_lands_where_the_wait_says(self):
        for v, h in [(50, 0), (60, 10), (150, 25)]:
            zx = self.machine([WAIT(v, h), MOVE(0x7F, 0x42), NEVER])
            to_line(zx, v - 1)
            zx.nr_write(0x62, RUN)
            self.assertEqual(zx.nr_read(0x7F), 0x00, 'not before its line')
            cvc, hc = first_change(self, zx, 0x42)
            self.assertEqual(cvc, v, f'WAIT ({v}, {h}): copper.vhd:94')
            self.assertTrue(8 * h + 12 <= hc <= 8 * h + 14,
                            f'WAIT ({v}, {h}): MOVE seen at hc_ula {hc}, want 8h+12 = {8 * h + 12} '
                            f'or a pixel or two after (a MOVE is two cycles, copper.vhd:87-90)')

    def test_mode_01_runs_once(self):
        zx = self.machine([WAIT(50), MOVE(0x7F, 0x42), WAIT(100), MOVE(0x7F, 0x43), NEVER])
        to_line(zx, 40)
        zx.nr_write(0x62, RUN)
        to_line(zx, 120)
        self.assertEqual(zx.nr_read(0x7F), 0x43)
        to_line(zx, 75)                                 # the next frame, past its line 50
        self.assertEqual(zx.nr_read(0x7F), 0x43, 'mode 01 rests at the last WAIT')

    def test_mode_11_restarts_every_frame(self):
        zx = self.machine([WAIT(50), MOVE(0x7F, 0x42), WAIT(100), MOVE(0x7F, 0x43), NEVER])
        to_line(zx, 40)
        zx.nr_write(0x62, RUN_EACH_FRAME)
        to_line(zx, 120)
        self.assertEqual(zx.nr_read(0x7F), 0x43)
        to_line(zx, 75)
        self.assertEqual(zx.nr_read(0x7F), 0x42, 'restarted at cvc 0, hc_ula 0 (copper.vhd:79-81)')

    def test_rewriting_the_mode_does_not_restart(self):
        zx = self.machine([MOVE(0x7F, 0x11), NEVER])
        zx.nr_write(0x62, RUN)
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x7F), 0x11)
        zx.nr_write(0x7F, 0x55)
        zx.nr_write(0x62, RUN)                          # the same mode again
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x7F), 0x55, 'copper.vhd:69-77 last_state')
        zx.nr_write(0x62, STOP)
        zx.nr_write(0x62, RESUME)                       # 10: carry on from where it was
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x7F), 0x55, 'resume keeps the address')
        zx.nr_write(0x62, STOP)
        zx.nr_write(0x62, RUN)                          # entering 01: back to 0
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x7F), 0x11, 'copper.vhd:73-74')


@needs_next
class CopperAndNR02(NextCase):
    """§9 D-7: the copper's writes reach NR 0x02 like any other (zxnext:4716-4718,
    3769-3770, 6277-6278), though nextreg.txt says it can't clear its bits."""

    def machine(self, words):
        zx = bare(timing='48k')
        load(zx, words)
        return zx

    def test_the_nmi_flag_sets_even_with_the_nmi_disabled(self):
        """nmi_accept_cause is only "the NMI machine is idle or fetching"
        (zxnext:2123): NR 0x06 gates the NMI itself (zxnext:2049), not the
        flag. (P-11 expected the flag clear; the VHDL sets it.)"""
        zx = bare(timing='48k')
        self.assertEqual(zx.nr_read(0x06) & 0x08, 0x00, 'multiface NMI disabled at power-on')
        zx.nr_write(0x02, 0x08)
        self.assertEqual(zx.nr_read(0x02) & 0x08, 0x08, 'zxnext:3778-3784')
        zx.nr_write(0x02, 0x00)
        self.assertEqual(zx.nr_read(0x02) & 0x08, 0x00, 'writing 0 clears it (zxnext:3782)')

    def test_the_copper_clears_the_flag(self):
        zx = self.machine([MOVE(0x02, 0x00), NEVER])
        zx.nr_write(0x02, 0x08)
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x02) & 0x08, 0x08, 'set, and the copper stopped')
        zx.nr_write(0x62, RUN)
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x02) & 0x08, 0x00, 'a copper MOVE of 0 clears it (D-7)')

    def test_the_copper_can_soft_reset(self):
        zx = self.machine([MOVE(0x02, 0x01), NEVER])
        zx.nr_write(0x57, 0x20)
        zx.nr_write(0x62, RUN)
        zx.run_ticks(5000)                              # the reset line is held ~1023 cycles
        self.assertEqual(zx.nr_read(0x02) & 0x03, 0b10, 'the first soft reset (zxnext:6277)')
        self.assertEqual(zx.nr_read(0x57), 0x01, 'MMU7 reset')
        self.assertEqual(zx.nr_read(0x62), 0x00, 'and the copper with it')

    def test_the_copper_can_hard_reset(self):
        zx = self.machine([MOVE(0x02, 0x02), NEVER])
        zx.nr_write(0x7F, 0x55)
        zx.nr_write(0x62, RUN)
        zx.run_ticks(5000)
        self.assertEqual(zx.nr_read(0x7F), 0xFF, 'NR 0x7F resets only on a hard reset '
                                                 '(zxnext:1210, 6278)')
        self.assertEqual(zx.nr_read(0x02) & 0x03, 0b00, 'power-on again')


if __name__ == '__main__':
    unittest.main()
