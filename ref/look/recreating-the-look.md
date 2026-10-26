# Recreating the PS1 look on modern hardware

> **TL;DR**: Render at **320×240** into an offscreen target. **Snap vertices** to that
> pixel grid in the vertex shader. Pass UVs **`noperspective`** (affine). Sample
> textures with **nearest** filtering and **no mipmaps**. Light **per vertex**
> (or use baked vertex colour) and modulate as `tex × col × 2`. Fog **per vertex**
> toward a single colour. Quantise to **5 bits per channel with the PS1 4×4
> dither** in screen space. Upscale with **integer nearest**. Optional extras:
> sort without depth writes for authentic popping, cull near-camera triangles,
> 15–30 fps animation steps, and a CRT/composite pass. Each step maps to one
> artifact in [`visual-signature.md`](visual-signature.md).

## Recipe, in order of impact

| Step | Setting | Artifact it produces |
|------|---------|----------------------|
| 1 | Internal resolution 320×240 (or 256/368/512 wide) | Jaggies, chunky pixels |
| 2 | Vertex snap: `clip.xy = round(clip.xy / clip.w * res/2) / (res/2) * clip.w` | Jitter, wobble |
| 3 | `noperspective` UVs | Affine warping |
| 4 | Nearest filtering, mip level 0, textures ≤ 256² and ideally 64²–128² | Crunchy texels, shimmer |
| 5 | Palette-reduce textures to 16 or 256 colours | Hand-painted CLUT look |
| 6 | Per-vertex lighting / baked vertex colour, `out = tex * vcol * 2.0` | Soft Gouraud lighting |
| 7 | Per-vertex fog: `mix(col, fogColor, fogFactor)` computed in the VS | Fog, short draw distance |
| 8 | 15-bit quantisation + 4×4 dither at internal resolution | Banding and grain |
| 9 | Integer nearest upscale | Crisp pixels |
| 10 | *Optional*: disable depth test and sort by triangle average depth | Sorting pops |
| 11 | *Optional*: discard triangles with a vertex inside a near distance | Near-plane dropout |
| 12 | *Optional*: only 4 blend modes and 1-bit alpha cut-out (`alpha < 0.5 → discard`) | PS1 transparency |
| 13 | *Optional*: 30/25 fps cap and 15 Hz animation sampling | Timing feel |
| 14 | *Optional*: composite blur, scanlines, slight chroma bleed | "As remembered" softness |

### Calibrating strength

Authentic hardware jitter happens at the *internal* resolution. If you render
at a higher resolution but want PS1 wobble, snap to a **virtual** 320×240 grid
anyway. Many modern "PS1-style" games choose a coarser grid (160×120) for
exaggerated wobble. That is a style choice and is not accurate to the hardware.

## Shaders

Ready-to-use GLSL (OpenGL 3.3 / WebGL2 compatible) is in [`shaders/`](shaders/):

* [`psx_vertex.glsl`](shaders/psx_vertex.glsl): vertex snapping, affine UV,
  per-vertex lighting (3 directional lights plus ambient, PS1-style), per-vertex fog.
* [`psx_fragment.glsl`](shaders/psx_fragment.glsl): nearest sampling,
  `×2` modulation, 1-bit cut-out, 15-bit quantisation with the exact PS1 dither
  matrix.

Engine notes:

| Engine | `noperspective` equivalent | Vertex snap location | Nearest sampling |
|--------|---------------------------|----------------------|------------------|
| Godot 4 | `varying noperspective vec2 uv;` in a spatial shader | `vertex()` after `POSITION = PROJECTION_MATRIX * ...` | `uniform sampler2D tex : filter_nearest;` |
| Unity (URP/HLSL) | `noperspective float2 uv : TEXCOORD0;` | vertex function on `positionCS` | Texture import: Filter Mode = Point, no mip maps |
| Unreal | Custom HLSL node / material vertex offset; affine is harder (needs a custom vertex factory or a `uv * w` / `w` trick) | World Position Offset (approximate) | Texture group with Nearest filter |
| Three.js / WebGL2 | `noperspective` is not in GLSL ES 3.0; use the `uv*w` / `w` trick (below) | `onBeforeCompile` vertex chunk | `THREE.NearestFilter`, `generateMipmaps = false` |

**`uv * w` trick (where `noperspective` is unavailable)**: in the VS, output
`vec3(uv * clip.w, clip.w)`. In the FS, divide `.xy / .z`. The hardware's
perspective correction then cancels out, which leaves affine interpolation.

## Software reference

`ref/tools/raster.py` is a slow but readable software rasteriser that applies
these rules exactly as written above: integer vertices, affine or perspective
UVs, ordering-table sort, `×/128` modulation, and dither + 15-bit output. Use it
to generate ground-truth comparison images for your shader:

```bash
python -m ref.tools.demo --out ref_out
# writes ref_out/affine_vs_perspective.png, dither_vs_none.png,
#        jitter_chart.png, sorting_ot_vs_zbuffer.png, fog_depthcue.png
```

## Asset authoring rules for the look

* Model in **small integer units** and keep polygons roughly uniform in size.
  Huge polygons warp and sort badly.
* Use **quads** where the texture has strong straight lines only if you are
  prepared to subdivide. Otherwise triangulate deliberately so the diagonal
  follows the texture.
* Paint textures at final resolution (no downscaled photos), with limited
  palettes, slightly exaggerated contrast, and lighting painted in.
* Bake ambient occlusion and light pools into **vertex colours**.
* See [`../models/modeling-guide.md`](../models/modeling-guide.md) for budgets.
