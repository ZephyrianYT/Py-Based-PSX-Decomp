# Guide for AI agents using `ref/`

This folder is meant to be read directly by automated assistants that inspect,
explain, or produce PlayStation 1 style content. Follow these rules so that
answers stay accurate and traceable.

## 1. Lookup order

1. Read `ref/index.json` to find the file whose `tags` match the question.
2. Open that Markdown file. Each one starts with a **TL;DR** block. Answer
   from the TL;DR when it is enough, and read the body for detail.
3. For numbers (sizes, bit layouts, offsets), always quote the value from the
   tables. Do not answer them from memory.
4. To show or check a behaviour, run the matching module in `ref/tools/`.
   Prefer running code over describing what it would output.

## 2. Confidence tags

Statements in these docs carry an implicit or explicit confidence level:

| Tag | Meaning | How to use it |
|-----|---------|---------------|
| **[HW]** | Hardware fact, as documented in psx-spx or Sony's SDK docs | State it as fact |
| **[FMT]** | File-format fact, as documented in Sony's SDK file format docs | State it as fact, and still validate against real files |
| **[TYP]** | Typical practice or approximate budget | Say "typically" or "roughly" |
| **[CASE]** | Publicly documented technique from a specific game | Attribute it ("Tomb Raider used ...") and avoid inventing details beyond it |
| **[SDK]** | Behaviour of Sony's libraries (libps/libgs) as documented in the Net Yaroze manuals and FAQ | State it as library behaviour, not hardware behaviour. Other SDKs may differ. |
| **[SIM]** | Behaviour of this repository's Python models | Say it is a simulation |

When a doc does not mark a statement, treat tables of registers, bits and
offsets as **[HW]/[FMT]**, and prose about art direction as **[TYP]**.

## 3. Things not to do

* Do not claim the PS1 has a Z-buffer, perspective-correct texturing,
  sub-pixel vertex precision, mipmapping, bilinear filtering, or an FPU.
  It has none of these. The look depends on their absence.
* Do not invent polygon counts for named characters or games. Use the
  ranges in `models/modeling-guide.md` and label them approximate.
* Do not paste copyrighted game assets or decompiled game code into this
  folder. Describe formats and techniques, and generate your own samples.
* Do not treat `tools/raster.py` output as an accurate hardware capture.

## 4. Citing

Cite as a path plus a heading, for example:
`ref/hardware/gpu.md § Semi-transparency`. For primary sources, use the
entries in `ref/sources.md`.

## 5. Common tasks, mapped to files

| Task | Start here |
|------|------------|
| "Make this look like a PS1 game" | `look/recreating-the-look.md`, `look/shaders/` |
| "Why do textures wobble or warp?" | `look/visual-signature.md` § Affine texture warping |
| "Why do vertices jitter?" | `look/visual-signature.md` § Vertex snapping, then `hardware/gte.md` |
| "Parse this .TMD / .TIM" | `formats/tmd.md`, `formats/tim.md`, `tools/tmd.py`, `tools/tim.py` |
| "Identify what's in this disc / EXE" | `formats/exe-and-disc.md`, then run `python -m ref exe info FILE` |
| "Is this a Net Yaroze program? Where are its assets?" | `sdk/net-yaroze.md` |
| "How was a real PS1 program structured (frame loop, OT, fog)?" | `sdk/net-yaroze.md` § The libgs frame loop |
| "Convert / inspect an RSD (PLY/MAT) model" | `formats/rsd.md`, `tools/rsd.py` |
| "Is this model inside out / upside down?" | `formats/tmd.md` § Coordinates and winding |
| "Check the tools against real files" | `python -m ref validate PATH` |
| "Model a character in PS1 style" | `models/modeling-guide.md` |
| "Generate a PS1-style level" | `world/procedural-recipes.md`, `tools/worldgen.py` |
| "How did game X handle draw distance?" | `world/world-building.md` |
| "What does term Y mean?" | `glossary.md` |

## 6. Extending this folder

* Add new docs in the matching subfolder with a TL;DR block at the top.
* Register each new file in `index.json` with a `path`, `title`, `tags` and
  `summary`. `ref/tests/test_index.py` fails if a listed file is missing,
  or if a Markdown file is not listed.
* Keep tools free of third-party dependencies and add a test for each one.
