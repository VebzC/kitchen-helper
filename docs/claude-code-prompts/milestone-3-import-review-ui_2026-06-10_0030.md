# Claude Code prompt — Milestone 3: import page + review UI (R1–R7)

**Sequencing:** requires M2 (`c199c96`). Verify it's HEAD before starting.

**Scope:** new `kitchen_import.html` served on `GET /import` (A2), implementing the approved review-UI design R1–R7 for the **paste path only** (file drops, URLs, photos are M4/M5); `log_review_event` telemetry (A6/R6); and a `KITCHEN_PORT` env override (decided 2026-06-10) so verification never touches live kitchen devices. **Do not modify `kitchen_display.html` at all this milestone.** All design choices below are decided (R1–R7 approved 2026-05-09 in Notion) — don't re-litigate; stop and ask if you hit something genuinely unspecified. Pause for Vebz's review after verification.

---

## Part 0 — `KITCHEN_PORT` override (test isolation)

In `kitchen_server.py`: port comes from `.env`'s `KITCHEN_PORT` if present and valid, else the existing 8000 default. Add the line (commented out) to `.env.example`. **All verification in this milestone runs on `KITCHEN_PORT=8001`** — during M2 verification a live kitchen device reconnected to the test server on 8000 mid-test; that must not recur. Note the Spotify redirect URI constraint (port 8000 is baked into the registered redirect) — Spotify simply won't be tested on 8001, which is fine; it's out of scope here.

## Part 1 — `kitchen_import.html` (A2: separate file, desktop-only)

Single HTML file, vanilla JS, no build step. Lift the theme as a copy-pasted CSS constants block with a comment naming `kitchen_display.html` as the source of truth — do not create a third shared file. Served by a new `GET /import` route following the existing pattern. If `ANTHROPIC_API_KEY` is blank, the page renders one message: "import disabled — set ANTHROPIC_API_KEY in .env" (A5). If opened at phone width (≤768px): show only "This page is built for desktop — open it on the laptop" (R confirmed, D8). No phone rendering.

### Input stage (D11)

Paste textarea + Import button. Run `detect_input_type` client-side equivalent on submit: show the detected-type indicator with one-tap override — "Treating this as **Paste** — change?" (D11's safety net). If the input detects as a pure URL: still submit honestly as `{type: "url"}`; the server 501s until M4, so map that to a friendly "URL import lands in a later milestone — paste the page text instead" message with the textarea preserved. Empty input: submit disabled (D11 frontend validation).

While parsing: disabled state with elapsed-seconds counter (Opus runs ~20–30s; say so in the UI). `insufficient_content` response → the D3 recovery message (paywall guidance: paste text / screenshot / log in) with the original input preserved.

## Part 2 — review surface (R1–R7)

Three-column landscape layout (R: ~700/700/350 at 1920px; source and parsed equal, flags sidebar takes the rest).

**Top bar:** editable recipe title + badges (source-type, model, parse-time from the response) + actions: **Discard / Re-parse / Save**.

**Left — source pane (R1):** the pasted text, raw, scrollable, monospace.

**Middle — parsed recipe (the editing surface):**
- Meta fields: yield, servings, times — inline editable.
- Ingredients: grouped list. `display`, `name`, `notes`, `optional`, `group` editable. The structured numerics (`quantity_min/max`, `unit_normalized`) render as a **read-only** small readout next to each ingredient (R open item: click-to-edit deferred until real volume shows it's needed — if a structured numeric is wrong, the recourse is re-parse or a comment, not hand-editing).
- Steps: numbered cards; `text` editable; `kind` toggle (cook/prep); `section` editable; timers shown as chips (not editable this milestone — merge combines them per R3).
- **Split (R3):** click in step text to place the cursor, hit the step's "Split here" button → text divides at cursor into steps N and N+1.
- **Merge (R3):** every step except the first has "Merge with previous" → text appended to previous step, timers and metadata combined. Both buttons always visible (after step 1).
- **Comments box (R2):** dedicated textarea at the bottom of this pane — notes to self, parse feedback, anything. Saved into `metadata.json` (as `comments`) AND logged to telemetry.

**Right — flags sidebar (R2):** all flags grouped by severity, each clickable to scroll-jump to its field. Inline: colored border + small icon on flagged fields.
- **Critical (red, blocks save):** empty title, zero ingredients, zero steps — computed live from the current edit state (this enforces L3 at review time).
- **High (orange):** G2 flags from the response; page-level low-confidence from `pages_processed`.
- **Soft (yellow):** entries in `low_confidence_fields`.
- Editing a flagged field clears its high/soft flag (the human looked at it — that's the gate working).

**Save behavior (R4):** no flags → "Save". Soft only → "Save" (flags recorded in metadata). High present → button reads "Save with N flags" → confirm dialog listing them → save on confirm. Critical → disabled with tooltip naming the failures.

**Re-parse / Discard (R7):** Re-parse re-submits the same input, replaces the parse, no confirm (recoverable). Discard → confirm dialog (irreversible) → back to the input stage, clean.

**Multi-recipe paste (R5):** add an optional `other_recipes_detected` (array of title strings) to the tool-use schema's metadata fields. When non-empty, after Save/Discard show: "Found N more recipe(s) in this paste: <titles> — import next?" → re-submits the same source with an instruction to parse the named next recipe. Sequential, parse-on-demand (saves API calls if Vebz bails after the first).

**Save wiring:** POST the edited state to the existing `/recipes` endpoint as `{recipe, metadata, source_text}`. On success: "Saved — <title> is in the library" + buttons "Import another" / link to the display.

## Part 3 — review telemetry (R6/A6)

On save, append a `review_save` line to `kitchen_import_log.jsonl` via a new `log_review_event` in `kitchen_import.py`:
- `fields_edited`: computed by diffing the original parse against the saved payload (passive layer).
- `wrong_flags`: each field gets a small flag icon the cook can tap to say "Claude got this wrong" without fixing it (explicit layer) — collect the tapped list.
- `comments`: the comments box content (qualitative layer).
- Plus `ts`, `slug`, `g2_flag_count`, `high_flags_acknowledged` (count confirmed through the R4 dialog).

## Part 4 — verification (ALL on `KITCHEN_PORT=8001`)

1. Self-tests still pass; server boots on 8001 with the env var and on 8000 without it.
2. Full happy path in the browser: paste a real recipe → parse → edit one ingredient note + one step text → split a step → merge it back → save → confirm the recipe folder exists, `metadata.json` contains the comment, and the telemetry `review_save` line lists exactly the fields you edited.
3. Flag rendering for all three severities must be visually verified. Critical is easy (delete the title in the editor → save disables). For high/soft, exercise the real path if a parse yields flags; otherwise use a temporary mock harness — any such affordance must be removed or hard-gated before commit.
4. R4 matrix: soft-only saves clean; high shows "Save with N flags" + dialog; critical blocks.
5. Paywall paste → recovery message, input preserved. Pure-URL paste → friendly M4 deferral message.
6. Discard confirms; Re-parse replaces without confirm.
7. Phone-width → desktop-only message. `GET /import` with blank key → disabled message.
8. Regressions: cooking display untouched (`git diff` shows zero changes to `kitchen_display.html`), `/state` and `/recipes` endpoints unchanged, display still works on 8000.
9. Commit: `milestone 3: import page + review UI (R1-R7), review telemetry, KITCHEN_PORT override`.

Report per-check results, screenshots-in-words of the three panes, and anything R1–R7 didn't specify that you had to decide — list those explicitly for Vebz's review. Then stop. M4 (URL + text-file ingestion) comes from Cowork after Vebz has imported a few real recipes through this UI.
