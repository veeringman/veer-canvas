"""Proceedings / MoM print and PDF layout must stay inside the paper page."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rwa_templates


class MomPrintLayoutTests(unittest.TestCase):
    def test_fit_height_shrinks_a4(self):
        self.assertEqual(rwa_templates._mom_fit_height("297mm"), "277mm")
        self.assertEqual(rwa_templates._mom_fit_height("11in"), "10.2126in")
        self.assertTrue(rwa_templates._mom_fit_height("nope").startswith("calc("))

    def test_pdf_css_does_not_use_full_page_height(self):
        css = rwa_templates._pdf_page_layout_css({"paperSize": "A4"}, mom=True)
        self.assertIn("277mm", css)
        self.assertNotIn("height: 297mm", css)
        self.assertIn("position: relative !important", css)
        self.assertNotIn("left: -11mm", css)
        self.assertIn("overflow: visible", css)

    def test_runtime_css_matches_fit_height(self):
        css = rwa_templates._runtime_options_css({"paperSize": "A4"}, mom=True)
        self.assertIn("277mm", css)
        self.assertNotIn("left: -11mm", css)

    def test_pad_html_footer_is_sheet_sibling(self):
        docs = ROOT.parent / "documents"
        for name in ("proceedings-ec-mom-pad.html", "proceedings-gh-mom-pad.html"):
            html = (docs / name).read_text()
            self.assertIn("proceedings-mom-print.css?v=20260921mom8", html)
            self.assertNotIn("class=\\\"foot-bar\\\"", html)
            self.assertIn('<div class="foot-bar"', html)
            # Footer sits after .pad, not inside it.
            self.assertRegex(html, r"</div>\s*<div class=\"foot-bar\"")


if __name__ == "__main__":
    unittest.main()
