"""Apple Wallet (.pkpass) and Google Wallet save-links for RWA vehicle passes.

Apple needs a Pass Type ID certificate (data/apple-wallet.env).
Google needs a Wallet issuer ID + service account (data/google-wallet.env).
Both stay disabled until those credentials are on the server.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import pathlib
import re
import time
import zipfile
from typing import Any
from urllib.parse import quote

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
from cryptography.x509.oid import NameOID
from PIL import Image, ImageDraw, ImageFont

KIND_COLORS = {
    "member": ("rgb(21, 35, 63)", "rgb(246, 241, 230)", "rgb(232, 213, 154)"),
    "tenant": ("rgb(28, 48, 36)", "rgb(246, 241, 230)", "rgb(183, 221, 184)"),
    "visitor": ("rgb(58, 32, 22)", "rgb(255, 248, 242)", "rgb(240, 196, 168)"),
    "adhoc": ("rgb(42, 34, 18)", "rgb(255, 248, 236)", "rgb(232, 212, 160)"),
}
KIND_HEX = {
    "member": "#15233F",
    "tenant": "#1C3024",
    "visitor": "#3A2016",
    "adhoc": "#2A2212",
}

_ENV_LOADED_FOR: str = ""
_SIGNING_CACHE: dict[str, Any] | None = None
_GOOGLE_CACHE: dict[str, Any] | None = None


def _site_root(site_root: pathlib.Path | None = None) -> pathlib.Path:
    if site_root is not None:
        return pathlib.Path(site_root)
    return pathlib.Path(
        os.environ.get("VEERCANVAS_SITE_ROOT")
        or os.environ.get("VEER_SITE_ROOT")
        or "."
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


def load_wallet_env(site_root: pathlib.Path | None = None) -> None:
    global _ENV_LOADED_FOR
    root = _site_root(site_root)
    marker = str(root.resolve())
    if _ENV_LOADED_FOR == marker:
        return
    _load_env_file(root / "data" / "apple-wallet.env")
    _load_env_file(root / "data" / "google-wallet.env")
    _ENV_LOADED_FOR = marker


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_existing(site_root: pathlib.Path | None, *candidates: str | pathlib.Path) -> pathlib.Path | None:
    root = _site_root(site_root)
    for raw in candidates:
        if not raw:
            continue
        path = pathlib.Path(raw)
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            return path
    return None


def wwdr_path(site_root: pathlib.Path | None = None) -> pathlib.Path | None:
    env = (os.environ.get("APPLE_WALLET_WWDR") or "").strip()
    return _resolve_existing(
        site_root,
        env,
        "assets/wallet/AppleWWDRCAG4.cer",
        "data/apple-wallet/wwdr.cer",
        "data/apple-wallet/AppleWWDRCAG4.cer",
    )


def p12_path(site_root: pathlib.Path | None = None) -> pathlib.Path | None:
    env = (os.environ.get("APPLE_WALLET_P12") or "").strip()
    return _resolve_existing(
        site_root,
        env,
        "data/apple-wallet/Certificates.p12",
        "data/apple-wallet/pass.p12",
    )


def is_configured(site_root: pathlib.Path | None = None) -> bool:
    load_wallet_env(site_root)
    if not _truthy(os.environ.get("APPLE_WALLET_ENABLED")):
        return False
    if p12_path(site_root):
        return True
    cert = _resolve_existing(
        site_root,
        os.environ.get("APPLE_WALLET_CERT") or "",
        "data/apple-wallet/certificate.pem",
    )
    key = _resolve_existing(
        site_root,
        os.environ.get("APPLE_WALLET_KEY") or "",
        "data/apple-wallet/private.key",
    )
    return bool(cert and key)


def public_fields(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "")
    active = status in ("active", "pending_renewal")
    pid = quote(str(item.get("id") or ""), safe="")
    code = quote(str(item.get("code") or ""), safe="")
    out = {
        "walletEnabled": False,
        "walletUrl": "",
        "googleWalletEnabled": False,
        "googleWalletUrl": "",
    }
    if active and is_configured():
        url = f"/api/rwa/parking/passes/{pid}/wallet.pkpass"
        if code:
            url += f"?code={code}"
        out["walletEnabled"] = True
        out["walletUrl"] = url
    if active and is_google_configured():
        url = f"/api/rwa/parking/passes/{pid}/wallet.google"
        if code:
            url += f"?code={code}"
        out["googleWalletEnabled"] = True
        out["googleWalletUrl"] = url
    return out


def _load_cert(path: pathlib.Path) -> x509.Certificate:
    data = path.read_bytes()
    if b"BEGIN CERTIFICATE" in data:
        return x509.load_pem_x509_certificate(data)
    return x509.load_der_x509_certificate(data)


def _cert_uid(cert: x509.Certificate) -> str:
    attrs = cert.subject.get_attributes_for_oid(NameOID.USER_ID)
    if attrs:
        return str(attrs[0].value or "").strip()
    for attr in cert.subject:
        raw = attr.rfc4514_string()
        if raw.upper().startswith("UID="):
            return raw.split("=", 1)[1].strip()
    return ""


def _cert_team(cert: x509.Certificate) -> str:
    attrs = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
    if attrs:
        value = str(attrs[0].value or "").strip()
        if re.fullmatch(r"[A-Z0-9]{10}", value):
            return value
    return ""


def _signing_material(site_root: pathlib.Path | None) -> dict[str, Any]:
    global _SIGNING_CACHE
    load_wallet_env(site_root)
    cache_key = str(_site_root(site_root).resolve())
    if _SIGNING_CACHE and _SIGNING_CACHE.get("root") == cache_key:
        return _SIGNING_CACHE

    password = (
        os.environ.get("APPLE_WALLET_P12_PASSWORD")
        or os.environ.get("APPLE_WALLET_KEY_PASSWORD")
        or ""
    ).encode("utf-8") or None

    cert: x509.Certificate | None = None
    key = None
    extras: list[x509.Certificate] = []

    bundle = p12_path(site_root)
    if bundle:
        parsed = pkcs12.load_key_and_certificates(bundle.read_bytes(), password)
        key, cert, extra = parsed
        extras = list(extra or [])
    else:
        cert_path = _resolve_existing(
            site_root,
            os.environ.get("APPLE_WALLET_CERT") or "",
            "data/apple-wallet/certificate.pem",
        )
        key_path = _resolve_existing(
            site_root,
            os.environ.get("APPLE_WALLET_KEY") or "",
            "data/apple-wallet/private.key",
        )
        if not cert_path or not key_path:
            raise ValueError("Apple Wallet certificate is not installed on the server")
        cert = _load_cert(cert_path)
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=password)

    if cert is None or key is None:
        raise ValueError("Apple Wallet certificate did not contain a signing key")

    wwdr = None
    wwdr_file = wwdr_path(site_root)
    if wwdr_file:
        wwdr = _load_cert(wwdr_file)
    else:
        for extra in extras:
            name = extra.subject.rfc4514_string()
            if "Worldwide Developer Relations" in name:
                wwdr = extra
                break
    if wwdr is None:
        raise ValueError("Apple WWDR intermediate certificate is missing")

    pass_type = (os.environ.get("APPLE_WALLET_PASS_TYPE_ID") or _cert_uid(cert)).strip()
    team = (os.environ.get("APPLE_WALLET_TEAM_ID") or _cert_team(cert)).strip()
    if not pass_type or not pass_type.startswith("pass."):
        raise ValueError("Set APPLE_WALLET_PASS_TYPE_ID (must start with pass.)")
    if not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise ValueError("Set APPLE_WALLET_TEAM_ID to your 10-character Apple Team ID")

    org = (
        os.environ.get("APPLE_WALLET_ORG")
        or "Himuda Housing Colony Sanyard"
    ).strip()
    material = {
        "root": cache_key,
        "cert": cert,
        "key": key,
        "wwdr": wwdr,
        "passTypeId": pass_type,
        "teamId": team,
        "org": org,
    }
    _SIGNING_CACHE = material
    return material


def _png_bytes(image: Image.Image) -> bytes:
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _fit_square(image: Image.Image, size: int, fill: tuple[int, int, int] = (21, 35, 63)) -> Image.Image:
    src = image.convert("RGBA")
    canvas = Image.new("RGBA", (size, size), fill + (255,))
    src.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - src.width) // 2
    y = (size - src.height) // 2
    canvas.paste(src, (x, y), src)
    return canvas.convert("RGB")


def _load_mark(site_root: pathlib.Path) -> Image.Image:
    root = _site_root(site_root)
    for rel in (
        "assets/mhws-logo/mhws-logo-icon-128.png",
        "assets/apple-touch-icon.png",
        "assets/hbcs-sanyard-seal-240.png",
        "assets/favicon-192.png",
    ):
        path = root / rel
        if path.is_file():
            return Image.open(path)
    canvas = Image.new("RGB", (128, 128), (21, 35, 63))
    return canvas


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if pathlib.Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _logo_png(mark: Image.Image, width: int, height: int) -> bytes:
    canvas = Image.new("RGB", (width, height), (21, 35, 63))
    side = max(8, height - 12)
    icon = _fit_square(mark, side)
    canvas.paste(icon, (8, (height - side) // 2))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(12, int(height * 0.38)))
    draw.text((side + 18, height * 0.28), "SANYARD", fill=(232, 213, 154), font=font)
    return _png_bytes(canvas)


def _pass_images(site_root: pathlib.Path, thumbnail_path: pathlib.Path | None) -> dict[str, bytes]:
    mark = _load_mark(site_root)
    files = {
        "icon.png": _png_bytes(_fit_square(mark, 29)),
        "icon@2x.png": _png_bytes(_fit_square(mark, 58)),
        "icon@3x.png": _png_bytes(_fit_square(mark, 87)),
        "logo.png": _logo_png(mark, 160, 50),
        "logo@2x.png": _logo_png(mark, 320, 100),
        "logo@3x.png": _logo_png(mark, 480, 150),
    }
    if thumbnail_path and thumbnail_path.is_file():
        try:
            thumb = Image.open(thumbnail_path)
            files["thumbnail.png"] = _png_bytes(_fit_square(thumb, 90, fill=(15, 18, 24)))
            files["thumbnail@2x.png"] = _png_bytes(_fit_square(thumb, 180, fill=(15, 18, 24)))
        except OSError:
            pass
    return files


def _iso_date(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw.startswith("9999"):
        return ""
    if raw.endswith("Z") or "+" in raw[10:] or raw.endswith("+00:00"):
        return raw
    if "T" in raw:
        return raw + "Z" if not raw.endswith("Z") else raw
    return ""


def _verify_url(item: dict[str, Any]) -> str:
    url = str(item.get("verifyUrl") or "").strip()
    if url:
        return url
    origin = (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")
    code = str(item.get("code") or "").strip()
    return f"{origin}/#parking?pass={code}" if code else origin


def _field(key: str, label: str, value: str, **extra: Any) -> dict[str, Any]:
    row = {"key": key, "label": label, "value": value or "—"}
    row.update(extra)
    return row


def pass_payload(item: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "visitor")
    bg, fg, label = KIND_COLORS.get(kind, KIND_COLORS["visitor"])
    plate = str(item.get("plateDisplay") or item.get("plate") or "").strip()
    who = str(item.get("tenantName") or item.get("visitorName") or item.get("memberName") or "").strip()
    plot = "Main gate" if kind == "adhoc" else str(item.get("plotNo") or item.get("houseId") or "").strip()
    valid = "Permanent" if item.get("permanent") else str(item.get("expiresAtLabel") or "—")
    primary_value = plate if plate and kind != "adhoc" else (who or item.get("kindLabel") or "Pass")
    primary_label = "VEHICLE" if plate and kind != "adhoc" else ("NAME" if who else "PASS")
    code = str(item.get("code") or item.get("id") or "")
    verify = _verify_url(item)
    barcode = {
        "format": "PKBarcodeFormatQR",
        "message": verify,
        "messageEncoding": "iso-8859-1",
        "altText": code,
    }
    secondary = [
        _field("kind", "PASS", str(item.get("kindLabel") or kind.title())),
        _field("plot", "PLOT", plot or "—"),
    ]
    auxiliary = [
        _field("valid", "VALID", valid),
        _field("code", "CODE", code),
    ]
    back = [
        _field("org", "Issued by", str(material["org"])),
        _field("holder", "Registered to", who or "—"),
        _field("status", "Status", str(item.get("statusLabel") or item.get("status") or "")),
        _field("verify", "Verify", verify),
        _field("help", "Gate", "Show this pass at Himuda Housing Colony Sanyard. Staff scan the QR to confirm it is valid."),
    ]
    if item.get("vehicleTypeLabel") or item.get("colour"):
        back.insert(2, _field(
            "vehicle",
            "Vehicle",
            " · ".join([str(item.get("vehicleTypeLabel") or ""), str(item.get("colour") or "")]).strip(" ·"),
        ))
    payload: dict[str, Any] = {
        "formatVersion": 1,
        "passTypeIdentifier": material["passTypeId"],
        "serialNumber": str(item.get("id") or code)[:64],
        "teamIdentifier": material["teamId"],
        "organizationName": material["org"],
        "description": f"{item.get('kindLabel') or 'Vehicle'} pass · {primary_value}",
        "logoText": "Sanyard",
        "backgroundColor": bg,
        "foregroundColor": fg,
        "labelColor": label,
        "barcode": barcode,
        "barcodes": [barcode],
        "generic": {
            "primaryFields": [_field("primary", primary_label, primary_value)],
            "secondaryFields": secondary,
            "auxiliaryFields": auxiliary,
            "backFields": back,
        },
    }
    expires = _iso_date(str(item.get("expiresAt") or ""))
    if expires and not item.get("permanent"):
        payload["expirationDate"] = expires
    if str(item.get("status") or "") in ("revoked", "expired"):
        payload["voided"] = True
    lat = (os.environ.get("APPLE_WALLET_LAT") or "").strip()
    lng = (os.environ.get("APPLE_WALLET_LNG") or "").strip()
    if lat and lng:
        try:
            payload["locations"] = [{
                "latitude": float(lat),
                "longitude": float(lng),
                "relevantText": os.environ.get("APPLE_WALLET_RELEVANT_TEXT") or "Sanyard vehicle pass",
            }]
            payload["maxDistance"] = int(os.environ.get("APPLE_WALLET_MAX_DISTANCE") or "1500")
        except ValueError:
            pass
    return payload


def _sign_manifest(manifest: bytes, material: dict[str, Any]) -> bytes:
    options = [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary]
    builder = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(manifest)
        .add_signer(material["cert"], material["key"], hashes.SHA256())
        .add_certificate(material["wwdr"])
    )
    return builder.sign(serialization.Encoding.DER, options)


def build_pkpass(
    item: dict[str, Any],
    site_root: pathlib.Path | None = None,
    *,
    thumbnail_path: pathlib.Path | None = None,
) -> bytes:
    if not is_configured(site_root):
        raise ValueError("Apple Wallet is not configured")
    material = _signing_material(site_root)
    files = _pass_images(_site_root(site_root), thumbnail_path)
    files["pass.json"] = json.dumps(pass_payload(item, material), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    manifest = {
        name: hashlib.sha1(data, usedforsecurity=False).hexdigest()
        for name, data in files.items()
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _sign_manifest(manifest_bytes, material)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("signature", signature)
    return buf.getvalue()


def google_sa_path(site_root: pathlib.Path | None = None) -> pathlib.Path | None:
    env = (os.environ.get("GOOGLE_WALLET_SA_JSON") or "").strip()
    return _resolve_existing(
        site_root,
        env,
        "data/google-wallet-sa.json",
        "data/google-wallet/sa.json",
    )


def is_google_configured(site_root: pathlib.Path | None = None) -> bool:
    load_wallet_env(site_root)
    if not _truthy(os.environ.get("GOOGLE_WALLET_ENABLED")):
        return False
    issuer = (os.environ.get("GOOGLE_WALLET_ISSUER_ID") or "").strip()
    if not issuer:
        return False
    path = google_sa_path(site_root)
    if not path:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("client_email") and data.get("private_key"))


def _google_material(site_root: pathlib.Path | None) -> dict[str, Any]:
    global _GOOGLE_CACHE
    load_wallet_env(site_root)
    cache_key = str(_site_root(site_root).resolve())
    if _GOOGLE_CACHE and _GOOGLE_CACHE.get("root") == cache_key:
        return _GOOGLE_CACHE
    issuer = (os.environ.get("GOOGLE_WALLET_ISSUER_ID") or "").strip()
    if not re.fullmatch(r"[0-9]{10,24}", issuer):
        raise ValueError("Set GOOGLE_WALLET_ISSUER_ID to your numeric Google Wallet issuer ID")
    path = google_sa_path(site_root)
    if not path:
        raise ValueError("Google Wallet service-account JSON is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Google Wallet service-account JSON is invalid") from exc
    email = str(data.get("client_email") or "").strip()
    pem = str(data.get("private_key") or "").replace("\\n", "\n")
    if not email or "BEGIN PRIVATE KEY" not in pem:
        raise ValueError("Google Wallet service-account JSON needs client_email and private_key")
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    class_suffix = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        (os.environ.get("GOOGLE_WALLET_CLASS_SUFFIX") or "sanyard_vehicle").strip(),
    ) or "sanyard_vehicle"
    org = (
        os.environ.get("GOOGLE_WALLET_ORG")
        or os.environ.get("APPLE_WALLET_ORG")
        or "Himuda Housing Colony Sanyard"
    ).strip()
    material = {
        "root": cache_key,
        "issuerId": issuer,
        "email": email,
        "key": key,
        "keyId": str(data.get("private_key_id") or "").strip(),
        "classSuffix": class_suffix,
        "org": org,
    }
    _GOOGLE_CACHE = material
    return material


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_rs256_jwt(claims: dict[str, Any], material: dict[str, Any]) -> str:
    header: dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
    if material.get("keyId"):
        header["kid"] = material["keyId"]
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))}."
        f"{_b64url(json.dumps(claims, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))}"
    )
    signature = material["key"].sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{signing_input}.{_b64url(signature)}"


def _google_origins() -> list[str]:
    raw = (
        os.environ.get("GOOGLE_WALLET_ORIGINS")
        or "https://housingcolonysanyard.in,https://www.housingcolonysanyard.in,https://hbcsanyard.veerlabs.solutions"
    )
    out: list[str] = []
    for part in raw.split(","):
        host = part.strip()
        if not host:
            continue
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].strip()
        if host and host not in out:
            out.append(host)
    return out or ["housingcolonysanyard.in"]


def _localized(value: str, lang: str = "en-IN") -> dict[str, Any]:
    return {"defaultValue": {"language": lang, "value": value or "—"}}


def _google_object_suffix(item: dict[str, Any]) -> str:
    raw = str(item.get("id") or item.get("code") or "pass")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._-")
    return cleaned[:64] or "pass"


def google_pass_payload(item: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "visitor")
    plate = str(item.get("plateDisplay") or item.get("plate") or "").strip()
    who = str(item.get("tenantName") or item.get("visitorName") or item.get("memberName") or "").strip()
    plot = "Main gate" if kind == "adhoc" else str(item.get("plotNo") or item.get("houseId") or "").strip()
    valid = "Permanent" if item.get("permanent") else str(item.get("expiresAtLabel") or "—")
    header = plate if plate and kind != "adhoc" else (who or str(item.get("kindLabel") or "Pass"))
    code = str(item.get("code") or item.get("id") or "")
    verify = _verify_url(item)
    origin = _public_origin()
    class_id = f"{material['issuerId']}.{material['classSuffix']}"
    object_id = f"{material['issuerId']}.{_google_object_suffix(item)}"
    modules = [
        {"id": "plot", "header": "Plot", "body": plot or "—"},
        {"id": "kind", "header": "Pass", "body": str(item.get("kindLabel") or kind.title())},
        {"id": "valid", "header": "Valid", "body": valid},
        {"id": "code", "header": "Code", "body": code or "—"},
    ]
    if who:
        modules.append({"id": "holder", "header": "Registered to", "body": who})
    vehicle = " · ".join(
        [str(item.get("vehicleTypeLabel") or ""), str(item.get("colour") or "")]
    ).strip(" ·")
    if vehicle:
        modules.append({"id": "vehicle", "header": "Vehicle", "body": vehicle})
    obj: dict[str, Any] = {
        "id": object_id,
        "classId": class_id,
        "genericType": "GENERIC_PARKING_PASS",
        "state": "EXPIRED" if str(item.get("status") or "") in ("expired", "revoked") else "ACTIVE",
        "cardTitle": _localized(str(material["org"])),
        "header": _localized(header),
        "subheader": _localized(str(item.get("kindLabel") or "Vehicle pass")),
        "hexBackgroundColor": KIND_HEX.get(kind, KIND_HEX["visitor"]),
        "barcode": {
            "type": "QR_CODE",
            "value": verify,
            "alternateText": code,
        },
        "textModulesData": modules,
        "linksModuleData": {
            "uris": [{
                "uri": verify,
                "description": "Verify this pass",
                "id": "verify",
            }]
        },
        "logo": {
            "sourceUri": {"uri": f"{origin}/assets/mhws-logo/mhws-logo-web-256.png"},
            "contentDescription": _localized("MHWS"),
        },
    }
    expires = _iso_date(str(item.get("expiresAt") or ""))
    issued = _iso_date(str(item.get("issuedAt") or ""))
    if expires and not item.get("permanent"):
        interval: dict[str, Any] = {"end": {"date": expires}}
        if issued:
            interval["start"] = {"date": issued}
        obj["validTimeInterval"] = interval
    return {
        "genericClasses": [{"id": class_id}],
        "genericObjects": [obj],
    }


def google_save_url(item: dict[str, Any], site_root: pathlib.Path | None = None) -> str:
    if not is_google_configured(site_root):
        raise ValueError("Google Wallet is not configured")
    material = _google_material(site_root)
    claims = {
        "iss": material["email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "origins": _google_origins(),
        "payload": google_pass_payload(item, material),
    }
    token = _sign_rs256_jwt(claims, material)
    return f"https://pay.google.com/gp/v/save/{token}"


def _public_origin() -> str:
    return (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")
