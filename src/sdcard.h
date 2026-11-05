// sdcard.h: an SD card in SPI mode, for omse-ai's divMMC.
//
// One byte in, one byte out, per SPI transfer: xfer() is the eight clocks of
// one transfer, taking the byte the host sends (MOSI) and returning the byte
// the card sends at the same time (MISO).  It's backed by an image file of
// 512-byte sectors, and it's one of four kinds of card, as drivers meet them:
//   SDHC  SD 2.0, high capacity: block addresses, CCS set, CSD version 2.0
//   SDSC  SD 2.0, standard capacity (2 GB at most): byte addresses, CCS
//         clear, CSD version 1.0, block length 512 (CMD16: 1 to 512, a read
//         mustn't cross a 512-byte block; writes are whole aligned blocks)
//   SDV1  SD 1.x: as SDSC, but CMD8 is an illegal command
//   MMC   MultiMediaCard: CMD8 and CMD55 illegal; CMD1 initialises it
//
// What it holds to, from the SD Physical Layer Simplified Specification's SPI
// mode and ChaN's "How to Use MMC/SDC" (http://elm-chan.org/docs/mmc/mmc_e.html):
//   - it ignores everything until the host has clocked 74 or more bits with
//     MOSI high, and then everything but CMD0 until a CMD0 with CS low puts it
//     in SPI mode;
//   - CMD0 and CMD8 must carry a valid CRC7 (others only after CMD59 turns
//     CRCs on); a bad one gets R1 with the CRC error bit, and isn't obeyed;
//   - a response comes N_CR bytes after the command (0 to 8 for SD cards;
//     ncr, default 1), a data block N_AC bytes after its R1 (nac, default 1),
//     and a write is followed by its data response token and then busy (MISO
//     held low: `busy` bytes of 00, default 2);
//   - CMD12 stops a multiple-block read with a stuff byte (the next byte
//     of the block it interrupts), then R1b;
//   - while it's initialising (idle), only CMD0, 1, 8, 55, 58, 59 and ACMD41
//     are legal; it leaves idle after init_tries tries (default 2: the first
//     answers "still idle", so a host has to loop as on a real card) of
//     ACMD41 (an SD card; an SDHC card only if CMD8 came first and ACMD41's
//     HCS bit is set) or CMD1 (an MMC, SDSC or SD 1.x card; never SDHC).
// Commands: 0, 1, 8, 9, 10, 12, 13, 16, 17, 18, 24, 25, 55, 58, 59, and ACMD
// 13, 22, 23, 41, 42, 51.
// Anything else gets R1 with the illegal-command bit.  Every command is logged
// (cmd, ACMD or not, argument, R1) for the instrument side.
//
// The image is read and written with pread/pwrite.  Inserted read-only, the
// card still takes writes, into an overlay in memory, so a test can write to
// a card without changing its image file.

#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fcntl.h>
#include <unistd.h>
#include <unordered_map>
#include <vector>

enum { SD_HC = 0, SD_SC = 1, SD_V1 = 2, SD_MMC = 3 };

struct SDCard {
    // the image, and the kind of card
    int kind = SD_HC;
    int fd = -1;
    bool writable = false;
    uint32_t sectors = 0;
    std::unordered_map<uint32_t, std::array<uint8_t, 512>> overlay;

    // timing, in bytes (transfers)
    int ncr = 1, nac = 1, busy = 2, init_tries = 2;

    // power-up and mode
    uint32_t wake_bits = 0;     // bits clocked with MOSI high, before SPI mode
    bool spi = false;           // a CMD0 with CS low has put it in SPI mode
    bool idle = true;           // R1's in-idle-state bit: still initialising
    bool cmd8 = false;          // CMD8 seen since the last CMD0
    bool app = false;           // the last command was CMD55
    bool crc_on = false;        // CMD59
    int tries = 0;              // ACMD41s with HCS since CMD8

    // the command being received
    uint8_t cmd[6];
    int cmd_n = 0;

    uint32_t blen = 512;        // the block length (CMD16), byte-addressed cards

    // what the card sends next, and a multiple-block read in progress
    std::deque<uint8_t> out;
    int64_t read_next = -1;

    // a write in progress
    enum { W_NONE, W_TOKEN, W_DATA, W_CRC1, W_CRC2 } w = W_NONE;
    bool w_multi = false;
    uint32_t w_sector = 0;
    int w_n = 0;
    uint8_t w_buf[512];
    uint16_t w_crc = 0;

    // log: (acmd << 47) | (cmd << 40) | (arg << 8) | r1; r1 = 0xFF: ignored
    std::vector<uint64_t> log;

    ~SDCard() { eject(); }

    // 0, or -1 (can't open), -2 (not whole sectors, or under 512K), -3 (over
    // 2 GB, too big for a standard-capacity card), -4 (no such kind)
    int insert(const char* path, bool rw, int k = SD_HC) {
        eject();
        if (k < SD_HC || k > SD_MMC) return -4;
        int f = open(path, rw ? O_RDWR : O_RDONLY);
        if (f < 0) return -1;
        off_t len = lseek(f, 0, SEEK_END);
        if (len < 512 * 1024 || len % 512) { close(f); return -2; }
        if (k != SD_HC && len > 0x80000000LL) { close(f); return -3; }
        kind = k;
        fd = f;
        writable = rw;
        sectors = (uint32_t)(len / 512);
        power();
        return 0;
    }

    void eject() {
        if (fd >= 0) close(fd);
        fd = -1;
        sectors = 0;
        overlay.clear();
        power();
    }

    // Power on (or off): the card forgets everything but its contents.
    void power() {
        wake_bits = 0;
        spi = false;
        idle = true;
        cmd8 = app = crc_on = false;
        tries = 0;
        cmd_n = 0;
        blen = 512;
        out.clear();
        read_next = -1;
        w = W_NONE;
    }

    // A read or write's argument as a sector (and an offset in it, for a
    // byte-addressed card).  The R1 error bit, or 0 if it's fine.
    uint8_t where(uint32_t arg, uint32_t len, bool aligned, uint32_t& sector, uint32_t& off) const {
        if (kind == SD_HC) {
            sector = arg;
            off = 0;
        } else {
            sector = arg / 512;
            off = arg % 512;
            if ((aligned && off) || off + len > 512) return 0x20;   // address error
        }
        return sector < sectors ? 0 : 0x40;                          // parameter error
    }

    static void put_bits(uint8_t* d, int hi, int lo, uint32_t v) {   // bit 127 is d[0]'s top bit
        for (int b = lo; b <= hi; b++) {
            uint8_t m = 1 << (b % 8);
            if (v >> (b - lo) & 1) d[15 - b / 8] |= m; else d[15 - b / 8] &= ~m;
        }
    }

    bool read_sector(uint32_t s, uint8_t* buf) {
        auto it = overlay.find(s);
        if (it != overlay.end()) {
            memcpy(buf, it->second.data(), 512);
            return true;
        }
        return pread(fd, buf, 512, (off_t)s * 512) == 512;
    }

    bool write_sector(uint32_t s, const uint8_t* buf) {
        if (writable) return pwrite(fd, buf, 512, (off_t)s * 512) == 512;
        std::array<uint8_t, 512> a;
        memcpy(a.data(), buf, 512);
        overlay[s] = a;
        return true;
    }

    static uint8_t crc7(const uint8_t* d, int n) {
        uint8_t c = 0;
        for (int i = 0; i < n; i++) {
            uint8_t b = d[i];
            for (int k = 0; k < 8; k++) {
                c <<= 1;
                if ((b ^ c) & 0x80) c ^= 0x09;
                b <<= 1;
            }
        }
        return c & 0x7F;
    }

    static uint16_t crc16(const uint8_t* d, int n) {
        uint16_t c = 0;
        for (int i = 0; i < n; i++) {
            c ^= (uint16_t)d[i] << 8;
            for (int k = 0; k < 8; k++) c = (c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1;
        }
        return c;
    }

    uint8_t r1() const { return idle ? 0x01 : 0x00; }

    void respond(std::initializer_list<uint8_t> bytes) {
        for (int i = 0; i < ncr; i++) out.push_back(0xFF);
        for (uint8_t b : bytes) out.push_back(b);
    }

    // a data block: N_AC bytes of FF, the start token, the bytes, their CRC16
    void block(const uint8_t* d, int n) {
        for (int i = 0; i < nac; i++) out.push_back(0xFF);
        out.push_back(0xFE);
        for (int i = 0; i < n; i++) out.push_back(d[i]);
        uint16_t c = crc16(d, n);
        out.push_back(c >> 8);
        out.push_back(c & 0xFF);
    }

    void csd(uint8_t* d) const {
        memset(d, 0, 16);
        if (kind == SD_HC) {             // CSD version 2.0: capacity = (C_SIZE + 1) * 512K
            put_bits(d, 127, 126, 1);
            put_bits(d, 119, 112, 0x0E); // TAAC
            put_bits(d, 69, 48, sectors / 1024 - 1);
        } else {                         // version 1.0 (an MMC's says 1.2, spec 3.x)
            // capacity = (C_SIZE + 1) * 2^(C_SIZE_MULT + 2) * 2^READ_BL_LEN: 512-byte
            // blocks up to 1 GB, 1024-byte ones for 2 GB, as cards do
            int bl = sectors > 2097152 ? 10 : 9;
            put_bits(d, 127, 126, kind == SD_MMC ? 2 : 0);
            if (kind == SD_MMC) put_bits(d, 125, 122, 3);
            put_bits(d, 119, 112, 0x26); // TAAC
            put_bits(d, 83, 80, bl);
            put_bits(d, 79, 79, 1);      // READ_BL_PARTIAL
            put_bits(d, 73, 62, (uint32_t)((uint64_t)sectors * 512 / (512u << bl)) - 1);
            put_bits(d, 61, 50, 0xFFF);  // the VDD currents: the most
            put_bits(d, 49, 47, 7);      // C_SIZE_MULT: 512
        }
        put_bits(d, 103, 96, 0x32);      // TRAN_SPEED: 25 MHz
        put_bits(d, 95, 84, 0x5B5);      // CCC: classes 0, 2, 4, 5, 7, 8, 10
        if (kind == SD_HC) put_bits(d, 83, 80, 9);   // READ_BL_LEN: 512
        put_bits(d, 46, 46, 1);          // ERASE_BLK_EN
        put_bits(d, 45, 39, 0x7F);       // SECTOR_SIZE
        put_bits(d, 28, 26, 2);          // R2W_FACTOR
        put_bits(d, 25, 22, kind == SD_HC ? 9 : (sectors > 2097152 ? 10 : 9));   // WRITE_BL_LEN
        d[15] = (crc7(d, 15) << 1) | 1;
    }

    void cid(uint8_t* d) const {
        static const uint8_t c[15] = {0x00, 'O', 'A', 'o', 'm', 's', 'e', 'S', 0x10, 0, 0, 0, 1, 0x01, 0xAA};
        memcpy(d, c, 15);                // OID "OA", product "omseS", rev 1.0, made 2026-10
        d[15] = (crc7(d, 15) << 1) | 1;
    }

    void note(bool acmd, uint8_t c, uint32_t arg, uint8_t r) {
        log.push_back(((uint64_t)acmd << 47) | ((uint64_t)c << 40) | ((uint64_t)arg << 8) | r);
    }

    void command() {
        uint8_t c = cmd[0] & 0x3F;
        uint32_t arg = (uint32_t)cmd[1] << 24 | cmd[2] << 16 | cmd[3] << 8 | cmd[4];
        bool acmd = app;
        app = false;
        bool crc_ok = (cmd[5] >> 1) == crc7(cmd, 5);

        if (!spi) {                      // native mode: only a good CMD0, once awake
            if (c != 0 || wake_bits < 74 || !crc_ok) {
                note(acmd, c, arg, 0xFF);
                return;
            }
            spi = true;
        }
        if (!crc_ok && (c == 0 || c == 8 || crc_on)) {
            respond({(uint8_t)(r1() | 0x08)});
            note(acmd, c, arg, r1() | 0x08);
            return;
        }
        uint8_t r;
        bool sd = kind != SD_MMC;
        if (acmd && c == 41 && sd) {     // SD_SEND_OP_COND: an SDHC card needs CMD8 and HCS
            if ((kind != SD_HC || (cmd8 && (arg & 0x40000000))) && ++tries >= init_tries) idle = false;
            r = r1();
            respond({r});
        } else if ((c == 8 && (kind == SD_V1 || kind == SD_MMC)) || (c == 55 && !sd)) {
            r = r1() | 0x04;             // a 1.x card has no CMD8; an MMC no application commands
            respond({r});
        } else if (acmd && !idle && (c == 13 || c == 22 || c == 23 || c == 42 || c == 51)) {
            uint8_t d[64] = {0};         // SD_STATUS (64 bytes), SEND_NUM_WR_BLOCKS (4),
            r = r1();                    // SEND_SCR (8: SD spec 2.00, SDHC security,
            if (c == 13) respond({r, 0x00});        // 1- and 4-bit bus); 23 and 42: R1
            else respond({r});
            if (c == 13) block(d, 64);
            if (c == 22) block(d, 4);
            if (c == 51) {
                d[0] = 0x02;
                d[1] = 0x35;
                block(d, 8);
            }
        } else if (idle && !(c == 0 || c == 1 || c == 8 || c == 55 || c == 58 || c == 59)) {
            r = 0x05;                    // idle, illegal command
            respond({r});
        } else {
            switch (c) {
            case 0:                      // GO_IDLE_STATE
                idle = true;
                cmd8 = false;
                tries = 0;
                read_next = -1;
                w = W_NONE;
                r = r1();
                respond({r});
                break;
            case 1:                      // SEND_OP_COND: no HCS, so an SDHC card stays idle
                if (kind != SD_HC && ++tries >= init_tries) idle = false;
                r = r1();
                respond({r});
                break;
            case 8: {                    // SEND_IF_COND: R7, echoing the pattern
                cmd8 = true;
                tries = 0;
                r = r1();
                uint8_t volts = (arg >> 8) & 0x0F;
                respond({r, 0x00, 0x00, (uint8_t)(volts == 1 ? 1 : 0), (uint8_t)(arg & 0xFF)});
                break;
            }
            case 9:
            case 10: {                   // SEND_CSD, SEND_CID
                uint8_t d[16];
                if (c == 9) csd(d); else cid(d);
                r = r1();
                respond({r});
                block(d, 16);
                break;
            }
            case 12: {                   // STOP_TRANSMISSION: a stuff byte, then R1b
                // The stuff byte is to be discarded and its value isn't defined:
                // a card in mid-block sends what came next, so software that
                // takes it for R1 can be fooled, as on a real card.
                uint8_t stuff = out.empty() ? 0xFF : out.front();
                read_next = -1;
                out.clear();
                out.push_back(stuff);
                r = r1();
                respond({r});
                for (int i = 0; i < busy; i++) out.push_back(0x00);
                break;
            }
            case 13:                     // SEND_STATUS: R2
                r = r1();
                respond({r, 0x00});
                break;
            case 16:                     // SET_BLOCKLEN: fixed at 512 on SDHC; 1 to 512 otherwise
                if (kind != SD_HC && (arg < 1 || arg > 512)) {
                    r = r1() | 0x40;
                } else {
                    if (kind != SD_HC) blen = arg;
                    r = r1();
                }
                respond({r});
                break;
            case 17:
            case 18: {                   // READ_SINGLE_BLOCK, READ_MULTIPLE_BLOCK
                uint32_t sec, off, n = kind == SD_HC ? 512 : blen;
                uint8_t err = where(arg, n, c == 18, sec, off);
                if (!err && c == 18 && n != 512) err = 0x40;     // whole blocks only
                if (err) {
                    r = r1() | err;
                    respond({r});
                    break;
                }
                uint8_t d[512];
                r = r1();
                respond({r});
                if (!read_sector(sec, d)) {
                    for (int i = 0; i < nac; i++) out.push_back(0xFF);
                    out.push_back(0x01); // error token: error
                    break;
                }
                block(d + off, n);
                if (c == 18) read_next = (int64_t)sec + 1;
                break;
            }
            case 24:
            case 25: {                   // WRITE_BLOCK, WRITE_MULTIPLE_BLOCK: whole aligned blocks
                uint32_t sec, off;
                uint8_t err = where(arg, 512, true, sec, off);
                if (!err && kind != SD_HC && blen != 512) err = 0x40;
                if (err) {
                    r = r1() | err;
                    respond({r});
                    break;
                }
                r = r1();
                respond({r});
                w = W_TOKEN;
                w_multi = c == 25;
                w_sector = sec;
                break;
            }
            case 55:                     // APP_CMD
                app = true;
                r = r1();
                respond({r});
                break;
            case 58: {                   // READ_OCR: R3; bit 31 once powered up, CCS (bit 30) if SDHC
                r = r1();
                uint8_t top = idle ? 0x00 : (kind == SD_HC ? 0xC0 : 0x80);
                respond({r, top, 0xFF, 0x80, 0x00});
                break;
            }
            case 59:                     // CRC_ON_OFF
                crc_on = arg & 1;
                r = r1();
                respond({r});
                break;
            default:
                r = r1() | 0x04;         // illegal command
                respond({r});
                break;
            }
        }
        note(acmd, c, arg, r);
    }

    void write_byte(uint8_t b) {
        switch (w) {
        case W_TOKEN:
            if (b == (w_multi ? 0xFC : 0xFE)) {
                w = W_DATA;
                w_n = 0;
            } else if (w_multi && b == 0xFD) {   // Stop Tran: a byte, then busy
                w = W_NONE;
                out.push_back(0xFF);
                for (int i = 0; i < busy; i++) out.push_back(0x00);
            }
            break;
        case W_DATA:
            w_buf[w_n++] = b;
            if (w_n == 512) w = W_CRC1;
            break;
        case W_CRC1:
            w_crc = (uint16_t)b << 8;
            w = W_CRC2;
            break;
        case W_CRC2: {
            w_crc |= b;
            uint8_t token;
            if (crc_on && w_crc != crc16(w_buf, 512)) token = 0x0B;      // CRC error
            else if (w_sector >= sectors || !write_sector(w_sector, w_buf)) token = 0x0D;  // write error
            else token = 0x05;                                           // accepted
            out.push_back(token);
            for (int i = 0; i < busy; i++) out.push_back(0x00);
            if (w_multi && token == 0x05) {
                w_sector++;
                w = W_TOKEN;
            } else {
                w = W_NONE;
            }
            break;
        }
        default:
            break;
        }
    }

    // One transfer: MOSI in, MISO out.  cs: this card is selected.
    uint8_t xfer(uint8_t mosi, bool cs) {
        if (fd < 0) return 0xFF;                 // no card: MISO is pulled up
        if (!spi && mosi == 0xFF && wake_bits < 74) wake_bits += 8;
        if (!cs) return 0xFF;
        uint8_t miso = 0xFF;
        if (out.empty() && read_next >= 0) {     // the next block of a multiple read
            if (read_next >= sectors) {
                read_next = -1;
            } else {
                uint8_t d[512];
                if (read_sector((uint32_t)read_next, d)) block(d, 512);
                read_next++;
            }
        }
        if (!out.empty()) {
            miso = out.front();
            out.pop_front();
        }
        if (w != W_NONE) {
            write_byte(mosi);
        } else if (cmd_n == 0) {
            if ((mosi & 0xC0) == 0x40) cmd[cmd_n++] = mosi;
        } else {
            cmd[cmd_n++] = mosi;
            if (cmd_n == 6) {
                cmd_n = 0;
                command();
            }
        }
        return miso;
    }
};
