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

**Three things kept apart.** The register separates who *occupies* a property
(the SBU), who *owns* it (the legal entity), and how it is *held* (tenure).
Conflating them is the defect the blueprint flags in the current property sheet,
where the Ownership column mixes owning companies with "Rent" and "Lease".

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

**Master sheets** — one module holding every reference list the system uses, so
codes and place names are maintained in a single place rather than retyped.

*Editable:* **Locations** (every place the group operates, with district, province
and coordinates), **Location codes**, **Business units (SBU)** and **Owning
companies**. A location code is `UNIQUE`, so one code can never stand for two
places — the LLKO-means-both-Kottawa-and-Kegalle defect the blueprint reports is
impossible by construction. A row cannot be deleted while something still points
at it.

*System lists* (read-only in Stage 1): provinces, districts, property types,
ownership/tenure types, property statuses, document types and extent units.
These are compiled into the application; the sheet shows exactly what each
drop-down offers.

The module is registry-driven: adding a new master sheet is one entry in
`MASTERS` in `server/masters.py`. No new endpoint or screen is needed — the grid,
the form and the validation are all generated from the column metadata.

**CSV export** — the full register, 32 columns, from the *Export CSV* button.

## Layout

```
property-system/
├── run.sh                  start the server
├── server/
│   ├── app.py              HTTP server, routing, static files
│   ├── api.py              REST handlers and validation
│   ├── db.py               schema + first-run sample data
│   ├── masters.py          master sheets: registry, generic CRUD
│   ├── errors.py           shared ApiError
│   ├── srilanka.py         districts, provinces, bounds, enumerations
│   ├── multipart.py        file-upload parsing
│   └── reset.py            clear or reload the register
├── web/
│   ├── index.html
│   ├── css/styles.css
│   └── js/{api,map,masters,app}.js
└── data/                   created at runtime
    ├── properties.db       SQLite database
    └── uploads/            uploaded document files
```

## Data model

`sbu` — code, name, sector, cost centre, description, map colour, active flag.
An SBU is the sector/business unit/department that **occupies** a property and
carries its costs. It is deliberately *not* the owning legal entity and *not* the
tenure — see *Not in Stage 1* for the legal-entity gap.

`legal_entity` — short code, registered name, registration no., notes, active
flag. The group company that **holds title**. A property leased or rented *in*
has none: an outside landlord owns it, and that party is recorded on the lease
document instead. Managed from the **Owning companies** tab.

`property` — property code (unique, auto-generated as `SBU-0001` if left blank),
name, SBU, owning company (optional), type, ownership type, status,
address (line 1/2, city, district,
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
| GET/POST | `/api/legal-entities` | list / create owning companies |
| PUT/DELETE | `/api/legal-entities/{id}` | update / delete an owning company |
| GET | `/api/properties` | list, filtered by `sbu_id`, `district`, `province`, `status`, `property_type`, `q` |
| POST | `/api/properties` | create |
| GET/PUT/DELETE | `/api/properties/{id}` | detail (with documents) / update / delete |
| GET/POST | `/api/properties/{id}/documents` | list / attach (multipart) |
| GET | `/api/documents/{id}/file` | view; add `?disposition=attachment` to download |
| DELETE | `/api/documents/{id}` | remove document and its file |
| GET | `/api/masters` | list the master sheets |
| GET | `/api/masters/{key}` | one sheet: columns, rows and reference options |
| POST | `/api/masters/{key}` | add a row (editable sheets only) |
| PUT/DELETE | `/api/masters/{key}/{id}` | update / delete a row |
| GET | `/api/stats` | dashboard figures |
| GET | `/api/export/properties.csv` | CSV export |

## Sample data

The first run seeds 6 placeholder SBUs, 13 properties across Sri Lanka and 9
document records so the map and lists are not empty. **Replace these with the
real register.**

It also seeds 5 owning companies — LIS, CNT, NCGE, NCGH, NSM — taken from the
blueprint. Only their short codes were stated there, so each `name` repeats its
code and the card shows a **name unconfirmed** badge until someone fills in the
registered name. The list is not exhaustive.

To clear everything:

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
- **Properties are not yet linked to the location master.** The location and
  location-code sheets exist and are ready to load, but a property still records
  its address as free text. Adding `property.location_id` is the obvious next
  step; it was left out deliberately so the Master sheets module changed nothing
  in the property register.
- No bulk import. An Excel importer is the first thing worth building next, and
  it must tolerate bad rows rather than reject the file: in the source sheet 36 of
  70 records have no property code, 32 have no usable address, and `LLKO` is used
  for both Kottawa and Kegalle.
- Map pins are points only — no plot boundaries or polygons.
