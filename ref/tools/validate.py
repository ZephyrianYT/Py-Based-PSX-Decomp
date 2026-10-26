"""Check the format tools against real PS1-era files.

    python -m ref.tools.validate PATH [PATH ...]

Walks the given folders (for example a checkout of
https://github.com/gwald/netyaroze_demo, Sony's Net Yaroze samples) and runs
every parser in ref/tools over every TIM, TMD, RSD and executable it finds:

  * TIM   parse and decode every file; tally pixel modes and flag bytes
  * TMD   parse every file; tally primitive kinds; count anything skipped
  * TMD   winding check: for lit polygons, compare (v1-v0) x (v2-v0) with the
          authored normal (front faces are clockwise in Y-down TMD space, so
          the cross product should point AGAINST the normal)
  * RSD   link every model; where a TMD of the same name sits beside it, compare
          byte for byte with Sony's RSDLINK output (trying scales 1..64)
  * EXE   identify PS-X EXE / ECOFF / CPE files by magic and read their headers

Nothing is written. The data never enters this repository. Only the counts
are reported (the results are summarised in ref/formats/*.md).
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from . import exe, rsd, tim, tmd


def _files(paths):
    for root in paths:
        for dp, dirs, fs in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in fs:
                yield os.path.join(dp, f)


def run(paths: list[str]) -> dict:
    r = {"tim_ok": 0, "tim_fail": [], "tim_modes": Counter(), "tim_flags": Counter(),
         "tmd_ok": 0, "tmd_fail": [], "prims": Counter(), "skipped": Counter(),
         "wind_against": 0, "wind_with": 0, "wind_flat": 0,
         "rsd_ok": 0, "rsd_fail": [], "rsd_pairs": [], "exe": Counter(), "exe_fail": []}
    for p in _files(paths):
        ext = p.lower().rsplit(".", 1)[-1] if "." in os.path.basename(p) else ""
        try:
            with open(p, "rb") as f:
                head = f.read(8)
        except OSError:
            continue
        if ext == "tim":
            try:
                data = open(p, "rb").read()
                t = tim.read_tim(data)
                if t.pmode in (0, 1, 2, 3):
                    tim.tim_to_rgba(t)
                r["tim_ok"] += 1
                r["tim_modes"][tim.PMODE_NAMES[t.pmode]] += 1
                r["tim_flags"][f"0x{data[4]:02X}"] += 1
            except ValueError as e:
                r["tim_fail"].append((p, str(e)))
        elif ext == "tmd":
            try:
                m = tmd.read_tmd(open(p, "rb").read())
            except ValueError as e:
                r["tmd_fail"].append((p, str(e)))
                continue
            r["tmd_ok"] += 1
            for o in m.objects:
                for pr in o.primitives:
                    r["prims"][f"{pr.name} [0x{pr.mode:02X}/0x{pr.flag:X}]"] += 1
                    if pr.code == tmd.CODE_POLYGON and pr.normals and not pr.flag & tmd.LGT:
                        v = [o.vertices[i] for i in pr.vertices]
                        nrm = o.normals[pr.normals[0]]
                        a = [v[1][k] - v[0][k] for k in range(3)]
                        b = [v[2][k] - v[0][k] for k in range(3)]
                        c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
                        d = sum(c[k] * nrm[k] for k in range(3))
                        key = "wind_against" if d < 0 else "wind_with" if d > 0 else "wind_flat"
                        r[key] += 1
                for s in o.skipped:
                    r["skipped"][f"0x{s[0]:02X}/0x{s[1]:X}/ilen {s[2]}"] += 1
        elif ext == "rsd":
            try:
                model = rsd.read_rsd(p)
                rsd.link(model)
                r["rsd_ok"] += 1
            except (ValueError, OSError, KeyError, IndexError) as e:
                r["rsd_fail"].append((p, repr(e)))
                continue
            for cand in (p[:-4] + ".tmd", p[:-4] + ".TMD"):
                if os.path.exists(cand):
                    sony = open(cand, "rb").read()
                    match = next((s for s in (1, 2, 4, 8, 16, 32, 64) if rsd.rsd_to_tmd([p], s) == sony), None)
                    r["rsd_pairs"].append((p, match))
                    break
        if exe.identify(head) != "unknown":
            try:
                h = exe.read_executable(open(p, "rb").read())
                label = h["kind"]
                if h["kind"] == "ecoff":
                    label += " executable" if h["executable"] else " object"
                    if h.get("net_yaroze_app"):
                        label += " (Net Yaroze app)"
                r["exe"][label] += 1
            except ValueError as e:
                r["exe_fail"].append((p, str(e)))
    return r


def report(r: dict) -> str:
    out = []
    out.append(f"TIM: {r['tim_ok']} parsed, {len(r['tim_fail'])} rejected; modes {dict(r['tim_modes'])}; flag bytes {dict(r['tim_flags'])}")
    for p, e in r["tim_fail"]:
        out.append(f"  rejected {p}: {e}")
    total = sum(r["prims"].values())
    out.append(f"TMD: {r['tmd_ok']} parsed, {len(r['tmd_fail'])} rejected; {total} primitives in {len(r['prims'])} kinds; "
               f"{sum(r['skipped'].values())} skipped")
    for k, c in r["prims"].most_common():
        out.append(f"  {k:32s} {c}")
    for k, c in r["skipped"].items():
        out.append(f"  SKIPPED {k}: {c}")
    for p, e in r["tmd_fail"]:
        out.append(f"  rejected {p}: {e}")
    lit = r["wind_against"] + r["wind_with"] + r["wind_flat"]
    if lit:
        out.append(f"TMD winding (lit polygons): cross product against the normal {r['wind_against']} "
                   f"({100 * r['wind_against'] / lit:.1f}%), with it {r['wind_with']}, degenerate {r['wind_flat']}")
    out.append(f"RSD: {r['rsd_ok']} linked, {len(r['rsd_fail'])} failed")
    for p, s in r["rsd_pairs"]:
        out.append(f"  vs Sony RSDLINK: {'IDENTICAL at scale ' + str(s) if s else 'DIFFERENT'}  {p}")
    for p, e in r["rsd_fail"]:
        out.append(f"  failed {p}: {e}")
    out.append(f"Executables: {dict(r['exe'])}, {len(r['exe_fail'])} unreadable")
    for p, e in r["exe_fail"]:
        out.append(f"  unreadable {p}: {e}")
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m ref.tools.validate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    print(report(run(a.paths)))


if __name__ == "__main__":
    main()
