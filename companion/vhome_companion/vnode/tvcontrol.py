"""The VNode TV controller: one background loop that keeps a session with the TV and applies the
pure Watcher's decisions. Implements contracts.Controller. Everything runs on one asyncio loop.

TV errors never end the process. Standby, a missing TV, a revoked key or a changed certificate
only change the reported state; the loop keeps waiting or retrying at a safe pace.
"""
import asyncio
import ipaddress
import logging
import re
import subprocess
import time
from collections import deque
from datetime import datetime, timezone

from .. import cli, ssap
from ..watcher import ConfigError, Watcher
from . import contracts, ssdp
from .contracts import TvState, WatcherState
from .store import Store

log = logging.getLogger("vhome.vnode.tv")

POWER_URI = "ssap://com.webos.service.tvpower/power/getPowerState"
# The node also reads power state (standby detection); the TV granted this to the Android app already.
PERMISSIONS = ssap.PERMISSIONS + ["READ_POWER_STATE"]
LIST_URI = "ssap://com.webos.applicationManager/listLaunchPoints"
CLOSE_URI = "ssap://system.launcher/close"
STANDBY = frozenset({"Active Standby", "Suspend", "Power Off"})
QUIET_LOG_PREFIXES = ("foreground", "ignored", "late")   # noisy watcher lines stay at DEBUG (SD wear)


def system_ntp_synced():
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "yes"
    except Exception:
        return False


def validate_host(host):
    if isinstance(host, str) and 0 < len(host) <= 253:
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            if re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.local", host, re.I):
                return host
    raise ValueError("host must be an IPv4/IPv6 address or a .local name")


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _RingHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = deque(maxlen=200)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def emit(self, record):
        try:
            self.lines.append(contracts.redact(self.format(record)))
        except Exception:
            pass


class _Refused(Exception):
    pass


class TvController:
    # Seconds. Attributes so tests can shrink them.
    LAUNCH_RETRY_GAP_S = 2.0
    LAUNCH_WINDOW_S = 8.0
    LAUNCH_REQUEST_S = 4.0
    STUCK_CHECK_S = 3.0
    RECOVERY_GAP_S = 600.0
    RECOVERY_WAIT_S = 1.0
    MISMATCH_RETRY_S = 300.0
    WAKE_GAPS_S = (0.0, 3.0, 7.0)    # re-read the foreground at 0, 3 and 10 s after the TV woke
    HEALTHY_SESSION_S = 30.0
    HEARTBEAT_S = 10.0              # proof the link is alive, so an idle TV doesn't read as stale
    NTP_POLL_S = 30.0

    def __init__(self, state_dir, *, connect=ssap.default_connect, clock=time.monotonic,
                 wall=time.time, ssdp_search=ssdp.search, ntp_synced=system_ntp_synced):
        self.dir = state_dir
        self.store = Store(state_dir)
        self._connect, self.clock, self.wall = connect, clock, wall
        self._ssdp, self.ntp_synced = ssdp_search, ntp_synced
        self.control = self.store.load_control()
        self.tv_state = TvState.UNKNOWN
        self.last_error = None
        self.power = None
        self.foreground = None
        self.pairing = {"state": "idle", "detail": ""}
        self.watcher = None
        self.cfg = {}
        self._last_rx = None            # monotonic time anything last arrived from the TV
        self._last_redirect = None
        self._up_since = None
        self._client = None
        self._launcher_missing = False
        self._revoked = self.store.revoked()  # the TV rejected our key: no more attempts until re-paired
        self._nonhome_seen = 0          # foreground events that were not LG Home, for the stuck check
        self._last_recovery = None
        self._wake = asyncio.Event()
        self._task = self._conn_task = self._launch_task = self._pair_task = self._timer = None
        self._ntp_ok = None             # last NTP check; diagnostics must not block the loop
        self._ntp_task = None
        self._tasks = set()             # per-session helpers (pumps, wake check)
        self._explicit = None           # asyncio.Event while an explicit launch() runs
        self._lock = None
        self._ring = _RingHandler()
        lg = logging.getLogger("vhome")
        if lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)
        lg.addHandler(self._ring)
        self._reload()

    # ---- lifecycle ----------------------------------------------------------------------

    def acquire_lock(self):
        """Take the single-watcher lock. This only stops a second process on THIS Pi; it cannot
        stop the Mac companion or the phone's own watcher, which must be switched off separately."""
        self._lock = cli.acquire_lock(self.dir, "vnode")
        return self._lock is not None

    async def start(self):
        self._restore_timed_pause()
        if self._ntp_task is None:
            self._ntp_task = asyncio.create_task(self._wait_for_ntp())
        self._task = asyncio.create_task(self._run())

    async def close(self):
        launch = self._launch_task
        self._cancel_launch()
        for t in (self._task, self._pair_task, self._timer, self._ntp_task):
            if t:
                t.cancel()
        pending = [t for t in (self._task, self._pair_task, self._timer, self._ntp_task, launch, *self._tasks) if t]
        for t in self._tasks:
            t.cancel()
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 5)
            except TimeoutError:
                log.warning("shutdown: some tasks did not stop in time")
        logging.getLogger("vhome").removeHandler(self._ring)
        if self._lock:
            self._lock.close()
            self._lock = None

    def _reload(self):
        """Re-read config and pairing; keep the Watcher (and its counters) unless the ids changed."""
        self.cfg = self.store.tv_config()
        c = self.cfg
        if not (c["host"] and c["key"] and c["pin"]):
            self.watcher = None
            self.tv_state = TvState.PAIRING_REQUIRED
            return
        w = self.watcher
        if w and (w.vhome_id, w.home_ids, w.double_home_escape) == (
                c["vhome_id"], tuple(c["home_ids"]), c["double_home_escape"]):
            return
        try:
            self.watcher = Watcher(c["vhome_id"], c["home_ids"], c["double_home_escape"],
                                   baseline_on_connect=True)
        except ConfigError as e:
            self.watcher = None
            self._error(f"configuration: {e}")
            return
        self._apply_flags()
        if self.tv_state == TvState.PAIRING_REQUIRED:
            self.tv_state = TvState.UNKNOWN

    def _relink(self):
        """New pairing: forget old failures and restart the connection right away."""
        self._revoked = False
        self._reload()
        if self._conn_task:
            self._conn_task.cancel()
        self._wake.set()

    # ---- state helpers ------------------------------------------------------------------

    def _set_state(self, state):
        if state != self.tv_state:
            log.info("TV state: %s", state.value)
        self.tv_state = state

    def _paired(self):
        c = self.cfg
        return bool(c["host"] and c["key"] and c["pin"]) and not self._revoked

    def _error(self, text, level=logging.WARNING):
        text = contracts.redact(text)
        if text != self.last_error:
            log.log(level, "%s", text)
        self.last_error = text

    def _touch(self):
        self._last_rx = self.clock()

    def _refresh_state(self):
        if self.power in STANDBY:
            self._set_state(TvState.STANDBY)
        elif self._launcher_missing:
            self._set_state(TvState.LAUNCHER_MISSING)
        else:
            self._set_state(TvState.CONNECTED)

    def _blocked(self):
        return (self.control["paused"] or not self.control["watcher_enabled"]
                or self._launcher_missing)

    def _apply_flags(self):
        """Make the live Watcher match the persisted switches. Home is only ever observed while blocked."""
        w = self.watcher
        if w is None:
            return
        if self._blocked():
            self._cancel_launch()
            w.pending = None   # a launch we stopped must not later count as a failed redirect
            if not w.paused:
                self._apply(w.pause("owner or safety pause" if self.control["paused"] else "not watching"))
        elif w.paused:
            self._apply(w.resume())

    def _save(self, **changes):
        self.control = self.store.save_control({**self.control, **changes})

    # ---- main loop ----------------------------------------------------------------------

    async def _idle(self, delay):
        """Wait `delay` seconds (None = until re-paired), but wake at once on a new pairing."""
        try:
            await asyncio.wait_for(self._wake.wait(), delay)
        except TimeoutError:
            pass
        self._wake.clear()

    async def _run(self):
        attempt = 0
        while True:
            try:
                if self.watcher is None or self._revoked:
                    if not self._paired():
                        self._set_state(TvState.PAIRING_REQUIRED)
                    await self._idle(None)
                    attempt = 0
                    continue
                self._up_since = None
                try:
                    await self._link_task()
                    attempt = 0
                    self._wake.clear()
                    continue   # the connection was cancelled for a new pairing
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    delay = self._on_link_error(e)
                if self._revoked:
                    continue
                if self._up_since is not None and self.clock() - self._up_since > self.HEALTHY_SESSION_S:
                    attempt = 0
                if delay is None:
                    delay = cli.backoff(attempt)
                    attempt += 1
                await self._idle(delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected error in the TV loop; continuing")
                await self._idle(cli.backoff(attempt))
                attempt += 1

    async def _link_task(self):
        """Run one connection as its own task, so a new pairing can cancel just that."""
        t = self._conn_task = asyncio.create_task(self._link())
        try:
            await asyncio.wait({t})
        except asyncio.CancelledError:
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
            raise
        finally:
            self._conn_task = None
        if not t.cancelled():
            t.result()

    def _on_link_error(self, e):
        """Map a failed connection to a state. Returns a fixed retry delay, or None for backoff."""
        quiet = isinstance(e, ssap.ConnectionLost) or getattr(e, "quiet", False)
        self._error(str(e), logging.INFO if quiet else logging.WARNING)
        if isinstance(e, ssap.PinMismatch):
            self._set_state(TvState.CERTIFICATE_MISMATCH)
            return self.MISMATCH_RETRY_S     # the pin is checked before any key is sent
        if isinstance(e, ssap.NotPaired):
            self._revoked = True
            try:
                self.store.set_revoked(True)
            except OSError as err:
                log.warning("could not persist the revoked marker: %s", err)
            self._set_state(TvState.PAIRING_REQUIRED)
            return None
        if isinstance(e, ssap.RequestFailed) and e.kind == "denied":
            self._set_state(TvState.PERMISSION_DENIED)
        elif self.power in STANDBY:
            self._set_state(TvState.STANDBY)   # the TV itself said it went to standby
        else:
            self._set_state(TvState.UNREACHABLE)
        return None

    async def _link(self):
        c = self.cfg
        client = ssap.Client(c["host"], c["key"], c["pin"], connect=self._connect, permissions=PERMISSIONS)
        try:
            key = await client.open()
            if key and key != c["key"]:   # the TV re-issued the key (e.g. after granting a new permission)
                self.store.save_tv_pairing(c["host"], key, c["pin"])
                self.cfg = self.store.tv_config()
            self._client = client
            self._up_since = self.clock()
            self.last_error = None
            self.power = self.foreground = None
            self._launcher_missing = False
            self._touch()
            log.info("connected to %s", c["host"])
            self._set_state(TvState.CONNECTED)
            await self._session(client)
        finally:
            self._client = None
            self.foreground = None
            if self.power not in STANDBY:
                self.power = None
            self._cancel_launch()
            for t in list(self._tasks):
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            await client.close()

    # ---- session ------------------------------------------------------------------------

    async def _req(self, client, uri, payload=None, timeout=None):
        r = await client.request(uri, payload, timeout=timeout)
        self._touch()
        return r

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _pump(self, sub, kind, q):
        while True:
            try:
                item = await sub.get()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                q.put_nowait((kind, e))
                return
            q.put_nowait((kind, item))

    async def _session(self, client):
        w = self.watcher
        q = asyncio.Queue()
        self._apply(w.on_connected(self.clock()))
        self._apply_flags()
        self._spawn(self._pump(await client.subscribe(cli.FG_URI), "fg", q))
        try:
            self._spawn(self._pump(await client.subscribe(POWER_URI), "power", q))
        except ssap.ConnectionLost:
            raise
        except ssap.SsapError as e:
            log.info("power state unavailable (%s); watching anyway", e)
        await self._check_launcher(client)
        self._spawn(self._heartbeat(client))
        while True:
            dl = w.next_deadline()
            try:
                kind, item = await asyncio.wait_for(
                    q.get(), None if dl is None else max(0.0, dl - self.clock()))
            except TimeoutError:
                self._apply(w.on_tick(self.clock()))
                self._settle()
                continue
            if isinstance(item, Exception):
                if kind == "power" and isinstance(item, ssap.RequestFailed):
                    log.info("power state unavailable (%s); watching anyway", item)
                    self.power = None
                    continue
                raise item
            self._touch()
            if kind == "fg":
                self._on_foreground(item)
            else:
                self._on_power(item)
            self._settle()

    async def _heartbeat(self, client):
        """One cheap request every HEARTBEAT_S; a success refreshes age_s. Failures are left to the
        subscriptions, which end the session when the link is really gone."""
        uri = POWER_URI
        while True:
            await asyncio.sleep(self.HEARTBEAT_S)
            try:
                await self._req(client, uri, timeout=5)
            except ssap.RequestFailed:
                uri = cli.FG_URI          # power service not readable on this firmware
            except (ssap.SsapError, OSError):
                pass

    def _settle(self):
        """Drop launch/recovery work whose token the watcher has already resolved."""
        if self.watcher.pending is None:
            self._cancel_launch()

    async def _check_launcher(self, client):
        try:
            r = await self._req(client, LIST_URI, timeout=8)
        except (ssap.RequestFailed, ssap.RequestTimeout) as e:
            log.info("launcher check skipped: %s", e)
            return
        points = r.get("launchPoints")
        if isinstance(points, list) and points:
            ids = {p.get("id") for p in points if isinstance(p, dict)}
            self._launcher_missing = self.watcher.vhome_id not in ids
            if self._launcher_missing:
                log.warning("V/HOME is not installed on the TV (%s); not launching", self.watcher.vhome_id)
                self._refresh_state()
                self._apply_flags()

    def _on_foreground(self, payload):
        w = self.watcher
        app = cli.extract_app_id(payload)
        if app:
            self.foreground = app
            if app not in w.home_ids:
                self._nonhome_seen += 1
            if app == w.vhome_id and self._explicit:
                self._explicit.set()
        if app in w.home_ids and self.power in STANDBY:
            log.debug("Home while the TV is in standby: ignored")
            return
        self._apply(w.on_foreground(app, self.clock()))

    def _on_power(self, payload):
        s = payload.get("state")
        if not isinstance(s, str) or not s:
            return
        was, self.power = self.power, s
        if s != was:
            log.info("TV power: %s", s)
        self._refresh_state()
        if s == "Active" and was != "Active":
            self._apply(self.watcher.on_power_active(self.clock()))
            if was in STANDBY and self.control["power_on_launch"]:
                self._spawn(self._wake_check())

    async def _wake_check(self):
        """Opt-in (power_on_launch): the TV just woke in this session; if it booted into LG Home,
        treat that as a Home press. Re-reads the foreground because it may not be known yet."""
        w, client = self.watcher, self._client
        for gap in self.WAKE_GAPS_S:
            await asyncio.sleep(gap)
            try:
                app = cli.extract_app_id(await self._req(client, cli.FG_URI, timeout=5))
            except (ssap.SsapError, OSError):
                return
            if app == w.vhome_id:
                return
            if app in w.home_ids:
                if w.pending or self._blocked():
                    return
                # Reset like a reconnect, but without the baseline, so this Home counts as a transition.
                w.baseline_on_connect = False
                acts = w.on_connected(self.clock())
                w.baseline_on_connect = True
                self._apply(acts + w.on_foreground(app, self.clock()))
                return
            if app:
                return

    # ---- applying watcher actions -------------------------------------------------------

    def _apply(self, actions):
        for a in actions:
            if a.kind == "log":
                quiet = a.text.startswith(QUIET_LOG_PREFIXES)
                level = logging.DEBUG if quiet else getattr(logging, a.level.upper(), logging.INFO)
                log.log(level, "%s", a.text)
            elif a.kind == "pause":
                self._breaker_pause()
            elif a.kind == "launch":
                self._cancel_launch()
                self._last_redirect = self.clock()
                self._launch_task = asyncio.create_task(self._launch_and_recover(a.token, a.app_id))

    def _breaker_pause(self):
        if not self.control["paused"]:
            try:
                self._save(paused=True, pause_reason="safety", paused_until=None)
            except OSError as e:
                log.error("could not save the safety pause: %s", e)
                self.control = {**self.control, "paused": True, "pause_reason": "safety"}
        self._cancel_launch()

    def _cancel_launch(self):
        t, self._launch_task = self._launch_task, None
        if t and t is not asyncio.current_task():
            t.cancel()

    def _live(self, token):
        p = self.watcher.pending if self.watcher else None
        return bool(p and p["token"] == token and not self._blocked() and self._client)

    async def _launch_and_recover(self, token, app_id):
        client, w = self._client, self.watcher
        start, err = self.clock(), ""
        while True:
            try:
                await self._req(client, cli.LAUNCH_URI, {"id": app_id}, timeout=self.LAUNCH_REQUEST_S)
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = str(e) or type(e).__name__
                if isinstance(e, ssap.ConnectionLost):
                    return    # the session is over; the next connect starts from a clean slate
            if self.clock() - start + self.LAUNCH_RETRY_GAP_S >= self.LAUNCH_WINDOW_S:
                self._apply(w.on_launch_result(token, False, self.clock(), err))
                return
            await asyncio.sleep(self.LAUNCH_RETRY_GAP_S)
            if not self._live(token):
                return
        seen = self._nonhome_seen
        self._apply(w.on_launch_result(token, True, self.clock()))
        await self._recover_if_stuck(client, token, app_id, seen)

    async def _still_on_home(self, client, token, seen):
        """The owner may have moved on while we waited: never relaunch over another app."""
        if not self._live(token) or self._nonhome_seen != seen:
            return False
        try:
            front = cli.extract_app_id(await self._req(client, cli.FG_URI, timeout=3))
        except (ssap.SsapError, OSError):
            return False
        return front in self.watcher.home_ids and self._live(token) and self._nonhome_seen == seen

    async def _recover_if_stuck(self, client, token, app_id, seen):
        """V/HOME stuck in the background: launch says OK, nothing appears. Close it and launch once."""
        await asyncio.sleep(self.STUCK_CHECK_S)
        if not self._live(token) or self._nonhome_seen != seen:
            return
        try:
            front = cli.extract_app_id(await self._req(client, cli.FG_URI, timeout=5))
        except (ssap.SsapError, OSError):
            return
        if front not in self.watcher.home_ids or not self._live(token):
            return
        if self._last_recovery is not None and self.clock() - self._last_recovery < self.RECOVERY_GAP_S:
            return
        if self._nonhome_seen != seen:
            return
        self._last_recovery = self.clock()
        log.info("V/HOME accepted the launch but did not appear; restarting it")
        try:
            await self._req(client, CLOSE_URI, {"id": app_id}, timeout=3)
        except (ssap.SsapError, OSError):
            pass
        await asyncio.sleep(self.RECOVERY_WAIT_S)
        if not await self._still_on_home(client, token, seen):
            return
        try:
            await self._req(client, cli.LAUNCH_URI, {"id": app_id}, timeout=self.LAUNCH_REQUEST_S)
        except (ssap.SsapError, OSError) as e:
            log.warning("restart of V/HOME failed: %s", e)

    # ---- Controller API -----------------------------------------------------------------

    def status(self):
        now = self.clock()
        c, w = self.cfg, self.watcher
        paired = self._paired()
        link_up = self._client is not None
        age = lambda t: None if t is None else round(now - t, 1)
        if w is None or not paired:
            wstate = WatcherState.NOT_READY
        elif not self.control["watcher_enabled"]:
            wstate = WatcherState.DISABLED
        elif self.control["paused"]:
            wstate = (WatcherState.SAFETY_PAUSED if self.control["pause_reason"] == "safety"
                      else WatcherState.USER_PAUSED)
        else:
            wstate = WatcherState.WATCHING
        stats = w.stats if w else {}
        return {
            "tv": {"state": self.tv_state.value, "host": c["host"] or None, "paired": paired,
                   "power": self.power if (link_up or self.power in STANDBY) else None,
                   "foreground": self.foreground if link_up else None, "age_s": age(self._last_rx),
                   "last_error": self.last_error, "pairing": dict(self.pairing)},
            "watcher": {"state": wstate.value, "enabled": self.control["watcher_enabled"],
                        "paused": self.control["paused"], "pause_reason": self.control["pause_reason"],
                        "paused_until": self.control["paused_until"],
                        "redirects": stats.get("redirects", 0), "ok": stats.get("ok", 0),
                        "failed": stats.get("failed", 0), "last_latency_s": stats.get("last_latency_s"),
                        "last_failure": stats.get("last_failure"),
                        "last_redirect_age_s": age(self._last_redirect)},
        }

    async def pause(self, minutes):
        if minutes is not None and not (isinstance(minutes, int) and 1 <= minutes <= 1440):
            return contracts.outcome("failed", "minutes must be 1..1440")
        until = _iso(self.wall() + minutes * 60) if minutes else None
        try:
            self._save(paused=True, pause_reason="user", paused_until=until)
        except OSError as e:
            return contracts.outcome("failed", f"could not save: {e}")
        self._apply_flags()
        self._schedule_resume(minutes * 60 if minutes else None)
        log.info("paused by the owner%s", f" for {minutes} min" if minutes else "")
        return contracts.outcome("confirmed")

    async def resume(self):
        try:
            self._save(paused=False, pause_reason=None, paused_until=None)
        except OSError as e:
            return contracts.outcome("failed", f"could not save: {e}")
        self._schedule_resume(None)
        self._apply_flags()
        return contracts.outcome("confirmed")

    async def set_enabled(self, enabled):
        try:
            self._save(watcher_enabled=bool(enabled))
        except OSError as e:
            return contracts.outcome("failed", f"could not save: {e}")
        log.info("watcher %s", "enabled" if enabled else "handed to the phone")
        self._apply_flags()
        return contracts.outcome("confirmed")

    def _schedule_resume(self, seconds):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if seconds is not None:
            self._timer = asyncio.create_task(self._resume_later(seconds))

    async def _resume_later(self, seconds):
        await asyncio.sleep(seconds)
        self._timer = None
        log.info("timed pause ended")
        await self.resume()

    async def _wait_for_ntp(self, deferred_pause=False):
        """Background: keep the NTP state fresh for diagnostics; resume a deferred timed pause once synced."""
        while True:
            self._ntp_ok = bool(await asyncio.to_thread(self.ntp_synced))
            if self._ntp_ok:
                break
            await asyncio.sleep(self.NTP_POLL_S)
        if deferred_pause and self.control["paused"] and self.control["paused_until"]:
            self._restore_timed_pause()

    def _restore_timed_pause(self):
        """After a restart the wall clock may be wrong (no RTC). Only trust it when NTP is synced;
        otherwise stay paused until the owner resumes, which is the safe side."""
        until = self.control["paused_until"]
        if not (self.control["paused"] and until):
            return
        self._ntp_ok = bool(self.ntp_synced())
        if not self._ntp_ok:
            log.warning("timed pause kept until the clock is NTP-synced")
            self._ntp_task = asyncio.create_task(self._wait_for_ntp(deferred_pause=True))
            return
        left = datetime.fromisoformat(until).timestamp() - self.wall()
        if left <= 0:
            log.info("timed pause expired while the node was off")
            self._schedule_resume(0)
        else:
            self._schedule_resume(left)

    async def launch(self):
        client = self._client
        if client is None:
            return contracts.outcome("failed", "TV not connected")
        if self._launcher_missing:
            return contracts.outcome("failed", "V/HOME is not installed on the TV")
        if self._explicit:
            return contracts.outcome("failed", "busy")
        vhome = self.cfg["vhome_id"]
        seen = self._explicit = asyncio.Event()
        start = self.clock()
        try:
            try:
                await self._req(client, cli.LAUNCH_URI, {"id": vhome}, timeout=8)
            except (ssap.RequestTimeout, ssap.ConnectionLost, TimeoutError) as e:
                return contracts.outcome("unknown", str(e))
            except (ssap.SsapError, OSError) as e:
                return contracts.outcome("failed", str(e))
            if self.foreground == vhome:
                return contracts.outcome("confirmed", "V/HOME is in front")
            try:
                async with asyncio.timeout(max(0.0, contracts.LAUNCH_WAIT_S - (self.clock() - start))):
                    await seen.wait()
                return contracts.outcome("confirmed", "V/HOME is in front")
            except TimeoutError:
                return contracts.outcome("accepted", "the TV accepted the launch")
        finally:
            self._explicit = None

    async def start_tv_pair(self, host, repin):
        host = validate_host(host)
        if self._pair_task and not self._pair_task.done():
            return contracts.outcome("failed", "busy")
        self.pairing = {"state": "waiting_prompt", "detail": "accept the prompt on the TV"}
        self._pair_task = asyncio.create_task(self._pair_job(host, bool(repin)))
        return contracts.outcome("accepted")

    async def _pair_job(self, host, repin):
        c = ssap.Client(host, None, None, trust_new=True, connect=self._connect, permissions=PERMISSIONS)
        try:
            key = await c.open(pair_timeout=60)
            old_pin = self.store.paired()[1]
            if old_pin and old_pin != c.cert_sha256 and not repin:
                raise _Refused("different TV certificate; repin needed")
            self.store.save_tv_pairing(host, key, c.cert_sha256)
            self.pairing = {"state": "done", "detail": ""}
            log.info("paired with %s", host)
            self._relink()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.pairing = {"state": "failed", "detail": contracts.redact(str(e))[:200]}
            log.warning("pairing failed: %s", self.pairing["detail"])
        finally:
            await c.close()

    async def discover_tvs(self):
        try:
            found = await asyncio.wait_for(self._ssdp(timeout=3.0), 4.0)
        except (TimeoutError, OSError):
            found = []
        pinned = self.cfg["host"] if self.cfg.get("pin") else None
        return [{"host": h, "pinned": h == pinned} for h in dict.fromkeys(found)]

    def diagnostics(self):
        c, w = self.cfg, self.watcher
        return {
            "checks": {"paired": bool(c["key"] and c["pin"]) and not self._revoked,
                       "host": c["host"] or None, "pinned": bool(c["pin"]),
                       "home_ids": list(c["home_ids"]), "vhome_id": c["vhome_id"],
                       "watcher_ready": w is not None, "link_up": self._client is not None,
                       "launcher_missing": self._launcher_missing,
                       "power_on_launch": self.control["power_on_launch"],
                       "ntp_synced": self._ntp_ok, "last_error": self.last_error},
            "log": list(self._ring.lines),
            "counters": dict(w.stats) if w else {},
        }
