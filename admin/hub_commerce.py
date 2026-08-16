"""City of Mandi commerce — shops, catalogues, orders, delivery jobs."""

from __future__ import annotations

import json
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from admin.hub_payments import (
        get_pack,
        load_payments_env,
        packs_public,
        payment_config,
        razorpay_create_order,
        razorpay_verify_signature,
    )
except ImportError:
    from hub_payments import (  # type: ignore
        get_pack,
        load_payments_env,
        packs_public,
        payment_config,
        razorpay_create_order,
        razorpay_verify_signature,
    )

COMMERCE_BOARDS = {
    "food": {
        "id": "food",
        "title": "Food & restaurants",
        "titleHi": "खाना और रेस्तराँ",
        "lede": "Order from kitchens near you. Pay on delivery.",
        "ledeHi": "आस-पास की रसोई से ऑर्डर करें। डिलीवरी पर भुगतान।",
        "categories": ("Restaurants", "Cafés", "Bakeries", "Sweets", "Other"),
        "partnerRole": "delivery_food",
        "hash": "landing-food",
    },
    "grocery": {
        "id": "grocery",
        "title": "Grocers",
        "titleHi": "किराना",
        "lede": "Kirana and daily needs, delivered locally.",
        "ledeHi": "किराना और रोज़मर्रा — स्थानीय डिलीवरी।",
        "categories": ("Grocers", "Dairy", "Vegetables", "Other"),
        "partnerRole": "delivery_grocery",
        "hash": "landing-grocery",
    },
    "hardware": {
        "id": "hardware",
        "title": "Hardware",
        "titleHi": "हार्डवेयर",
        "lede": "Hardware and building supplies.",
        "ledeHi": "हार्डवेयर और निर्माण सामग्री।",
        "categories": ("Hardware", "Sanitary", "Electrical", "Other"),
        "partnerRole": "delivery_hardware",
        "hash": "landing-hardware",
    },
    "haulage": {
        "id": "haulage",
        "title": "Trucks & tempo",
        "titleHi": "ट्रक और टेम्पो",
        "lede": "Load moves across Mandi — claim on duty.",
        "ledeHi": "मंडी में सामान ढुलाई — ड्यूटी पर दावा करें।",
        "categories": ("Tempo", "Truck", "Pickup", "Shared", "Other"),
        "partnerRole": "haulage",
        "hash": "landing-haulage",
    },
    "rentals": {
        "id": "rentals",
        "title": "To rent or sell",
        "titleHi": "किराये या बिक्री",
        "lede": "Brokers list property, vehicles, electronics, and more. Enquire or shortlist from their desk.",
        "ledeHi": "ब्रोकर संपत्ति, वाहन, इलेक्ट्रॉनिक्स आदि सूचीबद्ध करते हैं।",
        "categories": (
            "Real estate",
            "Auto",
            "Electronics",
            "Furniture",
            "Appliances",
            "Fashion",
            "Tools",
            "Industrial",
            "Other",
        ),
        "partnerRole": "",
        "hash": "landing-rentals",
        "shopLabel": "Broker",
        "itemLabel": "Listing",
        "cta": "View listings",
        "noDelivery": True,
    },
}

ORDER_STATUSES = (
    "placed",
    "accepted",
    "preparing",
    "ready",
    "out_for_delivery",
    "delivered",
    "cancelled",
    "rejected",
)

JOB_STATUSES = ("open", "claimed", "picked_up", "delivered", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def commerce_boards_meta() -> dict:
    return {
        "boards": [
            {
                "id": b["id"],
                "title": b["title"],
                "titleHi": b["titleHi"],
                "lede": b["lede"],
                "ledeHi": b["ledeHi"],
                "categories": list(b["categories"]),
                "partnerRole": b.get("partnerRole") or "",
                "hash": b["hash"],
                "shopLabel": b.get("shopLabel") or "Shop",
                "itemLabel": b.get("itemLabel") or "Item",
                "cta": b.get("cta") or "Order",
                "noDelivery": bool(b.get("noDelivery")),
            }
            for b in COMMERCE_BOARDS.values()
        ]
    }


def ensure_commerce_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hub_shops (
          id TEXT PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          publisher_id INTEGER,
          board_id TEXT NOT NULL DEFAULT 'food',
          display_name TEXT NOT NULL,
          tagline TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '',
          locality TEXT NOT NULL DEFAULT 'mandi',
          hours_json TEXT NOT NULL DEFAULT '{}',
          open_now INTEGER NOT NULL DEFAULT 1,
          fulfillment TEXT NOT NULL DEFAULT 'both',
          min_order_paise INTEGER NOT NULL DEFAULT 0,
          delivery_fee_paise INTEGER NOT NULL DEFAULT 0,
          free_delivery_above_paise INTEGER NOT NULL DEFAULT 0,
          photo TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_shops_board ON hub_shops(board_id, status, locality);
        CREATE TABLE IF NOT EXISTS hub_catalog_items (
          id TEXT PRIMARY KEY,
          shop_id TEXT NOT NULL REFERENCES hub_shops(id) ON DELETE CASCADE,
          category TEXT NOT NULL DEFAULT 'Other',
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          price_paise INTEGER NOT NULL,
          unit TEXT NOT NULL DEFAULT '',
          photo TEXT NOT NULL DEFAULT '',
          veg INTEGER NOT NULL DEFAULT 1,
          available INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_catalog_shop ON hub_catalog_items(shop_id, available, sort_order);
        CREATE TABLE IF NOT EXISTS hub_orders (
          id TEXT PRIMARY KEY,
          shop_id TEXT NOT NULL REFERENCES hub_shops(id),
          board_id TEXT NOT NULL DEFAULT 'food',
          customer_name TEXT NOT NULL DEFAULT '',
          customer_phone TEXT NOT NULL,
          address TEXT NOT NULL DEFAULT '',
          locality TEXT NOT NULL DEFAULT 'mandi',
          note TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'placed',
          fulfillment TEXT NOT NULL DEFAULT 'delivery',
          subtotal_paise INTEGER NOT NULL DEFAULT 0,
          delivery_fee_paise INTEGER NOT NULL DEFAULT 0,
          total_paise INTEGER NOT NULL DEFAULT 0,
          payment TEXT NOT NULL DEFAULT 'cod',
          provider_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_orders_shop ON hub_orders(shop_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hub_orders_phone ON hub_orders(customer_phone, created_at DESC);
        CREATE TABLE IF NOT EXISTS hub_order_items (
          id TEXT PRIMARY KEY,
          order_id TEXT NOT NULL REFERENCES hub_orders(id) ON DELETE CASCADE,
          item_id TEXT NOT NULL DEFAULT '',
          name TEXT NOT NULL,
          unit_price_paise INTEGER NOT NULL,
          qty INTEGER NOT NULL DEFAULT 1,
          line_paise INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hub_order_jobs (
          id TEXT PRIMARY KEY,
          order_id TEXT NOT NULL UNIQUE REFERENCES hub_orders(id) ON DELETE CASCADE,
          board_id TEXT NOT NULL DEFAULT 'food',
          role TEXT NOT NULL DEFAULT 'delivery_food',
          locality TEXT NOT NULL DEFAULT 'mandi',
          status TEXT NOT NULL DEFAULT 'open',
          provider_id TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_order_jobs_open
          ON hub_order_jobs(status, role, locality, created_at DESC);
        CREATE TABLE IF NOT EXISTS hub_shop_packs (
          id TEXT PRIMARY KEY,
          shop_id TEXT NOT NULL REFERENCES hub_shops(id) ON DELETE CASCADE,
          pack_id TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          amount_paise INTEGER NOT NULL DEFAULT 0,
          days INTEGER NOT NULL DEFAULT 7,
          features_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'pending',
          payment TEXT NOT NULL DEFAULT 'invoice',
          payment_status TEXT NOT NULL DEFAULT 'unpaid',
          razorpay_order_id TEXT NOT NULL DEFAULT '',
          razorpay_payment_id TEXT NOT NULL DEFAULT '',
          starts_at TEXT NOT NULL DEFAULT '',
          ends_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_shop_packs_shop
          ON hub_shop_packs(shop_id, status, ends_at);
        """
    )
    _migrate_commerce_columns(conn)
    conn.commit()


def _migrate_commerce_columns(conn: sqlite3.Connection) -> None:
    shop_cols = {row[1] for row in conn.execute("PRAGMA table_info(hub_shops)").fetchall()}
    if "featured_until" not in shop_cols:
        conn.execute("ALTER TABLE hub_shops ADD COLUMN featured_until TEXT NOT NULL DEFAULT ''")
    if "header_until" not in shop_cols:
        conn.execute("ALTER TABLE hub_shops ADD COLUMN header_until TEXT NOT NULL DEFAULT ''")
    if "pack_weight" not in shop_cols:
        conn.execute("ALTER TABLE hub_shops ADD COLUMN pack_weight INTEGER NOT NULL DEFAULT 0")
    order_cols = {row[1] for row in conn.execute("PRAGMA table_info(hub_orders)").fetchall()}
    if "payment_status" not in order_cols:
        conn.execute("ALTER TABLE hub_orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'unpaid'")
    if "razorpay_order_id" not in order_cols:
        conn.execute("ALTER TABLE hub_orders ADD COLUMN razorpay_order_id TEXT NOT NULL DEFAULT ''")
    if "razorpay_payment_id" not in order_cols:
        conn.execute("ALTER TABLE hub_orders ADD COLUMN razorpay_payment_id TEXT NOT NULL DEFAULT ''")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", str(raw or ""))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits[:15]


def paise(rupees) -> int:
    try:
        return max(0, int(round(float(rupees) * 100)))
    except (TypeError, ValueError):
        return 0


def rupees(paise_val: int) -> float:
    return round(int(paise_val or 0) / 100.0, 2)


def shop_public(row, *, item_count: int = 0) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    now = _now()
    featured_until = row["featured_until"] if "featured_until" in keys else ""
    header_until = row["header_until"] if "header_until" in keys else ""
    featured = bool(featured_until and featured_until >= now)
    header = bool(header_until and header_until >= now)
    return {
        "id": row["id"],
        "slug": row["slug"],
        "boardId": row["board_id"],
        "name": row["display_name"],
        "tagline": row["tagline"] or "",
        "summary": row["summary"] or "",
        "category": row["category"] or "",
        "address": row["address"] or "",
        "locality": row["locality"] or "mandi",
        "openNow": bool(row["open_now"]),
        "fulfillment": row["fulfillment"] or "both",
        "minOrder": rupees(row["min_order_paise"]),
        "deliveryFee": rupees(row["delivery_fee_paise"]),
        "freeDeliveryAbove": rupees(row["free_delivery_above_paise"]),
        "photo": row["photo"] if "photo" in keys else "",
        "phoneHidden": True,
        "itemCount": int(item_count or 0),
        "status": row["status"],
        "featured": featured,
        "headerSponsored": header,
        "featuredUntil": featured_until or "",
        "headerUntil": header_until or "",
        "packWeight": int(row["pack_weight"] if "pack_weight" in keys else 0) or 0,
    }


def item_public(row) -> dict:
    return {
        "id": row["id"],
        "shopId": row["shop_id"],
        "category": row["category"] or "Other",
        "name": row["name"],
        "description": row["description"] or "",
        "price": rupees(row["price_paise"]),
        "unit": row["unit"] or "",
        "photo": row["photo"] or "",
        "veg": bool(row["veg"]),
        "available": bool(row["available"]),
        "sortOrder": int(row["sort_order"] or 0),
    }


def order_public(row, items: list | None = None, *, include_phone: bool = False) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    payload = {
        "id": row["id"],
        "shopId": row["shop_id"],
        "boardId": row["board_id"],
        "customerName": row["customer_name"] or "",
        "address": row["address"] or "",
        "locality": row["locality"] or "mandi",
        "note": row["note"] or "",
        "status": row["status"],
        "fulfillment": row["fulfillment"] or "delivery",
        "subtotal": rupees(row["subtotal_paise"]),
        "deliveryFee": rupees(row["delivery_fee_paise"]),
        "total": rupees(row["total_paise"]),
        "payment": row["payment"] or "cod",
        "paymentStatus": (row["payment_status"] if "payment_status" in keys else "")
        or ("paid" if (row["payment"] or "cod") == "cod" else "unpaid"),
        "providerId": row["provider_id"] if "provider_id" in keys else "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "items": items or [],
    }
    if include_phone:
        payload["customerPhone"] = row["customer_phone"]
    return payload


def pack_public(row) -> dict:
    try:
        features = json.loads(row["features_json"] or "[]")
    except json.JSONDecodeError:
        features = []
    return {
        "id": row["id"],
        "shopId": row["shop_id"],
        "packId": row["pack_id"],
        "title": row["title"],
        "amount": rupees(row["amount_paise"]),
        "days": int(row["days"] or 0),
        "features": features if isinstance(features, list) else [],
        "status": row["status"],
        "payment": row["payment"] or "",
        "paymentStatus": row["payment_status"] or "",
        "startsAt": row["starts_at"] or "",
        "endsAt": row["ends_at"] or "",
        "createdAt": row["created_at"],
    }


def apply_pack_to_shop(conn: sqlite3.Connection, shop_id: str, pack: dict, *, now: str) -> tuple[str, str]:
    """Activate pack entitlements on the shop. Returns (starts_at, ends_at)."""
    days = int(pack.get("days") or 7)
    ends = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    shop = conn.execute("SELECT * FROM hub_shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return now, ends
    keys = set(shop.keys())
    featured_until = shop["featured_until"] if "featured_until" in keys else ""
    header_until = shop["header_until"] if "header_until" in keys else ""
    weight = int(shop["pack_weight"] if "pack_weight" in keys else 0) or 0
    features = pack.get("features") or []
    if "board_featured" in features:
        featured_until = max(featured_until or "", ends)
    if "header" in features:
        header_until = max(header_until or "", ends)
    weight = max(weight, int(pack.get("weight") or 0))
    conn.execute(
        """
        UPDATE hub_shops SET featured_until = ?, header_until = ?, pack_weight = ?, updated_at = ?
        WHERE id = ?
        """,
        (featured_until, header_until, weight, now, shop_id),
    )
    return now, ends


def active_header_pack_ads(db_factory) -> list[dict]:
    """Ads derived from active header shop packs (for sponsored strip)."""
    now = _now()
    conn = db_factory()
    try:
        ensure_commerce_tables(conn)
        rows = conn.execute(
            """
            SELECT * FROM hub_shops
            WHERE status = 'active' AND header_until != '' AND header_until >= ?
            ORDER BY pack_weight DESC, display_name ASC LIMIT 20
            """,
            (now,),
        ).fetchall()
    finally:
        conn.close()
    ads = []
    for row in rows:
        ads.append({
            "id": f"pack-{row['slug']}",
            "title": row["display_name"],
            "subtitle": row["tagline"] or "Order on City of Mandi · COD",
            "animation": "marquee",
            "imageUrl": "",
            "linkUrl": f"/b/{row['slug']}",
            "sponsor": "Sponsored shop",
            "active": True,
            "weight": max(2, int(row["pack_weight"] or 2)),
            "startsAt": "",
            "endsAt": row["header_until"] or "",
        })
    return ads


def register_commerce(app, *, db, require_publisher, require_provider, normalize_locality_fn, seed_dir: pathlib.Path | None = None, data_dir: pathlib.Path | None = None):
    """Wire commerce HTTP routes into the civic hub Flask app."""
    from flask import g, jsonify, request, session

    load_payments_env(data_dir)
    ensure = ensure_commerce_tables

    def conn_db():
        c = db()
        ensure(c)
        return c

    def _seed_demo_shop(conn: sqlite3.Connection) -> None:
        """Seed sample shops/catalogues for each commerce board (idempotent)."""
        now = _now()
        demos = [
            {
                "slug": "demo-rasoi",
                "board": "food",
                "name": "Demo Rasoi",
                "tagline": "Home-style thalis near Seri",
                "summary": "Sample kitchen for City of Mandi food board — COD orders.",
                "category": "Restaurants",
                "address": "Near Seri · Mandi town",
                "min": 10000,
                "fee": 2000,
                "free": 30000,
                "items": [
                    ("cat_thali", "Thali", "Veg thali", "Dal, sabzi, rice, 2 roti", 12000, 1, ""),
                    ("cat_momos", "Snacks", "Veg momos (8pc)", "Steamed", 8000, 1, ""),
                    ("cat_chai", "Drinks", "Masala chai", "Kulhad", 2000, 1, ""),
                    ("cat_paratha", "Tandoor", "Aloo paratha", "With curd", 5000, 1, ""),
                ],
            },
            {
                "slug": "demo-kirana",
                "board": "grocery",
                "name": "Demo Kirana",
                "tagline": "Daily needs from the gali",
                "summary": "Sample kirana for City of Mandi grocery board — COD delivery.",
                "category": "Grocers",
                "address": "Lower Bazaar · Mandi",
                "min": 5000,
                "fee": 1500,
                "free": 25000,
                "items": [
                    ("groc_atta", "Staples", "Atta 5kg", "Whole wheat", 22000, 1, "bag"),
                    ("groc_rice", "Staples", "Rice 1kg", "Basmati", 12000, 1, "kg"),
                    ("groc_milk", "Dairy", "Milk 1L", "Full cream", 6000, 1, "L"),
                    ("groc_oil", "Staples", "Mustard oil 1L", "Cold pressed", 18000, 1, "L"),
                    ("groc_onion", "Vegetables", "Onion 1kg", "Fresh", 4000, 1, "kg"),
                ],
            },
            {
                "slug": "demo-hardware",
                "board": "hardware",
                "name": "Demo Hardware",
                "tagline": "Nuts, pipes, and paint",
                "summary": "Sample hardware counter — COD / pickup.",
                "category": "Hardware",
                "address": "Industrial area · Mandi",
                "min": 0,
                "fee": 3000,
                "free": 50000,
                "items": [
                    ("hw_cement", "Building", "Cement bag 50kg", "OPC", 42000, 0, "bag"),
                    ("hw_pipe", "Sanitary", "PVC pipe 1\" × 3m", "ISI", 18000, 0, "pc"),
                    ("hw_wire", "Electrical", "Copper wire 1.5mm (90m)", "Roll", 95000, 0, "roll"),
                    ("hw_paint", "Paint", "Emulsion 1L", "White", 35000, 0, "L"),
                ],
            },
            {
                "slug": "demo-tempo",
                "board": "haulage",
                "name": "Demo Tempo",
                "tagline": "Load moves across Mandi",
                "summary": "Sample haulage desk — book a tempo or truck, COD.",
                "category": "Tempo",
                "address": "Seri stand · Mandi",
                "min": 0,
                "fee": 0,
                "free": 0,
                "items": [
                    ("haul_tempo_local", "Tempo", "Tempo · local (2hr)", "Within Mandi town", 80000, 0, "trip"),
                    ("haul_tempo_out", "Tempo", "Tempo · outstation", "Within district", 250000, 0, "trip"),
                    ("haul_truck", "Truck", "Truck · half day", "Building material", 450000, 0, "trip"),
                    ("haul_pickup", "Pickup", "Pickup · one trip", "Furniture / boxes", 120000, 0, "trip"),
                ],
            },
            {
                "slug": "demo-broker",
                "board": "rentals",
                "name": "Demo Mandi Brokers",
                "tagline": "Rent · sell · Mandi valley",
                "summary": "Sample broker desk — real estate, auto, electronics, and more. Shortlist listings; enquire with the broker.",
                "category": "Real estate",
                "address": "Indira Market · Mandi",
                "min": 0,
                "fee": 0,
                "free": 0,
                "items": [
                    ("rent_flat_2bhk", "Real estate", "2 BHK flat · for rent", "Near PAC · water + parking", 1200000, 0, "rent/mo"),
                    ("sale_plot_pandoh", "Real estate", "Plot 5 biswa · for sale", "Pandoh road · clear title", 250000000, 0, "sale"),
                    ("sale_swift", "Auto", "Maruti Swift 2018 · for sale", "Petrol · 62k km · single owner", 38500000, 0, "sale"),
                    ("rent_activa", "Auto", "Activa · for rent (day)", "Scooter with helmet", 50000, 0, "rent/day"),
                    ("sale_fridge", "Appliances", "Double-door fridge · for sale", "Almost new · Mandi town", 1800000, 0, "sale"),
                    ("sale_laptop", "Electronics", "Laptop i5 · for sale", "8GB / 512SSD · charger included", 2800000, 0, "sale"),
                    ("sale_sofa", "Furniture", "3-seater sofa · for sale", "Fabric · pickup from Ner Chowk", 950000, 0, "sale"),
                    ("rent_shop", "Industrial", "Shop space · for rent", "Indira Market · 12×18 ft", 2500000, 0, "rent/mo"),
                ],
            },
        ]
        for demo in demos:
            exists = conn.execute("SELECT id FROM hub_shops WHERE slug = ?", (demo["slug"],)).fetchone()
            if not exists:
                sid = "shop_" + secrets.token_hex(6)
                conn.execute(
                    """
                    INSERT INTO hub_shops (
                      id, slug, publisher_id, board_id, display_name, tagline, summary, category,
                      phone, address, locality, open_now, fulfillment, min_order_paise,
                      delivery_fee_paise, free_delivery_above_paise, status, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, '', ?, 'mandi', 1, 'both', ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        sid,
                        demo["slug"],
                        demo["board"],
                        demo["name"],
                        demo["tagline"],
                        demo["summary"],
                        demo["category"],
                        demo["address"],
                        demo["min"],
                        demo["fee"],
                        demo["free"],
                        now,
                        now,
                    ),
                )
            else:
                sid = exists["id"]
            for iid, cat, name, desc, price, veg, unit in demo["items"]:
                row = conn.execute("SELECT id FROM hub_catalog_items WHERE id = ?", (iid,)).fetchone()
                if row:
                    continue
                conn.execute(
                    """
                    INSERT INTO hub_catalog_items (
                      id, shop_id, category, name, description, price_paise, unit, veg, available, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                    """,
                    (iid, sid, cat, name, desc, price, unit, veg, now, now),
                )
        conn.commit()

    @app.get("/api/hub/commerce/boards")
    def commerce_boards():
        return jsonify({"ok": True, **commerce_boards_meta()})

    @app.get("/api/hub/commerce/shops")
    def commerce_shops_list():
        board_id = str(request.args.get("board") or "food").strip().lower()
        if board_id not in COMMERCE_BOARDS:
            board_id = "food"
        locality = request.args.get("locality") or ""
        conn = conn_db()
        try:
            _seed_demo_shop(conn)
            sql = "SELECT * FROM hub_shops WHERE status = 'active' AND board_id = ?"
            params: list = [board_id]
            if locality:
                sql += " AND locality = ?"
                params.append(normalize_locality_fn(locality))
            sql += " ORDER BY open_now DESC, display_name ASC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
            # Featured / sponsored packs first
            now = _now()
            def _sort_key(r):
                keys = set(r.keys())
                feat = (r["featured_until"] if "featured_until" in keys else "") or ""
                weight = int(r["pack_weight"] if "pack_weight" in keys else 0) or 0
                return (0 if feat >= now else 1, -weight, 0 if r["open_now"] else 1, (r["display_name"] or "").lower())
            rows = sorted(rows, key=_sort_key)
            out = []
            for row in rows:
                n = conn.execute(
                    "SELECT COUNT(*) AS n FROM hub_catalog_items WHERE shop_id = ? AND available = 1",
                    (row["id"],),
                ).fetchone()["n"]
                out.append(shop_public(row, item_count=n))
        finally:
            conn.close()
        return jsonify({"ok": True, "boardId": board_id, "shops": out, **commerce_boards_meta()})

    @app.get("/api/hub/commerce/shops/<slug>")
    def commerce_shop_detail(slug: str):
        slug = re.sub(r"[^a-z0-9-]+", "", (slug or "").lower())
        conn = conn_db()
        try:
            _seed_demo_shop(conn)
            row = conn.execute(
                "SELECT * FROM hub_shops WHERE slug = ? AND status = 'active'",
                (slug,),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Shop not found"}), 404
            items = conn.execute(
                """
                SELECT * FROM hub_catalog_items
                WHERE shop_id = ? AND available = 1
                ORDER BY sort_order ASC, category ASC, name ASC
                """,
                (row["id"],),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "ok": True,
            "shop": shop_public(row, item_count=len(items)),
            "items": [item_public(i) for i in items],
        })

    @app.get("/api/hub/commerce/merchant/shop")
    @require_publisher
    def commerce_merchant_shop_get():
        conn = conn_db()
        try:
            row = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? ORDER BY updated_at DESC LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not row:
                return jsonify({"ok": True, "shop": None, "items": [], **commerce_boards_meta()})
            items = conn.execute(
                "SELECT * FROM hub_catalog_items WHERE shop_id = ? ORDER BY sort_order, name",
                (row["id"],),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "ok": True,
            "shop": shop_public(row, item_count=len(items)),
            "items": [item_public(i) for i in items],
            **commerce_boards_meta(),
        })

    @app.post("/api/hub/commerce/merchant/shop")
    @require_publisher
    def commerce_merchant_shop_save():
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "").strip()[:80]
        if len(name) < 2:
            return jsonify({"ok": False, "error": "Shop name required"}), 400
        board_id = str(body.get("boardId") or "food").strip().lower()
        if board_id not in COMMERCE_BOARDS:
            board_id = "food"
        slug = re.sub(r"[^a-z0-9-]+", "-", str(body.get("slug") or name).lower()).strip("-")[:48]
        if not slug:
            slug = "shop-" + secrets.token_hex(3)
        now = _now()
        conn = conn_db()
        try:
            existing = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE hub_shops SET
                      display_name = ?, tagline = ?, summary = ?, category = ?, address = ?,
                      locality = ?, board_id = ?, open_now = ?, fulfillment = ?,
                      min_order_paise = ?, delivery_fee_paise = ?, free_delivery_above_paise = ?,
                      updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        str(body.get("tagline") or "")[:120],
                        str(body.get("summary") or "")[:600],
                        str(body.get("category") or "Other")[:40],
                        str(body.get("address") or "")[:200],
                        normalize_locality_fn(body.get("locality")),
                        board_id,
                        1 if body.get("openNow", True) else 0,
                        str(body.get("fulfillment") or "both")[:20],
                        paise(body.get("minOrder") or 0),
                        paise(body.get("deliveryFee") or 0),
                        paise(body.get("freeDeliveryAbove") or 0),
                        now,
                        existing["id"],
                    ),
                )
                sid = existing["id"]
            else:
                clash = conn.execute("SELECT id FROM hub_shops WHERE slug = ?", (slug,)).fetchone()
                if clash:
                    slug = f"{slug}-{secrets.token_hex(2)}"
                sid = "shop_" + secrets.token_hex(6)
                conn.execute(
                    """
                    INSERT INTO hub_shops (
                      id, slug, publisher_id, board_id, display_name, tagline, summary, category,
                      phone, address, locality, open_now, fulfillment, min_order_paise,
                      delivery_fee_paise, free_delivery_above_paise, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        sid, slug, int(g.publisher["id"]), board_id, name,
                        str(body.get("tagline") or "")[:120],
                        str(body.get("summary") or "")[:600],
                        str(body.get("category") or "Other")[:40],
                        str(body.get("address") or "")[:200],
                        normalize_locality_fn(body.get("locality")),
                        1 if body.get("openNow", True) else 0,
                        str(body.get("fulfillment") or "both")[:20],
                        paise(body.get("minOrder") or 0),
                        paise(body.get("deliveryFee") or 0),
                        paise(body.get("freeDeliveryAbove") or 0),
                        now, now,
                    ),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_shops WHERE id = ?", (sid,)).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "shop": shop_public(row)})

    @app.post("/api/hub/commerce/merchant/items")
    @require_publisher
    def commerce_merchant_item_save():
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "").strip()[:80]
        if len(name) < 1:
            return jsonify({"ok": False, "error": "Item name required"}), 400
        price = paise(body.get("price"))
        if price < 1:
            return jsonify({"ok": False, "error": "Enter a price"}), 400
        now = _now()
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "Create your shop first"}), 400
            item_id = str(body.get("id") or "").strip()
            if item_id:
                conn.execute(
                    """
                    UPDATE hub_catalog_items SET
                      category = ?, name = ?, description = ?, price_paise = ?, unit = ?,
                      veg = ?, available = ?, updated_at = ?
                    WHERE id = ? AND shop_id = ?
                    """,
                    (
                        str(body.get("category") or "Other")[:40],
                        name,
                        str(body.get("description") or "")[:240],
                        price,
                        str(body.get("unit") or "")[:24],
                        1 if body.get("veg", True) else 0,
                        1 if body.get("available", True) else 0,
                        now,
                        item_id,
                        shop["id"],
                    ),
                )
            else:
                item_id = "ci_" + secrets.token_hex(6)
                conn.execute(
                    """
                    INSERT INTO hub_catalog_items (
                      id, shop_id, category, name, description, price_paise, unit, veg, available,
                      sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        item_id, shop["id"],
                        str(body.get("category") or "Other")[:40],
                        name,
                        str(body.get("description") or "")[:240],
                        price,
                        str(body.get("unit") or "")[:24],
                        1 if body.get("veg", True) else 0,
                        1 if body.get("available", True) else 0,
                        now, now,
                    ),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_catalog_items WHERE id = ?", (item_id,)).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "item": item_public(row)})

    @app.delete("/api/hub/commerce/merchant/items/<item_id>")
    @require_publisher
    def commerce_merchant_item_delete(item_id: str):
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT id FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "No shop"}), 404
            conn.execute(
                "DELETE FROM hub_catalog_items WHERE id = ? AND shop_id = ?",
                (item_id, shop["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})

    @app.get("/api/hub/commerce/merchant/orders")
    @require_publisher
    def commerce_merchant_orders():
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": True, "orders": []})
            rows = conn.execute(
                """
                SELECT * FROM hub_orders WHERE shop_id = ?
                ORDER BY created_at DESC LIMIT 80
                """,
                (shop["id"],),
            ).fetchall()
            orders = []
            for row in rows:
                items = conn.execute(
                    "SELECT name, unit_price_paise, qty, line_paise FROM hub_order_items WHERE order_id = ?",
                    (row["id"],),
                ).fetchall()
                item_rows = [
                    {
                        "name": i["name"],
                        "price": rupees(i["unit_price_paise"]),
                        "qty": i["qty"],
                        "line": rupees(i["line_paise"]),
                    }
                    for i in items
                ]
                orders.append(order_public(row, item_rows, include_phone=True))
        finally:
            conn.close()
        return jsonify({"ok": True, "orders": orders})

    @app.post("/api/hub/commerce/merchant/orders/<order_id>/status")
    @require_publisher
    def commerce_merchant_order_status(order_id: str):
        body = request.get_json(force=True, silent=True) or {}
        status = str(body.get("status") or "").strip().lower()
        if status not in ORDER_STATUSES:
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        now = _now()
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "No shop"}), 404
            order = conn.execute(
                "SELECT * FROM hub_orders WHERE id = ? AND shop_id = ?",
                (order_id, shop["id"]),
            ).fetchone()
            if not order:
                return jsonify({"ok": False, "error": "Order not found"}), 404
            conn.execute(
                "UPDATE hub_orders SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, order_id),
            )
            if status in ("accepted", "preparing", "ready") and order["fulfillment"] == "delivery":
                job = conn.execute("SELECT id FROM hub_order_jobs WHERE order_id = ?", (order_id,)).fetchone()
                board_meta = COMMERCE_BOARDS.get(order["board_id"], COMMERCE_BOARDS["food"])
                role = board_meta.get("partnerRole") or ""
                if not job and role and not board_meta.get("noDelivery"):
                    jid = "oj_" + secrets.token_hex(6)
                    conn.execute(
                        """
                        INSERT INTO hub_order_jobs (
                          id, order_id, board_id, role, locality, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
                        """,
                        (jid, order_id, order["board_id"], role, order["locality"] or "mandi", now, now),
                    )
            if status in ("cancelled", "rejected", "delivered"):
                conn.execute(
                    "UPDATE hub_order_jobs SET status = ?, updated_at = ? WHERE order_id = ? AND status = 'open'",
                    ("cancelled" if status != "delivered" else "delivered", now, order_id),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_orders WHERE id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "order": order_public(row, include_phone=True)})

    @app.post("/api/hub/commerce/orders")
    def commerce_place_order():
        body = request.get_json(force=True, silent=True) or {}
        slug = re.sub(r"[^a-z0-9-]+", "", str(body.get("slug") or "").lower())
        phone = normalize_phone(body.get("phone") or "")
        name = str(body.get("name") or "").strip()[:80]
        address = str(body.get("address") or "").strip()[:240]
        note = str(body.get("note") or "").strip()[:400]
        fulfillment = str(body.get("fulfillment") or "delivery").strip().lower()
        if fulfillment not in ("delivery", "pickup"):
            fulfillment = "delivery"
        lines = body.get("items") if isinstance(body.get("items"), list) else []
        if len(phone) < 10:
            return jsonify({"ok": False, "error": "Enter a valid mobile number"}), 400
        if fulfillment == "delivery" and len(address) < 4:
            return jsonify({"ok": False, "error": "Enter a delivery address"}), 400
        if not lines:
            return jsonify({"ok": False, "error": "Cart is empty"}), 400
        if not name:
            name = f"Guest · {phone[-4:]}"
        now = _now()
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE slug = ? AND status = 'active'",
                (slug,),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "Shop not found"}), 404
            if not shop["open_now"]:
                return jsonify({"ok": False, "error": "Shop is closed right now"}), 400
            subtotal = 0
            cleaned = []
            for line in lines[:40]:
                if not isinstance(line, dict):
                    continue
                iid = str(line.get("id") or "").strip()
                qty = max(1, min(99, int(line.get("qty") or 1)))
                item = conn.execute(
                    "SELECT * FROM hub_catalog_items WHERE id = ? AND shop_id = ? AND available = 1",
                    (iid, shop["id"]),
                ).fetchone()
                if not item:
                    continue
                line_paise = int(item["price_paise"]) * qty
                subtotal += line_paise
                cleaned.append((item, qty, line_paise))
            if not cleaned:
                return jsonify({"ok": False, "error": "No available items in cart"}), 400
            if subtotal < int(shop["min_order_paise"] or 0):
                return jsonify({
                    "ok": False,
                    "error": f"Minimum order is ₹{rupees(shop['min_order_paise'])}",
                }), 400
            fee = 0
            if fulfillment == "delivery":
                fee = int(shop["delivery_fee_paise"] or 0)
                free_above = int(shop["free_delivery_above_paise"] or 0)
                if free_above and subtotal >= free_above:
                    fee = 0
            total = subtotal + fee
            oid = "ord_" + secrets.token_hex(6)
            locality = normalize_locality_fn(body.get("locality") or shop["locality"])
            pay_method = str(body.get("payment") or "cod").strip().lower()
            cfg = payment_config()
            if pay_method not in ("cod", "online", "demo"):
                pay_method = "cod"
            if pay_method == "online" and not cfg["onlineEnabled"]:
                if cfg["demoEnabled"]:
                    pay_method = "demo"
                else:
                    return jsonify({"ok": False, "error": "Online payment is not available yet — use COD"}), 400
            if pay_method == "demo" and not cfg["demoEnabled"] and not cfg["onlineEnabled"]:
                pay_method = "cod"
            payment_status = "unpaid"
            rzp_order_id = ""
            if pay_method == "cod":
                payment_status = "cod"
            conn.execute(
                """
                INSERT INTO hub_orders (
                  id, shop_id, board_id, customer_name, customer_phone, address, locality, note,
                  status, fulfillment, subtotal_paise, delivery_fee_paise, total_paise, payment,
                  payment_status, razorpay_order_id, razorpay_payment_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'placed', ?, ?, ?, ?, ?, ?, '', '', ?, ?)
                """,
                (
                    oid, shop["id"], shop["board_id"], name, phone, address, locality, note,
                    fulfillment, subtotal, fee, total, pay_method, payment_status, now, now,
                ),
            )
            for item, qty, line_paise in cleaned:
                conn.execute(
                    """
                    INSERT INTO hub_order_items (
                      id, order_id, item_id, name, unit_price_paise, qty, line_paise
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "oi_" + secrets.token_hex(5),
                        oid,
                        item["id"],
                        item["name"],
                        item["price_paise"],
                        qty,
                        line_paise,
                    ),
                )
            rzp_payload = None
            if pay_method == "online":
                try:
                    rzp = razorpay_create_order(
                        amount_paise=total,
                        receipt=oid,
                        notes={"kind": "order", "orderId": oid, "slug": slug},
                    )
                    rzp_order_id = str(rzp.get("id") or "")
                    conn.execute(
                        "UPDATE hub_orders SET razorpay_order_id = ?, updated_at = ? WHERE id = ?",
                        (rzp_order_id, now, oid),
                    )
                    rzp_payload = {
                        "keyId": cfg["keyId"],
                        "orderId": rzp_order_id,
                        "amount": total,
                        "currency": "INR",
                        "name": "City of Mandi",
                        "description": shop["display_name"],
                    }
                except RuntimeError as exc:
                    conn.execute("DELETE FROM hub_order_items WHERE order_id = ?", (oid,))
                    conn.execute("DELETE FROM hub_orders WHERE id = ?", (oid,))
                    conn.commit()
                    return jsonify({"ok": False, "error": str(exc)}), 502
            elif pay_method == "demo":
                # Immediate paid for local/demo smoke without Razorpay keys
                conn.execute(
                    "UPDATE hub_orders SET payment_status = 'paid', payment = 'demo', updated_at = ? WHERE id = ?",
                    (now, oid),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_orders WHERE id = ?", (oid,)).fetchone()
            items = [
                {"name": i[0]["name"], "price": rupees(i[0]["price_paise"]), "qty": i[1], "line": rupees(i[2])}
                for i in cleaned
            ]
        finally:
            conn.close()
        out = {"ok": True, "order": order_public(row, items, include_phone=True)}
        if rzp_payload:
            out["razorpay"] = rzp_payload
        return jsonify(out)

    @app.get("/api/hub/commerce/orders/<order_id>")
    def commerce_order_get(order_id: str):
        phone = normalize_phone(request.args.get("phone") or "")
        conn = conn_db()
        try:
            row = conn.execute("SELECT * FROM hub_orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Order not found"}), 404
            # Public track if phone matches; merchants use their desk
            include = False
            if phone and phone == row["customer_phone"]:
                include = True
            pub_id = session.get("publisher_id")
            if pub_id:
                shop = conn.execute(
                    "SELECT id FROM hub_shops WHERE id = ? AND publisher_id = ?",
                    (row["shop_id"], int(pub_id)),
                ).fetchone()
                if shop:
                    include = True
            items = conn.execute(
                "SELECT name, unit_price_paise, qty, line_paise FROM hub_order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()
            item_rows = [
                {"name": i["name"], "price": rupees(i["unit_price_paise"]), "qty": i["qty"], "line": rupees(i["line_paise"])}
                for i in items
            ]
            shop = conn.execute("SELECT display_name, slug FROM hub_shops WHERE id = ?", (row["shop_id"],)).fetchone()
            job = conn.execute("SELECT status, provider_id FROM hub_order_jobs WHERE order_id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
        payload = order_public(row, item_rows, include_phone=include)
        payload["shopName"] = shop["display_name"] if shop else ""
        payload["shopSlug"] = shop["slug"] if shop else ""
        payload["jobStatus"] = job["status"] if job else ""
        return jsonify({"ok": True, "order": payload})

    @app.get("/api/hub/commerce/jobs")
    @require_provider
    def commerce_jobs_open():
        role = str(request.args.get("role") or "delivery_food").strip()
        locality = request.args.get("locality") or ""
        conn = conn_db()
        try:
            sql = """
                SELECT j.*, o.address, o.locality AS order_locality, o.total_paise, o.customer_name,
                       s.display_name AS shop_name, s.address AS shop_address
                FROM hub_order_jobs j
                JOIN hub_orders o ON o.id = j.order_id
                JOIN hub_shops s ON s.id = o.shop_id
                WHERE j.status = 'open' AND j.role = ?
            """
            params: list = [role]
            if locality:
                sql += " AND j.locality = ?"
                params.append(normalize_locality_fn(locality))
            sql += " ORDER BY j.created_at ASC LIMIT 50"
            rows = conn.execute(sql, params).fetchall()
            jobs = [
                {
                    "id": r["id"],
                    "orderId": r["order_id"],
                    "shopName": r["shop_name"],
                    "shopAddress": r["shop_address"] or "",
                    "dropAddress": r["address"] or "",
                    "locality": r["order_locality"] or r["locality"],
                    "total": rupees(r["total_paise"]),
                    "customerName": r["customer_name"] or "",
                    "createdAt": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()
        return jsonify({"ok": True, "jobs": jobs})

    @app.post("/api/hub/commerce/jobs/<job_id>/claim")
    @require_provider
    def commerce_job_claim(job_id: str):
        now = _now()
        provider = g.hub_provider
        conn = conn_db()
        try:
            job = conn.execute(
                "SELECT * FROM hub_order_jobs WHERE id = ? AND status = 'open'",
                (job_id,),
            ).fetchone()
            if not job:
                return jsonify({"ok": False, "error": "Job no longer open"}), 409
            conn.execute(
                """
                UPDATE hub_order_jobs SET status = 'claimed', provider_id = ?, updated_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (provider["id"], now, job_id),
            )
            if conn.total_changes < 1:
                return jsonify({"ok": False, "error": "Someone else claimed this job"}), 409
            conn.execute(
                """
                UPDATE hub_orders SET provider_id = ?, status = 'out_for_delivery', updated_at = ?
                WHERE id = ?
                """,
                (provider["id"], now, job["order_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "jobId": job_id, "orderId": job["order_id"]})

    @app.get("/api/hub/commerce/payments/config")
    def commerce_payments_config():
        return jsonify({"ok": True, **payment_config()})

    @app.post("/api/hub/commerce/orders/<order_id>/pay/verify")
    def commerce_order_pay_verify(order_id: str):
        body = request.get_json(force=True, silent=True) or {}
        phone = normalize_phone(body.get("phone") or request.args.get("phone") or "")
        cfg = payment_config()
        now = _now()
        conn = conn_db()
        try:
            row = conn.execute("SELECT * FROM hub_orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Order not found"}), 404
            if phone and phone != row["customer_phone"]:
                return jsonify({"ok": False, "error": "Phone does not match order"}), 403
            if (row["payment_status"] if "payment_status" in set(row.keys()) else "") == "paid":
                return jsonify({"ok": True, "order": order_public(row, include_phone=True)})
            if cfg["onlineEnabled"]:
                rzp_order = str(body.get("razorpayOrderId") or row["razorpay_order_id"] or "")
                rzp_pay = str(body.get("razorpayPaymentId") or "")
                sig = str(body.get("razorpaySignature") or "")
                if not razorpay_verify_signature(order_id=rzp_order, payment_id=rzp_pay, signature=sig):
                    return jsonify({"ok": False, "error": "Payment signature invalid"}), 400
                conn.execute(
                    """
                    UPDATE hub_orders SET payment_status = 'paid', payment = 'online',
                      razorpay_order_id = ?, razorpay_payment_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (rzp_order, rzp_pay, now, order_id),
                )
            elif cfg["demoEnabled"] or str(body.get("demo") or "") in ("1", "true"):
                if not cfg["demoEnabled"]:
                    return jsonify({"ok": False, "error": "Demo payments disabled"}), 400
                conn.execute(
                    "UPDATE hub_orders SET payment_status = 'paid', payment = 'demo', updated_at = ? WHERE id = ?",
                    (now, order_id),
                )
            else:
                return jsonify({"ok": False, "error": "Online payment is not configured"}), 400
            conn.commit()
            row = conn.execute("SELECT * FROM hub_orders WHERE id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "order": order_public(row, include_phone=True)})

    @app.get("/api/hub/commerce/packs")
    def commerce_packs_catalog():
        return jsonify({"ok": True, "packs": packs_public(), **payment_config()})

    @app.get("/api/hub/commerce/merchant/packs")
    @require_publisher
    def commerce_merchant_packs():
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": True, "shop": None, "packs": packs_public(), "purchases": [], **payment_config()})
            rows = conn.execute(
                """
                SELECT * FROM hub_shop_packs WHERE shop_id = ?
                ORDER BY created_at DESC LIMIT 40
                """,
                (shop["id"],),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "ok": True,
            "shop": shop_public(shop),
            "packs": packs_public(),
            "purchases": [pack_public(r) for r in rows],
            **payment_config(),
        })

    @app.post("/api/hub/commerce/merchant/packs")
    @require_publisher
    def commerce_merchant_pack_buy():
        body = request.get_json(force=True, silent=True) or {}
        pack = get_pack(str(body.get("packId") or ""))
        if not pack:
            return jsonify({"ok": False, "error": "Unknown pack"}), 400
        cfg = payment_config()
        pay_method = str(body.get("payment") or "").strip().lower()
        if not pay_method:
            pay_method = "online" if cfg["onlineEnabled"] else ("demo" if cfg["demoEnabled"] else "invoice")
        if pay_method == "online" and not cfg["onlineEnabled"]:
            pay_method = "demo" if cfg["demoEnabled"] else "invoice"
        now = _now()
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "Create your shop first"}), 400
            pid = "pk_" + secrets.token_hex(6)
            amount = paise(pack["price"])
            status = "pending"
            payment_status = "unpaid"
            starts = ""
            ends = ""
            rzp_payload = None
            if pay_method in ("demo", "invoice"):
                # Demo: activate now. Invoice: activate now, settle offline with ops.
                starts, ends = apply_pack_to_shop(conn, shop["id"], pack, now=now)
                status = "active"
                payment_status = "paid" if pay_method == "demo" else "invoiced"
            conn.execute(
                """
                INSERT INTO hub_shop_packs (
                  id, shop_id, pack_id, title, amount_paise, days, features_json, status, payment,
                  payment_status, razorpay_order_id, razorpay_payment_id, starts_at, ends_at,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?, ?)
                """,
                (
                    pid, shop["id"], pack["id"], pack["title"], amount, pack["days"],
                    json.dumps(list(pack["features"])), status, pay_method, payment_status,
                    starts, ends, now, now,
                ),
            )
            if pay_method == "online":
                try:
                    rzp = razorpay_create_order(
                        amount_paise=amount,
                        receipt=pid,
                        notes={"kind": "pack", "packPurchaseId": pid, "shopId": shop["id"]},
                    )
                    rzp_order_id = str(rzp.get("id") or "")
                    conn.execute(
                        "UPDATE hub_shop_packs SET razorpay_order_id = ? WHERE id = ?",
                        (rzp_order_id, pid),
                    )
                    rzp_payload = {
                        "keyId": cfg["keyId"],
                        "orderId": rzp_order_id,
                        "amount": amount,
                        "currency": "INR",
                        "name": "City of Mandi",
                        "description": pack["title"],
                    }
                except RuntimeError as exc:
                    conn.execute("DELETE FROM hub_shop_packs WHERE id = ?", (pid,))
                    conn.commit()
                    return jsonify({"ok": False, "error": str(exc)}), 502
            conn.commit()
            row = conn.execute("SELECT * FROM hub_shop_packs WHERE id = ?", (pid,)).fetchone()
            shop = conn.execute("SELECT * FROM hub_shops WHERE id = ?", (shop["id"],)).fetchone()
        finally:
            conn.close()
        out = {"ok": True, "purchase": pack_public(row), "shop": shop_public(shop)}
        if rzp_payload:
            out["razorpay"] = rzp_payload
        return jsonify(out)

    @app.post("/api/hub/commerce/merchant/packs/<purchase_id>/verify")
    @require_publisher
    def commerce_merchant_pack_verify(purchase_id: str):
        body = request.get_json(force=True, silent=True) or {}
        cfg = payment_config()
        now = _now()
        conn = conn_db()
        try:
            shop = conn.execute(
                "SELECT * FROM hub_shops WHERE publisher_id = ? LIMIT 1",
                (int(g.publisher["id"]),),
            ).fetchone()
            if not shop:
                return jsonify({"ok": False, "error": "No shop"}), 404
            row = conn.execute(
                "SELECT * FROM hub_shop_packs WHERE id = ? AND shop_id = ?",
                (purchase_id, shop["id"]),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Purchase not found"}), 404
            if row["status"] == "active" and row["payment_status"] in ("paid", "invoiced"):
                return jsonify({"ok": True, "purchase": pack_public(row), "shop": shop_public(shop)})
            pack = get_pack(row["pack_id"])
            if not pack:
                return jsonify({"ok": False, "error": "Unknown pack"}), 400
            if cfg["onlineEnabled"]:
                rzp_order = str(body.get("razorpayOrderId") or row["razorpay_order_id"] or "")
                rzp_pay = str(body.get("razorpayPaymentId") or "")
                sig = str(body.get("razorpaySignature") or "")
                if not razorpay_verify_signature(order_id=rzp_order, payment_id=rzp_pay, signature=sig):
                    return jsonify({"ok": False, "error": "Payment signature invalid"}), 400
                starts, ends = apply_pack_to_shop(conn, shop["id"], pack, now=now)
                conn.execute(
                    """
                    UPDATE hub_shop_packs SET status = 'active', payment = 'online', payment_status = 'paid',
                      razorpay_order_id = ?, razorpay_payment_id = ?, starts_at = ?, ends_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (rzp_order, rzp_pay, starts, ends, now, purchase_id),
                )
            elif cfg["demoEnabled"]:
                starts, ends = apply_pack_to_shop(conn, shop["id"], pack, now=now)
                conn.execute(
                    """
                    UPDATE hub_shop_packs SET status = 'active', payment = 'demo', payment_status = 'paid',
                      starts_at = ?, ends_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (starts, ends, now, purchase_id),
                )
            else:
                return jsonify({"ok": False, "error": "Cannot verify payment"}), 400
            conn.commit()
            row = conn.execute("SELECT * FROM hub_shop_packs WHERE id = ?", (purchase_id,)).fetchone()
            shop = conn.execute("SELECT * FROM hub_shops WHERE id = ?", (shop["id"],)).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "purchase": pack_public(row), "shop": shop_public(shop)})

    # boot seed
    c = conn_db()
    try:
        _seed_demo_shop(c)
    finally:
        c.close()
