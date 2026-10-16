"""Bulk property upload: an Excel template, and an importer for it.

The template is generated from the live register, so its drop-downs always
offer the current property types, owning companies, location codes and so on.
The importer reads the filled template (.xlsx) or a CSV with the same
headings, checks every row with the same rules as the property form, and
reports row by row before anything is written. Committing imports the rows
that pass, in one transaction.

Pure standard library: an .xlsx file is a zip of XML parts, written and read
here directly.
"""

import csv
import datetime
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from . import db, srilanka
from .errors import ApiError

MAX_ROWS = 2000
MAX_FILE_BYTES = 10 * 1024 * 1024
SHEET = "Properties"

# key, heading, required, width, kind, help (shown when the cell is selected)
COLUMNS = [
    ("name", "Property name", True, 30, "text",
     "The property's name as people know it, e.g. Kandy City Showroom."),
    ("property_code", "Property code", False, 16, "code",
     "Leave blank to generate one from the property type (e.g. COMM-0004). Must be unique."),
    ("sbu", "Property type", True, 28, "list:types",
     "What the property is used for. Pick from the list."),
    ("entity", "Owning company", False, 16, "list:entities",
     "Short code of the group company holding title. Leave blank if leased or rented in."),
    ("ownership_type", "Tenure", True, 24, "list:tenures",
     "How the property is held. Pick from the list."),
    ("property_type", "Structure", False, 18, "list:structures",
     "Bare land, Land & building or Building only. Blank means Land & building."),
    ("status", "Status", False, 20, "list:statuses",
     "Blank means Active / in use."),
    ("location", "Location code", False, 14, "list:locations",
     "Code from the location master. If coordinates are blank, the property is placed at this location."),
    ("address_line1", "Address line 1", False, 28, "text", "Street address."),
    ("address_line2", "Address line 2", False, 20, "text", "Optional second address line."),
    ("city", "City / town", False, 16, "text", "City or town."),
    ("district", "District", False, 16, "list:districts",
     "One of the 25 districts. The province is filled in for you."),
    ("postal_code", "Postal code", False, 12, "code", "Postal code."),
    ("latitude", "Latitude", True, 12, "lat",
     "Decimal degrees, e.g. 7.293600. Can be left blank if a location code with coordinates is given."),
    ("longitude", "Longitude", True, 12, "lng",
     "Decimal degrees, e.g. 80.635100. Can be left blank if a location code with coordinates is given."),
    ("extent_value", "Land extent", False, 12, "number", "Land area as a number, e.g. 42.5."),
    ("extent_unit", "Land unit", False, 15, "list:units", "Unit of the land extent. Blank means Perches."),
    ("building_area_value", "Building area", False, 13, "number", "Floor area as a number."),
    ("building_area_unit", "Building unit", False, 15, "list:units",
     "Unit of the building area. Blank means the same as the land unit."),
    ("assessment_no", "Assessment no.", False, 16, "code", "Local authority assessment number."),
    ("plan_no", "Survey plan no.", False, 16, "code", "Survey plan number."),
    ("lot_no", "Lot no.", False, 10, "code", "Lot number on the plan."),
    ("acquisition_date", "Acquisition date", False, 15, "date",
     "Date acquired, e.g. 2019-03-31 or 31/03/2019 (day first). An Excel date works too."),
    ("acquisition_cost", "Acquisition cost", False, 16, "number", "Amount paid, e.g. 12500000."),
    ("current_value", "Current value", False, 16, "number", "Latest value, e.g. 18000000."),
    ("currency", "Currency", False, 10, "code", "Blank means LKR."),
    ("current_use", "Current use", False, 24, "text", "What the property is used for today."),
    ("custodian", "Custodian / officer", False, 20, "text", "The person responsible for it."),
    ("contact_phone", "Contact phone", False, 15, "code", "Phone number for the site or custodian."),
    ("notes", "Notes", False, 30, "text", "Anything else worth recording."),
]
KEYS = [c[0] for c in COLUMNS]
HEADING = {c[0]: c[1] for c in COLUMNS}

# Other headings people use for the same columns.
ALIASES = {
    "name": "name", "property": "name",
    "code": "property_code",
    "type": "sbu", "property category": "sbu", "category": "sbu", "business unit": "sbu", "sbu": "sbu",
    "owner": "entity", "owned by": "entity", "company": "entity", "legal entity": "entity",
    "ownership": "ownership_type", "ownership type": "ownership_type",
    "structure type": "property_type",
    "location": "location",
    "address": "address_line1", "address 1": "address_line1", "address 2": "address_line2",
    "city": "city", "town": "city",
    "postcode": "postal_code", "post code": "postal_code",
    "lat": "latitude", "lng": "longitude", "long": "longitude", "lon": "longitude",
    "extent": "extent_value", "land area": "extent_value",
    "extent unit": "extent_unit", "unit": "extent_unit",
    "floor area": "building_area_value", "building area sq ft": "building_area_value",
    "floor area unit": "building_area_unit", "building area unit": "building_area_unit",
    "assessment number": "assessment_no", "plan no": "plan_no", "survey plan": "plan_no",
    "lot": "lot_no", "acquired": "acquisition_date", "cost": "acquisition_cost",
    "value": "current_value", "custodian": "custodian", "officer": "custodian",
    "phone": "contact_phone",
}


def _norm(text):
    """Comparable form of a heading or a list value."""
    text = str(text or "").lower().replace("*", " ").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# --- the lists the template offers and the importer accepts -----------------

def _lists(conn):
    types = conn.execute(
        "SELECT id, code, name FROM sbu WHERE is_active = 1 ORDER BY COALESCE(sort_order, 500), name"
    ).fetchall()
    entities = conn.execute(
        "SELECT id, short_code, name FROM legal_entity WHERE is_active = 1 ORDER BY short_code"
    ).fetchall()
    locations = conn.execute(
        """SELECT lc.code, l.id, l.name, l.district, l.latitude, l.longitude
           FROM location_code lc JOIN location l ON l.id = lc.location_id
           WHERE lc.is_active = 1 ORDER BY lc.code"""
    ).fetchall()
    return {
        "types": [r["name"] for r in types],
        "entities": [r["short_code"] for r in entities],
        "tenures": [label for _, label in srilanka.OWNERSHIP_TYPES],
        "structures": [label for _, label in srilanka.PROPERTY_TYPES],
        "statuses": [label for _, label in srilanka.PROPERTY_STATUSES],
        "locations": [r["code"] for r in locations],
        "districts": [d for d, _p in sorted((d["district"], d["province"]) for d in srilanka.DISTRICTS)],
        "units": [label for _, label in srilanka.EXTENT_UNITS],
        "_types": types, "_entities": entities, "_locations": locations,
    }


LIST_SHEET_COLUMNS = [  # Lists sheet: (key, heading, defined name)
    ("types", "Property types", "lst_types"),
    ("entities", "Owning companies", "lst_entities"),
    ("tenures", "Tenures", "lst_tenures"),
    ("structures", "Structures", "lst_structures"),
    ("statuses", "Statuses", "lst_statuses"),
    ("locations", "Location codes", "lst_locations"),
    ("districts", "Districts", "lst_districts"),
    ("units", "Units", "lst_units"),
]


def _col(n):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# --- writing the template -----------------------------------------------------

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/><numFmt numFmtId="165" formatCode="0.000000"/></numFmts>
<fonts count="6">
<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="16"/><color rgb="FF063734"/><name val="Calibri"/><family val="2"/></font>
<font><i/><sz val="10"/><color rgb="FF5E716F"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FF063734"/><name val="Calibri"/><family val="2"/></font>
<font><sz val="11"/><color rgb="FF344645"/><name val="Calibri"/><family val="2"/></font>
</fonts>
<fills count="5">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF006E66"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF063734"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE3F7F6"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="thin"><color rgb="FFD2DCDC"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="5" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="4" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

S_HEAD, S_HEAD_REQ, S_TEXT, S_DATE, S_TITLE, S_WRAP, S_TABLE_HEAD, S_NOTE, S_COORD, S_BOLD = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10

KIND_STYLE = {"code": S_TEXT, "date": S_DATE, "lat": S_COORD, "lng": S_COORD}


def _cell(ref, value, style=0):
    st = ' s="%d"' % style if style else ""
    if value is None or value == "":
        return '<c r="%s"%s/>' % (ref, st) if style else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, repr(value))
    text = escape(str(value))
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return '<c r="%s" t="inlineStr"%s><is><t%s>%s</t></is></c>' % (ref, st, space, text)


def _row(n, cells, height=None):
    ht = ' ht="%s" customHeight="1"' % height if height else ""
    return '<row r="%d"%s>%s</row>' % (n, ht, "".join(cells))


def _sheet(rows, cols="", extra="", freeze=False, tab_selected=False, before_rows=""):
    view = ('<sheetViews><sheetView workbookViewId="0"%s>%s</sheetView></sheetViews>'
            % (' tabSelected="1"' if tab_selected else "",
               '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
               '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>' if freeze else ""))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            + view + '<sheetFormatPr defaultRowHeight="15"/>' + cols + before_rows
            + "<sheetData>" + "".join(rows) + "</sheetData>" + extra + "</worksheet>")


def _cols(widths, styles=None):
    out = []
    for i, w in enumerate(widths):
        st = styles[i] if styles and styles[i] else 0
        out.append('<col min="%d" max="%d" width="%s" customWidth="1"%s/>'
                   % (i + 1, i + 1, w, ' style="%d"' % st if st else ""))
    return "<cols>" + "".join(out) + "</cols>"


def _example_rows(lists):
    """Two sample rows, using values that exist in this register."""
    first = lambda key, default="": (lists[key][0] if lists[key] else default)
    loc = lists["_locations"][0] if lists["_locations"] else None
    return [
        {"name": "Kandy City Showroom", "property_code": "", "sbu": first("types"),
         "entity": first("entities"), "ownership_type": lists["tenures"][0],
         "property_type": "Land & building", "status": lists["statuses"][0],
         "location": loc["code"] if loc else "", "address_line1": "No. 12, Dalada Veediya",
         "city": "Kandy", "district": "Kandy", "postal_code": "20000",
         "latitude": 7.2936, "longitude": 80.6413,
         "extent_value": 12, "extent_unit": "Perches", "building_area_value": 5200,
         "building_area_unit": "Square feet", "assessment_no": "KMC/12/45",
         "plan_no": "PP 1234", "lot_no": "3", "acquisition_date": "2018-06-30",
         "acquisition_cost": 45000000, "current_value": 62000000, "currency": "LKR",
         "current_use": "Retail showroom", "custodian": "A. Perera", "contact_phone": "0812 223 344",
         "notes": "Example row: delete before uploading."},
        {"name": "Galle Hostel", "sbu": lists["types"][min(5, len(lists["types"]) - 1)] if lists["types"] else "",
         "entity": "", "ownership_type": "Rented in", "status": lists["statuses"][0],
         "address_line1": "45 Lighthouse Street", "city": "Galle", "district": "Galle",
         "latitude": 6.0260, "longitude": 80.2170, "extent_value": 0.5, "extent_unit": "Acres",
         "building_area_value": 650, "building_area_unit": "Square metres",
         "current_use": "Staff accommodation",
         "notes": "No owning company: rented in from an outside landlord."},
    ]


def build_template(conn):
    lists = _lists(conn)
    n_cols = len(COLUMNS)
    last = _col(n_cols - 1)
    data_rows = MAX_ROWS + 1

    # 1. Properties: headings, column formats, drop-downs and input prompts.
    head = [_cell("%s1" % _col(i), heading + (" *" if req else ""), S_HEAD_REQ if req else S_HEAD)
            for i, (key, heading, req, width, kind, help_) in enumerate(COLUMNS)]
    validations = []
    for i, (key, heading, req, width, kind, help_) in enumerate(COLUMNS):
        rng = "%s2:%s%d" % (_col(i), _col(i), data_rows)
        prompt = ' showInputMessage="1" promptTitle=%s prompt=%s' % (
            quoteattr(heading[:32]), quoteattr(help_[:250]))
        if kind.startswith("list:"):
            name = dict((k, n) for k, _h, n in LIST_SHEET_COLUMNS)[kind[5:]]
            if lists[kind[5:]]:
                strict = kind[5:] not in ("entities", "locations")
                validations.append(
                    '<dataValidation type="list" allowBlank="1" showErrorMessage="1" errorStyle="%s"%s '
                    'errorTitle=%s error=%s sqref="%s"><formula1>%s</formula1></dataValidation>'
                    % ("stop" if strict else "warning", prompt, quoteattr("Not in the list"),
                       quoteattr("Choose a value from the drop-down list."), rng, name))
                continue
        if kind in ("lat", "lng"):
            b = srilanka.SRI_LANKA_BOUNDS
            lo, hi = (b["min_lat"], b["max_lat"]) if kind == "lat" else (b["min_lng"], b["max_lng"])
            validations.append(
                '<dataValidation type="decimal" operator="between" allowBlank="1" showErrorMessage="1"%s '
                'errorTitle=%s error=%s sqref="%s"><formula1>%s</formula1><formula2>%s</formula2></dataValidation>'
                % (prompt, quoteattr("Outside Sri Lanka"),
                   quoteattr("%s must be between %s and %s." % (heading, lo, hi)), rng, lo, hi))
            continue
        if kind == "number":
            validations.append(
                '<dataValidation type="decimal" operator="greaterThanOrEqual" allowBlank="1" '
                'showErrorMessage="1"%s errorTitle=%s error=%s sqref="%s"><formula1>0</formula1></dataValidation>'
                % (prompt, quoteattr("Number needed"), quoteattr("Enter a number of 0 or more."), rng))
            continue
        validations.append('<dataValidation allowBlank="1"%s sqref="%s"/>' % (prompt, rng))
    props = _sheet(
        [_row(1, head, 32)],
        cols=_cols([c[3] for c in COLUMNS], [KIND_STYLE.get(c[4], 0) for c in COLUMNS]),
        extra='<autoFilter ref="A1:%s1"/>' % last +
              '<dataValidations count="%d">%s</dataValidations>' % (len(validations), "".join(validations)),
        freeze=True, tab_selected=True)

    # 2. Instructions.
    lines = [
        ("Bulk property upload", S_TITLE),
        ("Fill in one row per property on the Properties sheet, then upload this file "
         "from New property > Bulk upload. Nothing is saved until you have reviewed every row.", S_WRAP),
        ("1. Keep the headings in row 1 as they are. Columns marked * are required; the dark headings mark them.", S_WRAP),
        ("2. Pick list values from the drop-downs (property type, tenure, district, units...). "
         "They come from this register, as of the day you downloaded the file.", S_WRAP),
        ("3. Latitude and longitude are decimal degrees inside Sri Lanka. If you give a location code "
         "instead, the property is placed at that location and you can move the pin later.", S_WRAP),
        ("4. Leave Property code blank and the system numbers it for you from the property type.", S_WRAP),
        ("5. See the Example sheet for two filled-in rows. Up to %d properties per file." % MAX_ROWS, S_WRAP),
    ]
    rows = [_row(i + 1, [_cell("A%d" % (i + 1), text, style)], 26 if i == 0 else 34)
            for i, (text, style) in enumerate(lines)]
    r = len(lines) + 2
    rows.append(_row(r, [_cell("A%d" % r, "Column", S_TABLE_HEAD), _cell("B%d" % r, "Required", S_TABLE_HEAD),
                         _cell("C%d" % r, "What to enter", S_TABLE_HEAD)], 22))
    for key, heading, req, width, kind, help_ in COLUMNS:
        r += 1
        if kind.startswith("list:"):
            help_ += " Allowed values: the %s column on the Lists sheet." % dict(
                (k, h) for k, h, _n in LIST_SHEET_COLUMNS)[kind[5:]]
        rows.append(_row(r, [_cell("A%d" % r, heading, S_BOLD),
                             _cell("B%d" % r, "Yes" if req else "", S_WRAP),
                             _cell("C%d" % r, help_, S_WRAP)]))
    instructions = _sheet(rows, cols=_cols([26, 10, 90]),
                          before_rows="", extra='<mergeCells count="%d">%s</mergeCells>' % (
                              len(lines), "".join('<mergeCell ref="A%d:C%d"/>' % (i + 1, i + 1)
                                                  for i in range(len(lines)))))

    # 3. Example.
    ex_rows = [_row(1, head, 32)]
    for n, sample in enumerate(_example_rows(lists), start=2):
        ex_rows.append(_row(n, [_cell("%s%d" % (_col(i), n), sample.get(key, ""),
                                      KIND_STYLE.get(kind, 0) if kind != "date" else 0)
                                for i, (key, _h, _r, _w, kind, _hp) in enumerate(COLUMNS)]))
    example = _sheet(ex_rows, cols=_cols([c[3] for c in COLUMNS]), freeze=True)

    # 4. Lists: the allowed values, named so the drop-downs can point at them.
    list_rows, names = [], []
    longest = max(len(lists[k]) for k, _h, _n in LIST_SHEET_COLUMNS)
    list_rows.append(_row(1, [_cell("%s1" % _col(i), h, S_HEAD) for i, (_k, h, _n) in enumerate(LIST_SHEET_COLUMNS)], 22))
    for j in range(longest):
        list_rows.append(_row(j + 2, [_cell("%s%d" % (_col(i), j + 2), lists[k][j] if j < len(lists[k]) else "")
                                      for i, (k, _h, _n) in enumerate(LIST_SHEET_COLUMNS)]))
    for i, (k, _h, name) in enumerate(LIST_SHEET_COLUMNS):
        if lists[k]:
            names.append('<definedName name="%s">Lists!$%s$2:$%s$%d</definedName>'
                         % (name, _col(i), _col(i), len(lists[k]) + 1))
    names.append('<definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">%s!$A$1:$%s$1</definedName>'
                 % (SHEET, last))
    list_sheet = _sheet(list_rows, cols=_cols([30, 18, 26, 18, 22, 16, 18, 16]), freeze=True)

    sheets = [(SHEET, props), ("Instructions", instructions), ("Example", example), ("Lists", list_sheet)]
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<bookViews><workbookView activeTab="0"/></bookViews><sheets>'
                + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i + 1, i + 1)
                          for i, (n, _x) in enumerate(sheets))
                + "</sheets><definedNames>" + "".join(names) + "</definedNames></workbook>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      'Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets)))
            + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
              'Target="styles.xml"/></Relationships>' % (len(sheets) + 1))
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" '
                               'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
                               for i in range(len(sheets)))
                     + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                     '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                     '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                 '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                 '</Relationships>')
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>Property Register - bulk upload template</dc:title><dc:creator>Property Register</dc:creator>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created></cp:coreProperties>' % now)
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>Property Register</Application></Properties>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/styles.xml", STYLES)
        for i, (_n, xml) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), xml)
    return buf.getvalue()


# --- reading an upload ---------------------------------------------------------

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _ref_col(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read_xlsx(data):
    """Rows of the Properties sheet (else the first sheet): [(row_no, [values])]."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ApiError("This file isn't a readable Excel workbook (.xlsx). Save it as .xlsx and try again.",
                       field="file")
    names = set(z.namelist())
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall("pr:Relationship", NS)}
    sheets = [(s.get("name"), targets.get(s.get("{%s}id" % NS["r"])))
              for s in wb.find("m:sheets", NS).findall("m:sheet", NS)]
    chosen = next((s for s in sheets if s[0].strip().lower() == SHEET.lower()), sheets[0])
    path = chosen[1].lstrip("/")
    path = path if path.startswith("xl/") else "xl/" + path

    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))

    rows = []
    for row in ET.fromstring(z.read(path)).iter("{%s}row" % NS["m"]):
        values = {}
        for c in row.findall("m:c", NS):
            t, ref = c.get("t"), c.get("r")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif t == "b" and v is not None:
                val = "TRUE" if v.text == "1" else "FALSE"
            elif v is not None:
                val = v.text
                if t != "str" and t != "e":
                    try:
                        num = float(val)
                        val = num   # numbers stay numbers (dates arrive as Excel serials)
                    except ValueError:
                        pass
            else:
                val = ""
            if ref:
                values[_ref_col(ref)] = val
        if values:
            width = max(values) + 1
            rows.append((int(row.get("r")), [values.get(i, "") for i in range(width)]))
    return chosen[0], rows


def _read_csv(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return "CSV", [(i + 1, row) for i, row in enumerate(csv.reader(io.StringIO(text)))]


def read_upload(filename, data):
    if not data:
        raise ApiError("The file is empty.", field="file")
    if len(data) > MAX_FILE_BYTES:
        raise ApiError("The file is larger than %d MB." % (MAX_FILE_BYTES // (1024 * 1024)), 413, "file")
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return _read_csv(data)
    if name.endswith(".xls"):
        raise ApiError("This is an old .xls workbook. In Excel choose File > Save As > Excel Workbook (.xlsx), "
                       "then upload that.", field="file")
    return _read_xlsx(data)


def _map_headers(header):
    """Heading cells -> {column index: key}, plus headings nobody recognises."""
    # Least to most specific: the template's own headings always win.
    lookup = {_norm(k): k for k in KEYS}
    lookup.update({_norm(a): k for a, k in ALIASES.items()})
    lookup.update({_norm(h): k for k, h, *_ in COLUMNS})
    mapping, unknown, seen = {}, [], set()
    for i, cell in enumerate(header):
        if str(cell).strip() == "":
            continue
        key = lookup.get(_norm(cell))
        if key and key not in seen:
            mapping[i] = key
            seen.add(key)
        else:
            unknown.append(str(cell).strip())
    return mapping, unknown


# --- checking each row ---------------------------------------------------------

def _as_text(value):
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value or "").strip()


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S")


def _excel_date(value):
    """An Excel serial date, or a typed date in a common day-first form, as YYYY-MM-DD.

    Anything unreadable is passed on as typed, so the property check names it.
    """
    if isinstance(value, float):
        if 1 <= value < 2958466:
            return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(value))).isoformat()
        return str(value)
    text = _as_text(value)
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _choice_lookup(pairs):
    """Accept the code, the full label, or the label's first part ("Freehold")."""
    out = {}
    for code, label in pairs:
        for form in (code, label, re.split(r"\s*[(/]", label)[0]):
            out.setdefault(_norm(form), code)
    return out


UNIT_ALIASES = {"p": "PERCH", "perch": "PERCH", "perches": "PERCH", "ac": "ACRE", "acre": "ACRE",
                "acres": "ACRE", "a": "ACRE", "r": "ROOD", "rood": "ROOD", "roods": "ROOD",
                "ha": "HECTARE", "hectare": "HECTARE", "hectares": "HECTARE",
                "m2": "SQ_M", "sqm": "SQ_M", "sq m": "SQ_M", "square metre": "SQ_M", "square meters": "SQ_M",
                "sq ft": "SQ_FT", "sqft": "SQ_FT", "ft2": "SQ_FT", "square foot": "SQ_FT", "square feet": "SQ_FT"}


class _Body:
    """Stands in for a request, so a row goes through the property form's own checks."""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def check_rows(conn, sheet_rows):
    from . import api   # api imports this module; by the time a request runs, both are loaded

    if not sheet_rows:
        raise ApiError("The file has no rows. Fill in the Properties sheet and upload it again.", field="file")
    header_no, header = sheet_rows[0]
    mapping, unknown = _map_headers(header)
    found = set(mapping.values())
    missing = [HEADING[k] for k, _h, req, *_ in COLUMNS
               if req and k not in found and k not in ("latitude", "longitude")]
    if "name" not in found or missing:
        raise ApiError("The heading row is missing required columns: %s. Start from the template "
                       "so the headings match." % ", ".join(missing or ["Property name"]), field="file")

    lists = _lists(conn)
    types = {}
    for r in lists["_types"]:
        types[_norm(r["name"])] = r["id"]
        types[_norm(r["code"])] = r["id"]
    entities = {}
    for r in lists["_entities"]:
        entities[_norm(r["short_code"])] = r["id"]
        entities[_norm(r["name"])] = r["id"]
    locations = {_norm(r["code"]): r for r in lists["_locations"]}
    tenures = _choice_lookup(srilanka.OWNERSHIP_TYPES)
    structures = _choice_lookup(srilanka.PROPERTY_TYPES)
    statuses = _choice_lookup(srilanka.PROPERTY_STATUSES)
    units = _choice_lookup(srilanka.EXTENT_UNITS)
    units.update({_norm(k): v for k, v in UNIT_ALIASES.items()})
    districts = {_norm(d["district"]): d["district"] for d in srilanka.DISTRICTS}
    existing_codes = {r["property_code"].upper() for r in conn.execute("SELECT property_code FROM property")}
    existing_names = {(_norm(r["name"]), _norm(r["district"])) for r in
                      conn.execute("SELECT name, district FROM property")}

    results, codes_in_file = [], {}
    body = [r for r in sheet_rows[1:] if any(_as_text(v) for v in r[1])]
    if not body:
        raise ApiError("No properties found below the heading row. Fill in one row per property "
                       "on the Properties sheet and upload it again.", field="file")
    if len(body) > MAX_ROWS:
        raise ApiError("The file has %d rows; the limit is %d per upload. Split it into smaller files."
                       % (len(body), MAX_ROWS), field="file")

    for row_no, cells in body:
        raw = {key: (cells[i] if i < len(cells) else "") for i, key in mapping.items()}
        text = {k: _as_text(v) for k, v in raw.items()}
        errors, warnings, data = [], [], {}

        def err(key, message):
            errors.append({"column": HEADING.get(key, key), "message": message})

        def pick(key, table, label):
            value = text.get(key, "")
            if not value:
                return None
            found_value = table.get(_norm(value))
            if found_value is None:
                err(key, "“%s” is not %s in this register." % (value, label))
            return found_value

        data["name"] = text.get("name", "")
        data["property_code"] = text.get("property_code", "")
        sbu = pick("sbu", types, "a property type")
        if sbu is None and not text.get("sbu"):
            err("sbu", "Choose a property type.")
        data["sbu_id"] = sbu
        data["legal_entity_id"] = pick("entity", entities, "an owning company")
        tenure = pick("ownership_type", tenures, "a tenure")
        if tenure is None and not text.get("ownership_type"):
            err("ownership_type", "Choose a tenure, e.g. Freehold.")
        data["ownership_type"] = tenure
        data["property_type"] = pick("property_type", structures, "a structure") or "LAND_AND_BUILDING"
        data["status"] = pick("status", statuses, "a status") or "ACTIVE"
        data["extent_unit"] = pick("extent_unit", units, "a unit") or "PERCH"
        data["building_area_unit"] = pick("building_area_unit", units, "a unit") or data["extent_unit"]

        location = None
        if text.get("location"):
            location = locations.get(_norm(text["location"]))
            if location is None:
                err("location", "“%s” is not a location code in the location master." % text["location"])
        data["location_id"] = location["id"] if location else None

        district = text.get("district", "")
        if district:
            data["district"] = districts.get(_norm(district))
            if data["district"] is None:
                err("district", "“%s” is not one of Sri Lanka's 25 districts." % district)
        elif location is not None and location["district"]:
            data["district"] = location["district"]

        lat, lng = raw.get("latitude", ""), raw.get("longitude", "")
        if _as_text(lat) == "" and _as_text(lng) == "" and location is not None \
                and location["latitude"] is not None and location["longitude"] is not None:
            lat, lng = location["latitude"], location["longitude"]
            warnings.append("No coordinates: placed at the %s location (%s). Move the pin later if needed."
                            % (location["code"], location["name"]))
        data["latitude"], data["longitude"] = lat, lng

        for key in ("extent_value", "building_area_value", "acquisition_cost", "current_value"):
            data[key] = raw.get(key, "")
        data["acquisition_date"] = _excel_date(raw.get("acquisition_date", ""))
        for key in ("address_line1", "address_line2", "city", "postal_code", "assessment_no",
                    "plan_no", "lot_no", "current_use", "custodian", "contact_phone", "notes"):
            data[key] = text.get(key, "")
        data["currency"] = (text.get("currency") or "LKR").upper()

        code = data["property_code"].upper()
        if code:
            if code in existing_codes:
                err("property_code", "%s is already used by another property." % code)
            elif code in codes_in_file:
                err("property_code", "%s is also used on row %d of this file." % (code, codes_in_file[code]))
            else:
                codes_in_file[code] = row_no

        payload = None
        if not errors:
            try:
                payload, _code = api._property_payload(_Body(data), conn)
            except ApiError as exc:
                field = {"sbu_id": "sbu", "legal_entity_id": "entity",
                         "location_id": "location"}.get(exc.field, exc.field or "")
                err(field, exc.message)
        if not errors and (_norm(data["name"]), _norm(data.get("district"))) in existing_names:
            warnings.append("A property with this name is already registered%s; check it isn't a duplicate."
                            % (" in " + data["district"] if data.get("district") else ""))

        type_name = next((r["name"] for r in lists["_types"] if r["id"] == data["sbu_id"]), text.get("sbu", ""))
        results.append({
            "row": row_no, "ok": not errors, "errors": errors, "warnings": warnings,
            "name": data["name"], "code": code, "type": type_name,
            "district": data.get("district") or "", "tenure": text.get("ownership_type", ""),
            "_payload": payload, "_code": code,
        })
    return results, unknown, header_no


def import_rows(conn, results):
    """Insert every row that passed, in one transaction; returns the new codes."""
    from . import api

    columns = ["property_code", "sbu_id", "legal_entity_id", "location_id",
               "latitude", "longitude"] + api.PROPERTY_FIELDS
    created = []
    try:
        for r in results:
            if not r["ok"]:
                continue
            payload = dict(r["_payload"])
            payload["property_code"] = r["_code"] or api._next_property_code(conn, payload["sbu_id"])
            conn.execute("INSERT INTO property (%s) VALUES (%s)"
                         % (", ".join(columns), ", ".join(":" + c for c in columns)), payload)
            created.append(payload["property_code"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return created


# --- endpoints -------------------------------------------------------------------

def download_template(ctx):
    conn = db.get_conn()
    return 200, {
        "__raw__": True,
        "body": build_template(conn),
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "filename": "property-bulk-upload-template.xlsx",
    }


def upload_properties(ctx):
    """POST a filled template. `mode=check` reports only; `mode=import` saves the rows that pass."""
    conn = db.get_conn()
    fields, upload = ctx.form()
    if upload is None:
        raise ApiError("Choose the filled template to upload.", field="file")
    sheet, rows = read_upload(upload.filename, upload.data)
    results, unknown, _header_row = check_rows(conn, rows)
    valid = sum(1 for r in results if r["ok"])
    created = []
    if fields.get("mode") == "import":
        if not valid:
            raise ApiError("No rows are ready to import. Fix the rows marked in red and upload again.")
        created = import_rows(conn, results)
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    return (201 if created else 200), {
        "sheet": sheet, "total": len(results), "valid": valid, "invalid": len(results) - valid,
        "warnings": sum(1 for r in results if r["warnings"]),
        "unknownColumns": unknown, "rows": public, "created": created,
    }


ROUTES = [
    ("GET", r"^/api/import/template\.xlsx$", download_template),
    ("POST", r"^/api/import/properties$", upload_properties),
]
