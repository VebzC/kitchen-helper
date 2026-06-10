# Claude Code prompt — M3.1: resizable panes + aligned ingredient grid

**Why:** Vebz's first real session in the review UI (2026-06-10). Two friction points: (1) the parsed-recipe pane is too narrow and can't be widened; (2) ingredient fields (display, name, notes, group, opt, numeric readout) blend into each other — he wants uniform columns he can actually scan.

**Scope:** `kitchen_import.html` ONLY. No server changes, no schema changes, no changes to flags/split/merge/save logic. Verify on `KITCHEN_PORT=8001`. One commit.

---

## 1. Adjustable pane widths

- **Drag divider** between the source pane and the parsed-recipe pane: a slim grab handle (cursor `col-resize`, subtle hover highlight). Dragging reallocates width between those two panes; the flags sidebar keeps its current sizing.
- **Collapse toggle on the source pane** (small `«` button in its header): collapses it to a ~36px rail showing only a `»` to restore — parsed pane gets all the reclaimed width. After a parse, source is mostly reference, so this is the one-click "give me room" move.
- **Persist** divider position and collapsed state in `localStorage` so the layout survives reloads. Sensible floor/ceiling on the divider (source never below ~200px when expanded, parsed never below ~500px).

## 2. Ingredient grid

Replace the current free-flowing ingredient rows with a real grid:

- One **header row** at the top of the ingredients block: `Ingredient (display)` | `Name` | `Notes` | `Group` | `Opt` | `Qty`. Dim caps, same style family as the existing group sub-headers.
- All ingredient rows share one `grid-template-columns` so columns align perfectly down the page. Suggested proportions: display gets the widest column (~2fr), name ~1fr, notes ~1.2fr, group ~0.8fr, opt fixed narrow (checkbox), qty fixed narrow (the read-only dashed readout). Tune to taste at 1920px.
- Group sub-headers ("FOR THE CAKE") stay as full-width rows between grid sections — unchanged behavior, just spanning the grid.
- Subtle vertical column separation (hairline borders or alternating background — pick one, keep it quiet; this is a working surface, not a spreadsheet).
- Flag styling (inline colored borders) and the ⚑ wrong-flag button must survive the restructure — ⚑ can sit at the row's right edge.
- When the pane is narrow (user dragged it small or collapsed nothing), columns compress proportionally; below ~600px pane width, let Notes/Group drop to a second line within the row rather than truncating invisibly.

## 3. Verification (on 8001)

1. Load a saved recipe's parse (or re-import one): columns align across all rows, headers match, groups render between sections.
2. Drag the divider both ways — floors respected; collapse/restore the source pane; reload the page — layout persists.
3. Edit an ingredient field, trip a flag jump from the sidebar (scroll-and-flash still lands on the right row), tap a ⚑ — all unchanged.
4. Full save round-trip still works; telemetry line still has correct `fields_edited` refs (the refs must not change format because of the grid).
5. Phone-width guard and blank-key message unaffected. `git diff` touches only `kitchen_import.html`.
6. Commit: `m3.1: resizable review panes + aligned ingredient grid`.

Report what you tuned (column proportions, floors) and stop.
