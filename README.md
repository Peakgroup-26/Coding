# Peak Hydraulic Take-off & Estimating

A web app for Peak Plumbing & Gas Services that turns commercial hydraulic drawings into measured, staged quantities, and later a priced estimate. It follows the build brief "Hydraulic Take-off & Estimating System — Build Brief for Codex".

**Status: Phase 1 (core take-off) is built.** Phases 2–5 are still to come (see below).

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

## Next phases (from the brief)

2. Fittings and sundries rules engine and editor, check-measure flags, stage rules
3. Pricing: prebuild and rate import, mapping, labour, margins, price-book versions, Simpro CSV
4. AI assistance: sheet classification, legend reading, run and fixture suggestions
5. Revision compare, marked-up PDF export, Microsoft 365 single sign-on

Peak's inputs (the brief's "Inputs Peak must supply") are needed from Phase 2 onwards, especially the fitting and sundry rules, the Simpro prebuild export, the rates, and three completed jobs for the golden-job test.
