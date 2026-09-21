#!/usr/bin/env python3
"""Proceedings register number can be edited on save."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADMIN = ROOT.parents[2] / "admin"
for path in (str(ROOT), str(ADMIN)):
    if path not in sys.path:
        sys.path.insert(0, path)

import rwa_proceedings  # noqa: E402
from init_rwa_db import connect, init_schema  # noqa: E402


class ProceedingsRegisterNoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "t.db")
        init_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_edit_register_no(self) -> None:
        first = rwa_proceedings.upsert_meeting_proceeding(
            self.conn,
            {
                "title": "EC September",
                "meetingDate": "2026-09-12",
                "meetingType": "ec",
                "proceedingsBody": "Minutes",
            },
            actor={"houseId": "99"},
        )
        self.assertEqual(first["registerNo"], 1)
        self.assertEqual(first["registerLabel"], "1/2026")
        updated = rwa_proceedings.upsert_meeting_proceeding(
            self.conn,
            {
                "id": first["id"],
                "title": "EC September",
                "meetingDate": "2026-09-12",
                "meetingType": "ec",
                "registerNo": "3",
                "proceedingsBody": "Minutes",
            },
            actor={"houseId": "99"},
        )
        self.assertEqual(updated["registerNo"], 3)
        self.assertEqual(updated["registerLabel"], "3/2026")

    def test_register_label_payload(self) -> None:
        row = rwa_proceedings.upsert_meeting_proceeding(
            self.conn,
            {
                "title": "GH",
                "meetingDate": "2026-04-01",
                "meetingType": "gh",
                "registerNo": "2/2026",
            },
            actor={"houseId": "99"},
        )
        self.assertEqual(row["registerNo"], 2)

    def test_duplicate_register_no_rejected(self) -> None:
        rwa_proceedings.upsert_meeting_proceeding(
            self.conn,
            {
                "title": "A",
                "meetingDate": "2026-09-01",
                "meetingType": "ec",
                "registerNo": 1,
            },
            actor={"houseId": "99"},
        )
        with self.assertRaises(ValueError):
            rwa_proceedings.upsert_meeting_proceeding(
                self.conn,
                {
                    "title": "B",
                    "meetingDate": "2026-09-20",
                    "meetingType": "ec",
                    "registerNo": 1,
                },
                actor={"houseId": "99"},
            )


if __name__ == "__main__":
    unittest.main()
