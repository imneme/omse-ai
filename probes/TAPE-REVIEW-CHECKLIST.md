# Risky-tape review checklist (Rustyback, for Hart's-tongue's NMI / copper-NR02 / config-mode tapes)

Melissa O'Neill's rule (via Tally): hangs OK; nothing that could harm hardware or card; no flash, SD or bitstream writes; SPI deselected throughout.
Flag anything that can write the flash or a card, hard-reset or reload the core, or do more than hang.
Also check: each screen warns before it acts, and the README says what "stuck" looks like.

All cites are 3.02.02 (fpga-30202/cores/zxnext/src).

## SPI: flash and SD
- Port 0xE7 is decoded on A7:0 only. Check every OUT whose low port byte is E7, including OUT (C),r with C = E7, OUTI/OTIR loops, and DMA port addresses.
  - Only 0xFF is allowed.
  - Low bits 10 select SD0; low bits 01 select SD1.
  - FB and F7 select the Pi.
  - **0x7F selects the FPGA flash**, in config mode or while nr_02_reset_type(2) = 1 (zxnext:3266-3290; 3277).
- reset_type(2) is set from core load until the first soft reset (zxnext:1299, 1695). Her Next reads NR 02 = 01 at first launch (readings sitting2), so it's clear in practice.
- Port 0xEB (A7:0): no access unless 0xE7 = 0xFF. Includes DMA to/from EB, and INIR/OTIR with C = EB.
- esxDOS / NextZXOS calls that write: RST $08 F_OPEN/F_WRITE/F_UNLINK, M_P3DOS writes. Also the BASIC loader: SAVE, ERASE, dot commands.

## Reboots and resets (more than a hang)
- NR 0x02 b1 = hard reset, which reloads core slot 1 (zxnext:6278; top4:1066-1080).
- NR 0x02 b0 = soft reset. b3/b2 = MF/divMMC NMI (approved). b7 holds the expansion bus and ESP in reset; it must be cleared.
- NR 0x10 b7 = start selected core, from anywhere (zxnext:5635-5640). The core ID can only change in config mode: then a different flash slot boots.
- **The copper can write NR 0x00-0x7F** (zxnext:4672), so 0x02, 0x03, 0x04 and 0x10 are all in reach. Check the register byte of every MOVE, and WAIT/MOVE encoding slips.

## Config mode
- **NR 0x03 with bits 2:0 = 111 enters config mode from anywhere.** Writing 000 changes nothing (zxnext:5084-5089). nextreg.txt says 000; the VHDL says 111.
- In config mode:
  - 0xE7 = 0x7F reaches the flash;
  - NR 0x10 can retarget the core;
  - NR 0x04 maps any 16K SRAM bank at 0-3FFF writable. That's RAM (ROM images, divMMC, OS state), so it's corrupt-until-reboot, not hardware;
  - NR 0x03 machine type and NR 0x0A b7:6 become writable. Harmless.
- Leave config mode with NR 0x03 bits 2:0 = 001..100.

## Other things to flag
- UART to the ESP (ports 0x133B/0x143B/0x153B): AT commands can change the ESP's *persistent* settings.
- NR 0xA8/0xA9 (ESP GPIO0) combined with an ESP reset puts the ESP in download mode.
- Pi GPIO (NR 0x90-0x9B, 0xA0): if a Pi is fitted, the pins can fight it.
- NR 0xF0, 0xF8-0xFA (XDEV / XADC DRP, CPU only): DRP writes could set the over-temperature shutdown, which deconfigures the FPGA.
- NMI menus (esxDOS / Multiface): the screen should tell whoever runs it which key to press, and not to choose save.

## Added for PCF and PNM (Rustyback, after Tally passed on Hart's-tongue's plan)

**Config mode, for PCF.** All cites are 3.02.02 zxnext.
- **0x0000-0x3FFF changes underneath.** With MMU0/1 on ROM (0xFF), config mode maps 0x0000-0x3FFF to SRAM bank NR 0x04, and it's **writable** (zxnext:3002-3008). Bank 0 after boot is the ROM image area. Every rule below follows from that:
  - DI for the whole time in config mode. An IM1 interrupt would run RST 38 from that bank, not from the current ROM.
  - No ROM calls (RST 10, CALL into ROM) until config mode is left.
  - Code and stack above 0x4000.
  - Nothing written below 0x4000. That would corrupt the loaded ROM image until the next boot: no hardware harm, but more than a hang.
- **The soft-reset key does nothing in config mode** (zxnext:6277: `hotkey_soft_reset and not nr_03_config_mode`). If PCF sticks in config mode, a short press of reset won't help; only a hard reset will (a long press, or F1 on PS/2). **The README's "stuck" section must say this.**
- **Leaving config mode:** write NR 0x03 with bits 2:0 set to the machine type read at the start (001-100), and with **b7 = 0 and b3 = 0**.
  - b7 = 1 would change the display timing.
  - b3 *toggles* the user display-timing lock on every write (zxnext:5074: `xor nr_wr_dat(3)`).
  - A machine type different from the start one changes ROM selection and contention.
- NR 0x03 = 000 changes nothing, and in config mode it doesn't change the machine type either (zxnext:5076-5089), so the "000" half of PCF is safe.

**The copper's MOVE 02,00, for PNM.**
- **Safe.** b1 = b0 = 0, so no reset; b3 = b2 = 0, so no NMI is generated (zxnext:3771-3774).
- **By the VHDL, it does clear the NMI flags b3/b2,** although nextreg.txt says "Copper cannot clear these bits".
  - `nr_02_we` is decoded from `nr_wr_reg`, which is the copper's register while the copper writes (zxnext:4716-4717, 4779).
  - The clear branches only test `nr_02_we and nr_wr_dat(n) = '0'` (zxnext:3788-3789, 3801-3802).
  - So the doc and the VHDL disagree, which is presumably what PNM is for. It isn't a safety matter.
- **NMI bits with NMIs disabled:** a flag is only set while `nmi_accept_cause` is high (zxnext:2123, 3786, 3799).

## Reviews

**PNM and PCF: passed** (Rustyback, Fri 06 Nov 2026 18:14 PST by `date`). Sources read whole: pnm.asm, pcf.asm, probe.inc, beep.inc.

What I checked, and what I found:
- **The TAPs match their sources.** I reassembled both in scratch, and they match build/Pnm.TAP and build/Pcf.TAP byte for byte. The loader is line 10, `CLEAR 32767 : LOAD "" CODE : RANDOMIZE USR 32768`.
- **No hidden port or NEXTREG writes.** The only raw port op on the SPI ports is `main`'s `ld a,FF : out (E7),a` at 0x8349. There are no NEXTREG opcodes. Nextregs go only through nrwr/nrrd (0x243B/0x253B). beep.inc touches only port 0xFE and NR 0x07, which it puts back.
- **No dangerous registers.** No NR 0x10. NR 0x04 only in PCF, as 0x30. NR 0x03 is written only as 00, 07 and her type, always with b7 = 0 and b3 = 0. Every NR 0x02 write (08, 04, 00, and the closing 01 soft reset) has b7 = 0 and b1 = 0.
- **The copper list is what it says.** The first byte written goes to the MSB in both write modes (zxnext:3918-3919, 3939, 5357-5362). So `02 00` is MOVE 0x02,0x00 and `FF FF` halts.
- **No pending NMI can survive.** The NMI pulse reaches only the NR 0x06-gated asserts and the flags (zxnext:2049-2050, 3773-3779). The flags feed nothing but the read-back (zxnext:5798).
- **NR 0x06 is put back exactly.** It reads in its write format, and its PS/2 bit can only be written in config mode (zxnext:5100-5110, 5806-5807).
- **PCF can't get stuck in config mode through the NMI.** NMIs are held off entirely there (zxnext:2063-2066, 2110-2112).
- **PCF's exit is safe.** A soft reset left in config mode would re-enable the boot ROM (zxnext:5048-5050), which is reads only. But PCF leaves config mode first, and any type other than 000 or 111 leaves it unconditionally.
- **PCF's expected result is right.** MMU page 0x40 is SRAM bank 0x30 (zxnext:2923), so A5 5A is the correct expectation.

Nits, not blockers:
- Both tapes deselect (E7 = FF) *before* the warning screen, though the notes say after. Deselecting is the safe state, so I'd fix the words, not the code.
- **For reading PCF's result:** if `NR 03 = 07` shows neither A5 5A nor the ROM bytes, suspect port 0xE3 conmem or a layer 2 map first. Both can override the config window (override "110", zxnext:3008).
- **For the README:** carry each tape's "Stuck looks like" line into the tape folder's table row.

## The ESP and the Pi, for D-6 and D-20 (Rustyback, after Tally's bounds)

**Tally's bounds (Melissa O'Neill has both):**
- Nothing may change the ESP's or the Pi's own firmware or settings.
- The ESP gets read-only AT commands only: `AT`, `AT+GMR`, perhaps a status query. No network joins, no credentials, nothing stored.
- The Pi is listened to over the UART only, with a bare newline at most. No shell commands, and nothing that writes its card.

All cites are 3.02.02 zxnext.vhd, plus ports.txt.

### The UART ports
These four ports are decoded on A15-A11 = 00010 with low byte 3B, and only while NR 0x82-0x85 enable them (zxnext:2598).
- **0x133B:** write = Tx byte; read = status.
- **0x143B:** read = Rx byte; write = the prescaler's low 14 bits, 7 bits at a time.
- **0x153B:** b6 selects the UART (0 = ESP, 1 = Pi); b4 with b2:0 sets the prescaler's MSBs.
- **0x163B:** the frame: b7 resets the FIFOs, **b6 asserts break**, **b5 turns on hardware flow control**.

The rule for both devices: **trace every byte written to 0x133B back to a constant table in the source**, noting which UART 0x153B b6 selects at that moment. Nothing computed, nothing from a buffer, no loop that could run past its table.

### ESP (UART 0, on its own pins, so the risk is settings, not electrics)
- **Exact strings only:** `AT\r\n`, `AT+GMR\r\n`, and at most a status query such as `AT+CIPSTATUS\r\n`.
  - Nothing containing `=` (every setter).
  - None of AT+RST, AT+RESTORE (a factory reset), AT+UART*, AT+CW*, AT+CIP*/STA*/AP* setters, AT+CIUPDATE (a network firmware update), AT+SYSFLASH, AT+SLEEP/GSLP or AT+SAVETRANSLINK.
  - On old ESP8266 AT firmware, the plain AT+CWMODE/CWJAP/UART setters *store to flash*, so whitelist; never blacklist.
- **Keep her network off the photos:** no `AT+CWJAP?` (it prints her SSID) and no `AT+CIFSR` (her IP and MAC).
- **D-6 deliberately runs at a mis-set baud** (a 27 MHz vs 28 MHz prescaler, about 3.7% off). At the wrong rate, send only `AT\r\n`, the shortest string, which garbling can't turn into anything else.
- **No ESP reset or boot-mode change:** no NR 0x02 b7 (holds the ESP and the expansion bus in reset); no NR 0xA8/0xA9 (ESP GPIO0: held low across a reset, it puts the ESP in its flash-download mode).
- **Put the UART back:** frame 0x18 (8N1, the hard-reset value), select ESP (0x153B b6 = 0, also the soft-reset value), prescaler for 115200.

### Pi (UART 1, on the shared header: electrical risks as well as software)
- **NR 0xA0: only 0x00, 0x20 or 0x30. Never b4 without b5.** With b4 = 1, the FPGA's Tx goes to GPIO 14 when b5 = 0 and to GPIO 15 when b5 = 1 (zxnext:2279-2293; the code's own comment is "need to cross wires for pi!").
  - The Pi's GPIO 14 is its TXD *output*, so **0x10 puts two outputs on one pin.** The fight happens whenever the Pi transmits while the Next idles high, and the other way round.
  - 0x30 is the right, crossed orientation for a Pi.
  - 0x20 (the doc's "enable") leaves the UART off in the VHDL, which is harmless.
- **NR 0xA0 b0 (the SPI master) never.** It drives GPIO 7, 8, 10 and 11 (zxnext:2251-2266). b3 (I2C) is open-drain, so electrically safe, but it's out of scope: leave it.
- **No hardware flow control on the Pi UART** (0x163B b5 while 0x153B b6 = 1). It drives GPIO 16 or 17 (zxnext:2284-2290).
- **NR 0x90-0x93 (GPIO output enables): never written nonzero.** Each set bit drives that header pin. NR 0x98-0x9B are harmless only while the enables are 0, so simplest is to leave both groups alone.
- **NR 0xA2 (I2S): leave alone.** b4 picks whether the FPGA drives GPIO 20 or 21 (zxnext:2301-2307), and the Pi may drive either.
- **No break on the Pi UART (0x163B b6).** On a Linux serial console, a break followed by a key is a magic SysRq: `b` reboots, `c` crashes, `u` remounts.
- **Tx to the Pi: at most one 0x0D or 0x0A, and nothing else.** In particular no 0x03 or 0x04 (Ctrl-C/D), and no printable bytes that a shell could take as a command.
- **Its card:** only listening, so nothing in the tape can write it. But a stray command could, which is why the Tx rule above is strict.

### Also for both
- **NR 0x0B (joystick I/O mode): leave alone.** It can route a UART or pin 7 out onto the joystick connector (zxnext:1586-1587, 3494). With a joystick plugged in, that drives a pin its switches short to ground.
- A soft reset at the end puts the UART select back to ESP, but not the prescaler or frame, which are hard reset only. So the tape restores those itself.

**PUA (D-6): passed** (Rustyback, Fri 06 Nov 2026 18:36 PST by `date`). Source read whole.

What I checked, and what I found:
- **The TAP matches its source:** reassembled, it matches build/Pua.TAP byte for byte (2083 bytes).
- **Every OUT is accounted for:**
  - exactly one write to 0x133B (0x83BE, the `tx1` loop), four bytes from `s_at` = `41 54 0D 0A`;
  - 0x143B only for the prescaler halves;
  - 0x153B only as 0x10, then (saved & 0x40);
  - 0x163B only as 0x98 then 0x18: no break, no flow control.
- **No block OUTs, no NEXTREG opcodes,** and the one raw port op is the deselect (E7 = FF).
- **Skips:** if NR 0x02 b7 holds the ESP in reset, or if NR 0x0B b7+b5 has a UART on the joystick port.
- **The uart.vhd claims hold:** the power-on prescaler is 243 (uart.vhd:319-320), and FIFO reset is a level from frame bit 7 (uart.vhd:385).
- **The expected centre is right for her:** it's Fsys/115200 with Fsys from NR 0x11, and the test machine read NR 0x11 = 00 (readings-2026-11-06.md:9), so 243.

Notes, not blockers:
- **rxread's OK search stops at a NUL.** A mis-clocked frame can be 0x00, which could turn a window-edge `*` into `-`. Searching by the count in D would avoid that.
- **The ESP must be in command mode.** If a program had left it in transparent mode, AT would go out over the open connection. A power-on before running PUA guarantees command mode, and 115200 too.
- **Worth a line in NOTES:** the centre scales with NR 0x11 (0: 243, 1: 248, 2: 256, 3: 260). Settings 4-6 would land past 264.

**D-20, on paper: agreed.** The two readings put the FPGA's Tx on GPIO 14 for different values:
- nextreg.txt: 0x20;
- the VHDL and tbblue docs/rpi/linux/UART.txt: 0x10.

So the values that are safe under both, with the Pi on, are 0x00 and 0x30, and those route identically under both readings. No safe UART-routing test can decide it. With the Pi *removed*, 0x10 against 0x20 becomes safe and decisive: NR 0x99 reads GPIO 15:8 raw (zxnext:6086-6087), so while 0x00 bytes go out, the setting that drives GPIO 14 shows it low. That needs the case opened and the Pi taken off. It's for Melissa O'Neill to offer, not for us to ask.

**A miss of mine, for the record** (Fri 06 Nov 2026 19:07 PST by `date`). I passed PUA twice and didn't see that its "reply at 243" capture can never fire. The sweep visits only even prescalers (222 + 2n), and the capture tests for exactly 243. Hart's-tongue found it from the photo. It was harmless (a display line), but it was the kind of thing a second reader is for.

**New item for every review:** for each branch that tests a loop variable against a constant, check that the loop can actually reach that value (step, start, end, parity). Likewise check that every displayed field is written on some path that runs.

**New item, for NEX files:** check the header's fields (banks, PC/SP, preserve-registers byte 134, file handle 140-141, entry bank 139), not just the code. And check every claim a README makes about a film or a measurement against its numbers.

**PFB (Speccy-Zone's floating bus against contention): passed** (Rustyback, Sat 07 Nov 2026 02:07 PST by `date`). Read whole, and reassembled: it matches build/Pfb.TAP byte for byte (code 1427).

What it writes, and how each comes back:
- **NR 0x07 = 0:** restored from s07 & 3.
- **NR 0x03 = 0x90:** b7 timing, 48K, b3 = 0, type 000. Restored as (s03 & 0x70) | 0x80, so the lock isn't touched and neither config mode nor the machine type can change.
- **NR 0x08:** only b2/b6 changed, restored exactly. It round-trips: b7 reads "not locked", and writing 1 only clears 0x7FFD's lock bit (zxnext:3612-3614).

Nothing dangerous: no E7/EB, no NR 0x02 but the soft reset. The OUT trace finds only 0x243B/0x253B and the border. I drafted the README row for Tally, saying the tape turns contention on itself for F-2 and F-3.

**New item:** when a tape writes back a register it read, check the bits whose read and write meanings differ (here NR 0x08 b7: read = "not locked", write = "unlock").
