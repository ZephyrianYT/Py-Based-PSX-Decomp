"""TMD model format: read, write, export to OBJ (see ref/formats/tmd.md).

WHAT A TMD IS
=============
TMD is Sony's standard 3D model file. It is designed so the CPU can turn it
into GPU drawing commands with as little work as possible:

    header (12 bytes)      ID 0x41, flags, number of objects
    object table           one 28-byte entry per object, pointing at three lists:
      vertex list          int16 x, y, z, pad     (8 bytes each)
      normal list          int16 nx, ny, nz, pad  (1.3.12 fixed point, 4096 = 1.0)
      primitive list       polygons, lines and 3D sprites: a 4-byte header +
                           data that references the lists above by index

Each primitive's header says what kind it is (polygon, line or sprite; flat or
Gouraud, textured or not, triangle or quad, lit or unlit). Its data layout
depends on that kind, so a parser must work out the layout before it can read
the data. ``expected_ilen()`` below encodes the rule; ``ilen`` in the header
lets us verify it, and any primitive that disagrees is skipped via ``ilen`` and
recorded in ``TmdObject.skipped`` instead of being misread.

The rule was checked against Sony's Net Yaroze "File Formats" manual (every
table) and against 245 real TMD files from the Net Yaroze samples: ~77,000
primitives across 15 kinds decoded with nothing skipped (ref/tools/validate.py).

COORDINATES AND WINDING
=======================
TMD space is X right, Y DOWN, Z away from the viewer. A polygon faces the
viewer when its first three vertices run CLOCKWISE on screen (Sony's PLY spec;
in the samples, 96% of lit polygons' authored normals agree). Quad vertices are
in GPU "Z" order: (0,1,2,3) = top-left, top-right, bottom-left, bottom-right,
drawn as triangles (0,1,2) and (1,2,3).

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

# Primitive kinds: bits 7-5 of the mode byte ("CODE").
CODE_POLYGON, CODE_LINE, CODE_SPRITE = 1, 2, 3

# mode bits (polygon). These are the same bits as the GPU's polygon command
# byte, so a TMD mode of 0x3C is literally GPU command 0x3C (Gouraud textured quad).
TGE, ABE, TME, QUAD, IIP = 0x01, 0x02, 0x04, 0x08, 0x10
#     TGE  = texture used as-is (no brightness modulation). Sony's own unlit
#            primitives set it too (modes 0x21, 0x25, 0x31 ... in the manual).
#     ABE  = semi-transparent
#     TME  = textured
#     QUAD = four vertices instead of three
#     IIP  = Gouraud (per-vertex colour/normal) instead of flat
# A line's mode is 010 IIP 00 ABE 0; a 3D sprite's is 011 SIZ 1 ABE 0, where
# SIZ (bits 4-3) is 0 free size, 1 = 1x1, 2 = 8x8, 3 = 16x16.
# flag bits
LGT, FCE, GRD = 0x01, 0x02, 0x04
#     LGT = "no lighting": colours are stored and used directly (pre-lit / baked)
#     FCE = double-sided
#     GRD = per-vertex colours on a lit, untextured polygon ("gradation")

# Size of the GPU packet each polygon turns into, in 32-bit words. Stored in
# the file (olen) so the game can allocate packet memory without decoding.
_OLEN = {  # (quad, textured, gouraud-output) -> GPU packet words
    (0, 0, 0): 4, (0, 1, 0): 7, (0, 0, 1): 6, (0, 1, 1): 9,
    (1, 0, 0): 5, (1, 1, 0): 9, (1, 0, 1): 8, (1, 1, 1): 12,
}
_SPRITE_SIZES = {1: (1, 1), 2: (8, 8), 3: (16, 16)}


@dataclass
class Primitive:
    mode: int
    flag: int
    vertices: list[int]                       # indices, GPU order (2 for a line, 1 for a sprite)
    normals: list[int] = field(default_factory=list)   # per vertex (flat repeats normal0); empty if unlit
    colors: list[tuple[int, int, int]] = field(default_factory=list)  # 1 or n entries
    uvs: list[tuple[int, int]] = field(default_factory=list)
    cba: Optional[int] = None                 # CLUT attribute
    tsb: Optional[int] = None                 # texpage attribute
    size: Optional[tuple[int, int]] = None    # sprites: width, height

    @property
    def code(self) -> int:
        return self.mode >> 5

    @property
    def n(self) -> int:
        """Number of vertices."""
        if self.code == CODE_LINE:
            return 2
        if self.code == CODE_SPRITE:
            return 1
        return 4 if self.mode & QUAD else 3

    @property
    def name(self) -> str:
        if self.code == CODE_LINE:
            return "GLINE" if self.mode & IIP else "LINE"
        if self.code == CODE_SPRITE:
            w, h = self.size or (0, 0)
            return f"SPRITE {w}x{h}"
        s = ("G" if self.mode & IIP else "F") + ("T" if self.mode & TME else "") + str(self.n)
        return s + ("" if not self.flag & LGT else " (unlit)")


@dataclass
class TmdObject:
    vertices: list[tuple[int, int, int]]
    normals: list[tuple[int, int, int]]
    primitives: list[Primitive]
    scale: int = 0                            # the model was designed at 2**scale times this size
    skipped: list[tuple[int, int, int]] = field(default_factory=list)  # (mode, flag, ilen)


@dataclass
class Tmd:
    flags: int
    objects: list[TmdObject]


def layout(mode: int, flag: int) -> tuple[int, int, int, bool]:
    """Return (uv_words, color_words, index_halfwords, lit) for a polygon primitive.

    The data that follows a primitive header is, in order:
      1. texture coordinates (only if textured): one word per vertex
      2. colours: how many depends on lighting and shading (see below)
      3. indices into the normal and vertex lists, two 16-bit indices per word

    Why colours vary: a *lit* polygon gets its colour from the GTE's lighting
    at runtime, so it needs normals, plus a base colour only if untextured. An
    *unlit* polygon has its final colour baked into the file: one colour if
    flat, one per vertex if shaded.
    """
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


def _sprite_siz(mode: int) -> int:
    return (mode >> 3) & 3


def expected_ilen(mode: int, flag: int) -> int:
    """Words of data after the header, or -1 for a kind this module does not know."""
    code = mode >> 5
    if code == CODE_POLYGON:
        uv, col, idx, _ = layout(mode, flag)
        return uv + col + (idx + 1) // 2
    if code == CODE_LINE:
        return (2 if mode & IIP else 1) + 1          # colour(s), then vertex0|vertex1
    if code == CODE_SPRITE:
        return 3 if _sprite_siz(mode) == 0 else 2    # free-size sprites add a W|H word
    return -1


def expected_olen(mode: int, flag: int) -> int:
    code = mode >> 5
    if code == CODE_LINE:
        return 4 if mode & IIP else 3
    if code == CODE_SPRITE:
        return 5 if _sprite_siz(mode) == 0 else 4
    gour = bool(mode & IIP) or bool(flag & GRD)
    return _OLEN[(int(bool(mode & QUAD)), int(bool(mode & TME)), int(gour))]


# ---------------------------------------------------------------- reading

def _decode_polygon(mode: int, flag: int, words: bytes) -> Primitive:
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
    # Three index patterns:
    #   lit + Gouraud: normal0, vertex0, normal1, vertex1, ...  (a normal per corner)
    #   lit + flat:    normal0, vertex0, vertex1, ...           (one face normal)
    #   unlit:         vertex0, vertex1, ...                    (no normals needed)
    if lit and mode & IIP:
        p.normals = idx[0::2]
        p.vertices = idx[1::2]
    elif lit:
        p.normals = [idx[0]] * n
        p.vertices = idx[1:1 + n]
    else:
        p.vertices = idx[:n]
    return p


def _decode_line(mode: int, flag: int, words: bytes) -> Primitive:
    # [R G B mode] ([R1 G1 B1 pad]) [vertex0 | vertex1]
    p = Primitive(mode, flag, [])
    ncol = 2 if mode & IIP else 1
    for i in range(ncol):
        r, g, b, _ = struct.unpack_from("<BBBB", words, i * 4)
        p.colors.append((r, g, b))
    p.vertices = list(struct.unpack_from("<HH", words, ncol * 4))
    return p


def _decode_sprite(mode: int, flag: int, words: bytes) -> Primitive:
    # [vertex0 | TSB] [U V | CBA] ([W | H] for free size). A 3D sprite is a
    # camera-facing rectangle of texture placed at one vertex.
    v0, tsb, u, v, cba = struct.unpack_from("<HHBBH", words, 0)
    p = Primitive(mode, flag, [v0], uvs=[(u, v)], cba=cba, tsb=tsb)
    siz = _sprite_siz(mode)
    p.size = struct.unpack_from("<HH", words, 8) if siz == 0 else _SPRITE_SIZES[siz]
    return p


_DECODERS = {CODE_POLYGON: _decode_polygon, CODE_LINE: _decode_line, CODE_SPRITE: _decode_sprite}


def read_tmd(data: bytes, base: Optional[int] = None) -> Tmd:
    """Parse a TMD. For FIXP=1 files (pointers are RAM addresses) pass ``base``, the
    RAM address of the object table; if omitted it is inferred as
    ``min(all list pointers) - NOBJ*28`` (lists normally follow the table).

    Raises ValueError for anything that is not a complete TMD.
    """
    try:
        return _read_tmd(data, base)
    except struct.error as e:   # ran off the end of the data somewhere
        raise ValueError(f"truncated TMD ({len(data)} bytes): {e}") from None


def _read_tmd(data: bytes, base: Optional[int]) -> Tmd:
    ident, flags, nobj = struct.unpack_from("<III", data, 0)
    if ident != TMD_ID:
        raise ValueError(f"not a TMD (id=0x{ident:08X})")
    table = 12
    entries = [struct.unpack_from("<IIIIIIi", data, table + i * 28) for i in range(nobj)]
    if flags & 1:
        # FIXP=1: pointers are absolute RAM addresses (a file dumped from
        # memory after libgs relocated it). Work back to offsets.
        if base is None:
            base = min(min(e[0], e[2], e[4]) for e in entries) - nobj * 28
        rel = lambda p: p - base  # noqa: E731
    else:
        rel = lambda p: p  # noqa: E731

    objects = []
    for vtop, nv, ntop, nn, ptop, np_, scale in entries:
        vo, no, po = table + rel(vtop), table + rel(ntop), table + rel(ptop)
        for start, count in ((vo, nv), (no, nn)):
            if start < 0 or start + count * 8 > len(data):
                raise ValueError(f"truncated TMD: a list at offset {start} of {count} entries runs past {len(data)} bytes")
        verts = [struct.unpack_from("<hhh", data, vo + i * 8) for i in range(nv)]
        norms = [struct.unpack_from("<hhh", data, no + i * 8) for i in range(nn)]
        obj = TmdObject(verts, norms, [], scale)
        off = po
        for _ in range(np_):
            olen, ilen, flag, mode = struct.unpack_from("<BBBB", data, off)
            body = data[off + 4:off + 4 + ilen * 4]
            # ilen tells us the data size, so we can ALWAYS step to the next
            # primitive, even one we do not understand.
            off += 4 + ilen * 4
            # Safety check: only decode kinds whose size matches the layout
            # rule. Anything else is recorded, not guessed at, so a bad guess
            # can never produce garbage geometry.
            decoder = _DECODERS.get(mode >> 5)
            if decoder is None or ilen != expected_ilen(mode, flag) or len(body) < ilen * 4:
                obj.skipped.append((mode, flag, ilen))
                continue
            prim = decoder(mode, flag, body)
            if any(v >= nv for v in prim.vertices) or any(nidx >= nn for nidx in prim.normals):
                obj.skipped.append((mode, flag, ilen))
                continue
            obj.primitives.append(prim)
        objects.append(obj)
    return Tmd(flags, objects)


# ---------------------------------------------------------------- writing

def _encode_polygon(p: Primitive) -> bytes:
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
        # The first colour word of an untextured polygon repeats the mode byte.
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
    return bytes(out)


def _encode_line(p: Primitive) -> bytes:
    out = bytearray()
    for i in range(2 if p.mode & IIP else 1):
        r, g, b = p.colors[i] if i < len(p.colors) else p.colors[0]
        out += struct.pack("<BBBB", r, g, b, p.mode if i == 0 else 0)
    return bytes(out + struct.pack("<HH", p.vertices[0], p.vertices[1]))


def _encode_sprite(p: Primitive) -> bytes:
    u, v = p.uvs[0]
    out = struct.pack("<HHBBH", p.vertices[0], p.tsb or 0, u, v, p.cba or 0)
    if _sprite_siz(p.mode) == 0:
        out += struct.pack("<HH", *(p.size or (0, 0)))
    return out


_ENCODERS = {CODE_POLYGON: _encode_polygon, CODE_LINE: _encode_line, CODE_SPRITE: _encode_sprite}


def _encode_prim(p: Primitive) -> bytes:
    body = _ENCODERS[p.code](p)
    header = struct.pack("<BBBB", expected_olen(p.mode, p.flag), len(body) // 4, p.flag, p.mode)
    return header + body


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


def make_mode(quad: bool = False, textured: bool = False, gouraud: bool = False, semi: bool = False,
              tge: bool = False) -> int:
    """Polygon mode byte. Pass ``tge=True`` for unlit polygons to match Sony's tools."""
    return (0x20 | (IIP if gouraud else 0) | (QUAD if quad else 0) | (TME if textured else 0)
            | (ABE if semi else 0) | (TGE if tge else 0))


def make_line_mode(gouraud: bool = False, semi: bool = False) -> int:
    return 0x40 | (IIP if gouraud else 0) | (ABE if semi else 0)


def make_sprite_mode(width: int, height: int, semi: bool = False) -> int:
    siz = {v: k for k, v in _SPRITE_SIZES.items()}.get((width, height), 0)
    return 0x64 | (siz << 3) | (ABE if semi else 0)


# ---------------------------------------------------------------- export

def to_obj(tmd: Tmd, flip_y: bool = True) -> str:
    """Export to Wavefront OBJ (polygons as faces, lines as ``l``, sprites as points).

    OBJ viewers expect Y up and front faces running counter-clockwise. TMD is
    Y down with clockwise front faces. Negating Y is a mirror, and a mirror by
    itself turns clockwise into counter-clockwise, so the default export
    (``flip_y=True``) keeps the vertex order. With ``flip_y=False`` the geometry
    stays Y-down and the order is reversed instead, so faces still point out.
    """
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
            if p.code == CODE_LINE:
                lines.append(f"l {vbase + p.vertices[0]} {vbase + p.vertices[1]}")
                continue
            if p.code == CODE_SPRITE:
                lines.append(f"p {vbase + p.vertices[0]}")
                continue
            # PS1 quads list corners in "Z" order (top-left, top-right,
            # bottom-left, bottom-right) because the GPU draws them as triangles
            # (0,1,2) and (1,2,3). OBJ wants corners in order around the edge,
            # so swap the last two. Both orders turn the same way.
            ring = [0, 1, 3, 2] if p.n == 4 else [0, 1, 2]
            if not flip_y:
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
