# Contention

While the ULA reads the screen, it stops the Z80's clock whenever the CPU wants contended memory, or the ULA's port, at the wrong moment. Code and data in contended memory run slower during the 192 screen lines, by an amount that depends on the exact T-state. Demos that race the beam, and anything that times itself by counting T-states, depend on it. omse-ai models it, **on by default**, for the 48K and the 128. `zx.contention(False)` turns it off, and `zx.stalled` counts the T-states the ULA has held the CPU since power-on.

This is a first cut: principled, documented and tested, but whole T-states only (see "What's finessed", below). The floating bus, which keeps the same clock, is modelled too: see "The floating bus", below.

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

## The floating bus

When the CPU reads a port that nothing answers, nothing drives the data bus, and the CPU reads whatever is on it. Most of the time that's FFh, eight wires pulled up. But while the ULA fetches the screen, its bytes are on the bus too, and an unanswered IN that lands on one of its fetches reads a byte of the picture. Programs use this to find the beam without an interrupt (Arkanoid, Sidewize), and to tell an original 48K or 128 from a +2A/+3 (Breakspace, below). omse-ai models it, **on by default** for both machines. `zx.floating_bus(False)` makes every unanswered port read FFh.

**What's on the bus.** In the first 128 T-states of each of the 192 screen lines, in each group of 8: at position 2 a bitmap byte, at 3 its attribute, at 4 the next bitmap byte, at 5 its attribute, and FFh at 0, 1, 6 and 7. Everywhere else, FFh. The groups start at **14,336** on a 48K and **14,362** on a 128, one T-state after contention's, so the first byte comes at **14,338** and **14,364**. On a 128 showing the shadow screen (bit 3 of 7FFD), the bytes come from bank 7.

**When the CPU takes it.** At the I/O cycle's fourth T-state, after any hold there. For a port whose high byte isn't contended (N:4) that's three T-states after the cycle begins. For a contended high byte (C:1 ×4) it's after the fourth hold, so a hold can carry the sample onto an attribute beat.

**Who answers first.** The ULA's own port (bit 0 low), the Kempston joystick, the 128's AY and the divMMC's data port (EBh) all answer, and only an IN that none of them answers reads the floating bus.

**The 128's quirk.** On a 128, an IN from any port with A15 and A1 low (one that decodes as 7FFD) also writes the byte it read into the paging register, unless paging is locked. Read in the border, that's FFh: bank 7, ROM 1, the shadow screen, and the lock.

**Sources**, read and never copied (GPL):
- Fuse's `spectrum_unattached_port` (spectrum.c) has Ramsoft's pattern, with the first byte at 14,338 and 14,364 ("not 14347 and 14368 as used by Ramsoft"), and notes that Arkanoid and Sidewize work with it.
- Its `readport` (periph.c), and the ULA's `contend_port_early` and `contend_port_late` (peripherals/ula.c), place the sample after the holds, at the I/O cycle's fourth T-state.
- The same `readport` has the 128's write to 7FFD.

**How it's checked.** `tests/test_floating.py` reads unanswered ports from a screen whose every byte differs from its neighbours and is never FFh, and a reference written from the rule above predicts every byte read:
- 580 reads on a 48K, 35 T apart, so every phase of 8 comes round, across lines, borders and idle beats;
- 360 reads of port 40FF (a contended high byte), alternating between a held sample and an unheld one;
- the same 580 reads on a 128, on the normal screen and on the shadow screen, whose bytes differ from the first screen's at every place;
- the off switch, and the 128's write to 7FFD.

Ten mutants of the code were each run in a copy of the tree, and every one failed a test: the first byte a T-state late, bitmap and attribute swapped, the sample a T-state early, the high byte never held, the first hold dropped, the sample taken before the last hold, the shadow screen ignored, a 48K line on the 128, the 128 starting at the 48K's time, and no write to 7FFD.

**The acceptance test was Melissa's: Breakspace**, by Thesuper, on the 128. Its last picture draws angel's wings out into the border, row by row. Before drawing, it ANDs together about 3,000 reads of port xxFF: any byte that isn't FFh means a floating bus, so an original 48K or 128. Finding none, Breakspace took its other branch, with other timings, and the wings came out in blocky, shifted steps. With the floating bus, the final frame's border matches a capture of it from Melissa's real Spectrum Next, in 128K mode, in 99% of its pixels. That's as close as the paper area matches (98%), which is the same picture on both and so the capture's noise floor. Without the floating bus the border matched in 71%.

## Sources

Read, never copied: the emulators' and cores' source is GPL, and omse-ai is MIT.

- **The documented model**: the "Contended memory" and "Contended I/O" articles of the World of Spectrum FAQ (the ZX Spectrum FAQ wiki, faqwiki.zxnet.co.uk), which give the 6,5,4,3,2,1,0,0 pattern, the 14,335 start, the four I/O cases and the per-instruction tables (`pc:4`, `hl:3`, `ir:1 ×2`). The Next's ULA cites the same page.
- **The ZX Spectrum Next's ULA** (`cores/zxnext/src/video/zxula.vhd`, core 3.02.02), real logic, agrees on all but one port:
  - it contends when the address is in a contended page and the previous T-state had no MREQ (`mreq23_n`);
  - for the ULA's port, only on the first IORQ T-state (`ioreqtw3_n`);
  - in six of every eight T-states, in the first 128 of each line, outside the vertical border (`wait_s`);
  - with bank 5 contended on a 48K and the odd banks on a 128 (`zxnext.vhd`, `mem_contend`).
  - **The exception:** under 128 timing the Next also treats every port that decodes as 7FFD (`zxnext.vhd`, `port_7ffd`: A15 low, A1 low, A0 high) as the ULA's own (`port_contend`, which includes the ULA+ ports too). So there `OUT (7FFDh)` is C:1, C:3 and `OUT (3FFDh)` is N:1, C:3, where the documented table, and omse-ai, give C:1 ×4 and N:4. Which a real 128 does is open. omse-ai follows the documented table until a real machine says otherwise. (An earlier version of this page said the Next agreed term for term, and missed this.)
  - **Where it starts:** the Next applies the same rule two T-states later, relative to INT. Its timing generator puts the first held T-state of 48K timing 14,337 T after the first CPU clock edge that sees INT, where the original 48K's is the documented 14,335. Melissa's real Next agrees with its VHDL (probe P-7: the INT pulse timed against a loop synchronised by contention). omse-ai models the original 48K.
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
- **The floating bus is the documented pattern, in whole T-states.** The byte read is the one on the bus in the T-state Fuse samples. Where a real ULA's bus differs from the pattern, or a program depends on which half of a T-state the byte is latched in, omse-ai follows the pattern. The +2A/+3's own floating bus isn't modelled, because those machines aren't.
- **The address on the bus during internal T-states is the core's.** chips' Z80 leaves the last address it drove, which is what the tables assume for nearly every instruction. Where a real Z80 puts a different address on the bus during an internal T-state, omse-ai contends by the wrong one.
- **The beam itself** is drawn where omse-ai has always drawn it. On the 128, contention starts 3 T-states before the first pixel omse-ai draws, and on the 48K 1 before. Both starts are the documented ones.
