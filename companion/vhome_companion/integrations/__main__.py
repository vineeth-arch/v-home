"""python3 -m vhome_companion.integrations serve | cli <command>. Exit codes: 0 ok, 1 error, 2 usage."""
import argparse
import asyncio
import http.client
import json
import logging
import os
import socket
import sys
import urllib.parse

from . import contracts


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def _call(path, method, url, body=None):
    conn = _UnixConn(path, 120)     # vacuum on a microSD can be slow
    try:
        data = None if body is None else json.dumps(body).encode()
        conn.request(method, url, body=data, headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw) if raw else {}
        except ValueError:
            return r.status, {"error": "bad_response", "detail": "service sent a non-JSON reply"}
    finally:
        conn.close()


def _ago(s):
    return "never" if s is None else "%ds ago" % s


def _fmt_stats(d):
    j = d["jobs"]
    return "\n".join([
        "jobs: %d rows, %d live" % (d["rows"], d["live"]),
        "  " + ", ".join("%s %d" % (k, v) for k, v in j.items()),
        "payloads: %d bytes, db: %d bytes, disk free: %d MB" % (d["payload_bytes"], d["db_bytes"],
                                                               d["disk_free_bytes"] // (1024 * 1024)),
        "uptime: %ds, clock synced: %s" % (d["uptime_s"], "yes" if d["clock_synced"] else "no"),
        "worker last seen: %s, snapshot age: %s, worker tokens active: %d" % (
            "never" if d["worker_last_seen_age_s"] is None else "%ds ago" % d["worker_last_seen_age_s"],
            "none" if d["snapshot_age_s"] is None else "%ds" % d["snapshot_age_s"], d["worker_tokens_active"])]
        + ["housekeeping %s: last run %s, last error %s" % (
            n, _ago(h["last_run_age_s"]), "none" if h["last_error_age_s"] is None
            else "%s, %s" % (_ago(h["last_error_age_s"]), h["last_error"]))
           for n, h in d.get("housekeeping", {}).items()])


def _fmt_job_line(j):
    return "%s  %-10s %-5s attempts=%d bytes=%s created=%s" % (
        j["id"], j["status"], j["kind"], j["attempts"], j["payload_bytes"], j["created_at"])


def _parser():
    p = argparse.ArgumentParser(prog="vnode-int", description="VNode integrations service")
    top = p.add_subparsers(dest="cmd", required=True)
    top.add_parser("serve", help="run the service")
    cli = top.add_parser("cli", help="admin commands")
    sub = cli.add_subparsers(dest="sub", required=True)
    sub.add_parser("stats")
    j = sub.add_parser("jobs")
    j.add_argument("--status")
    sub.add_parser("show").add_argument("id")
    r = sub.add_parser("recover")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--requeue", metavar="ID")
    g.add_argument("--fail", metavar="ID")
    r.add_argument("--yes", action="store_true")
    pg = sub.add_parser("purge")
    pg.add_argument("--terminal", action="store_true", required=True)
    pg.add_argument("--yes", action="store_true")
    wt = sub.add_parser("worker-token").add_subparsers(dest="wsub", required=True)
    wt.add_parser("create")
    wt.add_parser("list")
    wt.add_parser("revoke").add_argument("id")
    sub.add_parser("vacuum", help="compact the database; pauses the service briefly")
    return p


def _cli(a, out, err):
    sock = os.environ.get("VHOME_INT_ADMIN") or contracts.ADMIN_SOCKET_PATH
    if a.sub in ("recover", "purge") and not a.yes:
        print("refusing: %s changes data; rerun with --yes" % a.sub, file=err)
        return 2
    s = a.sub
    if s == "stats":
        req = ("GET", "/stats", None)
    elif s == "jobs":
        req = ("GET", "/jobs" + ("?status=" + urllib.parse.quote(a.status, safe="") if a.status else ""), None)
    elif s == "show":
        req = ("GET", "/jobs/" + urllib.parse.quote(a.id, safe=""), None)
    elif s == "recover":
        req = ("POST", "/recover", {"id": a.requeue or a.fail, "action": "requeue" if a.requeue else "fail",
                                    "yes": True})
    elif s == "purge":
        req = ("POST", "/purge", {"terminal": True, "yes": True})
    elif s == "vacuum":
        req = ("POST", "/vacuum", {})
    elif a.wsub == "create":
        req = ("POST", "/worker-token", {})
    elif a.wsub == "list":
        req = ("GET", "/worker-tokens", None)
    else:
        req = ("POST", "/worker-token/%s/revoke" % urllib.parse.quote(a.id, safe=""), {})
    try:
        status, d = _call(sock, *req)
    except OSError as e:
        print("cannot reach admin socket %s: %s" % (sock, e.strerror or type(e).__name__), file=err)
        return 1
    if status != 200:
        print("error: %s (%s)" % (d.get("detail", ""), d.get("error", status)), file=err)
        return 1
    if s == "stats":
        print(_fmt_stats(d), file=out)
    elif s == "jobs":
        for j in d["jobs"]:
            print(_fmt_job_line(j), file=out)
        print("%d job(s)" % len(d["jobs"]), file=out)
    elif s == "show" or s == "recover":
        for k, v in d["job"].items():
            print("%-16s %s" % (k, v), file=out)
    elif s == "purge":
        print("purged %d row(s)/payload(s)" % d["purged"], file=out)
    elif s == "vacuum":
        print("db %d -> %d bytes" % (d["before_bytes"], d["after_bytes"]), file=out)
    elif a.wsub == "create":
        print("worker token id: %s (project %s)" % (d["id"], d["project"]), file=out)
        print("token (shown once, store it now): %s" % d["token"], file=out)
    elif a.wsub == "list":
        for t in d["tokens"]:
            print("%s  %-8s created=%s %s" % (t["id"], t["project"], t["created_at"],
                                               "revoked=" + t["revoked_at"] if t["revoked_at"] else "active"), file=out)
    else:
        print("revoked %s" % d["revoked"], file=out)
    return 0


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    a = _parser().parse_args(argv)      # usage errors exit 2
    if a.cmd == "cli":
        return _cli(a, out, err)
    from .server import serve
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(serve())


if __name__ == "__main__":
    sys.exit(main())
