"""The Next's two UARTs (serial/uart.vhd, uart_rx.vhd, uart_tx.vhd, fifop.vhd;
core 3.02.02), through DESIGN.md §9.1 (18) and its rulings a-e only.

Ports (zxnext:2598, uart:237-258, A9:8 picks the register): 133Bh write = Tx,
read = status; 143Bh read = Rx, write = prescaler LSB; 153Bh select (b6 UART,
b4 also sets that UART's prescaler MSB); 163Bh frame. UART 0 is the ESP's,
UART 1 the Pi's. The UARTs count CLK_28 (zxnext:3321): a bit is P t28.
Written from the VHDL by Loam Fern, without reading the builder's code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402,F401
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402
from test_next_timing import launch                      # noqa: E402
from test_next_interrupts import main_loop, vector, reached, CODE, F48  # noqa: E402

TX, RX, SEL, FRAME = 0x133B, 0x143B, 0x153B, 0x163B
P0 = 243                                                # power-on prescaler: 115200 at 28 MHz (uart:319)


def frame_byte(frame):
    """'8N1' -> the frame register: b4:3 bits-5, b2 parity, b1 odd, b0 two stops (uart:302)."""
    n, par, stops = int(frame[0]), frame[1], int(frame[2])
    return (n - 5) << 3 | (par != 'N') << 2 | (par == 'O') << 1 | (stops - 1)


def frame_bits(frame):
    """Bit times a frame takes: start, data, parity, stops."""
    return 1 + int(frame[0]) + (frame[1] != 'N') + int(frame[2])


def setup(zx, n=0, frame='8N1', p=P0, flow=False):
    """Select UART n, set its prescaler (MSB through select b4, LSB in two
    halves through 143Bh, uart:268-336) and its frame."""
    zx.io_out(SEL, n << 6 | 0x10 | (p >> 14))
    zx.io_out(RX, p & 0x7F)
    zx.io_out(RX, 0x80 | (p >> 7) & 0x7F)
    zx.io_out(FRAME, frame_byte(frame) | flow << 5)


def status(zx):
    return zx.io_in(TX)


def drain(zx, count):
    return bytes(zx.io_in(RX) for _ in range(count))


@needs_next
class Registers(NextCase):

    def test_power_on(self):
        zx = bare()
        self.assertEqual([zx.io_in(p) for p in (SEL, FRAME, TX, RX)], [0x00, 0x18, 0x10, 0x00],
                         'UART 0, prescaler MSB 0; 8N1 (uart:128); status: Tx empty only; Rx empty reads 0')
        zx.io_out(SEL, 0x40)
        self.assertEqual([zx.io_in(p) for p in (SEL, FRAME, TX, RX)], [0x40, 0x18, 0x10, 0x00],
                         'UART 1 reads "01000" & MSB (uart:371)')

    def test_prescaler_msb_belongs_to_each_uart(self):
        zx = bare()
        zx.io_out(SEL, 0x15)
        self.assertEqual(zx.io_in(SEL), 0x05)
        zx.io_out(SEL, 0x52)
        self.assertEqual(zx.io_in(SEL), 0x42)
        zx.io_out(SEL, 0x00)                            # b4 clear: select only (uart:276-286)
        self.assertEqual(zx.io_in(SEL), 0x05)
        zx.io_out(SEL, 0x40)
        self.assertEqual(zx.io_in(SEL), 0x42)

    def test_frame_belongs_to_each_uart(self):
        zx = bare()
        zx.io_out(FRAME, 0x1F)
        zx.io_out(SEL, 0x40)
        self.assertEqual(zx.io_in(FRAME), 0x18)
        zx.io_out(FRAME, 0x05)
        zx.io_out(SEL, 0x00)
        self.assertEqual(zx.io_in(FRAME), 0x1F)
        zx.io_out(SEL, 0x40)
        self.assertEqual(zx.io_in(FRAME), 0x05)

    def test_soft_reset_keeps_frame_and_prescaler(self):
        """i_reset_hard is tied low (zxnext:3325): only the core load sets the
        frame and prescaler; a soft reset clears the select (uart:274) and the
        FIFOs, nothing else."""
        zx = bare()
        zx.io_out(SEL, 0x13)
        zx.io_out(FRAME, 0x1F)
        zx.io_out(TX, 0x41)
        zx.reset()
        zx.run_ticks(1000)
        self.assertEqual([zx.io_in(p) for p in (SEL, FRAME, TX)], [0x03, 0x1F, 0x10])
        self.assertEqual(zx.uart_sent(0)[1:], [], 'at most the byte under way before the reset')


@needs_next
class Transmit(NextCase):

    def test_bytes_go_out_at_the_frame_rate(self):
        """A bit is P clocks (uart_tx:131-141); data LSB first, 5-8 bits,
        parity, one or two stops; between bytes one clock of IDLE before the
        next START (uart_tx:177-185, 213-226): start bits P*bits + 1 apart."""
        for frame in ('8N1', '7E1', '8O2', '5N1', '6E2'):
            for p in (P0, 100):
                with self.subTest(frame=frame, p=p):
                    zx = bare()
                    setup(zx, frame=frame, p=p)
                    data = [0x55, 0xA3, 0x0F, 0xFE]
                    for b in data:
                        zx.io_out(TX, b)
                    zx.run_ticks(5 * p * 12 + 1000)
                    sent = zx.uart_sent(0)
                    mask = (1 << int(frame[0])) - 1
                    self.assertEqual([b for _, b in sent], [b & mask for b in data])
                    self.assertEqual([b[0] - a[0] for a, b in zip(sent, sent[1:])],
                                     [p * frame_bits(frame) + 1] * 3)
                    self.assertEqual(zx.uart_sent(0), [], 'uart_sent clears')

    def test_a_17_bit_prescaler(self):
        zx = bare()
        p = 1 << 14 | 7                                 # MSB 1, LSB 7
        setup(zx, p=p)
        self.assertEqual(zx.io_in(SEL), 0x01)
        zx.io_out(TX, 0x11)
        zx.io_out(TX, 0x22)
        zx.run_ticks(p * 21)
        sent = zx.uart_sent(0)
        self.assertEqual([b for _, b in sent], [0x11, 0x22])
        self.assertEqual(sent[1][0] - sent[0][0], 10 * p + 1)

    def test_a_new_prescaler_waits_for_the_next_byte(self):
        """The prescaler and frame are taken while the transmitter is idle
        (uart_tx:100-110), so a byte under way keeps its own."""
        zx = bare()
        setup(zx, p=P0)
        for b in (1, 2, 3):
            zx.io_out(TX, b)
        zx.run_ticks(P0 * 4)                            # byte 1 under way
        zx.io_out(RX, 100)
        zx.io_out(RX, 0x80)                             # P = 100
        zx.run_ticks(P0 * 40)
        t = [s[0] for s in zx.uart_sent(0)]
        self.assertEqual([b - a for a, b in zip(t, t[1:])], [10 * P0 + 1, 10 * 100 + 1])

    def test_the_fifo_holds_64(self):
        """uart:529: a write when the 64-byte FIFO is full is dropped (b1 says full)."""
        zx = bare()
        setup(zx, p=20)
        for i in range(70):
            zx.io_out(TX, i)
        self.assertEqual(status(zx) & 0x12, 0x02, 'full, and not empty')
        zx.run_ticks(66 * 20 * 10 + 1000)
        self.assertEqual([b for _, b in zx.uart_sent(0)], list(range(64)))
        self.assertEqual(status(zx) & 0x12, 0x10, 'empty again')

    def test_tx_empty_waits_for_the_last_stop_bit(self):
        """Status b4 is FIFO empty and transmitter idle (uart:549)."""
        zx = bare()
        setup(zx)
        zx.io_out(TX, 0x5A)
        self.assertEqual(status(zx) & 0x10, 0x00)
        zx.run_ticks(P0 * 5)
        self.assertEqual(status(zx) & 0x10, 0x00, 'the FIFO is empty, the byte still going out')
        zx.run_ticks(P0 * 6)
        self.assertEqual(status(zx) & 0x10, 0x10)

    def test_flow_control_waits_for_cts(self):
        """Frame b5: with CTS not clear the transmitter waits in S_RTR (uart_tx:177-192)."""
        zx = bare()
        setup(zx, flow=True)
        zx.uart_cts(0, False)
        zx.io_out(TX, 0x77)
        zx.run_ticks(P0 * 30)
        self.assertEqual(zx.uart_sent(0), [])
        t = zx.t28
        zx.uart_cts(0, True)
        zx.run_ticks(P0 * 12)
        sent = zx.uart_sent(0)
        self.assertEqual([b for _, b in sent], [0x77])
        self.assertGreaterEqual(sent[0][0], t)

    def test_without_flow_control_cts_is_ignored(self):
        zx = bare()
        setup(zx)
        zx.uart_cts(0, False)
        zx.io_out(TX, 0x77)
        zx.run_ticks(P0 * 12)
        self.assertEqual([b for _, b in zx.uart_sent(0)], [0x77])


@needs_next
class Receive(NextCase):

    def test_bytes_arrive_in_order(self):
        zx = bare()
        setup(zx)
        zx.uart_feed(0, b'\x55\x00\xff\x81', P0)
        zx.run_ticks(P0 * 45)
        self.assertEqual(status(zx) & 0x01, 0x01)
        self.assertEqual(drain(zx, 4), b'\x55\x00\xff\x81')
        zx.run_ticks(10)
        self.assertEqual(status(zx), 0x10, 'empty, no errors')
        self.assertEqual(zx.io_in(RX), 0x00, 'an empty Rx reads 0 (uart:348-354)')

    def test_frames(self):
        for frame in ('7E1', '8O2', '5N1', '6E2'):
            with self.subTest(frame=frame):
                zx = bare()
                setup(zx, frame=frame, p=100)
                data = bytes([0x1F, 0x0A, 0x15])
                zx.uart_feed(0, data, 100, frame)
                zx.run_ticks(100 * 13 * 3 + 500)
                self.assertEqual(status(zx) & 0xC5, 0x01, 'received, no errors')
                self.assertEqual(drain(zx, 3), bytes(b & ((1 << int(frame[0])) - 1) for b in data))

    def test_a_byte_is_available_during_its_stop_bit(self):
        """Rx_avail rises when the stop bit's middle is sampled (uart_rx:299-306)."""
        zx = bare()
        setup(zx)
        zx.uart_feed(0, b'\x3C', P0)
        zx.run_ticks(9 * P0)
        self.assertEqual(status(zx) & 0x01, 0x00, 'not before the stop bit')
        zx.run_ticks(P0)
        self.assertEqual(status(zx) & 0x01, 0x01, 'by its end')

    def test_a_parity_error(self):
        """A wrong parity bit sends the receiver to S_ERROR (uart_rx:253-260): the
        byte isn't kept; status b6 sticks (uart:541) until a status read ends
        (uart:536), and bytes arriving meanwhile carry the error in their
        ninth bit, read as status b5 (uart:359, 792)."""
        zx = bare()
        setup(zx, frame='8E1')
        zx.uart_feed(0, b'\x41', P0, '8O1')
        zx.uart_feed(0, b'\x42', P0, '8E1')
        zx.run_ticks(P0 * 25)
        self.assertEqual(status(zx) & 0x65, 0x61, 'parity error, a byte, flagged')
        zx.run_ticks(10)
        self.assertEqual(status(zx) & 0x65, 0x21, 'the read cleared b6; the byte keeps its flag')
        self.assertEqual(drain(zx, 1), b'\x42')
        zx.run_ticks(10)
        self.assertEqual(status(zx), 0x10)

    def test_a_framing_error_and_no_break(self):
        """8N2 expected, 8N1 sent: the second stop bit is the next start bit, low
        (uart_rx:262-271). The byte isn't kept. The next byte, all zeros, holds
        the line low through the error, and still no break: the shift register
        refills with ones whenever the next state is S_ERROR (uart_rx:161-162), so
        o_err_break (uart_rx:314) never rises in 3.02.02."""
        zx = bare()
        setup(zx, frame='8N2')
        zx.uart_feed(0, b'\x7F\x00', P0, '8N1')
        zx.run_ticks(P0 * 25)
        self.assertEqual(status(zx), 0x50, 'framing error only: nothing kept, no break')

    def test_the_receiver_recentres_on_edges(self):
        """An Rx edge resets the bit timer to half a bit, at most once a bit
        (uart_rx:188-190), so a sender 8% slow or fast still lands every
        sample mid-bit through 8E2 with alternating data. A clock-level model
        (foil-run/probes/uart_rx_model.py) loses all four bytes at 8% without
        the re-centring and keeps them at 3-5%. (Mutant survivor 1, run 1.)"""
        for bit in (262, 224):                          # P = 243 +/- 8%
            with self.subTest(bit_t28=bit):
                zx = bare()
                setup(zx, frame='8E2')
                data = bytes([0x55, 0xAA, 0x5A, 0xA5])
                zx.uart_feed(0, data, bit, '8E2')
                zx.run_ticks(bit * 12 * 4 + 1000)
                self.assertEqual(status(zx) & 0xC5, 0x01, 'received, no errors')
                self.assertEqual(drain(zx, 4), data)

    def test_a_low_first_stop_bit_is_a_framing_error(self):
        """With one stop bit as with two, a 0 where the stop bit belongs sends
        the receiver to S_ERROR (uart_rx:262-268). A 7N1 receiver hearing 8N1
        samples the sender's bit 7 as its stop bit. (Mutant survivor 2, run 1.)"""
        zx = bare()
        setup(zx, frame='7N1')
        zx.uart_feed(0, b'\x05', P0, '8N1')
        zx.run_ticks(P0 * 12)
        self.assertEqual(status(zx), 0x50, 'bit 7 = 0: framing error, nothing kept')
        zx.run_ticks(10)
        zx.uart_feed(0, b'\x85', P0, '8N1')
        zx.run_ticks(P0 * 12)
        self.assertEqual(status(zx) & 0xC5, 0x01, 'bit 7 = 1 is a good stop bit')
        self.assertEqual(drain(zx, 1), b'\x05')

    def test_the_fifo_holds_512_and_one_more(self):
        """fifop: full at 512 (fifop:136); a byte arriving then waits in
        rx_avail_d (uart:784-800) until there's room; the next one is lost and
        sets b2, overflow (uart:540). Near full (b3) from 384 (fifop:141)."""
        zx = bare()
        setup(zx, p=20)
        data = bytes((i * 7 + 3) & 0xFF for i in range(520))
        zx.uart_feed(0, data[:383], 20)
        zx.run_ticks(383 * 200 + 500)
        self.assertEqual(status(zx) & 0x0D, 0x01, '383: not near full')
        zx.uart_feed(0, data[383:], 20)
        zx.run_ticks(137 * 200 + 500)
        self.assertEqual(status(zx) & 0x0D, 0x0D, 'near full, overflowed')
        got = drain(zx, 512)
        zx.run_ticks(200)
        got += drain(zx, 2)
        self.assertEqual(got, data[:513] + b'\x00', '512, then the one that waited, then nothing')

    def test_rts_with_flow_control(self):
        """RTR_n is high (not ready) from 510 stored (fifop:142; uart:438-446)."""
        zx = bare()
        setup(zx, p=20, flow=True)
        self.assertIs(zx.uart_rts(0), True)
        zx.uart_feed(0, bytes(509), 20)
        zx.run_ticks(509 * 200 + 500)
        self.assertIs(zx.uart_rts(0), True, '509: ready')
        zx.uart_feed(0, bytes(1), 20)
        zx.run_ticks(700)
        self.assertIs(zx.uart_rts(0), False, '510: not ready')
        drain(zx, 1)
        zx.run_ticks(20)
        self.assertIs(zx.uart_rts(0), True, 'a read makes room')

    def test_rts_without_flow_control_is_always_ready(self):
        zx = bare()
        setup(zx, p=20)
        zx.uart_feed(0, bytes(520), 20)
        zx.run_ticks(520 * 200 + 500)
        self.assertIs(zx.uart_rts(0), True)

    def test_frame_bit_7_resets_the_fifos(self):
        zx = bare()
        setup(zx)
        zx.uart_feed(0, b'\x01\x02', P0)
        zx.run_ticks(P0 * 22)
        self.assertEqual(status(zx) & 0x01, 0x01)
        zx.io_out(FRAME, 0x98)
        zx.run_ticks(16)                                # an instruction's worth: b7 held a while,
        zx.io_out(FRAME, 0x18)                          # as two OUTs on a real Next would hold it
        zx.run_ticks(10)
        self.assertEqual(status(zx) & 0x01, 0x00, 'uart:385')


def level_at(events, t, initial=1):
    """The host's wire level at tick t from uart_tx_events' changes."""
    level = initial
    for when, lv in events:
        if when > t:
            break
        level = lv
    return level


def frame_levels(byte, p, frame='8N1'):
    """[(level, ticks)] for one frame, LSB first, for uart_feed_levels."""
    n, par, stops = int(frame[0]), frame[1], int(frame[2])
    bits = [(byte >> i) & 1 for i in range(n)]
    out = [(0, p)] + [(b, p) for b in bits]
    if par != 'N':
        out.append(((sum(bits) & 1) ^ (par == 'O'), p))
    return out + [(1, p * stops)]


@needs_next
class Lines(NextCase):
    """The wires themselves, through ruling (i): uart_tx_events and
    uart_feed_levels."""

    def test_parity_on_transmit(self):
        """The parity bit is the odd flag xor the data bits (uart_tx:150-157,
        242): odd parity makes the count of ones odd, even parity even.
        (Mutant survivor 4, run 1.)"""
        for frame in ('8O1', '8E1', '7O2'):
            for byte in (0x41, 0x43):
                with self.subTest(frame=frame, byte=f'{byte:02X}h'):
                    zx = bare()
                    setup(zx, frame=frame)
                    zx.uart_tx_log(0, True)
                    zx.io_out(TX, byte)
                    zx.run_ticks(P0 * 14)
                    ev = zx.uart_tx_events(0)
                    self.assertTrue(ev and ev[0][1] == 0, 'a start bit')
                    t0 = ev[0][0]
                    n = int(frame[0])
                    bits = [level_at(ev, t0 + P0 * k + P0 // 2) for k in range(n + 3)]
                    self.assertEqual(bits[0], 0, 'start')
                    self.assertEqual(bits[1:n + 1], [(byte >> i) & 1 for i in range(n)], 'LSB first')
                    ones = sum(bits[1:n + 2])
                    self.assertEqual(ones & 1, 1 if frame[1] == 'O' else 0,
                                     f'{frame[1]} parity over data and parity bit')
                    self.assertEqual(bits[n + 2], 1, 'stop')

    def test_break_holds_tx_low(self):
        """Frame b6: the idle transmitter drives not b6 (uart_tx:239), so the
        line stays low for as long as b6 is set, one clock behind (uart:476-481).
        (Mutant survivor 5, run 1.)"""
        zx = bare()
        setup(zx)
        zx.uart_tx_log(0, True)
        t1 = zx.t28
        zx.io_out(FRAME, 0x58)
        zx.run_ticks(P0 * 20)
        t2 = zx.t28
        zx.io_out(FRAME, 0x18)
        zx.run_ticks(P0)
        ev = zx.uart_tx_events(0)
        self.assertEqual([lv for _, lv in ev], [0, 1], 'low, then high again, nothing between')
        self.assertTrue(t1 <= ev[0][0] <= t1 + 3 and t2 <= ev[1][0] <= t2 + 3, f'{ev} vs {t1}, {t2}')

    def test_a_short_glitch_is_ignored(self):
        """Rx goes through misc/debounce.vhd with COUNTER_SIZE 2 (uart_rx:119-129):
        a pulse shorter than 4 clocks never reaches the receiver. A 3-tick low
        glitch laid where a receiver without it would sample bit 0 of 0Fh
        (start + P/2 + P: foil-run/probes/uart_rx_model.py) changes nothing.
        (Mutant survivor 3, run 1.)"""
        for at in (118, 121, 124):                      # ticks into bit 0
            with self.subTest(at=at):
                zx = bare()
                setup(zx)
                lv = frame_levels(0x0F, P0)
                lv[1:2] = [(1, at), (0, 3), (1, P0 - at - 3)]
                zx.uart_feed_levels(0, lv)
                zx.run_ticks(P0 * 12)
                self.assertEqual(status(zx) & 0xC5, 0x01)
                self.assertEqual(drain(zx, 1), b'\x0f')

    def test_feed_levels_carries_a_whole_frame(self):
        """An anchor for the helper: the same frame without a glitch."""
        zx = bare()
        setup(zx)
        zx.uart_feed_levels(0, frame_levels(0xA7, P0))
        zx.run_ticks(P0 * 12)
        self.assertEqual(drain(zx, 1), b'\xa7')


@needs_next
class PiUart(NextCase):
    """Rulings (a) and (f): UART 1's far end is a Raspberry Pi on fixed pins,
    transmitting on GPIO 14 and listening on GPIO 15. In the VHDL the Pi UART
    enable is NR A0h b4 and b5 crosses Rx/Tx (zxnext:2237-2238; nextreg.txt:
    906-915 names them the other way round, D-20): the Next's Rx is GPIO 14
    and its Tx GPIO 15 only with b5 set (zxnext:2281-2292). So only A0h = 30h
    talks to the Pi."""

    def exchange(self, a0, frame=0x18):
        zx = bare()
        zx.nr_write(0xA0, a0)
        setup(zx, n=1)
        zx.io_out(FRAME, frame)
        zx.uart_feed(1, b'\x99', P0)
        zx.io_out(TX, 0x66)
        zx.run_ticks(P0 * 12)
        return zx

    def test_only_enable_and_swap_together_reach_the_pi(self):
        for a0 in (0x00, 0x20, 0x10):
            with self.subTest(a0=f'{a0:02X}h'):
                zx = self.exchange(a0)
                self.assertEqual(status(zx) & 0x01, 0x00, 'nothing received')
                self.assertEqual(zx.uart_sent(1), [], 'nothing reaches the Pi')
        zx = self.exchange(0x30)
        self.assertEqual(drain(zx, 1), b'\x99')
        self.assertEqual([b for _, b in zx.uart_sent(1)], [0x66])

    def test_rts_reaches_the_pi_only_with_hardware_flow_control(self):
        """Ruling (d): None when the pin isn't driven toward the host. GPIO 16/17
        carry RTR/CTS only with the Pi UART and frame b5 (zxnext:2283-2293)."""
        self.assertIsNone(self.exchange(0x00).uart_rts(1))
        self.assertIsNone(self.exchange(0x30).uart_rts(1), 'no flow control')
        self.assertIs(self.exchange(0x30, frame=0x38).uart_rts(1), True)

    def test_uart_0_is_always_connected(self):
        zx = bare()
        setup(zx, n=0)
        zx.uart_feed(0, b'\x12', P0)
        zx.run_ticks(P0 * 11)
        self.assertEqual(drain(zx, 1), b'\x12')
        self.assertIs(zx.uart_rts(0), True)


@needs_next
class JoystickUart(NextCase):
    """Ruling (b): NR 0Bh reroutes a UART to a joystick port only in UART mode,
    b7 and b5 both set (joy_iomode_uart_en, zxnext:3494); b0 picks the UART
    (zxnext:3298-3308). Then the host's line is disconnected from it."""

    def talk(self, nr0b):
        zx = bare()
        zx.nr_write(0x0B, nr0b)
        setup(zx)
        zx.uart_feed(0, b'\x3C', P0)
        zx.io_out(TX, 0xC3)
        zx.run_ticks(P0 * 12)
        return zx

    def test_io_mode_without_uart_mode_leaves_the_uart_alone(self):
        for nr0b in (0x80, 0x90):                       # b7 with modes 00 and 01 (Mutant survivor 9, run 1)
            with self.subTest(nr0b=f'{nr0b:02X}h'):
                zx = self.talk(nr0b)
                self.assertEqual(drain(zx, 1), b'\x3C')
                self.assertEqual([b for _, b in zx.uart_sent(0)], [0xC3])
                self.assertIs(zx.uart_rts(0), True)

    def test_uart_mode_takes_uart_0_from_the_host(self):
        zx = self.talk(0xA0)                            # b7, b5: UART mode; b0 = 0: UART 0
        self.assertEqual(status(zx) & 0x01, 0x00, 'Rx from the joystick pin, idle')
        self.assertEqual(zx.uart_sent(0), [])
        self.assertIsNone(zx.uart_rts(0), 'ruling (d): rerouted')


@needs_next
class Interrupts(NextCase):

    def test_status_in_nr_ca(self):
        """Status bits rise with each request's edge, enabled or not
        (im2p:156-160): Rx available reads in pairs (zxnext:6160-6161); Tx empty
        rises when the FIFO empties (uart:562)."""
        zx = bare()
        setup(zx)
        zx.nr_write(0xCA, 0x77)
        self.assertEqual(zx.nr_read(0xCA), 0x00, 'writes clear (zxnext:1911-1914)')
        zx.uart_feed(0, b'\x01', P0)
        zx.run_ticks(P0 * 11)
        self.assertEqual(zx.nr_read(0xCA), 0x03)
        zx.io_out(TX, 0x01)
        zx.run_ticks(P0 * 2)
        self.assertEqual(zx.nr_read(0xCA), 0x07)

    def im2(self, c6):
        zx = bare(timing='48k')
        zx.nr_write(0x03, 0x00)                         # boot ROM off (test_next_interrupts)
        zx.nr_write(0xC4, 0x80)                         # ULA interrupt off
        zx.nr_write(0xC0, 0xA1)                         # hardware IM2, vectors 101xxxx0
        zx.nr_write(0xC6, c6)
        loop = main_loop(zx, 2)
        vector(zx, 0x90, 0xA0 | 1 << 1, 0x9400)         # UART 0 Rx is source 1 (zxnext:1900-1902)
        zx.load(0x9400, bytes([0xFB, 0xED, 0x4D]))
        setup(zx)
        launch(zx, CODE)
        self.assertTrue(zx.run_until_pc(loop, max_ticks=10**6))
        return zx

    def test_rx_available_interrupts_in_hardware_im2(self):
        zx = self.im2(0x01)
        zx.uart_feed(0, b'\x01', P0)
        self.assertTrue(reached(zx, 0x9400, P0 * 12), 'vector A2h')

    def test_near_full_alone_ignores_one_byte(self):
        """C6 b1 masks 'available' (zxnext:1902): only near full interrupts."""
        zx = self.im2(0x02)
        zx.uart_feed(0, b'\x01', P0)
        self.assertFalse(reached(zx, 0x9400, P0 * 40))
        self.assertGreater(zx.t28, 0, 'time passed')


if __name__ == '__main__':
    unittest.main()
