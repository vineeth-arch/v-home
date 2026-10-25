"""VNode shared contract (Wave 0). Agents consume this file; changes go through the orchestrator.

The API shape lives in docs/contracts/vnode-api-v1.md. Everything here is pure: no I/O.
"""
import enum
import re
from typing import Protocol

API_VERSION = 1
PORT = 8443
SERVICE_TYPE = "_vhome._tcp"          # DNS-SD; discovery only, never trust
MAX_BODY = 4096                       # bytes, every POST
NONCE_TTL_S = 30.0                    # monotonic
PAIR_CODE_TTL_S = 300.0               # monotonic, single use
PAIR_MAX_TRIES = 5                    # per code; then the code is burned
POWER_ACTION_GAP_S = 60.0             # reboot / shutdown / restart-service
LAUNCH_WAIT_S = 11.0                  # API waits this long for confirmation
LED_STATE_FILE = "/run/vhome-leds/state.json"   # written by vhome-leds (tmpfs), read by the API
LED_CONFIG_FILE = "leds.json"         # in the vnode state dir: {"enabled": bool, "brightness": 1..4}
ADMIN_SOCKET = "admin.sock"           # in $RUNTIME_DIRECTORY (/run/vhome-vnode), mode 0600, local CLI only


class TvState(str, enum.Enum):
    CONNECTED = "connected"
    STANDBY = "standby"
    UNREACHABLE = "unreachable"
    PAIRING_REQUIRED = "pairing_required"
    CERTIFICATE_MISMATCH = "certificate_mismatch"
    PERMISSION_DENIED = "permission_denied"
    LAUNCHER_MISSING = "launcher_missing"
    UNKNOWN = "unknown"


class WatcherState(str, enum.Enum):
    WATCHING = "watching"
    USER_PAUSED = "user_paused"
    SAFETY_PAUSED = "safety_paused"   # a breaker tripped
    DISABLED = "disabled"             # handed over to the phone; no auto re-enable
    NOT_READY = "not_ready"           # not paired / no Home id


class Outcome(str, enum.Enum):
    ACCEPTED = "accepted"     # TV/OS took the command; effect not yet seen
    CONFIRMED = "confirmed"   # effect observed (e.g. V/HOME in front, state persisted)
    FAILED = "failed"
    UNKNOWN = "unknown"       # timeout / link lost: refresh status before any retry


# Headline order: the first matching problem wins. Pause states rank above TV reachability so the
# owner sees "paused" even when the TV is off.
_TV_PROBLEMS = (TvState.PAIRING_REQUIRED, TvState.CERTIFICATE_MISMATCH, TvState.PERMISSION_DENIED,
                TvState.LAUNCHER_MISSING)


def headline(tv: str, watcher: str) -> str:
    """One state for the app's hero line, from tv.state and watcher.state values."""
    if watcher == WatcherState.DISABLED.value:
        return "disabled"
    if tv in {s.value for s in _TV_PROBLEMS}:
        return tv
    if watcher in (WatcherState.USER_PAUSED.value, WatcherState.SAFETY_PAUSED.value):
        return watcher
    if tv in (TvState.CONNECTED.value, TvState.STANDBY.value, TvState.UNREACHABLE.value):
        return tv
    return TvState.UNKNOWN.value


def capabilities(power_on_launch=False, leds=False):
    return {
        "launch": "supported", "pause": "supported", "tv_pair": "supported",
        "diagnostics": "supported", "device_controls": "supported",
        "leds": "supported" if leds else "unavailable",
        "timer": "unavailable",          # V/TV Sleep stays the timer authority; no confirmed transport
        "catalog_sync": "unavailable",   # app builds stay on the Mac/CI
        "power_on_launch": "unverified" if power_on_launch else "disabled",
    }


def outcome(kind, detail=""):
    return {"outcome": Outcome(kind).value, "detail": redact(detail)[:300]}


_SECRET = re.compile(r'((?<![A-Za-z_-])"?(?:client-key|token|code|nonce|authorization)"?\s*[:=]\s*"?)(?:Bearer\s+)?[^",\s}]+', re.I)


def redact(text) -> str:
    return _SECRET.sub(r"\1<redacted>", str(text))


class Controller(Protocol):
    """Implemented by tvcontrol.TvController (S1); consumed by api.py (S2). All coroutines are safe to
    call from aiohttp handlers; none blocks longer than its documented bound."""

    def status(self) -> dict:
        """{"tv": {...}, "watcher": {...}} exactly as in docs/contracts/vnode-api-v1.md (no node/api keys)."""

    async def pause(self, minutes: "int | None") -> dict:
        """Persist and apply. minutes None = until resume; 1..1440 otherwise. Returns outcome(confirmed)."""

    async def resume(self) -> dict:
        ...

    async def set_enabled(self, enabled: bool) -> dict:
        """False = handed to the phone (persisted; cancels pending launch/recovery). True = take over again."""

    async def launch(self) -> dict:
        """Explicit 'open V/HOME'. Waits up to LAUNCH_WAIT_S: confirmed | accepted | failed | unknown."""

    async def start_tv_pair(self, host: str, repin: bool) -> dict:
        """Starts one background pairing job (TV shows its prompt, 60 s). Progress in status()['tv']['pairing'].
        Raises ValueError for a bad host; returns outcome(failed, 'busy') if a job is already running."""

    async def discover_tvs(self) -> list:
        """SSDP search, <= 4 s. [{"host": "192.168.1.20", "pinned": bool}]."""

    def diagnostics(self) -> dict:
        """Bounded, redacted: recent log lines (<= 200), TV checks, counters."""

    async def close(self) -> None:
        """Graceful shutdown: cancel tasks, close the TV link, flush persisted state."""
