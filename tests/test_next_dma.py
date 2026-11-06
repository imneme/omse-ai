"""The Next's zxnDMA (the builder's tests, Kelp Fern).

From device/dma.vhd (core 3.02.02, by Victor Trucco and Alvin Albrecht), its
wiring in zxnext.vhd (zxnext:1732-1835, 2602, 2727-2728) and the T80N's bus
request (t80n.vhd:1645-1760, t80na.vhd:140-360), through DESIGN.md §9.1 (16).
Every expected number is worked out from the VHDL in the comments.

The edges, for an OUT (n),A that enables the DMA (WR6 0x87) followed by NOPs.
The I/O cycle is T1 (e0), the auto-wait (e1, still TState 1 in t80n.vhd
1781-1782), T2 (e2), T3 (e3). The strobe starts just after e1 (IORQ_t2,
t80na:349-356), which is where io_events stamps the write (Cw, after the
edge). The DMA first sees it at e2 (cs_wr_v = "10") and enters START_DMA.
At e3 START_DMA drops BUSRQ. At e4 the T80N's BusReq_s takes it, too late
for e4's T_Res, so the CPU starts the NOP's M1 at e4. At e8, the NOP's T_Res,
the request is granted: BusAck, with the CPU frozen in its last T-state. At
e9 the DMA, in WAITING_ACK, sees BUSAK and enters TRANSFERING_READ_1: the
first read, stamped just before e9, so at cpu_clocks Cw + 7.

A byte then takes rl + wl clocks (each 2, 3 or 4 from the timing byte;
3 after a reset). After the last WRITE_4, FINISH_DMA (1), IDLE raises BUSRQ
(2), BusReq_s takes it (3), and the edge after that releases BUSAK and starts
the CPU's next M-cycle: the CPU is frozen for (rl + wl) * n + 5 edges.

Programs run from 0x8100 with data at 0x9000 and 0xA000 (pages 4 and 5,
uncontended under +3 timing, the default).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch                      # noqa: E402

CODE, SRC, DST = 0x8100, 0x9000, 0xA000
CLOCKS = {0: 4, 1: 3, 2: 2, 3: 4}     # a timing byte's b1:0 -> clocks (dma:312-316)


def regs(n, src=SRC, dst=DST, a_tim=None, b_tim=None, presc=None, mode=1, atob=True, a_io=False, b_io=False,
         a_inc=1, b_inc=1, wr5=None):
    """The register writes for a transfer of n bytes, A at src, B at dst, then LOAD: WR6 C3 (reset), WR0, WR1,
    WR2, WR4 (mode 0 byte, 1 continuous, 2 burst), WR5, WR6 CF. a_inc/b_inc: 1 increment, 0 decrement, 2 fixed."""
    out = [0xC3, 0x79 | (4 if atob else 0), src & 0xFF, src >> 8, n & 0xFF, n >> 8]
    wr1 = 0x04 | (8 if a_io else 0) | (a_inc << 4)
    out += [wr1] if a_tim is None else [wr1 | 0x40, a_tim]
    wr2 = 0x00 | (8 if b_io else 0) | (b_inc << 4)
    if presc is not None:
        out += [wr2 | 0x40, (1 if b_tim is None else b_tim) | 0x20, presc]
    else:
        out += [wr2] if b_tim is None else [wr2 | 0x40, b_tim]
    out += [0x8D | (mode << 5), dst & 0xFF, dst >> 8]
    if wr5 is not None:
        out += [wr5]
    return out + [0xCF]


def program(zx, writes, port=0x6B):
    for v in writes:
        zx.io_out(port, v)


def enabler(nops=200, port=0x6B):
    """LD A,87h; OUT (port),A; NOPs; JR $. Returns (code, end)."""
    code = bytes([0x3E, 0x87, 0xD3, port] + [0x00] * nops + [0x18, 0xFE])
    return code, CODE + 4 + nops


def run_enabled(zx, writes, data=None, nops=200, port=0x6B, src=SRC):
    """Program the DMA with io_out, then run LD A,87h; OUT (port),A; NOPs from CODE with both logs on.
    Returns (io_events, dma_events, cpu_clocks from CODE to the end, t28 likewise)."""
    program(zx, writes, port)
    if data is not None:
        zx.load(src, data)
    code, end = enabler(nops, port)
    zx.load(CODE, code)
    launch(zx, CODE)
    assert zx.run_until_pc(CODE, max_ticks=10**6)
    c0, t0 = zx.cpu_clocks, zx.t28
    zx.io_log(True)
    zx.dma_log(True)
    assert zx.run_until_pc(end, max_ticks=10**7), 'never reached the end'
    return zx.io_events, zx.dma_events, zx.cpu_clocks - c0, zx.t28 - t0


def expected_copy(cw, tw, n, rl=3, wl=3, k=8, first=7, src=SRC, dst=DST, data=None, rkind='mr', wkind='mw',
                  src_step=1, dst_step=1):
    """The DMA's events for a copy whose enabling OUT was stamped (tw, cw): the first read `first` clocks after
    it (7: see the module's note), a byte every rl + wl clocks, k t28 to the clock. io_events' cpu_clocks counts
    the write's own edge and its t28 doesn't (nextcore's cpu_edge), so the OUT's edge itself is at t28 tw, and a
    DMA stamp r clocks after cw is r + 1 edges after it."""
    out = []
    for i in range(n):
        r = first + (rl + wl) * i
        v = data[i] if data is not None else None
        out.append((tw + k * (r + 1), cw + r, rkind, (src + src_step * i) & 0xFFFF, v))
        out.append((tw + k * (r + rl + 1), cw + r + rl, wkind, (dst + dst_step * i) & 0xFFFF, v))
    return out


def readback(zx, n=8, port=0x6B):
    return [zx.io_in(port) for _ in range(n)]


@needs_next
class Registers(NextCase):
    """The read-back (dma:895-1140): status 00E1101T, then the counter and the two ports' addresses by the read
    mask, in fixed wrap orders. io_out/io_in take no time (§9.1 (6))."""

    def test_power_on_reads(self):
        # after a reset: status E = 1 (endofblock_n), T = 0; counter 0; src and dest 0 (signals start at 0);
        # the mask 7F walks all seven and wraps to the status
        zx = bare()
        self.assertEqual(readback(zx), [0x3A, 0, 0, 0, 0, 0, 0, 0x3A])

    def test_load_then_read_everything(self):
        zx = bare()
        program(zx, regs(0x0123, src=0x9876, dst=0xA543) + [0xBB, 0x7F, 0xA7])
        # A -> B: port A reads src, port B dest (dma:995-1000); the counter loads 0 in zxn mode
        self.assertEqual(readback(zx), [0x3A, 0x00, 0x00, 0x76, 0x98, 0x43, 0xA5, 0x3A])

    def test_b_to_a_swaps_what_the_ports_read(self):
        zx = bare()
        program(zx, regs(0x10, src=0x9876, dst=0xA543, atob=False) + [0xA7])
        # B -> A: src = B's start, dest = A's; port A reads dest = A's start, port B src = B's start
        self.assertEqual(readback(zx, 7), [0x3A, 0, 0, 0x76, 0x98, 0x43, 0xA5])

    def test_read_mask_orders(self):
        zx = bare()
        program(zx, regs(0x10, src=0x9876, dst=0xA543))
        program(zx, [0xBB, 0x0A])               # counter lo and port A lo: the sequence starts at counter lo
        self.assertEqual(readback(zx, 5), [0x00, 0x76, 0x00, 0x76, 0x00])
        program(zx, [0xBB, 0x01])               # the status alone, for ever
        self.assertEqual(readback(zx, 3), [0x3A] * 3)
        program(zx, [0xBB, 0x00])               # nothing: the status (dma:880-882)
        self.assertEqual(readback(zx, 3), [0x3A] * 3)
        program(zx, [0xBB, 0x41])               # status, then B hi, then status (bit 0 is skipped only after it)
        self.assertEqual(readback(zx, 4), [0x3A, 0xA5, 0x3A, 0xA5])
        program(zx, [0xBB, 0x60, 0xBF])         # BF: read the status next, whatever the mask; then B lo
        self.assertEqual(readback(zx, 4), [0x3A, 0x43, 0xA5, 0x43])

    def test_z80_mode_loads_minus_one(self):
        zx = bare()
        program(zx, regs(0x10, src=0x9876, dst=0xA543) + [0xA7], port=0x0B)
        self.assertEqual(readback(zx, 3, port=0x0B), [0x3A, 0xFF, 0xFF])   # "z80 dma loads -1" (dma:674-678)

    def test_wr4_with_only_b4_locks_the_write_sequencer(self):
        # WR4 b4 with b2, b3 clear enters R4_BYTE_2, which no case handles (dma:891): every later write is ignored
        # (even WR6 C3) until a reset; reads go on
        zx = bare()
        program(zx, regs(0x10, src=0x1234) + [0xBB, 0x08, 0xA7])
        self.assertEqual(readback(zx, 2), [0x34, 0x34])
        program(zx, [0x91])
        program(zx, regs(0x10, src=0x5678) + [0xBB, 0x01, 0xA7])
        self.assertEqual(readback(zx, 2), [0x34, 0x34])
        zx.reset()
        program(zx, regs(0x10, src=0x5678) + [0xBB, 0x08, 0xA7])
        self.assertEqual(readback(zx, 2), [0x78, 0x78])


@needs_next
class Copies(NextCase):
    """Memory to memory, every byte stamped, at each speed and cycle length."""
    DATA = bytes((i * 37 + 11) & 0xFF for i in range(256))

    def copy(self, n, speed=0, **kw):
        zx = bare(speed=speed)
        io, dma, clocks, t28 = run_enabled(zx, regs(n, **kw), self.DATA)
        return zx, io, dma, clocks

    def test_copy_at_3m5(self):
        n = 16
        zx, io, dma, clocks = self.copy(n)
        self.assertEqual(len(io), 1)
        tw, cw, port, v, rw = io[0]
        self.assertEqual((port, v, rw), (0x876B, 0x87, 'w'))
        self.assertEqual(dma, expected_copy(cw, tw, n, data=self.DATA))
        self.assertEqual(bytes(zx.read(DST, n + 1)), self.DATA[:n] + b'\x00')
        # LD A,n (7) + OUT (n),A (11) + 200 NOPs, and the CPU frozen 6n + 5 edges
        self.assertEqual(clocks, 7 + 11 + 4 * 200 + 6 * n + 5)

    def test_copy_at_each_speed(self):
        # 8 >> speed t28 to the clock; at 28 MHz the NOP after the OUT reads SRAM and waits a clock (ref §1.4), so
        # its T_Res, and the grant, come an edge later; the DMA's own reads, 3 clocks, don't feel the wait
        for speed in (1, 2, 3):
            with self.subTest(speed=speed):
                n = 10
                zx, io, dma, clocks = self.copy(n, speed)
                tw, cw = io[0][:2]
                self.assertEqual(dma, expected_copy(cw, tw, n, k=8 >> speed, first=8 if speed == 3 else 7,
                                                    data=self.DATA))
                base = (7 + 11 + 4 * 200) if speed < 3 else (9 + 13 + 5 * 200)
                self.assertEqual(clocks, base + 6 * n + 5)

    def test_every_cycle_length(self):
        for at in range(4):
            for bt in range(4):
                with self.subTest(a_tim=at, b_tim=bt):
                    n = 3
                    zx, io, dma, clocks = self.copy(n, a_tim=at, b_tim=bt)
                    tw, cw = io[0][:2]
                    rl, wl = CLOCKS[at], CLOCKS[bt]
                    self.assertEqual(dma, expected_copy(cw, tw, n, rl, wl, data=self.DATA))
                    self.assertEqual(clocks, 7 + 11 + 4 * 200 + (rl + wl) * n + 5)

    def test_two_clock_reads_wait_at_28_mhz(self):
        # sram_wait_n (zxnext:3130-3137) follows cpu_rd_n, which is the DMA's while it has the bus: low for the
        # clock after READ_1, so a 2-clock read's READ_4 samples it and waits once; 3 clocks, nothing
        n = 4
        zx, io, dma, clocks = self.copy(n, speed=3, a_tim=2, b_tim=2)
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n, 3, 2, k=1, first=8, data=self.DATA))

    def test_two_clock_cycles_at_14_mhz_dont_wait(self):
        # "Avoid wait state for 14MHz" (dma:157-161): the strobe stretched through READ_4 and the byte latched on
        # the rising edge; nothing waits, so 2 + 2
        n = 4
        zx, io, dma, clocks = self.copy(n, speed=2, a_tim=2, b_tim=2)
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n, 2, 2, k=2, data=self.DATA))

    def test_decrement_and_fixed(self):
        n = 5
        zx, io, dma, clocks = self.copy(n, src=0x9010, dst=0xA020, a_inc=0, b_inc=2)
        tw, cw = io[0][:2]
        data = [self.DATA[0x10 - i] for i in range(n)]
        self.assertEqual(dma, expected_copy(cw, tw, n, src=0x9010, dst=0xA020, src_step=-1, dst_step=0, data=data))
        self.assertEqual(zx.peek(0xA020), data[-1])

    def test_zxn_length_zero_moves_one_byte(self):
        # WRITE_4 tests counter < len after WRITE_1's increment: len 0 still moves the first byte (dma:418)
        zx, io, dma, clocks = self.copy(0)
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, 1, data=self.DATA))

    def test_z80_mode_moves_one_more(self):
        # through port 0x0B the counter loads FFFF (dma:674-678), so len + 1 bytes move
        n = 6
        zx = bare()
        io, dma, clocks, t28 = run_enabled(zx, regs(n), self.DATA[:n + 1], port=0x0B)
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n + 1, data=self.DATA))
        self.assertEqual(clocks, 7 + 11 + 4 * 200 + 6 * (n + 1) + 5)
        program(zx, [0xBB, 0x07, 0xA7], port=0x0B)
        self.assertEqual(readback(zx, 3, port=0x0B), [0x1A, n, 0])

    def test_status_and_addresses_after(self):
        # FINISH clears endofblock_n; IDLE clears atleastone every clock (dma:264): 00 0 1101 0
        n = 16
        zx, io, dma, clocks = self.copy(n)
        program(zx, [0xBB, 0x7F, 0xA7])
        self.assertEqual(readback(zx), [0x1A, n, 0, (SRC + n) & 0xFF, (SRC + n) >> 8, (DST + n) & 0xFF,
                                        (DST + n) >> 8, 0x1A])

    def test_busak(self):
        zx = bare()
        program(zx, regs(100))
        code, end = enabler()
        zx.load(CODE, code)
        launch(zx, CODE)
        assert zx.run_until_pc(CODE + 4, max_ticks=10**6)       # just before the NOP's M1 (e4)
        self.assertFalse(zx.busak)
        zx.run_ticks(8 * 4)                                      # e4-e7: the NOP
        self.assertFalse(zx.busak)
        zx.run_ticks(8)                                          # e8: granted
        self.assertTrue(zx.busak)
        assert zx.run_until_pc(end, max_ticks=10**7)
        self.assertFalse(zx.busak)

    def test_auto_restart(self):
        # WR5 b5: FINISH reloads and, still holding the bus, goes to WAITING_ACK (dma:477-494): a block every
        # 6n + 2 clocks, for ever, and the CPU never runs again
        n = 4
        zx = bare()
        program(zx, regs(n, wr5=0xA2))
        zx.load(SRC, self.DATA[:n])
        code, end = enabler()
        zx.load(CODE, code)
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        zx.io_log(True)
        zx.dma_log(True)
        zx.run_ticks(8 * 200)
        tw, cw = zx.io_events[0][:2]
        dma = zx.dma_events
        want = []
        for b in range(5):
            for e in expected_copy(cw, tw, n, data=self.DATA, first=7 + (6 * n + 2) * b):
                want.append(e)
        self.assertEqual(dma[:len(want)], want)
        self.assertTrue(zx.busak)


@needs_next
class Ports(NextCase):
    """Memory to port and port to memory: real bus cycles through the machine's decode (§9.1 (16))."""

    def test_memory_to_the_border(self):
        n = 8
        data = bytes([1, 2, 3, 4, 5, 6, 7, 2])
        zx = bare()
        io, dma, clocks, t28 = run_enabled(zx, regs(n, dst=0x00FE, b_io=True, b_inc=2), data)
        tw, cw = io[0][:2]
        self.assertEqual(len(io), 1)                             # DMA cycles never reach io_events
        self.assertEqual(dma, expected_copy(cw, tw, n, dst=0x00FE, dst_step=0, wkind='iw', data=data))
        self.assertEqual(zx.lib.zxn_border(zx.z), 2)

    def test_keyboard_to_memory(self):
        # B -> A: port B (I/O, fixed) at 7FFE, the half-row with SPACE; SPACE down reads E0 | 1E
        n = 4
        zx = bare()
        zx.set_keys([0, 0, 0, 0, 0, 0, 0, 0x01])
        io, dma, clocks, t28 = run_enabled(zx, regs(n, src=DST, dst=0x7FFE, atob=False, b_io=True, b_inc=2))
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n, src=0x7FFE, dst=DST, src_step=0, rkind='ir',
                                            data=[0xFE] * n))
        self.assertEqual(bytes(zx.read(DST, n)), b'\xFE' * n)


@needs_next
class Prescaler(NextCase):
    """WR2's prescaler (dma:432-447): after a byte's WRITE_4, wait while P > timer(13:5), the timer counting t28
    from READ_1 (it adds 8, 4, 2 or 1 a clock and clears in READ_1). WAITING_CYCLES then goes to WAITING_ACK
    (bus held, continuous) and READ_1 an edge later. With k t28 to the clock: the decision edge sees 4k t28
    (3 + 3 cycles), so it waits only if P > 4k/32; the wait ends at the first edge that sees 32P, and the next
    READ_1 is 32P/k + 3 clocks after the last."""

    def test_prescaled_period(self):
        for speed, presc in ((0, 2), (0, 5), (1, 3), (2, 1), (3, 1), (3, 7), (0, 1)):
            with self.subTest(speed=speed, presc=presc):
                k = 8 >> speed
                waits = presc > (4 * k) // 32
                period = 32 * presc // k + 3 if waits else 6
                n = 5
                zx = bare(speed=speed)
                io, dma, clocks, t28 = run_enabled(zx, regs(n, presc=presc), nops=400)
                reads = [e for e in dma if e[2] == 'mr']
                self.assertEqual([b[1] - a[1] for a, b in zip(reads, reads[1:])], [period] * (n - 1))
                self.assertEqual([b[0] - a[0] for a, b in zip(reads, reads[1:])], [period * k] * (n - 1))


if __name__ == '__main__':
    unittest.main()
