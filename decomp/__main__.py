"""PSX Decomp Studio pipeline: ``python -m decomp <command>``.

Commands:
    image    FILE [--out image.bin]       show (and optionally write) the flat memory image
    analyze  FILE --out DIR [--ghidra DIR] [--timeout S] [--dry-run]
             run Ghidra headless: PS1 memory map, register names, GTE comments,
             decompiled C (DIR/all.c, DIR/c/*.c) and DIR/functions.json
"""

from __future__ import annotations

import argparse
import sys

from .image import build_image


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m decomp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("image", help="build the flat memory image")
    p.add_argument("file")
    p.add_argument("--out")
    p = sub.add_parser("analyze", help="analyse with Ghidra headless")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--ghidra", help="Ghidra install dir (default: $GHIDRA_INSTALL_DIR)")
    p.add_argument("--timeout", type=int, default=1800, help="analysis timeout in seconds")
    p.add_argument("--dry-run", action="store_true", help="prepare inputs and print the command only")
    p.add_argument("--libps", help="Net Yaroze resident library image (PS-X EXE, may be .gz) to load at 0x80010000")
    p.add_argument("--libps-symbols", help="libps entry-point names: '.set NAME, 0xADDR' or 'NAME ADDR' lines")
    p.add_argument("--psxsdk", help="a ChrisRx/psxsdk checkout: take --libps and --libps-symbols from it")
    a = ap.parse_args(argv)

    if a.cmd == "image":
        img = build_image(open(a.file, "rb").read())
        print(f"{img.kind}: base 0x{img.base:08X}, {len(img.data)} bytes (to 0x{img.end:08X}), "
              f"entry 0x{img.entry:08X}, gp {'0x%08X' % img.gp if img.gp else '-'}")
        for n in img.notes:
            print("  note:", n)
        if a.out:
            with open(a.out, "wb") as f:
                f.write(img.data)
            print(f"wrote {a.out}")
        return 0

    from .ghidra import Libps, analyze
    try:
        libps = Libps.load(a.libps, a.libps_symbols, a.psxsdk)
        r = analyze(a.file, a.out, a.ghidra, a.timeout, a.dry_run, libps)
    except (OSError, RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if a.dry_run:
        print(" ".join(r.summary["command"]))
        return 0
    s = r.summary
    print(f"{s['functions']} functions ({s['decompiled']} decompiled, {s['failed']} failed, "
          f"{s['external']} external calls without code), "
          f"{s['gte_instructions']} GTE instructions {s['gte_by_command']}")
    print(f"output: {r.out_dir}/all.c, {r.out_dir}/c/, {r.out_dir}/functions.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
