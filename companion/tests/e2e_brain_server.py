"""Launcher for the real Brain API in a TEMP root (run by the Brain venv python, never imported by tests).

usage: e2e_brain_server.py <brain_repo> <temp_root> <port>
Binds 127.0.0.1 only. The root holds config.json, events.db and the temp vault/inbox; nothing else is touched.
"""
import os
import sys
from pathlib import Path

repo, root, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.environ["BRAIN_COCKPIT_ROOT"] = root
sys.path.insert(0, repo)

import uvicorn  # noqa: E402

from api.main import create_app  # noqa: E402

uvicorn.run(create_app(root=Path(root)), host="127.0.0.1", port=port, log_level="warning")
