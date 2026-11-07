"""Contract tests for the causal Python reference, independent of the C port."""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zxaudio import BiasController, ACTIVE, ATTACK, QUIET, RELEASE


class BiasContract(unittest.TestCase):
    def test_constant_any_level_is_exact_zero(self):
        for level in (0, 5120, 6395, -12000, 12000):
            p = BiasController(48000)
            self.assertEqual(p.process([level] * 1000), [0.0] * 1000)

    def test_cosines_move_bias_not_signal_gain(self):
        p = BiasController(1000, hold_ms=4, release_ms=4, attack_ms=2,
                           centered=True, initial=10)
        for got, want in zip(p.process([11, 12, 13]), [1.0, 7.0, 13.0]):
            self.assertAlmostEqual(got, want, places=12)
        self.assertEqual(p.state, ACTIVE)
        p.process([13] * 4)
        self.assertEqual(p.state, RELEASE)
        self.assertEqual(p.bias, 0)
        got = p.process([13] * 4)
        want = [13 * (1 + math.cos(math.pi * k / 4)) / 2 for k in range(1, 5)]
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=12)
        self.assertEqual(p.state, QUIET)
        self.assertEqual(got[-1], 0)
        # The first new sample passes at unit gain with the current bias.
        self.assertEqual(p.step(23), 10)
        self.assertEqual(p.state, ATTACK)

    def test_resume_mid_return_is_continuous_in_bias(self):
        p = BiasController(1000, hold_ms=4, release_ms=10, attack_ms=2,
                           centered=True, initial=0)
        p.process([10, 20, 10, 20] + [20] * 8)
        self.assertEqual(p.state, RELEASE)
        bias = p.bias
        self.assertAlmostEqual(p.step(30), 30 - bias)
        self.assertEqual(p.state, ATTACK)

    def test_chunks_future_and_reset(self):
        rng = random.Random(70)
        xs = [5120] * 20 + [rng.randrange(30000) for _ in range(500)] + [6395] * 1000
        full = BiasController(1000).process(xs)
        p = BiasController(1000)
        parts = []
        for a in range(0, len(xs), 17):
            parts.extend(p.process(xs[a:a+17]))
        self.assertEqual(full, parts)
        self.assertEqual(full[:300], BiasController(1000).process(xs[:300] + [-1234] * 50)[:300])
        p.reset()
        self.assertEqual(full, p.process(xs))
        self.assertEqual(p.process([]), [])

    def test_bass_is_not_rebiased(self):
        for rate in (44100, 48000, 96000):
            for hz in (8, 20, 26.7094):
                p = BiasController(rate)
                half = round(rate / (2 * hz))
                for i in range(rate):
                    p.step(5120 + 1275 * ((i // half) % 2))
                    self.assertNotEqual(p.state, RELEASE)

    def test_short_rests_are_not_gated_and_long_rest_settles(self):
        p = BiasController(1000)
        p.process([0, 100] * 500)
        before = p.process([0] * 50)
        self.assertTrue(any(before))
        self.assertEqual(p.state, ACTIVE)
        p.process([0] * 500)
        self.assertEqual(p.state, QUIET)
        self.assertEqual(p.process([0] * 100), [0.0] * 100)

    def test_no_second_highpass_for_centered_ay(self):
        p = BiasController(1000, centered=True, initial=0)
        xs = [-10, 10] * 100
        self.assertEqual(p.process(xs), xs)

    def test_edge_hint_avoids_false_idle_from_averaged_wave(self):
        p = BiasController(1000, initial=0)
        for _ in range(600):
            p.step(0, activity=True)
        self.assertEqual(p.state, ACTIVE)

    def test_bad_configuration_is_rejected(self):
        for rate in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                BiasController(rate)
        for key in ('hold_ms', 'release_ms', 'attack_ms'):
            with self.assertRaises(ValueError):
                BiasController(1000, **{key: -1})
        with self.assertRaises(ValueError):
            BiasController(1000, pole=1)

    def test_hold_deadline_applies_during_long_attack(self):
        p = BiasController(1000, hold_ms=1, release_ms=1, attack_ms=1000, initial=0)
        p.step(100)
        self.assertEqual(p.state, ATTACK)
        p.step(100)
        self.assertEqual(p.state, RELEASE)
        self.assertEqual(p.step(100), 0)
        self.assertEqual(p.state, QUIET)


if __name__ == '__main__':
    unittest.main()
