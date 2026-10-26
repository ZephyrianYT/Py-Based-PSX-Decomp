# Glossary

> **TL;DR**: One-line definitions of every PS1 term used in `ref/`, each with a
> pointer to the file that explains it in depth.

| Term | Definition | See |
|------|------------|-----|
| **1.3.12** | 16-bit fixed point: sign, 3 integer bits, 12 fraction bits. 4096 = 1.0. | [gte.md](hardware/gte.md) |
| **ABE** | TMD/GPU "semi-transparency enable" bit | [tmd.md](formats/tmd.md) |
| **Affine mapping** | Texture coordinates interpolated linearly in screen space, without perspective division | [visual-signature.md](look/visual-signature.md) |
| **AVSZ3 / AVSZ4** | GTE commands that average 3 or 4 depths into an OT index | [gte.md](hardware/gte.md) |
| **BK** | GTE background (ambient) colour | [gte.md](hardware/gte.md) |
| **CBA** | CLUT address field in a TMD textured primitive | [tmd.md](formats/tmd.md) |
| **CLUT** | Colour look-up table (palette) of 16 or 256 entries, stored in VRAM | [gpu.md](hardware/gpu.md) |
| **COP0 / COP2** | MIPS coprocessors: system control / GTE | [overview.md](hardware/overview.md) |
| **Depth cue** | Per-vertex interpolation toward the far colour by IR0. PS1 fog. | [gte.md](hardware/gte.md) |
| **Dither** | The GPU's 4×4 ordered pattern added before truncating to 5 bits | [gpu.md](hardware/gpu.md) |
| **DMA2 / DMA6** | GPU linked-list transfer / ordering-table clear | [overview.md](hardware/overview.md) |
| **DQA / DQB** | GTE depth-cue coefficients | [gte.md](hardware/gte.md) |
| **FC** | GTE far colour, the fog colour | [gte.md](hardware/gte.md) |
| **FCE** | TMD flag for double-sided primitives | [tmd.md](formats/tmd.md) |
| **FIXP** | TMD header flag: pointers are offsets (0) or real addresses (1) | [tmd.md](formats/tmd.md) |
| **Flat / Gouraud** | One colour per primitive / one colour per vertex, interpolated | [gpu.md](hardware/gpu.md) |
| **GP0 / GP1** | GPU command/data port / display-control port | [gpu.md](hardware/gpu.md) |
| **GRD** | TMD flag for per-vertex colours on an otherwise flat primitive | [tmd.md](formats/tmd.md) |
| **GTE** | Geometry Transformation Engine: fixed-point 3D math coprocessor | [gte.md](hardware/gte.md) |
| **H** | GTE projection-plane distance, which sets the field of view | [gte.md](hardware/gte.md) |
| **IIP** | Mode bit for Gouraud shading | [tmd.md](formats/tmd.md) |
| **IR0** | GTE register holding the depth-cue factor (0..4096) | [gte.md](hardware/gte.md) |
| **LGT** | TMD flag meaning "no light-source calculation" | [tmd.md](formats/tmd.md) |
| **libgs / libgpu / libgte** | Sony PsyQ SDK libraries for graphics system, GPU packets, and GTE math | [sources.md](sources.md) |
| **Mask bit** | Bit 15 of a pixel, usable as a 1-bit stencil | [gpu.md](hardware/gpu.md) |
| **MDEC** | Motion decoder for FMV (STR) | [overview.md](hardware/overview.md) |
| **Mode 2 Form 1/2** | CD sector types: 2048-byte data / 2324-byte streaming payload | [exe-and-disc.md](formats/exe-and-disc.md) |
| **NCLIP** | GTE back-face test (2D cross product) | [gte.md](hardware/gte.md) |
| **NCDS / NCDT** | GTE normal → light → colour → depth-cue commands | [gte.md](hardware/gte.md) |
| **OT (Ordering Table)** | Array of linked lists of GPU packets, indexed by depth, drawn far to near | [overview.md](hardware/overview.md) |
| **OTZ** | Ordering table index computed by AVSZ3/4 | [gte.md](hardware/gte.md) |
| **Painter's algorithm** | Drawing far to near, so nearer things cover farther ones | [visual-signature.md](look/visual-signature.md) |
| **PS-X EXE** | PS1 executable format with a 2048-byte header | [exe-and-disc.md](formats/exe-and-disc.md) |
| **RTPS / RTPT** | GTE rotate-translate-perspective for 1 / 3 vertices | [gte.md](hardware/gte.md) |
| **Scratchpad** | 1 KB of fast on-chip RAM at `0x1F800000` | [overview.md](hardware/overview.md) |
| **Sector (level design)** | A grid cell of a level, for example 1024×1024 units in Tomb Raider | [world-building.md](world/world-building.md) |
| **Semi-transparency** | One of four fixed GPU blend modes | [gpu.md](hardware/gpu.md) |
| **STP** | Bit 15 of a texel or CLUT entry: semi-transparency flag | [tim.md](formats/tim.md) |
| **STR** | MDEC video stream file | [exe-and-disc.md](formats/exe-and-disc.md) |
| **SVECTOR** | libgte struct of 3 int16 values plus a pad. Vertex and normal storage. | [modeling-guide.md](models/modeling-guide.md) |
| **SZ** | GTE screen depth (unsigned 16-bit) | [gte.md](hardware/gte.md) |
| **SYSTEM.CNF** | Boot configuration file on a PS1 disc | [exe-and-disc.md](formats/exe-and-disc.md) |
| **T-junction** | A vertex lying on another polygon's edge. Causes sparkle cracks. | [visual-signature.md](look/visual-signature.md) |
| **TGE** | Mode bit meaning "texture brightness modulation off" (raw texture) | [tmd.md](formats/tmd.md) |
| **TIM** | PS1 image/texture file with a VRAM destination | [tim.md](formats/tim.md) |
| **TMD** | PS1 static 3D model file | [tmd.md](formats/tmd.md) |
| **TME** | Mode bit for texture mapping | [tmd.md](formats/tmd.md) |
| **Texture page (tpage)** | A 256×256-texel window in VRAM that a primitive samples from | [gpu.md](hardware/gpu.md) |
| **Texture window** | GPU register that wraps or repeats u,v inside a sub-rectangle | [gpu.md](hardware/gpu.md) |
| **TSB** | Texpage field in a TMD textured primitive | [tmd.md](formats/tmd.md) |
| **VAB / VAG / SEQ / XA** | Sound bank / single sample / sequence / streamed ADPCM | [exe-and-disc.md](formats/exe-and-disc.md) |
| **Vertex jitter / snapping** | Visible whole-pixel wobble from integer screen coordinates | [visual-signature.md](look/visual-signature.md) |
| **VRAM** | 1 MB (1024×512×16-bit) GPU memory for framebuffers, textures and CLUTs | [gpu.md](hardware/gpu.md) |
| **Walkmesh** | Invisible navigation triangles used with pre-rendered backgrounds | [world-building.md](world/world-building.md) |
