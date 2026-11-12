"""Zero-dependency HTTP server: JSON API + static front end.

Run with:  python3 -m server.app  [--port 8000] [--host 127.0.0.1]

Postgres (DATABASE_URL) and Supabase Storage are optional; see db and storage.
"""

import argparse
import errno
import json
import mimetypes
import os
import posixpath
import sys
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

from . import access, api, auth, db, multipart, storage

WEB_DIR = os.path.join(db.BASE_DIR, "web")
MAX_BODY_BYTES = api.MAX_UPLOAD_BYTES + (2 * 1024 * 1024)


# What a person signed in with a temporary password may still do.
_BEFORE_NEW_PASSWORD = {"auth.get_status", "auth.logout", "auth.login", "admin.change_own_password",
                        "api.get_reference"}


class Context(object):
    """Everything a handler needs from the request."""

    def __init__(self, handler, match, query, body):
        self.handler = handler
        self.match = match
        self.query = query
        self.body = body
        self._json = None
        self._form = None
        self.user = None            # the signed-in user, set before the handler runs
        self.access = None          # what they may do (server/access.py)
        self.headers_out = []       # extra response headers, such as Set-Cookie
        self.audit_target = None    # what a change is logged as, when a handler says
        self.audit_detail = None

    def add_header(self, name, value):
        self.headers_out.append((name, value))

    def json(self):
        if self._json is None:
            if not self.body:
                self._json = {}
            else:
                try:
                    self._json = json.loads(self.body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise api.ApiError("Request body is not valid JSON.")
            if not isinstance(self._json, dict):
                raise api.ApiError("Request body must be a JSON object.")
        return self._json

    def form(self):
        """Parse multipart/form-data -> (text fields dict, first file Part or None)."""
        if self._form is None:
            content_type = self.handler.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type.lower():
                raise api.ApiError("Expected a multipart/form-data upload.")
            try:
                parts = multipart.parse(self.body, content_type)
            except ValueError as exc:
                raise api.ApiError("Malformed upload: %s" % exc)
            fields, upload = {}, None
            for name, part in parts.items():
                if part.is_file:
                    if upload is None:
                        upload = part
                else:
                    fields[name] = part.text
            self._form = (fields, upload)
        return self._form


class Handler(BaseHTTPRequestHandler):
    server_version = "PropertyRegister/1.0"
    protocol_version = "HTTP/1.1"

    # --- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):
        sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        items = extra_headers.items() if isinstance(extra_headers, dict) else (extra_headers or [])
        for key, value in items:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status, payload, extra=()):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8",
                   [("Cache-Control", "no-store")] + list(extra))

    def _send_raw(self, status, payload, extra=()):
        filename = payload.get("filename") or "download"
        disposition = "inline" if payload.get("inline") else "attachment"
        header = '%s; filename="%s"; filename*=UTF-8\'\'%s' % (
            disposition,
            filename.replace('"', "").encode("ascii", "ignore").decode("ascii") or "download",
            quote(filename),
        )
        self._send(status, payload["body"], payload["content_type"],
                   [("Content-Disposition", header), ("Cache-Control", "no-store")] + list(extra))

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            raise api.ApiError("Request body is too large.", 413)
        return self.rfile.read(length)

    # --- routing ----------------------------------------------------------

    def _handle(self):
        parsed = urlparse(self.path)
        path = posixpath.normpath(parsed.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path.startswith("/api/"):
            method = "GET" if self.command == "HEAD" else self.command
            # A change must come from this register's own pages: a browser sends
            # Origin with every cross-site POST, and it has to match our host.
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                origin = self.headers.get("Origin")
                if origin is not None and urlparse(origin).netloc != (self.headers.get("Host") or ""):
                    self._send_json(403, {"error": "Request refused: it did not come from this register."})
                    return
            # Signed in, or one of the few public endpoints.
            user = auth.user_for_token(db.get_conn(), auth.token_from(self))
            if user is None and (method, path) not in auth.PUBLIC:
                self._send_json(401, {"error": "Please sign in.", "signIn": True})
                return
            matched_path = False
            for route_method, pattern, handler in api.COMPILED_ROUTES:
                match = pattern.match(path)
                if not match:
                    continue
                matched_path = True
                if route_method != method:
                    continue
                body = self._read_body() if method in ("POST", "PUT", "PATCH") else b""
                ctx = Context(self, match, query, body)
                ctx.user = user
                if user is not None:
                    ctx.access = access.load(db.get_conn(), user)
                    # A temporary password must be replaced before anything else.
                    if user["mustChangePassword"] and access.handler_key(handler) not in _BEFORE_NEW_PASSWORD:
                        self._send_json(403, {"error": "Choose a new password first.", "changePassword": True})
                        return
                if (method, path) not in auth.PUBLIC:
                    access.check_route(ctx, handler)
                status, payload = handler(ctx)
                if user is not None and method != "GET":
                    access.audit_request(db.get_conn(), ctx, handler, status, payload)
                if isinstance(payload, dict) and payload.get("__raw__"):
                    self._send_raw(status, payload, ctx.headers_out)
                else:
                    self._send_json(status, payload, ctx.headers_out)
                return
            self._send_json(405 if matched_path else 404,
                            {"error": "Method not allowed for this endpoint."
                                      if matched_path else "Unknown API endpoint."})
            return

        self._serve_static(path)

    def _serve_static(self, path):
        if path in ("/", "/index.html", "/."):
            path = "/index.html"
        elif path in ("/login", "/login/"):
            path = "/login.html"
        relative = path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, relative))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            # Unknown non-API path: fall back to the app shell.
            full = os.path.join(WEB_DIR, "index.html")
            if not os.path.isfile(full):
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
        ctype, _ = mimetypes.guess_type(full)
        if full.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        with open(full, "rb") as fh:
            body = fh.read()
        self._send(200, body, ctype or "application/octet-stream",
                   {"Cache-Control": "no-cache"})

    def _dispatch(self):
        try:
            self._handle()
        except api.ApiError as exc:
            self._send_json(exc.status, {"error": exc.message, "field": exc.field})
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            try:
                self._send_json(500, {"error": "Internal server error."})
            except Exception:
                pass
        finally:
            db.release()

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch


def _register_already_running(host, port):
    """True if the process holding the port is this app, not something else."""
    probe_host = "127.0.0.1" if host in ("", "0.0.0.0") else host
    url = "http://%s:%d/api/reference" % (probe_host, port)
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return "mapCenter" in json.loads(response.read().decode("utf-8"))
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Property register server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Claim the port before touching the database, so a second start neither
    # migrates a live database nor dies with a bare traceback.
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        if _register_already_running(args.host, args.port):
            print("The property register is already running at http://%s:%d/"
                  % (args.host, args.port))
            print("Open that address in your browser. To restart it, stop it first:")
            print("    pkill -f server.app")
            return 0
        print("Port %d is in use by another program." % args.port)
        print("Start the register on a different port instead:")
        print("    PORT=8080 ./run.sh")
        return 1

    db.init_db()
    storage.init()
    httpd.daemon_threads = True
    conn = db.get_conn()
    if auth.bootstrap_from_env(conn):
        print("Created the first Super Admin from REGISTER_ADMIN_EMAIL.")
    code = auth.setup_code(conn)
    db.release()
    print("Property register running at http://%s:%d/" % (args.host, args.port))
    print("Database: %s" % db.describe())
    print("Uploads:  %s" % storage.describe())
    if code:
        print("")
        print("No one can sign in yet. Open http://%s:%d/login to create the first" % (args.host, args.port))
        print("Super Admin, and enter this one-time setup code:  %s" % code)
        print("")
    print("Press Ctrl+C to stop.")
    sys.stdout.flush()   # show the banner even when output goes to a log file
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
