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
