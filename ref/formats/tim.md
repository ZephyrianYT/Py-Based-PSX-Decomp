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
  used as textures by the GPU.

## Tool usage

```bash
python -m ref.tools.tim info   file.tim          # header summary
python -m ref.tools.tim png    file.tim out.png  # decode (CLUT 0) to PNG
python -m ref.tools.tim scan   blob.bin          # find embedded TIMs by signature
```

```python
from ref.tools.tim import read_tim, tim_to_rgba, write_tim
tim = read_tim(open("file.tim", "rb").read())
w, h, rgba = tim_to_rgba(tim, clut_index=0)
```
