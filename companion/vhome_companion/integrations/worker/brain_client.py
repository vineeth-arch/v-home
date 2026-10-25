"""Brain localhost client. Stdlib only. Errors carry a retryable flag."""
from __future__ import annotations

import http.client
import json
import socket
import urllib.parse

TIMEOUT_S = 10
LOOPBACK = ("127.0.0.1", "localhost", "::1")


NON_RETRYABLE = (400, 413, 422)     # the Brain judged this payload bad; everything else may succeed later
AUTH = (401, 403)


class BrainError(Exception):
    def __init__(self, retryable: bool, status: int = 0, code: str = ""):
        super().__init__("brain %s %s" % (status, code))
        self.retryable, self.status, self.code = retryable, status, code


def stops_pass(e: "BrainError") -> bool:
    """Brain is sick or refusing us: do not claim more jobs this pass."""
    return e.status in (0, 401, 403, 404, 408) or e.status >= 500


def parse_url(url: str):
    """Loopback http only: the Brain token must never leave this machine."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "http" or u.hostname not in LOOPBACK:
        raise ValueError("BRAIN_URL must be http://127.0.0.1 / localhost (loopback only)")
    return u.hostname, u.port or 80


class BrainClient:
    def __init__(self, url: str, token: str, timeout: float = TIMEOUT_S):
        self.host, self.port = parse_url(url)
        self.token, self.timeout = token, timeout
        self.auth_error = False     # last answer was 401/403; shown in the next snapshot

    def _req(self, method, path, body=None, key=None) -> dict:
        headers = {"Authorization": "Bearer " + self.token}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if key:
            headers["X-Capture-Key"] = key
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            try:
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(1 << 20)
            except (OSError, socket.timeout, http.client.HTTPException) as e:
                raise BrainError(True, 0, "unreachable:%s" % type(e).__name__) from None
        finally:
            conn.close()
        self.auth_error = resp.status in AUTH
        if resp.status >= 400:
            raise BrainError(resp.status not in NON_RETRYABLE, resp.status, "http_%d" % resp.status)
        try:
            out = json.loads(raw) if raw else {}
        except ValueError:
            raise BrainError(True, resp.status, "bad_json") from None
        return out if isinstance(out, dict) else {}

    def _capture(self, body, key) -> str:
        note_id = self._req("POST", "/api/capture", body, key).get("id")
        if not isinstance(note_id, str) or not note_id:
            raise BrainError(True, 0, "no_note_id")
        return note_id

    def capture_text(self, text: str, key: str) -> str:
        return self._capture({"text": text}, key)

    def capture_url(self, url: str, insight, key: str) -> str:
        body = {"url": url}
        if insight:
            body["insight"] = insight
        return self._capture(body, key)

    def status(self) -> dict:
        return self._req("GET", "/api/status")
