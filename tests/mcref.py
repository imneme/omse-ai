"""The T80N's machine cycles: for any instruction, the length in T-states of each of its machine cycles, as the
Next's CPU runs it. Transcribed from t80n_mcode.vhd (core 3.02.02; Daniel Wallner's T80 with the Next's changes):
each instruction's MCycles, and its TStates per cycle (M1 defaults to 4, every other cycle to 3), plus what
t80n.vhd and t80na.vhd add: an I/O cycle's automatic wait (IOWait = 1: one more T-state), an interrupt
acknowledge's two automatic waits (Auto_Wait in M1 of an IntCycle), and the (IX+d) displacement cycles (MCycle 6,
3 T, and MCycle 7, 5 T in Mode 0). Prefix fetches (CB, ED, DD, FD) are M1s of their own, 4 T each.

mcycles(code, regs) -> [T-states of each machine cycle], prefixes included, for the instruction whose bytes
begin `code`, with regs (a dict as test_z80n's: af, bc, de, hl, ...) deciding conditions and repeats. z80n=False
treats the Z80N's opcodes as the Zilog's ED no-ops. Used by tests/test_mcycle.py and tools/gen_mcend.py.
"""

CF, NF, PF, HF, ZF, SF = 0x01, 0x02, 0x04, 0x10, 0x40, 0x80

# floooh's z80.h: which opcodes are (HL) instructions that a DD or FD turns into (IX+d) (its _z80_indirect_table)
INDIRECT = {0x34, 0x35, 0x36, 0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x77,
            0x7E, 0x86, 0x8E, 0x96, 0x9E, 0xA6, 0xAE, 0xB6, 0xBE}


def cc(f, y):
    """condition y (NZ Z NC C PO PE P M) on flags f"""
    return [not f & ZF, bool(f & ZF), not f & CF, bool(f & CF), not f & PF, bool(f & PF), not f & SF,
            bool(f & SF)][y]


def unprefixed(op, regs):
    """an unprefixed instruction (or one after DD/FD that doesn't use (HL)): its cycles after no prefix"""
    f, b = regs['af'] & 0xFF, regs['bc'] >> 8
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    if op == 0x76:
        return [4]                                          # HALT (then M1s of 4, each a cycle)
    if x == 1:
        return [4, 3] if 6 in (y, z) else [4]               # LD r,r'; LD r,(HL) / LD (HL),r
    if x == 2:
        return [4, 3] if z == 6 else [4]                    # ALU A,r / A,(HL)
    if x == 0:
        if z == 0:
            if y < 2:
                return [4]                                  # NOP, EX AF,AF'
            if y == 2:
                return [5, 3, 5] if (b - 1) & 0xFF else [5, 3]  # DJNZ: M1 5 (B-1), M2 the offset, M3 5
            if y == 3:
                return [4, 3, 5]                            # JR e
            return [4, 3, 5] if cc(f, y - 4) else [4, 3]    # JR cc,e
        if z == 1:
            return [4, 3, 3] if y % 2 == 0 else [4, 4, 3]   # LD rr,nn; ADD HL,rr (M2 4 T, M3 3, both NoRead)
        if z == 2:
            return [[4, 3], [4, 3], [4, 3], [4, 3], [4, 3, 3, 3, 3], [4, 3, 3, 3, 3], [4, 3, 3, 3], [4, 3, 3, 3]][y]
        if z == 3:
            return [6]                                      # INC rr / DEC rr: M1 6 T
        if z in (4, 5):
            return [4, 4, 3] if y == 6 else [4]             # INC/DEC r; INC/DEC (HL): M2 4 T, M3 write
        if z == 6:
            return [4, 3, 3] if y == 6 else [4, 3]          # LD r,n; LD (HL),n
        return [4]                                          # RLCA RRCA RLA RRA DAA CPL SCF CCF
    # x == 3
    if z == 0:
        return [5, 3, 3] if cc(f, y) else [5]               # RET cc: M1 5 T either way
    if z == 1:
        if y % 2 == 0:
            return [4, 3, 3]                                # POP rr
        return [[4, 3, 3], [4], [4], [6]][y // 2]           # RET, EXX, JP (HL), LD SP,HL (M1 6 T)
    if z == 2:
        return [4, 3, 3]                                    # JP cc,nn (the same, taken or not)
    if z == 3:
        return {0: [4, 3, 3], 2: [4, 3, 4], 3: [4, 3, 4], 4: [4, 3, 4, 3, 5], 5: [4], 6: [4], 7: [4]}[y]
        # JP nn; OUT (n),A and IN A,(n) (the I/O cycle 3 T + IOWait); EX (SP),HL; EX DE,HL; DI; EI
    if z == 4:
        return [4, 3, 4, 3, 3] if cc(f, y) else [4, 3, 3]   # CALL cc,nn: M3 4 T when taken
    if z == 5:
        return [5, 3, 3] if y % 2 == 0 else [4, 3, 4, 3, 3]  # PUSH rr (M1 5 T); CALL nn
    if z == 6:
        return [4, 3]                                       # ALU A,n
    return [5, 3, 3]                                        # RST p: M1 5 T


def cb(op):
    """after the CB fetch: the CB-prefixed instruction's own cycles"""
    x, z = op >> 6, op & 7
    if z != 6:
        return [4]                                          # on a register
    return [4, 4] if x == 1 else [4, 4, 3]                  # BIT b,(HL): M2 4 T; the rest: M2 4 T, M3 write


Z80N_ED = {0x23: [4], 0x24: [4], 0x27: [4, 3], 0x28: [4], 0x29: [4], 0x2A: [4], 0x2B: [4], 0x2C: [4],
           0x30: [4], 0x31: [4], 0x32: [4], 0x33: [4], 0x34: [4, 4, 4], 0x35: [4, 4, 4], 0x36: [4, 4, 4],
           0x8A: [4, 3, 3, 3, 3, 3], 0x90: [5, 3, 4], 0x91: [4, 3, 3, 3, 3], 0x92: [4, 3, 3, 3], 0x93: [4],
           0x94: [4], 0x95: [4], 0x98: [4, 5], 0xA5: [4, 3, 3]}
# (TEST n: M2 reads n; ADD rr,nn: TStates 4 for every cycle; PUSH nn: six cycles after ED; OUTINB: M1 5 T, its
# I/O cycle 3 + IOWait; NEXTREG r,v: M2..M5, r,A: M2..M4; JP (C): TStates 4 for both, the I/O + IOWait 5;
# LDWS: M3 3 T. The LDxX family is below with the block instructions.)


def ed(op, regs, z80n=True):
    """after the ED fetch: the ED-prefixed instruction's own cycles"""
    f, bc = regs['af'] & 0xFF, regs['bc']
    if z80n and op in Z80N_ED:
        return Z80N_ED[op]
    if z80n and op in (0xA4, 0xAC, 0xB4, 0xBC, 0xB6, 0xB7):  # LDIX LDDX LDIRX LDDRX (ED B6) LDPIRX: as LDI
        return [4, 3, 5] + ([5] if op & 0x10 and (bc - 1) & 0xFFFF else [])
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    if x == 1:
        if z in (0, 1):
            return [4, 4]                                   # IN r,(C) / OUT (C),r: the I/O cycle 3 + IOWait
        if z == 2:
            return [4, 4, 3]                                # SBC/ADC HL,rr
        if z == 3:
            return [4, 3, 3, 3, 3]                          # LD (nn),rr / LD rr,(nn)
        if z in (4, 6):
            return [4]                                      # NEG, IM n
        if z == 5:
            return [4, 3, 3]                                # RETN, RETI
        if y < 4:
            return [5]                                      # LD I,A  LD R,A  LD A,I  LD A,R: M1 5 T
        if y < 6:
            return [4, 3, 4, 3]                             # RRD, RLD: M3 4 T
        return [4]                                          # ED 77, ED 7F: no-ops
    if x == 2 and z < 4 and y >= 4:
        rep = y >= 6                                        # A0-A3, A8-AB, B0-B3, B8-BB
        if z == 0:                                          # LDI LDD LDIR LDDR
            return [4, 3, 5] + ([5] if rep and (bc - 1) & 0xFFFF else [])
        if z == 1:                                          # CPI CPD CPIR CPDR: repeat unless BC = 0 or found
            return [4, 3, 5] + ([5] if rep and (bc - 1) & 0xFFFF and regs.get('_cp', 1) != 0 else [])
        if z == 2:                                          # INI IND INIR INDR: M1 5 T, I/O 3 + IOWait
            return [5, 4, 3] + ([5] if rep and ((bc >> 8) - 1) & 0xFF else [])
        return [5, 3, 4] + ([5] if rep and ((bc >> 8) - 1) & 0xFF else [])  # OUTI OUTD OTIR OTDR
    return [4]                                              # the rest: no-ops


def mcycles(code, regs, z80n=True, mem=None):
    """the instruction at code[0]...: every machine cycle's T-states, prefix fetches included. `mem` (address ->
    byte) gives what CPI and friends compare; regs['_cp'] is set here from it."""
    op = code[0]
    if op == 0xCB:
        return [4] + cb(code[1])
    if op == 0xED:
        regs = dict(regs)
        if code[1] in (0xA1, 0xA9, 0xB1, 0xB9):
            regs['_cp'] = ((regs['af'] >> 8) - (mem or {}).get(regs['hl'], 0)) & 0xFF
        return [4] + ed(code[1], regs, z80n)
    if op in (0xDD, 0xFD):
        nxt = code[1]
        if nxt in (0xDD, 0xFD, 0xED):
            return [4] + mcycles(code[1:], regs, z80n, mem)  # a prefix that the next one replaces
        if nxt == 0xCB:                                     # DD CB d op: CB's M1, d (3), op (5), then the rest
            op2 = code[3]
            rest = [4] if op2 >> 6 == 1 else [4, 3]         # BIT: the read (4 T); the others: read 4, write 3
            return [4, 4, 3, 5] + rest
        if nxt in INDIRECT:                                 # (IX+d): M1, d (M6, 3), M7 (5), then the rest
            body = unprefixed(nxt, regs)
            rest = [3] if nxt == 0x36 else body[1:]         # LD (IX+d),n reads n inside M7: then the write
            return [4, 4, 3, 5] + rest
        return [4] + unprefixed(nxt, regs)                  # IX/IY for HL, or a plain instruction after DD/FD
    return unprefixed(op, regs)


def interrupt(mode):
    """the interrupt acknowledge, after the instruction it follows: IM 0 and IM 1 as RST 38h (the Next's bus
    gives FFh) with M1 5 T + 2 auto-waits; IM 2: M1 5 + 2, the two pushes, the two vector reads"""
    return [7, 3, 3] if mode in (0, 1) else [7, 3, 3, 3, 3]


NMI = [5, 3, 3]                                             # the NMI response: M1 5 T, the two pushes
