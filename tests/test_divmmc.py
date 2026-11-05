"""divMMC: the interface's paging and automap, its SPI port, and the SD card.

These need only the 48K ROM. They don't use esxDOS: a small test EEPROM
(test_eeprom) hands every automap back to the ROM, and the paging is driven
by real OUT and IN instructions, run with RANDOMIZE USR. The SPI tests are
straight-line Z80 that Python writes, one OUT or IN at a time, so every byte
on the wire is seen. docs/divmmc.md has the hardware these hold us to.

The esxDOS tests at the end run if $OMSE_AI_ESXDOS names a folder holding
esxDOS 0.8.9's ESXMMC.BIN, SYS and BIN (esxdos.org; not included here):
they build a card with tools/mkfat.py and boot from it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import speccy                                           # noqa: E402
from speccy import Speccy                               # noqa: E402

OUT = ROOT / 'tests' / 'out'
OUT.mkdir(parents=True, exist_ok=True)

# The ROM instruction at each delayed entry point, and its length: its operand
# bytes are read *after* divMMC maps in, so the EEPROM must hold them too.
ENTRIES = {0x0000: 1, 0x0008: 3, 0x0038: 1, 0x0066: 1, 0x04C6: 3, 0x0562: 2}
CODE, BUF = 0x8000, 0xD000


def test_eeprom(changes=None):
    """8K: a pattern the ROM doesn't have, and at each entry point the ROM's
    own instruction, then a JP to a stub at 1000h onwards: PUSH HL; LD HL,next;
    EX (SP),HL; JP 1FF8h, where a RET (the off-area) maps the ROM back and
    returns to it at `next`, the instruction after the entry's."""
    rom = speccy.rom_bytes('48')
    e = bytearray((i * 7 + 3) & 0xFF for i in range(8192))
    stub = 0x1000
    for at, n in ENTRIES.items():
        e[at:at + n] = rom[at:at + n]
        nxt = at + n
        e[nxt:nxt + 3] = bytes([0xC3, stub & 0xFF, stub >> 8])
        e[stub:stub + 8] = bytes([0xE5, 0x21, nxt & 0xFF, nxt >> 8, 0xE3, 0xC3, 0xF8, 0x1F])
        stub += 8
    e[0x1FF8] = 0xC9
    for a, v in (changes or {}).items():
        e[a] = v
    return bytes(e)


def card_image(sectors=2048):
    """A raw card: sector s holds (s * 31 + i) & 0xFF at byte i."""
    p = OUT / 'card.img'
    p.write_bytes(bytes((s * 31 + i) & 0xFF for s in range(sectors) for i in range(512)))
    return p


def sector(s):
    return bytes((s * 31 + i) & 0xFF for i in range(512))


def crc7(bs):
    c = 0
    for b in bs:
        for _ in range(8):
            c <<= 1
            if (b ^ c) & 0x80:
                c ^= 0x09
            b = (b << 1) & 0xFF
    return c & 0x7F


def crc16(bs):
    c = 0
    for b in bs:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else c << 1
            c &= 0xFFFF
    return c


def cmd(n, arg=0, crc=None):
    f = bytes([0x40 | n, arg >> 24 & 0xFF, arg >> 16 & 0xFF, arg >> 8 & 0xFF, arg & 0xFF])
    return f + bytes([(crc7(f) << 1 | 1) if crc is None else crc])


def machine(card=None, eeprom=None, **kw):
    zx = Speccy()
    zx.fit_divmmc(eeprom if eeprom is not None else test_eeprom(), card=card, **kw)
    zx.wait_ready(max_frames=300)
    return zx


class Z80:
    """Straight-line machine code, run with RANDOMIZE USR 32768: interrupts
    off, then each step, then interrupts on and RET. Each in_() keeps the byte
    read at BUF onwards; run() returns them."""

    def __init__(self):
        self.code = bytearray([0xF3])
        self.n = 0

    def out(self, port, *bs):
        for b in bs:
            self.code += bytes([0x3E, b, 0xD3, port])
        return self

    def in_(self, count=1, port=0xEB):
        for _ in range(count):
            a = BUF + self.n
            self.code += bytes([0xDB, port, 0x32, a & 0xFF, a >> 8])
            self.n += 1
        return self

    def peek(self, addr):                 # LD A,(addr): kept like an IN
        a = BUF + self.n
        self.code += bytes([0x3A, addr & 0xFF, addr >> 8, 0x32, a & 0xFF, a >> 8])
        self.n += 1
        return self

    def poke(self, addr, v):              # LD A,v; LD (addr),A
        self.code += bytes([0x3E, v, 0x32, addr & 0xFF, addr >> 8])
        return self

    def raw(self, bs):
        self.code += bytes(bs)
        return self

    def run(self, zx):
        code = bytes(self.code) + bytes([0xFB, 0xC9])
        assert CODE + len(code) <= BUF
        zx.write(CODE, code)
        zx.type('RANDOMIZE USR 32768\n')
        zx.wait_ready(max_frames=500)
        return zx.read(BUF, self.n)


def wake_and_select(z):
    """74+ clocks with CS high (ten bytes of FF), then select card 0."""
    return z.out(0xE7, 0xFF).out(0xEB, *[0xFF] * 10).out(0xE7, 0xFE)


def init_card(z):
    """CMD0, CMD8, ACMD41 (HCS) twice: the card leaves idle on the second."""
    wake_and_select(z)
    z.out(0xEB, *cmd(0, 0)).in_(4)
    z.out(0xEB, *cmd(8, 0x1AA)).in_(8)
    for _ in range(2):
        z.out(0xEB, *cmd(55)).in_(3).out(0xEB, *cmd(41, 0x40000000)).in_(3)
    return z


class TestPaging(unittest.TestCase):
    def test_boots_through_the_test_eeprom(self):
        zx = machine()
        self.assertIn('1982 Sinclair Research', zx.screen_text())
        st = zx.divmmc_state()
        self.assertTrue(st['fitted'])
        self.assertFalse(st['mapped'])

    def test_conmem_maps_eeprom_below_and_a_bank_above(self):
        zx = machine()
        e = test_eeprom()
        got = (Z80().out(0xE3, 0x80 | 5)        # CONMEM, bank 5
               .peek(0x0100).peek(0x1234)
               .poke(0x2000, 0x55).peek(0x2000)
               .poke(0x0100, 0xAA).peek(0x0100)  # the EEPROM is write-protected
               .out(0xE3, 0x00).peek(0x0100)      # the ROM again
               .run(zx))
        rom = speccy.rom_bytes('48')
        self.assertEqual(list(got), [e[0x100], e[0x1234], 0x55, e[0x100], rom[0x100]])
        self.assertEqual(zx.divmmc_ram(5)[0], 0x55)
        self.assertNotEqual(zx.divmmc_ram(4)[0], 0x55)

    def test_eeprom_takes_writes_with_its_jumper_off(self):
        zx = machine()
        zx.lib.zx_div_wp(zx.z, 0)
        Z80().out(0xE3, 0x80).poke(0x0100, 0xAA).out(0xE3, 0x00).run(zx)
        self.assertEqual(zx.divmmc_eeprom()[0x100], 0xAA)

    def test_sixteen_banks_each_its_own(self):
        zx = machine()
        z = Z80()
        for b in range(16):
            z.out(0xE3, 0x80 | b).poke(0x2000, 0xB0 + b)
        for b in range(16):
            z.out(0xE3, 0x80 | b).peek(0x2000)
        z.out(0xE3, 0x80 | 0x3F).peek(0x2000)   # bits 0-5 set: 128K has 16, so bank 15
        z.out(0xE3, 0x00)
        self.assertEqual(list(z.run(zx)), [0xB0 + b for b in range(16)] + [0xBF])

    def test_mapram_sticks_until_power_off(self):
        zx = machine()
        Z80().out(0xE3, 0x40).out(0xE3, 0x00).run(zx)
        self.assertTrue(zx.divmmc_state()['mapram'])
        zx.lib.zx_reset(zx.z)
        self.assertFalse(zx.divmmc_state()['mapram'])

    def test_mapram_puts_bank_3_below_read_only(self):
        zx = machine()
        # as esxDOS does: copy the EEPROM into bank 3 (CONMEM, LDIR 0000 -> 2000), then MAPRAM
        Z80().out(0xE3, 0x80 | 3).raw([0x21, 0, 0, 0x11, 0, 0x20, 0x01, 0, 0x20, 0xED, 0xB0]) \
             .out(0xE3, 0x40).run(zx)
        self.assertEqual(zx.divmmc_ram(3), test_eeprom())
        self.assertEqual(zx.run_until(0x0039, frames=5), 0x0039)   # the next interrupt automaps
        st = zx.divmmc_state()
        self.assertEqual((st['mapped'], st['lower'], st['upper']), (True, 3, 0))
        self.assertFalse(st['lower_writable'])
        self.assertTrue(st['upper_writable'])
        zx.wait_ready(max_frames=100)
        Z80().out(0xE3, 0x40 | 3).run(zx)          # bank 3 above too: read-only there as well
        zx.run_until(0x0039, frames=5)
        st = zx.divmmc_state()
        self.assertEqual((st['upper'], st['upper_writable']), (3, False))

    def test_entry_points_map_after_their_fetch(self):
        # A HALT in the EEPROM where the ROM has DI (0000) and PUSH AF (0038):
        # mapped *before* those fetches, the machine would hang at power-on and
        # in every interrupt. Mapped after them, as the hardware does, it boots.
        zx = machine(eeprom=test_eeprom({0x0000: 0x76, 0x0038: 0x76}))
        self.assertIn('1982 Sinclair Research', zx.screen_text())
        zx.type('PRINT 6*7\n')
        zx.wait_ready(max_frames=100)
        self.assertIn('42', zx.screen_text())

    def test_3d00_maps_instantly(self):
        # Code in bank 0 at 3D00 (the ROM's font there is data): a fetch at
        # 3D00 must read divMMC's bank, then the off-area's RET maps the ROM back.
        # It's CALLed from code running with interrupts off, so no interrupt lands
        # while divMMC is mapped (that would run the EEPROM's own 0038).
        zx = machine()
        code = [0x3E, 0x42, 0x32, 0x00, 0xE0, 0xC3, 0xF8, 0x1F]   # LD A,42h; LD (E000h),A; JP 1FF8h
        z = Z80().out(0xE3, 0x80)
        for i, b in enumerate(code):
            z.poke(0x3D00 + i, b)
        z.out(0xE3, 0x00).raw([0xCD, 0x00, 0x3D]).peek(0x3D00)       # CALL 3D00h; then the ROM's font
        got = z.run(zx)
        self.assertEqual(zx.peek(0xE000), 0x42)
        self.assertEqual(got[0], speccy.rom_bytes('48')[0x3D00])     # unmapped again on return
        self.assertFalse(zx.divmmc_state()['mapped'])

    def test_nmi_automaps(self):
        zx = machine()
        zx.nmi()
        self.assertEqual(zx.run_until(0x0067, frames=5), 0x0067)
        self.assertTrue(zx.divmmc_state()['mapped'])
        zx.type('PRINT 1+1\n')
        zx.wait_ready(max_frames=100)
        self.assertIn('2', zx.screen_text())

    def test_the_tape_deck_still_loads(self):
        # LD-BYTES at 0562 is an entry point; with a tape in omse-ai's deck the
        # trap serves it and divMMC isn't mapped.
        zx = Speccy()
        zx.type('10 PRINT "from tape"\n')
        zx.type('SAVE "t"\n', verify=False)       # it waits at "Start tape, then press any key"
        zx.run(10)
        zx.keystroke('SPACE')
        zx.wait_ready(max_frames=300)
        tap = zx.saved_tape()
        zx = machine()
        zx.insert_tape(tap)
        zx.type('LOAD ""\n')
        zx.wait_ready(max_frames=500)
        zx.type('RUN\n')
        zx.wait_ready(max_frames=100)
        self.assertIn('from tape', zx.screen_text())
        self.assertFalse(zx.divmmc_state()['mapped'])


class TestSPI(unittest.TestCase):
    def test_a_read_returns_the_previous_transfer(self):
        # After CMD0's CRC byte the first IN returns what that transfer received
        # (FF), and starts the next; R1 (01) comes N_CR transfers after the command.
        for ncr in (0, 1, 2):
            with self.subTest(ncr=ncr):
                zx = machine(card=card_image())
                zx.sd_timing(ncr=ncr)
                got = wake_and_select(Z80()).out(0xEB, *cmd(0)).in_(5).run(zx)
                want = [0xFF] * (1 + ncr) + [0x01]
                self.assertEqual(list(got[:len(want)]), want)

    def test_a_card_needs_its_wake_up_clocks(self):
        zx = machine(card=card_image())
        got = Z80().out(0xE7, 0xFE).out(0xEB, *cmd(0)).in_(10).run(zx)
        self.assertEqual(set(got), {0xFF})
        self.assertEqual(zx.sd_log(), [('CMD0', 0, None)])

    def test_cmd0_and_cmd8_check_their_crc(self):
        zx = machine(card=card_image())
        got = wake_and_select(Z80()).out(0xEB, *cmd(0, crc=0x01)).in_(4).run(zx)
        self.assertEqual(set(got), {0xFF})                 # not yet in SPI mode: ignored
        zx = machine(card=card_image())
        got = (wake_and_select(Z80()).out(0xEB, *cmd(0)).in_(4)
               .out(0xEB, *cmd(8, 0x1AA, crc=0x01)).in_(4).run(zx))
        self.assertEqual(got[2], 0x01)
        self.assertEqual(got[6], 0x09)                     # idle + CRC error

    def test_initialise_and_read_a_block(self):
        zx = machine(card=card_image())
        z = init_card(Z80())
        z.out(0xEB, *cmd(58)).in_(7)
        z.out(0xEB, *cmd(17, 5)).in_(520)
        got = z.run(zx)
        self.assertEqual(list(got[6:11]), [0x01, 0x00, 0x00, 0x01, 0xAA])   # R7: echo of 1AA
        acmd41 = [got[i] for i in (12 + 3 + 2, 12 + 6 + 3 + 2)]
        self.assertEqual(acmd41, [0x01, 0x00])                           # idle, then ready
        self.assertEqual(list(got[26:31]), [0x00, 0xC0, 0xFF, 0x80, 0x00])  # OCR: up, CCS
        blk = got[31:]
        self.assertEqual(blk[2], 0x00)                                   # R1
        i = blk.index(0xFE, 3)                                           # N_AC, then the token
        self.assertEqual(blk[i + 1:i + 513], sector(5))
        self.assertEqual(blk[i + 513] << 8 | blk[i + 514], crc16(sector(5)))
        self.assertEqual([n for n, a, r in zx.sd_log()],
                         ['CMD0', 'CMD8', 'CMD55', 'ACMD41', 'CMD55', 'ACMD41', 'CMD58', 'CMD17'])

    def test_reads_before_initialising_are_illegal(self):
        zx = machine(card=card_image())
        got = wake_and_select(Z80()).out(0xEB, *cmd(0)).in_(3).out(0xEB, *cmd(17, 0)).in_(3).run(zx)
        self.assertEqual(got[5], 0x05)                     # idle + illegal command

    def test_write_a_block_into_memory_not_the_file(self):
        img = card_image()
        before = img.read_bytes()
        zx = machine(card=img)
        data = bytes(range(256)) * 2
        z = init_card(Z80())
        z.out(0xEB, *cmd(24, 7)).in_(3).out(0xEB, 0xFF, 0xFE, *data, 0x12, 0x34).in_(5)
        z.out(0xEB, *cmd(17, 7)).in_(520)
        got = z.run(zx)
        w = got[-(520 + 5):-520]
        self.assertEqual(list(w), [0xFF, 0x05, 0x00, 0x00, 0xFF])        # accepted, busy, done
        blk = got[-520:]
        i = blk.index(0xFE, 3)
        self.assertEqual(blk[i + 1:i + 513], data)
        self.assertEqual(img.read_bytes(), before)

    def test_a_writable_card_writes_its_file(self):
        img = card_image()
        zx = machine(card=img, writable=True)
        data = bytes([0x5A]) * 512
        init_card(Z80()).out(0xEB, *cmd(24, 9)).in_(3).out(0xEB, 0xFF, 0xFE, *data, 0, 0).in_(5).run(zx)
        zx.sd_eject()
        self.assertEqual(img.read_bytes()[9 * 512:10 * 512], data)

    def test_multiple_block_read_stops_at_cmd12(self):
        zx = machine(card=card_image())
        z = init_card(Z80())
        z.out(0xEB, *cmd(18, 3)).in_(2 * 520)
        z.out(0xEB, *cmd(12)).in_(8)
        got = z.run(zx)
        stream = got[-(2 * 520 + 8):-8]
        i = stream.index(0xFE)
        self.assertEqual(stream[i + 1:i + 513], sector(3))
        j = stream.index(0xFE, i + 515)
        self.assertEqual(stream[j + 1:j + 513], sector(4))
        # after CMD12: what its CRC byte's transfer received, the stuff byte (the
        # block's next byte: discard it), N_CR, R1, busy (00 00), then quiet
        tail = got[-8:]
        self.assertEqual(list(tail[2:]), [0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF])
        # The stuff byte is what the card would have sent next. Transfer 0 is
        # CMD18's CRC; the INs start transfers 1-1040, CMD12's bytes 1041-1046,
        # so the stuff byte is transfer 1047. Sector 3 took 1-518 (N_CR, R1,
        # N_AC, token, 512, CRC), sector 4 519-1034 (N_AC, token, 512, CRC),
        # sector 5 starts at 1035: N_AC, token, then data from 1037: byte 10.
        self.assertEqual(tail[1], sector(5)[10])
        self.assertEqual(zx.sd_log()[-1][0], 'CMD12')

    def test_cmd1_never_starts_an_sdhc_card(self):
        zx = machine(card=card_image())
        z = wake_and_select(Z80()).out(0xEB, *cmd(0)).in_(3)
        for _ in range(5):
            z.out(0xEB, *cmd(1)).in_(3)
        self.assertEqual(z.run(zx)[-1], 0x01)              # still idle: SDHC needs ACMD41 with HCS

    def test_an_unknown_command_is_illegal(self):
        zx = machine(card=card_image())
        got = init_card(Z80()).out(0xEB, *cmd(5)).in_(3).run(zx)
        self.assertEqual(got[-1], 0x04)


def start(z, kind):
    """Wake the card and initialise it the way its kind wants: SD 2.0 cards
    CMD8 then ACMD41 with HCS, an SD 1.x card ACMD41 alone (its CMD8 is an
    illegal command), an MMC CMD1. Twice, as the card leaves idle on the second."""
    wake_and_select(z).out(0xEB, *cmd(0)).in_(3)
    if kind != 'mmc':
        z.out(0xEB, *cmd(8, 0x1AA)).in_(7)
    for _ in range(2):
        if kind == 'mmc':
            z.out(0xEB, *cmd(1)).in_(3)
        else:
            z.out(0xEB, *cmd(55)).in_(3).out(0xEB, *cmd(41, 0 if kind == 'sdv1' else 0x40000000)).in_(3)
    return z


def capacity(csd):
    """The capacity a CSD declares, in bytes: version 2.0 (SDHC) or 1.0."""
    bits = int.from_bytes(csd, 'big')

    def f(hi, lo):
        return bits >> lo & ((1 << (hi - lo + 1)) - 1)
    if f(127, 126) == 1:
        return (f(69, 48) + 1) * 512 * 1024
    return (f(73, 62) + 1) * (1 << (f(49, 47) + 2)) * (1 << f(83, 80))


class TestCardKinds(unittest.TestCase):
    """SDSC, SD 1.x and MMC cards: byte addresses, CMD16, and their own ways in."""

    def card(self, kind, z):
        zx = machine(card=card_image(), kind=kind)
        return zx, z.run(zx)

    def test_each_kind_starts_its_own_way(self):
        for kind, cmd8, ocr in (('sdhc', 0x01, 0xC0), ('sdsc', 0x01, 0x80), ('sdv1', 0x05, 0x80),
                                ('mmc', None, 0x80)):
            with self.subTest(kind=kind):
                z = start(Z80(), kind).out(0xEB, *cmd(58)).in_(7)
                zx, got = self.card(kind, z)
                if cmd8 is not None:
                    self.assertEqual(got[5], cmd8)               # R1 of CMD8: 05 is illegal
                self.assertEqual(got[-7 + 2:-7 + 4], bytes([0x00, ocr]))   # ready, then OCR (CCS only SDHC)
                names = [n for n, a, r in zx.sd_log()]
                self.assertEqual(names[-1], 'CMD58')

    def test_an_mmc_has_no_cmd8_and_no_cmd55(self):
        zx, got = self.card('mmc', wake_and_select(Z80()).out(0xEB, *cmd(0)).in_(3)
                            .out(0xEB, *cmd(8, 0x1AA)).in_(3).out(0xEB, *cmd(55)).in_(3))
        self.assertEqual(list(got[5::3][:2]), [0x05, 0x05])

    def test_byte_addressed_cards_read_by_byte(self):
        for kind in ('sdsc', 'sdv1', 'mmc'):
            with self.subTest(kind=kind):
                z = start(Z80(), kind)
                z.out(0xEB, *cmd(17, 5 * 512)).in_(520)
                z.out(0xEB, *cmd(17, 5)).in_(3)                    # mid-block: it would cross one
                zx, got = self.card(kind, z)
                blk = got[-(520 + 3):-3]
                self.assertEqual(blk[2], 0x00)
                i = blk.index(0xFE, 3)
                self.assertEqual(blk[i + 1:i + 513], sector(5))
                self.assertEqual(got[-1], 0x20)                     # address error

    def test_cmd16_reads_a_shorter_block(self):
        z = start(Z80(), 'sdsc')
        z.out(0xEB, *cmd(16, 256)).in_(3)
        z.out(0xEB, *cmd(17, 5 * 512 + 256)).in_(264)
        z.out(0xEB, *cmd(24, 6 * 512)).in_(3)                      # a write needs 512 again
        zx, got = self.card('sdsc', z)
        blk = got[-(264 + 3):-3]
        i = blk.index(0xFE, 3)
        self.assertEqual(blk[i + 1:i + 257], sector(5)[256:])
        self.assertEqual(blk[i + 257] << 8 | blk[i + 258], crc16(sector(5)[256:]))
        self.assertEqual(got[-1], 0x40)

    def test_the_csd_says_the_capacity(self):
        for kind in ('sdhc', 'sdsc', 'sdv1', 'mmc'):
            with self.subTest(kind=kind):
                zx, got = self.card(kind, start(Z80(), kind).out(0xEB, *cmd(9)).in_(24))
                csd = got[-24:]
                i = csd.index(0xFE, 3)
                self.assertEqual(capacity(csd[i + 1:i + 17]), 2048 * 512)
                self.assertEqual(csd[i + 16] >> 1, crc7(csd[i + 1:i + 16]))

    def test_a_standard_card_is_2_gb_at_most(self):
        big = OUT / 'big.img'
        with open(big, 'wb') as f:
            f.truncate(0x80000000 + 512)                            # sparse: no disk used
        try:
            zx = Speccy()
            with self.assertRaises(ValueError):
                zx.sd_insert(big, kind='sdsc')
            zx.sd_insert(big, kind='sdhc')
            zx.sd_eject()
        finally:
            big.unlink()


ESXDOS = os.environ.get('OMSE_AI_ESXDOS')


def have_esxdos():
    return bool(ESXDOS) and all((Path(ESXDOS) / n).exists() for n in ('ESXMMC.BIN', 'SYS', 'BIN'))


def hello_tap():
    """A tape saved by a plain 48K: prints a line and plays a scale."""
    zx = Speccy()
    for line in ['10 PRINT AT 9,4;"Hello from the SD card!"',
                 '20 FOR n=0 TO 7: BEEP .05,n*2: NEXT n']:
        zx.type(line + '\n')
    zx.type('SAVE "hello" LINE 10\n', verify=False)
    zx.run(10)
    zx.keystroke('SPACE')
    zx.wait_ready(max_frames=300)
    return zx.saved_tape()


@unittest.skipUnless(have_esxdos(), 'set OMSE_AI_ESXDOS to a folder holding esxDOS 0.8.9 '
                                    '(ESXMMC.BIN, SYS, BIN), from esxdos.org')
class TestEsxDOS(unittest.TestCase):
    """esxDOS from a card built by tools/mkfat.py: SYS, BIN, TMP and HELLO.TAP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tree = Path(cls.tmp.name) / 'card'
        for d in ('SYS', 'BIN', 'TMP'):
            src = Path(ESXDOS) / d
            if src.exists():
                shutil.copytree(src, tree / d)
            else:
                (tree / d).mkdir(parents=True)
        (tree / 'HELLO.TAP').write_bytes(hello_tap())
        cls.img = Path(cls.tmp.name) / 'esx.img'
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'mkfat.py'), 'build',
                            str(cls.img), str(tree)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def boot(self):
        zx = Speccy()
        zx.fit_divmmc(Path(ESXDOS) / 'ESXMMC.BIN', card=self.img, boot_frames=0)
        zx.wait_ready(max_frames=1500)
        return zx

    def test_boots_from_the_card(self):
        zx = self.boot()
        self.assertIn('1982 Sinclair Research', zx.screen_text())
        names = [n for n, a, r in zx.sd_log()]
        self.assertEqual(names[:4], ['CMD0', 'CMD8', 'CMD55', 'ACMD41'])
        self.assertIn('CMD58', names)
        self.assertIn('CMD17', names)

    def test_every_kind_of_card(self):
        # esxDOS's driver takes its own path for each: SDHC needs no CMD16; an
        # SDSC card (CCS clear) gets CMD16 for 512-byte blocks; an SD 1.x card
        # or an MMC refuses CMD8, and esxDOS falls back to CMD1.
        for kind, want, refuse in (('sdhc', 'ACMD41', 'CMD16'), ('sdsc', 'CMD16', 'CMD1'),
                                   ('sdv1', 'CMD1', 'ACMD41'), ('mmc', 'CMD1', 'ACMD41')):
            with self.subTest(kind=kind):
                zx = Speccy()
                zx.fit_divmmc(Path(ESXDOS) / 'ESXMMC.BIN', card=self.img, kind=kind, boot_frames=0)
                self.assertIsNotNone(zx.wait_ready(max_frames=1500))
                names = [n for n, a, r in zx.sd_log()]
                self.assertIn(want, names)
                self.assertNotIn(refuse, names)
                zx.dot('.ls')
                self.assertIn('HELLO.TAP', zx.screen_text())

    def test_loads_a_tape_from_the_card(self):
        zx = self.boot()
        self.assertIsNotNone(zx.dot('.ls'))
        self.assertIn('HELLO.TAP', zx.screen_text())
        self.assertIsNotNone(zx.dot('.tapein hello.tap'))
        zx.record_audio()
        zx.type('LOAD ""\n')
        zx.wait_ready(max_frames=1500)
        self.assertIn('Hello from the SD card!', zx.screen_text())
        notes = [hz for start, length, hz in zx.beeper_notes()]
        self.assertEqual(len(notes), 8)
        for k, hz in enumerate(notes):                   # BEEP .05,n*2: middle C up, whole tones
            self.assertAlmostEqual(hz / (261.63 * 2 ** (2 * k / 12)), 1, delta=0.01)

    def test_loads_from_the_nmi_browser(self):
        # The browser lists the card's root by name (BIN, HELLO, SYS, TMP) in
        # its own font, which screen_text can't read; it reads the keyboard
        # itself, so keys are held rather than typed. ENTER on HELLO loads it,
        # and it autostarts.
        zx = self.boot()
        zx.nmi()
        zx.run(60)
        self.assertTrue(zx.divmmc_state()['mapped'])
        zx.hold('DOWN', 6)
        zx.run(20)
        zx.hold('ENTER', 6)
        zx.wait_ready(max_frames=1500)
        self.assertIn('Hello from the SD card!', zx.screen_text())
        self.assertFalse(zx.divmmc_state()['mapped'])


if __name__ == '__main__':
    unittest.main()
