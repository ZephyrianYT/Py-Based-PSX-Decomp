"""Keeps ref/index.json, the Markdown files and the tool modules in sync."""

import importlib
import json
import os
import unittest

REF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REF, "index.json")) as f:
            cls.index = json.load(f)

    def test_listed_docs_exist(self):
        for doc in self.index["docs"]:
            self.assertTrue(os.path.isfile(os.path.join(REF, doc["path"])), doc["path"])
            for key in ("title", "tags", "summary"):
                self.assertTrue(doc.get(key), f"{doc['path']} missing {key}")

    def test_every_markdown_file_is_listed(self):
        listed = {d["path"] for d in self.index["docs"]}
        for root, _dirs, files in os.walk(REF):
            for name in files:
                if name.endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, name), REF).replace(os.sep, "/")
                    self.assertIn(rel, listed, f"{rel} is not registered in index.json")

    def test_docs_have_tldr(self):
        for doc in self.index["docs"]:
            if doc["path"] in ("README.md", "AGENTS.md"):
                continue
            with open(os.path.join(REF, doc["path"])) as f:
                self.assertIn("**TL;DR**", f.read(), doc["path"])

    def test_tools_import(self):
        for tool in self.index["tools"]:
            self.assertTrue(os.path.isfile(os.path.join(REF, tool["path"])), tool["path"])
            importlib.import_module(tool["module"])

    def test_relative_links_resolve(self):
        import re
        link = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
        for doc in self.index["docs"]:
            path = os.path.join(REF, doc["path"])
            with open(path) as f:
                text = f.read()
            for target in link.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
                self.assertTrue(os.path.exists(resolved), f"{doc['path']}: broken link {target}")


if __name__ == "__main__":
    unittest.main()
