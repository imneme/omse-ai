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
        zx.nr_write(0x03, 0x00)                         # boot ROM off: in bare mode it wins every
                                                        # read at 0000-3FFF (zxnext:1809-1813, 5061;
                                                        # Ratio's catch), and RST 38 needs RAM there
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


def assemble(items, org):
    """Bytes and labels: str = a label here, ('jr', 'nz'|'z'|None, label) a
    relative jump, ('w', label) a little-endian address."""
    pc, labels = org, {}
    for it in items:
        if isinstance(it, str):
            labels[it] = pc
        elif isinstance(it, tuple):
            pc += 2
        else:
            pc += len(it)
    out, pc = [], org
    for it in items:
        if isinstance(it, str):
            continue
        if isinstance(it, tuple) and it[0] == 'jr':
            op = {None: 0x18, 'nz': 0x20, 'z': 0x28}[it[1]]
            out += [op, (labels[it[2]] - (pc + 2)) & 0xFF]
            pc += 2
        elif isinstance(it, tuple):
            out += [labels[it[1]] & 0xFF, labels[it[1]] >> 8]
            pc += 2
        else:
            out += it
            pc += len(it)
    return bytes(out)


CTCN, LINEN, INSIDE, NEST = 0xA000, 0xA001, 0xA002, 0xA003


def ld_a(a): return [0x3A, a & 0xFF, a >> 8]
def st_a(a): return [0x32, a & 0xFF, a >> 8]


@needs_next
class RetiService(NextCase):
    """Hardware IM2's daisy chain, line interrupt (source 0) above CTC 0 (source
    3). reti_decode is high from ED's fetch (im2c:233), reti_seen comes as 4D's
    T4 begins (im2c:171-172, 234), RETN gives retn_seen only (236). A device
    requesting passes IEO = IEI and reti_decode (im2d:142); one acknowledged or
    in service passes nothing (144); an in-service device leaves on reti_seen
    with IEI (123-124). Scree's repro (realsoft/repro/reti_race.asm) and Ratio's
    statement of it: a RETI while a higher device requests ends the service of
    the highest in-service device below it; RETN never ends service; a device
    with another in service above it never clears."""

    def play(self, ctc_handler, frames=5):
        zx = bare()
        main = [[0xF3, 0x31, 0xF0, 0xBF, 0xAF], st_a(CTCN), st_a(LINEN), st_a(INSIDE), st_a(NEST),
                [0x3E, 0x90, 0xED, 0x47, 0xED, 0x5E,                # LD I,90h; IM 2
                 0xED, 0x91, 0xC0, 0x01,                            # hardware IM2
                 0xED, 0x91, 0x22, 0x06, 0xED, 0x91, 0x23, 0x40,    # ULA off, line 64
                 0xED, 0x91, 0xC4, 0x02, 0xED, 0x91, 0xC5, 0x01, 0xED, 0x91, 0xC6, 0x00,
                 0x01, 0x3B, 0x18, 0x3E, 0x85, 0xED, 0x79, 0x3E, 200, 0xED, 0x79,   # CTC 0: int, /16, 200
                 0xFB], 'idle', ('jr', None, 'idle')]
        line = [[0xF5], ld_a(LINEN), [0x3C], st_a(LINEN), [0xF1, 0xFB, 0xED, 0x4D]]
        zx.load(0x8000, assemble(main, 0x8000))
        zx.load(0x8100, assemble(ctc_handler, 0x8100))
        zx.load(0x8300, assemble(line, 0x8300))
        zx.load(0x9000, bytes([0x00, 0x83, 0, 0, 0, 0, 0x00, 0x81]))   # vectors 00h line, 06h CTC 0
        zx.set_regs(pc=0x8000)
        zx.run_frames(frames)
        return zx.peek(CTCN), zx.peek(LINEN), zx.peek(NEST)

    def waiting_handler(self, tail):
        """CTC 0's handler from reti_race.asm: count, clear the line's status,
        poll NR C8h b1 with interrupts off until the line requests, then EI and
        the tail."""
        return [[0xF5, 0xC5], ld_a(CTCN), [0x3C], st_a(CTCN), [0xED, 0x91, 0xC8, 0x02],
                'wait', [0x01, 0x3B, 0x24, 0x3E, 0xC8, 0xED, 0x79, 0x04, 0xED, 0x78, 0xE6, 0x02],
                ('jr', 'z', 'wait'), [0xC1, 0xF1, 0xFB] + tail]

    def test_reti_with_a_higher_request_ends_the_lower_service(self):
        ctc, line, _ = self.play(self.waiting_handler([0xED, 0x4D]))
        self.assertGreaterEqual(line, 4)
        self.assertGreaterEqual(ctc, 4, f'CTC 0 left service at each RETI (got {ctc}, line {line})')
        self.assertLessEqual(abs(ctc - line), 1, 'one CTC 0 per line interrupt')

    def test_retn_never_ends_service(self):
        ctc, line, _ = self.play(self.waiting_handler([0xED, 0x45]))
        self.assertEqual(ctc, 1, 'RETN gives no reti_seen (im2c:236): CTC 0 stays in service')
        self.assertGreaterEqual(line, 4, 'the line, above it, still comes and goes')

    def test_a_device_with_another_in_service_above_it_doesnt_clear(self):
        """CTC 0's handler enables interrupts, lets the line interrupt in and out
        (its RETI ends the line's service; CTC 0 below sees IEI 0, im2d:144), then
        waits through many CTC 0 periods. CTC 0 must not interrupt its own
        handler: an entry while INSIDE is set would count in NEST."""
        h = [[0xF5, 0xC5], ld_a(INSIDE), [0xB7], ('jr', 'z', 'fresh'), ld_a(NEST), [0x3C], st_a(NEST),
             'fresh', [0x3E, 0x01], st_a(INSIDE), ld_a(CTCN), [0x3C], st_a(CTCN),
             ld_a(LINEN), [0x47, 0xFB],                          # remember LINEN; EI
             'w1', ld_a(LINEN), [0xB8], ('jr', 'z', 'w1'),       # until the line has come and gone
             [0x01, 0xE8, 0x03], 'w2', [0x0B, 0x78, 0xB1], ('jr', 'nz', 'w2'),   # ~65 CTC 0 periods
             [0xF3, 0xAF], st_a(INSIDE), [0xC1, 0xF1, 0xFB, 0xED, 0x4D]]
        ctc, line, nest = self.play(h)
        self.assertGreaterEqual(ctc, 2, 'CTC 0 came back after its own RETI')
        self.assertGreaterEqual(line, 2)
        self.assertEqual(nest, 0, 'never inside its own handler')


if __name__ == '__main__':
    unittest.main()
