"""TIM image format: read, write, decode, scan (see ref/formats/tim.md).

WHAT A TIM IS
=============
A TIM file is a VRAM upload saved to disk. The PS1 GPU has a single 1 MB block of
video memory (1024 x 512 cells of 16 bits) that holds the screen, the textures
and the palettes together. A TIM records the pixels *and where in VRAM they
should go*, so a game can copy it straight in:

    +--------+--------+  +-------------------------+  +-------------------------+
    | ID=0x10| FLAGS  |  | CLUT block (optional)   |  | IMAGE block             |
    +--------+--------+  | size, x, y, w, h, data  |  | size, x, y, w, h, data  |
                         +-------------------------+  +-------------------------+

Widths are counted in 16-bit VRAM cells ("halfwords"), not pixels. A 4-bit
texture packs 4 pixels into each cell, an 8-bit one packs 2, and a 15-bit one
uses 1. Forgetting this is the classic first bug when writing a TIM parser.

CLI:
    python -m ref.tools.tim info FILE.tim
    python -m ref.tools.tim png  FILE.tim OUT.png [--clut N]
    python -m ref.tools.tim scan BLOB.bin
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from typing import Optional

TIM_ID = 0x10
# Pixel modes (FLAGS bits 0-2)
PMODE_4BIT, PMODE_8BIT, PMODE_15BIT, PMODE_24BIT, PMODE_MIXED = range(5)
PMODE_NAMES = {0: "4-bit CLUT", 1: "8-bit CLUT", 2: "15-bit direct", 3: "24-bit", 4: "mixed"}


@dataclass
class Block:
    """One rectangle destined for VRAM: a palette block or an image block."""
    x: int
    y: int
    w: int  # in halfwords
    h: int
    data: list[int]  # halfwords, row-major


@dataclass
class TimImage:
    pmode: int
    image: Block
    clut: Optional[Block] = None

    @property
    def width(self) -> int:
        """Width in pixels (image.w is in halfwords)."""
        return {0: self.image.w * 4, 1: self.image.w * 2, 3: self.image.w * 2 // 3}.get(self.pmode, self.image.w)

    @property
    def height(self) -> int:
        return self.image.h

    @property
    def num_cluts(self) -> int:
        """How many palettes the file carries. Each CLUT row is one palette."""
        return self.clut.h if self.clut else 0


# ---------------------------------------------------------------- colour helpers
#
# PS1 colour word (16 bits):  [S][BBBBB][GGGGG][RRRRR]
#   S (bit 15) = semi-transparency / mask flag
#   note the order: RED is in the LOW bits, BLUE in the high bits.

def rgb8_to_15(r: int, g: int, b: int, stp: bool = False) -> int:
    """8-bit RGB -> PS1 15-bit BGR halfword. Note: pure black becomes transparent unless stp."""
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10) | (0x8000 if stp else 0)


def rgb15_to_rgb8(c: int) -> tuple[int, int, int]:
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)


# ---------------------------------------------------------------- parsing

def _read_block(data: bytes, off: int) -> tuple[Block, int]:
    """Read one block header (12 bytes) plus its halfwords; return the block and
    the offset of whatever follows it."""
    if off + 12 > len(data):
        raise ValueError("truncated block header")
    # "<IHHHH": little-endian u32 size, then u16 x, y, w, h
    bnum, x, y, w, h = struct.unpack_from("<IHHHH", data, off)
    count = w * h
    if off + 12 + count * 2 > len(data):
        raise ValueError("truncated block data")
    words = list(struct.unpack_from(f"<{count}H", data, off + 12))
    # BNUM should equal 12 + 2*w*h; some tools write slightly different values,
    # so we trust w*h and step by the larger of the two when it is plausible.
    size = 12 + count * 2
    step = bnum if size <= bnum <= len(data) - off else size
    return Block(x, y, w, h, words), off + step


def read_tim(data: bytes, offset: int = 0) -> TimImage:
    """Parse a TIM starting at ``offset`` (non-zero when it is embedded in an archive)."""
    ident, flags = struct.unpack_from("<II", data, offset)
    if ident != TIM_ID:
        raise ValueError(f"not a TIM (id=0x{ident:08X})")
    pmode = flags & 7                  # bits 0-2: pixel mode
    if pmode > 4 or flags & ~0xF:      # anything above bit 3 must be zero
        raise ValueError(f"bad TIM flags 0x{flags:08X}")
    off = offset + 8
    clut = None
    if flags & 8:                      # bit 3 (CF): a CLUT block comes first
        clut, off = _read_block(data, off)
    image, _ = _read_block(data, off)
    if pmode in (PMODE_4BIT, PMODE_8BIT) and clut is None:
        raise ValueError("palettised TIM without CLUT")
    return TimImage(pmode, image, clut)


# ---------------------------------------------------------------- addressing
#
# A textured primitive does not name a texture file. It names WHERE in VRAM
# the texels are: a texture page (TSB/TPAGE), a palette position (CBA), and
# U,V counted from the page's top-left corner. These helpers compute those
# values from the VRAM position a TIM records (see ref/hardware/gpu.md).

def tim_tpage(tim: TimImage) -> int:
    """TPAGE/TSB value: page x (VRAM x / 64) in bits 0-3, page y (VRAM y / 256)
    in bit 4, colour depth (0 4-bit, 1 8-bit, 2 15-bit) in bits 7-8."""
    return ((tim.pmode & 3) << 7) | ((tim.image.y // 256) << 4) | (tim.image.x // 64)


def tim_cba(tim: TimImage) -> int:
    """CBA value: palette x / 16 in bits 0-5, palette y in bits 6-14 (0 if no CLUT)."""
    if tim.clut is None:
        return 0
    return (tim.clut.y << 6) | (tim.clut.x // 16)


def tim_uv_origin(tim: TimImage) -> tuple[int, int]:
    """Where the image starts inside its texture page, in texels.

    A page is 64 VRAM halfwords wide; a halfword holds 4 texels at 4-bit,
    2 at 8-bit, 1 at 15-bit, so the same VRAM offset is a different U.
    """
    per_hw = {PMODE_4BIT: 4, PMODE_8BIT: 2}.get(tim.pmode, 1)
    return (tim.image.x % 64) * per_hw, tim.image.y % 256


def tim_size(tim: TimImage) -> int:
    """Byte size of the TIM as written by write_tim."""
    n = 8 + 12 + len(tim.image.data) * 2
    if tim.clut:
        n += 12 + len(tim.clut.data) * 2
    return n


# ---------------------------------------------------------------- decoding

def tim_indices(tim: TimImage) -> list[int]:
    """Per-pixel values: palette indices for 4/8-bit, raw halfwords for 15-bit.

    Unpacking order matters: the PS1 GPU reads the LOWEST bits first, so in 4-bit
    mode the low nibble is the leftmost pixel of each group of four.
    """
    out: list[int] = []
    if tim.pmode == PMODE_4BIT:
        for hw in tim.image.data:
            out += [hw & 0xF, (hw >> 4) & 0xF, (hw >> 8) & 0xF, (hw >> 12) & 0xF]  # low nibble = leftmost
    elif tim.pmode == PMODE_8BIT:
        for hw in tim.image.data:
            out += [hw & 0xFF, hw >> 8]
    elif tim.pmode == PMODE_15BIT:
        out = list(tim.image.data)
    else:
        raise ValueError("indices only defined for 4/8/15-bit TIMs")
    return out


def tim_halfwords(tim: TimImage, clut_index: int = 0) -> list[int]:
    """Resolve the palette and return one 15-bit colour per pixel (0x0000 = transparent).

    This is what the GPU does at draw time: look each index up in the CLUT row
    chosen by the polygon. Different rows = different colour schemes, same art.
    """
    vals = tim_indices(tim)
    if tim.pmode in (PMODE_4BIT, PMODE_8BIT):
        assert tim.clut is not None
        if not 0 <= clut_index < tim.clut.h:
            raise IndexError(f"clut_index {clut_index} out of range (0..{tim.clut.h - 1})")
        w = tim.clut.w
        pal = tim.clut.data[clut_index * w:(clut_index + 1) * w]
        return [pal[i] if i < len(pal) else 0 for i in vals]
    return vals


def tim_to_rgba(tim: TimImage, clut_index: int = 0) -> tuple[int, int, bytes]:
    """Decode to 8-bit RGBA. Colour 0x0000 gets alpha 0; everything else alpha 255."""
    w, h = tim.width, tim.height
    out = bytearray()
    if tim.pmode == PMODE_24BIT:
        # 24-bit images are packed R,G,B bytes running across halfword
        # boundaries. They are for full-screen stills, never for textures.
        raw = struct.pack(f"<{len(tim.image.data)}H", *tim.image.data)
        row_bytes = tim.image.w * 2
        for y in range(h):
            row = raw[y * row_bytes:y * row_bytes + w * 3]
            for x in range(w):
                out += row[x * 3:x * 3 + 3] + b"\xff"
        return w, h, bytes(out)
    for c in tim_halfwords(tim, clut_index):
        r, g, b = rgb15_to_rgb8(c)
        out += bytes((r, g, b, 0 if c == 0 else 255))
    return w, h, bytes(out)


# ---------------------------------------------------------------- writing

def write_tim(
    pmode: int,
    width: int,
    height: int,
    pixels: list[int],
    cluts: Optional[list[list[int]]] = None,
    image_xy: tuple[int, int] = (320, 0),
    clut_xy: tuple[int, int] = (0, 480),
) -> bytes:
    """Build a TIM. ``pixels`` are palette indices (4/8-bit) or 15-bit halfwords.

    ``cluts`` is a list of palettes (each 16 or 256 halfwords) for 4/8-bit modes.
    The default VRAM positions put the image just right of a 320-wide frame
    buffer and the palettes near the bottom of VRAM, a common PS1 layout.
    """
    if len(pixels) != width * height:
        raise ValueError("pixel count does not match width*height")
    # Pack pixels into 16-bit VRAM cells (the reverse of tim_indices).
    if pmode == PMODE_4BIT:
        if width % 4:
            raise ValueError("4-bit width must be a multiple of 4")
        words = [
            (pixels[i] & 0xF) | ((pixels[i + 1] & 0xF) << 4) | ((pixels[i + 2] & 0xF) << 8) | ((pixels[i + 3] & 0xF) << 12)
            for i in range(0, len(pixels), 4)
        ]
        hw_w = width // 4
    elif pmode == PMODE_8BIT:
        if width % 2:
            raise ValueError("8-bit width must be even")
        words = [(pixels[i] & 0xFF) | ((pixels[i + 1] & 0xFF) << 8) for i in range(0, len(pixels), 2)]
        hw_w = width // 2
    elif pmode == PMODE_15BIT:
        words = [p & 0xFFFF for p in pixels]
        hw_w = width
    else:
        raise ValueError("write_tim supports 4-bit, 8-bit and 15-bit modes")

    # Header: ID, then flags = pixel mode | CF bit (8) when a CLUT follows.
    out = bytearray(struct.pack("<II", TIM_ID, pmode | (8 if pmode in (0, 1) else 0)))
    if pmode in (PMODE_4BIT, PMODE_8BIT):
        entries = 16 if pmode == PMODE_4BIT else 256
        if not cluts:
            raise ValueError("palettised TIM needs at least one CLUT")
        flat: list[int] = []
        for pal in cluts:
            flat += (list(pal) + [0] * entries)[:entries]   # pad or trim to exactly 16/256
        out += struct.pack("<IHHHH", 12 + len(flat) * 2, clut_xy[0], clut_xy[1], entries, len(cluts))
        out += struct.pack(f"<{len(flat)}H", *flat)
    out += struct.pack("<IHHHH", 12 + len(words) * 2, image_xy[0], image_xy[1], hw_w, height)
    out += struct.pack(f"<{len(words)}H", *words)
    return bytes(out)


# ---------------------------------------------------------------- scanning
#
# Games often bury TIMs inside their own archive files. A cheap way to find
# them: search for the 4-byte ID, check the flags look sane, and try to parse.
# A real TIM parses cleanly; random bytes that happen to contain 10 00 00 00
# almost never do.

def scan(data: bytes) -> list[tuple[int, TimImage]]:
    """Find embedded TIMs by signature + structural validation."""
    found = []
    valid_flags = {0x00, 0x01, 0x02, 0x03, 0x08, 0x09}
    pos = data.find(b"\x10\x00\x00\x00")
    while pos != -1:
        if pos + 8 <= len(data) and data[pos + 4] in valid_flags and data[pos + 5:pos + 8] == b"\x00\x00\x00":
            try:
                tim = read_tim(data, pos)
                if 0 < tim.width <= 1024 and 0 < tim.height <= 512:   # must fit in VRAM
                    found.append((pos, tim))
            except (ValueError, struct.error):
                pass
        pos = data.find(b"\x10\x00\x00\x00", pos + 1)
    return found


def describe(tim: TimImage) -> str:
    s = f"{PMODE_NAMES[tim.pmode]}, {tim.width}x{tim.height} px, VRAM image at ({tim.image.x},{tim.image.y}) {tim.image.w}x{tim.image.h} hw"
    if tim.clut:
        s += f", {tim.clut.h} CLUT(s) of {tim.clut.w} at ({tim.clut.x},{tim.clut.y})"
    return s


def main(argv: Optional[list[str]] = None) -> None:
    from .pngio import write_png

    ap = argparse.ArgumentParser(prog="python -m ref.tools.tim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file")
    p = sub.add_parser("png"); p.add_argument("file"); p.add_argument("out"); p.add_argument("--clut", type=int, default=0)
    p = sub.add_parser("scan"); p.add_argument("file")
    a = ap.parse_args(argv)
    data = open(a.file, "rb").read()
    if a.cmd == "info":
        print(describe(read_tim(data)))
    elif a.cmd == "png":
        w, h, rgba = tim_to_rgba(read_tim(data), a.clut)
        write_png(a.out, w, h, rgba, channels=4)
        print(f"wrote {a.out} ({w}x{h})")
    else:
        hits = scan(data)
        for off, tim in hits:
            print(f"0x{off:08X}: {describe(tim)}")
        print(f"{len(hits)} TIM(s) found")


if __name__ == "__main__":
    main()
