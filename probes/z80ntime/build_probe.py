"""Build Z80NTIME.TAP: time every Z80N instruction on a real ZX Spectrum Next, and check its flags where the
Next's VHDL and the documentation disagree.  Fern, Fri 6 Nov 2026, for the test machine (Tally Fern's project).

  build_probe.py            writes z80ntime.asm, build/z80ntime.bin, build/Z80NTIME.TAP, build/expected.txt

How it times: interrupts on in IM 2 (a table at BD00h, a handler at BEBEh), every other interrupt source off
(nextreg C4h-C6h), code and data in bank 2 (8000h-BFFFh, uncontended). A test is a setup and then a loop,
`body; INC IY; JP (IX)`, started by one frame interrupt and stopped by the next: IY counts the loops that fit in
a frame. At 3.5 MHz a NOP loop calibrates the frame (W = n x 22 + 11 T-states, the + 11 for the loop the
interrupt cuts short), and a body's T-states are W / n - 18 (the INC IY and JP (IX)) - its helpers' (standard
Z80 timings, which the T80N keeps). At 28 MHz the window is 8 x (W + 119) - 146 (the frame is 8 times the
T-states; 119 and 146 are the dead time from the interrupt to the loop at each speed, the second with one wait
on every read), the loop's own overhead is measured (an empty loop), and so are LDIX's helpers. The Next does
the arithmetic (8.8 fixed point) and prints each T rounded, with * where it isn't what the VHDL says and ? where
the fraction is far from whole (something else took time).

Checks every TAP block's checksum before writing it (omse-ai's tape trap doesn't).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PASMO = Path(__import__('os').environ.get('PASMO', 'pasmo'))   # pasmo on PATH, or $PASMO
SCRATCH = 0xBB00
ED = 'db 0xED,'

# 3.5 MHz: (label, setup, body, helpers' T, the VHDL's T for the instruction). Operands are bytes that are harmless
# as instructions (00, or 3C: INC A; 7F 40: LD A,A and LD B,B), so a CPU without the Z80N, which runs them, survives.
T35 = [
    ('23', '', ED + '0x23', 0, 8),                                       # SWAPNIB
    ('24', '', ED + '0x24', 0, 8),                                       # MIRROR A
    ('27', '', ED + '0x27,0x3C', 0, 11),                                 # TEST n
    ('28', 'ld b,5', ED + '0x28', 0, 8),                                 # BSLA DE,B
    ('29', 'ld b,5', ED + '0x29', 0, 8),                                 # BSRA DE,B
    ('2A', 'ld b,5', ED + '0x2A', 0, 8),                                 # BSRL DE,B
    ('2B', 'ld b,5', ED + '0x2B', 0, 8),                                 # BSRF DE,B
    ('2C', 'ld b,5', ED + '0x2C', 0, 8),                                 # BRLC DE,B
    ('30', '', ED + '0x30', 0, 8),                                       # MUL D,E
    ('31', '', ED + '0x31', 0, 8),                                       # ADD HL,A
    ('32', '', ED + '0x32', 0, 8),                                       # ADD DE,A
    ('33', '', ED + '0x33', 0, 8),                                       # ADD BC,A
    ('34', '', ED + '0x34,0x00,0x00', 0, 16),                            # ADD HL,nn
    ('35', '', ED + '0x35,0x00,0x00', 0, 16),                            # ADD DE,nn
    ('36', '', ED + '0x36,0x00,0x00', 0, 16),                            # ADD BC,nn
    ('8A', '', ED + '0x8A,0x00,0x00\n        pop af', 10, 23),           # PUSH nn (and POP AF, 10)
    ('90', f'ld bc,0x243B\n        ld hl,{SCRATCH}', ED + '0x90', 0, 16),  # OUTINB, to the nextreg select port
    ('91', '', ED + '0x91,0x7F,0x40', 0, 20),                            # NEXTREG 7Fh,40h (user register 0)
    ('92', 'ld a,0x40', ED + '0x92,0x7F', 0, 17),                        # NEXTREG 7Fh,A
    ('93', 'ld hl,0x4000', ED + '0x93', 0, 8),                           # PIXELDN
    ('94', '', ED + '0x94', 0, 8),                                       # PIXELAD
    ('95', '', ED + '0x95', 0, 8),                                       # SETAE
    ('98', 'ld bc,0x253B', ED + '0x98', 0, 13),                          # JP (C): lands on a pad, which loops
    ('A5', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x80}', ED + '0xA5\n        dec l\n        dec d', 8, 14),
    ('A4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xA4\n        inc bc\n        dec hl\n        dec de', 18, 16),          # LDIX, copying
    ('a4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        xor a',
     ED + '0xA4\n        inc bc\n        dec hl\n        dec de', 18, 16),          # LDIX, skipping (byte = A)
    ('AC', f'ld hl,{SCRATCH + 8}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xAC\n        inc bc\n        inc hl\n        dec de', 18, 16),          # LDDX
    ('B4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xB4\n        inc bc\n        dec hl\n        dec de', 18, 16),          # LDIRX, BC = 1
    ('b4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,2\n        ld a,0x55',
     ED + '0xB4\n        ld bc,2\n        dec hl\n        dec hl\n        dec de\n        dec de', 34, 37),  # BC = 2
    ('BC', f'ld hl,{SCRATCH + 8}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xBC\n        inc bc\n        inc hl\n        dec de', 18, 16),          # LDDRX, BC = 1
    ('bc', f'ld hl,{SCRATCH + 8}\n        ld de,{SCRATCH + 0x40}\n        ld bc,2\n        ld a,0x55',
     ED + '0xBC\n        ld bc,2\n        inc hl\n        inc hl\n        dec de\n        dec de', 34, 37),
    ('B6', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xB6\n        inc bc\n        dec hl\n        dec de', 18, 16),          # ED B6 (undocumented)
    ('b6', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,2\n        ld a,0x55',
     ED + '0xB6\n        ld bc,2\n        dec hl\n        dec hl\n        dec de\n        dec de', 34, 37),
    ('B7', f'ld hl,{SCRATCH + 0x10}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xB7\n        inc bc\n        dec de', 12, 16),                          # LDPIRX, BC = 1
    ('b7', f'ld hl,{SCRATCH + 0x10}\n        ld de,{SCRATCH + 0x40}\n        ld bc,2\n        ld a,0x55',
     ED + '0xB7\n        ld bc,2\n        dec de\n        dec de', 22, 37),         # BC = 2
    ('57', '', ED + '0x57', 0, 9),                                       # LD A,I: a standard one, as a check
]

# 28 MHz: (label, setup, body, helper: 0 or 'hh' (subtract the measured hh), the T the VHDL leads me to expect:
# one wait on every memory read, fetches too (zxnext.vhd's sram_wait_n at cpu_speed 11), none on writes or I/O)
T28 = [
    ('00', '', 'nop', 0, 5),
    ('hh', '', 'inc bc\n        dec hl\n        dec de', 0, 21),
    ('30', '', ED + '0x30', 0, 10),
    ('27', '', ED + '0x27,0x3C', 0, 14),
    ('34', '', ED + '0x34,0x00,0x00', 0, 20),
    ('91', '', ED + '0x91,0x7F,0x40', 0, 26),
    ('92', 'ld a,0x40', ED + '0x92,0x7F', 0, 22),
    ('98', 'ld bc,0x253B', ED + '0x98', 0, 15),
    ('90', f'ld bc,0x243B\n        ld hl,{SCRATCH}', ED + '0x90', 0, 19),
    ('A4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        ld a,0x55',
     ED + '0xA4\n        inc bc\n        dec hl\n        dec de', 'hh', 19),
    ('a4', f'ld hl,{SCRATCH}\n        ld de,{SCRATCH + 0x40}\n        ld bc,1\n        xor a',
     ED + '0xA4\n        inc bc\n        dec hl\n        dec de', 'hh', 20),             # the skip is a read: + 1
    ('lp', '', '', 'lp', 22),                                                           # the loop itself
]

# Flags (and two registers), run once each: (label, code, result: 'f' or 'hl', the VHDL's, what else it would be)
FLAGS = [
    ('31 F', 'ld hl,0x01FF\n        push hl\n        pop af\n        ld hl,0x1234\n        ' + ED + '0x31', 'f', 0xFE,
     'FF if ADD HL,A kept carry'),
    ('A5 F', f'ld hl,{SCRATCH}\n        ld de,0xBB40\n        ld bc,0x00FF\n        push bc\n        pop af\n        '
     + ED + '0xA5', 'f', 0xA8, 'A9 if INC D (carry kept)'),
    ('A4 F', f'ld hl,0x00FF\n        push hl\n        pop af\n        ld hl,{SCRATCH + 0x20}\n        ld (hl),0x0A\n'
     f'        ld de,{SCRATCH + 0x60}\n        ld bc,2\n        ' + ED + '0xA4', 'f', 0xED, 'FF if flags kept'),
    ('B7 F', f'ld hl,0x0200\n        push hl\n        pop af\n        ld hl,{SCRATCH + 0x30}\n        ld (hl),0x08\n'
     f'        ld de,{SCRATCH + 0x68}\n        ld bc,1\n        ' + ED + '0xB7', 'f', 0x08,
     '28 if from A+byte, 00 if kept'),
    ('93HL', 'ld hl,0x5FE0\n        ' + ED + '0x93', 'hl', 0x4000, '6000 by the documented rule'),
    ('27 F', 'ld hl,0xF0FF\n        push hl\n        pop af\n        ' + ED + '0x27,0x3C', 'f', 0x34, 'AND n'),
    ('BITF', f'ld hl,0\n        push hl\n        pop af\n        ld hl,{SCRATCH + 0x70}\n        ld (hl),1\n'
     '        ld bc,0x28FF\n        ld a,(bc)\n        bit 0,(hl)', 'f', 0x10, '38 on a Zilog (MEMPTR 29xx)'),
    ('SCFF', 'xor a\n        cp 0x28\n        nop\n        scf', 'f', 0x81, 'A9 on a Zilog (Q)'),
]


def tap_block(flag, data):
    body = bytes([flag]) + data
    ck = 0
    for b in body:
        ck ^= b
    return len(body + bytes([ck])).to_bytes(2, 'little') + body + bytes([ck])


def check_tap(tap):
    """Every block's XOR checksum, as a real loader checks it (omse-ai's instant tape trap doesn't)."""
    i, blocks = 0, 0
    while i < len(tap):
        n = int.from_bytes(tap[i:i + 2], 'little')
        blk = tap[i + 2:i + 2 + n]
        x = 0
        for v in blk:
            x ^= v
        assert n >= 2 and len(blk) == n and x == 0, f"bad TAP block at offset {i}"
        i += 2 + n
        blocks += 1
    return blocks


def header(kind, name, length, p1, p2):
    return tap_block(0, bytes([kind]) + name.ljust(10)[:10].encode() + length.to_bytes(2, 'little')
                     + p1.to_bytes(2, 'little') + p2.to_bytes(2, 'little'))


def num(n):
    return str(n).encode() + bytes([0x0E, 0, 0]) + n.to_bytes(2, 'little') + b'\x00'


def tests_asm(table, prefix):
    out = []
    for k, (label, setup, body, helper, pred) in enumerate(table):
        name = f'{prefix}{k}'
        out.append(f'{name}:')
        if setup:
            out.append(f'        {setup}')
        out += [f'        ld ix,{name}l', f'{name}l:']
        if body:
            out.append(f'        {body}')
        out += ['        inc iy', '        jp (ix)']
    out.append(f'{prefix}tab:')
    for k, (label, setup, body, helper, pred) in enumerate(table):
        h = {'hh': 0xFF, 'lp': 0xFE}.get(helper, helper)
        out.append(f'        dw {prefix}{k}\n        db "{label}",{h},{pred}')
    out.append('        dw 0')
    out.append(f'{prefix}res: ds {2 * len(table)}')
    out.append(f'{prefix}n EQU {len(table)}')
    return '\n'.join(out)


def flags_asm():
    out = []
    for k, (label, code, kind, pred, other) in enumerate(FLAGS):
        out.append(f'flg{k}:  {code}')
        if kind == 'f':
            out += ['        push af', '        pop hl', '        ld h,0']
        out += [f'        ld (flres+{2 * k}),hl', '        ret']
    out.append('fltab:')
    for k, (label, code, kind, pred, other) in enumerate(FLAGS):
        out.append(f'        dw flg{k}\n        db "{label}",{1 if kind == "hl" else 0}\n        dw {pred}')
    out.append('        dw 0')
    out.append(f'flres: ds {2 * len(FLAGS)}')
    return '\n'.join(out)


ASM = r'''; z80ntime.asm: times every Z80N instruction on a real ZX Spectrum Next and checks the flags where the Next's
; VHDL and the documentation disagree.  Generated by build_probe.py (Fern, Fri 6 Nov 2026); see its docstring.
; Run from BASIC (CLEAR 32767: LOAD "" CODE: RANDOMIZE USR 32768); it prints one screen, waits for a key, returns.

PREG    EQU 0x243B              ; nextreg select
PDAT    EQU 0x253B              ; nextreg data
STACK   EQU 0xBD00              ; grows down through BCxx: above SCRATCH's page, below IMTAB
IMTAB   EQU 0xBD00              ; 257 bytes of BEh: IM 2 goes to BEBEh whatever the bus says
HANDLER EQU 0xBEBE
PAD1    EQU 0x9000              ; where JP (C) lands on a Next (user register 7Fh = 40h)
PAD2    EQU 0xBFC0              ; where it lands if the port reads FFh (omse-ai's 48K)
SCRATCH EQU {SCRATCH}
D35     EQU 119                 ; T-states from the interrupt to a loop, at 3.5 MHz
D28     EQU 147                 ; ... and at 28 MHz (one wait on every read: 28 of them)
O35     EQU 18                  ; INC IY (10) and JP (IX) (8)

        org 0x8000
start:  di
        ld (bas_sp),sp
        ld sp,STACK
        push ix                 ; BASIC's IX and IY, back at the end
        ld (bas_iy),iy
        ld a,i
        ld (bas_i),a
        call cls
        ld hl,s_title
        call pstr
        ld hl,nrsave            ; what the Next is, and what we change
        ld de,nrlist
nr0:    ld a,(de)
        cp 0xFF
        jr z,nr1
        push de
        push hl
        call nr_read
        pop hl
        pop de
        ld (hl),a
        inc hl
        inc de
        jr nr0
nr1:    ld hl,s_wait
        call pstr
        ld hl,SCRATCH           ; the LDxX tests' bytes: zeros
        ld de,SCRATCH+1
        ld bc,255
        ld (hl),0
        ldir
        ld hl,IMTAB             ; the interrupt table, its handler, JP (C)'s pads
        ld de,IMTAB+1
        ld bc,256
        ld (hl),HANDLER/256
        ldir
        ld hl,handler
        ld de,HANDLER
        ld bc,handler_end-handler
        ldir
        ld hl,pad
        ld de,PAD1
        ld bc,2+2
        ldir
        ld hl,pad
        ld de,PAD2
        ld bc,2+2
        ldir
        ; (nextregs through the ports, not NEXTREG: harmless on a Spectrum without them)
        ld a,0xC4               ; only the ULA's frame interrupt
        ld e,0x01
        call nr_write
        ld a,0xC5               ; no CTC
        ld e,0
        call nr_write
        ld a,0xC6               ; no UART
        ld e,0
        call nr_write
        ld a,0x07               ; 3.5 MHz
        ld e,0
        call nr_write
        ld a,0x7F               ; what JP (C) reads
        ld e,0x40
        call nr_write
        call sel7f
        ld a,IMTAB/256
        ld i,a
        im 2
        ; 3.5 MHz: calibrate, then every test
        ld hl,tcal
        call measure            ; (a warm-up)
        ld hl,tcal
        call measure
        ld (ncal),hl
        call times22            ; W35 = n x 22 + 11
        ld bc,11
        add hl,bc
        jr nc,cw1
        inc de
cw1:    ld (w35),hl
        ld (w35+2),de
        ld hl,O35*256
        ld (o88),hl
        ld hl,w35
        ld de,ttab
        ld bc,tres
        call run_table
        ; 28 MHz: the window from the frame, the loop's overhead measured, then the tests
        ld a,0x07               ; 28 MHz
        ld e,0x03
        call nr_write
        ld a,0x07
        call nr_read
        ld (speed28),a
        ld hl,(w35)             ; W28 = 8 x (W35 + D35) - D28
        ld de,(w35+2)
        ld bc,D35
        add hl,bc
        jr nc,cx1
        inc de
cx1:    ld b,3
cx2:    add hl,hl
        rl e
        rl d
        djnz cx2
        ld bc,D28
        or a
        sbc hl,bc
        jr nc,cx3
        dec de
cx3:    ld (w28),hl
        ld (w28+2),de
        ld hl,uempty
        call measure            ; (a warm-up at the new speed)
        ld hl,uempty
        call measure
        ld (nempty),hl
        ld hl,0
        ld (o88),hl
        ld hl,w28
        ld b,h
        ld c,l
        ld hl,(nempty)
        call q88                ; O28 = W28 / n, 8.8
        ld (o88),hl
        ld hl,w28
        ld de,utab
        ld bc,ures
        call run_table
        ; back to how it was
        ld a,(sv07)
        and 3
        ld e,a
        ld a,0x07
        call nr_write
        ld a,(svc4)
        ld e,a
        ld a,0xC4
        call nr_write
        ld a,(svc5)
        ld e,a
        ld a,0xC5
        call nr_write
        ld a,(svc6)
        ld e,a
        ld a,0xC6
        call nr_write
        ld a,(sv7f)
        ld e,a
        ld a,0x7F
        call nr_write
        im 1
        ld a,(bas_i)
        ld i,a
        ld hl,fltab             ; the flags, once each
fl0:    ld e,(hl)
        inc hl
        ld d,(hl)
        ld a,d
        or e
        jr z,fl1
        push hl
        ex de,hl
        call jphl
        pop hl
        ld bc,8                 ; past the address's high byte, the label, the kind and the VHDL's value
        add hl,bc
        jr fl0
fl1:    call report
        call photobeep          ; the photo beep (Melissa O'Neill's idea, Tally Fern's spec; ../beep.inc), added by Hart's-tongue
        call waitkey            ; a photo, then a key (Melissa O'Neill's rule: so it can run from the menu)
        ld iy,(bas_iy)
        pop ix
        ld sp,(bas_sp)
        ei
        ret

jphl:   jp (hl)

waitkey:                        ; any key, through port FEh (interrupts off): let go first, then a press
        xor a
        in a,(0xFE)
        cpl
        and 0x1F
        jr nz,waitkey
wk1:    xor a
        in a,(0xFE)
        cpl
        and 0x1F
        jr z,wk1
        ret

sel7f:  ld bc,PREG              ; select user register 7Fh at 253Bh (for JP (C))
        ld a,0x7F
        out (c),a
        ret

nr_write:                       ; nextreg A = E
        ld bc,PREG
        out (c),a
        inc b
        out (c),e
        ret

nr_read:                        ; A = a nextreg's value
        ld bc,PREG
        out (c),a
        inc b
        in a,(c)
        ret

; Run a table of tests: HL = the window (4 bytes), DE = the table, BC = where the results go (8.8 T each)
run_table:
        ld (rt_w),hl
        ld (rt_res),bc
rt0:    ld a,(de)
        ld l,a
        inc de
        ld a,(de)
        ld h,a
        inc de
        or l
        ret z
        push de
        call sel7f              ; (OUTINB's test writes the select port)
        call measure            ; HL = loops in the window
        ld bc,(rt_w)
        call q88                ; HL = window / n - overhead, 8.8
        pop de
        inc de                  ; past the label
        inc de
        ld a,(de)               ; the helpers' T
        inc de
        inc de                  ; past the prediction
        cp 0xFF
        jr z,rt_hh
        cp 0xFE
        jr z,rt_lp
        push de
        ld d,a                  ; helpers x 256
        ld e,0
        or a
        sbc hl,de
        pop de
        jr rt_st
rt_lp:  push de                 ; the loop itself: put its overhead back
        ld de,(o88)
        add hl,de
        pop de
        jr rt_st
rt_hh:  push de                 ; subtract the measured helpers (the 28 MHz table's second entry)
        ld de,(ures+2)
        or a
        sbc hl,de
        pop de
rt_st:  push de
        ld de,(rt_res)
        ex de,hl
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld (rt_res),hl
        pop de
        jr rt0

; HL = n, BC = the window's address: HL = (window x 256) / n - (o88), as 8.8 (FFFFh if it won't fit)
q88:    push hl
        ld h,b
        ld l,c
        ld de,dnum+1            ; window << 8
        ld bc,3
        ldir
        xor a
        ld (dnum),a
        pop bc
        call div32
        ld a,(dnum+2)
        ld hl,dnum+3
        or (hl)
        ld hl,0xFFFF
        ret nz
        ld hl,(dnum)
        ld de,(o88)
        or a
        sbc hl,de
        ret

; DE:HL = HL x 22 (= x 16 + x 4 + x 2; under 2^21, so D stays 0)
times22:
        ld de,0
        add hl,hl               ; x 2
        rl e
        push de
        push hl
        add hl,hl               ; x 4
        rl e
        push de
        push hl
        add hl,hl               ; x 8
        rl e
        add hl,hl               ; x 16
        rl e
        pop bc                  ; + x 4
        add hl,bc
        pop bc
        ld a,e
        adc a,c
        ld e,a
        pop bc                  ; + x 2
        add hl,bc
        pop bc
        ld a,e
        adc a,c
        ld e,a
        ret

; (dnum) 4 bytes / BC -> quotient in (dnum); (drem) 3 bytes
div32:  xor a
        ld (drem),a
        ld (drem+1),a
        ld (drem+2),a
        ld (dden),bc
        ld b,32
dv1:    ld hl,dnum
        sla (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,drem
        rl (hl)
        inc hl
        rl (hl)
        inc hl
        rl (hl)
        ld hl,(drem)
        ld de,(dden)
        or a
        sbc hl,de
        ld a,(drem+2)
        sbc a,0
        jr c,dv2
        ld (drem),hl
        ld (drem+2),a
        ld hl,dnum
        set 0,(hl)
dv2:    djnz dv1
        ret

; HL = a test's entry: run it from one frame interrupt to the next; HL = how many loops
measure:
        ld (m_go+1),hl
        ld (m_sp),sp
        xor a
        ld (istate),a
        ld iy,0
        ei
        halt                    ; the frame interrupt (its handler's first call returns here)
m_go:   jp 0
m_done: ld sp,(m_sp)            ; (its second call comes here, interrupts off)
        push iy
        pop hl
        ld iy,(bas_iy)
        ret

handler:                        ; copied to HANDLER
        push af
        ld a,(istate)
        or a
        jr nz,h_stop
        inc a
        ld (istate),a
        pop af
        ei
        ret
h_stop: jp m_done
handler_end:

pad:    inc iy                  ; copied to PAD1 and PAD2: JP (C) lands here
        jp (ix)

tcal:   ld ix,tcall             ; the calibration: NOP, 4 T
tcall:  nop
        inc iy
        jp (ix)

uempty: ld ix,uemptyl           ; the loop alone, at 28 MHz
uemptyl:
        inc iy
        jp (ix)

{TESTS35}

{TESTS28}

{FLAGS}

; -- printing -------------------------------------------------------------------------------------------
cls:    call 0x0DAF
        ld a,2
        call 0x1601
        ld a,255
        ld (0x5C8C),a           ; SCR_CT: never "scroll?"
        ret

putc:   push bc                 ; A to the screen (A comes back changed)
        push de
        push hl
        rst 0x10
        pop hl
        pop de
        pop bc
        ret

pstr:   ld a,(hl)
        or a
        ret z
        call putc
        inc hl
        jr pstr

phex2:  push af
        rrca
        rrca
        rrca
        rrca
        call phex1
        pop af
phex1:  and 15
        add a,0x90
        daa
        adc a,0x40
        daa
        jp putc

pdec3:                          ; HL = 0..999, right-aligned in three ("###" if more)
        ld de,1000
        or a
        sbc hl,de
        add hl,de
        jr nc,pd_big
        ld c,' '
        ld de,100
        call pd_dig
        ld de,10
        call pd_dig
        ld a,l
        add a,'0'
        jp putc
pd_big: ld hl,s_big
        jp pstr
pd_dig: ld a,'0'-1
pd1:    inc a
        or a
        sbc hl,de
        jr nc,pd1
        add hl,de
        cp '0'
        jr nz,pd2
        ld a,c
        jp putc
pd2:    ld c,'0'
        jp putc

; Print a table's results: DE = the table, HL = its results; B = how many matched (out), C = count (out)
ptable: xor a
        ld (pt_ok),a
        ld (pt_n),a
pt0:    ld a,(de)
        inc de
        ld c,a
        ld a,(de)
        inc de
        or c
        jr z,pt9
        ld a,(de)               ; the label
        inc de
        call putc
        ld a,(de)
        inc de
        call putc
        inc de                  ; the helpers
        ld a,(de)               ; the VHDL's T
        inc de
        ld (pt_pred),a
        push de
        ld e,(hl)               ; the result, 8.8
        inc hl
        ld d,(hl)
        inc hl
        push hl
        ex de,hl
        ld a,h                  ; negative (bit 15): "  -"
        and 0x80
        jr z,pt1
        ld hl,s_neg
        call pstr
        ld a,'?'
        jr pt3
pt1:    ld a,l                  ; the fraction far from whole?
        ld (pt_frac),a
        ld de,0x0080            ; rounded
        add hl,de
        ld l,h
        ld h,0
        push hl
        call pdec3
        pop hl
        ld a,(pt_frac)
        sub 0x41
        cp 0x7F
        ld a,'?'
        jr c,pt3
        ld a,(pt_pred)
        cp l
        ld a,'*'
        jr nz,pt3
        ld a,(pt_ok)
        inc a
        ld (pt_ok),a
        ld a,' '
pt3:    call putc
        ld a,' '
        call putc
        ld a,' '                ; (the ROM's printing changes A)
        call putc
        ld a,(pt_n)
        inc a
        ld (pt_n),a
        pop hl
        pop de
        jr pt0
pt9:    ld a,(pt_ok)
        ld b,a
        ld a,(pt_n)
        ld c,a
        ret

report: call cls
        ld hl,s_title
        call pstr
        ld a,(sv01)             ; core major.minor.sub, machine id, mmu4/5, type, speed
        rrca
        rrca
        rrca
        rrca
        and 15
        add a,'0'
        call putc
        ld a,'.'
        call putc
        ld a,(sv01)
        and 15
        call pdec2z
        ld a,'.'
        call putc
        ld a,(sv0e)
        call pdec2z
        ld hl,s_id
        call pstr
        ld a,(sv00)
        call phex2
        ld hl,s_mmu
        call pstr
        ld a,(sv54)
        call phex2
        ld a,' '
        call putc
        ld a,(sv55)
        call phex2
        ld hl,s_type
        call pstr
        ld a,(sv03)
        call phex2
        ld hl,s_cpu
        call pstr
        ld a,(sv07)
        call phex2
        ld a,'/'
        call putc
        ld a,(speed28)
        call phex2
        ld a,13
        call putc
        ld hl,s_35
        call pstr
        ld de,ttab
        ld hl,tres
        call ptable
        ld (ok35),bc
        ld hl,s_28
        call pstr
        ld de,utab
        ld hl,ures
        call ptable
        ld (ok28),bc
        ld hl,s_fl
        call pstr
        call pflags
        ld (okfl),bc
        ld hl,s_sum             ; the verdict: how many as the VHDL says
        call pstr
        ld bc,(ok35)
        call pfrac
        ld a,' '
        call putc
        ld bc,(ok28)
        call pfrac
        ld a,' '
        call putc
        ld bc,(okfl)
        call pfrac
        ld hl,s_key
        jp pstr

pfrac:  push bc                 ; "B/C"
        ld l,b
        ld h,0
        call pdec2
        ld a,'/'
        call putc
        pop bc
        ld l,c
        ld h,0
        jp pdec2

pdec2z: ld b,'0'-1              ; A = 0..99 as two digits
pz1:    inc b
        sub 10
        jr nc,pz1
        add a,10+'0'
        push af
        ld a,b
        call putc
        pop af
        jp putc

pdec2:  ld de,100               ; HL = 0..99 without leading spaces (or as pdec3 if more)
        or a
        sbc hl,de
        add hl,de
        jp nc,pdec3
        ld de,10
        or a
        sbc hl,de
        add hl,de
        jr c,pdec1
        ld c,'0'
        call pd_dig
pdec1:  ld a,l
        add a,'0'
        jp putc

pflags: xor a                   ; two to a line: "LLLL vv/pp*  " (16)
        ld (pt_ok),a
        ld (pt_n),a
        ld de,fltab
        ld hl,flres
pf0:    ld a,(de)
        inc de
        ld c,a
        ld a,(de)
        inc de
        or c
        jr z,pf9
        ld b,4
pf1:    ld a,(de)
        inc de
        call putc
        djnz pf1
        ld a,' '
        call putc
        ld a,(de)               ; 1: a 16-bit result
        inc de
        ld (pt_frac),a
        ld a,(de)               ; the VHDL's
        ld c,a
        inc de
        ld a,(de)
        ld b,a
        inc de
        push de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        push hl
        push bc
        ld a,(pt_frac)
        or a
        jr z,pf2
        ld a,d
        call phex2
pf2:    ld a,e
        call phex2
        ld a,'/'
        call putc
        pop bc
        ld a,(pt_frac)
        or a
        jr z,pf3
        ld a,b
        call phex2
pf3:    ld a,c
        call phex2
        ld a,e                  ; match?
        cp c
        jr nz,pf4
        ld a,d
        cp b
        jr nz,pf4
        ld a,(pt_ok)
        inc a
        ld (pt_ok),a
        ld a,' '
        jr pf5
pf4:    ld a,'*'
pf5:    call putc
        ld a,(pt_frac)          ; pad to 16
        or a
        ld b,1
        jr nz,pf6
        ld b,5
pf6:    ld a,' '
        call putc
        djnz pf6
        ld a,(pt_n)
        inc a
        ld (pt_n),a
        pop hl
        pop de
        jr pf0
pf9:    ld a,(pt_ok)
        ld b,a
        ld a,(pt_n)
        ld c,a
        ret

s_title: db "Z80NTIME core ",0
s_id:   db " id ",0
s_mmu:  db 13,"mmu ",0
s_type: db " type ",0
s_cpu:  db " cpu ",0
s_wait: db 13,"timing every Z80N instruction...",0
s_35:   db "3.5 MHz, T-states (*: not VHDL)",13,0
s_28:   db "28 MHz, T-states",13,0
s_fl:   db "flags got/VHDL",13,0
s_sum:  db "as VHDL: ",0
s_big:  db "###",0
s_neg:  db "  -",0
s_key:  db " (key)",0

nrlist: db 0x00,0x01,0x0E,0x03,0x07,0x54,0x55,0xC4,0xC5,0xC6,0x7F,0xFF
nrsave:
sv00:   db 0
sv01:   db 0
sv0e:   db 0
sv03:   db 0
sv07:   db 0
sv54:   db 0
sv55:   db 0
svc4:   db 0
svc5:   db 0
svc6:   db 0
sv7f:   db 0
speed28: db 0
bas_sp: dw 0
bas_iy: dw 0
bas_i:  db 0
istate: db 0
m_sp:   dw 0
ncal:   dw 0
nempty: dw 0
w35:    ds 4
w28:    ds 4
o88:    dw 0
rt_w:   dw 0
rt_res: dw 0
dnum:   ds 4
drem:   ds 3
dden:   dw 0
pt_ok:  db 0
pt_n:   db 0
pt_pred: db 0
pt_frac: db 0
ok35:   dw 0
ok28:   dw 0
okfl:   dw 0
TAPEID  equ 60                ; the photo beep's tape ID (../NOTES.md, "The photo beep")
        include "../beep.inc"
endcode:
'''


def main():
    asm = (ASM.replace('{SCRATCH}', str(SCRATCH)).replace('{TESTS35}', tests_asm(T35, 't'))
           .replace('{TESTS28}', tests_asm(T28, 'u')).replace('{FLAGS}', flags_asm()))
    (HERE / 'z80ntime.asm').write_text(asm)
    out = HERE / 'build'
    out.mkdir(exist_ok=True)
    r = subprocess.run([str(PASMO), '--bin', 'z80ntime.asm', str(out / 'z80ntime.bin'), str(out / 'z80ntime.sym')],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    code = (out / 'z80ntime.bin').read_bytes()
    assert 0x8000 + len(code) <= 0x9000, f'the code reaches {0x8000 + len(code):04X}: JP (C) lands at 9000h'
    line = bytes([0xFD]) + num(32767) + b':' + bytes([0xEF]) + b'""' + bytes([0xAF]) + b':' + \
        bytes([0xF9, 0xC0]) + num(32768) + b'\r'
    prog = (10).to_bytes(2, 'big') + len(line).to_bytes(2, 'little') + line
    tap = header(0, 'z80ntime', len(prog), 10, len(prog)) + tap_block(0xFF, prog)
    tap += header(3, 'z80ncode', len(code), 32768, 32768) + tap_block(0xFF, code)
    blocks = check_tap(tap)
    (out / 'Z80NTIME.TAP').write_bytes(tap)
    exp = ['What Z80NTIME should print on the test machine if the T80N VHDL (core 3.02.02) is right:', '']
    exp.append('3.5 MHz (label, T):')
    exp += ['  ' + '  '.join(f'{lab}{pred:>3}' for lab, _, _, _, pred in T35[i:i + 4]) for i in range(0, len(T35), 4)]
    exp.append('28 MHz (one wait on every memory read, fetches included; none on writes or I/O):')
    exp += ['  ' + '  '.join(f'{lab}{pred:>3}' for lab, _, _, _, pred in T28[i:i + 4]) for i in range(0, len(T28), 4)]
    exp.append('flags (label, VHDL, otherwise):')
    exp += [f'  {lab}  {pred:0{4 if kind == "hl" else 2}X}  ({other})' for lab, _, kind, pred, other in FLAGS]
    (out / 'expected.txt').write_text('\n'.join(exp) + '\n')
    print(f'Z80NTIME.TAP: {len(tap)} bytes, {blocks} blocks, checksums good (code {len(code)}, to '
          f'{0x8000 + len(code):04X})')


if __name__ == '__main__':
    main()
