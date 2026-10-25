"""VNode local HTTPS API v1 (docs/contracts/vnode-api-v1.md)."""
import asyncio
import hashlib
import inspect
import ipaddress
import json
import logging
import os
import re
import signal
import socket
import ssl
import time
from pathlib import Path

from aiohttp import web

from .. import __version__
from . import contracts
from .device import Device, RateLimited
from .phones import Nonces, PairingCodes, PhoneRegistry

log = logging.getLogger("vhome.api")
EX_CONFIG = 78
DIAG_MAX = 64 * 1024
_NO_AUTH = ("/v1/info", "/v1/pair")
_SENSITIVE_KEYS = {"client-key", "client_key", "clientkey", "token", "authorization", "nonce", "password", "secret"}
_LOCAL_NAME = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.local$")
_STATUS_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 413: "too_large"}


class ApiError(Exception):
    def __init__(self, status, code, detail="", **extra):
        super().__init__(code)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra

    def body(self):
        return {"error": self.code, "detail": contracts.redact(self.detail), **self.extra}


def _err_response(err):
    return web.json_response(err.body(), status=err.status)


# ---- request validation ------------------------------------------------------------------

def _str(max_len, min_len=1):
    def check(v):
        if not isinstance(v, str) or not min_len <= len(v) <= max_len:
            raise ValueError("must be a string of %d..%d chars" % (min_len, max_len))
        return v
    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("must be true or false")
    return v


def _int(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError("must be an integer %d..%d" % (lo, hi))
        return v
    return check


def _host(v):
    _str(253)(v)
    try:
        ipaddress.ip_address(v)
    except ValueError:
        if not _LOCAL_NAME.match(v):
            raise ValueError("must be an IP address or a .local name") from None
    return v


def _confirm(word):
    def check(v):
        if v != word:
            raise ValueError('must be "%s"' % word)
        return v
    return check


NONCE = _str(64)


async def read_json(request, fields):
    """fields: {key: (validator, required)}. Returns the validated dict. Unknown key -> 422."""
    raw = await request.read()  # aiohttp raises 413 past client_max_size
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiError(400, "bad_json", "body is not valid JSON") from None
    if not isinstance(data, dict):
        raise ApiError(422, "invalid", "body must be a JSON object")
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ApiError(422, "invalid", "unknown field: " + ", ".join(map(str, unknown)))
    out = {}
    for key, (check, required) in fields.items():
        if key not in data:
            if required:
                raise ApiError(422, "invalid", "missing field: " + key)
            continue
        try:
            out[key] = check(data[key])
        except ValueError as e:
            raise ApiError(422, "invalid", "%s %s" % (key, e)) from None
    return out


def _fields(**kw):
    """Shorthand: name=validator is required, name=(validator,) is optional. 'nonce' is always required."""
    spec = {"nonce": (NONCE, True)}
    for k, v in kw.items():
        spec[k] = (v[0], False) if isinstance(v, tuple) else (v, True)
    return spec


# ---- middleware --------------------------------------------------------------------------

@web.middleware
async def error_middleware(request, handler):
    status = 500
    try:
        declared = request.content_length
        if declared is not None and declared > contracts.MAX_BODY:
            raise ApiError(413, "too_large", "body over %d bytes" % contracts.MAX_BODY)
        resp = await handler(request)
        status = resp.status
        return resp
    except ApiError as e:
        status = e.status
        return _err_response(e)
    except web.HTTPException as e:
        status = e.status
        return web.json_response({"error": _STATUS_CODES.get(e.status, "error"), "detail": e.reason}, status=e.status)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - never leak internals to the client
        log.exception("unhandled error on %s %s", request.method, request.path)
        return web.json_response({"error": "internal", "detail": "internal error"}, status=500)
    finally:
        log.debug("%s %s -> %s", request.method, request.path, status)


@web.middleware
async def version_middleware(request, handler):
    sent = request.headers.get("X-VNode-Api")
    if sent is not None and sent.strip().split(".")[0] != str(contracts.API_VERSION):
        raise ApiError(426, "api_mismatch", "this node speaks API %d" % contracts.API_VERSION)
    return await handler(request)


def _timeout_for(path):
    return 13 if path == "/v1/tv/launch" else 6 if path == "/v1/tv/discover" else 5


# ---- application -------------------------------------------------------------------------

class _Api:
    def __init__(self, controller, phones, codes, nonces, device, info, admin):
        self.tv, self.phones, self.codes, self.nonces = controller, phones, codes, nonces
        self.device, self.info, self.admin = device, info, admin
        self.started = time.monotonic()
        self.launch_lock, self.pair_lock = asyncio.Lock(), asyncio.Lock()

    # middleware that needs state
    @web.middleware
    async def auth(self, request, handler):
        if not self.admin and request.path not in _NO_AUTH:
            header = request.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            phone = self.phones.check(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
            if phone is None:
                raise ApiError(401, "unauthorized", "missing or invalid token")
            request["phone_id"] = phone
        return await handler(request)

    @web.middleware
    async def timeout(self, request, handler):
        try:
            async with asyncio.timeout(_timeout_for(request.path)):
                return await handler(request)
        except TimeoutError:
            raise ApiError(504, "timeout", "the node did not answer in time") from None

    # nonce flow
    def _consume(self, nonce):
        state, previous = self.nonces.consume(nonce)
        if state == "duplicate":
            raise ApiError(409, "duplicate", "nonce already used", previous=previous)
        if state != "ok":
            raise ApiError(410, "expired", "nonce %s; fetch a new one" % state)

    async def _run_with_nonce(self, nonce, fn):
        self._consume(nonce)
        try:
            result = await fn()
        except ApiError as e:
            self.nonces.record(nonce, e.body())
            raise
        self.nonces.record(nonce, result)
        return web.json_response(result)

    def command(self, fields, fn):
        """POST route: validate -> consume nonce -> run -> remember the result under the nonce."""
        async def handler(request):
            data = await read_json(request, fields)
            nonce = data.pop("nonce")
            return await self._run_with_nonce(nonce, lambda: fn(request, data))
        return handler

    # unauthenticated
    async def get_info(self, request):
        caps = dict(self.info.get("capabilities", {}))
        if self.device.has_leds():
            caps["leds"] = "supported"
        return web.json_response({**self.info, "capabilities": caps})

    async def post_pair(self, request):
        data = await read_json(request, {"code": (_str(32), True), "name": (_str(64), True)})
        state = self.codes.redeem(data["code"])
        if state == "none":
            raise ApiError(429, "rate_limited", "no pairing code is active; make a new one on the node")
        if state == "wrong":
            raise ApiError(401, "unauthorized", "wrong pairing code")
        pid, token = self.phones.add(data["name"])
        log.info("phone paired: %s", pid)
        return web.json_response({"phone_id": pid, "token": token})

    # authenticated reads
    async def get_nonce(self, request):
        return web.json_response({"nonce": self.nonces.issue(), "ttl_s": int(contracts.NONCE_TTL_S)})

    async def get_status(self, request):
        st = self.tv.status()
        node = {"id": self.info.get("node_id"), "version": self.info.get("version"),
                "uptime_s": int(time.monotonic() - self.started), "service": "ok"}
        return web.json_response({"api": contracts.API_VERSION, "node": node,
                                 "headline": contracts.headline(st["tv"]["state"], st["watcher"]["state"]), **st})

    async def get_discover(self, request):
        return web.json_response({"tvs": await self.tv.discover_tvs()})

    async def get_diagnostics(self, request):
        diag = dict(self.tv.diagnostics())
        diag["system"] = self.device.status()
        diag = _scrub(diag)
        log_lines = [l[:500] for l in diag.get("log", []) if isinstance(l, str)]
        diag["log"] = log_lines
        body = json.dumps(diag)
        while len(body.encode()) > DIAG_MAX and log_lines:
            del log_lines[:max(1, len(log_lines) // 4)]  # drop the oldest quarter
            body = json.dumps(diag)
        if len(body.encode()) > DIAG_MAX:
            diag["checks"] = {}
            body = json.dumps(diag)
        return web.Response(text=body, content_type="application/json")

    async def get_phones(self, request):
        me = request.get("phone_id")
        return web.json_response({"phones": [{**p, "this": p["id"] == me} for p in self.phones.list()]})

    async def get_device(self, request):
        return web.json_response(self.device.status())

    # commands
    async def _pause(self, request, d):
        return await self.tv.pause(d.get("minutes"))

    async def _resume(self, request, d):
        return await self.tv.resume()

    async def _watcher(self, request, d):
        return await self.tv.set_enabled(d["enabled"])

    async def _launch(self, request, d):
        if self.launch_lock.locked():
            raise ApiError(409, "busy", "a launch is already running")
        async with self.launch_lock:
            return await self.tv.launch()

    async def _tv_pair(self, request, d):
        if self.pair_lock.locked():
            raise ApiError(409, "busy", "TV pairing is already starting")
        async with self.pair_lock:
            try:
                return await self.tv.start_tv_pair(d["host"], d.get("repin", False))
            except ValueError as e:
                raise ApiError(422, "invalid", str(e)) from None

    async def _leds(self, request, d):
        return self.device.set_leds(d["enabled"], d["brightness"])

    def _power(self, action):
        async def run(request, d):
            try:
                return await self.device.power(action)
            except RateLimited as e:
                raise ApiError(429, "rate_limited", str(e)) from None
        return run

    async def delete_phone(self, request):
        nonce = request.headers.get("X-VNode-Nonce", "")
        if not nonce or len(nonce) > 64:
            raise ApiError(422, "invalid", "X-VNode-Nonce header required")
        pid = request.match_info["id"]

        async def revoke():
            if not self.phones.revoke(pid):
                raise ApiError(404, "not_found", "no such phone")
            log.info("phone revoked: %s", pid)
            return {"outcome": "confirmed"}
        return await self._run_with_nonce(nonce, revoke)

    # admin
    async def admin_code(self, request):
        return web.json_response({"code": self.codes.new(), "node_id": self.info.get("node_id"),
                                  "expires_in_s": int(contracts.PAIR_CODE_TTL_S)})

    async def admin_phones(self, request):
        return web.json_response({"phones": self.phones.list()})

    async def admin_revoke(self, request):
        if not self.phones.revoke(request.match_info["id"]):
            raise ApiError(404, "not_found", "no such phone")
        log.info("phone revoked: %s", request.match_info["id"])
        return web.json_response({"outcome": "confirmed"})


def _scrub(obj):
    """contracts.redact on every string, plus whole values under secret-looking keys."""
    if isinstance(obj, dict):
        return {k: "<redacted>" if str(k).lower() in _SENSITIVE_KEYS else _scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        return contracts.redact(obj)
    return obj


def build_app(controller, phones, codes, nonces, device, info, *, admin=False):
    api = _Api(controller, phones, codes, nonces, device, info, admin)
    app = web.Application(client_max_size=contracts.MAX_BODY,
                          middlewares=[error_middleware, version_middleware, api.auth, api.timeout])
    f = _fields
    app.add_routes([
        web.get("/v1/info", api.get_info),
        web.post("/v1/pair", api.post_pair),
        web.get("/v1/nonce", api.get_nonce),
        web.get("/v1/status", api.get_status),
        web.post("/v1/pause", api.command(f(minutes=(_int(1, 1440),)), api._pause)),
        web.post("/v1/resume", api.command(f(), api._resume)),
        web.post("/v1/watcher", api.command(f(enabled=_bool), api._watcher)),
        web.post("/v1/tv/launch", api.command(f(), api._launch)),
        web.post("/v1/tv/pair", api.command(f(host=_host, repin=(_bool,)), api._tv_pair)),
        web.get("/v1/tv/discover", api.get_discover),
        web.get("/v1/diagnostics", api.get_diagnostics),
        web.get("/v1/phones", api.get_phones),
        web.delete("/v1/phones/{id}", api.delete_phone),
        web.get("/v1/device", api.get_device),
        web.post("/v1/device/leds", api.command(f(enabled=_bool, brightness=_int(1, 4)), api._leds)),
        web.post("/v1/device/restart-service", api.command(f(), api._power("restart-service"))),
        web.post("/v1/device/reboot", api.command(f(confirm=_confirm("reboot")), api._power("reboot"))),
        web.post("/v1/device/shutdown", api.command(f(confirm=_confirm("shutdown")), api._power("shutdown"))),
    ])
    if admin:
        app.add_routes([
            web.post("/admin/pairing-code", api.admin_code),
            web.get("/admin/phones", api.admin_phones),
            web.delete("/admin/phones/{id}", api.admin_revoke),
        ])
    return app


# ---- identity, TLS, serving --------------------------------------------------------------

def node_id(cert_path):
    der = ssl.PEM_cert_to_DER_cert(Path(cert_path).read_text())
    return hashlib.sha256(der).hexdigest()


def make_ssl_context(cert, key):
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def _version():
    v = __version__
    try:
        extra = (Path(__file__).resolve().parent.parent.parent / "VERSION").read_text().strip()
        if extra:
            v += "+" + extra
    except OSError:
        pass
    return v


async def serve(state_dir, cert, key, port=contracts.PORT, runtime_dir=None):
    """Runs until SIGTERM/SIGINT. Returns the process exit code (0 clean, 78 when another instance holds the lock)."""
    from .tvcontrol import TvController  # built in parallel; imported late so api tests don't need it

    state_dir = Path(state_dir)
    runtime_dir = Path(runtime_dir or os.environ.get("RUNTIME_DIRECTORY", "/run/vhome-vnode").split(":")[0])
    controller = TvController(state_dir)
    locked = controller.acquire_lock()
    if inspect.isawaitable(locked):
        locked = await locked
    if not locked:
        log.error("another vhome-vnode already holds the lock in %s", state_dir)
        return EX_CONFIG

    ssl_ctx = make_ssl_context(cert, key)
    info = {"api": contracts.API_VERSION, "node_id": node_id(cert), "name": socket.gethostname(),
            "version": _version(),
            "capabilities": contracts.capabilities(power_on_launch=bool(getattr(controller, "power_on_launch", False)),
                                                   leds=os.path.exists(contracts.LED_STATE_FILE))}
    phones, codes, nonces = PhoneRegistry(state_dir), PairingCodes(), Nonces()
    device = Device(state_dir)
    runner = web.AppRunner(build_app(controller, phones, codes, nonces, device, info), access_log=None)  # polling would flood the SD card
    admin_runner = web.AppRunner(build_app(controller, phones, codes, nonces, device, info, admin=True), access_log=None)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await controller.start()
        await runner.setup()
        await admin_runner.setup()
        await web.TCPSite(runner, host=None, port=port, ssl_context=ssl_ctx).start()
        sock = runtime_dir / contracts.ADMIN_SOCKET
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
            sock.unlink(missing_ok=True)
            old = os.umask(0o177)  # the socket is never world-accessible, not even briefly
            try:
                await web.UnixSite(admin_runner, str(sock)).start()
            finally:
                os.umask(old)
            os.chmod(sock, 0o600)
        except OSError as e:
            # Losing the local CLI must not take TV watching or the phone API down with it.
            log.error("admin socket %s unavailable (%s); the vnode CLI won't work until restart", sock, e)
        log.info("vnode %s listening on :%d (node %s)", info["version"], port, info["node_id"][:16])
        await stop.wait()
    finally:
        log.info("shutting down")
        try:
            async with asyncio.timeout(10):
                await runner.cleanup()
                await admin_runner.cleanup()
                await controller.close()
        except TimeoutError:
            log.error("shutdown took over 10 s")
    return 0
