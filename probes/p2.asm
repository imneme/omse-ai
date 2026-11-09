; P-2 NR 0x7F ACROSS A SOFT RESET. 3.02.02's nextreg.txt says a soft reset sets it to FF; the VHDL keeps it
; (no reset branch, zxnext.vhd:1210), as the changelog (3.01.09) and 3.02.05's nextreg.txt say.
; Run 1: shows NR 7F (FF after power-on), press W: writes 55 and soft-resets. Load again (run 2): shows 55 if
; it survived, as the VHDL says. NR 02's low bits say what the last reset was (01 soft, 02 hard).
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 2                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

main:   ld a,0x7F
        call nrrd
        ld (v7f),a
        ld a,0x02
        call nrrd
        ld (v02),a
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_7f
        call pstr
        ld a,(v7f)
        call phex8
        ld hl,s_02
        call pstr
        ld a,(v02)
        call phex8
        ld hl,s_help
        call pstr
        call photokey           ; the photo beep, then a key
        ld a,0xFB               ; Q W E R T row
        in a,(0xFE)
        bit 1,a                 ; W
        jr nz,m_other
        ld a,0x7F
        ld e,0x55
        call nrwr
m_other:
        call softreset
        jp back

v7f:    db 0
v02:    db 0
s_title: db "P-2 NR 7F ACROSS A SOFT RESET",0
s_7f:   db 22,2,0,"NR 7F now: ",0
s_02:   db 22,3,0,"NR 02 now: ",0
s_help: db 22,5,0,"(NR 02 bits 1:0: 01 = the last"
        db 22,6,1,"reset was soft, 02 = hard)"
        db 22,9,0,"W: write 55 to NR 7F and"
        db 22,10,3,"soft-reset. Then load this"
        db 22,11,3,"tape again and photograph"
        db 22,12,3,"what it shows."
        db 22,14,0,"Any other key: soft reset only."
        db 22,23,0,"Photo, please, then a key.",0
