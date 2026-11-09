# Z80NTIME on the test machine: the reading

*Strobe Fern, Fri 6 Nov 2026, from the photo (the photo, taken 07:44), read
against `z80ntime/build/expected.txt`. The tape: `z80ntime/build/Z80NTIME.TAP`, built by
`z80ntime/build_probe.py`.*

## What the machine says it is

`Z80NTIME core 3.02.02 id 0A` / `mmu 04 05 type 33 cpu 00/33`: core 3.02.02, machine id 0Ah (a Next), the code
in bank 2 (MMU4/5 = pages 4 and 5, uncontended), machine type 33h, CPU speed 3.5 MHz when the tape started (00)
and really 28 MHz when it asked (33: programmed 3, actual 3). Every condition the timing assumes held.

## The verdict line: `as VHDL: 36/36 12/12 7/8`

### 3.5 MHz: 36 of 36, every cell as the VHDL says

SWAPNIB, MIRROR, the five barrel shifts, MUL, ADD rr,A 8; TEST n 11; ADD rr,nn 16; PUSH nn 23; OUTINB 16;
NEXTREG r,v 20; NEXTREG r,A 17; PIXELDN, PIXELAD, SETAE 8; JP (C) 13; LDWS 14; LDIX (copying and skipping),
LDDX, LDIRX, LDDRX, ED B6, LDPIRX 16 each; the repeats (BC = 2) 37 each; LD A,I 9 (the standard check).

### 28 MHz: 12 of 12, as my reading of the machine said

NOP 5, MUL 10, TEST n 14, ADD HL,nn 20, JP (C) 15, OUTINB 19, the helpers 21, the loop itself 22, and:

- **NEXTREG r,v: 26, not 24.** The sister cell. NEXTREG's two idle machine cycles are real memory reads of
  the operand, each with the 28 MHz wait, as t80n_mcode.vhd says. NEXTREG r,A: 22 (its two idle reads too).
- **LDIX skipping: 20, against 19 copying.** When the byte equals A, the T80N's third cycle is a *read* of DE
  (Write drops and RD follows it), and that read waits too.
- So: one wait on every memory read, fetches included (NOP 5), none on writes (LDIX copying 19) or I/O
  (JP (C) 15, OUTINB 19). Loam's question and my answer, confirmed.

### Flags: 7 of 8

| cell | got | VHDL | otherwise | |
|---|---|---|---|---|
| 31 F (ADD HL,A, F=FF before) | FE | FE | FF if carry kept | **confirmed: ADD rr,A clears carry** |
| A5 F (LDWS, D=BBh, F=FF) | A8 | A8 | A9 if INC D | **confirmed: LDWS leaves ADD D,1's flags** |
| A4 F (LDIX, F=FF) | ED | ED | FF if kept | **confirmed: LDIX sets flags as LDI does** |
| B7 F (LDPIRX, F=00) | **00** | 08 | 28 from A+byte, 00 kept | **not as I read it** (below) |
| 93HL (PIXELDN from 5FE0) | 4000 | 4000 | 6000 | **confirmed: wraps in its 8-bit counter** |
| 27 F (TEST n) | 34 | 34 | | confirmed |
| BITF (BIT 0,(HL), MEMPTR 29xx) | **10** | 10 | 38 on a Zilog | **confirmed: X/Y = 0, no MEMPTR** |
| SCFF (SCF after CP 28h; NOP) | 81 | 81 | A9 on a Zilog | confirmed: X/Y from A (no Q) |

## The one miss: LDPIRX's flags

The test: A = 02h, F = 00h, BC = 1, HL = BB30h holding 08h, DE = BB68h (the scratch area, zeroed, so 00h there).
The pattern address is (HL & FFF8h) | (E & 7) = BB30h. My reading of the VHDL: LDPIRX keeps LDI's I_BT, its
second cycle leaves the ALU on the default OR with B on BusA, so n = B OR byte = 00h OR 08h = 08h and X = 1:
F = 08h. omse-ai, built from that reading, prints 08. Her Next printed **00**.

With F = 00h going in, 00h out has only two readings:
1. **LDPIRX leaves the flags alone** (as the Next's documentation, as I remember it, says the whole LDxX family
   does; LDIX's ED shows that isn't true of LDIX here). Then my reading of LDPIRX's I_BT is wrong somewhere.
2. **The byte the CPU saw had bits 3 and 1 clear.** The byte at DE was 00h, and the T80N moves the address bus
   from the pattern address to DE straight after M2's T1 (the any-T-state block in t80n.vhd). But zxnext.vhd's
   SRAM controller takes the address at the request edge, mid-T1, and holds the data for the CPU's T3, so by the
   source the CPU should get the pattern byte. If it got DE's byte, LDPIRX's pattern fill would be broken at
   3.5 MHz, which seems unlikely for an instruction people use.

The VHDL can't settle it, so a second tape will: **LDPIRX2.TAP** (`z80ntime/build_ldpirx2.py`), with F = FFh
going in (so "left alone" shows as FF), distinct bytes at the pattern address, at HL and at DE, and the byte
LDPIRX wrote printed beside the flags. Each explanation prints something different (the table is on its screen).

## What the core should change

- **Nothing that the tape confirmed** (48 of 48 timings and 7 of 8 flags, including all four places where the
  VHDL and the documentation disagree, and the 28 MHz wait on NEXTREG's idle reads and LDIX's skip read).
- **BIT n,(HL) and BIT n,(IX+d): change, under the z80n flag.** BITF = 10 says the Next's CPU takes no X/Y from
  MEMPTR. omse-ai (floooh's Zilog model) gives 38. A faithful Next gives X = Y = 0 for BIT n,(HL) and the
  documented DDCB d 46-7E BITs, and the byte's bits 3 and 5 for the undocumented DDCB BITs on other registers
  (t80n_alu.vhd; XYbit_undoc). I can make that change, tests first, if you'd like it.
- **LDPIRX's flags: wait for LDPIRX2.** If it says "left alone", the core's LDPIRX should keep F as it was (a
  two-line change). If it says the byte came from DE, that's a finding about the Next itself, and it's bigger.

## The follow-up tape: LDPIRX2.TAP (`z80ntime/build/LDPIRX2.TAP`, 1138 bytes, checksums good)

Built by `z80ntime/build_ldpirx2.py`; loads like Z80NTIME (CLEAR 32767: LOAD "" CODE: RANDOMIZE USR 32768),
returns to BASIC, one screen, the legend on it. Each case at 3.5 and at 28 MHz; F, then the byte at DE after.

| case | what | VHDL as I read it | flags untouched | byte from DE | other |
|---|---|---|---|---|---|
| C1 | LDPIRX, F=FF, A=02, pattern 48h, (HL) 85h, (DE) 22h | C9 48 | FF 48 | E1 22 | A+byte E9 48; plain HL C1 85 |
| C2 | Z80NTIME's test again (F=00, pattern 08h, (DE) 00h) | 08 08 | 00 08 | 00 00 | |
| C3 | C1 with F=00 | 08 48 | 00 48 | 20 22 | |
| C5 | LDIX on C1's layout (a control) | E1 85 | | | |
| C6 | BIT 0,(IX+5) at BB35h holding 85h, F=00 | 10 | | | a Zilog (and omse-ai today) 38 |
| C7 | undocumented DD CB 05 40 at 9045h holding 29h, F=00 | 38 | | | a Zilog (and omse-ai today) 10 |

Checked on omse-ai: with the Z80N on it prints the "VHDL as I read it" column (and 38, 10 for C6, C7, as floooh
does today); on a plain 48K it survives (every Z80N op a no-op) and returns "0 OK". C6 and C7 test the BIT change
proposed above in the two DDCB forms the photo didn't reach.

(Also: Z80NTIME's stack top at BC00h grew down into its scratch page, BB00h-BBFFh, which it zeroes, so it
returned to BASIC with IX = 0. Harmless there, BASIC doesn't need IX, and nothing measured depended on it. It's
moved to BD00h in both builders; the photo's tape was the old one.)

## A cross-check for Ratio: when an IN latches, and when INT is sampled (Tally's question)

- **An I/O read** (IOWait = 1, as T80na sets it) runs T1, T1w (the automatic wait: TState held at 1 for one
  extra clock while Auto_Wait_t1 rises), T2, T3. IORQ and RD are active from the start of T1w to the falling
  edge in T3. The T80N latches the data **on the falling edge in T3** (t80na.vhd 214-221, `DI_Reg <= D_i` when
  TState = 3), the same edge that drops RD. That's 3.5 clocks after T1 starts. In omse-ai's IN, ticks run T1
  (IORQ), T2 (IORQ|RD, where io_read is called), Tw, T3, so it's 2.5 T after io_read's tick begins. Ratio is
  right.
- **But a nextreg read through port 253Bh is sampled one clock earlier than that.** The data reaches the CPU
  through a register clocked on the CPU clock's *falling* edge (zxnext.vhd 5780-5782,
  `port_253b_dat_0 <= port_253b_dat` on falling_edge(i_CLK_CPU); cpu_di <= port_rd_dat <= port_253b_dat_0, lines
  1832, 2778, 2796). The T80N latches on that same falling edge, so it takes the value registered one clock
  before: **NR 22h's bit is the pulse as it was at the falling edge in T2** (less one CLK_28 register,
  port_253b_dat on its rising edge, and pulse_int_n's own falling-edge register). In omse-ai terms, that's
  1.5 T after io_read's tick begins.
- **INT** is registered on every CPU rising edge (`INT_s <= not INT_n`, t80n.vhd, "Syncronise inputs"). The
  decision is made at the edge that ends an instruction's last T-state (T_Res with MCycle = MCycles), from
  INT_s, so **INT is sampled at the rising edge that begins the instruction's last T-state**, as on a Zilog.
  It also needs IntE_FF1, and not directly after EI (SetEI = '0'); a HALT re-checks at every NOP M1.
- **Why 31, not 32.** The pulse starts at a CLK_28 falling edge (pulse_int_en), and pulse_count counts CPU
  rising edges from there. pulse_int_n goes back high at the CLK_28 falling edge just after the 32nd
  (zxnext.vhd 1975-2002). So the pulse covers exactly 32 CPU rising edges, and INT_s sees it 32 times: the
  "32 cpu cycles" of the comment. But its length is 31 clocks plus the gap from its start to the next rising
  edge, plus half a 28 MHz cycle. A sampler at mid-clock falling edges sees 32 if the pulse starts in the first
  half of a clock, and 31 if it starts in the second half, just before a rising edge, which is where an
  interrupt meant to be sampled on the rising edge belongs. The test machine's 31 says so. Ratio's 32 fits an INT
  exactly 32 whole T-states long, read at a T-state boundary. To match: assert INT from just before a CPU
  rising edge (so the CPU samples it on 32 rising edges) and let a 253Bh read see it at T2's falling edge.
  Hart's-tongue's 31 samples, k = 14 to 44, then place it.

## Another cross-check (Speccy-Zone's question): how many edges the SPI master sees an IN

- **`iord` is visible at two CPU rising edges**, the ones that end T1w and T2, as on a Zilog (its Tw and T3
  edges). From t80na.vhd: IORQ_t1 drops at T1's falling edge, IORQ_t2 follows it at the next rising edge (the
  start of T1w), and IORQ_t1 comes back at T3's falling edge, so IORQ_n is low from the start of T1w to mid-T3.
  RD_n is gated by the same IORQ_rw. The edge that starts T1w sees it still high, and the edge that ends T3
  sees it high again. zxnext.vhd's `port_eb_rd <= iord and port_eb` is combinational, and spi_master.vhd
  (clocked on i_CLK_CPU, the T80N's clock) evaluates `spi_begin` at both of those edges.
- spi_master: a begin sets state 0; it counts one a clock to 15 (`state_last`), then 16 is idle, where it
  stays. A begin needs state 15 or idle at an edge where the strobe is up. The finished byte reaches
  `miso_dat` two edges after state 15 (state_last, then state_last_d): **at begin + 17**. The IN latches at its
  T3's falling edge, which is its second strobe edge + 0.5.
- So, for an IN whose first strobe edge is d clocks after the last begin (d = 15 for the Lever's IN after the
  last INI: INIR's I/O cycle starts 9 T into its last 16 T iteration, IN's 8 T into its 12):
  - **d >= 16:** it begins a transfer (at its first edge) and reads the byte just finished. Clean.
  - **d = 15:** it **does** begin one, at its *second* edge (state 15), but it reads the byte *before* last:
    the one just finished lands at begin + 17, and it latches at begin + 16.5.
  - **d <= 14:** no begin, and a stale read.
- omse-ai's present rule (Tally's, spi_gap = 16) treats d = 15 the other way round: no begin, and the byte
  just finished. **Both explain the Lever's glitch.** In the VHDL's version, the 15-apart IN returns D512 and
  begins CRC2's transfer, the second IN (12 T later) is too soon and reads CRC1, and the first token poll
  reads CRC2. In omse-ai's, the 15-apart IN returns CRC1 and begins nothing, the second begins CRC2 and
  returns CRC1, and the first poll reads CRC2. Either way CRC2 lands where the token poll looks, which is what
  the test machine showed. So the photo didn't decide between one edge and two.
- **What would decide it:** what the 15-apart IN itself returns, on a sector whose bytes are known (D512 by
  the VHDL, CRC1 by the present rule). Or whether a 15-apart IN followed by one 17 clocks later reads a fresh
  byte (VHDL: no, the master is busy from the 15-apart begin) or not. A CARDTIME-sized probe could ask.
- For Ratio, moving IN reads to T3's falling edge: the begin sees the strobe at the edges ending T1w and T2
  (in omse-ai's IN, the ends of the IORQ|RD tick and the next IORQ tick), and the data is `miso_dat` as of
  mid-T3.

## LDPIRX2 on the test machine

*Read against the photo itself. Main's transcription is exact.* Header: core 3.02.02, and 28 MHz really reached
(cpu28 33).

| case | 3.5 MHz | 28 MHz | reads as |
|---|---|---|---|
| C1 LDPIRX, F=FF, pattern 48h, (DE) 22h | **E1 22** | **C9 48** | 3.5: the byte from DE; 28: the VHDL as read |
| C2 Z80NTIME's test again | **00 00** | **08 08** | 3.5: the byte from DE; 28: the VHDL as read |
| C3 C1 with F=00 | **20 22** | **08 48** | 3.5: the byte from DE; 28: the VHDL as read |
| C5 LDIX on C1's layout (a control) | E1 85 | E1 85 | as predicted, both speeds |
| C6 BIT 0,(IX+5), documented DD CB d 46 | **10** | **10** | the T80N's: X = Y = 0 (a Zilog 38) |
| C7 undocumented DD CB d 40 | **38** | **38** | the T80N's: X, Y from the byte (a Zilog 10) |

**What it says:**
- **At 28 MHz LDPIRX is exactly what I read in the VHDL**: it reads the pattern byte at (HL & FFF8h) + (E & 7),
  writes it to DE unless it equals A, and sets LDI's flags from B OR byte (B after the decrement). So the
  flag formula was right all along.
- **At 3.5 MHz LDPIRX reads the byte at DE instead.** The flags are that byte's (n = 00 OR 22h: Y, not X), and
  it writes the byte back where it found it. So at 3.5 MHz LDPIRX doesn't do its pattern fill on this core,
  which is a finding about the Next itself. Z80NTIME's 00 was this: its DE held 00.
- The T80N moves the address bus from the pattern address to DE at the end of M2's T1 (t80n.vhd's any-T-state
  block). So **at 28 MHz the Next's memory takes the address during T1, and at 3.5 MHz after it**. I can't find
  why in the source. zxnext.vhd's SRAM request (`sram_req_t`) looks to fire on the first 28 MHz edge after
  MREQ and RD fall, mid-T1, at both speeds, and the memory decode in front of it is combinational. Something
  between the request and the data must happen later at 3.5 MHz. That's a question for the machine side, not
  the CPU: the CPU's bus (the pattern address on T1, DE from T2) is now confirmed at both speeds.
- 7 and 14 MHz weren't tested. **LDPIRX3.TAP** (below) runs the same cases at all four speeds, which narrows
  where the memory takes its address.
- **BIT is settled**: for BIT n,(HL) (Z80NTIME's BITF), the documented DD CB d 46 (C6) and the undocumented
  DD CB d 40 (C7), the Next's CPU does what t80n_alu.vhd says, not what a Zilog does.

## What the core should do (updated)

- **BIT, under z80n: change it now.** BIT n,(HL) and the documented DDCB/FDCB BITs give X = Y = 0. The
  undocumented DDCB/FDCB BITs on other registers take X and Y from the byte's bits 3 and 5. BIT n,r is
  unchanged (X, Y from r, as now). Flag off: unchanged. I'm doing it now, tests first.
- **LDPIRX: no change to the CPU.** Its bus is right (pattern address on T1, DE from T2, as the T80N drives it).
  Its flag formula is right (confirmed at 28 MHz). Which byte comes back is the memory's doing, so it belongs
  to the machine. For Ratio: below 28 MHz, the Next's memory returns the byte at the address the bus shows
  after T1. LDPIRX is the only instruction whose address moves inside a memory cycle, so a memory that takes a
  read's address at T2 when the CPU is below 28 MHz reproduces the photo and changes nothing else. LDPIRX3
  says whether that's "below 28" or "at 3.5 only".
- Nothing else.

## Done since (08:50)

- **BIT, under z80n, is changed** on branch `next-z80n` (fast-forwarded to `next` at a47c7dd first): 4c6f3fd tests
  first (TestBit: every BIT form with the flag on, held to t80n_alu.vhd's rule and to the flag-off run in
  everything else, tick for tick, plus the photos' three cells exactly; watched failing), then ab40061 the
  change, in `_z80_cb_action` only when z80n is set. Three new mutants caught. The whole suite: 290 tests OK,
  plain, with OMSE_AI_ESXDOS, and with OMSE_AI_NEXT_ROMS (the fast-boot tests, NextZXOS booting on this CPU).
  omse-ai's Z80N now prints BITF 10, C6 10 and C7 38, as the test machine did.
- **The tapes pause** (Melissa O'Neill's rule): Z80NTIME, LDPIRX2 and the new LDPIRX3 end with "photo, then press a
  key" and return to BASIC on the key. Checked on omse-ai: they wait, then return "0 OK". Rebuilt in
  `z80ntime/build/`: Z80NTIME.TAP (3104 bytes), LDPIRX2.TAP (1182), LDPIRX3.TAP (1191), all checksums good.
  Each has the stack at BD00h.
- **LDPIRX3.TAP**: LDPIRX2's six cases at 3.5, 7, 14 and 28 MHz, with nextreg 07h read back after each change
  (the "cpu" line). By the photo so far: "DE's" columns at 3.5, the VHDL's at 28. 7 and 14 will say where the
  Next's memory starts taking a read's address during T1.

**LDPIRX3 prediction, written before the photo (Fri 06 Nov 11:43, Tally, from Ratio's core with the memory-timing change):**
DE's byte at **3.5, 7 and 14 MHz**, the pattern byte at **28 MHz** (memory takes a read's address at T2 below 28 MHz).
The alternative, DE's byte at 3.5 only, would mean the slow-memory behaviour is tied to contention or the 3.5 MHz clock.
LDPIRX2 now matches the photo in every cell at both speeds on this core.
- (Rustyback, Rustyback Fern's second-sources reading, Fri 06 Nov): the 3.02.02 changelog says "LDPIRX works properly at all cpu speeds", yet LDPIRX2 on
  Melissa O'Neill's 3.02.02 read DE's byte at 3.5 MHz. So whatever LDPIRX3 shows is a fact the changelog didn't capture.

- (Fri 06 Nov 15:35 PST, by `date`, Hart's-tongue, at Tally's asking) **The photo beep is in all three generators.** It's Melissa O'Neill's idea and Tally's spec (NOTES.md, "The photo beep"), and `../beep.inc` is the encoder. `build_probe.py`, `build_ldpirx2.py` and `build_ldpirx3.py` each gained one `call photobeep` before the photo's `call waitkey`, and a `TAPEID` (60, 62, 63) with `include "../beep.inc"` at the end of the template (above `endcode` in Z80NTIME). Nothing else in Strobe's design changed: the timing code, the tests and the screens are hers as they were. The beep saves the interrupt state and NR 0x07 and plays at 3.5 MHz after the measurements are done, so it can't touch a result. The tapes were rebuilt in `z80ntime/build/`.

## LDPIRX3 on the test machine (sitting 2: the photo)

*Read against the photo; Tally's transcription is exact.* Header: core 3.02.02; nextreg 07h read back as
**00 11 22 33**, so the CPU really ran at 3.5, 7, 14 and 28 MHz in turn. The board is an issue 4 (0F = 02,
from P-1).

| case | 3.5 MHz | 7 MHz | 14 MHz | 28 MHz |
|---|---|---|---|---|
| C1 LDPIRX, F=FF, pattern 48h, (DE) 22h | E1 22 | E1 22 | C9 48 | C9 48 |
| C2 Z80NTIME's test | 00 00 | 00 00 | 08 08 | 08 08 |
| C3 C1 with F=00 | 20 22 | 20 22 | 08 48 | 08 48 |
| C5 LDIX (control) | E1 85 | E1 85 | E1 85 | E1 85 |
| C6 BIT 0,(IX+d), DD CB d 46 | 10 | 10 | 10 | 10 |
| C7 DD CB d 40 (undocumented) | 38 | 38 | 38 | 38 |

**So LDPIRX takes DE's byte at 3.5 and 7 MHz, and the pattern byte at 14 and 28.** The boundary is between 7
and 14 MHz, not between 14 and 28 as the T2 model I gave Ratio assumed. LDIX and both BITs are the same at
every speed. Reruns of Z80NTIME (`60-...`) and LDPIRX2 (`62-...`) in the same sitting match the first sitting
cell for cell. Z80NTIME's LDPIRX flag cell is 00 again because it runs at the restored speed, 3.5 MHz. Both
tapes paused for the photo ("(key)" is on Z80NTIME's last line).

**The rule for the machine (measured, at all four speeds):** a memory read's byte comes from the address the
bus shows **after T1 when the CPU runs at 3.5 or 7 MHz**, and **during T1 at 14 or 28 MHz**. LDPIRX is the
only instruction whose address moves inside a read (the T80N switches its bus from the pattern address to DE
at the end of M2's T1), so nothing else can tell the difference. In omse-ai's terms: at 3.5 and 7 MHz, serve
a read from the address on its T2 tick (z80.h's LDPIRX puts DE there), and at 14 and 28 MHz from its T1 tick.

**Why, I can't yet say from the source.** zxnext.vhd's SRAM request (`sram_req_t`, the first CLK_28 rising edge
after MREQ and RD fall, mid-T1) and the issue 4 top's controller (it registers the address on that request
edge) look the same at every speed. On issue 4 the CPU clock comes straight from the PLL's CLK_7, CLK_14 or
CLK_28 through two BUFGMUXes, or at 3.5 MHz from a register on CLK_7. The memory decode in front of the
request (`sram_pre_*`) is registered on CLK_28's falling edge, but LDPIRX's two addresses share an 8K page,
so that can't move the byte. Something in how those clocks line up below 14 MHz puts the effective sample after
T1's end. The photo is the authority; the rule above is what it says.

**The core (z80.h): still no change.** The CPU's bus and LDPIRX's flags are confirmed at every speed. Which
byte comes back is the memory's doing.
