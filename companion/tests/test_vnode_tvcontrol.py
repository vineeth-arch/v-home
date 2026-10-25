import asyncio
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import cli, ssap  # noqa: E402
from vhome_companion.vnode import contracts, tvcontrol  # noqa: E402
from vhome_companion.vnode.store import Store  # noqa: E402
from vhome_companion.vnode.tvcontrol import TvController  # noqa: E402

VH, HOME, LIVE = "com.designinnsaeit.vhome", "com.webos.app.home", "com.webos.app.livetv"
CLOSE = tvcontrol.CLOSE_URI
CERT = "ab" * 32


class FakeTv:
    """One scripted TV. Every Client the controller creates talks to it."""

    def __init__(self):
        self.opens = []                 # (key, pin, trust_new) per open()
        self.open_error = None          # raised by open() while set
        self.pair_key = "new-key"
        self.cert = CERT
        self.front = LIVE
        self.requests = []              # (uri, payload)
        self.on_launch = None           # callable(payload) -> payload, may raise
        self.launch_points = [{"id": VH}, {"id": HOME}]
        self.client = None

    def launches(self):
        return [p for u, p in self.requests if u == cli.LAUNCH_URI]

    def closes(self):
        return [p for u, p in self.requests if u == CLOSE]

    def event(self, app):
        self.front = app
        self.client.subs[cli.FG_URI]._q.put_nowait({"returnValue": True, "appId": app})

    def power(self, state):
        self.client.subs[tvcontrol.POWER_URI]._q.put_nowait({"returnValue": True, "state": state})

    def drop(self):
        self.client.subs[cli.FG_URI]._q.put_nowait(ssap.ConnectionLost("link dropped"))

    def factory(self):
        tv = self

        class FakeClient:
            def __init__(self, host, client_key=None, pin=None, trust_new=False, connect=None, request_timeout=10.0,
                         permissions=None):
                self.host, self.key, self.pin, self.trust_new = host, client_key, pin, trust_new
                tv.permissions = permissions
                self.cert_sha256 = None
                self.subs = {}

            async def open(self, pair_timeout=60.0, on_prompt=None):
                tv.opens.append((self.key, self.pin, self.trust_new))
                await asyncio.sleep(0)
                if tv.open_error:
                    raise tv.open_error
                self.cert_sha256 = tv.cert
                if not self.trust_new:
                    tv.client = self
                return self.key or tv.pair_key

            async def subscribe(self, uri, payload=None):
                self.subs[uri] = ssap.Subscription()
                return self.subs[uri]

            async def request(self, uri, payload=None, timeout=None):
                tv.requests.append((uri, payload))
                if uri == cli.FG_URI:
                    return {"returnValue": True, "appId": tv.front}
                if uri == tvcontrol.LIST_URI:
                    return {"returnValue": True, "launchPoints": tv.launch_points}
                if uri == cli.LAUNCH_URI and tv.on_launch:
                    return tv.on_launch(payload)
                return {"returnValue": True}

            async def close(self):
                pass

        return FakeClient


async def until(pred, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


async def settle(t=0.05):
    await asyncio.sleep(t)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.tv = FakeTv()
        p = mock.patch.object(tvcontrol.ssap, "Client", self.tv.factory())
        p.start()
        self.addCleanup(p.stop)
        self.ctls = []
        self.t = 1000.0
        self.delays = []

    def pair(self, host="192.168.1.9"):
        Store(self.d).save_tv_pairing(host, "key", CERT)

    def make(self, paired=True, fast=True, **kw):
        if paired:
            self.pair()
        kw.setdefault("clock", lambda: self.t)
        kw.setdefault("wall", lambda: 1_700_000_000.0)
        kw.setdefault("ntp_synced", lambda: True)
        kw.setdefault("ssdp_search", self._no_ssdp)
        c = TvController(self.d, connect=None, **kw)
        c.LAUNCH_WINDOW_S = 0.0     # one attempt unless a test says otherwise
        c.STUCK_CHECK_S, c.RECOVERY_WAIT_S = 0.05, 0.01
        if fast:
            async def idle(delay):
                if delay is not None:
                    self.delays.append(delay)
                if delay is None or delay >= 300:
                    await c._wake.wait()
                else:
                    await asyncio.sleep(0.01)
                c._wake.clear()
            c._idle = idle
        self.ctls.append(c)
        return c

    async def _no_ssdp(self, timeout=3.0):
        return []

    async def asyncTearDown(self):
        for c in self.ctls:
            await c.close()

    async def up(self, **kw):
        c = self.make(**kw)
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED and c._client is not None)
        return c

    async def live(self, c):
        """Connected, with the baseline consumed by a Live TV foreground."""
        self.tv.event(LIVE)
        await until(lambda: c.foreground == LIVE)


class ReconnectTests(Base):
    async def test_first_foreground_live_tv_no_launch_then_home_launches(self):
        c = await self.up()
        await self.live(c)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())
        self.assertEqual(self.tv.launches(), [{"id": VH}])

    async def test_first_foreground_lg_home_after_reconnect_is_not_a_takeover(self):
        c = await self.up()
        await self.live(c)
        self.tv.drop()
        await until(lambda: len(self.tv.opens) == 2 and c._client is not None)
        self.tv.front = HOME
        self.tv.event(HOME)
        await until(lambda: c.foreground == HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.tv.event(LIVE)
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())
        self.assertEqual(len(self.tv.launches()), 1)

    async def test_connect_while_live_tv_after_reconnect_no_launch(self):
        c = await self.up()
        self.tv.drop()
        await until(lambda: len(self.tv.opens) == 2 and c._client is not None)
        self.tv.event(LIVE)
        await settle()
        self.assertEqual(self.tv.launches(), [])


class OwnershipTests(Base):
    async def test_disabled_never_launches_and_persists(self):
        c = await self.up()
        await self.live(c)
        self.assertEqual((await c.set_enabled(False))["outcome"], "confirmed")
        self.tv.event(HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.assertEqual(c.status()["watcher"]["state"], "disabled")
        c2 = self.make()
        self.assertEqual(c2.status()["watcher"]["state"], "disabled")
        self.assertFalse(c2.status()["watcher"]["enabled"])
        await c.close()
        self.ctls.remove(c)
        self.tv.requests.clear()
        await c2.start()
        await until(lambda: c2._client is not None)
        await self.live(c2)
        self.tv.event(HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        await c2.set_enabled(True)
        self.tv.event(LIVE)
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())

    async def test_disable_cancels_a_pending_launch_and_it_is_not_a_failure(self):
        c = await self.up()
        await self.live(c)
        self.tv.on_launch = lambda p: {"returnValue": True}
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())
        await c.set_enabled(False)
        self.assertIsNone(c.watcher.pending)
        self.assertEqual(c.status()["watcher"]["failed"], 0)

    async def test_second_lock_in_same_state_dir_is_refused(self):
        a, b = self.make(fast=False), self.make(fast=False)
        self.assertTrue(a.acquire_lock())
        self.assertFalse(b.acquire_lock())
        await a.close()
        self.assertTrue(b.acquire_lock())


class LinkErrorTests(Base):
    async def test_certificate_mismatch_waits_300_s_and_sends_no_key(self):
        self.tv.open_error = ssap.PinMismatch("different certificate")
        c = self.make()
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.CERTIFICATE_MISMATCH)
        await settle()
        self.assertEqual(len(self.tv.opens), 1)
        self.assertEqual(self.delays, [300.0])   # the loop is parked in the 300 s wait
        self.assertEqual(self.tv.requests, [])
        self.assertEqual(c.status()["tv"]["state"], "certificate_mismatch")
        self.assertFalse(c._task.done())

    async def test_not_paired_stops_connecting_until_start_tv_pair_succeeds(self):
        self.tv.open_error = ssap.NotPaired("key revoked")
        c = self.make()
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.PAIRING_REQUIRED)
        await settle(0.1)
        self.assertEqual(len(self.tv.opens), 1)
        self.assertFalse(c.status()["tv"]["paired"])
        self.assertEqual(c.status()["watcher"]["state"], "not_ready")
        self.tv.open_error = None
        self.assertEqual((await c.start_tv_pair("192.168.1.9", False))["outcome"], "accepted")
        await c._pair_task
        self.assertEqual(c.pairing["state"], "done")
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED)
        self.assertEqual(self.tv.opens[-1][:2], ("new-key", CERT))
        self.assertTrue(c.status()["tv"]["paired"])

    async def test_revoked_key_is_not_retried_after_restart(self):
        # The TV would show its pairing prompt on every attempt with a revoked key.
        self.tv.open_error = ssap.NotPaired("key revoked")
        c = self.make()
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.PAIRING_REQUIRED)
        await c.close()
        c2 = self.make(paired=False)       # same state dir, key still on disk
        await c2.start()
        await settle(0.1)
        self.assertEqual(len(self.tv.opens), 1)
        self.assertEqual(c2.status()["tv"]["state"], "pairing_required")

    async def test_never_contacts_tv_without_a_key(self):
        c = self.make(paired=False)
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.PAIRING_REQUIRED)
        await settle()
        self.assertEqual(self.tv.opens, [])
        self.assertEqual(c.status()["watcher"]["state"], "not_ready")

    async def test_permission_denied_on_foreground_subscription(self):
        c = await self.up()
        self.tv.client.subs[cli.FG_URI]._q.put_nowait(ssap.RequestFailed("401 insufficient permissions"))
        await until(lambda: len(self.tv.opens) >= 2 or c.tv_state == contracts.TvState.PERMISSION_DENIED)
        self.assertIn(c.tv_state, (contracts.TvState.PERMISSION_DENIED, contracts.TvState.CONNECTED))
        self.assertNotEqual(c.status()["tv"]["state"], "unknown")

    async def test_launcher_missing_does_not_launch(self):
        self.tv.launch_points = [{"id": "other.app"}, {"id": HOME}]
        c = self.make()
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.LAUNCHER_MISSING)
        await self.live(c)
        self.tv.event(HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.assertEqual(c.status()["tv"]["state"], "launcher_missing")
        self.assertEqual((await c.launch())["outcome"], "failed")

    async def test_launch_point_list_failure_is_ignored(self):
        orig = self.tv.factory()

        class NoList(orig):
            async def request(self, uri, payload=None, timeout=None):
                if uri == tvcontrol.LIST_URI:
                    raise ssap.RequestFailed("nope")
                return await super().request(uri, payload, timeout)

        with mock.patch.object(tvcontrol.ssap, "Client", NoList):
            c = await self.up()
        self.assertEqual(c.tv_state, contracts.TvState.CONNECTED)


class RecoveryTests(Base):
    async def home_launch(self, c):
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())

    async def test_stuck_launch_is_closed_and_relaunched_once(self):
        c = await self.up()
        await self.live(c)
        await self.home_launch(c)           # V/HOME never comes to the front: fg still Home
        await until(lambda: len(self.tv.launches()) == 2)
        self.assertEqual(self.tv.closes(), [{"id": VH}])
        await settle(0.2)
        self.assertEqual(len(self.tv.launches()), 2)    # once per token

    async def test_pause_before_the_check_sends_no_close_or_relaunch(self):
        c = await self.up()
        await self.live(c)
        c.STUCK_CHECK_S = 0.2
        await self.home_launch(c)
        await settle(0.05)
        await c.pause(None)
        await settle(0.4)
        self.assertEqual(self.tv.closes(), [])
        self.assertEqual(len(self.tv.launches()), 1)
        self.assertEqual(c.status()["watcher"]["failed"], 0)

    async def test_user_navigated_elsewhere_means_no_recovery(self):
        c = await self.up()
        await self.live(c)
        c.STUCK_CHECK_S = 0.15
        await self.home_launch(c)
        self.tv.event("netflix")
        await settle(0.4)
        self.assertEqual(self.tv.closes(), [])
        self.assertEqual(len(self.tv.launches()), 1)

    async def test_navigation_during_close_wait_blocks_the_relaunch(self):
        # Review finding: the owner switches to Live TV while V/HOME is being closed.
        c = await self.up()
        await self.live(c)
        c.RECOVERY_WAIT_S = 0.2
        await self.home_launch(c)
        await until(lambda: self.tv.closes())
        self.tv.event(LIVE)
        await settle(0.4)
        self.assertEqual(len(self.tv.launches()), 1)    # no relaunch over Live TV

    async def test_fresh_read_not_home_means_no_recovery(self):
        c = await self.up()
        await self.live(c)
        c.STUCK_CHECK_S = 0.1
        await self.home_launch(c)
        self.tv.front = VH                  # V/HOME is up, the event is just late
        await settle(0.3)
        self.assertEqual(self.tv.closes(), [])

    async def test_at_most_one_recovery_per_600_s(self):
        c = await self.up()
        await self.live(c)
        await self.home_launch(c)
        await until(lambda: len(self.tv.launches()) == 2)
        self.tv.event(VH)                   # confirmed
        await settle()
        self.tv.event(LIVE)                 # second Home cycle inside the window: no recovery
        self.tv.event(HOME)
        await until(lambda: len(self.tv.launches()) == 3)
        await settle(0.2)
        self.assertEqual(len(self.tv.closes()), 1)
        self.tv.event(VH)
        await settle()
        self.t += 700                       # window over: recovery allowed again
        self.tv.event(LIVE)
        self.tv.event(HOME)
        await until(lambda: len(self.tv.closes()) == 2)


class PersistenceTests(Base):
    async def test_user_pause_survives_restart(self):
        c = await self.up()
        self.assertEqual((await c.pause(60))["outcome"], "confirmed")
        w = c.status()["watcher"]
        self.assertEqual((w["state"], w["pause_reason"], w["paused"]), ("user_paused", "user", True))
        self.assertEqual(w["paused_until"], "2023-11-14T23:13:20Z")
        await c.close()
        self.ctls.remove(c)
        c2 = self.make()
        self.assertEqual(c2.status()["watcher"]["state"], "user_paused")
        await c2.start()
        await until(lambda: c2._client is not None)
        await self.live(c2)
        self.tv.event(HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.assertEqual((await c2.resume())["outcome"], "confirmed")
        self.assertEqual(c2.status()["watcher"]["state"], "watching")
        self.assertIsNone(c2.status()["watcher"]["paused_until"])

    async def test_timed_pause_without_ntp_stays_paused_after_restart(self):
        c = await self.up()
        await c.pause(1)
        await c.close()
        self.ctls.remove(c)
        c2 = self.make(ntp_synced=lambda: False, wall=lambda: 1_700_000_000.0 + 86400)  # clock says: long past
        await c2.start()
        await settle(0.1)
        self.assertEqual(c2.status()["watcher"]["state"], "user_paused")
        self.assertIsNotNone(c2.status()["watcher"]["paused_until"])
        self.assertIsNone(c2._timer)

    async def test_expired_timed_pause_resumes_when_clock_is_synced(self):
        c = self.make()
        await c.pause(1)
        c2 = self.make(wall=lambda: 1_700_000_000.0 + 3600)
        await c2.start()
        await until(lambda: c2.status()["watcher"]["state"] == "watching")
        self.assertIsNone(Store(self.d).load_control()["paused_until"])

    async def test_future_timed_pause_with_ntp_schedules_a_timer(self):
        c = self.make()
        await c.pause(30)
        c2 = self.make()
        await c2.start()
        await settle()
        self.assertEqual(c2.status()["watcher"]["state"], "user_paused")
        self.assertIsNotNone(c2._timer)

    async def test_safety_breaker_pause_survives_restart(self):
        self.tv.on_launch = mock.Mock(side_effect=ssap.RequestFailed("app not found"))
        c = await self.up()
        await self.live(c)
        for _ in range(3):
            self.tv.event(HOME)
            await until(lambda n=len(self.tv.launches()): len(self.tv.launches()) > n)
            await settle(0.03)
            self.tv.event("netflix")
            await settle(0.03)
        await until(lambda: c.status()["watcher"]["state"] == "safety_paused")
        self.assertEqual(c.status()["watcher"]["pause_reason"], "safety")
        self.assertEqual(c.status()["headline" if False else "watcher"]["failed"], 3)
        await c.close()
        self.ctls.remove(c)
        c2 = self.make()
        self.assertEqual(c2.status()["watcher"]["state"], "safety_paused")

    async def test_failed_write_is_reported_not_applied(self):
        c = await self.up()
        with mock.patch.object(c.store, "save_control", side_effect=OSError("disk full")):
            self.assertEqual((await c.pause(5))["outcome"], "failed")
            self.assertEqual((await c.set_enabled(False))["outcome"], "failed")
        self.assertEqual(c.status()["watcher"]["state"], "watching")

    async def test_invalid_minutes_rejected(self):
        c = self.make()
        self.assertEqual((await c.pause(0))["outcome"], "failed")
        self.assertEqual((await c.pause(1441))["outcome"], "failed")


class ServiceHealthTests(Base):
    async def test_unreachable_tv_keeps_the_loop_alive(self):
        self.tv.open_error = ssap.Unreachable("192.168.1.9: timed out")
        c = self.make()
        await c.start()
        await until(lambda: len(self.tv.opens) >= 4)
        self.assertFalse(c._task.done())
        s = c.status()
        self.assertEqual(s["tv"]["state"], "unreachable")
        self.assertIsNone(s["tv"]["age_s"])
        self.assertEqual(s["watcher"]["state"], "watching")
        self.assertTrue(all(1.0 < d < 3.0 or d <= 60 for d in self.delays))
        self.tv.open_error = None
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED)

    async def test_unexpected_exception_does_not_end_the_loop(self):
        self.tv.open_error = ValueError("surprise")
        c = self.make()
        await c.start()
        await until(lambda: len(self.tv.opens) >= 3)
        self.assertFalse(c._task.done())

    async def test_standby_is_reported_and_home_is_ignored(self):
        c = await self.up()
        await self.live(c)
        self.tv.power("Active Standby")
        await until(lambda: c.tv_state == contracts.TvState.STANDBY)
        self.assertEqual(c.status()["tv"]["power"], "Active Standby")
        self.tv.event(HOME)
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.assertEqual(c.status()["tv"]["foreground"], HOME)     # recorded anyway
        self.tv.power("Active")
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED)
        self.tv.event(LIVE)
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())

    async def test_link_loss_never_reports_connected(self):
        c = await self.up()
        self.tv.open_error = ssap.Unreachable("gone")
        self.tv.drop()
        await until(lambda: c._client is None)
        await until(lambda: c.tv_state == contracts.TvState.UNREACHABLE)
        s = c.status()["tv"]
        self.assertNotEqual(s["state"], "connected")
        self.assertIsNone(s["foreground"])

    async def test_power_active_clears_the_failure_window(self):
        self.tv.on_launch = mock.Mock(side_effect=ssap.RequestFailed("boom"))
        c = await self.up()
        await self.live(c)

        async def fail_once():
            n = len(self.tv.launches())
            self.tv.event(HOME)
            await until(lambda: len(self.tv.launches()) > n)
            await settle(0.03)
            self.tv.event("netflix")
            await settle(0.03)

        await fail_once()
        await fail_once()
        self.tv.power("Active Standby")
        await until(lambda: c.tv_state == contracts.TvState.STANDBY)
        self.tv.power("Active")
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED)
        await fail_once()
        self.assertEqual(c.status()["watcher"]["state"], "watching")
        self.assertEqual(c.status()["watcher"]["failed"], 3)

    async def test_power_subscription_failure_is_tolerated(self):
        c = await self.up()
        self.tv.client.subs[tvcontrol.POWER_URI]._q.put_nowait(ssap.RequestFailed("unknown method"))
        await settle()
        await self.live(c)
        self.tv.event(HOME)
        await until(lambda: self.tv.launches())
        self.assertIsNone(c.status()["tv"]["power"])

    async def test_power_on_launch_only_after_an_in_session_wake(self):
        c = await self.up()
        await c.close()
        self.ctls.remove(c)
        Store(self.d).save_control({"power_on_launch": True})
        self.tv.requests.clear()
        c = await self.up()
        c.WAKE_GAPS_S = (0.0, 0.01)
        self.tv.front = HOME
        self.tv.power("Active")              # first report after connect: not a wake
        await settle()
        self.assertEqual(self.tv.launches(), [])
        self.tv.power("Active Standby")
        await until(lambda: c.tv_state == contracts.TvState.STANDBY)
        self.tv.power("Active")              # woke in this session, booted into Home
        await until(lambda: self.tv.launches())

    async def test_power_on_launch_off_by_default(self):
        c = await self.up()
        self.tv.power("Active Standby")
        await until(lambda: c.tv_state == contracts.TvState.STANDBY)
        self.tv.front = HOME
        self.tv.power("Active")
        await settle(0.15)
        self.assertEqual(self.tv.launches(), [])


class ExplicitLaunchTests(Base):
    async def test_not_connected_fails(self):
        c = self.make()
        self.assertEqual(await c.launch(), {"outcome": "failed", "detail": "TV not connected"})

    async def test_confirmed_when_the_foreground_event_arrives(self):
        c = await self.up()
        self.tv.on_launch = lambda p: asyncio.get_running_loop().call_later(0.02, self.tv.event, VH) or {"returnValue": True}
        r = await c.launch()
        self.assertEqual(r["outcome"], "confirmed")
        self.assertEqual(c.status()["watcher"]["redirects"], 0)

    async def test_accepted_when_nothing_comes_to_the_front(self):
        c = await self.up()
        with mock.patch.object(tvcontrol.contracts, "LAUNCH_WAIT_S", 0.1):
            r = await c.launch()
        self.assertEqual(r["outcome"], "accepted")

    async def test_request_timeout_is_unknown(self):
        c = await self.up()
        self.tv.on_launch = mock.Mock(side_effect=ssap.RequestTimeout("no response"))
        self.assertEqual((await c.launch())["outcome"], "unknown")

    async def test_rejected_request_is_failed(self):
        c = await self.up()
        self.tv.on_launch = mock.Mock(side_effect=ssap.RequestFailed("app not found"))
        self.assertEqual((await c.launch())["outcome"], "failed")

    async def test_second_launch_while_one_runs_is_busy(self):
        c = await self.up()
        with mock.patch.object(tvcontrol.contracts, "LAUNCH_WAIT_S", 0.3):
            first = asyncio.create_task(c.launch())
            await settle(0.05)
            self.assertEqual((await c.launch())["detail"], "busy")
            self.assertEqual((await first)["outcome"], "accepted")

    async def test_allowed_while_paused_and_leaves_breaker_counters_alone(self):
        c = await self.up()
        await c.pause(None)
        with mock.patch.object(tvcontrol.contracts, "LAUNCH_WAIT_S", 0.05):
            self.assertEqual((await c.launch())["outcome"], "accepted")
        w = c.status()["watcher"]
        self.assertEqual((w["redirects"], w["failed"]), (0, 0))


class PairingTests(Base):
    async def test_bad_hosts_raise(self):
        c = self.make(paired=False)
        for bad in ("", "not a host", "tv.example.com", "a" * 300, "x.local.evil", "1.2.3", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                await c.start_tv_pair(bad, False)
        for ok in ("192.168.1.2", "fe80::1", "lgwebostv.local"):
            self.assertEqual((await c.start_tv_pair(ok, False))["outcome"], "accepted")
            await c._pair_task

    async def test_second_job_is_busy(self):
        c = self.make(paired=False)
        self.assertEqual((await c.start_tv_pair("192.168.1.2", False))["outcome"], "accepted")
        self.assertEqual(c.status()["tv"]["pairing"]["state"], "waiting_prompt")
        self.assertEqual(await c.start_tv_pair("192.168.1.3", False), {"outcome": "failed", "detail": "busy"})
        await c._pair_task

    async def test_different_certificate_needs_repin_and_saves_nothing(self):
        c = self.make()
        self.tv.cert = "cd" * 32
        await c.start_tv_pair("192.168.1.9", False)
        await c._pair_task
        p = c.status()["tv"]["pairing"]
        self.assertEqual(p["state"], "failed")
        self.assertIn("repin", p["detail"])
        self.assertEqual(Store(self.d).paired(), ("key", CERT))
        await c.start_tv_pair("192.168.1.9", True)
        await c._pair_task
        self.assertEqual(c.status()["tv"]["pairing"]["state"], "done")
        self.assertEqual(Store(self.d).paired(), ("new-key", "cd" * 32))
        self.assertEqual((self.d / "client-key.bak").read_text().strip(), "key")

    async def test_pairing_failure_is_reported_redacted(self):
        c = self.make(paired=False)
        self.tv.open_error = ssap.NotPaired('declined "client-key": "abc123"')
        await c.start_tv_pair("192.168.1.9", False)
        await c._pair_task
        p = c.status()["tv"]["pairing"]
        self.assertEqual(p["state"], "failed")
        self.assertNotIn("abc123", p["detail"])
        self.assertEqual(Store(self.d).paired(), (None, None))

    async def test_pairing_a_fresh_node_starts_the_loop_without_restart(self):
        c = self.make(paired=False)
        await c.start()
        await until(lambda: c.tv_state == contracts.TvState.PAIRING_REQUIRED)
        await c.start_tv_pair("192.168.1.9", False)
        await c._pair_task
        await until(lambda: c.tv_state == contracts.TvState.CONNECTED)
        self.assertEqual(c.status()["tv"]["host"], "192.168.1.9")
        self.assertEqual(c.status()["watcher"]["state"], "watching")


class DiscoveryAndDiagnosticsTests(Base):
    async def test_discover_marks_the_pinned_host(self):
        async def found(timeout=3.0):
            return ["192.168.1.9", "192.168.1.20", "192.168.1.9"]

        c = self.make(ssdp_search=found)
        self.assertEqual(await c.discover_tvs(), [{"host": "192.168.1.9", "pinned": True},
                                                  {"host": "192.168.1.20", "pinned": False}])

    async def test_discover_is_bounded(self):
        async def hang(timeout=3.0):
            await asyncio.sleep(60)

        c = self.make(ssdp_search=hang)
        with mock.patch.object(tvcontrol.asyncio, "wait_for", wraps=asyncio.wait_for) as wf:
            task = asyncio.create_task(c.discover_tvs())
            await asyncio.sleep(0)
            task.cancel()
        self.assertTrue(wf.called)
        self.assertEqual(wf.call_args.args[1], 4.0)

    async def test_status_matches_the_contract_shape(self):
        c = await self.up()
        await self.live(c)
        s = c.status()
        self.assertEqual(set(s), {"tv", "watcher"})
        self.assertEqual(set(s["tv"]), {"state", "host", "paired", "power", "foreground", "age_s",
                                        "last_error", "pairing"})
        self.assertEqual(set(s["watcher"]), {"state", "enabled", "paused", "pause_reason", "paused_until",
                                             "redirects", "ok", "failed", "last_latency_s", "last_failure",
                                             "last_redirect_age_s"})
        self.assertEqual(s["tv"]["foreground"], LIVE)
        self.assertEqual(s["tv"]["age_s"], 0.0)
        self.assertIsNone(s["watcher"]["last_redirect_age_s"])
        self.t += 12.34
        self.assertEqual(c.status()["tv"]["age_s"], 12.3)

    async def test_diagnostics_has_checks_bounded_log_and_counters(self):
        c = await self.up()
        for i in range(300):
            logging.getLogger("vhome.test").warning('line %d client-key: "secret%d"', i, i)
        d = c.diagnostics()
        self.assertEqual(len(d["log"]), 200)
        self.assertNotIn("secret299", "\n".join(d["log"]))
        self.assertTrue(d["checks"]["paired"] and d["checks"]["pinned"])
        self.assertEqual(d["checks"]["host"], "192.168.1.9")
        self.assertEqual(d["checks"]["home_ids"], [HOME])
        self.assertEqual(d["checks"]["vhome_id"], VH)
        self.assertIn("redirects", d["counters"])

    async def test_close_is_quick_and_stops_everything(self):
        c = await self.up()
        await c.pause(10)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await c.close()
        self.assertLess(loop.time() - t0, 1.0)
        self.assertTrue(c._task.done())
        self.assertIsNone(c._client)



class ReviewFixTests(Base):
    async def test_heartbeat_keeps_an_idle_tv_fresh(self):
        c = await self.up()
        c.HEARTBEAT_S = 0.02
        await self.live(c)
        # restart the session so the shorter heartbeat applies
        self.tv.drop()
        await until(lambda: c._client is not None and c.tv_state == contracts.TvState.CONNECTED)
        n = len([u for u, _ in self.tv.requests if u == tvcontrol.POWER_URI])
        self.t += 30.0                       # 30 s with no TV events
        await until(lambda: len([u for u, _ in self.tv.requests if u == tvcontrol.POWER_URI]) > n)
        self.assertLess(c.status()["tv"]["age_s"], 1.0)

    async def test_deferred_timed_pause_resumes_after_ntp_sync(self):
        synced = {"v": False}
        c = self.make(ntp_synced=lambda: synced["v"])
        c.NTP_POLL_S = 0.02
        await c.pause(1)
        c2 = self.make(paired=False, ntp_synced=lambda: synced["v"])
        c2.NTP_POLL_S = 0.02
        c2.wall = lambda: 1_700_000_000.0 + 120     # pause already over once the clock is trusted
        await c2.start()
        await settle(0.1)
        self.assertTrue(c2.status()["watcher"]["paused"])
        synced["v"] = True
        await until(lambda: not c2.status()["watcher"]["paused"])

    async def test_node_asks_for_power_state_and_keeps_a_reissued_key(self):
        self.tv.pair_key = "unused"
        c = await self.up()
        self.assertIn("READ_POWER_STATE", self.tv.permissions)
        self.assertEqual(Store(self.d).paired()[0], "key")

    def test_diagnostics_does_not_call_timedatectl(self):
        calls = []
        c = self.make(ntp_synced=lambda: calls.append(1) or True)
        c.diagnostics()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
