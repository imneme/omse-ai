; P-1 IDENTITY AND STATE: what the core is, and what NextZXOS (or whatever ran us) left in the registers.
; Reads only, apart from the memory test, which restores every byte it touches and MMU7.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 1                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

NREGS   equ 50
vals    equ BUF                 ; the registers' values, read first, in regtab's order
memres  equ BUF+0x100           ; 3 results x (read55, readAA)

main:   ld hl,regtab            ; 1. read everything before changing anything
        ld de,vals
        ld b,NREGS
m1:     ld a,(hl)
        call nrrd
        ld (de),a
        inc hl
        inc de
        djnz m1
        call memtest            ; 2. memory pages, through MMU7
        call screen_init        ; 3. now the display may change
        ld hl,s_title
        call pstr
        ld hl,groups            ; each group: a label string, then a count of registers to print
        ld ix,regtab
        ld iy,vals
g1:     ld a,(hl)
        or a
        jr z,g_done
        call pchr_nl_label      ; label (zero-terminated), starting a new line
        ld b,(hl)               ; registers in this group
        inc hl
        push hl
        ld c,0                  ; five to a line
g2:     ld a,c
        cp 5
        jr nz,g3
        ld a,13
        call pchr
        ld c,0
g3:     inc c
        ld a,(ix+0)
        call phex8
        ld a,'='
        call pchr
        ld a,(iy+0)
        call phex8
        call pspace
        inc ix
        inc iy
        djnz g2
        pop hl
        jr g1
g_done: ld hl,s_mem             ; the memory test
        call pstr
        ld hl,mempages
        ld de,memres
        ld b,3
mm1:    push bc
        ld a,(hl)
        inc hl
        call phex8
        ld a,':'
        call pchr
        ld a,(de)
        inc de
        call phex8
        ld a,'/'
        call pchr
        ld a,(de)
        inc de
        call phex8
        call pspace
        pop bc
        djnz mm1
        jp finish

; Print the label at HL on a new line; leave HL after its zero.
pchr_nl_label:
        ld a,(pcol)
        or a
        ld a,13
        call nz,pchr
        ld a,0x28               ; label rows black on cyan
        call hilite
        call pstr
        ld a,13
        jp pchr

; For each page in mempages: MMU7 = page, keep the byte at 0xE000, write 0x55 and read back, write 0xAA and
; read back, put the byte back. Then MMU7 as it was. A page that's there reads 55 and AA.
memtest:
        ld a,0x57
        call nrrd
        push af                 ; MMU7 as it was
        ld hl,mempages
        ld de,memres
        ld b,3
mt1:    push bc
        ld a,0x57
        push de
        ld e,(hl)
        call nrwr
        pop de
        inc hl
        ld a,(0xE000)
        ld c,a                  ; the byte that was there
        ld a,0x55
        ld (0xE000),a
        ld a,(0xE000)
        ld (de),a
        inc de
        ld a,0xAA
        ld (0xE000),a
        ld a,(0xE000)
        ld (de),a
        inc de
        ld a,c
        ld (0xE000),a
        pop bc
        djnz mt1
        pop af
        ld e,a
        ld a,0x57
        jp nrwr

mempages: db 0x5F, 0x60, 0xDF   ; the last 1 MB page, the first page above 1 MB, the last 2 MB page

regtab: db 0x00,0x01,0x0E,0x0F,0x02             ; identity, reset type
        db 0x03,0x05,0x06,0x07,0x08             ; machine, peripherals, speed
        db 0x09,0x0A,0x0B,0x10,0x11
        db 0x50,0x51,0x52,0x53,0x54             ; MMU, legacy paging
        db 0x55,0x56,0x57,0x8E,0x8F
        db 0x82,0x83,0x84,0x85,0x80             ; port enables, expansion bus, alt ROM, user reg
        db 0x86,0x87,0x88,0x89,0x81
        db 0x8A,0x8C,0x7F,0x12,0x13
        db 0xB8,0xB9,0xBA,0xBB,0xC0             ; divMMC entry points, interrupts
        db 0xC4,0xC5,0xC6,0x22,0x64
groups: db "id core board reset:",0,5
        db "machine speed periph:",0,10
        db "MMU 50-57, 8E 8F:",0,10
        db "ports 82-89, bus, 7F, L2:",0,15
        db "divMMC B8-BB, ints:",0,10
        db 0
s_title: db "P-1 IDENTITY + STATE (reg=val)",0
s_mem:  db 13,"pages w55/wAA: ",13,0
