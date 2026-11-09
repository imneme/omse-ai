; P-82: which SRAM does Layer 2's *display* read for a given NR 0x12? P-81 showed the port 0x123B map writing and
; reading back in NR 0x12's bank (bank 9 confirmed through MMU7; bank 5 read back C3), all as the VHDL says, yet
; P-8's display of bank 5 showed SRAM noise. So this probe paints a band of a different colour into rows 0-7 of
; banks 5, 8, 9 and 10, all through the map (the path P-81 proved), then shows Layer 2 with NR 0x12 = 5, 9 and 8
; in turn. The band's colour names the bank the display really reads:
;   red = bank 5, green = bank 8, blue = bank 9, yellow = bank 10, noise = none of them.
; VHDL (layer2.vhd:169-188, zxnext.vhd:3059-3066): red, then blue, then green. Layer order SLU, palette entries
; set explicitly, transparency E3, clip rows 0-7. Ends with the photo-then-key pause; puts NR 0x12 back.
; Tally Fern, Fri 06 Nov 2026, after the P-8 and P-81 photos (Hart's-tongue's P-8, while she rests).
; Fixed the same day (Tally): the first build filled the bands with LDIR from 0x0000, whose reads come from the ROM
; while the 0x123B map maps writes only, so it painted the ROM's bytes. P-8 did the same, which explains its noise:
; omse-ai's Next showed exactly that, faithfully. With a write loop the VHDL's answer should show: red, blue, green.
TAPEID  equ 82                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B

main:   ld a,0x12
        call nrrd
        ld (v12),a
        call screen_init
        xor a                   ; rows 0-7 are the test area: plain attributes, no title there
        ld (prow),a
        ld a,ATTR
        call hilite
        ld a,16
        ld (prow),a
        ld a,0x0F
        call hilite
        ld hl,s_text
        call pstr
        ld hl,l2regs
l1:     ld a,(hl)
        cp 0xFF
        jr z,l2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr l1
l2:     ld a,5                  ; paint the bands through the map
        ld e,0xE0
        call band
        ld a,8
        ld e,0x1C
        call band
        ld a,9
        ld e,0x03
        call band
        ld a,10
        ld e,0xFC
        call band
        ld a,0x12               ; show NR 0x12 = 5
        ld e,5
        call nrwr
        ld bc,L2PORT
        ld a,0x02               ; Layer 2 on, no mapping
        out (c),a
        ld hl,s_p1
        call pstr
        call photokey           ; the photo beep, then a key
        ld a,0x12
        ld e,9
        call nrwr
        ld hl,s_p2
        call pstr
        call photokey           ; the photo beep, then a key
        ld a,0x12
        ld e,8
        call nrwr
        ld hl,s_p3
        call pstr
        call photokey           ; the photo beep, then a key
        ld bc,L2PORT            ; Layer 2 off, NR 0x12 back
        xor a
        out (c),a
        ld a,(v12)
        ld e,a
        ld a,0x12
        call nrwr
        jp finish

; A = 16K bank, E = colour: NR 0x12 := A, map bank offset 0, write-map segment 0, rows 0-7 (2K) := E, map off
band:   push de
        ld e,a
        ld a,0x12
        call nrwr
        ld bc,L2PORT
        ld a,0x10
        out (c),a
        ld a,0x01
        out (c),a
        pop de
        ld hl,0x0000            ; a write loop, not LDIR: the map is for writes only, so LDIR's reads of
        ld bc,0x0800            ; 0x0000 come from the ROM and copy the ROM into Layer 2 (P-8's "noise")
bfill:  ld (hl),e
        inc hl
        dec bc
        ld a,b
        or c
        jr nz,bfill
        ld bc,L2PORT
        xor a
        out (c),a
        ret

v12:    db 0

l2regs: db 0x15,0x00            ; layer order S L U, sprites off
        db 0x70,0x00            ; 256x192x8, palette offset 0
        db 0x16,0x00,0x17,0x00,0x71,0x00
        db 0x14,0xE3            ; global transparency E3
        db 0x1C,0x01            ; Layer 2 clip: x 0-255, y 0-7
        db 0x18,0x00,0x18,0xFF,0x18,0x00,0x18,0x07
        db 0x43,0x10            ; edit Layer 2's first palette, auto-increment, first palettes active
        db 0x40,0xE3,0x41,0xE3  ; each band's colour maps to itself
        db 0x40,0xE0,0x41,0xE0
        db 0x40,0x1C,0x41,0x1C
        db 0x40,0x03,0x41,0x03
        db 0x40,0xFC,0x41,0xFC
        db 0x43,0x00
        db 0xFF
s_text: db 22,16,0,"P-82 WHICH BANK LAYER 2 SHOWS"
        db 22,17,0,"Bands in rows 0-7, each written"
        db 22,18,0,"through the 123B map: bank 5 red"
        db 22,19,0,"bank 8 green, 9 blue, 10 yellow;"
        db 22,20,0,"noise means none of them.",0
s_p1:   db 22,22,0,"NR12=5. VHDL: red.  Photo, key.  ",0
s_p2:   db 22,22,0,"NR12=9. VHDL: blue. Photo, key.  ",0
s_p3:   db 22,22,0,"NR12=8. VHDL: green. Photo, key. ",0
