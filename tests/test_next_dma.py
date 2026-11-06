"""The Next's zxnDMA (device/dma.vhd), through DESIGN.md §9.1 (16) only.

Programmed as a program would, through port 0x6B (or 0x0B, Z80-DMA mode);
watched through dma_events (one per DMA bus cycle, stamped just before the
edge that enters TRANSFERING_READ_1 or TRANSFERING_WRITE_1), busak, memory,
and the port's own read-back. Written from the VHDL by Loam Fern, without
reading the builder's code.

Facts used (dma.vhd, 3.02.02):
- Reset (dma:211-244): both ports' timing 3 clocks, prescaler 0, continuous,
  no auto-restart, read mask 7Fh, status 00E1101T = 3Ah, counter 0.
- A byte is a read cycle with the source port's timing and a write cycle with
  the destination's: 2, 3 or 4 clocks for timing bits 10, 01, 00 (11 is 4)
  (dma:307-324, 359-378). No I/O wait states of the Z80's kind.
- WRITE_1 counts and steps both addresses (inc 01, dec 00, fixed 1x;
  dma:359-399); WRITE_4 goes on while counter < length (dma:426), so a
  block of 0 or 1 moves one byte, and Z80 mode (counter loaded with FFFFh,
  dma:667) one more.
- IDLE clears T every clock (dma:265), so a finished block reads 1Ah.
- A DMA cycle can't reach the DMA's own port (zxnext:2727-2728).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch                      # noqa: E402
from test_next_interrupts import main_loop, vector, CODE, F48  # noqa: E402
from test_next_copper import load as load_copper, WAIT as copper_wait, MOVE as copper_move  # noqa: E402
from test_next_copper import NEVER as COPPER_NEVER  # noqa: E402

ZXN, Z80 = 0x6B, 0x0B
DEC, INC, FIXED = 0, 1, 2
BYTE, CONTINUOUS, BURST = 0, 1, 2
T2, T3, T4 = 0b10, 0b01, 0b00                           # timing bytes
A, B = 0x9000, 0xA100                                   # page 4 and page 5 (bank 2): SRAM, uncontended
COUNTING_LOOP = bytes([0xF3, 0x23, 0x18, 0xFD])         # DI; L: INC HL; JR L


def pattern(n, seed=11):
    return bytes((i * 37 + seed) & 0xFF for i in range(n))


def program(zx, a, b, n, ab=True, a_mode=INC, b_mode=INC, a_io=False, b_io=False,
            a_t=None, b_t=None, pre=None, mode=CONTINUOUS, restart=False, port=ZXN,
            enable=True):
    """Disable, WR0-WR5, LOAD and (unless told not to) ENABLE, as io_out writes
    (dma:509-735). a and b are port A's and port B's addresses; ab=True is A -> B."""
    out = [0x83, 0x7D if ab else 0x79, a & 0xFF, a >> 8, n & 0xFF, n >> 8]
    out.append(0x04 | a_io << 3 | a_mode << 4 | (a_t is not None) << 6)
    if a_t is not None:
        out.append(a_t)
    more = b_t is not None or pre is not None
    out.append(0x00 | b_io << 3 | b_mode << 4 | more << 6)
    if more:
        out.append((T3 if b_t is None else b_t) | (pre is not None) << 5)
        if pre is not None:
            out.append(pre)
    out += [0x8D | mode << 5, b & 0xFF, b >> 8, 0x82 | restart << 5, 0xCF]
    if enable:
        out.append(0x87)
    for v in out:
        zx.io_out(port, v)


def reads(zx, n, port=ZXN, restart=True):
    """n reads of the read sequence, from its start if restart (WR6 A7h)."""
    if restart:
        zx.io_out(port, 0xA7)
    return [zx.io_in(port) for _ in range(n)]


def machine(**kw):
    """bare, the CPU in a loop counting in HL (so its progress shows)."""
    zx = bare(**kw)
    zx.load(0x8000, COUNTING_LOOP)
    zx.set_regs(pc=0x8000, sp=0x7FF0, hl=0)
    return zx


def cycles(events):
    return [(k, a, v) for _, _, k, a, v in events]


@needs_next
class Registers(NextCase):

    def test_status_and_read_sequence_at_power_on(self):
        zx = machine()
        got = reads(zx, 8, restart=False)
        self.assertEqual(got[:3], [0x3A, 0x00, 0x00],
                         'status 00E1101T with E=1 T=0, then the counter, 0 (dma:241-244, 902)')
        self.assertEqual(got[7], 0x3A, 'mask 7Fh: seven items, then the status again (dma:239)')

    def test_read_mask_picks_and_orders_the_items(self):
        zx = machine()
        zx.write(A, pattern(5))
        program(zx, A, B, 5)
        zx.run_ticks(20000)
        for mask, want, why in [
                (0x06, [0x05, 0x00, 0x05, 0x00], 'counter low, high, again'),
                (0x01, [0x1A, 0x1A, 0x1A], 'status only'),
                (0x18, [0x05, 0x90, 0x05], 'port A low, high, again'),
                (0x60, [0x05, 0xA1, 0x05], 'port B low, high, again'),
                (0x00, [0x1A, 0x1A], 'no bits: the status (dma:859-891)'),
                (0x7E, [0x05, 0x00, 0x05, 0x90, 0x05, 0xA1, 0x05], 'no status: counter first')]:
            zx.io_out(ZXN, 0xBB)
            zx.io_out(ZXN, mask)
            self.assertEqual(reads(zx, len(want), restart=False), want,
                             f'mask {mask:02X}h: {why} (dma:859-891, 900-1125)')
        zx.io_out(ZXN, 0xBB)
        zx.io_out(ZXN, 0x06)
        zx.io_in(ZXN)
        self.assertEqual(reads(zx, 1), [0x05], 'A7h starts the sequence again (dma:694-722)')

    def test_wr4_with_only_bit_4_locks_the_register_writes(self):
        """WR4 with b4 set and b2, b3 clear sends the write sequence to
        R4_BYTE_2 (dma:607-608), whose case is commented out (dma:835-857), so
        `when others => null` (dma:891) keeps it there: every later write is
        lost, C3h included, until a reset (dma:229). Reads still answer.
        (Found by Tally's second-sources reader; checked in the VHDL.)"""
        zx = machine()
        zx.write(A, pattern(4))
        zx.write(B, bytes(4))
        zx.io_out(ZXN, 0x91)
        zx.io_out(ZXN, 0xC3)
        zx.dma_log(True)
        program(zx, A, B, 4)
        zx.run_ticks(20000)
        self.assertEqual(zx.dma_events, [], 'nothing written after 91h reaches the DMA')
        self.assertEqual(zx.read(B, 4), bytes(4))
        self.assertEqual(reads(zx, 3, restart=False), [0x3A, 0x00, 0x00], 'reads still answer')
        zx.reset()
        zx.load(0x8000, COUNTING_LOOP)
        zx.set_regs(pc=0x8000, sp=0x7FF0, hl=0)
        zx.dma_log(True)
        program(zx, A, B, 4)
        zx.run_ticks(20000)
        self.assertEqual(zx.read(B, 4), pattern(4), 'a reset frees it')

    def test_reset_command(self):
        zx = machine()
        zx.write(A, pattern(4))
        program(zx, A, B, 4)
        zx.run_ticks(20000)
        self.assertEqual(reads(zx, 1), [0x1A], 'a finished block')
        zx.io_out(ZXN, 0xC3)
        self.assertEqual(reads(zx, 1), [0x3A], 'C3h: E=1, T=0 (dma:637-646)')

    def test_reinitialise_status(self):
        zx = machine()
        zx.write(A, pattern(4))
        program(zx, A, B, 4)
        zx.run_ticks(20000)
        self.assertEqual(reads(zx, 1), [0x1A], 'ended: E=0; and T=0, IDLE clears it (dma:265)')
        zx.io_out(ZXN, 0x8B)
        self.assertEqual(reads(zx, 1), [0x3A], '8Bh: E=1, T=0 (dma:690-692)')


@needs_next
class Transfers(NextCase):

    def test_memory_to_memory_a_to_b(self):
        zx = machine()
        p = pattern(16)
        zx.write(A, p)
        zx.write(B, bytes(16))
        zx.dma_log(True)
        program(zx, A, B, 16)
        zx.run_ticks(20000)
        self.assertEqual(zx.read(B, 16), p, 'the block copied')
        self.assertEqual(zx.read(A, 16), p, 'the source untouched')
        want = [c for i in range(16) for c in [('mr', A + i, p[i]), ('mw', B + i, p[i])]]
        self.assertEqual(cycles(zx.dma_events), want, 'one read then one write per byte, in order')
        self.assertFalse(zx.busak, 'the bus given back at the end')
        self.assertEqual(reads(zx, 7), [0x1A, 16, 0, 0x10, 0x90, 0x10, 0xA1],
                         'status ended; counter 16; port A (the source) and B one past the block')

    def test_b_to_a_decrementing_into_a_fixed_address(self):
        zx = machine()
        p = pattern(16, seed=3)
        zx.write(B, p)
        zx.write(A, bytes([0xEE, 0xEE]))
        zx.dma_log(True)
        program(zx, A, B + 15, 16, ab=False, a_mode=FIXED, b_mode=DEC)
        zx.run_ticks(20000)
        want = [c for i in range(16) for c in [('mr', B + 15 - i, p[15 - i]), ('mw', A, p[15 - i])]]
        self.assertEqual(cycles(zx.dma_events), want, 'B -> A: B counts down, A stays')
        self.assertEqual(zx.read(A, 2), bytes([p[0], 0xEE]), 'the last byte read is the one left')
        self.assertEqual(reads(zx, 7), [0x1A, 16, 0, 0x00, 0x90, 0xFF, 0xA0],
                         'port A is the destination now (fixed); port B one below the block')

    def test_block_lengths(self):
        for length, port, n in [(0, ZXN, 1), (1, ZXN, 1), (5, ZXN, 5),
                                (0, Z80, 1), (1, Z80, 2), (5, Z80, 6)]:
            with self.subTest(length=length, port=f'{port:02X}h'):
                self.assertEqual(ref.dma_block_bytes(length, port == Z80), n)
                zx = machine()
                zx.write(A, pattern(8))
                zx.write(B, bytes([0xEE] * 8))
                zx.dma_log(True)
                program(zx, A, B, length, port=port)
                zx.run_ticks(20000)
                self.assertEqual(sum(1 for e in zx.dma_events if e[2] == 'mw'), n,
                                 f'length {length} through port {port:02X}h moves {n}')
                self.assertEqual(zx.read(B, 8), pattern(8)[:n] + bytes([0xEE] * (8 - n)))
                count = n if port == ZXN else n - 1
                self.assertEqual(reads(zx, 3, port=port)[1:], [count & 0xFF, count >> 8],
                                 'the counter counts up from 0 (or FFFFh in Z80 mode)')

    def test_continue_goes_on_from_where_it_stopped(self):
        zx = machine()
        p = pattern(8)
        zx.write(A, p)
        zx.dma_log(True)
        program(zx, A, B, 4)
        zx.run_ticks(20000)
        self.assertEqual(reads(zx, 1), [0x1A])
        zx.io_out(ZXN, 0xD3)
        self.assertEqual(reads(zx, 3), [0x3A, 0, 0], 'D3h: E=1 and the counter cleared (dma:670-676)')
        zx.io_out(ZXN, 0x87)
        zx.run_ticks(20000)
        self.assertEqual([(k, a) for k, a, v in cycles(zx.dma_events) if k == 'mw'],
                         [('mw', B + i) for i in range(8)], 'the addresses carried on')
        self.assertEqual(zx.read(B, 8), p)

    def test_auto_restart_reloads_the_addresses(self):
        zx = machine()
        zx.write(A, pattern(3))
        zx.dma_log(True)
        program(zx, A, B, 3, restart=True, pre=8, mode=BURST)  # burst: the CPU gets to stop it
        for _ in range(200000):
            zx.run_ticks(1)
            if len(zx.dma_events) >= 20 and not zx.busak:
                break
        zx.io_out(ZXN, 0x83)
        got = [a for k, a, v in cycles(zx.dma_events) if k == 'mr']
        self.assertGreaterEqual(len(got), 10, 'more than three blocks')
        self.assertEqual(got, [A + i % 3 for i in range(len(got))], 'each block from the start again')
        n = len(zx.dma_events)
        zx.run_ticks(20000)
        self.assertEqual(len(zx.dma_events), n, '83h stops it')

    def test_the_dma_cannot_program_itself(self):
        zx = machine()
        zx.write(A, bytes([0x83] * 8))                  # "disable", eight times
        zx.dma_log(True)
        program(zx, A, ZXN, 8, b_mode=FIXED, b_io=True)
        zx.run_ticks(20000)
        self.assertEqual([k for k, a, v in cycles(zx.dma_events)], ['mr', 'iw'] * 8,
                         'all eight written to port 6Bh, none reaching the DMA (zxnext:2727-2728)')
        self.assertEqual(reads(zx, 1), [0x1A], 'and the block ended normally')


@needs_next
class IOCycles(NextCase):

    def test_memory_to_a_port(self):
        zx = machine()
        p = pattern(4, seed=0x40)
        zx.write(A, p)
        zx.io_out(0x243B, 0x7F)                         # NR 7Fh, the user register
        zx.dma_log(True)
        program(zx, A, 0x253B, 4, b_mode=FIXED, b_io=True)
        zx.run_ticks(20000)
        ev = zx.dma_events
        self.assertEqual(cycles(ev), [c for i in range(4) for c in
                                      [('mr', A + i, p[i]), ('iw', 0x253B, p[i])]])
        self.assertEqual(zx.nr_read(0x7F), p[3], 'each write a real port write: NR 7Fh holds the last')
        self.assertEqual([b[1] - a[1] for a, b in zip(ev, ev[1:])], [3] * 7,
                         'three clocks each, I/O included: no automatic wait (dma:307-378)')

    def test_a_port_to_memory(self):
        zx = machine()
        zx.write(B, bytes(4))
        zx.io_out(0x243B, 0x00)                         # NR 00h, the machine ID: 0Ah
        zx.dma_log(True)
        program(zx, 0x253B, B, 4, a_mode=FIXED, a_io=True)
        zx.run_ticks(20000)
        self.assertEqual(cycles(zx.dma_events), [c for i in range(4) for c in
                                                 [('ir', 0x253B, 0x0A), ('mw', B + i, 0x0A)]])
        self.assertEqual(zx.read(B, 4), bytes([0x0A] * 4))


@needs_next
class Timing(NextCase):

    def intervals(self, zx):
        ev = zx.dma_events
        return [b[1] - a[1] for a, b in zip(ev, ev[1:])], [b[0] - a[0] for a, b in zip(ev, ev[1:])]

    def test_cycle_lengths_follow_each_ports_timing(self):
        for a_t, b_t in [(T2, T2), (T3, T3), (T4, T4), (T2, T4), (T4, T2), (0b11, T3)]:
            for ab in (True, False):
                with self.subTest(a=a_t, b=b_t, ab=ab):
                    zx = machine()
                    zx.dma_log(True)
                    program(zx, A, B, 8, ab=ab, a_t=a_t, b_t=b_t)
                    zx.run_ticks(20000)
                    r = ref.DMA_TIMING[a_t if ab else b_t]
                    w = ref.DMA_TIMING[b_t if ab else a_t]
                    clocks, ticks = self.intervals(zx)
                    self.assertEqual(len(clocks), 15)
                    self.assertEqual(clocks, [r, w] * 7 + [r],
                                     f'reads with the source port\'s timing ({r}), writes with the '
                                     f'destination\'s ({w}) (dma:307-324, 359-378)')
                    self.assertEqual(ticks, [8 * c for c in clocks], '3.5 MHz, uncontended')

    def test_prescaler_in_continuous_mode(self):
        for speed, m in [(0, 8), (1, 4), (2, 2), (3, 1)]:
            for pre in (10, 40):
                with self.subTest(speed=speed, prescaler=pre):
                    zx = machine(speed=speed)
                    zx.dma_log(True)
                    program(zx, A, B, 4, pre=pre)
                    zx.run_ticks(4 * 32 * pre + 20000)
                    ev = [e for e in zx.dma_events if e[2] == 'mr']
                    self.assertEqual(len(ev), 4)
                    want = ref.dma_period(3, 3, pre, m)
                    self.assertEqual([b[1] - a[1] for a, b in zip(ev, ev[1:])], [want] * 3,
                                     f'{want} clocks from byte to byte (nextref.dma_period)')
                    self.assertEqual([b[0] - a[0] for a, b in zip(ev, ev[1:])],
                                     [32 * pre + 3 * m] * 3,
                                     '32 t28 a prescaler unit at any speed, plus three clocks')

    def test_port_timing_resets_keep_the_prescaler(self):
        """C7h and CBh reset only their port's timing (dma:647-651); only C3h
        clears the prescaler (dma:643). (The wiki says all three do: probe.)"""
        zx = machine()
        zx.dma_log(True)
        program(zx, A, B, 4, a_t=T2, b_t=T2, pre=10, enable=False)
        zx.io_out(ZXN, 0xC7)
        zx.io_out(ZXN, 0xCB)
        zx.io_out(ZXN, 0x87)
        zx.run_ticks(4 * 32 * 10 + 20000)
        ev = zx.dma_events
        self.assertEqual(len(ev), 8)
        self.assertEqual([b[1] - a[1] for a, b in zip(ev, ev[1:])][0::2], [3] * 4,
                         'reads back to 3 clocks')
        self.assertEqual([b[1] - a[1] for a, b in zip(ev[0::2], ev[2::2])], [ref.dma_period(3, 3, 10, 8)] * 3,
                         'and the prescaler still spaces the bytes')

    def test_the_prescaler_works_in_z80_mode_too(self):
        """dma:424 and 451 have no mode term. (The wiki says zxnDMA mode only: probe.)"""
        zx = machine()
        zx.dma_log(True)
        program(zx, A, B, 3, pre=10, port=Z80)
        zx.run_ticks(4 * 32 * 10 + 20000)
        ev = [e for e in zx.dma_events if e[2] == 'mr']
        self.assertEqual(len(ev), 4, 'Z80 mode: length + 1')
        self.assertEqual([b[1] - a[1] for a, b in zip(ev, ev[1:])], [ref.dma_period(3, 3, 10, 8)] * 3)

    def test_continuous_mode_keeps_the_bus(self):
        zx = machine()
        zx.dma_log(True)
        program(zx, A, B, 32)
        for _ in range(20000):
            if zx.dma_events:
                break
            zx.run_ticks(1)
        self.assertTrue(zx.dma_events, 'the transfer never began')
        hl = zx.regs()['hl']
        for _ in range(64 * 3 * 8 + 100):
            if len(zx.dma_events) >= 64:
                break
            self.assertTrue(zx.busak, f'busak dropped after {len(zx.dma_events)} cycles')
            zx.run_ticks(1)
        self.assertEqual(len(zx.dma_events), 64, 'all 32 bytes, three clocks a cycle')
        self.assertEqual(zx.regs()['hl'], hl, 'the CPU did nothing meanwhile')
        clocks, _ = self.intervals(zx)
        self.assertEqual(sum(clocks), 63 * 3, 'cpu_clocks counts on through the DMA\'s cycles')
        zx.run_ticks(20000)
        self.assertFalse(zx.busak)
        self.assertGreater(zx.regs()['hl'], hl, 'and the CPU runs again after')

    def test_burst_mode_gives_the_bus_back_while_it_waits(self):
        pre = 20
        zx = machine()
        zx.dma_log(True)
        program(zx, A, B, 6, pre=pre, mode=BURST)
        trace = []                                      # (events so far, busak, HL) after each tick
        for _ in range(6 * 32 * pre + 20000):
            zx.run_ticks(1)
            trace.append((len(zx.dma_events), zx.busak, zx.regs()['hl']))
            if trace[-1][0] == 12 and not zx.busak:
                break
        self.assertEqual(len(zx.dma_events), 12)
        for i in range(1, 6):                           # between byte i-1's write and byte i's read
            gap = [t for t in trace if t[0] == 2 * i]
            self.assertTrue(gap and not all(t[1] for t in gap),
                            f'busak low between bytes {i - 1} and {i} (dma:439-447)')
            self.assertNotEqual(gap[0][2], gap[-1][2], f'the CPU ran between bytes {i - 1} and {i}')
        ev = [e for e in zx.dma_events if e[2] == 'mr']
        least = 8 * (ref.dma_period(3, 3, pre, 8) + 1)
        for a, b in zip(ev, ev[1:]):
            self.assertTrue(least <= b[0] - a[0] <= least + 8 * 24,
                            f'byte to byte {b[0] - a[0]} t28: at least the continuous period and '
                            f'one more clock to ask for the bus ({least}), then the CPU\'s answer')

    def test_status_mid_block(self):
        zx = machine()
        zx.dma_log(True)
        program(zx, A, B, 4, pre=20, mode=BURST)
        for _ in range(4 * 32 * 20 + 20000):
            if len(zx.dma_events) >= 2 and not zx.busak:
                break
            zx.run_ticks(1)
        self.assertEqual(len(zx.dma_events), 2, 'one byte, then the bus given back to wait')
        self.assertEqual(reads(zx, 3), [0x3B, 1, 0], 'one byte done: E=1, T=1; counter 1')

    def test_28mhz_read_wait_reaches_the_dma(self):
        """zxnext:3131-3135: at 28 MHz an SRAM read's first clock after the strobe
        drops WAIT for one clock; the DMA samples WAIT on the falling edge and
        tests it in READ_4 (dma:139-145, 342). A 2-clock read is in READ_4
        by then and waits one clock; a 3-clock read is still in READ_3 and
        doesn't. Writes never wait."""
        for a_t, b_t, r, w in [(T2, T2, 3, 2), (T3, T3, 3, 3), (T4, T2, 4, 2), (T2, T4, 3, 4)]:
            with self.subTest(a=a_t, b=b_t):
                zx = machine(speed=3)
                zx.dma_log(True)
                program(zx, A, B, 6, a_t=a_t, b_t=b_t)
                zx.run_ticks(20000)
                clocks, ticks = self.intervals(zx)
                self.assertEqual(clocks, [r, w] * 5 + [r])
                self.assertEqual(ticks, clocks, '28 MHz: a t28 a clock')


ISR = bytes([0x3A, 0x00, 0x98, 0x3C, 0x32, 0x00, 0x98,   # LD A,(9800h); INC A; LD (9800h),A
             0xFB, 0xED, 0x4D])                           # EI; RETI (at 9208h)
BLOCK = 30000                                           # fixed to fixed: about 2.6 frames at 48K


@needs_next
class Interrupts(NextCase):
    """NEXT-MACHINE §6.6. In hardware IM2 mode a source whose bit is set in NR
    CC-CE drives im2_dma_int from its request until RETI (im2d:151;
    zxnext:1916-1917), which holds the DMA's delay (zxnext:1960-1967): the DMA
    gives the bus up after the byte under way (dma:426-428) and waits in
    START_DMA (dma:269-275); RETI's own states keep it waiting through the pops
    (im2c:184-189, 238). In pulse mode the IM2 devices are held in reset
    (im2p:105), so nothing but an NMI interrupts a transfer."""

    def setup(self, c0, cc):
        zx = bare(timing='48k')
        zx.nr_write(0x03, 0x00)                         # boot ROM off (see test_next_interrupts)
        zx.nr_write(0xC0, c0)
        zx.nr_write(0xCC, cc)
        loop = main_loop(zx, 2)
        zx.load(0x9200, ISR)
        vector(zx, 0x90, (c0 & 0xE0) | 11 << 1, 0x9200)  # the ULA's vector
        vector(zx, 0x90, 0xFF, 0x9200)                  # pulse mode's
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(0x9200, max_ticks=2 * F48), 'a first interrupt, DMA idle')
        self.assertTrue(zx.run_until_pc(loop, max_ticks=F48))   # back, nothing pending: the next
        zx.poke(0x9800, 0)                                      # one is about a frame away
        zx.dma_log(True)
        program(zx, 0xA000, 0xC000, BLOCK, a_mode=FIXED, b_mode=FIXED)
        return zx

    def test_an_enabled_im2_source_takes_the_bus_between_bytes(self):
        zx = self.setup(0xA1, 0x01)                     # hardware IM2; NR CC b0: the ULA
        self.assertTrue(zx.run_until_pc(0x9200, max_ticks=2 * F48), 'the ULA\'s handler')
        n = len(zx.dma_events)
        self.assertTrue(0 < n < 2 * BLOCK, f'entered mid-block ({n} cycles done)')
        self.assertEqual(n % 2, 0, 'between bytes')
        self.assertFalse(zx.busak)
        self.assertTrue(zx.run_until_pc(0x9208, max_ticks=F48))
        self.assertEqual(len(zx.dma_events), n, 'the DMA stays off the bus through the handler')
        for _ in range(4000):
            zx.run_ticks(1)
            if len(zx.dma_events) > n:
                break
        self.assertGreater(len(zx.dma_events), n, 'the DMA came back')
        self.assertEqual(zx.regs()['sp'], 0x7FF0, 'only after RETI\'s pops (im2c:184-189)')
        zx.run_ticks(4 * F48)
        self.assertEqual(len(zx.dma_events), 2 * BLOCK, 'and finished the block')
        self.assertGreaterEqual(zx.peek(0x9800), 2, 'every interrupt in the block served')

    def test_without_its_enable_the_interrupt_waits_for_the_block(self):
        zx = self.setup(0xA1, 0x00)
        self.assertTrue(zx.run_until_pc(0x9200, max_ticks=4 * F48))
        self.assertEqual(len(zx.dma_events), 2 * BLOCK, 'continuous mode kept the bus to the end')

    def nmi_setup(self, cc):
        """The multiface NMI raised by a copper MOVE to NR 02h mid-block (the CPU
        can't write it then: the DMA has the bus). It needs config mode left
        (zxnext:2061), NR 06h b3 (zxnext:2049, 5105) and the multiface enabled
        (NR 83h b1, FFh at power-on; zxnext:2374); its ROM (SRAM page 0Ah,
        zxnext:2989-2991) holds the handler, RETN, at 0066h."""
        zx = machine(timing='48k')
        zx.nr_write(0x03, 0x01)                         # leave config mode: a 48K
        zx.nr_write(0x06, zx.nr_read(0x06) | 0x08)
        zx.nr_write(0xCC, cc)
        for base in (0x14000, ref.ROM_SRAM[0]):         # the multiface's ROM, and ROM 0 should it not page in
            zx.sram[base + 0x66], zx.sram[base + 0x67] = 0xED, 0x45
        load_copper(zx, [copper_wait(100), copper_move(0x02, 0x08), COPPER_NEVER])
        zx.dma_log(True)
        program(zx, 0xA000, 0xC000, BLOCK, a_mode=FIXED, b_mode=FIXED)
        zx.nr_write(0x62, 0x40)                         # copper: run once from the start
        return zx

    def test_an_nmi_takes_the_bus_when_nr_cc_bit_7_says(self):
        """NR CC b7 lets nmi_activated hold the DMA's delay (zxnext:1966), in any
        interrupt mode; RETN's states keep it through the pops (im2c:238)."""
        zx = self.nmi_setup(0x80)
        self.assertTrue(zx.run_until_pc(0x0066, max_ticks=2 * F48), 'the NMI')
        n = len(zx.dma_events)
        self.assertTrue(0 < n < 2 * BLOCK, f'taken mid-block ({n} cycles done)')
        self.assertEqual(n % 2, 0, 'between bytes')
        self.assertFalse(zx.busak)
        for _ in range(4000):
            zx.run_ticks(1)
            if len(zx.dma_events) > n:
                break
        self.assertGreater(len(zx.dma_events), n, 'the DMA came back')
        self.assertEqual(zx.regs()['sp'], 0x7FF0, 'only after RETN\'s pops')
        zx.run_ticks(4 * F48)
        self.assertEqual(len(zx.dma_events), 2 * BLOCK, 'and finished the block')

    def test_without_nr_cc_bit_7_the_nmi_waits_for_the_block(self):
        zx = self.nmi_setup(0x00)
        self.assertTrue(zx.run_until_pc(0x0066, max_ticks=4 * F48), 'the NMI, in the end')
        self.assertEqual(len(zx.dma_events), 2 * BLOCK, 'continuous mode kept the bus to the end')

    def test_pulse_mode_never_interrupts_the_dma(self):
        zx = self.setup(0xA0, 0x01)                     # pulse mode, NR CC b0 set all the same
        self.assertTrue(zx.run_until_pc(0x9200, max_ticks=4 * F48))
        self.assertEqual(len(zx.dma_events), 2 * BLOCK, 'the IM2 devices are held in reset (im2p:105)')


@needs_next
class Contention(NextCase):
    MMU = [0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x00, 0x01]

    def block(self, timing, n=64, a_t=None, b_t=None):
        """A bank-5 to page-4 block started near row 40; returns (q, v, events),
        q the odd hc_ula of the first cycle's first clock."""
        L, N, *_ = ref.TIMINGS[(timing, 50)]
        zx = machine(timing=timing)
        zx.write(0x4000, pattern(n))
        assert zx.run_until_pc(0x8001, max_ticks=10**6)
        now = zx.vc_ula * L + zx.hc_ula
        zx.run_ticks(((40 * L - 30 - now) % (L * N)) * ref.TICKS_PER_PIXEL)
        assert zx.run_until_pc(0x8001, max_ticks=10**6)
        t0, h0, v0 = zx.t28, zx.hc_ula, zx.vc_ula
        zx.dma_log(True)
        program(zx, 0x4000, 0x8800, n, a_t=a_t, b_t=b_t)
        zx.run_ticks(60000)
        ev = zx.dma_events
        self.assertEqual(len(ev), 2 * n)
        self.assertEqual((ev[0][0] - t0) % (2 * ref.TICKS_PER_PIXEL), 0,
                         'a DMA cycle starts on a CPU edge')
        q, v = h0 + (ev[0][0] - t0) // ref.TICKS_PER_PIXEL + 1, v0   # §9.1 (11): pre-edge stamps
        while q >= L:
            q, v = q - L, v + 1
        self.assertTrue(30 <= v < 180, f'the block should start near row 40 (hc {q}, row {v})')
        self.assertEqual(zx.read(0x8800, n), pattern(n))
        return q, v, ev

    def test_reads_from_bank_5_are_contended_like_the_cpus(self):
        """48K timing at 3.5 MHz: the ULA holds the CPU clock, which clocks the
        DMA (NEXT-MACHINE §6.6). A DMA cycle's first clock has MREQ high at the
        last rising edge and its address already out (dma:285-299, 407-419), so
        it's checked like a T1: the CPU's contention model, event for event."""
        L, N, *_ = ref.TIMINGS[('48k', 50)]
        q, v, ev = self.block('48k')
        per = [c for i in range(64) for c in [(0x4000 + i, 3), (0x8800 + i, 3)]]
        want = [8 * ref.Contention('48k', self.MMU, L, N).run(q, v, per[:j]) for j in range(128)]
        got = [e[0] - ev[0][0] for e in ev]
        self.assertEqual(got, want, f'from hc_ula {q} row {v}')
        self.assertGreater(got[-1], 8 * 3 * 127, 'some contention')
        self.assertEqual([b[1] - a[1] for a, b in zip(ev, ev[1:])], [3] * 127,
                         'held clocks add no cpu_clocks')

    def test_p3_waits_on_the_falling_edge(self):
        """+3 timing: WAIT, not a held clock (zxula.vhd:600). The DMA samples it
        on the falling edge (dma:139-145), so an n-clock cycle starting at odd q
        looks at hc q + 2(n-1), one T-state off the CPU's sample: its pattern
        runs 7..0 from q = 15 mod 16 (nextref.p3_dma_run). Each wait is a clock."""
        L, N, *_ = ref.TIMINGS[('p3', 50)]
        mem = ref.P3Contention('p3', self.MMU, L, N).mem
        for a_t, b_t, r, w in [(None, None, 3, 3), (T2, T2, 2, 2), (T4, T2, 4, 2)]:
            with self.subTest(read=r, write=w):
                q, v, ev = self.block('p3', a_t=a_t, b_t=b_t)
                per = [c for i in range(64) for c in [(0x4000 + i, r), (0x8800 + i, w)]]
                want = [ref.p3_dma_run(q, v, per[:j], mem, L, N) for j in range(128)]
                got = [e[1] - ev[0][1] for e in ev]
                self.assertEqual(got, want, f'cpu_clocks from the first cycle, from hc_ula {q} row {v}')
                self.assertEqual([e[0] - ev[0][0] for e in ev], [8 * c for c in want],
                                 'a wait is a whole clock: no held clocks under +3')
                self.assertGreater(got[-1], (r + w) * 64 - w, 'some waits')


if __name__ == '__main__':
    unittest.main()
