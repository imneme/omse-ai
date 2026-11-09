; P-2B (variant, after the sitting 2: 55 didn't survive, read 00). Separates the reset from NextZXOS:
; R writes 55 and returns to BASIC with no reset (load P2B again: 55 still there means NextZXOS's load path
; leaves NR 7F alone); W writes 55 and soft-resets; H writes 55 and hard-resets (FPGA reload: FF expected).
; Original P-2 notes:
; P-2 NR 0x7F ACROSS A SOFT RESET. 3.02.02's nextreg.txt says a soft reset sets it to FF; the VHDL keeps it
; (no reset branch, zxnext.vhd:1210), as the changelog (3.01.09) and 3.02.05's nextreg.txt say.
; Run 1: shows NR 7F (FF after power-on), press W: writes 55 and soft-resets. Load again (run 2): shows 55 if
; it survived, as the VHDL says. NR 02's low bits say what the last reset was (01 soft, 02 hard).
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 29                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
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
        ld c,a
        ld a,0x7F               ; any of R, W, H: write 55 first
        ld e,0x55
        bit 3,c                 ; R: no reset, back to BASIC
        jr nz,m_w
        call nrwr
        jp back
m_w:    bit 1,c                 ; W: soft reset
        jr nz,m_h
        call nrwr
        jr m_soft
m_h:    ld a,0xBF               ; H (ENTER L K J H row, bit 4): hard reset
        in a,(0xFE)
        bit 4,a
        jr nz,m_soft
        ld a,0x7F
        ld e,0x55
        call nrwr
        ld a,0x02
        ld e,0x02
        call nrwr
m_soft: call softreset
        jp back

v7f:    db 0
v02:    db 0
s_title: db "P-2B NR 7F: RESET OR NEXTZXOS?",0
s_7f:   db 22,2,0,"NR 7F now: ",0
s_02:   db 22,3,0,"NR 02 now: ",0
s_help: db 22,5,0,"(NR 02 bits 1:0: 01 = the last"
        db 22,6,1,"reset was soft, 02 = hard)"
        db 22,8,0,"R: write 55, back to BASIC, NO"
        db 22,9,3,"reset. Load P2B again."
        db 22,11,0,"W: write 55 and soft-reset."
        db 22,12,0,"H: write 55 and hard-reset."
        db 22,14,0,"Other: soft reset only."
        db 22,16,0,"P2B: R first, then W, then H."
        db 22,23,0,"Photo, please, then a key.",0
