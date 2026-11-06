"""divMMC's automap on the Next: entry points, instant and delayed, ROM3-only
points, the 1FF8-1FFF exit and RETN (the foil, Loam Fern).

From the survey's §3.8, zxnext.vhd:2805-2867 (the entry decode) and
divmmc.vhd:105-148 (the automap latches), core 3.02.02, through DESIGN.md §9
only. At an entry point the ROM and divMMC hold different opcodes: the ROM
LD A,n with n = 11h, divMMC LD B,n with n = 22h, both followed by JP 9000h.
  no automap  -> A = 11h, B = 99h (all from the ROM)
  delayed     -> A = 22h, B = 99h (the ROM's opcode, divMMC's operand:
                 automap_held takes the latch when MREQ rises, divmmc:136-143)
  instant     -> A = 99h, B = 22h (the fetch itself reads divMMC: automap is
                 combinational on the instant terms, divmmc:147)
At 9000h, A and B are stored at C000h and C001h.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch                      # noqa: E402
from test_next_memory import out, leave_config           # noqa: E402

CODE, STORE = 0x8100, 0x9000
JP_STORE = [0xC3, STORE & 0xFF, STORE >> 8]
NONE, DELAYED, INSTANT = (0x11, 0x99), (0x22, 0x99), (0x99, 0x22)


def machine(mtype=0b001, automap=True, port_7ffd=None):
    zx = bare()
    leave_config(zx, mtype)                             # the ROM in slots 0-1 (§3.4)
    if port_7ffd is not None:
        out(zx, ref.P7FFD, port_7ffd)
    zx.nr_write(0x0A, 0x11 if automap else 0x01)        # b4: automap (divmmc:98-99)
    zx.load(STORE, bytes([0x32, 0x00, 0xC0, 0x78, 0x32, 0x01, 0xC0, 0x18, 0xFE]))
    return zx


def entry(zx, addr, rom_base=ref.ROM_SRAM[0], div=None):
    """ROM: LD A,11h; JP 9000h at addr. divMMC (ROM, or RAM bank 0 at
    0x2000-0x3FFF): LD B,22h; JP 9000h."""
    rom = bytes([0x3E, 0x11] + JP_STORE)
    divb = bytes([0x06, 0x22] + JP_STORE)
    for i, b in enumerate(rom):
        zx.sram[rom_base + addr + i] = b
    base = ref.DIVMMC_ROM + addr if addr < 0x2000 else ref.divmmc_ram(0) + addr - 0x2000
    for i, b in enumerate(div or divb):
        zx.sram[base + i] = b


def go(zx, target, push=None):
    """At CODE: DI; LD A,99h; LD B,99h; [LD HL,push; PUSH HL]; JP target.
    Returns (A, B) as stored at 9000h."""
    code = [0xF3, 0x3E, 0x99, 0x06, 0x99]
    if push is not None:
        code += [0x21, push & 0xFF, push >> 8, 0xE5]
    code += [0xC3, target & 0xFF, target >> 8]
    zx.load(CODE, bytes(code))
    launch(zx, CODE)
    assert zx.run_until_pc(STORE + 7, max_ticks=10**6), 'never got back to 9000h'
    return zx.peek(0xC000), zx.peek(0xC001)


@needs_next
class Automap(NextCase):

    def anchor(self):
        zx = machine()
        entry(zx, 0x0000)
        self.assertEqual(go(zx, 0x0000), DELAYED, 'first: automap works at all')

    def test_without_automap_nothing_maps(self):
        self.anchor()
        zx = machine(automap=False)
        entry(zx, 0x0000)
        self.assertEqual(go(zx, 0x0000), NONE, 'NR 0x0A b4 = 0 (divmmc:98-99)')

    def test_0000_is_delayed_by_default(self):
        zx = machine()
        entry(zx, 0x0000)
        self.assertEqual(go(zx, 0x0000), DELAYED, 'B8 b0, B9 b0, BA b0 = 0 (zxnext:2811-2814, '
                                                  '5026-5028; divmmc:136-143)')
        self.assertEqual(zx.slot_page(0), 'divmmc-rom', 'and it stays mapped (automap_held)')

    def test_instant_when_nr_ba_says(self):
        zx = machine()
        zx.nr_write(0xBA, 0x01)
        entry(zx, 0x0000)
        self.assertEqual(go(zx, 0x0000), INSTANT, 'divmmc:147 automap on the fetch itself')

    def test_not_an_entry_point_when_nr_b8_says(self):
        self.anchor()
        zx = machine()
        zx.nr_write(0xB8, 0x82)                         # 0x0000 no longer an entry point
        entry(zx, 0x0000)
        self.assertEqual(go(zx, 0x0000), NONE, 'zxnext:2812')

    def test_rst_08_is_rom3_only(self):
        zx = machine(mtype=0b001)                       # 48K type: always ROM3 (zxnext:2942)
        entry(zx, 0x0008)
        self.assertEqual(go(zx, 0x0008), DELAYED, 'B9 b1 = 0: ROM3 only (zxnext:2856-2857)')
        zx = machine(mtype=0b010, port_7ffd=0x00)       # 128K type, ROM 0: not ROM3
        entry(zx, 0x0008)
        self.assertEqual(go(zx, 0x0008), NONE, 'not with the 128K editor in place')
        zx = machine(mtype=0b010, port_7ffd=0x10)       # ROM 1, the 48K BASIC
        entry(zx, 0x0008, rom_base=ref.ROM_SRAM[1])
        self.assertEqual(go(zx, 0x0008), DELAYED, 'sram_rom3 = 7FFD b4 (zxnext:2963)')

    def test_3dxx_is_instant_and_rom3_only(self):
        zx = machine()
        out(zx, ref.PE3, 0x00)                          # divMMC RAM bank 0 at 0x2000
        entry(zx, 0x3D00)
        self.assertEqual(go(zx, 0x3D00), INSTANT, 'BB b7 (zxnext:2853-2854)')

    def test_1ff8_unmaps_after_its_fetch(self):
        zx = machine()
        entry(zx, 0x0000, div=bytes([0x06, 0x22, 0xC3, 0xF8, 0x1F]))   # then JP 1FF8h
        for base, n in [(ref.ROM_SRAM[0], 0x44), (ref.DIVMMC_ROM, 0x33)]:
            for i, b in enumerate([0x3E, n] + JP_STORE):
                zx.sram[base + 0x1FF8 + i] = b
        a, b = go(zx, 0x0000)
        self.assertEqual(a, 0x44, 'the fetch at 1FF8h is divMMC\'s, its operand the ROM\'s '
                                  '(BB b6, zxnext:2849; divmmc:136)')
        self.assertEqual(b, 0x99, 'delayed: divMMC\'s LD B never ran as an opcode (Ratio)')
        self.assertEqual(zx.slot_page(0), ('rom', 0), 'unmapped')

    def test_retn_unmaps(self):
        zx = machine()
        entry(zx, 0x0000, div=bytes([0x06, 0x22, 0xED, 0x45]))          # LD B,22h; RETN
        self.assertEqual(go(zx, 0x0000, push=STORE), DELAYED,
                         'the ROM\'s LD A with divMMC\'s operand, then divMMC\'s RETN')
        self.assertEqual(zx.slot_page(0), ('rom', 0), 'RETN unmaps (zxnext:4052; divmmc:126, 139)')


if __name__ == '__main__':
    unittest.main()
