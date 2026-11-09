; P-V5 THE BUDGET RULER. One photograph of three strips of overlapping sprites, each a palette step, so the
; colours stop changing where the sprite renderer's line runs out (VIDEO-NOTES, P-V5):
;   top:    sprites 10-41 at 4x, 8 px apart;   middle: sprites 42-95 at 2x, 4 px apart;
;   bottom: sprites 96-127 at 8x, 8 px apart (exactly P-V2's strip).
; All 128 sprite slots are written (the others invisible), so no leftover sprite can take any line's time.
; The sprite status (port 0x303B: bit 1 overtime, bit 0 collision) is read after two frames and printed.
; The scene is defined once in pv5_scene.py (data: pv5_data.inc); the VHDL's picture is build/pv5-vhdl.png.
; Writes the sprite RAMs, a few palette entries and the ULA attributes; NR 0x83 is put back, and the key's
; soft reset puts back the rest. Hatch Fern, Fri 06 Nov 2026.
        include "probe.inc"

TAPEID  equ 95                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
SPRSEL  equ 0x303B
status  equ VARS+8
s83     equ VARS+9

main:   call screen_init
        ld a,0x83               ; enable the sprite ports (NR 0x83 b6; zxnext:2382), saved and put back
        call nrrd
        ld (s83),a
        or 0x40
        ld e,a
        ld a,0x83
        call nrwr
        ld hl,t_regs            ; ULA ink and papers, transparency, fallback, the sprite clip
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
        ld bc,SPRSEL            ; the pattern, from pattern 0
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
        ld bc,SPRSEL            ; all 128 sprites' five bytes, from slot 0
        xor a
        out (c),a
        ld hl,t_attrs
        ld de,640
m3:     ld a,(hl)
        out (0x57),a
        inc hl
        dec de
        ld a,d
        or e
        jr nz,m3
        ld hl,0x5800            ; ink 7 on paper 0 everywhere
        ld de,0x5801
        ld bc,767
        ld (hl),0x07
        ldir
        ld a,1                  ; border 1
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld a,0x15               ; sprites on, over the border, border clip
        ld e,NR15V
        call nrwr
        ld bc,SPRSEL            ; clear the status, wait two frames, read it
        in a,(c)
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

s_status:
        db 22,STROW,12,"status ",0

        include "pv5_data.inc"
