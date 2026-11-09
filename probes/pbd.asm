; PBD: "bus and D-rows". Rustyback Fern's expansion-bus probes (Rustyback Fern's bus-pin reading, P-BUS-1, 3, 4: the bus on with
; nothing attached), and two of NEXT-MACHINE.md §9's open rows, D-3 and D-12. Hart's-tongue Fern, Fri 06 Nov 2026.
; Expectations, with the VHDL lines, in NOTES.md under "PBD". One photo.
;
;   D-3     NR 0x22 bit 7 is the pulse-mode INT itself, from any enabled source, and never for a disabled one
;           (zxnext:5899; zxula_timing:551, 577). nextreg.txt: "ula is asserting an interrupt (even if disabled)".
;   D-12    only port 0xFF floats (the ULA's fetch, at 48K/128K timing, with NR 0x08 bit 2 clear); an odd port
;           nothing decodes reads FF (zxnext:1836, 2772, 4454). A real 48K floats any unattached port.
;   BUS-1   NR 0x81 reads 00 with the bus off and on (/ROMCS's pull-down, zxnext:6033); NR 0x07 = 3 reads 03 with
;           the bus on (speed pinned to 00, zxnext:5719-5723) and 33 with it off.
;   BUS-3   undecoded ports read FF with the bus on too (the connector's pull-ups, zxnext:1833-1836).
;   BUS-4   timed loops (NOP, IN, LD A,(HL)) take the same with the bus off and on: no stray waits.
;
; The bus: NEXTREG 0x80 = 0x80 turns it on at once (zxnext:2146) with memory and I/O cycles enabled; bits 3:0 are 0,
; so the closing soft reset leaves it off whatever happens (zxnext:2144-2145). While it's on, this code touches
; neither the ROM area nor port FE, and interrupts stay off. P-BUS-2 (interrupt release to a quarter T) is left for
; a tape of its own.

TAPEID  equ 70                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

V       equ VARS+0x20
s03     equ V+0
s07     equ V+1
s08     equ V+2
s22     equ V+3
s23     equ V+4
s80     equ V+5
s81     equ V+6
s85     equ V+7
rd3     equ V+8                 ; 3 words: hits for ULA off/line off, ULA on, line on
rfb     equ V+14                ; 2 words: non-FF reads of 40FF, 40F7
rfb38   equ V+18                ; 2 words: reads of 38 (the screen's attribute) from 40FF, 40F7
rb81    equ V+22                ; 2 bytes: NR 0x81 bus off, on
rb07    equ V+24                ; 2 bytes: NR 0x07 (3 written) bus on, off
rb3     equ V+26                ; 4 bytes: 40F7, 40DB bus on; 40F7, 40DB bus off
rb4     equ V+30                ; 6 words: NOP, IN, LD bus off; NOP, IN, LD bus on
w0      equ V+42
tptr    equ V+44
mrout   equ V+46
mbest   equ V+48

main:
        ld hl,savelist
sv1:    ld a,(hl)
        cp 0xFF
        jr z,sv2
        inc hl
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        call nrrd
        ld (de),a
        jr sv1
sv2:    call screen_init
        ld hl,s_testing
        call pstr
        ld a,0x07               ; 3.5 MHz for everything that follows
        ld e,0
        call nrwr
        call d3
        call d12
        call bus
        ld a,(s07)              ; the speed as it was
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

savelist:
        db 0x03
        dw s03
        db 0x07
        dw s07
        db 0x08
        dw s08
        db 0x22
        dw s22
        db 0x23
        dw s23
        db 0x80
        dw s80
        db 0x81
        dw s81
        db 0x85
        dw s85
        db 0xFF

; ---- helpers ----

rdline: push bc                 ; HL = NR 0x1E/0x1F, the line counter
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

wait2:  call waitf
        jp waitf

; ---- D-3: count samples of NR 0x22 bit 7 over four frames ----
; The sampler is built in SLED: 128 x (IN (C), CALL M,d3hit), then RET. IN (C) (ED 70) reads NR 0x22 through port
; 0x253B and sets S from bit 7; a sample every 22 T, so the 32-T pulse (36 at 128K timing) can't slip between two.
; The only gap is at the block's end (about 74 T, once per 2816 T).

d3:     ld hl,SLED
        ld b,128
mb1:    ld (hl),0xED            ; IN (C)
        inc hl
        ld (hl),0x70
        inc hl
        ld (hl),0xFC            ; CALL M,d3hit
        inc hl
        ld de,d3hit
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        djnz mb1
        ld (hl),0xC9
        ld a,0x23               ; line interrupt at line 100 (case 3)
        ld e,100
        call nrwr
        ld e,0x04               ; ULA off, line off
        call d3case
        ld (rd3),hl
        ld e,0x00               ; ULA on, line off
        call d3case
        ld (rd3+2),hl
        ld e,0x06               ; ULA off, line on
        call d3case
        ld (rd3+4),hl
        ld a,(s23)
        ld e,a
        ld a,0x23
        call nrwr
        ld a,(s22)
        and 0x07
        ld e,a
        ld a,0x22
        jp nrwr

d3case: ld a,0x22
        call nrwr
        call waitf
        ld bc,NRSEL
        ld a,0x22
        out (c),a
        ld bc,NRDAT
        ld hl,0
        ld de,101               ; 101 x 2816 T, four frames at 3.5 MHz
d3l:    push de
        call SLED
        pop de
        dec de
        ld a,d
        or e
        jr nz,d3l
        ret
d3hit:  inc hl
        ret

; ---- D-12: the floating bus at 48K timing ----

d12:    ld a,(s08)              ; port FF reads the ULA, not the Timex register
        and 0xFB
        ld e,a
        ld a,0x08
        call nrwr
        ld e,0x90               ; 48K timing
        ld a,0x03
        call nrwr
        call wait2
        ld bc,0x40FF
        call fbs
        ld (rfb),hl
        ld (rfb38),ix
        ld bc,0x40F7
        call fbs
        ld (rfb+2),hl
        ld (rfb38+2),ix
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
        jp nrwr

fbs:    ld hl,0                 ; 30000 reads of port BC: HL = not FF, IX = equal to 38
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

; ---- the bus, nothing attached ----

bus:    call ctcstop            ; the stopwatch (P-6's): channel 1 counts channel 0's turns, 16 x 28 MHz a tick
        ld bc,0x193B
        ld a,0x47
        out (c),a
        xor a
        out (c),a
        ld bc,0x183B
        ld a,0x07
        out (c),a
        xor a
        out (c),a
        ld a,0x81               ; BUS-1, bus off
        call nrrd
        ld (rb81),a
        ld hl,rb4
        ld (tptr),hl
        ld bc,0x40F7            ; BUS-3, bus off
        in a,(c)
        ld (rb3+2),a
        ld bc,0x40DB
        in a,(c)
        ld (rb3+3),a
        call timeall            ; BUS-4, bus off

        ld a,0x80               ; the bus on
        ld e,0x80
        call nrwr
        ld a,0x81
        call nrrd
        ld (rb81+1),a
        ld bc,0x40F7
        in a,(c)
        ld (rb3),a
        ld bc,0x40DB
        in a,(c)
        ld (rb3+1),a
        call timeall            ; BUS-4, bus on
        ld a,0x07               ; 28 MHz asked for, with the bus on
        ld e,3
        call nrwr
        ld a,0x07
        call nrrd
        ld (rb07),a
        ld a,(s80)              ; the bus off again
        ld e,a
        ld a,0x80
        call nrwr
        ld b,0
bw1:    djnz bw1
        ld a,0x07
        call nrrd
        ld (rb07+1),a
        ld a,0x07
        ld e,0
        call nrwr
        jp ctcstop

timeall:
        ld de,tnop
        call measmin
        call tstore
        ld de,tin
        call measmin
        call tstore
        ld de,tld
        call measmin
tstore: ex de,hl
        ld hl,(tptr)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld (tptr),hl
        ret

; HL = the least of three measurements of the routine at DE. swread retries when channel 1 moves between its two
; reads, and a retry lands inside the measured time, so a single measurement can come out 30-60 ticks long (omse-ai
; showed one: NOP 5933 against 5876); a retry can only add, so the minimum is the loop's own time.
measmin:
        ld (mrout),de
        call measure
        ld (mbest),hl
        ld b,2
mm1:    push bc
        ld de,(mrout)
        call measure
        ld de,(mbest)
        or a
        sbc hl,de               ; this one less than the best so far?
        jr nc,mm2
        add hl,de
        ld (mbest),hl
mm2:    pop bc
        djnz mm1
        ld hl,(mbest)
        ret

measure:                        ; HL = ticks taken by the routine at DE
        push de
        call swread
        ld (w0),hl
        pop de
        call jpde
        call swread
        ex de,hl
        ld hl,(w0)
        or a
        sbc hl,de
        ret
jpde:   push de
        ret

tnop:   ld b,0                  ; 256 x (8 NOP + DJNZ) = 11520 T
tn1:    nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        djnz tn1
        ret
tin:    ld b,0                  ; 256 x (4 x (LD A,40; IN A,(F7)) + DJNZ) = 21760 T
ti1:    ld a,0x40
        in a,(0xF7)
        ld a,0x40
        in a,(0xF7)
        ld a,0x40
        in a,(0xF7)
        ld a,0x40
        in a,(0xF7)
        djnz ti1
        ret
tld:    ld hl,0x8000            ; 256 x (8 LD A,(HL) + DJNZ) = 17664 T
        ld b,0
tl1:    ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        ld a,(hl)
        djnz tl1
        ret

swread: ld bc,0x183B            ; channel 1 : (channel 0 - 1), read consistently (P-6)
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
        cp 4
        jr nz,cs1
        ret

; ---- the photo ----

results:
        call screen_init
        ld hl,s_res
        call pstr
        ld hl,ctx
        ld b,8
rs1:    ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld a,(de)
        call phex8
        call pspace
        djnz rs1
        ld hl,s_d3a
        call pstr
        ld hl,(rd3)
        call pdec5
        ld hl,s_d3b
        call pstr
        ld hl,(rd3+2)
        call pdec5
        ld hl,s_d3c
        call pstr
        ld hl,(rd3+4)
        call pdec5
        ld hl,s_d12a
        call pstr
        ld hl,(rfb)
        call pdec5
        ld hl,s_eq38
        call pstr
        ld hl,(rfb38)
        call pdec5
        ld hl,s_d12b
        call pstr
        ld hl,(rfb+2)
        call pdec5
        ld hl,s_b1
        call pstr
        ld hl,rb81
        ld b,2
        call phexn
        ld hl,s_b1b
        call pstr
        ld hl,rb07
        ld b,2
        call phexn
        ld hl,s_b3
        call pstr
        ld hl,rb3
        ld b,4
        call phexn
        ld hl,s_b4
        call pstr
        ld hl,rb4
        ld de,rb4+6
        ld b,3
rs2:    push bc
        push de
        call pspace
        ld a,(hl)
        inc hl
        push hl
        ld h,(hl)
        ld l,a
        call pdec5
        pop hl
        inc hl
        pop de
        push hl
        ex de,hl
        ld a,'/'
        call pchr
        ld a,(hl)
        inc hl
        push hl
        ld h,(hl)
        ld l,a
        call pdec5
        pop hl
        inc hl
        ex de,hl
        pop hl
        pop bc
        djnz rs2
        ld hl,s_want
        jp pstr

phexn:  call pspace
        ld a,(hl)
        inc hl
        call phex8
        djnz phexn
        ret

pdec5:  push bc                 ; HL as five decimal digits
        ld bc,10000
        call pdd
        ld bc,1000
        call pdd
        call pdec3
        pop bc
        ret

ctx:    dw s80,s81,s07,s08,s22,s03,s85,s23

s_testing:
        db 22,2,0,"Testing (about 3 s). The screen",13
        db "may go dark for a moment.",0
s_res:  db 22,0,0,"PBD  bus and D-rows, 3.02.02",13
        db "NR 80 81 07 08 22 03 85 23",13,"   ",0
s_d3a:  db 22,3,0,"#D-3 NR22 b7 samples, 4 frames:",13
        db " ULA off,line off ",0
s_d3b:  db 22,5,0," ULA on ",0
s_d3c:  db "  line only ",0
s_d12a: db 22,7,0,"#D-12 48K timing, 30000 reads",13
        db " 40FF not FF ",0
s_eq38: db " =38 ",0
s_d12b: db 22,9,0," 40F7 not FF ",0
s_b1:   db 22,11,0,"BUS-1 NR81 off/on:",0
s_b1b:  db 22,12,0,"      NR07=3 on/off:",0
s_b3:   db 22,14,0,"BUS-3 F7 DB on, off:",0
s_b4:   db 22,16,0,"BUS-4 ticks off/on, NOP IN LD:",13,0
s_want: db 22,4,24,"(0)"
        db 22,6,0,"  VHDL >0, >0  nr.txt >0,0"
        db 22,10,0,"  VHDL 40FF >0, 40F7 00000"
        db 22,13,0,"  VHDL 00 00, 03 33"
        db 22,15,0,"  VHDL FF FF FF FF"
        db 22,20,0,"  VHDL each pair equal",0
