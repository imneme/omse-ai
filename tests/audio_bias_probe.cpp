// Test-only C ABI for the native header, independent of emulator plumbing.
#include "../src/audio_bias.h"
#include <cstddef>
extern "C" {
void* bias_new(int rate, double hold, double release, double attack, double pole, int centered) {
    auto* b = new zxaudio::Bias;
    b->configure(rate, hold, release, attack, pole, centered != 0);
    return b;
}
void bias_free(void* p) { delete static_cast<zxaudio::Bias*>(p); }
void bias_reset(void* p) { static_cast<zxaudio::Bias*>(p)->reset(); }
void bias_quantize(const double* input, int16_t* output, size_t count) {
    for (size_t i = 0; i < count; ++i) output[i] = zxaudio::pcm16(input[i]);
}
void bias_process(void* p, const double* input, double* output, int* state, size_t count) {
    auto& b = *static_cast<zxaudio::Bias*>(p);
    for (size_t i = 0; i < count; ++i) {
        output[i] = b.step(input[i]);
        state[i] = b.state;
    }
}
}
