"""Real websockets + real TLS against a local fake TV. Skipped when `websockets` is not installed
(use companion/.venv). Exercises the one thing the fake socket cannot: ws.transport's ssl_object."""
import asyncio
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import ssap  # noqa: E402

try:
    from websockets.asyncio.server import serve
except ImportError:
    serve = None


@unittest.skipIf(serve is None or not shutil.which("openssl"), "needs websockets and openssl")
class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        crt, key = f"{tmp.name}/c.pem", f"{tmp.name}/k.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=tv",
                        "-days", "1", "-keyout", key, "-out", crt], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        der = ssl.PEM_cert_to_DER_cert(open(crt).read())
        self.pin = hashlib.sha256(der).hexdigest()
        self.received = []

        async def handler(ws):
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                if msg["type"] == "register":
                    await ws.send(json.dumps({"type": "registered", "id": msg["id"],
                                              "payload": {"client-key": "K"}}))
                elif msg["type"] == "subscribe":
                    await ws.send(json.dumps({"type": "response", "id": msg["id"],
                                              "payload": {"returnValue": True, "appId": "com.webos.app.home"}}))
                else:
                    await ws.send(json.dumps({"type": "response", "id": msg["id"],
                                              "payload": {"returnValue": True}}))

        self.server = await serve(handler, "127.0.0.1", 0, ssl=ctx)
        self.addAsyncCleanup(self._stop)
        old, ssap.PORT = ssap.PORT, self.server.sockets[0].getsockname()[1]
        self.addCleanup(setattr, ssap, "PORT", old)

    async def _stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_pinned_connection_works(self):
        c = ssap.Client("127.0.0.1", "K", self.pin)
        await c.open()
        sub = await c.subscribe("ssap://fg")
        self.assertEqual((await sub.get())["appId"], "com.webos.app.home")
        self.assertEqual(await c.request("ssap://system.launcher/launch", {"id": "x"}), {"returnValue": True})
        await c.close()

    async def test_wrong_pin_never_sends_the_key(self):
        c = ssap.Client("127.0.0.1", "K", "0" * 64)
        with self.assertRaises(ssap.PinMismatch):
            await c.open()
        await asyncio.sleep(0.1)
        self.assertEqual(self.received, [])

    async def test_pairing_captures_cert_hash(self):
        c = ssap.Client("127.0.0.1", None, None, trust_new=True)
        await c.open()
        self.assertEqual(c.cert_sha256, self.pin)
        await c.close()


if __name__ == "__main__":
    unittest.main()
