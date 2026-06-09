# Claude Code prompt — Milestone 1: import foundation

**Scope:** four parts, in order: (0) git init, (1) secrets → `.env`, (2) new `kitchen_import.py` module, (3) `POST /import` paste path returning parsed JSON. **No UI work. No disk persistence of recipes (that's Milestone 2). Do not touch `kitchen_display.html`. Do not modify any existing endpoint's behavior.** Stop after Part 4 verification and report — Vebz reviews before Milestone 2.

**Why:** First implementation milestone of the recipe import pipeline. All design decisions are made and documented in Notion (pipeline plan D1–D12, schema S1–S11, architecture A1–A6, review UI R1–R7). This prompt encodes them — do not re-litigate or surface alternatives for anything marked with a decision reference. If you hit something genuinely undecided, stop and ask rather than picking.

**Working style:** after each part, run that part's verification before moving on. Commit at the points marked. If a verification fails, fix before proceeding.

---

## Part 0 — git init (decided 2026-06-09: local only, no remote)

1. Create `.gitignore` at repo root:

```
.env
spotify_tokens.json
kitchen_state.json
kitchen_import_log.jsonl
.DS_Store
__pycache__/
*.pyc
*.bak
recipes/
```

   (`recipes/` is ignored for now — it's runtime data; revisit at Milestone 2 if Vebz wants recipe JSONs versioned.)

2. `git init`. **Do NOT commit yet** — `kitchen_server.py` currently contains live secrets as constants (lines ~45–46). The first commit happens only after Part 1 strips them, so secrets never enter git history.

---

## Part 1 — secrets to `.env` (decision A5, reversed from constants-in-server)

Both Anthropic and Spotify credentials move to a `.env` file. One pattern for all secrets.

1. Safety copy first: `cp kitchen_server.py kitchen_server.py.bak` (gitignored; delete after Part 1 verification passes).

2. Create `.env` at repo root. Move the **values** of `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` from `kitchen_server.py` (lines ~45–46) into it, and add the Anthropic key placeholder:

```
SPOTIFY_CLIENT_ID=<existing value>
SPOTIFY_CLIENT_SECRET=<existing value>
ANTHROPIC_API_KEY=
```

   **Never print the secret values to your transcript, logs, or any other file.** Vebz fills in `ANTHROPIC_API_KEY` manually.

3. Create `.env.example` (committed) with the same keys, all values blank, one comment line pointing to SETUP.md.

4. In `kitchen_server.py`, add a small loader near the top (stdlib only — **no `python-dotenv`**, per A5; the repo has a no-install-step principle):

```python
def load_env(path=os.path.join(SCRIPT_DIR, ".env")):
    """Minimal .env parser: KEY=VALUE lines, # comments and blanks skipped."""
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env
```

   Replace the two Spotify constants with reads from this dict. Add `ANTHROPIC_API_KEY` the same way. Keep the constant *names* identical so the rest of the file doesn't change.

5. **Graceful degradation (A5, load-bearing):**
   - Missing/blank Spotify creds → Spotify features disabled, cooking app works (this matches existing behavior — verify you haven't changed it).
   - Missing/blank `ANTHROPIC_API_KEY` → `POST /import` returns HTTP 503 with body `{"error": "import disabled — set ANTHROPIC_API_KEY in .env"}`. **The cooking display must never break because of a missing import key.**
   - Missing `.env` entirely → server still starts, prints one warning line.

6. Update `SETUP.md`: new ".env setup" section (copy `.env.example` → `.env`, fill keys, where to get each). Adjust the existing docstring in `kitchen_server.py` that says "Edit SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET below" to point at `.env`.

**Verify Part 1:** start the server; confirm (a) display loads at `localhost:8000`, (b) Spotify now-playing works with the migrated creds, (c) `grep -i "client_secret\|sk-" kitchen_server.py` returns no secret values. Delete `kitchen_server.py.bak`. Then make the **initial commit** (entire tree; `.gitignore` keeps `.env` and tokens out — confirm with `git status` before committing).

---

## Part 2 — `kitchen_import.py` (decisions A1, D6, D7, D3 L2+L3, D5 G2, S1–S11, A6)

New file, imported by `kitchen_server.py`. Same process — this is code hygiene, not isolation (D1). The Anthropic call uses the **official `anthropic` SDK** (Vebz's call 2026-06-09 — this is the project's first pip dependency). Everything else stays stdlib.

Dependency setup:
- `pip3 install anthropic` (on newer macOS this may need `--user` or `--break-system-packages` — use whichever works, note which in SETUP.md).
- Create `requirements.txt` at repo root containing the single line `anthropic` (committed).
- Add a "Dependencies" section to SETUP.md with the install command.
- Part 1's `load_env` should additionally export the parsed keys into `os.environ` (without overwriting anything already set) so `kitchen_import.py` can read `ANTHROPIC_API_KEY` without a circular import.

Module-level constants: `MODEL = "claude-opus-4-8"` (D6, updated from Opus 4.7 on 2026-06-09), `PARSER_VERSION = "kitchen_import 0.1"`, `API_TIMEOUT_SECONDS = 120`.

### 2a. `detect_input_type(text=None, files=None) -> str`

D11 rule, text-input portion (file handling lands in later milestones):
- Entire input (after trimming whitespace) is a single URL with no other text → `"url"`
- Otherwise → `"paste"`
- Inline URLs inside prose do NOT make it a URL — the whole input must be the URL.

Pure function. Add 5–6 assert-based self-tests under `if __name__ == "__main__":` (pure URL, URL with query string, prose containing a URL, share-sheet style `"Title | Site https://..."` → paste, whitespace-padded URL, empty string).

### 2b. `parse_with_claude(content, content_type, source_text=None) -> dict`

One SDK call: `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=API_TIMEOUT_SECONDS).messages.create(model=MODEL, max_tokens=8000, system=..., messages=[...], tools=[...], tool_choice={"type": "any"})`. Construct the client lazily inside the function — never at module import time — so the module imports cleanly when the key is blank. Leave the SDK's default retry behavior in place (it retries transient connection/5xx errors); anything that still fails raises, and the endpoint surfaces it (D10: never silently save half-parsed output).

**Two tools, `tool_choice: {"type": "any"}` (D7 + D3 Layer 2):**
1. `record_recipe` — input schema below.
2. `report_insufficient_content` — single required string param `reason`.

**System prompt must include:** "If the input doesn't contain visible ingredients AND visible steps, call report_insufficient_content. Do not invent ingredients, quantities, or steps that aren't in the source."

**`record_recipe` schema** — JSON Schema translation of the approved composite (S1–S11). Field-by-field:

Recipe object (this shape becomes `recipe.json` at Milestone 2):
- `schema_version`: const `"1.0"`
- `title`: string, required
- `slug`: string, required — lowercase, dash-separated, derived from title, special chars stripped
- `description`: string or null
- `yield`: string (source-faithful free text, e.g. `"4"`, `"one 8\" cake"`)
- `servings`: number or null (parsed when possible)
- `times`: object — `prep_min`, `cook_min`, `total_min` (numbers or null) + `additional`: array of `{name, min, label_text}` (S9; preserve author's numbers even when they disagree — reconciliation is a display concern)
- `ingredients`: array, required, min 1 — each (S1 hybrid):
  - `display`: string, required — verbatim source render-string
  - `name`: string, required — canonical ingredient name
  - `quantity`: string — source-faithful (`"½ to ¾"`, `"rounded ½"`, may be empty)
  - `unit`: string — source-faithful as written, may be empty
  - `quantity_min`: number or null — `0.5` for `"½"`; null for non-scalable (`"to taste"`, `"pinch"`)
  - `quantity_max`: number or null — equals `quantity_min` when not a range
  - `unit_normalized`: string or null — one of `kg, g, lb, oz, cup, tbsp, tsp, ml, l, fl_oz, count, piece, inch`; null when non-scalable
  - `notes`: string or null — substitutions, "(divided)", footnote pointers
  - `optional`: boolean
  - `group`: string or null (S2 flat-with-group)
  - **Weight-first rule (S1):** when source gives multiple units for one ingredient ("1½ cups (130g) onions"), structured fields use weight (130, `"g"`); other units survive only in `display`/`notes`. Priority: weight > volume > count > null.
- `steps`: array, required, min 1 — each (S3–S6):
  - `text`: string, required — **cooking-unit granularity: one step = one NEXT click.** Split multi-action author paragraphs; best effort, the review UI corrects later (S3)
  - `section`: string or null — author sub-headings like "Make the sauce" (S5; display-only)
  - `kind`: `"cook"` or `"prep"` — preheat/grease/setup actions are steps tagged `prep` (S6). **No `"after"` value exists** (S7)
  - `timers`: array (possibly empty) of `{duration_seconds_min: number, duration_seconds_max: number, label: string, source_phrase: string}` — min == max when not a range; state-based completions ("until golden") get NO timer (S4)
- `serving_suggestions`: string or null (S7 — recipe-level, not steps)
- `storage`: string or null (S7)
- `nutrition`: object or null (S7) — `per_serving: boolean` (load-bearing), named optional number fields `calories, protein_g, carbs_g, fat_g, saturated_fat_g, trans_fat_g, fiber_g, sugar_g, sodium_mg, cholesterol_mg`, plus `other`: open object for niche nutrients (same `_unit` suffix naming)
- `notes`: string or null — recipe-level footnotes

Parse-metadata fields, same tool call, split out by the caller (S10 superset):
- `pages_processed`: array of `{page_index, ingredients_extracted, steps_extracted, confidence, issues}` (D5 Option D; for paste this is a single self-assessment entry)
- `low_confidence_fields`: array of strings — JSON-path-ish field refs Claude isn't sure about

**After the API responds:**

1. If `report_insufficient_content` → return `{"status": "insufficient_content", "reason": ...}`. The endpoint maps this to the user-facing paywall/no-content message (D3).
2. **Layer 3 null check (D3):** title non-empty, ≥1 ingredient, ≥1 step. Include this comment verbatim: `# This null check is a defensive safety net for malformed Claude responses. If logging shows L2's report_insufficient_content path is catching everything reliably, this whole block can be dropped.`
3. **G2 source-text consistency check (D5 G2)** — runs whenever `source_text` is provided (always, for paste). ~30 lines:
   - For each ingredient with a non-null `quantity_min`: locate `name` in the source text (case-insensitive). If the name can't be confidently located, **skip — no flag** (false positives are worse than misses here).
   - Extract quantity tokens near the name; normalize unicode fractions (½ ¾ ⅓ ⅔ ¼ ⅛), ranges ("X to Y", "X–Y", "X-Y"), and unit synonyms (teaspoon/tsp, tablespoon/tbsp, gram/g, kilogram/kg, ounce/oz, pound/lb) before comparing against `quantity_min`/`quantity_max`/`unit_normalized`.
   - Mismatch → append `{"field": "ingredients[i].quantity", "parsed": ..., "source_snippet": ...}` to `g2_flags`.
4. Return `{"status": "parsed", "recipe": {...}, "metadata": {...}, "g2_flags": [...]}` where `metadata` = `{imported_at (ISO), model, parser_version, source_type, source_url: null, pages_processed, low_confidence_fields}` (D9 sidecar shape, persisted at Milestone 2).

### 2c. `log_parse_event(...)` (A6)

Append one JSON line to `kitchen_import_log.jsonl` (repo root, create if missing):

```json
{"event": "parse", "ts": "...", "slug": "...", "source_type": "paste", "model": "claude-opus-4-8", "parse_ms": 4321, "pages_processed": [...], "low_confidence_fields": [...], "g2_flag_count": 0, "status": "parsed"}
```

Also log `insufficient_content` and error outcomes (`"status"` field distinguishes). Append-only, one line per event, never read at runtime. (`log_review_event` arrives with the review UI in Milestone 3 — do not stub it now.)

---

## Part 3 — `POST /import` endpoint (decision D2: single endpoint, typed envelope)

In `kitchen_server.py`'s `do_POST` if/elif chain (follow the existing pattern exactly):

- Body: JSON `{"type": "paste", "payload": "<raw recipe text>"}`.
- `type == "paste"` → `kitchen_import.parse_with_claude(payload, "paste", source_text=payload)` → return its result as JSON (200). Log via `log_parse_event` on every outcome.
- `type` in `{"url", "photos", "pdf", "file"}` → 501 `{"error": "this input type lands in a later milestone"}`.
- Anything else / malformed JSON / empty payload → 400 with a one-line reason.
- Blank `ANTHROPIC_API_KEY` → 503 per Part 1.5.
- API timeout or non-200 from Anthropic → 502 `{"error": "parse failed: <short reason>", "retryable": true}` (D10 — surface, never half-save).

Import the module defensively: if `import kitchen_import` fails at startup (most likely cause: `anthropic` not installed), print a warning and disable `/import` (503 with `{"error": "import disabled — run: pip3 install anthropic"}`) — **the cooking server must still boot** (D1's framing: import bugs must not take down dinner).

**Note:** parsed recipes are NOT saved to disk in this milestone. `POST /import` is parse-and-return; persistence (D9 per-recipe folders) is Milestone 2, the review-gated save flow is Milestone 3.

---

## Part 4 — verification

1. `python3 kitchen_import.py` → self-tests pass.
2. Start server with blank `ANTHROPIC_API_KEY` → `curl -X POST localhost:8000/import -d '{"type":"paste","payload":"x"}'` → 503, display still loads, Spotify still works.
3. With a real key (Vebz fills `.env` and confirms — **do not ask him to paste the key into chat**): curl the endpoint with a real pasted recipe (ask Vebz for one, or use any public-domain recipe text with ranges, sub-groups, and a timer phrase). Confirm: valid JSON back, ingredients carry structured numerics, weight-first applied where source had dual units, steps split at cooking-unit granularity with `kind` tags, timers extracted with `source_phrase`, one line appended to `kitchen_import_log.jsonl`.
4. Paywall simulation: `{"type":"paste","payload":"Subscribe to read the full recipe. Log in. Join now."}` → `insufficient_content`, not an invented recipe.
5. Regression: `/state` GET+POST still work (poll from a second browser tab and confirm step sync), display renders, Spotify transport works.
6. `git status` → confirm `.env`, `spotify_tokens.json`, `kitchen_state.json`, `kitchen_import_log.jsonl` are not staged. Commit: `milestone 1: .env migration + kitchen_import.py + POST /import paste path`.

Report results and stop. Milestone 2 (disk persistence per D9, `GET /recipes`, `GET /recipes/<slug>`, recipe picker, `currentRecipeSlug` state) starts only after Vebz reviews.
