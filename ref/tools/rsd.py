"""RSD models: read Sony's text 3D format and link it into a TMD (see ref/formats/rsd.md).

WHAT AN RSD IS
==============
RSD is the *source* form of a PlayStation model, the text that Sony's 3D tools
wrote and that the RSDLINK utility compiled into a TMD. It is four text files:

    NAME.RSD   @RSD940102   names the other three, and the TIM textures
    NAME.PLY   @PLY940102   vertices and normals (floats), polygons (indices)
    NAME.MAT   @MAT940801   per-polygon material: lit or not, shading, colour/texture
    NAME.GRP   @GRP940102   named groups of polygons (an editor aid, not linked)

Linking turns floats into the console's integers: vertices are scaled by a
power of two and rounded to int16, normals become 1.3.12 (x 4096). Material
U,V are relative to the top-left of the texture IMAGE, so linking adds the
image's position inside its texture page, read from the TIM, and fills in the
TPAGE and CLUT position. That is why a TMD only works with its textures loaded
exactly where their TIMs say.

This linker was written from Sony's Net Yaroze "File Formats" manual, with
rounding details from psxsdk's byte-exact rsdlink (see ref/sources.md). It
reproduces Sony's RSDLINK output byte for byte on the RSD/TMD pairs in the Net
Yaroze samples (ref/tools/validate.py).

CLI:
    python -m ref.tools.rsd info  MODEL.RSD
    python -m ref.tools.rsd tmd   MODEL.RSD [MORE.RSD ...] -o OUT.TMD [-s SCALE]
    python -m ref.tools.rsd obj   MODEL.RSD -o OUT.OBJ
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass, field
from typing import Optional

from . import tim as timfmt
from . import tmd as tmdfmt

# PLY polygon kinds (the PLY polygon flag)
KIND_TRI, KIND_QUAD, KIND_LINE, KIND_SPRITE = 0, 1, 2, 3


@dataclass
class RsdPolygon:
    kind: int                                  # 0 tri, 1 quad, 2 line, 3 sprite
    vertices: list[int]                        # 4 numbers (sprite: vertex, width, height, 0)
    normals: list[int]                         # 4 numbers
    flag: int = 0                              # MAT flag: bit0 unlit, bit1 double-sided, bit2 semi, bits3-5 rate
    gouraud: bool = False                      # MAT shading "G"
    mtype: str = "C"                           # MAT type: C G T D H
    texture: int = 0                           # TEX[n] for T/D/H
    uvs: list[tuple[int, int]] = field(default_factory=list)
    colors: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class RsdModel:
    name: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    polygons: list[RsdPolygon] = field(default_factory=list)
    textures: list[Optional[timfmt.TimImage]] = field(default_factory=list)
    groups: dict[str, list[int]] = field(default_factory=dict)


# ---------------------------------------------------------------- reading text

def _lines(path: str) -> list[str]:
    """Meaningful lines: '#' starts a comment, blank lines are skipped, and a DOS
    end-of-file mark (^Z) ends the file."""
    with open(path, "rb") as f:
        text = f.read().split(b"\x1a", 1)[0].decode("latin-1")
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _find(directory: str, name: str) -> str:
    """Find a file regardless of case: RSD files were written on DOS."""
    want = name.lower()
    for entry in os.listdir(directory):
        if entry.lower() == want:
            return os.path.join(directory, entry)
    raise FileNotFoundError(os.path.join(directory, name))


def _numbers(spec: str) -> list[int]:
    """Expand a MAT/GRP polygon list: '5', '0-3' or '2,4,6'."""
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out


def read_rsd(path: str) -> RsdModel:
    """Read an RSD and the PLY, MAT, GRP and TIM files it names."""
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.exists(path):              # DOS names: "car01.rsd" finds CAR01.RSD
        path = _find(directory, os.path.basename(path))
    model = RsdModel(os.path.splitext(os.path.basename(path))[0])
    keys: dict[str, str] = {}
    for line in _lines(path)[1:]:            # line 0 is the @RSDnnnnnn ID
        if "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip().upper()] = v.strip()
    _read_ply(model, _find(directory, keys["PLY"]))
    if "MAT" in keys:
        _read_mat(model, _find(directory, keys["MAT"]))
    if "GRP" in keys:
        try:
            _read_grp(model, _find(directory, keys["GRP"]))
        except (FileNotFoundError, ValueError, IndexError):
            pass                              # groups are optional and not linked
    for i in range(int(keys.get("NTEX", "0"))):
        name = keys.get(f"TEX[{i}]")
        tex = None
        if name:
            for d in (directory, os.path.join(directory, "..", "TIM")):   # RSDLINK also looked in ../TIM
                try:
                    with open(_find(d, os.path.basename(name.replace("\\", "/"))), "rb") as f:
                        tex = timfmt.read_tim(f.read())
                    break
                except (FileNotFoundError, NotADirectoryError):
                    continue
        model.textures.append(tex)
    return model


def _read_ply(model: RsdModel, path: str) -> None:
    lines = _lines(path)
    nv, nn, npoly = (int(x) for x in lines[1].split()[:3])
    rows = lines[2:]
    model.vertices = [tuple(float(x) for x in r.split()[:3]) for r in rows[:nv]]
    model.normals = [tuple(float(x) for x in r.split()[:3]) for r in rows[nv:nv + nn]]
    for r in rows[nv + nn:nv + nn + npoly]:
        parts = r.split()
        flag = int(parts[0], 16)               # hex, without 0x
        nums = [int(x) for x in parts[1:9]]
        model.polygons.append(RsdPolygon(kind=flag & 3, vertices=nums[:4], normals=nums[4:8]))


def _read_mat(model: RsdModel, path: str) -> None:
    lines = _lines(path)
    count = int(lines[1].split()[0])
    for line in lines[2:2 + count]:            # RSDLINK ignored materials past the count
        parts = line.split()
        polys, flag, shading, mtype = _numbers(parts[0]), int(parts[1], 16), parts[2].upper(), parts[3].upper()
        vals = [int(x) for x in parts[4:]]
        for pi in polys:
            if pi >= len(model.polygons):
                continue
            p = model.polygons[pi]
            p.flag, p.gouraud, p.mtype = flag, shading == "G", mtype
            if mtype == "C":
                p.colors = [tuple(vals[0:3])]
            elif mtype == "G":
                p.colors = [tuple(vals[i:i + 3]) for i in range(0, 12, 3)]
            elif mtype in "TDH":
                p.texture = vals[0]
                p.uvs = [(vals[1 + 2 * i], vals[2 + 2 * i]) for i in range(4)]
                if mtype == "D":
                    p.colors = [tuple(vals[9:12])]
                elif mtype == "H":
                    p.colors = [tuple(vals[i:i + 3]) for i in range(9, 21, 3)]


def _read_grp(model: RsdModel, path: str) -> None:
    lines = _lines(path)
    i, groups = 2, int(lines[1].split()[0])
    for _ in range(groups):
        name, nlines = lines[i].split()[0], int(lines[i].split()[1])
        polys: list[int] = []
        for spec in lines[i + 1:i + 1 + nlines]:
            for tok in spec.split():
                polys += _numbers(tok)
        model.groups[name] = polys
        i += 1 + nlines


# ---------------------------------------------------------------- linking

def _round(x: float) -> int:
    """Round half away from zero, as C's rounding did (Python's round() rounds
    half to even, which would change some vertices by one unit)."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def link(model: RsdModel, scale: float = 1.0, translate: tuple[float, float, float] = (0, 0, 0)) -> tmdfmt.TmdObject:
    """Link one RSD model into a TMD object, as RSDLINK did.

    ``scale`` is rounded to the nearest power of two and recorded in the
    object's ``scale`` field as that exponent.
    """
    exp = _round(math.log2(scale)) if scale > 0 else 0
    factor = 2.0 ** exp
    verts = []
    for v in model.vertices:
        c = tuple(_round(v[k] * factor + translate[k]) for k in range(3))
        if any(not -32768 <= x <= 32767 for x in c):
            raise ValueError(f"vertex {v} is outside 16 bits at scale {factor}")
        verts.append(c)
    norms = [tuple(_round(n[k] * 4096) for k in range(3)) for n in model.normals]
    prims = [_primitive(model, p, i) for i, p in enumerate(model.polygons)]
    return tmdfmt.TmdObject(verts, norms, prims, scale=exp)


def _texture(model: RsdModel, p: RsdPolygon, i: int) -> timfmt.TimImage:
    if p.texture >= len(model.textures) or model.textures[p.texture] is None:
        raise ValueError(f"polygon {i}: texture {p.texture} is missing")
    return model.textures[p.texture]  # type: ignore[return-value]


def _tsb(t: timfmt.TimImage, p: RsdPolygon) -> int:
    page = timfmt.tim_tpage(t)
    if p.flag & 4:                              # semi-transparent: blend rate in bits 5-6
        page |= ((p.flag >> 3) & 3) << 5
    return page


def _primitive(model: RsdModel, p: RsdPolygon, i: int) -> tmdfmt.Primitive:
    semi = bool(p.flag & 4)
    if p.kind == KIND_LINE:
        gour = p.mtype == "G"
        cols = p.colors[:2] if gour else p.colors[:1]
        return tmdfmt.Primitive(tmdfmt.make_line_mode(gour, semi), tmdfmt.LGT, p.vertices[:2], colors=cols)
    if p.kind == KIND_SPRITE:
        t = _texture(model, p, i)
        u0, v0 = timfmt.tim_uv_origin(t)
        w, h = p.vertices[1], p.vertices[2]
        return tmdfmt.Primitive(tmdfmt.make_sprite_mode(w, h, semi), tmdfmt.LGT, [p.vertices[0]],
                                uvs=[((u0 + p.uvs[0][0]) & 0xFF, (v0 + p.uvs[0][1]) & 0xFF)],
                                cba=timfmt.tim_cba(t), tsb=_tsb(t, p), size=(w, h))

    n = 4 if p.kind == KIND_QUAD else 3
    lit = not p.flag & 1
    textured = p.mtype in "TDH"
    flag = (0 if lit else tmdfmt.LGT) | (tmdfmt.FCE if p.flag & 2 else 0)
    prim = tmdfmt.Primitive(0, 0, p.vertices[:n])
    if lit:
        # Flat shading uses the first vertex's normal for the whole polygon.
        prim.normals = p.normals[:n] if p.gouraud else [p.normals[0]] * n
    if textured:
        t = _texture(model, p, i)
        u0, v0 = timfmt.tim_uv_origin(t)
        prim.uvs = [((u0 + u) & 0xFF, (v0 + v) & 0xFF) for u, v in p.uvs[:n]]
        prim.cba, prim.tsb = timfmt.tim_cba(t), _tsb(t, p)
    # Colours: a lit textured polygon takes its colour from the texture and the
    # light, so it stores none; an unlit textured one with no colour given is
    # drawn at 128, the texture's own brightness.
    if p.mtype == "C":
        prim.colors = p.colors[:1]
    elif p.mtype in "GH":
        prim.colors = p.colors[:n]
    elif p.mtype == "D":
        prim.colors = p.colors[:1]
    elif not lit:
        prim.colors = [(128, 128, 128)]
    if lit and textured:
        prim.colors = []
    gradation = len(prim.colors) > 1
    gouraud = (lit and p.gouraud) or (not lit and gradation)
    if lit and gradation:
        flag |= tmdfmt.GRD
    prim.mode = tmdfmt.make_mode(quad=n == 4, textured=textured, gouraud=gouraud, semi=semi, tge=not lit)
    prim.flag = flag
    return prim


def rsd_to_tmd(paths: list[str], scale: float = 1.0) -> bytes:
    """Link one or more RSD models into a TMD (one object each), like `rsdlink -o`."""
    return tmdfmt.write_tmd([link(read_rsd(p), scale) for p in paths])


def describe(m: RsdModel) -> str:
    kinds = {KIND_TRI: "triangles", KIND_QUAD: "quads", KIND_LINE: "lines", KIND_SPRITE: "sprites"}
    counts = {name: sum(1 for p in m.polygons if p.kind == k) for k, name in kinds.items()}
    mats = {t: sum(1 for p in m.polygons if p.mtype == t) for t in "CGTDH"}
    xs = [v for vert in m.vertices for v in vert] or [0]
    return (f"{m.name}: {len(m.vertices)} vertices, {len(m.normals)} normals, {len(m.polygons)} polygons "
            f"{ {k: v for k, v in counts.items() if v} }, materials { {k: v for k, v in mats.items() if v} }, "
            f"{len(m.textures)} texture(s), {len(m.groups)} group(s), coordinate range {min(xs):g}..{max(xs):g}")


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ref.tools.rsd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file")
    p = sub.add_parser("tmd"); p.add_argument("files", nargs="+"); p.add_argument("-o", "--out", required=True)
    p.add_argument("-s", "--scale", type=float, default=1.0, help="scale, rounded to a power of two (RSDLINK -s)")
    p = sub.add_parser("obj"); p.add_argument("file"); p.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "info":
        print(describe(read_rsd(a.file)))
    elif a.cmd == "tmd":
        data = rsd_to_tmd(a.files, a.scale)
        with open(a.out, "wb") as f:
            f.write(data)
        print(f"wrote {a.out}: {len(a.files)} object(s), {len(data)} bytes")
    else:
        t = tmdfmt.read_tmd(tmdfmt.write_tmd([link(read_rsd(a.file))]))
        with open(a.out, "w") as f:
            f.write(tmdfmt.to_obj(t))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
