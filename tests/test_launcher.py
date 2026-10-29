"""Exercise the user's startup path, not only TestClient or a temporary test server."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_launcher_persists_reuses_and_stops(tmp_path):
    port = free_port()
    env = {
        **os.environ,
        "RESOLVEDESK_DB": str(tmp_path / "app.db"),
        "RESOLVEDESK_LAUNCHER_DIR": str(tmp_path / "launcher"),
        "OPENAI_API_KEY": "",
        "ACCOUNT_API_URL": "",
    }

    def command(action):
        return subprocess.run(
            [sys.executable, str(ROOT / "launcher.py"), action, "--port", str(port)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    try:
        first = command("start")
        assert first.returncode == 0, first.stdout + first.stderr
        state_file = tmp_path / "launcher" / f"service-{port}.json"
        state = json.loads(state_file.read_text())
        # The startup command has exited, but its child remains available.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as response:
            assert json.load(response)["instance"] == state["instance"]
        assert command("start").returncode == 0
        assert json.loads(state_file.read_text())["pid"] == state["pid"]
        assert command("status").returncode == 0
        assert (
            "Reviewer token" in (tmp_path / "launcher" / "LOCAL_ACCESS.txt").read_text()
        )
    finally:
        stopped = command("stop")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert command("status").returncode == 1


def test_launcher_does_not_replace_another_service(tmp_path):
    # A foreign listener must not be killed or silently adopted as ResolveDesk.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        env = {**os.environ, "RESOLVEDESK_LAUNCHER_DIR": str(tmp_path / "launcher")}
        result = subprocess.run(
            [sys.executable, str(ROOT / "launcher.py"), "start", "--port", str(port)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1 and "occupied" in result.stdout
