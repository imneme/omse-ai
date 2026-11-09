"""Compare a photo (capture frame) of a video probe with the model's picture: sample the centre of every 4x4
block of Spectrum pixels, learn how the capture renders each 3-bit level per channel from the samples
themselves, and report the blocks that disagree, grouped by paper row band.

  compare_photo.py N PHOTO [--band ROWS]      (N: 1-4; geometry from PV2's frame: paper x 428.5-1460.5,
                                               top 179.5, 3.745 capture rows per Spectrum row)

Hatch Fern, Fri 6 Nov 2026.
"""
import argparse
import importlib
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tests'))
sys.path.insert(0, str(HERE))
import nextvideo as nv  # noqa: E402
from PIL import Image  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('n', type=int)
ap.add_argument('photo')
ap.add_argument('--band', type=int, default=16)
ap.add_argument('--tol', type=int, default=48)
a = ap.parse_args()

X0, SX, Y0, SY = 428.5, 1032 / 256, 179.5, 3.745
pm = importlib.import_module(f'pv{a.n}_model')
if a.n == 1:
    w, h, want = pm.scene_model().frame9(pm.SCHEDULE)
else:
    sc = importlib.import_module(f'pv{a.n}_scene')
    w, h, want = nv.frame9_np(pm.scene_model(), sc.schedule())
im = Image.open(a.photo).convert('RGB')
px = im.load()


def photo_at(fx, fy):
    """Median colour of a small box around frame9 sample (fx, fy)'s centre."""
    sx, sy = fx / 2 - 48 + 0.25, fy - 48 + 0.5          # Spectrum coordinates, paper origin
    cx, cy = X0 + sx * SX, Y0 + sy * SY
    box = [px[int(cx) + dx, int(cy) + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    return tuple(statistics.median(c[i] for c in box) for i in range(3))


samples = []
for py in range(-32, 224, 4):                          # paper rows, in the visible window
    for sxp in range(-40, 296, 4):
        fx, fy = 2 * (sxp + 48) + 1, py + 48 + 2
        if not (0 <= fx < w and 0 <= fy < h):
            continue
        cx, cy = X0 + (sxp + 0.5) * SX, Y0 + (py + 2.5) * SY
        if not (2 <= cx < im.size[0] - 2 and 2 <= cy < im.size[1] - 2):
            continue
        m = want[fy * w + fx]
        samples.append((py, sxp, m, photo_at(fx, fy)))
levels = [[[] for _ in range(8)] for _ in range(3)]
for _, _, m, p in samples:
    for ch, shift in enumerate((6, 3, 0)):
        levels[ch][(m >> shift) & 7].append(p[ch])
lut = [[statistics.median(v) if v else None for v in levels[ch]] for ch in range(3)]
print('capture level per 3-bit value (R, G, B):')
for v in range(8):
    print('  %d: %s' % (v, ', '.join('-' if lut[ch][v] is None else '%3d' % lut[ch][v] for ch in range(3))))
bad = {}
for py, sxp, m, p in samples:
    exp = [lut[ch][(m >> s) & 7] for ch, s in enumerate((6, 3, 0))]
    if any(e is not None and abs(e - q) > a.tol for e, q in zip(exp, p)):
        bad.setdefault(py // a.band, []).append((py, sxp, m, p))
print(f'{len(samples)} samples; {sum(len(v) for v in bad.values())} disagree (tolerance {a.tol})')
for b in sorted(bad):
    v = bad[b]
    print(f'  rows {b * a.band}-{b * a.band + a.band - 1}: {len(v)}, e.g. ' +
          '; '.join(f'(x{s},y{r}) model {m:03o} photo {tuple(int(c) for c in p)}' for r, s, m, p in v[:3]))
