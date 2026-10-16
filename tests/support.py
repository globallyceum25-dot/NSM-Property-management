"""Shared plumbing: a live register on a free port, a small HTTP client, and
the sample data reloaded before every test."""

import contextlib
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

from server import app, db, reset, storage

_httpd = None


class _QuietHandler(app.Handler):
    """No access log; a failing request still prints its traceback."""

    def log_message(self, fmt, *args):
        pass


def start_server():
    """The register serving from a background thread, once per test run."""
    global _httpd
    if _httpd is None:
        db.init_db()
        storage.init()
        _httpd = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
        _httpd.daemon_threads = True
        threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % _httpd.server_address[1]


def load_sample_data():
    """Empty the register and reload the sample set, ids starting from 1."""
    with contextlib.redirect_stdout(io.StringIO()):
        reset.wipe(reload_sample=True)
    db.release()


class Response(object):
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def _multipart(boundary, fields, files):
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, name, value)).encode("utf-8"))
    for name, (filename, data, content_type) in files.items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                   "Content-Type: %s\r\n\r\n" % (boundary, name, filename, content_type))
                  .encode("utf-8"))
        out.write(data + b"\r\n")
    out.write(("--%s--\r\n" % boundary).encode("ascii"))
    return out.getvalue()


class RegisterTestCase(unittest.TestCase):
    """Each test starts from the 13 sample properties."""

    @classmethod
    def setUpClass(cls):
        cls.base = start_server()

    def setUp(self):
        load_sample_data()

    def request(self, method, path, data=None, files=None, query=None, raw=None):
        """`data` goes as JSON, or as form fields when `files` is given
        ({field: (filename, bytes, content type)}, possibly empty)."""
        headers, body = {}, raw
        if files is not None:
            boundary = uuid.uuid4().hex
            body = _multipart(boundary, data or {}, files)
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        url = self.base + path + ("?" + urlencode(query) if query else "")
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return Response(response.status, response.headers, response.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.headers, exc.read())

    def ok(self, method, path, expected=200, **kwargs):
        """The response's JSON, after checking its status."""
        response = self.request(method, path, **kwargs)
        self.assertEqual(response.status, expected,
                         "%s %s -> %d: %s" % (method, path, response.status, response.body[:300]))
        return response.json()

    def get(self, path, **query):
        return self.ok("GET", path, query=query or None)
