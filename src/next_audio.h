// next_audio.h: the Spectrum Next's sound, as core 3.02.02 makes it. Slide Fern, 6 Nov 2026.
//
// Three AY/YM chips (audio/ym2149.vhd) under TurboSound (audio/turbosound.vhd), four 8-bit DACs (audio/soundrive.vhd),
// the beeper, and the mixer (audio/audio_mixer.vhd), wired as zxnext.vhd wires them (6284-6430). The chips tick on a
// 1.75 MHz enable: every 16th 28 MHz edge (zxnext_top_issue2:1161-1180). The register files stay where nextcore.cpp
// keeps them (z.ay_reg, written through 0xFFFD/0xBFFD); this owns what makes the sound: each chip's divider, tone,
// noise and envelope generators and levels, TurboSound's pans, the DACs, the beeper bits, and the mixer's output, at
// every enable (13 bits a side, 0-5998), for a test to capture or a resampler to turn into audio at a rate.
#pragma once
#include <cstdint>
#include <cstring>
#include <vector>

namespace nextaudio {

static const uint8_t AY_VOL[16] = {0x00, 0x03, 0x04, 0x06, 0x0a, 0x0f, 0x15, 0x22,       // ym2149:104-109
                                   0x28, 0x41, 0x5b, 0x72, 0x90, 0xb5, 0xd7, 0xff};
static const uint8_t YM_VOL[32] = {0x00, 0x01, 0x01, 0x02, 0x02, 0x03, 0x03, 0x04,       // ym2149:111-117
                                   0x06, 0x07, 0x09, 0x0a, 0x0c, 0x0e, 0x11, 0x13,
                                   0x17, 0x1b, 0x20, 0x25, 0x2c, 0x35, 0x3e, 0x47,
                                   0x54, 0x66, 0x77, 0x88, 0xa1, 0xc0, 0xe0, 0xff};

// One chip's generators (ym2149.vhd with I_SEL_L = '1', as turbosound.vhd ties all three).
struct Ym {
    uint8_t div = 0, ndiv = 0;                  // cnt_div, noise_div (258-275)
    uint16_t tcnt[3] = {0, 0, 0};               // tone_gen_cnt
    uint8_t top[3] = {0, 0, 0};                 // tone_gen_op
    uint8_t ncnt = 0;                           // noise_gen_cnt
    uint32_t poly = 0;                          // poly17
    uint16_t ecnt = 0;                          // env_gen_cnt
    uint8_t eena = 0, evol = 0, einc = 0, ehold = 0;
    uint8_t lev[3] = {0, 0, 0};                 // the 5-bit levels A, B, C (439-498)

    void reset() { *this = Ym(); }

    void env_reset(uint8_t r13) {               // writing R13 (205-207, 335-337, 361-368)
        ecnt = 0;
        eena = 1;
        if (!(r13 & 4)) { evol = 31; einc = 0; } else { evol = 0; einc = 1; }
        ehold = 0;
    }

    // One ENA tick. Every process in the VHDL sees the others' values from before the edge; here each part updates
    // in turn but reads only what it may (the envelope step uses env_ena as it stood before this tick), and the
    // levels take the new tone, noise and envelope values. Net effect, as Speccy-Zone measured in review: the output
    // comes about two chip ticks (2/1.75 MHz, ~1.1 us) earlier than the VHDL's, the same everywhere. Inaudible.
    void tick(const uint8_t* r) {
        bool ena_div = false, ena_noise = false;
        if (div == 0) {
            div = 7;
            ena_div = true;
            if (ndiv) ena_noise = true;
            ndiv ^= 1;
        } else {
            div--;
        }
        if (ena_noise) {                        // (277-297)
            const int comp = (r[6] & 0x1E) ? (r[6] & 0x1F) - 1 : 0;
            if (ncnt >= comp) {
                ncnt = 0;
                const uint32_t fb = (poly & 1) ^ ((poly >> 2) & 1) ^ (poly == 0 ? 1 : 0);
                poly = (fb << 16) | (poly >> 1);
            } else {
                ncnt++;
            }
        }
        if (ena_div) {                          // (299-322)
            for (int i = 0; i < 3; i++) {
                const int f = ((r[2 * i + 1] & 15) << 8) | r[2 * i];
                const int comp = (f >> 1) ? f - 1 : 0;
                if (tcnt[i] >= comp) { tcnt[i] = 0; top[i] ^= 1; }
                else tcnt[i]++;
            }
        }
        const uint8_t step = eena;
        if (ena_div) {                          // (324-350)
            const int f = (r[12] << 8) | r[11];
            const int comp = (f >> 1) ? f - 1 : 0;
            if (ecnt >= comp) { ecnt = 0; eena = 1; }
            else { ecnt++; eena = 0; }
        } else {
            eena = 0;
        }
        if (step) {                             // (359-437)
            const int v = evol;
            const bool bot = v == 0, bot1 = v == 1, top1 = v == 30, topv = v == 31;
            if (!ehold) evol = (v + (einc ? 1 : 31)) & 31;
            const uint8_t s = r[13];
            if (!(s & 8)) {
                if ((!einc && bot1) || (einc && topv)) ehold = 1;
            } else if (s & 1) {
                if (!einc) { if (((s & 2) && bot) || (!(s & 2) && bot1)) ehold = 1; }
                else if (((s & 2) && topv) || (!(s & 2) && top1)) ehold = 1;
            } else if (s & 2) {
                if (!einc) {
                    if (bot1) ehold = 1;
                    if (bot) { ehold = 0; einc = 1; }
                } else {
                    if (top1) ehold = 1;
                    if (topv) { ehold = 0; einc = 0; }
                }
            }
        }
        const int noise = poly & 1;             // (439-498)
        for (int i = 0; i < 3; i++) {
            const bool mixed = (((r[7] >> i) & 1) || top[i]) && (((r[7] >> (3 + i)) & 1) || noise);
            const uint8_t v = r[8 + i];
            lev[i] = !mixed ? 0 : (v & 0x10) ? evol : (v & 15) ? (((v & 15) << 1) | 1) : 0;
        }
    }

    void out(bool ay, int o[3]) const {         // (520-532)
        for (int i = 0; i < 3; i++) o[i] = ay ? AY_VOL[lev[i] >> 1] : YM_VOL[lev[i]];
    }
};

struct Audio {
    Ym ym[3];
    uint8_t pan[3] = {3, 3, 3};                 // TurboSound's psgN_pan, bit 1 L, bit 0 R (turbosound:80-92)
    uint8_t dac[4] = {0x80, 0x80, 0x80, 0x80};  // SounDrive's channels A-D (soundrive:56-64)
    uint8_t ear = 0, mic = 0;                   // port 0xFE's b4 and b3 as written (zxnext:3557, 6410)
    uint16_t L = 0, R = 0;                      // the mixer's output (audio_mixer:73-86)
    bool capturing = false;                     // every enable's (L, R), for tests
    std::vector<uint16_t> cap;
    int rate = 0;                               // resampled output: a box filter over the enables...
    bool point = false;                         // ...or, true, the mixer's value at each output instant, as the
                                                // Next's HDMI encoder takes it (hdmidataencoder.v:198-205, its
                                                // averaging commented out): ultrasonics fold into the band
    uint64_t acc = 0;
    uint64_t sumL = 0, sumR = 0, nsum = 0;
    std::vector<int16_t> outbuf;

    void reset_psgs() {
        for (auto& y : ym) y.reset();
        for (auto& p : pan) p = 3;
    }

    // One 1.75 MHz enable. regs: the three register files; sel: the chosen chip; nr06/08/09: the next registers;
    // held: NR 0x06 PSG mode 11 (all three chips held in reset, zxnext:6286).
    void tick(const uint8_t regs[3][16], int sel, uint8_t nr06, uint8_t nr08, uint8_t nr09, bool held) {
        const bool ay = nr06 & 1, ts = nr08 & 2, acb = nr08 & 0x20;
        int ayL = 0, ayR = 0;
        for (int c = 0; c < 3; c++) {
            if (held) { ym[c].reset(); continue; }
            ym[c].tick(regs[c]);
            int o[3];
            ym[c].out(ay, o);
            const bool mono = (nr09 >> (5 + c)) & 1;              // nr_09_psg_mono (zxnext:5125)
            int l, r;
            if (mono) { l = r = o[0] + o[1] + o[2]; }             // (turbosound:146-150)
            else if (acb) { l = o[0] + o[2]; r = o[2] + o[1]; }
            else { l = o[0] + o[1]; r = o[2] + o[1]; }
            if (!(c == sel || ts)) { l = r = 0; }                  // (156-164)
            if (pan[c] & 2) ayL += l;                              // (316-327)
            if (pan[c] & 1) ayR += r;
        }
        const bool dac_on = nr08 & 8;                              // held at 0x80 while off (zxnext:6343)
        const int a = dac_on ? dac[0] : 0x80, b = dac_on ? dac[1] : 0x80;
        const int cc = dac_on ? dac[2] : 0x80, d = dac_on ? dac[3] : 0x80;
        const bool exc = (nr06 & 0x40) && (nr08 & 0x10);           // beep_spkr_excl (zxnext:6411)
        // beep_mic_final = ear_in xor (mic and issue2) xor mic (zxnext:6410): no tape input, so mic unless NR 0x08 b0,
        // gated here as the mixer runs, not when port 0xFE was written (Speccy-Zone's mutant 3)
        const bool micf = mic && !(nr08 & 1);
        const int beep = (ear && !exc ? 512 : 0) + (micf && !exc ? 128 : 0);
        L = (uint16_t)(beep + ayL + 4 * (a + b));                  // (audio_mixer:73-86)
        R = (uint16_t)(beep + ayR + 4 * (cc + d));
        if (capturing) { cap.push_back(L); cap.push_back(R); }
        if (rate > 0) {                                            // a box filter, 1.75 MHz to the rate
            sumL += L; sumR += R; nsum++;
            acc += (uint64_t)rate;
            if (acc >= 1750000) {
                acc -= 1750000;
                outbuf.push_back((int16_t)(point ? L * 5 : sumL * 5 / nsum));  // 0-5998 to 0-29990
                outbuf.push_back((int16_t)(point ? R * 5 : sumR * 5 / nsum));
                sumL = sumR = nsum = 0;
            }
        }
    }
};

}  // namespace nextaudio
