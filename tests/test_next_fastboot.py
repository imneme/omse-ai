"""boot='fast': the state NextZXOS finds after the firmware's handover
(the foil, Loam Fern).

From the survey's §7.2-§7.3 (the firmware: tbblue fw/app/src/boot.c:279-407,
445-598, with the shipped machines/next/CONFIG.INI) and machine/ERRATA.md,
through DESIGN.md §9/§9.1 (1) only: fast boot is the Next personality's
handover, ending in the soft reset that leaves config mode behind. Values are
what nr_read returns (the read mux, zxnext:5789-6194), which differ from
what the firmware wrote where the reset or the read layout says so.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, park  # noqa: E402

# (value nr_read returns, why)
AFTER_HANDOVER = {
    0x02: (0x02, 'reset type "hard": the handover is the first soft reset (§4.3; zxnext:1695)'),
    0x03: (0x33, '+3 timing and type: NR 0x03 = 0x80|(2+1)<<4|(2+1) (boot.c:581-598)'),
    0x05: (0x71, 'Kempston 1, Sinclair 1, 50 Hz, scandoubler (boot.c:279-323; CONFIG.INI)'),
    0x06: (0xBD, 'the firmware wrote 0x9D; the soft reset sets b7 and b5 (zxnext:4871-4872; '
                 'ERRATA, Ratio)'),
    0x07: (0x00, '3.5 MHz: reset by the soft reset (zxnext:5694)'),
    0x08: (0x9E, 'written 0x1E; b7 reads "not locked" (zxnext:5813)'),
    0x09: (0x00, 'boot.c:279-323'),
    0x0A: (0x11, 'MF+3, divMMC automap on, mouse dpi 01 (boot.c:279-323)'),
    0x82: (0xDA, 'port FF, DFFD and 0x6B off for the +3 personality (boot.c:325-406)'),
    0x83: (0x3F, 'sprite and Layer 2 ports off (boot.c:325-406)'),
    0x84: (0xFF, 'AY and every DAC (boot.c:325-406)'),
    0x85: (0x01, 'ULA+ on, Z80-DMA off, b7 = 0 so they survived the soft reset (boot.c:325-327)'),
}
MMU_DEFAULT = [0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x00, 0x01]


def fast():
    try:
        return Next(boot='fast')
    except Exception as e:                              # the ROM images may not be on this machine
        if 'rom' in str(e).lower():
            raise unittest.SkipTest(f'boot="fast" needs the ROM images: {e}')
        raise


@needs_next
class FastBoot(NextCase):

    def test_registers_after_the_handover(self):
        """Read at the handover itself: NextZXOS, once it runs, rewrites some of
        these (speed, NR 0x06, the port enables; §7.3 "presumably NextZXOS
        changes these")."""
        zx = fast()
        bad = [f'NR {r:#04x}: read {zx.nr_read(r):#04x}, want {v:#04x} ({why})'
               for r, (v, why) in AFTER_HANDOVER.items()
               if r != 0x05 and zx.nr_read(r) != v]
        self.assertEqual(bad, [])
        park(zx)                                        # NR 0x05's 50/60 and scandoubler bits are
        zx.run_frames(1)                                # frame-synced: settle them, ROM not running
        self.assertEqual(zx.nr_read(0x05), AFTER_HANDOVER[0x05][0], AFTER_HANDOVER[0x05][1])

    def test_the_cpu_starts_at_0000_in_rom_0(self):
        zx = fast()
        self.assertEqual(zx.regs().get('pc'), 0x0000, '§7.1: after any reset, PC = 0')
        self.assertEqual(zx.slot_page(0), ('rom', 0), 'boot ROM off, ROM 0 of the +3 type')
        self.assertEqual([zx.nr_read(0x50 + i) for i in range(8)], MMU_DEFAULT,
                         'MMU at its defaults (zxnext:4552-4559)')

    def test_config_mode_is_over(self):
        zx = fast()
        zx.nr_write(0x03, 0x01)                         # a type write: refused outside config mode
        self.assertEqual(zx.nr_read(0x03) & 0x07, 0x03, 'zxnext:5076; §7.2 7')

    def test_the_divmmc_and_multiface_nmis_are_on(self):
        zx = fast()
        self.assertEqual(zx.nr_read(0x06) & 0x18, 0x18, 'their ROMs named in the menu line '
                                                        '(boot.c:548-573)')


if __name__ == '__main__':
    unittest.main()
