; PFB: the floating bus against contention (48K timing, 3.5 MHz). Speccy-Zone Fern, Sat 07 Nov 2026.
;
; PBD's D-12 read port 0x40FF 30000 times at 48K timing: 4929 not FF, 2066 of them the screen's attribute 38. NR 0x08
; was DE there, so contention was off (bit 6, zxnext:5115, 4422): NextZXOS turns it off while it runs and back on
; only for the Tape Loader and snapshots (nextzxos-changelog.txt:1639, 2049). This runs the same loop three ways:
;   F-1  contention off, as D-12: the control.
;   F-2  contention on. Port 0x40FF is in bank 5's page, so every T-state of the IN's I/O cycle can be held
;        (zxnext:4430; zxula:582-595). The T80N takes the byte at CLK_n's falling edge in TState 3, the I/O cycle's
;        fourth T-state (t80na:214-221; t80n:1781-1783). After a hold that lands in slot 2 (FFh) unless the cycle
;        began in slot 1 (an attribute), so far fewer reads float, nearly all of them 38. A model that takes the
;        byte at the IORQ edge, as omse-ai did, floats more than twice as many.
;   F-3  as F-2 with a NOP in the loop, so the reads meet the holds at other phases.
; Expectations, from omse-ai's Next running this tape, in NOTES.md under "PFB". One photo.
; Everything is put back: NR 0x03 timing, 0x07, 0x08. Interrupts stay off.

TAPEID  equ 74                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

V       equ VARS+0x20
s03     equ V+0
s07     equ V+1
s08     equ V+2
rfl     equ V+4                 ; 3 x (not FF, equal to 38): 6 words

main:   ld a,0x03
        call nrrd
        ld (s03),a
        ld a,0x07
        call nrrd
        ld (s07),a
        ld a,0x08
        call nrrd
        ld (s08),a
        call screen_init        ; bitmap 0, attributes 38 (probe.inc)
        ld hl,s_testing
        call pstr
        ld a,0x07               ; 3.5 MHz for everything that follows
        ld e,0
        call nrwr
        ld e,0x90               ; 48K timing
        ld a,0x03
        call nrwr
        ld a,(s08)              ; F-1: port FF reads the ULA (b2 clear), contention off (b6 set)
        and 0xFB
        or 0x40
        call setnr8
        ld hl,fbs
        call runf
        ld (rfl),hl
        ld (rfl+2),ix
        ld a,(s08)              ; F-2: contention on (b6 clear)
        and 0xBB
        call setnr8
        ld hl,fbs
        call runf
        ld (rfl+4),hl
        ld (rfl+6),ix
        ld hl,fbsn              ; F-3: the same, with a NOP in the loop
        call runf
        ld (rfl+8),hl
        ld (rfl+10),ix
        ld a,(s03)              ; timing as it was
        and 0x70
        or 0x80
        ld e,a
        ld a,0x03
        call nrwr
        call wait2
        ld a,(s08)
        ld e,a
        ld a,0x08
        call nrwr
        ld a,(s07)
        and 3
        ld e,a
        ld a,0x07
        call nrwr
        call results
        ld hl,s_finish
        call pstr
        call pb_settle          ; ~3 s: HDMI back from the 48K timing switch before the photo beep
        call photokey
        call softreset
        jp back

setnr8: ld e,a                  ; NR 0x08 = A, then two frames: it takes effect in a line's right half (zxnext:5729)
        ld a,0x08
        call nrwr
        jp wait2

runf:   ld bc,0x40FF            ; HL = routine: 30000 reads of port BC, HL = not FF, IX = equal to 38
        jp (hl)

fbs:    ld hl,0                 ; PBD's loop, read for read
        ld ix,0
        ld de,30000
fs1:    in a,(c)
        cp 0xFF
        jr z,fs2
        inc hl
        cp 0x38
        jr nz,fs2
        inc ix
fs2:    dec de
        ld a,d
        or e
        jr nz,fs1
        ret

fbsn:   ld hl,0                 ; the same with a NOP: 4 T more a read
        ld ix,0
        ld de,30000
fn1:    in a,(c)
        nop
        cp 0xFF
        jr z,fn2
        inc hl
        cp 0x38
        jr nz,fn2
        inc ix
fn2:    dec de
        ld a,d
        or e
        jr nz,fn1
        ret

rdline: push bc                 ; HL = NR 0x1E/0x1F, the line counter (PBD's)
        ld bc,NRSEL
        ld a,0x1E
        out (c),a
        ld bc,NRDAT
        in h,(c)
        ld bc,NRSEL
        ld a,0x1F
        out (c),a
        ld bc,NRDAT
        in l,(c)
        pop bc
        ret

wait2:  call waitf
waitf:  push de                 ; to line 10, then past it (gives up after 65536 reads: not a Next)
        ld de,0
wf1:    call rdline
        ld a,h
        or a
        jr nz,wf2
        ld a,l
        cp 10
        jr z,wf3
wf2:    dec de
        ld a,d
        or e
        jr nz,wf1
        pop de
        ret
wf3:    call rdline
        ld a,h
        or a
        jr nz,wf4
        ld a,l
        cp 10
        jr nz,wf4
        dec de
        ld a,d
        or e
        jr nz,wf3
wf4:    pop de
        ret

results:
        call screen_init
        ld hl,s_res
        call pstr
        ld a,(s08)
        call phex8
        ld hl,rfl
        ld de,s_rows
        ld b,3
rs1:    push bc
        ex de,hl
        call pstr               ; the row's label
        ex de,hl
        ld a,(hl)
        inc hl
        push hl
        ld h,(hl)
        ld l,a
        call pdec5
        pop hl
        inc hl
        push de
        ld de,s_eq38
        ex de,hl
        call pstr
        ex de,hl
        pop de
        ld a,(hl)
        inc hl
        push hl
        ld h,(hl)
        ld l,a
        call pdec5
        pop hl
        inc hl
        pop bc
        djnz rs1
        ret

pdec5:  push bc                 ; HL as five decimal digits
        ld bc,10000
        call pdd
        ld bc,1000
        call pdd
        call pdec3
        pop bc
        ret

s_testing:
        db 22,2,0,"Testing (about 3 s). The screen",13
        db "may go dark for a moment.",0
s_res:  db 22,0,0,"PFB  floating bus, 3.02.02",13
        db "48K timing, 30000 reads of 40FF",13
        db "NR 08 was ",0
s_rows: db 22,4,0,"F-1 off  not FF ",0
        db 22,6,0,"F-2 on   not FF ",0
        db 22,8,0,"F-3 +NOP not FF ",0
s_eq38: db " =38 ",0
