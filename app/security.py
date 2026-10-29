"""Named, revocable sessions; no passwords or raw session tokens are persisted."""

import hashlib
import hmac
import secrets
import time


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1
    ).hex()
    return f"{salt}:{value}"


def password_matches(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def initialize_security(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, name TEXT NOT NULL,
      role TEXT NOT NULL, password TEXT NOT NULL, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, username TEXT NOT NULL,
      expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS login_attempts(address TEXT PRIMARY KEY, attempts INTEGER, since REAL);
    """)


def create_user(c, username, name, role, password):
    if role not in ("operator", "reviewer") or len(password) < 12:
        raise ValueError(
            "Use operator/reviewer and a password of at least 12 characters"
        )
    c.execute(
        "INSERT INTO users(username,name,role,password) VALUES(?,?,?,?)",
        (username.lower(), name, role, password_hash(password)),
    )


def login(c, username, password, address):
    now = time.time()
    attempt = c.execute(
        "SELECT * FROM login_attempts WHERE address=?", (address,)
    ).fetchone()
    if attempt and attempt["since"] > now - 900 and attempt["attempts"] >= 10:
        return None, "rate_limited"
    if not attempt or attempt["since"] <= now - 900:
        c.execute("INSERT OR REPLACE INTO login_attempts VALUES(?,0,?)", (address, now))
    user = c.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username.lower(),)
    ).fetchone()
    # Equal-cost failure for unknown usernames.
    stored = (
        user["password"]
        if user
        else password_hash("unused-random-placeholder", "0" * 32)
    )
    valid = password_matches(password, stored)
    if not user or not valid:
        c.execute(
            "UPDATE login_attempts SET attempts=attempts+1 WHERE address=?", (address,)
        )
        return None, "invalid"
    c.execute("DELETE FROM login_attempts WHERE address=?", (address,))
    c.execute("DELETE FROM sessions WHERE expires<?", (now,))
    token = secrets.token_urlsafe(40)
    c.execute(
        "INSERT INTO sessions VALUES(?,?,?)",
        (token_hash(token), user["username"], now + 28800),
    )
    return token, "ok"


def session_user(c, token):
    result = c.execute(
        """SELECT u.username,u.name,u.role FROM sessions s JOIN users u
        ON u.username=s.username WHERE s.token=? AND s.expires>? AND u.active=1""",
        (token_hash(token), time.time()),
    ).fetchone()
    return dict(result) if result else None
