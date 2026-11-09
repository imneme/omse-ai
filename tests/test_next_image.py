"""image(): frame9's 9-bit colours widened 3 bits to 8 a channel as the Next's video output does (v << 5 | v << 2 |
v >> 1), then scaled. image() takes them through a 512-entry table over a numpy copy of the frame buffer
(frame9_array) rather than a Python generator; it must give the same bytes, for every colour and at every scale.
Slide Fern, Fri 6 Nov 2026 (after Tally Fern measured how long filming took)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import needs_next, NextCase  # noqa: E402


def widen(v):
    return v << 5 | v << 2 | v >> 1


def slow_rgb(values):
    """image()'s conversion as it was: a Python generator over frame9's list."""
    return bytes(c for v in values for c in (widen(v >> 6), widen((v >> 3) & 7), widen(v & 7)))


@needs_next
class Image9(NextCase):

    def test_all_512_colours(self):
        import next as nx
        t = nx._rgb9_table()
        want = np.array([[widen(v >> 6), widen((v >> 3) & 7), widen(v & 7)] for v in range(512)], np.uint8)
        self.assertEqual(t.shape, (512, 3))
        self.assertTrue(np.array_equal(t, want), 'each channel widened as v << 5 | v << 2 | v >> 1')

    def test_image_bytes_at_every_scale(self):
        from next import Next
        zx = Next(boot='bare', palette='loader')                      # power-on, but with the loader's colours
        pix = bytes((i * 37) & 0xFF for i in range(6144))            # a varied ULA screen: pixels and attributes
        attr = bytes(i & 0x7F for i in range(768))
        zx.load(0x4000, pix + attr)
        zx.run_frames(2)
        w, h, f9 = zx.frame9()
        arr = zx.frame9_array()
        self.assertEqual(arr.shape, (h, w))
        self.assertEqual(arr.ravel().tolist(), f9, 'frame9_array is frame9, as an array')
        self.assertGreaterEqual(len(set(f9)), 8, 'a frame with colours in it, so the comparison means something')
        ref = slow_rgb(f9)
        from PIL import Image
        for scale in (1, 2, 3):
            want = Image.frombytes('RGB', (w, h), ref).resize((w // 2 * scale, h * scale), Image.NEAREST)
            got = zx.image(scale=scale)
            self.assertEqual(got.size, want.size)
            self.assertEqual(got.tobytes(), want.tobytes(), f'scale {scale}: the same bytes as the per-pixel path')


if __name__ == '__main__':
    unittest.main()
