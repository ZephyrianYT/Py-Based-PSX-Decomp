# How PS1 games built their worlds

> **TL;DR**: PS1 worlds were shaped by four limits: **2 MB of RAM**, a **~300 KB/s
> CD**, a budget of **a few thousand polygons per frame**, and **no Z-buffer**.
> Shipped games handled them with **grid- or room-based level structures**,
> **portals and precomputed visibility**, **fog or darkness** to cap draw distance,
> **LOD and billboards** for distant objects, **streaming** of level chunks from CD,
> **separate simple collision data**, **baked vertex-colour lighting**, and
> **camera design** that controlled what could be seen. A few games went further and
> **generated** levels or creatures from data at runtime. Most worlds were authored
> by hand, and this file explains the techniques. Algorithms you can run are in
> [`procedural-recipes.md`](procedural-recipes.md).

## The constraints [HW] [TYP]

| Limit | Value | Design consequence |
|-------|-------|--------------------|
| Main RAM | 2 MB for code, level data, animation and game state | Levels split into areas or chunks, compact integer formats |
| VRAM | 1 MB, about 700 KB after the framebuffers | Few unique textures per area, heavy tiling, CLUT reuse |
| SPU RAM | 512 KB | Per-level sound banks |
| CD throughput | ~150–300 KB/s, plus seek times of hundreds of ms | Load screens, or careful streaming with data laid out in read order |
| Polygons | roughly 1.5k–5k visible per frame at 30 fps | Visibility culling, fog, LOD, closed spaces |
| Sorting | One depth per polygon, painter's order | Level geometry subdivided, designed to avoid large overlaps |

## 1. Level structures

### Grid / sector levels [CASE]
**Tomb Raider (1996)** built its levels from rooms. Each room is a grid of
square **sectors** of 1024×1024 world units, and floor and ceiling heights move in
256-unit "clicks". Collision, floor height, triggers and portals are all stored
per sector. A grid makes collision trivial (look up the sector under the player)
and makes level geometry very regular. Regular geometry sorts and subdivides well.
The format is publicly documented by the TR modding community.

**Use it when** you want simple collision, editor-friendly levels, and a
recognisable "blocky" architecture.

### Rooms and portals [TYP] [CASE]
Rooms connect through **portals**, which are openings in their shared walls.
A room is drawn only if its portal projects inside the screen or inside an
already-visible portal. Tomb Raider's rooms are a well-known example. Portal
tests run per room, not per polygon, so they are cheap.

### Linear paths with precomputed visibility [CASE]
**Crash Bandicoot (1996)**: Naughty Dog's Andy Gavin has described how the
levels were corridors along a camera path. The team **precomputed, offline,
which polygons were visible and in what order** for positions along the path,
stored that data compressed, and **streamed** level data from CD as the player
advanced. That moved sorting and culling costs out of the runtime and allowed
far more detail than the hardware could otherwise sustain.

### Pre-rendered backgrounds with walkmeshes [CASE]
**Resident Evil 1–3** and **Final Fantasy VII–IX** used fixed cameras over
pre-rendered 2D backdrops. Occlusion came from foreground **mask** layers drawn
with a depth bucket. Navigation used an invisible **walkmesh** (FF7's field
walkmesh is a triangle mesh with per-triangle neighbour links), and camera zones
switched backdrops. Characters were the only real-time 3D on screen, so they
could use more polygons.

### Open areas with LOD [CASE]
**Spyro the Dragon (1998)** displayed unusually wide, open levels. Insomniac
used **low-detail versions of distant level geometry** and **vertex-coloured
sky geometry** (no sky textures). That gave long views without fog hiding
everything.

### Fog as a design tool [CASE]
**Silent Hill (1999)** used dense fog, and darkness lit by a flashlight, to keep
its draw distance short. That freed the budget for a free-roaming 3D town, and
the fog became the game's defining atmosphere. Many other games used **black
depth cue** in caves and at night for the same reason.

### Seamless streaming [CASE]
**Legacy of Kain: Soul Reaver (1999)** was noted for streaming its world with
almost no loading screens. Area data was loaded in the background as the player
moved between connected regions. This kind of design requires disc layout
planned in streaming order.

## 2. Visibility and culling pipeline [TYP]

```
per frame:
  1. Area / room selection      (portal graph, camera zone, or path position)
  2. Chunk culling              (bounding box vs frustum, and vs fog distance)
  3. LOD selection              (distance → mesh / billboard / nothing)
  4. Per-polygon transform      (GTE RTPT)
  5. Back-face cull             (GTE NCLIP)
  6. Near / size rejection      (SZ too small, or edge > 1023×511 → drop or subdivide)
  7. OT insert                  (GTE AVSZ3/4 → OT bucket, plus a per-object bias)
```

* Set the **fog end at or slightly before the cull distance**, so culled geometry
  is already fully fogged when it disappears.
* Use **separate OTs or OT ranges** for sky (drawn first), world,
  characters/effects, and HUD (drawn last). Sony's libgs supports this directly:
  `GsSortOt` merges a local OT into a global one at a chosen depth. [SDK]

## 3. Collision is separate from rendering [TYP]

The render mesh is rarely used for collision. Typical representations:

| Representation | Example usage |
|----------------|---------------|
| Per-sector floor and ceiling heights (+ slopes) | Grid levels (Tomb Raider-style) |
| Walkmesh triangles with neighbour links | Pre-rendered background games |
| Height grids for terrain | Racing and open-field games |
| Simple boxes and cylinders | Props, characters |

## 4. Lighting the world [TYP]

* **Bake** lighting offline into vertex colours, using painted or computed AO,
  light pools and shadows. The runtime cost is zero.
* Dynamic effects, such as muzzle flashes or explosions, briefly brighten
  nearby vertex colours or the GTE ambient colour.
* Characters use the GTE's 3 directional lights, sometimes chosen per area
  so they match the baked environment.

## 5. Skies and backgrounds [TYP]

* A solid **clear colour**, matching the fog colour.
* A **vertex-coloured dome** or box with a gradient. This needs no texture memory.
* A **scrolling 2D backdrop** drawn first. It works for distant mountains and
  cities.
* Draw the sky with no depth logic, either first in the OT or in its own pass.

## 6. Generated and data-driven worlds on PS1 [CASE]

Procedural generation was uncommon but did exist:

| Game | What was generated |
|------|--------------------|
| **Vib-Ribbon (1999)** | Obstacle courses generated from the music on any audio CD the player inserted |
| **Monster Rancher (1997)** | Monsters generated from data read from any CD the player inserted |
| **Azure Dreams (1997)** | Randomly generated tower floors |
| **Chocobo's Mysterious Dungeon (1997)** | Randomly generated dungeon floors (roguelike) |
| **Diablo (PS1 port, 1998)** | Randomly generated dungeon levels |

These games show the typical approach: generate a **coarse grid** at runtime,
then build it from **pre-made tile pieces** (wall, floor and corner meshes and
textures). That keeps geometry and textures within budget and predictable. The
recipes in [`procedural-recipes.md`](procedural-recipes.md) follow the same approach.

## Typical RAM split for one area [TYP]

These are illustrative proportions, and real games vary a great deal:

| Item | Approx. share of 2 MB |
|------|-----------------------|
| Code (engine + game) + libraries | 25–45 % |
| Level geometry + collision | 15–30 % |
| Character models + animation | 10–25 % |
| Packet buffers + OTs (×2 for double buffering) | 5–15 % |
| Game state, stacks, sound/streaming buffers | 5–15 % |

The packet buffer is double-buffered: one frame's GPU packets are built while the
previous frame's are being drawn. A primitive costs 20–52 bytes per frame, from an
F3 (4 words + tag) to a GT4 (12 words + tag),
so a 4,000-polygon scene needs roughly 100–200 KB per buffer.
