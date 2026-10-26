"""A small PS1-rules software rasteriser (see ref/look/recreating-the-look.md).

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

World space for ``render_mesh`` is Y-up (like OBJ / Blender); the camera
converts to the PS1's Y-down screen space internally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import fixedpoint as fx

DITHER = (
    (-4, +0, -3, +1),
    (+2, -2, +3, -1),
    (-3, +1, -4, +0),
    (+3, -1, +2, -2),
)


def dither_to_15bit(r: int, g: int, b: int, x: int, y: int, dither: bool = True) -> int:
    """8-bit RGB -> 15-bit halfword the way the GPU writes it (dither, clamp, truncate)."""
    if dither:
        d = DITHER[y & 3][x & 3]
        r, g, b = r + d, g + d, b + d
    r = 0 if r < 0 else 255 if r > 255 else r
    g = 0 if g < 0 else 255 if g > 255 else g
    b = 0 if b < 0 else 255 if b > 255 else b
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def rgb15_to_rgb8(c: int) -> tuple[int, int, int]:
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)


class Texture:
    """A texture as 15-bit halfwords (already palette-resolved). Wraps on u,v."""

    def __init__(self, width: int, height: int, texels: Sequence[int]):
        if len(texels) != width * height:
            raise ValueError("texel count mismatch")
        self.width, self.height, self.texels = width, height, list(texels)

    @classmethod
    def from_tim(cls, tim, clut_index: int = 0) -> "Texture":
        from .tim import tim_halfwords
        return cls(tim.width, tim.height, tim_halfwords(tim, clut_index))

    def fetch(self, u: int, v: int) -> int:
        return self.texels[(v % self.height) * self.width + (u % self.width)]


class Framebuffer:
    def __init__(self, width: int = 320, height: int = 240, clear: tuple[int, int, int] = (0, 0, 0)):
        self.width, self.height = width, height
        c = dither_to_15bit(*clear, 0, 0, dither=False)
        self.pixels = [c] * (width * height)
        self.zbuf: Optional[list[float]] = None

    def enable_zbuffer(self) -> None:
        self.zbuf = [0.0] * (self.width * self.height)  # stores 1/z; larger = nearer

    def to_rgb8(self) -> bytes:
        out = bytearray()
        for c in self.pixels:
            out += bytes(rgb15_to_rgb8(c))
        return bytes(out)

    def save_png(self, path: str, scale: int = 1) -> None:
        from .pngio import scale_nearest, write_png
        w, h, px = scale_nearest(self.width, self.height, self.to_rgb8(), scale)
        write_png(path, w, h, px)


@dataclass
class ScreenVertex:
    x: float           # integer in PS1 mode
    y: float
    r: int = 128
    g: int = 128
    b: int = 128
    u: float = 0.0
    v: float = 0.0
    w: float = 1.0     # 1/z, used only for perspective-correct comparison and the Z-buffer


def _edge(ax, ay, bx, by, px, py):
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def _blend(mode: int, b: int, f: int) -> int:
    if mode == 0:
        return (b + f) >> 1
    if mode == 1:
        return min(255, b + f)
    if mode == 2:
        return max(0, b - f)
    return min(255, b + (f >> 2))


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
    """Rasterise one triangle. Returns the number of pixels written."""
    xs, ys = (v0.x, v1.x, v2.x), (v0.y, v1.y, v2.y)
    if size_limit and (max(xs) - min(xs) > 1023 or max(ys) - min(ys) > 511):
        return 0  # the GPU skips oversized polygons entirely
    area = _edge(v0.x, v0.y, v1.x, v1.y, v2.x, v2.y)
    if area == 0:
        return 0
    if area < 0:
        v1, v2 = v2, v1
        area = -area
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
            w0 = _edge(v1.x, v1.y, v2.x, v2.y, x, y)
            w1 = _edge(v2.x, v2.y, v0.x, v0.y, x, y)
            w2 = _edge(v0.x, v0.y, v1.x, v1.y, x, y)
            if w0 - bias0 < 0 or w1 - bias1 < 0 or w2 - bias2 < 0:
                continue
            l0, l1, l2 = w0 / area, w1 / area, w2 / area
            idx = y * W + x
            invz = l0 * v0.w + l1 * v1.w + l2 * v2.w
            if zbuf is not None:
                if invz <= zbuf[idx]:
                    continue
            if gouraud:  # epsilon keeps exact vertex colours from truncating one level down
                r = l0 * v0.r + l1 * v1.r + l2 * v2.r + 1e-6
                g = l0 * v0.g + l1 * v1.g + l2 * v2.g + 1e-6
                b = l0 * v0.b + l1 * v1.b + l2 * v2.b + 1e-6
            else:
                r, g, b = v0.r, v0.g, v0.b
            stp = True
            if texture is not None:
                if affine:
                    u = l0 * v0.u + l1 * v1.u + l2 * v2.u
                    v = l0 * v0.v + l1 * v1.v + l2 * v2.v
                else:
                    u = (l0 * v0.u * v0.w + l1 * v1.u * v1.w + l2 * v2.u * v2.w) / invz
                    v = (l0 * v0.v * v0.w + l1 * v1.v * v1.w + l2 * v2.v * v2.w) / invz
                t = texture.fetch(int(math.floor(u)), int(math.floor(v)))
                if t == 0:
                    continue  # 0x0000 = transparent texel
                stp = bool(t & 0x8000)
                tr, tg, tb = (t & 31) << 3, ((t >> 5) & 31) << 3, ((t >> 10) & 31) << 3
                if raw_texture:
                    r, g, b = tr, tg, tb
                else:
                    r, g, b = tr * r / 128, tg * g / 128, tb * b / 128
            r, g, b = int(r), int(g), int(b)
            if semi is not None and stp:
                br, bg, bb = rgb15_to_rgb8(pix[idx])
                r, g, b = _blend(semi, br, r), _blend(semi, bg, g), _blend(semi, bb, b)
            shaded = gouraud or (texture is not None and not raw_texture)
            pix[idx] = dither_to_15bit(r, g, b, x, y, dither and shaded)
            if zbuf is not None:
                zbuf[idx] = invz
            written += 1
    return written


# ---------------------------------------------------------------- ordering table

class OrderingTable:
    """Buckets of primitives drawn from the highest index (far) to 0 (near).

    Within a bucket the most recently added primitive is drawn first, matching
    libgpu's addPrim() inserting at the head of each list.
    """

    def __init__(self, length: int = 1024):
        self.buckets: list[list] = [[] for _ in range(length)]

    def add(self, otz: int, prim) -> None:
        self.buckets[max(0, min(len(self.buckets) - 1, otz))].append(prim)

    def __iter__(self):
        for bucket in reversed(self.buckets):
            yield from reversed(bucket)


# ---------------------------------------------------------------- mesh pipeline

@dataclass
class Face:
    idx: tuple[int, ...]                                   # 3 or 4 vertex indices, CCW ring seen from the front
    colors: tuple[tuple[int, int, int], ...] = ((128, 128, 128),)  # 1 (flat) or one per vertex
    uvs: Optional[tuple[tuple[int, int], ...]] = None
    texture: Optional[Texture] = None
    semi: Optional[int] = None
    double_sided: bool = False
    ot_bias: int = 0                                       # negative = drawn later (nearer)


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float]]
    faces: list[Face] = field(default_factory=list)


@dataclass
class Camera:
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
    """Transform, cull, sort and draw meshes. Returns simple stats."""
    m = cam.matrix()
    cx, cy, cz = cam.position
    ofx, ofy = fb.width // 2, fb.height // 2
    rt = [[fx.to_fx12(m[i][j]) for j in range(3)] for i in range(3)]
    dqa = dqb = 0
    if s.fog:
        dqa, dqb = fx.depth_cue_params(cam.h, int(s.fog[1]), int(s.fog[2]))
    zsf3, zsf4 = fx.zsf_for(s.ot_len, s.z_max, 3), fx.zsf_for(s.ot_len, s.z_max, 4)
    ot = OrderingTable(s.ot_len)
    stats = {"faces": 0, "culled_back": 0, "dropped_near": 0, "drawn_tris": 0, "pixels": 0}
    if s.sort == "zbuffer":
        fb.enable_zbuffer()

    for mesh in meshes:
        proj = []
        for (x, y, z) in mesh.vertices:
            dx, dy, dz = x - cx, y - cy, z - cz
            if s.psx:
                tr = (0, 0, 0)
                r = fx.rtps((int(round(dx)), int(round(dy)), int(round(dz))), rt, tr, cam.h, ofx << 16, ofy << 16, dqa, dqb)
                proj.append((r["sx"], r["sy"], r["sz"], r["ir0"]))
            else:
                vx = m[0][0] * dx + m[0][1] * dy + m[0][2] * dz
                vy = m[1][0] * dx + m[1][1] * dy + m[1][2] * dz
                vz = m[2][0] * dx + m[2][1] * dy + m[2][2] * dz
                if vz <= 0:
                    proj.append((0.0, 0.0, 0.0, 0))
                    continue
                n = cam.h / vz
                ir0 = 0
                if s.fog:
                    ir0 = max(0, min(0x1000, int((dqb + dqa * n * 65536) / 4096)))
                proj.append((ofx + vx * n, ofy + vy * n, vz, ir0))

        for f in mesh.faces:
            stats["faces"] += 1
            pts = [proj[i] for i in f.idx]
            if any(p[2] < s.near for p in pts):
                stats["dropped_near"] += 1
                continue
            if s.cull_backfaces and not f.double_sided:
                # front faces (CCW as seen) have a negative NCLIP in Y-down screen space
                if fx.nclip(pts[0][:2], pts[1][:2], pts[2][:2]) >= 0:
                    stats["culled_back"] += 1
                    continue
            szs = [int(p[2]) for p in pts]
            otz = fx.avsz3(*szs, zsf3) if len(szs) == 3 else fx.avsz4(*szs, zsf4)
            ot.add(otz + f.ot_bias, (f, pts))

    order = ot if s.sort == "ot" else (prim for b in ot.buckets for prim in b)
    for f, pts in order:
        n = len(pts)
        cols = f.colors if len(f.colors) == n else f.colors * n
        sv = []
        for k, (sx, sy, sz, ir0) in enumerate(pts):
            r, g, b = cols[k]
            if s.fog:
                r, g, b = fx.depth_cue((r, g, b), s.fog[0], ir0)
            u, v = f.uvs[k] if f.uvs else (0, 0)
            sv.append(ScreenVertex(sx, sy, r, g, b, u, v, 1.0 / max(1.0, sz)))
        tris = [(0, 1, 2)] if n == 3 else [(0, 1, 2), (0, 2, 3)]
        gouraud = len(f.colors) > 1 or bool(s.fog)
        for a, b_, c in tris:
            stats["pixels"] += draw_triangle(
                fb, sv[a], sv[b_], sv[c], f.texture,
                affine=s.affine, dither=s.dither, gouraud=gouraud, semi=f.semi, size_limit=s.psx,
            )
            stats["drawn_tris"] += 1
    return stats
