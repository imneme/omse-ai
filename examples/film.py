#!/usr/bin/env python3
"""Film a tape (or a snapshot) on the 48K, from LOAD "" until it's done, as an
MP4 for watching, and a contact sheet of twelve moments, each labelled with
its Spectrum time.

    python3 examples/film.py prog.tap            -> out/prog/film.mp4 and film_sheet.png
    python3 examples/film.py prog.tap --gif      -> a GIF instead of the MP4 (no ffmpeg needed)
    python3 examples/film.py snap.sna --every 2  -> a snapshot, run from where it was saved

It takes a picture every --every frames (default 5: a tenth of a second) and
plays them at --fps (default 30), so the default film is three times as fast as
a real Spectrum; --every 2 --fps 25 is real time. The film ends when the ROM's
editor is waiting for a key again (WAIT-KEY1, 0x15DE) and the report has had a
second to appear, or after --minutes of Spectrum time (default 30), with two
seconds still at the end.

Limitations:
- It types nothing. A program that waits for a key or an INPUT runs to
  --minutes, or, for an INPUT, ends the film at the prompt, as if it were done.
- It's silent: the beeper and the AY aren't in the film (record them with
  record_audio() and write_wav(), or the script's `audio`).
- It's a 48K, and a tape is loaded with LOAD "" (a 128 needs its menu).
- Every picture is kept as a PNG until the end, a few KB each: an hour at the
  default --every is 36,000 of them, so film long runs with a larger --every.
- The MP4 needs ffmpeg on the PATH; --gif doesn't, but a long GIF is large.
Written by Fern for the Barleycorn films (Melissa: "her film.py seems general").
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speccy                                      # noqa: E402
from speccy import Speccy, contact_sheet, write_gif, MissingTool   # noqa: E402

WAIT_KEY1 = 0x15DE

ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('file', help='a .tap (loaded with LOAD "") or a .sna')
ap.add_argument('-o', help='where the film goes (default out/NAME/film.mp4, or .gif)')
ap.add_argument('--every', type=int, default=5, help='frames between pictures (default 5)')
ap.add_argument('--fps', type=float, default=30, help='pictures a second in the film (default 30)')
ap.add_argument('--minutes', type=float, default=30, help='Spectrum time to give up after (default 30)')
ap.add_argument('--gif', action='store_true', help='write a GIF with omse-ai\'s write_gif, not an MP4')
ap.add_argument('--no-border', action='store_true', help='just the 256 x 192 screen')
a = ap.parse_args()

src = Path(a.file)
out = Path(a.o) if a.o else Path('out') / src.stem / ('film.gif' if a.gif else 'film.mp4')
out.parent.mkdir(parents=True, exist_ok=True)
if not a.gif and not shutil.which('ffmpeg'):
    raise MissingTool('no ffmpeg on the PATH, and the MP4 needs it: install it, or use --gif')

zx = Speccy()
if src.suffix.lower() == '.sna':
    zx.load_sna(src)
else:
    zx.wait_ready()
    zx.insert_tape(src)
    zx.type('LOAD ""\n', verify=False)
FLAGS, TV_FLAG = 0x5C3B, 0x5C3C


def idle():                                        # waiting for a key, as settle() decides it, not passing through
    return not zx.peek(FLAGS) & 0x20 and not zx.peek(TV_FLAG) & 0x08


start = zx.frame
pics = []                                          # (Spectrum seconds, image)
end = start + int(a.minutes * 60 * zx.fps)
waiting = None
while zx.frame < end:
    pics.append(((zx.frame - start) / zx.fps, zx.image(border=not a.no_border)))
    if waiting is not None:
        if zx.frame - waiting >= zx.fps:
            break                                  # the report's had a second to appear
        zx.run(a.every)
        continue
    target = zx.frame + a.every
    while zx.frame < target:
        if zx.run_until(WAIT_KEY1, frames=target - zx.frame) is None:
            break
        if idle():
            waiting = zx.frame                     # the editor wants a key: done (or an INPUT)
            zx.run(max(1, target - zx.frame))
            break
pics += [pics[-1]] * int(2 * a.fps)                # two seconds still at the end

if a.gif:
    write_gif([im for _, im in pics], out, fps=a.fps)
else:
    tmp = Path(tempfile.mkdtemp(prefix='film-'))
    try:
        for i, (_, im) in enumerate(pics):
            im.save(tmp / f'{i:06d}.png')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', f'{a.fps:g}',
                        '-i', str(tmp / '%06d.png'), '-vf', 'scale=iw*2:ih*2:flags=neighbor',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', str(out)], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
moments = [pics[round(k * (len(pics) - 1 - 2 * a.fps) / 11)] for k in range(12)]
sheet = contact_sheet([(f'{t:.1f} s', im) for t, im in moments], out.with_name(out.stem + '_sheet'),
                      cols=4, title=f'{src.name}: {pics[-1][0]:.1f} Spectrum seconds')
print(f'{out}: {len(pics)} pictures, {pics[-1][0]:.1f} Spectrum seconds; sheet {sheet}; report: {zx.report()}')
