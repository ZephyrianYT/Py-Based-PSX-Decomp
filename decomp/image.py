"""Turn a PS1 executable into a flat memory image for disassembly.

Ghidra (and most disassemblers) can load "raw bytes at an address" without
knowing anything about PlayStation file formats. This module does the format
work in Python, using the readers in ref/tools/exe.py (validated on 321 real
executables), and produces exactly that:

    base      RAM address of the first byte
    data      the bytes as they sit in RAM after loading (BSS included, zeroed)
    entry     where execution starts
    gp        initial value of the MIPS global pointer ($gp, r28), or None

Supported inputs:
    PS-X EXE   the body (file offset 0x800) at t_addr; BSS appended if it follows
    ECOFF      Net Yaroze programs: each section placed at its address
    CPE        Psy-Q builds: each load chunk placed at its address
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from ref.tools import exe

RAM_START, RAM_END = 0x80000000, 0x80200000          # 2 MB main RAM (KSEG0)
MAX_IMAGE = RAM_END - RAM_START


@dataclass
class MemoryImage:
    kind: str                      # psx-exe / ecoff / cpe
    base: int
    data: bytes
    entry: int
    gp: Optional[int]
    notes: list[str] = field(default_factory=list)
    net_yaroze: bool = False       # libps expected resident below 0x80090000

    @property
    def end(self) -> int:
        return self.base + len(self.data)


def _place(chunks: list[tuple[int, bytes]]) -> tuple[int, bytes]:
    """Lay (address, bytes) chunks into one buffer, zero-filling gaps."""
    chunks = [(a, b) for a, b in chunks if b]
    if not chunks:
        raise ValueError("nothing to load")
    lo = min(a for a, _ in chunks)
    hi = max(a + len(b) for a, b in chunks)
    if hi - lo > MAX_IMAGE:
        raise ValueError(f"image spans {hi - lo:#x} bytes, more than PS1 RAM")
    buf = bytearray(hi - lo)
    for a, b in chunks:
        buf[a - lo:a - lo + len(b)] = b
    return lo, bytes(buf)


def from_psx_exe(data: bytes) -> MemoryImage:
    h = exe.read_psx_exe(data)
    body = data[0x800:0x800 + h["t_size"]]
    chunks = [(h["t_addr"], body)]
    notes = []
    if not h["complete"]:
        notes.append(f"file is {h['t_size'] - len(body)} bytes shorter than t_size; image truncated")
    if h["b_size"] and h["b_addr"] >= h["t_addr"]:
        chunks.append((h["b_addr"], bytes(h["b_size"])))
    base, img = _place(chunks)
    if h["region_marker"].startswith("YAREXE"):
        notes.append("yarexe conversion: Net Yaroze program with libps bundled in")
    return MemoryImage("psx-exe", base, img, h["pc0"], h["gp0"] or None, notes)


_LOADED_ECOFF_SECTIONS = (".text", ".init", ".rdata", ".data", ".lit8", ".lit4", ".sdata")
_ZERO_ECOFF_SECTIONS = (".sbss", ".bss")


def from_ecoff(data: bytes) -> MemoryImage:
    h = exe.read_ecoff(data)
    if not h.get("executable") or "entry" not in h:
        raise ValueError("ECOFF object file (.o), not a linked program")
    chunks = []
    for s in h["sections"]:
        if s["size"] <= 0:
            continue
        if s["name"] in _LOADED_ECOFF_SECTIONS:
            chunks.append((s["address"], data[s["file_offset"]:s["file_offset"] + s["size"]]))
        elif s["name"] in _ZERO_ECOFF_SECTIONS:
            chunks.append((s["address"], bytes(s["size"])))
    base, img = _place(chunks)
    img_ = MemoryImage("ecoff", base, img, h["entry"], h["gp_value"] or None, net_yaroze=bool(h.get("net_yaroze_app")))
    if img_.net_yaroze:
        img_.notes.append("Net Yaroze program: calls below 0x80090000 go to resident libps (not in this file)")
    return img_


def from_cpe(data: bytes) -> MemoryImage:
    h = exe.read_cpe(data)
    chunks, off = [], 4
    while off < len(data):                       # walk again to collect the bytes
        t = data[off]
        off += 1
        if t == 0x00:
            break
        if t == 0x01:
            addr, n = struct.unpack_from("<II", data, off)
            chunks.append((addr, data[off + 8:off + 8 + n]))
            off += 8 + n
        elif t == 0x03:
            off += 6
        elif t == 0x08:
            off += 1
    base, img = _place(chunks)
    if h["entry"] is None:
        raise ValueError("CPE file sets no PC (register 0x90)")
    # Only register 0x90 (PC) has a documented meaning here; gp is left unset.
    return MemoryImage("cpe", base, img, h["entry"], None)


def build_image(data: bytes) -> MemoryImage:
    """Detect the container and build the memory image."""
    kind = exe.identify(data)
    if kind == "psx-exe":
        return from_psx_exe(data)
    if kind == "ecoff":
        return from_ecoff(data)
    if kind == "cpe":
        return from_cpe(data)
    raise ValueError("not a PS-X EXE, ECOFF or CPE executable")
