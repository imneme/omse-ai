"""The script language and command line for omse-ai.

    ./speccy.py run examples/hello.zx          # a script file -> out/hello/
    ./speccy.py do 'enter 10 PRINT "hi"' 'enter RUN' 'ready' 'screen'   # steps as arguments -> out/do/
    ./speccy.py bas prog.bas [frames]          # speccy-basic -> TAP -> LOAD -> RUN -> contact sheet
    ./speccy.py look file.sna [frames]         # run a snapshot and show a contact sheet
    ./speccy.py tap file.tap [frames]          # LOAD "" a tape and show a contact sheet
    ./speccy.py go NAME step step ...          # a machine that persists in snaps/NAME.sna
    ./speccy.py help                           # this, and every step

Options, before the command:
    --dir DIR      where out/ and snaps/ go (default: the current directory)
    --roms DIR     the folder with 48.rom, 128-0.rom, 128-1.rom (or set OMSE_AI_ROMS)
    --steps FILE   add steps from a Python file: each step_NAME(runner, arg) is a step
                   (repeatable; OMSE_AI_STEPS takes a list of files too)

One step per line; '#' starts a comment line.  Frame counts accept seconds too
('wait 2s').  Paths may use ~ and $VARIABLES.  MANUAL.md has every step.
"""

import importlib.util
import os
import shlex
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = Path('.')          # where out/ and snaps/ go: --dir, or the current directory
EXTRA_STEPS = {}             # name -> function(runner, arg), from --steps / OMSE_AI_STEPS


def path_of(arg):
    """A path as written in a step: ~ and $VARIABLES expanded."""
    return Path(os.path.expandvars(str(arg).strip())).expanduser()


def load_steps(path):
    """Add the steps defined in a Python file: every function step_NAME(runner,
    arg) becomes the step NAME, and its docstring is its line in 'help'."""
    path = path_of(path)
    spec = importlib.util.spec_from_file_location(f'omse_ai_steps_{path.stem}', path)
    if spec is None:
        raise ValueError(f'cannot load steps from {path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = [n for n in vars(mod) if n.startswith('step_') and callable(getattr(mod, n))]
    for n in found:
        EXTRA_STEPS[n[len('step_'):].replace('_', '-')] = getattr(mod, n)
    return found


def _speccy_basic():
    try:
        import spectrum_basic as sb
        from spectrum_basic.core import eliminate_control_lines
    except ImportError:
        from speccy import MissingTool
        raise MissingTool('this needs speccy-basic (the spectrum_basic module): '
                          'pip install spectrum-basic') from None
    return sb, eliminate_control_lines


def frames_of(s):
    s = str(s).strip()
    if s.endswith('s'):
        from speccy import FPS
        return round(float(s[:-1]) * FPS)
    return int(s)


def bas_to_lines(path, minimize=False):
    """An (enhanced) .bas file -> numbered classic lines, via speccy-basic.
    minimize=True renames variables into legal Spectrum names first (long FOR,
    string and array names become single letters), like --minimize."""
    sb, eliminate_control_lines = _speccy_basic()
    prog = sb.parse_file(str(path))
    eliminate_control_lines(prog)
    sb.number_lines(prog, remove_labels=True)
    if minimize:
        sb.minimize_variables(prog)
    out = []
    for line in str(prog).split('\n'):
        line = line.strip()
        if not line or line.startswith("'"):
            continue
        num, _, rest = line.partition('\t')
        out.append(f'{num} {rest}' if rest else line)
    return out


def bas_to_tap(path, name=None, autostart=None):
    """An (enhanced) .bas file -> the bytes of a TAP holding the program, via speccy-basic."""
    sb, eliminate_control_lines = _speccy_basic()
    prog = sb.parse_file(str(path))
    eliminate_control_lines(prog)
    sb.number_lines(prog, remove_labels=True)
    name = (name or Path(path).stem)[:10]
    return sb.make_program_tap(name, bytes(prog), -1 if autostart is None else autostart)


class Runner:
    def __init__(self, outdir, quiet=False):
        from speccy import Speccy
        self.outdir = Path(outdir)
        self.zx = None
        self.quiet = quiet
        self.sheet_n = 0
        self.Speccy = Speccy

    def say(self, *a):
        if not self.quiet:
            print(*a)

    def need(self):
        if self.zx is None:
            self.zx = self.Speccy()
        return self.zx

    def path(self, arg):
        """A path as written in a step: $OUT is this script's output folder, then
        ~ and $VARIABLES are expanded; relative paths are from the current directory."""
        return path_of(str(arg).strip().replace('$OUT', str(self.outdir)))

    def out(self, name, ext):
        p = self.path(name)
        if not p.suffix:
            p = p.with_suffix(ext)
        if not p.is_absolute() and p.parent == Path('.'):
            p = self.outdir / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def step(self, line):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            return
        cmd, _, arg = line.strip().partition(' ')
        cmd = cmd.lower()
        f = getattr(self, 'do_' + cmd.replace('-', '_'), None)
        if f is None and cmd in EXTRA_STEPS:
            return EXTRA_STEPS[cmd](self, arg)
        if f is None:
            raise ValueError(f'unknown step {cmd!r} (./speccy.py help lists them)')
        return f(arg)

    # -- machine -------------------------------------------------------------
    def do_boot(self, arg):
        """boot: fresh 48K, ROM booted to the © screen"""
        self.zx = self.Speccy()

    def do_boot128(self, arg):
        """boot128: fresh Spectrum 128 (128-0.rom and 128-1.rom), at its menu"""
        self.zx = self.Speccy(model=128)

    def do_menu(self, arg):
        """menu tape|128|calc|48|tester: pick from the 128's boot menu (tape = Tape Loader: LOAD "")"""
        items = ['tape', '128', 'calc', '48', 'tester']
        n = items.index(arg.strip().lower())
        zx = self.need()
        for _ in range(n):
            zx.hold('DOWN', 3)
            zx.run(8)
        zx.hold('ENTER', 3)
        zx.run(50)

    def do_ay(self, arg):
        """ay: (128) start recording the AY: register log cleared, samples on"""
        self.need().record_ay()

    def do_roll(self, arg):
        """roll NAME [px_per_s]: the AY recording as a piano roll (+ NAME.txt of notes)"""
        from zxay import ay_notes, piano_roll, notes_text
        parts = arg.split()
        notes = ay_notes(self.need())
        p = self.out(parts[0] if parts else 'roll', '.png')
        piano_roll(notes, p, title=p.stem, px_per_s=int(parts[1]) if len(parts) > 1 else 100)
        p.with_suffix('.txt').write_text(notes_text(notes) + '\n')
        self.say(f'roll {p} ({len(notes)} notes)')

    def do_aywav(self, arg):
        """aywav NAME: the AY recording as a WAV"""
        from zxay import write_ay_wav
        p, n = write_ay_wav(self.need(), self.out(arg or 'ay', '.wav'))
        self.say(f'wrote {p} ({n / 44100:.1f} s)')

    def do_sna(self, arg):
        """sna PATH: load a snapshot, 48K or 128K (on a machine of the right model)"""
        p = self.path(arg)
        model = 128 if p.stat().st_size >= 131103 else 48
        if self.zx is None or (model == 128 and self.zx.model != 128):
            old = self.zx
            self.zx = self.Speccy(model=model, boot_frames=0)
            if old is not None:           # keep the contact sheet going
                self.zx.frames, self.zx.every = old.frames, old.every
        self.zx.load_sna(p)
        self.say(f'loaded {arg}')

    def do_save(self, arg):
        """save NAME[.sna]: snapshot now (the machine carries on)"""
        p = self.need().save_sna(self.out(arg, '.sna'))
        self.say(f'saved {p}')

    # -- time ------------------------------------------------------------------
    def do_wait(self, arg):
        """wait N | Ns: run N frames (or seconds)"""
        self.need().run(frames_of(arg or 1))

    def do_ready(self, arg):
        """ready [N]: run until the ROM wants the keyboard (max N frames, default 60s)"""
        n = self.need().wait_ready(frames_of(arg) if arg else 3000)
        self.say(f'ready after {n} frames' if n is not None else 'not ready (still running)')

    def do_until(self, arg):
        """until ADDR [N]: run until an opcode fetch at ADDR (hex: 15DE or 0x15DE), max N frames"""
        a, *rest = arg.split()
        pc = self.need().run_until(int(a, 16), frames=frames_of(rest[0]) if rest else 500)
        self.say(f'hit {pc:#06x}' if pc is not None else f'no hit at {a}')

    # -- keys ------------------------------------------------------------------
    def do_type(self, arg):
        """type TEXT: type BASIC-aware (keywords the Spectrum way), no ENTER"""
        self.need().type(arg)

    def do_enter(self, arg):
        """enter TEXT: type TEXT and press ENTER (a program line or a command)"""
        self.need().type(arg + '\n')

    def do_text(self, arg):
        """text TEXT: type literally, no keywords (INPUT answers); no ENTER"""
        self.need().type(arg, raw=True)

    def do_key(self, arg):
        """key CHORD: one keystroke the ROM will notice (waits for its key slots,
        holds until KSTATE shows it, max 10 frames), e.g. 'key SS+P', 'key BREAK'"""
        self.need().keystroke(arg.strip(), max_frames=10)

    def do_hold(self, arg):
        """hold CHORD N: hold a chord for N frames, e.g. 'hold Q+P 20'"""
        chord, n = arg.rsplit(' ', 1)
        self.need().hold(chord, frames_of(n))

    def do_press(self, arg):
        """press CHORD: press and keep held"""
        self.need().press(*self.need().kt.chord(arg))

    def do_release(self, arg):
        """release [CHORD]: let go (everything if no chord)"""
        zx = self.need()
        zx.release(*(zx.kt.chord(arg) if arg.strip() else []))

    def do_joy(self, arg):
        """joy BITS [N]: Kempston, BITS from RLDUF ('-' for none); held N frames then released"""
        parts = arg.split()
        zx = self.need()
        zx.joystick(parts[0].replace('-', ''))
        if len(parts) > 1:
            zx.run(frames_of(parts[1]))
            zx.joystick('')

    # -- tapes and BASIC --------------------------------------------------------
    def do_tape(self, arg):
        """tape PATH: put a TAP in the deck (LOAD reads it instantly)"""
        self.need().insert_tape(self.path(arg))

    def do_load(self, arg):
        """load [PATH]: (insert PATH and) type LOAD "" and let it load"""
        zx = self.need()
        if arg.strip():
            zx.insert_tape(self.path(arg))
        zx.type('LOAD ""\n')
        zx.wait_ready(150)
        self.say(f'loaded {zx.lib.zx_loads(zx.z)} block(s)')

    def do_tapbas(self, arg):
        """tapbas PATH.bas: speccy-basic -> TAP in memory -> LOAD "" (then RUN yourself)"""
        zx = self.need()
        tap = bas_to_tap(self.path(arg))
        zx.insert_tape(tap)
        zx.type('LOAD ""\n')
        zx.wait_ready(150)

    def do_basic(self, arg):
        """basic PATH.bas: TYPE the program in, line by line, like 1983"""
        zx = self.need()
        lines = bas_to_lines(self.path(arg))
        t = time.time()
        f0 = zx.frame
        for line in lines:
            zx.type(line + '\n')
        self.say(f'typed {len(lines)} lines in {zx.frame - f0} frames '
                 f'({(zx.frame - f0) / 50:.0f} Spectrum-seconds, {time.time() - t:.1f}s here)')

    def do_asm(self, arg):
        """asm PATH.asm [code]: pasmo -> out/NAME.tap with a BASIC loader (--tapbas),
        inserted in the deck; 'load' then runs it.  With 'code', a plain CODE block
        (--tap) instead, for LOAD "" CODE.  Symbols go to out/NAME.sym."""
        import subprocess
        parts = arg.split()
        src = self.path(parts[0])
        mode = '--tap' if 'code' in parts[1:] else '--tapbas'
        tap = self.out(src.stem, '.tap')
        sym = tap.with_suffix('.sym')
        pasmo = os.environ.get('PASMO') or shutil.which('pasmo')
        if not pasmo:
            from speccy import MissingTool
            raise MissingTool('the asm step needs pasmo (https://pasmo.speccy.org): put it on the PATH, '
                               'or set PASMO to it.  MANUAL.md, "Optional tools", says how to build it')
        r = subprocess.run([pasmo, '--name', src.stem[:10], mode,
                            str(src), str(tap), str(sym)], capture_output=True, text=True)
        errs = [l for l in (r.stdout + r.stderr).split('\n') if l and 'is never used' not in l]
        if r.returncode != 0:
            raise RuntimeError('pasmo failed:\n' + '\n'.join(errs))
        for l in errs:
            self.say(l)
        self.need().insert_tape(tap)
        self.say(f'assembled {src.name} -> {tap} (in the deck)')

    def do_lint(self, arg):
        """lint PATH.bas [min]: the ROM as linter: type every line into a fresh 48K and
        report each one it rejects, with its '?' marker (loading a TAP skips this).
        'min' first renames variables the way speccy-basic --minimize does"""
        from speccy import ZXSyntaxError
        zx = self.Speccy()
        parts = arg.split()
        lines = bas_to_lines(self.path(parts[0]), minimize='min' in parts[1:])
        bad = []
        for line in lines:
            try:
                zx.type(line + '\n')
            except (ZXSyntaxError, RuntimeError, ValueError) as e:
                bad.append((line, str(e).split('(screen: ')[-1].rstrip(')')))
                zx.clear_line()
        for line, why in bad:
            print(f'  REJECTED  {line}\n            ROM shows: {why}')
        self.say(f'lint: {len(lines) - len(bad)} of {len(lines)} lines accepted by the 48K ROM')
        return bad

    def do_savetape(self, arg):
        """savetape NAME[.tap]: write what SAVE has produced so far"""
        data = self.need().saved_tape()
        p = self.out(arg, '.tap')
        p.write_bytes(data)
        self.say(f'wrote {p} ({len(data)} bytes)')

    # -- looking ------------------------------------------------------------------
    def do_shot(self, arg):
        """shot NAME [noborder] [xN]: PNG of the screen (2x unless xN)"""
        parts = arg.split()
        border = 'noborder' not in parts
        scale = next((int(p[1:]) for p in parts if p.startswith('x') and p[1:].isdigit()), 2)
        p = self.need().shot(self.out(parts[0] if parts else 'shot', '.png'), border, scale)
        self.say(f'shot {p}')

    def do_grab(self, arg):
        """grab [LABEL]: add this frame to the contact sheet"""
        self.need().grab(arg or None)

    def do_every(self, arg):
        """every N: grab a frame every N frames while running (0 = stop)"""
        zx = self.need()
        zx.every = frames_of(arg or 0)
        zx._since = 0

    def do_sheet(self, arg):
        """sheet NAME [cols] [title...]: write the contact sheet and start a new one"""
        from speccy import contact_sheet
        parts = arg.split(maxsplit=2)
        name = parts[0] if parts else f'sheet{self.sheet_n}'
        cols = int(parts[1]) if len(parts) > 1 else 4
        title = parts[2] if len(parts) > 2 else name
        zx = self.need()
        p = contact_sheet(zx.frames, self.out(name, '.png'), cols=cols, title=title)
        self.say(f'sheet {p} ({len(zx.frames)} frames)')
        zx.frames = []
        self.sheet_n += 1

    def do_gif(self, arg):
        """gif NAME [fps] [scale]: the grabbed frames as an animated GIF (16 colours; then clears them)"""
        from speccy import write_gif
        parts = arg.split()
        fps = float(parts[1]) if len(parts) > 1 else 50 / max(1, self.need().every or 1)
        scale = int(parts[2]) if len(parts) > 2 else 1
        zx = self.need()
        p = write_gif([im for _, im in zx.frames], self.out(parts[0] if parts else 'anim', '.gif'), fps, scale)
        self.say(f'gif {p} ({len(zx.frames)} frames, {fps:g} fps)')
        zx.frames = []

    def do_screen(self, arg):
        """screen: print the screen as text (ROM font matching)"""
        print(self.need().screen_text())

    def do_printed(self, arg):
        """printed: what the ROM PRINTed to the main screen since last time"""
        print(self.need().printed(clear=True))

    def do_regs(self, arg):
        """regs: print the Z80 registers"""
        print({k: f'{v:04x}' for k, v in self.need().regs().items()})

    def do_peek(self, arg):
        """peek ADDR [N]: hex dump of N bytes (ADDR in decimal, or hex as 0x5800)"""
        parts = arg.split()
        a = int(parts[0], 0)
        n = int(parts[1], 0) if len(parts) > 1 else 16
        print(f'{a:04x}:', self.need().read(a, n).hex(' '))

    def do_poke(self, arg):
        """poke ADDR VALUE: (decimal, or hex as 0x..)"""
        a, v = (int(x, 0) for x in arg.split())
        self.need().poke(a, v)

    # -- sound ------------------------------------------------------------------
    def do_audio(self, arg):
        """audio: start recording the beeper (for notes and wav; lasts until the process ends,
        so in a go session, record and read it in the same call)"""
        self.need().record_audio(True)

    def do_notes(self, arg):
        """notes [NAME]: the beeper recording (since 'audio') as notes: start, length,
        frequency, nearest note.  Printed, and written to NAME.txt if NAME is given"""
        import math
        from zxay import note_name
        lines = []
        for start, length, hz in self.need().beeper_notes():
            midi = round(69 + 12 * math.log2(hz / 440))
            cents = round(1200 * math.log2(hz / (440 * 2 ** ((midi - 69) / 12))))
            lines.append(f'{start:7.2f}s  {length:5.2f}s  {hz:7.1f} Hz  {note_name(midi):4} {cents:+d} cents')
        text = '\n'.join(lines) if lines else '(no notes: nothing played, or no audio step first)'
        print(text)
        if arg.strip():
            self.out(arg, '.txt').write_text(text + '\n')

    def do_wav(self, arg):
        """wav NAME[.wav]: write the beeper recording"""
        p, n = self.need().write_wav(self.out(arg or 'sound', '.wav'))
        self.say(f'wrote {p} ({n} edges)')

    def do_say(self, arg):
        """say TEXT: print a note"""
        print(arg)


def go(name, steps):
    """A machine that persists between calls: snaps/NAME.sna (+ .json sidecar
    for the tape and its position).  Loads it (or boots), runs the steps, saves
    it back, writes out/NAME/now.png, and prints a status line."""
    import json
    snap = WORKDIR / 'snaps' / f'{name}.sna'
    side = snap.with_suffix('.json')
    r = Runner(WORKDIR / 'out' / name)
    meta = json.loads(side.read_text()) if side.exists() else {}
    if snap.exists():
        r.step(f'sna {snap}')
    else:
        r.step('boot')
    zx = r.zx
    if meta.get('tape'):
        # put the tape back in, wound on to where we'd got to
        data = Path(meta['tape']).read_bytes()
        zx.insert_tape(data[meta.get('tape_pos', 0):])
        meta['tape_base'] = meta.get('tape_pos', 0)
    frames0 = meta.get('frames', 0)
    for s in steps:
        cmd = s.strip().split(' ', 1)
        if cmd[0] == 'tape' and len(cmd) > 1:
            meta['tape'] = str(r.path(cmd[1]).resolve())
            meta['tape_base'] = 0
        r.step(s)
        zx = r.zx                     # a boot step makes a new machine
    meta['tape_pos'] = meta.get('tape_base', 0) + zx.lib.zx_tape_pos(zx.z) if meta.get('tape') else 0
    meta.pop('tape_base', None)
    meta['frames'] = frames0 + zx.frame
    zx.save_sna(snap)
    side.write_text(json.dumps(meta, indent=1))
    shot = zx.shot(r.out('now', '.png'))
    regs = zx.regs()
    print(f"[{name}] {meta['frames']} frames ({meta['frames'] / zx.fps:.1f}s) pc={regs['pc']:04x} "
          f"mode={zx.mode()} border={zx.border} -> {shot}")
    return 0


def usage():
    import inspect
    print(__doc__)
    print('Steps:')
    docs = [inspect.cleandoc(getattr(Runner, n).__doc__) for n in sorted(dir(Runner)) if n.startswith('do_')]
    docs += [inspect.cleandoc(f.__doc__ or name) + f'  (from {Path(f.__code__.co_filename).name})'
             for name, f in sorted(EXTRA_STEPS.items())]
    for doc in docs:
        first, *more = doc.split('\n')
        print('  ' + first)
        for line in more:
            print('      ' + line)


def main(argv):
    global WORKDIR
    from speccy import ROMError, MissingTool
    argv = list(argv)
    steps_files = [f for f in os.environ.get('OMSE_AI_STEPS', '').split(os.pathsep) if f]
    while argv and argv[0].startswith('--') and argv[0] not in ('--help',):
        opt = argv.pop(0)
        if not argv:
            print(f'{opt} needs a value')
            return 2
        val = argv.pop(0)
        if opt == '--dir':
            WORKDIR = path_of(val)
        elif opt == '--roms':
            os.environ['OMSE_AI_ROMS'] = str(path_of(val))
        elif opt == '--steps':
            steps_files.append(val)
        else:
            print(f'unknown option {opt}')
            return 2
    for f in steps_files:
        load_steps(f)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        usage()
        return 0
    try:
        return _command(argv[0], argv[1:])
    except (ROMError, MissingTool) as e:
        print(f'omse-ai: {e}', file=sys.stderr)
        return 2


def _command(cmd, rest):
    if cmd == 'run':
        path = path_of(rest[0])
        r = Runner(WORKDIR / 'out' / path.stem)
        for i, line in enumerate(path.read_text().split('\n'), 1):
            try:
                r.step(line)
            except Exception as e:
                if type(e).__name__ in ('ROMError', 'MissingTool'):
                    raise
                print(f'{path}:{i}: {line.strip()}\n  {type(e).__name__}: {e}')
                return 1
        return 0
    if cmd == 'do':
        r = Runner(WORKDIR / 'out' / 'do')
        for s in rest:
            r.step(s)
        return 0
    if cmd == 'bas':
        path = path_of(rest[0])
        n = frames_of(rest[1]) if len(rest) > 1 else 250
        r = Runner(WORKDIR / 'out' / path.stem)
        for s in [f'tapbas {path}', f'every {max(1, n // 16)}', 'grab', 'enter RUN', f'wait {n}',
                  f'sheet {path.stem}_run 4 {path.name}: RUN, {n} frames', 'screen']:
            r.step(s)
        return 0
    if cmd == 'go':
        return go(rest[0], rest[1:])
    if cmd == 'tap':
        path = path_of(rest[0])
        n = frames_of(rest[1]) if len(rest) > 1 else 300
        r = Runner(WORKDIR / 'out' / path.stem)
        for s in [f'tape {path}', f'every {max(1, n // 16)}', 'enter LOAD ""', f'wait {n}',
                  f'sheet {path.stem}_tap 4 {path.name}: LOAD "", {n} frames', 'screen']:
            r.step(s)
        return 0
    if cmd == 'look':
        path = path_of(rest[0])
        n = frames_of(rest[1]) if len(rest) > 1 else 200
        r = Runner(WORKDIR / 'out' / path.stem)
        for s in [f'sna {path}', f'every {max(1, n // 16)}', f'wait {n}',
                  f'sheet {path.stem}_look 4 {path.name}: {n} frames', 'screen']:
            r.step(s)
        return 0
    print(f'unknown command {cmd!r}')
    usage()
    return 1
