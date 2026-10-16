"""Copy a SQLite register into Postgres, and its uploaded files into storage.

    python3 -m server.import_sqlite             copy data/properties.db (and
                                                the files in data/uploads)
    python3 -m server.import_sqlite OTHER.db    copy another SQLite register
    python3 -m server.import_sqlite --replace   empty the Postgres register and
                                                its stored files first

DATABASE_URL names the Postgres database; with SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY set the files go to Supabase Storage too. Row ids are
kept, so every link between properties, documents and the masters survives.
The SQLite file is only read, never changed.
"""

import argparse
import os
import sqlite3

from . import db, storage
from .errors import ApiError

DATE_COLUMNS = {"acquisition_date", "issue_date", "expiry_date"}


def _value(column, value):
    # An empty date string is valid in SQLite but not in a Postgres DATE column.
    return None if column in DATE_COLUMNS and value == "" else value


def main():
    parser = argparse.ArgumentParser(description="Copy a SQLite register into Postgres")
    parser.add_argument("source", nargs="?", default=db.DB_PATH,
                        help="SQLite file (default: data/properties.db)")
    parser.add_argument("--replace", action="store_true",
                        help="empty the Postgres register and its stored files first")
    args = parser.parse_args()

    if not db.IS_POSTGRES:
        raise SystemExit("Set DATABASE_URL (in .env) to the Postgres database to copy into.")
    if not os.path.isfile(args.source):
        raise SystemExit("No SQLite register at %s." % args.source)
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(args.source)), "uploads")

    source = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(args.source), uri=True)
    source.row_factory = sqlite3.Row
    target = db.get_conn()
    db.create_schema(target)
    target.executescript(db.INDEXES)
    target.commit()
    storage.init()

    existing = sum(target.execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()["n"]
                   for table in db.TABLES)
    if existing and not args.replace:
        raise SystemExit("%s already holds %d rows. Nothing was copied.\n"
                         "Run again with --replace to overwrite them."
                         % (db.describe(), existing))

    raw = target.raw
    raw.execute("SET LOCAL TIME ZONE 'UTC'")   # SQLite's timestamps are UTC
    if args.replace:
        raw.execute("TRUNCATE %s RESTART IDENTITY" % ", ".join(db.TABLES))

    counts = {}
    for table in db.TABLES:
        wanted = db.table_columns(target, table)
        columns = [r["name"] for r in source.execute("PRAGMA table_info(%s)" % table)
                   if r["name"] in wanted]
        if not columns:
            counts[table] = 0
            continue
        rows = [[_value(c, r[c]) for c in columns] for r in source.execute(
            "SELECT %s FROM %s ORDER BY id" % (", ".join(columns), table))]
        with raw.cursor() as cur:
            cur.executemany("INSERT INTO %s (%s) VALUES (%s)"
                            % (table, ", ".join(columns), ", ".join(["%s"] * len(columns))),
                            rows)
        # New rows carry on numbering after the copied ids.
        raw.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "COALESCE(MAX(id), 0) + 1, false) FROM " + table, (table,))
        counts[table] = len(rows)

    files, missing = 0, []
    stored = source.execute("SELECT stored_name, mime_type FROM document "
                            "WHERE stored_name IS NOT NULL").fetchall()
    if storage.IN_SUPABASE:
        if args.replace:
            storage.clear()
        for row in stored:
            path = os.path.join(upload_dir, os.path.basename(row["stored_name"]))
            if not os.path.isfile(path):
                missing.append(row["stored_name"])
                continue
            with open(path, "rb") as fh:
                try:
                    storage.save(row["stored_name"], fh.read(), row["mime_type"])
                except ApiError as exc:
                    raise SystemExit("%s Nothing was committed to the database." % exc.message)
            files += 1

    target.commit()
    db.release()

    print("Copied into %s:" % db.describe())
    for table in db.TABLES:
        print("    %-14s %d" % (table, counts[table]))
    if storage.IN_SUPABASE:
        print("Files uploaded to %s: %d" % (storage.describe(), files))
        for name in missing:
            print("    missing from %s: %s" % (upload_dir, name))
    elif stored:
        print("Files stay in %s (no Supabase Storage configured)." % storage.describe())


if __name__ == "__main__":
    main()
