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
import os
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
        'zxn_sd_insert': ([P, ctypes.c_char_p, I, I], I), 'zxn_sd_eject': ([P], None), 'zxn_frame9': ([P, I], ctypes.c_void_p), 'zxn_f9_width': ([], I), 'zxn_button': ([P, I], None), 'zxn_set_joy': ([P, I, I], None), 'zxn_set_mouse': ([P, I, I, I, I], None), 'zxn_uart_feed': ([P, I, ctypes.c_char_p, I, U64, I, I, I], None), 'zxn_uart_sent_len': ([P, I], I), 'zxn_uart_sent_get': ([P, I, I, U64P], None), 'zxn_uart_sent_clear': ([P, I], None), 'zxn_uart_cts': ([P, I, I], None), 'zxn_uart_feed_levels': ([P, I, ctypes.c_char_p, U64P, I], None), 'zxn_uart_tx_logging': ([P, I, I], None), 'zxn_uart_tx_log_len': ([P, I], I), 'zxn_uart_tx_log_get': ([P, I, I, U64P], None), 'zxn_uart_rts': ([P, I], I), 'zxn_i2c_rtc': ([P, I, I, I, I, I, I, I, I], None), 'zxn_i2c_logging': ([P, I], None), 'zxn_i2c_log_len': ([P], I), 'zxn_i2c_log_get': ([P, I, U64P], None), 'zxn_cvc': ([P], I), 'zxn_sd_timing': ([P, I, I, I, I], None), 'zxn_spi_state': ([P], I), 'zxn_spi_count': ([P], U64),
        'zxn_int_log_len': ([P], I), 'zxn_int_log_get': ([P, I, U64P], None),
        'zxn_io_logging': ([P, I], None), 'zxn_io_log_len': ([P], I), 'zxn_io_log_get': ([P, I, U64P], None),
        'zxn_audio_capture': ([P, I], None), 'zxn_audio_take': ([P, U16P, I], I), 'zxn_audio_cap_len': ([P], I),
        'zxn_audio_rate': ([P, I], None), 'zxn_audio_out_len': ([P], I),
        'zxn_audio_out': ([P, ctypes.POINTER(ctypes.c_int16), I], I),
        'zxn_audio_level': ([P, ctypes.POINTER(ctypes.c_int)], None),
        'zxn_ay_chan': ([P, I, ctypes.POINTER(ctypes.c_int)], None), 'zxn_ay_env': ([P, I], I),
    }
    for name, (args, res) in sigs.items():
        f = getattr(lib, name)
        f.argtypes = args
        f.restype = res
    _lib = lib
    return lib


# ---- boot='fast': what the Next's firmware does between its menu and the soft reset (NEXT-MACHINE.md §7.2 steps 4-7),
# from the distribution's own files, read at run time and never shipped: MENU.DEF's line for the machine, CONFIG.INI's
# settings, and the ROM images. The arithmetic is the firmware's (tbblue/src/firmware/app/src/boot.c: load_roms 86-176,
# init_registers 279-407, the handover 548-598; settings and defaults config.c 25-124).

# CONFIG.INI's keys, in the firmware's order, with its defaults (config.c 93-124)
NEXT_SETTINGS = dict(scandoubler=1, **{'50_60hz': 0}, timex=1, psgmode=1, intsnd=1, stereomode=0, turbosound=1,
                     divmmc=0, mf=0, joystick1=1, joystick2=3, ps2=1, dma=0, scanlines=0, turbokey=1, default=0,
                     timing=8, keyb_issue=0, divports=1, dac=1, ay48=0, uart_i2c=1, kmouse=1, ulaplus=1, hdmisound=1,
                     beepmode=0, buttonswap=0, mousedpi=1, espreset=0)
# Each timing's personality: MENU.DEF's first line of that mode (mode 0 48K, 1 128K, 2 +3, 3 Pentagon)
NEXT_MENU = {'p3': 'ZX Spectrum Next (standard)', '48k': 'ZX Spectrum 48K', '128k': 'ZX Spectrum 128k',
             'pentagon': 'Pentagon 128K'}


def next_roms_dir(roms=None):
    """The distribution's machines/next folder: roms=, else $OMSE_AI_NEXT_ROMS."""
    d = roms or os.environ.get('OMSE_AI_NEXT_ROMS')
    if not d or not os.path.isfile(_ci(d, 'MENU.DEF') or ''):
        raise FileNotFoundError("boot='fast' needs the Next's distribution: pass roms= or set OMSE_AI_NEXT_ROMS to its "
                                "machines/next folder (with MENU.DEF, CONFIG.INI and the ROMs)")
    return d


def _ci(d, name):
    """A file in d, matched without regard to case (the SD card's FAT doesn't care; MENU.DEF says enNextMF.rom)."""
    if not os.path.isdir(d):
        return None
    for f in os.listdir(d):
        if f.lower() == name.lower():
            return os.path.join(d, f)
    return None


def next_settings(d, **override):
    """CONFIG.INI's settings over the firmware's defaults, then any overrides."""
    st = dict(NEXT_SETTINGS)
    path = _ci(d, 'CONFIG.INI')
    if path:
        for line in open(path, encoding='latin-1'):
            k, eq, v = line.strip().partition('=')
            if eq and k in st and v.strip().isdigit():
                st[k] = int(v)
    st.update(override)
    return st


def next_menu(d, title):
    """MENU.DEF's line by title: (mode, rom, divmmc_rom, mf_rom); '' for a ROM not named, None for <none>."""
    for line in open(_ci(d, 'MENU.DEF'), encoding='latin-1'):
        if line.startswith('menu='):
            f = [x.strip() for x in line[5:].strip().split(',')]
            if f[0] == title:
                f += [''] * 6
                none = lambda x: None if x.startswith('<none>') else x
                return int(f[1]), f[3], none(f[4]), none(f[5])
    raise ValueError(f'MENU.DEF has no line {title!r}')


def next_firmware_state(mode, st, divmmc_rom, mf_rom):
    """The registers the firmware writes, as (reg, value) in its order, and the multiface type (boot.c 86-176, 279-407,
    548-573: a ROM named on the menu line forces divMMC or the multiface on; <none> forces it off)."""
    st = dict(st)
    if mf_rom is None: st['mf'] = 0
    elif mf_rom: st['mf'] = 1
    if divmmc_rom is None: st['divmmc'] = 0
    elif divmmc_rom: st['divmmc'] = 1
    mftype = 0
    if st['mf']:
        mftype = {0: 3, 1: 1, 2: 0, 3: 1}[mode]
        if mf_rom and mf_rom.lower().startswith(('mf128v1', 'mf128v12')): mftype = 2   # MF128 87.1 / 87.12
    j1, j2 = st['joystick1'], st['joystick2']
    nr05 = (j1 & 3) << 6 | (j2 & 3) << 4 | (8 if j1 & 4 else 0) | (4 if st['50_60hz'] else 0) | \
        (2 if j2 & 4 else 0) | (1 if st['scandoubler'] else 0)
    nr06 = (st['psgmode'] & 3) | (0x80 if st['turbokey'] else 0) | (0x40 if st['beepmode'] else 0) | \
        (0x10 if st['divmmc'] else 0) | (0x08 if st['mf'] else 0) | (0x04 if st['ps2'] else 0)
    nr08 = (0x20 if st['stereomode'] else 0) | (0x10 if st['intsnd'] else 0) | (0x08 if st['dac'] else 0) | \
        (0x04 if st['timex'] else 0) | (0x02 if st['turbosound'] else 0) | (0x01 if st['keyb_issue'] else 0)
    nr09 = (st['scanlines'] & 3) | (0 if st['hdmisound'] else 0x04)
    nr0a = (st['mousedpi'] & 3) | (0x08 if st['buttonswap'] else 0) | (0x10 if st['divmmc'] else 0) | mftype << 6
    hw3 = (1 if st['ulaplus'] else 0) | (2 if st['dma'] else 0)          # bit 7 = 0: kept through soft resets
    hw2 = 0xFF if st['dac'] else 0x01
    hw1 = (0x09 if st['divports'] else 0) | (0x02 if st['mf'] else 0) | (0x14 if st['uart_i2c'] else 0) | \
        (0x20 if st['kmouse'] else 0)
    hw0 = {0: 0xC0, 1: 0xC2, 2: 0xDA, 3: 0xC6}[mode]
    if mode == 0 and not st['ay48']: hw2 &= 0xFE
    if mode == 3: hw2 &= 0xFB
    regs = [(0x05, nr05), (0x06, nr06), (0x08, nr08), (0x09, nr09), (0x0A, nr0a),
            (0x82, hw0), (0x83, hw1), (0x84, hw2), (0x85, hw3)]
    return regs, st


class Next:
    """One Spectrum Next. boot='bare' is the power-on state (config mode, the boot ROM's area reading 0xFF unless
    boot_rom= gives bytes); timing/hz/speed are in effect from the start (DESIGN.md §9.1 (1))."""

    def __init__(self, timing='p3', hz=None, speed=0, boot='bare', boot_rom=None, issue=4, roms=None, settings=None,
                 palette=None):
        """boot='fast' (NEXT-MACHINE.md §7.4 (2)): the firmware's work for timing's personality on MENU.DEF (p3: ZX
        Spectrum Next (standard); 48k, 128k, pentagon: those machines), with the distribution's CONFIG.INI (roms=, or
        $OMSE_AI_NEXT_ROMS, names its machines/next folder) and settings= (a dict of CONFIG.INI keys) over it, then the
        soft reset: the CPU is at 0 in the chosen ROM. hz= overrides CONFIG.INI's 50_60hz, speed= the 3.5 MHz the soft
        reset leaves."""
        if boot not in ('bare', 'fast'):
            raise ValueError("boot is 'bare' or 'fast'")
        if timing not in TIMINGS:
            raise ValueError(f'timing must be one of {sorted(TIMINGS)}')
        if boot == 'fast':
            d = next_roms_dir(roms)
            mode, rom, div_rom, mf_rom = next_menu(d, NEXT_MENU[timing])
            over = dict(settings or {})
            if hz is not None:
                over['50_60hz'] = 1 if hz == 60 else 0
            regs, st = next_firmware_state(mode, next_settings(d, **over), div_rom, mf_rom)
            hz = 60 if st['50_60hz'] else 50
        self.lib = _load_lib()
        # (fast: the timing and Hz are in effect from the start, as they are by the firmware's pause before its soft
        # reset, which spans several frame syncs; boot.c 584-585)
        self.z = self.lib.zxn_new(TIMINGS[timing], 1 if hz == 60 else 0, 0 if boot == 'fast' else speed & 3, issue)
        if boot_rom is not None:
            self.lib.zxn_set_bootrom(self.z, bytes(boot_rom), len(boot_rom))
        self.sram = (ctypes.c_uint8 * (2 << 20)).from_address(self.lib.zxn_sram(self.z))
        self.bram5 = (ctypes.c_uint8 * 16384).from_address(self.lib.zxn_bram5(self.z))
        self.bram7 = (ctypes.c_uint8 * 8192).from_address(self.lib.zxn_bram7(self.z))
        if boot == 'bare' and palette == 'loader':     # power-on with the loader's palettes, for pictures (§9.1 (13))
            self._loader_palette()
            self.nr_write(0x43, 0x00)                  # (the soft reset would clear it; keep the power-on registers)
            self.nr_write(0x40, 0x00)
        if boot == 'fast':
            self._fast_boot(d, mode, rom, div_rom, mf_rom, regs, st)
            if speed:
                self.nr_write(0x07, speed & 3)

    LOADER_COLOURS = [0x00, 0x02, 0xA0, 0xA2, 0x14, 0x16, 0xB4, 0xB6, 0x00, 0x03, 0xE0, 0xE7, 0x1C, 0x1F, 0xFC, 0xFF]

    def _loader_palette(self):
        """What the boot ROM's loader writes before anything else runs (fw/loader/src/vdp.c vdp_init): the ULA's
        first palette, inks 0-127 and papers 128-255 in repeating 16-colour blocks; Layer 2's and the sprites' first
        palettes ordered. It leaves NR 0x43 at 0x20."""
        for base in (0, 128):
            self.nr_write(0x40, base)
            for _ in range(8):
                for c in self.LOADER_COLOURS:
                    self.nr_write(0x41, c)
        for sel in (0x10, 0x20):
            self.nr_write(0x43, sel)
            self.nr_write(0x40, 0)
            for c in range(256):
                self.nr_write(0x41, c)

    def _fast_boot(self, d, mode, rom, div_rom, mf_rom, regs, st):
        def load(name, page16, blocks, blocklen):     # through NR 0x04's window in the firmware; straight in here
            path = _ci(d, name)
            if not path:
                raise FileNotFoundError(f"boot='fast' wants {name} in {d}")
            data = open(path, 'rb').read()
            for b in range(blocks):
                chunk = data[b * blocklen:(b + 1) * blocklen]
                if len(chunk) != blocklen:
                    raise ValueError(f'{name} is too short for {blocks} block(s) of {blocklen}')
                self.sram[(page16 + b) * 16384:(page16 + b) * 16384 + blocklen] = chunk
        self._loader_palette()                         # the boot ROM's loader runs first (§9.1 (13))
        self.nr_write(0x07, 3)                         # the firmware's start: 28 MHz, NR 0x06 = 0xA0, the boot ROM off
        self.nr_write(0x06, 0xA0)                      # (boot.c 445-460; NR 0x03 = 0 stays in config mode)
        self.nr_write(0x03, 0x00)
        if st['divmmc']:                               # load_roms (boot.c 86-176): divMMC 8K to 16K page 4,
            load(div_rom or 'esxmmc.bin', 4, 1, 8192)  # the multiface 8K to page 5, the ROM to pages 0-3
        if st['mf']:
            load(mf_rom or {0: 'mf1.rom', 1: 'mf128.rom', 2: 'mf3.rom', 3: 'mf128.rom'}[mode], 5, 1, 8192)
        load(rom, 0, {0: 1, 2: 4}.get(mode, 2), 16384)
        for reg, v in regs:                            # init_registers (boot.c 279-407)
            self.nr_write(reg, v)
        self.nr_write(0x03, 0x80 | (mode + 1) << 4 | (mode + 1))   # the handover (boot.c 581-598)
        self.nr_write(0x02, 0x01)

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
    cvc = property(lambda self: self.lib.zxn_cvc(self.z))         # the ULA line + NR 0x64's offset
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
        r = dict(zip(REG_NAMES, list(buf)))
        r['i'], r['r'] = r['ir'] >> 8, r['ir'] & 0xFF
        return r

    def set_regs(self, **kw):
        for k, v in kw.items():
            if k in ('i', 'r'):                                       # halves of ir
                ir = self.regs()['ir']
                v, k = (v << 8 | ir & 0xFF) if k == 'i' else (ir & 0xFF00 | v & 0xFF), 'ir'
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
        'mf-rom', 'mf-ram', ('l2', page), or None for no memory. ('altrom', n): n 0 is the 128K alternate ROM (SRAM
        0x18000), 1 the 48K one (0x1C000), as the VHDL's alt_128_n."""
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

    def frame9(self, blank=True):
        """The visible area as 9-bit RRRGGGBBB colours (0-511), (w, h, values) with w = 704 14 MHz samples, two per
        7 MHz pixel, and h = 288; the ULA's paper pixel (px, py) is samples (96 + 2px, 48 + py) and (97 + 2px, 48 + py)
        (DESIGN.md §9.1 (12)). As output, black while blanking; blank=False gives the mixer's colour before it
        (§9.1 (14))."""
        w, h = self.lib.zxn_f9_width(), self.lib.zxn_fb_height()
        return w, h, list((ctypes.c_uint16 * (w * h)).from_address(self.lib.zxn_frame9(self.z, 1 if blank else 0)))

    def image(self, path=None, scale=2):
        """The screen as a PIL image (scaled), saved to path if given: frame9's colours, 3 bits to 8 as the Next's
        video output widens them."""
        from PIL import Image
        w, h, f9 = self.frame9()
        e = lambda v: v << 5 | v << 2 | v >> 1
        rgb = bytes(c for v in f9 for c in (e(v >> 6), e((v >> 3) & 7), e(v & 7)))
        im = Image.frombytes('RGB', (w, h), rgb).resize((w // 2 * scale, h * scale), Image.NEAREST)
        if path:
            im.save(path)
        return im

    # the SD card on the SPI master's card-select 0
    SD_KINDS = ('sdhc', 'sdsc', 'sdv1', 'mmc')     # as speccy.py, in sdcard.h's order

    def sd_insert(self, path, writable=False, kind='sdhc'):
        """Put an SD-card image in the slot (card 0), as speccy.py's sd_insert:
        kind 'sdhc' (block-addressed, the default), 'sdsc', 'sdv1' or 'mmc'.
        Returns 0 on success."""
        if kind not in self.SD_KINDS:
            raise ValueError(f'an SD card is one of {", ".join(self.SD_KINDS)}, not {kind!r}')
        return self.lib.zxn_sd_insert(self.z, str(path).encode(), 1 if writable else 0,
                                      self.SD_KINDS.index(kind))

    def button(self, which):
        """Press the Next's M1 (multiface NMI, needs NR 0x06 b3) or DRIVE (divMMC NMI, needs b4) button: 'm1' or 'drive'."""
        self.lib.zxn_button(self.z, {'m1': 1, 'drive': 2}[which])

    def set_joy(self, left=0, right=0):
        """The two joysticks, a bit per control pressed: R L D U B C A START Y Z X in bits 0-10 (zxnext:3398-3400).
        Kempston reads bits 5:0 (fire, up, down, left, right), MD adds 7:6."""
        self.lib.zxn_set_joy(self.z, left, right)

    # ---- the UARTs and I2C (DESIGN.md §9.1 (18)): the host is each UART's far end, and the DS1307 is optional
    def uart_feed(self, n, data, bit_t28, frame='8N1'):
        """Send data into UART n's Rx pin from now (after any earlier feed, back to back), each bit bit_t28 master
        ticks: start bit, data LSB first, parity if any, stop bits. frame: data bits (5-8), parity N/O/E, stop bits (1-2).
        UART 1's line reaches it only while NR 0xA0 b4 enables the Pi UART; under NR 0x0B's joystick mode neither."""
        data = bytes(data)
        self.lib.zxn_uart_feed(self.z, n, data, len(data), bit_t28, int(frame[0]), {'N': 0, 'O': 1, 'E': 2}[frame[1].upper()],
                               int(frame[2]))

    def uart_feed_levels(self, n, segments):
        """Raw levels on the host's sending wire into UART n: [(level, ticks), ...], after any earlier feed, back to
        back; the wire idles at 1 again after the last (§9.1 (18) i)."""
        levels = bytes(1 if lv else 0 for lv, _ in segments)
        ticks = (ctypes.c_uint64 * len(segments))(*[t for _, t in segments])
        self.lib.zxn_uart_feed_levels(self.z, n, levels, ticks, len(segments))

    def uart_tx_log(self, n, on=True):
        """Log the host's receiving wire for UART n: [(t28, level)] at each change, after the gating and routing,
        an undriven wire idle 1 (zx.uart_tx_events(n); §9.1 (18) i). Turning it off clears the log."""
        self.lib.zxn_uart_tx_logging(self.z, n, 1 if on else 0)

    def uart_tx_events(self, n):
        out = (ctypes.c_uint64 * 2)()
        res = []
        for i in range(self.lib.zxn_uart_tx_log_len(self.z, n)):
            self.lib.zxn_uart_tx_log_get(self.z, n, i, out)
            res.append((out[0], bool(out[1])))
        return res

    def uart_sent(self, n):
        """Every byte UART n put on its Tx pin since the last call, as [(t28, byte)], t28 the tick its start bit's
        falling edge began; then clears them. Nothing for UART 1 without the Pi UART, or for a UART on a joystick port."""
        out = (ctypes.c_uint64 * 2)()
        res = []
        for i in range(self.lib.zxn_uart_sent_len(self.z, n)):
            self.lib.zxn_uart_sent_get(self.z, n, i, out)
            res.append((out[0], out[1]))
        self.lib.zxn_uart_sent_clear(self.z, n)
        return res

    def uart_cts(self, n, level=True):
        """The host's CTS into UART n: True is clear to send (the default)."""
        self.lib.zxn_uart_cts(self.z, n, 1 if level else 0)

    def uart_rts(self, n):
        """UART n's RTS as the host sees it: True ready to receive, False not, None when the pin isn't driven toward
        the host (UART 1 without the Pi UART and hardware flow control, or a UART on a joystick port)."""
        v = self.lib.zxn_uart_rts(self.z, n)
        return None if v < 0 else bool(v)

    def i2c_rtc(self, datetime=None):
        """Attach the DS1307 at 0x68 running from datetime (the host's now if None, 24-hour mode, day 1 = Sunday), or
        detach it with False. None is attached by default. It keeps real seconds of the machine's time from then."""
        if datetime is False:
            self.lib.zxn_i2c_rtc(self.z, 0, 0, 0, 0, 0, 0, 0, 0)
            return
        import datetime as _dt
        d = datetime or _dt.datetime.now()
        self.lib.zxn_i2c_rtc(self.z, 1, d.second, d.minute, d.hour, d.isoweekday() % 7 + 1, d.day, d.month, d.year % 100)

    def i2c_log(self, on=True):
        """Log the I2C bus: [(t28, scl, sda)] at each change of either line as the bus sees it (zx.i2c_events)."""
        self.lib.zxn_i2c_logging(self.z, 1 if on else 0)

    @property
    def i2c_events(self):
        out = (ctypes.c_uint64 * 3)()
        res = []
        for i in range(self.lib.zxn_i2c_log_len(self.z)):
            self.lib.zxn_i2c_log_get(self.z, i, out)
            res.append((out[0], out[1], out[2]))
        return res

    def set_mouse(self, x=0, y=0, buttons=0, wheel=0):
        """The Kempston mouse: X and Y counts (0-255, as the PS/2 side accumulates them), buttons b0 left, b1 right,
        b2 middle, and the wheel's 4-bit count. Ports xBDF, xFDF and xADF read them (zxnext:3496-3520)."""
        self.lib.zxn_set_mouse(self.z, x, y, buttons, wheel)

    def sd_eject(self):
        self.lib.zxn_sd_eject(self.z)

    def sd_timing(self, ncr=1, nac=3, busy=2, init_tries=2):
        """The card's delays, in SPI bytes, as speccy.py's: before a response (N_CR, 0-8 on a real SD card), before
        a data block (N_AC), busy after a write; and how many ACMD41s it takes to leave the idle state."""
        self.lib.zxn_sd_timing(self.z, ncr, nac, busy, init_tries)

    spi_state = property(lambda self: self.lib.zxn_spi_state(self.z))
    spi_count = property(lambda self: self.lib.zxn_spi_count(self.z))

    # logs
    @property
    def int_log(self):
        out = (ctypes.c_uint64 * 2)()
        res = []
        for i in range(self.lib.zxn_int_log_len(self.z)):
            self.lib.zxn_int_log_get(self.z, i, out)
            res.append((out[0], out[1] or None))           # None: still low (§9.1 (4))
        return res

    # the sound (src/next_audio.h, Slide Fern): the mixer's output at every 1.75 MHz enable, 13 bits a side (0-5998),
    # as audio_mixer.vhd makes it; or resampled (a box filter) to a rate, scaled to 0-29990
    def audio_capture(self, on=True):
        """Start (or stop) keeping the mixer's (L, R) at every enable, for audio_take()."""
        self.lib.zxn_audio_capture(self.z, 1 if on else 0)

    def audio_take(self):
        """The captured enables since the last take: an int32 array of shape (n, 2), (L, R) each 0-5998."""
        import numpy as np
        n = self.lib.zxn_audio_cap_len(self.z)
        buf = (ctypes.c_uint16 * max(n, 1))()
        n = self.lib.zxn_audio_take(self.z, buf, n)
        return np.frombuffer(buf, np.uint16, n).reshape(-1, 2).astype(np.int32)

    def audio(self, rate=48000):
        """Stereo audio since the last call at `rate` (the first call at a rate starts it): int16, shape (n, 2)."""
        import numpy as np
        self.lib.zxn_audio_rate(self.z, rate)
        n = self.lib.zxn_audio_out_len(self.z)
        buf = (ctypes.c_int16 * max(n, 1))()
        n = self.lib.zxn_audio_out(self.z, buf, n)
        return np.frombuffer(buf, np.int16, n).reshape(-1, 2).copy()

    def audio_level(self):
        """The mixer's (L, R) now, 0-5998 each."""
        out = (ctypes.c_int * 2)()
        self.lib.zxn_audio_level(self.z, out)
        return out[0], out[1]

    def ay_chan(self, chip):
        """A chip's three channel outputs now (8 bits each, after its volume table)."""
        out = (ctypes.c_int * 3)()
        self.lib.zxn_ay_chan(self.z, chip, out)
        return tuple(out)

    def ay_env(self, chip):
        """A chip's envelope step now, 0-31."""
        return self.lib.zxn_ay_env(self.z, chip)

    def ay_log(self):
        """The CPU's AY writes in the I/O log (io_log(True) first; io_out isn't logged): [(t28, port, value)]."""
        return [(t, port, v) for t, _, port, v, rw in self.io_events
                if rw == 'w' and (port & 0xFF) == 0xFD and (port >> 14) in (2, 3)]

    @staticmethod
    def write_wav(path, samples, rate=48000):
        """Write audio() output (int16, shape (n, 2)) as a stereo WAV."""
        import wave
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(samples.astype('<i2').tobytes())

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
