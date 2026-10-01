"""SQLite schema, connection handling and first-run seed data."""

import os
import sqlite3
import threading

from . import srilanka

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "properties.db")

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

"""


def get_conn():
    """One connection per thread; the HTTP server is threaded."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


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
]


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


def migrate(conn):
    for table, column, decl in MIGRATIONS:
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in existing:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
    conn.commit()

    normalise_areas(conn)

    # Populate the owning-company master the first time it appears, and attach it
    # to the sample rows only -- matched by their exact seed property codes, so a
    # register holding real data is never touched.
    if conn.execute("SELECT COUNT(*) AS n FROM legal_entity").fetchone()["n"] == 0:
        seed_legal_entities(conn)
        if conn.execute("SELECT COUNT(*) AS n FROM property").fetchone()["n"]:
            assign_sample_entities(conn)
        conn.commit()

    # The location master arrives with the Master sheets module; fill it on the
    # first run that has it, so the sheet is not empty on an existing database.
    if conn.execute("SELECT COUNT(*) AS n FROM location").fetchone()["n"] == 0:
        if conn.execute("SELECT COUNT(*) AS n FROM property").fetchone()["n"]:
            seed_locations(conn)
            conn.commit()

    # Link the sample properties to the location master the first time that
    # column exists. Only the known seed property codes are matched.
    if conn.execute(
            "SELECT COUNT(*) AS n FROM property WHERE location_id IS NOT NULL"
    ).fetchone()["n"] == 0:
        assign_sample_locations(conn)
        conn.commit()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    # Indexes come after the migration: one of them covers a column that migrate()
    # adds to an already-existing property table.
    migrate(conn)
    conn.executescript(INDEXES)
    conn.commit()
    if conn.execute("SELECT COUNT(*) AS n FROM sbu").fetchone()["n"] == 0:
        seed(conn)
        normalise_areas(conn)


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

SEED_SBUS = [
    ("HO", "Head Office", "Corporate head office and shared services"),
    ("AGRI", "Agriculture", "Estates, farms and agri processing"),
    ("MFG", "Manufacturing", "Factories, plants and stores"),
    ("RETAIL", "Retail", "Showrooms, outlets and depots"),
    ("LOG", "Logistics", "Warehouses and distribution centres"),
    ("LEIS", "Leisure", "Hotels, resorts and bungalows"),
]

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
            "INSERT OR IGNORE INTO legal_entity (short_code, name, description) VALUES (?,?,?)",
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
            """INSERT OR IGNORE INTO location
               (name, city, district, province, latitude, longitude)
               VALUES (?,?,?,?,?,?)""",
            (name, city, district, info["province"] if info else None,
             info["lat"] if info else None, info["lng"] if info else None))
        row = conn.execute("SELECT id FROM location WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO location_code (code, location_id) VALUES (?,?)",
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
    for i, (code, name, desc) in enumerate(SEED_SBUS):
        conn.execute(
            "INSERT INTO sbu (code, name, description, color) VALUES (?,?,?,?)",
            (code, name, desc, srilanka.SBU_COLORS[i % len(srilanka.SBU_COLORS)]),
        )
    sbu_ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM sbu")}

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
