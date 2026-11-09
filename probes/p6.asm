; P-6 WAIT STATES AT 14 AND 28 MHZ. The VHDL (zxnext.vhd:3128-3140): at 28 MHz every memory read with an SRAM
; request, or a bank-5 block-RAM read, gets one WAIT cycle; writes and bank-7 block-RAM reads (page 0E) don't;
; at 14 MHz there are no memory waits. Timed with the CTC as a stopwatch: channel 0 a timer at 28 MHz / 16,
; channel 1 counting its zero crossings, so a tick is 16 cycles of the 28 MHz clock, whatever the CPU speed
; (ctc_chan.vhd; the CTC runs on the 28 MHz clock, zxnext.vhd:4013). Six sleds of 4095 instructions + RET:
;   A NOP in SRAM (8 passes)   B NOP in bank 7 block RAM   C NOP in bank 5 block RAM
;   D LD A,(HL) from SRAM (4 passes)   E LD (HL),A to SRAM   F LD A,(HL) from bank 7 block RAM
; Each net of an empty test (the call and return around it). Bank 7's and bank 5's 4K are saved and put back.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 6                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

ticks   equ VARS+0x10           ; 2 speeds x 7 tests (empty first) x 2 bytes (not in BUF: the 4K saves use it)
w0      equ VARS+0x30
mmu7    equ VARS+0x32
nr07    equ VARS+0x33

main:   ld a,0x07
        call nrrd
        ld (nr07),a
        ld a,0x57
        call nrrd
        ld (mmu7),a
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_wait
        call pstr
        call ctcstop
        ld bc,0x193B            ; channel 1: counter of channel 0's zero crossings, constant 256
        ld a,0x47
        out (c),a
        xor a
        out (c),a
        ld bc,0x183B            ; channel 0: timer, 28 MHz / 16, constant 256
        ld a,0x07
        out (c),a
        xor a
        out (c),a
        ld ix,ticks
        ld a,2                  ; 14 MHz
        call speed_run
        ld a,3                  ; 28 MHz
        call speed_run
        xor a                   ; back to 3.5 MHz
        ld e,a
        ld a,0x07
        call nrwr
        call ctcstop
        ld a,(mmu7)
        ld e,a
        ld a,0x57
        call nrwr
        ld hl,s_head            ; the table
        call pstr
        ld b,6
        ld c,'A'
        ld ix,ticks+2           ; 14 MHz results, after the empty test
        ld iy,expect
pt1:    ld a,13
        call pchr
        ld a,c
        call pchr
        call pspace
        push bc
        call netprint14
        pop bc
        inc ix
        inc ix
        inc c
        djnz pt1
        ld hl,s_legend
        call pstr
        ld hl,(ticks)           ; the empty tests
        call pdec5
        call pspace
        ld hl,(ticks+14)
        call pdec5
        ld hl,s_nr07
        call pstr
        ld a,(nr07)
        call phex8
        jp finish

; Print row: 14 MHz net (expected) and 28 MHz net (expected). IX -> this test's 14 MHz ticks; IY -> expectations.
netprint14:
        ld l,(ix+0)
        ld h,(ix+1)
        ld de,(ticks)           ; empty test at 14 MHz
        or a
        sbc hl,de
        call pdec5
        ld a,'('
        call pchr
        ld l,(iy+0)
        ld h,(iy+1)
        call pdec5
        ld a,')'
        call pchr
        call pspace
        ld l,(ix+14)            ; the same test at 28 MHz
        ld h,(ix+15)
        ld de,(ticks+14)        ; empty test at 28 MHz
        or a
        sbc hl,de
        call pdec5
        ld a,'('
        call pchr
        ld l,(iy+2)
        ld h,(iy+3)
        call pdec5
        ld a,')'
        call pchr
        inc iy
        inc iy
        inc iy
        inc iy
        ret

; At speed A (NR 07): the empty test and A-F, ticks to IX, IX+2, ...
speed_run:
        ld e,a
        ld a,0x07
        call nrwr
        ld b,0                  ; let the speed change settle
sp1:    djnz sp1
        push ix
        ld ix,tZ
        call measure
        pop ix
        call store
        ld a,0x00               ; the NOP sled
        call fill
        push ix
        ld ix,tA
        call measure
        pop ix
        call store
        call b7save             ; B: the sled in bank 7's first 8K (page 0E), its 4K put back after
        ld hl,SLED
        ld de,0xE000
        ld bc,4096
        ldir
        push ix
        ld ix,tB
        call measure
        pop ix
        call store
        call b7restore
        ld hl,0x6000            ; C: the sled in bank 5 (page 0B), its 4K put back after
        ld de,BUF
        ld bc,4096
        ldir
        ld hl,SLED
        ld de,0x6000
        ld bc,4096
        ldir
        push ix
        ld ix,tC
        call measure
        pop ix
        call store
        ld hl,BUF
        ld de,0x6000
        ld bc,4096
        ldir
        ld a,0x7E               ; D: LD A,(HL) from SRAM
        call fill
        push ix
        ld ix,tD
        call measure
        pop ix
        call store
        ld a,0x77               ; E: LD (HL),A to SRAM (to BUF)
        call fill
        push ix
        ld ix,tE
        call measure
        pop ix
        call store
        ld a,0x7E               ; F: LD A,(HL) from bank 7 (MMU7 = 0E, read only)
        call fill
        ld a,0x57
        ld e,0x0E
        call nrwr
        push ix
        ld ix,tF
        call measure
        pop ix
        call store
        ld a,(mmu7)
        ld e,a
        ld a,0x57
        jp nrwr

store:  ld (ix+0),l
        ld (ix+1),h
        inc ix
        inc ix
        ret

; SLED = 4095 x A, then RET
fill:   ld hl,SLED
        ld de,SLED+1
        ld bc,4094
        ld (hl),a
        ldir
        ld a,0xC9
        ld (SLED+4095),a
        ret

b7save: ld a,0x57
        ld e,0x0E
        call nrwr
        ld hl,0xE000
        ld de,BUF
        ld bc,4096
        ldir
        ret
b7restore:
        ld hl,BUF
        ld de,0xE000
        ld bc,4096
        ldir
        ld a,(mmu7)
        ld e,a
        ld a,0x57
        jp nrwr

; HL = ticks taken by the routine at IX
measure:
        call swread
        ld (w0),hl
        call jpix
        call swread
        ex de,hl
        ld hl,(w0)
        or a
        sbc hl,de               ; the counters count down
        ret
jpix:   jp (ix)

; HL = channel 1 : (channel 0 - 1), read consistently (channel 0 at 00 has just reloaded; channel 1 follows a
; couple of cycles later, so wait it out)
swread: ld bc,0x183B
        in a,(c)
        or a
        jr z,swread
        ld bc,0x193B
        in h,(c)
        ld bc,0x183B
        in l,(c)
        ld bc,0x193B
        in a,(c)
        cp h
        jr nz,swread
        ld a,l
        or a
        jr z,swread
        dec l
        ret

ctcstop:
        ld e,0
cs1:    ld a,e
        add a,0x18
        ld b,a
        ld c,0x3B
        ld a,0x03
        out (c),a
        out (c),a
        inc e
        ld a,e
        cp 8
        jr nz,cs1
        ret

tZ:     ret
tA:     ld b,8
tA1:    call SLED
        djnz tA1
        ret
tB:     ld b,8
tB1:    call 0xE000
        djnz tB1
        ret
tC:     ld b,8
tC1:    call 0x6000
        djnz tC1
        ret
tD:     ld hl,SLED
        ld b,4
tD1:    call SLED
        djnz tD1
        ret
tE:     ld hl,BUF
        ld b,4
tE1:    call SLED
        djnz tE1
        ret
tF:     ld hl,0xE000
        ld b,4
tF1:    call SLED
        djnz tF1
        ret

; HL as five decimal digits
pdec5:  ld bc,10000
        call pdd
        ld bc,1000
        call pdd
        jp pdec3

; Expected net ticks by the VHDL (16 cycles of 28 MHz each), per test: 14 MHz, 28 MHz. Worked in NOTES.md.
expect: dw 16420, 10262         ; A NOP SRAM
        dw 16420, 8214          ; B NOP bank 7
        dw 16420, 10262         ; C NOP bank 5
        dw 14354, 9227          ; D LD A,(HL) SRAM
        dw 14354, 8203          ; E LD (HL),A SRAM
        dw 14354, 8203          ; F LD A,(HL) bank 7

s_title: db "P-6 WAIT STATES, 14 / 28 MHZ",0
s_wait: db 22,2,0,"timing...",0
s_head: db 22,2,0,"CTC ticks of 16 x 28MHz cycles,"
        db 22,3,0,"net (VHDL's figure in brackets)"
        db 22,4,2,"14 MHz        28 MHz",0
s_legend:
        db 22,12,0,"A nop SRAM     B nop bank 7"
        db 22,13,0,"C nop bank 5   D ld a,(hl) SRAM"
        db 22,14,0,"E ld (hl),a    F ld a,(hl) bk7"
        db 22,16,0,"no 28MHz waits would give"
        db 22,17,0,"A-C 08210, D-F 07177"
        db 22,19,0,"empty test: ",0
s_nr07: db 22,20,0,"NR 07 was ",0
