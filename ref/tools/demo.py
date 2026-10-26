"""Render side-by-side comparison images of PS1 artifacts.

    python -m ref.tools.demo --out ref_out

Each PNG shows the PS1 behaviour on the LEFT (or top) and a modern renderer on the
RIGHT (or bottom). See ref/look/visual-signature.md for the explanations.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Callable, Optional

from .pngio import scale_nearest, write_png
from .raster import (Camera, Face, Framebuffer, Mesh, RenderSettings, ScreenVertex, Texture,
                     draw_triangle, render_mesh)
from .tim import read_tim, write_tim, rgb8_to_15


# ---------------------------------------------------------------- helpers

def hstack(*fbs: Framebuffer, gap: int = 2) -> tuple[int, int, bytes]:
    h = max(f.height for f in fbs)
    w = sum(f.width for f in fbs) + gap * (len(fbs) - 1)
    rows = [bytearray() for _ in range(h)]
    datas = [f.to_rgb8() for f in fbs]
    for i, (f, d) in enumerate(zip(fbs, datas)):
        for y in range(h):
            rows[y] += d[y * f.width * 3:(y + 1) * f.width * 3] if y < f.height else b"\x00" * f.width * 3
            if i < len(fbs) - 1:
                rows[y] += b"\xff\xff\xff" * gap
    return w, h, b"".join(rows)


def vstack(images: list[tuple[int, int, bytes]], gap: int = 2) -> tuple[int, int, bytes]:
    w = max(i[0] for i in images)
    out = bytearray()
    for k, (iw, ih, px) in enumerate(images):
        for y in range(ih):
            out += px[y * iw * 3:(y + 1) * iw * 3] + b"\x00" * (w - iw) * 3
        if k < len(images) - 1:
            out += b"\xff\xff\xff" * w * gap
    return w, len(out) // (w * 3), bytes(out)


def save(path: str, img: tuple[int, int, bytes], scale: int) -> None:
    w, h, px = scale_nearest(*img, scale)
    write_png(path, w, h, px)
    print(f"wrote {path} ({w}x{h})")


def checker_texture() -> Texture:
    # Built as a real 4-bit TIM and decoded again, so the demo also exercises
    # the same texture path a game asset would take.
    """64x64 4-bit TIM with a 2-colour checker + border lines, round-tripped through the TIM codec."""
    pix = []
    for y in range(64):
        for x in range(64):
            line = x % 16 == 0 or y % 16 == 0
            pix.append(2 if line else ((x // 16 + y // 16) & 1))
    clut = [rgb8_to_15(200, 180, 140), rgb8_to_15(120, 90, 60), rgb8_to_15(40, 30, 20)] + [0] * 13
    return Texture.from_tim(read_tim(write_tim(0, 64, 64, pix, [clut])))


def box(x0, y0, z0, x1, y1, z1, color=(128, 128, 128), uv=False, tex=None) -> list[tuple[list, Face]]:
    """Axis-aligned box as (vertices, faces) with outward CCW quads."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3), (1, 2, 6, 5), (3, 7, 6, 2), (0, 1, 5, 4)]
    shade = [0.8, 0.8, 0.6, 1.0, 1.15, 0.45]
    faces = []
    for q, s in zip(quads, shade):
        c = tuple(min(255, int(ch * s)) for ch in color)
        faces.append(Face(q, colors=(c,), uvs=((0, 0), (63, 0), (63, 63), (0, 63)) if uv else None, texture=tex))
    return v, faces


def mesh_from(parts) -> Mesh:
    mesh = Mesh([])
    for verts, faces in parts:
        base = len(mesh.vertices)
        mesh.vertices += verts
        for f in faces:
            f.idx = tuple(i + base for i in f.idx)
            mesh.faces.append(f)
    return mesh


# ---------------------------------------------------------------- scene specs
#
# Each 3D demo scene is described once, as a SceneSpec, so that the PNG demos
# below and the web UI (ui/logic.py) render exactly the same scenes. build()
# returns fresh meshes each call (mesh_from() rebases indices in place).

@dataclass
class SceneSpec:
    title: str
    build: Callable[[], list]                     # -> list[Mesh]
    camera: Camera
    clear: tuple = (0, 0, 0)
    fog: Optional[tuple] = None                   # (colour, z start, z full) used when fog is on
    z_max: int = 8192


def affine_spec() -> SceneSpec:
    """A checkerboard floor of large textured quads, seen at a low angle."""
    tex = checker_texture()

    def build():
        S = 1024
        verts, faces = [], []
        for gz in range(4):
            for gx in range(-2, 2):
                b = len(verts)
                verts += [(gx * S, 0, gz * S), (gx * S, 0, (gz + 1) * S), ((gx + 1) * S, 0, (gz + 1) * S), ((gx + 1) * S, 0, gz * S)]
                faces.append(Face((b, b + 1, b + 2, b + 3), colors=((128, 128, 128),), uvs=((0, 0), (0, 63), (63, 63), (63, 0)), texture=tex))
        return [Mesh(verts, faces)]
    return SceneSpec("Checker floor (affine texturing)", build, Camera(position=(0, 320, -350), pitch=math.radians(14), h=180))


def sorting_spec() -> SceneSpec:
    """A huge floor quad and a cube standing on its far half."""
    def build():
        floor_v = [(-2500, 0, 1200), (-2500, 0, 9000), (2500, 0, 9000), (2500, 0, 1200)]
        floor = ([tuple(map(float, v)) for v in floor_v], [Face((0, 1, 2, 3), colors=((60, 110, 60), (60, 110, 60), (30, 60, 30), (30, 60, 30)))])
        cube = box(-300, 0, 5200, 300, 600, 5800, color=(220, 80, 60))
        return [mesh_from([floor, cube])]
    return SceneSpec("Floor and cube (depth sorting)", build, Camera(position=(0, 700, -200), pitch=math.radians(6), h=200),
                     clear=(100, 140, 200), z_max=12000)


def fog_spec() -> SceneSpec:
    """A corridor of pillars receding into the distance."""
    fogc = (150, 150, 160)
    return SceneSpec("Pillar corridor (depth-cue fog)", lambda: [_fog_parts()],
                     Camera(position=(0, 450, -300), pitch=math.radians(4), h=180),
                     clear=fogc, fog=(fogc, 1200, 7000), z_max=12000)


SCENE_SPECS = {"affine": affine_spec, "sorting": sorting_spec, "fog": fog_spec}


# ---------------------------------------------------------------- scenes

def scene_affine(out: str, scale: int) -> None:
    """A checkerboard floor of large quads, seen at a low angle.

    Left (PS1): straight checker lines bend and kink along each quad's
    diagonal, because u,v are interpolated in screen space. Right: the same
    floor with perspective-correct texturing stays straight.
    """
    spec = affine_spec()
    left, right = Framebuffer(), Framebuffer()
    render_mesh(left, spec.build(), spec.camera, RenderSettings(psx=True, affine=True))
    render_mesh(right, spec.build(), spec.camera, RenderSettings(psx=False, affine=False, dither=False))
    save(os.path.join(out, "affine_vs_perspective.png"), hstack(left, right), scale)


def scene_dither(out: str, scale: int) -> None:
    """One Gouraud-shaded quad. Left: PS1 dither (fine grain, smooth-looking).
    Right: plain 15-bit truncation (visible bands of 32 levels)."""
    fbs = []
    for dither in (True, False):
        fb = Framebuffer(160, 120)
        a = ScreenVertex(0, 0, 20, 30, 80)
        b = ScreenVertex(160, 0, 250, 140, 40)
        c = ScreenVertex(160, 120, 90, 40, 20)
        d = ScreenVertex(0, 120, 10, 10, 30)
        draw_triangle(fb, a, b, c, dither=dither)
        draw_triangle(fb, a, c, d, dither=dither)
        fbs.append(fb)
    save(os.path.join(out, "dither_vs_none.png"), hstack(*fbs), scale * 2)


def scene_jitter(out: str, scale: int) -> None:
    """Chart of one vertex's screen X while it slides 30 world units at depth 2000.

    Orange = float projection (smooth). Cyan = GTE integer projection (staircase).
    Grey lines mark whole screen pixels; every step of the cyan line is a visible jump.
    """
    from . import fixedpoint as fx
    from .raster import dither_to_15bit
    W, H, lo, hi = 300, 100, 159.5, 164.5
    fb = Framebuffer(W, H, clear=(24, 24, 32))
    ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]

    def plot(x: int, sx: float, rgb) -> None:
        y = int(round((hi - sx) / (hi - lo) * (H - 1)))
        if 0 <= y < H:
            fb.pixels[y * W + x] = dither_to_15bit(*rgb, x, y, dither=False)

    for px in range(int(lo) + 1, int(hi) + 1):
        for x in range(W):
            plot(x, px, (70, 70, 80))
    for t in range(W):
        wx = t * 0.1
        plot(t, 160 + wx * 256 / 2000, (255, 160, 40))
        plot(t, fx.rtps((0, 0, 0), ident, (int(round(wx)), 0, 2000))["sx"], (60, 220, 255))
    w, h, px = fb.width, fb.height, fb.to_rgb8()
    save(os.path.join(out, "jitter_chart.png"), (w, h, px), scale * 2)


def scene_sorting(out: str, scale: int) -> None:
    """A huge floor quad and a cube standing on its far half.

    The floor's single average depth is NEARER than the cube's, so the ordering
    table draws the floor last and it covers the cube's lower half (left).
    A Z-buffer resolves depth per pixel and gets it right (right).
    """
    spec = sorting_spec()
    left, right = Framebuffer(clear=spec.clear), Framebuffer(clear=spec.clear)
    render_mesh(left, spec.build(), spec.camera, RenderSettings(sort="ot", z_max=spec.z_max))
    render_mesh(right, spec.build(), spec.camera, RenderSettings(sort="zbuffer", z_max=spec.z_max))
    save(os.path.join(out, "sorting_ot_vs_zbuffer.png"), hstack(left, right), scale)


def _fog_parts():
    parts = []
    for i in range(10):
        z = 600 + i * 900
        parts.append(box(-900, 0, z, -700, 900, z + 200, color=(200, 190, 170)))
        parts.append(box(700, 0, z, 900, 900, z + 200, color=(200, 190, 170)))
    floor_v, floor_f = [], []
    for i in range(12):
        b = len(floor_v)
        z0, z1 = 400 + i * 800, 400 + (i + 1) * 800
        floor_v += [(-1200.0, 0.0, float(z0)), (-1200.0, 0.0, float(z1)), (1200.0, 0.0, float(z1)), (1200.0, 0.0, float(z0))]
        floor_f.append(Face((b, b + 1, b + 2, b + 3), colors=((110, 100, 90),)))
    parts.append((floor_v, floor_f))
    return mesh_from(parts)


def scene_fog(out: str, scale: int) -> None:
    """A corridor of pillars. Left: GTE-style depth cue blends vertex colours
    toward the fog colour with distance. Right: no fog, so the far end pops."""
    spec = fog_spec()
    left, right = Framebuffer(clear=spec.clear), Framebuffer(clear=spec.clear)
    render_mesh(left, spec.build(), spec.camera, RenderSettings(fog=spec.fog, z_max=spec.z_max))
    render_mesh(right, spec.build(), spec.camera, RenderSettings(z_max=spec.z_max))
    save(os.path.join(out, "fog_depthcue.png"), hstack(left, right), scale)


SCENES = {
    "affine": scene_affine,
    "dither": scene_dither,
    "jitter": scene_jitter,
    "sorting": scene_sorting,
    "fog": scene_fog,
}


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ref.tools.demo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="ref_out")
    ap.add_argument("--scale", type=int, default=2, help="integer nearest upscale factor")
    ap.add_argument("--only", choices=sorted(SCENES), action="append")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for name in a.only or SCENES:
        SCENES[name](a.out, a.scale)


if __name__ == "__main__":
    main()
