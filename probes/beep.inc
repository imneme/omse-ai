; beep.inc: the photo beep, so a recording of a whole sitting can be cut into its photos by ear.
; Melissa O'Neill's idea, Tally Fern's spec (NOTES.md, "The photo beep"); this encoder by Hart's-tongue Fern, Fri 06 Nov 2026.
;
; Call photobeep once the result screen and its prompt are drawn, just before the key wait. It plays, on the
; beeper (port FE bit 4, MIC low, border kept):
;   SYNC 1800 Hz 200 ms, gap, TAPEID's tens, gap, TAPEID's units, gap, the photo number, gap, END 1800 Hz 100 ms
; with digit d as 600 + 100*d Hz for 120 ms and 50 ms gaps: about 0.86 s. The photo number counts 1, 2, 3 ... per
; run (mod 10). The tape defines TAPEID (0-99).
;
; Self-contained, so tapes that don't use probe.inc (Strobe Fern's z80ntime three) can include it too: its own
; nextreg access and variables. It saves every register, the interrupt state, NR 0x07 and the selected nextreg,
; and plays at 3.5 MHz. Each half-cycle of a tone is 68 + 26n T-states (pb_play's loop, counted below), so the
; table's frequencies are within 1% of the spec. Contention on port FE, if it's on at all, adds a few T a
; half-cycle: well inside the decoder's 5%. Every tone has an even number of half-cycles, so the speaker ends low.
;
; The border: pb_border, which probe.inc's screen_init and any tape that changes the border keep up to date.
; If nothing has set it (0xFF), BASIC's BORDCR is used.

PB_BORDCR equ 0x5C48

photobeep:
        push af
        push bc
        push de
        push hl
        ld a,i                  ; P/V = IFF2: were interrupts on?
        push af
        di
        ld bc,0x243B
        in a,(c)                ; the selected nextreg, to put back
        ld (pb_sel),a
        ld a,0x07               ; NR 0x07: save the speed, play at 3.5 MHz
        out (c),a
        inc b
        in a,(c)
        and 0x03
        ld (pb_s07),a
        xor a
        out (c),a
        ld a,(pb_border)
        cp 0xFF
        jr nz,pb_b1
        ld a,(PB_BORDCR)
        rrca
        rrca
        rrca
pb_b1:  and 0x07
        ld (pb_bord),a
        ld a,(pb_photo)
        inc a
        ld (pb_photo),a

        ld a,10                 ; SYNC
        call pb_play
        call pb_gap
        ld a,TAPEID/10
        call pb_play
        call pb_gap
        ld a,TAPEID-(TAPEID/10)*10
        call pb_play
        call pb_gap
        ld a,(pb_photo)
pb_m1:  cp 10
        jr c,pb_m2
        sub 10
        jr pb_m1
pb_m2:  call pb_play
        call pb_gap
        ld a,11                 ; END
        call pb_play

        ld bc,0x243B            ; NR 0x07 and the selection back
        ld a,0x07
        out (c),a
        inc b
        ld a,(pb_s07)
        out (c),a
        dec b
        ld a,(pb_sel)
        out (c),a
        pop af
        jp po,pb_x              ; interrupts were off
        ei
pb_x:   pop hl
        pop de
        pop bc
        pop af
        ret

; Tone A (0-9 digits, 10 SYNC, 11 END) from pb_table. A half-cycle is, in T-states:
; ld a,h 4, xor 7, ld h,a 4, out 11, push bc 11, the inner loop 26n - 5, pop bc 10, dec de 6, ld a,d 4,
; or e 4, jr nz 12: 68 + 26n.
pb_play:
        add a,a
        add a,a
        ld e,a
        ld d,0
        ld hl,pb_table
        add hl,de
        ld c,(hl)
        inc hl
        ld b,(hl)
        inc hl
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld a,(pb_bord)
        ld h,a
pb_t1:  ld a,h
        xor 0x10
        ld h,a
        out (0xFE),a
        push bc
pb_t2:  dec bc
        ld a,b
        or c
        jr nz,pb_t2
        pop bc
        dec de
        ld a,d
        or e
        jr nz,pb_t1
        ret

pb_gap: ld bc,6731              ; 50 ms of silence: 6731 x 26 T at 3.5 MHz
pb_g1:  dec bc
        ld a,b
        or c
        jr nz,pb_g1
        ret

; pb_settle: about three seconds, so HDMI is back (with its audio) before the photo beep, in a tape that has just put
; a video timing or refresh rate back (P7, PSS photo 1): a timing change resets the HDMI encoder (zxnext.vhd:1621) and
; the capture box needs a moment to lock again. Plays nothing; at 3.5 MHz whatever the tape's speed (NR 0x07 and the
; selected nextreg saved and put back), so it lasts the same everywhere: 150 x 2692 x 26 T = 10.50 M T = 3.0 s.
pb_settle:
        push af
        push bc
        push de
        ld bc,0x243B
        in a,(c)
        ld (pb_sel),a
        ld a,0x07
        out (c),a
        inc b
        in a,(c)
        and 0x03
        ld (pb_s07),a
        xor a
        out (c),a
        ld d,150
pb_s1:  ld bc,2692              ; 2692 x 26 T = 69,992 T, about a frame
pb_s2:  dec bc
        ld a,b
        or c
        jr nz,pb_s2
        dec d
        jr nz,pb_s1
        ld bc,0x243B
        ld a,0x07
        out (c),a
        inc b
        ld a,(pb_s07)
        out (c),a
        dec b
        ld a,(pb_sel)
        out (c),a
        pop de
        pop bc
        pop af
        ret

pb_table:                       ; n (inner count), half-cycles; frequency and length at 3.5 MHz
        dw 110,144              ; digit 0   600 Hz:  597.7 Hz, 120.5 ms
        dw  94,168              ; digit 1   700 Hz:  696.7 Hz, 120.6 ms
        dw  82,192              ; digit 2   800 Hz:  795.5 Hz, 120.7 ms
        dw  72,216              ; digit 3   900 Hz:  902.1 Hz, 119.7 ms
        dw  65,240              ; digit 4  1000 Hz:  995.4 Hz, 120.5 ms
        dw  59,262              ; digit 5  1100 Hz: 1092.4 Hz, 119.9 ms
        dw  53,290              ; digit 6  1200 Hz: 1210.2 Hz, 119.8 ms
        dw  49,314              ; digit 7  1300 Hz: 1304.0 Hz, 120.4 ms
        dw  45,340              ; digit 8  1400 Hz: 1413.6 Hz, 120.3 ms
        dw  42,362              ; digit 9  1500 Hz: 1508.6 Hz, 120.0 ms
        dw  35,716              ; SYNC     1800 Hz: 1789.4 Hz, 200.1 ms
        dw  35,358              ; END      1800 Hz: 1789.4 Hz, 100.0 ms

pb_photo:  db 0                 ; photos so far this run
pb_border: db 0xFF              ; the border colour, or FF for "use BORDCR"
pb_bord:   db 0
pb_s07:    db 0
pb_sel:    db 0
