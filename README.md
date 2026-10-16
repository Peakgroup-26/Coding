# Peak: estimating, jobs, the team's phones and the money in one place

A web app for Peak Plumbing & Gas Services. It runs the business from first enquiry to paid invoice: estimating and tendering,
live jobs (maintenance to large commercial and civil), scheduling, the team clocking in on their phones, plant and vehicle
pre-starts, purchasing and supplier pricing, invoicing through Xero, customer feedback, and budgets, WIP and cash flow.
The estimating side turns commercial hydraulic drawings into measured, staged quantities and a priced estimate, and civil plans into a bill of quantities priced from Peak's previous civil jobs. It follows the build brief "Hydraulic Take-off & Estimating System — Build Brief for Codex".

**Status:** the operations side (above) is built and tested with sample data. **Estimating: all five phases in the brief are built,** plus the autopilot ("drop the plans in") and the civil BOQ. They have been tested on generated drawings; tuning against Peak's real drawings and data comes next (see "Before going live").

**Putting it on the Plesk server:** see [deploy/PLESK.md](deploy/PLESK.md).

## Operations: from won quote to paid invoice

Everything below is one system: a job won here is scheduled here, clocked onto from the phones, costed by its POs and time,
invoiced through Xero, and rolled up into the WIP, the monthly forecast and the cash flow. Nothing is entered twice.

**Jobs** (Operations → Jobs). A won quote becomes a live job with **Start the job**: it gets a job number (`J26-0001`), a
customer and site record, and a budget from its estimate (labour hours and cost, materials, by stage). Maintenance and small
jobs are raised straight away with **+ New job** (tap-to-pick: sector, customer, type of work, priority, do-and-charge or fixed).
Each job's page has:
- **Overview**: budget against actual against committed against forecast by category, % complete, forecast margin, earned,
  invoiced, over / under billed, retention, and the job's details.
- **Budget**, **Time** (every clock-in, by person and task, with where they clocked in), **POs & costs**, **Variations**
  (approved ones add to the contract and the budget), **Invoices** (progress claims from % complete, or do-and-charge
  from time and materials), **Documents** (folders, versions, which ones show on the phones), **RFIs & defects** (also site
  instructions, incidents, inspections, observations, submittals; an RFI can become a variation), **Site diary** (who was on
  site comes from the timesheets) and **Forms**.

**Schedule** (Operations → Schedule). People down the side, days across. Click to book someone onto a job, drag to move,
**Copy last week**, then **Publish** to put it on their phones. Leave shows on the board. "On the clock now" shows who's working where.

**The phone app** (`/field`, add it to the home screen). The team's "On the tools" logins only get this:
- **Today**: clock in (today's scheduled jobs first), switch jobs, breaks, clock out, with location. No reception? The punch is
  kept on the phone and sent when it's back, with the time it really happened.
- **Jobs**: address and directions, call the contact, scope and site notes, plans and documents, notes and photos, materials
  used, **get a PO number** at the trade counter, forms and SWMS, and **Job finished** with the customer's signature.
- **Schedule**, **Timesheet** (submit the week, add a missed clock-in, ask for leave), and **Crew** for supervisors (clock a
  crew on or off together).
- **Pre-start** (Plant Assessor style), with rules that can each be switched off in Admin → Operations & plant:
  - a company vehicle's driver can't clock in each week until that week's vehicle pre-start is done (with photos)
  - operating a machine needs that day's pre-start with photos of the machine and the fuel gauge, and clocking off needs
    the end-of-day photos
  - a failed pre-start item or reported damage goes to the supervisors; a critical defect takes the machine out of service
  - each driver is reminded monthly to wash their vehicle and send photos of the outside and inside
  - plant hours on a job are charged to it at the machine's hire rate

**Timesheets** (Operations → Timesheets). Everyone's week with ordinary and overtime, flags for long shifts, hand-added and
edited time; approve a week (this fixes the cost rate used for job costing), fix entries (a reason is kept), payroll export, leave.

**Purchasing.** POs on jobs or for stock (`J26-0001-PO3`), print to send, enter or match bills (a bill more than 2% off its PO
is flagged), suppliers and their terms. **Supplier price files:** load each supplier's monthly price list (Reece maX download,
CSV or Excel from anyone else); columns are found by their headings and remembered. **Cheapest supplier** compares every product
sold by two or more suppliers (matched by manufacturer code or barcode), by product line, with what switching would have saved
on the last 12 months' POs, and can make a new price-book version at the cheapest prices.

**Plant & vehicles** and the **Maintenance planner** (assets on customers' sites with service intervals: backflow devices,
TMVs, hot water, grease traps. Due ones become one service job per site; filling in the test report moves the next due date on).

**Customers and feedback** (Customers). Each customer has a type, contacts, sites, jobs, money owed, NPS and a timeline of calls,
notes, tasks and messages. **Feedback & follow-ups** sends what you set per type of customer: e.g. homeowners and maintenance
customers get thanks and a feedback link 2 days after the invoice, and happy ones (9-10) are offered your Google review link;
builders get feedback after the final invoice; commercial and civil clients get a "how did we go this month?" check-in. Answers
come back as NPS by department, client type, customer and month. A score of 6 or less alerts the admins and puts a call-back
task on the customer.

**Money** (Money → Dashboard). **This month so far** against the forecast pro-rated to today by working days, for revenue,
labour, materials and subcontractors, red when costs run more than 5% ahead (or revenue behind), with the jobs behind it.
**WIP**, **cash flow** for the next 13 weeks (invoices on their due dates, work still to bill, wages from the schedule,
supplier bills on their terms, overheads), **budgets** by month (start them from what the live jobs say), **invoices and
aged debtors**.

**Xero.** Invoices go to Xero; payments, supplier bills (matched to POs and jobs by number) and the bank balance come back.
Set up in [deploy/XERO.md](deploy/XERO.md).

**Ask Peak** (the ✦ button on every page, and on the phones). Type or talk: "how many labour hours on the Maroochydore
Apartments job, actual vs estimated?", "which jobs are going over budget?", "who's working right now?", "which supplier is
cheapest for PVC fittings?". It looks it up in the live records and makes the report, downloadable as Excel. It can only read,
and only what the person asking is allowed to see.

**Permissions.** Two more ticks in Admin → People: **Operations** (jobs, schedule, timesheets, purchasing, plant, customers)
and **Finance** (WIP, budgets, cash flow, invoices, supplier prices, Xero). The **On the tools** role gets only the phone app.

## Drop the plans in (autopilot)

The home page has two drop zones: **Hydraulic take-off** and **Civil BOQ**. Drop the whole PDF set on one, and the job is created and read in the background while a progress screen shows where it's up to.

For a **hydraulic** set, the autopilot:

1. splits the PDFs into sheets and has the AI read each one: number, title, revision, scale, sheet type and services;
2. sets each plan's scale from its title block, then **confirms it against dimension strings on the sheet**. Two or more dimensions must agree within 1%, and any nearby dimension that disagrees stops it. If it can't confirm a scale, the plan goes on the "Needs you" list for a two-click check instead of being measured;
3. works out which line colours and layers are which pipes (service, DN, material) from the legend, the layer names and the labels, and traces them into runs;
4. counts items tagged with text on the plan (FW, IO, HR …), leaving out the legend and title block.

The overview then shows what it found, what needs you, and three steps: **check it on the drawings**, **approve everything**, and **download the Excel BOQ** (or Simpro CSV). Nothing the AI finds counts until it's approved. Approving also saves the line colours for that client, so the next set from the same consultant is read the same way without asking the AI.

## Signing in, permissions and the admin portal

Everyone signs in with email and password (or Microsoft 365 once it's set up) and can change their password under **My account**. The **Admin portal** (admins only) has four tabs:

- **People & permissions:** add people and tick what each can see. The options are *Plumbing* jobs, *Civil* jobs, *Everyone's jobs* (other people's and previous tenders; off means only jobs they started), *Past civil rates* (the previous-jobs rates library) and *Edit pricing* (price books, mappings, rules). Admins always see everything. The server enforces these on every request, for any job, sheet, line or document, so hiding a menu isn't the only protection.
- **All jobs:** every plumbing and civil job, who started it, and where it's up to.
- **AI memory:** see below.
- **Lists & settings:** services, stages, materials, count items, benchmarks and the Simpro layout.

## The AI chat panel and memory

Every job has an **Ask the AI** panel down the right-hand side. Tell it what to do, typed or spoken: "make all the sanitary DN150", "trace the green dashed line as 25 copper cold water", "count every FW", "accept the tender items but make night works 15%", "add 120 m of kerb at $85", "what's still to do?". It uses the same actions as the buttons, under the person's own name in the audit log. It lists what it did under each reply. Anything it adds is still a suggestion until approved, and it asks before changing more than 20 things at once.

- **Microphone:** press 🎤 and talk. *Hands-free* sends as soon as you stop talking; *read aloud* speaks the replies. This uses the browser's own speech recognition (Chrome, Edge, Safari) and needs HTTPS. Chrome and Edge send the audio to Google or Microsoft to turn it into text; the text then goes to Anthropic like a typed message.
- **Memory:** when you tell it a preference or correct it ("ABC always draw sewer in brown", "we always use Rehau for acoustic"), it saves a memory for all jobs, that client, or that job. Memories go into every later chat and every automatic read they apply to. Admins can edit, switch off or add memories in the admin portal.
- **One conversation per job,** shared by everyone working on it. Long conversations are summarised automatically, and *New chat* starts afresh (memories carry over).

## Residential, commercial and maintenance

The home page has a tab for each sector. Plans dropped in a tab, and leads added there, belong to that sector:

- Each sector has its own job list, its own quote numbers (`RES-2026-0001`, `COM-…`, `MNT-…`) and its own sales figures.
- An admin can limit people to certain sectors (Admin portal → People & permissions).

**Leads:** *+ New lead* records an enquiry before any plans arrive. Almost everything is tapped, not typed:

- sector, plumbing or civil, type of work (each sector has its own list), where it came from, rough size and when the quote is due are buttons
- client and contact are drop-downs of the ones already used, with *+ New…* for someone new
- the job name fills itself in (e.g. "Hot water – ABC Strata") unless you type one

Drop the plans on it later and it carries on as a normal job.

**Pipeline:** each job shows where it is: **Lead → Quoting → Quote sent → Won / Lost**.

- *Mark quote sent* asks when it went out (Today / Yesterday / pick) and the price. *Lost* and *Withdrawn* ask why, with a tap list of reasons. The dates are recorded as they happen and every date can be corrected.
- An admin edits the tap lists (lead sources, lost reasons, types of work per sector) in Admin portal → Reporting.
- Quoting happens by itself when plans arrive.

## Sales dashboard

**Sales** in the top menu, for all sectors or one, over the last 3, 6, 12 or 24 months:

- **Leads, conversion rates and value:**
  - leads, and the % quoted
  - % of quotes won, and % of leads won overall
  - value quoted and won
- **Time to convert:** average and middle days from lead to quote returned, quote to won, lead to won in total, and quote to lost.
- **Lists:**
  - the pipeline right now, with values
  - quotes waiting on an answer, oldest first (more than two weeks is highlighted for follow-up)
  - leads still to quote, with due dates and anything overdue
- **Breakdowns:**
  - month by month: leads, quotes sent, won, lost and won value
  - by sector, type of work, job size, client, lead source and estimator: quote rate, win rate, value and days to quote
  - why jobs are lost: count, share and value for each reason

Conversion is counted by cohort: of the leads that came in during the period, how many were quoted and how many won. The win rate of quotes decided in the period is shown alongside. Admins can edit the pick lists (Admin portal → Reporting).

## Reports

Each job has a **Reports** page (link at the top of the job), and *Download all reports* gives one Excel workbook with everything:

- **Crew & program.** Set the start date, then either a target duration (the app works out the crew) or a crew size (the app works out how long it takes). You get:
  - plumbers, apprentices and supervisors needed, and project-management hours
  - stage-by-stage dates on a working-day calendar (weekends, QLD public holidays and the Christmas shutdown skipped), as a Gantt chart
  - people on site each week, and the total working days

  Override any stage's crew or start date to match the builder's program.
- **Labour hours** by stage, by service and line by line, showing where each figure came from (price book or productivity rate). Items with no labour rate are listed rather than guessed.
- **Material list** to order from: pipe including waste and rounded up to stock lengths, fittings and sundries, and fixtures. It can be split by stage for staged ordering.
- **Cash flow:** the value earned each month (each stage spread over its working days), for progress claims. This needs a price book on hydraulic jobs.

Labour comes from the price book's prebuild labour hours first, then **productivity rates** (Admin portal → Reporting). Those are Peak's own hours per metre, per item or per civil unit; none are built in, and `docs/productivity-rates-template.csv` shows the layout with example rows that import switched off. The crew settings are admin settings too: hours per day, apprentice ratio and output, people per supervisor, PM %, stock lengths, the shutdown, and your headcount.

The **Reports** page in the top menu covers every job you can see:

- the tender pipeline (pending, won and lost, with values) and your win rate
- tenders due in the next 14 days
- a **workforce forecast**: people needed each week across won jobs (optionally pending ones too), against your headcount, with any short weeks flagged
- how well the AI is doing
- the most common exclusions

Record each tender's result and submitted price at the top of its job page.

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
  access.py           permissions, checked on every request
  chat.py, chat_tools.py   the chat panel: conversation handling and the actions the AI can take
  memory.py           the AI's memory
  reports.py          material lists, labour, crew, programs, cash flow, dashboard
  reports_export.py   the reports workbook
  sales.py            sectors, the lead-to-job pipeline, the sales dashboard
  ops.py              live jobs: job numbers, customers and sites, budgets from the estimate
  timesheets.py       clocking in and out, breaks, overtime, approvals, the schedule
  plant.py            plant and vehicle pre-starts, photos, defects, clock-in rules, wash reminders
  purchasing.py       POs, variations, invoices, aged debtors
  project.py          documents, RFIs and defects, forms, assets and the maintenance planner
  finance.py          job budget vs actual, WIP, month-to-date vs forecast, cash flow
  crm.py, messaging.py  follow-up rules, feedback and NPS; email and SMS
  supplier_prices.py  supplier price files, matching products, cheapest supplier
  xero.py             the Xero connection and sync
  assistant.py        Ask Peak, the company-wide assistant
  scheduler.py        background jobs: messages, reminders, Xero sync
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
