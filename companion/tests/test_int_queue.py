import logging
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vhome_companion.integrations import contracts
from vhome_companion.integrations.contracts import Err, IntError, Status
from vhome_companion.integrations.payloads import PayloadStore
from vhome_companion.integrations.queue import Queue
from vhome_companion.integrations.store import open_db

KEY = "k%015d"
P = contracts.PROJECT_BRAIN


class FakeClock:
    def __init__(self):
        self.w, self.m, self.boot, self.up, self.sync = 1_700_000_000.0, 1000.0, "boot-a", 5000.0, True

    def wall(self): return self.w
    def mono(self): return self.m
    def boot_id(self): return self.boot
    def uptime(self): return self.up
    def synced(self): return self.sync


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.dir = Path(self.t.name)
        self.clock = FakeClock()
        self.payloads = PayloadStore(self.dir / "payloads")
        self.db = self.dir / "q.db"
        self.q = Queue(open_db(self.db), self.payloads, self.clock, rand=lambda: 0.5, disk_free=lambda: 10**12)

    def tearDown(self):
        self.t.cleanup()

    def sub(self, i=0, body=None, kind="text"):
        return self.q.submit("p_1", kind, KEY % i, "lbl", body or ("note %d" % i).encode())[0]

    def claimed(self, i=0):
        self.sub(i)
        return self.q.claim(P, "w")

    def code(self, fn, *a, **kw):
        with self.assertRaises(IntError) as cm:
            fn(*a, **kw)
        return cm.exception.code


class SubmitTests(Base):
    def test_submit_and_views(self):
        row, dup = self.q.submit("p_1", "text", KEY % 1, "my/label!", b"hello")
        self.assertFalse(dup)
        self.assertEqual((row["status"], row["op"], row["project"], row["retry_safe"]),
                         ("queued", "brain.capture_text", P, 1))
        self.assertEqual(row["label"], "mylabel")
        self.assertEqual(self.payloads.read(row["payload_ref"]), b"hello")
        pv = self.q.phone_view(row)
        self.assertEqual(set(pv), {"id", "kind", "label", "status", "created_at", "updated_at", "attempts",
                                   "result_ref", "error_code", "error_msg", "retry_safe"})
        self.assertTrue(pv["created_at"].endswith("Z"))
        self.assertIs(pv["retry_safe"], True)
        wv = self.q.work_view(row)
        self.assertEqual(set(wv), {"id", "op", "kind", "idempotency_key", "label", "created_at", "attempts",
                                   "payload_sha256", "payload_bytes", "claim_token", "status"})
        self.assertEqual(wv["payload_bytes"], 5)

    def test_duplicate_returns_existing_without_write(self):
        a, _ = self.q.submit("p_1", "text", KEY % 1, "", b"same")
        before = self.q.c.total_changes
        files = os.listdir(self.payloads.dir)
        b, dup = self.q.submit("p_1", "text", KEY % 1, "", b"same")
        self.assertTrue(dup)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(self.q.c.total_changes, before)
        self.assertEqual(os.listdir(self.payloads.dir), files)

    def test_key_conflict(self):
        self.q.submit("p_1", "text", KEY % 1, "", b"one")
        self.assertEqual(self.code(self.q.submit, "p_1", "text", KEY % 1, "", b"two"), Err.KEY_CONFLICT)
        self.assertEqual(self.code(self.q.submit, "p_1", "url", KEY % 1, "", b"http://a.b/c"), Err.KEY_CONFLICT)
        self.assertEqual(len(os.listdir(self.payloads.dir)), 1)

    def test_validation_errors(self):
        s = lambda kind="text", key=KEY % 1, body=b"x": self.q.submit("p", kind, key, "", body)
        self.assertEqual(self.code(s, body=b"x" * (contracts.MAX_TEXT + 1)), Err.TOO_LARGE)
        self.assertEqual(self.code(s, body=b"\xff\xfe"), Err.BAD_REQUEST)
        self.assertEqual(self.code(s, body=b"a\x00b"), Err.BAD_REQUEST)
        self.assertEqual(self.code(s, kind="url", body=b"ftp://x"), Err.BAD_REQUEST)
        self.assertEqual(self.code(s, kind="url", body=b"https://a b"), Err.BAD_REQUEST)
        self.assertEqual(self.code(s, kind="exe"), Err.UNSUPPORTED_KIND)
        self.assertEqual(self.code(s, key="short"), Err.BAD_REQUEST)
        self.assertEqual(os.listdir(self.payloads.dir), [])

    def test_queue_full_live_jobs(self):
        with mock.patch.object(contracts, "MAX_LIVE_JOBS", 3):
            for i in range(3):
                self.sub(i)
            with self.assertRaises(IntError) as cm:
                self.sub(9)
        self.assertEqual(cm.exception.code, Err.QUEUE_FULL)
        self.assertEqual(cm.exception.extra["retry_after"], 60)
        self.assertEqual(cm.exception.status, 429)

    def test_queue_full_payload_dir(self):
        with mock.patch.object(contracts, "MAX_PAYLOAD_DIR_BYTES", 10):
            self.sub(0, b"123456")
            self.assertEqual(self.code(self.sub, 1, b"123456"), Err.QUEUE_FULL)

    def test_disk_reserve(self):
        self.q.disk_free = lambda: contracts.DISK_RESERVE_BYTES - 1
        self.assertEqual(self.code(self.sub, 0), Err.DISK_RESERVE)
        self.assertEqual(os.listdir(self.payloads.dir), [])

    def test_max_rows_evicts_oldest_terminal(self):
        with mock.patch.object(contracts, "MAX_ROWS", 3):
            ids = []
            for i in range(3):
                self.clock.w += 1
                ids.append(self.claimed(i))
                self.q.complete(ids[-1]["id"], ids[-1]["claim_token"], "r")
            self.clock.w += 1
            self.sub(7)
            self.assertEqual(self.code(self.q.get, ids[0]["id"]), Err.NOT_FOUND)
            self.q.get(ids[1]["id"])
            self.assertEqual(len(os.listdir(self.payloads.dir)), 3)      # evicted payload removed too
            # now fill with live rows until nothing terminal can be evicted
            self.sub(8)
            self.sub(9)
            self.assertEqual(self.code(self.sub, 10), Err.QUEUE_FULL)

    def test_payload_written_before_commit_and_removed_on_failure(self):
        seen = []
        orig = self.q._insert
        self.q._insert = lambda row: (seen.append(os.listdir(self.payloads.dir)), orig(row))
        self.sub(0)
        self.assertEqual(len(seen[0]), 1)       # payload already on disk when the insert ran

        def boom(row):
            raise sqlite3.OperationalError("disk I/O error")
        self.q._insert = boom
        with self.assertRaises(sqlite3.OperationalError):
            self.sub(1)
        self.assertEqual(len(os.listdir(self.payloads.dir)), 1)      # no orphan from the failed one
        self.assertEqual(self.code(self.q.by_key, P, KEY % 1), Err.NOT_FOUND)

    def test_db_full_maps_to_queue_full(self):
        def full(row):
            raise sqlite3.OperationalError("database or disk is full")
        self.q._insert = full
        self.assertEqual(self.code(self.sub, 0), Err.QUEUE_FULL)
        self.assertEqual(os.listdir(self.payloads.dir), [])

    def test_get_by_key_list_counts(self):
        ids = []
        for i in range(3):
            self.clock.w += 1
            ids.append(self.sub(i)["id"])
        self.assertEqual(self.q.get(ids[0])["id"], ids[0])
        self.assertEqual(self.q.by_key(P, KEY % 2)["id"], ids[2])
        self.assertEqual([r["id"] for r in self.q.list(P, 2)], [ids[2], ids[1]])
        self.assertEqual(len(self.q.list(P, 9999)), 3)
        c = self.q.counts(P)
        self.assertEqual(set(c), {s.value for s in Status})
        self.assertEqual((c["queued"], c["failed"]), (3, 0))
        self.assertEqual(self.code(self.q.get, "nope"), Err.NOT_FOUND)


class CancelRetryTests(Base):
    def test_cancel_only_queued_and_payload_gone(self):
        j = self.sub(0)
        out = self.q.cancel(j["id"])
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(os.listdir(self.payloads.dir), [])
        self.assertIsNone(self.q.get(j["id"])["payload_ref"])
        self.assertEqual(self.code(self.q.cancel, j["id"]), Err.NOT_CANCELLABLE)
        c = self.claimed(1)
        self.assertEqual(self.code(self.q.cancel, c["id"]), Err.NOT_CANCELLABLE)

    def test_retry_rules(self):
        c = self.claimed(0)
        self.assertEqual(self.code(self.q.retry, c["id"]), Err.NOT_RETRYABLE)
        self.q.fail(c["id"], c["claim_token"], "E", "bad", False)
        self.assertEqual(self.q.get(c["id"])["status"], "failed")
        r = self.q.retry(c["id"])
        self.assertEqual((r["status"], r["attempts"], r["claim_token"]), ("queued", 0, None))
        self.assertEqual(self.code(self.q.retry, c["id"]), Err.NOT_RETRYABLE)
        d = self.claimed(1)
        self.q.fail(d["id"], d["claim_token"], "E", "bad", False)
        self.q.c.execute("UPDATE jobs SET retry_safe=0 WHERE id=?", (d["id"],))
        self.assertEqual(self.code(self.q.retry, d["id"]), Err.NOT_RETRYABLE)


class ClaimTests(Base):
    def test_claim_fields_and_order(self):
        a = self.sub(0)
        self.clock.w += 1
        self.sub(1)
        c = self.q.claim(P, "mac")
        self.assertEqual((c["id"], c["status"], c["claimed_by"]), (a["id"], "claimed", "mac"))
        self.assertTrue(c["claim_token"])
        self.assertEqual(c["lease_boot_id"], "boot-a")
        self.assertEqual(c["lease_expires_mono"], 1000.0 + contracts.CLAIM_LEASE_S)
        self.assertNotEqual(self.q.claim(P, "mac")["id"], a["id"])
        self.assertIsNone(self.q.claim(P, "mac"))
        self.assertIsNone(self.q.claim("other", "mac"))

    def test_empty_claim_writes_nothing(self):
        before = self.q.c.total_changes
        self.assertIsNone(self.q.claim(P, "w"))
        self.assertEqual(self.q.c.total_changes, before)
        self.assertFalse(self.q.c.in_transaction)

    def test_backoff_gates_claim(self):
        c = self.claimed(0)
        self.q.fail(c["id"], c["claim_token"], "E", "m", True)
        self.assertIsNone(self.q.claim(P, "w"))
        self.clock.w += 10_000
        self.assertEqual(self.q.claim(P, "w")["id"], c["id"])

    def test_concurrent_claims_each_job_once(self):
        n = 40
        for i in range(n):
            self.sub(i)
        got, errs, barrier = [], [], threading.Barrier(20)

        def worker(k):
            try:
                conn = open_db(self.db)
                q = Queue(conn, PayloadStore(self.dir / "payloads"), self.clock, disk_free=lambda: 10**12)
                barrier.wait()
                while True:
                    j = q.claim(P, "w%d" % k)
                    if j is None:
                        break
                    got.append(j["id"])
                conn.close()
            except Exception as e:      # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=worker, args=(k,)) for k in range(20)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(len(got), n)
        self.assertEqual(len(set(got)), n)


class LifecycleTests(Base):
    def test_start_then_complete_idempotent(self):
        c = self.claimed()
        s = self.q.start(c["id"], c["claim_token"])
        self.assertEqual(s["status"], "processing")
        self.assertEqual(s["lease_expires_mono"], 1000.0 + contracts.PROCESSING_LEASE_S)
        self.assertEqual(self.code(self.q.start, c["id"], c["claim_token"]), Err.STALE_CLAIM)
        d = self.q.complete(c["id"], c["claim_token"], "x" * 500)
        self.assertEqual((d["status"], len(d["result_ref"])), ("completed", contracts.MAX_RESULT_REF))
        self.assertEqual(d["retention_until"], self.clock.w + contracts.RETENTION_DONE_S)
        again = self.q.complete(c["id"], c["claim_token"], "other")
        self.assertEqual(again["result_ref"], d["result_ref"])
        self.assertEqual(self.code(self.q.complete, c["id"], "wrong", "r"), Err.STALE_CLAIM)

    def test_stale_tokens_rejected(self):
        c = self.claimed()
        for fn in (lambda: self.q.start(c["id"], "bad"), lambda: self.q.complete(c["id"], "bad"),
                   lambda: self.q.fail(c["id"], "bad", "E", "m", True), lambda: self.q.start(c["id"], None),
                   lambda: self.q.reconcile(c["id"], "bad", "requeue")):
            self.assertEqual(self.code(fn), Err.STALE_CLAIM)
        self.assertEqual(self.q.get(c["id"])["status"], "claimed")

    def test_lease_expiry_by_mono_then_late_complete(self):
        c = self.claimed()
        self.clock.m += contracts.CLAIM_LEASE_S - 1
        self.assertEqual(self.q.expire_leases(), 0)
        self.clock.m += 2
        self.assertEqual(self.q.expire_leases(), 1)
        u = self.q.unknown(P)
        self.assertEqual([r["id"] for r in u], [c["id"]])
        self.assertEqual(u[0]["claim_token"], c["claim_token"])
        self.assertIsNone(self.q.claim(P, "w"))
        done = self.q.complete(c["id"], c["claim_token"], "n1")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.q.unknown(P), [])

    def test_lease_expiry_by_boot_change(self):
        c = self.claimed()
        self.q.start(c["id"], c["claim_token"])
        self.clock.boot = "boot-b"
        self.clock.m = 1.0      # mono reset after reboot
        self.assertEqual(self.q.expire_leases(), 1)
        self.assertEqual(self.q.get(c["id"])["status"], "unknown")

    def test_claim_expires_leases_first(self):
        c = self.claimed()
        self.clock.m += contracts.CLAIM_LEASE_S + 1
        self.assertIsNone(self.q.claim(P, "w"))
        self.assertEqual(self.q.get(c["id"])["status"], "unknown")

    def test_fail_backoff_and_max_attempts(self):
        j = self.claimed()
        tok = j["claim_token"]
        r = self.q.fail(j["id"], tok, "E1", "token=abc123 oops", True)
        self.assertEqual((r["status"], r["attempts"], r["claim_token"]), ("queued", 1, None))
        self.assertEqual(r["next_attempt_at"], self.clock.w + contracts.backoff_s(1, 0.5))
        self.assertNotIn("abc123", r["error_msg"])
        self.assertEqual(self.code(self.q.fail, j["id"], tok, "E", "m", True), Err.STALE_CLAIM)
        for n in range(2, contracts.MAX_ATTEMPTS + 1):
            self.clock.w += 100_000
            j = self.q.claim(P, "w")
            r = self.q.fail(j["id"], j["claim_token"], "E", "m" * 1000, True)
            self.assertEqual(r["attempts"], n)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(len(r["error_msg"]), contracts.MAX_ERROR_MSG)
        self.assertEqual(r["retention_until"], self.clock.w + contracts.RETENTION_FAILED_S)
        self.assertEqual(self.q.fail(j["id"], j["claim_token"], "E", "m", True)["status"], "failed")  # idempotent

    def test_nonretryable_fails_at_once(self):
        j = self.claimed()
        self.assertEqual(self.q.fail(j["id"], j["claim_token"], "E", "m", False)["status"], "failed")

    def test_reconcile_actions(self):
        a = self.claimed(0)
        r = self.q.reconcile(a["id"], a["claim_token"], "requeue")
        self.assertEqual((r["status"], r["attempts"], r["claim_token"]), ("queued", 0, None))
        b = self.q.claim(P, "w")
        self.q.start(b["id"], b["claim_token"])
        c = self.q.reconcile(b["id"], b["claim_token"], "complete", result_ref="note-1")
        self.assertEqual((c["status"], c["result_ref"]), ("completed", "note-1"))
        d = self.claimed(1)
        self.clock.m += 10_000
        self.q.expire_leases()
        f = self.q.reconcile(d["id"], d["claim_token"], "fail", error_code="X", error_msg="gone")
        self.assertEqual((f["status"], f["error_code"]), ("failed", "X"))
        self.assertEqual(self.code(self.q.reconcile, d["id"], d["claim_token"], "bogus"), Err.BAD_REQUEST)

    def test_reconcile_requeue_with_error_keeps_attempts_and_shows_reason(self):
        a = self.claimed(0)
        r = self.q.reconcile(a["id"], a["claim_token"], "requeue", error_code="brain_access_blocked",
                             error_msg="Brain's login page is blocking VNode. token=sekret")
        self.assertEqual((r["status"], r["attempts"], r["claim_token"]), ("queued", 0, None))
        self.assertEqual(r["error_code"], "brain_access_blocked")
        self.assertIn("login page", r["error_msg"])
        self.assertNotIn("sekret", r["error_msg"])
        b = self.q.claim(P, "w")                     # immediately claimable again, nothing burned
        self.assertEqual((b["id"], b["attempts"]), (a["id"], 0))
        self.assertEqual(self.q.reconcile(b["id"], b["claim_token"], "requeue")["error_code"], "brain_access_blocked")

    def test_illegal_transition_is_a_bug(self):
        j = self.sub(0)
        with self.assertRaises(RuntimeError):
            self.q._set(dict(j), Status.COMPLETED)


class PurgeTests(Base):
    def done(self, i):
        c = self.claimed(i)
        return self.q.complete(c["id"], c["claim_token"], "r")

    def test_waits_for_uptime_and_sync(self):
        j = self.done(0)
        self.clock.w += contracts.RETENTION_DONE_S + 10
        self.clock.up = contracts.RETENTION_MIN_UPTIME_S - 1
        self.assertEqual(self.q.purge(), 0)
        self.clock.up = 99999
        self.clock.sync = False
        self.assertEqual(self.q.purge(), 0)
        self.q.get(j["id"])
        self.clock.sync = True
        self.assertGreaterEqual(self.q.purge(), 1)
        self.assertEqual(self.code(self.q.get, j["id"]), Err.NOT_FOUND)

    def test_row_and_payload_deleted_past_retention(self):
        j = self.done(0)
        self.clock.w += contracts.RETENTION_DONE_S + 1
        self.q.purge()
        self.assertEqual(os.listdir(self.payloads.dir), [])
        self.assertEqual(self.q.counts(P)["completed"], 0)

    def test_completed_payload_dropped_after_grace_row_kept(self):
        j = self.done(0)
        self.q.purge()
        self.assertTrue(os.listdir(self.payloads.dir))
        self.clock.w += contracts.PAYLOAD_GRACE_S + 1
        self.q.purge()
        self.assertEqual(os.listdir(self.payloads.dir), [])
        row = self.q.get(j["id"])
        self.assertIsNone(row["payload_ref"])
        self.assertEqual(row["status"], "completed")

    def test_never_touches_live_rows(self):
        a = self.sub(0)
        b = self.claimed(1)
        self.q.start(b["id"], b["claim_token"])
        self.clock.w += 10 * contracts.RETENTION_FAILED_S
        self.q.purge()
        for j in (a, b):
            self.assertIsNotNone(self.q.get(j["id"])["payload_ref"])
        self.assertEqual(len(os.listdir(self.payloads.dir)), 2)


class TokenTests(Base):
    def test_create_check_revoke_hash_only(self):
        tid, tok = self.q.create_worker_token(P)
        self.assertEqual(self.q.check_worker_token(tok), P)
        self.assertIsNone(self.q.check_worker_token(tok + "x"))
        self.assertIsNone(self.q.check_worker_token(""))
        self.assertIsNone(self.q.check_worker_token(None))
        stored = self.q.c.execute("SELECT * FROM worker_tokens").fetchall()
        self.assertNotIn(tok, repr(stored))
        self.assertEqual(stored[0][2], __import__("hashlib").sha256(tok.encode()).hexdigest())
        listed = self.q.list_worker_tokens()
        self.assertEqual([r["id"] for r in listed], [tid])
        self.assertFalse(any("sha256" in r or tok in repr(r) for r in listed))
        self.assertTrue(self.q.revoke_worker_token(tid))
        self.assertIsNone(self.q.check_worker_token(tok))
        self.assertFalse(self.q.revoke_worker_token(tid))
        self.assertFalse(self.q.revoke_worker_token("nope"))


class LogTests(Base):
    def test_logs_never_carry_payload_key_or_token(self):
        secret = "SUPERSECRETPAYLOADTEXT"
        with self.assertLogs("vhome_companion.integrations.queue", level=logging.DEBUG) as cm:
            j, _ = self.q.submit("p_1", "text", "UNIQUEKEY0123456789", "", secret.encode())
            c = self.q.claim(P, "w")
            self.q.start(c["id"], c["claim_token"])
            self.q.fail(c["id"], c["claim_token"], "E", "boom", True)
        text = "\n".join(cm.output)
        for s in (secret, "UNIQUEKEY0123456789", c["claim_token"]):
            self.assertNotIn(s, text)
        self.assertIn(j["id"], text)


if __name__ == "__main__":
    unittest.main()


class _FlakyCommit:
    """Wraps a sqlite connection; the first COMMIT raises (before reaching sqlite), like a disk error."""

    def __init__(self, conn):
        self._c, self.armed = conn, False

    def execute(self, sql, *a):
        if self.armed and sql == "COMMIT":
            self.armed = False
            raise sqlite3.OperationalError("disk I/O error")
        return self._c.execute(sql, *a)

    def __getattr__(self, name):
        return getattr(self._c, name)


class HardeningTests(Base):
    def done(self, i):
        c = self.claimed(i)
        return self.q.complete(c["id"], c["claim_token"], "r")

    # 1. failed COMMIT must not wedge the shared connection
    def test_failed_commit_rolls_back_and_next_op_works(self):
        flaky = _FlakyCommit(self.q.c)
        self.q.c = flaky
        flaky.armed = True
        with self.assertRaises(sqlite3.OperationalError):
            self.sub(0)
        self.assertFalse(flaky.in_transaction)
        self.assertEqual(self.q.counts(P)["queued"], 0)
        self.sub(1)
        self.assertEqual(self.q.counts(P)["queued"], 1)

    # 2. payload budget counts live rows only; orphans swept
    def test_completed_payloads_do_not_block_submit(self):
        with mock.patch.object(contracts, "MAX_PAYLOAD_DIR_BYTES", 10):
            self.done(0)                         # 6 bytes completed, still on disk in grace window
            self.sub(1, b"123456")
            self.assertEqual(self.code(self.sub, 2, b"123456"), Err.QUEUE_FULL)

    def test_sweep_orphans(self):
        keep = self.sub(0)
        d = self.payloads.dir
        orphan = "0" * 8 + "-0000-0000-0000-" + "0" * 12 + ".bin"
        (d / orphan).write_bytes(b"x")
        old_tmp, new_tmp = d / ".a.tmp", d / ".b.tmp"
        old_tmp.write_bytes(b"x")
        new_tmp.write_bytes(b"x")
        os.utime(old_tmp, (self.clock.w - 600, self.clock.w - 600))
        os.utime(new_tmp, (self.clock.w - 10, self.clock.w - 10))
        outside = self.dir / "secret"
        outside.write_bytes(b"s")
        link = d / ("1" * 8 + "-0000-0000-0000-" + "0" * 12 + ".bin")
        os.symlink(outside, link)
        self.assertEqual(self.q.sweep_orphans(), 2)
        left = set(os.listdir(d))
        self.assertEqual(left, {keep["payload_ref"], ".b.tmp", link.name})
        self.assertTrue(outside.exists())
        self.assertEqual(self.q.sweep_orphans(tmp_age=0), 1)      # startup: no write in flight, any tmp goes

    def test_purge_sweeps_orphans(self):
        (self.payloads.dir / ("2" * 8 + "-0000-0000-0000-" + "0" * 12 + ".bin")).write_bytes(b"x")
        self.assertEqual(self.q.purge(), 1)
        self.assertEqual(os.listdir(self.payloads.dir), [])

    # 3. eviction order
    def test_eviction_prefers_completed_and_spares_unexpired_failed(self):
        with mock.patch.object(contracts, "MAX_ROWS", 3):
            f = self.claimed(0)
            self.q.fail(f["id"], f["claim_token"], "E", "m", False)       # oldest, failed, within retention
            self.clock.w += 1
            self.done(1)
            self.clock.w += 1
            self.sub(2)                                                    # live
            self.clock.w += 1
            self.sub(3)                                                    # evicts the completed one, not failed
            self.assertEqual(self.q.get(f["id"])["status"], "failed")
            self.assertEqual(self.q.counts(P)["completed"], 0)
            self.assertEqual(self.code(self.sub, 4), Err.QUEUE_FULL)       # only unexpired failed + live left
            self.clock.w += contracts.RETENTION_FAILED_S + 10
            self.sub(4)                                                    # failed past retention is evictable
            self.assertEqual(self.code(self.q.get, f["id"]), Err.NOT_FOUND)

    def test_eviction_never_touches_live(self):
        with mock.patch.object(contracts, "MAX_ROWS", 2):
            a, b = self.sub(0), self.sub(1)
            self.assertEqual(self.code(self.sub, 2), Err.QUEUE_FULL)
            self.q.get(a["id"]); self.q.get(b["id"])

    # 4. retention only with a synced clock
    def test_retention_null_when_unsynced_then_survives_first_purge(self):
        self.clock.sync = False
        j = self.done(0)
        self.assertIsNone(self.q.get(j["id"])["retention_until"])
        c = self.claimed(1)
        self.q.fail(c["id"], c["claim_token"], "E", "m", False)
        self.assertIsNone(self.q.get(c["id"])["retention_until"])
        self.clock.w += 10 * contracts.RETENTION_FAILED_S       # NTP step
        self.clock.sync = True
        self.q.purge()
        self.assertEqual(self.q.get(j["id"])["status"], "completed")      # stamped now, not deleted
        self.assertEqual(self.q.get(j["id"])["retention_until"], self.clock.w + contracts.RETENTION_DONE_S)
        self.assertEqual(self.q.get(c["id"])["retention_until"], self.clock.w + contracts.RETENTION_FAILED_S)
        self.clock.w += contracts.RETENTION_DONE_S + 1
        self.q.purge()
        self.assertEqual(self.code(self.q.get, j["id"]), Err.NOT_FOUND)
        self.q.get(c["id"])

    def test_cancel_unsynced_has_no_retention(self):
        self.clock.sync = False
        self.assertIsNone(self.q.cancel(self.sub(0)["id"])["retention_until"])

    # 5. reconcile
    def test_reconcile_fail_and_complete_idempotent(self):
        a = self.claimed(0)
        f1 = self.q.reconcile(a["id"], a["claim_token"], "fail", error_code="X", error_msg="m")
        f2 = self.q.reconcile(a["id"], a["claim_token"], "fail", error_code="Y", error_msg="n")
        self.assertEqual((f1["status"], f2["status"], f2["error_code"]), ("failed", "failed", "X"))
        self.assertEqual(self.code(self.q.reconcile, a["id"], "wrong", "fail"), Err.STALE_CLAIM)
        b = self.claimed(1)
        self.q.reconcile(b["id"], b["claim_token"], "complete", result_ref="r")
        self.assertEqual(self.q.reconcile(b["id"], b["claim_token"], "complete")["status"], "completed")

    def test_requeue_from_unknown_counts_attempts_and_caps(self):
        j = self.claimed(0)
        for n in range(1, contracts.MAX_ATTEMPTS):
            self.clock.m += 10_000
            self.q.expire_leases()
            r = self.q.reconcile(j["id"], j["claim_token"], "requeue")
            self.assertEqual((r["status"], r["attempts"]), ("queued", n))
            j = self.q.claim(P, "w")
        self.clock.m += 10_000
        self.q.expire_leases()
        r = self.q.reconcile(j["id"], j["claim_token"], "requeue")
        self.assertEqual((r["status"], r["error_code"], r["attempts"]), ("failed", "reconcile_limit",
                                                                         contracts.MAX_ATTEMPTS))

    def test_requeue_from_claimed_or_processing_keeps_attempts(self):
        a = self.claimed(0)
        self.assertEqual(self.q.reconcile(a["id"], a["claim_token"], "requeue")["attempts"], 0)
        b = self.q.claim(P, "w")
        self.q.start(b["id"], b["claim_token"])
        self.assertEqual(self.q.reconcile(b["id"], b["claim_token"], "requeue")["attempts"], 0)
