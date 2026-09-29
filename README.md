# Property Register — Stage 1

A property database organised by **SBU (Strategic Business Unit)**, with deeds,
lease agreements and other documents attached to each property, and every
property plotted on a map of Sri Lanka by latitude/longitude.

Stage 1 deliberately stops at the register. Tenancy billing, maintenance,
workflow and user accounts are later stages — see *Not in Stage 1* below.

## Running it

No installation, no dependencies. Python 3.7+ and a browser are all you need.

```bash
./run.sh
```

Then open <http://127.0.0.1:8000/>. To use another port:

```bash
PORT=8080 ./run.sh
```

The database and uploaded files are created on first run under `data/`.
Back up that one folder and you have backed up the whole system.

The map uses OpenStreetMap tiles and loads Leaflet from a CDN, so the machine
needs internet access for the map to draw. Everything else works offline.

## What it does

**Properties by SBU** — every property belongs to exactly one business unit.
SBUs are created and edited in the app (name, code, description, map colour),
and an SBU cannot be deleted while properties still point at it.

**Documents** — each property holds any number of documents: deed, title
certificate, rent/lease agreement, survey plan, valuation, rates receipt,
insurance policy, permit, photograph or other. Each carries a reference number,
issue and expiry dates, counterparty (notary, lessor, insurer), amount, notes,
and an optional uploaded file (PDF, image, Word, Excel, ZIP — up to 25 MB).
You can record a document reference now and attach the scan later.

**Map** — properties appear as pins over Sri Lanka coloured by SBU. The sidebar
filters (SBU, district, status, type, free-text search) drive the map, the table
and the dashboard together. Clicking a pin opens the property.

**Coordinate quality** — coordinates are validated server-side and in the browser
against Sri Lanka's bounding box (lat 5.80–9.95, lng 79.40–82.05). Values outside
it are rejected, and a transposed pair is detected and named as such, because
that is the most common data-entry error. In the property form you can type the
coordinates, paste a `6.927079, 79.861244` pair copied from Google Maps, or click
the map to drop a pin and drag it to fine-tune. Choosing a district recentres the
picker there.

**Dashboard** — counts per SBU, district and status; properties with no deed or
title recorded; and leases, policies and permits expiring within 180 days.

**CSV export** — the full register, 30 columns, from the *Export CSV* button.

## Layout

```
property-system/
├── run.sh                  start the server
├── server/
│   ├── app.py              HTTP server, routing, static files
│   ├── api.py              REST handlers and validation
│   ├── db.py               schema + first-run sample data
│   ├── srilanka.py         districts, provinces, bounds, enumerations
│   ├── multipart.py        file-upload parsing
│   └── reset.py            clear or reload the register
├── web/
│   ├── index.html
│   ├── css/styles.css
│   └── js/{api,map,app}.js
└── data/                   created at runtime
    ├── properties.db       SQLite database
    └── uploads/            uploaded document files
```

## Data model

`sbu` — code, name, sector, cost centre, description, map colour, active flag.
An SBU is the sector/business unit/department that **occupies** a property and
carries its costs. It is deliberately *not* the owning legal entity and *not* the
tenure — see *Not in Stage 1* for the legal-entity gap.

`property` — property code (unique, auto-generated as `SBU-0001` if left blank),
name, SBU, type, ownership type, status, address (line 1/2, city, district,
province, postal code), **latitude, longitude**, extent value + unit
(perch/acre/rood/hectare/m²), building area, assessment no., survey plan no.,
lot no., acquisition date and cost, current value, currency, current use,
custodian, contact phone, notes.

`document` — property, type, title, reference no., issue date, expiry date,
counterparty, amount, currency, notes, and the stored file's name, type and size.

District and province are validated against the 25 districts and 9 provinces of
Sri Lanka; selecting a district fills the province automatically.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/reference` | districts, provinces, enumerations, map bounds |
| GET/POST | `/api/sbus` | list / create SBUs |
| PUT/DELETE | `/api/sbus/{id}` | update / delete an SBU |
| GET | `/api/properties` | list, filtered by `sbu_id`, `district`, `province`, `status`, `property_type`, `q` |
| POST | `/api/properties` | create |
| GET/PUT/DELETE | `/api/properties/{id}` | detail (with documents) / update / delete |
| GET/POST | `/api/properties/{id}/documents` | list / attach (multipart) |
| GET | `/api/documents/{id}/file` | view; add `?disposition=attachment` to download |
| DELETE | `/api/documents/{id}` | remove document and its file |
| GET | `/api/stats` | dashboard figures |
| GET | `/api/export/properties.csv` | CSV export |

## Sample data

The first run seeds 6 placeholder SBUs, 13 properties across Sri Lanka and 9
document records so the map and lists are not empty. **Replace these with the
real register.** To clear them:

```bash
python3 -m server.reset --wipe
```

or `--sample` to drop everything and reload the sample set. Both ask for
confirmation.

## Not in Stage 1

By design, and worth agreeing before Stage 2:

- **No login or access control.** Bind to `127.0.0.1` (the default) and it is
  reachable only from that machine. Do not expose it to a network until
  authentication is added — anyone who can reach the port can read and change
  everything, including downloading deed scans.
- No tenancy/rent ledger, invoicing, receipts or arrears tracking.
- No maintenance requests, inspections or work orders.
- No document versioning or approval workflow — uploading a new lease adds a
  second document rather than superseding the first.
- No audit trail of who changed what.
- **No `legal_entity` table.** The blueprint separates three things the current
  property sheet conflates: the owning company (LIS, CNT, NCGE, NCGH, NSM…), the
  occupying SBU, and the tenure. Stage 1 models the SBU and the tenure
  (`ownership_type`); the owning company still has nowhere to live. Add it before
  loading the real 70 records, or the same confusion carries over.
- No bulk import. An Excel importer is the first thing worth building next, and
  it must tolerate bad rows rather than reject the file: in the source sheet 36 of
  70 records have no property code, 32 have no usable address, and `LLKO` is used
  for both Kottawa and Kegalle.
- Map pins are points only — no plot boundaries or polygons.
