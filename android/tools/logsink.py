"""Receive V/HOME Watcher phone logs over the LAN and append them to a file.

The phone opens a TCP connection, writes UTF-8 text, and closes. Each connection is appended
as-is, prefixed with the sender's address. Debug aid only: LAN, no auth, text the phone already
redacts (client keys).

    python3 android/tools/logsink.py [--port 8765] [--out ~/Library/Logs/vhome-watch-phone.log]
"""
import argparse
import socketserver
from datetime import datetime
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024  # per connection; a full dump with logcat stays well under this


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default=str(Path.home() / "Library/Logs/vhome-watch-phone.log"))
    args = ap.parse_args()
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            data = self.rfile.read(MAX_BYTES).decode("utf-8", "replace")
            if not data.strip():
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            with out.open("a", encoding="utf-8") as f:
                for line in data.rstrip("\n").split("\n"):
                    f.write(f"[{stamp} {self.client_address[0]}] {line}\n")

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", args.port), Handler) as srv:
        print(f"listening on :{args.port}, writing {out}", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
