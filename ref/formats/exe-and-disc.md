# Discs, executables and common asset formats

> **TL;DR**: A PS1 disc is a Mode 2 CD with an ISO 9660 filesystem. `SYSTEM.CNF`
> names the boot executable (for example `cdrom:\SLUS_000.01;1`). That file is a
> **PS-X EXE**: a 2048-byte header (magic `"PS-X EXE"`, entry PC, GP, load
> address, size, stack), then raw MIPS code and data, loaded at a
> `0x80xx_xxxx` address. Raw sectors are 2352 bytes. Data uses Mode 2 Form 1
> (2048 user bytes), and streamed audio and video use Form 2 (2324 bytes). Sound
> uses VAB/VAG/SEQ/XA, video uses STR (MDEC), images use TIM, and models use TMD
> or custom formats.

## Disc images [FMT] [TYP]

| Container | Notes |
|-----------|-------|
| `.bin` + `.cue` | Raw 2352-byte sectors. Most faithful (keeps XA/CDDA and subheaders). |
| `.iso` | Often 2048-byte user data only. **Loses Form 2 / XA streams.** Fine for reading files, not for streams. |
| `.chd` | MAME compressed hunks of raw sectors. Convert with `chdman extractcd`. |
| `.img`/`.mdf`/`.ccd` | Other raw dumps. Usually 2352-byte sectors. |

## CD sector layout [HW]

```
Mode 2 Form 1 (data):   12 sync | 4 header | 8 subheader | 2048 data | 4 EDC | 276 ECC   = 2352
Mode 2 Form 2 (stream): 12 sync | 4 header | 8 subheader | 2324 data | 4 EDC             = 2352
```

* The header holds a BCD minute:second:frame address plus the mode byte (`02`).
* The subheader (stored twice) holds file number, channel, **submode** (bit 5 =
  Form 2, bit 2 = audio, bit 1 = video, bit 3 = data) and coding info. XA audio
  interleaves channels by channel number.
* The ISO 9660 **Primary Volume Descriptor** is at sector 16 (LBA 16). The PS1
  license data and logo occupy sectors 0–15.

## SYSTEM.CNF [FMT]

```
BOOT = cdrom:\SLUS_012.34;1
TCB = 4
EVENT = 10
STACK = 801FFFF0
```

`BOOT` gives the executable path. Its name doubles as the product code, and
the prefix tells you the region and publisher:

| Prefix | Region |
|--------|--------|
| `SCUS`, `SLUS` | North America (Sony first-party / licensed third-party) |
| `SCES`, `SLES` | Europe / PAL |
| `SCPS`, `SLPS`, `SLPM` | Japan |

If `SYSTEM.CNF` is missing, the BIOS boots `cdrom:\PSX.EXE;1`.

## PS-X EXE header (2048 bytes) [FMT]

The fields from `0x10` onwards are Sony's `EXEC` structure (Net Yaroze
User's Guide, "Kernel Management"). The names in the second column are Sony's.

| Off | EXEC field | Meaning |
|-----|------------|---------|
| 0x000 | (magic) | `"PS-X EXE"` (8 bytes) |
| 0x010 | `pc0` | Entry point |
| 0x014 | `gp0` | Initial GP (`r28`) |
| 0x018 | `t_addr` | RAM address of text + initialised data (where the file body is copied) |
| 0x01C | `t_size` | Size of text + initialised data in bytes |
| 0x020 | `d_addr`, `d_size` | Reserved for system use (usually 0) |
| 0x028 | `b_addr`, `b_size` | BSS start and size (zeroed by the loader) |
| 0x030 | `s_addr` | Stack base (0 = keep the BIOS default / SYSTEM.CNF) |
| 0x034 | `s_size` | Stack size |
| 0x038 | `sp, fp, gp, ret, base` | Register save area used by `Exec()` |
| 0x04C | (marker) | ASCII marker, for example `Sony Computer Entertainment Inc. for North America area` |

* Sony documents the body as a multiple of 2048 bytes. The BIOS copies
  `t_size` bytes, and some linkers leave the last sector unpadded.
  `ref/tools/exe.py` reports both `complete` (the file holds `t_size` bytes)
  and `padded`.
* The marker is free text after the region string's position. Converters
  sign their output here. PS-X EXEs made from Net Yaroze programs by
  **yarexe** read `YAREXE - vN …`, load at `0x80010000`, and contain the
  libps library as well as the program.

To disassemble, load the bytes from file offset `0x800` at `t_addr`, with
the CPU set to **MIPS R3000, little-endian**. In Ghidra, use a MIPS:LE:32
default language (or a PSX loader plugin) and the entry point `pc0`.

## Other executable containers [FMT]

| Format | Magic | Where you meet it | What to read |
|--------|-------|-------------------|--------------|
| **ECOFF** (MIPS little-endian) | bytes `62 01` | Net Yaroze programs (`a.out`, no extension) and `.o` objects, built by GCC 2.x | 20-byte file header (magic, section count, timestamp, symbol pointer, symbol count, optional-header size, flags; flag `0x0002` = executable), then a 56-byte a.out header (magic `0413` ZMAGIC, text/data/bss sizes, **entry**, **text start**, data start, bss start, register masks, **gp value**), then 40-byte section headers (`.text`, `.rdata`, `.data`, `.sdata`, `.sbss`, `.bss`, …) |
| **CPE** | `CPE\x01` | Psy-Q development builds, loaded over a debug link | A sequence of chunks: `0x01` load (u32 address, u32 length, bytes), `0x03` set register (u16 register, u32 value; register `0x90` = PC), `0x08` select unit (1 byte), `0x00` end |

A Net Yaroze ECOFF program is only half a program: Sony's libps must already
be resident below `0x80090000`. See [`../sdk/net-yaroze.md`](../sdk/net-yaroze.md).

```bash
python -m ref exe info FILE     # identifies PS-X EXE / ECOFF / CPE and prints entry, load address, sections
```

Checked on the Net Yaroze samples: all 321 executables are read, namely
218 Yaroze ECOFF programs, 91 ECOFF objects, 10 PS-X EXEs and 2 CPE files.
Both CPE files end exactly on their end chunk.

## Common asset formats [FMT] [TYP]

| Ext / magic | What | Notes |
|-------------|------|-------|
| `.TIM` (`10 00 00 00`) | Image / texture | [`tim.md`](tim.md) |
| `.TMD` (`41 00 00 00`) | Static 3D model | [`tmd.md`](tmd.md) |
| `.HMD` | Hierarchical model and animation (libgs) | Later SDKs |
| `.PMD` | Pre-built primitive packets | Rare |
| `.TOD` | Animation for TMD objects | libgs |
| `.VAB` (`pBAV`), `.VH` + `.VB` | Instrument bank (header + ADPCM bodies) | Up to 128 programs × 16 tones and 254 samples. The VH stays in RAM and the VB goes to SPU RAM. |
| `.VAG` (`VAGp`) | Single ADPCM sample | 48-byte big-endian header (version, size, sample rate, name) |
| `.SEQ` (`pQES`) / `.SEP` | MIDI-like sequence | Played by libsnd |
| `.XA` | Interleaved Form 2 ADPCM audio streams | Needs raw 2352-byte sectors |
| `.STR` | MDEC video (+ XA audio) | Needs raw sectors. Frame headers are in the data. |
| `.MCR`, `.MCD`, … | Memory card images | 128 KB, 16 × 8 KB blocks |
| Custom archives | `.BIN`, `.DAT`, `.PAK` … | Game-specific. Scan for TIM/TMD signatures inside. |

## Relevance to this repository

The `PSX Decomp Studio` pipeline (see the root README) starts with **Image
Intake** and **Asset Extraction**. This file lists what those stages must
recognise. Reference implementations: `ref/tools/exe.py` (identify the
executable and find its entry point and load address), `ref/tools/tim.py scan`
(signature scanning for embedded textures), `ref/tools/tmd.py` and
`ref/tools/rsd.py` (models).
