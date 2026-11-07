"""Native conditioned stream: the raw hardware contract is a separate path."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from next import Next
from zxaudio import BiasController


def machine():
    zx = Next(boot='bare', rtc=False)
    zx.load(0x8000, bytes([0xF3, 0x18, 0xFE]))
    zx.set_regs(pc=0x8000, sp=0x7FF0)
    return zx


def ay(zx, reg, value):
    zx.io_out(0xFFFD, reg); zx.io_out(0xBFFD, value)


class ConditionedStream(unittest.TestCase):
    def test_raw_matches_independent_resampling_of_mixer_capture(self):
        for rate, hdmi in [(r, h) for r in (44100, 48000, 96000) for h in (False, True)]:
            zx = machine()
            zx.audio_hdmi(hdmi)
            zx.nr_write(0x06, zx.nr_read(0x06) | 1)
            for reg, value in [(0, 124), (1, 0), (4, 91), (5, 0), (7, 0xFA), (8, 15), (10, 7)]:
                ay(zx, reg, value)
            zx.audio_capture(True)
            zx.audio(rate, raw=True); zx.run_ticks(280000)
            raw = zx.audio(rate, raw=True)
            capture = zx.audio_take()
            acc = count = left = right = 0
            expected = []
            for l, r in capture:
                left += int(l); right += int(r); count += 1; acc += rate
                if acc >= 1750000:
                    acc -= 1750000
                    expected.append([int(l) * 5, int(r) * 5] if hdmi else
                                    [left * 5 // count, right * 5 // count])
                    left = right = count = 0
            np.testing.assert_array_equal(raw, expected)

    def test_real_notes_pauses_match_reference_at_all_rates(self):
        for rate in (44100, 48000, 96000):
            for period in (124, 4095):
                raw_machine, conditioned = machine(), machine()
                for zx in (raw_machine, conditioned):
                    zx.nr_write(0x06, zx.nr_read(0x06) | 1)
                    for reg, value in [(0, period & 255), (1, period >> 8), (7, 0xFE), (8, 0)]:
                        ay(zx, reg, value)
                    zx.audio(rate)
                models = [BiasController(rate), BiasController(rate)]
                for ms, volume in [(100, 0), (300, 15), (10, 0), (300, 15), (50, 0),
                                   (300, 15), (250, 0), (300, 15), (2000, 0), (100, 1)]:
                    for zx in (raw_machine, conditioned):
                        ay(zx, 8, volume); zx.run_ticks(ms * 28000)
                    raw = raw_machine.audio(rate, raw=True)
                    got = conditioned.audio(rate)
                    want = np.column_stack([models[c].process(raw[:, c]) for c in (0, 1)])
                    want = np.clip(want, -32768, 32767).astype(np.int16)
                    self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)
                    self.assertTrue(np.all(got[:, 1] == 0), 'quiet right channel must not borrow left bias')
                    if ms == 2000:
                        self.assertTrue(np.all(got[-rate:] == 0))

    def test_raw_reads_do_not_reset_or_fork_conditioner(self):
        a, b = machine(), machine()
        for zx in (a, b):
            zx.nr_write(0x06, zx.nr_read(0x06) | 1)
            for reg, value in [(0, 124), (7, 0xFE), (8, 15)]:
                ay(zx, reg, value)
            zx.audio(48000)
        for i in range(5):
            for zx in (a, b):
                zx.run_ticks(280000)
            expected = a.audio()
            got = b.audio(raw=(i < 3))
            if i >= 3:
                np.testing.assert_array_equal(got, expected)
            self.assertEqual(len(b.audio(raw=True)), 0, 'both modes share the same read cursor')

    def test_chunking_does_not_change_actual_stream(self):
        def render(chunk):
            zx = machine()
            for reg, value in [(0, 124), (7, 0xFE), (8, 15)]:
                ay(zx, reg, value)
            zx.audio()
            parts = []
            remaining = 2800000
            while remaining:
                n = min(chunk, remaining)
                zx.run_ticks(n); remaining -= n
                parts.append(zx.audio())
            return np.concatenate(parts)
        np.testing.assert_array_equal(render(2800000), render(10007))

    def test_invalid_rate_and_configuration(self):
        zx = machine()
        for rate in (0, -1, 1750001, 1.5, True):
            with self.assertRaises(ValueError):
                zx.audio(rate)
        for ms in (0, -1, 60001, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                zx.audio_config(hold_ms=ms)

    def test_valid_config_and_rate_changes_preserve_old_queue(self):
        raw_zx, zx = machine(), machine()
        for m in (raw_zx, zx):
            for reg, value in [(0, 124), (7, 0xFE), (8, 15)]:
                ay(m, reg, value)
            m.audio(48000); m.run_ticks(2800000)
        def expected(raw, rate, **kw):
            return np.column_stack([BiasController(rate, **kw).process(raw[:, c]) for c in (0, 1)])
        zx.audio_config(hold_ms=1000)
        raw = raw_zx.audio(48000, raw=True)
        got = zx.audio(48000)
        want = expected(raw, 48000).astype(np.int16)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)
        for m in (raw_zx, zx):
            m.run_ticks(2800000)
        raw = raw_zx.audio(44100, raw=True)  # old 48k queue, new rate for future
        got = zx.audio(44100)
        want = expected(raw, 48000, hold_ms=1000).astype(np.int16)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)
        self.assertTrue(4790 < len(raw) <= 4800)
        for m in (raw_zx, zx):
            m.run_ticks(2800000)
        raw = raw_zx.audio(44100, raw=True)
        got = zx.audio(44100)
        want = expected(raw, 44100, hold_ms=1000).astype(np.int16)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)
        self.assertTrue(4400 < len(raw) <= 4410)

    def test_machine_reset_is_not_recording_restart(self):
        raw_zx, zx = machine(), machine()
        models = [BiasController(48000), BiasController(48000)]
        for m in (raw_zx, zx):
            for reg, value in [(0, 124), (7, 0xFE), (8, 15)]:
                ay(m, reg, value)
            m.audio(); m.run_ticks(2800000)
        raw = raw_zx.audio(raw=True)
        zx.audio()
        for c in (0, 1):
            models[c].process(raw[:, c])
        for m in (raw_zx, zx):
            m.lib.zxn_reset(m.z, 1)
            m.load(0x8000, bytes([0xF3, 0x18, 0xFE])); m.set_regs(pc=0x8000, sp=0x7FF0)
            m.run_ticks(2800000)
        raw, got = raw_zx.audio(raw=True), zx.audio()
        want = np.column_stack([models[c].process(raw[:, c]) for c in (0, 1)]).astype(np.int16)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)

    def test_idle_stream_is_zero_but_mixer_is_not(self):
        zx = machine()
        zx.audio(48000); zx.run_ticks(2_800_000)
        a = zx.audio(48000)
        self.assertGreater(len(a), 4000)
        self.assertEqual(zx.audio_level(), (1024, 1024))
        self.assertTrue(np.all(a == 0), 'idle playback must be PCM zero')

    def test_constant_high_stream_is_zero(self):
        zx = machine()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        ay(zx, 7, 0xFF); ay(zx, 8, 15)
        zx.run_ticks(28000)
        zx.audio(48000); zx.run_ticks(2_800_000)
        a = zx.audio(48000)
        self.assertEqual(zx.audio_level(), (1279, 1024))
        self.assertTrue(np.all(a == 0), 'constant AY output is also silence')

    def test_long_middle_rest_settles(self):
        zx = machine()
        zx.nr_write(0x06, zx.nr_read(0x06) | 1)
        for reg, value in [(0, 124), (1, 0), (7, 0xFE), (8, 15)]:
            ay(zx, reg, value)
        zx.audio(48000); zx.run_ticks(28_000_000)
        self.assertGreater(np.ptp(zx.audio(48000)[:, 0]), 0)
        ay(zx, 8, 0); zx.run_ticks(28_000_000)
        a = zx.audio(48000)
        self.assertTrue(np.all(a[-12000:] == 0), 'long rest must finish at PCM zero')


if __name__ == '__main__':
    unittest.main()
