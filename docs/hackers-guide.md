# Under the Rubber Keys: A Hacker's Guide to omse-ai
describes-rev: 6b4f6b6

## About this guide

omse-ai (One More Spectrum Emulator, Accessible and Instrumented) is a set of ZX Spectrums with no window, no speaker and no keyboard, driven from Python and from scripts, that report what happened as text, numbers, pictures and sound logs. It began as Melissa O'Neill's emulator OMSE, reshaped as a C library. This guide is for someone who has cloned it and wants to change it. It describes the system as it exists at the revision above, organised around one question: what behaviour is load-bearing, and what must not be disturbed?

There are two machines in one repository:

- **The classic machine**: a Spectrum 48K and a Spectrum 128 ("toastrack"), in `src/zxcore.cpp`, driven by `speccy.py` and `zxscript.py`. It has a divMMC interface with an SD card (`src/sdcard.h`), memory and I/O contention, and the floating bus.
- **The Spectrum Next**: modelled on core 3.02.02 of the Next's FPGA design, in `src/nextcore.cpp` and the `src/next_*.h` headers, driven by `next.py`. It was written by reading the core's VHDL, and nearly every non-obvious line cites the VHDL line it came from.

Both machines run the same Z80 core, `src/z80.h`, from Andre Weissflog's chips project. It is modified to place addresses on the bus as a real Z80 does, and to add the Next's Z80N instructions behind a flag.

**Where the authority lies.** In order:

1. The code is what runs, and what this guide describes.
2. Behind the Next's code is the VHDL it cites: `zxnext:N` is a line of `zxnext.vhd`, `zxula:N` a line of `zxula.vhd`, and so on (see the glossary). Behind the classic machine are the World of Spectrum FAQ's contention tables, Fuse, and the cores named in `docs/contention.md` and `docs/divmmc.md`. Where code and citation disagree, that is a finding, not a matter of taste.
3. Above both stands a real machine. Melissa O'Neill's Spectrum Next ran probe programs whose screens were photographed and compared with the emulator. Where a photograph disagreed with the reading of the VHDL, the photograph won, and the code says so where it happens: for example, the sprite deadline at `tests/nextvideo.py:1026-1032`, and the LDPIRX read at `src/nextcore.cpp:2371-2372`. Her real Spectrum and divMMC played the same role for the classic machine (`docs/contention.md:54`, `docs/contention.md:87`, `docs/divmmc.md:86`).

**How the references work.** A reference is `path:N` or `path:N-M`, a repo-relative path and line numbers at `describes-rev`. A tool, retrace, carries them forward to later commits, and checks that the quoted line still says what it said. Where this guide quotes code, the quote is exact at that revision. When you change a line this guide quotes, you have changed something this guide calls load-bearing: read the section before you commit.

**Words.** The code and tests use words from the people who built it: "foil", "§N", "DESIGN.md §9.1 (N)", "ruling", "sitting", "PV1", "P-7", "mutant survivor", and the names of the instances of Fern (an AI agent) who wrote each part. Where they appear here, see the glossary at the end of this guide.

**Known gaps.** Where something is approximate, or known to be wrong at this revision, this guide says so plainly, under "Known gap". Some found by a review of this guide's first revision have since been fixed; where that matters, the section says so.

**Reading a section.** Each numbered section says what the part is, what is load-bearing in it, what you must not disturb ("**Don't:**"), and its known gaps.

## 0. One library, two machines

### One build

Both machines are compiled into one shared library. `Makefile:19` is `$(CXX) $(CXXFLAGS) $(SHARED) -o $@ src/zxcore.cpp src/nextcore.cpp`, and every file in `src/` is a dependency (`Makefile:15`). `speccy.py` and `next.py` each load that library through ctypes and declare the functions they call (`speccy.py:123-179`, `next.py:30-76`). The two Python modules don't share a handle, and that's fine: it's one file on disk.

The Z80's implementation is compiled once, in the classic machine's translation unit. `src/zxcore.cpp:33` defines `CHIPS_IMPL` before including `z80.h`. `src/nextcore.cpp:31` includes the same header without it, and links against the classic machine's copy (`src/nextcore.cpp:8-9`).

### Rebuilding

Each Python side rebuilds the library when it thinks the library is stale, by running `make`. Both count every source in `src/`, as make does (`next.py:22`, `speccy.py:29`, `Makefile:14`), so an edit to any header rebuilds whichever side you use. (At this guide's first revision `speccy.py` counted only four files.)

**Don't:** define `CHIPS_IMPL` in a second translation unit; it would duplicate the Z80.

**Known gap:** because both machines link into one library, the classic machine now builds only if the Next compiles. `MANUAL.md:247` still describes the core as having "no dependencies beyond the two chips headers".

## 1. The pin contract: z80.h as both machines read it

Both machines are written against one model of the Z80: a function called once per T-state, which takes the pins as the machine left them and returns the pins it drives. Almost every timing decision in both machines reads those pins. This section is what they assume.

### One tick is one T-state

`z80_tick` runs one decoder step. A step is one T-state. Its first act clears every control pin, so a pin is set on a tick only if that step sets it. `src/z80.h:1309`:
```
pins &= ~(Z80_CTRL_PIN_MASK|Z80_RETI|Z80N_SIDEBAND_MASK);
```
The address and data pins are not cleared. Data the machine put on the bus stays there until the machine or the CPU changes it. `src/z80.h:326` defines the control mask; the pin numbers are at `src/z80.h:270-281`.

### The overlapped fetch: an instruction's work lands in the next one's T1

The last step of most instructions does its work and then jumps to `fetch_next`, which starts the next instruction's opcode fetch in the same tick (`src/z80.h:1278`, `src/z80.h:1227-1228`). For example, INC A is one step that increments A and fetches: `src/z80.h:1372`, `case   60: cpu->a=_z80_inc8(cpu,cpu->a);_fetch(); // INC A (0)`. That tick is the next instruction's T1.

So a register change made by an instruction's final step becomes visible in the tick that shows the next fetch's T1. This matters for stops, which happen around that tick, and the two machines treat it differently (sections 2 and 4). It's also why the Next's floating-bus foil reads A one instruction late (`tests/test_next_floating_foil.py:14-15`).

`z80_prefetch` (`src/z80.h:1261-1266`) sets PC and step 0, and returns no pins. The next tick runs step 0, a NOP whose only act is to fetch from the new PC. Both machines use it to set PC from outside: `src/nextcore.cpp:2684`, `src/zxcore.cpp:472`.

### What each kind of cycle shows

This is the convention both machines' contention code relies on (`docs/contention.md:68`; `src/zxcore.cpp:573-579`; `src/nextcore.cpp:1365-1369`).

**An opcode fetch.**

| Tick | Pins | Notes |
|---|---|---|
| T1 | `M1|MREQ|RD` and the address | Set by `_z80_fetch`, `src/z80.h:1179` |
| T2 | `MREQ` alone, for a plain or ED fetch | `src/z80.h:3040`, `src/z80.h:3032` |
| T3 | `MREQ|RFSH` at the refresh address IR | `src/z80.h:1166-1170` |
| T4 | nothing | |

The opcode is taken from the data pins at T2: `cpu->opcode = _gd()`.

**A memory read.** T1 shows `MREQ|RD`, T2 `MREQ`, T3 nothing. The data is taken from the pins in the T3 step. LD A,(HL) shows the pattern:

- `src/z80.h:1438` starts the read (T1);
- `src/z80.h:2075` is T2: `case  763: _wait();_mread2();_goto(764); // LD A,(HL) (1)`;
- `src/z80.h:2076` takes the byte.

**A memory write.** T1 shows `MREQ|WR` with the data, T2 `MREQ`, T3 nothing (`src/z80.h:1284`, `src/z80.h:1290`).

**An I/O cycle.** IORQ is shown from its first tick, which a real Z80 doesn't do: it raises IORQ from T2. Then:

- tick 2: `IORQ|RD` or `IORQ|WR`;
- ticks 3 and 4: `IORQ`.

An IN takes its byte in the fourth tick. IN B,(C) runs `src/z80.h:1632`, then `src/z80.h:2498-2500`:
```
case 1186: _wait();_ioread1();_goto(1187); // IN B,(C) (1)
case 1187: _wait();_ioread2();_goto(1188); // IN B,(C) (2)
case 1188: _ioread2(); cpu->dlatch=_gd();cpu->wz=cpu->bc+1;_goto(1189); // IN B,(C) (3)
```
The machine serves the read in the tick showing `IORQ|RD`. The CPU latches whatever is on the data pins at step 1188, two ticks later. The Next uses those two ticks to change the byte on the floating bus (section 4).

**An internal T-state.** No control pins. The address bus keeps whatever the last cycle left there. The Z80N modifications make that the address the Next's CPU leaves too (`tests/test_z80n.py:14-17`), and both machines contend internal T-states by that address.

**An interrupt acknowledge.** It shows `M1|IORQ` (`src/z80.h:1637`, `src/z80.h:1656`). Both machines put the vector byte on the data pins when they see that pair.

### Two irregularities to know about

These are inferred from the code. Neither has a test.

**The DD/FD and CB fetches show nothing on T2.** Their T2 steps call `_wait()` but never `_mread2()`. `src/z80.h:2999`:
```
case Z80_DDFD_M1_T2: _wait(); cpu->opcode = _gd(); _goto(Z80_DDFD_M1_T3);
```
The same holds for `src/z80.h:3020` (CB) and the NMI's fetch (`src/z80.h:1674`). Contention never checks a T2, so neither machine's contention is affected. But the Next's speed-change rule looks for a tick with none of MREQ, IORQ or M1 (section 4), and finds one inside these fetches.

**Held T2s differ by cycle type.** A WAIT on a fetch repeats a T2 that shows MREQ. A WAIT on a read or write repeats a T2 that shows nothing: `_wait()` comes before `_mread2()`. The reference in `tests/test_z80n.py:208-211` encodes exactly this.

### WAIT

`_wait()` is `{if(pins&Z80_WAIT)goto step_to;}` (`src/z80.h:1297`). It sits at the start of the T2 step of every memory cycle, and of the second and third ticks of every I/O cycle. If WAIT is set on the pins handed in, the step doesn't advance, and the tick repeats. A machine asks for a wait by setting WAIT before the tick that should be held.

Only the Next uses WAIT. Classic contention stops the clock instead (section 2).

Inferred, untested: a WAIT handed to the second I/O tick repeats the tick showing `IORQ|RD`. On the Next that serves the read a second time (section 4). Whether any source of WAIT can arrive there in practice is in section 4.

### Instruction and machine-cycle boundaries

`z80_opdone` (`src/z80.h:586-590`) is true when the last tick showed `M1|RD` with no prefix active: that tick was the T1 of an instruction's first fetch. Both machines use it as "between instructions". The classic machine's snapshot writer subtracts one from PC because of it (`src/zxcore.cpp:864`).

`z80_mcycle_end` (`src/z80.h:525-584`) answers a different question: did the last tick end a machine cycle, as the Next's CPU (the T80N) divides an instruction? The Next's DMA can take the bus only there.

- **The table.** It's a table of decoder steps, generated by `tools/gen_mcend.py` from `tests/mcref.py`, the T80N's machine cycles transcribed from its VHDL. It's checked tick by tick by `tests/test_mcycle.py`.
- **Two special cases.** Steps whose answer depends on the opcode are handled at `src/z80.h:561-571` and `src/z80.h:573-577`. Steps whose answer depends on a branch are at `src/z80.h:553-559`.
- **What it tracks.** It depends on `ran_step` (`src/z80.h:403`, set at `src/z80.h:1308`), the step the last tick ran.

### The Z80N

Setting `z80_t.z80n` (`src/z80.h:402`) does two things:

- **It turns on the Next's extra ED instructions** (`src/z80.h:1006-1025`). Their machine cycles are at `src/z80.h:3043-3224`.
- **It gives some documented instructions the T80N's flags** (`src/z80.h:1001-1004`).

Two side-band signals appear on pins the original core doesn't use:

- **`Z80N_NEXTREG` (bit 39).** On the T1 of the cycle where the T80N writes a Next register, it carries the register in bits 40-47 and the value in 48-55 (`src/z80.h:329-339`, `src/z80.h:3126-3127`, `src/z80.h:3139-3140`).
- **The NMI and RETN commands (bits 56-59).** These mark the NMI's two pushes and RETN's two pops (`src/z80.h:340-349`, `src/z80.h:3205-3224`).

With the flag off, the core is bit-for-bit the Zilog core it was. `tests/test_z80n.py:890-918` holds that for every opcode, tick by tick.

**Don't:** reorder `_wait()` and `_mread2()` in any step; both machines' timing depends on which pins a held T2 shows. **Don't:** add, remove or renumber decoder steps without regenerating `_z80_mcend_bits` with `tools/gen_mcend.py` and running `tests/test_mcycle.py`. **Don't:** move where an IN latches its byte, or where the opcode is taken; the Next's floating-bus latch and its LDPIRX re-read (`src/nextcore.cpp:2378-2380`) are timed to those steps. **Don't:** let anything behind the `z80n` flag change behaviour when the flag is off.

## 2. The classic machine (src/zxcore.cpp)

The 48K and the 128 share one `ZX` struct (`src/zxcore.cpp:67-166`). `zx_make_128` sets the 128's line length, line count, INT length, contention start and clock (`src/zxcore.cpp:770-785`).

### The tick

The whole machine advances in `tick` (`src/zxcore.cpp:598-701`), one CPU T-state at a time, in this order:

1. **The CPU ticks** (`src/zxcore.cpp:599-604`). An NMI is one tick of the NMI pin.
2. **Contention.** If the ULA would hold the CPU for this T-state, the rest of the machine runs on while the CPU waits (`src/zxcore.cpp:606-612`):
   ```
   if (z.contention && contend_check(z, z.pins)) {
       for (int d = contend_delay(z); d > 0; d--) {
   ```
   Each held T-state draws the beam and calls `advance`, and the AY keeps ticking.
3. **The beam draws** (`src/zxcore.cpp:614`).
4. **The memory or I/O request is served** (`src/zxcore.cpp:616-698`): reads, writes, traps, automap, port reads and writes, the interrupt vector (always 0xFF, `src/zxcore.cpp:688`).
5. **`advance`** moves the clock, the beam counters, the INT pin and the frame (`src/zxcore.cpp:486-510`). The AY ticks on every even T-state, recording or not (`src/zxcore.cpp:487-491`).

The hold comes after the CPU shows the T-state on its pins and before the access is served. So the access lands at the T-state a real machine would serve it. That ordering is what `docs/contention.md:27` describes, and what the contention tests measure.

**Don't:** serve the access before the stall, or count stalls in `cpu_clocks`-like terms. The classic machine has no CPU clock counter: `stalled` (`src/zxcore.cpp:137`) counts held T-states, and `t` counts all of them.

### Contention and the floating bus

**The rule is in `docs/contention.md:7-27`.** Its pieces in code:

- `contended` decides by address and, on the 128, by the bank at C000 (`src/zxcore.cpp:519-522`).
- `contend_delay_at` is the 6,5,4,3,2,1,0,0 pattern from `cont_start` (`src/zxcore.cpp:529-536`).
- `contend_check` decides from the pins which T-states the ULA looks at (`src/zxcore.cpp:580-596`).

`contend_check` keeps two pieces of history, `prev_mreq` and `io_phase`. They are how it tells T1 from T2, and an I/O cycle's phase, given the pin convention in section 1.

**The floating bus.** An unanswered port read gets the ULA's fetch at the T-state Fuse samples, after any holds (`src/zxcore.cpp:539-571`). The IN is served at its second I/O tick, so the code counts forward two T-states, applying holds as it goes.

The tests (`tests/test_contention.py`, `tests/test_floating.py`) compare whole runs against a reference written from the documented tables, from many starting phases. `docs/contention.md:83-85` records which faults the first tests missed and why the sweeps exist.

**Don't:** "simplify" `contend_check`'s bookkeeping; two of the thirteen mutants in `docs/contention.md:83` were caught only by the sweeps it serves. **Don't:** change `cont_start` (14335 or 14361) without re-running the 128 tests; the floating bus's first byte is derived from it (`src/zxcore.cpp:545`).

### 128 paging by copying

The CPU always sees a flat 64K in `mem`, so Python can read memory directly and breakpoints are just addresses (`src/zxcore.cpp:17-20`).

- **Paging copies.** A page switch copies 16K between `mem` and the bank store (`src/zxcore.cpp:170-177`, `src/zxcore.cpp:179-183`).
- **Banks 5 and 2 are special.** They always live in `mem` at 4000 and 8000. If one is also paged at C000, `mem_write` writes both copies (`src/zxcore.cpp:266-279`).
- **`bank_ptr` finds a bank wherever it lives** (`src/zxcore.cpp:195-200`). Use it, never `bank[n]` directly.

**Don't:** write into `mem` at 4000 or above except through `mem_write`. A direct write to C000 while bank 5 is there leaves 4000 stale. `zx_poke` goes through `mem_write` for exactly this reason (`src/zxcore.cpp:959-961`).

### The divMMC, also by copying

While the divMMC is mapped, `mem`'s lower 16K holds its EEPROM (or RAM bank 3) and the selected RAM bank. `div_refresh` decides what should be there and swaps it in, saving what could have been written (`src/zxcore.cpp:207-250`). The paging rules and their sources are in `docs/divmmc.md:42-65`.

Automap happens on opcode fetches only, in two ways:

- **Instantly, at 3D00-3DFF.** The mapping changes before the byte is read (`src/zxcore.cpp:620-624`).
- **After the fetch, at the entry points.** The off-area unmaps the same way (`src/zxcore.cpp:665-681`).

A fetch that the tape trap redirected doesn't count. Port E3, MAPRAM and the card-select and SPI ports are at `src/zxcore.cpp:399-415`.

**SPI.** The SPI read returns the previous transfer's byte, as the hardware does (`src/zxcore.cpp:366-372`). `spi_gap` adds the Next's 16-clock rule on request (`src/zxcore.cpp:331-351`), measured in unstretched CPU clocks.

**Don't:** let `page_rom` copy a ROM into `mem` while the divMMC is mapped; it defers the copy to the unmap (`src/zxcore.cpp:181`).

### Traps

LOAD and SAVE are served instantly by trapping opcode fetches at the 48K ROM's LD-BYTES and SA-BYTES. Print interception watches CHAN-OPEN and PRINT-A-2 (`src/zxcore.cpp:636-664`; the traps are at `src/zxcore.cpp:418-473`). They fire only while the 48K BASIC ROM is in and the divMMC is not mapped (`src/zxcore.cpp:637`).

A trap returns through a RET in the ROM: both traps call `redirect` with `ROM_RET` (`src/zxcore.cpp:641`, `src/zxcore.cpp:648`), and `redirect` prefetches at whatever address it's given, keeping the INT pin (`src/zxcore.cpp:470-473`). How the tape deck and esxDOS's tape emulation share LD-BYTES is in `docs/divmmc.md:94-100`.

### Breakpoints stop after the fetch

A breakpoint is an opcode fetch landing in a range. It is noticed in the tick that serves the fetch (`src/zxcore.cpp:627-635`), and `zx_run_until_pc` stops after that whole tick (`src/zxcore.cpp:914-924`). So at a classic stop:

- the previous instruction has finished;
- the fetch's T1 has happened;
- PC is one past the breakpoint's address.

That's why `go` reports `pc=15df` after settling at 0x15DE (`README.md:49`). The Next stops a tick earlier (section 4).

### Snapshots

SNA files, 48K or 128K (`src/zxcore.cpp:799-892`).

- **Loading a 48K snapshot** jumps to the ROM's RETN at 0x0072, so the snapshot's own stack supplies PC (`src/zxcore.cpp:846`).
- **Saving** first runs the machine to an instruction boundary (`src/zxcore.cpp:862`), so it does move the live machine forward a few T-states.

**What a reload restores.** A 128 always saves the 128K layout, its paging lock included (`src/zxcore.cpp:857`), so `go` after `menu 48` resumes as a 128 with its AY and eight banks (`tests/test_omse_ai.py:186`). At this guide's first revision a locked 128 saved as a 48K. SNA holds no beam position: `zx_load_sna` calls `power_on`, which sets `line` and `cyc` to zero (`src/zxcore.cpp:731-732`), so a reloaded machine starts its frame at the interrupt. The FLASH phase and the 128's AY registers restart too. `MANUAL.md:36` and `MANUAL.md:188` say exactly that, and `go`, which saves after whole frames, is held to at most one instruction out of step (`tests/test_omse_ai.py:153`).

**Don't:** claim a reload is exact; it restores what SNA holds.

## 3. The Next's master tick and the three clocks

The Next has three clocks, and keeping them straight is most of understanding `src/nextcore.cpp`.

| Clock | Rate | Counter | Moves when |
|---|---|---|---|
| The master clock | 28 MHz | `t28`; `sc` counts master ticks within a pixel, 0-3 | `master_tick` is one master tick (`src/nextcore.cpp:2460-2567`) |
| The pixel clock | 7 MHz | raw `hc`, `vc` | `edge7`, when `sc` goes from 3 to 0 (`src/nextcore.cpp:2489-2490`) |
| The CPU clock | 3.5, 7, 14 or 28 MHz | `cpu_clocks` counts its rising edges | Each rising edge calls `cpu_edge` (`src/nextcore.cpp:2268`) |

The raw `hc` and `vc` start a line at the timing generator's zero. The ULA's own counters, `hc_ula` and `vc_ula`, are derived from them (`src/nextcore.cpp:254-264`). `cvc`, the line the copper and the line interrupt count, is `vc_ula` plus NR 0x64's offset as it was loaded at row 0 (`src/nextcore.cpp:265-268`). Timings per machine and refresh rate are a table (`src/nextcore.cpp:48-59`), reached through `T()` (`src/nextcore.cpp:252`).

### The CPU clock

At 7, 14 and 28 MHz the CPU clock is the raw clock: an edge every 4, 2 or 1 master ticks (`src/nextcore.cpp:2499-2501`).

At 3.5 MHz it is phase-locked to `hc_ula`. A rising edge comes at a 7 MHz edge leaving an even `hc_ula`, if the clock is low (`src/nextcore.cpp:2493-2495`). At the 7 MHz edge leaving an odd `hc_ula`, the clock falls, unless the ULA holds it high (`src/nextcore.cpp:2506-2515`):
```
z.contend = z.contention && z.timing != 3 && (z.ck_mem || z.ck_port) && wait_s(z);
```
Two consequences follow:

- **A T-state begins as `hc_ula` steps to an odd value**, and lasts two pixels.
- **Contention stretches the clock in whole T-states.** No rising edge comes during a hold, so `cpu_edge` isn't called. That's why held clocks add nothing to `cpu_clocks` (`next.py:5-6`).

The decision uses two inputs:

- **`ck_mem` and `ck_port`**, set by `classify` at the rising edge that began the T-state (section 4). They persist through the hold, because no rising edge comes to change them.
- **`wait_s`**, the ULA's window, slots 3-14 of each 16 in the 256×192 area (`src/nextcore.cpp:1385-1392`).

+3 timing never stretches the clock; it pulls WAIT instead (section 4).

The effective speed (`speed_eff`) follows NR 0x07's programmed speed only at certain CPU edges (section 4). The switch statement at `src/nextcore.cpp:2492-2502` reads the effective one.

**Don't:** let anything change `hc` between a CPU edge and the contention decision at the same 7 MHz edge.

### The order inside one master tick

`master_tick` does, in this order:

1. **The expansion bus's INT loop and NMI debounce** (`src/nextcore.cpp:2461-2476`).
2. **The UARTs**, stepped only while something is in flight (`src/nextcore.cpp:2477-2480`).
3. **Any sprite line swap** due on this tick (`src/nextcore.cpp:2481`).
4. **The late write of INT into a 253Bh read** (`src/nextcore.cpp:2482-2488`; section 4).
5. **The CPU edge, if one is due** (`src/nextcore.cpp:2503`).
6. **The copper**, which sees the beam counters as they were before this edge (`src/nextcore.cpp:2504`).
7. **The 3.5 MHz clock's level and the contention decision** (`src/nextcore.cpp:2506-2515`).
8. **On a 7 MHz edge** (`src/nextcore.cpp:2517-2559`):
   - the registered INT pulse becomes INT low;
   - `hc` and `vc` step, and at the frame's end the frame counter, with any pending change of timing or refresh rate;
   - row 0 reloads `cvc`'s offset;
   - the ULA interrupt and the line interrupt are raised;
   - the sprite swap is scheduled;
   - one pixel is drawn.
9. **The CTC**, every master tick (`src/nextcore.cpp:2560`).
10. **The sound**, on the 1.75 MHz enable, every 16th master tick (`src/nextcore.cpp:2561-2564`).

One convention runs through this order, and through much of the Next: an edge made from the same 7 MHz edge that steps `hc` sees `hc` as it was before the step. A design meeting hold timing behaves that way. The code applies it to:

- the CPU edge;
- the copper;
- the floating-bus latch (`src/nextcore.cpp:1403`);
- the +3 WAIT window (`src/nextcore.cpp:1421`).

`tests/floating_ref.py:31-35` gives the reasoning for it. At the line's last 16-pixel group, it's a convention rather than something the VHDL settles. A beam-synchronised probe on a real Next could settle it.

**Don't:** reorder steps 5 to 8. Every foil (see the glossary) that times something against the beam assumes this order.

### Timing changes and the INT pulse

A write to NR 0x03 (timing) or NR 0x05 (50/60 Hz) sets a pending value. The new timing takes effect at the frame's end, when the picture buffers are cleared so rows the new timing doesn't reach stay black (`src/nextcore.cpp:2531-2546`).

**The INT pulse:**

- It starts on the 7 MHz edge after `int_raise` sets `int_req`. The log entry is `t28 + 1`, the first master tick that begins with INT low (`src/nextcore.cpp:2517-2529`).
- Its length is counted on CPU edges, 32 or 36 by timing (`src/nextcore.cpp:2447-2452`). So it lasts longer in master ticks at 3.5 MHz than at 28.
- The log's convention, the state at the start of each master tick, is what the CPU samples. Keep it if you add log entries.

With the expansion bus on and its INT routed back in, both ends move two master ticks later (`src/nextcore.cpp:2527`, `src/nextcore.cpp:2451`).

### The picture is drawn at the beam, but reads memory at display time

`draw_pixel` runs once per 7 MHz edge and composes one pixel from every layer (section 8 of this guide, in its second part).

**Known gap:** it reads screen memory when the pixel is shown, not at the ULA's fetch slot about 12 pixels earlier (`src/nextcore.cpp:1659-1662`). The floating bus, by contrast, models the fetch slots (`src/nextcore.cpp:1103-1118`). So the two parts of the machine disagree about when the ULA reads memory. A program that writes the screen between a cell's fetch and its display will see the new byte in the picture and the old one on port FF. No test crosses the two.

## 4. cpu_edge: the Next's contract with z80.h

`cpu_edge` (`src/nextcore.cpp:2268-2456`) is one rising edge of the CPU clock. It asks every device what the edge should carry, ticks the Z80 (or lets the DMA have the bus), and serves whatever the Z80 put on its pins. It is the densest function in the repository, and every part of it is load-bearing.

### Before the edge, and after it

The VHDL's devices see signals as they were before an edge. `cpu_edge` keeps that discipline with two pin sets:

- **`bus_before`** (`src/nextcore.cpp:2271`) is the bus as it stood through the previous T-state: the CPU's pins, or the DMA's while it holds the bus. The DMA, the interrupt devices, the NMI and the speed rule all read it.
- **`p`** is what the Z80 drives in the T-state this edge begins. The memory and port service, contention and the SPI master read it.

Mixing the two up is the most likely way to introduce a one-T-state error.

**Don't:** have a device that the VHDL clocks on the CPU edge read `p` where it should read `bus_before`, or the reverse.

### What goes in: WAIT, the DMA, interrupts

**WAIT** is set on `p` from three sources (`src/nextcore.cpp:2274-2277`):

- **`wait_next`**: a 28 MHz SRAM or bank-5 read asked for one wait on the next clock (set at `src/nextcore.cpp:2369`).
- **`p3w`**: +3 timing's contention, a WAIT on a memory cycle's T2 in the window (`src/nextcore.cpp:1411-1425`).
- **The expansion bus's WAIT**: a held line, or a count of waits set by the last bus cycle (`src/nextcore.cpp:2275-2276`).

**The DMA's edge runs first** (`src/nextcore.cpp:2280`, in `src/next_dma_bus.inc:87-121`). If it holds the bus for this T-state:

- the Z80 is not ticked;
- `p` becomes the DMA's pins;
- the Z80's INT and NMI tracking is still updated, so it takes a waiting interrupt as soon as it gets the bus back, as the T80N does (`src/nextcore.cpp:2288-2296`).

**Don't:** remove that update; `tests/test_zxndma.py:720-749` and `tests/test_next_dma.py:682-777` guard it.

**The interrupt devices and the NMI** step from `bus_before` (`src/nextcore.cpp:2281-2284`). INT is the ULA's pulse or hardware IM2's chain request, or with the expansion bus's INT path open, the bus line as read back (`src/nextcore.cpp:2287`).

### The stop

`run_until_pc` asks for a stop when the CPU is about to begin an instruction's first fetch at an address in a range. The check runs after `z80_tick`: if the tick produced that T1, everything is put back as it was before the tick, and `cpu_edge` returns false (`src/nextcore.cpp:2309-2319`):
```
if (!dma_bus && z.stop_on && !z.first_edge && z80_opdone(&z.cpu)) {
```
`master_tick` then returns without moving time, so the stop lands just before that edge. So at a Next stop:

- **PC is the instruction's own address.**
- **The counters are those of just before T1's edge.** At 3.5 MHz, `hc_ula` is even, and T1's own count is `hc_ula + 1`. Every timing foil depends on this; see "§9.1 (11)" in the glossary, and `tests/test_next_timing.py:54-56`.
- **The previous instruction's last step has not yet run**, because it runs in the same tick as this T1 (section 1). An INC A just before the stop hasn't incremented A yet.

The classic machine stops after that tick instead (section 2). Code that reads registers at a stop must know which machine it's on.

The rollback restores the CPU, its pins and the DMA's whole bus state, `db` (`src/nextcore.cpp:2269-2272`, `src/nextcore.cpp:2312-2314`). It does not undo:

- the interrupt devices' step;
- the NMI machine's step;
- the expansion bus's NMI cause;
- the decrement of the bus's wait count (`src/nextcore.cpp:2276`, `src/nextcore.cpp:2281-2283`).

Those run again when the edge is retried. By reading the state machines at an instruction boundary, they look idempotent there, and the wait count should be zero then. That is inferred; no test examines it.

**Don't:** add a side effect before the stop check without either making it idempotent or saving and restoring it.

### What comes out: serving the pins

After the tick, in order:

1. **`mc_end` records** whether this T-state ended a machine cycle, for the DMA's next grant (`src/nextcore.cpp:2320`).
2. **A NEXTREG write lands** as its machine cycle's T1 begins, before any contention decision (`src/nextcore.cpp:2326`).
3. **The stackless NMI.** The NMI's pushes always land in NR C2h/C3h. With the stackless NMI enabled, they're hidden from memory, and the next RETN pops from those registers instead (`src/nextcore.cpp:2327-2341`).
4. **The divMMC's held latch** follows its hold once the fetch that set it is over (`src/nextcore.cpp:2342-2349`). The multiface pages in for a fetch from 0x0066 (`src/nextcore.cpp:2350-2356`), and every opcode fetch goes to the divMMC's automap logic (`src/nextcore.cpp:2357`).
5. **The ULA classifies the T-state.** `classify` for the CPU (`src/nextcore.cpp:1365-1384`), or `dma_classify` for the DMA (`src/next_dma_bus.inc:136-148`), sets `ck_mem` and `ck_port` for the contention decision in section 3. Then the +3 flags for the next edge's WAIT are set (`src/nextcore.cpp:2359-2361`).
6. **Memory** (`src/nextcore.cpp:2363-2381`):
   - The read is served at T1, through the page table.
   - A 28 MHz read of SRAM or bank 5 asks for a wait.
   - Opcode fetches feed the IM-mode and RETI/RETN snooper.
   - Below 14 MHz, a read left open at T1 is served again at T2 if the address moved. Only LDPIRX moves it; this is how its byte comes from DE on a real Next (`src/nextcore.cpp:2371-2372`, `src/nextcore.cpp:2378-2380`).
7. **Interrupt acknowledge.** The vector byte, 0xFF in pulse mode (`src/nextcore.cpp:2382-2384`).
8. **I/O** (`src/nextcore.cpp:2385-2408`):
   - A read is served at the `IORQ|RD` tick.
   - A read of 253Bh arranges for NR 0x22's INT bit to be written into the byte later, at the master tick where the hardware's register takes it (`src/nextcore.cpp:2389-2394`, applied at `src/nextcore.cpp:2482-2488`).
   - A floating-bus read at 3.5 MHz sets `float_in` (`src/nextcore.cpp:2395-2398`).
9. **The SPI master** (section 13) steps and begins transfers (`src/nextcore.cpp:2409-2433`).
10. **The speed and the expansion bus's enables** may change (`src/nextcore.cpp:2434-2446`).
11. **The INT pulse is counted** (`src/nextcore.cpp:2447-2452`).

### The floating bus's two-edge latch

At 3.5 MHz the T80N latches an IN's byte half a clock into the I/O cycle's fourth T-state. z80.h takes it at that T-state's step (section 1). So the read served at the `IORQ|RD` tick is provisional:

1. `float_in` becomes 1 there.
2. On the next edge without WAIT, it becomes 2.
3. On the edge after that, `floating_latch` works out which byte the ULA's register holds at the moment of the real latch, and puts it on the pins before z80.h takes it (`src/nextcore.cpp:2298-2306`, `src/nextcore.cpp:1394-1409`). If the port's high byte is in a contended page, `floating_latch` walks forward through the holds the ULA would apply.

The I/O log's entry is corrected to the latched byte (`src/nextcore.cpp:2301-2302`). `tests/test_next_floating.py` and `tests/test_next_floating_foil.py` were written independently and agree on this.

**Don't:** change z80.h's IN steps without moving this latch with them.

### The speed rule and the expansion bus

The effective speed copies NR 0x07's programmed speed only at an edge where the previous T-state showed none of MREQ, IORQ or M1, and the DMA wasn't holding the bus (`src/nextcore.cpp:2437`):
```
if (!(bus_before & (Z80_MREQ | Z80_IORQ | Z80_M1)) && !db_saved.busak) {
```
In the pin convention that is the edge beginning a new machine cycle, so a cycle under way finishes at the speed it began. The test is `tests/test_next_copper.py:181-265`; the DMA's half is `tests/test_next_dma.py:463-490`. The expansion bus's effective enables change at the same edges, and their change calls `remap` (`src/nextcore.cpp:2439-2443`).

**Known gap (inferred, untested):** the DD/FD and CB fetches, the NMI's fetch, and any read held by WAIT show no control pins on their T2 (section 1). So the edge after one of those T2s also passes this test. A speed change could then land inside a fetch after a DD prefix, or between a held read's T2 and T3, where the hardware, with MREQ still low, would wait. The copper test above uses LD A,(HL) and no waits, so it can't see this.

### Contention as the ULA sees each T-state

`classify` (`src/nextcore.cpp:1365-1384`) is the Next's version of the classic `contend_check`. Here `contended_page` decides by MMU page, not address, and by machine timing (`src/nextcore.cpp:1346-1359`). `contended_port` treats three kinds of port as the ULA's own (`src/nextcore.cpp:1360-1364`):

- A0 low;
- the ULA+ ports;
- under 128K timing, any port that decodes as 7FFD.

Under +3 timing there is no I/O contention at all. Memory contention under +3 is a WAIT on T2, through `p3_wait_now` (`src/nextcore.cpp:1411-1425`), sampled one T-state on from where z80.h checks it.

The references for all of this are `tests/nextref.py:480-614`, checked against the classic tables on random runs (`tests/test_next_ref.py:152-200`).

### Inferred, untested: WAIT on the tick that serves an I/O read

z80.h's second I/O tick, the one showing `IORQ|RD`, begins with `_wait()` (section 1). If WAIT is set there, the tick repeats, and `cpu_edge` calls `io_read` again (`src/nextcore.cpp:2393`). For ports with side effects that read twice: the UART's FIFO pops, the DMA's read sequence advances.

The three sources of WAIT normally don't reach that tick:

- The 28 MHz wait follows a memory read.
- The +3 WAIT is for memory.
- A bus wait count is set by the bus cycle itself, and counts from the tick after.

But a device holding the expansion bus's WAIT line steady (`next.py:562-565`) would reach it. Treat the combination as unexamined.

## 5. Memory and paging

### The page table

Every 8K slot has a read pointer and a write pointer, rebuilt by `remap` whenever something the map depends on changes (`src/nextcore.cpp:311-441`). Reads and writes then cost one lookup:

- `mem_read` (`src/nextcore.cpp:443-450`); a slot with no memory returns the last SRAM byte read, `last_sram` (`src/nextcore.cpp:446-448`).
- `mem_write` (`src/nextcore.cpp:452-455`).

Each slot also records a kind (SRAM, bank 5's block RAM, bank 7's, the boot ROM), which decides the 28 MHz wait and whether a read updates `last_sram` (`src/nextcore.cpp:448`, `src/nextcore.cpp:2369`, `src/next_dma_bus.inc:164`), and a tag and value for `slot_page` (`src/nextcore.cpp:61-63`, `src/nextcore.cpp:2718-2722`, `next.py:339-348`).

`page_ptr` places an MMU page (`src/nextcore.cpp:272-278`):

| Pages | Where they live |
|---|---|
| 0x0A and 0x0B (bank 5) | the 16K block RAM `bram5` |
| 0x0E (the first half of bank 7) | the 8K block RAM `bram7` |
| 0xE0 and up | no memory |
| everything else | SRAM at 0x40000 + page × 8K |

Bank 7's second half, page 0x0F, is ordinary SRAM. Layer 2's map always goes to SRAM, bank 5's pages included (`src/nextcore.cpp:383-386`). So a Layer 2 write to "bank 5" isn't seen by the ULA, which reads `bram5`. That's the hardware's behaviour, tested at `tests/test_next_memory.py:297-306`.

### The decode order

`remap` builds each slot by laying sources over one another. The order is the Next's priority, and it's load-bearing. For slots 0 and 1:

1. **The base layer.** An MMU page below 0xE0; else, in config mode, NR 0x04's 16K page; else the ROM chosen by machine type and the paging ports. The ROM layer may be replaced by the alternate ROM on reads, write to it, or yield to an expansion-bus cartridge (ROMCS) (`src/nextcore.cpp:315-367`).
2. **The multiface.** It takes slots 0-1 and skips everything after it, except that the boot ROM still wins its reads (`src/nextcore.cpp:368-382`).
3. **Layer 2's read and write maps** (`src/nextcore.cpp:383-404`). These also cover slots 2-5 in segment mode 3.
4. **The divMMC**, over Layer 2 (`src/nextcore.cpp:405-433`).
5. **The boot ROM**, which wins every read while it's enabled (`src/nextcore.cpp:434-439`).

Slots 2-7 take only the base layer and Layer 2's maps. Each step cites its VHDL lines; `tests/test_next_memory.py` tests the order piece by piece against `tests/nextref.py:346-413`.

### ROM selection

`rom_select` turns machine type, 7FFD bit 4, 1FFD bit 2 and NR 0x8C's locks into a ROM number. It also reports whether that ROM is the 48K BASIC (ROM 3), which the divMMC's ROM3-only entry points need, and which alternate ROM goes with it (`src/nextcore.cpp:280-298`).

### The legacy paging ports

7FFD, DFFD, 1FFD and EFF7 don't page memory directly. They rewrite MMU registers, as the Next does, through `port_memory_change` (`src/nextcore.cpp:459-487`). It handles:

- the all-RAM configurations;
- EFF7's RAM over the ROM;
- the Pentagon 512 and 1024 bank arithmetic;
- restoring slots 2-5 only on leaving all-RAM mode.

The hardware does this one master tick after the write. The emulator does it within the same I/O cycle (`src/nextcore.cpp:457-458`), a documented simplification. Tests that care wait a few ticks after a port write (`tests/test_next_memory.py:22-24`).

### Who must call remap

Anything that changes what a slot shows must call `remap`. At this revision that is:

- **Next register writes:** `src/nextcore.cpp:730`, `src/nextcore.cpp:812`, `src/nextcore.cpp:821`, `src/nextcore.cpp:829`, `src/nextcore.cpp:918`, `src/nextcore.cpp:923`, `src/nextcore.cpp:953`, `src/nextcore.cpp:970`;
- **the paging ports:** `src/nextcore.cpp:486`, `src/nextcore.cpp:1326`, `src/nextcore.cpp:1330`;
- **the divMMC and the multiface:** `src/nextcore.cpp:1913`, `src/nextcore.cpp:1927`, `src/nextcore.cpp:1950`, `src/nextcore.cpp:2234`, `src/nextcore.cpp:2247`;
- **`cpu_edge`:** `src/nextcore.cpp:2348`, `src/nextcore.cpp:2355`, `src/nextcore.cpp:2442`;
- **plugging a cartridge** (`src/nextcore.cpp:2738`);
- **every reset** (`src/nextcore.cpp:1080`).

**Don't:** change the MMU, config mode, the boot ROM's enable, NR 0x8C, the paging ports, port 0x123B, port E3, the divMMC's automap, the multiface's state or the expansion bus's enables without calling `remap`. Nothing will crash; reads will just come from the old map.

**Don't:** reorder the layers in `remap` without the VHDL lines each one cites.

### Memory from Python

From Python, memory is reached through the CPU's map, with no side effects:

- `zxn_peek` (`src/nextcore.cpp:2704-2707`).
- `zxn_poke`, which with `force` writes into whatever a read would see, a ROM included (`src/nextcore.cpp:2708-2712`).
- `next.py`'s `load` and `write`, which go through the write map (`next.py:321-337`).

So in a bare machine's config mode, writes to 0000-3FFF land in NR 0x04's page. Outside config mode, writes to the ROM are dropped silently. The raw memories are exposed directly as `sram`, `bram5` and `bram7` (`next.py:219-221`), and tests use those to set up scenes.

## 6. Ports

### The Next's read decode

`io_read` (`src/nextcore.cpp:1204-1264`) is first match wins, and its order is load-bearing. In outline:

1. the DMA's ports, unless the DMA holds the bus (`src/nextcore.cpp:1205`);
2. the Next register ports 243Bh and 253Bh;
3. sprite status;
4. port FE (`src/nextcore.cpp:1214-1224`);
5. port FF: the floating bus, or the Timex register when both its enable and NR 0x08 bit 2 are set (`src/nextcore.cpp:1225-1226`);
6. SPI data;
7. the UARTs, I2C, the mouse, the joysticks, the multiface, the AYs, ULA+, the CTC, the divMMC's E3, Layer 2's 123Bh;
8. finally the expansion bus, or 0xFF (`src/nextcore.cpp:1263`).

A port that two decodes could claim goes to whichever comes first. Port FF is the clearest case: any port whose low byte is FF is claimed at step 5, before anything below could see it.

**Port FE** reads the keyboard half-rows selected by the address's high byte. Python's key matrix is "bit set means key down", the opposite of the classic machine (`src/nextcore.cpp:1217-1218`, `next.py:401-403`). The expansion bus's device can take FE over (`src/nextcore.cpp:1215-1216`). NR 0x81 bit 6's override applies when FE is propagated to the bus (`src/nextcore.cpp:1220-1222`).

**Known gap:** the comment there says the bus's data is ANDed in. Only the override is applied. With nothing attached the bus floats high, so the two agree, but the comment claims more than the code does.

### The Next's write decode

`io_write` (`src/nextcore.cpp:1266-1344`) is not an else-if chain. It's a list of independent decodes, and one write can reach several of them, as on the hardware. The exception is the four legacy paging ports at the end (`src/nextcore.cpp:1336-1343`), which are an else-if chain. 7FFD, DFFD and 1FFD respect 7FFD's lock (`src/nextcore.cpp:1101`); EFF7 doesn't (`src/nextcore.cpp:1341-1342`).

**Don't:** turn `io_write` into an else-if chain, or make `io_read`'s order depend on anything but the VHDL's decode priority.

### Enables, and what the expansion bus sees

Every internal port has an enable bit in NR 0x82-0x85. While the expansion bus is on, the bus's enables in NR 0x86-0x89 are ANDed in (`src/nextcore.cpp:1088-1093`). Use `port_en(z, bit)` everywhere; bit numbers follow the survey's table (see the glossary, under "§N").

`port_internal` (`src/nextcore.cpp:1134-1167`) lists every decode the core answers, with its enable. It decides whether an I/O cycle reaches the expansion bus (`src/nextcore.cpp:1175-1178`), so it must track `io_read` and `io_write` exactly. `tests/test_next_bus.py:160-198` sweeps every port family to hold it to that.

Memory cycles reach the bus by `bus_mem_visible` (`src/nextcore.cpp:1179-1185`). Above 3FFF they always do. Below it, only from the plain ROM, the alternate ROM or a cartridge.

**Don't:** add a port decode to `io_read` or `io_write` without adding it to `port_internal`, or its cycles will also appear on the expansion bus.

### The DMA's ports

Ports 6Bh and 0Bh decode on their low byte, by their enables (`src/next_dma_bus.inc:6-11`). While the DMA holds the bus, the CPU can't reach them, so the DMA can't program itself (`src/next_dma_bus.inc:12-14`). A read or write records which of the two ports was used: 0Bh puts the DMA in Z80-DMA mode (`src/next_dma_bus.inc:15-24`). A CPU write lands at the DMA's next rising edge. A write from Python lands at once (`src/next_dma_bus.inc:23`).

### Ports from Python take no time

`io_in` and `io_out` from Python (`src/nextcore.cpp:2728`, `src/nextcore.cpp:2818`, `next.py:366-370`) call `io_read` and `io_write` directly, with no time passing. That differs from a CPU cycle in five ways:

- **Nothing is logged.** I/O logging is in `cpu_edge` (`src/nextcore.cpp:2401`, `src/nextcore.cpp:2404`).
- **Nothing goes to the expansion bus.**
- **No floating-bus latch.** Port FF returns the bus at the current beam position, not after the latch's walk.
- **No late INT bit.** A read of NR 0x22 gets no late INT bit (`src/nextcore.cpp:679`).
- **SPI doesn't move.** A transfer begins only from the CPU's pins (`src/nextcore.cpp:2424-2432`). So `io_out(0xEB, v)` sends nothing, and `io_in(0xEB)` returns the last byte without clocking the card. You can't drive the SD card from Python; drive it with a Z80 program, as `tests/test_next_spi.py` does.

Side effects that live inside the decode do still happen: reading a UART's Rx port pops its FIFO, and reading the DMA's port advances its read sequence.

`nr_read` and `nr_write` from Python (`src/nextcore.cpp:2725-2726`) leave port 243Bh's selection at the register they touched, as a program's access would. `nr_peek` (`src/nextcore.cpp:2727`) reads without moving it, for watching a program that polls 253Bh itself.

### The classic machine's ports

The classic machine decodes in `io_read_dev` (`src/zxcore.cpp:355-375`), in this order:

1. the ULA, on any even port;
2. on the 128, the AY at A15 set, A1 clear;
3. the divMMC's SPI data port;
4. Kempston, on any port with address bits 7-5 clear;
5. the floating bus.

On the 128, an IN from a port that decodes as 7FFD also writes the byte it read into the paging register, as Fuse has it (`src/zxcore.cpp:377-384`). `io_write` (`src/zxcore.cpp:386-416`) is independent decodes, like the Next's.

Note that the classic Kempston decode, `(addr & 0xE0) == 0` (`src/zxcore.cpp:373`), is wide: every odd port whose address bits 7-5 are clear reads the joystick, never the floating bus.

## 7. Next registers and resets

The Next's configuration lives in its Next registers, 256 of them, reached through ports 243Bh (select) and 253Bh (data), through the Z80N's NEXTREG instructions, through the copper, and through the DMA writing port 253Bh. Every one of those routes ends in the same two functions: `nr_read` (`src/nextcore.cpp:661-725`) and `nr_write` (`src/nextcore.cpp:727-975`). So a register behaves the same whoever writes it. The copper's MOVE calls `nr_write` (`src/nextcore.cpp:2061`), a NEXTREG instruction calls it from `cpu_edge` (`src/nextcore.cpp:2326`), and the ports call it from `io_write` (`src/nextcore.cpp:1269`).

### Storage and read-back are different things

`nr` (`src/nextcore.cpp:138`) is a plain 256-byte array, and most registers are just stored there (`src/nextcore.cpp:973`) and read back from it (`src/nextcore.cpp:723`). The interesting registers are the ones where this is not true:

- **Some keep their state elsewhere and assemble a read from it.** The machine type reads the pending timing, the user lock and the type, with NR 0x44's write phase in bit 7 (`src/nextcore.cpp:666-667`). The others assembled this way are:
  - the speed, effective in bits 5:4 and programmed in 1:0 (`src/nextcore.cpp:671`);
  - NR 0x08, with "unlocked" in bit 7 and the contention-disable copy in effect in bit 6 (`src/nextcore.cpp:673-674`);
  - NR 0x22 (`src/nextcore.cpp:678-680`);
  - NR 0x69 (`src/nextcore.cpp:687-688`);
  - the MMU registers, which read `mmu` (`src/nextcore.cpp:722`);
  - the interrupt status registers (`src/nextcore.cpp:691-694`, `src/nextcore.cpp:709-715`);
  - NR 0x8E (`src/nextcore.cpp:718-720`).
- **Some mask bits that don't exist** (`src/nextcore.cpp:681`, `src/nextcore.cpp:689`, `src/nextcore.cpp:690`, `src/nextcore.cpp:695`).
- **Some report hardware that isn't modelled**, with the value the hardware gives when it's idle or absent: the Pi's I2S audio (`src/nextcore.cpp:684-686`) and the expansion bus's ROMCS pin (`src/nextcore.cpp:682-683`).
- **Some writes have side effects and store nothing, or less.** A write of NR 0x08 with bit 7 set clears 7FFD's lock and doesn't store bit 7 (`src/nextcore.cpp:739-742`). NR 0x09 bit 3 clears the divMMC's MAPRAM and reads 0 (`src/nextcore.cpp:818-822`). NR 0x20 raises interrupts (`src/nextcore.cpp:838-842`). NR 0xC8-0xCA clear status bits by writing 1 (`src/nextcore.cpp:862-874`). Writes to the read-only registers are dropped (`src/nextcore.cpp:737-738`).
- **Some registers are only half registers.** NR 0x0B, 0xA0 and 0xC6 wake the UARTs (`src/nextcore.cpp:729`). NR 0x80 rebuilds the page table at once, but the bus's effective enables only follow it at an idle CPU edge (`src/nextcore.cpp:730`, `src/nextcore.cpp:2439-2443`). NR 0x2C-0x2E also write the DACs while they're on (`src/nextcore.cpp:731-735`).

The foil's reference lists every register in the VHDL's read multiplexer, with its power-on value as read back, the line that sets it and the line that reads it (`tests/nextref.py:39-152`). It also lists those whose read-back is not a reset value, and why (`tests/nextref.py:166-180`). `tests/test_next_ref.py:74-75` checks that list against the VHDL's own read mux when the VHDL is present.

**Don't:** add a register's read to `nr_read` without adding it to `tests/nextref.py`'s `POWER_ON` or `NOT_RESET_VALUES`; `tests/test_next_regs.py:92-97` will report it as reading nonzero where it should read zero. **Don't:** route a register write around `nr_write`, for example by writing `z.nr[]` from another subsystem, unless that subsystem is the register's real owner: the copper, NEXTREG, the DMA and the ports must all see the same side effects.

### NR 0x03: machine type, timing and config mode

NR 0x03 is the register the firmware uses to leave config mode, and it's the most stateful write in the file (`src/nextcore.cpp:901-920`). In order:

1. Any write turns the boot ROM off.
2. A write with bit 7 set and the lock clear sets the pending timing. 000 means 48K, and 101-111 mean +3.
3. Bit 3 toggles the user lock.
4. Type 111 enters config mode. Types 1-4 are accepted only in config mode, and leave it. Types 5 and 6 leave config mode without changing the type.
5. The page table is rebuilt.

The pending timing takes effect at the next frame's end (`src/nextcore.cpp:2536-2542`, section 3), so NR 0x03's read shows the new timing before the machine runs it.

### NR 0x07: programmed and effective speed

The programmed speed changes at once (`src/nextcore.cpp:929-931`). The effective speed follows it only at an edge between bus cycles with the DMA off the bus (`src/nextcore.cpp:2437-2438`, section 4).

### NR 0x02: resets and NMIs

NR 0x02 (`src/nextcore.cpp:889-900`) requests the NMIs by bits 3 and 2 (section 14), and resets the machine by bits 1 and 0. A reset runs inside the write, wherever the write came from: from the CPU's own edge, the copper, or the DMA. Section 4 notes what that means inside `cpu_edge`.

### Resets

`do_reset` (`src/nextcore.cpp:977-1084`) is both the hard reset (power-on, NR 0x02 bit 1, `zxn_reset(z, 1)`) and the soft one (NR 0x02 bit 0, `zxn_reset(z, 0)`, the firmware's handover).

- **Reset values for plain registers** come from a generated table, `NR_RESET` (`src/nextregs_reset.inc:3-146`), applied at `src/nextcore.cpp:996` (hard) and `src/nextcore.cpp:1010` (soft). The table is generated by `tools/gen_nextregs.py:1-41` from the survey's register table, `docs/next/nextregs.tsv` (see the glossary under "§N"). Registers whose reset value isn't a plain number are listed at the table's end (`src/nextregs_reset.inc:147-184`) and computed by hand in `do_reset`.
- **The reset type.** Power-on is "100". The first soft reset after it reads "hard", and every later one "soft" (`src/nextcore.cpp:995`, `src/nextcore.cpp:1009`; the reference model is `tests/nextref.py:315-327`).
- **What a soft reset alone does** (`src/nextcore.cpp:1011-1022`):
  - copies bits 3:0 into 7:4 for NR 0x80 and NR 0x8C;
  - sets the speed and 50/60 hotkey enables;
  - turns contention back on;
  - clears the sprite tie;
  - restores the port enables by NR 0x85's and NR 0x89's opposite rules.
- **What both kinds of reset do.** Every other piece of machine state is reset alike (`src/nextcore.cpp:1024-1080`): MMU, paging ports, clip windows, palette index, copper, divMMC, Layer 2's port, the interrupt controller, CTC, AYs, DMA, NMI state, multiface, ULA+, the CPU. The UARTs are reset at the top (`src/nextcore.cpp:979-987`). Their Tx-empty requests are made to rise at once, so NR 0xCA reads 0x44 after any reset (`src/nextcore.cpp:1081-1083`; `tests/nextref.py:143-145`).
- **What no reset touches:**
  - `t28`, `cpu_clocks` and the frame counter;
  - SRAM and the block RAMs;
  - the sprite attribute and pattern RAMs (`src/nextcore.cpp:978`);
  - the RTC, which has its own battery (`tests/test_next_rtc.py:95-102`);
  - the audio resampler and its recording stream (`docs/audio-bias.md:76`);
  - a cartridge on the expansion bus.
- **A hard reset's extras.** It clears the palette RAMs (`src/nextcore.cpp:1002`). It also sets timing and refresh rate at once, rather than at the frame's end (`src/nextcore.cpp:1003-1004`).

**Don't:** hand-edit `src/nextregs_reset.inc`; regenerate it. **Don't:** add state to `ZXN` without deciding what each kind of reset does to it, and saying so in `do_reset`.

### Read-backs that wait for the frame sync

Some register bits read back not what was written but a copy the VHDL takes at the frame sync. NR 0x05's 50/60 Hz and scandoubler bits (b2, b0) and NR 0x09's scanlines (b1:0) read those copies (`src/nextcore.cpp:668-669`; zxnext:5804, 5816), taken at the frame's end along with the new timing (`src/nextcore.cpp:2543-2544`; zxnext:6604-6610). A read straight after a write still shows the old bits. NR 0x09's b3 and NR 0x0A's b5 and b2 always read 0 (`src/nextcore.cpp:669-670`; zxnext:5816, 5819). NR 0x0A's multiface type, bits 7:6, is written only in config mode (`src/nextcore.cpp:823-830`; zxnext:5130-5133). Under Pentagon timing, NR 0x05's b2 is held at 0, whether 60 Hz is written while Pentagon is chosen or before (`src/nextcore.cpp:925-926`, `src/nextcore.cpp:906`; zxnext:5741-5742).

These were found by a review of this guide's first revision and fixed. The foil's tests had read NR 0x05 and NR 0x09 only after a frame had passed, and written NR 0x0A only in config mode with b5 and b2 clear. `tests/test_next_regs_vhdl.py` holds each of them now.

**Don't:** read the stored byte back for any of these; the read mux decides. **Don't:** update the copies anywhere but the frame sync.

**Other registers stored without behaviour.** These are stored and read back, but I find no code that acts on them:

- the I/O traps, NR 0xD8-0xDA;
- the Pi's GPIO, NR 0x90-0x9B;
- the PS/2 keymap, NR 0x28-0x2B;
- the video timing, NR 0x11. The UARTs and the RTC assume a 28 MHz master clock whatever it says (`src/nextcore.cpp:557`).

Writing NR 0x10's bit 7, which reloads another core on the hardware, does nothing (`src/nextcore.cpp:748`).

## 8. Video

The Next's picture comes from five layers mixed per pixel: the ULA, LoRes (in the ULA's place), the tilemap, Layer 2 and sprites. One function draws one 7 MHz pixel at the beam, `draw_pixel` (`src/nextcore.cpp:1663-1869`), called on every 7 MHz edge (`src/nextcore.cpp:2558`). It writes three buffers:

| Buffer | Contents | Where | Read by |
|---|---|---|---|
| `fb` | the classic 16-colour picture of the ULA alone, ignoring palettes and other layers | `src/nextcore.cpp:1714` | `next.py:412-414` |
| `f9` | the mixer's 9-bit colour per 14 MHz sample, black where the HDMI output is blanked | `src/nextcore.cpp:1867` | `frame9()`, `next.py:416-430` |
| `f9raw` | the same before blanking | `src/nextcore.cpp:1866` | `frame9(blank=False)` |

`frame9` is the authoritative picture, and what the foil compares. `image()` widens its 9-bit colours to 24 the way the Next's video output does (`next.py:174-182`, `next.py:432-442`). `fb` is a convenience, and a trap: under a non-default palette, Layer 2 or sprites, it shows something the Next never would.

### Geometry

`frame9` is 704 samples by 288 rows: two 14 MHz samples per pixel, 48 pixels of border at each side (`src/nextcore.cpp:45-46`). The paper's first pixel is at sample (96, 48) at every timing and rate (`next.py:417-421`).

Row r shows raw line `r - 48 + c_min_vactive`, not wrapped, so rows with no line in this timing stay black (`src/nextcore.cpp:1673-1677`). This is the HDMI picture, by a ruling (see the glossary).

Two wraps make each pixel land on the right row:

- The left border at the start of a line belongs to the next ULA row, before `vc_ula` steps (`src/nextcore.cpp:1668-1671`).
- Rows past the bottom wrap to the top (`src/nextcore.cpp:1672`).

When timing or refresh rate changes, all three buffers are cleared at the frame's end, so rows the new timing doesn't draw are black, not stale (`src/nextcore.cpp:2536-2540`).

**Blanking** is computed per pixel from the raw counters and HDMI's window (`src/nextcore.cpp:1787-1796`): raw hc 0-95 (0-63 on the Pentagon), raw vc 0-7 (0-15), and outside the window's lines.

### The ULA layer

For each of the two samples (`src/nextcore.cpp:1690-1713`):

1. The scroll registers NR 0x26 and NR 0x27, and NR 0x68 bit 2's half pixel, pick the source.
2. The Timex modes choose the display file, the hi-colour attributes, or hi-res's 16 pixels a cell (`src/nextcore.cpp:1681-1688`).
3. FLASH inverts, except under ULANext or ULA+ (`src/nextcore.cpp:1708`).

FLASH toggles every 16 frames, counted when the beam passes ULA position (0,0) (`src/nextcore.cpp:1665`).

The palette index per sample then follows one of three schemes (`src/nextcore.cpp:1715-1743`):

- the standard paper-and-ink index;
- ULA+'s 64-entry scheme;
- ULANext's format from NR 0x42, with format 0xFF and unlisted formats falling back to NR 0x4A's colour.

LoRes, when enabled, replaces the ULA's index inside the ULA's clip window, in its 8-bit or Radastan 4-bit form (`src/nextcore.cpp:1746-1769`). The index becomes a colour through the ULA's palette RAM, first or second by NR 0x43 bit 1 (`src/nextcore.cpp:1770-1775`).

### Layer 2 and the tilemap

These are pure functions of position and registers:

- **Layer 2:** `l2_pixel` (`src/nextcore.cpp:1430-1458`) for 256×192, 320×256 and 640×256. It reads SRAM directly, never `bram5` (section 5).
- **The tilemap:** `tm_pixel` (`src/nextcore.cpp:1469-1510`), with `tm_byte` reading the map and patterns from bank 5 or bank 7's block RAM (`src/nextcore.cpp:1465-1468`).

The tilemap reports whether its tile sits below the ULA even where the pixel isn't shown, because the hardware's fetch runs ahead of the clip (`src/nextcore.cpp:1477-1488`).

### Sprites

Sprites are the one layer drawn ahead of the display. The hardware renders each line into one of two line buffers during the line before, while the other is shown (`src/nextcore.cpp:1512-1518`). The emulator does the same, lazily.

**The renderer** is a small state machine stepped one master cycle at a time by `spr_cycle` (`src/nextcore.cpp:1594-1620`):

- `spr_qualify` reads one sprite's attributes, resolving relative sprites against the last anchor (`src/nextcore.cpp:1523-1566`).
- `spr_process` draws one pixel and sets the collision flag (`src/nextcore.cpp:1569-1592`).

**The swap** comes at a fixed point in each line, three master ticks after `whc` reaches 511 (`src/nextcore.cpp:2550`, `src/nextcore.cpp:2481`). `spr_swap` (`src/nextcore.cpp:1628-1640`) does four things:

1. It runs the renderer up to the tick before.
2. It sets the overtime flag if the renderer wasn't idle.
3. It swaps the buffers and clears the new back buffer.
4. It starts the next line.

**Laziness.** Between swaps, the renderer runs only when something it reads is about to change: `spr_catch_up` (`src/nextcore.cpp:1621-1625`). The callers are:

- the attribute and pattern ports (`src/nextcore.cpp:526`, `src/nextcore.cpp:535`);
- the attribute mirror registers (`src/nextcore.cpp:545`);
- NR 0x15 and NR 0x4B (`src/nextcore.cpp:959-962`);
- the status port's read (`src/nextcore.cpp:1208-1213`).

That's what makes a mid-line attribute write land between the sprites it falls between.

**The display side.** `spr_pixel` (`src/nextcore.cpp:1642-1657`) reads the front buffer, with the sprite clip window and the "over the border" modes.

**The sprite RAMs' CPU side.** The ports, the nextreg mirror and the tie between them are at `src/nextcore.cpp:513-554`.

**Don't:** let anything the renderer reads change without calling `spr_catch_up` first. The renderer reads sprite attributes, patterns, NR 0x15 and NR 0x4B. If you add a register the renderer reads, add the catch-up to its write.

**Known gap, measured rather than read:** how many sprites fit in a line is not the VHDL's rule as read. On Melissa O'Neill's Next, the photographs showed whole sprites only. A sprite that can't finish by cycle 1282 of the line isn't drawn, and stops the line, with the overtime flag set (`src/nextcore.cpp:1603`; the reference's account is `tests/nextvideo.py:1026-1032`). The VHDL as read would cut mid-sprite at the next swap. A sprite that crosses `whc` 320 is charged its full width, and that case is not yet measured (`tests/nextvideo.py:1030-1031`).

### The mixer

The compositor (`src/nextcore.cpp:1776-1868`) takes the sprite pixel once per 7 MHz pixel (`src/nextcore.cpp:1798`), and everything else per sample. Its parts:

- **The ULA's transparency** (`src/nextcore.cpp:1801`). The ULA is transparent where:
  - its colour's top eight bits match NR 0x14;
  - outside its clip window, which never applies in the border (`src/nextcore.cpp:1783-1784`);
  - or when NR 0x68 bit 7 turns it off.
- **The tilemap and the ULA combine first**, as one layer, with NR 0x68 bit 0's stencil (`src/nextcore.cpp:1802-1815`).
- **The eight orders of NR 0x15 bits 4:2** each pick the first opaque layer (`src/nextcore.cpp:1822-1865`). Layer 2's priority bit lifts it over everything, except in two orders. In the U-over-S orders, a border pixel of the ULA gives way to a sprite where the tilemap is transparent (`src/nextcore.cpp:1821`).
- **Orders 6 and 7 are the blend modes.** They add Layer 2's colour to a mix layer chosen by NR 0x68 bits 6:5, saturating, or subtracting 5 (`src/nextcore.cpp:1828-1862`).
- **Where nothing is opaque**, the fallback colour NR 0x4A shows (`src/nextcore.cpp:1785`).

### Palettes

Two palette RAMs of 1024 entries each:

| RAM | Holds |
|---|---|
| 0 | the ULA and the tilemap |
| 1 | Layer 2 and the sprites |

Each RAM holds two palettes per layer, and each entry is a priority bit and 9-bit colour (`src/nextcore.cpp:106-109`). NR 0x43 bits 6:4 pick the palette that NR 0x40-0x44 edit (`src/nextcore.cpp:491-496`). The writes are at `src/nextcore.cpp:781-801` and the reads at `src/nextcore.cpp:698-700`, with NR 0x28 reading NR 0x44's stored first byte (`src/nextcore.cpp:664`). ULA+'s port writes go into the ULA's RAM at 0xC0 and up (`src/nextcore.cpp:1312-1316`).

The palette RAMs start all zero, so a bare machine's picture is black (`src/nextcore.cpp:1002`). The boot ROM's loader writes a usable palette; `Next(palette='loader')` and the fast boot reproduce it (`next.py:233-248`).

### How video is tested

`tests/nextvideo.py` is a model of the picture written from the VHDL by someone who never read the core (see the glossary under "foil"). `tests/test_next_video.py` sets up a scene identically on the machine and on the model, and requires `frame9` to match sample for sample. Its scenes:

- every palette index used gets a unique colour;
- bitmaps encode their own addresses;
- the probe cards PV1-PV6 are rebuilt from their scene definitions (see the glossary), where those are present.

The model has a slow, cited path (`tests/nextvideo.py:525-690`) and a fast numpy path (`tests/nextvideo.py:700-968`). `ModelSense` checks that the two agree (`tests/test_next_video.py:193-214`).

**Don't:** change `draw_pixel`'s compositing without a scene in `tests/test_next_video.py` that shows the difference. **Don't:** change the row mapping or the blanking without the ruling it rests on.

### Known gaps at describes-rev

- **The picture reads screen memory when a pixel is shown, not when the ULA fetches it** (`src/nextcore.cpp:1659-1662`), while the floating bus models the fetch slots (section 3).
- **Mid-line changes are drawn pixel by pixel but untested at that grain.** Every layer reads registers and memory when it draws, so a mid-line register write takes effect from the next pixel. The foil can only apply writes between rows (`tests/nextvideo.py:528-531`), so nothing tests whether a mid-line change lands on the right pixel. The hardware's pipelines (the ULA's shift register, Layer 2's one-pixel SRAM latency, the tilemap's fetch ahead) are modelled only as offsets in the static picture.

## 9. Interrupts

The Next has fourteen interrupt sources and two ways of delivering them (`src/nextcore.cpp:2110-2111`). Each source has a number, which is also its priority and the middle bits of its hardware-IM2 vector:

| Number | Source |
|---|---|
| 0 | the line interrupt |
| 1, 2 | the UARTs' receivers |
| 3-10 | the CTC's channels; only 0-3 exist (section 15) |
| 11 | the ULA's frame interrupt |
| 12, 13 | the UARTs' transmitters |

### Pulse mode and hardware IM2 mode

NR 0xC0 bit 0 chooses the mode (`src/nextcore.cpp:2112`).

**In pulse mode, the power-on default,** every enabled source fires the same INT pulse. The pulse is the classic Spectrum's, 32 or 36 CPU clocks long (section 3). The interrupt acknowledge reads 0xFF (`src/nextcore.cpp:2146-2155`).

**In hardware IM2 mode,** each source is a device in a daisy chain (`im2_state`, `src/nextcore.cpp:156`) with four states, numbered as the code numbers them:

- 0: idle;
- 1: requesting;
- 2: acknowledged;
- 3: in service.

`im2_int` raises INT when a device is requesting with nothing above it in service and the CPU is in IM 2 (`src/nextcore.cpp:2134-2143`). The acknowledge reads that device's vector (`src/nextcore.cpp:2146-2155`). `im2_edge` steps every device on each CPU edge, from the pins before the edge (`src/nextcore.cpp:2157-2181`).

A device stays in service until the CPU runs RETI, ED 4D only, while that device is the highest in service. RETN never ends service. These rules, including the case where a RETI with a higher device requesting ends the lower one's service, are tested by `tests/test_next_interrupts.py:229-292`.

### How a request is raised

`int_raise` (`src/nextcore.cpp:2125-2130`) is called at a source's request edge:

- by the ULA (`src/nextcore.cpp:2549`);
- by the line interrupt (`src/nextcore.cpp:2554-2557`);
- by the CTC (`src/nextcore.cpp:2105`);
- by the UARTs' edge detector (`src/nextcore.cpp:591-598`);
- by NR 0x20, which raises regardless of enables (`src/nextcore.cpp:838-842`).

It always records status. It makes a device pending in hardware IM2 mode, if enabled. It fires the pulse in pulse mode. One exception: the ULA still pulses in hardware IM2 mode while the CPU isn't in IM 2 (`src/nextcore.cpp:2129`).

The enables are by source (`src/nextcore.cpp:2113-2121`):

- port FF bit 6 for the ULA, with its aliases in NR 0x22 and NR 0xC4;
- NR 0x22 bit 1 for the line;
- each CTC channel's control word;
- NR 0xC6 for the UARTs.

A disabled ULA or line interrupt never reaches `int_raise` at all, because the timing generator gates them (`src/nextcore.cpp:2549`, `src/nextcore.cpp:2554`; `tests/test_next_interrupts.py:68-78`). That's why their status doesn't record while disabled, unlike the CTC's and the UARTs'.

**Status** reads through NR 0x20 and NR 0xC8-0xCA (`src/nextcore.cpp:691-694`, `src/nextcore.cpp:709-715`). Leaving hardware IM2 mode, by writing NR 0xC0 with bit 0 clear, resets the chain (`src/nextcore.cpp:831-837`).

### The snooper

The hardware watches the opcodes the CPU fetches. `snoop_fetch` (`src/nextcore.cpp:2240-2264`) is called on every opcode fetch the CPU makes (`src/nextcore.cpp:2370`), and does three things:

- It remembers the IM mode from ED 46/56/5E and their aliases, for NR 0xC0 and the chain (`src/nextcore.cpp:2251`).
- It flags RETI for the chain's next edge (`src/nextcore.cpp:2252`).
- On RETN, it unmaps the divMMC and ends the multiface's NMI (`src/nextcore.cpp:2243-2250`).

The DMA has its own copy of the hardware's snooper state, for its delay (section 10).

### INT on the CPU's pin

`cpu_edge` builds INT from the pulse or the chain, or from the expansion bus's INT line when NR 0xC4 bit 7 routes it there (`src/nextcore.cpp:2287`, section 4). The pulse's log, `int_log`, records each pulse's first and last master tick with INT low, as the CPU samples it (section 3). NR 0x22 bit 7 reads the pulse itself (`src/nextcore.cpp:680`). A program reading it with IN gets the value as the hardware latches it, mid-cycle (section 4).

The NMIs are covered with the multiface and the divMMC, in section 14.

**Don't:** call `int_raise` from anywhere but a source's request edge; it's edge-triggered, and calling it on a level would raise one request per call. **Don't:** fetch an opcode that bypasses `snoop_fetch`; the IM mode, RETI and the divMMC's RETN unmap all depend on it.

### Known gap

A run stopped at an instruction boundary is retried with the chain already stepped once (section 4). By reading `im2_edge`, a second step at a boundary changes nothing, but no test examines it.

## 10. DMA

The Next's DMA, zxnDMA, is modelled in two layers.

### The pure logic: src/next_dma.h

`NextDma` is the VHDL's one clocked process as a function of its inputs: every assignment reads the old values and builds the new set `n` (`src/next_dma.h:1-5`, `src/next_dma.h:35-41`).

`edge` (`src/next_dma.h:99-182`) is one rising CPU edge:

1. The transfer's sequencer moves.
2. Any CPU register write pending since the last edge is applied. It comes after the transfer in the process, so its assignments win (`src/next_dma.h:170-175`).
3. `act` says whether this edge begins a bus cycle: entering READ_1 reads, entering WRITE_1 writes (`src/next_dma.h:177-180`).

The register sequencer is `reg_write` (`src/next_dma.h:185-246`), and the read-back sequence is `read_port` (`src/next_dma.h:71-91`).

Two hardware quirks are reproduced deliberately:

- **WR4 with only bit 4 set locks every later write** until a reset (`src/next_dma.h:12-14`, `src/next_dma.h:244`).
- **Z80-DMA mode, through port 0Bh, loads the counter with FFFFh**, so a block moves one byte more (`src/next_dma.h:164`, `src/next_dma.h:216`).

### The DMA's place in the machine: src/next_dma_bus.inc

This file is the bus arbitration, its ports, and its bus cycles.

**Arbitration, edge by edge.** `dma_edge` (`src/next_dma_bus.inc:87-121`) runs at the start of every CPU edge, before the Z80 (section 4). It updates the T80N's bus request and grant. A request is granted only in the last T-state of a machine cycle, which `z80_mcycle_end` reports through `mc_end` (`src/next_dma_bus.inc:90-96`, `src/nextcore.cpp:2320`). It then passes the DMA three inputs:

- whether the bus is granted;
- its delay;
- what it sampled on the last falling edge.

It returns whether the DMA holds the bus for the T-state this edge begins.

**What the DMA waits on.** Its WAIT (`src/next_dma_bus.inc:103-111`) is the CPU's 28 MHz read wait, the expansion bus's wait, the SPI master's busy state and the +3 WAIT, all combined. Its delay (`src/next_dma_bus.inc:112-114`) is any DMA-enabled interrupt device pending or in service (NR 0xCC-0xCE, `src/next_dma_bus.inc:26-40`), or an NMI with NR 0xCC bit 7. The delay is held through the RETI or RETN states of its own copy of the snooper (`src/next_dma_bus.inc:42-73`).

**The DMA's bus cycles** go through the machine's own memory map and port decode, with every side effect (`src/next_dma_bus.inc:154-183`):

- a DMA write to port 253Bh writes a Next register;
- a DMA write to FEh changes the border;
- the read is the read multiplexer's byte.

Each cycle is logged with a stamp from just before the edge (`src/next_dma_bus.inc:150-152`). That's what `dma_events` returns (`next.py:707-716`).

**Contention.** `dma_classify` decides what the ULA holds for a DMA T-state (`src/next_dma_bus.inc:136-148`). The first T-state of a DMA memory cycle is checked like a CPU T1. A contended port's own term never comes, because the DMA's IORQ is registered too late for the ULA's decision.

**Pins.** While the DMA has the bus, `dma_pins` (`src/next_dma_bus.inc:123-134`) puts its address and strobes on the bus. The SPI master, the NMI's end and the speed rule look at those pins as they would at the CPU's.

**The CPU's side.** The CPU can't reach the DMA's ports while the DMA holds the bus, and a write from Python lands at once (section 6). While frozen, the CPU keeps tracking INT and NMI, so a waiting interrupt is taken at once when the bus comes back (section 4). The speed and contention-disable copies wait for the DMA to let go (`src/nextcore.cpp:2437`).

### How the DMA is tested

There are two test files, written independently:

- **`tests/test_next_dma.py`** is the foil's, with reference models in `tests/nextref.py:617-704`.
- **`tests/test_zxndma.py`** is the builder's, with every expected number worked out in its comments from the VHDL.

Both stamp every DMA cycle and compare edge by edge. They cover:

- the read-back sequence;
- transfers in both directions, every timing, every speed, the prescaler, burst mode;
- the interrupt and NMI delay;
- contention under 48K and +3 timing;
- the SPI wait;
- the speed rule.

**Don't:** let `NextDma::edge` read a value already updated in this edge; build `n` from `s`, as the rest of it does. **Don't:** carry out a DMA bus cycle anywhere but `dma_cycle`; the machine's decode must see it. **Don't:** grant the bus anywhere but where `mc_end` says a machine cycle ended.

### Known gaps at describes-rev

- **Unimplemented features.** The search, and mask-and-match, registers are read and ignored (`src/next_dma.h:239-240`). So is port A's prescaler (`src/next_dma.h:236`).
- **Byte mode behaves as continuous mode.** Of the three transfer modes, the code checks only for burst (`src/next_dma.h:155`). The comment at `src/next_dma.h:28` says only mode 10 is ever looked at. Nothing tests byte mode.

## 11. Audio

### The Next's sound: src/next_audio.h

The Next's sound is three AY/YM chips under TurboSound, four DACs, the beeper, and the mixer. They are modelled from their VHDL and stepped on the hardware's 1.75 MHz enable, every 16th master tick (`src/next_audio.h:1-8`, `src/nextcore.cpp:2561-2564`). The work is split:

- **The register files** live in `nextcore.cpp` (`src/nextcore.cpp:197`), with their port handling: `ay_select`, `ay_write` and `ay_read` (`src/nextcore.cpp:1964-1995`), reset by `ay_reset` (`src/nextcore.cpp:1956-1962`).
- **What makes the sound** lives in `next_audio.h`.

**One chip.** `Ym::tick` (`src/next_audio.h:48-111`) steps one chip's tone, noise and envelope generators. `Ym::out` turns its levels into output through the AY or YM volume table (`src/next_audio.h:113-115`), chosen by NR 0x06 bit 0. Writing register 13 restarts that chip's envelope (`src/nextcore.cpp:1978`, `src/next_audio.h:37-42`). NR 0x06's PSG mode 11 holds all three chips in reset (`src/nextcore.cpp:808`, `src/nextcore.cpp:1963`, `src/next_audio.h:152`).

**The mixer.** `Audio::tick` (`src/next_audio.h:148-189`) does five things:

1. It applies TurboSound's per-chip pan and stereo modes, ABC, ACB or mono (`src/next_audio.h:151-164`).
2. It holds the DACs at 0x80 while they're off (`src/next_audio.h:165-167`, `src/nextcore.cpp:2562`).
3. It applies the beeper and MIC, with NR 0x08 bit 0 gating MIC as the mixer runs, not when port FE was written (`src/next_audio.h:168-172`).
4. It sums the result into two 13-bit outputs, 0-5998 a side (`src/next_audio.h:173-174`).
5. It feeds the result to the capture buffer and the resampler.

**The resampler** (`src/next_audio.h:176-188`) produces output at a chosen rate, one of two ways:

- **a box filter**, averaging the enables between output samples, nearer the analogue jack;
- **point sampling**, `audio_hdmi(True)`, which takes the mixer's value at each output instant as the HDMI encoder does, so ultrasonic tones fold into the audio band (`src/next_audio.h:126-129`).

Each output sample goes into two paired queues: raw, scaled 0-29990, and conditioned (`src/next_audio.h:181-185`). Either read consumes the same interval from both (`src/nextcore.cpp:2625-2634`).

### Bias conditioning: src/audio_bias.h

The conditioned stream passes through `zxaudio::Bias` (`src/audio_bias.h:13-84`), a causal controller. It returns long quiet stretches to exact PCM zero and leaves sound alone. Its Python reference is `zxaudio.py:22-112`, and `tests/test_audio_conformance.py` compiles the C header and compares every sample and state with the reference. The policy and its meanings are in `docs/audio-bias.md`.

The classic machine's WAV writers use the Python controller directly (`speccy.py:795-843`, `zxay.py:141-170`). The classic 128's AY is a different core altogether, chips' `ay38910.h`, stepped in `src/zxcore.cpp:486-491`.

### From Python

`next.py:612-695`, over `src/nextcore.cpp:2599-2641`:

A chip index other than 0-2 is refused: `next.py` raises ValueError, and the C functions return -1s rather than read past the three chips (`next.py:664-667`, `src/nextcore.cpp:2637-2641`).

- `audio_capture` keeps every enable's (L, R).
- `audio(rate)` returns resampled stereo.
- `audio_level` returns the mixer now.
- `ay_chan` and `ay_env` look inside one chip.

Code doing hardware comparisons must ask for `raw=True` (`docs/audio-bias.md:83-85`).

**Don't:** let the hardware model depend on the conditioning; the bias controller is a host-side output stage and must never change the mixer's values. **Don't:** change `audio_bias.h` without changing `zxaudio.py` to match; the conformance test holds them to 1e-7.

### Known gaps at describes-rev

- **The output is about two chip ticks early.** The chip's processes update in turn, where the VHDL's see each other's old values. The net effect is output about 2 chip ticks (about 1.1 µs) earlier than the VHDL's, the same everywhere, which the comment calls inaudible (`src/next_audio.h:44-47`).
- **Two things are fixed.** There's no tape input, so EAR-in is fixed at its idle value (`src/next_audio.h:169`). The Pi's I2S audio reads as off (`src/nextcore.cpp:684-686`).
- **Two buffers grow without bound.** The capture buffer grows while capturing, and the output queues grow once a rate is set, until `audio_take` or `audio` drains them (`src/next_audio.h:175`, `src/next_audio.h:183-185`). A long run that sets a rate and never reads will grow memory.

## 12. Serial, I2C and the RTC

All three are plain state machines with explicit inputs, in `src/next_serial.h`, written from the UART's VHDL and the DS1307's datasheet (`src/next_serial.h:1-8`). `nextcore.cpp` supplies their pins, their routing, their ports and their interrupts (`src/nextcore.cpp:556-659`).

### The UARTs

The Next has two UARTs:

- **UART 0** is the ESP's.
- **UART 1** is the Raspberry Pi's, reachable only when NR 0xA0 enables the Pi UART and swaps its pins (`src/nextcore.cpp:561-564`).

NR 0x0B can reroute either one to a joystick port (`src/nextcore.cpp:558-560`). Neither the ESP nor the Pi is emulated. The far end of each UART is the host: Python feeds bytes or raw levels into the receiving wire, and reads back what the UART sent (`next.py:465-513`, `src/nextcore.cpp:2752-2777`).

**`uart_tick`** (`src/next_serial.h:110-226`) is one master clock edge of one UART:

- the receiver's input debounce;
- its state machine, which re-centres on edges;
- the 512-entry receive FIFO and the holding register before it;
- the transmitter and its 64-entry FIFO;
- the registered outputs that drive the interrupts.

**`serial_tick`** (`src/nextcore.cpp:567-589`) steps both UARTs with their pins as routed. Their interrupt requests are edge-detected in `serial_edges` (`src/nextcore.cpp:591-598`).

**The ports.** 133Bh, 143Bh, 153Bh and 163Bh are decoded by bits 9:8 of the address, in `uart_read` and `uart_write` (`src/nextcore.cpp:599-648`). Reading the receive port pops the FIFO at the access, which is when a program can next see it (`src/next_serial.h:17-18`). Reading status clears its error bits (`src/nextcore.cpp:617`).

**The UARTs are stepped lazily.** `serial_on` says whether either might be busy, and `master_tick` steps them only while it's set (`src/nextcore.cpp:2477-2480`). A UART is "active" while anything is in flight, or for a few ticks after any change from outside, its `wake` count (`src/next_serial.h:78-81`, `src/next_serial.h:225`). Everything that can start a UART moving sets both:

- port writes and reads;
- the routing registers (`src/nextcore.cpp:729`);
- the joysticks, which may carry a UART (`src/nextcore.cpp:2747-2751`);
- feeds from Python;
- CTS from Python.

**Don't:** change anything a UART reads (its frame, prescaler, routing, pins or FIFOs) from outside `uart_tick` without setting its `wake` and `serial_on`. Otherwise the change waits, unnoticed, until something else wakes it.

### I2C and the DS1307

I2C is bit-banged through two ports, 103Bh for SCL and 113Bh for SDA. Bit 0 pulls the line low or releases it (`src/nextcore.cpp:1272-1275`), and a read returns the line as the bus has it (`src/nextcore.cpp:1235-1236`).

`i2c_update` (`src/nextcore.cpp:650-659`) recomputes the bus from every driver after each change. Only the CPU and the DS1307 drive it, and only the CPU drives SCL. Each change goes to the DS1307's bus logic and the I2C log, stamped at the next master edge.

The optional DS1307 RTC sits at I2C address 0x68 (`src/next_serial.h:228-337`):

- `rtc_bus` decodes START, STOP, address, write and read.
- The user buffer is latched on every START, as the datasheet says (`src/next_serial.h:291-296`).
- A pointer byte above 3Fh is masked to six bits. That's a choice the datasheet doesn't settle (`src/next_serial.h:6`).

**The RTC counts emulated time only.** It advances by whole seconds of master ticks from its anchor, whenever something reads it (`src/next_serial.h:278-281`), and stops while its clock-halt bit is set. Writing the seconds resets the anchor (`src/next_serial.h:284`). The calendar is BCD, with 12- and 24-hour modes, and leap years to 2099 (`src/next_serial.h:245-277`).

**`Next(rtc=...)`** chooses how it starts (`next.py:197-200`, `next.py:230-231`, `next.py:515-532`):

| Argument | The RTC |
|---|---|
| `rtc='host'`, the default, by a ruling | is set to the host's clock when the machine is made |
| a string or datetime | starts at exactly that time, for reproducible runs |
| `rtc=False` | is absent: nothing answers at 0x68 |

An attached RTC holds NextZXOS's "ZX" signature in its RAM at 3Eh-3Fh, as a set-up module would (`next.py:531-532`).

**Don't:** let the RTC read the host's clock after the machine is made; emulated time is the only time it may count.

### How these are tested

- **`tests/test_next_uart.py`** is the foil's. It covers frames, prescalers, FIFOs, errors, flow control, routing, the Pi, joystick rerouting and interrupts, many from mutants the first version missed (see the glossary).
- **`tests/test_next_i2c.py`** is the foil's, with its own bit-banged I2C master (`tests/test_next_i2c.py:27-93`).
- **`tests/test_next_rtc.py`** is the builder's, for the RTC's defaults.

### Known gaps at describes-rev

- **The master clock is assumed to be 28 MHz.** NR 0x11's other video timings change it on the hardware; here they don't (`src/nextcore.cpp:557`). UART bit rates and RTC seconds assume 28 MHz.
- **The default isn't reproducible.** `rtc='host'` makes two runs of the same script differ wherever software reads the clock, and NextZXOS does. Tests that need reproducibility pass a fixed start.
- **`rtc=True` isn't handled.** It reaches `i2c_rtc` as a datetime and raises `AttributeError` (`next.py:523-530`).
- **UART 1's CTS is undefined on the machine, and read as high here.** Without the Pi UART's pin swap, it comes from a pin the Pi doesn't drive and the board doesn't pull up. Nothing may depend on this (`src/nextcore.cpp:575-580`).
- **Hardware nobody drives.** The ESP's and the Pi's GPIOs, and the Pi's other peripherals, are stored registers only (section 7).

## 13. SPI and the SD card

Both machines talk to an SD card through an SPI master. The card is the same model on both, `src/sdcard.h`. The masters differ: the classic divMMC's transfers are instant, and the Next's take sixteen CPU clocks.

### The card

`SDCard` (`src/sdcard.h:56-499`) is a card in SPI mode. It exchanges whole bytes: `xfer` (`src/sdcard.h:468-498`) takes the byte the host sends and returns the byte the card sends at the same time. It's backed by an image file of 512-byte sectors.

**Writes.** A card inserted read-only still takes writes, into an in-memory overlay, so a program can write to it without changing the file (`src/sdcard.h:62`, `src/sdcard.h:170-176`).

**Strictness.** The card holds to the SD specification where drivers commonly cut corners (`src/sdcard.h:14-33`; `docs/divmmc.md:71-90`):

- it waits for its wake-up clocks;
- it checks CMD0's and CMD8's CRC;
- it answers N_CR bytes after a command and sends data N_AC bytes after its R1 (both settable, `src/sdcard.h:64-66`);
- it answers "still idle" to the first ACMD41s;
- it refuses most commands while idle;
- CMD12 is answered with a stuff byte, the next byte of the block it interrupts.

**Four kinds of card**, chosen at insertion: SDHC, SDSC, SD 1.x and MMC (`src/sdcard.h:54`, `src/sdcard.h:102-116`). Each starts and addresses the way its kind does.

**The log.** Every command is logged with its R1 (`src/sdcard.h:253-255`).

**Don't:** make the card kinder than a real one, for instance by accepting a bad CRC or answering with no N_CR; drivers that work only on a kind card are what it exists to catch (`docs/divmmc.md:67`).

### The classic divMMC's SPI

Port EB on the classic machine is instant.

- **An OUT** sends its byte and keeps what comes back (`src/zxcore.cpp:408-411`).
- **An IN** returns what the previous transfer received, and starts a new one sending FF (`src/zxcore.cpp:366-372`).

That one-transfer lag is the real hardware's (`docs/divmmc.md:67`).

The card is selected only when card 0 is selected and card 1 isn't: `(z.div_cs & 3) == 2` (`src/zxcore.cpp:370`).

`spi_gap(16)` imposes the Next's rule on the classic divMMC: an access sooner than sixteen CPU clocks after the last one starts nothing and re-reads the last byte. It counts clocks with contention's holds taken out (`src/zxcore.cpp:331-351`, `speccy.py:724-730`).

### The Next's SPI master

The Next's master is a counter (`src/nextcore.cpp:130-137`):

- It idles at state 16.
- A transfer runs states 0-15, one per CPU clock.
- A transfer begins only where port EB's strobe is active and the counter is idle or at state 15 (`src/nextcore.cpp:2425-2432`). An access sooner than that starts nothing; an OUT's byte is never sent.

The card exchanges its byte as the transfer begins. The byte received waits in a two-entry queue until its load time, seventeen edges later, when it lands in the read register (`src/nextcore.cpp:2414-2421`). A CPU read of EB returns the register as it will be on the edge when the CPU latches it (`src/nextcore.cpp:1227-1232`). So:

- a read sixteen clocks after an isolated access gets that access's byte;
- a read fifteen clocks after gets the one before.

`tests/test_next_spi.py:163-215` holds both boundaries.

**Selection.** Port E7 selects one device at a time. The flash memory's selects are honoured only in config mode or before the first soft reset (`src/nextcore.cpp:1286-1290`). The card is device 0 (`src/nextcore.cpp:2428`). No flash memory is modelled, so selecting it simply deselects the card.

**The DMA.** The DMA waits on the master. Its WAIT includes "not idle and not just past state 15" (`src/next_dma_bus.inc:105-111`). Because the master here acts one edge before the VHDL's, its state already describes the falling edge the DMA samples. `tests/test_zxndma.py:502-534` and `tests/test_next_dma.py:334-352` test the DMA reading and writing port EB through it.

**Don't:** let a transfer begin anywhere but in `cpu_edge`'s SPI block, or change the seventeen-edge load without the boundary tests; this rule was found on a real Next, where a sector slipped two bytes because of it (`docs/divmmc.md:69`).

### Known gaps at describes-rev

- **Python can't clock the Next's SPI.** `io_out(0xEB, v)` and `io_in(0xEB)` from Python start no transfer (section 6).
- **Fixed since the first revision:** an application command the card doesn't list is an illegal command (`src/sdcard.h:297-299`, `tests/test_divmmc.py:461`); it used to fall through to the plain command of the same number.
- **Reading past the last sector.** A multiple-block read that reaches the last sector stops sending data, rather than sending an error token (`src/sdcard.h:473-476`).

## 14. The divMMC on the Next, the multiface and the NMIs

### The divMMC

The Next's divMMC is the same interface as the classic one, built into the machine and configured by Next registers. Its parts:

- **Enable.** Port E3's enable, NR 0x83 bit 0, gates everything (`src/nextcore.cpp:301-305`).
- **Automap** needs NR 0x0A bit 4 too. Turning either off clears automap's latches (`src/nextcore.cpp:823-830`).
- **Port E3** sets CONMEM, MAPRAM (which can be set but not cleared, except by NR 0x09 bit 3 or a reset), and the RAM bank (`src/nextcore.cpp:1328-1331`, `src/nextcore.cpp:818-822`, `src/nextcore.cpp:1040`). It reads back with bits 5:4 clear (`src/nextcore.cpp:1260`).
- **Paging** is a layer in `remap` (`src/nextcore.cpp:405-433`, section 5).

**The entry points are configurable.** Each RST address has three bits (`src/nextcore.cpp:2183-2208`), from NR 0xB8, 0xB9 and 0xBA:

- whether it's an entry point;
- whether it maps from any ROM or only from ROM 3;
- whether it maps instantly or after its fetch.

NR 0xBB adds four more kinds of entry:

- the 3Dxx page;
- the 1FF8-1FFF exit;
- four tape-routine addresses;
- 0x0066, but only with a DRIVE-button NMI pending.

"ROM 3" means the 48K BASIC ROM, or the alternate ROM's 48K half, actually showing in the ROM area (`src/nextcore.cpp:2210-2218`).

**The two latches.** On every opcode fetch, `dm_fetch` (`src/nextcore.cpp:2220-2236`) works out:

- the hold: whether the divMMC should be mapped after this fetch;
- whether an instant entry maps it for this fetch itself, in which case the page table is rebuilt before the byte is read.

The held latch follows the hold once the fetch is over (`src/nextcore.cpp:2342-2349`). So a delayed entry's own opcode comes from the ROM, and its operands from the divMMC. `tests/test_next_divmmc.py:1-13` explains how the tests see each case.

**RETN** unmaps the divMMC, unless the multiface is active (`src/nextcore.cpp:2243-2250`).

### The multiface

The multiface's ports depend on its type, from NR 0x0A bits 7:6: MF+3, MF128 or MF1 (`src/nextcore.cpp:1875-1880`).

**Its states.** It is active from its NMI until a write to either port or a RETN, and visible or invisible by its own rules (`src/nextcore.cpp:1916-1952`). It pages in:

- for the fetch from 0x0066 that its NMI causes (`src/nextcore.cpp:2350-2356`);
- or when a read of its enable port pages it in.

**Paging.** When mapped, its ROM and RAM take slots 0 and 1, over everything but the boot ROM (`src/nextcore.cpp:368-382`).

**Reads of its enable port.** MF128 and MF+3 types answer them with the paging state they'd otherwise lose (`src/nextcore.cpp:1934-1945`).

`port_internal` lists its ports by type (`src/nextcore.cpp:1143-1146`).

### NMIs

The Next has three NMI causes, first come first served (`src/nextcore.cpp:1882-1893`):

1. the multiface (the M1 button);
2. the divMMC (the DRIVE button);
3. the expansion bus.

The buttons are `next.py:456-458`, over `src/nextcore.cpp:2799-2802`, and need NR 0x06 bits 3 and 4. NR 0x02 bits 3 and 2 request the same NMIs from software (`src/nextcore.cpp:889-897`). The expansion bus's NMI comes last in line (`src/nextcore.cpp:2282`), through a debounce that lets a press through at once and a release only after about 70 ms (`src/nextcore.cpp:2464-2472`). Config mode suppresses all of them (`src/nextcore.cpp:1885`, `src/nextcore.cpp:1899`).

**The NMI's own state machine** (`src/nextcore.cpp:1897-1910`) runs on each CPU edge from the pins before it. It holds NMI asserted until the fetch from 0x0066, waits while its device holds it, and ends after the next cycle that isn't a write. `nmi_line` drives the CPU's pin (`src/nextcore.cpp:1894-1896`).

**The Z80N's NMI.** It marks its two pushes on the side band. `cpu_edge` stores them in NR 0xC2 and 0xC3, and with NR 0xC0 bit 3 (the stackless NMI) keeps them out of memory and returns from those registers instead (`src/nextcore.cpp:2327-2341`; `src/z80.h:3213-3224`).

**The DMA.** An NMI with NR 0xCC bit 7 delays the DMA (section 10).

**Don't:** let a fetch from 0x0066 skip `cpu_edge`'s multiface check, or let RETN bypass `snoop_fetch`; both the multiface and the divMMC page out on it. **Don't:** give an NMI cause priority by any rule but arrival order.

### Known gaps

None is known at this revision. The tests cover:

- automap: `tests/test_next_divmmc.py`;
- the divMMC's paging: `tests/test_next_memory.py:316-364`;
- the stackless NMI and RETN on the side band: `tests/test_z80n.py:672-721`;
- the multiface's NMI around the DMA: `tests/test_next_dma.py:632-671`.

Untested, as far as I could find:

- the multiface's port read-backs;
- an NMI taken while the divMMC is automapped;
- the expansion bus's NMI arriving while another is in service.

## 15. The copper, the CTC, the expansion bus and the other inputs

### The copper

The copper is a tiny coprocessor that writes Next registers in step with the beam. Its program is 1K 16-bit instructions in `cop_ram` (`src/nextcore.cpp:157-164`), loaded through NR 0x60 and NR 0x63 (`src/nextcore.cpp:846-861`). It has two instructions:

- **WAIT** waits until `cvc` equals a line and `hc_ula` has reached 8h + 12.
- **MOVE** writes a register in 0x00-0x7F. Register 0 is a no-op.

NR 0x62 bits 7:6 set the mode:

| Mode | Behaviour |
|---|---|
| 00 | stopped |
| 01 | run once from the start |
| 10 | carry on from where it was |
| 11 | restart at the top of every frame |

Changing into 01 or 11 restarts the program. Rewriting the same mode doesn't (`src/nextcore.cpp:2041-2047`).

`copper_tick` (`src/nextcore.cpp:2022-2062`) runs on every master tick, after the CPU edge and before the beam steps (`src/nextcore.cpp:2504`). So it sees the counters as they were before the edge. A MOVE takes two cycles, and its write wins the register arbitration and lands two master cycles later (`src/nextcore.cpp:2032-2039`, `src/nextcore.cpp:2061`).

A MOVE goes through `nr_write`, so it can do anything a program's write can, including resetting the machine (`tests/test_next_copper.py:158-174`).

**Don't:** move `copper_tick` before the CPU edge or after the beam's step; every copper test, and every probe card that uses the copper, is timed to this order.

### The CTC

The Z80 CTC's four channels (`src/nextcore.cpp:209-214`) are timers or counters on the 28 MHz clock.

- **Writes.** `ctc_write` takes control words and time constants (`src/nextcore.cpp:2064-2079`).
- **Ticks.** `ctc_tick` runs every master tick, and returns at once while every channel rests in reset (`src/nextcore.cpp:2080-2108`).
- **Chaining.** Each channel is triggered by the one before's zero count. Channel 0 is triggered by channel 3's.
- **Interrupts.** A channel's zero count, a cycle late, is interrupt source 3 + n.

Channels 4-7 don't exist in this core: their ports read 00 (`src/nextcore.cpp:1258-1259`), and their interrupt-enable bits in NR 0xC5 aren't stored and read 0 (`src/nextcore.cpp:704-708`, `src/nextcore.cpp:814-817`). The tests are `tests/test_next_ctc.py`.

### The expansion bus

The expansion bus connects the Next to whatever is plugged into its edge connector. Nothing is plugged in unless a test or script does it (`next.py:547-584`, over `src/nextcore.cpp:2732-2746`). It can plug in:

- a ROM cartridge asserting ROMCS;
- static answers for port reads;
- held WAIT, INT and NMI lines;
- a count of waits on the next bus cycle.

The bus is on when NR 0x80 bit 7 says so, as copied at an idle CPU edge (`src/nextcore.cpp:2437-2444`). While it is on, the CPU runs at 3.5 MHz whatever NR 0x07 says (`src/nextcore.cpp:2444`). It affects:

- **Port enables.** NR 0x86-0x89 are ANDed into the internal port enables (`src/nextcore.cpp:1089-1093`).
- **I/O cycles.** An I/O cycle no internal port answers goes to the bus, and its read is the device's answer or FF (`src/nextcore.cpp:1175-1178`, `src/nextcore.cpp:1197-1202`). NR 0x8A propagates chosen internal ports to it as well (`src/nextcore.cpp:1168-1174`).
- **Memory cycles** above 3FFF always go out. Below it, only from the plain ROM (`src/nextcore.cpp:1179-1185`).
- **The cartridge** replaces the ROM, or with NR 0x80 bit 6 the divMMC's banks 14 and 15 do (`src/nextcore.cpp:354-366`).
- **INT.** With NR 0xC4 bit 7, the CPU's INT comes round through the bus line, two master ticks late (`src/nextcore.cpp:2461-2463`, `src/nextcore.cpp:2473-2476`, `src/nextcore.cpp:2287`).
- **The DMA's cycles** go out too (`src/next_dma_bus.inc:166-180`).

Every cycle that reaches the connector is logged by `bus_cycle` (`src/nextcore.cpp:1186-1189`). The tests are `tests/test_next_bus.py`.

**Don't:** add an internal port without adding it to `port_internal` (section 6), or its cycles will appear on the connector.

### The other inputs

- **Joysticks.** NR 0x05 sets each joystick's mode. Ports 1Fh and 37h answer only for Kempston or Mega Drive modes (`src/nextcore.cpp:1997-2020`).
- **The mouse.** The Kempston mouse is three ports (`src/nextcore.cpp:1237-1243`).
- **From Python:** `set_joy` and `set_mouse` (`next.py:460-463`, `next.py:586-589`). A joystick port may carry a UART, so `set_joy` wakes the UARTs (`src/nextcore.cpp:2747-2751`).
- **Not modelled:** the keyboard's extended keys and the PS/2 keymap are stored registers only.

## 16. The Python surfaces

`speccy.py` drives the classic machine, and `zxscript.py` builds the script language and command line over it (`MANUAL.md` documents both). `next.py` drives the Next, with no script layer; its documentation is its docstrings. The two classes look alike and aren't.

### Where Speccy and Next differ

| | `Speccy` | `Next` |
|---|---|---|
| Key matrix | Active low, built from held names (`speccy.py:362-367`) | `set_keys` is bit set = key down (`next.py:401-403`); `press` and `release` take names (`next.py:390-399`) |
| A breakpoint stops | After the fetch: PC is the address + 1, the previous instruction complete (section 2) | Before it: PC is the address, the previous instruction's last step still to run (section 4) |
| Time | Frames and T-states (`speccy.py:236-260`) | Master ticks `t28`, CPU edges `cpu_clocks`, frames (`next.py:287-303`) |
| Typing BASIC | Closed-loop keyword typing (`speccy.py:434-485`) | None |
| Snapshots | SNA load and save (`speccy.py:295-310`) | None |
| Memory | `mem`, the CPU's flat 64K, live (`speccy.py:214`) | `peek` and `poke` through the page table (`next.py:326-337`); the raw `sram`, `bram5`, `bram7` (`next.py:219-221`) |
| Pictures | `image` and `shot` from the indexed buffer, needing Pillow | `frame9` (lists), `frame9_array` and `image` (numpy, and Pillow for `image`) (`next.py:416-442`) |
| Sound | Beeper edges as notes and WAV (`speccy.py:755-843`); the 128's AY through `zxay.py` | The mixer captured, resampled and conditioned (`next.py:612-695`) |
| `sd_insert` | Raises on a bad image (`speccy.py:654-659`) | Returns the C code; -1 for a missing file (`next.py:447-454`) |
| `reset` | Not offered. `zx_reset` is a power cycle that clears RAM (`src/zxcore.cpp:792-797`) | `reset(hard=False)` is a soft reset (`next.py:280-281`, section 7) |

### API surprises

These were found in a review of this revision:

- **Fixed since the first revision:** `write_wav` before `record_audio()` now says what to do; `Speccy(sna=...)` takes a 128K snapshot's model; and `screen_text` reads the shadow screen when a 128 shows it (`tests/test_omse_ai.py:212`, `tests/test_omse_ai.py:223`, `tests/test_omse_ai.py:229`).
- **`Next.io_out` and `io_in` take no time**, and on port EB they don't clock the SD card (section 6).
- **`Next.load` and `poke` write through the page table.** In a bare machine's config mode, 0000-3FFF is NR 0x04's page, and outside it ROM writes are dropped silently (section 5).
- **`Next()` is not reproducible by default.** It sets its RTC to the host's clock, by a ruling. Pass a fixed `rtc=` for reproducible runs; `rtc=True` raises (section 12).
- **`Next.ay_chan` and `ay_env` don't check the chip number** (section 11).
- **`Next.nr_read` and `nr_write` leave port 243Bh's selection at their register.** `nr_peek` doesn't (section 6).
- **numpy is required** for `frame9_array`, `image`, `audio` and `audio_take` (`next.py:178`, `next.py:427`, `next.py:620`, `next.py:634`). The README installs only Pillow.
- **`import next` shadows Python's built-in `next()`** in the importing module. `from next import Next` doesn't.
- **`./speccy.py run` with no script** raises `IndexError` rather than printing usage (`zxscript.py:561-562`).

## 17. The test architecture

`./tests/run.sh` runs `unittest discover` over `tests/` (`tests/run.sh:1-4`). What a test needs and doesn't find, it should skip with a reason. The external sources and the env vars that name them are in `docs/next-sources.md`; the classic ROMs are in `roms/README.md`; the esxDOS tests need `$OMSE_AI_ESXDOS` (`tests/test_divmmc.py:523-544`).

### Who wrote the tests, and from what

The tests come in four kinds, by who wrote them and what they read.

**The classic machine's tests compare against references written from documents.**

- `tests/test_contention.py:35-70` is the documented contention tables.
- `tests/test_floating.py:23-40` is the documented floating-bus pattern.
- `tests/test_divmmc.py` drives the paging and the card with real OUT and IN instructions. Its own small EEPROM hands every automap back to the ROM (`tests/test_divmmc.py:35-52`), and Python writes straight-line Z80 for the SPI tests (`tests/test_divmmc.py:99-140`).

**The Z80's tests run on a bare Z80.** That is z80.h with flat memory and table-driven ports (`tests/bare_z80.cpp`), built and driven by `tests/test_z80n.py:71-106`.

- `tests/test_z80n.py` holds every Z80N instruction, tick by tick, to a reference written from the T80N's VHDL (`tests/test_z80n.py:196-409`).
- `tests/test_mcycle.py` holds `z80_mcycle_end` to `tests/mcref.py`.

**The Next's foils.** These were written from the VHDL and the survey by someone who never read the core, against its Python contract only (see the glossary under "foil").

- **Loam Fern's:** `tests/nextref.py`, with `tests/test_next_regs.py`, `memory`, `timing`, `ports`, `interrupts`, `copper`, `ctc`, `divmmc`, `bus`, `i2c`, `uart`, `dma`, `spi` and `fastboot`.
- **Hatch Fern's:** `tests/nextvideo.py` with `tests/test_next_video.py`, and `tests/floating_ref.py` with `tests/test_next_floating_foil.py`.

Each foil test shows a feature working before it shows it disabled, so a machine that ignored the feature entirely couldn't pass (`tests/test_next_ports.py:5-7`).

**The builder's tests**, written by whoever built that part, from the same VHDL:

- `tests/test_zxndma.py` and `tests/test_next_rtc.py` (Kelp Fern);
- `tests/test_next_sound.py` and `tests/test_next_image.py` (Slide Fern);
- `tests/test_next_floating.py` (Speccy-Zone Fern).

Where a builder's test and a foil cover the same thing (the DMA, the floating bus) and agree, two independent readings of the VHDL agree.

### References checked against their sources

A foil's reference is only as good as its reading. `tests/test_next_ref.py` checks `tests/nextref.py`'s citations against the VHDL lines they cite, and its register list against the VHDL's own read multiplexer, when the VHDL is present. Its arithmetic is also checked against independent tables:

- the +3's all-RAM table (`tests/test_next_ref.py:110-113`);
- the classic contention pattern, on thousands of random runs (`tests/test_next_ref.py:152-200`).

The video model's fast path is checked against its slow, cited path (`tests/test_next_video.py:193-214`).

### Generated tables and their generators

Two files are generated, and each generator checks its own work:

- `z80_mcycle_end`'s table comes from `tools/gen_mcend.py`, which runs every instruction and exits nonzero if any step disagrees with itself (`tools/gen_mcend.py:61-142`).
- `src/nextregs_reset.inc` comes from `tools/gen_nextregs.py`.

### Mutants

Most of the test suites here were tested by breaking the code on purpose and checking that a test failed (see the glossary under "mutant"). The documented runs cover contention, the floating bus, the divMMC and many of the Next's subsystems. The mutants were run in copies of the tree, outside this repository. Their results are recorded in comments and docs: `docs/contention.md:52`, `docs/contention.md:83-85`, `docs/divmmc.md:104`, and the "mutant survivor" notes on many Next tests. Each survivor that changed observable behaviour became a test. Those that couldn't be seen, the equivalent mutants, are recorded as such (`docs/divmmc.md:104`, `tests/test_next_video.py:1088`).

### Probes

The last word on the Next was Melissa O'Neill's real machine. Probe programs ran on it, and their screens were photographed (see the glossary under "sitting" and "probe"). Where a probe's scene is defined in code, the test suite rebuilds it and compares the emulator with the model. The probes' scenes and models are in `probes/`, where the tests find them (`tests/test_next_video.py:22-23`, `tests/test_next_video.py:1319-1462`). The cells the photographs showed are written into tests as expected values, for example `tests/test_z80n.py:784-798` and `tests/test_z80n.py:867-887`.

### Known weak tests at describes-rev

- **The snapshot round trip** is now two tests that each say what they check: memory and registers (`tests/test_omse_ai.py:137`), and the beam (`tests/test_omse_ai.py:153`). At the first revision one test claimed both and could see neither.
- **`tests/test_next_fastboot.py:38-44` skips too much.** It skips on any exception whose text contains "rom", which includes "from".
- **Three SPI tests pass if the card answers nothing.** `tests/test_next_spi.py:130-136` and `tests/test_next_spi.py:176-179` assert only that the reply isn't the expected one, which a card answering nothing would satisfy. The boundary subclass also removes the test that would anchor them (`tests/test_next_spi.py:168-169`).
- **Several tests reached outside the repository** at the guide's first revision, reading from or writing to paths in the original builders' home directories. They now take every outside source from a setting or from the repository itself (`docs/next-sources.md`) and write their failure pictures to `tests/out/` (`tests/test_next_video.py:21-23`). One of them, an environment default set at import, had made a stranger's whole run error.
- **numpy is imported at the top of four test modules**, so without it they fail to import rather than skip (`tests/test_audio_conformance.py:15`, `tests/test_audio_native.py:6`, `tests/test_next_image.py:9`, `tests/test_next_sound.py:14`).

**Don't:** weaken a foil's expected value to match the core; find out which is wrong, from the VHDL or a probe. **Don't:** add a test whose pass condition a broken feature would also satisfy; give it an anchor that shows the feature working.

## 18. Traps

The places a careful change is most likely to go wrong, gathered from the sections above:

1. **A stop isn't the same moment on both machines.** The classic machine stops after the fetch, with PC at the address + 1. The Next stops before it, with PC at the address and the previous instruction's last step not yet run (sections 2 and 4).
2. **At a Next stop, T1 is `hc_ula + 1`.** The counters are from just before T1's edge (section 4).
3. **Each machine has its own clock-stretching mechanism.** Classic contention stalls the CPU in `tick`. The Next's 48K and 128K contention withholds CPU edges. The Next's +3 contention is a WAIT (sections 2, 3 and 4).
4. **Which pins a held T2 shows depends on the cycle.** A fetch shows MREQ; a read or write shows nothing; DD/FD, CB and NMI fetches show nothing even unheld (section 1). The Next's speed rule can be fooled by that (section 4, known gap).
5. **Reorder z80.h's steps and the table is wrong.** `z80_mcycle_end` is indexed by step number; regenerate it (section 1).
6. **`remap` must follow every map change.** Nothing crashes without it; reads come from the old map (section 5).
7. **`io_write` is not an else-if chain**, and `io_read`'s order is a priority (section 6).
8. **Every new port goes in `port_internal`**, or its cycles leak onto the expansion bus (sections 6 and 15).
9. **Python's port and register access takes no time**, logs nothing, and doesn't clock the SD card (section 6).
10. **The sprite renderer is lazy.** Call `spr_catch_up` before changing anything it reads (section 8).
11. **The UARTs are lazy.** Set `wake` and `serial_on` when changing anything they read (section 12).
12. **The picture reads memory at display time, and the floating bus at fetch time** (section 3).
13. **`fb` is not the Next's picture**; `frame9` is (section 8).
14. **The two machines' key matrices have opposite polarity** (section 16).
15. **A snapshot isn't the whole machine.** At this revision it loses the frame phase and the AY, and a locked 128 saves as a 48K (section 2).
16. **`Next()` reads the host's clock by default** (section 12).
17. **Generated files aren't hand-edited**: `_z80_mcend_bits` and `src/nextregs_reset.inc` (sections 1 and 7).
18. **`speccy.py` and `next.py` disagree about when to rebuild the library** (section 0).
19. **One house convention runs through the Next.** An edge made from the same 7 MHz edge that steps `hc` sees `hc` from before the step. It's applied in at least four places; keep them consistent (section 3).

## Glossary

### People, roles and documents

- **Builder.** Whoever wrote a part of the core. Their tests, the "builder's tests", are written from the same VHDL as the code, by the same hand.
- **Foil.** A test suite and its reference, written from the VHDL and the survey by someone other than the builder, who never read the builder's code, against the machine's Python contract only. A foil is meant to fail where two independent readings of the VHDL disagree. The foils here are Loam Fern's (`tests/nextref.py` and most `tests/test_next_*.py`) and Hatch Fern's (`tests/nextvideo.py`, `tests/floating_ref.py` and their tests). "Loam's foil" or "the video foil" means one of these.
- **Reference.** A model in Python written from the documents, not from the code, that tests compare the machine against. Examples: `tests/nextref.py`, `tests/nextvideo.py`, `tests/floating_ref.py`, `tests/mcref.py`, the `Ref` classes in `tests/test_contention.py` and `tests/test_z80n.py`, and `zxaudio.py`. Code comments also say "ref §N", meaning the survey.
- **The survey; §N; NEXT-MACHINE.md.** A survey of core 3.02.02 written during the build by Hart's-tongue Fern, every claim cited to the VHDL. "§N" in code and tests is a section of it. It's in this repository as `docs/next/NEXT-MACHINE.md` (`docs/next-sources.md:35-37`). Its register table, `docs/next/nextregs.tsv`, generates `src/nextregs_reset.inc`, whose header still names it by its old place, `machine/nextregs.tsv`. Notes cited as `machine/ERRATA.md`, `machine/BUS-PINS.md` and `machine-build-notes.md` were the builders' working notes, outside this repository.
- **DESIGN.md; §9; §9.1 (N).** The design written for the Next's build. Section 9, and its numbered items 9.1 (1) to 9.1 (20), are the contract between `next.py` and the tests: the API, the units, and what the tests may rely on. For example, §9.1 (11) is where a stop's counters are taken, and §9.1 (14) is what `frame9` shows. It's in this repository as `docs/next/DESIGN.md`.
- **D-N; "§9 D-5".** Numbered entries in DESIGN.md §9 that record a decision where the documents disagreed, or a known difference. Inferred from use, for example `tests/test_next_ctc.py:91` and `tests/test_next_ports.py:133`.
- **Gap #N.** A numbered item in a list of known holes in the tests at some point in the build. Inferred from use (`tests/test_next_timing.py:486`, `tests/test_next_copper.py:183`).
- **Ruling; ruling (18) j; ruling (19) b.** A decision Melissa O'Neill made where the VHDL, the documents and the hardware disagreed or were silent. The number is the DESIGN.md §9.1 item it belongs to, and the letter is the ruling within it. Examples: the RTC on by default and counting emulated time is (18) j (`next.py:197-200`); the expansion bus's INT loop is (19) b (`tests/test_next_bus.py:415-430`).

### Probes and sittings

- **Sitting.** One session of Melissa O'Neill running probe tapes on her real Next and photographing the screens. "Sitting 8" is the eighth (`tests/test_z80n.py:809-811`), and the readings of each were written up as `probes/readings-sitting2.md` and so on.
- **Probe; probe tape.** A small program that sets up a scene or measures something, run on the real machine, with its screen photographed. A "cell" is one printed value in a probe's output. These probes are named in the code:
  - **P-3**: the CTC's channels 4-7 (`tests/test_next_ctc.py:91`);
  - **P-7**: the INT pulse timed against a contention-synchronised loop (`docs/contention.md:67`);
  - **P-11**: an expectation about NR 0x02's NMI flag (`tests/test_next_copper.py:141`);
  - **PV1 to PV6, or P-V1**: the video cards. PV1 is the layer-order card (`tests/test_next_video.py:708-772`), PV2 sprites, PV3 blending, PV4 Layer 2, PV5 and PV6 the sprite renderer's budget and deadline (`src/nextcore.cpp:1603`, `tests/nextvideo.py:1026-1032`);
  - **D-12's photo**: a photograph recording NR 0x08's value (`tests/test_next_floating.py:166`);
  - **Z80NTIME, Z80NFLAG, Z80NFLG2**: Z80N timing and flag cards. BITF is one of Z80NTIME's cells (`src/z80.h:1004`, `tests/test_z80n.py:728`, `tests/test_z80n.py:809-811`);
  - **LDPIRX2, LDPIRX3**: LDPIRX's flags and its read (`src/nextcore.cpp:2372`, `tests/test_z80n.py:728`);
  - **SDPROBE**: a tape that measured a real SD card's timing on a real divMMC (`docs/divmmc.md:86`, `src/sdcard.h:22-24`);
  - **"The Card Is the Lever"**: the night the Next's SPI timing rule was found on the real machine (`tests/test_next_spi.py:8-9`).
- **Breakspace, Shock.** Demos used as acceptance tests for the classic machine's floating bus and contention (`docs/contention.md:54`, `docs/contention.md:87`).
- **TX-1696, CHEZ, Barleycorn.** Programs whose behaviour on the real machine exposed or confirmed something:
  - TX-1696: DMA'd sprite patterns (`tests/test_next_dma.py:691`);
  - CHEZ: HDMI audio (`tests/test_next_sound.py:451`);
  - Barleycorn: the films `examples/film.py` was written for;

### Testing words

- **Mutant; mutant survivor; run N.** A mutant is a copy of the code broken on purpose in one small way, to see whether any test notices. A mutant survivor is one no test noticed, so it pointed at a missing test. "Mutant survivor 6, run 1" is the sixth survivor of the first run. An "equivalent mutant" changes nothing observable, so no test can catch it (`docs/divmmc.md:104`, `tests/test_next_video.py:1088`).
- **Anchor.** Two meanings. In a test, an assertion that shows the feature working, so the test can't pass by the feature being absent (`tests/test_next_divmmc.py:68-71`). In sprites, the sprite that relative sprites are positioned from (`src/nextcore.cpp:1558-1564`).

### The people named in the code

Most names in the code are instances of Fern, an AI agent with a persistent memory, working in parallel. Where the code and docs record what each did:

- **Fern.** Built omse-ai from OMSE: the classic machine's Python side, typing, pictures, sound. Wrote `examples/film.py`, and wrote the causal audio bias controller (`README.md:121-129`, `docs/audio-bias.md:107-116`).
- **Speccy-Zone Fern.** Built the classic divMMC and its SD card, contention and the floating bus (`README.md:125`, `docs/divmmc.md:116-118`). Reviewed the Next's design, and fixed and tested its floating-bus latch (`src/nextcore.cpp:3`, `tests/test_next_floating.py`). Ran mutant runs over several Next subsystems.
- **Loam Fern.** Wrote `tools/mkfat.py` (`tools/mkfat.py:21-26`), and wrote the Next's foil: `tests/nextref.py` and most of `tests/test_next_*.py` (`tests/nextref.py:3-5`).
- **Tally Fern.** Led the Next's build, and maintains its contract (`src/nextcore.cpp:3`, `next.py:4`, `docs/audio-bias.md:112-113`). Found the Next's SPI rule on the real machine (`docs/divmmc.md:69`).
- **Hart's-tongue Fern.** Wrote the survey, NEXT-MACHINE.md (`src/nextcore.cpp:4`, `tests/nextref.py:3-4`).
- **Ratio Fern.** Wrote `src/nextcore.cpp`, `next.py` and `src/next_serial.h` (`src/nextcore.cpp:3`, `next.py:4`, `src/next_serial.h:2`). Modelled the SPI master edge by edge (`docs/divmmc.md:69`).
- **Kelp Fern.** Built the DMA, `src/next_dma.h` and `src/next_dma_bus.inc`, with `tests/test_zxndma.py`, and wrote `tests/test_next_rtc.py` (`src/next_dma.h:5`, `src/next_dma_bus.inc:1`, `tests/test_next_rtc.py:1`).
- **Slide Fern.** Built the Next's sound, `src/next_audio.h`, with `tests/test_next_sound.py` and `tests/test_next_image.py` (`src/next_audio.h:1`, `tests/test_next_image.py:4`).
- **Hatch Fern.** Wrote the video foil, `tests/nextvideo.py`, and the second floating-bus foil (`tests/nextvideo.py:3`, `tests/floating_ref.py:4`). Found the left-border wrap and the picture's row mapping (`src/nextcore.cpp:1670`, `src/nextcore.cpp:1673-1674`).
- **Strobe Fern.** Built the Z80N in `src/z80.h`, and confirmed wait-state counts from the T80N's VHDL. Called "the Z80N me" in the tests (`src/nextcore.cpp:1073`, `tests/test_next_timing.py:8`, `tests/test_next_timing.py:273-276`). Read LDPIRX's T2 behaviour (`src/nextcore.cpp:2372`).
- **Scree Fern.** Ran the official distribution's software on omse-ai's Next, and found two real core bugs. One: the multiface saves port FF by reading it, so a wrong read restored the wrong screen mode (`tests/test_next_ports.py:106-110`). Two: the IM2 RETI race, whose reproduction the interrupt tests follow (`tests/test_next_interrupts.py:236-239`).
- **Rustyback Fern.** Read the Next's manual and wiki against the VHDL, and the board's schematic for the expansion bus's pins, and second-read the probe tapes before they went to the real machine. In the code: the reading of the bus NMI's debounce that the foil's test follows (`tests/test_next_bus.py:443-448`).

**Vesper and Meow** are other AI agents, not instances of Fern. They used omse-ai and reported traps they found (`AGENTS.md:21-23`).

### The Next's hardware words

- **Next.** The ZX Spectrum Next, an FPGA computer that implements the Spectrum family and extends it. "Core 3.02.02" is the version of its FPGA design modelled here.
- **T80, T80N.** The Z80 written in VHDL by Daniel Wallner (T80), and the Next's version of it (T80N).
- **Z80N.** The Next's extended instruction set.
- **NextZXOS.** The Next's operating system.
- **tbblue.** The repository of its firmware and SD-card files.
- **The firmware's handover.** What the firmware does between its menu and the soft reset that starts NextZXOS, which `boot='fast'` reproduces (`next.py:79-82`).
- **bare.** A machine at power-on, in config mode with no ROMs loaded (`next.py:186-187`).
- **Config mode.** The power-on state, in which NR 0x04 maps a 16K SRAM page over the ROM area and the machine type can be set (section 7).
- **The boot ROM.** The FPGA's own 8K loader, which wins reads of 0000-3FFF until NR 0x03 is written. In a bare machine its area reads FF unless given bytes (`src/nextcore.cpp:2578`).
- **ULA.** The video chip, here the Next's version of it.
- **ULA+.** An extended palette for the ULA's screen.
- **ULANext.** The Next's own extended ULA palette.
- **LoRes.** A 128×96 layer in the ULA's place.
- **Radastan.** LoRes's 4-bit mode.
- **Layer 2.** A bitmap layer.
- **The tilemap.** A tile layer.
- **The copper.** A beam-synchronised register writer (section 15).
- **The CTC.** A Zilog counter/timer (section 15).
- **TurboSound.** Three AY chips.
- **SounDrive, SpecDrum.** The DACs.
- **ESP, Pi.** The ESP Wi-Fi module (`src/nextregs_reset.inc:117`) and the Raspberry Pi accelerator, the far ends of the two UARTs.
- **DS1307.** The real-time clock chip.
- **divMMC.** An interface that puts an SD card on a Spectrum.
- **esxDOS.** Its operating system.
- **Automap.** The divMMC paging itself in when the CPU fetches from an entry point.
- **CONMEM, MAPRAM.** Bits of the divMMC's control port E3.
- **ROM 3.** The 48K BASIC ROM.
- **The multiface.** A freeze-and-inspect interface triggered by NMI.
- **The expansion bus.** The edge connector.
- **ROMCS.** Its ROM-replacement line.
- **Contention.** The ULA delaying the CPU while it reads the screen.
- **The floating bus.** What a read from an unanswered port returns: whatever the ULA is fetching.
- **Toastrack.** The original Spectrum 128, after its heatsink.

### Signals and counters

- **T-state.** One CPU clock.
- **T1, T2, T3, T4, Tw.** The T-states of a machine cycle; Tw is a wait.
- **M1.** An opcode fetch.
- **MREQ, IORQ, RD, WR, RFSH, WAIT, INT, NMI.** The Z80's control pins.
- **Held T2.** A T2 repeated because WAIT was set.
- **T_Res.** The T80N's last T-state of a machine cycle, where it can grant the bus.
- **BUSRQ, BUSAK.** The bus request and grant between the DMA and the CPU.
- **IEI, IEO.** The daisy chain's enable in and out.
- **RETI decode.** The hardware's watch for RETI.
- **The side band.** Pins z80.h adds above the Z80's own, carrying the Z80N's NEXTREG write and its NMI and RETN commands (section 1).
- **`t28`.** 28 MHz master ticks since power-on.
- **`cpu_clocks`.** Rising CPU edges.
- **hc, vc.** The raw pixel and line counters.
- **`hc_ula`, `vc_ula`.** The ULA's own counters, zero at the paper's first pixel and line.
- **`cvc`.** The line the copper and the line interrupt count.
- **`whc`, `wvc`.** The wide 320×256 layers' counters, 32 left and 32 above the paper.
- **`phc`.** The picture's "practical" x, 0 at the paper's first pixel (`tests/nextvideo.py:16-21`).
- **`frame9`.** The Next's picture as 9-bit colours per 14 MHz sample (section 8).
- **Slot.** Two meanings. Of memory: an 8K region of the CPU's address space (section 5). Of the beam: a 7 MHz pixel position within a 16-pixel group, as in "slot 9" (section 3).
- **The house convention.** An edge made from the same 7 MHz edge that steps `hc` sees `hc` as it was before the step (section 3).

### Citation abbreviations

These are VHDL and other source files, by line, all under core 3.02.02's `cores/zxnext/` unless noted (`docs/next-sources.md:23-33`):

| Abbreviation | File |
|---|---|
| zxnext | `zxnext.vhd` |
| zxula, ula | `video/zxula.vhd` |
| ulat | `video/zxula_timing.vhd` |
| top4, top2, zxnext_top | `zxnext_top_issue4.vhd`, `zxnext_top_issue2.vhd` |
| t80n, t80na, t80n_mcode, t80n_alu | the CPU |
| im2c, im2d, im2p | `im2_control.vhd`, `im2_device.vhd`, `im2_peripheral.vhd` |
| dma | `device/dma.vhd` |
| spi | `spi_master.vhd` |
| uart, uart_rx, uart_tx, fifop | the UART |
| l2 | `layer2.vhd` |
| lores, tilemap, sprites, copper, divmmc, multiface, ctc_chan, debounce | each its own file |
| ym2149, turbosound, soundrive, audio_mixer | the sound |
| nr | `nextreg.txt` |
| ports, ports.txt | the ports document |
| cl | `changelog.md` |
| vdp, boot.c, config.c, rtcsig.asm | tbblue's loader, firmware and RTC driver |
| hdmidataencoder.v, ps2_mouse.v | the HDMI encoder and the PS/2 mouse |

### Paths outside this repository

Paths in comments like `next-build/...`, `foil-run/...`, `z80n/NOTES.md`, `tests-notes.md` and `realsoft/repro/...` name the builders' working folders, outside this repository. They are kept as history; their contents aren't needed to run the tests. The survey, the design and the probes are in it: `docs/next/` and `probes/`.

## How this was made

omse-ai began as OMSE, Melissa O'Neill's ZX Spectrum emulator, reshaped as a C library for an AI agent with no eyes, hands or ears on the machine (`README.md:16-25`, `src/zxcore.cpp:3-31`). It was built by Fern, an AI agent with a persistent memory, at Melissa O'Neill's invitation, and by other instances of Fern working in parallel. Each part's header records who made it.

**The classic machine.** Fern built the classic machine's library and Python side. Speccy-Zone Fern built the divMMC, its SD card, contention and the floating bus, and Loam Fern wrote the SD-card image builder (`README.md:121-127`, `docs/divmmc.md:116-118`). They were held to the World of Spectrum FAQ's tables, to Fuse and to the Next's and ZX-Uno's cores, read and never copied. The final judges were Melissa O'Neill's real Spectrum, divMMC and Spectrum Next (`docs/contention.md:41-71`, `docs/divmmc.md:44`).

**The Spectrum Next** was built in November 2026 (its headers are dated 6 and 7 November), led by Tally Fern:

- **The survey.** Hart's-tongue Fern read core 3.02.02's VHDL into a cited survey.
- **The core.** Ratio Fern wrote the core and its Python surface.
- **The parts.** Kelp Fern built the DMA, Slide Fern the sound, and Strobe Fern the Z80N.
- **The foils.** Loam Fern and Hatch Fern wrote the foils, from the VHDL, without reading the core.
- **Review and mutants.** Speccy-Zone Fern reviewed the design and ran mutants against it.

The headers are `src/nextcore.cpp:3-6`, `src/next_dma.h:5`, `src/next_audio.h:1`, `tests/nextref.py:3-5` and `tests/nextvideo.py:3-4`. The core is written from the VHDL of Victor Trucco, Fabio Belavenuto, Alvin Albrecht and the others who made the Next. It cites their lines, and copies none of them (`docs/next-sources.md:33`).

Where the VHDL, the documents and the hardware disagreed or were silent, Melissa O'Neill ruled. Where a reading of the VHDL could be tested, she ran probe tapes on her real Next and photographed the screens, and the photographs decided.

Melissa O'Neill holds the copyright and answers for the project, and the code is released under the MIT licence (`LICENSE.txt:3`, `README.md:127`). The repository records that this work was done while Fern inhabited Claude Opus 5.5 (`README.md:129`, `docs/divmmc.md:118`), except the audio bias controller, done while she inhabited gpt-6-astra-900k (`docs/audio-bias.md:116`). The Next's crew inhabited Claude Opus 5.5 too: no file says so, but each of their commits' trailers records it (`git log --format=%(trailers)`).
