# TMD: PlayStation 3D model format

> **TL;DR**: TMD is Sony's standard static-mesh format from the libgs SDK. It has
> a 12-byte header (`ID = 0x00000041`, FLAGS, NOBJ), then an object table of
> 28-byte entries. Each entry points to a **vertex list** (`int16 x,y,z,pad`),
> a **normal list** (`int16 1.3.12 nx,ny,nz,pad`), and a **primitive list**. Each
> primitive has a 4-byte header `olen, ilen, flag, mode` followed by `ilen`
> words of data. The data holds UV/CLUT/TPAGE, colours, and vertex and normal
> indices, and its layout depends on `mode` and `flag`. All values are little-endian.
> Parser and writer: `ref/tools/tmd.py`.

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
| 0x18 | s32 | `scale`: 2^scale scaling. Usually 0, and ignored by libgs. |

Vertex: `int16 vx, vy, vz, pad` (8 bytes). Normal: `int16 nx, ny, nz, pad`
(8 bytes, 1.3.12, so 4096 = 1.0).

## Primitive header (4 bytes) [FMT]

| Byte | Field | Meaning |
|------|-------|---------|
| 0 | `olen` | Length in words of the **GPU packet** this primitive becomes (ignored when parsing) |
| 1 | `ilen` | Length in words of the **data that follows** this header. Use it to skip unknown primitives. |
| 2 | `flag` | bit 0 **LGT**: 1 = no light-source calculation (colours are used directly) · bit 1 **FCE**: 1 = double-sided · bit 2 **GRD**: 1 = per-vertex colours (gradation) on an otherwise flat primitive |
| 3 | `mode` | bits 7-5 **CODE**: `001` polygon, `010` line, `011` sprite. For polygons: bit 4 **IIP** (Gouraud), bit 3 **QUAD**, bit 2 **TME** (textured), bit 1 **ABE** (semi-transparent), bit 0 **TGE** (texture brightness modulation off) |

Polygon mode bytes follow the GPU command bytes (`0x20`–`0x3F`). See
[`../hardware/gpu.md`](../hardware/gpu.md#primitive-command-bytes-gp0-hw).

## Polygon data layout [FMT]

With `n = 4 if QUAD else 3`, the data words appear in this order:

1. **If TME**: `n` words of `[U][V][attr:u16]`. The `attr` of word 0 is
   **CBA** (CLUT address), the `attr` of word 1 is **TSB** (texpage), and the rest
   are padding.
2. **Colours**: words of `[R][G][B][mode-copy or pad]`:
   * Lit (`LGT=0`), untextured: 1 word, or `n` words if `GRD`.
   * Lit (`LGT=0`), textured: **none**. The texture is modulated by lighting.
   * Unlit (`LGT=1`): `n` words if `IIP` or `GRD`, otherwise 1 word.
3. **Indices** (u16, packed two per word, padded to a word):
   * Lit and Gouraud (`IIP`): `normal0, vertex0, normal1, vertex1, …`
   * Lit and flat: `normal0, vertex0, vertex1, …`
   * Unlit: `vertex0, vertex1, …`

This rule reproduces the `ilen` values of the standard layouts:

| Mode | Name | Lit `ilen` / `olen` | Lit data |
|------|------|---------------------|----------|
| `0x20` | F3 | 3 / 4 | RGB·mode; N0 V0; V1 V2 |
| `0x30` | G3 | 4 / 6 | RGB·mode; N0 V0; N1 V1; N2 V2 |
| `0x24` | FT3 | 5 / 7 | U0V0·CBA; U1V1·TSB; U2V2·pad; N0 V0; V1 V2 |
| `0x34` | GT3 | 6 / 9 | U0V0·CBA; U1V1·TSB; U2V2·pad; N0 V0; N1 V1; N2 V2 |
| `0x28` | F4 | 4 / 5 | RGB·mode; N0 V0; V1 V2; V3 pad |
| `0x38` | G4 | 5 / 8 | RGB·mode; N0 V0; N1 V1; N2 V2; N3 V3 |
| `0x2C` | FT4 | 7 / 9 | 4× UV words; N0 V0; V1 V2; V3 pad |
| `0x3C` | GT4 | 8 / 12 | 4× UV words; N0 V0; N1 V1; N2 V2; N3 V3 |

Unlit examples: F3 `LGT=1` has `ilen 3` (`RGB; V0 V1; V2 pad`). G3 `LGT=1` has
`ilen 5` (`RGB0; RGB1; RGB2; V0 V1; V2 pad`).

`ref/tools/tmd.py` computes the expected `ilen` from this rule and **refuses to
decode** any primitive whose header disagrees. It skips that primitive using
`ilen` and records it under `skipped`, so an unusual variant can never be
misread as garbage geometry. Lines (`CODE 010`) and sprites (`CODE 011`) are
skipped in the same way.

## Notes for decompilation work [TYP]

* `FIXP = 1` TMDs found in RAM dumps have pointers already relocated to
  `0x80xx_xxxx` addresses. Subtract the base address of the object table to
  get offsets back.
* Many games embed TMD-like structures without the `0x41` header, or use custom
  formats with the same primitive packets. Recognising the `olen, ilen, flag,
  mode` rhythm is the key heuristic. See
  [`../models/modeling-guide.md`](../models/modeling-guide.md#inspecting-an-extracted-model-checklist).
* Related libgs formats: **HMD** (hierarchical model and animation, later SDKs),
  **PMD** (pre-built packets with fixed shading), **TOD** (animation data for TMD
  objects).

## Tool usage

```bash
python -m ref.tools.tmd info model.tmd              # objects, counts, primitive mode histogram
python -m ref.tools.tmd obj  model.tmd --out m.obj  # export positions, normals, UVs and faces to OBJ
```
