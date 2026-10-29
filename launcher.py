"""Start a persistent loopback server, check ownership, and expose local access instructions.

No browser is controlled. --open is only used by the user-invoked Windows shortcut.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
if (ROOT / ".deps").exists():
    sys.path.insert(0, str(ROOT / ".deps"))
from app.config import load_env


def health(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=1
        ) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def port_busy(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description="ResolveDesk local service manager")
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the browser after a successful user-invoked start",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port between 1024 and 65535")
    load_env()
    state_dir = Path(
        os.environ.get("RESOLVEDESK_LAUNCHER_DIR", ROOT / "data" / "launcher")
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"service-{args.port}.json"
    access_file = state_dir / "LOCAL_ACCESS.txt"
    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else {}
    )
    current = health(args.port)
    own = bool(
        current
        and current.get("service") == "resolvedesk"
        and current.get("instance") == state.get("instance")
        and state.get("instance")
    )
    url = f"http://127.0.0.1:{args.port}"
    if args.command == "status":
        print(
            json.dumps(
                {"running": own, "url": url, "access_file": str(access_file)}, indent=2
            )
        )
        return 0 if own else 1
    if args.command == "stop":
        if not own:
            print(
                "No verified ResolveDesk launcher process is running here. Nothing was stopped."
            )
            return 1
        os.kill(state["pid"], signal.SIGTERM)
        for _ in range(40):
            if not port_busy(args.port):
                state_file.unlink(missing_ok=True)
                print(
                    "ResolveDesk stopped. Start it again before opening the local URL."
                )
                return 0
            time.sleep(0.1)
        print("The server has not stopped yet. Inspect the local service log.")
        return 1
    if not own and port_busy(args.port):
        print(
            f"Port {args.port} is occupied by another process. Nothing was changed. Choose --port 8002 or close that service yourself."
        )
        return 1
    if not own:
        if not importlib.util.find_spec("uvicorn"):
            print(
                "Dependencies are missing. Install requirements.txt using this Python environment, then retry."
            )
            return 1
        credentials_file = state_dir / "credentials.json"
        credentials = (
            json.loads(credentials_file.read_text(encoding="utf-8"))
            if credentials_file.exists()
            else {
                "operator": secrets.token_urlsafe(32),
                "reviewer": secrets.token_urlsafe(32),
            }
        )
        atomic_json(credentials_file, credentials)
        instance = secrets.token_hex(24)
        env = {
            **os.environ,
            "RESOLVEDESK_INSTANCE": instance,
            "RESOLVEDESK_TOKEN": os.environ.get("RESOLVEDESK_TOKEN")
            or credentials["operator"],
            "RESOLVEDESK_REVIEW_TOKEN": os.environ.get("RESOLVEDESK_REVIEW_TOKEN")
            or credentials["reviewer"],
        }
        env["PYTHONPATH"] = str(ROOT / ".deps") + os.pathsep + str(ROOT)
        log_path = state_dir / f"service-{args.port}.log"
        options = (
            {
                "creationflags": subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            }
            if os.name == "nt"
            else {"start_new_session": True}
        )
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **options,
            )
        state = {"pid": process.pid, "instance": instance}
        atomic_json(state_file, state)
        for _ in range(80):
            ready = health(args.port)
            if ready and ready.get("instance") == instance:
                break
            if process.poll() is not None:
                print(f"Server could not start. See {log_path}")
                return 1
            time.sleep(0.15)
        else:
            process.terminate()
            print(f"Startup health check timed out. See {log_path}")
            return 1
        access = f"ResolveDesk is running at {url}\n\n"
        if env.get("RESOLVEDESK_DISABLE_TOKENS") == "1":
            access += "Sign in with the named user created by manage.py.\n"
        else:
            access += (
                '1. Open the address above.\n2. Expand "Use a local development token".\n'
                "3. Paste the reviewer token below and click Connect.\n\nReviewer token:\n"
                + env["RESOLVEDESK_REVIEW_TOKEN"]
                + "\n\nOperator token:\n"
                + env["RESOLVEDESK_TOKEN"]
                + "\n"
            )
        access += "\nKeep these local credentials private. Do not include this file in screenshots or Git.\nThe server continues after the launcher closes. Restart it after reboot.\nStop it with Stop-ResolveDesk.cmd.\n"
        access_file.write_text(access, encoding="utf-8")
        if os.name != "nt":
            for path in (credentials_file, access_file):
                path.chmod(0o600)
    print(
        f"ResolveDesk is ready: {url}\nSign-in instructions: {access_file}\nIt continues running when this launcher closes."
    )
    if args.open:
        webbrowser.open(url)
        if os.name == "nt":
            os.startfile(access_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
