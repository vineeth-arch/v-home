import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.vnode import contracts  # noqa: E402
from vhome_companion.vnode.phones import Nonces, PairingCodes, PhoneRegistry  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PhoneRegistryTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_add_check_revoke_and_only_hash_stored(self):
        reg = PhoneRegistry(self.dir)
        pid, token = reg.add("  Pixel\n8  ")
        self.assertRegex(pid, r"^p_[0-9a-f]{6}$")
        self.assertEqual(reg.check(token), pid)
        self.assertIsNone(reg.check(token + "x"))
        self.assertNotIn(token, (self.dir / "phones.json").read_text())
        self.assertEqual(reg.list()[0]["name"], "Pixel8")
        self.assertEqual(oct((self.dir / "phones.json").stat().st_mode & 0o777), "0o600")
        self.assertTrue(PhoneRegistry(self.dir).check(token))  # survives restart
        self.assertTrue(reg.revoke(pid))
        self.assertFalse(reg.revoke(pid))
        self.assertIsNone(reg.check(token))

    def test_name_limited_to_40(self):
        reg = PhoneRegistry(self.dir)
        reg.add("x" * 100)
        self.assertEqual(len(reg.list()[0]["name"]), 40)

    def test_corrupt_file_fails_closed(self):
        (self.dir / "phones.json").write_text("{not json")
        with self.assertLogs("vhome.phones", "WARNING"):
            reg = PhoneRegistry(self.dir)
        self.assertEqual(reg.list(), [])
        self.assertIsNone(reg.check("anything"))


class PairingCodesTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.codes = PairingCodes(self.clock)

    def test_single_use_and_normalising(self):
        code = self.codes.new()
        self.assertRegex(code, r"^[0-9A-HJKMNP-TV-Z]{8}$")
        self.assertEqual(self.codes.redeem(code[:4].lower() + " - " + code[4:]), "ok")
        self.assertEqual(self.codes.redeem(code), "none")

    def test_lookalikes(self):
        self.codes.new()
        self.codes._code = "10ABCDEF"
        self.assertEqual(self.codes.redeem("iOabcdef"), "ok")

    def test_five_wrong_tries_burn_the_code(self):
        code = self.codes.new()
        for _ in range(contracts.PAIR_MAX_TRIES):
            self.assertEqual(self.codes.redeem("WRONGWRO"), "wrong")
        self.assertEqual(self.codes.redeem(code), "none")

    def test_expiry_and_replacement(self):
        old = self.codes.new()
        new = self.codes.new()
        self.assertEqual(self.codes.redeem(old if old != new else "ZZZZZZZZ"), "wrong")
        self.clock.t += contracts.PAIR_CODE_TTL_S + 1
        self.assertEqual(self.codes.redeem(new), "none")


class NoncesTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.n = Nonces(self.clock)

    def test_ok_duplicate_with_previous(self):
        a = self.n.issue()
        self.assertEqual(self.n.consume(a), ("ok", None))
        self.n.record(a, {"outcome": "confirmed"})
        self.assertEqual(self.n.consume(a), ("duplicate", {"outcome": "confirmed"}))
        self.clock.t += 100
        self.assertEqual(self.n.consume(a)[0], "duplicate")
        self.clock.t += 30
        self.assertEqual(self.n.consume(a)[0], "unknown")

    def test_expired_and_unknown(self):
        a = self.n.issue()
        self.clock.t += contracts.NONCE_TTL_S + 1
        self.assertEqual(self.n.consume(a), ("expired", None))
        self.assertEqual(self.n.consume("nope"), ("unknown", None))

    def test_cap_drops_oldest(self):
        first = self.n.issue()
        for _ in range(256):
            self.n.issue()
        self.assertEqual(self.n.consume(first), ("unknown", None))


if __name__ == "__main__":
    unittest.main()
