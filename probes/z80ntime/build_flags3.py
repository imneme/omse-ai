"""Build Z80NFLG2.TAP: Z80NFLAG's second half, from F = FF. Strobe Fern, Fri 6 Nov 2026.

  build_flags3.py          writes z80nflg2.asm, build/z80nflg2.bin, build/Z80NFLG2.TAP

the test machine agreed with the T80N's VHDL in all five of Z80NFLAG's cells, but those began from F = 00, so two
things still rested on the VHDL alone. This tape asks them on silicon:
  LD A,I, LD A,R and IN A,(C): are X and Y left as they were (the T80N's VHDL), or cleared? From F = FF with a value
      whose bits 3 and 5 are clear, "left" gives X and Y set and a Zilog (or "cleared") gives them clear;
  OUTI's flags as the ALU's SUB B,1: from B = 00 the borrow sets C (and H); from B = 80h, V is set and C, from FF,
      is cleared. OUTI, not INI, because its port is known and harmless: (B-1)C = FFFE / 7FFE, the ULA's, written
      07 (a white border; the border is put back from BORDCR after).
Each cell starts with A = 00 and F = FFh and prints what F became, what the T80N's VHDL says, and what a Zilog gives
(the OUTI cells' Zilog values as floooh's z80.h, which passes the FUSE tests, computes them). IN A,(C) reads nextreg
7Fh (user register 0) set to 00 through the ports, and puts it back. I is put back; R is left (nothing uses it).
Interrupts off; one screen; the photo beep (tape 65); "photo, then press a key"; returns to BASIC.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_flags2 import build, SCR  # noqa: E402

FF = '''ld de,0x00FF
        push de
        pop af'''
CELLS = [  # (label (8), code, T80N's F, a Zilog's F)
    ('OUTI B00', f'''ld hl,{SCR + 0xF0}
        ld (hl),0x07
        ld bc,0x00FE            ; B-1 = FFh: out to FFFEh, the ULA (border 7)
        {FF}
        db 0xED,0xA3            ; OUTI''', 0xBB, 0xAC),
    ('OUTI B80', f'''ld hl,{SCR + 0xE0}
        ld (hl),0x07
        ld bc,0x80FE            ; B-1 = 7Fh: out to 7FFEh, the ULA (border 7)
        {FF}
        db 0xED,0xA3            ; OUTI''', 0x3E, 0x28),
    ('LD A,I  ', f'''ld a,i
        ld (savi),a
        xor a
        ld i,a
        {FF}
        ld a,i
        push af
        ld a,(savi)
        ld i,a
        pop af''', 0x69, 0x41),
    ('LD A,R  ', f'''xor a
        ld r,a                  ; R is 02h-07h by the read: bits 3, 5, 7 clear, not zero
        {FF}
        ld a,r''', 0x29, 0x01),
    ('IN A,(C)', f'''ld a,0x7F
        ld e,0x00
        call nr_write           ; the port's byte: 00h
        ld bc,0x253B
        {FF}
        in a,(c)''', 0x6D, 0x45),
]

RESTORE = '''        ld a,(0x5C48)           ; the border back from BORDCR
        rrca
        rrca
        rrca
        and 7
        out (0xFE),a
'''


def main():
    build('Z80NFLG2', CELLS, 65, 'FF', RESTORE)


if __name__ == '__main__':
    main()
