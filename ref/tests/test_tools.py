"""Behavioural tests for ref/tools (stdlib unittest; run from the repo root:
python -m unittest discover -s ref/tests -t .)"""

import math
import struct
import tempfile
import os
import unittest
import zlib

from ref.tools import fixedpoint as fx
from ref.tools import raster, tim, tmd, worldgen
from ref.tools.pngio import encode_png, scale_nearest


class FixedPointTest(unittest.TestCase):
    def test_fx12_roundtrip(self):
        self.assertEqual(fx.to_fx12(1.0), 0x1000)
        self.assertEqual(fx.to_fx12(-0.5), -0x800)
        self.assertAlmostEqual(fx.from_fx12(fx.to_fx12(0.3)), 0.3, places=3)

    def test_rotation_is_near_orthonormal(self):
        m = fx.rot_matrix_xyz(300, 700, 1100)
        for row in m:
            self.assertAlmostEqual(sum(v * v for v in row) / 4096 ** 2, 1.0, places=2)

    def test_rtps_outputs_integers_and_steps(self):
        ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
        xs = [fx.rtps((0, 0, 0), ident, (x, 0, 2000))["sx"] for x in range(0, 24, 2)]
        self.assertTrue(all(isinstance(v, int) for v in xs))
        self.assertEqual(xs[0], 160)
        self.assertLess(len(set(xs)), len(xs))  # several world positions share one pixel: jitter

    def test_rtps_overflow_near_camera(self):
        ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
        r = fx.rtps((10, 0, 0), ident, (0, 0, 50), h=256)
        self.assertTrue(r["overflow"])

    def test_screen_clamp(self):
        ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
        r = fx.rtps((30000, 0, 0), ident, (0, 0, 600))
        self.assertEqual(r["sx"], 0x3FF)

    def test_nclip_sign(self):
        self.assertGreater(fx.nclip((0, 0), (10, 0), (0, 10)), 0)
        self.assertLess(fx.nclip((0, 0), (0, 10), (10, 0)), 0)

    def test_depth_cue_params(self):
        dqa, dqb = fx.depth_cue_params(256, 1000, 5000)
        ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
        near = fx.rtps((0, 0, 0), ident, (0, 0, 1000), 256, dqa=dqa, dqb=dqb)["ir0"]
        far = fx.rtps((0, 0, 0), ident, (0, 0, 5000), 256, dqa=dqa, dqb=dqb)["ir0"]
        self.assertLessEqual(near, 8)
        self.assertGreaterEqual(far, 0x1000 - 8)
        self.assertEqual(fx.depth_cue((0, 0, 0), (200, 100, 50), 0x1000), (200, 100, 50))


class RasterTest(unittest.TestCase):
    def test_dither_table_matches_hardware(self):
        self.assertEqual(raster.DITHER[0], (-4, 0, -3, 1))
        self.assertEqual(raster.DITHER[3], (3, -1, 2, -2))
        self.assertEqual(sum(sum(r) for r in raster.DITHER), -8)

    def test_dither_to_15bit(self):
        self.assertEqual(raster.dither_to_15bit(255, 255, 255, 0, 0, dither=False), 0x7FFF)
        self.assertEqual(raster.dither_to_15bit(4, 4, 4, 0, 0), 0)          # 4 - 4 = 0
        self.assertEqual(raster.dither_to_15bit(6, 6, 6, 2, 1), 0x0421)     # 6 + 3 = 9 -> 1

    def test_shared_edge_drawn_once(self):
        fb = raster.Framebuffer(16, 16)
        a, b, c, d = (raster.ScreenVertex(x, y, 255, 255, 255) for x, y in [(0, 0), (16, 0), (16, 16), (0, 16)])
        n = raster.draw_triangle(fb, a, b, c, dither=False, gouraud=False)
        n += raster.draw_triangle(fb, a, c, d, dither=False, gouraud=False)
        self.assertEqual(n, 256)  # top-left rule: every pixel exactly once

    def test_size_limit(self):
        fb = raster.Framebuffer(32, 32)
        v = [raster.ScreenVertex(0, 0), raster.ScreenVertex(1100, 0), raster.ScreenVertex(0, 10)]
        self.assertEqual(raster.draw_triangle(fb, *v), 0)
        self.assertGreater(raster.draw_triangle(fb, *v, size_limit=False), 0)

    def test_transparent_texel_and_modulation(self):
        texels = [0x0000, tim.rgb8_to_15(128, 128, 128)] * 8  # 4x4 alternating
        tex = raster.Texture(4, 4, texels)
        fb = raster.Framebuffer(4, 4, clear=(255, 0, 0))
        verts = [raster.ScreenVertex(x, y, 128, 128, 128, x, y) for x, y in [(0, 0), (4, 0), (4, 4), (0, 4)]]
        raster.draw_triangle(fb, verts[0], verts[1], verts[2], tex, dither=False)
        raster.draw_triangle(fb, verts[0], verts[2], verts[3], tex, dither=False)
        red = raster.dither_to_15bit(255, 0, 0, 0, 0, dither=False)
        self.assertEqual(fb.pixels[0], red)                       # u=0 texel 0x0000 -> untouched
        self.assertEqual(fb.pixels[1], tim.rgb8_to_15(128, 128, 128))  # colour 128 = unmodified

    def test_affine_differs_from_perspective(self):
        tex = raster.Texture(2, 1, [tim.rgb8_to_15(255, 255, 255), tim.rgb8_to_15(8, 8, 8)])
        out = []
        for affine in (True, False):
            fb = raster.Framebuffer(64, 8)
            a = raster.ScreenVertex(0, 0, u=0, v=0, w=1.0)
            b = raster.ScreenVertex(64, 0, u=2, v=0, w=0.1)
            c = raster.ScreenVertex(0, 8, u=0, v=0, w=1.0)
            raster.draw_triangle(fb, a, b, c, tex, affine=affine, dither=False)
            out.append(fb.pixels[:64])
        self.assertNotEqual(out[0], out[1])

    def test_ordering_table_draw_order(self):
        ot = raster.OrderingTable(8)
        ot.add(1, "near")
        ot.add(6, "far")
        ot.add(6, "far2")
        self.assertEqual(list(ot), ["far2", "far", "near"])

    def test_render_mesh_culls_backfaces(self):
        verts = [(-100.0, -100.0, 500.0), (100.0, -100.0, 500.0), (100.0, 100.0, 500.0), (-100.0, 100.0, 500.0)]
        front = raster.Mesh(verts, [raster.Face((0, 3, 2, 1))])   # CCW as seen from camera at origin looking +Z
        back = raster.Mesh(verts, [raster.Face((0, 1, 2, 3))])
        cam = raster.Camera(h=200)
        s1 = raster.render_mesh(raster.Framebuffer(), [front], cam)
        s2 = raster.render_mesh(raster.Framebuffer(), [back], cam)
        self.assertEqual((s1["culled_back"], s2["culled_back"]), (0, 1))
        self.assertGreater(s1["pixels"], 1000)


class TimTest(unittest.TestCase):
    def test_4bit_roundtrip(self):
        pix = [(x + y) % 16 for y in range(8) for x in range(8)]
        clut = [tim.rgb8_to_15(i * 16, 0, 255 - i * 16) for i in range(16)]
        data = tim.write_tim(0, 8, 8, pix, [clut, clut[::-1]])
        t = tim.read_tim(data)
        self.assertEqual((t.pmode, t.width, t.height, t.num_cluts), (0, 8, 8, 2))
        self.assertEqual(tim.tim_indices(t), pix)
        self.assertEqual(tim.tim_halfwords(t, 1)[0], clut[15])
        self.assertEqual(len(data), tim.tim_size(t))
        # low nibble is the left pixel
        self.assertEqual(t.image.data[0] & 0xF, pix[0])

    def test_8bit_and_15bit(self):
        pix8 = list(range(16))
        t8 = tim.read_tim(tim.write_tim(1, 4, 4, pix8, [list(range(256))]))
        self.assertEqual(tim.tim_indices(t8), pix8)
        pix15 = [0x7FFF, 0x0000, 0x8000, 0x001F]
        t15 = tim.read_tim(tim.write_tim(2, 2, 2, pix15))
        w, h, rgba = tim.tim_to_rgba(t15)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(rgba[7], 0)          # 0x0000 transparent
        self.assertEqual(rgba[8:12], b"\x00\x00\x00\xff")  # 0x8000 opaque black

    def test_scan_finds_embedded(self):
        a = tim.write_tim(2, 2, 2, [1, 2, 3, 4])
        b = tim.write_tim(0, 4, 1, [0, 1, 2, 3], [[0] * 16])
        blob = b"\xAA" * 13 + a + b"\x00" * 7 + b + b"\x10\x00\x00\x00junk"
        hits = tim.scan(blob)
        self.assertEqual([off for off, _ in hits], [13, 13 + len(a) + 7])

    def test_rejects_bad_id(self):
        with self.assertRaises(ValueError):
            tim.read_tim(b"\x11\x00\x00\x00" + b"\x00" * 40)


class TmdTest(unittest.TestCase):
    def _sample(self):
        verts = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)]
        norms = [(0, 0, -4096)]
        prims = [
            tmd.Primitive(tmd.make_mode(), 0, [0, 1, 2], normals=[0, 0, 0], colors=[(200, 100, 50)]),
            tmd.Primitive(tmd.make_mode(gouraud=True), 0, [1, 2, 3], normals=[0, 0, 0], colors=[(1, 2, 3)]),
            tmd.Primitive(tmd.make_mode(textured=True), 0, [0, 1, 2], normals=[0, 0, 0], uvs=[(0, 0), (63, 0), (0, 63)], cba=0x7801, tsb=0x0005),
            tmd.Primitive(tmd.make_mode(quad=True, textured=True, gouraud=True), 0, [0, 1, 2, 3], normals=[0] * 4,
                          uvs=[(0, 0), (63, 0), (0, 63), (63, 63)], cba=1, tsb=2),
            tmd.Primitive(tmd.make_mode(quad=True), tmd.LGT, [0, 1, 2, 3], colors=[(9, 9, 9)]),
            tmd.Primitive(tmd.make_mode(gouraud=True), tmd.LGT, [0, 1, 2], colors=[(1, 1, 1), (2, 2, 2), (3, 3, 3)]),
        ]
        return [tmd.TmdObject(verts, norms, prims)]

    def test_standard_ilen_olen(self):
        expect = {0x20: (3, 4), 0x30: (4, 6), 0x24: (5, 7), 0x34: (6, 9),
                  0x28: (4, 5), 0x38: (5, 8), 0x2C: (7, 9), 0x3C: (8, 12)}
        for mode, (ilen, olen) in expect.items():
            self.assertEqual((tmd.expected_ilen(mode, 0), tmd.expected_olen(mode, 0)), (ilen, olen), hex(mode))
        self.assertEqual(tmd.expected_ilen(0x20, tmd.LGT), 3)
        self.assertEqual(tmd.expected_ilen(0x30, tmd.LGT), 5)

    def test_roundtrip(self):
        data = tmd.write_tmd(self._sample())
        self.assertEqual(struct.unpack_from("<I", data)[0], 0x41)
        t = tmd.read_tmd(data)
        o = t.objects[0]
        self.assertEqual(len(o.primitives), 6)
        self.assertEqual(o.skipped, [])
        self.assertEqual(o.primitives[0].colors, [(200, 100, 50)])
        self.assertEqual(o.primitives[2].cba, 0x7801)
        self.assertEqual(o.primitives[3].vertices, [0, 1, 2, 3])
        self.assertEqual(o.primitives[5].colors, [(1, 1, 1), (2, 2, 2), (3, 3, 3)])
        self.assertEqual(o.vertices[3], (100, 100, 0))

    def test_unknown_primitive_is_skipped_not_misread(self):
        # Insert a line primitive (CODE 010, ilen 2) at the start of the primitive list.
        raw = bytearray(tmd.write_tmd(self._sample()))
        prim_off = 12 + 28
        line = struct.pack("<BBBB", 3, 2, 0, 0x40) + b"\x00" * 8
        vtop, nv, ntop, nn, ptop, nprim, scale = struct.unpack_from("<IIIIIIi", raw, 12)
        raw = raw[:prim_off] + line + raw[prim_off:]
        # vertex and normal lists follow the primitives, so they move by len(line)
        struct.pack_into("<IIIIIIi", raw, 12, vtop + len(line), nv, ntop + len(line), nn, ptop, nprim + 1, scale)
        t = tmd.read_tmd(bytes(raw))
        self.assertEqual(len(t.objects[0].primitives), 6)
        self.assertEqual(t.objects[0].skipped, [(0x40, 0, 2)])

    def test_obj_export(self):
        obj = tmd.to_obj(tmd.read_tmd(tmd.write_tmd(self._sample())))
        self.assertIn("v 100 -100 0", obj)
        self.assertEqual(obj.count("\nf "), 6)
        self.assertIn("usemtl tsb_0005_cba_7801", obj)


class WorldgenTest(unittest.TestCase):
    def test_terrain(self):
        m = worldgen.generate_terrain(size=8, seed=3, chunk_cells=4)
        self.assertEqual(len(m.faces), 64)
        self.assertEqual(len(m.vertices), 81)
        self.assertEqual(len(m.chunks), 4)
        self.assertTrue(all(c % 8 == 0 for col in m.colors for c in col))  # 15-bit levels
        self.assertTrue(all(isinstance(c, int) and -32768 <= c <= 32767 for v in m.vertices for c in v))
        # deterministic
        self.assertEqual(m.vertices, worldgen.generate_terrain(size=8, seed=3, chunk_cells=4).vertices)

    def test_terrain_faces_up(self):
        m = worldgen.generate_terrain(size=2, seed=1, max_height=0)
        a, b, c = (m.vertices[i] for i in m.faces[0][:3])
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        ny = u[2] * v[0] - u[0] * v[2]
        self.assertGreater(ny, 0)

    def test_dungeon_connected(self):
        grid, rooms = worldgen.generate_dungeon_grid(size=24, rooms=6, seed=5)
        self.assertGreaterEqual(len(rooms), 2)
        cells = {(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c}
        start = next(iter(cells))
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        self.assertEqual(seen, cells)

    def test_dungeon_obj(self):
        m = worldgen.generate_dungeon(size=16, rooms=4, seed=2, subdiv=1)
        text = m.to_obj()
        self.assertTrue(text.startswith("# generated"))
        self.assertEqual(text.count("\nf "), len(m.faces))
        self.assertGreater(m.stats()["faces"], 0)


class PngTest(unittest.TestCase):
    def test_png_structure(self):
        data = encode_png(2, 1, b"\xff\x00\x00\x00\xff\x00")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        idat_len = struct.unpack(">I", data[33:37])[0]
        raw = zlib.decompress(data[41:41 + idat_len])
        self.assertEqual(raw, b"\x00\xff\x00\x00\x00\xff\x00")

    def test_scale(self):
        w, h, px = scale_nearest(1, 1, b"\x01\x02\x03", 3)
        self.assertEqual((w, h, px), (3, 3, b"\x01\x02\x03" * 9))


class EntryPointTest(unittest.TestCase):
    def test_commands(self):
        import contextlib
        import io
        from ref.__main__ import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main([]), 0)
            self.assertEqual(main(["docs"]), 0)
            self.assertEqual(main(["jitter"]), 0)
        self.assertIn("ref/hardware/gpu.md", buf.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["nope"]), 2)


class DemoSmokeTest(unittest.TestCase):
    def test_demo_runs(self):
        from ref.tools import demo
        with tempfile.TemporaryDirectory() as d:
            demo.main(["--out", d, "--scale", "1", "--only", "dither", "--only", "jitter"])
            self.assertTrue(os.path.isfile(os.path.join(d, "dither_vs_none.png")))
            self.assertTrue(os.path.isfile(os.path.join(d, "jitter_chart.png")))


if __name__ == "__main__":
    unittest.main()
