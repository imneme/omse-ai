; P-3 THE CTC'S CHANNELS. nextreg.txt lists eight (NR C5, C9, CD, the IM2 table); the VHDL builds four
; (NUM_CTC => 4, zxnext.vhd:4005-4034), as ports.txt says. Channels 4-7's ports decode but select nothing.
; 1. NR C5 (CTC interrupt enables) written FF and read back: four channels give 0F. Then put back.
; 2. Every channel set running (timer, prescaler 256, time constant C8, no interrupt), read twice a little
;    apart: channels 0-3 count down (two different numbers), 4-7 read 00 00. NR C9 (status) gets 0F.
; 3. Every channel stopped again, NR C9 cleared.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 3                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

reads   equ BUF                 ; 8 channels x 2 reads

main:   ld a,0xC5
        call nrrd
        ld (c5was),a
        ld a,0xC9
        call nrrd
        ld (c9was),a
        ld a,0x07               ; 3.5 MHz, so the waits below are long enough whatever speed we came in at
        ld e,0x00
        call nrwr
        call stopall            ; every channel in its reset state before touching C5
        ld a,0xC5
        ld e,0xFF
        call nrwr
        ld a,0xC5
        call nrrd
        ld (c5ff),a
        ld a,0xC5
        ld e,0x00
        call nrwr
        ld a,0xC5
        call nrrd
        ld (c500),a
        ld b,0                  ; run them all
        ld c,0
r1:     push bc
        ld a,c
        call ctcport
        ld a,0x27               ; control: timer, prescaler 256, time constant follows, soft reset
        out (c),a
        ld a,0xC8
        out (c),a
        pop bc
        inc c
        ld a,c
        cp 8
        jr nz,r1
        ld b,0                  ; let them count a while
r2:     djnz r2
        ld hl,reads
        call readall
        ld b,0
r3:     djnz r3
        ld hl,reads+1
        call readall
        ld d,8                  ; about 7.6 ms more: each channel reaches zero (every 1.83 ms) a few times
r4:     ld b,0
r4b:    djnz r4b
        dec d
        jr nz,r4
        ld a,0xC9
        call nrrd
        ld (c9run),a
        call stopall
        ld a,0xC9               ; clear the status they made, put the enables back
        ld e,0xFF
        call nrwr
        ld a,(c5was)
        ld e,a
        ld a,0xC5
        call nrwr
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_c5
        call pstr
        ld a,(c5was)
        call phex8
        ld hl,s_c5b
        call pstr
        ld a,(c5ff)
        call phex8
        ld hl,s_c5c
        call pstr
        ld a,(c500)
        call phex8
        ld hl,s_run
        call pstr
        ld c,0                  ; "n port: aa bb", one channel a line
p1:     ld a,13
        call pchr
        ld a,c
        add a,'0'
        call pchr
        call pspace
        ld a,c
        add a,0x18
        call phex8
        ld a,0x3B
        call phex8
        ld a,':'
        call pchr
        call pspace
        ld l,c
        ld h,0
        add hl,hl
        ld de,reads
        add hl,de
        ld a,(hl)
        call phex8
        call pspace
        inc hl
        ld a,(hl)
        call phex8
        inc c
        ld a,c
        cp 8
        jr nz,p1
        ld hl,s_c9
        call pstr
        ld a,(c9was)
        call phex8
        ld hl,s_c9b
        call pstr
        ld a,(c9run)
        call phex8
        jp finish

; BC = the port of channel A: 0x183B + 0x100 * A
ctcport:
        add a,0x18
        ld b,a
        ld c,0x3B
        ret

; Read the eight channels into HL, HL+2, ... (every other byte)
readall:
        ld e,0
ra1:    ld a,e
        call ctcport
        in a,(c)
        ld (hl),a
        inc hl
        inc hl
        inc e
        ld a,e
        cp 8
        jr nz,ra1
        ret

; Every channel to its reset state: control word 03 (soft reset, no time constant), twice, as ctc_chan.vhd's
; notes ask (a channel waiting for a time constant takes the first write as one).
stopall:
        ld e,0
sa1:    ld a,e
        call ctcport
        ld a,0x03
        out (c),a
        out (c),a
        inc e
        ld a,e
        cp 8
        jr nz,sa1
        ret

c5was:  db 0
c5ff:   db 0
c500:   db 0
c9was:  db 0
c9run:  db 0
s_title: db "P-3 THE CTC'S CHANNELS",0
s_c5:   db 22,2,0,"NR C5 was ",0
s_c5b:  db 22,3,0,"wrote FF, read ",0
s_c5c:  db 22,4,0,"wrote 00, read ",0
s_run:  db 22,6,0,"running, read twice:",0
s_c9:   db 22,17,0,"NR C9 was ",0
s_c9b:  db 22,18,0,"after running ",0
