"""Causal audio bias restoration; reference for the Next branch's audio_bias.h.

Fern, building on Melissa O'Neill's OMSE: observe inactivity, then ease
silence to computer zero. No look-ahead, amplitude gate or gain control.
Times are milliseconds; process() boundaries have no signal meaning.

Next's native implementation is tested against this model within 1e-7
sample units before quantisation, and one PCM LSB after truncation.
Python float and C++ double deliberately retain the low-frequency bias
estimate without fixed-point deadbands. No third-party dependencies.
"""
import math

QUIET, ATTACK, ACTIVE, RELEASE = range(4)


def pcm16(value, limit=32767):
    """Truncate toward zero, then saturate (never wrap a loud sample)."""
    return max(-limit - (limit == 32767), min(limit, int(value)))


class BiasController:
    def __init__(self, rate, *, hold_ms=250, release_ms=250, attack_ms=2,
                 pole=None, centered=False, initial=None):
        if not isinstance(rate, int) or isinstance(rate, bool) or not 0 < rate <= 1750000:
            raise ValueError('audio rate must be an integer in 1..1750000')
        times = (hold_ms, release_ms, attack_ms)
        if any(not math.isfinite(t) or not 0 < t <= 60000 for t in times):
            raise ValueError('audio timings must be finite milliseconds in (0, 60000]')
        if pole is not None and (not math.isfinite(pole) or not 0 <= pole < 1):
            raise ValueError('audio pole must be in [0, 1)')
        self.rate = rate
        self.hold, self.release, self.attack = (max(1, int(rate * t / 1000 + 0.5)) for t in times)
        self.centered = centered
        self.pole = math.exp(-2 * math.pi / rate) if pole is None else pole
        # The existing beeper pole/gain stays exact; Next's new 1 Hz filter
        # is gain-normalised. Already-centred AY gets no additional filter.
        self.gain = (1 + self.pole) / 2 if pole is None and not centered else 1.0
        self.reset(initial)

    def reset(self, initial=None):
        self.previous = initial
        self.mean = self.saved = 0.0 if self.centered or initial is None else float(initial)
        self.bias = self.start = 0.0 if initial is None else float(initial)
        self.target = self.bias
        self.idle = self.phase = 0
        self.state = QUIET

    @staticmethod
    def _ease(position, length):
        if position >= length:
            return 1.0
        return (1 - math.cos(math.pi * position / length)) / 2

    def step(self, value, *, activity=None):
        """One sample. Optional activity is a source edge flag, not loudness.

        A beeper adapter supplies actual edges instead of floating-point
        dust from integrating a flat level. With no hint, exact input
        changes are activity. Each channel owns an independent controller.
        """
        x = float(value)
        if not math.isfinite(x):
            raise ValueError('audio sample must be finite')
        if self.previous is None:
            self.reset(x)
            return 0.0
        changed = x != self.previous if activity is None else bool(activity)
        self.idle = 0 if changed else min(self.hold, self.idle + 1)
        if changed and self.state in (QUIET, RELEASE):
            self.start = self.bias
            self.mean = self.saved
            self.phase = 0
            self.state = ATTACK

        if self.state in (ATTACK, ACTIVE):
            if not self.centered:
                # Delayed low-pass form of y=x-x_prev+R*y_prev. Initialising
                # mean from the actual input removes the artificial step.
                self.mean = self.pole * self.mean + (1 - self.pole) * self.previous
            if changed:
                self.saved = self.mean
            if self.idle >= self.hold:
                self.start, self.target, self.phase = self.bias, x, 0
                self.state = RELEASE

        if self.state == ATTACK:
            q = self._ease(self.phase, self.attack)
            self.bias = self.start + (self.mean - self.start) * q
            if self.phase >= self.attack:
                self.bias = self.mean
                self.state = ACTIVE
            else:
                self.phase += 1
        elif self.state == ACTIVE:
            self.bias = self.mean
        elif self.state == RELEASE:
            q = self._ease(self.phase, self.release)
            self.bias = self.start + (self.target - self.start) * q
            if self.phase >= self.release:
                self.bias = x
                self.state = QUIET
            else:
                self.phase += 1
        else:
            self.bias = x                         # exact zero, not asymptotic

        self.previous = x
        return self.gain * (x - self.bias)

    def process(self, samples):
        return [self.step(x) for x in samples]
