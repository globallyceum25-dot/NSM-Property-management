"""Where uploaded document files live.

On disk under data/uploads by default. With SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY set, in a private Supabase Storage bucket instead
(SUPABASE_STORAGE_BUCKET, "documents" unless set). Either way a file is only
ever read back through the register's own download endpoint.
"""

import json
import os
import shutil
import urllib.error
import urllib.request
from urllib.parse import quote

from . import db
from .errors import ApiError

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET") or "documents"
IN_SUPABASE = bool(SUPABASE_URL and SERVICE_KEY)


def describe():
    """Where uploads go, for the startup banner."""
    if IN_SUPABASE:
        return "Supabase Storage, bucket '%s'" % BUCKET
    return db.UPLOAD_DIR


def _request(method, path, body=None, content_type=None, extra_headers=None):
    headers = {"apikey": SERVICE_KEY, "Authorization": "Bearer " + SERVICE_KEY}
    if content_type:
        headers["Content-Type"] = content_type
    headers.update(extra_headers or {})
    request = urllib.request.Request(SUPABASE_URL + "/storage/v1/" + path,
                                     data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json(payload):
    return json.dumps(payload).encode("utf-8")


def _object(stored_name):
    return "object/%s/%s" % (quote(BUCKET), quote(os.path.basename(stored_name)))


def _path(stored_name):
    return os.path.join(db.UPLOAD_DIR, os.path.basename(stored_name))


def init():
    """Make sure uploads have somewhere to go: the folder, or the bucket."""
    if not IN_SUPABASE:
        os.makedirs(db.UPLOAD_DIR, exist_ok=True)
        return
    status, _ = _request("GET", "bucket/" + quote(BUCKET))
    if status == 200:
        return
    status, body = _request("POST", "bucket",
                            _json({"id": BUCKET, "name": BUCKET, "public": False}),
                            "application/json")
    if status not in (200, 201):
        raise SystemExit("Could not create the Supabase Storage bucket '%s' (%d): %s"
                         % (BUCKET, status, body[:300].decode("utf-8", "replace")))


def save(stored_name, data, content_type=None):
    if not IN_SUPABASE:
        with open(_path(stored_name), "wb") as fh:
            fh.write(data)
        return
    # Upsert, so copying the same files again (server.import_sqlite) is harmless.
    status, _ = _request("POST", _object(stored_name), data,
                         content_type or "application/octet-stream", {"x-upsert": "true"})
    if status not in (200, 201):
        raise ApiError("The file could not be saved to storage (error %d). "
                       "Nothing was recorded; please try again." % status, 502, "file")


def load(stored_name):
    """The file's bytes, or None if it is missing."""
    if not IN_SUPABASE:
        if not os.path.exists(_path(stored_name)):
            return None
        with open(_path(stored_name), "rb") as fh:
            return fh.read()
    status, body = _request("GET", _object(stored_name))
    if status == 200:
        return body
    # Storage reports a missing object as 404, or as 400 with "not_found".
    if status == 404 or (status == 400 and b"not_found" in body):
        return None
    raise ApiError("The file could not be read from storage (error %d)." % status, 502)


def remove(stored_name):
    """Best effort, as before: a file that is already gone is not an error."""
    if not stored_name:
        return
    if not IN_SUPABASE:
        try:
            os.remove(_path(stored_name))
        except OSError:
            pass
        return
    _request("DELETE", _object(stored_name))


def clear():
    """Delete every stored file (server.reset)."""
    if not IN_SUPABASE:
        if os.path.isdir(db.UPLOAD_DIR):
            shutil.rmtree(db.UPLOAD_DIR)
        os.makedirs(db.UPLOAD_DIR, exist_ok=True)
        return
    while True:
        status, body = _request("POST", "object/list/" + quote(BUCKET),
                                _json({"prefix": "", "limit": 1000}), "application/json")
        if status != 200:
            raise SystemExit("Could not list the storage bucket (%d)." % status)
        names = [item["name"] for item in json.loads(body.decode("utf-8")) if item.get("id")]
        if not names:
            return
        status, _ = _request("DELETE", "object/" + quote(BUCKET),
                             _json({"prefixes": names}), "application/json")
        if status != 200:
            raise SystemExit("Could not empty the storage bucket (%d)." % status)
