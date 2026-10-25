import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from vhome_companion.integrations import contracts
from vhome_companion.integrations.payloads import PayloadStore
from vhome_companion.integrations.store import open_db


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.dir = Path(self.t.name)

    def tearDown(self):
        self.t.cleanup()

    def test_pragmas_and_schema(self):
        c = open_db(self.dir / "q.db")
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(c.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(c.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], contracts.SCHEMA_VERSION)
        page = c.execute("PRAGMA page_size").fetchone()[0]
        self.assertEqual(c.execute("PRAGMA max_page_count").fetchone()[0], contracts.DB_MAX_BYTES // page)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"jobs", "worker_tokens"}, tables)
        self.assertFalse(c.in_transaction)

    def test_reopen_keeps_data_and_newer_version_refused(self):
        p = self.dir / "q.db"
        c = open_db(p)
        c.execute("INSERT INTO worker_tokens (id, project, sha256, created_at) VALUES ('a','brain','h',1)")
        c.close()
        c = open_db(p)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM worker_tokens").fetchone()[0], 1)
        c.execute("PRAGMA user_version=%d" % (contracts.SCHEMA_VERSION + 1))
        c.close()
        with self.assertRaises(RuntimeError):
            open_db(p)

    def test_unique_project_key(self):
        c = open_db(self.dir / "q.db")
        cols = ("id,project,op,kind,schema_version,created_at,updated_at,idempotency_key,digest,status")
        row = lambda i: (i, "brain", "o", "text", 1, 1.0, 1.0, "k" * 16, "d", "queued")
        c.execute("INSERT INTO jobs (%s) VALUES (?,?,?,?,?,?,?,?,?,?)" % cols, row("1"))
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO jobs (%s) VALUES (?,?,?,?,?,?,?,?,?,?)" % cols, row("2"))


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.p = PayloadStore(Path(self.t.name) / "payloads")

    def tearDown(self):
        self.t.cleanup()

    def test_roundtrip_mode_and_total(self):
        ref, sha = self.p.write(b"hello")
        self.assertRegex(ref, r"^[0-9a-f-]{36}\.bin$")
        self.assertEqual(len(sha), 64)
        self.assertEqual(self.p.read(ref), b"hello")
        self.assertEqual(self.p.total_bytes(), 5)
        self.assertEqual(os.stat(self.p.dir).st_mode & 0o777, 0o700)
        self.assertEqual(os.listdir(self.p.dir), [ref])      # no temp leftovers
        self.p.delete(ref)
        self.p.delete(ref)       # missing ok
        self.assertEqual(self.p.total_bytes(), 0)

    def test_bad_refs(self):
        for bad in ("../x.bin", "a.bin", "/etc/passwd", "x" * 36 + ".bin", ("0" * 36) + ".txt", None, 5,
                    "../" + "0" * 32 + ".bin"):
            with self.assertRaises(contracts.IntError) as cm:
                self.p.read(bad)
            self.assertEqual(cm.exception.code, contracts.Err.NOT_FOUND, bad)
            with self.assertRaises(contracts.IntError):
                self.p.delete(bad)

    def test_symlink_rejected(self):
        secret = Path(self.t.name) / "secret"
        secret.write_bytes(b"s")
        ref = "11111111-1111-4111-8111-111111111111.bin"
        os.symlink(secret, self.p.dir / ref)
        with self.assertRaises(contracts.IntError) as cm:
            self.p.read(ref)
        self.assertEqual(cm.exception.code, contracts.Err.NOT_FOUND)

    def test_missing_read_is_not_found(self):
        with self.assertRaises(contracts.IntError):
            self.p.read("11111111-1111-4111-8111-111111111111.bin")


class KillTests(unittest.TestCase):
    def test_kill9_mid_write_leaves_consistent_db_and_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            script = textwrap.dedent("""
                import sys, time
                from vhome_companion.integrations import contracts
                from vhome_companion.integrations.payloads import PayloadStore
                from vhome_companion.integrations.queue import Queue
                from vhome_companion.integrations.store import open_db
                class C:
                    wall = staticmethod(time.time); mono = staticmethod(time.monotonic)
                    boot_id = staticmethod(lambda: "b"); uptime = staticmethod(lambda: 1e6)
                    synced = staticmethod(lambda: True)
                d = sys.argv[1]
                q = Queue(open_db(d + "/q.db"), PayloadStore(d + "/p"), C(), disk_free=lambda: 10**12)
                print("ready", flush=True)
                for i in range(100000):
                    q.submit("p_1", "text", "key-%016d" % i, "", ("note %d" % i).encode())
            """)
            proc = subprocess.Popen([sys.executable, "-c", script, d], stdout=subprocess.PIPE,
                                    cwd=str(Path(__file__).resolve().parents[1]))
            proc.stdout.readline()
            import time
            time.sleep(1.0)
            proc.kill()
            proc.wait()
            c = open_db(Path(d) / "q.db")
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            rows = c.execute("SELECT payload_ref, payload_sha256 FROM jobs").fetchall()
            self.assertGreater(len(rows), 0)
            store = PayloadStore(Path(d) / "p")
            import hashlib
            for ref, sha in rows:
                self.assertEqual(hashlib.sha256(store.read(ref)).hexdigest(), sha)


if __name__ == "__main__":
    unittest.main()
