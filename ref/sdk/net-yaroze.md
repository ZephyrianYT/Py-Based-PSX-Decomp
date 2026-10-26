# Net Yaroze: Sony's hobbyist PlayStation SDK

> **TL;DR**: The Net Yaroze (Japan 1996, Europe and North America 1997, $750 in
> the US) was a black PlayStation, a boot disc, an access card and a serial
> cable. Programs were written in C with an MS-DOS GCC 2.x toolchain, linked
> against Sony's **libps** library, and sent over the cable with **SIOCONS**.
> The boot disc left libps **resident in the bottom 576 KB of RAM**
> (`0x80000000`–`0x8008FFFF`). A program ran from `0x80090000` up, and its
> assets were downloaded to **hard-coded RAM addresses**, because it could not
> read its own CD. Programs are **ECOFF `a.out`** files, not PS-X EXEs. The SDK's
> manuals and samples survive, and they document the official libgs frame loop,
> ordering tables, fog and the TMD/TIM/RSD formats. That makes the Yaroze the
> best-documented window into how PS1 games were really written.

## Why it matters here [SDK]

* **Decompilation**: Net Yaroze programs, and PS-X EXEs converted from them,
  have a recognisable shape (see [Recognising a Net Yaroze program](#recognising-a-net-yaroze-program)).
* **Ground truth**: the Net Yaroze manuals are Sony's own descriptions of the
  file formats and the graphics library. This folder's TIM, TMD and RSD tools
  were checked against them and against the sample files that shipped with
  them (see [`../formats/tmd.md`](../formats/tmd.md)).
* **Education**: the samples are complete, small PS1 programs in C, where you
  can see every concept in `ref/` used in context.

## The kit [SDK]

| Part | Role |
|------|------|
| Black "Net Yaroze" PlayStation | A console that runs the boot disc's monitor |
| Boot disc | Loads libps and a monitor program, then waits for commands on the serial port |
| Access card | Goes in memory card slot 1. It unlocks the boot disc. |
| Serial cable | Connects the console to the PC. All code and data travel over it. |
| Development disc (PC) | GCC toolchain, libps headers and library, SIOCONS, converters, samples |
| Manuals | Start Up Guide, User's Guide, Library Reference, and (from 1997) File Formats |

## Toolchain [SDK]

| Tool | What it did |
|------|-------------|
| `gcc` | GNU C compiler, GCC 2.x for MS-DOS, producing MIPS ECOFF objects. It can also call the linker. |
| `ld` | GNU linker. Programs are linked to a fixed address with `-Ttext`, for example `-Xlinker -Ttext -Xlinker 80140000`. |
| `strip` | Removes symbols for a release build |
| `make`, `ar`, `nm`, `gdb` | Build, library, symbol and debugger tools |
| `siocons` | Serial console: downloads programs and data, runs them, shows `printf` output |
| `rsdlink` | Links RSD text models into TMD (see [`../formats/rsd.md`](../formats/rsd.md)) |
| `dxf2rsd` and other converters | Turn models from other tools (for example AutoCAD DXF) into RSD |

### SIOCONS scripts

SIOCONS can run a script file, conventionally named `auto` or `batchN`. A
typical script downloads the program and each data file to a fixed address,
then starts the program:

```
local load main              ← download the ECOFF program (to its link address)
local dload cube0.tmd 800d0000   ← download raw data to a fixed RAM address
go                           ← start the program
```

The program then finds its data with constants in a header, for example
`#define CUBE_MODEL_ADDRESS 0x80092000`. This "asset at a hard-coded address"
pattern is everywhere in Yaroze code.

## Memory map for a Yaroze program [SDK]

```
0x801FFFFF ┌──────────────────────────┐
           │ system stack             │  (0x801FFF00 – 0x801FFFFF)
0x801FFF00 ├──────────────────────────┤
           │ application area         │  program text/data/bss, heap,
           │ (≈ 1.4 MB)               │  and every downloaded asset
0x80090000 ├──────────────────────────┤
           │ system area (576 KB)     │  kernel, libps, boot monitor
0x80000000 └──────────────────────────┘
```

In the 218 Yaroze programs among the samples, programs were linked at
`0x80140000` (149 programs), `0x80100000` (43) and several other addresses, always at or above
`0x80090000`. Data was placed in the gaps by hand.

## The libgs frame loop [SDK]

The User's Guide gives the standard structure of a 3D program, which uses
libps's integrated graphics functions (Sony's "Gs" layer):

| Step | Call(s) | Hardware concept (see `ref/hardware/`) |
|------|---------|---------------------------------------|
| 1 | `GsInitGraph`, `GsDefDispBuff` | Set up resolution and two display buffers in VRAM |
| 2 | read controller | |
| 3 | `GsSetRefView2` / `GsSetView2` | Camera matrix |
| 4 | `GsSetWorkBase` | Packet area for this frame's GPU commands (double-buffered) |
| 5 | `GsClearOt` | Clear this frame's ordering table |
| 6–7 | `GsGetLs`/`GsGetLw`, `GsSetLsMatrix`, `GsSetLightMatrix` | Load GTE rotation, translation and light matrices |
| 8 | `GsSortObject4` | GTE transform, project, light, cull, and link packets into the OT |
| 9 | `DrawSync(0)`, `VSync(0)` | Wait for the GPU to finish the previous frame, then for vertical blank |
| 10 | `GsSwapDispBuff` | Show the frame just drawn |
| 11 | `GsSortClear`, `GsDrawOt` | Clear the screen and start the GPU walking the new OT |

Because of double buffering, the picture on screen is about two frames behind
the game state the CPU is computing.

### Ordering tables in libgs [SDK]

* A `GsOT` has a `length` of 1–14, giving **2^length** entries.
* Several OTs can be merged with `GsSortOt`, using a representative depth.
  This is the documented way to keep layers (sky, world, HUD) in order. See
  [`../world/world-building.md`](../world/world-building.md#2-visibility-and-culling-pipeline-typ).
* Items sorted at the same depth are drawn in reverse order of sorting, so the
  last one sorted at a depth ends up behind the others. `ref/tools/raster.py`'s
  `OrderingTable` models exactly this.

### Fog and projection [SDK]

* `GsSetProjection(h)` sets the GTE `H` distance. A larger `h` gives a narrower
  field of view.
* Fog only applies when `GsSetLightMode(1)` is set. `GsSetFogParam` takes
  `dqa`, `dqb` and the far colour. Sony's recipe is `dqa = −df·4096/64/h` and
  `dqb = 1.25·4096²`. Worked through the GTE formula, that fog starts at **df/5**
  and is total at **df**, linear in 1/z. See `fixedpoint.libgs_fog_params`.

### Built-in polygon subdivision [SDK]

libgs objects have an automatic subdivision attribute (2×2 up to 64×64), which
the manual describes as reducing texture distortion. This is the SDK-level
version of the subdivision technique in
[`../look/visual-signature.md`](../look/visual-signature.md#1-affine-texture-warping-hw).

## Practical limits, from Sony's Yaroze Programming FAQ [SDK]

| Topic | Fact |
|-------|------|
| Packet sizes | Flat tri 20 B, flat textured tri 32, flat quad 24, flat textured quad 40, Gouraud tri 28, Gouraud textured tri 40, Gouraud quad 36, Gouraud textured quad 52. A sprite is about 24 B. |
| GPU texture cache | 2 KB, covering a 64×64 area at 4-bit, 64×32 at 8-bit, 32×32 at 15-bit. Cache hits can be about 30% faster. |
| GPU queue | Up to 64 linked lists may be queued. `DrawSync(0)` waits until the queue is empty. |
| Scratchpad ("DCache") | 1 KB at `0x1F800000`. One-cycle access instead of 6–8. Some library calls use it. |
| Sprites | 1×1 to 256×256. U, V are relative to the texture page. `GsSortFastSprite` needs an even U and an even width. |
| TMD primitives libps does not draw | Lines, 3D sprites, double-sided polygons, untextured Gouraud quads. Use thin polygons instead. |
| RSDLINK UVs | MAT UVs are relative to the image's top-left, not the page. Linking adds the offset. |
| Clipping | Polygons with a negative screen Z are clipped (dropped) |
| CD access | Only the boot disc. A program could not read, or be booted from, its own CD. |

## Recognising a Net Yaroze program

| Clue | Meaning |
|------|---------|
| File starts `62 01` (MIPS LE ECOFF), a.out text start ≥ `0x80090000` | A native Yaroze program. `python -m ref exe info FILE` reports it. |
| PS-X EXE whose header marker reads `YAREXE …` and whose text loads at `0x80010000` (≈1.2 MB) | A Yaroze program converted by yarexe, with libps bundled in |
| `auto` / `batch*` text files with `local load` / `local dload` | SIOCONS scripts. They are a map of which asset goes at which address. |
| Calls into the `0x80000000`–`0x8008FFFF` range with no code there | Calls into resident libps. The library must be supplied separately to emulate or decompile. |

## Running Yaroze programs today [TYP]

| Route | How |
|-------|-----|
| **yarexe** (`github.com/gwald/yarexe`) | Turns a program plus its SIOCONS script into a standalone PS-X EXE with libps included |
| **psxsdk** (`github.com/ChrisRx/psxsdk`) | A Go toolchain for the Net Yaroze. It relinks libps into PS-X EXEs (`eco2exe`), builds bootable discs, converts PNG/OBJ/WAV/MIDI to TIM/TMD/VAG/SEQ (tested against Sony's tools), and includes an emulator. |
| Original hardware | A Net Yaroze console with its boot disc and access card, driven by SIOCONS or psxsdk's `sioload` |

## Sources

Net Yaroze Start Up Guide, User's Guide, Library Reference and File Formats
manuals (1997), and the SCEE Yaroze Programming FAQ (1998), as mirrored in
`gwald/netyaroze_demo` and `ChrisRx/psxsdk`. The address statistics are
from running `ref/tools/validate.py` and `ref/tools/exe.py` over
`gwald/netyaroze_demo`. See [`../sources.md`](../sources.md). These documents
carry Sony's confidentiality notices, so this page summarises facts and
quotes no text.
