# Claude Code prompt — switch RECIPE to two citrus pans (drop pineapple)

**Scope:** edit only the `RECIPE` constant in `kitchen_display.html` (lines ~965–1074). Do not change server code, polling, or any unrelated UI. Do not touch other files.

**Why:** Vebz is baking today (2026-05-12). The current hardcoded RECIPE is 1 citrus pan (blood orange + cara cara) + 1 pineapple pan. He wants both pans to be **pure blood orange** — no cara caras, no pineapple. Each pan uses 4 blood oranges per the reference recipe.

**Decision Vebz already made (do not surface):** Pure blood orange only; cara cara is dropped along with pineapple. Do not propose adding other citrus.

---

## Edits

### 1. `metaLine` (line ~967)

```diff
- metaLine: "Citrus + Pineapple  •  400°F → 350°F  •  Two 8\" pans",
+ metaLine: "Blood Orange  •  400°F → 350°F  •  Two 8\" pans",
```

### 2. Step 1 — "Set up and stage" (lines ~970–979)

Remove the frozen-pineapple line and ingredient.

```diff
-      instruction: "Pull 3 large eggs from the fridge to come to room temp (need 30–60 min). Pull 200–250g frozen pineapple into a colander over a bowl to thaw. Preheat oven to 400°F with oven thermometer in place, center rack (or upper-middle + lower-middle if both 8\" pans don't fit side by side). Oil both pans, line bottoms with parchment rounds, oil the parchment.",
+      instruction: "Pull 3 large eggs from the fridge to come to room temp (need 30–60 min). Preheat oven to 400°F with oven thermometer in place, center rack (or upper-middle + lower-middle if both 8\" pans don't fit side by side). Oil both pans, line bottoms with parchment rounds, oil the parchment.",
       timeNote: "10 min active, then 30+ min wait",
       ingredients: [
         { amount: "3", name: "large eggs" },
-        { amount: "200–250g", name: "frozen pineapple" },
         { amount: "—", name: "olive oil for pans" },
         { amount: "2", name: "parchment rounds" }
       ]
```

### 3. Step 3 — "Slice fruit and prep slurry juices" (lines ~990–1001)

Replace mixed citrus with 8 blood oranges total (4 per pan, per the source recipe). Remove cara caras and the pineapple-draining paragraph. Reserved juice = 2 tbsp.

```diff
       title: "Slice fruit and prep slurry juices",
-      instruction: "Mandoline-slice 2 blood oranges and 2 cara caras paper-thin (1.5–2mm), reserving the ends and removing seeds. Squeeze the reserved ends to get 1 tbsp combined citrus juice. Press the thawed pineapple firmly between paper towels to remove as much liquid as possible — frozen pineapple holds extra water that will make the cake soggy if not drained aggressively. Reserve 1 tbsp of the drained pineapple juice.",
+      instruction: "Mandoline-slice 8 blood oranges paper-thin (1.5–2mm), reserving the ends and removing seeds. Aim for 25–30 paper-thin slices per pan. Squeeze the reserved ends to get 2 tbsp blood orange juice (1 tbsp per pan).",
       timeNote: "15 min active",
       ingredients: [
-        { amount: "2", name: "blood oranges" },
-        { amount: "2", name: "cara caras" },
-        { amount: "—", name: "thawed pineapple, drained hard" },
-        { amount: "1 tbsp", name: "reserved citrus juice" },
-        { amount: "1 tbsp", name: "reserved pineapple juice" }
+        { amount: "8", name: "blood oranges (4 per pan)" },
+        { amount: "2 tbsp", name: "reserved blood orange juice" }
       ]
```

### 4. Step 4 — "Build both upside-down layers" (lines ~1002–1013)

Collapse the two halves into one identical procedure repeated per pan. Sugar total stays 66g (still 33g per pan).

```diff
       title: "Build both upside-down layers",
-      instruction: "FOR THE CITRUS PAN: Whisk 33g sugar into the 1 tbsp citrus juice until smooth, pour into Pan 1, tilt to spread. Arrange blood orange and cara cara slices in concentric overlapping circles, alternating colors. Press gently to seat. FOR THE PINEAPPLE PAN: Whisk 33g sugar into the 1 tbsp pineapple juice until smooth, pour into Pan 2, tilt to spread. Arrange pineapple in a tight overlapping pattern, packing densely with no large gaps.",
+      instruction: "FOR EACH PAN (repeat twice): Whisk 33g sugar into 1 tbsp blood orange juice until smooth, pour into the pan, tilt to spread evenly across the parchment. Arrange blood orange slices in concentric overlapping circles. Press gently to seat. Repeat for the second pan.",
       timeNote: "15 min active",
       ingredients: [
         { amount: "66g", name: "sugar (33g per pan)" },
-        { amount: "1 tbsp", name: "citrus juice" },
-        { amount: "1 tbsp", name: "pineapple juice" },
-        { amount: "—", name: "sliced citrus" },
-        { amount: "—", name: "drained pineapple" }
+        { amount: "2 tbsp", name: "blood orange juice (1 tbsp per pan)" },
+        { amount: "—", name: "sliced blood oranges" }
       ]
```

### 5. Step 10 — "Cool, invert, unmold" (lines ~1058–1062)

Drop the line contrasting pineapple vs. citrus appearance.

```diff
       title: "Cool, invert, unmold",
-      instruction: "Transfer pans to wire racks and cool 15 minutes — set a timer. At 15 min, run a thin knife around the edge of each pan. Place a wire rack on top of each pan and flip in one confident motion (use oven mitts, the pans are hot). Lift the pan straight up, then carefully peel the parchment away from the fruit layer. If a fruit slice sticks to the parchment, gently lift it back onto the cake with a small offset spatula. The pineapple cake will look more rustic than the citrus cake — expected. Cool completely on the racks (45–60 min).",
+      instruction: "Transfer pans to wire racks and cool 15 minutes — set a timer. At 15 min, run a thin knife around the edge of each pan. Place a wire rack on top of each pan and flip in one confident motion (use oven mitts, the pans are hot). Lift the pan straight up, then carefully peel the parchment away from the fruit layer. If a fruit slice sticks to the parchment, gently lift it back onto the cake with a small offset spatula. Cool completely on the racks (45–60 min).",
```

---

## Steps that do NOT change

- Step 2 (orange flavoring liquid) — already common to both pans.
- Step 5 (dry ingredients), Step 6 (eggs+sugar ribbon), Step 7 (stream oil), Step 8 (alternate flour/liquid), Step 9 (divide and bake), Step 11 (wrap and rest). The batter recipe is unchanged.

## Verification

After editing, confirm:
1. No remaining instances of "pineapple", "Pineapple", "cara cara", or "Cara Cara" anywhere in the RECIPE block (grep the file).
2. The RECIPE constant still parses as valid JS (open the file in the browser locally and confirm it loads — or just `node -e` parse-check).
3. Total fruit count in step 3 is 8 blood oranges (4 per pan).
4. Total reserved blood orange juice is 2 tbsp.
5. metaLine reads "Blood Orange  •  400°F → 350°F  •  Two 8\" pans".

## Out of scope

- Don't refactor the RECIPE shape into JSON files (Option B is separate work).
- Don't touch server, Spotify, timers, layout, or CSS.
- Don't commit — Vebz will review the diff in his editor before saving.
