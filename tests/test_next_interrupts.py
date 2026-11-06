"""The Next's interrupt controller: status, NR 0x20, pulse mode's INTACK, the
IM snooper and hardware IM2 mode (the foil, Loam Fern).

From the survey's §6, zxnext.vhd:1884-1962 and the device files
im2_peripheral.vhd, im2_device.vhd and im2_control.vhd (core 3.02.02),
through DESIGN.md §9/§9.1 only. Programs take real interrupts: a main loop at
CODE in IM 1 or IM 2, handlers that mark how they were reached.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch, pulses              # noqa: E402

CODE = 0x8100
F48 = ref.frame_ticks('48k', 50)
IM = {0: [0xED, 0x46], 1: [0xED, 0x56], 2: [0xED, 0x5E]}
RETI, RET = [0xFB, 0xED, 0x4D], [0xFB, 0xC9]           # each after EI


def main_loop(zx, mode, i_reg=0x90):
    """At CODE: DI; LD A,i; LD I,A; IM mode; EI; L: JR L.  Returns L."""
    code = [0xF3, 0x3E, i_reg, 0xED, 0x47] + IM[mode] + [0xFB]
    loop = CODE + len(code)
    zx.load(CODE, bytes(code + [0x18, 0xFE]))
    return loop


def handler(zx, addr, tail=RETI):
    zx.load(addr, bytes(tail))


def vector(zx, i_reg, low, target):
    zx.poke(i_reg << 8 | low, target & 0xFF)
    zx.poke((i_reg << 8 | low) + 1, target >> 8)


def reached(zx, addr, ticks):
    """run_until_pc said so, and the PC agrees."""
    return zx.run_until_pc(addr, max_ticks=ticks) and zx.regs().get('pc') == addr


def entries(zx, addr, back, frames):
    """How many times the CPU starts the code at addr within `frames` frames."""
    end, n = zx.t28 + frames * F48, 0
    while zx.t28 < end and zx.run_until_pc(addr, max_ticks=end - zx.t28):
        n += 1
        assert n <= 4 * frames, f'{n} entries in {frames} frames: time is not passing'
        assert zx.run_until_pc(back, max_ticks=F48), 'the handler never returned'
    return n


@needs_next
class Status(NextCase):
    """§6.4: status bits, set by a request's edge, cleared by writing 1."""

    def test_ula_interrupt_sets_status(self):
        zx = bare(timing='48k')
        pulses(self, zx, 2, at_least=1)
        self.assertEqual(zx.nr_read(0xC8) & 0x01, 0x01, 'im2p:150-160; read zxnext:6154')
        self.assertEqual(zx.nr_read(0x20) & 0x40, 0x40, 'NR 0x20 b6 (zxnext:5895)')
        zx.nr_write(0xC8, 0x01)
        self.assertEqual(zx.nr_read(0xC8) & 0x01, 0x00, 'write 1 clears (zxnext:1911-1914)')

    def test_disabled_ula_or_line_interrupt_records_nothing(self):
        """Their enables gate the request itself at the timing generator
        (ulat:551, 581; zxnext:6657-6659), so the "polled mode" of a disabled
        source (nr:1071) is the CTC's and UARTs', not theirs."""
        zx = bare(timing='48k')
        pulses(self, zx, 2, at_least=1)
        self.assertEqual(zx.nr_read(0xC8) & 0x01, 0x01, 'enabled, it records')
        zx.nr_write(0x22, 0x04)                         # ULA off, line off
        zx.nr_write(0xC8, 0x03)
        zx.run_frames(3)
        self.assertEqual(zx.nr_read(0xC8) & 0x03, 0x00, 'disabled, nothing')

    def test_line_interrupt_sets_status(self):
        zx = bare(timing='48k')
        zx.nr_write(0x22, 0x06)                         # ULA off, line on
        zx.nr_write(0x23, 100)
        pulses(self, zx, 2, at_least=1)
        self.assertEqual(zx.nr_read(0xC8) & 0x03, 0x02, 'line is status bit 0 -> C8 b1')
        self.assertEqual(zx.nr_read(0x20) & 0x80, 0x80, 'NR 0x20 b7')
        zx.nr_write(0xC8, 0x02)
        self.assertEqual(zx.nr_read(0xC8) & 0x02, 0x00)

    def test_nr20_raises_status_and_a_pulse_regardless_of_enables(self):
        for bit, c8, c9 in [(0x40, 0x01, 0), (0x80, 0x02, 0), (0x05, 0, 0x05)]:
            zx = bare(timing='48k')
            zx.nr_write(0x22, 0x04)                     # every source off
            zx.run_frames(1)
            n = len(zx.int_log)
            zx.nr_write(0x20, bit)
            zx.run_ticks(2000)
            self.assertEqual(zx.nr_read(0xC8) & 0x03, c8, f'NR 0x20 = {bit:#04x}: zxnext:1905')
            self.assertEqual(zx.nr_read(0xC9) & 0x0F, c9, 'CTC 3-0 from b3:0')
            self.assertEqual(len(zx.int_log), n + 1, 'one pulse (im2p:192 i_int_unq)')


@needs_next
class PulseMode(NextCase):
    """§6.2: every enabled source fires the same pulse; INTACK reads 0xFF."""

    def test_im2_in_pulse_mode_vectors_through_ff(self):
        zx = bare(timing='48k')
        loop = main_loop(zx, 2)
        vector(zx, 0x90, 0xFF, 0x9300)
        vector(zx, 0x90, 0xB6, 0x9200)                  # where hardware IM2 would go
        handler(zx, 0x9300)
        handler(zx, 0x9200)
        launch(zx, CODE)
        self.assertTrue(reached(zx, 0x9300, 3 * F48),
                        'INTACK data 0xFF in pulse mode (zxnext:1827-1837)')

    def test_snooped_im_mode_reads_in_nr_c0(self):
        for mode, bits in [(1, 0x02), (2, 0x04), (0, 0x00)]:
            zx = bare(timing='48k')
            loop = main_loop(zx, mode)
            launch(zx, CODE)
            assert zx.run_until_pc(loop, max_ticks=10**5)
            self.assertEqual(zx.nr_read(0xC0) & 0x06, bits, f'IM {mode}: im2c:212-229, '
                                                           f'read zxnext:6136-6137')


@needs_next
class HardwareIM2(NextCase):
    """§6.3: NR 0xC0 b0 = 1: each source its own vector, served until RETI."""

    def setup(self, mode=2, tail=RETI, c0=0xA1, nr22=0x00, line=None):
        zx = bare(timing='48k')
        zx.nr_write(0x22, nr22)
        if line is not None:
            zx.nr_write(0x23, line)
        zx.nr_write(0xC0, c0)                           # vector top bits 101, IM2 mode
        loop = main_loop(zx, mode)
        for src, h in [(11, 0x9200), (0, 0x9400)]:      # ULA, line
            vector(zx, 0x90, (c0 & 0xE0) | src << 1, h)
            handler(zx, h, tail)
        vector(zx, 0x90, 0xFF, 0x9300)
        handler(zx, 0x9300, tail)
        return zx, loop

    def test_ula_vector(self):
        zx, loop = self.setup()
        launch(zx, CODE)
        self.assertTrue(reached(zx, 0x9200, 3 * F48),
                        'vector = NR 0xC0 b7:5 & 1011 & 0 = 0xB6 (zxnext:1958; im2d:155)')

    def test_line_vector(self):
        zx, loop = self.setup(nr22=0x06, line=60)       # ULA off, line 60 on
        launch(zx, CODE)
        self.assertTrue(reached(zx, 0x9400, 3 * F48),
                        'line is source 0: vector 0xA0')

    def test_reti_ends_service(self):
        zx, loop = self.setup(tail=RETI)
        launch(zx, CODE)
        self.assertEqual(entries(zx, 0x9200, loop, 4), 4, 'served every frame with RETI')

    def test_without_reti_the_source_stays_in_service(self):
        zx, loop = self.setup(tail=RET)
        launch(zx, CODE)
        self.assertEqual(entries(zx, 0x9200, loop, 4), 1,
                         'S_ISR until RETI (ED 4D only, im2d:83-131; im2c:233-234)')

    def test_ula_still_pulses_when_the_cpu_is_not_in_im2(self):
        zx, loop = self.setup(mode=1)
        zx.nr_write(0x50, 0x20)                         # RAM at 0: RST 38 lands in it
        zx.load(0x0038, bytes([0xC3, 0x00, 0x95]))      # JP 9500h
        handler(zx, 0x9500)
        launch(zx, CODE)
        self.assertTrue(reached(zx, 0x9500, 3 * F48),
                        'the ULA is the exception (zxnext:1923; im2p:190-192; cl:3.02.00)')

    def test_other_sources_wait_until_im2(self):
        zx, loop = self.setup(mode=1, nr22=0x06, line=60)   # ULA off, line on, CPU in IM 1
        zx.nr_write(0x50, 0x20)
        zx.load(0x0038, bytes([0xC3, 0x00, 0x95]))
        handler(zx, 0x9500)
        launch(zx, CODE)
        self.assertFalse(zx.run_until_pc(0x9500, max_ticks=2 * F48),
                         'no INT while the Z80 is not in IM 2 (im2d:150)')
        zx.load(loop, bytes(IM[2] + [0x18, 0xFE - 2]))     # IM 2, then JR back to it
        self.assertTrue(reached(zx, 0x9400, 2 * F48),
                        'the frozen request is served once it is (cl:3.02.00)')


if __name__ == '__main__':
    unittest.main()
