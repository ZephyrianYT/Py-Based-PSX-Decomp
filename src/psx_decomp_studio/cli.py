"""Command-line entry point."""

import argparse

from psx_decomp_studio import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psx-decomp-studio",
        description="Decompile and modernize PlayStation 1 titles (work in progress).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("PSX Decomp Studio is a work in progress; no pipeline stages are implemented yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
