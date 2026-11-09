; P-7 INT AGAINST THE BEAM (48K timing, 3.5 MHz). Where does the ULA interrupt sit relative to contention, to
; the T-state? Run identically on the real Next and on Ratio's core: if both print the same flip point, the core
; places INT right. By the VHDL the first holdable T-state is 14337 T after the first CPU edge that sees INT
; (zxula_timing.vhd:548-559; zxula.vhd:582-583; zxnext_top_issue4.vhd:994-1003); the original 48K's is 14335.
;
; Each sample: HALT wakes at frame N's INT (IM 2, our own vector table, an ISR that just returns). An exact delay
; reaches screen row 0, where four LD A,(DE) from bank 5, 11 T apart, run into contention: whatever HALT's 0-3 T
; jitter, they converge to one T-state (a hold ends at a fixed ULA phase). Then a fixed delay, a padding of
; 66+k T, and IN from port 0x253B with NR 0x22 selected: bit 7 is "the pulse INT is low" (zxnext.vhd:5899). k
; runs 0-63, one sample every two frames, so the scan crosses frame N+1's INT edge 1 T at a time and shows the
; pulse (32 T at 48K timing, zxnext.vhd:1971-2003). Everything timed runs from SRAM, uncontended.
; Timing, 50/60 Hz, speed and contention are put back before printing; the soft reset does the rest.
; Hart's-tongue Fern, Fri 06 Nov 2026.
TAPEID  equ 7                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

NDLY1   equ 550                 ; HALT wake -> first contended read at about row 0, T 28
NDLY2   equ 2128                ; synced -> the scan window around frame N+1's INT
samples equ BUF                 ; 64 bytes
IMTAB   equ 0xB400              ; IM 2 vector table, 257 x B6
ISR     equ 0xB6B6

sv03    equ VARS+0x10
sv05    equ VARS+0x11
sv07    equ VARS+0x12
sv08    equ VARS+0x13
sv64    equ VARS+0x14
kval    equ VARS+0x15
entc    equ VARS+0x16           ; coarse entry (2 bytes)
entf    equ VARS+0x18           ; fine entry (2 bytes)
entc2   equ VARS+0x1A           ; the same for the compensating padding, 63 - k
entf2   equ VARS+0x1C

main:   ld a,0x03
        call nrrd
        ld (sv03),a
        ld a,0x05
        call nrrd
        ld (sv05),a
        ld a,0x07
        call nrrd
        ld (sv07),a
        ld a,0x08
        call nrrd
        ld (sv08),a
        ld a,0x64
        call nrrd
        ld (sv64),a
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_run
        call pstr
        ld hl,setregs           ; 48K timing, 50 Hz, 3.5 MHz, contention on, offset 0, only the ULA interrupt
        call nrlist
        ld a,(sv05)
        and 0xFB
        ld e,a
        ld a,0x05
        call nrwr
        ld a,(sv08)
        and 0xBF
        ld e,a
        ld a,0x08
        call nrwr
        call wait3              ; the timing changes at a frame sync
        ld hl,IMTAB             ; IM 2: every vector to ISR, which returns with interrupts still off
        ld de,IMTAB+1
        ld bc,256
        ld (hl),ISR/256
        ldir
        ld a,0xC9
        ld (ISR),a
        ld a,IMTAB/256
        ld i,a
        im 2
        ld a,0x22               ; NR 22 selected for the whole scan
        ld bc,NRSEL
        out (c),a
        xor a
        ld (kval),a
sloop:  call entries            ; this k's padding entry points, before the timed part
        ld bc,NRDAT
        ld de,0x4000            ; bank 5: contended in 48K timing
        ei
        halt                    ; frame N's INT -> ISR -> here, interrupts off
        call dly1
        ld a,0                  ; 11 T (3 mod 8): on omse-ai's 48K this puts HALT's four jitter cases in one
        nop                     ; contention group's delay slots, with room for the Next's window 2 T later
sync0:  ld a,(de)               ; converge on the ULA: four contended reads, 11 T apart
        nop
        ld a,(de)
        nop
        ld a,(de)
        nop
        ld a,(de)
        nop
synced: call dly2
        ld hl,(entc)            ; 16 + 4, then 2 x kc NOPs
        jp (hl)
csled:  nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
cdone:  ld hl,(entf)            ; 16 + 4, then 16 + kf
        jp (hl)
doin:   in a,(c)                ; NR 22: bit 7 = pulse INT low
        ld hl,samples
        ld de,(kval)
        ld d,0
        add hl,de
        ld (hl),a
        ld hl,(entc2)           ; pad 63 - k more, so every pass reaches HALT at the same point: HALT's jitter
        jp (hl)                 ; is then the same on every pass
csled2: nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        ld hl,(entf2)
        jp (hl)
after2: ld b,20                 ; let frame N+1's INT pulse end before the next EI
sl2:    djnz sl2
        ld a,(kval)
        inc a
        ld (kval),a
        cp 64
        jr nz,sloop
        im 1                    ; put things back
        ld a,(sv03)
        and 0x70
        or 0x80                 ; timing as it was, type and lock untouched
        ld e,a
        ld a,0x03
        call nrwr
        ld a,(sv05)
        ld e,a
        ld a,0x05
        call nrwr
        ld a,(sv08)
        ld e,a
        ld a,0x08
        call nrwr
        ld a,(sv64)
        ld e,a
        ld a,0x64
        call nrwr
        call wait3              ; still at 3.5 MHz
        ld a,(sv07)
        and 0x03
        ld e,a
        ld a,0x07
        call nrwr
        call screen_init        ; the display again, in the old timing
        ld hl,s_title
        call pstr
        ld hl,s_res
        call pstr
        ld hl,samples           ; four rows of 16: 1 where bit 7 was set
        ld c,4
pr1:    ld a,13
        call pchr
        ld b,16
pr2:    ld a,(hl)
        rlca
        and 1
        add a,'0'
        call pchr
        inc hl
        djnz pr2
        dec c
        jr nz,pr1
        ld hl,s_flip            ; first 1, and the first 0 after it
        call pstr
        ld hl,samples
        ld b,0
fl1:    bit 7,(hl)
        jr nz,fl2
        inc hl
        inc b
        ld a,b
        cp 64
        jr nz,fl1
fl2:    push bc
        ld l,b
        ld h,0
        call pdec3
        ld hl,s_fall
        call pstr
        pop bc
        ld hl,samples
        ld e,b
        ld d,0
        add hl,de
fl3:    ld a,b
        cp 64
        jr z,fl4
        bit 7,(hl)
        jr z,fl4
        inc hl
        inc b
        jr fl3
fl4:    ld l,b
        ld h,0
        call pdec3
        ld hl,s_note
        call pstr
        ld a,(sv03)
        call phex8
        call pb_settle          ; ~3 s: HDMI back from the timing switch before the photo beep
        jp finish

; entc = csled + 14 - 2 * (k div 8); entf = fine[k mod 8]
entries:
        ld a,(kval)
        rrca
        rrca
        rrca
        and 7
        add a,a
        ld e,a
        ld d,0
        ld hl,csled+14
        or a
        sbc hl,de
        ld (entc),hl
        ld a,(kval)
        and 7
        add a,a
        ld e,a
        ld d,0
        ld hl,finetab
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld (entf),de
        ld a,(kval)             ; and for 63 - k
        cpl
        and 63
        ld c,a
        rrca
        rrca
        rrca
        and 7
        add a,a
        ld e,a
        ld d,0
        ld hl,csled2+14
        or a
        sbc hl,de
        ld (entc2),hl
        ld a,c
        and 7
        add a,a
        ld e,a
        ld d,0
        ld hl,finetab2
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld (entf2),de
        ret
finetab: dw f0,f1,f2,f3,f4,f5,f6,f7
finetab2: dw g0,g1,g2,g3,g4,g5,g6,g7
g0:     nop
        nop
        nop
        nop
        jp after2
g1:     nop
        inc hl
        ld a,0
        jp after2
g2:     inc hl
        inc hl
        inc hl
        jp after2
g3:     inc hl
        inc hl
        ld a,0
        jp after2
g4:     nop
        nop
        nop
        nop
        nop
        jp after2
g5:     ld a,0
        ld a,0
        ld a,0
        jp after2
g6:     nop
        nop
        ld a,0
        ld a,0
        jp after2
g7:     nop
        inc hl
        inc hl
        ld a,0
        jp after2
f0:     nop                     ; 16
        nop
        nop
        nop
        jp doin
f1:     nop                     ; 17
        inc hl
        ld a,0
        jp doin
f2:     inc hl                  ; 18
        inc hl
        inc hl
        jp doin
f3:     inc hl                  ; 19
        inc hl
        ld a,0
        jp doin
f4:     nop                     ; 20
        nop
        nop
        nop
        nop
        jp doin
f5:     ld a,0                  ; 21
        ld a,0
        ld a,0
        jp doin
f6:     nop                     ; 22
        nop
        ld a,0
        ld a,0
        jp doin
f7:     nop                     ; 23
        inc hl
        inc hl
        ld a,0
        jp doin

; exact delays: 26 x N + 32 T including the call (ld hl 10, loop 26 per pass but 21 the last, ret 10, call 17)
dly1:   ld hl,NDLY1
d1:     dec hl
        ld a,h
        or l
        jr nz,d1
        ret
dly2:   ld hl,NDLY2
d2:     dec hl
        ld a,h
        or l
        jr nz,d2
        ret

wait3:  ld hl,8100              ; about 3 frames (8100 x 26 T) at 3.5 MHz: the timing changes at a frame sync
w32:    dec hl
        ld a,h
        or l
        jr nz,w32
        ret

nrlist: ld a,(hl)               ; (register, value) pairs, FF ends
        cp 0xFF
        ret z
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr nrlist
setregs:
        db 0x07,0x00            ; 3.5 MHz
        db 0x64,0x00            ; no line offset
        db 0x22,0x00            ; ULA interrupt on, line interrupt off
        db 0xC0,0x00            ; pulse mode
        db 0xC5,0x00,0xC6,0x00  ; no CTC or UART interrupts
        db 0x03,0x90            ; 48K timing (type and lock untouched)
        db 0xFF

s_title: db "P-7 INT AGAINST THE BEAM (48K)",0
s_run:  db 22,2,0,"measuring: about 3 seconds",0
s_res:  db 22,2,0,"NR 22 bit 7 by k (padding 66+k)",0
s_flip: db 22,8,0,"first 1 at k=",0
s_fall: db 22,9,0,"first 0 after at k=",0
s_note: db 22,11,0,"Compare with Ratio's core: the"
        db 22,12,0,"same k means INT is placed"
        db 22,13,0,"right. Pulse: 32 T wide."
        db 22,15,0,"NR 03 was ",0
