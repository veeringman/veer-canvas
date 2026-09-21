"""Certified advocate-appointment resolution Word export."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import export_advocate_resolution_docx as exp


class AdvocateResolutionDocxTests(unittest.TestCase):
    def test_writes_fee_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "res.docx"
            exp.build_document().save(str(out))
            self.assertGreater(out.stat().st_size, 4000)
            with zipfile.ZipFile(out) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("50,000", xml)
            self.assertIn("25,000", xml)
            self.assertIn("B.C. Sharma", xml)
            self.assertIn("Shailesh Sharma", xml)
            self.assertIn("12/09/2026", xml)
            self.assertIn("1,500", xml)


if __name__ == "__main__":
    unittest.main()
