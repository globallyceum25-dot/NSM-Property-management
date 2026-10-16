"""REST handlers for the property register."""

import csv
import datetime
import io
import os
import re
import uuid

from . import db, errors, masters, srilanka
from .srilanka import valid_codes

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff",
    ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".zip",
}

PROPERTY_FIELDS = [
    "name", "property_type", "ownership_type", "status",
    "address_line1", "address_line2", "city", "district", "province", "postal_code",
    "extent_value", "extent_unit", "extent_sqft",
    "building_area_value", "building_area_unit", "building_area_sqft",
    "assessment_no", "plan_no", "lot_no",
    "acquisition_date", "acquisition_cost", "current_value", "currency",
    "current_use", "custodian", "contact_phone", "notes",
]

DOCUMENT_FIELDS = [
    "doc_type", "title", "reference_no", "issue_date", "expiry_date",
    "counterparty", "amount", "currency", "notes",
]


ApiError = errors.ApiError


# --- helpers ----------------------------------------------------------------

def _row_to_dict(row):
    return dict(row) if row is not None else None


def _clean_str(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


# Currency marks and separators people type around amounts: "LKR 1,250,000",
# "Rs. 420,000/=", "1 250 000". Stripped before the number is read.
_CURRENCY_PREFIX = re.compile(r"^(?:lkr|rs\.?|usd|us\$|\$)\s*", re.IGNORECASE)
_AMOUNT_SUFFIX = re.compile(r"\s*/\s*[=-]\s*$")


def _as_float(value, label, key):
    """Read a number the way people write one; `key` names the form field."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = _AMOUNT_SUFFIX.sub("", _CURRENCY_PREFIX.sub("", str(value).strip()))
    text = text.replace(",", "").replace(" ", "").replace("_", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        raise ApiError("%s must be a number, for example 1,250,000." % label, field=key)


def _as_date(value, label, key):
    value = _clean_str(value)
    if value is None:
        return None
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError("%s must be a date in YYYY-MM-DD format." % label, field=key)
    return value


def _check_enum(value, pairs, field, default=None):
    value = _clean_str(value) or default
    if value is None:
        raise ApiError("%s is required." % field, field=field)
    codes = valid_codes(pairs)
    if value not in codes:
        raise ApiError("%s must be one of: %s" % (field, ", ".join(codes)), field=field)
    return value


def _next_property_code(conn, sbu_id):
    sbu = conn.execute("SELECT code FROM sbu WHERE id = ?", (sbu_id,)).fetchone()
    prefix = (sbu["code"] if sbu else "PRP").upper()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM property WHERE sbu_id = ?", (sbu_id,)
    ).fetchone()["n"]
    while True:
        n += 1
        code = "%s-%04d" % (prefix, n)
        exists = conn.execute(
            "SELECT 1 FROM property WHERE property_code = ?", (code,)
        ).fetchone()
        if not exists:
            return code


# --- reference data ---------------------------------------------------------

def get_reference(ctx):
    return 200, {
        "provinces": [
            {"province": name,
             "districts": [{"district": d, "lat": lat, "lng": lng}
                           for d, lat, lng in districts]}
            for name, districts in srilanka.PROVINCES
        ],
        "districts": srilanka.DISTRICTS,
        "propertyTypes": srilanka.as_options(srilanka.PROPERTY_TYPES),
        "ownershipTypes": srilanka.as_options(srilanka.OWNERSHIP_TYPES),
        "statuses": srilanka.as_options(srilanka.PROPERTY_STATUSES),
        "extentUnits": srilanka.as_options(srilanka.EXTENT_UNITS),
        "sqftPerUnit": srilanka.SQFT_PER_UNIT,
        "documentTypes": srilanka.as_options(srilanka.DOCUMENT_TYPES),
        "bounds": srilanka.SRI_LANKA_BOUNDS,
        "mapCenter": srilanka.MAP_CENTER,
        "mapZoom": srilanka.MAP_DEFAULT_ZOOM,
        "colors": srilanka.SBU_COLORS,
        "maxUploadBytes": MAX_UPLOAD_BYTES,
        "allowedExtensions": sorted(ALLOWED_EXTENSIONS),
    }


# --- SBUs -------------------------------------------------------------------

def list_sbus(ctx):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM property p WHERE p.sbu_id = s.id) AS property_count
           FROM sbu s ORDER BY COALESCE(s.sort_order, 500), s.name"""
    ).fetchall()
    return 200, [_row_to_dict(r) for r in rows]


def _sbu_payload(ctx, require_code=True):
    data = ctx.json()
    code = _clean_str(data.get("code"))
    name = _clean_str(data.get("name"))
    if require_code and not code:
        raise ApiError("Property type code is required.", field="code")
    if not name:
        raise ApiError("Property type name is required.", field="name")
    color = _clean_str(data.get("color")) or srilanka.SBU_COLORS[0]
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        raise ApiError("Colour must be a hex value like #1f77b4.", field="color")
    return {
        "code": code.upper() if code else None,
        "name": name,
        "sector": _clean_str(data.get("sector")),
        "cost_centre": _clean_str(data.get("cost_centre")),
        "description": _clean_str(data.get("description")),
        "color": color,
        "is_active": 1 if data.get("is_active", True) else 0,
    }


def create_sbu(ctx):
    payload = _sbu_payload(ctx)
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM sbu WHERE code = ?", (payload["code"],)).fetchone():
        raise ApiError("A property type with code '%s' already exists." % payload["code"], 409, "code")
    cur = conn.execute(
        """INSERT INTO sbu (code, name, sector, cost_centre, description, color, is_active)
           VALUES (:code, :name, :sector, :cost_centre, :description, :color, :is_active)""",
        payload)
    conn.commit()
    row = conn.execute("SELECT * FROM sbu WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, _row_to_dict(row)


def update_sbu(ctx):
    sbu_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM sbu WHERE id = ?", (sbu_id,)).fetchone():
        raise ApiError("Property type not found.", 404)
    payload = _sbu_payload(ctx)
    clash = conn.execute("SELECT 1 FROM sbu WHERE code = ? AND id <> ?",
                         (payload["code"], sbu_id)).fetchone()
    if clash:
        raise ApiError("A property type with code '%s' already exists." % payload["code"], 409, "code")
    payload["id"] = sbu_id
    conn.execute(
        """UPDATE sbu SET code=:code, name=:name, sector=:sector,
                          cost_centre=:cost_centre, description=:description,
                          color=:color, is_active=:is_active,
                          updated_at=datetime('now')
           WHERE id=:id""", payload)
    conn.commit()
    row = conn.execute("SELECT * FROM sbu WHERE id = ?", (sbu_id,)).fetchone()
    return 200, _row_to_dict(row)


# --- legal entities (owning companies) --------------------------------------

def list_legal_entities(ctx):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT e.*,
                  (SELECT COUNT(*) FROM property p WHERE p.legal_entity_id = e.id)
                      AS property_count
           FROM legal_entity e ORDER BY e.short_code"""
    ).fetchall()
    return 200, [_row_to_dict(r) for r in rows]


def _entity_payload(ctx):
    data = ctx.json()
    short_code = _clean_str(data.get("short_code"))
    name = _clean_str(data.get("name"))
    if not short_code:
        raise ApiError("Short code is required.", field="short_code")
    if not name:
        raise ApiError("Company name is required.", field="name")
    return {
        "short_code": short_code.upper(),
        "name": name,
        "reg_no": _clean_str(data.get("reg_no")),
        "description": _clean_str(data.get("description")),
        "is_active": 1 if data.get("is_active", True) else 0,
    }


def create_legal_entity(ctx):
    payload = _entity_payload(ctx)
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM legal_entity WHERE short_code = ?",
                    (payload["short_code"],)).fetchone():
        raise ApiError("A company with short code '%s' already exists."
                       % payload["short_code"], 409, "short_code")
    cur = conn.execute(
        """INSERT INTO legal_entity (short_code, name, reg_no, description, is_active)
           VALUES (:short_code, :name, :reg_no, :description, :is_active)""", payload)
    conn.commit()
    row = conn.execute("SELECT * FROM legal_entity WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
    return 201, _row_to_dict(row)


def update_legal_entity(ctx):
    entity_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM legal_entity WHERE id = ?", (entity_id,)).fetchone():
        raise ApiError("Owning company not found.", 404)
    payload = _entity_payload(ctx)
    clash = conn.execute("SELECT 1 FROM legal_entity WHERE short_code = ? AND id <> ?",
                         (payload["short_code"], entity_id)).fetchone()
    if clash:
        raise ApiError("A company with short code '%s' already exists."
                       % payload["short_code"], 409, "short_code")
    payload["id"] = entity_id
    conn.execute(
        """UPDATE legal_entity SET short_code=:short_code, name=:name, reg_no=:reg_no,
                                   description=:description, is_active=:is_active,
                                   updated_at=datetime('now')
           WHERE id=:id""", payload)
    conn.commit()
    row = conn.execute("SELECT * FROM legal_entity WHERE id = ?", (entity_id,)).fetchone()
    return 200, _row_to_dict(row)


def delete_legal_entity(ctx):
    entity_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM property WHERE legal_entity_id = ?",
                     (entity_id,)).fetchone()["n"]
    if n:
        raise ApiError(
            "This company still owns %d propert%s. Reassign them first."
            % (n, "y" if n == 1 else "ies"), 409)
    conn.execute("DELETE FROM legal_entity WHERE id = ?", (entity_id,))
    conn.commit()
    return 200, {"deleted": entity_id}


def delete_sbu(ctx):
    sbu_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM property WHERE sbu_id = ?",
                     (sbu_id,)).fetchone()["n"]
    if n:
        raise ApiError(
            "This property type still has %d propert%s. Move them to another type first."
            % (n, "y" if n == 1 else "ies"), 409)
    conn.execute("DELETE FROM sbu WHERE id = ?", (sbu_id,))
    conn.commit()
    return 200, {"deleted": sbu_id}


# --- locations (for the property form) --------------------------------------

def list_locations(ctx):
    """Slim list for the property form's location picker.

    The full master sheet lives at /api/masters/location; this returns only what
    the picker needs, with each location's primary code.
    """
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT l.id, l.name, l.city, l.district, l.province,
                  l.latitude, l.longitude, l.is_active,
                  (SELECT lc.code FROM location_code lc
                    WHERE lc.location_id = l.id AND lc.is_active = 1
                    ORDER BY lc.code LIMIT 1) AS code,
                  (SELECT COUNT(*) FROM property p WHERE p.location_id = l.id)
                      AS property_count
           FROM location l ORDER BY l.name"""
    ).fetchall()
    return 200, [_row_to_dict(r) for r in rows]


# --- properties -------------------------------------------------------------

_PROPERTY_SELECT = """
    SELECT p.*, s.code AS sbu_code, s.name AS sbu_name, s.color AS sbu_color,
           s.sector AS sbu_sector, s.cost_centre AS sbu_cost_centre,
           e.short_code AS entity_code, e.name AS entity_name,
           loc.name AS location_name,
           (SELECT lc.code FROM location_code lc
             WHERE lc.location_id = loc.id AND lc.is_active = 1
             ORDER BY lc.code LIMIT 1) AS location_code,
           (SELECT COUNT(*) FROM document d WHERE d.property_id = p.id) AS document_count,
           EXISTS (SELECT 1 FROM document d WHERE d.property_id = p.id
                   AND d.doc_type IN ('DEED', 'TITLE_CERTIFICATE')) AS has_deed,
           -- Newest uploaded photograph, used as the card cover when present.
           (SELECT d.id FROM document d
             WHERE d.property_id = p.id AND d.doc_type = 'PHOTOGRAPH'
               AND d.stored_name IS NOT NULL AND d.mime_type LIKE 'image/%'
             ORDER BY d.id DESC LIMIT 1) AS cover_document_id
    FROM property p
    JOIN sbu s ON s.id = p.sbu_id
    LEFT JOIN legal_entity e ON e.id = p.legal_entity_id
    LEFT JOIN location loc ON loc.id = p.location_id
"""


# The 3 / 6 / 9 / 12-month reminder ladder, as conditions on a document's expiry
# date; the same edges the renewal pipeline chart counts with.
_RENEWAL_BUCKETS = {
    "expired": "dr.expiry_date < date('now')",
    "m3": "dr.expiry_date >= date('now') AND dr.expiry_date <= date('now', '+3 months')",
    "m6": "dr.expiry_date > date('now', '+3 months') AND dr.expiry_date <= date('now', '+6 months')",
    "m9": "dr.expiry_date > date('now', '+6 months') AND dr.expiry_date <= date('now', '+9 months')",
    "m12": "dr.expiry_date > date('now', '+9 months') AND dr.expiry_date <= date('now', '+12 months')",
    "later": "dr.expiry_date > date('now', '+12 months')",
}


def _property_filters(q):
    """Build the WHERE clauses shared by the property list and the dashboard.

    Every condition refers only to `p.`, so the same fragment can be dropped into
    any query that selects FROM property p.
    """
    where, params = [], []

    if q.get("sbu_id"):
        ids = [int(x) for x in q["sbu_id"].split(",") if x.strip().isdigit()]
        if ids:
            where.append("p.sbu_id IN (%s)" % ",".join("?" * len(ids)))
            params.extend(ids)
    if q.get("legal_entity_id"):
        if q["legal_entity_id"] == "none":
            where.append("p.legal_entity_id IS NULL")
        elif q["legal_entity_id"].isdigit():
            where.append("p.legal_entity_id = ?")
            params.append(int(q["legal_entity_id"]))
    if q.get("location_id"):
        if q["location_id"] == "none":
            where.append("p.location_id IS NULL")
        elif q["location_id"].isdigit():
            where.append("p.location_id = ?")
            params.append(int(q["location_id"]))
    if q.get("district"):
        where.append("p.district = ?")
        params.append(q["district"])
    if q.get("province"):
        where.append("p.province = ?")
        params.append(q["province"])
    if q.get("status"):
        where.append("p.status = ?")
        params.append(q["status"])
    if q.get("ownership_type"):
        where.append("p.ownership_type = ?")
        params.append(q["ownership_type"])
    if q.get("has_deed") in ("0", "1"):
        where.append(("" if q["has_deed"] == "1" else "NOT ") +
                     """EXISTS (SELECT 1 FROM document dd WHERE dd.property_id = p.id
                                AND dd.doc_type IN ('DEED', 'TITLE_CERTIFICATE'))""")
    if q.get("property_type"):
        where.append("p.property_type = ?")
        params.append(q["property_type"])
    # Properties holding at least one document of a type (dashboard cross-filter).
    if q.get("has_doc_type"):
        where.append("EXISTS (SELECT 1 FROM document dt WHERE dt.property_id = p.id AND dt.doc_type = ?)")
        params.append(q["has_doc_type"])
    # Properties with a document in one bucket of the renewal ladder.
    if q.get("has_renewal") in _RENEWAL_BUCKETS:
        where.append("EXISTS (SELECT 1 FROM document dr WHERE dr.property_id = p.id AND dr.expiry_date IS NOT NULL AND %s)"
                     % _RENEWAL_BUCKETS[q["has_renewal"]])
    if q.get("q"):
        term = "%" + q["q"].strip() + "%"
        where.append("""(p.name LIKE ? OR p.property_code LIKE ? OR p.city LIKE ?
                         OR p.address_line1 LIKE ? OR p.district LIKE ?
                         OR p.assessment_no LIKE ? OR p.current_use LIKE ?)""")
        params.extend([term] * 7)

    return where, params


def list_properties(ctx):
    conn = db.get_conn()
    where, params = _property_filters(ctx.query)
    sql = _PROPERTY_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.name, p.property_code"
    rows = conn.execute(sql, params).fetchall()
    return 200, [_row_to_dict(r) for r in rows]


def get_property(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    row = conn.execute(_PROPERTY_SELECT + " WHERE p.id = ?", (pid,)).fetchone()
    if row is None:
        raise ApiError("Property not found.", 404)
    data = _row_to_dict(row)
    data["documents"] = [_row_to_dict(d) for d in conn.execute(
        "SELECT * FROM document WHERE property_id = ? ORDER BY doc_type, issue_date DESC",
        (pid,))]
    return 200, data


def _property_payload(ctx, conn):
    data = ctx.json()

    name = _clean_str(data.get("name"))
    if not name:
        raise ApiError("Property name is required.", field="name")

    try:
        sbu_id = int(data.get("sbu_id"))
    except (TypeError, ValueError):
        raise ApiError("Please choose a property type.", field="sbu_id")
    if not conn.execute("SELECT 1 FROM sbu WHERE id = ?", (sbu_id,)).fetchone():
        raise ApiError("The selected property type does not exist.", field="sbu_id")

    # Optional: a property leased or rented IN is owned by an outside landlord,
    # who belongs on the lease document rather than in the group company master.
    entity_id = data.get("legal_entity_id")
    if entity_id in ("", None):
        entity_id = None
    else:
        try:
            entity_id = int(entity_id)
        except (TypeError, ValueError):
            raise ApiError("Owning company is not valid.", field="legal_entity_id")
        if not conn.execute("SELECT 1 FROM legal_entity WHERE id = ?",
                            (entity_id,)).fetchone():
            raise ApiError("The selected owning company does not exist.",
                           field="legal_entity_id")

    # Optional link to the location master. Free-text address lines stay for the
    # street detail; the location is the canonical place.
    location_id = data.get("location_id")
    if location_id in ("", None):
        location_id = None
    else:
        try:
            location_id = int(location_id)
        except (TypeError, ValueError):
            raise ApiError("Location is not valid.", field="location_id")
        if not conn.execute("SELECT 1 FROM location WHERE id = ?",
                            (location_id,)).fetchone():
            raise ApiError("The selected location does not exist.", field="location_id")

    lat = _as_float(data.get("latitude"), "Latitude", "latitude")
    lng = _as_float(data.get("longitude"), "Longitude", "longitude")
    ok, message = srilanka.coordinates_in_sri_lanka(lat, lng)
    if not ok:
        raise ApiError(message, field="latitude")

    district = _clean_str(data.get("district"))
    if district and district not in srilanka.DISTRICT_BY_NAME:
        raise ApiError("'%s' is not a Sri Lankan district." % district, field="district")
    province = srilanka.DISTRICT_BY_NAME[district]["province"] if district else \
        _clean_str(data.get("province"))

    payload = {
        "name": name,
        "sbu_id": sbu_id,
        "legal_entity_id": entity_id,
        "location_id": location_id,
        "latitude": lat,
        "longitude": lng,
        "property_type": _check_enum(data.get("property_type"),
                                     srilanka.PROPERTY_TYPES, "Property type", "LAND"),
        "ownership_type": _check_enum(data.get("ownership_type"),
                                      srilanka.OWNERSHIP_TYPES, "Ownership", "FREEHOLD"),
        "status": _check_enum(data.get("status"),
                              srilanka.PROPERTY_STATUSES, "Status", "ACTIVE"),
        "extent_unit": _check_enum(data.get("extent_unit"),
                                   srilanka.EXTENT_UNITS, "Extent unit", "PERCH"),
        "district": district,
        "province": province,
        "extent_value": _as_float(data.get("extent_value"), "Land extent", "extent_value"),
        "building_area_value": _as_float(data.get("building_area_value"), "Building area", "building_area_value"),
        "acquisition_cost": _as_float(data.get("acquisition_cost"), "Acquisition cost", "acquisition_cost"),
        "current_value": _as_float(data.get("current_value"), "Current value", "current_value"),
        "acquisition_date": _as_date(data.get("acquisition_date"), "Acquisition date", "acquisition_date"),
        "currency": _clean_str(data.get("currency")) or "LKR",
    }
    # Building area in its own unit (the land unit unless chosen otherwise). A
    # client that still sends only building_area_sqft is read as square feet.
    if payload["building_area_value"] is None and data.get("building_area_value") in (None, "") \
            and data.get("building_area_sqft") not in (None, ""):
        payload["building_area_value"] = _as_float(data.get("building_area_sqft"), "Building area",
                                                   "building_area_sqft")
        payload["building_area_unit"] = "SQ_FT"
    else:
        payload["building_area_unit"] = _check_enum(
            data.get("building_area_unit"), srilanka.EXTENT_UNITS, "Building area unit",
            payload["extent_unit"])
    for key, label in (("extent_value", "Land extent"), ("building_area_value", "Building area")):
        if payload[key] is not None and payload[key] < 0:
            raise ApiError("%s cannot be negative." % label, field=key)
    # Both areas, also in square feet, so every property compares on one scale.
    payload["extent_sqft"] = srilanka.to_sqft(payload["extent_value"], payload["extent_unit"])
    payload["building_area_sqft"] = srilanka.to_sqft(payload["building_area_value"],
                                                     payload["building_area_unit"])
    for field in ("address_line1", "address_line2", "city", "postal_code",
                  "assessment_no", "plan_no", "lot_no", "current_use",
                  "custodian", "contact_phone", "notes"):
        payload[field] = _clean_str(data.get(field))
    return payload, _clean_str(data.get("property_code"))


def create_property(ctx):
    conn = db.get_conn()
    payload, code = _property_payload(ctx, conn)
    payload["property_code"] = code.upper() if code else _next_property_code(conn, payload["sbu_id"])
    if conn.execute("SELECT 1 FROM property WHERE property_code = ?",
                    (payload["property_code"],)).fetchone():
        raise ApiError("Property code '%s' is already in use." % payload["property_code"],
                       409, "property_code")

    columns = ["property_code", "sbu_id", "legal_entity_id", "location_id",
               "latitude", "longitude"] + PROPERTY_FIELDS
    cur = conn.execute(
        "INSERT INTO property (%s) VALUES (%s)"
        % (", ".join(columns), ", ".join(":" + c for c in columns)), payload)
    conn.commit()
    row = conn.execute(_PROPERTY_SELECT + " WHERE p.id = ?", (cur.lastrowid,)).fetchone()
    return 201, _row_to_dict(row)


def update_property(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    existing = conn.execute("SELECT * FROM property WHERE id = ?", (pid,)).fetchone()
    if existing is None:
        raise ApiError("Property not found.", 404)

    payload, code = _property_payload(ctx, conn)
    payload["property_code"] = code.upper() if code else existing["property_code"]
    clash = conn.execute("SELECT 1 FROM property WHERE property_code = ? AND id <> ?",
                         (payload["property_code"], pid)).fetchone()
    if clash:
        raise ApiError("Property code '%s' is already in use." % payload["property_code"],
                       409, "property_code")
    payload["id"] = pid

    columns = ["property_code", "sbu_id", "legal_entity_id", "location_id",
               "latitude", "longitude"] + PROPERTY_FIELDS
    conn.execute(
        "UPDATE property SET %s, updated_at = datetime('now') WHERE id = :id"
        % ", ".join("%s = :%s" % (c, c) for c in columns), payload)
    conn.commit()
    row = conn.execute(_PROPERTY_SELECT + " WHERE p.id = ?", (pid,)).fetchone()
    return 200, _row_to_dict(row)


def delete_property(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    docs = conn.execute("SELECT stored_name FROM document WHERE property_id = ?",
                        (pid,)).fetchall()
    conn.execute("DELETE FROM document WHERE property_id = ?", (pid,))
    conn.execute("DELETE FROM property WHERE id = ?", (pid,))
    conn.commit()
    for d in docs:
        _remove_stored_file(d["stored_name"])
    return 200, {"deleted": pid}


# --- documents --------------------------------------------------------------

def _remove_stored_file(stored_name):
    if not stored_name:
        return
    path = os.path.join(db.UPLOAD_DIR, os.path.basename(stored_name))
    try:
        os.remove(path)
    except OSError:
        pass


def list_documents(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    rows = conn.execute(
        "SELECT * FROM document WHERE property_id = ? ORDER BY doc_type, issue_date DESC",
        (pid,)).fetchall()
    return 200, [_row_to_dict(r) for r in rows]


def create_document(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    if not conn.execute("SELECT 1 FROM property WHERE id = ?", (pid,)).fetchone():
        raise ApiError("Property not found.", 404)

    fields, upload = ctx.form()

    # 1. Check every field before anything touches the disk, so a rejected
    #    upload can never leave an orphaned file behind.
    doc_type = _check_enum(fields.get("doc_type"), srilanka.DOCUMENT_TYPES,
                           "Document type", "OTHER")
    # Fall back to the document type label so a row is never nameless.
    title = _clean_str(fields.get("title")) or dict(srilanka.DOCUMENT_TYPES)[doc_type]
    payload = {
        "property_id": pid,
        "doc_type": doc_type,
        "title": title,
        "reference_no": _clean_str(fields.get("reference_no")),
        "issue_date": _as_date(fields.get("issue_date"), "Issue date", "issue_date"),
        "expiry_date": _as_date(fields.get("expiry_date"), "Expiry date", "expiry_date"),
        "counterparty": _clean_str(fields.get("counterparty")),
        "amount": _as_float(fields.get("amount"), "Amount", "amount"),
        "currency": _clean_str(fields.get("currency")) or "LKR",
        "notes": _clean_str(fields.get("notes")),
        "file_name": None,
        "stored_name": None,
        "mime_type": None,
        "size_bytes": None,
    }
    if payload["issue_date"] and payload["expiry_date"] \
            and payload["expiry_date"] < payload["issue_date"]:
        raise ApiError("Expiry date cannot be before the issue date.", field="expiry_date")

    ext = None
    if upload is not None and upload.is_file:
        file_name = os.path.basename(upload.filename.replace("\\", "/"))
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ApiError(
                "File type '%s' is not allowed. Allowed: %s"
                % (ext or "(none)", ", ".join(sorted(ALLOWED_EXTENSIONS))), field="file")
        if len(upload.data) > MAX_UPLOAD_BYTES:
            raise ApiError("File is larger than the %d MB limit."
                           % (MAX_UPLOAD_BYTES // (1024 * 1024)), 413, "file")
        if not upload.data:
            raise ApiError("The uploaded file is empty.", field="file")
        payload.update({"file_name": file_name, "mime_type": upload.content_type,
                        "size_bytes": len(upload.data)})

    # 2. Everything is valid: write the file, then the record. If the record
    #    fails, take the file back out.
    if ext is not None:
        payload["stored_name"] = "%s%s" % (uuid.uuid4().hex, ext)
        with open(os.path.join(db.UPLOAD_DIR, payload["stored_name"]), "wb") as fh:
            fh.write(upload.data)

    columns = ["property_id", "file_name", "stored_name", "mime_type",
               "size_bytes"] + DOCUMENT_FIELDS
    try:
        cur = conn.execute(
            "INSERT INTO document (%s) VALUES (%s)"
            % (", ".join(columns), ", ".join(":" + c for c in columns)), payload)
        conn.commit()
    except Exception:
        conn.rollback()
        _remove_stored_file(payload["stored_name"])
        raise
    row = conn.execute("SELECT * FROM document WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, _row_to_dict(row)


# --- the documents register -------------------------------------------------

_DOC_STATUS = {
    "file":     "d.stored_name IS NOT NULL",
    "nofile":   "d.stored_name IS NULL",
    "expiring": "d.expiry_date >= date('now') AND d.expiry_date <= date('now', '+180 day')",
    "expired":  "d.expiry_date < date('now')",
}

_DOC_SORT = {
    "newest":   "d.id DESC",
    "expiry":   "d.expiry_date IS NULL, d.expiry_date ASC, d.id DESC",
    "title":    "d.title COLLATE NOCASE ASC",
    "property": "p.property_code ASC, d.doc_type ASC",
    "sbu":      "s.name COLLATE NOCASE ASC, p.property_code ASC",
}


def list_all_documents(ctx):
    """Every document, with its property and property type.

    Scoped by the same property filters as the portfolio (so the Documents
    card and this list agree), plus document filters: type, status, and a
    search that matches the document or the property it belongs to.
    """
    conn = db.get_conn()
    q = dict(ctx.query)
    text = (q.pop("q", "") or "").strip()
    where, params = _property_filters(q)

    if text:
        term = "%" + text + "%"
        where.append("""(d.title LIKE ? OR d.reference_no LIKE ? OR d.counterparty LIKE ?
                         OR d.notes LIKE ? OR d.file_name LIKE ?
                         OR p.name LIKE ? OR p.property_code LIKE ? OR p.city LIKE ?
                         OR p.district LIKE ? OR s.name LIKE ? OR s.code LIKE ?)""")
        params.extend([term] * 11)
    if q.get("doc_type"):
        where.append("d.doc_type = ?")
        params.append(q["doc_type"])

    base = """FROM document d
              JOIN property p ON p.id = d.property_id
              JOIN sbu s ON s.id = p.sbu_id
              LEFT JOIN location loc ON loc.id = p.location_id"""

    # Tab counts ignore the status filter, so each tab shows what it would hold.
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    counts = {"all": conn.execute("SELECT COUNT(*) AS n " + base + clause, params).fetchone()["n"]}
    for key, condition in _DOC_STATUS.items():
        counts[key] = conn.execute(
            "SELECT COUNT(*) AS n " + base + " WHERE " + " AND ".join(where + [condition]),
            params).fetchone()["n"]

    # `doc_status`, not `status`: plain `status` is the property-status filter.
    status = q.get("doc_status")
    if status in _DOC_STATUS:
        where.append(_DOC_STATUS[status])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = _DOC_SORT.get(q.get("sort"), _DOC_SORT["newest"])
    rows = conn.execute(
        """SELECT d.*, p.property_code, p.name AS property_name, p.city, p.district,
                  s.id AS sbu_id, s.code AS sbu_code, s.name AS sbu_name, s.color AS sbu_color,
                  loc.name AS location_name
           """ + base + clause + " ORDER BY " + order, params).fetchall()
    return 200, {"documents": [_row_to_dict(r) for r in rows], "counts": counts,
                 "properties": len({r["property_id"] for r in rows})}


def get_document(ctx):
    """One document with its property and property type, for the document panel."""
    conn = db.get_conn()
    doc_id = int(ctx.match.group("id"))
    row = conn.execute(
        """SELECT d.*, p.property_code, p.name AS property_name, p.city, p.district,
                  s.id AS sbu_id, s.code AS sbu_code, s.name AS sbu_name, s.color AS sbu_color,
                  loc.name AS location_name
           FROM document d
           JOIN property p ON p.id = d.property_id
           JOIN sbu s ON s.id = p.sbu_id
           LEFT JOIN location loc ON loc.id = p.location_id
           WHERE d.id = ?""", (doc_id,)).fetchone()
    if row is None:
        raise ApiError("Document not found.", 404)
    return 200, _row_to_dict(row)


def delete_document(ctx):
    conn = db.get_conn()
    doc_id = int(ctx.match.group("id"))
    row = conn.execute("SELECT * FROM document WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise ApiError("Document not found.", 404)
    conn.execute("DELETE FROM document WHERE id = ?", (doc_id,))
    conn.commit()
    _remove_stored_file(row["stored_name"])
    return 200, {"deleted": doc_id}


def download_document(ctx):
    """Returns a raw-file response tuple handled specially by the server."""
    conn = db.get_conn()
    doc_id = int(ctx.match.group("id"))
    row = conn.execute("SELECT * FROM document WHERE id = ?", (doc_id,)).fetchone()
    if row is None or not row["stored_name"]:
        raise ApiError("No file attached to this document.", 404)
    path = os.path.join(db.UPLOAD_DIR, os.path.basename(row["stored_name"]))
    if not os.path.exists(path):
        raise ApiError("The stored file is missing from disk.", 410)
    with open(path, "rb") as fh:
        data = fh.read()
    return 200, {
        "__raw__": True,
        "body": data,
        "content_type": row["mime_type"] or "application/octet-stream",
        "filename": row["file_name"] or row["stored_name"],
        "inline": ctx.query.get("disposition") != "attachment",
    }


# --- dashboard & export -----------------------------------------------------

def get_stats(ctx):
    """Dashboard figures, scoped to the same filters as the property list.

    With no filters this covers the whole register; with a search or a filter
    active every figure describes only the matching properties, so the dashboard
    never disagrees with the list next to it.
    """
    conn = db.get_conn()
    where, params = _property_filters(ctx.query)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    # The set every figure below is computed over.
    subset = "SELECT p.* FROM property p" + clause

    def run(sql, extra=()):
        return conn.execute(sql, list(params) + list(extra)).fetchall()

    by_sbu = [_row_to_dict(r) for r in run(
        """SELECT s.id, s.code, s.name, s.color,
                  COUNT(f.id) AS property_count,
                  COALESCE(SUM(CASE WHEN f.extent_unit='ACRE' THEN f.extent_value*160
                                    WHEN f.extent_unit='ROOD' THEN f.extent_value*40
                                    WHEN f.extent_unit='HECTARE' THEN f.extent_value*395.37
                                    WHEN f.extent_unit='SQ_M' THEN f.extent_value*0.0395369
                                    WHEN f.extent_unit='SQ_FT' THEN f.extent_value/272.25
                                    ELSE f.extent_value END), 0) AS extent_perches,
                  COALESCE(SUM(f.extent_sqft), 0) AS land_sqft,
                  COALESCE(SUM(f.building_area_sqft), 0) AS floor_sqft
           FROM sbu s LEFT JOIN (%s) f ON f.sbu_id = s.id
           GROUP BY s.id ORDER BY property_count DESC, s.name""" % subset)]
    if where:
        # Under a filter, business units with nothing matching are just noise.
        by_sbu = [row for row in by_sbu if row["property_count"]]

    by_status = [_row_to_dict(r) for r in run(
        "SELECT status, COUNT(*) AS n FROM (%s) GROUP BY status ORDER BY n DESC"
        % subset)]
    by_tenure = [_row_to_dict(r) for r in run(
        "SELECT ownership_type, COUNT(*) AS n FROM (%s) GROUP BY ownership_type ORDER BY n DESC"
        % subset)]
    by_type = [_row_to_dict(r) for r in run(
        "SELECT property_type, COUNT(*) AS n FROM (%s) GROUP BY property_type ORDER BY n DESC"
        % subset)]
    # Every province, including those with nothing in them: gaps are information.
    province_counts = {r["province"]: r["n"] for r in run(
        "SELECT province, COUNT(*) AS n FROM (%s) WHERE province IS NOT NULL GROUP BY province"
        % subset)}
    by_province = [{"province": name, "n": province_counts.get(name, 0)}
                   for name in srilanka.PROVINCE_NAMES]
    by_doc_type = [_row_to_dict(r) for r in run(
        """SELECT d.doc_type, COUNT(*) AS n FROM document d
           WHERE d.property_id IN (SELECT id FROM (%s))
           GROUP BY d.doc_type ORDER BY n DESC""" % subset)]
    # Renewal pipeline on the blueprint's 3 / 6 / 9 / 12-month reminder ladder.
    renewal_counts = {r["bucket"]: r["n"] for r in run(
        """SELECT CASE
                    WHEN d.expiry_date <  date('now')              THEN 'expired'
                    WHEN d.expiry_date <= date('now', '+3 months')  THEN 'm3'
                    WHEN d.expiry_date <= date('now', '+6 months')  THEN 'm6'
                    WHEN d.expiry_date <= date('now', '+9 months')  THEN 'm9'
                    WHEN d.expiry_date <= date('now', '+12 months') THEN 'm12'
                    ELSE 'later' END AS bucket,
                  COUNT(*) AS n
           FROM document d
           WHERE d.expiry_date IS NOT NULL
             AND d.property_id IN (SELECT id FROM (%s))
           GROUP BY bucket""" % subset)}
    renewals = [{"bucket": key, "n": renewal_counts.get(key, 0)}
                for key in ("expired", "m3", "m6", "m9", "m12", "later")]
    by_district = [_row_to_dict(r) for r in run(
        """SELECT district, province, COUNT(*) AS n FROM (%s)
           WHERE district IS NOT NULL GROUP BY district ORDER BY n DESC""" % subset)]
    by_entity = [_row_to_dict(r) for r in run(
        """SELECT COALESCE(CAST(e.id AS TEXT), 'none') AS id,
                  COALESCE(e.short_code, 'Not recorded') AS short_code,
                  COALESCE(e.name, 'No group company (leased / rented in)') AS name,
                  COUNT(f.id) AS n
           FROM (%s) f LEFT JOIN legal_entity e ON e.id = f.legal_entity_id
           GROUP BY f.legal_entity_id ORDER BY n DESC""" % subset)]

    # Owning company x business unit: who owns what each unit occupies.
    by_entity_sbu = [_row_to_dict(r) for r in run(
        """SELECT COALESCE(CAST(f.legal_entity_id AS TEXT), 'none') AS entity_id,
                  f.sbu_id, COUNT(*) AS n
           FROM (%s) f GROUP BY f.legal_entity_id, f.sbu_id""" % subset)]

    # Each figure is its own query: the filtered subset appears once per
    # statement, so the bound parameters line up exactly.
    def scalar(sql):
        return run(sql)[0]["n"]

    totals = {
        "properties": scalar("SELECT COUNT(*) AS n FROM (%s)" % subset),
        "sbus": scalar("SELECT COUNT(DISTINCT sbu_id) AS n FROM (%s)" % subset),
        "documents": scalar(
            """SELECT COUNT(*) AS n FROM document d
               WHERE d.property_id IN (SELECT id FROM (%s))""" % subset),
        "files": scalar(
            """SELECT COUNT(*) AS n FROM document d
               WHERE d.stored_name IS NOT NULL
                 AND d.property_id IN (SELECT id FROM (%s))""" % subset),
        # Land and floor area, summed in square feet, with how many properties
        # actually have each recorded (a total over half the register says so).
        "land_sqft": scalar("SELECT COALESCE(SUM(extent_sqft), 0) AS n FROM (%s)" % subset),
        "floor_sqft": scalar("SELECT COALESCE(SUM(building_area_sqft), 0) AS n FROM (%s)" % subset),
        "with_land": scalar("SELECT COUNT(*) AS n FROM (%s) WHERE extent_sqft > 0" % subset),
        "with_floor": scalar("SELECT COUNT(*) AS n FROM (%s) WHERE building_area_sqft > 0" % subset),
        "without_deed": scalar(
            """SELECT COUNT(*) AS n FROM (%s) f WHERE NOT EXISTS
                 (SELECT 1 FROM document d WHERE d.property_id = f.id
                  AND d.doc_type IN ('DEED','TITLE_CERTIFICATE'))""" % subset),
    }

    expiring = [_row_to_dict(r) for r in run(
        """SELECT d.id, d.title, d.doc_type, d.expiry_date, d.counterparty,
                  f.id AS property_id, f.property_code, f.name AS property_name,
                  s.code AS sbu_code, s.name AS sbu_name, s.color AS sbu_color
           FROM document d JOIN (%s) f ON f.id = d.property_id
           LEFT JOIN sbu s ON s.id = f.sbu_id
           WHERE d.expiry_date IS NOT NULL
             AND d.expiry_date >= date('now')
             AND d.expiry_date <= date('now', '+180 day')
           ORDER BY d.expiry_date""" % subset)]

    # So the front end can say "showing 2 of 13".
    totals["allProperties"] = conn.execute(
        "SELECT COUNT(*) AS n FROM property").fetchone()["n"]

    return 200, {"totals": totals, "bySbu": by_sbu, "byStatus": by_status,
                 "byDistrict": by_district, "byEntity": by_entity,
                 "byTenure": by_tenure, "byType": by_type, "byProvince": by_province,
                 "byDocType": by_doc_type, "renewals": renewals, "byEntitySbu": by_entity_sbu,
                 "expiringSoon": expiring, "filtered": bool(where)}


def export_properties_csv(ctx):
    conn = db.get_conn()
    rows = conn.execute(_PROPERTY_SELECT + " ORDER BY COALESCE(s.sort_order, 500), s.name, p.property_code").fetchall()
    buf = io.StringIO()
    headers = ["property_code", "name", "sbu_code", "sbu_name",
               "entity_code", "entity_name",
               "location_code", "location_name", "property_type",
               "ownership_type", "status", "address_line1", "address_line2", "city",
               "district", "province", "postal_code", "latitude", "longitude",
               "extent_value", "extent_unit", "extent_sqft",
               "building_area_value", "building_area_unit", "building_area_sqft", "assessment_no",
               "plan_no", "lot_no", "acquisition_date", "acquisition_cost",
               "current_value", "currency", "current_use", "custodian",
               "contact_phone", "document_count", "notes"]
    writer = csv.writer(buf)
    # Column titles as the app names them: the `sbu` table holds property types,
    # and the `property_type` column holds the structure.
    titles = {"sbu_code": "property_type_code", "sbu_name": "property_type",
              "property_type": "structure"}
    writer.writerow([titles.get(h, h) for h in headers])
    for r in rows:
        writer.writerow([r[h] if r[h] is not None else "" for h in headers])
    return 200, {
        "__raw__": True,
        "body": buf.getvalue().encode("utf-8-sig"),
        "content_type": "text/csv; charset=utf-8",
        "filename": "properties-%s.csv" % datetime.date.today().isoformat(),
        "inline": False,
    }


ROUTES = [
    ("GET",    r"^/api/reference$",                      get_reference),
    ("GET",    r"^/api/sbus$",                           list_sbus),
    ("POST",   r"^/api/sbus$",                           create_sbu),
    ("PUT",    r"^/api/sbus/(?P<id>\d+)$",               update_sbu),
    ("DELETE", r"^/api/sbus/(?P<id>\d+)$",               delete_sbu),
    ("GET",    r"^/api/legal-entities$",                 list_legal_entities),
    ("POST",   r"^/api/legal-entities$",                 create_legal_entity),
    ("PUT",    r"^/api/legal-entities/(?P<id>\d+)$",     update_legal_entity),
    ("DELETE", r"^/api/legal-entities/(?P<id>\d+)$",     delete_legal_entity),
    ("GET",    r"^/api/locations$",                      list_locations),
    ("GET",    r"^/api/properties$",                     list_properties),
    ("POST",   r"^/api/properties$",                     create_property),
    ("GET",    r"^/api/properties/(?P<id>\d+)$",         get_property),
    ("PUT",    r"^/api/properties/(?P<id>\d+)$",         update_property),
    ("DELETE", r"^/api/properties/(?P<id>\d+)$",         delete_property),
    ("GET",    r"^/api/properties/(?P<id>\d+)/documents$", list_documents),
    ("POST",   r"^/api/properties/(?P<id>\d+)/documents$", create_document),
    ("GET",    r"^/api/documents$",                      list_all_documents),
    ("GET",    r"^/api/documents/(?P<id>\d+)/file$",     download_document),
    ("GET",    r"^/api/documents/(?P<id>\d+)$",          get_document),
    ("DELETE", r"^/api/documents/(?P<id>\d+)$",          delete_document),
    ("GET",    r"^/api/stats$",                          get_stats),
    ("GET",    r"^/api/export/properties.csv$",          export_properties_csv),
]

# The Master sheets module registers its own routes; nothing above changes.
ROUTES = ROUTES + masters.ROUTES

# Bulk upload: the Excel template and its importer.
from . import bulk  # noqa: E402  (bulk reads helpers above at request time)
ROUTES = ROUTES + bulk.ROUTES

COMPILED_ROUTES = [(method, re.compile(pattern), handler)
                   for method, pattern, handler in ROUTES]
