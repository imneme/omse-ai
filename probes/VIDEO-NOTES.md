# Video probe tapes for Melissa O'Neill's Spectrum Next

*Hatch Fern, Fri 06 Nov 2026, the video foil (`../video-notes.md`). Same shape and habits as Hart's-tongue
Fern's probes beside this file (`NOTES.md`): one screen to photograph, then a key soft-resets the Next.
Built by `build_pv.py`; each tape's checksums checked. "VHDL says" is what core 3.02.02's source predicts,
drawn by the reference model (`../tests/nextvideo.py`) as `build/pv*-vhdl.png`. Your Next is the
judge; the emulator draws the same scene in `tests/test_next_video.py`, class Probes.*

## Running one

1. Copy `build/PV1.TAP` to the SD card.
2. In NextBASIC: `.tapein pv1.tap`, then `LOAD ""`.
3. It shows one screen and waits. **Photograph it**, as squarely as you can, the whole screen and some
   border. Then any key soft-resets back to NextZXOS.

It writes the Layer 2 screen NextZXOS already uses (the bank NR 0x12 names), the ULA screen, some palette
entries and the copper. Interrupts stay off. The soft reset puts all of it back.

## P-V1 the layer card (`PV1.TAP`, pv1.asm)

Eight 16-line bands, one for each value of NR 0x15's layer order (bits 4:2). The copper sets each band's
order in the horizontal blanking just before it. In each band the left half has the ULA's checker (cyan cells,
and cells whose paper is the transparent colour E3) under Layer 2's red diagonal stripes and a yellow block
whose palette entry carries the priority bit. The right half has the band's label. Below the bands are two
verniers and three lines of caption.

**VHDL says** (`build/pv1-vhdl.png`; zxnext.vhd:7007-7263):

- **Bands 0, 1, 3** (SLU, LSU, LUS): red stripes on top of everything. Between them, cyan cells and grey ones
  (the fallback colour, NR 0x4A = 49, where both layers are transparent).
- **Bands 2, 4, 5** (SUL, USL, ULS): the cyan cells cover the stripes, which show only in the grey cells. The
  yellow block is on top anyway (the priority bit lifts it over everything).
- **Band 6** (add, capped at 7): red over cyan is **white**, red over a grey cell stays red, and yellow over
  cyan is white. Where Layer 2 is transparent the ULA **isn't drawn at all**: cyan-only cells are grey, and so
  is **the border across this band and the next** (navy elsewhere). With blend mode 00 the mix's top and
  bottom are the tilemap, so the ULA reaches the screen only through the sum.
- **Band 7** (add, minus 5): red over cyan is **dark grey**, red over grey stays red, and yellow over cyan is
  **green** (7+0, 7+7, 0+7 become 2, 7, 2). The label is dark grey on black. The label in band 6 is white.
- **Vernier A** (just below the bands): white ULA lines and red Layer 2 lines, both at x = 16k. **Red only**
  if the two layers line up to the pixel. My model assumes they do, and this is the one assumption the VHDL
  can't settle on its own.
- **Vernier B**: Layer 2's lines are one pixel right of the ULA's on purpose, so a red line beside a white one
  is what one pixel off looks like. If vernier A looks like vernier B, the layers are a pixel apart.

The things most worth a close look: the green in band 7's yellow block, the grey border beside bands 6 and 7,
and vernier A against vernier B.

## P-V2 the sprite card (`PV2.TAP`, pv2.asm; the scene is pv2_scene.py)

Run it as P-V1: `.tapein pv2.tap`, `LOAD ""`, photograph, any key. It writes the sprite RAMs, a Layer 2
stripe column, the ULA screen, a few palette entries and the copper; the soft reset puts them back. After
two frames it reads the sprite status (port 0x303B) and prints it at row 19, column 12.

**VHDL says** (`build/pv2-vhdl.png`, made by pv2_model.py from the reference model), top to bottom:

- **Anchors** (top left and top right; relatives sprites.vhd:756-792, anchor state 929-949).
  - Left, a composite anchor: the grid (red, green, blue and yellow quadrants in white lines) with three
    relatives. To its right, the grid in palette 1 (orange and blue). Below it, the F. Diagonally, the grid
    x-mirrored. A composite's relatives keep their own mirrors and rotation (sprites:782).
  - Right, a unified anchor, rotated and x-mirrored. Its relatives' offsets and transforms turn with it
    (sprites:760-763, 783). So the yellow F that's set to its right appears *below* it, the green F (palette
    2) that's set below appears to its *right*, and both Fs are rotated with it.
- **Scales** (sprites:907-927): the grid at 1x, 2x, 4x and 8x wide (16, 32, 64 and 128 px), so its white
  lines repeat 1, 2, 4 and 8 times. In the right border, one grid 2x tall (sprites:807-810).
- **The F eight ways** (sprites:811-820): left to right, rot/x mirror/y mirror = 000, 001, ..., 111. The
  red corner dot says which way round each one is.
- **Priority bands**, paper rows 96-143: four 12-row bands where the copper sets NR 0x15's order to SLU,
  LSU, SUL and USL in turn, as in P-V1 (mixer zxnext:7123-7192).
  - Left, a solid sprite over the ULA checker, whose squares are cyan or transparent (the transparent
    ones show the grey-blue fallback). In the first three bands the sprite covers the checker. In USL the
    cyan squares cover the sprite, and it shows only through the transparent ones.
  - Middle, four sprites stepping across the red Layer 2 stripes. The sprite is over the stripes in SLU and
    SUL and under them in LSU. In USL the ULA's opaque black hides it completely, apart from its last four
    rows, which hang below the band into SLU again.
  - Right, an overlapping pair: the green (sprite 32) covers the pink (sprite 31). Higher numbers win, since
    sprite-zero-on-top is off.
- **The border and the clip**: a grid half in the left border, its left 8 px cut where the clip window
  starts (whc 8), and an F beside it, whole.
- **The per-line strip** (paper rows 162-177): 32 sprites, each 8x wide (128 px), 8 px apart. Each covers
  the one before from its own x onwards, so what shows is each sprite's first 8 px: its outline column,
  pattern colour 00 plus its palette offset (10h, 20h, ... F0h; sprite 0's column is clipped, and sprite
  16's is 00, black).
  - **The renderer has one line of time for the next line's sprites.** That's 4 x 456 cycles at 28 MHz on
    128K/+3 timing, and 4 x 448 on 48K or Pentagon. It spends one cycle qualifying each of the 128 sprites
    and one per pixel drawn, and what doesn't fit is never drawn (sprites:517-537, 826-866, 951-956).
  - So the colour steps stop at whc 111. Sprite 109's green interior (7Ch) runs from 112 to **152**, where
    the line's time runs out. Then comes sprite 108's pink interior (F3h) from 153 to 215, its closing
    outline column (C0h) from 216 to 223, and then nothing.
  - On 48K or Pentagon timing the green ends at **120** instead.
  - One pixel is one cycle, so the photo measures the budget to the cycle.
  - **The status should read `status 03`**: bit 1, a line ran out of time (sprites:977), and bit 0, sprites
    overlapped (sprites:991).
- **The bottom row is yellow on the Next and black in the model.** It is paper 6, which the probe never
  sets: the Next still has the loader's palette, and the model starts from the power-on palette, which is
  all zero.

The things most worth a close look: whether the unified group turns as one, where the strip's green ends,
and the status byte.

Checked before it went to you: the probe's own code, run on Ratio's core 20c589d (probes/run_pv.py), matches
the model's picture everywhere but the prompt row (paper 6, which the probe never sets) and prints
`status 03`.

## P-V3 the blend card (`PV3.TAP`, pv3.asm; the scene is pv3_scene.py)

Run it as P-V1 and P-V2: `.tapein pv3.tap`, `LOAD ""`, photograph squarely with some border, any key. It writes
palettes, the sprite RAMs, a Layer 2 screen, the ULA attributes and the copper; the soft reset puts them back.
(PV2 and PV3 both switch on the sprite and Layer 2 ports themselves, NR 0x83 bits 6-7, and put NR 0x83 back
once they've finished with the ports. NextZXOS already has them on.)

**The layout.** Twelve bands, each 16 rows tall, all showing the same three layers:
- Layer 2 in the left half: four colour columns, each 32 px wide (grey-blue, brick, green, olive). The right
  half is transparent.
- ULA paper columns, each 16 px wide, repeating grey, brown, transparent. Where nothing at all is drawn you
  see the fallback colour, magenta.
- Three sprites per band: white at x 40, over Layer 2 and the ULA; yellow at x 120, across Layer 2's right
  edge; cyan at x 168, where Layer 2 is transparent.

In each band the copper changes three things: the layer order (NR 0x15), NR 0x68's blend source and "ULA off"
bit, and NR 0x6B's bit 0. With the tilemap off, that bit decides whether the ULA counts as above or below the
sprites in blends 01 and 11 (zxnext:6770, 7046-7085).

**VHDL says** (`build/pv3-vhdl.png`; the mixer is zxnext:7000-7258), band by band from the top:
- 0: SLU, the reference. Sprites over Layer 2, over the ULA.
- 1: order 6, blend 00. Layer 2 + ULA added per channel, clamped at 7. Where Layer 2 is transparent you get
  the fallback, never the ULA alone. The sprites sit on top.
- 2: order 7, blend 00. The same sum minus 5, so darker.
- 3: **like band 1**, though "ULA off" is set: blend 00 takes the ULA from `ula_mix`, which ignores that bit
  (zxnext:7007-7008).
- 4: blend 10 with "ULA off". This blend takes `ula_final`, which "ULA off" empties, so you see Layer 2 alone
  (and the fallback on the right).
- 5: blend 10, ULA on: **like band 1**.
- 6: blend 01, NR 0x6B bit 0 = 0. The ULA is drawn **over the sprites**, which show only through its
  transparent columns. Layer 2 shows unblended.
- 7: blend 01, bit 0 = 1. The sprites are over the ULA, whole.
- 8: blend 11, bit 0 = 0: **like band 6**.
- 9: blend 11, bit 0 = 1: **like band 7**.
- 10: order 7, blend 00, "ULA off": **like band 2**.
- 11: SLU, with the text row.

So the pairs to compare are 1, 3 and 5; 2 and 10; 6 and 8; 7 and 9. If a pair differs on your Next, the
VHDL reading (or the VHDL) is wrong there. Band 6 against band 7 is the one the core got wrong first:
Ratio's core put the sprites over the ULA in both, until 20c589d.

**Row 22 should read `28:A5 34:65 off:01 on:00`:**
- `28:A5`: NR 0x28 reads back NR 0x44's stored first byte (zxnext:5337, 5911).
- `34:65`: NR 0x34 after selecting sprite 100 and one NR 0x75 step (sprites:603-606; zxnext:5939).
- `off:01`: the sprite flags with sprites **switched off** (NR 0x15 = 0) and two of them overlapping. The
  engine still renders and still flags the collision: NR 0x15 bit 0 doesn't reach sprites.vhd at all
  (zxnext:4269-4311). The second sources say otherwise, so your Next settles it.
- `on:00`: the card's own sprites never overlap and never run out of time.

The bottom row (the prompt) is ink 7 on paper 0, both set by the probe, so this time it should be white on
black on the Next as well as in the model.

Checked before it went to you: the probe's own code, run on Ratio's core 20c589d (probes/run_pv.py), draws
the model's picture to the sample (0 differ, outside the printed text) and prints those four values. On the
older 64d9b75, the scene test fails at band 6.

## P-V4 the Layer 2 card (`PV4.TAP`, pv4.asm; the scene is pv4_scene.py)

Run it as the others: `.tapein pv4.tap`, `LOAD ""`, photograph squarely with some border, any key. It writes
palettes, Layer 2 banks 8-10 (as P-V1 and P-V2 did, and no other memory), the ULA screen and the copper. It
puts NR 0x83 back; the soft reset puts back the rest.

**The layout.** Twelve bands, each 16 rows tall and labelled on the right in the ULA (white on blue). There's
one image in banks 8-10, byte (y, x) = (y + x/4) & FF, drawn through an identity palette, so it shows as
diagonal colour bands. The clip window keeps the 256-wide modes to x 0-95, and the wide modes to their first
192 columns (from the left border to paper x 159). That's so the wide modes read banks 8-10 and nothing else.

**VHDL says** (`build/pv4-vhdl.png`; layer2.vhd), band by band from the top:
- 0 `256 ref`: 256 x 192, image rows 0-15.
- 1 `320x8`: 320 x 256 at 8 bits, column-major (layer2:160), starting in the left border.
- 2 `640 r10` and 3 `640 r11=r10`: 640 x 256 at 4 bits; sixteen dark colours (00-0F). **They should match**,
  because bit 1 of the resolution alone picks 4-bit pixels (layer2:41, 198, 202).
- 4 `bank70 none` and 5 `640 70 none`: no Layer 2, just blue. With bank 70h the address reaches bit 21, past
  SRAM's end, and Layer 2 goes transparent (layer2:172-175). No memory is read.
- 6 `y+100 wrap`: rows 96-111 scrolled by 100 pass 192 and wrap to image rows 4-19 (layer2:156-158).
- 7 `640 off 3` and 8 `r11 off3=r7`: 640 mode with palette offset 3, added to the 4-bit pixel's empty top
  nibble, so greens (30-3F). **They should match.**
- 9 `b6 y255=r79`: bank 6, scroll 255, at rows 144-159. Row + scroll is 399-414. That's past 384, so
  subtracting 192 once leaves y = 207-222, which lies past the 192-row screen, in bank 6 + 3 = 9. **You should
  see image rows 79-94.** A machine that wrapped modulo 192 instead would show y = 15-30 from bank 6, whatever
  the 128K RAM's bank 6 holds.
- 10 `x+100`: columns 100-195 of rows 160-175.
- 11 `L2 off`: blue.

Checked before it went to you: the probe's own code, run on Ratio's core 20c589d (probes/run_pv.py), draws the
model's picture to the sample. On the older 64d9b75, bands 3 and 8 differ: the resolution 11 bug.

## P-V5 the budget ruler (PV5.TAP, pv5.asm; scene pv5_scene.py)

Why: PV2's limit strip stopped far sooner on your Next than
the VHDL reading says, and exactly between two sprites
(readings-sitting2-video.md). PV5 measures the rule.

Run it as the others: `.tapein pv5.tap`, `LOAD ""`,
photograph squarely, any key. It writes all 128 sprite slots
(the unused ones invisible, so no leftover sprite can take a
line's time), one pattern, the sprite palette and the ULA
attributes; NR 0x83 goes back, and the soft reset puts back
the rest. It prints the sprite status at row 22.

The card is three strips of overlapping sprites, each a
palette step. Every step shows a sprite's outline column then
a little of its interior. A whole sprite ends with its
interior, then its closing outline. A sprite cut by the
renderer's time ends in its interior, with no closing outline.

- top: sprites 10-41 at 4x (64 px), 8 px apart
- middle: sprites 42-95 at 2x (32 px), 4 px apart
- bottom: sprites 96-127 at 8x (128 px), 8 px apart: PV2's
  strip again, now with every other slot written

Each strip has a different number of undrawn sprites before it
(10, 42, 96) and a different sprite width, so the three cuts
separate a later start, a cost per sprite checked, and a cost
per sprite drawn.

**VHDL says** (build/pv5-vhdl.png), as whc:

| strip  | last sprite drawn | its pixels drawn       |
|--------|-------------------|------------------------|
| top    | 37 (#27)          | 216-272, 57 of 64: cut |
| middle | 95 (#53)          | 212-242, 31 of 32: cut |
| bottom | 109 (#13)         | 104-152, 49 of 128: cut |

If PV2's photo is right and only the budget is shorter (about
1259 cycles, the same costs), it would be:

| strip  | last sprite drawn | its pixels drawn       |
|--------|-------------------|------------------------|
| top    | 29 (#19)          | 152-163, 12 of 64: cut |
| middle | 78 (#36)          | 144-170, 27 of 32: cut |
| bottom | 104 (#8)          | 64-191, whole          |

Any other pattern means the costs differ too. Whether each
strip ends in a closing outline says whether the hardware cuts
mid-sprite or drops whole sprites. The status should read 03.

Checked before it went to you: its own code on core 16ed141
draws the model's picture to the sample, status 03 (run_pv.py).
Its photo beep decodes as tape 95, photo 1 (run_beep.py and
find_photos.py).

## P-V6 the deadline (PV6.TAP, pv6.asm; scene pv6_scene.py)

Why: PV5 showed your Next draws **whole sprites only**. A
sprite is drawn if it can finish by a deadline D, 1265-1297
cycles after the line reset (readings-sitting3-pv5.md). PV6
pins D, and asks what happens after a sprite that can't finish.

Run it as the others: `.tapein pv6.tap`, `LOAD ""`,
photograph squarely, any key. It writes all 128 sprite slots;
NR 0x83 goes back. The status prints on row 0.

The card:
- **Top row, skip or stop.** Nine wide sprites and one at 2x
  (all fit), then a wide sprite that can't finish, then four
  small squares on the right that would all fit. **Four squares:
  it skips past a sprite that can't finish. None: it stops**
  (or the dropped sprite spends its whole time).
- **Six rows below.** A block of wide sprites (all fit), then
  four small squares on the right. Count each row's squares.
  The row offsets differ, so the counts bracket D:

| D (cycles) | row 1 | row 2 | row 3 | row 4 | row 5 | row 6 |
|------------|-------|-------|-------|-------|-------|-------|
| 1265-1266  | 1     | 1     | 2     | 1     | 1     | 1     |
| 1267-1269  | 1     | 1     | 2     | 2     | 1     | 1     |
| 1270-1272  | 1     | 1     | 2     | 2     | 2     | 1     |
| 1273-1276  | 1     | 1     | 2     | 2     | 2     | 2     |
| 1277       | 2     | 1     | 2     | 2     | 2     | 2     |
| 1278-1280  | 2     | 2     | 2     | 2     | 2     | 2     |
| 1281-1283  | 2     | 2     | 3     | 2     | 2     | 2     |
| 1284-1286  | 2     | 2     | 3     | 3     | 2     | 2     |
| 1287-1289  | 2     | 2     | 3     | 3     | 3     | 2     |
| 1290-1293  | 2     | 2     | 3     | 3     | 3     | 3     |
| 1294       | 3     | 2     | 3     | 3     | 3     | 3     |
| 1295-1297  | 3     | 3     | 3     | 3     | 3     | 3     |

That holds whether it skips or stops: in these rows nothing is
dropped before the squares. D is counted as the cycle after a
sprite's last pixel, with START at 1 and the first qualify at 2.
A pattern not in the table means the costs aren't the VHDL's (1
per sprite checked, 1 per pixel), which would be news too.

The VHDL reading draws everything here, so its picture
(build/pv6-vhdl.png) shows all four squares on every row and
status 01. On your Next the skip row's dropped sprite should
also set bit 1: status 03.

Checked before it went to you: its own code on core e0bc141
draws the VHDL reading's picture to the sample (run_pv.py). Its
beep decodes as tape 96, photo 1.
