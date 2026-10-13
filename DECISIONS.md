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
