"""Find the photo beeps in a recording of a probe sitting and pull out the frames they mark.

Melissa O'Neill's idea (Fri 6 Nov 2026): every probe tape beeps when its result screen is complete, so a whole sitting can be
recorded through a capture box, with sound, and handed over as one video. The code (spec in probes/NOTES.md, "The photo
beep"): SYNC 1800 Hz 200 ms, three digit tones of 600 + 100*d Hz, 120 ms each with 50 ms gaps (the tape ID's tens and
units, then the photo number), then END 1800 Hz 100 ms. The screen is static after END until the key, so a frame from
just after END shows the result.

Usage:  find_photos.py VIDEO [OUTDIR] [--after 0.5] [--wav] [--unmatched]
        (--wav: VIDEO is a WAV file; report the beeps only, extract nothing)

Writes OUTDIR/<NN>-<name>-p<k>.png for each beep found and prints a table. Needs ffmpeg and numpy. Tally Fern.
"""
import os, subprocess, sys, tempfile, wave
import numpy as np

NAMES = {1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4', 6: 'P6', 7: 'P7', 8: 'P8', 13: 'P13', 20: 'P20', 29: 'P2B', 60: 'Z80NTIME',
         62: 'LDPIRX2', 63: 'LDPIRX3', 64: 'Z80NFLAG', 65: 'Z80NFLG2', 70: 'PBD', 71: 'PNM', 72: 'PCF', 73: 'PUA', 74: 'PFB', 77: 'PSS', 81: 'P81', 82: 'P82', 91: 'PV1', 92: 'PV2', 93: 'PV3', 94: 'PV4', 95: 'PV5', 96: 'PV6'}
SYNC_HZ = 1800.0
RATE = 48000
WIN = int(0.040 * RATE)            # 40 ms analysis window
HOP = int(0.005 * RATE)            # 5 ms hop
NFFT = 16384                       # zero-padded, for a finer peak


def read_audio(path, is_wav):
    """Mono float samples at RATE, via ffmpeg (or straight from a WAV)."""
    if not is_wav:
        tmp = tempfile.mkdtemp(prefix='find_photos_')
        wav = os.path.join(tmp, 'audio.wav')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vn', '-ac', '1', '-ar', str(RATE),
                        '-acodec', 'pcm_s16le', wav], check=True)
        path = wav
    with wave.open(path, 'rb') as w:
        n, ch, rate, width = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype={1: np.uint8, 2: np.int16, 4: np.int32}[width]).astype(np.float64)
    if width == 1:
        a -= 128
    a = a.reshape(-1, ch).mean(axis=1)
    if rate != RATE:                                      # crude resample (only for hand-made WAVs)
        a = np.interp(np.arange(0, len(a), rate / RATE), np.arange(len(a)), a)
    return a


def tone_track(a):
    """Per hop: (time, frequency or 0). A window counts as tonal when one peak in 400-2200 Hz stands far above the rest."""
    win = np.hanning(WIN)
    freqs = np.fft.rfftfreq(NFFT, 1 / RATE)
    band = (freqs >= 400) & (freqs <= 2200)
    out = []
    rms = []
    for s in range(0, len(a) - WIN, HOP):
        x = a[s:s + WIN]
        x = x - x.mean()                                  # the Next's audio sits on a DC level (Hart's-tongue)
        rms.append(np.sqrt(np.mean(x * x)))
    floor = np.percentile(rms, 30) + 1e-9
    for i, s in enumerate(range(0, len(a) - WIN, HOP)):
        t = (s + WIN / 2) / RATE
        if rms[i] < 4 * floor:
            out.append((t, 0.0)); continue
        x = a[s:s + WIN]
        spec = np.abs(np.fft.rfft((x - x.mean()) * win, NFFT))
        b = spec[band]
        k = int(np.argmax(b))
        if b[k] < 8 * np.median(b):
            out.append((t, 0.0)); continue
        j = np.nonzero(band)[0][k]                          # parabolic interpolation on the peak
        if 0 < j < len(spec) - 1:
            y0, y1, y2 = spec[j - 1], spec[j], spec[j + 1]
            d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) != 0 else 0
        else:
            d = 0
        out.append((t, (j + d) * RATE / NFFT))
    return out


def runs(track):
    """Group consecutive tonal hops of one pitch (within 3%) into (start, end, median frequency)."""
    res, cur = [], []
    for t, f in track:
        if f and cur and abs(f - np.median([g for _, g in cur])) <= 0.03 * f:
            cur.append((t, f))
        else:
            if len(cur) >= 4:                               # at least 20 ms of steady tone
                res.append((cur[0][0], cur[-1][0], float(np.median([g for _, g in cur]))))
            cur = [(t, f)] if f else []
    if len(cur) >= 4:
        res.append((cur[0][0], cur[-1][0], float(np.median([g for _, g in cur]))))
    return res


def digit(f):
    d = round((f - 600) / 100)
    return d if 0 <= d <= 9 and abs(f - (600 + 100 * d)) <= 40 else None


def is_sync(f):
    return abs(f - SYNC_HZ) <= 0.05 * SYNC_HZ


def decode(rs):
    """Find SYNC, three digits, END in the run list. Returns [(t_end, tape, photo)]."""
    rs = [r for r in rs if r[1] - r[0] + 0.04 >= 0.09]       # drop edge blips (~60 ms) a capture path adds between tones
    found = []
    i = 0
    while i < len(rs):
        s0, s1, f = rs[i]
        if is_sync(f) and 0.14 <= s1 - s0 + 0.04 <= 0.30 and i + 4 < len(rs):
            ds = [digit(rs[i + k][2]) for k in (1, 2, 3)]
            e0, e1, ef = rs[i + 4]
            spans_ok = all(0.07 <= rs[i + k][1] - rs[i + k][0] + 0.04 <= 0.20 for k in (1, 2, 3))
            gaps_ok = all(0.0 <= rs[i + k][0] - rs[i + k - 1][1] <= 0.15 for k in (1, 2, 3, 4))
            if None not in ds and is_sync(ef) and spans_ok and gaps_ok:
                found.append((e1 + 0.04, 10 * ds[0] + ds[1], ds[2]))
                i += 5; continue
        i += 1
    return found


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    is_wav = '--wav' in sys.argv
    after = 0.5
    if '--after' in sys.argv:
        after = float(sys.argv[sys.argv.index('--after') + 1]); args = [a for a in args if a != str(after)]
    if not args:
        print(__doc__); sys.exit(1)
    video = args[0]
    is_wav = is_wav or video.lower().endswith('.wav')      # a sound-only file: report, extract nothing
    outdir = args[1] if len(args) > 1 else os.path.splitext(video)[0] + '-photos'
    rs = runs(tone_track(read_audio(video, is_wav)))
    beeps = decode(rs)
    if '--unmatched' in sys.argv:                          # 1800 Hz tones that weren't part of a whole code
        used = {round(t, 1) for t, _, _ in beeps}
        for s0, s1, f in rs:
            if is_sync(f) and not any(abs(s1 + 0.04 - u) < 0.2 or (s0 < u and u - s0 < 1.2) for u in used):
                m, sec = divmod(s0, 60)
                print(f'unmatched 1800 Hz tone at {int(m)}:{sec:05.2f} for {s1 - s0 + 0.04:.2f} s')
    if not beeps:
        print('no photo beeps found'); sys.exit(2)
    if not is_wav:
        os.makedirs(outdir, exist_ok=True)
    print(f'{"time":>9}  tape  name       photo  file')
    seen = {}
    for t, tape, photo in beeps:
        name = NAMES.get(tape, f'id{tape:02d}')
        n = seen.get((tape, photo), 0); seen[(tape, photo)] = n + 1
        fn = f'{tape:02d}-{name}-p{photo}' + (f'-{"abcdefghij"[n]}' if n else '') + '.png'   # P2B's runs repeat
        if not is_wav:
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t + after:.3f}', '-i', video, '-frames:v', '1',
                            os.path.join(outdir, fn)], check=True)
        m, s = divmod(t, 60)
        print(f'{int(m):3d}:{s:05.2f}  {tape:4d}  {name:<9}  {photo:5d}  {fn if not is_wav else "-"}')


if __name__ == '__main__':
    main()
