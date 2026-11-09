; PSS: "second sources". One tape for the open disagreements in Rustyback Fern's second-sources reading section 1.1
; (Rustyback Fern's reading of the Next manual and wiki against core 3.02.02) that aren't DMA (Kelp's)
; or sprite flags (Hatch's PV2). Hart's-tongue Fern, Fri 06 Nov 2026. Expectations, with the VHDL lines,
; in NOTES.md under "PSS".
;
; Photo 1, numbers:
;   item 7   NR 0xC8 records nothing for a disabled ULA or line interrupt
;   item 11  in all-RAM mode an NR 0x57 write takes effect at once
;   item 12  copper mode 11 restarts at line 0 (cvc 0), not at vertical blank
;   item 13  60 Hz frames are 264 lines in 48K and in 128K timing
;   item 15  port DFFD has four bank bits (bit 3 is bank bit 6)
;   item 17  port FADF: buttons active low, bit 3 = 1
;   item 18  NR 0x6E/0x6F read back their bank-7 bit
; Photo 2, colour:
;   item 10  ULANext with an invalid ink mask: paper from NR 0x4A, border still palette 128 + border colour
;
; Interrupts are off throughout (probe.inc). Everything this changes is put back before the photos, and the
; ending is a soft reset; the two palette entries it borrows (which a soft reset keeps) are put back first.

TAPEID  equ 77                ; the photo beep's tape ID (beep.inc; NOTES.md "The photo beep")
        include "probe.inc"

BANKM   equ 0x5B5C              ; NextZXOS's copy of port 7FFD
BANK678 equ 0x5B67              ; ... and of port 1FFD
BORDCR  equ 0x5C48              ; border colour in bits 5:3

V       equ VARS+0x20
s03     equ V+0                 ; saved state
s05     equ V+1
s07     equ V+2
s22     equ V+3
s23     equ V+4
s16     equ V+5
s64     equ V+6
s6e     equ V+7
s6f     equ V+8
smmu    equ V+9                 ; 8 bytes, V+9 .. V+16
sbankm  equ V+17
sb678   equ V+18
sbord   equ V+19
s42     equ V+20
s4a     equ V+21
spal    equ V+22                ; 4 bytes: entry 56 (8-bit, NR44 read), entry 130 (same)
r6e     equ V+26                ; results
r6f     equ V+27
rfad    equ V+28                ; 2 bytes
rc8     equ V+30                ; 3 bytes
rdf     equ V+33                ; 2 bytes: NR 0x56, NR 0x57
rar     equ V+35                ; 4 bytes: E000, NR57, E000, NR57
rarok   equ V+39                ; 0 = ran
rdfok   equ V+40
rcopok  equ V+41
rcop    equ V+42                ; 3 words
rln     equ V+48                ; 4 words: 48K 50, 128K 50, 48K 60, 128K 60
o20     equ V+56
o07     equ V+57
s62     equ V+58
rfadok  equ V+59                ; 0 = ran, 1 = skipped, 2 = port disabled

SIGP    equ 0x20                ; the page that gets the A5 signature (bank 16)

main:
        ld hl,savelist          ; state first, before screen_init changes the display
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
sv2:    ld a,(BANKM)
        ld (sbankm),a
        ld a,(BANK678)
        ld (sb678),a
        ld a,(BORDCR)
        ld (sbord),a

        call screen_init
        ld b,8                  ; the MMU as screen_init leaves it (bank 5 at 0x4000)
        ld hl,smmu
        ld c,0x50
mm1:    ld a,c
        call nrrd
        ld (hl),a
        inc hl
        inc c
        djnz mm1
        ld hl,s_testing
        call pstr

        call t18
        call t17
        call t7
        call t15
        call t11
        ld a,0x07               ; 28 MHz for the copper and the line counts: finer polling
        ld e,3
        call nrwr
        call t12
        call t13
        ld a,(s07)
        ld e,a
        ld a,0x07
        call nrwr

        call results
        ld hl,s_photo1
        call pstr
        call pb_settle          ; ~3 s: HDMI back from the 60 Hz and timing tests before the photo beep
        call photokey           ; the photo beep, then a key

        call t10
        ld hl,s_photo2
        call pstr
        call photokey           ; the photo beep, then a key
        call t10end
        call softreset
        jp back

savelist:                       ; register, where to save it
        db 0x03
        dw s03
        db 0x05
        dw s05
        db 0x07
        dw s07
        db 0x22
        dw s22
        db 0x23
        dw s23
        db 0x16
        dw s16
        db 0x64
        dw s64
        db 0x6E
        dw s6e
        db 0x6F
        dw s6f
        db 0x42
        dw s42
        db 0x4A
        dw s4a
        db 0x62
        dw s62
        db 0xFF

; ---- helpers ----

; HL = the line counter, NR 0x1E/0x1F (cvc: 0 at the first pixel row when NR 0x64 = 0)
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

; Wait until line 10, then until it's past: called twice, at least one whole frame goes by.
; Gives up after 65536 reads (on a machine without NR 0x1E/0x1F).
waitf:  push de
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

; Put the MMU back as saved.
rstmmu: push bc
        push hl
        push de
        ld b,8
        ld hl,smmu
        ld c,0x50
rm1:    ld e,(hl)
        ld a,c
        call nrwr
        inc hl
        inc c
        djnz rm1
        pop de
        pop hl
        pop bc
        ret

; ---- item 18: NR 0x6E/0x6F read-backs (zxnext:5405-5411 writes, 6014-6017 reads) ----

t18:    ld a,0x6E
        ld e,0xEB
        call nrwr
        ld a,0x6F
        ld e,0xEB
        call nrwr
        ld a,0x6E
        call nrrd
        ld (r6e),a
        ld a,0x6F
        call nrrd
        ld (r6f),a
        ld a,(s6e)
        ld e,a
        ld a,0x6E
        call nrwr
        ld a,(s6f)
        ld e,a
        ld a,0x6F
        jp nrwr

; ---- item 17: port FADF twice, a frame apart (zxnext:3518) ----

t17:    ld a,2
        ld (rfadok),a
        ld a,0x83               ; the mouse ports' enable, NR 0x83 bit 5 (zxnext:2381)
        call nrrd
        and 0x20
        ret z
        xor a
        ld (rfadok),a
        ld bc,0xFADF
        in a,(c)
        ld (rfad),a
        call wait2
        ld bc,0xFADF
        in a,(c)
        ld (rfad+1),a
        ret

; ---- item 7: NR 0xC8 with the ULA and line interrupts disabled or enabled (im2_peripheral:160;
;      zxula_timing:551, 577; NR 0xC8 b1 = line, b0 = ULA, zxnext:6155) ----

t7:     ld a,0x23
        ld e,100                ; line interrupt at line 100
        call nrwr
        ld e,0x04               ; ULA off, line off
        call c8case
        ld (rc8),a
        ld e,0x00               ; ULA on, line off
        call c8case
        ld (rc8+1),a
        ld e,0x06               ; ULA off, line on
        call c8case
        ld (rc8+2),a
        ld a,(s23)
        ld e,a
        ld a,0x23
        call nrwr
        ld a,(s22)
        and 0x07
        ld e,a
        ld a,0x22
        jp nrwr

c8case: ld a,0x22
        call nrwr
        ld a,0xC8
        ld e,0x03               ; clear both
        call nrwr
        call wait2
        ld a,0xC8
        jp nrrd

; ---- item 15: DFFD bit 3 is bank bit 6 (zxnext:3704-3707; MMU6/7 4620-4621) ----

t15:    ld a,2
        ld (rdfok),a
        ld a,0x82               ; DFFD's enable, NR 0x82 bit 2 (zxnext:2359)
        call nrrd
        and 0x04
        ret z
        ld a,1
        ld (rdfok),a
        ld a,(sbankm)
        and 0x20                ; 7FFD locked: DFFD writes would be ignored
        ret nz
        ld bc,0xDFFD
        ld a,0x08
        out (c),a
        ld a,(sbankm)
        and 0xF8                ; bank 0 in 7FFD, ROM and screen bits kept
        ld bc,0x7FFD
        out (c),a
        ld a,0x56
        call nrrd
        ld (rdf),a
        ld a,0x57
        call nrrd
        ld (rdf+1),a
        ld bc,0xDFFD
        xor a
        out (c),a
        ld a,(sbankm)
        ld bc,0x7FFD
        out (c),a
        call rstmmu
        xor a
        ld (rdfok),a
        ret

; ---- item 11: all-RAM mode, then NEXTREG 0x57 (zxnext:4564-4573 sets the MMU once; 4627-4636) ----
; Configuration 00 maps banks 0,1,2,3, so 0x8000-0xBFFF (this code, the stack) stays bank 2, pages 4/5.
; Nothing may touch 0x4000-0x7FFF while it runs (that's bank 1 then), and no 7FFD write until it's over.

t11:    ld a,2
        ld (rarok),a
        ld a,0x82               ; 7FFD and 1FFD enabled, NR 0x82 bits 1 and 3 (zxnext:2358, 2360)
        call nrrd
        and 0x0A
        cp 0x0A
        ret nz
        ld a,1
        ld (rarok),a
        ld a,(smmu+4)
        cp 4
        ret nz
        ld a,(smmu+5)
        cp 5
        ret nz
        ld a,(sbankm)
        and 0x20
        ret nz
        ld a,0x57               ; signatures: A5 in page SIGP, 5A in page 7, at offset 0
        ld e,SIGP
        call nrwr
        ld a,(0xE000)
        ld (o20),a
        ld a,0xA5
        ld (0xE000),a
        ld a,0x57
        ld e,0x07
        call nrwr
        ld a,(0xE000)
        ld (o07),a
        ld a,0x5A
        ld (0xE000),a
        ld bc,0x1FFD            ; special mode, configuration 00
        ld a,0x01
        out (c),a
        ld a,(0xE000)           ; page 7 from the table: 5A
        ld (rar),a
        ld a,0x57
        call nrrd
        ld (rar+1),a            ; 07
        ld a,0x57
        ld e,SIGP
        call nrwr
        ld a,(0xE000)           ; VHDL: A5 (the write landed); wiki: still 5A
        ld (rar+2),a
        ld a,0x57
        call nrrd
        ld (rar+3),a
        ld a,(sb678)            ; leave special mode
        and 0xFE
        ld bc,0x1FFD
        out (c),a
        ld a,(sbankm)
        ld bc,0x7FFD
        out (c),a
        ld a,0x57               ; the two borrowed bytes back
        ld e,SIGP
        call nrwr
        ld a,(o20)
        ld (0xE000),a
        ld a,0x57
        ld e,0x07
        call nrwr
        ld a,(o07)
        ld (0xE000),a
        call rstmmu
        xor a
        ld (rarok),a
        ret

; ---- item 12: where copper mode 11 restarts (copper.vhd:80; hcount = hc_ula, vcount = cvc,
;      zxnext:3890-3891, 6644). The list: MOVE NR 0x16 = 55, then HALT (WAIT 63,511). The CPU sets
;      NR 0x16 to 0 and reads the line when the copper has written 55 again. ----

t12:    ld a,1
        ld (rcopok),a
        ld a,(s62)
        and 0xC0                ; the copper's already running something: leave it
        ret nz
        ld hl,coplist
co1:    ld a,(hl)
        cp 0xFF
        jr z,co2
        inc hl
        ld e,(hl)
        inc hl
        call nrwr
        jr co1
co2:    call cwait              ; mode 11 runs the MOVE at once
        jr c,coend
        ld ix,rcop
        ld b,3
co3:    push bc
        ld a,0x16
        ld e,0
        call nrwr
        call cwait
        jr nc,co4
        ld hl,0xFFFF
co4:    ld (ix+0),l
        ld (ix+1),h
        inc ix
        inc ix
        pop bc
        djnz co3
        xor a
        ld (rcopok),a
coend:  ld a,0x62
        ld e,0
        call nrwr
        ld a,(s16)
        ld e,a
        ld a,0x16
        call nrwr
        ld a,(s64)
        ld e,a
        ld a,0x64
        jp nrwr

coplist:
        db 0x64,0x00            ; no line offset: cvc 0 is the first pixel row
        db 0x62,0x00            ; copper stopped, list address 0
        db 0x61,0x00
        db 0x60,0x16,0x60,0x55  ; MOVE NR 0x16, 0x55
        db 0x60,0xFF,0x60,0xFF  ; WAIT 63,511: never
        db 0x16,0x00
        db 0x62,0xC0            ; mode 11
        db 0xFF

; Until NR 0x16 reads 55, then HL = the line. Carry if it never does (65536 reads).
cwait:  ld de,0
cw1:    ld a,0x16
        call nrrd
        cp 0x55
        jr z,cw2
        dec de
        ld a,d
        or e
        jr nz,cw1
        scf
        ret
cw2:    call rdline
        or a
        ret

; ---- item 13: the largest line number in 48K and 128K timing at 50 and 60 Hz (zxula_timing:147-312;
;      NR 0x03 write zxnext:5063-5070, NR 0x05 bit 2 zxnext:5743-5745; both change at a frame start) ----

t13:    ld e,0x90               ; 48K timing, 50 Hz
        call settim
        call set50
        call maxln
        ld (rln),hl
        call set60              ; 48K, 60 Hz
        call maxln
        ld (rln+4),hl
        ld e,0xA0               ; 128K, 60 Hz
        call settim
        call maxln
        ld (rln+6),hl
        call set50              ; 128K, 50 Hz
        call maxln
        ld (rln+2),hl
        ld a,(s05)              ; as it was
        ld e,a
        ld a,0x05
        call nrwr
        ld a,(s03)
        and 0x70
        or 0x80
        ld e,a
        ld a,0x03
        call nrwr
        jp wait2

settim: ld a,0x03
        call nrwr
        jp wait2
set50:  ld a,(s05)
        and 0xFB
        jr set5x
set60:  ld a,(s05)
        or 0x04
set5x:  ld e,a
        ld a,0x05
        call nrwr
        jp wait2

; HL = the largest line number over 12000 reads (several frames at 28 MHz). A read that straddles a line
; change can only come out lower than the truth (MSB first), never higher.
maxln:  ld de,0
        ld hl,12000
        ld (mlcnt),hl
ml1:    call rdline
        ld a,h
        cp d
        jr c,ml3
        jr nz,ml2
        ld a,l
        cp e
        jr c,ml3
ml2:    ex de,hl
ml3:    ld hl,(mlcnt)
        dec hl
        ld (mlcnt),hl
        ld a,h
        or l
        jr nz,ml1
        ex de,hl
        ret
mlcnt:  dw 0

; ---- photo 1 ----

results:
        call screen_init
        ld hl,s_res
        call pstr
        ld hl,ctxregs           ; row 2: NR 03 05 07 64 22 62, then 7FFD and 1FFD as NextZXOS left them
        ld b,8
rs1:    ld a,b
        cp 1                    ; the last one (1FFD) sits two further right, under its heading
        jr nz,rs2
        call pspace
        call pspace
rs2:    ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld a,(de)
        call phex8
        call pspace
        djnz rs1
        ld hl,s_mmu             ; row 3: the MMU
        call pstr
        ld hl,smmu
        ld b,8
        call phexn

        ld hl,s_7               ; item 7
        call pstr
        ld hl,rc8
        ld b,3
        call phexn

        ld hl,s_11              ; item 11
        call pstr
        ld a,(rarok)
        or a
        jr nz,rs11s
        ld hl,rar
        ld b,4
        call phexn
        jr rs11e
rs11s:  call pskip
rs11e:
        ld hl,s_12              ; item 12
        call pstr
        ld a,(rcopok)
        or a
        jr nz,rs12s
        ld hl,rcop
        ld b,3
        call pdecn
        jr rs12e
rs12s:  call pskip
rs12e:
        ld hl,s_13a             ; item 13
        call pstr
        ld hl,rln
        ld b,2
        call pdecn
        ld hl,s_13b
        call pstr
        ld hl,rln+4
        ld b,2
        call pdecn

        ld hl,s_15              ; item 15
        call pstr
        ld a,(rdfok)
        or a
        jr nz,rs15s
        ld hl,rdf
        ld b,2
        call phexn
        jr rs15e
rs15s:  call pskip
rs15e:
        ld hl,s_17              ; item 17
        call pstr
        ld a,(rfadok)
        or a
        jr nz,rs17s
        ld hl,rfad
        ld b,2
        call phexn
        jr rs17e
rs17s:  call pskip
rs17e:

        ld hl,s_18              ; item 18
        call pstr
        ld hl,r6e
        ld b,2
        call phexn

        ld hl,s_want
        jp pstr

; A = 1: " skip", 2: " port off"
pskip:  ld hl,s_skip
        dec a
        jp z,pstr
        ld hl,s_off
        jp pstr

; B bytes from HL as hex, a space before each
phexn:  call pspace              ; first: pchr hands back the column in A
        ld a,(hl)
        inc hl
        call phex8              ; pchr keeps BC, DE and HL
        djnz phexn
        ret

; B words from HL as three decimal digits (FFFF as ---), a space before each
pdecn:  ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        push hl
        push bc
        call pspace
        ex de,hl
        ld a,h
        and l
        inc a
        jr z,pdn1
        ld de,1000              ; over 999: say so
        or a
        sbc hl,de
        add hl,de
        jr nc,pdn1
        call pdec3
        jr pdn2
pdn1:   ld hl,s_dash
        call pstr
pdn2:   pop bc
        pop hl
        djnz pdecn
        ret

ctxregs:
        dw s03,s05,s07,s64,s22,s62,sbankm,sb678

; ---- photo 2: item 10, ULANext with ink mask 3B (zxula:485-526; fallback zxnext:6894-6897) ----
; Every attribute is 38: ink = 38 AND 3B = 38, entry 56, set white; paper falls back to NR 0x4A, set green.
; The border is palette 128 + border colour (2) = entry 130, set yellow, unless the VHDL is wrong.
; If ULANext didn't switch on at all, the border is standard red and the paper white.

t10:    ld a,0x43               ; read through the first ULA palette
        ld e,0x00
        call nrwr
        ld a,56
        call palrd
        ld (spal),de
        ld a,130
        call palrd
        ld (spal+2),de
        call screen_init
        ld hl,0x5800            ; one attribute everywhere, the title and prompt rows too
        ld de,0x5801
        ld bc,767
        ld (hl),0x38
        ldir
        ld hl,s_10
        call pstr
        ld a,56
        ld e,0xFF               ; white
        call palwr
        ld a,130
        ld e,0xFC               ; yellow
        call palwr
        ld a,0x4A
        ld e,0x1C               ; green
        call nrwr
        ld a,0x42
        ld e,0x3B               ; not one of 01 03 07 0F 1F 3F 7F FF
        call nrwr
        ld a,2
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ld a,0x43
        ld e,0x01               ; ULANext on, first ULA palette
        jp nrwr

t10end: ld a,0x43
        ld e,0x00
        call nrwr
        ld a,(s42)
        ld e,a
        ld a,0x42
        call nrwr
        ld a,(s4a)
        ld e,a
        ld a,0x4A
        call nrwr
        ld a,56
        ld de,(spal)
        call palput
        ld a,130
        ld de,(spal+2)
        call palput
        ld a,(sbord)
        rrca
        rrca
        rrca
        and 7
        out (0xFE),a
        ld (pb_border),a        ; for the photo beep
        ret

; Entry A of the selected palette: E = NR 0x41 (RRRGGGBB), D = NR 0x44 (priority bits, blue LSB)
palrd:  ld e,a
        ld a,0x40
        call nrwr
        ld a,0x41
        call nrrd
        push af
        ld a,0x44
        call nrrd
        ld d,a
        pop af
        ld e,a
        ret

; Entry A = E (8-bit write)
palwr:  push de
        ld e,a
        ld a,0x40
        call nrwr
        pop de
        ld a,0x41
        jp nrwr

; Entry A = E, D as read by palrd: exactly the nine bits and priority it had
palput: push de
        ld e,a
        ld a,0x40
        call nrwr
        pop de
        push de
        ld a,0x44
        call nrwr
        pop de
        ld e,d
        ld a,0x44
        jp nrwr

; ---- text ----

s_testing:
        db 22,2,0,"Testing. The screen may go dark",13
        db "for a few seconds (60 Hz).",0
s_res:  db 22,0,0,"PSS  second sources, 3.02.02",13
        db "NR 03 05 07 64 22 62 7FFD 1FFD",13
        db "   ",0
s_mmu:  db 22,3,0,"MMU0-7",0
s_7:    db 22,4,0,"#7  C8 off/ULA/line:",0
s_11:   db 22,6,0,"#11 allram E000 57 E000 57",13,"    got",0
s_12:   db 22,9,0,"#12 copper restart:",0
s_13a:  db 22,11,0,"#13 50Hz 48K 128K:",0
s_13b:  db 22,12,0,"    60Hz 48K 128K:",0
s_15:   db 22,15,0,"#15 DFFD 08, MMU6 7:",0
s_17:   db 22,17,0,"#17 FADF twice:",0
s_18:   db 22,19,0,"#18 6E 6F after EB:",0
s_want: db 22,5,4,"VHDL 00 01 02  doc 03 03 03"
        db 22,8,4,"VHDL 5A 07 A5 20  wiki ..5A"
        db 22,10,4,"VHDL 000 000 000  wiki ~247"
        db 22,13,4,"VHDL 311 310 263 263"
        db 22,14,4,"wiki 60Hz: 261 260"
        db 22,16,4,"VHDL 80 81  wiki 00 01"
        db 22,18,4,"VHDL xF xF, same  man x0"
        db 22,20,4,"VHDL AB AB  wiki 2B 2B",0
s_skip: db " skip",0
s_off:  db " port off",0
s_dash: db "---",0
s_photo1:
        db 22,23,0,"Photo 1, please. Key: photo 2",0
s_photo2:
        db 22,23,0,"Photo 2, please. Key: reset",0
s_10:   db 22,0,0,"PSS photo 2: ULANext, mask 3B",13,13
        db "Border YELLOW: as the VHDL.",13,13
        db "Border GREEN, like this paper:",13
        db "as the wiki and the manual.",13,13
        db "Border RED, paper WHITE:",13
        db "ULANext didn't switch on.",0
