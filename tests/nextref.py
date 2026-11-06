"""The Spectrum Next as its documents say it is: reference data for the foil.

Written by Loam Fern from the core 3.02.02 VHDL and Hart's-tongue Fern's survey,
independently of omse-ai's Next core, for tests that check the core through
DESIGN.md §9 only. Nothing here imports the machine.

Citations:
  zxnext:N   cores/zxnext/src/zxnext.vhd, line N, in
             next-build/sources/fpga-30202 (core 3.02.02, Melissa's machine)
  top4:N     cores/zxnext/src/zxnext_top_issue4.vhd
  nr:N       cores/zxnext/nextreg.txt
  ulat:N     cores/zxnext/src/video/zxula_timing.vhd
  §N         next-build/machine/NEXT-MACHINE.md (the survey)
The hardware is by Alvin Albrecht, Victor Trucco, Fabio Belavenuto and others
(GPL v3); this file describes it and copies none of it.
"""
from pathlib import Path

SOURCES = Path.home() / 'next-build/sources/fpga-30202/cores/zxnext'
SURVEY = Path.home() / 'next-build/machine'

# ----------------------------------------------------------------------------
# What nr_read returns right after power-on (boot='bare'), register by register:
# (value, where the value is set, where it is read back). Read back means the
# read mux at zxnext:5789-6194, which is what port 0x253B returns, and which
# can differ from the stored value (NR 0x08, 0x8E, 0xA2).

POWER_ON = {
    0x00: (0x0A, 'top4:35 g_machine_id', 'zxnext:5791-5792'),
    0x01: (0x32, 'top4:37 g_version', 'zxnext:5794-5795'),
    0x02: (0x00, 'zxnext:1090 bus_reset 0; zxnext:1299 reset_type "100" reads 00',
           'zxnext:5797-5798'),
    0x03: (0x33, 'zxnext:1094-1098 timing 011, lock 0, type 011', 'zxnext:5800-5801'),
    0x06: (0xA0, 'zxnext:1102-1108 (hotkey enables b7 and b5)', 'zxnext:5806-5807'),
    0x07: (0x00, 'zxnext:5694, 5708', 'zxnext:5809-5810'),
    0x08: (0x90, 'zxnext:3606/3710 unlocked (b7 reads 1); zxnext:1111 speaker b4',
           'zxnext:5812-5813'),
    0x09: (0x00, 'zxnext:1116-1118 (b2 reads NOT hdmi_audio_en=1)', 'zxnext:5815-5816'),
    0x0A: (0x01, 'zxnext:1119-1122 (mouse dpi 01)', 'zxnext:5818-5819'),
    0x0B: (0x01, 'zxnext:4878-4880', 'zxnext:5821-5822'),
    0x0E: (0x02, 'top4:38 g_sub_version', 'zxnext:5824-5825'),
    0x0F: (0x02, 'top4:39 g_board_issue (issue 4)', 'zxnext:5827-5828'),
    0x10: (0x04, 'zxnext:1127 coreid 00001; no buttons pressed', 'zxnext:5830-5831'),
    0x11: (0x00, 'top4:36 g_video_def; zxnext:1128', 'zxnext:5833-5834'),
    0x12: (0x08, 'zxnext:4882', 'zxnext:5836-5837'),
    0x13: (0x0B, 'zxnext:4883', 'zxnext:5839-5840'),
    0x14: (0xE3, 'zxnext:4885', 'zxnext:5842-5843'),
    0x15: (0x00, 'zxnext:4887-4892', 'zxnext:5845-5846'),
    0x16: (0x00, 'zxnext:4894', 'zxnext:5848-5849'),
    0x17: (0x00, 'zxnext:4896', 'zxnext:5851-5852'),
    0x18: (0x00, 'zxnext:4898-4902 index 0 shows X1 = 0', 'zxnext:5854-5860'),
    0x19: (0x00, 'zxnext:4904-4908', 'zxnext:5862-5868'),
    0x1A: (0x00, 'zxnext:4910-4914', 'zxnext:5870-5876'),
    0x1B: (0x00, 'zxnext:4916-4920', 'zxnext:5878-5884'),
    0x1C: (0x00, 'zxnext:4898-4920 indices 0', 'zxnext:5886-5887'),
    0x20: (0x00, 'no interrupt yet', 'zxnext:5895-5896'),
    0x22: (0x00, 'zxnext:4922-4924; zxnext:3572 port FF 0 (ULA INT on)', 'zxnext:5898-5899'),
    0x23: (0x00, 'zxnext:4924', 'zxnext:5901-5902'),
    0x26: (0x00, 'zxnext:4926', 'zxnext:5904-5905'),
    0x27: (0x00, 'zxnext:4928', 'zxnext:5907-5908'),
    0x28: (0x00, 'zxnext:4950 stored palette value', 'zxnext:5910-5911'),
    0x2F: (0x00, 'zxnext:4930', 'zxnext:5924-5925'),
    0x30: (0x00, 'zxnext:4930', 'zxnext:5927-5928'),
    0x31: (0x00, 'zxnext:4932', 'zxnext:5930-5931'),
    0x32: (0x00, 'zxnext:4934', 'zxnext:5933-5934'),
    0x33: (0x00, 'zxnext:4936', 'zxnext:5936-5937'),
    0x34: (0x00, 'sprites.vhd:598-599 (nextregs.tsv)', 'zxnext:5939-5940'),
    0x40: (0x00, 'zxnext:4938', 'zxnext:5942-5943'),
    0x42: (0x07, 'zxnext:4941', 'zxnext:5948-5949'),
    0x43: (0x00, 'zxnext:4943-4948', 'zxnext:5951-5952'),
    0x4A: (0xE3, 'zxnext:4953', 'zxnext:5957-5958'),
    0x4B: (0xE3, 'zxnext:4955', 'zxnext:5960-5961'),
    0x4C: (0x0F, 'zxnext:4957', 'zxnext:5963-5964'),
    0x50: (0xFF, 'zxnext:4552', 'zxnext:5966-5967'),
    0x51: (0xFF, 'zxnext:4553', 'zxnext:5969-5970'),
    0x52: (0x0A, 'zxnext:4554', 'zxnext:5972-5973'),
    0x53: (0x0B, 'zxnext:4555', 'zxnext:5975-5976'),
    0x54: (0x04, 'zxnext:4556', 'zxnext:5978-5979'),
    0x55: (0x05, 'zxnext:4557', 'zxnext:5981-5982'),
    0x56: (0x00, 'zxnext:4558', 'zxnext:5984-5985'),
    0x57: (0x01, 'zxnext:4559', 'zxnext:5987-5988'),
    0x61: (0x00, 'zxnext:4960', 'zxnext:5990-5991'),
    0x62: (0x00, 'zxnext:4959-4960', 'zxnext:5993-5994'),
    0x64: (0x00, 'zxnext:4963', 'zxnext:5996-5997'),
    0x68: (0x00, 'zxnext:4965-4969 (ULA on reads 0); zxnext:4488', 'zxnext:5999-6000'),
    0x69: (0x00, 'zxnext:3849, 3606, 3572', 'zxnext:6002-6003'),
    0x6A: (0x00, 'zxnext:4971-4973', 'zxnext:6005-6006'),
    0x6B: (0x00, 'zxnext:4975-4976', 'zxnext:6008-6009'),
    0x6C: (0x00, 'zxnext:4978', 'zxnext:6011-6012'),
    0x6E: (0x2C, 'zxnext:4980-4981', 'zxnext:6014-6015'),
    0x6F: (0x0C, 'zxnext:4983-4984', 'zxnext:6017-6018'),
    0x70: (0x00, 'zxnext:4986-4987', 'zxnext:6020-6021'),
    0x71: (0x00, 'zxnext:4989', 'zxnext:6023-6024'),
    0x7F: (0xFF, 'zxnext:1210', 'zxnext:6026-6027'),
    0x80: (0x00, 'zxnext:356, 2144-2145', 'zxnext:6029-6030'),
    0x82: (0xFF, 'zxnext:1219', 'zxnext:6035-6036'),
    0x83: (0xFF, 'zxnext:1220', 'zxnext:6038-6039'),
    0x84: (0xFF, 'zxnext:1221', 'zxnext:6041-6042'),
    0x85: (0x8F, 'zxnext:1222-1223', 'zxnext:6044-6045'),
    0x86: (0xFF, 'zxnext:1224', 'zxnext:6047-6048'),
    0x87: (0xFF, 'zxnext:1225', 'zxnext:6050-6051'),
    0x88: (0xFF, 'zxnext:1226', 'zxnext:6053-6054'),
    0x89: (0x8F, 'zxnext:1227-1228', 'zxnext:6056-6057'),
    0x8A: (0x00, 'zxnext:1229', 'zxnext:6059-6060'),
    0x8C: (0x00, 'zxnext:383, 2213-2214', 'zxnext:6062-6063'),
    0x8E: (0x08, 'zxnext:3606, 3646, 3673 (paging ports 0; b3 reads 1)',
           'zxnext:6065-6066'),
    0x8F: (0x00, 'zxnext:884', 'zxnext:6068-6069'),
    0x90: (0x00, 'zxnext:5014', 'zxnext:6071-6072'),
    0x91: (0x00, 'zxnext:5015', 'zxnext:6074-6075'),
    0x92: (0x00, 'zxnext:5016', 'zxnext:6077-6078'),
    0x93: (0x00, 'zxnext:5017', 'zxnext:6080-6081'),
    0xA0: (0x00, 'zxnext:5019', 'zxnext:6095-6096'),
    0xA2: (0x02, 'zxnext:5020 (b1 reads 1)', 'zxnext:6098-6099'),
    0xA8: (0x00, 'zxnext:5023', 'zxnext:6104-6105'),
    0xB8: (0x83, 'zxnext:5026', 'zxnext:6124-6125'),
    0xB9: (0x01, 'zxnext:5027', 'zxnext:6127-6128'),
    0xBA: (0x00, 'zxnext:5028', 'zxnext:6130-6131'),
    0xBB: (0xCD, 'zxnext:5029', 'zxnext:6133-6134'),
    0xC0: (0x00, 'zxnext:5031-5033; IM 0 snooped', 'zxnext:6136-6137'),
    0xC2: (0x00, 'zxnext:2017', 'zxnext:6139-6140'),
    0xC3: (0x00, 'zxnext:2018', 'zxnext:6142-6143'),
    0xC4: (0x81, 'zxnext:5035 expbus 1; zxnext:6618 ULA INT enabled', 'zxnext:6145-6146'),
    0xC5: (0x00, 'ctc_chan.vhd CTC enables reset', 'zxnext:6148-6149'),
    0xC6: (0x00, 'zxnext:5037-5038', 'zxnext:6151-6152'),
    0xC8: (0x00, 'no interrupt yet', 'zxnext:6154-6155'),
    0xC9: (0x00, 'no interrupt yet', 'zxnext:6157-6158'),
    0xCA: (0x00, 'no interrupt yet', 'zxnext:6160-6161'),
    0xCC: (0x00, 'zxnext:5040-5041', 'zxnext:6163-6164'),
    0xCD: (0x00, 'zxnext:5042', 'zxnext:6166-6167'),
    0xCE: (0x00, 'zxnext:5043-5044', 'zxnext:6169-6170'),
    0xD8: (0x00, 'zxnext:5046', 'zxnext:6172-6173'),
    0xD9: (0x00, 'zxnext:3832', 'zxnext:6175-6176'),
    0xDA: (0x00, 'zxnext:3811', 'zxnext:6178-6179'),
}

# NR 0x05 reads the frame-synced copies of its 50/60 and scandoubler bits
# (eff_nr_05_*, zxnext:6604-6611), which have no declared value: the value is
# settled only once the first frame ends. After that it reads 0x41
# (zxnext:1100-1101 joysticks, 1295-1296 50 Hz and scandoubler on).
NR05_AFTER_FIRST_FRAME = 0x41

# NR 0x81: bit 7 is the expansion bus's ROMCS pin (zxnext:6032), not stored;
# bits 6:0 are zero after power-on (zxnext:1215-1218).
NR81_STORED_MASK = 0x7F

# Registers whose read-back is not a reset value of the core, so not tested as
# one here (with why). Everything else in the read mux is in POWER_ON.
NOT_RESET_VALUES = {
    0x05: 'frame-synced copies; tested after the first frame (NR05_AFTER_FIRST_FRAME)',
    0x1E: 'the beam (cvc), zxnext:5889-5890',
    0x1F: 'the beam (cvc), zxnext:5892-5893',
    0x2C: 'reads the Pi I2S input, not DAC B (zxnext:5913-5915)',
    0x2D: 'reads the latched I2S sample (zxnext:5917-5918)',
    0x2E: 'reads the Pi I2S input, not DAC C (zxnext:5920-5922)',
    0x41: 'reads palette RAM at the index (zxnext:5945-5946)',
    0x44: 'reads palette RAM at the index (zxnext:5954-5955)',
    0x81: 'bit 7 is a bus pin; bits 6:0 checked with NR81_STORED_MASK',
    0x98: 'input pins (zxnext:6083-6084)',
    0x99: 'input pins', 0x9A: 'input pins', 0x9B: 'input pins',
    0xA9: 'ESP GPIO input pins (zxnext:6107-6108)',
    0xB0: 'extended keys (inputs)', 0xB1: 'extended keys (inputs)',
    0xB2: 'pad buttons (inputs)',
    0xF0: 'XDNA/XADC, issue 4 hardware not needed for Spectrum software (§8)',
    0xF8: 'XADC (§8)', 0xF9: 'XADC (§8)', 0xFA: 'XADC (§8)',
}

# Registers that have a read in the mux (zxnext:5789-6194). Every other number,
# including the write-only ones (0x04, 0x29-0x2B, 0x35-0x39, 0x60, 0x63,
# 0x75-0x79, 0xFF), reads 0 ("when others", zxnext:6193-6194).
READ_MUX = sorted(set(POWER_ON) | set(NOT_RESET_VALUES))
READS_ZERO = [r for r in range(256) if r not in READ_MUX]


def read_mux_from_source():
    """The registers in the VHDL's read mux, parsed from the source itself, or
    None if the sources aren't on this machine."""
    f = SOURCES / 'src' / 'zxnext.vhd'
    if not f.exists():
        return None
    lines = f.read_text(errors='replace').splitlines()
    regs = set()
    for line in lines[5788:6194]:                      # zxnext:5789-6194
        s = line.strip()
        if s.startswith('when X"') and s.endswith('=>'):
            regs.add(int(s[7:9], 16))
    return sorted(regs)


# ----------------------------------------------------------------------------
# Writes and how they read back, for registers with no awkward side effects:
# (value written, value read back right after, value after a soft reset).
# 'same' means a soft reset leaves the register alone (no reset branch).
# Settle: registers whose read-back is a frame-synced or idle-synced copy need
# time to pass before the written value shows (see SETTLE).

SCRIBBLE = {
    # reg: (write, read back, after soft reset, why)
    0x05: (0x96, 0x96, 'same', 'joy0 b3,b7,b6 / joy1 b1,b5,b4 / 60 Hz / scandoubler off; '
                               'no reset branch (zxnext:5095-5097, 5738-5760)'),
    0x06: (0x5E, 0x5E, 0xFE, 'soft reset sets b7 and b5 only (zxnext:4871-4872)'),
    0x08: (0x7F, 0xFF, 0xBF, 'b7 write clears the lock (reads 1); b6 resets (zxnext:4874); '
                             'b6 reads the copy taken in the right half of a line'),
    0x09: (0xF5, 0xF5, 0xE5, 'b4 sprite tie resets (zxnext:4876); b3 not written '
                             '(it clears divMMC mapram)'),
    0x0A: (0x9A, 0x9A, 'same', 'mf type b7:6 is config-mode only (bare is in config mode)'),
    0x0B: (0xA0, 0xA0, 0x01, 'zxnext:4878-4880'),
    0x12: (0x20, 0x20, 0x08, 'zxnext:4882'),
    0x13: (0x21, 0x21, 0x0B, 'zxnext:4883'),
    0x14: (0x12, 0x12, 0xE3, 'zxnext:4885'),
    0x15: (0x5B, 0x5B, 0x00, 'zxnext:4887-4892'),
    0x16: (0x12, 0x12, 0x00, 'zxnext:4894'),
    0x17: (0x34, 0x34, 0x00, 'zxnext:4896'),
    0x22: (0x07, 0x07, 0x00, 'zxnext:4922-4924; port FF b6 resets (zxnext:3572)'),
    0x23: (0x55, 0x55, 0x00, 'zxnext:4924'),
    0x26: (0x66, 0x66, 0x00, 'zxnext:4926'),
    0x27: (0x77, 0x77, 0x00, 'zxnext:4928'),
    0x2F: (0x03, 0x03, 0x00, 'zxnext:4930'),
    0x30: (0x45, 0x45, 0x00, 'zxnext:4930'),
    0x31: (0x56, 0x56, 0x00, 'zxnext:4932'),
    0x32: (0x67, 0x67, 0x00, 'zxnext:4934'),
    0x33: (0x78, 0x78, 0x00, 'zxnext:4936'),
    0x40: (0x10, 0x10, 0x00, 'zxnext:4938'),
    0x42: (0x0F, 0x0F, 0x07, 'zxnext:4941'),
    0x43: (0x5A, 0x5A, 0x00, 'zxnext:4943-4948'),
    0x4A: (0x12, 0x12, 0xE3, 'zxnext:4953'),
    0x4B: (0x34, 0x34, 0xE3, 'zxnext:4955'),
    0x4C: (0x05, 0x05, 0x0F, 'zxnext:4957'),
    0x50: (0x10, 0x10, 0xFF, 'zxnext:4552'),
    0x51: (0x11, 0x11, 0xFF, 'zxnext:4553'),
    0x52: (0x12, 0x12, 0x0A, 'zxnext:4554'),
    0x53: (0x13, 0x13, 0x0B, 'zxnext:4555'),
    0x55: (0x15, 0x15, 0x05, 'zxnext:4557'),
    0x56: (0x16, 0x16, 0x00, 'zxnext:4558'),
    0x57: (0x17, 0x17, 0x01, 'zxnext:4559'),
    0x61: (0x33, 0x33, 0x00, 'zxnext:4960'),
    0x62: (0x03, 0x03, 0x00, 'mode 00 (stopped), address MSB 3 (zxnext:4959-4960)'),
    0x64: (0x21, 0x21, 0x00, 'zxnext:4963'),
    0x68: (0x75, 0x75, 0x00, 'b3 (ULA+) not written; zxnext:4965-4969'),
    0x69: (0x41, 0x41, 0x00, 'aliases of ports 123B/7FFD/FF, all reset '
                             '(zxnext:3849, 3606, 3572)'),
    0x6A: (0x35, 0x35, 0x00, 'zxnext:4971-4973'),
    0x6B: (0x81, 0x81, 0x00, 'zxnext:4975-4976'),
    0x6C: (0x42, 0x42, 0x00, 'zxnext:4978'),
    0x6E: (0x90, 0x90, 0x2C, 'zxnext:4980-4981'),
    0x6F: (0x91, 0x91, 0x0C, 'zxnext:4983-4984'),
    0x70: (0x15, 0x15, 0x00, 'zxnext:4986-4987'),
    0x71: (0x01, 0x01, 0x00, 'zxnext:4989'),
    0x7F: (0x55, 0x55, 'same', 'hard reset only (zxnext:1210; §9 D-4)'),
    0x80: (0x03, 0x03, 0x33, 'b7:4 <- b3:0 on reset (zxnext:2144-2145); bus stays off'),
    0x8A: (0x2A, 0x2A, 'same', 'no reset branch (zxnext:1229, 5462)'),
    0x8C: (0x05, 0x05, 0x55, 'b7:4 <- b3:0 on reset (zxnext:2213-2214)'),
    0x8F: (0x02, 0x02, 'same', 'no reset branch (zxnext:884)'),
    0x90: (0x5A, 0x5A, 0x00, 'zxnext:5014'),
    0xA0: (0x39, 0x39, 0x00, 'zxnext:5019; read layout zxnext:6095-6096'),
    0xA2: (0xDD, 0xDF, 0x02, 'b5 reads 0, b1 reads 1 (zxnext:6098-6099)'),
    0xA8: (0x01, 0x01, 0x00, 'zxnext:5023'),
    0xB8: (0x00, 0x00, 0x83, 'zxnext:5026'),
    0xB9: (0x00, 0x00, 0x01, 'zxnext:5027'),
    0xBA: (0x5A, 0x5A, 0x00, 'zxnext:5028'),
    0xBB: (0x00, 0x00, 0xCD, 'zxnext:5029'),
    0xC0: (0xE9, 0xE9, 0x00, 'b2:1 read the snooped IM, still 0 (zxnext:5031-5033)'),
    0xC2: (0x34, 0x34, 0x00, 'zxnext:2017'),
    0xC3: (0x12, 0x12, 0x00, 'zxnext:2018'),
    0xC4: (0x02, 0x02, 0x81, 'b0 writes port FF b6 inverted (zxnext:3579-3580)'),
    0xC5: (0xFF, 0x0F, 0x00, 'four CTC channels: b7:4 read 0 (§9 D-5)'),
    0xC6: (0x77, 0x77, 0x00, 'zxnext:5037-5038'),
    0xCC: (0x83, 0x83, 0x00, 'zxnext:5040-5041'),
    0xCD: (0xFF, 0xFF, 0x00, 'zxnext:5042'),
    0xCE: (0x77, 0x77, 0x00, 'zxnext:5043-5044'),
    0xD9: (0x55, 0x55, 0x00, 'zxnext:3832'),
}

# For checking citations against the source: the signal names a register's
# set-citations must mention (a regular expression), when not simply nr_NN_.
STEMS = {
    0x02: r'nr_02_|reset_type', 0x03: r'nr_03_', 0x07: r'nr_07_|cpu_speed',
    0x08: r'nr_08_|port_7ffd', 0x0A: r'nr_0a_', 0x0B: r'nr_0b_',
    0x10: r'nr_10_', 0x11: r'nr_11_', 0x1C: r'clip_idx', 0x22: r'nr_22_|nr_23_|port_ff_reg',
    0x28: r'nr_stored_palette_value', 0x2F: r'nr_30_', 0x30: r'nr_30_', 0x40: r'nr_palette_idx',
    0x61: r'nr_copper_addr', 0x62: r'nr_62_|nr_copper_addr',
    0x68: r'nr_68_|port_ff3b_ulap_en', 0x69: r'port_123b|port_7ffd|port_ff_reg',
    0x6E: r'nr_6e_', 0x6F: r'nr_6f_',
    0x80: r'nr_80_', 0x85: r'nr_85_', 0x89: r'nr_89_', 0x8C: r'nr_8c_',
    0x8E: r'port_7ffd_reg|port_dffd_reg|port_1ffd_reg', 0xC2: r'nr_c2_', 0xC3: r'nr_c3_',
    0xC4: r'nr_c4_|ula_int_en', 0xD9: r'nr_d9_', 0xDA: r'nr_da_',
    **{0x50 + i: rf'MMU{i}\b' for i in range(8)},
}


# Registers whose read-back is a copy that needs time: NR 0x05's 50/60 and
# scandoubler bits copy at the frame sync (zxnext:6604-6611); NR 0x08 b6 copies
# at an idle CPU edge while hc_ula(8) = 1 (zxnext:5729-5731). Running a whole
# frame after the writes settles both.
SETTLE_FRAMES = 1

# The port-enable groups' soft-reset rule (§4.2; zxnext:4991-5007): NR 0x82-0x85
# go back to all-enabled only if NR 0x85 b7 = 1; NR 0x86-0x89 only if NR 0x89
# b7 = 0, the opposite sense.

# NR 0x02's reset type, read in bits 1:0 (zxnext:1691-1698, 5797-5798): power-on
# 100 reads 00; each soft reset shifts it: 100 -> 010 (reads 10, "hard"),
# then 001 (reads 01, "soft") for ever after.
RESET_TYPE_READS = [0b00, 0b10, 0b01, 0b01]


def reset_type_after(soft_resets):
    """NR 0x02 bits 1:0 after this many soft resets since power-on, by the
    shift at zxnext:1695: new = '0' & t(2) & (t(1) or t(0))."""
    t = 0b100
    for _ in range(soft_resets):
        t = ((t >> 2) & 1) << 1 | ((t >> 1) | t) & 1
    return t & 0b11


# ----------------------------------------------------------------------------
# NR 0x03 (zxnext:5060-5090, read zxnext:5800-5801).

TIMING_CODE = {'48k': 0b001, '128k': 0b010, 'p3': 0b011, 'pentagon': 0b100}


def nr03_timing_written(field):
    """The timing NR 0x03 stores for a written bits 6:4 (zxnext:5064-5071)."""
    return {0b000: 0b001, 0b001: 0b001, 0b010: 0b010, 0b011: 0b011,
            0b100: 0b100}.get(field, 0b011)


def nr03_read(timing, lock, mtype, palette_sub_idx=0):
    return palette_sub_idx << 7 | timing << 4 | lock << 3 | mtype
