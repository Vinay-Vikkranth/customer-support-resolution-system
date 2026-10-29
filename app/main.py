import hashlib
import json
import os
import secrets
import sqlite3
import time
import logging
import csv
import io
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .engine import POLICIES, decide
from .security import initialize_security, session_user, login, token_hash
from .intelligence import analyze
from .connectors import fetch_zendesk_ticket
from .account_api import AccountGateway
from .config import load_env

load_env()

logging.basicConfig(level=logging.INFO, format="%(message)s")

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("RESOLVEDESK_DB", ROOT / "data" / "resolvedesk.db"))
DB.parent.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get("RESOLVEDESK_TOKEN") or secrets.token_urlsafe(32)
REVIEW_TOKEN = os.environ.get("RESOLVEDESK_REVIEW_TOKEN") or secrets.token_urlsafe(32)
if TOKEN == REVIEW_TOKEN:
    raise RuntimeError("Operator and reviewer credentials must be different")


@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def audit(con, ticket, event, actor, details):
    con.execute(
        "INSERT INTO audit(ticket_id,event,actor,details,created) VALUES(?,?,?,?,?)",
        (ticket, event, actor, json.dumps(details), time.time()),
    )


def initialize():
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT,plan TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY,account_id TEXT,name TEXT,status TEXT,reporting INTEGER);
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,title TEXT,body TEXT,account_id TEXT,member_id TEXT,feature TEXT,status TEXT DEFAULT 'open',created REAL);
        CREATE TABLE IF NOT EXISTS investigations(id INTEGER PRIMARY KEY,ticket_id INTEGER,action TEXT,reason TEXT,evidence TEXT,snapshot TEXT,status TEXT DEFAULT 'pending',created REAL,latency_ms REAL,draft TEXT,model_status TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,ticket_id INTEGER,event TEXT,actor TEXT,details TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        """)
        initialize_security(c)
        c.executescript("""
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,ticket_id INTEGER,body TEXT,actor TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS imports(source TEXT PRIMARY KEY,ticket_id INTEGER);
        """)
        columns = {r[1] for r in c.execute("PRAGMA table_info(investigations)")}
        for name in ("analysis", "trace", "usage"):
            if name not in columns:
                c.execute(
                    f"ALTER TABLE investigations ADD COLUMN {name} TEXT DEFAULT '{{}}'"
                )
        c.execute(
            "INSERT OR IGNORE INTO settings VALUES('workspace_id',?)",
            (secrets.token_hex(16),),
        )
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
            c.executemany(
                "INSERT INTO tickets(title,body,account_id,member_id,feature,created) VALUES(?,?,?,?,?,?)",
                [
                    (
                        "Reporting disappeared after upgrade",
                        "Our Pro subscription is active but Alex cannot open reports.",
                        "acme",
                        "alex",
                        "reporting",
                        time.time(),
                    ),
                    (
                        "Please enable reports",
                        "We would like reporting on our Basic plan.",
                        "birch",
                        "sam",
                        "reporting",
                        time.time(),
                    ),
                    (
                        "Cannot view the dashboard",
                        "Reporting is unavailable to Robin.",
                        "cedar",
                        "robin",
                        "reporting",
                        time.time(),
                    ),
                ],
            )


initialize()
app = FastAPI(
    title="ResolveDesk",
    version="2.0.0",
    description="Evidence-grounded support operations. Account actions execute in the synthetic sandbox; imported tickets never mutate external services.",
)


class Actor(str):
    def __new__(cls, role, username=None, name=None):
        obj = super().__new__(cls, role)
        obj.username = username or role
        obj.name = name or role.title()
        return obj


def identity(authorization: str = Header(default="")):
    value = authorization.removeprefix("Bearer ")
    if os.environ.get("RESOLVEDESK_DISABLE_TOKENS") != "1":
        if secrets.compare_digest(value, REVIEW_TOKEN):
            return Actor("reviewer")
        if secrets.compare_digest(value, TOKEN):
            return Actor("operator")
    with db() as c:
        user = session_user(c, value)
    if user:
        return Actor(user["role"], user["username"], user["name"])
    raise HTTPException(401, "Valid operator or reviewer token required")


def reviewer(actor=Depends(identity)):
    if actor != "reviewer":
        raise HTTPException(403, "Reviewer approval required")
    return actor


@app.middleware("http")
async def headers(request: Request, call_next):
    request_id = secrets.token_hex(8)
    started = time.perf_counter()
    # Bound payloads before parsing; clients must send Content-Length for large imports.
    if (
        request.headers.get("content-length", "0").isdigit()
        and int(request.headers.get("content-length", "0")) > 65536
    ):
        return JSONResponse({"detail": "Request exceeds 64 KB limit"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request_id
    response.headers["Referrer-Policy"] = "same-origin"
    logging.getLogger("resolvedesk").info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    )
    return response


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@app.post("/api/auth/login")
def sign_in(value: Login, request: Request):
    with db() as c:
        token, status = login(
            c,
            value.username,
            value.password,
            request.client.host if request.client else "unknown",
        )
    if status == "rate_limited":
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if not token:
        raise HTTPException(401, "Invalid username or password")
    return {"token": token, "expires_in": 28800}


@app.post("/api/auth/logout")
def sign_out(authorization: str = Header(default=""), actor=Depends(identity)):
    with db() as c:
        c.execute(
            "DELETE FROM sessions WHERE token=?",
            (token_hash(authorization.removeprefix("Bearer ")),),
        )
    return {"status": "signed_out"}


class Ticket(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=5, max_length=5000)
    account_id: str = Field(max_length=80)
    member_id: str = Field(max_length=80)
    feature: str = Field(default="reporting", max_length=80)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]


class Incident(BaseModel):
    active: bool


class Note(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CaseUpdate(BaseModel):
    status: Literal["open", "escalated", "closed"]
    reason: str = Field(min_length=5, max_length=1000)


class ZendeskImport(BaseModel):
    ticket_id: int = Field(gt=0)
    account_id: str = Field(max_length=80)
    member_id: str = Field(max_length=80)


def row(c, table, key):
    # Table names are internal constants, never request input.
    r = c.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    return dict(r) if r else None


def snapshot(c, t):
    if os.environ.get("ACCOUNT_API_URL"):
        try:
            return AccountGateway().snapshot(t["account_id"], t["member_id"])
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                503,
                "Account service unavailable; no local fallback or mutation was performed",
            ) from None
    return {
        "account": row(c, "accounts", t["account_id"]),
        "member": row(c, "members", t["member_id"]),
        "incident": c.execute(
            "SELECT value FROM settings WHERE key='incident'"
        ).fetchone()[0]
        == "true",
    }


def digest(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()


@app.get("/health")
def health():
    return {"status": "ok", "environment": "synthetic sandbox"}


@app.get("/api/bootstrap")
def bootstrap(actor=Depends(identity)):
    with db() as c:
        return {
            "role": str(actor),
            "name": actor.name,
            "username": actor.username,
            "accounts": [dict(r) for r in c.execute("SELECT * FROM accounts")],
            "members": [dict(r) for r in c.execute("SELECT * FROM members")],
            "policies": POLICIES,
            "incident": c.execute(
                "SELECT value FROM settings WHERE key='incident'"
            ).fetchone()[0]
            == "true",
            "ai_enabled": bool(os.environ.get("OPENAI_API_KEY")),
            "remote_accounts": bool(os.environ.get("ACCOUNT_API_URL")),
            "zendesk_configured": all(
                os.environ.get(k)
                for k in ("ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN")
            ),
        }


@app.get("/api/tickets")
def tickets(actor=Depends(identity)):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tickets ORDER BY id DESC")]


@app.post("/api/tickets", status_code=201)
def create_ticket(t: Ticket, actor=Depends(identity)):
    with db() as c:
        a = row(c, "accounts", t.account_id)
        m = row(c, "members", t.member_id)
        if not a or not m or m["account_id"] != a["id"]:
            raise HTTPException(422, "Account/member mismatch")
        cur = c.execute(
            "INSERT INTO tickets(title,body,account_id,member_id,feature,created) VALUES(?,?,?,?,?,?)",
            (*t.model_dump().values(), time.time()),
        )
        audit(c, cur.lastrowid, "ticket_created", actor.username, {})
        return row(c, "tickets", cur.lastrowid)


@app.get("/api/tickets/{tid}")
def detail(tid: int, actor=Depends(identity)):
    with db() as c:
        t = row(c, "tickets", tid)
        if not t:
            raise HTTPException(404, "Ticket not found")
        runs = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM investigations WHERE ticket_id=? ORDER BY id DESC",
                (tid,),
            )
        ]
        for r in runs:
            for name in ("evidence", "analysis", "trace", "usage"):
                r[name] = json.loads(r[name] or "{}")
        return {
            "ticket": t,
            "context": snapshot(c, t),
            "investigations": runs,
            "notes": [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM notes WHERE ticket_id=? ORDER BY id DESC", (tid,)
                )
            ],
            "audit": [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM audit WHERE ticket_id=? ORDER BY id DESC", (tid,)
                )
            ],
        }


@app.post("/api/tickets/{tid}/investigate")
def investigate(tid: int, actor=Depends(identity)):
    start = time.perf_counter()
    with db() as c:
        if os.environ.get("OPENAI_API_KEY"):
            recent = c.execute(
                "SELECT COUNT(*) FROM audit WHERE event='investigated' AND created>?",
                (time.time() - 86400,),
            ).fetchone()[0]
            if recent >= int(os.environ.get("RESOLVEDESK_DAILY_AI_LIMIT", "200")):
                raise HTTPException(
                    429,
                    "Daily investigation allowance reached; try later or adjust the server limit",
                )
        t = row(c, "tickets", tid)
        if not t:
            raise HTTPException(404, "Ticket not found")
        if t["status"] in ("resolved", "closed"):
            raise HTTPException(409, "Reopen the ticket before investigating")
        if c.execute(
            "SELECT 1 FROM investigations WHERE ticket_id=? AND status='execution_unknown'",
            (tid,),
        ).fetchone():
            raise HTTPException(
                409,
                "Reconcile the uncertain remote action by retrying its approval first",
            )
        s = snapshot(c, t)
    result = analyze(t, s)
    action, reason, evidence, draft, mode = (
        result[k] for k in ("action", "reason", "evidence", "draft", "model_status")
    )
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if row(c, "tickets", tid)["status"] in ("resolved", "closed"):
            raise HTTPException(409, "Ticket closed during investigation")
        if c.execute(
            "SELECT 1 FROM investigations WHERE ticket_id=? AND status='execution_unknown'",
            (tid,),
        ).fetchone():
            raise HTTPException(409, "Reconcile uncertain remote execution first")
        if digest(snapshot(c, t)) != digest(s):
            raise HTTPException(409, "Evidence changed during investigation; retry")
        c.execute(
            "UPDATE investigations SET status='superseded' WHERE ticket_id=? AND status='pending'",
            (tid,),
        )
        cur = c.execute(
            "INSERT INTO investigations(ticket_id,action,reason,evidence,snapshot,created,latency_ms,draft,model_status) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                action,
                reason,
                json.dumps(evidence),
                digest(s),
                time.time(),
                round((time.perf_counter() - start) * 1000, 2),
                draft,
                mode,
            ),
        )
        c.execute(
            "UPDATE investigations SET analysis=?,trace=?,usage=? WHERE id=?",
            (
                json.dumps(result["analysis"]),
                json.dumps(result["trace"]),
                json.dumps(result["usage"]),
                cur.lastrowid,
            ),
        )
        c.execute("UPDATE tickets SET status='awaiting_review' WHERE id=?", (tid,))
        audit(
            c,
            tid,
            "investigated",
            actor.username,
            {"action": action, "run_id": cur.lastrowid, "model_status": mode},
        )
        return {"id": cur.lastrowid, **result}


@app.post("/api/investigations/{rid}/decision")
def approve(rid: int, decision: Decision, actor=Depends(reviewer)):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        r = row(c, "investigations", rid)
        if not r:
            raise HTTPException(404, "Investigation not found")
        if r["status"] in ("approved", "rejected"):
            if (
                r["status"]
                != {"approve": "approved", "reject": "rejected"}[decision.decision]
            ):
                raise HTTPException(409, "A different decision was already recorded")
            return {"status": r["status"], "replayed": True}
        if r["status"] not in ("pending", "execution_unknown"):
            raise HTTPException(409, "Run superseded; investigate again")
        t = row(c, "tickets", r["ticket_id"])
        remote = None
        recovered = None
        operation_key = None
        if os.environ.get("ACCOUNT_API_URL") and r["action"] == "restore_reporting":
            try:
                remote = AccountGateway()
                workspace = c.execute(
                    "SELECT value FROM settings WHERE key='workspace_id'"
                ).fetchone()[0]
                operation_key = f"{workspace}:investigation:{rid}"
                recovered = remote.lookup(operation_key)
            except (httpx.HTTPError, ValueError):
                raise HTTPException(
                    503,
                    "Cannot verify remote operation state. Retry this same proposal.",
                ) from None
        if recovered and recovered.get("found"):
            if decision.decision == "reject":
                raise HTTPException(
                    409,
                    "The remote action already completed. Approve again to reconcile its result.",
                )
            if (
                not recovered.get("verified")
                or recovered.get("account_id") != t["account_id"]
                or recovered.get("member_id") != t["member_id"]
                or recovered.get("expected") != r["snapshot"]
            ):
                raise HTTPException(
                    502, "Remote operation result could not be verified"
                )
            c.execute("UPDATE tickets SET status='resolved' WHERE id=?", (t["id"],))
            c.execute("UPDATE investigations SET status='approved' WHERE id=?", (rid,))
            audit(
                c,
                t["id"],
                "remote_execution_reconciled",
                actor.username,
                {"run_id": rid, "key": operation_key},
            )
            return {
                "status": "approved",
                "ticket_status": "resolved",
                "verified": True,
                "reconciled": True,
            }
        if decision.decision == "reject":
            if r["status"] == "execution_unknown":
                raise HTTPException(
                    409,
                    "Retry approval to reconcile the uncertain remote action before any other decision",
                )
            c.execute("UPDATE investigations SET status='rejected' WHERE id=?", (rid,))
            c.execute("UPDATE tickets SET status='open' WHERE id=?", (t["id"],))
            audit(c, t["id"], "rejected", actor.username, {"run_id": rid})
            return {"status": "rejected"}
        s = snapshot(c, t)
        if digest(s) != r["snapshot"]:
            raise HTTPException(409, "Account state changed; investigate again")
        action, _, _ = decide(s["account"], s["member"], t["feature"], s["incident"])
        if action != r["action"]:
            raise HTTPException(409, "Policy decision changed")
        if action == "restore_reporting":
            if remote:
                try:
                    result = remote.restore(
                        t["account_id"], t["member_id"], r["snapshot"], operation_key
                    )
                    verified = (
                        bool(result.get("verified"))
                        and result.get("account_id") == t["account_id"]
                        and result.get("member_id") == t["member_id"]
                        and result.get("expected") == r["snapshot"]
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 409:
                        raise HTTPException(
                            409, "Remote account changed; investigate again"
                        ) from None
                    c.execute(
                        "UPDATE investigations SET status='execution_unknown' WHERE id=?",
                        (rid,),
                    )
                    audit(
                        c,
                        t["id"],
                        "remote_execution_uncertain",
                        actor.username,
                        {"run_id": rid, "key": operation_key},
                    )
                    return JSONResponse(
                        {
                            "detail": "Remote execution could not be confirmed. Retry approval on this proposal to reconcile."
                        },
                        status_code=503,
                    )
                except httpx.HTTPError:
                    c.execute(
                        "UPDATE investigations SET status='execution_unknown' WHERE id=?",
                        (rid,),
                    )
                    audit(
                        c,
                        t["id"],
                        "remote_execution_uncertain",
                        actor.username,
                        {"run_id": rid, "key": operation_key},
                    )
                    return JSONResponse(
                        {
                            "detail": "Remote execution could not be confirmed. Retry approval on this proposal to reconcile."
                        },
                        status_code=503,
                    )
            else:
                c.execute(
                    "UPDATE members SET reporting=1 WHERE id=?", (t["member_id"],)
                )
                verified = bool(row(c, "members", t["member_id"])["reporting"])
            if not verified:
                if remote:
                    c.execute(
                        "UPDATE investigations SET status='execution_unknown' WHERE id=?",
                        (rid,),
                    )
                    return JSONResponse(
                        {
                            "detail": "Remote verification incomplete. Retry this approval to reconcile."
                        },
                        status_code=503,
                    )
                raise HTTPException(500, "Verification failed; transaction rolled back")
            status = "resolved"
        else:
            status = "escalated"
        c.execute("UPDATE tickets SET status=? WHERE id=?", (status, t["id"]))
        c.execute("UPDATE investigations SET status='approved' WHERE id=?", (rid,))
        audit(
            c,
            t["id"],
            "approved_and_verified" if status == "resolved" else "escalated",
            actor.username,
            {"run_id": rid, "action": action, "status": status},
        )
        return {
            "status": "approved",
            "ticket_status": status,
            "verified": status == "resolved",
        }


@app.post("/api/sandbox/incident")
def incident(value: Incident, actor=Depends(reviewer)):
    if os.environ.get("ACCOUNT_API_URL"):
        raise HTTPException(
            409, "Manage service incidents at the connected account service"
        )
    with db() as c:
        c.execute(
            "UPDATE settings SET value=? WHERE key='incident'",
            ("true" if value.active else "false",),
        )
        audit(c, None, "incident_changed", actor.username, {"active": value.active})
    return value


@app.get("/api/metrics")
def metrics(actor=Depends(identity)):
    with db() as c:
        return {
            "tickets": c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
            "resolved": c.execute(
                "SELECT COUNT(*) FROM tickets WHERE status='resolved'"
            ).fetchone()[0],
            "awaiting_review": c.execute(
                "SELECT COUNT(*) FROM tickets WHERE status='awaiting_review'"
            ).fetchone()[0],
            "investigations": c.execute(
                "SELECT COUNT(*) FROM investigations"
            ).fetchone()[0],
            "mean_latency_ms": c.execute(
                "SELECT ROUND(AVG(latency_ms),2) FROM investigations"
            ).fetchone()[0]
            or 0,
        }


@app.post("/api/tickets/{tid}/notes", status_code=201)
def add_note(tid: int, value: Note, actor=Depends(identity)):
    with db() as c:
        if not row(c, "tickets", tid):
            raise HTTPException(404, "Ticket not found")
        c.execute(
            "INSERT INTO notes(ticket_id,body,actor,created) VALUES(?,?,?,?)",
            (tid, value.body, actor.username, time.time()),
        )
        audit(c, tid, "note_added", actor.username, {})
    return {"status": "saved"}


@app.patch("/api/tickets/{tid}")
def update_case(tid: int, value: CaseUpdate, actor=Depends(reviewer)):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not row(c, "tickets", tid):
            raise HTTPException(404, "Ticket not found")
        if c.execute(
            "SELECT 1 FROM investigations WHERE ticket_id=? AND status='execution_unknown'",
            (tid,),
        ).fetchone():
            raise HTTPException(
                409, "Reconcile uncertain remote execution before changing this case"
            )
        c.execute("UPDATE tickets SET status=? WHERE id=?", (value.status, tid))
        c.execute(
            "UPDATE investigations SET status='superseded' WHERE ticket_id=? AND status='pending'",
            (tid,),
        )
        audit(c, tid, "case_status_changed", actor.username, value.model_dump())
    return {"status": value.status}


@app.get("/api/export")
def export_cases(actor=Depends(identity)):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Subject", "Account", "Member", "Feature", "Status", "Created (UTC)"]
    )

    def safe(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    with db() as c:
        for t in c.execute("SELECT * FROM tickets ORDER BY id"):
            writer.writerow(
                [
                    safe(t[k])
                    for k in (
                        "id",
                        "title",
                        "account_id",
                        "member_id",
                        "feature",
                        "status",
                    )
                ]
                + [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t["created"]))]
            )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="resolvedesk-cases.csv"'},
    )


@app.post("/api/integrations/zendesk/import", status_code=201)
def import_zendesk(value: ZendeskImport, actor=Depends(reviewer)):
    try:
        external = fetch_zendesk_ticket(value.ticket_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except (httpx.HTTPError, KeyError, TypeError):
        raise HTTPException(
            502, "Zendesk unavailable or returned invalid data"
        ) from None
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT ticket_id FROM imports WHERE source=?", (external["source"],)
        ).fetchone()
        if existing:
            return {"id": existing[0], "replayed": True}
        a = row(c, "accounts", value.account_id)
        m = row(c, "members", value.member_id)
        if not a or not m or m["account_id"] != a["id"]:
            raise HTTPException(422, "Account/member mismatch")
        cur = c.execute(
            "INSERT INTO tickets(title,body,account_id,member_id,feature,created) VALUES(?,?,?,?,?,?)",
            (
                external["title"],
                external["body"],
                value.account_id,
                value.member_id,
                "reporting",
                time.time(),
            ),
        )
        c.execute(
            "INSERT INTO imports VALUES(?,?)", (external["source"], cur.lastrowid)
        )
        audit(
            c,
            cur.lastrowid,
            "imported_from_zendesk",
            actor.username,
            {"source": external["source"], "execution": "local sandbox only"},
        )
        return {"id": cur.lastrowid, "replayed": False}


@app.get("/api/operations")
def operations(actor=Depends(reviewer)):
    with db() as c:
        modes = [
            dict(r)
            for r in c.execute(
                "SELECT model_status,COUNT(*) count FROM investigations GROUP BY model_status"
            )
        ]
        totals = {"input_tokens": 0, "output_tokens": 0}
        for r in c.execute("SELECT usage FROM investigations"):
            usage = json.loads(r[0] or "{}")
            for k in totals:
                totals[k] += usage.get(k, 0)
        events = [
            dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")
        ]
    return {
        "modes": modes,
        "usage": totals,
        "events": events,
        "cost_usd": None,
        "cost_note": "Token totals are measured; cost requires your provider pricing.",
    }


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")
