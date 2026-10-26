# Binary Analysis: Ghidra for PS1 executables

> **TL;DR**: `python -m decomp analyze GAME.EXE --out out/` runs
> [Ghidra](https://github.com/NationalSecurityAgency/ghidra) headless on a
> PlayStation executable (PS-X EXE, Net Yaroze ECOFF or Psy-Q CPE) with PS1
> knowledge applied: the full memory map, named hardware registers, the entry
> point and `$gp`, and **GTE instructions named in the output**. It decompiles every
> function to C (`out/all.c`, `out/c/*.c`) and indexes them in
> `out/functions.json`. For Net Yaroze programs you can also supply Sony's
> resident library, so calls into it are named and decompiled instead of
> left as gaps.

## How it works

```
GAME.EXE ──► decomp/image.py ──► flat memory image (base, bytes, entry, gp)
                │  PS-X EXE: body at t_addr, BSS appended
                │  ECOFF:    sections at their addresses (Net Yaroze a.out)
                │  CPE:      load chunks at their addresses
                ▼
         Ghidra analyzeHeadless  -loader BinaryLoader -processor MIPS:LE:32:default
                │
                ├─ PsxSetup.java   (pre-script, before auto-analysis)
                │    rest of 2 MB RAM, scratchpad, I/O, BIOS ROM as memory blocks
                │    names for 52 hardware registers (GPU_GP0, DMA2_GPU_CHCR, TIMER1_TARGET, …)
                │    entry point, and $gp so gp-relative data resolves
                │    optional: libps image + entry-point names (Net Yaroze)
                │
                ├─ Ghidra auto-analysis  (disassembly, functions, references, types)
                │
                └─ PsxExport.java  (post-script)
                     names every GTE command (cop2 0x0280030 → "GTE RTPT: …")
                     decompiles every function → all.c, c/<addr>_<name>.c
                     functions.json (name, address, size, GTE commands used), summary.json
```

**Why convert to a flat image first?** Ghidra has no built-in loader for
PS-X EXE, ECOFF-for-PS1 or CPE, but it can load raw bytes at an address
(`BinaryLoader`). The format work is done in Python, reusing `ref/tools/exe.py`,
which reads all 321 executables in Sony's Net Yaroze samples. Ghidra then gets
one simple, uniform input.

**Why name GTE commands?** Stock Ghidra disassembles a GTE command as a bare
`cop2 0x…` word, so a function full of 3D math is unreadable. The post-script
looks up the command number (see `ref/hardware/gte.md`) and writes a
pre-comment, which the decompiler prints in the C, such as:

```c
  /* GTE RTPT: rotate, translate, perspective-project V0..V2 */
```

## Usage

```bash
# Ghidra 11.x/12.x with JDK 21 installed locally:
export GHIDRA_INSTALL_DIR=/path/to/ghidra_12.1.4_PUBLIC
python -m decomp image   GAME.EXE                     # show the memory image layout
python -m decomp analyze GAME.EXE --out out/          # full analysis
python -m decomp analyze GAME.EXE --out out/ --dry-run   # print the Ghidra command only

# Or in Docker (Ghidra included):
docker compose run --rm decomp analyze /work/GAME.EXE --out /work/out    # files in ./work
```

### Net Yaroze programs and libps

A Net Yaroze program calls Sony's **libps**, which the boot disc leaves in RAM at
`0x80010000`–`0x8008FFFF`. That code is not in the program file. Without it:

* calls into libps are listed in `functions.json` as `"external": true` and are
  not decompiled (they would only decompile empty memory);
* with `--libps-symbols FILE`, they are at least **named**
  (`GsSortObject4(...)` instead of `FUN_80023e58(...)`);
* with `--libps FILE` (the resident library image, a PS-X EXE, optionally gzipped),
  libps is loaded as real code and decompiled along with the program.

This repository does **not** include libps or its symbol table, because both
come from Sony's library. [ChrisRx/psxsdk](https://github.com/ChrisRx/psxsdk)
carries them (`link/libps.exe.gz` and the TinyGo target's
`playstation-yaroze-symusr.S`), and `--psxsdk DIR` takes both from a checkout:

```bash
git clone --depth 1 https://github.com/ChrisRx/psxsdk
python -m decomp analyze tuto1 --out out/ --psxsdk psxsdk
```

PS-X EXEs converted by **yarexe** already contain libps (their header marker
reads `YAREXE …`), so they need nothing extra.

## Results on real programs

Measured in this repository's environment with Ghidra 12.1.4, on files from
[gwald/netyaroze_demo](https://github.com/gwald/netyaroze_demo):

| Input | Options | Functions decompiled | External | GTE instructions named | Time |
|-------|---------|----------------------|----------|------------------------|------|
| `demos/seventh/tuto1` (Net Yaroze ECOFF, 677 KB image) | none | 138 / 138 | 52 | 0 (the 3D math is in libps) | 22 s |
| same | `--libps-symbols` | 138 / 138 | 52, **named** (`GsSortObject4`, `GsClearOt`, …) | 0 | not timed |
| same | `--psxsdk` | **851 / 851** | 0 | **223** (RTPT 56, NCLIP 43, AVSZ3 25, …) | not timed |
| yarexe `psx.exe` (PS-X EXE, 1.2 MB, libps inside) | none, in Docker | **833 / 833** | 0 | **217** | 1 m 41 s |

With names, the decompiled main loop reads as the libgs frame loop
documented in [`ref/sdk/net-yaroze.md`](../ref/sdk/net-yaroze.md):

```c
  local_3c = GsGetActiveBuff();
  while (DAT_801591e0 == 0) {
    ...
    GsSetRefView2(&DAT_80179770);
    GsSetWorkBase(local_3c * 0xc000 + -0x7fea69b0);   /* double-buffered packet area */
    GsClearOt(0,0,&DAT_80171650 + local_3c * 5);
```

## Output files

| File | Contents |
|------|----------|
| `all.c` | Every function's decompiled C, in address order |
| `c/<address>_<name>.c` | One file per function |
| `functions.json` | `name`, `address`, `size`, `decompiled`, `external`, and `gte` (commands used and their counts) |
| `summary.json` | Totals, and GTE usage by command |
| `image.json`, `image.bin`, `symbols.tsv` | What Ghidra was given. Re-run or inspect by hand. |
| `ghidra.log` | Ghidra's full headless log |

The C is Ghidra's pseudo-C: a map for reading and understanding the program,
not source that recompiles. Turning it into buildable code is the job of the
pipeline's later stages.

## Tests

```bash
python -m unittest discover -s decomp/tests -t .                                     # unit tests
GHIDRA_INSTALL_DIR=/path/to/ghidra python -m unittest decomp.tests.test_decomp      # + real Ghidra
```

The integration test builds a five-instruction PS-X EXE by hand: a write to the GPU's
GP1 register, then a GTE `RTPT`. It checks that Ghidra's C names `GPU_GP1` and
includes the `GTE RTPT` comment.
