# Claude Code prompt — Milestone 2: persistence, library endpoints, recipe picker

**Sequencing:** apply only AFTER the M1 fixes commit (`milestone-1-fixes-g2-schema-version_2026-06-09_2312.md`) has landed. If it hasn't, do that prompt first.

**Scope:** D9 disk persistence, `POST /recipes` save endpoint, `GET /recipes` + `GET /recipes/<slug>`, A3 dropdown picker, A4 state coupling + timer tagging, RECIPE constant demoted to fallback. This milestone makes the **first pipeline edits to `kitchen_display.html`** — additive only, scope guards below are load-bearing. No import page, no review UI (M3), no URL/photo paths (M4/M5). Stop after verification for Vebz's review.

**Decisions encoded (made 2026-06-09, do not re-surface):** save lives at `POST /recipes`, separate from `/import` (parse and persist are different lifecycle stages with different payloads and recovery paths); `recipes/` is git-TRACKED (remove it from `.gitignore` — Vebz wants library history and future remote backup).

---

## Part 1 — `.gitignore`

Remove the `recipes/` line. Everything else stays ignored.

## Part 2 — `save_recipe` in `kitchen_import.py` (D9)

`save_recipe(recipe, metadata, source_bytes, source_ext) -> slug`:

- Layout per D9: `recipes/<slug>/recipe.json`, `recipes/<slug>/source.txt` (paste; other extensions arrive in M4/M5), `recipes/<slug>/metadata.json`.
- Slug: taken from `recipe["slug"]`, re-validated server-side against `^[a-z0-9-]+$` — **reject anything else (this is also the path-traversal guard; a slug containing `/` or `..` must be impossible)**. On collision with an existing folder, append `-2`, `-3`, … and update `recipe["slug"]` to match what was actually saved.
- Re-enforce at the persistence boundary regardless of what the caller sent: L3 null check (non-empty title, ≥1 ingredient, ≥1 step) and `recipe["schema_version"] = "1.0"` — code owns both; reviewed-and-edited payloads can drift.
- `metadata.json` contents: `imported_at` (ISO, set at save time), `model`, `parser_version`, `source_type`, `source_url` (null for paste), `pages_processed`, `low_confidence_fields`, `g2_flags`.
- Self-tests: extend the `__main__` block using a temp directory — save → expected three files; save same slug again → `-2`; malicious slug (`../x`, `a/b`, uppercase) → rejected.

## Part 3 — server endpoints (`kitchen_server.py`)

Follow the existing if/elif route pattern.

- **`POST /recipes`** — body is the `/import` response shape after Vebz's review-edits: `{recipe, metadata, source_text}`. Calls `save_recipe`; returns `{"saved": true, "slug": "<final-slug>"}`. 400 with a one-line reason on validation failure. Until M3's review UI exists, the workflow is: curl `/import`, eyeball the JSON, curl it back to `/recipes` — the human-review gate is procedural for now.
- **`GET /recipes`** — glob `recipes/*/recipe.json`, return `[{slug, title, last_imported}]` (from recipe + metadata), newest-first. Missing/empty `recipes/` → `[]`, never an error.
- **`GET /recipes/<slug>`** — slug regex guard first (400 on fail), then serve the `recipe.json` content; 404 if unknown.
- **`POST /state` whitelist** — add `currentRecipeSlug` to the accepted keys. **Server-enforced invariant (A4):** if an update changes `currentRecipeSlug` to a different value than current, force `currentStep` to 0 in the same update regardless of what the client sent. Timers are never touched by a recipe switch.

## Part 4 — display changes (`kitchen_display.html`)

**Scope guards:** do not modify the three existing media-query blocks (TV landscape ≥1600px, portrait, phone ≤768px) beyond minimal additive styles for the dropdown; do not touch `applyPhoneLayout()`'s existing moves; do not alter the `RECIPE` constant's content; do not change polling cadence.

1. **Recipe loading.** On load, fetch `/recipes`. If `state.currentRecipeSlug` is set and exists, fetch `/recipes/<slug>` and render that; otherwise render the hardcoded `RECIPE` constant exactly as today (fallback — zero recipes saved must look identical to the current app). When polling detects a `currentRecipeSlug` change, fetch and re-render (this is how the phone and wall stay in sync on a switch).
2. **Schema adapter.** Saved recipes use the S1–S11 schema, which differs from the `RECIPE` constant's shape. Write one adapter function that maps schema → the existing render model: `steps[].text` → step instruction; `steps[].section` → rendered as a small banner above the step when it changes from the previous step, suppressed otherwise (S5); step `timers[]` → the existing suggested-timer buttons (label + min seconds; show "35–40 min" style text when min ≠ max); recipe-level `ingredients[]` → the full ingredient list panel, rendered from each ingredient's `display` string, with a sub-heading whenever `group` changes (S2). **Known gap, deliberate:** schema recipes have no per-step ingredient mapping, so any per-step ingredient chips render only for the legacy `RECIPE` fallback. Do not invent a mapping — the future "ingredient highlight on current step" feature owns that.
3. **Picker (A3).** Small dropdown in the wall header listing recipe titles from `/recipes`, plus the fallback entry ("Built-in: <RECIPE title>") when no slug is active. On change: `POST /state` with `{currentRecipeSlug: <slug>, currentStep: 0}`. Hidden entirely when `/recipes` returns `[]`. Keep it visually quiet — the header is ambient display, not chrome.
4. **Timer tagging (A4, the invariant matters).** Every timer gets a `recipeSlug` field set at creation from whatever recipe is active at that moment (`null` when on the fallback RECIPE). **Once set, NOTHING ever rewrites it** — not recipe switches, nothing. Display: the timer chip shows a `(Recipe Title)` suffix only after a second distinct recipe has been used in this page session (track distinct slugs seen since load); before that, tags exist in data but stay hidden.

## Part 5 — verification

1. Module self-tests pass (`python3 kitchen_import.py`).
2. Curl flow: `/import` a paste → `POST /recipes` the result → confirm `recipes/<slug>/` has the three files with correct contents; save again → `<slug>-2`; `GET /recipes` lists both newest-first; `GET /recipes/<slug>` round-trips; unknown slug → 404; `GET /recipes/../etc` and a `..`-bearing slug → 400, and confirm no path outside `recipes/` can be read.
3. Display, zero-recipes state: temporarily move `recipes/` aside → app renders identically to current behavior, no dropdown, no console errors. Restore.
4. Display, with recipes: dropdown appears; picking a recipe renders it (steps, sections, grouped ingredients, timer buttons), step counter resets to 0; second device (or second browser window polling) follows the switch within ~1s.
5. Timer invariant: start a timer on recipe A; switch to recipe B → timer keeps running; its chip now shows "(A's title)"; switch back — tag unchanged.
6. Regression: `/state` sync, Spotify endpoints, blank-key `/import` 503 path, and all three layouts (resize through phone/landscape/TV widths) unchanged. Restore any state you modified to exactly what you found.
7. `git status` → confirm `recipes/` contents are now stageable; `.env`/tokens/state/log still ignored. Commit: `milestone 2: D9 persistence, POST /recipes + library endpoints, picker, A4 state+timer tagging`.

Report: per-check pass/fail, the adapter's mapping summary, and screenshots-in-words of the picker placement. Then stop — Milestone 3 (import page + review UI per R1–R7) comes from Cowork after Vebz reviews, and he'll likely want to import a few real recipes first to feel out the picker.
