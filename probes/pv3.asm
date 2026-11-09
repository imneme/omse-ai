; P-V3 THE BLEND CARD. One photograph of twelve 16-row bands. In each, the copper sets the layer order
; (NR 0x15), the blend source and "ULA off" (NR 0x68), and NR 0x6B bit 0 (which, with the tilemap off,
; decides whether the ULA sits over or under the sprites in blends 01 and 11) over the same three layers:
; Layer 2 colour columns in the left half, ULA paper columns (two colours and a transparent one), and three
; sprites. Bands the VHDL says should match: 1, 3 and 5; 2 and 10; 6 and 8; 7 and 9 (VIDEO-NOTES, P-V3).
; Row 22 prints read-backs: NR 0x28 after NR 0x44's first byte A5, NR 0x34 after NR 0x34 = 100 and one
; NR 0x75 step, and the sprite status with sprites switched off (two overlapping) and then on the card.
; The scene is defined once in pv3_scene.py (data: pv3_data.inc); the VHDL's picture is build/pv3-vhdl.png.
; Writes palettes, the sprite RAMs, the Layer 2 screen NR 0x12 names, the ULA attributes and the copper;
; the key's soft reset puts the machine back. Hatch Fern, Fri 06 Nov 2026.
TAPEID  equ 93                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B
SPRSEL  equ 0x303B
seg     equ VARS+8
r28     equ VARS+9
r34     equ VARS+10
foff    equ VARS+11
fon     equ VARS+12
s83     equ VARS+13

main:   call screen_init
        ld a,0x83               ; enable the sprite and Layer 2 ports (NR 0x83 b6, b7; zxnext:2382-2383):
        call nrrd               ; NextZXOS has them on, the firmware's own state hasn't. Saved, and put
        ld (s83),a              ; back once the ports are done with (the display doesn't need them)
        or 0xC0
        ld e,a
        ld a,0x83
        call nrwr
        ld a,0x4B               ; sprite transparency E3; sprites stay off (screen_init's NR 0x15 = 0)
        ld e,0xE3
        call nrwr
        call patterns
        ld hl,t_flag            ; two overlapping sprites, invisible because sprites are off
        call sprrecs
        call status2            ; the flags a frame of them leaves
        ld (foff),a
        ld hl,t_regs            ; the card: palettes, transparency, fallback, Layer 2, clips, band 0
        call nrlist
        ld a,0x43               ; the sprite first palette: entry i = colour i
        ld e,0x20
        call nrwr
        ld a,0x40
        ld e,0x00
        call nrwr
        ld b,0
        ld e,0
m1:     ld a,0x41
        call nrwr
        inc e
        djnz m1
        ld a,0x43
        ld e,0x00
        call nrwr
        ld hl,t_sprites
        call sprrecs
        call fill_l2
        ld hl,t_attr            ; the ULA's attribute columns
        ld de,0x5800
        ld bc,768
        ldir
        xor a                   ; border 0
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld hl,t_copper          ; the copper: eleven band changes, band 0 again at row 200 (mode 11)
        ld a,0x62
        ld e,0x00
        call nrwr
        ld a,0x61
        ld e,0x00
        call nrwr
m2:     ld a,(hl)
        inc hl
        ld e,a
        ld a,0x63
        call nrwr
        ld a,(hl)
        inc hl
        ld e,a
        ld a,0x63
        call nrwr
        ld a,e
        cp 0xFF
        jr nz,m2
        ld a,0x62
        ld e,0xC0
        call nrwr
        ld a,0x43               ; read-backs: NR 0x28 after NR 0x44's first byte
        ld e,0x00
        call nrwr
        ld a,0x40
        ld e,0xF0
        call nrwr
        ld a,0x44
        ld e,0xA5
        call nrwr
        ld a,0x28
        call nrrd
        ld (r28),a
        ld a,0x34               ; NR 0x34 after selecting sprite 100 and one NR 0x75 step
        ld e,100
        call nrwr
        ld a,0x75
        ld e,0x00
        call nrwr
        ld a,0x34
        call nrrd
        ld (r34),a
        call status2            ; the card's own flags
        ld (fon),a
        ld a,(s83)              ; NR 0x83 as it was
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,s_28
        call pstr
        ld a,(r28)
        call phex8
        ld hl,s_34
        call pstr
        ld a,(r34)
        call phex8
        ld hl,s_off
        call pstr
        ld a,(foff)
        call phex8
        ld hl,s_on
        call pstr
        ld a,(fon)
        call phex8
        jp finish

patterns:                       ; patterns from 0, through port 0x5B
        ld bc,SPRSEL
        xor a
        out (c),a
        ld hl,t_pats
        ld de,NPATBYTES
pa1:    ld a,(hl)
        out (0x5B),a
        inc hl
        dec de
        ld a,d
        or e
        jr nz,pa1
        ret

sprrecs:                        ; records: index, count, attribute bytes; FF ends
        ld a,(hl)
        cp 0xFF
        ret z
        inc hl
        ld bc,SPRSEL
        out (c),a
        ld b,(hl)
        inc hl
sr2:    ld a,(hl)
        out (0x57),a
        inc hl
        djnz sr2
        jr sprrecs

status2:                        ; clear the sprite status, wait two frames, read it into A
        ld bc,SPRSEL
        in a,(c)
        call frame
        call frame
        ld bc,SPRSEL
        in a,(c)
        ret

frame:  ld de,0                 ; until the active line's low byte is 240 (giving up after 65536 reads: not a
f1:     ld a,0x1F               ; Next, whose registers read FF), then until it isn't
        call nrrd
        cp 240
        jr z,f2
        dec de
        ld a,d
        or e
        jr nz,f1
        ret
f2:     ld a,0x1F
        call nrrd
        cp 240
        jr z,f2
        ret

nrlist: ld a,(hl)               ; (register, value) pairs, FF ends
        cp 0xFF
        ret z
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr nrlist

; ---- Layer 2: index 0x10 + x / 32 in the left half, transparent E3 on the right (as pv3_scene.layer2)
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
fl2:    ld a,l                  ; x = L
        cp 128
        ld a,0xE3
        jr nc,fl3
        ld a,l
        rlca
        rlca
        rlca
        and 3
        or 0x10
fl3:    ld (hl),a
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

t_flag: db 0,4,100,100,0x00,0x80
        db 1,4,108,104,0x00,0x80
        db 0xFF
s_28:   db 22,22,4,"28:",0
s_34:   db " 34:",0
s_off:  db " off:",0
s_on:   db " on:",0

        include "pv3_data.inc"
