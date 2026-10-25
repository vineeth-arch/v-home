"""Paired phones, one-time pairing codes and single-use request nonces."""
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .. import cli
from . import contracts

log = logging.getLogger("vhome.phones")
PHONES_FILE = "phones.json"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_NONCE_KEEP_S = 120.0     # consumed (and expired) nonces stay known this long, so a retry gets 409 not 410
_NONCE_MAX = 256


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _clean_name(name):
    name = "".join(c for c in str(name) if c.isprintable()).strip()[:40].strip()
    return name or "Phone"


class PhoneRegistry:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / PHONES_FILE
        self._phones = []
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, list) or not all(
                    isinstance(p, dict) and {"id", "name", "token_sha256", "created"} <= p.keys() for p in data):
                raise ValueError("unexpected structure")
            self._phones = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:  # fail closed: nobody is paired until the owner pairs again
            log.warning("%s unreadable (%s); treating as no paired phones", self.path, e)

    def _save(self):
        cli.write_private(self.path, json.dumps(self._phones, indent=1))

    def add(self, name):
        token = secrets.token_urlsafe(32)
        ids = {p["id"] for p in self._phones}
        pid = "p_" + secrets.token_hex(3)
        while pid in ids:
            pid = "p_" + secrets.token_hex(3)
        self._phones.append({"id": pid, "name": _clean_name(name), "token_sha256": _sha(token),
                             "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self._save()
        return pid, token

    def check(self, token):
        digest = _sha(token)
        found = None
        for p in self._phones:  # no early exit: constant work per entry
            if hmac.compare_digest(digest, p["token_sha256"]):
                found = p["id"]
        return found

    def revoke(self, phone_id):
        kept = [p for p in self._phones if p["id"] != phone_id]
        if len(kept) == len(self._phones):
            return False
        self._phones = kept
        self._save()
        return True

    def list(self):
        return [{"id": p["id"], "name": p["name"], "created": p["created"]} for p in self._phones]


def normalize_code(code):
    code = "".join(c for c in str(code).upper() if c not in " -")
    return code.translate(str.maketrans("ILO", "110"))


class PairingCodes:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._code = None
        self._expires = 0.0
        self._tries = 0

    def new(self):
        self._code = "".join(secrets.choice(_CROCKFORD) for _ in range(8))
        self._expires = self._clock() + contracts.PAIR_CODE_TTL_S
        self._tries = 0
        return self._code

    def redeem(self, code):
        """'ok' (code consumed) | 'wrong' | 'none' (no live code: expired, burned or never made)."""
        if self._code is None or self._clock() >= self._expires:
            self._code = None
            return "none"
        if hmac.compare_digest(normalize_code(code).encode(), self._code.encode()):
            self._code = None
            return "ok"
        self._tries += 1
        if self._tries >= contracts.PAIR_MAX_TRIES:
            self._code = None
        return "wrong"


class Nonces:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._open = OrderedDict()      # nonce -> issued_at
        self._used = OrderedDict()      # nonce -> (used_at, result)

    def _prune(self):
        now = self._clock()
        for table, at in ((self._open, lambda v: v), (self._used, lambda v: v[0])):
            while table:
                k = next(iter(table))
                if now - at(table[k]) <= _NONCE_KEEP_S:
                    break
                del table[k]

    def issue(self):
        self._prune()
        nonce = secrets.token_urlsafe(16)
        self._open[nonce] = self._clock()
        while len(self._open) > _NONCE_MAX:
            self._open.popitem(last=False)
        return nonce

    def consume(self, nonce):
        """('ok', None) | ('expired', None) | ('duplicate', previous_result) | ('unknown', None)."""
        self._prune()
        if nonce in self._used:
            return "duplicate", self._used[nonce][1]
        issued = self._open.pop(nonce, None)
        if issued is None:
            return "unknown", None
        if self._clock() - issued > contracts.NONCE_TTL_S:
            return "expired", None
        self._used[nonce] = (self._clock(), None)
        return "ok", None

    def record(self, nonce, result):
        if nonce in self._used:
            self._used[nonce] = (self._used[nonce][0], result)
