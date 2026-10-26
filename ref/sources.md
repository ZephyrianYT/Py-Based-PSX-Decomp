# Sources and trust levels

> **TL;DR**: Hardware facts come from **nocash's psx-spx** (the community hardware
> specification, maintained at psx-spx.consoledev.net). File formats come from
> **Sony's PsyQ / libgs "File Formats" documentation**. Game techniques come from
> **developers' own published accounts** or long-standing **community format
> documentation**. Verify behaviour against **accurate emulators** (DuckStation,
> Mednafen/Beetle PSX). This folder copies no text or data from these sources. It
> summarises them.

| Source | Covers | Trust | Notes |
|--------|--------|-------|-------|
| **psx-spx** (Martin "nocash" Korth; community-maintained edition at `psx-spx.consoledev.net`) | CPU, memory map, GPU commands, GTE formulas, CD-ROM, DMA, timers, formats | High for hardware. **The** reference used by emulator authors. | Basis for `hardware/*.md` |
| **Sony PsyQ SDK docs**: *Library Reference*, *Library Overview*, *File Formats* | libgpu/libgte/libgs APIs, TIM, TMD, HMD, VAB, SEQ, STR | High for formats and intended usage | Basis for `formats/*.md` |
| **Emulator source code**: DuckStation, Mednafen PSX, PCSX-Redux, Beetle PSX HW | Exact rasteriser rules, GTE precision, dithering | High, executable truth | Use to settle disagreements |
| **PCSX-Redux / PSn00bSDK documentation and examples** | Modern open-source PS1 homebrew SDK usage | High for practice | Good for writing new PS1 code |
| **Andy Gavin, "Making Crash Bandicoot" blog series** | Crash's precomputed visibility, streaming, and vertex animation | Developer first-hand, for that game only | `world/world-building.md`, `models/modeling-guide.md` |
| **TRosettaStone** (Tomb Raider format documentation, community) | TR rooms, sectors, portals, and floor data | High for TR formats | `world/world-building.md` |
| **Qhimm wiki** (FF7 community documentation) | FF7 field files, walkmesh, models | High for FF7 formats | `world/world-building.md` |
| **Developer interviews and post-mortems** (Insomniac on Spyro, Konami on Silent Hill, and others) | High-level design decisions | Medium. Interviews simplify. | Marked **[CASE]** |
| **Net Yaroze manuals** (Sony, 1997): Start Up Guide, User's Guide, Library Reference, File Formats | libps/libgs API and frame loop, memory map, PS-X EXE `EXEC` structure, TIM, TMD, RSD, SEQ, VAG and VAB | High for formats and SDK behaviour. It has two errata in the TIM chapter (see `formats/tim.md`). | `formats/*.md`, `sdk/net-yaroze.md`. They carry Sony's confidentiality notices, so this folder summarises them and quotes no text. |
| **SCEE Net Yaroze Programming FAQ** (1998) | Packet sizes, the GPU texture cache and queue, libps bugs, RSDLINK UVs | High (Sony's own answers) | `hardware/gpu.md`, `sdk/net-yaroze.md` |
| **`github.com/gwald/netyaroze_demo`** | Mirror of the Net Yaroze manuals, plus SCEE demos, tutorials and member guides with their data | The **test corpus**: 556 TIM, 249 TMD, 19 RSD, 321 executables | `tools/validate.py` runs over it. None of its files are copied here. |
| **`github.com/ChrisRx/psxsdk`** | Modern Go toolchain for the Net Yaroze, with converters tested against Sony's tools, a byte-exact rsdlink, ECOFF tooling, and documentation of the machine and the FAQ | High. An independent implementation that agrees with this folder's TMD layout rule and winding. | `formats/rsd.md` (rounding rules), `sdk/net-yaroze.md` |
| **`netyaroze.com/Development/Toolchain`** | Community page on setting up the toolchain | **Not consulted**: the site was unreachable from the environment that wrote these docs | Follow it for current setup steps |
| **This repository's tools** | Simulation | **[SIM]**. Illustrative only. | `tools/` |

## How to resolve disagreements

1. Emulator behaviour from an accuracy-focused emulator (DuckStation, Mednafen)
2. psx-spx
3. Sony SDK documentation (describes the intended use, which is sometimes not what the hardware does)
4. Community game-format documentation
5. Everything else

## Not used

* Leaked or confidential material.
* Copyrighted game assets or decompiled game code. The tools and images here
  are generated from scratch.
