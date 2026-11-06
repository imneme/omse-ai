"""The Spectrum Next's picture as its VHDL draws it: a reference model for the video foil.

Written by Hatch Fern from the core 3.02.02 VHDL, independently of omse-ai's Next core (never read), for
tests that compare `zx.frame9()` (DESIGN.md §9.1 (12)) with what the hardware would show. Nothing here
imports the machine. Give a `Video` the same register writes, port writes and memory a test gives the
machine, and `frame9()` returns the 704 x 288 grid of 9-bit colours the mixer would put out for a static
frame (no mid-frame changes; those need the beam).

Citations (paths under next-build/sources/fpga-30202/cores/zxnext/):
  zxnext:N   src/zxnext.vhd, line N             ula:N    src/video/zxula.vhd
  l2:N       src/video/layer2.vhd               ulat:N   src/video/zxula_timing.vhd
  vdp:N      next-build/sources/tbblue/src/firmware/loader/src/vdp.c (the boot loader's palettes)
The hardware is by Alvin Albrecht, Victor Trucco, Fabio Belavenuto and others (GPL v3); the loader by
Victor Trucco and Fabio Belavenuto. This file describes them and copies none of their code.

Coordinates. frame9 sample (sx, sy): sy 0..287 is paper row py = sy - 48 (48 border lines above and
below, §9.1 (12)); sx 0..703 is 14 MHz samples, two per 7 MHz pixel, starting 48 pixels left of the
paper, so the 7 MHz pixel is phc = sx // 2 - 48 and the half is sx % 2. phc is the "practical" x, 0 at
the first paper pixel (ulat:507-520); the 320 x 256 surface is whc = phc + 32 and wvc = py + 32, both
starting where frame9's rows start (ulat:476-505: phc starts at -48 and whc at -16 on the same tick; wvc
starts at -2 two lines before the line whose wvc is 0, 32 lines above the paper).
"""

# ---------------------------------------------------------------------------- colours

def rgb9_from8(v):
    """An 8-bit RRRGGGBB colour as the palette stores it from NR 0x41 or port 0xFF3B: the ninth (low blue)
    bit is b1 OR b0 (zxnext:4858)."""
    return ((v & 0xFF) << 1) | (((v >> 1) | v) & 1)


# The boot loader's palettes (vdp:52-131): ULA first palette = this 16-colour pattern repeated across all
# 256 entries (two passes of 256 NR 0x41 writes from index 0 and from 128, vdp:58-112); Layer 2 first and
# sprite first palettes = identity, entry i = colour i (set_ordered_palette, vdp:36-50, after NR 0x43 =
# 0x10 and 0x20, vdp:116-127). Afterwards NR 0x43 reads 0x20 and the border is black (vdp:134).
LOADER_ULA16 = [0x00, 0x02, 0xA0, 0xA2, 0x14, 0x16, 0xB4, 0xB6,
                0x00, 0x03, 0xE0, 0xE7, 0x1C, 0x1F, 0xFC, 0xFF]

W, H = 704, 288
L2_SRAM_BASE = 0x40000          # 16K bank B of Layer 2 at SRAM 0x40000 + B * 0x4000 (l2:170-173)


class Video:
    """The video state of a Next: registers, ports, both palette RAMs, and the memories the layers read.

    bram5 (16K) and bram7 (8K) are the block RAMs the ULA reads (zxnext:2920-2921; NEXT-MACHINE §3.11);
    sram (2 MB) is what Layer 2 reads (l2:169-188). Fill them as the test fills the machine.
    """

    def __init__(self, palette='zero'):
        # palette RAMs: 1K x 16 each, entry = priority(15:14) & "00000" & rgb(8:0) (zxnext:6879, 6932).
        # Address: bit 9 = layer (ULA 0 / tilemap 1; Layer 2 0 / sprites 1), bit 8 = second palette,
        # bits 7:0 = index (zxnext:6888, 6940). Power-on content is all zero: no init file (§9.1 (13)).
        self.ulatm = [0] * 1024
        self.l2s = [0] * 1024
        # registers, reset values from zxnext:4882-4969
        self.pal_idx = 0                # NR 0x40 (zxnext:4938)
        self.pal_sub = 0                # NR 0x44's half (zxnext:4939)
        self.pal_stored = 0             # NR 0x44's first byte (zxnext:4950)
        self.nr42 = 0x07                # ULANext format (zxnext:4941)
        self.nr43 = 0x00                # palette control (zxnext:4943-4948)
        self.nr14 = 0xE3                # global transparent colour (zxnext:4885)
        self.nr15 = 0x00                # sprite/layer system (zxnext:4887-4892)
        self.nr4a = 0xE3                # fallback colour (zxnext:4953)
        self.nr12 = 0x08                # Layer 2 active 16K bank (zxnext:4882)
        self.nr16 = 0x00                # Layer 2 scroll x (zxnext:4894); bit 8 from NR 0x71 bit 0
        self.nr71 = 0x00
        self.nr17 = 0x00                # Layer 2 scroll y (zxnext:4896)
        self.nr70 = 0x00                # Layer 2 resolution (5:4) and palette offset (3:0)
        self.nr26 = 0x00                # ULA scroll x (zxnext:4926)
        self.nr27 = 0x00                # ULA scroll y (zxnext:4928)
        self.nr68 = 0x00                # ULA control: b7 ULA off, b6:5 blend, b3 ULA+, b2 fine x, b0 stencil
        self.nr6b = 0x00                # tilemap control (b7 enable): not modelled yet
        self.nr6a = 0x00                # LoRes: b5 Radastan, b4 display-file XOR, b3:0 palette offset (zxnext:4972)
        self.nr32 = 0x00                # LoRes scroll x, y (zxnext:4934-4936)
        self.nr33 = 0x00
        # clip windows: x1, x2, y1, y2 and the write index (zxnext:4898-4920; writes zxnext:5180-5229)
        self.clip = {0x18: [0x00, 0xFF, 0x00, 0xBF], 0x19: [0x00, 0xFF, 0x00, 0xBF],
                     0x1A: [0x00, 0xFF, 0x00, 0xBF], 0x1B: [0x00, 0x9F, 0x00, 0xFF]}
        self.clip_idx = {0x18: 0, 0x19: 0, 0x1A: 0, 0x1B: 0}
        # ports
        self.border = 0                 # port 0xFE bits 2:0 (zxnext:3549-3562)
        self.port_ff = 0x00             # Timex screen mode, bits 5:0 shown (zxnext:3569-3592)
        self.port_7ffd = 0x00           # bit 3 = shadow screen (zxnext:3709); bit 5 locks
        self.l2_en = 0                  # port 0x123B bit 1 (zxnext:3855-3857)
        self.ulap_mode = 0              # port 0xBF3B bits 7:6 (zxnext:4467-4477)
        self.ulap_index = 0             # port 0xBF3B bits 5:0 when mode 00
        self.ulap_en = 0                # port 0xFF3B bit 0 in mode 01, or NR 0x68 bit 3 (zxnext:4482-4494)
        # memory the layers read
        self.bram5 = bytearray(16384)
        self.bram7 = bytearray(8192)
        self.sram = bytearray(2 * 1024 * 1024)
        self.flash = 0                  # flash phase: the ULA's counter bit 4 (ula:470-481), set by the test
        if palette == 'loader':
            self.load_loader_palette()
        elif palette != 'zero':
            raise ValueError(palette)

    # ------------------------------------------------------------------ the palette write path
    def _write_select(self):
        return (self.nr43 >> 4) & 7     # NR 0x43 bits 6:4 (zxnext:5328)

    def _pal_ram_and_addr(self, idx=None):
        """Which RAM a palette write or NR 0x41/0x44 read uses, and the address: bit 9 = select bit 1,
        bit 8 = select bit 2, low byte = the index (zxnext:6859); the ULA/tilemap RAM when select bits 1
        and 0 are equal, else Layer 2/sprites (zxnext:6860, 6864, 6918)."""
        sel = self._write_select()
        b0, b1, b2 = sel & 1, (sel >> 1) & 1, (sel >> 2) & 1
        addr = (b1 << 9) | (b2 << 8) | (self.pal_idx if idx is None else idx)
        return (self.ulatm if b1 == b0 else self.l2s), addr

    def _pal_write(self, rgb9, prio):
        ram, addr = self._pal_ram_and_addr()
        ram[addr] = ((prio & 3) << 14) | (rgb9 & 0x1FF)      # zxnext:6879, 6932

    def _inc_idx(self):
        if not (self.nr43 & 0x80):                         # NR 0x43 bit 7 disables (zxnext:5317, 5338)
            self.pal_idx = (self.pal_idx + 1) & 0xFF

    def nr_write(self, n, v):
        v &= 0xFF
        if n == 0x40:                                       # zxnext:5312-5314
            self.pal_idx, self.pal_sub = v, 0
        elif n == 0x41:                                     # write at the index, then step (zxnext:4857-4859,
            self._pal_write(rgb9_from8(v), 0)               # 5316-5320; the enable is combinational,
            self._inc_idx()                                 # zxnext:4726, so it writes the old index)
            self.pal_sub = 0
        elif n == 0x42:
            self.nr42 = v                                   # zxnext:5324
        elif n == 0x43:
            self.nr43, self.pal_sub = v, 0                  # zxnext:5327-5333
        elif n == 0x44:                                     # two writes: RRRGGGBB, then P..... ..B
            if self.pal_sub == 0:                           # (zxnext:5335-5341, 4857-4859)
                self.pal_stored = v
            else:
                self._pal_write((self.pal_stored << 1) | (v & 1), v >> 6)
                self._inc_idx()
            self.pal_sub ^= 1
        elif n == 0xFF:                                     # the ULA+ palette path also answers a NEXTREG
            ram_addr = (((self.nr43 >> 6) & 1) << 8) | 0xC0 | (self.ulap_index & 0x3F)   # 0xFF (zxnext:4845,
            self.ulatm[ram_addr] = rgb9_from8(v)            # 4858, 4864-4865)
        elif n == 0x14:
            self.nr14 = v                                   # zxnext:5164
        elif n == 0x15:
            self.nr15 = v                                   # zxnext:5167-5172
        elif n == 0x4A:
            self.nr4a = v                                   # zxnext:5345
        elif n == 0x12:
            self.nr12 = v & 0x7F
        elif n == 0x16:
            self.nr16 = v
        elif n == 0x17:
            self.nr17 = v
        elif n == 0x70:
            self.nr70 = v
        elif n == 0x71:
            self.nr71 = v
        elif n in (0x18, 0x19, 0x1A, 0x1B):                 # x1, x2, y1, y2 in turn (zxnext:5180-5214)
            self.clip[n][self.clip_idx[n]] = v
            self.clip_idx[n] = (self.clip_idx[n] + 1) & 3
        elif n == 0x1C:                                     # reset the clip indices (zxnext:5216-5229)
            for bit, reg in enumerate((0x18, 0x19, 0x1A, 0x1B)):
                if v & (1 << bit):
                    self.clip_idx[reg] = 0
        elif n == 0x26:
            self.nr26 = v
        elif n == 0x27:
            self.nr27 = v
        elif n == 0x68:                                     # zxnext:5383-5389; bit 3 also sets ULA+ on/off
            self.nr68 = v                                   # (zxnext:4491-4492)
            self.ulap_en = (v >> 3) & 1
        elif n == 0x69:                                     # Layer 2 enable, shadow screen, Timex mode
            self.l2_en = v >> 7                             # (zxnext:3865-3866, 3575-3576, 3616)
            self.port_7ffd = (self.port_7ffd & ~0x08) | ((v >> 3) & 0x08)
            self.port_ff = (self.port_ff & 0xC0) | (v & 0x3F)
        elif n == 0x6B:
            self.nr6b = v
        elif n == 0x6A:
            self.nr6a = v                                   # zxnext:5392-5396
        elif n == 0x32:
            self.nr32 = v
        elif n == 0x33:
            self.nr33 = v

    def nr_read(self, n):
        """What port 0x253B returns for the registers this model owns (zxnext:5842-5961)."""
        if n == 0x40:
            return self.pal_idx                             # zxnext:5942-5943
        if n == 0x41:                                       # entry bits 8:1 (zxnext:5945-5946)
            ram, addr = self._pal_ram_and_addr()
            return (ram[addr] >> 1) & 0xFF
        if n == 0x44:                                       # priority bits & "00000" & low blue
            ram, addr = self._pal_ram_and_addr()            # (zxnext:5954-5955, 6860)
            e = ram[addr]
            return (((e >> 14) & 3) << 6) | (e & 1)
        return {0x42: self.nr42, 0x43: self.nr43, 0x14: self.nr14, 0x15: self.nr15,
                0x4A: self.nr4a}[n]

    def io_out(self, port, v):
        v &= 0xFF
        lo = port & 0xFF
        if lo & 1 == 0 and lo == 0xFE:                      # border, bits 2:0 (zxnext:3551, 3562)
            self.border = v & 7
        elif port & 0xFFFF == 0xBF3B:                       # ULA+ mode and index (zxnext:4472-4476)
            self.ulap_mode = v >> 6
            if self.ulap_mode == 0:
                self.ulap_index = v & 0x3F
        elif port & 0xFFFF == 0xFF3B:
            if self.ulap_mode == 0:                         # GGGRRRBB reordered to RRRGGGBB, written by
                g, r, b = v >> 5, (v >> 2) & 7, v & 3       # the nextreg stream as register 0xFF
                self.nr_write(0xFF, (r << 5) | (g << 2) | b)   # (zxnext:4682-4686)
            elif self.ulap_mode == 1:
                self.ulap_en = v & 1                        # zxnext:4489-4490
        elif lo == 0xFF:                                    # Timex port (enabled by default, zxnext:2673)
            self.port_ff = v
        elif port & 0xFFFF == 0x7FFD:
            if not (self.port_7ffd & 0x20):                 # locked by bit 5 (zxnext:3710)
                self.port_7ffd = v
        elif port & 0xFFFF == 0x123B:
            if not (v & 0x10):                              # bit 4 = 0: bit 1 shows Layer 2 (zxnext:3855-3857)
                self.l2_en = (v >> 1) & 1

    def load_loader_palette(self):
        """The writes vdp_init makes (vdp:58-127), through the write path above."""
        self.nr_write(0x40, 0)
        for _ in range(16):
            for c in LOADER_ULA16:
                self.nr_write(0x41, c)
        self.nr_write(0x40, 128)
        for _ in range(16):
            for c in LOADER_ULA16:
                self.nr_write(0x41, c)
        for sel in (0x10, 0x20):
            self.nr_write(0x43, sel)
            self.nr_write(0x40, 0)
            for c in range(256):
                self.nr_write(0x41, c)
        self.border = 0

    # ------------------------------------------------------------------ the ULA
    def _ula(self, phc, half, py):
        """One 14 MHz sample of the ULA layer: (index, select_bgnd, border, clipped). index is the 8-bit
        palette index; select_bgnd means "show the fallback colour" (ULANext, ula:492-529)."""
        border = phc < 0 or phc > 255 or py < 0 or py > 191        # ula:414-415 (phc(8), vc(8), vc 192+)
        shadow = (self.port_7ffd >> 3) & 1
        mode = 0 if shadow else (self.port_ff & 7)                  # shadow forces mode 000 (ula:191)
        mem = self.bram7 if shadow else self.bram5
        ulanext = self.nr43 & 1
        ulap = self.ulap_en
        tmx_attr = 0x40 | ((~self.port_ff >> 3) & 7) << 3 | ((self.port_ff >> 3) & 7)   # ula:419
        if mode & 4:
            attr = tmx_attr                                         # hi-res: fixed colours everywhere (ula:426-427)
        elif border:
            attr = (self.border << 3) | self.border                 # ula:418, 428-429
        if border:
            pixel = 0                                               # pixel_en needs not border (ula:470)
        else:
            # scroll: the source sample is the screen sample plus 2 * scroll_x(2:0) + the fine bit, the cell
            # column wraps mod 32 and the row mod 192 (ula:192-216, 353-358, 384-395, 434-455)
            fine = (self.nr68 >> 2) & 1
            t = 2 * phc + half + 2 * self.nr26 + fine               # source sample within a 512-sample row
            t &= 511
            col, within = t >> 4, t & 15
            yy = (py + self.nr27) % 192
            addr_p = ((yy >> 6) << 11) | ((yy & 7) << 8) | (((yy >> 3) & 7) << 5) | col   # ula:223
            base = 0x2000 if mode & 1 else 0
            pbyte = mem[base + addr_p]
            if mode & 2:
                abyte = mem[0x2000 + addr_p]                        # hi-colour/hi-res second file (ula:238-239)
            else:
                abyte = mem[base + 0x1800 + (yy >> 3) * 32 + col]   # attributes (ula:224, 241)
            if mode & 4:                                            # hi-res: 8 samples from each byte (ula:389)
                byte = pbyte if within < 8 else abyte
                pixel = (byte >> (7 - (within & 7))) & 1
            else:                                                   # each bit doubled (ula:390-393)
                pixel = (pbyte >> (7 - (within >> 1))) & 1
                attr = abyte
        flash = (attr >> 7) & self.flash & (1 - ulanext) & (1 - ulap)
        ink = (pixel ^ flash) if not border else 0                  # ula:470
        bgnd = 0
        if ulanext:                                                 # ula:492-529
            fmt = self.nr42
            if border:
                bgnd = 1 if fmt == 0xFF else 0
                index = 0x80 | ((attr >> 3) & 7)
            elif ink:
                index = attr & fmt
            else:
                shifts = {0x01: 1, 0x03: 2, 0x07: 3, 0x0F: 4, 0x1F: 5, 0x3F: 6, 0x7F: 7}
                if fmt in shifts:
                    index = 0x80 | (attr >> shifts[fmt])    # paper base 0x80, then the attribute's top bits
                else:
                    index, bgnd = 0, 1
        elif ulap:                                                  # ula:531-541
            index = 0xC0 | ((attr >> 6) << 4) | ((1 if (mode & 4 or not ink) else 0) << 3) | \
                    ((attr & 7) if ink else ((attr >> 3) & 7))
        else:                                                       # ula:545-553
            index = ((0 if ink else 1) << 4) | (((attr >> 6) & 1) << 3) | \
                    ((attr & 7) if ink else ((attr >> 3) & 7))
        x1, x2, y1, y2 = self.clip[0x1A]
        if y2 >> 6 == 3:
            y2 = 0xBF                                               # zxnext:6686-6690
        inside = (not border) and x1 <= phc <= x2 and y1 <= py <= y2
        clipped = not (inside or border)                            # ula:562
        if self.nr15 & 0x80 and phc >= 0 and py >= 0 and x1 <= phc <= x2 and y1 <= py <= y2:
            # LoRes replaces the ULA's pixel where it's enabled, inside the ULA's clip window (lores:112;
            # zxnext:4199-4202, 6840, 6887); it's never clipped there and never the fallback (zxnext:6894, 6970)
            return self._lores(phc, py), 0, border, False
        return index, bgnd, border, clipped

    def _lores(self, phc, py):
        """LoRes's 8-bit palette index at (phc, py), both inside the paper (lores:80-108)."""
        x = (phc + self.nr32) & 0xFF                                # lores:82
        y = py + self.nr33
        if y >= 192:                                                # lores:86-87
            y = (y - 192) & 0xFF
        off = self.nr6a & 15
        if self.nr6a & 0x20:                                        # Radastan: 4-bit (lores:96, 104-108)
            dfile = (self.port_ff & 1) ^ ((self.nr6a >> 4) & 1)     # zxnext:6703
            byte = self.bram5[(dfile << 13) | ((y >> 1) << 6) | (x >> 2)]
            nib = (byte >> 4) if not (x & 2) else (byte & 15)
            ulap = self.ulap_en and not (self.nr43 & 1)             # zxnext:4185
            high = (0xC | (off & 3)) if ulap else off
            return (high << 4) | nib
        a = ((y >> 1) << 7) | (x >> 1)                              # lores:92-95: rows 96+ at +0x2000
        if y >= 96:
            a += 0x800
        byte = self.bram5[a]
        return ((((byte >> 4) + off) & 15) << 4) | (byte & 15)      # lores:100, 110

    # ------------------------------------------------------------------ Layer 2
    def _layer2(self, phc, half, py):
        """One sample of Layer 2: (index, enabled) where enabled is pixel_en (l2:175, 214)."""
        if not self.l2_en:
            return 0, False
        res = (self.nr70 >> 4) & 3
        wide = res != 0
        if wide:                                                    # whc/wvc (ulat:476-505)
            hc, vc = phc + 32, py + 32
        else:
            hc, vc = phc, py
        # one pixel of SRAM latency is compensated by the +1 (l2:143-148, 177-214): the pixel shown at hc
        # is memory x = hc + scroll, and the clip and range tests apply to hc
        if hc < 0 or vc < 0:
            return 0, False                                         # 9-bit counters: negative is >= 256
        sx = ((self.nr71 & 1) << 8) | self.nr16
        sy = self.nr17
        if not wide:
            if hc > 255 or vc > 191:                                # l2:164-165
                return 0, False
            x = (hc + sx) & 0xFF                                    # l2:152-154 (only x(7:0) is used)
            y = vc + sy
            if y >= 192:                                            # wraps at 192 (l2:156-158)
                y -= 192
            y &= 0xFF
            addr = (y << 8) | x                                     # l2:160
            cx1, cx2 = self.clip[0x18][0], self.clip[0x18][1]
        else:
            if hc > 319 or vc > 255:
                return 0, False
            x = hc + sx                                             # wraps at 320 (l2:152-153)
            if x >= 320:
                x = (x + 192) & 0x1FF
            y = (vc + sy) & 0xFF
            addr = (x << 8) | y                                     # l2:160, column-major
            cx1, cx2 = self.clip[0x18][0] * 2, self.clip[0x18][1] * 2 + 1   # l2:129-135
        cy1, cy2 = self.clip[0x18][2], self.clip[0x18][3]
        if not (cx1 <= hc <= cx2 and cy1 <= vc <= cy2):             # l2:167
            return 0, False
        bank = self.nr12 & 0x7F
        bank_eff = (((bank >> 4) + 1) << 4) | (bank & 15)           # l2:172: +16 banks = SRAM 0x40000
        a = ((bank_eff + (addr >> 14)) << 14) | (addr & 0x3FFF)     # l2:173
        if a >= (1 << 21):
            return 0, False                                         # l2:175 (address bit 21)
        byte = self.sram[a]
        if res & 2:                                                 # 640x256: high nibble first (l2:202)
            pix = (byte >> 4) if half == 0 else (byte & 15)
        else:
            pix = byte
        off = self.nr70 & 15
        pix = ((((pix >> 4) + off) & 15) << 4) | (pix & 15)         # l2:203
        return pix, True

    # ------------------------------------------------------------------ the mixer
    def frame9(self, schedule=None):
        """The 704 x 288 9-bit picture of a static frame, as the mixer makes it (zxnext:6843-7263).

        schedule: optional [(sy, register, value), ...]: next-register writes made in the horizontal
        blanking before frame9 row sy (as a copper WAIT at h = 38-50 does: hc_ula 316-419 lies between
        one row's last visible sample and the next row's first, on 448- and 456-pixel lines), so each
        row is drawn wholly with the registers as they stand when it starts."""
        if self.nr15 & 0x01 or any(n == 0x15 and v & 0x01 for _, n, v in (schedule or [])):
            raise NotImplementedError('sprites are not in the model yet (NR 0x15 bit 0)')
        if self.nr6b & 0x80:
            raise NotImplementedError('the tilemap is not in the model yet (NR 0x6B bit 7)')
        pending = sorted(schedule or [])
        tm_transparent = True                                       # the tilemap is off
        sprite_transparent = True                                   # sprites off (zxnext:6841, 7025)
        out = []
        for sy in range(H):
            while pending and pending[0][0] <= sy:
                _, n, v = pending.pop(0)
                self.nr_write(n, v)
            ula_pal = ((self.nr43 >> 1) & 1) << 8                   # zxnext:6732, 6888
            l2_pal = ((self.nr43 >> 2) & 1) << 8                    # zxnext:6734, 6940
            fallback = (self.nr4a << 1) | (((self.nr4a >> 1) | self.nr4a) & 1)   # zxnext:6897, 7121
            trans = self.nr14
            order = (self.nr15 >> 2) & 7
            ula_en = not (self.nr68 & 0x80)                         # zxnext:5383
            blend = (self.nr68 >> 5) & 3
            # the tilemap is off: "below" = NOT NR 0x6B bit 0 (zxnext:6770, 7016)
            tm_below = not (self.nr6b & 1)
            py = sy - 48
            for sx in range(W):
                phc, half = sx // 2 - 48, sx & 1
                idx, bgnd, border, clipped = self._ula(phc, half, py)
                ula_rgb2 = fallback if bgnd else (self.ulatm[ula_pal | idx] & 0x1FF)   # zxnext:6894-6898
                ula_mix_transparent = ((ula_rgb2 >> 1) == trans) or clipped           # zxnext:7007
                ula_mix_rgb = 0 if ula_mix_transparent else ula_rgb2
                ula_transparent = ula_mix_transparent or not ula_en                   # zxnext:7010
                ula_rgb = 0 if ula_transparent else ula_rgb2
                tm_rgb = 0
                # stencil mode needs the tilemap on (zxnext:7037), so with it off U = ULA (zxnext:7022-7023)
                ula_final_rgb, ula_final_transparent = ula_rgb, ula_transparent and tm_transparent
                if blend == 0:                                                        # zxnext:7048-7084
                    mix_rgb, mix_rgb_t = ula_mix_rgb, ula_mix_transparent
                    mix_top_t, mix_top = tm_transparent or tm_below, tm_rgb
                    mix_bot_t, mix_bot = tm_transparent or not tm_below, tm_rgb
                elif blend == 2:
                    mix_rgb, mix_rgb_t = ula_final_rgb, ula_final_transparent
                    mix_top_t, mix_top, mix_bot_t, mix_bot = True, tm_rgb, True, tm_rgb
                elif blend == 3:
                    mix_rgb, mix_rgb_t = tm_rgb, tm_transparent
                    mix_top_t, mix_top = ula_transparent or not tm_below, ula_rgb
                    mix_bot_t, mix_bot = ula_transparent or tm_below, ula_rgb
                else:
                    mix_rgb, mix_rgb_t = 0, True
                    if tm_below:
                        mix_top_t, mix_top = ula_transparent, ula_rgb
                        mix_bot_t, mix_bot = tm_transparent, tm_rgb
                    else:
                        mix_top_t, mix_top = tm_transparent, tm_rgb
                        mix_bot_t, mix_bot = ula_transparent, ula_rgb
                l2idx, l2en = self._layer2(phc, half, py)
                l2e = self.l2s[l2_pal | l2idx]
                l2_rgb2 = l2e & 0x1FF
                l2_transparent = ((l2_rgb2 >> 1) == trans) or not l2en               # zxnext:7028
                l2_rgb = 0 if l2_transparent else l2_rgb2
                l2_prio = (not l2_transparent) and bool(l2e & 0x8000)                 # zxnext:6946, 7030
                rgb = fallback                                                        # zxnext:7121
                U_t, U = ula_final_transparent, ula_final_rgb
                S_t, S = sprite_transparent, 0
                L_t, L = l2_transparent, l2_rgb
                # the border exception: in the U-over-S orders a sprite shows over the ULA's border
                # where the tilemap is transparent (zxnext:7163, 7173, 7185)
                U_wins = (not U_t) and not (border and tm_transparent and not S_t)
                if order == 0:                                                        # SLU
                    for t, c in ((not l2_prio, L), (S_t, S), (L_t, L), (U_t, U)):
                        if not t:
                            rgb = c
                            break
                elif order == 1:                                                      # LSU
                    for t, c in ((L_t, L), (S_t, S), (U_t, U)):
                        if not t:
                            rgb = c
                            break
                elif order == 2:                                                      # SUL
                    for t, c in ((not l2_prio, L), (S_t, S), (U_t, U), (L_t, L)):
                        if not t:
                            rgb = c
                            break
                elif order == 3:                                                      # LUS
                    if not L_t:
                        rgb = L
                    elif U_wins:
                        rgb = U
                    elif not S_t:
                        rgb = S
                elif order == 4:                                                      # USL
                    if l2_prio:
                        rgb = L
                    elif U_wins:
                        rgb = U
                    elif not S_t:
                        rgb = S
                    elif not L_t:
                        rgb = L
                elif order == 5:                                                      # ULS
                    if l2_prio:
                        rgb = L
                    elif U_wins:
                        rgb = U
                    elif not L_t:
                        rgb = L
                    elif not S_t:
                        rgb = S
                else:                                                                 # 110, 111: blends
                    r = (L >> 6) + (mix_rgb >> 6)                                     # zxnext:7108-7110
                    g = ((L >> 3) & 7) + ((mix_rgb >> 3) & 7)
                    b = (L & 7) + (mix_rgb & 7)
                    if order == 6:                                                    # zxnext:7195-7205
                        r, g, b = min(r, 7), min(g, 7), min(b, 7)
                    elif not mix_rgb_t:                                               # zxnext:7221-7247
                        r, g, b = [0 if q <= 4 else (7 if q >= 12 else q - 5) for q in (r, g, b)]
                    mixed = ((r & 7) << 6) | ((g & 7) << 3) | (b & 7)
                    if l2_prio:
                        rgb = mixed
                    elif not mix_top_t:
                        rgb = mix_top
                    elif not S_t:
                        rgb = S
                    elif not mix_bot_t:
                        rgb = mix_bot
                    elif not L_t:
                        rgb = mixed
                out.append(rgb)
        return W, H, out
