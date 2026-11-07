"""The Next's floating bus as an IN sees it: which byte the CPU takes, and when.

Written from the VHDL (core 3.02.02), independent of nextcore.cpp's code:
- The ULA's floating_bus_r loads on the falling 7 MHz edge in slots 9, B, D
  and F of each 16-pixel group (pixel 2G, attribute 2G, pixel 2G+1, attribute
  2G+1), and FFh in slot 1; FFh in the border (zxula.vhd:308-345, 573). Which
  cell each slot holds follows from the shift register's loads (zxula:368-401):
  sload_0 at slot C shows pbyte00, sload_1 at slot 4 shows pbyte10.
- cpu_di is that register, combinationally, for port 0xFF at 48K and 128K
  timing (zxnext:1830-1832, 2772, 4454).
- The T80N latches DI on CLK_n's falling edge while TState = 3 (t80na:214-221);
  with IOWait = 1 an I/O cycle is T1, T1 again, T2, T3 (t80n:1781-1783), so the
  byte is taken at the falling edge inside the I/O cycle's fourth T-state.
- CLK_CPU at 3.5 MHz is high in odd hc_ula and low in even; a held T-state
  stays high until an odd slot where o_cpu_contend is clear (zxnext_top_issue4
  994-1002 with zxnext:1569's hc(0)). A port whose high byte is in a contended
  page is checked on every T-state of its I/O cycle (mem_contend is by address,
  zxnext:4430; mreq23_n is high through it, zxula:587-595), with wait_s in slots
  3-14 of the first 256 pixels of the 192 rows (zxula:582-583).
So the byte is the register at the start of the even hc where that fourth
T-state falls. Where the hc counter and the CPU clock change on the same 7 MHz
edge, the latch is taken to see the counter from before the edge, the house
convention; at the line's last group that's a convention, not a reading, and a
beam-synchronised probe on Melissa's Next could settle it.

Each IN's start comes from a run_until_pc stop (§9.1 (11): T1 is hc_ula + 1),
so the only thing the model supplies is where its instructions begin.
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402
from test_next_regs import needs_next, NextCase, bare   # noqa: E402
from test_next_timing import launch, goto_line          # noqa: E402
from test_next_bus import bus_on                        # noqa: E402

CODE = 0x8100
OUT = 0x9000                        # page 4, uncontended under every timing
N = 300
BODY = bytes([0xED, 0x78, 0x77, 0x23])  # IN A,(C); LD (HL),A; INC HL: 12 + 7 + 6 = 25 T
PAD = bytes([0x1E, 0x00])               # LD E,0 (7 T): 0-7 of them after each IN, from a fixed random sequence, so every
                                        # phase comes round, even where contention pulls the loop into step with the ULA
                                        # after each hold (a regular i % 8 met one timing's line in step or the other's,
                                        # and then no IN in the window began in slot 1, the one that floats a byte)
PADS = (lambda r: [r.randrange(8) for _ in range(N)])(random.Random(1))
WAITS = (lambda r: [r.randrange(4) for _ in range(N)])(random.Random(2))   # a bus device's waits on each IN


def screen():
    """A screen whose every byte differs from its neighbours and is never FFh,
    and a second one that differs from it at every place."""
    a = bytes(((o * 7) + 3) % 255 for o in range(0x1800)) + bytes(((o * 13) + 1) % 255 for o in range(0x300))
    b = bytes(((o * 7) + 103) % 255 for o in range(0x1800)) + bytes(((o * 13) + 101) % 255 for o in range(0x300))
    return a, b


class Beam:
    """hc_ula and vc_ula as one count from the frame's start, for a timing."""

    def __init__(self, timing):
        self.L, self.N, *_ = ref.TIMINGS[(timing, 50)]

    def split(self, t):
        t %= self.L * self.N
        return t % self.L, t // self.L

    def wait_s(self, t):
        h, v = self.split(t)
        return (((h & 15) + 1) & 15) >= 4 and h < 256 and v < 192

    def byte(self, scr, e):
        """The floating bus at the start of even count e: floating_bus_r as the
        load at the odd slot before it left it, gated by the border there."""
        h, v = self.split(e - 1)
        if h >= 256 or v >= 192:
            return 0xFF
        g, s = h >> 4, h & 15
        if s not in (9, 11, 13, 15):
            return 0xFF
        c = 2 * g + (s >= 13)
        if s in (11, 15):
            return scr[0x1800 + (v >> 3) * 32 + c]
        return scr[((v & 0xC0) << 5) | ((v & 7) << 8) | ((v & 0x38) << 2) | c]

    def latch(self, t1, held, waits=0):
        """The even count where an I/O cycle's last T-state falls, its T1
        rising at odd count t1; held: the port's page is contended; waits:
        T-states the bus's WAIT holds the T80N in T2 (t80n:1738)."""
        t = t1
        for k in range(4 + waits):
            while held and self.wait_s(t):
                t += 2
            if k < 3 + waits:
                t += 2
        return t + 1


def program(port):
    """The code, the offset of each IN, and the offset of the JR $ after them."""
    code = bytes([0xF3, 0x3E, 0x00, 0xED, 0x47,         # DI; LD A,0; LD I,A (internal T-states uncontended)
                  0x01, port & 0xFF, port >> 8,          # LD BC,port
                  0x21, OUT & 0xFF, OUT >> 8])           # LD HL,OUT
    ins = []
    for i in range(N):
        ins.append(len(code))
        code += BODY + PAD * PADS[i]
    return code + bytes([0x18, 0xFE]), ins, len(code)


def run(timing, port, nr08=None, shadow=False, contention=True, waits=False):
    """The N bytes the INs took, and the N bytes the VHDL says they take.
    waits: the expansion bus on, port FF propagated to it (NR 0x8A b4), and a
    device holding WAIT for WAITS[i] T-states in IN i's I/O cycle."""
    zx = bare(timing=timing)
    if waits:
        bus_on(zx)
        zx.nr_write(0x8A, 0x10)
    a, b = screen()
    for i, v in enumerate(a):
        zx.bram5[i] = v
    for i, v in enumerate(b):
        zx.bram7[i] = v
    if shadow:
        zx.io_out(0x7FFD, 0x08)
    if nr08 is not None:
        zx.nr_write(0x08, nr08)
    code, ins, end = program(port)
    zx.load(CODE, code)
    goto_line(zx, timing, 50, 20)                        # 300 x about 50 T: rows 20 to about 90
    launch(zx, CODE)
    beam = Beam(timing)
    held = contention and nr08 is None and (port >> 8) in range(0x40, 0x80)   # bank 5's pages at 4000-7FFF
    want = []
    for i in range(N):
        assert zx.run_until_pc(CODE + ins[i], max_ticks=10**7)
        t = zx.vc_ula * beam.L + zx.hc_ula + 1           # the IN's first fetch's T1
        w = WAITS[i] if waits else 0
        if waits:
            zx.run_ticks(8 * 6 + 4)                      # past the second fetch's bus cycle, so the waits are the I/O's
            zx.bus_wait(w)
        want.append(beam.byte(b if shadow else a, beam.latch(t + 16, held, w)))   # two 4-T fetches, then I/O
    assert zx.run_until_pc(CODE + end, max_ticks=10**7)
    return zx.read(OUT, N), bytes(want)


@needs_next
class FloatingIn(NextCase):
    def check(self, got, want, what, least=N // 8):
        bad = [(i, got[i], want[i]) for i in range(N) if got[i] != want[i]]
        self.assertEqual(bad[:6], [], f'{what}: {len(bad)} of {N} INs took another byte (index, got, want)')
        self.assertGreaterEqual(sum(x != 0xFF for x in want), least, f'{what}: too few reads saw the screen to mean anything')

    def test_an_uncontended_port_ff_takes_the_byte_at_t3s_fall(self):
        # port 00FF: page 0's ROM, never contended: the byte 3.5 T after the I/O cycle begins
        self.check(*run('48k', 0x00FF), '48K, port 00FF')

    def test_a_contended_high_byte_takes_it_after_the_holds(self):
        # port 40FF: bank 5's page, checked on all four I/O T-states. Held, the latch lands in slot 2 (FFh) unless
        # the I/O cycle began in slot 1, so only about one IN in eight inside the window floats a byte
        self.check(*run('48k', 0x40FF), '48K, port 40FF', least=10)

    def test_with_contention_off_nothing_is_held(self):
        # NR 0x08 bit 6, as NextZXOS sets it (D-12's photo: NR 0x08 = DE)
        self.check(*run('48k', 0x40FF, nr08=0x40), '48K, port 40FF, NR 0x08 b6')

    def test_128k_timing(self):
        self.check(*run('128k', 0x00FF), '128K, port 00FF')
        self.check(*run('128k', 0x40FF), '128K, port 40FF', least=10)

    def test_a_device_holding_wait_moves_the_latch(self):
        # the bus's WAIT is ORed into the CPU's (zxnext:1798): each wait keeps the T80N in T2 a T-state longer, and the
        # latch in T3 comes that much later (z80.h repeats its waiting step, and the byte follows it)
        self.check(*run('48k', 0x00FF, waits=True), '48K, port 00FF, bus waits')

    def test_the_shadow_screen(self):
        self.check(*run('128k', 0x00FF, shadow=True), '128K, port 00FF, 7FFD b3')


if __name__ == '__main__':
    unittest.main()
