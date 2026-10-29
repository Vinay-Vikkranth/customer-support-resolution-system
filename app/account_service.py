"""Independent reference SaaS account service, with its own database and HTTP auth.

This service uses synthetic accounts. It demonstrates a real network integration,
not an integration with an actual customer's production system.
"""

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from .engine import decide
from .config import load_env

load_env()

DB = Path(os.environ.get("ACCOUNT_DB", "data/account-service.db"))
DB.parent.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get("ACCOUNT_API_TOKEN")
if not TOKEN:
    raise RuntimeError("Set ACCOUNT_API_TOKEN before starting the account service")


@contextmanager
def database():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


with database() as c:
    c.executescript("""CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT,plan TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY,account_id TEXT,name TEXT,status TEXT,reporting INTEGER);
    CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY,result TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);""")
    if not c.execute("SELECT 1 FROM accounts").fetchone():
        c.executemany(
            "INSERT INTO accounts VALUES(?,?,?,?)",
            [
                ("acme", "Acme Studio", "pro", "active"),
                ("birch", "Birch Works", "basic", "active"),
                ("cedar", "Cedar Labs", "enterprise", "past_due"),
            ],
        )
        c.executemany(
            "INSERT INTO members VALUES(?,?,?,?,?)",
            [
                ("alex", "acme", "Alex Morgan", "active", 0),
                ("jules", "acme", "Jules Chen", "active", 1),
                ("sam", "birch", "Sam Rivera", "active", 0),
                ("robin", "cedar", "Robin Lee", "active", 0),
                ("taylor", "acme", "Taylor Reed", "suspended", 0),
            ],
        )
        c.execute("INSERT INTO settings VALUES('incident','false')")

app = FastAPI(title="ResolveDesk reference account API", version="1.0.0")


def authorize(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, "Bearer " + TOKEN):
        raise HTTPException(401, "Account API authentication required")


def state(c, account_id, member_id):
    account = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    member = c.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not account or not member or member["account_id"] != account_id:
        raise HTTPException(404, "Account/member not found")
    return {
        "account": dict(account),
        "member": dict(member),
        "incident": c.execute(
            "SELECT value FROM settings WHERE key='incident'"
        ).fetchone()[0]
        == "true",
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/snapshot", dependencies=[Depends(authorize)])
def snapshot(account_id: str, member_id: str):
    with database() as c:
        return state(c, account_id, member_id)


@app.get("/v1/operation", dependencies=[Depends(authorize)])
def operation(key: str):
    with database() as c:
        result = c.execute(
            "SELECT result FROM operations WHERE key=?", (key,)
        ).fetchone()
        return json.loads(result[0]) if result else {"found": False}


class Restore(BaseModel):
    account_id: str = Field(max_length=80)
    member_id: str = Field(max_length=80)
    expected: str = Field(min_length=64, max_length=64)
    key: str = Field(min_length=10, max_length=150)


@app.post("/v1/restore", dependencies=[Depends(authorize)])
def restore(value: Restore):
    with database() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute(
            "SELECT result FROM operations WHERE key=?", (value.key,)
        ).fetchone()
        if previous:
            result = json.loads(previous[0])
            if (
                result["account_id"] != value.account_id
                or result["member_id"] != value.member_id
                or result["expected"] != value.expected
            ):
                raise HTTPException(
                    409, "Idempotency key was used for a different operation"
                )
            return result
        current = state(c, value.account_id, value.member_id)
        if fingerprint(current) != value.expected:
            raise HTTPException(409, "Remote account state changed")
        action, _, _ = decide(
            current["account"], current["member"], "reporting", current["incident"]
        )
        if action != "restore_reporting":
            raise HTTPException(409, "Remote policy denies restoration")
        c.execute("UPDATE members SET reporting=1 WHERE id=?", (value.member_id,))
        verified = bool(
            state(c, value.account_id, value.member_id)["member"]["reporting"]
        )
        if not verified:
            raise HTTPException(500, "Remote verification failed")
        result = {
            "found": True,
            "verified": True,
            "account_id": value.account_id,
            "member_id": value.member_id,
            "expected": value.expected,
            "key": value.key,
        }
        c.execute("INSERT INTO operations VALUES(?,?)", (value.key, json.dumps(result)))
        return result
