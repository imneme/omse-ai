"""Stock and foil: the compiled native controller versus the Python model.

Comparisons are before quantisation (<=1e-7 sample units), and after
truncation (<=1 LSB). Actual maxima go in tests/out/audio/conformance.json.
"""
import ctypes as ct
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zxaudio import BiasController, pcm16

OUT = ROOT / 'tests/out/audio'


class Native:
    def __init__(self, lib, rate, **kw):
        self.lib = lib
        self.ptr = lib.bias_new(rate, kw.get('hold_ms', 250), kw.get('release_ms', 250),
                               kw.get('attack_ms', 2), kw.get('pole', -1), kw.get('centered', False))

    def __del__(self):
        if getattr(self, 'ptr', None):
            self.lib.bias_free(self.ptr)

    def process(self, x):
        x = np.ascontiguousarray(x, dtype=np.float64)
        y = np.empty_like(x)
        s = np.empty(len(x), dtype=np.int32)
        self.lib.bias_process(self.ptr, x.ctypes.data_as(ct.POINTER(ct.c_double)),
                              y.ctypes.data_as(ct.POINTER(ct.c_double)),
                              s.ctypes.data_as(ct.POINTER(ct.c_int)), len(x))
        return y, s


def load_probe(path=None):
    OUT.mkdir(parents=True, exist_ok=True)
    path = Path(path or OUT / ('bias.dylib' if sys.platform == 'darwin' else 'bias.so'))
    if not path.exists() or path.stat().st_mtime < max((ROOT / 'src/audio_bias.h').stat().st_mtime,
                                                     (ROOT / 'tests/audio_bias_probe.cpp').stat().st_mtime):
        subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++20', '-O3', '-fPIC',
                        '-dynamiclib' if sys.platform == 'darwin' else '-shared',
                        str(ROOT / 'tests/audio_bias_probe.cpp'), '-o', str(path)], check=True)
    lib = ct.CDLL(str(path))
    lib.bias_new.argtypes = [ct.c_int, ct.c_double, ct.c_double, ct.c_double, ct.c_double, ct.c_int]
    lib.bias_new.restype = ct.c_void_p
    lib.bias_free.argtypes = [ct.c_void_p]
    lib.bias_reset.argtypes = [ct.c_void_p]
    lib.bias_process.argtypes = [ct.c_void_p, ct.POINTER(ct.c_double), ct.POINTER(ct.c_double),
                                ct.POINTER(ct.c_int), ct.c_size_t]
    lib.bias_quantize.argtypes = [ct.POINTER(ct.c_double), ct.POINTER(ct.c_int16), ct.c_size_t]
    return lib


def material(rate, hz=26.7094017094):
    def tone(seconds, offset=5120, amplitude=1275):
        t = np.arange(round(seconds * rate)) / rate
        return offset + amplitude * ((t * hz) % 1 < 0.5)
    pieces = [np.full(rate // 5, 5120.0)]
    for pause in (0.010, 0.050, 0.250, 2.000):
        pieces += [tone(0.35), np.full(round(pause * rate), 5120.0)]
    pieces += [tone(0.1, 6395, 1), np.full(rate, 6395.0),
               np.random.default_rng(70).integers(0, 29991, 1000).astype(float),
               np.full(rate, 10000.0)]
    return np.concatenate(pieces)


class NativeConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_probe(os.environ.get('BIAS_PROBE_LIB'))
        cls.receipts = []

    @classmethod
    def tearDownClass(cls):
        (OUT / 'conformance.json').write_text(json.dumps(cls.receipts, indent=2) + '\n')

    def compare(self, rate, x, **kw):
        model = BiasController(rate, **kw)
        y = np.empty(len(x)); states = np.empty(len(x), dtype=np.int32)
        for i, sample in enumerate(x):
            y[i] = model.step(sample); states[i] = model.state
        native = Native(self.lib, rate, **kw)
        actual, cstates = native.process(x)
        error = float(np.max(np.abs(y - actual))) if len(x) else 0
        py_pcm = np.fromiter((pcm16(v) for v in y), dtype=np.int16, count=len(y)).astype(int)
        c_pcm = np.empty(len(actual), dtype=np.int16)
        self.lib.bias_quantize(actual.ctypes.data_as(ct.POINTER(ct.c_double)),
                               c_pcm.ctypes.data_as(ct.POINTER(ct.c_int16)), len(actual))
        c_pcm = c_pcm.astype(int)
        pcm_error = int(np.max(np.abs(py_pcm - c_pcm))) if len(x) else 0
        self.assertLessEqual(error, 1e-7)
        self.assertLessEqual(pcm_error, 1)
        np.testing.assert_array_equal(states, cstates)
        self.receipts.append(dict(rate=rate, samples=len(x), options=kw,
                                  max_float_error=error, max_pcm_error=pcm_error,
                                  differing_pcm_samples=int(np.count_nonzero(py_pcm != c_pcm))))
        return actual

    def test_varied_material_and_rates(self):
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                self.compare(rate, material(rate))

    def test_beeper_pole_and_centered_ay_modes(self):
        x = material(44100, 261.63) - 5120
        self.compare(44100, x, pole=0.995)
        self.compare(44100, x, centered=True)
        self.compare(44100, x, hold_ms=2000)

    def test_native_chunks_causality_and_reset(self):
        x = material(48000, 882.056)
        full = self.compare(48000, x)
        native = Native(self.lib, 48000)
        parts = []
        for a in range(0, len(x), 257):
            parts.append(native.process(x[a:a+257])[0])
        np.testing.assert_array_equal(full, np.concatenate(parts))
        changed = np.r_[x[:12345], np.full(1000, -12345.0)]
        np.testing.assert_array_equal(full[:12345], Native(self.lib, 48000).process(changed)[0][:12345])
        self.lib.bias_reset(native.ptr)
        np.testing.assert_array_equal(full, native.process(x)[0])
        self.assertEqual(len(native.process([])[0]), 0)

    def test_short_curves_and_held_high(self):
        self.compare(1000, np.r_[np.full(10, 12000), [13000, 14000, 15000],
                                 np.full(30, 15000), [17000, 14000, 16000], np.full(30, 16000)],
                     hold_ms=4, release_ms=10, attack_ms=2, centered=True)
        for value in (0, 5120, 12000, -12000):
            y = self.compare(48000, np.full(1000, value))
            self.assertEqual(np.count_nonzero(y), 0)
        self.compare(1000, np.r_[np.zeros(10), np.full(2000, 100)],
                     hold_ms=1, release_ms=1, attack_ms=1000)

    def test_native_pcm_saturation_and_truncation(self):
        x = np.array([-1e6, -32768.9, -32768, -32000.9, -1.9, -0.9,
                      0, 0.9, 1.9, 32000.9, 32767, 32767.9, 1e6], dtype=np.float64)
        actual = np.empty(len(x), dtype=np.int16)
        self.lib.bias_quantize(x.ctypes.data_as(ct.POINTER(ct.c_double)),
                               actual.ctypes.data_as(ct.POINTER(ct.c_int16)), len(x))
        np.testing.assert_array_equal(actual, [pcm16(v) for v in x])


if __name__ == '__main__':
    unittest.main()
