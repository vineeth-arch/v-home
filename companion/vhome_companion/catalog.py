"""Build tv-catalog/catalog.json + icons/ (contract: docs/contracts/catalog-v1.md).

Adapted from webos-vibehack sync-apps.py (MIT, see NOTICE). Differences: an icon that fails to
download never drops the app (icon: null), icon downloads are restricted, and the write is atomic.

`system: true` rule (hidden from the grid, shown in Diagnostics): the launch point is flagged
hidden/invisible by the TV, or its id starts with `com.webos.app.` and is not in USER_FACING,
or it is V/HOME itself. Inputs are never system.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("vhome.catalog")

LIST_URI = "ssap://com.webos.applicationManager/listLaunchPoints"
INPUT_URI = "ssap://tv/getExternalInputList"
ID_RE = re.compile(r"^[a-zA-Z0-9._-]{2,100}$")
MAX_ENTRIES, MAX_TITLE, MAX_ICON = 200, 60, 256 * 1024
ICON_BUDGET_S = 120.0
USER_FACING = {"com.webos.app.browser", "com.webos.app.photovideo", "com.webos.app.music",
               "com.webos.app.screenshare"}
PNG, JPEG = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"


class CatalogError(Exception):
    pass


def icon_kind(data):
    if data.startswith(PNG):
        return ".png"
    if data.startswith(JPEG):
        return ".jpg"
    return None


def _no_redirect_opener():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # local to this request, host already checked
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    return lambda url, timeout: opener.open(url, timeout=timeout)


def fetch_icon(url, host, opener=None, timeout=5):
    """Return (ext, bytes). Raises CatalogError for anything not acceptable."""
    u = urlparse(str(url))
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise CatalogError("icon url is not a plain http(s) url")
    if u.hostname.lower() != str(host).lower():
        raise CatalogError("icon host is not the TV")
    opener = opener or _no_redirect_opener()
    with opener(url, timeout) as r:
        length = r.headers.get("Content-Length") if getattr(r, "headers", None) else None
        if length and length.isdigit() and int(length) > MAX_ICON:
            raise CatalogError("icon too large")
        data = r.read(MAX_ICON + 1)
    if len(data) > MAX_ICON:
        raise CatalogError("icon too large")
    ext = icon_kind(data)
    if not ext:
        raise CatalogError("icon is not PNG or JPEG")
    return ext, data


def _is_system(app_id, lp, vhome_id):
    if lp.get("hidden") is True or lp.get("visible") is False:
        return True
    if app_id == vhome_id:
        return True
    return app_id.startswith("com.webos.app.") and app_id not in USER_FACING


def _title(raw, fallback):
    t = " ".join(str(raw or "").split())[:MAX_TITLE].strip()
    return t or fallback[:MAX_TITLE]


def build(points, devices, tv, host, vhome_id, fetch=fetch_icon, now=None):
    """Return (catalog dict, {icon filename: bytes}). Pure apart from `fetch`."""
    if not isinstance(points, list) or not isinstance(devices, list):
        raise CatalogError("TV answered with an unexpected shape")
    seen, inputs, apps, dropped = set(), [], [], 0

    def take(raw_id):
        nonlocal dropped
        if not isinstance(raw_id, str) or not ID_RE.match(raw_id) or not re.search(r"[a-zA-Z0-9]", raw_id) \
                or raw_id.lower() in seen:  # case-insensitive: icon files live on a case-insensitive disk
            dropped += 1
            return False
        seen.add(raw_id.lower())
        return True

    for d in devices:
        if isinstance(d, dict) and take(d.get("appId")):
            inputs.append((d["appId"], _title(d.get("label") or d.get("name"), d["appId"]), "input",
                           False, [d.get("icon")]))
    for p in points:
        if isinstance(p, dict) and take(p.get("id")):
            apps.append((p["id"], _title(p.get("title"), p["id"]), "app",
                         _is_system(p["id"], p, vhome_id), [p.get("largeIcon"), p.get("icon")]))
    inputs = inputs[:MAX_ENTRIES]
    apps = apps[:MAX_ENTRIES - len(inputs)]
    if dropped:
        log.info("dropped %d invalid or duplicate entries", dropped)
    rows = apps + inputs
    if not rows:
        raise CatalogError("the TV returned no apps and no inputs; keeping the previous catalog")

    deadline = time.monotonic() + ICON_BUDGET_S

    def get_icon(row):
        for url in row[4]:
            if not url or time.monotonic() > deadline:
                continue
            try:
                return fetch(url, host)
            except Exception as e:
                log.info("no icon for %s: %s", row[0], e)
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(get_icon, rows))
    icons, entries = {}, []
    for row, ic in zip(rows, got):
        name = None
        if ic:
            name = row[0] + ic[0]
            icons[name] = ic[1]
        entries.append({"id": row[0], "title": row[1], "kind": row[2], "icon": name,
                        "source": "companion", "system": row[3]})
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"schema": 1, "generatedAt": stamp, "tv": tv, "entries": entries}, icons


def write_atomic(out, catalog, icons):
    """Write into a temp dir next to `out`, validate, then swap. On any failure `out` is untouched."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in [*out.parent.glob(out.name + ".tmp-*"), *out.parent.glob(out.name + ".old-*")]:
        shutil.rmtree(stale, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix=out.name + ".tmp-", dir=out.parent))
    old = None
    try:
        (tmp / "icons").mkdir()
        for name, data in icons.items():
            (tmp / "icons" / name).write_bytes(data)
        (tmp / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", "utf-8")
        back = json.loads((tmp / "catalog.json").read_text("utf-8"))
        for e in back["entries"]:
            if e["icon"] and not (tmp / "icons" / e["icon"]).is_file():
                raise CatalogError(f"icon file missing for {e['id']}")
        os.chmod(tmp, 0o755)
        if out.exists():
            old = out.parent / f"{out.name}.old-{os.getpid()}"
            os.rename(out, old)
        try:
            os.rename(tmp, out)
        except BaseException:
            if old:
                os.rename(old, out)
            raise
        if old:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


async def tv_info(client):
    """Best effort: model and firmware strings (field names unverified on this TV)."""
    model = fw = "unknown"
    try:
        model = (await client.request("ssap://system/getSystemInfo")).get("modelName") or model
    except Exception as e:
        log.info("getSystemInfo unavailable: %s", e)
    try:
        sw = await client.request("ssap://com.webos.service.update/getCurrentSWInformation")
        if model == "unknown":
            model = sw.get("model_name") or model
        if sw.get("major_ver") or sw.get("minor_ver"):
            fw = f"{sw.get('major_ver', '')}.{sw.get('minor_ver', '')}".strip(".")
    except Exception as e:
        log.info("getCurrentSWInformation unavailable: %s", e)
    return {"model": str(model), "firmware": str(fw)}


async def sync(client, out, host, vhome_id, fetch=fetch_icon):
    lp = await client.request(LIST_URI)
    inputs = await client.request(INPUT_URI)
    points, devices = lp.get("launchPoints"), inputs.get("devices")
    if points is None or devices is None:
        raise CatalogError("the TV did not return launchPoints and devices; keeping the previous catalog")
    tv = await tv_info(client)
    catalog, icons = await asyncio.to_thread(build, points, devices, tv, host, vhome_id, fetch)
    write_atomic(out, catalog, icons)
    return {"entries": len(catalog["entries"]), "icons": len(icons), "out": str(out)}
