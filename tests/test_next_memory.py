"""The Next's memory: MMU slots, block RAM, the paging ports, Layer 2's map,
divMMC, the ROMs and the alternate ROM (the foil, Loam Fern).

Written from the survey's §3 and the core 3.02.02 VHDL (zxnext:2919-3115,
3597-3760, 4546-4641), through DESIGN.md §9/§9.1 only. Expectations come from
nextref.py's memory models, which test_next_ref.py checks against the source
and, for all-RAM mode, against the +3's own table.

Port writes change the MMU one 28 MHz cycle later (zxnext:3744-3759), so each
port write here is followed by a few ticks with the CPU parked in RAM.
"""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare, park  # noqa: E402


def out(zx, port, v):
    zx.io_out(port, v)
    zx.run_ticks(8)                                     # port_memory_change_dly (zxnext:3755)


def mmu(zx):
    return [zx.nr_read(0x50 + i) for i in range(8)]


def leave_config(zx, mtype=0b001):
    """Leave config mode as the firmware does (§7.2 6): type 1-4 (zxnext:5086-5090)."""
    zx.nr_write(0x03, mtype)
    zx.run_ticks(8)


def digest(zx):
    return hashlib.sha256(bytes(zx.sram) + bytes(zx.bram5) + bytes(zx.bram7)).hexdigest()


@needs_next
class Slots(NextCase):
    """§3.1, §3.3, §3.11."""

    def test_power_on_slot_pages(self):
        zx = Next(boot='bare')
        self.assertEqual([zx.slot_page(i) for i in range(2, 8)],
                         [0x0A, 0x0B, 0x04, 0x05, 0x00, 0x01], 'zxnext:4552-4559')
        self.assertEqual(zx.slot_page(0), 'boot', 'boot ROM reads (zxnext:1815, §3.10)')
        self.assertEqual(zx.slot_page(0, write=True), ('config', 0),
                         'config-mode writes go to NR 0x04 page (zxnext:3003-3009)')

    def test_pages_land_where_they_should_in_sram(self):
        zx = bare()
        for slot, page in [(2, 0x00), (3, 0x10), (5, 0x5F), (6, 0x60), (7, 0xDF)]:
            zx.nr_write(0x50 + slot, page)
            a = slot * 0x2000 + 0x123
            zx.poke(a, slot ^ 0x5A)
            self.assertEqual(zx.sram[ref.sram_of_page(page) + 0x123], slot ^ 0x5A,
                             f'slot {slot}, page {page:#04x}: zxnext:2921')
            self.assertEqual(zx.peek(a), slot ^ 0x5A)
            self.assertEqual(zx.slot_page(slot), page)

    def test_the_last_byte_of_2mb(self):
        zx = bare()
        zx.nr_write(0x57, 0xDF)
        zx.poke(0xFFFF, 0xA7)
        self.assertEqual(zx.sram[0x1FFFFF], 0xA7, 'page 0xDF is the last 8K (§3.1)')

    def test_bank_5_and_first_half_of_bank_7_live_in_block_ram(self):
        zx = bare()
        for page, (arr, off) in ref.BLOCK_RAM_PAGES.items():
            zx.nr_write(0x52, page)
            zx.poke(0x4010, page)
            self.assertEqual(getattr(zx, arr)[off + 0x10], page,
                             f'page {page:#04x} -> {arr} (zxnext:2919-2920, 3020)')
            self.assertEqual(zx.sram[ref.sram_of_page(page) + 0x10], 0,
                             f'page {page:#04x}: SRAM never written through the MMU (§3.11)')
        zx.nr_write(0x52, 0x0F)                         # bank 7's second half is SRAM
        zx.poke(0x4010, 0x0F)
        self.assertEqual(zx.sram[ref.sram_of_page(0x0F) + 0x10], 0x0F, '§3.11: only 8K of bank 7')

    def test_bank_5_reads_come_from_block_ram(self):
        zx = bare()                                     # MMU2 = 0x0A
        zx.sram[ref.sram_of_page(0x0A)] = 0x99
        zx.bram5[0] = 0x11
        self.assertEqual(zx.peek(0x4000), 0x11, 'zxnext:1819-1822')

    def test_pages_e0_up_address_nothing_in_slots_2_to_7(self):
        zx = bare()
        zx.nr_write(0x57, 0xE0)
        before = digest(zx)
        zx.poke(0xE000, 0x5A)
        zx.poke(0xFFFF, 0x5A)
        self.assertEqual(digest(zx), before, 'writes lost (zxnext:3019-3020, 3113)')
        self.assertIsNone(zx.slot_page(7))
        self.assertIsNone(zx.slot_page(7, write=True))

    def test_pages_e0_up_show_the_rom_in_slots_0_and_1(self):
        zx = bare()
        zx.sram[ref.ROM_SRAM[0] + 5] = 0x3C
        leave_config(zx)                                # 48K type: ROM 0
        for v in (0xE0, 0xF0, 0xFE, 0xFF):
            zx.nr_write(0x50, v)
            self.assertEqual(zx.peek(0x0005), 0x3C, f'MMU0 = {v:#04x}: ROM (§9 D-9, zxnext:2996)')
            self.assertEqual(zx.slot_page(0), ('rom', 0))

    def test_an_mmu_page_in_slot_0_beats_the_rom_and_is_writable(self):
        zx = bare()
        leave_config(zx)
        zx.nr_write(0x50, 0x20)
        zx.poke(0x0010, 0x77)
        self.assertEqual(zx.sram[ref.sram_of_page(0x20) + 0x10], 0x77, 'zxnext:2998-3002')
        self.assertEqual(zx.peek(0x0010), 0x77)

    def test_an_mmu_page_beats_config_mode_too(self):
        zx = bare()
        zx.nr_write(0x03, 0x00)                         # boot ROM off, config mode kept
        zx.nr_write(0x50, 0x21)
        zx.poke(0x0010, 0x66)
        self.assertEqual(zx.sram[ref.sram_of_page(0x21) + 0x10], 0x66,
                         'MMU page < 0xE0 comes before config mode (zxnext:2997-3009)')

    def test_the_rom_is_read_only_unless_forced(self):
        zx = bare()
        leave_config(zx)
        zx.poke(0x0005, 0x77)
        self.assertEqual(zx.sram[5], 0, 'ROM is read-only (zxnext:3015, 3113)')
        zx.poke(0x0005, 0x77, force=True)
        self.assertEqual(zx.sram[5], 0x77, 'force writes the ROM (DESIGN.md §3)')


@needs_next
class PagingPorts(NextCase):
    """§3.6: the legacy ports are front ends to the MMU (zxnext:4561-4625)."""

    def test_7ffd_pages_a_bank_into_slots_6_and_7(self):
        zx = bare()
        out(zx, ref.P7FFD, 3)
        self.assertEqual(mmu(zx)[6:], [0x06, 0x07], 'zxnext:4617-4618')
        self.assertEqual(zx.slot_page(6), 0x06)

    def test_7ffd_puts_the_rom_back_in_slots_0_and_1(self):
        zx = bare()
        zx.nr_write(0x50, 0x10)
        zx.nr_write(0x51, 0x11)
        out(zx, ref.P7FFD, 0)
        self.assertEqual(mmu(zx)[:2], [0xFF, 0xFF], 'zxnext:4582-4584; ports:118')

    def test_7ffd_leaves_slots_2_to_5_alone(self):
        zx = bare()                                     # slot 4 keeps the parked loop
        for i, p in [(2, 0x20), (3, 0x21), (5, 0x23)]:
            zx.nr_write(0x50 + i, p)
        out(zx, ref.P7FFD, 1)
        self.assertEqual(mmu(zx)[2:6], [0x20, 0x21, 0x04, 0x23],
                         'restored only on leaving all-RAM mode (zxnext:4588-4605)')

    def test_all_ram_configurations(self):
        for cfg in range(4):
            zx = bare()
            out(zx, ref.P1FFD, 1 | cfg << 1)
            self.assertEqual(mmu(zx), ref.all_ram_mmu(cfg), f'configuration {cfg:02b}: '
                             f'zxnext:4565-4572 (ports.txt:150-154 has a typo for 10)')

    def test_leaving_all_ram_mode_restores_slots_2_to_5(self):
        zx = bare()
        out(zx, ref.P1FFD, 0x07)                        # all-RAM, configuration 11
        out(zx, ref.P7FFD, 0x02)
        out(zx, ref.P1FFD, 0x00)                        # leave
        self.assertEqual(mmu(zx), [0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x04, 0x05],
                         'zxnext:4588-4618; ports.txt:155-156')

    def test_the_lock(self):
        zx = bare()
        out(zx, ref.P7FFD, 0x20 | 2)                    # bank 2, locked
        self.assertEqual(mmu(zx)[6], 0x04)
        self.assertEqual(zx.nr_read(0x08) & 0x80, 0, 'NR 0x08 b7 reads "unlocked" (zxnext:5813)')
        out(zx, ref.P7FFD, 5)
        out(zx, ref.PDFFD, 1)
        out(zx, ref.P1FFD, 1)
        self.assertEqual(mmu(zx)[6], 0x04, 'locked: 7FFD, DFFD, 1FFD ignored (zxnext:3608, '
                                           '3649, 3676)')
        self.assertEqual(mmu(zx)[0], 0xFF, '1FFD all-RAM refused while locked')
        zx.nr_write(0x8E, 0x08 | 6 << 4)                # NR 0x8E ignores the lock
        zx.run_ticks(8)
        self.assertEqual(mmu(zx)[6], 0x0C, 'zxnext:3620')
        zx.nr_write(0x08, 0x80)                         # unlock
        out(zx, ref.P7FFD, 1)
        self.assertEqual(mmu(zx)[6], 0x02, 'zxnext:3612-3614')

    def test_dffd_extends_the_bank(self):
        zx = bare()
        out(zx, ref.PDFFD, 0x05)
        out(zx, ref.P7FFD, 0x03)
        bank = 0x05 << 3 | 0x03
        self.assertEqual(mmu(zx)[6:], [bank * 2, bank * 2 + 1], 'zxnext:3704-3707')
        zx.poke(0xC000, 0xB5)
        self.assertEqual(zx.sram[ref.sram_of_page(bank * 2)], 0xB5)

    def test_eff7_puts_bank_0_over_the_rom(self):
        zx = bare()
        out(zx, ref.PEFF7, 0x08)
        self.assertEqual(mmu(zx)[:2], [0x00, 0x01], 'zxnext:4576-4580')
        out(zx, ref.PEFF7, 0x00)
        self.assertEqual(mmu(zx)[:2], [0xFF, 0xFF])

    def test_nr_8e(self):
        zx = bare()
        zx.nr_write(0x8E, 0x58)                         # bank 5, normal mode, ROM 0
        zx.run_ticks(8)
        self.assertEqual(mmu(zx)[6:], [0x0A, 0x0B], 'zxnext:3620-3628')
        self.assertEqual(zx.nr_read(0x8E), 0x58, 'read layout zxnext:6065-6066')
        zx.nr_write(0x56, 0x30)
        zx.nr_write(0x8E, 0x01)                         # b3 = 0: bank and MMU6/7 left alone
        zx.run_ticks(8)
        self.assertEqual(mmu(zx)[6], 0x30, 'port_memory_ram_change_dly = 0 (zxnext:3756)')
        self.assertEqual(zx.nr_read(0x8E), 0x59, 'ROM bit set from b0 (zxnext:3626-3627)')
        zx.nr_write(0x8E, 0x04 | 0x02)                  # b2 = 1: all-RAM, configuration 10
        zx.run_ticks(8)
        self.assertEqual(mmu(zx), ref.all_ram_mmu(0b10), 'zxnext:3684-3692')

    def test_3ffd_is_7ffd_except_under_p3_timing(self):
        zx = bare(timing='128k')
        out(zx, 0x3FFD, 3)
        self.assertEqual(mmu(zx)[6], 0x06, 'A14 not decoded under 128K timing (zxnext:2552)')
        zx = bare()                                     # +3 timing
        out(zx, 0x3FFD, 3)
        self.assertEqual(mmu(zx)[6], 0x00, 'under +3 timing 0x3FFD is not 7FFD')

    def test_1ffd_beats_7ffd_unless_disabled(self):
        zx = bare(timing='128k')
        out(zx, ref.P1FFD, 0x02)                        # 1FFD: bit 0 clear, no all-RAM
        self.assertEqual(mmu(zx)[6], 0x00, '1FFD decodes first (zxnext:2552 port_1ffd = 0)')
        zx.nr_write(0x82, 0xF7)                         # 1FFD's enable off (b3)
        out(zx, ref.P1FFD, 0x02)
        self.assertEqual(mmu(zx)[6], 0x04, 'then 0x1FFD reaches 7FFD, as on a 128 (§5.2)')

    def test_a_disabled_7ffd_pages_nothing(self):
        zx = bare()
        out(zx, ref.P7FFD, 3)
        self.assertEqual(mmu(zx)[6], 0x06, 'enabled, it pages')
        zx.nr_write(0x82, 0xFD)                         # 7FFD's enable off (b1)
        out(zx, ref.P7FFD, 5)
        self.assertEqual(mmu(zx)[6], 0x06, 'disabled, it does not (zxnext:2358, 2552)')


@needs_next
class LayerTwoMap(NextCase):
    """§3.7: port 0x123B maps Layer 2's SRAM over the bottom 16K or 48K."""

    def setUp(self):
        self.zx = bare()
        self.zx.nr_write(0x03, 0x00)                    # boot ROM off (it would win reads)

    def test_write_map_segment_0(self):
        zx = self.zx
        out(zx, ref.P123B, 0x01)
        zx.poke(0x0123, 0x5A)
        page = ref.layer2_page(0x08, 0, 0, 0x0123)
        self.assertEqual(zx.sram[ref.sram_of_page(page) + 0x123], 0x5A, 'zxnext:2924-2927, 3059')
        self.assertEqual(zx.slot_page(0, write=True), ('l2', page))
        self.assertNotEqual(zx.slot_page(0), ('l2', page), 'read map not enabled')

    def test_each_segment(self):
        zx = self.zx
        for seg in range(3):
            out(zx, ref.P123B, seg << 6 | 0x01)
            zx.poke(0x2000 + seg, 0x40 + seg)
            page = ref.layer2_page(0x08, seg, 0, 0x2000)
            self.assertEqual(zx.sram[ref.sram_of_page(page) + seg], 0x40 + seg, f'segment {seg}')

    def test_segment_mode_3_covers_the_bottom_48k(self):
        zx = self.zx
        out(zx, ref.P123B, 0xC1)
        zx.poke(0x8001, 0x81)
        self.assertEqual(zx.sram[ref.sram_of_page(ref.layer2_page(8, 3, 0, 0x8001)) + 1], 0x81,
                         'zxnext:3024')
        zx.poke(0xC001, 0xC1)
        self.assertEqual(zx.sram[ref.sram_of_page(0x00) + 1], 0xC1, '0xC000 up stays MMU')

    def test_read_map(self):
        zx = self.zx
        page = ref.layer2_page(0x08, 0, 0, 0)
        zx.sram[ref.sram_of_page(page)] = 0xE7
        out(zx, ref.P123B, 0x04)
        self.assertEqual(zx.peek(0x0000), 0xE7, 'zxnext:3035')
        self.assertEqual(zx.slot_page(0), ('l2', page))

    def test_shadow_bank_and_offset(self):
        zx = self.zx
        out(zx, ref.P123B, 0x10 | 0x02)                 # b4: store offset 2
        out(zx, ref.P123B, 0x08 | 0x01)                 # shadow (NR 0x13 = 0x0B), write map
        zx.poke(0x0004, 0x44)
        page = ref.layer2_page(0x0B, 0, 2, 0x0004)
        self.assertEqual(zx.sram[ref.sram_of_page(page) + 4], 0x44, 'zxnext:3858-3863, 2925')

    def test_layer2_writes_to_bank_5_go_to_sram_not_block_ram(self):
        zx = self.zx
        zx.nr_write(0x12, 0x05)
        out(zx, ref.P123B, 0x01)
        zx.poke(0x0010, 0x55)
        self.assertEqual(zx.sram[ref.sram_of_page(0x0A) + 0x10], 0x55, 'zxnext:3062 bank5 = 0')
        self.assertEqual(zx.bram5[0x10], 0x00, 'the ULA never sees it (§9 D-11)')
        zx.poke(0x4011, 0x66)                           # through the MMU instead
        self.assertEqual(zx.bram5[0x11], 0x66)
        self.assertEqual(zx.sram[ref.sram_of_page(0x0A) + 0x11], 0x00, 'Layer 2 never sees it')

    def test_divmmc_comes_before_layer_2(self):
        zx = self.zx
        out(zx, ref.P123B, 0x01)
        out(zx, ref.PE3, 0x80 | 0x02)                   # conmem, bank 2
        zx.poke(0x2003, 0x23)
        self.assertEqual(zx.sram[ref.divmmc_ram(2) + 3], 0x23, 'zxnext:3043-3057 order')


@needs_next
class DivMMC(NextCase):
    """§3.8 (divmmc:83-101; zxnext:4114-4129)."""

    def setUp(self):
        self.zx = bare()
        leave_config(self.zx)                           # 48K type, the ROM in slots 0-1

    def test_conmem_maps_the_rom_and_a_bank(self):
        zx = self.zx
        zx.sram[ref.DIVMMC_ROM + 1] = 0xD1
        out(zx, ref.PE3, 0x80 | 0x02)
        self.assertEqual(zx.peek(0x0001), 0xD1, 'divmmc:93; zxnext:3043')
        self.assertEqual(zx.slot_page(0), 'divmmc-rom')
        zx.poke(0x2010, 0x22)
        self.assertEqual(zx.sram[ref.divmmc_ram(2) + 0x10], 0x22, 'zxnext:3051')
        self.assertEqual(zx.slot_page(1), ('divmmc', 2))
        zx.poke(0x0001, 0x00)
        self.assertEqual(zx.sram[ref.DIVMMC_ROM + 1], 0xD1, 'divMMC ROM is read-only (divmmc:99)')

    def test_mapram_and_bank_3(self):
        zx = self.zx
        out(zx, ref.PE3, 0xC0 | 0x03)                   # conmem + mapram, bank 3
        zx.sram[ref.divmmc_ram(3) + 7] = 0x37
        self.assertEqual(zx.peek(0x0007), 0x37, 'bank 3 replaces the ROM (divmmc:91-95)')
        zx.poke(0x2007, 0x99)                           # the same byte as 0x0007 (bank 3)
        self.assertEqual(zx.sram[ref.divmmc_ram(3) + 7], 0x37,
                         'bank 3 read-only with mapram: the 99h refused (divmmc:99)')
        out(zx, ref.PE3, 0xC0 | 0x05)
        zx.poke(0x2007, 0x99)
        self.assertEqual(zx.sram[ref.divmmc_ram(5) + 7], 0x99, 'other banks writable')

    def test_mapram_is_sticky_until_nr09(self):
        zx = self.zx
        out(zx, ref.PE3, 0x40)
        out(zx, ref.PE3, 0x00)
        self.assertEqual(zx.io_in(ref.PE3) & 0x40, 0x40, 'zxnext:4123 OR in')
        zx.nr_write(0x09, 0x08)
        zx.run_ticks(8)
        self.assertEqual(zx.io_in(ref.PE3) & 0x40, 0x00, 'zxnext:4125-4126')

    def test_disabling_the_port_unmaps_divmmc(self):
        zx = self.zx
        zx.sram[ref.ROM_SRAM[0] + 1], zx.sram[ref.DIVMMC_ROM + 1] = 0x01, 0xD1
        out(zx, ref.PE3, 0x80)
        self.assertEqual(zx.peek(0x0001), 0xD1)
        zx.nr_write(0x83, 0xFE)                         # b0: port E3 and divMMC off
        zx.run_ticks(8)
        self.assertEqual(zx.peek(0x0001), 0x01, 'i_en => port_divmmc_io_en (zxnext:4088)')


@needs_next
class Roms(NextCase):
    """§3.5: the ROM by machine type, and NR 0x8C's alternate ROM."""

    def marked(self):
        zx = bare()
        for n, a in enumerate(ref.ROM_SRAM):
            zx.sram[a] = 0xA0 + n
        zx.sram[ref.ALTROM_128], zx.sram[ref.ALTROM_48] = 0xB0, 0xB1
        return zx

    def test_48k_type_shows_rom_0(self):
        zx = self.marked()
        leave_config(zx, 0b001)
        self.assertEqual(zx.peek(0), 0xA0, 'zxnext:2940-2943')

    def test_128k_type_rom_by_7ffd_bit_4(self):
        zx = self.marked()
        leave_config(zx, 0b010)
        for v, rom in [(0x10, 1), (0x00, 0)]:
            out(zx, ref.P7FFD, v)
            self.assertEqual(zx.peek(0), 0xA0 + rom, f'7FFD {v:#04x}: zxnext:2959-2965')

    def test_p3_type_four_roms(self):
        zx = self.marked()
        leave_config(zx, 0b011)
        for rom in range(4):
            out(zx, ref.P1FFD, (rom >> 1) << 2)
            out(zx, ref.P7FFD, (rom & 1) << 4)
            self.assertEqual(zx.peek(0), 0xA0 + ref.rom_for(0b011, (rom & 1) << 4,
                                                             (rom >> 1) << 2),
                             f'ROM {rom}: zxnext:2944-2953')

    def test_rom_locks(self):
        zx = self.marked()
        leave_config(zx, 0b010)
        zx.nr_write(0x8C, 0x20)                         # lock ROM1 in place
        self.assertEqual(zx.peek(0), 0xA0 + ref.rom_for(0b010, 0, 0, 0x20), 'zxnext:2955-2958')

    def test_alternate_rom_replaces_reads(self):
        zx = self.marked()
        leave_config(zx, 0b001)
        zx.nr_write(0x8C, 0x80)
        self.assertEqual(zx.peek(0), zx.sram[ref.altrom_base(0b001)], 'zxnext:3036, 3075-3082')
        zx.poke(0x0000, 0x00)
        self.assertEqual(zx.sram[ref.ALTROM_48], 0xB1, 'read-only in read mode')

    def test_alternate_rom_for_the_128k_rom(self):
        zx = self.marked()
        leave_config(zx, 0b010)                         # 7FFD b4 = 0: ROM 0, the 128K editor
        zx.nr_write(0x8C, 0x80)
        self.assertEqual(zx.peek(0), 0xB0, 'sram_alt_128_n = 7FFD b4 = 0 (zxnext:2962)')

    def test_alternate_rom_write_mode(self):
        zx = self.marked()
        leave_config(zx, 0b001)
        zx.nr_write(0x8C, 0xC0)
        self.assertEqual(zx.peek(0), 0xA0, 'reads still see the ROM (zxnext:3036)')
        zx.poke(0x0010, 0x5C)
        self.assertEqual(zx.sram[ref.ALTROM_48 + 0x10], 0x5C, 'writes load the alternate ROM')
        self.assertEqual(zx.slot_page(0, write=True)[0], 'altrom')

    def test_no_alternate_rom_in_config_mode(self):
        zx = self.marked()
        zx.nr_write(0x03, 0x00)                         # boot ROM off, config mode kept
        zx.nr_write(0x8C, 0x80)
        self.assertEqual(zx.peek(0), 0xA0, 'config window, not the alternate ROM '
                                           '(override "110", zxnext:3009)')


if __name__ == '__main__':
    unittest.main()
