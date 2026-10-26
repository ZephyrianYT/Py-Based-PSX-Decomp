"""Behavioural tests for ref/tools (stdlib unittest; run from the repo root:
python -m unittest discover -s ref/tests -t .)"""

import math
import struct
import tempfile
import os
import unittest
import zlib

from ref.tools import fixedpoint as fx
from ref.tools import exe, raster, rsd, tim, tmd, worldgen
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
        # Insert a primitive of an undefined kind (CODE 100, mode 0x80) with ilen 2
        # at the start of the primitive list.
        raw = bytearray(tmd.write_tmd(self._sample()))
        prim_off = 12 + 28
        unknown = struct.pack("<BBBB", 3, 2, 0, 0x80) + b"\x00" * 8
        vtop, nv, ntop, nn, ptop, nprim, scale = struct.unpack_from("<IIIIIIi", raw, 12)
        raw = raw[:prim_off] + unknown + raw[prim_off:]
        # vertex and normal lists follow the primitives, so they move by len(unknown)
        struct.pack_into("<IIIIIIi", raw, 12, vtop + len(unknown), nv, ntop + len(unknown), nn, ptop, nprim + 1, scale)
        t = tmd.read_tmd(bytes(raw))
        self.assertEqual(len(t.objects[0].primitives), 6)
        self.assertEqual(t.objects[0].skipped, [(0x80, 0, 2)])

    def test_obj_export(self):
        obj = tmd.to_obj(tmd.read_tmd(tmd.write_tmd(self._sample())))
        self.assertIn("v 100 -100 0", obj)
        self.assertEqual(obj.count("\nf "), 6)
        self.assertIn("usemtl tsb_0005_cba_7801", obj)


class TmdSonyManualTest(unittest.TestCase):
    """Cases taken from Sony's Net Yaroze File Formats manual and the sample corpus."""

    def test_line_and_sprite_sizes_match_manual(self):
        # (mode, ilen, olen) as printed in the manual's packet tables
        for mode, ilen, olen in [(0x40, 2, 3), (0x50, 3, 4), (0x64, 3, 5), (0x6C, 2, 4), (0x74, 2, 4), (0x7C, 2, 4)]:
            self.assertEqual((tmd.expected_ilen(mode, tmd.LGT), tmd.expected_olen(mode, tmd.LGT)), (ilen, olen), hex(mode))
        # unlit polygons as the manual prints them (TGE set, LGT flag)
        for mode, ilen, olen in [(0x21, 3, 4), (0x31, 5, 6), (0x25, 6, 7), (0x35, 8, 9),
                                 (0x29, 3, 5), (0x39, 6, 8), (0x2D, 7, 9), (0x3D, 10, 12)]:
            self.assertEqual((tmd.expected_ilen(mode, tmd.LGT), tmd.expected_olen(mode, tmd.LGT)), (ilen, olen), hex(mode))
        # lit gradation (GRD) polygons
        for mode, ilen, olen in [(0x20, 5, 6), (0x30, 6, 6), (0x28, 7, 8), (0x38, 8, 8)]:
            self.assertEqual((tmd.expected_ilen(mode, tmd.GRD), tmd.expected_olen(mode, tmd.GRD)), (ilen, olen), hex(mode))

    def test_sprite_packet_layout(self):
        # [vertex0 | TSB] [U V | CBA] [W | H], built by hand from the manual's figure
        raw = struct.pack("<HHBBHHH", 2, 0x0105, 16, 32, 0x7801, 40, 24)
        p = tmd._decode_sprite(0x64, tmd.LGT, raw)
        self.assertEqual((p.vertices, p.tsb, p.uvs, p.cba, p.size), ([2], 0x0105, [(16, 32)], 0x7801, (40, 24)))
        self.assertEqual(tmd._decode_sprite(0x74, tmd.LGT, raw[:8]).size, (8, 8))

    def test_lines_and_sprites_roundtrip(self):
        verts = [(0, 0, 0), (100, 0, 0)]
        prims = [
            tmd.Primitive(tmd.make_line_mode(), tmd.LGT, [0, 1], colors=[(255, 0, 0)]),
            tmd.Primitive(tmd.make_line_mode(gouraud=True), tmd.LGT, [1, 0], colors=[(1, 2, 3), (4, 5, 6)]),
            tmd.Primitive(tmd.make_sprite_mode(16, 16), tmd.LGT, [1], uvs=[(8, 9)], cba=3, tsb=4, size=(16, 16)),
            tmd.Primitive(tmd.make_sprite_mode(40, 20, semi=True), tmd.LGT, [0], uvs=[(1, 2)], cba=5, tsb=6, size=(40, 20)),
        ]
        o = tmd.read_tmd(tmd.write_tmd([tmd.TmdObject(verts, [], prims)])).objects[0]
        self.assertEqual(o.skipped, [])
        self.assertEqual([p.name for p in o.primitives], ["LINE", "GLINE", "SPRITE 16x16", "SPRITE 40x20"])
        self.assertEqual(o.primitives[1].colors, [(1, 2, 3), (4, 5, 6)])
        self.assertEqual(o.primitives[3].size, (40, 20))
        obj = tmd.to_obj(tmd.read_tmd(tmd.write_tmd([tmd.TmdObject(verts, [], prims)])))
        self.assertIn("l 1 2", obj)
        self.assertIn("p 2", obj)

    def test_obj_export_faces_point_outward(self):
        # A polygon facing the viewer (-Z) in TMD space: clockwise on a Y-down
        # screen, authored normal (0, 0, -4096). This is the corpus convention.
        verts = [(0, 0, 0), (100, 0, 0), (0, 100, 0)]   # (0,0) -> (100,0) -> (0,100): clockwise with Y down
        prim = tmd.Primitive(tmd.make_mode(), 0, [0, 1, 2], normals=[0, 0, 0], colors=[(9, 9, 9)])
        data = tmd.write_tmd([tmd.TmdObject(verts, [(0, 0, -4096)], [prim])])
        for flip in (True, False):
            text = tmd.to_obj(tmd.read_tmd(data), flip_y=flip)
            vs = [tuple(map(float, l.split()[1:4])) for l in text.splitlines() if l.startswith("v ")]
            vn = [tuple(map(float, l.split()[1:4])) for l in text.splitlines() if l.startswith("vn ")][0]
            face = [int(tok.split("/")[0]) - 1 for tok in [l for l in text.splitlines() if l.startswith("f ")][0].split()[1:]]
            a, b, c = (vs[i] for i in face)
            u = [b[k] - a[k] for k in range(3)]
            w = [c[k] - a[k] for k in range(3)]
            cross = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
            self.assertGreater(sum(cross[k] * vn[k] for k in range(3)), 0, f"flip_y={flip}: OBJ face points inward")

    def test_truncated_file_is_a_value_error(self):
        data = tmd.write_tmd([tmd.TmdObject([(0, 0, 0)] * 4, [], [])])
        with self.assertRaises(ValueError):
            tmd.read_tmd(data[:-8])

    def test_fixp_ram_dump(self):
        # FIXP=1: pointers are RAM addresses; the object table sat at 0x8009500C.
        good = tmd.write_tmd([tmd.TmdObject([(1, 2, 3)], [(0, 0, 4096)],
                                            [tmd.Primitive(tmd.make_mode(), 0, [0, 0, 0], normals=[0, 0, 0], colors=[(1, 1, 1)])])])
        raw = bytearray(good)
        struct.pack_into("<I", raw, 4, 1)
        vtop, nv, ntop, nn, ptop, np_, sc = struct.unpack_from("<IIIIIIi", raw, 12)
        base = 0x8009500C
        struct.pack_into("<IIIIIIi", raw, 12, vtop + base, nv, ntop + base, nn, ptop + base, np_, sc)
        o = tmd.read_tmd(bytes(raw)).objects[0]
        self.assertEqual(o.vertices, [(1, 2, 3)])
        self.assertEqual(len(o.primitives), 1)


class TimAddressingTest(unittest.TestCase):
    def test_tpage_cba_uv(self):
        t4 = tim.read_tim(tim.write_tim(0, 8, 2, [0] * 16, [[0] * 16], image_xy=(704 + 10, 256 + 3), clut_xy=(32, 481)))
        self.assertEqual(tim.tim_tpage(t4), (0 << 7) | (1 << 4) | 11)
        self.assertEqual(tim.tim_cba(t4), (481 << 6) | 2)
        self.assertEqual(tim.tim_uv_origin(t4), (10 * 4, 3))
        t15 = tim.read_tim(tim.write_tim(2, 2, 1, [1, 2], image_xy=(640 + 5, 0)))
        self.assertEqual(tim.tim_tpage(t15), (2 << 7) | 10)
        self.assertEqual(tim.tim_cba(t15), 0)
        self.assertEqual(tim.tim_uv_origin(t15), (5, 0))


class RsdTest(unittest.TestCase):
    def _write(self, d, files):
        for name, text in files.items():
            with open(os.path.join(d, name), "wb") as f:
                f.write(text if isinstance(text, bytes) else text.encode())

    def _model(self, d):
        self._write(d, {
            "BOX.RSD": "@RSD940102\nPLY=box.ply\nMAT=box.mat\nGRP=box.grp\nNTEX=1\nTEX[0]=tex.tim\n",
            "box.ply": ("@PLY940102\n# counts\n4 2 4\n"
                        "0.5 -0.5 2.5\n-0.5 1.25 0\n10 20 30\n1 1 1\n"
                        "0 0 -1\n0.6 0.8 0\n"
                        "0 0 1 2 0 0 0 0 0\n"      # triangle
                        "1 0 1 3 2 0 1 0 1\n"      # quad
                        "0 0 1 2 0 0 0 0 0\n"
                        "2 0 3 0 0 0 0 0 0\n"),    # line
            "box.mat": ("@MAT940801\n# Number of Items\n4\n"
                        "0 0 F C 10 20 30\n"
                        "1 14 G T 0 0 0 7 0 0 7 7 7\n"      # unlit? no: 0x14 = semi(4) + rate 2 (bits 3-5 = 010)
                        "2 1 F H 0 1 1 2 2 3 3 0 0 10 10 10 20 20 20 30 30 30 0 0 0\n"
                        "3 0 F C 1 2 3\n"),
            "BOX.GRP": "@GRP940102\n1\nall 1 4\n0-3\n",
            "TEX.TIM": tim.write_tim(0, 8, 8, [1] * 64, [[0] * 16], image_xy=(640 + 4, 256 + 8), clut_xy=(16, 480)),
        })
        return rsd.read_rsd(os.path.join(d, "BOX.RSD"))

    def test_read_and_link(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._model(d)
            self.assertEqual(len(m.vertices), 4)
            self.assertEqual(m.groups, {"all": [0, 1, 2, 3]})
            o = rsd.link(m, scale=2)
            # half rounds away from zero: 1.0, -1.0, 5.0 / -1, 2.5 -> 3, 0
            self.assertEqual(o.vertices[0], (1, -1, 5))
            self.assertEqual(o.vertices[1], (-1, 3, 0))
            self.assertEqual(o.scale, 1)
            self.assertEqual(o.normals[1], (2458, 3277, 0))
            tri, quad, htri, line = o.primitives
            self.assertEqual((tri.mode, tri.flag, tri.colors), (0x20, 0, [(10, 20, 30)]))
            # lit, gouraud, textured, semi rate 2 -> TSB bits 5-6; UV offset by the image's place in its page
            self.assertEqual(quad.mode & 0xFE, 0x3E)
            self.assertEqual(quad.flag, 0)
            self.assertEqual(quad.tsb, tim.tim_tpage(m.textures[0]) | (2 << 5))
            self.assertEqual(quad.cba, (480 << 6) | 1)
            self.assertEqual(quad.uvs[0], (16, 8))
            self.assertEqual(quad.colors, [])
            # unlit textured with per-vertex colours: TGE + IIP, LGT flag, 3 colours
            self.assertEqual((htri.mode, htri.flag, len(htri.colors)), (0x35, tmd.LGT, 3))
            self.assertEqual((line.mode, line.vertices), (0x40, [0, 3]))

    def test_tmd_output_reparses(self):
        with tempfile.TemporaryDirectory() as d:
            self._model(d)
            data = rsd.rsd_to_tmd([os.path.join(d, "box.rsd")])   # lower case: DOS-style lookup
            o = tmd.read_tmd(data).objects[0]
            self.assertEqual(o.skipped, [])
            self.assertEqual(len(o.primitives), 4)


class ExeTest(unittest.TestCase):
    def test_psx_exe(self):
        h = bytearray(0x800)
        h[:8] = b"PS-X EXE"
        struct.pack_into("<10I", h, 0x10, 0x80010010, 0x80020000, 0x80010000, 0x800, 0, 0, 0x80010800, 64, 0x801FFF00, 0)
        h[0x4C:0x4C + 20] = b"Sony Computer Entert"
        r = exe.read_executable(bytes(h) + b"\0" * 0x800)
        self.assertEqual((r["kind"], r["entry"], r["load_address"], r["complete"], r["padded"]), ("psx-exe", 0x80010010, 0x80010000, True, True))
        self.assertFalse(exe.read_psx_exe(bytes(h) + b"\0" * 16)["complete"])

    def test_ecoff_yaroze_app(self):
        fh = struct.pack("<HHiIiHH", 0x0162, 1, 0, 0, 0, 56, 0x0002)
        ah = struct.pack("<hhiiiIIIIIIIIII", 0o413, 0, 0x1000, 0x200, 0x40, 0x80140040, 0x80140000, 0x80141000, 0x80141200, 0, 0, 0, 0, 0, 0x80149000)
        sh = struct.pack("<8sIIiIIIHHi", b".text", 0x80140000, 0x80140000, 0x1000, 0x400, 0, 0, 0, 0, 0x20)
        r = exe.read_executable(fh + ah + sh)
        self.assertEqual((r["kind"], r["entry"], r["load_address"], r["net_yaroze_app"]), ("ecoff", 0x80140040, 0x80140000, True))
        self.assertEqual(r["sections"][0]["name"], ".text")

    def test_cpe(self):
        body = b"CPE\x01" + b"\x08\x00" + struct.pack("<BHI", 3, 0x90, 0x80010000) + b"\x01" + struct.pack("<II", 0x80010000, 4) + b"abcd" + b"\x00"
        r = exe.read_executable(body)
        self.assertEqual((r["entry"], r["load_address"], r["load_bytes"], r["ended_cleanly"]), (0x80010000, 0x80010000, 4, True))

    def test_unknown(self):
        self.assertEqual(exe.identify(b"MZ\x90\x00"), "unknown")
        with self.assertRaises(ValueError):
            exe.read_executable(b"\x7fELF")


class SonyFogTest(unittest.TestCase):
    def test_libgs_fog_runs_from_df_over_5_to_df(self):
        ident = [[fx.ONE, 0, 0], [0, fx.ONE, 0], [0, 0, fx.ONE]]
        dqa, dqb = fx.libgs_fog_params(5000, 256)
        ir0 = lambda z: fx.rtps((0, 0, 0), ident, (0, 0, z), 256, dqa=dqa, dqb=dqb)["ir0"]  # noqa: E731
        self.assertEqual(ir0(900), 0)
        self.assertGreater(ir0(2000), 0)
        self.assertGreaterEqual(ir0(5000), 4090)


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
