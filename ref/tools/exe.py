"""Identify PlayStation executables and read their headers (see ref/formats/exe-and-disc.md).

THREE KINDS OF PROGRAM FILE
===========================
Before a decompiler can start, it needs to know what it is looking at, where
the code goes in RAM, and where execution starts. PS1-era programs come in
three containers:

    PS-X EXE   "PS-X EXE" magic. The console's own format: a 2048-byte header,
               then code and data copied to a fixed RAM address. What a disc boots.
    ECOFF      bytes 62 01. MIPS little-endian ECOFF from the GCC 2.x era. Net
               Yaroze programs ("a.out") and their .o objects. A Yaroze program
               is only half a program: Sony's libps library stays resident in
               the bottom 576 KB of RAM (below 0x80090000), loaded by the boot disc.
    CPE        "CPE\\x01". Psy-Q's debug-load format: a list of chunks, each
               "put these bytes at this address" or "set this register".

CLI:
    python -m ref.tools.exe info FILE
"""

from __future__ import annotations

import argparse
import struct
from typing import Optional

YAROZE_APP_BASE = 0x80090000     # below this, RAM belongs to the Net Yaroze system (libps)

_ECOFF_MAGIC = {b"\x62\x01": "MIPS little-endian", b"\x01\x62": "MIPS little-endian (byte-swapped header)",
                b"\x60\x01": "MIPS big-endian", b"\x01\x60": "MIPS big-endian (byte-swapped header)"}
_AOUT_MAGIC = {0o407: "OMAGIC (impure)", 0o410: "NMAGIC (shared text)", 0o413: "ZMAGIC (demand paged)"}


def identify(data: bytes) -> str:
    """Return 'psx-exe', 'ecoff', 'cpe' or 'unknown' from the first bytes."""
    if data[:8] == b"PS-X EXE":
        return "psx-exe"
    if data[:2] in _ECOFF_MAGIC:
        return "ecoff"
    if data[:4] == b"CPE\x01":
        return "cpe"
    return "unknown"


# ---------------------------------------------------------------- PS-X EXE

# Field names follow Sony's EXEC structure (Net Yaroze User's Guide, "Kernel
# Management"). The structure starts at offset 0x10 of the file.
_EXEC_FIELDS = ("pc0", "gp0", "t_addr", "t_size", "d_addr", "d_size", "b_addr", "b_size", "s_addr", "s_size")


def read_psx_exe(data: bytes) -> dict:
    if len(data) < 0x800 or data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE (needs the 8-byte magic and a 2048-byte header)")
    h = dict(zip(_EXEC_FIELDS, struct.unpack_from("<10I", data, 0x10)))
    marker = data[0x4C:0x800].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    body = len(data) - 0x800
    h.update(
        kind="psx-exe",
        entry=h["pc0"],
        load_address=h["t_addr"],
        region_marker=marker,
        # Sony documents the body as a multiple of 2048 bytes; the BIOS loads
        # t_size bytes, and some linkers leave the last sector unpadded.
        body_bytes=body,
        complete=body >= h["t_size"],
        padded=h["t_size"] % 0x800 == 0,
    )
    return h


# ---------------------------------------------------------------- ECOFF

def read_ecoff(data: bytes) -> dict:
    """Read the ECOFF file header, the a.out header (if present) and section headers."""
    if data[:2] not in _ECOFF_MAGIC:
        raise ValueError("not an ECOFF file")
    if data[:2] != b"\x62\x01":
        raise ValueError(f"ECOFF variant not handled: {_ECOFF_MAGIC[data[:2]]}")
    try:
        # File header (20 bytes): magic, section count, timestamp, symbolic
        # header offset and size, optional-header size, flags.
        _, nscns, timdat, symptr, nsyms, opthdr, flags = struct.unpack_from("<HHiIiHH", data, 0)
        h = {"kind": "ecoff", "machine": _ECOFF_MAGIC[data[:2]], "sections": [], "timestamp": timdat,
             "executable": bool(flags & 0x0002), "symbols": nsyms > 0}
        off = 20
        if opthdr >= 56:
            # a.out header (56 bytes): where the text/data/bss go and where to start.
            (amagic, _vstamp, tsize, dsize, bsize, entry, text_start, data_start, bss_start,
             _gpr, _c0, _c1, _c2, _c3, gp_value) = struct.unpack_from("<hhiiiIIIIIIIIII", data, off)
            h.update(aout_magic=_AOUT_MAGIC.get(amagic, f"0x{amagic:04X}"), text_size=tsize, data_size=dsize,
                     bss_size=bsize, entry=entry, load_address=text_start, data_start=data_start,
                     bss_start=bss_start, gp_value=gp_value)
        off += opthdr
        for _ in range(nscns):
            # Section header (40 bytes)
            name, _paddr, vaddr, size, scnptr = struct.unpack_from("<8sIIiI", data, off)
            h["sections"].append({"name": name.rstrip(b"\x00").decode("ascii", "replace"),
                                  "address": vaddr, "size": size, "file_offset": scnptr})
            off += 40
    except struct.error:
        raise ValueError(f"truncated ECOFF ({len(data)} bytes)") from None
    if "load_address" in h:
        h["net_yaroze_app"] = h["executable"] and h["load_address"] >= YAROZE_APP_BASE
    return h


# ---------------------------------------------------------------- CPE

def read_cpe(data: bytes) -> dict:
    """Walk a Psy-Q CPE file's chunks.

    Chunk types: 0x00 end; 0x01 load (u32 address, u32 length, bytes);
    0x03 set register (u16 register, u32 value; register 0x90 is the PC);
    0x08 select unit (u8).
    """
    if data[:4] != b"CPE\x01":
        raise ValueError("not a CPE file")
    off, loads, regs, ended = 4, [], {}, False
    try:
        while off < len(data):
            t = data[off]
            off += 1
            if t == 0x00:
                ended = True
                break
            if t == 0x01:
                addr, n = struct.unpack_from("<II", data, off)
                loads.append((addr, n))
                off += 8 + n
            elif t == 0x03:
                reg, val = struct.unpack_from("<HI", data, off)
                regs[reg] = val
                off += 6
            elif t == 0x08:
                off += 1
            else:
                raise ValueError(f"unknown CPE chunk 0x{t:02X} at offset {off - 1}")
    except struct.error:
        raise ValueError("truncated CPE") from None
    lo = min((a for a, _ in loads), default=0)
    hi = max((a + n for a, n in loads), default=0)
    return {"kind": "cpe", "entry": regs.get(0x90), "load_address": lo, "load_end": hi,
            "load_chunks": len(loads), "load_bytes": sum(n for _, n in loads),
            "registers": regs, "ended_cleanly": ended and off == len(data)}


def read_executable(data: bytes) -> dict:
    kind = identify(data)
    if kind == "psx-exe":
        return read_psx_exe(data)
    if kind == "ecoff":
        return read_ecoff(data)
    if kind == "cpe":
        return read_cpe(data)
    raise ValueError("not a PS-X EXE, ECOFF or CPE file")


def describe(h: dict) -> str:
    def hx(v):
        return "-" if v is None else f"0x{v:08X}"
    if h["kind"] == "psx-exe":
        return (f"PS-X EXE: entry {hx(h['pc0'])}, gp {hx(h['gp0'])}, text {hx(h['t_addr'])} +{h['t_size']} bytes"
                f"{'' if h['complete'] else ' (FILE SHORTER THAN t_size)'}, bss {hx(h['b_addr'])} +{h['b_size']}, "
                f"stack {hx(h['s_addr'])} +{h['s_size']}, marker {h['region_marker']!r}")
    if h["kind"] == "ecoff":
        s = f"ECOFF {h['machine']}, {'executable' if h['executable'] else 'object'}"
        if "entry" in h:
            s += (f", {h['aout_magic']}, entry {hx(h['entry'])}, text {hx(h['load_address'])} +{h['text_size']}, "
                  f"data +{h['data_size']}, bss +{h['bss_size']}, gp {hx(h['gp_value'])}")
            if h.get("net_yaroze_app"):
                s += " -- Net Yaroze program (needs libps resident below 0x80090000)"
        s += ", sections " + ", ".join(f"{x['name']}@{hx(x['address'])}+{x['size']}" for x in h["sections"])
        return s
    return (f"CPE: entry {hx(h['entry'])}, {h['load_chunks']} load chunks, {h['load_bytes']} bytes into "
            f"{hx(h['load_address'])}..{hx(h['load_end'])}{'' if h['ended_cleanly'] else ' (did not end cleanly)'}")


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ref.tools.exe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file")
    a = ap.parse_args(argv)
    print(describe(read_executable(open(a.file, "rb").read())))


if __name__ == "__main__":
    main()
