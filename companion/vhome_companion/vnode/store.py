"""Persistent VNode state in one directory (0600 files, atomic writes via cli.write_private).

TV pairing reuses the Mac layout (config.json, client-key, cert.sha256). control.json holds the
owner's switches. A corrupt or unreadable control.json never crashes: defaults plus one warning.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from .. import cli
from ..watcher import ConfigError

log = logging.getLogger("vhome.vnode.store")

DEFAULT_HOME_IDS = ["com.webos.app.home"]   # verified on the owner's TV
CONTROL_DEFAULTS = {"paused": False, "pause_reason": None, "paused_until": None,
                    "watcher_enabled": True, "power_on_launch": False}


def _valid_until(v):
    try:
        datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    return v


def normalize_control(raw):
    c = dict(CONTROL_DEFAULTS)
    for key in ("paused", "watcher_enabled", "power_on_launch"):
        if isinstance(raw.get(key), bool):
            c[key] = raw[key]
    if raw.get("pause_reason") in ("user", "safety"):
        c["pause_reason"] = raw["pause_reason"]
    c["paused_until"] = _valid_until(raw.get("paused_until"))
    if c["paused"]:
        c["pause_reason"] = c["pause_reason"] or "user"
    else:
        c["pause_reason"] = c["paused_until"] = None
    return c


class Store:
    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self._warned = False
        try:
            self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as e:
            log.warning("cannot create the state directory: %s", e)

    # ---- TV pairing ---------------------------------------------------------------------

    def paired(self):
        """(client_key, cert_sha256); either may be None."""
        return cli.paired(self.dir)

    def tv_config(self):
        """Everything the TV loop needs. A broken config.json reads as 'not configured'."""
        try:
            cfg = cli.load_config(self.dir)
        except ConfigError as e:
            self._warn_once(f"config.json ignored: {e}")
            cfg = dict(cli.DEFAULTS)
        key, pin = self.paired()
        home_ids = [i for i in cfg["home_ids"] if isinstance(i, str) and i.strip()]
        return {"host": cfg["host"] or "", "key": key, "pin": pin, "vhome_id": cfg["vhome_id"],
                "home_ids": home_ids or list(DEFAULT_HOME_IDS),
                "double_home_escape": bool(cfg["double_home_escape"])}

    def save_tv_pairing(self, host, key, pin):
        """Keep the previous key and pin as <name>.bak, then write the new ones and the host."""
        for name, value in (("client-key", key), ("cert.sha256", pin)):
            path = self.dir / name
            if path.exists():
                cli.write_private(path.with_name(name + ".bak"), path.read_text())
            cli.write_private(path, value + "\n")
        try:
            cfg = cli.load_config(self.dir)
        except ConfigError:
            cfg = dict(cli.DEFAULTS)
        cfg["host"] = host
        cli.save_config(self.dir, cfg)
        self.set_revoked(False)

    # ---- revoked marker: survives restarts so a revoked key is not retried (the TV would prompt) ----

    def revoked(self):
        return (self.dir / "tv-revoked").exists()

    def set_revoked(self, revoked):
        path = self.dir / "tv-revoked"
        if revoked:
            cli.write_private(path, "the TV rejected the client key; pair again\n")
        else:
            path.unlink(missing_ok=True)

    # ---- control.json -------------------------------------------------------------------

    def load_control(self):
        path = self.dir / "control.json"
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            return dict(CONTROL_DEFAULTS)
        except (OSError, ValueError) as e:
            self._warn_once(f"control.json unreadable, using defaults: {e}")
            return dict(CONTROL_DEFAULTS)
        return normalize_control(raw)

    def save_control(self, control):
        """Write and return the normalized control dict. Raises OSError if the write fails."""
        c = normalize_control(control)
        cli.write_private(self.dir / "control.json", json.dumps(c, indent=2) + "\n")
        return c

    def _warn_once(self, msg):
        if not self._warned:
            self._warned = True
            log.warning("%s", msg)
