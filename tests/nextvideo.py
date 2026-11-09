"""The Spectrum Next's picture as its VHDL draws it: a reference model for the video foil.

Written by Hatch Fern from the core 3.02.02 VHDL, independently of omse-ai's Next core (never read), for
tests that compare `zx.frame9()` (DESIGN.md §9.1 (12)) with what the hardware would show. Nothing here
imports the machine. Give a `Video` the same register writes, port writes and memory a test gives the
machine, and `frame9()` returns the 704 x 288 grid of 9-bit colours the mixer would put out for a static
frame (no mid-frame changes; those need the beam).

Citations (paths under core 3.02.02's cores/zxnext/; docs/next-sources.md):
  zxnext:N   src/zxnext.vhd, line N             ula:N    src/video/zxula.vhd
  l2:N       src/video/layer2.vhd               ulat:N   src/video/zxula_timing.vhd
  vdp:N      src/firmware/loader/src/vdp.c in the distribution (the boot loader's palettes)
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

    def __init__(self, palette='zero', timing='p3', hz=50):
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
        self.nr6b = 0x00                # tilemap: b7 on, b6 80 columns, b5 strip flags, b4 palette, b3 text,
                                        # b1 512 tiles, b0 always on top (zxnext:4975-4976, 5399-5400)
        self.nr6c = 0x00                # tilemap default attribute (zxnext:4978)
        self.nr6e = 0x2C                # map base: b7 bank 7, b5:0 256-byte offset (zxnext:4980-4981)
        self.nr6f = 0x0C                # tile definitions base, the same shape (zxnext:4983-4984)
        self.nr4c = 0x0F                # tilemap transparent index, 4 bits (zxnext:4957)
        self.tm_scroll_x = 0            # NR 0x2F bits 1:0 and NR 0x30, 10 bits (zxnext:4930, 5268-5272)
        self.nr31 = 0x00                # tilemap scroll y (zxnext:4932)
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
        # sprites: 128 x 5 attribute bytes, 16K of patterns, the port indices (sprites.vhd:321-463, 556-589,
        # 637-745), the transparent index (zxnext:4955)
        self.spr_attr = [[0] * 5 for _ in range(128)]
        self.spr_pat = bytearray(16384)
        self.spr_attr_index = 0
        self.spr_pat_index = 0
        self.mirror_q = 0               # the nextreg mirror's sprite (b6:0) and half bit (b7) (sprites:594-612)
        self.sprite_tie = 0             # NR 0x09 bit 4: nextreg mirror and ports in lockstep (zxnext:5126)
        self.nr4b = 0xE3
        # memory the layers read
        self.bram5 = bytearray(16384)
        self.bram7 = bytearray(8192)
        self.sram = bytearray(2 * 1024 * 1024)
        self.flash = 0                  # flash phase: the ULA's counter bit 4 (ula:470-481), set by the test
        self.timing, self.hz = timing, hz   # for blanking only (§9.1 (14)); bare starts in +3 timing at 50 Hz
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
        elif n == 0x6C:
            self.nr6c = v                                   # zxnext:5403
        elif n == 0x6E:
            self.nr6e = v & 0xBF                            # zxnext:5406-5408
        elif n == 0x6F:
            self.nr6f = v & 0xBF                            # zxnext:5410-5412
        elif n == 0x4C:
            self.nr4c = v & 15                              # zxnext:5351
        elif n == 0x4B:
            self.nr4b = v                                   # zxnext:5348-5349
        elif n == 0x2F:
            self.tm_scroll_x = ((v & 3) << 8) | (self.tm_scroll_x & 0xFF)   # zxnext:5268-5269
        elif n == 0x30:
            self.tm_scroll_x = (self.tm_scroll_x & 0x300) | v               # zxnext:5271-5272
        elif n == 0x31:
            self.nr31 = v                                   # zxnext:5274-5275
        elif n == 0x09:
            self.sprite_tie = (v >> 4) & 1                  # zxnext:5126
        elif n == 0x34:                                     # the mirror's sprite (zxnext:4794; sprites:600-602)
            self.mirror_q = v
            self._mirror_changed()
        elif n in (0x35, 0x36, 0x37, 0x38, 0x39, 0x75, 0x76, 0x77, 0x78, 0x79):
            # attribute byte n - 0x35 of the mirror's sprite (zxnext:4796-4814; sprites:704-715), written on the
            # inverted clock before 0x75-0x79's step lands on the next rising edge (zxnext:4855; sprites:603-606)
            self.spr_attr[self.mirror_q & 0x7F][(n & 0x0F) - 5] = v
            if n & 0x40:
                self.mirror_q = (self.spr_pat_index & 0x80) | ((self.mirror_q + 1) & 0x7F)
                self._mirror_changed()
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
        if n == 0x28:
            return self.pal_stored                          # NR 0x44's first byte (zxnext:5337, 5910-5911)
        if n == 0x34:
            return self.mirror_q & 0x7F                     # zxnext:5939-5940; sprites:614
        if n in (0x18, 0x19, 0x1A, 0x1B):                   # the entry at the clip index (zxnext:5854-5885)
            return self.clip[n][self.clip_idx[n]]
        if n == 0x1C:                                       # the four clip indices (zxnext:5886-5887)
            ci = self.clip_idx
            return (ci[0x1B] << 6) | (ci[0x1A] << 4) | (ci[0x19] << 2) | ci[0x18]
        if n == 0x68:                                       # bit 3 is ULA+'s enable however it was set, bit 1
            return (self.nr68 & 0xF5) | (self.ulap_en << 3) # isn't stored (zxnext:5999-6000)
        if n == 0x69:                                       # zxnext:6002-6003
            return (self.l2_en << 7) | (((self.port_7ffd >> 3) & 1) << 6) | (self.port_ff & 0x3F)
        return {0x12: self.nr12, 0x14: self.nr14, 0x15: self.nr15, 0x16: self.nr16,      # zxnext:5836-5852,
                0x17: self.nr17, 0x26: self.nr26, 0x27: self.nr27,                        # 5904-5908, 5924-5937,
                0x2F: self.tm_scroll_x >> 8, 0x30: self.tm_scroll_x & 0xFF, 0x31: self.nr31,
                0x32: self.nr32, 0x33: self.nr33, 0x42: self.nr42, 0x43: self.nr43,       # 5948-5964,
                0x4A: self.nr4a, 0x4B: self.nr4b, 0x4C: self.nr4c, 0x6A: self.nr6a & 0x3F,
                0x6B: self.nr6b, 0x6C: self.nr6c, 0x6E: self.nr6e, 0x6F: self.nr6f,       # 6005-6024
                0x70: self.nr70 & 0x3F, 0x71: self.nr71 & 1}[n]

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
        elif port & 0xFFFF == 0x303B:                       # sprite and pattern select (sprites:658-661, 728-730)
            self.spr_attr_index = (v & 0x7F) << 3
            self.spr_pat_index = ((v & 0x3F) << 8) | ((v >> 7) << 7)
            self._mirror_follow()
        elif lo == 0x57:                                    # an attribute byte, then the index steps: past byte 4,
            sp, ib = self.spr_attr_index >> 3, self.spr_attr_index & 7   # or byte 3 without bit 6, to the next
            if ib <= 4:                                     # sprite's byte 0 (sprites:637-668, 704-708)
                self.spr_attr[sp][ib] = v
            if (ib & 4) or (ib == 3 and not (v & 0x40)):
                self.spr_attr_index = ((sp + 1) & 0x7F) << 3
                self._mirror_follow()
            else:
                self.spr_attr_index = (self.spr_attr_index + 1) & 0x3FF
        elif lo == 0x5B:                                    # a pattern byte, then the index steps (sprites:713-735)
            self.spr_pat[self.spr_pat_index] = v
            self.spr_pat_index = (self.spr_pat_index + 1) & 0x3FFF
        elif port & 0xFFFF == 0x123B:
            if not (v & 0x10):                              # bit 4 = 0: bit 1 shows Layer 2 (zxnext:3855-3857)
                self.l2_en = (v >> 1) & 1

    def _mirror_follow(self):
        """Lockstep: a change of port 0x57's sprite (a 0x303B write, or the advance to the next sprite) moves
        the mirror's sprite too, its bit 7 from the pattern pointer; the pattern pointer stays (sprites:607-609)."""
        if self.sprite_tie:
            self.mirror_q = (self.spr_pat_index & 0x80) | (self.spr_attr_index >> 3)

    def _mirror_changed(self):
        """Lockstep: a change of the mirror's sprite (NR 0x34, or a 0x75-0x79 step) moves port 0x57's sprite
        and port 0x5B's pattern slot, keeping bit 7 as the 128-byte half (sprites:653-654, 733-734)."""
        if self.sprite_tie:
            q = self.mirror_q
            self.spr_attr_index = (q & 0x7F) << 3
            self.spr_pat_index = ((q & 0x3F) << 8) | (q & 0x80)

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
            ulap = self.ulap_en and not (self.nr43 & 1)             # zxnext:4187
            high = (0xC | (off & 3)) if ulap else off
            return (high << 4) | nib
        a = ((y >> 1) << 7) | (x >> 1)                              # lores:92-95: rows 96+ at +0x2000
        if y >= 96:
            a += 0x800
        byte = self.bram5[a]
        return ((((byte >> 4) + off) & 15) << 4) | (byte & 15)      # lores:100, 110

    # ------------------------------------------------------------------ the tilemap
    def _tm_mem(self, base, sub):
        """A byte the tilemap reads: (sub(13:8) + base(5:0)) mod 64, then sub(7:0), in bank 5 or (base bit 7)
        bank 7's 8K (tilemap:400-403; zxnext:4340-4349, 6567-6571)."""
        a = ((((sub >> 8) + (base & 0x3F)) & 0x3F) << 8) | (sub & 0xFF)
        return self.bram7[a & 0x1FFF] if base & 0x80 else self.bram5[a]

    def _tilemap(self, phc, half, py):
        """One sample of the tilemap: (index, pixel_en, below, textmode) (tilemap:183-446). The surface is
        320 x 256 at whc = phc + 32, wvc = py + 32 (zxnext:4330-4331); the fetch runs a character ahead into a
        double buffer, so the pixel shown at x is the map's pixel at (scroll + x) mod the width."""
        c = self.nr6b
        whc, wvc = phc + 32, py + 32
        x1, x2, y1, y2 = self.clip[0x1B]
        en = (0 <= whc < 320 and 0 <= wvc < 256 and x1 * 2 <= whc <= x2 * 2 + 1 and y1 <= wvc <= y2)  # tilemap:416-424
        mode80 = (c >> 6) & 1                                       # tilemap:189, 228
        width = 640 if mode80 else 320
        tx = whc * 2 + half if mode80 else whc
        abs_x = (self.tm_scroll_x + tx) % width                     # tilemap:309-318 (the corrections are mod W)
        abs_y = (self.nr31 + wvc) & 0xFF                            # tilemap:326
        idx = (abs_y >> 3) * (80 if mode80 else 40) + (abs_x >> 3)  # tilemap:327-328, 395
        if c & 0x20:                                                # strip flags: one byte each (tilemap:396-398)
            tile, attr = self._tm_mem(self.nr6e, idx), self.nr6c    # tilemap:363-367
        else:
            tile, attr = self._tm_mem(self.nr6e, idx * 2), self._tm_mem(self.nr6e, idx * 2 + 1)
        mode512 = (c >> 1) & 1
        tile9 = ((mode512 & attr & 1) << 8) | tile                  # tilemap:393
        if c & 0x08:                                                # text mode: 1 bit, 8 bytes a tile
            byte = self._tm_mem(self.nr6f, (tile9 << 3) | (abs_y & 7))  # tilemap:394
            bit = ((byte << (abs_x & 7)) >> 7) & 1                  # tilemap:385-386
            index, textmode = (attr & 0xFE) | bit, True
            pix_en = en                                             # tilemap:429
        else:
            ex, ey = abs_x & 7, abs_y & 7
            if ((attr >> 3) ^ (attr >> 1)) & 1:                     # rotation inverts the x mirror (tilemap:320-321)
                ex ^= 7
            if (attr >> 2) & 1:                                     # tilemap:322
                ey ^= 7
            if (attr >> 1) & 1:                                     # rotation swaps x and y (tilemap:323-324)
                ex, ey = ey, ex
            byte = self._tm_mem(self.nr6f, (tile9 << 5) | (ey << 2) | (ex >> 1))   # tilemap:394
            nib = (byte >> 4) if not (ex & 1) else (byte & 15)      # tilemap:383
            index, textmode = (attr & 0xF0) | nib, False
            pix_en = en and nib != self.nr4c                        # tilemap:427, 429
        below = bool((attr & 1) | mode512) and not (c & 1)          # tilemap:388
        return index, pix_en, below, textmode

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
    def frame9(self, schedule=None, rows=None, blank=True):
        """The 704 x 288 9-bit picture of a static frame, as the mixer makes it (zxnext:6843-7263).

        schedule: optional [(sy, register, value), ...]: next-register writes made in the horizontal
        blanking before frame9 row sy (as a copper WAIT at h = 38-50 does: hc_ula 316-419 lies between
        one row's last visible sample and the next row's first, on 448- and 456-pixel lines), so each
        row is drawn wholly with the registers as they stand when it starts."""
        import copy
        pending = sorted(schedule or [], key=lambda e: e[0])    # stable: same-row writes keep their order
        spr_pending = list(pending)
        spr_state = copy.deepcopy(self) if pending else self   # render-time state: sprites are drawn in
        spr_lines = None                                        # the line before, so a write before row r
        out = []                                                # reaches them from row r + 1 (sprites:539)
        for sy in range(H):
            while pending and pending[0][0] <= sy:
                _, n, v = pending.pop(0)
                self.nr_write(n, v)
            while spr_pending and spr_pending[0][0] <= sy - 1:
                _, n, v = spr_pending.pop(0)
                spr_state.nr_write(n, v)
                spr_lines = None
            if rows is not None and sy not in rows:
                out.extend([None] * W)
                continue
            ula_pal = ((self.nr43 >> 1) & 1) << 8                   # zxnext:6732, 6888
            l2_pal = ((self.nr43 >> 2) & 1) << 8                    # zxnext:6734, 6940
            fallback = (self.nr4a << 1) | (((self.nr4a >> 1) | self.nr4a) & 1)   # zxnext:6897, 7121
            trans = self.nr14
            order = (self.nr15 >> 2) & 7
            ula_en = not (self.nr68 & 0x80)                         # zxnext:5383
            blend = (self.nr68 >> 5) & 3
            tm_en = bool(self.nr6b & 0x80)                          # zxnext:6727
            tm_pal = 0x200 | (((self.nr6b >> 4) & 1) << 8)          # zxnext:6733, 6888
            stencil = self.nr68 & 1
            if self.nr15 & 1 and spr_lines is None:
                spr_lines = sprite_lines(spr_state)
            spr_win = sprite_window(self)
            spr_pal = 0x200 | (((self.nr43 >> 3) & 1) << 8)          # zxnext:6735, 6940
            py = sy - 48
            for sx in range(W):
                phc, half = sx // 2 - 48, sx & 1
                idx, bgnd, border, clipped = self._ula(phc, half, py)
                ula_rgb2 = fallback if bgnd else (self.ulatm[ula_pal | idx] & 0x1FF)   # zxnext:6894-6898
                ula_mix_transparent = ((ula_rgb2 >> 1) == trans) or clipped           # zxnext:7007
                ula_mix_rgb = 0 if ula_mix_transparent else ula_rgb2
                ula_transparent = ula_mix_transparent or not ula_en                   # zxnext:7010
                ula_rgb = 0 if ula_transparent else ula_rgb2
                if tm_en:
                    tidx, ten, tbelow, ttext = self._tilemap(phc, half, py)
                    tm_rgb2 = self.ulatm[tm_pal | tidx] & 0x1FF                       # zxnext:6909
                    tm_below = tbelow                                                 # zxnext:6770
                    tm_transparent = (not ten) or (ttext and (tm_rgb2 >> 1) == trans)  # zxnext:7016
                else:
                    tm_rgb2, tm_below, tm_transparent = 0, not (self.nr6b & 1), True  # zxnext:6770, 7016
                tm_rgb = 0 if tm_transparent else tm_rgb2                             # zxnext:7017
                ulatm_transparent = ula_transparent and tm_transparent                # zxnext:7022
                ulatm_rgb = tm_rgb if (not tm_transparent and (not tm_below or ula_transparent)) else ula_rgb
                if stencil and ula_en and tm_en:                                      # zxnext:7019-7020, 7037
                    st_t = ula_transparent or tm_transparent
                    ula_final_rgb, ula_final_transparent = (0 if st_t else (ula_rgb & tm_rgb)), st_t
                else:
                    ula_final_rgb, ula_final_transparent = ulatm_rgb, ulatm_transparent
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
                S_t, S = True, 0
                if self.nr15 & 1:                                                     # zxnext:6726, 6841
                    whc, wvc = phc + 32, py + 32
                    xs_, xe_, ys_, ye_, ymax = spr_win
                    if 0 <= whc < 320 and 0 <= wvc < min(256, ymax) and xs_ <= whc <= xe_ and ys_ <= wvc <= ye_:
                        p = spr_lines[wvc][whc]
                        if p is not None:                                             # sprites:1066-1067
                            S_t, S = False, self.l2s[spr_pal | p] & 0x1FF             # zxnext:6958, 7025-7026
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
        if blank:
            out = [0 if (b and x is not None) else x for x, b in zip(out, blank_mask(self))]
        else:                                   # the mixer's colour wherever a line exists, 0 where none does
            out = [0 if (x is not None and no_line(self, i // W)) else x for i, x in enumerate(out)]
        return W, H, out


# ---------------------------------------------------------------------------- the same, in numpy

def _np():
    import numpy as np
    return np


def frame9_np(v, schedule=None, blank=True):
    """frame9 computed over the whole grid at once: the same rules as Video.frame9 (which is the cited
    reading; test_next_video.ModelSense checks the two agree), about a hundred times faster. A schedule
    splits the frame into row segments, each drawn with the registers as they stand."""
    np = _np()
    import copy
    pending = sorted(schedule or [], key=lambda e: e[0])    # stable: same-row writes keep their order
    spr_pending = list(pending)
    out = np.zeros((H, W), dtype=np.int32)
    cur = copy.deepcopy(v)
    spr_cur = copy.deepcopy(v) if pending else cur      # render-time: each write a row later (Video.frame9)
    bounds = sorted({r for r, _, _ in pending} | {r + 1 for r, _, _ in pending} | {H})
    start = 0
    for stop in bounds:
        while pending and pending[0][0] <= start:
            _, n, val = pending.pop(0)
            cur.nr_write(n, val)
        while spr_pending and spr_pending[0][0] <= start - 1:
            _, n, val = spr_pending.pop(0)
            spr_cur.nr_write(n, val)
        if stop > start:
            out[start:min(stop, H)] = _frame_np(cur, spr_cur)[start:min(stop, H)]
        start = stop
    if blank:
        out = np.where(np.array(blank_mask(v)).reshape(H, W), 0, out)
    else:
        for sy in range(H):
            if no_line(v, sy):
                out[sy] = 0
    return W, H, out.ravel().tolist()


def _frame_np(v, spr_v=None):
    np = _np()
    sy, sx = np.mgrid[0:H, 0:W]
    phc, half, py = sx // 2 - 48, sx & 1, sy - 48
    ulatm = np.array(v.ulatm, dtype=np.int32)
    l2s = np.array(v.l2s, dtype=np.int32)
    b5 = np.frombuffer(bytes(v.bram5), dtype=np.uint8).astype(np.int32)
    b7 = np.frombuffer(bytes(v.bram7), dtype=np.uint8).astype(np.int32)
    # ---- the ULA (Video._ula)
    border = (phc < 0) | (phc > 255) | (py < 0) | (py > 191)
    shadow = (v.port_7ffd >> 3) & 1
    mode = 0 if shadow else (v.port_ff & 7)
    mem = b7 if shadow else b5
    ulanext, ulap = v.nr43 & 1, v.ulap_en
    tmx = 0x40 | (((~v.port_ff >> 3) & 7) << 3) | ((v.port_ff >> 3) & 7)
    fine = (v.nr68 >> 2) & 1
    t = (2 * phc + half + 2 * v.nr26 + fine) & 511
    col, within = t >> 4, t & 15
    yy = (np.clip(py, 0, 191) + v.nr27) % 192
    addr_p = ((yy >> 6) << 11) | ((yy & 7) << 8) | (((yy >> 3) & 7) << 5) | col
    base = 0x2000 if mode & 1 else 0
    memx = np.concatenate([mem, np.zeros(0x4000, dtype=np.int32)])     # bank 7 is 8K; stay in range
    pbyte = memx[base + addr_p]
    abyte = memx[0x2000 + addr_p] if mode & 2 else memx[base + 0x1800 + (yy >> 3) * 32 + col]
    if mode & 4:
        byte = np.where(within < 8, pbyte, abyte)
        pixel = (byte >> (7 - (within & 7))) & 1
        attr = np.full_like(phc, tmx)
    else:
        pixel = (pbyte >> (7 - (within >> 1))) & 1
        attr = np.where(border, (v.border << 3) | v.border, abyte)
    pixel = np.where(border, 0, pixel)
    flash = (attr >> 7) & v.flash & (1 - ulanext) & (1 - ulap)
    ink = np.where(border, 0, pixel ^ flash)
    bgnd = np.zeros_like(phc)
    paper_c, ink_c = (attr >> 3) & 7, attr & 7
    if ulanext:
        fmt = v.nr42
        shifts = {0x01: 1, 0x03: 2, 0x07: 3, 0x0F: 4, 0x1F: 5, 0x3F: 6, 0x7F: 7}
        if fmt in shifts:
            paper_i, paper_bg = 0x80 | (attr >> shifts[fmt]), 0
        else:
            paper_i, paper_bg = 0, 1
        index = np.where(border, 0x80 | paper_c, np.where(ink == 1, attr & fmt, paper_i))
        bgnd = np.where(border, 1 if fmt == 0xFF else 0, np.where(ink == 1, 0, paper_bg))
    elif ulap:
        hi = np.where((mode & 4) | (ink == 0), 1, 0)
        index = 0xC0 | ((attr >> 6) << 4) | (hi << 3) | np.where(ink == 1, ink_c, paper_c)
    else:
        index = (np.where(ink == 1, 0, 1) << 4) | (((attr >> 6) & 1) << 3) | np.where(ink == 1, ink_c, paper_c)
    x1, x2, y1, y2 = v.clip[0x1A]
    if y2 >> 6 == 3:
        y2 = 0xBF
    win = (phc >= x1) & (phc <= x2) & (py >= y1) & (py <= y2)
    inside = ~border & win
    clipped = ~(inside | border)
    if v.nr15 & 0x80:                                       # LoRes (Video._lores)
        lon = (phc >= 0) & (py >= 0) & win
        x = (np.clip(phc, 0, 255) + v.nr32) & 0xFF
        y = np.clip(py, 0, 191) + v.nr33
        y = np.where(y >= 192, (y - 192) & 0xFF, y)
        off = v.nr6a & 15
        if v.nr6a & 0x20:
            dfile = (v.port_ff & 1) ^ ((v.nr6a >> 4) & 1)
            byte = b5[(dfile << 13) | ((y >> 1) << 6) | (x >> 2)]
            nib = np.where(x & 2, byte & 15, byte >> 4)
            high = (0xC | (off & 3)) if (v.ulap_en and not (v.nr43 & 1)) else off
            lidx = (high << 4) | nib
        else:
            a = ((y >> 1) << 7) | (x >> 1)
            a = np.where(y >= 96, a + 0x800, a)
            byte = b5[a]
            lidx = ((((byte >> 4) + off) & 15) << 4) | (byte & 15)
        index = np.where(lon, lidx, index)
        bgnd = np.where(lon, 0, bgnd)
        clipped = np.where(lon, False, clipped)
    # ---- Layer 2 (Video._layer2)
    l2idx = np.zeros_like(phc)
    l2en = np.zeros(phc.shape, dtype=bool)
    if v.l2_en:
        res = (v.nr70 >> 4) & 3
        wide = res != 0
        hc, vc = (phc + 32, py + 32) if wide else (phc, py)
        sxr = ((v.nr71 & 1) << 8) | v.nr16
        if not wide:
            ok = (hc >= 0) & (vc >= 0) & (hc <= 255) & (vc <= 191)
            x = (hc + sxr) & 0xFF
            y = vc + v.nr17
            y = np.where(y >= 192, y - 192, y) & 0xFF
            addr = (y << 8) | x
            cx1, cx2 = v.clip[0x18][0], v.clip[0x18][1]
        else:
            ok = (hc >= 0) & (vc >= 0) & (hc <= 319) & (vc <= 255)
            x = hc + sxr
            x = np.where(x >= 320, (x + 192) & 0x1FF, x)
            y = (vc + v.nr17) & 0xFF
            addr = (x << 8) | y
            cx1, cx2 = v.clip[0x18][0] * 2, v.clip[0x18][1] * 2 + 1
        cy1, cy2 = v.clip[0x18][2], v.clip[0x18][3]
        ok &= (hc >= cx1) & (hc <= cx2) & (vc >= cy1) & (vc <= cy2)
        bank = v.nr12 & 0x7F
        bank_eff = (((bank >> 4) + 1) << 4) | (bank & 15)
        a = ((bank_eff + (np.clip(addr, 0, None) >> 14)) << 14) | (np.clip(addr, 0, None) & 0x3FFF)
        ok &= a < (1 << 21)
        sram = np.frombuffer(bytes(v.sram), dtype=np.uint8).astype(np.int32)
        byte = sram[np.where(ok, a, 0)]
        pix = np.where(half == 0, byte >> 4, byte & 15) if res & 2 else byte
        off = v.nr70 & 15
        pix = ((((pix >> 4) + off) & 15) << 4) | (pix & 15)
        l2idx, l2en = np.where(ok, pix, 0), ok
    # ---- the tilemap (Video._tilemap)
    tm_en = bool(v.nr6b & 0x80)
    trans = v.nr14
    fallback = (v.nr4a << 1) | (((v.nr4a >> 1) | v.nr4a) & 1)
    ula_rgb2 = np.where(bgnd == 1, fallback, ulatm[(((v.nr43 >> 1) & 1) << 8) | index] & 0x1FF)
    ula_mix_t = ((ula_rgb2 >> 1) == trans) | clipped
    ula_mix_rgb = np.where(ula_mix_t, 0, ula_rgb2)
    ula_en = not (v.nr68 & 0x80)
    ula_t = ula_mix_t | (not ula_en)
    ula_rgb = np.where(ula_t, 0, ula_rgb2)
    if tm_en:
        c = v.nr6b
        whc, wvc = phc + 32, py + 32
        cx1, cx2, cy1, cy2 = v.clip[0x1B]
        en = (whc >= 0) & (whc < 320) & (wvc >= 0) & (wvc < 256) & (whc >= cx1 * 2) & (whc <= cx2 * 2 + 1) & \
             (wvc >= cy1) & (wvc <= cy2)
        mode80 = (c >> 6) & 1
        width = 640 if mode80 else 320
        tx = whc * 2 + half if mode80 else whc
        abs_x = np.mod(v.tm_scroll_x + tx, width)
        abs_y = (v.nr31 + wvc) & 0xFF
        idx = (abs_y >> 3) * (80 if mode80 else 40) + (abs_x >> 3)

        def tmm(base, sub):
            a = ((((sub >> 8) + (base & 0x3F)) & 0x3F) << 8) | (sub & 0xFF)
            return b7[a & 0x1FFF] if base & 0x80 else b5[a]
        if c & 0x20:
            tile, tattr = tmm(v.nr6e, idx), np.full_like(idx, v.nr6c)
        else:
            tile, tattr = tmm(v.nr6e, idx * 2), tmm(v.nr6e, idx * 2 + 1)
        mode512 = (c >> 1) & 1
        tile9 = ((mode512 & tattr & 1) << 8) | tile
        if c & 0x08:
            byte = tmm(v.nr6f, (tile9 << 3) | (abs_y & 7))
            bit = ((byte << (abs_x & 7)) >> 7) & 1
            tidx, ttext, ten = (tattr & 0xFE) | bit, True, en
        else:
            ex, ey = abs_x & 7, abs_y & 7
            ex = np.where(((tattr >> 3) ^ (tattr >> 1)) & 1, ex ^ 7, ex)
            ey = np.where((tattr >> 2) & 1, ey ^ 7, ey)
            rot = (tattr >> 1) & 1
            ex, ey = np.where(rot == 1, ey, ex), np.where(rot == 1, ex, ey)
            byte = tmm(v.nr6f, (tile9 << 5) | (ey << 2) | (ex >> 1))
            nib = np.where(ex & 1, byte & 15, byte >> 4)
            tidx, ttext, ten = (tattr & 0xF0) | nib, False, en & (nib != v.nr4c)
        tm_below = (((tattr & 1) | mode512) != 0) & (not (c & 1))
        tm_rgb2 = ulatm[0x200 | (((c >> 4) & 1) << 8) | tidx] & 0x1FF
        tm_t = ~ten | (ttext & ((tm_rgb2 >> 1) == trans))
    else:
        tm_rgb2 = np.zeros_like(phc)
        tm_below = np.full(phc.shape, not (v.nr6b & 1))
        tm_t = np.ones(phc.shape, dtype=bool)
    tm_rgb = np.where(tm_t, 0, tm_rgb2)
    ulatm_t = ula_t & tm_t
    ulatm_rgb = np.where(~tm_t & (~tm_below | ula_t), tm_rgb, ula_rgb)
    if (v.nr68 & 1) and ula_en and tm_en:
        st_t = ula_t | tm_t
        U, U_t = np.where(st_t, 0, ula_rgb & tm_rgb), st_t
    else:
        U, U_t = ulatm_rgb, ulatm_t
    blend = (v.nr68 >> 5) & 3
    if blend == 0:
        mix_rgb, mix_t = ula_mix_rgb, ula_mix_t
        top_t, top, bot_t, bot = tm_t | tm_below, tm_rgb, tm_t | ~tm_below, tm_rgb
    elif blend == 2:
        mix_rgb, mix_t = U, U_t
        top_t, top, bot_t, bot = np.ones_like(tm_t), tm_rgb, np.ones_like(tm_t), tm_rgb
    elif blend == 3:
        mix_rgb, mix_t = tm_rgb, tm_t
        top_t, top, bot_t, bot = ula_t | ~tm_below, ula_rgb, ula_t | tm_below, ula_rgb
    else:
        mix_rgb, mix_t = np.zeros_like(phc), np.ones_like(tm_t)
        top_t = np.where(tm_below, ula_t, tm_t)
        top = np.where(tm_below, ula_rgb, tm_rgb)
        bot_t = np.where(tm_below, tm_t, ula_t)
        bot = np.where(tm_below, tm_rgb, ula_rgb)
    l2e = l2s[(((v.nr43 >> 2) & 1) << 8) | l2idx]
    l2_rgb2 = l2e & 0x1FF
    L_t = ((l2_rgb2 >> 1) == trans) | ~l2en
    L = np.where(L_t, 0, l2_rgb2)
    prio = ~L_t & ((l2e & 0x8000) != 0)
    S_t = np.ones_like(L_t)
    S = np.zeros_like(phc)
    if v.nr15 & 1:
        buf = np.full((256, 320), -1, dtype=np.int32)
        for i, line in enumerate(sprite_lines(spr_v or v)):
            buf[i] = [-1 if q is None else q for q in line]
        xs_, xe_, ys_, ye_, ymax = sprite_window(v)
        whc, wvc = phc + 32, py + 32
        inwin = (whc >= 0) & (whc < 320) & (wvc >= 0) & (wvc < min(256, ymax)) & \
                (whc >= xs_) & (whc <= xe_) & (wvc >= ys_) & (wvc <= ye_)
        p = buf[np.clip(wvc, 0, 255), np.clip(whc, 0, 319)]
        S_t = ~(inwin & (p >= 0))
        S = np.where(S_t, 0, l2s[0x200 | (((v.nr43 >> 3) & 1) << 8) | np.clip(p, 0, 255)] & 0x1FF)
    U_wins = ~U_t & ~(border & tm_t & ~S_t)
    order = (v.nr15 >> 2) & 7

    def first(pairs):
        conds = [~t_ for t_, _ in pairs]
        return np.select(conds, [c_ for _, c_ in pairs], default=fallback)
    if order == 0:
        rgb = first([(~prio, L), (S_t, S), (L_t, L), (U_t, U)])
    elif order == 1:
        rgb = first([(L_t, L), (S_t, S), (U_t, U)])
    elif order == 2:
        rgb = first([(~prio, L), (S_t, S), (U_t, U), (L_t, L)])
    elif order == 3:
        rgb = first([(L_t, L), (~U_wins, U), (S_t, S)])
    elif order == 4:
        rgb = first([(~prio, L), (~U_wins, U), (S_t, S), (L_t, L)])
    elif order == 5:
        rgb = first([(~prio, L), (~U_wins, U), (L_t, L), (S_t, S)])
    else:
        r = (L >> 6) + (mix_rgb >> 6)
        g = ((L >> 3) & 7) + ((mix_rgb >> 3) & 7)
        b = (L & 7) + (mix_rgb & 7)
        if order == 6:
            r, g, b = np.minimum(r, 7), np.minimum(g, 7), np.minimum(b, 7)
        else:
            def adj(q):
                return np.where(q <= 4, 0, np.where(q >= 12, 7, q - 5))
            r = np.where(mix_t, r, adj(r))
            g = np.where(mix_t, g, adj(g))
            b = np.where(mix_t, b, adj(b))
        mixed = ((r & 7) << 6) | ((g & 7) << 3) | (b & 7)
        rgb = first([(~prio, mixed), (top_t, top), (S_t, S), (bot_t, bot), (L_t, mixed)])
    return rgb


# ---------------------------------------------------------------------------- blanking (§9.1 (14))

TIMING = {  # c_min_hactive, c_max_hblank, {hz: (lines, c_min_vactive, c_hdmi_ymin, c_hdmi_ymax)}, c_max_vblank
    '48k': (128, 95, {50: (312, 64, 16, 303), 60: (264, 40, 16, 255)}, 7),
    '128k': (136, 95, {50: (311, 64, 16, 303), 60: (264, 40, 16, 255)}, 7),
    'p3': (136, 95, {50: (311, 64, 16, 303), 60: (264, 40, 16, 255)}, 7),
    'pentagon': (128, 63, {50: (320, 80, 24, 311)}, 15),
}   # zxula_timing.vhd:147-312 (the timings and HDMI's window), 351-356 (blank_n); NEXT-MACHINE §2.2
# HDMI's x window (c_hdmi_xmin/xmax) covers every frame9 column at every timing (frame9 stops 8 pixels short of
# its right edge), so only its y window matters here.


def frame_vc(v, sy):
    """The raw vc that frame9 row sy shows: the paper's first line is row 48 at every rate (§9.1 (12), ruling
    Sat 7 Nov), so vc = sy - 48 + c_min_vactive, unwrapped; outside 0..lines-1 the row has no line."""
    _, _, lines_by_hz, _ = TIMING[v.timing]
    lines, first, _, _ = lines_by_hz[v.hz]
    return sy - 48 + first


def no_line(v, sy):
    lines = TIMING[v.timing][2][v.hz][0]
    vc = frame_vc(v, sy)
    return vc < 0 or vc >= lines


def blank_mask(v):
    """True where frame9's sample is black on the Next's HDMI output (§9.1 (14), ruling Sat 7 Nov: frame9 is
    the HDMI picture): inside blanking (zxula_timing:351-356, zxnext:7311-7315; the blank signal travels the
    pipeline beside the pixels, zxnext:6789-6792, 7274-7287), outside HDMI's y window (c_hdmi_ymin/ymax), or on
    a row with no line. Raw hc = phc + c_min_hactive; raw vc from frame_vc."""
    cmin, hb_end, lines_by_hz, vb_end = TIMING[v.timing]
    lines, first, ymin, ymax = lines_by_hz[v.hz]
    out = []
    for sy in range(H):
        vc = frame_vc(v, sy)
        row_black = vc < 0 or vc >= lines or vc < ymin or vc > ymax or vc <= vb_end
        for sx in range(W):
            raw_hc = sx // 2 - 48 + cmin
            out.append(row_black or raw_hc <= hb_end)
    return out


# ---------------------------------------------------------------------------- sprites

LINE_HC = {'48k': 448, '128k': 456, 'p3': 456, 'pentagon': 448}   # c_max_hc + 1 (ulat:160, 196, 230, 262, 290)


def sprite_budget(v):
    """28 MHz cycles from one line reset to the next: whc reaches 511 once a line (ulat:476-490, sprites:517),
    and CLK_28 is four CLK_7 periods in every video mode (one PLL, zxnext_top_issue2:938-941). Only a
    backstop now: SPRITE_DEADLINE comes first."""
    return 4 * LINE_HC[v.timing]


# Measured on Melissa's Next, not read from the VHDL (probes/readings-sitting3-pv5.md, readings-sitting4-pv6.md):
# her Next draws whole sprites only. A drawn sprite qualified at cycle c is drawn if c + 1 + its width
# (16 << xscale) <= SPRITE_DEADLINE; the first that isn't stops the line (nothing more is drawn) and sets status
# bit 1. PV6 put the deadline at 1281-1283 cycles from line_reset_re = "01", so about whc 319: the line's
# sprites are done when the display reaches the sprite area's right edge. A sprite crossing whc 320 is charged
# its full width (not yet measured).
SPRITE_DEADLINE = 1282


def sprite_lines(v):
    """The sprites' line buffers for wvc 0..255: 256 lists of 320 entries, each None or an 8-bit index, as
    the renderer draws them in the line before (spr_cur_vcount = vcounter + 1, sprites:539), sprite 0 to 127
    (sprites:841-866), later writers winning unless NR 0x15 bit 6 puts sprite 0 on top (sprites:972), and
    whole sprites only, by SPRITE_DEADLINE (measured on her Next; what doesn't fit stops the line)."""
    return [_sprite_line(v, row)[0] for row in range(256)]


def sprite_status(v):
    """Port 0x303B after one whole frame since the last read (sprites:974-995): bit 1 if any line dropped a
    sprite that couldn't finish (SPRITE_DEADLINE), bit 0 if a sprite pixel was written over another (sprites:991). The engine renders
    row wvc + 1 in every line of the frame, wvc running from -2 (ulat:494-505), so rows 511, 0, 1, ..."""
    lines = TIMING[v.timing][2][v.hz][0]
    over = coll = 0
    for k in range(lines):
        _, o, c = _sprite_line(v, (511 + k) & 0x1FF)
        over, coll = over | o, coll | c
    return (over << 1) | coll


def _sprite_line(v, wvc, owners=None):
    """One sprite row: (320 entries, overtime, collision). Cycle 0 has line_reset_re = "01" (sprites:519-537),
    S_START is cycle 1 (sprites:831-832, 898-900), sprite 0 qualifies in cycle 2; each sprite spends one cycle
    in S_QUALIFY and, if drawn, one per S_PROCESS pixel (sprites:844-866, 951-956). A drawn sprite that can't
    finish by SPRITE_DEADLINE isn't drawn and stops the line, overtime (measured, not the VHDL's mid-sprite cut
    at the line reset; that stays as a backstop). owners, if given (320 entries), records which sprite wrote
    each pixel, for tests and diagnosis."""
    zero_on_top = (v.nr15 >> 6) & 1
    trans = v.nr4b
    budget = sprite_budget(v)
    t = 2
    collision = 0
    line = [None] * 320
    anchor = dict(vis=0, x=0, y=0, pat=0, pal=0, rel_type=0, h=0, rot=0, xm=0, ym=0, xs=0, ys=0)  # S_START
    for idx in range(128):
        if t > budget:                                                            # cut mid-list
            return line, 1, collision
        t += 1                                                                    # S_QUALIFY
        a0, a1, a2, a3, a4 = v.spr_attr[idx]
        five = (a3 >> 6) & 1
        relative = five and ((a4 >> 6) & 3) == 1                                  # sprites:756
        if relative:                                                              # sprites:760-786
            rx0, ry0 = (a1, a0) if anchor['rot'] else (a0, a1)
            if anchor['rot'] ^ anchor['xm']:
                rx0 = (-rx0) & 0xFF
            if anchor['ym']:
                ry0 = (-ry0) & 0xFF

            def scale(q, sc):
                q = q - 256 if q & 0x80 else q                                    # sign-extend
                return (q << sc) & 0x1FF
            x = (anchor['x'] + scale(rx0, anchor['xs'])) & 0x1FF
            y = (anchor['y'] + scale(ry0, anchor['ys'])) & 0x1FF
            pal = (a2 >> 4) if not (a2 & 1) else ((anchor['pal'] + (a2 >> 4)) & 15)
            if anchor['rel_type']:                                                # unified: the anchor's
                xm_own = ((a2 >> 2) ^ (a2 >> 1)) & 1 if anchor['rot'] else (a2 >> 3) & 1   # transforms join
                ym_own = ((a2 >> 3) ^ (a2 >> 1)) & 1 if anchor['rot'] else (a2 >> 2) & 1
                xm, ym, rot = anchor['xm'] ^ xm_own, anchor['ym'] ^ ym_own, anchor['rot'] ^ ((a2 >> 1) & 1)
                xs, ys = anchor['xs'], anchor['ys']
            else:
                xm, ym, rot = (a2 >> 3) & 1, (a2 >> 2) & 1, (a2 >> 1) & 1
                xs, ys = (a4 >> 3) & 3, (a4 >> 1) & 3
            vis = anchor['vis'] & (a3 >> 7)
            h = anchor['h']
            n6 = ((a4 >> 5) & 1) & h
            pat = (((a3 & 0x3F) << 1) | n6)
            if a4 & 1:                                                            # sprites:803
                pat = (pat + anchor['pat']) & 0x7F
        else:
            x = ((a2 & 1) << 8) | a0                                              # sprites:799
            y = ((five & a4 & 1) << 8) | a1                                       # sprites:796-797
            pal = a2 >> 4
            xm, ym, rot = (a2 >> 3) & 1, (a2 >> 2) & 1, (a2 >> 1) & 1
            xs, ys = ((a4 >> 3) & 3, (a4 >> 1) & 3) if five else (0, 0)          # sprites:807, 907-915
            vis = a3 >> 7
            h = ((a4 >> 7) & 1) & five                                            # sprites:801
            n6 = ((a4 >> 6) & 1) & h                                              # sprites:802
            pat = ((a3 & 0x3F) << 1) | n6
            unified = five and (a4 >> 5) & 1
            anchor = dict(vis=vis, x=x, y=y, pat=pat, pal=pal, rel_type=five & ((a4 >> 5) & 1),
                          h=h, rot=rot if unified else 0, xm=xm if unified else 0,
                          ym=ym if unified else 0, xs=xs if unified else 0,
                          ys=ys if unified else 0)                                # sprites:929-950
        yoff = (wvc - y) & 0x1FF                                                  # sprites:806-810
        if ys:
            yoff = ((yoff - 512 if yoff & 0x100 else yoff) >> ys) & 0x1FF
        if not vis or (yoff >> 4) != 0:                                           # sprites:842, 918
            continue
        yi = (yoff & 15) ^ (15 if ym else 0)                                      # sprites:811
        xme = xm ^ rot                                                            # sprites:813
        xi = 15 if xme else 0
        addr = ((pat >> 1) << 8) | ((xi << 4) | yi if rot else (yi << 4) | xi)    # sprites:816
        delta = {(1, 1): -16, (1, 0): -1, (0, 1): 16, (0, 0): 1}[(xme, rot)]      # sprites:817-820
        step = 8 >> xs                                                            # sprites:907-915
        wrap = (0x1F << xs) & 0x1F                                                # sprites:919-927
        if t + (16 << xs) > SPRITE_DEADLINE:                                      # measured: whole sprites
            return line, 1, collision                                             # only, then stop
        hc, count = x, 0
        while True:                                                               # S_PROCESS: a cycle,
            if t > budget:                                                        # then the exit test
                return line, 1, collision
            t += 1
            a = addr & 0x3FFF
            if h:                                                                 # 4-bit (sprites:962-968)
                byte = v.spr_pat[(a & 0x3F00) | ((pat & 1) << 7) | ((a & 0xFF) >> 1)]
                nib = (byte & 15) if (a & 1) else (byte >> 4)
                pix, opaque = (pal << 4) | nib, nib != (trans & 15)
            else:
                byte = v.spr_pat[a]
                pix, opaque = ((((byte >> 4) + pal) & 15) << 4) | (byte & 15), byte != trans
            if hc < 320 and opaque:                                               # sprites:971
                collision |= line[hc] is not None                                 # sprites:991
                if not zero_on_top or line[hc] is None:                           # sprites:972
                    line[hc] = pix
                    if owners is not None:
                        owners[hc] = idx
            nxt = count + step
            if (nxt ^ count) & 8:                                                 # sprites:954-956
                addr += delta
            count, hc = nxt, (hc + 1) & 0x1FF
            if count & 0x80 or (hc >= 320 and ((hc >> 4) & wrap) != wrap):        # sprites:855
                break
    return line, int(t > budget), collision


def sprite_window(v):
    """(x_s, x_e, y_s, y_e, y_max) for the sprites' output in whc/wvc (sprites:1043-1068)."""
    x1, x2, y1, y2 = v.clip[0x19]
    if v.nr15 & 0x02:                                       # over the border (NR 0x15 bit 1)
        if not (v.nr15 & 0x20):                             # border clip off (bit 5): the whole 320 x 256
            return 0, 319, 0, 255, 256
        return x1 * 2, x2 * 2 + 1, y1, y2, 256
    return x1 + 32, x2 + 32, y1 + 32, y2 + 32, 224         # the paper's window, never below line 224
