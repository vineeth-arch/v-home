"""Brain client. Stdlib only. Errors carry a retryable flag.

Brain is either on loopback (http, Mac worker) or on one named https host (Pi worker -> VPS, BRAIN_ALLOW_HOST)."""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import urllib.parse

from .. import contracts

TIMEOUT_S = 20      # Brain behind Cloudflare from a Pi Zero: TLS + first byte can take a while
LOOPBACK = ("127.0.0.1", "localhost", "::1")


NON_RETRYABLE = (400, 413, 422)     # the Brain judged this payload bad; everything else may succeed later
AUTH = (401, 403)
LOGIN_REDIRECTS = (301, 302, 303, 307, 308)     # what Cloudflare Access answers; never followed
_WHAT_KEYS = ("what", "detail", "message", "error")



USER_AGENT = "vhome-worker/0.2 (+https://github.com/vineeth-arch/v-home)"

class BrainError(Exception):
    def __init__(self, retryable: bool, status: int = 0, code: str = "", what: str = ""):
        super().__init__("brain %s %s" % (status, code))
        self.retryable, self.status, self.code, self.what = retryable, status, code, what


def stops_pass(e: "BrainError") -> bool:
    """Brain is sick or refusing us: do not claim more jobs this pass."""
    return e.status in (0, 401, 403, 404, 408) or e.status >= 500 or 300 <= e.status < 400 or e.code == "access_blocked"


def explain(e: "BrainError") -> str:
    """Plain sentence for the phone (job error_msg). Brain's own short reason, redacted, goes last."""
    if e.code == "access_blocked":
        msg = "Brain's login page (Cloudflare Access) is blocking VNode. Add the path to the Access bypass."
    elif e.status in AUTH:
        msg = "Brain refused VNode's token. Re-issue it on Brain and update VNode."
    elif e.status == 0:
        msg = "VNode could not reach Brain. It will try again."
    elif e.status >= 500:
        msg = "Brain had an error. VNode will try again."
    elif e.retryable:
        msg = "Brain didn't take this yet \u2014 VNode will try again."
    else:
        msg = "Brain did not accept this item (HTTP %d)." % e.status
    return msg + (" Brain said: " + e.what if e.what else "")


def _what(raw: bytes, secrets=()) -> str:
    """Short, single-line, redacted reason from Brain's error envelope. Never the raw body.
    The literal tokens VNode holds are scrubbed too, in case Brain echoes a header back."""
    try:
        d = json.loads(raw)
    except ValueError:
        return ""
    if isinstance(d, dict) and isinstance(d.get("error"), dict):     # Brain's envelope: {"error": {"what": ...}}
        d = d["error"]
    if not isinstance(d, dict):
        return ""
    for k in _WHAT_KEYS:
        if isinstance(d.get(k), str) and d[k].strip():
            text = d[k]
            for secret in secrets:
                if secret:
                    text = text.replace(secret, "<redacted>")
            return re.sub(r"\s+", " ", contracts.redact(text)).strip()[:60]
    return ""


_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")   # no trailing dot, no empty labels


def parse_url(url: str, allow_host: str = ""):
    """(scheme, host, port). http only to loopback (the token never leaves this machine in clear);
    https only to exactly allow_host, which must be set on purpose (BRAIN_ALLOW_HOST)."""
    if any(c in url for c in "\\ \t\r\n") or not url.isascii():
        raise ValueError("BRAIN_URL must be a plain ASCII URL (use the xn-- form for international names)")
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if u.username or u.password:
        raise ValueError("BRAIN_URL must not contain credentials")
    allow_host = allow_host.strip().lower()
    if allow_host and not _HOST.fullmatch(allow_host):
        raise ValueError("BRAIN_ALLOW_HOST must be a bare host name (no port, path or trailing dot)")
    if host not in LOOPBACK and not _HOST.fullmatch(host):
        raise ValueError("BRAIN_URL host is not a plain host name")
    if u.scheme == "http" and host in LOOPBACK:
        return "http", host, u.port or 80
    if u.scheme == "https" and host and allow_host and host == allow_host:
        return "https", host, u.port or 443
    raise ValueError("BRAIN_URL must be http://127.0.0.1 / localhost (loopback only), "
                     "or https://<host> with BRAIN_ALLOW_HOST=<that host>")


class BrainClient:
    def __init__(self, url: str, token: str, timeout: float = TIMEOUT_S, cf_id: str = "", cf_secret: str = "",
                 allow_host: str = "", ssl_context: ssl.SSLContext | None = None):
        self.scheme, self.host, self.port = parse_url(url, allow_host)
        self.token, self.timeout = token, timeout
        self._secrets = (token, cf_id, cf_secret)
        self.cf = {"CF-Access-Client-Id": cf_id, "CF-Access-Client-Secret": cf_secret} if cf_id and cf_secret else {}
        self._ctx = ssl_context or (ssl.create_default_context() if self.scheme == "https" else None)   # real cert checks
        self.auth_error = False     # last answer was 401/403 or a login redirect; shown in the next snapshot
        self.transport_down = False  # last request never got an HTTP answer
        self.captured = 0            # successful captures so far (reachability evidence beyond /api/status)

    def _conn(self):
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self._ctx)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _req(self, method, path, body=None, key=None) -> dict:
        # A named User-Agent: Cloudflare's bot protection answers 403 to requests
        # with none (http.client sends none) or with a stock Python one.
        headers = {"Authorization": "Bearer " + self.token, "User-Agent": USER_AGENT, **self.cf}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if key:
            headers["X-Capture-Key"] = key
        conn = self._conn()
        try:
            try:
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(1 << 20)
            except (OSError, socket.timeout, http.client.HTTPException) as e:   # ssl.SSLError is an OSError
                self.transport_down = True
                raise BrainError(True, 0, "unreachable:%s" % type(e).__name__) from None
        finally:
            conn.close()
        self.transport_down = False
        ctype = resp.getheader("Content-Type") or ""
        blocked = resp.status in LOGIN_REDIRECTS      # Cloudflare Access login redirect (never followed)
        self.auth_error = resp.status in AUTH or blocked
        if blocked:
            raise BrainError(True, resp.status, "access_blocked")
        if resp.status >= 300:              # other 3xx (304, 300, ...) and every 4xx/5xx
            raise BrainError(resp.status not in NON_RETRYABLE, resp.status, "http_%d" % resp.status,
                             _what(raw, self._secrets))
        try:
            out = json.loads(raw) if raw else {}
        except ValueError:
            if "text/html" in ctype.lower() or raw.lstrip()[:1] == b"<":    # an interstitial login page, not Brain
                self.auth_error = True
                raise BrainError(True, resp.status, "access_blocked") from None
            raise BrainError(True, resp.status, "bad_json") from None
        return out if isinstance(out, dict) else {}

    def _capture(self, body, key) -> str:
        note_id = self._req("POST", "/api/capture", body, key).get("id")
        if not isinstance(note_id, str) or not note_id:
            raise BrainError(True, 0, "no_note_id")
        self.captured += 1
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
