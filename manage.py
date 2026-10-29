"""Administrative commands run on the server, never exposed as public registration."""

import argparse
import getpass
import json
import sqlite3
import sys
from pathlib import Path

deps = Path(__file__).parent / ".deps"
if deps.exists():
    sys.path.insert(0, str(deps))
from app.main import db, DB
from app.security import create_user

parser = argparse.ArgumentParser(description="ResolveDesk administration")
commands = parser.add_subparsers(dest="command", required=True)
user = commands.add_parser("create-user")
user.add_argument("username")
user.add_argument("--name", required=True)
user.add_argument("--role", choices=["operator", "reviewer"], required=True)
disable = commands.add_parser("disable-user")
disable.add_argument("username")
backup = commands.add_parser("backup")
backup.add_argument("destination")
commands.add_parser("check")
args = parser.parse_args()
if args.command == "create-user":
    password = getpass.getpass("Password (12+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    with db() as c:
        create_user(c, args.username, args.name, args.role, password)
    print("User created.")
elif args.command == "disable-user":
    with db() as c:
        c.execute(
            "UPDATE users SET active=0 WHERE username=?", (args.username.lower(),)
        )
        c.execute("DELETE FROM sessions WHERE username=?", (args.username.lower(),))
    print("User disabled; sessions revoked.")
elif args.command == "backup":
    destination = Path(args.destination)
    if destination.exists():
        raise SystemExit(
            "Choose a new destination; existing backups are not overwritten."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with db() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    print("Backup created:", destination)
else:
    with db() as c:
        print(
            json.dumps(
                {
                    "database": str(DB),
                    "integrity": c.execute("PRAGMA integrity_check").fetchone()[0],
                    "active_users": c.execute(
                        "SELECT COUNT(*) FROM users WHERE active=1"
                    ).fetchone()[0],
                }
            )
        )
