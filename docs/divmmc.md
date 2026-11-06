# divMMC

omse-ai can fit a **divMMC**, the interface that puts an SD card on a Spectrum, and boot **esxDOS** from an SD-card image: dot commands, `.tapein` and `LOAD ""` from the card, the NMI browser. It's held to the hardware, not to what's convenient: what runs on omse-ai's divMMC should run on a real one, or on a Spectrum Next's. Each detail below says where it comes from.

```python
from speccy import Speccy
zx = Speccy()
zx.fit_divmmc('esxdos/ESXMMC.BIN', card='esx.img')   # power off, plug it in, power on: esxDOS boots
zx.wait_ready()
zx.dot('.ls')                                        # the card's root, on the screen
zx.dot('.tapein game.tap')
zx.type('LOAD ""\n')                                 # from the card, through esxDOS's tape emulation
```

## Getting esxDOS and making a card

**esxDOS isn't included.** It's free to download from [esxdos.org](http://www.esxdos.org/) (`esxdos089.zip`, 0.8.9, April 2021); no licence is stated, so it isn't redistributed here. Inside, `ESXMMC.BIN` is the divMMC's 8K EEPROM image, and the `SYS`, `BIN` and `TMP` folders go on the card. The sha256 of the copy these tests were run with: zip `d455888361cd13d455e362a4c841452b6f4568d30f9069443044affdd40de9a4`, `ESXMMC.BIN` `89706de560d66432fe19ddb895e7cde49e252e932687dcb57fb92259a0259339`.

**A card is an image file of 512-byte sectors**: a FAT16 or FAT32 filesystem, with or without a partition table, as on a real card. `tools/mkfat.py` builds one from a folder, deterministically, in plain Python, and reads it back (`ls`, `cat`, `check`):

```bash
mkdir card && cp -R esxdos/SYS esxdos/BIN esxdos/TMP card/ && cp game.tap card/GAME.TAP
python3 tools/mkfat.py build esx.img card              # 64 MiB: MBR, one FAT16 partition at sector 2048
python3 tools/mkfat.py ls esx.img
```

Names must be 8.3 (esxDOS 0.8.9 reads no long names). The image is what a real card holds, so `dd` it onto one, or copy the same folder onto a card formatted FAT16 or FAT32, and the real machine sees the same files.

## Driving it

- `fit_divmmc(eeprom, card=None, writable=False, ram_kb=128, write_protect=True)` fits one and power-cycles, as fitting a real one takes. `eeprom` is the 8K image (path or bytes; `None` is a blank EEPROM, all FF). `write_protect` is the EEPROM's jumper: on, as in use.
- `sd_insert(path, writable=False)` and `sd_eject()`. **A card that isn't writable still takes writes, into memory**, so a program can write to the card while the image file stays as it was; `writable=True` writes the file.
- `dot('.ls')` types a dot command and waits for esxDOS to finish it (`type()`, then `wait_ready()`).
- **Breakpoints at ROM addresses can land in divMMC's code.** While divMMC is mapped, `0000`-`3FFF` is its EEPROM and RAM, and esxDOS has code at the very address of the ROM editor's key-wait loop. `wait_ready()` and `type()` know this and ignore a stop there while divMMC is mapped (`divmmc_mapped()`); a `run_until()` of your own should check too.
- `nmi()` presses the divMMC's NMI button: esxDOS's browser.
- `sd_log()`: every command the card has had, as `('CMD17', argument, R1)`; R1 is `None` for a command the card ignored.
- `divmmc_state()`: port E3 (CONMEM, MAPRAM, the bank), the automap latch, what's mapped where and whether it can be written, the card selects.
- `divmmc_ram(bank)` and `divmmc_eeprom()`: the 8K pages.
- `sd_timing(ncr=1, nac=1, busy=2, init_tries=2)`: the card's delays (below).
- `tape_traps(False)` turns off omse-ai's own tape deck, so esxDOS's tape emulation sees every LOAD and SAVE (see "omse-ai's tape deck", below).

## The interface, as the hardware does it

The sources: **Fuse** (`peripherals/ide/divxxx.c`, `divmmc.c`, the automap in `z80/z80_ops.c`) and **libspectrum**'s `mmc.c`; the **ZX Spectrum Next**'s FPGA core (`device/divmmc.vhd`, `serial/spi_master.vhd`); the **ZX-Uno**'s core (`common/spi.v`); the **SD Association's Physical Layer Simplified Specification**, SPI mode, and **ChaN**'s ["How to Use MMC/SDC"](http://elm-chan.org/docs/mmc/mmc_e.html). The emulators' and cores' source is GPL and was read, not copied: everything here is written fresh.

**Ports**, decoded on the address's low byte only:

- **`E3`**, write-only, the control register. Bit 7 is CONMEM, bit 6 MAPRAM, bits 0-5 the RAM bank paged at `2000`-`3FFF`, as many bits as the RAM needs (128K is 16 banks: bits 0-3). **MAPRAM can be set but never cleared**, except by switching off: a power cycle clears the register.
- **`E7`**, card select: bit 0 is card 0, active low (write `FE` to select it, `FF` for none). Only card 0 has a slot here.
- **`EB`**, SPI data.

**What's mapped**, at `0000`-`3FFF` (Fuse's `divxxx_refresh_page_state` and `divxxx_memory_map`):

- **CONMEM set:** always mapped. The EEPROM at `0000`, writable only with the write-protect jumper off; the selected bank at `2000`, writable.
- **Otherwise, while automapped**, and only if the EEPROM is write-protected or MAPRAM is set (the jumper that lets you rewrite the EEPROM also stops automapping):
  - **MAPRAM:** RAM bank 3 at `0000`, read-only (esxDOS copies itself there); the selected bank at `2000`, read-only too if it's bank 3.
  - **No MAPRAM:** the EEPROM at `0000`, read-only; the bank at `2000`, writable.

**Automap**, on opcode fetches (M1) only, so data reads of these addresses don't count:

- **`0000`, `0008`, `0038`, `0066`, `04C6`, `0562`** map divMMC in **after** the fetch: the opcode comes from the ROM, everything after it from divMMC. That includes the rest of the same instruction: at `0008` the ROM's `LD HL,(CH_ADD)` gets its address bytes from the EEPROM, which is why esxDOS's EEPROM holds the same bytes there.
- **`3D00`-`3DFF`** maps it in **instantly**: that fetch already reads divMMC (it's the bank at `2000` there). TR-DOS programs jump to `3D00`.
- **`1FF8`-`1FFF`**, the off-area, maps it out after the fetch, so the instruction there is the last one read from divMMC.
- The Next does this with two latches: the new state is worked out during the M1 cycle and takes effect when MREQ goes high again. Every M1 counts, prefix bytes included; the Z80 core asserts M1 on those too. (Fuse looks at an instruction's first byte only.)
- **An interrupt while divMMC is mapped runs divMMC's own `0038`**: it's already mapped, so the fetch at `0038` reads it. Real esxDOS is written for this; code of your own that maps with CONMEM should run with interrupts off, as the Next's issue tracker also warns.

**SPI, the detail that's easy to get wrong.** Both an OUT and an IN on port `EB` start an 8-bit transfer: an OUT sends its byte, an IN sends `FF`. But **an IN returns the byte received during the *previous* transfer**, not the one it starts: in the Next's `spi_master.vhd`, the byte the CPU reads (`miso_dat`) is only updated at the end of a transfer; in the ZX-Uno's `spi.v`, a read hands the CPU `data_from_spi`, collected during the last transfer, as it starts the next. So reading lags by one. Fuse returns the card's next byte at once and clocks nothing on an IN, which is kinder than the hardware: software that forgets the lag works in Fuse and fails on the real thing. omse-ai does what the hardware does.

**On a Spectrum Next, SPI accesses need room.** The Next's SPI master (`spi_master.vhd`, by Alvin Albrecht and Fabio Belavenuto) takes 16 of the CPU's clocks for a transfer, and says reads and writes "must be separated by 16 cycles". An access that comes sooner starts nothing (an OUT's byte is never sent) and reads the same byte as the access before it: the read register loads the clock after a transfer's last state, so a byte reaches the CPU only from 16 clocks on. (Ratio Fern, another instance of Fern, modelled `spi_master.vhd` edge by edge for omse-ai's Next and showed this one clock sooner than an earlier version here.) Tally, another instance of Fern, found it on Melissa's real Next: a CRC-skipping IN 15 T after the last INI was ignored, and a sector slipped 2 bytes whenever its second CRC byte was FE. `spi_gap(16)` makes omse-ai's divMMC behave like the Next's (the clocks are the CPU's own, which stop while the ULA holds it), and `spi_early` counts the accesses that came too soon. The default, 0, is the classic divMMC, which has no such limit at 3.5 MHz.

## The card

A card in SPI mode, full duplex: one byte in and one byte out per transfer (`src/sdcard.h`). Where the spec gives a range, omse-ai picks a strict but real point in it, and you can move it with `sd_timing()`. It's one of four kinds, chosen with `kind=` when it's inserted, because drivers meet all four and must treat them differently:

| kind | what | addresses | how it starts |
|---|---|---|---|
| `sdhc` (default) | SD 2.0, high capacity | blocks; CCS set in the OCR; CSD version 2.0 | CMD8, then ACMD41 with HCS (CMD1 never) |
| `sdsc` | SD 2.0, standard capacity, 2 GB at most | bytes; CCS clear; CSD version 1.0 | CMD8, then ACMD41 (or CMD1) |
| `sdv1` | SD 1.x | bytes | ACMD41 or CMD1; CMD8 is an illegal command |
| `mmc` | MultiMediaCard | bytes; CSD version 1.2 | CMD1; CMD8 and CMD55 are illegal |

On the byte-addressed cards, CMD16 sets the block length (1 to 512; reads of less than a block are allowed, but a read mustn't cross a 512-byte block, and writes are whole aligned blocks). Their CSDs say 512-byte blocks up to 1 GB and 1024-byte ones above, as real cards do. esxDOS 0.8.9 boots from all four, and its driver shows in `sd_log()`: SDHC needs no CMD16; on an SDSC card it sends CMD16 when it sees CCS clear; an SD 1.x card or an MMC refuses CMD8, and esxDOS falls back to CMD1.

- **It wakes up only after 74 clocks with MOSI high** (ten bytes of `FF`), then listens only for CMD0, which puts it in SPI mode when it arrives with CS low.
- **CMD0 and CMD8 must carry a correct CRC7**, as in the spec; a wrong one gets R1 with the CRC-error bit, and isn't obeyed. Other commands' CRCs are checked only after CMD59 turns CRCs on.
- **A response comes N_CR bytes after the command** (the spec allows 0 to 8 for SD cards; default 1), so software has to poll for it. A data block comes N_AC bytes after its R1 (default 3, and a CSD or CID block straight after it: what a 32 GB Samsung SDHC card does on Melissa's real divMMC, measured with the SDPROBE tape, which also confirmed the one-transfer read lag), with its start token `FE` and a real CRC16. A write is answered with its data response token (`05`: accepted) and then busy, MISO held low (default 2 bytes of `00`).
- **It takes its time to initialise:** ACMD41 answers "still idle" the first time (`init_tries`, default 2), so a driver must loop, as on a real card. An SDHC card leaves idle only if CMD8 came first and ACMD41's HCS bit is set; CMD1 alone never initialises it.
- **While it's initialising, only CMD0, 1, 8, 55, 58 and 59 and ACMD41 are legal**; anything else gets R1 `05` (idle, illegal command).
- **CMD12 stops a multiple-block read with a stuff byte, then R1b.** The spec says to discard the stuff byte and doesn't define it; omse-ai sends the next byte of the block it interrupted, as a real card in mid-block does, so a driver that mistakes it for R1 can be caught here.
- Commands: CMD0, 1, 8, 9 (the CSD), 10 (CID: maker `OA`, product `omseS`, which esxDOS shows as `sda: OA omseS`), 12, 13, 16, 17, 18, 24, 25, 55, 58, 59; ACMD13, 22, 23, 41, 42, 51. Anything else gets the illegal-command bit.

esxDOS 0.8.9 initialises with CMD0, CMD8 (`1AA`), CMD55 and ACMD41 with HCS (twice: it loops while the card is idle), CMD9, CMD10, CMD58, and then reads with CMD17.

## omse-ai's tape deck

omse-ai serves LOAD and SAVE instantly by trapping the ROM's LD-BYTES (at `0562`) and SA-BYTES (at `04C2`). Both are near divMMC's entry points (`0562` and `04C6`), so they're decided like this:

- omse-ai's traps fire only while the ROM is mapped, never while divMMC is.
- **With a tape in omse-ai's deck, LOAD is served from it**, and that fetch at `0562` doesn't automap, because the trap jumps straight past the code there. With the deck empty, LOAD reaches `0562`, divMMC maps in, and esxDOS's tape emulation (`.tapein`) takes it.
- **SAVE is always caught by omse-ai's deck**, at `04C2`, before `04C6`, so `.tapeout` sees nothing. To try esxDOS's tape emulation on SAVE (or on LOAD with a tape in the deck), turn omse-ai's traps off: `tape_traps(False)`. Then LOAD and SAVE run as on a real machine.

## How it's checked

`tests/test_divmmc.py` holds every point above with real OUT and IN instructions. A small test EEPROM of its own hands each automap back to the ROM, and the SPI tests are straight-line Z80 that Python writes, one OUT or IN at a time, so every byte on the wire is visible. Before they were trusted, each was broken on purpose. Thirty mutants of the code (the IN returning this transfer's byte, entry points mapping before their fetch, `3D00` mapping after it, MAPRAM clearable, bank 3 writable, the jumper ignored, the off-area narrowed, bank bits dropped, no N_CR, no CRC check, no wake-up clocks, reads while idle, ACMD41 at once, a wrong CRC16, a read-only card writing its file, CMD12 without its stuff byte or busy, the stuff byte `FF`, and for the card kinds: CCS on every kind, block addresses everywhere, reads crossing blocks, CMD16 ignored, CMD8 on a 1.x card, CMD55 on an MMC, CMD1 starting an SDHC card, the CSD's size off by one, no 2 GB limit, writes ignoring the block length) were each run in a copy of the tree. Twenty-nine failed a test. The thirtieth adds a delayed map at `3D00` beside the instant one, which changes nothing, so no test can see it.

With `$OMSE_AI_ESXDOS` naming an esxDOS folder (holding `ESXMMC.BIN`, `SYS` and `BIN`), the tests also build a card with `tools/mkfat.py` and boot esxDOS from it.

## Limits

- **Snapshots don't hold the divMMC.** SNA has no room for it, so loading one power-cycles the interface (its RAM is kept), and a `go` session doesn't carry esxDOS's state between calls. Keep a divMMC session in one Python process.
- **One card.** No second slot, and no write-protect or card-detect switches. No SDXC either (it's SDHC to a driver in SPI mode, up to 2 TB).
- **SPI transfers take no time.** A real one takes a few T-states, always done before the next IN or OUT can arrive.
- **No divIDE**, and no Next extensions: it's the original divMMC, with 128K or 512K of RAM.
- The EEPROM can be rewritten with the write-protect jumper off (`write_protect=False`), as on the real thing, but esxDOS's own flashing tool hasn't been tried.

## Who made it

The divMMC, its card and its tests were built on the night of 4 to 5 November 2026 by Speccy-Zone, an instance of Fern (an AI agent with a persistent memory of her own), at Melissa O'Neill's invitation. `tools/mkfat.py` is the work of Loam, another instance of Fern, the same night, to Speccy-Zone's brief. For this work they inhabited Claude Opus 5.5. Melissa asked for it, set the bar (what runs here should run on her real divMMC and her Spectrum Next), and takes responsibility for it.
