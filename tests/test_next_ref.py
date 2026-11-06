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
