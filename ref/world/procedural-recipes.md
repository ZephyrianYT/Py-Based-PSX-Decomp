# Procedural recipes for PS1-style worlds

> **TL;DR**: Generate on a **coarse integer grid**. Emit **quads** of roughly
> uniform size. **Bake** all lighting into **vertex colours** quantised to 15-bit
> levels. Group faces into **chunks** that can be culled. Set **fog end = cull
> distance**. Check the result against a **polygon budget** per view. Two working
> implementations are in `ref/tools/worldgen.py`: tile terrain (A) and a
> sector-grid dungeon (B). The other recipes (C–F) are the standard pieces around
> them.

These recipes are written for **making new content in the PS1 style**, for
modern games, demos, or teaching. They follow the techniques in
[`world-building.md`](world-building.md).

## Design rules shared by every recipe [TYP]

| Rule | Why (PS1 cause) |
|------|-----------------|
| Integer coordinates, a fixed grid unit (256 or 1024) | 16-bit vertices, and grid collision |
| Quads of similar screen size | Affine warping and OT sorting get worse with large polygons |
| Subdivide surfaces the camera gets close to | Near-plane dropout and the 1023×511 size limit |
| Vertex colour carries the lighting | Per-pixel lighting does not exist |
| Colours snapped to multiples of 8 | A 5-bit framebuffer. Avoids "wasted" gradient detail. |
| Chunks of ~32–200 faces with bounding boxes | Cull whole chunks before transforming any vertices |
| Fog colour = clear colour = sky horizon colour | Hides the far clip and pop-in |
| Budget: count faces in the worst view | Roughly 1.5k–5k polygons per frame at 30 fps |

---

## A. Tile terrain with baked vertex colour

Implemented as `generate_terrain()`. Example output:
[`../look/images/worldgen_terrain.png`](../look/images/worldgen_terrain.png).

```
1. heights[z][x] = fBm(value_noise, x/8, z/8, 4 octaves)   for a (N+1)×(N+1) grid
2. normalise to 0..1 and scale to integer units (max_height ≈ 1600, cell = 256)
3. for each vertex:
     normal   = (h[x-1]-h[x+1], 2·cell, h[z-1]-h[z+1])          # central differences
     diffuse  = max(0, normal·L)                                 # one sun direction
     ao       = clamp(1 - 4·(avg(neighbours) - h)/max_h, .55, 1) # darker in hollows
     albedo   = palette band by height (sand, grass, dark grass, rock, snow)
     colour   = quantise15(albedo · (0.35 + 0.75·diffuse) · ao)
4. one quad per cell, CCW from above, sharing the grid vertices
5. group cells into 8×8 chunks (64 quads each)
```

* **Why a band palette**: PS1 terrain textures were few and small. Large-scale
  colour variation came from vertex colour. A hand-picked palette reads as
  "painted" rather than "photographic".
* **LOD variant**: for distant chunks, build the same chunk using every second
  vertex (stride 2), so it has 1/4 of the quads. Fill the cracks between LOD
  levels with skirts (vertical quads hanging down from the chunk edge), or hide
  them in fog.
* **Texturing variant**: give every quad UVs `(0,0)-(63,63)` on a 64×64 4-bit
  tile, and switch tiles by height band. Leave the vertex colour at about 128
  where unlit, because PS1 modulation is `texel × colour / 128`.

## B. Sector-grid dungeon

Implemented as `generate_dungeon()`. Example output:
[`../look/images/worldgen_dungeon.png`](../look/images/worldgen_dungeon.png).

```
1. place up to R rooms (3–6 cells per side) at random, rejecting overlaps (1-cell padding)
2. connect room centres with a minimum spanning tree (Prim, Manhattan distance)
3. add K extra random edges, so the level has loops (better for navigation and pacing)
4. carve each edge as an L-shaped corridor (random elbow orientation)
5. for every open cell: floor quad, ceiling quad, and a wall quad on each side
   that borders a solid cell. Each quad faces into the open cell.
6. subdivide each sector face k×k (default 2), as PS1 games did near the camera
7. bake light: ambient 0.08 + Σ torches (1 - d/radius)² → falls off into black
8. chunk by 4×4 cells
```

* Sector size 1024 and wall height 1024 mirror the Tomb Raider-style grid. See
  [`world-building.md`](world-building.md#grid--sector-levels-case).
* **Collision comes for free**: the `grid` returned by
  `generate_dungeon_grid()` *is* the collision map.
* **Black fog** (`FC = 0`) plus torch falloff produces the classic PS1 dungeon
  and horror look, and caps the polygons that need drawing.
* **Variation without new geometry**: use one wall texture with 2–4 CLUTs
  (clean, mossy, bloody, burnt) and choose one per room.

## C. Chunk culling and fog distance

```
for chunk in chunks:
    if chunk.bbox outside frustum: skip
    d = distance(camera, chunk.bbox)
    if d > FOG_END: skip                    # fully fogged anyway
    lod = 0 if d < LOD1 else 1 if d < LOD2 else billboard/none
    submit(chunk.lod[lod])
```

Pick `FOG_END` so that the worst view stays within budget, and set the fog to
start at about 40–60 % of `FOG_END`.

## D. Ordering-table bucketing for a generated world

```
OT_LEN = 1024–4096
ZSF3   = OT_LEN · 4096 / (3 · Z_MAX)       # see tools/fixedpoint.zsf_for
otz    = AVSZ3(sz0, sz1, sz2) + bias
```

* Use a separate OT, or the far end of the OT, for the **sky**, and a separate
  pass for the **HUD**.
* Give characters a small negative bias, which draws them later (nearer), so
  that large floor quads do not swallow their feet.
* Keep floor quads small (recipe B's subdivision), so the floor's average depth
  stays representative.

## E. Vertex-coloured sky dome

```
rings   = 4–6 latitude bands, segments = 8–16
colour  = lerp(horizon_colour (= fog colour), zenith_colour, latitude)
draw first, no depth sort, centred on the camera (translation ignored)
```

This uses no textures and no VRAM, and blends seamlessly into the fog.
Spyro-style skies use the same idea with more colour stops.

## F. Budget check

```
worst = max over sampled camera positions of Σ faces in visible chunks (after LOD)
assert worst ≤ budget        # e.g. 3000 faces at 30 fps for a mid-era game
```

`Model.stats()` reports total faces, chunk count, and the largest chunk. A
render through `ref/tools/raster.render_mesh()` returns `drawn_tris`, `culled_back`
and `dropped_near` for a given camera.

---

## Extending

* **Rivers and roads on terrain**: carve heights along a spline, then
  override the vertex colour along it.
* **Caves**: run recipe B with `rooms` replaced by cellular-automata blobs
  (4-5 rule). Keep the cell size at 1024.
* **Towns**: place pre-made building meshes on a terrain grid at
  integer-aligned positions. Use CLUT swaps for variation.
* **Data-seeded worlds** (in the spirit of Vib-Ribbon and Monster Rancher): hash any
  input file into the `seed`, and generation becomes deterministic per input.
