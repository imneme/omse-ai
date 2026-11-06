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


@needs_next
class Burst(NextCase):
    """Burst mode (WR4 b6:5 = 10): in WAITING_CYCLES the DMA lets go of BUSRQ while the prescaler is still due
    (dma:449-455). From READ_1 at E0: the WRITE_4 decision at E6 starts the wait, E7 lets go, BusReq_s follows at
    E8, E9 releases the bus with the CPU's next T1. The wait ends at E(4P+2) (32P t28 at 8 a clock) into
    START_DMA (BUSRQ was let go), which asks at E(4P+3); BusReq_s at E(4P+4); with NOPs the CPU's T_Res edges are
    E9 + 4m, so the grant is at E(4P+5) and the next READ_1 at E(4P+6). The CPU is frozen 10 edges a byte."""

    def test_burst_gives_the_cpu_the_waits(self):
        for presc in (2, 3, 7):
            with self.subTest(presc=presc):
                n = 6
                zx = bare()
                data = bytes(range(40, 40 + n))
                io, dma, clocks, t28 = run_enabled(zx, regs(n, presc=presc, mode=2), data, nops=400)
                tw, cw = io[0][:2]
                period = 4 * presc + 6
                want = []
                for i in range(n):
                    want += expected_copy(cw, tw, 1, first=7 + period * i, src=SRC + i, dst=DST + i,
                                          data=data[i:])
                self.assertEqual(dma, want)
                self.assertEqual(clocks, 7 + 11 + 4 * 400 + 10 * n)

    def test_continuous_keeps_the_bus_through_the_waits(self):
        # the same transfer in continuous mode: WAITING_CYCLES -> WAITING_ACK with the bus held (dma:457-462)
        n, presc = 6, 3
        zx = bare()
        io, dma, clocks, t28 = run_enabled(zx, regs(n, presc=presc, mode=1), bytes(n), nops=400)
        reads = [e[1] for e in dma if e[2] == 'mr']
        self.assertEqual([b - a for a, b in zip(reads, reads[1:])], [4 * presc + 3] * (n - 1))
        # frozen from the grant (7 clocks after the write, at e8) to the release: the last byte's wait ends at
        # E(4P+2), FINISH at +1, IDLE lets go at +2, BusReq_s at +3, released at +4
        frozen = 1 + (4 * presc + 3) * (n - 1) + (4 * presc + 2) + 4
        self.assertEqual(clocks, 7 + 11 + 4 * 400 + frozen)


@needs_next
class Interrupts(NextCase):
    """Giving the bus back (zxnext:1960-1968): im2_dma_delay is set while an im2 device whose DMA interrupt is
    enabled (NR 0xCC-0xCE) is pending or in service, and held through im2_control's RETI states. A WRITE_4 that
    sees it goes to START_DMA, which lets go of BUSRQ until it clears (dma:270-280, 420-425).

    RETI, from its T1 at r0: ED's T4 edge (r3) enters S_ED_T4, 4D's (r7) S_ED4D_T4, then S_SRL_T1 (r8),
    S_SRL_T2 (r9), S_0 (r10) (im2c). The device is idle again by then, so im2_dma_delay clears at r11, START_DMA
    asks at r12, BusReq_s at r13, and the grant is RETI's own T_Res at r14: the DMA's next read is stamped just
    before r15, before the CPU fetches anything after the RETI."""
    HANDLER, I_REG = 0x9200, 0x90

    def setup(self, c0=0xA1, cc=0x01, n=20000):
        zx = bare()
        zx.nr_write(0xC0, c0)                           # hardware IM2, vectors 101xxxx0
        zx.nr_write(0xCC, cc)                           # b0: the ULA's interrupt delays the DMA
        program(zx, regs(n, src=0xC000, dst=DST, b_inc=2))
        code = [0xF3, 0x3E, self.I_REG, 0xED, 0x47, 0xED, 0x5E, 0xFB, 0x3E, 0x87, 0xD3, 0x6B, 0x18, 0xFE]
        zx.load(CODE, bytes(code))                      # DI; LD I,90h; IM 2; EI; OUT (6Bh),87h; JR $
        vec = self.I_REG << 8 | (c0 & 0xE0) | 11 << 1   # the ULA is device 11 (zxnext:1958)
        zx.poke(vec, self.HANDLER & 0xFF)
        zx.poke(vec + 1, self.HANDLER >> 8)
        zx.load(self.HANDLER, bytes([0xFB, 0xED, 0x4D]))   # EI; RETI
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        zx.dma_log(True)
        return zx

    def test_im2_interrupt_takes_the_bus_and_reti_gives_it_back(self):
        n = 20000
        zx = self.setup(n=n)
        reti = self.HANDLER + 1
        stops = []
        while len(stops) < 2:
            assert zx.run_until_pc(reti, max_ticks=4 * 10**6), 'no interrupt was served'
            if zx.dma_events:                           # (one before the transfer began doesn't count)
                stops.append((zx.cpu_clocks, len(zx.dma_events)))
            zx.run_ticks(8)
        zx.run_ticks(8 * 6 * n)
        dma = zx.dma_events
        reads = [e for e in dma if e[2] == 'mr']
        self.assertEqual([e[3] for e in reads], [(0xC000 + i) & 0xFFFF for i in range(n)])   # none lost or doubled
        for s, k in stops:
            nxt = dma[k]                                # the first event after the RETI's T1
            self.assertEqual((nxt[1], nxt[2]), (s + 15, 'mr'))
            self.assertGreater(nxt[1] - dma[k - 1][1], 15)   # and a real pause before it
        self.assertFalse(zx.busak)

    def test_a_prescaled_continuous_transfer_never_gives_way(self):
        # a due prescaler sends WRITE_4 to WAITING_CYCLES before the delay is looked at, and continuous mode leaves
        # WAITING_CYCLES for WAITING_ACK with the bus held (dma:432-462): the interrupt waits for the block
        n, presc = 700, 25
        zx = bare()
        zx.nr_write(0xC0, 0xA1)
        zx.nr_write(0xCC, 0x01)
        program(zx, regs(n, src=0xC000, dst=DST, b_inc=2, presc=presc))
        code = [0xF3, 0x3E, self.I_REG, 0xED, 0x47, 0xED, 0x5E, 0xFB, 0x3E, 0x87, 0xD3, 0x6B, 0x18, 0xFE]
        zx.load(CODE, bytes(code))
        vec = self.I_REG << 8 | 0xA0 | 11 << 1
        zx.poke(vec, self.HANDLER & 0xFF)
        zx.poke(vec + 1, self.HANDLER >> 8)
        zx.load(self.HANDLER, bytes([0xFB, 0xED, 0x4D]))
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        zx.dma_log(True)
        period = 4 * presc + 3
        self.assertFalse(zx.run_until_pc(self.HANDLER, max_ticks=8 * period * (n - 10)))   # past a frame's INT
        zx.run_ticks(8 * period * 20)
        reads = [e[1] for e in zx.dma_events if e[2] == 'mr']
        self.assertEqual(len(reads), n)
        self.assertEqual(set(b - a for a, b in zip(reads, reads[1:])), {period})
        self.assertTrue(zx.run_until_pc(self.HANDLER, max_ticks=10**6))           # and then it's served

    def test_without_the_enable_the_transfer_runs_on(self):
        n = 20000
        zx = self.setup(cc=0x00, n=n)
        zx.run_ticks(8 * (6 * n + 400))
        reads = [e[1] for e in zx.dma_events if e[2] == 'mr']
        self.assertEqual(len(reads), n)
        self.assertEqual(set(b - a for a, b in zip(reads, reads[1:])), {6})

    def test_pulse_mode_never_delays(self):
        n = 20000
        zx = self.setup(c0=0xA0, n=n)                   # NR 0xC0 b0 = 0: pulse mode, no device states
        zx.run_ticks(8 * (6 * n + 400))
        reads = [e[1] for e in zx.dma_events if e[2] == 'mr']
        self.assertEqual(set(b - a for a, b in zip(reads, reads[1:])), {6})

    def test_nmi_takes_the_bus_with_nr_cc_b7(self):
        # (nmi_activated and NR 0xCC b7) sets im2_dma_delay (zxnext:1966); RETN's im2_control states hold it
        # (S_ED45_T4, S_SRL_T1, S_SRL_T2) exactly as RETI's do, so the DMA's next read is stamped at RETN's T1 + 15
        for cc, pauses in ((0x80, True), (0x00, False)):
            with self.subTest(cc=cc):
                n = 3000
                zx = bare()
                zx.nr_write(0x03, 0x03)                 # out of config mode (no NMI in it, zxnext:2063)
                zx.nr_write(0x06, zx.nr_read(0x06) | 0x08)   # the M1 button's NMI on (zxnext:2049)
                zx.nr_write(0xCC, cc)
                zx.sram[0x14066:0x14068] = bytes([0xED, 0x45])   # the multiface ROM (SRAM 0x14000): RETN at 0066
                program(zx, regs(n, src=0xC000, dst=DST, b_inc=2))
                code, end = enabler(nops=10)
                zx.load(CODE, code)
                launch(zx, CODE)
                assert zx.run_until_pc(CODE, max_ticks=10**6)
                zx.dma_log(True)
                zx.run_ticks(8 * 600)                   # well into the transfer
                zx.button('m1')
                if pauses:
                    assert zx.run_until_pc(0x0066, max_ticks=8 * 200)
                    s, k = zx.cpu_clocks, len(zx.dma_events)
                    zx.run_ticks(8 * 100)
                    nxt = zx.dma_events[k]
                    self.assertEqual((nxt[1], nxt[2]), (s + 15, 'mr'))
                else:
                    self.assertFalse(zx.run_until_pc(0x0066, max_ticks=8 * 6 * (n - 200)))
                zx.run_ticks(8 * 6 * n)
                reads = [e[3] for e in zx.dma_events if e[2] == 'mr']
                self.assertEqual(reads, [0xC000 + i for i in range(n)])


@needs_next
class SpiWait(NextCase):
    """dma_wait_n = z80_wait_n and spi_wait_n (zxnext:1803), spi_wait_n = state_idle or state_last_d (spi:177):
    while the SPI master is mid-byte, the DMA's READ_4/WRITE_4 waits, its strobe still up (dma_rw_cancel only
    with wait_n high, dma:146-155). Reading port 0xEB, the strobe that began a transfer is still there at state 15,
    so spi_begin (spi:82) starts a second one, and the DMA waits for that too: 34 clocks a byte, two transfers a
    byte, and each read returns the byte of the transfer before (the second of the previous pair)."""

    def test_reading_eb_waits_and_starts_two_transfers_a_byte(self):
        n = 5
        zx = bare()
        before = zx.spi_count
        io, dma, clocks, t28 = run_enabled(zx, regs(n, src=DST, dst=0x00EB, atob=False, b_io=True, b_inc=2),
                                           nops=400)
        tw, cw = io[0][:2]
        reads = [e for e in dma if e[2] == 'ir']
        writes = [e for e in dma if e[2] == 'mw']
        self.assertEqual([e[1] - cw for e in reads], [7 + 34 * i for i in range(n)])
        self.assertEqual([w[1] - r[1] for r, w in zip(reads, writes)], [18] * n)
        self.assertEqual(zx.spi_count - before, 2 * n)

    def test_writing_eb_sends_each_byte_twice(self):
        # memory -> 0xEB: the write's strobe, held through WRITE_4, begins the second transfer with the same byte
        # (oshift_r <= i_spi_mosi_dat, spi:95-99); the next READ_4 waits for it
        n = 4
        zx = bare()
        before = zx.spi_count
        io, dma, clocks, t28 = run_enabled(zx, regs(n, dst=0x00EB, b_io=True, b_inc=2), bytes(range(1, 9)),
                                           nops=400)
        tw, cw = io[0][:2]
        writes = [e for e in dma if e[2] == 'iw']
        self.assertEqual([e[1] - cw for e in writes], [10 + 34 * i for i in range(n)])
        self.assertEqual(zx.spi_count - before, 2 * n)


@needs_next
class Contention(NextCase):
    """What the ULA holds or waits for in a DMA cycle (zxula:586-600, on the muxed bus, zxnext:1786-1794). The
    DMA's strobes start on a falling edge (dma:146-155), after the ULA has decided its T-state, and by the next
    T-state mreq23_n/ioreqtw3_n have registered them. So a DMA cycle's first T-state is checked like a T1 (the
    memory term, if its address is contended), its later ones not, and a contended port's own term never comes:
    by the time IORQ is low, ioreqtw3_n is too. Under +3 timing the WAIT is MREQ low on a contended page, sampled
    on the falling edge and tested in READ_4/WRITE_4 (dma:140-145, 395-397, 412-414)."""

    def start_in_paper(self, zx, timing, line=40):
        import nextref as ref
        from test_next_timing import goto_line
        goto_line(zx, timing, 50, line)
        return ref.TIMINGS[(timing, 50)][:2]

    def test_a_contended_port_is_not_contended_for_the_dma(self):
        # 48K timing, the paper area: the CPU's OUT to FE would be held in its second T-state; the DMA's write
        # to 00FE is held nowhere (its address is in ROM's page, and the port's term needs ioreqtw3_n high)
        n = 64
        zx = bare(timing='48k')
        program(zx, regs(n, dst=0x00FE, b_io=True, b_inc=2))
        zx.load(SRC, bytes(i & 7 for i in range(n)))
        code, end = enabler(nops=200)
        zx.load(CODE, code)
        self.start_in_paper(zx, '48k')
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        zx.dma_log(True)
        assert zx.run_until_pc(end, max_ticks=10**7)
        stamps = [e[0] for e in zx.dma_events]
        self.assertEqual(len(stamps), 2 * n)
        self.assertEqual(set(b - a for a, b in zip(stamps[0::2], stamps[2::2])), {48})
        self.assertEqual(set(b - a for a, b in zip(stamps[0::2], stamps[1::2])), {24})

    def test_p3_wait_is_sampled_in_read_4(self):
        # +3 timing, 3-clock reads from bank 5 (contended): the window (Ratio's p3_wait_now: hc_ula + 1 at the edge
        # before the falling edge) is looked at from the edge entering READ_4, and again each clock it holds;
        # READ_3's falling edge counts for nothing. A byte drifts through every phase.
        n = 40
        zx = bare()
        program(zx, regs(n, src=0x4000))
        code, end = enabler(nops=400)
        zx.load(CODE, code)
        L, N = self.start_in_paper(zx, 'p3')
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        t0, pos0 = zx.t28, zx.vc_ula * L + zx.hc_ula
        zx.dma_log(True)
        assert zx.run_until_pc(end, max_ticks=10**7)
        dma = zx.dma_events

        def window(t):                                  # at the edge whose pre-edge t28 is t
            pos = (pos0 + (t - t0) // 4) % (L * N)
            v, h = pos // L, pos % L + 1
            adj = ((h & 15) + 1) & 15
            return (adj >= 4 or adj <= 1) and (h & 0x1FF) < 256 and v < 192

        t, want = dma[0][0], []
        for i in range(n):
            want.append((t, 'mr', 0x4000 + i))
            k = 0
            while window(t + 8 * (2 + k)):             # READ_4 entered 2 clocks after READ_1
                k += 1
            want.append((t + 8 * (3 + k), 'mw', DST + i))
            t += 8 * (6 + k)
        self.assertEqual([(e[0], e[2], e[3]) for e in dma], want)
        self.assertTrue(any(e[0] - d[0] > 48 for d, e in zip(dma[0::2], dma[2::2])), 'no byte waited at all')


@needs_next
class SpeedRule(NextCase):
    """The effective CPU speed follows NR 0x07 only on an edge where MREQ, IORQ and M1 are high and the DMA doesn't
    hold the bus (zxnext:5714, dma_holds_bus = BUSAK, 1784). Between a DMA write's WRITE_4 and the next READ_1 no
    strobe is low, so without the last term a speed change would land mid-transfer, and the DMA, clocked by the CPU
    clock, would speed up (Speccy-Zone's review)."""

    def test_a_speed_change_waits_for_the_dma_to_let_go(self):
        # the DMA itself writes 3 to NR 0x07, four times, through port 0x253B: every byte stays at 3.5 MHz (8 t28
        # a clock, 6 clocks a byte), and the change lands once the CPU has the bus again
        n = 4
        zx = bare()
        zx.io_out(0x243B, 0x07)
        io, dma, clocks, t28 = run_enabled(zx, regs(n, dst=0x253B, b_io=True, b_inc=2), bytes([3] * n))
        stamps = [e[0] for e in dma]
        self.assertEqual(len(stamps), 2 * n)
        self.assertEqual([b - a for a, b in zip(stamps, stamps[1:])], [24] * (2 * n - 1))
        self.assertEqual(zx.nr_read(0x07) >> 4 & 3, 3)


@needs_next
class Gaps(NextCase):
    """Behaviour Speccy-Zone's mutants found no test for (dma-mutants-run1-18fad66.log)."""

    def test_z80_mode_auto_restart_moves_one_more_every_block(self):
        # FINISH reloads the counter with FFFF in Z80-DMA mode too (dma:482-486): n + 1 bytes a block, every block
        n = 3
        zx = bare()
        data = bytes(range(50, 60))
        program(zx, regs(n, wr5=0xA2), port=0x0B)
        zx.load(SRC, data)
        code, end = enabler(port=0x0B)
        zx.load(CODE, code)
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        zx.io_log(True)
        zx.dma_log(True)
        zx.run_ticks(8 * 150)
        tw, cw = zx.io_events[0][:2]
        want = []
        for b in range(4):
            want += expected_copy(cw, tw, n + 1, data=data, first=7 + (6 * (n + 1) + 2) * b)
        self.assertEqual(zx.dma_events[:len(want)], want)

    def test_wr0_with_bits_1_0_equal_to_10_is_still_wr0(self):
        # WR0 is any base byte with b7 = 0 and b1:0 not 00 (dma:514); 10 and 11 "behave like transfer"
        n = 4
        zx = bare()
        w = regs(n)
        w[1] = (w[1] & 0xFC) | 0x02
        io, dma, clocks, t28 = run_enabled(zx, w, bytes(range(1, 9)))
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n, data=bytes(range(1, 9))))

    def test_c3_puts_both_ports_back_to_three_clocks(self):
        # WR6 C3 sets both timing bytes to 01 (dma:640-641): 2-clock timings written before it don't survive
        n = 3
        zx = bare()
        io, dma, clocks, t28 = run_enabled(zx, [0x54, 0x02, 0x50, 0x02] + regs(n), bytes(range(1, 9)))
        tw, cw = io[0][:2]
        self.assertEqual(dma, expected_copy(cw, tw, n, 3, 3, data=bytes(range(1, 9))))

    def test_48k_the_write_after_a_contended_port_read_is_checked_like_a_t1(self):
        # keyboard port 00FE -> bank 5 (contended under 48K timing), in the paper. The read's address is in ROM's
        # page and its port term never comes; by WRITE_1 the I/O strobe was cancelled at READ_4's falling edge, so
        # ioreqtw3_n and mreq23_n are high and WRITE_1 gets the memory term: held as the ULA holds a T1 there
        import nextref as ref
        from test_next_timing import goto_line
        n = 24
        zx = bare(timing='48k')
        program(zx, regs(n, src=0x4000, dst=0x00FE, atob=False, b_io=True, b_inc=2))
        code, end = enabler(nops=300)
        zx.load(CODE, code)
        L, N = ref.TIMINGS[('48k', 50)][:2]
        goto_line(zx, '48k', 50, 40)
        launch(zx, CODE)
        assert zx.run_until_pc(CODE, max_ticks=10**6)
        t0, pos0 = zx.t28, zx.vc_ula * L + zx.hc_ula
        zx.dma_log(True)
        assert zx.run_until_pc(end, max_ticks=10**7)
        dma = zx.dma_events
        cont = ref.Contention('48k', [0, 0, 10, 11, 4, 5, 0, 1], L, N)

        def held(t):                                    # a check in the T-state that begins at the edge after t28 t
            pos = (pos0 + (t - t0) // 4) % (L * N)
            return cont.holds(pos % L + 1, pos // L)

        t, want = dma[0][0], []
        for i in range(n):
            want.append((t, 'ir', 0x00FE))
            w = t + 24
            want.append((w, 'mw', 0x4000 + i))
            t = w + 8 * (3 + held(w))
        self.assertEqual([(e[0], e[2], e[3]) for e in dma], want)
        self.assertTrue(any(held(e[0]) for e in dma if e[2] == 'mw'), 'no write was held at all')
