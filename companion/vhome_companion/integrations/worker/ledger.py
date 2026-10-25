"""Delivery ledger: the source of truth for 'already delivered' (Brain's watcher may consume files)."""
from __future__ import annotations

import os
import sqlite3
import time


class Ledger:
    def __init__(self, path: str | None = None):
        path = path or os.path.expanduser("~/.vhome-int/delivered.db")
        d = os.path.dirname(path)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS delivered (job_id TEXT PRIMARY KEY, idempotency_key TEXT, "
                        "kind TEXT, state TEXT, result_ref TEXT, sha256 TEXT, at REAL)")
        self.db.commit()
        os.chmod(path, 0o600)

    def intent(self, job_id, key, kind, sha256):
        """Write BEFORE the side effect. Never downgrades an existing delivered row."""
        self.db.execute("INSERT INTO delivered VALUES (?,?,?,'intent',NULL,?,?) ON CONFLICT(job_id) DO UPDATE "
                        "SET at=excluded.at WHERE state='intent'", (job_id, key, kind, sha256, time.time()))
        self.db.commit()

    def delivered(self, job_id, result_ref):
        self.db.execute("UPDATE delivered SET state='delivered', result_ref=?, at=? WHERE job_id=?",
                        (result_ref, time.time(), job_id))
        self.db.commit()

    def get(self, job_id):
        r = self.db.execute("SELECT state, result_ref, sha256 FROM delivered WHERE job_id=?", (job_id,)).fetchone()
        return {"state": r[0], "result_ref": r[1], "sha256": r[2]} if r else None

    def last_delivered_ref(self):
        r = self.db.execute("SELECT result_ref FROM delivered WHERE state='delivered' ORDER BY at DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def close(self):
        self.db.close()
