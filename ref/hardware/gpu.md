# The PS1 GPU

> **TL;DR**: The GPU is a **2D** rasteriser. It receives triangles and quads
> whose vertices are already in **integer screen coordinates**, and fills them
> with flat or Gouraud colour and optional **affine** (not perspective-correct)
> texture mapping. It writes 15-bit pixels into a 1024×512 16-bit VRAM that holds
> the framebuffers, textures and palettes together. It has **no Z-buffer, no
> texture filtering and no mipmaps**. Textures are addressed through 256×256
> **texture pages** and 4- or 8-bit textures use **CLUT** palettes. It offers four
> fixed **semi-transparency** blend modes and an optional 4×4 **ordered dither**.

## VRAM [HW]

* **1 MB**, organised as **1024 × 512 halfwords** (16 bits each). There is no
  separate texture memory: framebuffers, textures and palettes all share it.
* Pixel / direct-colour texel format (15-bit BGR + 1 control bit):

```
bit  15   14..10   9..5    4..0
     M    Blue     Green   Red        (5 bits per channel, 0..31)
```

* `M` (bit 15) is the **mask / semi-transparency bit**. For texels, it selects
  whether that texel is blended when the primitive is semi-transparent.
* A texel value of exactly **`0x0000` is fully transparent** and is never
  drawn. To get opaque black, use `0x8000` (M set) or a very dark non-zero colour.

### Typical VRAM layout (320×240 game, double-buffered) [TYP]

```
x→ 0        320          512                     1023
y  ┌─────────┬────────────┬─────────────────────────┐ 0
↓  │ frame   │ tpage 5..7 │ texture pages 8..15     │
   │ buffer A│            │ (256 tall each)         │
   ├─────────┤            │                         │ 240
   │ frame   │            │                         │
   │ buffer B│            ├─────────────────────────┤ 256
   │         │            │ texture pages 24..31    │
   ├─────────┴────────────┤                         │ 480
   │ CLUT rows (palettes) │                         │
   └──────────────────────┴─────────────────────────┘ 511
```

Framebuffers usually sit at the left edge. Everything else is packed in by the
artists and programmers by hand, or with Sony's TIM tool, which is why TIM
files store their own VRAM destination. See [`../formats/tim.md`](../formats/tim.md).

## Texture pages and CLUTs [HW]

* A **texture page (tpage)** is a 256×256 *texel* window. Its top-left corner
  is at `X = 64 × n` (n = 0..15) halfwords and `Y = 0` or `256`.
* Per-primitive **u, v are 8-bit (0–255)**, so one polygon can never sample
  more than 256×256 texels. Larger surfaces are tiled across many polygons, or
  wrapped with the texture window register (GP0 `E2h`).
* Colour depth per page:

| Mode | Texels per halfword | VRAM width of a 256-texel page | Palette |
|------|--------------------|--------------------------------|---------|
| 4-bit | 4 | 64 halfwords | 16-entry CLUT |
| 8-bit | 2 | 128 halfwords | 256-entry CLUT |
| 15-bit direct | 1 | 256 halfwords | none |

* A **CLUT** (colour look-up table) is a row of 16 or 256 halfwords in VRAM.
  Its X position must be a multiple of **16** halfwords, and Y can be 0–511.
  Swapping the CLUT on the same texels is how games produce palette-swapped
  enemies, team colours, and cheap colour-cycling animation.
* In 4-bit mode, the **low nibble is the leftmost texel**.

### Attribute halfwords in a textured packet [HW]

| Field | Bits |
|-------|------|
| **CLUT** (packed with the 1st UV) | `0–5`: X / 16 · `6–14`: Y (0–511) |
| **Texpage** (packed with the 2nd UV) | `0–3`: X base / 64 · `4`: Y base / 256 · `5–6`: semi-transparency mode · `7–8`: colour depth (0 = 4-bit, 1 = 8-bit, 2 = 15-bit) · `11`: texture disable (if enabled in GP1) |

## Primitive command bytes (GP0) [HW]

Polygon commands are `001G QTSR` in binary:

| Bit | Name | Meaning when set |
|-----|------|------------------|
| 4 (G, 0x10) | Gouraud | Each vertex carries its own colour |
| 3 (Q, 0x08) | Quad | Four vertices, drawn as **two triangles** (v1 v2 v3) and (v2 v3 v4) |
| 2 (T, 0x04) | Textured | Each vertex carries u, v |
| 1 (S, 0x02) | Semi-transparent | Blend with the framebuffer using the current mode |
| 0 (R, 0x01) | Raw texture | Do not modulate the texture by the vertex colour |

| Code | Primitive | Words |
|------|-----------|-------|
| `20h` | Flat triangle | 4 |
| `24h` | Flat textured triangle | 7 |
| `28h` | Flat quad | 5 |
| `2Ch` | Flat textured quad | 9 |
| `30h` | Gouraud triangle | 6 |
| `34h` | Gouraud textured triangle | 9 |
| `38h` | Gouraud quad | 8 |
| `3Ch` | Gouraud textured quad | 12 |
| `40h`–`5Fh` | Lines and polylines (flat or Gouraud) | varies |
| `60h` / `64h` | Variable-size rectangle (untextured / textured sprite) | 3 / 4 |
| `68h` | 1×1 dot | 2 |
| `70h` / `74h` | 8×8 rectangle (untextured / textured) | 2 / 3 |
| `78h` / `7Ch` | 16×16 rectangle (untextured / textured) | 2 / 3 |
| `02h` | Fill rectangle in VRAM (ignores mask and draw area; X is rounded to 16) | 3 |
| `80h` / `A0h` / `C0h` | VRAM→VRAM copy / CPU→VRAM upload / VRAM→CPU download | |
| `E1h` | Draw mode (texpage, dither enable, semi-transparency mode) | 1 |
| `E2h` | Texture window (mask and offset for repeating textures) | 1 |
| `E3h` / `E4h` | Drawing area top-left / bottom-right (clip rectangle) | 1 |
| `E5h` | Drawing offset (added to every vertex) | 1 |
| `E6h` | Mask bit: set-while-drawing / test-before-drawing | 1 |

### Layout of a Gouraud textured quad (`3Ch`) [HW]

```
w0  [3Ch][  B1 G1 R1  ]
w1  [   Y1   ][   X1   ]      ← signed 11-bit coordinates, relative to the draw offset
w2  [  CLUT  ][ V1 ][ U1 ]
w3  [ 00 ][  B2 G2 R2  ]
w4  [   Y2   ][   X2   ]
w5  [ TPAGE  ][ V2 ][ U2 ]
w6  [ 00 ][  B3 G3 R3  ]
w7  [   Y3   ][   X3   ]
w8  [  ----  ][ V3 ][ U3 ]
w9  [ 00 ][  B4 G4 R4  ]
w10 [   Y4   ][   X4   ]
w11 [  ----  ][ V4 ][ U4 ]
```

In an ordering table, each packet is preceded by a **tag word**: the upper 8
bits are the packet length in words, and the lower 24 bits are the address of the
next packet (`0xFFFFFF` ends the list).

## Rasterisation rules [HW]

* **Vertex coordinates are integers**, signed 11-bit (−1024..+1023) after the
  drawing offset is added. There is **no sub-pixel precision**, which is the
  root cause of vertex "snapping" and "jitter".
* A polygon is **skipped** entirely if any edge spans more than **1023 pixels
  horizontally or 511 vertically**. Games subdivide big polygons partly for
  this reason.
* Fill convention: the top-left edges are drawn and the bottom-right edges are
  not, so shared edges are drawn exactly once.
* **Colour interpolation** (Gouraud) and **u,v interpolation** are both
  linear in *screen space*. For u,v this is called **affine** mapping, and there
  is no division by depth.
* Quads are split into two triangles, and each triangle is interpolated
  separately. A quad seen in perspective therefore shows a visible bend in its
  texture along the shared diagonal.
* **No texture filtering**: nearest-neighbour texel fetch only. No mipmaps.
* Coordinates are clipped to the drawing area (`E3h`/`E4h`). There is no
  near-plane clipping in hardware, so geometry that crosses the camera plane
  must be clipped, subdivided or discarded on the CPU.

## Shading and texture modulation [HW]

* Vertex colours are 8 bits per channel, BGR.
* With texturing enabled and the raw bit **off**, the result per channel is:

  `out = clamp( texel × colour / 128 , 0, 31 )` on the 5-bit texel scale.

  A vertex colour of **128 (`0x80`) means "unchanged"**, and 255 means about 2×
  brightness. Artists and engines use this to *brighten* textures with lighting
  as well as darken them.

## Semi-transparency [HW]

Four fixed blend equations. B is the background (framebuffer) and F is the
foreground (the new pixel):

| Mode | Equation | Typical use |
|------|----------|-------------|
| 0 | `B/2 + F/2` | Glass, ghosts, water surfaces |
| 1 | `B + F` (additive, saturating) | Fire, explosions, lens flare, light shafts |
| 2 | `B − F` (subtractive, clamped at 0) | Shadows, darkening decals |
| 3 | `B + F/4` | Soft glows and subtle additive effects |

* Untextured semi-transparent primitives blend every pixel.
* Textured semi-transparent primitives blend **only texels with bit 15 set**.
  The other texels are drawn opaque. This allows mixed opaque and translucent
  detail within one texture.
* Blending happens after the order is decided by the ordering table, and there
  is no depth test. Translucent objects only look correct if they are linked
  into the OT in a sensible order.

## Dithering [HW]

When dithering is enabled (`E1h` bit 9), Gouraud-shaded and texture-modulated
primitives have a **4×4 ordered dither** added to each 8-bit channel before it is
truncated to 5 bits:

```
            x=0  x=1  x=2  x=3
   y=0  [   -4,  +0,  -3,  +1 ]
   y=1  [   +2,  -2,  +3,  -1 ]
   y=2  [   -3,  +1,  -4,  +0 ]
   y=3  [   +3,  -1,  +2,  -2 ]
```

The table is indexed by **screen** pixel position `(x & 3, y & 3)`, so the
pattern stays fixed to the screen and does not move with the geometry.
Rectangles (sprites) are not dithered. This pattern, combined with
15-bit colour banding, is the characteristic "screen-door" grain of PS1 gradients.
`tools/raster.py` implements it in `dither_to_15bit()`.

## Mask bit [HW]

`E6h` has two switches:

* **set mask**: every pixel drawn gets bit 15 set.
* **check mask**: pixels whose framebuffer bit 15 is already set are not
  overwritten.

Together they act as a 1-bit stencil. Games used this for HUD protection,
reflections, and drawing order tricks.

## Display output [HW]

| Setting | Values |
|---------|--------|
| Horizontal resolution | 256, 320, 368, 512, 640 |
| Vertical resolution | 240 (NTSC) or 256 (PAL) progressive; 480 or 512 interlaced |
| Colour depth | 15-bit (all 3D rendering); 24-bit display mode (MDEC video / stills only, the GPU cannot draw in it) |
| Refresh | 60 Hz NTSC / 50 Hz PAL. Most 3D games rendered at 30 or 25 fps, or lower. |

The most common 3D game resolution is **320×240** (NTSC). 512×240 and 640×480
interlaced appear in some later or less demanding titles.
