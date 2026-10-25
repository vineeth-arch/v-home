import hashlib
import http.server
import json
import logging
import os
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
import uuid
from unittest import mock

from vhome_companion.integrations import contracts
from vhome_companion.integrations.worker import main as W
from vhome_companion.integrations.worker.brain_client import BrainClient, BrainError, explain, parse_url, stops_pass
from vhome_companion.integrations.worker.ledger import Ledger
from vhome_companion.integrations.worker.pi_client import PiClient, PinMismatch, PiError, UnixPiClient

PI_TOKEN, BRAIN_TOKEN = "pi-secret-token-AAAA", "brain-secret-token-BBBB"
SECRET_TEXT = "my very private thought 12345"
_CERT = {}


def setUpModule():
    if not shutil.which("openssl"):
        raise unittest.SkipTest("openssl CLI not available to make a throwaway cert")
    d = tempfile.mkdtemp()
    _CERT["dir"] = d
    for name in ("a", "b"):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=fake-pi",
                        "-keyout", "%s/%s.key" % (d, name), "-out", "%s/%s.pem" % (d, name)],
                       check=True, capture_output=True)
        der = subprocess.run(["openssl", "x509", "-in", "%s/%s.pem" % (d, name), "-outform", "DER"],
                             check=True, capture_output=True).stdout
        _CERT[name] = hashlib.sha256(der).hexdigest()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout", "%s/c.key" % d, "-out", "%s/c.pem" % d], check=True, capture_output=True)   # a cert a client can verify


def tearDownModule():
    shutil.rmtree(_CERT.get("dir", ""), ignore_errors=True)


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def server_bind(self):
        super().server_bind()
        self.server_address = ("unix", 0)


class Server:
    def __init__(self, handler, tls=None, unix=None):
        self.httpd = _UnixHTTPServer(unix, handler) if unix else http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain("%s/%s.pem" % (_CERT["dir"], tls), "%s/%s.key" % (_CERT["dir"], tls))
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_pi(state, tls="a", unix=None):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _do(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            state["calls"].append((self.command, self.path, self.headers.get("Authorization"), body))
            state.setdefault("headers", []).append((self.path, self.headers.get(contracts.CLAIM_HEADER)))
            route = self.path.split("?")[0].replace(contracts.WORKER_PREFIX, "")
            out, code, extra = b"", 200, {}
            for suffix, status in state.get("route_status", {}).items():
                if route.endswith(suffix):
                    self.send_response(status)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
            if route == "claim":
                job = state["queue"].pop(0) if state["queue"] else None
                out = json.dumps({"job": job}).encode()
            elif route == "unknown":
                out = json.dumps({"jobs": state["unknown"]}).encode()
            elif route.endswith("/payload"):
                jid = route.split("/")[1]
                out = state["payloads"][jid]
                extra = {"X-Payload-Sha256": hashlib.sha256(out).hexdigest()}
            elif route in ("heartbeat", "brain-status"):
                code = 204
            else:
                out = b"{}"
            self.send_response(code)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        do_GET = do_POST = _do
    return Server(H, tls, unix)


def make_brain(state, tls=None):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _do(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            state["calls"].append((self.command, self.path, self.headers.get("X-Capture-Key"), self.headers.get("Authorization"), body))
            state.setdefault("hdrs", []).append(dict(self.headers))
            if self.path in state.get("redirect", ()):        # Cloudflare Access login redirect
                self.send_response(state.get("redirect_code", 302))
                self.send_header("Location", "https://team.cloudflareaccess.com/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path in state.get("html", ()):            # 200 login page
                page = b"<html>Sign in</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            code, out = state.get("status_code", 200), {"vault": "v", "heartbeat": "hb", "counts": {"pending": 2, "processed_today": 3, "needs_review": 1, "failed": 0}}
            if self.path == "/api/capture":
                code = state.get("capture_code", 201)
                if code >= 400:
                    out = state.get("capture_err", {})
                else:
                    out = {"id": "note-%d" % len([c for c in state["calls"] if c[1] == "/api/capture"]), "status": "captured"}
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        do_GET = do_POST = _do
    return Server(H, tls)


def dead_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def mkjob(kind="text", key=None, payload=SECRET_TEXT.encode(), label="", created="2026-03-04T10:00:00Z"):
    return {"id": str(uuid.uuid4()), "op": "x", "kind": kind, "idempotency_key": key or uuid.uuid4().hex[:20],
            "label": label, "created_at": created, "attempts": 0, "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_bytes": len(payload), "claim_token": "ct-" + uuid.uuid4().hex, "status": "claimed"}, payload


class Base(unittest.TestCase):
    def setUp(self):
        W._STATE.clear()      # "log on change" and the soft-failure counter are per process; keep tests independent
        W._SOFT.clear()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inbox = os.path.join(self.tmp, "inbox")
        os.mkdir(self.inbox)
        self.pi_state = {"calls": [], "queue": [], "unknown": [], "payloads": {}}
        self.brain_state = {"calls": []}
        self.pi_srv, self.brain_srv = make_pi(self.pi_state), make_brain(self.brain_state)
        self.addCleanup(self.pi_srv.stop)
        self.addCleanup(self.brain_srv.stop)
        self.ledger = Ledger(os.path.join(self.tmp, "home", ".vhome-int", "delivered.db"))
        self.addCleanup(self.ledger.close)
        self.brain_port = self.brain_srv.port
        self.node_id = _CERT["a"]

    def parts(self, brain_port=None, node_id=None):
        brain_port = brain_port or self.brain_port
        cfg = W.Config({"VNODE_HOST": "127.0.0.1", "VNODE_PORT": str(self.pi_srv.port), "VNODE_NODE_ID": node_id or self.node_id,
                        "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_URL": "http://127.0.0.1:%d" % brain_port,
                        "BRAIN_VNODE_TOKEN": BRAIN_TOKEN, "BRAIN_INBOX_PATH": self.inbox})
        return (cfg, PiClient(cfg.host, cfg.port, cfg.node_id, cfg.pi_token), BrainClient(cfg.brain_url, cfg.brain_token))

    def queue(self, *jp):
        for job, payload in jp:
            self.pi_state["queue"].append(job)
            self.pi_state["payloads"][job["id"]] = payload

    def run_once(self, live=True, **kw):
        cfg, pi, brain = self.parts(**kw)
        W.run_once(cfg, pi, brain, self.ledger, live, sleep=lambda s: None)

    def pi_posts(self, suffix):
        return [c for c in self.pi_state["calls"] if c[1].split("?")[0].endswith(suffix)]

    def captures(self):
        return [c for c in self.brain_state["calls"] if c[1] == "/api/capture"]


class TestPin(Base):
    def test_mismatch_sends_no_authorization(self):
        with self.assertRaises(PinMismatch):
            self.run_once(node_id=_CERT["b"])
        self.assertEqual(self.pi_state["calls"], [])      # no request bytes at all

    def test_match_sends_bearer(self):
        self.run_once(live=False)
        self.assertTrue(self.pi_state["calls"])
        self.assertTrue(all(c[2] == "Bearer " + PI_TOKEN for c in self.pi_state["calls"]))


class TestDelivery(Base):
    def test_dry_run_requeues_and_skips_brain_capture(self):
        job, p = mkjob()
        self.queue((job, p))
        self.run_once(live=False)
        self.assertEqual(self.captures(), [])
        rec = self.pi_posts("reconcile")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0][3]["action"], "requeue")
        self.assertEqual(self.pi_posts("start"), [])
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertTrue(self.pi_posts("heartbeat") and self.pi_posts("brain-status"))
        snap = self.pi_posts("brain-status")[0][3]
        self.assertEqual({k: snap[k] for k in snap if k != "at"}, {"reachable": True, "heartbeat": "hb", "pending": 2,
                         "processed_today": 3, "needs_review": 1, "failed": 0, "last_note_id": None,
                         "mode": "dry_run", "auth_error": False})

    def test_live_text_and_url(self):
        t, tp = mkjob("text", key="textkey1234567890")
        u, up = mkjob("url", key="urlkey12345678901", payload=b"https://example.com/a", label="read later")
        self.queue((t, tp), (u, up))
        self.run_once()
        caps = self.captures()
        self.assertEqual([c[2] for c in caps], ["textkey1234567890", "urlkey12345678901"])
        self.assertEqual(caps[0][4], {"text": SECRET_TEXT})
        self.assertEqual(caps[1][4], {"url": "https://example.com/a", "insight": "read later"})
        self.assertTrue(all(c[3] == "Bearer " + BRAIN_TOKEN for c in caps))
        done = self.pi_posts("complete")
        self.assertEqual([c[3]["result_ref"] for c in done], ["note-1", "note-2"])
        self.assertEqual(self.ledger.get(t["id"])["state"], "delivered")

    def test_brain_5xx_requeues_not_fails(self):
        self.brain_state["capture_code"] = 500
        job, p = mkjob()
        self.queue((job, p))
        self.run_once()
        self.assertEqual(self.pi_posts("fail"), [])
        rec = self.pi_posts("reconcile")[0][3]
        self.assertEqual((rec["action"], rec["error_code"]), ("requeue", "brain_http_500"))
        self.assertEqual(self.pi_posts("complete"), [])

    def test_brain_400_fails_not_retryable(self):
        self.brain_state["capture_code"] = 400
        job, p = mkjob()
        self.queue((job, p))
        self.run_once()
        self.assertFalse(self.pi_posts("fail")[0][3]["retryable"])

    def test_brain_429_retryable_unit(self):
        self.brain_state["capture_code"] = 429
        with self.assertRaises(BrainError) as cm:
            self.parts()[2].capture_text("x", "k" * 16)
        self.assertTrue(cm.exception.retryable)

    def test_brain_down_no_claim(self):
        job, p = mkjob()
        self.queue((job, p))
        self.run_once(brain_port=dead_port())
        self.assertEqual(self.pi_posts("claim"), [])
        self.assertTrue(self.pi_posts("heartbeat"))
        snap = self.pi_posts("brain-status")[0][3]
        self.assertFalse(snap["reachable"])
        self.assertIsNone(snap["pending"])
        self.assertEqual(len(self.pi_state["queue"]), 1)

    def test_payload_claim_token_in_header_not_query(self):
        job, p = mkjob()
        self.queue((job, p))
        self.run_once()
        paths = [h for h in self.pi_state["headers"] if h[0].split("?")[0].endswith("/payload")]
        self.assertEqual(len(paths), 1)
        self.assertNotIn("claim_token", paths[0][0])
        self.assertNotIn("?", paths[0][0])
        self.assertEqual(paths[0][1], job["claim_token"])

    def test_payload_sha_mismatch_fails_without_delivery(self):
        job, p = mkjob()
        job["payload_sha256"] = "0" * 64
        self.queue((job, p))
        self.run_once()
        self.assertEqual(self.captures(), [])
        self.assertEqual(len(self.pi_posts("fail")), 1)
        self.assertEqual(self.pi_posts("start"), [])

    def test_crash_after_brain_post_reconciles_from_ledger(self):
        job, p = mkjob()
        self.queue((job, p))
        cfg, pi, brain = self.parts()
        with mock.patch.object(PiClient, "complete", side_effect=W.PiError(0, "unreachable:X")):
            W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)    # Pi lost mid-pass: pass stops
        self.assertEqual(len(self.captures()), 1)
        # simulate: crash happened after Brain accepted; ledger recorded delivered before complete was sent
        self.ledger.delivered(job["id"], "note-1")
        self.pi_state["unknown"] = [job]
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(len(self.captures()), 1)
        rec = self.pi_posts("reconcile")[-1][3]
        self.assertEqual((rec["action"], rec["result_ref"]), ("complete", "note-1"))

    def test_unknown_without_ledger_requeues(self):
        job, _ = mkjob()
        self.pi_state["unknown"] = [job]
        self.run_once()
        self.assertEqual(self.pi_posts("reconcile")[0][3]["action"], "requeue")
        self.assertEqual(self.captures(), [])


class TestDocs(Base):
    def doc(self, payload=b"# hello\n", key="dockey123456789012", kind="md", created="2026-03-04T10:00:00Z"):
        return mkjob(kind, key=key, payload=payload, created=created)

    def test_written_with_exact_name_and_completes(self):
        job, p = self.doc()
        self.queue((job, p))
        self.run_once()
        name = "2026-03-04 vnode-dockey1234567890.md"
        self.assertEqual(os.listdir(self.inbox), [name])
        self.assertEqual(open(os.path.join(self.inbox, name), "rb").read(), p)
        self.assertEqual(self.pi_posts("complete")[0][3]["result_ref"], name)
        self.assertEqual(self.captures(), [])

    def test_same_sha_existing_completes_without_rewrite(self):
        job, p = self.doc()
        path = os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md")
        open(path, "wb").write(p)
        before = os.stat(path)
        self.queue((job, p))
        self.run_once()
        after = os.stat(path)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assertEqual(len(self.pi_posts("complete")), 1)
        self.assertEqual(os.listdir(self.inbox), ["2026-03-04 vnode-dockey1234567890.md"])

    def test_different_sha_is_name_conflict_and_not_overwritten(self):
        job, p = self.doc()
        path = os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md")
        open(path, "wb").write(b"someone else's file")
        self.queue((job, p))
        self.run_once()
        f = self.pi_posts("fail")[0][3]
        self.assertEqual((f["error_code"], f["retryable"]), ("name_conflict", False))
        self.assertEqual(open(path, "rb").read(), b"someone else's file")
        self.assertEqual(os.listdir(self.inbox), ["2026-03-04 vnode-dockey1234567890.md"])   # no temp left behind

    def test_path_traversal_impossible(self):
        for key, created in (("../../../etc/evil-key123456", "2026-03-04"), ("dockey123456789012", "../../../x"),
                             ("dockey123456789012/../..", "2026-03-04")):
            job, p = self.doc(key=key, created=created)
            with self.assertRaises((W.Delivery, contracts.IntError)):
                W.deliver_doc(self.inbox, job, p)
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertEqual(os.listdir(self.tmp).count("etc"), 0)

    def test_symlinked_target_not_followed(self):
        outside = os.path.join(self.tmp, "outside.md")
        os.symlink(outside, os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md"))
        job, p = self.doc()
        with self.assertRaises(W.Delivery):
            W.deliver_doc(self.inbox, job, p)
        self.assertFalse(os.path.exists(outside))

    def test_unknown_doc_present_completes_absent_requeues(self):
        job, p = self.doc()
        self.pi_state["unknown"] = [job]
        self.run_once()
        self.assertEqual(self.pi_posts("reconcile")[0][3]["action"], "requeue")
        open(os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md"), "wb").write(p)
        self.run_once()
        rec = self.pi_posts("reconcile")[1][3]
        self.assertEqual((rec["action"], rec["result_ref"]), ("complete", "2026-03-04 vnode-dockey1234567890.md"))


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = os.path.join(self.tmp, "worker.env")

    def write(self, mode, brain_url="http://127.0.0.1:8000"):
        with open(self.env, "w") as f:
            f.write("VNODE_NODE_ID=%s\nVNODE_WORKER_TOKEN=%s\nBRAIN_VNODE_TOKEN=%s\nBRAIN_INBOX_PATH=%s\nBRAIN_URL=%s\n"
                    % ("a" * 64, PI_TOKEN, BRAIN_TOKEN, self.tmp, brain_url))
        os.chmod(self.env, mode)

    def test_0644_refused(self):
        self.write(0o644)
        with self.assertRaisesRegex(W.ConfigError, "0600"):
            W.load_config(self.env)

    def test_0600_ok_with_defaults(self):
        self.write(0o600)
        c = W.load_config(self.env)
        self.assertEqual((c.host, c.port), ("vnode.local", 8443))

    def test_non_loopback_brain_refused(self):
        for url in ("http://192.168.1.5:8000", "http://example.com", "https://127.0.0.1:8000", "https://example.com"):
            self.write(0o600, url)
            with self.assertRaisesRegex(W.ConfigError, "loopback"):
                W.load_config(self.env)

    def test_main_refuses_bad_env(self):
        self.write(0o644)
        self.assertEqual(W.main(["--once", "--env-file", self.env]), 78)


class TestLogs(Base):
    def test_no_tokens_or_payload_in_logs(self):
        job, p = mkjob()
        self.queue((job, p))
        cfg, pi, brain = self.parts()
        with self.assertLogs("vnode-worker", level="DEBUG") as cm:
            W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
            log = logging.getLogger("vnode-worker")
            log.info("sentinel")
        text = "\n".join(cm.output)
        for secret in (PI_TOKEN, BRAIN_TOKEN, SECRET_TEXT, job["claim_token"]):
            self.assertNotIn(secret, text)

    def test_pin_mismatch_main_logs_one_line_no_token(self):
        env = os.path.join(self.tmp, "w.env")
        with open(env, "w") as f:
            f.write("VNODE_HOST=127.0.0.1\nVNODE_PORT=%d\nVNODE_NODE_ID=%s\nVNODE_WORKER_TOKEN=%s\nBRAIN_VNODE_TOKEN=%s\n"
                    "BRAIN_INBOX_PATH=%s\nBRAIN_URL=http://127.0.0.1:%d\n"
                    % (self.pi_srv.port, _CERT["b"], PI_TOKEN, BRAIN_TOKEN, self.inbox, self.brain_port))
        os.chmod(env, 0o600)
        with mock.patch.dict(os.environ, {"HOME": os.path.join(self.tmp, "home")}):
            with self.assertLogs("vnode-worker", level="INFO") as cm:
                self.assertEqual(W.main(["--once", "--env-file", env]), 0)
        text = "\n".join(cm.output)
        self.assertIn("pin mismatch", text)
        self.assertNotIn(PI_TOKEN, text)
        self.assertEqual(self.pi_state["calls"], [])


if __name__ == "__main__":
    unittest.main()


class TestReviewFixes(Base):
    def test_classification(self):
        for code, retry in ((400, False), (413, False), (422, False), (401, True), (403, True), (404, True),
                            (408, True), (429, True), (500, True), (503, True), (409, True)):
            self.brain_state["capture_code"] = code
            with self.assertRaises(BrainError) as cm:
                self.parts()[2].capture_text("x", "k" * 16)
            self.assertEqual(cm.exception.retryable, retry, code)

    def test_auth_error_stops_claim_loop_and_flags_next_snapshot(self):
        a, ap = mkjob(key="authkey1234567890a")
        b, bp = mkjob(key="authkey1234567890b")
        self.queue((a, ap), (b, bp))
        self.brain_state["capture_code"] = 401
        cfg, pi, brain = self.parts()
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(len(self.captures()), 1)                       # second job never claimed
        self.assertEqual(len(self.pi_posts("claim")), 1)
        self.assertEqual(self.pi_posts("fail"), [])
        self.assertEqual(len(self.pi_posts("reconcile")), 1)             # requeued, attempt not burned
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        snap = self.pi_posts("brain-status")[-1][3]
        self.assertTrue(snap["auth_error"])

    def test_brain_5xx_and_404_stop_pass(self):
        for code in (500, 404, 408):
            self.pi_state["calls"].clear()
            self.brain_state["capture_code"] = code
            a, ap = mkjob()
            b, bp = mkjob()
            self.queue((a, ap), (b, bp))
            self.run_once()
            self.assertEqual(len(self.pi_posts("claim")), 1, code)
            self.assertEqual(self.pi_posts("fail"), [], code)
            self.assertEqual(self.pi_posts("reconcile")[0][3]["action"], "requeue", code)
            self.pi_state["queue"].clear()

    def test_brain_400_continues_pass(self):
        self.brain_state["capture_code"] = 400
        self.queue(mkjob(), mkjob())
        self.run_once()
        self.assertEqual(len(self.captures()), 2)
        self.assertEqual(len(self.pi_posts("fail")), 2)

    def test_auth_error_cleared_after_success(self):
        cfg, pi, brain = self.parts()
        self.brain_state["status_code"] = 403
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertTrue(self.pi_posts("brain-status")[-1][3]["auth_error"])
        self.brain_state["status_code"] = 200
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)   # snapshot taken before this pass's status ok
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertFalse(self.pi_posts("brain-status")[-1][3]["auth_error"])

    def test_deliver_doc_oserror_is_retryable_write_failed(self):
        job, p = mkjob("md", key="dockey123456789012", payload=b"# x")
        for target in ("tempfile.mkstemp", "os.path.exists", "os.path.realpath"):
            with mock.patch(target, side_effect=OSError("boom")):
                with self.assertRaises(W.Delivery) as cm:
                    W.deliver_doc(self.inbox, job, p)
            self.assertEqual((cm.exception.code, cm.exception.retryable), ("write_failed", True), target)
        open(os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md"), "wb").write(p)
        with mock.patch.object(W, "_sha_file", side_effect=OSError("boom")):
            with self.assertRaises(W.Delivery) as cm:
                W.deliver_doc(self.inbox, job, p)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("write_failed", True))

    def test_doc_name_uses_16_chars(self):
        job, _ = mkjob("md", key="dockey123456789012")
        self.assertEqual(W.doc_name(job), "2026-03-04 vnode-dockey1234567890.md")

    def test_unexpected_exception_fails_job_and_pass_continues(self):
        a, ap = mkjob(key="boomkey1234567890a")
        b, bp = mkjob(key="boomkey1234567890b")
        self.queue((a, ap), (b, bp))
        real = Ledger.intent
        calls = []

        def flaky(self_, *args):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("disk gone")
            return real(self_, *args)
        with mock.patch.object(Ledger, "intent", flaky), self.assertLogs("vnode-worker", "ERROR") as cm:
            self.run_once()
        f = self.pi_posts("fail")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0][3]["error_code"], f[0][3]["retryable"]), ("worker_error", True))
        self.assertEqual(len(self.pi_posts("complete")), 1)            # second job still processed
        self.assertTrue(any(a["id"] in "\n".join(cm.output) for a in (a,)))
        self.assertTrue(any(r.exc_info for r in cm.records))

    def test_pi_error_on_one_job_does_not_abort_pass(self):
        a, ap = mkjob(key="pierrkey1234567890a")
        b, bp = mkjob(key="pierrkey1234567890b")
        self.queue((a, ap), (b, bp))
        self.pi_state["route_status"] = {"/%s/start" % a["id"]: 500}
        with self.assertLogs("vnode-worker", "WARNING") as cm:
            self.run_once()
        self.assertEqual(self.captures().__len__(), 1)
        self.assertEqual(len(self.pi_posts("complete")), 1)
        self.assertTrue(any(a["id"] in line for line in cm.output))

    def test_pi_unreachable_mid_pass_stops(self):
        a, ap = mkjob()
        b, bp = mkjob()
        self.queue((a, ap), (b, bp))
        cfg, pi, brain = self.parts()
        with mock.patch.object(type(pi), "start", side_effect=W.PiError(0, "unreachable:X")):
            W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(len(self.pi_posts("claim")), 1)

    def test_ledger_delivered_failure_still_completes(self):
        job, p = mkjob()
        self.queue((job, p))
        with mock.patch.object(Ledger, "delivered", side_effect=RuntimeError("ledger")), \
                self.assertLogs("vnode-worker", "ERROR") as cm:
            self.run_once()
        self.assertEqual(len(self.captures()), 1)
        self.assertEqual(len(self.pi_posts("complete")), 1)
        self.assertEqual(self.pi_posts("fail"), [])
        self.assertTrue(any(r.exc_info for r in cm.records))

    def test_dry_run_reconcile_unknown_does_not_write(self):
        job, _ = mkjob()
        self.pi_state["unknown"] = [job]
        with self.assertLogs("vnode-worker", "INFO") as cm:
            self.run_once(live=False)
        self.assertEqual(self.pi_posts("reconcile"), [])
        self.assertTrue(any("requeue" in line and job["id"] in line for line in cm.output))

    def test_dry_run_claims_one_requeues_warns_once(self):
        self.queue(mkjob(), mkjob())
        with self.assertLogs("vnode-worker", "WARNING") as cm:
            self.run_once(live=False)
        self.assertEqual(len(self.pi_posts("claim")), 1)
        self.assertEqual(len(self.pi_posts("reconcile")), 1)
        warns = [r for r in cm.records if "jobs are waiting and will not be delivered" in r.getMessage()]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0].levelno, logging.WARNING)

    def test_mode_in_heartbeat_and_snapshot(self):
        self.run_once(live=False)
        self.run_once(live=True)
        hb = self.pi_posts("heartbeat")
        self.assertEqual([c[3]["mode"] for c in hb], ["dry_run", "live"])
        self.assertEqual([c[3]["mode"] for c in self.pi_posts("brain-status")], ["dry_run", "live"])


class TestInstaller(unittest.TestCase):
    def run_install(self, home):
        env = dict(os.environ, HOME=home, VHOME_NO_LAUNCHCTL="1")
        r = subprocess.run(["bash", os.path.join(os.path.dirname(__file__), "..", "install-worker.sh")],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_rerun_keeps_live_flag(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        out = self.run_install(home)
        self.assertIn("dry run", out.lower())
        agent = os.path.join(home, "Library/LaunchAgents/com.designinnsaeit.vhome-int-worker.plist")
        self.assertNotIn("--live", open(agent).read())
        s = open(agent).read().replace("<string>vhome_companion.integrations.worker.main</string>",
                                       "<string>vhome_companion.integrations.worker.main</string>\n    <string>--live</string>")
        open(agent, "w").write(s)
        out = self.run_install(home)
        self.assertIn("LIVE", out)
        self.assertEqual(open(agent).read().count("--live"), 1)
        self.assertEqual(subprocess.run(["plutil", "-lint", agent], capture_output=True).returncode, 0) \
            if shutil.which("plutil") else None


class TestAccessBlocked(Base):
    """F1: a Cloudflare Access redirect must not freeze delivery, and must read as a config problem."""

    def test_3xx_is_access_blocked_unit(self):
        self.brain_state["redirect"] = ["/api/status", "/api/capture"]
        brain = self.parts()[2]
        with self.assertRaises(BrainError) as cm:
            brain.status()
        e = cm.exception
        self.assertEqual((e.code, e.status, e.retryable), ("access_blocked", 302, True))
        self.assertTrue(stops_pass(e))
        self.assertTrue(brain.auth_error)
        self.assertIn("Cloudflare Access", explain(e))

    def test_200_html_login_page_is_access_blocked(self):
        self.brain_state["html"] = ["/api/capture"]
        with self.assertRaises(BrainError) as cm:
            self.parts()[2].capture_text("x", "k" * 16)
        self.assertEqual(cm.exception.code, "access_blocked")

    def test_status_blocked_but_capture_open_still_delivers(self):
        self.brain_state["redirect"] = ["/api/status", "/api/failed"]
        job, p = mkjob()
        self.queue((job, p))
        self.run_once()
        self.assertEqual(len(self.captures()), 1)
        self.assertEqual(len(self.pi_posts("complete")), 1)
        first, last = self.pi_posts("brain-status")[0][3], self.pi_posts("brain-status")[-1][3]
        self.assertTrue(first["auth_error"])                         # honest at pass start
        self.assertEqual((last["reachable"], last["auth_error"]), (True, False))   # corrected by the capture

    def test_capture_blocked_requeues_with_plain_message_and_burns_nothing(self):
        self.brain_state["redirect"] = ["/api/status", "/api/capture"]
        a, ap = mkjob()
        b, bp = mkjob()
        self.queue((a, ap), (b, bp))
        self.run_once()
        self.assertEqual(self.pi_posts("fail"), [])
        self.assertEqual(len(self.pi_posts("claim")), 1)             # pass stopped
        rec = self.pi_posts("reconcile")
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0][3]["action"], rec[0][3]["error_code"]), ("requeue", "access_blocked"))
        self.assertEqual(rec[0][3]["error_msg"], "Brain's login page (Cloudflare Access) is blocking VNode. "
                                                  "Add the path to the Access bypass.")
        self.assertTrue(self.pi_posts("brain-status")[-1][3]["auth_error"])

    def test_status_blocked_does_not_gate_claiming(self):
        self.brain_state["redirect"] = ["/api/status"]
        self.queue(mkjob())
        self.run_once()
        self.assertEqual(len(self.pi_posts("claim")), 2)             # claimed the job, then found the queue empty

    def test_cf_access_headers_sent_on_every_brain_call(self):
        self.queue(mkjob())
        cfg, _, _ = self.parts()
        brain = BrainClient(cfg.brain_url, cfg.brain_token, cf_id="id123.access", cf_secret="s3cr3t")
        W.run_once(cfg, PiClient(cfg.host, cfg.port, cfg.node_id, cfg.pi_token), brain, self.ledger, True, sleep=lambda s: None)
        hdrs = self.brain_state["hdrs"]
        self.assertEqual(len(hdrs), 2)                                # status + capture
        for h in hdrs:
            self.assertEqual((h["CF-Access-Client-Id"], h["CF-Access-Client-Secret"]), ("id123.access", "s3cr3t"))
        self.assertNotIn("CF-Access-Client-Id", self.parts()[2].cf)


class TestRequeueNotFail(Base):
    """F2: auth/transport/5xx never burn an attempt; only 400/413/422 fail the job."""

    def test_soft_errors_requeue(self):
        for code in (401, 403, 404, 408, 429, 500, 502, 503):
            self.pi_state["calls"].clear()
            self.brain_state["capture_code"] = code
            self.queue(mkjob())
            self.run_once()
            self.assertEqual(self.pi_posts("fail"), [], code)
            rec = self.pi_posts("reconcile")
            self.assertEqual((len(rec), rec[0][3]["action"], rec[0][3]["error_code"]), (1, "requeue", "brain_http_%d" % code), code)

    def test_hard_errors_fail_without_retry(self):
        for code in (400, 413, 422):
            self.pi_state["calls"].clear()
            self.brain_state["capture_code"] = code
            self.queue(mkjob())
            self.run_once()
            f = self.pi_posts("fail")
            self.assertEqual((len(f), f[0][3]["retryable"]), (1, False), code)
            self.assertEqual(self.pi_posts("reconcile"), [], code)

    def test_brain_dies_between_status_and_capture_requeues(self):
        self.queue(mkjob())
        cfg, pi, brain = self.parts()
        with mock.patch.object(BrainClient, "capture_text", side_effect=BrainError(True, 0, "unreachable:X")):
            W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(self.pi_posts("fail"), [])
        self.assertEqual(self.pi_posts("reconcile")[0][3]["action"], "requeue")

    def test_error_text_is_plain_and_what_is_redacted(self):
        self.brain_state["capture_code"] = 401
        self.queue(mkjob())
        self.run_once()
        self.assertEqual(self.pi_posts("reconcile")[0][3]["error_msg"],
                         "Brain refused VNode's token. Re-issue it on Brain and update VNode.")
        self.pi_state["calls"].clear()
        self.brain_state["capture_code"] = 500
        self.brain_state["capture_err"] = {"what": "vault locked\ntoken=hunter2 try later", "error": "x"}
        self.queue(mkjob())
        self.run_once()
        msg = self.pi_posts("reconcile")[0][3]["error_msg"]
        self.assertIn("Brain said: vault locked", msg)
        self.assertNotIn("hunter2", msg)
        self.assertNotIn("\n", msg)
        self.assertLessEqual(len(msg), contracts.MAX_ERROR_MSG)

    def test_hard_error_text_includes_brain_reason(self):
        self.brain_state["capture_code"] = 422
        self.brain_state["capture_err"] = {"error": {"what": "text too long", "code": "too_long"}}   # Brain's real envelope
        self.queue(mkjob())
        self.run_once()
        self.assertEqual(self.pi_posts("fail")[0][3]["error_msg"], "Brain did not accept this item (HTTP 422). Brain said: text too long")

    def test_delivery_errors_are_plain_sentences(self):
        job, p = mkjob("md", key="dockey123456789012", payload=b"# x")
        open(os.path.join(self.inbox, "2026-03-04 vnode-dockey1234567890.md"), "wb").close()
        self.queue((job, p))
        self.run_once()
        f = self.pi_posts("fail")[0][3]
        self.assertEqual(f["error_code"], "name_conflict")
        self.assertIn("already in Brain's inbox folder", f["error_msg"])
        self.assertNotEqual(f["error_msg"], "name_conflict")
        self.assertIn("could not write", W.DELIVERY_TEXT["write_failed"])

    def test_same_job_failing_8_times_with_5xx_is_failed_retryable_others_uncapped(self):
        W._SOFT.clear()
        self.brain_state["capture_code"] = 500
        job, p = mkjob()
        other, op = mkjob()
        cfg, pi, brain = self.parts()
        for n in range(7):
            self.pi_state["queue"].append(job)
            self.pi_state["payloads"][job["id"]] = p
            W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(self.pi_posts("fail"), [])                  # 7 requeues, still nothing burned
        self.pi_state["queue"].append(job)
        W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        f = self.pi_posts("fail")
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0][3]["retryable"])
        self.assertEqual(f[0][3]["error_msg"], "Brain kept failing on this item. Tap Retry later, or check Brain's Integrations page.")
        self.assertEqual(f[0][3]["error_code"], "brain_http_500")
        # counter was reset; a different failure kind in between also resets it
        self.assertNotIn(job["id"], W._SOFT)

    def test_auth_access_and_transport_errors_never_count(self):
        W._SOFT.clear()
        job, p = mkjob()
        cfg, pi, brain = self.parts()
        for code in (401, 403, 503):
            self.brain_state["capture_code"] = code
            for _ in range(10 if code != 503 else 3):
                self.pi_state["queue"].append(job)
                self.pi_state["payloads"][job["id"]] = p
                W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(self.pi_posts("fail"), [])
        self.assertEqual(W._SOFT.get(job["id"]), 3)                  # only the 503s counted, 401/403 reset the run

    def test_requeue_backs_polling_off(self):
        self.brain_state["capture_code"] = 503
        self.queue(mkjob())
        cfg, pi, brain = self.parts()
        self.assertTrue(W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None))
        self.assertFalse(W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None))   # queue empty now


class TestHttpsAllowHost(Base):
    """F10: https only to the one host the owner named, with real certificate checks."""

    def test_parse_url_rules(self):
        self.assertEqual(parse_url("http://127.0.0.1:8000"), ("http", "127.0.0.1", 8000))
        self.assertEqual(parse_url("https://cockpit.vineethnair.com", "cockpit.vineethnair.com"),
                         ("https", "cockpit.vineethnair.com", 443))
        self.assertEqual(parse_url("https://Cockpit.VineethNair.com:8443/x", "cockpit.vineethnair.com")[2], 8443)
        for url, allow in (("https://cockpit.vineethnair.com", ""), ("https://cockpit.vineethnair.com", "other.example.com"),
                           ("https://evil.cockpit.vineethnair.com", "cockpit.vineethnair.com"),
                           ("http://cockpit.vineethnair.com", "cockpit.vineethnair.com"),    # never clear text off-box
                           ("https://user:pw@cockpit.vineethnair.com", "cockpit.vineethnair.com"),
                           ("ftp://127.0.0.1", ""), ("https://", "x")):
            with self.assertRaises(ValueError, msg=url):
                parse_url(url, allow)

    def test_config_accepts_https_only_with_matching_allow_host(self):
        base = {"VNODE_NODE_ID": "a" * 64, "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_VNODE_TOKEN": BRAIN_TOKEN,
                "BRAIN_URL": "https://cockpit.vineethnair.com"}
        W.Config(dict(base, BRAIN_ALLOW_HOST="cockpit.vineethnair.com"))
        for allow in ("", "other.example.com"):
            with self.assertRaisesRegex(W.ConfigError, "loopback"):
                W.Config(dict(base, BRAIN_ALLOW_HOST=allow))
        with self.assertRaisesRegex(W.ConfigError, "both CF_ACCESS"):
            W.Config(dict(base, BRAIN_ALLOW_HOST="cockpit.vineethnair.com", CF_ACCESS_CLIENT_ID="x"))

    def https_brain(self, ctx=None):
        srv = make_brain(self.brain_state, tls="c")
        self.addCleanup(srv.stop)
        return BrainClient("https://localhost:%d" % srv.port, BRAIN_TOKEN, allow_host="localhost", ssl_context=ctx,
                           cf_id="cid", cf_secret="csec")

    def test_default_verification_rejects_untrusted_cert_and_sends_nothing(self):
        brain = self.https_brain()
        with self.assertRaises(BrainError) as cm:
            brain.capture_text("hello", "k" * 16)
        self.assertEqual((cm.exception.status, cm.exception.code), (0, "unreachable:SSLCertVerificationError"))
        self.assertEqual(self.brain_state["calls"], [])               # bearer token never left the box

    def test_trusted_cert_delivers_over_https(self):
        brain = self.https_brain(ssl.create_default_context(cafile="%s/c.pem" % _CERT["dir"]))
        self.assertEqual(brain.capture_text("hello", "k" * 16), "note-1")
        c = self.captures()[0]
        self.assertEqual((c[3], c[4]), ("Bearer " + BRAIN_TOKEN, {"text": "hello"}))
        self.assertEqual(self.brain_state["hdrs"][0]["CF-Access-Client-Id"], "cid")


class TestDocsAsText(Base):
    """No BRAIN_INBOX_PATH (the Pi): md/txt travel as capture text; the job key stays the capture key."""

    def setUp(self):
        super().setUp()
        cfg, self.pi, self.brain = self.parts()
        env = {"VNODE_HOST": "127.0.0.1", "VNODE_PORT": str(self.pi_srv.port), "VNODE_NODE_ID": self.node_id,
               "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_URL": "http://127.0.0.1:%d" % self.brain_port, "BRAIN_VNODE_TOKEN": BRAIN_TOKEN}
        self.cfg = W.Config(env)                       # note: no BRAIN_INBOX_PATH
        self.assertEqual(self.cfg.inbox, "")

    def go(self, *jobs):
        self.queue(*jobs)
        W.run_once(self.cfg, self.pi, self.brain, self.ledger, True, sleep=lambda s: None)

    def test_md_and_txt_sent_as_text_with_job_key(self):
        md, mp = mkjob("md", key="mdkey1234567890abc", payload=b"# Title\nbody\n")
        tx, tp = mkjob("txt", key="txtkey123456789abc", payload="plain \u2603 note".encode())
        self.go((md, mp), (tx, tp))
        caps = self.captures()
        self.assertEqual([c[2] for c in caps], ["mdkey1234567890abc", "txtkey123456789abc"])
        self.assertEqual([c[4] for c in caps], [{"text": "# Title\nbody\n"}, {"text": "plain \u2603 note"}])
        self.assertEqual([c[3]["result_ref"] for c in self.pi_posts("complete")], ["note-1", "note-2"])
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertEqual(self.ledger.get(md["id"])["state"], "delivered")

    def test_label_becomes_title_only_when_there_is_no_heading(self):
        a, ap = mkjob("txt", key="lblkey1234567890a1", payload=b"no heading here", label="Trip notes")
        b, bp = mkjob("md", key="lblkey1234567890b2", payload=b"intro\n\n## Real heading\n", label="Ignored")
        self.go((a, ap), (b, bp))
        self.assertEqual([c[4]["text"] for c in self.captures()], ["# Trip notes\n\nno heading here", "intro\n\n## Real heading\n"])

    def test_unreadable_doc_fails_without_retry(self):
        job, p = mkjob("md", key="badkey1234567890ab", payload=b"\xff\xfe")
        self.go((job, p))
        f = self.pi_posts("fail")[0][3]
        self.assertEqual((f["error_code"], f["retryable"]), ("bad_payload", False))
        self.assertEqual(self.captures(), [])

    def test_unknown_doc_requeues_without_inbox(self):
        job, _ = mkjob("md", key="unkkey1234567890ab")
        self.pi_state["unknown"] = [job]
        W.run_once(self.cfg, self.pi, self.brain, self.ledger, True, sleep=lambda s: None)
        self.assertEqual(self.pi_posts("reconcile")[0][3]["action"], "requeue")


class TestPiLocalSocket(Base):
    """The worker on the Pi: same PiClient methods over int.sock, no TLS, no pin."""

    def setUp(self):
        super().setUp()
        self.sockdir = tempfile.mkdtemp(prefix="vh")
        self.addCleanup(shutil.rmtree, self.sockdir, True)
        self.path = os.path.join(self.sockdir, "int.sock")
        self.unix_srv = make_pi(self.pi_state, tls=None, unix=self.path)
        self.addCleanup(self.unix_srv.stop)
        self.cfg = W.Config({"VNODE_SOCKET": self.path, "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_VNODE_TOKEN": BRAIN_TOKEN,
                             "BRAIN_URL": "http://127.0.0.1:%d" % self.brain_port, "WORKER_NAME": "pi-deliver",
                             "WORKER_MAX_PER_RUN": "5", "WORKER_POLL_S": "60"})

    def test_config_needs_no_node_id_and_picks_unix_client(self):
        self.assertIsInstance(self.cfg.pi_client(), UnixPiClient)
        self.assertEqual((self.cfg.poll_s, self.cfg.max_per_run, self.cfg.name), (60.0, 5, "pi-deliver"))
        with self.assertRaisesRegex(W.ConfigError, "absolute"):
            W.Config({"VNODE_SOCKET": "int.sock", "VNODE_WORKER_TOKEN": "t", "BRAIN_VNODE_TOKEN": "b"})
        with self.assertRaisesRegex(W.ConfigError, "VNODE_NODE_ID"):
            W.Config({"VNODE_WORKER_TOKEN": "t", "BRAIN_VNODE_TOKEN": "b"})

    def test_full_pass_over_unix_socket(self):
        job, p = mkjob()
        self.queue((job, p), (self.doc_job()))
        W.run_once(self.cfg, self.cfg.pi_client(), self.cfg.brain_client(), self.ledger, True, sleep=lambda s: None)
        self.assertEqual(len(self.captures()), 2)
        self.assertEqual(len(self.pi_posts("complete")), 2)
        self.assertTrue(all(c[2] == "Bearer " + PI_TOKEN for c in self.pi_state["calls"]))
        self.assertEqual(self.pi_posts("claim")[0][3], {"worker": "pi-deliver"})

    def doc_job(self):
        return mkjob("md", key="sockdoc1234567890a", payload=b"# doc\n")

    def test_max_per_run_respected(self):
        self.queue(*[mkjob() for _ in range(7)])
        W.run_once(self.cfg, self.cfg.pi_client(), self.cfg.brain_client(), self.ledger, True, sleep=lambda s: None)
        self.assertEqual(len(self.captures()), 5)
        self.assertEqual(len(self.pi_state["queue"]), 2)

    def test_missing_socket_is_a_pi_error_not_a_crash(self):
        pi = UnixPiClient(os.path.join(self.sockdir, "nope.sock"), PI_TOKEN)
        with self.assertRaises(PiError) as cm:
            pi.claim("w")
        self.assertEqual(cm.exception.status, 0)


class TestPiHomeMain(Base):
    def test_waits_for_clock_before_any_brain_call(self):
        cfg = W.Config({"VNODE_SOCKET": "/x/int.sock", "VNODE_WORKER_TOKEN": "t", "BRAIN_VNODE_TOKEN": "b",
                        "WAIT_CLOCK_SYNC": "1"})
        def tdc(out, rc=0):
            return mock.Mock(return_value=mock.Mock(returncode=rc, stdout=out))
        with mock.patch.object(W.os.path, "exists", return_value=False):
            with mock.patch.object(W.subprocess, "run", tdc("no\n")):
                self.assertFalse(W.clock_ready(cfg))
            with mock.patch.object(W.subprocess, "run", side_effect=FileNotFoundError):
                self.assertFalse(W.clock_ready(cfg))
            with mock.patch.object(W.subprocess, "run", tdc("yes\n")) as run:     # chrony etc: timedatectl says synced
                self.assertTrue(W.clock_ready(cfg))
            self.assertEqual(run.call_args[0][0], ["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
        with mock.patch.object(W.os.path, "exists", return_value=True):
            self.assertTrue(W.clock_ready(cfg))
        self.assertTrue(W.clock_ready(W.Config({"VNODE_SOCKET": "/x/int.sock", "VNODE_WORKER_TOKEN": "t", "BRAIN_VNODE_TOKEN": "b"})))

    def test_main_from_env_runs_one_pass_with_state_directory_ledger(self):
        sockdir = tempfile.mkdtemp(prefix="vh")
        self.addCleanup(shutil.rmtree, sockdir, True)
        path = os.path.join(sockdir, "int.sock")
        srv = make_pi(self.pi_state, tls=None, unix=path)
        self.addCleanup(srv.stop)
        job, p = mkjob()
        self.queue((job, p))
        state = os.path.join(self.tmp, "state")
        env = {"VNODE_SOCKET": path, "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_VNODE_TOKEN": BRAIN_TOKEN, "STATE_DIRECTORY": state,
               "BRAIN_URL": "http://127.0.0.1:%d" % self.brain_port, "WORKER_NAME": "pi-deliver"}
        with mock.patch.dict(os.environ, env, clear=True), self.assertLogs("vnode-worker", "INFO"):
            self.assertEqual(W.main(["--live", "--once", "--from-env"]), 0)
        self.assertEqual(len(self.captures()), 1)
        self.assertTrue(os.path.exists(os.path.join(state, "delivered.db")))

    def test_main_from_env_missing_config_exits_78(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(W.main(["--once", "--from-env"]), 78)


class TestReviewRound(Base):
    """Independent review fixes: caps, wording, secret scrubbing, redirects, URL strictness, main-loop timing."""

    def test_soft_cap_covers_404_408_429_and_bad_json_not_auth(self):
        for kind in ((404, "http_404"), (408, "http_408"), (429, "http_429"), (200, "bad_json")):
            W._SOFT.clear()
            self.pi_state["calls"].clear()
            job, p = mkjob()
            cfg, pi, brain = self.parts()
            err = BrainError(True, kind[0], kind[1])
            with mock.patch.object(BrainClient, "capture_text", side_effect=err):
                for n in range(8):
                    self.pi_state["queue"].append(job)
                    self.pi_state["payloads"][job["id"]] = p
                    W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
            f = self.pi_posts("fail")
            self.assertEqual(len(f), 1, kind)
            self.assertTrue(f[0][3]["retryable"], kind)
            self.assertEqual(len(self.pi_posts("reconcile")), 7, kind)

    def test_retryable_non_5xx_wording(self):
        self.assertEqual(explain(BrainError(True, 404, "http_404")), "Brain didn't take this yet \u2014 VNode will try again.")
        self.assertEqual(explain(BrainError(True, 429, "http_429", "slow down")),
                         "Brain didn't take this yet \u2014 VNode will try again. Brain said: slow down")
        self.assertIn("did not accept", explain(BrainError(False, 422, "http_422")))

    def test_only_login_redirect_statuses_are_access_blocked(self):
        for code in (301, 302, 303, 307, 308):
            self.brain_state["redirect"] = ["/api/status"]
            self.brain_state["redirect_code"] = code
            with self.assertRaises(BrainError) as cm:
                self.parts()[2].status()
            self.assertEqual(cm.exception.code, "access_blocked", code)
        self.brain_state["redirect_code"] = 304
        with self.assertRaises(BrainError) as cm:
            self.parts()[2].status()
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("http_304", True))

    def test_literal_tokens_scrubbed_from_brain_what(self):
        self.brain_state["capture_code"] = 500
        self.brain_state["capture_err"] = {"error": {"what": "echo %s and %s and %s" % (BRAIN_TOKEN, "cfsec-9999", "cfid-1234")}}
        cfg = self.parts()[0]
        brain = BrainClient(cfg.brain_url, BRAIN_TOKEN, cf_id="cfid-1234", cf_secret="cfsec-9999")
        with self.assertRaises(BrainError) as cm:
            brain.capture_text("x", "k" * 16)
        for secret in (BRAIN_TOKEN, "cfsec-9999", "cfid-1234"):
            self.assertNotIn(secret, cm.exception.what)
            self.assertNotIn(secret, explain(cm.exception))
        self.assertIn("<redacted>", cm.exception.what)

    def test_parse_url_is_strict(self):
        ok = "cockpit.vineethnair.com"
        for url, allow in (("https://cockpit.vineethnair.com./x", ok), ("https://cockpit.vineethnair.com.", ok + "."),
                           ("https://cockpit.vineethnair.com", ok + "."),            # trailing dot never matches
                           ("https://cockpit.vineethnair.com", ok + ":443"),          # allow host is a bare host
                           ("https://cockpit.vineethnair.com", ok + "/"),
                           ("https://b\u00fccher.example", "b\u00fccher.example"),     # international names: use xn--
                           ("https://xn--bcher-kva.example", "b\u00fccher.example"),
                           ("https://cockpit.vineethnair.com\\@evil.example", ok),
                           ("https://evil.example\\.cockpit.vineethnair.com", ok),
                           ("https://cockpit.vineethnair.com\n", ok), ("https://a..b.example", "a..b.example"),
                           ("https://-bad.example", "-bad.example"), ("https:// cockpit.vineethnair.com", ok)):
            with self.assertRaises(ValueError, msg=url):
                parse_url(url, allow)
        self.assertEqual(parse_url("https://xn--bcher-kva.example:8443/a", "xn--bcher-kva.example"),
                         ("https", "xn--bcher-kva.example", 8443))
        self.assertEqual(parse_url("https://COCKPIT.vineethnair.com", "Cockpit.VineethNair.com")[1], ok)

    def test_brain_timeout_is_20s(self):
        from vhome_companion.integrations.worker import brain_client as bc
        self.assertEqual(bc.TIMEOUT_S, 20)
        self.assertEqual(self.parts()[2].timeout, 20)


class TestMainLoopTiming(Base):
    class Stop(Exception):
        pass

    def run_main(self, run_once=None, clock=True, poll="60"):
        sockdir = tempfile.mkdtemp(prefix="vh")
        self.addCleanup(shutil.rmtree, sockdir, True)
        env = {"VNODE_SOCKET": os.path.join(sockdir, "int.sock"), "VNODE_WORKER_TOKEN": PI_TOKEN, "BRAIN_VNODE_TOKEN": BRAIN_TOKEN,
               "STATE_DIRECTORY": os.path.join(self.tmp, "st"), "WORKER_POLL_S": poll, "WAIT_CLOCK_SYNC": "1"}
        waits = []

        def fake_sleep(s):
            waits.append(s)
            if len(waits) >= 4:
                raise self.Stop
        hb = mock.Mock()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(W.time, "sleep", fake_sleep), \
                mock.patch.object(W, "clock_ready", return_value=clock), \
                mock.patch.object(W, "run_once", run_once or mock.Mock(return_value=False)) as ro, \
                mock.patch.object(UnixPiClient, "heartbeat", hb), self.assertLogs("vnode-worker", "INFO") as cm:
            with self.assertRaises(self.Stop):
                W.main(["--live", "--from-env"])
        return waits, ro, hb, cm.output

    def test_backoff_is_capped_below_worker_stale(self):
        waits, ro, _, _ = self.run_main(mock.Mock(return_value=True))
        self.assertEqual(waits, [120.0, 150.0, 150.0, 150.0])
        self.assertLess(max(waits), contracts.WORKER_STALE_S)
        self.assertEqual(ro.call_count, 4)                     # run_once (which sends the heartbeat) ran every cycle

    def test_healthy_polls_at_the_configured_rate(self):
        waits, _, _, _ = self.run_main(mock.Mock(return_value=False))
        self.assertEqual(waits, [60.0] * 4)

    def test_clock_wait_checks_every_30s_heartbeats_and_logs_once(self):
        waits, ro, hb, out = self.run_main(clock=False)
        self.assertEqual(waits, [30.0] * 4)
        self.assertEqual(ro.call_count, 0)                     # nothing sent to Brain
        self.assertEqual(hb.call_count, 4)                     # but the phone still sees a live worker
        self.assertEqual(len([l for l in out if "waiting for the clock" in l]), 1)

    def test_steady_conditions_log_once(self):
        cfg, pi, brain = self.parts(brain_port=dead_port())
        with self.assertLogs("vnode-worker", "INFO") as cm:
            for _ in range(3):
                W.run_once(cfg, pi, brain, self.ledger, True, sleep=lambda s: None)
            logging.getLogger("vnode-worker").info("sentinel")
        self.assertEqual(len([l for l in cm.output if "brain unreachable" in l]), 1)
