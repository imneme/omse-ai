// nextcore.cpp: a headless ZX Spectrum Next (core 3.02.02), as a C library for Python (next.py).
//
// Ratio Fern, Fri 6 Nov 2026, for omse-ai's Next (led by Tally Fern; design DESIGN.md, Speccy-Zone Fern's review;
// reference machine/NEXT-MACHINE.md by Hart's-tongue Fern, every claim cited to the VHDL of core 3.02.02, whose
// authors are Alvin Albrecht, Victor Trucco and Fabio Belavenuto). Citations below are to that reference ("ref §")
// and through it to the VHDL. Nothing here is copied from the VHDL: it's a model of what the reference says it does.
//
// A machine of its own beside zxcore.cpp's 48K/128 (which this file doesn't touch). It shares z80.h (whose
// implementation lives in zxcore.cpp's translation unit) and, later, ay38910.h and sdcard.h.
//
// Time: one tick is one cycle of the 28 MHz master clock (ref §0.1). The CPU clock is made from it: at 3.5 MHz
// phase-locked to the ULA's counter hc_ula (a T-state is two hc_ula counts; contention holds the clock high for
// whole T-states, ref §1.2), at 7/14/28 MHz the raw clocks. Each CPU clock is one z80_tick (floooh's z80.h: one
// T-state a tick, memory and I/O served in the same tick). At 28 MHz every SRAM or bank-5 read gets one wait state
// (ref §1.4): WAIT held for one CPU clock, which z80.h turns into a repeated step with the data still on the pins.
//
// Memory: a page table, one read and one write pointer per 8K slot, rebuilt whenever something that affects the map
// changes (ref §3). 2 MB of SRAM; bank 5 (16K) and the first 8K of bank 7 in block RAM (ref §3.11).
//
// Layer 1 (this file, so far): the clock, the counters for every timing, the ULA interrupt in pulse mode, memory
// with the boot ROM, config mode, the MMU and ROM selection by machine type, the Next registers (reset values
// generated from machine/nextregs.tsv), ports 0x243B/0x253B, the logs. Contention, the other ports, the screen, the
// SPI master and the fast boot are the next layers (machine-build-notes.md).

#include "next_audio.h"                // the sound (Slide Fern): generators, DACs, beeper, mixer
#include "next_dma.h"                  // the zxnDMA (Kelp Fern)
#include "next_serial.h"               // the UARTs, the I2C bus and its optional DS1307 (Ratio Fern)
#include <array>
#include "z80.h"
#include "sdcard.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace {

#include "nextregs_reset.inc"

constexpr uint32_t SRAM_SIZE = 2u << 20;          // 2 MB (issue 4, ref §3.2)
constexpr int BRAM5_SIZE = 16384, BRAM7_SIZE = 8192, BOOTROM_SIZE = 8192;
constexpr int FB_W = 352, FB_H = 288, FB_BORDER = 48;  // the visible area at 7 MHz, as zxcore's (48 pixels of border)
constexpr int F9_W = 2 * FB_W;                          // frame9: 14 MHz samples across the same area (§9.1 (12))

// Video timing per machine timing and 50/60 Hz (ref §2.2): pixels a line, lines, the raw hc where the 256-wide area
// starts (c_min_hactive), the raw line of pixel row 0 (c_min_vactive), the ULA interrupt's raw position, and the
// INT pulse length in CPU clocks (ref §2.3: 32 for 48K and +3, 36 for 128K and Pentagon).
struct Timing { int hc_len, vc_len, hactive, vactive, int_h, int_v, int_len; };
// index: timing 1 48K, 2 128K, 3 +3, 4 Pentagon; [0] 50 Hz, [1] 60 Hz
const Timing TIMINGS[5][2] = {
    {},
    {{448, 312, 128, 64, 116, 0, 32}, {448, 264, 128, 40, 116, 0, 32}},
    {{456, 311, 136, 64, 128, 1, 36}, {456, 264, 136, 40, 128, 0, 36}},
    {{456, 311, 136, 64, 126, 1, 32}, {456, 264, 136, 40, 126, 0, 32}},
    {{448, 320, 128, 80, 439, 319, 36}, {448, 320, 128, 80, 439, 319, 36}},  // Pentagon forces 50 Hz (ref §2.2)
};

enum Kind : uint8_t { K_NONE, K_SRAM, K_BRAM5, K_BRAM7, K_BOOT };
// what a slot shows, for slot_page (DESIGN.md §9.1 (8)): the tag and its value
enum Tag : uint8_t { T_PAGE, T_ROM, T_ALTROM, T_BOOT, T_CONFIG, T_DIVROM, T_DIV, T_MFROM, T_MFRAM, T_L2, T_NONE };

struct IoEvent { uint64_t t28, cpu_clocks; uint16_t port; uint8_t value, write; };
struct DmaEvent { uint64_t t28, cpu_clocks; uint16_t addr; uint8_t value, kind; };   // §9.1 (16)
struct IntEvent { uint64_t start, end; };

}  // namespace

struct ZXN {
    z80_t cpu;
    uint64_t pins = 0;

    uint8_t* sram = nullptr;
    uint8_t bram5[BRAM5_SIZE];
    uint8_t bram7[BRAM7_SIZE];
    uint8_t bootrom[BOOTROM_SIZE];

    // the page table
    uint8_t* rd[8];
    uint8_t* wr[8];
    Kind rd_kind[8], wr_kind[8];
    Tag rd_tag[8], wr_tag[8];
    int rd_val[8], wr_val[8];
    uint8_t last_sram = 0xFF;           // what a read of "no memory" returns (ref §3.3)

    // machine state
    int issue = 4;
    int timing = 3, hz60 = 0;           // in effect (1 48K, 2 128K, 3 +3, 4 Pentagon)
    int pend_timing = 3, pend_hz60 = 0; // NR 0x03 / NR 0x05 take effect at the frame sync (ref §2.6)
    int mtype = 3;                      // NR 0x03 bits 2:0
    int lock = 0;                       // NR 0x03 bit 3, the user lock
    bool config_mode = true, bootrom_en = true;
    int nr04 = 0;                       // config mode's 16K SRAM page (ref §3.10)
    int speed_prog = 0, speed_eff = 0;  // NR 0x07 (ref §1.3)
    int reset_type = 4;                 // 100 at power-on (ref §4.3, NR 0x02)
    uint8_t mmu[8];
    uint8_t port7ffd = 0, port1ffd = 0, portdffd = 0, porteff7 = 0, portff = 0;
    uint8_t border = 0;                 // port 0xFE bits 2:0 (ref §2.5)
    uint8_t keys[8] = {0};              // the keyboard matrix: half-row r (A8+r low), bit set = key down
    uint8_t fb[FB_W * FB_H];            // indexed: 0-7, +8 for BRIGHT
    uint16_t f9[F9_W * FB_H];           // frame9: 9-bit RRRGGGBBB per 14 MHz sample, black while blanking
    uint16_t f9raw[F9_W * FB_H];        // the mixer's colour before blanking (frame9(blank=False), §9.1 (14))
    uint16_t pal[2][1024];              // the palette RAMs (zxnext:6851-6960): 0 ULA/tilemap, 1 Layer 2/sprites;
                                        // address layer << 9 | second << 8 | index; data priority << 14 | RGB333
    uint8_t pal_idx = 0, pal_stored = 0;   // NR 0x40, and NR 0x44's first byte
    bool pal_sub = false;               // NR 0x44's write phase (reads in NR 0x03 b7)
    uint8_t clip[4][4];                 // NR 0x18-0x1B: x1, x2, y1, y2 of Layer 2, sprites, the ULA, the tilemap
    uint8_t clip_idx[4] = {0, 0, 0, 0};
    uint8_t spr_attr[128][5] = {{0}};   // sprite attributes (sprites.vhd)
    uint8_t spr_pat[16384] = {0};       // pattern RAM: 64 x 256 bytes (8-bit) or 128 x 128 (4-bit)
    int spr_ai = 0, spr_pi = 0;         // attr_index (sprite << 3 | byte), pattern_index (14 bits)
    int spr_mirror = 0;                 // NR 0x34's sprite (b7 the pattern half)
    uint16_t spr_buf[2][320] = {{0}};   // the line buffers (b8 written, b7:0 the palette index), sprites.vhd:470-553
    int spr_disp = 0;                   // the one the display reads; the renderer writes the other
    uint64_t spr_t = 0;                 // the renderer has run every cycle before this master tick
    uint64_t spr_swap_at = 0;           // the tick line_reset_re starts the next line's render (0: none due)
    int spr_state = 0;                  // SP_IDLE, SP_START, SP_QUALIFY, SP_PROCESS
    int spr_idx = 0, spr_vcount = 0;    // spr_cur_index; spr_cur_vcount, the wide line being rendered
    int sc_hcount = 0, sc_addr = 0, sc_delta = 0, sc_wc = 0, sc_wd = 0, sc_pal = 0, sc_wrap = 0;   // the sprite
    bool sc_h4 = false, sc_half = false;                                                         // being drawn
    bool sa_rt = false, sa_h = false, sa_vis = false, sa_rot = false, sa_xm = false, sa_ym = false;  // the anchor
    int sa_x = 0, sa_y = 0, sa_pat = 0, sa_pal = 0, sa_xs = 0, sa_ys = 0;
    uint8_t spr_status = 0;             // port 0x303B: b1 overtime, b0 collision
    int flash_count = 0;
    bool flash_on = false;

    // the SPI master (ref §1.7; spi_master.vhd by Alvin Albrecht and Fabio Belavenuto, zxnext 3240-3290)
    SDCard sd;
    uint8_t spi_cs = 0xFF;              // port 0xE7: bit 0 low selects card 0
    int spi_state = 16;                 // idles at 16; a transfer runs 0..15, one state a CPU clock
    uint8_t spi_rx = 0xFF;              // the read register port 0xEB returns
    struct { uint8_t byte; uint64_t due; } spi_pend[2];   // bytes received, each loading at its begin + 17 edges
    int spi_npend = 0;
    uint64_t spi_count = 0;             // transfers begun (for tests)
    uint8_t nr[256];
    int nr_sel = 0x24;                  // port 0x243B resets to 0x24 (ref §4.1)
    bool ula_int_disabled = false;      // port 0xFF bit 6 and its aliases (ref §2.3)
    bool eff_cd = false;                // eff_nr_08_contention_disable: NR 0x08 b6 as in effect (zxnext:5703-5733)
    int coreid = 1;                     // NR 0x10's core id (zxnext:1127)
    int cvc_off = 0;                    // NR 0x64 as the timing generator last loaded it, at ULA row 0
    bool l2_en = false;                 // port_123b_layer2_en (port 0x123B b1, NR 0x69 b7; Layer 2 itself: later)
    bool l2_wr = false, l2_rd = false, l2_shadow = false;   // port 0x123B b0, b2, b3 (zxnext:3845-3869)
    int l2_seg = 0, l2_off = 0;         // b7:6, and the offset a write with b4 set stores
    uint8_t porte3 = 0;                 // divMMC's port 0xE3: conmem b7, mapram b6 (set only), bank b3:0 (zxnext:4114-4129)
    bool dm_hold = false, dm_held = false;   // divmmc.vhd's automap_hold and automap_held
    bool dm_instant = false;            // an instant entry, during the fetch that met it
    bool dm_pending = false;            // automap_held follows automap_hold once the fetch's MREQ has risen
    int snoop = 0;                      // im2_control.vhd's state: 0, 1 after ED, 2 after CB, 3 after DD/FD
    int im_mode = 0;                    // the IM mode it has seen (NR 0xC0 b2:1)
    bool reti_seen = false;             // the snooper saw ED 4D, for the chain's next CPU edge
    uint16_t int_status = 0;            // each source's status (im2p:150-160), bit = source number
    uint16_t im2_req = 0;               // hardware IM2: pending until its service ends (im2p:162-176)
    uint8_t im2_state[14] = {0};        // im2_device.vhd: 0 idle, 1 requesting, 2 acknowledged, 3 in service
    uint8_t cop_ram[2048] = {0};        // the copper's 1K x 16 instructions, MSB at even byte addresses
    int cop_waddr = 0;                  // nr_copper_addr, 11 bits, the byte NR 0x60/0x63 write next
    uint8_t cop_stored = 0;             // nr_copper_data_stored, NR 0x63's even byte
    int cop_mode = 0, cop_last = 0;     // NR 0x62 b7:6, and copper.vhd's last_state_s
    int cop_pc = 0;                     // copper_list_addr_s
    bool cop_dout = false, cop_dout_d = false, cop_req = false;   // a MOVE's pulse, its edge, the arbitrated write
    uint16_t cop_data = 0;              // copper_data_o
    uint8_t cop_reg = 0, cop_val = 0;   // copper_nr_reg / copper_nr_dat
    uint8_t nmi_flags = 0;              // NR 0x02 b3 (multiface) and b2 (divMMC): software NMI requests
    int nmi_cause = 0;                  // nmi_mf (1), nmi_divmmc (2): the NMI accepted, first come first served
    int nmi_state = 0;                  // 0 idle, 1 waiting for the fetch from 0x0066, 2 held by its device, 3 end
    bool nmi_pending_mf = false, nmi_pending_dm = false;   // a button or NR 0x02 request this cycle
    bool mf_active = false, mf_invisible = true, mf_enable = false;   // multiface.vhd: nmi_active, invisible, mf_enable
    bool mf_fetch66 = false;            // the fetch from 0x0066 that pages it in, while it lasts
    bool dm_button = false;             // divmmc.vhd's button_nmi
    uint16_t joy[2] = {0, 0};           // the joysticks: X Z Y START A C B U D L R in bits 10:0 (zxnext:3398-3400)
    uint8_t mouse_x = 0, mouse_y = 0;   // the Kempston mouse as the PS/2 side counts it (ps2_mouse.v:186-203)
    uint8_t mouse_btn = 0, mouse_wheel = 0;   // b0 left, b1 right, b2 middle; the wheel's 4-bit count
    nserial::Uart uart[2];              // 0 the ESP's, 1 the Pi's (uart.vhd)
    int uart_sel = 0;                   // port 0x153B b6 (uart.vhd:262-279)
    uint16_t uart_req = 0;              // the UARTs' interrupt requests at the last tick (im2p's int_req_d)
    bool serial_on = true;              // a UART may be busy: step them (one test a tick when they're idle)
    bool i2c_scl = true, i2c_sda = true;      // our open-drain outputs, 1 released (zxnext:3189-3211)
    bool bus_scl = true, bus_sda = true;      // the bus as all its drivers make it
    nserial::Rtc rtc;                   // the optional DS1307 at 0x68 (none by default, §9.1 (18))
    bool i2c_logging = false;
    std::vector<std::array<uint64_t, 3>> i2c_log;
    uint8_t ay_reg[3][16] = {{0}};      // the AYs' register files (ym2149.vhd), chip 0 = AY_ID 11, 1 = 10, 2 = 01
    nextaudio::Audio audio;             // what makes the sound (next_audio.h)
    DmaBus db;                          // the zxnDMA and the bus request (next_dma.h, next_dma_bus.inc)
    uint64_t bus_pins = 0;              // the bus in the last T-state: the CPU's pins, or the DMA's while it has it
    bool io_now = false;                // io_out/io_in: no time passes (§9.1 (6))
    bool spi_last_d = false;            // spi_master's state_last_d (spi:154-160), for the DMA's SPI wait
    bool dma_logging = false;
    std::vector<DmaEvent> dma_log;
    uint8_t ay_addr[3] = {0, 0, 0};     // each chip's selected register (5 bits)
    int ay_sel = 0;                     // turbosound.vhd's ay_select, as a chip number
    uint8_t ulap_mode = 0, ulap_index = 0;   // port 0xBF3B (zxnext:4466-4478)
    bool ulap_en = false;               // port_ff3b_ulap_en
    struct Ctc {                        // ctc_chan.vhd: one channel
        uint8_t state = 0;              // 0 reset, 1 reset awaiting a time constant, 2 trigger, 3 run, 4 run awaiting one
        uint8_t ctrl = 0;               // the control word's bits 7:3 (b4 int enable, b3 counter, b2 /256, b1 rising, b0 trigger)
        uint8_t tc = 0, count = 0, p = 0;   // time constant, down counter, prescaler
        bool trg_d = false, zc_d = false, edge_change = false;
    } ctc[4];

    // time and the beam
    uint64_t t28 = 0, cpu_clocks = 0, frame = 0;
    int sc = 0;                         // 28 MHz sub-pixel count, 0-3 (ref §1.1)
    int hc = 0, vc = 0;                 // the raw frame counter (ref §2.1)
    bool cpu_clk_high = true;           // the 3.5 MHz clock's level (ref §1.2)
    bool contend = false;               // the ULA holding the 3.5 MHz clock high (zxula.vhd's o_cpu_contend)
    bool ck_mem = false, ck_port = false;  // what the current T-state asks the ULA (set at each rising CPU edge)
    bool prev_mreq = false, prev_io = false;
    int io_phase = 0;
    bool p3_mem = false;                // +3 timing: the last T-state began a contended memory cycle
    bool p3_waiting = false;            // +3 timing: the last T-state was a contention wait
    bool wait_next = false;             // a 28 MHz read wait for the next CPU clock
    bool stackless_retn = false;        // z80_stackless_retn_en: the next RETN pops from NR C2h/C3h (zxnext:2031-2042)
    bool contention = true;             // on, as the hardware is (zxn_contention can turn it off, for comparisons)

    // the interrupt
    bool int_req = false;               // the ULA's registered pulse, seen at the next 7 MHz edge
    bool int_low = false;
    int int_count = 0;
    int in_latch_dt = -1;               // during an IN's io_read: ticks on to the INT that a 253Bh read registers
    uint64_t in_latch_at = 0;           // that tick, for NR 0x22 b7 (0: none)
    bool rd_open = false;               // a read below 28 MHz, served at T1, waiting for its T2 (ldpirx_mem)
    uint16_t rd_addr = 0;               // the address it was served from
    std::vector<IntEvent> int_log;

    // logs and stops
    bool io_logging = false;
    std::vector<IoEvent> io_log;
    bool stop_on = false, first_edge = false, hit = false;
    uint16_t stop_lo = 0, stop_hi = 0, hit_pc = 0;
};

namespace {

inline const Timing& T(const ZXN& z) { return TIMINGS[z.timing][z.timing == 4 ? 0 : z.hz60]; }

// the ULA's own counters, derived from the raw ones (ref §2.1): hc_ula = hc - (c_min_hactive - 11) modulo the line;
// vc_ula steps at hc_ula = 0 and is 0 on the line where vc = c_min_vactive.
inline int hc_ula(const ZXN& z) {
    const Timing& t = T(z);
    return ((z.hc - (t.hactive - 11)) % t.hc_len + t.hc_len) % t.hc_len;
}
inline int vc_ula(const ZXN& z) {
    const Timing& t = T(z);
    int v = z.vc - t.vactive - (z.hc < t.hactive - 11 ? 1 : 0);
    return (v % t.vc_len + t.vc_len) % t.vc_len;
}
// cvc, the line the copper, line interrupt and NR 0x1E/0x1F count: the ULA's line plus NR 0x64's offset (ref §2.4;
// zxnext:5889-5893). The timing generator loads the offset as the ULA reaches row 0 and counts on from there, so a
// change of NR 0x64 takes effect at the next row 0 (ulat:455-470).
inline int cvc(const ZXN& z) { return (vc_ula(z) + z.cvc_off) % T(z).vc_len; }

// ---- memory (ref §3)

inline uint8_t* page_ptr(ZXN& z, int page, Kind& k) {
    if (page == 0x0A || page == 0x0B) { k = K_BRAM5; return z.bram5 + (page - 0x0A) * 8192; }   // ref §3.11
    if (page == 0x0E) { k = K_BRAM7; return z.bram7; }
    if (page >= 0xE0) { k = K_NONE; return nullptr; }                                             // ref §3.3
    k = K_SRAM;
    return z.sram + 0x40000 + page * 0x2000;                                                      // ref §3.1
}

// The ROM selection (ref §3.5; zxnext:2940-2967): which 16K ROM is in place, whether it's ROM 3 (the 48K BASIC,
// which divMMC's automap will want), and which alternate ROM goes with it (alt48: 0 the 128K one at SRAM 0x18000,
// 1 the 48K one at 0x1C000). 48K: ROM 0, and NR 0x8C's locks only choose the alternate ROM. 128K and Pentagon:
// ROM 0/1 by 7FFD bit 4. +3: ROMs 0-3 by 1FFD bit 2 (high) and 7FFD bit 4 (low). NR 0x8C bits 5:4 lock ROM1/ROM0
// in place over the ports. (The VHDL also decodes types 0 and 5-7, but NR 0x03 can only set 1-4: zxnext:5076-5083.)
struct RomSel { int rom; bool rom3, alt48; };
inline RomSel rom_select(const ZXN& z) {
    int l1 = (z.nr[0x8C] >> 5) & 1, l0 = (z.nr[0x8C] >> 4) & 1;
    int p = ((z.port1ffd >> 1) & 2) | ((z.port7ffd >> 4) & 1);         // port_1ffd_rom (zxnext:3713)
    switch (z.mtype) {
        case 1: return {0, true, !(!l1 && l0)};
        case 3:
            if (l1 | l0) return {l1 << 1 | l0, l1 && l0, l1 != 0};
            return {p, p == 3, (p & 1) != 0};
        default:
            if (l1 | l0) return {l1, l1 != 0, l1 != 0};
            return {p & 1, (p & 1) != 0, (p & 1) != 0};
    }
}

inline bool mf_mapped(const ZXN& z);
// divMMC (ref §3.8; device/divmmc.vhd; zxnext:4043-4131). Port 0xE3's decode (NR 0x83 b0, port enable bit 8) gates
// it all; automap also needs NR 0x0A b4 (divmmc_automap_reset, zxnext:4053).
inline bool dm_en(const ZXN& z) { return z.nr[0x83] & 1; }
inline bool dm_automap_reset(const ZXN& z) { return !dm_en(z) || !(z.nr[0x0A] & 0x10); }
inline bool dm_automap(const ZXN& z) { return !dm_automap_reset(z) && (z.dm_held || z.dm_instant); }

// Rebuild the page table (ref §3.4's decode order, the parts this layer has: boot ROM, MMU page, config mode, ROM).
void remap(ZXN& z) {
    for (int s = 0; s < 8; s++) {
        Kind k;
        uint8_t* p = page_ptr(z, z.mmu[s], k);
        if (s >= 2 || z.mmu[s] < 0xE0) {
            z.rd[s] = z.wr[s] = p;
            z.rd_kind[s] = z.wr_kind[s] = k;
            z.rd_tag[s] = z.wr_tag[s] = p ? T_PAGE : T_NONE;
            z.rd_val[s] = z.wr_val[s] = z.mmu[s];
        } else if (z.config_mode) {                                   // NR 0x04's 16K page, absolute (ref §3.10)
            uint8_t* q = z.sram + (z.nr04 * 16384 + s * 8192) % SRAM_SIZE;
            z.rd[s] = z.wr[s] = q;
            z.rd_kind[s] = z.wr_kind[s] = K_SRAM;
            z.rd_tag[s] = z.wr_tag[s] = T_CONFIG;
            z.rd_val[s] = z.wr_val[s] = z.nr04;
        } else {                                                      // ROM, read-only (ref §3.5)
            // NR 0x8C bit 7 brings in the alternate ROM, only here (not under an MMU page or config mode, whose
            // override bit 0 is clear): bit 6 clear, it replaces the ROM on reads; set, it takes the writes and
            // reads still see the ROM (zxnext:3015, 3037, 3075-3082).
            RomSel r = rom_select(z);
            int alt = z.nr[0x8C] & 0xC0;
            uint8_t* ap = z.sram + 0x18000 + (r.alt48 ? 0x4000 : 0) + s * 8192;
            z.rd_kind[s] = K_SRAM;
            if (alt == 0x80) {
                z.rd[s] = ap;
                z.rd_tag[s] = T_ALTROM;
                z.rd_val[s] = r.alt48;
            } else {
                z.rd[s] = z.sram + r.rom * 16384 + s * 8192;
                z.rd_tag[s] = T_ROM;
                z.rd_val[s] = r.rom;
            }
            if (alt == 0xC0) {
                z.wr[s] = ap;
                z.wr_kind[s] = K_SRAM;
                z.wr_tag[s] = T_ALTROM;
                z.wr_val[s] = r.alt48;
            } else {
                z.wr[s] = nullptr;
                z.wr_kind[s] = K_NONE;
                z.wr_tag[s] = T_NONE;
                z.wr_val[s] = 0;
            }
        }
        // the multiface (ref §3.9; zxnext:2988-2995): its ROM (SRAM 0x014000, read-only) and RAM (0x016000) over
        // slots 0-1, excluding divMMC, Layer 2, ROMCS and the alternate ROM (override "000")
        if (s < 2 && mf_mapped(z)) {
            uint8_t* p = z.sram + 0x14000 + s * 0x2000;
            z.rd[s] = p;
            z.rd_kind[s] = K_SRAM;
            z.rd_tag[s] = s == 0 ? T_MFROM : T_MFRAM;
            z.rd_val[s] = 0;
            z.wr[s] = s == 0 ? nullptr : p;
            z.wr_kind[s] = s == 0 ? K_NONE : K_SRAM;
            z.wr_tag[s] = s == 0 ? T_NONE : T_MFRAM;
            z.wr_val[s] = 0;
            if (z.bootrom_en) { z.rd[s] = z.bootrom; z.rd_kind[s] = K_BOOT; z.rd_tag[s] = T_BOOT; }
            continue;
        }
        // Layer 2's map (ref §3.7; zxnext:2924-2930, 3024, 3036, 3059-3066): slots 0-1, or 0-5 in segment mode 3,
        // for writes (0x123B b0) and reads (b2) separately. The page is ((NR 0x12, or NR 0x13 with b3) + the segment
        // or A15:14 + the offset) x 2 + A13, low 8 bits, placed like an MMU page; 0xE0 and up is no memory. It always
        // goes to SRAM, bank 5 included (zxnext:3062).
        if ((z.l2_rd || z.l2_wr) && (s < 2 || (s < 6 && z.l2_seg == 3))) {
            const int seg = z.l2_seg == 3 ? s >> 1 : z.l2_seg;
            const int bank = (z.l2_shadow ? z.nr[0x13] : z.nr[0x12]) & 0x7F;
            const int page = (((bank + ((seg + z.l2_off) & 15)) & 0xFF) * 2 + (s & 1)) & 0xFF;
            uint8_t* p = page >= 0xE0 ? nullptr : z.sram + 0x40000 + page * 0x2000;
            if (z.l2_rd) {
                z.rd[s] = p;
                z.rd_kind[s] = p ? K_SRAM : K_NONE;
                z.rd_tag[s] = p ? T_L2 : T_NONE;
                z.rd_val[s] = page;
            }
            if (z.l2_wr) {
                z.wr[s] = p;
                z.wr_kind[s] = p ? K_SRAM : K_NONE;
                z.wr_tag[s] = p ? T_L2 : T_NONE;
                z.wr_val[s] = page;
            }
        }
        // divMMC over slots 0-1, ahead of Layer 2, ROMCS, the alternate ROM and the rest (zxnext:3049-3066): with
        // conmem or automap, 0x0000-0x1FFF is its ROM (SRAM 0x010000) or, with mapram, RAM bank 3, read-only either
        // way; 0x2000-0x3FFF is the bank from port 0xE3, read-only if mapram is set and it's bank 3 (divmmc:83-101;
        // "Issue #7": conmem with mapram also brings in bank 3). The multiface, when mapped, excludes it.
        if (s < 2 && dm_en(z) && ((z.porte3 & 0x80) || dm_automap(z)) && !mf_mapped(z)) {
            const bool mapram = z.porte3 & 0x40;
            if (s == 0 && !mapram) {
                z.rd[s] = z.sram + 0x10000;
                z.rd_kind[s] = K_SRAM;
                z.rd_tag[s] = T_DIVROM;
                z.rd_val[s] = 0;
                z.wr[s] = nullptr;
                z.wr_kind[s] = K_NONE;
                z.wr_tag[s] = T_NONE;
                z.wr_val[s] = 0;
            } else {
                const int bank = s == 0 ? 3 : (z.porte3 & 15);
                const bool ro = s == 0 || (mapram && bank == 3);
                uint8_t* p = z.sram + 0x20000 + bank * 0x2000;
                z.rd[s] = p;
                z.rd_kind[s] = K_SRAM;
                z.rd_tag[s] = T_DIV;
                z.rd_val[s] = bank;
                z.wr[s] = ro ? nullptr : p;
                z.wr_kind[s] = ro ? K_NONE : K_SRAM;
                z.wr_tag[s] = ro ? T_NONE : T_DIV;
                z.wr_val[s] = ro ? 0 : bank;
            }
        }
        if (s < 2 && z.bootrom_en) {                                  // the boot ROM wins on reads (ref §3.10)
            z.rd[s] = z.bootrom;
            z.rd_kind[s] = K_BOOT;
            z.rd_tag[s] = T_BOOT;
            z.rd_val[s] = 0;
        }
    }
}

inline uint8_t mem_read(ZXN& z, uint16_t a, Kind* kind = nullptr) {
    int s = a >> 13;
    if (kind) *kind = z.rd_kind[s];
    if (!z.rd[s]) return z.last_sram;
    uint8_t v = z.rd[s][a & 0x1FFF];
    if (z.rd_kind[s] == K_SRAM) z.last_sram = v;
    return v;
}

inline void mem_write(ZXN& z, uint16_t a, uint8_t v) {
    int s = a >> 13;
    if (z.wr[s]) z.wr[s][a & 0x1FFF] = v;
}

// The legacy paging ports rewrite the MMU (ref §3.6; zxnext:4560-4625). (The hardware does it one 28 MHz cycle
// after the write, port_memory_change_dly; here it's at once, inside the same I/O cycle.)
void port_memory_change(ZXN& z, bool was_allram, bool set_top = true) {
    if (z.port1ffd & 1) {                                             // all-RAM mode: four banks from 1FFD bits 2:1
        static const int BANKS[4][4] = {{0, 1, 2, 3}, {4, 5, 6, 7}, {4, 5, 6, 3}, {4, 7, 6, 3}};
        const int* b = BANKS[(z.port1ffd >> 1) & 3];
        for (int i = 0; i < 4; i++) { z.mmu[2 * i] = 2 * b[i]; z.mmu[2 * i + 1] = 2 * b[i] + 1; }
    } else {
        if (z.porteff7 & 8) { z.mmu[0] = 0x00; z.mmu[1] = 0x01; }     // EFF7 bit 3: RAM bank 0 over the ROM
        else { z.mmu[0] = z.mmu[1] = 0xFF; }
        int bank;
        switch (z.nr[0x8F] & 3) {                                     // the paging mode, NR 0x8F (ref §3.6)
            case 2: bank = ((z.port7ffd >> 3) & 0x18) | (z.port7ffd & 7); break;            // Pentagon 512
            case 3:
                if (!(z.porteff7 & 4)) {                                                      // Pentagon 1024
                    bank = ((z.port7ffd & 0x20)) | ((z.port7ffd >> 3) & 0x18) | (z.port7ffd & 7);
                    break;
                }
                [[fallthrough]];
            default: bank = ((z.portdffd & 0x0F) << 3) | (z.port7ffd & 7);                    // standard
        }
        if (set_top) {
            z.mmu[6] = (2 * bank) & 0xFF;
            z.mmu[7] = (2 * bank + 1) & 0xFF;
        }
        if (was_allram) {                                             // MMU2-5 come back only on leaving all-RAM
            z.mmu[2] = 0x0A; z.mmu[3] = 0x0B; z.mmu[4] = 0x04; z.mmu[5] = 0x05;
        }
    }
    remap(z);
}

// ---- the Next registers (ref §4, machine/nextregs.tsv)

// ---- the palettes (zxnext:4857-4859, 5312-5341, 6843-6960). NR 0x43 b6:4 picks the one to edit: b0 == b1 the
// ULA/tilemap RAM (b1 = tilemap), else the Layer 2/sprite RAM (b1 = sprites); b2 the second palette.
inline int pal_ram(const ZXN& z) { const int w = (z.nr[0x43] >> 4) & 7; return ((w >> 1) & 1) != (w & 1); }
inline int pal_addr(const ZXN& z) { const int w = (z.nr[0x43] >> 4) & 7; return ((w >> 1) & 1) << 9 | ((w >> 2) & 1) << 8 | z.pal_idx; }
inline uint16_t rgb9(uint8_t v) { return (v << 1) | (((v >> 1) | v) & 1); }  // an 8-bit RRRGGGBB, blue LSB = B1 | B0
inline void pal_step(ZXN& z) { if (!(z.nr[0x43] & 0x80)) z.pal_idx++; }  // auto-increment unless NR 0x43 b7

void nr_write(ZXN& z, int n, int v);
void do_reset(ZXN& z, bool hard);
inline bool locked(const ZXN& z);
void int_raise(ZXN& z, int i, bool unq);
inline uint16_t int_status(const ZXN& z);
void ctc_write(ZXN& z, int n, uint8_t v);
void ay_reset(ZXN& z);
bool mf_io(ZXN& z, uint16_t port, bool wr, uint8_t* out);
void nmi_request(ZXN& z, bool mf);
void ay_select(ZXN& z, uint8_t v);
void ay_write(ZXN& z, uint8_t v);
uint8_t ay_read(const ZXN& z, bool info);
inline bool joy_port_on(const ZXN& z, int port);
uint8_t joy_read(const ZXN& z, int port);

// ---- sprites' CPU side (video/sprites.vhd:594-748; zxnext:4265-4316, 4794-4855). Anything the renderer reads
// brings it up to now first (spr_catch_up), so a write lands between the sprites it falls between.
void spr_catch_up(ZXN& z);
// port 0x303B write: the attribute index to sprite v6:0's first byte, the pattern index to pattern v5:0, half v7
// (647-667, 728-741); tied (NR 0x09 b4), NR 0x34's sprite follows, b7 the pattern index's ("wear helmet", 607-609)
void spr_select(ZXN& z, int v) {
    z.spr_ai = (v & 0x7F) << 3;
    z.spr_pi = (v & 0x3F) << 8 | (v & 0x80);
    if (z.nr[0x09] & 0x10) z.spr_mirror = (v & 0x7F) | (z.spr_pi & 0x80);
}
// port 0x57 write: the attribute byte at the index; then the next byte, or the next sprite's first after byte 4, or
// after byte 3 when its b6 says there's no fifth (639-667, 669-715); tied, a move to the next sprite moves NR 0x34's
void spr_attr_port(ZXN& z, int v) {
    spr_catch_up(z);
    z.spr_attr[z.spr_ai >> 3][z.spr_ai & 7] = v;
    if ((z.spr_ai & 4) || ((z.spr_ai & 7) == 3 && !(v & 0x40))) {
        z.spr_ai = (((z.spr_ai >> 3) + 1) & 0x7F) << 3;
        if (z.nr[0x09] & 0x10) z.spr_mirror = (z.spr_ai >> 3) | (z.spr_pi & 0x80);
    } else z.spr_ai++;
}
// port 0x5B write: the pattern byte at the index, which counts on through all 14 bits (717-741)
void spr_pat_port(ZXN& z, int v) {
    spr_catch_up(z);
    z.spr_pat[z.spr_pi] = v;
    z.spr_pi = (z.spr_pi + 1) & 0x3FFF;
}
// NR 0x34 sets the mirror's sprite (b7 the pattern half); NR 0x35-0x39 write that sprite's attribute 0-4, and NR
// 0x75-0x79 then move to the next sprite, b7 the pattern index's (zxnext:4794-4855: the increment is the register's
// b6; sprites.vhd:594-612, 704-715). Tied, a change of the mirror's sprite moves the port's indexes there.
void spr_mirror_write(ZXN& z, int n, int v) {
    if (n == 0x34) z.spr_mirror = v;
    else {
        spr_catch_up(z);
        z.spr_attr[z.spr_mirror & 0x7F][(n & 0x0F) - 5] = v;
        if (!(n & 0x40)) return;
        z.spr_mirror = ((z.spr_mirror + 1) & 0x7F) | (z.spr_pi & 0x80);
    }
    if (z.nr[0x09] & 0x10) {
        z.spr_ai = (z.spr_mirror & 0x7F) << 3;
        z.spr_pi = (z.spr_mirror & 0x3F) << 8 | (z.spr_mirror & 0x80);
    }
}

// ---- the UARTs' and I2C's glue (zxnext:2237-2293, 2587-2598, 3180-3226, 3298-3379, 3494-3497)
const uint64_t F_SYS = 28000000;        // the master clock; NR 0x11's VGA settings (28.57-33 MHz) aren't tracked yet
inline bool uart_rerouted(const ZXN& z, int n) {                     // NR 0x0B: b7 on, b5 UART mode, b0 which UART
    return (z.nr[0x0B] & 0x80) && (z.nr[0x0B] & 0x20) && (z.nr[0x0B] & 1) == n;
}
inline bool uart_pi(const ZXN& z) { return z.nr[0xA0] & 0x10; }      // pi_uart_en = NR 0xA0 b4 (zxnext:2238)
// the Pi is fixed: it sends on GPIO 14 and listens on 15 (ruling f), so the Next meets it only with b5 swapping its
// pins (pi_uart_rx from GPIO 14, Tx on 15, zxnext:2282-2293); with b5 clear both face the Pi's own pins
inline bool uart_pi_talks(const ZXN& z) { return uart_pi(z) && (z.nr[0xA0] & 0x20); }
void int_raise(ZXN& z, int i, bool unq);
void serial_edges(ZXN& z);
void serial_tick(ZXN& z) {
    const int side = (z.nr[0x0B] >> 4) & 1;                           // b4: the left or right joystick port
    const bool jrx = !(z.joy[side] & 0x20), jcts_n = !(z.joy[side] & 0x10);   // not JOY(5), not JOY(4)
    for (int n = 0; n < 2; n++) {
        nserial::Uart& u = z.uart[n];
        const bool rr = uart_rerouted(z, n);
        const bool host = n == 0 || uart_pi_talks(z);
        const bool rx = rr ? jrx : host ? u.line_level : true;       // undriven pins idle high
        // UART 1's CTS: from the Pi's RTS (GPIO 17) with b5; clear unless the Pi UART and flow control are on (2293).
        // Without b5 it comes from GPIO 16, which the fixed Pi doesn't drive and which has no pull-up (accel_io[16]
        // in zxnext_pins_issue4.xdc: IOSTANDARD and DRIVE only), so on the machine it's undefined; read here as high,
        // not clear (ruling h; no test may depend on it)
        const bool cts_n = rr ? jcts_n : n == 0 ? u.host_cts_n
                         : (uart_pi(z) && (u.frame & 0x20)) ? (uart_pi_talks(z) ? u.host_cts_n : true) : false;
        nserial::uart_tick(u, z.t28, false, rx, cts_n, !rr && host);
        const bool wire = (!rr && host) ? u.t.out : true;             // what the host's receiving wire carries
        if (wire != u.wire) {
            u.wire = wire;
            if (u.tx_logging) u.tx_events.push_back({z.t28, wire});
        }
    }
    serial_edges(z);
}
// the UARTs' interrupt requests (zxnext:1900-1909), edge-detected (im2p:92-101); status records whatever's enabled
void serial_edges(ZXN& z) {
    const uint16_t req = (z.uart[1].o_tx_empty << 13) | (z.uart[0].o_tx_empty << 12) |
                         ((z.uart[1].o_near_full || (z.uart[1].o_avail && !(z.nr[0xC6] & 0x20))) << 2) |
                         ((z.uart[0].o_near_full || (z.uart[0].o_avail && !(z.nr[0xC6] & 0x02))) << 1);
    const uint16_t rise = req & ~z.uart_req;
    z.uart_req = req;
    for (int i : {1, 2, 12, 13}) if (rise & (1 << i)) int_raise(z, i, false);
}
uint8_t uart_read(ZXN& z, int reg) {
    nserial::Uart& u = z.uart[z.uart_sel];
    u.wake = 4;
    z.serial_on = true;
    switch (reg) {
        case 0: {                                                     // 0x143B: the Rx FIFO's head, or 0 (uart.vhd:322-343)
            const uint8_t v = u.rxf.empty() ? 0 : u.rxf.head() & 0xFF;
            u.rxf.pop();
            return v;
        }
        case 1: return (z.uart_sel ? 0x40 : 0) | u.presc_msb;         // 0x153B
        case 2: return u.frame;                                       // 0x163B
        default: {                                                    // 0x133B: status, its errors cleared by the read
            const bool brk = u.r.state == nserial::Rx::ERROR && u.r.shift == 0;
            const bool busy = u.t.state != nserial::Tx::IDLE || (u.frame & 0xC0);
            const uint8_t v = brk << 7 | u.st_framing << 6 | ((u.rxf.head() >> 8) & !u.rxf.empty()) << 5 |
                              (u.txf.empty() && !busy) << 4 | u.rxf.near_full() << 3 | u.st_overflow << 2 |
                              u.txf.full() << 1 | !u.rxf.empty();
            u.st_overflow = u.st_framing = false;                     // (uart.vhd:528-533: tx_rd's falling edge)
            return v;
        }
    }
}
void uart_write(ZXN& z, int reg, uint8_t v) {
    z.serial_on = true;
    switch (reg) {
        case 0: {                                                     // 0x143B: the prescaler's 14 low bits, 7 at a time
            nserial::Uart& u = z.uart[z.uart_sel];
            u.presc_lsb = (v & 0x80) ? (u.presc_lsb & 0x7F) | (v & 0x7F) << 7 : (u.presc_lsb & ~0x7Fu) | (v & 0x7F);
            u.wake = 4;
            break;
        }
        case 1:                                                       // 0x153B: select (b6), and b2:0 the prescaler's top if b4
            z.uart_sel = (v >> 6) & 1;
            if (v & 0x10) z.uart[z.uart_sel].presc_msb = v & 7;
            z.uart[z.uart_sel].wake = 4;
            break;
        case 2: {                                                     // 0x163B
            nserial::Uart& u = z.uart[z.uart_sel];
            u.frame = v; u.wake = 4;
            if (v & 0x80) {     // b7 holds both FIFOs, the status and both state machines in reset (uart.vhd:385, 528,
                                // uart_rx:208, uart_tx:162); a program's next access is an instruction later, so at once
                u.rxf.reset(); u.txf.reset(); u.avail_d = false; u.byte_d = 0; u.st_overflow = u.st_framing = false;
                u.r.state = nserial::Rx::PAUSE; u.t.state = nserial::Tx::IDLE;
            }
            break;
        }
        default: z.uart[z.uart_sel].txf.push(v); z.uart[z.uart_sel].wake = 4;         // 0x133B: into the Tx FIFO
    }
}
// the bus after a change of our outputs: the DS1307 sees each change and may answer on SDA (it never drives SCL)
void i2c_update(ZXN& z) {
    for (int k = 0; k < 4; k++) {
        const bool scl = z.i2c_scl, sda = z.i2c_sda && z.rtc.sda;
        if (scl == z.bus_scl && sda == z.bus_sda) return;
        const bool scl0 = z.bus_scl, sda0 = z.bus_sda;
        z.bus_scl = scl; z.bus_sda = sda;
        if (z.i2c_logging) z.i2c_log.push_back({z.t28 + 1, (uint64_t)scl, (uint64_t)sda});   // at the next CLK_28 edge
        nserial::rtc_bus(z.rtc, scl0, sda0, scl, sda, z.t28 + 1, F_SYS);
    }
}

int nr_read(ZXN& z, int n) {
    switch (n) {
        case 0x34: return z.spr_mirror & 0x7F;                        // '0' & the mirror's sprite (zxnext:5939-5940)
        case 0x28: return z.pal_stored;                               // NR 0x44's stored first byte (5337, 5910-5911)
        case 0x02: return (z.reset_type == 2 ? 2 : z.reset_type == 1 ? 1 : 0) | (z.nr[0x02] & 0x80) | z.nmi_flags;
        case 0x03: return (z.pal_sub << 7) | (z.pend_timing << 4) | (z.lock << 3) | z.mtype;   // the registers, not the
                                                                      // timing in effect; b7 NR 0x44's phase (5800-5801)
        case 0x05: return z.nr[0x05];
        case 0x07: return (z.speed_eff << 4) | z.speed_prog;                                  // ref §1.3
        case 0x0F: return z.issue == 4 ? 0x02 : 0x00;
        case 0x08:                                                    // b7 reads "unlocked", b6 the copy in effect
            return (locked(z) ? 0 : 0x80) | (z.eff_cd ? 0x40 : 0) | (z.nr[0x08] & 0x3F);   // (zxnext:5812-5813)
        case 0x1E: return (cvc(z) >> 8) & 1;                          // the active line (zxnext:5889-5893)
        case 0x1F: return cvc(z) & 0xFF;
        case 0x10: return z.coreid << 2;                              // no buttons pressed (zxnext:5830-5831)
        case 0x22:                                                    // the pulse, port FF b6, the line interrupt's
            if (z.in_latch_dt >= 0) z.in_latch_at = z.t28 + z.in_latch_dt;   // an IN: b7 is set again at its latch
            return (z.int_low ? 0x80 : 0) | ((z.portff >> 4) & 4) | (z.nr[0x22] & 3);       // (zxnext:5898-5899)
        case 0x81: return 0x80 | (z.nr[0x81] & 0x70);                 // b7 the bus's ROMCS pin, high (zxnext:6032)
        case 0x2C: case 0x2E: return 0x80;                            // the Pi's I2S audio, off: 0x200 >> 2 (zxnext:2316-2317,
                                                                      // 5912-5913)
        case 0x2D: return 0x00;                                       // the Pi's latched I2S sample: none (zxnext:5917-5918)
        case 0x69:                                                    // aliases of 123B b1, 7FFD b3, FF b5:0 (zxnext:6002-6003)
            return (z.l2_en ? 0x80 : 0) | (z.port7ffd & 0x08) << 3 | (z.portff & 0x3F);
        case 0xA2: return (z.nr[0xA2] & 0xDD) | 0x02;                 // b5 reads 0, b1 reads 1 (zxnext:6098-6099)
        case 0xC0: return (z.nr[0xC0] & 0xE9) | (z.im_mode << 1);     // the snooped IM mode in b2:1 (zxnext:6136-6137)
        case 0x20: {                                                  // line, ULA, CTC 3-0 (zxnext:5895-5896)
            const uint16_t st = int_status(z);
            return ((st & 1) << 7) | (((st >> 11) & 1) << 6) | ((st >> 3) & 0x0F);
        }
        case 0xC6: return z.nr[0xC6] & 0x77;                          // (zxnext:6151-6152)
        case 0x18: case 0x19: case 0x1A: case 0x1B: return z.clip[n - 0x18][z.clip_idx[n - 0x18]];   // (5854-5885)
        case 0x1C: return z.clip_idx[3] << 6 | z.clip_idx[2] << 4 | z.clip_idx[1] << 2 | z.clip_idx[0];  // (5886-5887)
        case 0x40: return z.pal_idx;                                  // the palettes (zxnext:5942-5955)
        case 0x41: return (z.pal[pal_ram(z)][pal_addr(z)] >> 1) & 0xFF;
        case 0x44: { const uint16_t e = z.pal[pal_ram(z)][pal_addr(z)]; return (e >> 14) << 6 | (e & 1); }
        case 0x68: return (z.nr[0x68] & 0xF5) | (z.ulap_en ? 0x08 : 0);   // b3 is port_ff3b_ulap_en (zxnext:5998-5999)
        case 0x61: return z.cop_waddr & 0xFF;                         // (zxnext:5990-5994)
        case 0x62: return (z.cop_mode << 6) | (z.cop_waddr >> 8);
        case 0xC5: {
            int v = 0;
            for (int n = 0; n < 4; n++) v |= ((z.ctc[n].ctrl >> 4) & 1) << n;
            return v;
        }
        case 0xC8: { const uint16_t st = int_status(z); return ((st & 1) << 1) | ((st >> 11) & 1); }   // (6154-6155)
        case 0xC9: return (int_status(z) >> 3) & 0xFF;                // CTC 7-0 (6157-6158)
        case 0xCA: {                                                  // the UARTs (6160-6161)
            const uint16_t st = int_status(z);
            const int t1 = (st >> 13) & 1, r1 = (st >> 2) & 1, t0 = (st >> 12) & 1, r0 = (st >> 1) & 1;
            return (t1 << 6) | (r1 << 5) | (r1 << 4) | (t0 << 2) | (r0 << 1) | r0;
        }
        case 0xC4:                                                    // (zxnext:6144-6145, 6618)
            return (z.nr[0xC4] & 0x80) | (z.nr[0x22] & 2) | ((z.portff & 0x40) ? 0 : 1);
        case 0x8E:                                                    // the same layout, bit 3 = 1 (zxnext 6065-6066)
            return ((z.portdffd & 1) << 7) | ((z.port7ffd & 7) << 4) | 8 | ((z.port1ffd & 1) << 2) |
                   ((z.port1ffd & 1) ? ((z.port1ffd >> 1) & 3) : (((z.port1ffd >> 1) & 2) | ((z.port7ffd >> 4) & 1)));
        default:
            if (n >= 0x50 && n <= 0x57) return z.mmu[n - 0x50];
            return z.nr[n];
    }
}

void nr_write(ZXN& z, int n, int v) {
    v &= 0xFF;
    if (n == 0x0B || n == 0xA0 || n == 0xC6) { z.uart[0].wake = z.uart[1].wake = 4; z.serial_on = true; }   // routing, interrupts
    if (n >= 0x2C && n <= 0x2E && (z.nr[0x08] & 8)) {               // the DACs from next registers (soundrive:66-90)
        if (n == 0x2C) z.audio.dac[1] = v;                            // left: B
        else if (n == 0x2E) z.audio.dac[2] = v;                       // right: C
        else z.audio.dac[0] = z.audio.dac[3] = v;                     // mono: A and D
    }
    switch (n) {
        case 0x00: case 0x01: case 0x0E: case 0x0F: case 0x1E: case 0x1F: case 0xB0: case 0xB1: case 0xB2: case 0xDA:
            return;                                                   // read-only (machine/nextregs.tsv)
        case 0x08:
            if (v & 0x80) z.port7ffd &= ~0x20;                        // b7 clears 7FFD's lock, unstored (zxnext:3612-3614)
            z.nr[0x08] = v & 0x7F;
            return;
        case 0x10:                                                    // the core id, in config mode only (zxnext:5612-5640)
            if (z.config_mode) {
                if (z.issue != 4) z.coreid = v & 0x1F;
                else if (!(v & 0x10) && (v & 0x0F) != 0x0F) z.coreid = v & 0x0F;
            }
            return;                                                   // (b7, flash boot, reloads another core: not modelled)
        case 0x22:
            z.portff = (z.portff & ~0x40) | ((v & 4) << 4);           // b2 is port FF b6 (zxnext:3577-3578)
            z.ula_int_disabled = z.portff & 0x40;
            z.nr[0x22] = v & 3;                                       // the line interrupt: enable, line b8 (zxnext:5233-5236)
            return;
        case 0x18: case 0x19: case 0x1A: case 0x1B: {                 // clip windows: x1, x2, y1, y2 in turn (5180-5230)
            const int k = n - 0x18;
            z.clip[k][z.clip_idx[k]] = v;
            z.clip_idx[k] = (z.clip_idx[k] + 1) & 3;
            return;
        }
        case 0x1C:                                                    // reset the clip indices (5216-5229)
            for (int k = 0; k < 4; k++) if (v & (1 << k)) z.clip_idx[k] = 0;
            return;
        case 0x6A:                                                    // LoRes: Radastan b5, its display file b4, offset
            z.nr[0x6A] = v & 0x3F;
            return;
        case 0x2F:                                                    // the tilemap's X scroll, bits 9:8 (5269)
            z.nr[0x2F] = v & 3;
            return;
        case 0x4C:                                                    // its transparent index (5351)
            z.nr[0x4C] = v & 15;
            return;
        case 0x6E: case 0x6F:                                         // its bases: b7 bank 7, b5:0 the page (5406-5411)
            z.nr[n] = v & 0xBF;
            return;
        case 0x70:                                                    // Layer 2: resolution b5:4, palette offset b3:0
            z.nr[0x70] = v & 0x3F;
            return;
        case 0x71:                                                    // Layer 2's X scroll, bit 8
            z.nr[0x71] = v & 1;
            return;
        case 0x40:                                                    // the palette index (zxnext:5312-5314)
            z.pal_idx = v;
            z.pal_sub = false;
            return;
        case 0x41:                                                    // an 8-bit colour, priority cleared (4857-4859, 5316-5321)
            z.pal[pal_ram(z)][pal_addr(z)] = rgb9(v);
            pal_step(z);
            z.pal_sub = false;
            return;
        case 0x43:                                                    // (5326-5333)
            z.nr[0x43] = v;
            z.pal_sub = false;
            return;
        case 0x44:                                                    // RRRGGGBB, then the blue LSB and priority (5335-5341)
            if (!z.pal_sub) z.pal_stored = v;
            else {
                z.pal[pal_ram(z)][pal_addr(z)] = (v >> 6) << 14 | z.pal_stored << 1 | (v & 1);
                pal_step(z);
            }
            z.pal_sub = !z.pal_sub;
            return;
        case 0x68:                                                    // b3: ULA+ on (zxnext:4491-4492; the rest: later)
            z.nr[0x68] = v;
            z.ulap_en = v & 8;
            return;
        case 0x06:                                                    // PS/2 mode (bit 2) only in config mode
            z.nr[0x06] = z.config_mode ? v : (v & ~0x04) | (z.nr[0x06] & 0x04);   // (zxnext:5100-5109)
            if ((v & 3) == 3) ay_reset(z);                            // PSG mode 11 holds the AYs in reset (6286)
            return;
        case 0x12: case 0x13:                                         // Layer 2's banks, 7 bits (zxnext:5157-5161)
            z.nr[n] = v & 0x7F;
            remap(z);
            return;
        case 0xC5:                                                    // each channel's interrupt enable (control b7):
            for (int n = 0; n < 4; n++)                               // four channels, b7:4 aren't there (zxnext:4020-4021,
                z.ctc[n].ctrl = (z.ctc[n].ctrl & ~0x10) | (((v >> n) & 1) << 4);   // 4030, 6148-6149; ref §9 D-5)
            return;
        case 0x09:                                                    // b3 clears divMMC's mapram, reads 0 (zxnext:4125-4126,
            if (v & 0x08) z.porte3 &= ~0x40;                          // 5820)
            z.nr[0x09] = v & ~0x08;
            remap(z);
            return;
        case 0x0A: case 0x83:                                         // divMMC's automap and port enables
            z.nr[n] = v;
            if (dm_automap_reset(z)) z.dm_hold = z.dm_held = z.dm_instant = z.dm_pending = false;
            remap(z);
            return;
        case 0xC0:
            z.nr[0xC0] = v & 0xE9;                                    // (zxnext:5533-5536)
            if (!(v & 1)) {                                           // pulse mode resets the chain (im2p:96, im2_reset_n)
                z.im2_req = 0;
                memset(z.im2_state, 0, sizeof z.im2_state);
            }
            return;
        case 0x20:                                                    // raise line (b7), ULA (b6), CTC 3-0 (b3:0)
            if (v & 0x80) int_raise(z, 0, true);                      // regardless of enables (zxnext:1905-1906)
            if (v & 0x40) int_raise(z, 11, true);
            for (int c = 0; c < 4; c++) if (v & (1 << c)) int_raise(z, 3 + c, true);
            return;
        case 0xC6:
            z.nr[0xC6] = v & 0x77;
            return;
        case 0x60: case 0x63:                                         // copper data, 8-bit or 16-bit (zxnext:3918-3940,
            if (n == 0x60) z.cop_ram[z.cop_waddr] = v;                // 5356-5375): 0x60 writes each byte; 0x63 holds the
            else if (z.cop_waddr & 1) {                               // even byte and writes both on the odd one
                z.cop_ram[z.cop_waddr - 1] = z.cop_stored;
                z.cop_ram[z.cop_waddr] = v;
            }
            if (!(z.cop_waddr & 1)) z.cop_stored = v;
            z.cop_waddr = (z.cop_waddr + 1) & 0x7FF;
            return;
        case 0x61:
            z.cop_waddr = (z.cop_waddr & 0x700) | v;
            return;
        case 0x62:
            z.cop_mode = v >> 6;
            z.cop_waddr = (z.cop_waddr & 0xFF) | ((v & 7) << 8);
            return;
        case 0xC8:                                                    // write 1 to clear (zxnext:1911-1914)
            if (v & 1) z.int_status &= ~(1 << 11);
            if (v & 2) z.int_status &= ~1;
            return;
        case 0xC9:
            z.int_status &= ~((uint16_t)v << 3);
            return;
        case 0xCA:
            if (v & 0x40) z.int_status &= ~(1 << 13);
            if (v & 0x04) z.int_status &= ~(1 << 12);
            if (v & 0x30) z.int_status &= ~(1 << 2);
            if (v & 0x03) z.int_status &= ~(1 << 1);
            return;
        case 0x69:                                                    // (zxnext:3866, 3616-3617, 3575-3576)
            z.l2_en = v & 0x80;
            z.port7ffd = (z.port7ffd & ~0x08) | ((v >> 3) & 0x08);
            z.portff = (z.portff & 0xC0) | (v & 0x3F);
            return;
        case 0x81:
            z.nr[0x81] = v & 0x70;                                    // the speed is forced to 00 (zxnext:5429-5433)
            return;
        case 0xC4:                                                    // (zxnext:5544-5547, 3579-3580)
            z.nr[0xC4] = v & 0x80;
            z.nr[0x22] = (z.nr[0x22] & ~2) | (v & 2);
            z.portff = (z.portff & ~0x40) | ((v & 1) ? 0 : 0x40);
            z.ula_int_disabled = z.portff & 0x40;
            return;
        case 0x02:                                                    // reset (ref §4.3)
            z.nr[0x02] = (z.nr[0x02] & 0x7F) | (v & 0x80);
            {                                                         // b3/b2 request an NMI (zxnext:3770-3805): the flags set
                const bool accept = z.nmi_state <= 1;                 // only while one may be accepted, and a 0 clears them
                if (v & 0x08) { if (accept) z.nmi_flags |= 0x08; } else z.nmi_flags &= ~0x08;
                if (v & 0x04) { if (accept) z.nmi_flags |= 0x04; } else z.nmi_flags &= ~0x04;
                if ((v & 0x08) && (z.nr[0x06] & 0x08)) nmi_request(z, true);    // with NR 0x06 b3 / b2 (2049-2050)
                else if ((v & 0x04) && (z.nr[0x06] & 0x10)) nmi_request(z, false);
            }
            if (v & 2) do_reset(z, true);
            else if (v & 1) do_reset(z, false);
            return;
        case 0x03: {                                                  // machine type (ref §4.3)
            z.bootrom_en = false;                                     // any write turns the boot ROM off
            if ((v & 0x80) && !z.lock && !(v & 0x08)) {
                int t = (v >> 4) & 7;
                z.pend_timing = t == 0 ? 1 : t >= 5 ? 3 : t;          // 000 -> 48K, 101-111 -> +3
            }
            if (v & 0x08) z.lock ^= 1;
            int type = v & 7;
            if (type == 7) z.config_mode = true;
            else if (type != 0) {
                if (z.config_mode && type <= 4) z.mtype = type;       // types 1-4, only in config mode (zxnext:5076-5083)
                z.config_mode = false;
            }
            remap(z);
            return;
        }
        case 0x04:
            z.nr04 = v & 0x7F;
            remap(z);
            return;
        case 0x05:
            z.nr[0x05] = v;
            z.pend_hz60 = (v >> 2) & 1;
            return;
        case 0x07:
            z.speed_prog = v & 3;                                     // takes effect between bus cycles (ref §1.3)
            return;
        case 0x8E: {                                                  // the 128K paging state at once, ignoring the lock
            bool was_allram = z.port1ffd & 1;
            if (v & 8) {
                z.port7ffd = (z.port7ffd & ~7) | ((v >> 4) & 7);
                z.portdffd = (v >> 7) & 1;                            // clears DFFD's high bits
            }
            z.port1ffd = (z.port1ffd & ~1) | ((v >> 2) & 1);
            if (v & 4) z.port1ffd = (z.port1ffd & ~6) | ((v & 3) << 1);  // special mode: the all-RAM configuration
            else {
                z.port7ffd = (z.port7ffd & ~0x10) | ((v & 1) << 4);   // normal mode: the ROM selection
                z.port1ffd = (z.port1ffd & ~4) | ((v & 2) << 1);
            }
            port_memory_change(z, was_allram, (v & 8) != 0);          // MMU6/7 kept after a write with bit 3 clear
            return;
        }
        case 0x85:                                                    // bits 6:4 aren't kept (zxnext:5445-5459,
        case 0x89:                                                    // 6045, 6057)
            z.nr[n] = v & 0x8F;
            return;
        case 0x8C:                                                    // the alternate ROM and the ROM locks
            z.nr[0x8C] = v;
            remap(z);
            return;
        case 0x34: case 0x35: case 0x36: case 0x37: case 0x38: case 0x39:
        case 0x75: case 0x76: case 0x77: case 0x78: case 0x79:        // the sprite mirror; 0x35-0x39/0x75-0x79 read 0
            spr_mirror_write(z, n, v);
            return;
        case 0x15: case 0x4B:                                         // read by the renderer as it writes: zero on top,
            spr_catch_up(z);                                          // the transparent index
            z.nr[n] = v;
            return;
        case 0x8F:
            z.nr[0x8F] = v & 3;
            port_memory_change(z, z.port1ffd & 1);
            return;
        default:
            if (n >= 0x50 && n <= 0x57) {
                z.mmu[n - 0x50] = v;
                remap(z);
                return;
            }
            z.nr[n] = v;
    }
}

void do_reset(ZXN& z, bool hard) {
    z.spr_ai = z.spr_pi = z.spr_mirror = 0;                           // sprites.vhd's reset (the RAMs keep)
    z.uart_sel = 0;                                                   // the UARTs' reset (uart.vhd:262-319): FIFOs, state
    for (auto& u : z.uart) {
        if (hard) u.hard_reset();
        u.rxf.reset(); u.txf.reset(); u.r = nserial::Rx(); u.r.state = nserial::Rx::PAUSE; u.t = nserial::Tx();
        u.avail_d = false; u.byte_d = 0; u.st_overflow = u.st_framing = false; u.wake = 4;
    }
    z.uart_req = 0;                                                   // im2p's int_req_d: high requests rise again
    z.serial_on = true;
    for (auto& u : z.uart) { u.o_tx_empty = true; u.o_avail = u.o_near_full = false; }
    z.i2c_scl = z.i2c_sda = true;                                     // released (zxnext:3193, 3204)
    i2c_update(z);
    z.spr_status = 0;
    z.spr_state = 0; z.spr_idx = 0; z.spr_vcount = 0; z.spr_disp = 0; z.spr_t = z.t28; z.spr_swap_at = 0;
    z.sa_rt = z.sa_h = z.sa_vis = z.sa_rot = z.sa_xm = z.sa_ym = false;
    z.sa_x = z.sa_y = z.sa_pat = z.sa_pal = z.sa_xs = z.sa_ys = 0;
    if (hard) {
        z.reset_type = 4;
        for (auto& r : NR_RESET) if (r.hard >= 0) z.nr[r.reg] = r.hard;
        z.config_mode = true;
        z.mtype = 3;
        z.lock = 0;
        z.nr04 = 0;
        z.coreid = 1;                                                 // the FPGA reloads: declared values (ref §7.1)
        memset(z.pal, 0, sizeof z.pal);                               // the palette RAMs have no init file (none.bin.txt)
        z.timing = z.pend_timing = 3;
        z.hz60 = z.pend_hz60 = 0;
        z.issue = z.issue;
    } else {
        z.reset_type = z.reset_type == 4 ? 2 : 1;                     // the first soft reset reads "hard" (ref §4.3)
        for (auto& r : NR_RESET) if (r.soft >= 0) z.nr[r.reg] = r.soft;
        for (int r : {0x80, 0x8C}) z.nr[r] = (z.nr[r] & 0x0F) | ((z.nr[r] << 4) & 0xF0);   // zxnext:2141-2145, 2210-2214
        z.nr[0x06] |= 0xA0;                                           // the speed and 50/60 hotkeys back on, contention
        z.nr[0x08] &= ~0x40;                                          // back on, sprite tie off (zxnext:4871-4876)
        z.nr[0x09] &= ~0x10;
        if (z.nr[0x85] & 0x80) {                                      // the port enables come back if NR 0x85 b7 = 1,
            z.nr[0x82] = z.nr[0x83] = z.nr[0x84] = 0xFF;              // and the bus's if NR 0x89 b7 = 0 (sic:
            z.nr[0x85] |= 0x0F;                                       // zxnext:4991-5007)
        }
        if (!(z.nr[0x89] & 0x80)) {
            z.nr[0x86] = z.nr[0x87] = z.nr[0x88] = 0xFF;
            z.nr[0x89] |= 0x0F;
        }
    }
    if (z.config_mode) z.bootrom_en = true;                           // ref §3.10
    static const uint8_t MMU0[8] = {0xFF, 0xFF, 0x0A, 0x0B, 0x04, 0x05, 0x00, 0x01};   // ref §3.3
    memcpy(z.mmu, MMU0, 8);
    z.port7ffd = z.port1ffd = z.portdffd = z.porteff7 = z.portff = 0;
    z.border = 0;
    z.speed_prog = z.speed_eff = 0;
    z.eff_cd = false;                                                 // (zxnext:5706-5709)
    z.l2_en = false;                                                  // (zxnext:3849)
    {                                                                 // the clip windows (zxnext:4898-4920)
        static const uint8_t C[4][4] = {{0, 255, 0, 191}, {0, 255, 0, 191}, {0, 255, 0, 191}, {0, 159, 0, 255}};
        memcpy(z.clip, C, sizeof C);
        memset(z.clip_idx, 0, sizeof z.clip_idx);
    }
    z.pal_idx = 0;                                                    // (zxnext:4938-4948)
    z.pal_sub = false;
    z.cvc_off = 0;                                                    // NR 0x64 resets to 0 (zxnext:4963)
    z.porte3 = 0;                                                     // (zxnext:4114-4117; divmmc:107-140)
    z.l2_wr = z.l2_rd = z.l2_shadow = false;                          // (zxnext:3847-3854)
    z.l2_seg = z.l2_off = 0;
    z.dm_hold = z.dm_held = z.dm_instant = z.dm_pending = false;
    z.snoop = 0;
    z.im_mode = 0;
    z.reti_seen = false;
    z.int_status = z.im2_req = 0;
    memset(z.im2_state, 0, sizeof z.im2_state);
    for (auto& c : z.ctc) c = ZXN::Ctc();                             // (ctc_chan.vhd: reset_hard)
    z.cop_mode = z.cop_waddr = z.cop_pc = 0;                          // (zxnext:4959-4963; copper:52-56)
    z.cop_stored = 0;
    z.cop_dout = z.cop_dout_d = z.cop_req = false;
    z.cop_data = 0;
    z.nmi_flags = 0;                                                  // (zxnext:3784-3785, 3797-3798)
    ay_reset(z);
    z.db.reset();                                                     // (dma:211-245; t80n:1690)
    z.nmi_cause = z.nmi_state = 0;                                    // (zxnext:2057-2060, 2113)
    z.nmi_pending_mf = z.nmi_pending_dm = false;
    z.mf_active = z.mf_enable = z.mf_fetch66 = false;                 // (multiface:63-120)
    z.mf_invisible = true;
    z.dm_button = false;
    z.ulap_mode = z.ulap_index = 0;                                   // (zxnext:4469-4471, 4487-4488)
    z.ulap_en = false;
    z.nr_sel = 0x24;
    z.ula_int_disabled = false;
    z.int_req = z.int_low = false;
    z.in_latch_at = 0;
    z.rd_open = false;
    z.int_count = 0;
    z.int_log.clear();
    z.wait_next = false;
    z.pins = z80_init(&z.cpu);
    z.cpu.z80n = true;                                                // the Z80N's instructions (Strobe Fern's z80.h)
    z.stackless_retn = false;
    remap(z);
    // the Tx FIFOs are empty through the reset, so those requests rise at the first clock after it and their statuses
    // set, enabled or not (im2p:92-101, 156-160; Loam's foil): nothing can look sooner, so it's done here
    serial_edges(z);
}

// ---- ports (ref §5.1; zxnext:2537-2658). Layer 2: the Next register ports, 0xFE, 0xFF, and the legacy paging ports.

// the internal enable for a port (NR 0x82-0x85, bit numbers as ref §5.1's table; the expansion bus: later)
inline bool port_en(const ZXN& z, int bit) { return (z.nr[0x82 + bit / 8] >> (bit % 8)) & 1; }
inline bool fd(uint16_t port) { return (port & 3) == 1; }             // A1:0 = 01, the 128K-style partial decode
inline bool dec_1ffd(const ZXN& z, uint16_t port) { return (port >> 12) == 0x1 && fd(port) && port_en(z, 3); }
inline bool dec_7ffd(const ZXN& z, uint16_t port) {
    if ((port & 0x8000) || !fd(port) || !port_en(z, 1) || dec_1ffd(z, port)) return false;
    return z.timing != 3 || (port & 0x4000);                          // A14 = 1 too under +3 timing
}
// 7FFD bit 5, except in Pentagon 1024 mode, where it's a bank bit (ref §3.6)
inline bool locked(const ZXN& z) { return (z.port7ffd & 0x20) && !((z.nr[0x8F] & 3) == 3 && !(z.porteff7 & 4)); }

// The floating bus on port 0xFF (ref §2.5; 48K and 128K timing only): inside the 256 x 192 area, the ULA's latest
// fetch: the bitmap byte from slot 9, the attribute from slot B, the next bitmap from slot D, the next attribute from
// slot F of each 16-pixel group (each held to the next odd slot; slot 0 still holds the group's last attribute);
// 0xFF in slots 1-8 and in the border. PROVISIONAL: which cell a group fetches is my reading of ref §2.5's slots
// (group g fetches cells 2g and 2g+1 of line vc_ula); ula.vhd 218-345 and a probe settle it.
uint8_t floating_bus(const ZXN& z) {
    if (z.timing == 3 || z.timing == 4) return 0xFF;                  // +3 has its own port; Pentagon none (later)
    int h = hc_ula(z), v = vc_ula(z);
    int slot = h & 15;
    if (slot == 0) h -= 1;                                            // slot 0: the previous group's attribute
    if (h < 0 || h >= 256 || v >= 192 || (slot >= 1 && slot <= 8)) return 0xFF;
    int col = (h >> 4) * 2 + ((slot >= 13 || slot == 0) ? 1 : 0);
    const uint8_t* scr = (z.port7ffd & 8) ? z.bram7 : z.bram5;        // the shadow screen reads bank 7 (ref §2.5)
    bool attr = slot == 11 || slot == 12 || slot == 15 || slot == 0;
    if (attr) return scr[0x1800 + (v >> 3) * 32 + col];
    return scr[((v & 0xC0) << 5) | ((v & 7) << 8) | ((v & 0x38) << 2) | col];
}

inline bool dma_port_decode(const ZXN& z, uint16_t port);       // port_dma (next_dma_bus.inc)
inline bool dma_port(const ZXN& z, uint16_t port);
uint8_t dma_port_read(ZXN& z, uint16_t port);
void dma_port_write(ZXN& z, uint16_t port, uint8_t v);

uint8_t io_read(ZXN& z, uint16_t port) {
    if (dma_port(z, port)) return dma_port_read(z, port);           // the DMA (next_dma_bus.inc)
    if (port == 0x243B) return z.nr_sel;                              // both decode all 16 bits (ref §4.1)
    if (port == 0x253B) return nr_read(z, z.nr_sel);
    if (port == 0x303B && port_en(z, 14)) {                           // sprite status, cleared by the read (979-995)
        spr_catch_up(z);
        const uint8_t v = z.spr_status;
        z.spr_status = 0;
        return v;
    }
    if (!(port & 1)) {                                                // 0xFE: the half-rows selected by A8-A15 low
        uint8_t v = 0x1F;
        for (int r = 0; r < 8; r++) if (!(port & (0x100 << r))) v &= ~z.keys[r] & 0x1F;
        return 0xE0 | v;                                              // (EAR in, bit 6: later)
    }
    if ((port & 0xFF) == 0xFF) return floating_bus(z);                // always answered (ref §5.1)
    if ((port & 0xFF) == 0xEB && port_en(z, 11)) {                    // the read register as the CPU latches it, an edge
        uint8_t v = z.spi_rx;                                         // after the strobe: a byte due by then has landed
        for (int i = 0; i < z.spi_npend; i++)                         // (spi_master:155-175)
            if (z.spi_pend[i].due <= z.cpu_clocks + 1) v = z.spi_pend[i].byte;
        return v;
    }
    if ((port & 0xFF) == 0x3B && (port >> 11) == 2 && (((port >> 10) ^ ((port >> 9) & (port >> 8))) & 1) && port_en(z, 12))
        return uart_read(z, (port >> 8) & 3);                         // the UARTs (zxnext:2598, 3327)
    if ((port == 0x103B || port == 0x113B) && port_en(z, 10))         // I2C: the lines as the bus has them (3215-3226)
        return 0xFE | (port == 0x103B ? z.bus_scl : z.bus_sda);
    if ((port & 0xFF) == 0xDF && port_en(z, 13)) {                    // the Kempston mouse (zxnext:2627-2629, 3496-3520)
        const int a = (port >> 8) & 0x0F;
        if (a == 0x0B) return z.mouse_x;
        if (a == 0x0F) return z.mouse_y;
        if (a == 0x0A)
            return (z.mouse_wheel & 15) << 4 | 8 | (~z.mouse_btn & 4) | (~z.mouse_btn & 1) << 1 | (~z.mouse_btn & 2) >> 1;
    }
    if ((port & 0xFF) == 0x1F && port_en(z, 6) && joy_port_on(z, 0x1F)) return joy_read(z, 0x1F);   // (zxnext:2633)
    if ((port & 0xFF) == 0x37 && port_en(z, 7) && joy_port_on(z, 0x37)) return joy_read(z, 0x37);   // (zxnext:2634)
    { uint8_t v; if (mf_io(z, port, false, &v)) return v; }           // the multiface (zxnext:2569-2575, 4248-4263)
    if (fd(port) && (port & 4) && port_en(z, 16)) {                   // the AY: FFFD, BFFD (+3 timing), BFF5
        const int hi = port >> 14;                                    // (zxnext:2606-2608, 2730)
        if (hi == 2 && !(port & 8)) return ay_read(z, true);
        if (hi == 3 || (hi == 2 && z.timing == 3)) return ay_read(z, false);
    }
    if (port == 0xFF3B && port_en(z, 24))                             // ULA+ (zxnext:4497-4508)
    {
        if (z.ulap_mode != 0) return z.ulap_en;                       // mode 00: the entry, GGGRRRBB (zxnext:4497-4505)
        const uint16_t e = z.pal[0][((z.nr[0x43] >> 6) & 1) << 8 | 0xC0 | z.ulap_index];
        return ((e >> 3) & 7) << 5 | ((e >> 6) & 7) << 2 | ((e >> 1) & 3);
    }
    if ((port & 0xF8FF) == 0x183B && port_en(z, 27))                  // the CTC: channel by A10:8, 4-7 answer 00
        return ((port >> 8) & 7) < 4 ? z.ctc[(port >> 8) & 7].count : 0x00;    // (zxnext:2649, 2792; ctc:155-176)
    if ((port & 0xFF) == 0xE3 && dm_en(z)) return z.porte3 & 0xCF;    // divMMC (zxnext:2567, 4131)
    if (port == 0x123B && port_en(z, 15))                             // Layer 2 (zxnext:2594, 2781; the offset: unread)
        return (z.l2_seg << 6) | (z.l2_shadow << 3) | (z.l2_rd << 2) | (z.l2_en << 1) | z.l2_wr;
    return 0xFF;                                                      // nobody answers (ref §5.2)
}

void io_write(ZXN& z, uint16_t port, uint8_t v) {
    if (dma_port(z, port)) dma_port_write(z, port, v);              // the DMA (next_dma_bus.inc)
    if (port == 0x243B) { z.nr_sel = v; return; }
    if (port == 0x253B) { nr_write(z, z.nr_sel, v); return; }
    if ((port & 0xFF) == 0x3B && (port >> 11) == 2 && (((port >> 10) ^ ((port >> 9) & (port >> 8))) & 1) && port_en(z, 12))
        uart_write(z, (port >> 8) & 3, v);                            // the UARTs (zxnext:2598, 3327)
    if ((port == 0x103B || port == 0x113B) && port_en(z, 10)) {       // I2C: b0 drives the line, 0 low (3189-3211)
        (port == 0x103B ? z.i2c_scl : z.i2c_sda) = v & 1;
        i2c_update(z);
    }
    if (port_en(z, 14)) {                                             // sprites (zxnext:2638-2640, 2746-2749)
        if (port == 0x303B) spr_select(z, v);
        else if ((port & 0xFF) == 0x57) spr_attr_port(z, v);
        else if ((port & 0xFF) == 0x5B) spr_pat_port(z, v);
    }
    if (!(port & 1)) {                                                // 0xFE, A0 = 0 (ref §5.1)
        z.border = v & 7;
        z.audio.ear = (v >> 4) & 1;                                   // the beeper (zxnext:6410, audio_mixer:54-55)
        z.audio.mic = (v >> 3) & 1;                                   // NR 0x08 b0 gates it in the mixer
    }
    if ((port & 0xFF) == 0xE7 && port_en(z, 11)) {                    // slave select: one device only (zxnext 3258-3290)
        bool flash_ok = z.config_mode || z.reset_type == 4;           // the flash: config mode or before the first soft reset
        if ((v & 3) == 1 || (v & 3) == 2 || (flash_ok && (v == 0xFB || v == 0xF7 || v == 0x7F))) z.spi_cs = v;
        else z.spi_cs = 0xFF;
    }
    if ((port & 0xF8FF) == 0x183B && port_en(z, 27) && ((port >> 8) & 7) < 4) ctc_write(z, (port >> 8) & 7, v);
    mf_io(z, port, true, nullptr);
    if (fd(port) && (port & 4) && port_en(z, 16)) {                   // the AY (zxnext:2731-2732): FFFD loses to DFFD
        const bool dffd = (port >> 12) == 0xD && port_en(z, 2);
        if ((port >> 14) == 3 && !dffd) ay_select(z, v);
        else if ((port >> 14) == 2) ay_write(z, v);
    }
    if (z.nr[0x08] & 8) {                                             // the DACs, gated by NR 0x08 b3 (dac_hw_en)
        const int lo = port & 0xFF;
        const bool sd1 = port_en(z, 17), sd2 = port_en(z, 18), ad3f = port_en(z, 19), bc0f = port_en(z, 20);
        const bool mono_ad = (lo == 0xFB && port_en(z, 21) && !sd2) || (lo == 0xDF && port_en(z, 23));
        const bool mono_bc = lo == 0xB3 && port_en(z, 22);
        if (mono_ad || (lo == 0x1F && sd1) || (lo == 0xF1 && sd2) || (lo == 0x3F && ad3f)) z.audio.dac[0] = v;
        if (mono_bc || (lo == 0x0F && (sd1 || bc0f)) || (lo == 0xF3 && sd2)) z.audio.dac[1] = v;
        if (mono_bc || (lo == 0x4F && (sd1 || bc0f)) || (lo == 0xF9 && sd2)) z.audio.dac[2] = v;
        if (mono_ad || (lo == 0x5F && (sd1 || ad3f)) || (lo == 0xFB && sd2)) z.audio.dac[3] = v;
    }
    if (port == 0xBF3B && port_en(z, 24)) {                           // ULA+ mode and index (zxnext:4472-4477)
        z.ulap_mode = v >> 6;
        if (z.ulap_mode == 0) z.ulap_index = v & 0x3F;
    }
    if (port == 0xFF3B && port_en(z, 24)) {                           // mode 00: a palette entry; 01: the enable
        if (z.ulap_mode == 0)                                         // GGGRRRBB in, as register 0xFF (zxnext:4684, 6865)
            z.pal[0][((z.nr[0x43] >> 6) & 1) << 8 | 0xC0 | z.ulap_index] = rgb9(((v >> 2) & 7) << 5 | ((v >> 5) & 7) << 2 | (v & 3));
        else if (z.ulap_mode == 1) z.ulap_en = v & 1;
    }
    if (port == 0x123B && port_en(z, 15)) {                           // Layer 2's control (zxnext:3855-3864)
        if (v & 0x10) z.l2_off = v & 7;
        else {
            z.l2_en = v & 2;
            z.l2_wr = v & 1;
            z.l2_rd = v & 4;
            z.l2_shadow = v & 8;
            z.l2_seg = v >> 6;
        }
        remap(z);
    }
    if ((port & 0xFF) == 0xE3 && dm_en(z)) {                          // conmem, mapram (set only), bank (zxnext:4119-4122)
        z.porte3 = (v & 0x8F) | ((v | z.porte3) & 0x40);
        remap(z);
    }
    if ((port & 0xFF) == 0xFF && port_en(z, 0)) {                     // Timex port: bit 6 disables the ULA INT
        z.portff = v;
        z.ula_int_disabled = v & 0x40;
    }
    bool was_allram = z.port1ffd & 1;
    if (dec_7ffd(z, port) && !locked(z)) { z.port7ffd = v; port_memory_change(z, was_allram); }
    else if ((port >> 12) == 0xD && fd(port) && port_en(z, 2) && !locked(z)) {
        z.portdffd = v; port_memory_change(z, was_allram);
    } else if (dec_1ffd(z, port) && !locked(z)) { z.port1ffd = v; port_memory_change(z, was_allram); }
    else if ((port >> 12) == 0xE && (port & 0xFF) == 0xF7 && port_en(z, 26)) {
        z.porteff7 = v; port_memory_change(z, was_allram);
    }
}

// ---- contention (ref §1.5; zxula.vhd 577-600, zxnext 4422-4437)

// Is the CPU's address in a contended page? Decided by the MMU page alone, pages 0x00-0x0F only, by the machine
// *timing*: 48K bank 5; 128K pages with bit 1 set (banks 1, 3, 5, 7); +3 banks 4-7 (zxnext 4430-4434).
inline bool contended_page(const ZXN& z, uint16_t a) {
    int page = z.mmu[a >> 13];
    if (page >= 0x10) return false;
    switch (z.timing) {
        case 1: return page == 0x0A || page == 0x0B;
        case 2: return page & 2;
        case 3: return page >= 8;
        default: return false;
    }
}
// Is the port contended as the ULA's own? A0 = 0, and under 128K timing ports that decode as 7FFD (zxnext 4437).
inline bool contended_port(const ZXN& z, uint16_t port) {
    if ((port == 0xBF3B || port == 0xFF3B) && port_en(z, 24)) return true;   // ULA+ ("uno requires", zxnext:4437)
    return !(port & 1) || (z.timing == 2 && dec_7ffd(z, port));      // port_7ffd's own decode: not 1FFD, enabled (zxnext 2552)
}
// At each rising CPU edge: what does this T-state ask the ULA? zxula.vhd holds the clock for (a) a contended address
// while MREQ was high at the last rising edge and no contended I/O has begun (a memory cycle's T1, or an internal
// T-state not after an MREQ one), and (b) a contended port on the first T-state with IORQ low. In z80.h's pins (as
// zxcore.cpp's contend_check reads them, checked by Speccy-Zone against the documented tables): T1 shows MREQ with
// RD or WR; T2 MREQ alone; an I/O cycle shows IORQ from its first T-state, counted by io_phase.
inline void classify(ZXN& z, uint64_t p) {
    const uint16_t a = Z80_GET_ADDR(p);
    z.ck_mem = z.ck_port = false;
    if ((p & Z80_IORQ) && !(p & Z80_M1)) {
        z.io_phase = z.prev_io ? z.io_phase + 1 : 1;
        if (contended_port(z, a)) z.ck_port = z.io_phase == 2 || (contended_page(z, a) && z.io_phase == 1);
        else z.ck_mem = contended_page(z, a);                          // a contended high byte: every T-state
    } else if (p & Z80_MREQ) {
        z.ck_mem = (p & (Z80_RD | Z80_WR)) && !(p & Z80_RFSH) && contended_page(z, a);
    } else {
        z.ck_mem = !z.prev_mreq && !(p & Z80_IORQ) && contended_page(z, a);
    }
    z.prev_mreq = p & Z80_MREQ;
    z.prev_io = (p & Z80_IORQ) && !(p & Z80_M1);
}
// wait_s (zxula.vhd 582-583): slots with hc_ula(3:0) in 3-14 (decided a slot early: hc_adj = hc + 1), in the
// 256 x 192 area; only at 3.5 MHz, not with NR 0x08 bit 6, not in Pentagon timing (zxnext 4422).
inline bool wait_s(const ZXN& z) {
    if (z.speed_eff != 0 || z.eff_cd || z.timing == 4) return false;
    int h = hc_ula(z), v = vc_ula(z);
    int adj = ((h & 15) + 1) & 15;
    return adj >= 4 && h < 256 && v < 192;
}

// +3 timing's form (zxula.vhd 597-600): WAIT while MREQ is low on a contended page, in the window wait_s gives +3
// (hc_adj(3:1) = 000 as well: slots 15, 0 and 3-14). The T80N samples WAIT_n at the rising edge that ends T2 and
// each Tw (t80n.vhd's T-state process, "TState = 2 and WAIT_n = '0'"; t80na.vhd:193 passes it straight in), seeing
// the hc from before that edge. z80.h checks WAIT at the start of the T2 step, the edge that begins T2, and repeats
// the step while it's set; +3 never stretches the clock, so the deciding edge is one T on: hc_ula + 2, into the next
// row past the line's end (Loam's ContentionP3Exact). No I/O contention in +3 timing.
inline bool p3_wait_now(const ZXN& z) {
    if (!z.contention || z.timing != 3 || z.speed_eff != 0 || (z.nr[0x08] & 0x40)) return false;
    if (!z.p3_mem && !z.p3_waiting) return false;
    const Timing& t = T(z);
    int h = hc_ula(z) + 2, v = vc_ula(z);
    if (h >= t.hc_len) { h -= t.hc_len; v = (v + 1) % t.vc_len; }    // vc_ula steps at hc_ula 0
    int adj = ((h & 15) + 1) & 15;
    return (adj >= 4 || adj <= 1) && h < 256 && v < 192;
}

// ---- Layer 2 at the beam (video/layer2.vhd). (x, y) is the pixel relative to the ULA's paper; sample 0/1 the two
// 14 MHz halves. 256 x 192 lines up with the paper; the wide modes' counters start 32 pixels left and 32 lines above
// it (whc/wvc, ulat:476-507). Returns false where Layer 2 is off, outside its area, clipped, or past 2 MB.
bool l2_pixel(const ZXN& z, int x, int y, int sample, uint16_t& rgb, bool& prio) {
    if (!z.l2_en) return false;
    const int res = (z.nr[0x70] >> 4) & 3;
    const bool wide = res != 0;
    const int hc = wide ? x + 32 : x, vc = wide ? y + 32 : y;
    if (wide ? (hc < 0 || hc >= 320 || vc < 0 || vc >= 256) : (hc < 0 || hc >= 256 || vc < 0 || vc >= 192)) return false;
    const uint8_t* c = z.clip[0];                                     // the clip window, X doubled in the wide modes
    if (hc < (wide ? c[0] * 2 : c[0]) || hc > (wide ? c[1] * 2 + 1 : c[1]) || vc < c[2] || vc > c[3]) return false;
    const int xp = hc + (z.nr[0x16] | (z.nr[0x71] & 1) << 8), yp = vc + z.nr[0x17];   // x_pre, y_pre (l2:150-160)
    int xx, yy, addr;
    if (!wide) {
        xx = xp & 0xFF;
        yy = ((yp & 0x100) || (yp & 0xC0) == 0xC0) ? (yp + 64) & 0xFF : yp & 0xFF;   // 192 lines: +64 past them (l2:157)
        addr = yy << 8 | xx;                                          // row by row
    } else {
        xx = xp < 320 ? xp : (xp + 192) & 0x1FF;                      // one 320 taken off, mod 512 (l2:153-154)
        yy = yp & 0xFF;
        addr = xx << 8 | yy;                                          // column by column
    }
    const uint32_t sram = ((z.nr[0x12] & 0x7F) + 16) * 16384u + addr; // bank + 16, 16K units (l2:168-170)
    if (sram >= SRAM_SIZE) return false;
    uint8_t px = z.sram[sram];                                        // always SRAM, bank 5 included
    if (res & 2) px = sample ? px & 15 : px >> 4;                    // 1X = 640 x 256 x 4: high nibble, then low (l2:41, 198)
    px = (((px >> 4) + (z.nr[0x70] & 15)) & 15) << 4 | (px & 15);    // the palette offset (l2:200-203)
    const uint16_t e = z.pal[1][((z.nr[0x43] >> 2) & 1) << 8 | px];  // the second palette by NR 0x43 b2
    rgb = e & 0x1FF;
    prio = e >> 15;
    return true;
}

// ---- the tilemap at the beam (video/tilemap.vhd), on the wide 320 x 256 counters (whc/wvc: 32 left and above the
// paper). 40 x 32 tiles of 8 x 8, or 80 x 32 at 14 MHz (NR 0x6B b6); the map at NR 0x6E (b7 bank 7, b5:0 the 256-byte
// page), two bytes a tile (tile, attribute) or one with NR 0x6C's attribute (b5); 4-bit patterns at NR 0x6F, 32 bytes
// each, or 1-bit in text mode (b3); the attribute b7:4 palette offset, b3 X mirror, b2 Y mirror, b1 rotate, b0 below
// the ULA or (b1 of NR 0x6B) the 9th tile bit; scroll NR 0x2F/0x30 (10 bits) and NR 0x31; clip NR 0x1B (X in pairs).
inline uint8_t tm_byte(const ZXN& z, bool bank7, int page, int addr) {
    const int a = (((addr >> 8) + page) << 8 | (addr & 0xFF)) & 0x3FFF;   // (tilemap:240-243)
    return bank7 ? z.bram7[a & 0x1FFF] : z.bram5[a];
}
bool tm_pixel(const ZXN& z, int x, int y, int smp, uint16_t& rgb, bool& below, bool& text) {
    const uint8_t ctl = z.nr[0x6B];
    below = !(ctl & 1);                                               // the tilemap off: not NR 0x6B b0 (zxnext:6770)
    if (!(ctl & 0x80)) return false;
    const int whc = x + 32, wvc = y + 32;
    const uint8_t* c = z.clip[3];
    const bool wide = ctl & 0x40, strip = ctl & 0x20, t512 = ctl & 2;
    text = ctl & 8;
    // the fetch runs a tile ahead from (whc + scroll) wrapped, whatever the clip says, and its buffer's bit 8 is the
    // tile's below bit even where the pixel isn't shown (tilemap:388, 410, 445): so the tile comes first
    const int m = wide ? 640 : 320;
    const int xs = (wide ? 2 * whc + smp : whc) + ((z.nr[0x2F] & 3) << 8 | z.nr[0x30]);
    const int ax = (xs % m + m) % m;                                  // the hardware's corrections (tilemap:120-127)
    const int ay = (wvc + z.nr[0x31]) & 0xFF;
    const int idx = (ay >> 3) * (wide ? 80 : 40) + (ax >> 3);
    const bool mb7 = z.nr[0x6E] & 0x80, tb7 = z.nr[0x6F] & 0x80;
    const int mpg = z.nr[0x6E] & 0x3F, tpg = z.nr[0x6F] & 0x3F;
    const uint8_t tile = tm_byte(z, mb7, mpg, strip ? idx : 2 * idx);
    const uint8_t attr = strip ? z.nr[0x6C] : tm_byte(z, mb7, mpg, 2 * idx + 1);
    below = ((attr & 1) || t512) && !(ctl & 1);                       // (tilemap:388: tm_on_top clears it)
    if (whc < 0 || whc >= 320 || wvc < 0 || wvc >= 256 || whc < c[0] * 2 || whc > c[1] * 2 + 1 || wvc < c[2] || wvc > c[3])
        return false;
    const int t9 = tile | ((t512 && (attr & 1)) ? 0x100 : 0);
    uint8_t px;
    bool shown;
    if (text) {                                                       // 1 bit a pixel, 7-bit offset (tilemap:228)
        const uint8_t b = tm_byte(z, tb7, tpg, t9 * 8 + (ay & 7));
        px = (attr & 0xFE) | ((b << (ax & 7)) >> 7 & 1);
        shown = true;
    } else {
        const bool rot = attr & 2;
        const int ex = ((attr >> 3) ^ (attr >> 1)) & 1 ? ~ax & 7 : ax & 7, ey = (attr & 4) ? ~ay & 7 : ay & 7;
        const int tx = rot ? ey : ex, ty = rot ? ex : ey;             // (tilemap:139-143)
        const uint8_t b = tm_byte(z, tb7, tpg, t9 * 32 + ty * 4 + (tx >> 1));
        const uint8_t nib = (tx & 1) ? b & 15 : b >> 4;
        px = (attr & 0xF0) | nib;
        shown = nib != (z.nr[0x4C] & 15);                             // the transparent index (tilemap:260)
    }
    if (!shown) return false;
    rgb = z.pal[0][1 << 9 | ((ctl >> 4) & 1) << 8 | px] & 0x1FF;
    return true;
}

// ---- sprites (video/sprites.vhd:516-559, 750-995): two line buffers. At each line's whc = 511 they swap (the edge
// detect, line_reset_re, three master ticks after that 7 MHz edge): the display reads the one just rendered, and the
// renderer starts wide line wvc + 1 in the other, cleared as it was displayed (1004-1027). It runs on the master
// clock: S_START, a QUALIFY cycle per sprite, which reads its attributes then (the attribute RAMs' asynchronous
// port, 327-470), and for a sprite it draws 16 << xscale PROCESS cycles, a pixel each. The next swap cuts it off;
// if it wasn't idle, that's overtime (status b1, 977, 990). It runs lazily: spr_catch_up brings it to now before
// anything it reads changes and before the status is read; spr_swap runs at the swap's tick.
enum { SP_IDLE, SP_START, SP_QUALIFY, SP_PROCESS };

// QUALIFY: sprite i as the renderer sees it now (750-840), latched for PROCESS (902-928); an anchor sets the anchor
// registers (929-950). Returns whether it's drawn on the line being rendered.
bool spr_qualify(ZXN& z, int i) {
    const uint8_t* a = z.spr_attr[i];
    const bool e5 = a[3] & 0x40, rel = e5 && (a[4] & 0xC0) == 0x40;
    uint8_t c0 = a[0], c1 = a[1], c2 = a[2], c3 = a[3], c4 = a[4];
    if (rel) {                                                        // relative to the last anchor (758-792)
        const int x0 = (int8_t)(z.sa_rot ? a[1] : a[0]), y0 = (int8_t)(z.sa_rot ? a[0] : a[1]);
        const int x1 = (z.sa_rot ^ z.sa_xm) ? -x0 : x0, y1 = z.sa_ym ? -y0 : y0;
        const int x3 = (z.sa_x + ((x1 * (1 << z.sa_xs)) & 0x1FF)) & 0x1FF, y3 = (z.sa_y + ((y1 * (1 << z.sa_ys)) & 0x1FF)) & 0x1FF;
        const int pal = (a[2] & 1) ? (z.sa_pal + (a[2] >> 4)) & 15 : a[2] >> 4;
        const bool xm = z.sa_rot ? ((a[2] >> 2) ^ (a[2] >> 1)) & 1 : (a[2] >> 3) & 1;
        const bool ym = z.sa_rot ? ((a[2] >> 3) ^ (a[2] >> 1)) & 1 : (a[2] >> 2) & 1;
        c0 = x3 & 0xFF; c1 = y3 & 0xFF;
        c2 = pal << 4 | (z.sa_rt ? (z.sa_xm ^ xm) << 3 | (z.sa_ym ^ ym) << 2 | (z.sa_rot ^ ((a[2] >> 1) & 1)) << 1 : a[2] & 0x0E) | (x3 >> 8);
        c3 = (z.sa_vis && (a[3] & 0x80)) << 7 | 0x40 | (a[3] & 0x3F);
        c4 = z.sa_h << 7 | (a[4] & 0x20) << 1 | (z.sa_rt ? z.sa_xs << 3 | z.sa_ys << 1 : a[4] & 0x1E) | (y3 >> 8);
    }
    const int cy = (e5 ? (c4 & 1) : 0) << 8 | c1, cx = (c2 & 1) << 8 | c0;
    const bool h4 = (c4 & 0x80) && e5, n6 = (c4 & 0x40) && h4;
    int pat = (a[3] & 0x3F) << 1 | n6;                                // spr_rel_pattern: N5:N0, N6 (803-804)
    if (rel && (a[4] & 1)) pat = (pat + z.sa_pat) & 0x7F;
    const int xs = e5 ? (c4 >> 3) & 3 : 0, ys = e5 ? (c4 >> 1) & 3 : 0;
    int yo = (z.spr_vcount - cy) & 0x1FF;                             // 9-bit, scaled down by the Y scale (806-811)
    if (yo & 0x100) yo |= ~0x1FF;
    yo >>= ys;
    const int yi = (c2 & 4) ? 15 - (yo & 15) : yo & 15;
    const bool rot = c2 & 2, xme = ((c2 >> 3) ^ (c2 >> 1)) & 1;
    z.sc_hcount = cx;
    z.sc_addr = (pat >> 1) << 8 | (rot ? (xme ? 15 : 0) << 4 | yi : yi << 4 | (xme ? 15 : 0));
    z.sc_delta = xme ? (rot ? -16 : -1) : (rot ? 16 : 1);
    z.sc_wc = 0;
    z.sc_wd = 8 >> xs;                                                // 16 << xscale cycles
    z.sc_wrap = (0x1F << xs) & 0x1F;                                  // x wrap-around's mask (919-926)
    z.sc_pal = c2 >> 4;
    z.sc_h4 = h4;
    z.sc_half = pat & 1;                                              // the 4-bit half: the sum's N6 (928)
    if (!rel) {                                                       // an anchor (929-950)
        const bool u = e5 && (a[4] & 0x20);
        z.sa_rt = u; z.sa_h = h4; z.sa_vis = a[3] & 0x80;
        z.sa_x = cx; z.sa_y = cy; z.sa_pat = pat; z.sa_pal = a[2] >> 4;
        z.sa_rot = u && (a[2] & 2); z.sa_xm = u && (a[2] & 8); z.sa_ym = u && (a[2] & 4);
        z.sa_xs = u ? (a[4] >> 3) & 3 : 0; z.sa_ys = u ? (a[4] >> 1) & 3 : 0;
    }
    return (c3 & 0x80) && yo >= 0 && yo <= 15;                        // spr_cur_draw_it (842)
}
// PROCESS: one pixel (953-972): written where it's on the line and not the transparent index; a pixel already there
// is a collision, and with zero on top (NR 0x15 b6) it stays
void spr_process(ZXN& z) {
    const int hx = z.sc_hcount;
    if (hx < 320) {
        uint8_t idx;
        bool t;
        if (z.sc_h4) {
            const uint8_t b = z.spr_pat[((z.sc_addr & 0x3F00) | z.sc_half << 7 | (z.sc_addr & 0xFF) >> 1) & 0x3FFF];
            const uint8_t nib = (z.sc_addr & 1) ? b & 15 : b >> 4;
            idx = z.sc_pal << 4 | nib; t = nib == (z.nr[0x4B] & 15);
        } else {
            const uint8_t b = z.spr_pat[z.sc_addr & 0x3FFF];
            idx = (((b >> 4) + z.sc_pal) & 15) << 4 | (b & 15); t = b == z.nr[0x4B];
        }
        uint16_t& px = z.spr_buf[z.spr_disp ^ 1][hx];
        if (!t) {
            if (px & 0x100) z.spr_status |= 1;                        // collision (991)
            if (!((z.nr[0x15] & 0x40) && (px & 0x100))) px = 0x100 | idx;
        }
    }
    const int nc = z.sc_wc + z.sc_wd;
    if ((nc ^ z.sc_wc) & 8) z.sc_addr += z.sc_delta;
    z.sc_wc = nc;
    z.sc_hcount = (hx + 1) & 0x1FF;
}
// one master cycle: the data registers on the falling edge, then the state on the next rising one (826-866, 872-959)
void spr_cycle(ZXN& z) {
    switch (z.spr_state) {
        case SP_START:
            z.spr_idx = 0;
            z.sa_vis = false;
            z.spr_state = SP_QUALIFY;
            break;
        case SP_QUALIFY: {
            const bool draw = spr_qualify(z, z.spr_idx);
            z.spr_idx = (z.spr_idx + 1) & 0x7F;
            z.spr_state = draw ? SP_PROCESS : z.spr_idx == 0 ? SP_IDLE : SP_QUALIFY;
            break;
        }
        case SP_PROCESS:
            spr_process(z);
            if ((z.sc_wc & 0x80) || (z.sc_hcount >= 320 && ((z.sc_hcount >> 4) & z.sc_wrap) != z.sc_wrap))
                z.spr_state = z.spr_idx == 0 ? SP_IDLE : SP_QUALIFY;  // done, or off the line for good (855)
            break;
        default: break;
    }
}
void spr_catch_up_to(ZXN& z, uint64_t t) {
    while (z.spr_t < t && z.spr_state != SP_IDLE) { spr_cycle(z); z.spr_t++; }
    if (z.spr_t < t) z.spr_t = t;
}
void spr_catch_up(ZXN& z) { spr_catch_up_to(z, z.t28); }
// line_reset_re = "01" in the tick before this one: overtime if the renderer wasn't idle then (that tick's cycle
// still runs), then the swap and S_START for wide line wvc + 1 (wvc: -2 at c_min_vactive - 34, ulat:494-507)
void spr_swap(ZXN& z) {
    spr_catch_up_to(z, z.t28 - 1);
    if (z.spr_state != SP_IDLE) z.spr_status |= 2;                    // sprites_overtime (977, 990)
    spr_catch_up_to(z, z.t28);
    z.spr_disp ^= 1;
    for (auto& p : z.spr_buf[z.spr_disp ^ 1]) p = 0;
    const Timing& t = T(z);
    const int d = ((z.vc - (t.vactive - 34)) % t.vc_len + t.vc_len) % t.vc_len;
    z.spr_vcount = (d - 2 + 1) & 0x1FF;
    z.spr_state = SP_START;
    z.spr_swap_at = 0;
}
// the sprite pixel at paper (x, y) (sprites.vhd:1000-1068): sprites on (NR 0x15 b0), inside the clip window
bool spr_pixel(ZXN& z, int x, int y, uint16_t& rgb) {
    if (!(z.nr[0x15] & 1)) return false;
    const int whc = x + 32, wvc = y + 32;
    if (whc < 0 || whc >= 320 || wvc < 0 || wvc >= 256) return false;
    const uint16_t p = z.spr_buf[z.spr_disp][whc];
    if (!(p & 0x100)) return false;
    const uint8_t* c = z.clip[1];
    int xs, xe, ys, ye;
    if (z.nr[0x15] & 2) {                                             // over the border
        if (z.nr[0x15] & 0x20) { xs = c[0] * 2; xe = c[1] * 2 + 1; ys = c[2]; ye = c[3]; }
        else { xs = 0; xe = 319; ys = 0; ye = 255; }
    } else { xs = c[0] + 32; xe = c[1] + 32; ys = c[2] + 32; ye = c[3] + 32; if (wvc >= 224) return false; }
    if (whc < xs || whc > xe || wvc < ys || wvc > ye) return false;
    rgb = z.pal[1][1 << 9 | ((z.nr[0x43] >> 3) & 1) << 8 | (p & 0xFF)] & 0x1FF;
    return true;
}

// ---- the ULA screen, drawn at the beam (ref §2.5): pixel 0 of a line is hc_ula = 0x0C; the 256 x 192 area from
// bank 5's block RAM (bank 7's with the shadow screen); the border from port 0xFE; FLASH every 16 frames, counted at
// ULA position 0,0. APPROXIMATION: memory is read when the pixel is shown, not at its fetch slot 12 pixels earlier, so
// a change inside that gap shows a pixel early (the shift-register model: later).
inline void draw_pixel(ZXN& z) {
    const int h = hc_ula(z), v = vc_ula(z);
    if (h == 0 && v == 0 && ++z.flash_count == 16) { z.flash_count = 0; z.flash_on = !z.flash_on; }
    const Timing& t = T(z);
    int x = h - 12, y = v;
    if (x >= 256 + FB_BORDER) {                                       // the left border wraps round from the line end:
        x -= t.hc_len;                                                // it's the next scanline's, before vc_ula steps
        y++;                                                          // at hc_ula 0 (Hatch Fern's PV1 finding)
    }
    if (y >= 192 + FB_BORDER) y -= t.vc_len;
    const int fx = x + FB_BORDER, fy = y + FB_BORDER;
    if (fx < 0 || fx >= FB_W || fy < 0 || fy >= FB_H) return;
    uint8_t c = z.border;
    const bool next = z.nr[0x43] & 1, ulap = z.ulap_en && !next;     // ULANext wins over ULA+ (zxula:492-531)
    const bool border = !(x >= 0 && x < 256 && y >= 0 && y < 192);
    // the Timex modes (port 0xFF b2:0; none with the shadow screen, zxula:191): b0 the display file at 2000h, b1 the
    // attributes from the second file's pixel area (hi-colour), b2 hi-res, 16 pixels a cell at 14 MHz in port 0xFF
    // b5:3's ink on its inverse, BRIGHT, with the border in that paper too (zxula:220-256, 386-447)
    const int mode = (z.port7ffd & 8) ? 0 : z.portff & 7;
    const bool hires = mode & 4;
    const uint8_t tmx = 0x40 | (~(z.portff >> 3) & 7) << 3 | ((z.portff >> 3) & 7);   // border_clr_tmx (zxula:419)
    uint8_t attr2[2];
    attr2[0] = attr2[1] = hires ? tmx : (z.border << 3) | z.border;   // border_clr: "00" & border & border (zxula:417)
    bool on[2] = {false, false};
    if (!border) {
        // the ULA's scroll (zxula:189-216): NR 0x27 wraps within the 192 lines; NR 0x26 and NR 0x68 b2's half pixel
        // move the content left in half pixels, each pixel keeping its own cell's attribute
        const int ys = y + z.nr[0x27];
        const int cy = ys >= 384 ? ys - 384 : ys >= 192 ? ys - 192 : ys;
        const uint8_t* scr = (z.port7ffd & 8) ? z.bram7 : z.bram5;
        for (int smp = 0; smp < 2; smp++) {
            const int half = (2 * x + smp + 2 * z.nr[0x26] + ((z.nr[0x68] >> 2) & 1)) & 511;
            const int cx = half >> 1;
            const int pa = ((cy & 0xC0) << 5) | ((cy & 7) << 8) | ((cy & 0x38) << 2) | (cx >> 3);
            const uint8_t bits = scr[(mode & 1) << 13 | pa];
            const uint8_t second = scr[(mode & 2) ? 0x2000 | pa : (mode & 1) << 13 | (0x1800 + (cy >> 3) * 32 + (cx >> 3))];
            if (hires) {                                              // pixel byte's 8, then the second byte's 8
                const int sub = half & 15;
                on[smp] = sub < 8 ? (bits >> (7 - sub)) & 1 : (second >> (15 - sub)) & 1;
            } else {
                attr2[smp] = second;
                on[smp] = (bits >> (7 - (cx & 7))) & 1;
                if ((second & 0x80) && z.flash_on && !next && !ulap) on[smp] = !on[smp];   // no FLASH for ULANext/ULA+
            }
        }
        const uint8_t a = attr2[0];
        c = (on[0] ? (a & 7) : ((a >> 3) & 7)) | ((a & 0x40) ? 8 : 0);
    }
    z.fb[fy * FB_W + fx] = c;
    // the ULA's palette index per 14 MHz sample (zxula:484-560): standard 000 & paper & BRIGHT & colour; ULA+ 11 &
    // attr7:6 & paper (always, in hi-res) & colour; ULANext the ink masked by NR 0x42, the paper above it from 128,
    // format FF's paper and border the fallback
    uint8_t idx2[2];
    bool bgnd2[2] = {false, false};
    for (int smp = 0; smp < 2; smp++) {
        const bool o = on[smp];
        const uint8_t attr = attr2[smp];
        uint8_t& idx = idx2[smp];
        if (next) {
            const uint8_t f = z.nr[0x42];
            if (border) { idx = 0x80 | ((attr >> 3) & 7); bgnd2[smp] = f == 0xFF; }
            else if (o) idx = attr & f;
            else switch (f) {
                case 0x01: idx = 0x80 | attr >> 1; break;
                case 0x03: idx = 0x80 | attr >> 2; break;              // paper_base_index & the attribute's upper
                case 0x07: idx = 0x80 | attr >> 3; break;              // bits: 80h up, for every format (zxula:486,
                case 0x0F: idx = 0x80 | attr >> 4; break;              // 516-525)
                case 0x1F: idx = 0x80 | attr >> 5; break;
                case 0x3F: idx = 0x80 | attr >> 6; break;
                case 0x7F: idx = 0x80 | attr >> 7; break;
                default: idx = 0; bgnd2[smp] = true;
            }
        } else if (ulap) {
            idx = 0xC0 | (attr & 0xC0) >> 2 | ((hires || !o) ? 8 : 0) | (o ? attr & 7 : (attr >> 3) & 7);
        } else {
            idx = (o ? 0 : 0x10) | (attr & 0x40) >> 3 | (o ? attr & 7 : (attr >> 3) & 7);
        }
    }
    uint8_t idx = idx2[0];
    bool bgnd = bgnd2[0], lores = false;
    // LoRes (NR 0x15 b7) replaces the ULA's pixel inside the ULA's clip window (lores.vhd; zxnext:6831-6840): 128 x 96
    // from bank 5 (rows 0-47 at 0000, 48-95 at 2000), or Radastan's 4-bit pixels from a Timex display file (NR 0x6A
    // b5), scrolled by NR 0x32/0x33, through the ULA's palette
    if (z.nr[0x15] & 0x80) {
        const uint8_t* lc = z.clip[2];
        const int vc = y < 0 ? y + t.vc_len : y;
        if (x >= 0 && x < 256 && x >= lc[0] && x <= lc[1] && vc >= lc[2] && vc <= lc[3]) {
            const int x8 = (x + z.nr[0x32]) & 0xFF, yp = vc + z.nr[0x33];
            const int y8 = yp >= 192 ? (yp + 64) & 0xFF : yp & 0xFF;
            const int off = z.nr[0x6A] & 15;
            if (z.nr[0x6A] & 0x20) {                                  // Radastan (lores:62-68)
                const int dfile = (z.portff & 1) ^ ((z.nr[0x6A] >> 4) & 1);
                const uint8_t d = z.bram5[(dfile << 13 | (y8 >> 1) << 6 | x8 >> 2) & 0x3FFF];
                const int hi = (z.ulap_en && !(z.nr[0x43] & 1)) ? (0xC | (off & 3)) : off;
                idx = hi << 4 | ((x8 & 2) ? d & 15 : d >> 4);
            } else {
                const int a = ((y8 >> 1) << 7 | x8 >> 1) + (y8 >= 96 ? 0x800 : 0);
                const uint8_t d = z.bram5[a & 0x3FFF];
                idx = (((d >> 4) + off) & 15) << 4 | (d & 15);
            }
            bgnd = false;
            lores = true;
        }
    }
    uint16_t urgb2[2];
    for (int smp = 0; smp < 2; smp++) {
        const uint8_t i = lores ? idx : idx2[smp];
        const bool b = lores ? bgnd : bgnd2[smp];
        urgb2[smp] = b ? rgb9(z.nr[0x4A]) : z.pal[0][((z.nr[0x43] >> 1) & 1) << 8 | i] & 0x1FF;
    }
    // the compositor (zxnext:7000-7180). The ULA is transparent where its colour's bits 8:1 match NR 0x14, outside its
    // clip window (NR 0x1A; never in the border), or when it's off (NR 0x68 b7); Layer 2 where it doesn't show or
    // matches NR 0x14; its priority bit lifts it over everything except in L S U and L U S. Sprites where no sprite
    // pixel shows (sprite_transparent = not pixel_en; no colour test, zxnext:7025-7026). In the U-over-S orders a
    // border pixel of the ULA gives way to a sprite where the tilemap is transparent (7163, 7173, 7185).
    // The blend modes add Layer 2 to a mix colour chosen by NR 0x68 b6:5 (00 the ULA's colour even if it's off,
    // 10 the ULA as shown, 01/11 none: the ULA then sits below), 110 saturating at 7, 111 then less 5 (zxnext:7032-7250).
    const uint8_t* uc = z.clip[2];
    const bool uclip = !border && (x < uc[0] || x > uc[1] || y < uc[2] || y > uc[3]);
    const uint16_t fb9 = rgb9(z.nr[0x4A]);
    const int order = (z.nr[0x15] >> 2) & 7;
    // blanking (zxula_timing.vhd:150-240; the mixer forces black, zxnext:7311-7315): raw hc 0-95 (Pentagon 0-63) and
    // raw vc 0-7 (Pentagon 0-15), with the paper at raw (hactive, vactive)
    const bool pent = z.timing == 4;
    const int rawh = x + t.hactive, rawv = ((y + t.vactive) % t.vc_len + t.vc_len) % t.vc_len;
    const bool blank = rawh <= (pent ? 63 : 95) || rawv <= (pent ? 15 : 7);
    uint16_t srgb = 0;
    const bool st = !spr_pixel(z, x, y, srgb);                        // 7 MHz: the same for both samples
    for (int smp = 0; smp < 2; smp++) {
        const uint16_t ur = urgb2[smp];
        const bool ul_t = (ur >> 1) == z.nr[0x14] || uclip || (z.nr[0x68] & 0x80);   // ula_transparent
        // the tilemap with the ULA (zxnext:7011-7030): over it unless the tile is below and the ULA shows; or with
        // NR 0x68 b0's stencil, the two ANDed where both show
        uint16_t trgb = 0;
        bool below = false, text = false;
        const bool tt = !tm_pixel(z, x, y, smp, trgb, below, text) || (text && (trgb >> 1) == z.nr[0x14]);
        uint16_t urgb;
        bool ut;
        if ((z.nr[0x68] & 1) && !(z.nr[0x68] & 0x80) && (z.nr[0x6B] & 0x80)) {
            ut = ul_t || tt;
            urgb = ut ? 0 : ur & trgb;
        } else {
            ut = ul_t && tt;
            urgb = (!tt && (!below || ul_t)) ? trgb : ur;
        }
        uint16_t lrgb = 0;
        bool lp = false;
        const bool lt = !l2_pixel(z, x, y, smp, lrgb, lp) || (lrgb >> 1) == z.nr[0x14];
        if (lt) lp = false;
        uint16_t out;
        const bool uo = !ut && !(border && tt && !st);                // the ULA over S (7163, 7173, 7185)
        switch (order) {
            case 1: out = !lt ? lrgb : !st ? srgb : !ut ? urgb : fb9; break;                  // L S U (7137-7145)
            case 2: out = lp ? lrgb : !st ? srgb : !ut ? urgb : !lt ? lrgb : fb9; break;      // S U L (7147-7157)
            case 3: out = !lt ? lrgb : uo ? urgb : !st ? srgb : fb9; break;                   // L U S (7159-7167)
            case 4: out = lp ? lrgb : uo ? urgb : !st ? srgb : !lt ? lrgb : fb9; break;       // U S L (7169-7179)
            case 5: out = lp ? lrgb : uo ? urgb : !lt ? lrgb : !st ? srgb : fb9; break;       // U L S (7181-7191)
            case 6: case 7: {
                const int bm = (z.nr[0x68] >> 5) & 3;
                const bool umt = (ur >> 1) == z.nr[0x14] || uclip;   // ula_mix_transparent: not the ULA's enable
                bool mt = true, topt = true, bt = true;
                uint16_t mix = 0, top = 0, bot = 0;
                switch (bm) {                                         // mix, top and bottom layers (zxnext:7032-7068)
                    case 0:
                        if (!umt) { mix = ur; mt = false; }
                        if (!tt && !below) { top = trgb; topt = false; }
                        if (!tt && below) { bot = trgb; bt = false; }
                        break;
                    case 2:
                        if (!ut) { mix = urgb; mt = false; }
                        break;
                    case 3:
                        if (!tt) { mix = trgb; mt = false; }
                        if (!ul_t && below) { top = ur; topt = false; }
                        if (!ul_t && !below) { bot = ur; bt = false; }
                        break;
                    default:
                        if (below) { if (!ul_t) { top = ur; topt = false; } if (!tt) { bot = trgb; bt = false; } }
                        else { if (!tt) { top = trgb; topt = false; } if (!ul_t) { bot = ur; bt = false; } }
                }
                const int lr = lt ? 0 : lrgb;
                int ch[3];
                for (int i = 0; i < 3; i++) {
                    int v = ((lr >> (6 - 3 * i)) & 7) + ((mix >> (6 - 3 * i)) & 7);
                    if (order == 6) v = v > 7 ? 7 : v;
                    else if (!mt) v = v <= 4 ? 0 : v >= 12 ? 7 : v - 5;
                    ch[i] = v;
                }
                const uint16_t mixer = ch[0] << 6 | ch[1] << 3 | ch[2];
                out = lp ? mixer : !topt ? top : !st ? srgb : !bt ? bot : !lt ? mixer : fb9;   // (7207-7217, 7249-7259)
                break;
            }
            default:                                                  // S L U (7125-7135)
                out = lp ? lrgb : !st ? srgb : !lt ? lrgb : !ut ? urgb : fb9;
        }
        z.f9raw[fy * F9_W + 2 * fx + smp] = out;
        z.f9[fy * F9_W + 2 * fx + smp] = blank ? 0 : out;
    }
}

// ---- the clock

// One rising edge of the CPU clock. Returns false (and changes nothing) if a run_until_pc stop is due: the CPU is
// about to begin T1 of an instruction's first opcode fetch at an address in the range (DESIGN.md §9.1 (5)).
// ---- NMIs (zxnext:2046-2129) and the multiface (multiface.vhd). The multiface's ports by NR 0x0A b7:6: 00 MF+3
// enable 3F / disable BF, 01 and 10 MF128 BF / 3F, 11 (and b7 set) MF1 9F / 1F (zxnext:2571-2572).
inline int mf_type(const ZXN& z) { return z.nr[0x0A] >> 6; }
inline bool mf_en(const ZXN& z) { return (z.nr[0x83] >> 1) & 1; }   // port enable bit 9: off holds it in reset
inline bool mf_is_active(const ZXN& z) { return z.mf_enable || z.mf_fetch66 || z.mf_active; }
inline bool mf_mapped(const ZXN& z) { return mf_en(z) && (z.mf_enable || z.mf_fetch66); }
inline bool dm_nmi_hold(const ZXN& z) { return dm_automap(z) || z.dm_button; }   // divmmc o_disable_nmi
// a request from a button or NR 0x02 (nmi_assert_*): taken when no NMI is active (zxnext:2049-2074). The multiface
// needs divMMC's conmem off and divMMC not holding; divMMC needs the multiface inactive.
void nmi_request(ZXN& z, bool mf) {
    if (z.config_mode || z.nmi_cause) return;
    if (mf && !(z.porte3 & 0x80) && !dm_nmi_hold(z)) z.nmi_cause = 1;
    else if (!mf && !mf_is_active(z)) z.nmi_cause = 2;
    if (z.nmi_cause == 1 && z.nmi_state == 0 && mf_en(z) && !z.mf_active) {   // the multiface's button (multiface:93-110)
        z.mf_active = true;
        z.mf_invisible = false;
    }
    if (z.nmi_cause == 2 && z.nmi_state == 0 && dm_en(z) && !dm_automap_reset(z)) z.dm_button = true;
}
inline bool nmi_line(const ZXN& z) { return (z.nmi_state == 0 && z.nmi_cause) || z.nmi_state == 1; }   // (2128)
// the state machine, on a rising CPU edge with the pins before it (zxnext:2079-2121)
void nmi_edge(ZXN& z, uint64_t before) {
    if (z.config_mode) { z.nmi_state = 0; z.nmi_cause = 0; return; }
    const bool hold = z.nmi_cause == 1 ? z.mf_active : z.nmi_cause == 2 ? dm_nmi_hold(z) : false;
    switch (z.nmi_state) {
        case 0: if (z.nmi_cause) z.nmi_state = 1; break;
        case 1:
            if ((before & Z80_M1) && (before & Z80_MREQ) && Z80_GET_ADDR(before) == 0x0066) z.nmi_state = 2;
            break;
        case 2: if (!hold) z.nmi_state = 3; break;
        default:
            if (!(before & Z80_WR)) { z.nmi_state = 0; z.nmi_cause = 0; }   // (nmi_mf etc. clear in S_NMI_END)
    }
}
// RETN (ED 45, as the snooper sees it): the multiface pages out and its NMI ends (multiface:85-120)
void mf_retn(ZXN& z) {
    if (z.mf_active || z.mf_enable) { z.mf_active = false; z.mf_enable = false; remap(z); }
}
// the multiface's ports (multiface:69-120; zxnext:4248-4263). Returns true if it answered a read, with *out.
bool mf_io(ZXN& z, uint16_t port, bool wr, uint8_t* out) {
    if (!mf_en(z)) return false;
    const int t = mf_type(z);
    const uint8_t en_p = (t & 2) ? 0x9F : (t & 1) ? 0xBF : 0x3F, dis_p = (t & 2) ? 0x1F : (t & 1) ? 0x3F : 0xBF;
    const uint8_t lo = port & 0xFF;
    if (lo != en_p && lo != dis_p) return false;
    const bool p3 = t == 0, m48 = t == 3, en = lo == en_p;
    const bool was = mf_mapped(z);
    if (wr) {
        z.mf_active = false;                                          // a write to either port ends nmi_active
        if ((!en && !p3) || (en && p3)) z.mf_invisible = true;
        if (mf_mapped(z) != was) remap(z);
        return false;
    }
    bool answered = false;
    if (en) {                                                         // the enable port: reads page it in if visible
        const bool inv = z.mf_invisible && !m48;
        z.mf_enable = !inv;
        if (!inv && !m48) {                                           // mf_port_en: 128 and +3 types read it back
            answered = true;
            if (p3) {
                switch (port >> 12) {
                    case 0x1: *out = z.port1ffd; break;
                    case 0x7: *out = z.port7ffd; break;
                    case 0xD: *out = z.portdffd & 0x5F; break;
                    case 0xE: *out = z.porteff7 & 0x0C; break;
                    default: *out = z.border & 7;
                }
            } else *out = (z.port7ffd & 8) << 4 | 0x7F;
        }
    } else {                                                          // the disable port: reads page it out
        z.mf_enable = false;
        if (p3) z.mf_active = false;
    }
    if (mf_mapped(z) != was) remap(z);
    return answered;
}

// ---- the AYs (turbosound.vhd, ym2149.vhd): register files only, no sound yet. Reset leaves every register 0 but the
// mixer (R7) at 0xFF, register 0 selected and AY 0 chosen (ym2149:166-187; turbosound:80-86).
void ay_reset(ZXN& z) {
    memset(z.ay_reg, 0, sizeof z.ay_reg);
    for (auto& r : z.ay_reg) r[7] = 0xFF;
    memset(z.ay_addr, 0, sizeof z.ay_addr);
    z.ay_sel = 0;
    z.audio.reset_psgs();
}
inline bool ay_held(const ZXN& z) { return (z.nr[0x06] & 3) == 3; }  // NR 0x06 PSG mode 11 holds them in reset (6286)
// 0xFFFD: with TurboSound on (NR 0x08 b1), 1xx111nn picks a chip (nn 10 -> 1, 01 -> 2, else 0); 000rrrrr selects
// a register of the chosen chip (turbosound:80-100)
void ay_select(ZXN& z, uint8_t v) {
    if (ay_held(z)) return;
    if ((z.nr[0x08] & 2) && (v & 0x80) && (v & 0x1C) == 0x1C) {
        z.ay_sel = (v & 3) == 2 ? 1 : (v & 3) == 1 ? 2 : 0;
        z.audio.pan[z.ay_sel] = (v >> 5) & 3;                       // its pan, b6 L b5 R (turbosound:83-89)
    }
    else if (!(v & 0xE0)) z.ay_addr[z.ay_sel] = v & 0x1F;
}
void ay_write(ZXN& z, uint8_t v) {                                    // 0xBFFD (ym2149:183-206)
    if (ay_held(z)) return;
    const int a = z.ay_addr[z.ay_sel];
    if (!(a & 0x10)) z.ay_reg[z.ay_sel][a] = v;
    if (a == 13) z.audio.ym[z.ay_sel].env_reset(v);                  // env_reset (ym2149:205-207)
}
// what the chosen chip reads (ym2149:216-249): its ID and register number for 0xBFF5; 0xFF above 15 in YM mode; in
// AY mode (NR 0x06 b0) the unused bits of the narrow registers read 0; R14/R15 read the I/O ports (pulled up) when
// they're inputs, or the register ANDed with them
uint8_t ay_read(const ZXN& z, bool info) {
    const int c = z.ay_sel, a = z.ay_addr[c];
    if (info) return ((3 - c) << 6) | a;                              // AY_ID & '0' & addr
    const bool ay = z.nr[0x06] & 1;
    if ((a & 0x10) && !ay) return 0xFF;
    const uint8_t* r = z.ay_reg[c];
    static const uint8_t AYMASK[16] = {0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF,
                                       0x1F, 0x1F, 0x1F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF};
    const int k = a & 15;
    if (k == 14) return (r[7] & 0x40) ? r[14] : 0xFF;
    if (k == 15) return (r[7] & 0x80) ? r[15] : 0xFF;
    return ay ? r[k] & AYMASK[k] : r[k];
}

// ---- the joysticks (zxnext:3386-3465): NR 0x05 sets each one's mode, joystick 1 from b3 and b7:6, joystick 2 from
// b1 and b5:4. Port 0x1F answers when either is Kempston 1 (001) or MD 1 (101), 0x37 for Kempston 2 (100) or MD 2
// (110), with bits 5:0 of the joystick, and 7:6 too in MD mode.
inline int joy_mode(const ZXN& z, int j) {
    const uint8_t v = z.nr[0x05];
    return j == 0 ? ((v >> 1) & 4) | (v >> 6) : ((v << 1) & 4) | ((v >> 4) & 3);
}
inline bool joy_port_on(const ZXN& z, int port) {                     // port_1f_hw_en / port_37_hw_en (zxnext:2412-2413)
    for (int j = 0; j < 2; j++) {
        const int m = joy_mode(z, j);
        if (port == 0x1F ? (m == 1 || m == 5) : (m == 4 || m == 6)) return true;
    }
    return false;
}
uint8_t joy_read(const ZXN& z, int port) {
    uint8_t v = 0;
    for (int j = 0; j < 2; j++) {
        const int m = joy_mode(z, j);
        const bool md = port == 0x1F ? m == 5 : m == 6, k = md || (port == 0x1F ? m == 1 : m == 4);
        if (k) v |= z.joy[j] & 0x3F;
        if (md) v |= z.joy[j] & 0xC0;
    }
    return v;
}

// ---- the copper (copper.vhd), one 28 MHz cycle. A WAIT (b15 = 1) waits for cvc = b8:0 and hc_ula >= 8 x b14:9 + 12;
// a MOVE writes b7:0 to nextreg b14:8 (0x00-0x7F; register 0 is a NOP) and costs a second cycle. Mode 01 runs the
// list once from 0, 11 restarts it at each frame's (0, 0), 10 carries on from where it is; a change of mode resets
// the address for 01 and 11. Its writes win the nextreg arbitration and land two cycles after the MOVE
// (zxnext:4650-4676).
void nr_write(ZXN& z, int n, int v);
inline int cvc(const ZXN& z);
inline int hc_ula(const ZXN& z);
void copper_tick(ZXN& z) {
    if (!z.cop_mode && !z.cop_last && !z.cop_dout && !z.cop_dout_d && !z.cop_req) return;
    const bool req = z.cop_req;
    const uint8_t reg = z.cop_reg, val = z.cop_val;
    z.cop_req = false;
    if (z.cop_dout && !z.cop_dout_d) {                                // copper_requester's rising edge
        z.cop_req = true;
        z.cop_reg = (z.cop_data >> 8) & 0x7F;
        z.cop_val = z.cop_data & 0xFF;
    }
    z.cop_dout_d = z.cop_dout;
    if (z.cop_last != z.cop_mode) {
        z.cop_last = z.cop_mode;
        if (z.cop_mode == 1 || z.cop_mode == 3) z.cop_pc = 0;
        z.cop_dout = false;
    } else if (z.cop_mode == 3 && cvc(z) == 0 && hc_ula(z) == 0) {
        z.cop_pc = 0;
        z.cop_dout = false;
    } else if (z.cop_mode) {
        if (z.cop_dout) z.cop_dout = false;
        else {
            const uint16_t ins = z.cop_ram[2 * z.cop_pc] << 8 | z.cop_ram[2 * z.cop_pc + 1];
            if (ins & 0x8000) {
                if (cvc(z) == (ins & 0x1FF) && hc_ula(z) >= ((ins >> 9) & 0x3F) * 8 + 12) z.cop_pc = (z.cop_pc + 1) & 0x3FF;
            } else {
                z.cop_data = ins & 0x7FFF;
                if (ins & 0x7F00) z.cop_dout = true;
                z.cop_pc = (z.cop_pc + 1) & 0x3FF;
            }
        }
    } else z.cop_dout = false;
    if (req) nr_write(z, reg, val);                                   // the arbitrated write (it may reset the machine)
}

// ---- the CTC (ctc_chan.vhd). A write to a channel waiting for a time constant stores it; otherwise bit 0 = 1 is a
// control word (bit 1 resets the channel, bit 2 says a time constant follows) and bit 0 = 0 a vector (unused here).
void ctc_write(ZXN& z, int n, uint8_t v) {
    ZXN::Ctc& c = z.ctc[n];
    if (c.state == 1 || c.state == 4) {                               // iowr_tc (ctc_chan:212-217, 240-247)
        c.tc = v;
        c.state = c.state == 1 ? 2 : 3;
        return;
    }
    if (!(v & 1)) return;                                             // iowr_vc: the Z80 CTC's vector, ignored
    if (((v >> 4) & 1) != ((c.ctrl >> 1) & 1)) c.edge_change = true;  // clk_edge_change (ctc_chan:262)
    if (v & 2) c.state = (v & 4) ? 1 : 0;                             // a software reset (ctc_chan:150-156)
    else if (v & 4) c.state = c.state == 3 ? 4 : (c.state == 0 || c.state == 2) ? 1 : c.state;
    c.ctrl = v >> 3;
    if (c.state == 0) { c.count = c.tc; c.p = 0; }                  // reset_soft loads them every cycle in reset, so
}                                                                 // ctc_tick may skip a channel resting there
// one 28 MHz cycle for every channel (ctc_chan:91-139, 176-185); channel n is triggered by channel n-1's ZC/TO,
// channel 0 by channel 3's (zxnext:4026). A channel's ZC/TO, a cycle late, is interrupt source 3 + n.
void int_raise(ZXN& z, int i, bool unq);
void ctc_tick(ZXN& z) {
    bool busy = false;
    for (const auto& c : z.ctc) busy |= c.state != 0 || c.zc_d || c.trg_d || c.edge_change;
    if (!busy) return;                                                // all four held in reset: nothing moves
    const bool trg[4] = {z.ctc[3].zc_d, z.ctc[0].zc_d, z.ctc[1].zc_d, z.ctc[2].zc_d};
    bool zc[4];
    for (int n = 0; n < 4; n++) {
        ZXN::Ctc& c = z.ctc[n];
        const bool edge = ((c.ctrl & 2) ? (trg[n] && !c.trg_d) : (c.trg_d && !trg[n])) || c.edge_change;
        c.edge_change = false;
        c.trg_d = trg[n];
        const bool soft = c.state != 3 && c.state != 4;               // reset_soft
        const bool pclk = (c.ctrl & 4) ? c.p == 0xFF : (c.p & 15) == 15;
        const bool en = (c.ctrl & 8) ? edge : pclk;                   // counter mode: the trigger; timer: the prescaler
        const uint8_t next = c.count - 1;
        zc[n] = next == 0 && en && !soft;
        c.p = soft ? 0 : c.p + 1;
        if (soft || zc[n]) c.count = c.tc;
        else if (en) c.count = next;
        if (c.state == 2 && !(!(c.ctrl & 8) && (c.ctrl & 1) && !edge)) c.state = 3;   // a timer may wait for a trigger
    }
    for (int n = 0; n < 4; n++) {
        if (zc[n] && !z.ctc[n].zc_d) int_raise(z, 3 + n, false);      // the request's edge (im2p:118-131)
        z.ctc[n].zc_d = zc[n];
    }
}

// ---- the interrupt controller (ref §6; zxnext:1887-1958). Fourteen sources by priority, the number also the vector's
// middle bits: 0 line, 1 UART0 Rx, 2 UART1 Rx, 3-10 CTC 0-7, 11 ULA, 12 UART0 Tx, 13 UART1 Tx.
inline bool hw_im2(const ZXN& z) { return z.nr[0xC0] & 1; }          // NR 0xC0 b0: hardware IM2 mode
inline bool int_en(const ZXN& z, int i) {                             // im2_int_en (zxnext:1908-1909)
    if (i == 0) return z.nr[0x22] & 2;                                // the line interrupt (NR 0x22 b1 / NR 0xC4 b1)
    if (i == 11) return !(z.portff & 0x40);                           // the ULA (port FF b6, NR 0x22 b2, NR 0xC4 b0)
    if (i >= 3 && i <= 10) return i <= 6 && (z.ctc[i - 3].ctrl & 0x10);   // the CTC's control word b7 (ctc_int_en)
    if (i == 1) return z.nr[0xC6] & 0x03;                             // the UARTs (NR 0xC6)
    if (i == 2) return z.nr[0xC6] & 0x30;
    if (i == 12) return z.nr[0xC6] & 0x04;
    return z.nr[0xC6] & 0x40;
}
// A source's request edge (im2p:118-131), or NR 0x20's (unq: the enables don't apply, zxnext:1905-1906). Status is
// always recorded; the pulse fires in pulse mode, and in hardware IM2 mode only for the ULA while the CPU isn't in
// IM 2 (im2p:182-194, EXCEPTION); in hardware IM2 mode the source also becomes pending for the chain.
void int_raise(ZXN& z, int i, bool unq) {
    const bool en = unq || int_en(z, i);
    z.int_status |= 1 << i;
    if (hw_im2(z) && en) z.im2_req |= 1 << i;
    if (en && (!hw_im2(z) || (i == 11 && z.im_mode != 2))) z.int_req = true;
}
inline uint16_t int_status(const ZXN& z) { return z.int_status | z.im2_req; }   // o_int_status (im2p:178)
// the daisy chain's request to the CPU: a requesting device with nothing above it in service, the CPU in IM 2
// (im2d:150)
inline bool im2_int(const ZXN& z) {
    if (!hw_im2(z) || z.im_mode != 2) return false;
    bool iei = true;
    for (int i = 0; i < 14 && iei; i++) {
        const int st = z.im2_state[i];
        if (st == 1) return true;
        iei = st == 0 ? iei : st == 1 ? (iei && z.snoop == 1) : false;
    }
    return false;
}
// what the interrupt acknowledge reads: the acknowledged device's vector, NR 0xC0 b7:5 & number & 0, when the chain
// says so (im2_ieo low), else 0xFF (zxnext:1827-1837, 1958; im2d:155)
uint8_t intack_data(const ZXN& z) {
    if (!hw_im2(z)) return 0xFF;
    bool iei = true;
    for (int i = 0; i < 14; i++) {
        const int st = z.im2_state[i];
        if (st == 1 && iei && z.im_mode == 2) return (z.nr[0xC0] & 0xE0) | (i << 1);
        iei = st == 0 ? iei : st == 1 ? (iei && z.snoop == 1) : false;
    }
    return iei ? 0xFF : (z.nr[0xC0] & 0xE0);
}
// each device's state machine, on a rising CPU edge, from the pins as they were before it (im2_device.vhd:66-104)
void im2_edge(ZXN& z, uint64_t before) {
    const bool reti = z.reti_seen;
    z.reti_seen = false;
    if (!hw_im2(z)) return;
    const bool m1 = before & Z80_M1, iorq = before & Z80_IORQ, im2 = z.im_mode == 2;
    bool iei = true;
    for (int i = 0; i < 14; i++) {
        uint8_t& st = z.im2_state[i];
        const bool ieo = st == 0 ? iei : st == 1 ? (iei && z.snoop == 1) : false;
        switch (st) {
            case 0: if (((z.im2_req >> i) & 1) && !m1) st = 1; break;
            case 1: if (m1 && iorq && iei && im2) st = 2; break;
            case 2: if (!m1) st = 3; break;
            default:
                if (reti && iei && im2) {                             // RETI ends the service (im2d:123-128)
                    st = 0;
                    z.im2_req &= ~(1 << i);
                }
        }
        iei = ieo;
    }
}

// divMMC's entry points for a fetch from address a (zxnext:2805-2867). RST n (0x0000-0x0038): NR 0xB8 bit n enables
// it, NR 0xB9 bit n makes it always (1) or ROM 3 only (0), NR 0xBA bit n instant (1) or delayed (0). NR 0xBB: b7
// 0x3Dxx (instant, ROM 3), b6 the 0x1FF8-0x1FFF exit (delayed), b5:2 the tape traps 0x056A, 0x04D7, 0x0562, 0x04C6
// (delayed, ROM 3), b1/b0 0x0066 instant/delayed (only with a DRIVE-button NMI pending: no button yet).
struct DmEntry { bool on_instant, on_delayed, off_delayed, rom3_instant, rom3_delayed; };
inline DmEntry dm_entry(const ZXN& z, uint16_t a) {
    DmEntry e = {false, false, false, false, false};
    const uint8_t bb = z.nr[0xBB];
    if ((a & 0xFFC7) == 0x0000) {                                     // RST 00-38
        const int n = (a >> 3) & 7;
        const bool ep = (z.nr[0xB8] >> n) & 1, valid = (z.nr[0xB9] >> n) & 1, instant = (z.nr[0xBA] >> n) & 1;
        e.on_instant = ep && valid && instant;
        e.on_delayed = ep && valid && !instant;
        e.rom3_instant = ep && !valid && instant;
        e.rom3_delayed = ep && !valid && !instant;
    }
    if ((a & 0xFFF8) == 0x1FF8 && (bb & 0x40)) e.off_delayed = true;
    if ((a & 0xFF00) == 0x3D00 && (bb & 0x80)) e.rom3_instant = true;
    if (a == 0x0066 && z.dm_button) {                                 // 0x0066 with a DRIVE-button NMI (divmmc:120-121)
        if (bb & 0x02) e.on_instant = true;
        if (bb & 0x01) e.on_delayed = true;
    }
    if ((a == 0x04C6 && (bb & 0x04)) || (a == 0x0562 && (bb & 0x08)) || (a == 0x04D7 && (bb & 0x10)) ||
        (a == 0x056A && (bb & 0x20))) e.rom3_delayed = true;
    return e;
}

// sram_divmmc_automap_rom3_en (zxnext:3097): the fetch is from the ROM branch (slots 0-1 showing neither an MMU page
// nor config mode), and what it reads is ROM 3, the 48K BASIC, or the alternate ROM's 48K half. (Layer 2's read
// map and the expansion bus's ROMCS would exclude it: later.)
inline bool dm_rom3_active(const ZXN& z, uint16_t a) {
    const int s = a >> 13;
    if (s >= 2 || z.mmu[s] < 0xE0 || z.config_mode || z.l2_rd) return false;   // Layer 2's read map excludes it
    const RomSel r = rom_select(z);
    return (z.nr[0x8C] & 0xC0) == 0x80 ? r.alt48 : r.rom3;
}

// An opcode fetch from address a: divMMC's automap decision (divmmc.vhd:107-145). An instant entry maps divMMC in for
// this fetch itself; automap_hold, set during the fetch, becomes automap_held when its MREQ rises, so a delayed
// entry (or exit) takes effect from the next memory cycle.
void dm_fetch(ZXN& z, uint16_t a) {
    if (dm_automap_reset(z)) return;
    const DmEntry e = dm_entry(z, a);
    const bool active = a < 0x4000 && !mf_mapped(z);                  // sram_pre_override(2): slots 0-1, not the multiface
    const bool rom3 = active && dm_rom3_active(z, a);
    z.dm_hold = (active && (e.on_instant || e.on_delayed)) || (rom3 && (e.rom3_instant || e.rom3_delayed)) ||
                (z.dm_held && !(active && e.off_delayed));
    z.dm_pending = true;
    const bool instant = (active && e.on_instant) || (rom3 && e.rom3_instant);
    if (instant != z.dm_instant) {
        z.dm_instant = instant;
        remap(z);
    }
}

// im2_control.vhd's snooper, at each opcode fetch with the byte fetched: RETN (ED 45 only) unmaps divMMC
// (divmmc_retn_seen, zxnext:4052, unless the multiface is active); IM n is remembered for NR 0xC0 (im2c:212-229).
void snoop_fetch(ZXN& z, uint8_t op) {
    switch (z.snoop) {
        case 1:                                                       // after ED
            if (op == 0x45) {                                         // RETN: divMMC unless the multiface is active
                if (!mf_is_active(z) && !dm_automap_reset(z)) {       // (zxnext:4052), and the multiface itself
                    z.dm_hold = z.dm_held = z.dm_instant = z.dm_pending = false;
                    z.dm_button = false;
                    remap(z);
                }
                mf_retn(z);
            }
            if ((op & 0xC7) == 0x46) z.im_mode = ((op & 0x18) == 0x18) ? 2 : ((op & 0x18) == 0x10) ? 1 : 0;
            if (op == 0x4D) z.reti_seen = true;                       // RETI, ED 4D only (im2c:22-38, 233-234)
            z.snoop = 0;
            return;
        case 2:                                                       // after CB: this is its opcode
            z.snoop = 0;
            return;
        case 3:                                                       // after DD/FD
            z.snoop = (op == 0xDD || op == 0xFD) ? 3 : 0;
            return;
        default:
            z.snoop = op == 0xED ? 1 : op == 0xCB ? 2 : (op == 0xDD || op == 0xFD) ? 3 : 0;
    }
}

#include "next_dma_bus.inc"

bool cpu_edge(ZXN& z) {
    z80_t saved = z.cpu;
    uint64_t saved_pins = z.pins;
    const uint64_t bus_before = z.bus_pins;                           // the CPU's pins, or the DMA's
    const DmaBus db_saved = z.db;
    uint64_t p = z.pins;
    const bool p3w = p3_wait_now(z);
    if (z.wait_next || p3w) p |= Z80_WAIT; else p &= ~Z80_WAIT;
    const bool dma_bus = dma_edge(z, bus_before, z.wait_next, p3w);     // the DMA's edge, and BUSRQ/BUSAK
    im2_edge(z, bus_before);
    nmi_edge(z, bus_before);
    if (nmi_line(z)) p |= Z80_NMI; else p &= ~Z80_NMI;
    if (z.int_low || im2_int(z)) p |= Z80_INT; else p &= ~Z80_INT;     // pulse_int_n and im2_int_n (zxnext:1799)
    if (dma_bus) p = dma_pins(z);                                     // the CPU frozen, the bus the DMA's
    else p = z80_tick(&z.cpu, p);
    if (!dma_bus && z.stop_on && !z.first_edge && z80_opdone(&z.cpu)) {
        uint16_t a = Z80_GET_ADDR(p);
        if (a >= z.stop_lo && a <= z.stop_hi) {
            z.cpu = saved;
            z.pins = saved_pins;
            z.db = db_saved;
            z.hit = true;
            z.hit_pc = a;
            return false;
        }
    }
    if (!dma_bus) z.db.mc_end = z80_mcycle_end(&z.cpu);
    z.first_edge = false;
    z.wait_next = false;
    z.cpu_clocks++;
    // The Z80N's side band, acted on as the cycle's T1 begins, before its memory access or any contention decision.
    // NEXTREG writes its register (zxnext:4740-4840 via cpu_requester_0); the read on the pins is a dummy.
    if (p & Z80N_NEXTREG) nr_write(z, Z80N_GET_NR_REG(p), Z80N_GET_NR_VAL(p));
    // The NMI's pushes always land in NR C2h/C3h too; with the stackless NMI (NR C0h bit 3) they're kept out of memory,
    // and the first RETN after the acknowledge pops NR C2h/C3h instead (zxnext:1787, 1809-1811, 2009-2044).
    bool hide = false;
    if ((p & (Z80N_NMIACK_LSB | Z80N_NMIACK_MSB)) && (p & Z80_WR)) {
        z.nr[(p & Z80N_NMIACK_LSB) ? 0xC2 : 0xC3] = Z80_GET_DATA(p);
        hide = z.nr[0xC0] & 8;
    }
    if ((p & (Z80N_RETN_LSB | Z80N_RETN_MSB)) && z.stackless_retn) {
        hide = true;
        Z80_SET_DATA(p, z.nr[(p & Z80N_RETN_LSB) ? 0xC2 : 0xC3]);
    }
    if (!(z.nr[0xC0] & 8)) z.stackless_retn = false;                  // the CPU-clocked flag (zxnext:2031-2042)
    else if (p & Z80N_NMIACK_LSB) z.stackless_retn = true;
    else if (p & Z80N_RETN_MSB) z.stackless_retn = false;
    if (hide) p &= ~Z80_MREQ;                                         // MREQ hidden from the machine
    if (z.dm_pending) {                                               // the fetch's MREQ has risen: held follows hold
        z.dm_pending = false;
        const bool was = dm_automap(z);
        z.dm_held = z.dm_hold;
        if (z.dm_held) z.dm_button = false;                           // (divmmc:113-114)
        z.dm_instant = false;
        if (dm_automap(z) != was) remap(z);
    }
    const bool fetch = (p & Z80_M1) && (p & Z80_MREQ) && (p & Z80_RD);
    if (z.mf_fetch66 && !fetch) { z.mf_fetch66 = false; }             // fetch_66 lasts for its M1 (multiface:113-125)
    if (fetch && Z80_GET_ADDR(p) == 0x0066 && z.mf_active && mf_en(z)) {
        z.mf_fetch66 = true;                                          // the multiface pages in for this fetch, and stays
        z.mf_enable = true;
        remap(z);
    }
    if (fetch) dm_fetch(z, Z80_GET_ADDR(p));
    if (dma_bus) dma_classify(z, p); else classify(z, p);            // (the DMA's: next_dma_bus.inc)
    z.p3_waiting = p3w;
    if (!p3w) z.p3_mem = (p & Z80_MREQ) && (p & (Z80_RD | Z80_WR)) && !(p & Z80_RFSH) && contended_page(z, Z80_GET_ADDR(p));
    if (dma_bus) z.p3_mem = z.p3_waiting = false;                    // the DMA's +3 WAIT is its own
    if (dma_bus) dma_cycle(z, p);                                     // the DMA's bus cycle (next_dma_bus.inc)
    else if (p & Z80_MREQ) {
        uint16_t a = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            Kind k;
            Z80_SET_DATA(p, mem_read(z, a, &k));
            if (z.speed_eff == 3 && (k == K_SRAM || k == K_BRAM5)) z.wait_next = true;   // ref §1.4
            if (fetch) snoop_fetch(z, Z80_GET_DATA(p));
            z.rd_open = !fetch && z.speed_eff < 3;                    // below 28 MHz the memory takes the address at T2
            z.rd_addr = a;
        } else if (p & Z80_WR) {
            z.rd_open = false;
            mem_write(z, a, Z80_GET_DATA(p));
        } else if (z.rd_open) {                                       // the read's T2 (or a refresh, which closes it)
            z.rd_open = false;
            if (!(p & Z80_RFSH) && a != z.rd_addr) Z80_SET_DATA(p, mem_read(z, a));   // LDPIRX: DE's byte (Strobe)
        }
    } else if ((p & Z80_IORQ) && (p & Z80_M1)) {
        z.rd_open = false;
        Z80_SET_DATA(p, intack_data(z));                              // INTACK: 0xFF, or hardware IM2's vector
    } else if ((p & Z80_IORQ) && !(p & Z80_M1)) {
        z.rd_open = false;
        uint16_t port = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            // NR 0x22 b7 through 253Bh: INT as port_253b_dat held it at the falling edge in the T80N's T2, 1.5 clocks
            // after this tick begins, less the CLK_28 register in front of it (master_tick sets it then)
            const int per = z.speed_eff == 0 ? 8 : z.speed_eff == 1 ? 4 : z.speed_eff == 2 ? 2 : 1;   // ticks a CPU clock
            z.in_latch_dt = (3 * per + 1) / 2 - 1;
            uint8_t v = io_read(z, port);
            z.in_latch_dt = -1;
            Z80_SET_DATA(p, v);
            if (z.io_logging) z.io_log.push_back({z.t28, z.cpu_clocks, port, v, 0});
        } else if (p & Z80_WR) {
            uint8_t v = Z80_GET_DATA(p);
            if (z.io_logging) z.io_log.push_back({z.t28, z.cpu_clocks, port, v, 1});
            io_write(z, port, v);
        }
    }
    // the SPI master, clocked by the CPU (ref §1.7): the read register loads one edge after state 15; a transfer
    // begins where port 0xEB's read or write strobe is active and the counter is idle (16) or at its last state (15);
    // a second access sooner starts nothing. The card exchanges the byte at once (sdcard.h works in bytes).
    {
        const int old_state = z.spi_state;
        // miso_dat loads 17 edges after a begin, from ishift_r, which still holds that transfer's bits even if the
        // next one began at state 15 (spi_master:146-169); the card exchanges whole bytes at the begin, so each
        // byte waits here for its load
        while (z.spi_npend && z.spi_pend[0].due <= z.cpu_clocks) {
            z.spi_rx = z.spi_pend[0].byte;
            z.spi_pend[0] = z.spi_pend[1];
            z.spi_npend--;
        }
        if (old_state < 16) z.spi_state = old_state + 1;
        z.spi_last_d = old_state == 15;
        const uint16_t port = Z80_GET_ADDR(p);
        if ((p & Z80_IORQ) && !(p & Z80_M1) && (p & (Z80_RD | Z80_WR)) && (port & 0xFF) == 0xEB && port_en(z, 11) &&
            (old_state == 16 || old_state == 15)) {
            const uint8_t mosi = (p & Z80_WR) ? Z80_GET_DATA(p) : 0xFF;   // a read sends 0xFF
            const uint8_t miso = z.sd.xfer(mosi, !(z.spi_cs & 1));          // card 0 on select bit 0
            if (z.spi_npend < 2) z.spi_pend[z.spi_npend++] = {miso, z.cpu_clocks + 17};
            z.spi_state = 0;
            z.spi_count++;
        }
    }
    // the effective speed follows the programmed one only between bus cycles (ref §1.3)
    // (the VHDL samples MREQ, IORQ and M1 as they were before the edge: the previous T-state's pins, not this one's;
    // Speccy-Zone's review)
    if (!(bus_before & (Z80_MREQ | Z80_IORQ | Z80_M1)) && !db_saved.busak) {   // and the DMA not holding it (5714)
        z.speed_eff = z.speed_prog;
        if (hc_ula(z) & 0x100) z.eff_cd = z.nr[0x08] & 0x40;          // in the line's right half only (zxnext:5729-5731)
    }
    // the INT pulse is counted on rising CPU edges until 32 (48K, +3) or 36 (128K, Pentagon), then released on the
    // falling 28 MHz edge inside this same tick (zxnext:1993-2003): this edge still saw INT low, the next won't
    if (z.int_low && ++z.int_count >= T(z).int_len) {
        z.int_low = false;
        z.int_log.back().end = z.t28 + 1;                             // the first tick that starts with INT high
    }
    if (!dma_bus) z.pins = p;
    z.bus_pins = p;
    return true;
}

// One 28 MHz master tick. Returns false if a stop was due before anything moved.
void spr_swap(ZXN& z);
bool master_tick(ZXN& z) {
    if (z.serial_on) {                                                // stepped while busy, free when idle
        serial_tick(z);
        z.serial_on = z.uart[0].active() || z.uart[1].active();
    }
    if (z.spr_swap_at == z.t28 && z.spr_swap_at) spr_swap(z);       // line_reset_re: the next line's render begins
    if (z.in_latch_at == z.t28 && z.in_latch_at) {                    // the 253Bh register takes INT (cpu_edge's IN)
        z.in_latch_at = 0;
        const uint8_t d = (Z80_GET_DATA(z.pins) & 0x7F) | (z.int_low ? 0x80 : 0);
        Z80_SET_DATA(z.pins, d);                                      // the byte z80.h takes at T3
        if (z.io_logging && !z.io_log.empty() && z.io_log.back().port == 0x253B && !z.io_log.back().write)
            z.io_log.back().value = d;
    }
    const int sc_next = (z.sc + 1) & 3;
    const bool edge7 = sc_next == 0;                                  // the 7 MHz edge: sc from 3 to 0 (ref §1.1)
    bool edge = false;
    switch (z.speed_eff) {
        case 0:                                                       // 3.5 MHz, phase-locked to hc_ula (ref §1.2)
            if (edge7) {
                if ((hc_ula(z) & 1) == 0) { edge = !z.cpu_clk_high; }
                else if (!z.contend) { /* goes low below */ }
            }
            break;
        case 1: edge = edge7; break;
        case 2: edge = sc_next == 0 || sc_next == 2; break;
        default: edge = true;
    }
    if (edge && !cpu_edge(z)) return false;
    copper_tick(z);                                                   // copper.vhd samples hc and cvc as they were before
                                                                      // this edge: after a possible stop, before the beam's step
    if (z.speed_eff == 0 && edge7) {
        if ((hc_ula(z) & 1) == 0) z.cpu_clk_high = true;
        else {
            // o_cpu_contend, decided at this odd slot (48K and 128K timing; +3 pulls WAIT instead: later)
            // (no rising CPU edge comes during a hold, so ioreqtw3_n and mreq23_n keep their values and both terms
            // persist through it; Speccy-Zone's review, from zxnext.vhd:47's i_CLK_CPU)
            z.contend = z.contention && z.timing != 3 && (z.ck_mem || z.ck_port) && wait_s(z);
            if (!z.contend) z.cpu_clk_high = false;
        }
    }
    z.sc = sc_next;
    if (edge7) {
        // the registered INT pulse becomes INT low (ref §2.3)
        if (z.int_req) {
            z.int_req = false;
            if (!z.int_low) {
                // pulse_int_n goes low on the falling 28 MHz edge inside this tick (zxnext:1978-1991), so the first
                // tick that *starts* with INT low is the next one. int_log uses that convention at both ends: the
                // state of INT at the start of each master tick, which is what the CPU samples on its rising edges.
                z.int_low = true;
                z.int_count = 0;
                z.int_log.push_back({z.t28 + 1, 0});
            }
        }
        const Timing& t = T(z);
        if (++z.hc == t.hc_len) {
            z.hc = 0;
            if (++z.vc == t.vc_len) {
                z.vc = 0;
                z.frame++;
                z.timing = z.pend_timing;                             // timing and 50/60 Hz change here (ref §2.6)
                z.hz60 = z.pend_hz60;
            }
        }
        const Timing& t2 = T(z);
        if (hc_ula(z) == 0 && vc_ula(z) == 0) z.cvc_off = z.nr[0x64];   // ula_min_vactive: cvc <= offset (ulat:461-462)
        if (z.hc == t2.int_h && z.vc == t2.int_v && !z.ula_int_disabled) int_raise(z, 11, false);
        if (hc_ula(z) == t2.hc_len - 21) z.spr_swap_at = z.t28 + 3;  // whc = 511 (sprites.vhd:518; see spr_swap)
        // the line interrupt for line N: at hc_ula 255 on cvc line N-1, the last line for N = 0, "before the line is
        // drawn" (ulat:561-583); NR 0x22 b1 enables it, NR 0x22 b0 : NR 0x23 is N (zxnext:5233-5239). In pulse mode
        // it makes the same pulse as the ULA's (zxnext:1900-1955).
        if (z.nr[0x22] & 2) {
            const int n = ((z.nr[0x22] & 1) << 8) | z.nr[0x23];
            if (hc_ula(z) == 255 && cvc(z) == (n == 0 ? t2.vc_len - 1 : n - 1)) int_raise(z, 0, false);
        }
        draw_pixel(z);
    }
    ctc_tick(z);
    if ((z.t28 & 15) == 0 && z.t28) {                                 // the 1.75 MHz enable (zxnext_top:1161-1180)
        if (!(z.nr[0x08] & 8)) memset(z.audio.dac, 0x80, 4);          // held in reset while off (zxnext:6343)
        z.audio.tick(z.ay_reg, z.ay_sel, z.nr[0x06], z.nr[0x08], z.nr[0x09], ay_held(z));
    }
    z.t28++;
    return true;
}

}  // namespace

extern "C" {

ZXN* zxn_new(int timing, int hz60, int speed, int issue) {
    ZXN* z = new ZXN();
    z->sram = (uint8_t*)calloc(SRAM_SIZE, 1);
    memset(z->bram5, 0, sizeof z->bram5);
    memset(z->bram7, 0, sizeof z->bram7);
    memset(z->bootrom, 0xFF, sizeof z->bootrom);                     // bare: the boot ROM's area reads 0xFF (§9.1 (2))
    memset(z->nr, 0, sizeof z->nr);
    z->issue = issue == 2 ? 2 : 4;
    do_reset(*z, true);
    // the timing, rate and speed asked for, in effect from the start (§9.1 (1)); still config mode, boot ROM on
    if (timing >= 1 && timing <= 4) z->timing = z->pend_timing = timing;
    z->hz60 = z->pend_hz60 = (z->timing == 4) ? 0 : (hz60 ? 1 : 0);
    z->nr[0x05] = (z->nr[0x05] & ~4) | (z->hz60 << 2);
    z->speed_prog = z->speed_eff = speed & 3;
    return z;
}

void zxn_free(ZXN* z) { free(z->sram); delete z; }
void zxn_contention(ZXN* z, int on) { z->contention = on != 0; }
void zxn_reset(ZXN* z, int hard) { do_reset(*z, hard != 0); }
void zxn_set_bootrom(ZXN* z, const uint8_t* data, int n) {
    memset(z->bootrom, 0xFF, sizeof z->bootrom);
    memcpy(z->bootrom, data, n < BOOTROM_SIZE ? n : BOOTROM_SIZE);
}

uint64_t zxn_t28(ZXN* z) { return z->t28; }
// the sound (next_audio.h): capture every enable's (L, R); resampled audio at a rate; the levels now
void zxn_audio_capture(ZXN* z, int on) { z->audio.capturing = on; if (!on) {} }
int zxn_audio_take(ZXN* z, uint16_t* out, int max) {
    const int n = (int)std::min<size_t>(z->audio.cap.size(), (size_t)max);
    memcpy(out, z->audio.cap.data(), n * sizeof(uint16_t));
    z->audio.cap.erase(z->audio.cap.begin(), z->audio.cap.begin() + n);
    return n;
}
int zxn_audio_cap_len(ZXN* z) { return (int)z->audio.cap.size(); }
void zxn_audio_rate(ZXN* z, int rate) {
    if (rate != z->audio.rate) { z->audio.rate = rate; z->audio.acc = 0; z->audio.sumL = z->audio.sumR = z->audio.nsum = 0; }
}
int zxn_audio_out_len(ZXN* z) { return (int)z->audio.outbuf.size(); }
int zxn_audio_out(ZXN* z, int16_t* out, int max) {
    const int n = (int)std::min<size_t>(z->audio.outbuf.size(), (size_t)max);
    memcpy(out, z->audio.outbuf.data(), n * sizeof(int16_t));
    z->audio.outbuf.erase(z->audio.outbuf.begin(), z->audio.outbuf.begin() + n);
    return n;
}
void zxn_audio_level(ZXN* z, int* out) { out[0] = z->audio.L; out[1] = z->audio.R; }
void zxn_ay_chan(ZXN* z, int c, int* out) { z->audio.ym[c].out(z->nr[0x06] & 1, out); }
int zxn_ay_env(ZXN* z, int c) { return z->audio.ym[c].evol; }
uint64_t zxn_cpu_clocks(ZXN* z) { return z->cpu_clocks; }
uint64_t zxn_frame(ZXN* z) { return z->frame; }
int zxn_hc_ula(ZXN* z) { return hc_ula(*z); }
int zxn_vc_ula(ZXN* z) { return vc_ula(*z); }
int zxn_hc(ZXN* z) { return z->hc; }
int zxn_vc(ZXN* z) { return z->vc; }
int zxn_speed(ZXN* z) { return z->speed_eff; }

void zxn_run_ticks(ZXN* z, uint64_t n) {
    z->stop_on = false;
    for (uint64_t i = 0; i < n; i++) master_tick(*z);
}

int zxn_run_until_pc(ZXN* z, int lo, int hi, uint64_t max_ticks) {
    z->stop_on = true;
    z->first_edge = true;
    z->hit = false;
    z->stop_lo = lo;
    z->stop_hi = hi;
    for (uint64_t i = 0; i < max_ticks; i++)
        if (!master_tick(*z)) break;
    z->stop_on = false;
    return z->hit ? 1 : 0;
}

void zxn_run_frames(ZXN* z, int n) {
    z->stop_on = false;
    uint64_t target = z->frame + n;
    while (z->frame < target) master_tick(*z);
}

void zxn_regs(ZXN* z, uint16_t* out) {
    z80_t& c = z->cpu;
    uint16_t v[16] = {c.pc, c.sp, c.af, c.bc, c.de, c.hl, c.ix, c.iy, c.af2, c.bc2, c.de2, c.hl2,
                      (uint16_t)((c.i << 8) | c.r), c.im, c.iff1, c.iff2};
    memcpy(out, v, sizeof v);
}

// which: 0 pc 1 sp 2 af 3 bc 4 de 5 hl 6 ix 7 iy 8 af' 9 bc' 10 de' 11 hl' 12 ir 13 im 14 iff1 15 iff2
void zxn_set_reg(ZXN* z, int which, int v) {
    z80_t& c = z->cpu;
    switch (which) {
        case 0: z->pins = z80_prefetch(&c, (uint16_t)v); break;
        case 1: c.sp = v; break;
        case 2: c.af = v; break;
        case 3: c.bc = v; break;
        case 4: c.de = v; break;
        case 5: c.hl = v; break;
        case 6: c.ix = v; break;
        case 7: c.iy = v; break;
        case 8: c.af2 = v; break;
        case 9: c.bc2 = v; break;
        case 10: c.de2 = v; break;
        case 11: c.hl2 = v; break;
        case 12: c.i = v >> 8; c.r = v & 0xFF; break;
        case 13: c.im = v; break;
        case 14: c.iff1 = v; break;
        case 15: c.iff2 = v; break;
    }
}

// memory through the CPU's current map, with no side effects (DESIGN.md §3, SZ)
int zxn_peek(ZXN* z, int a) {
    int s = (a >> 13) & 7;
    return z->rd[s] ? z->rd[s][a & 0x1FFF] : z->last_sram;
}
void zxn_poke(ZXN* z, int a, int v, int force) {
    int s = (a >> 13) & 7;
    if (z->wr[s]) z->wr[s][a & 0x1FFF] = v;
    else if (force && z->rd[s]) z->rd[s][a & 0x1FFF] = v;             // into what the CPU reads there
}
uint8_t* zxn_sram(ZXN* z) { return z->sram; }
uint8_t* zxn_bram5(ZXN* z) { return z->bram5; }
uint8_t* zxn_bram7(ZXN* z) { return z->bram7; }
int zxn_slot_page(ZXN* z, int i) { return z->mmu[i & 7]; }
// what slot i shows to reads (write = 0) or where a write lands (write = 1): tag (enum Tag) and value
void zxn_slot_desc(ZXN* z, int i, int write, int* out) {
    i &= 7;
    out[0] = write ? z->wr_tag[i] : z->rd_tag[i];
    out[1] = write ? z->wr_val[i] : z->rd_val[i];
}

int zxn_nr_read(ZXN* z, int n) { return nr_read(*z, n & 0xFF); }
void zxn_nr_write(ZXN* z, int n, int v) { nr_write(*z, n & 0xFF, v); }
int zxn_io_in(ZXN* z, int port) { return io_read(*z, port & 0xFFFF); }
void zxn_set_keys(ZXN* z, const uint8_t* rows) { memcpy(z->keys, rows, 8); }
uint8_t* zxn_framebuffer(ZXN* z) { return z->fb; }
int zxn_cvc(ZXN* z) { return cvc(*z); }                          // DESIGN.md §9
void zxn_set_joy(ZXN* z, int left, int right) {
    z->joy[0] = left & 0x7FF; z->joy[1] = right & 0x7FF;
    z->uart[0].wake = z->uart[1].wake = 4;                            // a joystick port may carry a UART
    z->serial_on = true;
}
void zxn_uart_feed(ZXN* z, int n, const uint8_t* data, int len, uint64_t bit_t28, int bits, int parity, int stops) {
    z->uart[n & 1].feed(z->t28, data, len, bit_t28, bits, parity, stops);
    z->serial_on = true;
}
void zxn_uart_feed_levels(ZXN* z, int n, const uint8_t* levels, const uint64_t* ticks, int count) {
    z->uart[n & 1].feed_levels(z->t28, levels, ticks, count);
    z->serial_on = true;
}
void zxn_uart_tx_logging(ZXN* z, int n, int on) {
    nserial::Uart& u = z->uart[n & 1];
    u.tx_logging = on;
    if (!on) u.tx_events.clear();
}
int zxn_uart_tx_log_len(ZXN* z, int n) { return (int)z->uart[n & 1].tx_events.size(); }
void zxn_uart_tx_log_get(ZXN* z, int n, int i, uint64_t* out) {
    out[0] = z->uart[n & 1].tx_events[i].first; out[1] = z->uart[n & 1].tx_events[i].second;
}
int zxn_uart_sent_len(ZXN* z, int n) { return (int)z->uart[n & 1].sent.size(); }
void zxn_uart_sent_get(ZXN* z, int n, int i, uint64_t* out) { out[0] = z->uart[n & 1].sent[i].first; out[1] = z->uart[n & 1].sent[i].second; }
void zxn_uart_sent_clear(ZXN* z, int n) { z->uart[n & 1].sent.clear(); }
void zxn_uart_cts(ZXN* z, int n, int clear) { z->uart[n & 1].host_cts_n = !clear; z->uart[n & 1].wake = 4; z->serial_on = true; }
int zxn_uart_rts(ZXN* z, int n) {                                     // -1: not driven toward the host (ruling d)
    n &= 1;
    if (uart_rerouted(*z, n) || (n == 1 && !(uart_pi_talks(*z) && (z->uart[1].frame & 0x20)))) return -1;
    return !z->uart[n].rtr_n;
}
void zxn_i2c_rtc(ZXN* z, int attach, int sec, int min, int hour, int dow, int date, int month, int year) {
    nserial::Rtc& c = z->rtc;
    if (attach) {
        c = nserial::Rtc();
        c.attached = true;
        c.regs[0] = nserial::bcd_put(sec); c.regs[1] = nserial::bcd_put(min); c.regs[2] = nserial::bcd_put(hour);
        c.regs[3] = (uint8_t)dow; c.regs[4] = nserial::bcd_put(date); c.regs[5] = nserial::bcd_put(month);
        c.regs[6] = nserial::bcd_put(year % 100); c.regs[7] = 0;
        c.anchor = z->t28;
    } else c = nserial::Rtc();
    i2c_update(*z);
}
void zxn_i2c_logging(ZXN* z, int on) { z->i2c_logging = on; if (!on) z->i2c_log.clear(); }
int zxn_i2c_log_len(ZXN* z) { return (int)z->i2c_log.size(); }
void zxn_i2c_log_get(ZXN* z, int i, uint64_t* out) { for (int k = 0; k < 3; k++) out[k] = z->i2c_log[i][k]; }
void zxn_set_mouse(ZXN* z, int x, int y, int buttons, int wheel) {
    z->mouse_x = x & 0xFF; z->mouse_y = y & 0xFF; z->mouse_btn = buttons & 7; z->mouse_wheel = wheel & 15;
}
void zxn_button(ZXN* z, int which) {                                  // 1 = M1 (multiface), 2 = DRIVE (divMMC): a press
    if (which == 1 && (z->nr[0x06] & 0x08)) nmi_request(*z, true);    // needs NR 0x06 b3 (zxnext:2049)
    if (which == 2 && (z->nr[0x06] & 0x10)) nmi_request(*z, false);   // b4 (2050)
}
int zxn_sd_insert(ZXN* z, const char* path, int writable, int kind) { return z->sd.insert(path, writable != 0, kind); }
void zxn_sd_eject(ZXN* z) { z->sd.eject(); }
void zxn_sd_timing(ZXN* z, int ncr, int nac, int busy, int init_tries) {   // as zxcore's zx_sd_timing
    z->sd.ncr = ncr;
    z->sd.nac = nac;
    z->sd.busy = busy;
    z->sd.init_tries = init_tries;
}
int zxn_spi_state(ZXN* z) { return z->spi_state; }
uint64_t zxn_spi_count(ZXN* z) { return z->spi_count; }
const uint16_t* zxn_frame9(ZXN* z, int blank) { return blank ? z->f9 : z->f9raw; }
int zxn_f9_width() { return F9_W; }
int zxn_fb_width() { return FB_W; }
int zxn_fb_height() { return FB_H; }
int zxn_border(ZXN* z) { return z->border; }
void zxn_io_out(ZXN* z, int port, int v) { z->io_now = true; io_write(*z, port & 0xFFFF, v & 0xFF); z->io_now = false; }
int zxn_busak(ZXN* z) { return z->db.busak; }
void zxn_dma_logging(ZXN* z, int on) { if (on) z->dma_log.clear(); z->dma_logging = on != 0; }
int zxn_dma_log_len(ZXN* z) { return (int)z->dma_log.size(); }
void zxn_dma_log_get(ZXN* z, int i, uint64_t* out) {
    const DmaEvent& e = z->dma_log[i];
    out[0] = e.t28; out[1] = e.cpu_clocks; out[2] = e.kind; out[3] = e.addr; out[4] = e.value;
}

int zxn_int_log_len(ZXN* z) { return (int)z->int_log.size(); }
void zxn_int_log_get(ZXN* z, int i, uint64_t* out) { out[0] = z->int_log[i].start; out[1] = z->int_log[i].end; }
void zxn_io_logging(ZXN* z, int on) { if (on) z->io_log.clear(); z->io_logging = on != 0; }
int zxn_io_log_len(ZXN* z) { return (int)z->io_log.size(); }
void zxn_io_log_get(ZXN* z, int i, uint64_t* out) {
    const IoEvent& e = z->io_log[i];
    out[0] = e.t28; out[1] = e.cpu_clocks; out[2] = e.port; out[3] = e.value; out[4] = e.write;
}

}  // extern "C"
