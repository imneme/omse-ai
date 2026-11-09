; P-13 PORT 0x1F ANSWERS ONLY FOR A KEMPSTON STICK. ports.txt lists 0x1F as Kempston joystick 1 without
; condition; the VHDL answers it only while a joystick is set to Kempston 1 or MD 1 in NR 05 (zxnext.vhd:2408-2414,
; 2633), and 0x37 only for Kempston 2 / MD 2 (2634). Otherwise nobody answers and the read is FF (1827-1841).
; Reads 1F, 37 and DF with NR 05 as it was, with both sticks Sinclair 2, and with Kempston 1 and Kempston 2, then
; puts NR 05 back (keeping its 50/60 Hz and scandoubler bits throughout, so the display doesn't change).
; Leave the joysticks alone while it runs. Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 13                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

res13   equ BUF                 ; 3 settings x 3 ports
nr05    equ BUF+0x10

main:   ld a,0x05
        call nrrd
        ld (nr05),a
        ld ix,res13
        call rd3                ; as it was
        ld a,(nr05)
        and 0x05                ; both sticks Sinclair 2 (000)
        ld e,a
        ld a,0x05
        call nrwr
        call rd3
        ld a,(nr05)
        and 0x05
        or 0x42                 ; joystick 1 Kempston 1 (001), joystick 2 Kempston 2 (100)
        ld e,a
        ld a,0x05
        call nrwr
        call rd3
        ld a,(nr05)
        ld e,a
        ld a,0x05
        call nrwr
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_head
        call pstr
        ld ix,res13
        ld hl,s_rows
        ld b,3
p1:     push bc
        call pstr               ; the row's label (HL moves on)
        push hl
        ld b,3
p2:     ld a,(ix+0)
        call phex8
        call pspace
        call pspace
        call pspace
        inc ix
        djnz p2
        pop hl
        pop bc
        djnz p1
        ld hl,s_nr05
        call pstr
        ld a,(nr05)
        call phex8
        ld hl,s_expect
        call pstr
        jp finish

; read ports 1F, 37, DF into IX+0..2 (A15:8 = 0), IX moves on
rd3:    ld b,0                  ; a moment for the new setting (the decode samples it in memory cycles)
r0:     djnz r0
        ld bc,0x001F
        in a,(c)
        ld (ix+0),a
        ld bc,0x0037
        in a,(c)
        ld (ix+1),a
        ld bc,0x00DF
        in a,(c)
        ld (ix+2),a
        inc ix
        inc ix
        inc ix
        ret

s_title: db "P-13 PORT 1F AND THE STICKS",0
s_head: db 22,2,0,"NR 05 sticks:   1F   37   DF",0
s_rows: db 22,3,0,"as they were    ",0
        db 22,4,0,"Sinclair 2 x2   ",0
        db 22,5,0,"Kempston 1, 2   ",0
s_nr05: db 22,7,0,"NR 05 was ",0
s_expect:
        db 22,9,0,"VHDL: Sinclair row FF FF; the"
        db 22,10,0,"Kempston row 00 00 (sticks"
        db 22,11,0,"idle). DF: FF while the mouse"
        db 22,12,0,"port is on.",0
