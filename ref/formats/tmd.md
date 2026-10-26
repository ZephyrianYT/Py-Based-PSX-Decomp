# TMD: PlayStation 3D model format

> **TL;DR**: TMD is Sony's standard static-mesh format from the libgs SDK. It has
> a 12-byte header (`ID = 0x00000041`, FLAGS, NOBJ), then an object table of
> 28-byte entries. Each entry points to a **vertex list** (`int16 x,y,z,pad`),
> a **normal list** (`int16 1.3.12 nx,ny,nz,pad`), and a **primitive list** of
> polygons, lines and 3D sprites. Each primitive has a 4-byte header
> `olen, ilen, flag, mode` followed by `ilen` words of data. Axes are X right,
> **Y down**, Z away, and a polygon's front is the side from which its vertices run
> **clockwise**. All values are little-endian. Parser and writer:
> `ref/tools/tmd.py`, verified against Sony's manual and 245 real files.

## File header [FMT]

```
offset  size  field
0x00    u32   ID     = 0x00000041
0x04    u32   FLAGS  bit 0 FIXP: 0 = pointers are offsets, 1 = already relocated to RAM addresses
0x08    u32   NOBJ   number of objects
0x0C          object table (NOBJ × 28 bytes)
```

When `FIXP = 0`, every `*_top` pointer is an **offset from the start of the
object table** (file offset `0x0C`), not from the start of the file.

## Object table entry (28 bytes) [FMT]

| Off | Type | Field |
|-----|------|-------|
| 0x00 | u32 | `vert_top`: offset of the vertex list |
| 0x04 | u32 | `n_vert` |
| 0x08 | u32 | `normal_top` |
| 0x0C | u32 | `n_normal` |
| 0x10 | u32 | `primitive_top` |
| 0x14 | u32 | `n_primitive` |
| 0x18 | s32 | `scale`: the model was designed at 2^scale times this size (RSDLINK `-s`). Ignored by libgs. |

Vertex: `int16 vx, vy, vz, pad` (8 bytes). Normal: `int16 nx, ny, nz, pad`
(8 bytes, 1.3.12, so 4096 = 1.0). Sony's tools wrote lists in the order
primitives, vertices, normals.

## Coordinates and winding [FMT]

* X right, **Y down**, Z into the screen. This is the libgs coordinate space.
* A polygon faces the viewer when its first three vertices run **clockwise
  on screen**. For a closed model in raw TMD coordinates, the right-hand-rule
  cross product `(v1−v0)×(v2−v0)` therefore points *into* the model. In the
  Net Yaroze samples, 74,233 of 77,300 lit polygons (96%) have an authored
  normal that points the opposite way to that cross product. Most of the rest are
  degenerate.
* Exporting to a Y-up, counter-clockwise format (OBJ, glTF) by negating Y
  needs **no** change of vertex order, because the mirror flips the winding by
  itself. `tmd.to_obj` does this. (An earlier version of this repository also
  reversed the order, which turned models inside out.)

## Primitive header (4 bytes) [FMT]

| Byte | Field | Meaning |
|------|-------|---------|
| 0 | `olen` | Length in words of the **GPU packet** this primitive becomes (ignored when parsing) |
| 1 | `ilen` | Length in words of the **data that follows** this header. Use it to skip unknown primitives. |
| 2 | `flag` | bit 0 **LGT**: 1 = no light-source calculation (colours are used directly) · bit 1 **FCE**: 1 = double-sided · bit 2 **GRD**: 1 = per-vertex colours on a lit, untextured polygon (gradation) |
| 3 | `mode` | bits 7-5 **CODE**: `001` polygon, `010` line, `011` sprite. For polygons: bit 4 **IIP** (Gouraud), bit 3 **QUAD**, bit 2 **TME** (textured), bit 1 **ABE** (semi-transparent), bit 0 **TGE** (texture brightness modulation off) |

Polygon mode bytes follow the GPU command bytes (`0x20`–`0x3F`). See
[`../hardware/gpu.md`](../hardware/gpu.md#primitive-command-bytes-gp0-hw).
Sony's own unlit (`LGT`) examples also set **TGE** (modes `0x21`, `0x25`, `0x31`,
`0x35`, …), and RSDLINK does the same.

## Polygon data layout [FMT]

With `n = 4 if QUAD else 3`, the data words appear in this order:

1. **If TME**: `n` words of `[U][V][attr:u16]`. The `attr` of word 0 is
   **CBA** (CLUT address), the `attr` of word 1 is **TSB** (texpage, plus the
   blend rate in bits 5–6 when semi-transparent), and the rest are padding.
2. **Colours**: words of `[R][G][B][mode-copy or pad]`. The first colour of an
   untextured polygon repeats the mode byte.
   * Lit (`LGT=0`), untextured: 1 word, or `n` words if `GRD`.
   * Lit (`LGT=0`), textured: **none**. The texture is modulated by lighting.
   * Unlit (`LGT=1`): `n` words if `IIP` or `GRD`, otherwise 1 word.
3. **Indices** (u16, packed two per word, padded to a word):
   * Lit and Gouraud (`IIP`): `normal0, vertex0, normal1, vertex1, …`
   * Lit and flat: `normal0, vertex0, vertex1, …`
   * Unlit: `vertex0, vertex1, …`

This rule reproduces every `ilen`/`olen` in the manual's tables:

| Mode | Name | Lit `ilen`/`olen` | Lit GRD | Unlit (TGE set) |
|------|------|-------------------|---------|-----------------|
| `0x20` | F3 | 3 / 4 | 5 / 6 | `0x21`: 3 / 4 |
| `0x30` | G3 | 4 / 6 | 6 / 6 | `0x31`: 5 / 6 |
| `0x24` | FT3 | 5 / 7 | | `0x25`: 6 / 7 |
| `0x34` | GT3 | 6 / 9 | | `0x35`: 8 / 9 |
| `0x28` | F4 | 4 / 5 | 7 / 8 | `0x29`: 3 / 5 |
| `0x38` | G4 | 5 / 8 | 8 / 8 | `0x39`: 6 / 8 |
| `0x2C` | FT4 | 7 / 9 | | `0x2D`: 7 / 9 |
| `0x3C` | GT4 | 8 / 12 | | `0x3D`: 10 / 12 |

## Lines and 3D sprites [FMT]

| Mode | Kind | `ilen`/`olen` | Data |
|------|------|---------------|------|
| `0x40` | Line, one colour | 2 / 3 | `[R G B mode]` `[vertex0 \| vertex1]` |
| `0x50` | Line, two colours (IIP) | 3 / 4 | `[R0 G0 B0 mode]` `[R1 G1 B1 pad]` `[vertex0 \| vertex1]` |
| `0x64` | Sprite, free size | 3 / 5 | `[vertex0 \| TSB]` `[U V \| CBA]` `[W \| H]` |
| `0x6C` / `0x74` / `0x7C` | Sprite 1×1 / 8×8 / 16×16 | 2 / 4 | `[vertex0 \| TSB]` `[U V \| CBA]` |

`[a | b]` is one word with `a` in the low halfword. A line's mode is
`010 IIP 0 0 ABE 0`, and a sprite's is `011 SIZ 1 ABE 0`, where SIZ (bits 4–3) selects
the size. The Net Yaroze libps could not draw lines, sprites, double-sided
polygons or untextured Gouraud quads from a TMD (a library bug listed in
Sony's FAQ). Use thin polygons instead.

`ref/tools/tmd.py` computes the expected `ilen` for every kind and **refuses to
decode** any primitive whose header disagrees. It skips that primitive using
`ilen` and records it under `skipped`, so an unusual variant can never be
misread as garbage geometry.

## Validation against real files

`python -m ref.tools.validate` over the Net Yaroze samples (`gwald/netyaroze_demo`)
parses 245 TMDs, about 77,000 primitives in 15 kinds, with **nothing skipped**:

| Kind | Count | Kind | Count |
|------|-------|------|-------|
| G3 `0x30` | 38,769 | F3 GRD `0x20`/4 | 576 |
| F3 `0x20` | 28,156 | F3 double-sided `0x20`/2 | 501 |
| GT3 `0x34` | 4,155 | FT4 `0x2C` | 452 |
| G3 double-sided `0x30`/2 | 3,027 | FT3 `0x24` | 306 |
| F4 `0x28` | 869 | GT4 `0x3C` | 293 |

The four files it rejects are 96-byte `temp1.tmd` RAM dumps (`FIXP = 1`, with
pointers at `0x80095xxx`) that were cut off before their vertex list. The
parser infers the RAM base correctly, then reports them as truncated.

## Notes for decompilation work [TYP]

* `FIXP = 1` TMDs found in RAM dumps have pointers already relocated to
  `0x80xx_xxxx` addresses. `read_tmd` infers the base as the lowest list
  pointer minus the object table size, or you can pass `base` explicitly.
* Many games embed TMD-like structures without the `0x41` header, or use custom
  formats with the same primitive packets. Recognising the `olen, ilen, flag,
  mode` rhythm is the key heuristic. See
  [`../models/modeling-guide.md`](../models/modeling-guide.md#inspecting-an-extracted-model-checklist).
* A TMD names textures by VRAM position (TSB/CBA), not by file. To view a
  textured model, load its TIMs where their headers say.
* Related formats: **RSD** (the text source, see [`rsd.md`](rsd.md)), **HMD**
  (hierarchical model and animation, later SDKs), **PMD** (pre-built packets
  with fixed shading), **TOD** (animation data for TMD objects).

## Tool usage

```bash
python -m ref tmd info model.tmd              # objects, counts, primitive histogram
python -m ref tmd obj  model.tmd --out m.obj  # positions, normals, UVs, faces; lines as `l`, sprites as `p`
```
