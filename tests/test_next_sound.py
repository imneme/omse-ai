"""The Next's sound: three AY/YM chips as ym2149.vhd makes them, TurboSound's selection, panning and stereo modes
(turbosound.vhd), the four DACs (soundrive.vhd), the beeper and the mixer (audio_mixer.vhd), wired as zxnext.vhd
wires them (6284-6430), core 3.02.02. Slide Fern, 6 Nov 2026.

The chips tick on a 1.75 MHz enable (every 16th 28 MHz edge, zxnext_top:1161-1180). The machine can hand back the
mixer's output at every one of those ticks (13 bits a side, 0-5998); YM2149 below is an independent model of one
chip, written from ym2149.vhd, that the per-tick output is checked against. At power-on the DACs are off and held
at 0x80 (soundrive:56-64, zxnext:6343), which puts a constant 4 * (0x80 + 0x80) = 1024 into each side.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import needs_next, NextCase, bare  # noqa: E402
from test_next_memory import out  # noqa: E402

AY_VOL = [0x00, 0x03, 0x04, 0x06, 0x0a, 0x0f, 0x15, 0x22, 0x28, 0x41, 0x5b, 0x72, 0x90, 0xb5, 0xd7, 0xff]
YM_VOL = [0x00, 0x01, 0x01, 0x02, 0x02, 0x03, 0x03, 0x04, 0x06, 0x07, 0x09, 0x0a, 0x0c, 0x0e, 0x11, 0x13,
          0x17, 0x1b, 0x20, 0x25, 0x2c, 0x35, 0x3e, 0x47, 0x54, 0x66, 0x77, 0x88, 0xa1, 0xc0, 0xe0, 0xff]
DAC_IDLE = 1024


class YM2149:
    """One chip, an ENA tick at a time, as ym2149.vhd has it (I_SEL_L = 1: an 8-tick divider)."""

    def __init__(self, ay=False):
        self.r = [0] * 16
        self.r[7] = 0xFF
        self.ay = ay
        self.div = 0
        self.ndiv = 0
        self.tcnt = [0, 0, 0]
        self.top = [0, 0, 0]
        self.ncnt = 0
        self.poly = 0
        self.ecnt = 0
        self.eena = 0
        self.evol = 0
        self.einc = 0
        self.ehold = 0
        self.lev = [0, 0, 0]

    def write(self, a, v):
        self.r[a] = v
        if a == 13:                                       # env_reset (ym2149:205-207, 335-337, 361-368)
            self.ecnt, self.eena = 0, 1
            self.evol, self.einc = (31, 0) if not (v & 4) else (0, 1)
            self.ehold = 0

    def tick(self):
        ena_div = ena_noise = 0
        if self.div == 0:                                 # (ym2149:258-275)
            self.div = 7
            ena_div = 1
            if self.ndiv:
                ena_noise = 1
            self.ndiv ^= 1
        else:
            self.div -= 1
        r = self.r
        if ena_noise:                                     # (ym2149:277-295)
            comp = (r[6] & 0x1F) - 1 if (r[6] & 0x1E) else 0
            if self.ncnt >= comp:
                self.ncnt = 0
                p = self.poly
                fb = (p & 1) ^ ((p >> 2) & 1) ^ (1 if p == 0 else 0)
                self.poly = (fb << 16) | (p >> 1)
            else:
                self.ncnt += 1
        if ena_div:                                       # (ym2149:299-322)
            for i in range(3):
                f = ((r[2 * i + 1] & 15) << 8) | r[2 * i]
                comp = f - 1 if (f >> 1) else 0
                if self.tcnt[i] >= comp:
                    self.tcnt[i] = 0
                    self.top[i] ^= 1
                else:
                    self.tcnt[i] += 1
        # the envelope step uses env_ena as it stood before this tick's period counter (registered signals)
        eena = self.eena
        if ena_div:                                       # (ym2149:324-350)
            f = (r[12] << 8) | r[11]
            comp = f - 1 if (f >> 1) else 0
            if self.ecnt >= comp:
                self.ecnt, self.eena = 0, 1
            else:
                self.ecnt, self.eena = self.ecnt + 1, 0
        else:
            self.eena = 0
        if eena:                                          # (ym2149:359-437)
            v = self.evol
            bot, bot1, top1, top = v == 0, v == 1, v == 30, v == 31
            if not self.ehold:
                self.evol = (v + (1 if self.einc else -1)) & 31
            s = r[13]
            if not (s & 8):
                if (not self.einc and bot1) or (self.einc and top):
                    self.ehold = 1
            elif s & 1:
                if not self.einc:
                    if (s & 2 and bot) or (not s & 2 and bot1):
                        self.ehold = 1
                elif (s & 2 and top) or (not s & 2 and top1):
                    self.ehold = 1
            elif s & 2:
                if not self.einc:
                    if bot1:
                        self.ehold = 1
                    if bot:
                        self.ehold, self.einc = 0, 1
                else:
                    if top1:
                        self.ehold = 1
                    if top:
                        self.ehold, self.einc = 0, 0
        noise = self.poly & 1                             # mix and level (ym2149:439-498)
        for i in range(3):
            mixed = ((r[7] >> i) & 1 or self.top[i]) and ((r[7] >> (3 + i)) & 1 or noise)
            v = r[8 + i]
            if not mixed:
                self.lev[i] = 0
            elif v & 0x10:
                self.lev[i] = self.evol
            else:
                self.lev[i] = 0 if not (v & 15) else ((v & 15) << 1) | 1

    def out(self):
        return [AY_VOL[l >> 1] if self.ay else YM_VOL[l] for l in self.lev]


def ay(zx, reg, v):
    zx.io_out(0xFFFD, reg)
    zx.io_out(0xBFFD, v)


def chip(zx, n, pan=3):
    """TurboSound's chip select (turbosound:80-92): 1 pp 111 cc, cc = 11 for chip 0, 10 for 1, 01 for 2."""
    zx.io_out(0xFFFD, 0x80 | (pan << 5) | 0x1C | (3, 2, 1)[n])


def capture(zx, ticks):
    """The mixer's output at each of the next `ticks` 1.75 MHz enables: an (n, 2) array of (L, R)."""
    zx.audio_capture(True)
    zx.run_ticks(16 * ticks)
    s = zx.audio_take()
    zx.audio_capture(False)
    return s


def aligned(got, want, slack=3):
    """True if got matches want exactly for some start offset 0..slack (a register write lands a tick or two
    before its first effect, depending on where in the 16-cycle enable period it falls)."""
    n = len(want)
    return any(np.array_equal(got[k:k + n], want) for k in range(slack + 1) if k + n <= len(got))


@needs_next
class Tone(NextCase):

    def setUp(self):
        self.zx = bare()
        self.zx.nr_write(0x06, self.zx.nr_read(0x06) | 1)  # AY mode (zxnext:6296, NR 0x06 b0)

    def test_half_period_is_eight_enables_a_step(self):
        zx = self.zx
        for p in (1, 2, 5, 0x123):
            ay(zx, 0, p & 0xFF)
            ay(zx, 1, p >> 8)
            ay(zx, 7, 0xFE)                                # tone A only
            ay(zx, 8, 15)
            s = capture(zx, 16 * max(p, 1) * 4)[:, 0] - DAC_IDLE
            self.assertEqual(set(np.unique(s)), {0, 0xFF}, f'A alone at volume 15 is 0 or 0xFF (period {p})')
            edges = np.nonzero(np.diff(s))[0]
            runs = np.diff(edges)
            self.assertTrue(len(runs) >= 3 and set(runs) == {8 * max(p, 1)},
                            f'period {p}: the output flips every {8 * max(p, 1)} enables (ym2149:305-320)')

    def test_periods_zero_and_one_are_the_same(self):
        zx = self.zx
        ay(zx, 7, 0xFE)
        ay(zx, 8, 15)
        ay(zx, 0, 0)
        a = np.diff(np.nonzero(np.diff(capture(zx, 64)[:, 0]))[0])
        ay(zx, 0, 1)
        b = np.diff(np.nonzero(np.diff(capture(zx, 64)[:, 0]))[0])
        self.assertTrue(set(a) == set(b) == {8}, 'comp = 0 when freq(11:1) = 0 (ym2149:302)')


@needs_next
class Levels(NextCase):

    def test_ay_volume_table(self):
        zx = bare()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        ay(zx, 7, 0xFF)                                    # everything off: mixed = 1, a steady level
        got = []
        for v in range(16):
            ay(zx, 8, v)
            got.append(int(capture(zx, 8)[-1, 0]) - DAC_IDLE)
        self.assertEqual(got, AY_VOL, 'volTableAy[level(4:1)] (ym2149:104-109, 528-531)')

    def test_ym_volume_table(self):
        zx = bare()                                        # YM mode at power-on (NR 0x06 b1:0 = 00)
        ay(zx, 7, 0xFF)
        got = []
        for v in range(16):
            ay(zx, 8, v)
            got.append(int(capture(zx, 8)[-1, 0]) - DAC_IDLE)
        self.assertEqual(got, [0] + [YM_VOL[(v << 1) | 1] for v in range(1, 16)],
                         'volTableYm[R(3:0) & 1], 0 for 0 (ym2149:111-117, 452-458, 524-526)')

    def test_abc_acb_and_mono(self):
        zx = bare()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        ay(zx, 7, 0xFF)
        ay(zx, 8, 15)
        ay(zx, 9, 12)
        ay(zx, 10, 9)
        a, b, c = AY_VOL[15], AY_VOL[12], AY_VOL[9]
        s = capture(zx, 8)[-1] - DAC_IDLE
        self.assertEqual(list(s), [a + b, c + b], 'ABC: L = A + B, R = C + B (turbosound:146-150)')
        zx.nr_write(0x08, zx.nr_read(0x08) | 0x20)
        s = capture(zx, 8)[-1] - DAC_IDLE
        self.assertEqual(list(s), [a + c, c + b], 'ACB (NR 0x08 b5): L = A + C, R = C + B')
        zx.nr_write(0x08, zx.nr_read(0x08) & ~0x20)
        zx.nr_write(0x09, zx.nr_read(0x09) | 0x20)         # chip 0's mono bit (nr_09_psg_mono)
        s = capture(zx, 8)[-1] - DAC_IDLE
        self.assertEqual(list(s), [a + b + c] * 2, 'mono: both sides A + B + C')


@needs_next
class Envelope(NextCase):

    def test_all_sixteen_shapes(self):
        for shape in range(16):
            zx = bare()                                    # YM mode: all 32 envelope steps show
            ay(zx, 7, 0xFF)
            ay(zx, 8, 0x10)
            ay(zx, 11, 3)
            ay(zx, 12, 0)
            m = YM2149()
            for a, v in ((7, 0xFF), (8, 0x10), (11, 3), (12, 0)):
                m.write(a, v)
            ay(zx, 13, shape)
            m.write(13, shape)
            n = 8 * 3 * 80
            got = capture(zx, n + 8)[:, 0] - DAC_IDLE
            want = []
            for _ in range(n):
                m.tick()
                want.append(m.out()[0])
            self.assertTrue(aligned(got, np.array(want)), f'shape {shape}: the envelope as ym2149:359-437 steps it')


    def test_shapes_as_the_datasheet_draws_them(self):
        """Independent of the model above (which is my reading of the VHDL): the sixteen shapes as every AY/YM
        datasheet draws them, as the envelope step at the end of the first and second cycles and the direction of
        travel in each. d = down, u = up; after the first cycle: 0 hold low, 1 hold high, or the second cycle's
        direction."""
        want = {0: ('d', 0), 1: ('d', 0), 2: ('d', 0), 3: ('d', 0), 4: ('u', 0), 5: ('u', 0), 6: ('u', 0),
                7: ('u', 0), 8: ('d', 'd'), 9: ('d', 0), 10: ('d', 'u'), 11: ('d', 1), 12: ('u', 'u'),
                13: ('u', 1), 14: ('u', 'd'), 15: ('u', 0)}
        for shape, (first, then) in want.items():
            zx = bare()
            ay(zx, 11, 1)
            ay(zx, 12, 0)
            ay(zx, 13, shape)
            steps = []
            for _ in range(70):                           # an envelope step every 8 enables at period 1
                zx.run_ticks(16 * 8)
                steps.append(zx.ay_env(0))
            a, b = steps[2:30], steps[36:62]              # inside the first and the second cycle
            go = lambda xs: 'u' if xs[-1] > xs[0] else 'd' if xs[-1] < xs[0] else ('1' if xs[0] == 31 else '0')
            self.assertEqual(go(a), first, f'shape {shape}: first cycle')
            got = go(b)
            self.assertEqual(got, str(then) if then in (0, 1) else then, f'shape {shape}: after the first cycle')


@needs_next
class Noise(NextCase):

    def test_lfsr_as_the_model(self):
        for period in (0, 1, 3, 31):
            zx = bare()
            m = YM2149()
            for a, v in ((6, period), (7, 0xF7), (8, 15)):  # noise on A only
                ay(zx, a, v)
                m.write(a, v)
            n = 16 * max(period, 1) * 60
            got = capture(zx, n + 8)[:, 0] - DAC_IDLE
            want = []
            for _ in range(n):
                m.tick()
                want.append(m.out()[0])
            self.assertTrue(aligned(got, np.array(want), slack=40),
                            f'noise period {period}: poly17, taps 0 and 2, the zero escape (ym2149:277-297)')


@needs_next
class TurboSound(NextCase):

    def test_select_and_pan(self):
        zx = bare()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        zx.nr_write(0x08, zx.nr_read(0x08) | 2)            # TurboSound on (NR 0x08 b1)
        for n in range(3):
            chip(zx, n)
            ay(zx, 7, 0xFF)
            ay(zx, 8, (15, 13, 11)[n])                     # A only, a different level on each chip
        s = capture(zx, 8)[-1] - DAC_IDLE
        tot = AY_VOL[15] + AY_VOL[13] + AY_VOL[11]
        self.assertEqual(list(s), [tot, 0], 'three chips sum into L (A is left in ABC) (turbosound:322-327)')
        chip(zx, 1, pan=1)                                 # chip 1 to the right only: its L is muted
        s = capture(zx, 8)[-1] - DAC_IDLE
        self.assertEqual(list(s), [tot - AY_VOL[13], 0], 'pan bit 1 is L (turbosound:316-321)')
        zx.nr_write(0x08, zx.nr_read(0x08) & ~2)           # TurboSound off: only the selected chip (1) sounds
        s = capture(zx, 8)[-1] - DAC_IDLE
        self.assertEqual(list(s), [0, 0], 'off: only the selected chip, and chip 1 is panned right (156-164)')


@needs_next
class Dacs(NextCase):

    def test_ports_and_nextregs(self):
        zx = bare()
        idle = capture(zx, 8)[-1]
        self.assertEqual(list(idle), [DAC_IDLE, DAC_IDLE], 'off: all four held at 0x80 (soundrive:56-64)')
        zx.nr_write(0x08, zx.nr_read(0x08) | 8)            # DACs on (NR 0x08 b3)
        zx.run_ticks(64)
        zx.io_out(0x00DF, 0x20)                            # SpecDrum: A and D (zxnext:2617, en23)
        s = capture(zx, 8)[-1]
        self.assertEqual(list(s), [4 * (0x20 + 0x80), 4 * (0x80 + 0x20)], 'DF writes A and D; L = A + B, R = C + D')
        zx.nr_write(0x2C, 0x10)                            # NR 0x2C: B (left)
        zx.nr_write(0x2E, 0xF0)                            # NR 0x2E: C (right)
        s = capture(zx, 8)[-1]
        self.assertEqual(list(s), [4 * (0x20 + 0x10), 4 * (0xF0 + 0x20)], 'NR 0x2C is B, 0x2E is C (soundrive:66-90)')


@needs_next
class Beeper(NextCase):

    def test_ear_and_the_speaker_exclusion(self):
        zx = bare()
        zx.io_out(0x00FE, 0x10)                            # EAR (port FE b4)
        s = capture(zx, 8)[-1]
        self.assertEqual(list(s), [DAC_IDLE + 512] * 2, 'ear adds 512 to each side (audio_mixer:54)')
        zx.nr_write(0x06, zx.nr_read(0x06) | 0x40)          # beep to the internal speaker only...
        zx.nr_write(0x08, zx.nr_read(0x08) | 0x10)          # ...when it's enabled (zxnext:6411)
        s = capture(zx, 8)[-1]
        self.assertEqual(list(s), [DAC_IDLE] * 2, 'exc: the beeper leaves the mix (audio_mixer:54-55)')


@needs_next
class Log(NextCase):

    def test_ay_log(self):
        zx = bare()
        code = [0x01, 0xFD, 0xFF, 0x3E, 0x08, 0xED, 0x79,  # LD BC,FFFD; LD A,8; OUT (C),A
                0x06, 0xBF, 0x3E, 0x0F, 0xED, 0x79,        # LD B,BF; LD A,15; OUT (C),A
                0x18, 0xFE]                                # JR $
        zx.load(0x8000, bytes(code))
        zx.set_regs(pc=0x8000, sp=0x7FF0)
        zx.io_log(True)                                    # the CPU's own I/O cycles (io_out isn't logged)
        t0 = zx.t28
        zx.run_ticks(4000)
        log = zx.ay_log()
        self.assertEqual([(p, v) for _, p, v in log], [(0xFFFD, 8), (0xBFFD, 15)], 'select then data, in order')
        self.assertTrue(t0 < log[0][0] < log[1][0], 'each with its t28')


@needs_next
class Resampled(NextCase):

    def test_audio_at_a_rate(self):
        zx = bare()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        ay(zx, 0, 0x7C)                                    # about 882 Hz: 1.75 MHz / (16 * 124)
        ay(zx, 7, 0xFE)
        ay(zx, 8, 15)
        zx.audio(48000)
        zx.run_ticks(28_000_000 // 10)                     # 0.1 s
        a = zx.audio(48000)
        self.assertTrue(4790 <= len(a) <= 4810, f'0.1 s at 48 kHz is about 4,800 frames, got {len(a)}')
        x = a[:, 0].astype(float) - a[:, 0].mean()
        f = np.argmax(np.abs(np.fft.rfft(x))) * 48000 / len(x)
        self.assertAlmostEqual(f, 1_750_000 / (16 * 124), delta=15, msg='the tone where the AY puts it')


if __name__ == '__main__':
    unittest.main()
