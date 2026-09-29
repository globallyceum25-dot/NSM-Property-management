"""Zero-dependency HTTP server: JSON API + static front end.

Run with:  python3 -m server.app  [--port 8000] [--host 127.0.0.1]
"""

import argparse
import json
import mimetypes
import os
import posixpath
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

from . import api, db, multipart

WEB_DIR = os.path.join(db.BASE_DIR, "web")
MAX_BODY_BYTES = api.MAX_UPLOAD_BYTES + (2 * 1024 * 1024)


class Context(object):
    """Everything a handler needs from the request."""

    def __init__(self, handler, match, query, body):
        self.handler = handler
        self.match = match
        self.query = query
        self.body = body
        self._json = None
        self._form = None

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
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _send_raw(self, status, payload):
        filename = payload.get("filename") or "download"
        disposition = "inline" if payload.get("inline") else "attachment"
        header = '%s; filename="%s"; filename*=UTF-8\'\'%s' % (
            disposition,
            filename.replace('"', "").encode("ascii", "ignore").decode("ascii") or "download",
            quote(filename),
        )
        self._send(status, payload["body"], payload["content_type"],
                   {"Content-Disposition": header, "Cache-Control": "no-store"})

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
            matched_path = False
            for route_method, pattern, handler in api.COMPILED_ROUTES:
                match = pattern.match(path)
                if not match:
                    continue
                matched_path = True
                if route_method != method:
                    continue
                body = self._read_body() if method in ("POST", "PUT", "PATCH") else b""
                status, payload = handler(Context(self, match, query, body))
                if isinstance(payload, dict) and payload.get("__raw__"):
                    self._send_raw(status, payload)
                else:
                    self._send_json(status, payload)
                return
            self._send_json(405 if matched_path else 404,
                            {"error": "Method not allowed for this endpoint."
                                      if matched_path else "Unknown API endpoint."})
            return

        self._serve_static(path)

    def _serve_static(self, path):
        if path in ("/", "/index.html", "/."):
            path = "/index.html"
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

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch


def main():
    parser = argparse.ArgumentParser(description="Property register server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    db.init_db()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print("Property register running at http://%s:%d/" % (args.host, args.port))
    print("Database: %s" % db.DB_PATH)
    print("Uploads:  %s" % db.UPLOAD_DIR)
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
