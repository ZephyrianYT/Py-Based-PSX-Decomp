# PS1 models: budgets, construction and animation

> **TL;DR**: PS1 models are built from **16-bit integer vertices**, **1.3.12
> normals**, and **8-bit UVs into 256×256 texture pages**, using a mix of triangles
> and **quads**. Characters are typically **a few hundred to ~1,500 polygons**,
> made of **rigid parts** in a joint hierarchy (no skinning), and textured from
> **4- or 8-bit palettised atlases**, often 128×128 to 256×256. Environments rely
> on **baked vertex colours** for lighting. The standard Sony container is
> **TMD** (static meshes). Most games also used custom formats with the same
> building blocks.

## Data building blocks [HW] [FMT]

| Element | PS1 representation | Consequence for art |
|---------|--------------------|---------------------|
| Vertex position | `int16 x, y, z` (`SVECTOR`) | Pick a unit scale where the model spans hundreds to thousands of units, and never more than ±32767 |
| Normal | `int16` 1.3.12 (4096 = 1.0) | Low-precision smooth shading. Split normals for hard edges. |
| UV | `uint8 u, v` in a 256×256 texture page | One polygon samples one page. UV precision is whole texels. |
| Texture | 4-bit / 8-bit CLUT, or 15-bit direct | Palette-limited painting. CLUT swaps give recolours for free. |
| Colour | `uint8 r, g, b` per face or per vertex | Baked lighting and gradients. 128 is neutral when modulating textures. |
| Primitive | Triangle or quad, flat or Gouraud, textured or not | Quads are cheaper per area (one packet, four vertices shared) |
| Transform | 1.3.12 rotation matrix + 32-bit translation per part | Rigid parts animate cheaply |

### Axes and winding [FMT]

Sony's model space (TMD, RSD, libgs) is **X right, Y down, Z away from the
viewer**, so "up" is −Y. A polygon's front is the side from which its vertices
run **clockwise** on screen. In the Net Yaroze sample models, 96% of lit
polygons follow this rule (see [`../formats/tmd.md`](../formats/tmd.md#coordinates-and-winding-fmt)).
When moving models to Y-up, counter-clockwise tools (Blender, glTF, OBJ), negate
Y and **keep** the vertex order. The mirror already flips the winding.
Check both before deciding an extracted model is upside down or inside out.

### How models were authored [SDK]

Sony's pipeline was: a 3D package → **RSD** text (PLY geometry, MAT materials,
GRP groups) → **RSDLINK** → TMD, with textures as TIMs placed in VRAM by hand.
`ref/tools/rsd.py` reproduces RSDLINK byte for byte. See [`../formats/rsd.md`](../formats/rsd.md).
The Net Yaroze version of libps could not draw lines, 3D sprites,
double-sided polygons or untextured Gouraud quads from a TMD, so its models
avoid them.

## Typical budgets [TYP]

These ranges are approximate. They vary widely between early and late titles
and between genres, and are guidance rather than limits.

| Asset | Polygons (tris + quads) | Texture |
|-------|------------------------|---------|
| Player character (3rd person action) | ~300 – 1,500 | 1–2 pages' worth: 128×128 – 256×256, 4/8-bit |
| Fighting game character (one or two on screen) | ~500 – 2,000 | Larger share of VRAM |
| Common enemy / NPC | ~100 – 600 | 64×64 – 128×128, 4-bit, CLUT variants |
| Prop (crate, barrel, lamp) | ~6 – 100 | 32×32 – 64×64, 4-bit |
| Vehicle (racing game) | ~200 – 800 | 128×128 – 256×256 |
| Whole visible scene per frame | ~1,500 – 5,000 at 30 fps | Everything left in VRAM after the framebuffers (~700 KB) |

Sony's launch-era figures were about **360,000 flat polygons/s** and about
**180,000 textured, lit polygons/s** peak. Shipping games reached far less once
game logic, sorting, clipping and overdraw are included.

## Topology rules [TYP]

1. **Prefer quads on flat or regular surfaces.** A quad is one GPU packet and
   four transformed vertices. Two triangles cost more CPU time to sort and link.
   Note that the hardware still splits it into two affine triangles.
2. **Keep polygons uniformly sized.** Big polygons warp (affine), sort badly
   (single OTZ), and can exceed the 1023×511 size limit up close.
3. **Avoid T-junctions.** They cause sparkle cracks. Weld vertices and keep edges
   continuous.
4. **Avoid long thin triangles.** They jitter visibly and cull unreliably.
5. **Subdivide where the camera gets close.** Floors and walls near the player
   path need more density. Distant geometry needs very little.
6. **Silhouette first.** Spend polygons on outline and big forms. Interior detail
   goes into the texture.
7. **Hard edges by splitting normals or using flat primitives.** A model can mix
   flat and Gouraud primitives.

## Texturing [TYP] [HW]

* **Atlas everything** a model uses into as few texture pages as possible. Each
  page or CLUT change costs draw-mode state changes.
* Paint at **final resolution** with a **16-colour palette** for most surfaces.
  256 colours is for faces and hero detail.
* **Bake lighting, grime and AO into the texture and the vertex colours.** There
  is no runtime per-pixel lighting.
* Use **colour `0x0000` (index 0 mapped to transparent black)** for cut-outs
  such as hair cards, foliage, fences and grilles.
* Faces: a small, high-contrast face texture is usually more effective than
  geometry. Some games swap face textures for expressions.
* **Mirror UVs** for symmetric halves to save texture space.
* UVs snap to whole texels, so leave 1-texel padding between islands, because
  there is no filtering bleed to worry about but rounding can still pick the
  neighbour texel.

## Vertex colour [TYP]

* Environment meshes almost always carry **per-vertex colour**: painted
  shadows under objects, darkened corners, coloured light pools, sky gradients.
* Gouraud-textured primitives modulate texels by it at no extra cost.
* For untextured "flat art" geometry, such as distant hills, skies and simple
  props, vertex colour *is* the material. Spyro the Dragon's skies are a
  well-known example of vertex-coloured geometry used as a skybox. [CASE]

## Animation [TYP] [CASE]

| Technique | How it works | Look |
|-----------|--------------|------|
| **Rigid hierarchy** (most common) | Each body part is a separate mesh with its own matrix. Joints are keyframed rotations, plus a root translation. | Visible overlaps or gaps at elbows and knees, and a "puppet" quality |
| **Vertex animation** | Store vertex positions per frame (often compressed or delta-encoded) | Smooth deformation at a high memory cost. Andy Gavin has described Crash Bandicoot's characters as vertex-animated. |
| **Limited vertex blending** | Some vertices near joints are attached to two parts | Hides joint gaps. Rarer, mostly later titles. |
| **Texture / CLUT swaps** | Change face or eye textures, or palettes | Expressions, damage states, blinking |
| **Sprite / billboard effects** | Camera-facing rectangles (GPU `64h`/`74h`/`7Ch`) | Explosions, smoke, distant trees and crowds |

* Keyframes are usually sampled at **15–30 Hz** and are often not interpolated,
  which gives visibly stepped motion.
* Rotations are typically stored as 12-bit angles (4096 = 360°) or as matrices.
* Sony's libgs **HMD** format added hierarchical models and animation late in
  the console's life. Many studios used their own formats instead.

## Level of detail [TYP]

* Two or three LOD meshes per important object, switched by distance (with
  visible pops).
* Distant objects become **billboards** or are culled entirely behind fog.
* Spyro the Dragon is a well-known example of a game that swapped in
  low-detail versions of distant level geometry to extend its view distance. [CASE]

## Making a PS1-style model in Blender (workflow)

1. Set the unit scale so the character is around 1,000–2,000 units tall. This
   matches int16 precision after export.
2. Block out the silhouette with about 300–800 faces. Keep quads on limbs and torso.
3. Split into rigid parts at joints (head, torso, pelvis, upper and lower arms,
   hands, thighs, shins, feet). Keep each part as a separate object, parented in a hierarchy.
4. Unwrap everything into one 128×128 or 256×256 atlas, and paint it with a
   16- or 256-colour palette.
5. Paint vertex colours for AO and baked light.
6. Preview with the shaders in [`../look/shaders/`](../look/shaders/), or export
   to OBJ and render with `ref/tools/raster.py`.
7. Optional: write RSD text and link it with `python -m ref rsd tmd`, or build a TMD with `ref/tools/tmd.py` (`write_tmd`), to check that
   it fits the format's limits.

## Inspecting an extracted model (checklist)

* Are vertices `int16` triples followed by a pad halfword (8-byte stride)? That
  is TMD / `SVECTOR` style.
* Are there `int16` values whose magnitude is at most 4096 in groups of 3?
  Those are likely 1.3.12 normals.
* Are there pairs of bytes in the range 0–255 next to a halfword whose bits match
  a CLUT or texpage layout? Those are textured primitive data. See
  [`../hardware/gpu.md`](../hardware/gpu.md#attribute-halfwords-in-a-textured-packet-hw).
* Do primitive headers repeat with a constant pattern like
  `olen, ilen, flag, mode`, where mode is in `0x20–0x3F`? That is TMD. See
  [`../formats/tmd.md`](../formats/tmd.md).
