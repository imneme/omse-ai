; PUA: the ESP's UART clock. NEXT-MACHINE.md §9 D-6, as a careful tape with Melissa O'Neill's go-ahead (read-only AT commands
; only; nothing stored in the ESP; nothing network-facing). Hart's-tongue Fern, Fri 06 Nov 2026. Expectations in
; NOTES.md under "PUA". Checked against Rustyback Fern's TAPE-REVIEW-CHECKLIST.md (ESP and Pi lines).
;
;   D-6  ports.txt's example: "If the system is hdmi ... Fsys = 27000000", prescaler 234 for 115200. The VHDL: the UART
;        runs on the system clock (i_CLK_28, zxnext:3316), 28.0 MHz in video setting 0, which HDMI uses; the core's
;        own power-on prescaler is 243, "115200 @ 28MHz system clock" (uart.vhd:319-320).
;
; One AT at 243 and one at 234 would both likely get OK: the two clocks are only 3.7% apart, inside what a UART
; forgives. So it sweeps: "AT\r\n" at prescalers 222-264 in steps of 2, and the window that answers OK is centred on
; the real clock (243 for 28 MHz, 234 for 27). Only "AT\r\n" is ever sent, from a constant table, at every baud; no
; break, no flow control, no NR 0xA0, 0x0B, 0xA8 or 0xA9 writes, no E7 except one OUT of FF (deselect all). It ends
; with the prescaler at 243 (the core's own power-on value), 8N1, the FIFOs empty, the select as it was.

TAPEID  equ 73                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

UTX     equ 0x133B              ; status (read), Tx byte (write)
URX     equ 0x143B              ; Rx byte (read), prescaler low 14 bits (write)
USEL    equ 0x153B              ; select: bit 6 = Pi, bit 4 = write bits 2:0 (prescaler MSBs)
UFRM    equ 0x163B              ; frame: bit 7 holds the FIFOs in reset while set (uart.vhd:385)
PFIRST  equ 222
NTRY    equ 22                  ; 222, 224, ... 264

V       equ VARS+0x20
s11     equ V+0
s02     equ V+1
s0b     equ V+2
ssel    equ V+3
skipw   equ V+4                 ; 0 ran; 1 ESP held in reset; 2 UART on the joystick port
rsw     equ V+8                 ; NTRY bytes: 2 OK, 1 bytes but no OK, 0 nothing
rep     equ V+32                ; 16 bytes: the reply at 243
pcur    equ V+48                ; word
nrx     equ V+50

main:   ld a,0xFF               ; every SPI device deselected (the one E7 write)
        out (0xE7),a
        ld a,0x11
        call nrrd
        ld (s11),a
        ld a,0x02
        call nrrd
        ld (s02),a
        ld a,0x0B
        call nrrd
        ld (s0b),a
        ld bc,USEL
        in a,(c)
        ld (ssel),a
        call screen_init
        ld hl,s_warn
        call pstr
        call waitkey            ; she reads the warning; nothing has been done yet

        ld a,1
        ld (skipw),a
        ld a,(s02)
        and 0x80                ; NR 0x02 bit 7 holds the ESP in reset: nothing to talk to
        jp nz,done
        ld a,2
        ld (skipw),a
        ld a,(s0b)              ; joystick I/O mode as a UART (NR 0x0B b7 and b5): the ESP is unplugged
        and 0xA0
        cp 0xA0
        jp z,done
        xor a
        ld (skipw),a
        ld bc,USEL              ; the ESP's UART, prescaler bits 16:14 = 0
        ld a,0x10
        out (c),a
        ld hl,PFIRST
        ld (pcur),hl
        ld ix,rsw
        ld b,NTRY
try:    push bc
        call setpre
        call fifoclr
        ld hl,s_at              ; "AT\r\n" from the table, nothing else
        ld b,4
tx1:    ld a,(hl)
        inc hl
        push bc
        ld bc,UTX
        out (c),a
        pop bc
        djnz tx1
        call waitf
        call waitf
        call waitf
        call rxread             ; HL = BUF, nrx = count; A = 2 OK, 1 bytes, 0 none
        ld (ix+0),a
        inc ix
        ld hl,(pcur)            ; keep the reply at 243
        ld de,243
        or a
        sbc hl,de
        jr nz,try2
        ld hl,BUF
        ld de,rep
        ld bc,16
        ldir
try2:   ld hl,(pcur)
        inc hl
        inc hl
        ld (pcur),hl
        pop bc
        djnz try
        ld hl,243               ; back to the core's power-on value, 115200 at 28 MHz
        ld (pcur),hl
        call setpre
        call fifoclr
        ld a,(ssel)             ; the select as it was (the UART only, bits 2:0 untouched)
        and 0x40
        ld bc,USEL
        out (c),a

done:   call screen_init
        ld hl,s_res
        call pstr
        ld a,(s11)
        call phex8
        ld hl,s_02
        call pstr
        ld a,(s02)
        call phex8
        ld hl,s_0b
        call pstr
        ld a,(s0b)
        call phex8
        ld a,(skipw)
        or a
        jr z,pr1
        ld hl,s_sk1
        dec a
        jr z,pr0
        ld hl,s_sk2
pr0:    call pstr
        jp finish
pr1:    ld hl,s_row
        call pstr
        ld hl,rsw
        ld b,NTRY
pr2:    ld a,(hl)
        inc hl
        push hl
        ld hl,marks
        add a,l
        ld l,a
        jr nc,pr3
        inc h
pr3:    ld a,(hl)
        call pchr
        pop hl
        djnz pr2
        call window
        ld hl,s_win
        call pstr
        ld hl,(wlo)
        call pdec3
        ld a,'-'
        call pchr
        ld hl,(whi)
        call pdec3
        ld hl,s_ctr
        call pstr
        ld hl,(wctr)
        call pdec3
        ld hl,s_rep
        call pstr
        ld hl,rep
        ld b,16
pr4:    ld a,(hl)
        inc hl
        cp 32
        jr c,pr5
        cp 127
        jr c,pr6
pr5:    ld a,'.'
pr6:    call pchr
        djnz pr4
        ld hl,s_want
        call pstr
        jp finish

marks:  db ".-*"

; the OK window: lowest and highest prescaler that got OK, and their middle (0 if none)
window: ld hl,0
        ld (wlo),hl
        ld (whi),hl
        ld (wctr),hl
        ld hl,rsw
        ld de,PFIRST
        ld b,NTRY
wn1:    ld a,(hl)
        cp 2
        jr nz,wn2
        push hl
        ld hl,(wlo)
        ld a,h
        or l
        jr nz,wn3
        ld (wlo),de
wn3:    ld (whi),de
        pop hl
wn2:    inc hl
        inc de
        inc de
        djnz wn1
        ld hl,(wlo)
        ld de,(whi)
        add hl,de
        srl h
        rr l
        ld (wctr),hl
        ret
wlo:    dw 0
whi:    dw 0
wctr:   dw 0

; prescaler = (pcur): bits 13:7 then 6:0 through port 0x143B (bits 16:14 were set 0 through 0x153B)
setpre: ld hl,(pcur)
        ld a,l
        and 0x7F
        ld bc,URX
        out (c),a
        add hl,hl
        ld a,h
        and 0x7F
        or 0x80
        out (c),a
        ret

fifoclr:                        ; reset and empty the FIFOs, 8N1, then release (bit 7 is a level)
        ld bc,UFRM
        ld a,0x98
        out (c),a
        ld a,0x18
        out (c),a
        ret

; read what arrived (up to 64 bytes) into BUF; A = 2 if "OK" is in it, 1 if anything came, 0 if nothing
rxread: ld hl,BUF
        push hl
        ld d,0
rx1:    ld bc,UTX
        in a,(c)
        rra                     ; bit 0: Rx has bytes
        jr nc,rx2
        ld bc,URX
        in a,(c)
        ld (hl),a
        inc hl
        inc d
        ld a,d
        cp 64
        jr c,rx1
rx2:    pop hl                  ; search the D bytes that came, by count (a mis-clocked frame can be 00)
        ld a,d
        or a
        ret z
        ld e,d
        dec e                   ; pairs to look at
        jr z,rx5
rx3:    ld a,(hl)
        inc hl
        cp 'O'
        jr nz,rx4
        ld a,(hl)
        cp 'K'
        jr nz,rx4
        ld a,2
        ret
rx4:    dec e
        jr nz,rx3
rx5:    ld a,1
        ret

rdline: push bc
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
        push hl
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
        jr wf4
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
wf4:    pop hl
        pop de
        ret

s_at:   db "AT",13,10           ; the only bytes ever sent

s_warn: db 22,0,0,"PUA  the ESP's UART clock",13,13
        db "On a key this tape talks to the",13
        db "WiFi module. It sends only AT",13
        db "(a read-only hello) at 22 baud",13
        db "settings near 115200, and sees",13
        db "which ones get OK back. Nothing",13
        db "is stored in the ESP; nothing",13
        db "touches a network. The UART is",13
        db "left at 115200.",13,13
        db "Run it soon after switching the",13
        db "Next on, so the WiFi module is",13
        db "in its plain command mode.",13,13
        db "If it freezes: power the Next",13
        db "off and on.",13,13
        db "Key: go on",0
s_res:  db 22,0,0,"PUA  the ESP's UART clock (D-6)",13
        db "NR 11 ",0
s_02:   db "  02 ",0
s_0b:   db "  0B ",0
s_sk1:  db 22,3,0,"ESP held in reset (NR 02 b7):",13
        db "not tested.",0
s_sk2:  db 22,3,0,"UART on the joystick port",13
        db "(NR 0B): not tested.",0
s_row:  db 22,3,0,"AT at prescaler 222-264, by 2:",13," ",0
s_win:  db 22,6,0,"OK from ",0
s_ctr:  db ", centre ",0
s_rep:  db 22,8,0,"reply at 243:",13," ",0
s_want: db 22,11,0,"* OK  - bytes, no OK  . none",13,13
        db "VHDL (28 MHz system clock):",13
        db "centre 243. ports.txt's 27 MHz:",13
        db "centre 234.",0
