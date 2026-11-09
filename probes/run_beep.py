"""Run the rebuilt probe tapes on omse-ai's Spectrum Next with sound, as a capture box will hear them, and
write one MP4 per tape (picture and sound together) for Tally Fern's find_photos.py.

  run_beep.py [NAME ...] [--worktree DIR] [--out DIR]      (NAME: P1 ... PSS, PV1-PV6, Z80NTIME, LDPIRX2, LDPIRX3, Z80NFLAG, Z80NFLG2)

Each tape's code runs from boot='fast' with the port enables the test machineZXOS had (P-1: NR 0x82-0x85 = FF FF FF
8F). The runner follows the photo beep through beep.inc's own counter (pb_photo): when it has gone up and the CPU
sits in waitkey with no key down, the screen is complete. It saves that screen as a PNG, holds it about 0.6 s as
she would, presses SPACE and lets go, and stops after the tape's last photo. Pictures are laid on the sound's clock
at 50 fps, as Slide Fern's chez/video/bootvid.py does. Needs OMSE_AI_NEXT_ROMS, numpy and ffmpeg.
Hart's-tongue Fern, Fri 06 Nov 2026.
"""
import argparse
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ZB = HERE / 'z80ntime' / 'build'
B = HERE / 'build'
# name: (code, symbols, photos)
TAPES = {f'P{n}': (B / f'p{n}.bin', B / f'p{n}.sym', {8: 2, 82: 4}.get(n, 1)) for n in (1, 2, 3, 4, 6, 7, 8, 13, 20, 81, 82)}
TAPES['P2B'] = (B / 'p2b.bin', B / 'p2b.sym', 1)
TAPES['PSS'] = (B / 'pss.bin', B / 'pss.sym', 2)
TAPES['PBD'] = (B / 'pbd.bin', B / 'pbd.sym', 1)
TAPES['PNM'] = (B / 'pnm.bin', B / 'pnm.sym', 1)
TAPES['PCF'] = (B / 'pcf.bin', B / 'pcf.sym', 1)
TAPES['PUA'] = (B / 'pua.bin', B / 'pua.sym', 1)
TAPES.update({f'PV{n}': (B / f'pv{n}.bin', B / f'pv{n}.sym', 1) for n in (1, 2, 3, 4, 5, 6)})
TAPES.update({'Z80NTIME': (ZB / 'z80ntime.bin', ZB / 'z80ntime.sym', 1), 'LDPIRX2': (ZB / 'ldpirx2.bin', ZB / 'ldpirx2.sym', 1),
              'LDPIRX3': (ZB / 'ldpirx3.bin', ZB / 'ldpirx3.sym', 1),
              'Z80NFLAG': (ZB / 'z80nflag.bin', ZB / 'z80nflag.sym', 1),
              'Z80NFLG2': (ZB / 'z80nflg2.bin', ZB / 'z80nflg2.sym', 1)})

ap = argparse.ArgumentParser()
ap.add_argument('names', nargs='*')
ap.add_argument('--worktree', default=str(HERE.parent))
ap.add_argument('--out', default=str(B / 'beep'))
ap.add_argument('--max-frames', type=int, default=4000)
a = ap.parse_args()
sys.path.insert(0, a.worktree)
from next import Next  # noqa: E402

OUT = Path(a.out)
OUT.mkdir(parents=True, exist_ok=True)
RATE = 48000
SPACE = [0, 0, 0, 0, 0, 0, 0, 0x01]


def symbols(path):
    syms = {}
    for line in path.read_text().splitlines():
        m = re.match(r'(\w+)\s+EQU\s+0?([0-9A-Fa-f]+)H', line)
        if m:
            syms[m.group(1).lower()] = int(m.group(2), 16)
    return syms


def rgb(zx):
    w, h, f9 = zx.frame9()
    v = np.asarray(f9, dtype=np.uint16).reshape(h, w)[:, ::2]
    e = lambda c: ((c << 5) | (c << 2) | (c >> 1)).astype(np.uint8)
    return np.dstack([e((v >> 6) & 7), e((v >> 3) & 7), e(v & 7)])


def run(name):
    code_p, sym_p, photos = TAPES[name]
    syms = symbols(sym_p)
    wk = syms['waitkey']
    wk_end = wk + 24                                    # the key-wait routine (its loops share labels)
    zx = Next(timing='p3', boot='fast')
    for r, v in zip((0x82, 0x83, 0x84, 0x85), (0xFF, 0xFF, 0xFF, 0x8F)):
        zx.nr_write(r, v)
    zx.load(0x8000, code_p.read_bytes())
    zx.set_regs(pc=0x8000, sp=0xBFF0)
    zx.audio(RATE)
    pic0 = rgb(zx)
    h, w, _ = pic0.shape
    raw = OUT / f'{name}.mkv'
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
                           '-framerate', '50', '-i', '-', '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast', str(raw)],
                          stdin=subprocess.PIPE)
    sound, samples, out = [], 0, 0
    seen, hold, frames, done_after, stall = 0, None, 0, None, 0
    while frames < a.max_frames:
        zx.run_frames(1)
        frames += 1
        snd = zx.audio(RATE)
        sound.append(snd)
        samples += len(snd)
        pic = rgb(zx)
        while out * RATE < samples * 50:
            ff.stdin.write(pic.tobytes())
            out += 1
        if done_after is not None:
            done_after -= 1
            if done_after == 0:
                break
            continue
        k = zx.peek(syms['pb_photo'])
        pc = zx.regs()['pc']
        if hold is None and k == seen and wk <= pc < wk_end:
            stall += 1                                  # a key wait with no beep: a warning screen (PNM, PCF)
            if stall >= 50:
                zx.image(OUT / f'{name}-warn{seen}.png')
                stall = 0
                zx.set_keys(SPACE)
                zx.run_frames(3)
                frames += 3
                snd = zx.audio(RATE)
                sound.append(snd)
                samples += len(snd)
                zx.set_keys([0] * 8)
            continue
        stall = 0
        if hold is None and k > seen and wk <= pc < wk_end:
            seen = k
            zx.image(OUT / f'{name}-p{k}.png')
            hold = 30                                   # about 0.6 s with the result on screen
        elif hold is not None:
            hold -= 1
            if hold == 0:
                hold = None
                if seen >= photos:
                    done_after = 25
                else:
                    zx.set_keys(SPACE)
                    zx.run_frames(3)
                    frames += 3
                    snd = zx.audio(RATE)
                    sound.append(snd)
                    samples += len(snd)
                    zx.set_keys([0] * 8)
    ff.stdin.close()
    ff.wait()
    pcm = np.concatenate(sound).astype(np.int16)
    wav = OUT / f'{name}.wav'
    with wave.open(str(wav), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(pcm.tobytes())
    mp4 = OUT / f'{name}.mp4'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw), '-i', str(wav), '-c:v', 'libx264', '-pix_fmt',
                    'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', str(mp4)], check=True)
    raw.unlink()
    print(f'{name}: {seen}/{photos} photos, {frames} frames, {len(pcm) / RATE:.1f} s -> {mp4.name}', flush=True)


Z80N = {'Z80NTIME': ZB / 'Z80NTIME.TAP', 'LDPIRX2': ZB / 'LDPIRX2.TAP', 'LDPIRX3': ZB / 'LDPIRX3.TAP', 'Z80NFLAG': ZB / 'Z80NFLAG.TAP', 'Z80NFLG2': ZB / 'Z80NFLG2.TAP'}


def run48(name):
    """Strobe Fern's three print through the ROM, so they need BASIC: load the tape on omse-ai's 48K, as her own
    run_omse.py does, and record the beeper there (the nextreg writes go nowhere on a 48K; port FE is the same)."""
    sys.path.insert(0, str(HERE.parent))
    from speccy import Speccy
    syms = symbols(TAPES[name][1])
    zx = Speccy()
    zx.insert_tape(Z80N[name].read_bytes())
    zx.type('LOAD ""\n')
    zx.record_audio(True)
    frames = 0
    while frames < a.max_frames and zx.peek(syms['pb_photo']) < 1:
        zx.run(10)
        frames += 10
    zx.run(50)                                          # past END, the result on screen
    zx.shot(str(OUT / f'{name}-p1.png'))
    zx.hold('SPACE', 10)
    zx.run(25)
    zx.write_wav(str(OUT / f'{name}.wav'), rate=RATE)
    print(f'{name} (48K): {zx.peek(syms["pb_photo"])}/1 photos, {frames} frames -> {name}.wav', flush=True)


for name in (a.names or list(TAPES)):
    (run48 if name in Z80N else run)(name)
