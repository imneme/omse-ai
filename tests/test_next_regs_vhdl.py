"""Next registers as the VHDL's read mux returns them: frame-synced copies, bits that always read 0, a field only
config mode can write, Pentagon's 50 Hz, and the AY accessors' chip index.

A foil, written from core 3.02.02's zxnext.vhd alone by Speccy-Zone Fern (Sun 8 Nov 2026), after a cold read of the
repository found NR 0x05 and NR 0x0A and Ratio Fern found NR 0x09. Ratio wrote the fixes, from a description of the
behaviour, not from these tests. Lines are zxnext:N (docs/next-sources.md).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import needs_next, NextCase, bare     # noqa: E402
from test_next_timing import launch                       # noqa: E402

PENTAGON_TIMING = 0x80 | 4 << 4        # NR 0x03: b7 writes the timing field, 100 is Pentagon, type 000 keeps config mode


@needs_next
class FrameSynced(NextCase):
    """At video_frame_sync the effective copies take the written values: eff_nr_05_5060, eff_nr_05_scandouble_en and
    eff_nr_09_scanlines (zxnext:6604-6611). The read mux returns the copies (5804, 5816). So a read straight after a
    write still shows the old bits, and the new ones once a frame has begun."""

    def test_nr05_b2_and_b0_wait_for_the_frame_sync(self):
        zx = bare(timing='48k')
        old = zx.nr_read(0x05)
        new = ~old & 0xFF
        zx.nr_write(0x05, new)
        self.assertEqual(zx.nr_read(0x05), (new & ~0x05) | (old & 0x05),
                         'joysticks at once; b2 (50/60) and b0 (scandoubler) are the frame-synced copies (5804)')
        zx.run_frames(1)
        self.assertEqual(zx.nr_read(0x05), new, 'copied at video_frame_sync (6605-6609)')

    def test_nr09_scanlines_wait_for_the_frame_sync_and_b3_reads_0(self):
        zx = bare(timing='48k')
        old = zx.nr_read(0x09)
        zx.nr_write(0x09, 0xFF)          # (b3 also clears divMMC's mapram, zxnext:4125; harmless here)
        self.assertEqual(zx.nr_read(0x09), 0xF4 | (old & 0x03),
                         'mono b7:5, tie b4, b3 reads 0, HDMI audio b2 as written; scanlines b1:0 the old copy (5816)')
        zx.run_frames(1)
        self.assertEqual(zx.nr_read(0x09), 0xF7, 'scanlines copied at video_frame_sync (6608)')


@needs_next
class Pentagon(NextCase):
    """While NR 0x03's written machine timing is Pentagon, nr_05_5060 is held at 0 on every clock (zxnext:5741-5742):
    "Pentagon is always 50 Hz"."""

    def test_a_write_of_60_hz_is_held_at_50(self):
        zx = bare(timing='pentagon')
        zx.nr_write(0x05, zx.nr_read(0x05) | 0x04)
        self.assertFalse(zx.nr_read(0x05) & 0x04, 'at once (the copy was 0)')
        zx.run_frames(1)
        self.assertFalse(zx.nr_read(0x05) & 0x04, 'and after the frame sync (5742)')

    def test_choosing_pentagon_clears_60_hz(self):
        zx = bare(timing='48k')
        zx.nr_write(0x05, zx.nr_read(0x05) | 0x04)
        zx.run_frames(1)
        self.assertTrue(zx.nr_read(0x05) & 0x04, '60 Hz in effect under 48K timing')
        zx.nr_write(0x03, PENTAGON_TIMING)              # bare is in config mode, so the timing field is written
        zx.run_frames(1)
        self.assertFalse(zx.nr_read(0x05) & 0x04, 'held at 0 once Pentagon is written (5741-5742), copied at the sync')


@needs_next
class Nr0A(NextCase):
    """The read mux: nr_0a_mf_type & '0' & automap & mouse reverse & '0' & mouse dpi (zxnext:5819). The multiface type
    is written only in config mode (5130-5133); the other fields always."""

    def test_b5_and_b2_read_0(self):
        zx = bare(timing='48k')
        zx.nr_write(0x0A, 0xFF)
        self.assertEqual(zx.nr_read(0x0A), 0xDB, 'b5 and b2 are constant 0 in the read mux (5819)')

    def test_the_multiface_type_only_in_config_mode(self):
        zx = bare(timing='48k')
        zx.nr_write(0x0A, 0x40)                         # bare is in config mode: mf type 01
        self.assertEqual(zx.nr_read(0x0A) & 0xC0, 0x40)
        zx.nr_write(0x03, 0x01)                         # 48K type: accepted, and config mode is left (zxnext:5076)
        zx.nr_write(0x0A, 0xD1)
        self.assertEqual(zx.nr_read(0x0A), 0x40 | (0xD1 & 0x1B),
                         'mf type kept out of config mode (5131); automap, reverse and dpi written')


@needs_next
class AyIndex(NextCase):
    """There are three AYs (TurboSound): chips 0, 1 and 2. The accessors must refuse any other index rather than read
    past the array."""

    def test_a_bad_chip_is_refused(self):
        zx = bare(timing='48k')
        for chip in (0, 1, 2):
            zx.ay_chan(chip)
            zx.ay_env(chip)
        for chip in (-1, 3):
            with self.assertRaises((ValueError, IndexError)):
                zx.ay_chan(chip)
            with self.assertRaises((ValueError, IndexError)):
                zx.ay_env(chip)


@needs_next
class CpuSoftReset(NextCase):
    """NEXTREG 02h,01h from a running program: the soft reset happens inside a CPU edge. The reset type shifts on
    every reset, '0' & b2 & (b1 or b0), from "100" at power-on (zxnext:1299, 1695), so NR 0x02 reads 10 after the
    first and 01 after the next. RAM survives, and the CPU starts again at 0."""

    def test_a_program_can_soft_reset_twice(self):
        zx = bare(timing='48k')
        code = bytes([0xF3, 0x3E, 0x5A, 0x32, 0x00, 0x90,          # DI; LD A,5Ah; LD (9000h),A
                      0xED, 0x91, 0x02, 0x01, 0x18, 0xFE])         # NEXTREG 02h,01h; JR $
        zx.load(0x8100, code)
        launch(zx, 0x8100)
        self.assertTrue(zx.run_until_pc(0x0000, max_ticks=10**6), 'the CPU starts again at 0')
        self.assertEqual(zx.nr_read(0x02) & 3, 2, 'first reset after power-on reads 10 (1695)')
        self.assertEqual(zx.read(0x9000, 1), b'\x5a', 'RAM survives a soft reset')
        zx.nr_write(0x02, 0x01)
        self.assertEqual(zx.nr_read(0x02) & 3, 1, 'the next reads 01 (1695)')


if __name__ == '__main__':
    unittest.main()
