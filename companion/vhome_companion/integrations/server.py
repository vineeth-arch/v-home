"""vhome-integrations service: phone + worker routes on one unix socket, admin routes on another.

Logs carry job id, kind, size, status, route template and http status only. Never payload, key, label or tokens.
"""
import asyncio
import collections
import hmac
import json
import logging
import os
import shutil
import signal
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from . import contracts
from .contracts import Err, IntError, Status
from .payloads import PayloadStore
from .queue import Queue
from .status import StatusHolder
from .store import open_db

log = logging.getLogger("vhome.integrations")
LEASE_EVERY_S, PURGE_EVERY_S = 30.0, 3600.0
_JSON_CODES = {400: Err.BAD_REQUEST, 401: Err.UNAUTHORIZED, 404: Err.NOT_FOUND, 413: Err.TOO_LARGE}


def _iso(t):
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(e):
    headers = {"Retry-After": str(int(e.extra["retry_after"]))} if "retry_after" in e.extra else None
    return web.json_response(e.body(), status=e.status, headers=headers)


@web.middleware
async def _errors(request, handler):
    try:
        resp = await handler(request)
    except IntError as e:
        resp = _err(e)
    except web.HTTPRequestEntityTooLarge:
        resp = _err(IntError(Err.TOO_LARGE, "body too large"))
    except web.HTTPException as e:
        resp = web.json_response({"error": _JSON_CODES.get(e.status, Err.BAD_REQUEST).value, "detail": e.reason},
                                 status=e.status)
    except sqlite3.Error as e:
        log.error("storage error %s", type(e).__name__)
        resp = _err(IntError(Err.UNAVAILABLE, "storage busy"))
    except Exception as e:  # noqa: BLE001 - never leak internals (messages could echo request data)
        log.error("unhandled %s", type(e).__name__, exc_info=True)     # frames only; bodies/headers are never logged
        resp = web.json_response({"error": "internal", "detail": "internal error"}, status=500)
    res = request.match_info.route.resource
    log.info("%s %s job=%s -> %d", request.method, res.canonical if res else "-",
             request.match_info.get("id", "-"), resp.status)
    return resp


def _obj(raw):
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise IntError(Err.BAD_REQUEST, "body must be a JSON object") from None
    if not isinstance(obj, dict):
        raise IntError(Err.BAD_REQUEST, "body must be a JSON object")
    return obj


def _str(obj, name, maxlen, required=True):
    v = obj.get(name)
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v) or len(v) > maxlen:
        raise IntError(Err.BAD_REQUEST, "%s must be a string of at most %d chars" % (name, maxlen))
    return v


class _Service:
    def __init__(self, queue, status, clock):
        self.q, self.status, self.clock = queue, status, clock
        self.hits = collections.defaultdict(collections.deque)   # phone id -> mono times, RAM only

    # ---- helpers ----
    def phone(self, request):
        pid = request.headers.get(contracts.PHONE_HEADER, "")
        if not pid or len(pid) > 64:
            raise IntError(Err.UNAUTHORIZED, "phone identity missing")
        return pid

    def worker_project(self, request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        project = self.q.check_worker_token(token.strip()) if scheme.lower() == "bearer" else None
        if not project:
            raise IntError(Err.UNAUTHORIZED, "worker token required")
        return project

    def job(self, job_id, project):
        row = self.q.get(job_id)
        if row["project"] != project:
            raise IntError(Err.NOT_FOUND, "no such job")
        return row

    def rate_ok(self, phone):
        now, dq = self.clock.mono(), self.hits[phone]
        while dq and now - dq[0] >= 60.0:
            dq.popleft()
        if len(dq) >= contracts.SUBMIT_PER_MIN_PER_PHONE:
            raise IntError(Err.RATE_LIMITED, "too many submissions", retry_after=max(1, int(60 - (now - dq[0]))))
        dq.append(now)

    @staticmethod
    def jobs_json(row, **extra):
        return web.json_response({"job": Queue.phone_view(row), **extra})

    @staticmethod
    def work_json(row):
        return web.json_response({"job": Queue.work_view(row)})

    # ---- phone ----
    async def submit(self, request):
        phone = self.phone(request)
        self.rate_ok(phone)
        body = await request.read()
        row, dup = self.q.submit(phone, request.headers.get(contracts.KIND_HEADER),
                                 request.headers.get(contracts.KEY_HEADER), request.headers.get(contracts.LABEL_HEADER),
                                 body)
        if dup:
            return self.jobs_json(row, duplicate=True)
        return web.json_response({"job": Queue.phone_view(row)}, status=201)

    async def list_jobs(self, request):
        self.phone(request)
        try:
            limit = int(request.query.get("limit", contracts.LIST_MAX))
        except ValueError:
            raise IntError(Err.BAD_REQUEST, "limit must be an integer") from None
        p = contracts.PROJECT_BRAIN
        return web.json_response({"jobs": [Queue.phone_view(r) for r in self.q.list(p, limit)],
                                  "counts": self.q.counts(p)})

    async def get_job(self, request):
        self.phone(request)
        return self.jobs_json(self.job(request.match_info["id"], contracts.PROJECT_BRAIN))

    async def by_key(self, request):
        self.phone(request)
        return self.jobs_json(self.q.by_key(contracts.PROJECT_BRAIN, request.match_info["key"]))

    def own_job(self, request):
        phone = self.phone(request)
        row = self.job(request.match_info["id"], contracts.PROJECT_BRAIN)
        if row["phone_id"] != phone:
            raise IntError(Err.NOT_FOUND, "no such job")
        return row["id"]

    async def cancel(self, request):
        return self.jobs_json(self.q.cancel(self.own_job(request)))

    async def retry(self, request):
        return self.jobs_json(self.q.retry(self.own_job(request)))

    async def brain_status(self, request):
        self.phone(request)
        return web.json_response(self.status.brain_status(self.q.counts(contracts.PROJECT_BRAIN)))

    # ---- worker ----
    async def w_claim(self, request):
        project = self.worker_project(request)
        worker = _str(_obj(await request.read()), "worker", 40)
        row = self.q.claim(project, worker)
        return web.json_response({"job": None if row is None else Queue.work_view(row)})

    async def w_payload(self, request):
        project = self.worker_project(request)
        row = self.job(request.match_info["id"], project)
        if "claim_token" in request.query:      # a query string reaches proxy/access logs
            raise IntError(Err.BAD_REQUEST, "send the claim token in the %s header" % contracts.CLAIM_HEADER)
        token = request.headers.get(contracts.CLAIM_HEADER)
        if not (isinstance(token, str) and row["claim_token"] and hmac.compare_digest(row["claim_token"], token)
                and row["status"] in (Status.CLAIMED.value, Status.PROCESSING.value)):
            raise IntError(Err.STALE_CLAIM, "claim token does not match")
        if not row["payload_ref"]:
            raise IntError(Err.NOT_FOUND, "no payload")
        data = self.q.payloads.read(row["payload_ref"])
        log.info("job %s payload served size=%d", row["id"], len(data))
        return web.Response(body=data, content_type="application/octet-stream",
                            headers={"X-Payload-Sha256": row["payload_sha256"]})

    async def w_start(self, request):
        project = self.worker_project(request)
        self.job(request.match_info["id"], project)
        body = _obj(await request.read())
        return self.work_json(self.q.start(request.match_info["id"], _str(body, "claim_token", 128)))

    async def w_complete(self, request):
        project = self.worker_project(request)
        self.job(request.match_info["id"], project)
        body = _obj(await request.read())
        return self.work_json(self.q.complete(request.match_info["id"], _str(body, "claim_token", 128),
                                              _str(body, "result_ref", contracts.MAX_RESULT_REF, False)))

    async def w_fail(self, request):
        project = self.worker_project(request)
        self.job(request.match_info["id"], project)
        body = _obj(await request.read())
        if not isinstance(body.get("retryable"), bool):
            raise IntError(Err.BAD_REQUEST, "retryable must be a boolean")
        return self.work_json(self.q.fail(request.match_info["id"], _str(body, "claim_token", 128),
                                          _str(body, "error_code", 64), _str(body, "error_msg", 4096),
                                          body["retryable"]))

    async def w_unknown(self, request):
        project = self.worker_project(request)
        return web.json_response({"jobs": [Queue.work_view(r) for r in self.q.unknown(project)]})

    async def w_reconcile(self, request):
        project = self.worker_project(request)
        body = _obj(await request.read())
        job_id = _str(body, "job_id", 64)
        self.job(job_id, project)
        row = self.q.reconcile(job_id, _str(body, "claim_token", 128), _str(body, "action", 16),
                               _str(body, "result_ref", contracts.MAX_RESULT_REF, False),
                               _str(body, "error_code", 64, False), _str(body, "error_msg", 4096, False))
        return self.work_json(row)

    async def w_brain_status(self, request):
        self.worker_project(request)
        raw = await request.read()
        if len(raw) > contracts.MAX_SNAPSHOT:
            raise IntError(Err.TOO_LARGE, "snapshot over %d bytes" % contracts.MAX_SNAPSHOT)
        self.status.set_snapshot(_obj(raw))
        return web.Response(status=204)

    async def w_heartbeat(self, request):
        self.worker_project(request)
        body = _obj(await request.read())
        self.status.heartbeat(_str(body, "worker", 40), _str(body, "version", 40))
        return web.Response(status=204)


def build_app(queue, status, clock) -> web.Application:
    app = web.Application(client_max_size=contracts.PROXY_MAX_BODY, middlewares=[_errors])
    s = _Service(queue, status, clock)
    ph, wk = contracts.PHONE_PREFIX, contracts.WORKER_PREFIX
    app.add_routes([
        web.post(ph + "jobs", s.submit), web.get(ph + "jobs", s.list_jobs),
        web.get(ph + "jobs/{id}", s.get_job), web.get(ph + "by-key/{key}", s.by_key),
        web.post(ph + "jobs/{id}/cancel", s.cancel), web.post(ph + "jobs/{id}/retry", s.retry),
        web.get(ph + "brain-status", s.brain_status),
        web.post(wk + "claim", s.w_claim), web.get(wk + "jobs/{id}/payload", s.w_payload),
        web.post(wk + "jobs/{id}/start", s.w_start), web.post(wk + "jobs/{id}/complete", s.w_complete),
        web.post(wk + "jobs/{id}/fail", s.w_fail), web.get(wk + "unknown", s.w_unknown),
        web.post(wk + "reconcile", s.w_reconcile), web.post(wk + "brain-status", s.w_brain_status),
        web.post(wk + "heartbeat", s.w_heartbeat),
    ])
    return app


# ---- admin (backs the vnode-int CLI) -----------------------------------------------------------
class _ForcedClock:
    """Admin purge: pretend uptime and NTP gates are satisfied; everything else is the real clock."""

    def __init__(self, clock):
        self._c = clock

    def __getattr__(self, name):
        return getattr(self._c, name)

    def uptime(self):
        return float("inf")

    def synced(self):
        return True


class _Admin:
    def __init__(self, queue, status, clock, state_dir):
        self.q, self.status, self.clock, self.state_dir = queue, status, clock, Path(state_dir)

    def rows(self, sql, args=()):
        cur = self.q.c.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    async def stats(self, request):
        by = {s.value: 0 for s in Status}
        for st, n in self.q.c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
            by[st] = n
        db = self.state_dir / contracts.DB_NAME
        st = self.status.brain_status({})
        tokens = [t for t in self.q.list_worker_tokens() if t["revoked_at"] is None]
        return web.json_response({
            "jobs": by, "rows": sum(by.values()), "live": sum(by[s.value] for s in contracts.LIVE),
            "payload_bytes": self.q.payloads.total_bytes(),
            "db_bytes": db.stat().st_size if db.exists() else 0,
            "disk_free_bytes": shutil.disk_usage(str(self.state_dir)).free,
            "uptime_s": int(self.clock.uptime()), "clock_synced": bool(self.clock.synced()),
            "worker_last_seen_age_s": st["worker_last_seen_age_s"], "worker_stale": st["worker_stale"],
            "snapshot_age_s": st["snapshot_age_s"], "worker_tokens_active": len(tokens),
            "housekeeping": self.status.housekeeping()})

    async def jobs(self, request):
        sql, args = "SELECT * FROM jobs", ()
        want = request.query.get("status")
        if want:
            if want not in {s.value for s in Status}:
                raise IntError(Err.BAD_REQUEST, "unknown status")
            sql, args = sql + " WHERE status=?", (want,)
        rows = self.rows(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*args, contracts.MAX_ROWS))
        return web.json_response({"jobs": [self.view(r) for r in rows]})

    @staticmethod
    def view(r):
        return {"id": r["id"], "project": r["project"], "kind": r["kind"], "op": r["op"], "status": r["status"],
                "attempts": r["attempts"], "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"]),
                "next_attempt_at": _iso(r["next_attempt_at"]), "retention_until": _iso(r["retention_until"]),
                "payload_bytes": r["payload_bytes"], "payload_sha256": r["payload_sha256"],
                "has_payload": bool(r["payload_ref"]), "claimed_by": r["claimed_by"], "result_ref": r["result_ref"],
                "error_code": r["error_code"], "error_msg": r["error_msg"], "retry_safe": bool(r["retry_safe"])}

    async def show(self, request):
        return web.json_response({"job": self.view(self.q.get(request.match_info["id"]))})

    @staticmethod
    def _confirmed(body):
        if body.get("yes") is not True:
            raise IntError(Err.BAD_REQUEST, "confirmation required")

    async def recover(self, request):
        body = _obj(await request.read())
        self._confirmed(body)
        action = body.get("action")
        if action not in ("requeue", "fail"):
            raise IntError(Err.BAD_REQUEST, "action must be requeue or fail")
        row = self.q.get(_str(body, "id", 64))
        if row["status"] not in (Status.CLAIMED.value, Status.PROCESSING.value, Status.UNKNOWN.value):
            raise IntError(Err.BAD_REQUEST, "only claimed, processing or unknown jobs can be recovered")
        out = self.q.reconcile(row["id"], row["claim_token"], action, error_code="admin_recovered",
                               error_msg="failed by admin")
        return web.json_response({"job": self.view(out)})

    async def purge(self, request):
        body = _obj(await request.read())
        self._confirmed(body)
        if body.get("terminal") is not True:
            raise IntError(Err.BAD_REQUEST, "terminal must be true")
        real, self.q.clock = self.q.clock, _ForcedClock(self.q.clock)
        try:
            n = self.q.purge()
        finally:
            self.q.clock = real
        return web.json_response({"purged": n})

    async def token_create(self, request):
        tid, token = self.q.create_worker_token(contracts.PROJECT_BRAIN)
        return web.json_response({"id": tid, "project": contracts.PROJECT_BRAIN, "token": token})

    async def token_list(self, request):
        return web.json_response({"tokens": [{**t, "created_at": _iso(t["created_at"]),
                                              "revoked_at": _iso(t["revoked_at"])}
                                             for t in self.q.list_worker_tokens()]})

    async def token_revoke(self, request):
        if not self.q.revoke_worker_token(request.match_info["id"]):
            raise IntError(Err.NOT_FOUND, "no active token with that id")
        return web.json_response({"revoked": request.match_info["id"]})

    async def vacuum(self, request):
        before = (self.state_dir / contracts.DB_NAME).stat().st_size
        self.q.c.execute("VACUUM")
        self.q.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return web.json_response({"before_bytes": before,
                                  "after_bytes": (self.state_dir / contracts.DB_NAME).stat().st_size})


def build_admin_app(queue, status, clock, state_dir) -> web.Application:
    app = web.Application(client_max_size=4096, middlewares=[_errors])
    a = _Admin(queue, status, clock, state_dir)
    app.add_routes([
        web.get("/stats", a.stats), web.get("/jobs", a.jobs), web.get("/jobs/{id}", a.show),
        web.post("/recover", a.recover), web.post("/purge", a.purge), web.post("/worker-token", a.token_create),
        web.get("/worker-tokens", a.token_list), web.post("/worker-token/{id}/revoke", a.token_revoke),
        web.post("/vacuum", a.vacuum),
    ])
    return app


# ---- process -----------------------------------------------------------------------------------
class SysClock:
    def __init__(self):
        self._boot = None

    def wall(self):
        return time.time()

    def mono(self):
        return time.monotonic()

    def boot_id(self):
        if self._boot is None:
            try:
                self._boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            except OSError:
                self._boot = "proc-" + uuid.uuid4().hex     # non-Linux: leases never outlive the process
        return self._boot

    def uptime(self):
        try:
            return float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return time.monotonic()

    def synced(self):
        return os.path.exists("/run/systemd/timesync/synchronized")


async def _periodic(name, every, fn, status=None):
    failing = 0
    while True:
        try:
            fn()
            if failing:
                log.info("%s recovered after %d failure(s)", name, failing)
            failing = 0
            if status:
                status.record(name)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - housekeeping must never die
            if not failing:     # log the first failure of a streak only
                log.error("%s failed: %s", name, type(e).__name__)
            failing += 1
            if status:
                status.record(name, e)
        await asyncio.sleep(every)


async def _listen(runner, path, umask, mode):
    path = Path(path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    path.unlink(missing_ok=True)          # stale socket from a crashed run
    old = os.umask(umask)                 # never world-accessible, not even briefly
    try:
        await web.UnixSite(runner, str(path)).start()
    finally:
        os.umask(old)
    os.chmod(path, mode)


async def serve(state_dir=None, socket_path=None, admin_socket_path=None, *, stop=None, ready=None):
    """Runs until SIGTERM/SIGINT (or `stop` is set, for tests). Returns the exit code."""
    state_dir = Path(state_dir or os.environ.get("VHOME_INT_STATE") or contracts.STATE_DIR)
    socket_path = socket_path or os.environ.get("VHOME_INT_SOCKET") or contracts.SOCKET_PATH
    admin_socket_path = admin_socket_path or os.environ.get("VHOME_INT_ADMIN") or contracts.ADMIN_SOCKET_PATH
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    clock = SysClock()
    conn = open_db(state_dir / contracts.DB_NAME)
    queue = Queue(conn, PayloadStore(state_dir / contracts.PAYLOAD_DIR), clock)
    status = StatusHolder(clock)
    try:
        queue.sweep_orphans(tmp_age=0)      # nothing is in flight yet: any partial file is a crash leftover
    except (OSError, sqlite3.Error) as e:
        log.error("startup orphan sweep failed: %s", type(e).__name__)
    runners = [web.AppRunner(build_app(queue, status, clock), access_log=None),
               web.AppRunner(build_admin_app(queue, status, clock, state_dir), access_log=None)]
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    tasks = []
    try:
        for r in runners:
            await r.setup()
        await _listen(runners[0], socket_path, 0o117, 0o660)
        await _listen(runners[1], admin_socket_path, 0o177, 0o600)
        tasks = [asyncio.create_task(_periodic("expire_leases", LEASE_EVERY_S, queue.expire_leases, status)),
                 asyncio.create_task(_periodic("purge", PURGE_EVERY_S, queue.purge, status))]
        log.info("integrations listening on %s", socket_path)
        if ready is not None:
            ready.set()
        await stop.wait()
    finally:
        log.info("shutting down")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with asyncio.timeout(10):
                for r in runners:
                    await r.cleanup()
        except TimeoutError:
            log.error("shutdown timed out")
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        conn.close()
    return 0
