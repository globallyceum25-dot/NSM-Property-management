# Property Register — Stage 1

[![CI](https://github.com/globallyceum25-dot/NSM-Property-management/actions/workflows/ci.yml/badge.svg)](https://github.com/globallyceum25-dot/NSM-Property-management/actions/workflows/ci.yml)
[![CodeQL](https://github.com/globallyceum25-dot/NSM-Property-management/actions/workflows/codeql.yml/badge.svg)](https://github.com/globallyceum25-dot/NSM-Property-management/actions/workflows/codeql.yml)

A property database organised by **property type** (Educational, Warehouse,
Corporate Office, …), with deeds,
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

### Running on Supabase

The register can keep its data in a Supabase project instead of `data/`: the
tables in Supabase Postgres, the uploaded files in a private Supabase Storage
bucket. The server still runs on your machine; only where it stores things
changes.

1. Install the Postgres driver once (into `.venv`, which `./run.sh` uses):

   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in the project's details: the
   session pooler connection string (dashboard → **Connect**) and the
   `service_role` key (**Project Settings → API keys**, legacy keys tab;
   Storage does not accept the newer `sb_secret_` keys). `.env` is git-ignored.

3. Copy the existing register across. Ids are kept, so every link survives,
   and the SQLite file is only read:

   ```bash
   .venv/bin/python3 -m server.import_sqlite
   ```

   It refuses to overwrite a register that already has rows; `--replace`
   empties it (and its stored files) first.

4. Start it as usual with `./run.sh`. The banner says where the data lives:

   ```
   Database: Postgres at aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
   Uploads:  Supabase Storage, bucket 'documents'
   ```

Delete `.env` (or the `DATABASE_URL` line) to go back to `data/`. The tables
have row level security switched on with no policies, so Supabase's public API
and anon key can read none of it; only the server, connecting as the database
owner, can.

### Tests and CI

The tests need nothing installed and never touch the real register: they run
on SQLite in a temporary folder and ignore `.env`.

```bash
python3 -m unittest discover -s tests -t .
```

To run the same tests on Postgres, point `TEST_DATABASE_URL` at a **throwaway**
database (it is emptied and reseeded over and over; a Supabase URL is
refused). With Docker:

```bash
docker run -d --name register-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=register_test -p 127.0.0.1:55432:5432 postgres:17
```

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/register_test .venv/bin/python3 -m unittest discover -s tests -t .
```

On Postgres the suite also checks that every read endpoint returns exactly
what SQLite returns, and tests `server.import_sqlite`. The browser smoke test
runs when Playwright is installed (`.venv/bin/pip install -r
requirements-dev.txt`, then `.venv/bin/python3 -m playwright install chromium`).

The same checks CI runs, locally (after `.venv/bin/pip install -r
requirements-dev.txt`):

```bash
.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/python3 -m coverage run -m unittest discover -s tests -t . && .venv/bin/python3 -m coverage combine && .venv/bin/python3 -m coverage report
```

GitHub Actions runs **CI** on every pull request and every push to `main`:

| Stage | Jobs |
| --- | --- |
| Static checks | **Lint**: Ruff, JavaScript syntax, ShellCheck, actionlint on the workflows. **Type check**: mypy over the server and the tests. |
| Tests | Python 3.9 and 3.13, each against SQLite and Postgres 17; Python 3.7 (the oldest supported) with nothing installed; the **browser smoke test** in Chromium. |
| Coverage | Combines every test run into one report (job summary, plus an HTML artifact) and fails below the minimum in `.coveragerc`. |
| Build | Builds the Docker image, smoke-tests it on SQLite and on Postgres, and scans it with Trivy for fixable high and critical vulnerabilities. |
| Security | **Dependency audit** (pip-audit) of both requirement files; **secret scan** (gitleaks) of the whole git history. |
| Gate | **CI passed** fails if anything above did: the one check to require in branch protection. |

Alongside it, **CodeQL** scans the Python, the JavaScript and the workflows
(on every change and weekly), and Dependabot proposes updates to the Python
packages, the Docker base image and the actions weekly.

### Docker

The `Dockerfile` packages the register (with the Postgres driver; no `.env`,
data or tests inside). Settings come in at run time:

```bash
docker build -t nsm-property-register .
```

```bash
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env nsm-property-register
```

Without `--env-file` it runs on SQLite in `/app/data`; add
`-v register-data:/app/data` to keep that data. Publish the port on
`127.0.0.1` as above: the register has no login yet.

### Releasing

Push a version tag. The **Release** workflow runs all of CI again, then
publishes the image to `ghcr.io/globallyceum25-dot/nsm-property-management`
(Intel and ARM, with an SBOM and signed build provenance) and creates a
GitHub Release with generated notes:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

## What it does

![Portfolio: property cards beside the map](docs/screenshots/1-portfolio-map.png)

More in [`docs/screenshots/`](docs/screenshots/): the grid layout, a property’s detail panel, the dashboard, the Documents module and a property type's page.

**Three things kept apart.** The register separates what a property is *used
for* (its property type), who *owns* it (the legal entity), and how it is *held*
(tenure).
Conflating them is the defect the blueprint flags in the current property sheet,
where the Ownership column mixes owning companies with "Rent" and "Lease".

**Property types** — every property has exactly one type, which says what the
property is used for. The list starts as:

1. Educational
2. Warehouse
3. Corporate Office
4. Technical & Mechanical Sites
5. Bus Yards
6. Hostels
7. Commercial Properties
8. Other (always last)

Types are added, renamed, recoloured or removed from the **Property types** tab
or the master sheet. A type can't be deleted while properties still use it.

Property types replaced the earlier *business units*. The six sample units were
renamed in place, so every property, document and link stayed attached:

- Head Office → Corporate Office
- Logistics → Warehouse
- Retail → Commercial Properties
- Manufacturing → Technical & Mechanical Sites
- Leisure → Hostels
- Agriculture → Other

Existing property codes such as `HO-0003` were kept; new properties get the
type's code as their prefix (`CORP-0001`).

**Structure** — separate from the property type, a property's physical form:
Bare land, Land & building, Building only or Other. When property types
arrived, the old Type values that described use (Office, Warehouse, Showroom,
Factory, Residential, Estate) became *Land & building*.

**Property type pages** — click any card under Property types to open that
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
leased or rented in), property types (how many of the list are in use), documents
(how many expire within 180 days), files stored (share of documents scanned)
and properties **without a deed or title** (share of the portfolio). Every
figure covers exactly what is on screen, so a search or filter narrows the
summary too. Every card is a shortcut, marked with a ↗ arrow:

- **Properties** opens the register table.
- **Property types** opens the property-type list.
- **Documents** opens the Documents module.
- **Files stored** opens the Documents module on the *With file* tab.
- **Without deed / title** lists just the properties missing one. Click it again to clear.

Below the summary, three layouts:

- **Map** — property cards beside a light-grey map of Sri Lanka. Pins are coloured
  by property type and labelled with their property code wherever there is room;
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

**Areas in the property form** — land extent and building area are each
entered in their own unit:

- **Building area** has its own unit picker. It follows the land **Unit** until
  you pick another, so land in perches with a building in sq ft works.
- Two read-only fields, **Land extent (sq ft)** and **Building area (sq ft)**,
  calculate as you type and show the rate used, for example
  `1 acre = 43,560 sq ft`.

The conversions are exact, with one table on the server (`SQFT_PER_UNIT` in
`server/srilanka.py`) that the form also uses:

- 1 perch = 272.25 sq ft
- 1 rood = 40 perches
- 1 acre = 160 perches = 43,560 sq ft
- 1 hectare = 107,639.1 sq ft
- 1 m² = 10.764 sq ft

**One unit across the portfolio** — cards, the map's floating card and the
table all show areas in **square feet**, so properties compare at a glance:

- Every card has a **Land / Floor area** row, e.g. "152,460 sq ft · 48,000 sq ft".
- Figures of a million or more shorten to "5.49M sq ft".
- The table has right-aligned **Land (sq ft)** and **Floor area (sq ft)** columns.
- Hovering any figure shows the unit it was recorded in ("Recorded as 126 acres").
- *Largest extent* sorts on land in sq ft.

Every property's sq ft figures are worked out when it is saved. Existing
properties were converted when the database was upgraded; their building areas
were recorded in sq ft before, so they keep that unit. The property panel shows
both forms, for example "6.6 acres · 287,496 sq ft". Negative areas are refused.

**Required fields** — every form marks required fields with a red * and says
so once at the top ("* Required"). For a property these are Property name,
Property type, Tenure, Latitude and Longitude, the same five the bulk template
requires; everything else can be added later.

**Bulk upload** — add many properties at once from an Excel file. Open **New
property** and switch to **Bulk upload**:

1. **Download the template** (.xlsx). It is generated from the register at that
   moment and has four sheets:
   - **Properties** — one column per property detail and a frozen heading row.
     Required columns (Property name, Property type, Tenure, Latitude,
     Longitude) have a deep-teal heading with a * and pale yellow cells all the
     way down, so a missed one stands out; optional columns have light
     headings. Each required column's hint starts with "Required". Drop-downs offer the current
     property types, owning companies, tenures, structures, statuses, location
     codes, districts and units. Latitude and longitude are checked against Sri
     Lanka as you type, and every cell shows a short hint when selected.
   - **Instructions** — what to enter in each column.
   - **Example** — two filled-in rows.
   - **Lists** — every allowed value.
2. **Upload the filled file** — the .xlsx, or a CSV with the same headings. Up
   to 2,000 properties and 10 MB.
3. **Review and import** — every row is checked with the same rules as the
   property form before anything is saved. Each row is marked *Ready*, *Ready ·
   check* (a warning, such as a likely duplicate name) or *Needs fixing* (with
   the column and the reason). **Import** saves the rows that are ready, in one
   go, and skips the rest. You can fix those in the file and upload it again.

Things the importer accepts or does for you:

- Property code can be left blank; it is numbered from the property type
  (`BUS-0001`).
- A location code with no coordinates places the property at that location.
- Dates may be typed `2019-03-31` or `31/03/2019`, or be real Excel dates.
- Units can be written as `acres`, `P`, `sq ft`, `m2` and similar.
- Columns can be in any order. Columns the register doesn't use are listed and
  ignored.

A copy of the template is in `docs/templates/`, but download a fresh one from
the app so its lists are current.

**Search and filters** — the tenure tabs (All · Freehold · Leasehold · Rented in ·
Leased out) and the search box sit above everything; the filter button opens
property types, location, owning company, district, tenure, status and structure.
Every active filter shows as a removable chip under the heading, and the count
reads "2 of 13" while any filter is on. Sort by latest, code, name, largest
extent or most documents.

**Documents module** — every document in the register on one page, whichever
property it belongs to. Each row is marked with its **property type**: the
unit's colour dot, code and name. The row also shows:

- the property
- the issue and expiry dates, with anything expired or due within 90 or 180 days badged
- the counterparty and the amount
- the attached file, which you can view or download

Tabs split the list into All · With file · No file · Expiring soon ·
Expired, each with its count. You can narrow it by document type and sort it by
latest, expiry, property type, property or title. The toolbar's search, tenure
tabs and filters apply here too, so searching "Colombo" lists only documents on
properties in Colombo. **Attach document** records a new one: you pick the
property in the form, and you stay on the list afterwards.

Click a row to open the **document panel**, which shows:

- the document's type, title, property type and reference
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
colour alone.

**Business-unit filter** — a row of chips at the top of the dashboard, one per
unit with its colour and property count:

- Click a unit to show only that unit.
- Click more units to compare them together.
- **All units** goes back to the whole register.

It is the same business-unit filter the Portfolio and Documents use, so moving
between modules keeps the selection.

**Click any chart to filter the dashboard.** Clicking a donut slice or legend
row, a bar, a column, a gauge arc or a breakdown row filters every other chart
to match, and the filters combine. For example, *Freehold* in Tenure mix plus
*Western* in Properties by province gives 2 properties.

- **The clicked chart keeps its context:** it shows all its categories, the
  chosen one highlighted and the rest dimmed, so you can compare or switch with
  one click.
- **Clearing:** click the chosen mark again, use the chart's **Clear** button,
  remove a pill from the **Filtered by** row, or press **Clear all**.
- **Tooltips** say whether a click will filter or clear.
- **Keyboard:** Tab to a mark and press Enter or Space.

What each chart filters on:

| Chart | Filters properties by |
|---|---|
| Tenure mix | Tenure |
| Deed & title coverage | With or without a deed |
| Documents by type | Holding a document of that type |
| Renewal pipeline | Having a document in that expiry band |
| Province | Province |
| Structure | Structure |
| Property type (charts, area bars and breakdown) | Property type |
| Owning company (bar name, segment or legend) | Owning company, and property type for a segment |
| Status | Status |
| District | District |

These are the register's shared filters, so the Portfolio, Documents and the
tenure tabs show the same selection.

Below the band come five sections, each headed by a rule:

- *Land & floor area*:
  - **Total land area** and **Total floor area** — the sum over every property
    shown, in square feet. Land is also given in acres and hectares, floor area
    in m² and acres.
  - Each total has a bar split by property type in the type's colour, with a
    legend of each unit's share.
  - A line underneath says how many properties have the area recorded
    ("Recorded for 12 of 14 properties"), so a partial total never passes for
    a complete one.

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
  - **Land by property type** — square feet and share of all land.
  - **Largest holdings** — the five biggest properties by land, in sq ft.
  - **Properties by province** — all nine provinces, shown as bars instead of
    columns on a phone.
  - **Structure** — bare land, land & building, building only.
- *Breakdowns*:
  - **Properties by owning company** — the full total and how much of it a group
    company owns ("14 properties · 8 owned by group companies (57%) · 6 with no
    group owner").
    - **By company** shows a stacked bar per company, split by the business
      units that use its properties, with "Not recorded" last.
    - **By property type** shows a bar per type, split by the companies that own
      what it uses.
    - Each company and unit keeps a fixed colour and position in every bar.
    - Click a bar's name to filter by that company or unit. Click a segment to
      filter by both, e.g. NCGE within Head Office.
  - Properties by status and by property type (in each type's map colour).
  - Properties by district, in columns across a wide card.

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
and coordinates), **Location codes**, **Property types** and **Owning
companies**. A location code is `UNIQUE`, so one code can never stand for two
places — the LLKO-means-both-Kottawa-and-Kegalle defect the blueprint reports is
impossible by construction. A row cannot be deleted while something still points
at it, and the message names every blocker.

Each property links to a location. Choosing one on the property form fills the
district and province, and seeds the coordinates from the location centroid *only
when they are still blank* — a pin you have already placed is never overwritten.
The address lines stay free text for the street detail. Locations added under
Master sheets appear in the property form immediately.

*System lists* (read-only in Stage 1): provinces, districts, structures,
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
├── requirements.txt        Postgres driver, only for Supabase
├── requirements-dev.txt    lint, type check, coverage, audit, browser tools
├── ruff.toml, mypy.ini, .coveragerc
├── Dockerfile              the register as a container image
├── .env.example            Supabase settings; copy to .env
├── .github/                CI, CodeQL and Release workflows, Dependabot
├── tests/                  unittest suite: API, units, storage, Postgres, browser
├── server/
│   ├── app.py              HTTP server, routing, static files
│   ├── api.py              REST handlers and validation
│   ├── db.py               schema (SQLite + Postgres), connections, sample data
│   ├── storage.py          uploaded files: data/uploads or Supabase Storage
│   ├── masters.py          master sheets: registry, generic CRUD
│   ├── errors.py           shared ApiError
│   ├── srilanka.py         districts, provinces, bounds, enumerations
│   ├── multipart.py        file-upload parsing
│   ├── bulk.py             bulk upload: Excel template writer and importer
│   ├── import_sqlite.py    copy a SQLite register into Postgres / Supabase
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

`sbu` — the **property types**: code, name, description, map colour, sort
order, active flag. The table keeps its original name (it started as business
units), so `sbu_id` on a property is its property type. It is deliberately *not*
the owning legal entity and *not* the tenure; those are `legal_entity` and
`ownership_type`.

`legal_entity` — short code, registered name, registration no., notes, active
flag. The group company that **holds title**. A property leased or rented *in*
has none: an outside landlord owns it, and that party is recorded on the lease
document instead. Managed from the **Owning companies** tab.

`property` — property code (unique, auto-generated as `CORP-0001` from the type's
code if left blank), name, property type (`sbu_id`), owning company (optional), **location** (optional, from the location
master), structure (`property_type`), ownership type, status,
address (line 1/2, city, district,
province, postal code), **latitude, longitude**, land extent value + unit
(perch/acre/rood/hectare/m²/sq ft), building area value + unit, **both areas in
square feet** (`extent_sqft`, `building_area_sqft` — calculated on every save),
assessment no., survey plan no.,
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
| GET/POST | `/api/sbus` | list / create property types |
| PUT/DELETE | `/api/sbus/{id}` | update / delete a property type |
| GET/POST | `/api/legal-entities` | list / create owning companies |
| PUT/DELETE | `/api/legal-entities/{id}` | update / delete an owning company |
| GET | `/api/locations` | slim location list for the property form |
| GET | `/api/properties` | list, filtered by `sbu_id`, `legal_entity_id` (or `none`), `location_id`, `ownership_type`, `has_deed` (`0`/`1`), `has_doc_type`, `has_renewal` (`expired`, `m3`, `m6`, `m9`, `m12`, `later`), `district`, `province`, `status`, `property_type`, `q` |
| POST | `/api/properties` | create |
| GET/PUT/DELETE | `/api/properties/{id}` | detail (with documents) / update / delete |
| GET/POST | `/api/properties/{id}/documents` | list / attach (multipart) |
| GET | `/api/documents` | every document with its property and property type; takes the property filters above plus `doc_status` (`file`, `nofile`, `expiring`, `expired`), `doc_type` and `sort` (`newest`, `expiry`, `sbu`, `property`, `title`), and returns per-tab counts |
| GET | `/api/documents/{id}` | one document with its property and property type |
| GET | `/api/documents/{id}/file` | view; add `?disposition=attachment` to download |
| DELETE | `/api/documents/{id}` | remove document and its file |
| GET | `/api/masters` | list the master sheets |
| GET | `/api/masters/{key}` | one sheet: columns, rows and reference options |
| POST | `/api/masters/{key}` | add a row (editable sheets only) |
| PUT/DELETE | `/api/masters/{key}/{id}` | update / delete a row |
| GET | `/api/stats` | summary and chart figures (totals, tenure, types, provinces, document types, renewal buckets, breakdowns); accepts the same filters as `/api/properties` |
| GET | `/api/export/properties.csv` | CSV export |
| GET | `/api/import/template.xlsx` | bulk upload template, with drop-downs from the live register |
| POST | `/api/import/properties` | multipart `file` (.xlsx or .csv) and `mode`: `check` reports every row; `import` saves the rows that pass, in one transaction |

## Sample data

The first run seeds the 8 property types, 13 sample properties across Sri Lanka and 9
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
confirmation, and act on whichever database `.env` names: on Supabase, use
`.venv/bin/python3` in place of `python3`.

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
