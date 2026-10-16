"""Postgres only (TEST_DATABASE_URL set): the same answers as SQLite, and the
SQLite-to-Postgres import."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from server import db

from . import TEST_DATABASE_URL
from .support import RegisterTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, **env):
    full_env = dict(os.environ, **env)
    return subprocess.run([sys.executable] + args, cwd=ROOT, env=full_env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


def _canonical(value):
    """Timestamps differ by when each database was seeded; float sums differ in
    the last bits (Postgres adds more precisely). Neither is a real difference."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()
                if k not in ("created_at", "updated_at")}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


@unittest.skipUnless(db.IS_POSTGRES, "set TEST_DATABASE_URL to run the Postgres tests")
class SameAnswersAsSqliteTest(unittest.TestCase):

    def test_every_read_endpoint_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = {}
            for name, url in (("sqlite", ""), ("postgres", TEST_DATABASE_URL)):
                out = os.path.join(tmp, name + ".json")
                result = _run(["-m", "tests.snapshot", out], TEST_DATABASE_URL=url)
                self.assertEqual(result.returncode, 0, result.stdout)
                with open(out, encoding="utf-8") as fh:
                    answers[name] = json.load(fh)
        self.assertNotIn("Postgres", answers["sqlite"]["backend"])
        self.assertIn("Postgres", answers["postgres"]["backend"])
        sqlite, postgres = answers["sqlite"]["answers"], answers["postgres"]["answers"]
        self.assertEqual(sorted(sqlite), sorted(postgres))
        for key in sqlite:
            self.assertEqual(sqlite[key][0], 200, key)
            self.assertEqual(_canonical(sqlite[key]), _canonical(postgres[key]), key)


@unittest.skipUnless(db.IS_POSTGRES, "set TEST_DATABASE_URL to run the Postgres tests")
class ImportSqliteTest(RegisterTestCase):

    def make_sqlite_register(self, folder):
        """The sample register as a SQLite file, plus one extra row and a file."""
        path = os.path.join(folder, "properties.db")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        # The columns a SQLite register gains from db.migrate(), which in this
        # process would ask Postgres instead.
        for table, column, decl in db.MIGRATIONS:
            if column not in {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
        conn.executescript(db.INDEXES)
        db.seed(conn)
        conn.execute("""INSERT INTO document (property_id, doc_type, title, issue_date,
                                              stored_name, mime_type, file_name)
                        VALUES (5, 'DEED', 'Scanned deed', '', 'scan.pdf', 'application/pdf',
                                'scan.pdf')""")
        conn.commit()
        conn.close()
        os.makedirs(os.path.join(folder, "uploads"))
        with open(os.path.join(folder, "uploads", "scan.pdf"), "wb") as fh:
            fh.write(b"%PDF scan")
        return path

    def importer(self, *args):
        return _run(["-m", "server.import_sqlite"] + list(args),
                    DATABASE_URL=TEST_DATABASE_URL, SUPABASE_URL="",
                    SUPABASE_SERVICE_ROLE_KEY="")

    def test_copies_rows_with_their_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.make_sqlite_register(folder)
            refused = self.importer(source)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("Nothing was copied", refused.stdout)

            result = self.importer(source, "--replace")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("document       10", result.stdout)
            self.assertIn("Files stay in", result.stdout)

            conn = sqlite3.connect(source)
            conn.row_factory = sqlite3.Row
            expected = {t: [dict(r) for r in conn.execute("SELECT id, * FROM %s ORDER BY id" % t)]
                        for t in db.TABLES}
            conn.close()

        pg = db.get_conn()
        for table in db.TABLES:
            rows = pg.execute("SELECT id, * FROM %s ORDER BY id" % table).fetchall()
            self.assertEqual([r["id"] for r in rows], [r["id"] for r in expected[table]], table)
        scanned = pg.execute("SELECT * FROM document WHERE title = 'Scanned deed'").fetchone()
        self.assertIsNone(scanned["issue_date"])      # '' is not a date in Postgres
        db.release()

        # New rows carry on numbering after the copied ids.
        made = self.ok("POST", "/api/legal-entities", 201,
                       data={"short_code": "NEW", "name": "New Co"})
        self.assertEqual(made["id"], len(expected["legal_entity"]) + 1)
