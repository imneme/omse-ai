// next_serial.h: the Spectrum Next's two UARTs and its bit-banged I2C bus, with an optional DS1307 on it.
// Ratio Fern, 6 Nov 2026. From serial/uart.vhd, uart_rx.vhd, uart_tx.vhd, fifop.vhd and input/debounce.vhd (core
// 3.02.02), and the DS1307 datasheet (Maxim, rev. 10/08; sources/ds1307): RAM 08h-3Fh and the pointer wrapping 3Fh to
// 00h (p. 7); BCD registers, CH, 12/24-hour, the user buffer synchronised on every START, the divider chain reset when
// the seconds are written, the power-on state (p. 8); address 1101000, the pointer moving after each byte, a NACK
// ending a read (p. 12). A pointer byte above 3Fh is masked to six bits (my choice; the datasheet doesn't say).
// Plain state machines with explicit inputs; nextcore.cpp supplies the pins, the gating (NR 0xA0, NR 0x0B), the ports
// and the interrupts (DESIGN.md §9.1 (18) and its rulings a-e).
#pragma once
#include <cstdint>
#include <deque>
#include <utility>
#include <vector>

namespace nserial {

// fifop.vhd: 2^bits entries; empty, full, near full (3/4), almost full (full - 2). The pointers move as a strobe ends;
// here a read pops and a write pushes at the access, which is when the CPU can next see it.
struct Fifo {
    std::vector<uint16_t> mem;
    int bits, rd = 0, wr = 0, stored = 0;
    explicit Fifo(int b) : mem(1 << b, 0), bits(b) {}
    bool empty() const { return stored == 0; }
    bool full() const { return stored >> bits; }
    bool near_full() const { return full() || stored >= (3 << (bits - 2)); }
    bool almost_full() const { return full() || stored >= (1 << bits) - 2; }
    uint16_t head() const { return mem[rd]; }
    void push(uint16_t v) { if (full()) return; mem[wr] = v; wr = (wr + 1) & ((1 << bits) - 1); stored++; }
    void pop() { if (empty()) return; rd = (rd + 1) & ((1 << bits) - 1); stored--; }
    void reset() { rd = wr = stored = 0; }
};

// uart_rx.vhd, one master clock edge at a time
struct Rx {
    enum { IDLE, START, BITS, PARITY, STOP_1, STOP_2, ERROR, PAUSE };
    int state = IDLE;
    uint8_t sync = 3;                   // debounce.vhd: the two-stage synchroniser (INITIAL_STATE '1')
    int counter = 0;                    // its 2^NOISE_REJECTION_BITS (= 4) counter
    bool db = true, rx_d = true;        // its output, and Rx_d
    int fbits = 3; bool fpar = false, fstop2 = false; uint32_t presc = 243;   // latched in S_IDLE (falling edge)
    uint32_t timer = 0; bool timer_updated = false;
    int bit_count = 7; bool parity = false; uint8_t shift = 0xFF;
    bool avail = false;                 // o_Rx_avail (registered, one cycle)
};
// uart_tx.vhd
struct Tx {
    enum { IDLE, RTR, START, BITS, PARITY, STOP_1, STOP_2 };
    int state = IDLE;
    bool fpar = false, fstop2 = false; uint32_t presc = 243;
    uint32_t timer = 0; int bit_count = 7; bool parity = false; uint8_t shift = 0;
    bool out = true;                    // o_Tx_n (uart.vhd registers Tx_0 once more)
    bool en_d = false;                  // the Tx FIFO's rd_dly (i_rd = Tx_en)
};

// one UART (uart.vhd), and the host's end of its line
struct Uart {
    uint8_t frame = 0x18;               // reset, break, flow control, bits (2), parity on, odd, two stop bits
    uint32_t presc_lsb = 243;           // 14 bits: 115200 at 28 MHz
    uint8_t presc_msb = 0;              // 3 bits
    Fifo rxf{9}, txf{6};
    Rx r; Tx t;
    bool avail_d = false; uint16_t byte_d = 0;
    bool st_overflow = false, st_framing = false;
    bool rtr_n = false;                 // o_Rx_rtr_n, registered
    bool o_avail = false, o_near_full = false, o_tx_empty = true;   // registered, for the interrupts
    int wake = 4;                       // ticks to step after any change from outside
    // the host's line: edges (t28, level) queued by uart_feed, back to back (ruling c)
    std::deque<std::pair<uint64_t, bool>> line;
    bool line_level = true;
    uint64_t feed_end = 0;
    std::vector<std::pair<uint64_t, uint8_t>> sent;   // the host's decode of Tx: (t28 of the start bit's fall, byte)
    bool host_cts_n = false;            // the host's CTS into this UART: clear to send by default
    bool tx_logging = false, wire = true;   // §9.1 (18) i: the host's receiving wire, and its log
    std::vector<std::pair<uint64_t, bool>> tx_events;
    uint32_t presc() const { return (uint32_t)presc_msb << 14 | presc_lsb; }
    bool fifo_reset(bool reset) const { return reset || (frame & 0x80); }
    bool status_rx_err() const { return st_overflow || st_framing; }
    bool active() const {
        return wake > 0 || r.state != Rx::IDLE || t.state != Tx::IDLE || !txf.empty() || avail_d || !line.empty() ||
               !line_level || r.counter < 4 || r.sync != 3 || !r.db || !r.rx_d;
    }
    void hard_reset() { frame = 0x18; presc_lsb = 243; presc_msb = 0; }
    // queue raw levels on the host's sending wire, (level, ticks) each, then idle 1 (§9.1 (18) i)
    void feed_levels(uint64_t now, const uint8_t* levels, const uint64_t* ticks, int n) {
        uint64_t t = feed_end > now ? feed_end : now;
        for (int i = 0; i < n; i++) { line.push_back({t, levels[i] != 0}); t += ticks[i]; }
        line.push_back({t, true});
        feed_end = t;
        wake = 4;
    }
    // queue a host frame stream: start bit, data LSB first, parity, stop bits, each bit_t28 ticks
    void feed(uint64_t now, const uint8_t* data, int len, uint64_t bit_t28, int bits, int par, int stops) {
        uint64_t t = feed_end > now ? feed_end : now;
        for (int i = 0; i < len; i++) {
            const uint8_t b = data[i];
            line.push_back({t, false}); t += bit_t28;
            int ones = 0;
            for (int k = 0; k < bits; k++) { const bool v = (b >> k) & 1; ones += v; line.push_back({t, v}); t += bit_t28; }
            if (par) { line.push_back({t, par == 1 ? !(ones & 1) : (ones & 1)}); t += bit_t28; }   // 1 odd, 2 even
            line.push_back({t, true}); t += bit_t28 * stops;
        }
        feed_end = t;
        wake = 4;
    }
};

// One master clock edge of a UART (uart.vhd, uart_rx.vhd, uart_tx.vhd). rx_pin and cts_n are the pins as the UART
// sees them after the routing; tx_visible says whether the host sees Tx (for its decode); reading/reading_status are
// the CPU's strobes this tick (they hold off the Rx FIFO's write, uart.vhd:798, 813).
inline void uart_tick(Uart& u, uint64_t now, bool reset, bool rx_pin, bool cts_n, bool tx_visible) {
    if (u.wake > 0) u.wake--;
    while (!u.line.empty() && u.line.front().first <= now) { u.line_level = u.line.front().second; u.line.pop_front(); }
    Rx& r = u.r;
    Tx& t = u.t;
    const bool frst = u.fifo_reset(reset);
    // ---- receiver. The falling-edge latch of the frame (uart_rx:98-107) happens half a cycle before this edge.
    if (r.state == Rx::IDLE) { r.fbits = (u.frame >> 3) & 3; r.fpar = u.frame & 4; r.fstop2 = u.frame & 1; r.presc = u.presc(); }
    const bool Rxv = r.db;                                            // the debounced line (debounce.vhd)
    const bool Rx_e = Rxv != r.rx_d;
    const bool texp = (r.timer >> 1) == 0;                            // rx_timer(16:1) = 0
    const bool bcexp = r.bit_count == 0;
    int nx;                                                           // state_next (uart_rx:217-287)
    switch (r.state) {
        case Rx::IDLE: nx = !Rxv ? Rx::START : Rx::IDLE; break;       // (i_frame(6), pause, is always 0 here)
        case Rx::START: nx = Rxv ? Rx::IDLE : texp ? Rx::BITS : Rx::START; break;
        case Rx::BITS: nx = (!bcexp || !texp) ? Rx::BITS : r.fpar ? Rx::PARITY : Rx::STOP_1; break;
        case Rx::PARITY: nx = !texp ? Rx::PARITY : Rxv == r.parity ? Rx::STOP_1 : Rx::ERROR; break;
        case Rx::STOP_1: nx = !texp ? Rx::STOP_1 : !Rxv ? Rx::ERROR : r.fstop2 ? Rx::STOP_2 : Rx::IDLE; break;
        case Rx::STOP_2: nx = !texp ? Rx::STOP_2 : !Rxv ? Rx::ERROR : Rx::IDLE; break;
        case Rx::ERROR: nx = !Rxv ? Rx::ERROR : Rx::IDLE; break;
        case Rx::PAUSE: nx = !Rxv ? Rx::PAUSE : Rx::IDLE; break;
        default: nx = Rx::IDLE;
    }
    const bool err_parity = r.state == Rx::PARITY && nx == Rx::ERROR;
    const bool err_framing = (r.state == Rx::STOP_1 || r.state == Rx::STOP_2) && nx == Rx::ERROR;
    const bool rx_avail_out = r.avail;                                // the registered o_Rx_avail, as uart.vhd sees it
    const uint8_t rx_byte = r.shift;
    // registers at the edge (uart_rx:110-205, 291-299)
    uint8_t shift = r.shift;
    if (r.state == Rx::START || nx == Rx::ERROR) shift = 0xFF;
    else if ((r.state == Rx::BITS || r.state == Rx::ERROR) && texp) shift = (uint8_t)(Rxv << 7 | r.shift >> 1);
    else if (r.state == Rx::STOP_1 && texp) {
        switch (r.fbits) { case 2: shift = r.shift >> 1; break; case 1: shift = r.shift >> 2; break;
                           case 0: shift = r.shift >> 3; break; default: break; }
    }
    uint32_t timer = r.timer; bool tu = r.timer_updated;
    if (r.state == Rx::IDLE) timer = r.presc >> 1;
    else if (texp) { timer = r.presc; tu = false; }
    else if (r.state != Rx::START && Rx_e && !r.timer_updated) { timer = r.presc >> 1; tu = true; }   // re-centre on an edge
    else timer = r.timer - 1;
    int bc = r.bit_count; bool par = r.parity;
    if (r.state == Rx::IDLE) { bc = 4 | r.fbits; par = u.frame & 2; }
    else if (r.state == Rx::BITS && texp) { bc = r.bit_count - 1; par = r.parity ^ Rxv; }
    const bool avail = (r.state == Rx::STOP_1 || r.state == Rx::STOP_2) && nx == Rx::IDLE;
    // debounce.vhd: button <= button(0) & i; noise resets the counter; the output follows button(1) once settled
    const bool noise = (r.sync & 1) != ((r.sync >> 1) & 1);
    const int counter = noise ? 0 : (r.counter & 4) ? r.counter : r.counter + 1;
    const bool db = (r.counter & 4) ? (r.sync >> 1) & 1 : r.db;
    r.sync = (uint8_t)(((r.sync & 1) << 1) | rx_pin);
    r.counter = counter; r.db = db; r.rx_d = Rxv;
    r.shift = shift; r.timer = timer; r.timer_updated = tu; r.bit_count = bc; r.parity = par; r.avail = avail;
    r.state = (reset || (u.frame & 0x80)) ? Rx::PAUSE : nx;
    // ---- uart.vhd's Rx side: status (528-538), the holding register and the FIFO write (787-799)
    if (frst) { u.st_overflow = u.st_framing = false; }
    else {
        u.st_overflow = u.st_overflow || (rx_avail_out && u.avail_d);
        u.st_framing = u.st_framing || err_framing || err_parity;
    }
    const bool fifo_we = u.avail_d && !u.rxf.full();
    if (fifo_we) u.rxf.push(u.byte_d);
    if (reset || fifo_we) { u.avail_d = false; u.byte_d = 0; }
    else if (rx_avail_out && !u.avail_d) { u.avail_d = true; u.byte_d = (uint16_t)(u.status_rx_err() << 8 | rx_byte); }
    if (frst) u.rxf.reset();
    u.rtr_n = frst ? (u.frame & 0x20) : ((u.frame & 0x20) && u.rxf.almost_full());
    // ---- transmitter (uart_tx:90-235)
    if (t.state == Tx::IDLE) { t.fpar = u.frame & 4; t.fstop2 = u.frame & 1; t.presc = u.presc(); }
    const bool busy = t.state != Tx::IDLE || (u.frame & 0xC0);
    const bool tx_en = !busy && !u.txf.empty();
    const bool texp2 = (t.timer >> 1) == 0, bcexp2 = t.bit_count == 0;
    const bool flow = u.frame & 0x20;
    int tn;
    switch (t.state) {
        case Tx::IDLE: tn = ((u.frame & 0x40) || !tx_en) ? Tx::IDLE : (!cts_n || !flow) ? Tx::START : Tx::RTR; break;
        case Tx::RTR: tn = (cts_n && flow) ? Tx::RTR : Tx::START; break;
        case Tx::START: tn = texp2 ? Tx::BITS : Tx::START; break;
        case Tx::BITS: tn = (!bcexp2 || !texp2) ? Tx::BITS : t.fpar ? Tx::PARITY : Tx::STOP_1; break;
        case Tx::PARITY: tn = texp2 ? Tx::STOP_1 : Tx::PARITY; break;
        case Tx::STOP_1: tn = !texp2 ? Tx::STOP_1 : t.fstop2 ? Tx::STOP_2 : Tx::IDLE; break;
        case Tx::STOP_2: tn = !texp2 ? Tx::STOP_2 : Tx::IDLE; break;
        default: tn = Tx::IDLE;
    }
    uint8_t tsh = t.shift;
    if (t.state == Tx::IDLE) tsh = (uint8_t)u.txf.head();
    else if (t.state == Tx::BITS && texp2) tsh = t.shift >> 1;
    const uint32_t ttimer = (t.state != tn || texp2) ? t.presc : t.timer - 1;
    int tbc = t.bit_count; bool tpar = t.parity;
    if (t.state == Tx::IDLE) { tbc = 4 | ((u.frame >> 3) & 3); tpar = u.frame & 2; }
    else if (t.state == Tx::BITS && texp2) { tbc = t.bit_count - 1; tpar = t.parity ^ (t.shift & 1); }
    bool txc;                                                         // o_Tx from the state before this edge
    switch (t.state) {
        case Tx::IDLE: txc = !(u.frame & 0x40); break;
        case Tx::START: txc = false; break;
        case Tx::BITS: txc = t.shift & 1; break;
        case Tx::PARITY: txc = t.parity; break;
        default: txc = true;
    }
    const bool was = t.out;
    t.out = txc;                                                      // uart.vhd:476-481 registers it
    if (tx_visible && was && !txc && t.state == Tx::START) {
        const int nbits = 5 + ((u.frame >> 3) & 3);
        u.sent.push_back({now, (uint8_t)(t.shift & ((1 << nbits) - 1))});
    }
    // the Tx FIFO's read pointer moves as Tx_en falls (fifop: rd_dly and not i_rd)
    if (t.en_d && !tx_en) u.txf.pop();
    t.en_d = tx_en;
    t.shift = tsh; t.timer = ttimer; t.bit_count = tbc; t.parity = tpar;
    t.state = (reset || (u.frame & 0x80)) ? Tx::IDLE : tn;
    if (frst) u.txf.reset();
    // registered outputs (uart.vhd:540-548)
    u.o_near_full = u.rxf.near_full();
    u.o_avail = !u.rxf.empty();
    u.o_tx_empty = u.txf.empty();
    // anything in flight keeps it stepping a few ticks more, so a byte's way through avail, avail_d, the FIFO and
    // the registered outputs (and so the interrupt) completes on time
    if (r.state != Rx::IDLE || t.state != Tx::IDLE || r.avail || u.avail_d || fifo_we || t.en_d) u.wake = 4;
}

// ---- the DS1307 (datasheet): on the I2C bus at 0x68, running on its own crystal (ruling e)
struct Rtc {
    bool attached = false;
    uint8_t regs[8] = {0x80, 0, 0, 1, 1, 1, 0, 0};   // seconds (CH b7), minutes, hours, day, date, month, year,
                                                      // control: first power, 01/01/00 01 00:00:00 with CH set (p. 8)
    uint8_t ubuf[7] = {0};              // the user buffer, latched on every START
    uint8_t ram[56] = {0};
    uint64_t anchor = 0;                // the master tick of the last whole second
    int ptr = 0;
    enum { IDLE, ADDR, ACK_ADDR, WRITE, ACK_W, READ, WAIT_ACK, IGNORE };
    int state = IDLE, nbits = 0;
    uint8_t sh = 0, cur = 0;
    bool rw = false, first = true, master_ack = false;
    bool sda = true;                    // its open-drain output (true: released)
};
inline int bcd_get(uint8_t v) { return (v >> 4) * 10 + (v & 15); }
inline uint8_t bcd_put(int n) { return (uint8_t)((n / 10) << 4 | n % 10); }
inline void rtc_second(Rtc& c) {
    uint8_t* g = c.regs;
    int s = bcd_get(g[0] & 0x7F) + 1;
    if (s < 60) { g[0] = bcd_put(s); return; }
    g[0] = 0;
    int m = bcd_get(g[1] & 0x7F) + 1;
    if (m < 60) { g[1] = bcd_put(m); return; }
    g[1] = 0;
    bool new_day = false;
    if (g[2] & 0x40) {                                                // 12-hour mode: b5 PM, b4:0 1-12
        int h = bcd_get(g[2] & 0x1F);
        bool pm = g[2] & 0x20;
        if (h == 11) { pm = !pm; new_day = !pm; h = 12; }
        else h = h == 12 ? 1 : h + 1;
        g[2] = (uint8_t)(0x40 | (pm ? 0x20 : 0) | bcd_put(h));
    } else {
        int h = bcd_get(g[2] & 0x3F) + 1;
        if (h == 24) { h = 0; new_day = true; }
        g[2] = bcd_put(h);
    }
    if (!new_day) return;
    g[3] = (uint8_t)(g[3] >= 7 ? 1 : g[3] + 1);
    const int y = bcd_get(g[6]), mo = bcd_get(g[5] & 0x1F);
    static const int ML[13] = {0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    const int dim = (mo == 2 && y % 4 == 0) ? 29 : (mo >= 1 && mo <= 12 ? ML[mo] : 31);   // leap years to 2099
    int d = bcd_get(g[4] & 0x3F) + 1;
    if (d <= dim) { g[4] = bcd_put(d); return; }
    g[4] = 1;
    int m2 = mo + 1;
    if (m2 <= 12) { g[5] = bcd_put(m2); return; }
    g[5] = 1;
    g[6] = bcd_put((y + 1) % 100);
}
inline void rtc_advance(Rtc& c, uint64_t now, uint64_t fsys) {
    if (c.regs[0] & 0x80) { c.anchor = now; return; }                 // CH: the oscillator stopped
    while (now - c.anchor >= fsys) { rtc_second(c); c.anchor += fsys; }
}
inline uint8_t rtc_read(const Rtc& c, int p) { return p < 7 ? c.ubuf[p] : p == 7 ? c.regs[7] : c.ram[p - 8]; }
inline void rtc_write(Rtc& c, int p, uint8_t v, uint64_t now) {
    if (p < 7) { c.regs[p] = v; if (p == 0) c.anchor = now; }        // a seconds write resets the countdown chain
    else if (p == 7) c.regs[7] = v;
    else c.ram[p - 8] = v;
}
// the bus changed from (scl0, sda0) to (scl, sda), as all its drivers make it
inline void rtc_bus(Rtc& c, bool scl0, bool sda0, bool scl, bool sda, uint64_t now, uint64_t fsys) {
    if (!c.attached) return;
    if (scl0 && scl && sda0 && !sda) {                               // START
        rtc_advance(c, now, fsys);
        for (int i = 0; i < 7; i++) c.ubuf[i] = c.regs[i];
        c.state = Rtc::ADDR; c.nbits = 0; c.sh = 0; c.sda = true;
        return;
    }
    if (scl0 && scl && !sda0 && sda) { c.state = Rtc::IDLE; c.sda = true; return; }   // STOP
    if (!scl0 && scl) {                                               // rising: sample
        if (c.state == Rtc::ADDR || c.state == Rtc::WRITE) { c.sh = (uint8_t)(c.sh << 1 | sda); c.nbits++; }
        else if (c.state == Rtc::WAIT_ACK) c.master_ack = !sda;
        return;
    }
    if (scl0 && !scl) {                                               // falling: drive
        switch (c.state) {
            case Rtc::ADDR:
                if (c.nbits < 8) break;
                if ((c.sh >> 1) == 0x68) { c.rw = c.sh & 1; c.sda = false; c.state = Rtc::ACK_ADDR; }
                else c.state = Rtc::IGNORE;
                break;
            case Rtc::ACK_ADDR:
                if (c.rw) {
                    rtc_advance(c, now, fsys);
                    c.cur = rtc_read(c, c.ptr); c.ptr = (c.ptr + 1) & 0x3F;
                    c.sda = c.cur & 0x80; c.nbits = 1; c.state = Rtc::READ;
                } else { c.sda = true; c.state = Rtc::WRITE; c.nbits = 0; c.sh = 0; c.first = true; }
                break;
            case Rtc::WRITE:
                if (c.nbits < 8) break;
                if (c.first) { c.ptr = c.sh & 0x3F; c.first = false; }
                else { rtc_advance(c, now, fsys); rtc_write(c, c.ptr, c.sh, now); c.ptr = (c.ptr + 1) & 0x3F; }
                c.sda = false; c.state = Rtc::ACK_W;
                break;
            case Rtc::ACK_W: c.sda = true; c.state = Rtc::WRITE; c.nbits = 0; c.sh = 0; break;
            case Rtc::READ:
                if (c.nbits < 8) { c.sda = (c.cur >> (7 - c.nbits)) & 1; c.nbits++; }
                else { c.sda = true; c.state = Rtc::WAIT_ACK; c.master_ack = false; }
                break;
            case Rtc::WAIT_ACK:
                if (c.master_ack) {
                    c.cur = rtc_read(c, c.ptr); c.ptr = (c.ptr + 1) & 0x3F;
                    c.sda = c.cur & 0x80; c.nbits = 1; c.state = Rtc::READ;
                } else { c.sda = true; c.state = Rtc::IGNORE; }
                break;
            default: break;
        }
    }
}

}  // namespace nserial
