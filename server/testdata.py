"""Test data: a sandbox register kept apart from the real one.

Test properties carry property.is_test = 1. Their documents and finance
entries belong to them, so they are test data too. Property types, owning
companies and the master lists are shared: the test set uses the real lists
and adds nothing to them.

Each person chooses which data they see (app_user.test_mode). In test mode every
list, count, chart and export shows only test properties, and anything created
is created as test data; in real mode test data is invisible.

The set covers every section: all property types, the owning companies, every
tenure, status, structure and area unit, documents across the whole renewal
ladder (with and without files), and finance that is profitable, break-even,
loss-making and cost only. Dates are relative to the day it is loaded.
"""

import datetime
import uuid

from . import access, db, storage
from .errors import ApiError

CODE_PREFIX = "TST-"

# name, type code, company, tenure, structure, status, district, town, lat, lng,
# (land, unit), (floor, unit), finance profile
PROPERTIES = [
    ("Test Lyceum Campus - Kandy", "EDU", "LIS", "FREEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Kandy", "Kandy",
     7.2906, 80.6337, (120, "PERCH"), (38000, "SQ_FT"), "school"),
    ("Test Lyceum Campus - Galle", "EDU", "LIS", "RENTED_IN", "LAND_AND_BUILDING", "ACTIVE", "Galle", "Galle",
     6.0535, 80.2210, (80, "PERCH"), (24000, "SQ_FT"), "school-rented"),
    ("Test Leaf School - Negombo", "EDU", "LIS", "LEASEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Gampaha", "Negombo",
     7.2083, 79.8358, (60, "PERCH"), (16500, "SQ_FT"), "school-thin"),
    ("Test Leaf School - Matara", "EDU", "LIS", "RENTED_IN", "BUILDING", "ACTIVE", "Matara", "Matara",
     5.9549, 80.5550, None, (9000, "SQ_FT"), "school-loss"),
    ("Test Central Warehouse - Peliyagoda", "WH", "CNT", "FREEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Gampaha",
     "Peliyagoda", 6.9600, 79.8890, (2.5, "ACRE"), (42000, "SQ_FT"), "warehouse"),
    ("Test Distribution Store - Kurunegala", "WH", "NCGE", "RENTED_IN", "BUILDING", "ACTIVE", "Kurunegala",
     "Kurunegala", 7.4863, 80.3623, None, (12500, "SQ_FT"), "cost-rented"),
    ("Test Head Office - Colombo 03", "CORP", "NCGH", "FREEHOLD", "BUILDING", "ACTIVE", "Colombo", "Colombo 03",
     6.9000, 79.8530, (40, "PERCH"), (30000, "SQ_FT"), "office"),
    ("Test Regional Office - Jaffna", "CORP", "NCGH", "RENTED_IN", "BUILDING", "ACTIVE", "Jaffna", "Jaffna",
     9.6615, 80.0255, None, (4200, "SQ_FT"), "cost-rented"),
    ("Test Bus Workshop - Ratmalana", "TECH", "NSM", "FREEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Colombo",
     "Ratmalana", 6.8216, 79.8862, (1.2, "HECTARE"), (18000, "SQ_FT"), "workshop"),
    ("Test Generator House - Anuradhapura", "TECH", "NSM", "STATE_GRANT", "BUILDING", "IDLE", "Anuradhapura",
     "Anuradhapura", 8.3114, 80.4037, (2, "ROOD"), (1500, "SQ_FT"), "idle"),
    ("Test Bus Yard - Kadawatha", "BUS", "NSM", "LEASEHOLD", "LAND", "ACTIVE", "Gampaha", "Kadawatha",
     7.0012, 79.9530, (3, "ACRE"), None, "yard"),
    ("Test Bus Yard - Batticaloa", "BUS", None, "RENTED_IN", "LAND", "ACTIVE", "Batticaloa", "Batticaloa",
     7.7310, 81.6747, (1.5, "ACRE"), None, "yard-loss"),
    ("Test Staff Hostel - Nugegoda", "HOST", "LIS", "RENTED_IN", "LAND_AND_BUILDING", "ACTIVE", "Colombo",
     "Nugegoda", 6.8649, 79.8997, (25, "PERCH"), (8000, "SQ_FT"), "hostel"),
    ("Test Student Hostel - Peradeniya", "HOST", "LIS", "FREEHOLD", "LAND_AND_BUILDING", "UNDER_CONSTRUCTION",
     "Kandy", "Peradeniya", 7.2690, 80.5940, (55, "PERCH"), (14000, "SQ_FT"), "construction"),
    ("Test City Showroom - Kandy", "COMM", "NCGE", "RENTED_IN", "BUILDING", "ACTIVE", "Kandy", "Kandy",
     7.2955, 80.6356, None, (3500, "SQ_FT"), "shop"),
    ("Test Shopping Unit - Colombo 07", "COMM", "NCGE", "LEASED_OUT", "BUILDING", "ACTIVE", "Colombo", "Colombo 07",
     6.9110, 79.8640, None, (2200, "SQ_M"), "let"),
    ("Test Car Park - Panadura", "COMM", "LIS", "FREEHOLD", "LAND", "ACTIVE", "Kalutara", "Panadura",
     6.7130, 79.9070, (45, "PERCH"), None, "carpark"),
    ("Test Commercial Plot - Hambantota", "COMM", "CNT", "FREEHOLD", "LAND", "IDLE", "Hambantota", "Hambantota",
     6.1240, 81.1185, (2, "ACRE"), None, "land"),
    ("Test Disputed Land - Ratnapura", "OTHER", "CNT", "FREEHOLD", "LAND", "UNDER_DISPUTE", "Ratnapura",
     "Ratnapura", 6.6828, 80.3992, (90, "PERCH"), None, "disputed"),
    ("Test Former Depot - Badulla", "OTHER", None, "OTHER", "LAND_AND_BUILDING", "DISPOSED", "Badulla", "Badulla",
     6.9934, 81.0550, (35, "PERCH"), (5200, "SQ_FT"), "none"),
    ("Test Training Centre - Kalutara", "EDU", "LIS", "FREEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Kalutara",
     "Kalutara", 6.5854, 79.9607, (70, "PERCH"), (12000, "SQ_FT"), "school"),
    ("Test Cold Store - Trincomalee", "WH", "CNT", "LEASEHOLD", "LAND_AND_BUILDING", "ACTIVE", "Trincomalee",
     "Trincomalee", 8.5874, 81.2152, (1, "ACRE"), (9600, "SQ_FT"), "warehouse-thin"),
    ("Test Canteen - Kurunegala", "OTHER", "LIS", "RENTED_IN", "BUILDING", "ACTIVE", "Kurunegala", "Kurunegala",
     7.4818, 80.3609, None, (1800, "SQ_FT"), "shop-even"),
    ("Test Sports Ground - Nuwara Eliya", "EDU", "LIS", "LEASEHOLD", "LAND", "ACTIVE", "Nuwara Eliya",
     "Nuwara Eliya", 6.9497, 80.7891, (1.8, "HECTARE"), None, "cost-lease"),
]

# Monthly income, monthly rent, other monthly running costs, capital (LKR).
PROFILES = {
    "school": (2600000, 0, 650000, 85000000), "school-rented": (1900000, 550000, 420000, 0),
    "school-thin": (950000, 380000, 520000, 0), "school-loss": (420000, 480000, 210000, 0),
    "warehouse": (0, 0, 320000, 120000000), "warehouse-thin": (300000, 0, 285000, 0),
    "cost-rented": (0, 240000, 90000, 0), "office": (0, 0, 780000, 210000000),
    "workshop": (180000, 0, 260000, 45000000), "idle": (0, 0, 35000, 0), "yard": (520000, 150000, 110000, 0),
    "yard-loss": (90000, 160000, 60000, 0), "hostel": (640000, 300000, 140000, 0),
    "construction": (0, 0, 60000, 64000000), "shop": (1450000, 600000, 380000, 0),
    "let": (850000, 0, 95000, 0), "carpark": (210000, 0, 25000, 18000000), "land": (0, 0, 15000, 32000000),
    "disputed": (0, 0, 40000, 0), "none": (0, 0, 0, 0), "shop-even": (390000, 180000, 200000, 0),
    "cost-lease": (0, 120000, 30000, 0),
}

# doc type, title, months to expiry (None: no expiry), with a file?
DOCS = [
    ("DEED", "Deed of Transfer", None, True), ("TITLE_CERTIFICATE", "Title certificate", None, True),
    ("LEASE_AGREEMENT", "Lease agreement", -1, True), ("LEASE_AGREEMENT", "Rent agreement", 2, True),
    ("SURVEY_PLAN", "Survey plan", None, False), ("VALUATION_REPORT", "Valuation report", None, True),
    ("TAX_RECEIPT", "Assessment rates receipt", 5, True), ("INSURANCE_POLICY", "Fire insurance policy", 8, True),
    ("PERMIT_APPROVAL", "Certificate of conformity", 11, False), ("LEASE_AGREEMENT", "Long lease", 30, True),
    ("PHOTOGRAPH", "Site photograph", None, False), ("OTHER", "Board approval", None, False),
]


def _day(base, months=0, days=0):
    y, m = divmod(base.year * 12 + base.month - 1 + months, 12)
    return datetime.date(y, m + 1, min(base.day, 28)) + datetime.timedelta(days=days)


def tiny_pdf(title, lines):
    """A one-page PDF with a heading and a few lines."""
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = ["BT /F2 22 Tf 64 760 Td (%s) Tj ET" % esc(title), "0.75 0.8 0.8 RG 64 742 m 531 742 l S"]
    y = 712
    for line in lines:
        body.append("BT /F1 13 Tf 64 %d Td (%s) Tj ET" % (y, esc(line)))
        y -= 24
    body.append("BT /F1 10 Tf 64 60 Td (TEST DATA - not a real document) Tj ET")
    stream = "\n".join(body).encode("latin-1", "replace")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


class _Body:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def counts(conn):
    one = lambda sql: conn.execute(sql).fetchone()["n"]  # noqa: E731
    return {"properties": one("SELECT COUNT(*) AS n FROM property WHERE is_test = 1"),
            "documents": one("SELECT COUNT(*) AS n FROM document d JOIN property p ON p.id = d.property_id "
                             "WHERE p.is_test = 1"),
            "entries": one("SELECT COUNT(*) AS n FROM finance_entry f JOIN property p ON p.id = f.property_id "
                           "WHERE p.is_test = 1")}


def remove(conn):
    """Delete every test property with its documents, files and finance entries."""
    files = [r["stored_name"] for r in conn.execute(
        "SELECT d.stored_name FROM document d JOIN property p ON p.id = d.property_id "
        "WHERE p.is_test = 1 AND d.stored_name IS NOT NULL")]
    conn.execute("DELETE FROM finance_entry WHERE property_id IN (SELECT id FROM property WHERE is_test = 1)")
    conn.execute("DELETE FROM document WHERE property_id IN (SELECT id FROM property WHERE is_test = 1)")
    conn.execute("DELETE FROM property WHERE is_test = 1")
    conn.commit()
    for name in files:
        storage.remove(name)


def load(conn, user_id=None, today=None):
    """Replace the test set with a fresh one; returns its counts."""
    from . import api
    remove(conn)
    today = today or datetime.date.today()
    sbus = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM sbu")}
    if not sbus:
        raise ApiError("Add at least one property type before loading test data.", 400)
    fallback = next(iter(sbus.values()))
    entities = {r["short_code"]: r["id"] for r in conn.execute("SELECT id, short_code FROM legal_entity")}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fy = datetime.date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    last_fy = datetime.date(fy.year - 1, 4, 1)
    files = []
    try:
        for i, (name, sbu, entity, tenure, structure, status, district, town, lat, lng, land, floor,
                profile) in enumerate(PROPERTIES):
            owned = tenure in ("FREEHOLD", "LEASED_OUT")
            income, rent, running, capital = PROFILES[profile]
            data = {
                "name": name, "property_code": "%s%s-%02d" % (CODE_PREFIX, sbu, i + 1),
                "sbu_id": sbus.get(sbu, fallback), "legal_entity_id": entities.get(entity) if entity else None,
                "ownership_type": tenure, "property_type": structure, "status": status,
                "latitude": lat, "longitude": lng, "district": district, "city": town,
                "address_line1": "No. %d, Test Road" % (10 + i * 7), "postal_code": "%05d" % (10000 + i * 371),
                "extent_value": land[0] if land else "", "extent_unit": land[1] if land else "PERCH",
                "building_area_value": floor[0] if floor else "", "building_area_unit": floor[1] if floor else "SQ_FT",
                "assessment_no": "TA/%d/%03d" % (2020 + i % 5, i + 11), "plan_no": "TP-%04d" % (3100 + i * 13),
                "lot_no": str(1 + i % 7),
                "acquisition_date": _day(today, -(30 + i * 9)).isoformat() if owned else "",
                "acquisition_cost": capital or "", "current_value": int(capital * 1.35) if capital else "",
                "currency": "LKR", "current_use": "Test record", "custodian": "Test custodian %d" % (i + 1),
                "contact_phone": "+94 11 %03d %04d" % (200 + i, 1000 + i * 37),
                "notes": "Test data — not a real property.",
            }
            payload, code = api._property_payload(_Body(data), conn)
            payload["property_code"] = code
            payload["is_test"] = 1
            cols = ["property_code", "sbu_id", "legal_entity_id", "location_id", "latitude", "longitude",
                    "is_test"] + api.PROPERTY_FIELDS
            pid = conn.execute("INSERT INTO property (%s) VALUES (%s) RETURNING id"
                               % (", ".join(cols), ", ".join(":" + c for c in cols)), payload).fetchone()["id"]

            # Documents: owned properties have deeds; rented ones have leases;
            # every property gets two more from the list, so the ladder is covered.
            picks = [0, 5] if owned else [3 if i % 2 else 2]
            picks += [(i * 3 + k) % len(DOCS) for k in (4, 7)]
            if profile == "none":
                picks = []
            for j, k in enumerate(dict.fromkeys(picks)):
                doc_type, title, months, with_file = DOCS[k]
                expiry = _day(today, months, days=(i * 5) % 20) if months is not None else None
                if months is not None and months < 0:
                    expiry = today - datetime.timedelta(days=12 + i)
                row = {"property_id": pid, "doc_type": doc_type, "title": "%s — %s" % (title, town),
                       "reference_no": "T-%03d-%d" % (i + 1, j + 1),
                       "issue_date": _day(today, -(14 + i + j * 5)).isoformat(),
                       "expiry_date": expiry.isoformat() if expiry else None,
                       "counterparty": "Test counterparty", "amount": None, "currency": "LKR",
                       "notes": "Test document.", "file_name": None, "stored_name": None, "mime_type": None,
                       "size_bytes": None, "uploaded_by": user_id}
                if with_file:
                    blob = tiny_pdf(row["title"], [name, "Reference: " + row["reference_no"],
                                                   "Expires: " + (row["expiry_date"] or "no expiry")])
                    row.update(file_name=title.replace(" ", "-") + ".pdf", stored_name=uuid.uuid4().hex + ".pdf",
                               mime_type="application/pdf", size_bytes=len(blob))
                    storage.save(row["stored_name"], blob, "application/pdf")
                    files.append(row["stored_name"])
                dcols = list(row)
                conn.execute("INSERT INTO document (%s) VALUES (%s)" % (", ".join(dcols), ", ".join(":" + c for c in dcols)),
                             row)

            # Finance: last year and this year, so every period has figures.
            def entry(kind, category, amount, start, months=1, who=None, what=None, pid=pid):
                conn.execute("""INSERT INTO finance_entry (property_id, kind, category, amount, currency, period_start,
                                    months, description, counterparty, reference_no, notes, created_by, created_at,
                                    updated_at)
                                VALUES (?, ?, ?, ?, 'LKR', ?, ?, ?, ?, NULL, 'Test entry', ?, ?, ?)""",
                             (pid, kind, category, round(amount, 2), start.isoformat(), months, what, who, user_id, stamp,
                              stamp))
            for year in (last_fy, fy):
                if rent:
                    entry("cost", "RENT", rent * 12, year, 12, "Test landlord", "Rent for the year")
                if running:
                    entry("cost", "RATES_TAXES", running * 0.15 * 12, year, 12, "Local authority", "Assessment rates")
                    entry("cost", "UTILITIES", running * 0.45 * 6, year, 6, "CEB / NWSDB", "Utilities, first half")
                    entry("cost", "UTILITIES", running * 0.45 * 6, _day(year, 6), 6, "CEB / NWSDB",
                          "Utilities, second half")
                    entry("cost", "MAINTENANCE", running * 0.40 * 12, year, 12, "Test contractor",
                          "Maintenance contract")
                    if i % 3 == 0:
                        entry("cost", "MAINTENANCE", running * 0.5, _day(year, 3 + i % 6), 1, "Test contractor",
                              "One-off repairs")
                if income:
                    category = "RENT_RECEIVED" if tenure == "LEASED_OUT" else "BUSINESS_REVENUE"
                    for q in range(4):
                        entry("income", category, income * 3 * (1 + 0.02 * (q % 2)), _day(year, q * 3), 3,
                              "Test tenant" if category == "RENT_RECEIVED" else None, "Quarter %d" % (q + 1))
            if capital:
                entry("capital", "PURCHASE", capital * 0.8, _day(last_fy, -14 - i), 1, "Test vendor", "Purchase")
                entry("capital", "LEGAL_FEES", capital * 0.04, _day(last_fy, -14 - i), 1, "Test notary",
                      "Stamp duty and legal fees")
                if profile == "construction":
                    entry("capital", "CONSTRUCTION", capital * 0.3, _day(fy, 2), 1, "Test builder", "Construction")
        conn.commit()
    except Exception:
        conn.rollback()
        for name in files:
            storage.remove(name)
        raise
    return counts(conn)


# --- endpoints --------------------------------------------------------------------

def get_state(ctx):
    conn = db.get_conn()
    return 200, dict(counts(conn), testMode=bool(access.test_mode(ctx)),
                     canManage=bool(ctx.access and ctx.access.can("properties.delete")))


def set_mode(ctx):
    """Show this person test data, or real data again."""
    conn = db.get_conn()
    on = bool(ctx.json().get("on"))
    conn.execute("UPDATE app_user SET test_mode = ? WHERE id = ?", (1 if on else 0, ctx.user["id"]))
    conn.commit()
    return 200, dict(counts(conn), testMode=on)


def load_data(ctx):
    conn = db.get_conn()
    result = load(conn, ctx.user["id"])
    access.record(conn, "property.test_load", "Test data",
                  "Loaded %(properties)d test properties, %(documents)d documents, %(entries)d finance entries"
                  % result, ctx.user, access.client_ip(ctx))
    return 201, result


def remove_data(ctx):
    conn = db.get_conn()
    before = counts(conn)
    remove(conn)
    access.record(conn, "property.test_remove", "Test data",
                  "Removed %(properties)d test properties with their documents and finance entries" % before,
                  ctx.user, access.client_ip(ctx))
    return 200, counts(conn)


ROUTES = [
    ("GET", r"^/api/test-data$", get_state),
    ("PUT", r"^/api/test-data/mode$", set_mode),
    ("POST", r"^/api/test-data$", load_data),
    ("DELETE", r"^/api/test-data$", remove_data),
]
