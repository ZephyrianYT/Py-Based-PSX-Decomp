"""Tests for the decomp pipeline.

    python -m unittest discover -s decomp/tests -t .

Unit tests need only Python. The integration test runs real Ghidra headless and
is skipped unless GHIDRA_INSTALL_DIR points at a Ghidra installation.
"""

import json
import os
import struct
import tempfile
import unittest

from decomp import ghidra, psx_symbols
from decomp.image import RAM_END, RAM_START, build_image


def psx_exe(code_words, t_addr=0x80010000, entry=None, b_size=0, gp=0):
    body = struct.pack(f"<{len(code_words)}I", *code_words)
    body += bytes(-len(body) % 0x800)
    h = bytearray(0x800)
    h[:8] = b"PS-X EXE"
    struct.pack_into("<10I", h, 0x10, entry or t_addr, gp, t_addr, len(body), 0, 0,
                     t_addr + len(body) if b_size else 0, b_size, 0x801FFF00, 0)
    h[0x4C:0x4C + 12] = b"test program"
    return bytes(h) + body


# A tiny function: write 0 to GPU GP1 (display reset), run GTE RTPT, return.
TINY = [
    0x3C021F80,   # lui  v0, 0x1F80
    0xAC401814,   # sw   zero, 0x1814(v0)     -> GPU_GP1 at 0x1F801814
    0x4A280030,   # cop2 0x0280030            -> GTE RTPT
    0x03E00008,   # jr   ra
    0x00000000,   # nop (delay slot)
]


class ImageTest(unittest.TestCase):
    def test_psx_exe_with_bss(self):
        img = build_image(psx_exe(TINY, b_size=0x100, gp=0x80018000))
        self.assertEqual((img.kind, img.base, img.entry, img.gp), ("psx-exe", 0x80010000, 0x80010000, 0x80018000))
        self.assertEqual(len(img.data), 0x800 + 0x100)
        self.assertEqual(struct.unpack_from("<I", img.data, 8)[0], 0x4A280030)

    def test_ecoff_sections_placed(self):
        text, data = struct.pack("<2I", 0x03E00008, 0), b"DATA"
        fh = struct.pack("<HHiIiHH", 0x0162, 3, 0, 0, 0, 56, 0x0002)
        ah = struct.pack("<hhiiiIIIIIIIIII", 0o413, 0, 8, 4, 16, 0x80140000, 0x80140000, 0x80140010, 0x80140020,
                         0, 0, 0, 0, 0, 0x80148000)
        hdr_len = len(fh) + len(ah) + 3 * 40
        sh = struct.pack("<8sIIiIIIHHi", b".text", 0x80140000, 0x80140000, 8, hdr_len, 0, 0, 0, 0, 0x20)
        sh += struct.pack("<8sIIiIIIHHi", b".data", 0x80140010, 0x80140010, 4, hdr_len + 8, 0, 0, 0, 0, 0x40)
        sh += struct.pack("<8sIIiIIIHHi", b".bss", 0x80140020, 0x80140020, 16, 0, 0, 0, 0, 0, 0x80)
        img = build_image(fh + ah + sh + text + data)
        self.assertEqual((img.kind, img.base, img.entry, img.gp, img.net_yaroze), ("ecoff", 0x80140000, 0x80140000, 0x80148000, True))
        self.assertEqual(img.data[0x10:0x14], b"DATA")
        self.assertEqual(len(img.data), 0x30)

    def test_cpe_chunks(self):
        cpe = (b"CPE\x01" + bytes([0x08, 0]) + struct.pack("<BHI", 3, 0x90, 0x80010004)
               + b"\x01" + struct.pack("<II", 0x80010000, 4) + b"abcd"
               + b"\x01" + struct.pack("<II", 0x80010008, 2) + b"ef" + b"\x00")
        img = build_image(cpe)
        self.assertEqual((img.base, img.entry, img.data), (0x80010000, 0x80010004, b"abcd\x00\x00\x00\x00ef"))

    def test_rejects(self):
        with self.assertRaises(ValueError):
            build_image(b"\x7fELF" + bytes(64))
        fh = struct.pack("<HHiIiHH", 0x0162, 0, 0, 0, 0, 0, 0)      # an object file, not a program
        with self.assertRaises(ValueError):
            build_image(fh)


class SymbolsTest(unittest.TestCase):
    def test_gte_decode(self):
        self.assertEqual(psx_symbols.gte_command(0x4A280030)[:3], ("RTPT", psx_symbols.GTE_COMMANDS[0x30][1], 1))
        self.assertEqual(psx_symbols.gte_command(0x4A180001)[0], "RTPS")
        self.assertIsNone(psx_symbols.gte_command(0x48020000))   # mfc2: COP2 without the CO bit
        self.assertIsNone(psx_symbols.gte_command(0x03E00008))

    def test_io_labels(self):
        names = {n: a for a, n, _ in psx_symbols.IO_REGISTERS}
        self.assertEqual(names["GPU_GP0"], 0x1F801810)
        self.assertEqual(names["DMA2_GPU_CHCR"], 0x1F8010A8)
        self.assertEqual(names["TIMER1_TARGET"], 0x1F801118)
        self.assertEqual(len(names), len(psx_symbols.IO_REGISTERS))   # no duplicate names

    def test_parse_symbol_list(self):
        text = ("# comment\n\t.set noreorder\n\t.set GsSortObject4, 0x80023E58\n"
                "InitHeap 80010700\n0x80010030 libps_init\nnot a symbol line\n")
        self.assertEqual(psx_symbols.parse_symbol_list(text),
                         [("GsSortObject4", 0x80023E58), ("InitHeap", 0x80010700), ("libps_init", 0x80010030)])


class LayoutTest(unittest.TestCase):
    def test_ram_gaps_tile_ram(self):
        for net_yaroze in (False, True):
            img = build_image(psx_exe(TINY, t_addr=0x80090000))
            img.net_yaroze = net_yaroze
            spans = [(s, s + n) for _, s, n, _ in ghidra.ram_gaps(img)]
            spans.append((img.base, img.end))
            fixed = psx_symbols.REGIONS + ([psx_symbols.NET_YAROZE_LIBPS] if net_yaroze else [])
            spans += [(s, s + n) for _, s, n, _ in fixed if RAM_START <= s < RAM_END]
            spans.sort()
            self.assertEqual(spans[0][0], RAM_START)
            self.assertEqual(spans[-1][1], RAM_END)
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                self.assertEqual(a1, b0, "RAM must be covered exactly once")

    def test_dry_run_prepares_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            exe_path = os.path.join(d, "t.exe")
            with open(exe_path, "wb") as f:
                f.write(psx_exe(TINY))
            r = ghidra.analyze(exe_path, os.path.join(d, "out"), dry_run=True)
            cmd = r.summary["command"]
            self.assertIn("BinaryLoader", cmd)
            self.assertEqual(cmd[cmd.index("-loader-baseAddr") + 1], "0x80010000")
            self.assertEqual(cmd[cmd.index("-processor") + 1], "MIPS:LE:32:default")
            self.assertIn("PsxSetup.java", cmd)
            tsv = open(os.path.join(d, "out", "symbols.tsv")).read()
            self.assertIn("label\tGPU_GP1\t1F801814", tsv)
            info = json.load(open(os.path.join(d, "out", "image.json")))
            self.assertEqual(info["entry"], "0x80010000")


@unittest.skipUnless(os.environ.get("GHIDRA_INSTALL_DIR"), "set GHIDRA_INSTALL_DIR to run Ghidra")
class GhidraIntegrationTest(unittest.TestCase):
    def test_tiny_program(self):
        with tempfile.TemporaryDirectory() as d:
            exe_path = os.path.join(d, "tiny.exe")
            with open(exe_path, "wb") as f:
                f.write(psx_exe(TINY))
            r = ghidra.analyze(exe_path, os.path.join(d, "out"), timeout_s=600)
            self.assertEqual(r.summary["gte_by_command"], {"RTPT": 1})
            entry = [f for f in r.functions if f["address"] == "0x80010000"]
            self.assertEqual(len(entry), 1)
            self.assertTrue(entry[0]["decompiled"])
            self.assertEqual(entry[0]["gte"], {"RTPT": 1})
            c = open(os.path.join(d, "out", "all.c")).read()
            self.assertIn("GPU_GP1", c)          # the hardware register is named in the C
            self.assertIn("GTE RTPT", c)         # the GTE command is named in the C


if __name__ == "__main__":
    unittest.main()
