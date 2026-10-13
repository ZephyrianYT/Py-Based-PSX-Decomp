# PSX Decomp Studio (Concept / WIP)

PSX Decomp Studio (developed in the `Py-Based-PSX-Decomp` repository) is an early-stage Python application exploring automated decompilation and modernization of PlayStation 1 titles. The long-term vision is a pipeline that takes a PSX disc image and outputs a structured, editable project suitable for rebuilding into a modern executable.

This repository is not complete and should be treated as a prototype.

## Architecture Overview

The project is designed around a modular pipeline. All stages below are planned; none are usable yet.

- **Image Intake** – Planned to accept `.chd`, `.iso`, or `.zip` and extract the PSX executable.
- **Binary Analysis** – Planned integration with Ghidra headless mode and PSX-specific loaders.
- **Decompilation Layer** – Planned to convert assembly into preliminary C/C++ sources.
- **Asset Extraction** – Planned to identify textures, TIM files, audio banks, and other data.
- **Modernization Hooks** – Conceptual modules for:
  - Resolution scaling
  - Texture replacement
  - Input remapping
  - Runtime patches
- **Output Project Generation** – Planned to create a folder containing all reconstructed materials.

## Current State

No source code has been published to this repository yet. Work in progress, not yet published here:

- Early scaffolding
- Partial extraction routines
- Incomplete output directory generation
- Placeholder modules for future tooling
- Known issues with dependency resolution

The project is not capable of producing runnable builds. It is actively unstable and intended for developers who want to help shape the direction.

## Roadmap

- Replace placeholder modules with real toolchain integrations
- Implement Ghidra headless workflows
- Add PSX asset parsers
- Build a minimal modern runtime layer
- Create a reproducible build pipeline
- Document internal formats and memory maps

## Community Involvement

The goal is to create a foundation others can extend. If you're interested in PSX reverse engineering, runtime rebuilding, or game modernization, contributions are welcome.

- Open an issue to discuss ideas or report problems before starting larger changes.
- Setup instructions will be added once the first code is published.
- A license has not been chosen yet; until one is added, please ask in an issue before contributing code.
