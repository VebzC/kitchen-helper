# Claude Code prompt — M3.2: step titles, amount-weaving, split/merge action log

**Why:** first batch of real-import feedback (logged in Notion: Import feedback page, items 1–4, all approved by Vebz 2026-06-10). Build now, before the next import session, so new imports get all four improvements.

**Scope:** `kitchen_import.py` (tool schema + system prompt + version stamp), `kitchen_import.html` (title editing + ingredient-ref chips + action log), `kitchen_display.html` (adapter headline logic + per-step ingredient panel — nothing else in that file). Verification on `KITCHEN_PORT=8001`. One commit.

**Current library state:** one recipe (`muhammara-recipe-roasted-red-pepper-dip`). Its saved source is the verification input — it contains the divided-oil case these changes exist for. Vebz re-imports it himself through the UI after this ships; don't auto-save anything (the review gate stays human).

---

## 1. Step `title` field (Import feedback #1)

- **Tool schema:** each step gains optional `title`: a 3–6 word imperative summary of the step ("Roast the peppers", "Blend into a paste"). The schema description must demand a *summary*, never a copy or truncation of the step text, ≤ ~40 chars.
- **System prompt:** instruct Claude to write one per step.
- **Version stamp:** `parse_with_claude` now stamps `schema_version = "1.1"` (code-owned, same as before). Anything reading recipes treats `title` as optional regardless of version — 1.0 files must keep working everywhere.
- **Review UI:** title renders as a small editable input at the top of each step card (so bad summaries are fixable at review — re-parse must not be the only recourse). Edits log as `steps[i].title` in `fields_edited`. On **split**, the first half keeps the title, second half gets an empty title (cook writes one or leaves blank). On **merge**, keep the surviving (previous) step's title.
- **Display adapter (`kitchen_display.html`):** headline = `title` when present and non-empty; otherwise exactly the current truncation fallback (this keeps 1.0 recipes rendering unchanged). When a title is used as headline, the full step text always renders as body — no more headline-with-no-body for short steps, since the title no longer duplicates the text. Touch only the headline-selection logic.

## 2. Amount-weaving in step text (Import feedback #2)

System-prompt addition to the parse instructions:

- When a step references ingredients from the ingredient list, restate each referenced ingredient's quantity inline in the step text, source-faithful formatting ("3 tbsp extra virgin olive oil", "1 garlic clove", "¼ lb walnuts"). Apply to ALL referenced ingredients that have a quantity in the list.
- **Divided ingredients:** allocate the correct portion per step (muhammara's "4 tbsp olive oil, divided" → "1 tbsp" in the brushing step, "3 tbsp" in the blending step). The allocation must come from the source text's own statements.
- **Hard guard (verbatim in the system prompt):** "Never state a quantity that is not present in, or directly derivable from, the ingredient list and instructions. If the amount for a reference is unclear, leave the ingredient name bare rather than guessing."
- No code-side checking of woven amounts this milestone — G2 stays ingredients-only. (Known accepted risk per the Notion page; review UI is the catch; G3 candidate later.)

## 3. Split/merge action log (Import feedback #3)

- The review page accumulates every split/merge action in order, including pairs that cancel out: `{action: "split", step_index, at_char}` / `{action: "merge", step_index}`.
- Ship the list as `structure_edits` in the existing `review_save` telemetry line (no new endpoint). Empty array when untouched.
- Reset the accumulator on Re-parse and Discard (new parse = new baseline).
- The existing diff-based `fields_edited` behavior stays as is — `structure_edits` is additive.

## 4. Per-step ingredient refs (Import feedback #4 — added 2026-06-10 night)

Vebz: "only the ingredients relevant to that step should be shown on any step." The wall's ingredient panel currently shows the full grouped list on every step for schema recipes (M2's deliberate gap). Close it:

- **Tool schema:** each step gains `ingredient_refs`: array of integers — indices into the recipe-level `ingredients` array, naming which ingredients this step actually uses. Empty array is valid (preheat/rest steps). Claude fills this during the same reasoning pass as amount-weaving (it's already identifying referenced ingredients — record the mapping).
- **Display (`kitchen_display.html`):** for steps with `ingredient_refs`, the ingredient panel shows ONLY the referenced ingredients' `display` strings (skip group sub-headers in this per-step view). Zero refs → keep the panel in place with a dim "no ingredients this step" (layout stability at a glance). Recipes without refs anywhere (1.0 files, legacy RECIPE) → current full-list behavior, byte-identical.
- **Review UI:** each step card shows its refs as small dim chips (ingredient names) so mapping errors are visible at review. Chips removable (×); add via a small picker listing the recipe's ingredient names. Edits log as `steps[i].ingredient_refs` in `fields_edited`. On split, both halves inherit the original refs (cook prunes); on merge, union.
- **Index stability note:** refs are indices; the review UI doesn't reorder or delete ingredients, so indices hold. If that ever changes, refs must be remapped — leave a comment at the ref-handling code saying exactly this.

## 5. Verification (on 8001)

1. Self-tests pass (extend with: schema accepts step with/without `title`; stamp is `"1.1"`).
2. Re-parse the muhammara saved source through `POST /import` (don't save): every step has a title that is a summary, not a prefix of its text; the brushing step says "1 tbsp", the blending step says "3 tbsp" (the divided-oil case); other referenced ingredients carry their amounts; no quantity appears that isn't in the source. `ingredient_refs`: the blending step references the oil + garlic + walnuts + the spice/paste ingredients; the preheat step has none; the cover-and-steam step has none or peppers only.
3. In the review UI: edit a title → `fields_edited` includes `steps[i].title`; split a step then merge it back → `structure_edits` shows both actions while `fields_edited` shows no structure change (the canceling case that motivated this); do a real merge → both layers record it.
4. Display adapter: the existing 1.0 muhammara recipe renders exactly as before (fallback path); load a 1.1 parse (temporary save, then delete, or verify via the review preview if that's faster) and confirm headline = title with full text as body.
5. Regressions: save round-trip, flags, pane layout (M3.1), phone guard, `git diff kitchen_display.html` touches only the headline-selection logic.
6. Commit: `m3.2: step title field + parse-time amount weaving + structure_edits telemetry`.

Report: the muhammara step list (titles + woven amounts) verbatim for Vebz's review, anything unspecified you had to decide, then stop. Vebz re-imports muhammara through the UI to migrate it.
