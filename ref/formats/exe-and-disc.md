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

| Off | Size | Field |
|-----|------|-------|
| 0x000 | 8 | Magic `"PS-X EXE"` |
| 0x010 | 4 | Initial PC (entry point) |
| 0x014 | 4 | Initial GP (`r28`) |
| 0x018 | 4 | Destination address in RAM (the `t_addr` load address) |
| 0x01C | 4 | File size excluding the header (a multiple of 2048) |
| 0x020 | 8 | Data section start and size (usually 0) |
| 0x028 | 8 | BSS start and size (zeroed by the loader) |
| 0x030 | 4 | Initial SP base (0 = use the BIOS default / SYSTEM.CNF) |
| 0x034 | 4 | SP offset |
| 0x04C | … | ASCII region marker, for example `Sony Computer Entertainment Inc. for North America area` |

To disassemble, load the bytes from file offset `0x800` at the destination
address, with the CPU set to **MIPS R3000, little-endian**. In Ghidra, use a
MIPS:LE:32 default language (or a PSX loader plugin) and the entry point from
offset `0x010`.

## Common asset formats [FMT] [TYP]

| Ext / magic | What | Notes |
|-------------|------|-------|
| `.TIM` (`10 00 00 00`) | Image / texture | [`tim.md`](tim.md) |
| `.TMD` (`41 00 00 00`) | Static 3D model | [`tmd.md`](tmd.md) |
| `.HMD` | Hierarchical model and animation (libgs) | Later SDKs |
| `.PMD` | Pre-built primitive packets | Rare |
| `.TOD` | Animation for TMD objects | libgs |
| `.VAB` (`pBAV`), `.VH` + `.VB` | Instrument bank (header + ADPCM bodies) | SPU sound |
| `.VAG` (`VAGp`) | Single ADPCM sample | Big-endian header |
| `.SEQ` (`pQES`) / `.SEP` | MIDI-like sequence | Played by libsnd |
| `.XA` | Interleaved Form 2 ADPCM audio streams | Needs raw 2352-byte sectors |
| `.STR` | MDEC video (+ XA audio) | Needs raw sectors. Frame headers are in the data. |
| `.MCR`, `.MCD`, … | Memory card images | 128 KB, 16 × 8 KB blocks |
| Custom archives | `.BIN`, `.DAT`, `.PAK` … | Game-specific. Scan for TIM/TMD signatures inside. |

## Relevance to this repository

The `PSX Decomp Studio` pipeline (see the root README) starts with **Image
Intake** and **Asset Extraction**. This file lists what those stages must
recognise. `ref/tools/tim.py scan` is a minimal reference implementation of
signature scanning for one format.
