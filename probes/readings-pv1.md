# P-V1 the layer card: the reading of the photo

*Hatch Fern, Fri 6 Nov 2026. Photo: the photo (the test machine, a 1920x1080 capture,
"16:9 black bars as usual"). Prediction: (the reference model, `../tests/
nextvideo.py`). Crops: .*

**Verdict: the real Next draws what the VHDL reading says, everywhere the card looks.** Nothing in the
model or the core needs to change for this card (the core has matched the model on this scene since
84efb01).

| What the card asks | VHDL says | the test machine |
|---|---|---|
| Bands 0, 1, 3 (SLU LSU LUS) | red stripes on top of everything | yes |
| Bands 2, 4, 5 (SUL USL ULS) | cyan covers the stripes; they show only in grey cells; the yellow priority block on top | yes |
| Band 6 (add, cap 7) | red over cyan white; yellow over cyan white; cyan alone grey | yes |
| Band 7 (add, minus 5) | red over cyan dark grey; **yellow over cyan green** (7+0, 7+7, 0+7 -> 2, 7, 2); yellow over grey stays yellow | **yes: green cells alternate with yellow exactly as predicted** |
| The border beside bands 6-7 | grey fallback (blend mode 00 never draws the ULA by itself) | yes, a grey stripe across the border |
| Labels in bands 6 / 7 | white / dark grey on black | yes |
| **Vernier A** (both layers at x = 16k) | red only if Layer 2 and the ULA align | **red only: aligned to the pixel** |
| Vernier B (Layer 2 at 16k + 1) | white with red on its right | yes: the vernier can see one pixel |
| Left margin | black blanking, then navy border (§9.1 (14)) | consistent (the capture crops the edges) |

**What this settles.** The model's one assumption the VHDL couldn't settle alone, that Layer 2 and the
ULA reach the mixer aligned, is now confirmed on hardware. So are the mixer's order logic, the priority
bit, both blend modes' arithmetic (Speccy-Zone's review left the blends to the foil, and the green block
is the bit-exact proof), the copper landing NR 0x15 in the blanking before each band, and the fallback
colour where nothing draws.

**Not settled here.** Hart's-tongue's P-8 (Layer 2 over bank 5) seems to differ from the VHDL reading on the
real machine (main's first look). The model reads Layer 2 from SRAM as l2:169-188 says, so if P-8 shows
otherwise, `nextvideo.Video._layer2` and `_frame_np` change with it; P-V1 used Layer 2 in its own bank, so
it doesn't touch that question.
