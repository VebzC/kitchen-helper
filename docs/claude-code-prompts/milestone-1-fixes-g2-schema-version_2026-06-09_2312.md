# Claude Code prompt — M1 fixes: G2 false positives + schema_version stamping

**Scope:** the two findings from the 2026-06-09 verification run, both approved by Vebz. Edit only `kitchen_import.py` and its self-tests. Do not touch `kitchen_server.py`, `kitchen_display.html`, the tool schema's other fields, or anything else. One commit at the end.

---

## Fix A — `_g2_check` false positives

Two changes, per the root cause you identified:

1. **Clamp the comparison window to the single line containing the matched ingredient name.** The boundary is structural (the newline), not a smaller character count — in an ingredient list, the line IS the ingredient. If the name match spans a wrapped line edge case, use the line where the match starts.
2. **Skip the unit comparison when `unit_normalized` isn't in the synonym map.** Either extend the map to cover all 13 schema units (kg, g, lb, oz, cup, tbsp, tsp, ml, l, fl_oz, count, piece, inch — with common synonyms: cup/cups/c, milliliter/millilitre/ml, liter/litre/l, fluid ounce/fl oz/fl_oz, etc.) — preferred — or, where a unit genuinely has no reliable text form to verify, skip rather than flag. **No-flag-on-uncertainty is the rule:** false positives train the cook to ignore flags, which destroys G2's value.

The quantity comparison logic stays as is — it was correct in both false-positive cases.

## Fix B — stamp `schema_version`

In `parse_with_claude`, after extracting the `record_recipe` tool input: `recipe["schema_version"] = "1.0"`. The code owns this constant — the model's emitted value (string, number, or missing) is overwritten unconditionally. Add a one-line comment: `# schema_version is owned by code, not the model — it marks the recipe.json file-format version, bumped only when the schema design changes.`

---

## Verification

1. **Extend the self-tests** (`if __name__ == "__main__"`) with a G2 regression case that reproduces yesterday's false positive offline — no API call: a multi-line ingredient source text where a `cup`-normalized and an `ml`-normalized ingredient sit adjacent to `tsp`/`g` lines, with correctly parsed values → assert **zero flags**. Keep the existing real-mismatch case (500g parsed as 250g) → assert it **still flags**. Add one case for a unit outside the map → assert no flag.
2. Run `python3 kitchen_import.py` → all self-tests pass.
3. Optional but ideal if Vebz okays the ~1¢: re-run the same lemon-yogurt-loaf paste through `POST /import` and confirm `g2_flags: []` and `schema_version: "1.0"` (string) in the response. If you do this, stop the server after and confirm state is untouched, same as the verification run.
4. `git status` → only `kitchen_import.py` changed. Commit: `m1 fixes: G2 line-clamped window + full unit map, schema_version stamped by code`.

Report the diff summary and self-test output, then stop. Milestone 2 prompt comes from Cowork after Vebz signs off.
