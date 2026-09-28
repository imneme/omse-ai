# The omse-ai manual

omse-ai is a ZX Spectrum 48K and 128K with no window, no speaker and no keyboard. You drive it from a script or from Python, and it tells you what happened: as text, as numbers, and as pictures and sound files you can open later. This manual covers everything; README.md is the short version, and AGENTS.md has the rules that matter most if you're an agent driving it.

Contents: [Running it](#running-it) · [Settings](#settings) · [Script steps](#script-steps) · [Python](#python) · [Adding your own steps](#adding-your-own-steps) · [How typing works](#how-typing-works) · [What fights you](#what-fights-you) · [Seeing](#seeing) · [Hearing](#hearing) · [Tapes and snapshots](#tapes-and-snapshots) · [The 128](#the-128) · [Spectrum BASIC, learned the hard way](#spectrum-basic-learned-the-hard-way) · [Machine code](#machine-code) · [Optional tools](#optional-tools) · [The core](#the-core) · [Limits](#limits)

## Running it

```bash
./speccy.py run examples/hello.zx              # a script -> out/hello/
./speccy.py do 'enter 10 PRINT "hi"' 'enter RUN' 'ready' 'screen'   # steps as arguments -> out/do/
./speccy.py go NAME 'step' 'step' ...          # a machine that persists between calls: snaps/NAME.sna
./speccy.py bas prog.bas [frames]              # .bas -> TAP -> LOAD -> RUN -> contact sheet (needs speccy-basic)
./speccy.py tap file.tap [frames]              # LOAD "" a tape, contact sheet of what happens
./speccy.py look file.sna [frames]             # run a snapshot, contact sheet
./speccy.py help                               # every step
./zxdis.py 15D4 1601                           # disassemble the ROM (or a file); needs tzxtools
```

The machine runs at about 2,200 frames a second on a laptop, or 44 times real time. A contact sheet of 20 seconds of play takes about half a second to make.

Everything a script writes goes in `out/<script name>/`, under the current directory (or under `--dir`). `go` keeps its machines in `snaps/`.

### `go`: run a bit, look, carry on later

```
$ ./speccy.py go demo 'enter 10 BORDER 2: PAUSE 0'
[demo] 126 frames (2.5s) pc=15df mode=K border=7 -> out/demo/now.png
$ ./speccy.py go demo 'enter RUN' 'wait 20'             # later, in another call
loaded snaps/demo.sna
[demo] 162 frames (3.2s) pc=1f3e mode=L border=2 -> out/demo/now.png
```

Each call loads `snaps/NAME.sna` (or boots a fresh 48K), runs the steps, saves the machine back, writes `out/NAME/now.png` and prints that status line: frames so far, the program counter, the editor's cursor mode and the border colour. With a tape, `go game 'tape game.tap' 'enter LOAD ""' 'wait 100'` in one call and `go game 'key SPACE' 'wait 100'` in the next works the same way.

A `.json` file next to the snapshot remembers which tape is in the deck and how far it has been read. Delete both files to start again. Snapshot round trips are exact: a machine reloaded from a snapshot does precisely what it would have done without stopping (the tests check this).

This is the natural way for an agent to explore a program: one tool call per move, a picture and a status line after each.

## Settings

| Setting | What | Default |
|---|---|---|
| `OMSE_AI_ROMS` or `--roms DIR` | the folder holding `48.rom`, `128-0.rom`, `128-1.rom` | `roms/` in this repository |
| `--dir DIR` | where `out/` and `snaps/` go | the current directory |
| `--steps FILE.py` or `OMSE_AI_STEPS` | extra steps (below); `OMSE_AI_STEPS` is a list of files separated like `PATH` | none |
| `PASMO` | the pasmo assembler, for the `asm` step | `pasmo` on the `PATH` |

Options go before the command: `./speccy.py --dir ~/work --roms ~/roms run game.zx`.

The ROMs aren't included; `roms/README.md` says where to get them and how to check them. A missing ROM, or a file that isn't one (a failed download is usually a web page), gets a message saying so and what to do, rather than a crash.

## Script steps

One step per line. `#` starts a comment. Frame counts take seconds too (`wait 2s`; the Spectrum shows 50 frames a second). Paths may use `~` and `$VARIABLES`, and `$OUT` is the script's own output folder, so a script can reload what it saved: `load $OUT/game.tap`.

| Step | What |
|---|---|
| `boot` / `sna PATH` / `save NAME` | a fresh 48K (at the © screen) / load a snapshot, 48K or 128K / snapshot now (the machine carries on) |
| `boot128` / `menu tape\|128\|calc\|48\|tester` | a fresh Spectrum 128 at its menu / choose from the menu (`tape` is Tape Loader, which LOADs "" whatever is in the deck) |
| `ay` / `roll NAME [px/s]` / `aywav NAME` | (128) record the AY / a piano roll `.png` and a note list `.txt` / a WAV |
| `wait N` | run N frames |
| `ready [N]` | run until the ROM wants the keyboard: the editor after a command, or INPUT |
| `until ADDR [N]` | run until an opcode fetch at ADDR, in hex (`15DE` or `0x15DE`), for at most N frames |
| `enter TEXT` | **type TEXT, keywords the Spectrum way, then ENTER**: a program line or a direct command |
| `type TEXT` / `text TEXT` | type without ENTER / type literally, with no keywords (answers to INPUT) |
| `basic PATH.bas` | type a whole program in, line by line (speccy-basic numbers and delabels it first) |
| `lint PATH.bas [min]` | **the ROM as linter**: type every line into a fresh 48K and list each one it rejects, with its own `?` marker. `min` renames variables first (speccy-basic's `--minimize`) |
| `key CHORD` | one keystroke the ROM will notice: `key ENTER`, `key SS+P`, `key BREAK`, `key LEFT` |
| `hold CHORD N` / `press CHORD` / `release [CHORD]` | hold keys for N frames, the way games want them: `hold 9 48`, `hold Q+P 20` |
| `joy RLDUF [N]` | Kempston joystick: the letters of the directions held, `F` for fire |
| `tape PATH` / `load [PATH]` / `tapbas PATH.bas` | put a TAP in the deck / (insert it and) `LOAD ""` / a .bas made into a TAP in memory, then `LOAD ""` |
| `asm PATH.asm [code]` | assemble with pasmo into `out/NAME.tap` with a BASIC loader (or a bare CODE block), put in the deck; `load` runs it |
| `savetape NAME` | write what the program has SAVEd as a .tap |
| `shot NAME [noborder] [xN]` | a PNG of the screen (2× unless `xN`) |
| `every N` / `grab [LABEL]` / `sheet NAME [cols] [title]` | collect a frame every N frames while running / collect this one / write them as a contact sheet (`.png` and a `_960.jpg` preview) |
| `gif NAME [fps] [scale]` | the collected frames as an animated GIF in the Spectrum's 16 colours (`every 2` gives 25 fps) |
| `screen` | the screen **as text**: every 8×8 cell matched against the current font, the UDGs and the block graphics |
| `printed` | what the ROM has PRINTed to the main screen since last asked (keywords spelled out) |
| `audio` / `notes [NAME]` / `wav NAME` | record the beeper / print what it played as notes (start, length, Hz, nearest note and cents; `NAME.txt` too if named) / write it as a WAV. A recording lasts until the process ends, so in a `go` session, record and read it in the same call |
| `peek ADDR [N]` / `poke ADDR V` / `regs` | memory (ADDR in decimal, or hex written `0x5800`) and the Z80's registers |
| `say TEXT` | print a note to yourself |

Chord names are the letters and digits, `ENTER`, `SPACE`, `CS` (CAPS SHIFT) and `SS` (SYMBOL SHIFT), joined with `+` or spaces, and the named keys of the real keyboard: `BREAK DELETE EDIT CAPSLOCK TRUEVIDEO INVVIDEO LEFT DOWN UP RIGHT GRAPHICS EXTEND`.

`./speccy.py help` prints every step with its details.

## Python

```python
import sys; sys.path.insert(0, '/path/to/omse-ai')
from speccy import Speccy, contact_sheet
import zxay

zx = Speccy()                          # boots a 48K; Speccy(model=128), Speccy(sna='x.sna')
zx.type('10 PRINT "HELLO"\n')          # raises ZXSyntaxError if the ROM refuses the line
zx.type('RUN\n'); zx.wait_ready()      # until the editor wants a key again
print(zx.screen_text()); zx.shot('out/x.png')
print(zx.report())                     # '0 OK, 10:1'
zx.hold('9', 48)                       # games: hold keys for N frames
zx.every = 10; zx.run(500); contact_sheet(zx.frames, 'out/sheet', cols=5)
zx.peek(0x5800); zx.peek16(23627); zx.read(a, n); zx.poke(a, v); zx.mem[a]   # memory
zx.regs(); zx.mode(); zx.border         # registers; the cursor mode 'K' 'L' 'C' 'E' 'G'
zx.run_until(0x15DE, frames=50)        # breakpoints on opcode fetch; returns the PC or None
zx.record_audio(); ...; zx.beeper_notes()   # [(start_s, dur_s, Hz)]
zx.record_ay(); ...; zxay.ay_notes(zx) # (128) [(channel, start_s, dur_s, midi, volume)]
zx.insert_tape('x.tap'); zx.saved_tape(); zx.save_sna('x.sna')
```

`examples/tour.py` types a short program, runs it and reports what it did as text and numbers: the screen, the ROM's report, the notes the beeper played, a colour. It's a good place to start. For anything the script steps can do, `zxscript.Runner` runs a step from Python: `r = Runner('out/mine'); r.zx = zx; r.step('menu 48')`.

## Adding your own steps

A Python file of functions named `step_NAME(runner, arg)` adds the step `NAME` (underscores become hyphens). The function's docstring is its line in `help`. Load it with `--steps FILE.py`, or list it in `OMSE_AI_STEPS`.

```python
def step_border_is(runner, arg):
    """border-is N: stop the script unless the border is colour N"""
    zx = runner.need()                  # the machine (booting one if there isn't one yet)
    assert zx.border == int(arg), f'border is {zx.border}'
```

`runner.path(arg)` resolves a path the way the built-in steps do (with `$OUT`), and `runner.out(name, '.png')` gives a file in the script's output folder. Steps like these are for things that belong to one setup rather than to the tool, such as driving software on the emulated machine that can't be distributed with it.

## How typing works

The 48K doesn't take letters; it takes **keys in a mode**. At the start of a statement the cursor is **K**, and `P` *is* PRINT. After that it's **L**, where `P` is p, `CS+P` is P, and `SS+P` is `"`. **E** mode (`CS+SS`) gives the functions printed in green above the keys (E mode, then `Q`, is SIN), and E mode then `SS+letter` gives the red ones below (BEEP, INK, CIRCLE…). **G** (`CS+9`) gives block graphics and UDGs. `type()` handles all of it:

- **Every table comes from the ROM itself**: MAIN-KEYS at `0x0205`, E-UNSHIFT `0x022C`, EXT-SHIFT `0x0246`, SYM-CODES `0x026A`, E-DIGITS `0x0284`, and the keyword spellings at TKN-TABLE `0x0095`. In K mode, a letter gives the token letter + `0xA5`. Nothing is transcribed by hand.
- **Your text is split into tokens.** Keywords only count in UPPERCASE and on word boundaries; `GOTO` and `GOSUB` become `GO TO` and `GO SUB`; nothing inside quotes or after REM is a keyword. Spaces next to keywords are dropped, because the ROM draws its own. UDGs are written `Ⓐ`..`Ⓤ` and block graphics `▘▝▀`… (speccy-basic's conventions); `£ © ↑` work too.
- **Keystrokes are chosen from the mode the ROM reports** (FLAGS bit 3, FLAGS2 bit 3 and MODE), and **every keystroke is closed-loop**. Before pressing a key, `type()` waits until the previous one has been consumed and one of the ROM's two KSTATE slots is free and doesn't hold this key. It holds the key until KSTATE shows it registered, then lets go.
- **After each line, the edit line in memory is compared byte for byte** with what was meant, before ENTER is pressed. If the ROM then refuses the line, you get `ZXSyntaxError`, with the ROM's own `?` marker quoted from the screen: `10 PRINT 1+?: CAT`.

A torture test of every keyword on the keyboard (`tests/torture.bas`: SIN, SCREEN$, DEF FN, OPEN #, LINE, VERIFY, FORMAT, `©`, `▛▀▜ⒶⒷ█`…) goes in with no errors. A 38-line game typed in takes about 65 Spectrum-seconds, or 1.5 seconds here.

## What fights you

**The mode is only true once the ROM has finished redrawing.** This is the most important one. After a key, the ROM reprints the whole edit line (ED-COPY, `0x111D`), and FLAGS bit 3, the K/L mode, is set only when it draws the cursor, at the end. TV_FLAG bit 3 is cleared at the *start* of the redraw (`0x1120`), so it isn't the signal. On a long line the redraw takes about 3 frames. Reading the mode mid-redraw typed a keyword where a letter belonged. The fix is `settle()`: run to a breakpoint at **WAIT-KEY1 (`0x15DE`)**, the top of the editor's key-wait loop, and accept it only when no key is pending and no redraw is due.

**The same key twice needs about 5 frames between.** A released key keeps its KSTATE slot for 5 interrupts, and pressing it again inside that window counts as a *repeat*, which the editor ignores for a while. That covers `LL`, and also `P` followed by `SS+P`, because the slot holds the main key and not the shift. It bites with SAVE: the ENTER that submitted `SAVE "x"` is still in a slot, so an immediate "press any key" ENTER is ignored. `key` and `type` wait on KSTATE. `hold` is blind, on purpose, for games.

**Program lines and direct commands behave differently after ENTER.** A numbered line goes into the program and the ROM lists it, so `type` waits for the editor. A direct command (`RUN`) may never come back, so ENTER returns after a few frames and you call `ready`. (Waiting for the editor after RUN once let a snake crash into a wall before the first picture was taken.)

**The ROM needs a key to SAVE**: "Start tape, then press any key." Send `key ENTER`.

**Games read the keyboard their own way.** Some only accept a key at certain moments: one classic game only takes S once its "PRESS S TO START" scroller is running, 12 seconds into the title screen. Some use CAPS SHIFT as a modifier, so `CS+5` does something different from `5`. And a program that replaces the ROM's interrupt routine never updates KSTATE, so `key` would wait for nothing: use `hold`.

**The report arrives a few frames after `ready`.** `ready` fires when the ROM starts waiting for a key, and `0 OK, …` is printed just after that. A `shot` taken straight away shows an empty bottom line. Put `wait 50` before a final shot.

**`PAUSE n` and `PAUSE 0` both end on a key that's *already held*.** A result screen vanished instantly for a player (a bot) still holding a direction when the game ended. Wait for hands off first: `REPEAT: REPEAT UNTIL INKEY$ = ""` in the program, or `release` before the end in the script.

**Sync on the program, not on the pixels.** A game may keep its whole state *in* the screen's attributes, with every rule an `ATTR()` test, and a move drawn in two half-steps inside one loop. "The player has stopped moving" fired while the BASIC was still inside the move, and the snapshot was a half-drawn board with a crate stranded half a square over. The honest signal was in the program: when idle it re-printed a status line with `PRINT #0`, so a breakpoint on CHAN-OPEN (`0x1601`) with A = 0 meant "back at the top of the loop". Find the equivalent in whatever you're driving.

**Measure the timing; don't reason it out.** Assumed: a key pressed now steers the move after next. Measured: it steered the very next one. The machine is literal, and it's quicker to ask it than to argue.

**Small traps.** A script named `dis.py` shadows Python's `dis` module and breaks Pillow's import (so the disassembler is `zxdis.py`). zsh treats an unquoted `====` as an expansion, so quote separators in `echo`.

## Seeing

**The picture** is 352×288: a 48-pixel border all round, drawn by the beam as it goes, so an `OUT 254` in the middle of a frame splits the border (`examples/hello.zx` catches one, and `examples/stripes.asm` makes a screenful). Colours are `0xD7` normal and `0xFF` bright. FLASH swaps every 16 frames. After a snapshot is loaded, the core draws a frame from memory, so there's a picture before any frame has run.

**A picture is the last complete frame.** Steps that stop in the middle of a frame (typing, `ready`, `until`) leave memory up to a frame ahead of the picture, so a `grab` straight after typing can show the listing half-drawn. `wait 1` first, or call `zx.lib.zx_render_static(zx.z)` to draw the screen from memory as it stands.

**Look at the `_960.jpg` previews.** A contact sheet is 1,000 to 1,400 pixels wide as a PNG; the preview is 960. A `shot` is 704×576 (2×, with the border).

**Look long enough, and crop before claiming absence.** A program that lights up the keys you hold needed more than 3 frames to show a key, and ENTER was nearly declared broken. When something looks missing, crop the region and scale it 3 or 4 times (Pillow's `crop` and `resize` with `NEAREST`) before deciding. A report line that seemed empty turned out, zoomed, to really be empty, and the zoom is what made that trustworthy.

**`screen` reads 8×8 text only.** It matches each character cell against the font the ROM is using (the CHARS system variable), the UDGs and the block graphics, in either polarity. Big custom fonts come out as `·`. A graphic cell that happens to match a character reads as that character: a line along the bottom of a cell is exactly `_`, so a circle's edge can produce a few. Check the attributes or a picture when it matters. UDGs still showing their default A–U shapes read as letters, which is honest, because that's what they look like. `printed` gives what the ROM printed to the main screen, even if it has since scrolled away.

**The attributes are the colours**, and they're easy to read directly: the byte at `22528 + 32*row + column` holds INK (bits 0–2), PAPER (3–5), BRIGHT (6) and FLASH (7). Many BASIC games keep their model of the world here, which makes them easy to read from outside too.

## Hearing

**The beeper is recorded as edges.** `beeper_notes()` splits the edge train by silence *and* by change of pitch, because consecutive BEEPs have no gap between them. `FOR n=0 TO 12 STEP 2: BEEP 0.15,n` measures as 261.7, 293.7, 329.8, 370.3, 415.7, 466.7 and 523.6 Hz, every note within 0.02 semitones and 0.148 s long. The `notes` step prints them with the nearest note and how many cents off it is; `wav` writes the sound for human ears, DC-blocked.

**The AY (on the 128)** has every register write logged with its T-state, so `zxay.ay_notes()` replays them into notes per channel (tone = 1.77345 MHz / 16 / period) and `piano_roll()` draws them: time across, pitch up, one colour per channel. `notes_text()` gives the same as lines of text, which is the form to read if you can't see the roll. Samples from the AY core are collected only while recording (the `ay` step, or `record_ay()`), so it costs nothing otherwise, and `aywav` writes a WAV.

You can't hear it, but you can measure it: pitch, timing, which channel, how loud. A tune can be checked note for note against what was written.

## Tapes and snapshots

**LOAD is instant** through a trap on the ROM's LD-BYTES (an opcode fetch at `0x0562`, returning through `0x0555`). A block that doesn't match (wrong flag or length) is skipped whole, the way the real ROM skips a data block after an unwanted header. With no tape left, the ROM waits for edges, as a real machine does with the recorder stopped. **SAVE** goes through SA-BYTES (`0x04C2`) into `saved_tape()`, and `savetape` writes it out.

**Only TAP files** are read. Convert a TZX with tzxtools' `tzxtap`; a `.z80` snapshot needs converting to SNA with another tool first.

**Snapshots are SNA files**, 48K (49,179 bytes) or 128K (131,103 bytes). They load and save at any moment, and a reload carries on exactly. The only differences a reload leaves are a few bytes of dead stack below SP.

## The 128

`Speccy(model=128)`, or the `boot128` step, boots the Spectrum 128 to its 1986 menu. `menu tape` picks Tape Loader, which LOADs "" from the deck and runs what autostarts. `menu 48` gives 48 BASIC, where all the keyword typing works (it locks ROM 1 in).

- **Paging is done by copying.** The CPU sees a flat 64K, so Python's `zx.mem`, breakpoints and traps work unchanged. A page switch swaps 16K between the flat view and a bank store. Banks 5 (the screen) and 2 are always in the flat view; if one is *also* paged at `0xC000`, writes go to both copies. `zx.lib.zx_bank(zx.z, n)` gives a pointer to bank *n* wherever it currently lives.
- **The tape traps fire only when ROM 1 is paged in** (the 128's editor calls the 48K ROM's LD-BYTES).
- **Typing in 128 BASIC isn't supported yet**: its editor is a different program, in ROM 0, and `type()` knows the 48K one. Use `menu 48`, or make a TAP (speccy-basic knows the PLAY keyword) and use Tape Loader. Plain keystrokes do work, since the 128 editor tokenises the line on ENTER; its idle loop is at ROM 0 `0x3683`.
- **128 programs play the AY**, so record it: `ay`, run, then `roll` and `aywav`.

## Spectrum BASIC, learned the hard way

**Loading a TAP skips the syntax check that typing does.** `FOR ii = …` passed speccy-basic and loaded from a TAP without complaint, then stopped at RUN with "C Nonsense in BASIC". So typing a program in (`basic`) is the stricter test, and `lint` does it for a whole file. **FOR variables, string variables and array names must be single letters** (`FOR ii`, `LET ab$`, `DIM ab(3)` are all refused); long *numeric* names like `score` are fine. `lint tests/illegal.bas` accepts 5 of 8 lines; `lint tests/illegal.bas min` accepts all 8, because `min` renames `ii` to `I` and `ab$` to `A$` first. A good workflow: write readable long names, let speccy-basic's `--minimize` rename them, then lint what the ROM will actually see.

**A colon inside a REM flips the editor to K mode.** The ROM decides the mode by scanning the line, and it doesn't know it's inside a comment, so after `REM a: X…` the next letter would go in as a keyword. `type()` refuses (`cannot type letter 'X' in K mode`) rather than type it wrong. Keep colons out of REMs.

**`ATTR (line, column)` takes the same order as `AT`.** After `PRINT AT 3,10; INK 2; PAPER 6;"x"`, `ATTR (3,10)` is 50 and `ATTR (10,3)` is 56 (the default). Checked on the machine.

**`CLEAR` belongs on the first line.** Inside a GO SUB it wipes the return stack.

**Screen tricks** (from Melissa O'Neill, who wrote OMSE and speccy-basic). `PRINT #0; AT 0,0; "…"` writes into the bottom two lines, the editor's, so it's a free status line, and `INPUT ""` clears them. `OUT 254, x` sets the border *transiently*, without the lower screen's colours that BORDER also sets, which is right for a flash. And let a game's model live in the screen colours: one colour per kind of thing, so a collision is one `ATTR` read. Spectrum BASIC's `OR` is logical, not bitwise, so to change one bit of an attribute, POKE the whole byte.

**BASIC is slow enough to design around.** Parsing a string of notes one character at a time took 25 seconds; fixed-width fields with `CODE` lookups instead of `VAL` took 10. Draw the picture first, so the slow setup happens while there's something to look at.

## Machine code

Code called from BASIC with `USR` must **preserve the alternate HL'**, which the ROM needs to get back to BASIC, so avoid `EXX` or save it. **Never change IY while the ROM's interrupt handler can run**: it reaches the system variables through IY. Either disable interrupts while you use IY, or install your own IM 2 handler, and an IM 2 handler that hands on to `$0038` afterwards must leave IY alone too. To call code without disturbing the random-number seed (as `RANDOMIZE USR` does), use `POKE 0, 0*USR addr`: the POKE into ROM does nothing.

`asm` assembles with pasmo and puts the result in the deck; `until ADDR` and `run_until` stop at an address; `regs` and `peek` show the state. `zxdis.py` disassembles the ROM or a file. For a clean code/data split of any program, the core has an **execution map**: `zx.lib.zx_execmap(zx.z, 1, -1)` starts counting opcode fetches at every address (the last argument restricts counting to while one bank is paged at `0xC000`), and `zx.lib.zx_execmap_get(zx.z)` points at 65,536 counts. That's the input SkoolKit's `sna2ctl -m` wants.

## Optional tools

- **Pillow** is required (every picture). `pip install Pillow`.
- **speccy-basic** (`pip install spectrum-basic`), Melissa O'Neill's BASIC toolkit, for `.bas` files: the `bas` command and the `basic`, `lint` and `tapbas` steps. It reads classic numbered BASIC and its own enhanced dialect (labels, `REPEAT`, multi-line `IF`), which it turns into classic numbered lines.
- **tzxtools** (`pip install tzxtools`) for `zxdis.py`, and for looking inside tapes: `tzxls` lists blocks, `tzxcat -B` lists BASIC, `tzxcat -S` turns a SCREEN$ into a PNG.
- **pasmo** for the `asm` step. It isn't packaged by Homebrew; build it from source, which takes a minute and needs only a C++ compiler:

  ```bash
  curl -fLO https://pasmo.speccy.org/bin/pasmo-0.5.5.tar.gz
  tar xzf pasmo-0.5.5.tar.gz && cd pasmo-0.5.5
  ./configure && make          # then put ./pasmo on your PATH, or set PASMO to it
  ```
- **SkoolKit** (`pip install skoolkit`) isn't used by omse-ai, but the annotated disassembly of the 48K ROM on its website (skoolkit.ca) names every routine, which beats remembering addresses, and its `sna2ctl -m` takes the execution map above.

## The core

`src/zxcore.cpp` is the machine, as a C library with no dependencies beyond the two chips headers: the Z80, the ULA racing the beam, the keyboard matrix, Kempston joystick, 128K paging and the AY, tape traps, and the logs (beeper edges, AY register writes, printed text). `make` builds `lib/libzxcore.dylib` on macOS or `lib/libzxcore.so` elsewhere, and `speccy.py` rebuilds it by itself when the source is newer. The functions are all `zx_*` and all listed, with their C types, in `_load_lib()` in `speccy.py`; `zx.lib` gives you them directly.

It began as OMSE, Melissa O'Neill's emulator. The beam-racing ULA, the timing and the SNA loading come from a stripped-down 48K version of it (including loading a snapshot by jumping to the ROM's `RETN` at `0x0072`, so the snapshot's own stack supplies the PC). The tape traps, print interception, 128K paging, port decoding and AY hookup come from OMSE itself. What changed: no SDL; the screen goes into an indexed framebuffer; the keyboard matrix is set by the caller; sound is logged rather than played; snapshots can be saved at any frame; tapes come in as bytes.

## Limits

- **No contention.** Memory and I/O contention aren't emulated, so code that races the beam to the exact T-state (some demos, some multicolour effects) will be slightly off.
- **TAP and SNA only.** No TZX, `.z80` or disk images.
- **Typing is for the 48K editor** (on a 48K, or in 48 BASIC on a 128). 128 BASIC takes plain keystrokes only.
- **`screen` reads 8×8 characters only**, in the current font.
- **The AY exists only on the 128.** A 48K has the beeper.
- Tested on macOS (Apple silicon) with Python 3.14 and Pillow 12. The Makefile knows Linux, but nobody has tried it there yet.
