; P-V4 THE LAYER 2 CARD. One photograph of twelve 16-row bands, each labelled on the right. In each, the
; copper sets Layer 2's resolution and palette offset (NR 0x70), bank (NR 0x12), scroll (NR 0x17, NR 0x16)
; and whether it shows (NR 0x69 b7), over one image in banks 8-10: byte (y, x) = (y + x / 4) & FF. It asks:
; does resolution 11 draw as 10 (640x256x4)? Is a bank range past SRAM's end transparent? Does a Y scroll
; with row + scroll >= 384 read rows 192 and up (bank + 3) rather than wrapping twice? (VIDEO-NOTES, P-V4.)
; Touches no memory but banks 8-10. The scene is defined once in pv4_scene.py (data: pv4_data.inc); the
; VHDL's picture is build/pv4-vhdl.png. Writes palettes, Layer 2 banks 8-10, the ULA screen and the copper;
; NR 0x83 is put back, and the key's soft reset puts the rest back. Hatch Fern, Fri 06 Nov 2026.
TAPEID  equ 94                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B
seg     equ VARS+8
s83     equ VARS+9

main:   call screen_init
        ld a,0x83               ; enable the Layer 2 port (NR 0x83 b7; zxnext:2383), saved and put back
        call nrrd
        ld (s83),a
        or 0x80
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,t_regs            ; palettes, transparency, fallback, Layer 2's clip, band 0 (bank 8)
        call nrlist
        call fill_l2
        ld a,(s83)              ; NR 0x83 as it was: the ports are done with
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,0x5800            ; every cell ink 7 on paper 1
        ld de,0x5801
        ld bc,767
        ld (hl),UATTR
        ldir
        ld hl,s_labels
        call pstr
        ld a,1                  ; border 1
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld hl,t_copper          ; the copper: eleven band changes, band 0 again at row 200 (mode 11)
        ld a,0x62
        ld e,0x00
        call nrwr
        ld a,0x61
        ld e,0x00
        call nrwr
m1:     ld d,(hl)               ; a word, MSB first; FFFF ends (a MOVE's value can be FF)
        inc hl
        ld e,(hl)
        inc hl
        ld a,d
        and e
        inc a
        jr z,m2
        ld a,0x63
        push de
        ld e,d
        call nrwr
        pop de
        ld a,0x63
        call nrwr
        jr m1
m2:     ld a,0x62
        ld e,0xC0
        call nrwr
        jp finish

nrlist: ld a,(hl)               ; (register, value) pairs, FF ends
        cp 0xFF
        ret z
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr nrlist

; ---- Layer 2, banks 8-10 through the write mapping: byte (y, x) = (y + x / 4) & FF (as pv4_scene.layer2)
fill_l2:
        xor a
        ld (seg),a
fl1:    ld a,(seg)
        rrca
        rrca
        or 0x01
        ld bc,L2PORT
        out (c),a
        ld hl,0x0000
fl2:    ld a,(seg)              ; y = 64 * seg + H
        rrca
        rrca
        add a,h
        ld e,a
        ld a,l                  ; + x / 4
        rrca
        rrca
        and 0x3F
        add a,e
        ld (hl),a
        inc hl
        ld a,h
        cp 0x40
        jr nz,fl2
        ld a,(seg)
        inc a
        ld (seg),a
        cp 3
        jr nz,fl1
        ld a,0x02
        ld bc,L2PORT
        out (c),a
        ret

        include "pv4_data.inc"
