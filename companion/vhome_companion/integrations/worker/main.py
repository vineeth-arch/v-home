"""VNode Mac worker: polls the Pi (outbound TLS only), delivers Brain capture jobs locally.

Dry run by default; --live delivers. Stdlib only (runs on the macOS system python3)."""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import socket
import stat
import sys
import tempfile
import time

from .. import contracts
from ..contracts import Kind
from .brain_client import BrainClient, BrainError, parse_url, stops_pass
from .ledger import Ledger
from .pi_client import PayloadMismatch, PinMismatch, PiClient, PiError

VERSION = "0.1.0"
log = logging.getLogger("vnode-worker")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ConfigError(Exception):
    pass


class Delivery(Exception):
    def __init__(self, code: str, retryable: bool):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class Config:
    def __init__(self, env: dict):
        g = lambda k, d="": (env.get(k) or d).strip()
        self.host, self.port = g("VNODE_HOST", "vnode.local"), int(g("VNODE_PORT", "8443") or 8443)
        self.node_id, self.pi_token = g("VNODE_NODE_ID").lower(), g("VNODE_WORKER_TOKEN")
        self.brain_url, self.brain_token = g("BRAIN_URL", "http://127.0.0.1:8000"), g("BRAIN_VNODE_TOKEN")
        self.inbox = g("BRAIN_INBOX_PATH")
        missing = [k for k, v in (("VNODE_NODE_ID", self.node_id), ("VNODE_WORKER_TOKEN", self.pi_token),
                                  ("BRAIN_VNODE_TOKEN", self.brain_token), ("BRAIN_INBOX_PATH", self.inbox)) if not v]
        if missing:
            raise ConfigError("worker.env is missing: " + ", ".join(missing))
        if not re.fullmatch(r"[0-9a-f]{64}", self.node_id):
            raise ConfigError("VNODE_NODE_ID must be 64 hex chars (sha256 of the node cert DER)")
        if not os.path.isabs(self.inbox):
            raise ConfigError("BRAIN_INBOX_PATH must be an absolute path")
        try:
            parse_url(self.brain_url)
        except ValueError as e:
            raise ConfigError(str(e)) from None


def load_config(path: str | None = None) -> Config:
    path = os.path.expanduser(path or contracts.WORKER_ENV_FILE)
    try:
        st = os.stat(path)
    except OSError:
        raise ConfigError("cannot read %s (run install-worker.sh to create it)" % path) from None
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise ConfigError("%s must be owned by you and mode 0600 (chmod 600 it)" % path)
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return Config(env)


# ---- delivery ------------------------------------------------------------------------------
def doc_name(job: dict) -> str:
    key, created = str(job.get("idempotency_key", "")), str(job.get("created_at", ""))[:10]
    contracts.validate_key(key)
    if not _DATE.match(created):
        raise Delivery("bad_job", False)
    return "%s vnode-%s.%s" % (created, key[:16], Kind(job["kind"]).value)


def _sha_file(p: str) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def doc_target(inbox: str, job: dict) -> str:
    base = os.path.realpath(inbox)
    target = os.path.realpath(os.path.join(base, doc_name(job)))
    if os.path.dirname(target) != base:        # also catches symlinked or odd names
        raise Delivery("bad_job", False)
    return target


def deliver_doc(inbox: str, job: dict, payload: bytes) -> str:
    try:
        return _deliver_doc(inbox, job, payload)
    except OSError:                            # mkstemp / stat / realpath / read / link: all retryable
        raise Delivery("write_failed", True) from None


def _deliver_doc(inbox: str, job: dict, payload: bytes) -> str:
    target = doc_target(inbox, job)
    sha = hashlib.sha256(payload).hexdigest()
    if os.path.exists(target):
        if _sha_file(target) == sha:
            return os.path.basename(target)
        raise Delivery("name_conflict", False)
    fd, tmp = tempfile.mkstemp(prefix=".vnode-", suffix=".part", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, target)               # fails if target exists: never overwrites
        except FileExistsError:
            if _sha_file(target) != sha:
                raise Delivery("name_conflict", False) from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return os.path.basename(target)


def deliver(cfg: Config, brain: BrainClient, job: dict, payload: bytes) -> str:
    kind = Kind(job["kind"])
    if kind in (Kind.MD, Kind.TXT):
        return deliver_doc(cfg.inbox, job, payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise Delivery("bad_payload", False) from None
    key = contracts.validate_key(job.get("idempotency_key"))
    if kind is Kind.TEXT:
        return brain.capture_text(text, key)
    return brain.capture_url(text.strip(), contracts.sanitize_label(job.get("label")) or None, key)


# ---- one pass ------------------------------------------------------------------------------
def _safe_fail(pi, job, code, msg, retryable):
    try:
        pi.fail(job["id"], job["claim_token"], code, msg, retryable)
    except PiError as e:
        log.warning("job %s: fail not recorded (%s)", job["id"], e)


def process(cfg, pi, brain, ledger, job) -> bool:
    """Handle one claimed job. Returns True when the pass should stop (Brain sick / Pi unreachable)."""
    jid = job.get("id")
    try:
        return _process(cfg, pi, brain, ledger, job)
    except PinMismatch:
        raise
    except PiError as e:
        log.warning("job %s: pi error %s", jid, e)
        return e.status == 0
    except Exception:
        log.error("job %s: unexpected error", jid, exc_info=True)
        _safe_fail(pi, job, "worker_error", "unexpected worker error", True)
        return False


def _process(cfg, pi, brain, ledger, job) -> bool:
    jid, ctok = job["id"], job["claim_token"]
    try:
        contracts.validate_job_id(jid)
        kind = Kind(job["kind"])
    except (contracts.IntError, ValueError, KeyError):
        _safe_fail(pi, job, "bad_job", "unsupported job", False)
        return False
    done = ledger.get(jid)
    if done and done["state"] == "delivered":       # delivered earlier, complete never landed
        pi.complete(jid, ctok, done["result_ref"])
        log.info("job %s kind=%s already delivered; completed", jid, kind.value)
        return False
    try:
        payload = pi.payload(jid, ctok, job.get("payload_sha256", ""))
    except PayloadMismatch:
        _safe_fail(pi, job, "payload_sha_mismatch", "payload failed integrity check", False)
        return False
    pi.start(jid, ctok)
    ledger.intent(jid, job.get("idempotency_key"), kind.value, hashlib.sha256(payload).hexdigest())
    try:
        ref = deliver(cfg, brain, job, payload)
    except BrainError as e:
        _safe_fail(pi, job, "brain_" + (e.code or "error"), "brain rejected the capture", e.retryable)
        return stops_pass(e)
    except Delivery as e:
        _safe_fail(pi, job, e.code, e.code, e.retryable)
        return False
    try:
        ledger.delivered(jid, ref)
    except Exception:       # Brain/inbox already has it; complete anyway (text/url dedupe by key)
        log.error("job %s: ledger write failed after delivery", jid, exc_info=True)
    pi.complete(jid, ctok, ref)
    log.info("job %s kind=%s delivered (%d bytes)", jid, kind.value, len(payload))
    return False


def reconcile_unknown(cfg, pi, ledger, live=True):
    """Settle jobs the Pi lost track of. Dry run only logs what it would do (never writes to the Pi)."""
    def act(jid, ctok, action, **kw):
        if live:
            pi.reconcile(jid, ctok, action, **kw)
        else:
            log.info("dry-run: would reconcile job %s as %s", jid, action)

    for job in pi.unknown():
        jid, ctok = job.get("id"), job.get("claim_token")
        try:
            done = ledger.get(jid)
            if done and done["state"] == "delivered":
                act(jid, ctok, "complete", result_ref=done["result_ref"])
                continue
            if job.get("kind") in ("md", "txt"):
                target = doc_target(cfg.inbox, job)
                if os.path.isfile(target) and _sha_file(target) == job.get("payload_sha256"):
                    act(jid, ctok, "complete", result_ref=os.path.basename(target))
                    continue
            # text/url: Brain dedupes by X-Capture-Key, so a requeue cannot double-capture.
            # ponytail: doc with ledger intent only AND file already consumed by Brain's watcher re-delivers once.
            act(jid, ctok, "requeue")
        except (Delivery, contracts.IntError):
            act(jid, ctok, "fail", error_code="bad_job", error_msg="cannot reconcile")
        except PiError as e:
            if e.status == 0:
                raise
            log.warning("reconcile %s: %s", jid, e)


def snapshot(brain, ledger, live=False) -> dict:
    """Flat shape the Android screen reads. Brain down -> reachable false, counts null."""
    snap = {"reachable": True, "heartbeat": None, "pending": None, "processed_today": None, "needs_review": None,
            "failed": None, "last_note_id": ledger.last_delivered_ref(),
            "mode": "live" if live else "dry_run", "auth_error": False,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    carried = bool(getattr(brain, "auth_error", False))     # 401/403 seen since the last status call
    try:
        st = brain.status()
        counts = st.get("counts") if isinstance(st.get("counts"), dict) else {}
        snap["heartbeat"] = st.get("heartbeat")
        for k in ("pending", "processed_today", "needs_review", "failed"):
            snap[k] = counts.get(k)
    except BrainError:
        snap["reachable"] = False
    snap["auth_error"] = carried or bool(getattr(brain, "auth_error", False))
    return snap


def run_once(cfg, pi, brain, ledger, live, sleep=time.sleep):
    pi.heartbeat(socket.gethostname()[:30], VERSION, "live" if live else "dry_run")
    snap = snapshot(brain, ledger, live)
    pi.brain_status(snap)
    reconcile_unknown(cfg, pi, ledger, live)
    if not snap["reachable"]:
        return log.info("brain unreachable; not claiming this pass")
    if not live:
        job = pi.claim("mac-dry-run")
        if job:
            log.warning("dry run: jobs are waiting and will not be delivered")
            log.info("dry-run: would deliver job %s kind=%s bytes=%s", job.get("id"), job.get("kind"), job.get("payload_bytes"))
            pi.reconcile(job["id"], job["claim_token"], "requeue")
        return
    for i in range(contracts.WORKER_MAX_PER_RUN):
        job = pi.claim("mac-worker")
        if not job:
            break
        if i:
            sleep(contracts.WORKER_PACE_S)
        if process(cfg, pi, brain, ledger, job):
            log.warning("stopping this pass (brain or pi unhealthy)")
            break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vnode-worker")
    ap.add_argument("--live", action="store_true", help="deliver to Brain (default is dry run)")
    ap.add_argument("--once", action="store_true", help="one pass then exit")
    ap.add_argument("--env-file", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load_config(a.env_file)
    except ConfigError as e:
        log.error("refusing to start: %s", e)
        return 78
    pi = PiClient(cfg.host, cfg.port, cfg.node_id, cfg.pi_token)
    brain = BrainClient(cfg.brain_url, cfg.brain_token)
    ledger = Ledger()
    log.info("worker %s started mode=%s", VERSION, "LIVE" if a.live else "dry-run")
    while True:
        try:
            run_once(cfg, pi, brain, ledger, a.live)
        except PinMismatch:
            log.error("pi certificate pin mismatch; nothing sent")
        except PiError as e:
            log.warning("pi: %s", e)
        except Exception as e:      # never crash-loop
            log.error("pass failed: %s", contracts.redact(type(e).__name__))
        if a.once:
            return 0
        time.sleep(contracts.WORKER_POLL_S)


if __name__ == "__main__":
    sys.exit(main())
