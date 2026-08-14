"""Share colony notices and listings onto the City of Mandi hub."""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

import rwa_marketplace
import rwa_portal

KIND_FROM_NOTICE = {
    "ad": "ad",
    "events": "event",
    "event": "event",
}
KIND_FROM_MARKET = {
    "business": "business",
    "service_need": "service",
    "ad": "ad",
}

DEFAULT_HUB_URL = "https://cityofmandi.com"
SIBLING_SYNDICATE_ENV = pathlib.Path(
    "/var/www/cityofmandi.veerlabs.solutions/data/syndicate.env"
)


def _load_env_file(path: pathlib.Path) -> None:
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def load_config(site_root: pathlib.Path) -> dict:
    _load_env_file(pathlib.Path(site_root) / "data" / "city-hub.env")
    token = (os.environ.get("CITY_HUB_TOKEN") or "").strip()
    if not token:
        _load_env_file(SIBLING_SYNDICATE_ENV)
        token = (os.environ.get("SYNDICATE_TOKEN_HBCSANYARD") or "").strip()
    return {
        "url": (os.environ.get("CITY_HUB_URL") or DEFAULT_HUB_URL).rstrip("/"),
        "siteId": (os.environ.get("CITY_HUB_SITE_ID") or "hbcsanyard").strip().lower(),
        "token": token,
        "configured": bool(token),
    }


def _post(cfg: dict, payload: dict) -> dict:
    if not cfg.get("token"):
        raise ValueError("City of Mandi sharing is not configured yet")
    req = urllib.request.Request(
        f"{cfg['url']}/api/hub/syndicate",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['token']}",
            "X-Hub-Source": cfg["siteId"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("error") or ""
        except Exception:
            detail = exc.reason or str(exc)
        raise ValueError(detail or f"City hub returned {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError("Could not reach City of Mandi") from exc
    if not body.get("ok"):
        raise ValueError(body.get("error") or "City hub rejected the listing")
    return body


def share_notice(conn, site_root: pathlib.Path, notice_id: str, *, origin: str) -> dict:
    notice = rwa_portal.get_notice(conn, notice_id)
    if not notice:
        raise ValueError("Notice not found")
    if (notice.get("status") or "") != "published":
        raise ValueError("Publish the notice on the colony board first")
    cfg = load_config(site_root)
    category = str(notice.get("category") or "general").strip().lower()
    kind = KIND_FROM_NOTICE.get(category, "news")
    title = str(notice.get("title") or "").strip()
    body = str(notice.get("body") or "").strip()
    return _post(cfg, {
        "kind": kind,
        "title": title,
        "summary": body[:600],
        "body": body[:4000],
        "category": category[:40],
        "url": f"{origin.rstrip('/')}/#landing-news",
        "location": "Himuda Housing Colony Sanyard, Mandi",
        "sourceId": f"notice:{notice['id']}",
    })


def share_marketplace(conn, site_root: pathlib.Path, item_id: str, *, origin: str) -> dict:
    item = rwa_marketplace.get_item(conn, item_id)
    if not item:
        raise ValueError("Listing not found")
    if (item.get("status") or "") != "published":
        raise ValueError("Approve the listing on the colony board first")
    cfg = load_config(site_root)
    kind = KIND_FROM_MARKET.get(item.get("kind") or "ad", "ad")
    if kind == "ad" and (item.get("category") or "") == "event":
        kind = "event"
    title = str(item.get("title") or "").strip()
    summary = str(item.get("description") or "").strip()
    origin = origin.rstrip("/")
    if kind in {"business", "service"}:
        url = f"{origin}/#landing-services"
    elif kind == "event":
        url = f"{origin}/#landing-ads"
    else:
        url = f"{origin}/#landing-ads"
    return _post(cfg, {
        "kind": kind,
        "title": title,
        "summary": summary[:600],
        "body": summary[:4000],
        "category": str(item.get("categoryLabel") or item.get("category") or "")[:40],
        "phone": str(item.get("phone") or "")[:24],
        "url": url,
        "location": str(item.get("area") or "Himuda Housing Colony Sanyard, Mandi")[:80],
        "plan": "listed",
        "sourceId": f"market:{item['id']}",
    })
