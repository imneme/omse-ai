; P-V2 THE SPRITE CARD. One photograph: anchors and relative sprites (composite at left; unified, rotated and
; x-mirrored, at right: the group turns together), sprite scales 1/2/4/8 in X and 2 in Y on a grid pattern,
; all eight mirror/rotate orientations of an F, sprites against Layer 2 and the ULA in four copper bands of
; NR 0x15 (SLU LSU SUL USL), an overlapping pair, a sprite cut by the clip window over the left border, and
; the per-line limit: 32 sprites at 8x on one line, 8 px apart, each a palette step, so the hardware's
; colours stop changing where its time runs out. The sprite status (port 0x303B: bit 1 = a line ran out of
; time, bit 0 = collision) is read after a full frame and printed.
; The scene is defined once in pv2_scene.py (data: pv2_data.inc); the VHDL's picture is build/pv2-vhdl.png.
; Writes the sprite RAMs, the Layer 2 screen NR 12 names, the ULA screen, palette entries and the copper;
; the key's soft reset puts the machine back. Hatch Fern, Fri 06 Nov 2026.
TAPEID  equ 92                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B
SPRSEL  equ 0x303B
seg     equ VARS+8
status  equ VARS+9
s83     equ VARS+10

main:   call screen_init
        ld a,0x83               ; enable the sprite and Layer 2 ports (NR 0x83 b6, b7; zxnext:2382-2383):
        call nrrd               ; NextZXOS has them on, the firmware's own state hasn't. Saved, and put
        ld (s83),a              ; back once the ports are done with (the display doesn't need them)
        or 0xC0
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,regs              ; ULA and Layer 2 palette entries, transparency, fallback, Layer 2's mode
        call nrlist
        ld a,0x43               ; the sprite first palette: 256 entries through NR 0x41
        ld e,0x20
        call nrwr
        ld a,0x40
        ld e,0x00
        call nrwr
        ld hl,t_pal
        ld b,0
m1:     ld e,(hl)
        inc hl
        ld a,0x41
        call nrwr
        djnz m1
        ld a,0x43
        ld e,0x00
        call nrwr
        ld bc,SPRSEL            ; patterns from 0, through port 0x5B
        xor a
        out (c),a
        ld hl,t_pats
        ld de,NPATBYTES
m2:     ld a,(hl)
        out (0x5B),a
        inc hl
        dec de
        ld a,d
        or e
        jr nz,m2
        ld hl,t_sprites         ; records: index, count, attribute bytes; FF ends
m3:     ld a,(hl)
        cp 0xFF
        jr z,m5
        inc hl
        ld bc,SPRSEL
        out (c),a
        ld b,(hl)
        inc hl
m4:     ld a,(hl)
        out (0x57),a
        inc hl
        djnz m4
        jr m3
m5:     call fill_l2
        call draw_ula
        ld a,1                  ; border 1: navy
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld hl,t_copper          ; the copper: four bands of NR 0x15, then SLU (mode 11, as P-V1)
        ld a,0x62
        ld e,0x00
        call nrwr
        ld a,0x61
        ld e,0x00
        call nrwr
m6:     ld a,(hl)
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
        jr nz,m6
        ld a,0x62
        ld e,0xC0
        call nrwr
        ld a,0x15               ; sprites on, over the border, border clip, SLU
        ld e,NR15V
        call nrwr
        ld bc,SPRSEL            ; clear the status, wait a whole frame (by the line counter, so any CPU speed
        in a,(c)                ; works), then read it
        call frame
        call frame
        ld bc,SPRSEL
        in a,(c)
        ld (status),a
        ld a,(s83)              ; NR 0x83 as it was
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,s_status
        call pstr
        ld a,(status)
        call phex8
        jp finish

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

; ---- Layer 2: a red stripe column at x 120-135 in rows 96-143, transparent elsewhere (as pv2_model.layer2)
fill_l2:
        ld d,0
        xor a
        ld (seg),a
fl1:    ld a,(seg)
        rrca
        rrca
        or 0x01
        ld bc,L2PORT
        out (c),a
        ld hl,0x0000
fl2:    ld b,0                  ; one row: D = Y, HL = its first byte
fl3:    ld a,0xE3
        ld e,a
        ld a,d
        cp 96
        jr c,fl4
        cp 144
        jr nc,fl4
        ld a,l
        cp 120
        jr c,fl4
        cp 136
        jr nc,fl4
        add a,d                 ; (x + y) mod 4 < 2 -> red
        and 3
        cp 2
        jr nc,fl4
        ld e,0xE0
fl4:    ld (hl),e
        inc l
        djnz fl3
        inc h
        inc d
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

; ---- the ULA: white on black; a cyan / transparent checker in char rows 12-17, left half; the prompt row
draw_ula:
        ld hl,0x4000
        ld de,0x4001
        ld bc,6143
        ld (hl),0
        ldir
        ld de,0x5800
        ld c,0
da1:    ld b,0
da2:    ld a,c
        cp 12
        jr c,da4
        cp 18
        jr nc,da4
        ld a,b
        cp 16
        jr nc,da4
        add a,c
        and 1
        ld a,0x38
        jr z,da5
        ld a,0x28
        jr da5
da4:    ld a,0x07
da5:    ld (de),a
        inc de
        inc b
        ld a,b
        cp 32
        jr nz,da2
        inc c
        ld a,c
        cp 24
        jr nz,da1
        ld hl,0x5800+23*32
        ld b,32
da6:    ld (hl),0x30
        inc hl
        djnz da6
        ret

regs:   db 0x43,0x00
        db 0x40,0x07,0x41,0xFF  ; ink 7 white
        db 0x40,0x10,0x41,0x00  ; paper 0 black
        db 0x40,0x11,0x41,0x02  ; paper 1 navy (the border)
        db 0x40,0x15,0x41,0x1F  ; paper 5 cyan
        db 0x40,0x17,0x41,0xE3  ; paper 7 = transparent
        db 0x43,0x10            ; Layer 2 first palette: E0 red, E3 transparent
        db 0x40,0xE0,0x41,0xE0,0x40,0xE3,0x41,0xE3
        db 0x43,0x00
        db 0x14,0xE3,0x4A,0x49,0x4B,0xE3
        db 0x70,0x00,0x16,0x00,0x17,0x00,0x71,0x00
        db 0x1C,0x03,0x18,0x00,0x18,0xFF,0x18,0x00,0x18,0xBF
        db 0x19,CLIPX1,0x19,CLIPX2,0x19,CLIPY1,0x19,CLIPY2
        db 0xFF

s_status:
        db 22,19,12,"status ",0

        include "pv2_data.inc"
