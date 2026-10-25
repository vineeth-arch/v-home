"""Durable job queue on SQLite. Payload hits disk (fsync) before its row commits; leases use the monotonic clock."""
import hashlib
import hmac
import logging
import random
import secrets
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import contracts
from .contracts import Err, IntError, Status

log = logging.getLogger(__name__)
_LIVE = tuple(s.value for s in contracts.LIVE)
_TERMINAL = tuple(s.value for s in contracts.TERMINAL)


def _marks(vals):
    return ",".join("?" * len(vals))


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Queue:
    def __init__(self, conn, payloads, clock, *, rand=random.random, disk_free=None):
        self.c, self.payloads, self.clock, self.rand = conn, payloads, clock, rand
        self.disk_free = disk_free or (lambda: shutil.disk_usage(str(payloads.dir)).free)

    # ---- plumbing ----
    def _q(self, sql, args=()):
        cur = self.c.execute(sql, args)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    @contextmanager
    def _tx(self):
        self.c.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            try:
                self.c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        try:
            self.c.execute("COMMIT")
        except sqlite3.Error:      # a failed COMMIT can leave the shared connection mid-transaction
            if self.c.in_transaction:
                try:
                    self.c.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise

    def _retention(self, period):
        """Wall time is meaningless before NTP sync: no deadline yet, purge() stamps one once synced."""
        return self.clock.wall() + period if self.clock.synced() else None

    def _row(self, job_id):
        rows = self._q("SELECT * FROM jobs WHERE id=?", (contracts.validate_job_id(job_id),))
        if not rows:
            raise IntError(Err.NOT_FOUND, "no such job")
        return rows[0]

    def _set(self, row, to, **cols):
        """Move row to status `to` (checked against TRANSITIONS). Call inside _tx."""
        if Status(to) not in contracts.TRANSITIONS[Status(row["status"])]:
            raise RuntimeError("illegal transition %s -> %s" % (row["status"], Status(to).value))
        cols.update(status=Status(to).value, updated_at=self.clock.wall())
        self.c.execute("UPDATE jobs SET %s WHERE id=?" % ",".join(k + "=?" for k in cols),
                       (*cols.values(), row["id"]))
        row.update(cols)
        log.info("job %s %s kind=%s", row["id"], row["status"], row["kind"])
        return row

    _CLEAR = dict(claim_token=None, claimed_by=None, lease_boot_id=None, lease_expires_mono=None)

    def _owned(self, job_id, token, states):
        row = self._row(job_id)
        ok = isinstance(token, str) and row["claim_token"] and hmac.compare_digest(row["claim_token"], token)
        if not ok or row["status"] not in states:
            raise IntError(Err.STALE_CLAIM, "claim token does not match")
        return row

    # ---- submit / read ----
    def submit(self, phone_id, kind_str, key, label, body):
        key = contracts.validate_key(key)
        kind = contracts.validate_kind(kind_str)
        body = contracts.validate_payload(kind, body)
        label = contracts.sanitize_label(label)
        digest = hashlib.sha256(kind.value.encode() + b"\0" + body).hexdigest()
        proj = contracts.PROJECT_BRAIN
        dup = self._dup(proj, key, digest)
        if dup:
            return dup, True
        if self.disk_free() < contracts.DISK_RESERVE_BYTES:
            raise IntError(Err.DISK_RESERVE, "storage reserve reached")
        self._make_room(len(body))
        ref, sha = self.payloads.write(body)
        op = contracts.OP_FOR_KIND[kind]
        now = self.clock.wall()
        row = dict(id=str(uuid.uuid4()), project=proj, phone_id=phone_id, op=op, kind=kind.value, label=label,
                   schema_version=contracts.SCHEMA_VERSION, created_at=now, updated_at=now,
                   idempotency_key=key, digest=digest, payload_ref=ref, payload_sha256=sha,
                   payload_bytes=len(body), status=Status.QUEUED.value, attempts=0, next_attempt_at=None,
                   lease_boot_id=None, lease_expires_mono=None, claim_token=None, claimed_by=None,
                   result_ref=None, error_code=None, error_msg=None,
                   retry_safe=int(op in contracts.RETRY_SAFE_OPS), retention_until=None)
        try:
            self._insert(row)
        except sqlite3.IntegrityError:      # lost a race on the same key
            self.payloads.delete(ref)
            dup = self._dup(proj, key, digest)
            if dup:
                return dup, True
            raise
        except sqlite3.OperationalError as e:
            self.payloads.delete(ref)
            if "full" in str(e):
                raise IntError(Err.QUEUE_FULL, "queue storage full", retry_after=60) from None
            raise
        except BaseException:
            self.payloads.delete(ref)
            raise
        log.info("job %s queued kind=%s size=%d", row["id"], kind.value, len(body))
        return row, False

    def _insert(self, row):
        with self._tx():
            self.c.execute("INSERT INTO jobs (%s) VALUES (%s)" % (",".join(row), _marks(row)), tuple(row.values()))

    def _dup(self, proj, key, digest):
        rows = self._q("SELECT * FROM jobs WHERE project=? AND idempotency_key=?", (proj, key))
        if not rows:
            return None
        if not hmac.compare_digest(rows[0]["digest"], digest):
            raise IntError(Err.KEY_CONFLICT, "key already used for a different payload")
        return rows[0]

    def _make_room(self, size):
        full = IntError(Err.QUEUE_FULL, "queue is full", retry_after=60)
        live = self.c.execute("SELECT COUNT(*) FROM jobs WHERE status IN (%s)" % _marks(_LIVE), _LIVE).fetchone()[0]
        used = self.c.execute("SELECT COALESCE(SUM(payload_bytes),0) FROM jobs WHERE payload_ref IS NOT NULL "
                              "AND status IN (%s)" % _marks(_LIVE), _LIVE).fetchone()[0]   # grace-window payloads don't count
        if live >= contracts.MAX_LIVE_JOBS or used + size > contracts.MAX_PAYLOAD_DIR_BYTES:
            raise full
        total = self.c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        excess = total - contracts.MAX_ROWS + 1
        if excess > 0:
            # completed/cancelled first (oldest), failed only once past retention; never live rows
            old = self._q("SELECT id, payload_ref FROM jobs WHERE status IN ('completed','cancelled') "
                          "OR (status='failed' AND retention_until<?) "
                          "ORDER BY status='failed', created_at, rowid LIMIT ?", (self.clock.wall(), excess))
            if len(old) < excess:
                raise full
            with self._tx():
                self.c.execute("DELETE FROM jobs WHERE id IN (%s)" % _marks(old), [r["id"] for r in old])
            for r in old:
                if r["payload_ref"]:
                    self.payloads.delete(r["payload_ref"])

    def get(self, job_id):
        return self._row(job_id)

    def by_key(self, project, key):
        rows = self._q("SELECT * FROM jobs WHERE project=? AND idempotency_key=?", (project, str(key)))
        if not rows:
            raise IntError(Err.NOT_FOUND, "no job for that key")
        return rows[0]

    def list(self, project, limit=contracts.LIST_MAX):
        limit = max(1, min(int(limit), contracts.LIST_MAX))
        return self._q("SELECT * FROM jobs WHERE project=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                       (project, limit))

    def counts(self, project):
        out = {s.value: 0 for s in Status}
        for st, n in self.c.execute("SELECT status, COUNT(*) FROM jobs WHERE project=? GROUP BY status", (project,)):
            out[st] = n
        return out

    # ---- phone actions ----
    def cancel(self, job_id):
        with self._tx():
            row = self._row(job_id)
            if row["status"] != Status.QUEUED.value:
                raise IntError(Err.NOT_CANCELLABLE, "only queued jobs can be cancelled")
            ref = row["payload_ref"]
            self._set(row, Status.CANCELLED, payload_ref=None,
                      retention_until=self._retention(contracts.RETENTION_DONE_S), **self._CLEAR)
        if ref:
            self.payloads.delete(ref)
        return row

    def retry(self, job_id):
        with self._tx():
            row = self._row(job_id)
            if row["status"] != Status.FAILED.value or not row["retry_safe"]:
                raise IntError(Err.NOT_RETRYABLE, "only failed, retry-safe jobs can be retried")
            return self._set(row, Status.QUEUED, attempts=0, next_attempt_at=None, retention_until=None,
                             error_code=None, error_msg=None, **self._CLEAR)

    # ---- worker actions ----
    def claim(self, project, worker):
        self.expire_leases()
        due = ("SELECT * FROM jobs WHERE project=? AND status='queued' AND (next_attempt_at IS NULL "
               "OR next_attempt_at<=?) ORDER BY created_at, rowid LIMIT 1")
        if not self._q(due, (project, self.clock.wall())):      # empty queue: read only, no write
            return None
        with self._tx():
            rows = self._q(due, (project, self.clock.wall()))
            if not rows:
                return None
            return self._set(rows[0], Status.CLAIMED, claim_token=secrets.token_urlsafe(24),
                             claimed_by=str(worker)[:40], lease_boot_id=self.clock.boot_id(),
                             lease_expires_mono=self.clock.mono() + contracts.CLAIM_LEASE_S)

    def start(self, job_id, token):
        with self._tx():
            row = self._owned(job_id, token, {Status.CLAIMED.value})
            return self._set(row, Status.PROCESSING,
                             lease_expires_mono=self.clock.mono() + contracts.PROCESSING_LEASE_S)

    def complete(self, job_id, token, result_ref=None):
        with self._tx():
            row = self._owned(job_id, token, {Status.CLAIMED.value, Status.PROCESSING.value,
                                              Status.UNKNOWN.value, Status.COMPLETED.value})
            if row["status"] == Status.COMPLETED.value:
                return row
            ref = None if result_ref is None else str(result_ref)[:contracts.MAX_RESULT_REF]
            return self._set(row, Status.COMPLETED, result_ref=ref, error_code=None, error_msg=None,
                             lease_expires_mono=None,
                             retention_until=self._retention(contracts.RETENTION_DONE_S))

    def fail(self, job_id, token, code, msg, retryable):
        with self._tx():
            row = self._owned(job_id, token, {Status.CLAIMED.value, Status.PROCESSING.value,
                                              Status.UNKNOWN.value, Status.FAILED.value})
            if row["status"] == Status.FAILED.value:
                return row
            return self._fail(row, code, msg, retryable)

    def _fail(self, row, code, msg, retryable):
        attempts = row["attempts"] + 1
        err = dict(attempts=attempts, error_code=str(code)[:64],
                   error_msg=contracts.redact(msg)[:contracts.MAX_ERROR_MSG])
        if retryable and attempts < contracts.MAX_ATTEMPTS:
            return self._set(row, Status.QUEUED, next_attempt_at=self.clock.wall()
                             + contracts.backoff_s(attempts, self.rand()), **err, **self._CLEAR)
        # token kept on terminal failure so a repeated fail call is idempotent
        return self._set(row, Status.FAILED, lease_expires_mono=None,
                         retention_until=self._retention(contracts.RETENTION_FAILED_S), **err)

    def unknown(self, project):
        return self._q("SELECT * FROM jobs WHERE project=? AND status='unknown' ORDER BY created_at, rowid", (project,))

    def reconcile(self, job_id, token, action, result_ref=None, error_code=None, error_msg=None):
        if action == "complete":
            return self.complete(job_id, token, result_ref)
        if action not in ("requeue", "fail"):
            raise IntError(Err.BAD_REQUEST, "action must be requeue, complete or fail")
        with self._tx():
            row = self._owned(job_id, token, {Status.CLAIMED.value, Status.PROCESSING.value, Status.UNKNOWN.value,
                                              Status.FAILED.value})
            if row["status"] == Status.FAILED.value:       # token is kept on failure: a repeat is a no-op
                if action == "fail":
                    return row
                raise IntError(Err.STALE_CLAIM, "claim token does not match")
            if action == "requeue":
                if row["status"] == Status.UNKNOWN.value:  # the worker may have run it: count it, or claim->crash loops forever
                    attempts = row["attempts"] + 1
                    if attempts >= contracts.MAX_ATTEMPTS:
                        return self._set(row, Status.FAILED, attempts=attempts, lease_expires_mono=None,
                                         error_code="reconcile_limit", error_msg="gave up after repeated unknown outcomes",
                                         retention_until=self._retention(contracts.RETENTION_FAILED_S))
                    return self._set(row, Status.QUEUED, attempts=attempts, next_attempt_at=None, **self._CLEAR)
                return self._set(row, Status.QUEUED, next_attempt_at=None, **self._CLEAR)
            return self._set(row, Status.FAILED, lease_expires_mono=None, error_code=str(error_code or "reconciled")[:64],
                             error_msg=contracts.redact(error_msg or "")[:contracts.MAX_ERROR_MSG],
                             retention_until=self._retention(contracts.RETENTION_FAILED_S))

    # ---- housekeeping ----
    def expire_leases(self):
        boot, mono = self.clock.boot_id(), self.clock.mono()
        where = "status IN ('claimed','processing') AND (lease_boot_id IS NOT ? OR lease_expires_mono<?)"
        if not self.c.execute("SELECT 1 FROM jobs WHERE " + where + " LIMIT 1", (boot, mono)).fetchone():
            return 0
        with self._tx():       # claim_token kept: a late complete from the worker is still accepted
            cur = self.c.execute("UPDATE jobs SET status='unknown', updated_at=? WHERE " + where,
                                 (self.clock.wall(), boot, mono))
        log.info("%d lease(s) expired -> unknown", cur.rowcount)
        return cur.rowcount

    def purge(self):
        """Retention. Waits for uptime and NTP sync because wall time is meaningless before that."""
        if not (self.clock.uptime() > contracts.RETENTION_MIN_UPTIME_S and self.clock.synced()):
            return 0
        now = self.clock.wall()
        with self._tx():
            for status, period in (("failed", contracts.RETENTION_FAILED_S), ("completed", contracts.RETENTION_DONE_S),
                                   ("cancelled", contracts.RETENTION_DONE_S)):    # finished while unsynced: start the clock now
                self.c.execute("UPDATE jobs SET retention_until=? WHERE status=? AND retention_until IS NULL",
                               (now + period, status))
            dead = self._q("SELECT id, payload_ref FROM jobs WHERE status IN (%s) AND retention_until<?"
                           % _marks(_TERMINAL), (*_TERMINAL, now))
            if dead:
                self.c.execute("DELETE FROM jobs WHERE id IN (%s)" % _marks(dead), [r["id"] for r in dead])
            stale = self._q("SELECT id, payload_ref FROM jobs WHERE status='completed' AND payload_ref IS NOT NULL "
                            "AND updated_at<?", (now - contracts.PAYLOAD_GRACE_S,))
            for r in stale:
                self.c.execute("UPDATE jobs SET payload_ref=NULL WHERE id=?", (r["id"],))
        for r in dead + stale:
            if r["payload_ref"]:
                self.payloads.delete(r["payload_ref"])
        return len(dead) + len(stale) + self.sweep_orphans()

    def sweep_orphans(self, tmp_age=300):
        """Delete payload files no row references (crash between file write and row commit). tmp_age=None/0: any
        partial file goes (service start, nothing in flight). Runs on the event-loop thread, so no submit is mid-write."""
        keep = {r[0] for r in self.c.execute("SELECT payload_ref FROM jobs WHERE payload_ref IS NOT NULL")}
        n = self.payloads.sweep(keep, self.clock.wall(), tmp_age)
        if n:
            log.info("swept %d orphan payload file(s)", n)
        return n

    # ---- worker tokens ----
    def create_worker_token(self, project):
        token, tid = secrets.token_urlsafe(32), secrets.token_hex(6)
        with self._tx():
            self.c.execute("INSERT INTO worker_tokens (id, project, sha256, created_at) VALUES (?,?,?,?)",
                           (tid, project, _sha(token), self.clock.wall()))
        return tid, token

    def check_worker_token(self, token):
        if not isinstance(token, str) or not token:
            return None
        digest, found = _sha(token), None
        for proj, h in self.c.execute("SELECT project, sha256 FROM worker_tokens WHERE revoked_at IS NULL"):
            if hmac.compare_digest(h, digest):      # no early exit: constant-time over all rows
                found = proj
        return found

    def list_worker_tokens(self):
        return self._q("SELECT id, project, created_at, revoked_at FROM worker_tokens ORDER BY created_at, rowid")

    def revoke_worker_token(self, token_id):
        with self._tx():
            cur = self.c.execute("UPDATE worker_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                                 (self.clock.wall(), str(token_id)))
        return cur.rowcount > 0

    # ---- views ----
    @staticmethod
    def phone_view(row):
        return {"id": row["id"], "kind": row["kind"], "label": row["label"], "status": row["status"],
                "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"]),
                "attempts": row["attempts"], "result_ref": row["result_ref"], "error_code": row["error_code"],
                "error_msg": row["error_msg"], "retry_safe": bool(row["retry_safe"])}

    @staticmethod
    def work_view(row):
        return {"id": row["id"], "op": row["op"], "kind": row["kind"], "idempotency_key": row["idempotency_key"],
                "label": row["label"], "created_at": _iso(row["created_at"]), "attempts": row["attempts"],
                "payload_sha256": row["payload_sha256"], "payload_bytes": row["payload_bytes"],
                "claim_token": row["claim_token"], "status": row["status"]}
