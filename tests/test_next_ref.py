"""The foil's own reference, checked: nextref.py against the sources it cites.

These run without any machine. They keep the reference honest: every line it
cites from zxnext.vhd must say what the citation claims, its list of readable
registers must be the VHDL's own read mux, and where it differs from the
survey's register table (machine/nextregs.tsv) the difference must be one it
knows about and explains. A test the machine passes is only as good as the
reference behind it.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextref as ref                                   # noqa: E402

VHDL = ref.SOURCES / 'src' / 'zxnext.vhd'
TSV = ref.SURVEY / 'nextregs.tsv'
CITE = re.compile(r'zxnext:(\d+)(?:-(\d+))?')

# Where the reference deliberately differs from nextregs.tsv's hard_reset column
# (plain hex values only), and why. The survey gives stored values; nr_read
# returns the read mux, which can differ.
KNOWN_TSV_DIFFS = {
    0xA2: 'tsv gives the stored 0x00 and notes "reads b1=1"; the read is 0x02',
}


def vhdl_lines():
    return VHDL.read_text(errors='replace').splitlines() if VHDL.exists() else None


def cites(text):
    for m in CITE.finditer(text):
        a = int(m.group(1))
        yield a, int(m.group(2) or a)


@unittest.skipUnless(VHDL.exists(), f'needs the 3.02.02 VHDL at {VHDL}')
class Citations(unittest.TestCase):
    """Every zxnext: citation says what it claims."""

    def setUp(self):
        self.lines = vhdl_lines()

    def span(self, a, b):
        return '\n'.join(self.lines[a - 1:b])

    def test_read_citations_are_the_registers_read_mux_entries(self):
        bad = []
        for reg, (_, _, rd) in ref.POWER_ON.items():
            for a, b in cites(rd):
                if f'when X"{reg:02X}"' not in self.span(a, b):
                    bad.append(f'NR {reg:#04x}: {rd} has no when X"{reg:02X}"')
        self.assertEqual(bad, [])

    def test_set_citations_name_the_registers_signals(self):
        bad = []
        tables = [(r, v[1]) for r, v in ref.POWER_ON.items()]
        tables += [(r, v[3]) for r, v in ref.SCRIBBLE.items()]
        for reg, text in tables:
            stem = ref.STEMS.get(reg, f'nr_{reg:02x}_')
            for a, b in cites(text):
                span = self.span(a, b)
                if not re.search(stem, span, re.I):
                    bad.append(f'NR {reg:#04x}: zxnext:{a}-{b} never mentions /{stem}/: '
                               f'{span.strip()[:80]!r}')
        self.assertEqual(bad, [])

    def test_the_read_mux_is_the_vhdls(self):
        self.assertEqual(ref.READ_MUX, ref.read_mux_from_source())

    def test_registers_said_to_survive_a_soft_reset_have_no_reset_branch(self):
        branch = self.span(4869, 5050)                   # zxnext:4869-5050, "if reset = '1'"
        bad = []
        for reg, (_, _, after, _) in ref.SCRIBBLE.items():
            stem = ref.STEMS.get(reg, f'nr_{reg:02x}_')
            if after == 'same' and re.search(stem, branch, re.I):
                bad.append(f'NR {reg:#04x} is said to survive, but the reset branch sets it')
        self.assertEqual(bad, [])


class Tables(unittest.TestCase):

    def test_power_on_and_exclusions_cover_the_read_mux_once(self):
        both = set(ref.POWER_ON) & set(ref.NOT_RESET_VALUES)
        self.assertEqual(both, set(), 'a register is both tested and excluded')
        self.assertEqual(len(ref.READ_MUX) + len(ref.READS_ZERO), 256)

    @unittest.skipUnless(TSV.exists(), f'needs the survey table at {TSV}')
    def test_agrees_with_the_surveys_table(self):
        rows = [l.split('\t') for l in TSV.read_text().splitlines()[1:]]
        bad = []
        for row in rows:
            if not row[0].startswith('0x'):
                continue
            reg = int(row[0], 16)
            m = re.match(r'(0x[0-9A-Fa-f]+)\s*($|\()', row[4].strip())
            if reg not in ref.POWER_ON or not m:
                continue
            tsv, mine = int(m.group(1), 16), ref.POWER_ON[reg][0]
            if tsv != mine and reg not in KNOWN_TSV_DIFFS:
                bad.append(f'NR {reg:#04x}: tsv {tsv:#04x}, reference {mine:#04x}')
        self.assertEqual(bad, [])

    def test_all_ram_arithmetic_is_the_p3s_table(self):
        for cfg, banks in ref.ALL_RAM_BANKS.items():
            pages = [p for b in banks for p in (b * 2, b * 2 + 1)]
            self.assertEqual(ref.all_ram_mmu(cfg), pages, f'configuration {cfg:02b}')

    @unittest.skipUnless(VHDL.exists(), f'needs the 3.02.02 VHDL at {VHDL}')
    def test_all_ram_arithmetic_is_transcribed(self):
        text = '\n'.join(vhdl_lines()[4564:4572])        # zxnext:4565-4572
        self.assertIn('MMU0 <= X"0" & (port_1ffd_reg(2) or port_1ffd_reg(1)) & "00" & \'0\'', text)
        self.assertIn('MMU6 <= X"0" & (not(port_1ffd_reg(2)) and port_1ffd_reg(1)) & "11" & \'0\'',
                      text)

    def test_layer2_and_rom_models(self):
        self.assertEqual(ref.layer2_page(8, 0, 0, 0x0000), 16)
        self.assertEqual(ref.layer2_page(8, 3, 0, 0x8000), 20)
        self.assertEqual(ref.layer2_page(8, 1, 2, 0x2000), 23)
        self.assertEqual([ref.rom_for(0b011, f << 4 & 0x10, f << 1 & 0x04) for f in range(4)],
                         [0, 1, 2, 3])
        self.assertEqual(ref.altrom_base(0b001), ref.ALTROM_48)
        self.assertEqual(ref.altrom_base(0b010, 0x00), ref.ALTROM_128)

    def test_int_beam_reproduces_the_surveys_derived_offsets(self):
        for key, want in ref.SURVEY_INT_BEFORE_ROW0.items():
            self.assertEqual(ref.int_tstates_before_row0(*key), want, key)

    def test_frame_figures(self):
        want = {('48k', 50): 69888, ('48k', 60): 59136, ('128k', 50): 70908,
                ('128k', 60): 60192, ('p3', 50): 70908, ('pentagon', 50): 71680}  # §2.2
        for key, t in want.items():
            self.assertEqual(ref.frame_tstates(*key), t, key)

    def test_contention_pattern_is_the_classic_one(self):
        c = ref.Contention('48k', [0xFF, 0xFF, 0x0A, 0x0B, 4, 5, 0, 1], 448, 312)
        self.assertEqual([c.holds(q, 0) for q in range(1, 17, 2)], [0, 6, 5, 4, 3, 2, 1, 0])
        self.assertEqual(c.holds(3, 192), 0, 'border row')
        self.assertEqual(c.holds(259, 0), 0, 'right half of the line')
        self.assertEqual(c.holds(243, 0), 6, 'the last group of the line')
        four = [c.run(3, 0, [('io', p)]) - 4 for p in (0x40FE, 0x80FE, 0x40FF, 0x80FF)]
        # From the first check at the "6" phase: C:1 (6), C:3 at the phase after (0);
        # N:1, C:3 at the next phase (5); C:1 x4: 6, then 0, 6, 0 (12); N:4 (0).
        self.assertEqual(four, [6, 5, 12, 0], 'C:1,C:3 / N:1,C:3 / C:1x4 / N:4')

    def test_the_next_window_is_the_classic_table(self):
        """The Next's rule in hc_ula terms (zxula.vhd) against the documented
        table (docs/contention.md: delay 6,5,4,3,2,1,0,0 from the first
        contended T-state of a line, 128 T a line), on random runs."""
        import random
        rnd = random.Random(1234)
        mmu = [0xFF, 0xFF, 0x0A, 0x0B, 4, 5, 0, 1]
        L, N = 448, 312

        def classic(q, v, events):
            t = 0
            def delay():
                if v >= 192 or q < 3:
                    return 0
                k = (q - 3) // 2
                return [6, 5, 4, 3, 2, 1, 0, 0][k % 8] if k < 128 else 0
            def adv(n):
                nonlocal q, v
                q += 2 * n
                while q >= L:
                    q -= L
                    v = (v + 1) % N
            for e in events:
                steps = []
                if e[0] == 'io':
                    hc = 0x4000 <= e[1] < 0x8000
                    ula = not e[1] & 1
                    steps = ([(True, 1), (True, 3)] if hc and ula else [(True, 1)] * 4 if hc
                             else [(False, 1), (True, 3)] if ula else [(False, 4)])
                else:
                    steps = [(e[0] is not None and 0x4000 <= e[0] < 0x8000, e[1])]
                for check, n in steps:
                    if check:
                        d = delay()
                        t += d
                        adv(d)
                    t += n
                    adv(n)
            return t

        for trial in range(3000):
            q, v = rnd.randrange(1, L, 2), rnd.choice([rnd.randrange(0, 192), rnd.randrange(0, N)])
            ev = [rnd.choice([(0x4000 + rnd.randrange(0x4000), rnd.choice([1, 3, 4])),
                              (0x8000 + rnd.randrange(0x8000), rnd.choice([3, 4])),
                              (None, rnd.randrange(1, 5)),
                              ('io', rnd.choice([0x40FE, 0x80FE, 0x40FF, 0x80FF]))])
                  for _ in range(rnd.randrange(1, 40))]
            c = ref.Contention('48k', mmu, L, N)
            self.assertEqual(c.run(q, v, ev), classic(q, v, ev), f'q={q} v={v} {ev}')

    @unittest.skipUnless(VHDL.exists(), f'needs the 3.02.02 VHDL at {VHDL}')
    def test_contention_window_is_transcribed(self):
        ula = (ref.SOURCES / 'src/video/zxula.vhd').read_text().splitlines()
        self.assertIn('hc_adj <= i_hc(3 downto 0) + 1;', ula[581])
        self.assertIn('(hc_adj(3 downto 2) /= "00")', ula[582])
        self.assertIn("i_hc(8) = '0'", ula[582])

    def test_port_contention_model(self):
        self.assertTrue(ref.port_contended('48k', 0x00FE))
        self.assertFalse(ref.port_contended('48k', 0x7FFD), '7FFD: 128K/+3 timing only')
        self.assertTrue(ref.port_contended('128k', 0x7FFD))
        self.assertTrue(ref.port_contended('128k', 0x3FFD), 'A14 not decoded under 128K')
        self.assertFalse(ref.port_contended('p3', 0x3FFD))
        self.assertFalse(ref.port_contended('128k', 0x1FFD), '1FFD is not 7FFD (zxnext:2552)')

    def test_reset_type_model(self):
        for n, want in enumerate(ref.RESET_TYPE_READS):
            self.assertEqual(ref.reset_type_after(n), want, f'after {n} soft resets')

    def test_scribbles_avoid_the_dangerous_bits(self):
        s = ref.SCRIBBLE
        self.assertFalse(s[0x09][0] & 0x08, 'NR 0x09 b3 would clear divMMC mapram')
        self.assertFalse(s[0x80][0] & 0x80, 'NR 0x80 b7 would turn the expansion bus on')
        self.assertFalse(s[0x80][0] & 0x08, 'NR 0x80 b3 would turn the bus on at the reset')
        self.assertFalse(s[0x68][0] & 0x08, 'NR 0x68 b3 is ULA+ (port FF3B)')
        self.assertFalse(s[0x62][0] & 0xC0, 'NR 0x62 b7:6 would start the copper')
        self.assertNotIn(0x54, s, 'MMU4 holds the parked CPU loop at 0x8000')

    @unittest.skipUnless(VHDL.exists(), f'needs the 3.02.02 VHDL at {VHDL}')
    def test_nr03_timing_model_matches_the_case(self):
        text = '\n'.join(vhdl_lines()[5063:5072])        # zxnext:5064-5072
        for field in range(8):
            want = ref.nr03_timing_written(field)
            if field < 5:
                self.assertIn(f'when "{field:03b}"  => nr_03_machine_timing <= "{want:03b}"',
                              text)
            else:
                self.assertIn(f'when others => nr_03_machine_timing <= "{want:03b}"', text)


if __name__ == '__main__':
    unittest.main()
