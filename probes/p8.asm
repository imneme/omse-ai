; P-8 LAYER 2 OVER BANK 5. 16K bank 5 lives only in block RAM for the CPU and the ULA (zxnext.vhd:2920, 3020,
; 6469-6485), but Layer 2 reads SRAM (layer2.vhd:169-188), and writes through port 0x123B's Layer 2 mapping go to
; SRAM even for bank 5 (zxnext.vhd:3059-3066). So with Layer 2 based at bank 5 (NR 12 = 5):
;   0. SRAM's copy of bank 5 is filled with E3 (transparent) through the 123B mapping,
;   A. the ULA's top third (0x4000-0x47FF) is written with 1C through the MMU: the ULA shows thin stripes, and
;      Layer 2, reading SRAM, still shows nothing (were it reading the same memory: solid green),
;   B. Layer 2's rows 0-7 are written with E0 through the 123B mapping: a red band, and the ULA's stripes stay
;      (were it the same memory, the ULA's whole top third would change pattern).
; Layer 2 is clipped to rows 0-63 (bank 5 only) so banks 6 and 7 are never touched. Second key: Layer 2 off.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 8                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

L2PORT  equ 0x123B

main:   call screen_init
        xor a                   ; the top third is the test area: plain attributes, no title there
        ld (prow),a
        ld a,ATTR
        call hilite
        ld hl,s_text
        call pstr
        ld a,16
        ld (prow),a
        ld a,0x0F
        call hilite
        ld hl,l2regs            ; Layer 2: bank 5, 256x192, no scroll, clip rows 0-63, palette entries
l1:     ld a,(hl)
        cp 0xFF
        jr z,l2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr l1
l2:     ld a,0x10               ; first, the 123B mapping's bank offset to 0: it applies to the CPU's mapping but not
        ld bc,L2PORT            ; the display, and NextZXOS can leave it set (Hart's-tongue's reading of Melissa O'Neill's
        out (c),a               ; first P-8 photo, 6 Nov; fix applied by Tally)
        ld a,0x01               ; 0. segment 0 (bank 5) mapped for writes at 0000-3FFF, display off
        ld bc,L2PORT
        out (c),a
        ld hl,0x0000
        ld de,0x0001
        ld bc,0x3FFF
        ld (hl),0xE3
        ldir
        xor a
        ld bc,L2PORT
        out (c),a
        ld hl,0x4000            ; A. the ULA's top third through the MMU (bank 5 block RAM)
        ld de,0x4001
        ld bc,0x07FF
        ld (hl),0x1C
        ldir
        ld a,0x03               ; B. Layer 2 on, mapped for writes: rows 0-7 red
        ld bc,L2PORT
        out (c),a
        ld hl,0x0000
        ld de,0x0001
        ld bc,0x07FF
        ld (hl),0xE0
        ldir
        ld a,0x02               ; Layer 2 on, mapping off
        ld bc,L2PORT
        out (c),a
        ld hl,s_prompt1
        call pstr
        call photokey           ; the photo beep, then a key
        xor a                   ; Layer 2 off: what's underneath rows 0-7
        ld bc,L2PORT
        out (c),a
        ld hl,s_prompt2
        call pstr
        call photokey           ; the photo beep, then a key
        call softreset
        jp back

l2regs: db 0x12,0x05            ; Layer 2 based at 16K bank 5
        db 0x70,0x00            ; 256x192x8, palette offset 0
        db 0x16,0x00,0x17,0x00,0x71,0x00
        db 0x14,0xE3            ; global transparency E3
        db 0x1C,0x01            ; Layer 2 clip: x 0-255, y 0-63
        db 0x18,0x00,0x18,0xFF,0x18,0x00,0x18,0x3F
        db 0x43,0x10            ; edit Layer 2's first palette, auto-increment, first palettes active
        db 0x40,0xE3,0x41,0xE3  ; E3 -> E3 (transparent), E0 -> red, 1C -> green
        db 0x40,0xE0,0x41,0xE0
        db 0x40,0x1C,0x41,0x1C
        db 0x43,0x00
        db 0xFF
s_text: db 22,16,0,"P-8 LAYER 2 OVER BANK 5"
        db 22,17,0,"Top third: ULA stripes, written"
        db 22,18,0,"through the MMU. Red band: Layer"
        db 22,19,0,"2 rows 0-7, written through 123B"
        db 22,20,0,"VHDL: stripes everywhere but"
        db 22,21,0,"the red band; no green at all.",0
s_prompt1:
        db 22,23,0,"Photo, then a key: Layer 2 off",0
s_prompt2:
        db 22,22,0,"Layer 2 off: stripes all over.  "
        db 22,23,0,"Photo, then a key: soft reset. ",0
