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

    def __init__(self, palette='zero', timing='p3'):
        self.palette = palette
        self.timing = timing
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
        v = nv.Video(palette=self.palette, timing=self.timing)
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
        if self.timing != 'p3':
            kw['timing'] = self.timing
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

    def test_sprite_budget_by_hand(self):
        """The cycle counts written in budget_cut_slots and budget_boundary_slots, against the model."""
        def last_x(slots, timing, idx):
            v = budget_scene(slots, timing).model()
            owners = [None] * 320
            nv._sprite_line(v, 100, owners)
            return max(x for x in range(320) if owners[x] == idx)
        self.assertEqual(last_x(budget_cut_slots(), 'p3', 77), 172 + 40)
        self.assertEqual(last_x(budget_cut_slots(), '48k', 77), 172 + 8)
        for d, over, last in ((0, 0, 319), (1, 1, 319), (2, 1, 318)):
            v = budget_scene(budget_boundary_slots(d)).model()
            self.assertEqual(nv._sprite_line(v, 100)[1], over, f'd={d}')
            self.assertEqual(last_x(budget_boundary_slots(d), 'p3', 127), last, f'd={d}')

    def test_sprite_scenes_can_see_what_they_test(self):
        """Each sprite-survivor scene against the same scene with its behaviour taken away: the pictures
        must differ, or the scene is testing nothing (mixed_sprites once had no overlaps at all)."""
        def pic(s):
            return nv.frame9_np(s.model())[2]
        self.assertNotEqual(pic(sprite_scene(0x01, cluster_sprites())), pic(sprite_scene(0x41, cluster_sprites())))
        self.assertNotEqual(pic(sprite_scene(0x01, mixed_sprites())), pic(sprite_scene(0x41, mixed_sprites())))
        a = sprite_scene(0x03, four_bit_sprites(), four_bit=True)
        self.assertNotEqual(pic(a), pic(sprite_scene(0x03, four_bit_sprites(), four_bit=True).nr(0x4B, 0x5A)))
        b = sprite_scene(0x01, mixed_sprites())
        write_palette(b, 0b110, unique_palette(77))
        first = pic(b)
        self.assertNotEqual(first, pic(b.nr(0x43, 0x08)), 'the second sprite palette shows')
        c = sprite_scene(0x01, [[120, 100, 0x00, 0x80 | 5], [160, 100, 0x0A, 0x80 | 5]])
        before = pic(c)
        c.io(0x303B, 0x80 | 5)
        for i in range(128):
            c.io(0x5B, (i * 0x3B + 0x11) & 0xFF)
        self.assertNotEqual(before, pic(c), 'the second-half upload is on screen')
        orders = set()
        for order in range(8):
            orders.add(tuple(pic(sprites_l2_scene(order))))
        self.assertEqual(len(orders), 8, 'each layer order draws differently')

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
            for blend in (0, 1, 2, 3):
                with self.subTest(order=order, blend=blend):
                    s = l2_scene(0).nr(0x15, order << 2).nr(0x68, blend << 5)
                    self.assertFrameMatches(s, name=f'blend_{order}_{blend}')

    def test_ula_off_still_blends(self):
        for order in (6, 7):                          # blend 00 takes ula_mix, which ignores NR 0x68 b7;
            for nr68 in (0x80, 0xC0):                 # blend 10 takes ula_final, which doesn't (zxnext:7007-7010,
                with self.subTest(order=order, nr68=nr68):                                  # 7049-7058)
                    s = l2_scene(0).nr(0x15, order << 2).nr(0x68, nr68).nr(0x4A, 0x31)
                    self.assertFrameMatches(s, name=f'ula_off_blend_{order}_{nr68:02x}')

    def test_256x192_y_scroll_past_192(self):
        for sy in (200, 255):                         # y = vc + scroll - 192 once, so rows 192-254 of the
            with self.subTest(sy=sy):                 # bank range show at the bottom (layer2:156-158)
                s = l2_scene(0)
                s.sram(nv.L2_SRAM_BASE + 11 * 0x4000, bytes(((a * 0x61) ^ (a >> 7)) & 0xFF for a in range(0x4000)))
                self.assertFrameMatches(s.nr(0x17, sy), name=f'l2_scroll_y_{sy}')

    def test_resolution_11_is_640(self):
        self.assertFrameMatches(l2_scene(3).nr(0x70, 0x35))   # layer2:145, 202 (bit 5 alone decides)



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

    def test_radastan_under_ula_plus(self):
        s = self.lores_scene(radastan=True).io(0xBF3B, 0x40).io(0xFF3B, 0x01)
        for i in range(64):
            s.io(0xBF3B, i).io(0xFF3B, (i * 0x47 + 3) & 0xFF)
        self.assertFrameMatches(s)                    # 192 + offset(1:0) x 16 + nibble (lores:107; zxnext:4187)


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

    def test_text_mode_transparency_is_by_colour(self):
        pal = unique_palette(31)                      # NR 0x4C is ignored in text mode; NR 0x14 matches the
        for idx in (0x43, 0x86):                      # colour (zxnext:7016; tilemap:385-429)
            with self.subTest(idx=idx):
                s = tm_scene(0x88).nr(0x4C, 0x03).nr(0x14, pal[idx] >> 1)
                self.assertFrameMatches(s, name=f'tm_text_trans_{idx:02x}')

    def test_stencil(self):
        self.assertFrameMatches(tm_scene(0x80).nr(0x68, 0x01))

    def test_blends_with_the_tilemap(self):
        for order in (6, 7):
            for blend in (0, 1, 2, 3):
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


def four_bit_sprites():
    """Twelve 4-bit sprites: both halves (N6), every scale in x and y, palette offsets, y mirror."""
    spr = []
    for i in range(12):
        x, y = 10 + (i % 6) * 48, 20 + (i // 6) * 90
        a4 = 0x80 | ((i & 1) << 6) | ((i % 4) << 3) | (((i // 2) % 4) << 1)
        spr.append([x, y, ((i * 0x30) & 0xF0) | ((i & 3) << 2), 0xC0 | (i * 3 & 0x3F), a4])
    return spr


def cluster_sprites():
    """Twelve sprites piled 6 px apart, every mirror/rotate, so most pixels have several writers."""
    return [[100 + (i % 4) * 6, 80 + (i // 4) * 6, ((i * 0x50) & 0xF0) | ((i & 7) << 1), 0x80 | (i * 7 & 0x3F)]
            for i in range(12)]


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
    out.append([150, 40, 0x40, 0x80 | 12])                     # overlaps sprite 4 (156, 35)
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
        self.assertFrameMatches(sprite_scene(0x03, four_bit_sprites(), four_bit=True).nr(0x4B, 0x03))

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


def budget_scene(slots, timing='p3'):
    """sprite_scene with all 128 slots written (the unlisted ones invisible), so every slot's cost is known;
    sprites over the border with no clip (NR 0x15 = 03h), so whc 0-319 all show."""
    s = sprite_scene(0x03, list(slots) + [[0, 0, 0x00, 0x00]] * (128 - len(slots)))
    s.timing = timing
    return s


def budget_cut_slots():
    """Forty sprites on the row but off the right (x 330: S_QUALIFY and one S_PROCESS cycle each, sprites:855),
    24 invisible (S_QUALIFY only), then sixteen 8x-wide overlapping sprites, a palette step each: the line's
    time runs out in the fourteenth (cycle 2 + 80 + 24, then 129 each: sprite 77 gets 41 of its 128 cycles
    on 128K/+3 timing, 9 on 48K)."""
    out = [[330 & 0xFF, 100, 0x01, 0x80 | i] for i in range(40)]
    out += [[40, 100, 0x00, i] for i in range(24)]
    out += [[16 + 12 * i, 100, i << 4, 0xC0 | (20 + i), 0x18] for i in range(16)]
    return out


def budget_boundary_slots(d):
    """114 invisible slots (cycles 2-115), thirteen full 8x sprites (129 each), and in slot 127 one at
    x 290 - d running to whc 319 (30 + d cycles): its last pixel is cycle 1823 + d and the machine idles at
    1824 + d. d = 0 fits exactly; d = 1 is overtime though that pixel, in cycle 1824 itself, still lands;
    d = 2 loses it (sprites:470-501, 531-537, 977). The drawn sprites must come last: invisible slots after
    them would spend the time in S_QUALIFY instead."""
    out = [[0, 0, 0x00, 0x00]] * 114
    out += [[8 + 14 * i, 100, i << 4, 0xC0 | (30 + i), 0x18] for i in range(13)]
    out.append([(290 - d) & 0xFF, 100, 0xF1, 0xC0 | 50, 0x18])
    return out


@needs_next
class SpriteBudget(VideoCase):
    """The renderer's time: one line of 28 MHz cycles from line reset to line reset (4 x 456 on 128K/+3
    timing, 4 x 448 on 48K and Pentagon); one cycle per sprite qualified and one per pixel processed; what
    doesn't fit is never drawn, and port 0x303B bit 1 says so (sprites:517-537, 826-866, 951-995)."""

    def test_line_runs_out_mid_sprite(self):
        for timing in ('p3', '48k'):
            with self.subTest(timing=timing):
                self.assertFrameMatches(budget_scene(budget_cut_slots(), timing), name=f'budget_cut_{timing}')

    def test_the_boundary_to_the_cycle(self):
        for d in (0, 1, 2):
            with self.subTest(d=d):
                self.assertFrameMatches(budget_scene(budget_boundary_slots(d)), name=f'budget_boundary_{d}')

    def test_status_says_overtime_and_clears_on_read(self):
        for d, want in ((0, 0x01), (1, 0x03), (2, 0x03)):
            with self.subTest(d=d):
                s = budget_scene(budget_boundary_slots(d))
                self.assertEqual(nv.sprite_status(s.model()), want)
                zx = s.machine()
                self.assertEqual(zx.io_in(0x303B), want, 'sprites:977, 990-991')
                self.assertEqual(zx.io_in(0x303B), 0x00, 'sprites:986-988: a read clears it')


def sprites_l2_scene(order):
    """Sprites, Layer 2 (with its band of transparent E3) and the ULA, in layer order `order`. ULA paper 4
    is the transparent colour too, or with the ULA on top the order beneath it would never show."""
    s = sprite_scene(0x01, cluster_sprites() + mixed_sprites())
    s.ops += l2_scene(0).ops[len(ula_scene(1).ops):]
    write_palette(s, 0b000, [nv.rgb9_from8(0xE3)], start=16 + 4)
    return s.nr(0x15, 0x01 | (order << 2))


@needs_next
class SpriteSurvivors(VideoCase):
    """Behaviours Speccy-Zone's sprite mutants showed the suite missing (10 real of 24 on 64d9b75), as scenes.
    Her #5 (overlap sets status bit 0) and #10 (a read clears it) are in SpriteBudget and test_collision_flag;
    her #11 (9-bit Y wrap) is an equivalent mutant."""

    def test_four_byte_sprite_is_an_anchor_despite_a_stale_fifth_byte(self):
        s = sprite_scene(0x01, [[200, 150, 0x00, 0xC0 | 2, 0x40], [100, 100, 0x00, 0xC0 | 3, 0x00]])
        s.io(0x303B, 0x00)                                  # sprite 0 again, four bytes: byte 4 keeps 40h
        for b in (100, 80, 0x00, 0x80 | 5):                 # (sprites:639-664), and bit 6 = 0 makes it an
            s.io(0x57, b)                                   # anchor anyway (sprites:756)
        self.assertFrameMatches(s)

    def test_relatives_hide_with_their_anchor(self):
        spr = [[60, 40, 0x00, 0x40 | 2, 0x00],              # an anchor, invisible
               [16, 0, 0x00, 0xC0 | 3, 0x40], [0, 16, 0x00, 0xC0 | 4, 0x40],   # visible relatives: hidden too
               [150, 40, 0x00, 0xC0 | 5, 0x00],             # a visible anchor (sprites:784, 932)
               [16, 0, 0x00, 0xC0 | 6, 0x40], [0, 16, 0x00, 0x40 | 7, 0x40]]
        self.assertFrameMatches(sprite_scene(0x01, spr))

    def test_four_bit_relative_takes_its_half_from_the_added_pattern(self):
        spr = [[80, 60, 0x10, 0xC0 | 9, 0xC0],              # 4-bit anchor, N6 = 1: pattern 19
               [16, 0, 0x00, 0xC0 | 4, 0x41],               # own N6 0, + anchor: 8 + 19 = 27, odd half
               [0, 16, 0x00, 0xC0 | 5, 0x61],               # own N6 1: 11 + 19 = 30, even half
               [16, 16, 0x00, 0xC0 | 6, 0x40]]              # no pattern add: its own 12
        self.assertFrameMatches(sprite_scene(0x01, spr, four_bit=True))   # sprites:803, 928, 962-963

    def test_four_bit_transparency_is_the_low_nibble(self):
        for nr4b in (0xE3, 0x5A):                           # nibble 3, nibble A (sprites:971)
            with self.subTest(nr4b=nr4b):
                s = sprite_scene(0x03, four_bit_sprites(), four_bit=True).nr(0x4B, nr4b)
                self.assertFrameMatches(s, name=f'sprites_4bit_trans_{nr4b:02x}')

    def test_zero_on_top_where_sprites_really_overlap(self):
        for nr15 in (0x01, 0x41):                           # sprites:972
            with self.subTest(nr15=nr15):
                self.assertFrameMatches(sprite_scene(nr15, cluster_sprites()), name=f'sprites_cluster_{nr15:02x}')

    def test_second_sprite_palette(self):
        s = sprite_scene(0x01, mixed_sprites())
        write_palette(s, 0b110, unique_palette(77))
        s.nr(0x43, 0x08)                                    # NR 0x43 bit 3 (zxnext:5329, 6735)
        self.assertFrameMatches(s)

    def test_sprites_and_layer2_in_every_order(self):
        for order in range(8):                              # zxnext:7123-7192 and on
            with self.subTest(order=order):
                self.assertFrameMatches(sprites_l2_scene(order), name=f'sprites_l2_order_{order}')

    def test_pattern_upload_into_the_second_half(self):
        s = sprite_scene(0x01, [[120, 100, 0x00, 0x80 | 5], [160, 100, 0x0A, 0x80 | 5]])
        s.io(0x303B, 0x80 | 5)                              # pattern 5 from byte 128 (sprites:736)
        for i in range(128):
            b = (i * 0x3B + 0x11) & 0xFF
            s.io(0x5B, 0x00 if b == 0xE3 else b)
        self.assertFrameMatches(s)

    def test_sprites_in_the_blend_modes(self):
        for tm in (False, True):                            # the blend layer's partner sits above or below
            for order in (6, 7):                            # sprites by tm_pixel_below (zxnext:7046-7085,
                for blend in (1, 2, 3):                     # 7193-7258)
                    with self.subTest(tm=tm, order=order, blend=blend):
                        s = sprites_l2_scene(order)
                        if tm:
                            s.ops += tm_scene(0x80).ops[len(ula_scene(1).ops):]
                        s.nr(0x68, blend << 5)
                        self.assertFrameMatches(s, name=f'sprites_blend_{int(tm)}_{order}_{blend}')

    def test_flags_ignore_display(self):
        pair = [[100, 100, 0, 0x80 | 2], [108, 104, 0, 0x80 | 3]]
        for nr15, clip in ((0x00, None), (0x01, (100, 120, 10, 20)), (0x23, (0, 0, 0, 0))):
            with self.subTest(nr15=nr15, clip=clip):       # sprites off, or clipped away: the flags still
                s = sprite_scene(nr15, pair)                # come from the line store (sprites:842, 971-991)
                if clip:
                    s.nr(0x1C, 0x02).nr(0x19, *clip)
                self.assertEqual(nv.sprite_status(s.model()), 0x01)
                self.assertEqual(s.machine().io_in(0x303B), 0x01, 'sprites:991, whatever is shown')

    def test_collision_flag(self):
        for spr, want in (([[100, 100, 0, 0x80 | 2], [108, 104, 0, 0x80 | 3]], 0x01),
                          ([[100, 100, 0, 0x80 | 2], [140, 104, 0, 0x80 | 3]], 0x00)):
            with self.subTest(want=want):
                s = sprite_scene(0x01, spr)
                self.assertEqual(nv.sprite_status(s.model()), want)
                zx = s.machine()
                self.assertEqual(zx.io_in(0x303B), want, 'sprites:991')
                self.assertEqual(zx.io_in(0x303B), 0x00, 'sprites:986-988')


@needs_next
class Registers(VideoCase):
    """What port 0x253B reads back for the video registers (zxnext:5836-6024)."""

    REGS = (0x12, 0x14, 0x15, 0x16, 0x17, 0x26, 0x27, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x42, 0x4A, 0x4B, 0x4C,
            0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6E, 0x6F, 0x70, 0x71)

    def test_video_register_readbacks(self):
        for pat in (0xFF, 0xA5, 0x5A, 0x00):
            with self.subTest(pat=pat):
                s = ula_scene(1)
                for n in self.REGS:
                    s.nr(n, pat)
                s.nr(0x43, pat & 0x7F).nr(0x44, pat)  # NR 0x28 keeps NR 0x44's first byte
                s.nr(0x18, pat).nr(0x19, pat, pat ^ 0x0F).nr(0x1A, pat, 1, 2).nr(0x1C, 0x02)
                s.nr(0x1B, pat ^ 0x33)
                v, zx = s.model(), s.machine(frames=1)
                bad = {f'{n:02X}': (f'{zx.nr_read(n):02X}', f'{v.nr_read(n):02X}')
                       for n in self.REGS + (0x28, 0x43, 0x18, 0x19, 0x1A, 0x1B, 0x1C) if zx.nr_read(n) != v.nr_read(n)}
                self.assertEqual(bad, {}, f'NR: (got, want) after writing {pat:02X}')


def upload_half(s, start, salt):
    """128 pattern bytes through port 0x5B from wherever its pointer is (none the transparent E3)."""
    for i in range(128):
        b = (i * 0x3B + salt) & 0xFF
        s.io(0x5B, 0x00 if b == 0xE3 else b)
    return s


@needs_next
class SpriteMirror(VideoCase):
    """The nextreg route to the sprites: NR 0x34 picks the mirror's sprite, NR 0x35-0x39 write its bytes,
    NR 0x75-0x79 write and then step; NR 0x09 b4 ties the mirror to the ports (zxnext:4794-4855, 5126,
    5939; sprites:594-745)."""

    def check(self, s):
        v, zx = s.model(), s.machine()
        self.assertEqual(zx.nr_read(0x34), v.nr_read(0x34), 'NR 0x34 (zxnext:5939-5940)')
        self.assertFrameMatches(s)

    def test_nextreg_writes_and_steps(self):
        s = sprite_scene(0x01, [[20 + 24 * i, 150, 0x00, 0x00 | i] for i in range(24)])   # invisible ones
        s.nr(0x34, 30).nr(0x35, 60).nr(0x36, 50).nr(0x37, 0x24).nr(0x38, 0xC0 | 3).nr(0x79, 0x0A)   # 30, steps
        s.nr(0x35, 100).nr(0x36, 50).nr(0x37, 0x30).nr(0x78, 0x80 | 4)                               # 31, steps
        s.nr(0x35, 140).nr(0x36, 52).nr(0x37, 0x4E).nr(0x38, 0x80 | 7)                               # 32, stays
        s.nr(0x34, 8)
        for i in range(8):                                  # make 8-15 visible, a step each
            s.nr(0x78, 0x80 | (9 + i))
        self.check(s)

    def test_lockstep_moves_the_ports(self):
        s = sprite_scene(0x01, []).nr(0x09, 0x10)
        s.nr(0x34, 0x80 | 5)                                # sprite 5, pattern 5's second half
        for b in (90, 70, 0x00, 0x80 | 5):
            s.io(0x57, b)                                   # port 0x57 now writes sprite 5
        upload_half(s, 0, 0x29)                             # port 0x5B, pattern 5 from byte 128
        s.nr(0x34, 7).nr(0x75, 130).nr(0x35, 0)             # sprite 7's x, a step to 8 moves port 0x57 too
        for b in (200, 70, 0x10, 0x80 | 5):
            s.io(0x57, b)                                   # sprite 8 (the step reloaded the port's index)
        self.check(s)

    def test_port_advance_moves_the_mirror_but_not_the_pattern_pointer(self):
        s = sprite_scene(0x01, []).nr(0x09, 0x10)
        s.io(0x303B, 0x80 | 12)                             # mirror follows: sprite 12 (sprites:607-609)
        for b in (40, 90, 0x00, 0x80 | 12, 40, 110, 0x00, 0x80 | 13):
            s.io(0x57, b)                                   # sprites 12 and 13; the mirror is now 14
        upload_half(s, 0, 0x45)                             # still pattern 12's second half
        s.nr(0x37, 0x50).nr(0x38, 0x80 | 12).nr(0x36, 110).nr(0x35, 80)   # sprite 14 by nextreg
        self.check(s)

    def test_untied_nextreg_leaves_the_ports_alone(self):
        s = sprite_scene(0x01, [])
        s.io(0x303B, 20)
        s.nr(0x34, 0x80 | 3)                                # untied: ports stay at sprite 20, pattern 20
        for b in (60, 100, 0x00, 0x80 | 20):
            s.io(0x57, b)
        upload_half(s, 0, 0x17)
        s.nr(0x35, 160).nr(0x36, 100).nr(0x37, 0x00).nr(0x38, 0x80 | 3)   # sprite 3 by nextreg
        self.check(s)


def ulap_scene(seed=8):
    s = ula_scene(seed)
    s.io(0xBF3B, 0x40).io(0xFF3B, 0x01)                     # ULA+ on (zxnext:4489-4490)
    for i in range(64):
        s.io(0xBF3B, i).io(0xFF3B, (i * 0x47 + 3) & 0xFF)
    s.bram5(0x1800, bytes((i * 53) & 0xFF for i in range(768)))   # every CLUT; bit 7 set in half
    return s


@needs_next
class Survivors(VideoCase):
    """Behaviours Speccy-Zone's video mutants showed the suite missing (4 of 31), as scenes."""

    def test_ula_plus_in_hi_res_ink_takes_the_paper_half(self):
        s = ulap_scene()
        bm, _ = address_bitmap(23)
        s.bram5(0x2000, bm).io(0x00FF, 0x06 | (5 << 3))      # ula:535: bit 3 = hi-res OR paper
        self.assertFrameMatches(s)

    def test_no_flash_under_ula_plus(self):
        s = ulap_scene()
        want = nv.frame9_np(s.model())[2]
        for frames in (2, 18):                              # both FLASH phases (ula:470-481)
            with self.subTest(frames=frames):
                self.assertEqual(list(s.machine(frames).frame9()[2]), want, 'ula:470: no FLASH under ULA+')

    def test_tile_below_shows_through_transparent_ula(self):
        s = tm_scene(0x80)
        pal = unique_palette(1)
        for paper in (1, 4):                                # these papers become transparent
            s.nr(0x14, pal[16 + paper] >> 1)
        self.assertFrameMatches(s)                          # zxnext:7023: below, but the ULA is transparent

    def test_512_tiles_ninth_bit_on_top(self):
        s = tm_scene(0x83)                                  # 512 tiles, always on top
        defs = bytes(((a * 0x6B) ^ (a >> 8) ^ (a >> 4)) & 0xFF for a in range(0x2000))
        s.bram5(0x0000, defs)                               # definitions in bank 5 (16K: tiles 100h+ differ)
        s.nr(0x6F, 0x00)
        self.assertFrameMatches(s)


@needs_next
class ProbeV2(VideoCase):
    """P-V2's sprite card (next-build/probes/pv2_scene.py, the scene defined once): the machine against the
    model, the per-line strip cut where the line's time runs out (whc 152 on 128K/+3 timing)."""

    def test_pv2_sprite_card(self):
        probes = Path.home() / 'next-build/probes'
        if not (probes / 'pv2_scene.py').exists():
            self.skipTest('needs next-build/probes/pv2_scene.py')
        sys.path.insert(0, str(probes))
        import pv2_model as pm
        import pv2_scene as sc
        s = Scene()
        for kind, a, b in pm.writes():
            (s.nr if kind == 'nr' else s.io)(a, b)
        bm, at = pm.ula()
        s.bram5(0, bm).bram5(0x1800, at)
        s.sram(nv.L2_SRAM_BASE + pm.L2_BANK * 0x4000, pm.layer2())
        s.nr(0x62, 0x00).nr(0x61, 0x00)
        for w in sc.copper_words():
            s.nr(0x63, w >> 8, w & 0xFF)
        s.nr(0x62, 0xC0)
        zx = s.machine(frames=3)
        got = list(zx.frame9()[2])
        want = nv.frame9_np(s.model(), sc.schedule())[2]
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        if bad:
            path = self._save_diff('pv2_sprite_card', got, want, bad)
            self.fail(f'{len(bad)} samples differ, first at ({bad[0] % nv.W},{bad[0] // nv.W}); {path}')
        self.assertEqual(zx.io_in(0x303B), 0x03, 'the strip runs out of time and overlaps (sprites:977, 991)')


@needs_next
class ProbeV3(VideoCase):
    """P-V3's blend card (next-build/probes/pv3_scene.py, the scene defined once): the machine against the
    model, band by band, and the read-backs the probe prints (NR 0x28, NR 0x34, the card's sprite status)."""

    def test_pv3_blend_card(self):
        probes = Path.home() / 'next-build/probes'
        if not (probes / 'pv3_scene.py').exists():
            self.skipTest('needs next-build/probes/pv3_scene.py')
        sys.path.insert(0, str(probes))
        import pv3_model as pm
        import pv3_scene as sc
        s = Scene()
        for kind, a, b in pm.writes():
            (s.nr if kind == 'nr' else s.io)(a, b)
        bm, at = sc.ula()
        s.bram5(0, bm).bram5(0x1800, at)
        s.sram(nv.L2_SRAM_BASE + sc.L2_BANK * 0x4000, sc.layer2())
        s.nr(0x62, 0x00).nr(0x61, 0x00)
        for w in sc.copper_words():
            s.nr(0x63, w >> 8, w & 0xFF)
        s.nr(0x62, 0xC0)
        zx, v = s.machine(frames=3), s.model()
        got = list(zx.frame9()[2])
        want = nv.frame9_np(v, sc.schedule())[2]
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        if bad:
            path = self._save_diff('pv3_blend_card', got, want, bad)
            self.fail(f'{len(bad)} samples differ, first at ({bad[0] % nv.W},{bad[0] // nv.W}); {path}')
        self.assertEqual((zx.nr_read(0x28), zx.nr_read(0x34), zx.io_in(0x303B)),
                         (v.nr_read(0x28), v.nr_read(0x34), nv.sprite_status(v)), 'NR 0x28, NR 0x34, status')


if __name__ == '__main__':
    unittest.main()
