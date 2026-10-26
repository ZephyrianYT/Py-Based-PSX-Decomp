"""TMD model format: read, write, export to OBJ (see ref/formats/tmd.md).

Polygon primitives are decoded with the generic layout rule from tmd.md. Any
primitive whose header ``ilen`` disagrees with that rule (or that is a line or
sprite) is skipped via ``ilen`` and recorded in ``TmdObject.skipped`` instead of
being misread.

Quad vertex order in TMD follows the GPU: (0,1,2,3) = top-left, top-right,
bottom-left, bottom-right ("Z" order). OBJ export converts it to a ring (0,1,3,2).

CLI:
    python -m ref.tools.tmd info MODEL.tmd
    python -m ref.tools.tmd obj  MODEL.tmd --out MODEL.obj
"""

from __future__ import annotations

import argparse
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

TMD_ID = 0x41

# mode bits (polygon)
TGE, ABE, TME, QUAD, IIP = 0x01, 0x02, 0x04, 0x08, 0x10
# flag bits
LGT, FCE, GRD = 0x01, 0x02, 0x04

_OLEN = {  # (quad, textured, gouraud-output) -> GPU packet words
    (0, 0, 0): 4, (0, 1, 0): 7, (0, 0, 1): 6, (0, 1, 1): 9,
    (1, 0, 0): 5, (1, 1, 0): 9, (1, 0, 1): 8, (1, 1, 1): 12,
}


@dataclass
class Primitive:
    mode: int
    flag: int
    vertices: list[int]                       # indices, GPU order
    normals: list[int] = field(default_factory=list)   # per vertex (flat repeats normal0); empty if unlit
    colors: list[tuple[int, int, int]] = field(default_factory=list)  # 1 or n entries
    uvs: list[tuple[int, int]] = field(default_factory=list)
    cba: Optional[int] = None                 # CLUT attribute
    tsb: Optional[int] = None                 # texpage attribute

    @property
    def n(self) -> int:
        return 4 if self.mode & QUAD else 3

    @property
    def name(self) -> str:
        s = ("G" if self.mode & IIP else "F") + ("T" if self.mode & TME else "") + str(self.n)
        return s + ("" if not self.flag & LGT else " (unlit)")


@dataclass
class TmdObject:
    vertices: list[tuple[int, int, int]]
    normals: list[tuple[int, int, int]]
    primitives: list[Primitive]
    scale: int = 0
    skipped: list[tuple[int, int, int]] = field(default_factory=list)  # (mode, flag, ilen)


@dataclass
class Tmd:
    flags: int
    objects: list[TmdObject]


def layout(mode: int, flag: int) -> tuple[int, int, int, bool]:
    """Return (uv_words, color_words, index_halfwords, lit) for a polygon primitive."""
    n = 4 if mode & QUAD else 3
    tme, iip = bool(mode & TME), bool(mode & IIP)
    lit = not (flag & LGT)
    uv_words = n if tme else 0
    if lit:
        color_words = 0 if tme else (n if flag & GRD else 1)
        idx = 2 * n if iip else 1 + n
    else:
        color_words = n if (iip or flag & GRD) else 1
        idx = n
    return uv_words, color_words, idx, lit


def expected_ilen(mode: int, flag: int) -> int:
    uv, col, idx, _ = layout(mode, flag)
    return uv + col + (idx + 1) // 2


def expected_olen(mode: int, flag: int) -> int:
    gour = bool(mode & IIP) or bool(flag & GRD)
    return _OLEN[(int(bool(mode & QUAD)), int(bool(mode & TME)), int(gour))]


# ---------------------------------------------------------------- reading

def _decode_prim(mode: int, flag: int, words: bytes) -> Primitive:
    n = 4 if mode & QUAD else 3
    uv_words, color_words, idx_count, lit = layout(mode, flag)
    p = Primitive(mode, flag, [])
    off = 0
    for i in range(uv_words):
        u, v, attr = struct.unpack_from("<BBH", words, off)
        p.uvs.append((u, v))
        if i == 0:
            p.cba = attr
        elif i == 1:
            p.tsb = attr
        off += 4
    for _ in range(color_words):
        r, g, b, _pad = struct.unpack_from("<BBBB", words, off)
        p.colors.append((r, g, b))
        off += 4
    idx = list(struct.unpack_from(f"<{idx_count}H", words, off))
    if lit and mode & IIP:
        p.normals = idx[0::2]
        p.vertices = idx[1::2]
    elif lit:
        p.normals = [idx[0]] * n
        p.vertices = idx[1:1 + n]
    else:
        p.vertices = idx[:n]
    return p


def read_tmd(data: bytes, base: Optional[int] = None) -> Tmd:
    """Parse a TMD. For FIXP=1 files (pointers are RAM addresses) pass ``base``, the
    RAM address of the object table; if omitted it is inferred as
    ``min(all list pointers) - NOBJ*28`` (lists normally follow the table)."""
    ident, flags, nobj = struct.unpack_from("<III", data, 0)
    if ident != TMD_ID:
        raise ValueError(f"not a TMD (id=0x{ident:08X})")
    table = 12
    entries = [struct.unpack_from("<IIIIIIi", data, table + i * 28) for i in range(nobj)]
    if flags & 1:
        if base is None:
            base = min(min(e[0], e[2], e[4]) for e in entries) - nobj * 28
        rel = lambda p: p - base  # noqa: E731
    else:
        rel = lambda p: p  # noqa: E731

    objects = []
    for vtop, nv, ntop, nn, ptop, np_, scale in entries:
        vo, no, po = table + rel(vtop), table + rel(ntop), table + rel(ptop)
        verts = [struct.unpack_from("<hhh", data, vo + i * 8) for i in range(nv)]
        norms = [struct.unpack_from("<hhh", data, no + i * 8) for i in range(nn)]
        obj = TmdObject(verts, norms, [], scale)
        off = po
        for _ in range(np_):
            olen, ilen, flag, mode = struct.unpack_from("<BBBB", data, off)
            body = data[off + 4:off + 4 + ilen * 4]
            off += 4 + ilen * 4
            if (mode >> 5) != 1 or ilen != expected_ilen(mode, flag) or len(body) < ilen * 4:
                obj.skipped.append((mode, flag, ilen))
                continue
            prim = _decode_prim(mode, flag, body)
            if any(v >= nv for v in prim.vertices) or any(nidx >= nn for nidx in prim.normals):
                obj.skipped.append((mode, flag, ilen))
                continue
            obj.primitives.append(prim)
        objects.append(obj)
    return Tmd(flags, objects)


# ---------------------------------------------------------------- writing

def _encode_prim(p: Primitive) -> bytes:
    mode, flag = p.mode, p.flag
    n = p.n
    uv_words, color_words, idx_count, lit = layout(mode, flag)
    out = bytearray()
    for i in range(uv_words):
        attr = (p.cba or 0) if i == 0 else (p.tsb or 0) if i == 1 else 0
        u, v = p.uvs[i]
        out += struct.pack("<BBH", u, v, attr)
    for i in range(color_words):
        r, g, b = p.colors[i] if i < len(p.colors) else p.colors[0]
        out += struct.pack("<BBBB", r, g, b, mode if i == 0 and not (mode & TME) else 0)
    if lit and mode & IIP:
        idx = [x for pair in zip(p.normals, p.vertices) for x in pair]
    elif lit:
        idx = [p.normals[0]] + p.vertices[:n]
    else:
        idx = p.vertices[:n]
    assert len(idx) == idx_count
    if len(idx) % 2:
        idx.append(0)
    out += struct.pack(f"<{len(idx)}H", *idx)
    header = struct.pack("<BBBB", expected_olen(mode, flag), len(out) // 4, flag, mode)
    return header + bytes(out)


def write_tmd(objects: list[TmdObject]) -> bytes:
    """Serialise objects (FIXP=0). Lists are laid out per object as primitives, vertices, normals."""
    table_size = len(objects) * 28
    body = bytearray()
    entries = []
    for obj in objects:
        prim_off = table_size + len(body)
        for p in obj.primitives:
            body += _encode_prim(p)
        vert_off = table_size + len(body)
        for v in obj.vertices:
            body += struct.pack("<hhhh", *v, 0)
        norm_off = table_size + len(body)
        for nrm in obj.normals:
            body += struct.pack("<hhhh", *nrm, 0)
        entries.append((vert_off, len(obj.vertices), norm_off, len(obj.normals), prim_off, len(obj.primitives), obj.scale))
    out = bytearray(struct.pack("<III", TMD_ID, 0, len(objects)))
    for e in entries:
        out += struct.pack("<IIIIIIi", *e)
    return bytes(out + body)


def make_mode(quad: bool = False, textured: bool = False, gouraud: bool = False, semi: bool = False) -> int:
    return 0x20 | (IIP if gouraud else 0) | (QUAD if quad else 0) | (TME if textured else 0) | (ABE if semi else 0)


# ---------------------------------------------------------------- export

def to_obj(tmd: Tmd, flip_y: bool = True) -> str:
    """Export to Wavefront OBJ. PS1 models are usually Y-down, so Y (and normal Y) is
    negated by default; face winding is reversed accordingly to keep outward normals."""
    lines = ["# exported by ref/tools/tmd.py"]
    vbase = nbase = tbase = 1
    sy = -1 if flip_y else 1
    for oi, obj in enumerate(tmd.objects):
        lines.append(f"o object_{oi}")
        for x, y, z in obj.vertices:
            lines.append(f"v {x} {y * sy} {z}")
        for x, y, z in obj.normals:
            lines.append(f"vn {x / 4096:.5f} {y * sy / 4096:.5f} {z / 4096:.5f}")
        nuv = 0
        current_mat = None
        for p in obj.primitives:
            ring = [0, 1, 3, 2] if p.n == 4 else [0, 1, 2]
            if flip_y:
                ring = ring[::-1]
            if p.uvs:
                mat = f"tsb_{p.tsb or 0:04X}_cba_{p.cba or 0:04X}"
                if mat != current_mat:
                    lines.append(f"usemtl {mat}")
                    current_mat = mat
                for u, v in p.uvs:
                    lines.append(f"vt {u / 256:.5f} {1 - v / 256:.5f}")
            parts = []
            for k in ring:
                s = str(vbase + p.vertices[k])
                if p.uvs or p.normals:
                    s += "/" + (str(tbase + nuv + k) if p.uvs else "")
                if p.normals:
                    s += "/" + str(nbase + p.normals[k])
                parts.append(s)
            lines.append("f " + " ".join(parts))
            nuv += len(p.uvs)
        vbase += len(obj.vertices)
        nbase += len(obj.normals)
        tbase += nuv
    return "\n".join(lines) + "\n"


def describe(tmd: Tmd) -> str:
    out = [f"TMD flags=0x{tmd.flags:X} objects={len(tmd.objects)}"]
    for i, o in enumerate(tmd.objects):
        hist = Counter(p.name for p in o.primitives)
        out.append(f"  object {i}: {len(o.vertices)} verts, {len(o.normals)} normals, {len(o.primitives)} prims, {len(o.skipped)} skipped")
        for name, c in sorted(hist.items()):
            out.append(f"    {name:12s} x{c}")
        if o.skipped:
            sk = Counter(f"mode=0x{m:02X} flag=0x{f:02X} ilen={il}" for m, f, il in o.skipped)
            for k, c in sk.items():
                out.append(f"    skipped {k} x{c}")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ref.tools.tmd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file")
    p = sub.add_parser("obj"); p.add_argument("file"); p.add_argument("--out", required=True)
    p.add_argument("--no-flip", action="store_true", help="keep PS1 Y-down axis")
    a = ap.parse_args(argv)
    tmd = read_tmd(open(a.file, "rb").read())
    if a.cmd == "info":
        print(describe(tmd))
    else:
        with open(a.out, "w") as f:
            f.write(to_obj(tmd, flip_y=not a.no_flip))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
