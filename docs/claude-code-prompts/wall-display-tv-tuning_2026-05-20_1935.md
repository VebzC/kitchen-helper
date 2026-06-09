# Claude Code prompt — tune wall display for 43"/65" landscape TV

**Scope:** Edit only the CSS in `kitchen_display.html`. Do not touch the RECIPE constant, JS, server code, polling, or HTML structure. Do not modify the existing `@media (orientation: portrait)` block, the `@media (orientation: portrait) and (min-width: 900px)` block, or the `@media (max-width: 768px)` (phone) block. Add a new media query branch for TV-scale landscape displays.

**Why:** Vebz is replacing the 27" portrait monitor with a 43" or 65" TCL TV mounted landscape, driven by HDMI from the MacBook. The existing default landscape CSS will render but type is sized for ~MacBook-scale displays at desk distance, not for a TV viewed from 6–12 ft across the kitchen. The portrait monitor path (with its 27" type bumps) won't fire because the TV is landscape.

**Decision Vebz already made:** Landscape orientation. Same MacBook-over-HDMI delivery. Either 43" or 65" — the CSS should work for both with one breakpoint, not two.

---

## Approach

Add one new media query that targets TV-class landscape displays. Most TVs over HDMI from macOS present as 1920×1080 CSS pixels (HiDPI scaling), so use `min-width: 1600px` as the threshold — wide enough to skip MacBook-class displays (≤1440px wide) but to catch any TV at typical settings.

Bump key text and spacing ~1.7× over the current landscape defaults. Don't try to hit perfection on the first pass — Vebz will see it on the actual TV and tune from there.

---

## Add this CSS block

Insert immediately **after** the `@media (orientation: portrait) and (min-width: 900px)` block (around line 670, just before the phone `@media (max-width: 768px)` block). Use this exact structure so it doesn't collide with existing rules:

```css
/* ============================================
   TV-SCALE LANDSCAPE — 43" or 65" TCL mounted on the kitchen wall.
   Triggers at min-width 1600px in landscape so it skips MacBook-class
   displays. Bumps type ~1.7× for cooking-distance reading (6–12 ft).
   Tuning targets: comfortable read from across the kitchen, no need
   to walk up to the screen mid-bake.
   ============================================ */
@media (orientation: landscape) and (min-width: 1600px) {
  .app {
    padding: 28px;
    gap: 24px;
    grid-template-columns: 1fr clamp(440px, 26vw, 640px);
  }

  /* HEADER */
  .title       { font-size: 36px; }
  .meta-line   { font-size: 20px; }
  .clock       { font-size: 28px; }

  /* SPOTIFY WIDGET — bumped so artist/track readable from distance */
  .spotify-widget   { min-width: 380px; max-width: 520px; padding: 14px 22px 14px 14px; }
  .spotify-art      { width: 80px; height: 80px; }
  .spotify-track    { font-size: 22px; }
  .spotify-artist   { font-size: 18px; }

  /* MAIN STEP AREA */
  .main             { padding: 52px; border-radius: 22px; }
  .step-counter     { font-size: 20px; letter-spacing: 0.14em; }
  .step-time        { font-size: 22px; gap: 10px; }
  .suggested-timer-btn {
    padding: 10px 22px;
    border-radius: 12px;
  }
  .step-title       { font-size: 64px; margin-bottom: 32px; line-height: 1.05; }
  .step-instruction { font-size: 36px; line-height: 1.45; padding-right: 14px; }

  /* INGREDIENTS */
  .ingredients-used  { margin-bottom: 32px; padding-bottom: 26px; }
  .ingredients-label { font-size: 18px; margin-bottom: 14px; }
  .ingredient-tag    { font-size: 24px; padding: 10px 18px; border-radius: 10px; }

  /* TIMER PANEL */
  .timer-panel { padding: 28px; gap: 18px; border-radius: 22px; }
}
```

---

## Verification

After the edit:

1. `grep -n "min-width: 1600px" kitchen_display.html` returns exactly one match (the new block).
2. The portrait blocks at lines ~609 and ~632 are unchanged. `grep -c "@media (orientation: portrait)" kitchen_display.html` returns 2.
3. The phone block at `@media (max-width: 768px)` is unchanged.
4. The RECIPE constant is unchanged (no edits below the `<script>` tag).
5. Optional sanity: open the file in a desktop browser at full-window, then resize the window past 1600px wide — at that threshold the type should noticeably jump up. Resize below 1600 and it should return to the current sizing.

---

## What's out of scope for this prompt

- Timer panel internal font sizes — only the panel container is touched. If timers look small on the TV, Vebz will report and we tune in a follow-up.
- The phone layout — untouched. Phone is the remote, TV is the display, no overlap.
- The portrait monitor path — untouched. If Vebz ever puts the 27" back, that still works.
- 4K-native rendering (DPR 1) — if the TV happens to present 3840×2160 instead of 1920×1080, the type will be smaller than intended and Vebz can either change the Mac display setting to "looks like 1920×1080" (recommended) or we add a `min-width: 3000px` super-bump in a follow-up.

---

## After Claude Code applies the edit

Vebz will:
1. Plug in the TV, set the macOS display setting to "looks like 1080p" if the type ends up tiny.
2. Hard-refresh the wall browser (Cmd+Shift+R) — server-served HTML reads from disk per request, no server restart needed.
3. Walk to the counter at typical cooking distance and confirm the step title and instruction text are comfortably readable. Report back what's too small / too big.
