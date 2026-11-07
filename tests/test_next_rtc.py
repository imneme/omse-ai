"""The Next's RTC by default (the builder's tests, Kelp Fern), through DESIGN.md §9.1 (18) e as Melissa ruled it on
Sat 7 Nov 2026: "on by default is nice so you get good timestamps on files... the time is time of starting the
program plus emulated time, not actual host time after start."

Next(rtc=...): by default the DS1307 is attached and set to the host's clock when the machine is made, then counts
emulated time only. A set start (an ISO string or a datetime) runs from that instead; rtc=False is a board with no RTC.
Either way an attached clock carries NextZXOS's "ZX" signature in its RAM at 3Eh-3Fh, the bytes NextZXOS's RTC driver
checks before it trusts the time (tbblue/src/asm/rtc/rtcsig.asm:144-148: LD HL,(SIG); LD DE,585Ah, so 3Eh = 'Z',
3Fh = 'X'). The DS1307 keeps a two-digit year, which NextZXOS reads as 20xx (rtcsig.asm:55): 1990 shows as 2090.

Read through the bus as a program would, with Loam Fern's bit-banged master (test_next_i2c.Bus).
"""
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_next_regs import Next, needs_next, NextCase  # noqa: E402
from test_next_i2c import Bus, SECOND  # noqa: E402


def bcd(v):
    return (v >> 4) * 10 + (v & 15)


def clock(zx):
    """(datetime, day of week) as the DS1307's registers say, through the bus."""
    r = Bus(zx).read_regs(7, pointer=0)
    when = datetime.datetime(2000 + bcd(r[6]), bcd(r[5]), bcd(r[4]), bcd(r[2] & 0x3F), bcd(r[1]), bcd(r[0] & 0x7F))
    return when, r[3]


def signature(zx):
    return bytes(Bus(zx).read_regs(2, pointer=0x3E))


@needs_next
class Default(NextCase):

    def test_on_by_default_at_the_hosts_clock(self):
        before = datetime.datetime.now().replace(microsecond=0)
        zx = Next(boot='bare')
        after = datetime.datetime.now()
        when, dow = clock(zx)
        self.assertTrue(before - datetime.timedelta(seconds=1) <= when <= after + datetime.timedelta(seconds=1),
                        f'the host clock when the machine was made: {before} .. {after}, read {when}')
        self.assertEqual(dow, before.isoweekday() % 7 + 1, 'day of week, 1 = Sunday')

    def test_the_signature_is_in_place(self):
        self.assertEqual(signature(Next(boot='bare')), b'ZX', "NextZXOS trusts it (rtcsig.asm:144-148)")

    def test_fast_boot_has_it_too(self):
        try:
            zx = Next(boot='fast')
        except (FileNotFoundError, OSError) as e:      # as test_next_fastboot does without the distribution
            raise unittest.SkipTest(f'boot="fast" needs the ROM images: {e}')
        self.assertEqual(signature(zx), b'ZX')
        self.assertLess(abs((clock(zx)[0] - datetime.datetime.now()).total_seconds()), 10)

    def test_it_counts_emulated_time_not_the_hosts(self):
        # start plus emulated time: 7 emulated seconds on, it reads 7 seconds after the start, however long that took
        zx = Next(boot='bare', rtc='2026-11-07T23:59:55')
        zx.run_ticks(7 * SECOND)
        self.assertEqual(clock(zx)[0], datetime.datetime(2026, 11, 8, 0, 0, 2), 'over midnight, by emulated seconds')


@needs_next
class Options(NextCase):

    def test_a_set_start(self):
        zx = Next(boot='bare', rtc='2001-02-03T04:05:06')
        when, dow = clock(zx)
        self.assertEqual(when, datetime.datetime(2001, 2, 3, 4, 5, 6))
        self.assertEqual(dow, 7, '3 Feb 2001 was a Saturday: 7 with 1 = Sunday')
        self.assertEqual(signature(zx), b'ZX')

    def test_a_datetime_start(self):
        zx = Next(boot='bare', rtc=datetime.datetime(2026, 11, 7, 1, 2, 3))
        self.assertEqual(clock(zx)[0], datetime.datetime(2026, 11, 7, 1, 2, 3))

    def test_1990_keeps_its_two_digits(self):
        # the DS1307's year is 00-99: 1990 is stored as 90, which NextZXOS reads as 2090 (rtcsig.asm:55)
        zx = Next(boot='bare', rtc='1990-01-01T00:00')
        r = Bus(zx).read_regs(7, pointer=0)
        self.assertEqual((r[6], r[5], r[4], r[2], r[1], r[0]), (0x90, 0x01, 0x01, 0x00, 0x00, 0x00))

    def test_no_rtc(self):
        zx = Next(boot='bare', rtc=False)
        bus = Bus(zx)
        bus.start()
        self.assertFalse(bus.write(0xD0), 'rtc=False: nothing at 68h')
        bus.stop()

    def test_a_reset_leaves_the_clock_running(self):
        # the module has its own battery: a soft reset of the Next doesn't touch it
        zx = Next(boot='bare', rtc='2026-11-07T12:00:00')
        zx.run_ticks(3 * SECOND)
        zx.reset()
        zx.run_ticks(2 * SECOND)
        self.assertEqual(clock(zx)[0], datetime.datetime(2026, 11, 7, 12, 0, 5))
        self.assertEqual(signature(zx), b'ZX')


if __name__ == '__main__':
    unittest.main()
