// A bare Z80 for the tests: omse-ai's src/z80.h with 64K of flat memory, ports that answer from a
// table, and a log of every tick's pins.  tests/test_z80n.py builds it (into tests/out/) and drives it
// with ctypes, one instruction at a time.  Z80_HEADER may name another copy of z80.h (for mutants).
#define CHIPS_IMPL
#ifdef Z80_HEADER
#include Z80_HEADER
#else
#include "../src/z80.h"
#endif
#include <cstring>

struct Bare {
    z80_t cpu;
    uint64_t pins;
    bool at_t1;                 // the last tick was an instruction's first (its fetch's T1)
    uint64_t t1_pins;           // ... and these were its pins
    int wait_mem;               // wait states to add to each memory cycle (read or write), at its T2
    int wait_rd;                // ... or to each memory *read* only (the Next at 28 MHz)
    int waits_left;
    uint8_t mem[65536];
    uint8_t io_in[65536];       // what an IN from each port reads
};

static bool is_t1(const Bare* b, uint64_t p) {
    return (p & (Z80_M1 | Z80_MREQ | Z80_RD)) == (Z80_M1 | Z80_MREQ | Z80_RD) && !b->cpu.prefix_active;
}

// one tick: the CPU, then the system's answer (memory, ports), then any wait state for the next tick
static uint64_t tick(Bare* b) {
    uint64_t p = z80_tick(&b->cpu, b->pins);
    const uint16_t a = Z80_GET_ADDR(p);
    const bool mem_t1 = (p & Z80_MREQ) && (p & (Z80_RD | Z80_WR)) && !(p & Z80_RFSH);
    if (mem_t1) {
        if (p & Z80_RD) {
            Z80_SET_DATA(p, b->mem[a]);
        } else {
            b->mem[a] = Z80_GET_DATA(p);
        }
        b->waits_left = b->wait_mem + ((p & Z80_RD) ? b->wait_rd : 0);
    } else if ((p & Z80_IORQ) && !(p & Z80_M1) && (p & Z80_RD)) {
        Z80_SET_DATA(p, b->io_in[a]);
    }
    // a wait state is asked for on T1's pins (or a held T2's), and the next tick's T2 sees it and stays a T2
    p &= ~Z80_WAIT;
    if (b->waits_left > 0) {
        p |= Z80_WAIT;
        b->waits_left--;
    }
    b->pins = p;
    return p;
}

extern "C" {

Bare* bare_new(int z80n) {
    Bare* b = new Bare;
    memset(b, 0, sizeof *b);
    b->pins = z80_init(&b->cpu);
    b->cpu.z80n = z80n != 0;
    memset(b->io_in, 0xFF, sizeof b->io_in);
    return b;
}

void bare_free(Bare* b) { delete b; }
uint8_t* bare_mem(Bare* b) { return b->mem; }
uint8_t* bare_io(Bare* b) { return b->io_in; }
void bare_waits(Bare* b, int mem, int rd) { b->wait_mem = mem; b->wait_rd = rd; }
int bare_z80n(Bare* b) { return b->cpu.z80n; }

// registers by number: 0 AF 1 BC 2 DE 3 HL 4 IX 5 IY 6 SP 7 PC 8 WZ 9 IR 10 AF' 11 BC' 12 DE' 13 HL'
// 14 IM 15 IFF1 16 IFF2
unsigned bare_get(Bare* b, int r) {
    z80_t& c = b->cpu;
    switch (r) {
        case 0: return c.af; case 1: return c.bc; case 2: return c.de; case 3: return c.hl;
        case 4: return c.ix; case 5: return c.iy; case 6: return c.sp;
        case 7: return b->at_t1 ? Z80_GET_ADDR(b->t1_pins) : c.pc;   // (the next fetch's T1 has run: pc++)
        case 8: return c.wz; case 9: return c.ir; case 10: return c.af2; case 11: return c.bc2;
        case 12: return c.de2; case 13: return c.hl2; case 14: return c.im; case 15: return c.iff1;
        case 16: return c.iff2;
    }
    return 0;
}

void bare_set(Bare* b, int r, unsigned v) {
    z80_t& c = b->cpu;
    switch (r) {
        case 0: c.af = v; break; case 1: c.bc = v; break; case 2: c.de = v; break; case 3: c.hl = v; break;
        case 4: c.ix = v; break; case 5: c.iy = v; break; case 6: c.sp = v; break;
        case 7: b->pins = z80_prefetch(&c, v); b->at_t1 = false; break;
        case 8: c.wz = v; break; case 9: c.ir = v; break; case 10: c.af2 = v; break; case 11: c.bc2 = v; break;
        case 12: c.de2 = v; break; case 13: c.hl2 = v; break; case 14: c.im = v; break;
        case 15: c.iff1 = v; break; case 16: c.iff2 = v; break;
    }
}

// z80_reset, as a machine's reset button would
void bare_reset(Bare* b) { b->pins = z80_reset(&b->cpu); b->at_t1 = false; }

// Run one instruction, from its fetch's T1 to the tick before the next instruction's T1, logging every
// tick's pins (as the system left them: read data on the data bus) into log[0..max).  Returns the number
// of ticks (its T-states, waits included), or -1 if it ran past `limit` ticks.
int bare_step(Bare* b, uint64_t* log, int max, int limit) {
    int n = 0;
    uint64_t p = b->at_t1 ? b->t1_pins : tick(b);
    for (;;) {
        if (n < max) log[n] = p;
        n++;
        if (n > limit) return -1;
        p = tick(b);
        if (is_t1(b, p)) break;
    }
    b->at_t1 = true;
    b->t1_pins = p;
    return n;
}

}
