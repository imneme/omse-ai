; P-20 THE zxnDMA. What core 3.02.02's dma.vhd predicts, measured by time with the CTC as a stopwatch (a tick is 16
; cycles of the 28 MHz clock, at any CPU speed: P-6's stopwatch). Each figure is the difference of two transfer
; lengths, so the programming and the bus hand-over cancel. Kelp Fern, Fri 06 Nov 2026; the probe ideas for the
; prescaler, CB, port 0x0B, length 0 and timing 11 are Rustyback's and Loam Fern's (Rustyback Fern's second-sources reading).
;   SPI   port 0xEB -> memory, 128 bytes more, every SPI device DESELECTED (port 0xE7 = FF; nothing on the SD
;         card or the flash is touched). A held strobe begins a second transfer at state 15 (spi:82, dma:146-155):
;         34 clocks a byte, 2176 ticks. One transfer a byte (3.02.05's spi_active) would be 1344; no wait, 384.
;   P55   prescaler 55, 256 bytes more, at 3.5 and at 28 MHz: 32P t28 + 3 CPU clocks a byte (dma:309, 424, 457):
;         28544 and 28208 ticks. The wiki's 875 kHz / P, the same at every speed: 28160.
;   CB    prescaler 255, then WR6 CB (reset port B timing), 8 bytes more: CB keeps the prescaler (dma:647-651):
;         4092. The wiki (CB resets it too): 24.
;   0B    the same programmed through port 0x0B (Z80-DMA mode), no CB: the prescaler still works: 4092.
;   STAT  after a finished 512-byte transfer, status and counter: 1A 00 02 (IDLE clears T, dma:265; the wiki 1B).
;   LEN0  a zxnDMA transfer of length 0 copies 1 byte (the test comes after the byte, dma:426; the wiki 0).
;   T11   timing byte 11 against 00, 256 bytes each: the same (dma:312-324: 11 is 4 clocks).
;   LOCK  last: WR4 = 91h, then C3 and a 16-byte copy: 00 copied, the write sequencer stuck in R4_BYTE_2
;         (dma:607-608, 891) until the reset `finish` does.
; Port enables NR 0x82 b5 (0x6B), NR 0x85 b1 (0x0B) and b3 (the CTC) are turned on for the run and put back.
; 3.5 MHz unless said.
TAPEID  equ 20                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

DMA     equ 0x6B
ZDMA    equ 0x0B
SRC     equ 0x9000
DST     equ 0x9800
rslt    equ VARS+0x10           ; 12 words, in the order of the tables below
w0      equ VARS+0x30
nr07    equ VARS+0x32
nr82    equ VARS+0x33
nr85    equ VARS+0x34
stat    equ VARS+0x35           ; 3 bytes
cnt0    equ VARS+0x38
cntl    equ VARS+0x39

main:   ld a,0x07
        call nrrd
        ld (nr07),a
        ld a,0x82
        call nrrd
        ld (nr82),a
        ld a,0x85
        call nrrd
        ld (nr85),a
        call screen_init
        ld hl,s_title
        call pstr
        ld hl,s_wait
        call pstr
        ld a,(nr82)             ; the DMA's ports on
        or 0x20
        ld e,a
        ld a,0x82
        call nrwr
        ld a,(nr85)
        or 0x0A                 ; 0x0B, and the CTC (bit 27) for the stopwatch
        ld e,a
        ld a,0x85
        call nrwr
        call speed0
        ld a,0xFF               ; deselect every SPI device
        out (0xE7),a
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
        ld ix,rslt
        ld hl,t_spi128
        call mstore
        ld hl,t_spi256
        call mstore
        ld hl,t_p55a
        call mstore
        ld hl,t_p55b
        call mstore
        ld a,0xBB               ; STAT: mask = status, counter lo, counter hi (BB's mask restarts the sequence)
        out (DMA),a
        ld a,0x07
        out (DMA),a
        in a,(DMA)
        ld (stat),a
        in a,(DMA)
        ld (stat+1),a
        in a,(DMA)
        ld (stat+2),a
        ld e,3                  ; 28 MHz
        ld a,0x07
        call nrwr
        ld b,0
sp28:   djnz sp28
        ld hl,t_p55a
        call mstore
        ld hl,t_p55b
        call mstore
        call speed0
        ld hl,t_cb8
        call mstore
        ld hl,t_cb16
        call mstore
        ld hl,t_z8
        call mstore
        ld hl,t_z16
        call mstore
        ld hl,t_t11
        call mstore
        ld hl,t_t00
        call mstore
        call setbuf             ; LEN0
        ld hl,t_len0
        call dmatab
        call count
        ld (cnt0),a
        call setbuf             ; LOCK
        ld a,0x91
        out (DMA),a
        ld hl,t_copy16
        call dmatab
        ld b,0
lk1:    djnz lk1
        call count
        ld (cntl),a
        ld a,(nr82)             ; put the ports back
        ld e,a
        ld a,0x82
        call nrwr
        ld a,(nr85)
        ld e,a
        ld a,0x85
        call nrwr
        ld a,(nr07)
        and 3
        ld e,a
        ld a,0x07
        call nrwr
        call ctcstop
        ld hl,s_rows            ; the results
        call pstr
        ld hl,(rslt+2)           ; SPI: 256 - 128
        ld de,(rslt+0)
        ld a,2
        call pdiff
        ld hl,(rslt+6)           ; P55 at 3.5 MHz
        ld de,(rslt+4)
        ld a,4
        call pdiff
        ld hl,(rslt+10)          ; P55 at 28 MHz
        ld de,(rslt+8)
        ld a,5
        call pdiff
        ld hl,(rslt+14)          ; CB
        ld de,(rslt+12)
        ld a,7
        call pdiff
        ld hl,(rslt+18)          ; port 0x0B
        ld de,(rslt+16)
        ld a,8
        call pdiff
        ld a,9                  ; T11 and T00, raw
        call at10
        ld hl,(rslt+20)
        call pdec5
        call pspace
        ld hl,(rslt+22)
        call pdec5
        ld a,10                 ; STAT
        call at10
        ld a,(stat)
        call phex8
        call pspace
        ld a,(stat+1)
        call phex8
        call pspace
        ld a,(stat+2)
        call phex8
        ld a,11                 ; LEN0 and LOCK
        call at10
        ld a,(cnt0)
        call phex8
        ld a,12
        call at10
        ld a,(cntl)
        call phex8
        jp finish

speed0: ld e,0
        ld a,0x07
        call nrwr
        ld b,0
s01:    djnz s01
        ret

; Print HL - DE (5 digits) at row A, column 10
pdiff:  call at10
        or a
        sbc hl,de
        jp pdec5

; The print position to row A, column 9
at10:   ld (prow),a
        ld a,9
        ld (pcol),a
        ret

; Measure the table at HL; ticks to (IX), IX += 2
mstore: push hl
        call swread
        ld (w0),hl
        pop hl
        call dmatab
        call swread
        ex de,hl
        ld hl,(w0)
        or a
        sbc hl,de               ; the counters count down
        ld (ix+0),l
        ld (ix+1),h
        inc ix
        inc ix
        ret

; A table: port, count, bytes. OTIR them (the last is the enable, 87h); a continuous transfer runs to its end
; before the CPU's next M-cycle after that.
dmatab: ld c,(hl)
        inc hl
        ld b,(hl)
        inc hl
        otir
        ret

; SRC = 1..16, DST = 16 zeros
setbuf: ld hl,SRC
        ld b,16
        ld a,1
sb1:    ld (hl),a
        inc hl
        inc a
        djnz sb1
        ld hl,DST
        ld b,16
sb2:    ld (hl),0
        inc hl
        djnz sb2
        ret

; A = how many of DST's 16 bytes are non-zero
count:  ld hl,DST
        ld b,16
        ld c,0
cn1:    ld a,(hl)
        or a
        jr z,cn2
        inc c
cn2:    inc hl
        djnz cn1
        ld a,c
        ret

; P-6's stopwatch (Hart's-tongue Fern): HL = channel 1 : (channel 0 - 1), read consistently
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

pdec5:  ld bc,10000
        call pdd
        ld bc,1000
        call pdd
        jp pdec3

; ---- the transfers: port, count, then C3 (reset), WR0, WR1, WR2, WR4, [CB], CF (load), 87 (enable) ----
; WR0 79/7D: B->A / A->B, A's start and the length follow. WR1 14: A memory, increment; 54 with a timing byte.
; WR2 10: B memory, increment; 28: B I/O, fixed; 50 with a timing byte (21: 3 clocks, prescaler follows).
; WR4 AD: continuous, B's start follows.
t_spi128: db DMA,13, 0xC3, 0x79,DST AND 0xFF,DST SHR 8,128,0, 0x14, 0x28, 0xAD,0xEB,0x00, 0xCF, 0x87
t_spi256: db DMA,13, 0xC3, 0x79,DST AND 0xFF,DST SHR 8,0,1, 0x14, 0x28, 0xAD,0xEB,0x00, 0xCF, 0x87
t_p55a:   db DMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,0,1, 0x14, 0x50,0x21,55, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_p55b:   db DMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,0,2, 0x14, 0x50,0x21,55, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_cb8:    db DMA,16, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,8,0, 0x14, 0x50,0x21,255, 0xAD,DST AND 0xFF,DST SHR 8, 0xCB, 0xCF, 0x87
t_cb16:   db DMA,16, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,16,0, 0x14, 0x50,0x21,255, 0xAD,DST AND 0xFF,DST SHR 8, 0xCB, 0xCF, 0x87
t_z8:     db ZDMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,8,0, 0x14, 0x50,0x21,255, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_z16:    db ZDMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,16,0, 0x14, 0x50,0x21,255, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_t11:    db DMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,0,1, 0x54,0x03, 0x50,0x03, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_t00:    db DMA,15, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,0,1, 0x54,0x00, 0x50,0x00, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_len0:   db DMA,13, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,0,0, 0x14, 0x10, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87
t_copy16: db DMA,13, 0xC3, 0x7D,SRC AND 0xFF,SRC SHR 8,16,0, 0x14, 0x10, 0xAD,DST AND 0xFF,DST SHR 8, 0xCF, 0x87

s_title: db "P-20 THE zxnDMA, CORE 3.02.02",0
s_wait:  db 22,2,0,"timing...",0
s_rows:  db 22,1,0,"CTC ticks; VHDL's in brackets"
         db 22,2,0,"SPI EB         (02176)"
         db 22,3,0," one xfer/byte 01344 none 00384"
         db 22,4,0,"P55 3.5        (28544) wiki"
         db 22,5,0,"P55 28         (28208) 28160"
         db 22,7,0,"P255 CB        (04092) wiki 24"
         db 22,8,0,"P255 0B        (04092)"
         db 22,9,0,"T11 T00              (equal)"
         db 22,10,0,"STAT              (1A 00 02)"
         db 22,11,0,"LEN0        (01) wiki 00"
         db 22,12,0,"LOCK 91     (00) else 10"
         db 22,14,0,"SPI: no device selected; the"
         db 22,15,0,"card and flash are untouched.",0
