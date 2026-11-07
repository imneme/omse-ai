"""The Next's expansion bus (zxnext.vhd; core 3.02.02), through DESIGN.md §9.1
(19) only. Nothing is attached unless a test plugs it in.

From the VHDL: NR 80h b7 bus on, b6 ROMCS replace, b5/b4 disable I/O / memory
cycles, b3:0 copied into b7:4 on any reset (zxnext:2141-2159); NR 81h b6 ULA
override, b5 NMI debounce off, b4 clock enable, speed forced 00 (5429-5433),
b7 the ROMCS pin (6033); NR 86h-89h ANDed into the port enables while the bus is
on (2351-2352); NR 8Ah propagates internal ports (2167-2175). With the bus on
the CPU runs at the bus speed, 3.5 MHz (5705-5727). Written by Loam Fern,
without reading the builder's code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402,F401
from test_next_regs import Next, needs_next, NextCase, bare, park  # noqa: E402
from test_next_timing import launch                      # noqa: E402
from test_next_interrupts import reached                 # noqa: E402

CODE = 0x8100
F48 = 448 * 312 * 8                                     # a 48K frame in t28


def bus_on(zx, nr80=0x80):
    zx.nr_write(0x80, nr80)
    zx.run_ticks(64)                                    # the effective copies wait for an idle edge


def run_code(zx, code, end_offset=None):
    """Load code at CODE (then JR $), park the CPU (a run before may have left it
    at its own JR $; Ratio's catch), launch, run to the JR."""
    park(zx)
    zx.load(CODE, bytes(code) + bytes([0x18, 0xFE]))
    launch(zx, CODE)
    end = CODE + len(code)
    assert zx.run_until_pc(end, max_ticks=10**6), 'never finished'
    return end


def io_cycles(zx):
    return [(k, a, v) for _, k, a, v in zx.bus_events if k in ('ir', 'iw')]


@needs_next
class Registers(NextCase):

    def test_nr80_and_the_reset_copy(self):
        """Any reset copies b3:0 into b7:4 and keeps b3:0 (zxnext:2144-2145)."""
        for written, after in [(0x05, 0x55), (0x08, 0x88), (0xF0, 0x00)]:
            with self.subTest(nr80=f'{written:02X}h'):
                zx = bare()
                zx.nr_write(0x80, written)
                self.assertEqual(zx.nr_read(0x80), written)
                zx.reset()
                zx.run_ticks(2000)
                self.assertEqual(zx.nr_read(0x80), after)

    def test_a_reset_brings_the_bus_up_as_b3_0_said(self):
        """The reset copy (zxnext:2144-2145) isn't only a read-back: with b3 set
        the bus is on after the reset and carries the CPU's cycles. (Mutant
        survivor 1, run 1.)"""
        for nr80, on in [(0x08, True), (0x00, False)]:
            with self.subTest(nr80=f'{nr80:02X}h'):
                zx = bare()
                zx.nr_write(0x80, nr80)
                zx.reset()
                zx.run_ticks(2000)
                park(zx)
                zx.bus_log(True)
                zx.run_ticks(2000)
                self.assertEqual(bool([e for e in zx.bus_events if e[1] == 'mr']), on)

    def test_nr81_keeps_three_bits_and_no_speed(self):
        """b6:4 stored; the speed bits are ignored in 3.02.02 (zxnext:5433); b3:2
        read 0 (6033)."""
        zx = bare()
        zx.nr_write(0x81, 0x73)
        self.assertEqual(zx.nr_read(0x81) & 0x7F, 0x70)

    def test_nr81_b7_is_the_romcs_pin(self):
        """A cartridge drives ROMCS, which zxnext uses active high (2977, 3038), and
        NR 81h b7 reads that pin (6033)."""
        zx = bare()
        zx.bus_rom(bytes(16384))
        zx.run_ticks(64)
        self.assertEqual(zx.nr_read(0x81) & 0x80, 0x80)

    def test_nr81_reads_0_with_nothing_plugged_in(self):
        """Ruling (19) c: /ROMCS has a 680R pull-down on the board (issue 4
        schematic sheet 8, R93; machine/BUS-PINS.md), so with nothing attached
        b7 reads 0, bus on or off: the read isn't gated (zxnext:6033)."""
        zx = bare()
        self.assertEqual(zx.nr_read(0x81), 0x00)
        bus_on(zx)
        zx.nr_write(0x81, 0x70)
        self.assertEqual(zx.nr_read(0x81), 0x70, 'b7 still 0 beside the stored bits')

    def test_nr8a_is_six_bits(self):
        zx = bare()
        zx.nr_write(0x8A, 0xFF)
        self.assertEqual(zx.nr_read(0x8A), 0x3F, 'zxnext:6059-6060')


@needs_next
class NothingAttached(NextCase):

    def test_bus_off_carries_nothing(self):
        zx = bare()
        zx.bus_io({0x00F7: 0x12})
        zx.bus_log(True)
        run_code(zx, [0x3E, 0x5A, 0xD3, 0xF7, 0xDB, 0xF7, 0x32, 0x00, 0x90])
        self.assertEqual(zx.bus_events, [], 'the bus is off')
        self.assertEqual(zx.peek(0x9000), 0xFF, 'an unanswered port reads FFh (zxnext:1835-1837)')

    def test_bus_on_with_nothing_attached_reads_ff(self):
        zx = bare()
        bus_on(zx)
        self.assertEqual(zx.io_in(0x00F7), 0xFF, 'the data bus floats to FFh')


@needs_next
class IOCycles(NextCase):

    def test_io_cycles_reach_the_connector(self):
        """An I/O cycle no internal port answers goes to the bus (zxnext:2179),
        and its read is the device's answer (1832-1833)."""
        zx = bare()
        bus_on(zx)
        zx.bus_io({0x5AF7: 0x12})
        zx.bus_log(True)
        run_code(zx, [0x3E, 0x5A, 0xD3, 0xF7, 0x3E, 0x5A, 0xDB, 0xF7, 0x32, 0x00, 0x90])
        self.assertEqual(io_cycles(zx), [('iw', 0x5AF7, 0x5A), ('ir', 0x5AF7, 0x12)])
        self.assertEqual(zx.peek(0x9000), 0x12)

    def test_internal_ports_stay_inside(self):
        """An internally answered port isn't put on the bus (zxnext:2179) and
        its internal answer wins (1830-1831)."""
        zx = bare()
        bus_on(zx)
        zx.bus_io({0x243B: 0x99})
        zx.bus_log(True)
        run_code(zx, [0x01, 0x3B, 0x24, 0xED, 0x78, 0x32, 0x00, 0x90])   # LD BC,243Bh; IN A,(C)
        self.assertEqual(io_cycles(zx), [])
        self.assertEqual(zx.peek(0x9000), 0x80, 'the register last selected (NR 80h, by bus_on; zxnext:4544)')

    def test_nr8a_propagates_port_fe_writes(self):
        """NR 8Ah b0 shows port FE's cycles on the bus as well (zxnext:2167, 2177-2179)."""
        for nr8a, want in [(0x00, []), (0x01, [('iw', 0x02FE, 0x02)])]:
            with self.subTest(nr8a=nr8a):
                zx = bare()
                zx.nr_write(0x8A, nr8a)
                bus_on(zx)
                zx.bus_log(True)
                run_code(zx, [0x3E, 0x02, 0xD3, 0xFE])
                self.assertEqual(io_cycles(zx), want)

    INTERNAL = {                                        # port family: an address that decodes, zxnext:2542-2649
        'FE': 0x00FE, 'FF': 0x00FF, '7FFD': 0x7FFD, 'DFFD': 0xDFFD, '1FFD': 0x1FFD, 'EFF7': 0xEFF7,
        'E3': 0x00E3, 'E7': 0x00E7, 'EB': 0x00EB, '243B': 0x243B, '253B': 0x253B, '103B': 0x103B,
        '113B': 0x113B, '123B': 0x123B, 'UART Tx': 0x133B, 'UART Rx': 0x143B, 'UART sel': 0x153B,
        'UART frame': 0x163B, 'DMA 6B': 0x006B, 'DMA 0B': 0x000B, 'FFFD': 0xFFFD, 'BFFD': 0xBFFD,
        'FADF': 0xFADF, 'FBDF': 0xFBDF, 'FFDF': 0xFFDF, '57': 0x0057, '5B': 0x005B, '303B': 0x303B,
        'BF3B': 0xBF3B, 'FF3B': 0xFF3B, **{f'CTC {i}': 0x183B + 0x100 * i for i in range(8)}}
    SAFE = {0x00E7: 0xFF, 0x006B: 0x83, 0x000B: 0x83}   # deselect SPI; disable the DMA

    def test_every_internal_port_family_stays_off_the_connector(self):
        """Writes to every family in port_internal_response (zxnext:2654-2657)
        keep IORQ off the bus while NR 8Ah propagates nothing (2179); a port no
        family claims does reach it. (Mutant survivors 2-4, run 1, as a sweep.)"""
        for name, port in list(self.INTERNAL.items()) + [('none', 0x5AF7)]:
            with self.subTest(port=name):
                zx = bare()
                bus_on(zx)
                zx.bus_log(True)
                v = self.SAFE.get(port, 0x00)
                run_code(zx, [0x01, port & 0xFF, port >> 8, 0x3E, v, 0xED, 0x79])   # OUT (C),A
                want = [('iw', port, v)] if name == 'none' else []
                self.assertEqual(io_cycles(zx), want)

    def test_nr8a_b1_propagates_7ffd(self):
        """NR 8Ah b1: a 7FFD write shows on the connector (zxnext:2168, 2177-2179)
        and pages as well. (Mutant survivor 5, run 1.)"""
        zx = bare()
        zx.nr_write(0x8A, 0x02)
        bus_on(zx)
        zx.bus_log(True)
        run_code(zx, [0x01, 0xFD, 0x7F, 0x3E, 0x01, 0xED, 0x79])
        self.assertEqual(io_cycles(zx), [('iw', 0x7FFD, 0x01)])
        self.assertEqual(zx.slot_page(6), 0x02, 'bank 1 at C000h')

    def test_ula_override_frees_ports_00_to_0e(self):
        """NR 81h b6 with FE propagated: an even port with A7:4 = 0 gets only the
        bus's byte (port_fe_override, zxnext:2544, 3416-3419, 3426), FFh with
        nothing attached; other even ports keep the ULA. Needs a key held so the
        ULA's own answer isn't FFh. (Mutant survivor 8, run 1.)"""
        zx = bare()
        zx.nr_write(0x8A, 0x01)
        bus_on(zx)
        zx.press('SPACE')
        zx.run_ticks(5000)
        ula = zx.io_in(0x7FFE)
        self.assertNotEqual(ula, 0xFF, 'SPACE shows in row 7Fh')
        self.assertEqual(zx.io_in(0x7F0E), ula, 'no override: the ULA answers 0Eh too')
        zx.nr_write(0x81, 0x40)
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x7F0E), 0xFF, 'override: the bus only')
        self.assertEqual(zx.io_in(0x7FFE), ula, 'A7:4 = 1111: still the ULA')

    def test_disabling_io_cycles(self):
        """NR 80h b5: I/O cycles don't reach the bus and reads give FFh (2179, 1832)."""
        zx = bare()
        bus_on(zx, 0xA0)
        zx.bus_io({0x5AF7: 0x12})
        zx.bus_log(True)
        run_code(zx, [0x3E, 0x5A, 0xD3, 0xF7, 0x3E, 0x5A, 0xDB, 0xF7, 0x32, 0x00, 0x90])
        self.assertEqual(io_cycles(zx), [])
        self.assertEqual(zx.peek(0x9000), 0xFF)

    def test_iorqula_takes_port_fe_from_the_ula(self):
        """A device asserting IORQULA on port FE answers instead of the ULA
        (bus_iorq_ula, zxnext:2183, 1830-1833)."""
        zx = bare()
        zx.bus_io({0x7FFE: 0x5A})
        self.assertNotEqual(zx.io_in(0x7FFE), 0x5A, 'bus off: the ULA')
        bus_on(zx)
        self.assertEqual(zx.io_in(0x7FFE), 0x5A, 'bus on: the device')

    def test_bus_port_enables_hand_ports_to_the_bus(self):
        """While the bus is on, NR 86h-89h are ANDed into the internal port
        enables (zxnext:2351-2352): NR 87h b2 clear takes the I2C's port 103Bh
        (internal enable 10, 2377) away, so the device answers it."""
        zx = bare()
        zx.bus_io({0x103B: 0x12})
        bus_on(zx)
        self.assertEqual(zx.io_in(0x103B), 0xFF, 'NR 87h as at power-on: the I2C answers')
        zx.nr_write(0x87, 0xFB)
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x103B), 0x12)
        zx.nr_write(0x80, 0x00)
        zx.run_ticks(64)
        self.assertEqual(zx.io_in(0x103B), 0xFF, 'bus off: NR 87h no longer counts')


@needs_next
class MemoryCycles(NextCase):

    def test_memory_cycles_reach_the_connector(self):
        """Memory cycles above 3FFFh always reach the bus (zxnext:2181)."""
        zx = bare()
        bus_on(zx)
        zx.poke(0x9000, 0x77)
        zx.bus_log(True)
        run_code(zx, [0x3A, 0x00, 0x90, 0x32, 0x01, 0x90])   # LD A,(9000h); LD (9001h),A
        ev = [(k, a, v) for _, k, a, v in zx.bus_events if k in ('mr', 'mw') and a in (0x9000, 0x9001)]
        self.assertEqual(ev, [('mr', 0x9000, 0x77), ('mw', 0x9001, 0x77)])
        fetches = {a for _, k, a, _ in zx.bus_events if k == 'mr'}
        self.assertTrue({CODE, CODE + 3} <= fetches, 'opcode fetches too')

    def test_disabling_memory_cycles(self):
        zx = bare()
        bus_on(zx, 0x90)
        zx.bus_log(True)
        run_code(zx, [0x3A, 0x00, 0x90])
        self.assertEqual([e for e in zx.bus_events if e[1] in ('mr', 'mw')], [], 'NR 80h b4 (2181)')
        bus_on(zx, 0x80)
        zx.bus_log(True)
        zx.run_ticks(1000)
        self.assertTrue([e for e in zx.bus_events if e[1] == 'mr'], 'and back on, the parked loop\'s fetches')

    def test_the_rom_area_shows_only_on_the_plain_rom_path(self):
        """0000h-3FFFh reaches the bus only when sram_mem_hide_n is set: the plain
        ROM (override "111", zxnext:3016), not config mode's ROM or MMU RAM
        ("110", 3009), nor divMMC or Layer 2 overlays (3040-3066)."""
        for setup, shown in [('config', False), ('rom', True), ('ram', False)]:
            with self.subTest(setup):
                zx = bare()
                if setup != 'config':
                    zx.nr_write(0x03, 0x01)             # leave config mode: a 48K
                if setup == 'ram':
                    zx.nr_write(0x50, 0x10)
                bus_on(zx)
                zx.bus_log(True)
                run_code(zx, [0x3A, 0x05, 0x00])        # LD A,(0005h)
                seen = any(k == 'mr' and a == 0x0005 for _, k, a, _ in zx.bus_events)
                self.assertEqual(seen, shown)


@needs_next
class Cartridge(NextCase):

    def cart(self, size):
        data = bytes((i * 13 + 7) & 0xFF for i in range(size))
        zx = bare()
        zx.nr_write(0x03, 0x01)                         # the plain ROM path: config mode off
        zx.bus_rom(data)
        return zx, data

    def read(self, zx, addrs):
        code = []
        for i, a in enumerate(addrs):
            code += [0x3A, a & 0xFF, a >> 8, 0x32, i, 0x90]  # LD A,(a); LD (9000h+i),A
        run_code(zx, code)
        return [zx.peek(0x9000 + i) for i in range(len(addrs))]

    def test_a_cartridge_replaces_the_rom_while_the_bus_is_on(self):
        """ROMCS with the bus on and memory enabled: 0000h-3FFFh reads come from the
        bus (sram_romcs, zxnext:2977, 3038, 3066-3073; cpu_di 1812-1813)."""
        zx, data = self.cart(16384)
        addrs = [0x0005, 0x2005, 0x3FFF]
        rom = self.read(zx, addrs)
        bus_on(zx)
        self.assertEqual(self.read(zx, addrs), [data[a] for a in addrs])
        self.assertNotEqual(rom, [data[a] for a in addrs], 'bus off: the Next\'s own ROM')

    def test_an_8k_cartridge_is_mirrored(self):
        zx, data = self.cart(8192)
        bus_on(zx)
        self.assertEqual(self.read(zx, [0x0005, 0x2005]), [data[5], data[5]])

    def test_romcs_replace_reads_divmmc_banks_14_and_15(self):
        """NR 80h b6: the cartridge's area comes from SRAM pages 1Eh/1Fh
        (divMMC banks 14 and 15) by A13, read-only (zxnext:3066-3073, 1810-1813)."""
        zx, data = self.cart(16384)
        zx.sram[0x3C005] = 0xA1
        zx.sram[0x3E005] = 0xB2
        bus_on(zx, 0xC0)
        self.assertEqual(self.read(zx, [0x0005, 0x2005]), [0xA1, 0xB2])
        run_code(zx, [0x3E, 0x55, 0x32, 0x05, 0x00])    # LD A,55h; LD (0005h),A
        self.assertEqual(zx.sram[0x3C005], 0xA1, 'read-only')

    def test_memory_disabled_ignores_romcs(self):
        """sram_pre_romcs_n needs memory cycles enabled (zxnext:2977)."""
        zx, data = self.cart(16384)
        rom = self.read(zx, [0x0005])
        bus_on(zx, 0x90)
        self.assertEqual(self.read(zx, [0x0005]), rom)
        bus_on(zx, 0x80)
        self.assertEqual(self.read(zx, [0x0005]), [data[5]], 'memory cycles on: the cartridge')


@needs_next
class Lines(NextCase):

    def test_the_bus_runs_at_3_5_mhz(self):
        """With the bus on, cpu_speed copies the bus speed, 00 (zxnext:5719-5725)."""
        zx = bare(speed=3)
        self.assertEqual(zx.speed, 3)
        bus_on(zx)
        self.assertEqual(zx.speed, 0)
        self.assertEqual(zx.nr_read(0x07), 0x03, 'NR 07h: effective 00, selection 11 (5810)')
        zx.nr_write(0x80, 0x00)
        zx.run_ticks(64)
        self.assertEqual(zx.speed, 3)

    def test_wait_lengthens_the_next_bus_cycle(self):
        """The bus's WAIT is ORed into the CPU's (zxnext:1798): n waits on the
        next bus cycle, an opcode fetch here, make that NOP 4 + n T-states."""
        zx = bare()
        bus_on(zx)
        zx.load(CODE, bytes([0x00] * 8 + [0x18, 0xFE]))
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(CODE + 2, max_ticks=10**6))
        c0 = zx.cpu_clocks
        zx.bus_wait(3)
        self.assertTrue(zx.run_until_pc(CODE + 3, max_ticks=10**5))
        c1 = zx.cpu_clocks
        self.assertTrue(zx.run_until_pc(CODE + 4, max_ticks=10**5))
        self.assertEqual((c1 - c0, zx.cpu_clocks - c1), (7, 4))

    def im1(self, c4):
        zx = bare()
        zx.nr_write(0xC4, c4)
        zx.load(CODE, bytes([0xF3, 0xED, 0x56, 0xFB, 0x18, 0xFE]))   # DI; IM 1; EI; JR $
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(CODE + 4, max_ticks=10**6))
        return zx

    def test_a_device_interrupt(self):
        """With the bus on and NR C4h b7 (reset 1), the CPU's INT is the bus's INT
        line (zxnext:1799)."""
        zx = self.im1(0x80)                             # the ULA's interrupt off
        zx.bus_lines(int_=True)
        self.assertFalse(zx.run_until_pc(0x0038, max_ticks=2 * F48), 'bus off: not heard')
        bus_on(zx)
        self.assertTrue(reached(zx, 0x0038, 10**5))

    def test_the_next_s_own_interrupt_comes_round_the_bus(self):
        """With the bus on the CPU hears only the bus's INT line, and top4 drives
        that line with the Next's own interrupt (top4:1967, 1988, 752, 1925), so
        the ULA's frame interrupt still arrives with nothing attached."""
        zx = self.im1(0x81)
        bus_on(zx)
        self.assertTrue(reached(zx, 0x0038, 2 * F48))

    def test_int_round_the_bus_is_two_ticks_late(self):
        """Ruling (19) b: the loop is the VHDL's. zxnext drives o_BUS_INT_n with
        its own interrupt (1654); top4 registers the pin drive on CLK_28 (1967,
        1988) and registers the line back on CLK_28 (752, 1925), so the INT the
        CPU samples (int_log, §9.1 (4)) comes two master ticks later, at both
        ends, while the bus is on and NR C4h b7 routes INT through it."""
        def first(nr80, c4=0x81):
            zx = bare(timing='48k')
            zx.nr_write(0xC4, c4)
            zx.nr_write(0x80, nr80)
            zx.run_ticks(2 * F48)
            self.assertTrue(zx.int_log, 'an interrupt in two frames')
            return zx.int_log[0]
        s, e = first(0x00)
        self.assertEqual(first(0x80), (s + 2, e + 2))
        self.assertEqual(first(0x80, c4=0x01), (s, e), 'C4h b7 clear: INT from inside, no loop')

    def nmi_machine(self, nr81=0x00):
        zx = bare()
        zx.nr_write(0x03, 0x01)                         # out of config mode: a 48K, ROM 0
        zx.sram[0x0066], zx.sram[0x0067] = 0xED, 0x45   # RETN in ROM 0 (ROM_SRAM[0])
        zx.nr_write(0x81, nr81)
        bus_on(zx)
        zx.bus_lines(nmi=True)
        self.assertTrue(reached(zx, 0x0066, 10**5), 'the first NMI')
        zx.run_ticks(1000)
        return zx

    def test_a_bus_nmi_release_is_debounced(self):
        """top4:1931-1946: misc/asymmetrical_debounce.vhd, COUNTER_SIZE 3, clocked
        by CLK_28_DEBOUNCE_EN once every 2^18 master ticks (top4:1044-1053): a
        fall passes at once, a release counts only after 8 enables of steady high,
        7 to 8 x 2^18 ticks. Until then the NMI machine holds (zxnext:2093-2097),
        so a new fall isn't a new NMI. (Rustyback's reading; mine of the same lines.)"""
        zx = self.nmi_machine()
        zx.bus_lines(nmi=False)
        zx.run_ticks(1_700_000)                         # under 7 x 2^18, over 4 x 2^18 (mutant 7: half)
        zx.bus_lines(nmi=True)
        self.assertFalse(zx.run_until_pc(0x0066, max_ticks=50_000), 'still held: no second NMI')
        zx.bus_lines(nmi=False)
        zx.run_ticks(2_200_000)                         # over 8 x 2^18
        zx.bus_lines(nmi=True)
        self.assertTrue(reached(zx, 0x0066, 50_000), 'released, then a new fall')

    def test_nr81_b5_bypasses_the_nmi_debounce(self):
        """top4:1946: NR 81h b5 takes the registered pin straight in."""
        zx = self.nmi_machine(nr81=0x20)
        zx.bus_lines(nmi=False)
        zx.run_ticks(10_000)
        zx.bus_lines(nmi=True)
        self.assertTrue(reached(zx, 0x0066, 50_000))

    def test_a_device_nmi(self):
        """nmi_assert_expbus: bus on, memory enabled, the line held (zxnext:2047),
        and not in config mode (2061)."""
        zx = bare()
        zx.nr_write(0x03, 0x01)
        zx.bus_lines(nmi=True)
        self.assertFalse(zx.run_until_pc(0x0066, max_ticks=F48), 'bus off: not heard')
        bus_on(zx)
        self.assertTrue(reached(zx, 0x0066, 10**5))


if __name__ == '__main__':
    unittest.main()
