"""A small PS1-rules software rasteriser (see ref/look/recreating-the-look.md).

HOW TO READ THIS FILE
=====================
This module is a teaching model. Its job is to make the PlayStation's visual
quirks *visible and explainable*, not to be fast or cycle-accurate. Read it top
to bottom: each section corresponds to one stage of the real console's frame
pipeline (see ref/hardware/overview.md, "How one frame is produced"):

    1. Colour output      dither_to_15bit()    GPU writes 15-bit pixels with a 4x4 dither
    2. Textures           Texture              VRAM texels, nearest fetch, 0x0000 = see-through
    3. Framebuffer        Framebuffer          a 320x240 grid of 15-bit pixels
    4. Rasterising        draw_triangle()      the GPU filling one screen-space triangle
    5. Sorting            OrderingTable        the CPU's depth buckets (there is no Z-buffer)
    6. Geometry           render_mesh()        the GTE: transform, project, cull, fog

Rules modelled ([SIM] - visible behaviour, not cycle accuracy):
  * vertices are integer screen pixels (GTE output), no sub-pixel precision
  * u,v and colour interpolate linearly in screen space (affine); an optional
    perspective-correct mode exists only for comparison
  * no Z-buffer: primitives are sorted with an ordering table (one depth per
    primitive, far to near); an optional Z-buffer exists for comparison
  * textures are 15-bit halfwords, nearest fetch, 0x0000 is transparent
  * texture modulation is texel * colour / 128 (128 = unchanged)
  * output is 15-bit with the hardware 4x4 ordered dither
  * the four semi-transparency modes
  * polygons wider than 1023 or taller than 511 pixels are dropped

Every "modern" switch (``affine=False``, ``sort="zbuffer"``, ``psx=False``)
exists so you can render the same scene twice and *see* what the PS1 lacked.

World space for ``render_mesh`` is Y-up (like OBJ / Blender); the camera
converts to the PS1's Y-down screen space internally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import fixedpoint as fx


# =============================================================================
# 1. COLOUR OUTPUT: 15-bit pixels and the ordered dither
# =============================================================================
#
# The PS1 framebuffer stores 5 bits per channel (32 levels of red, green and
# blue). Smooth gradients would show hard bands, so the GPU can add a small,
# fixed offset to each pixel *before* throwing away the low 3 bits. The offset
# depends only on the pixel's screen position (x & 3, y & 3), so the pattern is
# glued to the screen, not to the geometry. That is why PS1 gradients look
# "grainy" in a regular cross-hatch that does not move when the camera does.
#
# The table below is the exact hardware matrix (psx-spx, "GPU Dithering").
# Its values range over -4..+3: half of one 5-bit step (8) either way.

DITHER = (
    (-4, +0, -3, +1),
    (+2, -2, +3, -1),
    (-3, +1, -4, +0),
    (+3, -1, +2, -2),
)


def dither_to_15bit(r: int, g: int, b: int, x: int, y: int, dither: bool = True) -> int:
    """8-bit RGB -> 15-bit halfword the way the GPU writes it (dither, clamp, truncate)."""
    if dither:
        d = DITHER[y & 3][x & 3]          # same offset for R, G and B at this pixel
        r, g, b = r + d, g + d, b + d
    # Clamp: adding the dither can push 0 below zero or 255 above 255.
    r = 0 if r < 0 else 255 if r > 255 else r
    g = 0 if g < 0 else 255 if g > 255 else g
    b = 0 if b < 0 else 255 if b > 255 else b
    # Truncate to 5 bits (>> 3) and pack as the PS1 does: bits 0-4 red,
    # 5-9 green, 10-14 blue. Bit 15 (the mask / semi-transparency bit) stays 0.
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def rgb15_to_rgb8(c: int) -> tuple[int, int, int]:
    """Expand a 15-bit pixel back to 8 bits per channel for saving as PNG.

    ``(c5 << 3) | (c5 >> 2)`` copies the top bits into the empty low bits, so
    31 maps to 255 (pure white stays white) rather than 248.
    """
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)


# =============================================================================
# 2. TEXTURES: texels as they sit in VRAM
# =============================================================================
#
# On real hardware a texture lives in VRAM, either as palette indices (4- or
# 8-bit, looked up through a CLUT) or as direct 15-bit colours. This class
# stores the *resolved* 15-bit colours, which is what the GPU ends up blending.
#
# Two PS1 rules are visible here:
#   * Sampling is nearest-neighbour: one texel per pixel, no blending between
#     texels and no mipmaps. Close up you see big square texels; far away you
#     see shimmering, because neighbouring pixels skip over many texels.
#   * The value 0x0000 means "do not draw this pixel" (cut-out transparency).

class Texture:
    """A texture as 15-bit halfwords (already palette-resolved). Wraps on u,v."""

    def __init__(self, width: int, height: int, texels: Sequence[int]):
        if len(texels) != width * height:
            raise ValueError("texel count mismatch")
        self.width, self.height, self.texels = width, height, list(texels)

    @classmethod
    def from_tim(cls, tim, clut_index: int = 0) -> "Texture":
        """Build a texture from a parsed TIM file, choosing one of its palettes.

        Choosing a different ``clut_index`` on the same texels is exactly how PS1
        games made palette-swapped enemies for free.
        """
        from .tim import tim_halfwords
        return cls(tim.width, tim.height, tim_halfwords(tim, clut_index))

    def fetch(self, u: int, v: int) -> int:
        # The modulo wraps coordinates so a texture can repeat. (On hardware,
        # u and v are 8-bit, so they wrap at 256; the texture-window register
        # can wrap them at smaller powers of two.)
        return self.texels[(v % self.height) * self.width + (u % self.width)]


# =============================================================================
# 3. FRAMEBUFFER: the screen the GPU draws into
# =============================================================================

class Framebuffer:
    """A width x height grid of 15-bit pixels, like one display buffer in VRAM.

    Real games keep two of these in VRAM (double buffering): the GPU draws into
    one while the TV shows the other, and they swap every frame.
    """

    def __init__(self, width: int = 320, height: int = 240, clear: tuple[int, int, int] = (0, 0, 0)):
        self.width, self.height = width, height
        c = dither_to_15bit(*clear, 0, 0, dither=False)
        self.pixels = [c] * (width * height)   # row-major: pixel (x, y) is pixels[y * width + x]
        self.zbuf: Optional[list[float]] = None

    def enable_zbuffer(self) -> None:
        """Comparison mode only: the PS1 has NO depth buffer.

        Stores 1/z per pixel; a larger value means nearer to the camera.
        """
        self.zbuf = [0.0] * (self.width * self.height)

    def to_rgb8(self) -> bytes:
        out = bytearray()
        for c in self.pixels:
            out += bytes(rgb15_to_rgb8(c))
        return bytes(out)

    def save_png(self, path: str, scale: int = 1) -> None:
        # Always enlarge PS1 output with integer nearest-neighbour scaling.
        # Smooth (bilinear) scaling would blur away the dither and hard pixels.
        from .pngio import scale_nearest, write_png
        w, h, px = scale_nearest(self.width, self.height, self.to_rgb8(), scale)
        write_png(path, w, h, px)


# =============================================================================
# 4. RASTERISING: how the GPU fills a triangle
# =============================================================================

@dataclass
class ScreenVertex:
    """One corner of a triangle *after* projection, ready for the GPU.

    This is everything a PS1 GPU packet carries per vertex: a screen position,
    a colour, and a texture coordinate. Note what is missing: depth. The GPU
    never sees Z. The ``w`` field exists only for the comparison modes.
    """
    x: float           # integer in PS1 mode
    y: float
    r: int = 128       # vertex colour; 128 means "leave the texture unchanged"
    g: int = 128
    b: int = 128
    u: float = 0.0     # texel coordinate (0-255 on hardware)
    v: float = 0.0
    w: float = 1.0     # 1/z, used only for perspective-correct comparison and the Z-buffer


def _edge(ax, ay, bx, by, px, py):
    """Edge function: which side of the line a->b the point p lies on.

    It is the 2D cross product of (b - a) and (p - a). Zero means p is on the
    line. For a triangle wound consistently, a point is inside when all three
    edge functions have the same sign. The values, divided by the triangle's
    total area, are also the barycentric weights used for interpolation.
    """
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def _blend(mode: int, b: int, f: int) -> int:
    """The four fixed PS1 semi-transparency equations (B = background, F = new pixel).

    There is no general alpha value. These four are all a PS1 game gets.
    """
    if mode == 0:
        return (b + f) >> 1             # 0: B/2 + F/2   average: glass, water, ghosts
    if mode == 1:
        return min(255, b + f)          # 1: B + F       additive: fire, glows
    if mode == 2:
        return max(0, b - f)            # 2: B - F       subtractive: shadows
    return min(255, b + (f >> 2))       # 3: B + F/4     faint additive


def draw_triangle(
    fb: Framebuffer,
    v0: ScreenVertex,
    v1: ScreenVertex,
    v2: ScreenVertex,
    texture: Optional[Texture] = None,
    *,
    affine: bool = True,
    dither: bool = True,
    gouraud: bool = True,
    raw_texture: bool = False,
    semi: Optional[int] = None,
    size_limit: bool = True,
) -> int:
    """Rasterise one triangle. Returns the number of pixels written.

    The parameters mirror bits in a real GPU polygon command:
    ``gouraud`` (per-vertex colours), ``texture`` (textured), ``semi``
    (semi-transparent, plus which blend mode), ``raw_texture`` (skip colour
    modulation). ``affine`` and ``size_limit`` let you switch PS1 behaviour off.
    """
    # --- Step 1: the GPU's size limit. A polygon spanning more than 1023
    # pixels across or 511 down is skipped entirely, with no partial drawing.
    # This is one reason big floor polygons vanish when the camera gets close.
    xs, ys = (v0.x, v1.x, v2.x), (v0.y, v1.y, v2.y)
    if size_limit and (max(xs) - min(xs) > 1023 or max(ys) - min(ys) > 511):
        return 0  # the GPU skips oversized polygons entirely

    # --- Step 2: winding. The edge function of the whole triangle is twice its
    # signed area. We reorder the vertices so the area is positive, which means
    # "inside" is always "all three edge values >= 0". (Back-face culling has
    # already happened earlier, in render_mesh, as it does on the GTE.)
    area = _edge(v0.x, v0.y, v1.x, v1.y, v2.x, v2.y)
    if area == 0:
        return 0                          # degenerate: zero-width triangle
    if area < 0:
        v1, v2 = v2, v1
        area = -area

    # --- Step 3: the fill rule. When two triangles share an edge, the pixels
    # exactly on that edge must be drawn by only one of them. Otherwise they
    # are drawn twice, which shows up as visible seams with semi-transparency.
    # The "top-left" rule says: an on-edge pixel belongs to the triangle only if
    # the edge is a top edge (horizontal, interior below) or a left edge.
    # For other edges we subtract a bias of 1 so "exactly 0" counts as outside.
    def top_left(a, b):
        dx, dy = b.x - a.x, b.y - a.y
        return (dy == 0 and dx > 0) or dy < 0

    bias0 = 0 if top_left(v1, v2) else 1
    bias1 = 0 if top_left(v2, v0) else 1
    bias2 = 0 if top_left(v0, v1) else 1
    # float coordinates (comparison mode) cannot use the integer bias trick
    integer = all(float(c).is_integer() for c in xs + ys)
    if not integer:
        bias0 = bias1 = bias2 = 0

    # --- Step 4: only visit pixels inside the triangle's bounding box,
    # clipped to the screen (the GPU's "drawing area").
    minx = max(0, int(math.floor(min(v0.x, v1.x, v2.x))))
    maxx = min(fb.width - 1, int(math.ceil(max(v0.x, v1.x, v2.x))))
    miny = max(0, int(math.floor(min(v0.y, v1.y, v2.y))))
    maxy = min(fb.height - 1, int(math.ceil(max(v0.y, v1.y, v2.y))))
    written = 0
    zbuf = fb.zbuf
    pix = fb.pixels
    W = fb.width
    for y in range(miny, maxy + 1):
        for x in range(minx, maxx + 1):
            # Inside test: one edge function per edge, each opposite one vertex.
            w0 = _edge(v1.x, v1.y, v2.x, v2.y, x, y)
            w1 = _edge(v2.x, v2.y, v0.x, v0.y, x, y)
            w2 = _edge(v0.x, v0.y, v1.x, v1.y, x, y)
            if w0 - bias0 < 0 or w1 - bias1 < 0 or w2 - bias2 < 0:
                continue
            # Barycentric weights: how much each vertex "owns" this pixel.
            # l0 + l1 + l2 == 1. They are measured in SCREEN space, which is
            # exactly why PS1 interpolation is affine (see Step 6).
            l0, l1, l2 = w0 / area, w1 / area, w2 / area
            idx = y * W + x
            invz = l0 * v0.w + l1 * v1.w + l2 * v2.w

            # Comparison mode only: a per-pixel depth test. The PS1 cannot do
            # this. It relies on drawing order instead (OrderingTable, below).
            if zbuf is not None:
                if invz <= zbuf[idx]:
                    continue

            # --- Step 5: colour. Gouraud shading = blend the three vertex
            # colours by the barycentric weights. Flat = use the first vertex's
            # colour for the whole triangle, as the GPU does.
            if gouraud:  # epsilon keeps exact vertex colours from truncating one level down
                r = l0 * v0.r + l1 * v1.r + l2 * v2.r + 1e-6
                g = l0 * v0.g + l1 * v1.g + l2 * v2.g + 1e-6
                b = l0 * v0.b + l1 * v1.b + l2 * v2.b + 1e-6
            else:
                r, g, b = v0.r, v0.g, v0.b
            stp = True   # "semi-transparency allowed" (bit 15 of the texel, below)

            # --- Step 6: texturing. THIS is the PS1's most famous artifact.
            if texture is not None:
                if affine:
                    # PS1: u,v are blended with the same screen-space weights as
                    # colour. That ignores perspective: a texture on a floor
                    # receding into the distance gets stretched evenly across
                    # the screen instead of compressing with depth. Straight
                    # lines in the texture bend, and they bend differently in
                    # each of a quad's two triangles.
                    u = l0 * v0.u + l1 * v1.u + l2 * v2.u
                    v = l0 * v0.v + l1 * v1.v + l2 * v2.v
                else:
                    # Modern GPUs: interpolate u/z, v/z and 1/z (all of which ARE
                    # linear in screen space), then divide per pixel. The PS1
                    # has no per-pixel divider, so it cannot do this.
                    u = (l0 * v0.u * v0.w + l1 * v1.u * v1.w + l2 * v2.u * v2.w) / invz
                    v = (l0 * v0.v * v0.w + l1 * v1.v * v1.w + l2 * v2.v * v2.w) / invz
                # Nearest-neighbour: round down to one whole texel. No filtering.
                t = texture.fetch(int(math.floor(u)), int(math.floor(v)))
                if t == 0:
                    continue  # 0x0000 = transparent texel
                stp = bool(t & 0x8000)
                # Texel channels as 8-bit values (5-bit << 3).
                tr, tg, tb = (t & 31) << 3, ((t >> 5) & 31) << 3, ((t >> 10) & 31) << 3
                if raw_texture:
                    r, g, b = tr, tg, tb
                else:
                    # Modulation: texel x colour / 128. A vertex colour of 128
                    # leaves the texel as it is, 64 halves it, 255 nearly
                    # doubles it. This is how baked vertex lighting darkens
                    # (or brightens) textures for free.
                    r, g, b = tr * r / 128, tg * g / 128, tb * b / 128
            r, g, b = int(r), int(g), int(b)

            # --- Step 7: semi-transparency. Read what is already on screen and
            # combine. On textured polygons, only texels with bit 15 set blend.
            if semi is not None and stp:
                br, bg, bb = rgb15_to_rgb8(pix[idx])
                r, g, b = _blend(semi, br, r), _blend(semi, bg, g), _blend(semi, bb, b)

            # --- Step 8: write the pixel. The GPU dithers only shaded or
            # texture-modulated polygons; a flat untextured polygon is one solid
            # 15-bit colour.
            shaded = gouraud or (texture is not None and not raw_texture)
            pix[idx] = dither_to_15bit(r, g, b, x, y, dither and shaded)
            if zbuf is not None:
                zbuf[idx] = invz
            written += 1
    return written


# =============================================================================
# 5. SORTING: the ordering table (why there is no Z-buffer and what replaces it)
# =============================================================================
#
# A Z-buffer needs one depth value stored per pixel. The PS1 had neither the
# VRAM nor the bandwidth for that. Instead the CPU keeps an array of "buckets",
# one per depth range. Each polygon goes into ONE bucket, chosen from the
# average depth of its corners. The GPU then draws the buckets from far to
# near, so nearer polygons paint over farther ones (the painter's algorithm).
#
# The weakness: a polygon has only one depth. A long floor polygon's average
# can be nearer than an object standing on its far end, so the floor gets drawn
# last and covers the object. See ref/look/images/sorting_ot_vs_zbuffer.png.

class OrderingTable:
    """Buckets of primitives drawn from the highest index (far) to 0 (near).

    Within a bucket the most recently added primitive is drawn first, matching
    libgpu's addPrim() inserting at the head of each list.
    """

    def __init__(self, length: int = 1024):
        self.buckets: list[list] = [[] for _ in range(length)]

    def add(self, otz: int, prim) -> None:
        # Clamp so depths beyond the table land in the first or last bucket.
        self.buckets[max(0, min(len(self.buckets) - 1, otz))].append(prim)

    def __iter__(self):
        # Far to near; newest first within each bucket.
        for bucket in reversed(self.buckets):
            yield from reversed(bucket)


# =============================================================================
# 6. GEOMETRY: meshes, the camera, and the GTE stage
# =============================================================================

@dataclass
class Face:
    """One polygon of a mesh, plus the GPU attributes it will be drawn with."""
    idx: tuple[int, ...]                                   # 3 or 4 vertex indices, CCW ring seen from the front
    colors: tuple[tuple[int, int, int], ...] = ((128, 128, 128),)  # 1 (flat) or one per vertex
    uvs: Optional[tuple[tuple[int, int], ...]] = None
    texture: Optional[Texture] = None
    semi: Optional[int] = None                             # blend mode 0-3, or None for opaque
    double_sided: bool = False                             # skip back-face culling
    ot_bias: int = 0                                       # negative = drawn later (nearer)


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float]]
    faces: list[Face] = field(default_factory=list)


@dataclass
class Camera:
    """A simple yaw/pitch camera.

    ``h`` is the GTE's "projection plane distance". It acts like focal length:
    screen_x = x * h / z. On a 320-wide screen, h = 160 gives a 90 degree
    horizontal field of view; larger h zooms in.
    """
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw: float = 0.0       # radians, rotation about +Y; 0 looks along +Z
    pitch: float = 0.0     # radians, positive looks down
    h: int = 240           # GTE projection-plane distance (smaller = wider FOV)

    def matrix(self) -> list[list[float]]:
        """World (Y-up) -> view (x right, y down, z forward)."""
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        # yaw: forward = (sin yaw, 0, cos yaw)
        yaw = [[-cy, 0, sy], [0, 1, 0], [sy, 0, cy]]  # right-handed: right = forward x up
        # pitch, then flip Y to point down
        pitch = [[1, 0, 0], [0, -cp, -sp], [0, -sp, cp]]
        return [[sum(pitch[i][k] * yaw[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


@dataclass
class RenderSettings:
    """Switches between PS1 behaviour (defaults) and modern behaviour."""
    psx: bool = True                 # integer GTE projection (False = float, sub-pixel)
    affine: bool = True
    dither: bool = True
    sort: str = "ot"                 # "ot" (PS1) or "zbuffer" (modern comparison)
    ot_len: int = 1024
    z_max: int = 8192                # depth range mapped onto the OT
    near: float = 32.0               # faces with any vertex nearer than this are dropped
    cull_backfaces: bool = True
    fog: Optional[tuple[tuple[int, int, int], float, float]] = None  # (far colour, z start, z full)


def render_mesh(fb: Framebuffer, meshes: Sequence[Mesh], cam: Camera, s: RenderSettings = RenderSettings()) -> dict:
    """Transform, cull, sort and draw meshes. Returns simple stats.

    This function plays the part of the game's CPU code plus the GTE:
    for every vertex, project to the screen; for every face, cull and sort it;
    then hand the sorted list to draw_triangle (the GPU).
    """
    m = cam.matrix()
    cx, cy, cz = cam.position
    ofx, ofy = fb.width // 2, fb.height // 2        # screen centre (GTE OFX/OFY)
    # The GTE holds the rotation matrix in 1.3.12 fixed point (4096 = 1.0).
    # Converting here already loses precision, exactly as on hardware.
    rt = [[fx.to_fx12(m[i][j]) for j in range(3)] for i in range(3)]
    dqa = dqb = 0
    if s.fog:
        # Depth-cue coefficients: the GTE computes a fog factor per vertex.
        dqa, dqb = fx.depth_cue_params(cam.h, int(s.fog[1]), int(s.fog[2]))
    # ZSF3/ZSF4 scale averaged depths onto the ordering table's length.
    zsf3, zsf4 = fx.zsf_for(s.ot_len, s.z_max, 3), fx.zsf_for(s.ot_len, s.z_max, 4)
    ot = OrderingTable(s.ot_len)
    stats = {"faces": 0, "culled_back": 0, "dropped_near": 0, "drawn_tris": 0, "pixels": 0}
    if s.sort == "zbuffer":
        fb.enable_zbuffer()

    for mesh in meshes:
        # ---- Per-vertex stage (the GTE's RTPS/RTPT commands) ----
        proj = []
        for (x, y, z) in mesh.vertices:
            # Work relative to the camera. On the PS1 this also keeps numbers
            # inside the 16-bit vertex range.
            dx, dy, dz = x - cx, y - cy, z - cz
            if s.psx:
                # PS1 path: integer inputs, fixed-point math, INTEGER screen
                # output. Rounding to whole pixels here causes vertex jitter.
                tr = (0, 0, 0)
                r = fx.rtps((int(round(dx)), int(round(dy)), int(round(dz))), rt, tr, cam.h, ofx << 16, ofy << 16, dqa, dqb)
                proj.append((r["sx"], r["sy"], r["sz"], r["ir0"]))
            else:
                # Modern path: floating point, sub-pixel screen positions.
                vx = m[0][0] * dx + m[0][1] * dy + m[0][2] * dz
                vy = m[1][0] * dx + m[1][1] * dy + m[1][2] * dz
                vz = m[2][0] * dx + m[2][1] * dy + m[2][2] * dz
                if vz <= 0:
                    proj.append((0.0, 0.0, 0.0, 0))
                    continue
                n = cam.h / vz                       # perspective divide
                ir0 = 0
                if s.fog:
                    ir0 = max(0, min(0x1000, int((dqb + dqa * n * 65536) / 4096)))
                proj.append((ofx + vx * n, ofy + vy * n, vz, ir0))

        # ---- Per-face stage (CPU code + GTE NCLIP/AVSZ) ----
        for f in mesh.faces:
            stats["faces"] += 1
            pts = [proj[i] for i in f.idx]
            # Near-plane rejection. The PS1 has no hardware clipping, so many
            # games simply threw away any polygon touching the camera. That is
            # why walls right in front of you sometimes vanish.
            if any(p[2] < s.near for p in pts):
                stats["dropped_near"] += 1
                continue
            # Back-face culling with NCLIP: the sign of the screen-space area
            # tells us whether we are looking at the front or the back.
            if s.cull_backfaces and not f.double_sided:
                # front faces (CCW as seen) have a negative NCLIP in Y-down screen space
                if fx.nclip(pts[0][:2], pts[1][:2], pts[2][:2]) >= 0:
                    stats["culled_back"] += 1
                    continue
            # One depth per polygon: the average of its corners (AVSZ3/AVSZ4).
            szs = [int(p[2]) for p in pts]
            otz = fx.avsz3(*szs, zsf3) if len(szs) == 3 else fx.avsz4(*szs, zsf4)
            ot.add(otz + f.ot_bias, (f, pts))

    # ---- Drawing stage (DMA walks the ordering table into the GPU) ----
    order = ot if s.sort == "ot" else (prim for b in ot.buckets for prim in b)
    for f, pts in order:
        n = len(pts)
        cols = f.colors if len(f.colors) == n else f.colors * n
        sv = []
        for k, (sx, sy, sz, ir0) in enumerate(pts):
            r, g, b = cols[k]
            if s.fog:
                # Fog is applied to vertex COLOURS, before rasterising, which is
                # why it looks uneven across large polygons.
                r, g, b = fx.depth_cue((r, g, b), s.fog[0], ir0)
            u, v = f.uvs[k] if f.uvs else (0, 0)
            sv.append(ScreenVertex(sx, sy, r, g, b, u, v, 1.0 / max(1.0, sz)))
        # A quad is drawn as two triangles. Each is interpolated on its own,
        # hence the visible "kink" along the diagonal of a warped textured quad.
        tris = [(0, 1, 2)] if n == 3 else [(0, 1, 2), (0, 2, 3)]
        gouraud = len(f.colors) > 1 or bool(s.fog)
        for a, b_, c in tris:
            stats["pixels"] += draw_triangle(
                fb, sv[a], sv[b_], sv[c], f.texture,
                affine=s.affine, dither=s.dither, gouraud=gouraud, semi=f.semi, size_limit=s.psx,
            )
            stats["drawn_tris"] += 1
    return stats
