# Claude Code prompt — Milestone 1 final verification (Part 4, steps 3–4)

**Context:** Milestone 1 is implemented and committed (`b9e41ce`). The only outstanding items from `milestone-1-import-foundation_2026-06-09_2136.md` are the two tests that needed a real API key. Vebz has now filled `ANTHROPIC_API_KEY` in `.env`.

**Scope:** verification only. **Make no code changes** unless a test fails — and if one does, report the failure and the proposed fix first; don't fix-and-move-on. Do not touch `kitchen_display.html`, existing endpoints, or state. **Never print the API key or any `.env` value.**

---

## Setup

Start the server (`python3 kitchen_server.py`). If it was already running, note that and use it as-is. Confirm `/import` no longer returns the 503 disabled message.

## Test 1 — real recipe parse

POST a real recipe to the endpoint:

```
curl -s -X POST localhost:8000/import \
  -H "Content-Type: application/json" \
  -d @/tmp/recipe_payload.json
```

Build `/tmp/recipe_payload.json` as `{"type": "paste", "payload": "<recipe text>"}`. For the recipe text, ask Vebz if he has one he wants to import for real; if he doesn't care, use any complete recipe text that exercises: ingredient sub-groups, at least one range quantity ("½ to ¾ tsp"), one dual-unit ingredient ("1½ cups (180g) flour"), a count ingredient ("2 large eggs"), a non-scalable one ("pinch of salt"), a preheat/grease setup paragraph, a multi-action paragraph, a timer range ("bake 35 to 40 minutes"), and a storage/serving line at the end.

**Verify against the decided schema (S1–S11):**

1. `status: "parsed"`, valid JSON back.
2. Dual-unit ingredient → structured fields use the **weight** (S1 weight-first): e.g. `quantity_min: 180, unit_normalized: "g"`, cup measure surviving only in `display`.
3. Range quantity → `quantity_min` ≠ `quantity_max`, source-faithful `quantity` string intact.
4. "Pinch of salt" → all numeric/unit fields `null`.
5. Setup paragraph → step(s) with `kind: "prep"`; no step has any `kind` other than `cook`/`prep`.
6. Multi-action paragraph → split into multiple steps (cooking-unit granularity per S3).
7. Timer range → `{duration_seconds_min: 2100, duration_seconds_max: 2400}` with a `source_phrase`; state-based cues ("until golden") got NO timer.
8. Storage/serving lines → recipe-level `storage` / `serving_suggestions` fields, NOT steps (S7).
9. `g2_flags` present (empty is fine — flags only on real mismatches).
10. One `"event": "parse"` line appended to `kitchen_import_log.jsonl` with `status`, `parse_ms`, `g2_flag_count`.

## Test 2 — paywall simulation

```
curl -s -X POST localhost:8000/import \
  -H "Content-Type: application/json" \
  -d '{"type": "paste", "payload": "Subscribe to read the full recipe. Log in. Join now."}'
```

**Verify:** `status: "insufficient_content"` with a reason — NOT an invented recipe (D3 Layer 2). One corresponding telemetry line logged.

## Report

Show Vebz:
1. The full parsed recipe JSON, **pretty-printed**, with the steps array called out separately so he can judge the step-splitting granularity (this is the S3 review — the one schema decision he approved at only ~75% confidence and wants to sanity-check against real output).
2. Any `g2_flags` and `low_confidence_fields`, verbatim.
3. The two telemetry lines.
4. A one-line per-check pass/fail list for the 10 checks above.

Then stop. Leave the parsed recipe unsaved (persistence is Milestone 2). Restore any state you changed, stop the server if you started it, and don't commit anything — verification produces no code changes.
