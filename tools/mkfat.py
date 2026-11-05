#!/usr/bin/env python3
"""mkfat.py: build and read SD-card images for divMMC (esxDOS).

An image is an MBR with one FAT16 (or, with --fat32, FAT32) partition,
holding a host directory tree under 8.3 names. Pure Python 3, standard
library only, so it runs anywhere omse-ai does.

    mkfat.py build IMG DIR [--size-mb N] [--label NAME] [--fat32]
                           [--mtimes | --stamp YYYY-MM-DDTHH:MM:SS]
    mkfat.py ls    IMG [PATH] [-l] [-R] [-a]
    mkfat.py cat   IMG PATH
    mkfat.py info  IMG
    mkfat.py check IMG
    mkfat.py put   IMG HOSTFILE [DIR] [--as NAME] [--replace]

Written on 5 Nov 2026 by Fern (the instance of her called Loam; for this
work she inhabited Claude Opus 5.5), from Melissa O'Neill's idea, to a
brief by Speccy-Zone (another instance of Fern), who built omse-ai's
divMMC and booted esxDOS from the first card this made.

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
    LBA 1..2047    zero: the partition starts at 1 MiB, as SD cards are
                   formatted, so FAT structures sit on erase-block bounds
    LBA 2048..end  the FAT volume, filling the rest of the image

Inside the volume, [FAT Data Structure]: the reserved region (FAT16: the
boot sector alone; FAT32: 32 sectors), two FATs, the FAT16 root
directory (512 entries, 32 sectors), then the data region from cluster 2.

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
    454  LBA start     2048
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
                       64 MiB image: 2K clusters (FAT16), 512 bytes (FAT32)
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
    28  BPB_HiddSec    2048, the sectors preceding the partition
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
                    A host name that doesn't fit is an error naming it:
                    esxDOS 0.8.9 has no long names, so neither do we
                    (no LFN entries are ever written). Names beginning
                    with "." (macOS's .DS_Store and friends) are skipped
                    with a note on stderr.
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

DETERMINISM
-----------
The same tree, size, label and options give the same bytes: sorted
order, a fixed stamp, a VolID derived from it, and nothing taken from
the clock. (--mtimes trades that away on purpose.)

PUT: ADDING ONE FILE TO AN EXISTING IMAGE
-----------------------------------------
put refuses an image that fails check, then works as a DOS would. The
file gets the first run of free clusters long enough to hold it whole
(first fit; never fragmented, so it refuses rather than scatter it). Its
entry goes in the first free slot of DIR (00h or E5h [DIR_Name[0]]); a
full subdirectory, or a full FAT32 root, grows by one zeroed cluster,
while a full FAT16 root is fixed at 512 entries and refuses. The
writes go data first, then every FAT copy, then the directory entry, so
an interrupted put leaves at worst lost clusters, never an entry
pointing at garbage. The slack after the file's last byte is zeroed.
FAT32's FSInfo free count and next-free hint are updated. With
--replace, an existing file of that name is freed first and its slot
reused. The same image and file give the same bytes, but put appends
where a DOS would, so it needn't match a fresh build of the same tree.
"""

import argparse
import datetime
import os
import stat
import struct
import sys

SECTOR = 512
PART_START = 2048          # LBA of the partition: 1 MiB alignment
HEADS, SPT = 255, 63       # CHS geometry for the MBR and the BPB
MEDIA = 0xF8
DEFAULT_STAMP = "2026-11-05T00:00:00"
DEFAULT_LABEL = "DIVMMC"

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
BOOT_CODE = bytes([0xCD, 0x18, 0xF4, 0xEB, 0xFD])

# Partition types that hold a FAT volume, for the reader.
FAT_PTYPES = {0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E}


class FatError(Exception):
    """Anything wrong with a tree, an option, or an image."""


def warn(msg):
    print(f"mkfat: {msg}", file=sys.stderr)


# ----------------------------------------------------------------------
# Names, labels and timestamps

def short_name(name, where):
    """A host name as an 11-byte DIR_Name, or FatError naming it."""
    def bad(why):
        raise FatError(f"{where}: {why}; esxDOS 0.8.9 needs 8.3 names "
                       f"(no long file names)")
    if not name.isascii():
        bad("not ASCII")
    up = name.upper()
    if up.count(".") > 1:
        bad("more than one '.'")
    base, _, ext = up.partition(".")
    if not base:
        bad("empty name before the '.'")
    if len(base) > 8:
        bad(f"name part '{base}' is longer than 8 characters")
    if len(ext) > 3:
        bad(f"extension '{ext}' is longer than 3 characters")
    for ch in base + ext:
        if not (ch.isalnum() or ch in NAME_SPECIALS):
            bad(f"character {ch!r} isn't allowed in a short name")
    return (base.ljust(8) + ext.ljust(3)).encode("ascii")


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


def stamp_text(date, time):
    y, mo, d = 1980 + (date >> 9), (date >> 5) & 15, date & 31
    h, mi, s = time >> 11, (time >> 5) & 63, (time & 31) * 2
    return f"{y:04}-{mo:02}-{d:02} {h:02}:{mi:02}:{s:02}"


# ----------------------------------------------------------------------
# Geometry: the volume's layout from its size [FAT Volume Initialization]

class Geometry:
    def __init__(self, vol_sectors, fat32):
        self.fat32 = fat32
        self.total = vol_sectors
        table = DSK_TABLE_FAT32 if fat32 else DSK_TABLE_FAT16
        kind = "FAT32" if fat32 else "FAT16"
        spc = next(v for limit, v in table if vol_sectors <= limit)
        if spc == 0:
            mib = vol_sectors * SECTOR / 2**20
            raise FatError(f"a {mib:.1f} MiB volume is outside {kind}'s "
                           f"format table; pick another --size-mb"
                           + ("" if fat32 else " or --fat32"))
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
        self.count = (vol_sectors - self.first_data) // spc
        # Check the result the way a reader would [FAT Type Determination].
        lo, hi = (65525, 0x0FFFFFF5) if fat32 else (4085, 65524)
        if not lo <= self.count <= hi:
            raise FatError(f"this size gives {self.count} clusters, which "
                           f"every reader would take for "
                           f"{fat_type_of(self.count)}, not {kind}; pick "
                           f"another --size-mb"
                           + ("" if fat32 else " or --fat32"))
        for cut in (4085, 65525):
            if abs(self.count - cut) <= 16:
                warn(f"{self.count} clusters is within 16 of the "
                     f"{cut} cutover, which fatgen103 advises avoiding")
        self.entsize = 4 if fat32 else 2
        self.eoc = 0x0FFFFFFF if fat32 else 0xFFFF
        assert (self.count + 2) * self.entsize <= self.fatsz * SECTOR
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
    def __init__(self, name11, host, rel, is_dir, size, stamp):
        self.name11, self.host, self.rel = name11, host, rel
        self.is_dir, self.size, self.stamp = is_dir, size, stamp
        self.children = []
        self.first = 0       # first cluster
        self.nclus = 0       # clusters in its (contiguous) run


def scan(host, rel, stamp_for):
    """The tree under host, as sorted Nodes; errors name the bad path."""
    nodes, seen = [], {}
    with os.scandir(host) as it:
        entries = sorted(it, key=lambda e: e.name)
    for e in entries:
        path = f"{rel}/{e.name}" if rel else e.name
        if e.name.startswith("."):
            warn(f"skipping hidden {path}")
            continue
        n11 = short_name(e.name, path)
        if n11 in seen:
            raise FatError(f"{path} and {seen[n11]} would both be "
                           f"{show_name(n11)}")
        seen[n11] = path
        st = os.stat(e.path)
        if stat.S_ISDIR(st.st_mode):
            if e.is_symlink():
                raise FatError(f"{path}: a symlink to a directory; "
                               f"not followed")
            node = Node(n11, e.path, path, True, 0, stamp_for(st))
            node.children = scan(e.path, path, stamp_for)
        elif stat.S_ISREG(st.st_mode):
            if st.st_size > 0xFFFFFFFF:
                raise FatError(f"{path}: larger than FAT's 4 GiB limit")
            node = Node(n11, e.path, path, False, st.st_size,
                        stamp_for(st))
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
          volid=None, ptype=None):
    if size_mb < 2:
        raise FatError("--size-mb must be at least 2")
    total_sectors = size_mb * 2048
    vol_sectors = total_sectors - PART_START
    g = Geometry(vol_sectors, fat32)
    fixed = dos_stamp(stamp_dt)

    def stamp_for(st):
        if not mtimes:
            return fixed
        t = datetime.datetime.fromtimestamp(st.st_mtime)
        t = min(max(t, datetime.datetime(1980, 1, 1)),
                datetime.datetime(2107, 12, 31, 23, 59, 58))
        return dos_stamp(t)

    if not os.path.isdir(top):
        raise FatError(f"{top}: not a directory")
    label11 = label_name(label) if label else None
    root = Node(b"", top, "", True, 0, fixed)
    root.children = scan(top, "", stamp_for)

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
        n = len(node.children) + (0 if is_root else 2)
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
                     0 if fat32 else g.fatsz, SPT, HEADS, PART_START,
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
            last = PART_START + vol_sectors - 1
            ptype = 0x0B if last // (HEADS * SPT) <= 1023 else 0x0C
        else:
            ptype = 0x06 if vol_sectors >= 0x10000 else 0x04
    mbr = bytearray(SECTOR)
    mbr[446:462] = struct.pack("<B3sB3sII", 0x00, chs(PART_START), ptype,
                               chs(PART_START + vol_sectors - 1),
                               PART_START, vol_sectors)
    mbr[510:512] = b"\x55\xAA"

    # Write. Regions not written stay zero (and sparse on disk).
    base = PART_START * SECTOR

    def at(sector):
        return base + sector * SECTOR

    def cluster_at(n):
        return at(g.first_data + (n - 2) * g.spc)

    with open(img, "wb") as f:
        f.write(mbr)
        f.seek(at(0))
        f.write(bs)
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
                f.seek(at(start))
                f.write(bs + fsinfo + third)
        for i in range(g.nfats):
            f.seek(at(g.rsvd + i * g.fatsz))
            f.write(fat)
        if fat32:
            f.seek(cluster_at(root.first))
            f.write(dir_bytes(root, 0, True, root.nclus * cb))
        else:
            f.seek(at(g.rsvd + g.nfats * g.fatsz))
            f.write(dir_bytes(root, 0, True, g.root_dir_sectors * SECTOR))

        def emit(node):
            for c in node.children:
                if c.is_dir:
                    f.seek(cluster_at(c.first))
                    f.write(dir_bytes(c, 0 if node is root else node.first,
                                      False, c.nclus * cb))
                    emit(c)
                elif c.size:
                    f.seek(cluster_at(c.first))
                    got = 0
                    with open(c.host, "rb") as src:
                        while chunk := src.read(1 << 20):
                            got += len(chunk)
                            if got > c.size:
                                break
                            f.write(chunk)
                    if got != c.size:
                        raise FatError(f"{c.rel} changed size while "
                                       f"being copied")
        emit(root)
        f.truncate(total_sectors * SECTOR)
    return g, used


# ----------------------------------------------------------------------
# Reading

class Entry:
    def __init__(self, raw, path):
        self.name11 = raw[0:11]
        self.attr = raw[11]
        (self.ctenth, self.ctime, self.cdate, self.adate, hi, self.wtime,
         self.wdate, lo, self.size) = struct.unpack_from("<BHHHHHHHI",
                                                         raw, 13)
        self.hi, self.lo = hi, lo
        self.name = show_name(self.name11)
        self.path = path

    @property
    def is_dir(self):
        return bool(self.attr & ATTR_DIRECTORY)

    @property
    def is_label(self):
        return (self.attr & (ATTR_DIRECTORY | ATTR_VOLUME_ID)) \
            == ATTR_VOLUME_ID


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

    def first_cluster(self, e):
        return ((e.hi << 16) if self.fat32 else 0) | e.lo

    def root_entries(self):
        if self.fat32:
            data = self.read_clusters(self.chain(self.root_clus, "/"))
        else:
            data = self.raw(self.sector_at(self.rsvd
                                           + self.nfats * self.fatsz),
                            self.root_dir_sectors * self.bps)
        return self.parse_dir(data, "")

    def dir_entries(self, e):
        first = self.first_cluster(e)
        if first == 0:                    # ".." to the root
            return self.root_entries()
        data = self.read_clusters(self.chain(first, e.path or "/"))
        return self.parse_dir(data, e.path)

    @staticmethod
    def parse_dir(data, path):
        out = []
        for off in range(0, len(data) - 31, 32):
            raw = data[off:off + 32]
            if raw[0] == 0x00:
                break
            if raw[0] == 0xE5 or raw[11] & 0x3F == ATTR_LONG_NAME:
                continue
            name = show_name(raw[0:11])
            out.append(Entry(raw, f"{path}/{name}" if path else name))
        return out

    def label(self):
        for e in self.root_entries():
            if e.is_label:
                return e.name11.decode("latin-1").rstrip(" ")
        return None

    def lookup(self, path):
        """The Entry for a path (None for the root), case-insensitively."""
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        cur = None
        for i, part in enumerate(parts):
            ents = self.root_entries() if cur is None \
                else self.dir_entries(cur)
            want = part.upper()
            for e in ents:
                if not e.is_label and e.name == want:
                    cur = e
                    break
            else:
                raise FatError(f"{'/'.join(parts[:i + 1])}: not found")
            if i < len(parts) - 1 and not cur.is_dir:
                raise FatError(f"{'/'.join(parts[:i + 1])}: not a "
                               f"directory")
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
            if e.name11[0] == 0x20 or e.name in names:
                problems.append(f"{e.path}: a bad or duplicate name")
            names.add(e.name)
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
                    sub = vol.parse_dir(vol.read_clusters(clusters),
                                        e.path)
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

    if vol.fat32:
        try:
            rc = vol.chain(vol.root_clus, "/")
            claim(rc, "/")
            visit(vol.parse_dir(vol.read_clusters(rc), ""), "", 0, 0)
        except FatError as err:
            problems.append(str(err))
    else:
        visit(vol.root_entries(), "", 0, 0)
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
# put: one more file into an existing image

def put(img, host, dest, name=None, replace=False, stamp=None):
    if not os.path.isfile(host):
        raise FatError(f"{host}: not a regular file")
    size = os.path.getsize(host)
    if size > 0xFFFFFFFF:
        raise FatError(f"{host}: larger than FAT's 4 GiB limit")
    shown = name or os.path.basename(host)
    name11 = short_name(shown, shown)
    vol = Volume(img, writable=True)
    problems, _ = check(vol)
    if problems:
        raise FatError(f"{img} fails check ({problems[0]}); not writing "
                       f"to it")
    d = vol.lookup(dest)
    if d is not None and not d.is_dir:
        raise FatError(f"{dest}: not a directory")
    where = (d.path + "/" if d is not None and d.path else "") \
        + show_name(name11)
    clusters, slots = vol.dir_slots(d)

    slot, old = None, None
    for off, raw in slots:
        if raw[0] == 0x00:
            slot = slot if slot is not None else off
            break                         # nothing allocated after this
        if raw[0] == 0xE5:
            slot = slot if slot is not None else off
            continue
        if raw[11] & 0x3F == ATTR_LONG_NAME:
            continue
        if raw[0:11] == name11:
            old = (off, Entry(raw, where))
    fat = bytearray(vol.fat)
    w = 4 if vol.fat32 else 2

    def get(n):
        v = struct.unpack_from("<I" if w == 4 else "<H", fat, n * w)[0]
        return v & 0x0FFFFFFF if w == 4 else v

    def set_(n, v):
        if w == 4:      # keep the reserved high 4 bits [FAT Data Structure]
            hi = struct.unpack_from("<I", fat, n * 4)[0] & 0xF0000000
            struct.pack_into("<I", fat, n * 4, hi | v)
        else:
            struct.pack_into("<H", fat, n * 2, v)

    eoc = 0x0FFFFFFF if vol.fat32 else 0xFFFF
    if old:
        off, e = old
        if e.attr & (ATTR_DIRECTORY | ATTR_VOLUME_ID):
            raise FatError(f"{where}: already there, and not a file")
        if not replace:
            raise FatError(f"{where}: already there (--replace to "
                           f"overwrite it)")
        if vol.first_cluster(e):
            for c in vol.chain(vol.first_cluster(e), where):
                set_(c, 0)
        slot = off

    def find_run(n):
        best, start, length = 0, None, 0
        for c in range(2, vol.count + 2):
            if get(c) == 0:
                if length == 0:
                    start = c
                length += 1
                if length == n:
                    return start, best
            else:
                best, length = max(best, length), 0
        return None, max(best, length)

    need = -(-size // vol.cb)
    first = 0
    if need:
        first, largest = find_run(need)
        if first is None:
            raise FatError(f"{where} needs {need} contiguous clusters of "
                           f"{vol.cb} bytes; the largest free run is "
                           f"{largest}, and esxDOS needs some files "
                           f"unfragmented, so nothing was written")
        for c in range(first, first + need - 1):
            set_(c, c + 1)
        set_(first + need - 1, eoc)

    grow = None
    if slot is None:
        if clusters is None:
            raise FatError(f"the root directory is full ({vol.root_ent} "
                           f"entries, fixed on FAT16); nothing was "
                           f"written")
        if (len(slots) + vol.cb // 32) > 65536:
            raise FatError(f"{dest or '/'}: a FAT directory holds at most "
                           f"65536 entries")
        grow, _ = find_run(1)
        if grow is None:
            raise FatError(f"no free cluster to grow {dest or '/'}; "
                           f"nothing was written")
        set_(clusters[-1], grow)
        set_(grow, eoc)
        slot = vol.cluster_at(grow)

    if stamp is None:
        stamp = dos_stamp(datetime.datetime.fromisoformat(DEFAULT_STAMP))
    f = vol.f
    # 1. the data, its last cluster's slack zeroed
    if need:
        f.seek(vol.cluster_at(first))
        got = 0
        with open(host, "rb") as src:
            while chunk := src.read(1 << 20):
                got += len(chunk)
                if got > size:
                    break
                f.write(chunk)
        if got != size:
            raise FatError(f"{host} changed size while being copied")
        f.write(bytes(need * vol.cb - size))
    if grow is not None:
        f.seek(vol.cluster_at(grow))
        f.write(bytes(vol.cb))
    # 2. every FAT copy
    for i in range(vol.nfats):
        f.seek(vol.sector_at(vol.rsvd + i * vol.fatsz))
        f.write(fat)
    # 3. FAT32's FSInfo
    if vol.fat32 and vol.fsinfo:
        free = sum(1 for c in range(2, vol.count + 2) if get(c) == 0)
        nxt = next((c for c in range(2, vol.count + 2) if get(c) == 0),
                   0xFFFFFFFF)
        f.seek(vol.sector_at(vol.fsinfo) + 488)
        f.write(struct.pack("<II", free, nxt))
    # 4. the directory entry, last
    f.seek(slot)
    f.write(dirent(name11, ATTR_ARCHIVE, first, size, stamp))
    f.close()
    return where, first, need


# ----------------------------------------------------------------------
# The command line

def cmd_build(a):
    if a.mtimes and a.stamp != DEFAULT_STAMP:
        raise FatError("--mtimes and --stamp don't mix")
    try:
        stamp = datetime.datetime.fromisoformat(a.stamp)
    except ValueError:
        raise FatError(f"--stamp {a.stamp!r}: use YYYY-MM-DDTHH:MM:SS")
    g, used = build(a.img, a.dir, a.size_mb, a.label, a.fat32, stamp,
                    a.mtimes, a.volid, a.ptype)
    kind = "FAT32" if g.fat32 else "FAT16"
    print(f"{a.img}: {a.size_mb} MiB, {kind}, {g.count} clusters of "
          f"{g.cluster_bytes} bytes, {used} used")


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
                    go(e, f"{prefix}{e.name}/")
    go(top, "")


def show_entries(vol, ents, a, prefix):
    for e in ents:
        name = prefix + e.name + ("/" if e.is_dir else "")
        if a.long:
            kind = "d" if e.is_dir else "-"
            print(f"{kind} {e.size:>10}  {stamp_text(e.wdate, e.wtime)}  "
                  f"@{vol.first_cluster(e):<6} {name}")
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
    if a.mtime:
        t = datetime.datetime.fromtimestamp(os.stat(a.hostfile).st_mtime)
        stamp = dos_stamp(min(max(t, datetime.datetime(1980, 1, 1)),
                              datetime.datetime(2107, 12, 31, 23, 59, 58)))
    else:
        try:
            stamp = dos_stamp(datetime.datetime.fromisoformat(a.stamp))
        except ValueError:
            raise FatError(f"--stamp {a.stamp!r}: use YYYY-MM-DDTHH:MM:SS")
    where, first, n = put(a.img, a.hostfile, a.dir, a.name, a.replace,
                          stamp)
    run = f"clusters {first}..{first + n - 1}" if n else "no clusters"
    print(f"{a.img}: put {where} ({run})")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mkfat.py",
        description="Build and read SD-card images (an MBR and one FAT16 "
                    "or FAT32 partition, 8.3 names) for divMMC/esxDOS.")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build IMG from the tree in DIR",
                       description="Build IMG from the tree in DIR: an MBR "
                       "and one FAT partition from sector 2048. Same input, "
                       "same bytes.")
    b.add_argument("img")
    b.add_argument("dir")
    b.add_argument("--size-mb", type=int, default=64,
                   help="image size in MiB (default 64)")
    b.add_argument("--label", default=DEFAULT_LABEL,
                   help=f"volume label (default {DEFAULT_LABEL}; '' for "
                        f"none)")
    b.add_argument("--fat32", action="store_true",
                   help="FAT32 instead of FAT16 (needs 34 MiB or more)")
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
                   help="size, write time and first cluster too")
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
                       "run of clusters.")
    u.add_argument("img")
    u.add_argument("hostfile")
    u.add_argument("dir", nargs="?", default="")
    u.add_argument("--as", dest="name", default=None,
                   help="the 8.3 name to give it (default: the host name)")
    u.add_argument("--replace", action="store_true",
                   help="overwrite a file of that name")
    u.add_argument("--stamp", default=DEFAULT_STAMP,
                   help=f"its timestamp (default {DEFAULT_STAMP})")
    u.add_argument("--mtime", action="store_true",
                   help="use the host file's mtime instead")
    u.set_defaults(fn=cmd_put)

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
