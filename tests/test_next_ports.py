"""The Next's port enables (NR 0x82-0x85) and the joystick ports' gating
(the foil, Loam Fern).

From the survey's §5 and zxnext.vhd:2356-2401 (the enable bits), 2537-2658
(the decodes), core 3.02.02, through DESIGN.md §9/§9.1 only. Each test shows
the port working while enabled before showing it ignored while disabled, so
a machine that ignores the port altogether can't pass.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_memory import out, mmu                    # noqa: E402

# Enable bits (zxnext:2356-2401): (register, bit) of NR 0x82-0x85.
EN = {'ff': (0x82, 0), '7ffd': (0x82, 1), 'dffd': (0x82, 2), '1ffd': (0x82, 3),
      'p3float': (0x82, 4), 'dma6b': (0x82, 5), '1f': (0x82, 6), '37': (0x82, 7),
      'divmmc': (0x83, 0), 'mf': (0x83, 1), 'i2c': (0x83, 2), 'spi': (0x83, 3),
      'uart': (0x83, 4), 'mouse': (0x83, 5), 'sprite': (0x83, 6), 'layer2': (0x83, 7),
      'ay': (0x84, 0), 'ulap': (0x85, 0), 'dma0b': (0x85, 1), 'eff7': (0x85, 2),
      'ctc': (0x85, 3)}


def disable(zx, name):
    reg, bit = EN[name]
    zx.nr_write(reg, zx.nr_read(reg) & ~(1 << bit) & 0xFF)
    zx.run_ticks(64)                                    # sampled in memory cycles (zxnext:2408)


@needs_next
class Enables(NextCase):

    def test_port_ff_writes(self):
        zx = bare()
        out(zx, 0x00FF, 0x05)
        self.assertEqual(zx.nr_read(0x69) & 0x3F, 0x05, 'port FF b5:0 = NR 0x69 b5:0 (zxnext:6003)')
        disable(zx, 'ff')
        out(zx, 0x00FF, 0x02)
        self.assertEqual(zx.nr_read(0x69) & 0x3F, 0x05, 'zxnext:2673 port_ff_wr needs bit 0')

    def test_dffd(self):
        zx = bare()
        out(zx, 0xDFFD, 0x01)
        self.assertEqual(mmu(zx)[6], 0x10, 'bank 8 at C000h (zxnext:3704-3707)')
        disable(zx, 'dffd')
        out(zx, 0xDFFD, 0x02)
        self.assertEqual(mmu(zx)[6], 0x10, 'zxnext:2555, 2359')

    def test_1ffd(self):
        zx = bare()                                     # +3 timing: 1FFD can't fall to 7FFD
        out(zx, 0x1FFD, 0x01)
        self.assertEqual(mmu(zx), ref.all_ram_mmu(0), 'all-RAM on')
        out(zx, 0x1FFD, 0x00)
        disable(zx, '1ffd')
        out(zx, 0x1FFD, 0x01)
        self.assertEqual(mmu(zx)[0], 0xFF, 'zxnext:2557, 2360')

    def test_eff7(self):
        zx = bare()
        out(zx, 0xEFF7, 0x08)
        self.assertEqual(mmu(zx)[:2], [0x00, 0x01])
        out(zx, 0xEFF7, 0x00)
        disable(zx, 'eff7')
        out(zx, 0xEFF7, 0x08)
        self.assertEqual(mmu(zx)[:2], [0xFF, 0xFF], 'zxnext:2563, 2400')

    def test_layer2_port(self):
        zx = bare()
        zx.nr_write(0x03, 0x00)                         # boot ROM off
        out(zx, 0x123B, 0x01)
        zx.poke(0x0010, 0x5A)
        page = ref.layer2_page(0x08, 0, 0, 0)
        self.assertEqual(zx.sram[ref.sram_of_page(page) + 0x10], 0x5A, 'write map on')
        out(zx, 0x123B, 0x00)                           # map off again
        disable(zx, 'layer2')
        out(zx, 0x123B, 0x01)
        zx.poke(0x0011, 0x5B)
        self.assertEqual(zx.sram[ref.sram_of_page(page) + 0x11], 0x00, 'zxnext:2594, 2375')
        self.assertEqual(zx.sram[0x0011], 0x5B, 'the write went to config mode\'s page')

    def test_ula_plus(self):
        zx = bare()
        out(zx, 0xBF3B, 0x40)                           # mode group 01
        out(zx, 0xFF3B, 0x01)
        self.assertEqual(zx.nr_read(0x68) & 0x08, 0x08, 'zxnext:4484-4495, read 6000')
        out(zx, 0xFF3B, 0x00)
        disable(zx, 'ulap')
        out(zx, 0xBF3B, 0x40)
        out(zx, 0xFF3B, 0x01)
        self.assertEqual(zx.nr_read(0x68) & 0x08, 0x00, 'zxnext:2644-2645, 2394')

    def test_ay(self):
        zx = bare()
        out(zx, 0xFFFD, 0x00)                           # select register 0
        out(zx, 0xBFFD, 0x55)
        self.assertEqual(zx.io_in(0xFFFD), 0x55, 'AY register 0 reads back (zxnext:2784)')
        disable(zx, 'ay')
        self.assertEqual(zx.io_in(0xFFFD), 0xFF, 'unanswered: FF (zxnext:2606, 1827-1841)')


@needs_next
class TimexPortReadback(NextCase):
    """Port FFh reads the Timex register only with port enable 0 (NR 82h b0)
    and NR 08h b2 both set; otherwise it's port_ff_dat_ula, the floating bus in
    48K/128K timing and FFh at +3 (zxnext:2772, 4454, 2356, 5119). Writes need
    the enable too (2673). Scree found it: the Multiface saves port FF by
    reading it, so a wrong read restored the wrong screen mode."""

    def machine(self, nr08_b2, nr82_b0):
        zx = bare()
        zx.io_out(0x00FF, 0x05)                         # with the enable on (power-on NR 82h = FFh)
        zx.run_ticks(16)
        zx.nr_write(0x08, (zx.nr_read(0x08) & 0x7F) | nr08_b2 << 2)
        zx.nr_write(0x82, 0xFE | nr82_b0)
        zx.run_ticks(16)
        return zx

    def test_both_set_reads_the_timex_register(self):
        self.assertEqual(self.machine(1, 1).io_in(0x00FF), 0x05)

    def test_without_nr08_b2_it_is_the_floating_bus(self):
        self.assertEqual(self.machine(0, 1).io_in(0x00FF), 0xFF, '+3 timing: FFh (zxnext:4454)')

    def test_without_the_port_enable_it_is_the_floating_bus(self):
        self.assertEqual(self.machine(1, 0).io_in(0x00FF), 0xFF, 'the register holds 05h, unread')


@needs_next
class Joysticks(NextCase):
    """§9 D-13: port 0x1F answers only while a joystick is Kempston 1 or MD 1."""

    def joy(self, zx, nr05):
        zx.nr_write(0x05, nr05)
        zx.run_ticks(64)                                # port_1f_hw_en in memory cycles

    def test_port_1f_needs_a_kempston_joystick(self):
        zx = bare()                                     # NR 0x05 = 0x41: joystick 1 Kempston 1
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x001F), 0x00, 'idle Kempston (zxnext:3433, 2633)')
        self.joy(zx, 0x01)                              # both Sinclair 2
        self.assertEqual(zx.io_in(0x001F), 0xFF, 'not Kempston: unanswered (§9 D-13)')

    def test_port_1f_enable(self):
        zx = bare()
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x001F), 0x00)
        disable(zx, '1f')
        self.assertEqual(zx.io_in(0x001F), 0xFF, 'zxnext:2633, 2362')

    def test_port_37_needs_kempston_2(self):
        zx = bare()
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x0037), 0xFF, 'joystick 2 is Sinclair 2 at power-on')
        self.joy(zx, 0x08 | 0x01)                       # joystick 1 = 100, Kempston 2
        self.assertEqual(zx.io_in(0x0037), 0x00, 'zxnext:3434, 2634')


if __name__ == '__main__':
    unittest.main()
