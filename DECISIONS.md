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
