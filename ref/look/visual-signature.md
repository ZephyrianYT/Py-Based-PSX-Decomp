# The PS1 visual signature

> **TL;DR**: PS1 graphics are recognisable from a short list of artifacts, and each
> one has a specific hardware cause:
> **affine texture warping** (no perspective divide), **vertex jitter** (integer
> screen coordinates), **sorting errors** (no Z-buffer, one depth per polygon),
> **near-camera polygon dropout** (no hardware clipping), **15-bit colour with a
> 4×4 dither**, **unfiltered low-res textures** (no bilinear, no mipmaps),
> **per-vertex Gouraud lighting and baked vertex colour**, **depth-cue fog with
> a short draw distance**, and **rigid-segment character animation**. A
> convincing "PS1 look" needs most of these at once. Pixelating the screen alone
> does not produce it.

Use this file to **inspect** footage (say which artifacts are present and why)
or to **specify** a stylised renderer (decide which artifacts to reproduce).

## Quick inspection checklist

| # | Artifact | Look for | Root cause | Ref |
|---|----------|----------|------------|-----|
| 1 | Affine texture warping | Texture lines bend and "swim" on floors and walls as the camera turns, with a kink along quad diagonals | UV interpolated linearly in screen space | [gpu.md](../hardware/gpu.md#rasterisation-rules-hw) |
| 2 | Vertex jitter / wobble | Edges shake by whole pixels on slow camera moves, and models "breathe" | Integer screen coordinates and a low-precision divide | [gte.md](../hardware/gte.md#perspective-transform-rtps-simplified-hw) |
| 3 | Seam cracks / sparkles | Single-pixel gaps flickering between adjacent polygons, especially at T-junctions | Independent rounding of shared vertices | §3 |
| 4 | Sorting errors | Objects pop in front of or behind each other, and characters' feet vanish into floors | No Z-buffer, painter's order by one average depth | [gte.md](../hardware/gte.md#depth-sorting-avsz3avsz4-hw) |
| 5 | Near-plane dropout | Polygons near the camera vanish or stretch to infinity | No hardware near clipping, and the divide overflows | §5 |
| 6 | Banding and dither | Visible steps in gradients, and a fixed 4×4 grain pattern on shaded surfaces | 5 bits per channel output, ordered dither | [gpu.md](../hardware/gpu.md#dithering-hw) |
| 7 | Crunchy textures | Big blocky texels up close, shimmering and moiré in the distance | Nearest-neighbour sampling, no mipmaps | §7 |
| 8 | Low texture resolution and palettes | 64×64 to 128×128 textures, 16 or 256 colours each, obvious tiling | 1 MB of VRAM shared with framebuffers, 4/8-bit CLUTs | [gpu.md](../hardware/gpu.md#texture-pages-and-cluts-hw) |
| 9 | Soft vertex lighting | Smooth colour gradients across big polygons, with no sharp highlights or shadows | Per-vertex lighting plus Gouraud interpolation | [gte.md](../hardware/gte.md#lighting-hw) |
| 10 | Fog and short draw distance | Geometry fades to a flat colour or to black within a short distance, then pops in | Depth cue to FC, and polygon budget | [gte.md](../hardware/gte.md#depth-cueing--ps1-fog-hw-typ) |
| 11 | Jaggies | Stair-stepped edges that crawl, with no anti-aliasing | 320×240, no AA hardware | §11 |
| 12 | Limited transparency | Additive glows, 50/50 water, cut-out foliage with hard edges | 4 fixed blend modes, 1-bit per-texel translucency | [gpu.md](../hardware/gpu.md#semi-transparency-hw) |
| 13 | Low-poly, rigid models | Faceted silhouettes, separate limb pieces, visible gaps or overlaps at joints | Polygon budget, mostly no skinning | [modeling-guide.md](../models/modeling-guide.md) |
| 14 | Low and unstable frame rate | 30 / 25 fps or lower, slowdown under load | CPU/GTE/GPU budget | §14 |
| 15 | Pre-rendered and FMV elements | Static detailed backgrounds with low-poly characters, and blocky video | MDEC video, depth-masked 2D backdrops | [world-building.md](../world/world-building.md) |
| 16 | Composite / CRT softness | Horizontal colour bleed and scanlines when shown on original displays | Video output path, not the GPU | §16 |

---

## 1. Affine texture warping [HW]

**What you see**: Straight lines in a texture (bricks, floor tiles) bend into
curves on polygons seen at an angle, and the curve changes as the camera moves.
On quads, the texture visibly kinks along the diagonal, because each of the two
triangles is mapped separately.

**Why**: The GPU interpolates `u, v` linearly across the screen. Correct
perspective mapping would interpolate `u/z, v/z, 1/z` and divide per pixel,
which needs a per-pixel divider that the PS1 does not have.

**How games reduced it**: They **subdivided** large polygons near the camera, so
each piece covers fewer pixels and the error shrinks. The subdivision was often
adaptive, so the subdivision level changing could itself be seen as a "pop".
Artists also avoided long straight texture lines on floors.

**Reproduce**: Interpolate UVs without perspective correction
(GLSL `noperspective`). See `tools/raster.py` (`affine=True`).

## 2. Vertex snapping / jitter [HW]

**What you see**: When the camera or an object moves slowly, edges step a
whole pixel at a time, and different vertices step at different moments, so
models seem to wobble.

**Why**: The GTE returns integer screen coordinates, the GPU has no
sub-pixel precision, and the perspective reciprocal is only about 17 bits.
Some engines added extra rounding of their own, for example by storing
vertices at low precision or using coarse animation fixed point.

**Reproduce**: In clip space, snap `xy/w` to the target pixel grid (for example
320×240) and multiply back by `w`. Run `python -m ref.tools.fixedpoint` to see it.

## 3. Seam cracks and sparkles [HW]

**What you see**: Single-pixel holes along edges where polygons meet, which
flicker as the view changes. They are common at **T-junctions**, where one
polygon's edge midpoint touches another polygon's corner.

**Why**: A vertex shared by two polygons is usually projected once, but a
T-junction point is not exactly on the neighbouring edge after rounding. Also,
each primitive is rasterised independently with integer edges.

**Inspection hint**: Sparkles that show the background colour, often the
clear colour, along mesh seams are a strong PS1 tell.

## 4. Sorting errors (no Z-buffer) [HW]

**What you see**: Polygons from different objects swap order abruptly ("pop"),
a character's feet disappear into a large floor polygon, or a wall in front of
an object is drawn behind it.

**Why**: Order comes from the ordering table: one depth bucket per polygon,
usually the average Z of its vertices (AVSZ3/AVSZ4), drawn far to near. Large
polygons have an average depth that does not represent all of their pixels.

**How games mitigated it**: Subdividing floors, adding a bias to the OT
index for specific objects (characters always slightly in front), using separate
OTs for layers (sky / world / characters / HUD), pre-sorted static geometry per
camera zone, and level design that avoids problematic overlaps.

## 5. Near-plane dropout [HW]

**What you see**: Walls or floor polygons right in front of the camera
suddenly vanish, or a vertex flings off to the screen edge.

**Why**: There is no hardware clipping against the near plane. When a vertex's
`SZ` is very small, the GTE divide saturates. Many engines simply **discarded**
any polygon with a vertex too near or behind the camera, or any polygon larger
than the GPU's 1023×511 limit. Better engines subdivided or clipped on the CPU.

## 6. 15-bit colour, banding and dither [HW]

**What you see**: Gradients (sky, fog, Gouraud-lit walls) show distinct steps,
overlaid with a fine, regular cross-hatch pattern that stays fixed to the
screen as the camera moves.

**Why**: The framebuffer holds 5 bits per channel (32 levels). The optional 4×4
ordered dither (see [`gpu.md`](../hardware/gpu.md#dithering-hw)) trades banding for
grain. Flat-shaded untextured polygons and sprites are not dithered, so the
grain appears only on shaded or modulated surfaces.

**Reproduce**: Add `DITHER[y&3][x&3]` to the 8-bit colour, clamp it, then
truncate it to 5 bits (`>>3`). Do this in **screen space** at the target
resolution, not at the upscaled resolution.

## 7. Unfiltered textures, no mipmaps [HW]

**What you see**: Up close, large square texels with hard edges. Far away,
shimmering, sparkly noise and moiré as texels alias.

**Why**: Nearest-neighbour fetch only, and no mip chain. Some games
hand-authored lower-detail textures for distant LOD models, which is effectively
manual mipmapping per object.

## 8. Low texture resolution and palettes [HW] [TYP]

* All textures, framebuffers and CLUTs share **1 MB** of VRAM. After two 320×240
  framebuffers (about 300 KB), roughly 700 KB remains for a whole scene.
* Typical environment textures are **32×32 to 128×128**. Character atlases are
  typically **128×128 to 256×256**, in **4-bit (16 colours) or 8-bit (256
  colours)**. 15-bit direct textures were rare in 3D games because they use four
  times the VRAM of 4-bit ones.
* Textures were often **hand-painted or heavily touched up**, with high contrast
  and baked lighting detail, because there was no runtime lighting detail.
* A texture cannot repeat beyond a 256-texel page except through the texture
  window register, so large surfaces are built from many tiled polygons.

## 9. Per-vertex lighting and baked colour [HW] [TYP]

* At most three directional lights plus ambient, evaluated **per vertex**, with no
  specular highlights and no per-pixel normals.
* Environments typically used **pre-computed vertex colours**, painted or baked
  offline, to fake shadows, light pools and ambient occlusion. That is free at
  runtime, because a Gouraud-textured polygon modulates the texture by vertex colour.
* Because modulation is `texel × colour / 128`, vertex colours above 128
  *brighten* the texture. Some games use this for hot spots.
* Shiny surfaces were faked with environment-mapping-style UV tricks or
  with additive overlays.

## 10. Fog and draw distance [HW] [TYP]

* Distance fog is the GTE depth cue: per-vertex interpolation toward a
  single far colour (`FC`).
* **Black fog** works as darkness (Resident Evil-style corridors, many
  horror games). **Coloured fog** sets mood (Silent Hill's white/grey fog
  hid a famously short draw distance).
* Without fog, geometry pops in at the far clip and LOD switches are visible.
  See [`../world/world-building.md`](../world/world-building.md).

## 11. Jaggies and low resolution [HW]

320×240 (or 256×240 / 512×240 / 640×480i) with no anti-aliasing. Edges
stair-step and "crawl" in motion. When you scale it up for display, use integer
**nearest-neighbour** scaling for a crisp look, or simulate a CRT for an
authentic one. Do not use bilinear upscaling.

## 12. Limited transparency [HW]

* Exactly four blend equations: average, additive, subtractive, and quarter-add.
* Per-texel translucency is **one bit** (bit 15). There is no smooth alpha
  gradient within a texture, so smoke and glow are drawn as many additive sprites.
* Alpha-tested foliage has hard pixel edges (colour `0x0000` = transparent).

## 13. Low-poly, rigid models [TYP]

Characters are typically a few hundred to about 1,500 triangles, built from
separate rigid pieces (head, torso, upper arm, and so on) that are each
transformed by one matrix. Joints overlap or show gaps. Some games used limited
vertex blending, but rigid segments are the norm. Details are in
[`../models/modeling-guide.md`](../models/modeling-guide.md).

## 14. Frame rate [TYP]

60 fps 3D was uncommon. 30 fps (NTSC) or 25 fps (PAL) was typical, and many
games dipped lower under load. Animation was often sampled at 15–30 Hz, with
visible stepping.

## 15. Pre-rendered backgrounds and FMV [CASE] [HW]

Fixed-camera games (Final Fantasy VII–IX, Resident Evil 1–3, Parasite Eve)
drew a **pre-rendered 2D background**, with depth-sorted foreground "mask"
sprites for occlusion, and composited low-poly real-time characters on top.
FMV used the MDEC, and 8×8 / 16×16 block artifacts are visible in dark or fast
scenes.

## 16. Composite video and CRT softness [TYP]

Most players saw PS1 output through **composite or RF** on a CRT. That blurred
pixels horizontally, softened the dither pattern into apparent extra colours,
and added scanlines. Crisp emulator screenshots are therefore *harsher* than
what players remember. Include a mild horizontal blur and scanlines if
"as remembered" matters more than "as rendered".

---

## Common misconceptions

| Claim | Reality |
|-------|---------|
| "The PS1 look is just low-res pixelation." | Resolution is one ingredient. Warping, jitter, dithering, fog and sorting matter as much or more. |
| "The PS1 had bilinear filtering." | No. Nearest only. (The N64 had filtering, and comparing the two is a classic exercise.) |
| "The wobble comes from a low-precision Z-buffer." | There is no Z-buffer. Wobble comes from integer XY. |
| "PS1 textures are always 4-bit." | 4-bit and 8-bit CLUT textures dominate, but 15-bit direct textures exist. |
| "Dithering is a post-process filter." | It is applied by the GPU per primitive, only on shaded or modulated polygons, in screen space. |
