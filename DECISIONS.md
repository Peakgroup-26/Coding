# Decisions and assumptions

These are choices made where the brief left room, as it asks. Each one can be revisited.

## Phase 1

1. **SQLite by default, PostgreSQL in production.** Everything uses SQLAlchemy, so `DATABASE_URL` switches databases. Tables are created on startup. Add Alembic migrations before the first production deployment, so schema changes from later phases don't need a reset.

2. **Uploads are processed straight away, not on a background queue.** Splitting, rendering and text and vector extraction run during the upload request. A 40-page A1 set takes a few seconds. Celery or RQ with Redis should take this over when OCR and AI suggestions arrive (Phase 4), or if real drawing sets turn out slow. `DrawingFile.status` already exists for that.

3. **Sheets are shown as server-rendered PNGs, not PDF.js.** Each page is rendered once with PyMuPDF (longest side 5000 px) and drawn on a Konva canvas. This keeps the browser fast on large A1 and A0 sets and gives one coordinate system. All geometry is stored in PDF points on the displayed page, never in screen pixels, as the brief requires. PDF.js can still be added later for crisper deep zoom.

4. **Snapping uses vector line ends extracted on the server** (lines, curve ends and rectangle corners), stored per sheet as JSON. They are capped at 250,000 points per sheet.

5. **No OCR yet.** Tesseract isn't installed in the build environment. Sheets without a text layer are flagged "No text layer" in the register, and their fields are typed in. Add OCR alongside the background queue.

6. **Title-block reading looks at the bottom-right 38% × 45% of the page,** where most Australian title blocks sit. It reads the labelled `DRAWING NO` / `SHEET NO` first, then sheet-number-like tokens such as `H-101` or `HYD-201`. The largest text in that area is taken as the title. All of it is a proposal for the user to confirm.

7. **Revision order:** preliminary revisions (P1, P2, …) come before issued ones. Letters sort alphabetically and numbers numerically. The highest revision of each sheet number is current. Measuring on a superseded sheet is refused, and runs already on it drop out of the totals (reported as "superseded").

8. **Scale tolerance is 1%, applied to both the sheet scale and detail viewport scales.** A new calibration always resets verification. Recalibrating is refused while runs exist at the old scale, so delete them first. This stops measured lengths changing without anyone noticing.

9. **A stated scale with a paper size (e.g. `1:100 @ A1`) is corrected for the actual page size.** An A1 drawing saved at A3 is scaled up by 841/420. If no paper size is stated, the page is assumed to be the intended size. The two-point calibration also warns when it differs from the stated scale by more than 1%.

10. **A run inside a detail viewport uses that viewport's scale.** A run crossing a viewport edge is refused, and the user splits it at the boundary.

11. **Lengths are rounded to 2 decimal places on each run, and totals are added up exactly (Decimal) from those rounded values.** This is what makes the screen and the export match to the cent.

12. **Waste % is copied onto each run when it is created** from the material's current value, and can be edited on the run. Changing a material's waste % later doesn't change runs already measured. Defaults are 0% until Peak supplies its own figures (brief: "Peak's rules, not invented ones").

13. **Vertical lengths:** a drop or riser is either count × height, or count × the sum of floor-to-floor heights from the lower level up to (not including) the upper level, ordered by RL. A riser is a run with a single point and no plan length.

14. **Manually entered quantities are confirmed when created.** The *suggested* status is for automated output (legend matching, AI, from Phase 4). It can also be set by hand, and those items stay out of totals until confirmed.

15. **Count items have their own default stage.** Fixtures default to Fit-off. Other items fall back to their service's default stage.

16. **Auth uses email and password, PBKDF2-SHA256 hashing, and HMAC-signed bearer tokens** that last 12 hours. Files are served only through authenticated endpoints, so there are no public URLs. Microsoft 365 single sign-on is in Phase 5.

17. **Admin lists are retired, not deleted** (the `active` flag), so old jobs keep their references.

18. **Local disk storage** sits behind `storage.py`. Swap in an S3-compatible bucket (AWS Sydney) for production by implementing the same functions.

19. **Default service colours** follow common hydraulic drafting practice and are editable: cold water blue, hot water red, sanitary brown, stormwater green, fire magenta, gas yellow.

## Phase 2

20. **Rules write a description, not only a catalogue link.** The brief's Rule has an `output_item_id`, but Peak's catalogue and prebuilds don't arrive until Phase 3. So each rule also has an output description template (`{material} DN{dn} 88° bend`) and a unit. `output_item_id` is optional now. Phase 3 maps descriptions to catalogue items and prebuilds.

21. **Formulas are evaluated by a small whitelist evaluator** (numbers, `n`, `m`, `dn`, `fixtures`, arithmetic, `ceil`, `floor`, `round`, `min`, `max`, `abs`). They are never run with `eval`.

22. **One generated line per rule per source.** A source is a run, a counted item, or the job. Lines are only added up for display and export. This keeps each line traceable, as the brief requires.

23. **Overrides survive regeneration** when the rule, source and description still match. If a line disappears because the run was deleted or the rule no longer matches, its override goes with it, and the generate result says how many were dropped. Rule-generated lines can't be deleted, only set to 0 with a note. Lines added by hand can be deleted.

24. **Bends come from traced polyline vertices.** The deflection angle is the change of direction, so a square corner is 90°. Each rule matches an angle band, e.g. 67.5–95° for an "88° bend". Deflections under 5° are treated as drafting wobble.

25. **A branch is a run end that meets another run of the same service part-way along it,** or at one of its interior vertices. End-to-end joins are not branches. Runs and risers only connect within the same service. Counted items connect to any service.

26. **Connection tolerances are measured on the page,** not in metres, so they don't depend on scale. Run ends join within 6 pt (about 2 mm on paper). Fixtures join within 20 pt (about 7 mm), because symbols are bigger than the point clicked.

27. **IO "at ends" means run ends that don't join another run of the same service:** heads of drains, and ends at fixtures or pits.

28. **Drainage is traced in the direction of flow.** The size-jump check reads the run a run's end flows into as downstream. The viewer shows flow arrows on drainage and stormwater, and *Reverse direction* fixes runs traced the other way.

29. **Service kind** (drainage, stormwater, water, fire, gas, other) and each count item's *needs drainage* / *needs water* settings drive the check-measure connection checks. Both are admin-editable.

30. **Duplicate checks:**
    - Same sheet, same service, with more than 80% overlap: flagged as an error.
    - Different sheets, same service, DN, material and level, with lengths within 1%: flagged as a warning. It may be legitimate, so accepting it with a note is expected.

31. **The second-pass check** re-derives every run from its stored geometry, scale and levels, independently of the stored figures, and compares that with the displayed total.

32. **No benchmarks are seeded.** Peak sets them on the Admin page.

33. **Sign-off needs the Reviewer or Admin role.** It re-runs the checks first. While a job is final, all its measurements, sheets, levels and items are read-only. The PATCH endpoint can't set the status to final directly.

34. **Audit entries now store the job id,** so a job's log includes items that have since been deleted.

35. **Schema:** Phase 2 adds tables and columns. The development database is created with `create_all`, which doesn't alter existing tables, so delete `backend/data/` after updating. Alembic migrations are needed before production. That's still a to-do.

## Phase 3

36. **Prices are versioned; mappings are not.** Price items, prebuilds and labour rates belong to a price-book version. Mappings point at codes, not rows, so one set of mappings works with every version. A job points at one version.

37. **Draft, then locked.** Imports and edits only go into a draft version. Locking freezes it. A job can be priced on a draft while it's being checked, but sign-off needs a locked version.

38. **The estimate is worked out live and not stored.** It's recalculated from the take-off, mappings and price book on every view, so it can't drift from the quantities. Once a job is final, both its quantities and its locked price book are frozen, so the figure can't change.

39. **Money is Decimal, rounded to the cent per line.** Totals are sums of the rounded lines. GST is rounded once, on the total.

40. **Pipe is priced on its total length:** plan plus vertical plus waste, the same figure as the BOQ.

41. **Fitting lines are priced by exact description,** which is case-insensitive. When a rule names a catalogue item, that code is used without a mapping.

42. **Prebuild cost** = Σ(component qty × component unit cost) + labour hours × rate. A component can be a catalogue item or another prebuild, nested up to 5 deep. If a prebuild has no labour rate code of its own, it uses the version's default rate. Codes the price book doesn't have are reported as missing, not priced at $0, and they block sign-off.

43. **Margin precedence:** a stage margin beats a service margin, which beats the job default. "Markup" means sell = cost × (1 + p). "Margin" means sell = cost ÷ (1 − p). It is a per-job choice that defaults to markup. PC items and provisional sums take the margin for their service and stage, unless *add margin* is off.

44. **Simpro CSV:** Simpro import layouts vary by setup, so the columns are an admin template, not a fixed format. The default is Part Number, Description, Type, Quantity, Unit Sell Price, Cost Centre (= stage), Section (= service). It needs checking against Peak's actual Simpro import before first use.

45. **Price-book import column matching** ignores case and punctuation and uses common Simpro headings. Unknown layouts can name their columns as JSON. Rows with bad numbers are skipped and reported, and the rest are imported.

46. **Golden-job comparison** compares known quantities against the take-off's total metres, including waste, per service and per line. The known total is compared with the estimate's sell price ex GST.

## Phase 4

47. **AI is opt-in and limited to sheet reading.** Drawings are commercial-in-confidence (a non-negotiable in the brief), so nothing goes to an outside service unless `TAKEOFF_AI=claude` is set. Run and fixture suggestions use local methods instead (vector analysis and image matching), which are fast and free, and work offline.

48. **The AI sits behind an interface** (`SheetReader` in `ai.py`), so the provider or model can change without touching the rest. The Claude reader:
    - sends the rendered sheet (scaled to a 2000 px long side) plus the PDF text layer
    - asks for a JSON-schema structured output with effort `low`
    - turns on the API's server-side refusal fallback
    - treats a refusal, a cut-off response or an API error as "unavailable" for that sheet, not as a failure of the take-off

49. **AI readings never overwrite a confirmed sheet.** They only fill fields the AI actually read. The raw reading, including the legend, is kept on the sheet for reference.

50. **Classification accuracy is measured against people's confirmations.** The first proposal for a sheet is stored when it's made. The test set is every confirmed sheet, so the brief's 90% target can only be checked once Peak has confirmed real sheets.

51. **Line styles are keyed by colour, line type, width and CAD layer,** taken from the PDF's vector paths. Styles assigned to a service are remembered per client, on the basis that consultants reuse their CAD standards.

52. **Chaining suggested runs:**
    - Segments join where exactly two meet and break at junctions and ends, so each polyline is one run and branches meet the main mid-run, as Phase 2's branch rule expects.
    - Gaps of up to 4 pt between pieces pointing the same way are bridged, for dashes that CAD has exploded into separate lines.
    - Pieces under 0.5 m are dropped.
    - A suggestion that overlaps an existing run of the same service by more than 80% is skipped.
    - Direction is arbitrary, so check the flow arrows on suggested drainage and use *Reverse direction*.

53. **Symbol matching** uses normalised cross-correlation on the rendered sheet, trying the example at 0°, 90°, 180° and 270°. The match threshold and box size are adjustable. Matches near an existing count of the same item are skipped. It finds the same symbol at the same scale; it doesn't recognise a symbol drawn differently.

54. **Outcome tracking:**
    - *Accepted* means confirmed unchanged.
    - *Edited* means changed while suggested, then confirmed.
    - *Rejected* means deleted while suggested.

    Manual items aren't counted.

## Phase 5

55. **Revision compare assumes both revisions share a page frame,** which is normal for consultant re-issues. If a revision has shifted, the API takes an offset (`dx`, `dy` in points). Vector sheets are compared per colour, with a 1.5 pt tolerance and slivers under 3 pt ignored. Nearby changes within 30 pt are grouped into one region. Scanned sheets use an image difference: darker in the new revision means added, darker in the old means removed.

56. **A measured run is "affected" by a revision** when at least 20% of its length lies on removed line work.

57. **Carry-forward never copies the scale.** The new revision must be calibrated and verified first (non-negotiable 3). Runs are re-measured at the new scale. Everything arrives as suggested, with `source = "carried"`, so it stays out of totals until reviewed. Items already on the new sheet are skipped.

58. **The marked-up PDF overlays the original page,** so it stays vector and prints crisply. Suggested items are included and drawn dashed or hollow unless `include_suggested=false`. Legend totals count confirmed items only.

59. **Microsoft 365 sign-on** uses the authorisation code flow with PKCE, a nonce and a signed state cookie (10 minutes, HttpOnly). The ID token's signature is checked against Microsoft's published keys, along with its audience, issuer, expiry and nonce. The app token is handed back in the URL fragment, so it isn't sent to the server or written to logs. Unknown users are refused unless `SSO_AUTO_CREATE` is set, and roles are always managed by an admin in the app.

## Production readiness

60. **Migrations run on startup** (`alembic upgrade head` inside the app's lifespan), so a deploy can't run against an out-of-date schema. That's why the container runs one process: run more containers rather than more workers per container. A database created before migrations existed is adopted (stamped) only when its schema already matches the models, so it never silently runs on a mismatched schema. `render_as_batch` keeps migrations working on SQLite as well as PostgreSQL.

61. **S3 is the source of truth when on, and the local disk is a cache.** Every new file is uploaded as soon as it's complete, with server-side encryption (AES256). Reads fetch from the bucket when the cache doesn't have the file, so servers are disposable. Files are still only served through authenticated endpoints, never as bucket URLs. The default region is ap-southeast-2 (Sydney), for data residency.

62. **CI** runs lint (pyflakes), then the backend tests on SQLite and on PostgreSQL 16, then the frontend typecheck and build.

63. **The Docker image** builds the frontend in a Node stage and runs on `python:3.12-slim` as a non-root user. It has a health check and trusts proxy headers, so HTTPS termination in front gives correct redirect URLs for sign-on. The compose file is for a single server or a trial. A larger deployment would use managed PostgreSQL (e.g. RDS in Sydney) and S3.

## Autopilot and civil BOQ

64. **"Fully AI driven" still keeps the sign-off.** The brief's non-negotiable 2 (a person signs off AI suggestions) stays. The autopilot does all the reading, scaling, tracing and counting, but its work arrives as suggestions behind one *Approve everything* button. One click is the least sign-off there can be while a person still owns the numbers.

65. **Automatic scale confirmation uses the drawing's own dimensions.** The second dimension the brief requires is a dimension string on the sheet (e.g. "3600") beside a parallel line whose length matches at the stated scale. Two matches within 1% confirm it. Any dimension within 10% but outside 1% counts as a disagreement and blocks it (non-negotiable 3). A sheet it can't confirm is never measured; it goes on the "Needs you" list.

66. **The AI names line styles; the app measures them.** The AI only says which colour, dash or layer is which service, DN and material, and only assignments it rates at 0.5 confidence or above are used. The lengths come from the PDF's vector geometry at the verified scale, never from the AI. Styles are only saved as the client's mapping once their runs are approved.

67. **Counts come from text tags, not from the AI pointing at the drawing.** Vision models aren't reliable at giving positions. The AI says which tag means which item (FW = floor waste); the app finds every tag in the PDF's text layer and places a count there. Tags in a legend line or the title block are skipped. Symbol-only items are still counted with *click one, find the rest* (Phase 4).

68. **Civil quantities are read, never estimated.** The AI lists only quantities written on the sheet (schedules, long sections, labels) and says where each came from. The AI groups duplicates across sheets and says whether to count once or add up; the app does the arithmetic. A group mixing units is rejected.

69. **Civil rates are the median of the matching past rates,** with each source job listed. Without AI the match is on wording (shared words, the same unit, and the same sizes). With AI, the model picks from the eight best wording matches, so it can't pick a rate that isn't in Peak's history.

70. **Re-reading never overwrites approved civil quantities.** New readings attach to the approved line (same unit, similar wording), and a change adds a note for a person to act on.

71. **The autopilot runs in background threads in the app process** (`AUTOPILOT_WORKERS`, default 2). This suits one server. If the server restarts mid-read, the job shows *interrupted* with a button to carry on. A blank API key turns the AI off rather than failing the read, and one sheet the AI can't read doesn't stop the rest.

72. **Deployment on Plesk:** the app container listens on `127.0.0.1` only, and Plesk's nginx forwards the subdomain to it over HTTPS (Let's Encrypt). Docker is installed from Docker's own apt repository if Plesk hasn't already installed it. Backups (database, drawings, settings) run nightly to `/var/backups/peak-takeoff` and are kept for 14 days. They should also be copied off the server.

## Tender documents

73. **Documents are told from drawings by page size.** A PDF whose first pages are mostly A4 (or smaller) is a document; anything else is a drawing set. Word, Excel and text files are always documents. A drawing set issued at A4 would be read as a document. It can be removed and re-added as plans, but that's rare in commercial hydraulic work.

74. **Requirements are typed so each has a defined, reversible effect.** There are seven types: material spec, exclusion, inclusion, allowance, rate loading, risk and note. Accepting one makes a specific change and records exactly what changed, so *Undo* (and removing the document) can reverse it. Free-text advice with no defined effect would have no traceability.

75. **The AI never sets money or percentages.** Amounts are only taken when the document states them (e.g. a provisional sum). Loadings for night works, access, rock and so on wait for the estimator to enter the %. Only then can they be accepted. This keeps Peak's commercial judgement with Peak.

76. **Loadings are explicit, not hidden in rates.** In hydraulic pricing a loading raises the labour and/or material cost of the services it names. The pricing tab shows the total loading and what it came from. In a civil BOQ each loading is a separate line under the subtotal, on the approved lines of its category.

77. **Specified materials override what the drawing reading says,** for that service, on this job only. Existing runs are changed when the requirement is accepted, and new runs from later reads use it automatically. A material the price book doesn't know yet is created (waste 0%) so it can be mapped; until it's mapped, pricing lists it as unmapped rather than guessing a price.

78. **Long documents are read in parts** (about 150,000 characters each, split at page breaks), and duplicate items across parts are merged. Scanned PDFs with no text are sent to the AI as PDFs (up to 30 MB). The document text is kept so it can be re-read later without the original.

## Permissions, chat and memory

79. **Permissions are enforced once, centrally.** Every router runs `access.enforce`. It finds the job behind any id in the URL (job, sheet, run, count, line, document, requirement, allowance, level, flag, viewport, generated item) and answers 404 if the person can't see it, so a new route can't forget the check. Areas without a job (the past-rates library, pricing edits) are checked by path. The job list is filtered the same way. Five permissions cover what was asked. Roles (estimator, reviewer, admin) keep their meaning for sign-off.

80. **"Everyone's jobs" covers previous tenders.** With it off, a person sees only the jobs they started. Jobs made before this change have no recorded starter, so only people with "Everyone's jobs" (and admins) see them.

81. **People without the past-rates permission still get civil lines priced from history.** The rate is shown, but which previous jobs it came from is hidden. Otherwise the permission would stop them pricing at all.

82. **The chat acts through tools, not free text.** About 25 tools wrap the same functions as the buttons. Each change is audited under the person chatting. Changing tools refuse while the job is final or while the autopilot is reading it. Bulk changes over 20 items need the person's confirmation. Approvals only happen when asked, and AI-created items stay suggestions, so the brief's sign-off rule still holds.

83. **The conversation history is append-only,** as the current Claude API requires for its thinking blocks. The system prompt (instructions, job, memories) and the tool list are fixed when a session starts. The job's live state goes into each new user message instead. Messages are stored and replayed exactly as received. A long conversation (about 100k tokens) is summarised into a fresh session. As a safety net, a history that somehow fails the check drops the stale thinking (`drop_block`) rather than failing the message. One conversation per job is shared, and a per-job lock stops two people's messages interleaving.

84. **Memory is plain sentences people can read and edit,** scoped to company, client or job. The AI decides when to save one (preferences, rules, corrections), and admins can edit, switch off or add their own. Memories feed both the chat and the autopilot's reads.

85. **Speech uses the browser's built-in recognition** rather than another cloud service, because the Claude API doesn't transcribe audio. It needs HTTPS (the Plesk setup has it) and works in Chrome, Edge and Safari. Chrome and Edge send the audio to Google or Microsoft for recognition. Replies can be read aloud with the browser's speech synthesis, which runs on the device.

## Reports

86. **Labour hours are never invented.** The price book's prebuild labour (through the same mappings as pricing) comes first, then Peak's productivity rates, where the most specific match wins. Anything with neither shows as "no labour rate" and counts toward a visible "missing" total, so a short program is never silently short.

87. **Crew settings are admin settings, not built-in rules.** The defaults (8 h days, 0.5 apprentices per plumber at 50% output, one supervisor per 6 from a crew of 4, PM 10% of field hours) are starting points to change. Apprentices are whole people, never more than the ratio allows.

88. **The program is sequential by stage, in the stage order Peak set.** With a target duration, the crew is the smallest one that gets every stage done in whole days within the target. Builders' programs rarely run that neatly, so any stage's crew or start date can be overridden. The calendar skips weekends, QLD public holidays (Easter computed, Monday substitutes for Christmas and New Year) and the Christmas shutdown.

89. **Material quantities include the waste allowance** and pipe is rounded up to whole stock lengths per material (an admin setting). Fittings come from the fitting rules. With "include items not approved yet" off (the default), only approved quantities count.

90. **Cash flow spreads each stage's sell value evenly over its working days.** That's simple and explainable, good for forecasting progress claims, not a contract claim schedule.

91. **The workforce forecast adds up people per week across won jobs that have a start date** (optionally pending ones too) and compares that with Peak's headcount setting. It's a capacity check, not a roster.

92. **No dual-axis charts.** The cash-flow chart shows monthly value, and the running total is in the table and tooltips instead of on a second axis. Chart colours use a validated colour-blind-safe order, and every chart has a legend and a table next to it.

## Sectors and sales

93. **The sector is a field on every job, not a separate system.** Residential, commercial and maintenance jobs use the same take-off, AI, reports and chat. The sector decides which tab a job is in, its quote-number prefix, who can see it (per-person sector access) and which sales figures it counts in. Jobs that existed before this change are filed as commercial.

94. **A lead is a job with no plans yet,** so nothing has to be copied when the plans arrive. You drop them on the lead.

95. **The pipeline stage is worked out, not stored.** Won, lost or withdrawn comes from the result. Otherwise, a sent date means quote sent; plans, an autopilot run or BOQ lines mean quoting; anything else is a lead. It can't drift from what has actually happened. The dates fill in when the event is recorded and can be corrected. The app refuses a quote dated before its lead, or a result dated before its quote.

96. **Conversion is measured by cohort** (the leads that came in during the period and what became of them), so a period isn't flattered by wins from older leads. The win rate of quotes decided in the period is shown separately. Times are reported as average and median, because one slow job skews the average.

97. **Sales details are picked from lists, not typed,** so the dashboard can group them: type of work per sector, rough size bands, lead source, lost reason. Lists are edited by an admin; a value no longer on a list stays on old jobs and still shows. Client and contact are drop-downs of the ones already used, plus "new". The real quote price is still typed: a band isn't a price.

## Operations

98. **One job record from lead to closed.** A won quote becomes a live job by getting a job number and a work status; nothing is
copied. The estimate, sales fields and delivery records all hang off the same job, so the budget can come straight from the
take-off and the reports can compare estimated to actual.

99. **Everything financial is worked out from the records, never stored as totals.** Labour actual is clocked time × the
person's cost rate (frozen when the time is approved); materials actual is billed POs (the bill), received POs (their value) and
other costs; committed is POs sent but not received. Forecast final cost per category is the larger of its budget and actual +
committed, unless someone sets % complete. So the WIP, the dashboard and Ask Peak can't disagree.

100. **The month-to-date check is pro-rata by working days** (Queensland holidays and the Christmas shutdown from the reports
calendar), against the monthly budget when one is set, otherwise against what the live jobs' remaining budgets say. 5% tolerance,
adjustable.

101. **Clock-ins are made safe for bad reception.** A punch carries the time it happened on the phone and an id; if it can't be
sent it waits on the phone and is replayed later, and the server ignores a repeat of the same id. The server doesn't trust a
phone time more than 24 hours old or in the future.

102. **Switching jobs closes the open entry at the same instant.** A person has at most one open entry, so time is never double
counted or lost.

103. **The plant rules block clocking in rather than just warning,** because that's what was asked, but each rule can be switched
off. Photos are required by the server, not just the form.

104. **The CRM sends nothing until email or SMS is set up;** messages wait in the queue with the reason. Review links are only
offered after a 9 or 10, and only by rules that ask for reviews, so commercial clients never get one.

105. **Supplier products are matched across suppliers by manufacturer code, then barcode, then by a person linking them.** Matching
by description guesses wrong too often to base buying decisions on.

106. **Reece maX is loaded from its price file,** because Reece only gives direct access to approved partner software. Xero
uses its OAuth2 with the granular scopes required for apps made after March 2026; tokens stay on the server.

107. **Ask Peak only reads.** It answers from the same functions the pages use, and its tools respect the person's permissions
(money tools need Finance). Changes are made on the pages, where they're recorded under the person's name.

108. **The app is branded Lorojo** from the supplied logo: black header, orange (#ff6a13) for actions, peach (#ffb27a) as the
second colour, white cards on a warm light grey so tables stay readable in the sun. The logo files are cut from the PDF.
Emails to customers still come from the company name in settings.

109. **People records need their own permission (can_hr),** and HR files are stored apart from company documents, so a person
with Operations access can't open a contract or a warning. Tax file numbers and bank details are not kept: Xero Payroll has them.

110. **Leave balances are worked out, not typed:** opening balance + built up − taken, like the NES. Annual and personal leave
build up per ordinary hour (approved timesheets and paid leave, capped at the normal week); long service builds up with service
and is shown but not usable before 7 years (Queensland). Casuals don't build up annual or personal leave. Xero Payroll stays the
pay run; this is the view the office and the boys use day to day.

111. **Anonymous surveys keep who answered apart from the answers.** Answers store only the month and department, and results
aren't broken down for groups smaller than three.

112. **Board automations run straight after the change that triggers them,** up to three deep (so one can set off another but a
loop can't run away); dated and recurring ones are checked once a minute and fire once per item and day. A failing automation
records its error and never stops the change being saved.

113. **Workbook rows price into the same estimate as the take-off,** with the job's margins, so the quote, the budget, WIP, the
Simpro export and Ask Lorojo all see them. Quantities can follow the take-off live; awarded subcontract quotes become a row
that follows the quote. Without a price book the estimate is priced from the workbook alone.

114. **The tender cash flow** spreads each stage's sell and cost over the activities it belongs to (S-curve by default), claims
monthly, holds retention up to the cap, gets paid after the payment terms and pays suppliers after theirs (labour the same
month), and returns retention half at practical completion and half after 12 months.

115. **Access is per feature, per person, with positions as presets.** A person's level for a feature is what's set on them, else
their position's, else "Can change", so nothing changes until an admin restricts it. The server maps each API path to a feature,
so hiding a tab also stops the data behind it; things every page needs (signing in, settings, notifications, the staff list and
the team directory) stay open. View only means reads are allowed and every change is refused, whatever the page tries.

116. **The program is called Lorojo** (the logo, page titles, the phone app name and the assistant, "Ask Lorojo").

117. **Tool hand-overs need both people.** The register is only right if the person giving and the person getting agree, so a
hand-over waits for the other one to confirm. The exception is taking a tool from the yard, which is immediate. The office can
override anything, and a stocktake sets holders directly.

118. **Geotab is read-only and polled.** Lorojo signs in to MyGeotab with its own read-only user, reads devices, positions and
drivers, and keeps the result for 30 seconds so many people looking at the map make one call. Credentials live only in the
server's `.env`.

119. **Site pre-starts are one per job per day.** The first person fills it in, and everyone else on the job reads it and signs
on. Daily ITP items reset each day; other items stay done once passed. Hold and witness points can't pass without the inspector's
name and signature.

120. **A SWMS on a job is a copy of the template.** Site-specific changes don't touch the library. Any content change bumps the
version, and everyone must sign again.

121. **PDFs are built on the server** (PyMuPDF), so they look the same from every phone. Sharing uses the phone's own share
sheet where it can, so they go out through whatever app people already use.

122. **To-dos gate clocking off, but a reason counts.** People can't always finish what they were given (weather, deliveries,
inspectors), so a task needs to be either ticked or explained, not necessarily done. The explanation goes to whoever set it. The
day that counts is the day they clocked on, so a night shift finishing after midnight is judged on its own list. The automatic
"forgot to clock off" safety net and office timesheet edits aren't blocked.

123. **Who can set someone else's list:** supervisors, foremen, project managers and managers (by trade); office staff with the
To-do lists feature; and anyone for the people who report to them (People → manager). Everyone else keeps only their own list.

124. **Spoken lists are always checked before saving.** Speech-to-text mishears names, so what was said becomes a draft that the
supervisor edits and then saves. Claude does the reading when the AI is connected. A simple word-by-word reader (a name starts
that person's tasks; "and", "then" and commas split them) works without it, so the feature never depends on the AI.

125. **The performance rating is about finishing, with reasons kept separate.** "Couldn't finish" with a reason is honest and
allowed, but it still isn't finished, so it lowers the % finished. The reasons sit next to the number, so management can tell rain
and late deliveries apart from a pattern. Tasks nobody ever ticked or explained (missed clock-offs) are counted on their own.

