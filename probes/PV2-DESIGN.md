# P-V2 the sprite card: design (Hatch Fern, Fri 6 Nov 2026)

*Written before building, so a fold mid-build loses nothing. PV1 (pv1.asm, readings-pv1.md) is the model:
one photograph, "photo, then press a key", the VHDL's prediction from the reference model
(tests/nextvideo.py: sprite_lines, sprite_window), the same scene as a test (class Probes).*

## Questions for the test machine
1. Relative sprites: a **composite** anchor (relatives keep their own transforms) and a **unified** anchor
   (rotated + mirrored + 2x: the whole group turns together) (sprites.vhd:756-792, 929-950).
2. Scaling: 1x, 2x, 4x, 8x in X, and in Y, on a pattern with a 1-pixel grid, so the repeat is countable
   (sprites.vhd:807-810, 907-927, 954-956).
3. All eight mirror/rotate orientations of an asymmetric glyph ("F") (sprites.vhd:811-820).
4. Priorities: sprites crossing Layer 2 stripes and ULA cells in copper bands of NR 0x15 (SLU, LSU, SUL,
   USL), with NR 0x15 bit 6 (sprite 0 on top) in one band... (bit 6 is global; use two overlapping sprite
   pairs instead: lower index vs higher index, read against the zero-on-top rule) (sprites.vhd:972).
5. The clip window (NR 0x19) cutting a sprite, and sprites over the border (NR 0x15 bit 1) at the left
   edge (sprites.vhd:1043-1068).
6. **The per-line limit**: sprites 0..127 on one line, 2 px apart; the hardware stops where its time runs
   out ("at least 100", cl:3.02.02; sprites_overtime, sprites.vhd:977). The photo shows where the strip
   ends; the probe prints the status register (port 0x303B, bit 1 = max per line) read after a frame.
   The model has no limit yet: this strip is a measurement for the core and the model.

## Layout (paper rows; ULA labels on the right half, like PV1)
- rows 0-31: anchors (composite at left, unified at right), labelled.
- rows 32-63: scales: X 1/2/4/8 then Y 2/4/8, the grid pattern.
- rows 64-95: eight orientations of "F", labelled 0-7 (bits rot, xm, ym).
- rows 96-143: priority bands (copper, WAIT h=44 as PV1): SLU / LSU / SUL / USL, 12 rows each, sprites
  crossing a Layer 2 stripe column and a ULA checker; a pair overlapping to show lower vs higher index.
- rows 144-159: clip window cutting a sprite; a sprite half over the left border (over-border on).
- rows 160-175: the per-line strip (128 small sprites, one 16-px line; only a few px tall visible via the
  clip so it doesn't cover captions) and "status: N" printed.
- rows 176-191: captions; row 23 the prompt.

## Build plan
- Tables generated in Python (build_pv.py or a pv2_tables.py) as `db` data: sprite attributes (128 x 5),
  patterns (grid, F, solid, stripes: 4-6 patterns x 256 bytes), the copper list. The Z80 copies them to
  ports 0x303B/0x57/0x5B and NR 0x60-0x63, draws Layer 2's stripe column procedurally (as PV1), prints
  labels with probe.inc, reads 0x303B after a HALT-free wait of one frame (poll NR 0x1E/0x1F line), prints.
- Code limit 4K (probe.inc: 0x8000-0x8FFF); patterns 1.5K + attributes 640 + copper ~40 should fit.
- Model: pv2_model.py (like pv1_model.py) -> build/pv2-vhdl.png. Test: Probes.test_pv2_sprite_card.
- Per-line limit: the model and test leave the strip out of the comparison (mask its rows) until the
  hardware says where it stops; then model it (time per sprite: QUALIFY + 16 x scale PROCESS cycles at
  28 MHz within a line?) and test it.

## Status
- Scene defined (pv2_scene.py); model view renders (pv2_model.py -> build/pv2-vhdl.png). Layout fix: X scales
  1/2/4/8 + one Y 2x (taller Y scales ran through every section); the unified anchor at 1x (rotated,
  x-mirrored) so its group stays 32 px.
- 11:51 pv2_data.py writes pv2_data.inc (palette, patterns, sprite records, copper as db). Next: the generator is done; (attributes, patterns, palette, copper as db), pv2.asm (copy tables to
  ports/NRs, Layer 2 stripe column, ULA attrs + labels, wait a frame, read 0x303B, print status),
  build with build_pv.py (NAMES[2] = 'pv2-sprites'), check on omse-ai's 48K, then the test.
- 11:52 **pv2.asm written and built**: build/PV2.TAP (2560 bytes, checksums checked by build_pv.py). Checked on
  omse-ai's 48K: loads, runs to "status FF" (no 0x303B there) and the prompt. The frame wait polls NR 0x1F for
  line 240 and gives up after 65536 reads on a non-Next. Known model/photo difference: the prompt row's paper
  (attr 0x30, ULA entry 22) is NextZXOS's yellow on the Next and black in the model (zero palette), as in PV1;
  the model has no ULA text.
- Next: (1) the test Probes.test_pv2_sprite_card (machine vs model from pv2_model.writes(), masking the
  strip's rows 160-177 + 48 until the limit is known); (2) run it on Ratio's core in **my own copy**
  (a private build of that core); (3) VIDEO-NOTES.md section for PV2 + add the tape to the set.
- 11:53 **Probes/ProbeV2.test_pv2_sprite_card passes on Ratio's 64d9b75** (a private build of that core),
  strip rows masked. PV2 is checked: add PV2.TAP to the set, and write its
  VIDEO-NOTES section (what the VHDL says, from build/pv2-vhdl.png).
- From Tally (Speccy-Zone's review): the hardware renders a line's sprites during the line before, against a
  time budget, setting overtime and dropping the rest; Ratio's core draws at line start with no limit. My
  model agrees on the line before (sprites:539) and has no budget either. To do: check the budget in
  sprites.vhd (S_QUALIFY/S_PROCESS cycles per line, sprites_overtime at line_reset, sprites:841-977), model
  it, unmask the strip; consider a copper-multiplexed sprite row with a ruler on the card (a position
  rewritten mid-frame lands a line away in a core without the line-before render).
- 11:55 PV2's VIDEO-NOTES section written.
- **The sprite time budget, first reading (to confirm at sprites.vhd:516-545 and the state clocking):**
  the state machine runs on the 28 MHz clock (sprites:826-837); each line it restarts at S_START when
  hcounter = 511 (line_reset_s, sprites:518, edge-detected: line_reset_re) and visits every sprite in
  S_QUALIFY (1 cycle each, sprites:848-854); a drawn sprite then spends 1 cycle per output pixel in
  S_PROCESS (16 x scale, or until the x wrap stops it, sprites:855-863, 951-956). If the next line_reset
  arrives while not idle, sprites_overtime sets status bit 1 and S_START cuts the rest (sprites:831-832,
  977). Budget = one line = 456 x 4 = 1824 cycles (+3/128K), 448 x 4 = 1792 (48K/Pentagon), less S_START
  and the edge detect. The strip: QUALIFY of sprites 0-95 (96 cycles) then 129 per 8x sprite -> about 13
  whole strip sprites (96-108) and a 14th cut part-way (~46 px), so the colour steps should stop near
  x = 104-150 (whc), with status bit 1 set. The photo will pin the offset to a few cycles.
- 12:08 **Budget reading confirmed and corrected** (sprites.vhd read whole around it). S_PROCESS also stops once
  hcount passes 319 unless the sprite is wrapping (sprites:855), so a sprite off the right costs 320 - x
  cycles, or 1 if it starts past 320. The first PROCESS cycle always happens. Line buffers write on the
  inverted clock and swap at the next reset, so cycles up to and including 4L land (sprites:470-501,
  531-537). The strip's cut is at whc 152 (+3/128K timing) and 120 (48K/Pentagon), and the status is 03.
  The model has it (nextvideo.sprite_budget, _sprite_line, sprite_status), the strip is unmasked, and the
  SpriteBudget tests are written. Against 64d9b75 everything passes except the six budget checks, which
  wait for Ratio's budget.
