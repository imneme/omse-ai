; P-81, a diagnostic for P-8: why didn't Layer 2's port 0x123B mapping land where the display reads?
; the test machine showed SRAM noise and no red band, even with the bank offset cleared first.
; Reads, before touching anything: NR 0x12 (Layer 2 bank), NR 0x13 (shadow bank), MMU0/1, MMU7, port 0x123B,
; port 0xE3 (divMMC control) and the byte at 0000. Then:
;   A. Layer 2's own bank as NextZXOS left it (NR 0x12): offset 0 (0x10), map for reads and writes (0x05),
;      read the 123B readback, read two bytes through the map, write A5 5A, read them back through the map;
;      a write-only map (0x01) and an ordinary read of 0000 (should be the ROM's byte); then map off and read the
;      same two bytes through MMU7 at page 2 x NR12 (the SRAM the display reads); put them back.
;   B. NR 0x12 := 5 (read back), the ULA's bank 5 byte at 4000 before and after, offset 0, map 0x05, write C3 at
;      0000 and read it back through the map; put it back; NR 0x12 restored.
; VHDL (zxnext.vhd 3059-3066; ports.txt 0x123B): A reads back A5 5A both ways; the write-only read gives the ROM
; byte; B reads back 05 and C3, and the ULA's 4000 byte is the same twice.
; Tally Fern, Fri 06 Nov 2026, for the sitting (Hart's-tongue's P-8, while she rests).
TAPEID  equ 81                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B

main:   ld a,0x12
        call nrrd
        ld (v12),a
        ld a,0x13
        call nrrd
        ld (v13),a
        ld a,0x50
        call nrrd
        ld (v50),a
        ld a,0x51
        call nrrd
        ld (v51),a
        ld a,0x57
        call nrrd
        ld (v57),a
        ld bc,L2PORT
        in a,(c)
        ld (p0),a
        ld bc,0x00E3
        in a,(c)
        ld (pe3),a
        ld a,(0x0000)
        ld (rom0),a
; A: Layer 2's own bank
        ld bc,L2PORT
        ld a,0x10               ; bank offset 0
        out (c),a
        in a,(c)
        ld (p1),a
        ld a,0x05               ; map Layer 2's first 16K into 0000-3FFF for reads and writes
        out (c),a
        in a,(c)
        ld (p2),a
        ld a,(0x0000)
        ld (aold0),a
        ld a,(0x0001)
        ld (aold1),a
        ld a,0xA5
        ld (0x0000),a
        ld a,0x5A
        ld (0x0001),a
        ld a,(0x0000)
        ld (ard0),a
        ld a,(0x0001)
        ld (ard1),a
        ld a,0x01               ; write-only map: an ordinary read of 0000 should see the ROM
        out (c),a
        ld a,(0x0000)
        ld (awo),a
        xor a                   ; map off
        out (c),a
        ld a,(v12)              ; MMU7 at page 2 x NR12: the SRAM Layer 2 displays
        add a,a
        ld e,a
        ld a,0x57
        call nrwr
        ld a,(0xE000)
        ld (amm0),a
        ld a,(0xE001)
        ld (amm1),a
        ld a,(aold0)            ; put the two bytes back
        ld (0xE000),a
        ld a,(aold1)
        ld (0xE001),a
        ld a,(v57)
        ld e,a
        ld a,0x57
        call nrwr
; B: bank 5
        ld a,0x12
        ld e,0x05
        call nrwr
        ld a,0x12
        call nrrd
        ld (v12b),a
        ld a,(0x4000)
        ld (b5a),a
        ld bc,L2PORT
        ld a,0x10
        out (c),a
        ld a,0x05
        out (c),a
        ld a,(0x0000)
        ld (bold),a
        ld a,0xC3
        ld (0x0000),a
        ld a,(0x0000)
        ld (brd),a
        ld a,(bold)
        ld (0x0000),a
        xor a
        out (c),a
        ld a,(0x4000)
        ld (b5b),a
        ld a,(v12)
        ld e,a
        ld a,0x12
        call nrwr
; show
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_r1
        call pstr
        ld a,(v12)
        call phex8
        ld hl,s_r1b
        call pstr
        ld a,(v13)
        call phex8
        ld hl,s_r1c
        call pstr
        ld a,(v50)
        call phex8
        call pspace
        ld a,(v51)
        call phex8
        ld hl,s_r2
        call pstr
        ld a,(p0)
        call phex8
        ld hl,s_r2b
        call pstr
        ld a,(p1)
        call phex8
        ld hl,s_r2c
        call pstr
        ld a,(p2)
        call phex8
        ld hl,s_r3
        call pstr
        ld a,(pe3)
        call phex8
        ld hl,s_r3b
        call pstr
        ld a,(rom0)
        call phex8
        ld hl,s_a1
        call pstr
        ld a,(ard0)
        call phex8
        call pspace
        ld a,(ard1)
        call phex8
        ld hl,s_a2
        call pstr
        ld a,(awo)
        call phex8
        ld hl,s_a3
        call pstr
        ld a,(amm0)
        call phex8
        call pspace
        ld a,(amm1)
        call phex8
        ld hl,s_b1
        call pstr
        ld a,(v12b)
        call phex8
        ld hl,s_b2
        call pstr
        ld a,(brd)
        call phex8
        ld hl,s_b3
        call pstr
        ld a,(b5a)
        call phex8
        call pspace
        ld a,(b5b)
        call phex8
        ld hl,s_vhdl
        call pstr
        jp finish

v12:    db 0
v13:    db 0
v50:    db 0
v51:    db 0
v57:    db 0
v12b:   db 0
p0:     db 0
p1:     db 0
p2:     db 0
pe3:    db 0
rom0:   db 0
aold0:  db 0
aold1:  db 0
ard0:   db 0
ard1:   db 0
awo:    db 0
amm0:   db 0
amm1:   db 0
b5a:    db 0
b5b:    db 0
bold:   db 0
brd:    db 0

s_title: db "P-81 P8 DIAGNOSTIC: 123B MAP",0
s_r1:   db 22,2,0,"NR12 ",0
s_r1b:  db "  NR13 ",0
s_r1c:  db "  MMU0/1 ",0
s_r2:   db 22,3,0,"123B read: ",0
s_r2b:  db " /10:",0
s_r2c:  db " /05:",0
s_r3:   db 22,4,0,"port E3 ",0
s_r3b:  db "  0000 reads ",0
s_a1:   db 22,6,0,"A. NR12's bank, map 05:",13,"wrote A5 5A, map read ",0
s_a2:   db 22,8,0,"write-only map, 0000 reads ",0
s_a3:   db 22,9,0,"MMU7 at page 2xNR12: ",0
s_b1:   db 22,11,0,"B. NR12:=05 reads back ",0
s_b2:   db 22,12,0,"wrote C3 via map, read ",0
s_b3:   db 22,13,0,"ULA's 4000 before/after ",0
s_vhdl: db 22,15,0,"VHDL: A5 5A; the ROM byte;",13
        db "A5 5A; 05; C3; the same byte",13
        db "twice.",0
