"""Master sheets module.

One registry drives everything: the sheet list, the grid columns, validation and
the add/edit form. Adding a new master sheet means adding one entry to MASTERS --
no new endpoints, no new screens.

Two kinds of sheet:
  * editable -- backed by a table, full add/edit/delete
  * system   -- fixed lists compiled into the application (districts, document
                types and so on), shown read-only so people can see exactly what
                the drop-downs offer

Nothing here touches the property register, documents, map or dashboard.
"""

import re

from . import db, srilanka
from .errors import ApiError

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# --- sheet definitions ------------------------------------------------------

def _static(rows, columns):
    return {"rows": rows, "columns": columns}


def _option_rows(pairs):
    return [{"code": code, "label": label} for code, label in pairs]


CODE_LABEL_COLUMNS = [
    {"name": "code", "label": "Code", "type": "text"},
    {"name": "label", "label": "Description", "type": "text"},
]

MASTERS = [
    {
        "key": "location",
        "label": "Locations",
        "group": "Editable",
        "description": "Every place the group operates. Holding these centrally keeps "
                       "one town spelled one way across the whole register.",
        "editable": True,
        "table": "location",
        "order_by": "name",
        "display": "name",
        "blocked_by": [("location_code", "location_id", "location code"),
                       ("property", "location_id", "property")],
        "columns": [
            {"name": "name", "label": "Location name", "type": "text",
             "required": True, "unique": True, "maxlength": 120},
            {"name": "city", "label": "City / town", "type": "text", "maxlength": 80},
            {"name": "district", "label": "District", "type": "enum",
             "options": srilanka.DISTRICT_NAMES, "fills": "province"},
            {"name": "province", "label": "Province", "type": "text",
             "readonly": True, "hint": "set from the district"},
            {"name": "latitude", "label": "Latitude", "type": "number"},
            {"name": "longitude", "label": "Longitude", "type": "number"},
            {"name": "notes", "label": "Notes", "type": "textarea", "maxlength": 500,
             "in_grid": False},
            {"name": "is_active", "label": "Active", "type": "bool", "default": 1},
        ],
    },
    {
        "key": "location_code",
        "label": "Location codes",
        "group": "Editable",
        "description": "The short code used on documents and in the property sheet. "
                       "A code is unique, so one code can never stand for two places "
                       "-- the LLKO problem the blueprint reports.",
        "editable": True,
        "table": "location_code",
        "order_by": "code",
        "display": "code",
        "columns": [
            {"name": "code", "label": "Code", "type": "text", "required": True,
             "unique": True, "maxlength": 20, "upper": True},
            {"name": "location_id", "label": "Location", "type": "ref",
             "ref": "location", "required": True},
            {"name": "description", "label": "Description", "type": "text",
             "maxlength": 200},
            {"name": "is_active", "label": "Active", "type": "bool", "default": 1},
        ],
    },
    {
        "key": "sbu",
        "label": "Business units (SBU)",
        "group": "Editable",
        "description": "The sector, business unit or department that occupies a "
                       "property and carries its costs.",
        "editable": True,
        "table": "sbu",
        "order_by": "code",
        "display": "name",
        "blocked_by": [("property", "sbu_id", "property")],
        "columns": [
            {"name": "code", "label": "Code", "type": "text", "required": True,
             "unique": True, "maxlength": 16, "upper": True},
            {"name": "name", "label": "Name", "type": "text", "required": True,
             "maxlength": 120},
            {"name": "sector", "label": "Sector", "type": "text", "maxlength": 80},
            {"name": "cost_centre", "label": "Cost centre", "type": "text",
             "maxlength": 40},
            {"name": "color", "label": "Map colour", "type": "color",
             "default": "#1f77b4"},
            {"name": "description", "label": "Description", "type": "textarea",
             "maxlength": 500, "in_grid": False},
            {"name": "is_active", "label": "Active", "type": "bool", "default": 1},
        ],
    },
    {
        "key": "legal_entity",
        "label": "Owning companies",
        "group": "Editable",
        "description": "The group company that holds title. Separate from the SBU "
                       "that occupies the property and from how it is held.",
        "editable": True,
        "table": "legal_entity",
        "order_by": "short_code",
        "display": "name",
        "blocked_by": [("property", "legal_entity_id", "property")],
        "columns": [
            {"name": "short_code", "label": "Short code", "type": "text",
             "required": True, "unique": True, "maxlength": 16, "upper": True},
            {"name": "name", "label": "Registered name", "type": "text",
             "required": True, "maxlength": 160},
            {"name": "reg_no", "label": "Registration no.", "type": "text",
             "maxlength": 40},
            {"name": "description", "label": "Notes", "type": "textarea",
             "maxlength": 500, "in_grid": False},
            {"name": "is_active", "label": "Active", "type": "bool", "default": 1},
        ],
    },

    # --- system lists (read-only in Stage 1) ---
    {
        "key": "province",
        "label": "Provinces",
        "group": "System lists",
        "description": "The nine provinces of Sri Lanka.",
        "editable": False,
        "static": _static(
            [{"province": name, "districts": len(districts)}
             for name, districts in srilanka.PROVINCES],
            [{"name": "province", "label": "Province", "type": "text"},
             {"name": "districts", "label": "Districts", "type": "number"}]),
    },
    {
        "key": "district",
        "label": "Districts",
        "group": "System lists",
        "description": "The 25 districts, each with the centroid the map uses when "
                       "you pick a district on the property form.",
        "editable": False,
        "static": _static(
            srilanka.DISTRICTS,
            [{"name": "district", "label": "District", "type": "text"},
             {"name": "province", "label": "Province", "type": "text"},
             {"name": "lat", "label": "Latitude", "type": "number"},
             {"name": "lng", "label": "Longitude", "type": "number"}]),
    },
    {
        "key": "property_type",
        "label": "Property types",
        "group": "System lists",
        "description": "Choices offered by the Property type field.",
        "editable": False,
        "static": _static(_option_rows(srilanka.PROPERTY_TYPES), CODE_LABEL_COLUMNS),
    },
    {
        "key": "ownership_type",
        "label": "Ownership / tenure types",
        "group": "System lists",
        "description": "How a property is held. Distinct from the owning company.",
        "editable": False,
        "static": _static(_option_rows(srilanka.OWNERSHIP_TYPES), CODE_LABEL_COLUMNS),
    },
    {
        "key": "property_status",
        "label": "Property statuses",
        "group": "System lists",
        "description": "Lifecycle status shown as a badge on each property.",
        "editable": False,
        "static": _static(_option_rows(srilanka.PROPERTY_STATUSES), CODE_LABEL_COLUMNS),
    },
    {
        "key": "document_type",
        "label": "Document types",
        "group": "System lists",
        "description": "Kinds of document that can be attached to a property.",
        "editable": False,
        "static": _static(_option_rows(srilanka.DOCUMENT_TYPES), CODE_LABEL_COLUMNS),
    },
    {
        "key": "extent_unit",
        "label": "Extent units",
        "group": "System lists",
        "description": "Units land extent can be recorded in.",
        "editable": False,
        "static": _static(_option_rows(srilanka.EXTENT_UNITS), CODE_LABEL_COLUMNS),
    },
]

BY_KEY = {sheet["key"]: sheet for sheet in MASTERS}


def _sheet(ctx):
    key = ctx.match.group("key")
    sheet = BY_KEY.get(key)
    if sheet is None:
        raise ApiError("Unknown master sheet '%s'." % key, 404)
    return sheet


def _summary(sheet, count):
    return {
        "key": sheet["key"],
        "label": sheet["label"],
        "group": sheet["group"],
        "description": sheet["description"],
        "editable": sheet["editable"],
        "rowCount": count,
    }


def _count(sheet):
    if not sheet["editable"]:
        return len(sheet["static"]["rows"])
    return db.get_conn().execute(
        "SELECT COUNT(*) AS n FROM %s" % sheet["table"]).fetchone()["n"]


# --- reading ----------------------------------------------------------------

def _ref_labels(ref_key):
    target = BY_KEY[ref_key]
    rows = db.get_conn().execute(
        "SELECT id, %s AS label FROM %s ORDER BY %s"
        % (target["display"], target["table"], target["order_by"])).fetchall()
    return [{"id": r["id"], "label": r["label"]} for r in rows]


def _rows_for(sheet):
    if not sheet["editable"]:
        return sheet["static"]["rows"]
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM %s ORDER BY %s" % (sheet["table"], sheet["order_by"]))]

    # Resolve foreign keys to a display label so the grid reads properly.
    for column in sheet["columns"]:
        if column["type"] != "ref":
            continue
        lookup = {item["id"]: item["label"] for item in _ref_labels(column["ref"])}
        for row in rows:
            row[column["name"] + "_label"] = lookup.get(row.get(column["name"]), "")

    # Usage counts make it obvious which rows can still be deleted.
    for table, fk, _label in sheet.get("blocked_by", []):
        counts = {r["k"]: r["n"] for r in conn.execute(
            "SELECT %s AS k, COUNT(*) AS n FROM %s GROUP BY %s" % (fk, table, fk))}
        for row in rows:
            row["_used"] = row.get("_used", 0) + counts.get(row["id"], 0)
    return rows


def list_sheets(ctx):
    return 200, [_summary(sheet, _count(sheet)) for sheet in MASTERS]


def get_sheet(ctx):
    sheet = _sheet(ctx)
    columns = sheet["static"]["columns"] if not sheet["editable"] else sheet["columns"]
    payload = _summary(sheet, _count(sheet))
    payload["columns"] = columns
    payload["rows"] = _rows_for(sheet)
    payload["refs"] = {
        column["ref"]: _ref_labels(column["ref"])
        for column in columns if column.get("type") == "ref"
    }
    return 200, payload


# --- writing ----------------------------------------------------------------

def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _validate(sheet, data, row_id=None):
    conn = db.get_conn()
    payload = {}
    for column in sheet["columns"]:
        name = column["name"]
        kind = column["type"]
        raw = data.get(name)

        if column.get("readonly"):
            # Derived server-side; never trusted from the client.
            payload[name] = None
            continue

        if kind == "bool":
            payload[name] = 1 if (raw if raw is not None else column.get("default", 1)) else 0
            continue

        if kind == "number":
            if raw in ("", None):
                payload[name] = None
            else:
                try:
                    payload[name] = float(raw)
                except (TypeError, ValueError):
                    raise ApiError("%s must be a number." % column["label"], field=name)
            continue

        if kind == "ref":
            if raw in ("", None):
                value = None
            else:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    raise ApiError("%s is not valid." % column["label"], field=name)
                target = BY_KEY[column["ref"]]
                if not conn.execute("SELECT 1 FROM %s WHERE id = ?" % target["table"],
                                    (value,)).fetchone():
                    raise ApiError("The selected %s does not exist."
                                   % column["label"].lower(), field=name)
            if value is None and column.get("required"):
                raise ApiError("%s is required." % column["label"], field=name)
            payload[name] = value
            continue

        value = _clean(raw)
        if value and column.get("upper"):
            value = value.upper()
        if value is None:
            value = column.get("default")
        if column.get("required") and not value:
            raise ApiError("%s is required." % column["label"], field=name)
        if value and column.get("maxlength") and len(value) > column["maxlength"]:
            raise ApiError("%s is longer than %d characters."
                           % (column["label"], column["maxlength"]), field=name)
        if kind == "enum" and value and value not in column["options"]:
            raise ApiError("%s is not a recognised value." % column["label"], field=name)
        if kind == "color" and value and not HEX_COLOR.match(value):
            raise ApiError("%s must be a hex colour like #1f77b4."
                           % column["label"], field=name)
        if value and column.get("unique"):
            clash = conn.execute(
                "SELECT 1 FROM %s WHERE %s = ? AND id <> ?"
                % (sheet["table"], name), (value, row_id or -1)).fetchone()
            if clash:
                raise ApiError("%s '%s' is already used on another row."
                               % (column["label"], value), 409, name)
        payload[name] = value

    # District drives province, so the client can never disagree with the master.
    for column in sheet["columns"]:
        if column.get("fills") and payload.get(column["name"]):
            info = srilanka.DISTRICT_BY_NAME.get(payload[column["name"]])
            if info:
                payload[column["fills"]] = info["province"]
    return payload


def _plural(word, n):
    if n == 1:
        return word
    return word[:-1] + "ies" if word.endswith("y") else word + "s"


def _require_editable(sheet):
    if not sheet["editable"]:
        raise ApiError("'%s' is a system list and cannot be edited here."
                       % sheet["label"], 405)


def create_row(ctx):
    sheet = _sheet(ctx)
    _require_editable(sheet)
    payload = _validate(sheet, ctx.json())
    names = list(payload.keys())
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO %s (%s) VALUES (%s)"
        % (sheet["table"], ", ".join(names), ", ".join(":" + n for n in names)),
        payload)
    conn.commit()
    row = conn.execute("SELECT * FROM %s WHERE id = ?" % sheet["table"],
                       (cur.lastrowid,)).fetchone()
    return 201, dict(row)


def update_row(ctx):
    sheet = _sheet(ctx)
    _require_editable(sheet)
    row_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM %s WHERE id = ?" % sheet["table"],
                        (row_id,)).fetchone():
        raise ApiError("Row not found.", 404)
    payload = _validate(sheet, ctx.json(), row_id)
    names = list(payload.keys())
    payload["id"] = row_id
    conn.execute(
        "UPDATE %s SET %s, updated_at = datetime('now') WHERE id = :id"
        % (sheet["table"], ", ".join("%s = :%s" % (n, n) for n in names)), payload)
    conn.commit()
    row = conn.execute("SELECT * FROM %s WHERE id = ?" % sheet["table"],
                       (row_id,)).fetchone()
    return 200, dict(row)


def delete_row(ctx):
    sheet = _sheet(ctx)
    _require_editable(sheet)
    row_id = int(ctx.match.group("id"))
    conn = db.get_conn()
    blockers = []
    for table, fk, label in sheet.get("blocked_by", []):
        n = conn.execute("SELECT COUNT(*) AS n FROM %s WHERE %s = ?" % (table, fk),
                         (row_id,)).fetchone()["n"]
        if n:
            blockers.append("%d %s" % (n, _plural(label, n)))
    if blockers:
        raise ApiError(
            "This row is still used by %s. Reassign or remove %s first."
            % (" and ".join(blockers), "that" if len(blockers) == 1 else "those"), 409)
    conn.execute("DELETE FROM %s WHERE id = ?" % sheet["table"], (row_id,))
    conn.commit()
    return 200, {"deleted": row_id}


ROUTES = [
    ("GET",    r"^/api/masters$",                                     list_sheets),
    ("GET",    r"^/api/masters/(?P<key>[a-z_]+)$",                    get_sheet),
    ("POST",   r"^/api/masters/(?P<key>[a-z_]+)$",                    create_row),
    ("PUT",    r"^/api/masters/(?P<key>[a-z_]+)/(?P<id>\d+)$",        update_row),
    ("DELETE", r"^/api/masters/(?P<key>[a-z_]+)/(?P<id>\d+)$",        delete_row),
]
