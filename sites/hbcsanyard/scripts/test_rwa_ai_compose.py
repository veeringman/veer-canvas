#!/usr/bin/env python3
"""Tests for Templates → Write a document AI Assist (eGenie + Syntheon)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rwa_ai_compose  # noqa: E402
from init_rwa_db import connect  # noqa: E402


class ClassifyIntentTest(unittest.TestCase):
    def test_resolution_keywords(self) -> None:
        intent = rwa_ai_compose.classify_intent(
            "Draft a resolution to hire Advocate Shailesh Sharma for Rs 50000"
        )
        self.assertEqual(intent["starterId"], "resolution")
        self.assertIn("resolution", intent["title"].lower())

    def test_user_starter_wins(self) -> None:
        intent = rwa_ai_compose.classify_intent(
            "Draft a resolution for the path case",
            starter_id="notice",
        )
        self.assertEqual(intent["starterId"], "notice")
        self.assertEqual(intent["source"], "user")

    def test_minutes_default_ec(self) -> None:
        intent = rwa_ai_compose.classify_intent("Write minutes of yesterday's sitting")
        self.assertEqual(intent["starterId"], "mom_ec")


class HtmlHelpersTest(unittest.TestCase):
    def test_html_from_nested_act(self) -> None:
        html = rwa_ai_compose._html_from_remote({
            "act": {"document": {"htmlBody": "<p>Resolved that the path is opened.</p>"}},
        })
        self.assertIn("Resolved that", html)

    def test_coerce_plain_text(self) -> None:
        html = rwa_ai_compose._coerce_html("Hello\n\nWorld")
        self.assertIn("<p>Hello</p>", html)
        self.assertIn("<p>World</p>", html)


class DraftDocumentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self.conn = connect(self.root / "data" / "t.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_empty_intent_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rwa_ai_compose.draft_document(self.conn, self.root, intent_text="  ")

    def test_syntheon_html_used(self) -> None:
        with patch.object(rwa_ai_compose, "call_egenie", return_value={
            "intent": {"starterId": "resolution", "title": "Resolution — advocate"},
        }), patch.object(rwa_ai_compose, "call_syntheon", return_value={
            "htmlBody": "<p>RESOLVED THAT Advocate Sharma be engaged.</p>",
            "title": "Resolution — engage advocate",
        }), patch.object(rwa_ai_compose.rwa_ai_chat, "retrieve_smart", return_value=([], "python-lexical")):
            out = rwa_ai_compose.draft_document(
                self.conn,
                self.root,
                intent_text="Hire advocate Sharma for the path case at 50000",
            )
        self.assertEqual(out["starterId"], "resolution")
        self.assertIn("Advocate Sharma", out["htmlBody"])
        self.assertEqual(out["title"], "Resolution — engage advocate")
        self.assertIn("egenie", out["mode"])
        self.assertIn("syntheon", out["mode"])

    def test_extractive_fallback_without_services(self) -> None:
        env = {
            "EGENIE_ENABLED": "0",
            "SYNTHEON_ENABLED": "0",
            "RWA_AI_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        chunks = [{
            "id": "proc-1",
            "title": "EC minutes 12 Jan 2026",
            "text": "The Committee discussed the pending path / link-road civil suit.",
            "source": "proceedings",
        }]
        with patch.dict("os.environ", env, clear=False), patch.object(
            rwa_ai_compose.rwa_ai_chat, "retrieve_smart", return_value=(chunks, "python-lexical")
        ), patch.object(rwa_ai_compose, "call_egenie", return_value=None), patch.object(
            rwa_ai_compose, "call_syntheon", return_value=None
        ):
            out = rwa_ai_compose.draft_document(
                self.conn,
                self.root,
                intent_text="Write an EC resolution about the pending path case",
            )
        self.assertEqual(out["starterId"], "resolution")
        self.assertIn("RESOLVED THAT", out["htmlBody"])
        self.assertIn("path / link-road", out["htmlBody"])
        self.assertTrue(out["sources"])

    def test_compose_status_keys(self) -> None:
        with patch.object(rwa_ai_compose, "_service_health", return_value={"ok": False, "error": "unreachable"}):
            status = rwa_ai_compose.compose_status(self.root, self.conn)
        self.assertIn("egenie", status)
        self.assertIn("syntheon", status)
        self.assertIn("mode", status)


if __name__ == "__main__":
    unittest.main()
