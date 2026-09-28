#!/usr/bin/env python3
"""omse-ai: a headless ZX Spectrum (48K and 128K) you can script and *look at*.

The core (src/zxcore.cpp) is OMSE, Melissa O'Neill's emulator, reshaped as a C
library.  This module drives it through ctypes: run frames, press keys, type
BASIC (keyword entry and all), load TAPs through the ROM, save and load
snapshots, and turn what happened into PNGs, contact sheets, text and numbers.

    from speccy import Speccy
    zx = Speccy()                    # boots the 48K ROM
    zx.type('10 PRINT "HELLO"\\n')    # types keywords the Spectrum way
    zx.type('RUN\\n'); zx.wait_ready()
    zx.shot('out/hello.png')
    print(zx.screen_text())

The ROMs are not included: see README.md, "Bring your own ROMs".  The command
line (./speccy.py run script.zx, and the rest) is in zxscript.py; MANUAL.md
has everything.
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB_PATH = HERE / 'lib' / ('libzxcore.dylib' if sys.platform == 'darwin' else 'libzxcore.so')
LIB_SOURCES = [HERE / 'src' / n for n in ('zxcore.cpp', 'z80.h', 'ay38910.h')]

# The ROMs: a folder holding 48.rom, 128-0.rom and 128-1.rom (the names OMSE
# and most emulators use).  $OMSE_AI_ROMS, or roms/ next to this file.
ROM_NAMES = {'48': '48.rom', '128-0': '128-0.rom', '128-1': '128-1.rom'}
ROM_SIZE = 16384


class ROMError(Exception):
    """A ROM is missing or isn't a ROM."""


class MissingTool(RuntimeError):
    """Something omse-ai needs for this job isn't installed (the message says what)."""


def pil():
    """Pillow's Image, ImageDraw and ImageFont, or a MissingTool saying how to get them."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise MissingTool(f'no Pillow in this Python ({sys.executable}), and pictures need it: '
                          'pip install Pillow') from None
    return Image, ImageDraw, ImageFont


def roms_dir():
    """Where the ROMs are looked for: $OMSE_AI_ROMS, else roms/ in the repository."""
    env = os.environ.get('OMSE_AI_ROMS')
    return Path(env).expanduser() if env else HERE / 'roms'


def rom_bytes(which='48', path=None):
    """The 16K of one ROM ('48', '128-0' or '128-1'), checked.  `path` overrides
    where it's read from.  Raises ROMError with directions if it's missing or
    isn't a ROM (a failed download is often a web page)."""
    p = Path(path).expanduser() if path else roms_dir() / ROM_NAMES[which]
    if not p.exists():
        where = 'the path you gave' if path else (
            '$OMSE_AI_ROMS' if os.environ.get('OMSE_AI_ROMS') else 'roms/ (set OMSE_AI_ROMS to look elsewhere)')
        raise ROMError(
            f'no ROM at {p}\n'
            f'  omse-ai needs the ZX Spectrum ROMs and does not include them. It looked in {where}.\n'
            f'  Put 48.rom (and 128-0.rom, 128-1.rom for the 128) there: README.md, "Bring your own ROMs",\n'
            f'  has a download recipe.')
    data = p.read_bytes()
    if data[:1] == b'<' or b'<html' in data[:512].lower():
        raise ROMError(f'{p} is a web page, not a ROM: the download fetched HTML. '
                       'Fetch the raw file (README.md, "Bring your own ROMs").')
    if len(data) != ROM_SIZE:
        raise ROMError(f'{p} is {len(data)} bytes; a Spectrum ROM is {ROM_SIZE}.')
    return data


FPS = 50.08   # 3.5 MHz / 69888 T-states per frame
T_PER_FRAME = 69888
CLOCK = 3_500_000

# ---------------------------------------------------------------------------
# Palette: index = colour + 8 * bright.  Normal at 0xD7, bright at 0xFF.
N, B = 0xD7, 0xFF
PALETTE = [
    (0, 0, 0), (0, 0, N), (N, 0, 0), (N, 0, N), (0, N, 0), (0, N, N), (N, N, 0), (N, N, N),
    (0, 0, 0), (0, 0, B), (B, 0, 0), (B, 0, B), (0, B, 0), (0, B, B), (B, B, 0), (B, B, B),
]
COLOUR_NAMES = ['black', 'blue', 'red', 'magenta', 'green', 'cyan', 'yellow', 'white']

# ---------------------------------------------------------------------------
# System variables we lean on (addresses from the 48K ROM disassembly)
KSTATE = 23552    # two 4-byte key sets; byte 0 bit 7 set = free
LAST_K = 23560
FLAGS = 23611     # bit 5: new key; bit 3: keyboard in L mode (else K)
TV_FLAG = 23612   # bit 3: edit line needs redrawing
ERR_NR = 23610    # report code - 1 (0xFF = OK)
MODE = 23617      # 0 = K/L/C, 1 = E, 2 = G
PPC = 23621       # line number of the statement being executed
E_LINE = 23641
X_PTR = 23647
K_CUR = 23643
FLAGS2 = 23658    # bit 3: caps lock
FLAGX = 23665     # bit 5: INPUT mode
UDG = 23675
FRAMES = 23672

_lib = None


class ZXSyntaxError(Exception):
    pass


def _load_lib():
    global _lib
    if _lib is not None:
        return _lib
    newest = max(f.stat().st_mtime for f in LIB_SOURCES)
    if not LIB_PATH.exists() or LIB_PATH.stat().st_mtime < newest:
        # build (or rebuild) the core: make, with a C++20 compiler
        r = subprocess.run(['make', '-s', '-C', str(HERE)], capture_output=True, text=True)
        if r.returncode != 0 or not LIB_PATH.exists():
            raise MissingTool(f'could not build {LIB_PATH.name} with make in {HERE} '
                               f'(it needs make and a C++20 compiler):\n{r.stdout}{r.stderr}')
    lib = ctypes.CDLL(str(LIB_PATH))
    P, U8P, I, U16, U64 = ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_uint16, ctypes.c_uint64
    sigs = {
        'zx_new': ([], P), 'zx_free': ([P], None),
        'zx_load_rom': ([P, ctypes.c_char_p, I], None), 'zx_reset': ([P], None),
        'zx_load_sna': ([P, ctypes.c_char_p, I], I), 'zx_save_sna': ([P, U8P, I], I),
        'zx_run_frames': ([P, I], I), 'zx_run_until_pc': ([P, U16, U16, U64], I),
        'zx_run_tstates': ([P, U64], None), 'zx_run_until_breaks': ([P, U64], I),
        'zx_add_break': ([P, U16, U16], None), 'zx_clear_breaks': ([P], None), 'zx_hit_pc': ([P], I),
        'zx_set_keys': ([P, ctypes.c_char_p], None), 'zx_set_kempston': ([P, ctypes.c_uint8], None),
        'zx_memory': ([P], P), 'zx_framebuffer': ([P], P),
        'zx_fb_width': ([], I), 'zx_fb_height': ([], I),
        'zx_frame': ([P], U64), 'zx_render_static': ([P], None),
        'zx_frame_pos': ([P], I), 'zx_frame_len': ([P], I),
        'zx_make_128': ([P, ctypes.c_char_p, ctypes.c_char_p], None), 'zx_model': ([P], I),
        'zx_clock': ([P], I), 'zx_paging': ([P], I), 'zx_bank': ([P, I], P),
        'zx_ay_record': ([P, I], None), 'zx_ay_rate': ([], I),
        'zx_ay_samples_len': ([P], I), 'zx_ay_samples_get': ([P, ctypes.POINTER(ctypes.c_float)], None),
        'zx_ay_samples_clear': ([P], None), 'zx_ay_log_len': ([P], I),
        'zx_ay_log_get': ([P, ctypes.POINTER(ctypes.c_uint64)], None), 'zx_ay_log_clear': ([P], None), 'zx_tstates': ([P], U64), 'zx_border': ([P], I),
        'zx_regs': ([P, ctypes.POINTER(ctypes.c_uint16)], None),
        'zx_tape_insert': ([P, ctypes.c_char_p, I], None), 'zx_tape_pos': ([P], I), 'zx_tape_len': ([P], I),
        'zx_tape_out_len': ([P], I), 'zx_tape_out_get': ([P, U8P], None), 'zx_tape_out_clear': ([P], None),
        'zx_loads': ([P], I), 'zx_saves': ([P], I),
        'zx_log_audio': ([P, I], None), 'zx_audio_len': ([P], I),
        'zx_audio_get': ([P, ctypes.POINTER(ctypes.c_uint64)], None), 'zx_audio_clear': ([P], None),
        'zx_ear': ([P], I),
        'zx_text_len': ([P], I), 'zx_text_get': ([P, U8P], None), 'zx_text_clear': ([P], None),
        'zx_execmap': ([P, I, I], None), 'zx_execmap_get': ([P], P),
    }
    for name, (args, res) in sigs.items():
        f = getattr(lib, name)
        f.argtypes = args
        f.restype = res
    _lib = lib
    return lib


class Speccy:
    """One Spectrum: a 48K, or with model=128 a Spectrum 128 at its menu.
    Boots the ROM unless given a snapshot.  The ROMs come from roms_dir()
    ($OMSE_AI_ROMS or roms/); rom= overrides the 48K ROM's path, and
    roms128=(rom0, rom1) the 128's."""

    def __init__(self, sna=None, rom=None, boot_frames=None, model=48, roms128=None):
        if model not in (48, 128):
            raise ValueError(f'model is 48 or 128, not {model!r}')
        # read the ROMs first, so a missing one is reported before anything else happens
        if model == 128:
            r0, r1 = roms128 or (None, None)
            r0, r1 = rom_bytes('128-0', r0), rom_bytes('128-1', r1)
            self.rom = r1                 # the 48K BASIC ROM: token and key tables
        else:
            self.rom = rom_bytes('48', rom)
        self.lib = _load_lib()
        self.z = self.lib.zx_new()
        if model == 128:
            self.lib.zx_make_128(self.z, r0, r1)
        else:
            self.lib.zx_load_rom(self.z, self.rom, len(self.rom))
        self.model = model
        self.clock = self.lib.zx_clock(self.z)
        self.frame_len = self.lib.zx_frame_len(self.z)
        self.fps = self.clock / self.frame_len
        if boot_frames is None:
            boot_frames = 100 if model == 48 else 150
        W, H = self.lib.zx_fb_width(), self.lib.zx_fb_height()
        self.W, self.H = W, H
        self.mem = (ctypes.c_uint8 * 65536).from_address(self.lib.zx_memory(self.z))
        self._fb = (ctypes.c_uint8 * (W * H)).from_address(self.lib.zx_framebuffer(self.z))
        self._keys_down = set()       # names of matrix keys currently held
        self.frames = []              # (label, image) collected for contact sheets
        self.every = 0                # auto-collect every N frames (0 = off)
        self._since = 0
        self.log = []                 # human-readable log of script steps
        from zxkeys import KeyTables
        self.kt = KeyTables(self.rom)
        if sna:
            self.load_sna(sna)
        elif boot_frames:
            self.run(boot_frames)     # the ROM's RAM test and © message take ~1.5 s

    def __del__(self):
        try:
            self.lib.zx_free(self.z)
            self.z = None
        except Exception:
            pass

    # -- time ---------------------------------------------------------------
    @property
    def frame(self):
        return self.lib.zx_frame(self.z)

    @property
    def seconds(self):
        return self.frame / self.fps

    def run(self, frames=1):
        """Run whole frames, collecting contact-sheet frames if `every` is set."""
        frames = int(frames)
        if not self.every:
            self.lib.zx_run_frames(self.z, frames)
            return
        while frames > 0:
            step = min(frames, self.every - self._since)
            self.lib.zx_run_frames(self.z, step)
            frames -= step
            self._since += step
            if self._since >= self.every:
                self._since = 0
                self.grab()

    def run_seconds(self, s):
        self.run(round(s * self.fps))

    # -- memory and registers ----------------------------------------------
    def peek(self, a):
        return self.mem[a & 0xFFFF]

    def peek16(self, a):
        return self.mem[a] | (self.mem[(a + 1) & 0xFFFF] << 8)

    def poke(self, a, v):
        if a >= 0x4000:
            self.mem[a] = v & 0xFF

    def read(self, a, n):
        return bytes(self.mem[a:a + n])

    def write(self, a, data):
        for i, b in enumerate(data):
            self.poke(a + i, b)

    def regs(self):
        buf = (ctypes.c_uint16 * 16)()
        self.lib.zx_regs(self.z, buf)
        names = ['pc', 'sp', 'af', 'bc', 'de', 'hl', 'ix', 'iy',
                 "af'", "bc'", "de'", "hl'", 'ir', 'im', 'iff1', 'iff2']
        return dict(zip(names, list(buf)))

    @property
    def pc(self):
        return self.regs()['pc']

    @property
    def border(self):
        return self.lib.zx_border(self.z)

    # -- snapshots -----------------------------------------------------------
    def load_sna(self, path):
        data = Path(path).read_bytes()
        if self.lib.zx_load_sna(self.z, data, len(data)) != 0:
            raise ValueError(f'{path}: not a SNA snapshot ({len(data)} bytes; a 48K SNA is 49,179, '
                             f'a 128K one 131,103 or 147,487)')
        self._keys_down.clear()
        self._apply_keys()

    def save_sna(self, path):
        buf = (ctypes.c_uint8 * 147487)()
        n = self.lib.zx_save_sna(self.z, buf, len(buf))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(bytes(buf[:n]))
        return path

    # -- the picture ---------------------------------------------------------
    def indices(self, border=True):
        """The last complete frame as palette indices (bytes, row-major)."""
        raw = bytes(self._fb)
        if border:
            return raw, self.W, self.H
        rows = [raw[(48 + y) * self.W + 48:(48 + y) * self.W + 48 + 256] for y in range(192)]
        return b''.join(rows), 256, 192

    def image(self, border=True, scale=1):
        Image, _, _ = pil()
        data, w, h = self.indices(border)
        im = Image.frombytes('P', (w, h), data)
        im.putpalette([c for rgb in PALETTE for c in rgb])
        im = im.convert('RGB')
        if scale != 1:
            im = im.resize((w * scale, h * scale), Image.NEAREST)
        return im

    def shot(self, path, border=True, scale=2):
        """Save the current frame as PNG (default 2x, nearest neighbour)."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        im = self.image(border, scale)
        im.save(path)
        return path

    def grab(self, label=None):
        """Add the current frame to the contact-sheet collection."""
        if label is None:
            label = f'f{self.frame}  {self.seconds:.1f}s'
        self.frames.append((label, self.image(True, 1)))

    # -- text on screen ------------------------------------------------------
    def screen_text(self, udg_as='?', show_inverse=False):
        """Read the 24x32 character screen by matching cells against the ROM
        font (and the UDGs), either polarity.  Unknown cells become '·'."""
        from zxkeys import screen_text
        return screen_text(self, udg_as=udg_as)

    def printed(self, clear=False):
        """Everything the ROM has printed to the main screen (stream 2) since
        the last clear, with keyword tokens expanded."""
        n = self.lib.zx_text_len(self.z)
        buf = (ctypes.c_uint8 * max(n, 1))()
        self.lib.zx_text_get(self.z, buf)
        if clear:
            self.lib.zx_text_clear(self.z)
        return self.kt.detokenize(bytes(buf[:n]))

    # -- keyboard ------------------------------------------------------------
    def _apply_keys(self):
        rows = [0xFF] * 8
        for name in self._keys_down:
            r, bit = self.kt.MATRIX[name]
            rows[r] &= ~(1 << bit)
        self.lib.zx_set_keys(self.z, bytes(rows))

    def press(self, *names):
        for n in names:
            self._keys_down.add(self.kt.keyname(n))
        self._apply_keys()

    def release(self, *names):
        if not names:
            self._keys_down.clear()
        for n in names:
            self._keys_down.discard(self.kt.keyname(n))
        self._apply_keys()

    def hold(self, keys, frames=5):
        """Hold a chord ('SS+P', 'Q', ['CS','5']) for some frames, then let go."""
        names = self.kt.chord(keys)
        self.press(*names)
        self.run(frames)
        self.release(*names)

    def tap(self, keys, frames=3, after=3):
        self.hold(keys, frames)
        self.run(after)

    def joystick(self, bits):
        """Kempston: bits = 'RLDUF' letters held (right, left, down, up, fire)."""
        v = 0
        for ch, bit in zip('RLDUF', range(5)):
            if ch in bits.upper():
                v |= 1 << bit
        self.lib.zx_set_kempston(self.z, v)

    # -- typing the Spectrum way --------------------------------------------
    def mode(self):
        """The editor's cursor mode as the ROM sees it: K, L, C, E or G."""
        m = self.peek(MODE)
        if m == 1:
            return 'E'
        if m == 2:
            return 'G'
        if not self.peek(FLAGS) & 0x08:
            return 'K'
        return 'C' if self.peek(FLAGS2) & 0x08 else 'L'

    def edit_line(self):
        """Bytes of the line being edited (or INPUT being typed)."""
        a = self.peek16(E_LINE)
        if self.peek(FLAGX) & 0x20:     # INPUT mode: the line lives at WORKSP
            a = self.peek16(23649)
        out = bytearray()
        while len(out) < 1024:
            b = self.peek(a + len(out))
            if b == 0x0D:
                break
            out.append(b)
        return bytes(out)

    def _key_ready(self, main_code):
        """True when the ROM will register `main_code` as a fresh key."""
        if self.peek(FLAGS) & 0x20:          # previous key not yet consumed
            return False
        s0, s1 = self.peek(KSTATE), self.peek(KSTATE + 4)
        if main_code in (s0, s1):            # would count as a repeat
            return False
        return bool(s0 & 0x80 or s1 & 0x80)  # a free set

    def keystroke(self, chord, max_frames=60):
        """Press one chord and wait, frame by frame, until the ROM has taken it.
        Closed loop: reads KSTATE, FLAGS and TV_FLAG instead of guessing timing."""
        names = self.kt.chord(chord)
        code = self.kt.main_code(names)
        for _ in range(max_frames):
            if self._key_ready(code):
                break
            self.run(1)
        self.press(*names)
        took = False
        for _ in range(max_frames):
            self.run(1)
            if code in (self.peek(KSTATE), self.peek(KSTATE + 4)):
                took = True
                break
        self.release(*names)
        self.run(1)
        return took

    def type(self, text, raw=False, verify=True):
        """Type text into the ROM editor, choosing keystrokes from the cursor
        mode as it goes: keywords in K mode are one letter, THEN is SS+G, SIN is
        E-mode Q, and so on.  '\\n' presses ENTER.  With raw=True, nothing is
        treated as a keyword (for INPUT answers).  Returns the keystrokes used."""
        from zxkeys import tokenize_line
        used = []
        for li, piece in enumerate(text.split('\n')):
            if li > 0:
                self._enter(used, verify)
            if not piece:
                continue
            if raw:
                units = [self.kt.char_code(c) for c in piece]
            else:
                units = tokenize_line(piece, self.kt)
            self.settle()
            before = self.edit_line()
            for u in units:
                self.settle()   # the mode is only true once the line is redrawn
                for chord in self.kt.strokes_for(u, self):
                    used.append(chord)
                    if not self.keystroke(chord):
                        raise RuntimeError(f'key {chord} was not taken (mode {self.mode()})')
            self.settle()       # let the ROM take the last key before we look
            if verify:
                want = before + bytes(units)
                got = self.edit_line()
                if got != want:
                    raise RuntimeError('typed line differs:\n  want %r\n  got  %r' % (
                        self.kt.detokenize(want), self.kt.detokenize(got)))
        return used

    def run_until(self, *addrs, frames=50):
        """Run until an opcode fetch at any of `addrs` (ints or (lo,hi)
        ranges), or `frames` frames.  Stops mid-frame.  Returns the PC or None.
        Frames that complete on the way count for `every` (contact sheets)."""
        self.lib.zx_clear_breaks(self.z)
        for a in addrs:
            lo, hi = (a, a) if isinstance(a, int) else a
            self.lib.zx_add_break(self.z, lo, hi)
        flen = self.frame_len
        end = self.frame + frames
        pc = -1
        try:
            while pc < 0 and self.frame < end:
                left = flen - self.lib.zx_frame_pos(self.z)
                pc = self.lib.zx_run_until_breaks(self.z, left)
                if pc < 0 and self.every:     # reached a frame boundary
                    self._since += 1
                    if self._since >= self.every:
                        self._since = 0
                        self.grab()
        finally:
            self.lib.zx_clear_breaks(self.z)
        return None if pc < 0 else pc

    def settle(self, max_frames=100, pause=False):
        """Run until the ROM editor is idle: back round its key-wait loop
        (WAIT-KEY1, 0x15DE) with no key pending and the line redrawn.  Only then
        are mode() and edit_line() true.  (TV_FLAG bit 3 isn't enough: it is
        cleared at the *start* of the redraw, and FLAGS bit 3 is set only when
        the cursor is drawn, at the end.)  With pause=True, a PAUSE 0 key-wait
        (HALT at 0x1F3D) also counts.  Returns True if idle."""
        start = self.frame
        stops = [0x15DE] + ([0x1F3D] if pause else [])
        while self.frame - start < max_frames:
            pc = self.run_until(*stops, frames=max_frames - (self.frame - start))
            if pc is None:
                return False
            if pc == 0x1F3D:
                return True
            if not (self.peek(FLAGS) & 0x20) and not (self.peek(TV_FLAG) & 0x08):
                return True
        return False

    def clear_line(self, max_keys=300):
        """Delete whatever is in the edit line (DELETE until it's empty)."""
        self.settle()
        n = 0
        while self.edit_line() and n < max_keys:
            self.keystroke('DELETE')
            self.settle()
            n += 1
        # leave E/G mode too
        if self.mode() == 'E':
            self.keystroke('EXTEND')
        elif self.mode() == 'G':
            self.keystroke('GRAPHICS')
        return n

    def _enter(self, used, verify):
        used.append('ENTER')
        line = self.edit_line()
        self.keystroke('ENTER')
        # A program line goes in and auto-LISTs: wait for the editor.  A direct
        # command (RUN, LOAD "", PRINT ...) may run for ever: give the ROM a few
        # frames to reject it or finish, then hand back.  Use wait_ready().
        program_line = line[:1].isdigit()
        idle = self.settle(max_frames=self.enter_wait if program_line else 10)
        if idle and verify and self.edit_line() and self.edit_line() == line:
            # The ROM kept the line: a syntax error.  It shows a '?' at the spot.
            text = self.kt.detokenize(line)
            shown = ' / '.join(l.strip() for l in self.screen_text().split('\n')[-3:] if l.strip())
            raise ZXSyntaxError(f'the ROM rejected: {text}   (screen: {shown})')

    enter_wait = 250   # frames to let a line go in (and auto-LIST) after ENTER

    def wait_ready(self, max_frames=50 * 120, pause=False):
        """Run until the ROM wants the keyboard: the editor (after a command or
        program ends, or at INPUT), or with pause=True also PAUSE 0.  Returns
        the number of frames it took, or None if it never did."""
        start = self.frame
        ok = self.settle(max_frames=max_frames, pause=pause)
        return (self.frame - start) if ok else None

    def report(self):
        """The ROM's last report, e.g. '0 OK, 0:1', as read off the screen."""
        lines = [l for l in self.screen_text().split('\n') if l.strip()]
        return lines[-1].strip() if lines else ''

    # -- tapes ---------------------------------------------------------------
    def insert_tape(self, tap):
        """Put a TAP (path or bytes) in the tape deck.  LOAD reads it instantly
        through the LD-BYTES trap."""
        data = Path(tap).read_bytes() if not isinstance(tap, (bytes, bytearray)) else bytes(tap)
        self.lib.zx_tape_insert(self.z, data, len(data))

    def load_tap(self, tap, command='LOAD ""'):
        """Insert a tape, type LOAD "" and wait until it's done (or running)."""
        self.insert_tape(tap)
        self.type(command + '\n')
        return self.wait_ready(max_frames=50 * 10)

    def saved_tape(self, clear=False):
        n = self.lib.zx_tape_out_len(self.z)
        buf = (ctypes.c_uint8 * max(n, 1))()
        self.lib.zx_tape_out_get(self.z, buf)
        if clear:
            self.lib.zx_tape_out_clear(self.z)
        return bytes(buf[:n])

    # -- sound ---------------------------------------------------------------
    def record_ay(self, on=True):
        """(128) Start recording the AY: clears its register-write log and
        collects samples for a WAV until record_ay(False).  zxay.py reads both."""
        if on:
            self.lib.zx_ay_log_clear(self.z)
            self.lib.zx_ay_samples_clear(self.z)
        self.lib.zx_ay_record(self.z, 1 if on else 0)

    def record_audio(self, on=True):
        self.lib.zx_log_audio(self.z, 1 if on else 0)
        if on:
            self.lib.zx_audio_clear(self.z)
            self._audio_t0 = self.lib.zx_tstates(self.z)
            self._audio_level0 = self.lib.zx_ear(self.z)

    def beeper_notes(self, gap_s=0.03, tol=0.04, min_edges=6):
        """The beeper recording as notes: [(start_s, duration_s, Hz)].  Splits
        the edge train wherever it goes quiet (gap_s) or the half-period moves
        by more than tol (BEEPs run into each other with no gap)."""
        n = self.lib.zx_audio_len(self.z)
        buf = (ctypes.c_uint64 * max(n, 1))()
        self.lib.zx_audio_get(self.z, buf)
        edges = list(buf[:n])
        CLOCK = self.clock
        notes, cur = [], []
        for i in range(1, len(edges)):
            h = edges[i] - edges[i - 1]
            if h > gap_s * CLOCK:
                notes.append(cur)
                cur = []
                continue
            if cur:
                ref = sorted(x for _, x in cur[-8:])[len(cur[-8:]) // 2]
                if abs(h - ref) > tol * ref:
                    notes.append(cur)
                    cur = []
            cur.append((edges[i - 1], h))
        notes.append(cur)
        out = []
        for note in notes:
            if len(note) < min_edges:
                continue
            hs = sorted(h for _, h in note)
            half = hs[len(hs) // 2]
            t0, t1 = note[0][0], note[-1][0] + note[-1][1]
            out.append(((t0 - self._audio_t0) / CLOCK, (t1 - t0) / CLOCK, CLOCK / (2 * half)))
        return out

    def write_wav(self, path, rate=44100):
        """Beeper output since record_audio() as a mono 16-bit WAV."""
        import wave
        import array
        n = self.lib.zx_audio_len(self.z)
        buf = (ctypes.c_uint64 * max(n, 1))()
        self.lib.zx_audio_get(self.z, buf)
        edges = list(buf[:n])
        CLOCK = self.clock
        t0 = self._audio_t0
        t1 = self.lib.zx_tstates(self.z)
        nsamp = int((t1 - t0) * rate / CLOCK)
        level = self._audio_level0
        out = array.array('h', [0] * nsamp)
        ei = 0
        # box-filter each sample period for a little anti-aliasing
        step = CLOCK / rate
        prev_x = prev_y = 0.0
        for i in range(nsamp):
            a, b = t0 + i * step, t0 + (i + 1) * step
            acc, t = 0.0, a
            while ei < len(edges) and edges[ei] < b:
                if edges[ei] > t:
                    acc += (edges[ei] - t) * (1 if level else -1)
                    t = edges[ei]
                level ^= 1
                ei += 1
            acc += (b - t) * (1 if level else -1)
            x = acc / step
            y = x - prev_x + 0.995 * prev_y      # DC blocker: silence is silence
            prev_x, prev_y = x, y
            out[i] = max(-32000, min(32000, int(12000 * y)))
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(out.tobytes())
        return path, n


def write_gif(images, path, fps=25, scale=1):
    """Frames -> an animated GIF on the Spectrum's own 16 colours (Pillow keeps
    only the changed rectangle per frame, so these stay small)."""
    Image, _, _ = pil()
    pal = Image.new('P', (1, 1))
    pal.putpalette([c for rgb in PALETTE for c in rgb] + [0] * (768 - 48))
    frames = []
    for im in images:
        if scale != 1:
            im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
        frames.append(im.quantize(palette=pal, dither=Image.Dither.NONE))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0,
                   duration=round(1000 / fps), optimize=False, disposal=1)
    return path


_FONTS = ['/System/Library/Fonts/Menlo.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
          '/usr/share/fonts/TTF/DejaVuSansMono.ttf', 'C:/Windows/Fonts/consola.ttf', 'DejaVuSansMono.ttf']


def label_font(size):
    """A monospaced font for labels: the first that exists, else Pillow's own."""
    _, _, ImageFont = pil()
    for f in _FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:                 # Pillow before 10.1
        return ImageFont.load_default()


def contact_sheet(frames, path, cols=4, scale=1, title=None, preview=960):
    """Grid of (label, image) with labels under each; writes PNG and a
    `_960.jpg` preview.  Returns the preview path."""
    Image, ImageDraw, _ = pil()
    if not frames:
        raise ValueError('no frames to put on a sheet')
    w0, h0 = frames[0][1].size
    w, h = w0 * scale, h0 * scale
    pad, lab = 8, 18
    top = 26 if title else 0
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new('RGB', (pad + cols * (w + pad), top + pad + rows * (h + lab + pad)), (40, 38, 36))
    d = ImageDraw.Draw(sheet)
    font, tfont = label_font(13), label_font(16)
    if title:
        d.text((pad, 5), title, fill=(235, 225, 205), font=tfont)
    for i, (label, im) in enumerate(frames):
        r, c = divmod(i, cols)
        x, y = pad + c * (w + pad), top + pad + r * (h + lab + pad)
        if scale != 1:
            im = im.resize((w, h), Image.NEAREST)
        sheet.paste(im, (x, y))
        d.text((x + 2, y + h + 2), label, fill=(210, 200, 180), font=font)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path.with_suffix('.png'))
    prev = path.with_name(path.stem + f'_{preview}.jpg')
    ratio = preview / sheet.width
    small = sheet if ratio >= 1 else sheet.resize((preview, round(sheet.height * ratio)), Image.LANCZOS)
    small.save(prev, quality=88)
    return prev


if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    from zxscript import main
    sys.exit(main(sys.argv[1:]))
