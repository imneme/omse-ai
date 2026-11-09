; PNM: the NMI flags in NR 0x02, and the copper clearing them. NEXT-MACHINE.md §9 D-8 and D-7, as a careful tape
; with Melissa O'Neill's go-ahead (a hang is fine; nothing that can harm the machine or the card). Hart's-tongue Fern,
; Fri 06 Nov 2026. Expectations with the VHDL lines in NOTES.md under "PNM". Checked against Rustyback Fern's
; TAPE-REVIEW-CHECKLIST.md: no port with low byte E7 or EB except one OUT of FF to E7 (deselect all), no NR 0x10, no
; reset bits, NR 0x02 bit 7 always written 0, the copper's one MOVE is to register 0x02 with value 0x00.
;
;   D-8  NR 0x02 bits 3/2 set the multiface/divMMC NMI flag on any write while the NMI machine is idle
;        (zxnext:3784-3803), but the NMI itself fires only if NR 0x06 bit 3/4 enables it (zxnext:2049-2050).
;        nextreg.txt gives no condition. So with NR 0x06's enables off: flag set, no NMI, NR 0xC2/0xC3 (the NMI
;        return address, written only on an NMI acknowledge, zxnext:2019-2022) unchanged.
;   D-7  nextreg.txt: "Copper cannot clear these bits". The copper's writes take the same path (zxnext:4672-4676,
;        4779), so a copper MOVE of 0x00 to NR 0x02 clears the flag (zxnext:3788, 3801).
;
; Order matters: the enables go off first, the flags are cleared (by the copper, then by the CPU to be sure) before
; NR 0x06 is put back, so no pending flag can meet a restored enable.

TAPEID  equ 71                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

V       equ VARS+0x20
s06     equ V+0
sc2     equ V+1
sc3     equ V+2
s62     equ V+3
s02     equ V+4
rbuf    equ V+5                 ; MF: NR02, C2, C3, NR02 after the copper; DIV: the same four
rok     equ V+13                ; 0 = ran, 1 = copper busy, skipped

main:   ld a,0xFF               ; every SPI device deselected (the one E7 write)
        out (0xE7),a
        ld a,0x06
        call nrrd
        ld (s06),a
        ld a,0xC2
        call nrrd
        ld (sc2),a
        ld a,0xC3
        call nrrd
        ld (sc3),a
        ld a,0x62
        call nrrd
        ld (s62),a
        ld a,0x02
        call nrrd
        ld (s02),a
        call screen_init
        ld hl,s_warn
        call pstr
        call waitkey            ; she reads the warning; nothing has been done yet

        ld a,1
        ld (rok),a
        ld a,(s62)
        and 0xC0
        jr nz,skip              ; the copper's in use: don't take it, touch nothing
        ld a,0x06               ; both NMI enables off (bit 3 multiface, bit 4 divMMC), the rest kept
        call nrrd
        and 0xE7
        ld e,a
        ld a,0x06
        call nrwr
        ld hl,copl              ; the copper list: MOVE 0x02,0x00 then WAIT 63,511 (never)
cl1:    ld a,(hl)
        cp 0xFF
        jr z,cl2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr cl1
cl2:    ld e,0x08               ; the multiface flag
        ld ix,rbuf
        call flagtest
        ld e,0x04               ; the divMMC flag
        ld ix,rbuf+4
        call flagtest
        xor a
        ld (rok),a
        ld a,0x02               ; both flags clear, by the CPU, before anything is put back
        ld e,0x00
        call nrwr
        ld a,0x62               ; copper stopped
        ld e,0x00
        call nrwr
        ld a,(s06)              ; NR 0x06 as it was
        ld e,a
        ld a,0x06
        call nrwr

skip:   call screen_init
        ld hl,s_res
        call pstr
        ld a,(s06)
        call phex8
        ld hl,s_c2
        call pstr
        ld a,(sc2)
        call phex8
        call pspace
        ld a,(sc3)
        call phex8
        ld a,(rok)
        or a
        jr z,pr1
        ld hl,s_skip
        call pstr
        jr pr2
pr1:    ld hl,s_mf
        call pstr
        ld hl,rbuf
        call prow4
        ld hl,s_dv
        call pstr
        ld hl,rbuf+4
        call prow4
        ld hl,s_want
        call pstr
pr2:    jp finish

; E = 0x08 or 0x04: write it to NR 0x02, read NR 0x02, C2, C3; run the copper once (mode 01: from 0, MOVE 0x02,0x00,
; then it waits for ever); read NR 0x02 again; stop the copper. Four bytes at IX.
flagtest:
        ld a,0x02
        call nrwr
        ld a,0x02
        call nrrd
        ld (ix+0),a
        ld a,0xC2
        call nrrd
        ld (ix+1),a
        ld a,0xC3
        call nrrd
        ld (ix+2),a
        ld a,0x62               ; mode 01, list address 0: the MOVE happens at once
        ld e,0x40
        call nrwr
        ld b,0
ft1:    djnz ft1
        ld a,0x02
        call nrrd
        ld (ix+3),a
        ld a,0x62
        ld e,0x00
        jp nrwr

copl:   db 0x62,0x00            ; copper stopped, list address 0
        db 0x61,0x00
        db 0x60,0x02,0x60,0x00  ; MOVE NR 0x02, 0x00 (no reset bits, no NMI bits)
        db 0x60,0xFF,0x60,0xFF  ; WAIT 63,511: never satisfied
        db 0xFF

prow4:  ld b,4                  ; four bytes from HL as hex
p41:    call pspace
        ld a,(hl)
        inc hl
        call phex8
        djnz p41
        ret

s_warn: db 22,0,0,"PNM  NMI flags and the copper",13,13
        db "On a key this tape will:",13
        db " turn NR 06's NMI enables off,",13
        db " write NR 02 = 08, then 04 (the",13
        db " multiface, divMMC NMI flags)",13
        db " then clear each by the copper.",13,13
        db "The VHDL says no NMI fires.",13
        db "If the screen freezes, or a",13
        db "Multiface or NMI menu appears:",13
        db "save NOTHING; choose its Return",13
        db "or Exit, or power the Next off",13
        db "and on. It writes no files.",13,13
        db "Key: go on",0
s_res:  db 22,0,0,"PNM  NMI flags and the copper",13
        db "NR 06 was ",0
s_c2:   db 13,"C2 C3 before: ",0
s_skip: db 22,4,0,"copper busy: skipped",0
s_mf:   db 22,4,0,"NR02=08: 02 C2 C3 02-after-cu",13," ",0
s_dv:   db 22,7,0,"NR02=04: 02 C2 C3 02-after-cu",13," ",0
s_want: db 22,10,0,"VHDL: 02 has the flag (08 / 04)",13
        db "plus the reset type, bits 1:0;",13
        db "C2 C3 as before (no NMI); after",13
        db "the copper, the flag clear.",13,13
        db "nextreg.txt: NMI fires (D-8),",13
        db "the copper can't clear (D-7).",0
