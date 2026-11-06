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
from test_next_timing import program, launch, CODE  # noqa: E402

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


@needs_next
class SpeedChangeMidCycle(NextCase):
    """Gap #7 (Speccy-Zone's survivor): a speed change waits for the next T1.
    cpu_speed copies NR 0x07's selection only at a rising CPU edge with MREQ,
    IORQ and M1 all high (zxnext:5703-5735). In a sled of LD A,(HL) (fetch 4 T,
    read 3 T, code and data in page 4, uncontended), those are exactly the
    edges that begin a fetch's T1 or the read's T1. NR 0x07 reads cpu_speed in
    bits 5:4 and the selection in bits 1:0 (zxnext:5810), so the copper's MOVE
    is seen landing (W) and the switch taking effect (S), tick by tick.

    A copy on the very tick W lands may see either selection (the CPU clock is a
    register's output through a BUFGMUX, so the VHDL leaves that race open), so a
    W on a T1 edge accepts that edge or the next T1. Everywhere else S is the
    first T1 edge after W, with every edge before it at the old speed: a cycle
    under way finishes at the speed it began. (Up to 14 MHz and back down: 28 MHz
    goes through the BUFGMUX's switch-over, a separate question.)"""

    PERIOD = {0: 8, 1: 4, 2: 2}                         # t28 per CPU clock

    def trace(self, k, h, old, new, v=60):
        zx = bare(timing='48k', speed=old)
        load(zx, [WAIT(v, h), MOVE(0x07, new), NEVER])
        code, s, e = program([0x21, 0x00, 0x90], [0x7E], 1500, prefix=k)
        zx.load(CODE, code)
        to_line(zx, v - 1)
        zx.nr_write(0x62, RUN)
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(CODE + s, max_ticks=10**6), 'the sled never started')
        c0, rows, done = zx.cpu_clocks, [], None
        for t in range(1, 4 * L48 * ref.TICKS_PER_PIXEL):
            zx.run_ticks(1)
            r = zx.nr_read(0x07)
            rows.append((t, zx.cpu_clocks - c0, r & 3, r >> 4 & 3, zx.speed))
            if done is None and r >> 4 & 3 == new:
                done = t
            if done is not None and t > done + 64:
                break
        return rows

    def switch(self, k, h, old, new):
        """Check one switch; return (T-state of the sled W landed in, whether W
        fell on an edge, edges from W's to S)."""
        rows = self.trace(k, h, old, new)
        name = f'{old} -> {new} by a copper MOVE at WAIT(60, {h}), prefix {k}'
        W = next((r for r in rows if r[2] == new), None)
        S = next((r for r in rows if r[3] == new), None)
        self.assertIsNotNone(W, f'{name}: NR 0x07 bits 1:0 never read {new}')
        self.assertIsNotNone(S, f'{name}: NR 0x07 bits 5:4 never read {new}')
        self.assertEqual(S[4], new, f'{name}: zx.speed disagrees with NR 0x07 bits 5:4')
        edge, prev = {}, 0                              # tick -> edge index (0: the sled's first T1)
        for t, c, *_ in rows:
            if c != prev:
                self.assertEqual(c, prev + 1, f'{name}: two CPU edges in one tick at {t}')
                edge[t] = c - 1
            prev = c
        self.assertIn(S[0], edge, f'{name}: the switch (tick {S[0]}) is not on a rising CPU edge')
        t1 = sorted(t for t, i in edge.items() if i % 7 in (0, 4))
        want = {min(t for t in t1 if t > W[0])} | ({W[0]} if W[0] in t1 else set())
        iw = edge[max(t for t in edge if t <= W[0])]
        where = ['fetch T1', 'fetch T2', 'fetch T3', 'fetch T4', 'read T1', 'read T2', 'read T3']
        self.assertIn(S[0], want,
                      f'{name}: NR 0x07 written at tick {W[0]} (in the sled\'s {where[iw % 7]}), '
                      f'speed changed at tick {S[0]} (edge {edge[S[0]]}, its {where[edge[S[0]] % 7]}); '
                      f'want the first T1 edge after it, tick {sorted(want)}')
        ticks = sorted(edge)
        before = [t for t in ticks if t <= S[0]][-4:]
        self.assertEqual([b - a for a, b in zip(before, before[1:])], [self.PERIOD[old]] * 3,
                         f'{name}: the clocks up to the switch run at the old speed')
        after = [t for t in ticks if t > S[0]][:4]
        self.assertEqual([b - a for a, b in zip(after[1:], after[2:])], [self.PERIOD[new]] * 2,
                         f'{name}: the clocks after the switch run at the new speed')
        return iw % 7, W[0] in edge, edge[S[0]] - iw

    def test_the_switch_waits_for_the_next_t1(self):
        seen = []
        for old, new in [(0, 2), (2, 0)]:
            for k in (0, 1):
                for h in range(14):
                    seen.append(self.switch(k, h, old, new))
        mid_read = [s for s in seen if s[0] in (5, 6)]
        self.assertTrue(mid_read, 'no MOVE landed in a read\'s T2 or T3')
        self.assertTrue([s for s in seen if s[0] in (1, 2, 3)], 'no MOVE landed inside a fetch')
        self.assertTrue([s for s in mid_read if s[2] >= 2],
                        'no case where the edge after the MOVE was not yet a T1 (nothing to tell '
                        '"the next T1" from "the next edge")')
