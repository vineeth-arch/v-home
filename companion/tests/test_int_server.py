import asyncio
import io
import logging
import os
import re
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from vhome_companion.integrations import contracts
from vhome_companion.integrations.__main__ import main
from vhome_companion.integrations.payloads import PayloadStore
from vhome_companion.integrations.queue import Queue
from vhome_companion.integrations.server import build_admin_app, build_app, serve
from vhome_companion.integrations.status import StatusHolder
from vhome_companion.integrations.store import open_db

KEY = "k%015d"
PH = contracts.PHONE_HEADER
P = contracts.PROJECT_BRAIN
CH = contracts.CLAIM_HEADER
W = "/v1/int/worker/"
I = "/v1/inbox/"


class FakeClock:
    def __init__(self):
        self.w, self.m, self.boot, self.up, self.sync = 1_700_000_000.0, 1000.0, "boot-a", 5000.0, True

    def wall(self): return self.w
    def mono(self): return self.m
    def boot_id(self): return self.boot
    def uptime(self): return self.up
    def synced(self): return self.sync


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.dir = Path(self.t.name)
        self.clock = FakeClock()
        self.conn = open_db(self.dir / contracts.DB_NAME)
        self.q = Queue(self.conn, PayloadStore(self.dir / "payloads"), self.clock, rand=lambda: 0.5,
                       disk_free=lambda: 10 ** 12)
        self.status = StatusHolder(self.clock)
        # the test harness ignores access_log=None; serve() really does pass it, so mute the logger here
        access = logging.getLogger("aiohttp.access")
        access.disabled = True
        self.addCleanup(setattr, access, "disabled", False)
        self.client = TestClient(TestServer(build_app(self.q, self.status, self.clock)))
        await self.client.start_server()
        tid, tok = self.q.create_worker_token(P)
        self.tid, self.tok = tid, tok
        self.wh = {"Authorization": "Bearer " + tok}

    async def asyncTearDown(self):
        await self.client.close()
        self.conn.close()
        self.t.cleanup()

    # ---- helpers ----
    def ph(self, kind="text", i=0, label=None, phone="p_1"):
        h = {PH: phone, contracts.KIND_HEADER: kind, contracts.KEY_HEADER: KEY % i}
        if label is not None:
            h[contracts.LABEL_HEADER] = label
        return h

    async def submit(self, i=0, body=b"hello", **kw):
        return await self.client.post(I + "jobs", data=body, headers=self.ph(i=i, **kw))

    async def phone_get(self, path):
        return await self.client.get(path, headers={PH: "p_1"})

    async def claim(self, headers=None):
        r = await self.client.post(W + "claim", json={"worker": "mac"}, headers=headers or self.wh)
        return r.status, (await r.json())["job"]

    async def err(self, resp, status, code):
        self.assertEqual(resp.status, status)
        d = await resp.json()
        self.assertEqual(d["error"], code.value if hasattr(code, "value") else code)
        self.assertIn("detail", d)
        return d


class PhoneRouteTests(Base):
    async def test_submit_get_list_by_key(self):
        r = await self.submit(0, b"hi there", label="my/label!")
        self.assertEqual(r.status, 201)
        job = (await r.json())["job"]
        self.assertEqual((job["kind"], job["status"], job["label"], job["attempts"]), ("text", "queued", "mylabel", 0))
        self.assertNotIn("payload", job)
        again = await self.submit(0, b"hi there", label="my/label!")
        self.assertEqual(again.status, 200)
        d = await again.json()
        self.assertTrue(d["duplicate"])
        self.assertEqual(d["job"]["id"], job["id"])
        g = await (await self.phone_get(I + "jobs/" + job["id"])).json()
        self.assertEqual(g["job"]["id"], job["id"])
        k = await (await self.phone_get(I + "by-key/" + KEY % 0)).json()
        self.assertEqual(k["job"]["id"], job["id"])
        await self.submit(1, b"two")
        lst = await (await self.phone_get(I + "jobs?limit=1")).json()
        self.assertEqual(len(lst["jobs"]), 1)
        self.assertEqual(lst["counts"]["queued"], 2)
        full = await (await self.phone_get(I + "jobs")).json()
        self.assertEqual([j["id"] for j in full["jobs"]][-1], job["id"])    # newest first

    async def test_cancel_and_retry(self):
        job = (await (await self.submit(0)).json())["job"]
        r = await self.client.post(I + "jobs/%s/retry" % job["id"], headers={PH: "p_1"})
        await self.err(r, 409, "not_retryable")
        r = await self.client.post(I + "jobs/%s/cancel" % job["id"], headers={PH: "p_1"})
        self.assertEqual((await r.json())["job"]["status"], "cancelled")
        r = await self.client.post(I + "jobs/%s/cancel" % job["id"], headers={PH: "p_1"})
        await self.err(r, 409, "not_cancellable")
        # failed + retry_safe -> retry works
        await self.submit(1)
        _, wj = await self.claim()
        r = await self.client.post(W + "jobs/%s/fail" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "error_code": "x", "error_msg": "m",
                                         "retryable": False})
        self.assertEqual(r.status, 200)
        r = await self.client.post(I + "jobs/%s/retry" % wj["id"], headers={PH: "p_1"})
        j = (await r.json())["job"]
        self.assertEqual((j["status"], j["attempts"]), ("queued", 0))

    async def test_error_codes(self):
        await self.err(await self.client.post(I + "jobs", data=b"x", headers={**self.ph(), contracts.KEY_HEADER: "short"}),
                       400, "bad_request")
        await self.err(await self.client.post(I + "jobs", data=b"\xff\xfe", headers=self.ph()), 400, "bad_request")
        await self.err(await self.client.post(I + "jobs", data=b"  ", headers=self.ph(i=2)), 400, "bad_request")
        await self.err(await self.client.post(I + "jobs", data=b"x", headers=self.ph(kind="pdf")), 415, "unsupported_kind")
        await self.err(await self.client.post(I + "jobs", data=b"x", headers={
            PH: "p_1", contracts.KEY_HEADER: KEY % 9}), 415, "unsupported_kind")
        await self.err(await self.submit(3, b"x" * (contracts.MAX_TEXT + 1)), 413, "too_large")
        await self.err(await self.submit(4, b"x" * (contracts.PROXY_MAX_BODY + 1)), 413, "too_large")
        await self.submit(5, b"one")
        await self.err(await self.submit(5, b"different"), 409, "key_conflict")
        await self.err(await self.phone_get(I + "jobs/" + "0" * 36), 404, "not_found")
        await self.err(await self.phone_get(I + "jobs/not-a-uuid"), 404, "not_found")
        await self.err(await self.phone_get(I + "by-key/" + KEY % 77), 404, "not_found")
        await self.err(await self.phone_get(I + "jobs?limit=abc"), 400, "bad_request")
        await self.err(await self.phone_get(I + "nope"), 404, "not_found")
        self.q.disk_free = lambda: 0
        await self.err(await self.submit(6), 507, "disk_reserve")

    async def test_queue_full_has_retry_after(self):
        with mock.patch.object(contracts, "MAX_LIVE_JOBS", 1):
            await self.submit(0)
            r = await self.submit(1)
        d = await self.err(r, 429, "queue_full")
        self.assertEqual(r.headers["Retry-After"], "60")
        self.assertEqual(d["retry_after"], 60)

    async def test_rate_limit_31st(self):
        for i in range(30):
            self.assertEqual((await self.submit(i)).status, 201, i)
        r = await self.submit(30)
        await self.err(r, 429, "rate_limited")
        self.assertIn("Retry-After", r.headers)
        self.assertEqual((await self.submit(31, phone="p_2")).status, 201)     # per phone
        self.clock.m += 61
        self.assertEqual((await self.submit(30)).status, 201)

    async def test_phone_routes_need_phone_header(self):
        job = (await (await self.submit(0)).json())["job"]
        for method, path in [("POST", I + "jobs"), ("GET", I + "jobs"), ("GET", I + "jobs/" + job["id"]),
                             ("GET", I + "by-key/" + KEY % 0), ("POST", I + "jobs/%s/cancel" % job["id"]),
                             ("POST", I + "jobs/%s/retry" % job["id"]), ("GET", I + "brain-status")]:
            r = await self.client.request(method, path, data=b"x" if method == "POST" else None)
            await self.err(r, 401, "unauthorized")
        # worker token on a phone route is not a phone identity
        await self.err(await self.client.get(I + "jobs", headers=self.wh), 401, "unauthorized")


class WorkerRouteTests(Base):
    async def test_full_flow(self):
        job = (await (await self.submit(0, b"secret body", label="L")).json())["job"]
        _, wj = await self.claim()
        self.assertEqual((wj["id"], wj["status"], wj["op"], wj["attempts"]), (job["id"], "claimed", "brain.capture_text", 0))
        self.assertEqual(wj["payload_bytes"], 11)
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], headers={**self.wh, CH: wj["claim_token"]})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "application/octet-stream")
        self.assertEqual(r.headers["X-Payload-Sha256"], wj["payload_sha256"])
        self.assertEqual(await r.read(), b"secret body")
        r = await self.client.post(W + "jobs/%s/start" % wj["id"], headers=self.wh, json={"claim_token": wj["claim_token"]})
        self.assertEqual((await r.json())["job"]["status"], "processing")
        r = await self.client.post(W + "jobs/%s/complete" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "result_ref": "note-42"})
        self.assertEqual((await r.json())["job"]["status"], "completed")
        r = await self.client.post(W + "jobs/%s/complete" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"]})
        self.assertEqual(r.status, 200)                                         # repeat is fine
        g = (await (await self.phone_get(I + "jobs/" + job["id"])).json())["job"]
        self.assertEqual((g["status"], g["result_ref"]), ("completed", "note-42"))
        self.assertEqual(await self.claim(), (200, None))

    async def test_claim_empty_writes_nothing(self):
        before = self.conn.total_changes
        self.assertEqual(await self.claim(), (200, None))
        self.assertEqual(self.conn.total_changes, before)

    async def test_auth(self):
        for h in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic " + self.tok},
                  {"Authorization": "Bearer "}, {"Authorization": self.tok}):
            r = await self.client.post(W + "claim", json={"worker": "m"}, headers=h)
            await self.err(r, 401, "unauthorized")
        for method, path in [("GET", W + "unknown"), ("POST", W + "heartbeat"), ("POST", W + "brain-status"),
                             ("GET", W + "jobs/%s/payload" % ("0" * 36)), ("POST", W + "reconcile")]:
            await self.err(await self.client.request(method, path), 401, "unauthorized")
        self.assertTrue(self.q.revoke_worker_token(self.tid))
        r = await self.client.post(W + "claim", json={"worker": "m"}, headers=self.wh)
        await self.err(r, 401, "unauthorized")

    async def test_project_isolation(self):
        job = (await (await self.submit(0)).json())["job"]
        _, tok2 = self.q.create_worker_token("other")
        h2 = {"Authorization": "Bearer " + tok2}
        self.assertEqual(await self.claim(h2), (200, None))                    # cannot see brain jobs
        _, wj = await self.claim()
        h2[CH] = wj["claim_token"]
        for method, path, body in [
                ("GET", W + "jobs/%s/payload" % job["id"], None),
                ("POST", W + "jobs/%s/start" % job["id"], {"claim_token": wj["claim_token"]}),
                ("POST", W + "jobs/%s/complete" % job["id"], {"claim_token": wj["claim_token"]}),
                ("POST", W + "jobs/%s/fail" % job["id"], {"claim_token": wj["claim_token"], "error_code": "e",
                                                         "error_msg": "m", "retryable": True}),
                ("POST", W + "reconcile", {"job_id": job["id"], "claim_token": wj["claim_token"], "action": "requeue"})]:
            r = await self.client.request(method, path, json=body, headers=h2)
            await self.err(r, 404, "not_found")
        r = await self.client.get(W + "unknown", headers=h2)
        self.assertEqual((await r.json())["jobs"], [])
        self.assertEqual((await self.client.get(I + "jobs/" + job["id"], headers={PH: "p"})).status, 200)

    async def test_stale_claim(self):
        await self.submit(0)
        _, wj = await self.claim()
        bad = {"claim_token": "wrong"}
        for path, body in [("start", bad), ("complete", bad),
                           ("fail", {**bad, "error_code": "e", "error_msg": "m", "retryable": True})]:
            r = await self.client.post(W + "jobs/%s/%s" % (wj["id"], path), json=body, headers=self.wh)
            await self.err(r, 409, "stale_claim")
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], headers={**self.wh, CH: "wrong"})
        await self.err(r, 409, "stale_claim")
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], headers=self.wh)
        await self.err(r, 409, "stale_claim")
        r = await self.client.post(W + "reconcile", headers=self.wh,
                                   json={"job_id": wj["id"], "claim_token": "wrong", "action": "requeue"})
        await self.err(r, 409, "stale_claim")

    async def test_bad_bodies(self):
        for body in (b"", b"[]", b"not json", b'{"worker": 5}', b'{"worker": "' + b"x" * 41 + b'"}'):
            r = await self.client.post(W + "claim", data=body, headers=self.wh)
            await self.err(r, 400, "bad_request")
        await self.submit(0)
        _, wj = await self.claim()
        r = await self.client.post(W + "jobs/%s/fail" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "error_code": "e", "error_msg": "m",
                                         "retryable": "yes"})
        await self.err(r, 400, "bad_request")
        r = await self.client.post(W + "reconcile", headers=self.wh,
                                   json={"job_id": wj["id"], "claim_token": wj["claim_token"], "action": "nuke"})
        await self.err(r, 400, "bad_request")

    async def test_fail_retryable_requeues_with_backoff(self):
        await self.submit(0)
        _, wj = await self.claim()
        r = await self.client.post(W + "jobs/%s/fail" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "error_code": "brain_down",
                                         "error_msg": "x", "retryable": True})
        j = (await r.json())["job"]
        self.assertEqual((j["status"], j["attempts"]), ("queued", 1))
        self.assertEqual(await self.claim(), (200, None))                      # backoff not elapsed
        self.clock.w += 600
        self.assertIsNotNone((await self.claim())[1])

    async def test_lease_expiry_unknown_then_late_complete(self):
        job = (await (await self.submit(0)).json())["job"]
        _, wj = await self.claim()
        self.clock.m += contracts.CLAIM_LEASE_S + 1
        self.q.expire_leases()
        g = (await (await self.phone_get(I + "jobs/" + job["id"])).json())["job"]
        self.assertEqual(g["status"], "unknown")
        r = await self.client.get(W + "unknown", headers=self.wh)
        unk = (await r.json())["jobs"]
        self.assertEqual([u["id"] for u in unk], [job["id"]])
        self.assertEqual(unk[0]["claim_token"], wj["claim_token"])
        r = await self.client.post(W + "jobs/%s/complete" % job["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "result_ref": "n1"})
        self.assertEqual(r.status, 200)
        g = (await (await self.phone_get(I + "jobs/" + job["id"])).json())["job"]
        self.assertEqual((g["status"], g["result_ref"]), ("completed", "n1"))

    async def test_reconcile_requeue_and_dry_run_keeps_attempts(self):
        job = (await (await self.submit(0)).json())["job"]
        _, wj = await self.claim()                                              # dry run: claim ...
        r = await self.client.post(W + "reconcile", headers=self.wh,            # ... then requeue
                                   json={"job_id": wj["id"], "claim_token": wj["claim_token"], "action": "requeue"})
        j = (await r.json())["job"]
        self.assertEqual((j["status"], j["attempts"]), ("queued", 0))
        _, wj2 = await self.claim()
        self.assertEqual((wj2["id"], wj2["attempts"]), (job["id"], 0))
        self.clock.m += contracts.CLAIM_LEASE_S + 1
        self.q.expire_leases()
        r = await self.client.post(W + "reconcile", headers=self.wh,
                                   json={"job_id": wj2["id"], "claim_token": wj2["claim_token"], "action": "requeue"})
        self.assertEqual((await r.json())["job"]["status"], "queued")
        _, wj3 = await self.claim()
        r = await self.client.post(W + "reconcile", headers=self.wh,
                                   json={"job_id": wj3["id"], "claim_token": wj3["claim_token"], "action": "fail",
                                         "error_code": "gone", "error_msg": "not in brain"})
        self.assertEqual((await r.json())["job"]["status"], "failed")

    async def test_brain_status_and_worker_staleness(self):
        d = await (await self.phone_get(I + "brain-status")).json()
        self.assertEqual((d["snapshot"], d["snapshot_age_s"], d["stale"], d["worker_last_seen_age_s"], d["worker_stale"]),
                         (None, None, True, None, True))
        self.assertEqual(set(d["queue"]), {s.value for s in contracts.Status})
        r = await self.client.post(W + "brain-status", json={"ok": True, "notes": 12}, headers=self.wh)
        self.assertEqual(r.status, 204)
        r = await self.client.post(W + "heartbeat", json={"worker": "mac", "version": "1.2"}, headers=self.wh)
        self.assertEqual(r.status, 204)
        d = await (await self.phone_get(I + "brain-status")).json()
        self.assertEqual((d["snapshot"], d["snapshot_age_s"], d["stale"], d["worker_stale"]),
                         ({"ok": True, "notes": 12}, 0, False, False))
        self.clock.m += contracts.SNAPSHOT_STALE_S - 1
        self.assertFalse((await (await self.phone_get(I + "brain-status")).json())["stale"])
        self.clock.m += 2
        d = await (await self.phone_get(I + "brain-status")).json()
        self.assertTrue(d["stale"])
        self.assertTrue(d["worker_stale"])
        self.assertEqual(d["worker_last_seen_age_s"], contracts.SNAPSHOT_STALE_S + 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    async def test_brain_status_validation(self):
        r = await self.client.post(W + "brain-status", data=b'{"a":"' + b"x" * 2100 + b'"}', headers=self.wh)
        await self.err(r, 413, "too_large")
        await self.err(await self.client.post(W + "brain-status", data=b"[1]", headers=self.wh), 400, "bad_request")
        self.assertIsNone(self.status.snapshot)
        await self.err(await self.client.post(W + "heartbeat", json={"worker": "m"}, headers=self.wh), 400, "bad_request")


class HardeningRouteTests(Base):
    async def test_cancel_retry_require_owning_phone(self):
        job = (await (await self.submit(0, phone="p_1")).json())["job"]
        other = {PH: "p_2"}
        r = await self.client.post(I + "jobs/%s/cancel" % job["id"], headers=other)
        await self.err(r, 404, "not_found")
        self.assertEqual(self.q.get(job["id"])["status"], "queued")
        r = await self.client.post(I + "jobs/%s/cancel" % job["id"], headers={PH: "p_1"})
        self.assertEqual(r.status, 200)
        await self.submit(1)
        _, wj = await self.claim()
        await self.client.post(W + "jobs/%s/fail" % wj["id"], headers=self.wh,
                               json={"claim_token": wj["claim_token"], "error_code": "e", "error_msg": "m",
                                     "retryable": False})
        r = await self.client.post(I + "jobs/%s/retry" % wj["id"], headers=other)
        await self.err(r, 404, "not_found")
        self.assertEqual(self.q.get(wj["id"])["status"], "failed")
        r = await self.client.post(I + "jobs/%s/retry" % wj["id"], headers={PH: "p_1"})
        self.assertEqual(r.status, 200)

    async def test_payload_token_in_query_is_rejected(self):
        await self.submit(0)
        _, wj = await self.claim()
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], params={"claim_token": wj["claim_token"]},
                                  headers=self.wh)
        await self.err(r, 400, "bad_request")
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], params={"claim_token": "x"},
                                  headers={**self.wh, CH: wj["claim_token"]})
        await self.err(r, 400, "bad_request")
        r = await self.client.get(W + "jobs/%s/payload" % wj["id"], headers={**self.wh, CH: wj["claim_token"]})
        self.assertEqual(r.status, 200)

    async def test_unhandled_error_logs_stack_but_no_request_data(self):
        with mock.patch.object(Queue, "submit", side_effect=ValueError("boom")):
            with self.assertLogs("vhome.integrations", level="ERROR") as cm:
                r = await self.submit(0, b"SECRETBODY")
        self.assertEqual(r.status, 500)
        rec = [x for x in cm.records if "unhandled" in x.getMessage()][0]
        self.assertIsNotNone(rec.exc_info)
        self.assertNotIn("SECRETBODY", "\n".join(cm.output))

    async def test_periodic_logs_recovery_and_records_runs(self):
        from vhome_companion.integrations.server import _periodic
        calls = []

        def fn():
            calls.append(1)
            if len(calls) <= 2:
                raise RuntimeError("x")
            if len(calls) >= 4:
                raise asyncio.CancelledError

        with self.assertLogs("vhome.integrations", level="INFO") as cm:
            with self.assertRaises(asyncio.CancelledError):
                await _periodic("purge", 0, fn, status=self.status)
        msgs = [m.getMessage() for m in cm.records]
        self.assertEqual(sum("purge failed" in m for m in msgs), 1)      # streak logged once
        self.assertEqual(sum("purge recovered" in m for m in msgs), 1)
        h = self.status.housekeeping()["purge"]
        self.assertEqual(h["last_error"], "RuntimeError")
        self.assertIsNotNone(h["last_run_age_s"])
        self.assertIsNotNone(h["last_error_age_s"])

    async def test_admin_stats_housekeeping(self):
        admin = TestClient(TestServer(build_admin_app(self.q, self.status, self.clock, self.dir), access_log=None))
        await admin.start_server()
        try:
            d = await (await admin.get("/stats")).json()
            self.assertEqual(set(d["housekeeping"]), {"expire_leases", "purge"})
            self.assertIsNone(d["housekeeping"]["purge"]["last_run_age_s"])
            self.status.record("purge", RuntimeError("x"))
            self.clock.m += 5
            d = await (await admin.get("/stats")).json()
            self.assertEqual(d["housekeeping"]["purge"]["last_error_age_s"], 5)
            self.assertEqual(d["housekeeping"]["purge"]["last_error"], "RuntimeError")
        finally:
            await admin.close()


class CliHelpTests(unittest.TestCase):
    def test_vacuum_help_warns_about_pause(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit):
            main(["cli", "--help"])
        self.assertIn("pauses the service briefly", " ".join(out.getvalue().split()))


class LoggingTests(Base):
    async def test_logs_never_carry_payload_key_label_or_tokens(self):
        secret, label = "SUPERSECRETPAYLOAD", "SECRETLABEL"
        with self.assertLogs(level="DEBUG") as cm:
            r = await self.submit(0, secret.encode(), label=label)
            job = (await r.json())["job"]
            await self.phone_get(I + "by-key/" + KEY % 0)
            _, wj = await self.claim()
            await self.client.get(W + "jobs/%s/payload" % wj["id"], headers={**self.wh, CH: wj["claim_token"]})
            await self.client.post(W + "jobs/%s/complete" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"], "result_ref": "RESULTREF"})
            await self.client.post(W + "claim", headers={"Authorization": "Bearer BADTOKEN"}, json={})
        text = "\n".join(cm.output)
        self.assertIn(job["id"], text)
        for bad in (secret, label, KEY % 0, self.tok, wj["claim_token"], "BADTOKEN", "RESULTREF"):
            self.assertNotIn(bad, text)


class AdminTests(Base):
    async def test_admin_purge_ignores_uptime_and_sync_gates(self):
        admin = TestClient(TestServer(build_admin_app(self.q, self.status, self.clock, self.dir), access_log=None))
        await admin.start_server()
        try:
            await self.submit(0)
            _, wj = await self.claim()
            await self.client.post(W + "jobs/%s/complete" % wj["id"], headers=self.wh,
                                   json={"claim_token": wj["claim_token"]})
            self.clock.w += contracts.RETENTION_DONE_S + 10
            self.clock.sync = False
            self.assertEqual(self.q.purge(), 0)                                 # normal purge waits for NTP
            r = await admin.post("/purge", json={"terminal": True})
            await self.err(r, 400, "bad_request")                               # no yes
            r = await admin.post("/purge", json={"terminal": True, "yes": True})
            self.assertEqual((await r.json())["purged"], 1)
            self.assertIs(self.q.clock, self.clock)                             # gate override is restored
            self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        finally:
            await admin.close()


class ServeTests(unittest.IsolatedAsyncioTestCase):
    async def test_serve_modes_and_cli_end_to_end(self):
        tmp = Path(tempfile.mkdtemp(dir="/tmp"))
        sock, asock = tmp / "i.sock", tmp / "a.sock"
        sock.write_text("stale")                                                # stale file is unlinked
        stop, ready = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(serve(tmp / "state", sock, asock, stop=stop, ready=ready))
        try:
            await asyncio.wait_for(ready.wait(), 10)
            self.assertEqual(stat.S_IMODE(sock.stat().st_mode), 0o660)
            self.assertEqual(stat.S_IMODE(asock.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((tmp / "state").stat().st_mode), 0o700)

            def cli(*args):
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.dict(os.environ, {"VHOME_INT_ADMIN": str(asock)}):
                    code = main(["cli", *args], out=out, err=err)
                return code, out.getvalue(), err.getvalue()

            async def run(*args):
                return await asyncio.to_thread(cli, *args)

            code, out, _ = await run("stats")
            self.assertEqual(code, 0)
            self.assertIn("jobs: 0 rows", out)
            code, out, _ = await run("worker-token", "create")
            self.assertEqual(code, 0)
            tid = re.search(r"id: (\w+)", out).group(1)
            token = re.search(r"store it now\): (\S+)", out).group(1)
            code, out, _ = await run("worker-token", "list")
            self.assertIn(tid, out)
            self.assertIn("active", out)
            self.assertNotIn(token, out)                                        # only the hash is stored

            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(sock))) as s:
                wh = {"Authorization": "Bearer " + token}
                r = await s.post("http://x" + W + "heartbeat", json={"worker": "m", "version": "1"}, headers=wh)
                self.assertEqual(r.status, 204)
                r = await s.post("http://x" + I + "jobs", data=b"via socket",
                                 headers={PH: "p_1", contracts.KIND_HEADER: "text", contracts.KEY_HEADER: KEY % 1})
                self.assertEqual(r.status, 201)
                job = (await r.json())["job"]
                code, out, _ = await run("jobs", "--status", "queued")
                self.assertIn(job["id"], out)
                code, out, _ = await run("show", job["id"])
                self.assertIn("queued", out)
                self.assertNotIn("via socket", out)
                code, out, err = await run("recover", "--requeue", job["id"])   # no --yes
                self.assertEqual(code, 2)
                self.assertIn("--yes", err)
                code, _, err = await run("recover", "--fail", job["id"], "--yes")   # queued: not recoverable
                self.assertEqual(code, 1)
                code, _, _ = await run("purge", "--terminal")
                self.assertEqual(code, 2)
                code, out, _ = await run("purge", "--terminal", "--yes")
                self.assertEqual(code, 0)
                code, out, _ = await run("vacuum")
                self.assertEqual(code, 0)
                code, _, _ = await run("worker-token", "revoke", tid)
                self.assertEqual(code, 0)
                code, _, err = await run("worker-token", "revoke", tid)
                self.assertEqual(code, 1)
                r = await s.post("http://x" + W + "heartbeat", json={"worker": "m", "version": "1"}, headers=wh)
                self.assertEqual(r.status, 401)
            code, out, _ = await run("stats")
            self.assertIn("jobs: 1 rows, 1 live", out)
            with self.assertRaises(SystemExit) as cm:
                await asyncio.to_thread(main, ["cli", "bogus"], io.StringIO(), io.StringIO())
            self.assertEqual(cm.exception.code, 2)
        finally:
            stop.set()
            self.assertEqual(await asyncio.wait_for(task, 15), 0)
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_cli_unreachable_socket_exit_1(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"VHOME_INT_ADMIN": "/tmp/definitely-not-here.sock"}):
            code = await asyncio.to_thread(main, ["cli", "stats"], out, err)
        self.assertEqual(code, 1)
        self.assertIn("cannot reach", err.getvalue())


if __name__ == "__main__":
    unittest.main()
