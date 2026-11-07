"""Which byte an IN from port xxFF takes off the Next's floating bus, read from the VHDL (core 3.02.02).

A second reading for Speccy-Zone's fix (next-floating d0bf52d), written from the VHDL and her docstring's
citations only, never from her code (Hatch Fern, Sat 7 Nov 2026). The chain, as I read it:

The ULA's register (zxula.vhd:308-345). On CLK_7's falling edge, in the middle of hc's cycle: in the border
(border_active_ula = hc(8) or border_active_v, zxula:416) it loads FF and clears floating_bus_en; in the paper
it loads i_ula_vram_d in slots 9, B, D and F of each 16-hc group and FF (enable off) in slot 1. The fetch
(zxula:186-256, 270-300): px moves to column 2G in the middle of slot 3 and to 2G+1 in the middle of slot B;
each process sees i_hc as it stood before its edge, so the address set at the end of slot 7 is pixel 2G
(captured in slot 9), 9 is attribute 2G (B), B is pixel 2G+1 (D), D is attribute 2G+1 (F). Output
(zxula:573): the register when floating_bus_en and not border_active_ula, else FF (48K and 128K timing).

The CPU's byte (zxnext:1806-1845, 2672, 2768-2769, 4454): port FF (low byte FF, zxnext:2530) answers from
port_ff_dat_ula = the ULA's output at 48K and 128K timing (unless NR 0x08 b2 and NR 0x82 b0 select the
Timex register), combinationally into cpu_di. The T80N latches DI on CLK_n's falling edge while TState = 3
(t80na:214-221); an I/O M-cycle repeats T1 once (IOWait = 1, t80na:184; t80n:1706, 1781-1783), so the byte is
taken at the falling edge inside the I/O cycle's fourth T-state.

The clock (zxnext_top_issue4:994-1002; zxnext:1569): CLK_3M5_CONT is registered on CLK_7's rising edge, the
edge that steps hc: low after an odd hc unless o_cpu_contend, high after an even hc. So a T-state begins at an
odd hc, is high through it, and falls at the start of the next even hc unless held; a held T-state stays high
through pairs of slots until the end of an odd slot with contend clear. o_cpu_contend at 48K/128K timing
(zxula:577-595): mem_contend and mreq23_n and ioreqtw3_n and wait_s; for port xxFF (A0 = 1, not 7FFD/BF3B/FF3B)
contention_port is 0 (zxnext:4437), so ioreqtw3_n is 1; mreq23_n is MREQ registered on CLK_CPU's rise, and
MREQ is high from T4's falling edge through an I/O cycle (t80na:269-297), so every T-state of the I/O cycle,
T1 included, is checked; mem_contend is by the address's page (zxnext:4430: 48K bank 5, 128K odd banks 0-7).
wait_s (zxula:582-583) is 1 when (hc + 1) mod 16 >= 4, hc < 256, the line is paper and contention is on: at
the end of odd slots 3..13 a contended T-state is held, at the end of slots 15 and 1 it goes on.

The sample is taken on CPU clock edge that comes from a flip-flop clocked by the CLK_7 edge that also steps
hc, so a design meeting hold timing sees signals as they were before that edge: the byte is the register as
loaded in the middle of the odd slot before the falling edge, with border_active_ula from that slot. At
hc 255 -> 256 that gives attribute 31, not FF. (Speccy-Zone takes the same view as a house convention; this is
the reason I'd give for it.)
"""

LINE = {'48k': 448, '128k': 456}
LINES = {'48k': 312, '128k': 311}


def contended_page(page, timing):
    """mem_contend for an 8K page number (zxnext:4430-4434)."""
    if not isinstance(page, int) or page >> 4:
        return False
    if timing == '48k':
        return page >> 1 == 5
    return bool(page & 2)                     # 128K: odd 16K banks


def io_sample_edge(start, timing, port_contended, contention_on=True):
    """The absolute 7 MHz count (line * LINE + hc) of the even hc whose starting edge latches an IN A,(C)'s
    byte, for an instruction whose first T1 begins at odd absolute count start, its two opcode fetches
    uncontended."""
    L, N = LINE[timing], LINES[timing]

    def held(pos):                            # contend at the end of odd slot pos?
        if not (port_contended and contention_on):
            return False
        hc, vc = pos % L, (pos // L) % N
        return hc < 256 and vc < 192 and (hc + 1) % 16 >= 4

    pos = start + 16                          # ED and 78: two 4-T-state fetches, uncontended
    for t in range(4):                        # T1, T1 again, T2, T3
        while held(pos):
            pos += 2
        if t == 3:
            return pos + 1
        pos += 2


def floating_byte(edge, timing, pixel, attr):
    """The ULA's output just before the edge into even count edge. pixel(row, col) and attr(row // 8, col)
    give the screen's bytes."""
    L, N = LINE[timing], LINES[timing]
    h = edge - 1
    hc, vc = h % L, (h // L) % N
    if vc >= 192 or hc >= 256:
        return 0xFF
    k, s = divmod(hc, 16)
    if s == 9:
        return pixel(vc, 2 * k)
    if s == 11:
        return attr(vc >> 3, 2 * k)
    if s == 13:
        return pixel(vc, 2 * k + 1)
    if s == 15:
        return attr(vc >> 3, 2 * k + 1)
    return 0xFF
