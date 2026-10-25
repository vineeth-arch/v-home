"""Fail-fast proxy from the TV API to the integrations service (docs/contracts/vnode-int-api-v1.md, "Proxy").

Runs inside vhome-vnode, so it must never queue, buffer past PROXY_MAX_BODY, or let an exception escape.
"""
import asyncio
import collections
import logging
import os
import time

import aiohttp
from aiohttp import web

from ..integrations import contracts as ic
from .api import ApiError

log = logging.getLogger("vhome.intproxy")
_CHUNK = 64 * 1024
_MAX_IPS = 64
_OK_GRACE_S = 600.0
PROXY_KEY = web.AppKey("intproxy", object)


def _unavailable(detail):
    return ApiError(503, ic.Err.UNAVAILABLE.value, detail)


class _Proxy:
    def __init__(self, api, socket_path, total_s, connect_s, clock):
        self.api, self.socket_path, self.clock = api, socket_path, clock
        self.timeout = aiohttp.ClientTimeout(total=total_s, sock_connect=connect_s)
        self.session = None
        self.sem = asyncio.Semaphore(ic.PROXY_CONCURRENCY)
        self.fails, self.open_until = 0, 0.0
        # ponytail: per-IP (request.remote) fail times; ceiling _MAX_IPS tracked IPs, oldest dropped, so a LAN
        # host rotating >64 source addresses can evade the throttle (needs spoofing on a LAN; accepted).
        self.auth_fails, self.ok_ips = collections.OrderedDict(), collections.OrderedDict()

    async def close(self, app=None):
        if self.session is not None:
            await self.session.close()

    def _breaker_failed(self):
        self.fails += 1
        if self.fails >= ic.BREAKER_FAILS:
            self.open_until = self.clock() + ic.BREAKER_OPEN_S

    @staticmethod
    def _ip(request):
        return request.remote

    @staticmethod
    def _remember(d, ip, value):
        d[ip] = value
        d.move_to_end(ip)
        while len(d) > _MAX_IPS:
            d.popitem(last=False)

    async def _read_body(self, request, cap):
        if request.content_length is not None and request.content_length > cap:
            raise ApiError(413, "too_large", "body over %d bytes" % cap)
        parts, size = [], 0
        while True:
            chunk = await request.content.read(_CHUNK)
            if not chunk:
                return b"".join(parts)
            size += len(chunk)
            if size > cap:
                raise ApiError(413, "too_large", "body over %d bytes" % cap)
            parts.append(chunk)

    def _worker_gate(self, request):
        auth = request.headers.get("Authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(401, "unauthorized", "worker token required")
        ip, now = self._ip(request), self.clock()
        fails = self.auth_fails.get(ip)
        if fails is not None:
            while fails and now - fails[0] >= 60.0:
                fails.popleft()
            if not fails:
                del self.auth_fails[ip]
            elif len(fails) >= ic.AUTH_FAIL_LIMIT_PER_MIN and now - self.ok_ips.get(ip, -_OK_GRACE_S) >= _OK_GRACE_S:
                raise ApiError(429, ic.Err.RATE_LIMITED.value, "too many failed worker auths")
        return auth

    async def handle(self, request):
        start = time.monotonic()
        status = 500
        try:
            resp = await self._handle(request)
            status = resp.status
            return resp
        except ApiError as e:
            status = e.status
            raise
        finally:
            prefix = ic.WORKER_PREFIX if request.path.startswith(ic.WORKER_PREFIX) else ic.PHONE_PREFIX
            log.info("%s %s* -> %s in %.0f ms", request.method, prefix, status, (time.monotonic() - start) * 1000)

    async def _handle(self, request):
        worker = request.path.startswith(ic.WORKER_PREFIX)
        headers = {h: request.headers[h] for h in ic.FORWARD_HEADERS if h in request.headers}
        nonce = None
        if worker:
            headers["Authorization"] = self._worker_gate(request)
        else:
            headers[ic.PHONE_HEADER] = request["phone_id"]   # client copy was never copied above
            if request.method not in ("GET", "HEAD"):
                nonce = request.headers.get(ic.NONCE_HEADER, "")
                if not nonce or len(nonce) > 64:
                    raise ApiError(422, "invalid", "%s header required" % ic.NONCE_HEADER)
        if self.clock() < self.open_until:
            raise _unavailable("integrations are not answering; retry later")
        if not os.path.exists(self.socket_path):
            self._breaker_failed()
            raise _unavailable("integrations service is not running")
        if self.sem.locked():
            raise _unavailable("integrations proxy busy")
        async with self.sem:   # taken before the body is read: at most PROXY_CONCURRENCY bodies are buffered
            body = await self._read_body(request, ic.PROXY_WORKER_MAX_BODY if worker else ic.PROXY_MAX_BODY)
            if nonce is not None:
                self.api._consume(nonce)
            try:
                if self.session is None:
                    self.session = aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=self.socket_path),
                                                         timeout=self.timeout)
                async with self.session.request(request.method, "http://int" + request.rel_url.raw_path_qs,
                                                data=body or None, headers=headers) as r:
                    data = await r.read()
                    status, out = r.status, {h: r.headers[h] for h in ic.RETURN_HEADERS if h in r.headers}
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - timeout, refused, reset, malformed reply: all "unavailable"
                self._breaker_failed()
                log.warning("integrations call failed: %s", type(e).__name__)
                raise _unavailable("integrations service did not answer") from None
        self.fails = 0
        if worker:
            ip = self._ip(request)
            if status == 401:
                self._remember(self.auth_fails, ip, self.auth_fails.get(ip) or collections.deque())
                self.auth_fails[ip].append(self.clock())
            elif 200 <= status < 300:
                self._remember(self.ok_ips, ip, self.clock())
        return web.Response(status=status, body=data, headers=out)


def register(app, api, socket_path, *, total_s=ic.PROXY_TOTAL_TIMEOUT_S, connect_s=ic.PROXY_CONNECT_TIMEOUT_S,
             clock=time.monotonic):
    proxy = _Proxy(api, socket_path, total_s, connect_s, clock)
    app[PROXY_KEY] = proxy
    app.router.add_route("*", "/v1/inbox/{tail:.*}", proxy.handle)
    app.router.add_route("*", "/v1/int/worker/{tail:.*}", proxy.handle)
    app.on_cleanup.append(proxy.close)
    caps = {**api.info.get("capabilities", {}), "inbox": "supported"}
    api.info = {**api.info, "int": ic.INT_API, "capabilities": caps}
    return proxy
