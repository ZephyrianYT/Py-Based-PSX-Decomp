"""Minimal PNG writer (RGB / RGBA, 8-bit) using only zlib. No reader."""

from __future__ import annotations

import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(width: int, height: int, pixels: bytes, channels: int = 3) -> bytes:
    """Encode row-major 8-bit pixels (``channels`` = 3 for RGB, 4 for RGBA)."""
    if channels not in (3, 4):
        raise ValueError("channels must be 3 or 4")
    stride = width * channels
    if len(pixels) != stride * height:
        raise ValueError(f"expected {stride * height} bytes, got {len(pixels)}")
    raw = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    color_type = 2 if channels == 3 else 6
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def write_png(path: str, width: int, height: int, pixels: bytes, channels: int = 3) -> None:
    with open(path, "wb") as f:
        f.write(encode_png(width, height, pixels, channels))


def scale_nearest(width: int, height: int, pixels: bytes, factor: int, channels: int = 3) -> tuple[int, int, bytes]:
    """Integer nearest-neighbour upscale (the correct way to enlarge PS1 output)."""
    if factor == 1:
        return width, height, pixels
    out = bytearray()
    stride = width * channels
    for y in range(height):
        row = pixels[y * stride:(y + 1) * stride]
        big = b"".join(row[x * channels:(x + 1) * channels] * factor for x in range(width))
        out += big * factor
    return width * factor, height * factor, bytes(out)
