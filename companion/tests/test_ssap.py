import asyncio
import errno
import hashlib
import json
import os
import ssl
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import ssap  # noqa: E402

DER = b"fake-der-certificate"
PIN = hashlib.sha256(DER).hexdigest()
KEY = "SECRET-CLIENT-KEY"


class FakeSSL:
    def __init__(self, der):
        self.der = der

    def getpeercert(self, binary_form=False):
        return self.der


class FakeTransport:
    def __init__(self, der):
        self.der = der

    def get_extra_info(self, name):
        return FakeSSL(self.der) if name == "ssl_object" else None


class FakeWS:
    """Stands in for a websockets connection; `server` reacts to each message the client sends."""

    def __init__(self, der=DER, server=None):
        self.transport = FakeTransport(der)
        self.sent = []
        self.inbox = asyncio.Queue()
        self.server = server
        self.closed = False

    async def send(self, text):
        msg = json.loads(text)
        self.sent.append(msg)
        if self.server:
            self.server(self, msg)

    async def recv(self):
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True

    def push(self, obj):
        self.inbox.put_nowait(obj if isinstance(obj, (str, bytes)) else json.dumps(obj))


def registering_server(ws, msg):
    if msg["type"] == "register":
        ws.push({"type": "registered", "id": msg["id"], "payload": {"client-key": KEY}})


def make_client(ws, **kw):
    async def connect(host, ctx):
        return ws
    kw.setdefault("pin", PIN)
    return ssap.Client("192.168.1.50", connect=connect, **kw)


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_with_narrowed_permissions_and_unsigned_manifest(self):
        ws = FakeWS(server=registering_server)
        c = make_client(ws, client_key="old-key")
        self.assertEqual(await c.open(), KEY)
        reg = ws.sent[0]
        self.assertEqual(reg["type"], "register")
        p = reg["payload"]
        self.assertEqual(p["manifest"]["permissions"],
                         ["LAUNCH", "READ_RUNNING_APPS", "READ_INSTALLED_APPS", "READ_INPUT_DEVICE_LIST"])
        self.assertEqual(p["manifest"]["appVersion"], "1.1")
        self.assertEqual(p["pairingType"], "PROMPT")
        self.assertEqual(p["client-key"], "old-key")
        self.assertNotIn("signed", p["manifest"])
        self.assertNotIn("signatures", p["manifest"])
        self.assertNotIn("com.lge.test", json.dumps(reg))
        await c.close()

    async def test_blacklisted_certificate_error_is_explained(self):
        def server(ws, msg):
            ws.push({"type": "error", "id": msg["id"], "error": "403 Pairing rejected: blacklisted certificate detected"})
        with self.assertRaises(ssap.NotPaired) as cm:
            await make_client(FakeWS(server=server)).open()
        self.assertIn("blacklisted", str(cm.exception))
        self.assertIn("rejects", str(cm.exception))

    async def test_hello(self):
        def server(ws, msg):
            if msg["type"] == "register":
                registering_server(ws, msg)
            elif msg["type"] == "hello":
                ws.push({"type": "hello", "id": msg["id"], "payload": {"deviceType": "tv"}})
        c = make_client(FakeWS(server=server))
        await c.open()
        self.assertEqual(await c.hello(), {"deviceType": "tv"})
        await c.close()

    async def test_pin_mismatch_refuses_before_sending_anything(self):
        ws = FakeWS(der=b"some-other-cert", server=registering_server)
        c = make_client(ws, client_key=KEY)
        with self.assertRaises(ssap.PinMismatch):
            await c.open()
        self.assertEqual(ws.sent, [])  # the client key never left
        self.assertTrue(ws.closed)

    async def test_no_pin_and_not_pairing_refuses_before_sending(self):
        ws = FakeWS(server=registering_server)
        c = make_client(ws, pin=None, client_key=KEY)
        with self.assertRaises(ssap.NotPaired):
            await c.open()
        self.assertEqual(ws.sent, [])

    async def test_pairing_records_cert_hash(self):
        ws = FakeWS(server=registering_server)
        c = make_client(ws, pin=None, trust_new=True)
        prompts = []
        await c.open(on_prompt=lambda: prompts.append(1))
        self.assertEqual(c.cert_sha256, PIN)
        self.assertNotIn("client-key", ws.sent[0]["payload"])
        await c.close()

    async def test_prompt_then_registered(self):
        def server(ws, msg):
            ws.push({"type": "response", "id": msg["id"], "payload": {"pairingType": "PROMPT", "returnValue": True}})
            ws.push("garbage that is not json")
            ws.push({"type": "registered", "id": msg["id"], "payload": {"client-key": KEY}})
        prompts = []
        c = make_client(FakeWS(server=server), pin=None, trust_new=True)
        self.assertEqual(await c.open(on_prompt=lambda: prompts.append(1)), KEY)
        self.assertEqual(prompts, [1])
        await c.close()

    async def test_rejected_registration(self):
        def server(ws, msg):
            ws.push({"type": "error", "id": msg["id"], "error": "403 User rejected"})
        with self.assertRaises(ssap.NotPaired):
            await make_client(FakeWS(server=server)).open()

    async def test_pair_timeout(self):
        with self.assertRaises(ssap.NotPaired):
            await make_client(FakeWS(), pin=None, trust_new=True).open(pair_timeout=0.05)

    async def test_stored_key_without_answer_is_link_loss_not_revocation(self):
        # A waking TV that never answers register must not stop the watcher for good.
        c = make_client(FakeWS())
        c.client_key = KEY
        with self.assertRaises(ssap.ConnectionLost):
            await c.open(pair_timeout=0.05)

    async def test_connect_errors_are_mapped(self):
        def failing(exc):
            async def connect(host, ctx):
                raise exc
            return ssap.Client("10.0.0.9", pin=PIN, connect=connect)
        with self.assertRaises(ssap.Unreachable) as cm:
            await failing(OSError(errno.EHOSTUNREACH, "No route to host")).open()
        self.assertIn("Local Network", str(cm.exception))
        self.assertFalse(cm.exception.quiet)
        with self.assertRaises(ssap.Unreachable) as cm:
            await failing(ConnectionRefusedError(errno.ECONNREFUSED, "refused")).open()
        self.assertTrue(cm.exception.quiet)
        self.assertNotIn("Local Network", str(cm.exception))

    def test_ssl_context_is_local_and_global_settings_untouched(self):
        before = ssl._create_default_https_context
        a, b = ssap.new_ssl_context(), ssap.new_ssl_context()
        self.assertIsNot(a, b)
        self.assertFalse(a.check_hostname)
        self.assertEqual(a.verify_mode, ssl.CERT_NONE)
        self.assertIs(ssl._create_default_https_context, before)
        self.assertEqual(ssl.create_default_context().verify_mode, ssl.CERT_REQUIRED)

    def test_redact_hides_the_key(self):
        out = ssap.redact(json.dumps({"payload": {"client-key": KEY}}))
        self.assertNotIn(KEY, out)


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ws = FakeWS(server=registering_server)
        self.c = make_client(self.ws, request_timeout=0.2)
        await self.c.open()
        self.ws.sent.clear()

    async def asyncTearDown(self):
        await self.c.close()

    async def test_requests_correlated_by_id_out_of_order(self):
        t1 = asyncio.create_task(self.c.request("ssap://a"))
        t2 = asyncio.create_task(self.c.request("ssap://b"))
        await asyncio.sleep(0.01)
        ids = {m["uri"]: m["id"] for m in self.ws.sent}
        self.ws.push({"type": "response", "id": ids["ssap://b"], "payload": {"returnValue": True, "v": "B"}})
        self.ws.push({"type": "response", "id": ids["ssap://a"], "payload": {"returnValue": True, "v": "A"}})
        self.assertEqual((await t1)["v"], "A")
        self.assertEqual((await t2)["v"], "B")

    async def test_malformed_messages_tolerated(self):
        t = asyncio.create_task(self.c.request("ssap://a"))
        await asyncio.sleep(0.01)
        rid = self.ws.sent[0]["id"]
        for junk in ("not json", "[1,2]", "null", b"\xff\xfe", '{"id": 5}', '{"type":"response"}',
                     json.dumps({"id": rid, "type": "response", "payload": "str-payload-is-fine"})):
            self.ws.push(junk)
        self.assertEqual(await t, {})  # non-dict payload tolerated as empty
        self.assertFalse(self.c._reader.done())  # reader survived all of it

    async def test_timeout(self):
        with self.assertRaises(ssap.RequestTimeout):
            await self.c.request("ssap://silent", timeout=0.05)
        self.assertEqual(self.c._pending, {})

    async def test_error_and_returnvalue_false(self):
        t = asyncio.create_task(self.c.request("ssap://a"))
        await asyncio.sleep(0.01)
        self.ws.push({"type": "error", "id": self.ws.sent[0]["id"], "error": "401 insufficient permissions"})
        with self.assertRaises(ssap.RequestFailed) as cm:
            await t
        self.assertEqual(cm.exception.kind, "denied")
        t = asyncio.create_task(self.c.request("ssap://b"))
        await asyncio.sleep(0.01)
        self.ws.push({"type": "response", "id": self.ws.sent[1]["id"],
                      "payload": {"returnValue": False, "errorText": "Application not found"}})
        with self.assertRaises(ssap.RequestFailed) as cm:
            await t
        self.assertEqual(cm.exception.kind, "unavailable")

    async def test_subscription_delivers_in_order_then_connection_lost(self):
        sub = await self.c.subscribe("ssap://fg")
        sid = self.ws.sent[0]["id"]
        self.assertEqual(self.ws.sent[0]["type"], "subscribe")
        for app in ("a", "b"):
            self.ws.push({"type": "response", "id": sid, "payload": {"returnValue": True, "appId": app}})
        self.assertEqual((await sub.get())["appId"], "a")
        self.assertEqual((await sub.get())["appId"], "b")
        pending = asyncio.create_task(self.c.request("ssap://x", timeout=2))
        await asyncio.sleep(0.01)
        self.ws.inbox.put_nowait(ConnectionError("closed"))
        with self.assertRaises(ssap.ConnectionLost):
            await sub.get()
        with self.assertRaises(ssap.ConnectionLost):
            await pending


if __name__ == "__main__":
    unittest.main()
