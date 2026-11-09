; PCF: NR 0x03 and config mode. NEXT-MACHINE.md §9 D-1, as a careful tape with Melissa O'Neill's go-ahead (a hang is fine;
; nothing that can harm the machine or the card). Hart's-tongue Fern, Fri 06 Nov 2026. Expectations with the VHDL
; lines in NOTES.md under "PCF". Checked against Rustyback Fern's TAPE-REVIEW-CHECKLIST.md.
;
;   D-1  nextreg.txt: NR 0x03 type "000 = Configuration mode". The VHDL: bits 2:0 = 111 enter config mode, 000 leaves
;        it as it is, 001-100 leave it (zxnext:5084-5089). In config mode, with MMU0/1 on the ROM, 0x0000-0x3FFF is
;        16K SRAM bank NR 0x04 (zxnext:3002-3008).
;
; So: put A5 5A at the start of RAM bank 32 (page 0x40, SRAM bank 0x30), point NR 0x04 at it, and read 0x0000-0x0001
; before, after NR 0x03 = 00, after NR 0x03 = 07, and after writing her machine type back. Only 07 should show A5 5A.
;
; Safety, while config mode may be on: interrupts off; code and stack above 0x4000 (0x8000, 0xBF00); no ROM calls; no
; writes below 0x4000 (the window is writable SRAM); no port with low byte E7 or EB except one OUT of FF to E7 at the
; start (deselect all); no NR 0x10. Every NR 0x03 write has bit 7 = 0 (no timing change) and bit 3 = 0 (the lock
; toggles on a 1, zxnext:5074). Config mode is left by writing her machine type (bits 2:0 = 001-100) before anything
; else happens, and before the closing soft reset. NR 0x04 is write-only, so it stays at 0x30: it matters only in
; config mode, and the firmware sets it at every boot.

TAPEID  equ 72                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

V       equ VARS+0x20
s03     equ V+0
s57     equ V+1
o0      equ V+2
o1      equ V+3
typ     equ V+4
rd      equ V+5                 ; 4 pairs: before, NR03=00, NR03=07, type back

main:   ld a,0xFF               ; every SPI device deselected (the one E7 write)
        out (0xE7),a
        ld a,0x03
        call nrrd
        ld (s03),a
        and 0x07                ; her machine type, to leave config mode with
        jr z,mt1                ; (000 or 111 can't be a type: use 011, the Next's +3 type)
        cp 7
        jr nz,mt2
mt1:    ld a,3
mt2:    ld (typ),a
        ld a,0x57
        call nrrd
        ld (s57),a
        call screen_init
        ld hl,s_warn
        call pstr
        call waitkey            ; she reads the warning; nothing has been done yet

        ld a,0x57               ; the signature, in RAM bank 32's first two bytes
        ld e,0x40
        call nrwr
        ld hl,0xE000
        ld a,(hl)
        ld (o0),a
        ld (hl),0xA5
        inc hl
        ld a,(hl)
        ld (o1),a
        ld (hl),0x5A
        ld a,(s57)
        ld e,a
        ld a,0x57
        call nrwr
        ld ix,rd
        call rd2                ; before
        ld a,0x04               ; the config window: SRAM 16K bank 0x30 = RAM bank 32
        ld e,0x30
        call nrwr
        ld a,0x03               ; nextreg.txt's "000 = configuration mode"
        ld e,0x00
        call nrwr
        call rd2
        ld a,0x03               ; the VHDL's: bits 2:0 = 111
        ld e,0x07
        call nrwr
        call rd2
        ld a,(typ)              ; leave config mode: her machine type, bits 7 and 3 clear
        ld e,a
        ld a,0x03
        call nrwr
        call rd2
        ld a,0x57               ; the two bytes back
        ld e,0x40
        call nrwr
        ld a,(o0)
        ld (0xE000),a
        ld a,(o1)
        ld (0xE001),a
        ld a,(s57)
        ld e,a
        ld a,0x57
        call nrwr

        call screen_init
        ld hl,s_res
        call pstr
        ld a,(s03)
        call phex8
        ld hl,s_rows
        call pstr
        ld ix,rd
        ld hl,s_r0
        call prpair
        ld hl,s_r1
        call prpair
        ld hl,s_r2
        call prpair
        ld hl,s_r3
        call prpair
        ld hl,s_want
        call pstr
        jp finish

rd2:    ld a,(0x0000)           ; reads only, below 0x4000
        ld (ix+0),a
        ld a,(0x0001)
        ld (ix+1),a
        inc ix
        inc ix
        ret

prpair: call pstr                ; a label, then the pair at IX
        ld a,(ix+0)
        call phex8
        call pspace
        ld a,(ix+1)
        call phex8
        inc ix
        inc ix
        ret

s_warn: db 22,0,0,"PCF  NR 03 and config mode",13,13
        db "On a key this tape will write",13
        db "NR 03 = 00, then 07, reading",13
        db "address 0000 after each, then",13
        db "put your machine type back.",13,13
        db "The VHDL says 07 (bits 111)",13
        db "enters config mode; 00 doesn't.",13
        db "It only reads below 4000, and",13
        db "writes no files.",13,13
        db "If it freezes: the soft-reset",13
        db "key does nothing in config",13
        db "mode. Hold reset for a hard",13
        db "reset, or press F1, or power",13
        db "the Next off and on.",13,13
        db "Key: go on",0
s_res:  db 22,0,0,"PCF  NR 03 and config mode",13
        db "NR 03 was ",0
s_rows: db 13,"bytes at 0000 0001:",0
s_r0:   db 22,3,0," before          ",0
s_r1:   db 22,4,0," NR 03 = 00      ",0
s_r2:   db 22,5,0," NR 03 = 07      ",0
s_r3:   db 22,6,0," type back       ",0
s_want: db 22,8,0,"VHDL: 00 as before; 07 shows",13
        db "A5 5A (RAM bank 32, through",13
        db "NR 04 = 30); type back as",13
        db "before.",13,13
        db "nextreg.txt: A5 5A at 00 too.",0
