"""Seeing the AY-3-8912: register writes -> notes -> a piano roll (and a WAV).

The core logs every AY register write as (T-state, register, value).  The AY
on a 128 runs at CPU/2 = 1.77345 MHz; a channel's tone is clock / (16 * period).

    from zxay import ay_notes, piano_roll, write_ay_wav
    notes = ay_notes(zx)                 # [(channel, start_s, dur_s, midi, volume)]
    piano_roll(notes, 'out/roll.png')
    write_ay_wav(zx, 'out/tune.wav')     # needs zx.record_ay() first
"""
import ctypes
import math
from pathlib import Path

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
CH_COLOURS = [(230, 90, 80), (90, 200, 110), (100, 150, 240)]   # A red, B green, C blue


def note_name(m):
    return f'{NAMES[m % 12]}{m // 12 - 1}'


def ay_log(zx, clear=False):
    n = zx.lib.zx_ay_log_len(zx.z)
    buf = (ctypes.c_uint64 * max(n, 1))()
    zx.lib.zx_ay_log_get(zx.z, buf)
    if clear:
        zx.lib.zx_ay_log_clear(zx.z)
    return [(v >> 16, (v >> 8) & 0xFF, v & 0xFF) for v in buf[:n]]


def ay_notes(zx, log=None, t0=None, min_dur=0.02):
    """Replay the register writes into per-channel notes.  A note starts when
    the pitch changes or the volume goes *up* (an attack); the same pitch
    getting quieter is the note decaying.  Returns [(ch, start_s, dur_s, midi,
    vol)] with vol = the note's peak, 0-15, or 16 for 'envelope'."""
    log = ay_log(zx) if log is None else log
    if not log:
        return []
    clock = zx.clock / 2
    t0 = log[0][0] if t0 is None else t0
    regs = [0] * 16
    regs[7] = 0xFF
    state = [None, None, None]       # (start_t, midi, vol) per channel
    out = []

    def current(ch):
        period = regs[2 * ch] | ((regs[2 * ch + 1] & 0x0F) << 8)
        tone_on = not (regs[7] >> ch) & 1
        vol = regs[8 + ch]
        v = 16 if vol & 0x10 else vol & 0x0F
        if not tone_on or v == 0 or period == 0:
            return None
        f = clock / (16 * period)
        return round(69 + 12 * math.log2(f / 440)), v

    def close(ch, t):
        if state[ch]:
            st, m, v = state[ch]
            d = (t - st) / zx.clock
            if d >= min_dur:
                out.append((ch, (st - t0) / zx.clock, d, m, v))
            state[ch] = None

    last_vol = [0, 0, 0]
    for t, r, v in log:
        before = [current(c) for c in range(3)]
        if r < 16:
            regs[r] = v
        after = [current(c) for c in range(3)]
        for c in range(3):
            if after[c] == before[c] and not (r == 13 and after[c] and after[c][1] == 16):
                continue
            # the same pitch getting quieter is a note decaying, not a new note
            if (after[c] and before[c] and state[c] and after[c][0] == before[c][0]
                    and after[c][1] < last_vol[c] and after[c][1] != 16):
                last_vol[c] = after[c][1]
                continue
            close(c, t)
            if after[c]:
                state[c] = (t, after[c][0], after[c][1])
                last_vol[c] = after[c][1]
    t_end = log[-1][0] + int(0.1 * zx.clock)
    for c in range(3):
        close(c, t_end)
    return sorted(out, key=lambda n: (n[1], n[0]))


def piano_roll(notes, path, title=None, px_per_s=120, row_h=6):
    """Notes as bars: time across, pitch up, one colour per channel."""
    from speccy import pil
    Image, ImageDraw, _ = pil()
    if not notes:
        raise ValueError('no notes')
    lo = min(n[3] for n in notes) - 2
    hi = max(n[3] for n in notes) + 2
    end = max(n[1] + n[2] for n in notes)
    left, top = 56, 30 if title else 8
    W = left + int(end * px_per_s) + 16
    H = top + (hi - lo + 1) * row_h + 24
    im = Image.new('RGB', (W, H), (26, 24, 30))
    d = ImageDraw.Draw(im)
    from speccy import label_font
    font, tfont = label_font(11), label_font(14)
    if title:
        d.text((8, 6), title, fill=(235, 225, 205), font=tfont)
    for m in range(lo, hi + 1):
        y = top + (hi - m) * row_h
        black = NAMES[m % 12].endswith('#')
        d.rectangle([left, y, W - 8, y + row_h - 1], fill=(34, 32, 40) if black else (44, 42, 50))
        if m % 12 == 0:
            d.text((6, y - 5), note_name(m), fill=(200, 190, 170), font=font)
            d.line([left, y + row_h - 1, W - 8, y + row_h - 1], fill=(70, 66, 80))
    for s in range(int(end) + 1):
        x = left + s * px_per_s
        d.line([x, top, x, H - 20], fill=(60, 58, 70))
        d.text((x + 2, H - 18), f'{s}s', fill=(160, 150, 140), font=font)
    for ch, st, du, m, v in notes:
        x0 = left + st * px_per_s
        x1 = max(x0 + 2, left + (st + du) * px_per_s - 1)
        y = top + (hi - m) * row_h
        r, g, b = CH_COLOURS[ch]
        k = 1.0 if v == 16 else 0.45 + 0.55 * v / 15
        d.rectangle([x0, y, x1, y + row_h - 2], fill=(int(r * k), int(g * k), int(b * k)))
    for i, name in enumerate('ABC'):
        d.text((W - 90 + i * 26, 8), name, fill=CH_COLOURS[i], font=tfont)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def notes_text(notes, per_channel=True):
    """The notes as lines of text: 'A  0.00s  0.25s  C6 (v16)'."""
    lines = []
    for ch, st, du, m, v in notes:
        lines.append(f"{'ABC'[ch]}  {st:6.2f}s  {du:5.2f}s  {note_name(m):4} v{v}")
    return '\n'.join(lines)


def write_ay_wav(zx, path, trim=True, *, raw=False):
    """The AY samples collected while recording (zx.record_ay()), as a WAV.
    trim: drop the silence before the first sound (setup time, loading).
    raw: preserve the chip's existing DC-adjusted samples, without the
    causal rest controller. No second high-pass is applied in either mode.
    """
    import array
    import sys
    import wave
    from zxaudio import BiasController, pcm16
    n = zx.lib.zx_ay_samples_len(zx.z)
    buf = (ctypes.c_float * max(n, 1))()
    zx.lib.zx_ay_samples_get(zx.z, buf)
    xs = buf[:n]
    if trim and xs:
        quiet = xs[0]
        first = next((i for i, x in enumerate(xs) if abs(x - quiet) > 0.01), 0)
        xs = xs[max(0, first - 2205):]
        n = len(xs)
    controller = BiasController(zx.lib.zx_ay_rate(), centered=True)
    out = array.array('h', (pcm16(x * 32000, limit=32000) for x in
                           (xs if raw else controller.process(xs))))
    if sys.byteorder != 'little':
        out.byteswap()
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(zx.lib.zx_ay_rate())
        w.writeframes(out.tobytes())
    return path, n
