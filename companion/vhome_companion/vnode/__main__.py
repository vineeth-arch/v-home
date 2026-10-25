"""python3 -m vhome_companion.vnode <serve|pair-phone|phones|status|diag|pause|resume|leds>"""
import argparse
import asyncio
import json
import logging
import os
import sys

import aiohttp

from .. import cli
from . import contracts

EX_CONFIG = 78
NOT_RUNNING = "vhome-vnode is not running: sudo systemctl status vhome-vnode"


def runtime_dir():
    return os.environ.get("RUNTIME_DIRECTORY", "/run/vhome-vnode").split(":")[0]


def fingerprint(node_id):
    s = node_id[:24]
    return " ".join(s[i:i + 4] for i in range(0, 24, 4))


async def admin_call(method, path, body=None, headers=None):
    """Talk to the running service over its admin socket. Returns (status, json)."""
    conn = aiohttp.UnixConnector(path=os.path.join(runtime_dir(), contracts.ADMIN_SOCKET))
    async with aiohttp.ClientSession(connector=conn, headers={"X-VNode-Api": "1"}) as s:
        async with s.request(method, "http://vnode" + path, json=body, headers=headers,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
            return r.status, await r.json()


async def command(path, body=None):
    """GET a nonce, then POST body+nonce."""
    _, n = await admin_call("GET", "/v1/nonce")
    return await admin_call("POST", path, {**(body or {}), "nonce": n["nonce"]})


def serve(args):
    state = cli.state_dir()
    cert, key = state / "cert.pem", state / "key.pem"
    if not (cert.exists() and key.exists()):
        print("missing %s or %s. Create them with the installer, or:\n"
              "  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 "
              "-subj /CN=vnode -keyout %s -out %s" % (cert, key, key, cert), file=sys.stderr)
        return EX_CONFIG
    from .api import serve as run
    return asyncio.run(run(state, cert, key, args.port, runtime_dir()))


async def run_client(args):
    if args.cmd == "pair-phone":
        st, d = await admin_call("POST", "/admin/pairing-code")
        c = d["code"]
        print("Node fingerprint: %s\nPairing code:     %s-%s\nExpires in:       %d minutes\n"
              "In the V/HOME app, check the fingerprint matches, then enter the code."
              % (fingerprint(d["node_id"]), c[:4], c[4:], d["expires_in_s"] // 60))
        return 0
    if args.cmd == "phones":
        if args.action == "revoke":
            st, d = await admin_call("DELETE", "/admin/phones/" + args.id)
            print("revoked" if st == 200 else "no such phone: " + args.id)
            return 0 if st == 200 else 1
        st, d = await admin_call("GET", "/admin/phones")
        for p in d["phones"]:
            print("%s  %-24s %s" % (p["id"], p["name"], p["created"]))
        if not d["phones"]:
            print("no paired phones")
        return 0
    if args.cmd == "status":
        _, d = await admin_call("GET", "/v1/status")
        tv, w = d["tv"], d["watcher"]
        print("headline: %s\nnode:     %s, up %ds\ntv:       %s (%s), foreground %s\nwatcher:  %s, %s redirects, %s failed"
              % (d["headline"], d["node"]["version"], d["node"]["uptime_s"], tv["state"], tv.get("host"),
                 tv.get("foreground"), w["state"], w.get("redirects"), w.get("failed")))
        return 0
    if args.cmd == "diag":
        _, d = await admin_call("GET", "/v1/diagnostics")
        print(json.dumps(d, indent=2))
        return 0
    if args.cmd == "pause":
        st, d = await command("/v1/pause", {"minutes": args.minutes} if args.minutes else {})
    elif args.cmd == "resume":
        st, d = await command("/v1/resume")
    else:  # leds
        brightness = args.brightness
        if brightness is None:
            _, dev = await admin_call("GET", "/v1/device")
            brightness = (dev.get("leds") or {}).get("brightness") or 2
        st, d = await command("/v1/device/leds", {"enabled": args.state == "on", "brightness": brightness})
    print(d.get("outcome") or "%s: %s" % (d.get("error"), d.get("detail")), d.get("detail", "") if st == 200 else "")
    return 0 if st == 200 else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="vnode")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=contracts.PORT)
    sub.add_parser("pair-phone")
    ph = sub.add_parser("phones")
    ph.add_argument("action", choices=["list", "revoke"], nargs="?", default="list")
    ph.add_argument("id", nargs="?")
    sub.add_parser("status")
    sub.add_parser("diag")
    pa = sub.add_parser("pause")
    pa.add_argument("--minutes", type=int)
    sub.add_parser("resume")
    le = sub.add_parser("leds")
    le.add_argument("state", choices=["on", "off"])
    le.add_argument("--brightness", type=int, choices=[1, 2, 3, 4])
    args = p.parse_args(argv)
    if args.cmd == "phones" and args.action == "revoke" and not args.id:
        p.error("phones revoke needs an ID")
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    if args.cmd == "serve":
        return serve(args)
    try:
        return asyncio.run(run_client(args))
    except (OSError, aiohttp.ClientConnectionError):  # missing socket, permission, refused
        print(NOT_RUNNING, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
