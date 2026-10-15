# Peak Hydraulic Take-off & Estimating

A web app for Peak Plumbing & Gas Services that turns commercial hydraulic drawings into measured, staged quantities and a priced estimate, and civil plans into a bill of quantities priced from Peak's previous civil jobs. It follows the build brief "Hydraulic Take-off & Estimating System — Build Brief for Codex".

**Status: all five phases in the brief are built,** plus the autopilot ("drop the plans in") and the civil BOQ. They have been tested on generated drawings; tuning against Peak's real drawings and data comes next (see "Before going live").

**Putting it on the Plesk server:** see [deploy/PLESK.md](deploy/PLESK.md).

## Drop the plans in (autopilot)

The home page has two drop zones: **Hydraulic take-off** and **Civil BOQ**. Drop the whole PDF set on one, and the job is created and read in the background while a progress screen shows where it's up to.

For a **hydraulic** set, the autopilot:

1. splits the PDFs into sheets and has the AI read each one: number, title, revision, scale, sheet type and services;
2. sets each plan's scale from its title block, then **confirms it against dimension strings on the sheet**. Two or more dimensions must agree within 1%, and any nearby dimension that disagrees stops it. If it can't confirm a scale, the plan goes on the "Needs you" list for a two-click check instead of being measured;
3. works out which line colours and layers are which pipes (service, DN, material) from the legend, the layer names and the labels, and traces them into runs;
4. counts items tagged with text on the plan (FW, IO, HR …), leaving out the legend and title block.

The overview then shows what it found, what needs you, and three steps: **check it on the drawings**, **approve everything**, and **download the Excel BOQ** (or Simpro CSV). Nothing the AI finds counts until it's approved. Approving also saves the line colours for that client, so the next set from the same consultant is read the same way without asking the AI.

## Tender documents

Drop the scope of works, specifications, acoustic reports, design briefs, addenda and tender conditions in with the plans (PDF, Word, Excel or text), or add them later from the job page. The app tells documents from drawings by page size: mostly-A4 PDFs are documents. The AI reads each document **before** the drawings, and lists what changes the take-off or the price. Each item quotes the document's own words and page:

| Type | Accepting it… |
|---|---|
| Material specified (e.g. acoustic PVC in ceilings) | changes that service's pipe material on its runs, and the autopilot uses it from then on. The price follows through the price mappings. |
| Exclusion ("by others") | stops that service (or civil category) being taken off, removes its suggestions, and lists it as an exclusion |
| Allowance (provisional sum, PC item, CCTV, fees…) | adds it to the estimate (or a line to the civil BOQ) |
| Rate loading (night works, access, rock…) | adds the % you set to labour, materials or both for the services or civil category it names |
| Inclusion, commercial risk, note | lists it in the Excel export's **Tender notes** sheet |

The AI never invents amounts or percentages: where the document doesn't state one, the item waits for you to enter it. While the drawings are read, the document requirements are passed to the AI too, so the specified materials and scope steer how the plans are read. Everything can be undone, and removing a document undoes what was accepted from it.

## Civil BOQ

1. **Load previous jobs' rates** (*Civil rates* in the menu): drop in the priced BOQs from past civil jobs, Excel or CSV. Any layout works if it has a header row with *Description* and *Rate* (*Unit* and *Qty* are used too). Section headings become categories.
2. **Drop the civil plans** on the *Civil BOQ* zone. The AI reads each sheet and lists the quantities written on it: pit and pipe schedules, long sections, labelled lengths and areas. It never estimates. Anything it can see but can't quantify is listed as *needs a quantity*.
3. **Duplicates are merged:** a pipe on the plan and on its long section is counted once. The AI decides which items are the same work; the app does the arithmetic.
4. **Each line is priced** from the matching rates in previous jobs (the middle value). It shows which jobs those rates came from, and you can type over any quantity or rate.
5. **Approve** lines one at a time or all together, then **download the Excel BOQ**: priced lines by category with subtotals, plus tabs for unapproved lines and for every quantity by sheet.

Reading the plans again (for example, a new revision) keeps approved lines and typed-in rates. If the new reading differs, it adds a note to the line instead of changing an approved quantity.

## What Phase 1 does

- **Jobs:** name, client, builder, address, quote number and due date.
- **Drawing upload:** one combined PDF or many single-page PDFs, up to 200 MB each, in any order. Each file is split into sheets, and each page is rendered and stored privately.
- **Sheet register:**
  - Reads each sheet's title block for sheet number, title, revision, date and stated scale (e.g. `1:100 @ A1`).
  - Detects the page size and proposes the sheet type and the services shown, with a confidence score.
  - Everything is editable inline. Classification corrections are remembered per client.
  - Duplicate sheets (same number and revision) are hidden. Only the latest revision of each sheet is current.
- **Scale:**
  - Calibrate a sheet from two points and a known distance, or from the stated scale. The stated scale is corrected for page size, so an A1 drawing saved at A3 still measures correctly.
  - **Measuring is blocked until the scale has been checked against a second known dimension and agrees within 1%.**
  - Detail viewports can have their own scale.
  - Recalibrating is refused once runs exist, so measured lengths can't change silently.
- **Tracing runs:**
  - Polylines by service, DN, material, level, stage and location tag.
  - Snaps to line ends in vector PDFs. Shift locks the angle to 45° steps.
- **Verticals:** drops are entered as count × height. Risers are entered as count × height or taken from the job's level table (floor-to-floor heights), and they update when a level changes.
- **Waste allowance:** a percentage per material, set by the admin and shown separately from measured length.
- **Counts:** click-to-count per item type (WC, basin, FW, IO, pit, valve, hydrant, TMV and so on). Each item type has a default service and stage.
- **Suggested vs confirmed:** quantities marked *suggested* never reach the totals or the export until someone confirms them.
- **Running totals:** by service, size and material, by stage, and counts.
- **Excel BOQ export** with these tabs:
  - Summary
  - By service
  - By stage
  - Counts
  - Run detail, which traces each run to its sheet and revision
  - Count detail
  - Sheet register

  The export and the screen use the same totals function, so they always match.
- **Roles:** Estimator, Reviewer and Admin. The admin maintains services and colours, stages, materials and waste %, count items, and users.
- **Audit log:** every create, update, calibration and verification is recorded with before and after values.

## What Phase 2 adds

- **Fittings and sundries rules engine.** Rules are Peak's own allowances, kept as data. **None ship with the system.** Each rule has:
  - a trigger
  - filters for service, material, DN range, fixture type and angle band
  - a quantity formula
  - an output item description, a unit and a stage

  The six trigger types are:

  | Trigger | Formula variables |
  |---|---|
  | Per fixture | `n` = 1 per fixture |
  | Per metre of run | `m` = metres, `dn` |
  | Per change of direction (angle band, from the traced vertices) | `n` = bends |
  | Per branch connection (a run joining another part-way along) | `n` = branches |
  | Per IO requirement (free ends, bends, every X m) | `n` = IO locations |
  | Per job (sundries) | `m` = total metres, `fixtures` = fixture count |

  Formulas are plain arithmetic, e.g. `ceil(m / 1.2)`, evaluated safely. Output descriptions can use `{dn}`, `{material}`, `{main_dn}` and similar fields.
- **Rule editor** (Rules page) plus **CSV import and export**. `docs/fitting-rules-template.csv` has the columns and a few rows labelled *EXAMPLE*, which are imported as inactive. Fill it in with Peak's values and import it.
- **Generated items** trace to their rule (and its version) and their source: a run, a fixture, or the whole job. Click through to the drawing. Quantities and stages can be overridden with a note, and overrides survive regeneration. Items can also be added by hand.
- **Staging:**
  - The rule's stage, or else the source's stage.
  - Fixtures default to Fit-off.
  - A stage × service matrix that reconciles to the service totals.
- **Check-measure** flags problems and never fixes them. Each flag links to its spot on the drawing. It checks for:
  - hydraulic sheets with nothing measured
  - open run ends
  - fixtures with no drainage or water run connected
  - drainage size jumps, where a run flows into a smaller one
  - sheets with the same stated scale but different calibrations
  - benchmark ratios outside Peak's band
  - duplicate or overlapping runs
  - an independent second-pass total
  - unconfirmed items
  - fittings not yet generated
- **Reviewer sign-off:** "Sign off as final" re-runs the checks and needs every flag resolved or accepted with a note. A final estimate is locked until a reviewer reopens it.
- **Audit log** per job: who changed what, with before and after values, including deleted items.
- The **Excel export** adds three tabs: *Stage x service*, *Fittings and sundries* (with the AS/NZS 3500 disclaimer) and *Flags and notes*.

Drainage runs are traced **in the direction of flow**. The viewer shows flow arrows, and the run editor has a *Reverse direction* button. Size-jump checks rely on this.

## What Phase 3 adds

- **Price books (versions):**
  - Import Peak's price list, prebuilds and labour rates from CSV or Excel into a draft version.
  - Columns are recognised from Simpro-style headings, and any column can be named explicitly.
  - Prebuilds can be one row per component (the Simpro export layout) or have a components column. Prebuilds can contain other prebuilds.
  - Set the default labour rate, then **lock** the version. Locked versions never change, and jobs keep the version they were priced on. For new prices, copy the version.
  - `docs/sample-price-book/` has made-up *SAMPLE* files for trying it out.
- **Mappings:**
  - Each take-off item maps to a prebuild or catalogue code: a pipe by service, material and DN; a counted item by type; a fitting line by description.
  - A rule's catalogue item is used automatically.
  - Mappings use codes, so they carry across versions.
  - Unmapped items are listed on the job's Pricing tab, each with a one-click map.
- **Job pricing:**
  - Material is the sum of component costs. Labour is prebuild hours × the charge-out rate.
  - Margin works as markup on cost or margin on sell. Set it per job, with per-service and per-stage overrides.
  - PC items, provisional sums (with or without margin) and exclusions.
  - GST is shown separately. Totals are given by stage and by service.
- **Unmapped items and codes missing from the price book block sign-off.** Accepting the flag doesn't get around it. A draft price book also blocks sign-off.
- **Simpro CSV** export. The admin sets its columns, grouping and whether PC items and provisional sums are included. The Excel BOQ also gets a **Pricing** tab.
- **Golden-job comparison:**
  - Upload Peak's known final quantities (service, dn, material, qty) for a completed job, and enter its known total.
  - The app reports the variance per service and per line, and on price.

## What Phase 4 adds

Everything here only *suggests*. Suggestions are drawn dashed, labelled, and stay out of totals, fittings and pricing until someone confirms them.

- **AI sheet reading (optional, off by default).**
  - With `TAKEOFF_AI=claude` and an Anthropic API key on the server, *Read sheets with AI* sends each unconfirmed sheet's image and text layer to Claude.
  - It reads the title block (number, title, revision, scale), the sheet type and services, and any legend.
  - It fills in only sheets that haven't been confirmed. A person still confirms each one.
  - Drawings leave Peak's server when this is on, so turn it on deliberately.
- **Line styles to suggested runs.** This runs locally.
  - A sheet's vector line work is grouped by colour, line type, width and CAD layer, with the length of each style.
  - Tick the styles that are pipework and say what each is (service, DN, material). Hovering highlights where each is drawn.
  - *Suggest runs* chains each style into runs: it follows connected segments, breaks at junctions, and bridges small gaps in exploded dashes.
  - Styles are remembered per client, so the next sheet from the same consultant needs one click.
- **Symbol matching.** This also runs locally.
  - Select one counted symbol, then *Find more like this one*. It searches the sheet image, including rotated copies.
  - Each match becomes a suggested count.
- **Review:** confirm or reject one at a time, or *Accept all* / *Reject all* on a sheet.
- **Statistics:**
  - Each sheet shows how many suggestions were accepted as is, edited then accepted, rejected, or still pending.
  - Classification accuracy compares the first proposal (keywords, remembered, or AI) with what people confirmed, against the brief's 90% target. The test set is every confirmed sheet.

## What Phase 5 adds

- **Revision compare.** Upload Rev B; Rev A drops out of the totals. On Rev B, *Compare with Rev A* shows:
  - added line work (green) and removed line work (red), with each changed area boxed so you can step through them
  - runs measured on Rev A that sit on changed line work
  - new line work that isn't measured yet

  Vector sheets are compared line by line, per colour. Scanned sheets fall back to an image comparison.
- **Carry forward.** After verifying Rev B's scale (scales are never copied), bring Rev A's runs and counts across as suggestions to review. Ones on changed line work are noted.
- **Marked-up PDF** from the job page:
  - a cover page with job totals
  - each measured sheet with its runs (solid = confirmed, dashed = suggested), counts, DN and length labels, and a legend with that sheet's totals
- **Keyboard shortcuts help:** press `?` in the viewer.
- **Microsoft 365 sign-on** (Entra ID, OpenID Connect with PKCE). Set `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` and `SSO_REDIRECT_URI` (`https://<your host>/api/auth/sso/callback`).
  - Optionally restrict to `SSO_ALLOWED_DOMAINS=peakpcg.com.au`.
  - By default people must already have an account (an admin adds them by email), so roles stay controlled. `SSO_AUTO_CREATE=true` creates estimators instead.
  - Email and password sign-in keeps working alongside it.

## Before going live

- **Run it on real drawings.** Run three of Peak's completed jobs end to end and record the variance per service: this is the brief's golden-job test, using the *Compare with a completed job* panel. Tune title-block reading, connection tolerances and the line-style chaining on real consultant sheets.
- **Load Peak's data:**
  - fitting and sundry rules (`docs/fitting-rules-template.csv`)
  - the price book, from the Simpro exports
  - waste % per material
  - benchmarks
- **Match the Simpro CSV layout** to Peak's actual Simpro import.
- **Production setup:** follow [deploy/PLESK.md](deploy/PLESK.md). It covers HTTPS, the settings file with random secrets, nightly backups and updates. The AI needs an Anthropic API key; without one the app runs, but sorts sheets by keywords only and takes nothing off automatically.
- **Check the autopilot on real sets.** Watch how often it confirms scales from dimensions and names the line colours correctly on Peak's consultants' drawings, and tune it from there. Civil quantities should be spot-checked against the schedules on the first few jobs.
- **Have a developer review the code and hosting,** as the brief recommends.

Peak's inputs (the brief's "Inputs Peak must supply") are needed now, especially the fitting and sundry rules, the Simpro prebuild export, the rates, and three completed jobs for the golden-job test.

## Running it

You need Python 3.11+ and Node 18+.

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m pytest                 # run the tests
SECRET_KEY=some-long-random-string \
ADMIN_EMAIL=you@peakpcg.com.au ADMIN_PASSWORD='choose-a-password' \
python -m uvicorn app.main:app --port 8000

# Frontend (development, with hot reload; proxies /api to :8000)
cd frontend
npm install
npm run dev                      # open http://localhost:5173
```

For a single server, run `npm run build` in `frontend/`. The backend then serves the built app at http://localhost:8000.

### With Docker (production-style)

```bash
cp .env.example .env      # fill in SECRET_KEY, POSTGRES_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up --build -d
```

This runs the app (API plus built frontend, as a non-root user) and PostgreSQL 16. Drawings go in the `files` volume, or in S3 with `STORAGE_BACKEND=s3`. The app only listens on `127.0.0.1`, so put HTTPS in front of it. On the Plesk server, `deploy/install.sh` does all of this and `deploy/PLESK.md` explains each step.

### Database migrations

The app applies Alembic migrations automatically on startup. After changing `app/models.py`, generate a migration:

```bash
cd backend && alembic revision --autogenerate -m "what changed"
```

`tests/test_migrations.py` fails if the models and migrations disagree. Development databases made before migrations existed are adopted only if they already match; otherwise delete `backend/data/`.

If you don't set them, the first admin account is `admin@peak.local` / `changeme`. Change it straight away.

### Settings (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite file in `backend/data/` | Use `postgresql+psycopg://user:pass@host/db` in production |
| `STORAGE_DIR` | `backend/data/files` | Private file store for drawings and renders (the cache when using S3) |
| `STORAGE_BACKEND` | `local` | `s3` keeps files in a private, encrypted bucket |
| `S3_BUCKET` / `S3_PREFIX` / `AWS_REGION` | – / `takeoff` / `ap-southeast-2` | AWS credentials come from the usual `AWS_*` variables or an instance role |
| `S3_ENDPOINT_URL` | – | For S3-compatible storage other than AWS |
| `SECRET_KEY` | random per start | **Set this**, or everyone is signed out on every restart |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `admin@peak.local` / `changeme` | First admin account, created only when there are no users |
| `MAX_UPLOAD_MB` | 200 | |
| `CORS_ORIGINS` | `http://localhost:5173` | |
| `TAKEOFF_AI` | off | `claude` turns on AI sheet reading (needs `ANTHROPIC_API_KEY`). Drawings are sent to Anthropic's API when used |
| `TAKEOFF_AI_MODEL` | `claude-opus-5-5` | Model for AI sheet reading |
| `SSO_TENANT_ID` / `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` | off | Microsoft 365 sign-on (all three turn it on) |
| `SSO_REDIRECT_URI` | `http://localhost:8000/api/auth/sso/callback` | Must match the app registration in Entra ID |
| `SSO_ALLOWED_DOMAINS` | any | e.g. `peakpcg.com.au` |
| `SSO_AUTO_CREATE` | off | Create unknown users as estimators |

## Viewer shortcuts

| Key | Action |
|---|---|
| T | Trace a run (click points; double-click or Enter finishes; Backspace removes the last point) |
| N | Count |
| R | Riser or drop |
| K | Calibrate |
| H / Esc | Pan and select |
| `[` / `]` | Previous or next service |
| S | Snap on or off |
| F | Fit sheet |
| Shift | Lock to 45° while tracing |
| Space + drag | Pan |
| Del | Delete the selected item |
| ? | Show all shortcuts |

## Layout

```
backend/app/
  scale.py            scale maths (page size, stated scale, calibration, verification)
  titleblock.py       title-block reading, classification, revision ordering
  pdf_processing.py   page split, render, text and vector extraction
  takeoff.py          measuring rules, verticals, waste, totals
  rules.py, expr.py   fittings and sundries rules engine, safe formulas
  geometry.py         connections, bends, branches, overlaps
  checks.py           check-measure
  pricing.py          price books, mappings, cost, margin, GST
  pricebook_import.py CSV/Excel price list, prebuild and rate import
  simpro.py           Simpro CSV
  ai.py, suggest.py   AI sheet reading; line-style and symbol suggestions
  assist.py           AI steps shared by the sheet tools and the autopilot
  autopilot.py        drop-the-plans-in pipeline (runs in the background)
  autoscale.py        confirms a scale against dimension strings on the sheet
  civil.py            civil BOQ: rate import, merging, pricing from past jobs, export
  tender.py           tender documents: reading, and applying / undoing their requirements
  revision.py         revision compare
  markup.py           marked-up PDF
  sso.py              Microsoft 365 sign-on
  storage.py          local or S3 file storage
  migrate.py          applies database migrations on startup
backend/migrations/   Alembic migrations
  export.py           Excel BOQ
  routers/            HTTP API
backend/tests/        unit and acceptance tests
frontend/src/         React + TypeScript app (Konva canvas for the take-off overlay)
docs/                 fitting rules template, sample price book
deploy/               Plesk guide, install / update / backup scripts, nginx settings
DECISIONS.md          assumptions and choices made where the brief left room
```

## Tests

`cd backend && pip install -r requirements-dev.txt && python -m pytest` runs every phase's acceptance criteria from the brief as automated tests. Set `TEST_DATABASE_URL=postgresql+psycopg://…` to run them against PostgreSQL. GitHub Actions (`.github/workflows/ci.yml`) runs these on every pull request:

- lint
- the tests on SQLite and on PostgreSQL 16
- the frontend typecheck and build

Phase 1's are tested in `backend/tests/test_phase1_acceptance.py`:

- A 40-page PDF splits correctly.
- A test line measures within ±0.5%.
- A check that is more than 1% out blocks measuring.
- Export totals equal on-screen totals.

Phase 2's acceptance criteria are tested in `backend/tests/test_phase2_rules.py` and `test_phase2_checks.py`:

- Every generated item traces to its rule and its source.
- Every check-measure test triggers on a job seeded with faults.
- Stage totals reconcile to service totals.

Phase 3's are tested in `test_phase3_pricing.py`:

- An imported price book reproduces a known estimate within ±1%.
- Unmapped items block final pricing.

Phase 4's are tested in `test_phase4_ai.py`:

- Suggestions never enter totals or pricing unconfirmed.
- Accepted, edited and rejected counts are tracked.
- Accuracy is measured.

The 90% classification target can only be checked on Peak's own drawings.

Phase 5's are tested in `test_phase5_polish.py`:

- Revision compare highlights the added and removed runs between two revisions of a test sheet.
- Carry-forward works.
- The marked-up PDF is produced.
- Sign-on handles both the successful and the refused cases.
