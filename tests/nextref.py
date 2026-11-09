"""The Spectrum Next as its documents say it is: reference data for the foil.

Written by Loam Fern from the core 3.02.02 VHDL and Hart's-tongue Fern's survey,
independently of omse-ai's Next core, for tests that check the core through
DESIGN.md §9 only. Nothing here imports the machine.

Citations:
  zxnext:N   cores/zxnext/src/zxnext.vhd, line N, in core 3.02.02 (the core on
             Melissa O'Neill's Next, which judges this work; docs/next-sources.md)
  top4:N     cores/zxnext/src/zxnext_top_issue4.vhd
  nr:N       cores/zxnext/nextreg.txt
  ulat:N     cores/zxnext/src/video/zxula_timing.vhd
  §N         NEXT-MACHINE.md, Hart's-tongue Fern's survey of the core (not yet
             in this repository)
The hardware is by Alvin Albrecht, Victor Trucco, Fabio Belavenuto and others
(GPL v3); this file describes it and copies none of it.
"""
import os
from pathlib import Path


def setting(name):
    """A folder named by an environment variable, or one that never exists."""
    v = os.environ.get(name)
    return Path(v).expanduser() if v else Path(os.devnull) / name


# For the tests that check citations against the source (docs/next-sources.md): the 3.02.02 core's cores/zxnext
# folder, and the survey's folder. Without them those tests skip and say which is missing.
SOURCES = setting('OMSE_AI_NEXT_VHDL')
SURVEY = setting('OMSE_AI_NEXT_SURVEY')

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
    0x2C: (0x80, 'zxnext:2317 I2S off at reset: pi_audio_L = "10" & X"00"',
           'zxnext:5913-5915'),
    0x2D: (0x00, 'zxnext:2317 the latched low bits of pi_audio are 00', 'zxnext:5917-5918'),
    0x2E: (0x80, 'zxnext:2318 pi_audio_R = "10" & X"00"', 'zxnext:5920-5922'),
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
    0xCA: (0x44, 'both UARTs\' Tx-empty status: their Tx FIFOs are empty through reset, so the first '
                 'clock after it sees a rising request (im2_int_req, zxnext line 1900; im2p:93-101, 156-160); writes clear '
                 '(zxnext:1911-1914)', 'zxnext:6160-6161'),
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
    0x28: r'nr_stored_palette_value', 0x2C: r'pi_audio', 0x2D: r'pi_audio', 0x2E: r'pi_audio', 0x2F: r'nr_30_', 0x30: r'nr_30_', 0x40: r'nr_palette_idx',
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


# ----------------------------------------------------------------------------
# Memory (§3; zxnext:2919-3115, 3597-3760, 4546-4641)

def sram_of_page(page):
    """SRAM address of 8K page N: 0x40000 + N x 0x2000 (zxnext:2921, §3.1)."""
    return 0x40000 + page * 0x2000


ROM_SRAM = [0x0000, 0x4000, 0x8000, 0xC000]   # ROMs 0-3 (zxnext:3009 "00000" & rom & A13)
ALTROM_128 = 0x18000                          # zxnext:3077 "000011" & alt_128_n & A13
ALTROM_48 = 0x1C000
DIVMMC_ROM = 0x10000                          # zxnext:3043 "00001000"
BLOCK_RAM_PAGES = {0x0A: ('bram5', 0x0000), 0x0B: ('bram5', 0x2000), 0x0E: ('bram7', 0x0000)}


def divmmc_ram(bank):
    return 0x20000 + bank * 0x2000            # zxnext:3051 "0001" & divmmc_bank


def all_ram_mmu(cfg):
    """MMU0-7 in all-RAM mode for 1FFD bits 2:1 = cfg, by the arithmetic at
    zxnext:4565-4572 (r2 = 1FFD bit 2, r1 = bit 1)."""
    r2, r1 = cfg >> 1 & 1, cfg & 1
    o, a = r2 | r1, r2 & r1
    m6 = (1 - r2) & r1
    return [o << 3 | 0, o << 3 | 1, o << 3 | a << 2 | 2, o << 3 | a << 2 | 3,
            o << 3 | 4, o << 3 | 5, m6 << 3 | 6, m6 << 3 | 7]


# The +3's own table, 16K banks at 0000/4000/8000/C000 (ports.txt:150-154, whose
# configuration 10 says bank 5 at 0x0000: a typo, see tests-notes.md; the VHDL
# and a real +3 give bank 4).
ALL_RAM_BANKS = {0: (0, 1, 2, 3), 1: (4, 5, 6, 7), 2: (4, 5, 6, 3), 3: (4, 7, 6, 3)}


def layer2_page(base_bank, segment, offset, addr):
    """The 8K page port 0x123B maps addr to (zxnext:2924-2927): segment 3 uses
    A15:14 as the 16K offset; plus the stored bank offset; x2 + A13."""
    seg = (addr >> 14) & 3 if segment == 3 else segment
    return (base_bank + seg + offset) * 2 + (addr >> 13 & 1)


def rom_for(mtype, port_7ffd=0, port_1ffd=0, nr_8c=0):
    """The ROM 0-3 a machine type shows (zxnext:2938-2967)."""
    lock1, lock0 = nr_8c >> 5 & 1, nr_8c >> 4 & 1
    hi, lo = port_1ffd >> 2 & 1, port_7ffd >> 4 & 1
    if mtype == 0b001:                        # 48K
        return 0
    if mtype == 0b011:                        # +3
        return (lock1 << 1 | lock0) if (lock1 or lock0) else (hi << 1 | lo)
    return lock1 if (lock1 or lock0) else lo  # 128K, Pentagon


def altrom_base(mtype, port_7ffd=0, port_1ffd=0, nr_8c=0):
    """Which alternate ROM replaces the ROM (sram_alt_128_n, zxnext:2938-2967)."""
    lock1, lock0 = nr_8c >> 5 & 1, nr_8c >> 4 & 1
    if mtype == 0b001:
        alt_48 = not ((not lock1) and lock0)
    elif mtype == 0b011:
        alt_48 = bool(lock1) if (lock1 or lock0) else bool(port_7ffd >> 4 & 1)
    else:
        alt_48 = bool(lock1) if (lock1 or lock0) else bool(port_7ffd >> 4 & 1)
    return ALTROM_48 if alt_48 else ALTROM_128


# Ports, as decoded (zxnext:2537-2563). 0x3FFD reaches 7FFD only when A14 isn't
# decoded, i.e. not under +3 timing (zxnext:2552).
P7FFD, PDFFD, P1FFD, PEFF7, P123B, PE3 = 0x7FFD, 0xDFFD, 0x1FFD, 0xEFF7, 0x123B, 0x00E3


# ----------------------------------------------------------------------------
# Video timing (§2; zxula_timing.vhd, "ulat")
# (timing, hz): (pixels a line = c_max_hc+1, lines = c_max_vc+1, c_int_h, c_int_v,
#                c_min_hactive, c_min_vactive), each read off the constants.
TIMINGS = {
    ('48k', 50): (448, 312, 116, 0, 128, 64),        # ulat:257-270
    ('48k', 60): (448, 264, 116, 0, 128, 40),        # ulat:285-298
    ('128k', 50): (456, 311, 128, 1, 136, 64),       # ulat:187-204
    ('128k', 60): (456, 264, 128, 0, 136, 40),       # ulat:221-238
    ('p3', 50): (456, 311, 126, 1, 136, 64),         # ulat:189-204
    ('p3', 60): (456, 264, 126, 0, 136, 40),         # ulat:223-238
    ('pentagon', 50): (448, 320, 439, 319, 128, 80),  # ulat:155-168 (always 50 Hz)
}
TICKS_PER_PIXEL = 4                     # 7 MHz pixels of 28 MHz ticks (zxnext:6457-6459)
TICKS_PER_CLOCK = {0: 8, 1: 4, 2: 2, 3: 1}   # 3.5/7/14/28 MHz (top4:1005-1030)
INT_CLOCKS = {'48k': 32, 'p3': 32, '128k': 36, 'pentagon': 36}   # zxnext:1971-2003


def frame_ticks(timing, hz):
    L, N, *_ = TIMINGS[(timing, hz)]
    return L * N * TICKS_PER_PIXEL


def frame_tstates(timing, hz):
    """T-states a frame at 3.5 MHz: two pixels a T-state (§1.2)."""
    L, N, *_ = TIMINGS[(timing, hz)]
    return L * N // 2


def int_beam(timing, hz):
    """(hc_ula, vc_ula) of the ULA interrupt: the match at raw (c_int_h,
    c_int_v) is registered, so it shows the pixel after (ulat:548-556);
    hc_ula = hc - (c_min_hactive - 11), and vc_ula steps when hc_ula wraps
    (ulat:423-453)."""
    L, N, ih, iv, ha, va = TIMINGS[(timing, hz)]
    h = ih + 1
    hc_ula = (h - (ha - 11)) % L
    vc_ula = (iv - va - (0 if h >= ha - 11 else 1)) % N
    return hc_ula, vc_ula


def int_tstates_before_row0(timing, hz):
    """T-states from the ULA interrupt to hc_ula = 0 of row 0 (§2.3, derived)."""
    L, N, *_ = TIMINGS[(timing, hz)]
    h, v = int_beam(timing, hz)
    return ((N - v) * L - h) / 2


# The survey's own derived figures (§2.3), which int_beam must reproduce.
SURVEY_INT_BEFORE_ROW0 = {('48k', 50): 14336, ('128k', 50): 14362, ('p3', 50): 14363,
                          ('pentagon', 50): 17982.5, ('48k', 60): 8960,
                          ('128k', 60): 9118, ('p3', 60): 9119}


def line_int_beam(timing, hz, line, offset=0):
    """(hc_ula, vc_ula) where a line interrupt for `line` shows: the match at
    hc_ula = 255 on cvc = line - 1 (or the last line for 0), registered
    (ulat:561-583); cvc = vc_ula + NR 0x64 offset (ulat:455-472)."""
    L, N, *_ = TIMINGS[(timing, hz)]
    cvc = N - 1 if line == 0 else line - 1
    return 256, (cvc - offset) % N


# ----------------------------------------------------------------------------
# Contention at 3.5 MHz (§1.2, §1.5), in the ULA's own counters.
# The window (zxula.vhd:582-583): hc_adj = hc(3:0) + 1 in 4..15, hc(8) = 0,
# vc in 0..191 (border_active_v, zxula.vhd:414). The clock (top4:994-1003): at
# the end of an odd pixel it goes low unless contended; at the end of an even
# one it goes high. So a T-state starts at an odd hc_ula q, and a contended
# check there is held for each consecutive odd pixel q, q+2, ... whose low
# nibble is 3..13 (q < 256): the classic 6,5,4,3,2,1,0,0, keyed to hc_ula.
# Which T-states are checks (zxula.vhd:589-596): the memory term needs MREQ
# high at the last rising CPU edge, so T1 of each memory cycle and every
# internal T-state; the port term is a contended port's IORQ having just gone
# low, at T2 of its I/O cycle; after that edge IORQ low ends both terms for a
# contended port, while an uncontended port with a contended high byte keeps
# the memory term at T3 and T4: the classic four I/O cases (docs/contention.md).

HOLD_NIBBLES = {3, 5, 7, 9, 11, 13}


def contended_page(timing, page):
    """zxnext:4430-4434."""
    if page >= 0x10:
        return False
    if timing == '48k':
        return page in (0x0A, 0x0B)
    if timing == '128k':
        return bool(page & 0x02)
    if timing == 'p3':
        return bool(page & 0x08)
    return False                                    # Pentagon: zxnext:4422


def port_contended(timing, port):
    """port_contend (zxnext:4437): A0 = 0, 7FFD under 128K/+3 timing, ULA+."""
    if not port & 1:
        return True
    if port in (0xBF3B, 0xFF3B):
        return True
    p7ffd = (not port & 0x8000) and (port & 0x4000 or timing != 'p3') \
        and port & 3 == 1 and not ((port >> 12) & 0xF == 0x1)       # zxnext:2552, 2557
    return bool(p7ffd and timing in ('128k', 'p3'))


class Contention:
    """T-states (held ones included) for a run of bus events at 3.5 MHz,
    from the beam position where the first T-state starts."""

    def __init__(self, timing, mmu, line_len, lines, enabled=True):
        self.timing, self.mmu, self.L, self.N = timing, mmu, line_len, lines
        self.enabled = enabled and timing != 'pentagon'

    def mem(self, addr):
        return contended_page(self.timing, self.mmu[(addr >> 13) & 7])

    def holds(self, q, v):
        if not self.enabled or v >= 192:
            return 0
        k = 0
        while q + 2 * k < 256 and ((q + 2 * k) & 15) in HOLD_NIBBLES:
            k += 1
        return k

    def run(self, q, v, events):
        """events: (addr, n): a check at addr (if contended) then n T-states;
        (None, n): n T-states, no check; ('io', port): an I/O cycle."""
        assert q & 1, f'a 3.5 MHz T-state starts on an odd hc_ula, not {q}'
        total = 0

        def step(check, n):
            nonlocal q, v, total
            for i in range(n):
                if check and i == 0:
                    h = self.holds(q, v)
                    total += h
                    self.advance(2 * h)
                    q, v = self.q, self.v
                total += 1
                self.advance(2)
                q, v = self.q, self.v

        self.q, self.v = q, v
        for e in events:
            if e[0] == 'io':
                port = e[1]
                hc, ula = self.mem(port), port_contended(self.timing, port)
                steps = ([(True, 1), (True, 3)] if hc and ula else
                         [(True, 1)] * 4 if hc else
                         [(False, 1), (True, 3)] if ula else [(False, 4)])
                for check, n in steps:
                    step(check, n)
            else:
                a, n = e
                step(a is not None and self.mem(a), n)
        return total

    def advance(self, pixels):
        self.q += pixels
        while self.q >= self.L:
            self.q -= self.L
            self.v = (self.v + 1) % self.N


# +3 timing (gap #5): WAIT, not a stretched clock (zxula.vhd:600; window 582-583
# with the hc_adj(3:1) = "000" term: hc(3:0) in 3..14, 15, 0). T80N holds T2
# while WAIT_n = 0 at the edge ending T2 (Strobe, z80n/NOTES.md:206-208); that
# edge ends the even pixel p = T1's pixel + 3, so a memory cycle (MREQ low at T2)
# waits once for each consecutive even p, p+2, ... with p & 15 in P3_WAIT.
# Internal T-states and I/O never wait. By T1's phase 1,3,...,15: 7,6,5,4,3,2,1,0,
# the documented +3 pattern 1,0,7,6,5,4,3,2 rotated.
P3_WAIT = {0, 4, 6, 8, 10, 12, 14}


class P3Contention(Contention):

    def waits(self, p, v):
        if not self.enabled or v >= 192:
            return 0
        k = 0
        while p + 2 * k < 256 and ((p + 2 * k) & 15) in P3_WAIT:
            k += 1
        return k

    def run(self, q, v, events):
        assert q & 1, f'a 3.5 MHz T-state starts on an odd hc_ula, not {q}'
        self.q, self.v, total = q, v, 0
        for e in events:
            n = 4 if e[0] == 'io' else e[1]
            if e[0] not in (None, 'io') and n >= 3 and self.mem(e[0]):
                total += 2
                self.advance(4)                     # T1, T2
                w = self.waits(self.q - 1, self.v)  # the even pixel ending T2
                total += w + n - 2
                self.advance(2 * (w + n - 2))
            else:
                total += n
                self.advance(2 * n)
        return total


# The zxnDMA (device/dma.vhd; DESIGN.md §9.1 (16)). Clocked by the CPU clock.
DMA_TIMING = {0b00: 4, 0b01: 3, 0b10: 2, 0b11: 4}      # timing byte bits 1:0 -> clocks (dma:310-324)
DMA_STATUS_IDLE, DMA_STATUS_ENDED = 0x3A, 0x1A          # 00E1101T (dma:902); IDLE clears T (dma:265)


def dma_block_bytes(length, z80_mode=False):
    """Bytes a block moves: LOAD sets the counter to 0 (zxnDMA) or FFFF (Z80 mode),
    WRITE_1 adds one, and WRITE_4 goes on while counter < length, unsigned
    (dma:661-676, 361, 426). So 0 and 1 both move one byte; Z80 mode one more."""
    if z80_mode:
        return length + 1 if length else 1
    return max(length, 1)


def dma_period(r, w, prescaler, m):
    """CPU clocks from one byte's READ_1 entry to the next, in continuous mode
    (the bus kept), for read and write cycles of r and w clocks and m t28 per
    clock (8, 4, 2, 1 at 3.5, 7, 14, 28 MHz). Edge E0 enters READ_1; at E1 the
    timer is cleared (dma:309); after that it gains m a clock (dma:250-255), so
    before edge k it holds m(k-2). WRITE_4 finishes at E(r+w) and waits if
    prescaler > timer(13:5) (dma:424); WAITING_CYCLES leaves at the first edge
    whose timer(13:5) >= prescaler (dma:451) for WAITING_ACK, and READ_1 follows
    one clock later (dma:285-299)."""
    k = r + w
    if not prescaler or (m * (k - 2)) >> 5 >= prescaler:
        return k
    k += 1
    while (m * (k - 2)) >> 5 < prescaler:
        k += 1
    return k + 1


P3_DMA_WAIT = {3, 5, 7, 9, 11, 13, 15}                  # the +3 window (zxula.vhd:583) at odd hc


def p3_dma_run(q, v, cycles, contended, line_len, lines):
    """CPU clocks for DMA bus cycles under +3 timing at 3.5 MHz, from the odd
    hc_ula q where the first starts. cycles: (addr, n clocks); contended(addr).
    The DMA samples WAIT on the CPU clock's falling edge (dma:139-145), the step
    from an odd hc to the even one after it, and tests it in READ_4/WRITE_4
    (dma:342, 410): so an n-clock cycle's sample sees hc q + 2(n-1), and each
    wait clock looks again 2 pixels on. WAIT is MREQ, a contended page and the
    window (zxula.vhd:583, 600): memory only, odd hc 3..15 of each 16, hc < 256,
    rows 0-191. One T-state off the CPU's own sample (the edge ending T2)."""
    assert q & 1
    total = 0
    for addr, n in cycles:
        k = 0
        if addr is not None and contended(addr):
            p, pv = q + 2 * (n - 1), v                  # the sample may be on the next row
            while p >= line_len:                        # (Kelp's catch: hc 455 + 6 is hc 5 below)
                p, pv = p - line_len, (pv + 1) % lines
            if pv < 192:
                while p + 2 * k < 256 and ((p + 2 * k) & 15) in P3_DMA_WAIT:
                    k += 1
        total += n + k
        q += 2 * (n + k)
        while q >= line_len:
            q, v = q - line_len, (v + 1) % lines
    return total


def dma_burst_reads(first, n, r, w, prescaler, m, mcycles, j):
    """READ_1 stamps (cpu_clocks) of an n-byte burst transfer with a due
    prescaler, the first at `first`, while the CPU runs a sled whose M-cycles
    repeat with lengths `mcycles`, frozen at the end of M-cycle j at the first
    grant. Per byte from its READ_1 edge E0: WAITING_CYCLES releases BUSRQ at
    E(r+w+1) (dma:441-447); the T80N samples it at E(r+w+2) and at E(r+w+3)
    drops BUSAK and starts its next M-cycle (t80n:1661-1663, 1738-1752). The
    DMA leaves WAITING at E_k (dma:451), asks again at E(k+1) (dma:269-283);
    the T80N sees it at E(k+2) and grants only where an M-cycle ends, T_Res,
    internal M-cycles too (t80n:1742-1747); READ_1 is the edge after.
    Returns (stamps, the M-cycle index at each later grant)."""
    assert (m * (r + w - 2)) >> 5 < prescaler, 'the prescaler must be due at WRITE_4'
    stamps, grants = [first], []
    for _ in range(n - 1):
        k = r + w + 1
        while (m * (k - 2)) >> 5 < prescaler:
            k += 1
        t = r + w + 3                                   # the CPU's next M-cycle starts here
        while True:
            j = (j + 1) % len(mcycles)
            t += mcycles[j]                             # the edge that ends it
            if t >= k + 3:
                break
        grants.append(j)
        stamps.append(stamps[-1] + t + 1)
    return stamps, grants
