"""omse-ai's tests.  They need the ROMs (README.md, "Bring your own ROMs").
Tests are skipped, with the reason, without the 128K ROMs, without Pillow
(pictures) or without speccy-basic (the linter).  What they write goes in
tests/out/.

    python3 -m unittest discover -s tests        (or ./tests/run.sh)
"""
import ctypes
import math
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import speccy                                           # noqa: E402
from speccy import Speccy, ZXSyntaxError, ROMError      # noqa: E402

OUT = ROOT / 'tests' / 'out'
OUT.mkdir(parents=True, exist_ok=True)


def have_128():
    try:
        speccy.rom_bytes('128-0'), speccy.rom_bytes('128-1')
        return True
    except ROMError:
        return False


def have_pillow():
    try:
        speccy.pil()
        return True
    except speccy.MissingTool:
        return False


def have_speccy_basic():
    try:
        import spectrum_basic  # noqa: F401
        return True
    except ImportError:
        return False


def cli(*args, env=None):
    """Run ./speccy.py with these arguments; returns (exit code, output)."""
    r = subprocess.run([sys.executable, str(ROOT / 'speccy.py'), *args], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


class TestROMs(unittest.TestCase):
    def test_missing_rom_says_what_to_do(self):
        empty = OUT / 'no-roms'
        empty.mkdir(parents=True, exist_ok=True)
        code, out = cli('--roms', str(empty), 'do', 'boot')
        self.assertEqual(code, 2)
        self.assertIn('no ROM at', out)
        self.assertIn('Bring your own ROMs', out)

    def test_a_web_page_is_not_a_rom(self):
        page = OUT / 'page.rom'
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('<!DOCTYPE html><html><title>Page not found</title></html>\n' * 300)
        with self.assertRaisesRegex(ROMError, 'web page'):
            Speccy(rom=page)


class TestTyping(unittest.TestCase):
    def test_boots_to_the_copyright_message(self):
        self.assertIn('1982 Sinclair Research Ltd', Speccy().screen_text())

    def test_keywords_go_in_as_tokens(self):
        zx = Speccy()
        zx.type('10 PRINT "hi": GO TO 10')
        self.assertEqual(zx.edit_line(), b'10\xf5"hi":\xec10')    # PRINT and GO TO are one byte each
        self.assertEqual(zx.mode(), 'L')

    def test_every_keyword_on_the_keyboard(self):
        zx = Speccy()
        lines = (ROOT / 'tests' / 'torture.bas').read_text().strip().split('\n')
        for line in lines[:-1]:
            zx.type(line + '\n')
            self.assertFalse(zx.edit_line(), line)                # the ROM took it
        with self.assertRaises(ZXSyntaxError) as e:               # the last line is a real error
            zx.type(lines[-1] + '\n')
        self.assertIn('?', str(e.exception))                      # quoted with the ROM's own marker

    def test_breakpoint_on_the_editor_loop(self):
        zx = Speccy()
        self.assertEqual(zx.run_until(0x15DE, frames=10), 0x15DE)


class TestSound(unittest.TestCase):
    def test_the_beeper_is_measured_in_tune(self):
        zx = Speccy()
        zx.type('10 FOR i=1 TO 8: READ n: BEEP 0.2,n: NEXT i: DATA 0,2,4,5,7,9,11,12\n')
        zx.record_audio()
        zx.type('RUN\n')
        self.assertIsNotNone(zx.wait_ready())
        notes = zx.beeper_notes()
        self.assertEqual(len(notes), 8)
        for (start, dur, hz), semis in zip(notes, [0, 2, 4, 5, 7, 9, 11, 12]):
            want = 261.63 * 2 ** (semis / 12)
            self.assertLess(abs(12 * math.log2(hz / want)), 0.05)    # within 5 cents
            self.assertAlmostEqual(dur, 0.2, delta=0.01)


class TestTapesAndSnapshots(unittest.TestCase):
    def test_save_then_load(self):
        zx = Speccy()
        zx.type('10 PRINT "round trip"\n')
        zx.type('SAVE "rt" LINE 10\n')
        zx.wait_ready(200)
        zx.keystroke('ENTER')                     # "Start tape, then press any key."
        zx.wait_ready(200)
        tape = zx.saved_tape()
        blocks, i = [], 0
        while i < len(tape):
            n = tape[i] | tape[i + 1] << 8
            blocks.append(tape[i + 2:i + 2 + n])
            i += 2 + n
        self.assertEqual([b[0] for b in blocks], [0x00, 0xFF])      # a header, then the data
        self.assertEqual(blocks[0][1:12], b'\x00rt        ')          # a program called "rt"
        zx2 = Speccy()
        zx2.insert_tape(tape)
        zx2.type('LOAD ""\n')
        zx2.wait_ready(500)
        zx2.run(20)
        self.assertIn('round trip', zx2.screen_text())

    def test_a_snapshot_resumes_exactly(self):
        # Sync on the program, not the frame count: both machines are compared
        # when the program reaches its PAUSE 0.
        zx = Speccy()
        zx.type('10 FOR i=0 TO 175: PLOT i,i: DRAW 80,0: NEXT i: PAUSE 0\n')
        zx.type('RUN\n')
        zx.run(40)                                 # mid-loop
        snap = OUT / 'mid.sna'
        zx.save_sna(snap)
        self.assertIsNotNone(zx.wait_ready(pause=True))
        zx2 = Speccy(sna=snap)
        self.assertIsNotNone(zx2.wait_ready(pause=True))
        self.assertEqual(zx.read(0x4000, 6912), zx2.read(0x4000, 6912))

    @unittest.skipUnless(have_128(), 'no 128K ROMs')
    def test_128k_snapshot_keeps_every_bank(self):
        zx = Speccy(model=128)
        for b in range(8):
            ctypes.memset(zx.lib.zx_bank(zx.z, b) + 0x3000, 0x40 + b, 64)
        snap = OUT / 'banks.sna'
        zx.save_sna(snap)
        self.assertEqual(snap.stat().st_size, 131103)
        zx2 = Speccy(model=128, sna=snap)
        for b in range(8):
            got = ctypes.string_at(zx2.lib.zx_bank(zx2.z, b) + 0x3000, 64)
            self.assertEqual(got, bytes([0x40 + b]) * 64, f'bank {b}')


@unittest.skipUnless(have_128(), 'no 128K ROMs')
class TestPokeOn128(unittest.TestCase):
    """With bank 5 or 2 also paged at C000, the 128 has the same bank at two
    addresses: a poke at either must show at both, and stay in the bank."""

    def paged(self, bank):                  # DI; LD BC,7FFDh; LD A,10h+bank; OUT (C),A; JR $
        zx = Speccy(model=128)
        snap = OUT / 'poke128.sna'
        zx.save_sna(snap)
        d = bytearray(snap.read_bytes())
        code = bytes([0xF3, 0x01, 0xFD, 0x7F, 0x3E, 0x10 | bank, 0xED, 0x79, 0x18, 0xFE])
        d[27 + 0x4000:27 + 0x4000 + len(code)] = code               # bank 2, at 8000h
        d[49179:49181] = (0x8000).to_bytes(2, 'little')             # PC
        snap.write_bytes(bytes(d))
        zx.load_sna(snap)
        self.assertEqual(zx.run_until(0x8008, frames=10), 0x8008)
        self.assertEqual(zx.lib.zx_paging(zx.z) & 7, bank)
        return zx

    def test_bank_5_at_c000(self):
        zx = self.paged(5)
        zx.poke(0xC123, 0x5A)
        zx.poke(0x4321, 0xA5)
        self.assertEqual((zx.peek(0x4123), zx.peek(0xC321)), (0x5A, 0xA5))
        self.assertEqual(ctypes.string_at(zx.lib.zx_bank(zx.z, 5) + 0x123, 1), b"\x5a")

    def test_bank_2_at_c000(self):
        zx = self.paged(2)
        zx.poke(0xC456, 0x3C)
        zx.poke(0x8654, 0xC3)
        self.assertEqual((zx.peek(0x8456), zx.peek(0xC654)), (0x3C, 0xC3))
        self.assertEqual(ctypes.string_at(zx.lib.zx_bank(zx.z, 2) + 0x456, 1), b"\x3c")


@unittest.skipUnless(have_128(), 'no 128K ROMs')
@unittest.skipUnless(have_pillow(), 'no Pillow (the roll step draws a PNG)')
class Test128(unittest.TestCase):
    def test_the_ay_played_an_arpeggio(self):
        code, out = cli('--dir', str(OUT), 'run', 'examples/ay48.zx')
        self.assertEqual(code, 0, out)
        notes = (OUT / 'out' / 'ay48' / 'arpeggio.txt').read_text().split('\n')
        names = [line.split()[3] for line in notes if line.strip()]
        self.assertEqual(names, ['C4', 'E4', 'G#4', 'C5', 'E5', 'G#5', 'C6'])


class TestCommandLine(unittest.TestCase):
    @unittest.skipUnless(have_pillow(), 'no Pillow (the script makes pictures)')
    def test_hello_script(self):
        code, out = cli('--dir', str(OUT), 'run', 'examples/hello.zx')
        self.assertEqual(code, 0, out)
        self.assertIn('hello from omse-ai', out)
        self.assertIn('0 OK, 20:1', out)
        for f in ['hello_run.png', 'hello_run_960.jpg', 'hello_end.png', 'hello.wav']:
            self.assertTrue((OUT / 'out' / 'hello' / f).exists(), f)

    def test_notes_step(self):
        code, out = cli('--dir', str(OUT), 'do', 'enter 10 BEEP 0.1,0: BEEP 0.1,7: BEEP 0.1,12',
                        'audio', 'enter RUN', 'ready', 'notes')
        self.assertEqual(code, 0, out)
        self.assertEqual([line.split()[4] for line in out.split('\n') if ' Hz ' in line], ['C4', 'G4', 'C5'])

    def test_roundtrip_script(self):
        code, out = cli('--dir', str(OUT), 'run', 'examples/roundtrip.zx')
        self.assertEqual(code, 0, out)
        self.assertIn('saved and loaded', out)

    @unittest.skipUnless(have_pillow(), 'no Pillow (go writes now.png)')
    def test_go_persists_between_calls(self):
        shutil.rmtree(OUT / 'snaps', ignore_errors=True)
        code, out = cli('--dir', str(OUT), 'go', 't', 'enter 10 PRINT "kept"')
        self.assertEqual(code, 0, out)
        code, out = cli('--dir', str(OUT), 'go', 't', 'enter RUN', 'ready', 'wait 20', 'screen')
        self.assertEqual(code, 0, out)
        self.assertIn('kept', out)
        self.assertTrue((OUT / 'snaps' / 't.sna').exists())

    def test_steps_from_a_file(self):
        steps = OUT / 'mysteps.py'
        steps.write_text('def step_border_is(runner, arg):\n'
                         '    """border-is N: fail unless the border is colour N"""\n'
                         '    assert runner.need().border == int(arg), runner.need().border\n'
                         '    print("border ok")\n')
        code, out = cli('--dir', str(OUT), '--steps', str(steps),
                        'do', 'enter BORDER 3', 'ready', 'border-is 3')
        self.assertEqual(code, 0, out)
        self.assertIn('border ok', out)
        code, out = cli('--steps', str(steps), 'help')
        self.assertIn('border-is N', out)

    def test_a_failing_script_names_its_line(self):
        bad = OUT / 'bad.zx'
        bad.write_text('enter 10 PRINT 1+\n')
        code, out = cli('--dir', str(OUT), 'run', str(bad))
        self.assertEqual(code, 1)
        self.assertIn('bad.zx:1:', out)
        self.assertIn('ZXSyntaxError', out)


@unittest.skipUnless(have_speccy_basic(), 'speccy-basic is not installed')
class TestLint(unittest.TestCase):
    def test_the_rom_as_linter(self):
        code, out = cli('--dir', str(OUT), 'do', 'lint tests/illegal.bas')
        self.assertIn('lint: 5 of 8 lines accepted', out)
        self.assertIn('FOR ii', out)
        code, out = cli('--dir', str(OUT), 'do', 'lint tests/illegal.bas min')
        self.assertIn('lint: 8 of 8 lines accepted', out)


if __name__ == '__main__':
    unittest.main()
