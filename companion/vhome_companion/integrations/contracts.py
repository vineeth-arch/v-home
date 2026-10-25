"""VNode integrations shared contract (Wave 0). Agents consume this file; changes go through the orchestrator.

The wire shape lives in docs/contracts/vnode-int-api-v1.md. Everything here is pure: no I/O.

Processes:
  vhome-vnode (TV, user vhome)  -- intproxy.py forwards /v1/inbox/* and /v1/int/worker/* over a unix socket
  vhome-integrations (user vhome-int) -- owns the SQLite queue + payload dir; trusts the socket peer
  Mac worker (launchd) -- polls /v1/int/worker/* over TLS, delivers to Brain on localhost
"""
import enum
import re
import unicodedata
from typing import Protocol

SCHEMA_VERSION = 1
INT_API = 1                                   # advertised in /v1/info as "int": 1

# ---- sockets / paths (Pi) ------------------------------------------------------------------
SOCKET_PATH = "/run/vhome-integrations/int.sock"     # 0660 group vhome-intsock; env VHOME_INT_SOCKET overrides
ADMIN_SOCKET_PATH = "/run/vhome-integrations/admin.sock"  # 0600 vhome-int; vnode-int CLI only
STATE_DIR = "/var/lib/vhome-integrations"            # 0700 vhome-int; env VHOME_INT_STATE overrides
DB_NAME = "queue.db"
PAYLOAD_DIR = "payloads"                             # inside STATE_DIR; files are <uuid4>.bin

# Header the proxy sets for phone routes after phone-token auth. The service trusts it ONLY because
# the socket is group-restricted. The proxy MUST drop any client-sent copy.
PHONE_HEADER = "X-VNode-Phone"
NONCE_HEADER = "X-VNode-Nonce"
KEY_HEADER = "X-Idempotency-Key"
KIND_HEADER = "X-Inbox-Kind"
LABEL_HEADER = "X-Label"
CLAIM_HEADER = "X-Claim-Token"       # payload GET; never in the query string (would reach access logs)
# Headers the proxy forwards from client to service (plus Content-Type). Anything else is dropped.
FORWARD_HEADERS = ("Content-Type", KEY_HEADER, KIND_HEADER, LABEL_HEADER, CLAIM_HEADER)
PROXY_WORKER_MAX_BODY = 8 * 1024     # worker bodies are small; read cap before the token is checked
# Response headers the proxy passes back.
RETURN_HEADERS = ("Content-Type", "Retry-After", "X-Payload-Sha256")

PHONE_PREFIX = "/v1/inbox/"
WORKER_PREFIX = "/v1/int/worker/"

# ---- proxy limits (inside the TV process) --------------------------------------------------
PROXY_MAX_BODY = 300 * 1024          # hard cap, read by streaming, never buffered past this
PROXY_CONCURRENCY = 2                # asyncio.Semaphore
PROXY_CONNECT_TIMEOUT_S = 1.0
PROXY_TOTAL_TIMEOUT_S = 8.0
PROXY_ROUTE_TIMEOUT_S = 12           # api._timeout_for for both prefixes
BREAKER_FAILS = 3                    # consecutive socket failures ...
BREAKER_OPEN_S = 30.0                # ... -> instant 503 for this long
AUTH_FAIL_LIMIT_PER_MIN = 10         # global, worker routes; then 429 without forwarding

# ---- payload limits ------------------------------------------------------------------------
MAX_TEXT = 8 * 1024
MAX_URL = 2 * 1024
MAX_DOC = 256 * 1024
MAX_LABEL = 40
MAX_SNAPSHOT = 2 * 1024              # worker brain-status POST, kept in RAM only
MAX_RESULT_REF = 128
MAX_ERROR_MSG = 200

# ---- queue limits --------------------------------------------------------------------------
MAX_LIVE_JOBS = 200                  # queued + claimed + processing + unknown
MAX_ROWS = 500                       # total; terminal rows purged oldest-first beyond this
MAX_PAYLOAD_DIR_BYTES = 8 * 1024 * 1024
DB_MAX_BYTES = 4 * 1024 * 1024       # PRAGMA max_page_count = DB_MAX_BYTES // page_size
DISK_RESERVE_BYTES = 400 * 1024 * 1024   # refuse new jobs below this free space (statvfs on STATE_DIR)
DISK_WARN_BYTES = 300 * 1024 * 1024      # health warning (already below reserve -> refusing)
SUBMIT_PER_MIN_PER_PHONE = 30
LIST_MAX = 50

MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 900
BACKOFF_JITTER = 0.2
CLAIM_LEASE_S = 120.0                # claimed -> unknown if not started/completed in time (monotonic)
PROCESSING_LEASE_S = 300.0           # processing -> unknown
WORKER_STALE_S = 180.0               # "Mac not reporting"
SNAPSHOT_STALE_S = 180.0             # Brain status never shows OK when older

RETENTION_DONE_S = 7 * 86400         # completed / cancelled
RETENTION_FAILED_S = 30 * 86400
PAYLOAD_GRACE_S = 86400              # payload kept this long after completed (deleted at once on cancel)
RETENTION_MIN_UPTIME_S = 600.0       # never purge before this uptime, and only when clock is synced

# ---- Mac worker ----------------------------------------------------------------------------
WORKER_PACE_S = 1.0
WORKER_MAX_PER_RUN = 20
WORKER_POLL_S = 30.0
WORKER_ENV_FILE = "~/.vhome-int/worker.env"   # 0600; VNODE_WORKER_TOKEN, BRAIN_VNODE_TOKEN, VNODE_NODE_ID
WORKER_LEDGER = "~/.vhome-int/delivered.db"


class Status(str, enum.Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    COMPLETED = "completed"     # accepted by Brain inbox. NEVER "processed into vault".
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"         # lease expired; outcome not known


LIVE = frozenset({Status.QUEUED, Status.CLAIMED, Status.PROCESSING, Status.UNKNOWN})
TERMINAL = frozenset({Status.COMPLETED, Status.FAILED, Status.CANCELLED})

# Allowed transitions (from -> {to}). Enforced in queue.py; a disallowed move is a bug -> raise.
TRANSITIONS = {
    Status.QUEUED: {Status.CLAIMED, Status.CANCELLED},
    Status.CLAIMED: {Status.PROCESSING, Status.COMPLETED, Status.FAILED, Status.UNKNOWN, Status.QUEUED},
    Status.PROCESSING: {Status.COMPLETED, Status.FAILED, Status.UNKNOWN, Status.QUEUED},
    Status.UNKNOWN: {Status.QUEUED, Status.COMPLETED, Status.FAILED},   # late complete accepted
    Status.FAILED: {Status.QUEUED},                                     # retry only if retry_safe
    Status.COMPLETED: set(),
    Status.CANCELLED: set(),
}
# claimed/processing -> queued only on worker 'fail' with retryable=true and attempts < MAX_ATTEMPTS.


class Kind(str, enum.Enum):
    TEXT = "text"
    URL = "url"
    MD = "md"
    TXT = "txt"


OP_FOR_KIND = {Kind.TEXT: "brain.capture_text", Kind.URL: "brain.capture_url",
               Kind.MD: "brain.capture_doc", Kind.TXT: "brain.capture_doc"}
MAX_FOR_KIND = {Kind.TEXT: MAX_TEXT, Kind.URL: MAX_URL, Kind.MD: MAX_DOC, Kind.TXT: MAX_DOC}
RETRY_SAFE_OPS = frozenset({"brain.capture_text", "brain.capture_url", "brain.capture_doc"})
PROJECT_BRAIN = "brain"


# ---- errors (v1 envelope: {"error": code, "detail": str, ...extra}) ------------------------
class Err(str, enum.Enum):
    BAD_REQUEST = "bad_request"                 # 400
    UNAUTHORIZED = "unauthorized"               # 401
    NOT_FOUND = "not_found"                     # 404
    KEY_CONFLICT = "key_conflict"               # 409 same key, different digest
    NOT_CANCELLABLE = "not_cancellable"         # 409 cancel when not queued
    NOT_RETRYABLE = "not_retryable"             # 409 retry when not failed / not retry_safe
    STALE_CLAIM = "stale_claim"                 # 409 claim_token does not match
    DUPLICATE = "duplicate"                     # 409 nonce reuse (proxy, from api._consume)
    TOO_LARGE = "too_large"                     # 413
    UNSUPPORTED_KIND = "unsupported_kind"       # 415
    RATE_LIMITED = "rate_limited"               # 429 submit rate / auth-fail throttle
    QUEUE_FULL = "queue_full"                   # 429 + Retry-After
    UNAVAILABLE = "integrations_unavailable"    # 503 (proxy: socket down / breaker open / busy)
    DISK_RESERVE = "disk_reserve"               # 507


ERR_STATUS = {Err.BAD_REQUEST: 400, Err.UNAUTHORIZED: 401, Err.NOT_FOUND: 404, Err.KEY_CONFLICT: 409,
              Err.NOT_CANCELLABLE: 409, Err.NOT_RETRYABLE: 409, Err.STALE_CLAIM: 409, Err.DUPLICATE: 409,
              Err.TOO_LARGE: 413, Err.UNSUPPORTED_KIND: 415, Err.RATE_LIMITED: 429, Err.QUEUE_FULL: 429,
              Err.UNAVAILABLE: 503, Err.DISK_RESERVE: 507}


class IntError(Exception):
    """Raised by validators / queue ops; server maps to the v1 envelope via ERR_STATUS."""

    def __init__(self, code: Err, detail: str = "", **extra):
        super().__init__(detail)
        self.code, self.detail, self.extra = Err(code), detail, extra

    @property
    def status(self) -> int:
        return ERR_STATUS[self.code]

    def body(self) -> dict:
        return {"error": self.code.value, "detail": self.detail, **self.extra}


# ---- validators (pure) ---------------------------------------------------------------------
_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_LABEL_BAD = re.compile(r"[^A-Za-z0-9 ._-]")
_URL = re.compile(r"^https?://\S+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def validate_key(key) -> str:
    if not isinstance(key, str) or not _KEY.match(key):
        raise IntError(Err.BAD_REQUEST, "idempotency key must be 16-64 chars [A-Za-z0-9_-]")
    return key


def validate_job_id(job_id) -> str:
    if not isinstance(job_id, str) or not _UUID.match(job_id):
        raise IntError(Err.NOT_FOUND, "no such job")
    return job_id


def sanitize_label(label) -> str:
    """Display-only. Never used as a filename. Strips anything outside [A-Za-z0-9 ._-], caps at 40."""
    if not label:
        return ""
    label = unicodedata.normalize("NFKD", str(label))
    return _LABEL_BAD.sub("", label).strip()[:MAX_LABEL]


def validate_kind(kind) -> Kind:
    try:
        return Kind(kind)
    except ValueError:
        raise IntError(Err.UNSUPPORTED_KIND, "kind must be text, url, md or txt") from None


def validate_payload(kind: Kind, body: bytes) -> bytes:
    """Strict UTF-8, no NUL, non-empty, per-kind size. URL: ^https?:// and no whitespace. Never fetched."""
    if len(body) > MAX_FOR_KIND[kind]:
        raise IntError(Err.TOO_LARGE, "%s over %d bytes" % (kind.value, MAX_FOR_KIND[kind]))
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise IntError(Err.BAD_REQUEST, "payload must be UTF-8") from None
    if "\x00" in text:
        raise IntError(Err.BAD_REQUEST, "payload contains NUL")
    if not text.strip():
        raise IntError(Err.BAD_REQUEST, "payload is empty")
    if kind is Kind.URL and not _URL.match(text.strip()):
        raise IntError(Err.BAD_REQUEST, "url must be http(s) with no whitespace")
    return body


def backoff_s(attempts: int, rand: float) -> float:
    """rand in [0,1). min(30*2^n, 900) +-20 %."""
    base = min(BACKOFF_BASE_S * (2 ** max(attempts, 0)), BACKOFF_CAP_S)
    return base * (1 - BACKOFF_JITTER + 2 * BACKOFF_JITTER * rand)


_SECRET = re.compile(r'((?<![A-Za-z_-])"?(?:token|authorization|nonce|claim_token|secret)"?\s*[:=]\s*"?)(?:Bearer\s+)?[^",\s}]+', re.I)


def redact(text) -> str:
    """Logs carry job id, kind, size, status only. This is the safety net for anything else."""
    return _SECRET.sub(r"\1<redacted>", str(text))


class Clock(Protocol):
    """Injected everywhere time matters, so tests can drive it. No RTC on the Pi."""

    def wall(self) -> float:
        """time.time(); informational only (created_at, retention) and wrong until NTP sync."""

    def mono(self) -> float:
        """time.monotonic(); leases. Only comparable within one boot."""

    def boot_id(self) -> str:
        """/proc/sys/kernel/random/boot_id; a lease from another boot is expired."""

    def uptime(self) -> float:
        """Seconds since boot."""

    def synced(self) -> bool:
        """True once the wall clock is NTP-synced (timedatectl / adjtimex). Retention waits for it."""
