# PSX Reference Library (`ref/`)

A self-contained reference on how the original Sony PlayStation (PSX / PS1)
**looks**, how its **models** are built and stored, and how its **worlds** were
constructed. It is written so that both people and AI agents can point at
a single file and get accurate, citable facts. Where a fact matters, there is
also a runnable Python demonstration.

> Agents: read [`AGENTS.md`](AGENTS.md) first. It explains the lookup order,
> how confident each kind of statement is, and how to cite this folder.
> A machine-readable manifest is in [`index.json`](index.json).

## Map

| Area | File | What it answers |
|------|------|-----------------|
| Hardware | [`hardware/overview.md`](hardware/overview.md) | CPU, RAM sizes, memory map, DMA, the frame pipeline |
| Hardware | [`hardware/gpu.md`](hardware/gpu.md) | VRAM layout, primitives, texture pages, CLUTs, blending, dithering, limits |
| Hardware | [`hardware/gte.md`](hardware/gte.md) | Fixed-point 3D math, projection, depth cueing (fog), lighting |
| Look | [`look/visual-signature.md`](look/visual-signature.md) | Every visual artifact that makes PS1 graphics recognisable, and the hardware cause of each |
| Look | [`look/recreating-the-look.md`](look/recreating-the-look.md) | How to reproduce the look in modern engines (shader recipes) |
| Look | [`look/shaders/`](look/shaders/) | Drop-in GLSL vertex and fragment shaders |
| Look | [`look/images/`](look/images/README.md) | Generated before/after images of each artifact (affine, dither, jitter, sorting, fog, world previews) |
| Models | [`models/modeling-guide.md`](models/modeling-guide.md) | Polygon and texture budgets, topology, vertex colour, rigid-segment animation |
| Formats | [`formats/tmd.md`](formats/tmd.md) | TMD 3D model file format, byte by byte |
| Formats | [`formats/tim.md`](formats/tim.md) | TIM texture/image file format, byte by byte |
| Formats | [`formats/rsd.md`](formats/rsd.md) | RSD/PLY/MAT/GRP, Sony's text model source, and how RSDLINK linked it |
| Formats | [`formats/exe-and-disc.md`](formats/exe-and-disc.md) | PS-X EXE header (Sony's EXEC fields), ECOFF and CPE executables, SYSTEM.CNF, CD sector modes, other asset formats |
| SDK | [`sdk/net-yaroze.md`](sdk/net-yaroze.md) | Net Yaroze: toolchain, memory map, the official libgs frame loop, FAQ limits, recognising Yaroze programs |
| World | [`world/world-building.md`](world/world-building.md) | How shipped games built and streamed worlds (grids, rooms, portals, fog, LOD, pre-rendered backgrounds) |
| World | [`world/procedural-recipes.md`](world/procedural-recipes.md) | Step-by-step algorithms for generating PS1-style worlds |
| Support | [`glossary.md`](glossary.md) | Short definitions of every term used here |
| Support | [`sources.md`](sources.md) | Where the facts come from, and how far to trust each source |

## Runnable tools (`ref/tools/`)

Python 3.9+ standard library only: no NumPy and no Pillow.

| Module | Purpose |
|--------|---------|
| `tools/fixedpoint.py` | GTE-style fixed-point math: 1.3.12 matrices, RTPS-like projection, NCLIP, AVSZ3, depth cue |
| `tools/raster.py` | A small software rasteriser that follows PS1 rules: integer vertices, affine UVs, no Z-buffer, ordering table, 15-bit colour plus 4x4 dither |
| `tools/tim.py` | Read and write TIM files, and convert them to RGBA and PNG |
| `tools/tmd.py` | Read and write TMD files (polygons, lines, 3D sprites), and export them to OBJ |
| `tools/rsd.py` | Read RSD/PLY/MAT/GRP and link them to TMD, byte-identical to Sony's RSDLINK on the samples |
| `tools/exe.py` | Identify PS-X EXE / ECOFF / CPE executables. Entry point, load address, sections. |
| `tools/validate.py` | Run every parser over a folder of real PS1-era files and report the results |
| `tools/worldgen.py` | PS1-style world generators: tile terrain with baked vertex colour, and a grid dungeon |
| `tools/pngio.py` | Minimal PNG writer (zlib only) |
| `tools/demo.py` | Renders the side-by-side comparison images |
| `__main__.py` | `python -m ref <command>`: one entry point for every tool (also the container entry point) |

```bash
# from the repository root
python -m ref                                   # list commands (ref/__main__.py)
python -m ref demo --out ref_out                # render the comparison PNGs
python -m ref worldgen terrain --out ref_out/terrain.obj --png ref_out/terrain.png
python -m ref worldgen dungeon --out ref_out/dungeon.obj
python -m ref tim info path/to/file.tim
python -m ref tmd obj path/to/model.tmd --out model.obj
python -m ref rsd tmd MODEL.RSD -o MODEL.TMD     # link Sony RSD text models
python -m ref exe info path/to/program           # PS-X EXE / ECOFF / CPE
python -m ref validate path/to/netyaroze_demo    # check every parser on real files
python -m ref test                              # self-tests
```

The same commands run in the container. See the root README, section
"Running in a container":

```bash
docker build -t psx-ref .
docker run --rm psx-ref test
docker run --rm -v "$PWD/ref_out:/out" --user "$(id -u):$(id -g)" psx-ref demo --out /out
```

Every tool module is commented for learners. Read `tools/raster.py` top to
bottom for a guided tour of the PS1 rendering pipeline.

## Validated against real data

The format tools were run over Sony's Net Yaroze samples
(`github.com/gwald/netyaroze_demo`, not copied here) with
`python -m ref validate PATH`:

| Check | Result |
|-------|--------|
| TIM | 556 / 556 parsed and decoded |
| TMD | 245 parsed, ~77,000 primitives in 15 kinds, **0 skipped**. The 4 rejected files are truncated RAM dumps. |
| TMD winding | 96% of lit polygons follow the clockwise-front rule. This exposed and fixed an inside-out OBJ export. |
| RSD | 19 / 19 linked. **4 / 4 byte-identical** to Sony's RSDLINK output. |
| Executables | 321 / 321 read: 218 Yaroze ECOFF programs, 91 objects, 10 PS-X EXEs, 2 CPE |

## Scope and honesty

* **Hardware behaviour and file formats** are documented facts from the
  community hardware spec (nocash *psx-spx*) and Sony's own SDK
  documentation. See [`sources.md`](sources.md).
* **Art budgets** (polygon counts, texture counts) are *typical ranges*,
  not hard limits, and are marked as approximate.
* **Game case studies** describe techniques that developers or long-standing
  community research have publicly documented. They are summaries and do not
  claim to show any game's actual code.
* The Python tools are **educational models**. They reproduce the visible
  behaviour, not the hardware cycle for cycle. Use an accurate emulator
  (DuckStation, Mednafen/Beetle PSX) for ground truth.
* No copyrighted game data is included. All sample assets are generated.
