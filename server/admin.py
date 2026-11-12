"""Users & access: people, roles, the audit log, and changing your own password.

Who may call each endpoint is decided in access.ROUTE_PERMISSIONS before the
handler runs; the rules below are the finer ones:

- Only someone who holds a protected role (Super Admin, or a role that can
  manage roles) may create, change or switch off a person with a protected role,
  or give anyone such a role. Nobody can hand out more power than they hold.
- Nobody can change their own role or switch themselves off, and the last
  active Super Admin cannot be removed, so the register can't be locked out.
- New people and password resets get a one-time temporary password, shown to
  the administrator once; the person must replace it when they first sign in.
"""

import datetime

from . import access, auth, db
from .errors import ApiError


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ip(ctx):
    return access.client_ip(ctx)


def _roles(conn):
    """{code: row} for every role, with its levels and whether it is protected."""
    out = {}
    for row in conn.execute("SELECT * FROM app_role ORDER BY sort_order, name"):
        levels = access.role_levels(conn, row["code"])
        out[row["code"]] = {"row": row, "levels": levels,
                            "protected": access.is_protected_role(levels, row["code"])}
    return out


def _acting_is_protected(ctx, roles):
    role = roles.get(ctx.user["role"])
    return bool(role and role["protected"])


def _names(conn, table, column, ids):
    if not ids:
        return []
    rows = conn.execute("SELECT id, %s AS label FROM %s WHERE id IN (%s)"
                        % (column, table, ",".join("?" * len(ids))), ids).fetchall()
    found = {r["id"]: r["label"] for r in rows}
    return [{"id": i, "label": found[i]} for i in ids if i in found]


def _user_json(conn, row, ctx, roles, sessions):
    scope = access.user_scope(conn, row["id"])
    role = roles.get(row["role"])
    now = _now()
    locked = bool(row["locked_until"] and row["locked_until"] > now)
    protected = bool(role and role["protected"])
    may_touch = not protected or _acting_is_protected(ctx, roles)
    you = row["id"] == ctx.user["id"]
    return {
        "id": row["id"], "name": row["name"], "email": row["email"],
        "role": row["role"], "roleLabel": role["row"]["name"] if role else row["role"],
        "status": "off" if not row["is_active"] else ("locked" if locked else "active"),
        "isActive": bool(row["is_active"]), "lockedUntil": row["locked_until"] if locked else None,
        "lastLoginAt": row["last_login_at"], "createdAt": row["created_at"],
        "mustChangePassword": bool(row["must_change_password"]),
        "sessions": sessions.get(row["id"], 0),
        "scope": scope,
        "scopeLabels": {"types": _names(conn, "sbu", "name", scope["types"]),
                        "companies": _names(conn, "legal_entity", "short_code", scope["companies"])},
        "isYou": you, "protected": protected,
        "canEdit": ctx.access.can("users.edit") and may_touch,
        "canDeactivate": ctx.access.can("users.deactivate") and may_touch and not you,
    }


def _session_counts(conn):
    rows = conn.execute("SELECT user_id, COUNT(*) AS n FROM app_session WHERE expires_at > ? GROUP BY user_id",
                        (_now(),)).fetchall()
    return {r["user_id"]: r["n"] for r in rows}


def _visible(ctx, conn, row):
    """Limited users.view: only people sharing one of your property types or companies."""
    if ctx.access.level("users.view") != "limited" or row["id"] == ctx.user["id"]:
        return True
    theirs = access.user_scope(conn, row["id"])
    return bool(set(theirs["types"]) & set(ctx.access.types)
                or set(theirs["companies"]) & set(ctx.access.companies))


def _get_row(conn, user_id):
    row = conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError("No such user.", 404)
    return row


def _clean_scope(conn, scope):
    scope = scope or {}
    out = {}
    for kind, table, label in (("types", "sbu", "property type"), ("companies", "legal_entity", "owning company")):
        ids = []
        for value in scope.get(kind) or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                raise ApiError("Unknown %s." % label, field="scope") from None
        ids = sorted(set(ids))
        if ids:
            found = conn.execute("SELECT COUNT(*) AS n FROM %s WHERE id IN (%s)"
                                 % (table, ",".join("?" * len(ids))), ids).fetchone()["n"]
            if found != len(ids):
                raise ApiError("One of the chosen %s entries no longer exists." % label, field="scope")
        out[kind] = ids
    return out


def _save_scope(conn, user_id, scope):
    conn.execute("DELETE FROM app_user_scope WHERE user_id = ?", (user_id,))
    for kind, db_kind in (("types", "type"), ("companies", "company")):
        for ref in scope[kind]:
            conn.execute("INSERT INTO app_user_scope (user_id, kind, ref_id) VALUES (?, ?, ?)",
                         (user_id, db_kind, ref))


def _scope_text(conn, scope):
    types = ", ".join(x["label"] for x in _names(conn, "sbu", "name", scope["types"])) or "any type"
    companies = ", ".join(x["label"] for x in _names(conn, "legal_entity", "short_code", scope["companies"])) \
        or "any company"
    if not scope["types"] and not scope["companies"]:
        return "nothing assigned"
    return "%s; %s" % (types, companies)


def _check_role_choice(ctx, roles, code):
    if code not in roles:
        raise ApiError("Choose a role.", field="role")
    if roles[code]["protected"] and not _acting_is_protected(ctx, roles):
        raise ApiError("Only a Super Admin can give someone the %s role." % roles[code]["row"]["name"],
                       403, "role")


def _check_may_touch(ctx, roles, row, verb="change"):
    role = roles.get(row["role"])
    if role and role["protected"] and not _acting_is_protected(ctx, roles):
        raise ApiError("Only a Super Admin can %s a %s." % (verb, role["row"]["name"]), 403)


def _active_super_admins(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM app_user WHERE role = ? AND is_active = 1",
                        (access.SUPER_ADMIN,)).fetchone()["n"]


# --- people -----------------------------------------------------------------------

def list_users(ctx):
    conn = db.get_conn()
    roles = _roles(conn)
    sessions = _session_counts(conn)
    rows = conn.execute("SELECT * FROM app_user ORDER BY is_active DESC, lower(name)").fetchall()
    users = [_user_json(conn, r, ctx, roles, sessions) for r in rows if _visible(ctx, conn, r)]
    return 200, {"users": users, "limited": ctx.access.level("users.view") == "limited"}


def get_user(ctx):
    conn = db.get_conn()
    row = _get_row(conn, int(ctx.match.group("id")))
    if not _visible(ctx, conn, row):
        raise ApiError("No such user.", 404)
    return 200, _user_json(conn, row, ctx, _roles(conn), _session_counts(conn))


def create_user(ctx):
    conn = db.get_conn()
    data = ctx.json()
    roles = _roles(conn)
    role = (data.get("role") or "").strip().upper()
    _check_role_choice(ctx, roles, role)
    scope = _clean_scope(conn, data.get("scope"))
    password = auth.temporary_password()
    user_id = auth.create_user(conn, data.get("email"), data.get("name"), role, password, must_change=True)
    _save_scope(conn, user_id, scope)
    row = _get_row(conn, user_id)
    access.record(conn, "user.create", row["email"],
                  "%s, as %s. Scope: %s." % (row["name"], roles[role]["row"]["name"], _scope_text(conn, scope)),
                  ctx.user, _ip(ctx), commit=False)
    conn.commit()
    return 201, {"user": _user_json(conn, row, ctx, roles, {}), "temporaryPassword": password}


def update_user(ctx):
    conn = db.get_conn()
    data = ctx.json()
    roles = _roles(conn)
    row = _get_row(conn, int(ctx.match.group("id")))
    you = row["id"] == ctx.user["id"]
    changes = []

    wants_active = data.get("isActive")
    edits = {k for k in ("name", "email", "role", "scope") if k in data}
    if edits:
        ctx.access.require("users.edit")
        _check_may_touch(ctx, roles, row)
    if wants_active is not None and bool(wants_active) != bool(row["is_active"]):
        ctx.access.require("users.deactivate")
        _check_may_touch(ctx, roles, row, "switch off" if not wants_active else "switch on")
        if you:
            raise ApiError("You cannot switch off your own account.", 400)
        if not wants_active and row["role"] == access.SUPER_ADMIN and _active_super_admins(conn) <= 1:
            raise ApiError("This is the only active Super Admin. Give someone else the role first.", 400)

    name, email, role = row["name"], row["email"], row["role"]
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ApiError("Enter the person's name.", field="name")
        if name != row["name"]:
            changes.append("Name: %s → %s" % (row["name"], name))
    if "email" in data:
        email = (data.get("email") or "").strip().lower()
        if not auth.EMAIL_RE.match(email):
            raise ApiError("Enter a valid email address.", field="email")
        if email != row["email"]:
            if conn.execute("SELECT 1 FROM app_user WHERE email = ? AND id <> ?", (email, row["id"])).fetchone():
                raise ApiError("There is already an account for %s." % email, 409, "email")
            changes.append("Email: %s → %s" % (row["email"], email))
    if "role" in data:
        role = (data.get("role") or "").strip().upper()
        if role != row["role"]:
            if you:
                raise ApiError("You cannot change your own role. Ask another administrator.", 400, "role")
            _check_role_choice(ctx, roles, role)
            if row["role"] == access.SUPER_ADMIN and row["is_active"] and _active_super_admins(conn) <= 1:
                raise ApiError("This is the only active Super Admin. Give someone else the role first.",
                               400, "role")
            changes.append("Role: %s → %s" % (roles[row["role"]]["row"]["name"] if row["role"] in roles
                                               else row["role"], roles[role]["row"]["name"]))
    scope = None
    if "scope" in data:
        scope = _clean_scope(conn, data.get("scope"))
        before = access.user_scope(conn, row["id"])
        if scope != before:
            changes.append("Scope: %s → %s" % (_scope_text(conn, before), _scope_text(conn, scope)))

    conn.execute("UPDATE app_user SET name = ?, email = ?, role = ?, updated_at = ? WHERE id = ?",
                 (name, email, role, _now(), row["id"]))
    if scope is not None:
        _save_scope(conn, row["id"], scope)
    if wants_active is not None and bool(wants_active) != bool(row["is_active"]):
        conn.execute("UPDATE app_user SET is_active = ? WHERE id = ?", (1 if wants_active else 0, row["id"]))
        if not wants_active:
            conn.execute("DELETE FROM app_session WHERE user_id = ?", (row["id"],))
        access.record(conn, "user.activate" if wants_active else "user.deactivate", email,
                      "Switched on: can sign in again" if wants_active
                      else "Switched off and signed out everywhere", ctx.user, _ip(ctx), commit=False)
    if changes:
        access.record(conn, "user.update", email, "; ".join(changes), ctx.user, _ip(ctx), commit=False)
    conn.commit()
    return 200, _user_json(conn, _get_row(conn, row["id"]), ctx, roles, _session_counts(conn))


def reset_password(ctx):
    conn = db.get_conn()
    roles = _roles(conn)
    row = _get_row(conn, int(ctx.match.group("id")))
    _check_may_touch(ctx, roles, row, "reset the password of")
    if row["id"] == ctx.user["id"]:
        raise ApiError("Change your own password from your account menu instead.", 400)
    password = auth.temporary_password()
    auth.set_password(conn, row["email"], password, must_change=True)
    access.record(conn, "user.password_reset", row["email"],
                  "Temporary password issued; signed out everywhere", ctx.user, _ip(ctx))
    return 200, {"temporaryPassword": password,
                 "user": _user_json(conn, _get_row(conn, row["id"]), ctx, roles, _session_counts(conn))}


def revoke_sessions(ctx):
    conn = db.get_conn()
    roles = _roles(conn)
    row = _get_row(conn, int(ctx.match.group("id")))
    _check_may_touch(ctx, roles, row, "sign out")
    n = conn.execute("SELECT COUNT(*) AS n FROM app_session WHERE user_id = ?", (row["id"],)).fetchone()["n"]
    conn.execute("DELETE FROM app_session WHERE user_id = ?", (row["id"],))
    access.record(conn, "user.sign_out", row["email"], "Signed out of %d session%s" % (n, "" if n == 1 else "s"),
                  ctx.user, _ip(ctx))
    return 200, _user_json(conn, _get_row(conn, row["id"]), ctx, roles, {})


def unlock_user(ctx):
    conn = db.get_conn()
    roles = _roles(conn)
    row = _get_row(conn, int(ctx.match.group("id")))
    _check_may_touch(ctx, roles, row, "unlock")
    conn.execute("UPDATE app_user SET failed_logins = 0, locked_until = NULL WHERE id = ?", (row["id"],))
    access.record(conn, "user.unlock", row["email"], "Unlocked after wrong passwords", ctx.user, _ip(ctx))
    return 200, _user_json(conn, _get_row(conn, row["id"]), ctx, roles, _session_counts(conn))


def change_own_password(ctx):
    conn = db.get_conn()
    data = ctx.json()
    auth._throttle(_ip(ctx))
    row = _get_row(conn, ctx.user["id"])
    if not auth.verify_password(data.get("current") or "", row["password_hash"]):
        auth.failed_attempt(_ip(ctx))
        raise ApiError("Your current password is not right.", 400, "current")
    new = data.get("password") or ""
    if new != (data.get("confirm") or ""):
        raise ApiError("The two new passwords do not match.", field="confirm")
    if new == (data.get("current") or ""):
        raise ApiError("Choose a password different from the current one.", field="password")
    auth.set_password(conn, row["email"], new, keep_session=auth.token_from(ctx.handler))
    access.record(conn, "auth.password_change", row["email"], "Changed own password; other sessions signed out",
                  ctx.user, _ip(ctx))
    return 200, {"ok": True}


def my_access(ctx):
    """What the signed-in person may do: their role, their scope, and every
    action with its level. Anyone signed in may see their own."""
    conn = db.get_conn()
    acc = ctx.access
    role = conn.execute("SELECT * FROM app_role WHERE code = ?", (ctx.user["role"],)).fetchone()
    modules = [dict(m, actions=[dict(a, level=acc.level(a["key"])) for a in m["actions"]])
               for m in access.MODULES]
    return 200, {
        "role": {"code": ctx.user["role"], "name": role["name"] if role else ctx.user["role"],
                 "description": (role["description"] if role else "") or ""},
        "usesScope": any(level == "limited" for level in acc.levels.values()),
        "scope": {"types": _names(conn, "sbu", "name", acc.types),
                  "companies": _names(conn, "legal_entity", "short_code", acc.companies)},
        "modules": modules,
    }


# --- roles ------------------------------------------------------------------------

def _role_json(conn, code, role, counts, ctx):
    row = role["row"]
    return {"code": code, "name": row["name"], "description": row["description"] or "",
            "isSystem": bool(row["is_system"]), "locked": code == access.SUPER_ADMIN,
            "protected": role["protected"], "users": counts.get(code, 0),
            "permissions": role["levels"]}


def list_roles(ctx):
    conn = db.get_conn()
    counts = {r["role"]: r["n"] for r in conn.execute(
        "SELECT role, COUNT(*) AS n FROM app_user WHERE is_active = 1 GROUP BY role")}
    roles = _roles(conn)
    return 200, {"modules": access.MODULES, "levels": list(access.LEVELS),
                 "roles": [_role_json(conn, code, role, counts, ctx) for code, role in roles.items()],
                 "canManage": ctx.access.can("roles.manage"),
                 "assignable": [code for code, role in roles.items()
                                if not role["protected"] or _acting_is_protected(ctx, roles)]}


def create_role(ctx):
    conn = db.get_conn()
    data = ctx.json()
    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError("Name the role.", field="name")
    code = access.role_code_for(name)
    if not code:
        raise ApiError("Use letters or numbers in the role's name.", field="name")
    if conn.execute("SELECT 1 FROM app_role WHERE code = ? OR lower(name) = lower(?)", (code, name)).fetchone():
        raise ApiError("There is already a role called %s." % name, 409, "name")
    source = (data.get("copyFrom") or "").upper()
    levels = access.role_levels(conn, source) if source else {k: "no" for k in access.ALL_KEYS}
    stamp = _now()
    conn.execute("""INSERT INTO app_role (code, name, description, is_system, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, 0, 100, ?, ?)""",
                 (code, name, (data.get("description") or "").strip(), stamp, stamp))
    for key, level in levels.items():
        if level != "no":
            conn.execute("INSERT INTO app_role_permission (role_code, permission, level) VALUES (?, ?, ?)",
                         (code, key, level))
    access.record(conn, "role.create", name,
                  "New role" + (", starting from %s" % auth.role_name(conn, source) if source else ""),
                  ctx.user, _ip(ctx), commit=False)
    conn.commit()
    roles = _roles(conn)
    return 201, _role_json(conn, code, roles[code], {}, ctx)


def update_role(ctx):
    conn = db.get_conn()
    data = ctx.json()
    code = ctx.match.group("code").upper()
    row = conn.execute("SELECT * FROM app_role WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ApiError("No such role.", 404)
    if code == access.SUPER_ADMIN:
        raise ApiError("Super Admin always has full access and cannot be changed.", 400)
    changes = []
    name = (data.get("name") if "name" in data else row["name"]) or ""
    name = name.strip()
    if not name:
        raise ApiError("Name the role.", field="name")
    if name != row["name"]:
        if conn.execute("SELECT 1 FROM app_role WHERE lower(name) = lower(?) AND code <> ?",
                        (name, code)).fetchone():
            raise ApiError("There is already a role called %s." % name, 409, "name")
        changes.append("Name: %s → %s" % (row["name"], name))
    description = (data.get("description") if "description" in data else row["description"]) or ""
    if description.strip() != (row["description"] or ""):
        changes.append("Description changed")
    if "permissions" in data:
        before = access.role_levels(conn, code)
        wanted = data.get("permissions") or {}
        unknown = [k for k in wanted if k not in access.ACTIONS]
        if unknown:
            raise ApiError("Unknown permission: %s." % ", ".join(unknown))
        after = dict(before)
        for key, level in wanted.items():
            after[key] = access.clean_level(key, level)
        # Keeping "Manage roles" on a role makes it protected; only Super Admins may do so.
        for key in access.ALL_KEYS:
            if after[key] != before[key]:
                changes.append("%s: %s → %s" % (access._label(key), before[key], after[key]))
        conn.execute("DELETE FROM app_role_permission WHERE role_code = ?", (code,))
        for key, level in after.items():
            if level != "no":
                conn.execute("INSERT INTO app_role_permission (role_code, permission, level) VALUES (?, ?, ?)",
                             (code, key, level))
    conn.execute("UPDATE app_role SET name = ?, description = ?, updated_at = ? WHERE code = ?",
                 (name, description.strip(), _now(), code))
    if changes:
        access.record(conn, "role.update", name, "; ".join(changes), ctx.user, _ip(ctx), commit=False)
    conn.commit()
    counts = {r["role"]: r["n"] for r in conn.execute(
        "SELECT role, COUNT(*) AS n FROM app_user WHERE is_active = 1 GROUP BY role")}
    return 200, _role_json(conn, code, _roles(conn)[code], counts, ctx)


def delete_role(ctx):
    conn = db.get_conn()
    code = ctx.match.group("code").upper()
    row = conn.execute("SELECT * FROM app_role WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ApiError("No such role.", 404)
    if row["is_system"]:
        raise ApiError("The %s role comes with the register and cannot be deleted." % row["name"], 400)
    n = conn.execute("SELECT COUNT(*) AS n FROM app_user WHERE role = ?", (code,)).fetchone()["n"]
    if n:
        raise ApiError("%d %s this role. Give them another role first."
                       % (n, "person has" if n == 1 else "people have"), 409)
    conn.execute("DELETE FROM app_role_permission WHERE role_code = ?", (code,))
    conn.execute("DELETE FROM app_role WHERE code = ?", (code,))
    access.record(conn, "role.delete", row["name"], "Role deleted", ctx.user, _ip(ctx), commit=False)
    conn.commit()
    return 200, {"deleted": code}


# --- the audit log ----------------------------------------------------------------

AUDIT_CATEGORIES = ["auth", "user", "role", "property", "document", "bulk", "type", "company", "master"]


def list_audit(ctx):
    conn = db.get_conn()
    q = ctx.query
    where, params = [], []
    if q.get("category") in AUDIT_CATEGORIES:
        where.append("action LIKE ?")
        params.append(q["category"] + ".%")
    if (q.get("user_id") or "").isdigit():
        where.append("user_id = ?")
        params.append(int(q["user_id"]))
    if q.get("q"):
        term = "%" + q["q"].strip().lower() + "%"
        where.append("(lower(target) LIKE ? OR lower(detail) LIKE ? OR lower(user_name) LIKE ? "
                     "OR lower(user_email) LIKE ?)")
        params.extend([term] * 4)
    if (q.get("days") or "").isdigit():
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(q["days"]))
        where.append("at >= ?")
        params.append(since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if (q.get("before") or "").isdigit():
        where.append("id < ?")
        params.append(int(q["before"]))
    limit = min(int(q["limit"]) if (q.get("limit") or "").isdigit() else 50, 200)
    sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "") + \
        " ORDER BY id DESC LIMIT %d" % (limit + 1)
    rows = conn.execute(sql, params).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    people = conn.execute("""SELECT DISTINCT user_id, user_name FROM audit_log
                             WHERE user_id IS NOT NULL ORDER BY user_name""").fetchall()
    return 200, {
        "entries": [{"id": r["id"], "at": r["at"], "userId": r["user_id"], "userName": r["user_name"],
                     "userEmail": r["user_email"], "action": r["action"], "target": r["target"],
                     "detail": r["detail"], "ip": r["ip"]} for r in rows],
        "nextBefore": rows[-1]["id"] if more and rows else None,
        "people": [{"id": p["user_id"], "name": p["user_name"]} for p in people],
        "categories": AUDIT_CATEGORIES,
    }


ROUTES = [
    ("POST", r"^/api/account/password$", change_own_password),
    ("GET", r"^/api/account/access$", my_access),
    ("GET", r"^/api/users$", list_users),
    ("POST", r"^/api/users$", create_user),
    ("GET", r"^/api/users/(?P<id>\d+)$", get_user),
    ("PUT", r"^/api/users/(?P<id>\d+)$", update_user),
    ("POST", r"^/api/users/(?P<id>\d+)/reset-password$", reset_password),
    ("POST", r"^/api/users/(?P<id>\d+)/sign-out$", revoke_sessions),
    ("POST", r"^/api/users/(?P<id>\d+)/unlock$", unlock_user),
    ("GET", r"^/api/roles$", list_roles),
    ("POST", r"^/api/roles$", create_role),
    ("PUT", r"^/api/roles/(?P<code>[A-Za-z0-9_]+)$", update_role),
    ("DELETE", r"^/api/roles/(?P<code>[A-Za-z0-9_]+)$", delete_role),
    ("GET", r"^/api/audit$", list_audit),
]
