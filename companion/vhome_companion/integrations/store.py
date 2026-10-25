"""SQLite connection + schema for the integrations queue. Explicit transactions, WAL, synchronous=FULL."""
import sqlite3

from . import contracts

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project TEXT NOT NULL, phone_id TEXT, op TEXT NOT NULL, kind TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '', schema_version INTEGER NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  idempotency_key TEXT NOT NULL, digest TEXT NOT NULL,
  payload_ref TEXT, payload_sha256 TEXT, payload_bytes INTEGER,
  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL,
  lease_boot_id TEXT, lease_expires_mono REAL, claim_token TEXT, claimed_by TEXT,
  result_ref TEXT, error_code TEXT, error_msg TEXT, retry_safe INTEGER NOT NULL DEFAULT 0,
  retention_until REAL,
  UNIQUE(project, idempotency_key)
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(project, status, next_attempt_at);
CREATE TABLE IF NOT EXISTS worker_tokens (
  id TEXT PRIMARY KEY, project TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL, revoked_at REAL
);
"""


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=2.0)
    conn.execute("PRAGMA busy_timeout=2000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver > contracts.SCHEMA_VERSION:
        conn.close()
        raise RuntimeError("queue db schema %d is newer than supported %d" % (ver, contracts.SCHEMA_VERSION))
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.execute("PRAGMA max_page_count=%d" % (contracts.DB_MAX_BYTES // page))
    if ver == 0:
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA user_version=%d" % contracts.SCHEMA_VERSION)
    return conn
