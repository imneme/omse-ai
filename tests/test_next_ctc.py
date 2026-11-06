"""The Next's CTC: timer periods in 28 MHz ticks, chaining, polled status and
pulse interrupts, the missing channels 4-7 (the foil, Loam Fern).

From the survey's §8 (CTC) and §6, ctc_chan.vhd (Zilog Z8430-style, with its
clarifications 1-6) and zxnext.vhd:4005-4034 (four channels), core 3.02.02,
through DESIGN.md §9 only.

The channel (ctc_chan.vhd): the prescaler counts 28 MHz ticks and pulses
every 16 (control D5 = 0) or 256 (D5 = 1); in timer mode (D6 = 0) each pulse
decrements the count, and at zero ZC/TO goes up for one cycle and the time
constant reloads. So the period is TC x 16 or TC x 256 ticks, TC = 0 being
256. Periods are measured between successive ZC/TOs (as status bits), so
the start-up offset cancels.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import completed                   # noqa: E402

CH = [0x183B, 0x193B, 0x1A3B, 0x1B3B, 0x1C3B, 0x1D3B, 0x1E3B, 0x1F3B]   # A10:8 (zxnext:2649)
TIMER, PRESCALE_256, COUNTER, INT_EN = 0x00, 0x20, 0x40, 0x80
CONTROL = 0x07                      # D2 time constant follows, D1 soft reset, D0 control word


def program(zx, ch, mode, tc):
    zx.io_out(CH[ch], CONTROL | mode)
    zx.io_out(CH[ch], tc)


def zc_times(case, zx, bit, count, limit):
    """The ticks at which CTC channel `bit`'s status (NR 0xC9) goes up, `count`
    times, clearing it after each; fails rather than spins past `limit` ticks."""
    times, mask = [], 1 << bit
    zx.nr_write(0xC9, mask)
    for _ in range(limit):
        zx.run_ticks(1)
        if zx.nr_read(0xC9) & mask:
            times.append(zx.t28)
            zx.nr_write(0xC9, mask)
            if len(times) == count:
                return times
    case.fail(f'CTC {bit}: {len(times)} of {count} ZC/TOs in {limit} ticks')


def gaps(times):
    return {b - a for a, b in zip(times, times[1:])}


@needs_next
class Timer(NextCase):

    def test_prescale_16(self):
        zx = bare()
        program(zx, 0, TIMER, 100)
        self.assertEqual(gaps(zc_times(self, zx, 0, 4, 10000)), {1600}, 'TC 100 x 16 ticks')

    def test_prescale_256(self):
        zx = bare()
        program(zx, 0, TIMER | PRESCALE_256, 10)
        self.assertEqual(gaps(zc_times(self, zx, 0, 3, 12000)), {2560}, 'TC 10 x 256 ticks')

    def test_time_constant_0_is_256(self):
        zx = bare()
        program(zx, 2, TIMER, 0)
        self.assertEqual(gaps(zc_times(self, zx, 2, 3, 15000)), {4096}, '256 x 16 ticks')

    def test_count_reads_back_and_falls(self):
        zx = bare()
        program(zx, 1, TIMER | PRESCALE_256, 200)
        zx.run_ticks(256 * 5)
        a = zx.io_in(CH[1])
        zx.run_ticks(256 * 20)
        b = zx.io_in(CH[1])
        self.assertTrue(1 <= b < a <= 200, f'counts {a} then {b} (ctc_chan.vhd o_cpu_d)')

    def test_channel_0_triggers_channel_1(self):
        zx = bare()
        program(zx, 1, COUNTER, 3)                      # counts channel 0's ZC/TO (zxnext:4025)
        program(zx, 0, TIMER, 100)
        self.assertEqual(gaps(zc_times(self, zx, 1, 3, 20000)), {4800}, 'every third of 1600')

    def test_channels_4_to_7_dont_exist(self):
        zx = bare()
        program(zx, 0, TIMER | PRESCALE_256, 200)
        zx.run_ticks(256 * 3)
        self.assertTrue(1 <= zx.io_in(CH[0]) <= 200, 'channel 0 answers with its count')
        for ch in range(4, 8):
            self.assertEqual(zx.io_in(CH[ch]), 0x00, f'port {CH[ch]:#06x}: §9 D-5, P-3')


@needs_next
class Interrupts(NextCase):
    """§6: a disabled CTC channel records status only ("polled mode",
    nr:1071); enabled, it fires the pulse."""

    def test_disabled_channel_is_polled(self):
        zx = bare()
        zx.nr_write(0x22, 0x04)                         # ULA interrupt off
        program(zx, 0, TIMER, 100)
        n = len(zx.int_log)
        times = zc_times(self, zx, 0, 3, 10000)
        self.assertEqual(len(zx.int_log), n, 'status, but no pulse (im2p:150-192)')
        self.assertEqual(gaps(times), {1600})

    def test_enabled_channel_pulses(self):
        zx = bare()
        zx.nr_write(0x22, 0x04)
        program(zx, 0, TIMER | INT_EN, 100)
        self.assertEqual(zx.nr_read(0xC5) & 0x01, 0x01, 'D7 is the channel\'s enable '
                                                       '(ctc_chan.vhd:276; zxnext:6148)')
        n = len(zx.int_log)
        zx.run_ticks(1600 * 5)
        starts = [s for s, e in completed(zx.int_log[n:])]
        self.assertGreaterEqual(len(starts), 3)
        self.assertEqual(gaps(starts), {1600}, 'one pulse a period')

    def test_nr_c5_enables_it_too(self):
        zx = bare()
        zx.nr_write(0x22, 0x04)
        program(zx, 3, TIMER, 50)
        zx.nr_write(0xC5, 0x08)                         # channel 3 (zxnext:4019)
        n = len(zx.int_log)
        zx.run_ticks(800 * 5)
        self.assertGreaterEqual(len(completed(zx.int_log[n:])), 3, 'NR 0xC5 b3')


if __name__ == '__main__':
    unittest.main()
