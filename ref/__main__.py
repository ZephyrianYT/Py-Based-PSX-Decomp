"""Single entry point for the reference tools: ``python -m ref <command> [args]``.

This is also the container's entry point (see the Dockerfile), so
``docker run psx-ref demo --out /out`` and ``python -m ref demo --out ref_out``
do exactly the same thing.

Commands:
    demo       render the comparison images        (ref/tools/demo.py)
    worldgen   generate terrain / dungeon OBJ+PNG  (ref/tools/worldgen.py)
    tim        inspect, convert or scan TIM files  (ref/tools/tim.py)
    tmd        inspect or OBJ-export TMD models    (ref/tools/tmd.py)
    rsd        read / link Sony RSD text models    (ref/tools/rsd.py)
    exe        identify PS-X EXE / ECOFF / CPE     (ref/tools/exe.py)
    validate   check the tools on a folder of real files (ref/tools/validate.py)
    jitter     print the GTE vertex-jitter table   (ref/tools/fixedpoint.py)
    test       run the self-tests                  (ref/tests/)
    docs       list the reference documents        (ref/index.json)
"""

from __future__ import annotations

import json
import os
import sys
import unittest

REF_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_tests() -> int:
    # Discover from the repository root so ``ref`` imports as a package.
    root = os.path.dirname(REF_DIR)
    suite = unittest.defaultTestLoader.discover(os.path.join(REF_DIR, "tests"), top_level_dir=root)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def _list_docs() -> int:
    with open(os.path.join(REF_DIR, "index.json")) as f:
        index = json.load(f)
    for doc in index["docs"]:
        print(f"ref/{doc['path']:<32} {doc['summary']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "demo":
        from .tools import demo
        demo.main(rest)
    elif cmd == "worldgen":
        from .tools import worldgen
        worldgen.main(rest)
    elif cmd == "tim":
        from .tools import tim
        tim.main(rest)
    elif cmd == "tmd":
        from .tools import tmd
        tmd.main(rest)
    elif cmd == "rsd":
        from .tools import rsd
        rsd.main(rest)
    elif cmd == "exe":
        from .tools import exe
        exe.main(rest)
    elif cmd == "validate":
        from .tools import validate
        validate.main(rest)
    elif cmd == "jitter":
        from .tools import fixedpoint
        fixedpoint._demo()
    elif cmd == "test":
        return _run_tests()
    elif cmd == "docs":
        return _list_docs()
    else:
        print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
