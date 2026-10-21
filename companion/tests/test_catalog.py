import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import catalog  # noqa: E402

HOST, VH = "192.168.1.50", "com.designinnsaeit.vhome"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
TV = {"model": "M", "firmware": "F"}


def ok_fetch(url, host):
    return ".png", PNG


def no_fetch(url, host):
    raise catalog.CatalogError("boom")


class Resp:
    def __init__(self, data, length=None):
        self._d = data
        self.headers = {"Content-Length": str(length)} if length is not None else {}

    def read(self, n=-1):
        return self._d if n < 0 else self._d[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeClient:
    def __init__(self, answers):
        self.answers = answers

    async def request(self, uri, payload=None, timeout=None):
        a = self.answers.get(uri)
        if isinstance(a, Exception):
            raise a
        if a is None:
            raise catalog.CatalogError("unexpected " + uri)
        return a


POINTS = [
    {"id": "netflix", "title": "  Netflix ", "largeIcon": f"http://{HOST}:3000/n.png"},
    {"id": "youtube.leanback.v4", "title": "YouTube", "icon": f"http://{HOST}/y.png"},
    {"id": "com.webos.app.livetv", "title": "Live TV"},
    {"id": "com.webos.app.browser", "title": "Web Browser"},
    {"id": "secret.helper", "title": "Helper", "hidden": True},
    {"id": VH, "title": "V/HOME"},
]
DEVICES = [{"id": "HDMI_1", "label": "HDMI 1", "appId": "com.webos.app.hdmi1"}]


class BuildTests(unittest.TestCase):
    def build(self, points=POINTS, devices=DEVICES, fetch=ok_fetch):
        return catalog.build(points, devices, TV, HOST, VH, fetch)

    def test_contract_shape(self):
        cat, icons = self.build()
        self.assertEqual(cat["schema"], 1)
        self.assertRegex(cat["generatedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(cat["tv"], TV)
        ids = [e["id"] for e in cat["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        for e in cat["entries"]:
            self.assertRegex(e["id"], r"^[a-zA-Z0-9._-]{2,100}$")
            self.assertTrue(1 <= len(e["title"]) <= 60)
            self.assertIn(e["kind"], ("app", "input"))
            self.assertEqual(e["source"], "companion")
            self.assertIsInstance(e["system"], bool)
            if e["icon"]:
                self.assertRegex(e["icon"], r"^[a-zA-Z0-9._-]+\.(png|jpg)$")
                self.assertIn(e["icon"], icons)

    def test_kinds_titles_and_system_rule(self):
        cat, _ = self.build()
        by = {e["id"]: e for e in cat["entries"]}
        self.assertEqual(by["netflix"]["title"], "Netflix")
        self.assertFalse(by["netflix"]["system"])
        self.assertFalse(by["com.webos.app.livetv"]["system"])
        self.assertFalse(by["com.webos.app.browser"]["system"])
        self.assertTrue(by["secret.helper"]["system"])
        self.assertTrue(by[VH]["system"])
        self.assertEqual(by["com.webos.app.hdmi1"]["kind"], "input")
        self.assertFalse(by["com.webos.app.hdmi1"]["system"])
        self.assertEqual(cat["entries"][-1]["id"], "com.webos.app.hdmi1")  # apps first, inputs last

    def test_icon_failure_keeps_entry_with_null_icon(self):
        cat, icons = self.build(fetch=no_fetch)
        self.assertEqual(len(cat["entries"]), len(POINTS) + 1)
        self.assertTrue(all(e["icon"] is None for e in cat["entries"]))
        self.assertEqual(icons, {})

    def test_large_icon_failure_falls_back_to_small_icon(self):
        def fetch(url, host):
            if "3000" in url:
                raise catalog.CatalogError("no")
            return ".png", PNG
        cat, _ = catalog.build([{"id": "ab", "title": "A", "largeIcon": f"http://{HOST}:3000/a", "icon": f"http://{HOST}/a"}],
                               [], TV, HOST, VH, fetch)
        self.assertEqual(cat["entries"][0]["icon"], "ab.png")

    def test_duplicate_ids_dropped_case_insensitive_and_inputs_win(self):
        pts = [{"id": "dup", "title": "A"}, {"id": "dup", "title": "B"}, {"id": "DUP", "title": "C"},
               {"id": "com.webos.app.hdmi1", "title": "as app"}]
        cat, _ = self.build(points=pts)
        ids = [e["id"] for e in cat["entries"]]
        self.assertEqual(ids.count("dup"), 1)
        self.assertNotIn("DUP", ids)
        hdmi = [e for e in cat["entries"] if e["id"] == "com.webos.app.hdmi1"]
        self.assertEqual([e["kind"] for e in hdmi], ["input"])

    def test_invalid_ids_dropped(self):
        pts = [{"id": "a"}, {"id": "../etc/passwd"}, {"id": "x" * 101}, {"id": ".."}, {"id": 5}, "str",
               {"id": "ok.app", "title": ""}]
        cat, _ = self.build(points=pts, devices=[])
        self.assertEqual([e["id"] for e in cat["entries"]], ["ok.app"])
        self.assertEqual(cat["entries"][0]["title"], "ok.app")

    def test_title_trimmed_to_60(self):
        cat, _ = self.build(points=[{"id": "long.one", "title": "T" * 100}], devices=[])
        self.assertEqual(len(cat["entries"][0]["title"]), 60)

    def test_cap_200_keeps_inputs(self):
        pts = [{"id": f"app{i:03d}", "title": "x"} for i in range(300)]
        cat, _ = self.build(points=pts)
        self.assertEqual(len(cat["entries"]), 200)
        self.assertIn("com.webos.app.hdmi1", [e["id"] for e in cat["entries"]])

    def test_empty_answer_is_an_error(self):
        with self.assertRaises(catalog.CatalogError):
            self.build(points=[], devices=[])
        with self.assertRaises(catalog.CatalogError):
            catalog.build(None, [], TV, HOST, VH)


class FetchIconTests(unittest.TestCase):
    def opener(self, data, length=None, calls=None):
        def op(url, timeout):
            if calls is not None:
                calls.append(url)
            return Resp(data, length)
        return op

    def test_ok_png_and_jpeg(self):
        self.assertEqual(catalog.fetch_icon(f"http://{HOST}/a.png", HOST, self.opener(PNG))[0], ".png")
        self.assertEqual(catalog.fetch_icon(f"https://{HOST}:3001/a", HOST, self.opener(b"\xff\xd8\xff\xe0abc"))[0], ".jpg")

    def test_foreign_host_rejected_before_any_request(self):
        calls = []
        for url in (f"http://evil.example/a.png", f"http://{HOST}.evil.example/a.png",
                    f"http://user:pw@{HOST}/a.png", "file:///etc/passwd", "ftp://%s/a" % HOST, "/usr/palm/a.png"):
            with self.assertRaises(catalog.CatalogError, msg=url):
                catalog.fetch_icon(url, HOST, self.opener(PNG, calls=calls))
        self.assertEqual(calls, [])

    def test_oversize_rejected(self):
        big = PNG + b"x" * catalog.MAX_ICON
        with self.assertRaises(catalog.CatalogError):
            catalog.fetch_icon(f"http://{HOST}/a.png", HOST, self.opener(big))
        with self.assertRaises(catalog.CatalogError):
            catalog.fetch_icon(f"http://{HOST}/a.png", HOST, self.opener(PNG, length=catalog.MAX_ICON + 1))

    def test_exactly_at_limit_is_ok(self):
        data = PNG + b"x" * (catalog.MAX_ICON - len(PNG))
        self.assertEqual(len(catalog.fetch_icon(f"http://{HOST}/a.png", HOST, self.opener(data))[1]), catalog.MAX_ICON)

    def test_wrong_magic_rejected(self):
        for data in (b"<html>", b"GIF89a....", b""):
            with self.assertRaises(catalog.CatalogError):
                catalog.fetch_icon(f"http://{HOST}/a.png", HOST, self.opener(data))


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "tv-catalog"

    def leftovers(self):
        return [p.name for p in Path(self.tmp.name).iterdir() if p.name != "tv-catalog"]

    def good(self):
        return catalog.build(POINTS, DEVICES, TV, HOST, VH, ok_fetch)

    def test_writes_catalog_and_icons(self):
        cat, icons = self.good()
        catalog.write_atomic(self.out, cat, icons)
        data = json.loads((self.out / "catalog.json").read_text())
        self.assertEqual(data["schema"], 1)
        for e in data["entries"]:
            if e["icon"]:
                self.assertTrue((self.out / "icons" / e["icon"]).is_file())
        self.assertEqual(self.leftovers(), [])

    def test_replaces_previous_and_removes_stale_icons(self):
        cat, icons = self.good()
        catalog.write_atomic(self.out, cat, icons)
        cat2, icons2 = catalog.build([{"id": "only.one", "title": "One"}], [], TV, HOST, VH, no_fetch)
        catalog.write_atomic(self.out, cat2, icons2)
        self.assertEqual([e["id"] for e in json.loads((self.out / "catalog.json").read_text())["entries"]], ["only.one"])
        self.assertEqual(list((self.out / "icons").iterdir()), [])
        self.assertEqual(self.leftovers(), [])

    def test_broken_catalog_keeps_previous(self):
        cat, icons = self.good()
        catalog.write_atomic(self.out, cat, icons)
        before = (self.out / "catalog.json").read_text()
        bad = json.loads(json.dumps(cat))
        bad["entries"][0]["icon"] = "missing.png"  # references an icon that was never written
        with self.assertRaises(catalog.CatalogError):
            catalog.write_atomic(self.out, bad, {})
        self.assertEqual((self.out / "catalog.json").read_text(), before)
        self.assertEqual(self.leftovers(), [])

    def test_unserialisable_catalog_keeps_previous(self):
        cat, icons = self.good()
        catalog.write_atomic(self.out, cat, icons)
        before = (self.out / "catalog.json").read_text()
        with self.assertRaises(TypeError):
            catalog.write_atomic(self.out, {"entries": [object()]}, {})
        self.assertEqual((self.out / "catalog.json").read_text(), before)
        self.assertEqual(self.leftovers(), [])


class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "tv-catalog"

    def client(self, **over):
        a = {catalog.LIST_URI: {"launchPoints": POINTS}, catalog.INPUT_URI: {"devices": DEVICES},
             "ssap://system/getSystemInfo": {"modelName": "43NU885BPLA"},
             "ssap://com.webos.service.update/getCurrentSWInformation": {"major_ver": "04", "minor_ver": "05.30"}}
        a.update(over)
        return FakeClient(a)

    async def test_sync_end_to_end(self):
        r = await catalog.sync(self.client(), self.out, HOST, VH, ok_fetch)
        data = json.loads((self.out / "catalog.json").read_text())
        self.assertEqual(r["entries"], len(data["entries"]))
        self.assertEqual(data["tv"], {"model": "43NU885BPLA", "firmware": "04.05.30"})

    async def test_partial_or_corrupt_answers_keep_previous(self):
        await catalog.sync(self.client(), self.out, HOST, VH, ok_fetch)
        before = (self.out / "catalog.json").read_text()
        for bad in ({catalog.LIST_URI: {"returnValue": True}},
                    {catalog.INPUT_URI: {}},
                    {catalog.LIST_URI: {"launchPoints": "garbage"}},
                    {catalog.LIST_URI: {"launchPoints": []}, catalog.INPUT_URI: {"devices": []}}):
            with self.assertRaises(catalog.CatalogError):
                await catalog.sync(self.client(**bad), self.out, HOST, VH, ok_fetch)
            self.assertEqual((self.out / "catalog.json").read_text(), before)

    async def test_request_error_keeps_previous(self):
        await catalog.sync(self.client(), self.out, HOST, VH, ok_fetch)
        before = (self.out / "catalog.json").read_text()
        with self.assertRaises(RuntimeError):
            await catalog.sync(self.client(**{catalog.INPUT_URI: RuntimeError("denied")}), self.out, HOST, VH, ok_fetch)
        self.assertEqual((self.out / "catalog.json").read_text(), before)


if __name__ == "__main__":
    unittest.main()


class EdgeColorTests(unittest.TestCase):
    @staticmethod
    def png(w, h, px, ctype=6):
        import struct
        import zlib

        ch = {2: 3, 6: 4}[ctype]
        raw = b"".join(b"\x00" + bytes(px) * w for _ in range(h))
        c = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
        return b"\x89PNG\r\n\x1a\n" + c(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)) + c(b"IDAT", zlib.compress(raw)) + c(b"IEND", b"")

    def test_solid_and_transparent_and_garbage(self):
        from vhome_companion.pngcolor import edge_color

        self.assertEqual(edge_color(self.png(40, 40, (20, 146, 255, 255))), "#1492ff")
        self.assertEqual(edge_color(self.png(40, 40, (0, 0, 0, 0))), "#ffffff")  # transparent border -> white
        self.assertIsNone(edge_color(b"not a png"))
        self.assertIsNone(edge_color(self.png(40, 40, (1, 2, 3, 255))[:60]))  # truncated
