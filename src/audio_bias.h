// Causal audio bias controller. Fern; Python reference: zxaudio.py.
// Inspired by Melissa O'Neill's OMSE's return-to-zero policy, not its
// activity detector. No hardware levels are changed by this output stage.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace zxaudio {
constexpr double pi = 3.141592653589793238462643383279502884;
enum State { QUIET, ATTACK, ACTIVE, RELEASE };

struct Bias {
    uint32_t hold = 12000, release = 12000, attack = 96;
    uint32_t idle = 0, phase = 0;
    double pole = 0, gain = 1;
    double previous = 0, mean = 0, saved = 0, bias = 0, start = 0, target = 0;
    bool initialized = false, centered = false;
    State state = QUIET;

    void configure(int rate, double hm = 250, double rm = 250, double am = 2,
                   double p = -1, bool already_centered = false) {
        auto count = [rate](double ms) { return (uint32_t)std::max(1.0, std::floor(rate * ms / 1000 + 0.5)); };
        hold = count(hm); release = count(rm); attack = count(am);
        centered = already_centered;
        pole = p < 0 ? std::exp(-2 * pi / rate) : p;
        gain = p < 0 && !centered ? (1 + pole) / 2 : 1;
        reset();
    }
    void reset() {
        initialized = false;
        previous = mean = saved = bias = start = target = 0;
        idle = phase = 0; state = QUIET;
    }
    static double ease(uint32_t n, uint32_t total) {
        return n >= total ? 1.0 : (1 - std::cos(pi * n / total)) / 2;
    }
    double step(double x, int activity = -1) {
        if (!initialized) {
            initialized = true;
            previous = bias = start = target = x;
            mean = saved = centered ? 0 : x;
            return 0;
        }
        const bool changed = activity < 0 ? x != previous : activity != 0;
        idle = changed ? 0 : std::min(hold, idle + 1);
        if (changed && (state == QUIET || state == RELEASE)) {
            start = bias;
            mean = saved;
            phase = 0;
            state = ATTACK;
        }
        if (state == ATTACK || state == ACTIVE) {
            if (!centered) mean = pole * mean + (1 - pole) * previous;
            if (changed) saved = mean;
            if (idle >= hold) {
                start = bias;
                target = x;
                phase = 0;
                state = RELEASE;
            }
        }
        switch (state) {
            case ATTACK:
                bias = start + (mean - start) * ease(phase, attack);
                if (phase >= attack) { bias = mean; state = ACTIVE; }
                else ++phase;
                break;
            case ACTIVE:
                bias = mean;
                break;
            case RELEASE:
                bias = start + (target - start) * ease(phase, release);
                if (phase >= release) { bias = x; state = QUIET; }
                else ++phase;
                break;
            case QUIET:
                bias = x;
                break;
        }
        previous = x;
        return gain * (x - bias);
    }
};

inline int16_t pcm16(double x) {
    return (int16_t)std::clamp(x, -32768.0, 32767.0);  // truncate, never wrap
}
}  // namespace zxaudio
