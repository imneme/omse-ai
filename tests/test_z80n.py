"""The ZX Spectrum Next's Z80N instructions, held to the Next's own CPU.

With its `z80n` flag set, omse-ai's Z80 (src/z80.h) runs the Next's extra ED instructions. These tests hold
each one to a reference written from the Next's VHDL CPU, not from z80.h: the T80N of core 3.02.02 (Melissa's
Next; the files are the same in 3.02.05), by Daniel Wallner, with the Next's changes by Fabio Belavenuto,
Victor Trucco, Charlie Ingley, Garry Lancaster and ACX. t80n_mcode.vhd gives each instruction's machine cycles
and T-states, t80n.vhd what the Z80N "commands" do and when the address bus changes, t80n_alu.vhd the flags,
and t80na.vhd when MREQ, RD, WR and IORQ fall. Every instruction is checked for its result, its flags, memory,
and every tick's pins (the cycle, its address, its data) on a bare Z80 with flat memory (tests/bare_z80.cpp).

The reference speaks omse-ai's pin convention (docs/contention.md): a memory cycle shows MREQ with RD or WR on
its T1, MREQ alone on T2 and nothing on T3; an opcode fetch shows M1, MREQ, RD, then MREQ, then MREQ with RFSH
at the refresh address IR, then nothing; an I/O cycle shows IORQ, IORQ with RD or WR, IORQ, IORQ (the T80N's
I/O cycle, T1 T1w T2 T3, has the same strobe in the same place as a Zilog's T1 T2 Tw T3). An internal T-state
shows the address the bus still holds, which on the T80N is whatever the last machine cycle's end set: t80n.vhd
changes A only at T_Res. That matters, because the Next contends internal T-states by that address, as a real
48K does (video/zxula.vhd).

A NEXTREG write reaches the machine on a side band: virtual pin Z80N_NEXTREG (bit 39) for one tick, register
in bits 40-47, value in 48-55, on the T1 of the machine cycle where the T80N raises Z80N_dout with the
NEXTREGW command (zxnext.vhd writes on that signal's rising edge).

Where the VHDL disagrees with the documented behaviour, these tests follow the VHDL (each place is marked
"VHDL:"); a probe on Melissa's real Next decides (next-build/z80n/NOTES.md lists them).
"""
import ctypes
import hashlib
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'tests' / 'out'
OUT.mkdir(parents=True, exist_ok=True)

M1, MREQ, IORQ, RD, WR, RFSH = 1 << 24, 1 << 25, 1 << 26, 1 << 27, 1 << 28, 1 << 34
NEXTREG = 1 << 39
NMIACK_MSB, NMIACK_LSB, RETN_LSB, RETN_MSB = 1 << 56, 1 << 57, 1 << 58, 1 << 59
CTRL = M1 | MREQ | IORQ | RD | WR | RFSH | NEXTREG | NMIACK_MSB | NMIACK_LSB | RETN_LSB | RETN_MSB
S_, Z_, Y_, H_, X_, P_, N_, C_ = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
REGS = ['af', 'bc', 'de', 'hl', 'ix', 'iy', 'sp', 'pc', 'wz', 'ir', 'af2', 'bc2', 'de2', 'hl2', 'im', 'iff1',
        'iff2']

# The Z80N's ED opcodes in core 3.02.02, and their T-states as the documentation gives them (an independent
# check on the cycle-by-cycle reference below; the repeating ones are given per repeat / last).
Z80N_T = {0x23: 8, 0x24: 8, 0x27: 11, 0x28: 8, 0x29: 8, 0x2A: 8, 0x2B: 8, 0x2C: 8, 0x30: 8, 0x31: 8,
          0x32: 8, 0x33: 8, 0x34: 16, 0x35: 16, 0x36: 16, 0x8A: 23, 0x90: 16, 0x91: 20, 0x92: 17, 0x93: 8,
          0x94: 8, 0x95: 8, 0x98: 13, 0xA4: 16, 0xA5: 14, 0xAC: 16, 0xB4: (21, 16), 0xB6: (21, 16),
          0xB7: (21, 16), 0xBC: (21, 16)}
OPERANDS = {0x27: 1, 0x34: 2, 0x35: 2, 0x36: 2, 0x8A: 2, 0x91: 2, 0x92: 1}
# The T80N decodes these as RETN (t80n_mcode.vhd), with its RETN_LSB/RETN_MSB commands on the two pops; ED 4D is
# RETI, with none. (A Zilog's ED 55..7D are RETN too; floooh's z80.h runs them as RETI, the same but its RETI pin.)
RETN_OPS = (0x45, 0x55, 0x5D, 0x65, 0x6D, 0x75, 0x7D)
# The documented ED instructions whose flags the Next's CPU makes its own way (the T80N leaves a Zilog; the core's
# idle t80n-complete is the T80N with those places fixed, and the diff between them names them): TestT80NFlags.
T80N_INXR = (0xA2, 0xAA, 0xB2, 0xBA, 0xA3, 0xAB, 0xB3, 0xBB)     # INI IND INIR INDR OUTI OUTD OTIR OTDR
T80N_CPXR = (0xA1, 0xA9, 0xB1, 0xB9)                             # CPI CPD CPIR CPDR
T80N_LDAIR = (0x57, 0x5F)                                        # LD A,I  LD A,R
T80N_INRC = (0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70, 0x78)     # IN r,(C), IN (C)
T80N_FLAG_OPS = T80N_INXR + T80N_CPXR + T80N_LDAIR + T80N_INRC


# -- the bare Z80 ----------------------------------------------------------------------------------------

_libs = {}


def harness(header=None):
    """Build tests/bare_z80.cpp against src/z80.h (or another copy of it, for mutants) and load it."""
    header = str(Path(header).resolve()) if header else None
    if header in _libs:
        return _libs[header]
    ext = 'dylib' if sys.platform == 'darwin' else 'so'
    tag = '' if header is None else '-' + hashlib.sha1(header.encode()).hexdigest()[:12]
    lib = (OUT if header is None else OUT / 'mutants') / f'libbarez80{tag}.{ext}'
    lib.parent.mkdir(exist_ok=True)
    src = ROOT / 'tests' / 'bare_z80.cpp'
    deps = [src, Path(header) if header else ROOT / 'src' / 'z80.h']
    if not lib.exists() or any(d.stat().st_mtime > lib.stat().st_mtime for d in deps):
        cmd = [os.environ.get('CXX', 'c++'), '-O1', '-std=c++20', '-fPIC',
               '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-o', str(lib), str(src)]
        if header:
            cmd.insert(1, f'-DZ80_HEADER="{header}"')
        subprocess.run(cmd, check=True)
    h = ctypes.CDLL(str(lib))
    h.bare_new.restype = ctypes.c_void_p
    h.bare_new.argtypes = [ctypes.c_int]
    for f in ('bare_free', 'bare_reset'):
        getattr(h, f).argtypes = [ctypes.c_void_p]
    h.bare_mem.restype = h.bare_io.restype = ctypes.c_void_p
    h.bare_mem.argtypes = h.bare_io.argtypes = [ctypes.c_void_p]
    h.bare_waits.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    h.bare_z80n.argtypes = h.bare_nmi.argtypes = [ctypes.c_void_p]
    h.bare_get.restype = ctypes.c_uint
    h.bare_get.argtypes = [ctypes.c_void_p, ctypes.c_int]
    h.bare_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint]
    h.bare_step.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64), ctypes.c_int, ctypes.c_int]
    if hasattr(h, 'bare_endlog'):
        h.bare_steplog.restype = h.bare_endlog.restype = ctypes.c_void_p
        h.bare_steplog.argtypes = h.bare_endlog.argtypes = [ctypes.c_void_p]
        h.bare_set_int.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _libs[header] = h
    return h


class Bare:
    def __init__(self, z80n=True, header=None, wait_mem=0, wait_rd=0):
        self.h = harness(header if header is not None else os.environ.get('Z80N_TEST_HEADER'))
        self.b = self.h.bare_new(int(z80n))
        self.mem = (ctypes.c_uint8 * 65536).from_address(self.h.bare_mem(self.b))
        self.io = (ctypes.c_uint8 * 65536).from_address(self.h.bare_io(self.b))
        self.log = (ctypes.c_uint64 * 512)()
        self.h.bare_waits(self.b, wait_mem, wait_rd)
        self.wait_mem, self.wait_rd = wait_mem, wait_rd
        for i in range(65536):                       # something to read everywhere, and from every port
            self.mem[i] = (i * 37 + 11) & 0xFF
            self.io[i] = (i * 53 + 7) & 0xFF

    def __del__(self):
        if getattr(self, 'b', None):
            self.h.bare_free(self.b)

    def regs(self):
        return {r: self.h.bare_get(self.b, i) for i, r in enumerate(REGS)}

    def set(self, regs):
        for i, r in enumerate(REGS):
            if r in regs and r != 'pc':
                self.h.bare_set(self.b, i, regs[r])
        if 'pc' in regs:                             # last: it prefetches there
            self.h.bare_set(self.b, REGS.index('pc'), regs['pc'])

    def nmi(self):
        self.h.bare_nmi(self.b)

    def step(self, limit=400):
        n = self.h.bare_step(self.b, self.log, 512, limit)
        assert n >= 0, 'ran away: no next instruction within the limit'
        self.last_n = n
        return [tick_of(self.log[i]) for i in range(min(n, 512))]

    def ends(self):
        """z80_mcycle_end after each tick of the last step"""
        e = (ctypes.c_uint8 * 2048).from_address(self.h.bare_endlog(self.b))
        return [bool(e[i]) for i in range(min(self.last_n, 2048))]

    def steps(self):
        """the decoder step each tick of the last step ran"""
        e = (ctypes.c_uint16 * 2048).from_address(self.h.bare_steplog(self.b))
        return [e[i] for i in range(min(self.last_n, 2048))]

    def interrupt(self, on):
        self.h.bare_set_int(self.b, int(on))


def tick_of(p):
    """A tick as the tests compare it: control pins, address, data (only where RD or WR says it's
    meaningful), and the NEXTREG side band (only on its strobe)."""
    c = p & CTRL
    return (c, p & 0xFFFF, (p >> 16) & 0xFF if c & (RD | WR) else None,
            ((p >> 40) & 0xFF, (p >> 48) & 0xFF) if c & NEXTREG else None)


# -- the reference: the T80N, from its VHDL ---------------------------------------------------------------

def parity(v):
    return bin(v).count('1') % 2 == 0


def flags_and(q):                                    # t80n_alu.vhd, ALU_Op AND: H=1, N=0, C=0, P parity
    return (q & S_) | (Z_ if q == 0 else 0) | (q & (Y_ | X_)) | H_ | (P_ if parity(q) else 0)


def flags_add8(a, b):                                # t80n_alu.vhd, ALU_Op ADD with no carry in
    r = a + b
    q = r & 0xFF
    v = ((a ^ q) & (b ^ q) & 0x80) != 0
    return ((q & S_) | (Z_ if q == 0 else 0) | (q & (Y_ | X_)) | (H_ if (a & 15) + (b & 15) > 15 else 0)
            | (P_ if v else 0) | (C_ if r > 0xFF else 0))


def flags_bt(f, n, bc):                              # t80n.vhd, I_BT: X=n3, Y=n1, H=N=0, P = BC != 0
    return (f & (S_ | Z_ | C_)) | (n & X_) | ((n & 0x02) << 4) | (P_ if bc else 0)


def pixeldn(hl):
    """t80n.vhd's PIXELDN (Garry's version): H4 H3 L7 L6 L5 H2 H1 H0 + 1, eight bits, the rest kept."""
    h, l = hl >> 8, hl & 0xFF
    c = (((h >> 3) & 3) << 6 | ((l >> 5) & 7) << 3 | (h & 7)) + 1
    return ((h & 0xE0) | ((c >> 6) & 3) << 3 | (c & 7)) << 8 | ((c >> 3) & 7) << 5 | (l & 0x1F)


class Ref:
    """One instruction of the T80N: what it does to the state, and every tick of it."""

    def __init__(self, regs, mem, io, z80n=True, wait_mem=0, wait_rd=0):
        self.R = dict(regs)
        self.mem = bytearray(mem)
        self.io = bytes(io)
        self.z80n = z80n
        self.wait_mem, self.wait_rd = wait_mem, wait_rd
        self.ticks = []

    # the bus, a machine cycle at a time
    def _held(self, rd, fetch, a):
        # Each wait holds T2. A fetch's held T2 shows MREQ (z80.h raises it before it looks at WAIT); a
        # read's or a write's shows nothing (z80.h looks at WAIT first), as every other cycle in z80.h.
        self.ticks += [(MREQ if fetch else 0, a, None, None)] * (self.wait_mem + (self.wait_rd if rd else 0))

    def fetch(self, a, extra=0, t2=MREQ):
        ir = self.R['ir']
        d = self.mem[a]
        self.ticks.append((M1 | MREQ | RD, a, d, None))
        self._held(True, True, a)
        self.ticks += [(t2, a, None, None), (MREQ | RFSH, ir, None, None), (0, ir, None, None)]
        self.ticks += [(0, ir, None, None)] * extra          # a 5-T M1's last T: the refresh address stays
        r = ir & 0xFF
        self.R['ir'] = (ir & 0xFF00) | (r & 0x80) | ((r + 1) & 0x7F)
        return d

    def rd(self, a, side=None, then=None, extra=0):
        """A read at a; `then`: the address the bus moves to after T1 (LDPIRX); side: a NEXTREG strobe; extra:
        other side-band pins on its T1 (RETN's)."""
        a &= 0xFFFF
        d = self.mem[a]
        self.ticks.append((MREQ | RD | (NEXTREG if side else 0) | extra, a, d, side))
        b = a if then is None else then
        self._held(True, False, b)
        self.ticks += [(MREQ, b, None, None), (0, b, None, None)]
        return d

    def wr(self, a, d, extra=0):
        a &= 0xFFFF
        self.mem[a] = d
        self.ticks.append((MREQ | WR | extra, a, d, None))
        self._held(False, False, a)
        self.ticks += [(MREQ, a, None, None), (0, a, None, None)]

    def internal(self, a, n=1):
        self.ticks += [(0, a & 0xFFFF, None, None)] * n

    def io_in(self, port):
        d = self.io[port]
        self.ticks += [(IORQ, port, None, None), (IORQ | RD, port, d, None), (IORQ, port, None, None),
                       (IORQ, port, None, None)]
        return d

    def io_out(self, port, d):
        self.ticks += [(IORQ, port, None, None), (IORQ | WR, port, d, None), (IORQ, port, None, None),
                       (IORQ, port, None, None)]

    # registers
    def g(self, r):
        if len(r) == 1:
            pair, hi = {'a': ('af', 1), 'f': ('af', 0), 'b': ('bc', 1), 'c': ('bc', 0), 'd': ('de', 1),
                        'e': ('de', 0), 'h': ('hl', 1), 'l': ('hl', 0)}[r]
            return (self.R[pair] >> 8) & 0xFF if hi else self.R[pair] & 0xFF
        return self.R[r]

    def s(self, r, v):
        if len(r) == 1:
            pair, hi = {'a': ('af', 1), 'f': ('af', 0), 'b': ('bc', 1), 'c': ('bc', 0), 'd': ('de', 1),
                        'e': ('de', 0), 'h': ('hl', 1), 'l': ('hl', 0)}[r]
            v &= 0xFF
            self.R[pair] = (self.R[pair] & 0x00FF) | (v << 8) if hi else (self.R[pair] & 0xFF00) | v
        else:
            self.R[r] = v & 0xFFFF

    def nmi(self):
        """The NMI response: a fetch at PC that doesn't count it, 5 T (the last internal, the bus on IR), then
        PC pushed, high byte first, with the T80N's NMIACK_MSB and NMIACK_LSB commands on the two writes."""
        p = self.R['pc']
        self.fetch(p, extra=1, t2=0)            # (z80.h's NMI fetch shows no MREQ on T2, as it always has)
        sp = self.R['sp']
        self.wr(sp - 1, p >> 8, extra=NMIACK_MSB if self.z80n else 0)
        self.wr(sp - 2, p & 0xFF, extra=NMIACK_LSB if self.z80n else 0)
        self.R.update(sp=(sp - 2) & 0xFFFF, pc=0x0066, wz=0x0066, iff1=0)
        return self

    def run(self):
        g, s = self.g, self.s
        p = self.R['pc']
        assert self.mem[p] == 0xED
        self.fetch(p)
        op = self.mem[(p + 1) & 0xFFFF]
        self.fetch((p + 1) & 0xFFFF, extra=1 if (self.z80n and op == 0x90) else 0)
        pc = (p + 2) & 0xFFFF
        if op in RETN_OPS or op == 0x4D:                        # RETN (and RETI): pops PC, IFF1 = IFF2
            side = self.z80n and op != 0x4D
            sp = g('sp')
            lo = self.rd(sp, extra=RETN_LSB if side else 0)
            hi = self.rd(sp + 1, extra=RETN_MSB if side else 0)
            s('sp', sp + 2)
            s('pc', hi << 8 | lo)
            s('wz', hi << 8 | lo)                               # (floooh's MEMPTR, kept as it was)
            self.R['iff1'] = self.R['iff2']
            return self
        if not self.z80n or op not in Z80N_T:
            s('pc', pc)                                         # a Zilog's ED no-op, 8 T
            return self
        a, f = g('a'), g('f')
        if op == 0x23:                                          # SWAPNIB: at TState 3 of M1
            s('a', (a << 4) | (a >> 4))
        elif op == 0x24:                                        # MIRROR A
            s('a', int(f'{a:08b}'[::-1], 2))
        elif op == 0x27:                                        # TEST n: AND's flags, A kept (no Read_To_Reg)
            n = self.rd(pc)
            pc += 1
            s('f', flags_and(a & n))
        elif 0x28 <= op <= 0x2C:                                # barrel shifts of DE by B(4:0)
            de, k = g('de'), g('b') & 31
            if op == 0x28:
                de = de << k
            elif op == 0x29:                                    # 17 bits, bit 16 = bit 15: arithmetic
                de = (de - 0x10000 if de & 0x8000 else de) >> k
            elif op == 0x2A:                                    # bit 16 = IR(0) = 0
                de = de >> k
            elif op == 0x2B:                                    # bit 16 = IR(0) = 1: fills with ones
                de = (de | -0x10000) >> k
            else:                                               # rotate_left: by k mod 16
                k &= 15
                de = (de << k) | (de >> (16 - k))
            s('de', de & 0xFFFF)
        elif op == 0x30:                                        # MUL D,E
            s('de', g('d') * g('e'))
        elif op in (0x31, 0x32, 0x33):                          # ADD rr,A, 16 bits, unsigned
            rr = {0x31: 'hl', 0x32: 'de', 0x33: 'bc'}[op]
            s(rr, g(rr) + a)
            s('f', f & ~C_)     # VHDL: F(C) <= reg_temp_t(16), and the sum fills only bits 15..0: C is cleared
        elif op in (0x34, 0x35, 0x36):                          # ADD rr,nn: M2, M3 are 4 T (TStates "100")
            rr = {0x34: 'hl', 0x35: 'de', 0x36: 'bc'}[op]
            lo = self.rd(pc)
            self.internal(pc)
            hi = self.rd(pc + 1)
            self.internal(pc + 1)
            pc += 2
            s(rr, g(rr) + (hi << 8 | lo))                       # flags kept
        elif op == 0x8A:                                        # PUSH nn: hi first; six M-cycles after ED
            hi = self.rd(pc)
            sp = (g('sp') - 1) & 0xFFFF
            self.wr(sp, hi)
            lo = self.rd(pc + 1)
            sp = (sp - 1) & 0xFFFF
            self.wr(sp, lo)
            self.rd(pc + 1)                                     # M6: a read of the operand again, then PC+1
            pc += 2
            s('sp', sp)
        elif op == 0x90:                                        # OUTINB: B and flags kept, HL+1
            v = self.rd(g('hl'))
            self.io_out(g('bc'), v)
            s('hl', g('hl') + 1)
        elif op == 0x91:                                        # NEXTREG r,v: M4 strobes, M4 and M5 re-read v's
            r = self.rd(pc)
            v = self.rd(pc + 1)
            self.rd(pc + 1, side=(r, v))
            self.rd(pc + 1)
            pc += 2
        elif op == 0x92:                                        # NEXTREG r,A: M3 strobes, M3 and M4 re-read r's
            r = self.rd(pc)
            self.rd(pc, side=(r, a))
            self.rd(pc)
            pc += 1
        elif op == 0x93:                                        # PIXELDN
            s('hl', pixeldn(g('hl')))
        elif op == 0x94:                                        # PIXELAD: HL from (E, D)
            d, e = g('d'), g('e')
            s('h', 0x40 | (d >> 6) << 3 | (d & 7))
            s('l', ((d >> 3) & 7) << 5 | (e >> 3))
        elif op == 0x95:                                        # SETAE
            s('a', 0x80 >> (g('e') & 7))
        elif op == 0x98:                                        # JP (C): PC(13:6) from the port, PC(15:14) kept
            v = self.io_in(g('bc'))
            self.internal(g('bc'))                              # M2 is 4 T: the T4 after the I/O
            pc = (pc & 0xC000) | (v << 6)
        elif op in (0xA4, 0xAC, 0xB4, 0xBC, 0xB6, 0xB7):        # the LDxX family
            hl, de, bc = g('hl'), g('de'), (g('bc') - 1) & 0xFFFF
            if op == 0xB7:                                      # LDPIRX: the pattern byte; the bus moves to DE
                byte = self.rd((hl & 0xFFF8) | (de & 7), then=de)
            else:
                byte = self.rd(hl)
            if byte != a:
                self.wr(de, byte)
            else:
                self.rd(de)             # VHDL: Write <= '0' leaves RD <= not Write: a read cycle at DE
            self.internal(de, 2)
            if op in (0xA4, 0xB4, 0xB6):
                hl += 1
            elif op in (0xAC, 0xBC):
                hl -= 1
            s('hl', hl)
            s('de', de + 1)                                     # DE always counts up, even for LDDX
            s('bc', bc)
            # VHDL: the X variants keep I_BT, so they set flags as LDI does; LDPIRX's ALU sum is B OR byte
            n = ((bc >> 8) | byte) if op == 0xB7 else (a + byte) & 0xFF
            s('f', flags_bt(f, n, bc))
            if op & 0x10 and bc:                                # repeat: M4, 5 T, and PC back to the ED
                self.internal(de if op == 0xB4 else pc, 5)      # LDIRX keeps No_PC, so DE; the rest PC
                pc = p
        elif op == 0xA5:                                        # LDWS
            self.wr(g('de'), self.rd(g('hl')))
            d = g('d')
            s('l', g('l') + 1)
            s('d', d + 1)
            s('f', flags_add8(d, 1))    # VHDL: INC D is an ALU ADD without PreserveC: its flags, carry too
        s('pc', pc & 0xFFFF)
        return self


# -- the tests ----------------------------------------------------------------------------------------

def fill_regs(rng, **fixed):
    r = {k: rng.randrange(0x10000) for k in ('af', 'bc', 'de', 'hl', 'ix', 'iy', 'sp', 'wz', 'af2', 'bc2',
                                              'de2', 'hl2')}
    r['ir'] = rng.randrange(0x10000)
    r.update(im=1, iff1=0, iff2=0, pc=0x8000)
    r.update(fixed)
    return r


class Z80NCase(unittest.TestCase):
    z80n = True

    @classmethod
    def setUpClass(cls):
        cls.cpu = Bare(z80n=cls.z80n)

    def put(self, regs, code, mem=None, cpu=None):
        cpu = cpu or self.cpu
        for a, v in (mem or {}).items():
            cpu.mem[a & 0xFFFF] = v
        for i, v in enumerate(code):
            cpu.mem[(regs['pc'] + i) & 0xFFFF] = v
        cpu.set(regs)

    def check(self, regs, code, mem=None, what='', cpu=None):
        """Run one instruction on the bare Z80 and in the reference, from the same state; all must agree."""
        cpu = cpu or self.cpu
        self.put(regs, code, mem, cpu)
        start = cpu.regs()
        ref = Ref(start, bytes(cpu.mem), bytes(cpu.io), z80n=self.z80n and cpu.h.bare_z80n(cpu.b),
                  wait_mem=cpu.wait_mem, wait_rd=cpu.wait_rd).run()
        ticks = cpu.step()
        got = cpu.regs()
        label = what or ' '.join(f'{b:02X}' for b in code)
        for r in REGS:
            self.assertEqual(got[r], ref.R[r], f'{label}: {r} is {got[r]:04X}, the T80N gives {ref.R[r]:04X}'
                             f' (from {", ".join(f"{k}={start[k]:04X}" for k in REGS[:10])})')
        if bytes(cpu.mem) != bytes(ref.mem):
            diff = [a for a in range(65536) if cpu.mem[a] != ref.mem[a]]
            self.fail(f'{label}: memory differs at {", ".join(f"{a:04X}" for a in diff[:8])}')
        for i, (t, w) in enumerate(zip(ticks, ref.ticks)):
            self.assertEqual(t, w, f'{label}: tick {i} is {show(t)}, the T80N gives {show(w)}\n'
                             f'  got {[show(x) for x in ticks]}\n want {[show(x) for x in ref.ticks]}')
        self.assertEqual(len(ticks), len(ref.ticks), f'{label}: {len(ticks)} T-states, the T80N takes '
                         f'{len(ref.ticks)}')
        return ticks, ref


def show(t):
    c, a, d, side = t
    names = [n for n, b in (('M1', M1), ('MREQ', MREQ), ('IORQ', IORQ), ('RD', RD), ('WR', WR),
                            ('RFSH', RFSH), ('NEXTREG', NEXTREG), ('NMIACK_MSB', NMIACK_MSB),
                            ('NMIACK_LSB', NMIACK_LSB), ('RETN_LSB', RETN_LSB), ('RETN_MSB', RETN_MSB)) if c & b]
    s = '|'.join(names) or '-'
    s += f'@{a:04X}'
    if d is not None:
        s += f'={d:02X}'
    if side:
        s += f'[{side[0]:02X}<-{side[1]:02X}]'
    return s


class TestEachInstruction(Z80NCase):
    """Every Z80N instruction, from a few states each: everything it does, tick by tick."""

    def test_every_opcode(self):
        rng = random.Random(1)
        for op in Z80N_T:
            for k in range(12):
                with self.subTest(op=f'ED {op:02X}', k=k):
                    regs = fill_regs(rng, pc=rng.choice((0x8000, 0x6000, 0xC123, 0x3FFE, 0xFFFE)))
                    code = [0xED, op] + [rng.randrange(256) for _ in range(OPERANDS.get(op, 0))]
                    self.check(regs, code)

    def test_t_states_as_documented(self):
        """The cycle-by-cycle reference adds up to the documentation's T-states (a second source)."""
        rng = random.Random(2)
        for op, t in Z80N_T.items():
            with self.subTest(op=f'ED {op:02X}'):
                regs = fill_regs(rng, bc=0x0005)
                code = [0xED, op] + [0x12] * OPERANDS.get(op, 0)
                ticks, _ = self.check(regs, code)
                self.assertEqual(len(ticks), t[0] if isinstance(t, tuple) else t)
                if isinstance(t, tuple):
                    regs = fill_regs(rng, bc=0x0001)
                    ticks, _ = self.check(regs, code)
                    self.assertEqual(len(ticks), t[1])

    def test_nextreg_strobes_once(self):
        """NEXTREG's write: one tick of the side band, on the T1 of M4 (r,v) or M3 (r,A), with its bytes."""
        for code, at in (([0xED, 0x91, 0x07, 0x03], 4 + 4 + 3 + 3), ([0xED, 0x92, 0x07], 4 + 4 + 3)):
            with self.subTest(op=f'ED {code[1]:02X}'):
                regs = fill_regs(random.Random(3), af=0x5A00)
                ticks, _ = self.check(regs, code)
                strobes = [i for i, t in enumerate(ticks) if t[0] & NEXTREG]
                self.assertEqual(strobes, [at])
                self.assertEqual(ticks[at][3], (0x07, 0x03 if code[1] == 0x91 else 0x5A))
                self.assertEqual(ticks[at][0], MREQ | RD | NEXTREG)     # the dummy read goes on with it

    def test_ldix_writes_only_other_bytes(self):
        for byte, a in ((0x33, 0x33), (0x33, 0x34)):
            for op in (0xA4, 0xAC, 0xB4, 0xBC, 0xB6):
                with self.subTest(op=f'ED {op:02X}', same=byte == a):
                    regs = fill_regs(random.Random(4), af=a << 8, hl=0x9000, de=0xA000, bc=3)
                    ticks, _ = self.check(regs, [0xED, op], mem={0x9000: byte, 0xA000: 0x77})
                    self.assertEqual(self.cpu.mem[0xA000], 0x77 if byte == a else byte)
                    self.assertTrue(any(t[0] == MREQ | (RD if byte == a else WR) and t[1] == 0xA000
                                        for t in ticks))

    def test_ldpirx_reads_the_pattern(self):
        """LDPIRX: byte from (HL & FFF8) + (E & 7), to DE unless it's A; HL stays; DE, BC count."""
        for e in range(16):
            with self.subTest(e=e):
                mem = {0x9000 + i: 0x10 + i for i in range(8)}
                mem[0xA000 + e] = 0x77
                regs = fill_regs(random.Random(5), af=0x1300, hl=0x9005, de=0xA000 + e, bc=2)
                self.check(regs, [0xED, 0xB7], mem=mem)
                self.assertEqual(self.cpu.regs()['hl'], 0x9005)
                want = 0x10 + (e & 7)
                self.assertEqual(self.cpu.mem[0xA000 + e], 0x77 if want == 0x13 else want)

    def test_jp_c_keeps_the_top_two_bits(self):
        for pc in (0x0000, 0x3FFC, 0x3FFE, 0x7FFE, 0x8000, 0xBFFE, 0xFFFC):
            for v in (0x00, 0x01, 0x80, 0xFF):
                with self.subTest(pc=f'{pc:04X}', v=v):
                    regs = fill_regs(random.Random(6), pc=pc, bc=0x1234)
                    self.cpu.io[0x1234] = v
                    self.check(regs, [0xED, 0x98])
                    self.assertEqual(self.cpu.regs()['pc'], ((pc + 2) & 0xC000) | (v << 6))


class TestValues(Z80NCase):
    """The arithmetic ones across their operands (registers, flags and bus, as above)."""

    def run_op(self, op, **regs):
        operands = regs.pop('operands', [])
        rng = random.Random(hash((op, tuple(operands), tuple(sorted(regs.items())))) & 0xFFFFFFFF)
        self.check(fill_regs(rng, **regs), [0xED, op] + operands)

    def test_swapnib_mirror_setae_every_value(self):
        for v in range(256):
            for f in (0x00, 0xFF):
                self.run_op(0x23, af=v << 8 | f)
                self.run_op(0x24, af=v << 8 | f)
                self.run_op(0x95, de=0x5500 | v, af=0x1200 | f)

    def test_test_n(self):
        rng = random.Random(7)
        for n in range(256):
            for a in (0x00, 0xFF, 0x80, 0x01, rng.randrange(256), rng.randrange(256)):
                self.run_op(0x27, af=a << 8 | rng.randrange(256), operands=[n])

    def test_mul(self):
        rng = random.Random(8)
        for d in range(256):
            for e in (0, 1, 2, 0x7F, 0x80, 0xFE, 0xFF, rng.randrange(256)):
                self.run_op(0x30, de=d << 8 | e)

    def test_add_rr_a(self):
        rng = random.Random(9)
        for op in (0x31, 0x32, 0x33):
            for a in range(256):
                for rr in (0x0000, 0x00FF, 0xFFFF, 0xFF80, rng.randrange(0x10000)):
                    reg = {0x31: 'hl', 0x32: 'de', 0x33: 'bc'}[op]
                    self.run_op(op, **{reg: rr, 'af': a << 8 | rng.choice((0x00, 0x01, 0xFF, 0xFE))})

    def test_add_rr_nn(self):
        rng = random.Random(10)
        for op in (0x34, 0x35, 0x36):
            for _ in range(300):
                reg = {0x34: 'hl', 0x35: 'de', 0x36: 'bc'}[op]
                self.run_op(op, **{reg: rng.randrange(0x10000)}, operands=[rng.randrange(256),
                                                                           rng.randrange(256)])

    def test_barrel_shifts(self):
        rng = random.Random(11)
        des = (0x0000, 0x0001, 0x8000, 0x8001, 0xFFFF, 0x1234, 0xA5C3, rng.randrange(0x10000))
        for op in (0x28, 0x29, 0x2A, 0x2B, 0x2C):
            for b in list(range(0x40)) + [0x40, 0x5F, 0x7F, 0x80, 0x9F, 0xE1, 0xFF]:
                for de in des:
                    self.run_op(op, de=de, bc=b << 8 | rng.randrange(256))

    def test_pixelad(self):
        for d in range(256):
            for e in (0x00, 0x07, 0x08, 0x80, 0xF8, 0xFF):
                self.run_op(0x94, de=d << 8 | e)

    def test_pixeldn(self):
        """Down a line everywhere: H all 256 values, L at the boundaries of its fields."""
        for h in range(256):
            for l in (0x00, 0x1F, 0x20, 0x5A, 0xDF, 0xE0, 0xE5, 0xFF):
                self.run_op(0x93, hl=h << 8 | l)

    def test_pixeldn_against_the_documented_rule(self):
        """The VHDL's counter and the documented three-case rule agree on the whole screen, its last line
        included (57E0h -> 5800h), and everywhere else but where the counter wraps: H&1Fh = 1Fh with
        L&E0h = E0h (VHDL: 5FE0h -> 4000h, documented: 6000h). A probe on a real Next decides there."""
        def documented(hl):
            if hl & 0x0700 != 0x0700:
                return (hl + 0x100) & 0xFFFF
            if hl & 0xE0 != 0xE0:
                return (hl & 0xF8FF) + 0x20
            return ((hl & 0xF81F) + 0x800) & 0xFFFF
        for hl in range(0x10000):
            wraps = hl & 0x1F00 == 0x1F00 and hl & 0xE0 == 0xE0
            self.assertEqual(pixeldn(hl) == documented(hl), not wraps, f'{hl:04X}')
        self.assertEqual(pixeldn(0x57E0), 0x5800)
        self.assertEqual(pixeldn(0x5FE0), 0x4000)

    def test_ldws(self):
        rng = random.Random(12)
        for d in range(256):
            for l in (0x00, 0x7F, 0xFF):
                hl = rng.randrange(0x40, 0x100) << 8 | l
                self.run_op(0xA5, hl=hl, de=d << 8 | rng.randrange(256), af=rng.randrange(0x10000))


class TestRepeats(Z80NCase):
    """The repeating ones, run to the end: 21 T a repeat and 16 for the last, and what they leave."""

    def run_block(self, op, regs, mem):
        self.put(regs, [0xED, op], mem)
        total, steps = 0, 0
        while True:
            ticks, ref = self.check(self.cpu.regs(), [0xED, op])
            total += len(ticks)
            steps += 1
            if self.cpu.regs()['pc'] != regs['pc']:
                return total, steps

    def test_ldirx_lddrx_ldpirx_b6(self):
        for op in (0xB4, 0xBC, 0xB7, 0xB6):
            for n in (1, 2, 7, 20):
                with self.subTest(op=f'ED {op:02X}', n=n):
                    src = {0x9000 + i: (0x20 + i if i % 3 else 0x55) for i in range(-24, 24)}
                    regs = fill_regs(random.Random(13), af=0x5500, hl=0x9000, de=0xA000, bc=n)
                    total, steps = self.run_block(op, regs, src)
                    self.assertEqual(steps, n)
                    self.assertEqual(total, 21 * (n - 1) + 16)
                    self.assertEqual(self.cpu.regs()['bc'], 0)
                    self.assertEqual(self.cpu.regs()['de'], 0xA000 + n)


class TestWaits(Z80NCase):
    """Every machine cycle waits at its T2 when the machine asks: one wait on every read (the Next at
    28 MHz), or on every read and write."""

    def test_reads_wait(self):
        for wm, wr in ((0, 1), (1, 0), (2, 0)):
            cpu = Bare(wait_mem=wm, wait_rd=wr)
            rng = random.Random(14)
            for op in Z80N_T:
                with self.subTest(op=f'ED {op:02X}', wait_mem=wm, wait_rd=wr):
                    regs = fill_regs(rng, bc=3)
                    code = [0xED, op] + [rng.randrange(256) for _ in range(OPERANDS.get(op, 0))]
                    self.check(regs, code, cpu=cpu)


class TestNmiAndRetn(Z80NCase):
    """The NMI's two pushes and RETN's two pops carry the T80N's NMIACK and RETN commands on the side band (the
    Next keeps the NMI's return address in nextregs C2h/C3h, and its stackless NMI uses them instead of memory);
    RETI (ED 4D) and the flag off carry none. Timing and everything else as the Zilog's."""

    def nmi_case(self, z80n):
        cpu = Bare(z80n=z80n)
        rng = random.Random(18)
        for k in range(8):
            regs = fill_regs(rng, iff1=1, iff2=1, pc=rng.choice((0x8000, 0x1234, 0xFFFF)))
            cpu.mem[regs['pc']] = 0x00                          # a NOP, then the NMI
            cpu.set(regs)
            cpu.nmi()
            self.assertEqual(len(cpu.step()), 4)
            start = cpu.regs()
            ref = Ref(start, bytes(cpu.mem), bytes(cpu.io), z80n=z80n).nmi()
            ticks = cpu.step()
            got = cpu.regs()
            for r in REGS:
                self.assertEqual(got[r], ref.R[r], r)
            self.assertEqual(bytes(cpu.mem), bytes(ref.mem))
            self.assertEqual([show(t) for t in ticks], [show(t) for t in ref.ticks])
            self.assertEqual(len(ticks), 11)

    def test_nmi_with_z80n(self):
        self.nmi_case(True)

    def test_nmi_without(self):
        self.nmi_case(False)

    def test_retn_family(self):
        rng = random.Random(19)
        for z80n in (True, False):
            cpu = Bare(z80n=z80n)
            for op in RETN_OPS + (0x4D,):
                with self.subTest(op=f'ED {op:02X}', z80n=z80n):
                    self.check(fill_regs(rng, iff1=0, iff2=1), [0xED, op], cpu=cpu)

    def test_retn_side_band_ticks(self):
        cpu = Bare()
        regs = fill_regs(random.Random(20), sp=0x9000)
        cpu.mem[0x9000], cpu.mem[0x9001] = 0x34, 0x12
        for op, want in ((0x45, (RETN_LSB, RETN_MSB)), (0x7D, (RETN_LSB, RETN_MSB)), (0x4D, (0, 0))):
            with self.subTest(op=f'ED {op:02X}'):
                cpu.mem[0x8000], cpu.mem[0x8001] = 0xED, op
                cpu.set(regs)
                ticks = cpu.step()
                pops = [t for t in ticks if t[0] & RD and not t[0] & M1]
                self.assertEqual([(t[0] & (RETN_LSB | RETN_MSB), t[1]) for t in pops], [(want[0], 0x9000), (want[1], 0x9001)])
                self.assertEqual(cpu.regs()['pc'], 0x1234)


class TestBit(unittest.TestCase):
    """BIT's undocumented X and Y flags as the Next's CPU makes them (t80n_alu.vhd, ALU_Op BIT): from the register
    for BIT n,r (as a Zilog); 0 for BIT n,(HL) and the documented DD/FD CB d 46-7E (a Zilog takes them from
    MEMPTR); the byte's bits 3 and 5 for the undocumented DD/FD CB d 40-7F on other registers (XYbit_undoc puts the
    byte on BusB). Melissa's Next agreed in all three places it was asked (Z80NTIME's BITF, LDPIRX2's C6 and C7).
    Everything else BIT does is as with the flag off, tick for tick; with it off, nothing changes."""

    def run_both(self, code, regs, mem):
        res = []
        for z80n in (True, False):
            cpu = self.cpus[z80n]
            for a, v in mem.items():
                cpu.mem[a & 0xFFFF] = v
            for i, v in enumerate(code):
                cpu.mem[(regs['pc'] + i) & 0xFFFF] = v
            cpu.set(regs)
            ticks = cpu.step()
            res.append((cpu.regs(), bytes(cpu.mem), ticks))
        return res

    @classmethod
    def setUpClass(cls):
        cls.cpus = {True: Bare(z80n=True), False: Bare(z80n=False)}

    def test_every_bit(self):
        rng = random.Random(21)
        for k in range(1500):
            op = 0x40 | rng.randrange(0x40)
            pre = rng.choice((None, None, 0xDD, 0xFD))
            regs = fill_regs(rng, pc=0x8000)
            regs['wz'] = rng.randrange(0x10000)
            d = rng.randrange(256)
            if pre is None:
                code = [0xCB, op]
                at = regs['hl']
            else:
                code = [pre, 0xCB, d, op]
                at = (regs['ix' if pre == 0xDD else 'iy'] + (d - 256 if d & 0x80 else d)) & 0xFFFF
            if 0x7F00 <= at <= 0x8010:
                continue                                    # (not over the code)
            byte = rng.randrange(256)
            (on, mem_on, t_on), (off, mem_off, t_off) = self.run_both(code, regs, {at: byte})
            label = ' '.join(f'{b:02X}' for b in code)
            self.assertEqual(t_on, t_off, label)
            self.assertEqual(mem_on, mem_off, label)
            for r in REGS:
                if r != 'af':
                    self.assertEqual(on[r], off[r], f'{label}: {r}')
            self.assertEqual(on['af'] & ~0x28, off['af'] & ~0x28, f'{label}: all but X and Y as with the flag off')
            if pre is None and op & 7 != 6:
                r8 = {0: 'b', 1: 'c', 2: 'd', 3: 'e', 4: 'h', 5: 'l', 7: 'a'}[op & 7]
                pair = {'b': 'bc', 'c': 'bc', 'd': 'de', 'e': 'de', 'h': 'hl', 'l': 'hl', 'a': 'af'}[r8]
                v = regs[pair] >> 8 if r8 in 'bdha' else regs[pair] & 0xFF
                want = v & 0x28                             # BIT n,r: from r, as a Zilog
            elif pre is None or op & 7 == 6:
                want = 0                                    # BIT n,(HL), BIT n,(IX+d): none
            else:
                want = byte & 0x28                          # the undocumented DDCB forms: the byte's
            self.assertEqual(on['af'] & 0x28, want, f'{label}: X, Y with the Z80N')

    def test_the_photographs_cells(self):
        """LDPIRX2's C6 and C7, as Melissa's Next printed them (10 and 38), and Z80NTIME's BITF (10)."""
        cpu = self.cpus[True]
        for code, regs, mem, want in (
                ([0xDD, 0xCB, 0x05, 0x46], {'ix': 0xBB30, 'af': 0x0000}, {0xBB35: 0x85}, 0x10),
                ([0xDD, 0xCB, 0x05, 0x40], {'ix': 0x9040, 'af': 0x0000}, {0x9045: 0x29}, 0x38),
                ([0xCB, 0x46], {'hl': 0xBB70, 'af': 0x0000, 'wz': 0x2900}, {0xBB70: 0x01}, 0x10)):
            with self.subTest(code=' '.join(f'{b:02X}' for b in code)):
                for a, v in mem.items():
                    cpu.mem[a] = v
                for i, v in enumerate(code):
                    cpu.mem[0x8000 + i] = v
                cpu.set({**fill_regs(random.Random(22)), **regs, 'pc': 0x8000})
                cpu.step()
                self.assertEqual(cpu.regs()['af'] & 0xFF, want)


class TestT80NFlags(unittest.TestCase):
    """The four other places the Next's CPU leaves a Zilog's flags, from the diff between t80n.vhd and the core's
    idle t80n_complete.vhd ("with the memptr and xy flags fixes applied"):
      INI/IND/OUTI/OUTD and repeats: F is the ALU's SUB B,1 (t80n_mcode.vhd M1: BusA B, BusB 1, ALU_Op 0010,
          Save_ALU, no PreserveC): S Z X Y from the new B, H and C as borrows, V as overflow, N set;
      CPI/CPD and repeats: X and Y are the byte's bits 3 and 5 (the ALU's CP takes them from BusB);
      LD A,I and LD A,R: X and Y are left as they were (t80n.vhd's Special_LD sets S Z H P N only);
      IN r,(C) and IN (C): X and Y are left as they were (its F update sets S Z P H N only).
    Melissa's Next agreed in all five cells Z80NFLAG asked (sitting 5: INI 22, OUTI 22, CPI BE, LD A,I 00,
    IN A,(C) 04). Those cells began from F = 00, so "left as they were", and INI's carry, rest on the VHDL; the
    random cells here begin from any F. Everything else is as with the flag off, tick for tick; off, nothing
    changes."""

    @classmethod
    def setUpClass(cls):
        cls.cpus = {True: Bare(z80n=True), False: Bare(z80n=False)}

    def run_one(self, z80n, code, regs, mem, io):
        cpu = self.cpus[z80n]
        for a, v in mem.items():
            cpu.mem[a & 0xFFFF] = v
        for a, v in io.items():
            cpu.io[a & 0xFFFF] = v
        for i, v in enumerate(code):
            cpu.mem[(regs['pc'] + i) & 0xFFFF] = v
        cpu.set(regs)
        ticks = cpu.step()
        return cpu.regs(), bytes(cpu.mem), ticks

    @staticmethod
    def want_f(op, f_in, b_in, byte, off_f):
        """The T80N's F, from what went in (and, for the bits it shares with a Zilog, the flag-off run's F)."""
        if op in T80N_INXR:
            b = (b_in - 1) & 0xFF
            return ((b & 0xA8) | (0x40 if b == 0 else 0) | (0x10 if b_in & 0xF == 0 else 0)
                    | (0x04 if b_in == 0x80 else 0) | 0x02 | (0x01 if b_in == 0 else 0))
        if op in T80N_CPXR:
            return (off_f & ~0x28) | (byte & 0x28)
        return (off_f & ~0x28) | (f_in & 0x28)                  # LD A,I/R, IN r,(C)

    def test_every_one(self):
        rng = random.Random(64)
        for k in range(4000):
            op = rng.choice(T80N_FLAG_OPS)
            regs = fill_regs(rng, pc=0x8000)
            regs['iff2'] = rng.randrange(2)
            if rng.randrange(4) == 0:                           # the edges: B = 00, 01, 80, 10h; BC = 1
                regs['bc'] = (rng.choice((0x00, 0x01, 0x80, 0x10, 0x81)) << 8) | rng.randrange(256)
            if rng.randrange(8) == 0:
                regs['bc'] = 1
            if 0x7FF0 <= regs['hl'] <= 0x8010:
                continue                                        # (not over the code)
            byte = rng.randrange(256)
            code = [0xED, op]
            on, mem_on, t_on = self.run_one(True, code, regs, {regs['hl']: byte}, {})
            off, mem_off, t_off = self.run_one(False, code, regs, {regs['hl']: byte}, {})
            label = f'ED {op:02X} af={regs["af"]:04X} bc={regs["bc"]:04X} byte={byte:02X}'
            self.assertEqual(t_on, t_off, label)
            self.assertEqual(mem_on, mem_off, label)
            for r in REGS:
                if r != 'af':
                    self.assertEqual(on[r], off[r], f'{label}: {r}')
            self.assertEqual(on['af'] >> 8, off['af'] >> 8, f'{label}: A')
            want = self.want_f(op, regs['af'] & 0xFF, regs['bc'] >> 8, byte, off['af'] & 0xFF)
            self.assertEqual(on['af'] & 0xFF, want, f'{label}: F with the Z80N')

    def test_the_photographs_cells(self):
        """Z80NFLAG's five cells as Melissa's Next printed them (the T80N column), and as a Zilog (the flag off)."""
        cells = (  # code, regs, mem, io, T80N's F, a Zilog's F
            ([0xED, 0xA2], {'hl': 0xBB90, 'bc': 0x253B, 'af': 0x0000}, {}, {0x253B: 0xD0}, 0x22, 0x33),
            ([0xED, 0xA3], {'hl': 0xBBF0, 'bc': 0x253B, 'af': 0x0000}, {0xBBF0: 0x90}, {}, 0x22, 0x33),
            ([0xED, 0xA1], {'hl': 0xBBA0, 'bc': 0x0002, 'af': 0x1000}, {0xBBA0: 0x28}, {}, 0xBE, 0xB6),
            ([0xED, 0x57], {'ir': 0x2800, 'af': 0x0000}, {}, {}, 0x00, 0x28),
            ([0xED, 0x78], {'bc': 0x253B, 'af': 0x0000}, {}, {0x253B: 0x28}, 0x04, 0x2C))
        for code, regs, mem, io, t80n, zilog in cells:
            for z80n, want in ((True, t80n), (False, zilog)):
                with self.subTest(code=f'ED {code[1]:02X}', z80n=z80n):
                    r = {**fill_regs(random.Random(65)), **regs, 'pc': 0x8000}
                    got, _, _ = self.run_one(z80n, code, r, mem, io)
                    self.assertEqual(got['af'] & 0xFF, want)


class TestOthersUnchanged(unittest.TestCase):
    """The flag takes only the Z80N's own opcodes: every other instruction (unprefixed, CB, DD, FD, ED) runs
    exactly as with the flag off, tick for tick."""

    def test_on_and_off_agree(self):
        on, off = Bare(z80n=True), Bare(z80n=False)
        rng = random.Random(16)
        codes = [[op] for op in range(256) if op not in (0xCB, 0xDD, 0xED, 0xFD)]
        codes += [[pre, op] for pre in (0xCB, 0xDD, 0xED, 0xFD) for op in range(256)]
        for code in codes:
            if code[0] == 0xED and (code[1] in Z80N_T or code[1] in RETN_OPS or code[1] in T80N_FLAG_OPS):
                continue                        # (T80N_FLAG_OPS: their flags are TestT80NFlags's)
            regs = fill_regs(rng)
            code = code + [rng.randrange(256) for _ in range(3)]
            if code[0] in (0xDD, 0xFD) and code[1] == 0xED and (code[2] in Z80N_T or code[2] in T80N_FLAG_OPS):
                code[2] = 0x00                  # DD ED op is ED op (below), so not one of the others
            if code[0] == 0xCB and 0x40 <= code[1] < 0x80 and code[1] & 7 == 6:
                continue                        # BIT n,(HL): the Z80N's X and Y (TestBit)
            if code[0] in (0xDD, 0xFD) and code[1] == 0xCB and 0x40 <= code[3] < 0x80:
                code[3] = 0x06                  # BIT b,(IX+d): ditto; RLC (IX+d) instead
            res = []
            for cpu in (on, off):
                for i, v in enumerate(code):
                    cpu.mem[0x8000 + i] = v
                cpu.mem[regs['sp']] = cpu.mem[(regs['sp'] + 1) & 0xFFFF] = 0x80   # somewhere to RET to
                cpu.set(regs)
                ticks = cpu.step(limit=100)
                res.append((cpu.regs(), bytes(cpu.mem), ticks))
            self.assertEqual(res[0], res[1], ' '.join(f'{b:02X}' for b in code))

    def test_dd_fd_before_ed_drop(self):
        """A DD or FD before ED is a prefix the ED drops (t80n.vhd: Prefix "10" sets XY_State "00"), as on a
        Zilog: DD ED op is ED op with 4 T and one R step more, on HL and not IX."""
        cpu = Bare()
        rng = random.Random(17)
        for op in Z80N_T:
            for pre in (0xDD, 0xFD):
                with self.subTest(op=f'{pre:02X} ED {op:02X}'):
                    regs = fill_regs(rng, bc=1)
                    tail = [rng.randrange(256) for _ in range(OPERANDS.get(op, 0))]
                    runs = []
                    for code in ([0xED, op] + tail, [pre, 0xED, op] + tail):
                        for i, v in enumerate(code):
                            cpu.mem[0x8000 + i] = v
                        for i in range(8):
                            cpu.mem[0x9000 + i] = cpu.mem[regs['hl'] + i & 0xFFFF] = 0x40 + i
                        cpu.set(regs)
                        n = len(cpu.step())
                        runs.append((n, cpu.regs()))
                    (n0, r0), (n1, r1) = runs
                    self.assertEqual(n1, n0 + 4)
                    for r in REGS:
                        if r not in ('pc', 'ir'):
                            self.assertEqual(r0[r], r1[r], r)
                    self.assertEqual(r1['ir'] & 0x7F, (r0['ir'] + 1) & 0x7F)
                    if r0['pc'] != 0x8000:                  # (a repeat goes back to its own ED)
                        self.assertEqual(r1['pc'], r0['pc'] + (1 if op != 0x98 else 0))


class TestOff(Z80NCase):
    """With the flag off (the 48K and 128), every Z80N opcode is a Zilog's ED no-op: 8 T, two fetches."""
    z80n = False

    def test_no_ops(self):
        rng = random.Random(15)
        for op in Z80N_T:
            with self.subTest(op=f'ED {op:02X}'):
                ticks, _ = self.check(fill_regs(rng), [0xED, op, 0x12, 0x34])
                self.assertEqual(len(ticks), 8)

    def test_flag_defaults_off_and_survives_reset(self):
        off = Bare(z80n=False)
        self.assertEqual(off.h.bare_z80n(off.b), 0)
        on = Bare(z80n=True)
        on.h.bare_reset(on.b)
        self.assertEqual(on.h.bare_z80n(on.b), 1, 'a Next is still a Next after a reset')


if __name__ == '__main__':
    unittest.main()
