; P-V1 THE LAYER CARD. One photograph shows every layer order of NR 0x15 (bits 4:2), one per 16-line band,
; set by the copper in the horizontal blanking before each band (WAIT h=44 is hc_ula 364, between the last
; visible sample of one row and the first of the next on 448- and 456-pixel lines; copper.vhd:91-110), and a
; vernier that shows whether Layer 2's pixels line up with the ULA's.
;
; In each band the ULA's left half is a checker of opaque cyan cells and cells whose paper is the transparent
; colour E3; Layer 2's left half is red diagonal stripes over E3, with a yellow block whose palette entry has
; the priority bit; the right half carries the band's label in the ULA (and, in the blend bands, opaque black
; Layer 2 behind it, without which the ULA wouldn't show there at all).
;
; VHDL says (zxnext.vhd:7007-7263): bands 0, 1, 3 (SLU LSU LUS): red stripes over everything, cyan between,
; grey fallback (NR 4A = 49) where both are transparent. Bands 2, 4, 5 (SUL USL ULS): cyan cells cover the
; stripes, which show only in the transparent cells; the yellow block is on top everywhere (priority).
; Band 6 (add, saturating): red over cyan is WHITE, red over a transparent cell red, the yellow block over
; cyan white; with no Layer 2 above it the ULA isn't drawn at all (blend mode 00: the tilemap is the top and
; bottom of the mix), so the cyan-only cells and the border go grey; the label shows (black + white = white).
; Band 7 (add, minus 5): red over cyan is dark grey (7 -> 2 in each channel), red over a transparent cell
; stays red (no subtraction without a ULA colour), the label is dark grey on black.
; Vernier A (rows 128-143): ULA white lines and Layer 2 red lines both at x = 16k: red only if aligned.
; Vernier B (rows 144-159): Layer 2's lines at x = 16k + 1 on purpose: what one pixel off looks like.
;
; Writes the Layer 2 bank NR 12 already names (NextZXOS's own Layer 2 screen), the ULA screen, palette entries
; and the copper; the key's soft reset puts the machine back. Hatch Fern, Fri 06 Nov 2026.
TAPEID  equ 91                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B
seg     equ VARS+8

main:   call screen_init
        ld hl,regs              ; palettes, transparency, fallback, Layer 2's mode
m1:     ld a,(hl)
        cp 0xFF
        jr z,m2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr m1
m2:     call fill_l2
        call draw_ula
        ld a,1                  ; border 1: navy (palette entry 17)
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld hl,copper            ; the copper list, through NR 0x63 (MSB, then LSB)
        ld a,0x62
        ld e,0x00
        call nrwr
        ld a,0x61
        ld e,0x00
        call nrwr
m3:     ld a,(hl)
        inc hl
        ld e,(hl)
        inc hl
        push de
        ld e,a                  ; MSB
        ld a,0x63
        call nrwr
        pop de                  ; LSB in E
        ld a,0x63
        call nrwr
        ld a,e
        cp 0xFF                 ; the HALT word (FFFF) ends the list
        jr nz,m3
        ld a,0x62
        ld e,0xC0               ; mode 11: from index 0, restarting at raster (0,0) every frame
        call nrwr
        jp finish

; ---- Layer 2: three 16K segments through port 0x123B's write mapping at 0x0000-0x3FFF
fill_l2:
        ld d,0                  ; D = Y
        xor a
        ld (seg),a
fl1:    ld a,(seg)
        rrca
        rrca
        or 0x01                 ; segment in bits 7:6, writes mapped, display off for now
        ld bc,L2PORT
        out (c),a
        ld hl,0x0000
fl2:    call l2row
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
        ld a,0x02               ; display on, mapping off
        ld bc,L2PORT
        out (c),a
        ret

l2row:  ld a,d                  ; one row: D = Y, HL = its first byte (L = 0)
        cp 128
        jr c,band
        cp 144
        jr c,vern0
        cp 160
        jr c,vern1
        ld a,0xE3
        ld b,0
lr1:    ld (hl),a
        inc l
        djnz lr1
        ret
vern0:  ld e,0
        jr vern
vern1:  ld e,1
vern:   ld b,0
v1:     ld a,l
        and 15
        cp e
        ld a,0xE3
        jr nz,v2
        ld a,0xE0
v2:     ld (hl),a
        inc l
        djnz v1
        ret
band:   ld a,d
        and 15
        ld c,a                  ; C = row within the band
        ld b,128
b1:     ld a,l                  ; the priority block: x 96-119, band rows 4-11
        cp 96
        jr c,b3
        cp 120
        jr nc,b3
        ld a,c
        cp 4
        jr c,b3
        cp 12
        jr nc,b3
        ld a,0xFC
        jr b4
b3:     ld a,l                  ; stripes: (x + Y) mod 16 < 6
        add a,d
        and 15
        cp 6
        ld a,0xE0
        jr c,b4
        ld a,0xE3
b4:     ld (hl),a
        inc l
        djnz b1
        ld a,d                  ; right half: black behind the labels of bands 6 and 7, else transparent
        cp 96
        ld a,0xE3
        jr c,b5
        xor a
b5:     ld b,128
b6:     ld (hl),a
        inc l
        djnz b6
        ret

; ---- the ULA: checker cells, label column, vernier lines, captions
draw_ula:
        ld hl,0x4000            ; bitmap clear
        ld de,0x4001
        ld bc,6143
        ld (hl),0
        ldir
        ld de,0x5800            ; attributes, row by row
        ld c,0                  ; C = char row
da1:    ld b,0                  ; B = column
da2:    ld a,c
        cp 16
        jr nc,da4
        ld a,b
        cp 16
        jr nc,da4
        add a,c                 ; checker: (row + col) odd -> cyan paper, even -> transparent paper
        and 1
        ld a,0x38               ; paper 7 (E3), ink 0
        jr z,da3
        ld a,0x28               ; paper 5 (cyan), ink 0
da3:    jr da5
da4:    ld a,0x07               ; white ink on black paper
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
        ld hl,0x5800+23*32      ; the prompt row, black on yellow
        ld b,32
da6:    ld (hl),0x30
        inc hl
        djnz da6
        ld hl,0x5000            ; vernier lines: char rows 16-19 (the bottom third's rows 0-3), x = 16k
        ld c,8                  ; every pixel line of those rows
da7:    push hl
        ld b,4*32
da8:    ld a,l
        and 1
        ld a,0x80
        jr z,da9
        xor a
da9:    ld (hl),a
        inc hl
        djnz da8
        pop hl
        inc h
        dec c
        jr nz,da7
        ld hl,labels
        jp pstr

regs:   db 0x43,0x00            ; ULA first palette: the entries the card uses
        db 0x40,0x00,0x41,0x00  ; ink 0 black
        db 0x40,0x07,0x41,0xFF  ; ink 7 white
        db 0x40,0x10,0x41,0x00  ; paper 0 black
        db 0x40,0x11,0x41,0x02  ; paper 1 navy (the border)
        db 0x40,0x15,0x41,0x1F  ; paper 5 cyan
        db 0x40,0x17,0x41,0xE3  ; paper 7 = the transparent colour
        db 0x43,0x10            ; Layer 2 first palette
        db 0x40,0xE3,0x41,0xE3  ; E3 transparent, E0 red, 00 black
        db 0x40,0xE0,0x41,0xE0
        db 0x40,0x00,0x41,0x00
        db 0x40,0xFC,0x44,0xFC,0x44,0x80   ; FC yellow, with the priority bit
        db 0x43,0x00            ; first palettes shown
        db 0x14,0xE3            ; global transparency
        db 0x4A,0x49            ; fallback grey
        db 0x15,0x00            ; SLU, sprites and LoRes off
        db 0x68,0x00            ; ULA on, blend mode 00
        db 0x70,0x00            ; Layer 2 256x192, palette offset 0
        db 0x16,0x00,0x17,0x00,0x71,0x00
        db 0x1C,0x01,0x18,0x00,0x18,0xFF,0x18,0x00,0x18,0xBF
        db 0xFF

copper: db 0xD8,0x0F,0x15,0x04  ; WAIT (15,44)  MOVE NR15 <- 1 LSU   (MSB first, as NR 0x63 takes them)
        db 0xD8,0x1F,0x15,0x08  ; WAIT (31,44)  MOVE NR15 <- 2 SUL
        db 0xD8,0x2F,0x15,0x0C  ; WAIT (47,44)  MOVE NR15 <- 3 LUS
        db 0xD8,0x3F,0x15,0x10  ; WAIT (63,44)  MOVE NR15 <- 4 USL
        db 0xD8,0x4F,0x15,0x14  ; WAIT (79,44)  MOVE NR15 <- 5 ULS
        db 0xD8,0x5F,0x15,0x18  ; WAIT (95,44)  MOVE NR15 <- 6 blend
        db 0xD8,0x6F,0x15,0x1C  ; WAIT (111,44) MOVE NR15 <- 7 blend
        db 0xD8,0x7F,0x15,0x00  ; WAIT (127,44) MOVE NR15 <- 0 SLU for the vernier, captions and next frame
        db 0xFF,0xFF            ; HALT

labels: db 22,0,17,"0 SLU",22,1,17,"L over U"
        db 22,2,17,"1 LSU",22,3,17,"L over U"
        db 22,4,17,"2 SUL",22,5,17,"U over L"
        db 22,6,17,"3 LUS",22,7,17,"L over U"
        db 22,8,17,"4 USL",22,9,17,"U over L"
        db 22,10,17,"5 ULS",22,11,17,"U over L"
        db 22,12,17,"6 L+U",22,13,17,"add, max 7"
        db 22,14,17,"7 L+U-5",22,15,17,"add, minus 5"
        db 22,20,0,"P-V1: one NR15 order per band"
        db 22,21,0,"Vernier A: red only = aligned"
        db 22,22,0,"Vernier B: 1px off on purpose",0
