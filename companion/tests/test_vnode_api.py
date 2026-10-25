import asyncio
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from vhome_companion.vnode import api, contracts  # noqa: E402
from vhome_companion.vnode.device import Device  # noqa: E402
from vhome_companion.vnode.phones import Nonces, PairingCodes, PhoneRegistry  # noqa: E402


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class FakeController:
    def __init__(self):
        self.calls = []
        self.launch_gate = None
        self.log = ["started", "registered client-key=SECRETKEY123 ok"]

    def status(self):
        return {"tv": {"state": "connected", "host": "192.168.1.20", "paired": True, "power": "Active",
                       "foreground": "x", "age_s": 1.0, "last_error": None,
                       "pairing": {"state": "idle", "detail": ""}},
                "watcher": {"state": "user_paused", "enabled": True, "paused": True}}

    async def pause(self, minutes):
        self.calls.append(("pause", minutes))
        return contracts.outcome("confirmed")

    async def resume(self):
        self.calls.append(("resume",))
        return contracts.outcome("confirmed")

    async def set_enabled(self, enabled):
        self.calls.append(("set_enabled", enabled))
        return contracts.outcome("confirmed")

    async def launch(self):
        self.calls.append(("launch",))
        if self.launch_gate:
            await self.launch_gate.wait()
        return contracts.outcome("confirmed", "V/HOME in front")

    async def start_tv_pair(self, host, repin):
        self.calls.append(("pair", host, repin))
        if host == "10.0.0.99":
            raise ValueError("bad host")
        return contracts.outcome("accepted")

    async def discover_tvs(self):
        return [{"host": "192.168.1.20", "pinned": True}]

    def diagnostics(self):
        return {"checks": {"tv": "ok", "token": "abc"}, "log": self.log, "counters": {"n": 1}}

    async def close(self):
        pass


INFO = {"api": 1, "node_id": "ab" * 32, "name": "vnode", "version": "0.1.0",
        "capabilities": contracts.capabilities()}


class Base(unittest.IsolatedAsyncioTestCase):
    admin = False

    async def asyncSetUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.clock = Clock()
        self.tv = FakeController()
        self.phones = PhoneRegistry(self.dir)
        self.codes = PairingCodes(self.clock)
        self.nonces = Nonces(self.clock)
        self.runs = []
        self.devclock = Clock()

        async def run(argv):
            self.runs.append(argv)
            return 0, ""
        self.device = Device(self.dir, run=run, clock=self.devclock, read=lambda p: (_ for _ in ()).throw(OSError()),
                             restart_delay=0.05)
        app = api.build_app(self.tv, self.phones, self.codes, self.nonces, self.device, INFO, admin=self.admin)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.pid, self.token = self.phones.add("Test phone")
        self.auth = {"Authorization": "Bearer " + self.token}

    async def asyncTearDown(self):
        await self.client.close()

    async def nonce(self):
        r = await self.client.get("/v1/nonce", headers=self.auth)
        return (await r.json())["nonce"]

    async def post(self, path, body=None, headers=None, nonce=True, **kw):
        body = dict(body or {})
        if nonce:
            body.setdefault("nonce", await self.nonce())
        return await self.client.post(path, json=body, headers=headers or self.auth, **kw)


class AuthTest(Base):
    async def test_missing_bad_and_revoked_token(self):
        self.assertEqual((await self.client.get("/v1/status")).status, 401)
        r = await self.client.get("/v1/status", headers={"Authorization": "Bearer nope"})
        self.assertEqual((r.status, (await r.json())["error"]), (401, "unauthorized"))
        self.assertEqual((await self.client.get("/v1/status", headers=self.auth)).status, 200)
        self.phones.revoke(self.pid)
        self.assertEqual((await self.client.get("/v1/status", headers=self.auth)).status, 401)

    async def test_info_and_pair_need_no_auth(self):
        r = await self.client.get("/v1/info")
        self.assertEqual((await r.json())["node_id"], INFO["node_id"])
        code = self.codes.new()
        r = await self.client.post("/v1/pair", json={"code": code, "name": "Phone 2"})
        body = await r.json()
        self.assertEqual(r.status, 200)
        self.assertTrue(self.phones.check(body["token"]))

    async def test_api_mismatch(self):
        r = await self.client.get("/v1/status", headers={**self.auth, "X-VNode-Api": "2"})
        self.assertEqual((r.status, (await r.json())["error"]), (426, "api_mismatch"))
        r = await self.client.get("/v1/status", headers={**self.auth, "X-VNode-Api": "1"})
        self.assertEqual(r.status, 200)

    async def test_status_shape(self):
        d = await (await self.client.get("/v1/status", headers=self.auth)).json()
        self.assertEqual(d["api"], 1)
        self.assertEqual(d["headline"], "user_paused")
        self.assertEqual(d["node"]["service"], "ok")
        self.assertIn("tv", d)

    async def test_phones_marks_this(self):
        other, _ = self.phones.add("Other")
        d = await (await self.client.get("/v1/phones", headers=self.auth)).json()
        self.assertEqual({p["id"]: p["this"] for p in d["phones"]}, {self.pid: True, other: False})
        self.assertNotIn("token", json.dumps(d))


class PairingTest(Base):
    async def pair(self, code):
        return await self.client.post("/v1/pair", json={"code": code, "name": "P"})

    async def test_single_use(self):
        code = self.codes.new()
        self.assertEqual((await self.pair(code)).status, 200)
        self.assertEqual((await self.pair(code)).status, 429)

    async def test_wrong_tries_burn_then_429(self):
        code = self.codes.new()
        for _ in range(contracts.PAIR_MAX_TRIES):
            self.assertEqual((await self.pair("AAAAAAAA")).status, 401)
        self.assertEqual((await self.pair(code)).status, 429)
        self.assertEqual((await self.pair("AAAAAAAA")).status, 429)

    async def test_expiry(self):
        code = self.codes.new()
        self.clock.t += contracts.PAIR_CODE_TTL_S + 1
        self.assertEqual((await self.pair(code)).status, 429)


class NonceTest(Base):
    async def test_expired_unknown_duplicate(self):
        n = await self.nonce()
        self.clock.t += contracts.NONCE_TTL_S + 1
        r = await self.post("/v1/resume", {"nonce": n}, nonce=False)
        self.assertEqual(r.status, 410)
        r = await self.post("/v1/resume", {"nonce": "never-issued"}, nonce=False)
        self.assertEqual((r.status, (await r.json())["error"]), (410, "expired"))
        n = await self.nonce()
        self.assertEqual((await self.post("/v1/pause", {"nonce": n, "minutes": 30}, nonce=False)).status, 200)
        r = await self.post("/v1/pause", {"nonce": n, "minutes": 30}, nonce=False)
        body = await r.json()
        self.assertEqual((r.status, body["error"]), (409, "duplicate"))
        self.assertEqual(body["previous"]["outcome"], "confirmed")
        self.assertEqual(self.tv.calls, [("pause", 30)])

    async def test_delete_phone_uses_header_nonce(self):
        other, _ = self.phones.add("Other")
        r = await self.client.delete("/v1/phones/" + other, headers={**self.auth, "X-VNode-Nonce": await self.nonce()})
        self.assertEqual((r.status, await r.json()), (200, {"outcome": "confirmed"}))
        r = await self.client.delete("/v1/phones/" + other, headers={**self.auth, "X-VNode-Nonce": await self.nonce()})
        self.assertEqual(r.status, 404)
        self.assertEqual((await self.client.delete("/v1/phones/" + other, headers=self.auth)).status, 422)


class ValidationTest(Base):
    async def test_oversized_body(self):
        r = await self.client.post("/v1/resume", data=b'{"nonce": "' + b"a" * 5000 + b'"}', headers=self.auth)
        self.assertEqual((r.status, (await r.json())["error"]), (413, "too_large"))

    async def test_bad_json(self):
        r = await self.client.post("/v1/resume", data=b"{nope", headers=self.auth)
        self.assertEqual((r.status, (await r.json())["error"]), (400, "bad_json"))

    async def test_invalid_bodies(self):
        cases = [
            ("/v1/resume", {"extra": 1}),
            ("/v1/pause", {"minutes": True}),
            ("/v1/pause", {"minutes": 0}),
            ("/v1/pause", {"minutes": 1441}),
            ("/v1/pause", {"minutes": "5"}),
            ("/v1/watcher", {"enabled": 1}),
            ("/v1/watcher", {}),
            ("/v1/tv/pair", {"host": "not a host"}),
            ("/v1/tv/pair", {"host": "1.2.3.4", "repin": "yes"}),
            ("/v1/device/leds", {"enabled": True, "brightness": 5}),
            ("/v1/device/leds", {"enabled": True, "brightness": 2.0}),
            ("/v1/device/reboot", {}),
            ("/v1/device/reboot", {"confirm": "shutdown"}),
            ("/v1/device/shutdown", {"confirm": "reboot"}),
        ]
        for path, body in cases:
            r = await self.post(path, body)
            self.assertEqual((path, body, r.status), (path, body, 422))
        r = await self.client.post("/v1/resume", data=b"[1]", headers=self.auth)
        self.assertEqual(r.status, 422)
        self.assertEqual(self.tv.calls + self.runs, [])

    async def test_valid_hosts_and_pair_error(self):
        for host in ("192.168.1.5", "fe80::1", "lg-tv.local"):
            self.assertEqual((await self.post("/v1/tv/pair", {"host": host})).status, 200)
        r = await self.post("/v1/tv/pair", {"host": "10.0.0.99"})
        self.assertEqual(r.status, 422)

    async def test_pause_until_resume(self):
        self.assertEqual((await self.post("/v1/pause")).status, 200)
        self.assertEqual(self.tv.calls, [("pause", None)])


class ConcurrencyTest(Base):
    async def test_second_launch_is_busy(self):
        self.tv.launch_gate = asyncio.Event()
        first = asyncio.ensure_future(self.post("/v1/tv/launch"))
        await asyncio.sleep(0.1)
        r = await self.post("/v1/tv/launch")
        self.assertEqual((r.status, (await r.json())["error"]), (409, "busy"))
        self.tv.launch_gate.set()
        self.assertEqual((await first).status, 200)


class DeviceRoutesTest(Base):
    async def test_power_rate_limit_and_whitelist(self):
        r = await self.post("/v1/device/reboot", {"confirm": "reboot"})
        self.assertEqual((r.status, (await r.json())["outcome"]), (200, "accepted"))
        r = await self.post("/v1/device/shutdown", {"confirm": "shutdown"})
        self.assertEqual((r.status, (await r.json())["error"]), (429, "rate_limited"))
        self.assertEqual(self.runs, [["systemctl", "reboot"]])
        self.devclock.t += contracts.POWER_ACTION_GAP_S + 1
        await self.post("/v1/device/shutdown", {"confirm": "shutdown"})
        self.assertEqual(self.runs[-1], ["systemctl", "poweroff"])

    async def test_restart_after_reply(self):
        r = await self.post("/v1/device/restart-service")
        self.assertEqual(r.status, 200)
        self.assertEqual(self.runs, [])
        await asyncio.sleep(0.2)
        self.assertEqual(self.runs, [["systemctl", "restart", "vhome-vnode.service"]])

    async def test_leds_and_device(self):
        r = await self.post("/v1/device/leds", {"enabled": False, "brightness": 4})
        self.assertEqual((await r.json())["outcome"], "accepted")
        self.assertEqual(json.loads((self.dir / contracts.LED_CONFIG_FILE).read_text()),
                         {"enabled": False, "brightness": 4})
        d = await (await self.client.get("/v1/device", headers=self.auth)).json()
        self.assertIsNone(d["temp_c"])
        self.assertIsNone(d["leds"])


class DiagnosticsTest(Base):
    async def test_redacted_and_bounded(self):
        self.tv.log = ["line %d client-key=SECRETKEY123 token: abc999 %s" % (i, "x" * 400) for i in range(1000)]
        r = await self.client.get("/v1/diagnostics", headers=self.auth)
        raw = await r.read()
        self.assertLessEqual(len(raw), 64 * 1024)
        d = json.loads(raw)
        self.assertNotIn("SECRETKEY123", raw.decode())
        self.assertNotIn("abc999", raw.decode())
        self.assertNotIn(self.token, raw.decode())
        self.assertEqual(d["checks"]["token"], "<redacted>")
        self.assertIn("system", d)
        self.assertTrue(d["log"])
        self.assertIn("line 999", d["log"][-1])  # newest lines survive truncation

    async def test_discover(self):
        d = await (await self.client.get("/v1/tv/discover", headers=self.auth)).json()
        self.assertEqual(d, {"tvs": [{"host": "192.168.1.20", "pinned": True}]})


class AdminTest(Base):
    admin = True

    async def test_no_token_and_pairing_code(self):
        r = await self.client.post("/admin/pairing-code")
        d = await r.json()
        self.assertEqual(r.status, 200)
        self.assertEqual((d["node_id"], d["expires_in_s"], len(d["code"])), (INFO["node_id"], 300, 8))
        self.assertEqual(self.codes.redeem(d["code"]), "ok")
        self.assertEqual((await self.client.get("/v1/status")).status, 200)

    async def test_admin_phones(self):
        d = await (await self.client.get("/admin/phones")).json()
        self.assertEqual([p["id"] for p in d["phones"]], [self.pid])
        self.assertEqual((await self.client.delete("/admin/phones/" + self.pid)).status, 200)
        self.assertEqual((await self.client.delete("/admin/phones/" + self.pid)).status, 404)

    async def test_nonce_still_applies_to_v1_posts(self):
        r = await self.client.post("/v1/resume", json={"nonce": "x"})
        self.assertEqual(r.status, 410)


class NoAdminRoutesOnPublicApp(Base):
    async def test_admin_route_absent(self):
        r = await self.client.post("/admin/pairing-code", headers=self.auth)
        self.assertEqual(r.status, 404)


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class TlsTest(unittest.IsolatedAsyncioTestCase):
    async def test_node_id_and_tls_serving(self):
        d = Path(tempfile.mkdtemp())
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "2", "-subj", "/CN=vnode", "-keyout", str(d / "k.pem"),
                        "-out", str(d / "c.pem")], check=True, capture_output=True)
        nid = api.node_id(d / "c.pem")
        self.assertRegex(nid, r"^[0-9a-f]{64}$")
        der = subprocess.run(["openssl", "x509", "-in", str(d / "c.pem"), "-outform", "DER"],
                             check=True, capture_output=True).stdout
        import hashlib
        self.assertEqual(nid, hashlib.sha256(der).hexdigest())
        ctx = api.make_ssl_context(d / "c.pem", d / "k.pem")
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        app = api.build_app(FakeController(), PhoneRegistry(d), PairingCodes(), Nonces(), Device(d), dict(INFO))
        server = TestServer(app)
        await server.start_server(ssl=ctx)
        try:
            cctx = ssl.create_default_context()
            cctx.check_hostname = False
            cctx.verify_mode = ssl.CERT_NONE
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get("https://127.0.0.1:%d/v1/info" % server.port, ssl=cctx) as r:
                    self.assertEqual((await r.json())["api"], 1)
        finally:
            await server.close()


if __name__ == "__main__":
    unittest.main()
