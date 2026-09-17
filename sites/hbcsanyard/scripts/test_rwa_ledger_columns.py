#!/usr/bin/env python3
"""Unit tests for EC-configured ledger custom columns."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rwa_ledger_columns  # noqa: E402
from init_rwa_db import connect  # noqa: E402


class LedgerColumnsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "t.db")
        rwa_ledger_columns.ensure_ledger_custom_columns(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_save_and_values(self) -> None:
        cols = rwa_ledger_columns.save_columns(
            self.conn,
            [
                {"label": "Water", "kind": "money"},
                {"label": "Receipt no.", "kind": "text"},
            ],
        )
        self.assertEqual(len(cols), 2)
        self.assertEqual(cols[0]["label"], "Water")
        self.assertEqual(cols[0]["kind"], "money")
        water_id = cols[0]["id"]
        receipt_id = cols[1]["id"]

        vals = rwa_ledger_columns.set_values_for_house(
            self.conn,
            "12",
            {water_id: "1500", receipt_id: "R-44"},
        )
        self.assertEqual(vals[water_id], 1500)
        self.assertEqual(vals[receipt_id], "R-44")

        payment = {"houseId": "12", "pendingDues": 0}
        rwa_ledger_columns.attach_to_payment(payment, cols, vals)
        self.assertEqual(payment[f"custom:{water_id}"], 1500)
        self.assertEqual(payment["customValues"][receipt_id], "R-44")

        fields = rwa_ledger_columns.report_field_defs(self.conn)
        self.assertEqual({f["id"] for f in fields}, {f"custom:{water_id}", f"custom:{receipt_id}"})
        self.assertIn(f"custom:{water_id}", rwa_ledger_columns.money_field_ids(self.conn))

        # Rename keeps values; dropping a column deletes values.
        rwa_ledger_columns.save_columns(
            self.conn,
            [{"id": water_id, "label": "Water charge", "kind": "money"}],
        )
        leftover = rwa_ledger_columns.values_for_house(self.conn, "12")
        self.assertEqual(leftover.get(water_id), 1500)
        self.assertNotIn(receipt_id, leftover)

    def test_max_columns(self) -> None:
        payload = [{"label": f"Col {i}", "kind": "text"} for i in range(12)]
        cols = rwa_ledger_columns.save_columns(self.conn, payload)
        self.assertEqual(len(cols), 8)


if __name__ == "__main__":
    unittest.main()
