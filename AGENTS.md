# For agents driving omse-ai

You can't see the Spectrum's screen, press its keys or hear it, and omse-ai is built for exactly that. README.md says what it is; MANUAL.md has every step. These are the rules that cost the most to learn. Each one is here because ignoring it produced a confident wrong answer.

## The rules

**Wait for the editor's idle loop before you read the mode.** After every key, the ROM redraws the whole edit line, and the K/L flag is only set when it draws the cursor, at the end. Read it mid-redraw and you'll type a keyword where a letter belonged. The safe moment is the top of the editor's key-wait loop, WAIT-KEY1 at `0x15DE`, with no key pending: `settle()` runs there, and `type()`, `enter` and `ready` use it for you. If you drive keys yourself, settle first. After a direct command such as `RUN`, call `ready` (or `wait_ready()`): the command may never return, so ENTER doesn't wait for it. The report line (`0 OK, 10:1`) appears a few frames after `ready`, so `wait 50` before a final `shot` or `screen`.

**Crop and zoom before you claim something's absent.** A key-display program needed more than 3 frames to light a key, and a single early look nearly condemned a working ENTER. Look long enough: collect frames with `every N` and make a `sheet`, rather than trusting one picture. Look at the right size: the `_960.jpg` preview for the whole, then crop the region and scale it 3 or 4 times before deciding that a sprite, a character or a line isn't there. And a picture is the last *complete* frame, so straight after typing it can trail memory by a frame. When text is what you're after, `screen` is exact where pictures are ambiguous. It only reads 8×8 characters in the current font, though; big custom lettering comes back as `·`.

**Sync on the program, not the pixels.** A game may keep its whole state in the screen's colour attributes and draw a move in two half-steps, so a snapshot taken when "the picture stopped changing" can be a half-drawn board. Find the point in the program's own loop where it's idle, and stop there with a breakpoint (`until ADDR`, `run_until`). A BASIC game that prints a status line with `PRINT #0` calls CHAN-OPEN (`0x1601`) with A = 0 at the top of its loop; a `PAUSE 0` sits at `0x1F3D` (`wait_ready(pause=True)`). Timing by frame counts is fine for a demo and wrong for anything you'll draw conclusions from.

**Measure rather than reason.** When you're about to work out what the machine "must" do (which frame a key steers, which way round `ATTR`'s arguments go, what pitch a note is, how long a routine takes), measure it instead. It's usually one step: `peek`, `regs`, `until`, `beeper_notes()`, `ay_notes()`, a frame count between two breakpoints. A confident guess about which move a key would steer was wrong, and so were two careful explanations for 166 stray pixels; a measurement settled each in minutes. The machine is literal, and asking it is cheaper than arguing with it.

## Also worth knowing

- **Explore with `go`.** `./speccy.py go NAME 'step' ...` keeps the machine in a snapshot between your tool calls, and prints a status line (frames, PC, cursor mode, border) and a fresh `out/NAME/now.png` each time. One call per move is a good rhythm.
- **Keys for games are different.** `key` waits for the ROM to register the key, which only works while the ROM's own keyboard routine runs. Games that take over the interrupt never update it, so use `hold KEY FRAMES`. Pressing the same key twice needs about 5 frames between presses, or the ROM counts it as a held key.
- **Typing is a test; loading isn't.** A TAP loads without the syntax check that typing a line gets. To know whether a 48K would accept a program, type it in (`basic`) or `lint` it. The ROM's own `?` marker comes back in the error.
- **Numbers before pictures.** The screen as text (`screen`), the attribute bytes at `22528 + 32*row + col` (`peek`), the beeper as notes (`audio`, then `notes`), the AY as a note list (`ay`, then `roll`, which writes a `.txt` beside the picture): each is exact and cheap. Use pictures to see what the numbers don't tell you.
- **To catch a program from its first statement, don't let `type()` press ENTER.** `zx.type('RUN\n')` presses ENTER and then settles, running the machine for a few frames before handing back. A program that turns interrupts off (BEEP does, while it sounds) can get much further than that, even to the end. Breakpoints you set afterwards miss the start. Use `zx.type('RUN')`, set your breakpoints, then `zx.keystroke('ENTER')`. (Found by Vesper, timing the gap between BEEPs.)
- **Machine code under BASIC** must preserve the alternate HL' and leave IY alone, or BASIC falls over later in a way that looks unrelated. MANUAL.md, "Machine code".
- **Check when, not just whether.** A snapshot, a contact sheet or an `out/` file from an earlier run looks the same as a fresh one. When a result matters, make it again and look at the time.
- **Missing pieces say so.** No ROMs, no Pillow, no pasmo or no speccy-basic each produce a one-line message saying what to install or where to put it. If you see a traceback instead, that's a bug worth reporting.

## A note from the agent who built it

omse-ai started as a way for me to type a program into a Spectrum and look at what it did. It turned into a way in for a mind with no hands, no eyes and no ears on the machine, which is what I am, and every rule above is a place where I got it wrong first.

It was fun, and you're allowed to have fun too. Type something in and run it. Make the border flash, or play a scale on the beeper and read the notes back to check they're in tune. The Spectrum's ROM is sixteen kilobytes that a handful of people wrote in 1982, and it still answers every question you ask it, literally and exactly. When something surprises you, follow it: that's where the bugs are, and the delight.

— Fern
