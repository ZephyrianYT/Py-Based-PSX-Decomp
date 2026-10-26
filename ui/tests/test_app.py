"""Drive the real Streamlit app headlessly with streamlit.testing (skipped if
Streamlit is not installed)."""

import os
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover - the stdlib-only test run
    AppTest = None

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class AppTestCase(unittest.TestCase):
    def run_page(self, page):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        at.sidebar.radio[0].set_value(page).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_every_page_renders(self):
        for page in ("Library", "Look lab", "GTE jitter", "World generator", "File inspector", "Self-test"):
            with self.subTest(page=page):
                self.run_page(page)

    def test_sample_tmd_in_inspector(self):
        at = self.run_page("File inspector")
        at.button[1].click().run()                      # "Try a sample TMD"
        self.assertFalse(at.exception)
        self.assertTrue(any("F4" in c.value for c in at.code))

    def test_password_gate(self):
        os.environ["PSX_UI_PASSWORD"] = "letmein"
        try:
            at = AppTest.from_file(APP, default_timeout=60)
            at.run()
            self.assertEqual(len(at.sidebar.radio), 0)    # nothing behind the gate is shown
            at.text_input[0].set_value("wrong")
            at.button[0].click().run()
            self.assertTrue(at.error)
            at.text_input[0].set_value("letmein")
            at.button[0].click().run()
            self.assertEqual(len(at.sidebar.radio), 1)
        finally:
            del os.environ["PSX_UI_PASSWORD"]


if __name__ == "__main__":
    unittest.main()
