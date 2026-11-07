"""WAV regressions: actual silence, not just the beeper's edge-note log."""
import array
import sys
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speccy import Speccy
from zxay import write_ay_wav

OUT = Path(__file__).resolve().parent / 'out' / 'audio'


def samples(path):
    with wave.open(str(path), 'rb') as f:
        xs = array.array('h', f.readframes(f.getnframes()))
    if sys.byteorder != 'little':
        xs.byteswap()
    return list(xs)


class AudioExport(unittest.TestCase):
    def test_held_high_ay_has_no_recording_startup_pulse(self):
        from zxscript import Runner
        OUT.mkdir(parents=True, exist_ok=True)
        runner = Runner(str(OUT))
        runner.step('boot128'); runner.step('menu 48')
        zx = runner.zx
        zx.type('OUT 65533,7: OUT 49149,255: OUT 65533,8: OUT 49149,15\n')
        zx.wait_ready(); zx.run(10)
        zx.record_ay(); zx.run(10)
        path = OUT / 'ay-held-high.wav'
        write_ay_wav(zx, path, trim=False)
        self.assertEqual(max(abs(x) for x in samples(path)), 0)

    def test_writer_is_repeatable_and_does_not_change_note_log(self):
        zx = Speccy()
        zx.type('10 BEEP 0.1,0: PAUSE 25: BEEP 0.1,7\n')
        zx.type('RUN'); zx.record_audio(); zx.keystroke('ENTER')
        zx.wait_ready(); zx.run(40)
        notes = zx.beeper_notes()
        OUT.mkdir(parents=True, exist_ok=True)
        a, b, raw = (OUT / n for n in ('repeat-a.wav', 'repeat-b.wav', 'raw.wav'))
        zx.write_wav(a); zx.write_wav(b); zx.write_wav(raw, raw=True)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(notes, zx.beeper_notes())
        self.assertEqual(len(samples(a)), len(samples(raw)))
        self.assertTrue(all(x == 0 for x in samples(a)[-4000:]))
        self.assertNotEqual(samples(a), samples(raw))

    def test_empty_recording_and_invalid_rate(self):
        zx = Speccy(); zx.record_audio()
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / 'empty.wav'
        zx.write_wav(path)
        self.assertEqual(samples(path), [])
        with self.assertRaises(ValueError):
            zx.write_wav(path, rate=0)

    def test_idle_beeper_is_all_zero(self):
        zx = Speccy()
        zx.record_audio(); zx.run(10)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / 'idle.wav'
        zx.write_wav(path)
        self.assertTrue(samples(path))
        self.assertEqual(set(samples(path)), {0})

    def test_held_high_beeper_is_all_zero(self):
        zx = Speccy()
        zx.type('OUT 254,16\n'); zx.wait_ready(); zx.run(10)
        zx.record_audio(); zx.run(10)
        self.assertEqual(zx._audio_level0, 1)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / 'high.wav'
        zx.write_wav(path)
        self.assertEqual(set(samples(path)), {0})

    def test_ay_silence_stays_zero(self):
        zx = Speccy(model=128)
        zx.record_ay(); zx.run(10)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / 'ay.wav'
        write_ay_wav(zx, path, trim=False)
        self.assertEqual(set(samples(path)), {0})


if __name__ == '__main__':
    unittest.main()
