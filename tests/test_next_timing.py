"""The Next's timing: frames, the INT pulse, the line interrupt, 28 MHz waits,
speed changes, contention and the floating bus (the foil, Loam Fern).

Written from the survey's §1-§2, zxula_timing.vhd, zxula.vhd and zxnext.vhd
(core 3.02.02), through DESIGN.md §9/§9.1 only. The contention reference
(nextref.Contention) is the ULA's own rule in hc_ula terms; test_next_ref.py
checks it against the classic table on thousands of random runs. Wait-state
counts confirmed from t80n.vhd by Strobe, the Z80N me.

Programs run from RAM at 0x8000 (page 4, uncontended under every timing),
launched from the parked loop by patching it into a JP, and are measured
between two run_until_pc stops (§9.1 5): in t28 for contention, in cpu_clocks
for wait states.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402

LOOP = 0x8001                       # JR $ (test_next_regs.LOOP at PARK + 1)
CODE = 0x8100
REPS = 600


def launch(zx, target):
    """From the parked loop's JR, jump to target: JR +0 then JP target."""
    assert zx.run_until_pc(LOOP, max_ticks=10**6)
    zx.poke(0x8003, 0xC3)
    zx.poke(0x8004, target & 0xFF)
    zx.poke(0x8005, target >> 8)
    zx.poke(0x8002, 0x00)


def goto_line(zx, timing, hz, line):
    """Park at an instruction boundary a little before ULA row `line`."""
    L, N, *_ = ref.TIMINGS[(timing, hz)]
    assert zx.run_until_pc(LOOP, max_ticks=10**6)
    now = zx.vc_ula * L + zx.hc_ula
    d = (line * L - now - 300) % (L * N)
    zx.run_ticks(d * ref.TICKS_PER_PIXEL)


def run_block(zx, addr, code, start, end, timing='48k', hz=50, line=None):
    """Load code at addr, launch it (at ULA row `line` if given), and return
    (t28 from start to end, cpu_clocks from start to end, hc_ula, vc_ula at start)."""
    zx.load(addr, code)
    if line is not None:
        goto_line(zx, timing, hz, line)
    launch(zx, addr)
    assert zx.run_until_pc(start, max_ticks=10**7), f'never reached {start:#06x}'
    t0, c0, q, v = zx.t28, zx.cpu_clocks, zx.hc_ula, zx.vc_ula
    assert zx.run_until_pc(end, max_ticks=10**8), f'never reached {end:#06x}'
    return zx.t28 - t0, zx.cpu_clocks - c0, q, v


def program(setup, body, reps, prefix=0):
    """setup; `prefix` x LD A,(BC) (7 T, to vary the phase); S: body x reps;
    E: JR $.  Returns (code, offset of S, offset of E)."""
    code = bytes([0xF3]) + bytes(setup) + bytes([0x0A]) * prefix
    s = len(code)
    code += bytes(body) * reps
    return code + bytes([0x18, 0xFE]), s, len(code)


MMU0 = [0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x00, 0x01]


def pulses(case, zx, frames, since=0, at_least=2):
    """Run frames; the INT pulses since index `since`, failing (not erroring)
    if there are too few to judge."""
    zx.run_frames(frames)
    got = zx.int_log[since:]
    case.assertGreaterEqual(len(got), at_least, f'only {len(got)} INT pulses in {frames} frames')
    return got


@needs_next
class Frames(NextCase):
    """§2.2: the frame, and the T-states in it."""

    def test_int_period_is_the_frame(self):
        for (timing, hz) in ref.TIMINGS:
            zx = bare(timing=timing, hz=hz)
            zx.run_frames(4)
            starts = [s for s, e in zx.int_log]
            self.assertGreaterEqual(len(starts), 3, f'{timing} {hz} Hz: INT pulses')
            self.assertEqual({b - a for a, b in zip(starts, starts[1:])},
                             {ref.frame_ticks(timing, hz)}, f'{timing} {hz} Hz: ulat:147-312')

    def test_pentagon_is_always_50_hz(self):
        zx = bare(timing='pentagon', hz=60)
        zx.run_frames(4)
        starts = [s for s, e in zx.int_log]
        self.assertEqual({b - a for a, b in zip(starts, starts[1:])},
                         {ref.frame_ticks('pentagon', 50)}, 'zxnext:5739-5743')
        self.assertEqual(zx.nr_read(0x05) & 0x04, 0, 'NR 0x05 b2 forced to 50 Hz')

    def test_cpu_clocks_a_frame_at_every_speed(self):
        for timing, hz in [('48k', 50), ('128k', 50), ('p3', 60), ('pentagon', 50)]:
            for speed in range(4):
                zx = bare(timing=timing, hz=hz, speed=speed)
                zx.run_frames(1)
                c0 = zx.cpu_clocks
                zx.run_ticks(ref.frame_ticks(timing, hz))
                self.assertEqual(zx.cpu_clocks - c0,
                                 ref.frame_ticks(timing, hz) // ref.TICKS_PER_CLOCK[speed],
                                 f'{timing} {hz} Hz speed {speed}: top4:1005-1030; §2.2 '
                                 f'(a 128K frame is {ref.frame_tstates("128k", 50)} T)')


@needs_next
class UlaInterrupt(NextCase):
    """§2.3: where the ULA interrupt goes up, and how long the INT pulse is."""

    def test_pulse_is_32_or_36_ticks_at_28_mhz(self):
        for timing in ('48k', '128k', 'p3', 'pentagon'):
            zx = bare(timing=timing, speed=3)
            zx.run_frames(3)
            self.assertEqual({e - s for s, e in zx.int_log}, {ref.INT_CLOCKS[timing]},
                             f'{timing}: zxnext:1971-2003, one CPU clock a tick at 28 MHz')

    def test_pulse_length_at_slower_speeds(self):
        for timing in ('48k', '128k'):
            n = ref.INT_CLOCKS[timing]
            for speed in (0, 1, 2):
                p = ref.TICKS_PER_CLOCK[speed]
                zx = bare(timing=timing, speed=speed)
                for s, e in pulses(self, zx, 3):
                    self.assertTrue((n - 1) * p < e - s <= n * p,
                                    f'{timing} speed {speed}: {e - s} ticks for {n} CPU clocks')

    def test_place_on_the_beam(self):
        for (timing, hz) in ref.TIMINGS:
            zx = bare(timing=timing, hz=hz)
            nxt = pulses(self, zx, 2, at_least=1)[-1][0] + ref.frame_ticks(timing, hz)
            zx.run_ticks(nxt - zx.t28)
            h, v = ref.int_beam(timing, hz)
            self.assertEqual(zx.vc_ula, v, f'{timing} {hz} Hz: ulat:548-556 (§2.3)')
            self.assertIn(zx.hc_ula, (h, h + 1), f'{timing} {hz} Hz: the pixel after the match')

    def test_disabled_ula_interrupt_makes_no_pulse(self):
        zx = bare()
        pulses(self, zx, 2, at_least=1)                 # enabled, it pulses
        zx.nr_write(0x22, 0x04)                         # b2: ULA interrupt off
        n = len(zx.int_log)
        zx.run_frames(3)
        self.assertEqual(len(zx.int_log), n, 'ulat:551 i_inten_ula_n')


@needs_next
class LineInterrupt(NextCase):
    """§2.4: the line interrupt fires as the ULA finishes the line before."""

    def line_starts(self, zx, frames=3):
        return [s for s, e in pulses(self, zx, frames, since=len(zx.int_log))]

    def test_place(self):
        for line in (0, 1, 100, 191, 300):
            zx = bare(timing='48k')
            zx.nr_write(0x22, 0x06 | (line >> 8))       # ULA INT off, line INT on, MSB
            zx.nr_write(0x23, line & 0xFF)
            starts = self.line_starts(zx)
            F = ref.frame_ticks('48k', 50)
            self.assertEqual({b - a for a, b in zip(starts, starts[1:])}, {F},
                             f'line {line}: once a frame, and no ULA pulse')
            zx.run_ticks(starts[-1] + F - zx.t28)
            h, v = ref.line_int_beam('48k', 50, line)
            self.assertEqual(zx.vc_ula, v, f'line {line}: ulat:561-583')
            self.assertIn(zx.hc_ula, (h, h + 1))

    def test_offset_moves_it(self):
        zx = bare(timing='48k')
        zx.nr_write(0x64, 10)
        zx.nr_write(0x22, 0x06)
        zx.nr_write(0x23, 100)
        starts = self.line_starts(zx)                   # the offset applies at row 0
        zx.run_ticks(starts[-1] + ref.frame_ticks('48k', 50) - zx.t28)
        self.assertEqual(zx.vc_ula, ref.line_int_beam('48k', 50, 100, offset=10)[1],
                         'cvc = vc_ula + NR 0x64 (ulat:455-472)')

    def test_nr22_bit7_is_any_pulse_now(self):
        zx = bare(timing='48k')
        zx.nr_write(0x22, 0x06)
        zx.nr_write(0x23, 50)
        starts = self.line_starts(zx)
        zx.run_ticks(starts[-1] + ref.frame_ticks('48k', 50) + 8 - zx.t28)
        self.assertEqual(zx.nr_read(0x22) & 0x80, 0x80, 'zxnext:5899 not pulse_int_n (§9 D-3)')
        zx.run_ticks(400)
        self.assertEqual(zx.nr_read(0x22) & 0x80, 0x00, 'pulse over')
        h, v = ref.int_beam('48k', 50)                  # the disabled ULA INT's place
        L = ref.TIMINGS[('48k', 50)][0]
        now = zx.vc_ula * L + zx.hc_ula
        zx.run_ticks(((v * L + h - now) % (L * 312) + 2) * 4)
        self.assertEqual(zx.nr_read(0x22) & 0x80, 0x00, 'never for a disabled source (§9 D-3)')


@needs_next
class Waits(NextCase):
    """§1.4: at 28 MHz one wait on every memory read; Strobe confirmed the
    counts from t80n.vhd. None at 14 MHz or below."""

    def clocks(self, speed, body, setup=b'', reps=REPS, mmu=None):
        zx = bare(speed=speed)
        for slot, page in (mmu or {}).items():
            zx.nr_write(0x50 + slot, page)
        code, s, e = program(setup, body, reps)
        dt, dc, q, v = run_block(zx, CODE, code, CODE + s, CODE + e)
        return dc / reps

    def test_28_mhz(self):
        ld_hl = [0x21, 0x00, 0xC0]                      # LD HL,C000h (page 0, SRAM)
        self.assertEqual(self.clocks(3, [0x00]), 5, 'NOP: 4 + 1 (zxnext:3128-3140)')
        self.assertEqual(self.clocks(3, [0x7E], ld_hl), 9, 'LD A,(HL): 4+1, 3+1')
        self.assertEqual(self.clocks(3, [0x77], ld_hl), 8, 'LD (HL),A: writes never wait')

    def test_28_mhz_bank_5_reads_wait_too(self):
        self.assertEqual(self.clocks(3, [0x7E], [0x21, 0x00, 0x40]), 9,
                         'cpu_bank5_sched (zxnext:3135)')

    def test_28_mhz_bank_7_block_ram_reads_do_not(self):
        self.assertEqual(self.clocks(3, [0x7E], [0x21, 0x00, 0xC0], mmu={6: 0x0E}), 8,
                         'page 0x0E: no SRAM request, no bank-5 schedule (§1.4)')

    def test_28_mhz_unmapped_reads_do_not(self):
        self.assertEqual(self.clocks(3, [0x7E], [0x21, 0x00, 0xE0], mmu={7: 0xE0}), 8,
                         'page >= 0xE0 in slots 2-7: no request (zxnext:3019-3020)')

    def test_slower_speeds_have_no_waits(self):
        ld_hl = [0x21, 0x00, 0xC0]
        for speed in (0, 1, 2):
            self.assertEqual(self.clocks(speed, [0x00]), 4, f'NOP at speed {speed}')
            self.assertEqual(self.clocks(speed, [0x7E], ld_hl), 7, f'LD A,(HL) at speed {speed}')


@needs_next
class SpeedChange(NextCase):
    """§1.3: the effective speed changes only between bus cycles."""

    SELECT_7 = [0x01, 0x3B, 0x24, 0x3E, 0x07, 0xED, 0x79,   # LD BC,243Bh; LD A,7; OUT (C),A
                0x01, 0x3B, 0x25]                        # LD BC,253Bh

    def switch(self, start_speed, new):
        zx = bare(speed=start_speed)
        code = bytes([0xF3] + self.SELECT_7 + [0x3E, new])   # LD A,new
        s = len(code)
        code += bytes([0xED, 0x79]) + bytes(60) + bytes([0x18, 0xFE])   # S: OUT (C),A; NOPs
        zx.load(CODE, code)
        launch(zx, CODE)
        stops = []
        for a in (CODE + s, CODE + s + 2, CODE + s + 12, CODE + s + 62):
            assert zx.run_until_pc(a, max_ticks=10**6)
            stops.append(zx.t28)
        return stops

    def test_up_to_28_mhz(self):
        s, n1, n10, n60 = self.switch(0, 3)
        self.assertGreaterEqual(n1 - s, 12 * 8, 'OUT (C),A is all at 3.5 MHz: the change waits '
                                                'for an idle edge (zxnext:5713)')
        self.assertLessEqual(n1 - s, 12 * 8 + 16, 'and comes at the first one (allowing the '
                                                  'clock multiplexers a few ticks, top4:1005)')
        self.assertEqual(n60 - n10, 50 * 5, 'NOPs at 28 MHz: 5 ticks each (§1.4)')

    def test_down_to_3_5_mhz(self):
        s, n1, n10, n60 = self.switch(3, 0)
        self.assertGreaterEqual(n1 - s, 5 + 5 + 4, 'OUT (C),A at 28 MHz: two waited fetches, I/O')
        self.assertLessEqual(n1 - s, 5 + 5 + 4 + 8 + 16, 'then the 3.5 MHz clock (phase-locked)')
        self.assertEqual(n60 - n10, 50 * 32, 'NOPs at 3.5 MHz: 32 ticks each')


@needs_next
class Contention48(NextCase):
    """§1.5: 48K timing, 3.5 MHz, from every phase of the pattern."""

    TIMING = '48k'

    def check(self, setup, body, per, name, mmu=MMU0, regs=None, line=8, prefixes=range(8),
              reps=REPS, addr=CODE):
        L, N, *_ = ref.TIMINGS[(self.TIMING, 50)]
        for k in prefixes:
            zx = bare(timing=self.TIMING)
            for slot, page in enumerate(mmu):
                if page != MMU0[slot]:
                    zx.nr_write(0x50 + slot, page)
            if regs:
                zx.set_regs(**regs)
            code, s, e = program(setup, body, reps, prefix=k)
            dt, dc, q, v = run_block(zx, addr, code, addr + s, addr + e, self.TIMING, 50, line)
            events = [ev for i in range(reps) for ev in per(addr + s + i * len(body))]
            want = ref.Contention(self.TIMING, mmu, L, N).run(q, v, events)
            self.assertEqual(dt, 8 * want, f'{name}, prefix {k}, from hc_ula {q} row {v}: '
                                           f'{dt} ticks, the ULA rule says {8 * want}')
            plain = sum(e[1] if e[0] != 'io' else 4 for e in per(addr + s)) * reps
            if any(ref.Contention(self.TIMING, mmu, L, N).mem(e[1] if e[0] == 'io' else e[0] or 0)
                   for e in per(addr + s) if e[0] is not None):
                self.assertGreater(dt, 8 * plain, f'{name}: no contention at all')

    def test_reads(self):                               # LD A,(HL): pc:4, hl:3
        self.check([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E],
                   lambda pc: [(pc, 4), (0x4000, 3)], 'LD A,(HL) from bank 5')

    def test_writes(self):                              # LD (HL),A: pc:4, hl:3
        self.check([0x21, 0x00, 0x58, 0x01, 0x00, 0x80], [0x77],
                   lambda pc: [(pc, 4), (0x5800, 3)], 'LD (HL),A to bank 5')

    def test_internal_cycles_by_address(self):         # INC HL with I = 40h: pc:4, ir:1 x2
        self.check([0x01, 0x00, 0x80], [0x23], lambda pc: [(pc, 4), (0x4000, 1), (0x4000, 1)],
                   'INC HL, IR in bank 5', regs={'i': 0x40})

    def test_fetches_from_bank_5(self):                # NOPs in bank 5: pc:4 each
        self.check([], [0x00], lambda pc: [(pc, 4)], 'NOPs in bank 5 (slot 5 = page 0Ah)',
                   mmu=[0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x0A, 0x00, 0x01], prefixes=[0, 1],
                   addr=0xA100)

    def test_io_four_cases(self):                       # OUT (n),A: pc:4, pc+1:3, the I/O cycle
        for hi, lo in [(0x40, 0xFE), (0x80, 0xFE), (0x40, 0xFF), (0x80, 0xFF)]:
            port = hi << 8 | lo
            self.check([0x3E, hi, 0x01, 0x00, 0x80], [0xD3, lo],
                       lambda pc, port=port: [(pc, 4), (pc + 1, 3), ('io', port)],
                       f'OUT ({lo:02X}h),A with A = {hi:02X}h')

    def test_one_ula_port_access_from_every_phase(self):
        """Speccy-Zone's point via Tally: the port term holds through the whole
        window (ioreqtw3_n registered on the stretched clock, zxula.vhd:589-592),
        visible only to a single access timed from each phase."""
        for hi in (0x80, 0x40):
            port = hi << 8 | 0xFE
            self.check([0x3E, hi, 0x01, 0x00, 0x80], [0xD3, 0xFE, 0x00],
                       lambda pc, port=port: [(pc, 4), (pc + 1, 3), ('io', port), (pc + 2, 4)],
                       f'one OUT (FEh),A with A = {hi:02X}h, then a NOP', reps=1)

    def test_contention_follows_the_page_not_the_address(self):
        self.check([0x21, 0x00, 0xC0, 0x01, 0x00, 0x80], [0x7E],
                   lambda pc: [(pc, 4), (0xC000, 3)], 'bank 5 at C000h (MMU6 = 0Ah)',
                   mmu=[0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x0A, 0x0B], prefixes=[0, 3])
        self.check([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E],
                   lambda pc: [(pc, 4), (0x4000, 3)], 'page 10h at 4000h: uncontended',
                   mmu=[0xFF, 0xFF, 0x10, 0x11, 0x04, 0x05, 0x00, 0x01], prefixes=[0, 3])

    def test_off_above_3_5_mhz(self):
        zx = bare(timing='48k', speed=1)
        code, s, e = program([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E], REPS)
        dt, *_ = run_block(zx, CODE, code, CODE + s, CODE + e, '48k', 50, 8)
        self.assertEqual(dt, 7 * REPS * 4, 'speed 01: no contention (zxnext:4422)')

    def test_off_by_nr08_bit6(self):
        zx = bare(timing='48k')
        zx.nr_write(0x08, 0x50)                         # b6: contention off (speaker kept)
        zx.run_frames(1)                                # copied in the right half of a line
        code, s, e = program([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E], REPS)
        dt, *_ = run_block(zx, CODE, code, CODE + s, CODE + e, '48k', 50, 8)
        self.assertEqual(dt, 7 * REPS * 8, 'NR 0x08 b6 (zxnext:5729-5731)')

    def test_none_under_pentagon_timing(self):
        zx = bare(timing='pentagon')
        code, s, e = program([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E], REPS)
        dt, *_ = run_block(zx, CODE, code, CODE + s, CODE + e, 'pentagon', 50, 8)
        self.assertEqual(dt, 7 * REPS * 8, 'zxnext:4422')


@needs_next
class Contention128(Contention48):
    """§1.5: 128K timing contends the odd banks, and 7FFD as the ULA's port."""

    TIMING = '128k'

    def test_odd_banks_at_c000(self):
        for bank in (1, 2, 3, 7):
            mmu = MMU0[:6] + [bank * 2, bank * 2 + 1]
            self.check([0x21, 0x00, 0xC0, 0x01, 0x00, 0x80], [0x7E],
                       lambda pc: [(pc, 4), (0xC000, 3)], f'LD A,(HL) from bank {bank}',
                       mmu=mmu, prefixes=[0, 5])

    def test_7ffd_is_contended_as_the_ula_port(self):  # OUT (C),A: pc:4, pc+1:4, I/O
        self.check([0x01, 0xFD, 0x7F, 0xAF], [0xED, 0x79],
                   lambda pc: [(pc, 4), (pc + 1, 4), ('io', 0x7FFD)],
                   'OUT (C),A to 7FFD (zxnext:4437, 2553)')

    def test_1ffd_is_not(self):
        self.check([0x01, 0xFD, 0x1F, 0xAF], [0xED, 0x79],
                   lambda pc: [(pc, 4), (pc + 1, 4), ('io', 0x1FFD)],
                   'OUT (C),A to 1FFD: port_7ffd excludes it (zxnext:2552)')


@needs_next
class ContentionP3(NextCase):
    """§1.5: +3 timing has no I/O contention at all (zxula.vhd:599; cl:3.01.05)."""

    def test_out_is_never_contended(self):
        for hi, lo in [(0x40, 0xFE), (0x80, 0xFE), (0x40, 0xFF), (0x80, 0xFF)]:
            for k in range(8):
                zx = bare()                             # +3 timing
                code, s, e = program([0x3E, hi, 0x01, 0x00, 0x80], [0xD3, lo], REPS, prefix=k)
                dt, *_ = run_block(zx, CODE, code, CODE + s, CODE + e, 'p3', 50, 8)
                self.assertEqual(dt, 11 * REPS * 8, f'OUT ({lo:02X}h),A, A = {hi:02X}h, '
                                                    f'prefix {k}: +3 contends memory only')

    def test_memory_in_banks_4_to_7_is_delayed(self):
        zx = bare()
        code, s, e = program([0x21, 0x00, 0x40, 0x01, 0x00, 0x80], [0x7E], REPS)
        dt, *_ = run_block(zx, CODE, code, CODE + s, CODE + e, 'p3', 50, 8)
        self.assertGreater(dt, 7 * REPS * 8, '+3: WAIT on bank 5 reads (zxula.vhd:600)')


@needs_next
class FloatingBus(NextCase):
    """§2.5: port 0xFF floats in 48K/128K timing; nothing else does."""

    def screen(self, timing):
        zx = bare(timing=timing)
        for i in range(0x1800):
            zx.bram5[i] = 0x5A
        for i in range(0x1800, 0x1B00):
            zx.bram5[i] = 0xA5
        return zx

    def sample_line(self, zx, timing, line, port=0x40FF):
        L, N, *_ = ref.TIMINGS[(timing, 50)]
        goto_line(zx, timing, 50, line)
        for _ in range(L * N * ref.TICKS_PER_PIXEL):
            if zx.vc_ula == line:
                break
            zx.run_ticks(1)
        else:
            self.fail(f'the beam never reached row {line} in a frame (vc_ula stuck at {zx.vc_ula})')
        seen = []
        for _ in range(L * ref.TICKS_PER_PIXEL):
            seen.append(zx.io_in(port))
            zx.run_ticks(1)
        return seen

    def test_pixel_area_shows_screen_bytes(self):
        for timing in ('48k', '128k'):
            seen = set(self.sample_line(self.screen(timing), timing, 20))
            self.assertLessEqual(seen, {0x5A, 0xA5, 0xFF}, f'{timing}: zxula.vhd:305-346')
            self.assertTrue({0x5A, 0xA5} <= seen, f'{timing}: bitmap and attribute both float')

    def test_border_floats_ff(self):
        seen = set(self.sample_line(self.screen('48k'), '48k', 200))
        self.assertEqual(seen, {0xFF}, 'border_active_ula (zxula.vhd:312-315)')

    def test_only_port_ff_floats(self):
        seen = set(self.sample_line(self.screen('48k'), '48k', 20, port=0x40F7))
        self.assertEqual(seen, {0xFF}, 'every other unanswered port reads FF (§9 D-12)')

    def test_no_floating_bus_under_p3_or_pentagon_timing(self):
        for timing in ('p3', 'pentagon'):
            seen = set(self.sample_line(self.screen(timing), timing, 20))
            self.assertEqual(seen, {0xFF}, f'{timing}: zxnext:4454')


if __name__ == '__main__':
    unittest.main()
