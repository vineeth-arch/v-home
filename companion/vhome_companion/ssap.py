"""LG webOS SSAP client over wss://<tv>:3001 (adapted from webos-vibehack lgtv.py, MIT; see NOTICE).

Certificate trust is trust-on-first-use: `pair` stores the SHA-256 of the TV's DER certificate,
every later connection compares it BEFORE the client key is sent. Nothing global is changed.
"""
import asyncio
import errno
import hashlib
import hmac
import itertools
import json
import logging
import re
import ssl

log = logging.getLogger("vhome.ssap")

PORT = 3001
MAX_MESSAGE = 4 * 1024 * 1024

# Narrowed on purpose: the only permissions V/HOME's companion asks for. The manifest is UNSIGNED:
# LG's shared "signed" test block (appId com.lge.test) is rejected by affected firmware with
# "403 Pairing rejected: blacklisted certificate detected", so it is deliberately not sent.
PERMISSIONS = ["LAUNCH", "READ_RUNNING_APPS", "READ_INSTALLED_APPS", "READ_INPUT_DEVICE_LIST"]

LOCAL_NETWORK_HINT = (
    "no route to the TV. If the TV is on and on this network, allow Local Network for the "
    "Python/Terminal app in System Settings > Privacy & Security > Local Network"
)


class SsapError(Exception):
    pass


class PinMismatch(SsapError):
    """The TV presented a different certificate than the one pinned at pair time."""


class NotPaired(SsapError):
    pass


class Unreachable(SsapError):
    def __init__(self, msg, quiet=True):
        super().__init__(msg)
        self.quiet = quiet  # plain standby / network loss is not worth a warning


class ConnectionLost(SsapError):
    pass


class RequestTimeout(SsapError):
    pass


class RequestFailed(SsapError):
    def __init__(self, text, code=None):
        super().__init__(text or "request failed")
        self.code = code

    @property
    def kind(self):
        t = f"{self} {self.code}".lower()
        if any(w in t for w in ("denied", "permission", "not allowed", "insufficient", "401", "403")):
            return "denied"
        return "unavailable"


def map_os_error(exc, host):
    if getattr(exc, "errno", None) == errno.EHOSTUNREACH or "No route to host" in str(exc):
        return Unreachable(f"{host}: {LOCAL_NETWORK_HINT}", quiet=False)
    return Unreachable(f"{host}: {type(exc).__name__}: {exc}")


def new_ssl_context():
    # Per connection only. The TV uses a certificate from LG's own CA; identity is the pin instead.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def redact(text):
    return re.sub(r'("client-key"\s*:\s*")[^"]*', r"\1<redacted>", str(text))


def manifest():
    return {"manifestVersion": 1, "appVersion": "1.1", "permissions": list(PERMISSIONS)}


async def default_connect(host, ctx):
    from websockets.asyncio.client import connect  # lazy: tests do not need websockets

    return await connect(f"wss://{host}:{PORT}", ssl=ctx, open_timeout=10, ping_interval=10,
                         ping_timeout=10, max_size=MAX_MESSAGE, close_timeout=3)


class Subscription:
    def __init__(self):
        self._q = asyncio.Queue()

    async def get(self):
        item = await self._q.get()
        if isinstance(item, Exception):
            raise item
        return item


class Client:
    def __init__(self, host, client_key=None, pin=None, trust_new=False,
                 connect=default_connect, request_timeout=10.0):
        self.host, self.client_key, self.pin = host, client_key, pin
        self.trust_new, self._connect = trust_new, connect
        self.request_timeout = request_timeout
        self.cert_sha256 = None
        self._ws = None
        self._reader = None
        self._ids = itertools.count(1)
        self._pending = {}
        self._subs = {}

    async def open(self, pair_timeout=60.0, on_prompt=None):
        """Connect, check the pin, register. Returns the client key."""
        try:
            ws = await self._connect(self.host, new_ssl_context())
        except SsapError:
            raise
        except (OSError, TimeoutError) as e:
            raise map_os_error(e, self.host) from e
        except Exception as e:
            raise SsapError(f"{self.host}: handshake failed: {type(e).__name__}: {e}") from e
        self._ws = ws
        try:
            self._check_pin(ws)
            key = await self._register(ws, pair_timeout, on_prompt)
        except BaseException:
            await self.close()
            raise
        self.client_key = key
        self._reader = asyncio.create_task(self._read_loop())
        return key

    def _check_pin(self, ws):
        try:
            der = ws.transport.get_extra_info("ssl_object").getpeercert(binary_form=True)
        except Exception as e:
            raise SsapError(f"could not read the TV certificate: {e}") from e
        if not der:
            raise SsapError("the TV presented no certificate")
        self.cert_sha256 = hashlib.sha256(der).hexdigest()
        if self.pin is None:
            if not self.trust_new:
                raise NotPaired("no pinned TV certificate; run `pair` first")
        elif not hmac.compare_digest(self.pin, self.cert_sha256):
            raise PinMismatch(
                f"{self.host} presented a different certificate than the one pinned at pair time; "
                "refusing to connect. If the TV was reset or updated, run `pair --repin`")

    async def _register(self, ws, pair_timeout, on_prompt):
        payload = {"forcePairing": False, "pairingType": "PROMPT", "manifest": manifest()}
        if self.client_key:
            payload["client-key"] = self.client_key
        await self._send_raw({"type": "register", "id": "register_0", "payload": payload})
        wait = pair_timeout if not self.client_key else min(pair_timeout, 15.0)
        try:
            async with asyncio.timeout(wait):
                while True:
                    msg = self._parse(await ws.recv())
                    if msg is None:
                        continue
                    kind = msg.get("type")
                    if kind == "registered":
                        key = (msg.get("payload") or {}).get("client-key")
                        if not isinstance(key, str) or not key:
                            raise SsapError("the TV registered us without a client key")
                        return key
                    if kind == "error":
                        err = str(msg.get("error"))
                        if "blacklist" in err.lower():
                            raise NotPaired(f"TV refused registration ({err}). The firmware rejects "
                                            "the manifest it was sent; report this with `diag` output.")
                        raise NotPaired(f"TV refused registration (401/403 means pairing was "
                                        f"declined or the key is no longer valid): {err}")
                    if kind == "response" and on_prompt:
                        on_prompt()
        except TimeoutError:
            raise NotPaired("timed out waiting for the TV to accept the pairing prompt") from None
        except SsapError:
            raise
        except Exception as e:
            raise ConnectionLost(f"connection closed during registration: {e}") from e

    @staticmethod
    def _parse(raw):
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("ignored malformed message: %.200s", redact(raw))
            return None
        if not isinstance(msg, dict):
            log.warning("ignored non-object message: %.200s", redact(raw))
            return None
        return msg

    async def _send_raw(self, obj):
        try:
            await self._ws.send(json.dumps(obj))
        except Exception as e:
            raise ConnectionLost(f"send failed: {e}") from e

    async def _read_loop(self):
        why = "closed"
        try:
            while True:
                msg = self._parse(await self._ws.recv())
                if msg is not None:
                    self._dispatch(msg)
        except asyncio.CancelledError:
            why = "closed"
            raise
        except Exception as e:
            why = f"{type(e).__name__}: {e}"
        finally:
            self._fail_all(ConnectionLost(f"connection to the TV lost ({why})"))

    def _dispatch(self, msg):
        rid = msg.get("id")
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        err = None
        if msg.get("type") == "error":
            err = RequestFailed(str(msg.get("error") or "error"), msg.get("error"))
        elif payload.get("returnValue") is False:
            err = RequestFailed(payload.get("errorText"), payload.get("errorCode"))
        fut = self._pending.get(rid)
        if fut is not None:
            if not fut.done():
                fut.set_exception(err) if err else fut.set_result(payload)
            return
        sub = self._subs.get(rid)
        if sub is not None:
            sub._q.put_nowait(err or payload)
            return
        log.debug("ignored message for unknown id %r", rid)

    def _fail_all(self, exc):
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        for sub in self._subs.values():
            sub._q.put_nowait(exc)

    async def request(self, uri, payload=None, timeout=None):
        rid = f"r{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send_raw({"type": "request", "id": rid, "uri": uri, "payload": payload or {}})
            return await asyncio.wait_for(fut, timeout or self.request_timeout)
        except TimeoutError:
            raise RequestTimeout(f"no response to {uri}") from None
        finally:
            self._pending.pop(rid, None)

    async def hello(self, timeout=None):
        """Send LG's `hello` (platform info). Answer shape is unverified; returns the payload dict."""
        rid = f"r{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send_raw({"type": "hello", "id": rid, "payload": {}})
            return await asyncio.wait_for(fut, timeout or self.request_timeout)
        except TimeoutError:
            raise RequestTimeout("no answer to hello") from None
        finally:
            self._pending.pop(rid, None)

    async def subscribe(self, uri, payload=None):
        rid = f"s{next(self._ids)}"
        sub = Subscription()
        self._subs[rid] = sub
        await self._send_raw({"type": "subscribe", "id": rid, "uri": uri, "payload": payload or {}})
        return sub

    async def close(self):
        if self._reader:
            self._reader.cancel()
            self._reader = None
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
