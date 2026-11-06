"""The Next's bit-banged I2C and the optional DS1307 RTC, through DESIGN.md
§9.1 (18) and its rulings only.

The lines (zxnext:3186-3226; ports.txt:334-343): 103Bh is SCL and 113Bh is SDA.
Writing bit 0 = 0 pulls the line low and 1 releases it, latched on CLK_28.
Reading gives "1111111" & the line, sampled on the CPU clock's falling edge;
the lines are open drain with pull-ups (top:2038-2042). The DS1307's behaviour
comes from its datasheet (sources/ds1307/DS1307.pdf, Maxim, rev. 10/08): the
address map on p. 7, the clock and calendar on p. 8, the 2-wire modes on p. 12.
Written by Loam Fern, without reading the builder's code.
"""

import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import Next, needs_next, NextCase, bare  # noqa: E402

SCL, SDA = 0x103B, 0x113B
HALF = 150                                              # t28 per half clock: about 93 kHz, under the DS1307's 100
SECOND = 28_000_000                                     # ruling (e): f_sys at NR 11h = 0
WHEN = datetime.datetime(2026, 11, 6, 13, 45, 30)


class Bus:
    """An I2C master, bit-banged through the two ports as a program would."""

    def __init__(self, zx):
        self.zx = zx

    def set(self, port, level):
        self.zx.io_out(port, level)
        self.zx.run_ticks(HALF)

    def sda(self):
        return self.zx.io_in(SDA) & 1

    def start(self):                                    # SDA falls while SCL is high
        self.set(SDA, 1)
        self.set(SCL, 1)
        self.set(SDA, 0)
        self.set(SCL, 0)

    def stop(self):                                     # SDA rises while SCL is high
        self.set(SDA, 0)
        self.set(SCL, 1)
        self.set(SDA, 1)

    def write(self, byte):
        """Eight bits MSB first, then the ninth clock: True if acknowledged."""
        for i in range(7, -1, -1):
            self.set(SDA, byte >> i & 1)
            self.set(SCL, 1)
            self.set(SCL, 0)
        self.set(SDA, 1)
        self.set(SCL, 1)
        ack = self.sda() == 0
        self.set(SCL, 0)
        return ack

    def read(self, ack=True):
        self.set(SDA, 1)
        byte = 0
        for _ in range(8):
            self.set(SCL, 1)
            byte = byte << 1 | self.sda()
            self.set(SCL, 0)
        self.set(SDA, 0 if ack else 1)
        self.set(SCL, 1)
        self.set(SCL, 0)
        self.set(SDA, 1)
        return byte

    def write_regs(self, pointer, data=b''):
        """Slave receiver mode (p. 12): address + W, the word address, data."""
        self.start()
        acks = [self.write(0xD0), self.write(pointer)] + [self.write(b) for b in data]
        self.stop()
        return acks

    def read_regs(self, count, pointer=None):
        """Slave transmitter mode (p. 12), from `pointer` (a write of the word
        address, then a repeated START) or from wherever the pointer is."""
        self.start()
        if pointer is not None:
            assert self.write(0xD0) and self.write(pointer), 'no acknowledge'
            self.start()
        assert self.write(0xD1), 'no acknowledge'
        out = [self.read(ack=i < count - 1) for i in range(count)]
        self.stop()
        return out


@needs_next
class Lines(NextCase):

    def test_both_lines_idle_high(self):
        zx = bare()
        self.assertEqual((zx.io_in(SCL), zx.io_in(SDA)), (0xFF, 0xFF),
                         'released, pulled up, nothing pulling down (no RTC by default)')

    def test_bit_0_pulls_low_or_releases(self):
        for port in (SCL, SDA):
            with self.subTest(port=f'{port:04X}h'):
                zx = bare()
                got = []
                for v in (0x00, 0xFF, 0xFE, 0x01):
                    zx.io_out(port, v)
                    zx.run_ticks(16)
                    got.append(zx.io_in(port))
                self.assertEqual(got, [0xFE, 0xFF, 0xFE, 0xFF], 'only bit 0 counts (zxnext:3196, 3207)')

    def test_the_lines_are_independent(self):
        zx = bare()
        zx.io_out(SCL, 0)
        zx.run_ticks(16)
        self.assertEqual((zx.io_in(SCL), zx.io_in(SDA)), (0xFE, 0xFF))

    def test_a_reset_releases_both(self):
        zx = bare()
        zx.io_out(SCL, 0)
        zx.io_out(SDA, 0)
        zx.reset()
        zx.run_ticks(2000)
        self.assertEqual((zx.io_in(SCL), zx.io_in(SDA)), (0xFF, 0xFF), 'zxnext:3193-3194, 3204-3205')

    def test_events_record_each_change(self):
        zx = bare()
        zx.run_ticks(100)
        zx.i2c_log(True)
        writes = []
        for port, level in [(SCL, 0), (SDA, 0), (SCL, 1), (SDA, 1), (SDA, 1)]:
            writes.append(zx.t28)
            zx.io_out(port, level)
            zx.run_ticks(50)
        ev = zx.i2c_events
        self.assertEqual([(s, d) for _, s, d in ev], [(0, 1), (0, 0), (1, 0), (1, 1)],
                         'a change of either line, and nothing for a write that changes nothing')
        for (t, _, _), w in zip(ev, writes):
            self.assertTrue(w <= t <= w + 2, f'latched on the next 28 MHz edge: write at {w}, change at {t}')


@needs_next
class RTC(NextCase):

    def rtc(self, when=WHEN):
        zx = bare()
        zx.i2c_rtc(when)
        return zx, Bus(zx)

    def test_no_rtc_no_acknowledge(self):
        zx = bare()
        bus = Bus(zx)
        bus.start()
        self.assertFalse(bus.write(0xD0), 'nothing at 68h by default (ruling 18)')
        bus.stop()

    def test_detached_again(self):
        zx, bus = self.rtc()
        zx.i2c_rtc(False)
        bus.start()
        self.assertFalse(bus.write(0xD0))
        bus.stop()

    def test_it_answers_with_the_time_in_bcd(self):
        """p. 8, Table 2: 00h seconds (CH in b7), 01h minutes, 02h hours (b6 =
        12-hour mode, clear here), 03h day, 04h date, 05h month, 06h year."""
        zx, bus = self.rtc()
        r = bus.read_regs(7, pointer=0)
        self.assertEqual([r[0], r[1], r[2], r[4], r[5], r[6]], [0x30, 0x45, 0x13, 0x06, 0x11, 0x26])
        self.assertIn(r[3], range(1, 8), 'day of week 1-7, user-defined (p. 8)')

    def test_it_counts_emulated_seconds(self):
        """Ruling (e): seconds = master ticks / f_sys, from the attach."""
        zx, bus = self.rtc()
        zx.run_ticks(SECOND * 3 // 2)
        self.assertEqual(bus.read_regs(1, pointer=0), [0x31])
        zx.run_ticks(SECOND)
        self.assertEqual(bus.read_regs(1, pointer=0), [0x32])

    def test_writing_seconds_resets_the_divider(self):
        """'The divider chain is reset whenever the seconds register is
        written' (p. 8): the next tick is a whole second after the write."""
        zx, bus = self.rtc()
        zx.run_ticks(SECOND // 2)
        self.assertEqual(bus.write_regs(0, b'\x10'), [True, True, True])
        zx.run_ticks(SECOND * 9 // 10)
        self.assertEqual(bus.read_regs(1, pointer=0), [0x10], 'not at the old second boundary')
        zx.run_ticks(SECOND // 5)
        self.assertEqual(bus.read_regs(1, pointer=0), [0x11])

    def test_clock_halt_stops_it(self):
        """CH, bit 7 of register 0, disables the oscillator (p. 8)."""
        zx, bus = self.rtc()
        bus.write_regs(0, b'\xA0')
        zx.run_ticks(SECOND * 2)
        self.assertEqual(bus.read_regs(1, pointer=0), [0xA0])

    def test_ram_and_the_pointer_wrap(self):
        """56 bytes of RAM at 08h-3Fh; past 3Fh the pointer wraps to 00h (p. 7)."""
        zx, bus = self.rtc()
        bus.write_regs(0, b'\x87')                      # halted, so register 0 holds still
        data = bytes((i * 29 + 5) & 0xFF for i in range(56))
        self.assertTrue(all(bus.write_regs(0x08, data)))
        self.assertEqual(bus.read_regs(57, pointer=0x08), list(data) + [0x87])

    def test_a_read_starts_where_the_pointer_was_left(self):
        """'If the register pointer is not written to before the initiation of a
        read mode the first address that is read is the last one stored' (p. 12)."""
        zx, bus = self.rtc()
        bus.write_regs(0x05)
        self.assertEqual(bus.read_regs(2), [0x11, 0x26], 'month, year')


if __name__ == '__main__':
    unittest.main()
