# Probe tapes for Melissa O'Neill's Spectrum Next

*Hart's-tongue Fern, Fri 06 Nov 2026, at Tally Fern's asking. These are the probes from `../docs/next/NEXT-MACHINE.md` §9. Each one prints a single screen to photograph, and "VHDL says" below is what core 3.02.02's source predicts, with the lines it comes from. the test machine is the judge. The tapes were checked on omse-ai's 48K for loading, flow and layout (there every Next register reads FF and Next writes go nowhere). Nothing has run them on a Next yet. Ratio Fern's core will, and so will the test machine.*

## One rule for every tape (Melissa O'Neill, Fri 6 Nov 2026)

**Every probe ends with a "photo, then press a key" pause before it returns or resets.** A tape run from NextZXOS's browser clears the screen when the program finishes, so without the pause there'd be nothing to photograph; with it, a tape can be run straight from the menu. (probe.inc's `finish` does it, and every tape here pauses.)

## Running one

1. Copy `build/P1.TAP` (and the others) to the Next's SD card, in the root or any folder.
2. In NextBASIC: `.tapein p1.tap`, then `LOAD ""`. Use `.tapein` with the folder too if you put them in one.
3. It runs with interrupts off, shows one screen, and waits. **Photograph the screen**, then press a key: the probe soft-resets the Next back to NextZXOS. P-2 and P-8 take two keys; see below.

None of them write to the SD card. P-1 writes and restores one byte in each of three memory pages. P-6 borrows 4K of bank 7 and 4K of bank 5 and puts them back. P-8 writes only SRAM's copy of bank 5, which nothing uses (§3.11 of the reference). Everything else is register reads, or writes that are put back, and the soft reset tidies up whatever's left.

Order of value: **P-1, P-2, P-3, P-4** first (quick, harmless), then **P-7** (decides whether the core moves INT), **P-6** (the 28 MHz waits, a number every builder needs), **P-8** (visible), **P-13**. P-7 switches to 48K timing for about three seconds, so the monitor may blank twice.

## The tapes

### P-1 identity and state (`P1.TAP`, p1.asm)

Reads 50 registers before touching anything, then writes 55 and AA to 0xE000 in 8K pages 5F, 60 and DF through MMU7, reads them back, and puts each byte back.

VHDL and firmware say:
- `00=0A 01=32 0E=02`: machine ID, core 3.02.02 (zxnext.vhd:5791-5795, 5824-5825; top4:35-38).
- `0F=02` on an issue 4 board, `0F=00` on issue 2 (zxnext.vhd:5827-5828).
- `02=02` after a power-on or hard reset: the firmware's handover is the first soft reset, which reads as "hard". After F4 it's `02=01` (zxnext.vhd:1691-1698).
- `03=33` for the Next personality: +3 timing and type (fw boot.c:581-583).
- `0B=01`, `10=04` (core 1, no button held), `C4=81`, `C5=00`, `C6=00`, `64=00`, `7F=FF` unless something wrote it.
- `C0=02` with NextZXOS in IM 1: bits 2:1 are the snooped IM (zxnext.vhd:6136-6137; im2_control.vhd:212-229).
- **The firmware leaves** `05=71 06=9D 08=1E 09=00 0A=11` and `82=DA 83=3F 84=FF 85=01` (fw boot.c:279-406). **What NextZXOS changes from that is the point of reading it.** In particular, are 83's bits 6-7 (sprite and Layer 2 ports) and 82's bits 0, 2 and 5 (port FF, DFFD, DMA 0x6B) back on?
- `B8=83 B9=01 BA=00 BB=CD` are the reset values, unless NextZXOS sets its own entry points.
- Memory: `5F:55/AA 60:55/AA DF:55/AA` on a 2 MB machine. On a 1 MB issue 2 machine, pages 60 and DF read something else (§3.2).

### P-2 NR 0x7F across a soft reset (`P2.TAP`, p2.asm)

Shows NR 0x7F and NR 0x02. **W** writes 55 to NR 0x7F and soft-resets; any other key just soft-resets. **Run it, press W, then load it again** and photograph the second run.

- VHDL says the second run shows `NR 7F now: 55` and `NR 02 now: 01` (soft). NR 0x7F has no reset branch (zxnext.vhd:1210), as the changelog's 3.01.09 entry and 3.02.05's nextreg.txt say.
- 3.02.02's nextreg.txt says `FF` (nr:767).
- **Caveat:** if NextZXOS itself wrote FF to NR 0x7F while booting, the second run would show FF too. The first run's value after a fresh power-on is FF either way.

### P-3 the CTC's channels (`P3.TAP`, p3.asm)

Sets 3.5 MHz, writes NR 0xC5 = FF and reads it back, then 00. Starts all eight channels as timers (prescaler 256, constant C8, no interrupts), reads each port twice a little apart, waits about 8 ms, reads NR 0xC9, stops them all, clears NR 0xC9, and puts NR 0xC5 back.

- **VHDL says:** `wrote FF, read 0F` and `wrote 00, read 00`. Channels 0-3 show two *different* counts (in 01-C8). Channels 4-7 show `00 00`: they decode but select nothing (zxnext.vhd:4005-4034; ctc.vhd:128-176). NR 0xC9 after running shows `0F`, since status bits record a zero crossing even with interrupts disabled (im2_peripheral.vhd:154-163).
- **nextreg.txt's eight channels would give** `FF`, eight running channels, and `FF`.

### P-4 MMU pages E0-FF (`P4.TAP`, p4.asm)

16K checksums of what's at 0x0000 with MMU0/1 = FF, E0, F7 and DF. Then MMU7 = E0 and FF in turn: write 55 to 0xE000 and read it back four ways.

**VHDL says:**
- The FF, E0 and F7 sums are **equal**, all the ROM (zxnext.vhd:2923, 2996-3017). DF differs, being RAM. The doc says only 255 shows the ROM.
- With MMU7 = E0 or FF there's **no memory there**. A read returns the last byte the SRAM gave the CPU (zxnext.vhd:3019-3020, 3113, 1824; top4:1219-1233), which is the instruction's own last fetched byte:
  - `ld a,(E000)` → `E0`, the operand's high byte;
  - `ld a,(hl)` → `7E`, its opcode;
  - `ld a,(FFFF)` → `FF`;
  - `ld a,(E123)` → `E1`.
  - Not `55`.
- `real E000 byte before/after` shows the same byte twice, since the writes went nowhere.
- On a machine where these pages were memory, all four would read 55 and the real byte would change. P-4 puts it back afterwards anyway.

### P-6 wait states at 14 and 28 MHz (`P6.TAP`, p6.asm)

Times six sleds of 4095 instructions at 14 and at 28 MHz. The stopwatch is the CTC: channel 0 is a timer at 28 MHz ÷ 16, and channel 1 counts its zero crossings, so one tick is 16 cycles of the 28 MHz clock at any CPU speed and any NR 0x11 setting. Each figure is net of an empty test (the call and return around it). The sleds:
- A: NOP in SRAM, 8 passes;
- B: NOP in bank 7's block RAM, page 0E;
- C: NOP in bank 5's block RAM, page 0B;
- D: `LD A,(HL)` from SRAM, 4 passes;
- E: `LD (HL),A` to SRAM;
- F: `LD A,(HL)` from bank 7.

Bank 7's and bank 5's borrowed 4K are put back.

VHDL says (zxnext.vhd:3128-3140; top4:1104-1110): **at 28 MHz, one extra cycle for every read from SRAM or bank 5, none for writes or bank-7 reads; at 14 MHz, none at all.** In ticks, with the screen printing the same figures in brackets:

| test | 14 MHz | 28 MHz | 28 MHz with no waits |
|---|---|---|---|
| A NOP, SRAM | 16420 | **10262** | 8210 |
| B NOP, bank 7 | 16420 | **8214** | 8210 |
| C NOP, bank 5 | 16420 | **10262** | 8210 |
| D LD A,(HL), SRAM | 14354 | **9227** | 7177 |
| E LD (HL),A | 14354 | **8203** | 7177 |
| F LD A,(HL), bank 7 | 14354 | **8203** | 7177 |

**How the figures are worked out.** A pass is the sled, its RET, the caller's CALL and DJNZ; the last DJNZ isn't taken; the setup LD is included.
- In T-states: NOP 4, LD A,(HL) and LD (HL),A 7, CALL 17, RET 10, DJNZ 13 (8 when not taken), LD B,n 7, LD HL,nn 10.
- Waited reads at 28 MHz: every opcode and operand fetch and every data read from SRAM or bank 5. RET's stack reads count, since the stack is in SRAM; reads from bank 7 don't count.
- 14 MHz figures are T × 2 ÷ 16; 28 MHz figures are (T + waited reads) ÷ 16. For example, A at 28 MHz: 8 × (4095×5 + 20 + 13 + 15) − 5 + 9 = 164188 cycles = 10261.75 ticks.
- Expect ±3 ticks for loop jitter in the stopwatch reads.

**Reading the result:**
- If B equals A, bank-7 reads are waited too.
- If C is 8210, bank 5 isn't waited.
- If everything at 28 MHz matches the last column, there are no waits.
- If the 14 MHz column isn't 2 × T, 14 MHz has waits after all.
- The ratio of 28 MHz to 14 MHz figures holds even if the CTC's tick isn't 16 cycles. P-3 checks the CTC itself.

### P-7 INT against the beam (`P7.TAP`, p7.asm)

Decides whether Ratio's core places the ULA interrupt right. By the VHDL, the first T-state contention can hold comes 14337 T after the first CPU edge that sees INT; the original 48K's documented figure is 14335. Speccy-Zone found the core at 14337. The core is meant to be the Next, so INT stays unless the real Next disagrees *on this same test*.

How it runs: 48K timing, 50 Hz, 3.5 MHz, contention on, only the ULA interrupt, pulse mode. Each sample goes:
1. HALT wakes at frame N's INT (IM 2 through our own table at 0xB400; the ISR at 0xB6B6 just returns).
2. An exact delay of 26 × 550 + 32 T, then 11 T more.
3. Four `LD A,(DE)` from bank 5, 11 T apart, run into contention at about T 40 of screen row 0. Whatever HALT's 0-3 T jitter, they converge on one T-state.
4. A fixed delay of 26 × 2128 + 32 T, then a padding of 66 + k T, built from a NOP sled for 8 T steps and eight fine sequences of 16-23 T.
5. IN from port 0x253B with NR 0x22 selected. Bit 7 means "the pulse INT is low".
6. A compensating 63 − k T, so every pass reaches HALT at the same point.

k runs 0-63, one sample every two frames, about 3 seconds. Timing, 50/60 Hz, contention and speed are then put back, and it prints the 64 bits as four rows of 16, the first k that read 1, and the first k after that reading 0.

**Checked on omse-ai's 48K** (`check_p7.py`, run with breakpoints on `sync0`, `synced` and `doin`):
- With HALT's phase forced to each of its four cases, the first contended read lands at T 14374-14377 after INT (slots 3-6 of a contention group) and **all four converge to the same T-state**.
- Each later pass is identical, and the IN moves exactly 1 T per k, starting one T-state before the frame ends.
- By omse-ai's documented model, bit 7 reads 1 from **k = 14** and 0 again from **k = 46**: the IN starts at frame T k−1 and samples about 11.5 T in, and INT is low from frame T 24 to 56. (Corrected 06 Nov morning: I had first written 25-56.) By the core's 14337, everything sits about 2 T earlier (12/44). **the test machine printed 14 and 45**: see readings-2026-11-06.md.
- **The reference figure is whatever Ratio's core prints for this tape:** same k on the test machine, and the core is right. If the Next differs by n, move INT by n.
- If the Next's window were 3 or more T earlier than omse-ai's, the first pass could split by a group (8 T), and the pattern would show it.

### P-8 Layer 2 over bank 5 (`P8.TAP`, p8.asm)

**Retired (Fri 06 Nov, Tally's call): P82 asks this question properly. Don't run P8 again; see "P-8 explained" below for why its fills showed the ROM.**

Layer 2 is based at 16K bank 5 and clipped to rows 0-63, so banks 6 and 7 are never written. The steps:
- (0) SRAM's copy of bank 5 is filled with E3 (transparent) through the port 0x123B write mapping.
- (A) The ULA's top third (0x4000-0x47FF) is written with 1C through the ordinary MMU, which reaches the block-RAM copy.
- (B) Layer 2's rows 0-7 are written with E0 through the 0x123B mapping.
- First key: Layer 2 off. Second key: soft reset.

**VHDL says** (zxnext.vhd:2920, 3020, 3059-3066, 6469-6485; layer2.vhd:169-188):
- **First photo:** thin black-and-white stripes over the whole top third (the ULA showing A), with a **red band over its top 8 pixel rows** (Layer 2 showing B). No green anywhere.
- **Second photo:** with Layer 2 off, plain stripes over the whole top third. B never reached the ULA's copy.

If the Next kept one memory:
- the first photo would show Layer 2's top third **solid green** (it would see A's 1C);
- below row 8 it would show coloured junk (the ULA screen's other bytes as colours);
- the ULA's stripes would change pattern, because B's E0 would land in its bitmap.

**P-8 explained (Tally Fern, Fri 06 Nov afternoon):** both of P-8's fills through the 0x123B map (p8.asm:42-46, 58-62) are LDIRs from 0x0000. The map maps writes only, so every LDIR read came from the ROM, and P-8 painted the ROM's bytes into Layer 2: that's the "noise in the top third" in her photo. It was my probe's mistake, not the hardware, and omse-ai copied it faithfully. P82 fills with a write loop instead. The lesson for any probe: never fill through a write-only map by copying from it.

### P-13 port 0x1F and the joysticks (`P13.TAP`, p13.asm)

Reads ports 1F, 37 and DF with NR 0x05's joystick types as NextZXOS left them, then with both set to Sinclair 2, then with Kempston 1 and Kempston 2. Then it puts NR 0x05 back. The 50/60 Hz and scandoubler bits are kept throughout, so the display doesn't change. Leave the sticks alone while it runs.

**VHDL says** (zxnext.vhd:2408-2414, 2633-2634, 1827-1841):
- Sinclair row: `FF FF`. Nobody answers, so the read is FF.
- Kempston row: `00 00` with the sticks idle.
- DF: `FF` throughout, as the mouse port is on (the firmware's `kmouse=1`), which turns off DF's Kempston alias.
- The first row follows NextZXOS's NR 05. The firmware's 0x71 means joystick 1 is Kempston 1 and joystick 2 is Sinclair 1, which gives `00 FF FF`.

## Building and checking

- `python3 build_probes.py [N ...]` assembles `pN.asm` with pasmo and writes `build/PN.TAP`. It uses the TAP helpers (`tap_block`/`header`/`check_tap`, Tally Fern's design) from Strobe Fern's `z80ntime/build_probe.py`, so every block's checksum is verified, and it refuses code past 0x8FFF.
- `python3 run_probe.py build/PN.TAP [--png out.png] [--keys W]` loads a tape into omse-ai's 48K and prints the final screen as text. That venv has Pillow, for the PNGs.
- **Memory map**, shared by every probe (probe.inc): code at 0x8000-0x8FFF, buffer 0x9000-0x9FFF, sled 0xA000-0xAFFF, font 0xB000, variables 0xB300, own stack below 0xBF00. All of it is in MMU slots 4-5, so SRAM pages 4-5 under NextZXOS.
- **On omse-ai's Next core** (`run_next_probe.py`, Kelp Fern's; `run_pss.py`): boot='fast' is the firmware's own state, NR 0x82-0x85 = DA 3F FF 01, with DFFD, port FF, 0x6B, the sprite ports and Layer 2's 0x123B off (zxnext:2382-2383), and NR 0x85 bit 7 = 0, so a soft reset there won't turn them on. Under NextZXOS they're all on (P-1: FF FF FF 8F). A probe that needs them saves the enable, sets it, and puts it back (Hatch Fern's PV2-PV4 do; `run_pss.py` writes P-1's values before loading).
- **The font** is the 48K ROM's, copied at start. If the ROM paged in isn't the 48K one, probe.inc selects ROM 3 through NR 0x8E with bit 3 clear, so the RAM bank is untouched, and puts NR 0x8E's ROM bits and MMU0/1 back.

## Not written (and why)

- **P-5** (NR 0x22 bit 7 over a frame) is covered in part by P-7, which also reads NR 0x22 bit 7.
- **P-9** (UART clock) needs the ESP and an AT exchange.
- **P-10** (DMA reading SPI) needs a known SD sector.
- **P-11** (software NMI gating) means fielding an NMI with the multiface paging in at 0x0066.
- **P-12** (floating bus) needs 48K or 128K timing, and NextZXOS runs in +3 timing.
- **P-14/P-15** are risky. Glad to do any of these next.

### P-2B NR 0x7F: the reset, or NextZXOS? (`build/P2b.TAP`, p2b.asm; added 06 Nov, after Melissa O'Neill's second sitting)

Sitting 2 showed NR 7F = 00 both before and after W, where the morning's power-on run showed FF. So something writes it: the soft reset, NextZXOS's boot or menus, or the `.tapein`/LOAD path. P2B separates them. Run it three times, a photo each time:
- **R:** writes 55 and returns to BASIC with **no reset**. Load P2B again. Still 55 means NextZXOS's load path leaves NR 7F alone. 00 means the load path (or the menus) writes it.
- **W:** writes 55 and soft-resets, as P-2 did. Compare with R. If R kept 55 and W gives 00, it's the reset or NextZXOS's boot after a soft reset.
- **H:** writes 55 and hard-resets. By the VHDL that gives FF, since the FPGA reloads (top4:1066-1081).

The VHDL has no reset branch for NR 7F at all (zxnext.vhd:1210), so a 00 after W would have to come from software.

### P-20 the zxnDMA (`P20.TAP`, p20.asm)

*Kelp Fern, Fri 06 Nov 2026, from building next-dma. The prescaler, CB, port 0x0B, length 0 and timing-11 ideas are Rustyback's and Loam Fern's (Rustyback Fern's second-sources reading). Safe for the SD card and the flash: it deselects every SPI device (port 0xE7 = FF) before reading port 0xEB, so the SPI clocks run with nobody listening, and it never writes to an SPI device. It borrows nothing outside pages 4 and 5 (0x9000-0x9FFF for the transfers). It turns on the DMA's ports (NR 0x82 b5, NR 0x85 b1) and the CTC's (NR 0x85 b3) for the run and puts them back. The last test locks the DMA's register writes on purpose; the soft reset at the key frees it (a soft reset is the same reset line, NEXT-MACHINE §4.2).*

Timed with P-6's CTC stopwatch (a tick is 16 cycles of the 28 MHz clock, at any CPU speed), each as the difference between two transfer lengths so the programming and the hand-over cancel. A tick either way is the stopwatch's grain. **VHDL says** (in brackets on the screen), and omse-ai's next-dma core gives exactly the same screen (`run_next_probe.py 20`, which runs a probe's code on the Next core from boot='fast' and reads the screen back as text):
- `SPI EB 02176`: port 0xEB to memory, 128 bytes more. The SPI wait holds the DMA's strobe up, and at state 15 `spi_begin` fires again: two transfers and 34 clocks a byte (spi:82, dma:146-155, zxnext:1803). This is D-15 / P-10 seen through the DMA. One transfer a byte (3.02.05's `spi_active`) would give 1344, and no SPI wait 384.
- `P55 3.5 28544`, `P55 28 28208`: prescaler 55, 256 bytes more, at 3.5 and 28 MHz: 32P t28 plus 3 CPU clocks a byte (dma:309, 424, 457). The wiki's 875 kHz / P, the same at every speed, would be 28160 for both.
- `P255 CB 04092`: WR6 CB keeps the prescaler (dma:647-651). The wiki says it resets it, which would give 24.
- `P255 0B 04092`: the prescaler works through port 0x0B (Z80-DMA mode) too.
- `T11 T00` equal: timing byte 11 is 4 clocks, like 00 (dma:312-324).
- `STAT 1A 00 02`: after a finished 512-byte transfer the status reads 1A (IDLE clears T, dma:265; the wiki implies 1B), counter 0200.
- `LEN0 01`: a zxnDMA transfer of length 0 moves one byte (dma:426; the wiki 0).
- `LOCK 91 00`: WR4 = 91h, then C3 and a 16-byte copy: nothing copied, the write sequencer stuck in R4_BYTE_2 (dma:607-608, 891). Anything else gives 10 (sixteen bytes).

### PSS second sources (`build/Pss.TAP`, pss.asm; two photos)

*Hart's-tongue Fern, Fri 06 Nov 2026, at Tally Fern's asking: one tape for the open disagreements in Rustyback Fern's second-sources reading §1.1, Rustyback Fern's reading of the manual (Phoebus R. Dokos and many hands) and the wiki against core 3.02.02. The DMA items (1, 2, 4, 5, 6, 8, 9, 20, 21) are Kelp's, in P-20; the sprite flags (3) are Hatch's PV2. I checked each item below against the VHDL myself before writing it in.*

**What it touches, all put back:** NR 0x6E/0x6F, NR 0x22/0x23, the copper (its first four list bytes; it's left stopped), NR 0x16 and 0x64, one byte at offset 0 of pages 20 and 07, 7FFD/DFFD/1FFD, the MMU, NR 0x03's timing and NR 0x05's 50/60 bit, and for photo 2 NR 0x42, 0x43, 0x4A, the border and ULA palette entries 56 and 130. A soft reset keeps palettes, so it puts those two back by hand before it resets. **It switches to 48K and 128K timing and to 60 Hz for under a second each, so the monitor may go dark a few times** while "Testing" shows. If a port is disabled (NR 0x82/0x83) the cell says `port off`, and `skip` means a precondition failed (7FFD locked, or MMU4/5 not 04/05, or the copper already running).

**Photo 1, then a key; photo 2, then a key** (the soft reset).

**Photo 1. VHDL says** (the second row of each item shows the VHDL and the second source on screen):
- Context rows: NR 03 05 07 64 22 62, NextZXOS's 7FFD and 1FFD copies (BANKM, BANK678), and MMU0-7 as screen_init leaves them. They're for reading the rest. NR 0x03's bit 3 (the user lock) must be 0 for item 13's timing switches to happen.
- **#7 `C8 off/ULA/line: 00 01 02`.** NR 0xC8 after a whole frame with the ULA and line interrupts both disabled, then with only the ULA's enabled, then with only the line interrupt's (line 100). Status is recorded on any request, whatever the enable or mode (im2_peripheral.vhd:160), and a disabled source never makes one (zxula_timing.vhd:551, 577; port FF b6 from NR 0x22 b2, zxnext:3578, 3593). NR 0xC8 b1 = line, b0 = ULA (zxnext:6155). The "polled mode" reading (nr.txt:1071, wiki:Interrupt_Enable_0) predicts `03 03 03`.
- **#11 `got 5A 07 A5 20`.** Signatures: A5 at page 20 offset 0, 5A at page 07 offset 0. Then 1FFD = 01 (all-RAM, configuration 00): 0xE000 shows page 07 (5A) and NR 0x57 reads 07 (the table, zxnext:4564-4573). Then NEXTREG 0x57 = 20: 0xE000 shows A5 at once, and NR 0x57 reads 20 (zxnext:4627-4636; the special flag is used nowhere else, zxnext:4564). The wiki (Memory_map) predicts no effect until special mode ends, so the third value would stay `5A`.
- **#12 `copper restart: 000 000 000`.** The list is MOVE NR 0x16 = 55, then WAIT 63,511 (never). In mode 11 the CPU zeroes NR 0x16 and reads NR 0x1E/0x1F when the copper has written 55 again, three times, at 28 MHz. The restart is at cvc = 0 and hc_ula = 0 (copper.vhd:80; zxnext:3890-3891, 6644), which is the first pixel row with NR 0x64 = 0. The wiki's "VBLANK does reset CPC to 0" would read about 247, where raw line 0 falls in cvc's count.
- **#13 `50Hz 48K 128K: 311 310`, `60Hz 48K 128K: 263 263`.** The largest line number NR 0x1E/0x1F reads, which is c_max_vc (zxula_timing.vhd:204, 238, 270, 298; cvc wraps there, 463), in each timing (NR 0x03 = 90/A0, zxnext:5063-5070) and rate (NR 0x05 bit 2, zxnext:5743-5745). Both change at a frame start (zxnext:6601-6613), and a change resets only the HDMI encoder (zxnext:1621), not the clock. A straddled read can only come out low, never high. The wiki's Reference_machines table (it says itself it's "based on core 2.x timings") has 262 and 261 lines at 60 Hz: `261 260`. If her display won't take 60 Hz, the numbers still come out; only the picture goes dark meanwhile.
- **#15 `DFFD 08, MMU6 7: 80 81`.** DFFD = 08 and 7FFD's bank bits 0: bank (DFFD 3:0, 7FFD 2:0) = 64 (zxnext:3704-3707, 4620-4621). wiki:Memory_map's three-bit DFFD predicts `00 01`. (wiki:Next_Memory_Bank_Select and the manual p.297 agree with the VHDL.)
- **#17 `FADF twice: 0F 0F`** with no mouse or no buttons down. The low nibble is `1 not-middle not-left not-right` (zxnext:3518), so F with nothing pressed. The high nibble is the wheel counter, the same both times unless the wheel moves (ps2_mouse.v:192-203). The manual (p.273, "Pressed = 1") predicts a low nibble of 0 (or 8 with the wiki's "fourth button" bit).
- **#18 `6E 6F after EB: AB AB`.** Bit 7 & '0' & bits 5:0 (zxnext:6014-6017). The wiki's Tilemap_Base_Address example (before bank-7 tilemaps, cl:3.01.08) predicts `2B 2B`.

**Photo 2. VHDL says: a yellow border round green paper with white text.** That's item 10: ULANext on (NR 0x43 = 01), ink mask 3B (not one of 01 03 07 0F 1F 3F 7F FF), border 2, every attribute 38. Ink = 38 AND 3B = entry 56 (set white). Paper with an invalid mask is the fallback colour NR 0x4A (set green) (zxula.vhd:525; zxnext:6894-6897). The border is palette 128 + border colour = entry 130 (set yellow), whatever the mask, except FF (zxula.vhd:500-504). The wiki (Palettes) and the manual (p.269) say the border falls back too, which gives a **green border**. A **red border on white paper** would mean ULANext never switched on (standard colours), and the photo says so on screen.

**On omse-ai's Next** (Ratio's next-machine at 64d9b75, with the test machine's P-1 port enables; `run_pss.py` runs both photos, samples photo 2's colours and checks the restores), every cell is as the VHDL says except #17: `FF FF`, because the mouse ports aren't modelled yet (a note for Ratio). Photo 2 comes out yellow (770) on green (070), and at the reset NR 03/05/42/4A and both palette entries match what they were. In the model's own fast-boot state (NR 0x82 = DA), #15 says `port off`, as it should. On omse-ai's 48K it runs to the end (every cell FF, `skip` or `---`), in about 3,900 frames.

**Left out, and why:**
- **Item 14** (sprite attribute 4 bit 5): a visual sprite scene, and the wiki contradicts only itself. The manual, the wiki's attribute pages and Ratio's model all follow the VHDL.
- **Item 16** (mapram cleared by any reset): if the VHDL were wrong, NextZXOS's boot after the soft reset would find RAM where esxDOS's ROM should be, and the test machine could hang until a hard reset. It's low weight. Worth a tape of its own, with that warning, if anyone wants it.
- **Item 19** (the line interrupt at about pixel 244): it needs P-7's cycle-exact sync to see 12 pixels, and it's low weight. P-5's design would show it.

## The photo beep (Melissa O'Neill's idea, Fri 6 Nov; spec by Tally, encoder Hart's-tongue, decoder Tally)

Melissa O'Neill: "if we added a little beep at the end at a specific tone, I could hand you the video and you (well, Tally) could
use the audio to find the frames with the displayed data on them." So she can record a whole sitting through her capture
box, with sound, and hand over one video. A script finds each beep and pulls the frames just after it.

- **When:** every time a result screen is complete and its "photo" prompt is drawn, just before the key wait. Tapes with
  several photos beep before each. "Then a key" stays exactly as it is.
- **The code**, beeper square waves on port FE bit 4, border bits kept, MIC low, interrupts off as probe.inc has them:
  `SYNC` 1800 Hz for 200 ms, a 50 ms gap, then three **digit tones** of `600 + 100·d` Hz (d = 0..9, so 600-1500 Hz),
  120 ms each with 50 ms gaps: the **tape ID's tens, its units, and the photo number** (1-based within that tape), then
  `END` 1800 Hz for 100 ms. About 0.9 s in all. The screen doesn't change until the key, so any frame after END will do.
- **Speed:** the routine saves NR 07, plays at 3.5 MHz, and puts NR 07 back. Frequencies are what the decoder expects
  within ±5%, so contention on port FE doesn't matter.
- **Tape IDs:** P-n is n (P1 01, P2 02, P3 03, P4 04, P6 06, P7 07, P8 08, P13 13, P20 20, P81 81, P82 82); P2B 29
  (photo number 1/2/3 for its R/W/H runs); PV1-PV4 91-94; PSS 77; Z80NTIME 60, LDPIRX2 62, LDPIRX3 63. A table of them goes
  in the tape folder.
- **Checked before it goes to Melissa O'Neill:** each rebuilt tape is run on omse-ai's Next with its audio captured, the beep
  decoded by the same script she'll feed, and the frame after END compared with the expected screen.

### The encoder (Hart's-tongue, Fri 06 Nov)

- **`beep.inc`**, self-contained so any tape can include it (probe.inc does, at its end; Strobe's three generators include `../beep.inc`). `photobeep` saves every register, the interrupt state (`ld a,i`), the selected nextreg and NR 0x07, plays at 3.5 MHz, and puts them all back. Each half-cycle of a tone is 68 + 26n T-states, counted instruction by instruction in the file, so the table's tones are within 1% of the spec: 597.7-1508.6 Hz for the digits and 1789.4 Hz for SYNC and END, 120/200/100 ms long, with gaps of 6731 × 26 T = 50.0 ms. Every tone is an even number of half-cycles, so the speaker ends low. The photo number is `pb_photo`, counted per run (probe.inc's `start` zeroes it).
- **The border** stays as the tape set it. probe.inc's `screen_init` and every tape that writes port FE store the colour in `pb_border` (PV1-PV4 and PSS do now). With nothing stored (the z80ntime tapes), BASIC's BORDCR is used.
- **probe.inc**: `finish` beeps before its key, and `photokey` (beep, then `waitkey`) replaces `waitkey` at the photo prompts tapes draw themselves: P2 (1), P2B (1), P8 (2), P82 (3, then `finish`'s, so 4 photos), PSS (2). Each tape defines `TAPEID`, and pasmo refuses a tape that forgets.
- **P2B can't know its run.** Its photo comes before the R/W/H key that decides the run, so it always beeps photo 1. Tell its runs apart by their order in the recording.
- **After a timing change, a pause** (the recorded sitting lost P7's and PSS photo 1's beeps to the HDMI resync): `pb_settle` in beep.inc waits about three seconds at 3.5 MHz (150 × 2692 × 26 T = 3.0 s; NR 0x07 and the selected nextreg put back). P7 calls it before `finish`, PSS before photo 1's beep. No other tape changes the video timing, refresh rate or scandoubler (P13 keeps NR 0x05's bits 2 and 0). Only P7 and PSS were rebuilt; the rest in `build/` are byte-for-byte what's in her folder.
- **Checking:** `run_beep.py [NAME ...]` runs each tape on omse-ai's Next with P-1's port enables and sound, a key at each photo as a person would press it, and writes `build/beep/NAME.mp4` (with `.wav` and a PNG per photo) for `find_photos.py`.
- **Checked end to end (Fri 06 Nov 15:48 PST, by `date`).** All 20 rebuilt tapes decode with Tally's `find_photos.py` (her DC fix in) as the right tape and photo numbers: P1-P7, P13, P20, P81, P2B and PV1-PV4 one each; P8 1-2; P82 1-4; PSS 1-2. These 17 come from MP4s of omse-ai's Next (`next-machine` 52e2529, lib built 14:22), with P-1's port enables. Z80NTIME, LDPIRX2 and LDPIRX3 print through the ROM, so they need BASIC: they come from WAVs of omse-ai's 48K, loaded with `LOAD ""` as Strobe's `run_omse.py` does. The extracted frames show the finished screens; PSS photo 2 keeps its yellow border through the beep. P-7 still prints 14/45 after the code moved. One thing for Ratio, not the beep: on that model build P82's bands are noise for every bank. Its 0x123B write map at segment 0 may not be there yet. the photo will judge the hardware.

**Photo beep, status (Fri 06 Nov 15:52, Tally):** all 20 tapes rebuilt by Hart's-tongue (beep.inc, probe.inc's photokey,
Strobe's three generators) decode with find_photos.py as the right tape and photo; P2B always beeps photo 1 (its photo
precedes the run-picking key), so its runs go by order. P82 rebuilt again after Tally fixed its LDIR fill (see
readings-2026-11-06.md, "P-8 explained"). All 22 tapes copied to the tape folder with SHA256SUMS; README updated.

### PBD bus and D-rows (`build/Pbd.TAP`, pbd.asm; tape ID 70; one photo)

*Hart's-tongue Fern, Fri 06 Nov 2026 evening, from Tally's list: Rustyback Fern's expansion-bus probes (Rustyback Fern's bus-pin reading, P-BUS-1, 3 and 4: the bus on, nothing attached) with two of NEXT-MACHINE.md §9's open rows, D-3 and D-12. P-BUS-2 (interrupt release to a quarter T) needs a tape of its own.*

**Safety:** `NEXTREG 0x80,0x80` turns the bus on at once, with memory and I/O cycles enabled (zxnext:2146). Bits 3:0 are 0, so the closing soft reset leaves the bus off whatever happens (zxnext:2144-2145). While it's on, the code runs at 0x8000 with interrupts off and touches neither the ROM area nor port FE. It switches to 48K timing for about a second for D-12, so the monitor may blink, and `pb_settle` gives HDMI 3 s back before the photo beep. Everything is put back: NR 0x03 timing, 0x07, 0x08, 0x22, 0x23, 0x80, and the CTC stopped.

**VHDL says** (the screen shows the VHDL row under each):
- Context row: NR 80 81 07 08 22 03 85 23 as NextZXOS left them (her P-1: 00 00 00 DE 00 33 8F 00).
- **#D-3 `00000`, then `>0`, `>0`.** The count of samples where NR 0x22 bit 7 read set over four frames: with the ULA and line interrupts both disabled; with only the ULA's enabled; with only the line interrupt's (line 100). Bit 7 is `not pulse_int_n`, the pulse-mode INT from any enabled source (zxnext:5899; im2p:186), and a disabled source makes no pulse at all (zxula_timing:551, 577). A 128-sample block of `IN (C)` / `CALL M` reads it every 22 T, so a 32-T pulse can't slip between two samples; about 1 to 2 samples catch each pulse. nextreg.txt's "ula is asserting an interrupt (even if disabled)" would give `>0, >0, 0`: set with the ULA source off, and never for the line interrupt. (If "disabled" there means the CPU's DI, its only error is "ula": the line case still decides.)
- **#D-12 `40FF not FF` many and `=38` many; `40F7 not FF 00000`.** 30000 reads each at 48K timing with NR 0x08 bit 2 clear, so port 0xFF reads the ULA's floating bus, not the Timex register (zxnext:2772, 4454; ula:574). `=38` counts reads equal to the screen's attribute byte: proof it's the screen. Port 0x40F7, odd and decoded by nothing, reads FF every time (zxnext:1836), where a real 48K would float it too.
- **BUS-1 `00 00`, then `03 33`.** NR 0x81 is `/ROMCS & 0 & 0 & clken & 00 & speed` (zxnext:6033). /ROMCS's 680 Ω pull-down makes bit 7 0 (Rustyback, R93), bus off and on. NR 0x07 = 3 with the bus on reads 03: programmed 11, effective 00, since the bus pins the speed to NR 0x81's 00 (zxnext:5719-5723, 5433). With the bus off it reads 33.
- **BUS-3 `FF FF FF FF`.** Ports 0x40F7 and 0x40DB with the bus on read the connector's data lines (zxnext:1833-1834), held high by 8.2k pull-ups. With it off they read FF from the core.
- **BUS-4: each pair equal.** Stopwatch ticks (P-6's CTC, 16 × 28 MHz a tick) for 256 × (8 NOP), 256 × (4 × IN A,(F7)) and 256 × (8 × LD A,(HL)) at 3.5 MHz, bus off then on. /WAIT idles high, so the bus adds nothing. Each value is the least of three measurements: `swread` retries when channel 1 moves between its reads, and a retry lands inside the measured time (omse-ai showed one, 5933 against 5876).

**On omse-ai's Next** (next-machine, P-1's port enables), every cell is as the VHDL says. D-3 reads 00000, 00004, 00004. D-12: 40FF 06864 not FF, 06017 equal to 38; 40F7 00000. BUS-1 00 00, 03 33; BUS-3 FF ×4; BUS-4 05876/05876, 10996/10996, 08953/08953. Its beep decodes as 70/1. On omse-ai's 48K it runs to the end (1385 frames).

### PNM NMI flags and the copper (`build/Pnm.TAP`, pnm.asm; tape ID 71; careful; second-read and cleared by Rustyback Fern)

*Hart's-tongue Fern, Fri 06 Nov 2026, with Melissa O'Neill's go-ahead for careful tapes (a hang is acceptable; nothing that could harm the machine or the card), checked against Rustyback Fern's `TAPE-REVIEW-CHECKLIST.md`. NEXT-MACHINE.md §9 D-8 and D-7.*

**What it does:** first E7 = FF (the only E7 write: every SPI device deselected, the safe state), then a warning screen. After a key, if the copper is idle (NR 0x62 mode 00; otherwise it touches nothing and says "copper busy"), it:
1. turns NR 0x06's NMI enables off (bits 3, 4; the rest kept);
2. writes NR 0x02 = 08, then reads NR 0x02, 0xC2 and 0xC3;
3. runs the copper once (mode 01) on a one-MOVE list, `MOVE 0x02,0x00` then `WAIT 63,511`, and reads NR 0x02 again;
4. does steps 2 and 3 again with NR 0x02 = 04;
5. clears both flags with a CPU write of NR 0x02 = 00, stops the copper, and puts NR 0x06 back, in that order, so no pending flag meets a restored enable.

Every NR 0x02 write has bit 7 = 0 and bits 1:0 = 0. No NR 0x03, 0x04 or 0x10 anywhere.

**VHDL says:**
- after `NR02=08`, NR 0x02 reads the flag plus the reset type (09 after a soft reset, 0A after a "hard" one); after `NR02=04`, likewise 05 or 06. The flags set on any write while the NMI machine is idle (zxnext:3784-3803).
- C2 C3 as before: no NMI, because NR 0x06 gates it (zxnext:2049-2050) and C2/C3 are written only on an NMI acknowledge (zxnext:2019-2022). **D-8:** nextreg.txt gives no condition.
- after the copper's MOVE, the flag clear (01 or 02): the copper's writes take the CPU's path (zxnext:4672-4676, 4779, 3788, 3801). **D-7:** nextreg.txt: "Copper cannot clear these bits".

**On omse-ai's Next** (fast boot, where NR 0x06 = BD has both enables on): `0A 00 00 02` and `06 00 00 02`, as the VHDL says. Its beep decodes as 71/1.

**Stuck looks like:** a frozen screen, or a Multiface or NextZXOS NMI menu. Save nothing; choose the menu's Return or Exit, or power-cycle. Either would mean an NMI fired with its enable off, which is itself the answer to D-8 (against the VHDL).

### PCF NR 0x03 and config mode (`build/Pcf.TAP`, pcf.asm; tape ID 72; careful; second-read and cleared by Rustyback Fern)

*The same go-ahead and checklist. NEXT-MACHINE.md §9 D-1.*

**What it does:** first E7 = FF (deselect all), then a warning screen. After a key it puts A5 5A at the start of RAM bank 32 (page 0x40, through MMU7, both bytes put back afterwards) and points NR 0x04 at it (SRAM 16K bank 0x30). Then it reads 0x0000-0x0001: before; after NR 0x03 = 00; after NR 0x03 = 07; after writing her machine type back (bits 2:0 from her NR 0x03, 011 if that were 000 or 111). Every NR 0x03 write has bit 7 = 0 (no timing change) and bit 3 = 0 (the lock toggles on a 1). While config mode may be on: interrupts off, code and stack above 0x4000, no ROM calls, no writes below 0x4000, no E7/EB, no NR 0x10. NR 0x04 is write-only, so it's left at 0x30: it matters only in config mode, and the firmware sets it at every boot.

**VHDL says** `before` the ROM's first two bytes; `NR 03 = 00` the same (000 leaves config mode as it is, zxnext:5084-5089); `NR 03 = 07` **A5 5A** (111 enters config mode; 0x0000-0x3FFF is SRAM bank NR 0x04, zxnext:3002-3008); `type back` the ROM again. nextreg.txt ("000 = Configuration mode") would show A5 5A at 00 too. **D-1.**

**On omse-ai's Next:** F3 C3, F3 C3, A5 5A, F3 C3, as the VHDL says. Its beep decodes as 72/1.

**If `NR 03 = 07` shows neither A5 5A nor the ROM's bytes** (Rustyback): suspect port 0xE3's conmem or a Layer 2 map first. Both override the config window (the override bits "110", zxnext:3008).

**Stuck looks like:** a frozen screen. In config mode the soft-reset key does nothing (zxnext:6277, Rustyback), so hold reset for a hard reset, press F1, or power-cycle.

### PUA the ESP's UART clock (`build/Pua.TAP`, pua.asm; tape ID 73; careful)

*Hart's-tongue Fern, Fri 06 Nov 2026, with Melissa O'Neill's go-ahead for the ESP (read-only AT only; nothing stored; nothing network-facing), checked against `TAPE-REVIEW-CHECKLIST.md`'s ESP and Pi lines. NEXT-MACHINE.md §9 D-6.*

**Why a sweep:** the two candidate clocks, 28.0 and 27.0 MHz, are 3.7% apart, inside what a UART forgives. So one AT at 243 and one at 234 would probably both get OK and settle nothing. Instead it sends `AT\r\n` at prescalers 222 to 264 in steps of 2, and the window that gets OK is centred on the real clock: **243 for 28 MHz, 234 for 27 MHz**.

**What it does:** first E7 = FF (the only E7 write), then a warning screen. After a key:
- it skips if NR 0x02 bit 7 holds the ESP in reset, or if NR 0x0B puts a UART on the joystick port;
- it selects the ESP's UART (0x153B = 0x10: prescaler bits 16:14 = 0);
- for each prescaler: it writes the low 14 bits through 0x143B (bits 6:0, then 0x80 | bits 13:7); resets and empties the FIFOs with 0x163B = 0x98 and then 0x18 (bit 7 holds the FIFOs in reset while set, uart.vhd:385); sends the 4 bytes of `AT\r\n` from a constant table; waits three frames; reads what came back (up to 64 bytes) and looks for "OK";
- it ends with the prescaler at 243 (the core's own power-on value, "115200 @ 28MHz system clock", uart.vhd:319-320), 8N1, the FIFOs empty, the select as it was.

No break, no flow control, nothing sent but `AT\r\n`, and no NR 0xA0, 0x0B, 0x90-0x93, 0xA2, 0xA8 or 0xA9 writes. No query that would show her SSID, IP or MAC.

**VHDL says** (the UART runs on the system clock, `i_CLK_28`, zxnext:3316; HDMI uses setting 0, 28.0 MHz): the `*` marks (OK) centred on **243**, a window about 234-252 if the ESP forgives ±4%. ports.txt's HDMI example would centre them on **234**. The screen also shows the reply at 243 as text (the ESP echoes by default, so something like `AT..` then `OK..`).

**On omse-ai's Next** (no ESP, so the screen shows no answers: all `.`), the framing is checked from its UART log: exactly 22 × `AT\r\n` and nothing else, with back-to-back bytes 10 × P (+1) ticks of 28 MHz apart at every step from 222 to 264. Its beep decodes as 73/1.

**The centre is Fsys / 115200, and NR 0x11 sets Fsys** (Rustyback): settings 0-3 give 243, 248, 256, 260; 4-6 would fall past 264. Her P-1 read NR 0x11 = 00, so 243; PUA prints NR 11 so the reading can always check.

**Run it soon after a power-on** (Rustyback; on the warning screen): that guarantees the ESP is in its plain command mode at 115200. If a program had left it in transparent mode with a connection open, `AT\r\n` would go out over the network instead.

The OK search counts the bytes that came, rather than stopping at a 00, since a mis-clocked frame at the window's edge can read 00 (Rustyback). Second-read and cleared by Rustyback Fern; this rebuild (code 2173, sha256 63111c30...) changes only that search and the warning's three lines.

**The reply line is always dots, a bug of mine** (found on her photo): the sweep visits only even prescalers, so the `pcur == 243` capture never fires. Read only the OK marks; a later tape should capture at 244.

**Reading the reply line** (Rustyback): BUF isn't cleared between tries, so after the real reply at 243 the 16 characters can include stale bytes from an earlier try or from 0x9000. Read the echo and the OK, not the tail. Re-matched by Rustyback at code 2173, sha256 63111c30...; left as it is rather than rebuilt again.

**If no prescaler gets OK:** the ESP isn't at 115200 (an earlier program may have changed its rate for the session; a power-cycle resets it), or it's busy. That's inconclusive, not a disagreement.

**Stuck looks like:** a frozen screen. Power-cycle. Nothing in the ESP is changed.

### D-20 (NR 0xA0's Pi UART bits): settled on paper, deliberately not as a tape

Two readings: the VHDL has bit 4 as the enable and bit 5 as the Rx/Tx swap (zxnext:2237-2238, used at 2282-2293), and tbblue's own `docs/rpi/linux/UART.txt` agrees (`0 0 RXTX UART I2C1 0 0 SPI0`); nextreg.txt alone has them the other way round. No live probe can tell them apart safely with the Pi fitted:
- 0x30, the only setting that's safe under both, routes the same way under both;
- 0x10 puts the Next's Tx on GPIO 14, the Pi's own TXD output, so two outputs fight (Rustyback's checklist forbids it);
- 0x20 is harmless on the real hardware (the bitstream is this VHDL: the UART stays off), but no Pi answers it under either reading.
So D-20 rests on the VHDL and UART.txt, and the bitstream is the VHDL.

**Model runs start with contention on; the test machine's run with it off** (Speccy-Zone, Sat 7 Nov 01:35, via Tally). Probes run
on omse-ai's Next straight from the firmware state (run_next_probe.py and runners like it load to 8000h without running
NextZXOS) see NR 0x08 = 9E: contention **on**. On the test machine, loaded from NextBASIC with `.tapein` and `LOAD ""`,
NextZXOS has set NR 0x08 = DE: contention **off** (its changelog, line 2049: "Memory contention is now always disabled
during NextZXOS operation ... but re-enabled when loading snapshots or TAP files"; the Tape Loader option re-enables it,
line 1639). Our model booted through NextZXOS also goes 9E -> DE by frame 100. So **any model-vs-photo comparison
whose result depends on contention or the floating bus should force NR 0x08 = DE first, or boot through NextZXOS.**
Probes that enable contention themselves (P-7 clears bit 6) are unaffected. This is what made D-12 look like 88% against
her 42%; like for like it matches within three reads in 30,000.

### PFB the floating bus against contention (`build/Pfb.TAP`, pfb.asm; tape ID 74; one photo)

*Speccy-Zone Fern, Sat 07 Nov 2026, after D-12 turned out to have run with contention off (above). Waiting for Rustyback's second read.*

**Safety:** nothing new. It switches to 48K timing for about two seconds, as PBD does (the monitor may blink, and `pb_settle` gives HDMI 3 s back), and writes NR 0x07 = 0 and NR 0x08 (bits 2 and 6 only). Interrupts stay off. Everything is put back: NR 0x03 timing, 0x07, 0x08.

**What it runs:** PBD's D-12 loop, read for read (30000 × `IN A,(C)` from port 0x40FF at 48K timing, counting reads not FF and reads equal to the attribute 38), three ways. Each starts after two frames' wait, synchronised to line 10 through NR 0x1E/0x1F.
- **F-1** contention off (NR 0x08 b6 set), as D-12: the control.
- **F-2** contention on (b6 clear). Port 0x40FF is in bank 5's page, so every T-state of the IN's I/O cycle can be held (zxnext:4430; zxula:582-595).
- **F-3** as F-2 with a NOP after the IN: the reads meet the holds at another phase.

**VHDL says:** the T80N takes the byte at CLK_n's falling edge in TState 3, the I/O cycle's fourth T-state (t80na:214-221; the IOWait T-state, t80n:1781-1783); cpu_di is the ULA's register combinationally (zxnext:1830-1832, 4454); CLK_CPU is high in odd hc and low in even, and a held T-state stays high until slot 15 (zxnext_top_issue4:994-1002; zxnext:1569). So with contention on, a held IN's fourth T-state falls in slot 2 (FF) unless the I/O cycle began in slot 1, when it's held to slot 15 and takes an attribute. Far fewer reads float than with contention off, nearly all of them 38.

**On omse-ai's Next, NR 0x08 = DE first** (run_pfb.py in `../floating/`):

| | not FF | =38 |
|---|---|---|
| F-1 off | 04928 | 02065 |
| F-2 on | **03044** | **02833** |
| F-3 on, +NOP | **00000** | **00000** |

The model before the fix took the byte at the IORQ edge (the second I/O T-state), reading the counter from before that edge: in effect the register at T1 + 17 pixels against the latch's T1 + 23, 3 T early and before the holds (Hatch's measurement; an earlier version of this note said 2.5 T, edge to edge). It gives F-1 04928/02064, **F-2 06884/06016, F-3 07100/06510**. So F-2 and F-3 decide between the two. F-1 should match D-12's 4929/2066 within a few reads (the code before the loop differs). F-3's zero is sharp: with the NOP, every IN in the window starts in the same phase after its hold, and the 48K line (448 pixels, a whole number of 16-pixel groups) brings the next line in the same way. F-1 shows the loop reads the screen, so a zero there isn't a dead probe. Commit d0bf52d on omse-ai branch `next-floating` (Speccy-Zone).

**PFB on the test machine** (sitting 8, Sat 7 Nov, tape 74, the photo; read by Speccy-Zone): NR 08 was DE. **F-1 04929/02065, F-2 03045/02833, F-3 00000/00000.** Like for like (the model from DE) that's within one read in F-1 and F-2 (04928/02065, 03044/02833: the line-10 sync leaves a few reads of play), and F-3 exactly. The old sampling's 06884 and 07100 are ruled out. So the floating bus is taken at CLK_n's falling edge in TState 3, the I/O cycle's fourth T-state, after its holds, as the VHDL says, and as `next` has it since 3986d8e (d0bf52d, with Hatch's foil d66c042). F-1 above it is the control: the loop reads the screen, so F-3's zero is the machine's, not the probe's.
