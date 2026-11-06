"""The Next registers: power-on and reset values as read back, writes, NR 0x03.

The foil (Loam Fern): written from the core 3.02.02 VHDL and the survey,
through DESIGN.md §9 and §9.1 only, independently of the core. Each expectation
comes from nextref.py, which cites the VHDL line that sets it and the line that
reads it back, and whose citations test_next_ref.py checks against the source.

Until next.py exists these skip, naming the missing machine. Once it exists,
anything missing fails rather than skips.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402


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

PARK = 0x8000                       # MMU4 = page 4 at power-on (zxnext:4556)
LOOP = bytes([0xF3, 0x18, 0xFE])    # DI; JR $ (on itself)


def bare(**kw):
    """The exact power-on state (§9.1 1), with the CPU parked in a loop in RAM
    so time can pass without it wandering (bare's boot-ROM area reads 0xFF,
    §9.1 2, which would be RST 38 for ever)."""
    zx = Next(boot='bare', **kw)
    park(zx)
    return zx


def park(zx):
    zx.load(PARK, LOOP)
    zx.set_regs(pc=PARK, sp=0x7FF0)


class NextCase(unittest.TestCase):
    maxDiff = None                                      # show every mismatch, not the first few


def mismatches(zx, table):
    """[(reg, want, got, why)] for every register in table whose read differs."""
    out = []
    for reg, (want, *why) in table.items():
        got = zx.nr_read(reg)
        if got != want:
            out.append(f'NR {reg:#04x}: read {got:#04x}, want {want:#04x} ({"; ".join(why)})')
    return out


@needs_next
class PowerOn(NextCase):
    """§4.2: the hard_reset column, as nr_read returns it (zxnext:5789-6194)."""

    def test_selection_port_starts_at_0x24(self):
        zx = Next(boot='bare')                          # before any nr_read moves it
        self.assertEqual(zx.io_in(0x243B), 0x24, 'zxnext:4537 nr_register <= X"24"')

    def test_registers_read_their_power_on_values(self):
        self.assertEqual(mismatches(Next(boot='bare'), ref.POWER_ON), [])

    def test_nr05_once_the_first_frame_ends(self):
        zx = bare()
        zx.run_frames(1)
        self.assertEqual(zx.nr_read(0x05), ref.NR05_AFTER_FIRST_FRAME,
                         'zxnext:1100-1101, 1295-1296; copies at the frame sync 6604-6611')

    def test_nr81_stored_bits(self):
        zx = Next(boot='bare')
        self.assertEqual(zx.nr_read(0x81) & ref.NR81_STORED_MASK, 0,
                         'zxnext:1215-1218 (b7 is the ROMCS pin, zxnext:6032)')
        zx.nr_write(0x81, 0x73)                         # speed forced to 00 (zxnext:5433)
        self.assertEqual(zx.nr_read(0x81) & ref.NR81_STORED_MASK, 0x70, 'zxnext:5427-5433')
        zx.reset(hard=True)
        self.assertEqual(zx.nr_read(0x81) & ref.NR81_STORED_MASK, 0, 'declared values')

    def test_unassigned_and_write_only_registers_read_zero(self):
        zx = Next(boot='bare')
        self.assertEqual(zx.nr_read(0x00), 0x0A, 'a live machine answers NR 0x00')
        bad = [f'NR {r:#04x} reads {zx.nr_read(r):#04x}' for r in ref.READS_ZERO
               if zx.nr_read(r) != 0]
        self.assertEqual(bad, [], 'zxnext:6193-6194 "when others => 0"')

    def test_read_only_registers_ignore_writes(self):
        zx = Next(boot='bare')
        for reg in (0x00, 0x01, 0x0E, 0x0F):
            zx.nr_write(reg, 0x55)
            self.assertEqual(zx.nr_read(reg), ref.POWER_ON[reg][0], f'NR {reg:#04x} is R')

    def test_issue_2_board(self):
        self.assertEqual(Next(boot='bare').nr_read(0x0F), 0x02, 'issue 4 by default')
        self.assertEqual(Next(boot='bare', issue=2).nr_read(0x0F), 0x00,
                         'top2 g_board_issue; §3.2, §9.1 7')


def scribbled():
    """A bare machine with every SCRIBBLE register written and settled."""
    zx = bare()
    # NR 0x8F first: writing it rewrites MMU0/1 and MMU6/7 through the paging
    # logic a cycle later (nr_8f_we_dly -> port_memory_change_dly, zxnext:3753),
    # which would undo the MMU scribbles if it came after them.
    order = [0x8F] + [r for r in ref.SCRIBBLE if r != 0x8F]
    for reg in order:
        zx.nr_write(reg, ref.SCRIBBLE[reg][0])
    zx.run_frames(ref.SETTLE_FRAMES)
    return zx


@needs_next
class Writes(NextCase):

    def test_writes_read_back(self):
        zx = scribbled()
        want = {r: (rb, why) for r, (w, rb, after, why) in ref.SCRIBBLE.items()}
        self.assertEqual(mismatches(zx, want), [])

    def test_speed_programmed_at_once_effective_between_bus_cycles(self):
        zx = bare()
        zx.nr_write(0x07, 0x02)
        self.assertEqual(zx.nr_read(0x07) & 0x03, 0x02, 'programmed, zxnext:5696')
        zx.run_ticks(1000)
        self.assertEqual(zx.nr_read(0x07), 0x22, 'effective in b5:4, zxnext:5703-5735, 5809')
        self.assertEqual(zx.speed, 2)

    def test_selection_port_reads_back(self):
        zx = Next(boot='bare')
        zx.io_out(0x243B, 0x7F)
        self.assertEqual(zx.io_in(0x243B), 0x7F, 'zxnext:4539-4544')
        self.assertEqual(zx.io_in(0x253B), 0xFF, 'NR 0x7F through port 0x253B')


@needs_next
class SoftReset(NextCase):
    """§4.2: a soft reset runs the reset branches only; state without one keeps."""

    def soft(self, zx):
        zx.reset(hard=False)
        park(zx)
        zx.run_frames(ref.SETTLE_FRAMES)                # NR 0x08 b6 reads a copy (zxnext:5729)
        return zx

    def test_registers_after_a_soft_reset(self):
        zx = self.soft(scribbled())
        want = {r: (rb if after == 'same' else after, why)
                for r, (w, rb, after, why) in ref.SCRIBBLE.items()}
        self.assertEqual(mismatches(zx, want), [])

    def test_reset_type_reads_hard_then_soft(self):
        zx = Next(boot='bare')
        seen = [zx.nr_read(0x02) & 3]
        for _ in range(3):
            zx.reset(hard=False)
            seen.append(zx.nr_read(0x02) & 3)
        self.assertEqual(seen, ref.RESET_TYPE_READS, 'zxnext:1691-1698')
        zx.reset(hard=True)
        self.assertEqual(zx.nr_read(0x02) & 3, 0b00, 'a hard reset reloads: "100" again')

    def test_internal_port_enables_rule(self):
        zx = Next(boot='bare')
        for r in (0x82, 0x83, 0x84):
            zx.nr_write(r, 0x00)
        zx.nr_write(0x85, 0x80)                         # b7 = 1: re-enable on soft reset
        zx.reset(hard=False)
        self.assertEqual([zx.nr_read(r) for r in (0x82, 0x83, 0x84, 0x85)],
                         [0xFF, 0xFF, 0xFF, 0x8F], 'zxnext:4991-4998')
        zx.nr_write(0x82, 0x12)
        zx.nr_write(0x85, 0x05)                         # b7 = 0: keep them
        zx.reset(hard=False)
        self.assertEqual([zx.nr_read(0x82), zx.nr_read(0x85)], [0x12, 0x05],
                         'zxnext:4991 only if NR 0x85 b7 = 1')

    def test_bus_port_enables_rule_is_the_opposite_sense(self):
        zx = Next(boot='bare')
        zx.nr_write(0x86, 0x34)                         # NR 0x89 = 0x8F: b7 = 1, keep
        zx.reset(hard=False)
        self.assertEqual(zx.nr_read(0x86), 0x34, 'zxnext:5000 only if NR 0x89 b7 = 0')
        zx.nr_write(0x89, 0x03)                         # b7 = 0: re-enable
        zx.reset(hard=False)
        self.assertEqual([zx.nr_read(r) for r in (0x86, 0x87, 0x88, 0x89)],
                         [0xFF, 0xFF, 0xFF, 0x0F], 'zxnext:5000-5007; nr:792-793')

    def test_selection_port_resets_to_0x24(self):
        zx = Next(boot='bare')
        zx.io_out(0x243B, 0x7F)
        zx.reset(hard=False)
        self.assertEqual(zx.io_in(0x243B), 0x24, 'zxnext:4536-4537')

    def test_speed_resets(self):
        zx = bare()
        zx.nr_write(0x07, 0x03)
        zx.run_ticks(1000)
        self.assertEqual(zx.nr_read(0x07), 0x33, 'at 28 MHz before the reset')
        zx.reset(hard=False)
        zx.run_ticks(1000)
        self.assertEqual(zx.nr_read(0x07), 0x00, 'zxnext:5694, 5708')


@needs_next
class HardReset(NextCase):

    def test_hard_reset_restores_power_on(self):
        zx = scribbled()
        zx.reset(hard=True)
        self.assertEqual(mismatches(zx, ref.POWER_ON), [])
        self.assertEqual(zx.nr_read(0x7F), 0xFF, 'zxnext:1210: hard reset only')
        park(zx)
        zx.run_frames(1)
        self.assertEqual(zx.nr_read(0x05), ref.NR05_AFTER_FIRST_FRAME)


@needs_next
class MachineType(NextCase):
    """NR 0x03 (§4.3; zxnext:5060-5090, read 5800-5801)."""

    def test_timing_field_needs_bit_7(self):
        zx = Next(boot='bare')
        zx.nr_write(0x03, 0x10)                         # b7 = 0, type 000: config mode kept
        self.assertEqual(zx.nr_read(0x03), 0x33, 'zxnext:5063')

    def test_timing_field_values(self):
        for field in range(8):
            zx = Next(boot='bare')
            zx.nr_write(0x03, 0x80 | field << 4)        # type 000 keeps config mode and type
            want = ref.nr03_read(ref.nr03_timing_written(field), 0, 0b011)
            self.assertEqual(zx.nr_read(0x03), want,
                             f'timing field {field:03b}: zxnext:5064-5071')

    def test_user_lock(self):
        zx = Next(boot='bare')
        zx.nr_write(0x03, 0x08)                         # toggle the lock on
        self.assertEqual(zx.nr_read(0x03), 0x3B, 'zxnext:5074')
        zx.nr_write(0x03, 0x90)                         # timing 001: refused while locked
        self.assertEqual(zx.nr_read(0x03), 0x3B, 'zxnext:5063 lock = 0 needed')
        zx.nr_write(0x03, 0x08)                         # off again
        zx.nr_write(0x03, 0x98)                         # b7 with b3: lock toggles, no timing
        self.assertEqual(zx.nr_read(0x03), 0x3B, 'zxnext:5063 b3 = 0 needed')

    def test_type_only_in_config_mode(self):
        zx = Next(boot='bare')
        zx.nr_write(0x03, 0x01)                         # 48K: accepted, leaves config mode
        self.assertEqual(zx.nr_read(0x03), 0x31, 'zxnext:5076-5090')
        zx.nr_write(0x03, 0x02)                         # not in config mode: ignored
        self.assertEqual(zx.nr_read(0x03), 0x31, 'zxnext:5076 config mode only')
        zx.nr_write(0x03, 0x07)                         # 111 enters config mode, type kept
        self.assertEqual(zx.nr_read(0x03), 0x31, 'zxnext:5086-5087; 111 sets no type')
        zx.nr_write(0x03, 0x02)                         # now accepted
        self.assertEqual(zx.nr_read(0x03), 0x32)

    def test_types_5_and_6_leave_config_mode_unchanged(self):
        zx = Next(boot='bare')
        zx.nr_write(0x03, 0x05)                         # no such type: kept, but config left
        self.assertEqual(zx.nr_read(0x03), 0x33, 'zxnext:5082 others => null')
        zx.nr_write(0x03, 0x01)                         # refused: config mode was left
        self.assertEqual(zx.nr_read(0x03), 0x33, 'zxnext:5088-5089')

    def test_any_write_turns_the_boot_rom_off(self):
        zx = Next(boot='bare')
        self.assertEqual(zx.peek(0x0000), 0xFF, 'bare boot-ROM area reads 0xFF (§9.1 2)')
        zx.sram[0x0000] = 0x5A
        zx.sram[0x8000] = 0xA5
        zx.nr_write(0x03, 0x00)                         # boot ROM off, config mode kept
        self.assertEqual(zx.peek(0x0000), 0x5A, 'NR 0x04 page 0 (§3.4, zxnext:3003-3009)')
        zx.nr_write(0x04, 0x02)
        self.assertEqual(zx.peek(0x0000), 0xA5, 'NR 0x04 = 2: SRAM 0x8000')
        self.assertEqual(zx.peek(0x2000), zx.sram[0xA000], 'one 16K page over slots 0-1')

    def test_config_mode_writes_land_in_nr04_page(self):
        zx = Next(boot='bare')                          # boot ROM on: reads only (§3.10)
        zx.nr_write(0x04, 0x03)
        zx.poke(0x0123, 0xA5)
        self.assertEqual(zx.sram[3 * 0x4000 + 0x123], 0xA5, 'zxnext:3003-3009')

    def test_leaving_config_mode_shows_the_rom(self):
        zx = Next(boot='bare')
        zx.sram[0x0000], zx.sram[0x8000] = 0x11, 0x22
        zx.nr_write(0x04, 0x02)
        zx.nr_write(0x03, 0x00)
        self.assertEqual(zx.peek(0x0000), 0x22, 'config mode: NR 0x04 page')
        zx.nr_write(0x03, 0x01)                         # 48K type: ROM 0 (§3.5)
        self.assertEqual(zx.peek(0x0000), 0x11, 'zxnext:2938-2967: ROM 0 at SRAM 0')

    def test_bare_with_a_timing_starts_in_it(self):
        for timing, code in ref.TIMING_CODE.items():
            zx = Next(boot='bare', timing=timing)
            self.assertEqual((zx.nr_read(0x03) >> 4) & 7, code, f'{timing}: §9.1 1')
            self.assertEqual(zx.nr_read(0x03) & 7, 0b011, 'type stays +3 in bare')


if __name__ == '__main__':
    unittest.main()
