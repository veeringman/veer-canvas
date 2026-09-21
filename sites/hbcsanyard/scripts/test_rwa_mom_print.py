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
            self.assertIn("proceedings-mom-print.css?v=20260921mom13", html)
            self.assertNotIn("class=\\\"foot-bar\\\"", html)
            self.assertIn('<div class="foot-bar"', html)
            # Footer sits after .pad, not inside it.
            self.assertIn("Proceedings / minutes (continued)", html)
            self.assertIn("ruled-block xxl", html)

    def test_portal_print_always_includes_page2_minutes(self):
        js = (ROOT.parent / "portal.js").read_text()
        self.assertIn('<h2>Proceedings / minutes (continued)</h2>', js)
        self.assertIn("ruled-block xxl", js)
        self.assertIn("data-minutes=", js)
        self.assertIn("function fitMomMinutesAcrossPages", js)
        self.assertIn("const bodyP2 = split.page2", js)
        self.assertNotIn("bodySplit ? split.page2 : split.page1", js)
        css = (ROOT.parent / "documents" / "proceedings-mom-print.css").read_text()
        self.assertIn(".grow { flex: 1 1 0;", css)
        self.assertIn("min-height: 0 !important", css)
        self.assertIn("column-count: 3", css)

    def test_watermark_visible_through_tables(self):
        docs = ROOT.parent / "documents"
        css = (docs / "proceedings-mom-print.css").read_text()
        self.assertIn("mix-blend-mode: multiply", css)
        self.assertIn("table.res-table td {", css)
        common = (docs / "print-pad-common.css").read_text()
        self.assertIn("mix-blend-mode: multiply", common)
        pdf = rwa_templates._pdf_page_layout_css({"paperSize": "A4"}, mom=True)
        self.assertIn("mix-blend-mode: multiply", pdf)
        self.assertIn("table.res-table td", pdf)
        runtime = rwa_templates._runtime_options_css({"paperSize": "A4"}, mom=True)
        self.assertIn("mix-blend-mode: multiply", runtime)
        self.assertIn("background: transparent", runtime)


if __name__ == "__main__":
    unittest.main()
