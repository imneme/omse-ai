// zxcore.cpp: a headless ZX Spectrum 48K / 128K, as a C library for Python.
//
// omse-ai (One More Spectrum Emulator, Accessible and Instrumented), begun
// 2026-09-27.  Derived from OMSE (One More Spectrum Emulator) by Melissa
// O'Neill, 2025:
//   - the beam-racing ULA, timing constants and SNA loading are from a
//     stripped-down 48K version of OMSE (the RETN-at-0x0072 trick included);
//   - the LD-BYTES / SA-BYTES tape traps, the CHAN-OPEN / RST 10 print
//     interception, the 128K paging, port decoding, AY hookup and the 128K
//     SNA layout are from OMSE itself.
// What changed: no SDL.  The screen is drawn into an indexed framebuffer
// (palette 0-15, BRIGHT as +8); the keyboard matrix is set by the caller;
// beeper edges and AY register writes are logged (and AY samples collected
// on request) so Python can write WAVs and piano rolls; snapshots can be
// saved at any frame; tapes come in as bytes and SAVE output is collected.
//
// 128K paging is done by *copying*: the CPU always sees a flat 64K (so Python
// can read memory directly), and a page switch swaps 16K between the flat view
// and the bank store.  Banks 5 and 2 live in the flat view at 0x4000/0x8000;
// if one is also paged in at 0xC000, writes are mirrored to both copies.
//
// Z80 and AY cores: floooh's chips z80.h and ay38910.h (zlib licence; the
// licence text is at the top of each, and z80.h carries OMSE's modification
// notice).  They are OMSE's copies, unchanged.

#define CHIPS_IMPL
#include "z80.h"
#include "ay38910.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr int SCREEN_START_COL = 6;       // in 8-pixel columns (48 px border)
constexpr int COLUMNS = 44;               // 352 px of visible line
constexpr int INT_AT = SCREEN_START_COL * 4;  // interrupt raised on line 0 here
constexpr int FLASH_FRAMES = 16;
constexpr int FB_W = COLUMNS * 8;         // 352
constexpr int FB_H = 288;                 // 48 lines of border above and below
constexpr int AY_RATE = 44100;

// ROM addresses (48K ROM, which is ROM 1 on a 128)
constexpr uint16_t ROM_RETN = 0x0072;      // RETN at the end of the NMI handler
constexpr uint16_t ROM_LD_BYTES_IN = 0x0562;  // LD-BYTES, just after PUSH SA/LD-RET
constexpr uint16_t ROM_SA_BYTES = 0x04C2;  // SA-BYTES entry
constexpr uint16_t ROM_RET = 0x0555;       // a RET (SA/LD-END is POP AF; RET)
constexpr uint16_t ROM_PRINT_A_2 = 0x15F2; // RST 10 jumps here
constexpr uint16_t ROM_CHAN_OPEN = 0x1601;

}  // namespace

struct ZX {
    uint8_t mem[65536];       // what the CPU sees
    z80_t cpu;
    uint64_t pins = 0;

    // model and timing
    int model = 48;
    int t_line = 224, lines = 312, screen_line0 = 64, int_len = 32;
    int clock = 3500000;

    // 128K
    uint8_t rom[2][0x4000];
    uint8_t bank[8][0x4000];  // store for banks not currently in the flat view
    int slot3 = 0;            // bank at 0xC000
    int rom_sel = 0;
    bool screen7 = false;
    bool locked = false;
    uint8_t last_7ffd = 0;

    // AY-3-8912
    ay38910_t ay;
    uint8_t ay_reg = 0;
    bool ay_record = false;
    std::vector<float> ay_samples;
    std::vector<uint64_t> ay_log;   // (t << 16) | (reg << 8) | value

    uint8_t keys[8];          // keyboard half-rows, active low
    uint8_t kempston = 0;     // port 0x1F, active high
    uint8_t border = 7;
    bool ear = false;

    int line = 0, cyc = 0;    // beam position
    uint64_t t = 0;           // T-states since power-on
    uint64_t frame = 0;
    int flash_count = FLASH_FRAMES;
    bool flash_inv = false;

    uint8_t fb[FB_W * FB_H];

    std::vector<uint8_t> tape;       // TAP bytes to LOAD from
    size_t tape_pos = 0;
    std::vector<uint8_t> tape_out;   // TAP bytes produced by SAVE
    uint32_t loads = 0, saves = 0;

    bool log_audio = false;
    std::vector<uint64_t> ear_edges; // T-state of every beeper toggle

    bool log_text = true;
    uint8_t cur_stream = 0;
    std::string text;                // characters printed to stream 2 (screen)

    // Execution map: every opcode fetch counted, while execmap_bank is paged at
    // 0xC000 (-1: always).  For code/data maps (SkoolKit's sna2ctl -m).
    bool execmap_on = false;
    int execmap_bank = -1;
    uint32_t execmap[65536];

    // Breakpoints on opcode fetch.  Hit when any M1 fetch lands in [lo,hi].
    std::vector<std::pair<uint16_t, uint16_t>> breaks;
    bool hit = false;
    uint16_t hit_pc = 0;
};

// -- 128K paging --------------------------------------------------------------

static void page_slot3(ZX& z, int nb) {
    if (nb == z.slot3) return;
    if (z.slot3 != 5 && z.slot3 != 2) memcpy(z.bank[z.slot3], z.mem + 0xC000, 0x4000);
    if (nb == 5) memcpy(z.mem + 0xC000, z.mem + 0x4000, 0x4000);
    else if (nb == 2) memcpy(z.mem + 0xC000, z.mem + 0x8000, 0x4000);
    else memcpy(z.mem + 0xC000, z.bank[nb], 0x4000);
    z.slot3 = nb;
}

static void page_rom(ZX& z, int r) {
    if (r == z.rom_sel) return;
    memcpy(z.mem, z.rom[r], 0x4000);
    z.rom_sel = r;
}

static void write_7ffd(ZX& z, uint8_t v) {
    if (z.model != 128 || z.locked) return;
    page_slot3(z, v & 7);
    page_rom(z, (v >> 4) & 1);
    z.screen7 = v & 0x08;
    z.locked = v & 0x20;
    z.last_7ffd = v;
}

// the bytes of a bank wherever it currently lives
static uint8_t* bank_ptr(ZX& z, int b) {
    if (b == 5) return z.mem + 0x4000;
    if (b == 2) return z.mem + 0x8000;
    if (b == z.slot3) return z.mem + 0xC000;
    return z.bank[b];
}

static inline void mem_write(ZX& z, uint16_t a, uint8_t v) {
    if (a < 0x4000) return;
    z.mem[a] = v;
    if (z.slot3 == 5) {
        if (a >= 0xC000) z.mem[a - 0x8000] = v;
        else if (a < 0x8000) z.mem[a + 0x8000] = v;
    } else if (z.slot3 == 2) {
        if (a >= 0xC000) z.mem[a - 0x4000] = v;
        else if (a >= 0x8000) z.mem[a + 0x4000] = v;
    }
}

// -- the screen -----------------------------------------------------------------

static inline int fb_first_line(const ZX& z) { return z.screen_line0 - 48; }

static void draw8(ZX& z) {
    const int row = z.line - fb_first_line(z);
    const int col = z.cyc >> 2;
    uint8_t* dst = &z.fb[row * FB_W + col * 8];
    const int sl = z.line - z.screen_line0;
    const int sc = col - SCREEN_START_COL;
    if (sl >= 0 && sl < 192 && sc >= 0 && sc < 32) {
        const uint8_t* scr = (z.model == 128 && z.screen7) ? bank_ptr(z, 7) : z.mem + 0x4000;
        uint16_t off = ((sl & 0xC0) << 5) | ((sl & 0x07) << 8) | ((sl & 0x38) << 2) | sc;
        uint8_t bits = scr[off];
        uint8_t attr = scr[0x1800 + (sl >> 3) * 32 + sc];
        uint8_t bright = (attr & 0x40) ? 8 : 0;
        uint8_t ink = (attr & 7) | bright;
        uint8_t paper = ((attr >> 3) & 7) | bright;
        if ((attr & 0x80) && z.flash_inv) {
            uint8_t tmp = ink; ink = paper; paper = tmp;
        }
        for (int i = 0; i < 8; i++) {
            dst[i] = (bits & (0x80 >> i)) ? ink : paper;
        }
    } else {
        memset(dst, z.border, 8);
    }
}

// -- ports --------------------------------------------------------------------

static void ay_write(ZX& z, uint16_t addr, uint8_t v) {
    uint64_t pins = AY38910_BDIR;
    if (addr & 0x4000) pins |= AY38910_BC1;   // 0xFFFD selects, 0xBFFD writes
    AY38910_SET_DATA(pins, v);
    ay38910_iorq(&z.ay, pins);
    if (addr & 0x4000) {
        z.ay_reg = v & 0x0F;
    } else {
        z.ay_log.push_back((z.t << 16) | ((uint64_t)z.ay_reg << 8) | v);
    }
}

static uint8_t ay_read(ZX& z, uint16_t addr) {
    uint64_t pins = 0;
    if (addr & 0x4000) pins |= AY38910_BC1;
    pins = ay38910_iorq(&z.ay, pins);
    return AY38910_GET_DATA(pins);
}

static uint8_t io_read(ZX& z, uint16_t addr) {
    if ((addr & 1) == 0) {  // ULA: keyboard (+ EAR on bit 6)
        uint8_t v = 0xBF;
        uint8_t rows = ~(addr >> 8);
        for (int r = 0; r < 8; r++) {
            if (rows & (1 << r)) v &= z.keys[r];
        }
        return v | (z.ear ? 0x40 : 0);
    }
    if (z.model == 128 && (addr & 0x8002) == 0x8000) return ay_read(z, addr);
    if ((addr & 0xE0) == 0) return z.kempston;  // Kempston joystick, 0x1F
    return 0xFF;
}

static void io_write(ZX& z, uint16_t addr, uint8_t v) {
    if ((addr & 1) == 0) {
        z.border = v & 7;
        bool e = v & 0x10;
        if (e != z.ear) {
            z.ear = e;
            if (z.log_audio) z.ear_edges.push_back(z.t);
        }
    }
    if (z.model == 128) {
        if ((addr & 0x8002) == 0x8000) ay_write(z, addr, v);
        else if ((addr & 0x8002) == 0x0000) write_7ffd(z, v);
    }
}

// -- tape traps ---------------------------------------------------------------

// Fetch and check one TAP block.  Returns false if the tape is exhausted.
// On mismatch the block is skipped and carry is cleared, as a real LD-BYTES
// would do; LD-CONTRL then asks again for the next header.
static bool trap_ld_bytes(ZX& z) {
    if (z.tape_pos + 2 > z.tape.size()) return false;  // no tape: let ROM wait
    z80_t& c = z.cpu;
    bool loading = c.af2 & Z80_CF;           // carry set: LOAD, reset: VERIFY
    uint8_t want = c.af2 >> 8;              // flag byte: 0x00 header, 0xFF data
    uint16_t len = c.de;
    uint16_t dst = c.ix;

    size_t blen = z.tape[z.tape_pos] | (z.tape[z.tape_pos + 1] << 8);
    size_t start = z.tape_pos + 2;
    z.tape_pos = start + blen;
    if (z.tape_pos > z.tape.size()) z.tape_pos = z.tape.size();
    bool ok = false;
    if (blen >= 2 && start + blen <= z.tape.size() && z.tape[start] == want) {
        uint8_t sum = 0;
        for (size_t i = 0; i < blen; i++) sum ^= z.tape[start + i];
        size_t n = blen - 2;                 // payload, without flag and checksum
        if (n > len) n = len;
        if (loading) {
            for (size_t i = 0; i < n; i++) mem_write(z, dst + i, z.tape[start + 1 + i]);
        }
        ok = (sum == 0) && (blen - 2 == len);
    }
    if (ok) c.f |= Z80_CF; else c.f &= ~Z80_CF;
    z.loads++;
    return true;
}

static void trap_sa_bytes(ZX& z) {
    z80_t& c = z.cpu;
    uint8_t flag = c.a;
    uint16_t len = c.de;
    uint16_t src = c.ix;
    uint16_t blen = len + 2;
    z.tape_out.push_back(blen & 0xFF);
    z.tape_out.push_back(blen >> 8);
    z.tape_out.push_back(flag);
    uint8_t sum = flag;
    for (uint16_t i = 0; i < len; i++) {
        uint8_t b = z.mem[(uint16_t)(src + i)];
        z.tape_out.push_back(b);
        sum ^= b;
    }
    z.tape_out.push_back(sum);
    z.saves++;
}

static inline void redirect(ZX& z, uint16_t pc) {
    uint64_t intpin = z.pins & Z80_INT;
    z.pins = z80_prefetch(&z.cpu, pc) | intpin;
}

// -- the clock ------------------------------------------------------------------

static inline void tick(ZX& z) {
    z.pins = z80_tick(&z.cpu, z.pins);

    // The beam: 8 pixels every 4 T-states across the visible part of a line.
    if (z.cyc < COLUMNS * 4 && (z.cyc & 3) == 0) {
        int first = fb_first_line(z);
        if (z.line >= first && z.line < first + FB_H) draw8(z);
    }

    uint64_t p = z.pins;
    if (p & Z80_MREQ) {
        const uint16_t a = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            Z80_SET_DATA(p, z.mem[a]);
            z.pins = p;
            if (p & Z80_M1) {
                if (z.execmap_on && (z.execmap_bank < 0 || z.slot3 == z.execmap_bank)) z.execmap[a]++;
                for (auto& br : z.breaks) {
                    if (a >= br.first && a <= br.second) {
                        z.hit = true;
                        z.hit_pc = a;
                    }
                }
                // ROM traps: only when the 48K BASIC ROM is paged in
                if (a < 0x4000 && (z.model == 48 || z.rom_sel == 1)) {
                    switch (a) {
                        case ROM_LD_BYTES_IN:
                            if (trap_ld_bytes(z)) redirect(z, ROM_RET);
                            break;
                        case ROM_SA_BYTES:
                            trap_sa_bytes(z);
                            redirect(z, ROM_RET);
                            break;
                        case ROM_CHAN_OPEN:
                            z.cur_stream = z.cpu.a;
                            break;
                        case ROM_PRINT_A_2:
                            if (z.log_text
                                && (z.cur_stream == 2 || z.cur_stream == 0xFE)) {
                                z.text.push_back((char)z.cpu.a);
                            }
                            break;
                        default:
                            break;
                    }
                }
            }
        } else if (p & Z80_WR) {
            mem_write(z, a, Z80_GET_DATA(p));
        }
    } else if (p & Z80_IORQ) {
        if (p & Z80_M1) {
            Z80_SET_DATA(p, 0xFF);  // interrupt acknowledge (IM 2 vector 0xFF)
        } else {
            const uint16_t a = Z80_GET_ADDR(p);
            if (p & Z80_RD) {
                Z80_SET_DATA(p, io_read(z, a));
            } else if (p & Z80_WR) {
                io_write(z, a, Z80_GET_DATA(p));
            }
        }
        z.pins = p;
    }

    if (z.ay_record && z.model == 128 && (z.t & 1) == 0) {
        if (ay38910_tick(&z.ay)) z.ay_samples.push_back(z.ay.sample);
    }

    z.t++;
    z.cyc++;
    if (z.line == 0) {
        if (z.cyc == INT_AT) z.pins |= Z80_INT;
        else if (z.cyc == INT_AT + z.int_len) z.pins &= ~Z80_INT;
    }
    if (z.cyc == z.t_line) {
        z.cyc = 0;
        if (++z.line == z.lines) {
            z.line = 0;
            z.frame++;
            if (--z.flash_count == 0) {
                z.flash_count = FLASH_FRAMES;
                z.flash_inv = !z.flash_inv;
            }
        }
    }
}

// Draw a whole frame from memory as it stands (no beam racing), so there is a
// picture straight after loading a snapshot, before any frame has run.
static void render_static(ZX& z) {
    int line = z.line, cyc = z.cyc;
    int first = fb_first_line(z);
    for (z.line = first; z.line < first + FB_H; z.line++) {
        for (z.cyc = 0; z.cyc < COLUMNS * 4; z.cyc += 4) draw8(z);
    }
    z.line = line;
    z.cyc = cyc;
}

static void ay_setup(ZX& z) {
    ay38910_desc_t desc = {};
    desc.type = AY38910_TYPE_8912;
    desc.tick_hz = z.clock / 2;
    desc.sound_hz = AY_RATE;
    desc.magnitude = 0.5f;
    ay38910_init(&z.ay, &desc);
}

static void power_on(ZX& z) {
    z.pins = z80_init(&z.cpu);
    memset(z.keys, 0xFF, sizeof z.keys);
    z.kempston = 0;
    z.border = 7;
    z.ear = false;
    z.line = 0;
    z.cyc = 0;
    z.flash_count = FLASH_FRAMES;
    z.flash_inv = false;
    memset(z.fb, 7, sizeof z.fb);
    if (z.model == 128) {
        // back to ROM 0, bank 0, normal screen, unlocked
        z.locked = false;
        page_slot3(z, 0);
        page_rom(z, 0);
        memcpy(z.mem, z.rom[0], 0x4000);
        z.rom_sel = 0;
        z.screen7 = false;
        z.last_7ffd = 0;
        ay_setup(z);
    }
}

extern "C" {

ZX* zx_new(void) {
    ZX* z = new ZX();
    memset(z->mem, 0, sizeof z->mem);
    memset(z->bank, 0, sizeof z->bank);
    power_on(*z);
    return z;
}

void zx_free(ZX* z) { delete z; }

// Load 16K of ROM from bytes (48K model).  Does not reset.
void zx_load_rom(ZX* z, const uint8_t* data, int len) {
    if (len > 0x4000) len = 0x4000;
    memcpy(z->mem, data, len);
    memcpy(z->rom[1], data, len);
}

// Become a 128K (Spectrum 128, "toastrack" timings) with these two ROMs, and
// power on.  ROM 0 is the 128 editor/menu, ROM 1 the 48K BASIC.
void zx_make_128(ZX* z, const uint8_t* rom0, const uint8_t* rom1) {
    z->model = 128;
    z->t_line = 228;
    z->lines = 311;
    z->screen_line0 = 63;
    z->int_len = 36;
    z->clock = 3546900;
    memcpy(z->rom[0], rom0, 0x4000);
    memcpy(z->rom[1], rom1, 0x4000);
    memset(z->mem + 0x4000, 0, 0xC000);
    memset(z->bank, 0, sizeof z->bank);
    z->slot3 = 0;
    z->rom_sel = 0;
    power_on(*z);
}

int zx_model(ZX* z) { return z->model; }
int zx_clock(ZX* z) { return z->clock; }
int zx_paging(ZX* z) { return z->last_7ffd | (z->slot3 & 7) | (z->rom_sel << 4) | (z->screen7 << 3) | (z->locked << 5); }

// Power-cycle: clears RAM (like a real cold start; the ROM tests it anyway)
void zx_reset(ZX* z) {
    memset(z->mem + 0x4000, 0, 0xC000);
    memset(z->bank, 0, sizeof z->bank);
    power_on(*z);
}

// Load a SNA from bytes: 48K (49179 bytes) or 128K (131103 / 147487 bytes).
// A 48K SNA on a 128 locks it into 48K mode (ROM 1, bank 0, paging off).
int zx_load_sna(ZX* z, const uint8_t* d, int len) {
    if (len < 27 + 49152) return -1;
    auto w = [d](int o) -> uint16_t { return d[o] | (d[o + 1] << 8); };
    z80_t& c = z->cpu;
    power_on(*z);
    c.i = d[0];
    c.hl2 = w(1); c.de2 = w(3); c.bc2 = w(5); c.af2 = w(7);
    c.hl = w(9); c.de = w(11); c.bc = w(13); c.iy = w(15); c.ix = w(17);
    c.iff2 = (d[19] & 0x04) != 0;
    c.iff1 = false;          // RETN copies IFF2 into IFF1
    c.r = d[20];
    c.af = w(21);
    c.sp = w(23);
    c.im = d[25] & 3;
    z->border = d[26] & 7;
    bool is128 = len >= 49179 + 4 + 5 * 16384;
    if (z->model == 128 && is128) {
        uint8_t cfg = d[49179 + 2];
        int paged = cfg & 7;
        // 48K part: bank 5, bank 2, then the paged bank
        memcpy(z->mem + 0x4000, d + 27, 0x4000);
        memcpy(z->mem + 0x8000, d + 27 + 0x4000, 0x4000);
        z->locked = false;
        z->slot3 = 0;            // (content of bank 0 comes below if not paged)
        memcpy(z->mem + 0xC000, d + 27 + 0x8000, 0x4000);
        z->slot3 = paged;
        if (paged == 5) memcpy(z->mem + 0x4000, d + 27 + 0x8000, 0x4000);
        if (paged == 2) memcpy(z->mem + 0x8000, d + 27 + 0x8000, 0x4000);
        int off = 49179 + 4;
        for (int b = 0; b < 8; b++) {
            if (b == 5 || b == 2 || b == paged) continue;
            if (off + 0x4000 > len) return -2;
            memcpy(z->bank[b], d + off, 0x4000);
            off += 0x4000;
        }
        memcpy(z->mem, z->rom[(cfg >> 4) & 1], 0x4000);
        z->rom_sel = (cfg >> 4) & 1;
        z->screen7 = cfg & 8;
        z->locked = cfg & 0x20;
        z->last_7ffd = cfg;
        c.iff1 = c.iff2;
        z->pins = z80_prefetch(&c, w(49179));
    } else {
        if (z->model == 128) write_7ffd(*z, 0x30);  // ROM 1, bank 0, locked
        memcpy(z->mem + 0x4000, d + 27, 49152);
        z->pins = z80_prefetch(&c, ROM_RETN);  // RETN pops PC off the stack
    }
    render_static(*z);
    return 0;
}

// Write a SNA into out: 48K (49179 bytes), or on a 128 the 128K layout.
// First runs to an instruction boundary.  On a 48K the PC goes on the stack
// *in the file only*; the live machine is left untouched.
int zx_save_sna(ZX* z, uint8_t* out, int cap) {
    bool is128 = z->model == 128 && !z->locked;
    int paged = z->slot3;
    int need = 49179 + (is128 ? 4 + ((paged == 5 || paged == 2) ? 6 : 5) * 0x4000 : 0);
    if (cap < need) return -1;
    int guard = 0;
    while (!z80_opdone(&z->cpu) && guard++ < 100) tick(*z);
    z80_t& c = z->cpu;
    uint16_t pc = c.pc - 1;  // opdone is reported in M1/T2 of the next fetch
    uint16_t sp = is128 ? c.sp : (uint16_t)(c.sp - 2);
    auto w = [out](int o, uint16_t v) { out[o] = v & 0xFF; out[o + 1] = v >> 8; };
    out[0] = c.i;
    w(1, c.hl2); w(3, c.de2); w(5, c.bc2); w(7, c.af2);
    w(9, c.hl); w(11, c.de); w(13, c.bc); w(15, c.iy); w(17, c.ix);
    out[19] = c.iff2 ? 0x04 : 0x00;
    out[20] = c.r;
    w(21, c.af);
    w(23, sp);
    out[25] = c.im;
    out[26] = z->border;
    memcpy(out + 27, z->mem + 0x4000, 49152);
    if (!is128) {
        if (sp >= 0x4000) out[27 + sp - 0x4000] = pc & 0xFF;
        if ((uint16_t)(sp + 1) >= 0x4000) out[27 + (uint16_t)(sp + 1) - 0x4000] = pc >> 8;
        return 49179;
    }
    w(49179, pc);
    out[49181] = (paged & 7) | (z->screen7 ? 8 : 0) | (z->rom_sel ? 0x10 : 0);
    out[49182] = 0;
    int off = 49183;
    for (int b = 0; b < 8; b++) {
        if (b == 5 || b == 2 || b == paged) continue;
        memcpy(out + off, bank_ptr(*z, b), 0x4000);
        off += 0x4000;
    }
    return off;
}

// Run whole frames.  Stops at the start of a frame (line 0, T-state 0), when
// the framebuffer holds the complete previous frame.  If a breakpoint is hit,
// stops at the end of that frame and returns 1; otherwise 0.
int zx_run_frames(ZX* z, int n) {
    uint64_t target = z->frame + n;
    z->hit = false;
    while (z->frame < target) {
        tick(*z);
        if (z->hit && !z->breaks.empty()) {
            // finish this frame so the picture is whole
            uint64_t f = z->frame;
            while (z->frame == f) tick(*z);
            return 1;
        }
    }
    return 0;
}

// Run until an opcode fetch lands in [lo,hi], or max_t T-states.  Stops right
// there (mid-frame).  Returns 1 if hit.
int zx_run_until_pc(ZX* z, uint16_t lo, uint16_t hi, uint64_t max_t) {
    uint64_t end = z->t + max_t;
    auto saved = z->breaks;
    z->breaks = {{lo, hi}};
    z->hit = false;
    while (z->t < end && !z->hit) tick(*z);
    z->breaks = saved;
    bool h = z->hit;
    z->hit = false;
    return h ? 1 : 0;
}

// Run until an opcode fetch hits any breakpoint added with zx_add_break, or
// max_t T-states.  Stops right there (mid-frame).  Returns the PC hit, or -1.
int zx_run_until_breaks(ZX* z, uint64_t max_t) {
    uint64_t end = z->t + max_t;
    z->hit = false;
    while (z->t < end && !z->hit) tick(*z);
    bool h = z->hit;
    z->hit = false;
    return h ? z->hit_pc : -1;
}

void zx_run_tstates(ZX* z, uint64_t n) {
    uint64_t end = z->t + n;
    while (z->t < end) tick(*z);
}

// Execution map: on/off (bank: count only while that bank is at 0xC000, -1 = always)
void zx_execmap(ZX* z, int on, int bank) {
    if (on && !z->execmap_on) memset(z->execmap, 0, sizeof z->execmap);
    z->execmap_on = on;
    z->execmap_bank = bank;
}
uint32_t* zx_execmap_get(ZX* z) { return z->execmap; }

void zx_add_break(ZX* z, uint16_t lo, uint16_t hi) { z->breaks.push_back({lo, hi}); }
void zx_clear_breaks(ZX* z) { z->breaks.clear(); }
int zx_hit_pc(ZX* z) { return z->hit_pc; }

void zx_set_keys(ZX* z, const uint8_t* rows) { memcpy(z->keys, rows, 8); }
void zx_set_kempston(ZX* z, uint8_t v) { z->kempston = v; }

uint8_t* zx_memory(ZX* z) { return z->mem; }
uint8_t* zx_bank(ZX* z, int b) { return bank_ptr(*z, b & 7); }
const uint8_t* zx_framebuffer(ZX* z) { return z->fb; }
int zx_fb_width(void) { return FB_W; }
int zx_fb_height(void) { return FB_H; }
uint64_t zx_frame(ZX* z) { return z->frame; }
uint64_t zx_tstates(ZX* z) { return z->t; }
int zx_border(ZX* z) { return z->border; }
void zx_render_static(ZX* z) { render_static(*z); }
int zx_frame_pos(ZX* z) { return z->line * z->t_line + z->cyc; }  // T-states into this frame
int zx_frame_len(ZX* z) { return z->t_line * z->lines; }

// PC SP AF BC DE HL IX IY AF' BC' DE' HL' IR IM IFF1 IFF2
void zx_regs(ZX* z, uint16_t* out) {
    z80_t& c = z->cpu;
    uint16_t v[16] = {c.pc, c.sp, c.af, c.bc, c.de, c.hl, c.ix, c.iy,
                      c.af2, c.bc2, c.de2, c.hl2, c.ir, c.im, c.iff1, c.iff2};
    memcpy(out, v, sizeof v);
}

void zx_tape_insert(ZX* z, const uint8_t* data, int len) {
    z->tape.assign(data, data + len);
    z->tape_pos = 0;
}
int zx_tape_pos(ZX* z) { return (int)z->tape_pos; }
int zx_tape_len(ZX* z) { return (int)z->tape.size(); }
int zx_tape_out_len(ZX* z) { return (int)z->tape_out.size(); }
void zx_tape_out_get(ZX* z, uint8_t* out) {
    memcpy(out, z->tape_out.data(), z->tape_out.size());
}
void zx_tape_out_clear(ZX* z) { z->tape_out.clear(); }
int zx_loads(ZX* z) { return z->loads; }
int zx_saves(ZX* z) { return z->saves; }

void zx_log_audio(ZX* z, int on) { z->log_audio = on; }
int zx_audio_len(ZX* z) { return (int)z->ear_edges.size(); }
void zx_audio_get(ZX* z, uint64_t* out) {
    memcpy(out, z->ear_edges.data(), z->ear_edges.size() * sizeof(uint64_t));
}
void zx_audio_clear(ZX* z) { z->ear_edges.clear(); }
int zx_ear(ZX* z) { return z->ear; }

// AY: register-write log (always on for a 128) and samples (while recording)
void zx_ay_record(ZX* z, int on) { z->ay_record = on; }
int zx_ay_rate(void) { return AY_RATE; }
int zx_ay_samples_len(ZX* z) { return (int)z->ay_samples.size(); }
void zx_ay_samples_get(ZX* z, float* out) {
    memcpy(out, z->ay_samples.data(), z->ay_samples.size() * sizeof(float));
}
void zx_ay_samples_clear(ZX* z) { z->ay_samples.clear(); }
int zx_ay_log_len(ZX* z) { return (int)z->ay_log.size(); }
void zx_ay_log_get(ZX* z, uint64_t* out) {
    memcpy(out, z->ay_log.data(), z->ay_log.size() * sizeof(uint64_t));
}
void zx_ay_log_clear(ZX* z) { z->ay_log.clear(); }

int zx_text_len(ZX* z) { return (int)z->text.size(); }
void zx_text_get(ZX* z, uint8_t* out) { memcpy(out, z->text.data(), z->text.size()); }
void zx_text_clear(ZX* z) { z->text.clear(); }

}  // extern "C"
