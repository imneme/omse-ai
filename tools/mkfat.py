#!/usr/bin/env python3
"""mkfat.py: build and read SD-card images for divMMC (esxDOS).

An image is an MBR with one FAT16 (or, with --fat32, FAT32) partition,
holding a host directory tree. Names are 8.3 by default, as esxDOS 0.8.9
has no long names; --lfn adds long-name entries for anything else. Pure
Python 3, standard library only, so it runs anywhere omse-ai does.

    mkfat.py build IMG DIR [--size-mb N] [--label NAME] [--fat32]
                           [--part-start LBA] [--cluster-kb K] [--lfn]
                           [--mtimes | --stamp YYYY-MM-DDTHH:MM:SS]
    mkfat.py ls    IMG [PATH] [-l] [-R] [-a]
    mkfat.py cat   IMG PATH
    mkfat.py info  IMG
    mkfat.py check IMG
    mkfat.py put   IMG HOSTFILE [DIR] [--as NAME] [--replace] [--lfn]
                                      [--at CLUSTER[,CLUSTER...]]
    mkfat.py rm    IMG PATH
    mkfat.py runs  IMG PATH

Written on 5 Nov 2026 by Fern (the instance of her called Loam; for this
work she inhabited Claude Opus 5.5), from Melissa O'Neill's idea, to a
brief by Speccy-Zone (another instance of Fern), who built omse-ai's
divMMC and booted esxDOS from the first card this made. Long names,
placement and the rest added the next night, for Tally (another
instance of Fern), to make cards shaped like Melissa's real one.

SOURCE
------
Every FAT field below follows Microsoft, "FAT: General Overview of
On-Disk Format", version 1.03 (fatgen103.doc, 6 Dec 2000; the copy read
had sha256 b17d66c796d9cd3070adf4ccbc00add5a8b6b6f5491fe8ea949df778fce60172).
Section names in [brackets] are its headings. The MBR is outside
fatgen103; where a choice there is convention rather than that
document, it says so.

IMAGE LAYOUT (512-byte sectors)
-------------------------------
    LBA 0          MBR, one partition entry, signature 55AA
    LBA 1..S-1     zero. S is --part-start, default 2048 (1 MiB), as SD
                   cards are formatted, so FAT structures sit on
                   erase-block bounds; 32 GB SDHC cards use 8192 (4 MiB)
    LBA S..end     the FAT volume, filling the rest of the image

Inside the volume, [FAT Data Structure]: the reserved region (FAT16: the
boot sector alone; FAT32: 32 sectors), two FATs, the FAT16 root
directory (512 entries, 32 sectors), then the data region from cluster 2.

Images are sparse: a 4K block that would be all zeros is never written
(or, when changing an existing image, rewritten only if it isn't zero
already). How much disk that saves is up to the host's filesystem.
APFS fills short gaps anyway (measured on 5 Nov 2026: gaps of 16 MiB
were filled, gaps of 64 MiB left as holes), so there a 30,560 MiB card
holding 23 MB near its start and 21 MB at 4 GB takes 43 MB.

THE MBR (convention; fatgen103 does not cover it)
--------------------------------------------------
    446  status        00h, not bootable (nothing here boots a PC)
    447  CHS first     from LBA with 255 heads x 63 sectors, the geometry
    451  CHS last      mkfs.fat assumes when it can't ask; past cylinder
                       1023 the CHS fields saturate to FE FF FF
    450  type          FAT16: 06h ("FAT16B", 65536 sectors or more; every
                       size from 33 MiB up, including the 64 MiB default)
                       or 04h below that. FAT32: 0Bh if the partition
                       ends within CHS reach, else 0Ch (FAT32 LBA).
                       --ptype overrides.
    454  LBA start     --part-start
    458  sector count  the rest of the image
    510  55h AAh
Bytes 0..445 (boot code, disk signature) are zero.

THE BOOT SECTOR AND BPB [Boot Sector and BPB]
---------------------------------------------
    0   BS_jmpBoot     EB 3C 90 (FAT16) / EB 58 90 (FAT32): the
                       recommended short-jump form, to the boot code just
                       after the BPB
    3   BS_OEMName     "MSWIN4.1", the string the spec recommends as
                       "least likely to cause compatibility problems"
    11  BPB_BytsPerSec 512: SD cards' sector size, and the only value
                       the format tables below are valid for
    13  BPB_SecPerClus from DskTableFAT16 / DskTableFAT32
                       [FAT Volume Initialization], by volume size.
                       64 MiB image: 2K clusters (FAT16), 512 bytes
                       (FAT32). --cluster-kb overrides (up to 32, the
                       spec's limit): SD-formatted 32 GB cards use 32K
                       where the table says 16K. The FAT size arithmetic
                       below is the same either way, and the result is
                       checked to hold every cluster.
    14  BPB_RsvdSecCnt 1 (FAT16: "should never be anything other than 1")
                       or 32 (FAT32: "typically 32"); the tables assume
                       exactly these
    16  BPB_NumFATs    2 ("should always contain the value 2")
    17  BPB_RootEntCnt 512 (FAT16: "for maximum compatibility... 512");
                       0 for FAT32 (must be)
    19  BPB_TotSec16   the volume's sector count if below 10000h, else 0
                       (always 0 for FAT32)
    21  BPB_Media      F8h, fixed media, as SD cards are formatted; also
                       the low byte of FAT[0]
    22  BPB_FATSz16    from the spec's TmpVal1/TmpVal2 arithmetic
                       [FAT Volume Initialization]; 0 for FAT32
    24  BPB_SecPerTrk  63   } the same geometry as the MBR's CHS fields
    26  BPB_NumHeads   255  }
    28  BPB_HiddSec    --part-start, the sectors preceding the partition
    32  BPB_TotSec32   the volume's sector count if 10000h or more, else 0
  FAT16, from offset 36 [Fat12 and Fat16 Structure Starting at Offset 36]:
    36  BS_DrvNum      80h (a hard disk, not a floppy)
    37  BS_Reserved1   0 ("should always set this byte to 0")
    38  BS_BootSig     29h: the next three fields are present
    39  BS_VolID       the stamp's DOS date (high word) and time (low
                       word), "combining the current date and time" as
                       the spec describes, but from the fixed stamp so
                       builds are deterministic; --volid overrides
    43  BS_VolLab      the label, space-padded, matching the root
                       directory's label entry; "NO NAME    " if none
    54  BS_FilSysType  "FAT16   " (informational, but "should be set")
  FAT32, from offset 36 [FAT32 Structure Starting at Offset 36]:
    36  BPB_FATSz32    the same arithmetic, with TmpVal2 halved
    40  BPB_ExtFlags   0: the FAT is mirrored into both copies
    42  BPB_FSVer      0:0, the only version defined
    44  BPB_RootClus   2: the root directory is the first cluster
                       allocated, as disk utilities expect
    48  BPB_FSInfo     1
    50  BPB_BkBootSec  6 ("No value other than 6 is recommended")
    52  BPB_Reserved   zeros
    64..89             BS_DrvNum .. BS_FilSysType as for FAT16, at their
                       FAT32 offsets; BS_FilSysType "FAT32   "
  Then boot code: CD 18 F4 EB FD (INT 18h, "no bootable disk here, try
  the next one"; then HLT forever). Bytes 510-511 are 55h AAh.

FAT32 only [FAT32 FSInfo Sector Structure and Backup Boot Sector]:
sector 1 is FSInfo (lead signature 41615252h, structure signature
61417272h, FSI_Free_Count the true free count, FSI_Nxt_Free the first
free cluster, trail signature AA550000h); sector 2 is the boot record's
third sector, empty but for its 55AA; sectors 6-8 copy sectors 0-2.

THE FAT [FAT Data Structure]
----------------------------
FAT[0] is the media byte with every other bit set (FFF8h / 0FFFFFF8h);
FAT[1] is the EOC mark with the clean-shutdown and no-error bits set
(FFFFh / 0FFFFFFFh). Chains end with FFFFh / 0FFFFFFFh, the EOC values
Microsoft's drivers write. Entries past CountofClusters+1, and any
spare FAT sectors, are zero. Both FATs are identical.

Every file and directory gets one contiguous run of clusters, allocated
in sorted pre-order (a directory, then everything inside it, then its
next sibling). esxDOS needs some files unfragmented (its DOCS say so
for .dvo and .wav), and this way nothing on a fresh card is fragmented.
A zero-length file has first cluster 0 and no FAT entries.

The cluster count is recomputed exactly as a reader computes it [FAT
Type Determination], and the build refuses a count outside the type's
range (FAT16: 4085 to 65524). It warns when within 16 clusters of a
cutover, which the spec advises avoiding. Note that DskTableFAT16's
2 GiB row yields 65527 clusters, which every reader takes for FAT32;
the check catches that rather than trusting the table.

DIRECTORIES [FAT Directory Structure]
-------------------------------------
    DIR_Name        8.3, upper-cased, space-padded. Only letters,
                    digits and $ % ' - _ @ ~ ` ! ( ) { } ^ # & [Name
                    Limits and Character Sets, Short Directory Entries].
                    Without --lfn, a host name that doesn't fit is an
                    error naming it (esxDOS 0.8.9 has no long names).
                    Names beginning with "." (macOS's .DS_Store and
                    friends) are skipped with a note on stderr.
    DIR_Attr        files 20h (ARCHIVE, "set... when a file is
                    created"); directories 10h; the label 08h
    DIR_NTRes       0
    DIR_CrtTimeTenth 0 (odd seconds with --mtimes: 100)
    DIR_CrtTime/Date, DIR_WrtTime/Date: the stamp, default 2026-11-05
                    00:00:00 (--stamp to change it, --mtimes for each
                    host file's own local mtime); creation counts as a
                    write
    DIR_LstAccDate  the same date ("should be set to the same date as
                    DIR_WrtDate")
    DIR_FstClusHI/LO the first cluster (HI is 0 on FAT16)
    DIR_FileSize    bytes; 0 for directories
The root directory holds the volume label entry first (attribute 08h,
cluster 0, size 0), then the tree. Each subdirectory starts with "." (its
own cluster) and ".." (its parent's, 0 for the root, even on FAT32),
with the directory's own timestamps. Entries are sorted by DIR_Name.
Directories are sized to their entries, at least one cluster, and
otherwise zero-filled; a FAT16 root holds at most 512 entries.

LONG NAMES, WITH --lfn [FAT Long Directory Entries]
---------------------------------------------------
A name that is already its own upper-case 8.3 form (SYS, ZOOM.BIN) gets
a short entry alone. Any other name gets long entries holding it whole,
just before its short entry, and the short entry's name (its alias) is
made by [The Basis-Name Generation Algorithm] and [The Numeric-Tail
Generation Algorithm]: upper-case it; any character not allowed in a
short name becomes "_" (a "lossy" conversion); strip spaces and leading
periods; up to 8 characters before the first period, up to 3 after the
last. If nothing was lost and the name fits 8.3 ("readme.txt"), the
alias is the name upper-cased; otherwise "~n" goes on the primary part,
with n the smallest that doesn't collide (so "Card test file 1.txt"
becomes CARDTE~1.TXT). Aliases are chosen in sorted host-name order,
after names that are their own alias, so builds stay deterministic.
    LDIR_Ord       1..n, the last ORed with 40h; stored last first
    LDIR_Name1/2/3 13 UCS-2 characters an entry, NUL-terminated and
                   padded with FFFFh unless the name fills the last
                   entry exactly
    LDIR_Attr      0Fh; LDIR_Type 0; LDIR_FstClusLO 0
    LDIR_Chksum    the spec's ChkSum() of the 11-byte alias
Long names follow [Name Limits and Character Sets]: up to 255
characters, none of " * / : < > ? \\ | or control characters; leading or
trailing spaces and trailing periods are refused rather than silently
dropped. Characters past U+FFFF are refused. Long names are stored
precomposed (Unicode NFC), whatever form the host gave them in. The reader assembles long
names (checking ordinals and checksums) and check reports orphans.

DETERMINISM
-----------
The same tree, size, label and options give the same bytes: sorted
order, a fixed stamp, a VolID derived from it, and nothing taken from
the clock. (--mtimes trades that away on purpose.)

PUT, RM AND RUNS: CHANGING AN EXISTING IMAGE
--------------------------------------------
put and rm refuse an image that fails check, then work as a DOS would.
put gives the file the first run of free clusters long enough to hold
it whole (first fit; never fragmented, so it refuses rather than
scatter it), or, with --at, exactly the clusters asked for: one start
puts it there in one piece, several split it into that many pieces as
evenly as possible, chained in the order given (for testing readers;
esxDOS wants some files whole). Its entries go in the first run of free
slots in DIR long enough for them (00h or E5h [DIR_Name[0]]); a full
subdirectory, or a full FAT32 root, grows by zeroed clusters, while a
full FAT16 root is fixed at 512 entries and refuses. The writes go data
first, then every FAT copy, then the directory entries (long ones
before the short one), so an interrupted put leaves at worst lost
clusters, never an entry pointing at garbage. The slack after the
file's last byte is zeroed. FAT32's FSInfo free count and next-free
hint are updated. With --replace, an existing file of that name (long
or short) is deleted first, entry before clusters. rm deletes a file the
same way: its entries marked E5h, then its chain freed. runs prints a
file's clusters as runs, with the card sectors (LBA) each covers, and
where its directory entry sits. The same image and file give the same
bytes, but put appends where a DOS would, so it needn't match a fresh
build of the same tree.
"""

import argparse
import datetime
import os
import stat
import struct
import sys
import unicodedata

SECTOR = 512
PART_START = 2048          # default LBA of the partition: 1 MiB
HEADS, SPT = 255, 63       # CHS geometry for the MBR and the BPB
MEDIA = 0xF8
DEFAULT_STAMP = "2026-11-05T00:00:00"
DEFAULT_LABEL = "DIVMMC"
BLOCK = 4096               # sparse-writing granularity (APFS's block)
ZERO_BLOCK = bytes(BLOCK)

# [FAT Volume Initialization]: (DiskSize in sectors, SecPerClusVal).
# The first row whose DiskSize is >= the volume size applies; 0 is an
# error ("trips an error").
DSK_TABLE_FAT16 = [
    (8400, 0), (32680, 2), (262144, 4), (524288, 8),
    (1048576, 16), (2097152, 32), (4194304, 64), (0xFFFFFFFF, 0),
]
DSK_TABLE_FAT32 = [
    (66600, 0), (532480, 1), (16777216, 8), (33554432, 16),
    (67108864, 32), (0xFFFFFFFF, 64),
]

ATTR_READ_ONLY, ATTR_HIDDEN, ATTR_SYSTEM = 0x01, 0x02, 0x04
ATTR_VOLUME_ID, ATTR_DIRECTORY, ATTR_ARCHIVE = 0x08, 0x10, 0x20
ATTR_LONG_NAME = 0x0F

NAME_SPECIALS = set("$%'-_@~`!(){}^#&")
LONG_NAME_BAD = set('"*/:<>?\\|')
BOOT_CODE = bytes([0xCD, 0x18, 0xF4, 0xEB, 0xFD])

# Partition types that hold a FAT volume, for the reader.
FAT_PTYPES = {0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E}


class FatError(Exception):
    """Anything wrong with a tree, an option, or an image."""


def warn(msg):
    print(f"mkfat: {msg}", file=sys.stderr)


def write_at(f, off, data, fresh=False):
    """Write data at byte off, sparsely: an all-zero 4K block (aligned to
    the file) is skipped when the file is fresh, or when it is already
    zero on disk; anything else is written."""
    data = memoryview(data)
    i, n = 0, len(data)
    while i < n:
        j = min(n, (off + i) // BLOCK * BLOCK + BLOCK - off)
        piece = data[i:j]
        if piece == ZERO_BLOCK[:len(piece)]:
            if not fresh:
                f.seek(off + i)
                old = f.read(len(piece))
                if old.count(0) != len(old):
                    f.seek(off + i)
                    f.write(piece)
        else:
            f.seek(off + i)
            f.write(piece)
        i = j


# ----------------------------------------------------------------------
# Names, labels and timestamps

def fit_83(name):
    """(DIR_Name, None) if name upper-cased is a valid 8.3 name, else
    (None, why not)."""
    if not name.isascii():
        return None, "not ASCII"
    up = name.upper()
    if up.count(".") > 1:
        return None, "more than one '.'"
    base, _, ext = up.partition(".")
    if not base:
        return None, "empty name before the '.'"
    if len(base) > 8:
        return None, f"name part '{base}' is longer than 8 characters"
    if len(ext) > 3:
        return None, f"extension '{ext}' is longer than 3 characters"
    for ch in base + ext:
        if not (ch.isalnum() or ch in NAME_SPECIALS):
            return None, f"character {ch!r} isn't allowed in a short name"
    return (base.ljust(8) + ext.ljust(3)).encode("ascii"), None


def short_name(name, where):
    """A host name as an 11-byte DIR_Name, or FatError naming it."""
    n11, why = fit_83(name)
    if n11 is None:
        raise FatError(f"{where}: {why}; esxDOS 0.8.9 needs 8.3 names "
                       f"(--lfn adds long names anyway)")
    return n11


def check_long(name, where):
    """FatError unless name is a long name we're willing to write."""
    if len(name) > 255:
        raise FatError(f"{where}: longer than 255 characters")
    if name != name.strip(" ") or name.endswith("."):
        raise FatError(f"{where}: leading or trailing spaces, or a "
                       f"trailing '.', which FAT would drop")
    for ch in name:
        if ord(ch) < 0x20 or ch in LONG_NAME_BAD:
            raise FatError(f"{where}: character {ch!r} isn't allowed in a "
                           f"long name")
        if ord(ch) > 0xFFFF:
            raise FatError(f"{where}: character {ch!r} is past U+FFFF")


def needs_long(name):
    """True if name isn't simply its own upper-case 8.3 form."""
    n11, _ = fit_83(name)
    return n11 is None or name != name.upper()


def basis_name(long):
    """[The Basis-Name Generation Algorithm]: (primary, ext, lossy)."""
    lossy, chars = False, []
    for ch in long.upper():
        if ch in " ." or (ch.isascii() and (ch.isalnum()
                                            or ch in NAME_SPECIALS)):
            chars.append(ch)
        else:
            chars.append("_")
            lossy = True
    s = "".join(chars).replace(" ", "").lstrip(".")
    primary = ""
    for ch in s:
        if ch == "." or len(primary) == 8:
            break
        primary += ch
    dot = s.rfind(".")
    ext = s[dot + 1:dot + 4] if dot != -1 else ""
    if not primary:
        primary, lossy = "_", True
    return primary, ext, lossy


def make_alias(long, taken):
    """[The Numeric-Tail Generation Algorithm]: an 11-byte alias for a
    long name, not in taken."""
    primary, ext, lossy = basis_name(long)
    n11, _ = fit_83(long)
    if not lossy and n11 is not None and n11 not in taken:
        return n11
    for n in range(1, 1000000):
        tail = f"~{n}"
        cand = ((primary[:8 - len(tail)] + tail).ljust(8)
                + ext.ljust(3)).encode("ascii")
        if cand not in taken:
            return cand
    raise FatError(f"{long}: no free ~n alias left")


def lfn_checksum(name11):
    """The spec's ChkSum(): an unsigned rotate right, then add."""
    s = 0
    for b in name11:
        s = (((s & 1) << 7) + (s >> 1) + b) & 0xFF
    return s


def lfn_entries(long, name11):
    """The long entries for a name, in on-disk order (the last part
    first) [Storage of a Long-Name Within Long Directory Entries].
    Stored precomposed (NFC), as Windows and macOS's own driver write."""
    units = [ord(c) for c in unicodedata.normalize("NFC", long)]
    n = -(-len(units) // 13)
    if len(units) % 13:
        units.append(0)
        units += [0xFFFF] * (n * 13 - len(units))
    csum = lfn_checksum(name11)

    def u16(part):
        return struct.pack(f"<{len(part)}H", *part)
    out = []
    for i in range(n):
        part = units[13 * i:13 * i + 13]
        ordv = (i + 1) | (0x40 if i == n - 1 else 0)
        out.append(struct.pack("<B10sBBB12sH4s", ordv, u16(part[0:5]),
                               ATTR_LONG_NAME, 0, csum, u16(part[5:11]), 0,
                               u16(part[11:13])))
    return out[::-1]


def label_name(label):
    """A volume label as 11 bytes (no '.' split; inner spaces allowed)."""
    up = label.upper()
    if not up.isascii() or len(up) > 11 or up.startswith(" "):
        raise FatError(f"label {label!r}: at most 11 ASCII characters, "
                       f"not starting with a space")
    for ch in up:
        if not (ch.isalnum() or ch in NAME_SPECIALS or ch == " "):
            raise FatError(f"label {label!r}: character {ch!r} isn't "
                           f"allowed")
    return up.ljust(11).encode("ascii")


def show_name(name11):
    """An 11-byte DIR_Name as NAME.EXT."""
    if name11[0] == 0x05:
        name11 = b"\xe5" + name11[1:]
    base = name11[:8].decode("latin-1").rstrip(" ")
    ext = name11[8:].decode("latin-1").rstrip(" ")
    return base + ("." + ext if ext else "")


def dos_stamp(dt):
    """(date, time, tenths) for a datetime [Date and Time Formats]."""
    if not 1980 <= dt.year <= 2107:
        raise FatError(f"timestamp {dt} is outside FAT's 1980-2107")
    date = ((dt.year - 1980) << 9) | (dt.month << 5) | dt.day
    time = (dt.hour << 11) | (dt.minute << 5) | (dt.second // 2)
    return date, time, (dt.second % 2) * 100


def mtime_stamp(st):
    t = datetime.datetime.fromtimestamp(st.st_mtime)
    return dos_stamp(min(max(t, datetime.datetime(1980, 1, 1)),
                         datetime.datetime(2107, 12, 31, 23, 59, 58)))


def stamp_text(date, time):
    y, mo, d = 1980 + (date >> 9), (date >> 5) & 15, date & 31
    h, mi, s = time >> 11, (time >> 5) & 63, (time & 31) * 2
    return f"{y:04}-{mo:02}-{d:02} {h:02}:{mi:02}:{s:02}"


# ----------------------------------------------------------------------
# Geometry: the volume's layout from its size [FAT Volume Initialization]

class Geometry:
    def __init__(self, vol_sectors, fat32, spc=None):
        self.fat32 = fat32
        self.total = vol_sectors
        kind = "FAT32" if fat32 else "FAT16"
        if spc is None:
            table = DSK_TABLE_FAT32 if fat32 else DSK_TABLE_FAT16
            spc = next(v for limit, v in table if vol_sectors <= limit)
            if spc == 0:
                mib = vol_sectors * SECTOR / 2**20
                raise FatError(f"a {mib:.1f} MiB volume is outside {kind}'s "
                               f"format table; pick another --size-mb"
                               + ("" if fat32 else " or --fat32"))
        elif spc not in (1, 2, 4, 8, 16, 32, 64):
            raise FatError("--cluster-kb must be 1, 2, 4, 8, 16 or 32 "
                           "(fatgen103: never more than 32K a cluster)")
        self.spc = spc
        self.rsvd = 32 if fat32 else 1
        self.nfats = 2
        self.root_ent = 0 if fat32 else 512
        self.root_dir_sectors = (self.root_ent * 32 + SECTOR - 1) // SECTOR
        tmp1 = vol_sectors - (self.rsvd + self.root_dir_sectors)
        tmp2 = 256 * spc + self.nfats
        if fat32:
            tmp2 //= 2
        self.fatsz = (tmp1 + tmp2 - 1) // tmp2
        self.first_data = (self.rsvd + self.nfats * self.fatsz
                           + self.root_dir_sectors)
        if vol_sectors <= self.first_data:
            raise FatError("the volume is too small for its own FATs")
        self.count = (vol_sectors - self.first_data) // spc
        # Check the result the way a reader would [FAT Type Determination].
        lo, hi = (65525, 0x0FFFFFF5) if fat32 else (4085, 65524)
        if not lo <= self.count <= hi:
            raise FatError(f"this size gives {self.count} clusters, which "
                           f"every reader would take for "
                           f"{fat_type_of(self.count)}, not {kind}; pick "
                           f"another --size-mb or cluster size"
                           + ("" if fat32 else " or --fat32"))
        for cut in (4085, 65525):
            if abs(self.count - cut) <= 16:
                warn(f"{self.count} clusters is within 16 of the "
                     f"{cut} cutover, which fatgen103 advises avoiding")
        self.entsize = 4 if fat32 else 2
        self.eoc = 0x0FFFFFFF if fat32 else 0xFFFF
        if (self.count + 2) * self.entsize > self.fatsz * SECTOR:
            raise FatError("the FAT would be too small for its clusters")
        self.cluster_bytes = spc * SECTOR


def fat_type_of(count):
    """[FAT Type Determination]: the count of clusters, and nothing else."""
    if count < 4085:
        return "FAT12"
    if count < 65525:
        return "FAT16"
    return "FAT32"


# ----------------------------------------------------------------------
# The host tree

class Node:
    def __init__(self, name11, host, rel, is_dir, size, stamp, long=None):
        self.name11, self.host, self.rel = name11, host, rel
        self.is_dir, self.size, self.stamp = is_dir, size, stamp
        self.long = long     # the long name, if it gets long entries
        self.children = []
        self.first = 0       # first cluster
        self.nclus = 0       # clusters in its (contiguous) run

    def nslots(self):
        return 1 + (len(lfn_entries(self.long, self.name11))
                    if self.long else 0)


def scan(host, rel, stamp_for, lfn=False):
    """The tree under host, as sorted Nodes; errors name the bad path."""
    with os.scandir(host) as it:
        entries = sorted(it, key=lambda e: e.name)
    names = []
    for e in entries:
        path = f"{rel}/{e.name}" if rel else e.name
        if e.name.startswith("."):
            warn(f"skipping hidden {path}")
            continue
        names.append((e, path))
    # Names: those that are their own alias first, then the rest in
    # sorted order, so ~n tails are deterministic.
    alias, taken, seen = {}, set(), {}
    for e, path in names:
        if lfn:
            check_long(e.name, path)
        if not lfn or not needs_long(e.name) or fit_83(e.name)[0]:
            n11 = short_name(e.name, path)
            if n11 in taken:
                other = next(p for (x, p) in names if alias.get(x.name)
                             == n11)
                raise FatError(f"{path} and {other} would both be "
                               f"{show_name(n11)}")
            alias[e.name] = n11
            taken.add(n11)
    for e, path in names:
        if e.name not in alias:
            alias[e.name] = make_alias(e.name, taken)
            taken.add(alias[e.name])
    for e, path in names:      # one namespace, ignoring case
        key = e.name.upper()
        if key in seen:
            raise FatError(f"{path} and {seen[key]} differ only in case")
        seen[key] = path
    nodes = []
    for e, path in names:
        n11 = alias[e.name]
        long = e.name if lfn and needs_long(e.name) else None
        st = os.stat(e.path)
        if stat.S_ISDIR(st.st_mode):
            if e.is_symlink():
                raise FatError(f"{path}: a symlink to a directory; "
                               f"not followed")
            node = Node(n11, e.path, path, True, 0, stamp_for(st), long)
            node.children = scan(e.path, path, stamp_for, lfn)
        elif stat.S_ISREG(st.st_mode):
            if st.st_size > 0xFFFFFFFF:
                raise FatError(f"{path}: larger than FAT's 4 GiB limit")
            node = Node(n11, e.path, path, False, st.st_size,
                        stamp_for(st), long)
        else:
            raise FatError(f"{path}: not a regular file or directory")
        nodes.append(node)
    nodes.sort(key=lambda n: n.name11)
    return nodes


# ----------------------------------------------------------------------
# Building

def dirent(name11, attr, cluster, size, stamp):
    date, time, tenth = stamp
    return struct.pack("<11sBBBHHHHHHHI", name11, attr, 0, tenth,
                       time, date, date, cluster >> 16,
                       time, date, cluster & 0xFFFF, size)


def chs(lba):
    c = lba // (HEADS * SPT)
    if c > 1023:
        return bytes([254, 0xFF, 0xFF])
    h = (lba // SPT) % HEADS
    s = lba % SPT + 1
    return bytes([h, s | ((c >> 2) & 0xC0), c & 0xFF])


def build(img, top, size_mb, label, fat32, stamp_dt, mtimes,
          volid=None, ptype=None, part_start=PART_START, spc=None,
          lfn=False):
    if size_mb < 2:
        raise FatError("--size-mb must be at least 2")
    total_sectors = size_mb * 2048
    if not 1 <= part_start < total_sectors:
        raise FatError(f"--part-start {part_start} is outside the image")
    vol_sectors = total_sectors - part_start
    g = Geometry(vol_sectors, fat32, spc)
    fixed = dos_stamp(stamp_dt)

    def stamp_for(st):
        return mtime_stamp(st) if mtimes else fixed

    if not os.path.isdir(top):
        raise FatError(f"{top}: not a directory")
    label11 = label_name(label) if label else None
    root = Node(b"", top, "", True, 0, fixed)
    root.children = scan(top, "", stamp_for, lfn)

    # Allocate contiguous runs in sorted pre-order.
    cb = g.cluster_bytes
    nxt = 2
    runs = []                                  # (first, nclus)

    def alloc(node, nclus):
        nonlocal nxt
        node.first, node.nclus = nxt, nclus
        runs.append((nxt, nclus))
        nxt += nclus

    def dir_entries(node, is_root):
        n = sum(c.nslots() for c in node.children) + (0 if is_root else 2)
        if is_root and label11:
            n += 1
        if n > 65536:
            raise FatError(f"{node.rel or '/'}: {n} entries; a FAT "
                           f"directory holds at most 65536")
        return n

    def walk(node):
        for child in node.children:
            if child.is_dir:
                n = dir_entries(child, False)
                alloc(child, max(1, -(-n * 32 // cb)))
                walk(child)
            elif child.size:
                alloc(child, -(-child.size // cb))

    n_root = dir_entries(root, True)
    if fat32:
        alloc(root, max(1, -(-n_root * 32 // cb)))
    elif n_root > g.root_ent:
        raise FatError(f"the root directory needs {n_root} entries; "
                       f"FAT16's holds {g.root_ent}")
    walk(root)
    used = nxt - 2
    if used > g.count:
        raise FatError(f"the tree needs {used} clusters of {cb} bytes; "
                       f"the volume has {g.count}. Try a bigger --size-mb.")

    # The FAT.
    fat = bytearray(g.fatsz * SECTOR)
    put = (lambda n, v: struct.pack_into("<I", fat, n * 4, v)) if fat32 \
        else (lambda n, v: struct.pack_into("<H", fat, n * 2, v))
    put(0, (0x0FFFFF00 if fat32 else 0xFF00) | MEDIA)
    put(1, g.eoc)
    for first, n in runs:
        for c in range(first, first + n - 1):
            put(c, c + 1)
        put(first + n - 1, g.eoc)

    # Directory contents.
    def dir_bytes(node, parent_first, is_root, nbytes):
        out = bytearray(nbytes)
        ents = []
        if is_root and label11:
            ents.append(dirent(label11, ATTR_VOLUME_ID, 0, 0, fixed))
        if not is_root:
            ents.append(dirent(b".          ", ATTR_DIRECTORY,
                               node.first, 0, node.stamp))
            ents.append(dirent(b"..         ", ATTR_DIRECTORY,
                               parent_first, 0, node.stamp))
        for c in node.children:
            if c.long:
                ents.extend(lfn_entries(c.long, c.name11))
            if c.is_dir:
                ents.append(dirent(c.name11, ATTR_DIRECTORY, c.first, 0,
                                   c.stamp))
            else:
                ents.append(dirent(c.name11, ATTR_ARCHIVE, c.first,
                                   c.size, c.stamp))
        blob = b"".join(ents)
        out[:len(blob)] = blob
        return out

    # The boot sector.
    if volid is None:
        volid = (fixed[0] << 16) | fixed[1]
    vollab = label11 or b"NO NAME    "
    bs = bytearray(SECTOR)
    bs[0:3] = b"\xEB\x58\x90" if fat32 else b"\xEB\x3C\x90"
    bs[3:11] = b"MSWIN4.1"
    totsec16 = 0 if (fat32 or vol_sectors >= 0x10000) else vol_sectors
    totsec32 = 0 if totsec16 else vol_sectors
    struct.pack_into("<HBHBHHBHHHII", bs, 11, SECTOR, g.spc, g.rsvd,
                     g.nfats, g.root_ent, totsec16, MEDIA,
                     0 if fat32 else g.fatsz, SPT, HEADS, part_start,
                     totsec32)
    if fat32:
        struct.pack_into("<IHHIHH12sBBBI11s8s", bs, 36, g.fatsz, 0, 0, 2,
                         1, 6, bytes(12), 0x80, 0, 0x29, volid, vollab,
                         b"FAT32   ")
        bs[90:90 + len(BOOT_CODE)] = BOOT_CODE
    else:
        struct.pack_into("<BBBI11s8s", bs, 36, 0x80, 0, 0x29, volid,
                         vollab, b"FAT16   ")
        bs[62:62 + len(BOOT_CODE)] = BOOT_CODE
    bs[510:512] = b"\x55\xAA"

    # The MBR.
    if ptype is None:
        if fat32:
            last = part_start + vol_sectors - 1
            ptype = 0x0B if last // (HEADS * SPT) <= 1023 else 0x0C
        else:
            ptype = 0x06 if vol_sectors >= 0x10000 else 0x04
    mbr = bytearray(SECTOR)
    mbr[446:462] = struct.pack("<B3sB3sII", 0x00, chs(part_start), ptype,
                               chs(part_start + vol_sectors - 1),
                               part_start, vol_sectors)
    mbr[510:512] = b"\x55\xAA"

    # Write. Regions not written stay zero (and sparse on disk).
    base = part_start * SECTOR

    def at(sector):
        return base + sector * SECTOR

    def cluster_at(n):
        return at(g.first_data + (n - 2) * g.spc)

    with open(img, "wb") as f:
        write_at(f, 0, mbr, fresh=True)
        write_at(f, at(0), bs, fresh=True)
        if fat32:
            fsinfo = bytearray(SECTOR)
            struct.pack_into("<I", fsinfo, 0, 0x41615252)
            struct.pack_into("<III", fsinfo, 484, 0x61417272,
                             g.count - used,
                             nxt if nxt <= g.count + 1 else 0xFFFFFFFF)
            struct.pack_into("<I", fsinfo, 508, 0xAA550000)
            third = bytearray(SECTOR)
            third[510:512] = b"\x55\xAA"
            for start in (0, 6):
                write_at(f, at(start), bs + fsinfo + third, fresh=True)
        for i in range(g.nfats):
            write_at(f, at(g.rsvd + i * g.fatsz), fat, fresh=True)
        if fat32:
            write_at(f, cluster_at(root.first),
                     dir_bytes(root, 0, True, root.nclus * cb), fresh=True)
        else:
            write_at(f, at(g.rsvd + g.nfats * g.fatsz),
                     dir_bytes(root, 0, True, g.root_dir_sectors * SECTOR),
                     fresh=True)

        def emit(node):
            for c in node.children:
                if c.is_dir:
                    write_at(f, cluster_at(c.first),
                             dir_bytes(c, 0 if node is root else node.first,
                                       False, c.nclus * cb), fresh=True)
                    emit(c)
                elif c.size:
                    copy_in(f, c.host, c.size, cluster_at(c.first),
                            c.rel, fresh=True)
        emit(root)
        f.truncate(total_sectors * SECTOR)
    return g, used


def copy_in(f, host, size, off, what, fresh=False):
    """Copy a host file's bytes to byte off of the image."""
    got = 0
    with open(host, "rb") as src:
        while chunk := src.read(1 << 20):
            if got + len(chunk) > size:
                got += len(chunk)
                break
            write_at(f, off + got, chunk, fresh)
            got += len(chunk)
    if got != size:
        raise FatError(f"{what} changed size while being copied")


# ----------------------------------------------------------------------
# Reading

class Entry:
    def __init__(self, raw, path, long=None):
        self.name11 = raw[0:11]
        self.attr = raw[11]
        (self.ctenth, self.ctime, self.cdate, self.adate, hi, self.wtime,
         self.wdate, lo, self.size) = struct.unpack_from("<BHHHHHHHI",
                                                         raw, 13)
        self.hi, self.lo = hi, lo
        self.name = show_name(self.name11)
        self.long = long
        self.display = long or self.name
        self.path = path

    @property
    def is_dir(self):
        return bool(self.attr & ATTR_DIRECTORY)

    @property
    def is_label(self):
        return (self.attr & (ATTR_DIRECTORY | ATTR_VOLUME_ID)) \
            == ATTR_VOLUME_ID

    def matches(self, name):
        want = name.upper()
        return self.name == want or (self.long is not None
                                     and self.long.upper() == want)


def parse_entries(raws, path, notes=None):
    """[(Entry, [its slot indices: long entries, then the short one])]
    for a directory's 32-byte slots, assembling long names [Organization
    and Association of Short & Long Directory Entries]. Orphaned long
    entries are skipped, and noted in notes if given."""
    out, pend = [], None
    where = path or "/"

    def orphan(why):
        if notes is not None:
            notes.append(f"{where}: orphaned long-name entries ({why})")

    for i, raw in enumerate(raws):
        if raw[0] == 0x00:
            break
        if raw[0] == 0xE5:
            if pend:
                orphan("followed by a deleted entry")
            pend = None
            continue
        if raw[11] & 0x3F == ATTR_LONG_NAME:
            ordv, csum = raw[0], raw[13]
            units = (struct.unpack_from("<5H", raw, 1)
                     + struct.unpack_from("<6H", raw, 14)
                     + struct.unpack_from("<2H", raw, 28))
            if ordv & 0x40:
                if pend:
                    orphan("a new set began before the short entry")
                n = ordv & 0x3F
                pend = {"n": n, "csum": csum, "parts": {}, "next": n,
                        "slots": []} if 1 <= n <= 20 else None
                if pend is None:
                    orphan(f"ordinal {n}")
                    continue
            elif pend is None:
                orphan("no first (40h) entry")
                continue
            if (ordv & 0x3F) != pend["next"] or csum != pend["csum"]:
                orphan("ordinals or checksums out of step")
                pend = None
                continue
            pend["parts"][pend["next"]] = units
            pend["slots"].append(i)
            pend["next"] -= 1
            continue
        long, slots = None, [i]
        if pend:
            if pend["next"] == 0 and lfn_checksum(raw[0:11]) == pend["csum"]:
                chars = []
                for k in range(1, pend["n"] + 1):
                    for u in pend["parts"][k]:
                        if u == 0:
                            break
                        chars.append(chr(u))
                    else:
                        continue
                    break
                long = "".join(chars)
                slots = pend["slots"] + [i]
            else:
                orphan("their checksum doesn't match the short name"
                       if pend["next"] == 0 else "a short entry came early")
            pend = None
        name = long or show_name(raw[0:11])
        out.append((Entry(raw, f"{path}/{name}" if path else name, long),
                    slots))
    if pend:
        orphan("no short entry followed")
    return out


class Volume:
    """A FAT volume inside an image, read per fatgen103."""

    def __init__(self, path, writable=False):
        self.f = open(path, "r+b" if writable else "rb")
        self.img_size = os.fstat(self.f.fileno()).st_size
        sec0 = self.raw(0, SECTOR)
        if len(sec0) < SECTOR or sec0[510:512] != b"\x55\xAA":
            raise FatError("sector 0 has no 55AA signature")
        self.part = None
        for i in range(4):
            e = sec0[446 + 16 * i: 462 + 16 * i]
            status, ptype, start, count = struct.unpack("<B3xB3xII", e)
            if ptype in FAT_PTYPES and start and count:
                self.part = (i + 1, status, ptype, start, count)
                break
        if self.part:
            self.lba = self.part[3]
        elif self.looks_like_bpb(sec0):
            self.lba = 0                 # an unpartitioned "superfloppy"
        else:
            raise FatError("no FAT partition in the MBR, and sector 0 "
                           "isn't a FAT boot sector")
        bs = self.raw(self.lba * SECTOR, SECTOR)
        self.bs = bs
        if bs[510:512] != b"\x55\xAA":
            raise FatError("the boot sector has no 55AA signature")
        (self.bps, self.spc, self.rsvd, self.nfats, self.root_ent,
         totsec16, self.media, fatsz16, self.spt, self.heads,
         self.hidden, totsec32) = struct.unpack_from("<HBHBHHBHHHII",
                                                     bs, 11)
        if self.bps not in (512, 1024, 2048, 4096):
            raise FatError(f"BPB_BytsPerSec is {self.bps}")
        if self.spc == 0 or self.spc & (self.spc - 1):
            raise FatError(f"BPB_SecPerClus is {self.spc}")
        if self.rsvd == 0 or self.nfats == 0:
            raise FatError("BPB_RsvdSecCnt or BPB_NumFATs is 0")
        self.root_dir_sectors = ((self.root_ent * 32 + self.bps - 1)
                                 // self.bps)
        self.fatsz = fatsz16 or struct.unpack_from("<I", bs, 36)[0]
        self.totsec = totsec16 or totsec32
        self.first_data = (self.rsvd + self.nfats * self.fatsz
                           + self.root_dir_sectors)
        if self.totsec <= self.first_data:
            raise FatError("the volume is smaller than its own FATs")
        self.count = (self.totsec - self.first_data) // self.spc
        self.type = fat_type_of(self.count)
        if self.type == "FAT12":
            raise FatError("FAT12 volumes aren't supported")
        self.fat32 = self.type == "FAT32"
        self.cb = self.spc * self.bps
        if self.fat32:
            (self.ext_flags, self.fsver, self.root_clus, self.fsinfo,
             self.bkboot) = struct.unpack_from("<HHIHH", bs, 40)
            ext = 64
        else:
            ext = 36
        (self.drvnum, _, self.bootsig, self.volid, self.vollab,
         self.fstype) = struct.unpack_from("<BBBI11s8s", bs, ext)
        self.eoc_min = 0x0FFFFFF8 if self.fat32 else 0xFFF8
        self.bad = 0x0FFFFFF7 if self.fat32 else 0xFFF7
        self.fats = [self.raw(self.sector_at(self.rsvd + i * self.fatsz),
                              self.fatsz * self.bps)
                     for i in range(self.nfats)]
        need = (self.count + 2) * (4 if self.fat32 else 2)
        if len(self.fats[0]) < need:
            raise FatError(f"the FAT holds {len(self.fats[0])} bytes, but "
                           f"{self.count} clusters need {need}")
        self.fat = self.fats[0]

    @staticmethod
    def looks_like_bpb(s):
        bps, spc = struct.unpack_from("<HB", s, 11)
        return (s[0] in (0xEB, 0xE9) and bps in (512, 1024, 2048, 4096)
                and spc and not spc & (spc - 1) and s[21] >= 0xF0)

    def raw(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def sector_at(self, vol_sector):
        return self.lba * SECTOR + vol_sector * self.bps

    def cluster_at(self, n):
        return self.sector_at(self.first_data + (n - 2) * self.spc)

    def cluster_lba(self, n):
        """The card sector (LBA) where cluster n starts."""
        return self.cluster_at(n) // SECTOR

    def entry(self, n, fat=None):
        fat = self.fat if fat is None else fat
        if self.fat32:
            return struct.unpack_from("<I", fat, n * 4)[0] & 0x0FFFFFFF
        return struct.unpack_from("<H", fat, n * 2)[0]

    def chain(self, first, what):
        """The clusters of a chain, or FatError saying what's wrong."""
        out, seen, n = [], set(), first
        while True:
            if not 2 <= n <= self.count + 1:
                raise FatError(f"{what}: cluster {n} is out of range "
                               f"(2..{self.count + 1})")
            if n in seen:
                raise FatError(f"{what}: the chain loops at cluster {n}")
            seen.add(n)
            out.append(n)
            v = self.entry(n)
            if v >= self.eoc_min:
                return out
            if v == 0:
                raise FatError(f"{what}: the chain runs into free "
                               f"cluster {n}'s entry")
            if v == self.bad:
                raise FatError(f"{what}: cluster {n} is marked bad")
            n = v

    def read_clusters(self, clusters):
        return b"".join(self.raw(self.cluster_at(c), self.cb)
                        for c in clusters)

    def first_cluster(self, e):
        return ((e.hi << 16) if self.fat32 else 0) | e.lo

    def dir_slots(self, d):
        """(clusters, [(image offset, 32 raw bytes)]) for a directory:
        d an Entry, or None for the root. clusters is None for a FAT16
        root, which is a fixed region rather than a chain."""
        if d is not None and self.first_cluster(d) == 0:
            d = None                      # ".." back to the root
        if d is None and not self.fat32:
            base = self.sector_at(self.rsvd + self.nfats * self.fatsz)
            data = self.raw(base, self.root_ent * 32)
            return None, [(base + i, data[i:i + 32])
                          for i in range(0, len(data), 32)]
        first = self.root_clus if d is None else self.first_cluster(d)
        clusters = self.chain(first, d.path if d else "/")
        out = []
        for c in clusters:
            base = self.cluster_at(c)
            data = self.raw(base, self.cb)
            out += [(base + i, data[i:i + 32])
                    for i in range(0, self.cb, 32)]
        return clusters, out

    def items(self, d, notes=None):
        """[(Entry, slot indices)] for directory d (None: the root)."""
        _, slots = self.dir_slots(d)
        path = d.path if d is not None and self.first_cluster(d) else ""
        return parse_entries([raw for _, raw in slots], path, notes)

    def root_entries(self, notes=None):
        return [e for e, _ in self.items(None, notes)]

    def dir_entries(self, e, notes=None):
        return [x for x, _ in self.items(e, notes)]

    def label(self):
        for e in self.root_entries():
            if e.is_label:
                return e.name11.decode("latin-1").rstrip(" ")
        return None

    def lookup(self, path):
        """The Entry for a path (None for the root), case-insensitively,
        by long or short names."""
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        cur = None
        for i, part in enumerate(parts):
            ents = self.root_entries() if cur is None \
                else self.dir_entries(cur)
            for e in ents:
                if not e.is_label and e.matches(part):
                    cur = e
                    break
            else:
                raise FatError(f"{'/'.join(parts[:i + 1])}: not found")
            if i < len(parts) - 1 and not cur.is_dir:
                raise FatError(f"{'/'.join(parts[:i + 1])}: not a "
                               f"directory")
        if cur is not None and cur.is_dir and self.first_cluster(cur) == 0:
            return None                   # a ".." that leads to the root
        return cur

    def listing(self, d):
        ents = self.root_entries() if d is None else self.dir_entries(d)
        return [e for e in ents if not e.is_label]

    def read_file(self, e):
        first = self.first_cluster(e)
        if first == 0:
            if e.size:
                raise FatError(f"{e.path}: {e.size} bytes but no "
                               f"clusters")
            return b""
        clusters = self.chain(first, e.path)
        need = -(-e.size // self.cb)
        if len(clusters) != need:
            raise FatError(f"{e.path}: {e.size} bytes need {need} "
                           f"clusters, but its chain has {len(clusters)}")
        return self.read_clusters(clusters)[:e.size]


# ----------------------------------------------------------------------
# check: a small fsck, to agree (or not) with fsck_msdos

def check(vol):
    problems = []
    for i in range(1, vol.nfats):
        if vol.fats[i] != vol.fats[0]:
            problems.append(f"FAT {i + 1} differs from FAT 1")
    full = 0x0FFFFFFF if vol.fat32 else 0xFFFF
    if vol.entry(0) != (full & ~0xFF) | vol.media:
        problems.append(f"FAT[0] is {vol.entry(0):X}h, not the media "
                        f"byte {vol.media:02X}h with every other bit set")
    flags = 0x0C000000 if vol.fat32 else 0xC000   # clean/no-error bits
    if vol.entry(1) | flags < vol.eoc_min:
        problems.append(f"FAT[1] is {vol.entry(1):X}h, not an EOC mark")
    if vol.totsec > (vol.part[4] if vol.part
                     else vol.img_size // SECTOR):
        problems.append("the BPB's total sectors run past the partition")

    owner = {}
    labels = []

    def claim(clusters, path):
        for c in clusters:
            if c in owner:
                problems.append(f"{path} and {owner[c]} are cross-linked "
                                f"at cluster {c}")
                return False
            owner[c] = path
        return True

    def visit(ents, dirpath, self_first, parent_first):
        names = set()
        if dirpath:
            if (len(ents) < 2 or ents[0].name11 != b".          "
                    or ents[1].name11 != b"..         "):
                problems.append(f"{dirpath}: doesn't start with . and ..")
            else:
                if vol.first_cluster(ents[0]) != self_first:
                    problems.append(f"{dirpath}/.: points at cluster "
                                    f"{vol.first_cluster(ents[0])}, not "
                                    f"{self_first}")
                if vol.first_cluster(ents[1]) != parent_first:
                    problems.append(f"{dirpath}/..: points at cluster "
                                    f"{vol.first_cluster(ents[1])}, not "
                                    f"{parent_first}")
            ents = ents[2:]
        for e in ents:
            if e.is_label:
                labels.append(e.path)
                if dirpath:
                    problems.append(f"{e.path}: a volume label outside "
                                    f"the root")
                continue
            # One namespace of long and short names, ignoring case
            # [Name Matching In Short & Long Names].
            keys = {e.name} | ({e.long.upper()} if e.long else set())
            if e.name11[0] == 0x20 or keys & names:
                problems.append(f"{e.path}: a bad or duplicate name")
            names |= keys
            first = vol.first_cluster(e)
            if e.is_dir:
                if first == 0:
                    problems.append(f"{e.path}: a directory with no "
                                    f"cluster")
                    continue
                try:
                    clusters = vol.chain(first, e.path)
                except FatError as err:
                    problems.append(str(err))
                    continue
                if claim(clusters, e.path):
                    raws = vol.read_clusters(clusters)
                    sub = [x for x, _ in parse_entries(
                        [raws[k:k + 32] for k in range(0, len(raws), 32)],
                        e.path, problems)]
                    visit(sub, e.path, first,
                          self_first if dirpath else 0)
            else:
                if first == 0:
                    if e.size:
                        problems.append(f"{e.path}: {e.size} bytes but "
                                        f"no clusters")
                    continue
                try:
                    clusters = vol.chain(first, e.path)
                except FatError as err:
                    problems.append(str(err))
                    continue
                claim(clusters, e.path)
                need = -(-e.size // vol.cb)
                if len(clusters) != need:
                    problems.append(f"{e.path}: {e.size} bytes need "
                                    f"{need} clusters, but its chain has "
                                    f"{len(clusters)}")

    try:
        if vol.fat32:
            claim(vol.chain(vol.root_clus, "/"), "/")
        visit(vol.root_entries(problems), "", 0, 0)
    except FatError as err:
        problems.append(str(err))
    if len(labels) > 1:
        problems.append(f"{len(labels)} volume labels")

    free = 0
    for n in range(2, vol.count + 2):
        v = vol.entry(n)
        if v == 0:
            free += 1
        elif n not in owner and v != vol.bad:
            problems.append(f"cluster {n} is allocated but in no chain "
                            f"(lost)")
    if vol.fat32:
        fsi = vol.raw(vol.sector_at(vol.fsinfo), SECTOR)
        lead, = struct.unpack_from("<I", fsi, 0)
        sig, fcount, nfree = struct.unpack_from("<III", fsi, 484)
        trail, = struct.unpack_from("<I", fsi, 508)
        if (lead, sig, trail) != (0x41615252, 0x61417272, 0xAA550000):
            problems.append("FSInfo signatures are wrong")
        if fcount not in (free, 0xFFFFFFFF):
            problems.append(f"FSInfo says {fcount} free clusters; there "
                            f"are {free}")
        # The backup boot record [FAT32 FSInfo Sector Structure and
        # Backup Boot Sector]: sector 6 copies sector 0 (the backup
        # FSInfo may go stale, so it isn't compared).
        if vol.bkboot and vol.raw(vol.sector_at(vol.bkboot), vol.bps) \
                != vol.raw(vol.sector_at(0), vol.bps):
            problems.append(f"the backup boot sector ({vol.bkboot}) "
                            f"differs from sector 0")
    return problems, free


# ----------------------------------------------------------------------
# Changing an image: put and rm

class Editor:
    """An image opened for one change, with a working copy of its FAT and
    of one directory's slots, written back in a safe order."""

    def __init__(self, img):
        self.vol = vol = Volume(img, writable=True)
        problems, _ = check(vol)
        if problems:
            raise FatError(f"{img} fails check ({problems[0]}); not "
                           f"writing to it")
        self.fat = bytearray(vol.fat)
        self.w = 4 if vol.fat32 else 2
        self.eoc = 0x0FFFFFFF if vol.fat32 else 0xFFFF

    def get(self, n):
        if self.w == 4:
            return struct.unpack_from("<I", self.fat, n * 4)[0] & 0x0FFFFFFF
        return struct.unpack_from("<H", self.fat, n * 2)[0]

    def set(self, n, v):
        if self.w == 4:     # keep the reserved high 4 bits
            hi = struct.unpack_from("<I", self.fat, n * 4)[0] & 0xF0000000
            struct.pack_into("<I", self.fat, n * 4, hi | v)
        else:
            struct.pack_into("<H", self.fat, n * 2, v)

    def open_dir(self, path):
        """Load directory path's slots: self.d, self.offs, self.raws."""
        vol = self.vol
        d = vol.lookup(path)
        if d is not None and not d.is_dir:
            raise FatError(f"{path}: not a directory")
        self.d = d
        self.dpath = d.path if d is not None else ""
        self.clusters, slots = vol.dir_slots(d)
        self.offs = [o for o, _ in slots]
        self.raws = [r for _, r in slots]
        self.changed = set()

    def items(self):
        return parse_entries(self.raws, self.dpath)

    def find(self, name):
        for e, slots in self.items():
            if not e.is_label and e.matches(name):
                return e, slots
        return None, None

    def delete(self, e, slots):
        """Mark an entry and its long entries free, and free its chain."""
        for i in slots:
            self.raws[i] = b"\xE5" + self.raws[i][1:]
            self.changed.add(i)
        first = self.vol.first_cluster(e)
        if first:
            for c in self.vol.chain(first, e.path):
                self.set(c, 0)

    def find_run(self, n):
        best, start, length = 0, None, 0
        for c in range(2, self.vol.count + 2):
            if self.get(c) == 0:
                if length == 0:
                    start = c
                length += 1
                if length == n:
                    return start, best
            else:
                best, length = max(best, length), 0
        return None, max(best, length)

    def free_slots(self, k):
        """The index of the first run of k free slots, growing the
        directory by zeroed clusters if it must."""
        run = 0
        for i, raw in enumerate(self.raws):
            if raw[0] in (0x00, 0xE5):
                run += 1
                if run == k:
                    return i - k + 1
            else:
                run = 0
        if self.clusters is None:
            raise FatError(f"the root directory is full ({len(self.raws)} "
                           f"entries, fixed on FAT16); nothing was written")
        per = self.vol.cb // 32
        grow = -(-(k - run) // per)
        if len(self.raws) + grow * per > 65536:
            raise FatError(f"{self.dpath or '/'}: a FAT directory holds at "
                           f"most 65536 entries")
        self.grown = getattr(self, "grown", [])
        for _ in range(grow):
            c, _ = self.find_run(1)
            if c is None:
                raise FatError(f"no free cluster to grow "
                               f"{self.dpath or '/'}; nothing was written")
            self.set(self.clusters[-1], c)
            self.set(c, self.eoc)
            self.clusters.append(c)
            self.grown.append(c)
            base = self.vol.cluster_at(c)
            self.offs += [base + j * 32 for j in range(per)]
            self.raws += [bytes(32)] * per
        return len(self.raws) - (grow * per) - run

    def write_entries(self, f, changed):
        for i in sorted(changed):
            f.seek(self.offs[i])
            f.write(self.raws[i])

    def write_fat(self, f):
        vol = self.vol
        for i in range(vol.nfats):
            old, base = vol.fats[i], vol.sector_at(vol.rsvd + i * vol.fatsz)
            for s in range(0, len(self.fat), vol.bps):
                new = self.fat[s:s + vol.bps]
                if new != old[s:s + vol.bps]:
                    f.seek(base + s)
                    f.write(new)
        if vol.fat32 and vol.fsinfo:
            free = sum(1 for c in range(2, vol.count + 2)
                       if self.get(c) == 0)
            nxt = next((c for c in range(2, vol.count + 2)
                        if self.get(c) == 0), 0xFFFFFFFF)
            f.seek(vol.sector_at(vol.fsinfo) + 488)
            f.write(struct.pack("<II", free, nxt))


def put(img, host, dest, name=None, replace=False, stamp=None, lfn=False,
        at=None):
    """Add a host file to directory dest; returns (path, runs)."""
    if not os.path.isfile(host):
        raise FatError(f"{host}: not a regular file")
    size = os.path.getsize(host)
    if size > 0xFFFFFFFF:
        raise FatError(f"{host}: larger than FAT's 4 GiB limit")
    shown = name or os.path.basename(host)
    if lfn:
        check_long(shown, shown)
    else:
        short_name(shown, shown)
    ed = Editor(img)
    vol, f = ed.vol, ed.vol.f
    ed.open_dir(dest)

    old, old_slots = ed.find(shown)
    deleted = set()
    if old:
        where = old.path
        if old.attr & (ATTR_DIRECTORY | ATTR_VOLUME_ID):
            raise FatError(f"{where}: already there, and not a file")
        if not replace:
            raise FatError(f"{where}: already there (--replace to "
                           f"overwrite it)")
        ed.delete(old, old_slots)
        deleted = set(ed.changed)

    taken = {e.name11 for e, _ in ed.items()}
    if lfn and needs_long(shown) and not fit_83(shown)[0]:
        name11 = make_alias(shown, taken)
    else:
        name11 = short_name(shown, shown)
        if name11 in taken:
            raise FatError(f"{show_name(name11)} is already taken in "
                           f"{dest or '/'}")
    long = shown if lfn and needs_long(shown) else None
    where = (ed.dpath + "/" if ed.dpath else "") + (long or show_name(name11))
    ents = (lfn_entries(long, name11) if long else []) \
        + [dirent(name11, ATTR_ARCHIVE, 0, size, stamp or dos_stamp(
            datetime.datetime.fromisoformat(DEFAULT_STAMP)))]

    # Clusters: first fit, or exactly where --at says.
    need = -(-size // vol.cb)
    runs = []
    if need and at:
        k = len(at)
        if need < k:
            raise FatError(f"{where} has {need} clusters; it can't be "
                           f"split into {k} pieces")
        sizes = [need // k + (1 if j < need % k else 0) for j in range(k)]
        mine = set()
        for start, n in zip(at, sizes):
            for c in range(start, start + n):
                if not 2 <= c <= vol.count + 1:
                    raise FatError(f"--at {start}: cluster {c} is out of "
                                   f"range (2..{vol.count + 1})")
                if ed.get(c) != 0 or c in mine:
                    raise FatError(f"--at {start}: cluster {c} isn't free")
                mine.add(c)
            runs.append((start, n))
    elif need:
        first, largest = ed.find_run(need)
        if first is None:
            raise FatError(f"{where} needs {need} contiguous clusters of "
                           f"{vol.cb} bytes; the largest free run is "
                           f"{largest}, and esxDOS needs some files "
                           f"unfragmented, so nothing was written")
        runs = [(first, need)]
    clusters = [c for start, n in runs for c in range(start, start + n)]
    for a, b in zip(clusters, clusters[1:]):
        ed.set(a, b)
    if clusters:
        ed.set(clusters[-1], ed.eoc)
    first = clusters[0] if clusters else 0
    ents[-1] = dirent(name11, ATTR_ARCHIVE, first, size, stamp or dos_stamp(
        datetime.datetime.fromisoformat(DEFAULT_STAMP)))

    start = ed.free_slots(len(ents))
    for j, raw in enumerate(ents):
        ed.raws[start + j] = raw

    # 0. a replaced file's entries go first, so nothing points at clusters
    #    about to be reused
    ed.write_entries(f, deleted)
    # 1. the data, each run's slack zeroed; any new directory clusters
    if clusters:
        done = 0
        with open(host, "rb") as src:
            for c in clusters:
                chunk = src.read(vol.cb)
                done += len(chunk)
                write_at(f, vol.cluster_at(c),
                         chunk + bytes(vol.cb - len(chunk)))
            if done != size or src.read(1):
                raise FatError(f"{host} changed size while being copied")
    for c in getattr(ed, "grown", []):
        write_at(f, vol.cluster_at(c), bytes(vol.cb))
    # 2. every FAT copy, and FAT32's FSInfo
    ed.write_fat(f)
    # 3. the new entries, long ones before the short one
    for j in range(len(ents)):
        f.seek(ed.offs[start + j])
        f.write(ed.raws[start + j])
    f.close()
    return where, runs


def rm(img, path):
    parent, _, leaf = path.replace("\\", "/").strip("/").rpartition("/")
    if not leaf:
        raise FatError("rm needs a file's path")
    ed = Editor(img)
    ed.open_dir(parent)
    e, slots = ed.find(leaf)
    if e is None or leaf in (".", ".."):
        raise FatError(f"{path}: not found")
    if e.attr & (ATTR_DIRECTORY | ATTR_VOLUME_ID):
        raise FatError(f"{path}: not a file (rm removes files only)")
    ed.delete(e, slots)
    f = ed.vol.f
    ed.write_entries(f, ed.changed)      # the entries first, then the FAT
    ed.write_fat(f)
    f.close()
    return e.path


def file_runs(vol, e):
    """[(first cluster, count)] for a file's chain."""
    first = vol.first_cluster(e)
    if not first:
        return []
    out = []
    for c in vol.chain(first, e.path):
        if out and out[-1][0] + out[-1][1] == c:
            out[-1][1] += 1
        else:
            out.append([c, 1])
    return [tuple(r) for r in out]


# ----------------------------------------------------------------------
# The command line

def parse_stamp(text):
    try:
        return dos_stamp(datetime.datetime.fromisoformat(text))
    except ValueError:
        raise FatError(f"--stamp {text!r}: use YYYY-MM-DDTHH:MM:SS")


def cmd_build(a):
    if a.mtimes and a.stamp != DEFAULT_STAMP:
        raise FatError("--mtimes and --stamp don't mix")
    parse_stamp(a.stamp)
    stamp = datetime.datetime.fromisoformat(a.stamp)
    spc = None
    if a.cluster_kb is not None:
        spc = a.cluster_kb * 2
    g, used = build(a.img, a.dir, a.size_mb, a.label, a.fat32, stamp,
                    a.mtimes, a.volid, a.ptype, a.part_start, spc, a.lfn)
    kind = "FAT32" if g.fat32 else "FAT16"
    print(f"{a.img}: {a.size_mb} MiB, {kind} from LBA {a.part_start}, "
          f"{g.count} clusters of {g.cluster_bytes} bytes, {used} used")


def cmd_ls(a):
    vol = Volume(a.img)
    top = vol.lookup(a.path or "")
    if top is not None and not top.is_dir:
        show_entries(vol, [top], a, "")
        return

    def go(d, prefix):
        ents = vol.listing(d)
        if not a.all:
            ents = [e for e in ents if e.name not in (".", "..")]
        show_entries(vol, ents, a, prefix)
        if a.recursive:
            for e in ents:
                if e.is_dir and e.name not in (".", ".."):
                    go(e, f"{prefix}{e.display}/")
    go(top, "")


def show_entries(vol, ents, a, prefix):
    for e in ents:
        name = prefix + e.display + ("/" if e.is_dir else "")
        if a.long:
            kind = "d" if e.is_dir else "-"
            alias = f"  [{e.name}]" if e.long else ""
            print(f"{kind} {e.size:>10}  {stamp_text(e.wdate, e.wtime)}  "
                  f"@{vol.first_cluster(e):<6} {name}{alias}")
        else:
            print(name)


def cmd_cat(a):
    vol = Volume(a.img)
    e = vol.lookup(a.path)
    if e is None or e.is_dir:
        raise FatError(f"{a.path}: a directory")
    sys.stdout.buffer.write(vol.read_file(e))


def cmd_info(a):
    vol = Volume(a.img)
    if vol.part:
        num, status, ptype, start, count = vol.part
        print(f"partition {num}: type {ptype:02X}h, status {status:02X}h, "
              f"LBA {start}, {count} sectors")
    else:
        print("no partition table: the volume starts at sector 0")
    print(f"type            {vol.type} ({vol.count} clusters of "
          f"{vol.cb} bytes)")
    print(f"BS_OEMName      {vol.bs[3:11].decode('latin-1')!r}")
    for name, val in [
            ("BPB_BytsPerSec", vol.bps), ("BPB_SecPerClus", vol.spc),
            ("BPB_RsvdSecCnt", vol.rsvd), ("BPB_NumFATs", vol.nfats),
            ("BPB_RootEntCnt", vol.root_ent),
            ("BPB_Media", f"{vol.media:02X}h"),
            ("FAT size", f"{vol.fatsz} sectors"),
            ("total sectors", vol.totsec),
            ("BPB_SecPerTrk", vol.spt), ("BPB_NumHeads", vol.heads),
            ("BPB_HiddSec", vol.hidden),
            ("BS_VolID", f"{vol.volid >> 16:04X}-{vol.volid & 0xFFFF:04X}"),
            ("BS_VolLab", repr(vol.vollab.decode("latin-1"))),
            ("BS_FilSysType", repr(vol.fstype.decode("latin-1")))]:
        print(f"{name:<15} {val}")
    if vol.fat32:
        print(f"BPB_RootClus    {vol.root_clus}")
        print(f"BPB_FSInfo      {vol.fsinfo}")
        print(f"BPB_BkBootSec   {vol.bkboot}")
    print(f"first data LBA  {vol.cluster_lba(2)} (cluster 2)")
    print(f"label entry     {vol.label()!r}")


def cmd_check(a):
    vol = Volume(a.img)
    problems, free = check(vol)
    for p in problems:
        print(p)
    if problems:
        raise FatError(f"{len(problems)} problem(s)")
    print(f"{a.img}: {vol.type}, clean; {vol.count - free} of "
          f"{vol.count} clusters used")


def cmd_put(a):
    if a.mtime and a.stamp != DEFAULT_STAMP:
        raise FatError("--mtime and --stamp don't mix")
    stamp = mtime_stamp(os.stat(a.hostfile)) if a.mtime \
        else parse_stamp(a.stamp)
    at = None
    if a.at:
        try:
            at = [int(x, 0) for x in a.at.split(",")]
        except ValueError:
            raise FatError(f"--at {a.at!r}: cluster numbers, comma-separated")
    where, runs = put(a.img, a.hostfile, a.dir, a.name, a.replace, stamp,
                      a.lfn, at)
    text = ", ".join(f"{s}..{s + n - 1}" for s, n in runs) or "no clusters"
    print(f"{a.img}: put {where} (clusters {text})")


def cmd_rm(a):
    print(f"{a.img}: removed {rm(a.img, a.path)}")


def cmd_runs(a):
    vol = Volume(a.img)
    e = vol.lookup(a.path)
    if e is None or e.is_dir:
        raise FatError(f"{a.path}: not a file")
    first = vol.first_cluster(e)
    runs = file_runs(vol, e)
    print(f"{e.path}: {e.size} bytes, {sum(n for _, n in runs)} clusters "
          f"of {vol.cb} bytes, {len(runs)} run(s)")
    print(f"  first cluster {first} = {first:#010x} (high word "
          f"{first >> 16:#06x}, low word {first & 0xFFFF:#06x})")
    for s, n in runs:
        lba = vol.cluster_lba(s)
        print(f"  clusters {s}..{s + n - 1} ({n}): LBA {lba}.."
              f"{lba + n * vol.spc - 1} ({n * vol.spc} sectors)")
    # Where its short entry sits in its directory.
    parent = e.path.rpartition("/")[0]
    d = vol.lookup(parent) if parent else None
    clusters, slots = vol.dir_slots(d)
    for x, idx in parse_entries([r for _, r in slots], parent):
        if x.name11 == e.name11:
            i = idx[-1]
            per = vol.cb // 32
            if clusters is None:
                print(f"  entry: slot {i} of the FAT16 root, LBA "
                      f"{slots[i][0] // SECTOR}")
            else:
                print(f"  entry: slot {i} of {parent or '/'}, in its "
                      f"cluster #{i // per + 1} of {len(clusters)} "
                      f"(cluster {clusters[i // per]}, LBA "
                      f"{slots[i][0] // SECTOR})")
            break


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mkfat.py",
        description="Build and read SD-card images (an MBR and one FAT16 "
                    "or FAT32 partition) for divMMC/esxDOS.")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build IMG from the tree in DIR",
                       description="Build IMG from the tree in DIR: an MBR "
                       "and one FAT partition. Same input, same bytes.")
    b.add_argument("img")
    b.add_argument("dir")
    b.add_argument("--size-mb", type=int, default=64,
                   help="image size in MiB (default 64)")
    b.add_argument("--label", default=DEFAULT_LABEL,
                   help=f"volume label (default {DEFAULT_LABEL}; '' for "
                        f"none)")
    b.add_argument("--fat32", action="store_true",
                   help="FAT32 instead of FAT16 (needs 34 MiB or more)")
    b.add_argument("--part-start", type=int, default=PART_START,
                   help=f"the partition's first sector (default "
                        f"{PART_START}; 32 GB SDHC cards use 8192)")
    b.add_argument("--cluster-kb", type=int, default=None,
                   help="cluster size in KB, instead of fatgen103's table")
    b.add_argument("--lfn", action="store_true",
                   help="write long names for names that aren't 8.3 "
                        "(esxDOS 0.8.9 ignores them)")
    b.add_argument("--stamp", default=DEFAULT_STAMP,
                   help=f"the fixed timestamp (default {DEFAULT_STAMP})")
    b.add_argument("--mtimes", action="store_true",
                   help="use each file's own mtime instead (not "
                        "deterministic)")
    b.add_argument("--volid", type=lambda s: int(s, 16), default=None,
                   help="BS_VolID in hex (default: from the stamp)")
    b.add_argument("--ptype", type=lambda s: int(s, 16), default=None,
                   help="MBR partition type in hex (default 06/04 for "
                        "FAT16, 0B/0C for FAT32)")
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("ls", help="list a directory in IMG")
    s.add_argument("img")
    s.add_argument("path", nargs="?", default="")
    s.add_argument("-l", "--long", action="store_true",
                   help="size, write time, first cluster, and the short "
                        "alias of a long name")
    s.add_argument("-R", "--recursive", action="store_true")
    s.add_argument("-a", "--all", action="store_true",
                   help="show . and .. too")
    s.set_defaults(fn=cmd_ls)

    c = sub.add_parser("cat", help="write a file from IMG to stdout")
    c.add_argument("img")
    c.add_argument("path")
    c.set_defaults(fn=cmd_cat)

    i = sub.add_parser("info", help="show IMG's partition and BPB")
    i.add_argument("img")
    i.set_defaults(fn=cmd_info)

    k = sub.add_parser("check", help="check IMG's FAT structures (a small "
                       "fsck; exits 1 on any problem)")
    k.add_argument("img")
    k.set_defaults(fn=cmd_check)

    u = sub.add_parser("put", help="add one file to an existing IMG",
                       description="Add HOSTFILE to directory DIR (default "
                       "the root) of an existing image, in one contiguous "
                       "run of clusters, or where --at says.")
    u.add_argument("img")
    u.add_argument("hostfile")
    u.add_argument("dir", nargs="?", default="")
    u.add_argument("--as", dest="name", default=None,
                   help="the name to give it (default: the host name)")
    u.add_argument("--replace", action="store_true",
                   help="overwrite a file of that name")
    u.add_argument("--lfn", action="store_true",
                   help="allow a long name (with a generated alias)")
    u.add_argument("--at", default=None, metavar="CLUSTER[,CLUSTER...]",
                   help="put it at these clusters: one start for one "
                        "piece, several to split it (for testing readers)")
    u.add_argument("--stamp", default=DEFAULT_STAMP,
                   help=f"its timestamp (default {DEFAULT_STAMP})")
    u.add_argument("--mtime", action="store_true",
                   help="use the host file's mtime instead")
    u.set_defaults(fn=cmd_put)

    r = sub.add_parser("rm", help="remove a file from IMG")
    r.add_argument("img")
    r.add_argument("path")
    r.set_defaults(fn=cmd_rm)

    n = sub.add_parser("runs", help="show a file's clusters as runs, with "
                       "card sectors, and where its entry sits")
    n.add_argument("img")
    n.add_argument("path")
    n.set_defaults(fn=cmd_runs)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (FatError, OSError) as err:
        print(f"mkfat: {err}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
