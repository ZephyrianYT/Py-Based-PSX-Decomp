# PlayStation hardware overview

> **TL;DR**: A 33.8688 MHz MIPS R3000A-class CPU with **no FPU**, 2 MB of main
> RAM, 1 MB of VRAM, and 512 KB of sound RAM. 3D math runs on a fixed-point
> coprocessor, the **GTE** (COP2). A 2D-only **GPU** draws screen-space
> triangles and quads into VRAM, with no Z-buffer and no perspective-correct
> texturing. Draw order comes from a CPU-built **ordering table** that DMA sends
> to the GPU. Almost every visual quirk of the platform follows from this design.

## Components [HW]

| Unit | Details |
|------|---------|
| CPU | MIPS R3000A-compatible core (in an LSI custom chip), 33.8688 MHz, 32-bit, no floating-point unit. 4 KB instruction cache. The 1 KB data cache is mapped as **scratchpad RAM** rather than used as a cache. |
| COP0 | System control: exceptions, interrupts, cache isolation. |
| COP2 / GTE | Geometry Transformation Engine: fixed-point matrix, projection and lighting coprocessor. See [`gte.md`](gte.md). |
| GPU | 2D rasteriser for points, lines, rectangles (sprites), triangles and quads, with 1 MB of dedicated VRAM. See [`gpu.md`](gpu.md). |
| MDEC | Motion decoder that decompresses JPEG-like macroblocks for full-motion video (STR files). |
| SPU | 24 ADPCM voices, 512 KB of sound RAM, hardware reverb. |
| CD-ROM | 2x speed: 150 KB/s at 1x and about 300 KB/s at 2x. Reads Mode 1 and Mode 2 (XA) sectors and can stream XA-ADPCM audio. |
| Main RAM | 2 MB. |
| BIOS ROM | 512 KB. |

## Memory map [HW]

The same physical memory appears in three address windows: KUSEG
`0x0000_0000`, KSEG0 (cached) `0x8000_0000`, and KSEG1 (uncached) `0xA000_0000`.
Games almost always run from KSEG0 (`0x80xx_xxxx`).

| Physical range | Size | Contents |
|----------------|------|----------|
| `0x0000_0000` – `0x001F_FFFF` | 2 MB | Main RAM. The first 64 KB (`0x0000_0000`–`0x0000_FFFF`) is used by the BIOS/kernel. |
| `0x1F00_0000` – `0x1F7F_FFFF` | 8 MB | Expansion region 1 (parallel port / cheat carts) |
| `0x1F80_0000` – `0x1F80_03FF` | 1 KB | Scratchpad: fast RAM, not reachable by DMA |
| `0x1F80_1000` – `0x1F80_1FFF` | 4 KB | Hardware I/O ports |
| `0x1F80_2000` – … | | Expansion region 2 (debug and dev hardware) |
| `0x1FC0_0000` – `0x1FC7_FFFF` | 512 KB | BIOS ROM. The reset vector is `0xBFC0_0000`. |
| `0xFFFE_0130` | | Cache control register (KSEG2) |

### Key I/O registers [HW]

| Address | Name | Notes |
|---------|------|-------|
| `0x1F80_1070` | I_STAT | Interrupt status |
| `0x1F80_1074` | I_MASK | Interrupt mask |
| `0x1F80_1080`+ | DMA | Seven channels, 0x10 bytes each, plus DPCR at `0x1F80_10F0` and DICR at `0x1F80_10F4` |
| `0x1F80_1100`+ | Timers | Root counters 0–2 |
| `0x1F80_1800`–`1803` | CD-ROM | Index/command/parameter/data ports |
| `0x1F80_1810` | GP0 | GPU rendering commands and VRAM data (write), GPUREAD (read) |
| `0x1F80_1814` | GP1 | GPU display control (write), GPUSTAT (read) |
| `0x1F80_1820` / `1824` | MDEC | Command/data and status/control |
| `0x1F80_1C00`+ | SPU | Voice and control registers |

### DMA channels [HW]

| Ch | Device | Typical use |
|----|--------|-------------|
| 0 | MDEC in | Compressed video macroblocks |
| 1 | MDEC out | Decoded pixels, which then go to VRAM |
| 2 | GPU | **Linked-list mode** walks the ordering table and sends packets to GP0. Block mode is used for VRAM uploads. |
| 3 | CD-ROM | Sector data to RAM |
| 4 | SPU | Samples to sound RAM |
| 5 | PIO | Expansion port |
| 6 | OTC | **Clears an ordering table**, writing a reverse linked list of empty entries |

### Interrupt sources (I_STAT bits) [HW]

0 VBLANK · 1 GPU · 2 CD-ROM · 3 DMA · 4–6 Timers 0–2 · 7 Controller/Memory card · 8 SIO · 9 SPU · 10 Lightpen/PIO

## How one frame is produced [HW] [TYP]

```
           CPU + GTE                                   GPU
 ┌─────────────────────────────────┐          ┌──────────────────────────┐
 │ for each object:                │          │                          │
 │   load rotation/translation     │          │                          │
 │   RTPT  → 3 screen XY + SZ      │          │                          │
 │   NCLIP → cull back faces       │  DMA ch2 │  walk linked list        │
 │   AVSZ3 → OTZ (depth bucket)    │ ───────► │  rasterise each packet   │
 │   build GPU packet in RAM       │ (linked) │  affine UV, Gouraud,     │
 │   link it into OT[OTZ]          │          │  dither, 15-bit write    │
 └─────────────────────────────────┘          └──────────────────────────┘
          double-buffered: draw into buffer B while buffer A is displayed
```

1. The CPU clears an ordering table (OT), an array of N list heads, using DMA6.
2. For each primitive, the GTE transforms its vertices to **integer** screen
   coordinates, culls back faces, and returns an averaged depth.
3. The CPU writes a GPU command packet and inserts it at `OT[depth]`.
4. DMA2 walks the OT from far to near (painter's algorithm), and the GPU
   rasterises each packet.
5. At VBLANK, the display area and draw area swap (double buffering in VRAM).

The rest of this folder explains why each of those steps produces a
particular visible artifact. See [`../look/visual-signature.md`](../look/visual-signature.md).

## CPU quirks worth knowing when reading disassembly [HW]

* **Branch delay slot**: the instruction after a branch or jump always executes.
* **Load delay slot**: the result of a load is not available to the very next
  instruction. Compilers fill the slot with a `nop` or an unrelated instruction.
* No FPU, so all game math is integer or fixed point. A float routine in a
  PS1 binary is almost always a software library, used rarely.
* GTE instructions are COP2 opcodes (`cop2 0x0180001` = RTPS, and so on), and
  data moves between CPU and GTE with `mtc2/mfc2/ctc2/cfc2/lwc2/swc2`. See
  [`gte.md`](gte.md).
