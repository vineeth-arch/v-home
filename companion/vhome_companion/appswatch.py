"""Notice when apps are installed or removed on the TV, and optionally refresh V/HOME by itself.

Pure helpers (tested) plus the small decision function; the Runner in cli.py does the I/O.
Refreshing runs `scripts/refresh-tv.sh` (export catalog + build + install). That restarts V/HOME on the TV, so the
unattended mode is opt-in and only runs while V/HOME itself is in front (it never interrupts another app)."""
import json
import subprocess
from pathlib import Path

POLL_S = 30 * 60
REFRESH_MIN_GAP_S = 60 * 60


def app_ids(points, devices):
    """Every id the TV lists (hidden ones too, since the exported catalog keeps them as system entries), plus inputs."""
    ids = set()
    for p in points or []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            ids.add(p["id"])
    for d in devices or []:
        if isinstance(d, dict) and isinstance(d.get("appId"), str):
            ids.add(d["appId"])
    return frozenset(ids)


def known_ids(catalog_dir):
    """Ids in the exported catalog.json (system helpers included), or None when there is no usable catalog."""
    try:
        data = json.loads((Path(catalog_dir) / "catalog.json").read_text("utf-8"))
        return frozenset(e["id"] for e in data["entries"] if isinstance(e, dict) and isinstance(e.get("id"), str))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def diff(current, known):
    """(added, removed). Hidden/system apps that were exported are not 'removed'; only ids absent from the TV count."""
    if known is None:
        return frozenset(), frozenset()
    return frozenset(current - known), frozenset(known - current)


def decide(added, removed, notified_sig, auto, command, vhome_in_front, now, last_refresh):
    """-> (action, signature). action: None | 'notify' | 'refresh'. `notified_sig` is the change we already told the user about."""
    if not added and not removed:
        return None, None
    sig = (tuple(sorted(added)), tuple(sorted(removed)))
    if auto and command and vhome_in_front and (last_refresh is None or now - last_refresh >= REFRESH_MIN_GAP_S):
        return "refresh", sig
    if sig != notified_sig:
        return "notify", sig
    return None, sig


def notify(title, text):
    """macOS notification; best effort."""
    try:
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title {json.dumps(title)}'],
                       timeout=10, check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
