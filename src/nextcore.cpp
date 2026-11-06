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
    int flash_count = 0;
    bool flash_on = false;

    // the SPI master (ref §1.7; spi_master.vhd by Alvin Albrecht and Fabio Belavenuto, zxnext 3240-3290)
    SDCard sd;
    uint8_t spi_cs = 0xFF;              // port 0xE7: bit 0 low selects card 0
    int spi_state = 16;                 // idles at 16; a transfer runs 0..15, one state a CPU clock
    uint8_t spi_rx = 0xFF;              // the read register port 0xEB returns
    uint8_t spi_got = 0xFF;             // the byte the transfer in progress has received
    bool spi_last_d = false;            // state_last_d: the edge after state 15 loads the read register
    uint64_t spi_count = 0;             // transfers begun (for tests)
    uint8_t nr[256];
    int nr_sel = 0x24;                  // port 0x243B resets to 0x24 (ref §4.1)
    bool ula_int_disabled = false;      // port 0xFF bit 6 and its aliases (ref §2.3)
    bool eff_cd = false;                // eff_nr_08_contention_disable: NR 0x08 b6 as in effect (zxnext:5703-5733)
    int coreid = 1;                     // NR 0x10's core id (zxnext:1127)
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
// zxnext:5889-5893). (A change of NR 0x64 waits for row 0 on the hardware, ulat:455-472: here it's at once.)
inline int cvc(const ZXN& z) { return (vc_ula(z) + z.nr[0x64]) % T(z).vc_len; }

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
        // "Issue #7": conmem with mapram also brings in bank 3). (The multiface, when it comes, excludes it.)
        if (s < 2 && dm_en(z) && ((z.porte3 & 0x80) || dm_automap(z))) {
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

void nr_write(ZXN& z, int n, int v);
void do_reset(ZXN& z, bool hard);
inline bool locked(const ZXN& z);
void int_raise(ZXN& z, int i, bool unq);
inline uint16_t int_status(const ZXN& z);
void ctc_write(ZXN& z, int n, uint8_t v);

int nr_read(ZXN& z, int n) {
    switch (n) {
        case 0x02: return (z.reset_type == 2 ? 2 : z.reset_type == 1 ? 1 : 0) | (z.nr[0x02] & 0x80) | z.nmi_flags;
        case 0x03: return (z.pend_timing << 4) | (z.lock << 3) | z.mtype; // the registers, not the timing in effect
                                                                      // (zxnext:5800-5801; palette sub-index b7: later)
        case 0x05: return z.nr[0x05];
        case 0x07: return (z.speed_eff << 4) | z.speed_prog;                                  // ref §1.3
        case 0x0F: return z.issue == 4 ? 0x02 : 0x00;
        case 0x08:                                                    // b7 reads "unlocked", b6 the copy in effect
            return (locked(z) ? 0 : 0x80) | (z.eff_cd ? 0x40 : 0) | (z.nr[0x08] & 0x3F);   // (zxnext:5812-5813)
        case 0x1E: return (cvc(z) >> 8) & 1;                          // the active line (zxnext:5889-5893)
        case 0x1F: return cvc(z) & 0xFF;
        case 0x10: return z.coreid << 2;                              // no buttons pressed (zxnext:5830-5831)
        case 0x22:                                                    // the pulse, port FF b6, the line interrupt's
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
            z.nmi_flags = v & 0x0C;                                   // b3/b2 request an NMI; a 0 clears (zxnext:3781-3805;
                                                                      // the NMI itself: with the multiface)
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
        case 0x06:                                                    // PS/2 mode (bit 2) only in config mode
            z.nr[0x06] = z.config_mode ? v : (v & ~0x04) | (z.nr[0x06] & 0x04);   // (zxnext:5100-5109)
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
    if (hard) {
        z.reset_type = 4;
        for (auto& r : NR_RESET) if (r.hard >= 0) z.nr[r.reg] = r.hard;
        z.config_mode = true;
        z.mtype = 3;
        z.lock = 0;
        z.nr04 = 0;
        z.coreid = 1;                                                 // the FPGA reloads: declared values (ref §7.1)
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
    z.nr_sel = 0x24;
    z.ula_int_disabled = false;
    z.int_req = z.int_low = false;
    z.int_count = 0;
    z.int_log.clear();
    z.wait_next = false;
    z.pins = z80_init(&z.cpu);
    z.cpu.z80n = true;                                                // the Z80N's instructions (Strobe Fern's z80.h)
    z.stackless_retn = false;
    remap(z);
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

uint8_t io_read(ZXN& z, uint16_t port) {
    if (port == 0x243B) return z.nr_sel;                              // both decode all 16 bits (ref §4.1)
    if (port == 0x253B) return nr_read(z, z.nr_sel);
    if (!(port & 1)) {                                                // 0xFE: the half-rows selected by A8-A15 low
        uint8_t v = 0x1F;
        for (int r = 0; r < 8; r++) if (!(port & (0x100 << r))) v &= ~z.keys[r] & 0x1F;
        return 0xE0 | v;                                              // (EAR in, bit 6: later)
    }
    if ((port & 0xFF) == 0xFF) return floating_bus(z);                // always answered (ref §5.1)
    if ((port & 0xFF) == 0xEB && port_en(z, 11)) return z.spi_rx;     // the previous transfer's byte (ref §1.7)
    if ((port & 0xF8FF) == 0x183B && port_en(z, 27))                  // the CTC: channel by A10:8, 4-7 answer 00
        return ((port >> 8) & 7) < 4 ? z.ctc[(port >> 8) & 7].count : 0x00;    // (zxnext:2649, 2792; ctc:155-176)
    if ((port & 0xFF) == 0xE3 && dm_en(z)) return z.porte3 & 0xCF;    // divMMC (zxnext:2567, 4131)
    if (port == 0x123B && port_en(z, 15))                             // Layer 2 (zxnext:2594, 2781; the offset: unread)
        return (z.l2_seg << 6) | (z.l2_shadow << 3) | (z.l2_rd << 2) | (z.l2_en << 1) | z.l2_wr;
    return 0xFF;                                                      // nobody answers (ref §5.2)
}

void io_write(ZXN& z, uint16_t port, uint8_t v) {
    if (port == 0x243B) { z.nr_sel = v; return; }
    if (port == 0x253B) { nr_write(z, z.nr_sel, v); return; }
    if (!(port & 1)) z.border = v & 7;                                // 0xFE, A0 = 0 (ref §5.1)
    if ((port & 0xFF) == 0xE7 && port_en(z, 11)) {                    // slave select: one device only (zxnext 3258-3290)
        bool flash_ok = z.config_mode || z.reset_type == 4;           // the flash: config mode or before the first soft reset
        if ((v & 3) == 1 || (v & 3) == 2 || (flash_ok && (v == 0xFB || v == 0xF7 || v == 0x7F))) z.spi_cs = v;
        else z.spi_cs = 0xFF;
    }
    if ((port & 0xF8FF) == 0x183B && port_en(z, 27) && ((port >> 8) & 7) < 4) ctc_write(z, (port >> 8) & 7, v);
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
// (hc_adj(3:1) = 000 as well: slots 15, 0 and 3-14). The Z80 samples WAIT on the falling edge of T2 and of each Tw;
// z80.h checks it at the start of the T2 step and repeats the step while it's set. So before each rising edge, the
// window is evaluated at the slot of that T-state's falling edge, hc_ula + 1. No I/O contention in +3 timing.
inline bool p3_wait_now(const ZXN& z) {
    if (!z.contention || z.timing != 3 || z.speed_eff != 0 || (z.nr[0x08] & 0x40)) return false;
    if (!z.p3_mem && !z.p3_waiting) return false;
    int h = hc_ula(z) + 1, v = vc_ula(z);
    int adj = ((h & 15) + 1) & 15;
    return (adj >= 4 || adj <= 1) && (h & 0x1FF) < 256 && v < 192;
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
    if (x >= 256 + FB_BORDER) x -= t.hc_len;                          // the left border wraps round from the line end
    if (y >= 192 + FB_BORDER) y -= t.vc_len;
    const int fx = x + FB_BORDER, fy = y + FB_BORDER;
    if (fx < 0 || fx >= FB_W || fy < 0 || fy >= FB_H) return;
    uint8_t c = z.border;
    if (x >= 0 && x < 256 && y >= 0 && y < 192) {
        const uint8_t* scr = (z.port7ffd & 8) ? z.bram7 : z.bram5;
        uint8_t bits = scr[((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | (x >> 3)];
        uint8_t attr = scr[0x1800 + (y >> 3) * 32 + (x >> 3)];
        bool on = (bits >> (7 - (x & 7))) & 1;
        if ((attr & 0x80) && z.flash_on) on = !on;
        c = (on ? (attr & 7) : ((attr >> 3) & 7)) | ((attr & 0x40) ? 8 : 0);
    }
    z.fb[fy * FB_W + fx] = c;
}

// ---- the clock

// One rising edge of the CPU clock. Returns false (and changes nothing) if a run_until_pc stop is due: the CPU is
// about to begin T1 of an instruction's first opcode fetch at an address in the range (DESIGN.md §9.1 (5)).
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
    const bool active = a < 0x4000;                                   // sram_pre_override(2): slots 0-1 (the multiface: later)
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
// (divmmc_retn_seen, zxnext:4052; the multiface's exception: later); IM n is remembered for NR 0xC0 (im2c:212-229).
void snoop_fetch(ZXN& z, uint8_t op) {
    switch (z.snoop) {
        case 1:                                                       // after ED
            if (op == 0x45 && !dm_automap_reset(z)) {
                z.dm_hold = z.dm_held = z.dm_instant = z.dm_pending = false;
                remap(z);
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

bool cpu_edge(ZXN& z) {
    z80_t saved = z.cpu;
    uint64_t saved_pins = z.pins;
    uint64_t p = z.pins;
    const bool p3w = p3_wait_now(z);
    if (z.wait_next || p3w) p |= Z80_WAIT; else p &= ~Z80_WAIT;
    im2_edge(z, saved_pins);
    if (z.int_low || im2_int(z)) p |= Z80_INT; else p &= ~Z80_INT;     // pulse_int_n and im2_int_n (zxnext:1799)
    p = z80_tick(&z.cpu, p);
    if (z.stop_on && !z.first_edge && z80_opdone(&z.cpu)) {
        uint16_t a = Z80_GET_ADDR(p);
        if (a >= z.stop_lo && a <= z.stop_hi) {
            z.cpu = saved;
            z.pins = saved_pins;
            z.hit = true;
            z.hit_pc = a;
            return false;
        }
    }
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
        z.dm_instant = false;
        if (dm_automap(z) != was) remap(z);
    }
    const bool fetch = (p & Z80_M1) && (p & Z80_MREQ) && (p & Z80_RD);
    if (fetch) dm_fetch(z, Z80_GET_ADDR(p));
    classify(z, p);
    z.p3_waiting = p3w;
    if (!p3w) z.p3_mem = (p & Z80_MREQ) && (p & (Z80_RD | Z80_WR)) && !(p & Z80_RFSH) && contended_page(z, Z80_GET_ADDR(p));
    if (p & Z80_MREQ) {
        uint16_t a = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            Kind k;
            Z80_SET_DATA(p, mem_read(z, a, &k));
            if (z.speed_eff == 3 && (k == K_SRAM || k == K_BRAM5)) z.wait_next = true;   // ref §1.4
            if (fetch) snoop_fetch(z, Z80_GET_DATA(p));
        } else if (p & Z80_WR) {
            mem_write(z, a, Z80_GET_DATA(p));
        }
    } else if ((p & Z80_IORQ) && (p & Z80_M1)) {
        Z80_SET_DATA(p, intack_data(z));                              // INTACK: 0xFF, or hardware IM2's vector
    } else if ((p & Z80_IORQ) && !(p & Z80_M1)) {
        uint16_t port = Z80_GET_ADDR(p);
        if (p & Z80_RD) {
            uint8_t v = io_read(z, port);
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
        if (z.spi_last_d) { z.spi_rx = z.spi_got; }
        z.spi_last_d = old_state == 15;
        if (old_state < 16) z.spi_state = old_state + 1;
        const uint16_t port = Z80_GET_ADDR(p);
        if ((p & Z80_IORQ) && !(p & Z80_M1) && (p & (Z80_RD | Z80_WR)) && (port & 0xFF) == 0xEB && port_en(z, 11) &&
            (old_state == 16 || old_state == 15)) {
            const uint8_t mosi = (p & Z80_WR) ? Z80_GET_DATA(p) : 0xFF;   // a read sends 0xFF
            z.spi_got = z.sd.xfer(mosi, !(z.spi_cs & 1));                 // card 0 on select bit 0
            z.spi_state = 0;
            z.spi_count++;
        }
    }
    // the effective speed follows the programmed one only between bus cycles (ref §1.3)
    // (the VHDL samples MREQ, IORQ and M1 as they were before the edge: the previous T-state's pins, not this one's;
    // Speccy-Zone's review)
    if (!(saved_pins & (Z80_MREQ | Z80_IORQ | Z80_M1))) {
        z.speed_eff = z.speed_prog;
        if (hc_ula(z) & 0x100) z.eff_cd = z.nr[0x08] & 0x40;          // in the line's right half only (zxnext:5729-5731)
    }
    // the INT pulse is counted on rising CPU edges until 32 (48K, +3) or 36 (128K, Pentagon), then released on the
    // falling 28 MHz edge inside this same tick (zxnext:1993-2003): this edge still saw INT low, the next won't
    if (z.int_low && ++z.int_count >= T(z).int_len) {
        z.int_low = false;
        z.int_log.back().end = z.t28 + 1;                             // the first tick that starts with INT high
    }
    z.pins = p;
    return true;
}

// One 28 MHz master tick. Returns false if a stop was due before anything moved.
bool master_tick(ZXN& z) {
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
        if (z.hc == t2.int_h && z.vc == t2.int_v && !z.ula_int_disabled) int_raise(z, 11, false);
        // the line interrupt for line N: at hc_ula 255 on cvc line N-1, the last line for N = 0, "before the line is
        // drawn" (ulat:561-583); NR 0x22 b1 enables it, NR 0x22 b0 : NR 0x23 is N (zxnext:5233-5239). In pulse mode
        // it makes the same pulse as the ULA's (zxnext:1900-1955).
        if (z.nr[0x22] & 2) {
            const int n = ((z.nr[0x22] & 1) << 8) | z.nr[0x23];
            if (hc_ula(z) == 255 && cvc(z) == (n == 0 ? t2.vc_len - 1 : n - 1)) int_raise(z, 0, false);
        }
        draw_pixel(z);
    }
    copper_tick(z);
    ctc_tick(z);
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
int zxn_fb_width() { return FB_W; }
int zxn_fb_height() { return FB_H; }
int zxn_border(ZXN* z) { return z->border; }
void zxn_io_out(ZXN* z, int port, int v) { io_write(*z, port & 0xFFFF, v & 0xFF); }

int zxn_int_log_len(ZXN* z) { return (int)z->int_log.size(); }
void zxn_int_log_get(ZXN* z, int i, uint64_t* out) { out[0] = z->int_log[i].start; out[1] = z->int_log[i].end; }
void zxn_io_logging(ZXN* z, int on) { if (on) z->io_log.clear(); z->io_logging = on != 0; }
int zxn_io_log_len(ZXN* z) { return (int)z->io_log.size(); }
void zxn_io_log_get(ZXN* z, int i, uint64_t* out) {
    const IoEvent& e = z->io_log[i];
    out[0] = e.t28; out[1] = e.cpu_clocks; out[2] = e.port; out[3] = e.value; out[4] = e.write;
}

}  // extern "C"
