"""Worker -> Pi client. Stdlib only. One connection per request.

PiClient: TLS to the node, pinned by cert sha256 (Mac worker).
UnixPiClient: the node's own int.sock (worker running on the Pi): same methods, no TLS, no proxy."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import ssl

from .. import contracts

TIMEOUT_S = 10


class PinMismatch(Exception):
    pass


class PiError(Exception):
    """Pi answered non-2xx (status, code from the v1 envelope) or could not be reached (status 0)."""

    def __init__(self, status: int, code: str = ""):
        super().__init__("pi %s %s" % (status, code))
        self.status, self.code = status, code


class PayloadMismatch(Exception):
    pass


class PiClient:
    def __init__(self, host: str, port: int, node_id: str, token: str, timeout: float = TIMEOUT_S):
        self.host, self.port, self.pin, self.token, self.timeout = host, port, node_id.lower(), token, timeout
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False          # identity is the cert pin, not a hostname (IP / mDNS both work)
        ctx.verify_mode = ssl.CERT_NONE
        self._ctx = ctx

    def _connect(self) -> http.client.HTTPSConnection:
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self._ctx)
        try:
            conn.connect()
            der = conn.sock.getpeercert(binary_form=True)
        except (OSError, ssl.SSLError, http.client.HTTPException) as e:
            conn.close()
            raise PiError(0, "unreachable:%s" % type(e).__name__) from None
        # pin check BEFORE any request bytes: the bearer token never reaches an unpinned peer
        if not der or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self.pin):
            conn.close()
            raise PinMismatch("pi certificate does not match VNODE_NODE_ID")
        return conn

    def _req(self, method: str, path: str, body: dict | None = None, extra_headers: dict | None = None):
        conn = self._connect()
        try:
            data = None if body is None else json.dumps(body).encode()
            headers = {"Authorization": "Bearer " + self.token}
            headers.update(extra_headers or {})
            if data is not None:
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, contracts.WORKER_PREFIX + path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(contracts.MAX_DOC + 4096)
            except (OSError, ssl.SSLError, http.client.HTTPException, socket.timeout) as e:
                raise PiError(0, "unreachable:%s" % type(e).__name__) from None
            if resp.status >= 300:
                try:
                    code = str(json.loads(raw).get("error", ""))[:40]
                except (ValueError, AttributeError):
                    code = ""
                raise PiError(resp.status, code)
            return resp, raw
        finally:
            conn.close()

    def _json(self, method, path, body=None) -> dict:
        _, raw = self._req(method, path, body)
        try:
            out = json.loads(raw) if raw else {}
        except ValueError:
            raise PiError(0, "bad_json") from None
        return out if isinstance(out, dict) else {}

    def heartbeat(self, worker: str, version: str, mode: str = "live"):
        self._req("POST", "heartbeat", {"worker": worker, "version": version, "mode": mode})

    def brain_status(self, snapshot: dict):
        self._req("POST", "brain-status", snapshot)

    def claim(self, worker: str):
        return self._json("POST", "claim", {"worker": worker}).get("job")

    def payload(self, job_id: str, claim_token: str, expected_sha: str) -> bytes:
        resp, raw = self._req("GET", "jobs/%s/payload" % job_id, extra_headers={contracts.CLAIM_HEADER: claim_token})
        got = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(got, str(expected_sha).lower()):
            raise PayloadMismatch("payload sha256 differs from job.payload_sha256")
        return raw

    def start(self, job_id, claim_token):
        return self._json("POST", "jobs/%s/start" % job_id, {"claim_token": claim_token})

    def complete(self, job_id, claim_token, result_ref=None):
        body = {"claim_token": claim_token}
        if result_ref:
            body["result_ref"] = str(result_ref)[:contracts.MAX_RESULT_REF]
        self._req("POST", "jobs/%s/complete" % job_id, body)

    def fail(self, job_id, claim_token, error_code, error_msg, retryable):
        self._req("POST", "jobs/%s/fail" % job_id, {
            "claim_token": claim_token, "error_code": error_code,
            "error_msg": contracts.redact(error_msg)[:contracts.MAX_ERROR_MSG], "retryable": bool(retryable)})

    def unknown(self) -> list:
        return self._json("GET", "unknown").get("jobs") or []

    def reconcile(self, job_id, claim_token, action, result_ref=None, error_code=None, error_msg=None):
        body = {"job_id": job_id, "claim_token": claim_token, "action": action}
        if result_ref:
            body["result_ref"] = str(result_ref)[:contracts.MAX_RESULT_REF]
        if error_code:
            body["error_code"] = error_code
            body["error_msg"] = contracts.redact(error_msg or "")[:contracts.MAX_ERROR_MSG]
        self._req("POST", "reconcile", body)


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect(self._path)
        except OSError:
            self.sock.close()
            raise


class UnixPiClient(PiClient):
    """Same surface as PiClient. The unix socket (0660, group vhome-intsock) is the trust boundary, so no pin;
    the worker bearer token is still checked by the service. Skips the TLS handshake (slow on a Pi Zero W) and the
    HTTP proxy's 2-slot semaphore, breaker and shared auth-failure limiter."""

    def __init__(self, path: str, token: str, timeout: float = TIMEOUT_S):
        self.path, self.token, self.timeout = path, token, timeout

    def _connect(self):
        conn = _UnixConn(self.path, self.timeout)
        try:
            conn.connect()
        except OSError as e:
            conn.close()
            raise PiError(0, "unreachable:%s" % type(e).__name__) from None
        return conn
