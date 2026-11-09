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
// divMMC (fitted on request): the interface's paging, automap and SPI, and an
// SD card on its card-select 0 (sdcard.h).  Paging is by copying too: while
// divMMC memory is mapped, the flat view's lower 16K holds the EEPROM (or RAM
// bank 3) and the selected 8K RAM bank, and writes the hardware allows land
// there; the bank is copied home when it's unmapped.  The details, each with
// its source, are in docs/divmmc.md.
//
// Z80 and AY cores: floooh's chips z80.h and ay38910.h (zlib licence; the
// licence text is at the top of each, and z80.h carries OMSE's modification
// notice).  They are OMSE's copies, unchanged.

#define CHIPS_IMPL
#include "z80.h"
#include "ay38910.h"
#include "sdcard.h"

#include <array>
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

constexpr int DIV_EEPROM = -1;            // div_lower: the EEPROM, not a RAM bank

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

    bool tape_traps = true;   // LD-BYTES / SA-BYTES served from the tape deck

    // contention (docs/contention.md): on, where it starts, and the tracking it needs
    bool contention = true;
    bool floating = true;         // unanswered port reads see the ULA's fetches (docs/contention.md)
    int cont_start = 14335;   // T-states after INT goes up: 14335 on a 48K, 14361 on a 128
    bool prev_mreq = false, prev_io = false;
    int io_phase = 0;
    uint64_t stalled = 0;     // T-states the ULA has held the CPU, since power-on
    bool nmi = false;         // an NMI requested: one tick of the NMI pin

    // divMMC: fitted or not, the EEPROM's write-protect jumper, port E3, the
    // automap latch, and what the flat view's lower 16K holds while mapped
    bool div_fitted = false;
    bool div_wp = true;
    uint8_t div_ctrl = 0;
    bool div_automap = false;
    bool div_mapped = false;
    int div_lower = DIV_EEPROM;   // DIV_EEPROM or RAM bank 3, at 0x0000
    int div_upper = 0;            // the RAM bank at 0x2000
    bool div_lower_wr = false, div_upper_wr = false;
    int div_banks = 16;           // 8K RAM banks: 16 (128K) or 64 (512K)
    uint8_t div_eeprom[0x2000];
    std::vector<std::array<uint8_t, 0x2000>> div_ram;
    uint8_t div_cs = 0xFF;        // port E7: card selects, active low
    uint8_t div_spi = 0xFF;       // what the last SPI transfer received
    // The ZX Spectrum Next's SPI master (Alvin Albrecht and Fabio Belavenuto's spi_master.vhd), if
    // spi_gap is set (16 on the Next): a transfer takes spi_gap clocks of the CPU's own clock (stretched,
    // like the CPU, while the ULA holds it), and an access that comes sooner starts nothing (an OUT's byte
    // is never sent) and reads the last *finished* transfer's byte. 0: every access starts one at once.
    int spi_gap = 0;
    uint64_t spi_early = 0;       // accesses that came too soon (and so started nothing)
    uint16_t spi_early_pc[4096];  // the PC (just after the instruction) and gap of each, the first 4096
    uint8_t spi_early_dt[4096];
    uint64_t spi_begin = 0;       // when the transfer in flight began, in unstretched CPU clocks
    uint8_t spi_done = 0xFF;      // the last finished transfer's byte (spi_master's miso_dat)
    SDCard sd;
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
    if (!z.div_mapped) memcpy(z.mem, z.rom[r], 0x4000);   // else it's copied in at divMMC's unmap
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

// -- divMMC paging -------------------------------------------------------------

static const uint8_t* rom_now(const ZX& z) { return z.rom[z.model == 48 ? 1 : z.rom_sel]; }

// The live 8K pages, back to their homes (only what could have been written).
static void div_save(ZX& z) {
    if (!z.div_mapped) return;
    if (z.div_lower_wr) memcpy(z.div_eeprom, z.mem, 0x2000);
    if (z.div_upper_wr) memcpy(z.div_ram[z.div_upper].data(), z.mem + 0x2000, 0x2000);
}

// What should be at 0x0000-0x3FFF now, from port E3, the automap latch and the
// write-protect jumper (Fuse's divxxx_refresh_page_state and memory_map):
//   CONMEM: always mapped; EEPROM below, writable only without write-protect,
//     the selected bank above, writable.
//   else, while automapped, and only with write-protect on or MAPRAM set:
//     MAPRAM: bank 3 below, read-only; the bank above, read-only if it's 3.
//     no MAPRAM: EEPROM below, read-only; the bank above, writable.
static void div_refresh(ZX& z) {
    bool map = false, lw = false, uw = false;
    int lo = DIV_EEPROM, up = z.div_ctrl & (z.div_banks - 1);
    if (z.div_ctrl & 0x80) {
        map = true;
        lw = !z.div_wp;
        uw = true;
    } else if (z.div_automap && (z.div_wp || (z.div_ctrl & 0x40))) {
        map = true;
        if (z.div_ctrl & 0x40) {
            lo = 3;
            uw = up != 3;
        } else {
            uw = true;
        }
    }
    if (map == z.div_mapped && (!map || (lo == z.div_lower && up == z.div_upper
                                         && lw == z.div_lower_wr && uw == z.div_upper_wr))) return;
    div_save(z);
    if (map) {
        memcpy(z.mem, lo == DIV_EEPROM ? z.div_eeprom : z.div_ram[lo].data(), 0x2000);
        memcpy(z.mem + 0x2000, z.div_ram[up].data(), 0x2000);
    } else if (z.div_mapped) {
        memcpy(z.mem, rom_now(z), 0x4000);
    }
    z.div_mapped = map;
    z.div_lower = lo;
    z.div_upper = up;
    z.div_lower_wr = lw;
    z.div_upper_wr = uw;
}

// Power on: port E3 cleared (MAPRAM too), automap off, the card powered up.
static void div_power(ZX& z) {
    if (z.div_mapped) {
        div_save(z);
        memcpy(z.mem, rom_now(z), 0x4000);
        z.div_mapped = false;
    }
    z.div_ctrl = 0;
    z.div_automap = false;
    z.div_cs = 0xFF;
    z.div_spi = 0xFF;
    z.sd.power();
}

static inline void mem_write(ZX& z, uint16_t a, uint8_t v) {
    if (a < 0x4000) {
        if (z.div_mapped && (a < 0x2000 ? z.div_lower_wr : z.div_upper_wr)) z.mem[a] = v;
        return;
    }
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

// The Next's rule (spi_gap clocks a transfer). spi_master loads its read register the clock after its
// last state, so the byte in flight has landed by the time the CPU latches an access's data only if the
// access comes spi_gap or more clocks after it, which is also when a new transfer can start (on the last
// state or when idle). Sooner, it starts nothing and reads the last landed byte again.
static uint8_t spi_gap_access(ZX& z, uint8_t mosi, bool rd) {
    uint64_t now = z.t - z.stalled;
    uint64_t dt = now - z.spi_begin;
    if (dt >= (uint64_t)z.spi_gap) z.spi_done = z.div_spi;
    uint8_t v = z.spi_done;
    if (dt >= (uint64_t)z.spi_gap) {
        z.div_spi = z.sd.xfer(rd ? 0xFF : mosi, (z.div_cs & 3) == 2);
        z.spi_begin = now;
    } else {
        if (z.spi_early < 4096) {
            z.spi_early_pc[z.spi_early] = z.cpu.pc;
            z.spi_early_dt[z.spi_early] = (uint8_t)dt;
        }
        z.spi_early++;
    }
    return v;
}

static uint8_t floating_bus(ZX& z, uint16_t addr);

static uint8_t io_read_dev(ZX& z, uint16_t addr) {
    if ((addr & 1) == 0) {  // ULA: keyboard (+ EAR on bit 6)
        uint8_t v = 0xBF;
        uint8_t rows = ~(addr >> 8);
        for (int r = 0; r < 8; r++) {
            if (rows & (1 << r)) v &= z.keys[r];
        }
        return v | (z.ear ? 0x40 : 0);
    }
    if (z.model == 128 && (addr & 0x8002) == 0x8000) return ay_read(z, addr);
    if (z.div_fitted && (addr & 0xFF) == 0xEB && z.spi_gap) return spi_gap_access(z, 0xFF, true);
    if (z.div_fitted && (addr & 0xFF) == 0xEB) {
        // SPI: an IN returns what the *previous* transfer received, and starts
        // a new one sending FF (the Next's spi_master.vhd, the ZX-Uno's spi.v)
        uint8_t v = z.div_spi;
        z.div_spi = z.sd.xfer(0xFF, (z.div_cs & 3) == 2);
        return v;
    }
    if ((addr & 0xE0) == 0) return z.kempston;  // Kempston joystick, 0x1F
    return floating_bus(z, addr);               // nobody answers
}

// The 128's quirk (as Fuse has it, periph.c readport): an IN from any port that
// decodes as 7FFD (A15 and A1 low) also writes the byte it read into the paging
// register, as an OUT would (and as an OUT would, not once it's locked).
static uint8_t io_read(ZX& z, uint16_t addr) {
    const uint8_t v = io_read_dev(z, addr);
    if (z.model == 128 && (addr & 0x8002) == 0) write_7ffd(z, v);
    return v;
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
    if (z.div_fitted) {                     // decoded on A0-A7 only
        switch (addr & 0xFF) {
        case 0xE3:                          // control; MAPRAM can be set, never cleared
            z.div_ctrl = v | (z.div_ctrl & 0x40);
            div_refresh(z);
            break;
        case 0xE7:                          // card selects: bit 0 is card 0, active low
            z.div_cs = v;
            break;
        case 0xEB:                          // SPI: send v, keep what comes back
            if (z.spi_gap) spi_gap_access(z, v, false);
            else z.div_spi = z.sd.xfer(v, (z.div_cs & 3) == 2);
            break;
        default:
            break;
        }
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

// The beam: 8 pixels every 4 T-states across the visible part of a line.
static inline void beam(ZX& z) {
    if (z.cyc < COLUMNS * 4 && (z.cyc & 3) == 0) {
        int first = fb_first_line(z);
        if (z.line >= first && z.line < first + FB_H) draw8(z);
    }
}

// One T-state of the clock: the AY, the counters, the INT pin, the frame.
static inline void advance(ZX& z) {
    if (z.model == 128 && (z.t & 1) == 0) {
        // Recording observes the chip; it must not start its clock or DC
        // filter. A held level has already settled before capture begins.
        if (ay38910_tick(&z.ay) && z.ay_record) z.ay_samples.push_back(z.ay.sample);
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

// -- contention ---------------------------------------------------------------
// The ULA stops the CPU's clock while it reads the screen, when the CPU wants a
// contended address at the wrong moment (docs/contention.md has the rule and its
// sources). These are the pieces; tick() applies them.

// Is this address contended?  4000-7FFF always (bank 5); on the 128, C000-FFFF
// too while an odd bank (1, 3, 5, 7) is paged there.
static inline bool contended(const ZX& z, uint16_t a) {
    if ((a & 0xC000) == 0x4000) return true;
    return z.model == 128 && (a & 0xC000) == 0xC000 && (z.slot3 & 1);
}

// The ULA's delay for a CPU T-state that wants a contended address now: 6, 5,
// 4, 3, 2, 1, 0, 0 by position in each 8 T-states of the first 128 T of each of
// the 192 screen lines, counted from cont_start T-states after INT goes up.
// T-states since INT went up, for the T-state the CPU is in now
static inline int frame_t(const ZX& z) { return z.line * z.t_line + z.cyc - INT_AT; }
static inline int contend_delay_at(const ZX& z, int t) {
    static const int PATTERN[8] = {6, 5, 4, 3, 2, 1, 0, 0};
    int rel = t - z.cont_start;
    if (rel < 0) return 0;
    int col = rel % z.t_line;
    if (rel / z.t_line >= 192 || col >= 128) return 0;
    return PATTERN[col & 7];
}
static inline int contend_delay(const ZX& z) { return contend_delay_at(z, frame_t(z)); }

// The floating bus: what an IN from a port nobody answers reads, T-states t after
// INT. In each 8 T of a screen line's first 128 the ULA fetches bitmap, attribute,
// bitmap + 1, attribute + 1, and leaves four T idle (FFh): Ramsoft's pattern, with
// the first byte 14338 T after INT on a 48K and 14364 on a 128, as Fuse times it
// (spectrum.c, tuned on Arkanoid and Sidewize). Anywhere else, FFh.
static uint8_t floating_byte(ZX& z, int t) {
    const int u = t - (z.cont_start + 1);
    if (u < 0) return 0xFF;
    const int line = u / z.t_line, col = u % z.t_line;
    if (line >= 192 || col >= 128) return 0xFF;
    const uint8_t* scr = (z.model == 128 && z.screen7) ? bank_ptr(z, 7) : z.mem + 0x4000;
    int x = (col >> 3) * 2;
    switch (col & 7) {
    case 4: x++; [[fallthrough]];
    case 2: return scr[((line & 0xC0) << 5) | ((line & 7) << 8) | ((line & 0x38) << 2) | x];
    case 5: x++; [[fallthrough]];
    case 3: return scr[0x1800 + (line >> 3) * 32 + x];
    default: return 0xFF;
    }
}
// Sampled where Fuse samples it (readport): at the start of the I/O cycle's last
// T-state, after its hold. An IN is served here at its second T-state, so the two
// after it are counted on, held as contention would hold them (with A0 set, a port
// whose high byte is contended is checked on every T-state: C:1 x4).
static uint8_t floating_bus(ZX& z, uint16_t addr) {
    if (!z.floating) return 0xFF;
    const bool hc = z.contention && contended(z, addr);
    int t = frame_t(z) + 1;
    if (hc) t += contend_delay_at(z, t);
    t += 1;
    if (hc) t += contend_delay_at(z, t);
    return floating_byte(z, t);
}

// Does the ULA check the T-state the CPU has just shown on its pins?  Memory: a
// cycle's T1 (MREQ with RD or WR: this core clears its control pins every tick,
// so T2 shows MREQ alone and T3 nothing), or an internal T-state that doesn't
// follow an MREQ T-state (so never T2 or T3, nor the fetch's T4 after the
// refresh), when the address on the bus is contended. I/O (this core raises
// IORQ from T1): by phase and port, as the ULA does it (port bit 0 low is its
// own port; a contended high byte counts as memory).
static inline bool contend_check(ZX& z, uint64_t p) {
    const uint16_t a = Z80_GET_ADDR(p);
    bool check;
    if ((p & Z80_IORQ) && !(p & Z80_M1)) {
        z.io_phase = z.prev_io ? z.io_phase + 1 : 1;
        bool hc = contended(z, a);
        if (!(a & 1)) check = z.io_phase == 2 || (hc && z.io_phase == 1);    // C:1, C:3 or N:1, C:3
        else check = hc;                                                    // C:1 x4, or N:4
    } else if (p & Z80_MREQ) {
        check = (p & (Z80_RD | Z80_WR)) && !(p & Z80_RFSH) && contended(z, a);
    } else {
        check = !z.prev_mreq && !(p & Z80_IORQ) && contended(z, a);
    }
    z.prev_mreq = p & Z80_MREQ;
    z.prev_io = (p & Z80_IORQ) && !(p & Z80_M1);
    return check;
}

static inline void tick(ZX& z) {
    if (z.nmi) {                            // one tick of the NMI pin: the core takes the edge
        z.pins = z80_tick(&z.cpu, z.pins | Z80_NMI) & ~Z80_NMI;
        z.nmi = false;
    } else {
        z.pins = z80_tick(&z.cpu, z.pins);
    }
    // contention: the ULA holds the CPU, and everything else runs on
    if (z.contention && contend_check(z, z.pins)) {
        for (int d = contend_delay(z); d > 0; d--) {
            beam(z);
            advance(z);
            z.stalled++;
        }
    }

    beam(z);

    uint64_t p = z.pins;
    if (p & Z80_MREQ) {
        const uint16_t a = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            // divMMC's instant automap: an opcode fetch at 3D00-3DFF reads divMMC memory
            if ((p & Z80_M1) && z.div_fitted && (a & 0xFF00) == 0x3D00 && !z.div_automap) {
                z.div_automap = true;
                div_refresh(z);
            }
            Z80_SET_DATA(p, z.mem[a]);
            z.pins = p;
            if (p & Z80_M1) {
                bool trapped = false;
                if (z.execmap_on && (z.execmap_bank < 0 || z.slot3 == z.execmap_bank)) z.execmap[a]++;
                for (auto& br : z.breaks) {
                    if (a >= br.first && a <= br.second) {
                        z.hit = true;
                        z.hit_pc = a;
                    }
                }
                // ROM traps: only when the 48K BASIC ROM is paged in (and not divMMC's memory)
                if (a < 0x4000 && !z.div_mapped && (z.model == 48 || z.rom_sel == 1)) {
                    switch (a) {
                        case ROM_LD_BYTES_IN:
                            if (z.tape_traps && trap_ld_bytes(z)) {
                                redirect(z, ROM_RET);
                                trapped = true;
                            }
                            break;
                        case ROM_SA_BYTES:
                            if (z.tape_traps) {
                                trap_sa_bytes(z);
                                redirect(z, ROM_RET);
                                trapped = true;
                            }
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
                // divMMC's automap, after this fetch: the entry points map it in,
                // the off-area 1FF8-1FFF maps it out (a fetch the tape deck served
                // with a redirect never reached 0562's code, so doesn't count)
                if (z.div_fitted && !trapped) {
                    if ((a & 0xFFF8) == 0x1FF8) {
                        if (z.div_automap) {
                            z.div_automap = false;
                            div_refresh(z);
                        }
                    } else if (a == 0x0000 || a == 0x0008 || a == 0x0038 || a == 0x0066
                               || a == 0x04C6 || a == 0x0562) {
                        if (!z.div_automap) {
                            z.div_automap = true;
                            div_refresh(z);
                        }
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

    advance(z);
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
    div_power(z);
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
    z->cont_start = 14361;
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
    for (auto& b : z->div_ram) b.fill(0);
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

// Write a SNA into out: 48K (49179 bytes), or on a 128 the 128K layout,
// locked or not (a locked 128 still has its AY, its timing and eight banks).
// First runs to an instruction boundary.  On a 48K the PC goes on the stack
// *in the file only*; the live machine is left untouched.
int zx_save_sna(ZX* z, uint8_t* out, int cap) {
    bool is128 = z->model == 128;
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
    out[49181] = (paged & 7) | (z->screen7 ? 8 : 0) | (z->rom_sel ? 0x10 : 0) | (z->locked ? 0x20 : 0);
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
// a write from outside the machine, as the CPU's would land (so a bank paged at
// two addresses changes at both), but never into the ROM area
void zx_poke(ZX* z, int a, int v) { if (a >= 0x4000 && a <= 0xFFFF) mem_write(*z, a, v); }
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

// -- divMMC and its SD card ------------------------------------------------------

// Fit a divMMC: its 8K EEPROM (eeprom NULL: blank, all FF), 128 or 512 K of RAM,
// and the EEPROM's write-protect jumper (wp 1, as in use: automap needs it, or
// MAPRAM).  Then a power cycle, as fitting one takes.  Choose the model first.
// Returns 0, or -1 if ram_kb is neither 128 nor 512.
int zx_div_fit(ZX* z, const uint8_t* eeprom, int len, int ram_kb, int wp) {
    if (ram_kb != 128 && ram_kb != 512) return -1;
    div_power(*z);
    z->div_fitted = true;
    z->div_wp = wp != 0;
    z->div_banks = ram_kb / 8;
    z->div_ram.assign(z->div_banks, {});
    memset(z->div_eeprom, 0xFF, sizeof z->div_eeprom);
    if (eeprom) memcpy(z->div_eeprom, eeprom, len < 0x2000 ? len : 0x2000);
    zx_reset(z);
    return 0;
}

// Take it off again (and power-cycle).
void zx_div_unfit(ZX* z) {
    div_power(*z);
    z->div_fitted = false;
    zx_reset(z);
}

void zx_div_wp(ZX* z, int wp) {
    z->div_wp = wp != 0;
    div_refresh(*z);
}

// fitted, port E3, automap, mapped, lower (-1 EEPROM, else a bank), upper bank,
// port E7, write-protect, RAM banks, lower writable, upper writable
void zx_div_state(ZX* z, int* out) {
    int v[11] = {z->div_fitted, z->div_ctrl, z->div_automap, z->div_mapped, z->div_lower,
                 z->div_upper, z->div_cs, z->div_wp, z->div_banks, z->div_lower_wr, z->div_upper_wr};
    memcpy(out, v, sizeof v);
}

// The EEPROM's 8K, brought up to date first.
uint8_t* zx_div_eeprom(ZX* z) {
    div_save(*z);
    return z->div_eeprom;
}

// RAM bank b's 8K wherever it is now (the flat view, while mapped there).
uint8_t* zx_div_ram(ZX* z, int b) {
    if (!z->div_fitted) return nullptr;
    b &= z->div_banks - 1;
    if (z->div_mapped && z->div_upper == b) return z->mem + 0x2000;
    if (z->div_mapped && z->div_lower == b) return z->mem;
    return z->div_ram[b].data();
}

// The divMMC's NMI button (esxDOS's browser): one pulse on the Z80's NMI.
void zx_nmi(ZX* z) { z->nmi = true; }

// omse-ai's tape deck traps LD-BYTES and SA-BYTES; off, they run as on a real
// machine (so esxDOS's tape emulation sees every LOAD and SAVE).
void zx_tape_traps(ZX* z, int on) { z->tape_traps = on != 0; }

// An image of 512-byte sectors, as the card in slot 0: kind 0 SDHC, 1 SDSC, 2 SD
// 1.x, 3 MMC (sdcard.h).  Read-only, writes go to memory and the file is
// untouched.  0, or -1 (can't open), -2 (not whole sectors, or under 512K), -3
// (over 2 GB, for a standard-capacity card), -4 (no such kind).
int zx_sd_insert(ZX* z, const char* path, int writable, int kind) {
    return z->sd.insert(path, writable != 0, kind);
}
void zx_sd_eject(ZX* z) { z->sd.eject(); }
uint32_t zx_sd_sectors(ZX* z) { return z->sd.sectors; }
void zx_sd_timing(ZX* z, int ncr, int nac, int busy, int init_tries) {
    z->sd.ncr = ncr;
    z->sd.nac = nac;
    z->sd.busy = busy;
    z->sd.init_tries = init_tries;
}
int zx_sd_log_len(ZX* z) { return (int)z->sd.log.size(); }
void zx_sd_log_get(ZX* z, uint64_t* out) {
    memcpy(out, z->sd.log.data(), z->sd.log.size() * sizeof(uint64_t));
}
void zx_sd_log_clear(ZX* z) { z->sd.log.clear(); }

// The Next's SPI rule (Tally's, from spi_master.vhd): clocks a transfer takes
// (16 on a Spectrum Next; 0, the default, for a classic divMMC); how many
// accesses came too soon; and the k-th of them, as (PC << 8) | the gap.
void zx_spi_gap(ZX* z, int clocks) { z->spi_gap = clocks; z->spi_begin = 0; }
uint64_t zx_spi_early(ZX* z) { return z->spi_early; }
int zx_spi_early_at(ZX* z, int k) { return k < 4096 ? (z->spi_early_pc[k] << 8) | z->spi_early_dt[k] : -1; }

// Contention: on (the default, as a real machine) or off; and how many T-states
// the ULA has held the CPU since power-on.
void zx_contention(ZX* z, int on) { z->contention = on != 0; }
void zx_floating_bus(ZX* z, int on) { z->floating = on != 0; }
int zx_contention_on(ZX* z) { return z->contention; }
uint64_t zx_stalled(ZX* z) { return z->stalled; }

int zx_text_len(ZX* z) { return (int)z->text.size(); }
void zx_text_get(ZX* z, uint8_t* out) { memcpy(out, z->text.data(), z->text.size()); }
void zx_text_clear(ZX* z) { z->text.clear(); }

}  // extern "C"
