# Peak Hydraulic Take-off & Estimating

A web app for Peak Plumbing & Gas Services that turns commercial hydraulic drawings into measured, staged quantities, and later a priced estimate. It follows the build brief "Hydraulic Take-off & Estimating System — Build Brief for Codex".

**Status: Phases 1 (core take-off) and 2 (rules, staging, check-measure) are built.** Phases 3–5 are still to come (see below).

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

The Phase 1 acceptance criteria from the brief are automated tests in `backend/tests/test_phase1_acceptance.py`:

- A 40-page PDF splits correctly.
- A test line measures within ±0.5%.
- A check that is more than 1% out blocks measuring.
- Export totals equal on-screen totals.

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

If you don't set them, the first admin account is `admin@peak.local` / `changeme`. Change it straight away.

### Settings (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite file in `backend/data/` | Use `postgresql+psycopg://user:pass@host/db` in production |
| `STORAGE_DIR` | `backend/data/files` | Private file store for drawings and renders |
| `SECRET_KEY` | random per start | **Set this**, or everyone is signed out on every restart |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `admin@peak.local` / `changeme` | First admin account, created only when there are no users |
| `MAX_UPLOAD_MB` | 200 | |
| `CORS_ORIGINS` | `http://localhost:5173` | |

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

## Layout

```
backend/app/
  scale.py           scale maths (page size, stated scale, calibration, verification)
  titleblock.py      title-block reading, classification, revision ordering
  pdf_processing.py  page split, render, text and vector extraction
  takeoff.py         measuring rules, verticals, waste, totals
  export.py          Excel BOQ
  routers/           HTTP API
backend/tests/       unit and acceptance tests
frontend/src/        React + TypeScript app (Konva canvas for the take-off overlay)
DECISIONS.md         assumptions and choices made where the brief left room
```

Phase 2's acceptance criteria are tested in `backend/tests/test_phase2_rules.py` and `test_phase2_checks.py`:

- Every generated item traces to its rule and its source.
- Every check-measure test triggers on a job seeded with faults.
- Stage totals reconcile to service totals.

## Next phases (from the brief)

3. Pricing: prebuild and rate import, mapping, labour, margins, price-book versions, Simpro CSV
4. AI assistance: sheet classification, legend reading, run and fixture suggestions
5. Revision compare, marked-up PDF export, Microsoft 365 single sign-on

Peak's inputs (the brief's "Inputs Peak must supply") are needed now, especially the fitting and sundry rules, the Simpro prebuild export, the rates, and three completed jobs for the golden-job test.
