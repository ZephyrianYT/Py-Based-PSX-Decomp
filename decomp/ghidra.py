"""Run Ghidra headless over a PS1 executable: the pipeline's Binary Analysis stage.

    image  -> ghidra analyzeHeadless (BinaryLoader, MIPS:LE:32)
           -> PsxSetup.java   (memory map, register names, entry, $gp)  before analysis
           -> auto-analysis   (Ghidra's own disassembly, functions, references)
           -> PsxExport.java  (GTE comments, decompiled C, functions.json) after analysis

Ghidra itself is not bundled. Point at an installation with --ghidra DIR or
the GHIDRA_INSTALL_DIR environment variable (the decomp Docker image has one).
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from . import psx_symbols
from .image import RAM_END, RAM_START, MemoryImage, build_image, from_psx_exe

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ghidra_scripts")
PROCESSOR = "MIPS:LE:32:default"          # R3000A: 32-bit MIPS I, little-endian


def find_analyze_headless(ghidra_dir: Optional[str] = None) -> str:
    """Path to Ghidra's analyzeHeadless launcher."""
    candidates = []
    for d in (ghidra_dir, os.environ.get("GHIDRA_INSTALL_DIR")):
        if d:
            candidates.append(os.path.join(d, "support", "analyzeHeadless"))
    on_path = shutil.which("analyzeHeadless")
    if on_path:
        candidates.append(on_path)
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("Ghidra not found: pass --ghidra DIR or set GHIDRA_INSTALL_DIR "
                            "(the folder that contains support/analyzeHeadless)")


@dataclass
class Libps:
    """A user-supplied copy of the Net Yaroze resident library, and/or its entry
    point names. Not bundled: both come from Sony's libps (see decomp/README.md)."""
    image: Optional[MemoryImage] = None
    symbols: list = None  # type: ignore[assignment]

    @classmethod
    def load(cls, image_path: Optional[str] = None, symbols_path: Optional[str] = None,
             psxsdk_dir: Optional[str] = None) -> Optional["Libps"]:
        if psxsdk_dir:
            image_path = image_path or os.path.join(psxsdk_dir, "link", "libps.exe.gz")
            symbols_path = symbols_path or os.path.join(
                psxsdk_dir, "internal", "toolchain", "_tinygo", "targets", "playstation-yaroze-symusr.S")
        if not image_path and not symbols_path:
            return None
        lib = cls(symbols=[])
        if image_path:
            with open(image_path, "rb") as f:
                data = f.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            lib.image = from_psx_exe(data)
        if symbols_path:
            with open(symbols_path) as f:
                lib.symbols = psx_symbols.parse_symbol_list(f.read())
        return lib


def ram_gaps(image: MemoryImage, libps: Optional[Libps] = None) -> list[tuple[str, int, int, str]]:
    """Main-RAM ranges not covered by the image or by a fixed region, as regions."""
    taken = [(image.base, image.end)]
    if libps and libps.image:
        taken.append((libps.image.base, libps.image.end))
    use_placeholder = image.net_yaroze and not (libps and libps.image)
    regions = list(psx_symbols.REGIONS) + ([psx_symbols.NET_YAROZE_LIBPS] if use_placeholder else [])
    taken += [(s, s + n) for _, s, n, _ in regions if RAM_START <= s < RAM_END]
    taken.sort()
    gaps, cur = [], RAM_START
    for s, e in taken:
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < RAM_END:
        gaps.append((cur, RAM_END))
    return [(f"ram_{s:08X}", s, e - s, "ram") for s, e in gaps if e - s > 0]


def symbols_file_text(image: MemoryImage, libps: Optional[Libps] = None, libps_path: Optional[str] = None) -> str:
    use_placeholder = image.net_yaroze and not (libps and libps.image)
    text = psx_symbols.symbols_tsv(net_yaroze=use_placeholder)
    for name, start, size, kind in ram_gaps(image, libps):
        text += f"region\t{name}\t{start:08X}\t{size:X}\t{kind}\n"
    if libps and libps.image and libps_path:
        text += f"file\tlibps\t{libps.image.base:08X}\t{len(libps.image.data):X}\t{libps_path}\n"
    for name, addr in (libps.symbols if libps else []):
        text += f"func\t{name}\t{addr:08X}\tNet Yaroze libps entry point\n"
    return text


def headless_command(analyze_headless: str, project_dir: str, image_path: str, image: MemoryImage,
                     symbols_path: str, out_dir: str, timeout_s: int = 1800) -> list[str]:
    gp = f"{image.gp:08X}" if image.gp else "-"
    return [
        analyze_headless, project_dir, "psx",
        "-import", image_path,
        "-loader", "BinaryLoader",
        "-loader-baseAddr", f"0x{image.base:08X}",
        "-loader-blockName", "main",
        "-processor", PROCESSOR,
        "-cspec", "default",
        "-scriptPath", SCRIPTS_DIR,
        "-preScript", "PsxSetup.java", symbols_path, f"{image.entry:08X}", gp,
        "-postScript", "PsxExport.java", out_dir, symbols_path,
        "-analysisTimeoutPerFile", str(timeout_s),
        "-deleteProject",
    ]


@dataclass
class AnalysisResult:
    out_dir: str
    summary: dict
    functions: list[dict]
    log: str


def analyze(exe_path: str, out_dir: str, ghidra_dir: Optional[str] = None, timeout_s: int = 1800,
            dry_run: bool = False, libps: Optional[Libps] = None) -> AnalysisResult:
    """Analyse one executable. With dry_run, only prepare the inputs and return the command."""
    with open(exe_path, "rb") as f:
        image = build_image(f.read())
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    image_path = os.path.join(out_dir, "image.bin")
    symbols_path = os.path.join(out_dir, "symbols.tsv")
    with open(image_path, "wb") as f:
        f.write(image.data)
    libps_path = None
    if libps and libps.image:
        libps_path = os.path.join(out_dir, "libps.bin")
        with open(libps_path, "wb") as f:
            f.write(libps.image.data)
    with open(symbols_path, "w") as f:
        f.write(symbols_file_text(image, libps, libps_path))
    with open(os.path.join(out_dir, "image.json"), "w") as f:
        json.dump({"source": os.path.basename(exe_path), "kind": image.kind, "base": f"0x{image.base:08X}",
                   "size": len(image.data), "entry": f"0x{image.entry:08X}",
                   "gp": f"0x{image.gp:08X}" if image.gp else None, "net_yaroze": image.net_yaroze,
                   "notes": image.notes,
                   "libps_image": bool(libps and libps.image),
                   "libps_symbols": len(libps.symbols) if libps else 0}, f, indent=2)

    ah = "analyzeHeadless" if dry_run else find_analyze_headless(ghidra_dir)
    project_dir = tempfile.mkdtemp(prefix="psx_ghidra_")
    cmd = headless_command(ah, project_dir, image_path, image, symbols_path, out_dir, timeout_s)
    if dry_run:
        os.rmdir(project_dir)
        return AnalysisResult(out_dir, {"dry_run": True, "command": cmd}, [], "")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 600)
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
    log = proc.stdout + proc.stderr
    with open(os.path.join(out_dir, "ghidra.log"), "w") as f:
        f.write(log)
    summary_path = os.path.join(out_dir, "summary.json")
    if proc.returncode != 0 or not os.path.exists(summary_path):
        tail = "\n".join(log.strip().splitlines()[-25:])
        raise RuntimeError(f"Ghidra analysis failed (exit {proc.returncode}); see {out_dir}/ghidra.log\n{tail}")
    with open(summary_path) as f:
        summary = json.load(f)
    with open(os.path.join(out_dir, "functions.json")) as f:
        functions = json.load(f)
    return AnalysisResult(out_dir, summary, functions, log)
