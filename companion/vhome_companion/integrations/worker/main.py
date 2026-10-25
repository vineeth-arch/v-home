"""VNode delivery worker: polls the node for inbox jobs and hands them to Brain.

Two homes, same code. Mac: polls the Pi over pinned TLS, delivers to Brain on loopback (and may write docs to the
vault inbox folder). Pi: polls its own int.sock (VNODE_SOCKET), delivers to Brain over https with docs sent as text.
Dry run by default; --live delivers. Stdlib only (macOS system python3 and the Pi's python3)."""
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
from .brain_client import BrainClient, BrainError, explain, parse_url, stops_pass
from .ledger import Ledger
from .pi_client import PayloadMismatch, PinMismatch, PiClient, PiError, UnixPiClient

VERSION = "0.2.0"
CLOCK_SYNC_FILE = "/run/systemd/timesync/synchronized"   # systemd-timesyncd; same signal the node service uses
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
        self.socket = g("VNODE_SOCKET")             # set on the Pi: talk to the node's unix socket instead of TLS
        self.node_id, self.pi_token = g("VNODE_NODE_ID").lower(), g("VNODE_WORKER_TOKEN")
        self.brain_url, self.brain_token = g("BRAIN_URL", "http://127.0.0.1:8000"), g("BRAIN_VNODE_TOKEN")
        self.allow_host = g("BRAIN_ALLOW_HOST").lower()
        self.cf_id, self.cf_secret = g("CF_ACCESS_CLIENT_ID"), g("CF_ACCESS_CLIENT_SECRET")
        self.inbox = g("BRAIN_INBOX_PATH")          # optional: unset = docs go to Brain as text over the API
        self.name = g("WORKER_NAME", "mac-worker")[:30]
        self.wait_clock = g("WAIT_CLOCK_SYNC") == "1"
        try:
            self.poll_s = max(10.0, float(g("WORKER_POLL_S", str(contracts.WORKER_POLL_S))))
            self.max_per_run = min(contracts.WORKER_MAX_PER_RUN, max(1, int(g("WORKER_MAX_PER_RUN", str(contracts.WORKER_MAX_PER_RUN)))))
        except ValueError:
            raise ConfigError("WORKER_POLL_S / WORKER_MAX_PER_RUN must be numbers") from None
        missing = [k for k, v in (("VNODE_NODE_ID", self.node_id or self.socket), ("VNODE_WORKER_TOKEN", self.pi_token),
                                  ("BRAIN_VNODE_TOKEN", self.brain_token)) if not v]
        if missing:
            raise ConfigError("worker env is missing: " + ", ".join(missing))
        if not self.socket and not re.fullmatch(r"[0-9a-f]{64}", self.node_id):
            raise ConfigError("VNODE_NODE_ID must be 64 hex chars (sha256 of the node cert DER)")
        if self.socket and not os.path.isabs(self.socket):
            raise ConfigError("VNODE_SOCKET must be an absolute path")
        if self.inbox and not os.path.isabs(self.inbox):
            raise ConfigError("BRAIN_INBOX_PATH must be an absolute path")
        if bool(self.cf_id) != bool(self.cf_secret):
            raise ConfigError("set both CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET, or neither")
        try:
            parse_url(self.brain_url, self.allow_host)
        except ValueError as e:
            raise ConfigError(str(e)) from None

    def pi_client(self):
        if self.socket:
            return UnixPiClient(self.socket, self.pi_token)
        return PiClient(self.host, self.port, self.node_id, self.pi_token)

    def brain_client(self):
        return BrainClient(self.brain_url, self.brain_token, cf_id=self.cf_id, cf_secret=self.cf_secret,
                           allow_host=self.allow_host)


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


_HEADING = re.compile(r"^#{1,6}\s", re.M)


def doc_as_text(text: str, job: dict) -> str:
    """Documents travel as plain capture text. Content untouched, except a label becomes the title when there is none."""
    label = contracts.sanitize_label(job.get("label"))
    return text if not label or _HEADING.search(text) else "# %s\n\n%s" % (label, text)


def deliver(cfg: Config, brain: BrainClient, job: dict, payload: bytes) -> str:
    kind = Kind(job["kind"])
    if kind in (Kind.MD, Kind.TXT) and cfg.inbox:
        return deliver_doc(cfg.inbox, job, payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise Delivery("bad_payload", False) from None
    key = contracts.validate_key(job.get("idempotency_key"))
    if kind in (Kind.MD, Kind.TXT):                  # no inbox folder here: Brain has no file route, send the text
        return brain.capture_text(doc_as_text(text, job), key)
    if kind is Kind.TEXT:
        return brain.capture_text(text, key)
    return brain.capture_url(text.strip(), contracts.sanitize_label(job.get("label")) or None, key)


# ---- one pass ------------------------------------------------------------------------------
def _safe_fail(pi, job, code, msg, retryable):
    try:
        pi.fail(job["id"], job["claim_token"], code, msg, retryable)
    except PiError as e:
        log.warning("job %s: fail not recorded (%s)", job["id"], e)


def _safe_requeue(pi, job, code, msg):
    try:
        pi.reconcile(job["id"], job["claim_token"], "requeue", error_code=code, error_msg=msg)
    except PiError as e:
        log.warning("job %s: requeue not recorded (%s); the lease will expire", job["id"], e)


DELIVERY_TEXT = {
    "name_conflict": "A different file with this name is already in Brain's inbox folder. VNode did not overwrite it.",
    "write_failed": "VNode could not write to Brain's inbox folder. It will try again.",
    "bad_payload": "This item is not valid UTF-8 text.",
    "bad_job": "VNode could not understand this item.",
}


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
        code = e.code if e.code == "access_blocked" else "brain_" + (e.code or "error")   # codes the phone app maps
        if e.retryable:          # Brain, token, network or Access problem: not this job's fault, so no attempt is burned
            _safe_requeue(pi, job, code, explain(e))
            return True          # same job would be claimed again at once; stop and retry on the next poll
        _safe_fail(pi, job, code, explain(e), False)
        return stops_pass(e)
    except Delivery as e:
        _safe_fail(pi, job, e.code, DELIVERY_TEXT.get(e.code, e.code), e.retryable)
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
            if job.get("kind") in ("md", "txt") and cfg.inbox:
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
    """Flat shape the Android screen reads. Brain down -> reachable false, counts null.
    A login redirect or 401/403 means Brain answered but refuses us: reachable true, auth_error true."""
    snap = {"reachable": True, "heartbeat": None, "pending": None, "processed_today": None, "needs_review": None,
            "failed": None, "last_note_id": ledger.last_delivered_ref(),
            "mode": "live" if live else "dry_run", "auth_error": False,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    carried = bool(getattr(brain, "auth_error", False))     # 401/403/redirect seen since the last status call
    try:
        st = brain.status()
        counts = st.get("counts") if isinstance(st.get("counts"), dict) else {}
        snap["heartbeat"] = st.get("heartbeat")
        for k in ("pending", "processed_today", "needs_review", "failed"):
            snap[k] = counts.get(k)
    except BrainError as e:
        snap["reachable"] = bool(getattr(brain, "auth_error", False)) and e.status != 0
    snap["auth_error"] = carried or bool(getattr(brain, "auth_error", False))
    return snap


def run_once(cfg, pi, brain, ledger, live, sleep=time.sleep) -> bool:
    """One pass. Returns True when Brain (not the Pi) made it stop early, so the caller can slow its polling."""
    pi.heartbeat(socket.gethostname()[:30], VERSION, "live" if live else "dry_run")
    snap = snapshot(brain, ledger, live)
    pi.brain_status(snap)
    reconcile_unknown(cfg, pi, ledger, live)
    # /api/status can be blocked (Access) while /api/capture works, so only a dead transport stops claiming.
    if getattr(brain, "transport_down", False):
        log.info("brain unreachable; not claiming this pass")
        return True
    if not live:
        job = pi.claim("mac-dry-run")
        if job:
            log.warning("dry run: jobs are waiting and will not be delivered")
            log.info("dry-run: would deliver job %s kind=%s bytes=%s", job.get("id"), job.get("kind"), job.get("payload_bytes"))
            pi.reconcile(job["id"], job["claim_token"], "requeue")
        return False
    stopped, captured = False, getattr(brain, "captured", 0)
    for i in range(cfg.max_per_run):
        job = pi.claim(cfg.name)
        if not job:
            break
        if i:
            sleep(contracts.WORKER_PACE_S)
        if process(cfg, pi, brain, ledger, job):
            log.warning("stopping this pass (brain or pi unhealthy)")
            stopped = True
            break
    if getattr(brain, "captured", 0) > captured and (not snap["reachable"] or snap["auth_error"]):
        # a capture just succeeded, so Brain is usable whatever /api/status said: fix what the phone sees
        brain.auth_error = False
        snap.update(reachable=True, auth_error=False)
        pi.brain_status(snap)
    return stopped


def clock_ready(cfg) -> bool:
    """TLS to Brain needs a real date; a Pi Zero has no RTC. Only enforced when WAIT_CLOCK_SYNC=1."""
    return not cfg.wait_clock or os.path.exists(CLOCK_SYNC_FILE)


def ledger_path():
    state = os.environ.get("STATE_DIRECTORY")      # set by systemd (StateDirectory=); the Mac uses ~/.vhome-int
    return os.path.join(state.split(":")[0], "delivered.db") if state else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vnode-worker")
    ap.add_argument("--live", action="store_true", help="deliver to Brain (default is dry run)")
    ap.add_argument("--once", action="store_true", help="one pass then exit")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--from-env", action="store_true", help="read settings from the environment (systemd EnvironmentFile)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = Config(dict(os.environ)) if a.from_env else load_config(a.env_file)
    except ConfigError as e:
        log.error("refusing to start: %s", e)
        return 78
    pi, brain = cfg.pi_client(), cfg.brain_client()
    ledger = Ledger(ledger_path())
    log.info("worker %s started mode=%s via=%s", VERSION, "LIVE" if a.live else "dry-run", "unix socket" if cfg.socket else "tls")
    slow = 0
    while True:
        wait = cfg.poll_s
        if not clock_ready(cfg):
            log.info("waiting for the clock to sync before talking to Brain")
            wait = 10.0
        else:
            try:
                slow = slow + 1 if run_once(cfg, pi, brain, ledger, a.live) else 0
            except PinMismatch:
                log.error("pi certificate pin mismatch; nothing sent")
            except PiError as e:
                log.warning("pi: %s", e)
            except Exception as e:      # never crash-loop
                log.error("pass failed: %s", contracts.redact(type(e).__name__))
            wait = min(cfg.poll_s * 2 ** min(slow, 4), 600.0)    # Brain trouble: poll less often, fewer SD writes
        if a.once:
            return 0
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
