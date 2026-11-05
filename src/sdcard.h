// sdcard.h: an SD card in SPI mode, for omse-ai's divMMC.
//
// One byte in, one byte out, per SPI transfer: xfer() is the eight clocks of
// one transfer, taking the byte the host sends (MOSI) and returning the byte
// the card sends at the same time (MISO).  The card is an SDHC card (block
// addressing, CCS set), backed by an image file of 512-byte sectors.
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
//     are legal; an SDHC card leaves idle on ACMD41 only if CMD8 came first
//     and ACMD41's HCS bit is set, after init_tries tries (default 2: the
//     first answers "still idle", so a host has to loop as on a real card).
// Commands: 0, 1, 8, 9, 10, 12, 13, 16, 17, 18, 24, 25, 55, 58, 59, ACMD41.
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

struct SDCard {
    // the image
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

    int insert(const char* path, bool rw) {
        eject();
        int f = open(path, rw ? O_RDWR : O_RDONLY);
        if (f < 0) return -1;
        off_t len = lseek(f, 0, SEEK_END);
        if (len < 512 || len % 512) { close(f); return -2; }
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
        out.clear();
        read_next = -1;
        w = W_NONE;
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

    void csd(uint8_t* d) const {         // CSD version 2.0 (SDHC)
        uint32_t c_size = sectors / 1024 - 1;    // capacity = (C_SIZE + 1) * 512K
        memset(d, 0, 16);
        d[0] = 0x40;                     // CSD_STRUCTURE = 1
        d[1] = 0x0E;                     // TAAC
        d[3] = 0x32;                     // TRAN_SPEED: 25 MHz
        d[4] = 0x5B;                     // CCC
        d[5] = 0x59;                     // CCC, READ_BL_LEN = 9 (512)
        d[7] = (c_size >> 16) & 0x3F;
        d[8] = (c_size >> 8) & 0xFF;
        d[9] = c_size & 0xFF;
        d[10] = 0x7F;                    // ERASE_BLK_EN, SECTOR_SIZE
        d[11] = 0x80;
        d[12] = 0x0A;                    // R2W_FACTOR, WRITE_BL_LEN = 9
        d[13] = 0x40;
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
        if (acmd && c == 41) {           // SD_SEND_OP_COND
            if (cmd8 && (arg & 0x40000000) && ++tries >= init_tries) idle = false;
            r = r1();
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
            case 16:                     // SET_BLOCKLEN: fixed at 512 on SDHC
                r = r1();
                respond({r});
                break;
            case 17:
            case 18: {                   // READ_SINGLE_BLOCK, READ_MULTIPLE_BLOCK
                if (arg >= sectors) {
                    r = r1() | 0x40;     // parameter error
                    respond({r});
                    break;
                }
                uint8_t d[512];
                r = r1();
                respond({r});
                if (!read_sector(arg, d)) {
                    for (int i = 0; i < nac; i++) out.push_back(0xFF);
                    out.push_back(0x01); // error token: error
                    break;
                }
                block(d, 512);
                if (c == 18) read_next = (int64_t)arg + 1;
                break;
            }
            case 24:
            case 25:                     // WRITE_BLOCK, WRITE_MULTIPLE_BLOCK
                if (arg >= sectors) {
                    r = r1() | 0x40;
                    respond({r});
                    break;
                }
                r = r1();
                respond({r});
                w = W_TOKEN;
                w_multi = c == 25;
                w_sector = arg;
                break;
            case 55:                     // APP_CMD
                app = true;
                r = r1();
                respond({r});
                break;
            case 58: {                   // READ_OCR: R3; bit 31 once powered up, CCS (bit 30)
                r = r1();
                uint8_t top = idle ? 0x00 : 0xC0;
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
