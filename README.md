# Property Register — Stage 1

A property database organised by **SBU (Strategic Business Unit)**, with deeds,
lease agreements and other documents attached to each property, and every
property plotted on a map of Sri Lanka by latitude/longitude.

Stage 1 deliberately stops at the register. Tenancy billing, maintenance,
workflow and user accounts are later stages — see *Not in Stage 1* below.

## Brand

The interface carries the **Serengeti Property Management** logo and takes its
colours from it. One teal hue from the logo (`#00A69A`) is stepped light to dark:
the logo teal itself for marks, fills and charts; a deeper step (`#006E66`,
6.1:1) for teal text and primary buttons so both pass WCAG AA; the darkest steps
for deep surfaces such as the hero card and map labels. Greys carry a faint teal
tint. All of it lives as CSS variables at the top of `web/css/styles.css`.

Logo files are in `web/img/`: `serengeti-logo.png` (header), `serengeti-mark.png`
(the building mark, used on narrow screens) and `favicon.png`, all with
transparent backgrounds, cut from the original in `docs/brand/`.
`serengeti-logo-dark.png` and `serengeti-mark-dark.png` are the same marks in a
lighter teal for the dark theme.

## Light and dark mode

![The dashboard in dark mode](docs/screenshots/7-dark-mode.png)

The sun/moon button in the header opens **Appearance**:

- **Light**
- **Dark**
- **System** (the default), which follows the device's setting and switches
  live when the device does, for example at sunset

**Shift + D** flips between light and dark from anywhere outside a text field.
The choice is remembered in the browser and applied before the page draws, so a
dark page never flashes white. The browser's own tab bar follows the theme too.

Dark mode is a designed palette, not an inversion:

- **Surfaces:** deep teal-tinted surfaces stepped by elevation (page, card,
  raised panel).
- **Text:** body text at 14.8:1 contrast, secondary text at 6.6:1.
- **Buttons:** primary buttons are bright teal with dark text, at 7:1.
- **Status colours:** retuned for dark backgrounds.
- **Charts:** they switch to a dark set of the same hues. That set was checked
  with the data-viz palette validator against the dark card surface: it passes
  colour-blind separation, the normal-vision floor and 3:1 contrast.
- **Maps:** the maps and the property map thumbnails go dark.
- **Logo:** the header uses the lighter-teal logo.

Every colour is a CSS variable, defined once for light at the top of
`web/css/styles.css` and once for dark below it.

## Running it

No installation, no dependencies. Python 3.7+ and a browser are all you need.

```bash
./run.sh
```

Then open <http://127.0.0.1:8000/>. To use another port:

```bash
PORT=8080 ./run.sh
```

If the register is already running, `./run.sh` says so and leaves it alone
rather than starting a second copy. To restart it, stop it first:

```bash
pkill -f server.app
```

The database and uploaded files are created on first run under `data/`.
Back up that one folder and you have backed up the whole system.

Three things come from the internet: OpenStreetMap tiles (the map and the
street-map covers on each property card), Leaflet from a CDN, and the Plus
Jakarta Sans typeface from Google Fonts. Offline, the register still works: the
maps go blank and the text falls back to the system font.

## What it does

![Portfolio: property cards beside the map](docs/screenshots/1-portfolio-map.png)

More in [`docs/screenshots/`](docs/screenshots/): the grid layout, a property’s detail panel, the dashboard, the Documents module and a business unit's page.

**Three things kept apart.** The register separates who *occupies* a property
(the SBU), who *owns* it (the legal entity), and how it is *held* (tenure).
Conflating them is the defect the blueprint flags in the current property sheet,
where the Ownership column mixes owning companies with "Rent" and "Lease".

**Properties by SBU** — every property belongs to exactly one business unit.
SBUs are created and edited in the app (name, code, description, map colour),
and an SBU cannot be deleted while properties still point at it.

**Business unit pages** — click any card under Business units to open that
unit's page:

- a header in the unit's colour, with its description and six figures:
  properties, documents, files stored, land, properties without a deed or
  title, and documents due within 180 days
- two tabs, **Properties** and **Documents**

The Properties tab lists each property with its picture, location, type,
tenure, status and document count; click one to open it. The Documents tab
lists every document on the unit's properties, soonest expiry first. Each has
an **Open in Documents** shortcut that jumps to the Documents module, highlights
that document and opens its panel. **Show on map**, **Open in Portfolio** and
**Open all in Documents** show the unit in those modules, as a filter you can
clear. Each page has its own link, for example `#sbus/5` or `#sbus/5/documents`.

**Documents** — each property holds any number of documents: deed, title
certificate, rent/lease agreement, survey plan, valuation, rates receipt,
insurance policy, permit, photograph or other. Each carries a reference number,
issue and expiry dates, counterparty (notary, lessor, insurer), amount, notes,
and an optional uploaded file (PDF, image, Word, Excel, ZIP — up to 25 MB).
You can record a document reference now and attach the scan later.

**Portfolio** — the main screen. It opens with a **summary strip** of five
figures, each with context rather than a bare number: properties (owned vs
leased or rented in), business units (across how many districts), documents
(how many expire within 180 days), files stored (share of documents scanned)
and properties **without a deed or title** (share of the portfolio). Every
figure covers exactly what is on screen, so a search or filter narrows the
summary too. Every card is a shortcut, marked with a ↗ arrow:

- **Properties** opens the register table.
- **Business units** opens the business-unit list.
- **Documents** opens the Documents module.
- **Files stored** opens the Documents module on the *With file* tab.
- **Without deed / title** lists just the properties missing one. Click it again to clear.

Below the summary, three layouts:

- **Map** — property cards beside a light-grey map of Sri Lanka. Pins are coloured
  by business unit and labelled with their property code wherever there is room;
  labels that would overlap are hidden until you zoom in or hover. Clicking a pin
  opens a floating card; hovering a card lights up its pin. The map can expand to
  full width, switch to the colour style, and zoom to fit every property. The
  business-unit chips on the map double as a quick filter — click one to show
  only that unit.
- **Grid** — the cards alone, four across on a desktop.
- **Table** — the dense register view, with the actions pinned to the right edge.

Each card's picture is the latest **Photograph** document with an image file. If
there is none, the card shows a street map of the exact spot with a pin on the
property's coordinates. A blue ✓ beside a name means a deed or title
certificate is on file.

**Search and filters** — the tenure tabs (All · Freehold · Leasehold · Rented in ·
Leased out) and the search box sit above everything; the filter button opens
business units, location, owning company, district, tenure, status and type.
Every active filter shows as a removable chip under the heading, and the count
reads "2 of 13" while any filter is on. Sort by latest, code, name, largest
extent or most documents.

**Documents module** — every document in the register on one page, whichever
property it belongs to. Each row is marked with its **business unit**: the
unit's colour dot, code and name. The row also shows:

- the property
- the issue and expiry dates, with anything expired or due within 90 or 180 days badged
- the counterparty and the amount
- the attached file, which you can view or download

Tabs split the list into All · With file · No file · Expiring soon ·
Expired, each with its count. You can narrow it by document type and sort it by
latest, expiry, business unit, property or title. The toolbar's search, tenure
tabs and filters apply here too, so searching "Colombo" lists only documents on
properties in Colombo. **Attach document** records a new one: you pick the
property in the form, and you stay on the list afterwards.

Click a row to open the **document panel**, which shows:

- the document's type, title, business unit and reference
- a preview of the file: images and PDFs inline, other formats as a download
- **View file**, **Download** and **Open property**
- every detail recorded for it

Each document has its own link, `#documents/doc/<id>`.

**Alerts** — the bell counts documents expiring within 180 days across the whole
register, whatever is filtered, and lists them; click one to open its property.

**Links** — the address bar follows what is on screen, so any view can be
bookmarked or sent: `#dashboard`, `#portfolio/grid`, `#portfolio/table`,
`#masters`, and `#property/12` to open one property directly. Escape closes
whatever is on top: a popover, then a form, then the property panel, then the
map card.

**Forms** — numbers are read the way people type them: `1,250,000`,
`LKR 1,250,000`, `Rs. 420,000/=`. Every problem is reported on the field
itself, which is scrolled into view and focused, so a long form never looks as
if its button did nothing; buttons show *Saving…* / *Uploading…* while they
work. Files can be dropped onto the document form or chosen; the type and size
are checked the moment a file is picked, and a rejected upload never leaves a
file on disk.

**Coordinate quality** — coordinates are validated server-side and in the browser
against Sri Lanka's bounding box (lat 5.80–9.95, lng 79.40–82.05). Values outside
it are rejected, and a transposed pair is detected and named as such, because
that is the most common data-entry error. In the property form you can type the
coordinates, paste a `6.927079, 79.861244` pair copied from Google Maps, or click
the map to drop a pin and drag it to fine-tune. Choosing a district recentres the
picker there.

**Dashboard** — opens on a dark **attention band**: today's date, a one-line
scope of what is covered, and four signals, each a shortcut to the list behind it:

- **Without deed or title** opens those properties in the portfolio.
- **Expired documents** opens the Documents module on its *Expired* tab.
- **Due within 180 days** opens the Documents module on its *Expiring soon* tab.
- **Documents without a file** opens the Documents module on its *No file* tab.

Each signal shows its state with an icon and words (critical, due, clear), not
colour alone. Below the band come four sections, each headed by a rule:

- *Portfolio at a glance*:
  - **Tenure mix** and **Documents by type** — donut charts with a legend that
    prints every count and share, so no value depends on colour or hover.
  - **Deed & title coverage** — a gauge of the share of properties with a deed
    or title on file, coloured and labelled by status (low / partial / good).
- *Renewals*:
  - **Renewal pipeline** — documents by expiry, bucketed on the 3 / 6 / 9 /
    12-month reminder ladder from the review points. Expired is red, within
    3 months amber, and "later" recedes to grey.
  - Beside it, **Expiring within 180 days** — the documents coming up, soonest
    first, each with its date, business-unit dot and days left. Click one to
    open its property.
- *Land & location*:
  - **Land extent by business unit** — acres and share of all land, with the
    exact perches beneath.
  - **Largest holdings** — the five biggest properties by land.
  - **Properties by province** — all nine provinces, shown as bars instead of
    columns on a phone.
  - **Property types**.
- *Breakdowns* — properties by business unit (in each unit's map colour), by
  owning company and by status. Properties by district runs in columns across
  one wide card.

Card headers carry shortcuts where there is a list to go to: *Documents*,
*View all* and *Register*. Every chart mark has a tooltip on hover and on
keyboard focus. Chart colours come from one validated colour-blind-safe palette
and are assigned per category in a fixed order, so a category keeps its colour
whatever is filtered.

**The dashboard follows the filters.** Search or filter anything and every figure
— the attention signals, every chart, the breakdowns and the expiry list — recomputes over just the
matching properties, so the dashboard can never disagree with the list beside it.
A banner names the active filters and says how many of the register they cover
("these 2 of 13 properties"), with a button to clear them.

**Master sheets** — one module holding every reference list the system uses, so
codes and place names are maintained in a single place rather than retyped.

*Editable:* **Locations** (every place the group operates, with district, province
and coordinates), **Location codes**, **Business units (SBU)** and **Owning
companies**. A location code is `UNIQUE`, so one code can never stand for two
places — the LLKO-means-both-Kottawa-and-Kegalle defect the blueprint reports is
impossible by construction. A row cannot be deleted while something still points
at it, and the message names every blocker.

Each property links to a location. Choosing one on the property form fills the
district and province, and seeds the coordinates from the location centroid *only
when they are still blank* — a pin you have already placed is never overwritten.
The address lines stay free text for the street detail. Locations added under
Master sheets appear in the property form immediately.

*System lists* (read-only in Stage 1): provinces, districts, property types,
ownership/tenure types, property statuses, document types and extent units.
These are compiled into the application; the sheet shows exactly what each
drop-down offers.

The module is registry-driven: adding a new master sheet is one entry in
`MASTERS` in `server/masters.py`. No new endpoint or screen is needed — the grid,
the form and the validation are all generated from the column metadata.

**CSV export** — the full register, 34 columns, from the *Export CSV* button.

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
│   ├── img/                logo, building mark, favicon
│   └── js/{api,map,masters,charts,app}.js
└── data/                   created at runtime
    ├── properties.db       SQLite database
    └── uploads/            uploaded document files
```

## Data model

`sbu` — code, name, sector, cost centre, description, map colour, active flag.
An SBU is the sector/business unit/department that **occupies** a property and
carries its costs. It is deliberately *not* the owning legal entity and *not* the
tenure; those are `legal_entity` and `ownership_type`.

`legal_entity` — short code, registered name, registration no., notes, active
flag. The group company that **holds title**. A property leased or rented *in*
has none: an outside landlord owns it, and that party is recorded on the lease
document instead. Managed from the **Owning companies** tab.

`property` — property code (unique, auto-generated as `SBU-0001` if left blank),
name, SBU, owning company (optional), **location** (optional, from the location
master), type, ownership type, status,
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
| GET | `/api/locations` | slim location list for the property form |
| GET | `/api/properties` | list, filtered by `sbu_id`, `legal_entity_id`, `location_id`, `ownership_type`, `has_deed` (`0`/`1`), `district`, `province`, `status`, `property_type`, `q` |
| POST | `/api/properties` | create |
| GET/PUT/DELETE | `/api/properties/{id}` | detail (with documents) / update / delete |
| GET/POST | `/api/properties/{id}/documents` | list / attach (multipart) |
| GET | `/api/documents` | every document with its property and SBU; takes the property filters above plus `doc_status` (`file`, `nofile`, `expiring`, `expired`), `doc_type` and `sort` (`newest`, `expiry`, `sbu`, `property`, `title`), and returns per-tab counts |
| GET | `/api/documents/{id}` | one document with its property and SBU |
| GET | `/api/documents/{id}/file` | view; add `?disposition=attachment` to download |
| DELETE | `/api/documents/{id}` | remove document and its file |
| GET | `/api/masters` | list the master sheets |
| GET | `/api/masters/{key}` | one sheet: columns, rows and reference options |
| POST | `/api/masters/{key}` | add a row (editable sheets only) |
| PUT/DELETE | `/api/masters/{key}/{id}` | update / delete a row |
| GET | `/api/stats` | summary and chart figures (totals, tenure, types, provinces, document types, renewal buckets, breakdowns); accepts the same filters as `/api/properties` |
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
- No bulk import. An Excel importer is the first thing worth building next, and
  it must tolerate bad rows rather than reject the file: in the source sheet 36 of
  70 records have no property code, 32 have no usable address, and `LLKO` is used
  for both Kottawa and Kegalle.
- Map pins are points only — no plot boundaries or polygons.
