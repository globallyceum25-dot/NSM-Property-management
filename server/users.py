"""Manage sign-in accounts from the command line.

    python3 -m server.users list
    python3 -m server.users add --email a.perera@company.lk --name "A. Perera" --role PROPERTY_MANAGER
    python3 -m server.users reset-password --email a.perera@company.lk
    python3 -m server.users disable --email a.perera@company.lk
    python3 -m server.users enable  --email a.perera@company.lk

Passwords are typed at a hidden prompt, never on the command line, so they do
not end up in the shell history. Roles: see `list-roles`.
"""

import argparse
import getpass
import sys

from . import auth, db
from .errors import ApiError


def _ask_password():
    while True:
        first = getpass.getpass("Password (at least %d characters): " % auth.MIN_PASSWORD_LENGTH)
        if getpass.getpass("Type it again: ") == first:
            return first
        print("The two passwords do not match. Try again.")


def _set_active(conn, email, active):
    email = email.strip().lower()
    row = conn.execute("SELECT id FROM app_user WHERE email = ?", (email,)).fetchone()
    if row is None:
        raise ApiError("No account for %s." % email)
    conn.execute("UPDATE app_user SET is_active = ? WHERE id = ?", (1 if active else 0, row["id"]))
    if not active:
        conn.execute("DELETE FROM app_session WHERE user_id = ?", (row["id"],))
    conn.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the register's sign-in accounts")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list accounts")
    sub.add_parser("list-roles", help="list the roles an account can have")
    add = sub.add_parser("add", help="add an account")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True, choices=[code for code, _ in auth.ROLES])
    for name in ("reset-password", "disable", "enable"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    db.init_db()
    conn = db.get_conn()
    try:
        if args.command == "list":
            rows = conn.execute("SELECT email, name, role, is_active, last_login_at FROM app_user "
                                "ORDER BY name").fetchall()
            if not rows:
                print("No accounts yet.")
            for r in rows:
                print("%-34s %-26s %-20s %-8s last sign-in: %s" % (
                    r["email"], r["name"], auth.ROLE_LABELS.get(r["role"], r["role"]),
                    "active" if r["is_active"] else "OFF", r["last_login_at"] or "never"))
        elif args.command == "list-roles":
            for code, label in auth.ROLES:
                print("%-20s %s" % (code, label))
        elif args.command == "add":
            auth.create_user(conn, args.email, args.name, args.role, _ask_password())
            print("Added %s as %s." % (args.email.lower(), auth.ROLE_LABELS[args.role]))
        elif args.command == "reset-password":
            auth.set_password(conn, args.email, _ask_password())
            print("Password changed; %s is signed out everywhere." % args.email.lower())
        else:
            _set_active(conn, args.email, args.command == "enable")
            print("%s %s." % (args.email.lower(), "can sign in again" if args.command == "enable"
                              else "can no longer sign in"))
    except ApiError as exc:
        print("Error: %s" % exc.message, file=sys.stderr)
        return 1
    finally:
        db.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
