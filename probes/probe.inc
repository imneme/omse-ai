; probe.inc: shared code for the Spectrum Next probe tapes.
; Hart's-tongue Fern, Fri 06 Nov 2026. See NOTES.md and ../docs/next/NEXT-MACHINE.md section 9.
;
; Each probe is CODE at 0x8000, started by RANDOMIZE USR 32768 from a TAP (build_probes.py).
; Interrupts stay off for the whole run, and we use our own stack, so MMU slots 2-3 can be touched.
; The probe defines `main`. It reads what it needs *before* calling screen_init, which changes the display.
; Then it prints and ends with `finish`: wait for a key, soft-reset the Next. On a machine that isn't a Next,
; the reset does nothing and we return to BASIC.
;
; Memory used: code 0x8000-0x8FFF, buffer 0x9000-0x9FFF, sled 0xA000-0xAFFF, font 0xB000, vars 0xB300,
; stack below 0xBF00. All in slots 4-5, which are SRAM pages 4 and 5 under NextZXOS and BASIC.

NRSEL   equ 0x243B
NRDAT   equ 0x253B
BUF     equ 0x9000
SLED    equ 0xA000
FONTBUF equ 0xB000
VARS    equ 0xB300
STACKTOP equ 0xBF00
ATTR    equ 0x38                ; black ink on white paper

prow    equ VARS                ; print position
pcol    equ VARS+1
savesp  equ VARS+2
sv8e    equ VARS+4
svm0    equ VARS+5
svm1    equ VARS+6

        org 0x8000
start:  di
        ld (savesp),sp
        ld sp,STACKTOP
        xor a                   ; no photos yet this run (beep.inc)
        ld (pb_photo),a
        call main
back:   ld sp,(savesp)
        ei
        ret

; ---- nextreg access through the ports (so a non-Next just reads FF) ----

nrrd:   push bc                 ; A = register -> A = value
        ld bc,NRSEL
        out (c),a
        ld bc,NRDAT
        in a,(c)
        pop bc
        ret

nrwr:   push bc                 ; A = register, E = value
        ld bc,NRSEL
        out (c),a
        ld bc,NRDAT
        out (c),e
        pop bc
        ret

; ---- the screen ----

; Make the ULA screen visible and clear. Copy the ROM font. Puts bank 5 at 0x4000.
screen_init:
        call getfont
        ld hl,dispregs
si1:    ld a,(hl)               ; pairs (register, value), ending with FF
        cp 0xFF
        jr z,si2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr si1
si2:    ld hl,0x4000
        ld de,0x4001
        ld bc,6143
        ld (hl),0
        ldir
        ld hl,0x5800
        ld de,0x5801
        ld bc,767
        ld (hl),ATTR
        ldir
        ld a,7
        out (0xFE),a
        ld (pb_border),a        ; the photo beep keeps this border
        ld a,23                 ; the prompt row, yellow
        ld (prow),a
        ld a,0x30
        call hilite
        xor a
        ld (prow),a
        ld (pcol),a
        ld a,0x0F               ; the title row, white on blue
        jp hilite

; The attributes of row (prow) to A
hilite: push hl
        push de
        push bc
        ld c,a
        ld a,(prow)
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,0x5800
        add hl,de
        ld b,32
hi1:    ld (hl),c
        inc hl
        djnz hi1
        pop bc
        pop de
        pop hl
        ret

dispregs:
        db 0x69,0x00            ; Layer 2 off, shadow screen off, Timex mode 0
        db 0x6B,0x00            ; tilemap off
        db 0x15,0x00            ; LoRes off, sprites off, SLU
        db 0x68,0x00            ; ULA on, ULA+ off, no stencil
        db 0x43,0x00            ; ULANext off, first palettes
        db 0x26,0x00,0x27,0x00  ; ULA scroll 0
        db 0x1C,0x04            ; ULA clip index to 0, then 0,255,0,191
        db 0x1A,0x00,0x1A,0xFF,0x1A,0x00,0x1A,0xBF
        db 0x52,0x0A,0x53,0x0B  ; bank 5 at 0x4000-0x7FFF
        db 0xFF

; The 48K ROM's font (32-127) into FONTBUF. If the ROM at 0x0000 isn't the 48K one, select ROM 3 through NR 0x8E
; first, without touching the RAM bank (bit 3 = 0), and afterwards put NR 0x8E's ROM bits and MMU0/1 back.
getfont:
        ld hl,0x3D00
        call fontok
        jr z,gf_copy
        ld a,0x8E
        call nrrd
        ld (sv8e),a
        ld a,0x50
        call nrrd
        ld (svm0),a
        ld a,0x51
        call nrrd
        ld (svm1),a
        ld a,0x8E
        ld e,0x03               ; normal paging, ROM 3, RAM bank unchanged
        call nrwr
        call gf_copy
        ld a,(sv8e)
        and 0xF7
        ld e,a
        ld a,0x8E
        call nrwr
        ld a,(svm0)
        ld e,a
        ld a,0x50
        call nrwr
        ld a,(svm1)
        ld e,a
        ld a,0x51
        jp nrwr
gf_copy:
        ld hl,0x3D00
        ld de,FONTBUF
        ld bc,768
        ldir
        ret

; Z if HL points at a plausible font: space is eight zero bytes; '0' starts with a zero row and isn't blank.
fontok: push hl
        ld b,8
fo1:    ld a,(hl)
        or a
        jr nz,fo_no
        inc hl
        djnz fo1
        pop hl
        push hl
        ld de,0x80
        add hl,de
        ld a,(hl)
        or a
        jr nz,fo_no
        inc hl
        ld a,(hl)
        inc hl
        or (hl)
        jr z,fo_no
        pop hl
        xor a
        ret
fo_no:  pop hl
        or 1
        ret

; Print character A at (prow, pcol). 13 = new line. Wraps at column 32.
pchr:   cp 13
        jr z,pnl
        push hl
        push de
        push bc
        sub 32
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,FONTBUF
        add hl,de
        ld a,(prow)
        ld b,a
        and 0x18
        or 0x40
        ld d,a
        ld a,b
        and 7
        rrca
        rrca
        rrca
        ld e,a
        ld a,(pcol)
        or e
        ld e,a
        ld b,8
pc1:    ld a,(hl)
        ld (de),a
        inc hl
        inc d
        djnz pc1
        pop bc
        pop de
        pop hl
        ld a,(pcol)
        inc a
        ld (pcol),a
        cp 32
        ret c
pnl:    xor a
        ld (pcol),a
        ld a,(prow)
        inc a
        cp 24
        jr c,pnl1
        xor a
pnl1:   ld (prow),a
        ret

; Print the zero-terminated string at HL. 13 = new line; 22,r,c = move to row r, column c.
pstr:   ld a,(hl)
        inc hl
        or a
        ret z
        cp 22
        jr z,pstr_at
        call pchr
        jr pstr
pstr_at:
        ld a,(hl)
        inc hl
        ld (prow),a
        ld a,(hl)
        inc hl
        ld (pcol),a
        jr pstr

phex8:  push af                 ; A as two hex digits
        rrca
        rrca
        rrca
        rrca
        call phexd
        pop af
phexd:  and 0x0F
        add a,'0'
        cp '9'+1
        jr c,phd1
        add a,7
phd1:   jp pchr

phex16: ld a,h                  ; HL as four hex digits
        call phex8
        ld a,l
        jp phex8

pdec3:  ld bc,100               ; HL (0-999) as three decimal digits
        call pdd
        ld bc,10
        call pdd
        ld a,l
        add a,'0'
        jp pchr
pdd:    ld a,'0'-1
pdd1:   inc a
        or a
        sbc hl,bc
        jr nc,pdd1
        add hl,bc
        jp pchr

pspace: ld a,' '
        jp pchr

; ---- keys and the end ----

waitkey:                        ; until no key is held, then until one is pressed
wk1:    xor a
        in a,(0xFE)
        cpl
        and 0x1F
        jr nz,wk1
wk2:    xor a
        in a,(0xFE)
        cpl
        and 0x1F
        jr z,wk2
        ret

softreset:                      ; NR 0x02 bit 0. A real Next is gone before the loop ends.
        ld a,0x02
        ld e,0x01
        call nrwr
        ld b,0
sr1:    djnz sr1
        ret

; The common ending: a prompt on the bottom row, a key, a soft reset (or back to BASIC if not a Next).
finish: ld hl,s_finish
        call pstr
        call photokey
        call softreset
        jp back
s_finish:
        db 22,23,0,"Photo, please. Key: soft reset",0

; A photo's key wait: the photo beep (beep.inc, which needs the tape's TAPEID), then a key. Tapes that draw their
; own photo prompt call this in place of waitkey. Any tape that changes the border stores it in pb_border too.
photokey:
        call photobeep
        jp waitkey

        include "beep.inc"
