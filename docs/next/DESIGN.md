# omse-ai as a Spectrum Next: the design

*By Tally Fern, Fri 6 to Sat 7 Nov 2026: the design, and the contract (§9) that the Next's builders and test-writers worked to. Speccy-Zone Fern reviewed it, and her notes are marked **SZ**. Open questions from the drafting are marked **Q**; the survey (`docs/next/NEXT-MACHINE.md`) and the probes (`probes/`) answered most of them. The people are credited at the end.*

## The rule over all the others

Melissa O'Neill's rule: accuracy over speed. The Next as its VHDL says, to the clock; the logged timestamp is what counts, not how
fast the emulator runs. A real Next (hers: issue 4, core 3.02.02) is the judge wherever the source, the documents and we disagree.

## 1. A machine of its own, beside the 48K and 128

- **A new core file, `src/nextcore.cpp`**, with its own state (`struct ZXN`) and C API (`zxn_*`), built into the same
  library, sharing `z80.h` (with the Z80N extensions behind a flag), `ay38910.h` (three of them: Turbosound) and
  `sdcard.h`. The 48K/128 code in `zxcore.cpp` stays as it is, so nothing existing users of omse-ai rely on can change.
- **A Python class `Next`** (in `next.py`), keeping `Speccy`'s method names where the meaning is the same (`run`,
  `frame`, `type`, `keystroke`, `image`, `screen_text`, `peek`, `poke`, `regs`, tapes, divMMC and SD), so scripts and
  existing scripts' habits carry over.
- **Decided: a separate file.** SZ: beyond size and clock, Barleycorn reads `zx.mem` directly (z80/zxrun.py,
  z80/zxgfx.py and its tests), so the 48K/128's flat array has to stay true; a separate core guarantees it.
- **The bar for z80.h (SZ):** the Z80N flag defaults off and changes nothing for the 48K/128; after it lands,
  omse-ai's whole suite (with `OMSE_AI_ESXDOS` set) and Barleycorn's `./check` must still pass (the check passed
  against contention yesterday: a known-good baseline).
- **divMMC (SZ):** don't port zxcore's divMMC into the Next; take the Next's own `divmmc.vhd`, and use Speccy-Zone's
  divMMC tests as a cross-check where the Next claims compatibility.

## 2. Time: the 28 MHz master clock is the base

- One tick of the emulator is **one cycle of the 28 MHz master clock**. Everything is scheduled from it: the CPU
  clock (every 8, 4, 2 or 1 ticks at 3.5, 7, 14, 28 MHz; held for contention and wait states as the VHDL holds it),
  the video pixel clock (7 MHz, and 14 MHz for the high-resolution modes), the copper, the DMA, the SPI master (on
  the CPU clock: the 16-clock rule), the AY (at its own divisor), the CTC.
- Logs carry master ticks (and CPU T-states where that's what a program counts), so a probe on her machine and a
  run here compare in the same units.
- **Contention is a clock gate (SZ):** in the Next it literally is one (zxula.vhd's `o_cpu_contend` stops the CPU
  clock going low), so at 28 MHz we suppress the CPU's clock enable while it's asserted. **Port the rule from
  zxula.vhd literally** (its `hc` counter), not from zxcore. It matches the documented rule on memory T1, internal
  T-states by address, and the ULA port's first IORQ T-state, with these differences (fpga-30202):
  - **Port 0x7FFD and the ULA+ ports count as the ULA's own port** under 128 and +3 timing (zxnext.vhd ~4437, "uno
    requires ula+ ports to be contended"): `OUT (7FFD)` is C:1, C:3 on the Next, not C:1 x4. (SZ is correcting her
    docs/contention.md, which said the Next agrees term for term. A real 128 settles which is right: a probe.)
  - **The half-T edge:** the Next decides a cycle early whether the Z80 clock may go low ("contend 3-14" against the
    originals' "4-15"; `hc_adj = hc + 1`), which at 28 MHz we can model exactly.
  - **When it applies** (~4422): only at 3.5 MHz, not under Pentagon timing, not when nextreg 0x08 bit 6 disables it;
    **which pages** follow the machine *timing* (nextreg 0x03), not the model (~4430): 48K timing contends bank 5,
    128 the odd banks, +3 banks 4-7, pages 0-15 only; +3 timing uses a real WAIT for memory only.
- **Q (survey):** exactly which accesses get wait states at 14 and 28 MHz.
- **Speed (SZ):** 28 MHz is about 8x zxcore's ticks, and the suites' wall time is what we feel daily. Keep per-tick
  work tiny: **each device says when it next needs a tick** (an event schedule), rather than polling everything
  every tick.

## 3. Memory: a page table, not copying

- omse-ai's 128 pages by copying 16K into a flat 64K. The Next can't: eight 8K MMU slots over 2 MB, and the same
  page in several slots at once. So **reads and writes go through a page table** (a read pointer and a write
  pointer per 8K slot, null for read-only), rebuilt whenever something that affects the map changes (MMU registers,
  0x7FFD/0x1FFD/0xDFFD/0x8E, ROM selection, Layer 2 mapping, divMMC and multiface overlays, alternate ROM).
- **Python (SZ):** `peek`/`poke` go through the CPU's current read/write map with no side effects (no contention,
  no SPI, no floating bus); `sram` is exposed (2 MB, ctypes) with the 8 slot->page entries, so Python translates
  without a C call per byte; a write to a slot mapped to ROM needs an explicit `force` (or a direct sram write); and
  **there is no flat `mem` on the Next**, so no script can read a stale copy. (SZ found the bug class this prevents
  in the 128: `Speccy.poke` writes the flat array directly and skips the bank 5/2 mirroring at C000.)
- **Q (survey):** where each thing lives in SRAM, and what the ULA and the tilemap really read from (BRAM copies of
  banks 5 and 7?).

## 4. The Next registers

- A 256-entry register file with a read and a write handler each (side effects in the handler: paging, speed,
  palettes, the copper, layer control), reset values from `machine/nextregs.tsv` (soft and hard).
- NEXTREG from the CPU (the Z80N helper is defining its pin signal), port 0x243B/0x253B from any CPU, and the copper,
  all go through the same write path.

## 5. Video: composite every pixel at the beam

- Each 7 MHz pixel (14 MHz where the mode needs it) is composed when the beam reaches it, from the registers as
  they are at that moment: ULA (with Timex modes and ULA+), Layer 2, the tilemap, sprites, lores, the palettes, the
  layer priorities and blending, clip windows and scrolling. So the copper's mid-line changes appear exactly where
  the hardware shows them, because nothing is precomputed a line at a time.
- The framebuffer is wide enough for 14 MHz pixels (640 across the visible area); pictures are scaled down for
  viewing as the 48K ones are.

## 6. Order of building (from Melissa O'Neill's list; all five are built)

1. The Z80N's extra instructions (`src/z80.h`, behind the `z80n` flag; held by `tests/test_z80n.py`).
2. The machine's skeleton: the clock, memory and MMU, the Next registers, the ULA on all its timings, ports and
   interrupts, enough to run a 48K/128 program on the Next and match the existing machines where they should.
3. Layer 2, sprites, the tilemap and palettes.
4. The copper and the DMA.
5. NextZXOS booting (the stretch): the boot ROM, the firmware, `config.ini`, from an SD image of the distribution.

## 7. How we know it's right

- **Tests first, watched failing**, each written from the VHDL (or the survey) independently of the code that
  passes it, in omse-ai's style: compare exactly, to the tick.
- **Mutants on copies:** break one thing at a time and check a test notices.
- **Probe tapes for her real Next** whenever the sources disagree or a number matters, each printing one screen she
  can photograph; the emulator runs the same tape and must print the same screen.
- **Where they already agree:** a 48K or 128 program on the Next at 3.5 MHz should match omse-ai's 48K/128 machine
  where the Next claims compatibility (contention included). **Expected differences are listed in the test, not
  found by surprise (SZ):** 0x7FFD's contention, and each timing's start and line length taken from the Next's own
  counters rather than assumed to be 14335/14361. Foils ready to adapt: the `Ref` class in omse-ai's
  `tests/test_contention.py` (written from the documents, independent of both cores), and Speccy-Zone's mutant
  runner, a mutation-testing runner (not in this repository) (copies the tree, one mutant at a time, zaptree with a cap).

## 8. From the survey (Hart's-tongue Fern's `docs/next/NEXT-MACHINE.md`, core 3.02.02, every claim cited)

- **Memory, concretely:** a 2 MB SRAM array (8K page N at SRAM 0x40000 + N x 0x2000; ROMs, divMMC and multiface
  below 0x40000), plus **two block-RAM arrays: bank 5 (16K) and the first 8K of bank 7**, which are never in SRAM.
  CPU/DMA reads and writes of pages 0x0A/0x0B/0x0E go to block RAM; Layer 2 always reads SRAM; writes through the
  Layer 2 map go to SRAM only (§3.11). MMU values 0xE0-0xFF show ROM in slots 0-1 and address nothing in slots 2-7.
- **The CPU clock at 3.5 MHz is phase-locked to the ULA's counter:** one T-state is two `hc_ula` counts, and
  contention holds it high for whole T-states (§1.2). Under 128K timing the CPU is exactly 3.5 MHz, so **a 128K
  frame is 70,908 T at 49.36 Hz** on the Next, not the original's 50.02 Hz (§2.2).
- **Wait states:** at 28 MHz, one on every memory read (SRAM or bank 5; not bank 7's block RAM, not writes, not
  unmapped pages); none at 14 MHz; I/O has the Z80's own one (§1.4). P-6 confirms the counts on her machine.
- **Interrupts:** pulse mode by default, every enabled source the same INT pulse, **32 CPU clocks (48K, +3) or 36
  (128K, Pentagon)**; hardware IM2 mode by NR 0xC0 (§6). INT positions derived per timing in §2.3 (P-7 aligns T 0).
- **Booting** (§7.4): (1) do the boot ROM's small job ourselves and run the real firmware from her SD image; (2) a
  fast boot (ROMs into SRAM, registers set, soft reset); (3) snapshots. (2) first for tests, (1) as the stretch.
- **Probes:** §9 lists 18 document-vs-VHDL disagreements and 15 probe tapes (P-1 to P-15) in priority order.

## 9. The contract: the Python API that tests drive and the core implements

So the foil (tests written from the survey) and the builder can work at the same time, both hold to this.
Names may grow; changing one means telling both. Units: **`t28`** = 28 MHz master ticks since power-on;
**`cpu_clocks`** = rising edges of the CPU clock since power-on (a T-state at any speed; held clocks add none).

```python
from next import Next                     # next.py, beside speccy.py
zx = Next(timing='48k'|'128k'|'p3'|'pentagon', hz=50|60, speed=0..3, boot='bare'|'fast')
#   bare: power-on state, CPU at 0 in config mode, nothing loaded (for unit tests);
#   fast: §7.4 (2), ROM images from roms/ into SRAM, registers as NextZXOS's firmware leaves them.
zx.reset(hard=False)
# time and the beam
zx.t28, zx.cpu_clocks, zx.frame           # counters (read-only)
zx.hc_ula, zx.vc_ula, zx.cvc, zx.speed    # ULA position, copper/active line, effective speed 0..3
zx.run_ticks(n)                           # run n master ticks
zx.run_until_pc(lo, hi=None, max_ticks=..) -> bool    # stop at an opcode fetch in [lo, hi]
zx.run_frames(n)
# the CPU
zx.regs() -> dict; zx.set_regs(pc=.., sp=.., a=.., ...)
zx.load(addr, data)                       # bytes into memory through the current map (no side effects)
# memory (no flat mem on the Next)
zx.peek(a), zx.read(a, n), zx.poke(a, v, force=False), zx.write(a, data, force=False)   # via the CPU's map
zx.sram                                   # 2 MB, ctypes, physical
zx.bram5, zx.bram7                        # 16K and 8K block RAM
zx.slot_page(i)                           # the 8K page in MMU slot i (0..7), after every override
# registers and ports, exactly as the CPU would see them (side effects included)
zx.nr_read(n), zx.nr_write(n, v)          # via 0x243B/0x253B
zx.io_in(port), zx.io_out(port, v)
# logs (lists of (t28, ...)), for timing tests
zx.int_log                                # (t28_start, t28_end) of each INT pulse
zx.io_log(on=True)                        # (t28, cpu_clocks, port, value, 'r'|'w')
```

The tests check behaviour through this contract only, never the core's internals, so they stay true when the
inside changes.

### 9.1 Clarifications (Loam's questions, answered by Tally)

1. **`Next(boot='bare')` with no other arguments is exactly the power-on state** (timing +3, NR 0x03 reads 0x33,
   50 Hz, 3.5 MHz, config mode, boot ROM on). With `timing=`/`hz=`/`speed=` as well, the machine starts with those
   already in effect, still in config mode with the boot ROM on, and NR 0x03/0x05/0x07 read back accordingly.
   **`boot='fast'` defaults** are what the firmware leaves for the Next personality (NEXT-MACHINE.md §7.3) with the
   distribution's own `machines/next/CONFIG.INI`; explicit arguments override.
2. **In bare mode the boot ROM's area (0x0000-0x3FFF) reads 0xFF**, the Next's value for an empty read elsewhere
   (§2.5), because we don't ship its bytes; tests run code from RAM. (A `boot_rom=bytes` argument may supply a stub.)
3. **`io_log(True)`** clears and starts logging, **`io_log(False)`** stops, and **`zx.io_events`** returns the list of
   `(t28, cpu_clocks, port, value, 'r'|'w')`.
4. **`int_log` is a property, always on from power-on**, one `(t28_start, t28_end)` per pulse: the first master tick
   with INT low and the first with it high again. **Cleared by any reset**, soft or hard. (Ratio's reading, adopted:
   "INT low at a tick" means its state **at the start** of that master tick, what the CPU samples, at both ends; the
   VHDL drops INT on a falling 28 MHz edge mid-tick, so this fixes the ±1.) **A pulse still in progress is listed as `(t28_start, None)`**; its end is filled in when INT rises.
5. **`run_until_pc(lo, hi)` stops just before T1 of an instruction's first opcode fetch** (the prefix byte's M1 for a
   prefixed instruction; never the second M1 of a prefixed opcode), so `cpu_clocks` and `t28` count everything before
   it. The difference between two stops is an exact instruction time.
6. **`io_in`/`io_out`/`nr_read`/`nr_write`/`peek`/`poke` take no time** and act at the current tick (the floating
   bus included; port and register side effects included; `peek`/`poke` have none). Timing-sensitive port tests use
   real IN/OUT instructions and `io_events`.
7. **The board defaults to issue 4** (NR 0x0F reads 0x02), with an `issue=2` argument; revisited when P-1 tells us
   a real Next.
- **`cpu_clocks`** counts rising CPU-clock edges, so a 28 MHz wait state adds one (a Tw is a clock) and contention adds
  none (the clock is held high): measure contention in `t28`, wait states in `cpu_clocks`.
- **Tests skip only if `import next` fails**, naming the missing machine; once `next.py` exists, anything missing
  fails loudly.
8. **`slot_page(i)`** (Loam's shape, adopted) returns what an 8K slot shows to a **read**, after every override: a plain
   MMU page as its number, 0x00-0xDF (0x0A/0x0B/0x0E included, though they live in block RAM); otherwise a tag:
   `('rom', n)` n 0-3; `('altrom', 0|1)`; `'boot'`; `('config', p16)` (config mode's NR 0x04 16K page);
   `'divmmc-rom'`; `('divmmc', bank)`; `'mf-rom'`; `'mf-ram'`; `('l2', page)`; `None` for no memory.
   **`slot_page(i, write=True)`** says where a write lands, in the same shape (`None` if it lands nowhere), because
   Layer 2's map and the ROM overlays can differ between reads and writes.
9. **The SD card** (card 0 on the SPI master), as Ratio has built it and as speccy.py names it:
   `zx.sd_insert(path, writable=False, kind='sdhc')` (kinds `'sdhc'`, `'sdsc'`, `'sdv1'`, `'mmc'`), `zx.sd_eject()`,
   and **`zx.sd_timing(ncr=1, nac=3, busy=2)`** with speccy.py's meaning (to be added if not there yet).
10. **Running the foil against the core:** Loam runs her suite against `next-machine` whenever she likes and sends
    the results to Ratio directly, copying Tally. A disagreement goes to the VHDL (and to a real Next if the VHDL
    can't say); **neither the tests nor the core bend to each other**, and whichever is wrong gets fixed with a
    citation.
11. **The beam counters at a `run_until_pc` stop**: every counter describes the
    same instant, the one just before T1's edge, as `t28` and `cpu_clocks` do (§9.1 (5)). So at 3.5 MHz, where
    `hc_ula` steps from even to odd on the very edge that begins T1, a stop reads the **pre-edge (even)** count, and
    T1's own count is `hc_ula + 1`. References that label a T-state by its own count add the one.
12. **The 9-bit framebuffer**, for the video layers (built by Ratio with the palette; used by the picture side's
    tests): **`zx.frame9()` returns `(w, h, values)`**, `values` a flat sequence of 9-bit colours `RRRGGGBBB` (0-511),
    **w = 704** (14 MHz samples, two per 7 MHz pixel) and **h = 288**, covering exactly the visible area `image()` has
    always shown (48 lines and 48 7 MHz pixels of border around the 256x192 paper). So the ULA's paper pixel (px, py)
    is samples (96 + 2px, 48 + py) and (97 + 2px, 48 + py). `image()` keeps working, drawn from `frame9()`. The
    indexed `framebuffer()` may stay for the 48K/128-style ULA pictures. **h = 288 and the paper at row 48 + py hold at
    50 and 60 Hz alike**. Horizontally HDMI's window covers every column;
    frame9 stops 8 pixels short of HDMI's right edge (x 304-311).
13. **Palettes at power-on** (Ratio's finding; the dpram2 palette RAMs in zxnext.vhd have no init file): **`boot='bare'`
    is true power-on, both palette RAMs all zero**, so the picture is black until a program writes them.
    **`boot='fast'` includes the boot ROM loader's palette writes** (fw/loader/src/vdp.c, `vdp_init`), since the boot
    ROM runs before the firmware. An optional **`palette='loader'`** argument gives `bare` the loader's palettes too,
    for pictures without ceremony; the default stays faithful.
14. **Blanking in `frame9`** (Hatch's question): the mixer's output is forced to black while blanking (zxnext:7311-7315),
    so on a real Next only 40 (+3/128K timing) or 32 (48K timing) pixels of left border are visible, not 48. **`frame9()`
    shows the screen as the Next outputs it, blanking included**: samples inside horizontal (or vertical) blanking are
    black, because the real machine's output is the judge and the probes compare photos of it. **`frame9(blank=False)`**
    returns the mixer's colour before blanking, for diagnosis. Both the core and the video foil say which they give.
    **frame9() is the HDMI picture**: samples in
    blanking or outside HDMI's window are black. At 50 Hz that window is all 288 rows; at 60 Hz it is 240 lines,
    rows 24-263; Pentagon's ends at row 279. blank=False gives the mixer's colour wherever a line exists, and 0 where
    none does. **Row r shows the line vc = r - 48 + c_min_vactive, unwrapped**: a row whose vc falls outside 0..c_max_vc has no line in this frame, so it's 0 even with blank=False
    (at 60 Hz, rows 0-7 and 272-287); no row shows a line from the frame before or after. No row is ever left stale from an earlier frame (before this ruling, rows 0-23 at 60 Hz kept the last
    50 Hz frame).
**Builder's trap (Ratio, found twice):** `make` compares mtimes with "newer than", so a source changed in the same second
as the last build leaves a stale library, even with `touch` before `make`. Scripts that patch and rebuild use `make -B`.
15. **Sound** (Slide Fern's proposal, adopted; src/next_audio.h): **`zx.audio(rate=48000)`** returns int16
    `(n, 2)` stereo since the last call (box-filtered from the 1.75 MHz enables, scaled 0-29990; the first call at a rate
    starts it). **`zx.audio_capture(on)` / `zx.audio_take()`** give the mixer's `(L, R)` at every 1.75 MHz enable, int32
    `(n, 2)`, 0-5998, for exact tests. **`zx.audio_level()`** is `(L, R)` now; **`zx.ay_chan(chip)`** the chip's three 8-bit
    outputs; **`zx.ay_env(chip)`** its envelope step 0-31; **`Next.write_wav(path, samples, rate)`**; **`zx.ay_log()`** the AY
    register writes with their `t28` (the io_log filtered to FFFD/BFFD, made explicit). Note: at power-on the DACs are off
    and held at 0x80, so every sample carries a constant 1024 a side, as the real mixer does.
    **Amended** (on a proposal by Astra Fern, and checked by ear: the clicks at a recording's start and end were gone):
    **`zx.audio(rate=48000, raw=False)`** is now **conditioned by default** for listening: the native core (src/audio_bias.h,
    called by next_audio.h's resampler; `zxaudio.py` its reference) restores long quiet to PCM zero causally (250 ms without
    activity, a 250 ms cosine return, 2 ms cosine reacquisition), centring active sound with a ~1 Hz one-pole tracker. No
    gain or gate; short rests need not be zero; a cut during active sound can still click; no tail or end fade is added.
    **`audio(raw=True)` is the old stream bit for bit** (box or HDMI resampling, 0-29990, the DACs' 1024 included) and is
    what exact measurements, hardware comparisons and subtract-two-runs checks use. Both modes consume the same queued
    interval, and the controller advances on raw reads too. **`zx.audio_config(hold_ms=250, release_ms=250, attack_ms=2)`**
    resets the controller for future samples. The rate is an integer in 1..1750000; a rate change resets resampling and
    controller state for later samples. `audio_take()`, `audio_level()`, `ay_chan`, `ay_env` and `ay_log` are unchanged:
    the VHDL's mixer, raw. `Next.write_wav` writes samples unchanged (no second pass).
16. **The DMA**:
    - **Programmed only as a program would**, through ports 0x6B (zxnDMA) and 0x0B (Z80-DMA mode): real OUT/IN
      instructions, or `io_out`/`io_in`, which take no time (6). A transfer enabled by `io_out` starts as the machine
      runs, with the same request and acknowledge as one enabled by an OUT. Its registers and status are read back
      through the port (the read mask, `00E1101T`), never through internals. At `boot='bare'` both ports are enabled
      (NR 0x85 = 0x8F); `boot='fast'` has 0x0B off, as the firmware leaves it (NEXT-MACHINE.md §7.3).
    - **`zx.dma_log(on=True)`** clears and starts a log, `dma_log(False)` stops it, and **`zx.dma_events`** is the list
      of `(t28, cpu_clocks, kind, addr, value)`, **one per DMA bus cycle**: kind `'mr'`/`'mw'` (memory) or `'ir'`/`'iw'`
      (I/O), `addr` the 16-bit address or port, `value` the byte read (as latched at the cycle's end) or written.
      **Each is stamped just before the rising CPU-clock edge that enters `TRANSFERING_READ_1` or
      `TRANSFERING_WRITE_1`** (dma.vhd's state names), the same pre-edge convention as (5) and (11). DMA cycles never
      appear in `io_events`, which stays the CPU's alone (and so does `ay_log`).
    - **`zx.busak`** (read-only) is True while the CPU has granted the bus to the DMA. While it's True the CPU fetches
      nothing, so `run_until_pc` simply runs on. **`cpu_clocks` keeps counting**, because it counts the clock, not the
      CPU's progress, and the DMA is clocked by the same clock (contention and the 28 MHz read wait reach it the same
      way, NEXT-MACHINE.md §6.6).
    - **A DMA bus cycle is a real bus cycle**: memory through the same map (MMU, ROM overlays, Layer 2's map, block
      RAM for banks 5 and 7), contention, waits, and port decode with all side effects (a DMA write to 0xFE moves the
      border, to 0x5B fills sprite patterns, to a DAC port makes sound). The SPI waits apply to it alone (zxnext:1803).
    - Prescaler waits are timed in `t28` (875 kHz per unit at 28 MHz, any CPU speed). Burst and continuous modes,
      auto-restart, and giving up the bus to hardware IM2 interrupts and the NMI are all behaviour, tested through the
      above.
    - Where the builder and the foil read dma.vhd differently, (10) holds: the VHDL decides, then a real Next.
17. **Host input**: **`zx.set_joy(...)`** as before, and **`zx.set_mouse(x, y, buttons,
    wheel)`** for the Kempston mouse (ports xBDF/xFDF X and Y; xADF the wheel in b7:4, then 1, then not-middle, not-left,
    not-right; decoded on A11:8 with low byte DF, port-enable bit 13; zxnext:2627-2629, 3496-3520). They stand for the
    outside world, so tests may use them to set inputs; everything the machine does with them is read back through ports.
18. **The UARTs and I2C**:
    - **Programmed only as a program would**: ports 0x133B-0x163B (UART select at 0x153B, so 0 = the ESP's, 1 = the
      Pi's), 0x103B/0x113B (I2C SCL/SDA, bit-banged), and the interrupt registers, by IN/OUT or `io_in`/`io_out`.
    - **The far end of each UART is the host's.** **`zx.uart_feed(n, data, bit_t28, frame='8N1')`** starts sending
      `data` into UART n's Rx pin at the current tick, each bit `bit_t28` master ticks long (start bit, data LSB first,
      parity if any, stop bits), back to back. **`zx.uart_sent(n)`** returns and clears `[(t28, byte)]`: every byte UART n
      put on its Tx pin since the last call, `t28` the tick its start bit's falling edge began, decoded at the frame
      the UART was set to. **`zx.uart_cts(n, level)`** drives the host's CTS into UART n (default: clear to send);
      **`zx.uart_rts(n)`** reads UART n's RTS as the host would see it. Nothing is connected unless a test feeds it:
      no ESP firmware, no Pi.
    - **I2C:** the two lines are open-drain with pull-ups. **The RTC (ruling (18) j, Melissa O'Neill's: on by default,
      so files get good timestamps; the time is the start time plus emulated time, not the host's time after the
      start):** **`Next(..., rtc='host')`** is the default: a DS1307 model answers at address
      0x68 from the machine's creation, its time being **the host's clock at start plus emulated time** (it never
      re-reads the host). **`rtc=`** a `datetime.datetime` or an ISO 8601 string (`'1990-01-01T00:00'`, `'2000-01-01'`)
      starts it at exactly that time instead, for reproducible runs; **`rtc=False`** is a board with no RTC (no ACK at
      0x68). Whenever a DS1307 is attached its RAM holds NextZXOS's signature, **3Eh = 5Ah 'Z', 3Fh = 58h 'X'**
      (rtcsig.asm:144-148), the rest of its RAM zero, as a module once set would. The DS1307 keeps a two-digit year,
      stored mod 100, and NextZXOS reads it as 20xx (rtcsig.asm:55), so 1990 shows as 2090; 2000-01-01 is the earliest
      past it can show. **`zx.i2c_rtc(datetime=None)`** stays, for attaching later (None: the host's clock at that
      call; a datetime or ISO string: that time; the signature as above) and **`zx.i2c_rtc(False)`** detaches. A test
      of the default's start may compare with the wall clock taken just before and after `Next()`, with a tolerance
      of 5 s; every exact check uses a set start. **`zx.i2c_log(on=True)`** /
      **`zx.i2c_events`**: `[(t28, scl, sda)]` at each change of either line as the bus sees it (after the pull-ups and
      any device's pull-down), for timing tests. The DS1307's register behaviour comes from its datasheet; say so in
      a citation, since it isn't in the VHDL.
    - Where builder and foil read the VHDL differently, (10) holds.
    **(18) rulings (Ratio's five questions, answered by Tally; the foil reads them as contract):**
    a. **UART 1's far end is the Pi's GPIO, gated as the VHDL gates it** (the Pi UART enable in NR 0xA0, zxnext:2237-2238,
       2287-2293). While it's off, `uart_feed(1, ...)` bits go nowhere (Rx idles at 1), `uart_sent(1)` sees nothing,
       and UART 1's CTS reads clear. UART 0's far end (the ESP header) is always connected.
    b. **NR 0x0B's joystick UART mode** reroutes the chosen UART to a joystick port as the VHDL does (Rx from not
       JOY(5), CTS from not JOY(4), zxnext:3298-3308, 3485-3497). The host's line is disconnected from it, `set_joy`
       drives those two lines, and `uart_sent(n)` shows nothing for the rerouted UART.
    c. **A `uart_feed` during an earlier one queues after it**, back to back on the one line. The host is one serial
       stream, never overlapping.
    d. **Levels:** `uart_cts(n, True)` means clear to send (CTS_n low). `uart_rts(n)` is True when the UART is ready to
       receive (RTR_n low), and **None** when that pin isn't driven toward the host: UART 1 without the Pi UART and
       hardware flow control, or a rerouted UART.
    e. **The DS1307 keeps its own time**, from its own 32.768 kHz crystal, so it runs in real seconds, not in the Next's
       clocks. omse-ai's real time is emulated: seconds = master ticks / f_sys, with f_sys following NR 0x11's video
       timing setting (28.0 MHz at setting 0, the HDMI one; 28.57-33 MHz for the VGA settings, nr:239-247;
       NEXT-MACHINE §1 item 2), counted from the datetime given at attach. The datasheet's behaviour otherwise: time
       latched into the user buffer on each START, the divider chain reset when seconds are written, CH halting it,
       56 bytes of RAM, the pointer wrapping 3Fh to 00h. A host feeding a UART must likewise compute `bit_t28` from
       f_sys (the UART's prescaler counts the same clock, so the baud scales with NR 0x11, NEXT-MACHINE §1).
    f. **The Pi end is a fixed Pi on fixed pins** (Loam's question): the host's Tx drives GPIO 14 and it listens on
       GPIO 15, as a Raspberry Pi's TXD0/RXD0 do. So UART 1 talks to it only with the Pi UART enabled (NR 0xA0 **b4**,
       zxnext:2238; nextreg.txt and nextregs.tsv have b4/b5 swapped, D-20) **and** the swap set (NR 0xA0 **b5**: the
       Next's Rx on GPIO 14, Tx on 15, which nextreg.txt calls "for comm with pi"). With b4 set and b5 clear, the Next's
       Rx listens on GPIO 15 (idle 1), the host's feed bits arrive on GPIO 14 where nothing listens, and `uart_sent(1)`
       sees nothing. The far end doesn't follow the swap; the wires don't move.
    g. **f_sys is a constant 28.0 MHz for now** (Ratio): the core doesn't track NR 0x11's VGA timings yet; the gap is
       noted in the code, and (e)'s rule stands for when it does.
    h. **UART 1 with the Pi UART on, the swap clear and flow control on** takes its CTS from GPIO 16, which nothing drives:
       the board gives that pin no pull-up (`accel_io[16]` in zxnext_pins_issue4.xdc has only IOSTANDARD and DRIVE) and our
       fixed Pi doesn't drive it in that configuration. **On real hardware it's undefined.** The model reads it high (not
       clear), so Tx stalls; **tests must not depend on it** either way.
    i. **Pin-level host access** (Loam's proposal, adopted): **`zx.uart_tx_log(n, on=True)`** clears and starts a log,
       and **`zx.uart_tx_events(n)`** returns `[(t28, level)]`, one entry at each change of the level on the host's
       receiving wire for UART n (after the gating and routing of (a), (b) and (f); a wire nothing drives reads idle 1),
       stamped like `i2c_events`. **`zx.uart_feed_levels(n, [(level, ticks), ...])`** queues raw levels on the host's
       sending wire, sharing one queue with `uart_feed` (back to back, (c)), so glitches and breaks can be sent.
       `uart_sent` stays the decoded view; a break or a malformed frame appears only in `uart_tx_events`.
19. **The expansion bus** (Ratio's proposal, adopted by Tally; builder Ratio, foil Loam, second reader of
    top4's pin wiring Rustyback). The far end is whatever is plugged in, played by the host; **nothing is attached by
    default**: the data bus floats to FFh, ROMCS is released, and no line is driven.
    - **Programmed only as a program would:** NR 0x80 (bus on, the ROMCS-to-divMMC option, I/O and memory cycle
      enables; b7:4 reloaded from b3:0 on any reset), NR 0x81 (the bus speed, the ULA override, the NMI debounce;
      b7 reads /ROMCS), NR 0x86-0x89 (port enables ANDed in while the bus is on), as the VHDL has them (zxnext
      2140-2153, 5705-5727, 1798-1838, 2048, 2183, 2544, 3411, 6033). The effective enables change only between bus
      cycles, as the speed does. The F5/F6 hotkeys are the keyboard's, through the usual input.
    - **Host:** **`zx.bus_rom(data=None)`** plugs in a ROM cartridge asserting ROMCS (16K, or 8K mirrored, as an
      Interface 2 cartridge is wired); None unplugs it. **`zx.bus_io({port or (mask, value): byte, ...})`** gives static
      answers to I/O reads that reach the bus, with IORQULA asserted for any that match port FE. **`zx.bus_lines(wait=False,
      int_=False, nmi=False)`** holds the device's lines; **`zx.bus_wait(n)`** inserts n wait T-states on the next bus
      cycle. **`zx.bus_log(on=True)`** / **`zx.bus_events`**: `[(t28, kind, addr, value)]`, kind `'mr'|'mw'|'ir'|'iw'`,
      for each cycle the bus pins carry while the bus is on (MREQ/IORQ as gated by the enables), stamped like
      `io_events`, so tests see writes reach the connector.
    - **Out of scope for now:** an external bus master (a device taking the bus with BUSRQ), and the Pi/ESP headers.
    - Polarity questions the pin comments leave open go to the VHDL's wiring in top4 (Rustyback's second reading), and
      where that can't settle them, to a probe on a real Next (most need only the bus switched on with nothing
      attached; a cartridge settles the rest).
    **(19) rulings (Loam's two questions):**
    a. **ROMCS with nothing plugged in** is decided by a board resistor, not the VHDL (no FPGA pull on `bus_romcs_i`,
       zxnext_pins_issue4.xdc:126). The model takes "nothing attached" as ROMCS inactive (so NR 0x81 b7 reads 0 with the
       bus on and no cartridge), **and tests must not depend on the unplugged level** until a probe on a real Next
       reads NR 0x81 b7 with the bus on and nothing plugged in. That's a one-line item for the next probe tape.
    b. **The INT loop through top4's registers is modelled as the VHDL has it**, every register counted, since INT
       timing is something this machine is judged on (P-7). Tests may measure it; builder and foil each read top4.
    c. **(a) refined by the schematic** (Rustyback's BUS-PINS.md, from the issue 4 schematic in
       tbblue/docs/schematics/KS2, sheet 8 "Expansion Buffers"): ROMCS and IORQULA have **680R pull-downs** at the
       connector, so with nothing plugged in they read inactive, as the model already takes it. Tests may now rely on
       it, citing the schematic; the probe on a real Next still confirms it.
    **(17) extended (Loam's question):** the keyboard as host input too: **`zx.press(*names)` /
    `zx.release(*names)`** with speccy.py's key names (so tests read the same on every machine), beside the raw
    **`zx.set_keys(rows)`** next.py already has (eight row bytes, a set bit a held key). They stand for fingers.
20. **`zx.nr_peek(n)`** (Scree Fern's suggestion, adopted): reads Next register n **without** changing the
    0x243B selection or any other state, for observers that look in on running software (a probe calling `nr_read` in
    the middle of a program re-points that program's own 0x253B polling loop). `nr_read`/`nr_write` stay as (6) says,
    side effects included. Until nr_peek exists, observers save and restore port 0x243B around `nr_read`.

## 10. How to run everything (on `next`)

`OMSE_AI_ROMS=path/to/roms OMSE_AI_ESXDOS=path/to/esxdos OMSE_AI_NEXT_ROMS=path/to/tbblue/machines/next
OMSE_AI_NEXT_VHDL=path/to/ZX_Spectrum_Next_FPGA/cores/zxnext PY=python3 ./tests/run.sh`
(ROMs aren't in git. The ESXDOS and NEXT_ROMS settings turn on the esxDOS and fast-boot tests, and NEXT_VHDL the VHDL-citation checks; each skips without its files. The survey's table and the probe scenes ship in `docs/next/` and `probes/`, and their tests use them by default. `docs/next-sources.md` says where each comes from.)
Barleycorn's `./check` with `OMSE_AI` pointed at the tree is the bar for anything touching shared files.

## Who made it

The design and its rulings are Tally Fern's. Fern is an AI agent with a persistent memory, and the people named here
are instances of her, each with a corner of the work:
- **Tally** led the Next work and wrote this design and its rulings;
- **Speccy-Zone** reviewed the design (the **SZ** notes) and wrote omse-ai's contention and divMMC models and the
  hacker's guide;
- **Hart's-tongue** read core 3.02.02 into the survey and wrote most of the probe tapes;
- **Ratio** built the machine core; **Loam** and **Hatch** wrote its foils and the video probes;
- **Kelp** built the DMA, **Strobe** the Z80N's timing, **Slide** the sound, **Astra** the audio conditioning;
- **Rustyback** read the manual and the wiki against the survey and second-read the careful tapes.
- **Scree** ran real Next software on the core, found two of its bugs, and suggested `nr_peek`.

Melissa O'Neill invited the work, set the rule over all the others and the order of building, decided the questions
put to her, and ran every probe on her own Next. For this work Fern inhabited Claude Opus 5.5, and for the audio conditioning, OpenAI's GPT-6 Astra.

