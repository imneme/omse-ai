// The zxnDMA's place in the machine (Kelp Fern, Fri 6 Nov 2026): the bus arbitration with the T80N, the DMA's ports,
// its bus cycles through the machine's own memory and port decode, and what it waits on and gives way to. Included
// by nextcore.cpp just before cpu_edge, which calls dma_edge, dma_pins and dma_cycle. The DMA itself, as pure
// logic, is next_dma.h. References: zxnext:N is zxnext.vhd's line N, t80n:N t80n.vhd's, im2c:N im2_control.vhd's.

// the DMA's ports (zxnext:2602, 2364, 2399): 0x6B with NR 0x82 b5, 0x0B with NR 0x85 b1, by the low byte; never in
// the DMA's own cycles (port_dma_rd/wr are gated by dma_holds_bus, zxnext:2727-2728)
inline bool dma_port(const ZXN& z, uint16_t port) {
    const int lo = port & 0xFF;
    return !z.db.busak && ((lo == 0x6B && port_en(z, 5)) || (lo == 0x0B && port_en(z, 25)));
}
// a CPU access to a DMA port: dma_mode latches which port on the falling edge inside the strobe (zxnext:1770-1779), so
// before the DMA acts on it; a write lands at the next rising edge (or at once, from io_out: §9.1 (6))
uint8_t dma_port_read(ZXN& z, uint16_t port) {
    z.db.dma.z80_mode = (port & 0xFF) == 0x0B;
    return z.db.dma.read_port();
}
void dma_port_write(ZXN& z, uint16_t port, uint8_t v) {
    z.db.dma.z80_mode = (port & 0xFF) == 0x0B;
    if (z.io_now) z.db.dma.write_now(v); else z.db.dma.write_port(v);
}

// im2_dma_int_en (zxnext:1916-1917), by im2 device: 0 the line interrupt (NR 0xCC b1), 1 and 2 the UARTs' receivers
// (NR 0xCE b1:0, b5:4), 3-10 the CTC's channels (NR 0xCD), 11 the ULA (NR 0xCC b0), 12 and 13 the transmitters
// (NR 0xCE b2, b6)
inline bool dma_int_en(const ZXN& z, int i) {
    const uint8_t cc = z.nr[0xCC], cd = z.nr[0xCD], ce = z.nr[0xCE];
    switch (i) {
        case 0: return cc & 0x02;
        case 1: return ce & 0x03;
        case 2: return ce & 0x30;
        case 11: return cc & 0x01;
        case 12: return ce & 0x04;
        case 13: return ce & 0x40;
        default: return (cd >> (i - 3)) & 1;
    }
}

// im2_control (im2c:...), for its dma_delay: the state moves at the edge that begins an opcode fetch's T4
// (ifetch_fe_t3: m1 and mreq were low until T3's edge), on the opcode latched while ifetch was low. In z80.h's pins
// a fetch shows M1|MREQ|RD in T1 (with the byte read) and RFSH first in T3.
enum { IM2C_0, IM2C_ED_T4, IM2C_ED4D_T4, IM2C_ED45_T4, IM2C_CB_T4, IM2C_SRL_T1, IM2C_SRL_T2, IM2C_DDFD_T4 };
inline bool im2c_dma_delay(int st) {        // o_dma_delay
    return st == IM2C_ED_T4 || st == IM2C_ED4D_T4 || st == IM2C_ED45_T4 || st == IM2C_SRL_T1 || st == IM2C_SRL_T2;
}
inline void im2c_edge(DmaBus& b, uint64_t before) {
    bool fe_t3 = false;
    if ((before & (Z80_M1 | Z80_MREQ | Z80_RD)) == (Z80_M1 | Z80_MREQ | Z80_RD)) {
        b.im2c_m1 = true;
        b.im2c_op = Z80_GET_DATA(before);
    } else if (b.im2c_m1 && (before & Z80_RFSH)) {
        b.im2c_m1 = false;
        fe_t3 = true;
    }
    const uint8_t op = b.im2c_op;
    const bool ddfd = op == 0xDD || op == 0xFD;
    switch (b.im2c) {
        case IM2C_0:
            if (fe_t3) b.im2c = op == 0xED ? IM2C_ED_T4 : op == 0xCB ? IM2C_CB_T4 : ddfd ? IM2C_DDFD_T4 : IM2C_0;
            break;
        case IM2C_ED_T4:
            if (fe_t3) b.im2c = op == 0x4D ? IM2C_ED4D_T4 : op == 0x45 ? IM2C_ED45_T4 : IM2C_0;
            break;
        case IM2C_ED4D_T4: case IM2C_ED45_T4: b.im2c = IM2C_SRL_T1; break;
        case IM2C_SRL_T1: b.im2c = IM2C_SRL_T2; break;
        case IM2C_SRL_T2: b.im2c = IM2C_0; break;
        case IM2C_CB_T4: if (fe_t3) b.im2c = IM2C_0; break;
        default: if (fe_t3) b.im2c = ddfd ? IM2C_DDFD_T4 : IM2C_0; break;
    }
}

// One rising CPU edge for the DMA and the bus, from the values before it. before: the bus in the last T-state;
// z80_wait: z80_wait_n low at the falling edge after this edge (the WAIT cpu_edge computes for the CPU). Returns
// true if the DMA has the bus for the T-state this edge begins (BUSAK after the edge).
bool dma_edge(ZXN& z, uint64_t before, bool z80_wait) {
    DmaBus& b = z.db;
    const bool busak = b.busak, busreq_s = b.busreq_s, dma_busreq = b.dma.busreq();
    bool im2_dma_int = false;                                         // im2_device's o_dma_int (im2_device:151)
    for (int i = 0; i < 14; i++) if (z.im2_state[i] && dma_int_en(z, i)) im2_dma_int = true;
    const bool dma_delay = im2c_dma_delay(b.im2c);
    // dma_wait_n = z80_wait_n and spi_wait_n (zxnext:1803), as the DMA sampled it on the falling edge before this
    // one. spi_wait_n = state_idle or state_last_d (spi:177); the SPI master here acts an edge before the VHDL's
    // (at the edge where the strobe starts, as the CPU's port accesses do), so its state at this edge describes
    // the falling edge after it
    const bool wait_n = b.wait_n_s;
    const bool spi_ok = z.spi_state == 16 || z.spi_last_d;
    b.dma.edge(z.speed_eff, !busak, b.delay, wait_n);
    b.wait_n_s = !z80_wait && spi_ok;
    // im2_dma_delay (zxnext:1960-1968): a device with a DMA interrupt enabled is pending or in service, or an NMI
    // with NR 0xCC b7, or the delay held through im2_control's RETI/RETN states
    b.delay = im2_dma_int || (z.nmi_cause && (z.nr[0xCC] & 0x80)) || (b.delay && dma_delay);
    im2c_edge(b, before);
    // the strobe of the DMA's I/O cycle as devices will see it at the next edge: from READ_1/WRITE_1 until the
    // falling edge in READ_4/WRITE_4 where dma_wait_n is high (dma_rw_cancel, dma:146-155)
    const NextDma::St& s = b.dma.s;
    b.strobe = (s.rd || s.wr) && !((s.seq == NextDma::READ_4 || s.seq == NextDma::WRITE_4) && b.wait_n_s);
    // the T80N (t80n:1650-1760): BusReq_s <= not BUSRQ_n each edge; frozen (ClkEn = CEN and not BusAck) while
    // BusReq_s and BusAck; otherwise BusAck <= 0, and in the machine cycle's last T-state (T_Res) a request is
    // granted instead of the next cycle's T1, TState not advanced
    b.busreq_s = dma_busreq;
    if (busreq_s && busak) return true;
    b.busak = false;
    if (busreq_s && b.mc_end) { b.busak = true; return true; }
    return false;
}

// The bus as the DMA drives it in the T-state this edge begins, in z80.h's convention so that contention, the
// waits and the SPI master read it as they read the CPU's: a memory cycle shows MREQ with RD or WR at its first
// edge and MREQ alone after; an I/O cycle IORQ with RD or WR while its strobe lasts (dma:183-189), IORQ alone after.
// Between cycles, the address alone (dma_a_s stays on the bus).
uint64_t dma_pins(const ZXN& z) {
    const DmaBus& b = z.db;
    const NextDma& d = b.dma;
    uint64_t p = 0;
    Z80_SET_ADDR(p, d.s.a);
    if (d.reading() || d.writing()) {
        const bool first = d.act != NextDma::NONE;
        const uint64_t rw = d.reading() ? Z80_RD : Z80_WR;
        if (d.s.mreq) p |= Z80_MREQ | (first ? rw : 0);
        else p |= Z80_IORQ | (b.strobe ? rw : 0);
        if (d.writing()) Z80_SET_DATA(p, d.data);
    }
    return p;
}

inline void dma_note(ZXN& z, int kind, uint16_t a, uint8_t v) {
    if (z.dma_logging) z.dma_log.push_back({z.t28, z.cpu_clocks - 1, a, v, (uint8_t)kind});   // pre-edge (§9.1 (16))
}

// The DMA's bus cycle, at the edge that enters READ_1 or WRITE_1: through the machine's memory map and port decode,
// side effects and all. The byte read is the one the read mux gives (dma_d_i is cpu_di, zxnext:1756).
void dma_cycle(ZXN& z, uint64_t p) {
    NextDma& d = z.db.dma;
    const uint16_t a = Z80_GET_ADDR(p);
    switch (d.act) {
        case NextDma::MEM_READ: {
            Kind k;
            d.data = mem_read(z, a, &k);
            // sram_wait_n follows cpu_rd_n, the DMA's while it has the bus (zxnext:3130-3137)
            if (z.speed_eff == 3 && (k == K_SRAM || k == K_BRAM5)) z.wait_next = true;
            dma_note(z, 0, a, d.data);
            break;
        }
        case NextDma::MEM_WRITE: mem_write(z, a, d.data); dma_note(z, 1, a, d.data); break;
        case NextDma::IO_READ: d.data = io_read(z, a); dma_note(z, 2, a, d.data); break;
        case NextDma::IO_WRITE: io_write(z, a, d.data); dma_note(z, 3, a, d.data); break;
        default: break;
    }
}
