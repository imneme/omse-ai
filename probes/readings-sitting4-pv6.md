# Sitting 4: PV6, the deadline, read

*Hatch Fern, Fri 6 Nov 2026. Frame: the photos
found/96-PV6-p1.png (the beep decoded as 96/1). Scene:
pv6_scene.py; predict(D, mode) gives each rule's counts.*

## What the frame shows

- **Top row:** the nine wide sprites and the 2x one draw. The 8x
  sprite that can't finish doesn't, and **none of the four small
  squares after it draw.**
- **The six rows below:** 2, 2, 3, 2, 2 and 2 squares, each whole.
- **Status:** 03.

## What it means

- **The engine stops** at the first sprite it can't finish.
  pv6_scene.predict matches the photo in "stop" mode only; no
  "skip" deadline matches at all. Skipping that sprite but paying
  its time would look the same, since everything after it would
  start past the deadline. In effect the rule is "stop".
- **The deadline D is 1281, 1282 or 1283.** Counting is as in
  PV5's reading:
  - cycle 0 is line_reset_re = "01", START is 1, and the first
    qualify is 2
  - one cycle per sprite qualified, one per pixel drawn
  - a sprite qualified at cycle c is drawn if c + 1 + width <= D
- **In whc,** the last pixel must land at cycle D - 1, 1280-1282.
  That's about whc 319: a line's sprites must be finished by the
  time the display reaches the right edge of the sprite area.

## The rule, for the core and the model

1. Count cycles from START as the VHDL does: 1 per qualify, 1 per
   pixel.
2. At a drawn sprite's qualify (cycle c), if c + 1 + width > D,
   don't draw it, set status bit 1, and draw nothing more this
   line.
3. Take **D = 1282**, the middle of what the photo allows.
4. Keep the line-reset cut only as a backstop.

**Not measured:** a sprite that crosses whc 320. The VHDL stops
processing it there (sprites:855), so is it charged its full width
or its shortened run? The rule above charges the full width (16
<< xscale), the simpler choice. A later card could settle it.

## Where this leaves the reading of the VHDL

sprites.vhd as read draws mid-sprite until the line reset, with
4 x 456 cycles. Her Next draws whole sprites with D about 1282.
Either the bitstream differs from the source we read, or there's
a check we haven't found. Ratio is re-reading with this shape in
mind. Either way, the core and the reference model follow the
machine.
