"""Sri Lanka reference geography and enumerations used across the system."""

# Approximate bounding box of Sri Lanka (including offshore islands / Jaffna
# peninsula).  Any property coordinate outside this box is rejected, which stops
# the classic "0,0 in the Gulf of Guinea" and "lat/long swapped" data entry bugs.
SRI_LANKA_BOUNDS = {
    "min_lat": 5.80,
    "max_lat": 9.95,
    "min_lng": 79.40,
    "max_lng": 82.05,
}

MAP_CENTER = [7.8731, 80.7718]
MAP_DEFAULT_ZOOM = 7

# province -> list of (district, latitude, longitude) district centroids.
PROVINCES = [
    ("Western", [
        ("Colombo", 6.9271, 79.8612),
        ("Gampaha", 7.0840, 79.9999),
        ("Kalutara", 6.5854, 79.9607),
    ]),
    ("Central", [
        ("Kandy", 7.2906, 80.6337),
        ("Matale", 7.4675, 80.6234),
        ("Nuwara Eliya", 6.9497, 80.7891),
    ]),
    ("Southern", [
        ("Galle", 6.0535, 80.2210),
        ("Matara", 5.9549, 80.5550),
        ("Hambantota", 6.1241, 81.1185),
    ]),
    ("Northern", [
        ("Jaffna", 9.6615, 80.0255),
        ("Kilinochchi", 9.3803, 80.3770),
        ("Mannar", 8.9810, 79.9044),
        ("Vavuniya", 8.7514, 80.4971),
        ("Mullaitivu", 9.2671, 80.8142),
    ]),
    ("Eastern", [
        ("Batticaloa", 7.7102, 81.6924),
        ("Ampara", 7.2917, 81.6747),
        ("Trincomalee", 8.5874, 81.2152),
    ]),
    ("North Western", [
        ("Kurunegala", 7.4863, 80.3623),
        ("Puttalam", 8.0362, 79.8283),
    ]),
    ("North Central", [
        ("Anuradhapura", 8.3114, 80.4037),
        ("Polonnaruwa", 7.9403, 81.0188),
    ]),
    ("Uva", [
        ("Badulla", 6.9934, 81.0550),
        ("Monaragala", 6.8728, 81.3510),
    ]),
    ("Sabaragamuwa", [
        ("Ratnapura", 6.6828, 80.3992),
        ("Kegalle", 7.2513, 80.3464),
    ]),
]

DISTRICTS = []
for _province, _districts in PROVINCES:
    for _name, _lat, _lng in _districts:
        DISTRICTS.append({
            "district": _name,
            "province": _province,
            "lat": _lat,
            "lng": _lng,
        })

DISTRICT_NAMES = [d["district"] for d in DISTRICTS]
PROVINCE_NAMES = [p[0] for p in PROVINCES]
DISTRICT_BY_NAME = {d["district"]: d for d in DISTRICTS}

# Structure: the physical form of a property. (Stored as `property_type`;
# what a property is used for is its property type category, the `sbu` table.)
PROPERTY_TYPES = [
    ("LAND", "Bare land"),
    ("LAND_AND_BUILDING", "Land & building"),
    ("BUILDING", "Building only"),
    ("OTHER", "Other"),
]

# Earlier structure values that described use rather than form; they now
# read as land with a building on it.
RETIRED_STRUCTURES = ("OFFICE", "WAREHOUSE", "FACTORY", "SHOWROOM", "RESIDENTIAL", "ESTATE")

# Property types: what each property is used for. Stored in the `sbu` table,
# editable from the app; this is the starting list, in display order.
PROPERTY_CATEGORIES = [
    # code, name, description, map colour
    ("EDU", "Educational", "Schools, campuses and other teaching premises", "#e377c2"),
    ("WH", "Warehouse", "Warehouses, stores and distribution centres", "#9467bd"),
    ("CORP", "Corporate Office", "Head office and administrative offices", "#1f77b4"),
    ("TECH", "Technical & Mechanical Sites", "Workshops, plants and technical installations", "#2ca02c"),
    ("BUS", "Bus Yards", "Yards and depots for the bus fleet", "#d4a017"),
    ("HOST", "Hostels", "Student and staff accommodation", "#8c564b"),
    ("COMM", "Commercial Properties", "Showrooms, shops and premises let commercially", "#ff7f0e"),
    ("OTHER", "Other", "Properties that fit none of the types above", "#7f8c8d"),
]

# The first sample business units, and the property type each became.
BUSINESS_UNIT_TO_CATEGORY = {
    "HO": "CORP", "LOG": "WH", "RETAIL": "COMM", "MFG": "TECH", "LEIS": "HOST", "AGRI": "OTHER",
}

OWNERSHIP_TYPES = [
    ("FREEHOLD", "Freehold (owned)"),
    ("LEASEHOLD", "Leasehold (we lease in)"),
    ("RENTED_IN", "Rented in"),
    ("LEASED_OUT", "Owned, leased out"),
    ("STATE_GRANT", "State grant / permit"),
    ("OTHER", "Other"),
]

PROPERTY_STATUSES = [
    ("ACTIVE", "Active / in use"),
    ("IDLE", "Idle / vacant"),
    ("UNDER_CONSTRUCTION", "Under construction"),
    ("UNDER_DISPUTE", "Under dispute"),
    ("DISPOSED", "Disposed / sold"),
]

EXTENT_UNITS = [
    ("PERCH", "Perches"),
    ("ACRE", "Acres"),
    ("ROOD", "Roods"),
    ("HECTARE", "Hectares"),
    ("SQ_M", "Square metres"),
    ("SQ_FT", "Square feet"),
]

# Square feet in one of each unit: the one table every area conversion uses.
# 1 perch = 272.25 sq ft (16.5 ft square), 1 rood = 40 perches,
# 1 acre = 160 perches = 43,560 sq ft, 1 m = 3.28084 ft.
SQFT_PER_UNIT = {
    "PERCH": 272.25,
    "ROOD": 10890.0,
    "ACRE": 43560.0,
    "HECTARE": 107639.104,
    "SQ_M": 10.7639104,
    "SQ_FT": 1.0,
}


def to_sqft(value, unit):
    """An area in square feet, or None when there is no value."""
    if value is None:
        return None
    return round(value * SQFT_PER_UNIT.get(unit or "PERCH", 1.0), 2)

DOCUMENT_TYPES = [
    ("DEED", "Deed"),
    ("TITLE_CERTIFICATE", "Title certificate"),
    ("LEASE_AGREEMENT", "Rent / lease agreement"),
    ("SURVEY_PLAN", "Survey plan"),
    ("VALUATION_REPORT", "Valuation report"),
    ("TAX_RECEIPT", "Rates / tax receipt"),
    ("INSURANCE_POLICY", "Insurance policy"),
    ("PERMIT_APPROVAL", "Permit / approval"),
    ("PHOTOGRAPH", "Photograph"),
    ("OTHER", "Other document"),
]

# Palette used when auto-assigning a map colour to a new SBU.
SBU_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
    "#8c564b", "#17becf", "#e377c2", "#7f7f7f", "#bcbd22",
]


def valid_codes(pairs):
    return [code for code, _label in pairs]


def as_options(pairs):
    return [{"value": code, "label": label} for code, label in pairs]


def coordinates_in_sri_lanka(lat, lng):
    """Return (ok, message)."""
    b = SRI_LANKA_BOUNDS
    if lat is None or lng is None:
        return False, "Latitude and longitude are required."
    if not (b["min_lat"] <= lat <= b["max_lat"]) or not (b["min_lng"] <= lng <= b["max_lng"]):
        hint = ""
        # The single most common entry error: the two values transposed.
        if (b["min_lat"] <= lng <= b["max_lat"]) and (b["min_lng"] <= lat <= b["max_lng"]):
            hint = " It looks like latitude and longitude have been swapped."
        return False, (
            "Coordinates %.5f, %.5f are outside Sri Lanka (lat %.2f..%.2f, "
            "lng %.2f..%.2f).%s" % (lat, lng, b["min_lat"], b["max_lat"],
                                    b["min_lng"], b["max_lng"], hint)
        )
    return True, ""
