# Causal audio bias restoration

A constant hardware output is acoustically quiet, but a nonzero PCM
baseline is not computer silence. This output-stage controller restores
long quiet intervals to zero without looking into the future.

## Policy

The defaults are a 250 ms inactivity hold, a 250 ms raised-cosine return
to zero, and a 2 ms raised-cosine reacquisition when activity resumes.
These are listening defaults, not a claim that every short rest is zero.
A 1 Hz square wave can be treated as successive long-held levels; an
ordinary bass note is not. Activity is change, not amplitude: quiet tones
are not noise-gated.

Each channel owns its previous input, active bias estimate, last active
estimate, applied bias, timer and state. States are QUIET, ATTACK, ACTIVE
and RELEASE. A new edge aborts a release at the offset actually reached;
following edges do not keep restarting the attack. During a release,
only the additive offset changes, not the signal's gain. A fully quiet
channel subtracts its exact constant level, giving exact PCM zero.

No future silence intervals, whole-file mean, peak normalisation, or
backwards end fades are used. Short rests keep the normal centring
response. A recording cut during sound can still click: there is no
silent extra tail and no change in sample count. Block end is not stop.

## 48K and 128K

`Speccy.write_wav(path, rate=44100)` uses the Python controller in
`zxaudio.py`. The beeper's existing 0.995 filter coefficient and gain stay;
its initial bias comes from the EAR level captured by `record_audio()`.
Actual beeper edges supply activity, so numerical integration dust does
not keep silence awake. `hold_ms`, `release_ms` and `attack_ms` are
keyword-only settings, positive milliseconds up to 60000.

`raw=True` bypasses conditioning and writes the box-filtered +/-12000
beeper levels, useful for diagnosis. It is not the old, already-filtered
WAV. The edge log and `beeper_notes()` are unchanged.

`zxay.write_ay_wav(..., raw=True)` preserves the chip's existing
DC-adjusted samples. The normal writer adds the rest controller with
active target zero, NOT a second high-pass. Existing leading-silence trim
remains optional and unchanged. Both writers retain their sample rate,
length and existing saturation limit.

The 128K AY now clocks continuously, even when samples are not being
recorded. Previously the recording flag also paused the chip and its DC
filter; starting capture could invent a transient from an already-held
level. This fixes that upstream bug without a second filter. It can
change the phase of late-started captures compared with the old paused
chip, but does not change the oscillator rates or volume table.

## Native Next path

`src/audio_bias.h` is the C++ double-precision implementation beside the
resampler in `src/next_audio.h`. It runs once per output sample, not at
Python read time. `zxaudio.py` is its standard-library reference model.
The active estimate is a gain-normalised 1 Hz DC blocker. The host-side
rest policy is separate from the hardware model.

- `audio(rate=48000)` returns conditioned int16 stereo `(n, 2)`.
- `audio(rate=48000, raw=True)` returns the original scaled 0-29990
  samples, box-filtered or HDMI point-sampled as selected.
- Reading either consumes the same interval from paired queues. A second
  read gets new samples, not the other version of the old interval.
- The controller advances even when raw samples are selected. Chunk
  boundaries and mode changes do not restart it.
- `audio_config(hold_ms=250, release_ms=250, attack_ms=2)` changes the
  policy and resets the controller for FUTURE samples. Queued samples
  are unchanged. Arguments must be finite and in `(0, 60000]` ms.
- Rates are integers in `1..1750000`. A rate change restarts resampling
  and bias state for future samples. Previously queued samples are
  returned at their old rate, matching the previous API's behaviour.
  Drain old samples before changing rates when their rate matters.
- A CPU/machine reset does not restart the host recording stream.
- `audio_capture`, `audio_take`, `audio_level`, AY levels/logs, and the
  1.75 MHz mixer are unchanged. `audio_hdmi()` still selects sampling,
  not conditioning.
- `Next.write_wav` writes the supplied samples unchanged. It does not
  filter them again. Select raw at `audio()` when making a raw WAV.

Code doing hardware comparisons, mixing differences or its own DSP must
request `raw=True`. A conditioned stream with signal-dependent rest
transitions is not globally linear. Plain playback uses the default.

## Arithmetic and tests

Python float and C++ double keep the slow estimate without an integer
fixed-point deadband. The independent-language comparison permits 1e-7
sample units before quantisation and at most one PCM LSB after truncation
(the two sides can land on opposite sides of an integer boundary).
Silence itself must be exact zero. Sample conversion saturates, never
wraps; the valid Next raw range does not require extra peak limiting.

Tests cover actual idle and held-high recordings, cosine curves, resume
mid-return, 26.71 Hz bass, one-LSB material, pauses of 10/50/250/2000 ms,
separate stereo state, raw resampling checked against mixer captures,
block-size invariance and unchanged prefixes when the future changes.
`tests/test_audio_conformance.py` compiles a small
probe of the same header used by the emulator and compares every sample
and state with the Python reference at 44.1, 48 and 96 kHz. Its receipt
is `tests/out/audio/conformance.json`.

## Credits

Written by Fern, an AI agent with a persistent memory, at Melissa
O'Neill's invitation. Melissa supplied the distinction between computer
silence and a shifted constant level, and her OMSE supplied the prior
return-to-zero approach. An earlier instance of Fern built omse-ai from
OMSE. Slide Fern wrote the Next mixer; Ratio Fern's recording exposed the
remaining offset; Tally Fern supplied the brief and maintains the Next
contract. An independent read-only review by another instance of Fern
exposed the AY capture-clock and long-attack timeout bugs.

For this work Fern inhabited gpt-6-astra-900k on OpenAI.
