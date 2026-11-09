; P-4 MMU PAGES E0-FF. nextreg.txt: "A 255 value causes the ROM to become visible" (MMU0/1). The VHDL: in slots 0-1
; any page E0-FF shows the ROM (zxnext.vhd:2923, 2996-3017). In slots 2-7 such a page is no memory at all: no SRAM
; cycle, writes vanish, and a read returns the last byte the SRAM gave the CPU (zxnext.vhd:3019-3020, 3113, 1824;
; zxnext_top_issue4.vhd:1219-1233). For LD A,(nn) that's nn's own high byte, the instruction's last fetch.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 4                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

sums    equ BUF                 ; 4 x 16-bit
nmres   equ BUF+0x10            ; 2 x 4 results
mmu0    equ BUF+0x20
mmu1    equ BUF+0x21
mmu7    equ BUF+0x22
kept    equ BUF+0x23            ; the real page's byte at E000, before and after
kept2   equ BUF+0x24

main:   ld a,0x50
        call nrrd
        ld (mmu0),a
        ld a,0x51
        call nrrd
        ld (mmu1),a
        ld a,0x57
        call nrrd
        ld (mmu7),a
        ld a,(0xE000)           ; the real page's byte, to check afterwards that the tests never wrote it
        ld (kept),a
        ld hl,romsettings       ; 1. what appears at 0000-3FFF for each MMU0/1 value
        ld ix,sums
        ld b,4
s1:     push bc
        ld a,(hl)
        inc hl
        push hl
        ld e,a
        ld a,0x50
        call nrwr
        ld a,0x51
        call nrwr
        call csum
        ld (ix+0),l
        ld (ix+1),h
        inc ix
        inc ix
        pop hl
        pop bc
        djnz s1
        ld a,(mmu0)
        ld e,a
        ld a,0x50
        call nrwr
        ld a,(mmu1)
        ld e,a
        ld a,0x51
        call nrwr
        ld e,0xE0               ; 2. MMU7 = E0, then FF: reads from no memory
        ld ix,nmres
        call nomem
        ld e,0xFF
        ld ix,nmres+4
        call nomem
        ld a,(mmu7)
        ld e,a
        ld a,0x57
        call nrwr
        ld a,(0xE000)
        ld (kept2),a
        ld a,(kept)             ; and put it back, in case it did change
        ld (0xE000),a
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_sums
        call pstr
        ld hl,romsettings
        ld ix,sums
        ld b,4
p1:     ld a,(hl)
        inc hl
        call phex8
        ld a,':'
        call pchr
        push hl
        ld l,(ix+0)
        ld h,(ix+1)
        call phex16
        pop hl
        call pspace
        inc ix
        inc ix
        djnz p1
        ld hl,s_e0
        call pstr
        ld ix,nmres
        call pres
        ld hl,s_ff
        call pstr
        ld ix,nmres+4
        call pres
        ld hl,s_kept
        call pstr
        ld a,(kept)
        call phex8
        call pspace
        ld a,(kept2)
        call phex8
        jp finish

; MMU7 = E, write 55 to E000, then four reads into IX+0..3
nomem:  ld a,0x57
        call nrwr
        ld a,0x55
        ld (0xE000),a
        ld a,(0xE000)           ; expect E0
        ld (ix+0),a
        ld hl,0xE000
        ld a,(hl)               ; expect 7E (this instruction's opcode)
        ld (ix+1),a
        ld a,(0xFFFF)           ; expect FF
        ld (ix+2),a
        ld a,(0xE123)           ; expect E1
        ld (ix+3),a
        ret

; print IX+0..3 under their labels
pres:   ld hl,s_r1
        call pstr
        ld a,(ix+0)
        call phex8
        ld hl,s_r2
        call pstr
        ld a,(ix+1)
        call phex8
        ld hl,s_r3
        call pstr
        ld a,(ix+2)
        call phex8
        ld hl,s_r4
        call pstr
        ld a,(ix+3)
        jp phex8

; HL = 16-bit sum of the bytes at 0000-3FFF
csum:   ld hl,0
        ld de,0
        ld bc,0x4000
cs1:    ld a,(de)
        add a,l
        ld l,a
        jr nc,cs2
        inc h
cs2:    inc de
        dec bc
        ld a,b
        or c
        jr nz,cs1
        ret

romsettings: db 0xFF, 0xE0, 0xF7, 0xDF
s_title: db "P-4 MMU PAGES E0-FF",0
s_sums: db 22,2,0,"16K sums at 0000 by MMU0/1:",13,0
s_e0:   db 22,5,0,"MMU7=E0, wrote 55 at E000:",0
s_ff:   db 22,9,0,"MMU7=FF, wrote 55 at E000:",0
s_r1:   db 13,"ld a,(E000) ",0
s_r2:   db "  ld a,(hl) ",0
s_r3:   db 13,"ld a,(FFFF) ",0
s_r4:   db "  ld a,(E123) ",0
s_kept: db 22,13,0,"real E000 byte before/after:",13,0
