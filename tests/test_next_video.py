"""The Next's picture: palettes, the ULA's modes, Layer 2 and the mixer, against a model from the VHDL.

The video foil (Hatch Fern): every scene is set up the same way on the machine and on nextvideo.Video
(written from the core 3.02.02 VHDL, independently of the core), and zx.frame9() (DESIGN.md §9.1 (12))
must equal the model's frame sample for sample. The scenes are drawn so mistakes are visible and
countable: every palette index used gets its own 9-bit colour (none equal to the transparent E3), bitmaps
encode their own addresses, and edges sit on distinct colours. On a mismatch the test names the count,
the first samples, and writes got / want / difference pictures to next-build/video-diffs/.

Until next.py exists these skip, naming the missing machine. Once it exists, anything missing fails.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextvideo as nv                                  # noqa: E402

DIFFS = Path.home() / 'next-build/video-diffs'


def _machine():
    try:
        import next as nextmod                          # noqa: F401
    except ModuleNotFoundError as e:
        if e.name == 'next':
            return None, 'needs the Next machine (next.py, DESIGN.md §9), not built yet'
        raise
    return nextmod.Next, None


Next, WHY = _machine()
needs_next = unittest.skipIf(Next is None, WHY or '')

PARK = 0x8000
LOOP = bytes([0xF3, 0x18, 0xFE])                        # DI; JR $ (on itself)


# ---------------------------------------------------------------------------- scenes

class Scene:
    """A list of writes, applied identically to a machine and to the model."""

    def __init__(self, palette='zero'):
        self.palette = palette
        self.ops = []

    def nr(self, n, *vals):
        for v in vals:
            self.ops.append(('nr', n, v))
        return self

    def io(self, port, v):
        self.ops.append(('io', port, v))
        return self

    def bram5(self, addr, data):
        self.ops.append(('bram5', addr, bytes(data)))
        return self

    def bram7(self, addr, data):
        self.ops.append(('bram7', addr, bytes(data)))
        return self

    def sram(self, addr, data):
        self.ops.append(('sram', addr, bytes(data)))
        return self

    def model(self):
        v = nv.Video(palette=self.palette)
        for op in self.ops:
            kind = op[0]
            if kind == 'nr':
                v.nr_write(op[1], op[2])
            elif kind == 'io':
                v.io_out(op[1], op[2])
            else:
                mem = {'bram5': v.bram5, 'bram7': v.bram7, 'sram': v.sram}[kind]
                mem[op[1]:op[1] + len(op[2])] = op[2]
        return v

    def machine(self, frames=2):
        kw = {} if self.palette == 'zero' else {'palette': self.palette}
        zx = Next(boot='bare', **kw)
        zx.load(PARK, LOOP)
        zx.set_regs(pc=PARK, sp=0x7FF0)
        for op in self.ops:
            kind = op[0]
            if kind == 'nr':
                zx.nr_write(op[1], op[2])
            elif kind == 'io':
                zx.io_out(op[1], op[2])
            else:
                mem = {'bram5': zx.bram5, 'bram7': zx.bram7, 'sram': zx.sram}[kind]
                for i, b in enumerate(op[2]):
                    mem[op[1] + i] = b
        zx.run_frames(frames)
        return zx


def unique_palette(seed=0):
    """256 distinct 9-bit colours, none whose bits 8:1 are the default transparent 0xE3: a permutation of
    0-511 (an odd multiplier mod 512 visits every value), the two transparent colours left out."""
    perm = [(i * 167 + seed * 61 + 13) % 512 for i in range(512)]
    return [c for c in perm if (c >> 1) != 0xE3][:256]


def write_palette(scene, select, colours, start=0):
    """Write 9-bit colours through NR 0x44 into the palette that NR 0x43 bits 6:4 = select picks."""
    scene.nr(0x43, select << 4)
    scene.nr(0x40, start)
    for c in colours:
        scene.nr(0x44, c >> 1, c & 1)
    scene.nr(0x43, 0x00)
    return scene


def address_bitmap(salt=0):
    """6144 bitmap bytes, each a function of its own (third, line, row, column), so any addressing slip
    shows; and 768 attributes covering all 128 non-flash values (FLASH has its own test)."""
    bm = bytearray(6144)
    for a in range(6144):
        third, line, row, col = a >> 11, (a >> 8) & 7, (a >> 5) & 7, a & 31
        y = third * 64 + row * 8 + line
        bm[a] = ((y * 7 + col * 13 + salt) * 0x9D + (y ^ col)) & 0xFF
    at = bytearray((i * 37 + salt) & 0x7F for i in range(768))
    return bm, at


class VideoCase(unittest.TestCase):

    def assertFrameMatches(self, scene, frames=2, name=None):
        zx = scene.machine(frames)
        got_w, got_h, got = zx.frame9()
        want_w, want_h, want = nv.frame9_np(scene.model())
        self.assertEqual((got_w, got_h), (want_w, want_h), 'frame9 size (§9.1 (12))')
        got = list(got)
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        if bad:
            path = self._save_diff(name or self.id().split('.')[-1], got, want, bad)
            first = ', '.join(f'({i % want_w},{i // want_w}) got {got[i]:03o} want {want[i]:03o}'
                              for i in bad[:6])
            self.fail(f'{len(bad)} of {len(want)} samples differ; first: {first}; pictures: {path}')

    def _save_diff(self, name, got, want, bad):
        try:
            from PIL import Image
        except ImportError:
            return '(no PIL)'
        DIFFS.mkdir(parents=True, exist_ok=True)

        def img(vals):
            im = Image.new('RGB', (nv.W, nv.H))
            im.putdata([(((c >> 6) & 7) * 255 // 7, ((c >> 3) & 7) * 255 // 7, (c & 7) * 255 // 7) for c in vals])
            return im
        sheet = Image.new('RGB', (nv.W, nv.H * 3 + 8), (64, 64, 64))
        sheet.paste(img(got), (0, 0))
        sheet.paste(img(want), (0, nv.H + 4))
        badset = set(bad)
        diff = Image.new('RGB', (nv.W, nv.H))
        diff.putdata([(255, 0, 255) if i in badset else (0, 0, 0) for i in range(nv.W * nv.H)])
        sheet.paste(diff, (0, 2 * nv.H + 8))
        path = DIFFS / f'{name}.png'
        sheet.save(path)
        return str(path)


def ula_scene(palette_seed=1, salt=0, border=5):
    s = Scene()
    write_palette(s, 0b000, unique_palette(palette_seed))
    bm, at = address_bitmap(salt)
    s.bram5(0x0000, bm).bram5(0x1800, at).io(0x00FE, border)
    return s


# ---------------------------------------------------------------------------- the model's own sense

class ModelSense(unittest.TestCase):
    """The model against facts read straight off the VHDL, without the machine."""

    def test_numpy_path_matches_the_reading(self):
        """frame9_np (fast, used by the scenes) against Video.frame9 (the cited reading) on sampled rows."""
        import random
        scenes = {'ula': ula_scene(), 'ula+': None, 'l2': l2_scene(0), 'l2-320': l2_scene(1),
                  'l2-640': l2_scene(2).nr(0x70, 0x25), 'tm': tm_scene(0x80), 'tm80': tm_scene(0xC0),
                  'tmtext': tm_scene(0x88), 'lores': ula_scene(12).nr(0x15, 0x80).nr(0x6A, 0x03)}
        s = ula_scene(8).io(0xBF3B, 0x40).io(0xFF3B, 0x01)
        scenes['ula+'] = s
        for order in range(8):
            scenes[f'order{order}'] = l2_scene(0).nr(0x15, order << 2).nr(0x68, (order % 4) << 5)
        scenes['sprites'] = sprite_scene(0x03, mixed_sprites())
        scenes['sprites0top'] = sprite_scene(0x41 | (4 << 2), mixed_sprites())
        scenes['sprites-rel'] = sprite_scene(0x23, [[60, 40, 0x10, 0xC0 | 2, 0x20], [16, 0, 0x01, 0xC0 | 3, 0x41],
                                                    [0, 16, 0x0A, 0xC0 | 4, 0x40]])
        rows = set(random.Random(5).sample(range(288), 4)) | {20, 60, 140}
        for name, sc in scenes.items():
            with self.subTest(scene=name):
                v = sc.model()
                fast = nv.frame9_np(v)[2]
                slow = v.frame9(rows=rows)[2]
                bad = [i for i, x in enumerate(slow) if x is not None and x != fast[i]]
                self.assertEqual(bad[:5], [], f'{len(bad)} samples differ between the two paths')

    def test_power_on_picture_is_black(self):
        self.assertEqual(set(nv.Video().frame9()[2]), {0}, '§9.1 (13): palette RAMs start all zero')

    def test_loader_border_colours(self):
        v = nv.Video(palette='loader')
        for b in range(8):
            v.io_out(0xFE, b)
            self.assertEqual(v.frame9(blank=False)[2][0], nv.rgb9_from8(nv.LOADER_ULA16[b]),
                             'border = ULA paper index 16 + colour (ula:418, 547-552; vdp:65-84)')

    def test_nr41_ninth_bit_is_b1_or_b0(self):
        self.assertEqual([nv.rgb9_from8(x) for x in (0x00, 0x01, 0x02, 0x03, 0xFC)],
                         [0x000, 0x003, 0x005, 0x007, 0x1F8], 'zxnext:4858')

    def test_palette_write_lands_before_the_increment(self):
        v = nv.Video()
        v.nr_write(0x40, 7)
        v.nr_write(0x41, 0xAB)
        self.assertEqual((v.ulatm[7], v.pal_idx), (nv.rgb9_from8(0xAB), 8), 'zxnext:4726, 5316-5318')

    def test_blanking_margins(self):
        """§9.1 (14): blanking is black; +3 timing shows 40 px of left border, 48K timing 32 (ulat:154-168;
        zxnext:7311-7315)."""
        for timing, black in (('p3', 16), ('48k', 32)):
            v = nv.Video(palette='loader', timing=timing)
            v.io_out(0xFE, 2)
            f = nv.frame9_np(v)[2]
            g = nv.frame9_np(v, blank=False)[2]
            row = f[100 * nv.W:101 * nv.W]
            self.assertEqual(row[:black + 1], [0] * black + [nv.rgb9_from8(0xA0)], timing)
            self.assertEqual(set(g[100 * nv.W:100 * nv.W + black]), {nv.rgb9_from8(0xA0)}, timing)

    def test_layer2_priority_bit_from_nr44(self):
        v = nv.Video()
        v.nr_write(0x43, 0x10)
        v.nr_write(0x44, 0x12)
        v.nr_write(0x44, 0x81)
        self.assertEqual(v.l2s[0], 0x8000 | (0x12 << 1) | 1, 'zxnext:4859, 6932')
        v.nr_write(0x40, 0)                           # the index stepped past it (zxnext:5338-5339)
        self.assertEqual((v.nr_read(0x41), v.nr_read(0x44)), (0x12, 0x81), 'zxnext:5945-5955')


# ---------------------------------------------------------------------------- the palettes

@needs_next
class Blanking(VideoCase):
    """§9.1 (14): frame9() is the screen with blanking (black), frame9(blank=False) the mixer's colour."""

    def test_left_margin_is_black_and_unblanked_shows_border(self):
        s = ula_scene(border=6)
        zx = s.machine()
        self.assertEqual(list(zx.frame9()[2]), nv.frame9_np(s.model())[2])
        self.assertEqual(list(zx.frame9(blank=False)[2]), nv.frame9_np(s.model(), blank=False)[2])


@needs_next
class Palettes(VideoCase):
    """NR 0x40-0x44: the write path, the 9th bit, auto-increment, routing, readback (zxnext:4857-4859,
    5312-5341, 5942-5955, 6859-6960)."""

    def test_bare_power_on_is_black(self):
        zx = Scene().machine()
        self.assertEqual(set(zx.frame9()[2]), {0}, '§9.1 (13): palette RAMs start all zero')

    def test_loader_palettes(self):
        s = Scene(palette='loader')
        bm, at = address_bitmap()
        s.bram5(0, bm).bram5(0x1800, at).io(0xFE, 3)
        self.assertFrameMatches(s)

    def test_nr41_and_nr44_write_paths(self):
        s = Scene()
        s.nr(0x40, 0)
        for i in range(16):                           # entries 0-15 by NR 0x41 (the 9th bit = b1|b0)
            s.nr(0x41, (i * 0x35 + 0x01) & 0xFF)
        for i in range(16, 32):                       # 16-31 by NR 0x44, low blue bit alternating
            s.nr(0x44, (i * 0x29) & 0xFF, i & 1)
        bm, at = address_bitmap(3)
        s.bram5(0, bm).bram5(0x1800, at).io(0xFE, 6)
        self.assertFrameMatches(s)

    def test_autoincrement_disabled(self):
        s = Scene()
        s.nr(0x43, 0x80).nr(0x40, 3).nr(0x41, 0x1C, 0xE0, 0x03)   # all three land on entry 3
        s.nr(0x43, 0x00).nr(0x41, 0xFF)                            # 3 again (index never moved), then 4
        s.io(0xFE, 3).io(0xFE, 4)
        s.nr(0x40, 19).nr(0x41, 0x55)                              # paper index 16 + 3 for the attrs
        s.bram5(0x1800, bytes([0x18] * 768))                       # paper 3, ink 0
        self.assertFrameMatches(s)

    def test_routing_to_all_eight_palettes_and_readback(self):
        zx = Next(boot='bare')
        model = nv.Video()
        for sel in range(8):
            for dev in (zx, model):
                dev.nr_write(0x43, sel << 4)
                dev.nr_write(0x40, 0x5A)
                dev.nr_write(0x44, 0x10 + sel * 0x11)
                dev.nr_write(0x44, 0x80 | (sel & 1))
        for sel in range(8):
            for dev in (zx, model):
                dev.nr_write(0x43, sel << 4)
                dev.nr_write(0x40, 0x5A)
            self.assertEqual((zx.nr_read(0x41), zx.nr_read(0x44)),
                             (model.nr_read(0x41), model.nr_read(0x44)),
                             f'palette {sel:03b} entry 0x5A (zxnext:5945-5955, 6859-6860)')

    def test_second_ula_palette_shown(self):
        s = ula_scene(1)
        write_palette(s, 0b100, unique_palette(9))
        s.nr(0x43, 0x02)                              # show the second ULA palette (zxnext:5331, 6732)
        self.assertFrameMatches(s)


# ---------------------------------------------------------------------------- the ULA

@needs_next
class Ula(VideoCase):
    """zxula.vhd: the standard screen, the border, clip, scroll, Timex modes, ULA+, ULANext."""

    def test_standard_screen(self):
        self.assertFrameMatches(ula_scene())

    def test_every_border_colour(self):
        for b in range(8):
            with self.subTest(border=b):
                self.assertFrameMatches(ula_scene(border=b), name=f'border_{b}')

    def test_transparent_colour_shows_fallback(self):
        s = ula_scene(2)
        pal = unique_palette(2)
        s.nr(0x14, pal[16 + 2] >> 1)                  # paper colour 2 becomes transparent (zxnext:7007)
        s.nr(0x4A, 0x6D)                              # ...and the fallback shows through (zxnext:7121)
        self.assertFrameMatches(s)

    def test_clip_window_edges(self):
        s = ula_scene(3)
        s.nr(0x1C, 0x04).nr(0x1A, 17, 230, 9, 182).nr(0x4A, 0x92)
        self.assertFrameMatches(s)

    def test_clip_y2_above_bf_means_bf(self):
        s = ula_scene(3)
        s.nr(0x1C, 0x04).nr(0x1A, 0, 255, 100, 0xD0).nr(0x4A, 0x92)   # zxnext:6686-6690
        self.assertFrameMatches(s)

    def test_scroll_x_y(self):
        s = ula_scene(4).nr(0x26, 13).nr(0x27, 37)
        self.assertFrameMatches(s)

    def test_scroll_wraps_at_192_rows(self):
        s = ula_scene(4).nr(0x27, 191)
        self.assertFrameMatches(s)

    def test_fine_scroll_half_pixel(self):
        s = ula_scene(4).nr(0x26, 5).nr(0x68, 0x04)   # NR 0x68 bit 2 (ula:199, 353)
        self.assertFrameMatches(s)

    def test_ula_disabled_shows_fallback(self):
        s = ula_scene(5).nr(0x68, 0x80).nr(0x4A, 0x31)   # zxnext:5383, 7010
        self.assertFrameMatches(s)

    def test_timex_screen_1(self):
        s = ula_scene(6)
        bm, at = address_bitmap(9)
        s.bram5(0x2000, bm).bram5(0x3800, at).io(0x00FF, 0x01)
        self.assertFrameMatches(s)

    def test_timex_hi_colour(self):
        s = ula_scene(6)
        bm, _ = address_bitmap(11)
        s.bram5(0x2000, bytes(b & 0x7F for b in bm)).io(0x00FF, 0x02)
        self.assertFrameMatches(s)

    def test_timex_hi_res_and_its_border(self):
        for colour in (0, 3, 7):
            with self.subTest(colour=colour):
                s = ula_scene(6)
                bm, _ = address_bitmap(13)
                s.bram5(0x2000, bm).io(0x00FF, 0x06 | (colour << 3))
                self.assertFrameMatches(s, name=f'hires_{colour}')

    def test_shadow_screen_reads_bank_7(self):
        s = ula_scene(7)
        bm, at = address_bitmap(17)
        s.bram7(0, bm).bram7(0x1800, at).io(0x7FFD, 0x08)
        self.assertFrameMatches(s)

    def test_ula_plus(self):
        s = ula_scene(8)
        s.io(0xBF3B, 0x40).io(0xFF3B, 0x01)           # mode group 01: ULA+ on (zxnext:4489-4490)
        for i in range(64):
            s.io(0xBF3B, i).io(0xFF3B, (i * 0x47 + 3) & 0xFF)   # GGGRRRBB (zxnext:4682-4686)
        bm, _ = address_bitmap(19)
        s.bram5(0x1800, bytes((i * 53) & 0xFF for i in range(768)))   # all four CLUTs, FLASH bit is a CLUT bit
        self.assertFrameMatches(s)

    def test_ulanext_formats(self):
        for fmt in (0x07, 0x0F, 0x01, 0x7F, 0xFF, 0x05):
            with self.subTest(fmt=fmt):
                s = ula_scene(10)
                write_palette(s, 0b000, unique_palette(11))
                s.nr(0x42, fmt).nr(0x43, 0x01).nr(0x4A, 0x5B)
                s.bram5(0x1800, bytes((i * 29 + 7) & 0xFF for i in range(768)))
                self.assertFrameMatches(s, name=f'ulanext_{fmt:02x}')


# ---------------------------------------------------------------------------- Layer 2 and the mixer

def l2_scene(res=0, seed=21, bank=8):
    """Layer 2 shown over the ULA scene; its bytes encode their own address, a band of the transparent
    colour E3 crosses it, and its palette is unique (with entry 0xE3 set to the colour 0xE3)."""
    s = ula_scene(1)
    pal = unique_palette(seed)
    pal[0xE3] = nv.rgb9_from8(0xE3)
    write_palette(s, 0b001, pal)
    size = 48 * 1024 if res == 0 else 80 * 1024
    data = bytearray(size)
    for a in range(size):
        data[a] = ((a * 0x2F) ^ (a >> 8) ^ (a >> 13)) & 0xFF
        if (a >> 8) % 23 == 7:                        # a band of transparent pixels
            data[a] = 0xE3
    s.sram(nv.L2_SRAM_BASE + bank * 0x4000, data)
    s.nr(0x12, bank).nr(0x70, res << 4).io(0x123B, 0x02)
    return s


@needs_next
class Layer2(VideoCase):
    """layer2.vhd and the mixer's orders (zxnext:7087-7263)."""

    def test_256x192_over_the_ula(self):
        self.assertFrameMatches(l2_scene(0))

    def test_every_layer_order(self):
        for order in range(8):
            with self.subTest(order=order):
                s = l2_scene(0).nr(0x15, order << 2)
                self.assertFrameMatches(s, name=f'order_{order}')

    def test_priority_bit_lifts_layer_2(self):
        for order in (2, 4, 5):                       # orders with L below U
            with self.subTest(order=order):
                s = l2_scene(0)
                s.nr(0x43, 0x10).nr(0x40, 0x40)
                for i in range(64):                   # entries 0x40-0x7F get the priority bit
                    s.nr(0x44, (i * 3) & 0xFF, 0x80 | (i & 1))
                s.nr(0x43, 0x00).nr(0x15, order << 2)
                self.assertFrameMatches(s, name=f'priority_{order}')

    def test_clip_scroll_and_palette_offset(self):
        s = l2_scene(0).nr(0x1C, 0x01).nr(0x18, 11, 244, 5, 186)
        s.nr(0x16, 77).nr(0x17, 150).nr(0x70, 0x03)
        self.assertFrameMatches(s)

    def test_320x256(self):
        s = l2_scene(1).nr(0x1C, 0x01).nr(0x18, 3, 155, 2, 251)
        self.assertFrameMatches(s)

    def test_320x256_scroll_wraps_at_320(self):
        s = l2_scene(1).nr(0x16, 0x30).nr(0x71, 0x01).nr(0x17, 200)
        self.assertFrameMatches(s)

    def test_640x256(self):
        s = l2_scene(2).nr(0x70, 0x25)
        self.assertFrameMatches(s)

    def test_blend_modes(self):
        for order in (6, 7):
            for blend in (0, 2, 3):
                with self.subTest(order=order, blend=blend):
                    s = l2_scene(0).nr(0x15, order << 2).nr(0x68, blend << 5)
                    self.assertFrameMatches(s, name=f'blend_{order}_{blend}')



# ---------------------------------------------------------------------------- the probes' scenes

def pv1_scene():
    """P-V1 (next-build/probes/pv1.asm), the layer card: the same registers, Layer 2 and ULA screen, with the
    copper changing NR 0x15 in the blanking before each 16-line band. Returns (scene, schedule)."""
    import os
    rom = Path(os.environ.get('OMSE_AI_ROMS', Path.home() / 'omse-ai/roms')) / '48.rom'
    font = rom.read_bytes()[0x3D00:0x4000]
    s = Scene()
    for n, v in [(0x43, 0x00), (0x40, 0x00), (0x41, 0x00), (0x40, 0x07), (0x41, 0xFF), (0x40, 0x10),
                 (0x41, 0x00), (0x40, 0x11), (0x41, 0x02), (0x40, 0x15), (0x41, 0x1F), (0x40, 0x17),
                 (0x41, 0xE3), (0x43, 0x10), (0x40, 0xE3), (0x41, 0xE3), (0x40, 0xE0), (0x41, 0xE0),
                 (0x40, 0x00), (0x41, 0x00), (0x40, 0xFC), (0x44, 0xFC), (0x44, 0x80), (0x43, 0x00),
                 (0x14, 0xE3), (0x4A, 0x49), (0x15, 0x00), (0x68, 0x00), (0x70, 0x00), (0x16, 0x00),
                 (0x17, 0x00), (0x71, 0x00), (0x1C, 0x01), (0x18, 0x00), (0x18, 0xFF), (0x18, 0x00),
                 (0x18, 0xBF), (0x12, 0x08)]:
        s.nr(n, v)
    l2 = bytearray(256 * 192)
    for y in range(192):
        for x in range(256):
            if y < 128:
                if x < 128:
                    p = 0xFC if (96 <= x < 120 and 4 <= (y & 15) < 12) else (0xE0 if ((x + y) & 15) < 6 else 0xE3)
                else:
                    p = 0x00 if y >= 96 else 0xE3
            elif y < 144:
                p = 0xE0 if (x & 15) == 0 else 0xE3
            elif y < 160:
                p = 0xE0 if (x & 15) == 1 else 0xE3
            else:
                p = 0xE3
            l2[y * 256 + x] = p
    s.sram(nv.L2_SRAM_BASE + 8 * 0x4000, l2)
    bm, at = bytearray(6144), bytearray(768)
    for row in range(24):
        for col in range(32):
            if row < 16 and col < 16:
                at[row * 32 + col] = 0x28 if (row + col) & 1 else 0x38
            else:
                at[row * 32 + col] = 0x30 if row == 23 else 0x07

    def addr(row, line, col):
        return ((row & 0x18) << 8) | (line << 8) | ((row & 7) << 5) | col
    for row in range(16, 20):
        for line in range(8):
            for col in range(0, 32, 2):
                bm[addr(row, line, col)] = 0x80
    texts = [(2 * b, 17, t) for b, t in enumerate(['0 SLU', '1 LSU', '2 SUL', '3 LUS', '4 USL', '5 ULS',
                                                   '6 L+U', '7 L+U-5'])]
    texts += [(2 * b + 1, 17, t) for b, t in enumerate(['L over U', 'L over U', 'U over L', 'L over U',
                                                       'U over L', 'U over L', 'add, max 7', 'add, minus 5'])]
    texts += [(20, 0, 'P-V1: one NR15 order per band'), (21, 0, 'Vernier A: red only = aligned'),
              (22, 0, 'Vernier B: 1px off on purpose'), (23, 0, 'Photo, please. Key: soft reset')]
    for row, col, t in texts:
        for k, ch in enumerate(t):
            g = font[(ord(ch) - 32) * 8:(ord(ch) - 32) * 8 + 8]
            for line in range(8):
                bm[addr(row, line, col + k)] = g[line]
    s.bram5(0, bm).bram5(0x1800, at).io(0x123B, 0x02).io(0x00FE, 0x01)
    # the copper: WAIT (16b - 1, 44), MOVE NR 0x15 <- b << 2, ..., then SLU at row 128; mode 11
    words = [w for b in range(1, 8) for w in (0xD800 | (16 * b - 1), 0x1500 | (b << 2))]
    words += [0xD87F, 0x1500, 0xFFFF]
    s.nr(0x62, 0x00).nr(0x61, 0x00)
    for w in words:
        s.nr(0x63, w >> 8, w & 0xFF)
    s.nr(0x62, 0xC0)
    schedule = [(48 + 16 * b, 0x15, b << 2) for b in range(1, 8)] + [(48 + 128, 0x15, 0x00)]
    return s, schedule


@needs_next
class Probes(VideoCase):
    """The probe tapes' scenes, so the emulator's picture, the model's and the photograph can meet."""

    def test_pv1_layer_card(self):
        s, schedule = pv1_scene()
        zx = s.machine(frames=3)
        w, h, got = zx.frame9()
        want = nv.frame9_np(s.model(), schedule)[2]
        got = list(got)
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        if bad:
            path = self._save_diff('pv1_layer_card', got, want, bad)
            self.fail(f'{len(bad)} samples differ, first at ({bad[0] % w},{bad[0] // w}); pictures: {path}')


@needs_next
class LoRes(VideoCase):
    """lores.vhd: 128x96 in 8 bits or Radastan's 4, in the ULA's place, inside the ULA's clip window."""

    def lores_scene(self, radastan=False):
        s = ula_scene(12)
        data = bytes(((a * 0x3B) ^ (a >> 7)) & 0xFF for a in range(0x3800))
        s.bram5(0, data[:0x1800]).bram5(0x2000, data[0x2000:0x3800] if not radastan else data[0x2000:0x3800])
        s.nr(0x15, 0x80).nr(0x6A, 0x20 | 0x05 if radastan else 0x03)
        return s

    def test_lores(self):
        self.assertFrameMatches(self.lores_scene())

    def test_lores_scroll_and_clip(self):
        s = self.lores_scene().nr(0x32, 37).nr(0x33, 150).nr(0x1C, 0x04).nr(0x1A, 20, 200, 30, 170)
        self.assertFrameMatches(s)

    def test_radastan(self):
        self.assertFrameMatches(self.lores_scene(radastan=True))


def tm_scene(control=0x80, seed=31, ula_seed=1):
    """The tilemap over the ULA scene: map in bank 5 at +0x2000 (NR 0x6E = 0x20), tile definitions in bank 7
    (NR 0x6F = 0x80), so the ULA's screen stays the known picture beneath. Map entries cover every attribute
    (palette offsets, mirrors, rotation, the ULA-over bit); definitions encode their own address, and some
    nibbles are the transparent index F, so the ULA shows through."""
    s = ula_scene(ula_seed)
    write_palette(s, 0b011, unique_palette(seed))           # tilemap first palette (zxnext:6859-6864)
    defs = bytes(((a * 0x5B) ^ (a >> 5) ^ (a >> 9)) & 0xFF for a in range(8192))
    s.bram7(0, defs)
    cols = 80 if control & 0x40 else 40
    entries = 32 * cols
    if control & 0x20:                                      # strip flags: one byte per entry
        m = bytes((i * 7 + 3) & 0xFF for i in range(entries))
    else:
        m = bytes(b for i in range(entries) for b in ((i * 7 + 3) & 0xFF, (i * 13 + 5) & 0xFF))
    s.bram5(0x2000, m)
    s.nr(0x6E, 0x20).nr(0x6F, 0x80).nr(0x6B, control)
    return s


@needs_next
class Tilemap(VideoCase):
    """tilemap.vhd and its place in the mixer (zxnext:7016-7085)."""

    def test_40x32(self):
        self.assertFrameMatches(tm_scene(0x80))

    def test_80x32(self):
        self.assertFrameMatches(tm_scene(0xC0))

    def test_strip_flags_with_default_attribute(self):
        self.assertFrameMatches(tm_scene(0xA0).nr(0x6C, 0x56))

    def test_512_tiles(self):
        self.assertFrameMatches(tm_scene(0x82))

    def test_text_mode(self):
        self.assertFrameMatches(tm_scene(0x88))

    def test_always_on_top(self):
        self.assertFrameMatches(tm_scene(0x81))

    def test_second_tilemap_palette(self):
        s = tm_scene(0x90)
        write_palette(s, 0b111, unique_palette(37))
        self.assertFrameMatches(s)

    def test_scroll_and_clip(self):
        s = tm_scene(0x80).nr(0x2F, 0x01).nr(0x30, 0x17).nr(0x31, 201)
        s.nr(0x1C, 0x08).nr(0x1B, 6, 141, 11, 243)
        self.assertFrameMatches(s)

    def test_transparent_index(self):
        self.assertFrameMatches(tm_scene(0x80).nr(0x4C, 0x03))

    def test_stencil(self):
        self.assertFrameMatches(tm_scene(0x80).nr(0x68, 0x01))

    def test_blends_with_the_tilemap(self):
        for order in (6, 7):
            for blend in (0, 2, 3):
                with self.subTest(order=order, blend=blend):
                    s = tm_scene(0x80)
                    s.ops += l2_scene(0).ops[len(ula_scene(1).ops):]     # Layer 2 over the same ULA
                    s.nr(0x15, order << 2).nr(0x68, blend << 5)
                    self.assertFrameMatches(s, name=f'tm_blend_{order}_{blend}')


def sprite_scene(nr15=0x01, sprites=None, four_bit=False, seed=41, ula_seed=1):
    """Sprites over the ULA scene. Patterns encode their own address (a few bytes are the transparent E3,
    or nibble 3 in 4-bit); the sprite palette is unique. sprites: list of 4- or 5-byte attribute lists,
    written through port 0x57 from sprite 0 (sprites.vhd:637-745)."""
    s = ula_scene(ula_seed)
    write_palette(s, 0b010, unique_palette(seed))           # sprite first palette (zxnext:6859-6860, 6918)
    s.io(0x303B, 0x00)
    for a in range(16384):
        b = ((a * 0x4D) ^ (a >> 6) ^ (a >> 11)) & 0xFF
        if not four_bit and a % 37 == 5:
            b = 0xE3
        s.io(0x5B, b)
    s.io(0x303B, 0x00)
    for attrs in sprites or []:
        for b in attrs:
            s.io(0x57, b)
    s.nr(0x15, nr15)
    return s


def mixed_sprites():
    """Sixteen sprites: every mirror/rotate combination, palette offsets, overlaps, one across the left
    border, one wrapping past x 511, one partly below line 224."""
    out = []
    for i in range(16):
        x, y = 20 + (i % 8) * 34, 30 + (i // 8) * 70 + (i % 3) * 5
        a2 = ((i * 3) & 0xF0) | ((i & 7) << 1) | (x >> 8)
        out.append([x & 0xFF, y, a2, 0x80 | (i * 5 & 0x3F)])
    out.append([4, 100, 0x00, 0x80 | 7])                       # across the left border
    out.append([500 & 0xFF, 120, 0x01, 0x80 | 9])              # x 500: wraps to 0-3
    out.append([140, 216, 0x20, 0x80 | 11])                    # crosses line 224
    out.append([150, 60, 0x40, 0x80 | 12])                     # overlaps sprite 4
    return out


@needs_next
class Sprites(VideoCase):
    """sprites.vhd: attributes, patterns, order, scaling, relatives, clip and the border (zxnext:7025-7192)."""

    def test_mixed_sprites(self):
        self.assertFrameMatches(sprite_scene(0x01, mixed_sprites()))

    def test_sprite_zero_on_top(self):
        self.assertFrameMatches(sprite_scene(0x41, mixed_sprites()))

    def test_over_the_border(self):
        for nr15 in (0x03, 0x23):                              # over border, with and without border clip
            with self.subTest(nr15=nr15):
                s = sprite_scene(nr15, mixed_sprites()).nr(0x1C, 0x02).nr(0x19, 4, 150, 3, 240)
                self.assertFrameMatches(s, name=f'sprites_border_{nr15:02x}')

    def test_clip_window(self):
        s = sprite_scene(0x01, mixed_sprites()).nr(0x1C, 0x02).nr(0x19, 30, 200, 20, 170)
        self.assertFrameMatches(s)

    def test_four_bit_and_scaling(self):
        spr = []
        for i in range(12):
            x, y = 10 + (i % 6) * 48, 20 + (i // 6) * 90
            a4 = 0x80 | ((i & 1) << 6) | ((i % 4) << 3) | (((i // 2) % 4) << 1)
            spr.append([x, y, ((i * 0x30) & 0xF0) | ((i & 3) << 2), 0xC0 | (i * 3 & 0x3F), a4])
        self.assertFrameMatches(sprite_scene(0x03, spr, four_bit=True).nr(0x4B, 0x03))

    def test_relative_sprites(self):
        spr = [[60, 40, 0x10, 0xC0 | 2, 0x00],                 # composite anchor (5 bytes, bit 5 = 0)
               [16, 0, 0x01, 0xC0 | 3, 0x40], [0, 16, 0x08, 0xC0 | 4, 0x41], [240, 240, 0x00, 0xC0 | 5, 0x40],
               [150, 90, 0x26, 0xC0 | 6, 0x2A],                # unified anchor: rotate, mirror, 2x scale
               [16, 0, 0x01, 0xC0 | 7, 0x40], [0, 16, 0x04, 0xC0 | 8, 0x41], [16, 16, 0x02, 0x80 | 9, 0x40]]
        self.assertFrameMatches(sprite_scene(0x03, spr))

    def test_border_exception_in_u_over_s(self):
        for order in (3, 4, 5):
            with self.subTest(order=order):
                s = sprite_scene(0x03 | (order << 2), mixed_sprites())
                self.assertFrameMatches(s, name=f'sprites_border_order_{order}')


if __name__ == '__main__':
    unittest.main()
