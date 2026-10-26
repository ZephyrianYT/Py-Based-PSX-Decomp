# The GTE (Geometry Transformation Engine, COP2)

> **TL;DR**: The GTE does all of the PS1's 3D math in **fixed point**. Matrices are
> 16-bit **1.3.12** values (4096 = 1.0), vertices are 16-bit integers, and the
> perspective divide uses a 17-bit reciprocal approximation. Its outputs are
> **integer screen coordinates** (clamped to −1024..1023), a 16-bit depth, an
> averaged ordering-table index, and lit, **depth-cued** (fogged) colours. The
> lost precision is the source of PS1 vertex jitter. The built-in depth cue is
> the source of PS1 distance fog.

## Number formats [HW]

| Notation | Bits | Example | Used for |
|----------|------|---------|----------|
| 1.3.12 | 16 (sign, 3 integer bits, 12 fraction bits) | `0x1000` = 1.0, `-0x0800` = −0.5 | Rotation, light and colour matrices, normals |
| 16-bit int | 16 | −32768..32767 | Model-space vertex coordinates (`SVECTOR`) |
| 32-bit int | 32 | | Translation vector (`TRX/TRY/TRZ`) |
| 16.16 | 32 | | Screen offset `OFX/OFY` |
| 4.12 angles | 12 bits per turn | 4096 = 360° | Angles in Sony's libgte (`rsin/rcos` tables) |

Because model vertices are 16-bit, models are authored in small integer units
and placed relative to the camera, so that world coordinates do not overflow.

## Registers you will see in disassembly [HW]

| Group | Registers | Notes |
|-------|-----------|-------|
| Input vectors | `VXY0, VZ0`, `VXY1, VZ1`, `VXY2, VZ2` | Three 16-bit XYZ vectors |
| Colour in | `RGBC` | Colour plus a "code" byte that is passed through into the GPU command |
| Screen XY FIFO | `SXY0, SXY1, SXY2` (`SXYP` pushes) | Packed `Y<<16 \| X`, ready to copy into a GPU packet |
| Depth FIFO | `SZ0..SZ3` | Unsigned 16-bit screen depth |
| Results | `MAC0..3` (32-bit), `IR0..3` (16-bit) | IR0 holds the depth-cue factor |
| Ordering | `OTZ` | Result of AVSZ3/AVSZ4, the OT index |
| Colour FIFO | `RGB0..RGB2` | Lit / depth-cued colours |
| Control | `RT` (rotation 3×3), `TR` (translation), `L` (light dirs 3×3), `LCM` (light colours 3×3), `BK` (ambient), `FC` (far/fog colour), `OFX OFY`, `H`, `DQA DQB`, `ZSF3 ZSF4`, `FLAG` | Set with `ctc2` |

## Key commands [HW]

The opcode is the low 6 bits of the `cop2` immediate. The full immediates shown
are the ones Sony's `inline_*.h` macros emit.

| Cmd | Full imm | Name | What it does |
|-----|----------|------|--------------|
| `01h` | `0x0180001` | **RTPS** | Rotate, translate and perspective-project one vertex (V0) |
| `30h` | `0x0280030` | **RTPT** | Same for V0, V1 and V2 (one triangle) |
| `06h` | `0x1400006` | **NCLIP** | 2D cross product of the 3 screen vertices, used for back-face culling |
| `2Dh` | `0x158002D` | **AVSZ3** | `OTZ = ZSF3 × (SZ1+SZ2+SZ3) >> 12` |
| `2Eh` | `0x168002E` | **AVSZ4** | `OTZ = ZSF4 × (SZ0+SZ1+SZ2+SZ3) >> 12` |
| `12h` | | MVMVA | General matrix × vector + translation |
| `13h` / `16h` | | NCDS / NCDT | Normal → light → colour → depth-cue, for 1 or 3 vertices |
| `1Bh` / `3Fh` | | NCCS / NCCT | Same as NCDS/NCDT, without the depth cue |
| `1Eh` / `20h` | | NCS / NCT | Normal → light colour only |
| `10h` / `2Ah` | | DPCS / DPCT | Depth-cue a colour toward the far colour `FC` |
| `11h` | | INTPL | Interpolate IR toward FC by IR0 |
| `28h` | | SQR | Square IR1..3 |
| `0Ch` | | OP | Outer product (cross product) |
| `3Dh` / `3Eh` | | GPF / GPL | General interpolation helpers |

## Perspective transform (RTPS), simplified [HW]

```
MAC1..3 = (TR << 12) + RT · V        then >> 12 (with sf = 1)
IR1..3  = clamp16(MAC1..3)
SZ3     = clamp(MAC3, 0, 0xFFFF)
n       = min(0x1FFFF, ((H << 17) / SZ3 + 1) >> 1)     ← unsigned Newton-Raphson reciprocal
SX2     = clamp((OFX + IR1 · n) >> 16, -0x400, 0x3FF)  ← integer pixels
SY2     = clamp((OFY + IR2 · n) >> 16, -0x400, 0x3FF)
IR0     = clamp((DQB + DQA · n) >> 12, 0, 0x1000)      ← depth-cue factor
```

* **H** is the projection-plane distance. It sets the field of view: a smaller
  H gives a wider FOV.
* If `SZ3` is too small (`H ≥ 2·SZ3`), the divide overflows, `n` saturates, and
  a FLAG bit is set. Vertices very close to the camera therefore explode or
  stretch, unless the game clips them first.
* Because `SX`/`SY` are integers and `n` is only 17-bit, a vertex moving
  slowly in 3D moves on screen in **whole-pixel steps**, and the step size
  changes with depth. Every vertex rounds independently, so polygons wobble
  and seams crack. This is the classic PS1 jitter.

## Back-face culling (NCLIP) [HW]

```
MAC0 = SX0·SY1 + SX1·SY2 + SX2·SY0 − SX0·SY2 − SX1·SY0 − SX2·SY1
```

The sign gives the winding. Games skip the primitive when `MAC0 <= 0`, or
`>= 0`, depending on their convention. The test runs on already-snapped integer
coordinates, so very thin or distant triangles can flicker between visible and
culled.

## Depth sorting (AVSZ3/AVSZ4) [HW]

`OTZ` is the averaged depth scaled by `ZSF3` / `ZSF4`. The CPU uses it directly
as the ordering table index. **One depth value per polygon** is the reason for
PS1 sorting errors: a large floor polygon's average can land "behind" a
character standing on it, so the character is hidden or clips through. See
[`../look/visual-signature.md`](../look/visual-signature.md) § Sorting errors.

Typical setup: `ZSF3 = OT_LEN · 0x1000 / (3 · Z_RANGE)`, so the sum of three
SZ values maps across the OT. Games often use a coarse OT, with a few hundred to
a few thousand entries, plus separate small OTs for the HUD and sky.

## Lighting [HW]

```
IR   = clamp0( L · N )            per light: L is 3 light directions × the normal (1.3.12)
IR   = BK + LCM · IR              ambient + coloured light contributions
RGB  = clamp( RGBC × IR )         modulate the vertex or material colour
RGB  = RGB + (FC − RGB) · IR0     (NCDS/NCDT only) depth cue toward the far colour
```

* Up to **three directional lights**, plus ambient (`BK`). There are no point
  lights in hardware. Games fake them by recomputing `L` per object from the
  nearest light position.
* Lighting is per **vertex**. Combined with Gouraud shading, this gives the soft,
  low-frequency PS1 lighting look.
* Many games skip runtime lighting for the environment and use **pre-baked
  vertex colours** instead. See [`../models/modeling-guide.md`](../models/modeling-guide.md).

## Depth cueing = PS1 fog [HW] [TYP]

`IR0` rises from 0 (near) to 0x1000 (far) as `DQB + DQA·(H/SZ)`. DPCS, DPCT
and NCDS/NCDT blend the colour toward the far colour **FC** by IR0. A game sets
FC to its fog or sky colour, so distant geometry fades into the background,
**per vertex**. This hides the short draw distance. Silent Hill is the most famous
example. Because the blend is per vertex and Gouraud-interpolated, large
polygons fog unevenly.

## Python model

`ref/tools/fixedpoint.py` implements these formulas:

| Function | Models |
|----------|--------|
| `to_fx12(x)` / `from_fx12(v)` | 1.3.12 conversion |
| `rot_matrix_xyz(ax, ay, az)` | Rotation matrix in 1.3.12 (angles in 4096-per-turn units) |
| `rtps(v, rt, tr, h, ofx, ofy, dqa, dqb)` | One vertex → `(sx, sy, sz, ir0)` with integer rounding |
| `nclip(p0, p1, p2)` | Winding / back-face test |
| `avsz3(sz1, sz2, sz3, zsf3)` | OT index |
| `depth_cue(rgb, far_rgb, ir0)` | Fog blend |

Run `python -m ref.tools.fixedpoint` to print a jitter table. It shows a
vertex moving smoothly in 3D while its screen position moves in integer steps.
