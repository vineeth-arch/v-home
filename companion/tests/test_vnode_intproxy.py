import asyncio
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from vhome_companion.integrations import contracts as ic  # noqa: E402
from vhome_companion.vnode import api, intproxy  # noqa: E402
from vhome_companion.vnode.device import Device  # noqa: E402
from vhome_companion.vnode.phones import Nonces, PairingCodes, PhoneRegistry  # noqa: E402
from test_vnode_api import INFO, Clock, FakeController  # noqa: E402


class FakeService:
    """Stands in for vhome-integrations on a unix socket."""

    def __init__(self, path):
        self.path, self.seen, self.hang, self.status, self.headers = path, [], False, 200, {}
        self.runner, self.release = None, asyncio.Event()

    async def handle(self, request):
        body = await request.read()
        self.seen.append({"method": request.method, "path_qs": request.path_qs, "headers": dict(request.headers),
                          "body": body})
        if self.hang:
            await self.release.wait()
        return web.Response(status=self.status, body=b"ok:%d" % len(body), headers=self.headers,
                            content_type="application/json")

    async def start(self):
        app = web.Application(client_max_size=1024 ** 2)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.UnixSite(self.runner, self.path).start()

    async def stop(self):
        self.release.set()
        await self.runner.cleanup()


class Base(unittest.IsolatedAsyncioTestCase):
    total_s = 8.0
    start_service = True

    async def asyncSetUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.sockdir = tempfile.mkdtemp(dir="/tmp")
        self.sock = os.path.join(self.sockdir, "i.sock")
        self.svc = FakeService(self.sock)
        if self.start_service:
            await self.svc.start()
        clock = Clock()
        phones = PhoneRegistry(self.dir)
        self.nonces = Nonces(clock)
        dev = Device(self.dir, run=None, clock=clock, read=lambda p: (_ for _ in ()).throw(OSError()),
                     run_out=None, glob=lambda pat: [])
        self.mono = Clock()
        self.mono.t = 5000.0
        self.app = api.build_app(FakeController(), phones, PairingCodes(clock), self.nonces, dev, dict(INFO),
                                 int_socket=self.sock)
        self.proxy = self.app[intproxy.PROXY_KEY]
        self.proxy.timeout = intproxy.aiohttp.ClientTimeout(total=self.total_s, sock_connect=0.3)
        self.proxy.clock = self.mono
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.pid, token = phones.add("Test phone")
        self.auth = {"Authorization": "Bearer " + token}

    async def asyncTearDown(self):
        await self.client.close()
        if self.svc.runner is not None:
            await self.svc.stop()
        shutil.rmtree(self.sockdir, ignore_errors=True)

    async def nonce(self):
        r = await self.client.get("/v1/nonce", headers=self.auth)
        return (await r.json())["nonce"]

    async def post_phone(self, path="/v1/inbox/jobs", data=b"hello", headers=None):
        h = {**self.auth, ic.NONCE_HEADER: await self.nonce(), **(headers or {})}
        return await self.client.post(path, data=data, headers=h)


class PhoneRouteTest(Base):
    async def test_forwarded_with_phone_header_and_stripped_client_headers(self):
        r = await self.post_phone(data=b"hi", headers={ic.PHONE_HEADER: "forged", ic.KEY_HEADER: "k" * 20,
                                                       "X-Evil": "1", "Content-Type": "text/plain"})
        self.assertEqual((r.status, await r.read()), (200, b"ok:2"))
        seen = self.svc.seen[0]
        h = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertEqual(h["x-vnode-phone"], self.pid)
        self.assertNotIn("authorization", h)
        self.assertNotIn("x-evil", h)
        self.assertNotIn("x-vnode-nonce", h)
        self.assertEqual(h[ic.KEY_HEADER.lower()], "k" * 20)
        self.assertEqual(seen["body"], b"hi")

    async def test_get_forwards_path_and_query(self):
        r = await self.client.get("/v1/inbox/jobs?limit=7", headers=self.auth)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.svc.seen[0]["path_qs"], "/v1/inbox/jobs?limit=7")
        self.assertEqual(self.svc.seen[0]["method"], "GET")

    async def test_no_phone_token_is_401(self):
        r = await self.client.get("/v1/inbox/jobs")
        self.assertEqual(r.status, 401)
        self.assertEqual(self.svc.seen, [])

    async def test_post_without_nonce_rejected(self):
        r = await self.client.post("/v1/inbox/jobs", data=b"x", headers=self.auth)
        self.assertEqual(r.status, 422)
        self.assertEqual(self.svc.seen, [])

    async def test_nonce_reuse_409(self):
        n = await self.nonce()
        h = {**self.auth, ic.NONCE_HEADER: n}
        self.assertEqual((await self.client.post("/v1/inbox/jobs", data=b"x", headers=h)).status, 200)
        r = await self.client.post("/v1/inbox/jobs", data=b"x", headers=h)
        self.assertEqual((r.status, (await r.json())["error"]), (409, "duplicate"))
        self.assertEqual(len(self.svc.seen), 1)

    async def test_big_body_forwarded_intact(self):
        data = os.urandom(200 * 1024)
        r = await self.post_phone(data=data)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.svc.seen[0]["body"], data)

    async def test_over_cap_by_content_length(self):
        r = await self.post_phone(data=b"a" * (ic.PROXY_MAX_BODY + 1))
        self.assertEqual((r.status, (await r.json())["error"]), (413, "too_large"))
        self.assertEqual(self.svc.seen, [])

    async def test_exactly_cap_ok(self):
        r = await self.post_phone(data=b"a" * ic.PROXY_MAX_BODY)
        self.assertEqual(r.status, 200)

    async def test_over_cap_by_streaming(self):
        async def gen():
            for _ in range(5):
                yield b"a" * (64 * 1024)
            yield b"a" * (ic.PROXY_MAX_BODY - 5 * 64 * 1024 + 1)
        r = await self.post_phone(data=gen())
        self.assertEqual((r.status, (await r.json())["error"]), (413, "too_large"))
        self.assertEqual(self.svc.seen, [])

    async def test_other_routes_keep_4k_limit(self):
        r = await self.client.post("/v1/pause", data=b"a" * 5000, headers=self.auth)
        self.assertEqual(r.status, 413)

    async def test_return_headers_passed_back(self):
        self.svc.status, self.svc.headers = 429, {"Retry-After": "7", "X-Secret": "no"}
        r = await self.client.get("/v1/inbox/jobs", headers=self.auth)
        self.assertEqual((r.status, r.headers["Retry-After"]), (429, "7"))
        self.assertNotIn("X-Secret", r.headers)
        self.assertEqual(r.content_type, "application/json")


class WorkerRouteTest(Base):
    async def test_no_bearer_401_not_forwarded(self):
        for h in ({}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}):
            r = await self.client.post("/v1/int/worker/claim", data=b"{}", headers=h)
            self.assertEqual(r.status, 401)
        self.assertEqual(self.svc.seen, [])

    async def test_bearer_forwarded_no_phone_header(self):
        r = await self.client.post("/v1/int/worker/claim", data=b"{}", headers={"Authorization": "Bearer wtok",
                                                                               ic.PHONE_HEADER: "forged"})
        self.assertEqual(r.status, 200)
        h = {k.lower(): v for k, v in self.svc.seen[0]["headers"].items()}
        self.assertEqual(h["authorization"], "Bearer wtok")
        self.assertNotIn("x-vnode-phone", h)

    async def test_worker_token_cannot_reach_tv_routes(self):
        r = await self.client.get("/v1/status", headers={"Authorization": "Bearer wtok"})
        self.assertEqual(r.status, 401)

    async def test_auth_fail_throttle(self):
        self.svc.status = 401
        h = {"Authorization": "Bearer bad"}
        for _ in range(ic.AUTH_FAIL_LIMIT_PER_MIN):
            self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=h)).status, 401)
        n = len(self.svc.seen)
        r = await self.client.get("/v1/int/worker/unknown", headers=h)
        self.assertEqual((r.status, (await r.json())["error"]), (429, "rate_limited"))
        self.assertEqual(len(self.svc.seen), n)
        self.mono.t += 61
        self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=h)).status, 401)


class WorkerHardeningTest(Base):
    def by_header_ip(self):
        self.proxy._ip = lambda r: r.headers.get("X-Test-Ip", "1.1.1.1")

    async def test_throttle_is_per_ip(self):
        self.by_header_ip()
        self.svc.status = 401
        a = {"Authorization": "Bearer bad", "X-Test-Ip": "10.0.0.1"}
        for _ in range(ic.AUTH_FAIL_LIMIT_PER_MIN):
            await self.client.get("/v1/int/worker/unknown", headers=a)
        self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=a)).status, 429)
        n = len(self.svc.seen)
        b = {"Authorization": "Bearer bad", "X-Test-Ip": "10.0.0.2"}
        self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=b)).status, 401)
        self.assertEqual(len(self.svc.seen), n + 1)

    async def test_recent_2xx_ip_never_throttled(self):
        self.by_header_ip()
        h = {"Authorization": "Bearer w", "X-Test-Ip": "10.0.0.3"}
        self.assertEqual((await self.client.get("/v1/int/worker/ok", headers=h)).status, 200)
        self.svc.status = 401
        for _ in range(ic.AUTH_FAIL_LIMIT_PER_MIN + 3):
            self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=h)).status, 401)
        self.mono.t += 601   # grace over: the same IP is throttled like any other
        for _ in range(ic.AUTH_FAIL_LIMIT_PER_MIN):
            self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=h)).status, 401)
        self.assertEqual((await self.client.get("/v1/int/worker/unknown", headers=h)).status, 429)

    async def test_ip_table_bounded(self):
        self.by_header_ip()
        self.svc.status = 401
        for i in range(intproxy._MAX_IPS + 5):
            await self.client.get("/v1/int/worker/x", headers={"Authorization": "Bearer b", "X-Test-Ip": "ip%d" % i})
        self.assertEqual(len(self.proxy.auth_fails), intproxy._MAX_IPS)

    async def test_worker_body_cap(self):
        h = {"Authorization": "Bearer w"}
        r = await self.client.post("/v1/int/worker/claim", data=b"a" * ic.PROXY_WORKER_MAX_BODY, headers=h)
        self.assertEqual(r.status, 200)
        r = await self.client.post("/v1/int/worker/claim", data=b"a" * (ic.PROXY_WORKER_MAX_BODY + 1), headers=h)
        self.assertEqual((r.status, (await r.json())["error"]), (413, "too_large"))

    async def test_worker_body_cap_streaming(self):
        async def gen():
            yield b"a" * ic.PROXY_WORKER_MAX_BODY
            yield b"a"
        r = await self.client.post("/v1/int/worker/claim", data=gen(), headers={"Authorization": "Bearer w"})
        self.assertEqual(r.status, 413)
        self.assertEqual(self.svc.seen, [])

    async def test_claim_token_forwarded_and_sha_returned(self):
        self.svc.headers = {"X-Payload-Sha256": "ab" * 32}
        r = await self.client.get("/v1/int/worker/jobs/1/payload",
                                  headers={"Authorization": "Bearer w", ic.CLAIM_HEADER: "claim123"})
        h = {k.lower(): v for k, v in self.svc.seen[0]["headers"].items()}
        self.assertEqual(h[ic.CLAIM_HEADER.lower()], "claim123")
        self.assertEqual(r.headers["X-Payload-Sha256"], "ab" * 32)


class InfoTest(Base):
    async def test_info_advertises_int(self):
        body = await (await self.client.get("/v1/info")).json()
        self.assertEqual(body["int"], 1)
        self.assertEqual(body["capabilities"]["inbox"], "supported")
        self.assertNotIn("inbox", INFO["capabilities"])   # shared dict not mutated

    async def test_admin_app_has_no_proxy(self):
        app = api.build_app(FakeController(), None, None, None, None, dict(INFO), admin=True)
        self.assertNotIn(intproxy.PROXY_KEY, app)


class DownServiceTest(Base):
    start_service = False

    async def test_socket_absent_503_fast(self):
        t = time.monotonic()
        r = await self.client.get("/v1/inbox/jobs", headers=self.auth)
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertEqual((r.status, (await r.json())["error"]), (503, "integrations_unavailable"))

    async def test_breaker_opens_and_closes(self):
        for _ in range(ic.BREAKER_FAILS):
            self.assertEqual((await self.client.get("/v1/inbox/jobs", headers=self.auth)).status, 503)
        await self.svc.start()   # service comes back, but the breaker is open
        r = await self.client.get("/v1/inbox/jobs", headers=self.auth)
        self.assertEqual(r.status, 503)
        self.assertEqual(self.svc.seen, [])
        self.mono.t += ic.BREAKER_OPEN_S + 1
        self.assertEqual((await self.client.get("/v1/inbox/jobs", headers=self.auth)).status, 200)
        self.assertEqual(self.proxy.fails, 0)

    async def test_breaker_503_does_not_burn_nonce(self):
        n = await self.nonce()
        for _ in range(ic.BREAKER_FAILS):
            await self.client.get("/v1/inbox/jobs", headers=self.auth)
        r = await self.client.post("/v1/inbox/jobs", data=b"x", headers={**self.auth, ic.NONCE_HEADER: n})
        self.assertEqual(r.status, 503)
        await self.svc.start()
        self.mono.t += ic.BREAKER_OPEN_S + 1
        r = await self.client.post("/v1/inbox/jobs", data=b"x", headers={**self.auth, ic.NONCE_HEADER: n})
        self.assertEqual(r.status, 200)


class DownServiceNonceTest(Base):
    start_service = False

    async def test_missing_socket_does_not_burn_nonce(self):
        n = await self.nonce()
        h = {**self.auth, ic.NONCE_HEADER: n}
        self.assertEqual((await self.client.post("/v1/inbox/jobs", data=b"x", headers=h)).status, 503)
        await self.svc.start()
        self.assertEqual((await self.client.post("/v1/inbox/jobs", data=b"x", headers=h)).status, 200)


class DebugLogTest(Base):
    async def test_by_key_key_never_logged(self):
        key = "SECRETKEY" + "z" * 12
        with self.assertLogs(api.log, "DEBUG") as cm:
            await self.client.get("/v1/inbox/by-key/" + key, headers=self.auth)
        self.assertNotIn(key, "\n".join(cm.output))
        self.assertIn("/v1/inbox/…", "\n".join(cm.output))


class SlotBeforeBodyTest(Base):
    async def test_third_large_upload_503_before_body_read(self):
        gate = asyncio.Event()

        async def slow():
            yield b"a" * 1024
            await gate.wait()
            yield b"b"
        held = []
        for _ in range(ic.PROXY_CONCURRENCY):
            h = {**self.auth, ic.NONCE_HEADER: await self.nonce()}
            held.append(asyncio.create_task(self.client.post("/v1/inbox/jobs", data=slow(), headers=h)))
        await asyncio.sleep(0.2)
        pulled = []

        async def third():
            pulled.append(1)
            yield b"c" * 1024
        t = time.monotonic()
        r = await self.client.post("/v1/inbox/jobs", data=third(),
                                   headers={**self.auth, ic.NONCE_HEADER: await self.nonce()})
        self.assertEqual((r.status, (await r.json())["error"]), (503, "integrations_unavailable"))
        self.assertLess(time.monotonic() - t, 0.3)
        gate.set()
        self.assertEqual([(await x).status for x in held], [200] * ic.PROXY_CONCURRENCY)
        self.assertEqual(len(self.svc.seen), ic.PROXY_CONCURRENCY)


class HungServiceTest(Base):
    total_s = 0.4

    async def test_hung_service_503_and_tv_stays_responsive(self):
        self.svc.hang = True
        slow = asyncio.create_task(self.client.get("/v1/inbox/jobs", headers=self.auth))
        await asyncio.sleep(0.1)
        t = time.monotonic()
        self.assertEqual((await self.client.get("/v1/status", headers=self.auth)).status, 200)
        self.assertLess(time.monotonic() - t, 0.3)
        self.assertFalse(slow.done())
        r = await slow
        self.assertEqual((r.status, (await r.json())["error"]), (503, "integrations_unavailable"))

    async def test_semaphore_full_503_at_once(self):
        self.svc.hang = True
        held = [asyncio.create_task(self.client.get("/v1/inbox/jobs", headers=self.auth))
                for _ in range(ic.PROXY_CONCURRENCY)]
        await asyncio.sleep(0.1)
        t = time.monotonic()
        r = await self.client.get("/v1/inbox/jobs", headers=self.auth)
        self.assertLess(time.monotonic() - t, 0.2)
        self.assertEqual((r.status, (await r.json())["error"]), (503, "integrations_unavailable"))
        await asyncio.gather(*held)


if __name__ == "__main__":
    unittest.main()
