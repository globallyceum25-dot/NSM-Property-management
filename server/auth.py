"""Sign-in: user accounts, password hashing and sessions.

Passwords are stored only as PBKDF2-SHA256 hashes (600,000 iterations, a
random salt each). A session is a random token in an HttpOnly cookie; the
database keeps only its SHA-256, so a copy of the database cannot be used to
sign in. Wrong passwords are throttled per address and lock an account for a
while after five in a row, and every message about a failed sign-in is the
same, so nobody can find out which emails have accounts.

The first Super Admin is created on a setup screen that asks for a one-time
code printed in the server's terminal, or, for containers, from the
REGISTER_ADMIN_EMAIL / REGISTER_ADMIN_PASSWORD environment variables.
"""

import base64
import collections
import datetime
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from typing import DefaultDict, Deque

from . import access, db
from .errors import ApiError

ITERATIONS = int(os.environ.get("REGISTER_PBKDF2_ITERATIONS") or 600000)
MIN_PASSWORD_LENGTH = 10
COOKIE = "pr_session"
SESSION_HOURS = 12            # without "keep me signed in": 12 hours since last use
REMEMBER_DAYS = 30            # with it: 30 days
MAX_FAILED = 5                # wrong passwords in a row before a lock
LOCK_MINUTES = 15
IP_WINDOW_SECONDS = 15 * 60   # failed attempts per address, per window: wrong passwords,
IP_MAX_ATTEMPTS = int(os.environ.get("REGISTER_SIGNIN_ATTEMPTS") or 30)   # setup codes...

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- time ----------------------------------------------------------------------

def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")   # sorts and compares as text


# --- passwords -----------------------------------------------------------------

def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def hash_password(password, iterations=None):
    iterations = iterations or ITERATIONS
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, _b64(salt), _b64(digest))


def verify_password(password, stored):
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                    base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(check, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_dummy_hash = None


def _burn_time(password):
    """Spend as long as a real check does, so an unknown email is not faster."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(password, _dummy_hash)


def password_problem(password, email=None):
    """Why a new password is not acceptable, or None."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return "Use at least %d characters." % MIN_PASSWORD_LENGTH
    if len(set(password)) < 4:
        return "Use a less repetitive password."
    if email and password.lower() == email.lower():
        return "The password cannot be the email address."
    return None


# --- users ---------------------------------------------------------------------

def role_name(conn, code):
    row = conn.execute("SELECT name FROM app_role WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else code


def _public(conn, row):
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"],
            "roleLabel": role_name(conn, row["role"]),
            "mustChangePassword": bool(row["must_change_password"])}


def count_users(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM app_user").fetchone()["n"]


def create_user(conn, email, name, role, password, must_change=False):
    email = (email or "").strip().lower()
    name = (name or "").strip()
    if not name:
        raise ApiError("Enter the person's name.", field="name")
    if not EMAIL_RE.match(email):
        raise ApiError("Enter a valid email address.", field="email")
    if not conn.execute("SELECT 1 FROM app_role WHERE code = ?", (role,)).fetchone():
        raise ApiError("Choose a role.", field="role")
    problem = password_problem(password, email)
    if problem:
        raise ApiError(problem, field="password")
    if conn.execute("SELECT 1 FROM app_user WHERE email = ?", (email,)).fetchone():
        raise ApiError("There is already an account for %s." % email, 409, "email")
    stamp = _iso(_now())
    new_id = conn.execute(
        """INSERT INTO app_user (email, name, role, password_hash, must_change_password,
                                 created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (email, name, role, hash_password(password), 1 if must_change else 0, stamp, stamp)).fetchone()["id"]
    conn.commit()
    return new_id


def set_password(conn, email, password, must_change=False, keep_session=None):
    """A new password. It signs the person out everywhere, except (when they
    changed it themselves) the session they changed it from."""
    email = (email or "").strip().lower()
    problem = password_problem(password, email)
    if problem:
        raise ApiError(problem, field="password")
    row = conn.execute("SELECT id FROM app_user WHERE email = ?", (email,)).fetchone()
    if row is None:
        raise ApiError("No account for %s." % email, 404, "email")
    conn.execute("""UPDATE app_user SET password_hash = ?, failed_logins = 0, locked_until = NULL,
                    must_change_password = ?, updated_at = ? WHERE id = ?""",
                 (hash_password(password), 1 if must_change else 0, _iso(_now()), row["id"]))
    if keep_session:
        conn.execute("DELETE FROM app_session WHERE user_id = ? AND token_hash <> ?",
                     (row["id"], _token_hash(keep_session)))
    else:
        conn.execute("DELETE FROM app_session WHERE user_id = ?", (row["id"],))
    conn.commit()


def temporary_password():
    """A one-time password an administrator passes on, often by phone, so it
    avoids letters that are easy to mix up (l, 1, i, o, 0). About 59 bits."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    chars = "".join(secrets.choice(alphabet) for _ in range(12))
    return "%s-%s-%s" % (chars[:4], chars[4:8], chars[8:12])


# --- sessions ------------------------------------------------------------------

def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(conn, user_id, remember, ip=None, agent=None):
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + (datetime.timedelta(days=REMEMBER_DAYS) if remember
                     else datetime.timedelta(hours=SESSION_HOURS))
    conn.execute(
        """INSERT INTO app_session (token_hash, user_id, remember, created_at, last_seen_at,
                                    expires_at, ip, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (_token_hash(token), user_id, 1 if remember else 0, _iso(now), _iso(now), _iso(expires),
         ip, (agent or "")[:300]))
    conn.execute("UPDATE app_user SET last_login_at = ?, failed_logins = 0, locked_until = NULL "
                 "WHERE id = ?", (_iso(now), user_id))
    conn.execute("DELETE FROM app_session WHERE expires_at < ?", (_iso(now),))
    conn.commit()
    return token, (REMEMBER_DAYS * 86400 if remember else None)


def user_for_token(conn, token):
    if not token:
        return None
    now = _now()
    row = conn.execute(
        """SELECT u.*, s.token_hash, s.remember, s.last_seen_at, s.expires_at
           FROM app_session s JOIN app_user u ON u.id = s.user_id
           WHERE s.token_hash = ?""", (_token_hash(token),)).fetchone()
    if row is None or row["expires_at"] < _iso(now) or not row["is_active"]:
        return None
    # Without "keep me signed in", a session lasts 12 hours from its last use.
    # Refreshed at most every 5 minutes, so reads stay reads.
    if not row["remember"] and row["last_seen_at"] < _iso(now - datetime.timedelta(minutes=5)):
        conn.execute("UPDATE app_session SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                     (_iso(now), _iso(now + datetime.timedelta(hours=SESSION_HOURS)), row["token_hash"]))
        conn.commit()
    return _public(conn, row)


def end_session(conn, token):
    if token:
        conn.execute("DELETE FROM app_session WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()


# --- throttling ----------------------------------------------------------------

# Recent failed attempt times per address, for this server process. Only
# failures count, so an office signing in from one shared address is not
# throttled by its own everyday sign-ins.
_attempts: DefaultDict[str, Deque[float]] = collections.defaultdict(collections.deque)
_attempts_lock = threading.Lock()


def _throttle(ip):
    """Refuse an address that has failed too often lately."""
    now = time.monotonic()
    with _attempts_lock:
        recent = _attempts[ip or "?"]
        while recent and now - recent[0] > IP_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= IP_MAX_ATTEMPTS:
            raise ApiError("Too many failed attempts from this computer. Wait a few minutes "
                           "and try again.", 429)


def failed_attempt(ip):
    with _attempts_lock:
        _attempts[ip or "?"].append(time.monotonic())


# --- first-run setup -----------------------------------------------------------

_setup_code = None


def setup_code(conn):
    """The one-time code for the setup screen while no account exists, else None."""
    global _setup_code
    if count_users(conn):
        _setup_code = None
        return None
    if _setup_code is None:
        raw = secrets.token_hex(4).upper()
        _setup_code = raw[:4] + "-" + raw[4:]
    return _setup_code


def bootstrap_from_env(conn):
    """Containers: create the first Super Admin from the environment, once."""
    email = os.environ.get("REGISTER_ADMIN_EMAIL")
    password = os.environ.get("REGISTER_ADMIN_PASSWORD")
    if email and password and not count_users(conn):
        create_user(conn, email, os.environ.get("REGISTER_ADMIN_NAME") or "Administrator",
                    "SUPER_ADMIN", password)
        return True
    return False


# --- request helpers -----------------------------------------------------------

def token_from(handler):
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return None
    morsel = cookie.get(COOKIE)
    return morsel.value if morsel else None


def _secure(handler):
    return (os.environ.get("REGISTER_SECURE_COOKIES") == "1"
            or (handler.headers.get("X-Forwarded-Proto") or "").lower() == "https")


def session_cookie(handler, token, max_age):
    parts = ["%s=%s" % (COOKIE, token), "Path=/", "HttpOnly", "SameSite=Lax"]
    if max_age:
        parts.append("Max-Age=%d" % max_age)
    if _secure(handler):
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie(handler):
    parts = ["%s=" % COOKIE, "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if _secure(handler):
        parts.append("Secure")
    return "; ".join(parts)


def client_ip(handler):
    return handler.client_address[0] if handler.client_address else None


# --- endpoints -----------------------------------------------------------------

def get_status(ctx):
    conn = db.get_conn()
    user = user_for_token(conn, token_from(ctx.handler))
    out = {"signedIn": user is not None, "user": user,
           "needsSetup": user is None and count_users(conn) == 0}
    if user is not None:
        out["access"] = access.load(conn, user).public()
    return 200, out


def login(ctx):
    conn = db.get_conn()
    data = ctx.json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        raise ApiError("Enter your email and password.", field="email" if not email else "password")
    _throttle(client_ip(ctx.handler))

    ip = client_ip(ctx.handler)
    wrong = ApiError("The email or password is incorrect.", 401, "password")
    row = conn.execute("SELECT * FROM app_user WHERE email = ?", (email,)).fetchone()
    if row is None:
        _burn_time(password)
        failed_attempt(ip)
        access.record(conn, "auth.failed", email, "Unknown email address", ip=ip)
        raise wrong
    person = {"id": row["id"], "name": row["name"], "email": row["email"]}
    now = _now()
    if row["locked_until"] and row["locked_until"] > _iso(now):
        _burn_time(password)
        failed_attempt(ip)
        access.record(conn, "auth.failed", email, "Account locked", person, ip)
        raise ApiError("Too many wrong passwords. This account is locked for a few minutes; "
                       "try again later or ask your administrator.", 423)
    if not verify_password(password, row["password_hash"]):
        failed_attempt(ip)
        failed = (row["failed_logins"] or 0) + 1
        locked = _iso(now + datetime.timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED else None
        conn.execute("UPDATE app_user SET failed_logins = ?, locked_until = ? WHERE id = ?",
                     (0 if locked else failed, locked, row["id"]))
        access.record(conn, "auth.locked" if locked else "auth.failed", email,
                      "Locked for %d minutes after %d wrong passwords" % (LOCK_MINUTES, MAX_FAILED)
                      if locked else "Wrong password", person, ip)
        raise wrong
    if not row["is_active"]:
        access.record(conn, "auth.failed", email, "Account switched off", person, ip)
        raise ApiError("This account has been switched off. Ask your administrator.", 403)

    token, max_age = start_session(conn, row["id"], bool(data.get("remember")),
                                   ip, ctx.handler.headers.get("User-Agent"))
    access.record(conn, "auth.sign_in", email,
                  "Kept signed in for %d days" % REMEMBER_DAYS if data.get("remember") else "", person, ip)
    ctx.add_header("Set-Cookie", session_cookie(ctx.handler, token, max_age))
    return 200, {"signedIn": True, "user": _public(conn, row)}


def logout(ctx):
    conn = db.get_conn()
    token = token_from(ctx.handler)
    user = user_for_token(conn, token)
    if user:
        access.record(conn, "auth.sign_out", user["email"], "", user, client_ip(ctx.handler))
    end_session(conn, token)
    ctx.add_header("Set-Cookie", clear_cookie(ctx.handler))
    return 200, {"signedIn": False}


def setup(ctx):
    """The first Super Admin, with the code from the server's terminal."""
    conn = db.get_conn()
    data = ctx.json()
    _throttle(client_ip(ctx.handler))
    code = setup_code(conn)
    if code is None:
        raise ApiError("The register is already set up. Sign in instead.", 409)
    given = (data.get("setupCode") or "").strip().upper().replace(" ", "")
    if not hmac.compare_digest(given.encode(), code.encode()):
        failed_attempt(client_ip(ctx.handler))
        raise ApiError("That setup code is not right. Copy it from the terminal where the "
                       "register is running.", 400, "setupCode")
    if (data.get("password") or "") != (data.get("confirm") or ""):
        raise ApiError("The two passwords do not match.", field="confirm")
    user_id = create_user(conn, data.get("email"), data.get("name"), "SUPER_ADMIN", data.get("password"))
    setup_code(conn)    # clears the code now that an account exists
    token, max_age = start_session(conn, user_id, False, client_ip(ctx.handler),
                                   ctx.handler.headers.get("User-Agent"))
    ctx.add_header("Set-Cookie", session_cookie(ctx.handler, token, max_age))
    row = conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
    access.record(conn, "user.create", row["email"], "First Super Admin, created with the setup code",
                  {"id": row["id"], "name": row["name"], "email": row["email"]}, client_ip(ctx.handler))
    return 201, {"signedIn": True, "user": _public(conn, row)}


# Reachable without signing in. Everything else under /api/ needs a session.
PUBLIC = {
    ("GET", "/api/reference"),     # the health check; enumerations only, no register data
    ("GET", "/api/auth/status"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/setup"),
}

ROUTES = [
    ("GET", r"^/api/auth/status$", get_status),
    ("POST", r"^/api/auth/login$", login),
    ("POST", r"^/api/auth/logout$", logout),
    ("POST", r"^/api/auth/setup$", setup),
]
