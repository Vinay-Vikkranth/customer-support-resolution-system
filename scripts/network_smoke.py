"""Exercise two real HTTP processes with separate databases on loopback."""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(port, path, body=None, token="network-reviewer"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


with tempfile.TemporaryDirectory(prefix="resolvedesk-network-") as directory:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / ".deps"),
        "OPENAI_API_KEY": "",
        "ACCOUNT_API_TOKEN": "network-service-token",
        "ACCOUNT_DB": str(Path(directory) / "account.db"),
        "RESOLVEDESK_DB": str(Path(directory) / "support.db"),
        "ACCOUNT_API_URL": "http://127.0.0.1:18179",
        "RESOLVEDESK_TOKEN": "network-operator",
        "RESOLVEDESK_REVIEW_TOKEN": "network-reviewer",
    }
    processes = []
    try:
        for module, port in [
            ("app.account_service:app", 18179),
            ("app.main:app", 18178),
        ]:
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        module,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            )
            for attempt in range(60):
                try:
                    request(port, "/health")
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError(f"Service {port} did not start")
        run = request(18178, "/api/tickets/1/investigate", {})
        assert run["action"] == "restore_reporting"
        before = request(
            18179,
            "/v1/snapshot?account_id=acme&member_id=alex",
            token="network-service-token",
        )
        assert before["member"]["reporting"] == 0
        result = request(
            18178, f"/api/investigations/{run['id']}/decision", {"decision": "approve"}
        )
        assert result["verified"]
        after = request(
            18179,
            "/v1/snapshot?account_id=acme&member_id=alex",
            token="network-service-token",
        )
        assert after["member"]["reporting"] == 1
        repeated = request(
            18178, f"/api/investigations/{run['id']}/decision", {"decision": "approve"}
        )
        assert repeated["replayed"]
        print(
            "PASS: real HTTP account lookup, remote conditional execution, verification and idempotent replay across two independent databases."
        )
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)
