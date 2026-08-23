PSX Decomp Studio (Concept / WIP)

PSX Decomp Studio is an early‑stage Python application exploring automated decompilation and modernization of PlayStation 1 titles. The long‑term vision is a pipeline that takes a PSX disc image and outputs a structured, editable project suitable for rebuilding into a modern executable.

This repository is not complete and should be treated as a prototype.
Architecture Overview

The project is built around a modular pipeline:

    Image Intake  
    Accepts .chd, .iso, or .zip and extracts the PSX executable.

    Binary Analysis  
    Planned integration with Ghidra headless mode and PSX‑specific loaders.

    Decompilation Layer  
    Converts assembly into preliminary C/C++ sources.
    (Currently stubbed and incomplete.)

    Asset Extraction  
    Identifies textures, TIM files, audio banks, and other data.

    Modernization Hooks  
    Conceptual modules for:

        Resolution scaling

        Texture replacement

        Input remapping

        Runtime patches

    Output Project Generation  
    Creates a folder containing all reconstructed materials.

Current State

    Early scaffolding

    Partial extraction routines

    Incomplete output directory generation

    Placeholder modules for future tooling

    Known issues with dependency resolution

    Not capable of producing runnable builds

This project is actively unstable and intended for developers who want to help shape the direction.
Roadmap

    Replace placeholder modules with real toolchain integrations

    Implement Ghidra headless workflows

    Add PSX asset parsers

    Build a minimal modern runtime layer

    Create a reproducible build pipeline

    Document internal formats and memory maps

Community Involvement

The goal is to create a foundation others can extend.
If you’re interested in PSX reverse engineering, runtime rebuilding, or game modernization, contributions are welcome.
