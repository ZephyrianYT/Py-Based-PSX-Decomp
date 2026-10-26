# PSX Decomp Studio (Concept / WIP)

PSX Decomp Studio is an early-stage Python project exploring automated
decompilation and modernization of PlayStation 1 titles. The long-term vision
is a pipeline that takes a PSX disc image and outputs a structured, editable
project suitable for rebuilding into a modern executable.

The repository currently has two parts:

| Part | Status | What it is |
|------|--------|------------|
| **[`ref/`: PSX Reference Library](ref/README.md)** | **Working, tested** | A reference on how PS1 games *look*, how their *models and textures* are stored, and how their *worlds* were built. It is written for people and for AI agents, and comes with runnable, commented Python tools. |
| **Decomp Studio pipeline** | Concept / planned | The disc-to-project pipeline described in [Decomp Studio pipeline](#decomp-studio-pipeline) below. |

> This repository is not complete and should be treated as a prototype.

---

## Contents

- [Why this exists](#why-this-exists)
- [Quick start](#quick-start)
- [Running in a container](#running-in-a-container)
- [How it works](#how-it-works)
  - [The PS1 frame, step by step](#the-ps1-frame-step-by-step)
  - [How `ref/` is organised](#how-ref-is-organised)
  - [How an AI agent uses it](#how-an-ai-agent-uses-it)
  - [Design principles](#design-principles)
- [Gallery](#gallery)
- [Learning path](#learning-path)
- [Repository layout](#repository-layout)
- [Decomp Studio pipeline](#decomp-studio-pipeline)
- [Contributing](#contributing)
- [Legal](#legal)

---

## Why this exists

**Decompiling and modernising PS1 games needs ground truth.** Before a tool can
extract a model, re-render a level, or explain why a game looks the way it does,
someone has to pin down the facts: how the GPU draws, how the GTE does its
fixed-point math, what is inside a TIM or TMD file. Those facts are scattered
across hardware wikis, SDK manuals and emulator source code.

**AI assistants get PS1 details wrong in predictable ways.** They claim the PS1
had a Z-buffer, perspective-correct texturing or bilinear filtering (it had
none of these), invent polygon counts, or blur hardware fact into folklore.
`ref/` gives them one curated place to look. Every statement is tagged with how
far it can be trusted, and every claim that can be demonstrated *is*
demonstrated, with code you can run.

**The PS1 look is best learned by seeing its causes.** "Wobbly textures" and
"jittery polygons" are not arbitrary style. They follow directly from specific
hardware limits. The tools here reproduce each limit on its own, so you can
switch it off and see the difference:

![Affine texture warping vs perspective-correct](ref/look/images/affine_vs_perspective.png)
*Left: PS1 rules (affine UVs, integer vertices, dither). Right: the same scene on a modern renderer.*

Who it is for:

- **Decompilation and modding work**: format specs, a TIM scanner, a TMD parser
  that refuses to misread unknown data, an executable header reference.
- **AI agents**: a tagged, indexed, test-checked knowledge base (`ref/AGENTS.md`, `ref/index.json`).
- **Game developers recreating the style**: shader recipes, drop-in GLSL, asset budgets.
- **Students and the curious**: heavily commented code that you can step through.

---

## Quick start

Requires **Python 3.9+**. There is nothing to install, because the tools use only the
standard library. Run everything from the repository root.

```bash
python -m ref                      # list commands
python -m ref docs                 # list every reference document with a one-line summary
python -m ref test                 # run the 35 self-tests
python -m ref demo --out ref_out   # render the comparison images into ./ref_out
python -m ref jitter               # print the vertex-jitter table (GTE integer math)
python -m ref worldgen terrain --out ref_out/terrain.obj --png ref_out/terrain.png
python -m ref worldgen dungeon --out ref_out/dungeon.obj --png ref_out/dungeon.png
python -m ref tim info  path/to/file.tim
python -m ref tim png   path/to/file.tim out.png
python -m ref tim scan  path/to/archive.bin     # find TIMs embedded in any file
python -m ref tmd info  path/to/model.tmd
python -m ref tmd obj   path/to/model.tmd --out model.obj
```

The generated `.obj` files carry per-vertex colours and open in Blender or MeshLab.

---

## Running in a container

The repository ships a `Dockerfile` and a `docker-compose.yml`. The image is
`python:3.12-slim` plus the `ref/` folder. It runs as a non-root user, needs no
network access, and writes its outputs to `/out`.

```bash
# Build once
docker build -t psx-ref .

# Run any command (same commands as `python -m ref ...`)
docker run --rm psx-ref                 # help
docker run --rm psx-ref test            # self-tests
docker run --rm psx-ref jitter

# Write files to ./ref_out on your machine, owned by you
mkdir -p ref_out
docker run --rm -v "$PWD/ref_out:/out" --user "$(id -u):$(id -g)" psx-ref demo --out /out
```

With Compose:

```bash
docker compose run --rm test       # self-tests
docker compose run --rm demo       # comparison images  -> ./ref_out
docker compose run --rm terrain    # terrain OBJ + PNG   -> ./ref_out
docker compose run --rm dungeon    # dungeon OBJ + PNG   -> ./ref_out
docker compose run --rm tools tmd info /out/model.tmd   # anything else
```

Why containerise a stdlib-only tool? It gives a **pinned, reproducible
environment**: the same Python, the same output bytes on every machine (the
container's renders are byte-identical to a local run). It also gives a
**sandbox** for running the scanners over untrusted files extracted from discs.

---

## How it works

### The PS1 frame, step by step

The PS1 draws a 3D frame in a fixed sequence of steps. Each step has a
hardware limit, and each limit leaves a visible fingerprint. `ref/` is
organised around this sequence: every stage has a document that explains it
and a function that simulates it.

```
  CPU + GTE (geometry)                         GPU (pixels)
 ┌──────────────────────────────────┐        ┌──────────────────────────────────┐
 │ 1 transform vertices (fixed pt)  │        │ 5 fill triangle (integer edges)  │
 │ 2 project to INTEGER screen x,y  │──DMA──►│ 6 texture: AFFINE u,v, nearest   │
 │ 3 cull back faces (NCLIP)        │ linked │ 7 shade: Gouraud, texel*col/128  │
 │ 4 sort: one depth per polygon    │  list  │ 8 write 15-bit pixel + DITHER    │
 │   into an ORDERING TABLE         │        │   (no Z-buffer, no filtering)    │
 └──────────────────────────────────┘        └──────────────────────────────────┘
```

| Step | Hardware limit | What you see | Explained in | Simulated by |
|------|----------------|--------------|--------------|--------------|
| 1 | No FPU: 1.3.12 fixed-point matrices | Slight model distortion and drift | [`hardware/gte.md`](ref/hardware/gte.md) | `fixedpoint.rot_matrix_xyz`, `mat_mul` |
| 2 | Integer screen coordinates, 17-bit divide | **Vertex jitter / wobble** | [`hardware/gte.md`](ref/hardware/gte.md) | `fixedpoint.rtps` |
| 2 | Divide saturates near the camera, no clipping | **Polygons vanish or stretch up close** | [`look/visual-signature.md`](ref/look/visual-signature.md) | `raster.render_mesh` (near test) |
| 3 | Culling on rounded coordinates | Thin triangles flicker | [`hardware/gte.md`](ref/hardware/gte.md) | `fixedpoint.nclip` |
| 4 | No Z-buffer, one depth per polygon | **Sorting errors / popping** | [`look/visual-signature.md`](ref/look/visual-signature.md) | `raster.OrderingTable`, `fixedpoint.avsz3` |
| 5 | Max polygon 1023×511 px | Big polygons drop out | [`hardware/gpu.md`](ref/hardware/gpu.md) | `raster.draw_triangle` (size limit) |
| 6 | No per-pixel divide | **Affine texture warping** | [`hardware/gpu.md`](ref/hardware/gpu.md) | `raster.draw_triangle` (`affine=True`) |
| 6 | No filtering, no mipmaps, 1 MB VRAM | **Crunchy, shimmering, low-res textures** | [`hardware/gpu.md`](ref/hardware/gpu.md) | `raster.Texture.fetch` |
| 7 | Per-vertex lighting only | Soft Gouraud light, baked vertex colour | [`models/modeling-guide.md`](ref/models/modeling-guide.md) | `raster.draw_triangle` (modulation) |
| 7 | Fog computed per vertex by the GTE | **Distance fog**, uneven on big polygons | [`hardware/gte.md`](ref/hardware/gte.md) | `fixedpoint.depth_cue` |
| 8 | 5 bits per colour channel | **Banding + 4×4 dither grain** | [`hardware/gpu.md`](ref/hardware/gpu.md) | `raster.dither_to_15bit` |

Every simulation can be switched to "modern" behaviour (`affine=False`,
`sort="zbuffer"`, `psx=False`, `dither=False`). Rendering the same scene both
ways is how the comparison images in [`ref/look/images/`](ref/look/images/README.md)
were made.

### How `ref/` is organised

```
ref/
├── AGENTS.md, index.json   ← how to look things up (for bots and people)
├── hardware/               ← what the console can and cannot do
├── look/                   ← what that looks like, and how to reproduce it
├── models/                 ← how characters and props were built
├── formats/                ← byte-level file formats (TIM, TMD, EXE, disc)
├── world/                  ← how levels were built and how to generate them
├── tools/                  ← runnable, commented Python models of all of the above
└── tests/                  ← keeps docs, index and tools consistent
```

- **Docs** each open with a **TL;DR** and tag their claims: `[HW]` hardware
  fact, `[FMT]` file-format fact, `[TYP]` typical practice, `[CASE]` a
  documented technique from a specific game, `[SIM]` this repo's simulation.
- **Tools** are plain Python with no dependencies. Each is written to be read:
  the code is annotated with *why* each line behaves as the hardware does.
- **Tests** check the tools (round-trips, the dither table, fill rules, culling,
  sorting order, generator connectivity). They also check the **library
  itself**: every Markdown file must be registered in `index.json`, every
  relative link must resolve, and every doc must have a TL;DR. A bot can rely
  on the index never pointing at a missing file.

### How an AI agent uses it

```
question ──► ref/index.json (match tags) ──► doc TL;DR ──► doc body / tables
                                                   │
                                                   └──► run ref/tools/* to demonstrate or verify
```

[`ref/AGENTS.md`](ref/AGENTS.md) spells out the rules: quote numbers from the
tables rather than from memory, respect the confidence tags, never claim the PS1
had features it lacked, and cite as `ref/<file> § <heading>`.

### Design principles

1. **Explain the cause, not just the effect.** Every artifact is traced to
   a specific hardware limit.
2. **Show, don't assert.** If a claim can be demonstrated, there is code that
   demonstrates it.
3. **Be honest about certainty.** Hardware facts, typical practice and game
   anecdotes are labelled differently. Budgets are marked approximate.
4. **No copyrighted material.** Every image, texture and model here is
   generated from scratch.
5. **Zero dependencies.** Standard-library Python only, so the tools run
   anywhere: a laptop, a CI runner, a container, an agent sandbox.
6. **Simulations are labelled as such.** `ref/tools/raster.py` reproduces the
   *visible* behaviour, not the hardware cycle for cycle. Use an accurate
   emulator (DuckStation, Mednafen/Beetle PSX) for ground truth.

---

## Gallery

All rendered by `ref/tools` at 320×240 and upscaled with nearest-neighbour filtering.
Left = PS1 rules, right = modern.

| | |
|---|---|
| ![dither](ref/look/images/dither_vs_none.png) **Dither vs banding**: 15-bit colour with and without the 4×4 dither | ![sorting](ref/look/images/sorting_ot_vs_zbuffer.png) **Sorting error**: the floor's single average depth puts it in front of the cube |
| ![fog](ref/look/images/fog_depthcue.png) **Depth-cue fog**: per-vertex fade vs none | ![jitter](ref/look/images/jitter_chart.png) **Jitter**: integer screen X (cyan) vs float (orange) |
| ![terrain](ref/look/images/worldgen_terrain.png) **Generated terrain**: baked vertex colour, fog, dither | ![dungeon](ref/look/images/worldgen_dungeon.png) **Generated dungeon**: torch light baked into black fog |

---

## Learning path

A suggested order for learning from the folder. Each step pairs reading with
something to run.

| # | Read | Then run / open | You will understand |
|---|------|-----------------|---------------------|
| 1 | [`ref/hardware/overview.md`](ref/hardware/overview.md) | | What is inside the console and how a frame is built |
| 2 | [`ref/look/visual-signature.md`](ref/look/visual-signature.md) | `ref/look/images/` | The 16 tell-tale artifacts and their causes |
| 3 | [`ref/hardware/gte.md`](ref/hardware/gte.md) | `python -m ref jitter`, then read `ref/tools/fixedpoint.py` | Fixed-point math and why vertices jitter |
| 4 | [`ref/hardware/gpu.md`](ref/hardware/gpu.md) | Read `ref/tools/raster.py` top to bottom | Rasterising, affine mapping, dithering, ordering tables |
| 5 | [`ref/formats/tim.md`](ref/formats/tim.md), [`tmd.md`](ref/formats/tmd.md) | `ref/tools/tim.py`, `ref/tools/tmd.py`, and the round-trip tests in `ref/tests/test_tools.py` | How textures and models sit in files and VRAM |
| 6 | [`ref/models/modeling-guide.md`](ref/models/modeling-guide.md) | Model something in Blender to the budgets | How to build PS1-style assets |
| 7 | [`ref/world/world-building.md`](ref/world/world-building.md), [`procedural-recipes.md`](ref/world/procedural-recipes.md) | `python -m ref worldgen dungeon --out d.obj --png d.png`, then read `ref/tools/worldgen.py` | How worlds were structured, and how to generate one |
| 8 | [`ref/look/recreating-the-look.md`](ref/look/recreating-the-look.md) | `ref/look/shaders/*.glsl` | Bringing it all into a modern engine |

Exercises to try: change `RenderSettings(affine=False)` in a demo scene and
compare; set `subdiv=1` in the dungeon generator and look for near-plane holes;
swap the CLUT index when decoding a TIM to make a palette-swapped variant.

---

## Repository layout

```
.
├── README.md               this file
├── Dockerfile              reproducible runtime for the ref/ tools
├── docker-compose.yml      test / demo / terrain / dungeon shortcuts
├── .dockerignore
└── ref/
    ├── __main__.py         `python -m ref <command>` entry point (also the container entry point)
    ├── README.md           map of the library
    ├── AGENTS.md           rules for AI agents
    ├── index.json          machine-readable manifest
    ├── glossary.md, sources.md
    ├── hardware/           overview.md, gpu.md, gte.md
    ├── look/               visual-signature.md, recreating-the-look.md, shaders/, images/
    ├── models/             modeling-guide.md
    ├── formats/            tim.md, tmd.md, exe-and-disc.md
    ├── world/              world-building.md, procedural-recipes.md
    ├── tools/              fixedpoint, raster, tim, tmd, worldgen, pngio, demo
    └── tests/              test_tools.py, test_index.py
```

---

## Decomp Studio pipeline

The pipeline below is the planned architecture of the wider project. The
working, tested part of this repository today is `ref/`. Its format specs and
parsers (TIM, TMD, PS-X EXE, disc sectors) are the groundwork for the
**Image Intake** and **Asset Extraction** stages.

```
disc image ──► Image Intake ──► Binary Analysis ──► Decompilation ──► Modernization ──► Output Project
                    │                                                     Hooks
                    └──────────► Asset Extraction ───────────────────────────────────────────┘
```

**Image Intake**: accepts `.chd`, `.iso`, or `.zip` and extracts the PSX
executable. (See [`ref/formats/exe-and-disc.md`](ref/formats/exe-and-disc.md)
for sector layouts, `SYSTEM.CNF` and the PS-X EXE header.)

**Binary Analysis**: planned integration with Ghidra headless mode and
PSX-specific loaders.

**Decompilation Layer**: converts assembly into preliminary C/C++ sources.
(Currently stubbed and incomplete.)

**Asset Extraction**: identifies textures, TIM files, audio banks, and other
data. (Reference parsers: `ref/tools/tim.py` including `scan`, and `ref/tools/tmd.py`.)

**Modernization Hooks**: conceptual modules for resolution scaling, texture
replacement, input remapping, and runtime patches. (See
[`ref/look/recreating-the-look.md`](ref/look/recreating-the-look.md) for what
must be preserved or deliberately changed.)

**Output Project Generation**: creates a folder containing all reconstructed materials.

### Current state

- Early scaffolding
- Partial extraction routines
- Incomplete output directory generation
- Placeholder modules for future tooling
- Known issues with dependency resolution
- Not capable of producing runnable builds

This project is actively unstable and intended for developers who want to help
shape the direction.

### Roadmap

- [ ] Replace placeholder modules with real toolchain integrations
- [ ] Implement Ghidra headless workflows
- [ ] Add PSX asset parsers (*started: TIM and TMD in `ref/tools/`*)
- [ ] Build a minimal modern runtime layer
- [ ] Create a reproducible build pipeline (*started: `Dockerfile`*)
- [ ] Document internal formats and memory maps (*started: `ref/hardware/`, `ref/formats/`*)

---

## Contributing

The goal is to create a foundation others can extend. If you're interested in
PSX reverse engineering, runtime rebuilding, or game modernization,
contributions are welcome.

For `ref/` specifically:

1. Put new docs in the matching subfolder, start them with a `**TL;DR**`
   block, and tag claims (`[HW]`, `[FMT]`, `[TYP]`, `[CASE]`, `[SIM]`).
2. Register every new file in `ref/index.json`. The tests fail otherwise.
3. Keep tools standard-library only, comment them for learners, and add a test.
4. Run `python -m ref test` (or `docker compose run --rm test`) before opening a PR.
5. Never add copyrighted game assets or decompiled game code. Generate samples instead.

---

## Legal

PlayStation is a trademark of Sony Interactive Entertainment. This project is
not affiliated with or endorsed by Sony. It contains no Sony code, no BIOS, and
no game data. All documentation is original writing that summarises publicly
available technical information (see [`ref/sources.md`](ref/sources.md)), and
all images and samples are generated by the code in this repository.
