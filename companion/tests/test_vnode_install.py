import os
import subprocess
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "vnode", "install-pi.sh")


def bash(code, stdin=""):
    return subprocess.run(["bash", "-c", f'source "{SCRIPT}"; {code}'], input=stdin, text=True,
                          capture_output=True)


@unittest.skipUnless(os.path.exists(SCRIPT), "vnode/install-pi.sh not present (bundle without ops files)")
class InstallScriptLogic(unittest.TestCase):
    def test_version_ge(self):
        for a, b, ok in (("13", "12", True), ("12", "12", True), ("11", "12", False), ("12.1", "12", True),
                         ("9", "12", False)):
            self.assertEqual(bash(f"version_ge {a} {b}").returncode == 0, ok, (a, b))

    def test_archive_names(self):
        good = "vhome-vnode\nvhome-vnode/key.pem\nvhome-vnode/sub/x\n"
        self.assertEqual(bash("archive_names_ok", good).returncode, 0)
        for bad in ("/etc/passwd\n", "vhome-vnode/../x\n", "../x\n", "vhome-vnode/a/..\n", "other/file\n"):
            self.assertNotEqual(bash("archive_names_ok", bad).returncode, 0, bad)

    def test_archive_types(self):
        ok = "drwx------ a/b 0 2026-01-01 00:00 vhome-vnode/\n-rw------- a/b 5 2026-01-01 00:00 vhome-vnode/x\n"
        self.assertEqual(bash("archive_types_ok", ok).returncode, 0)
        link = "lrwxrwxrwx a/b 0 2026-01-01 00:00 vhome-vnode/l -> /etc/passwd\n"
        self.assertNotEqual(bash("archive_types_ok", link).returncode, 0)


if __name__ == "__main__":
    unittest.main()
