# Sitting 2: the video cards, read

*Hatch Fern, Fri 6 Nov 2026. Frames: the photos
91-PV1 to 94-PV4 (1920x1080 HDMI capture). Predictions: build/
pvN-vhdl.png. Numbers from compare_photo.py, which samples every
4x4 block against the model with the capture's own colour levels.
Geometry: paper x 428.5-1460.5 (4.031 px per pixel), top 179.5
(3.745 px per row). P1 on this sitting: core 3.02.02 (NR 01 = 32,
NR 0E = 02), issue 4 board, +3 timing (NR 03 = 33), 3.5 MHz.*

## PV3, the blend card: as the VHDL says

31 of 5376 samples disagree, and all 31 are row 22-23's printed
text (the model draws none). So every band matches the model:

- 1, 3 and 5 match. "ULA off" doesn't stop blend 00.
- 2 and 10 match.
- 6 and 8 put the ULA over the sprites; 7 and 9 put the sprites
  over it. NR 6B b0 decides "below" with the tilemap off, in
  blends 01 and 11 both.
- Row 22 reads "off:01 on:00". **The sprite engine flags a
  collision with sprites switched off** (NR 15 = 0): Rustyback's
  open question, settled as the VHDL says.
- My slip: band 11's Layer 2 covers row 22's left half, so
  "28:A5 34:65" can't be read (the model hides it too).

## PV4, the Layer 2 card: as the VHDL says

Every 256-wide band matches the model to the edge samples:
- the reference band
- "y+100" (the wrap at 192)
- "x+100"
- **"b6 y255=r79"**: with row + scroll past 384, Layer 2 reads
  rows 192 and up, in bank + 3. It doesn't wrap twice.
- **both "bank70" bands empty**: past SRAM's end is transparent

In the 640 and 320 bands the samples disagree, because the
capture's chroma subsampling smears their half-pixel colours. By
eye, r10 and r11 are one continuous 4-bit picture (so resolution
11 is 640x256x4), and the two offset-3 bands match.

## PV1, rerun: the same as sitting 1

Against sitting 1's frame, 0.072% of pixels differ by more than
48 levels, in thin edge noise (at most 3% of any character cell).
Nothing changed.

## PV2, the sprite card: all but the limit strip

Everything else matches. The status reads 03 (overtime and
collision), as predicted. **The strip doesn't:**

| whc     | colour        | what it is                        |
|---------|---------------|-----------------------------------|
| 8-63    | 10h ... 70h   | sprites 97-103's outline columns  |
| 64-72   | 80h           | sprite 104's outline              |
| 72-184  | 8Fh (purple)  | sprite 104's interior             |
| 184-192 | 80h           | sprite 104's closing outline      |
| 192 on  | black         | nothing                           |

Sprites 96-104 drew whole, and sprite 105 drew **no pixel at
all**: there's no 90h column at whc 72. The VHDL reading says
sprites 96-108 whole and 109 cut at whc 152.

In my cycle count (START, then 1 per qualify, 1 per pixel), the
real Next stopped between cycle 1258 (sprite 104's last pixel)
and cycle 1260 (sprite 105's first). The reading gives a whole
line, 4 x 456 = 1824. Two things don't fit:

1. 565 cycles are missing. The line is 456 pixels on this board
   too (HDMI changes only the window, zxula_timing:206-212), and
   CLK_28 is 4 x CLK_7 on the issue 4 board as well
   (top_issue4:955-958).
2. A cut that falls between two sprites is a 1-in-60 chance under
   a mid-sprite cutoff. The hardware may drop whole sprites, or
   charge something per sprite.

**One weakness is mine:** PV2 never wrote sprite slots 35-95.
Visible leftovers on the strip's rows would eat the line. PV3's
photo makes that unlikely: PV2's own strip sprites had been
cleared by then, presumably by NextZXOS at the reset. But it
isn't ruled out.

**So the rule isn't known yet. Don't change the core's budget on
this photo alone.** PV5 measures it properly:
- every one of the 128 slots written
- strips at three scales, so the budget, a per-sprite cost and a
  per-pixel cost can be solved for
- each cut read as mid-sprite or whole
