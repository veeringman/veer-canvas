#!/usr/bin/env python3
"""EC desk plot directory: profile, delegates, tenants, vehicles on another plot."""

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

import rwa_household  # noqa: E402
import rwa_parking  # noqa: E402
import rwa_portal  # noqa: E402
import rwa_tenants  # noqa: E402
from init_rwa_db import (  # noqa: E402
    connect,
    ensure_household_members_table,
    ensure_household_tenants_table,
    ensure_parking_passes_table,
    init_schema,
    utc_now,
)


def _insert_resident(conn, house_id: str, name: str, *, role: str = "resident") -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO residents(
          house_id, plot_no, section, name, role, status, employment_status, created_at, updated_at
        ) VALUES (?, ?, 'A', ?, ?, 'active', 'unknown', ?, ?)
        """,
        (house_id, house_id, name, role, now, now),
    )


def _owner_member(conn, house_id: str, name: str, member_id: str) -> None:
    now = utc_now()
    ensure_household_members_table(conn)
    conn.execute(
        """
        INSERT INTO household_members(
          id, house_id, relation, is_primary, is_primary_delegate, can_manage, view_only,
          name, title, email, phone, status, created_at, updated_at
        ) VALUES (?, ?, 'owner', 1, 0, 1, 0, ?, NULL, NULL, NULL, 'active', ?, ?)
        """,
        (member_id, house_id, name, now, now),
    )


class PlotDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "t.db")
        init_schema(self.conn)
        ensure_household_members_table(self.conn)
        ensure_household_tenants_table(self.conn)
        ensure_parking_passes_table(self.conn)
        _insert_resident(self.conn, "43", "Plot Forty Three")
        _insert_resident(self.conn, "99", "EC Admin Plot", role="admin")
        _owner_member(self.conn, "43", "Plot Forty Three", "hm_43")
        _owner_member(self.conn, "99", "EC Admin Plot", "hm_99")
        self.conn.commit()
        self.ec = {
            "houseId": "99",
            "role": "admin",
            "isPrimary": True,
            "holdsEcSeat": True,
            "isEcAdmin": True,
            "name": "EC Admin",
            "memberId": "hm_99",
        }
        self.owner = {
            "houseId": "43",
            "role": "resident",
            "isPrimary": True,
            "holdsEcSeat": False,
            "name": "Plot Forty Three",
            "memberId": "hm_43",
            "canManageHousehold": True,
        }

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_ec_snapshot_and_cross_plot_vehicle(self) -> None:
        tenant = rwa_tenants.add_tenant(
            self.conn,
            "43",
            {"name": "Renter Singh", "phone": "9812345678"},
            actor=self.ec,
        )
        item = rwa_parking.issue_pass(
            self.conn,
            actor=self.ec,
            payload={
                "kind": "member",
                "houseId": "43",
                "plate": "HP33A1234",
                "vehicleType": "car",
            },
            site_root=self.root,
        )
        self.assertEqual(item["houseId"], "43")
        self.assertEqual(item["kind"], "member")
        snap = rwa_portal.household_directory(self.conn, "43", actor=self.ec, site_root=self.root)
        self.assertTrue(snap["canManage"])
        self.assertTrue(snap["canEditProfile"])
        self.assertEqual(snap["resident"]["name"], "Plot Forty Three")
        self.assertEqual(len(snap["tenants"]), 1)
        self.assertEqual(snap["tenants"][0]["id"], tenant["id"])
        self.assertEqual(len(snap["vehicles"]), 1)
        self.assertIn("HP", snap["vehicles"][0]["plate"].upper().replace(" ", ""))

    def test_neighbor_cannot_register_other_plot(self) -> None:
        with self.assertRaises(PermissionError):
            rwa_parking.issue_pass(
                self.conn,
                actor=self.owner,
                payload={"kind": "member", "houseId": "99", "plate": "HP01A0001"},
                site_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
