// The zxnDMA (device/dma.vhd, core 3.02.02, by Victor Trucco and Alvin Albrecht: "Loosely based on Zilog Z80C10.
// There are differences!"), as pure logic: dma.vhd's one rising-edge process, every assignment reading the values
// from before the edge, as VHDL signals do. It knows nothing of the machine: nextcore.cpp gives it its inputs at
// each rising CPU edge and carries out the bus cycle it asks for, through the machine's own memory and port decode
// (DESIGN.md §9.1 (16)). Kelp Fern, Fri 6 Nov 2026. dma:N is dma.vhd's line N.
#pragma once
#include <cstdint>

struct NextDma {
    enum Seq { IDLE, START_DMA, WAITING_ACK, READ_1, READ_2, READ_3, READ_4, WRITE_1, WRITE_2, WRITE_3, WRITE_4,
               WAITING_CYCLES, FINISH_DMA };
    // The register write sequencer (dma:198). R4_B2 is entered (WR4 with b4 set and b2, b3 clear) but no case
    // handles it (dma:835-857 are commented out), so "when others => null" (dma:891) leaves the sequencer there:
    // every later write is ignored until a reset.
    enum WrSeq { W_IDLE, R0_B0, R0_B1, R0_B2, R0_B3, R1_B0, R1_B1, R2_B0, R2_B1, R3_B0, R3_B1, R4_B0, R4_B1, R4_B2,
                 R6_B0 };
    // the read sequence (dma:199); each item's number is its bit in the read mask
    enum RdSeq { RD_STATUS, RD_COUNTER_LO, RD_COUNTER_HI, RD_PORT_A_LO, RD_PORT_A_HI, RD_PORT_B_LO, RD_PORT_B_HI };
    enum Act { NONE, MEM_READ, MEM_WRITE, IO_READ, IO_WRITE };

    // ---- registers (dma:68-105); a reset sets some (dma:211-245) and keeps the rest
    bool dir_atob = false;              // WR0 b2: 1 = A -> B
    uint16_t a_start = 0, len = 0, b_start = 0;
    bool a_io = false, b_io = false;    // WR1/WR2 b3
    uint8_t a_mode = 0, b_mode = 0;     // b5:4: 00 decrement, 01 increment, 1x fixed
    uint8_t a_tim = 1, b_tim = 1;       // the timing byte's b1:0: 00 4 clocks, 01 3, 10 2, 11 4
    uint8_t presc = 0;                  // port B's prescaler (WR2's second follow-on byte)
    uint8_t mode4 = 1;                  // WR4 b6:5: 00 byte, 01 continuous, 10 burst (only 10 is ever tested)
    bool ce_wait = false, auto_restart = false;
    uint8_t rmask = 0x7F;
    uint8_t reg_temp = 0;
    int wr_seq = W_IDLE, rd_seq = RD_STATUS;
    bool z80_mode = false;              // dma_mode_i (zxnext:1770-1779): the last DMA port the CPU used, 0x0B = 1

    // ---- the transfer (dma:107-133): the signals, as one struct so an edge can build the next set from the old
    struct St {
        int seq = IDLE;
        uint16_t src = 0, dest = 0, counter = 0, timer = 0, a = 0;   // a: dma_a_s, on the bus while the DMA has it
        bool busreq_n = true, rd = false, wr = false, mreq = false;   // dma_read/write/mreq_cycle
        bool one = false, eob_n = true;                               // status_atleastone, status_endofblock_n
    } s;
    uint8_t data = 0;                   // the byte read, written next

    // ---- a CPU write to the port: seen at the next rising edge (t80na:335-355: IORQ_rw starts after an edge)
    bool wr_pending = false;
    uint8_t wr_data = 0;

    // ---- this edge's bus action, for the machine to carry out
    Act act = NONE;

    void reset() {                      // dma:211-245
        s.seq = IDLE; s.a = 0; s.rd = s.wr = s.mreq = false; s.counter = 0; s.busreq_n = true; s.timer = 0;
        s.one = false; s.eob_n = true;
        wr_seq = W_IDLE; a_tim = b_tim = 1; presc = 0; mode4 = 1; ce_wait = auto_restart = false;
        rmask = 0x7F; rd_seq = RD_STATUS; wr_pending = false; z80_mode = false; act = NONE;
    }

    bool busreq() const { return !s.busreq_n; }
    bool src_io() const { return dir_atob ? a_io : b_io; }
    bool dst_io() const { return dir_atob ? b_io : a_io; }
    bool reading() const { return s.seq >= READ_1 && s.seq <= READ_4; }
    bool writing() const { return s.seq >= WRITE_1 && s.seq <= WRITE_4; }

    static int first_read(uint8_t mask) {          // dma:696-720, 862-886: the first set bit, else STATUS
        for (int b = 0; b < 7; b++) if ((mask >> b) & 1) return b;
        return RD_STATUS;
    }

    // A read of the port (dma:895-1140): the item now, and the sequence moves on, by the mask, in fixed wrap orders.
    // After STATUS only bits 1-6 are looked at (bit 0's test is commented out, dma:921-922).
    uint8_t read_port() {
        static const int order[7][7] = {{1, 2, 3, 4, 5, 6, -1}, {2, 3, 4, 5, 6, 0, 1}, {3, 4, 5, 6, 0, 1, 2},
                                        {4, 5, 6, 0, 1, 2, 3}, {5, 6, 0, 1, 2, 3, 4}, {6, 0, 1, 2, 3, 4, 5},
                                        {0, 1, 2, 3, 4, 5, 6}};
        const uint16_t pa = dir_atob ? s.src : s.dest, pb = dir_atob ? s.dest : s.src;
        uint8_t v = 0;
        switch (rd_seq) {
            case RD_STATUS:     v = (s.eob_n ? 0x20 : 0) | 0x1A | (s.one ? 1 : 0); break;   // 00E1101T (dma:902)
            case RD_COUNTER_LO: v = s.counter & 0xFF; break;
            case RD_COUNTER_HI: v = s.counter >> 8; break;
            case RD_PORT_A_LO:  v = pa & 0xFF; break;
            case RD_PORT_A_HI:  v = pa >> 8; break;
            case RD_PORT_B_LO:  v = pb & 0xFF; break;
            default:            v = pb >> 8; break;
        }
        int next = RD_STATUS;
        for (int i = 0; i < 7 && order[rd_seq][i] >= 0; i++)
            if ((rmask >> order[rd_seq][i]) & 1) { next = order[rd_seq][i]; break; }
        rd_seq = next;
        return v;
    }

    void write_port(uint8_t v) { wr_pending = true; wr_data = v; }
    void write_now(uint8_t v) { St n = s; reg_write(v, n); s = n; }   // io_out: no time passes (§9.1 (6))

    // One rising CPU edge (dma:249-497, then the register write, dma:499-892). The inputs as they were before it:
    // turbo, the CPU speed 0-3 (turbo_i); bai_n, BUSAK; delay, im2_dma_delay; wait_n, dma_wait_n as sampled on the
    // falling edge before this one (dma:140-145).
    void edge(int turbo, bool bai_n, bool delay, bool wait_n) {
        St n = s;
        n.timer = (uint16_t)((s.timer + (8 >> turbo)) & 0x3FFF);    // dma:250-255: counts in 28 MHz ticks
        const int src_tim = dir_atob ? a_tim : b_tim, dst_tim = dir_atob ? b_tim : a_tim;
        auto after_1 = [](int tim, int s2, int s3, int s4) { return tim == 1 ? s3 : tim == 2 ? s4 : s2; };
        const bool waiting = (uint16_t)presc > (uint16_t)(s.timer >> 5);   // ('0' & presc) > timer(13:5)

        switch (s.seq) {
            case IDLE:
                n.busreq_n = true;
                n.one = false;
                break;
            case START_DMA:                                             // bus_busreq_n_i is '1' (zxnext:1746)
                if (!bai_n || delay) n.busreq_n = true;
                else { n.busreq_n = false; n.seq = WAITING_ACK; }
                break;
            case WAITING_ACK:
                n.a = s.src;
                n.wr = false;
                n.mreq = !src_io();
                if (!bai_n) { n.seq = READ_1; n.rd = true; }
                else n.rd = false;
                break;
            case READ_1:
                n.timer = 0;
                n.seq = after_1(src_tim, READ_2, READ_3, READ_4);
                break;
            case READ_2: n.seq = READ_3; break;
            case READ_3: n.seq = READ_4; break;
            case READ_4:
                if (wait_n) { n.seq = WRITE_1; n.a = s.dest; n.rd = false; n.wr = true; n.mreq = !dst_io(); }
                break;
            case WRITE_1: {
                n.counter = s.counter + 1;
                n.seq = after_1(dst_tim, WRITE_2, WRITE_3, WRITE_4);
                const int sm = dir_atob ? a_mode : b_mode, dm = dir_atob ? b_mode : a_mode;
                if (sm == 1) n.src = s.src + 1; else if (sm == 0) n.src = s.src - 1;
                if (dm == 1) n.dest = s.dest + 1; else if (dm == 0) n.dest = s.dest - 1;
                break;
            }
            case WRITE_2: n.seq = WRITE_3; break;
            case WRITE_3: n.seq = WRITE_4; break;
            case WRITE_4:
                if (wait_n) {
                    n.one = true;
                    n.a = s.src;
                    n.wr = false;
                    n.mreq = !src_io();
                    if (presc > 0 && waiting) n.seq = WAITING_CYCLES;
                    else if (s.counter < len) {
                        if (delay) n.seq = START_DMA;
                        else { n.seq = READ_1; n.rd = true; }
                    } else n.seq = FINISH_DMA;
                }
                break;
            case WAITING_CYCLES:
                if (mode4 == 2 && waiting) n.busreq_n = true;           // burst: give the bus back while waiting
                if (waiting) n.seq = WAITING_CYCLES;
                else if (s.counter < len) n.seq = s.busreq_n ? START_DMA : WAITING_ACK;
                else n.seq = FINISH_DMA;
                break;
            case FINISH_DMA:
                n.eob_n = false;
                if (auto_restart) {
                    if (dir_atob) { n.src = a_start; n.dest = b_start; } else { n.src = b_start; n.dest = a_start; }
                    n.counter = z80_mode ? 0xFFFF : 0;                  // "z80 dma loads -1" (dma:482-486)
                    n.seq = s.busreq_n ? START_DMA : WAITING_ACK;
                } else n.seq = IDLE;
                break;
        }

        // the register write, when its strobe is first seen at this edge (cs_wr_v = "10", dma:499-505); it comes
        // after the transfer in the process, so its assignments win
        if (wr_pending) {
            wr_pending = false;
            reg_write(wr_data, n);
        }

        // the bus cycle this edge begins (DESIGN §9.1 (16)): entering READ_1 reads, entering WRITE_1 writes
        act = NONE;
        if (n.seq == READ_1 && s.seq != READ_1) act = src_io() ? IO_READ : MEM_READ;
        if (n.seq == WRITE_1 && s.seq != WRITE_1) act = dst_io() ? IO_WRITE : MEM_WRITE;
        s = n;
    }

    // dma:505-892, onto the next-state signals n
    void reg_write(uint8_t d, St& n) {
        switch (wr_seq) {
            case W_IDLE:
                reg_temp = d;
                if (!(d & 0x80) && (d & 3)) {                                       // WR0 (dma:514-534)
                    dir_atob = d & 4;
                    wr_seq = (d & 8) ? R0_B0 : (d & 0x10) ? R0_B1 : (d & 0x20) ? R0_B2 : (d & 0x40) ? R0_B3 : W_IDLE;
                } else if (!(d & 0x80) && (d & 7) == 4) {                           // WR1 (dma:538-551)
                    a_io = d & 8; a_mode = (d >> 4) & 3;
                    wr_seq = (d & 0x40) ? R1_B0 : W_IDLE;
                } else if (!(d & 0x80) && (d & 7) == 0) {                           // WR2 (dma:555-568)
                    b_io = d & 8; b_mode = (d >> 4) & 3;
                    wr_seq = (d & 0x40) ? R2_B0 : W_IDLE;
                } else if ((d & 0x80) && (d & 3) == 0) {                            // WR3 (dma:572-593)
                    if (d & 0x40) n.seq = START_DMA;
                    wr_seq = (d & 8) ? R3_B0 : (d & 0x10) ? R3_B1 : W_IDLE;
                } else if ((d & 0x80) && (d & 3) == 1) {                            // WR4 (dma:597-613)
                    mode4 = (d >> 5) & 3;
                    wr_seq = (d & 4) ? R4_B0 : (d & 8) ? R4_B1 : (d & 0x10) ? R4_B2 : W_IDLE;
                } else if ((d & 0xC0) == 0x80 && (d & 7) == 2) {                    // WR5 (dma:617-627)
                    ce_wait = d & 0x10; auto_restart = d & 0x20;
                } else if ((d & 0x80) && (d & 3) == 3) {                            // WR6 (dma:632-734)
                    switch (d) {
                        case 0xC3:                                                  // reset
                            n.seq = IDLE; n.eob_n = true; n.one = false; a_tim = b_tim = 1; presc = 0;
                            ce_wait = auto_restart = false; break;
                        case 0xC7: a_tim = 1; break;                                // reset port A timing
                        case 0xCB: b_tim = 1; break;                                // reset port B timing
                        case 0xCF:                                                  // load
                            n.eob_n = true;
                            if (dir_atob) { n.src = a_start; n.dest = b_start; } else { n.src = b_start; n.dest = a_start; }
                            n.counter = z80_mode ? 0xFFFF : 0;
                            break;
                        case 0xD3: n.eob_n = true; n.counter = z80_mode ? 0xFFFF : 0; break;   // continue
                        case 0xBF: rd_seq = RD_STATUS; break;                       // read status byte
                        case 0x8B: n.eob_n = true; n.one = false; break;            // reinitialise status byte
                        case 0xA7: rd_seq = first_read(rmask); break;               // initialise read sequence
                        case 0x87: n.seq = START_DMA; break;                        // enable
                        case 0x83: n.seq = IDLE; break;                             // disable
                        case 0xBB: wr_seq = R6_B0; break;                           // read mask follows
                        default: break;
                    }
                }
                break;
            case R0_B0: a_start = (a_start & 0xFF00) | d;
                wr_seq = (reg_temp & 0x10) ? R0_B1 : (reg_temp & 0x20) ? R0_B2 : (reg_temp & 0x40) ? R0_B3 : W_IDLE; break;
            case R0_B1: a_start = (a_start & 0x00FF) | (d << 8);
                wr_seq = (reg_temp & 0x20) ? R0_B2 : (reg_temp & 0x40) ? R0_B3 : W_IDLE; break;
            case R0_B2: len = (len & 0xFF00) | d; wr_seq = (reg_temp & 0x40) ? R0_B3 : W_IDLE; break;
            case R0_B3: len = (len & 0x00FF) | (d << 8); wr_seq = W_IDLE; break;
            case R1_B0: a_tim = d & 3; wr_seq = (d & 0x20) ? R1_B1 : W_IDLE; break;
            case R1_B1: wr_seq = W_IDLE; break;                                     // port A's prescaler: unused
            case R2_B0: b_tim = d & 3; wr_seq = (d & 0x20) ? R2_B1 : W_IDLE; break;
            case R2_B1: presc = d; wr_seq = W_IDLE; break;
            case R3_B0: wr_seq = (reg_temp & 0x10) ? R3_B1 : W_IDLE; break;          // mask and match: unused
            case R3_B1: wr_seq = W_IDLE; break;
            case R4_B0: b_start = (b_start & 0xFF00) | d; wr_seq = (reg_temp & 8) ? R4_B1 : W_IDLE; break;
            case R4_B1: b_start = (b_start & 0x00FF) | (d << 8); wr_seq = W_IDLE; break;
            case R6_B0: rmask = d; rd_seq = first_read(d); wr_seq = W_IDLE; break;
            default: break;                                                           // R4_B2: stuck (dma:891)
        }
    }
};

// The DMA with its place on the bus, all the state one rising CPU edge moves (so a run_until_pc stop can put it back):
// the T80N's bus request and acknowledge (t80n.vhd:1650-1760), im2_dma_delay (zxnext:1960-1968), im2_control's state
// for its dma_delay, and what the DMA sampled on the last falling edge. The logic is next_dma_bus.inc.
struct DmaBus {
    NextDma dma;
    bool busak = false, busreq_s = false;   // BusAck, BusReq_s
    bool mc_end = false;                    // the CPU's last tick was its machine cycle's last T-state (T_Res)
    bool delay = false;                     // im2_dma_delay
    bool wait_n_s = true;                   // dma_wait_n at the last falling edge (dma:140-145)
    bool strobe = false;                    // the DMA's strobe, as devices see it at the next edge
    bool owned_before = false, strobe_before = false, mreq_before = false;   // the same, before this edge
    uint16_t a_before = 0;
    int im2c = 0;                           // im2_control's state
    bool im2c_m1 = false;                   // in an opcode fetch, before its T3
    uint8_t im2c_op = 0;                    // cpu_opcode
    void reset() {
        dma.reset();
        busak = busreq_s = delay = strobe = im2c_m1 = owned_before = strobe_before = mreq_before = false;
        a_before = 0;
        wait_n_s = true;
        im2c = 0;
        im2c_op = 0;
    }
};
