; Border stripes: change the border colour every few T-states, forever.
; The beam draws the border as it goes, so the colours come out as stripes.
    org 32768
start:
    di
loop:
    ld a, b
    and 7
    out (254), a
    inc b
    ld c, 9
wait:
    dec c
    jr nz, wait
    jr loop
    end start
