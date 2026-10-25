import os
import re
import shutil
import subprocess
import unittest

VNODE = os.path.join(os.path.dirname(__file__), "..", "..", "vnode")
SCRIPT = os.path.join(VNODE, "install-pi.sh")
INT_UNIT = os.path.join(VNODE, "systemd", "vhome-integrations.service")
TV_UNIT = os.path.join(VNODE, "systemd", "vhome-vnode.service")
DELIVER_UNIT = os.path.join(VNODE, "systemd", "vhome-int-deliver.service")


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


def unit_lines(path):
    """Non-comment, non-blank lines of a unit file."""
    with open(path) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


@unittest.skipUnless(os.path.exists(INT_UNIT), "integrations files not present")
class IntegrationsPackaging(unittest.TestCase):
    def test_unit_identity_and_limits(self):
        lines = unit_lines(INT_UNIT)
        for want in ("User=vhome-int", "Group=vhome-intsock", "StateDirectory=vhome-integrations",
                     "StateDirectoryMode=0700", "RuntimeDirectory=vhome-integrations", "RuntimeDirectoryMode=0750",
                     "ExecStart=/usr/bin/python3 -m vhome_companion.integrations serve",
                     "Environment=PYTHONPATH=/opt/vhome-vnode/current", "Restart=on-failure",
                     "MemoryMax=64M", "CPUQuota=30%", "TasksMax=32", "Nice=10", "IOWeight=10"):
            self.assertIn(want, lines)
        self.assertFalse([ln for ln in lines if ln.startswith("SupplementaryGroups=")])

    def test_unit_hardening_matches_tv_unit(self):
        tv = unit_lines(TV_UNIT)
        it = unit_lines(INT_UNIT)
        for key in ("NoNewPrivileges", "ProtectSystem", "ProtectHome", "PrivateTmp", "DevicePolicy",
                    "ProtectKernelTunables", "ProtectKernelModules", "ProtectControlGroups", "RestrictNamespaces",
                    "LockPersonality", "CapabilityBoundingSet", "SystemCallArchitectures", "UMask"):
            tv_line = [ln for ln in tv if ln.startswith(key + "=")]
            self.assertTrue(tv_line, key)
            self.assertEqual([ln for ln in it if ln.startswith(key + "=")], tv_line, key)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", it)   # deliberate: narrower than the TV unit

    def test_units_are_independent(self):
        for path in (INT_UNIT, TV_UNIT):
            for ln in unit_lines(path):
                self.assertFalse(re.match(r"(Requires|BindsTo|PartOf|Requisite|Wants|After|Before|Conflicts)=.*vhome-(vnode|integrations)", ln), ln)

    def test_tv_unit_unchanged_vs_head(self):
        r = subprocess.run(["git", "show", "HEAD:vnode/systemd/vhome-vnode.service"], cwd=VNODE,
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("no git history here")
        with open(TV_UNIT) as f:
            self.assertEqual(f.read(), r.stdout)

    def test_tv_state_dir_stays_private(self):
        with open(SCRIPT) as f:
            text = f.read()
        self.assertIn('chmod 0700 "$STATE"', text)
        self.assertNotIn('usermod -aG "$SVC_USER" "$INT_USER"', text)
        self.assertIn('usermod -aG "$INT_GROUP" "$SVC_USER"', text)
        self.assertNotIn("StateDirectory=vhome-vnode", "\n".join(unit_lines(INT_UNIT)))

    def test_scripts_syntax(self):
        for name in ("install-pi.sh", "deploy.sh", os.path.join("bin", "vnode-int")):
            path = os.path.join(VNODE, name)
            shell = "sh" if name.endswith("vnode-int") else "bash"
            self.assertEqual(subprocess.run([shell, "-n", path], capture_output=True).returncode, 0, name)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck(self):
        for name in ("install-pi.sh", "deploy.sh", os.path.join("bin", "vnode-int")):
            r = subprocess.run(["shellcheck", os.path.join(VNODE, name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_wrapper_runs_as_service_user(self):
        with open(os.path.join(VNODE, "bin", "vnode-int")) as f:
            text = f.read()
        self.assertIn("exec sudo -u vhome-int env PYTHONPATH=/opt/vhome-vnode/current /usr/bin/python3 "
                      '-m vhome_companion.integrations cli "$@"', text)

    def run_install(self, with_int, start_rc=0):
        """Run cmd_install with every step stubbed; return (rc, calls)."""
        stubs = ("preflight install_packages ensure_user install_release ensure_state install_files restart_units "
                 "health_check int_preflight ensure_int_users")
        code = (f"for f in {stubs}; do eval \"$f() {{ echo CALL:$f; }}\"; done; "
                "node_id16() { echo n; }; "
                f"start_integrations() {{ echo CALL:start_integrations; return {start_rc}; }}; "
                f"WITH_INT={with_int}; cmd_install")
        r = bash(code)
        return r.returncode, [ln for ln in r.stdout.splitlines() if ln.startswith("CALL:")]

    def test_install_without_flag_never_touches_integrations(self):
        rc, calls = self.run_install(0)
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in calls if "int" in c.lower()], calls)
        self.assertEqual(calls[0], "CALL:preflight")

    def test_install_with_flag_and_start_failure_keeps_tv(self):
        rc, calls = self.run_install(1, start_rc=1)
        self.assertEqual(rc, 3)
        self.assertIn("CALL:int_preflight", calls)
        self.assertLess(calls.index("CALL:int_preflight"), calls.index("CALL:restart_units"))
        self.assertGreater(calls.index("CALL:start_integrations"), calls.index("CALL:health_check"))
        self.assertEqual(calls.count("CALL:restart_units"), 1)

    def test_failed_int_preflight_skips_integrations_but_installs_tv(self):
        code = ("for f in preflight install_packages ensure_user install_release ensure_state install_files "
                "restart_units health_check; do eval \"$f() { echo CALL:$f; }\"; done; node_id16() { echo n; }; "
                "int_preflight() { return 1; }; ensure_int_users() { echo CALL:users; }; "
                "start_integrations() { echo CALL:start_integrations; }; WITH_INT=1; cmd_install")
        r = bash(code)
        self.assertEqual(r.returncode, 3)   # TV installed; asked-for integrations missing -> loud exit 3
        self.assertNotIn("CALL:users", r.stdout)
        self.assertNotIn("CALL:start_integrations", r.stdout)
        self.assertIn("CALL:health_check", r.stdout)

    FINAL = "TV OK, integrations NOT running (see journalctl -u vhome-integrations)"

    def run_cmd(self, cmd, enabled, start_rc=0, with_int=0, extra=""):
        """Run cmd_install/cmd_rollback with steps stubbed and systemctl faked; return (rc, stdout lines)."""
        stubs = ("preflight install_packages ensure_user install_release ensure_state install_files restart_units "
                 "health_check")
        en = "0" if enabled else "1"
        code = (f"for f in {stubs}; do eval \"$f() {{ echo CALL:$f; }}\"; done; node_id16() {{ echo n; }}; "
                f"id() {{ echo 0; }}; switch_to() {{ echo CALL:switch_to; }}; OPT=$(mktemp -d); "
                "mkdir $OPT/p; echo $OPT/p > $OPT/previous; "
                f"systemctl() {{ if [ \"$1\" = is-enabled ]; then return {en}; fi; echo CALL:systemctl:$1; }}; "
                f"start_integrations() {{ echo CALL:start_integrations; return {start_rc}; }}; "
                f"{extra} WITH_INT={with_int}; {cmd}")
        r = bash(code)
        return r.returncode, r.stdout.splitlines()

    def test_start_failure_exits_3_with_final_line_tv_untouched(self):
        rc, out = self.run_cmd("cmd_install", enabled=False, start_rc=1, with_int=1,
                               extra="int_preflight() { return 0; }; ensure_int_users() { return 0; };")
        self.assertEqual(rc, 3)
        self.assertEqual(out[-1], self.FINAL)
        self.assertEqual(out.count("CALL:restart_units"), 1)
        self.assertNotIn("CALL:switch_to", out)

    def test_groupadd_failure_skips_integrations_tv_continues(self):
        rc, out = self.run_cmd("cmd_install", enabled=False, with_int=1,
                               extra="int_preflight() { return 0; }; getent() { return 2; }; "
                                     "groupadd() { return 9; }; useradd() { echo CALL:useradd; }; "
                                     "usermod() { echo CALL:usermod; };")
        self.assertEqual(rc, 3)
        self.assertEqual(out[-1], self.FINAL)
        self.assertNotIn("CALL:start_integrations", out)
        self.assertNotIn("CALL:useradd", out)
        self.assertNotIn("CALL:usermod", out)
        self.assertIn("CALL:health_check", out)

    def test_update_with_integrations_enabled_restarts_them(self):
        rc, out = self.run_cmd("cmd_install", enabled=True)
        self.assertEqual(rc, 0)
        self.assertGreater(out.index("CALL:start_integrations"), out.index("CALL:health_check"))

    def test_update_restart_failure_exits_3(self):
        rc, out = self.run_cmd("cmd_install", enabled=True, start_rc=1)
        self.assertEqual(rc, 3)
        self.assertEqual(out[-1], self.FINAL)

    def test_update_with_integrations_disabled_does_nothing(self):
        rc, out = self.run_cmd("cmd_install", enabled=False)
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in out if "integrations" in c or "systemctl" in c], out)

    def test_rollback_with_integrations_enabled_restarts_them(self):
        rc, out = self.run_cmd("cmd_rollback", enabled=True)
        self.assertEqual(rc, 0)
        self.assertGreater(out.index("CALL:start_integrations"), out.index("CALL:health_check"))

    def test_rollback_restart_failure_exits_3(self):
        rc, out = self.run_cmd("cmd_rollback", enabled=True, start_rc=1)
        self.assertEqual(rc, 3)
        self.assertEqual(out[-1], self.FINAL)

    def test_rollback_with_integrations_disabled_does_nothing(self):
        rc, out = self.run_cmd("cmd_rollback", enabled=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("CALL:start_integrations", out)

    def test_flag_parsing_defaults_off(self):
        self.assertEqual(bash('echo "$WITH_INT"').stdout.strip(), "0")


@unittest.skipUnless(os.path.exists(DELIVER_UNIT), "delivery worker unit not present")
class DeliveryWorkerPackaging(unittest.TestCase):
    def test_unit_identity_limits_and_hardening(self):
        lines = unit_lines(DELIVER_UNIT)
        self.assertNotIn("User=vhome-int", lines)                      # its own user: cannot read the queue db
        for want in ("User=vhome-deliver", "Group=vhome-intsock", "EnvironmentFile=/etc/vhome-int/deliver.env",
                     "ExecStart=/usr/bin/python3 -m vhome_companion.integrations.worker.main --live --from-env",
                     "StateDirectory=vhome-int-deliver", "StateDirectoryMode=0700",
                     "Environment=PYTHONPATH=/opt/vhome-vnode/current", "Restart=on-failure",
                     "MemoryMax=48M", "CPUQuota=40%", "Nice=15", "PrivateDevices=yes", "ProtectProc=invisible",
                     "ProcSubset=pid", "RestrictSUIDSGID=yes", "SystemCallFilter=@system-service", "Wants=network-online.target",
                     "After=network-online.target time-sync.target",
                     "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"):
            self.assertIn(want, lines)
        self.assertFalse([ln for ln in lines if ln.startswith("MemoryDenyWriteExecute")])    # untestable on the Pi: left out
        self.assertFalse([ln for ln in lines if ln.startswith("SupplementaryGroups")])
        it = unit_lines(INT_UNIT)
        for key in ("NoNewPrivileges", "ProtectSystem", "ProtectHome", "PrivateTmp", "DevicePolicy", "CapabilityBoundingSet",
                    "ProtectKernelTunables", "ProtectKernelModules", "ProtectControlGroups", "RestrictNamespaces",
                    "LockPersonality", "SystemCallArchitectures", "UMask"):
            self.assertEqual([ln for ln in lines if ln.startswith(key + "=")], [ln for ln in it if ln.startswith(key + "=")], key)

    def test_unit_is_independent_and_holds_no_secrets(self):
        for ln in unit_lines(DELIVER_UNIT):
            self.assertFalse(re.match(r"(Requires|BindsTo|PartOf|Requisite|Conflicts|After|Before)=.*vhome-", ln), ln)
            self.assertNotRegex(ln, r"(?i)token=|secret=")

    def run_env(self, src_text, existing="", minted="MINTEDTOKEN123", token_ok=True):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        src = os.path.join(d, "src.env")
        with open(src, "w") as f:
            f.write(src_text)
        dest_dir = os.path.join(d, "etc")
        os.mkdir(dest_dir)
        dest = os.path.join(dest_dir, "deliver.env")
        self.modes = os.path.join(d, "modes.log")
        if existing:
            with open(dest, "w") as f:
                f.write(existing)
        code = ('install() { local d=0 m="" o="" g="" a=(); while [ $# -gt 0 ]; do case "$1" in -d) d=1;; -m) m="$2"; shift;; '
                '-o) o="$2"; shift;; -g) g="$2"; shift;; *) a+=("$1");; esac; shift; done; '
                f'echo "d=$d owner=$o:$g mode=$m" >> "{self.modes}"; '
                'if [ $d = 1 ]; then mkdir -p "${a[@]}"; else cp "${a[0]}" "${a[1]}"; fi; }; '
                f'DELIVER_DIR="{dest_dir}"; DELIVER_ENV="{dest}"; WORKER_ENV_SRC="{src}"; '
                f'check_worker_token() {{ return {0 if token_ok else 1}; }}; '
                f'INT_WRAPPER=/bin/true; mint_worker_token() {{ echo {minted}; }}; write_deliver_env')
        r = bash(code)
        out = open(dest).read() if os.path.exists(dest) else None
        return r, out, os.path.exists(src)

    def test_env_file_built_from_source_without_echoing_tokens(self):
        r, out, src_left = self.run_env("BRAIN_URL=https://cockpit.vineethnair.com\nBRAIN_VNODE_TOKEN=brainsecret1\n"
                                        "CF_ACCESS_CLIENT_ID=cid\nCF_ACCESS_CLIENT_SECRET=csec\nJUNK=drop\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(out.splitlines()), sorted([
            "BRAIN_URL=https://cockpit.vineethnair.com", "BRAIN_ALLOW_HOST=cockpit.vineethnair.com",
            "BRAIN_VNODE_TOKEN=brainsecret1", "CF_ACCESS_CLIENT_ID=cid", "CF_ACCESS_CLIENT_SECRET=csec",
            "VNODE_SOCKET=/run/vhome-integrations/int.sock", "VNODE_WORKER_TOKEN=MINTEDTOKEN123", "WORKER_NAME=pi-deliver",
            "WORKER_POLL_S=60", "WORKER_MAX_PER_RUN=5", "WAIT_CLOCK_SYNC=1"]))
        for secret in ("brainsecret1", "csec", "MINTEDTOKEN123"):
            self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertFalse(src_left)                                   # source file consumed and deleted
        self.assertEqual(open(self.modes).read().splitlines(),       # root-only: systemd reads it as root, the service user cannot
                         ["d=1 owner=root:root mode=0700", "d=0 owner=root:root mode=0600"])

    def test_cf_pair_needs_both_and_existing_worker_token_is_kept(self):
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com:8443/x\nBRAIN_VNODE_TOKEN=t\nCF_ACCESS_CLIENT_ID=only\n",
                                 existing="VNODE_WORKER_TOKEN=oldworker\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("CF_ACCESS", out)
        self.assertIn("VNODE_WORKER_TOKEN=oldworker", out)
        self.assertIn("BRAIN_ALLOW_HOST=b.example.com", out)

    def test_missing_token_or_failed_mint_is_refused(self):
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIsNone(out)
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com\nBRAIN_VNODE_TOKEN=t\n", minted="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIsNone(out)

    def test_parse_minted_token(self):
        text = "worker token id: abc (project brain)\ntoken (shown once, store it now): s3cr3t-Tok_en\n"
        self.assertEqual(bash("parse_minted_token", text).stdout.strip(), "s3cr3t-Tok_en")

    def test_flags_parse_and_imply_integrations(self):
        r = bash('cmd_install() { echo "$WITH_WORKER $WITH_INT $WORKER_ENV_SRC"; }; main install --with-worker --worker-env-file /nonexistent/x')
        self.assertEqual(r.stdout.strip(), "1 1 /nonexistent/x")
        self.assertEqual(bash('echo "$WITH_WORKER"').stdout.strip(), "0")

    def run_worker_install(self, int_rc=0, worker_rc=0):
        stubs = ("preflight install_packages ensure_user install_release ensure_state install_files restart_units "
                 "health_check int_preflight ensure_int_users")
        code = (f"for f in {stubs}; do eval \"$f() {{ echo CALL:$f; }}\"; done; node_id16() {{ echo n; }}; "
                f"start_integrations() {{ echo CALL:start_integrations; return {int_rc}; }}; "
                f"setup_worker() {{ echo CALL:setup_worker; return {worker_rc}; }}; WITH_WORKER=1; WITH_INT=1; cmd_install")
        r = bash(code)
        return r.returncode, [ln for ln in r.stdout.splitlines() if ln.startswith("CALL:")], r.stdout.splitlines()

    def test_worker_set_up_after_integrations_are_up(self):
        rc, calls, _ = self.run_worker_install()
        self.assertEqual(rc, 0)
        self.assertGreater(calls.index("CALL:setup_worker"), calls.index("CALL:start_integrations"))
        self.assertEqual(calls.count("CALL:restart_units"), 1)

    def test_worker_failure_exits_3_tv_untouched_and_skipped_when_integrations_fail(self):
        rc, calls, out = self.run_worker_install(worker_rc=1)
        self.assertEqual(rc, 3)
        self.assertEqual(out[-1], "TV OK, integrations OK, delivery worker NOT running (see journalctl -u vhome-int-deliver)")
        rc, calls, out = self.run_worker_install(int_rc=1)
        self.assertEqual(rc, 3)
        self.assertNotIn("CALL:setup_worker", calls)

    def test_values_are_validated(self):
        base = "BRAIN_URL=https://b.example.com\nBRAIN_VNODE_TOKEN=t\n"
        for bad in ("BRAIN_VNODE_TOKEN=has space\n", "BRAIN_VNODE_TOKEN=a\tb\n", "BRAIN_VNODE_TOKEN=a\\b\n",
                    "BRAIN_VNODE_TOKEN=a$(x)`b`\n", "CF_ACCESS_CLIENT_ID=ok\x01x\nCF_ACCESS_CLIENT_SECRET=s\n"):
            src = base.replace("BRAIN_VNODE_TOKEN=t\n", "") + bad if bad.startswith("BRAIN") else base + bad
            r, out, _ = self.run_env(src)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIsNone(out, bad)
        for url in ("http://b.example.com", "https://user:pw@b.example.com", "https://b.example.com:x", "ftp://b",
                    "https://", "https://b.example.com/a b", "https://b_x.example.com"):
            r, out, _ = self.run_env("BRAIN_URL=%s\nBRAIN_VNODE_TOKEN=t\n" % url)
            self.assertNotEqual(r.returncode, 0, url)
            self.assertIsNone(out, url)
        for url in ("https://b.example.com", "https://b.example.com:8443/x/y", "https://1.2.3.4"):
            r, out, _ = self.run_env("BRAIN_URL=%s\nBRAIN_VNODE_TOKEN=t\n" % url)
            self.assertEqual(r.returncode, 0, (url, r.stderr))

    def test_env_get_strips_only_balanced_quotes_and_cr(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        f = os.path.join(d, "e")
        with open(f, "w", newline="") as fh:
            fh.write('A="quoted"\r\nB=\'single\'\nC="unbalanced\nD=plain\r\nE=a"b"c\nF=\'"mixed"\'\n')
        got = {k: bash(f'env_get "{f}" {k}').stdout for k in "ABCDEF"}
        self.assertEqual(got, {"A": "quoted", "B": "single", "C": '"unbalanced', "D": "plain", "E": 'a"b"c', "F": '"mixed"'})

    def test_supplied_worker_token_must_be_accepted(self):
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com\nBRAIN_VNODE_TOKEN=t\nVNODE_WORKER_TOKEN=revoked\n",
                                 token_ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIsNone(out)
        self.assertNotIn("revoked", r.stdout + r.stderr)
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com\nBRAIN_VNODE_TOKEN=t\nVNODE_WORKER_TOKEN=good\n")
        self.assertIn("VNODE_WORKER_TOKEN=good", out)

    def test_revoked_existing_worker_token_is_replaced(self):
        r, out, _ = self.run_env("BRAIN_URL=https://b.example.com\nBRAIN_VNODE_TOKEN=t\n",
                                 existing="VNODE_WORKER_TOKEN=oldrevoked\n", token_ok=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VNODE_WORKER_TOKEN=MINTEDTOKEN123", out)

    def test_mint_failure_shows_redacted_reason(self):
        code = ('INT_WRAPPER="$(mktemp)"; cat > "$INT_WRAPPER" <<"EOF"\n#!/bin/sh\n'
                'echo "cannot reach admin socket /run/x: token (shown once, store it now): LEAKME authorization: Bearer LEAKME2" >&2\n'
                'exit 1\nEOF\nchmod +x "$INT_WRAPPER"; if mint_worker_token; then echo rc=0; else echo rc=1; fi')
        r = bash(code)
        self.assertIn("rc=1", r.stdout)
        self.assertIn("cannot reach admin socket", r.stderr)
        self.assertNotIn("LEAKME", r.stdout + r.stderr)

    def test_source_file_removed_on_every_exit_path(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for body in ("exit 1", "die boom", "exit 3", "return 0"):
            src = os.path.join(d, "s.env")
            with open(src, "w") as f:
                f.write("BRAIN_VNODE_TOKEN=secret\n")
            bash(f'cmd_install() {{ {body}; }}; main install --with-worker --worker-env-file "{src}"')
            self.assertFalse(os.path.exists(src), body)

    def run_setup(self, active=True, started=True, user_ok=True):
        code = ("ensure_deliver_user() { return %d; }; write_deliver_env() { echo CALL:env; }; sleep() { :; }; "
                "systemctl() { case \"$1\" in is-active) return %d;; *) echo CALL:systemctl:$1;; esac; }; "
                "journalctl() { %s; }; if setup_worker; then echo rc=0; else echo rc=1; fi"
                % (0 if user_ok else 1, 0 if active else 1, 'echo "worker 0.2.0 started mode=LIVE via=unix socket"' if started else "true"))
        r = bash(code)
        return r.stdout + r.stderr

    def test_startup_waits_for_started_line(self):
        out = self.run_setup()
        self.assertIn("rc=0", out)
        self.assertIn("delivery worker running", out)
        self.assertLess(out.index("CALL:env"), out.index("CALL:systemctl:restart"))
        out = self.run_setup(started=False)                          # active but never says started: fail after the wait
        self.assertIn("rc=1", out)
        self.assertIn("did not report 'started' within 45 s and was disabled", out)
        out = self.run_setup(active=False)
        self.assertIn("rc=1", out)
        self.assertIn("rc=1", self.run_setup(user_ok=False))
        self.assertNotIn("CALL:env", self.run_setup(user_ok=False))

    def test_own_service_user_in_socket_group_only(self):
        with open(SCRIPT) as f:
            text = f.read()
        self.assertIn('useradd --system --gid "$INT_GROUP" --home-dir "$DELIVER_STATE"', text)
        self.assertNotIn('usermod -aG "$INT_GROUP" "$DELIVER_USER"', text)
        self.assertNotIn('usermod -aG "$DELIVER_USER"', text)
        self.assertIn('userdel "$DELIVER_USER"', text)
        self.assertEqual(bash('echo "$DELIVER_USER"').stdout.strip(), "vhome-deliver")

    def test_redact_output(self):
        out = bash("redact_output", "ok line\ntoken (shown once, store it now): SECRETX\nAuthorization: Bearer SECRETY\n").stdout
        self.assertIn("ok line", out)
        self.assertNotIn("SECRET", out)

    def test_deploy_passes_worker_secrets_by_file_not_argv(self):
        with open(os.path.join(VNODE, "deploy.sh")) as f:
            text = f.read()
        self.assertIn("--worker-env-file", text)
        self.assertIn("umask 077", text)
        self.assertNotRegex(text, r"--worker-env-file[^\n]*BRAIN_VNODE_TOKEN")
        self.assertIn("vhome-int-deliver", text)                    # int-status / int-inspect show it


@unittest.skipUnless(os.path.exists(os.path.join(VNODE, "deploy.sh")), "deploy.sh not present")
class DeployScriptWithStubs(unittest.TestCase):
    """Run the real deploy.sh with stub ssh/scp/launchctl on PATH: secrets stay out of argv and files are cleaned up."""

    SECRET = "brain-tok-SUPERSECRET-123"
    CFSEC = "cf-SUPERSECRET-456"

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.bin = os.path.join(self.d, "bin")
        self.tmp = os.path.join(self.d, "tmp")
        self.cap = os.path.join(self.d, "captured")
        for x in (self.bin, self.tmp, self.cap, os.path.join(self.d, "vnode")):
            os.mkdir(x)
        shutil.copy(os.path.join(VNODE, "deploy.sh"), os.path.join(self.d, "vnode", "deploy.sh"))
        self.write(os.path.join(self.d, "vnode", "build-bundle.sh"), "#!/bin/sh\necho %s/bundle.tar.gz\n" % self.d)
        open(os.path.join(self.d, "bundle.tar.gz"), "w").close()
        self.log = os.path.join(self.d, "calls.log")
        self.write(os.path.join(self.bin, "ssh"), """#!/bin/sh
echo "ssh $*" >> "%s"
case "$*" in *mktemp*) echo /home/vnode/.vnode-deliver-env.ABC123; exit 0;; esac
case "$*" in *install-pi.sh*) exit ${STUB_INSTALL_RC:-0};; esac
exit 0
""" % self.log)
        self.write(os.path.join(self.bin, "scp"), """#!/bin/sh
echo "scp $*" >> "%s"
for a in "$@"; do last_prev=$last; last=$a; done
case "$last_prev" in *.tar.gz|-*) ;; *) [ -f "$last_prev" ] && cp "$last_prev" "%s/$(basename "$last")";; esac
exit 0
""" % (self.log, self.cap))
        self.write(os.path.join(self.bin, "launchctl"), "#!/bin/sh\nexit 1\n")

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def run_deploy(self, rc=0, token=True, *args):
        env = dict(os.environ, PATH=self.bin + ":" + os.environ["PATH"], TMPDIR=self.tmp, STUB_INSTALL_RC=str(rc))
        for k in ("BRAIN_VNODE_TOKEN", "CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET", "BRAIN_URL"):
            env.pop(k, None)
        if token:
            env.update(BRAIN_VNODE_TOKEN=self.SECRET, CF_ACCESS_CLIENT_ID="cfid.access", CF_ACCESS_CLIENT_SECRET=self.CFSEC)
        return subprocess.run(["bash", os.path.join(self.d, "vnode", "deploy.sh"), "--host", "pi.test", "update", "--with-worker", *args],
                              env=env, capture_output=True, text=True, cwd=self.d)

    def calls(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def test_success_keeps_secrets_out_of_argv_and_cleans_up(self):
        r = self.run_deploy()
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        for secret in (self.SECRET, self.CFSEC):
            self.assertFalse([c for c in calls if secret in c], secret)       # never in any argv
            self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertTrue([c for c in calls if "mktemp" in c and "umask 077" in c])
        sent = os.path.join(self.cap, ".vnode-deliver-env.ABC123")
        body = open(sent).read()                                              # but it did travel, in the private file
        self.assertIn("BRAIN_VNODE_TOKEN=" + self.SECRET, body)
        self.assertIn("BRAIN_URL=https://cockpit.vineethnair.com", body)
        self.assertTrue([c for c in calls if "install-pi.sh" in c and "--worker-env-file /home/vnode/.vnode-deliver-env.ABC123" in c])
        self.assertEqual(calls[-1], "ssh vnode@pi.test rm -f /home/vnode/.vnode-deliver-env.ABC123")
        self.assertEqual(os.listdir(self.tmp), [])                            # no local temp file left
        self.assertIn("launchctl bootout gui/$UID/com.designinnsaeit.vhome-int-worker", r.stdout)

    def test_failed_install_still_removes_both_copies_and_skips_the_mac_step(self):
        r = self.run_deploy(rc=3)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls()[-1], "ssh vnode@pi.test rm -f /home/vnode/.vnode-deliver-env.ABC123")
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertNotIn("launchctl bootout", r.stdout)

    def test_scp_failure_still_removes_remote_file(self):
        self.write(os.path.join(self.bin, "scp"), "#!/bin/sh\necho \"scp $*\" >> \"%s\"\ncase \"$*\" in *.vnode-deliver-env*) exit 1;; esac\nexit 0\n" % self.log)
        r = self.run_deploy()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.calls()[-1], "ssh vnode@pi.test rm -f /home/vnode/.vnode-deliver-env.ABC123")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_without_token_no_file_is_sent(self):
        r = self.run_deploy(token=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([c for c in self.calls() if "mktemp" in c or "worker-env-file" in c])
        self.assertIn("keeping the delivery settings already on the Pi", r.stderr)


if __name__ == "__main__":
    unittest.main()
