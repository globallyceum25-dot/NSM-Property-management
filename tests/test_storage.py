"""Uploaded files, on disk and in Supabase Storage.

The Supabase side runs against a small stand-in for the Storage API that
answers the way the real one does (a missing object is a 400 saying
"not_found", both auth headers are required, upsert must be asked for), so
CI covers that code without credentials.
"""

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import unquote

from server import db, storage
from server.errors import ApiError

KEY = "service-role-key-for-tests"


class FakeStorage(BaseHTTPRequestHandler):
    buckets = set()
    objects = {}     # (bucket, name) -> (bytes, content type)
    fail_uploads = False

    def log_message(self, fmt, *args):
        pass

    def _reply(self, status, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _route(self):
        if self.headers.get("apikey") != KEY or self.headers.get("Authorization") != "Bearer " + KEY:
            return self._reply(400, {"statusCode": "403", "error": "Unauthorized"})
        parts = [unquote(p) for p in self.path.split("?")[0].split("/")[3:]]   # after /storage/v1/
        method = self.command
        if parts[0] == "bucket":
            if method == "GET":
                found = parts[1] in self.buckets
                return self._reply(200 if found else 400, {"name": parts[1]} if found else
                                   {"statusCode": "404", "error": "Bucket not found"})
            self.buckets.add(json.loads(self._body())["id"])
            return self._reply(200, {"name": "ok"})
        if parts[:2] == ["object", "list"]:
            limit = json.loads(self._body())["limit"]
            names = sorted(name for bucket, name in self.objects if bucket == parts[2])[:limit]
            return self._reply(200, [{"name": n, "id": n} for n in names])
        bucket, name = parts[1], "/".join(parts[2:])
        if parts[1] not in self.buckets:
            return self._reply(400, {"statusCode": "404", "error": "Bucket not found"})
        if method == "POST":
            if self.fail_uploads:
                return self._reply(500, {"error": "boom"})
            if (bucket, name) in self.objects and self.headers.get("x-upsert") != "true":
                return self._reply(400, {"statusCode": "409", "error": "Duplicate"})
            self.objects[(bucket, name)] = (self._body(), self.headers.get("Content-Type"))
            return self._reply(200, {"Key": bucket + "/" + name})
        if method == "GET":
            if (bucket, name) not in self.objects:
                return self._reply(400, {"statusCode": "404", "error": "not_found"})
            return self._reply(200, self.objects[(bucket, name)][0])
        if method == "DELETE" and name:
            self.objects.pop((bucket, name), None)
            return self._reply(200, {"message": "Successfully deleted"})
        for prefix in json.loads(self._body())["prefixes"]:      # DELETE object/<bucket>
            self.objects.pop((bucket, prefix), None)
        return self._reply(200, [])

    do_GET = do_POST = do_DELETE = _route


class SupabaseStorageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeStorage)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.patches = [mock.patch.object(storage, name, value) for name, value in (
            ("SUPABASE_URL", url), ("SERVICE_KEY", KEY), ("IN_SUPABASE", True),
            ("BUCKET", "documents"))]
        for patch in cls.patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in cls.patches:
            patch.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        FakeStorage.buckets.clear()
        FakeStorage.objects.clear()
        FakeStorage.fail_uploads = False
        storage.init()

    def test_init_creates_the_bucket_once(self):
        self.assertEqual(FakeStorage.buckets, {"documents"})
        storage.init()
        self.assertEqual(FakeStorage.buckets, {"documents"})
        self.assertEqual(storage.describe(), "Supabase Storage, bucket 'documents'")

    def test_save_load_remove(self):
        storage.save("abc.pdf", b"%PDF one", "application/pdf")
        self.assertEqual(FakeStorage.objects[("documents", "abc.pdf")],
                         (b"%PDF one", "application/pdf"))
        self.assertEqual(storage.load("abc.pdf"), b"%PDF one")
        storage.save("abc.pdf", b"%PDF two")          # upsert: copying again is harmless
        self.assertEqual(storage.load("abc.pdf"), b"%PDF two")
        storage.remove("abc.pdf")
        self.assertIsNone(storage.load("abc.pdf"))
        storage.remove("abc.pdf")                      # already gone: not an error
        storage.remove(None)

    def test_names_cannot_escape_the_bucket(self):
        storage.save("../../other/evil.pdf", b"x")
        self.assertEqual(list(FakeStorage.objects), [("documents", "evil.pdf")])

    def test_failed_upload_is_a_502(self):
        FakeStorage.fail_uploads = True
        with self.assertRaises(ApiError) as caught:
            storage.save("abc.pdf", b"x")
        self.assertEqual((caught.exception.status, caught.exception.field), (502, "file"))

    def test_clear_empties_the_bucket_in_batches(self):
        for i in range(2500):
            FakeStorage.objects[("documents", "f%04d.pdf" % i)] = (b"", None)
        storage.clear()
        self.assertEqual(FakeStorage.objects, {})


class LocalStorageTests(unittest.TestCase):

    def setUp(self):
        storage.init()

    def test_save_load_remove_clear(self):
        self.assertFalse(storage.IN_SUPABASE)
        self.assertEqual(storage.describe(), db.UPLOAD_DIR)
        storage.save("../evil.txt", b"hello")
        self.assertTrue(os.path.isfile(os.path.join(db.UPLOAD_DIR, "evil.txt")))
        self.assertEqual(storage.load("evil.txt"), b"hello")
        storage.remove("evil.txt")
        self.assertIsNone(storage.load("evil.txt"))
        storage.save("keep.txt", b"x")
        storage.clear()
        self.assertEqual(os.listdir(db.UPLOAD_DIR), [])
