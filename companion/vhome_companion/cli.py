"""Command line, state directory and the watch loop. Adapted from webos-vibehack home-watch.py (MIT)."""
import argparse
import asyncio
import fcntl
import json
import logging
import logging.handlers
import os
import random
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import appswatch, catalog, ssap
from .watcher import ConfigError, Watcher

LABEL = "com.designinnsaeit.vhome-companion"
FG_URI = "ssap://com.webos.applicationManager/getForegroundAppInfo"
LAUNCH_URI = "ssap://system.launcher/launch"
EX_CONFIG = 78
DEFAULTS = {"host": "", "vhome_id": "com.designinnsaeit.vhome", "home_ids": [],
            "double_home_escape": False, "auto_refresh": False, "refresh_command": ""}
log = logging.getLogger("vhome.cli")


# ---- state directory -------------------------------------------------------------------

def state_dir():
    d = Path(os.environ.get("VHOME_COMPANION_DIR")
             or Path.home() / "Library" / "Application Support" / "vhome-companion")
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def write_private(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def read_text(path):
    try:
        return Path(path).read_text().strip() or None
    except OSError:
        return None


def load_config(d):
    cfg = dict(DEFAULTS)
    try:
        loaded = json.loads((d / "config.json").read_text())
        if isinstance(loaded, dict):
            cfg.update(loaded)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        raise ConfigError(f"config.json is unreadable: {e}") from e
    if not isinstance(cfg["home_ids"], list):
        raise ConfigError("config.json: home_ids must be a list")
    return cfg


def save_config(d, cfg):
    write_private(d / "config.json", json.dumps(cfg, indent=2) + "\n")


def setup_logging(d, console):
    root = logging.getLogger("vhome")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.handlers.RotatingFileHandler(d / "companion.log", maxBytes=1_000_000, backupCount=3)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(sh)


def backoff(attempt, rand=random.random):
    """2 s doubling to a 60 s cap, with +-20% jitter (never above the cap)."""
    base = min(60.0, 2.0 * 2 ** attempt)
    return min(60.0, base * (0.8 + 0.4 * rand()))


def acquire_lock(d, host):
    f = open(d / f"watch-{re.sub(r'[^A-Za-z0-9._-]', '_', host)}.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def extract_app_id(payload):
    app = payload.get("appId")
    if isinstance(app, str):
        return app
    info = payload.get("foregroundAppInfo")  # array form, seen on some firmware (unverified here)
    if isinstance(info, list):
        for item in info:
            if isinstance(item, dict) and isinstance(item.get("appId"), str):
                return item["appId"]
    return ""


# ---- watch loop ------------------------------------------------------------------------

class Runner:
    """Glue between the Client and the pure Watcher. All decisions live in the Watcher."""

    def __init__(self, watcher, d, host, clock=time.monotonic):
        self.w, self.d, self.host, self.clock = watcher, d, host, clock
        self.flag = d / "paused"
        self.flag_seen = False   # we have seen/written the flag, so its removal means "resume"
        self.connected = False
        self.last_error = None
        self.last_event = None
        self.client = None
        self.tasks = set()
        self.cfg = {}
        self.apps_sig = None       # the app change we already told the user about
        self.last_refresh = None   # monotonic time of the last unattended refresh
        self.apps_changed = None   # {'added': [...], 'removed': [...]} while the exported catalog is out of date

    def sync_flag(self):
        exists = self.flag.exists()
        if exists:
            self.flag_seen = True
            if not self.w.paused:
                self.apply(self.w.pause("pause flag present"))
        elif self.flag_seen and self.w.paused:
            self.flag_seen = False
            self.apply(self.w.resume())
        elif self.flag_seen:
            self.flag_seen = False

    def apply(self, actions):
        for a in actions:
            if a.kind == "log":
                log.log(getattr(logging, a.level.upper(), logging.INFO), "%s", a.text)
            elif a.kind == "pause":
                try:
                    write_private(self.flag, f"{a.text}\n")
                    self.flag_seen = True
                except OSError as e:
                    log.error("could not write the pause flag: %s", e)
            elif a.kind == "launch":
                t = asyncio.create_task(self._launch(a))
                self.tasks.add(t)
                t.add_done_callback(self.tasks.discard)

    async def _launch(self, a):
        ok, err = True, ""
        try:
            await self.client.request(LAUNCH_URI, {"id": a.app_id}, timeout=10)
        except Exception as e:  # SsapError, or anything unexpected: count it as a failed launch
            ok, err = False, str(e)
        self.apply(self.w.on_launch_result(a.token, ok, self.clock(), err))
        self.write_state()

    def write_state(self):
        st = {"pid": os.getpid(), "host": self.host, "connected": self.connected,
              "last_event": self.last_event, "last_error": self.last_error, "apps_changed": self.apps_changed,
              "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "watcher": self.w.snapshot()}
        try:
            write_private(self.d / "state.json", json.dumps(st, indent=2) + "\n")
        except OSError as e:
            log.warning("could not write state.json: %s", e)

    async def check_apps(self):
        """Compare the TV's app list with the exported catalog. Notify, or (opt-in) refresh V/HOME while it is in front."""
        out = Path(self.cfg.get("catalog_dir") or default_catalog_dir() or "")
        known = appswatch.known_ids(out) if str(out) else None
        lp = await self.client.request(catalog.LIST_URI)
        devs = await self.client.request(catalog.INPUT_URI)
        added, removed = appswatch.diff(appswatch.app_ids(lp.get("launchPoints"), devs.get("devices")), known)
        front = self.w.last_app == self.w.vhome_id
        action, sig = appswatch.decide(added, removed, self.apps_sig, bool(self.cfg.get("auto_refresh")), self.cfg.get("refresh_command") or "", front, self.clock(), self.last_refresh)
        self.apps_changed = {"added": sorted(added), "removed": sorted(removed)} if sig else None
        if action == "notify":
            self.apps_sig = sig
            msg = f"{len(added)} new and {len(removed)} removed apps on the TV. Run scripts/refresh-tv.sh to update V/HOME."
            log.info("apps changed: +%s -%s", sorted(added), sorted(removed))
            await asyncio.to_thread(appswatch.notify, "V/HOME", msg)
        elif action == "refresh":
            self.last_refresh = self.clock()
            log.info("apps changed: +%s -%s; refreshing V/HOME (auto_refresh on, V/HOME in front)", sorted(added), sorted(removed))
            try:
                r = await asyncio.to_thread(subprocess.run, shlex.split(self.cfg["refresh_command"]), capture_output=True, text=True, timeout=900)
                log.info("refresh finished with exit code %s: %s", r.returncode, (r.stdout or r.stderr or "").strip()[-300:])
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("refresh failed: %s", e)
        self.write_state()

    async def apps_loop(self):
        await asyncio.sleep(60)  # let the first connection settle
        while True:
            try:
                await self.check_apps()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # the TV may be busy or sleeping; try again next round
                log.info("app list check skipped: %s", e)
            await asyncio.sleep(appswatch.POLL_S)

    async def session(self, client):
        self.client = client
        sub = await client.subscribe(FG_URI)
        poller = asyncio.create_task(self.apps_loop())
        self.tasks.add(poller)
        self.sync_flag()
        self.apply(self.w.on_connected(self.clock()))
        try:
            while True:
                dl = self.w.next_deadline()
                try:
                    payload = await asyncio.wait_for(
                        sub.get(), None if dl is None else max(0.0, dl - self.clock()))
                except TimeoutError:
                    self.sync_flag()
                    self.apply(self.w.on_tick(self.clock()))
                    self.write_state()
                    continue
                self.sync_flag()
                self.last_event = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.apply(self.w.on_foreground(extract_app_id(payload), self.clock()))
                self.write_state()
        finally:
            for t in list(self.tasks):
                t.cancel()

    async def forever(self, cfg, key, pin):
        attempt, last_msg = 0, None
        while True:
            client = ssap.Client(self.host, key, pin)
            up_since = None
            try:
                await client.open()
                up_since, last_msg = time.monotonic(), None
                self.connected, self.last_error = True, None
                log.info("connected to %s", self.host)
                self.write_state()
                await self.session(client)
            except asyncio.CancelledError:
                raise
            except ssap.NotPaired as e:
                # A revoked/stale key would make the TV show its pairing prompt on every retry. Stop until `pair` is re-run.
                self.last_error = f"{e} (watcher stopped; run `pair` again)"
                log.error("%s", self.last_error)
                return
            except (ssap.SsapError, OSError, TimeoutError) as e:
                self.last_error = str(e)
                quiet = isinstance(e, ssap.ConnectionLost) or getattr(e, "quiet", False)
                if str(e) != last_msg:
                    last_msg = str(e)
                    (log.info if quiet else log.error if isinstance(e, ssap.PinMismatch)
                     else log.warning)("%s", e)
            finally:
                self.connected = False
                await client.close()
                self.write_state()
            if up_since and time.monotonic() - up_since > 30:
                attempt = 0
            await asyncio.sleep(backoff(attempt))
            attempt += 1


def paired(d):
    return read_text(d / "client-key"), read_text(d / "cert.sha256")


def cmd_watch(args):
    d = state_dir()
    setup_logging(d, sys.stderr.isatty())
    try:
        cfg = load_config(d)
        if not cfg["host"]:
            raise ConfigError("no TV host configured; run `pair --host IP`")
        w = Watcher(cfg["vhome_id"], cfg["home_ids"], cfg["double_home_escape"])
        key, pin = paired(d)
        if not key or not pin:
            raise ConfigError("not paired; run `pair --host IP`")
    except ConfigError as e:
        log.error("watcher not started: %s", e)
        print(f"watcher not started: {e}", file=sys.stderr)
        return 0 if args.service else EX_CONFIG
    lock = acquire_lock(d, cfg["host"])
    if lock is None:
        print("another watcher for this TV is already running", file=sys.stderr)
        return 0 if args.service else 1
    runner = Runner(w, d, cfg["host"])
    runner.cfg = cfg

    async def main():
        task = asyncio.create_task(runner.forever(cfg, key, pin))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await task
        except asyncio.CancelledError:
            pass

    log.info("watcher starting for %s (V/HOME %s, Home ids %s)", cfg["host"], w.vhome_id, list(w.home_ids))
    asyncio.run(main())
    runner.write_state()
    log.info("watcher stopped")
    return 0


# ---- other commands --------------------------------------------------------------------

async def open_client(d, cfg):
    if not cfg["host"]:
        raise ssap.NotPaired("no TV host configured; run `pair --host IP`")
    key, pin = paired(d)
    if not key or not pin:
        raise ssap.NotPaired("not paired; run `pair --host IP`")
    c = ssap.Client(cfg["host"], key, pin)
    await c.open()
    return c


def cmd_pair(args):
    d = state_dir()
    cfg = load_config(d)
    old_pin = read_text(d / "cert.sha256")

    async def go():
        c = ssap.Client(args.host, None, None, trust_new=True)
        print(f"Connecting to {args.host}. Accept the pairing prompt on the TV (60 s)...")
        try:
            key = await c.open(pair_timeout=60, on_prompt=lambda: print("Prompt is showing on the TV."))
            if old_pin and old_pin != c.cert_sha256 and not args.repin:
                raise ssap.PinMismatch("a different TV certificate is already pinned; use --repin if the TV was reset")
            write_private(d / "client-key", key + "\n")
            write_private(d / "cert.sha256", c.cert_sha256 + "\n")
            cfg["host"] = args.host
            save_config(d, cfg)
            print(f"Paired. Pinned certificate {c.cert_sha256[:16]}... Next: diag --observe 20")
        finally:
            await c.close()

    return run_async(go())


def run_async(coro):
    try:
        asyncio.run(coro)
        return 0
    except ssap.SsapError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (OSError, TimeoutError, catalog.CatalogError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


async def probe(client, uri, payload=None):
    try:
        await client.request(uri, payload, timeout=8)
        return "supported"
    except ssap.RequestTimeout:
        return "unavailable (no answer)"
    except ssap.RequestFailed as e:
        return f"{e.kind} ({e})"


def cmd_diag(args):
    d = state_dir()
    cfg = load_config(d)
    if args.save_home:
        if args.save_home not in cfg["home_ids"]:
            cfg["home_ids"].append(args.save_home)
        save_config(d, cfg)
        print(f"Saved LG Home id {args.save_home}. Home ids now: {cfg['home_ids']}")

    async def go():
        c = await open_client(d, cfg)
        try:
            info = await catalog.tv_info(c)
            print(f"TV {cfg['host']}: model {info['model']}, firmware {info['firmware']} (field names unverified)")
            print("pairing/connection: supported")
            try:
                print("hello:", json.dumps(await c.hello()))
            except ssap.SsapError as e:
                print(f"hello: unavailable ({e})")
            try:
                print("getSystemInfo:", json.dumps(await c.request("ssap://system/getSystemInfo", timeout=8)))
            except ssap.SsapError as e:
                print(f"getSystemInfo: {getattr(e, 'kind', 'unavailable')} ({e})")
            try:
                pts = (await c.request(catalog.LIST_URI, timeout=15)).get("launchPoints", [])
                ids = {p.get("id") for p in pts if isinstance(p, dict)}
                print(f"V/HOME installed ({cfg['vhome_id']}):", "yes" if cfg["vhome_id"] in ids else "no")
                print("READ_INSTALLED_APPS (listLaunchPoints): supported")
            except ssap.RequestFailed as e:
                print("V/HOME installed: unverified (app list not readable)")
                print(f"READ_INSTALLED_APPS (listLaunchPoints): {e.kind} ({e})")
            print("READ_RUNNING_APPS (getForegroundAppInfo):", await probe(c, FG_URI))
            print("READ_INPUT_DEVICE_LIST (getExternalInputList):", await probe(c, catalog.INPUT_URI))
            print("LAUNCH (system.launcher/launch): unverified (not exercised here so nothing is interrupted)")
            print("LG Home ids configured:", cfg["home_ids"] or "none (needed before `watch` will start)")
            if args.observe:
                print(f"Observing foreground changes for {args.observe} s. Press Home on the remote now.")
                sub = await c.subscribe(FG_URI)
                end, last = time.monotonic() + args.observe, None
                while (left := end - time.monotonic()) > 0:
                    try:
                        app = extract_app_id(await asyncio.wait_for(sub.get(), left))
                    except TimeoutError:
                        break
                    if app and app != last:
                        last = app
                        print(f"{time.strftime('%H:%M:%S')}  {app}")
                print("Done. Save LG Home's id with: diag --save-home <id>")
        finally:
            await c.close()

    return run_async(go())


def cmd_sync_catalog(args):
    d = state_dir()
    cfg = load_config(d)
    out = Path(args.out) if args.out else default_catalog_dir()
    if out is None:
        print("error: run from the repo root or pass --out", file=sys.stderr)
        return 1

    async def go():
        c = await open_client(d, cfg)
        try:
            r = await catalog.sync(c, out, cfg["host"], cfg["vhome_id"])
            print(f"Catalog written: {r['entries']} entries, {r['icons']} icons -> {r['out']}")
        finally:
            await c.close()

    rc = run_async(go())
    if rc:
        print("The previous catalog (if any) was left untouched.", file=sys.stderr)
    return rc


def cmd_autorefresh(args):
    d = state_dir()
    cfg = load_config(d)
    if args.mode == "off":
        cfg["auto_refresh"] = False
        save_config(d, cfg)
        print("Auto refresh is off. The helper still notifies you when apps change.")
        return 0
    root = default_catalog_dir()
    cmd = args.command or (str(root.parent / "scripts" / "refresh-tv.sh") if root else "")
    if not cmd:
        print("error: run from the repo root or pass --command", file=sys.stderr)
        return 1
    cfg["auto_refresh"], cfg["refresh_command"] = True, cmd
    save_config(d, cfg)
    print(f"Auto refresh is on: {cmd}\nIt runs only when apps changed, V/HOME is in front on the TV, and at most once an hour.")
    return 0


def default_catalog_dir():
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (base / "package.json").is_file() and (base / "scripts").is_dir():
            return base / "tv-catalog"
    return None


def cmd_status(args):
    d = state_dir()
    cfg = load_config(d)
    flag = d / "paused"
    print(f"host: {cfg['host'] or 'not set'}; paired: {'yes' if all(paired(d)) else 'no'}; "
          f"Home ids: {cfg['home_ids'] or 'none'}")
    print("paused flag:", "yes (observe only)" if flag.exists() else "no")
    try:
        st = json.loads((d / "state.json").read_text())
        pid = st.get("pid")
        try:
            os.kill(pid, 0)
            alive = True
        except (OSError, TypeError):
            alive = False
        print(f"watcher: {'running' if alive else 'not running'} (pid {pid}); connected: "
              f"{'yes' if st.get('connected') and alive else 'no'}; updated {st.get('updated')}")
        print("watcher state:", json.dumps(st.get("watcher")))
        if st.get("last_error"):
            print("last error:", st["last_error"])
    except (OSError, ValueError):
        print("watcher: no state recorded yet")
    return 0


def cmd_pause(args):
    write_private(state_dir() / "paused", "paused by user\n")
    print("Paused. The watcher only observes until you run `resume`.")
    return 0


def cmd_resume(args):
    try:
        (state_dir() / "paused").unlink()
        print("Resumed.")
    except FileNotFoundError:
        print("Was not paused.")
    return 0


def cmd_stop(args):
    r = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
                       capture_output=True, text=True)
    print("Stopped." if r.returncode == 0 else f"launchctl: {r.stderr.strip() or r.stdout.strip()}")
    return r.returncode


def main(argv=None):
    os.umask(0o077)
    p = argparse.ArgumentParser(prog="vhome_companion")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pair", help="pair with the TV and pin its certificate")
    s.add_argument("--host", required=True)
    s.add_argument("--repin", action="store_true", help="accept a different certificate than the pinned one")
    s.set_defaults(fn=cmd_pair)
    s = sub.add_parser("diag", help="show TV info and capabilities")
    s.add_argument("--observe", type=int, default=0, metavar="SECONDS")
    s.add_argument("--save-home", metavar="ID")
    s.set_defaults(fn=cmd_diag)
    s = sub.add_parser("watch", help="run the watcher in the foreground")
    s.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_watch)
    for name, fn in (("status", cmd_status), ("pause", cmd_pause), ("resume", cmd_resume), ("stop", cmd_stop)):
        sub.add_parser(name).set_defaults(fn=fn)
    s = sub.add_parser("autorefresh", help="refresh V/HOME by itself when TV apps change (opt-in)")
    s.add_argument("mode", choices=["on", "off"])
    s.add_argument("--command", help="command to run (default: scripts/refresh-tv.sh in this repo)")
    s.set_defaults(fn=cmd_autorefresh)
    s = sub.add_parser("sync-catalog", help="write tv-catalog/ from the TV")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_sync_catalog)
    args = p.parse_args(argv)
    if args.cmd != "watch":
        setup_logging(state_dir(), console=False)
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return EX_CONFIG
