"""next.py: a Spectrum Next (core 3.02.02) for Python, over nextcore.cpp. The contract is next-build/DESIGN.md §9
(and §9.1): what the tests drive and the core implements.

Ratio Fern, Fri 6 Nov 2026, for omse-ai's Next (led by Tally Fern). Units: `t28` is 28 MHz master ticks since
power-on; `cpu_clocks` is rising edges of the CPU clock since power-on (a 28 MHz wait state is one; contention adds
none).

    from next import Next
    zx = Next(timing='p3', hz=50, speed=0, boot='bare')

Layer 1 so far: the clock, the counters, the ULA interrupt (pulse mode), memory and the MMU, the Next registers,
ports 0x243B/0x253B, the logs. boot='fast' comes with a later layer.
"""
import ctypes
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB_PATH = HERE / 'lib' / ('libzxcore.dylib' if sys.platform == 'darwin' else 'libzxcore.so')
SOURCES = [HERE / 'src' / f for f in ('zxcore.cpp', 'nextcore.cpp', 'nextregs_reset.inc', 'z80.h',
                                      'ay38910.h', 'sdcard.h')]
TIMINGS = {'48k': 1, '128k': 2, 'p3': 3, 'pentagon': 4}
REG_NAMES = ['pc', 'sp', 'af', 'bc', 'de', 'hl', 'ix', 'iy', "af'", "bc'", "de'", "hl'", 'ir', 'im', 'iff1', 'iff2']

_lib = None


def _load_lib():
    global _lib
    if _lib is not None:
        return _lib
    newest = max(f.stat().st_mtime for f in SOURCES if f.exists())
    if not LIB_PATH.exists() or LIB_PATH.stat().st_mtime < newest:
        r = subprocess.run(['make', '-s', '-C', str(HERE)], capture_output=True, text=True)
        if r.returncode != 0 or not LIB_PATH.exists():
            raise RuntimeError(f'could not build {LIB_PATH.name} with make in {HERE}:\n{r.stdout}{r.stderr}')
    lib = ctypes.CDLL(str(LIB_PATH))
    P, I, U64, U8P = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint8)
    U64P, U16P = ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint16)
    sigs = {
        'zxn_new': ([I, I, I, I], P), 'zxn_free': ([P], None), 'zxn_reset': ([P, I], None),
        'zxn_contention': ([P, I], None),
        'zxn_set_bootrom': ([P, ctypes.c_char_p, I], None),
        'zxn_t28': ([P], U64), 'zxn_cpu_clocks': ([P], U64), 'zxn_frame': ([P], U64),
        'zxn_hc_ula': ([P], I), 'zxn_vc_ula': ([P], I), 'zxn_hc': ([P], I), 'zxn_vc': ([P], I),
        'zxn_speed': ([P], I),
        'zxn_run_ticks': ([P, U64], None), 'zxn_run_until_pc': ([P, I, I, U64], I), 'zxn_run_frames': ([P, I], None),
        'zxn_regs': ([P, U16P], None), 'zxn_set_reg': ([P, I, I], None),
        'zxn_peek': ([P, I], I), 'zxn_poke': ([P, I, I, I], None),
        'zxn_sram': ([P], P), 'zxn_bram5': ([P], P), 'zxn_bram7': ([P], P), 'zxn_slot_page': ([P, I], I),
        'zxn_slot_desc': ([P, I, I, ctypes.POINTER(ctypes.c_int)], None),
        'zxn_nr_read': ([P, I], I), 'zxn_nr_write': ([P, I, I], None),
        'zxn_io_in': ([P, I], I), 'zxn_io_out': ([P, I, I], None),
        'zxn_set_keys': ([P, ctypes.c_char_p], None), 'zxn_border': ([P], I),
        'zxn_framebuffer': ([P], P), 'zxn_fb_width': ([], I), 'zxn_fb_height': ([], I),
        'zxn_sd_insert': ([P, ctypes.c_char_p, I, I], I), 'zxn_sd_eject': ([P], None), 'zxn_spi_state': ([P], I), 'zxn_spi_count': ([P], U64),
        'zxn_int_log_len': ([P], I), 'zxn_int_log_get': ([P, I, U64P], None),
        'zxn_io_logging': ([P, I], None), 'zxn_io_log_len': ([P], I), 'zxn_io_log_get': ([P, I, U64P], None),
    }
    for name, (args, res) in sigs.items():
        f = getattr(lib, name)
        f.argtypes = args
        f.restype = res
    _lib = lib
    return lib


class Next:
    """One Spectrum Next. boot='bare' is the power-on state (config mode, the boot ROM's area reading 0xFF unless
    boot_rom= gives bytes); timing/hz/speed are in effect from the start (DESIGN.md §9.1 (1))."""

    def __init__(self, timing='p3', hz=50, speed=0, boot='bare', boot_rom=None, issue=4):
        if boot != 'bare':
            raise NotImplementedError("boot='fast' comes with a later layer")
        if timing not in TIMINGS:
            raise ValueError(f'timing must be one of {sorted(TIMINGS)}')
        self.lib = _load_lib()
        self.z = self.lib.zxn_new(TIMINGS[timing], 1 if hz == 60 else 0, speed & 3, issue)
        if boot_rom is not None:
            self.lib.zxn_set_bootrom(self.z, bytes(boot_rom), len(boot_rom))
        self.sram = (ctypes.c_uint8 * (2 << 20)).from_address(self.lib.zxn_sram(self.z))
        self.bram5 = (ctypes.c_uint8 * 16384).from_address(self.lib.zxn_bram5(self.z))
        self.bram7 = (ctypes.c_uint8 * 8192).from_address(self.lib.zxn_bram7(self.z))

    def __del__(self):
        if getattr(self, 'z', None):
            self.lib.zxn_free(self.z)
            self.z = None

    def reset(self, hard=False):
        self.lib.zxn_reset(self.z, 1 if hard else 0)

    def contention(self, on=True):
        """Contention is on, as the hardware is; off is for comparisons only."""
        self.lib.zxn_contention(self.z, 1 if on else 0)

    # time and the beam
    t28 = property(lambda self: self.lib.zxn_t28(self.z))
    cpu_clocks = property(lambda self: self.lib.zxn_cpu_clocks(self.z))
    frame = property(lambda self: self.lib.zxn_frame(self.z))
    hc_ula = property(lambda self: self.lib.zxn_hc_ula(self.z))
    vc_ula = property(lambda self: self.lib.zxn_vc_ula(self.z))
    speed = property(lambda self: self.lib.zxn_speed(self.z))

    def run_ticks(self, n):
        self.lib.zxn_run_ticks(self.z, n)

    def run_until_pc(self, lo, hi=None, max_ticks=200_000_000):
        return bool(self.lib.zxn_run_until_pc(self.z, lo, lo if hi is None else hi, max_ticks))

    def run_frames(self, n):
        self.lib.zxn_run_frames(self.z, n)

    # the CPU
    def regs(self):
        buf = (ctypes.c_uint16 * 16)()
        self.lib.zxn_regs(self.z, buf)
        return dict(zip(REG_NAMES, list(buf)))

    def set_regs(self, **kw):
        for k, v in kw.items():
            name = {'af_': "af'", 'bc_': "bc'", 'de_': "de'", 'hl_': "hl'"}.get(k, k)
            self.lib.zxn_set_reg(self.z, REG_NAMES.index(name), v)

    def load(self, addr, data):
        for i, b in enumerate(data):
            self.lib.zxn_poke(self.z, (addr + i) & 0xFFFF, b, 0)

    # memory, through the CPU's map, with no side effects
    def peek(self, a):
        return self.lib.zxn_peek(self.z, a & 0xFFFF)

    def read(self, a, n):
        return bytes(self.peek(a + i) for i in range(n))

    def poke(self, a, v, force=False):
        self.lib.zxn_poke(self.z, a & 0xFFFF, v & 0xFF, 1 if force else 0)

    def write(self, a, data, force=False):
        for i, b in enumerate(data):
            self.poke(a + i, b, force)

    def slot_page(self, i, write=False):
        """What MMU slot i (0-7) shows to reads, or with write=True where a write lands (DESIGN.md §9.1 (8)): a plain
        page number 0x00-0xDF, or ('rom', n), ('altrom', n), 'boot', ('config', p16), 'divmmc-rom', ('divmmc', bank),
        'mf-rom', 'mf-ram', ('l2', page), or None for no memory."""
        out = (ctypes.c_int * 2)()
        self.lib.zxn_slot_desc(self.z, i, 1 if write else 0, out)
        tag, val = out[0], out[1]
        return [val, ('rom', val), ('altrom', val), 'boot', ('config', val), 'divmmc-rom', ('divmmc', val),
                'mf-rom', 'mf-ram', ('l2', val), None][tag]

    def mmu(self, i):
        """The MMU register for slot i (NR 0x50 + i), whatever overrides it."""
        return self.lib.zxn_slot_page(self.z, i)

    # registers and ports, as the CPU sees them (side effects included), taking no time
    def nr_read(self, n):
        return self.lib.zxn_nr_read(self.z, n)

    def nr_write(self, n, v):
        self.lib.zxn_nr_write(self.z, n, v)

    def io_in(self, port):
        return self.lib.zxn_io_in(self.z, port)

    def io_out(self, port, v):
        self.lib.zxn_io_out(self.z, port, v)

    # the keyboard and the border
    def set_keys(self, rows):
        """The keyboard matrix: 8 half-row bytes (row r is read with A8+r low; bit set = key down)."""
        self.lib.zxn_set_keys(self.z, bytes(rows))

    border = property(lambda self: self.lib.zxn_border(self.z))

    # the picture: the ULA's screen as drawn at the beam (352 x 288 at 7 MHz, indexed 0-15)
    PALETTE = [(0, 0, 0), (0, 0, 0xD7), (0xD7, 0, 0), (0xD7, 0, 0xD7), (0, 0xD7, 0), (0, 0xD7, 0xD7), (0xD7, 0xD7, 0),
               (0xD7, 0xD7, 0xD7), (0, 0, 0), (0, 0, 0xFF), (0xFF, 0, 0), (0xFF, 0, 0xFF), (0, 0xFF, 0), (0, 0xFF, 0xFF),
               (0xFF, 0xFF, 0), (0xFF, 0xFF, 0xFF)]

    def framebuffer(self):
        w, h = self.lib.zxn_fb_width(), self.lib.zxn_fb_height()
        return w, h, bytes((ctypes.c_uint8 * (w * h)).from_address(self.lib.zxn_framebuffer(self.z)))

    def image(self, path=None, scale=2):
        """The screen as a PIL image (scaled), saved to path if given."""
        from PIL import Image
        w, h, data = self.framebuffer()
        im = Image.frombytes('P', (w, h), data)
        im.putpalette([c for rgb in self.PALETTE for c in rgb])
        im = im.convert('RGB').resize((w * scale, h * scale), Image.NEAREST)
        if path:
            im.save(path)
        return im

    # the SD card on the SPI master's card-select 0
    def sd_insert(self, path, writable=False, kind=1):
        return self.lib.zxn_sd_insert(self.z, str(path).encode(), 1 if writable else 0, kind)

    def sd_eject(self):
        self.lib.zxn_sd_eject(self.z)

    spi_state = property(lambda self: self.lib.zxn_spi_state(self.z))
    spi_count = property(lambda self: self.lib.zxn_spi_count(self.z))

    # logs
    @property
    def int_log(self):
        out = (ctypes.c_uint64 * 2)()
        res = []
        for i in range(self.lib.zxn_int_log_len(self.z)):
            self.lib.zxn_int_log_get(self.z, i, out)
            res.append((out[0], out[1]))
        return res

    def io_log(self, on=True):
        self.lib.zxn_io_logging(self.z, 1 if on else 0)

    @property
    def io_events(self):
        out = (ctypes.c_uint64 * 5)()
        res = []
        for i in range(self.lib.zxn_io_log_len(self.z)):
            self.lib.zxn_io_log_get(self.z, i, out)
            res.append((out[0], out[1], out[2], out[3], 'w' if out[4] else 'r'))
        return res
