"""Tests for ui/logic.py (standard library only, no Streamlit needed).

    python -m unittest discover -s ui/tests -t .
"""

import math
import unittest

from ui import logic
from ref.tools import tmd


class LibraryTest(unittest.TestCase):
    def test_search_and_read(self):
        hits = logic.search_docs("net yaroze")
        self.assertIn("sdk/net-yaroze.md", [d["path"] for d in hits])
        self.assertIn("**TL;DR**", logic.read_doc("sdk/net-yaroze.md"))

    def test_read_refuses_unlisted_paths(self):
        for bad in ("../README.md", "tools/tmd.py", "/etc/passwd"):
            with self.assertRaises(ValueError):
                logic.read_doc(bad)

    def test_doc_images(self):
        names = [n for n, _ in logic.doc_images("look/images/README.md")]
        self.assertIn("affine_vs_perspective.png", names)


class RenderTest(unittest.TestCase):
    def test_scenes_render_png(self):
        for name in logic.SCENE_NAMES:
            png, stats = logic.render_scene(name, logic.LookSettings(), scale=1)
            self.assertTrue(png.startswith(b"\x89PNG"))
            self.assertGreater(stats["pixels"], 0)

    def test_modern_differs_from_ps1(self):
        a, _ = logic.render_scene("affine", logic.LookSettings(), scale=1)
        b, _ = logic.render_scene("affine", logic.LookSettings.modern(), scale=1)
        self.assertNotEqual(a, b)

    def test_jitter_steps(self):
        rows = logic.jitter_series(2000, 30, 60)
        self.assertEqual(len(rows), 61)
        self.assertLess(len({r["gte_screen_x"] for r in rows}), len(rows))


class WorldTest(unittest.TestCase):
    def test_dungeon(self):
        w = logic.generate_world("dungeon", 3, 16, scale=1)
        self.assertTrue(w.png.startswith(b"\x89PNG"))
        self.assertIn("#", w.ascii_map)
        self.assertTrue(w.obj.startswith("# generated"))


class InspectorTest(unittest.TestCase):
    def test_detect_kind(self):
        self.assertEqual(logic.detect_kind("x", logic.sample_tim()), "tim")
        self.assertEqual(logic.detect_kind("x", logic.sample_tmd()), "tmd")
        self.assertEqual(logic.detect_kind("x", b"PS-X EXE" + bytes(2040)), "exe")
        self.assertEqual(logic.detect_kind("m.rsd", b"@RSD940102"), "rsd")
        self.assertEqual(logic.detect_kind("x.bin", b"hello"), "unknown")

    def test_tim_palette_swap(self):
        info, a = logic.inspect_tim(logic.sample_tim(), 0, scale=1)
        _, b = logic.inspect_tim(logic.sample_tim(), 1, scale=1)
        self.assertIn("2 CLUT(s)", info)
        self.assertNotEqual(a, b)

    def test_sample_house_faces_outward(self):
        mesh = logic.tmd_to_meshes(tmd.read_tmd(logic.sample_tmd()))[0][0]
        centre = [sum(v[k] for v in mesh.vertices) / len(mesh.vertices) for k in range(3)]
        for f in mesh.faces:
            a, b, c = (mesh.vertices[i] for i in f.idx[:3])
            u = [b[k] - a[k] for k in range(3)]
            v = [c[k] - a[k] for k in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            fc = [sum(mesh.vertices[i][k] for i in f.idx) / len(f.idx) for k in range(3)]
            self.assertGreater(sum(n[k] * (fc[k] - centre[k]) for k in range(3)), 0)

    def test_render_tmd_culls_back_half(self):
        png, stats = logic.render_tmd(logic.sample_tmd(), scale=1)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(stats["faces"], 8)
        self.assertTrue(2 <= stats["culled_back"] <= 6)

    def test_tiny_model_is_framed(self):
        # a model 2 units across must still be visible (the preview normalises size)
        prim = tmd.Primitive(tmd.make_mode(), 0, [0, 1, 2], normals=[0] * 3, colors=[(200, 200, 200)])
        data = tmd.write_tmd([tmd.TmdObject([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(0, 0, -4096)], [prim])])
        meshes, _, radius = logic.tmd_to_meshes(tmd.read_tmd(data))
        # vertices are rescaled so the farthest one is 1000 units from the centre
        farthest = max(math.sqrt(sum(c * c for c in v)) for v in meshes[0].vertices)
        self.assertAlmostEqual(farthest, 1000, delta=1)
        self.assertLess(radius, 2)

    def test_rsd_upload_needs_one_rsd(self):
        with self.assertRaises(ValueError):
            logic.link_rsd({"a.ply": b""})

    def test_exe(self):
        text, header = logic.inspect_exe(b"CPE\x01\x00")
        self.assertIn("CPE", text)
        self.assertEqual(header["kind"], "cpe")


if __name__ == "__main__":
    unittest.main()
