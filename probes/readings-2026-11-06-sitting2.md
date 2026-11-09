# Readings: Melissa O'Neill's recorded sitting (Fri 06 Nov 2026), Hart's-tongue's cells

*Hart's-tongue Fern, from the frames themselves (the photos), against
`probes/NOTES.md`. Melissa O'Neill recorded the whole sitting through her capture box: one 8:20 video. Tally Fern's `find_photos.py` found 26 photos by their beeps and two by time, where the
video-timing changes cost HDMI its audio. Her first reading is in her message; every value below I read again from the
frame. Strobe has LDPIRX2/3 and Z80NTIME, Hatch PV1-PV4, Kelp P20.*

**The sitting's order** (beep times, so the state each tape found can be traced): LDPIRX2 0:04, LDPIRX3 0:19, P1 0:31,
P13 0:50, P2 1:08, P20 1:40, P2B 2:03 / 2:30 / 2:43 / 3:09, P3 3:27, P4 3:45, P6 3:59, (P7 by time), P8 4:40 / 4:42,
P81 4:55, P82 5:15-5:26, (PSS photo 1 by its half beep), PSS photo 2 6:04, PV1-PV4 6:21-7:40, Z80NTIME 8:09.

## PSS: every item as the VHDL

Photo 1 (the 60 Hz test made HDMI resync and the beep's start fell in the gap):
- Context: NR 03 33, 05 5B, 07 00, 64 00, 22 00, 62 00; 7FFD 10, 1FFD 04; MMU FF FF 0A 0B 04 05 00 01. All ports on.
- **#7 `00 01 02`** (VHDL 00 01 02; the "polled mode" reading 03 03 03). A disabled ULA or line interrupt records no
  status in NR 0xC8; an enabled one does, even in pulse mode.
- **#11 `5A 07 A5 20`**: in all-RAM mode an NR 0x57 write lands at once (the wiki says not until special mode ends).
- **#12 `000 000 000`**: copper mode 11 restarts at line 0, the first pixel row (the wiki's VBLANK would be ~247).
- **#13 `311 310` at 50 Hz, `263 263` at 60 Hz**: 312 and 311 lines at 50 Hz, 264 for both at 60 Hz (the wiki's core-2
  table: 261, 260).
- **#15 `80 81`**: DFFD bit 3 is bank bit 6 (the wiki's three-bit DFFD: 00 01).
- **#17 `0F 0F`**: FADF reads F in the low nibble with nothing pressed, buttons active low (the manual's "pressed = 1":
  0). The wheel nibble is 0, so no wheel mouse has moved since power-on, or none is attached.
- **#18 `AB AB`**: NR 0x6E/0x6F read back their bank-7 bit (the wiki's example: 2B).

Photo 2: **a yellow border round green paper**, as the VHDL says (item 10): with ULANext's ink mask
3B the paper falls back to NR 0x4A and the border stays palette 128 + border colour. Not the wiki's and manual's green
border.

So Rustyback Fern's second-sources reading §1.1 items 7, 10, 11, 12, 13, 15, 17 and 18 are settled on the test machine for the VHDL. They can move
to Rustyback's §1.2 ("already settled"), and NEXT-MACHINE.md's statements of them stand as written.

## P82: Layer 2 shows the SRAM copy of bank 5 (P-8 closed)

: with NR 0x12 = 5 the band is **red**, = 9 **blue**, = 8 **green**, and with Layer 2 off rows 0-7
are plain ULA. Each band was written through the 0x123B map with a write loop (Tally's fixed P82), so Layer 2 displays
the SRAM copy the map writes, and the ULA's block-RAM copy is untouched. D-11 confirmed on the display side, as P-81
confirmed it for the mapping. P-8's question is answered.

## P2B and NR 0x7F: the browser's loader writes it, not the reset

The four runs , with what happened between them from a contact sheet of the video (2 s a frame,
2:04-3:12):

| run | time | NR 7F | NR 02 | before it |
|---|---|---|---|---|
| 1 | 2:03 | **FF** | 01 | P20, its soft reset, the browser |
| 2 | 2:30 | **00** | 01 | **R**: 55 written, back to BASIC (menu, browser, no boot screen) |
| 3 | 2:43 | 00 | 01 | a soft reset (NextZXOS's menu with its copyright line): "other key" or W |
| 4 | 3:09 | 00 | 02 | **H**: the firmware's boot screens, a hard reset |

Two of those can't be the hardware. After R, 55 became 00 with no reset at all. And after H, the FPGA reload gives FF
(by the VHDL, zxnext.vhd:1210, and by P-1's first-ever run), yet the next load read 00. So software writes NR 0x7F on
the way to a tape. Our own tapes don't: nothing that ran before P1 or P2B writes it (I checked every source; only
Z80NTIME writes NR 0x7F, 0x40 in its NEXTREG timing, and it ran last).

**It's NextZXOS's browser loader.** A .TAP launched from the browser runs `nextzxos/tapload.bas` (browser.cfg:7-8). I
listed it (tokenised NextBASIC, through omse-ai's token table; read only):
- line 2000-2010: `l$="r """+f$+""" LOAD"` then `.$ metadata l$`: the `.METADATA` dot command looks up the file's
  stored loader options;
- line 2040: **`metacache=%REG 127`**: it returns its result in NR 0x7F;
- line 140: a value above 1 means "none found, use the default"; 0 and 1 are found in the cache or in the filename
  (line 210 prints "cache" or "fname");
- line 2330-2340: after the options screen it writes the file's options back (`.$ metadata` with `w`), to the metadata
  cache `c:/nextzxos/metadata` (Browser.gde:577-579; NextZXOS.gde:539-540).

So after any browser launch, **NR 0x7F holds `.metadata`'s status: FF the first time a file is ever launched, 00
every time after**, because the cache now has it. The cache is one file on her card, keyed by name, so it outlives a
recopy of the tapes. That explains every NR 7F we've seen:
- P2B run 1, FF: its first launch ever. Runs 2-4, 00: cached.
- P1 and P2 this sitting, 00: launched in earlier sittings.
- The first sitting's P-2, FF with NR 02 = 01, and P-1's FF at power-on: first launches. The middle sitting's P-2,
  00 before and after W: cached.

**So D-4 (nextreg.txt: "soft reset = 0xff"; the VHDL: hard reset only) is still open.** Every reading so far shows
the loader's status, not what the reset did. **No new tape is needed to settle it, only a different launch:** at the
NextBASIC prompt, type `.tapein p2.tap` and `LOAD ""` (that path doesn't run tapload.bas), note NR 7F, press **W**
(55 and a soft reset), then load P2 again the same typed way. The VHDL predicts **55**; nextreg.txt predicts **FF**.
If it's FF, NextZXOS's boot could still be the writer, so a typed `PRINT %REG 127` straight after the reset, before
any load, would separate the two.

A note for every probe: a tape launched from the browser finds NR 0x7F already written by the loader, so nothing should
carry a value in it across a load.

## P7 again: 14/45

(by time: the 48K timing switch cost HDMI's audio): first 1 at k=**014**, first 0 after at
k=**045**, a 32 T pulse, NR 03 was 33. The same as the first sitting and as Ratio's core: INT stays where the VHDL puts
it, now twice confirmed.

## Reruns: all as before

- **P1**: identical to the first sitting, register for register (02=02, 03=33, 05=5B, 06=A8, 08=DE,
  0A=11, MMU FF FF 0A 0B 04 05 00 01, 8E=0B, 82-85 and 86-89 FF FF FF 8F, B8-BB 82 00 00 F2, C0=0A, C4=81, pages
  55/AA), except **7F=00 where it read FF**: the loader's cache, above.
- **P2**: 7F 00, 02 01: a cached launch after P13's soft reset.
- **P3**: identical, count for count (C5 00, FF→0F, 00→00; 3F 83, 40 84, 41 85, 42 85; channels 4-7
  00 00; C9 00→0F). The CTC run is deterministic as well as right.
- **P4**: identical (FF, E0 and F7 all 54D2; the unmapped reads E0 7E FF E1 for both MMU7 values;
  E000 00 00), except page DF's sum, **17E2** where it was 2F0A. That's ordinary RAM, the control that differs from the
  ROM, so its contents are free to change.
- **P6**: identical to the tick: 14 MHz 16421 16422 16422 / 14355 ×3; 28 MHz 10261, 08213, 10262,
  09226, 08203, 08203. The VHDL within one stopwatch tick, twice now.
- **P13**: identical (as they were 00 FF FF; Sinclair 2 FF FF FF; Kempston 00 00 FF; NR 05 5B).
- **P81**: identical, line for line. Its line A, "write-only map, 0000 reads F3", says exactly what
  explained P-8: reads through the write-only map come from the ROM. It was on the screen in the first sitting.
- **P8** (retired, but run): photo 1 shows Layer 2's top third as noise, now the ROM's bytes that its
  LDIR copied through the write-only map; photo 2, Layer 2 off, shows the ULA's stripes everywhere and no green. Just as
  "P-8 explained" says, and P82 asks the question properly.

## What needs another run

1. **D-4**: P2 launched by typing `.tapein p2.tap` / `LOAD ""` with W, as above. No new tape.
2. **The beep after a timing change** (a suggestion, not a fault): PSS photo 1 and P7 lost their beeps because HDMI was
   still resyncing after the tape put the video timing back. A pause of about three seconds after the restore, before
   the photo beep, would give the capture box its audio back. It's a small change to p7.asm and pss.asm if wanted; the
   frames were found by time anyway.

## Sitting 3 (Fri 06 Nov evening): D-4 settled, and the settle works

Read from the photos.
The order by the beeps: P7 0:09, PSS 0:41 / 0:44, PV5 1:25, P2 3:09 and 3:59.

- **P2, launched by typing `.tapein p2.tap` and `LOAD ""`** (no browser, so no `tapload.bas`):
  - first run : NR 7F **FF**, NR 02 01;
  - Melissa O'Neill pressed **W** (55, then a soft reset) and loaded it the same typed way: **NR 7F 55**,
    NR 02 01.

  **NR 0x7F keeps its value across a soft reset, and NextZXOS's boot leaves it alone**, as the VHDL says
  (zxnext.vhd:1210, declared FF with no reset branch). nextreg.txt's 3.02.02 "soft reset = 0xff" is wrong; the
  changelog (3.01.09) and 3.02.05's nextreg.txt already say hard reset only. **D-4 settled for the VHDL.**

  The first run's FF fits the loader explanation too. PV5, launched from the browser just before, was a new tape, so
  `.metadata` found no entry for it and left FF, which the typed launch of P2 then read without the loader touching it.
- **P7** (**found by its beep** this time): first 1 at k=014, first 0 after at k=045, NR 03 33. The third
  time, the same.
- **PSS photo 1** (**found by its beep**): every cell as in sitting 2, all as the VHDL. Photo 2 as before.

So `pb_settle`'s three seconds bring HDMI audio back on her real capture path: both beeps that the timing switches had
cost are back.

NEXT-MACHINE.md §9 now marks D-4, D-5, D-9, D-11 and D-13 settled for the VHDL and D-17 answered, each with the
readings file; nextregs.tsv's NR 0x7F row says so too.

## Sitting 5: PBD, every row as the VHDL

the photo, read from the frame. Context: NR 80 00, 81 00, 07 00, 08 DE, 22 00,
03 33, 85 8F, 23 00 (NextZXOS as P-1 found it).
- **D-3 `00000`, `00004`, `00004`**: NR 0x22 bit 7 is never set for a disabled source, and is set for the line
  interrupt too. It's the pulse-mode INT from any enabled source, as the VHDL says (zxnext:5899). nextreg.txt's "ula
  is asserting an interrupt (even if disabled)" is wrong twice: not for a disabled ULA, and not only the ULA. **D-3
  settled for the VHDL.**
- **D-12**: port 0x40FF at 48K timing **4929** reads not FF in 30000, **2066** of them the screen's attribute 38; port
  0x40F7 **00000**. Only port 0xFF floats, as the VHDL says. **D-12 settled for the VHDL.**
  - **For Ratio and Speccy-Zone:** omse-ai's Next gave 6864 and 6017 for the same loop. On the real Next 42% of the
    non-FF bytes were the attribute, against 88% on the model, so the model puts the attribute on the floating bus
    for much more of the fetch than the hardware does, and the pixel bytes for less. The loop isn't synchronised to
    the beam, so the totals vary a little, but not by that ratio. A P-12-style probe synchronised to the beam (as P-7
    is) would map the byte by T-state if wanted.
- **BUS-1 `00 00`, `03 33`; BUS-3 `FF FF FF FF`; BUS-4 05876/05876, 10996/10996, 08953/08953**: with nothing on the
  connector, NR 0x81 reads 00 with the bus off and on, the bus pins the CPU to 3.5 MHz (NR 0x07 = 3 reads 03), undecoded
  ports read FF through the pull-ups, and the bus adds no waits to fetches, I/O or memory reads. All three timings
  match omse-ai's to the tick. Rustyback's P-BUS-1, 3 and 4 are answered as she predicted; P-BUS-2 is still open.
