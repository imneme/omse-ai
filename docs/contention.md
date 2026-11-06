# Contention

While the ULA reads the screen, it stops the Z80's clock whenever the CPU wants contended memory, or the ULA's port, at the wrong moment. Code and data in contended memory run slower during the 192 screen lines, by an amount that depends on the exact T-state. Demos that race the beam, and anything that times itself by counting T-states, depend on it. omse-ai models it, **on by default**, for the 48K and the 128. `zx.contention(False)` turns it off, and `zx.stalled` counts the T-states the ULA has held the CPU since power-on.

This is a first cut: principled, documented and tested, but whole T-states only, and without the floating bus (see "What's finessed", below).

## The rule

**Where the ULA looks.** At each CPU T-state, the ULA decides whether to hold the CPU. It considers:

- **The first T-state of a memory cycle** (an opcode fetch, a read or a write) whose address is contended.
- **An internal T-state** (no memory or I/O cycle) whose address on the bus is contended, unless it directly follows a memory T-state. The Z80 leaves the last address it used on the bus: IR after an opcode fetch's refresh, DE after LDIR's write, PC+1 after JR's offset. That's why the documented tables have entries like `ir:1 ×2` for INC HL or `de:1 ×5` for LDIR's repeat.
- **Never** the second and third T-states of a memory cycle, the refresh, or the fourth T-state of an opcode fetch (which follows the refresh), nor an interrupt acknowledge.
- **An I/O cycle**, by the documented four cases. "The ULA's port" means bit 0 of the port is low; "contended" means its high byte would be a contended memory address. `C:n` is a check and then n T-states; `N:n` is n T-states with no check.

| high byte | bit 0 | pattern |
|---|---|---|
| uncontended | 1 | N:4 |
| uncontended | 0 | N:1, C:3 |
| contended | 0 | C:1, C:3 |
| contended | 1 | C:1, C:1, C:1, C:1 |

**When it holds, and for how long.** A check at T-state t waits **6, 5, 4, 3, 2, 1, 0, 0** T-states by t's position in each group of 8. That applies only in the first 128 T-states of each of the 192 screen lines, counted from **14,335** T-states after INT goes up on a 48K (224-T lines) and **14,361** on a 128 (228-T lines). Anywhere else it doesn't wait.

**What's contended.** 4000h-7FFFh on both machines (on the 128 that's always bank 5). On the 128 also C000h-FFFFh while an **odd bank** (1, 3, 5 or 7) is paged there, which includes the shadow screen, bank 7. This is the original Spectrum 128 (the "toastrack", as omse-ai's 128 is); the +2A and +3 contend banks 4-7 and behave differently, and aren't modelled.

**How it's applied.** omse-ai's Z80 core runs one T-state per call, so the ULA holding the clock is exactly that: for the delay, the beam, the AY and the clock run on and the CPU doesn't. The hold comes straight after the CPU shows the T-state on its pins, before the access is served, so the access lands where it would on the real machine.

## Sources

Read, never copied: the emulators' and cores' source is GPL, and omse-ai is MIT.

- **The documented model**: the "Contended memory" and "Contended I/O" articles of the World of Spectrum FAQ (the ZX Spectrum FAQ wiki, faqwiki.zxnet.co.uk), which give the 6,5,4,3,2,1,0,0 pattern, the 14,335 start, the four I/O cases and the per-instruction tables (`pc:4`, `hl:3`, `ir:1 ×2`). The Next's ULA cites the same page.
- **The ZX Spectrum Next's ULA** (`cores/zxnext/src/video/zxula.vhd`, core 3.02.02), real logic, agrees on all but one port:
  - it contends when the address is in a contended page and the previous T-state had no MREQ (`mreq23_n`);
  - for the ULA's port, only on the first IORQ T-state (`ioreqtw3_n`);
  - in six of every eight T-states, in the first 128 of each line, outside the vertical border (`wait_s`);
  - with bank 5 contended on a 48K and the odd banks on a 128 (`zxnext.vhd`, `mem_contend`).
  - **The exception:** under 128 timing the Next also treats every port that decodes as 7FFD (`zxnext.vhd`, `port_7ffd`: A15 low, A1 low, A0 high) as the ULA's own (`port_contend`, which includes the ULA+ ports too). So there `OUT (7FFDh)` is C:1, C:3 and `OUT (3FFDh)` is N:1, C:3, where the documented table, and omse-ai, give C:1 ×4 and N:4. Which a real 128 does is open. omse-ai follows the documented table until a real machine says otherwise. (An earlier version of this page said the Next agreed term for term, and missed this.)
- **The Z80 core** (chips' `z80.h`, as OMSE has it): it clears its control pins every T-state, so a memory cycle's first T-state is the only one showing MREQ with RD or WR. Its I/O cycles raise IORQ from their first T-state (a real Z80 raises it from the second), so omse-ai counts I/O cycles by phase.
- **OMSE** (Melissa O'Neill's emulator): it holds the CPU while the address on the bus is contended and the ULA is in the first six T-states of each eight, with "lockouts" so a cycle isn't contended twice.
  - **Agrees:** holding the clock, rather than adding T-states afterwards; contending internal T-states by the address the core leaves on the bus; the lockout after a memory T-state, which is the same as the Next's `mreq23_n`.
  - **Differs:** OMSE locks out the two T-states after an I/O access, so a contended high byte with bit 0 set is checked twice (C:1, C:1), not four times (C:1 ×4) as the documented table says, and the Next too for every port but those that decode as 7FFD (above). omse-ai follows them.

## How it's checked

`tests/test_contention.py` runs long straight lines of one kind of instruction and measures each to the T-state. A reference written from the documented tables works out the same time from the same starting T-state, and they must agree exactly. The tests cover:
- reads, writes, and a whole frame of reads (past the last screen line);
- a body of 11 T-states, which doesn't divide a line, so every phase comes round, and the same from 32 starting points;
- INC HL with I at 40h (internal T-states, `ir:1 ×2`) and fetches from contended memory;
- all four I/O cases;
- contention off;
- on the 128, each bank at C000 and bank 5 at 4000.

Thirteen mutants of the code were each run in a copy of the tree, and every one failed a test: the pattern shifted, the window a T-state late, 136 T wide, or 193 lines tall, T2 contended, internal T-states never contended, or contended after a memory T-state, the ULA's port checked at T1, OMSE's two-check rule, no bank contention on the 128, the even banks contended, the 128 using the 48K's start, and no contention at all.

Two of the thirteen got past the first version of the tests. "193 lines" got through because the runs never reached the bottom of the screen. "T2 contended" shows only from about 7% of starting phases. The whole-frame test and the 32 starting points are there because of them.

**The acceptance test was Melissa's: Shock**, Raww Arse's megademo (48K version), which she'd had running right on OMSE with a basic contention model. Its second part is a full-screen raster with a spinning logo, colour changes timed to the T-state across border and screen. With contention on, the rasters run unbroken from border to paper. With it off, the paper area falls out of step and the effect finishes early, leaving the bottom of the screen black.

## What's finessed

- **Whole T-states.** The ULA really decides on clock edges, half a T-state apart, and the documented tables are in whole T-states. omse-ai decides once per T-state, at the start of it, and the documented start (14,335) carries the absolute offset. That's enough for timing. It isn't enough for effects that depend on which edge the ULA samples on.
- **No floating bus.** Reading an unattached port during the screen returns 0xFF here, not the byte the ULA is fetching. Programs that sync to the beam that way won't sync.
- **The address on the bus during internal T-states is the core's.** chips' Z80 leaves the last address it drove, which is what the tables assume for nearly every instruction. Where a real Z80 puts a different address on the bus during an internal T-state, omse-ai contends by the wrong one.
- **The beam itself** is drawn where omse-ai has always drawn it. On the 128, contention starts 3 T-states before the first pixel omse-ai draws, and on the 48K 1 before. Both starts are the documented ones.
