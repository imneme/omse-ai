# Readings: the careful tapes, PNM and PCF (the sitting 6, Fri 06 Nov 2026)

*Hart's-tongue Fern, read from the frames (the photos). Second-read by Rustyback Fern, who transcribed both photos before reading these values: every cell matched. Melissa O'Neill: "Both ran safely (no
resets or plug-pulling required)."*

## PNM: D-8 and D-7 as the VHDL says

- Context: NR 0x06 was **A8** (her own: multiface NMI enabled, divMMC NMI off), C2 C3 before **00 00**.
- `NR02=08`: NR 0x02 **09**, C2 C3 **00 00**, after the copper **01**.
- `NR02=04`: NR 0x02 **05**, C2 C3 **00 00**, after the copper **01**.

Each write set its flag (bit 3, then bit 2), on top of the reset type 01 (her last reset was soft, since the tape
was launched after another tape's soft reset; omse-ai's fast boot reported type 02, hence its 0A and 06). With NR
0x06's enables off, **no NMI fired**: C2 and C3 stayed 00 00, and the tape ran on. The core writes them on any NMI
acknowledge, stackless or not, or on a nextreg write to them, and a soft reset clears them (zxnext:2016-2027,
2017-2018; Rustyback), so an NMI during the tape would have left a return address inside it, near 0x80xx. So NR 0x02's NMI bits need NR 0x06 to fire an NMI, though the flag sets regardless
(zxnext:2049-2050, 3784-3803). **D-8 settled for the VHDL**; nextreg.txt gives no condition.

And the copper's `MOVE 0x02,0x00` cleared each flag (09 → 01, 05 → 01): its writes reach NR 0x02 through the same
path as the CPU's (zxnext:4672-4676, 4779, 3788, 3801). **D-7 settled for the VHDL**; nextreg.txt says "Copper cannot
clear these bits".

## PCF: D-1 as the VHDL says

- Context: NR 0x03 was **33** (+3 timing, +3 type).
- Bytes at 0x0000-0x0001: before **F3 AF**; after `NR 03 = 00` **F3 AF**; after `NR 03 = 07` **A5 5A**; after her type
  back **F3 AF**.

Writing 000 changed nothing; writing 111 entered config mode, and 0x0000 showed RAM bank 32 through NR 0x04 = 0x30,
with the signature A5 5A the tape had put there; writing her type (011) left config mode. **D-1 settled for the
VHDL** (zxnext:5084-5089, 3002-3008); nextreg.txt's "000 = Configuration mode" is wrong. It's wrong as a read value
too: NR 0x03 reads the machine type in bits 2:0 even in config mode (zxnext:5801), so config mode can't be seen
through NR 0x03 at all (Rustyback). And the A5 5A confirms on the test machine that MMU page 0x40 is SRAM 16K bank 0x30,
MMU pages sitting 0x20 8K pages above SRAM 0 (zxnext:2923).

**F3 AF** is `DI; XOR A`, the 48K ROM's first two bytes, so under NextZXOS a USR program runs with ROM 3 (48K BASIC)
at 0x0000. omse-ai's fast boot showed F3 C3 there, a different ROM image in that slot. Both are right for their own
state. The test needs only the two to differ from A5 5A.

## The careful tapes, as a pair

Both ran without a hang, as the VHDL predicted. With them, D-1, D-7 and D-8 are settled. And D-15 (3.02.02's SPI
double transfer) was settled in sitting 2 by Kelp Fern's P-20 (port 0xEB through the DMA: 02176, two transfers a
byte), though §9 hadn't recorded it until now. So every §9 row a software probe can settle on the test machine has its
answer. What's left needs the ESP (D-6) or a Pi or a hat (D-20), or is notation only (D-2, D-10, D-14, D-16, D-18,
D-19).
