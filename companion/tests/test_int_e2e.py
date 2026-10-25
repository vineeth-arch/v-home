"""End-to-end drills for the VNode integrations stack, all on localhost in temp dirs.

phone (TLS client) -> vnode API (TLS, 127.0.0.1) -> intproxy -> integrations service (unix socket)
                                                  <- Mac worker (TLS, pinned) -> Brain (loopback http)

Brain is the REAL Brain API (subprocess, Brain venv python, temp root) when it can start in ~20 s; the Brain drills
then run twice (fake Brain, real Brain). If Brain cannot start the real-Brain class is skipped with the reason.
Slow tests carry `slow` in their names: test_slow_* (real Brain, kill -9, restart).
"""
import asyncio
import hashlib
import http.client
import http.server
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

import aiohttp
from aiohttp import web

COMPANION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPANION))

from vhome_companion.integrations import contracts as ic  # noqa: E402
from vhome_companion.integrations import server as int_server  # noqa: E402
from vhome_companion.integrations.__main__ import _call as admin_call  # noqa: E402
from vhome_companion.integrations.payloads import PayloadStore  # noqa: E402
from vhome_companion.integrations.queue import Queue  # noqa: E402
from vhome_companion.integrations.status import StatusHolder  # noqa: E402
from vhome_companion.integrations.store import open_db  # noqa: E402
from vhome_companion.integrations.worker import main as W  # noqa: E402
from vhome_companion.integrations.worker.brain_client import BrainClient  # noqa: E402
from vhome_companion.integrations.worker.ledger import Ledger  # noqa: E402
from vhome_companion.integrations.worker.pi_client import PiClient, PiError  # noqa: E402
from vhome_companion.vnode import api, contracts as vc, intproxy  # noqa: E402
from vhome_companion.vnode.device import Device  # noqa: E402
from vhome_companion.vnode.phones import Nonces, PairingCodes, PhoneRegistry  # noqa: E402

BRAIN_REPO = Path("/Users/vineethnair/Vibe Code/brain-cockpit-vt")
BRAIN_PY = Path("/Users/vineethnair/Vibe Code/personal-brain-os/brain-cockpit/.venv/bin/python")
BRAIN_LAUNCHER = Path(__file__).resolve().parent / "e2e_brain_server.py"
BRAIN_START_S = 20.0
_CERT = {}
_REAL = {}


# ---- module fixtures --------------------------------------------------------------------------

def setUpModule():
    if not shutil.which("openssl"):
        raise unittest.SkipTest("openssl CLI not available to make a throwaway cert")
    d = tempfile.mkdtemp(dir="/tmp", prefix="e2e_cert_")
    _CERT["dir"] = Path(d)
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-days", "2", "-subj", "/CN=e2e-vnode", "-keyout", d + "/k.pem", "-out", d + "/c.pem"],
                   check=True, capture_output=True)
    _CERT["cert"], _CERT["key"] = d + "/c.pem", d + "/k.pem"
    _CERT["pin"] = api.node_id(_CERT["cert"])


def tearDownModule():
    brain = _REAL.get("brain")
    if brain:
        brain.stop()
    shutil.rmtree(_CERT.get("dir", ""), ignore_errors=True)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---- helpers ----------------------------------------------------------------------------------

class Loop:
    """A background asyncio loop; the blocking test thread talks to servers living in it."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, fn, *a, timeout=30):
        async def w():
            r = fn(*a)
            if inspect.isawaitable(r):
                r = await r
            return r
        return asyncio.run_coroutine_threadsafe(w(), self.loop).result(timeout)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.t.join(5)
        self.loop.close()


class TClock:
    """Real time plus a controllable offset (leases, backoff, stale windows) shared by every service clock method."""

    def __init__(self):
        self.off = 0.0

    def advance(self, s):
        self.off += s

    def wall(self): return time.time() + self.off
    def mono(self): return time.monotonic() + self.off
    def boot_id(self): return "e2e-boot"
    def uptime(self): return 1e6
    def synced(self): return True


class LogCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class InProcService:
    """The integrations service (real server.build_app + real Queue/SQLite) on a unix socket inside the loop thread."""

    def __init__(self, loop, state, sock, clock):
        self.loop, self.state, self.sock, self.clock = loop, Path(state), str(sock), clock
        self.free = [10 ** 12]
        self.runner = self.conn = self.queue = None

    def start(self):
        self.loop.call(self._start)

    async def _start(self):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.conn = open_db(self.state / ic.DB_NAME)
        self.queue = Queue(self.conn, PayloadStore(self.state / ic.PAYLOAD_DIR), self.clock, rand=lambda: 0.5,
                           disk_free=lambda: self.free[0])
        self.status = StatusHolder(self.clock)
        self.runner = web.AppRunner(int_server.build_app(self.queue, self.status, self.clock), access_log=None)
        await self.runner.setup()
        Path(self.sock).unlink(missing_ok=True)
        await web.UnixSite(self.runner, self.sock).start()

    def stop(self):
        if self.runner is not None:
            self.loop.call(self._stop)

    async def _stop(self):
        await self.runner.cleanup()
        self.conn.close()
        self.runner = None

    def create_token(self):
        return self.loop.call(self.queue.create_worker_token, ic.PROJECT_BRAIN)[1]

    def q(self, fn, *a):
        """Run a Queue call on the loop thread (SQLite connection is thread-bound)."""
        return self.loop.call(fn, *a)

    def expire(self):
        return self.loop.call(self.queue.expire_leases)

    def row(self, job_id):
        return self.loop.call(self.queue.get, job_id)


class SubprocService:
    """The real `python -m vhome_companion.integrations serve` process."""

    def __init__(self, tmp, state, sock, admin):
        self.tmp, self.state, self.sock, self.admin = Path(tmp), str(state), str(sock), str(admin)
        self.p = None
        self.log_path = self.tmp / "svc.log"

    def start(self):
        env = dict(os.environ, VHOME_INT_STATE=self.state, VHOME_INT_SOCKET=self.sock, VHOME_INT_ADMIN=self.admin,
                   PYTHONPATH=str(COMPANION), PYTHONDONTWRITEBYTECODE="1")
        with open(self.log_path, "ab") as log:
            self.p = subprocess.Popen([sys.executable, "-m", "vhome_companion.integrations", "serve"], env=env,
                                      stdout=log, stderr=log, cwd=str(self.tmp))
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.p.poll() is not None:
                raise RuntimeError("integrations service exited early: " + self.log_path.read_text()[-500:])
            if all(self._accepts(s) for s in (self.sock, self.admin)):
                return
            time.sleep(0.05)
        raise RuntimeError("integrations service did not come up")

    @staticmethod
    def _accepts(path):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1)
        try:
            s.connect(path)
            return True
        except OSError:
            return False
        finally:
            s.close()

    def stop(self):
        if self.p is not None and self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
            try:
                self.p.wait(15)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(5)

    def kill9(self):
        os.kill(self.p.pid, signal.SIGKILL)
        self.p.wait(10)

    def create_token(self):
        st, d = admin_call(self.admin, "POST", "/worker-token", {})
        assert st == 200, d
        return d["token"]

    def log_text(self):
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""


class FakeTV:
    def status(self):
        return {"tv": {"state": "connected", "host": "192.168.1.20", "paired": True, "power": "Active",
                       "foreground": "x", "age_s": 1.0, "last_error": None,
                       "pairing": {"state": "idle", "detail": ""}},
                "watcher": {"state": "watching", "enabled": True, "paused": False}}

    def diagnostics(self):
        return {"checks": {}, "log": [], "counters": {}}

    async def close(self):
        pass


class VNode:
    """The vnode API (real api.build_app + intproxy) served over TLS on 127.0.0.1:<free port>."""

    def __init__(self, loop, tmp, int_socket):
        self.loop, self.dir, self.int_socket = loop, Path(tmp) / "vnode", str(int_socket)
        self.runner = None

    def start(self):
        self.loop.call(self._start)

    async def _start(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.phones = PhoneRegistry(self.dir)
        self.phone_id, self.phone_token = self.phones.add("E2E phone")

        async def run(argv):
            return 0, ""

        async def run_out(argv):
            return 1, ""

        def no_read(p):
            raise OSError()
        device = Device(self.dir, run=run, run_out=run_out, read=no_read, glob=lambda pat: [], restart_delay=0.05)
        info = {"api": 1, "node_id": _CERT["pin"], "name": "vnode", "version": "0.1.0",
                "capabilities": vc.capabilities()}
        app = api.build_app(FakeTV(), self.phones, PairingCodes(), Nonces(), device, info, int_socket=self.int_socket)
        self.proxy = app[intproxy.PROXY_KEY]
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=api.make_ssl_context(_CERT["cert"], _CERT["key"]))
        await site.start()
        self.port = self.runner.addresses[0][1]

    def set_proxy_timeouts(self, total_s, connect_s=0.5):
        self.proxy.timeout = aiohttp.ClientTimeout(total=total_s, sock_connect=connect_s)

    def stop(self):
        if self.runner is not None:
            self.loop.call(self._stop)

    async def _stop(self):
        await self.runner.cleanup()
        self.runner = None


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, {k.lower(): v for k, v in headers}, body

    def json(self):
        return json.loads(self.body)

    @property
    def error(self):
        return self.json().get("error")


def https_request(port, method, path, headers=None, body=None, timeout=20):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=timeout, context=ctx)
    try:
        try:
            conn.request(method, path, body=body, headers=headers or {})
        except (BrokenPipeError, ConnectionResetError):
            pass          # server answered early (413) and closed; the response may still be readable
        r = conn.getresponse()
        return Resp(r.status, r.getheaders(), r.read())
    finally:
        conn.close()


class Phone:
    def __init__(self, port, token, secrets_list):
        self.port, self.token, self.secrets = port, token, secrets_list

    @property
    def auth(self):
        return {"Authorization": "Bearer " + self.token}

    def get(self, path, token=None, **kw):
        h = {"Authorization": "Bearer " + (token or self.token)}
        return https_request(self.port, "GET", path, h, **kw)

    def nonce(self):
        n = self.get("/v1/nonce").json()["nonce"]
        self.secrets.append(n)
        return n

    def post(self, path, body=b"", headers=None, nonce=True):
        h = dict(self.auth, **(headers or {}))
        if nonce is True:
            nonce = self.nonce()
        if nonce:
            h["X-VNode-Nonce"] = nonce
        r = https_request(self.port, "POST", path, h, body)
        r.nonce = nonce
        return r

    def submit(self, kind, body, key=None, label=None, nonce=True):
        body = body.encode() if isinstance(body, str) else body
        key = key or uuid.uuid4().hex
        h = {"X-Inbox-Kind": kind, "X-Idempotency-Key": key, "Content-Type": "application/octet-stream"}
        if label:
            h["X-Label"] = label
        r = self.post("/v1/inbox/jobs", body, h, nonce)
        r.key = key
        return r

    def job(self, job_id):
        r = self.get("/v1/inbox/jobs/" + job_id)
        assert r.status == 200, (r.status, r.body)
        return r.json()["job"]

    def counts(self):
        return self.get("/v1/inbox/jobs").json()["counts"]

    def brain_status(self):
        r = self.get("/v1/inbox/brain-status")
        assert r.status == 200, (r.status, r.body)
        return r.json()


# ---- Brain (real subprocess, or an in-process fake with the same observable behaviour) ----------

_NOTE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4} .*\.md$")
_DOC = re.compile(r"^\d{4}-\d{2}-\d{2} vnode-[A-Za-z0-9_-]{16}\.(md|txt)$")


class BrainBase:
    real = False

    def notes(self):
        """Capture notes the Brain API wrote into its inbox: [(filename, text)]."""
        return [(n, (self.inbox / n).read_text(encoding="utf-8")) for n in sorted(os.listdir(self.inbox))
                if _NOTE.match(n)]

    def docs(self):
        return sorted(n for n in os.listdir(self.inbox) if _DOC.match(n))

    def notes_with(self, marker):
        return [n for n in self.notes() if marker in n[1]]

    def capture(self, body, key=None):
        """Direct capture the way the worker does it (vnode token + X-Capture-Key). -> (status, json)"""
        h = {"Authorization": "Bearer " + self.vnode_token, "Content-Type": "application/json"}
        if key:
            h["X-Capture-Key"] = key
        req = urllib.request.Request(self.url + "/api/capture", data=json.dumps(body).encode(), headers=h,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")


class RealBrain(BrainBase):
    real = True

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(dir="/tmp", prefix="e2e_brain_"))
        self.inbox = self.root / "inbox"
        self.auth_token, self.vnode_token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self.p = None
        self.log_path = self.root / "brain.log"

    def start(self):
        for d in ("vault", "inbox", "archive", "failed"):
            (self.root / d).mkdir()
        cfg = {"vault_path": str(self.root / "vault"), "inbox_path": str(self.inbox),
               "archive_path": str(self.root / "archive"), "failed_path": str(self.root / "failed"),
               "transcription": {"engine": "whispercpp", "whispercpp": {"binary_path": "", "model_path": ""}},
               "ntfy": {"url": "", "topic": ""}, "api": {"auth_token": self.auth_token, "vnode_token": self.vnode_token},
               "classification": {"confidence_threshold": 0.7}, "links": {"dex": "https://getdex.com/"}}
        (self.root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        port = free_port()
        self.url = "http://127.0.0.1:%d" % port
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root), "PYTHONDONTWRITEBYTECODE": "1",
               "BRAIN_COCKPIT_ROOT": str(self.root)}
        with open(self.log_path, "ab") as log:
            self.p = subprocess.Popen([str(BRAIN_PY), "-B", str(BRAIN_LAUNCHER), str(BRAIN_REPO), str(self.root), str(port)],
                                      env=env, stdout=log, stderr=log, cwd=str(self.root))
        deadline = time.time() + BRAIN_START_S
        while time.time() < deadline:
            if self.p.poll() is not None:
                raise RuntimeError("brain exited: " + self.log_path.read_text(errors="replace")[-400:])
            try:
                with urllib.request.urlopen(self.url + "/api/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError("brain did not answer /api/health in %.0f s" % BRAIN_START_S)

    def stop(self):
        if self.p is not None and self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(5)
        shutil.rmtree(self.root, ignore_errors=True)


def real_brain():
    """-> (RealBrain | None, skip reason). Started once per run, on first need."""
    if "tried" in _REAL:
        return _REAL.get("brain"), _REAL.get("reason", "")
    _REAL["tried"] = True
    if not BRAIN_PY.exists() or not BRAIN_REPO.exists():
        _REAL["reason"] = "Brain venv python or brain-cockpit-vt worktree not found"
        return None, _REAL["reason"]
    b = RealBrain()
    try:
        b.start()
    except Exception as e:  # noqa: BLE001
        b.stop()
        _REAL["reason"] = "real Brain could not start in a temp root: %s" % str(e)[:300]
        return None, _REAL["reason"]
    _REAL["brain"] = b
    return b, ""


class FakeBrain(BrainBase):
    """Same observable behaviour as the Brain API for the routes the worker uses (bearer, X-Capture-Key dedupe,
    one inbox file per capture), plus a switch to fail captures."""

    def __init__(self, tmp, name="fakebrain"):
        self.inbox = Path(tmp) / (name + "-inbox")
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.vnode_token = "fake-brain-" + secrets.token_urlsafe(12)
        self.keys, self.capture_status, self.capture_calls, self.n = {}, 201, 0, 0
        self.lock = threading.Lock()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                if self.headers.get("Authorization") != "Bearer " + outer.vnode_token:
                    self._send(401, {"error": {"what": "no"}})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path == "/api/status":
                    return self._send(200, {"vault": "v", "heartbeat": "hb", "last_run": "hb",
                                            "counts": {"pending": 0, "processed_today": 0, "needs_review": 0, "failed": 0}})
                self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if not self._auth():
                    return
                with outer.lock:
                    outer.capture_calls += 1
                    if outer.capture_status >= 400:
                        return self._send(outer.capture_status, {"error": {"what": "boom"}})
                    key = self.headers.get("X-Capture-Key")
                    if key and key in outer.keys:
                        return self._send(201, {"id": outer.keys[key], "status": "captured"})
                    if body.get("url") is not None:
                        text = (body.get("insight") + "\n\n" if body.get("insight") else "") + body["url"].strip()
                    else:
                        text = (body.get("text") or "").strip()
                    outer.n += 1
                    nid = "%s00" % datetime.now().strftime("%Y%m%d%H%M")
                    name = "%s fake-%d.md" % (datetime.now().strftime("%Y-%m-%d-%H%M"), outer.n)
                    (outer.inbox / name).write_text(text + "\n", encoding="utf-8")
                    if key:
                        outer.keys[key] = nid
                    self._send(201, {"id": nid, "status": "captured"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Mac:
    """The Mac worker with a temp HOME, a 0600 worker.env and the real PiClient/BrainClient/Ledger."""

    def __init__(self, tmp, vnode_port, worker_token, brain, name="mac"):
        self.home = Path(tmp) / name
        d = self.home / ".vhome-int"
        d.mkdir(parents=True, mode=0o700)
        self.env_path = d / "worker.env"
        self.env_path.write_text("\n".join([
            "VNODE_HOST=127.0.0.1", "VNODE_PORT=%d" % vnode_port, "VNODE_NODE_ID=" + _CERT["pin"],
            "VNODE_WORKER_TOKEN=" + worker_token, "BRAIN_URL=" + brain.url,
            "BRAIN_VNODE_TOKEN=" + brain.vnode_token, "BRAIN_INBOX_PATH=" + str(brain.inbox)]) + "\n")
        os.chmod(self.env_path, 0o600)
        self.cfg = W.load_config(str(self.env_path))
        self.pi = PiClient(self.cfg.host, self.cfg.port, self.cfg.node_id, self.cfg.pi_token)
        self.brain = BrainClient(self.cfg.brain_url, self.cfg.brain_token)
        self.ledger = Ledger(str(d / "delivered.db"))

    def run(self, live=True):
        W.run_once(self.cfg, self.pi, self.brain, self.ledger, live, sleep=lambda s: None)

    def run_cli(self, live=True):
        env = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(COMPANION), PYTHONDONTWRITEBYTECODE="1")
        args = [sys.executable, "-m", "vhome_companion.integrations.worker.main", "--once",
                "--env-file", str(self.env_path)] + (["--live"] if live else [])
        return subprocess.run(args, env=env, capture_output=True, text=True, timeout=60, cwd=str(self.home))

    def close(self):
        self.ledger.close()


# ---- base test --------------------------------------------------------------------------------

class StackTest(unittest.TestCase):
    brain_kind = "fake"          # fake | real
    service_mode = "inproc"      # inproc | subproc

    @classmethod
    def setUpClass(cls):
        if cls.brain_kind == "real":
            b, reason = real_brain()
            if b is None:
                raise unittest.SkipTest(reason)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir="/tmp", prefix="e2e_"))
        self.secrets, self.extra_logs = [], []
        self.addCleanup(self.assert_logs_clean)          # registered first = runs last, after everything stopped
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = LogCollector()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(self.logs)
        root.setLevel(logging.DEBUG)
        self.addCleanup(lambda: (root.removeHandler(self.logs), root.setLevel(old_level)))
        self.loop = Loop()
        self.addCleanup(self.loop.close)
        self.clock = TClock()
        self.sock, self.admin = self.tmp / "int.sock", self.tmp / "admin.sock"
        if self.service_mode == "inproc":
            self.svc = InProcService(self.loop, self.tmp / "state", self.sock, self.clock)
        else:
            self.svc = SubprocService(self.tmp, self.tmp / "state", self.sock, self.admin)
        self.addCleanup(self.svc.stop)
        self.svc.start()
        self.vnode = VNode(self.loop, self.tmp, self.sock)
        self.addCleanup(self.vnode.stop)
        self.vnode.start()
        self.phone = Phone(self.vnode.port, self.vnode.phone_token, self.secrets)
        self.worker_token = self.svc.create_token()
        self.secrets += [self.vnode.phone_token, self.worker_token]
        if self.brain_kind == "real":
            self.brain = real_brain()[0]
            self.secrets += [self.brain.auth_token, self.brain.vnode_token]
        else:
            self.brain = FakeBrain(self.tmp)
            self.addCleanup(self.brain.stop)
            self.secrets.append(self.brain.vnode_token)
        self.mac = self.new_mac(self.brain)

    def new_mac(self, brain, name="mac"):
        mac = Mac(self.tmp, self.vnode.port, self.worker_token, brain, name)
        self.addCleanup(mac.close)
        return mac

    def marker(self, label="m"):
        m = "E2E-%s-%s" % (label, secrets.token_hex(6))
        self.secrets.append(m)
        return m

    def all_log_text(self):
        parts = list(self.logs.lines) + list(self.extra_logs)
        if isinstance(self.svc, SubprocService):
            parts.append(self.svc.log_text())
        return "\n".join(parts)

    def assert_logs_clean(self):
        text = self.all_log_text()
        for s in set(self.secrets):
            if len(s) >= 8 and s in text:
                self.fail("a secret/payload (%s...) leaked into logs" % s[:8])

    def submit_ok(self, kind, body, **kw):
        r = self.phone.submit(kind, body, **kw)
        self.assertEqual(r.status, 201, r.body)
        return r.json()["job"]


# ---- Brain drills: run against a fake Brain (fast) and the real Brain (slow) ----------------------

class BrainDrills:
    def test_happy_text(self):
        text = self.marker("text")
        r = self.phone.submit("text", text)
        self.assertEqual(r.status, 201, r.body)
        job = r.json()["job"]
        self.assertEqual((job["status"], job["kind"], job["attempts"]), ("queued", "text", 0))
        self.assertNotIn(text, r.body.decode())                       # phone view never carries the payload
        # same key + body again (fresh nonce) -> 200 duplicate; spent nonce -> 409
        again = self.phone.submit("text", text, key=r.key)
        self.assertEqual((again.status, again.json().get("duplicate"), again.json()["job"]["id"]),
                         (200, True, job["id"]))
        replay = self.phone.post("/v1/inbox/jobs", text.encode(), {"X-Inbox-Kind": "text", "X-Idempotency-Key": r.key},
                                 nonce=r.nonce)
        self.assertEqual((replay.status, replay.error), (409, "duplicate"))
        self.mac.run(live=True)
        done = self.phone.job(job["id"])
        self.assertEqual((done["status"], done["attempts"], done["error_code"]), ("completed", 0, None))
        self.assertTrue(done["result_ref"])
        self.assertEqual(len(self.brain.notes_with(text)), 1)
        if self.brain.real:
            self.assertRegex(done["result_ref"], r"^\d{14}$")
        # the note id the phone sees is the one Brain hands out for that key (idempotent re-capture)
        code, body = self.brain.capture({"text": text}, key=r.key)
        self.assertEqual((code, body["id"]), (201, done["result_ref"]))
        self.assertEqual(len(self.brain.notes_with(text)), 1)
        by_key = self.phone.get("/v1/inbox/by-key/" + r.key)
        self.assertEqual((by_key.status, by_key.json()["job"]["status"]), (200, "completed"))
        self.mac.run(live=True)                          # the snapshot is taken at the start of a pass
        bs = self.phone.brain_status()
        self.assertFalse(bs["worker_stale"])
        self.assertTrue(bs["snapshot"]["reachable"])
        self.assertEqual(bs["snapshot"]["last_note_id"], done["result_ref"])

    def test_url_with_label(self):
        url = "https://example.com/e2e/" + self.marker("url")
        job = self.submit_ok("url", url, label="read later")
        self.mac.run()
        done = self.phone.job(job["id"])
        self.assertEqual(done["status"], "completed")
        notes = self.brain.notes_with(url)
        self.assertEqual(len(notes), 1)
        self.assertIn("read later", notes[0][1])

    def test_md_and_txt_docs_land_in_inbox_with_exact_name(self):
        for kind in ("md", "txt"):
            body = ("# %s\n\nline two ✓\n" % self.marker(kind)).encode()
            r = self.phone.submit(kind, body)
            self.assertEqual(r.status, 201, r.body)
            job = r.json()["job"]
            self.mac.run()
            done = self.phone.job(job["id"])
            name = "%s vnode-%s.%s" % (job["created_at"][:10], r.key[:16], kind)
            self.assertEqual((done["status"], done["result_ref"]), ("completed", name))
            self.assertEqual((self.brain.inbox / name).read_bytes(), body)       # byte-exact
            self.assertIn(name, self.brain.docs())

    def test_dry_run_requeues_and_leaves_brain_untouched(self):
        text = self.marker("dry")
        job = self.submit_ok("text", text)
        before = (self.brain.notes(), self.brain.docs())
        self.mac.run(live=False)
        j = self.phone.job(job["id"])
        self.assertEqual((j["status"], j["attempts"]), ("queued", 0))
        self.assertEqual((self.brain.notes(), self.brain.docs()), before)
        self.assertEqual(self.brain.notes_with(text), [])
        lines = [l for l in self.logs.lines if job["id"] in l]
        claimed = [i for i, l in enumerate(lines) if " claimed " in l]
        queued = [i for i, l in enumerate(lines) if "queued kind=" in l and " queued " in l and i > (claimed or [0])[0]]
        self.assertTrue(claimed and queued, "job should have been claimed then requeued: %s" % lines)
        bs = self.phone.brain_status()                   # heartbeat + snapshot are sent in dry-run too
        self.assertFalse(bs["worker_stale"])
        self.assertTrue(bs["snapshot"]["reachable"])
        self.mac.run(live=True)                          # and a later live pass still delivers it
        self.assertEqual(self.phone.job(job["id"])["status"], "completed")
        self.assertEqual(len(self.brain.notes_with(text)), 1)

    def test_mac_asleep_jobs_queue_then_one_pass_drains_up_to_max(self):
        n = ic.WORKER_MAX_PER_RUN + 5
        texts = [self.marker("sleep%d" % i) for i in range(n)]
        ids = [self.submit_ok("text", t)["id"] for t in texts]
        self.assertEqual(self.phone.counts()["queued"], n)           # nobody home: all wait
        self.mac.run()
        c = self.phone.counts()
        self.assertEqual((c["completed"], c["queued"]), (ic.WORKER_MAX_PER_RUN, 5))
        self.mac.run()
        c = self.phone.counts()
        self.assertEqual((c["completed"], c["queued"]), (n, 0))
        self.assertTrue(all(len(self.brain.notes_with(t)) == 1 for t in texts))
        self.assertTrue(all(self.phone.job(i)["status"] == "completed" for i in ids))

    def test_crash_after_brain_post_before_complete_yields_exactly_one_note(self):
        text = self.marker("dupA")
        job = self.submit_ok("text", text)
        real_complete, calls = self.mac.pi.complete, []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise PiError(0, "unreachable:crash")
            return real_complete(*a, **kw)
        with mock.patch.object(self.mac.pi, "complete", flaky):
            self.mac.run()                       # Pi unreachable at complete: the pass stops, no exception
            self.assertEqual(len(calls), 1)
            self.assertEqual(self.phone.job(job["id"])["status"], "processing")
            self.assertEqual(len(self.brain.notes_with(text)), 1)
            self.clock.advance(ic.PROCESSING_LEASE_S + 10)
            self.assertEqual(self.svc.expire(), 1)
            self.assertEqual(self.phone.job(job["id"])["status"], "unknown")
            self.mac.run()                                            # next pass reconciles from the ledger
        done = self.phone.job(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertTrue(done["result_ref"])
        self.assertEqual(len(self.brain.notes_with(text)), 1)

    def test_ledger_write_failure_after_brain_capture_still_completes(self):
        text = self.marker("dupB")
        job = self.submit_ok("text", text)
        with mock.patch.object(self.mac.ledger, "delivered", side_effect=sqlite3.OperationalError("disk I/O")):
            self.mac.run()                                            # logged, complete still sent
        done = self.phone.job(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertTrue(done["result_ref"])
        self.assertEqual(len(self.brain.notes_with(text)), 1)

    def test_worker_dies_after_brain_post_before_ledger_and_complete_dedupes(self):
        text = self.marker("dupC")
        job = self.submit_ok("text", text)
        with mock.patch.object(self.mac.ledger, "delivered", side_effect=SystemExit("killed")):
            with self.assertRaises(SystemExit):
                self.mac.run()
        self.assertEqual(len(self.brain.notes_with(text)), 1)
        self.assertEqual(self.phone.job(job["id"])["status"], "processing")
        self.clock.advance(ic.PROCESSING_LEASE_S + 10)
        self.svc.expire()
        self.assertEqual(self.phone.job(job["id"])["status"], "unknown")
        self.mac.run()                    # ledger only has intent: requeue, re-deliver, Brain dedupes by capture key
        done = self.phone.job(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(len(self.brain.notes_with(text)), 1)
        code, body = self.brain.capture({"text": text}, key=self.svc.row(job["id"])["idempotency_key"])
        self.assertEqual(body["id"], done["result_ref"])

    def test_payload_claim_token_in_query_is_400_and_dry_run_mode_and_cross_phone_cancel(self):
        job = self.submit_ok("text", self.marker("misc"))
        claimed = self.mac.pi.claim("probe")
        r = https_request(self.vnode.port, "GET", "/v1/int/worker/jobs/%s/payload?claim_token=%s" % (
            job["id"], claimed["claim_token"]), {"Authorization": "Bearer " + self.worker_token})
        self.assertEqual(r.status, 400)
        self.assertEqual(self.mac.pi.payload(job["id"], claimed["claim_token"], claimed["payload_sha256"]) is not None, True)
        self.mac.pi.reconcile(job["id"], claimed["claim_token"], "requeue")
        self.mac.run(live=False)
        self.assertEqual(self.phone.brain_status()["snapshot"]["mode"], "dry_run")
        other = self.loop.call(self.vnode.phones.add, "second phone")[1]
        self.secrets.append(other)
        h = {"Authorization": "Bearer " + other, "X-VNode-Nonce": https_request(
            self.vnode.port, "GET", "/v1/nonce", {"Authorization": "Bearer " + other}).json()["nonce"]}
        r = https_request(self.vnode.port, "POST", "/v1/inbox/jobs/%s/cancel" % job["id"], h, b"")
        self.assertEqual(r.status, 404)
        self.assertEqual(self.phone.job(job["id"])["status"], "queued")

    def test_worker_cli_once_live_subprocess(self):
        text = self.marker("cli")
        job = self.submit_ok("text", text)
        dry = self.mac.run_cli(live=False)
        self.extra_logs += [dry.stdout, dry.stderr]
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(self.phone.job(job["id"])["status"], "queued")
        self.assertEqual(self.brain.notes_with(text), [])
        live = self.mac.run_cli(live=True)
        self.extra_logs += [live.stdout, live.stderr]
        self.assertEqual(live.returncode, 0, live.stderr)
        self.assertEqual(self.phone.job(job["id"])["status"], "completed")
        self.assertEqual(len(self.brain.notes_with(text)), 1)
        self.assertTrue((self.mac.home / ".vhome-int" / "delivered.db").exists())


class TestDrillsFakeBrain(BrainDrills, StackTest):
    brain_kind = "fake"


class TestSlowDrillsRealBrain(BrainDrills, StackTest):
    """test_* here are the same drills against the real Brain API subprocess (slow: it boots uvicorn + FastAPI)."""
    brain_kind = "real"

    def test_slow_real_brain_rejects_wrong_vnode_token(self):
        req = urllib.request.Request(self.brain.url + "/api/status", headers={"Authorization": "Bearer nope"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 401)


# ---- infrastructure drills ------------------------------------------------------------------------

class TestInfra(StackTest):
    def test_queue_full_gives_429_with_retry_after_through_proxy(self):
        for i in range(ic.MAX_LIVE_JOBS):
            self.svc.q(self.svc.queue.submit, "p-fill", "text", "fill%013d" % i, "", b"x%d" % i)
        r = self.phone.submit("text", self.marker("full"))
        self.assertEqual((r.status, r.error), (429, "queue_full"))
        self.assertGreater(int(r.headers["retry-after"]), 0)
        self.assertEqual(self.phone.counts()["queued"], ic.MAX_LIVE_JOBS)

    def test_disk_reserve_gives_507_through_proxy(self):
        self.svc.free[0] = ic.DISK_RESERVE_BYTES - 1
        r = self.phone.submit("text", self.marker("disk"))
        self.assertEqual((r.status, r.error), (507, "disk_reserve"))
        self.assertEqual(self.phone.counts()["queued"], 0)
        self.svc.free[0] = 10 ** 12                                 # space back: submits work again
        self.assertEqual(self.phone.submit("text", self.marker("disk2")).status, 201)

    def test_malformed_and_oversize_payloads(self):
        m = self.marker("bad")
        cases = [
            ("bad utf8", "text", b"\xff\xfe" + m.encode(), 400, "bad_request"),
            ("NUL", "text", (m + "\x00x").encode(), 400, "bad_request"),
            ("empty", "text", b"   \n", 400, "bad_request"),
            ("bad url", "url", ("ftp://example.com/" + m).encode(), 400, "bad_request"),
            ("url with space", "url", ("https://a.b/c d" + m).encode(), 400, "bad_request"),
            ("unknown kind", "pdf", m.encode(), 415, "unsupported_kind"),
            ("text over 8 KiB", "text", b"a" * (ic.MAX_TEXT + 1), 413, "too_large"),
            ("url over 2 KiB", "url", b"https://a.b/" + b"a" * ic.MAX_URL, 413, "too_large"),
            ("doc over 256 KiB", "md", b"a" * (ic.MAX_DOC + 1), 413, "too_large"),
            ("over the proxy cap", "md", b"a" * (ic.PROXY_MAX_BODY + 1), 413, "too_large"),
        ]
        for name, kind, body, status, code in cases:
            with self.subTest(name):
                r = self.phone.submit(kind, body)
                self.assertEqual((r.status, r.error), (status, code), r.body[:200])
        r = self.phone.submit("text", m, key="short")
        self.assertEqual((r.status, r.error), (400, "bad_request"))
        r = self.phone.post("/v1/inbox/jobs", m.encode(), {"X-Inbox-Kind": "text", "X-Idempotency-Key": uuid.uuid4().hex},
                            nonce=False)
        self.assertEqual(r.status, 422)                              # nonce header is mandatory for phone POSTs
        self.assertEqual(sum(self.phone.counts().values()), 0)       # nothing was stored
        k = uuid.uuid4().hex                                          # same key, different body -> key_conflict
        self.assertEqual(self.phone.submit("text", m, key=k).status, 201)
        r = self.phone.submit("text", m + "-other", key=k)
        self.assertEqual((r.status, r.error), (409, "key_conflict"))

    def test_worker_gone_jobs_stay_queued_and_status_goes_stale(self):
        self.mac.run(live=False)                                     # worker was alive: heartbeat + snapshot
        bs = self.phone.brain_status()
        self.assertFalse(bs["worker_stale"])
        self.assertFalse(bs["stale"])
        ids = [self.submit_ok("text", self.marker("gone%d" % i))["id"] for i in range(3)]
        self.clock.advance(ic.WORKER_STALE_S + 5)                    # ... and then the Mac sleeps
        bs = self.phone.brain_status()
        self.assertTrue(bs["worker_stale"])
        self.assertTrue(bs["stale"])
        self.assertGreater(bs["worker_last_seen_age_s"], ic.WORKER_STALE_S)
        self.assertEqual(bs["queue"]["queued"], 3)
        self.assertEqual([self.phone.job(i)["status"] for i in ids], ["queued"] * 3)
        self.assertEqual([self.phone.job(i)["attempts"] for i in ids], [0] * 3)

    def test_never_seen_worker_is_stale_with_null_ages(self):
        bs = self.phone.brain_status()
        self.assertEqual((bs["worker_stale"], bs["stale"], bs["snapshot"], bs["worker_last_seen_age_s"]),
                         (True, True, None, None))

    def test_brain_unreachable_worker_does_not_claim(self):
        job = self.submit_ok("text", self.marker("down"))
        dead = types.SimpleNamespace(url="http://127.0.0.1:%d" % free_port(), vnode_token="x", inbox=self.brain.inbox)
        mac = self.new_mac(dead, "mac-down")
        mac.run(live=True)
        j = self.phone.job(job["id"])
        self.assertEqual((j["status"], j["attempts"]), ("queued", 0))
        bs = self.phone.brain_status()
        self.assertFalse(bs["snapshot"]["reachable"])                # the phone can tell "Brain down" from "Mac down"
        self.assertFalse(bs["worker_stale"])

    def test_brain_5xx_backs_off_then_succeeds_when_brain_returns(self):
        text = self.marker("5xx")
        job = self.submit_ok("text", text)
        self.brain.capture_status = 503
        self.mac.run()
        j = self.phone.job(job["id"])
        self.assertEqual((j["status"], j["attempts"], j["error_code"]), ("queued", 1, "brain_http_503"))
        self.assertNotIn(text, json.dumps(j))
        nxt = self.svc.row(job["id"])["next_attempt_at"]
        self.assertGreater(nxt, self.clock.wall() + 30)              # backoff, not an immediate retry
        calls = self.brain.capture_calls
        self.brain.capture_status = 201                              # Brain is back, but backoff still holds
        self.mac.run()
        self.assertEqual((self.brain.capture_calls, self.phone.job(job["id"])["status"]), (calls, "queued"))
        self.clock.advance(ic.BACKOFF_BASE_S * 4)
        self.mac.run()
        j = self.phone.job(job["id"])
        self.assertEqual((j["status"], j["attempts"]), ("completed", 1))
        self.assertEqual(len(self.brain.notes_with(text)), 1)

    def test_brain_4xx_is_a_permanent_failure_and_retry_is_offered(self):
        job = self.submit_ok("text", self.marker("4xx"))
        self.brain.capture_status = 400
        self.mac.run()
        j = self.phone.job(job["id"])
        self.assertEqual((j["status"], j["error_code"], j["retry_safe"]), ("failed", "brain_http_400", True))
        self.brain.capture_status = 201
        r = self.phone.post("/v1/inbox/jobs/%s/retry" % job["id"])
        self.assertEqual((r.status, r.json()["job"]["status"]), (200, "queued"))
        self.mac.run()
        self.assertEqual(self.phone.job(job["id"])["status"], "completed")

    def test_cancel_queued_job_is_never_delivered(self):
        text = self.marker("cancel")
        job = self.submit_ok("text", text)
        r = self.phone.post("/v1/inbox/jobs/%s/cancel" % job["id"])
        self.assertEqual((r.status, r.json()["job"]["status"]), (200, "cancelled"))
        self.mac.run()
        self.assertEqual(self.brain.notes_with(text), [])

    def test_worker_and_phone_tokens_do_not_cross(self):
        # worker token on a phone route: the vnode phone-auth middleware refuses it
        r = self.phone.get("/v1/status", token=self.worker_token)
        self.assertEqual((r.status, r.error), (401, "unauthorized"))
        r = self.phone.get("/v1/inbox/brain-status", token=self.worker_token)
        self.assertEqual(r.status, 401)
        self.assertEqual(self.phone.get("/v1/status").status, 200)
        # phone token on a worker route: proxy forwards, the service verifies against worker tokens -> 401
        r = https_request(self.vnode.port, "POST", "/v1/int/worker/claim", {
            "Authorization": "Bearer " + self.vnode.phone_token, "Content-Type": "application/json"},
            json.dumps({"worker": "x"}).encode())
        self.assertEqual((r.status, r.error), (401, "unauthorized"))
        # no bearer at all: refused at the proxy before forwarding
        r = https_request(self.vnode.port, "POST", "/v1/int/worker/claim", {}, b"{}")
        self.assertEqual(r.status, 401)
        # a worker bearer that is not a token we issued
        wrong = "wrong-" + secrets.token_urlsafe(12)
        self.secrets.append(wrong)
        r = https_request(self.vnode.port, "POST", "/v1/int/worker/claim", {"Authorization": "Bearer " + wrong},
                          b'{"worker": "x"}')
        self.assertEqual(r.status, 401)
        # the proper worker token works
        r = https_request(self.vnode.port, "POST", "/v1/int/worker/claim", {"Authorization": "Bearer " + self.worker_token},
                          b'{"worker": "x"}')
        self.assertEqual((r.status, r.json()), (200, {"job": None}))
        # a forged X-VNode-Phone from a client is dropped; no phone token -> still 401 at the vnode
        r = https_request(self.vnode.port, "GET", "/v1/inbox/jobs", {"X-VNode-Phone": "forged"})
        self.assertEqual(r.status, 401)

    def test_logs_never_contain_payload_or_tokens(self):
        secret_text = self.marker("logs")
        job = self.submit_ok("text", secret_text, label="lbl")
        self.phone.submit("text", secret_text + "\x00")              # rejected
        self.phone.submit("text", secret_text + "-x", key=self.phone.submit("text", secret_text, key=uuid.uuid4().hex).key)
        self.mac.run()
        self.mac.run(live=False)
        self.phone.get("/v1/inbox/jobs/" + job["id"])
        self.assertTrue(any("vhome.intproxy" in l or "->" in l for l in self.logs.lines), "no logs collected")
        text = self.all_log_text()
        self.assertIn(job["id"], text)                               # logs do carry ids ...
        for s in set(self.secrets):
            self.assertNotIn(s, text)                                # ... but never payloads/tokens/nonces

    def test_tv_status_unaffected_when_integrations_socket_absent(self):
        self.svc.stop()
        self.sock.unlink(missing_ok=True)
        for _ in range(3):
            t = time.perf_counter()
            self.assertEqual(self.phone.get("/v1/status").status, 200)
            self.assertLess(time.perf_counter() - t, 0.5)
        for path in ("/v1/inbox/jobs", "/v1/inbox/brain-status"):
            t = time.perf_counter()
            r = self.phone.get(path)
            self.assertLess(time.perf_counter() - t, 0.5)
            self.assertEqual((r.status, r.error), (503, "integrations_unavailable"))
        t = time.perf_counter()
        r = self.phone.submit("text", self.marker("absent"))
        self.assertLess(time.perf_counter() - t, 0.5)
        self.assertEqual((r.status, r.error), (503, "integrations_unavailable"))
        self.assertEqual(self.phone.get("/v1/info").status, 200)
        self.assertEqual(self.phone.get("/v1/info").json()["int"], 1)

    def test_tv_status_unaffected_when_integrations_socket_hangs(self):
        self.svc.stop()
        self.sock.unlink(missing_ok=True)
        hang = Path(self.sock)

        async def start_hang():
            async def h(reader, writer):
                await asyncio.sleep(3600)
            return await asyncio.start_unix_server(h, path=str(hang))
        server = self.loop.call(start_hang)
        self.addCleanup(lambda: self.loop.call(lambda: server.close()))
        self.vnode.set_proxy_timeouts(total_s=1.0)
        result = {}

        def inbox_call():
            t = time.perf_counter()
            result["r"] = self.phone.get("/v1/inbox/brain-status")
            result["dt"] = time.perf_counter() - t
        th = threading.Thread(target=inbox_call)
        th.start()
        lat = []
        while th.is_alive():                                         # TV traffic while the inbox call is stuck
            t = time.perf_counter()
            self.assertEqual(self.phone.get("/v1/status").status, 200)
            lat.append(time.perf_counter() - t)
            time.sleep(0.05)
        th.join()
        self.assertTrue(lat and max(lat) < 0.5, lat)
        self.assertEqual((result["r"].status, result["r"].error), (503, "integrations_unavailable"))
        self.assertLess(result["dt"], 3.0)                           # bounded by the proxy timeout, not by the hang
        for _ in range(2):                                           # two more stalls trip the breaker ...
            self.assertEqual(self.phone.get("/v1/inbox/jobs").status, 503)
        t = time.perf_counter()
        r = self.phone.get("/v1/inbox/jobs")                         # ... after which inbox routes fail instantly
        self.assertLess(time.perf_counter() - t, 0.5)
        self.assertEqual((r.status, r.error), (503, "integrations_unavailable"))
        t = time.perf_counter()
        self.assertEqual(self.phone.get("/v1/status").status, 200)
        self.assertLess(time.perf_counter() - t, 0.5)


# ---- slow: real service process --------------------------------------------------------------------

class TestSlowRestart(StackTest):
    service_mode = "subproc"

    def test_slow_service_restart_mid_queue_keeps_jobs_and_they_drain(self):
        texts = [self.marker("rs%d" % i) for i in range(3)]
        ids = [self.submit_ok("text", t)["id"] for t in texts]
        self.svc.stop()
        self.assertEqual(self.svc.p.returncode, 0)                    # SIGTERM = clean exit
        r = self.phone.get("/v1/inbox/jobs")
        self.assertEqual((r.status, r.error), (503, "integrations_unavailable"))   # down, and the TV side says so fast
        self.assertEqual(self.phone.get("/v1/status").status, 200)
        self.svc.start()
        r = self.phone.get("/v1/inbox/jobs")
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(r.json()["counts"]["queued"], 3)
        self.assertEqual({j["id"] for j in r.json()["jobs"]}, set(ids))
        self.mac.run()                                                # the old worker token still works
        self.assertEqual(self.phone.counts()["completed"], 3)
        self.assertTrue(all(len(self.brain.notes_with(t)) == 1 for t in texts))

    def test_slow_service_stderr_has_no_payloads_or_tokens(self):
        text = self.marker("subproc-logs")
        job = self.submit_ok("text", text)
        self.mac.run()
        self.assertEqual(self.phone.job(job["id"])["status"], "completed")
        log = self.svc.log_text()
        self.assertIn(job["id"], log)
        self.assertNotIn(text, log)
        for s in self.secrets:
            self.assertNotIn(s, log)


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def unix_request(path, method, url, headers=None, body=None):
    c = UnixConn(path)
    try:
        c.request(method, url, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


class TestSlowKill9(unittest.TestCase):
    """SIGKILL the real service while phones are submitting; every acknowledged (201) job must survive."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir="/tmp", prefix="e2e_k9_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.svc = SubprocService(self.tmp, self.tmp / "state", self.tmp / "int.sock", self.tmp / "admin.sock")
        self.addCleanup(self.svc.stop)

    def submit_until_killed(self, ack, stop, tid, tag):
        i = 0
        while not stop.is_set():
            i += 1
            body = ("kill9-%s-%d-%d" % (tag, tid, i)).encode()
            try:
                st, raw = unix_request(self.svc.sock, "POST", "/v1/inbox/jobs", {
                    "X-VNode-Phone": "k9-%d-%d" % (tid, i), "X-Inbox-Kind": "text",
                    "X-Idempotency-Key": uuid.uuid4().hex}, body)
            except (OSError, http.client.HTTPException):
                return                                               # the service was killed under us
            if st == 201:
                ack.append((json.loads(raw)["job"]["id"], hashlib.sha256(body).hexdigest()))
            elif st == 429:
                return                                               # queue full

    def test_slow_kill9_mid_submit_keeps_every_acknowledged_job(self):
        acked = []
        for cycle, threshold in enumerate((25, 40, 60)):
            self.svc.start()
            ack, stop = [], threading.Event()
            threads = [threading.Thread(target=self.submit_until_killed, args=(ack, stop, t, cycle)) for t in range(3)]
            for t in threads:
                t.start()
            deadline = time.time() + 20
            while len(ack) < threshold and time.time() < deadline and any(t.is_alive() for t in threads):
                time.sleep(0.005)
            self.svc.kill9()                                         # no clean shutdown, no WAL checkpoint
            stop.set()
            for t in threads:
                t.join(10)
            self.assertGreaterEqual(len(ack), threshold, "submitters made no progress")
            acked += list(ack)
            # inspect the database as left by the dead process (opening replays the WAL)
            db = sqlite3.connect(str(self.tmp / "state" / ic.DB_NAME))
            try:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                rows = {r[0]: r[1:] for r in db.execute("SELECT id, payload_ref, payload_sha256, status FROM jobs")}
            finally:
                db.close()
            for jid, sha in acked:
                self.assertIn(jid, rows, "acknowledged job %s lost after kill -9 (cycle %d)" % (jid, cycle))
                ref = rows[jid][0]
                data = (self.tmp / "state" / ic.PAYLOAD_DIR / ref).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), sha)
            for jid, (ref, _, _) in rows.items():                     # no row points at a missing payload
                self.assertTrue((self.tmp / "state" / ic.PAYLOAD_DIR / ref).exists(), "row %s has no payload" % jid)
        self.svc.start()
        for jid, _ in acked:
            st, raw = unix_request(self.svc.sock, "GET", "/v1/inbox/jobs/" + jid, {"X-VNode-Phone": "k9-check"})
            self.assertEqual(st, 200, raw)
            self.assertEqual(json.loads(raw)["job"]["status"], "queued")
        self.assertNotIn("kill9-", self.svc.log_text())               # payloads never reach stderr
        # macOS-only aiohttp noise: SO_KEEPALIVE on an AF_UNIX socket whose peer already hung up -> EINVAL. Harmless on Linux.
        blocks = self.svc.log_text().split("Traceback (most recent call last)")[1:]
        self.assertEqual([b[:300] for b in blocks if "tcp_keepalive" not in b], [])


if __name__ == "__main__":
    unittest.main()
