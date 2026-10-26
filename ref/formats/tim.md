# TIM: PlayStation image / texture format

> **TL;DR**: A TIM file is a VRAM upload packaged as a file. It has an 8-byte
> header (`ID = 0x00000010`, then flags giving the pixel mode and whether a CLUT is
> present), an optional **CLUT block**, and an **image block**. Each block stores
> its own **VRAM destination rectangle**, measured in 16-bit units. Pixel modes
> are 4-bit CLUT, 8-bit CLUT, 15-bit direct, 24-bit, and mixed. All values are
> little-endian. Parser: `ref/tools/tim.py`.

## Layout [FMT]

```
offset  size  field
0x00    u32   ID      = 0x00000010
0x04    u32   FLAGS   bits 0-2: PMODE, bit 3: CF (CLUT present)
                     PMODE 0 = 4-bit CLUT, 1 = 8-bit CLUT, 2 = 15-bit direct,
                           3 = 24-bit, 4 = mixed
--- CLUT block (only if CF = 1) ---
+0x00   u32   BNUM    length of this block in bytes, including these 12 header bytes
+0x04   u16   DX      VRAM x of the palette (halfwords; multiple of 16)
+0x06   u16   DY      VRAM y
+0x08   u16   W       palette width in entries (16 for 4-bit, 256 for 8-bit)
+0x0A   u16   H       number of palettes (rows)
+0x0C   u16[W*H]      15-bit colours (see below)
--- Image block ---
+0x00   u32   BNUM    length of this block in bytes, including 12 header bytes
+0x04   u16   DX      VRAM x (halfwords)
+0x06   u16   DY      VRAM y
+0x08   u16   W       width in **halfwords**
+0x0A   u16   H       height in pixels
+0x0C   u16[W*H]      pixel data
```

### Width in halfwords versus pixels [FMT]

| PMODE | Pixels per halfword | Pixel width |
|-------|---------------------|-------------|
| 0 (4-bit) | 4 | `W × 4` (the **low nibble is the left pixel**) |
| 1 (8-bit) | 2 | `W × 2` (the low byte is the left pixel) |
| 2 (15-bit) | 1 | `W` |
| 3 (24-bit) | 2/3 | `W × 2 / 3` (bytes `R, G, B` packed across halfwords) |

### Colour word [HW]

```
bit 15  STP   semi-transparency / mask bit
bits 14-10    blue  (0-31)
bits  9-5     green (0-31)
bits  4-0     red   (0-31)
```

* `0x0000` is **fully transparent** when used as a texel or palette entry.
* With `STP` set on a non-zero colour, the texel is semi-transparent when the
  primitive's semi-transparency bit is on, and opaque otherwise.
* `0x8000` (black with STP set) is **opaque black**.
* To expand to 8 bits: `c8 = (c5 << 3) | (c5 >> 2)` is a common choice.
  Emulators differ in the exact scaling.

## Practical notes [TYP]

* The DX/DY fields tell you where the game expected the texture to live. That
  helps match textures to the `tpage`/`clut` attributes found in model data.
  Many games ignore them and upload to computed positions instead.
* A single TIM can contain **several CLUT rows** (H > 1). Games choose one per
  primitive for palette swaps.
* Many games pack TIMs inside their own archive formats. Scan for the
  `10 00 00 00` + flags `{00,01,02,03,08,09}` `00 00 00` signature, then check
  that the BNUM sizes are consistent. `tools/tim.py scan` does this.
* 24-bit TIMs are usually full-screen stills or video frames. They cannot be
  used as textures by the GPU. Pixels pack as bytes R0 G0 B0 R1 G1 B1 …, so
  three halfwords hold two pixels.

## From a TIM to a primitive's texture fields [HW]

A model or sprite never names a TIM file. It names the VRAM position the TIM
was loaded to. `tools/tim.py` computes those fields:

| Helper | Value |
|--------|-------|
| `tim_tpage(t)` | TPAGE/TSB: `x/64` in bits 0–3, `y/256` in bit 4, colour depth in bits 7–8 |
| `tim_cba(t)` | CBA: CLUT `x/16` in bits 0–5, CLUT `y` in bits 6–14 |
| `tim_uv_origin(t)` | Where the image starts inside its page, in texels: `(x mod 64) × (4, 2 or 1)`, `y mod 256` |

RSDLINK used exactly these to turn image-relative MAT U,V into TMD values
(see [`rsd.md`](rsd.md)).

## Errata in Sony's 1997 File Formats manual

The Net Yaroze *File Formats* manual (1997) has two slips in its TIM chapter.
Agents reading the original should know about them:

* **Flag bits**: the prose says PMODE is bits 0–3 and CF is bit 4, but the
  manual's own figure, every real file, psx-spx and this parser put **PMODE in
  bits 0–2 and CF in bit 3**. In the Net Yaroze samples, every one of the 556
  TIMs has a flag byte of `0x08`, `0x09`, `0x02` or `0x03`.
* **16-bit pixel figure**: it labels bits 14–10 as G and 9–5 as B. The CLUT
  entry figure in the same manual has the correct order: **B in bits 14–10,
  G in bits 9–5, R in bits 4–0**.

## Validation against real files

`python -m ref.tools.validate` over the Net Yaroze samples parses and decodes
**556 of 556** TIMs: 292 at 4-bit, 155 at 8-bit, 106 at 15-bit and 3 at 24-bit.

## Tool usage

```bash
python -m ref tim info   file.tim          # header summary
python -m ref tim png    file.tim out.png  # decode (CLUT 0) to PNG
python -m ref tim scan   blob.bin          # find embedded TIMs by signature
```

```python
from ref.tools.tim import read_tim, tim_to_rgba, write_tim
tim = read_tim(open("file.tim", "rb").read())
w, h, rgba = tim_to_rgba(tim, clut_index=0)
```
