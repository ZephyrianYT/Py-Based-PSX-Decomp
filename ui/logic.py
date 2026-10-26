"""Everything the web UI does, as plain Python with no Streamlit import.

The Streamlit pages in ui/app.py only lay out widgets and call these
functions, so all the behaviour can be unit-tested (ui/tests/) and reused from
a script. Every function works on bytes in and bytes out: uploaded files
arrive as bytes, and images go back as PNG bytes.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:                       # allow `streamlit run ui/app.py` from anywhere
    sys.path.insert(0, ROOT)

from ref.tools import exe, fixedpoint as fx, raster, rsd, tim, tmd, worldgen  # noqa: E402
from ref.tools.demo import SCENE_SPECS  # noqa: E402
from ref.tools.pngio import encode_png, scale_nearest  # noqa: E402

REF_DIR = os.path.join(ROOT, "ref")


def fb_to_png(fb: raster.Framebuffer, scale: int = 2) -> bytes:
    """A 15-bit framebuffer as PNG bytes, enlarged with nearest-neighbour filtering."""
    w, h, px = scale_nearest(fb.width, fb.height, fb.to_rgb8(), scale)
    return encode_png(w, h, px)


# ---------------------------------------------------------------- library

def list_docs() -> list[dict]:
    with open(os.path.join(REF_DIR, "index.json")) as f:
        return json.load(f)["docs"]


def search_docs(query: str) -> list[dict]:
    """Docs whose title, tags or summary contain every word of the query."""
    words = [w.lower() for w in query.split()]
    out = []
    for d in list_docs():
        hay = " ".join([d["title"], d["summary"], " ".join(d["tags"]), d["path"]]).lower()
        if all(w in hay for w in words):
            out.append(d)
    return out


def read_doc(path: str) -> str:
    """Read a doc listed in the index (paths outside ref/ are refused)."""
    full = os.path.normpath(os.path.join(REF_DIR, path))
    if not full.startswith(REF_DIR + os.sep) or path not in {d["path"] for d in list_docs()}:
        raise ValueError(f"not a listed document: {path}")
    with open(full, encoding="utf-8") as f:
        return f.read()


def doc_images(path: str) -> list[tuple[str, bytes]]:
    """PNG images referenced by a doc, as (name, bytes), for docs that show pictures."""
    text = read_doc(path)
    base = os.path.dirname(os.path.join(REF_DIR, path))
    out, seen = [], set()
    for token in text.replace("(", " ").replace(")", " ").split():
        if token.endswith(".png") and token not in seen:
            seen.add(token)
            p = os.path.normpath(os.path.join(base, token.strip("`")))
            if p.startswith(REF_DIR) and os.path.isfile(p):
                with open(p, "rb") as f:
                    out.append((os.path.basename(p), f.read()))
    return out


# ---------------------------------------------------------------- look lab

@dataclass
class LookSettings:
    integer_vertices: bool = True    # GTE integer screen coordinates (jitter)
    affine: bool = True              # affine texture mapping
    dither: bool = True              # 15-bit output with the 4x4 dither
    ordering_table: bool = True      # painter's sort by one depth per polygon (False = Z-buffer)
    fog: bool = True                 # GTE depth cue (scenes that define fog)

    @classmethod
    def modern(cls) -> "LookSettings":
        return cls(False, False, False, False, True)


SCENE_NAMES = {name: spec().title for name, spec in SCENE_SPECS.items()}


def render_scene(name: str, s: LookSettings, scale: int = 2) -> tuple[bytes, dict]:
    spec = SCENE_SPECS[name]()
    fb = raster.Framebuffer(clear=spec.clear)
    stats = raster.render_mesh(fb, spec.build(), spec.camera, raster.RenderSettings(
        psx=s.integer_vertices, affine=s.affine, dither=s.dither,
        sort="ot" if s.ordering_table else "zbuffer",
        fog=spec.fog if s.fog else None, z_max=spec.z_max))
    return fb_to_png(fb, scale), stats


def render_gradient(dither: bool, scale: int = 3) -> bytes:
    """One Gouraud quad: shows 15-bit banding with and without the PS1 dither."""
    fb = raster.Framebuffer(160, 120)
    a = raster.ScreenVertex(0, 0, 20, 30, 80)
    b = raster.ScreenVertex(160, 0, 250, 140, 40)
    c = raster.ScreenVertex(160, 120, 90, 40, 20)
    d = raster.ScreenVertex(0, 120, 10, 10, 30)
    raster.draw_triangle(fb, a, b, c, dither=dither)
    raster.draw_triangle(fb, a, c, d, dither=dither)
    return fb_to_png(fb, scale)


# ---------------------------------------------------------------- GTE jitter

def jitter_series(depth: int = 2000, distance: float = 30.0, steps: int = 120, h: int = 256) -> list[dict]:
    """Screen X of a vertex sliding sideways at a fixed depth: float vs GTE integer."""
    ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
    rows = []
    for i in range(steps + 1):
        wx = distance * i / steps
        rows.append({
            "world_x": round(wx, 3),
            "float_screen_x": 160 + wx * h / depth,
            "gte_screen_x": fx.rtps((0, 0, 0), ident, (int(round(wx)), 0, depth), h)["sx"],
        })
    return rows


# ---------------------------------------------------------------- world generator

@dataclass
class WorldResult:
    png: bytes
    obj: str
    model_stats: dict
    render_stats: dict
    ascii_map: Optional[str] = None


def generate_world(kind: str, seed: int, size: int, scale: int = 2) -> WorldResult:
    if kind == "terrain":
        model = worldgen.generate_terrain(size=size, seed=seed)
    elif kind == "dungeon":
        model = worldgen.generate_dungeon(size=size, seed=seed)
    else:
        raise ValueError(kind)
    fb, rstats = worldgen.render_preview(model, kind)
    amap = worldgen.ascii_map(model.grid) if kind == "dungeon" else None  # type: ignore[attr-defined]
    return WorldResult(fb_to_png(fb, scale), model.to_obj(), model.stats(), rstats, amap)


# ---------------------------------------------------------------- file inspector

def detect_kind(name: str, data: bytes) -> str:
    """'tim', 'tmd', 'rsd', 'exe' or 'unknown', from magic bytes first and the name second."""
    if data[:4] == b"\x10\x00\x00\x00":
        return "tim"
    if data[:4] == b"\x41\x00\x00\x00":
        return "tmd"
    if exe.identify(data) != "unknown":
        return "exe"
    if data[:4] == b"@RSD" or name.lower().endswith(".rsd"):
        return "rsd"
    return "unknown"


def inspect_tim(data: bytes, clut: int = 0, scale: int = 4) -> tuple[str, Optional[bytes]]:
    t = tim.read_tim(data)
    info = tim.describe(t)
    if t.pmode == tim.PMODE_MIXED:
        return info, None
    w, h, rgba = tim.tim_to_rgba(t, min(clut, max(0, t.num_cluts - 1)))
    w2, h2, big = scale_nearest(w, h, rgba, scale, channels=4)
    return info, encode_png(w2, h2, big, channels=4)


def tmd_to_meshes(model: tmd.Tmd, light=(0.4, 0.7, -0.6)) -> tuple[list[raster.Mesh], tuple, float]:
    """Turn TMD objects into raster meshes for a quick PS1-style preview.

    TMD is Y-down with clockwise fronts; negating Y gives Y-up with
    counter-clockwise fronts, which is what raster.render_mesh expects, so the
    vertex order is kept (quads go from GPU "Z" order to a ring). Untextured
    colours are used as stored; textures are not loaded (a TMD names VRAM
    positions, not files), so textured faces are grey. A fixed light shades
    faces so the shape reads. Returns (meshes, centre, radius) in TMD units.
    """
    pts = [(x, -y, z) for o in model.objects for (x, y, z) in o.vertices] or [(0, 0, 0)]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    centre = tuple((lo[k] + hi[k]) / 2 for k in range(3))
    radius = max(1e-6, max(math.dist(p, centre) for p in pts))
    k = 1000.0 / radius                         # normalise so tiny or huge models both frame well
    ll = math.sqrt(sum(c * c for c in light))
    L = [c / ll for c in light]
    meshes = []
    for o in model.objects:
        verts = [((x - centre[0]) * k, (-y - centre[1]) * k, (z - centre[2]) * k) for x, y, z in o.vertices]
        mesh = raster.Mesh(verts)
        for p in o.primitives:
            if p.code != tmd.CODE_POLYGON:
                continue
            ring = [0, 1, 3, 2] if p.n == 4 else [0, 1, 2]
            idx = tuple(p.vertices[i] for i in ring)
            a, b, c = (verts[i] for i in idx[:3])
            u = [b[j] - a[j] for j in range(3)]
            v = [c[j] - a[j] for j in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            nl = math.sqrt(sum(x * x for x in n)) or 1.0
            shade = 0.45 + 0.55 * max(0.0, sum(n[j] * L[j] for j in range(3)) / nl)
            base = p.colors if p.colors else [(150, 150, 150)]
            cols = [base[i] if i < len(base) else base[0] for i in ring] if len(base) > 1 else [base[0]]
            cols = tuple(tuple(min(255, int(ch * shade)) for ch in c) for c in cols)
            mesh.faces.append(raster.Face(idx, colors=cols, double_sided=bool(p.flag & tmd.FCE)))
        meshes.append(mesh)
    return meshes, centre, radius


def render_tmd(data: bytes, yaw_deg: float = 30.0, pitch_deg: float = 20.0, s: Optional[LookSettings] = None,
               scale: int = 2) -> tuple[bytes, dict]:
    s = s or LookSettings()
    model = tmd.read_tmd(data)
    meshes, _, _ = tmd_to_meshes(model)
    d, yaw, pitch = 2600.0, math.radians(yaw_deg), math.radians(pitch_deg)
    pos = (-math.sin(yaw) * d * math.cos(pitch), d * math.sin(pitch), -math.cos(yaw) * d * math.cos(pitch))
    cam = raster.Camera(position=pos, yaw=yaw, pitch=pitch, h=200)
    fb = raster.Framebuffer(clear=(40, 44, 56))
    stats = raster.render_mesh(fb, meshes, cam, raster.RenderSettings(
        psx=s.integer_vertices, affine=s.affine, dither=s.dither,
        sort="ot" if s.ordering_table else "zbuffer", z_max=8192))
    return fb_to_png(fb, scale), stats


def inspect_tmd(data: bytes) -> tuple[str, str]:
    """(description, OBJ text)."""
    model = tmd.read_tmd(data)
    return tmd.describe(model), tmd.to_obj(model)


def link_rsd(files: dict[str, bytes], scale: float = 1.0) -> tuple[str, bytes]:
    """Link an uploaded RSD set (the .RSD plus its PLY/MAT/GRP and TIM files).

    Returns (description, TMD bytes). Files are written to a private temporary
    folder, because RSD files name each other by file name.
    """
    names = [n for n in files if n.lower().endswith(".rsd")]
    if len(names) != 1:
        raise ValueError("upload exactly one .RSD file together with its .PLY, .MAT, .GRP and texture .TIM files")
    with tempfile.TemporaryDirectory() as d:
        for name, data in files.items():
            with open(os.path.join(d, os.path.basename(name)), "wb") as f:
                f.write(data)
        model = rsd.read_rsd(os.path.join(d, os.path.basename(names[0])))
        return rsd.describe(model), tmd.write_tmd([rsd.link(model, scale)])


def inspect_exe(data: bytes) -> tuple[str, dict]:
    h = exe.read_executable(data)
    return exe.describe(h), h


# ---------------------------------------------------------------- samples

def sample_tim() -> bytes:
    """A generated 32x32 4-bit TIM with two palettes (a palette swap demo)."""
    pix = [((x // 8 + y // 8) & 1) * 1 + (2 if (x % 8 == 0 or y % 8 == 0) else 0) for y in range(32) for x in range(32)]
    warm = [tim.rgb8_to_15(*c) for c in [(200, 160, 90), (120, 70, 40), (40, 20, 10), (250, 230, 200)]] + [0] * 12
    cool = [tim.rgb8_to_15(*c) for c in [(90, 160, 200), (40, 70, 120), (10, 20, 40), (200, 230, 250)]] + [0] * 12
    return tim.write_tim(0, 32, 32, pix, [warm, cool])


def sample_tmd() -> bytes:
    """A generated low-poly house: lit flat walls, a Gouraud roof, Sony winding."""
    # TMD space: Y down. Corners of a 200-wide box from y=0 (ground) up to y=-150.
    v = [(-100, 0, -100), (100, 0, -100), (100, 0, 100), (-100, 0, 100),
         (-100, -150, -100), (100, -150, -100), (100, -150, 100), (-100, -150, 100),
         (0, -250, -100), (0, -250, 100)]
    norms = [(0, 0, -4096), (4096, 0, 0), (0, 0, 4096), (-4096, 0, 0), (2896, -2896, 0), (-2896, -2896, 0)]
    wall, roof = (200, 180, 150), (170, 60, 50)
    prims = []

    def quad(a, b, c, d, n, col):
        # a,b,c,d in "Z" order: (a,b,c) must run clockwise seen from outside (Y-down screen)
        prims.append(tmd.Primitive(tmd.make_mode(quad=True), 0, [a, b, c, d], normals=[n] * 4, colors=[col]))

    def tri(a, b, c, n, col):
        prims.append(tmd.Primitive(tmd.make_mode(), 0, [a, b, c], normals=[n] * 3, colors=[col]))
    quad(4, 5, 0, 1, 0, wall)       # front (-Z)
    quad(5, 6, 1, 2, 1, wall)       # right (+X)
    quad(6, 7, 2, 3, 2, wall)       # back (+Z)
    quad(7, 4, 3, 0, 3, wall)       # left (-X)
    quad(8, 9, 5, 6, 4, roof)       # roof right
    quad(9, 8, 7, 4, 5, roof)       # roof left
    tri(8, 5, 4, 0, wall)           # gable front
    tri(9, 7, 6, 2, wall)           # gable back
    return tmd.write_tmd([tmd.TmdObject(v, norms, prims)])


# ---------------------------------------------------------------- self-test

def run_self_tests() -> tuple[bool, str]:
    suite = unittest.defaultTestLoader.discover(os.path.join(REF_DIR, "tests"), top_level_dir=ROOT)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result.wasSuccessful(), stream.getvalue()
