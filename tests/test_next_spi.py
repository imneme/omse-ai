"""The Next's SPI master and an SD card: the 16-clock rule, end to end
(the foil, Loam Fern).

From the survey's §1.7 and spi_master.vhd (spi:82-177), core 3.02.02, through
DESIGN.md §9/§9.1 (9) only. The rule: a transfer begins only when the 5-bit
counter is idle or at its last state, so an access sooner than that starts
nothing; a read returns the byte the previous transfer received (spi:159-168;
zxnext:2776). Last night's real-hardware bug ("The Card Is the Lever" on
Melissa's Next) was exactly this rule.

Observed only through the card's own replies, so nothing here peeks inside:
CMD0 must answer R1 = 01 and CMD8 (argument 1AAh) must echo R7 = 01 00 00 01
AA (SD Physical Layer Simplified Spec, SPI mode). Writing every command byte
twice back to back (11 T apart, too soon) must change nothing: the duplicates
start no transfer. Written twice 19 T apart, both go out and the card sees
garbage. Reads paired back to back return the same byte twice.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch                      # noqa: E402

CODE, RESULTS, NREADS = 0x8100, 0xC000, 12
CMD0 = [0x40, 0x00, 0x00, 0x00, 0x00, 0x95]
CMD8 = [0x48, 0x00, 0x00, 0x01, 0xAA, 0x87]
R7 = [0x01, 0x00, 0x00, 0x01, 0xAA]


def out_eb(b, mode):
    """LD A,b; OUT (EBh),A, once ('single'), twice back to back ('fast',
    11 T apart), or twice with two NOPs between ('slow', 19 T apart)."""
    if mode == 'gap16':                                 # OUT (C),A; NOP; OUT (C),A: 16 apart
        return [0x3E, b, 0xED, 0x79, 0x00, 0xED, 0x79]
    code = [0x3E, b, 0xD3, 0xEB]
    if mode == 'gap15':                                 # OUT (n),A; NOP; OUT (n),A: 15 apart
        code += [0x00, 0xD3, 0xEB]
    elif mode == 'fast':
        code += [0xD3, 0xEB]
    elif mode == 'slow':
        code += [0x00, 0x00, 0xD3, 0xEB]
    return code


def reads(n, paired=False):
    """n reads into (HL): IN A,(EBh); LD (HL),A; INC HL (24 T apart), or, if
    paired, IN A,(EBh) and IN B,(C) back to back, both stored."""
    one = [0xDB, 0xEB, 0x77, 0x23]
    two = [0xDB, 0xEB, 0xED, 0x40, 0x77, 0x23, 0x70, 0x23]
    if paired == 'gap15':                               # IN A,(n); LD E,A; IN A,(n): 15 apart
        return [0xDB, 0xEB, 0x5F, 0xDB, 0xEB, 0x73, 0x23, 0x77, 0x23] * n
    if paired == 'ini':                                 # INI; INI; ...: 16 apart
        return [0xED, 0xA2] * (2 * n)
    return (two if paired else one) * n


def program(commands, paired=False):
    """Deselect; ten FF clocks; select card 0 (E7 = FEh, zxnext:3258-3290);
    for each (bytes, mode): the bytes, then NREADS reads; JR $."""
    code = [0xF3, 0x21, RESULTS & 0xFF, RESULTS >> 8, 0x01, 0xEB, 0x00,
            0x3E, 0xFF, 0xD3, 0xE7]
    for _ in range(10):
        code += out_eb(0xFF, 'single')
    code += [0x3E, 0xFE, 0xD3, 0xE7]
    for cmd, mode in commands:
        for b in cmd:
            code += out_eb(b, mode)
        code += reads(NREADS, paired)
    return bytes(code + [0x18, 0xFE])


def reply(stream, n):
    """The first n bytes from the first one that isn't FF (the card's
    response after N_CR filler bytes)."""
    for i, b in enumerate(stream):
        if b != 0xFF:
            return list(stream[i:i + n])
    return []


@needs_next
class SpiGap(NextCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.card = os.path.join(cls.tmp.name, 'card.img')
        with open(cls.card, 'wb') as f:
            f.write(bytes(4 * 1024 * 1024))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_cards(self, commands, paired=False, speed=0):
        zx = bare(speed=speed)
        zx.sd_insert(self.card, kind='sdhc')
        code = program(commands, paired)
        zx.load(CODE, code)
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(CODE + len(code) - 2, max_ticks=10**7), 'program ran')
        per = NREADS * (2 if paired else 1)             # every reader stores 2 bytes a pair
        got = zx.read(RESULTS, per * len(commands))
        return [list(got[i * per:(i + 1) * per]) for i in range(len(commands))]

    def check_speeds(self, fn):
        for speed in (0, 3):
            with self.subTest(speed=speed):
                fn(speed)

    def test_well_spaced_commands(self):
        def t(speed):
            r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'single')], speed=speed)
            self.assertEqual(reply(r0, 1), [0x01], 'CMD0: R1 idle')
            self.assertEqual(reply(r8, 5), R7, 'CMD8: R7 echoes 1AAh')
        self.check_speeds(t)

    def test_writes_too_soon_start_nothing(self):
        def t(speed):
            r0, r8 = self.run_cards([(CMD0, 'fast'), (CMD8, 'fast')], speed=speed)
            self.assertEqual(reply(r0, 1), [0x01], 'each duplicate 11 T on started nothing '
                                                   '(spi:82-100)')
            self.assertEqual(reply(r8, 5), R7, 'so the card saw clean commands')
        self.check_speeds(t)

    def test_writes_far_enough_apart_all_go_out(self):
        def t(speed):
            r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'slow')], speed=speed)
            self.assertEqual(reply(r0, 1), [0x01])
            self.assertNotEqual(reply(r8, 5), R7, '19 T apart, both copies were sent: '
                                                  'the card saw 48 48 00 00 00 00 ...')
        self.check_speeds(t)

    def test_a_read_too_soon_returns_the_same_byte(self):
        def t(speed):
            r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'single')], paired=True,
                                    speed=speed)
            pairs = list(zip(r8[0::2], r8[1::2]))
            self.assertTrue(all(a == b for a, b in pairs),
                            f'IN B,(C) right after IN A,(EBh) returns the same byte, '
                            f'having started nothing (spi:159-168): {pairs}')
            self.assertEqual(reply([a for a, b in pairs], 5), R7,
                             'and the stream advanced one byte a pair')
        self.check_speeds(t)


@needs_next
class SpiGapBoundary(SpiGap):
    """Mutant survivors: the boundary itself, at 3.5 MHz where T-states are
    CPU clocks (at 28 MHz each read's wait would widen these gaps)."""

    test_well_spaced_commands = test_writes_too_soon_start_nothing = None
    test_writes_far_enough_apart_all_go_out = test_a_read_too_soon_returns_the_same_byte = None

    def test_writes_15_apart_start_nothing(self):
        r0, r8 = self.run_cards([(CMD0, 'gap15'), (CMD8, 'gap15')])
        self.assertEqual(reply(r0, 1), [0x01])
        self.assertEqual(reply(r8, 5), R7, '15 clocks on, the copy started nothing (spi:82-100)')

    def test_writes_16_apart_both_go_out(self):
        r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'gap16')])
        self.assertEqual(reply(r0, 1), [0x01])
        self.assertNotEqual(reply(r8, 5), R7, '16 clocks on, the copy went out too')

    def test_a_read_15_apart_rereads(self):
        r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'single')], paired='gap15')
        pairs = list(zip(r8[0::2], r8[1::2]))
        self.assertTrue(all(a == b for a, b in pairs), f'15 apart: the same byte (spi:159-168) {pairs}')

    def test_reads_16_apart_get_each_finished_byte(self):
        r0, r8 = self.run_cards([(CMD0, 'single'), (CMD8, 'single')], paired='ini')
        self.assertEqual(reply(r8, 5), R7, 'INI after INI, 16 apart: one fresh byte each')


if __name__ == '__main__':
    unittest.main()
