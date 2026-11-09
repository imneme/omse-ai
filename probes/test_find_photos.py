"""A self-test for find_photos.py: synthesise a 'sitting' with beeps as the spec makes them (square waves, as a beeper
does), with noise, key clicks and a stray tone between, encode it as an mp4 with AAC (as a capture box might), and check
the decoder finds every beep with the right tape and photo, at the right time. Tally Fern."""
import os, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_photos as fp

R = fp.RATE
rng = np.random.default_rng(6)


def square(f, dur, amp=0.25):
    t = np.arange(int(dur * R)) / R
    return amp * np.sign(np.sin(2 * np.pi * f * t))


def silence(dur):
    return np.zeros(int(dur * R))


def beep(tape, photo):
    parts = [square(1800, 0.200), silence(0.050)]
    for d in (tape // 10, tape % 10, photo):
        parts += [square(600 + 100 * d, 0.120), silence(0.050)]
        if (tape + d) % 2:                                   # a ~60 ms blip at a tone's edge, as Melissa O'Neill's capture had
            parts[-1] = square(600 + 100 * d - 60, 0.050, 0.15)
    parts += [square(1800, 0.100)]
    return np.concatenate(parts)


def click():
    return np.concatenate([0.3 * rng.standard_normal(int(0.004 * R)), silence(0.05)])


def build():
    plan = [(29, 1), (29, 2), (82, 1), (82, 3), (77, 2), (63, 1), (92, 1), (20, 1)]
    segs, expect, t = [], [], 0.0
    for i, (tape, ph) in enumerate(plan):
        lead = silence(2.0 + i * 0.37)
        clicks = np.concatenate([click() for _ in range(5)])
        stray = square(1000, 0.4, 0.1) if i % 3 == 0 else silence(0.4)    # a lone tone that isn't a code
        b = beep(tape, ph)
        for s in (lead, clicks, stray, silence(0.3)):
            segs.append(s); t += len(s) / R
        segs.append(b); t += len(b) / R
        expect.append((t, tape, ph))
        segs.append(silence(1.5)); t += 1.5
    a = np.concatenate(segs)
    a = a + 0.01 * rng.standard_normal(len(a))
    a = a + 0.2                                            # a DC level, as omse-ai's (and maybe HDMI) audio has
    k = np.ones(5) / 5                                     # a gentle low-pass, like an analogue path
    return np.convolve(a, k, mode='same'), expect


def main():
    a, expect = build()
    tmp = tempfile.mkdtemp(prefix='fp_test_')
    wav = os.path.join(tmp, 'sitting.wav')
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(R)
        w.writeframes((np.clip(a, -1, 1) * 32000).astype(np.int16).tobytes())
    dur = len(a) / R
    mp4 = os.path.join(tmp, 'sitting.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=size=320x240:rate=50:duration={dur:.2f}',
                    '-i', wav, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest', mp4],
                   check=True)
    got = fp.decode(fp.runs(fp.tone_track(fp.read_audio(mp4, False))))
    ok = len(got) == len(expect)
    for (te, tape, ph), g in zip(expect, got):
        good = g[1] == tape and g[2] == ph and abs(g[0] - te) < 0.08
        ok &= good
        print(f'expect {tape:02d}/{ph} at {te:7.2f}   got {g[1]:02d}/{g[2]} at {g[0]:7.2f}   {"ok" if good else "WRONG"}')
    print('found', len(got), 'of', len(expect))
    print('ALL OK' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
