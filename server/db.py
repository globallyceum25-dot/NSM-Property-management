"""Schema, connection handling and first-run seed data.

The register runs on SQLite by default. With DATABASE_URL set to a Postgres
URL (a Supabase project's connection pooler, for example) it runs on Postgres
instead. The SQL elsewhere is written once, in sqlite3's style (`?` and
`:name` placeholders), and works on both; only the table definitions differ.
"""

import atexit
import datetime
import decimal
import os
import re
import sqlite3
import threading
from urllib.parse import urlparse

from . import srilanka

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# REGISTER_DATA_DIR moves the SQLite file and uploads elsewhere (the tests use
# a temporary folder, so they never touch the real register in data/).
DATA_DIR = os.environ.get("REGISTER_DATA_DIR") or os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "properties.db")

DATABASE_URL = os.environ.get("DATABASE_URL") or ""
IS_POSTGRES = bool(DATABASE_URL)

_local = threading.local()

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_property_sbu ON property(sbu_id);
CREATE INDEX IF NOT EXISTS idx_property_entity ON property(legal_entity_id);
CREATE INDEX IF NOT EXISTS idx_property_district ON property(district);
CREATE INDEX IF NOT EXISTS idx_property_status ON property(status);
CREATE INDEX IF NOT EXISTS idx_document_property ON document(property_id);
CREATE INDEX IF NOT EXISTS idx_document_type ON document(doc_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_location_name ON location(name);
CREATE INDEX IF NOT EXISTS idx_location_code_loc ON location_code(location_id);
CREATE INDEX IF NOT EXISTS idx_property_location ON property(location_id);
"""


SCHEMA = """
PRAGMA journal_mode = WAL;

-- An SBU is the sector / business unit / department that OCCUPIES a property and
-- carries its costs.  It is deliberately not the owning legal entity (LIS, CNT,
-- NCGE ...) and not the tenure (owned / leased / rented) -- conflating those
-- three is the data defect the blueprint flags in the current property sheet.
CREATE TABLE IF NOT EXISTS sbu (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    sector      TEXT,
    cost_centre TEXT,
    description TEXT,
    color       TEXT NOT NULL DEFAULT '#1f77b4',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The group company that holds title to the property.  Null is meaningful and
-- common: a property we lease or rent IN is owned by an outside landlord, who is
-- recorded on the lease document, not here.
CREATE TABLE IF NOT EXISTS legal_entity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    short_code  TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    reg_no      TEXT,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS property (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    property_code     TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    sbu_id            INTEGER NOT NULL REFERENCES sbu(id),
    legal_entity_id   INTEGER REFERENCES legal_entity(id),
    location_id       INTEGER REFERENCES location(id),
    property_type     TEXT NOT NULL DEFAULT 'LAND',
    ownership_type    TEXT NOT NULL DEFAULT 'FREEHOLD',
    status            TEXT NOT NULL DEFAULT 'ACTIVE',

    address_line1     TEXT,
    address_line2     TEXT,
    city              TEXT,
    district          TEXT,
    province          TEXT,
    postal_code       TEXT,

    latitude          REAL NOT NULL,
    longitude         REAL NOT NULL,

    extent_value      REAL,
    extent_unit       TEXT DEFAULT 'PERCH',
    building_area_sqft REAL,          -- derived: building_area_value in sq ft
    building_area_value REAL,         -- as entered, in building_area_unit
    building_area_unit TEXT DEFAULT 'SQ_FT',
    extent_sqft       REAL,           -- derived: extent_value in sq ft

    assessment_no     TEXT,
    plan_no           TEXT,
    lot_no            TEXT,

    acquisition_date  TEXT,
    acquisition_cost  REAL,
    current_value     REAL,
    currency          TEXT NOT NULL DEFAULT 'LKR',

    current_use       TEXT,
    custodian         TEXT,
    contact_phone     TEXT,
    notes             TEXT,

    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);


-- Master sheets ------------------------------------------------------------
-- A physical place where the group operates.  Kept as its own master so the
-- same town is spelled one way everywhere.
CREATE TABLE IF NOT EXISTS location (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    city        TEXT,
    district    TEXT,
    province    TEXT,
    latitude    REAL,
    longitude   REAL,
    notes       TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The short code used on documents and in the property sheet.  `code` is UNIQUE,
-- which is precisely what stops one code standing for two places -- the defect
-- the blueprint reports, where LLKO means both Kottawa and Kegalle.
CREATE TABLE IF NOT EXISTS location_code (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT NOT NULL UNIQUE,
    location_id  INTEGER NOT NULL REFERENCES location(id),
    description  TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS document (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id   INTEGER NOT NULL REFERENCES property(id) ON DELETE CASCADE,
    doc_type      TEXT NOT NULL DEFAULT 'OTHER',
    title         TEXT NOT NULL,
    reference_no  TEXT,
    issue_date    TEXT,
    expiry_date   TEXT,
    counterparty  TEXT,
    amount        REAL,
    currency      TEXT DEFAULT 'LKR',
    notes         TEXT,

    file_name     TEXT,
    stored_name   TEXT,
    mime_type     TEXT,
    size_bytes    INTEGER,

    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Facts about this register itself, such as which starter lists it has
-- already been given (so a list emptied on purpose is not refilled).
CREATE TABLE IF NOT EXISTS register_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# The same tables in Postgres types. Row level security is on with no policies:
# Supabase's public data API (the anon key) sees nothing, while the server,
# connecting as the tables' owner, is not restricted by it.
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS sbu (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    sector      TEXT,
    cost_centre TEXT,
    description TEXT,
    color       TEXT NOT NULL DEFAULT '#1f77b4',
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_entity (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    short_code  TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    reg_no      TEXT,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS location (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT,
    district    TEXT,
    province    TEXT,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    notes       TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS location_code (
    id           BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    location_id  BIGINT NOT NULL REFERENCES location(id),
    description  TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS property (
    id                  BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    property_code       TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    sbu_id              BIGINT NOT NULL REFERENCES sbu(id),
    legal_entity_id     BIGINT REFERENCES legal_entity(id),
    location_id         BIGINT REFERENCES location(id),
    property_type       TEXT NOT NULL DEFAULT 'LAND',
    ownership_type      TEXT NOT NULL DEFAULT 'FREEHOLD',
    status              TEXT NOT NULL DEFAULT 'ACTIVE',

    address_line1       TEXT,
    address_line2       TEXT,
    city                TEXT,
    district            TEXT,
    province            TEXT,
    postal_code         TEXT,

    latitude            DOUBLE PRECISION NOT NULL,
    longitude           DOUBLE PRECISION NOT NULL,

    extent_value        DOUBLE PRECISION,
    extent_unit         TEXT DEFAULT 'PERCH',
    building_area_sqft  DOUBLE PRECISION,
    building_area_value DOUBLE PRECISION,
    building_area_unit  TEXT DEFAULT 'SQ_FT',
    extent_sqft         DOUBLE PRECISION,

    assessment_no       TEXT,
    plan_no             TEXT,
    lot_no              TEXT,

    acquisition_date    DATE,
    acquisition_cost    DOUBLE PRECISION,
    current_value       DOUBLE PRECISION,
    currency            TEXT NOT NULL DEFAULT 'LKR',

    current_use         TEXT,
    custodian           TEXT,
    contact_phone       TEXT,
    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document (
    id            BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    property_id   BIGINT NOT NULL REFERENCES property(id) ON DELETE CASCADE,
    doc_type      TEXT NOT NULL DEFAULT 'OTHER',
    title         TEXT NOT NULL,
    reference_no  TEXT,
    issue_date    DATE,
    expiry_date   DATE,
    counterparty  TEXT,
    amount        DOUBLE PRECISION,
    currency      TEXT DEFAULT 'LKR',
    notes         TEXT,

    file_name     TEXT,
    stored_name   TEXT,
    mime_type     TEXT,
    size_bytes    BIGINT,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE sbu           ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_entity  ENABLE ROW LEVEL SECURITY;
ALTER TABLE location      ENABLE ROW LEVEL SECURITY;
ALTER TABLE location_code ENABLE ROW LEVEL SECURITY;
ALTER TABLE property      ENABLE ROW LEVEL SECURITY;
ALTER TABLE document      ENABLE ROW LEVEL SECURITY;

-- Facts about this register itself, such as which starter lists it has
-- already been given (so a list emptied on purpose is not refilled).
CREATE TABLE IF NOT EXISTS register_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
ALTER TABLE register_meta ENABLE ROW LEVEL SECURITY;
"""

# Tables in the order rows can be inserted (each after the tables it refers to).
TABLES = ["sbu", "legal_entity", "location", "location_code", "property", "document"]


# --- Postgres ---------------------------------------------------------------

# A string literal, a comment, a `?`, a `:name` (not a `::` cast) or a bare `%`.
_SQL_TOKEN = re.compile(r"'(?:[^']|'')*'|--[^\n]*|\?|(?<!:):(\w+)|%")


def _pg_sql(sql):
    """sqlite3-style placeholders to psycopg's: `?` -> %s, `:name` -> %(name)s.

    Every literal `%` is doubled, as psycopg expects once parameters are passed.
    """
    def swap(match):
        text = match.group(0)
        if text == "?":
            return "%s"
        if match.group(1):
            return "%%(%s)s" % match.group(1)
        return text.replace("%", "%%")
    return _SQL_TOKEN.sub(swap, sql)


def _plain(value):
    """Postgres values as the SQLite version of the register returned them."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime.datetime):
        return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _dict_row(cursor):
    names = [c.name for c in cursor.description or []]

    def make(values):
        return {name: _plain(value) for name, value in zip(names, values)}
    return make


class _PgConnection(object):
    """A pooled psycopg connection that takes the same calls as sqlite3's."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        # Always pass parameters, even none, so psycopg undoes the `%%` escaping.
        return self.raw.execute(_pg_sql(sql), params)

    def executescript(self, script):
        # No parameters: psycopg sends the script as is, statements and all.
        self.raw.execute(script)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


_pool = None
_pool_lock = threading.Lock()


def _pg_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError:
                raise SystemExit(
                    "DATABASE_URL is set, so the register needs the Postgres driver.\n"
                    "Install it once, then start with ./run.sh (which uses .venv):\n"
                    "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
            # prepare_threshold=None: no server-side prepared statements, which
            # a connection pooler in front of the database may not keep.
            _pool = ConnectionPool(DATABASE_URL, open=True, min_size=1, max_size=8, max_idle=120,
                                   kwargs={"row_factory": _dict_row,
                                           "prepare_threshold": None})
            _pool.wait(timeout=30)
            # Close it while the interpreter is still whole: left to garbage
            # collection at exit, the pool stalls shutdown and prints errors.
            atexit.register(_pool.close)
    return _pool


def describe():
    """Where the register keeps its data, for the startup banner."""
    if IS_POSTGRES:
        url = urlparse(DATABASE_URL)
        return "Postgres at %s:%s%s" % (url.hostname, url.port or 5432, url.path)
    return DB_PATH


def get_conn():
    """One connection per thread; the HTTP server is threaded."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        if IS_POSTGRES:
            conn = _PgConnection(_pg_pool().getconn())
        else:
            conn = sqlite3.connect(DB_PATH, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def release():
    """End of a request: hand this thread's Postgres connection back to the pool.

    Anything left uncommitted is rolled back. SQLite keeps its connection.
    """
    conn = getattr(_local, "conn", None)
    if conn is None or not IS_POSTGRES:
        return
    _local.conn = None
    try:
        conn.rollback()
    except Exception:
        pass    # a broken connection; the pool discards it
    _pg_pool().putconn(conn.raw)


def fetch_many(conn, statements):
    """Run several read queries, (sql, params) each; return their rows in order.

    On Postgres they travel in one pipelined round trip rather than one each,
    which is what keeps the dashboard quick against a distant database.
    """
    if not IS_POSTGRES:
        return [conn.execute(sql, params).fetchall() for sql, params in statements]
    with conn.raw.pipeline():
        cursors = [conn.raw.execute(_pg_sql(sql), params) for sql, params in statements]
    return [cursor.fetchall() for cursor in cursors]


def table_columns(conn, table):
    if IS_POSTGRES:
        rows = conn.execute("""SELECT column_name AS name FROM information_schema.columns
                               WHERE table_schema = current_schema() AND table_name = ?""",
                            (table,))
    else:
        rows = conn.execute("PRAGMA table_info(%s)" % table)
    return {r["name"] for r in rows}


# Columns added after the first release.  CREATE TABLE IF NOT EXISTS will not
# add them to a database that already exists, so apply them here.
MIGRATIONS = [
    ("sbu", "sector", "TEXT"),
    ("sbu", "cost_centre", "TEXT"),
    ("property", "legal_entity_id", "INTEGER REFERENCES legal_entity(id)"),
    ("property", "location_id", "INTEGER REFERENCES location(id)"),
    ("property", "building_area_value", "REAL"),
    ("property", "building_area_unit", "TEXT DEFAULT 'SQ_FT'"),
    ("property", "extent_sqft", "REAL"),
    ("sbu", "sort_order", "INTEGER"),
]


def adopt_property_categories(conn):
    """Business units became property types (Educational, Warehouse, ...).

    The six sample business units are renamed in place, so every property,
    document and link keeps pointing at the same row; the remaining types
    are added. Runs once: afterwards none of the old codes exist.
    """
    old = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM sbu")}
    if not any(code in old for code in srilanka.BUSINESS_UNIT_TO_CATEGORY):
        return
    categories = {c[0]: c for c in srilanka.PROPERTY_CATEGORIES}
    for unit, code in srilanka.BUSINESS_UNIT_TO_CATEGORY.items():
        if unit in old and code not in old:
            _, name, description, colour = categories[code]
            conn.execute("""UPDATE sbu SET code = ?, name = ?, description = ?, color = ?,
                                          sector = NULL, cost_centre = NULL WHERE id = ?""",
                         (code, name, description, colour, old[unit]))
    existing = {r["code"] for r in conn.execute("SELECT code FROM sbu")}
    for code, name, description, colour in srilanka.PROPERTY_CATEGORIES:
        if code not in existing:
            conn.execute("INSERT INTO sbu (code, name, description, color) VALUES (?, ?, ?, ?)",
                         (code, name, description, colour))
    order_categories(conn)
    conn.commit()


def order_categories(conn):
    """The starting list keeps its order; "Other" always sorts last."""
    for i, (code, *_rest) in enumerate(srilanka.PROPERTY_CATEGORIES):
        conn.execute("UPDATE sbu SET sort_order = ? WHERE code = ?",
                     (1000 if code == "OTHER" else (i + 1) * 10, code))


def normalise_structures(conn):
    """Structure now records only physical form; use lives in the property type."""
    conn.execute("UPDATE property SET property_type = 'LAND_AND_BUILDING' WHERE property_type IN (%s)"
                 % ",".join("?" * len(srilanka.RETIRED_STRUCTURES)), srilanka.RETIRED_STRUCTURES)
    conn.commit()


def normalise_areas(conn):
    """Every property's land and building area, also in square feet.

    Building area used to be recorded in sq ft only, so an existing figure
    becomes a value in SQ_FT before the conversion runs.
    """
    conn.execute("""UPDATE property SET building_area_value = building_area_sqft,
                                        building_area_unit = 'SQ_FT'
                    WHERE building_area_value IS NULL AND building_area_sqft IS NOT NULL""")
    for row in conn.execute("""SELECT id, extent_value, extent_unit, building_area_value,
                                      building_area_unit, extent_sqft, building_area_sqft
                               FROM property""").fetchall():
        extent = srilanka.to_sqft(row["extent_value"], row["extent_unit"])
        building = srilanka.to_sqft(row["building_area_value"], row["building_area_unit"])
        if extent != row["extent_sqft"] or building != row["building_area_sqft"]:
            conn.execute("UPDATE property SET extent_sqft = ?, building_area_sqft = ? WHERE id = ?",
                         (extent, building, row["id"]))
    conn.commit()


def was_seeded(conn, key):
    return conn.execute("SELECT 1 FROM register_meta WHERE key = ?", (key,)).fetchone() is not None


def mark_seeded(conn, key):
    if not was_seeded(conn, key):
        conn.execute("INSERT INTO register_meta (key, value) VALUES (?, ?)",
                     (key, datetime.date.today().isoformat()))


def migrate(conn):
    for table, column, decl in MIGRATIONS:
        if column not in table_columns(conn, table):
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
    conn.commit()

    normalise_areas(conn)
    adopt_property_categories(conn)
    normalise_structures(conn)

    # The starter owning companies and locations are given once per register.
    # After that an empty list means someone emptied it on purpose, so it stays
    # empty rather than being refilled at the next start.
    if not was_seeded(conn, "legal_entities"):
        # Attach them to the sample rows only -- matched by their exact seed
        # property codes, so a register holding real data is never touched.
        if conn.execute("SELECT COUNT(*) AS n FROM legal_entity").fetchone()["n"] == 0:
            seed_legal_entities(conn)
            if conn.execute("SELECT COUNT(*) AS n FROM property").fetchone()["n"]:
                assign_sample_entities(conn)
        mark_seeded(conn, "legal_entities")
        conn.commit()

    # The location master arrived with the Master sheets module; an existing
    # register got it filled on the first run that had it.
    if not was_seeded(conn, "locations"):
        if conn.execute("SELECT COUNT(*) AS n FROM location").fetchone()["n"] == 0:
            if conn.execute("SELECT COUNT(*) AS n FROM property").fetchone()["n"]:
                seed_locations(conn)
        mark_seeded(conn, "locations")
        conn.commit()

    # Link the sample properties to the location master the first time that
    # column exists. Only the known seed property codes are matched.
    if conn.execute(
            "SELECT COUNT(*) AS n FROM property WHERE location_id IS NOT NULL"
    ).fetchone()["n"] == 0:
        assign_sample_locations(conn)
        conn.commit()


def create_schema(conn):
    if IS_POSTGRES:
        conn.executescript(PG_SCHEMA)
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        conn.executescript(SCHEMA)
    conn.commit()


def init_db():
    conn = get_conn()
    create_schema(conn)
    # Indexes come after the migration: one of them covers a column that migrate()
    # adds to an already-existing property table.
    migrate(conn)
    conn.executescript(INDEXES)
    conn.commit()
    if conn.execute("SELECT COUNT(*) AS n FROM sbu").fetchone()["n"] == 0:
        seed(conn)
        normalise_areas(conn)
        normalise_structures(conn)
    release()


# --- first-run seed ---------------------------------------------------------
# These SBUs and properties are placeholders so the map and lists are not empty
# on first launch.  Replace them with the real register: SBUs are fully editable
# from the UI, and `python3 -m server.reset --wipe` clears the sample rows.

# Owning companies. The short codes come from the blueprint; the full registered
# names were not stated there, so `name` repeats the code until someone confirms
# it. Editable from the Owning companies tab, and the list is not exhaustive.
SEED_LEGAL_ENTITIES = [
    ("LIS", "LIS"),
    ("CNT", "CNT"),
    ("NCGE", "NCGE"),
    ("NCGH", "NCGH"),
    ("NSM", "NSM"),
]
ENTITY_PLACEHOLDER_NOTE = "Short code from the blueprint - confirm the full registered name."

# Which sample property belongs to which company. Properties we lease or rent IN
# are deliberately left unassigned: an outside landlord owns those, and that party
# belongs on the lease document instead.
SAMPLE_PROPERTY_ENTITY = {
    "HO-COL-001": "LIS",
    "AGRI-NUW-001": "NCGE",
    "AGRI-ANU-002": "NCGE",
    "MFG-KUR-002": "CNT",
    "LOG-COL-001": "CNT",
    "LEI-HAM-001": "NCGH",
    "LEI-BAD-002": "NSM",
}

# Sample location master: one row per place used by the sample properties, each
# with a single unique code. Replace with the real location list.
SEED_LOCATIONS = [
    # (code, name, city, district)
    ("LCOL", "Colombo 01", "Colombo 01", "Colombo"),
    ("LORU", "Orugodawatta", "Orugodawatta", "Colombo"),
    ("LYAK", "Yakkala", "Yakkala", "Gampaha"),
    ("LBIY", "Biyagama", "Biyagama", "Gampaha"),
    ("LKAN", "Kandy", "Kandy", "Kandy"),
    ("LNUW", "Nuwara Eliya", "Nuwara Eliya", "Nuwara Eliya"),
    ("LGAL", "Galle", "Galle", "Galle"),
    ("LHAM", "Hambantota", "Hambantota", "Hambantota"),
    ("LJAF", "Jaffna", "Jaffna", "Jaffna"),
    ("LTRI", "Trincomalee", "Trincomalee", "Trincomalee"),
    ("LANU", "Anuradhapura", "Anuradhapura", "Anuradhapura"),
    ("LKUR", "Kurunegala", "Kurunegala", "Kurunegala"),
    ("LBAD", "Badulla", "Badulla", "Badulla"),
]

# Which sample property sits at which location.
SAMPLE_PROPERTY_LOCATION = {
    "HO-COL-001": "Colombo 01",
    "HO-GAM-002": "Yakkala",
    "AGRI-NUW-001": "Nuwara Eliya",
    "AGRI-ANU-002": "Anuradhapura",
    "MFG-GAM-001": "Biyagama",
    "MFG-KUR-002": "Kurunegala",
    "RET-KAN-001": "Kandy",
    "RET-GAL-002": "Galle",
    "RET-JAF-003": "Jaffna",
    "LOG-COL-001": "Orugodawatta",
    "LOG-TRI-002": "Trincomalee",
    "LEI-HAM-001": "Hambantota",
    "LEI-BAD-002": "Badulla",
}

SEED_PROPERTIES = [
    # (sbu_code, code, name, type, ownership, status, addr, city, district,
    #  lat, lng, extent, unit, sqft, use)
    ("HO", "HO-COL-001", "Corporate Head Office", "LAND_AND_BUILDING", "FREEHOLD", "ACTIVE",
     "No. 45, Sir Baron Jayatilaka Mawatha", "Colombo 01", "Colombo",
     6.93548, 79.84265, 42.5, "PERCH", 38000, "Head office building"),
    ("HO", "HO-GAM-002", "Records & Archives Centre", "BUILDING", "LEASEHOLD", "ACTIVE",
     "Kandy Road, Yakkala", "Gampaha", "Gampaha",
     7.08997, 80.01234, 18.0, "PERCH", 9500, "Document archive"),
    ("AGRI", "AGRI-NUW-001", "Hill Country Tea Estate", "ESTATE", "FREEHOLD", "ACTIVE",
     "Ambewela Road", "Nuwara Eliya", "Nuwara Eliya",
     6.94970, 80.78910, 126.0, "ACRE", None, "Tea cultivation"),
    ("AGRI", "AGRI-ANU-002", "Anuradhapura Farm", "LAND", "STATE_GRANT", "ACTIVE",
     "Mihintale Road", "Anuradhapura", "Anuradhapura",
     8.31140, 80.40370, 54.0, "ACRE", None, "Crop farm"),
    ("MFG", "MFG-GAM-001", "Biyagama Manufacturing Plant", "FACTORY", "LEASEHOLD", "ACTIVE",
     "Biyagama Export Processing Zone", "Biyagama", "Gampaha",
     6.94800, 79.99100, 310.0, "PERCH", 86000, "Main production plant"),
    ("MFG", "MFG-KUR-002", "Kurunegala Assembly Unit", "LAND_AND_BUILDING", "FREEHOLD", "UNDER_CONSTRUCTION",
     "Negombo Road", "Kurunegala", "Kurunegala",
     7.48630, 80.36230, 180.0, "PERCH", 42000, "Assembly line (phase 2)"),
    ("RETAIL", "RET-KAN-001", "Kandy City Showroom", "SHOWROOM", "RENTED_IN", "ACTIVE",
     "Dalada Veediya", "Kandy", "Kandy",
     7.29360, 80.63510, 12.0, "PERCH", 5200, "Retail showroom"),
    ("RETAIL", "RET-GAL-002", "Galle Outlet", "SHOWROOM", "RENTED_IN", "ACTIVE",
     "Main Street, Galle Fort", "Galle", "Galle",
     6.02690, 80.21700, 9.5, "PERCH", 3100, "Retail outlet"),
    ("RETAIL", "RET-JAF-003", "Jaffna Outlet", "SHOWROOM", "LEASEHOLD", "ACTIVE",
     "Hospital Road", "Jaffna", "Jaffna",
     9.66150, 80.02550, 11.0, "PERCH", 3600, "Retail outlet"),
    ("LOG", "LOG-COL-001", "Orugodawatta Distribution Centre", "WAREHOUSE", "FREEHOLD", "ACTIVE",
     "New Nuge Road", "Orugodawatta", "Colombo",
     6.94500, 79.88900, 240.0, "PERCH", 64000, "Central warehouse"),
    ("LOG", "LOG-TRI-002", "Trincomalee Transit Store", "WAREHOUSE", "LEASEHOLD", "IDLE",
     "Harbour Road", "Trincomalee", "Trincomalee",
     8.58740, 81.21520, 96.0, "PERCH", 21000, "Transit store (idle)"),
    ("LEIS", "LEI-HAM-001", "Southern Coast Resort", "LAND_AND_BUILDING", "FREEHOLD", "ACTIVE",
     "Tangalle Road", "Hambantota", "Hambantota",
     6.12410, 81.11850, 3.5, "ACRE", 48000, "Resort hotel"),
    ("LEIS", "LEI-BAD-002", "Badulla Holiday Bungalow", "RESIDENTIAL", "FREEHOLD", "ACTIVE",
     "Bandarawela Road", "Badulla", "Badulla",
     6.99340, 81.05500, 64.0, "PERCH", 4800, "Staff holiday bungalow"),
]

SEED_DOCUMENTS = [
    # (property_code, doc_type, title, ref_no, issue, expiry, counterparty, amount)
    ("HO-COL-001", "DEED", "Deed of Transfer No. 4821", "4821", "2009-06-18", None,
     "Notary: S. Perera", None),
    ("HO-COL-001", "SURVEY_PLAN", "Survey Plan No. 1120/A", "1120/A", "2009-04-02", None,
     "Licensed Surveyor: K. Fernando", None),
    ("HO-GAM-002", "LEASE_AGREEMENT", "Lease agreement - Archives Centre", "LSE/2023/014",
     "2023-01-01", "2028-12-31", "Yakkala Holdings (Pvt) Ltd", 185000.0),
    ("AGRI-NUW-001", "DEED", "Deed of Transfer No. 2214", "2214", "1998-11-05", None,
     "Notary: M. Jayasuriya", None),
    ("MFG-GAM-001", "LEASE_AGREEMENT", "BOI land lease - Biyagama", "BOI/L/2015/77",
     "2015-03-01", "2045-02-28", "Board of Investment of Sri Lanka", 1250000.0),
    ("RET-KAN-001", "LEASE_AGREEMENT", "Tenancy agreement - Kandy showroom", "TEN/2024/03",
     "2024-04-01", "2027-03-31", "Dalada Properties", 420000.0),
    ("LOG-COL-001", "DEED", "Deed of Transfer No. 7745", "7745", "2013-08-22", None,
     "Notary: A. Wickramasinghe", None),
    ("LOG-COL-001", "INSURANCE_POLICY", "Fire & perils policy", "POL-88213",
     "2025-01-01", "2026-12-31", "Ceylinco General Insurance", 3400000.0),
    ("LEI-HAM-001", "VALUATION_REPORT", "Valuation report 2025", "VAL/2025/09",
     "2025-03-15", None, "Sunil Fernando & Associates", 485000000.0),
]


def seed_legal_entities(conn):
    for short_code, name in SEED_LEGAL_ENTITIES:
        conn.execute(
            """INSERT INTO legal_entity (short_code, name, description) VALUES (?,?,?)
               ON CONFLICT DO NOTHING""",
            (short_code, name, ENTITY_PLACEHOLDER_NOTE))


def assign_sample_entities(conn):
    ids = {r["short_code"]: r["id"]
           for r in conn.execute("SELECT id, short_code FROM legal_entity")}
    for property_code, short_code in SAMPLE_PROPERTY_ENTITY.items():
        if short_code in ids:
            conn.execute(
                "UPDATE property SET legal_entity_id = ? WHERE property_code = ?",
                (ids[short_code], property_code))


def seed_locations(conn):
    for code, name, city, district in SEED_LOCATIONS:
        info = srilanka.DISTRICT_BY_NAME.get(district)
        conn.execute(
            """INSERT INTO location
               (name, city, district, province, latitude, longitude)
               VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (name, city, district, info["province"] if info else None,
             info["lat"] if info else None, info["lng"] if info else None))
        row = conn.execute("SELECT id FROM location WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "INSERT INTO location_code (code, location_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                (code, row["id"]))


def assign_sample_locations(conn):
    """Point the sample properties at the sample locations.

    Matched on the exact seed property codes, so a register holding real data is
    never touched.
    """
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM location")}
    for property_code, location_name in SAMPLE_PROPERTY_LOCATION.items():
        if location_name in ids:
            conn.execute("UPDATE property SET location_id = ? WHERE property_code = ?",
                         (ids[location_name], property_code))


def seed(conn):
    seed_legal_entities(conn)
    seed_locations(conn)
    mark_seeded(conn, "legal_entities")
    mark_seeded(conn, "locations")
    for code, name, desc, colour in srilanka.PROPERTY_CATEGORIES:
        conn.execute(
            "INSERT INTO sbu (code, name, description, color) VALUES (?,?,?,?)",
            (code, name, desc, colour),
        )
    order_categories(conn)
    sbu_ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM sbu")}
    # The sample properties were written against business units; place each
    # under the property type its unit became.
    sbu_ids.update({unit: sbu_ids[code]
                    for unit, code in srilanka.BUSINESS_UNIT_TO_CATEGORY.items()})

    for row in SEED_PROPERTIES:
        (sbu_code, code, name, ptype, ownership, status, addr, city, district,
         lat, lng, extent, unit, sqft, use) = row
        province = srilanka.DISTRICT_BY_NAME[district]["province"]
        conn.execute(
            """INSERT INTO property
               (property_code, name, sbu_id, property_type, ownership_type, status,
                address_line1, city, district, province, latitude, longitude,
                extent_value, extent_unit, building_area_sqft, current_use)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, name, sbu_ids[sbu_code], ptype, ownership, status, addr, city,
             district, province, lat, lng, extent, unit, sqft, use),
        )
    assign_sample_entities(conn)
    assign_sample_locations(conn)
    prop_ids = {r["property_code"]: r["id"]
                for r in conn.execute("SELECT id, property_code FROM property")}

    for (pcode, dtype, title, ref, issue, expiry, party, amount) in SEED_DOCUMENTS:
        conn.execute(
            """INSERT INTO document
               (property_id, doc_type, title, reference_no, issue_date, expiry_date,
                counterparty, amount)
               VALUES (?,?,?,?,?,?,?,?)""",
            (prop_ids[pcode], dtype, title, ref, issue, expiry, party, amount),
        )
    conn.commit()
