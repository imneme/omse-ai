# Sitting 3: PV5, the budget ruler, read

*Hatch Fern, Fri 6 Nov 2026. Frame: the photo (1080p HDMI capture; the beep decoded as
95/1). Same geometry as sitting 2: paper x 428.5-1460.5, 4.031
capture px per pixel. Scene: pv5_scene.py; all 128 slots written.*

## Where each strip stops

| strip             | drawn       | last sprite         | next     |
|-------------------|-------------|---------------------|----------|
| top, 4x (10-41)   | 10-28 (19)  | 28, whole: 144-207  | 29: none |
| middle, 2x (42-95)| 42-78 (37)  | 78, whole: 144-175  | 79: none |
| bottom, 8x (96-127)| 96-104 (9) | 104, whole: 64-191  | 105: none |

"Whole" means the closing outline is there:
- 20h at whc 205-207 for sprite 28 (its own 20h step reads the
  same, at 145-146)
- 40h at 174-175 for sprite 78
- 80h at 184-192 for sprite 104

"None" means the next sprite's outline step is absent where it
would start (whc 152, 148 and 72). The status reads 03.

The bottom strip repeats PV2's exactly, with every slot written
this time. **So leftover sprites were never the cause.**

## The rule shape

**No mid-sprite cutoff fits.** A search over linear costs found
nothing that puts the cut between two sprites in all three
strips at once:
- 0-4 cycles per sprite checked
- 0.25-4 per pixel
- up to 300 cycles of overhead per sprite, before or after its
  pixels

The VHDL reading cuts mid-sprite (sprites:831-832), so the real
machine doesn't do what I read there.

**A whole-sprite rule fits, with the VHDL's own costs:** one
cycle per sprite checked (drawn or not) and one per pixel drawn.
**A sprite is drawn only if it can finish before a deadline.**
Counting from the line reset (cycle 0 is line_reset_re = "01",
START is 1):

| strip  | last sprite finishes | the next would finish |
|--------|----------------------|-----------------------|
| top    | 1247                 | 1312                  |
| middle | 1265                 | 1298                  |
| bottom | 1259                 | 1388                  |

So the deadline D satisfies 1265 <= D <= 1297. That's 316-324
pixels after the reset at whc 511, or **whc 315-323**. whc 320
(cycle 1284), the sprite area's right edge, lies inside that
window. That may be where the line's sprites must be done, but
it isn't measured yet.

## Still open

1. D to the cycle, within 1265-1297.
2. **Skip or stop:** once a sprite doesn't fit, are later
   sprites that would fit still drawn? (In PV5 every later
   sprite is as wide as the dropped one, so it can't tell.)
3. Exactly when status bit 1 sets. It reads 03 here.

PV6 can settle 1 and 2. A row of 1x sprites (17 cycles each),
with the undrawn count before it stepped across several rows,
brackets D to a few cycles. A wide sprite that won't fit,
followed by narrow ones that would, answers skip-or-stop.

## For the reference model and the tests

The model (nextvideo._sprite_line) and SpriteBudget encode the
mid-sprite reading. They change to the measured rule once D and
skip-or-stop are known:
- line_runs_out_mid_sprite
- the_boundary_to_the_cycle
- status_says_overtime
- ProbeV2's and ProbeV5's strips
