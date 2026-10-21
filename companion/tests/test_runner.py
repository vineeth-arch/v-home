import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import cli, ssap  # noqa: E402
from vhome_companion.watcher import Watcher  # noqa: E402

VH, HOME = "com.designinnsaeit.vhome", "com.webos.app.home"


class FakeClient:
    def __init__(self, launch_error=None):
        self.sub = ssap.Subscription()
        self.launches = []
        self.launch_error = launch_error

    async def subscribe(self, uri, payload=None):
        return self.sub

    async def request(self, uri, payload=None, timeout=None):
        self.launches.append((uri, payload))
        if self.launch_error:
            raise self.launch_error
        return {"returnValue": True}

    def event(self, app):
        self.sub._q.put_nowait({"returnValue": True, "appId": app})


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    async def run_with(self, client, w=None):
        r = cli.Runner(w or Watcher(VH, [HOME]), self.d, "tv")
        task = asyncio.create_task(r.session(client))
        await settle()
        return r, task

    async def stop(self, task):
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_home_triggers_launch_and_state_is_written(self):
        c = FakeClient()
        r, task = await self.run_with(c)
        c.event(HOME)
        await settle()
        self.assertEqual(c.launches, [("ssap://system.launcher/launch", {"id": VH})])
        c.event(HOME)  # duplicate
        c.event(VH)
        await settle()
        self.assertEqual(len(c.launches), 1)
        st = json.loads((self.d / "state.json").read_text())
        self.assertEqual(st["watcher"]["ok"], 1)
        self.assertEqual(oct((self.d / "state.json").stat().st_mode & 0o777), "0o600")
        await self.stop(task)

    async def test_other_apps_never_launch(self):
        c = FakeClient()
        r, task = await self.run_with(c)
        for app in ("netflix", "com.webos.app.hdmi1", ""):
            c.event(app)
        await settle()
        self.assertEqual(c.launches, [])
        await self.stop(task)

    async def test_pause_flag_checked_on_every_event(self):
        c = FakeClient()
        (self.d / "paused").write_text("x")
        r, task = await self.run_with(c)
        c.event(HOME)
        await settle()
        self.assertEqual(c.launches, [])
        (self.d / "paused").unlink()
        c.event("netflix")
        c.event(HOME)
        await settle()
        self.assertEqual(len(c.launches), 1)
        await self.stop(task)

    async def test_launch_error_counts_as_failure_and_breaker_writes_flag(self):
        c = FakeClient(launch_error=ssap.RequestFailed("app not found"))
        r, task = await self.run_with(c)
        for _ in range(3):
            c.event(HOME)
            await settle()
            c.event("netflix")
            await settle()
        self.assertEqual(len(c.launches), 3)
        self.assertTrue((self.d / "paused").exists())
        c.event(HOME)
        await settle()
        self.assertEqual(len(c.launches), 3)  # paused: observe only
        (self.d / "paused").unlink()  # `resume`
        c.event("netflix")
        c.event(HOME)
        await settle()
        self.assertEqual(len(c.launches), 4)
        await self.stop(task)

    async def test_connection_loss_ends_session(self):
        c = FakeClient()
        r, task = await self.run_with(c)
        c.sub._q.put_nowait(ssap.ConnectionLost("gone"))
        with self.assertRaises(ssap.ConnectionLost):
            await task

    async def test_error_reply_on_foreground_subscription_ends_session_for_reconnect(self):
        c = FakeClient()
        r, task = await self.run_with(c)
        c.sub._q.put_nowait(ssap.RequestFailed("401 insufficient permissions"))
        with self.assertRaises(ssap.RequestFailed):
            await task  # Runner.forever catches SsapError, backs off and reconnects

    def test_backoff_is_capped_and_jittered(self):
        self.assertTrue(1.5 <= cli.backoff(0) <= 2.5)
        for n in range(20):
            self.assertLessEqual(cli.backoff(n, rand=lambda: 1.0), 60.0)
        self.assertGreater(cli.backoff(3, rand=lambda: 0.0), 10)

    def test_state_dir_permissions_and_lock(self):
        os.environ["VHOME_COMPANION_DIR"] = str(self.d / "sub")
        self.addCleanup(os.environ.pop, "VHOME_COMPANION_DIR")
        d = cli.state_dir()
        self.assertEqual(d.stat().st_mode & 0o777, 0o700)
        a = cli.acquire_lock(d, "192.168.1.50")
        self.assertIsNotNone(a)
        self.assertIsNone(cli.acquire_lock(d, "192.168.1.50"))  # second watcher refused
        other = cli.acquire_lock(d, "192.168.1.51")  # other TV is independent
        self.assertIsNotNone(other)
        other.close()
        a.close()
        again = cli.acquire_lock(d, "192.168.1.50")
        self.assertIsNotNone(again)
        again.close()


if __name__ == "__main__":
    unittest.main()
