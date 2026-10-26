# RSD: Sony's text model format (RSD / PLY / MAT / GRP)

> **TL;DR**: RSD is the *source* form of a PS1 model, the plain text that
> Sony's 3D tools wrote and that **RSDLINK** compiled into a [TMD](tmd.md). It is
> four files: **RSD** (names the others and the TIM textures), **PLY** (float
> vertices and normals, and polygons as indices), **MAT** (per-polygon
> lighting, shading, colour or texture), and **GRP** (named polygon groups). Linking
> scales vertices by a power of two and rounds them to int16, turns normals
> into 1.3.12, and adds each texture image's position in its page to the MAT
> U,V. `ref/tools/rsd.py` reproduces Sony's RSDLINK **byte for byte** on every
> RSD/TMD pair in the Net Yaroze samples.

## Files [FMT]

All four are ASCII text with LF or CR/LF line ends. `#` starts a comment.
Files written on DOS may end with `^Z`, and names are case-insensitive.

### RSD

```
@RSD940102
PLY=car.ply
MAT=car.mat
GRP=car.grp
NTEX=1
TEX[0]=car.tim
```

The first line is a version ID. `NTEX`/`TEX[n]` are only present for textured
models. RSDLINK also looked for textures in `../TIM`.

### PLY: geometry

```
@PLY940102
<vertex count> <normal count> <polygon count>
<x> <y> <z>            × vertex count   (floats)
<nx> <ny> <nz>         × normal count   (floats, unit length)
<flag> <8 numbers>     × polygon count
```

| PLY flag (hex) | Kind | The 8 numbers |
|----------------|------|---------------|
| 0 | Triangle | v0 v1 v2 0, n0 n1 n2 0 |
| 1 | Quad | v0 v1 v2 v3, n0 n1 n2 n3. The order is "Z": (v0,v1,v2) and (v1,v2,v3) are the two triangles. |
| 2 | Line | v0 v1, then zeros |
| 3 | 3D sprite | vertex, width, height, then zeros |

The axes are the same as TMD: X right, **Y down**, Z away. A polygon's front is
the side from which its vertices run **clockwise**. Flat shading uses the
first vertex's normal.

### MAT: materials

```
@MAT940801
<count>
<polygons> <flag> <shading> <type> <values...>
```

* **polygons**: one number, a range `0-5`, or a list `2,4,6`.
* **flag** (hex): bit 0 = no lighting (fixed colour); bit 1 = double-sided;
  bit 2 = semi-transparent; bits 3–5 = blend rate (0: 50/50, 1: add, 2:
  subtract, 3: add 25%).
* **shading**: `F` flat or `G` Gouraud.
* **type**:

| Type | Values | Meaning |
|------|--------|---------|
| `C` | r g b | One colour, no texture |
| `G` | r0 g0 b0 … r3 g3 b3 | A colour per vertex, no texture |
| `T` | tex u0 v0 … u3 v3 | Textured. `tex` is a TEX[] index. |
| `D` | as T, then r g b | Textured, tinted by one colour (for unlit models) |
| `H` | as T, then 4 × rgb | Textured with per-vertex colours (for unlit models) |

MAT U,V are relative to the top-left of the **texture image**, not its page.
That is a common source of "strange UVs" when people hand-convert models.

### GRP

Named lists of polygon numbers, used by the editors. RSDLINK ignores them.

## Linking rules (what RSDLINK did) [FMT] [SIM]

| Input | TMD output |
|-------|------------|
| Vertex (float) | `round(v × 2^s)` as int16, where `s` is the `-s` factor rounded to the nearest power of two. `s` is stored in the TMD object's `scale` field. Rounding is half away from zero. |
| Normal (float) | `round(n × 4096)` (1.3.12) |
| MAT flag bit 0 = 0 (lit) | Normals in the packet. A `T` textured polygon gets no colour. `G` colours set the GRD flag. |
| MAT flag bit 0 = 1 (unlit) | LGT flag and TGE mode bit. Colours in the packet. An unlit `T` gets colour 128 (texture as-is). |
| Shading `G` | IIP (Gouraud) mode bit when lit. Unlit polygons are Gouraud when they have per-vertex colours. |
| Texture | TSB = the TIM's page, plus the blend rate if semi-transparent. CBA = the TIM's CLUT position. U,V += the image's offset in its page. |

## Validation

`python -m ref.tools.validate <netyaroze_demo checkout>` links all 19 RSD
models in the Net Yaroze samples. Four of them have Sony's RSDLINK output
beside them, and all four match byte for byte: `CAR01` (twice, textured),
`SQUARE1` (textured), and `cube` (at scale 32, which its TMD's `scale` field
records as 2⁵).

## Tool usage

```bash
python -m ref rsd info  MODEL.RSD
python -m ref rsd tmd   MODEL.RSD -o MODEL.TMD [-s 32]
python -m ref rsd obj   MODEL.RSD -o MODEL.OBJ
```
