"""City of Mandi payments — Razorpay helpers + sponsored shop pack catalogue."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any

# Self-serve packs (INR). Duration is calendar days from activation.
SHOP_PACKS = {
    "board_boost": {
        "id": "board_boost",
        "title": "Board boost",
        "titleHi": "बोर्ड बूस्ट",
        "lede": "Featured at the top of your board for 7 days.",
        "price": 499,
        "days": 7,
        "features": ("board_featured",),
        "weight": 4,
    },
    "header_spotlight": {
        "id": "header_spotlight",
        "title": "Header spotlight",
        "titleHi": "हेडर स्पॉटलाइट",
        "lede": "Rotate in the site header sponsored strip for 7 days.",
        "price": 999,
        "days": 7,
        "features": ("header",),
        "weight": 8,
    },
    "combo_14": {
        "id": "combo_14",
        "title": "Combo · 14 days",
        "titleHi": "कॉम्बो · 14 दिन",
        "lede": "Board featured + header spotlight for two weeks.",
        "price": 1499,
        "days": 14,
        "features": ("board_featured", "header"),
        "weight": 10,
    },
}


def packs_public() -> list[dict]:
    return [
        {
            "id": p["id"],
            "title": p["title"],
            "titleHi": p["titleHi"],
            "lede": p["lede"],
            "price": p["price"],
            "days": p["days"],
            "features": list(p["features"]),
        }
        for p in SHOP_PACKS.values()
    ]


def get_pack(pack_id: str) -> dict | None:
    return SHOP_PACKS.get((pack_id or "").strip().lower())


def load_payments_env(data_dir: pathlib.Path | None) -> None:
    """Load data/payments.env into os.environ without overriding existing keys."""
    if not data_dir:
        return
    path = pathlib.Path(data_dir) / "payments.env"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def payment_config() -> dict[str, Any]:
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "").strip()
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()
    demo = (os.environ.get("HUB_PAYMENTS_DEMO") or "1").strip() in ("1", "true", "yes", "on")
    online = bool(key_id and key_secret)
    return {
        "onlineEnabled": online,
        "demoEnabled": demo and not online,
        "keyId": key_id if online else "",
        "upiVpa": (os.environ.get("HUB_UPI_VPA") or "").strip(),
        "upiName": (os.environ.get("HUB_UPI_NAME") or "City of Mandi").strip() or "City of Mandi",
        "currency": "INR",
        "packs": packs_public(),
    }


def razorpay_create_order(*, amount_paise: int, receipt: str, notes: dict | None = None) -> dict:
    cfg = payment_config()
    if not cfg["onlineEnabled"]:
        raise RuntimeError("Online payments are not configured")
    payload = {
        "amount": int(amount_paise),
        "currency": "INR",
        "receipt": str(receipt)[:40],
        "notes": notes or {},
    }
    body = json.dumps(payload).encode("utf-8")
    auth = base64.b64encode(
        f"{os.environ['RAZORPAY_KEY_ID']}:{os.environ['RAZORPAY_KEY_SECRET']}".encode("utf-8")
    ).decode("ascii")
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/orders",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Razorpay order failed: {detail}") from exc


def razorpay_verify_signature(*, order_id: str, payment_id: str, signature: str) -> bool:
    secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").encode("utf-8")
    if not secret:
        return False
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())
